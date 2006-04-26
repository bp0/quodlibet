# Copyright 2005 Joe Wreschnig
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as
# published by the Free Software Foundation
#
# $Id$

import sys
import random
import locale
import time
import datetime

import gobject
import gtk
import pango

import qltk
import player
import util

from library import library
from parse import Query
from qltk.properties import SongProperties
from qltk.information import Information
from qltk.views import AllTreeView
from util import tag
from util.uri import URI

if sys.version_info < (2, 4): from sets import Set as set

OFF, SHUFFLE, WEIGHTED, ONESONG = range(4)

class PlaylistMux(object):

    def __init__(self, watcher, q, pl):
        self.q = q
        self.pl = pl
        watcher.connect('song-started', self.__check_q)

    def __check_q(self, watcher, song):
        if song is not None:
            iter = self.q.find(song)
            if iter: self.q.remove(iter)
            self.q.go_to(None)

    def get_current(self):
        if self.q.current is not None: return self.q.current
        else: return self.pl.current

    current = property(get_current)

    def next(self):
        if self.q.is_empty():
            self.pl.next()
            self.q.sourced = False
            self.pl.sourced = True
        elif self.q.current is None:
            self.q.next()
            self.q.sourced = True
            self.pl.sourced = False

    def next_ended(self):
        if self.q.is_empty():
            self.pl.next_ended()
            self.q.sourced = False
            self.pl.sourced = True
        elif self.q.current is None:
            self.q.next()
            self.q.sourced = True
            self.pl.sourced = False

    def previous(self):
        self.pl.previous()

    def go_to(self, song):
        self.pl.go_to(song)
        self.q.go_to(None)

    def reset(self):
        self.pl.reset()
        self.q.go_to(None)
        if not self.pl.is_empty():
            self.pl.go_to(self.pl.get_iter((0,)))

    def enqueue(self, songs):
        for song in songs: self.q.append(row=[song])

