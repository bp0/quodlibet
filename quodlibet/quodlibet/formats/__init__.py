# -*- coding: utf-8 -*-
# Copyright 2004-2005 Joe Wreschnig, Michael Urman
#           2012 Christoph Reiter
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as
# published by the Free Software Foundation

import sys

from quodlibet.util.importhelper import load_dir_modules
from quodlibet import util
from quodlibet import const
from quodlibet.util.dprint import print_w
from quodlibet.const import MinVersions

mimes = set()
_infos = {}
modules = []
names = []
types = []
_extensions = ()


def init():
    global mimes, _infos, modules, names, _extensions

    import mutagen

    MinVersions.MUTAGEN.check(mutagen.version)

    base = util.get_module_dir()
    load_pyc = util.is_windows() or util.is_osx()
    formats = load_dir_modules(base,
                               package=__package__,
                               load_compiled=load_pyc)

    for format in formats:
        name = format.__name__

        for ext in format.extensions:
            _infos[ext] = format.info

        types.extend(format.types)

        if format.extensions:
            for type_ in format.types:
                mimes.update(type_.mimes)
                names.append(type_.format)
            modules.append(name.split(".")[-1])

        # Migrate pre-0.16 library, which was using an undocumented "feature".
        sys.modules[name.replace(".", "/")] = format
        # Migrate old layout
        if name.startswith("quodlibet."):
            sys.modules[name.split(".", 1)[1]] = format

    modules.sort()
    names.sort()

    # This can be used for the quodlibet.desktop file
    desktop_mime_types = "MimeType=" + \
        ";".join(sorted({m.split(";")[0] for m in mimes})) + ";"
    print_d(desktop_mime_types)

    if not _infos:
        raise SystemExit("No formats found!")

    _extensions = tuple(_infos.keys())


def MusicFile(filename):
    """Returns a AudioFile instance or None"""

    lower = filename.lower()
    for ext in _extensions:
        if lower.endswith(ext):
            try:
                return _infos[ext](filename)
            except:
                print_w("Error loading %r" % filename)
                if const.DEBUG:
                    util.print_exc()
                return
    else:
        print_w("Unknown file extension %r" % filename)
        return


def filter(filename):
    """Returns true if the file extension is supported"""

    return filename.lower().endswith(_extensions)


from ._audio import PEOPLE, AudioFile, DUMMY_SONG, decode_value
from ._image import EmbeddedImage, APICType

AudioFile
EmbeddedImage
DUMMY_SONG
PEOPLE
decode_value
APICType
