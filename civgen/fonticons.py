"""The game's font icons ([ICON_Faith], [ICON_Strength], ...) as images,
to draw inline in text (the Workshop showcase images, see workshop.py).

Which icon a tag shows comes from the game's own XML: IconTextureAtlases
(a texture split into a grid) and IconDefinitions (a name -> atlas and
index). [ICON_Strength] is the definition named "Strength". The base
game's are in Base/Assets/UI/Icons/FontIcons.xml, the expansions' and
DLCs' in DLC/*/Data/*FontIcons*.xml (loaded after, so they override).

The game ships its textures only cooked into .blp packages; the
uncooked .dds textures are in the "Sid Meier's Civilization VI SDK
Assets" Steam tool (Civ6/pantry/Textures, Civ6/DLC/*/pantry/Textures).
Without them (or the game) there are no icons: get() returns None and
callers drop the tags.
"""

import functools
import glob
import os
import re
import xml.etree.ElementTree as ET

from .util import find_game_dir, steam_libraries

SDK_ASSETS_FOLDER = "Sid Meier's Civilization VI SDK Assets"
ICON_TAG = re.compile(r"\[ICON_([A-Za-z0-9_]+)\]")


def find_sdk_assets():
    """The SDK Assets folder (with Civ6/pantry in it), or None."""
    for lib in steam_libraries():
        path = os.path.join(lib, "steamapps", "common", SDK_ASSETS_FOLDER)
        if os.path.isdir(os.path.join(path, "Civ6", "pantry")):
            return path
    return None


def icon_xml_files(game_dir):
    """The XML files defining icons, in load order: the base game's, then
    the expansions' and DLCs' (scenarios skipped - they redefine icons
    for themselves only). Any icon can be used in text, not only the
    font icons: [ICON_DISTRICT_CAMPUS], [ICON_Favor] (Gathering Storm's
    yields file), ..."""
    files = sorted(glob.glob(os.path.join(game_dir, "Base", "Assets", "UI",
                                          "Icons", "*.xml")))
    for dlc in sorted(glob.glob(os.path.join(game_dir, "DLC", "*"))):
        if "scenario" in os.path.basename(dlc).lower():
            continue
        files += sorted(glob.glob(os.path.join(dlc, "Data", "*Icons*.xml")))
    return [f for f in files if os.path.isfile(f)]


def _rows(root, table):
    """The Row / Replace elements of a table in a GameInfo document."""
    for section in root.iter(table):
        for row in section:
            if row.tag in ("Row", "Replace"):
                yield row.attrib


class FontIcons:
    """Font icons by name. xml_files: see icon_xml_files; texture_dirs:
    folders with the atlases' textures (later ones win)."""

    def __init__(self, xml_files, texture_dirs):
        # atlas name -> {icon size: (filename, per row, per column)} (an
        # atlas comes in several sizes, one texture each)
        self.atlases = {}
        self.icons = {}                 # icon name -> (atlas, index)
        for path in xml_files:
            try:
                root = ET.parse(path).getroot()
            except (OSError, ET.ParseError):
                continue
            for a in _rows(root, "IconTextureAtlases"):
                try:
                    self.atlases.setdefault(a["Name"], {})[
                        int(a.get("IconSize") or 0)] = (
                        a["Filename"], int(a.get("IconsPerRow") or 1),
                        int(a.get("IconsPerColumn") or 1))
                except (KeyError, ValueError):
                    pass
            for d in _rows(root, "IconDefinitions"):
                try:
                    self.icons[d["Name"]] = (d["Atlas"], int(d["Index"]))
                except (KeyError, ValueError):
                    pass
        self.lower = {name.lower(): name for name in self.icons}
        self.textures = {}              # lowercase file name -> path
        for folder in texture_dirs:
            for path in glob.glob(os.path.join(folder, "*.dds")):
                self.textures[os.path.basename(path).lower()] = path
        self._sheets = {}
        self._cache = {}

    def __bool__(self):
        return bool(self.icons and self.textures)

    def _name(self, name):
        if name in self.icons:
            return name
        return self.lower.get(name.lower()) or \
            self.lower.get("icon_" + name.lower())

    def get(self, name, size=None, trim=False):
        """The icon named name (a tag without "ICON_", e.g. "Faith") as an
        RGBA image, scaled to size x size when given; None if unknown or
        its texture is missing. trim: without the cell's transparent
        margin, fitted (aspect kept) into size x size - for drawing in
        text, where the margin would make it look small."""
        key = (name, size, trim)
        if key not in self._cache:
            self._cache[key] = self._load(name, size, trim)
        return self._cache[key]

    def _load(self, name, size, trim):
        from PIL import Image
        name = self._name(name)
        if name is None:
            return None
        atlas_name, index = self.icons[name]
        sizes = self.atlases.get(atlas_name) or {}
        # the smallest size at least as big as wanted (scaled down, not
        # up), else the biggest
        order = sorted(sizes, key=lambda s: (s < (size or 0),
                                             s if s >= (size or 0) else -s))
        for icon_size in order:
            icon = self._cell(sizes[icon_size], index)
            if icon is None:
                continue
            if trim:
                icon = icon.crop(icon.getchannel("A").getbbox())
            if size:
                scale = size / float(max(icon.size))
                icon = icon.resize((max(1, int(round(icon.width * scale))),
                                    max(1, int(round(icon.height * scale)))),
                                   Image.LANCZOS)
            return icon
        return None

    def _cell(self, atlas, index):
        """Cell index of an atlas's texture, or None (no texture, or an
        empty cell)."""
        filename, per_row, per_column = atlas
        if not filename.lower().endswith(".dds"):
            filename += ".dds"
        sheet = self._sheet(filename)
        if sheet is None:
            return None
        w, h = sheet.width // per_row, sheet.height // per_column
        col, row = index % per_row, index // per_row
        if row >= per_column or not (w and h):
            return None
        icon = sheet.crop((col * w, row * h, (col + 1) * w, (row + 1) * h))
        if icon.getchannel("A").getbbox() is None:
            return None
        return icon

    def _sheet(self, filename):
        from PIL import Image
        key = filename.lower()
        if key not in self._sheets:
            path = self.textures.get(key)
            sheet = None
            if path:
                try:
                    with Image.open(path) as img:
                        sheet = img.convert("RGBA")
                except Exception:           # unreadable / unsupported DDS
                    sheet = None
            self._sheets[key] = sheet
        return self._sheets[key]


def texture_dirs(sdk_dir):
    """The SDK Assets' texture folders, base game first."""
    civ6 = os.path.join(sdk_dir, "Civ6")
    return [os.path.join(civ6, "pantry", "Textures")] + sorted(
        glob.glob(os.path.join(civ6, "DLC", "*", "pantry", "Textures")))


@functools.lru_cache(maxsize=1)
def default_icons():
    """FontIcons from the installed game and SDK Assets (empty - falsy -
    without either)."""
    game, sdk = find_game_dir(), find_sdk_assets()
    if not (game and sdk):
        return FontIcons([], [])
    return FontIcons(icon_xml_files(game), texture_dirs(sdk))