class PlaylistModel(gtk.ListStore):
    order = OFF
    repeat = False
    sourced = False
    __iter = None
    __old_value = None
    __sig = None

    __gsignals__ = {
        'songs-set': (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, ())
        }

    def __init__(self):
        super(PlaylistModel, self).__init__(object)
        self.__played = []

    def set(self, songs):
        if self.__sig is not None:
            gobject.source_remove(self.__sig)
            self.__sig = None

        oldsong = self.current
        if oldsong is None: oldsong = self.__old_value
        else: self.__old_value = oldsong
        self.__played = []
        self.__iter = None
        self.clear()
        songs = songs[:]
        if self.__set_idle(oldsong, songs):
            self.__sig = gobject.idle_add(self.__set_idle, oldsong, songs)

    def __set_idle(self, oldsong, songs):
        to_add = songs[:100]
        del(songs[:100])
        for song in to_add:
            iter = self.append(row=[song])
            if song == oldsong:
                self.__iter = iter
        if songs: return True
        else:
            if self.__iter is not None:
                self.__old_value = None
            self.__sig = None
            self.emit('songs-set')
            return False

    def remove(self, iter):
        if self.__iter and self[iter].path == self[self.__iter].path:
            self.__iter = self.iter_next(iter)
        super(PlaylistModel, self).remove(iter)

    def get(self):
        return [row[0] for row in self]

    def get_current(self):
        if self.__iter is None: return None
        elif self.is_empty(): return None
        else: return self[self.__iter][0]

    current = property(get_current)

    def get_current_path(self):
        if self.__iter is None: return None
        elif self.is_empty(): return None
        else: return self[self.__iter].path
    current_path = property(get_current_path)

    def get_current_iter(self):
        if self.__iter is None: return None
        elif self.is_empty(): return None
        else: return self.__iter
    current_iter = property(get_current_iter)

    def next(self):
        if self.order in [WEIGHTED, SHUFFLE]:
            self.__next_shuffle()
            return
        
        # If we're empty, the next song is no song.
        # If the current song is the last song,
        #  - If repeat is off, the next song is no song.
        #  - If repeat is on, the next song is the first song.
        # Else, if the current song is no song, the next song is the first.
        # Else, the next song is the next song.
        if self.is_empty(): self.__iter = None
        elif self.__iter is None:
            self.__iter = self.get_iter_first()
        else:
            next = self.iter_next(self.__iter)
            if next is None and self.repeat:
                self.__iter = self.get_iter_first()
            else: self.__iter = next

    def next_ended(self):
        if self.order != ONESONG: self.next()
        elif not self.repeat: self.__iter = None

    def __next_shuffle(self):
        if self.__iter is not None:
            self.__played.append(self[self.__iter].path[0])

        if self.order == SHUFFLE: self.__next_shuffle_regular()
        elif self.order == WEIGHTED: self.__next_shuffle_weighted()
        else: raise ValueError("Invalid shuffle %d" % self.order)

    def __next_shuffle_regular(self):
        played = set(self.__played)
        songs = set(range(len(self)))
        remaining = songs.difference(played)

        if remaining:
            self.__iter = self[random.choice(list(remaining))].iter
        elif self.repeat and not self.is_empty():
            self.__played = []
            self.__iter = self[random.choice(list(songs))].iter
        else:
            self.__played = []
            self.__iter = None

    def __next_shuffle_weighted(self):
        songs = self.get()
        max_score = sum([song.get('~#rating', 2) for song in songs])
        choice = random.random() * max_score
        current = 0.0
        for i, song in enumerate(songs):
            current += song.get("~#rating", 2)
            if current >= choice:
                self.__iter = self.get_iter((i,))
                break

        else: self.__iter = self.get_iter_first()

    def previous(self):
        if self.order in [SHUFFLE, WEIGHTED]:
            self.__previous_shuffle()
            return

        # If we're empty, the last song is no song.
        # Else if the current song is none, the previous is the last.
        # Else the previous song is the previous song.
        if self.is_empty(): self.__iter = None
        elif self.__iter is None:
            self.__iter = self[(len(self) - 1,)].iter
        else:
            newpath = self[self.__iter].path[0] - 1
            self.__iter = self[(max(0, newpath),)].iter

    def __previous_shuffle(self):
        try: path = self.__played.pop(-1)
        except IndexError: pass
        else: self.__iter = self.get_iter(path)

    def go_to(self, song):
        if self.order and self.__iter is not None:
            self.__played.append(self.get_path(self.__iter)[0])

        self.__iter = None
        if isinstance(song, gtk.TreeIter):
            self.__iter = song
            self.sourced = True
        else:
            for row in self:
                if row[0] == song:
                    self.__iter = row.iter
                    self.sourced = True
                    break

    def find(self, song):
        for row in self:
            if row[0] == song: return row.iter
        return None

    def find_all(self, songs):
        return [row.iter for row in self if row[0] in songs]

    def __contains__(self, song): return bool(self.find(song))

    def is_empty(self):
        return not bool(len(self))

    def reset(self):
        self.__played = []
        self.go_to(None)

class SongList(AllTreeView, util.InstanceTracker):
    # A TreeView containing a list of songs.

    headers = [] # The list of current headers.
    star = list(Query.STAR)

    CurrentColumn = None

    class TextColumn(gtk.TreeViewColumn):
        # Base class for other kinds of columns.
        _render = gtk.CellRendererText()

        def _cdf(self, column, cell, model, iter, tag):
            try:
                song = model.get_value(iter, 0)
                cell.set_property('text', song.comma(tag))
            except AttributeError: pass

        def __init__(self, t):
            gtk.TreeViewColumn.__init__(self, tag(t), self._render)
            self.header_name = t
            self.set_sizing(gtk.TREE_VIEW_COLUMN_GROW_ONLY)
            self.set_visible(True)
            self.set_clickable(True)
            self.set_sort_indicator(False)
            self.set_cell_data_func(self._render, self._cdf, t)

    class DateColumn(TextColumn):
        # The '~#' keys that are dates.
        def _cdf(self, column, cell, model, iter, tag):
            try:
                stamp = model.get_value(iter, 0)(tag)
                if not stamp: cell.set_property('text', _("Never"))
                else:
                    date = datetime.datetime.fromtimestamp(stamp).date()
                    today = datetime.datetime.now().date()
                    days = (today - date).days
                    stamp = time.localtime(stamp)
                    if days == 0: rep = time.strftime("%X", stamp).decode(
                        locale.getpreferredencoding())
                    elif days < 7: rep = time.strftime("%A", stamp).decode(
                        locale.getpreferredencoding())
                    else: rep = time.strftime("%x", stamp).decode(
                        locale.getpreferredencoding())
                    cell.set_property('text', rep)
            except AttributeError: pass

    class WideTextColumn(TextColumn):
        # Resizable and ellipsized at the end. Used for any key with
        # a '~' in it, and 'title'.
        _render = gtk.CellRendererText()
        _render.set_property('ellipsize', pango.ELLIPSIZE_END)

        def __init__(self, tag):
            SongList.TextColumn.__init__(self, tag)
            self.set_expand(True)
            self.set_resizable(True)
            self.set_sizing(gtk.TREE_VIEW_COLUMN_FIXED)
            self.set_fixed_width(1)

    class RatingColumn(TextColumn):
        # Render ~#rating directly (simplifies filtering, saves
        # a function call).
        def _cdf(self, column, cell, model, iter, tag):
            try:
                song = model.get_value(iter, 0)
                cell.set_property(
                    'text', util.format_rating(song.get("~#rating", 0.5)))
            except AttributeError: pass

        def __init__(self):
            SongList.TextColumn.__init__(self, "~#rating")
            self.set_sizing(gtk.TREE_VIEW_COLUMN_GROW_ONLY)

            # Neither of TreeViewColumn or CellRendererText is a GTK
            # widget, so we need a new one to use Pango. Lame.
            l = gtk.Label(util.format_rating(1.0))
            # Magic offset constant tested on Sans 10 to Sans 26.
            min_width = l.size_request()[0] + 10
            l.destroy()
            self.set_min_width(min_width)

    class NonSynthTextColumn(WideTextColumn):
        # Optimize for non-synthesized keys by grabbing them directly.
        # Used for any tag without a '~' except 'title'.
        def _cdf(self, column, cell, model, iter, tag):
            try:
                song = model.get_value(iter, 0)
                cell.set_property(
                    'text', song.get(tag, "").replace("\n", ", "))
            except AttributeError: pass

    class FSColumn(WideTextColumn):
        # Contains text in the filesystem encoding, so needs to be
        # decoded safely (and also more slowly).
        def _cdf(self, column, cell, model, iter, tag, code=util.fscoding):
            try:
                song = model.get_value(iter, 0)
                cell.set_property('text', util.unexpand(
                    song.comma(tag).decode(code, 'replace')))
            except AttributeError: pass

    class LengthColumn(TextColumn):
        _render = gtk.CellRendererText()
        _render.set_property('xalign', 1.0)
        def _cdf(self, column, cell, model, iter, tag):
            try:
                song = model.get_value(iter, 0)
                cell.set_property(
                    'text', util.format_time(song.get("~#length", 0)))
            except AttributeError: pass

        def __init__(self, tag="~#length"):
            SongList.TextColumn.__init__(self, tag)
            self.set_alignment(1.0)

    class NumericColumn(TextColumn):
        # Any '~#' keys except dates.
        _render = gtk.CellRendererText()
        _render.set_property('xpad', 12)
        _render.set_property('xalign', 1.0)

    class PatternColumn(WideTextColumn):
        def _cdf(self, column, cell, model, iter, tag):
            try:
                song = model.get_value(iter, 0)
                cell.set_property('text', self.__pattern % song)
            except AttributeError: pass

        def __init__(self, pattern):
            SongList.WideTextColumn.__init__(self, pattern)
            from parse import Pattern
            self.__pattern = Pattern(pattern)

    def Menu(self, header, browser, watcher):
        from qltk.songsmenu import SongsMenu
        songs = self.get_selected_songs()
        if not songs: return

        menu = SongsMenu(watcher, songs, delete=True, accels=self.accelerators)

        can_filter = browser.can_filter

        def Filter(t):
            # Translators: The substituted string is the name of the
            # selected column (a translated tag name).
            b = qltk.MenuItem(
                _("_Filter on %s") % tag(t, True), gtk.STOCK_INDEX)
            b.connect_object('activate', self.__filter_on, t, songs, browser)
            return b

        header = util.tagsplit(header)[0]

        if can_filter("album") or can_filter("artist") or can_filter(header):
            menu.preseparate()

        if can_filter("artist"): menu.prepend(Filter("artist"))
        if can_filter("album"): menu.prepend(Filter("album"))
        if (header not in ["artist", "album"] and can_filter(header)):
            menu.prepend(Filter(header))

        item = gtk.MenuItem(_("_Rating"))
        m2 = gtk.Menu()
        item.set_submenu(m2)
        for i in range(0, int(1.0/util.RATING_PRECISION)+1):
            i *= util.RATING_PRECISION
            itm = gtk.MenuItem("%0.2f\t%s" % (i, util.format_rating(i)))
            m2.append(itm)
            itm.connect_object(
                'activate', self.__set_rating, i, songs, watcher)
        menu.preseparate()
        menu.prepend(item)

        items = browser.Menu(songs, self)
        items.reverse()
        if items:
            menu.preseparate()
            map(menu.prepend, items)

        menu.show_all()
        return menu

    def __init__(self, watcher):
        super(SongList, self).__init__()
        self._register_instance(SongList)
        self.set_model(PlaylistModel())
        self.set_size_request(200, 150)
        self.set_rules_hint(True)
        self.get_selection().set_mode(gtk.SELECTION_MULTIPLE)
        self.set_column_headers(self.headers)
        sigs = [watcher.connect('changed', self.__song_updated),
                watcher.connect('removed', self.__song_removed),
                watcher.connect('paused', self.__redraw_current),
                watcher.connect('unpaused', self.__redraw_current)
                ]
        for sig in sigs:
            self.connect_object('destroy', watcher.disconnect, sig)

        self.connect('button-press-event', self.__button_press, watcher)
        self.connect('key-press-event', self.__key_press, watcher)

        self.disable_drop()
        self.connect('drag-motion', self.__drag_motion)
        self.connect('drag-data-get', self.__drag_data_get, watcher)
        self.connect('drag-data-received', self.__drag_data_received, watcher)

        # Enabling this screws up rating and enqueuing
        #self.set_search_column(0)
        #self.set_search_equal_func(self.__search_func)

        self.accelerators = gtk.AccelGroup()
        key, mod = gtk.accelerator_parse("<alt>Return")
        self.accelerators.connect_group(
            key, mod, 0, lambda *args: self.__song_properties(watcher))
        key, mod = gtk.accelerator_parse("<control>I")
        self.accelerators.connect_group(
            key, mod, 0, lambda *args: self.__information(watcher))
        self.accelerators.connect

    def __search_func(self, model, column, key, iter, *args):
        for column in self.get_columns():
            value = model.get_value(iter, 0)(column.header_name)
            if not isinstance(value, basestring): continue
            elif key in value.lower() or key in value: return False
        else: return True

    def enable_drop(self):
        targets = [("text/x-quodlibet-songs", gtk.TARGET_SAME_APP, 1),
                   ("text/uri-list", 0, 2)]
        self.drag_source_set(
            gtk.gdk.BUTTON1_MASK, targets,
            gtk.gdk.ACTION_COPY|gtk.gdk.ACTION_MOVE)
        self.drag_dest_set(gtk.DEST_DEFAULT_ALL, targets,
                           gtk.gdk.ACTION_COPY|gtk.gdk.ACTION_MOVE)

    def disable_drop(self):
        targets = [("text/x-quodlibet-songs", gtk.TARGET_SAME_APP, 1),
                   ("text/uri-list", 0, 2)]
        self.drag_source_set(
            gtk.gdk.BUTTON1_MASK, targets, gtk.gdk.ACTION_COPY)
        self.drag_dest_unset()

    def __drag_motion(self, view, ctx, x, y, time):
        try: self.set_drag_dest_row(*self.get_dest_row_at_pos(x, y))
        except TypeError:
            if len(self.get_model()) == 0: path = 0
            else: path = len(self.get_model()) - 1
            self.set_drag_dest_row(path, gtk.TREE_VIEW_DROP_AFTER)
        if ctx.get_source_widget() == self: kind = gtk.gdk.ACTION_MOVE
        else: kind = gtk.gdk.ACTION_COPY
        ctx.drag_status(kind, time)
        return True

    def __drag_data_delete(self, view, ctx):
        map(view.get_model(), self.__drag_iters)
        self.__drag_iters = []

    def __drag_data_get(self, view, ctx, sel, tid, etime, watcher):
        model, paths = self.get_selection().get_selected_rows()
        if tid == 1:
            songs = [model[path][0] for path in paths
                     if model[path][0].can_add]
            if len(songs) != len(paths):
                qltk.ErrorMessage(
                    qltk.get_top_parent(self), _("Unable to copy songs"),
                    _("The files selected cannot be copied to other "
                      "song lists or the queue.")).run()
                ctx.drag_abort(etime)
                return
            added = filter(library.add_song, songs)
            filenames = [song("~filename") for song in songs]
            sel.set("text/x-quodlibet-songs", 8, "\x00".join(filenames))
            if added: watcher.added(added)
            if ctx.action == gtk.gdk.ACTION_MOVE:
                self.__drag_iters = map(model.get_iter, paths)
            else: self.__drag_iters = []
        else:
            uris = [model[path][0]("~uri") for path in paths]
            sel.set_uris(uris)
            self.__drag_iters = []

    def __drag_data_received(self, view, ctx, x, y, sel, info, etime, watcher):
        model = view.get_model()
        if info == 1:
            filenames = sel.data.split("\x00")
            move = (ctx.get_source_widget() == view)
        elif info == 2:
            def to_filename(s):
                try: return URI(s).filename
                except ValueError: return None

            filenames = map(to_filename, sel.get_uris())
            move = False
        else:
            ctx.finish(False, False, etime)
            return

        added = []
        for filename in filenames:
            if filename not in library and library.add(filename):
                added.append(library[filename])
        songs = filter(None, map(library.get, filenames))
        if not songs:
            ctx.finish(bool(not filenames), False, etime)
            return

        watcher.added(added)

        try: path, position = view.get_dest_row_at_pos(x, y)
        except TypeError:
            path = max(0, len(model) - 1)
            position = gtk.TREE_VIEW_DROP_AFTER

        if move and ctx.get_source_widget() == view:
            iter = model.get_iter(path) # model can't be empty, we're moving
            if position in (gtk.TREE_VIEW_DROP_BEFORE,
                            gtk.TREE_VIEW_DROP_INTO_OR_BEFORE):
                while self.__drag_iters:
                    model.move_before(self.__drag_iters.pop(0), iter)
            else:
                while self.__drag_iters:
                    model.move_after(self.__drag_iters.pop(), iter)
            ctx.finish(True, False, etime)
        else:
            song = songs.pop(0)
            try: iter = model.get_iter(path)
            except ValueError: iter = model.append(row=[song]) # empty model
            else:
                if position in (gtk.TREE_VIEW_DROP_BEFORE,
                                gtk.TREE_VIEW_DROP_INTO_OR_BEFORE):
                    iter = model.insert_before(iter, [song])
                else: iter = model.insert_after(iter, [song])
            for song in songs:
                iter = model.insert_after(iter, [song])
            ctx.finish(True, move, etime)

    def __filter_on(self, header, songs, browser):
        if not browser or not browser.can_filter(header): return
        if songs is None:
            if player.playlist.song: songs = [player.playlist.song]
            else: return

        values = set()
        if header.startswith("~#"):
            values.update([song(header, 0) for song in songs])
        else:
            for song in songs: values.update(song.list(header))
        browser.filter(header, list(values))

    def __button_press(self, view, event, watcher):
        if event.button != 1: return
        x, y = map(int, [event.x, event.y])
        try: path, col, cellx, celly = view.get_path_at_pos(x, y)
        except TypeError: return True
        if col.header_name == "~#rating":
            song = view.get_model()[path][0]
            l = gtk.Label()
            l.set_text(util.format_rating(util.RATING_PRECISION))
            width = l.size_request()[0]
            l.destroy()
            count = int(float(cellx - 5) / width) + 1
            rating = max(0.0, min(1.0, count * util.RATING_PRECISION))
            if (rating <= util.RATING_PRECISION and
                song["~#rating"] == util.RATING_PRECISION): rating = 0
            self.__set_rating(rating, [song], watcher)

    def __set_rating(self, value, songs, watcher):
        for song in songs: song["~#rating"] = value
        watcher.changed(songs)

    def __key_press(self, songlist, event, watcher):
        if event.string in ['0', '1', '2', '3', '4']:
            rating = min(1.0, int(event.string) * util.RATING_PRECISION)
            self.__set_rating(rating, self.get_selected_songs(), watcher)
        elif event.string in ['Q', 'q']:
            self.__enqueue(self.get_selected_songs(), watcher)

    def __enqueue(self, songs, watcher):
        songs = filter(lambda s: s.can_add, songs)
        if songs:
            from widgets import main
            added = filter(library.add_song, songs)
            main.playlist.enqueue(songs)
            if added: watcher.added(added)

    def __redraw_current(self, watcher, song=None):
        iter = self.model.current_iter
        if iter: self.model.row_changed(self.model.get_path(iter), iter)

    def set_all_column_headers(cls, headers):
        try: headers.remove("~current")
        except ValueError: pass
        cls.headers = headers
        for listview in cls.instances():
            listview.set_column_headers(headers)

        star = list(Query.STAR)
        for header in headers:
            if not header.startswith("~#") and header not in star:
                star.append(header)
        SongList.star = star

    set_all_column_headers = classmethod(set_all_column_headers)

    def get_sort_by(self):
        for header in self.get_columns():
            if header.get_sort_indicator():
                return (header.header_name,
                        header.get_sort_order() == gtk.SORT_DESCENDING)
        else: return "album", False

    def is_sorted(self):
        return max([col.get_sort_indicator() for col in self.get_columns()])

    # Resort based on the header clicked.
    def set_sort_by(self, header, tag=None, order=None, refresh=True):
        if header and tag is None: tag = header.header_name

        for h in self.get_columns():
            if h.header_name == tag:
                if order is None:
                    s = header.get_sort_order()
                    if (not header.get_sort_indicator() or
                        s == gtk.SORT_DESCENDING):
                        s = gtk.SORT_ASCENDING
                    else: s = gtk.SORT_DESCENDING
                else:
                    if order: s = gtk.SORT_DESCENDING
                    else: s = gtk.SORT_ASCENDING
                h.set_sort_indicator(True)
                h.set_sort_order(s)
            else: h.set_sort_indicator(False)
        if refresh: self.set_songs(self.get_songs())

    def set_model(self, model):
        super(SongList, self).set_model(model)
        if model is not None: model.connect('songs-set', self.__songs_set)
        self.model = model

    def get_songs(self):
        try: return self.get_model().get()
        except AttributeError: return [] # model is None

    def set_songs(self, songs, sorted=False):
        model = self.get_model()

        if not sorted:
            tag, reverse = self.get_sort_by()
            if tag == "~#track": tag = "album"
            elif tag == "~#disc": tag = "album"
            elif tag == "~length": tag = "~#length"
            elif tag == "~album~part": tag = "album"

            songs = [(song(tag), song.sort_key, song) for song in songs]
            songs.sort()
            if reverse: songs.reverse()
            songs = [song[2] for song in songs]
        else:
            self.set_sort_by(None, refresh=False)

        for column in self.get_columns():
            column.set_clickable(False)
            column.set_reorderable(False)

        if self.window:
            self.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))

        model.set(songs)

    def __songs_set(self, songlist):
        for column in self.get_columns():
            if column.header_name not in["~current"]:
                column.set_clickable(True)
                column.set_reorderable(True)
        if self.window: self.window.set_cursor(None)

    def get_selected_songs(self):
        model, rows = self.get_selection().get_selected_rows()
        return [model[row][0] for row in rows]

    def __song_updated(self, watcher, songs):
        model = self.get_model()
        for row in model:
            if row[0] in songs: model.row_changed(row.path, row.iter)

    def __song_removed(self, watcher, songs):
        # The selected songs are removed from the library and should
        # be removed from the view.
        map(self.model.remove, self.model.find_all(songs))

    def __song_properties(self, watcher):
        model, rows = self.get_selection().get_selected_rows()
        if rows: songs = [model[row][0] for row in rows]
        else:
            from player import playlist
            songs = [playlist.song]
        SongProperties(watcher, songs)

    def __information(self, watcher):
        model, rows = self.get_selection().get_selected_rows()
        if rows: songs = [model[row][0] for row in rows]
        else:
            from player import playlist
            songs = [playlist.song]
        Information(watcher, songs)

    # Build a new filter around our list model, set the headers to their
    # new values.
    def set_column_headers(self, headers):
        if len(headers) == 0: return
        map(self.remove_column, self.get_columns())

        if self.CurrentColumn is not None:
            self.append_column(self.CurrentColumn())

        for i, t in enumerate(headers):
            if t in ["tracknumber", "discnumber"]:
                column = self.TextColumn(t)
            elif t in ["~#added", "~#mtime", "~#lastplayed", "~#laststarted"]:
                column = self.DateColumn(t)
            elif t in ["~length", "~#length"]: column = self.LengthColumn()
            elif t in ["~rating", "~#rating"]: column = self.RatingColumn()
            elif t.startswith("~#"): column = self.NumericColumn(t)
            elif t in ["~filename", "~basename", "~dirname"]:
                column = self.FSColumn(t)
            elif "~" not in t and t != "title":
                column = self.NonSynthTextColumn(t)
            elif t.startswith("<"):
                column = self.PatternColumn(t)
            else: column = self.WideTextColumn(t)
            column.connect('clicked', self.set_sort_by)
            column.set_reorderable(True)
            self.append_column(column)
