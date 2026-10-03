#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Civ 6 Alternate Leader Mod Generator
====================================

A tkinter GUI that generates "alternate leaders for existing civilizations"
mods for Sid Meier's Civilization VI. One mod ("pack") can contain any
number of new leaders; each generated leader:

  * inherits the original leader's ability (traits, name and description)
    and AI agenda - or uses another of the game's agendas, optionally
    under a new name and description,
  * shares the civilization's uniques automatically,
  * and has customizable cosmetics: name, loading bio, quote, all
    diplomacy lines, Civilopedia page, leader icon, loading/diplomacy
    images and leader colors.

Work-in-progress projects can be saved and re-opened (pickled to
*.altleader files), so you can build a pack over several sessions.

Usage:
    python alt_leader_generator.py

Optional dependency:
    Pillow (pip install Pillow) - auto-converts your chosen icon image
    into the .dds files the game's IconTextureAtlases reference.
    Without it, icon art falls back to the inherited leader's icon
    (or hand-converted .dds files).

Data source (recommended):
    Click "Load from game cache" and point it at the game's
    DebugGameplay.sqlite (auto-detected from the usual locations). This
    fills the civ/leader dropdowns with the real content of YOUR install,
    including DLC and other mods, and pre-fills inherited fields.

Note:
    Project files are Python pickles. Only open *.altleader files you
    or people you trust created - pickle can execute arbitrary code.
"""

import copy
import json
import os
import pickle
import re
import shutil
import sqlite3
import struct
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import xml.etree.ElementTree as ET
import zipfile

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ICON_SIZES = [32, 45, 48, 50, 55, 64, 80, 256]

PROJECT_MAGIC = "civ6-alt-leader-generator-project"
PROJECT_VERSION = 2              # 2: icon crops are in fitted-portrait pixels

# Used only when no game cache is loaded. The dropdowns are editable, so
# anything missing here can be typed by hand (or loaded from the cache).
FALLBACK_DATA = {
    "CIVILIZATION_AMERICA": ["LEADER_T_ROOSEVELT"],
    "CIVILIZATION_ARABIA": ["LEADER_SALADIN"],
    "CIVILIZATION_AUSTRALIA": ["LEADER_JOHN_CURTIN"],
    "CIVILIZATION_AZTEC": ["LEADER_MONTEZUMA"],
    "CIVILIZATION_BRAZIL": ["LEADER_PEDRO"],
    "CIVILIZATION_CHINA": ["LEADER_QIN_SHI_HUANG"],
    "CIVILIZATION_EGYPT": ["LEADER_CLEOPATRA"],
    "CIVILIZATION_ENGLAND": ["LEADER_VICTORIA"],
    "CIVILIZATION_FRANCE": ["LEADER_CATHERINE_TO_US"],
    "CIVILIZATION_GERMANY": ["LEADER_BARBAROSSA"],
    "CIVILIZATION_GREECE": ["LEADER_PERICLES", "LEADER_GORGO"],
    "CIVILIZATION_INDIA": ["LEADER_GANDHI", "LEADER_CHANDRAGUPTA"],
    "CIVILIZATION_JAPAN": ["LEADER_HOJO"],
    "CIVILIZATION_KHMER": ["LEADER_JAYAVARMAN"],
    "CIVILIZATION_KONGO": ["LEADER_MVEMBA"],
    "CIVILIZATION_KOREA": ["LEADER_SEONDEOK"],
    "CIVILIZATION_NORWAY": ["LEADER_HARALD_HARDDRADA"],
    "CIVILIZATION_ROME": ["LEADER_TRAJAN"],
    "CIVILIZATION_RUSSIA": ["LEADER_PETER"],
    "CIVILIZATION_SCYTHIA": ["LEADER_TOMYRIS"],
    "CIVILIZATION_SPAIN": ["LEADER_PHILIP"],
    "CIVILIZATION_SUMERIA": ["LEADER_GILGAMESH"],
}


def find_game_cache():
    """Return the most likely location of DebugGameplay.sqlite, if any."""
    home = os.path.expanduser("~")
    docs = [os.path.join(home, "Documents")]
    onedrive = os.path.join(home, "OneDrive", "Documents")
    if os.path.isdir(onedrive):
        docs.insert(0, onedrive)
    candidates = []
    for d in docs:
        candidates.append(os.path.join(
            d, "My Games", "Sid Meier's Civilization VI", "Cache",
            "DebugGameplay.sqlite"))
    appdata = os.path.join(home, "AppData", "Local", "Firaxis Games",
                           "Sid Meier's Civilization VI", "Cache",
                           "DebugGameplay.sqlite")
    candidates.append(appdata)
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def sql_str(value):
    """Escape a value for a single-quoted SQL string literal."""
    return "'" + str(value).replace("'", "''") + "'"


def xml_escape(value):
    """Escape a string for use as XML text (modinfo Name/Description)."""
    return (str(value)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))


def clean_prefix(prefix):
    """Project type prefix as used in type names, e.g. 'rfvs' -> 'RFVS'."""
    return re.sub(r"[^0-9A-Za-z]+", "_", prefix or "").strip("_").upper()


def slug_for_name(name, prefix=""):
    """Turn a display name into a Civ 6 type slug, e.g. 'Jeanne d'Arc'
    -> 'LEADER_JEANNE_D_ARC', or with prefix 'RFVS' ->
    'LEADER_RFVS_JEANNE_D_ARC'. The prefix keeps the types (and every
    icon, texture and text tag derived from them) from colliding with
    other mods' leaders."""
    base = re.sub(r"[^0-9A-Za-z]+", "_", name or "").strip("_").upper()
    if not base:
        return ""
    prefix = clean_prefix(prefix)
    if prefix and base != prefix and not base.startswith(prefix + "_"):
        base = prefix + "_" + base
    return "LEADER_" + base


def type_display_name(type_name):
    """Readable stand-in for a type whose text is not in the cache, e.g.
    'AGENDA_ANGEVIN_EMPIRE' -> 'Angevin Empire'."""
    return type_name.split("_", 1)[-1].replace("_", " ").title()


def safe_folder_name(name):
    """Filesystem-safe folder name for a mod pack."""
    base = re.sub(r"[^0-9A-Za-z]+", "_", name or "").strip("_")
    return base or "AltLeaderPack"


# ---------------------------------------------------------------------------
# Leader colors (from the game's XML files - the debug cache has none)
# ---------------------------------------------------------------------------

GAME_FOLDER = "Sid Meier's Civilization VI"
WORKSHOP_APP_ID = "289070"


def find_game_dir():
    """The Civ VI install folder (Steam or Epic), or None."""
    candidates = [os.path.join(lib, "steamapps", "common", GAME_FOLDER)
                  for lib in steam_libraries()]
    candidates.append(r"C:\Program Files\Epic Games\SidMeiersCivilizationVI")
    return next((c for c in candidates
                 if os.path.isdir(os.path.join(c, "Base"))), None)


def xml_under(folder, exts=(".xml",)):
    """Every file below folder with one of the extensions, sorted."""
    out = []
    for root, _dirs, files in os.walk(folder):
        out += [os.path.join(root, f) for f in files
                if f.lower().endswith(exts)]
    return sorted(out)


def text_files(game_dir):
    """XML and SQL files that may define text, in roughly the game's load
    order (later files override earlier ones): DLC and expansions (not
    scenarios), Steam Workshop mods and local mods. The base game's text
    is always in the localization cache, so it is left out."""
    exts = (".xml", ".sql")
    files = []
    if game_dir:
        dlc = os.path.join(game_dir, "DLC")
        if os.path.isdir(dlc):
            for name in sorted(os.listdir(dlc)):
                if "scenario" not in name.lower():
                    files += xml_under(os.path.join(dlc, name, "Text"), exts)
        files += xml_under(os.path.join(
            os.path.dirname(os.path.dirname(game_dir)), "workshop",
            "content", WORKSHOP_APP_ID), exts)
    files += xml_under(GeneratorApp.default_out_dir(), exts)
    return files


TEXT_TABLES = ("EnglishText", "BaseGameText", "LocalizedText")


def load_english_texts(files):
    """{Tag: English text} from the EnglishText / BaseGameText rows and
    en_US LocalizedText rows the files define."""
    texts = {}
    for path in files:
        try:
            with open(path, "rb") as fh:
                raw = fh.read()
        except OSError:
            continue
        if (b"EnglishText" not in raw and b"BaseGameText" not in raw
                and not (b"LocalizedText" in raw and b"en_US" in raw)):
            continue                    # no English text in this file
        if path.lower().endswith(".sql"):
            _load_sql_texts(raw, texts)
        else:
            _load_xml_texts(raw, texts)
    return texts


def _load_sql_texts(raw, texts):
    """Text rows of a mod's .sql file: its statements run one by one
    against in-memory copies of the text tables (statements on other
    tables fail and are skipped)."""
    db = sqlite3.connect(":memory:")
    # the file is a stranger's code: no attaching (= writing) other files
    denied = (sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH,
              sqlite3.SQLITE_PRAGMA)
    db.set_authorizer(lambda action, *_: sqlite3.SQLITE_DENY
                      if action in denied else sqlite3.SQLITE_OK)
    for table in TEXT_TABLES:
        lang = "Language TEXT DEFAULT 'en_US', " \
            if table == "LocalizedText" else ""
        key = "Language, Tag" if lang else "Tag"
        db.execute("CREATE TABLE {} ({}Tag TEXT NOT NULL, Text TEXT, "
                   "Gender TEXT, Plurality TEXT, PRIMARY KEY ({}))"
                   .format(table, lang, key))
    statement = ""                      # (a ';' may be inside a string)
    for part in raw.decode("utf-8", errors="replace").split(";"):
        statement += part + ";"
        if sqlite3.complete_statement(statement):
            try:
                db.execute(statement)
            except sqlite3.Error:
                pass
            statement = ""
    for tag, text in db.execute(
            "SELECT Tag, Text FROM EnglishText UNION ALL "
            "SELECT Tag, Text FROM BaseGameText UNION ALL "
            "SELECT Tag, Text FROM LocalizedText WHERE Language='en_US'"):
        if tag and text:
            texts[tag] = text
    db.close()


def _load_xml_texts(raw, texts):
    """Text rows of an XML file (<Row> or <Replace>, as elements or
    attributes)."""
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return
    for table in root:
        if table.tag not in TEXT_TABLES:
            continue
        for row in table:
            if row.tag not in ("Row", "Replace"):
                continue
            fields = dict(row.attrib)
            fields.update({c.tag: c.text or "" for c in row})
            if (table.tag == "LocalizedText"
                    and fields.get("Language", "en_US") != "en_US"):
                continue
            if fields.get("Tag") and fields.get("Text"):
                texts[fields["Tag"]] = fields["Text"]


def color_xml_files(game_dir):
    """XML files that may define colors, in roughly the game's load
    order (later files override earlier ones): the base game, DLC and
    expansions (not scenarios - they recolor leaders for that scenario
    only), Steam Workshop mods and local mods."""
    files = []
    if game_dir:
        files += xml_under(os.path.join(game_dir, "Base", "Assets", "UI",
                                        "Colors"))
        dlc = os.path.join(game_dir, "DLC")
        if os.path.isdir(dlc):
            for name in sorted(os.listdir(dlc)):
                if "scenario" not in name.lower():
                    files += xml_under(os.path.join(dlc, name, "Data"))
        workshop = os.path.join(os.path.dirname(os.path.dirname(game_dir)),
                                "workshop", "content", WORKSHOP_APP_ID)
        files += xml_under(workshop)
    files += xml_under(GeneratorApp.default_out_dir())
    return files


def parse_color(value, colors, depth=0):
    """'r,g,b[,a]' (0-255, or 0-1 floats) or the name of another color
    -> (r, g, b), or None."""
    value = (value or "").strip()
    if value in colors and depth < 10:
        return parse_color(colors[value], colors, depth + 1)
    try:
        parts = [float(p) for p in value.split(",")][:3]
    except ValueError:
        return None
    if len(parts) != 3:
        return None
    if "." in value and all(p <= 1 for p in parts):
        parts = [p * 255 for p in parts]
    return tuple(max(0, min(255, int(round(p)))) for p in parts)


def load_leader_colors(files):
    """{LeaderType: (primary rgb, secondary rgb)} from Colors /
    PlayerColors rows (<Row> or <Replace>, as elements or attributes)."""
    colors, players = {}, {}
    for path in files:
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            if "Colors" not in text:
                continue
            root = ET.fromstring(text.encode("utf-8"))
        except (OSError, ET.ParseError):
            continue
        for table in root:
            if table.tag not in ("Colors", "PlayerColors"):
                continue
            for row in table:
                if row.tag not in ("Row", "Replace"):
                    continue
                fields = dict(row.attrib)
                fields.update({c.tag: (c.text or "").strip() for c in row})
                kind = fields.get("Type")
                if not kind:
                    continue
                if table.tag == "Colors" and fields.get("Color"):
                    colors[kind] = fields["Color"]
                elif table.tag == "PlayerColors" and kind.startswith(
                        "LEADER_"):
                    players[kind] = (fields.get("PrimaryColor"),
                                     fields.get("SecondaryColor"))
    out = {}
    for leader, (primary, secondary) in players.items():
        p, s = parse_color(primary, colors), parse_color(secondary, colors)
        if p and s:
            out[leader] = (p, s)
    return out


# ---------------------------------------------------------------------------
# Game data (from the game's own debug SQLite cache)
# ---------------------------------------------------------------------------

class GameData:
    """Optional wrapper around DebugGameplay.sqlite."""

    def __init__(self):
        self.conn = None
        self.loc_conn = None
        self.file_texts = {}    # Tag -> English text from DLC / mod files
        self.path = None
        self.civ_to_leaders = {}
        self.leader_meta = {}   # LeaderType -> dict of display/meta fields
        self.agendas = {}       # AgendaType -> {"name", "desc", "leaders"}
        self.leader_agenda = {}  # LeaderType -> historical AgendaType
        self.leader_colors = {}  # LeaderType -> (primary rgb, secondary rgb)
        # LeaderType -> [{"type", "name", "desc", "name_tag", "desc_tag"}]
        self.leader_abilities = {}

    # -- helpers -----------------------------------------------------------

    def _query(self, sql, args=()):
        try:
            cur = self.conn.execute(sql, args)
            return cur.fetchall()
        except sqlite3.Error:
            return []

    def _loc(self, tag):
        """Resolve a LOC_ tag to English text if possible."""
        if not tag:
            return None
        for table, extra in (("LocalizedText", " AND Language='en_US'"),
                             ("LocalizedText", ""),
                             ("EnglishText", "")):
            rows = self._query(
                "SELECT Text FROM {} WHERE Tag=?{}".format(table, extra),
                (tag,))
            if rows and rows[0][0]:
                return rows[0][0]
        return None

    # -- loading -----------------------------------------------------------

    def uniques_for(self, civ, leader):
        """Unique units / buildings / districts / improvements of a
        civilization plus those of a leader (via its traits) - the items
        a generated leader inheriting from that leader gets."""
        if not self.conn:
            return []
        traits = ("SELECT TraitType FROM CivilizationTraits "
                  "WHERE CivilizationType=? UNION "
                  "SELECT TraitType FROM LeaderTraits WHERE LeaderType=?")
        items = []
        for table, column in (("Units", "UnitType"),
                              ("Buildings", "BuildingType"),
                              ("Districts", "DistrictType"),
                              ("Improvements", "ImprovementType")):
            items += [r[0] for r in self._query(
                "SELECT {} FROM {} WHERE TraitType IN ({}) ORDER BY 1".format(
                    column, table, traits), (civ, leader))]
        return items

    def loc_text(self, tag):
        """English text of a tag from the game's DebugLocalization.sqlite
        (next to the gameplay cache), or else from the DLC / mod text
        files (the cache lacks most DLC and expansion text), or None."""
        row = None
        if self.loc_conn:
            try:
                row = self.loc_conn.execute(
                    "SELECT Text FROM LocalizedText WHERE Tag=? AND "
                    "Language='en_US'", (tag,)).fetchone()
            except sqlite3.Error:
                pass
        return (row[0] if row and row[0] else None) or \
            self.file_texts.get(tag)

    def load(self, path):
        # (loaded in a worker thread, used from the GUI thread afterwards)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.path = path
        loc = os.path.join(os.path.dirname(path), "DebugLocalization.sqlite")
        self.loc_conn = (sqlite3.connect(loc, check_same_thread=False)
                         if os.path.isfile(loc) else None)
        self.file_texts = load_english_texts(text_files(find_game_dir()))
        self.civ_to_leaders = {}
        self.leader_meta = {}

        for civ, leader in self._query(
                "SELECT CivilizationType, LeaderType FROM CivilizationLeaders"):
            if leader.startswith("LEADER_MINOR_CIV_"):
                continue
            self.civ_to_leaders.setdefault(civ, []).append(leader)

        for (leader,) in self._query("SELECT LeaderType FROM Leaders"):
            if leader.startswith("LEADER_MINOR_CIV_"):
                continue
            meta = {
                "name": None, "sex": None, "icon": None,
                "portrait": None, "portrait_bg": None,
                "load_fg": None, "load_bg": None,
            }
            row = self._query(
                "SELECT Name, Sex FROM Leaders WHERE LeaderType=?",
                (leader,))
            if row:
                meta["name"] = self._loc(row[0][0]) or row[0][0]
                meta["sex"] = row[0][1]
            # Players table (front-end config cached into the debug DB)
            row = self._query(
                "SELECT LeaderIcon, Portrait, PortraitBackground "
                "FROM Players WHERE LeaderType=? LIMIT 1", (leader,))
            if row:
                meta["icon"] = row[0][0]
                meta["portrait"] = row[0][1]
                meta["portrait_bg"] = row[0][2]
            row = self._query(
                "SELECT ForegroundImage, BackgroundImage FROM LoadingInfo "
                "WHERE LeaderType=? LIMIT 1", (leader,))
            if row:
                meta["load_fg"], meta["load_bg"] = row[0][0], row[0][1]
            self.leader_meta[leader] = meta

        # the cache's Colors / PlayerColors tables are empty: colors are
        # loaded by UpdateColors actions straight from the XML files
        self.leader_colors = load_leader_colors(
            color_xml_files(find_game_dir()))

        self.agendas = {}
        self.leader_agenda = {}
        for agenda, name, desc in self._query(
                "SELECT AgendaType, Name, Description FROM Agendas "
                "ORDER BY AgendaType"):
            self.agendas[agenda] = {
                "name": self.loc_text(name) or self._loc(name) or
                        type_display_name(agenda),
                "desc": self.loc_text(desc) or self._loc(desc) or "",
                "leaders": []}
        for leader, agenda in self._query(
                "SELECT LeaderType, AgendaType FROM HistoricalAgendas "
                "ORDER BY LeaderType"):
            self.leader_agenda.setdefault(leader, agenda)
            if agenda in self.agendas:
                self.agendas[agenda]["leaders"].append(leader)

        # Leader abilities: the traits the UI shows. Traits that unlock a
        # unique unit, building etc. are left out - the item names the
        # trait, so a renamed copy (see ability_block) would not unlock it.
        item_traits = set()
        for (table,) in self._query(
                "SELECT name FROM sqlite_master WHERE type = 'table'"):
            if table in ("Traits", "TraitModifiers", "LeaderTraits",
                         "CivilizationTraits", "AgendaTraits") \
                    or table in TRAIT_RULE_TABLES:
                continue
            columns = [r[1] for r in self._query(
                'PRAGMA table_info("{}")'.format(table))]
            if "TraitType" in columns:
                item_traits.update(r[0] for r in self._query(
                    'SELECT TraitType FROM "{}"'.format(table)))
        self.leader_abilities = {}
        for leader, trait, name, desc in self._query(
                "SELECT LeaderType, TraitType, Name, Description "
                "FROM LeaderTraits JOIN Traits USING (TraitType) "
                "WHERE InternalOnly = 0 AND Name IS NOT NULL "
                "ORDER BY LeaderType, TraitType"):
            if trait in item_traits:
                continue
            self.leader_abilities.setdefault(leader, []).append({
                "type": trait,
                "name": self.loc_text(name) or self._loc(name) or
                        type_display_name(trait),
                "desc": self.loc_text(desc) or self._loc(desc) or "",
                "name_tag": name, "desc_tag": desc})

    def city_names(self, civ):
        """English names of a civilization's own (not leader-specific)
        cities, in the game's order; the first one is its usual
        capital."""
        if not self.conn:
            return []
        return [self.loc_text(tag) or self._loc(tag) or tag
                for (tag,) in self._query(
                    "SELECT CityName FROM CityNames WHERE CivilizationType=? "
                    "AND LeaderType IS NULL ORDER BY SortIndex, ID", (civ,))]

    def meta(self, leader_type):
        return self.leader_meta.get(leader_type) or {}

    def historical_agenda(self, leader_type):
        return self.leader_agenda.get(leader_type)

    def abilities(self, leader_type):
        """The leader's ability traits (see leader_abilities), or []."""
        return self.leader_abilities.get(leader_type) or []

    def colors(self, leader_type):
        """(primary rgb, secondary rgb) of a leader, or None."""
        return self.leader_colors.get(leader_type)


# ---------------------------------------------------------------------------
# DDS writing (uncompressed 32-bit RGBA; no external tools needed)
# ---------------------------------------------------------------------------

def write_dds(path, width, height, levels):
    """Write an uncompressed DDS file (32bpp RGBA).

    levels: pixel data of the base image followed by any mipmaps (each
    half the size of the previous, minimum 1 pixel).

    Layout: magic + dwSize, dwFlags, dwHeight, dwWidth, dwPitch, dwDepth,
    dwMipMapCount, dwReserved1[11], pixel format (32 bytes), 5 caps DWORDs.
    Total header (incl. magic) = 128 bytes. Mirrors Firaxis' own source
    textures (e.g. the SDK leader template).

    Byte order must be R,G,B,A (red mask 0xFF), like Firaxis' own source
    textures: the asset cooker ignores the channel masks and copies the
    bytes straight into PF_R8G8B8A8_UNORM, so BGRA data comes out with
    red and blue swapped.
    """
    DDSD_CAPS, DDSD_HEIGHT, DDSD_WIDTH, DDSD_PITCH, DDSD_PIXELFORMAT = (
        0x1, 0x2, 0x4, 0x8, 0x1000)
    DDSD_MIPMAPCOUNT = 0x20000
    DDPF_ALPHAPIXELS, DDPF_RGB = 0x1, 0x40
    DDSCAPS_COMPLEX, DDSCAPS_TEXTURE, DDSCAPS_MIPMAP = 0x8, 0x1000, 0x400000

    flags = DDSD_CAPS | DDSD_HEIGHT | DDSD_WIDTH | DDSD_PIXELFORMAT
    caps = DDSCAPS_TEXTURE
    if len(levels) > 1:
        flags |= DDSD_MIPMAPCOUNT
        caps |= DDSCAPS_COMPLEX | DDSCAPS_MIPMAP
        pitch, mip_count = 0, len(levels)
    else:
        flags |= DDSD_PITCH
        pitch, mip_count = width * 4, 0
    hdr = struct.pack("<4s7I", b"DDS ", 124, flags, height, width,
                      pitch, 0, mip_count)
    hdr += b"\x00" * 44                                   # dwReserved1[11]
    hdr += struct.pack("<2I4s5I", 32, DDPF_RGB | DDPF_ALPHAPIXELS,
                       b"\x00\x00\x00\x00",
                       32, 0x000000FF, 0x0000FF00, 0x00FF0000, 0xFF000000)
    hdr += struct.pack("<5I", caps, 0, 0, 0, 0)
    with open(path, "wb") as fh:
        fh.write(hdr)
        for data in levels:
            fh.write(data)


def convert_image_to_dds(src, dst, size=None, mips=False):
    """Convert any Pillow-readable image to DDS, optionally center-cropped
    and resized (size: int for a square, or (width, height)), optionally
    with a full mipmap chain.
    Returns (width, height, mipmap count excluding the base level), or
    None when Pillow is not installed."""
    try:
        from PIL import Image
    except ImportError:
        return None
    img = Image.open(src).convert("RGBA")
    if size:
        # int: square; (w, h): that size. Centre-crop to the target aspect
        # first so nothing is stretched.
        tw, th = (size, size) if isinstance(size, int) else size
        w, h = img.size
        if w * th > h * tw:                       # too wide
            cw, ch = h * tw // th, h
        else:                                     # too tall (or exact)
            cw, ch = w, w * th // tw
        left, top = (w - cw) // 2, (h - ch) // 2
        img = img.crop((left, top, left + cw, top + ch))
        img = img.resize((tw, th), Image.LANCZOS)
    width, height = img.size
    levels = [img.tobytes()]                                 # RGBA order
    if mips:
        w, h = width, height
        while w > 1 or h > 1:
            w, h = max(1, w // 2), max(1, h // 2)
            levels.append(img.resize((w, h), Image.BOX).tobytes())
    write_dds(dst, width, height, levels)
    return width, height, len(levels) - 1


# ---------------------------------------------------------------------------
# Art cooking (SDK asset cooker -> .blp packages the game can load)
# ---------------------------------------------------------------------------
# The game only loads textures from cooked .blp packages, never loose
# .dds files. We therefore write a tiny art "pantry" (textures + .tex
# descriptors + .xlp package lists + artdefs) to a temp folder and run
# the SDK's asset cooker on it, exactly like ModBuddy does, then reference
# the results from a .dep file loaded by UpdateArt.
#
# Two kinds of texture are produced:
#   * UI textures (icons, loading screen, setup portrait) in a UITexture
#     package, looked up by texture name.
#   * Leader fallbacks (the 2D image the diplomacy screen shows for
#     leaders without a 3D scene) in a LeaderFallback package, mapped to
#     the leader type by FallbackLeaders.artdef.

COOKER_EXE = "Civ6AssetCooker_FinalRelease.exe"
COOKER_PLATFORMS = ("Windows", "MacOS")
FALLBACK_ARTDEF = "FallbackLeaders.artdef"

# Per-kind texture settings, as the Asset Editor writes them.
TEXTURE_KINDS = {
    "ui": {
        "xlp_class": "UITexture", "class_name": "UserInterface",
        "tags": ["UserInterface"], "filter": "FT_LANCZOS6", "mips": False,
        "cook_params": """
			<Element class="AssetObjects::BoolValue">
				<m_bValue>false</m_bValue>
				<m_ParamName text="IsScalable"/>
			</Element>
			<Element class="AssetObjects::IntValue">
				<m_nValue>2</m_nValue>
				<m_ParamName text="TexturePadding"/>
			</Element>
			<Element class="AssetObjects::BoolValue">
				<m_bValue>false</m_bValue>
				<m_ParamName text="IsStandalone"/>
			</Element>
			<Element class="AssetObjects::BoolValue">
				<m_bValue>false</m_bValue>
				<m_ParamName text="IsTiled"/>
			</Element>
		""",
    },
    "fallback": {
        "xlp_class": "LeaderFallback", "class_name": "Leader_Fallback",
        "tags": ["Leader_Fallback", "Leader", "Fallback"],
        "filter": "FT_BOX", "mips": True, "cook_params": "",
    },
}


def steam_libraries():
    """All Steam library folders (default install + libraryfolders.vdf)."""
    steam_roots = [r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam"]
    libraries = list(steam_roots)
    for root in steam_roots:
        vdf = os.path.join(root, "steamapps", "libraryfolders.vdf")
        try:
            with open(vdf, encoding="utf-8", errors="replace") as fh:
                for m in re.finditer(r'"path"\s+"([^"]+)"', fh.read()):
                    libraries.append(m.group(1).replace("\\\\", "\\"))
        except OSError:
            pass
    return libraries


def find_cooker():
    """Locate the Civ VI SDK asset cooker in any Steam library."""
    for lib in steam_libraries():
        path = os.path.join(lib, "steamapps", "common",
                            "Sid Meier's Civilization VI SDK",
                            "AssetModTools", "Cooker", COOKER_EXE)
        if os.path.isfile(path):
            return path
    return None


TEX_TEMPLATE = """<?xml version="1.0" encoding="UTF-8" ?>
<AssetObjects::TextureInstance>
	<m_ExportSettings>
		<ePixelformat>PF_R8G8B8A8_UNORM</ePixelformat>
		<eFilterType>{filter}</eFilterType>
		<bUseMips>{use_mips}</bUseMips>
		<iNumManualMips>0</iNumManualMips>
		<bCompleteMipChain>false</bCompleteMipChain>
		<fValueClampMin>0.000000</fValueClampMin>
		<fValueClampMax>1.000000</fValueClampMax>
		<fSupportScale>1.000000</fSupportScale>
		<fGammaIn>2.200000</fGammaIn>
		<fGammaOut>2.200000</fGammaOut>
		<iSlabWidth>0</iSlabWidth>
		<iSlabHeight>0</iSlabHeight>
		<iColorKeyX>64</iColorKeyX>
		<iColorKeyY>64</iColorKeyY>
		<iColorKeyZ>64</iColorKeyZ>
		<eExportMode>TEXTURE_2D</eExportMode>
		<bSampleFromTopLayer>false</bSampleFromTopLayer>
	</m_ExportSettings>
	<m_CookParams>
		<m_Values>{cook_params}</m_Values>
	</m_CookParams>
	<m_Version>
		<major>4</major>
		<minor>0</minor>
		<build>253</build>
		<revision>293</revision>
	</m_Version>
	<m_Height>{height}</m_Height>
	<m_Width>{width}</m_Width>
	<m_Depth>1</m_Depth>
	<m_NumMipMaps>{num_mips}</m_NumMipMaps>
	<m_SourceFilePath text="{source}"/>
	<m_SourceObjectName text=""/>
	<m_ImportedTime>0</m_ImportedTime>
	<m_ExportedTime>0</m_ExportedTime>
	<m_ClassName text="{class_name}"/>
	<m_DataFiles>
		<Element>
			<m_ID text="DDS"/>
			<m_RelativePath text="{name}.dds"/>
		</Element>
	</m_DataFiles>
	<m_Name text="{name}"/>
	<m_Description text=""/>
	<m_Tags>
{tags}
	</m_Tags>
	<m_Groups/>
</AssetObjects::TextureInstance>
"""


def add_texture(pantry, name, src, kind="ui", size=None):
    """Convert src into pantry/Textures/<name>.dds plus its .tex
    descriptor. Returns False when Pillow is not installed."""
    settings = TEXTURE_KINDS[kind]
    tex_dir = os.path.join(pantry, "Textures")
    os.makedirs(tex_dir, exist_ok=True)
    result = convert_image_to_dds(src, os.path.join(tex_dir, name + ".dds"),
                                  size=size, mips=settings["mips"])
    if not result:
        return False
    width, height, num_mips = result
    with open(os.path.join(tex_dir, name + ".tex"), "w",
              encoding="utf-8", newline="\n") as fh:
        fh.write(TEX_TEMPLATE.format(
            width=width, height=height, name=name, source=xml_escape(src),
            filter=settings["filter"], num_mips=num_mips,
            use_mips="true" if settings["mips"] else "false",
            cook_params=settings["cook_params"],
            class_name=settings["class_name"],
            tags="\n".join('\t\t<Element text="{}"/>'.format(t)
                           for t in settings["tags"])))
    return True


def build_xlp(xlp_class, package, texture_names):
    entries = "\n".join(
        "\t\t<Element>\n"
        "\t\t\t<m_EntryID text=\"{0}\"/>\n"
        "\t\t\t<m_ObjectName text=\"{0}\"/>\n"
        "\t\t</Element>".format(n) for n in texture_names)
    return """<?xml version="1.0" encoding="UTF-8" ?>
<AssetObjects..XLP>
	<m_Version>
		<major>4</major>
		<minor>0</minor>
		<build>253</build>
		<revision>293</revision>
	</m_Version>
	<m_ClassName text="{xlp_class}"/>
	<m_PackageName text="{package}"/>
	<m_Entries>
{entries}
	</m_Entries>
	<m_AllowedPlatforms>
		<Element>WINDOWS</Element>
		<Element>LINUX</Element>
		<Element>MACOS</Element>
		<Element>IOS</Element>
	</m_AllowedPlatforms>
</AssetObjects..XLP>
""".format(xlp_class=xlp_class, package=package, entries=entries)


def build_fallback_artdef(package, fallbacks):
    """Cooked FallbackLeaders.artdef: leader type -> its fallback texture.
    fallbacks: (leader type, texture name) pairs. The game merges this
    with the other FallbackLeaders.artdef files by element name."""
    leaders = "\n".join("""			<Element>
				<m_Fields>
					<m_Values/>
				</m_Fields>
				<m_ChildCollections>
					<Element>
						<m_CollectionName text="Animations"/>
						<m_ReplaceMergedCollectionElements>false</m_ReplaceMergedCollectionElements>
						<Element>
							<m_Fields>
								<m_Values>
									<Element class="AssetObjects..BLPEntryValue">
										<m_EntryName text="{texture}"/>
										<m_XLPClass text="LeaderFallback"/>
										<m_XLPPath text="{package}.xlp"/>
										<m_BLPPackage text="{package}"/>
										<m_LibraryName text="LeaderFallback"/>
										<m_ParamName text="BLP Entry"/>
									</Element>
								</m_Values>
							</m_Fields>
							<m_ChildCollections/>
							<m_Name text="DEFAULT"/>
							<m_AppendMergedParameterCollections>false</m_AppendMergedParameterCollections>
						</Element>
					</Element>
				</m_ChildCollections>
				<m_Name text="{leader}"/>
				<m_AppendMergedParameterCollections>false</m_AppendMergedParameterCollections>
			</Element>""".format(leader=leader, texture=texture, package=package)
        for leader, texture in fallbacks)
    return """<?xml version="1.0" encoding="UTF-8" ?>
<AssetObjects..ArtDefSet>
	<m_Version>
		<major>4</major>
		<minor>0</minor>
		<build>253</build>
		<revision>293</revision>
	</m_Version>
	<m_TemplateName text="LeaderFallback"/>
	<m_RootCollections>
		<Element>
			<m_CollectionName text="Leaders"/>
			<m_ReplaceMergedCollectionElements>false</m_ReplaceMergedCollectionElements>
{leaders}
		</Element>
	</m_RootCollections>
</AssetObjects..ArtDefSet>
""".format(leaders=leaders)


def build_dep(mod_name, guid, ui_package, fallback_package):
    """Art dependency file: makes the game load our cooked packages (and
    the fallback artdef). Either package may be None."""
    consumers, artdefs, libraries = [], "\t<ArtDefDependencies/>", []
    if ui_package:
        consumers.append("""		<Element>
			<ConsumerName text="UI"/>
			<ArtDefDependencyPaths/>
			<LibraryDependencies>
				<Element text="UITexture"/>
			</LibraryDependencies>
			<LoadsLibraries>true</LoadsLibraries>
		</Element>""")
        libraries.append(("UITexture", ui_package))
    if fallback_package:
        consumers.append("""		<Element>
			<ConsumerName text="LeaderFallback"/>
			<ArtDefDependencyPaths>
				<Element text="{artdef}"/>
			</ArtDefDependencyPaths>
			<LibraryDependencies>
				<Element text="LeaderFallback"/>
			</LibraryDependencies>
			<LoadsLibraries>true</LoadsLibraries>
		</Element>""".format(artdef=FALLBACK_ARTDEF))
        artdefs = """	<ArtDefDependencies>
		<Element>
			<ArtDefPath text="{artdef}"/>
			<ArtDefDependencyPaths/>
		</Element>
	</ArtDefDependencies>""".format(artdef=FALLBACK_ARTDEF)
        libraries.append(("LeaderFallback", fallback_package))
    library_xml = "\n".join("""		<Element>
			<LibraryName text="{0}"/>
			<PackageDependencies>
				<Element text="{1}.blp"/>
			</PackageDependencies>
		</Element>""".format(lib, pkg) for lib, pkg in sorted(libraries))
    return """<?xml version="1.0" encoding="UTF-8" ?>
<AssetObjects..GameDependencyData>
	<ID>
		<name text="{name}"/>
		<id text="{guid}"/>
	</ID>
	<RequiredGameArtIDs/>
	<SystemDependencies>
{consumers}
	</SystemDependencies>
{artdefs}
	<LibraryDependencies>
{libraries}
	</LibraryDependencies>
</AssetObjects..GameDependencyData>
""".format(name=xml_escape(mod_name), guid=guid,
           consumers="\n".join(consumers), artdefs=artdefs,
           libraries=library_xml)


def run_cooker(cooker, args, report, what, cwd=None):
    """Run the asset cooker with ModBuddy's standard arguments.
    Returns True when it reports success. The cooker writes cooker.log
    into its working directory, so pass the (temporary) pantry as cwd."""
    cooker_dir = os.path.dirname(cooker)
    # Same command lines ModBuddy's Civ6.targets uses.
    cmd = ([cooker, "--absolute_paths", "--no_mt"] + args[:-1] +
           ["--shaders", cooker_dir,
            "--config", os.path.join(cooker_dir, "Civ6.cfg"), args[-1]])
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, errors="replace",
            timeout=600, cwd=cwd, creationflags=getattr(subprocess,
                                               "CREATE_NO_WINDOW", 0))
        output = proc.stdout + proc.stderr
    except (OSError, subprocess.SubprocessError) as exc:
        output = str(exc)
    if "cook completed with success" not in output:
        report.append("WARNING: cooking {} failed:".format(what))
        report.extend("    " + line for line in output.splitlines()[-15:])
        return False
    report.append("cooked " + what)
    return True


def cook_art(cooker, pantry, packages, fallbacks, mod_dir, report):
    """Cook the texture packages and write the fallback artdef (if any).

    packages: {package name: (texture kind, [texture names])}
    fallbacks: (leader type, fallback texture name) pairs
    Writes mod_dir/Platforms/*/BLPs/*.blp and mod_dir/ArtDefs/*.artdef.
    Returns the mod-relative paths of all cooked files ([] on failure)."""
    pantry_arg = os.path.join(pantry, "")
    xlp_dir = os.path.join(pantry, "XLPs")
    os.makedirs(xlp_dir, exist_ok=True)
    xlps = []
    for package, (kind, names) in sorted(packages.items()):
        path = os.path.join(xlp_dir, package + ".xlp")
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(build_xlp(TEXTURE_KINDS[kind]["xlp_class"], package,
                               names))
        xlps.append((package, path))

    for sub in ("Platforms", "ArtDefs"):               # drop stale output
        shutil.rmtree(os.path.join(mod_dir, sub), ignore_errors=True)

    for platform in COOKER_PLATFORMS:
        stewpot = os.path.join(mod_dir, "Platforms", platform, "BLPs")
        os.makedirs(stewpot, exist_ok=True)
        for package, xlp in xlps:
            ok = run_cooker(
                cooker, ["--mode", "XLP", "--platform", platform,
                         "--pantry", pantry_arg, "--stewpot", stewpot, xlp],
                report, "{}.blp for {}".format(package, platform),
                cwd=pantry)
            if not ok or not os.path.isfile(
                    os.path.join(stewpot, package + ".blp")):
                return []

    if fallbacks:
        # Written in cooked form directly: the command-line cooker cannot
        # cook artdefs outside ModBuddy, and cooking only changes the
        # BLPEntryValue class separator ("::" -> ".."), as a diff of the
        # SDK template's source and cooked FallbackLeaders.artdef shows.
        fallback_package = next(p for p, (kind, _) in packages.items()
                                if kind == "fallback")
        artdef_dir = os.path.join(mod_dir, "ArtDefs")
        os.makedirs(artdef_dir, exist_ok=True)
        with open(os.path.join(artdef_dir, FALLBACK_ARTDEF), "w",
                  encoding="utf-8", newline="\n") as fh:
            fh.write(build_fallback_artdef(fallback_package, fallbacks))
        report.append("wrote ArtDefs/" + FALLBACK_ARTDEF)

    cooked = []
    for sub in ("Platforms", "ArtDefs"):
        for dirpath, _, filenames in os.walk(os.path.join(mod_dir, sub)):
            for fname in filenames:
                rel = os.path.relpath(os.path.join(dirpath, fname), mod_dir)
                cooked.append(rel.replace(os.sep, "/"))
    return sorted(cooked)


# ---------------------------------------------------------------------------
# Editable localization lines (diplomacy + Civilopedia)
# ---------------------------------------------------------------------------
# Keys are tag templates; "{L}" is the leader type (which already starts
# with LEADER_). Moods: _ANY is used by the base game, _HAPPY/_UNHAPPY
# override it for that mood.

DIPLO_TEXT = [
    ("First meet", [
        ("LOC_DIPLO_FIRST_MEET_{L}_ANY", "First AI line"),
        ("LOC_DIPLO_FIRST_MEET_VISIT_RECIPIENT_{L}_ANY",
         "AI invites you to visit a nearby city"),
        ("LOC_DIPLO_FIRST_MEET_NEAR_INITIATOR_POSITIVE_{L}_ANY",
         "AI accepts your invitation"),
        ("LOC_DIPLO_FIRST_MEET_NO_MANS_INFO_EXCHANGE_{L}_ANY",
         "AI proposes exchanging capital information"),
    ]),
    ("Greetings", [
        ("LOC_DIPLO_GREETING_{L}_ANY", "Greeting (any mood)"),
        ("LOC_DIPLO_GREETING_{L}_HAPPY", "Greeting (happy)"),
        ("LOC_DIPLO_GREETING_{L}_UNHAPPY", "Greeting (unhappy)"),
    ]),
    ("Delegation", [
        ("LOC_DIPLO_ACCEPT_DELEGATION_FROM_HUMAN_{L}_ANY", "AI accepts"),
        ("LOC_DIPLO_REJECT_DELEGATION_FROM_HUMAN_{L}_ANY", "AI rejects"),
        ("LOC_DIPLO_DELEGATION_FROM_AI_{L}_ANY", "AI sends a delegation"),
    ]),
    ("Open borders", [
        ("LOC_DIPLO_ACCEPT_OPEN_BORDERS_FROM_HUMAN_{L}_ANY", "AI accepts"),
        ("LOC_DIPLO_REJECT_OPEN_BORDERS_FROM_HUMAN_{L}_ANY", "AI rejects"),
        ("LOC_DIPLO_OPEN_BORDERS_FROM_AI_{L}_ANY", "AI requests"),
    ]),
    ("Declare friendship", [
        ("LOC_DIPLO_ACCEPT_DECLARE_FRIEND_FROM_HUMAN_{L}_ANY", "AI accepts"),
        ("LOC_DIPLO_REJECT_DECLARE_FRIEND_FROM_HUMAN_{L}_ANY", "AI rejects"),
        ("LOC_DIPLO_DECLARE_FRIEND_FROM_AI_{L}_ANY", "AI requests"),
        ("LOC_DIPLO_ACCEPT_DECLARE_FRIEND_FROM_AI_{L}_ANY",
         "You accept the AI's request, AI responds"),
        ("LOC_DIPLO_REJECT_DECLARE_FRIEND_FROM_AI_{L}_ANY",
         "You reject the AI's request, AI responds"),
    ]),
    ("Alliance", [
        ("LOC_DIPLO_MAKE_ALLIANCE_FROM_AI_{L}_ANY", "AI requests an alliance"),
    ]),
    ("Kudos & warnings", [
        ("LOC_DIPLO_KUDO_EXIT_{L}_ANY", "AI kudos"),
        ("LOC_DIPLO_WARNING_EXIT_{L}_ANY", "AI warning"),
        ("LOC_DIPLO_KUDO_{L}_REASON_ANY", "Agenda: reason for liking you"),
        ("LOC_DIPLO_WARNING_{L}_REASON_ANY",
         "Agenda: reason for disliking you"),
    ]),
    ("Troops near border", [
        ("LOC_DIPLO_WARNING_TOO_MANY_TROOPS_NEAR_ME_{L}_HAPPY",
         "AI warns about your troops (happy)"),
        ("LOC_DIPLO_WARNING_TOO_MANY_TROOPS_NEAR_ME_{L}_UNHAPPY",
         "AI warns about your troops (unhappy)"),
        ("LOC_DIPLO_WARNING_TOO_MANY_TROOPS_NEAR_ME_AI_RESPONSE_POSITIVE"
         "_{L}_HAPPY", "AI accepts your warning (happy)"),
        ("LOC_DIPLO_WARNING_TOO_MANY_TROOPS_NEAR_ME_AI_RESPONSE_POSITIVE"
         "_{L}_UNHAPPY", "AI accepts your warning (unhappy)"),
        ("LOC_DIPLO_WARNING_TOO_MANY_TROOPS_NEAR_ME_AI_RESPONSE_NEGATIVE"
         "_{L}_ANY", "AI rejects your warning - declares war"),
    ]),
    ("Settling too close", [
        ("LOC_DIPLO_WARNING_DONT_SETTLE_NEAR_ME_AI_{L}_HAPPY",
         "AI warns you (happy)"),
        ("LOC_DIPLO_WARNING_DONT_SETTLE_NEAR_ME_AI_{L}_UNHAPPY",
         "AI warns you (unhappy)"),
        ("LOC_DIPLO_WARNING_DONT_SETTLE_NEAR_ME_AI_RESPONSE_POSITIVE_{L}"
         "_HAPPY", "AI accepts your request (happy)"),
        ("LOC_DIPLO_WARNING_DONT_SETTLE_NEAR_ME_AI_RESPONSE_POSITIVE_{L}"
         "_UNHAPPY", "AI accepts your request (unhappy)"),
        ("LOC_DIPLO_WARNING_DONT_SETTLE_NEAR_ME_AI_RESPONSE_NEGATIVE_{L}"
         "_HAPPY", "AI rejects your request (happy)"),
        ("LOC_DIPLO_WARNING_DONT_SETTLE_NEAR_ME_AI_RESPONSE_NEGATIVE_{L}"
         "_UNHAPPY", "AI rejects your request (unhappy)"),
    ]),
    ("Trade", [
        ("LOC_DIPLO_ACCEPT_MAKE_DEAL_FROM_AI_{L}_HAPPY",
         "AI accepts a deal (happy)"),
        ("LOC_DIPLO_ACCEPT_MAKE_DEAL_FROM_AI_{L}_UNHAPPY",
         "AI accepts a deal (unhappy)"),
        ("LOC_DIPLO_REJECT_MAKE_DEAL_FROM_AI_{L}_HAPPY",
         "AI rejects a deal (happy)"),
        ("LOC_DIPLO_REJECT_MAKE_DEAL_FROM_AI_{L}_UNHAPPY",
         "AI rejects a deal (unhappy)"),
    ]),
    ("Denounce", [
        ("LOC_DIPLO_DENOUNCE_FROM_HUMAN_{L}_ANY",
         "You denounce, AI responds"),
        ("LOC_DIPLO_DENOUNCE_FROM_AI_{L}_ANY", "AI denounces you"),
    ]),
    ("Declarations of war", [
        ("LOC_DIPLO_DECLARE_WAR_FROM_HUMAN_{L}_ANY",
         "You declare war, AI responds"),
        ("LOC_DIPLO_DECLARE_WAR_FROM_AI_{L}_ANY", "AI declares war"),
    ]),
    ("Make peace", [
        ("LOC_DIPLO_MAKE_PEACE_AI_ACCEPT_DEAL_{L}_ANY", "AI accepts"),
        ("LOC_DIPLO_MAKE_PEACE_AI_REFUSE_DEAL_{L}_ANY", "AI refuses"),
        ("LOC_DIPLO_MAKE_PEACE_FROM_AI_{L}_ANY", "AI requests peace"),
    ]),
    ("Defeat", [
        ("LOC_DIPLO_DEFEAT_FROM_AI_{L}_ANY", "AI is defeated"),
        ("LOC_DIPLO_DEFEAT_FROM_HUMAN_{L}_ANY",
         "You are defeated (seen in hotseat)"),
    ]),
]

PEDIA_PREFIX = "LOC_PEDIA_LEADERS_PAGE_{L}_"
PEDIA_HISTORY = PEDIA_PREFIX + "CHAPTER_HISTORY"   # -> _PARA_1, _PARA_2, ...
# (key, label, text box height, inherit from the original leader if empty)
PEDIA_TEXT = [
    (PEDIA_PREFIX + "TITLE", "Title (empty = leader name)", 1, False),
    (PEDIA_PREFIX + "SUBTITLE", "Subtitle", 1, False),
    (PEDIA_PREFIX + "QUOTE", "Quote", 3, False),
    (PEDIA_PREFIX + "CHAPTER_CAPSULE_BODY", "Summary (capsule)", 4, True),
    (PEDIA_PREFIX + "CHAPTER_DETAILED_BODY", "Detailed approach", 7, True),
    (PEDIA_HISTORY, "History (separate paragraphs with a blank line)", 14,
     False),
]

# The generator used to have three greeting fields of its own.
LEGACY_GREETINGS = {"greet_happy": "LOC_DIPLO_GREETING_{L}_HAPPY",
                    "greet_neutral": "LOC_DIPLO_GREETING_{L}_ANY",
                    "greet_unhappy": "LOC_DIPLO_GREETING_{L}_UNHAPPY"}


def spec_texts(spec):
    """The spec's {tag template: text}, including legacy greeting fields."""
    texts = dict(spec.get("texts") or {})
    for old, key in LEGACY_GREETINGS.items():
        if (spec.get(old) or "").strip() and not texts.get(key):
            texts[key] = spec[old].strip()
    return texts


def inherit_candidates(key):
    """Tag templates of the original leader to copy an empty line from:
    the same mood first, then the mood-independent _ANY line - unless
    that _ANY line is editable itself (like the greeting), because the
    game already falls back to our own _ANY line then, and copying the
    original's would override it."""
    editable = {k for _, lines in DIPLO_TEXT for k, _ in lines}
    candidates = [key]
    for mood in ("_HAPPY", "_UNHAPPY"):
        any_key = key[:-len(mood)] + "_ANY"
        if key.endswith(mood) and any_key not in editable:
            candidates.append(any_key)
    return candidates


def editable_text_keys():
    return ([k for _, lines in DIPLO_TEXT for k, _ in lines] +
            [k for k, _, _, _ in PEDIA_TEXT])


# (symbol, what it marks) for the leader list's "Custom" column, in the
# order they are shown. Non-BMP emoji need Tk 8.6.10+ (drawn monochrome).
CUSTOM_MARKS = [
    ("\U0001F5BC", "loading background"),
    ("\U0001F3DB", "diplomacy background"),
    ("\U0001F3AF", "agenda"),
    ("\U0001F396", "leader ability"),
    ("\U0001F4AC", "diplomacy text"),
    ("\U0001F4D6", "Civilopedia"),
    ("⭐", "historic moments"),
]


def leader_custom_marks(spec):
    """The CUSTOM_MARKS entries (symbol, what) for what a leader
    customizes."""
    def filled(value):
        return bool((value or "").strip())
    texts = {k for k, v in spec_texts(spec).items() if filled(v)}
    checks = [
        filled(spec.get("load_bg_path")),
        filled(spec.get("diplo_bg_path")),
        any(filled(spec.get(k)) for k in ("agenda", "agenda_name",
                                          "agenda_desc")),
        any(filled(text.get("name")) or filled(text.get("desc"))
            for text in (spec.get("abilities") or {}).values()),
        any(k in texts for _, lines in DIPLO_TEXT for k, _ in lines),
        any(k in texts for k, _, _, _ in PEDIA_TEXT),
        any(filled(entry.get("path"))
            for entry in spec.get("moment_illustrations") or []),
    ]
    return [mark for mark, on in zip(CUSTOM_MARKS, checks) if on]


def texts_to_json(texts):
    """All editable lines as JSON (empty ones too, so the result doubles
    as a template), keyed by tag template with {L} for the leader."""
    return json.dumps({k: texts.get(k, "") for k in editable_text_keys()},
                      ensure_ascii=False, indent=2)


def texts_from_json(data):
    """Parse clipboard JSON into {tag template: text}. Keys may be tag
    templates ("..._{L}_ANY") or real tags of any leader
    ("..._LEADER_RFVS_LEOPOLD_I_ANY"); history may also come as separate
    ..._CHAPTER_HISTORY_PARA_<n> entries. Returns (texts, unknown keys).
    Raises ValueError for anything that is not a JSON object of strings."""
    try:
        obj = json.loads(data)
    except ValueError as exc:
        raise ValueError("The clipboard does not contain valid JSON ({})."
                         .format(exc))
    if not isinstance(obj, dict):
        raise ValueError("Expected a JSON object of {\"tag\": \"text\"}.")
    patterns = []
    for key in editable_text_keys():
        head, tail = key.split("{L}")
        patterns.append((key, re.compile(
            re.escape(head) + r"LEADER_[A-Z0-9_]+?" + re.escape(tail) + "$")))
    head, tail = PEDIA_HISTORY.split("{L}")
    para = re.compile(re.escape(head) + r"(?:\{L\}|LEADER_[A-Z0-9_]+?)" +
                      re.escape(tail) + r"_PARA_(\d+)$")
    texts, unknown, paras = {}, [], {}
    for tag, text in obj.items():
        if not isinstance(text, str):
            raise ValueError("The value of {} is not text.".format(tag))
        m = para.match(tag)
        if m:
            paras[int(m.group(1))] = text.strip()
            continue
        key = tag if tag in editable_text_keys() else next(
            (k for k, p in patterns if p.match(tag)), None)
        if key:
            texts[key] = text.strip()
        else:
            unknown.append(tag)
    if paras and PEDIA_HISTORY not in texts:
        texts[PEDIA_HISTORY] = "\n\n".join(
            paras[n] for n in sorted(paras) if paras[n])
    return texts, unknown


def history_paragraphs(text):
    return [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]


def loc_text(text):
    """Editor text -> game text (single newlines become [NEWLINE])."""
    return "[NEWLINE]".join(line.strip() for line in text.strip().split("\n"))


# ---------------------------------------------------------------------------
# Leader spec: validation and derived fields
# ---------------------------------------------------------------------------
# A leader spec is a plain picklable dict with these keys:
#   name, sex, civ, orig, bio, quote, texts ({tag template: text}, see
#   DIPLO_TEXT / PEDIA_TEXT), primary, secondary,
#   icon_path, load_fg_path, load_bg_path, diplo_bg_path,
#   diplo_bg_mask (fade the diplomacy background out with assets/mask.png),
#   icon_mode ('portrait' or 'file'), icon_crop ((x, y, r) in fitted
#   portrait pixels, see fit_portrait, or None), icon_border_color,
#   icon_border_width,
#   moment_illustrations ([{"item": "UNIT_X", "path": image, "mask": bool
#   (fade frame from assets/mask_historical.png), "half": bool (50%
#   transparent), "sepia": bool (old-photo brown tint)}, ...]),
#   agenda (AGENDA_ type, "" = the original leader's), agenda_name,
#   agenda_desc (either one filled = a renamed copy of that agenda),
#   abilities ({TraitType: {"name": ..., "desc": ...}} of the original
#   leader's ability traits; either one filled = a renamed copy),
#   city_names ([name, ...], the first is the capital; [] = the
#   civilization's own names)
# (older projects may also have greet_happy/neutral/unhappy)

def new_leader_spec():
    return {
        "name": "", "sex": "Female", "civ": "", "orig": "",
        "bio": "", "quote": "", "texts": {},
        "primary": (30, 90, 170), "secondary": (230, 230, 230),
        "icon_path": "", "load_fg_path": "", "load_bg_path": "",
        "diplo_bg_path": "", "diplo_bg_mask": False,
        "icon_mode": "portrait", "icon_crop": None,
        "icon_border_color": DEFAULT_ICON_BORDER_COLOR,
        "icon_border_width": DEFAULT_ICON_BORDER_WIDTH,
        "moment_illustrations": [],
        "agenda": "", "agenda_name": "", "agenda_desc": "",
        "abilities": {},
        "city_names": [],
    }


# Historic moments (Rise and Fall / Gathering Storm). Mods cannot add new
# moments - their triggers are engine code - but the engine's "first unique
# unit / building / district / improvement" moments take their picture from
# MomentIllustrations, keyed by the item's type.
# item type prefix -> (MomentIllustrationType, MomentDataType)
MOMENT_KINDS = {
    "UNIT_": ("MOMENT_ILLUSTRATION_UNIQUE_UNIT", "MOMENT_DATA_UNIT"),
    "BUILDING_": ("MOMENT_ILLUSTRATION_UNIQUE_BUILDING",
                  "MOMENT_DATA_BUILDING"),
    "DISTRICT_": ("MOMENT_ILLUSTRATION_UNIQUE_DISTRICT",
                  "MOMENT_DATA_DISTRICT"),
    "IMPROVEMENT_": ("MOMENT_ILLUSTRATION_UNIQUE_IMPROVEMENT",
                     "MOMENT_DATA_IMPROVEMENT"),
}
MOMENT_ILLUSTRATION_SIZE = (456, 332)     # size of Firaxis' own illustrations


def moment_kind(item):
    return next((kind for prefix, kind in MOMENT_KINDS.items()
                 if item.startswith(prefix)), None)


def spec_icon_mode(spec):
    """'portrait' (cut a circle out of the loading portrait) or 'file'
    (use icon_path). Projects from before the mode existed keep using
    their icon file if they had one."""
    mode = spec.get("icon_mode")
    if mode in ("portrait", "file"):
        return mode
    return "file" if (spec.get("icon_path") or "").strip() else "portrait"


def normalize_spec(spec, data, prefix=""):
    """Validate a leader spec and compute derived fields (slug, text keys,
    icon handling). prefix is the project-wide type prefix. Raises
    ValueError with a human-friendly message. A type that already exists
    in the game data is not an error; it is flagged as exists_in_game."""
    name = (spec.get("name") or "").strip()
    civ = (spec.get("civ") or "").strip()
    orig = (spec.get("orig") or "").strip()
    if not name:
        raise ValueError("A leader has no name.")
    if not civ or not orig:
        raise ValueError("{}: pick (or type) both the civilization and the "
                         "leader to inherit from.".format(name))
    slug = slug_for_name(name, prefix)
    if not slug:
        raise ValueError("{} does not produce a valid type name.".format(name))
    if slug == orig:
        raise ValueError("{}: its type ({}) collides with the leader being "
                         "inherited. Change the name.".format(name, slug))

    icon_mode = spec_icon_mode(spec)
    images = {}
    for key, label in (("icon_path", "icon"),
                       ("load_fg_path", "loading portrait"),
                       ("load_bg_path", "loading background"),
                       ("diplo_bg_path", "diplomacy background")):
        path = (spec.get(key) or "").strip()
        if key == "icon_path" and icon_mode != "file":
            path = ""                   # the icon comes from the portrait
        if path and not os.path.isfile(path):
            raise ValueError("{}: {} image not found: {}".format(
                name, label, path))
        images[key] = path
    moments = []
    for entry in spec.get("moment_illustrations") or []:
        item = (entry.get("item") or "").strip().upper()
        path = (entry.get("path") or "").strip()
        if not item and not path:
            continue                    # empty editor row
        kind = moment_kind(item)
        if not kind:
            raise ValueError(
                "{}: historic moment item '{}' must be a unique UNIT_, "
                "BUILDING_, DISTRICT_ or IMPROVEMENT_ type.".format(name, item))
        if not path or not os.path.isfile(path):
            raise ValueError("{}: historic moment image for {} not found: {}"
                             .format(name, item, path or "(none)"))
        moments.append({"item": item, "illustration": kind[0],
                        "data_type": kind[1], "path": path,
                        "texture": "MOMENT_{}_{}".format(slug, item),
                        "mask": bool(entry.get("mask")),
                        "half": bool(entry.get("half")),
                        "sepia": bool(entry.get("sepia"))})
    agenda = (spec.get("agenda") or "").strip().upper()
    if agenda and not agenda.startswith("AGENDA_"):
        raise ValueError("{}: agenda '{}' must be an AGENDA_ type."
                         .format(name, agenda))
    agenda_name = (spec.get("agenda_name") or "").strip()
    agenda_desc = (spec.get("agenda_desc") or "").strip()
    agenda_type = "AGENDA_" + slug[len("LEADER_"):]
    known = {a["type"]: a for a in data.abilities(orig)}
    abilities = []
    for trait, text in sorted((spec.get("abilities") or {}).items()):
        trait = trait.strip().upper()
        new_name = (text.get("name") or "").strip()
        new_desc = (text.get("desc") or "").strip()
        if not new_name and not new_desc:
            continue
        if not re.fullmatch(r"[A-Z0-9_]+", trait):
            raise ValueError("{}: ability '{}' is not a trait type."
                             .format(name, trait))
        copy_type = "{}_{}".format(trait, slug[len("LEADER_"):])
        abilities.append({
            "source": trait, "type": copy_type,
            "name": new_name, "desc": new_desc,
            "name_tag": "LOC_{}_NAME".format(copy_type),
            "desc_tag": "LOC_{}_DESCRIPTION".format(copy_type),
            # the source's text tags, to swap on the setup screen (None
            # without the game cache)
            "source_name_tag": known.get(trait, {}).get("name_tag"),
            "source_desc_tag": known.get(trait, {}).get("desc_tag")})
    city_names = []
    for city in spec.get("city_names") or []:
        city = city.strip()
        if city and city.lower() not in (n.lower() for n in city_names):
            city_names.append(city)
    load_bg_name = slug + "_BACKGROUND"
    icon_path = images["icon_path"]
    # portrait mode without a portrait: keep the inherited icon
    icon_custom = bool(icon_path if icon_mode == "file"
                       else images["load_fg_path"])

    meta = data.meta(orig)
    icon_inherit = meta.get("icon") or "ICON_{}".format(orig)
    return {
        "name": name,
        "slug": slug,
        # the type is already in the loaded game data - usually an earlier
        # build of this very mod; the caller decides whether that is fine
        "exists_in_game": slug in data.leader_meta,
        "civ": civ,
        "orig": orig,
        "sex": (spec.get("sex") or "Female"),
        "bio": (spec.get("bio") or "").strip() or
               ("The burden of history falls to you, " + name + "..."),
        "quote": (spec.get("quote") or "").strip() or
                 ('"A leader is only as great as their moment." - ' + name),
        "texts": {k: v.strip() for k, v in spec_texts(spec).items()
                  if v and v.strip()},
        "primary": tuple(spec.get("primary") or (30, 90, 170)),
        "secondary": tuple(spec.get("secondary") or (230, 230, 230)),
        "icon_path": icon_path,
        "icon_custom": icon_custom,
        "moments": moments,
        "icon_mode": icon_mode,
        "icon_crop": spec.get("icon_crop"),
        "icon_border_color": tuple(spec.get("icon_border_color") or
                                   DEFAULT_ICON_BORDER_COLOR),
        "icon_border_width": int(spec.get("icon_border_width",
                                          DEFAULT_ICON_BORDER_WIDTH)),
        "icon_name": "ICON_{}".format(slug),
        "icon_atlas": "ICON_ATLAS_{}".format(slug),
        "icon_inherit": icon_inherit,
        "leader_icon": icon_name_from(slug) if icon_custom else icon_inherit,
        # Loading-screen / setup-portrait textures. Names follow the game's
        # own convention (LoadScreen.lua falls back to these). None means
        # "inherit from the original leader".
        "load_fg_path": images["load_fg_path"],
        "load_bg_path": images["load_bg_path"],
        "load_fg_name": slug + "_NEUTRAL",
        "load_bg_name": load_bg_name,
        "load_fg": slug + "_NEUTRAL" if images["load_fg_path"] else None,
        "load_bg": load_bg_name if images["load_bg_path"] else None,
        # 2D diplomacy-screen image (made from the loading portrait),
        # named like the SDK template's FALLBACK_NEUTRAL_JASPERKITTY
        "fallback_name": "FALLBACK_NEUTRAL_" + slug[len("LEADER_"):],
        # diplomacy-screen background (DiplomacyInfo.BackgroundImage)
        "diplo_bg_path": images["diplo_bg_path"],
        "diplo_bg_name": slug + "_DIPLO_BG",
        "diplo_bg": slug + "_DIPLO_BG" if images["diplo_bg_path"] else None,
        "diplo_bg_mask": bool(spec.get("diplo_bg_mask")),
        # no own background: show the original's layered scene (set by
        # _write_mod once it knows the art and LeaderScene.lua worked)
        "scene_from_orig": False,
        # AI agenda: "" = the original leader's; a new name or description
        # makes a copy of the agenda (agenda_type) with that text
        "agenda": agenda,
        "agenda_name": agenda_name,
        "agenda_desc": agenda_desc,
        "agenda_clone": bool(agenda_name or agenda_desc),
        "agenda_type": agenda_type,
        "agenda_name_tag": "LOC_{}_NAME".format(agenda_type),
        "agenda_desc_tag": "LOC_{}_DESCRIPTION".format(agenda_type),
        # leader ability traits with new text: renamed copies replace them
        "abilities": abilities,
        # own city names ([(tag, name)], the first is the capital); empty
        # = the civilization's names and the original leader's capital
        "city_names": [("LOC_CITY_NAME_{}_{}".format(slug, i), city)
                       for i, city in enumerate(city_names, 1)],
        # text keys
        "name_tag": "LOC_{}_NAME".format(slug),
        "bio_tag": "LOC_LOADING_INFO_{}".format(slug),
        "quote_tag": "LOC_{}_QUOTE".format(slug),
    }


def needs_art(c):
    """Whether a leader has any custom art to convert and cook."""
    return bool(c["icon_custom"] or c["load_fg"] or c["load_bg"]
                or c["diplo_bg"] or c["moments"])


def icon_name_from(slug):
    return "ICON_{}".format(slug)


# ---------------------------------------------------------------------------
# Per-leader mod file fragments
# ---------------------------------------------------------------------------

def value_or_column(value, column):
    """SQL for INSERT ... SELECT: a literal override, or copy the column."""
    return sql_str(value) if value else column


def ability_config_column(c, column, key):
    """SQL for a setup-screen ability column (key 'name' or 'desc'): the
    renamed ability's new text tag where the original shows its source's
    tag, or the column as is."""
    swaps = [(a["source_{}_tag".format(key)], a["{}_tag".format(key)])
             for a in c["abilities"] if a[key]]
    known = [(source, tag) for source, tag in swaps if source]
    if known:
        return "CASE {} {} ELSE {} END".format(column, " ".join(
            "WHEN {} THEN {}".format(sql_str(source), sql_str(tag))
            for source, tag in known), column)
    if len(swaps) == 1:     # no game cache: it is the ability shown there
        return sql_str(swaps[0][1])
    return column


def config_block(c):
    """Setup-screen SQL fragment (Players + PlayerItems) for one leader."""
    return """-----------------------------------------------
-- Setup-screen rows for {slug} (civ fields and leader ability text
-- inherited from {orig}; leader name, icon and portrait are new)
-----------------------------------------------
INSERT INTO Players (
    Domain, CivilizationType, LeaderType,
    CivilizationName, CivilizationIcon,
    CivilizationAbilityName, CivilizationAbilityDescription, CivilizationAbilityIcon,
    LeaderName, LeaderIcon,
    LeaderAbilityName, LeaderAbilityDescription, LeaderAbilityIcon,
    Portrait, PortraitBackground
)
SELECT
    Domain, CivilizationType, '{slug}',
    CivilizationName, CivilizationIcon,
    CivilizationAbilityName, CivilizationAbilityDescription, CivilizationAbilityIcon,
    '{name_tag}', {leader_icon},
    {ability_name}, {ability_desc}, {leader_icon},
    {portrait}, {portrait_bg}
FROM Players WHERE LeaderType = '{orig}';

INSERT INTO PlayerItems (Domain, CivilizationType, LeaderType, Type, Name, Description, Icon, SortIndex)
SELECT Domain, CivilizationType, '{slug}', Type, Name, Description, Icon, SortIndex
FROM PlayerItems WHERE LeaderType = '{orig}';
""".format(slug=c["slug"], orig=c["orig"], name_tag=c["name_tag"],
           leader_icon=sql_str(c["leader_icon"]),
           ability_name=ability_config_column(c, "LeaderAbilityName",
                                              "name"),
           ability_desc=ability_config_column(
               c, "LeaderAbilityDescription", "desc"),
           portrait=value_or_column(c["load_fg"], "Portrait"),
           portrait_bg=value_or_column(c["load_bg"], "PortraitBackground"))


def agenda_block(c):
    """HistoricalAgendas SQL for one leader: the original leader's agenda,
    another existing agenda, or a renamed copy of either. A copy shares the
    source's traits, so its behaviour (modifiers and AI lists, which are
    keyed by trait) is identical; only its name / description differ."""
    slug, orig = c["slug"], c["orig"]
    if not c["agenda"] and not c["agenda_clone"]:
        return """-- INHERIT the AI agenda
INSERT INTO HistoricalAgendas (LeaderType, AgendaType)
SELECT '{slug}', AgendaType FROM HistoricalAgendas WHERE LeaderType = '{orig}';
""".format(slug=slug, orig=orig)

    source = (sql_str(c["agenda"]) if c["agenda"] else
              "(SELECT AgendaType FROM HistoricalAgendas "
              "WHERE LeaderType = '{}' LIMIT 1)".format(orig))
    if c["agenda_clone"]:
        target = sql_str(c["agenda_type"])
        out = """-- AI agenda: a copy of {what} with its own name / description.
-- Nothing is copied if that agenda does not exist in the current ruleset.
INSERT INTO Agendas (AgendaType, OperationList, Name, Description)
SELECT {target}, OperationList, {name}, {desc}
FROM Agendas WHERE AgendaType = {source};

INSERT INTO AgendaTraits (AgendaType, TraitType)
SELECT {target}, TraitType FROM AgendaTraits WHERE AgendaType = {source};

-- random agendas that cannot be combined with it
INSERT OR IGNORE INTO ExclusiveAgendas (AgendaOne, AgendaTwo)
SELECT {target}, AgendaTwo FROM ExclusiveAgendas WHERE AgendaOne = {source};
INSERT OR IGNORE INTO ExclusiveAgendas (AgendaOne, AgendaTwo)
SELECT AgendaOne, {target} FROM ExclusiveAgendas WHERE AgendaTwo = {source};

""".format(what=c["agenda"] or "the agenda of " + orig, target=target,
           source=source,
           name=value_or_column(c["agenda_name"] and c["agenda_name_tag"],
                                "Name"),
           desc=value_or_column(c["agenda_desc"] and c["agenda_desc_tag"],
                                "Description"))
    else:
        target = sql_str(c["agenda"])
        out = "-- AI agenda: {} instead of {}'s own\n".format(c["agenda"], orig)
    return out + """INSERT INTO HistoricalAgendas (LeaderType, AgendaType)
SELECT '{slug}', AgendaType FROM Agendas WHERE AgendaType = {target};
-- ...or the original leader's agenda if that one does not exist here
INSERT INTO HistoricalAgendas (LeaderType, AgendaType)
SELECT '{slug}', AgendaType FROM HistoricalAgendas WHERE LeaderType = '{orig}'
AND NOT EXISTS (SELECT 1 FROM Agendas WHERE AgendaType = {target});
""".format(slug=slug, orig=orig, target=target)


# Tables of rules a trait sets besides its modifiers: {table: the other
# key column}. A renamed ability copies their rows.
TRAIT_RULE_TABLES = {
    "ExcludedAdjacencies": "YieldChangeId",
    "ExcludedDistricts": "DistrictType",
    "ExcludedGreatPersonClasses": "GreatPersonClassType",
}


def ability_block(c):
    """LeaderTraits SQL for one leader: the original leader's traits, with
    a renamed copy in place of each ability given a new name /
    description. A copy has the same modifiers, rules and AI preference
    lists, so it plays the same; only its text differs."""
    slug, orig = c["slug"], c["orig"]
    if not c["abilities"]:
        return """-- INHERIT the leader ability
INSERT INTO LeaderTraits (LeaderType, TraitType)
SELECT '{slug}', TraitType FROM LeaderTraits WHERE LeaderType = '{orig}';
""".format(slug=slug, orig=orig)

    out = ["""-- INHERIT the leader ability, except the renamed copies below
INSERT INTO LeaderTraits (LeaderType, TraitType)
SELECT '{slug}', TraitType FROM LeaderTraits WHERE LeaderType = '{orig}'
AND TraitType NOT IN ({renamed});
""".format(slug=slug, orig=orig, renamed=", ".join(
        sql_str(a["source"]) for a in c["abilities"]))]
    for a in c["abilities"]:
        rules = "".join("""
INSERT INTO {table} (TraitType, {column})
SELECT {new}, {column} FROM {table} WHERE TraitType = {source};
""".format(table=table, column=column, new=sql_str(a["type"]),
           source=sql_str(a["source"]))
            for table, column in TRAIT_RULE_TABLES.items())
        out.append("""
-- {source} with its own name / description. Nothing is copied if that
-- trait does not exist in the current ruleset.
INSERT INTO Types (Type, Kind)
SELECT {new}, Kind FROM Types WHERE Type = {source};

INSERT INTO Traits (TraitType, Name, Description, InternalOnly)
SELECT {new}, {name}, {desc}, InternalOnly
FROM Traits WHERE TraitType = {source};

INSERT INTO TraitModifiers (TraitType, ModifierId)
SELECT {new}, ModifierId FROM TraitModifiers WHERE TraitType = {source};
{rules}
-- the AI's preference lists for the trait, copied for the new one
INSERT INTO AiListTypes (ListType)
SELECT ListType || {suffix} FROM AiLists WHERE LeaderType = {source};
INSERT INTO AiLists (ListType, LeaderType, AgendaType, System, MinDifficulty, MaxDifficulty)
SELECT ListType || {suffix}, {new}, AgendaType, System, MinDifficulty, MaxDifficulty
FROM AiLists WHERE LeaderType = {source};
INSERT INTO AiFavoredItems (ListType, Item, Favored, Value, StringVal, MinDifficulty, MaxDifficulty, TooltipString)
SELECT ListType || {suffix}, Item, Favored, Value, StringVal, MinDifficulty, MaxDifficulty, TooltipString
FROM AiFavoredItems
WHERE ListType IN (SELECT ListType FROM AiLists WHERE LeaderType = {source});

INSERT INTO LeaderTraits (LeaderType, TraitType)
SELECT '{slug}', TraitType FROM Traits WHERE TraitType = {new};
""".format(source=sql_str(a["source"]), new=sql_str(a["type"]),
           slug=slug, rules=rules,
           suffix=sql_str("_" + slug[len("LEADER_"):]),
           name=value_or_column(a["name"] and a["name_tag"], "Name"),
           desc=value_or_column(a["desc"] and a["desc_tag"],
                                "Description")))
    return "".join(out)


def capital_block(c):
    """CivilizationLeaders row: the first custom city name as capital, or
    the original leader's capital."""
    if c["city_names"]:
        return """-- capital: the first of this leader's own city names
INSERT INTO CivilizationLeaders (CivilizationType, LeaderType, CapitalName)
VALUES ('{civ}', '{slug}', '{capital}');
""".format(civ=c["civ"], slug=c["slug"], capital=c["city_names"][0][0])
    return """-- CapitalName is NOT NULL; reuse the original leader's capital
INSERT INTO CivilizationLeaders (CivilizationType, LeaderType, CapitalName)
SELECT '{civ}', '{slug}', CapitalName
FROM CivilizationLeaders WHERE LeaderType = '{orig}';
""".format(civ=c["civ"], slug=c["slug"], orig=c["orig"])


def city_names_block(c):
    """Leader-specific CityNames rows (none: the civilization's names).
    SortIndex -1 puts them before the civilization's own names (0)."""
    if not c["city_names"]:
        return ""
    rows = ",\n".join("('{}', '{}', -1, '{}')".format(c["civ"], c["slug"],
                                                       tag)
                      for tag, _ in c["city_names"])
    return """
-- this leader's own city names, used before the civilization's
INSERT INTO CityNames (CivilizationType, LeaderType, SortIndex, CityName)
VALUES
{rows};
""".format(rows=rows)


def scene_block(c):
    """AltLeaderScenes row: show the original leader's layered diplomacy
    scene (or, for a generated original, the scene it shows)."""
    if not c["scene_from_orig"]:
        return ""
    return """
-- no diplomacy background of its own (and {orig} has no DiplomacyInfo
-- image to copy): show {orig}'s layered scene
INSERT OR REPLACE INTO AltLeaderScenes (LeaderType, SceneLeaderType)
SELECT '{slug}', COALESCE((SELECT SceneLeaderType FROM AltLeaderScenes
                           WHERE LeaderType = '{orig}'), '{orig}');
""".format(slug=c["slug"], orig=c["orig"])


def gameplay_block(c):
    """Core gameplay SQL fragment for one leader."""
    return """-----------------------------------------------
-- {name} ({slug})
-----------------------------------------------
INSERT INTO Types (Type, Kind)
VALUES ('{slug}', 'KIND_LEADER');

-- InheritFrom is copied from {orig} (normally LEADER_DEFAULT), like the
-- official personas (LEADER_SALADIN_ALT etc.). Inheriting from {orig}
-- itself would make the UI list its ability twice: GetLeaderUniqueTraits
-- adds the InheritFrom leader's traits on top of our LeaderTraits copy.
INSERT INTO Leaders (LeaderType, Name, InheritFrom, Sex, SceneLayers)
SELECT '{slug}', '{name_tag}', InheritFrom, {sex}, SceneLayers
FROM Leaders WHERE LeaderType = '{orig}';

{capital}{city_names}
{ability}
{agenda}
-- Loading screen: this leader's own bio; images are custom or inherited
INSERT INTO LoadingInfo (LeaderType, ForegroundImage, BackgroundImage, PlayDawnOfManAudio, EraText, LeaderText)
SELECT '{slug}', {load_fg}, {load_bg}, PlayDawnOfManAudio, EraText, '{bio_tag}'
FROM LoadingInfo WHERE LeaderType = '{orig}';

INSERT INTO LeaderQuotes (LeaderType, Quote)
VALUES ('{slug}', '{quote_tag}');

-- Diplomacy-screen background. Without a DiplomacyInfo row LeaderScene.lua
-- looks for layered textures named after the leader type, which a
-- generated leader does not have.
INSERT INTO DiplomacyInfo (Type, BackgroundImage)
SELECT '{slug}', {diplo_bg}{diplo_from};
{scene}""".format(name=c["name"], slug=c["slug"], name_tag=c["name_tag"],
           agenda=agenda_block(c), ability=ability_block(c),
           capital=capital_block(c),
           scene=scene_block(c),
           city_names=city_names_block(c),
           diplo_bg=value_or_column(c["diplo_bg"], "BackgroundImage"),
           diplo_from="" if c["diplo_bg"] else
           "\nFROM DiplomacyInfo WHERE Type = '{}'".format(c["orig"]),
           orig=c["orig"], sex=sql_str(c["sex"]), civ=c["civ"],
           bio_tag=c["bio_tag"], quote_tag=c["quote_tag"],
           load_fg=value_or_column(c["load_fg"], "ForegroundImage"),
           load_bg=value_or_column(c["load_bg"], "BackgroundImage"))


def text_rows(c):
    """Localization row literals for one leader."""
    def row(tag, text):
        return "({}, {}, {})".format(sql_str("en_US"), sql_str(tag),
                                     sql_str(text))

    texts = c["texts"]
    rows = [
        row(c["name_tag"], c["name"]),
        row(c["bio_tag"], c["bio"]),
        row(c["quote_tag"], c["quote"]),
        row(PEDIA_PREFIX.format(L=c["slug"]) + "TITLE",
            loc_text(texts.get(PEDIA_PREFIX + "TITLE") or c["name"])),
    ]
    rows += [row(tag, city) for tag, city in c["city_names"]]
    pairs = [(c["agenda_name_tag"], c["agenda_name"]),
             (c["agenda_desc_tag"], c["agenda_desc"])]
    for a in c["abilities"]:
        pairs += [(a["name_tag"], a["name"]), (a["desc_tag"], a["desc"])]
    for tag, text in pairs:
        if text:
            rows.append(row(tag, loc_text(text)))
    keys = [k for _, lines in DIPLO_TEXT for k, _ in lines]
    keys += [k for k, _, _, _ in PEDIA_TEXT
             if k not in (PEDIA_PREFIX + "TITLE", PEDIA_HISTORY)]
    for key in keys:
        if texts.get(key):
            rows.append(row(key.format(L=c["slug"]), loc_text(texts[key])))
    for i, para in enumerate(history_paragraphs(texts.get(PEDIA_HISTORY)),
                             1):
        rows.append(row("{}_PARA_{}".format(
            PEDIA_HISTORY.format(L=c["slug"]), i), loc_text(para)))
    return rows


def inherited_text_sql(c):
    """Empty diplomacy lines (and pedia strategy text) reuse the original
    leader's text, in every language the game has it in."""
    keys = [k for _, lines in DIPLO_TEXT for k, _ in lines]
    keys += [k for k, _, _, inherit in PEDIA_TEXT if inherit]
    out = []
    for key in keys:
        if c["texts"].get(key):
            continue
        for candidate in inherit_candidates(key):
            # OR IGNORE: the first candidate that exists wins
            out.append(
                "INSERT OR IGNORE INTO LocalizedText (Language, Tag, Text)\n"
                "SELECT Language, {}, Text FROM LocalizedText "
                "WHERE Tag = {};".format(
                    sql_str(key.format(L=c["slug"])),
                    sql_str(candidate.format(L=c["orig"]))))
    return out


def colors_fragment(c):
    """(color rows XML, playercolors row XML) for one leader."""
    p, s = c["primary"], c["secondary"]
    entries = [("PRIMARY", 255), ("PRIMARY1", 125), ("PRIMARY2", 200),
               ("PRIMARY3", 175)]
    color_rows = "\n".join(
        "    <Row><Type>COLOR_PLAYER_{slug}_{key}</Type>"
        "<Color>{r},{g},{b},{a}</Color></Row>".format(
            slug=c["slug"], key=key, r=p[0], g=p[1], b=p[2], a=a)
        for key, a in entries)
    color_rows += "\n    <Row><Type>COLOR_PLAYER_{slug}_SECONDARY</Type>" \
                  "<Color>{r},{g},{b},255</Color></Row>".format(
                      slug=c["slug"], r=s[0], g=s[1], b=s[2])
    player_row = """    <Row>
      <Type>{slug}</Type>
      <Usage>Unique</Usage>
      <PrimaryColor>COLOR_PLAYER_{slug}_PRIMARY</PrimaryColor>
      <SecondaryColor>COLOR_PLAYER_{slug}_SECONDARY</SecondaryColor>
      <Alt1PrimaryColor>COLOR_PLAYER_{slug}_PRIMARY1</Alt1PrimaryColor>
      <Alt1SecondaryColor>COLOR_PLAYER_{slug}_SECONDARY</Alt1SecondaryColor>
      <Alt2PrimaryColor>COLOR_PLAYER_{slug}_PRIMARY2</Alt2PrimaryColor>
      <Alt2SecondaryColor>COLOR_PLAYER_{slug}_SECONDARY</Alt2SecondaryColor>
      <Alt3PrimaryColor>COLOR_PLAYER_{slug}_PRIMARY3</Alt3PrimaryColor>
      <Alt3SecondaryColor>COLOR_PLAYER_{slug}_SECONDARY</Alt3SecondaryColor>
    </Row>""".format(slug=c["slug"])
    return color_rows, player_row


def icons_fragment(c, icon_files):
    """(atlas rows XML, definition rows XML) for one leader's custom icon.
    icon_files: (size, texture name) pairs; Filename is the name of the
    texture inside the cooked .blp, not a file path."""
    atlas_rows = "\n".join(
        '    <Row Name="{atlas}" IconSize="{size}" IconsPerRow="1" '
        'IconsPerColumn="1" Filename="{texture}"/>'.format(
            atlas=c["icon_atlas"], size=size, texture=texture)
        for size, texture in icon_files)
    def_row = ('    <Row Name="{icon}" Atlas="{atlas}" Index="0"/>'
               .format(icon=c["icon_name"], atlas=c["icon_atlas"]))
    return atlas_rows, def_row


# ---------------------------------------------------------------------------
# Whole-mod file builders
# ---------------------------------------------------------------------------

# Every action needs a unique id attribute - the game silently skips
# actions without one. The high LoadOrder makes our SQL run after DLC
# content, so INSERT ... SELECT can copy rows of DLC leaders too.
ICONS_ACTION = ("\n    <UpdateIcons id=\"{scope}Icons\">\n"
                "      <File>Config/NewLeader_Icons.xml</File>\n"
                "    </UpdateIcons>")
ART_ACTION = ("\n    <UpdateArt id=\"{scope}Art\">\n"
              "      <File>{dep}</File>\n"
              "    </UpdateArt>")


# Historic moments only exist with Rise and Fall / Gathering Storm; without
# them the MomentIllustrations table is missing, so the rows get their own
# action that only runs then (criteria as in Firaxis' DLC modinfos).
EXPANSION_CRITERIA = """
  <ActionCriteria>
    <Criteria id="Expansion1AndBeyond" any="1">
      <GameCoreInUse>Expansion1</GameCoreInUse>
      <GameCoreInUse>Expansion2</GameCoreInUse>
      <RuleSetInUse>RULESET_EXPANSION_1,RULESET_EXPANSION_2</RuleSetInUse>
    </Criteria>
  </ActionCriteria>"""
MOMENTS_FILE = "Gameplay/NewLeader_Moments.sql"
MOMENTS_ACTION = """
    <UpdateDatabase id="InGameMoments">
      <Properties><LoadOrder>1000</LoadOrder></Properties>
      <Criteria>Expansion1AndBeyond</Criteria>
      <File>{}</File>
    </UpdateDatabase>""".format(MOMENTS_FILE)


# Diplomacy-screen backgrounds. LeaderScene.lua shows DiplomacyInfo's single
# image if the leader has one, else the layered scene textures named after
# the leader type (VICTORIA_1..SceneLayers). Base-game leaders have no
# DiplomacyInfo row, and a generated leader has no layers under its own
# name, so the mod ships a copy of the game's LeaderScene.lua that shows
# the scene of the leader named in AltLeaderScenes instead. All generated
# packs share the table and the patch, so whichever copy wins works for
# every pack.
LEADER_SCENE_FILE = "UI/LeaderScene.lua"
LEADER_SCENE_SOURCE = os.path.join("Base", "Assets", "UI", "LeaderScene.lua")
LEADER_SCENE_ANCHOR = "m_oldLeaderName = leaderName;"
LEADER_SCENE_PATCH = """
		-- Alt Leader Generator: a leader without a diplomacy background of
		-- its own shows the scene of the leader it was made from.
		local altInfo = GameInfo.DiplomacyInfo[leaderName];
		local altScene = GameInfo.AltLeaderScenes and GameInfo.AltLeaderScenes[leaderName];
		if altScene and not (altInfo and altInfo.BackgroundImage) and GameInfo.Leaders[altScene.SceneLeaderType] then
			leaderName = altScene.SceneLeaderType;
		end"""
LEADER_SCENE_ACTION = """
    <ImportFiles id="InGameLeaderScene">
      <File>{}</File>
    </ImportFiles>""".format(LEADER_SCENE_FILE)
ALT_SCENES_TABLE = """-- leader -> leader whose layered diplomacy scene it shows (read by this
-- mod's UI/LeaderScene.lua; shared by every generated alt-leader pack)
CREATE TABLE IF NOT EXISTS AltLeaderScenes (
	LeaderType TEXT NOT NULL PRIMARY KEY,
	SceneLeaderType TEXT NOT NULL);
"""


def patched_leader_scene(game_dir):
    """The game's LeaderScene.lua with LEADER_SCENE_PATCH added, or
    (None, reason) when it cannot be patched. Returns (text, None)."""
    if not game_dir:
        return None, "the Civ VI install folder was not found"
    path = os.path.join(game_dir, LEADER_SCENE_SOURCE)
    try:
        with open(path, encoding="utf-8-sig") as fh:
            text = fh.read()
    except OSError as exc:
        return None, "cannot read {} ({})".format(path, exc)
    if "AltLeaderScenes" in text:
        return text, None               # already patched
    if text.count(LEADER_SCENE_ANCHOR) != 1:
        return None, "{} has changed; cannot patch it".format(path)
    return text.replace(LEADER_SCENE_ANCHOR,
                        LEADER_SCENE_ANCHOR + LEADER_SCENE_PATCH), None


def build_modinfo(mod_name, description, guid, has_icons, dep_file, files,
                  has_moments=False, has_scene=False):
    """dep_file: mod-relative .dep path when cooked art exists, else None.
    has_moments: add the expansion-only historic moment action.
    has_scene: import the patched UI/LeaderScene.lua."""
    def icons(scope):
        out = ICONS_ACTION.format(scope=scope) if has_icons else ""
        if dep_file:
            out += ART_ACTION.format(scope=scope, dep=xml_escape(dep_file))
        if scope == "InGame" and has_moments:
            out += MOMENTS_ACTION
        if scope == "InGame" and has_scene:
            out += LEADER_SCENE_ACTION
        return out

    return """<?xml version="1.0" encoding="utf-8"?>
<Mod id="{guid}" version="1">
  <Properties>
    <Name>{mod_name}</Name>
    <Teaser>Alternate leaders for existing civilizations</Teaser>
    <Description>{description}</Description>
    <Authors>Generated by Alt Leader Generator</Authors>
    <AffectsSavedGames>0</AffectsSavedGames>
    <CompatibleVersions>1.2,2.0</CompatibleVersions>
  </Properties>
  <Dependencies/>{criteria}
  <InGameActions>
    <UpdateDatabase id="InGameDatabase">
      <Properties><LoadOrder>1000</LoadOrder></Properties>
      <File>Gameplay/NewLeader_Gameplay.sql</File>
    </UpdateDatabase>{ingame_icons}
    <UpdateColors id="InGameColors">
      <File>Config/NewLeader_Colors.xml</File>
    </UpdateColors>
    <UpdateText id="InGameText">
      <Properties><LoadOrder>1000</LoadOrder></Properties>
      <File>Text/NewLeader_Text.sql</File>
    </UpdateText>
  </InGameActions>
  <FrontEndActions>
    <UpdateDatabase id="FrontEndDatabase">
      <Properties><LoadOrder>1000</LoadOrder></Properties>
      <File>Config/NewLeader_Config.sql</File>
    </UpdateDatabase>{frontend_icons}
    <UpdateColors id="FrontEndColors">
      <File>Config/NewLeader_Colors.xml</File>
    </UpdateColors>
    <UpdateText id="FrontEndText">
      <Properties><LoadOrder>1000</LoadOrder></Properties>
      <File>Text/NewLeader_Text.sql</File>
    </UpdateText>
  </FrontEndActions>
  <Files>
{files}
  </Files>
</Mod>
""".format(guid=guid, mod_name=xml_escape(mod_name),
           description=xml_escape(description),
           ingame_icons=icons("InGame"), frontend_icons=icons("FrontEnd"),
           criteria=EXPANSION_CRITERIA if has_moments
           else "\n  <ActionCriteria/>",
           files="\n".join("    <File>{}</File>".format(xml_escape(f))
                           for f in files))


def build_config_sql(ctxs):
    return "\n".join(config_block(c) for c in ctxs)


def build_gameplay_sql(ctxs):
    head = ALT_SCENES_TABLE if any(c["scene_from_orig"] for c in ctxs) \
        else ""
    return head + "\n\n".join(gameplay_block(c) for c in ctxs)


def build_moments_sql(ctxs):
    """Custom pictures for the engine's 'first unique ...' historic
    moments. OR REPLACE: the row replaces Firaxis' picture for that item."""
    rows = ["({}, {}, {}, {})".format(
        sql_str(m["illustration"]), sql_str(m["data_type"]),
        sql_str(m["item"]), sql_str(m["texture"] + ".dds"))
        for c in ctxs for m in c["moments"]]
    return ("-- Historic moment illustrations (Rise and Fall / Gathering "
            "Storm only).\n"
            "INSERT OR REPLACE INTO MomentIllustrations\n"
            "    (MomentIllustrationType, MomentDataType, GameDataType, "
            "Texture)\nVALUES\n{};\n".format(",\n".join(rows)))


def build_text_sql(ctxs):
    rows = []
    for c in ctxs:
        rows.extend(text_rows(c))
    inherited = []
    for c in ctxs:
        lines = inherited_text_sql(c)
        if lines:
            inherited.append("\n-- {}: lines left empty reuse the text of {}"
                             .format(c["name"], c["orig"]))
            inherited.extend(lines)
    return ("-- All customizable text for {} leader(s).\n"
            "INSERT OR REPLACE INTO LocalizedText (Language, Tag, Text) "
            "VALUES\n{};\n{}\n".format(len(ctxs), ",\n".join(rows),
                                        "\n".join(inherited)))


def build_colors_xml(ctxs):
    color_rows, player_rows = [], []
    for c in ctxs:
        cr, pr = colors_fragment(c)
        color_rows.append(cr)
        player_rows.append(pr)
    return """<?xml version="1.0" encoding="utf-8"?>
<!-- Leader colors: city banners, map tint, diplo screen tint. -->
<GameData>
  <Colors>
{colors}
  </Colors>
  <PlayerColors>
{players}
  </PlayerColors>
</GameData>
""".format(colors="\n".join(color_rows), players="\n".join(player_rows))


def build_icons_xml(icon_leader_files):
    """icon_leader_files: list of (ctx, icon_files)."""
    atlas_rows, def_rows = [], []
    for c, files in icon_leader_files:
        ar, dr = icons_fragment(c, files)
        atlas_rows.append(ar)
        def_rows.append(dr)
    return """<?xml version="1.0" encoding="utf-8"?>
<!-- Leader icon atlases. The .dds files live in the Art/ folder and are
     referenced relative to the mod root. -->
<GameData>
  <IconTextureAtlases>
{atlases}
  </IconTextureAtlases>
  <IconDefinitions>
{defs}
  </IconDefinitions>
</GameData>
""".format(atlases="\n".join(atlas_rows), defs="\n".join(def_rows))


def readme_agenda(c):
    """README note on a leader's agenda, or "" if it is the original's."""
    if not c["agenda"] and not c["agenda_clone"]:
        return ""
    note = ", agenda: " + (c["agenda"] or "inherited")
    if c["agenda_name"]:
        note += ' renamed "{}"'.format(c["agenda_name"])
    elif c["agenda_clone"]:
        note += " with a new description"
    return note


def readme_abilities(c):
    """README note on a leader's renamed abilities, or ""."""
    return "".join(
        ", ability {}{}".format(a["source"], ' renamed "{}"'.format(a["name"])
                                if a["name"] else " with a new description")
        for a in c["abilities"])


def build_readme(mod_name, ctxs, icon_count, report):
    lines = "\n".join(
        "  * {name} ({slug}) - {civ}, inherits {orig}{ability}{agenda}"
        "{cities}".format(
            name=c["name"], slug=c["slug"], civ=c["civ"], orig=c["orig"],
            ability=readme_abilities(c), agenda=readme_agenda(c),
            cities="; {} own city names, capital {}".format(
                len(c["city_names"]), c["city_names"][0][1])
            if c["city_names"] else "")
        for c in ctxs)
    return """{mod_name} (generated)
======================================================

An alternate-leader pack. Each leader inherits the ability of its
original leader and, unless another one was chosen, its AI agenda, and
shares the civilization's uniques. All gameplay effects are inherited;
everything textual and visual is defined by this mod's own files.

LEADERS
{lines}

FILES
  MyLeader.modinfo              mod registration
  Config/NewLeader_Config.sql   setup screen rows (Players / PlayerItems)
  Config/NewLeader_Icons.xml    leader icon atlases ({icon_count} custom)
  Config/NewLeader_Colors.xml    leader colors
  Gameplay/NewLeader_Gameplay.sql leaders, trait & agenda inheritance
  Gameplay/NewLeader_Moments.sql  historic moment pictures (if any;
                                  Rise and Fall / Gathering Storm only)
  Text/NewLeader_Text.sql       names, bios, quotes, diplomacy lines,
                                Civilopedia
  <ModFolder>.dep                art dependencies (loads the cooked .blp)
  Platforms/*/BLPs/              cooked icons, loading-screen and
                                 diplomacy (fallback) images
  ArtDefs/FallbackLeaders.artdef diplomacy-screen image per leader

INSTALL
  Copy this folder into:
    Documents/My Games/Sid Meier's Civilization VI/Mods
  Enable it under Additional Content. If anything misbehaves, check
  Logs/Database.log in that same folder.

NOTES
  * The leader ability (traits) and its name/description are those of
    the original leader.
  * No 3D leader scene is generated; the diplomacy screen shows the 2D
    fallback image made from the loading portrait. A 3D scene requires
    the Blender -> Asset Editor art pipeline and is outside this
    generator's scope.
  * Custom icons, loading portraits, loading backgrounds and diplomacy
    backgrounds are cooked into .blp packages with the Civ VI SDK asset
    cooker (install "Sid Meier's Civilization VI Development Tools" from
    Steam). The loading portrait is also used as the setup-screen
    portrait and the diplomacy-screen leader image. Art that is not
    customized is inherited from the original leader. Base-game leaders'
    diplomacy backgrounds are layered scenes that the database cannot
    point to, so leaders without a custom diplomacy background get a
    patched copy of the game's UI/LeaderScene.lua that shows the original
    leader's scene (listed in the AltLeaderScenes table). Another mod
    that also replaces LeaderScene.lua can override it.
  * Historic moment pictures replace the picture of the engine's
    "first unique unit / building / district / improvement" moments for
    that item. Mods cannot add new moments (their triggers are engine
    code), the picture is per item (so it applies to every leader of the
    civilization), and tech/civic moment pictures depend on the era only.
  * The "fade mask" options use the generator's assets/mask.png
    (diplomacy background) and assets/mask_historical.png (historic
    moment pictures, stretched to 456 x 332): white keeps the image, black
    becomes transparent. Historic moment pictures can also be made 50%
    transparent and/or sepia-toned. A packaged generator needs the
    assets folder next to the exe, or built in with Nuitka
    --include-data-dir=assets=assets.
  * Leaders with their own city names found their capital under the
    first name and name new cities from their list first; once it runs
    out, the civilization's own names are used.
  * Leaders inheriting from DLC leaders require that DLC installed;
    add <Dependencies> entries to the .modinfo to enforce it.

GENERATION LOG
{log}
""".format(mod_name=mod_name, lines=lines, icon_count=icon_count,
           log="\n".join("  " + r for r in report))


# ---------------------------------------------------------------------------
# Leader editor dialog
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Leader icon cut out of the loading portrait
# ---------------------------------------------------------------------------

DEFAULT_ICON_BORDER_COLOR = (0, 0, 0)     # black
DEFAULT_ICON_BORDER_WIDTH = 5                 # pixels at 256 x 256


PORTRAIT_SIZE = (800, 1080)     # every loading portrait is fitted to this


def _portrait_placement(width, height):
    """(scale, left, top) that fits a width x height image inside
    PORTRAIT_SIZE, centred horizontally and resting on the bottom edge."""
    pw, ph = PORTRAIT_SIZE
    scale = min(pw / float(width), ph / float(height))
    w, h = max(1, int(round(width * scale))), max(1, int(round(height * scale)))
    return scale, (pw - w) // 2, ph - h


def fit_portrait(src):
    """The loading portrait at src as a PORTRAIT_SIZE RGBA image: scaled to
    fit (aspect kept), centred horizontally, aligned to the bottom, with a
    transparent margin."""
    from PIL import Image
    img = Image.open(src).convert("RGBA")
    scale, left, top = _portrait_placement(*img.size)
    size = (max(1, int(round(img.width * scale))),
            max(1, int(round(img.height * scale))))
    out = Image.new("RGBA", PORTRAIT_SIZE, (0, 0, 0, 0))
    out.alpha_composite(img.resize(size, Image.LANCZOS), (left, top))
    return out


def fit_icon_crop(crop, src):
    """Convert an icon crop chosen on the unfitted portrait at src (projects
    from before portraits were fitted) to fitted-portrait pixels."""
    from PIL import Image
    scale, left, top = _portrait_placement(*Image.open(src).size)
    cx, cy, r = crop
    return (cx * scale + left, cy * scale + top, r * scale)


def default_icon_crop(width, height):
    """(center x, center y, radius) in source pixels. Faces usually sit
    in the upper part of a leader portrait."""
    r = min(width, height) * 0.3
    return (width / 2.0, max(r, min(height * 0.35, height - r)), r)


def default_image_crop(img):
    """default_icon_crop for a Pillow image, within its non-transparent
    part (a fitted portrait can have transparent margins)."""
    left, top, right, bottom = (img.getchannel("A").getbbox()
                                if img.mode == "RGBA" else None) or         (0, 0) + img.size
    cx, cy, r = default_icon_crop(right - left, bottom - top)
    return (cx + left, cy + top, r)


def make_circle_icon(src, crop, border_color=DEFAULT_ICON_BORDER_COLOR,
                     border_width=DEFAULT_ICON_BORDER_WIDTH, size=512):
    """Cut a circle out of an image and put a border ring around it.

    src: a path or a Pillow image. crop: (center x, center y, radius) in
    source pixels, or None for default_icon_crop. border_width is in
    pixels of a 256 x 256 icon and scales with size. Areas of the circle
    outside the image stay transparent. Returns a size x size RGBA image
    with transparent corners."""
    from PIL import Image, ImageChops, ImageDraw
    img = src if isinstance(src, Image.Image) else \
        Image.open(src).convert("RGBA")
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    cx, cy, r = crop or default_image_crop(img)
    box = tuple(int(round(v)) for v in (cx - r, cy - r, cx + r, cy + r))
    face = img.crop(box).resize((size, size), Image.LANCZOS)   # pads out of
                                                               # bounds with 0
    ss = 4                                     # supersampling for smooth edges
    big = size * ss

    def disc(inset=0.0):
        mask = Image.new("L", (big, big), 0)
        ImageDraw.Draw(mask).ellipse(
            (inset, inset, big - 1 - inset, big - 1 - inset), fill=255)
        return mask

    outer = disc()
    face.putalpha(ImageChops.multiply(face.getchannel("A"),
                                      outer.resize((size, size),
                                                   Image.LANCZOS)))
    if border_width <= 0:
        return face
    ring = ImageChops.subtract(outer, disc(border_width * size / 256.0 * ss))
    ring = ring.resize((size, size), Image.LANCZOS)
    color = Image.new("RGBA", (size, size), tuple(border_color) + (255,))
    # outside the circle the face is transparent, so the ring's
    # anti-aliased outer edge blends into transparency
    return Image.composite(color, face, ring)


APP_ICON = "icon.png"
DIPLO_BG_MASK = "mask.png"
MOMENT_MASK = "mask_historical.png"
MOMENT_HALF_OPACITY = 0.5


def asset_path(name):
    """Path of assets/<name> shipped with the generator, or None. Looks next
    to this file (script, or Nuitka's onefile extraction folder when built
    with --include-data-dir=assets=assets) and next to the executable."""
    bases = [os.path.dirname(os.path.abspath(__file__)),
             os.path.dirname(os.path.abspath(sys.executable)),
             os.path.dirname(os.path.abspath(sys.argv[0] or "."))]
    for base in bases:
        path = os.path.join(base, "assets", name)
        if os.path.isfile(path):
            return path
    return None


SEPIA_TONES = ("#2b1d0e", "#8c6a43", "#f4e6c8")   # shadows, mid, highlights


def apply_image_mask(src, mask_path, size=None, opacity=1.0, sepia=False):
    """Fade an image out with a greyscale mask: white keeps the image,
    black makes it transparent, grey partially. The image is centre-cropped
    and resized to size (default: the mask's size); the mask is stretched
    to that size, since it acts as a frame. mask_path may be None to only
    apply opacity (0..1, multiplies the alpha). sepia recolours the image
    in SEPIA_TONES. Returns an RGBA image."""
    from PIL import Image, ImageChops, ImageOps
    mask = Image.open(mask_path).convert("L") if mask_path else None
    size = tuple(size or mask.size)
    img = ImageOps.fit(Image.open(src).convert("RGBA"), size, Image.LANCZOS)
    alpha = img.getchannel("A")
    if sepia:
        dark, mid, light = SEPIA_TONES
        img = ImageOps.colorize(img.convert("L"), black=dark, white=light,
                                mid=mid).convert("RGBA")
    if mask is not None:
        alpha = ImageChops.multiply(alpha, mask.resize(size, Image.LANCZOS))
    if opacity < 1.0:
        alpha = alpha.point(lambda a: int(round(a * opacity)))
    img.putalpha(alpha)
    return img


# ---------------------------------------------------------------------------
# Previews (Pillow images for the GUI; cached, since sources can be large)
# ---------------------------------------------------------------------------

PREVIEW_BACKDROP = (43, 43, 43, 255)
PREVIEW_BOX = (208, 117)                  # 16:9, like the screens
LIST_ICON_SIZE = 32
_preview_cache = {}


def _cached(key_parts, path, make):
    """make() cached on key_parts plus the file's modification time, so an
    edited image is picked up again."""
    try:
        key = key_parts + (os.path.abspath(path), os.path.getmtime(path))
    except OSError:
        return None
    if key not in _preview_cache:
        if len(_preview_cache) > 200:
            _preview_cache.clear()
        _preview_cache[key] = make()
    return _preview_cache[key]


def fitted_portrait(path):
    """fit_portrait(path), cached. Raises ImportError without Pillow."""
    return _cached(("portrait",), path, lambda: fit_portrait(path))


def preview_image(path, box, mask_path=None, portrait=False):
    """The image at path fitted into box (w, h) and centred on a dark
    backdrop of that size, so transparency shows. With mask_path the image
    is faded out with that mask first (cropped to the mask's aspect, like
    the generated texture). portrait: show path fitted like a loading
    portrait (fit_portrait). Returns an RGBA image or None if path is not
    a file. Raises ImportError without Pillow."""
    from PIL import Image
    if not path or not os.path.isfile(path):
        return None

    def make():
        if mask_path:
            mw, mh = Image.open(mask_path).size
            scale = min(box[0] / float(mw), box[1] / float(mh))
            img = apply_image_mask(path, mask_path,
                                   size=(max(1, int(mw * scale)),
                                         max(1, int(mh * scale))))
        elif portrait:
            img = fitted_portrait(path).copy()
            img.thumbnail(box, Image.LANCZOS)
        else:
            img = Image.open(path)
            img.draft("RGB", box)       # fast JPEG downscale on load
            img = img.convert("RGBA")
            img.thumbnail(box, Image.LANCZOS)
        out = Image.new("RGBA", tuple(box), PREVIEW_BACKDROP)
        out.alpha_composite(img, ((box[0] - img.width) // 2,
                                  (box[1] - img.height) // 2))
        return out
    return _cached(("preview", tuple(box), mask_path, portrait), path, make)


def placeholder_icon(name, primary, secondary, size):
    """A round icon in the leader's colors with their initials, for leaders
    whose icon is inherited from the original leader."""
    from PIL import Image, ImageDraw, ImageFont
    ss = 4
    big = size * ss
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((0, 0, big - 1, big - 1), fill=tuple(secondary))
    inset = max(ss, big // 16)
    draw.ellipse((inset, inset, big - 1 - inset, big - 1 - inset),
                 fill=tuple(primary))
    initials = "".join(w[0] for w in (name or "?").split()[:2]).upper()
    try:
        font = ImageFont.load_default(size=int(big * 0.4))
        draw.text((big / 2.0, big / 2.0), initials, fill=tuple(secondary),
                  font=font, anchor="mm")
    except (TypeError, ValueError):     # old Pillow: no scalable font
        pass
    return img.resize((size, size), Image.LANCZOS)


def leader_icon_preview(spec, size):
    """The icon the generator will make for spec (size x size RGBA), or
    a placeholder in the leader's colors when the icon is inherited.
    Raises ImportError without Pillow."""
    from PIL import Image
    icon = None
    try:
        if spec_icon_mode(spec) == "portrait":
            src = (spec.get("load_fg_path") or "").strip()
            crop = spec.get("icon_crop")
            color = tuple(spec.get("icon_border_color") or
                          DEFAULT_ICON_BORDER_COLOR)
            width = int(spec.get("icon_border_width",
                                 DEFAULT_ICON_BORDER_WIDTH))
            icon = _cached(("circle", size, tuple(crop) if crop else None,
                            color, width), src,
                           lambda: make_circle_icon(fitted_portrait(src), crop,
                                                    color, width, size=size))
        else:
            src = (spec.get("icon_path") or "").strip()

            def make():
                img = Image.open(src).convert("RGBA")
                img.thumbnail((size, size), Image.LANCZOS)
                out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
                out.alpha_composite(img, ((size - img.width) // 2,
                                          (size - img.height) // 2))
                return out
            icon = _cached(("icon", size), src, make)
    except Exception:                   # unreadable image
        icon = None
    return icon or placeholder_icon(
        spec.get("name"), spec.get("primary") or (30, 90, 170),
        spec.get("secondary") or (230, 230, 230), size)


# ---------------------------------------------------------------------------
# Leader export / import (move leaders between projects or machines)
# ---------------------------------------------------------------------------

# An export is a zip: leaders.json (the specs, as JSON rather than a pickle
# so importing one is safe) plus a copy of every image the leaders use.
LEADERS_MAGIC = "civ6-alt-leader-generator-leaders"
LEADERS_ENTRY = "leaders.json"
IMAGE_KEYS = ("icon_path", "load_fg_path", "load_bg_path", "diplo_bg_path")
TUPLE_KEYS = ("primary", "secondary", "icon_border_color", "icon_crop")


def _spec_images(spec):
    """(holder, key) of every image path a leader spec refers to."""
    refs = [(spec, key) for key in IMAGE_KEYS]
    refs += [(entry, "path") for entry in spec.get("moment_illustrations")
             or []]
    return refs


def export_leaders(specs, path):
    """Write leader specs and their images to the zip at path. Returns
    the image paths that were not found (exported as bare paths)."""
    images = {}                         # original path -> name in the zip
    missing = []
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for spec in specs:
            for holder, key in _spec_images(spec):
                src = (holder.get(key) or "").strip()
                if not src or src in images:
                    continue
                if not os.path.isfile(src):
                    if src not in missing:
                        missing.append(src)
                    continue
                images[src] = "images/{}_{}".format(len(images) + 1,
                                                    os.path.basename(src))
                zf.write(src, images[src])
        zf.writestr(LEADERS_ENTRY, json.dumps({
            "magic": LEADERS_MAGIC, "version": PROJECT_VERSION,
            "leaders": specs, "images": images}, indent=2,
            ensure_ascii=False))
    return missing


def import_leaders(path):
    """Read an export_leaders zip. Returns (specs, version). An image that
    is still at its original path is used from there; the others are
    unpacked into '<export name> images' next to the zip. Raises
    ValueError if the file is not a leader export."""
    try:
        zf = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValueError("This is not a leader export ({}).".format(exc))
    with zf:
        try:
            data = json.loads(zf.read(LEADERS_ENTRY).decode("utf-8"))
        except (KeyError, ValueError):
            raise ValueError("This is not a leader export (no readable {})."
                             .format(LEADERS_ENTRY))
        if (not isinstance(data, dict)
                or data.get("magic") != LEADERS_MAGIC
                or not isinstance(data.get("leaders"), list)
                or not isinstance(data.get("images", {}), dict)):
            raise ValueError("This is not a leader export.")
        specs = data["leaders"]
        for spec in specs:
            if (not isinstance(spec, dict) or "name" not in spec
                    or not all(isinstance(entry, dict) for entry in
                               spec.get("moment_illustrations") or [])):
                raise ValueError("The export contains a malformed leader "
                                 "entry.")
        images = data.get("images", {})
        image_dir = os.path.splitext(path)[0] + " images"
        unpacked = {}                   # original path -> unpacked copy
        for spec in specs:
            for key in TUPLE_KEYS:      # JSON turned the tuples into lists
                if isinstance(spec.get(key), list):
                    spec[key] = tuple(spec[key])
            for holder, key in _spec_images(spec):
                src = holder.get(key)
                if (not isinstance(src, str) or not src.strip()
                        or os.path.isfile(src)):
                    continue
                if src not in unpacked:
                    name = images.get(src)
                    # only the file name: never write outside image_dir
                    base = os.path.basename(name) if isinstance(name, str) \
                        else ""
                    if not base or name not in zf.namelist():
                        continue        # not bundled: keep the bare path
                    os.makedirs(image_dir, exist_ok=True)
                    dst = os.path.join(image_dir, base)
                    with open(dst, "wb") as fh:
                        fh.write(zf.read(name))
                    unpacked[src] = dst
                holder[key] = unpacked[src]
    return specs, data.get("version", 1)


class IconCropDialog(tk.Toplevel):
    """Pick the icon's circle on the loading portrait: drag inside the
    circle to move it, drag its edge (or use the mouse wheel) to resize."""

    MAX_W, MAX_H = 760, 600
    EDGE = 9          # pixels around the circle's edge that start a resize

    def __init__(self, parent, src, crop, border_color, border_width):
        from PIL import Image, ImageEnhance
        super().__init__(parent)
        self.title("Choose icon area")
        self.resizable(False, False)
        self.transient(parent)
        self.result = None

        self.src = fitted_portrait(src)
        w, h = self.src.size
        self.scale = min(1.0, self.MAX_W / float(w), self.MAX_H / float(h))
        dw, dh = max(1, int(w * self.scale)), max(1, int(h * self.scale))
        # show transparent portraits on a checker-free dark background
        backdrop = Image.new("RGBA", (dw, dh), (40, 40, 40, 255))
        self.disp = Image.alpha_composite(
            backdrop, self.src.resize((dw, dh), Image.LANCZOS))
        self.dark = ImageEnhance.Brightness(self.disp).enhance(0.35)
        self.crop = list(crop or default_image_crop(self.src))
        self.border_color = tuple(border_color)
        self.drag = None
        self._pending = False

        body = ttk.Frame(self, padding=10)
        body.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(body, width=dw, height=dh,
                                highlightthickness=0, background="black")
        self.canvas.grid(row=0, column=0, rowspan=2, sticky="nw")
        self.img_item = self.canvas.create_image(0, 0, anchor="nw")
        self.ring_item = self.canvas.create_oval(0, 0, 1, 1, outline="white",
                                                 width=2, dash=(6, 4))
        self.handle_item = self.canvas.create_rectangle(
            0, 0, 1, 1, outline="black", fill="white")
        for seq, fn in (("<ButtonPress-1>", self.on_press),
                        ("<B1-Motion>", self.on_drag),
                        ("<ButtonRelease-1>", self.on_release),
                        ("<Motion>", self.on_hover),
                        ("<MouseWheel>", self.on_wheel)):
            self.canvas.bind(seq, fn)

        side = ttk.Frame(body, padding=(12, 0, 0, 0))
        side.grid(row=0, column=1, sticky="n")
        ttk.Label(side, text="Preview").pack(anchor="w")
        self.preview = tk.Canvas(side, width=200, height=140,
                                 highlightthickness=0, background="#2b2b2b")
        self.preview.pack(anchor="w", pady=(2, 10))
        self.preview_big = self.preview.create_image(8, 6, anchor="nw")
        self.preview_small = self.preview.create_image(144, 38, anchor="nw")

        ttk.Label(side, text="Border width").pack(anchor="w")
        self.width_var = tk.IntVar(value=int(border_width))
        tk.Scale(side, from_=0, to=40, orient="horizontal", length=200,
                 variable=self.width_var,
                 command=lambda *_: self.schedule()).pack(anchor="w")
        color_row = ttk.Frame(side)
        color_row.pack(anchor="w", pady=(8, 0))
        ttk.Label(color_row, text="Border color").pack(side="left")
        self.swatch = tk.Label(color_row, width=4, relief="sunken")
        self.swatch.pack(side="left", padx=6)
        ttk.Button(color_row, text="Pick...",
                   command=self.pick_color).pack(side="left")
        ttk.Label(side, wraplength=200, justify="left", text=(
            "Drag inside the circle to move it. Drag its edge or the "
            "handle, or use the mouse wheel, to resize.")).pack(
            anchor="w", pady=(14, 0))
        ttk.Button(side, text="Reset circle",
                   command=self.reset).pack(anchor="w", pady=(10, 0))

        btns = ttk.Frame(body)
        btns.grid(row=1, column=1, sticky="se")
        ttk.Button(btns, text="OK", command=self.on_ok).pack(side="left",
                                                             padx=4)
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(
            side="left", padx=4)

        self._refresh_swatch()
        self.redraw()
        self.grab_set()
        self.bind("<Return>", lambda e: self.on_ok())
        self.bind("<Escape>", lambda e: self.destroy())

    # -- geometry helpers ---------------------------------------------------

    def _disp_circle(self):
        cx, cy, r = self.crop
        return cx * self.scale, cy * self.scale, r * self.scale

    def _clamp(self):
        w, h = self.src.size
        cx, cy, r = self.crop
        r = min(max(r, 8.0 / self.scale, 4.0), max(w, h))
        self.crop = [min(max(cx, 0.0), w), min(max(cy, 0.0), h), r]

    # -- drawing ------------------------------------------------------------

    def schedule(self):
        """Coalesce redraws while dragging."""
        if not self._pending:
            self._pending = True
            self.after_idle(self.redraw)

    def redraw(self):
        from PIL import Image, ImageDraw, ImageTk
        self._pending = False
        cx, cy, r = self._disp_circle()
        mask = Image.new("L", self.disp.size, 0)
        ImageDraw.Draw(mask).ellipse((cx - r, cy - r, cx + r, cy + r),
                                     fill=255)
        self._photo = ImageTk.PhotoImage(
            Image.composite(self.disp, self.dark, mask))
        self.canvas.itemconfig(self.img_item, image=self._photo)
        self.canvas.coords(self.ring_item, cx - r, cy - r, cx + r, cy + r)
        self.canvas.coords(self.handle_item, cx + r - 5, cy - 5,
                           cx + r + 5, cy + 5)

        icon = make_circle_icon(self.src, self.crop, self.border_color,
                                self.width_var.get(), size=128)
        self._preview_big = ImageTk.PhotoImage(icon)
        self._preview_small = ImageTk.PhotoImage(
            icon.resize((48, 48), Image.LANCZOS))
        self.preview.itemconfig(self.preview_big, image=self._preview_big)
        self.preview.itemconfig(self.preview_small,
                                image=self._preview_small)

    # -- mouse --------------------------------------------------------------

    def _hit(self, x, y):
        cx, cy, r = self._disp_circle()
        d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
        if abs(d - r) <= self.EDGE:
            return "resize"
        return "move" if d < r else None

    def on_hover(self, event):
        hit = self._hit(event.x, event.y)
        self.canvas.configure(cursor={"resize": "sizing",
                                      "move": "fleur"}.get(hit, ""))

    def on_press(self, event):
        hit = self._hit(event.x, event.y)
        cx, cy, _ = self._disp_circle()
        if hit is None:                 # click outside: jump there
            self.crop[0], self.crop[1] = (event.x / self.scale,
                                          event.y / self.scale)
            hit, cx, cy = "move", event.x, event.y
        self.drag = (hit, event.x - cx, event.y - cy)
        self._clamp()
        self.schedule()

    def on_drag(self, event):
        if not self.drag:
            return
        mode, dx, dy = self.drag
        if mode == "move":
            self.crop[0] = (event.x - dx) / self.scale
            self.crop[1] = (event.y - dy) / self.scale
        else:
            cx, cy, _ = self._disp_circle()
            self.crop[2] = ((event.x - cx) ** 2 +
                            (event.y - cy) ** 2) ** 0.5 / self.scale
        self._clamp()
        self.schedule()

    def on_release(self, _event):
        self.drag = None

    def on_wheel(self, event):
        self.crop[2] *= 1.05 if event.delta > 0 else 1 / 1.05
        self._clamp()
        self.schedule()

    # -- controls -----------------------------------------------------------

    def _refresh_swatch(self):
        self.swatch.configure(background="#%02x%02x%02x" % self.border_color)

    def pick_color(self):
        rgb, _ = colorchooser.askcolor(
            parent=self, initialcolor="#%02x%02x%02x" % self.border_color)
        if rgb:
            self.border_color = tuple(int(c) for c in rgb)
            self._refresh_swatch()
            self.schedule()

    def reset(self):
        self.crop = list(default_image_crop(self.src))
        self.schedule()

    def on_ok(self):
        self.result = (tuple(self.crop), self.border_color,
                       int(self.width_var.get()))
        self.destroy()


class BusyDialog(tk.Toplevel):
    """Modal 'working...' window with a moving progress bar, a status line
    and the elapsed time, shown while run() does the work in a thread."""

    def __init__(self, parent, title):
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", lambda: None)   # cannot be closed
        self._status = "Starting..."
        self._start = time.monotonic()

        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)
        self.status_label = ttk.Label(body, text=self._status, width=60)
        self.status_label.pack(anchor="w")
        self.bar = ttk.Progressbar(body, mode="indeterminate", length=380)
        self.bar.pack(fill="x", pady=(10, 4))
        self.bar.start(12)
        self.elapsed_label = ttk.Label(body, text="", foreground="gray35")
        self.elapsed_label.pack(anchor="e")

        self.update_idletasks()         # center over the parent
        x = parent.winfo_rootx() + (parent.winfo_width() -
                                    self.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() -
                                    self.winfo_height()) // 3
        self.geometry("+{}+{}".format(max(x, 0), max(y, 0)))
        self.grab_set()

    def set_status(self, text):
        """Safe to call from the worker thread (only stores the text)."""
        self._status = text

    def run(self, work):
        """Run work() in a thread while the window stays responsive, then
        close. Returns work()'s result or re-raises its exception here.
        work() must not touch Tk."""
        result = {}

        def target():
            try:
                result["value"] = work()
            except BaseException as exc:    # re-raised on the main thread
                result["error"] = exc

        thread = threading.Thread(target=target, daemon=True)
        thread.start()

        def poll():
            if thread.is_alive():
                self.status_label.configure(text=self._status)
                self.elapsed_label.configure(text="{:.0f} s".format(
                    time.monotonic() - self._start))
                self.after(100, poll)
            else:
                self.bar.stop()
                self.grab_release()
                self.destroy()

        poll()
        self.wait_window()
        if "error" in result:
            raise result["error"]
        return result.get("value")


class Tooltip:
    """A small text box shown near the mouse after it rests on a widget.
    The owner calls show(text) on mouse motion ("" hides it) and hide()
    when the mouse leaves."""

    DELAY_MS = 400

    def __init__(self, widget):
        self.widget = widget
        self.text = ""
        self.tip = None
        self.pending = None

    def show(self, text):
        if text == self.text:
            return                      # already shown (or scheduled)
        self.hide()
        self.text = text
        if text:
            self.pending = self.widget.after(self.DELAY_MS, self._open)

    def _open(self):
        self.pending = None
        x, y = self.widget.winfo_pointerxy()
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry("+{}+{}".format(x + 16, y + 16))
        tk.Label(self.tip, text=self.text, justify="left",
                 background="#ffffe0", foreground="black", relief="solid",
                 borderwidth=1, padx=6, pady=3).pack()

    def hide(self):
        if self.pending:
            self.widget.after_cancel(self.pending)
            self.pending = None
        if self.tip is not None:
            self.tip.destroy()
            self.tip = None
        self.text = ""


class ScrollFrame(ttk.Frame):
    """A vertically scrollable frame; put widgets into .inner."""

    def __init__(self, parent, height=560):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, height=height, highlightthickness=0,
                                borderwidth=0)
        bar = ttk.Scrollbar(self, orient="vertical",
                            command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas, padding=(10, 6))
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all"),
            width=self.inner.winfo_reqwidth()))
        self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        # scroll with the mouse wheel while the pointer is over the frame
        self.bind("<Enter>", lambda e: self.bind_all(
            "<MouseWheel>", self._on_wheel))
        self.bind("<Leave>", lambda e: self.unbind_all("<MouseWheel>"))

    def _on_wheel(self, event):
        self.canvas.yview_scroll(int(-event.delta / 120), "units")


class LeaderEditor(tk.Toplevel):

    def __init__(self, app, spec, title="Leader"):
        super().__init__(app)
        self.app = app
        self.result = None
        self.title(title)
        self.resizable(False, False)
        self.transient(app)

        outer = ttk.Frame(self, padding=10)
        outer.pack(fill="both", expand=True)
        notebook = ttk.Notebook(outer)
        notebook.pack(fill="both", expand=True)

        general = ttk.Frame(notebook, padding=10)
        diplo = ScrollFrame(notebook)
        pedia = ScrollFrame(notebook)
        notebook.add(general, text="General")
        ability = ttk.Frame(notebook, padding=10)
        notebook.add(ability, text="Ability")
        agenda = ttk.Frame(notebook, padding=10)
        notebook.add(agenda, text="Agenda")
        cities = ttk.Frame(notebook, padding=10)
        notebook.add(cities, text="City names")
        notebook.add(diplo, text="Diplomacy text")
        notebook.add(pedia, text="Civilopedia")
        moments = ttk.Frame(notebook, padding=10)
        notebook.add(moments, text="Historic moments")

        self._build_general(general, spec)
        self.on_name_changed()          # show the type right away
        texts = spec_texts(spec)
        self.text_widgets = {}          # tag template -> tk.Text
        self._build_diplo(diplo.inner, texts)
        self._build_pedia(pedia.inner, texts)
        self._build_moments(moments, spec)
        self._build_abilities(ability, spec)
        self._build_agenda(agenda, spec)
        self._build_cities(cities, spec)

        # -- buttons
        btns = ttk.Frame(outer)
        btns.pack(side="bottom", anchor="e", pady=(10, 0))
        ttk.Button(btns, text="OK", command=self.on_ok).pack(
            side="left", padx=4)
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(
            side="left", padx=4)

        self.grab_set()
        self.bind("<Return>", self.on_return)
        self.bind("<Escape>", lambda e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    # -- tabs ---------------------------------------------------------------

    def _build_general(self, body, spec):
        pad = {"padx": 6, "pady": 3}

        # -- identity
        row = 0
        ttk.Label(body, text="Name").grid(row=row, column=0, sticky="w",
                                          **pad)
        self.name_var = tk.StringVar(value=spec.get("name", ""))
        self.name_var.trace_add("write", self.on_name_changed)
        ttk.Entry(body, textvariable=self.name_var, width=28).grid(
            row=row, column=1, sticky="w", **pad)
        self.slug_label = ttk.Label(body, text="type: (auto)")
        self.slug_label.grid(row=row, column=2, sticky="w", **pad)

        row += 1
        ttk.Label(body, text="Sex").grid(row=row, column=0, sticky="w", **pad)
        self.sex_var = tk.StringVar(value=spec.get("sex", "Female"))
        ttk.Combobox(body, textvariable=self.sex_var, width=12,
                     values=["Female", "Male"], state="readonly").grid(
            row=row, column=1, sticky="w", **pad)

        # -- civ / original leader
        row += 1
        ttk.Label(body, text="Civilization").grid(row=row, column=0,
                                                  sticky="w", **pad)
        self.civ_var = tk.StringVar(value=spec.get("civ", ""))
        self.civ_combo = ttk.Combobox(body, textvariable=self.civ_var,
                                      width=40,
                                      values=self.app.all_civs())
        self.civ_combo.grid(row=row, column=1, columnspan=2, sticky="w",
                            **pad)
        self.civ_combo.bind("<<ComboboxSelected>>", self.on_civ_changed)

        row += 1
        ttk.Label(body, text="Inherit from").grid(row=row, column=0,
                                                  sticky="w", **pad)
        self.orig_var = tk.StringVar(value=spec.get("orig", ""))
        self.orig_combo = ttk.Combobox(body, textvariable=self.orig_var,
                                       width=40,
                                       values=self.app.leaders_for_civ(
                                           self.civ_var.get()))
        self.orig_combo.grid(row=row, column=1, columnspan=2, sticky="w",
                             **pad)

        # -- flavour
        row += 1
        self.bio = tk.Text(body, height=4, width=56, wrap="word")
        self.bio.insert("1.0", spec.get("bio", ""))
        self.quote_var = tk.StringVar(value=spec.get("quote", ""))
        ttk.Label(body, text="Loading bio").grid(row=row, column=0,
                                                 sticky="ne", **pad)
        self.bio.grid(row=row, column=1, columnspan=2, sticky="w", **pad)
        row += 1
        ttk.Label(body, text="Loading quote").grid(row=row, column=0,
                                                   sticky="w", **pad)
        ttk.Entry(body, textvariable=self.quote_var, width=48).grid(
            row=row, column=1, columnspan=2, sticky="w", **pad)
        row += 1

        # -- colors
        self.primary = tuple(spec.get("primary") or (30, 90, 170))
        self.secondary = tuple(spec.get("secondary") or (230, 230, 230))
        ttk.Label(body, text="Primary color").grid(row=row, column=0,
                                                   sticky="w", **pad)
        self.primary_lbl = ttk.Label(body, text="")
        self.primary_lbl.grid(row=row, column=1, sticky="w", **pad)
        ttk.Button(body, text="Pick...",
                   command=lambda: self.pick_color("primary")).grid(
            row=row, column=2, sticky="w", **pad)
        row += 1
        ttk.Label(body, text="Secondary color").grid(row=row, column=0,
                                                     sticky="w", **pad)
        self.secondary_lbl = ttk.Label(body, text="")
        self.secondary_lbl.grid(row=row, column=1, sticky="w", **pad)
        ttk.Button(body, text="Pick...",
                   command=lambda: self.pick_color("secondary")).grid(
            row=row, column=2, sticky="w", **pad)
        self._refresh_swatches()
        row += 1

        # -- images (empty = inherit from the original leader)
        self.icon_path = tk.StringVar(value=spec.get("icon_path", ""))
        self.load_fg_path = tk.StringVar(value=spec.get("load_fg_path", ""))
        self.load_bg_path = tk.StringVar(value=spec.get("load_bg_path", ""))
        self.diplo_bg_path = tk.StringVar(
            value=spec.get("diplo_bg_path", ""))
        for label, var in (
                ("Portrait", self.load_fg_path),
                ("Loading background", self.load_bg_path),
                ("Diplomacy background", self.diplo_bg_path)):
            ttk.Label(body, text=label).grid(row=row, column=0, sticky="w",
                                             **pad)
            entry = ttk.Entry(body, textvariable=var, width=40)
            entry.grid(row=row, column=1, sticky="w", **pad)
            browse = ttk.Button(
                body, text="Browse...",
                command=lambda v=var, t=label: self.browse_image(v, t))
            browse.grid(row=row, column=2, sticky="w", **pad)
            row += 1
        # optional fade mask for the diplomacy background (last row above)
        self.diplo_bg_mask = tk.BooleanVar(
            value=bool(spec.get("diplo_bg_mask")))
        mask_check = ttk.Checkbutton(body, text="Apply fade mask",
                                     variable=self.diplo_bg_mask)
        mask_check.grid(row=row - 1, column=3, sticky="w", **pad)
        if not asset_path(DIPLO_BG_MASK):
            mask_check.state(["disabled"])
            mask_check.configure(text="Apply fade mask (assets/{} not found)"
                                 .format(DIPLO_BG_MASK))

        # -- leader icon: cut from the loading portrait, or an image file
        self.icon_mode = tk.StringVar(value=spec_icon_mode(spec))
        self.icon_crop = spec.get("icon_crop")
        self.icon_border_color = tuple(spec.get("icon_border_color") or
                                       DEFAULT_ICON_BORDER_COLOR)
        self.icon_border_width = int(spec.get("icon_border_width",
                                              DEFAULT_ICON_BORDER_WIDTH))
        ttk.Label(body, text="Leader icon").grid(row=row, column=0,
                                                 sticky="nw", **pad)
        icon_box = ttk.Frame(body)
        icon_box.grid(row=row, column=1, columnspan=2, sticky="w", **pad)
        modes = ttk.Frame(icon_box)
        modes.grid(row=0, column=0, columnspan=3, sticky="w")
        for text, value in (("Cut from loading portrait", "portrait"),
                            ("Image file", "file")):
            ttk.Radiobutton(modes, text=text, value=value,
                            variable=self.icon_mode,
                            command=self._update_icon_widgets).pack(
                side="left", padx=(0, 12))
        self.icon_thumb = ttk.Label(icon_box)
        self.icon_thumb.grid(row=1, column=0, rowspan=2, sticky="w",
                             pady=(4, 0))
        self.icon_area_btn = ttk.Button(icon_box, text="Choose icon area...",
                                        command=self.choose_icon_area)
        self.icon_area_btn.grid(row=1, column=1, sticky="w", padx=8,
                                pady=(4, 0))
        file_row = ttk.Frame(icon_box)
        file_row.grid(row=2, column=1, columnspan=2, sticky="w", padx=8,
                      pady=(4, 0))
        self.icon_entry = ttk.Entry(file_row, textvariable=self.icon_path,
                                    width=34)
        self.icon_entry.pack(side="left")
        self.icon_browse = ttk.Button(
            file_row, text="Browse...",
            command=lambda: self.browse_image(self.icon_path,
                                              "Leader icon image"))
        self.icon_browse.pack(side="left", padx=(6, 0))
        self._last_fg = self.load_fg_path.get()
        for var in (self.load_fg_path, self.icon_path):
            var.trace_add("write", lambda *_: self._on_icon_source_changed())
        self._update_icon_widgets()

        # -- previews of the chosen images
        row += 1
        previews = ttk.LabelFrame(body, text="Preview", padding=(8, 4))
        previews.grid(row=row, column=0, columnspan=4, sticky="we",
                      padx=6, pady=(10, 3))
        self.preview_labels = {}
        for col, (key, caption) in enumerate((
                ("portrait", "Portrait"),
                ("load_bg", "Loading background"),
                ("diplo_bg", "Diplomacy background"))):
            ttk.Label(previews, text=caption).grid(row=0, column=col,
                                                   sticky="w", padx=6)
            frame = tk.Frame(previews, width=PREVIEW_BOX[0],
                             height=PREVIEW_BOX[1],
                             background="#%02x%02x%02x" %
                             PREVIEW_BACKDROP[:3])
            frame.grid(row=1, column=col, padx=6, pady=(2, 4))
            frame.grid_propagate(False)
            frame.pack_propagate(False)
            label = tk.Label(frame, background=frame["background"],
                             foreground="#bbbbbb", justify="center",
                             wraplength=PREVIEW_BOX[0] - 16)
            label.pack(fill="both", expand=True)
            self.preview_labels[key] = label
        self._preview_photos = {}
        mask_check.configure(command=self._refresh_previews)
        for var in (self.load_fg_path, self.load_bg_path,
                    self.diplo_bg_path, self.orig_var):
            var.trace_add("write", lambda *_: self._schedule_previews())
        self._refresh_previews()

    def _schedule_previews(self):
        """Refresh the previews once typing in a path field pauses."""
        if getattr(self, "_preview_job", None):
            self.after_cancel(self._preview_job)
        self._preview_job = self.after(250, self._refresh_previews)

    def _refresh_previews(self):
        self._preview_job = None
        inherited = "(inherited from {})".format(
            type_display_name(self.orig_var.get().strip()) or
            "the original leader")
        mask = asset_path(DIPLO_BG_MASK) if self.diplo_bg_mask.get() \
            else None
        sources = {
            "portrait": (self.load_fg_path.get().strip(), None, True),
            "load_bg": (self.load_bg_path.get().strip(), None, False),
            "diplo_bg": (self.diplo_bg_path.get().strip(), mask, False),
        }
        for key, (path, mask_path, portrait) in sources.items():
            photo, text = None, inherited
            try:
                from PIL import ImageTk
                if path and not os.path.isfile(path):
                    text = "(file not found)"
                img = preview_image(path, PREVIEW_BOX, mask_path, portrait)
                if img is not None:
                    photo = ImageTk.PhotoImage(img)
            except ImportError:
                text = "(install Pillow for a preview)"
            except Exception as exc:    # unreadable image
                text = "(cannot preview: {})".format(exc)
            self._preview_photos[key] = photo
            self.preview_labels[key].configure(image=photo or "",
                                               text="" if photo else text)

    def _text_field(self, parent, key, label, height, texts, row):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="nw",
                                           padx=(12, 6), pady=3)
        widget = tk.Text(parent, height=height, width=78, wrap="word",
                         undo=True)
        widget.insert("1.0", texts.get(key, ""))
        widget.grid(row=row, column=1, sticky="w", pady=3)
        self.text_widgets[key] = widget

    def _tab_header(self, parent, hint):
        ttk.Label(parent, text=hint, wraplength=820, justify="left").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
        btns = ttk.Frame(parent)
        btns.grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 6))
        ttk.Button(btns, text="Copy original leader's text into empty "
                              "fields", command=self.copy_original_text
                   ).pack(side="left")
        ttk.Button(btns, text="Copy all text as JSON",
                   command=self.export_texts_json).pack(side="left",
                                                        padx=(12, 0))
        ttk.Button(btns, text="Paste text from JSON",
                   command=self.import_texts_json).pack(side="left",
                                                        padx=(6, 0))
        return 2

    def _build_diplo(self, parent, texts):
        row = self._tab_header(
            parent, "Lines left empty reuse the original leader's line "
                    "(for HAPPY/UNHAPPY lines: the same mood, otherwise its "
                    "any-mood line). Use [NEWLINE] or line breaks for new "
                    "lines, and {LOC_...} to reference another text.")
        for section, lines in DIPLO_TEXT:
            ttk.Label(parent, text=section, font=("TkDefaultFont", 10,
                                                  "bold")).grid(
                row=row, column=0, columnspan=2, sticky="w", pady=(10, 2))
            row += 1
            for key, label in lines:
                self._text_field(parent, key, label, 2, texts, row)
                row += 1

    def _build_pedia(self, parent, texts):
        row = self._tab_header(
            parent, "Civilopedia leader page. The summary and detailed "
                    "approach reuse the original leader's text when empty "
                    "(the ability is the same); title, subtitle, quote and "
                    "history are only written when filled in.")
        for key, label, height, _ in PEDIA_TEXT:
            self._text_field(parent, key, label, height, texts, row)
            row += 1

    # -- events -------------------------------------------------------------

    def on_return(self, event):
        # Return inserts a newline in text boxes; elsewhere it means OK
        if not isinstance(event.widget, tk.Text):
            self.on_ok()

    def on_name_changed(self, *_):
        slug = slug_for_name(self.name_var.get(), self.app.type_prefix())
        self.slug_label.config(
            text="type: " + slug if slug else "type: (type a name)")

    def on_civ_changed(self, *_):
        self.orig_combo["values"] = self.app.leaders_for_civ(
            self.civ_var.get())
        self._refresh_moment_items()

    # -- historic moments ---------------------------------------------------

    def _build_moments(self, parent, spec):
        ttk.Label(parent, wraplength=860, justify="left", text=(
            "Custom pictures for the historic moment shown when this "
            "leader's civilization first trains or builds a unique unit, "
            "building, district or improvement (Rise and Fall / Gathering "
            "Storm).\n\n"
            "Mods cannot add new moments - when a moment fires is decided "
            "by the game itself - so this replaces the picture of that "
            "existing moment. The picture belongs to the item, not the "
            "leader: it is shown for every leader of the civilization "
            "that has the item. Tech and civic moments have no per-item "
            "pictures. Images are cropped to 456 x 332 like the game's own."
        )).grid(row=0, column=0, sticky="w", pady=(0, 10))
        self.moment_list = ttk.Frame(parent)
        self.moment_list.grid(row=1, column=0, sticky="w")
        self.moment_rows = []
        for entry in spec.get("moment_illustrations") or []:
            self._add_moment_row(entry)
        ttk.Button(parent, text="Add illustration",
                   command=self._add_moment_row).grid(row=2, column=0,
                                                      sticky="w", pady=8)
        self.orig_combo.bind("<<ComboboxSelected>>",
                             lambda e: self.on_orig_selected())

    def on_orig_selected(self):
        """Picking the leader to inherit from also takes its colors."""
        self._refresh_moment_items()
        colors = self.app.data.colors(self.orig_var.get().strip())
        if colors:
            self.primary, self.secondary = colors
            self._refresh_swatches()

    # -- agenda -------------------------------------------------------------

    AGENDA_INHERIT = "(inherit from original leader)"

    def _agenda_label(self, agenda):
        """Combobox text for an agenda type: 'Iron Crown (AGENDA_IRON_CROWN)
        - Frederick Barbarossa' (or '- random' if no leader has it)."""
        info = self.app.data.agendas.get(agenda)
        if not info:
            return agenda
        data = self.app.data
        names = []
        for leader in info["leaders"]:
            name = data.meta(leader).get("name") or ""   # text or its tag
            if name.startswith("LOC_"):
                name = data.loc_text(name) or type_display_name(leader)
            names.append(name or type_display_name(leader))
        leaders = ", ".join(names) or "random"
        return "{} ({}) - {}".format(info["name"], agenda, leaders)

    def _agenda_type(self):
        """Agenda type picked (or typed) in the combobox, "" = inherit."""
        text = self.agenda_var.get().strip()
        if not text or text == self.AGENDA_INHERIT:
            return ""
        m = re.search(r"\((AGENDA_[A-Z0-9_]+)\)", text)
        return m.group(1) if m else text.upper()

    def _source_agenda(self):
        """The agenda the leader gets (or copies): picked or inherited."""
        return (self._agenda_type() or
                self.app.data.historical_agenda(self.orig_var.get().strip()))

    def _build_agenda(self, parent, spec):
        pad = {"padx": 6, "pady": 3}
        ttk.Label(parent, wraplength=760, justify="left", text=(
            "The AI agenda this leader plays by: the original leader's, or "
            "any agenda the game already defines. A new name and/or "
            "description gives this leader its own copy of the agenda - "
            "same behaviour, different text; empty fields keep the "
            "agenda's own text. The reasons the AI gives for liking or "
            "disliking you are on the Diplomacy text tab (Kudos & "
            "warnings).")).grid(row=0, column=0, columnspan=2, sticky="w",
                                pady=(0, 10))
        ttk.Label(parent, text="Agenda").grid(row=1, column=0, sticky="w",
                                              **pad)
        agenda = (spec.get("agenda") or "").strip()
        self.agenda_var = tk.StringVar(
            value=self._agenda_label(agenda) if agenda
            else self.AGENDA_INHERIT)
        combo = ttk.Combobox(
            parent, textvariable=self.agenda_var, width=70,
            values=[self.AGENDA_INHERIT] + [
                self._agenda_label(a) for a in sorted(
                    self.app.data.agendas,
                    key=lambda a: self.app.data.agendas[a]["name"])])
        combo.grid(row=1, column=1, sticky="w", **pad)
        self.agenda_info = ttk.Label(parent, wraplength=560, justify="left",
                                     foreground="gray25")
        self.agenda_info.grid(row=2, column=1, sticky="w", **pad)

        ttk.Label(parent, text="New name").grid(row=3, column=0, sticky="w",
                                                **pad)
        self.agenda_name_var = tk.StringVar(value=spec.get("agenda_name", ""))
        ttk.Entry(parent, textvariable=self.agenda_name_var, width=40).grid(
            row=3, column=1, sticky="w", **pad)
        ttk.Label(parent, text="New description").grid(row=4, column=0,
                                                       sticky="nw", **pad)
        self.agenda_desc = tk.Text(parent, height=4, width=70, wrap="word",
                                   undo=True)
        self.agenda_desc.insert("1.0", spec.get("agenda_desc", ""))
        self.agenda_desc.grid(row=4, column=1, sticky="w", **pad)
        ttk.Button(parent, text="Copy agenda's text into empty fields",
                   command=self.copy_agenda_text).grid(
            row=5, column=1, sticky="w", **pad)

        self.agenda_var.trace_add("write",
                                  lambda *_: self._refresh_agenda_info())
        self.orig_var.trace_add("write",
                                lambda *_: self._refresh_agenda_info())
        self._refresh_agenda_info()

    def _build_abilities(self, parent, spec):
        ttk.Label(parent, wraplength=760, justify="left", text=(
            "The leader ability is inherited from the original leader. A "
            "new name and/or description gives this leader its own copy of "
            "it - same effects, different text; empty fields keep the "
            "ability's own text.")).grid(row=0, column=0, sticky="w",
                                         pady=(0, 10))
        self.ability_frame = ttk.Frame(parent)
        self.ability_frame.grid(row=1, column=0, sticky="nw")
        # typed text per trait, kept while the original leader changes
        self.ability_texts = {trait: dict(text) for trait, text in
                              (spec.get("abilities") or {}).items()}
        self.ability_widgets = {}       # trait -> (name var, tk.Text)
        self.orig_var.trace_add("write", lambda *_: self._refresh_abilities())
        self._refresh_abilities()

    def _shown_abilities(self):
        """[(trait, info or None)] for the tab: the original leader's
        abilities from the game cache, or (without it) the traits this
        leader already renames."""
        orig = self.orig_var.get().strip()
        data = self.app.data
        if data.conn:
            return [(a["type"], a) for a in data.abilities(orig)]
        return [(trait, None) for trait in sorted(self.ability_texts)]

    def _store_ability_texts(self):
        for trait, (name_var, desc) in self.ability_widgets.items():
            self.ability_texts[trait] = {
                "name": name_var.get().strip(),
                "desc": desc.get("1.0", "end").strip()}

    def _refresh_abilities(self):
        self._store_ability_texts()
        frame = self.ability_frame
        for widget in frame.winfo_children():
            widget.destroy()
        self.ability_widgets = {}
        pad = {"padx": 6, "pady": 3}
        shown = self._shown_abilities()
        if not shown:
            orig = self.orig_var.get().strip()
            if not self.app.data.conn:
                text = ("(load the game cache to list the original leader's "
                        "abilities)")
            elif not orig:
                text = "(pick the leader to inherit from on the General tab)"
            else:
                text = ("{} has no ability that can be renamed (it only "
                        "unlocks a unique item, or is not in the loaded game "
                        "data).".format(type_display_name(orig)))
            ttk.Label(frame, text=text, foreground="gray25").grid(
                row=0, column=0, sticky="w", **pad)
            return
        row = 0
        for trait, info in shown:
            ttk.Label(frame, text="{} ({})".format(info["name"], trait)
                      if info else trait,
                      font=("TkDefaultFont", 10, "bold")).grid(
                row=row, column=0, columnspan=2, sticky="w",
                pady=(10 if row else 0, 2))
            row += 1
            if info and info["desc"]:
                ttk.Label(frame, text=info["desc"].replace("[NEWLINE]", "\n"),
                          wraplength=560, justify="left",
                          foreground="gray25").grid(row=row, column=1,
                                                    sticky="w", **pad)
                row += 1
            text = self.ability_texts.get(trait) or {}
            ttk.Label(frame, text="New name").grid(row=row, column=0,
                                                   sticky="w", **pad)
            name_var = tk.StringVar(value=text.get("name", ""))
            ttk.Entry(frame, textvariable=name_var, width=40).grid(
                row=row, column=1, sticky="w", **pad)
            row += 1
            ttk.Label(frame, text="New description").grid(
                row=row, column=0, sticky="nw", **pad)
            desc = tk.Text(frame, height=4, width=70, wrap="word", undo=True)
            desc.insert("1.0", text.get("desc", ""))
            desc.grid(row=row, column=1, sticky="w", **pad)
            row += 1
            self.ability_widgets[trait] = (name_var, desc)
        if any(info for _, info in shown):
            ttk.Button(frame, text="Copy the ability's text into empty "
                       "fields", command=self.copy_ability_text).grid(
                row=row, column=1, sticky="w", **pad)

    def copy_ability_text(self):
        """Fill the empty names / descriptions with the abilities' English
        text, so it can be edited instead of retyped."""
        for trait, info in self._shown_abilities():
            name_var, desc = self.ability_widgets[trait]
            if not info:
                continue
            if not name_var.get().strip():
                name_var.set(info["name"])
            if not desc.get("1.0", "end").strip():
                desc.insert("1.0", info["desc"].replace("[NEWLINE]", "\n"))

    def abilities(self):
        """{trait: {"name", "desc"}} of the shown abilities with new text."""
        self._store_ability_texts()
        shown = {trait for trait, _ in self._shown_abilities()}
        return {trait: text for trait, text in self.ability_texts.items()
                if trait in shown and (text.get("name") or text.get("desc"))}

    def _build_cities(self, parent, spec):
        ttk.Label(parent, wraplength=760, justify="left", text=(
            "This leader's own city names, one per line. The first one is "
            "the capital; new cities take the next name on the list, and "
            "once it runs out the civilization's own names are used. Leave "
            "the list empty to use the civilization's names and the "
            "original leader's capital.")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))
        box = ttk.Frame(parent)
        box.grid(row=1, column=0, sticky="nw")
        self.city_text = tk.Text(box, height=22, width=40, wrap="none",
                                 undo=True)
        bar = ttk.Scrollbar(box, orient="vertical",
                            command=self.city_text.yview)
        self.city_text.configure(yscrollcommand=bar.set)
        self.city_text.pack(side="left", fill="y")
        bar.pack(side="left", fill="y")
        self.city_text.insert("1.0", "\n".join(spec.get("city_names") or []))
        self.city_text.bind("<<Modified>>", self._on_cities_modified)

        side = ttk.Frame(parent)
        side.grid(row=1, column=1, sticky="nw", padx=(16, 0))
        self.city_count = ttk.Label(side, justify="left")
        self.city_count.pack(anchor="w")
        ttk.Button(side, text="Copy the civilization's city names",
                   command=self.copy_civ_city_names).pack(anchor="w",
                                                          pady=(10, 0))
        ttk.Button(side, text="Clear", command=lambda: self.city_text.delete(
            "1.0", "end")).pack(anchor="w", pady=(6, 0))
        self._refresh_city_count()

    def city_names(self):
        return [line.strip() for line in
                self.city_text.get("1.0", "end").splitlines()
                if line.strip()]

    def _on_cities_modified(self, _event=None):
        self.city_text.edit_modified(False)     # re-arm <<Modified>>
        self._refresh_city_count()

    def _refresh_city_count(self):
        names = self.city_names()
        self.city_count.configure(
            text="{} names\nCapital: {}".format(len(names), names[0])
            if names else "No names: using the civilization's")

    def copy_civ_city_names(self):
        civ = self.civ_var.get().strip()
        names = self.app.data.city_names(civ)
        if not names:
            messagebox.showinfo(
                "No city names", "No city names found for {}. Load the "
                "game cache first (main window).".format(civ or "(no civ)"),
                parent=self)
            return
        if self.city_names() and not messagebox.askyesno(
                "Replace city names", "Replace the list with the {} names "
                "of {}?".format(len(names), civ), parent=self):
            return
        self.city_text.delete("1.0", "end")
        self.city_text.insert("1.0", "\n".join(names))

    def _refresh_agenda_info(self):
        agenda = self._source_agenda()
        info = self.app.data.agendas.get(agenda or "")
        if info:
            text = "{}: {}".format(info["name"], info["desc"])
            if not self._agenda_type():
                text = "Inherited - " + text
        elif agenda:
            text = "{} (not in the loaded game data)".format(agenda)
        elif self.app.data.conn:
            text = "(pick the leader to inherit from on the General tab)"
        else:
            text = ("(load the game cache to list the agendas - or type an "
                    "AGENDA_ type)")
        self.agenda_info.configure(text=text)

    def copy_agenda_text(self):
        """Fill the empty name / description with the agenda's English
        text, so it can be edited instead of retyped."""
        info = self.app.data.agendas.get(self._source_agenda() or "")
        if not info:
            messagebox.showinfo("No agenda text",
                                "Load the game cache and pick an agenda (or "
                                "the leader to inherit from) first.",
                                parent=self)
            return
        if not self.agenda_name_var.get().strip():
            self.agenda_name_var.set(info["name"])
        if not self.agenda_desc.get("1.0", "end").strip():
            self.agenda_desc.insert("1.0",
                                    info["desc"].replace("[NEWLINE]", "\n"))

    def _unique_items(self):
        return self.app.data.uniques_for(self.civ_var.get().strip(),
                                         self.orig_var.get().strip())

    def _refresh_moment_items(self):
        items = self._unique_items()
        for row in getattr(self, "moment_rows", []):
            row["combo"]["values"] = items

    def _add_moment_row(self, entry=None):
        entry = entry or {}
        frame = ttk.Frame(self.moment_list)
        frame.pack(anchor="w", pady=3)
        row = {"frame": frame,
               "item": tk.StringVar(value=entry.get("item", "")),
               "path": tk.StringVar(value=entry.get("path", "")),
               "mask": tk.BooleanVar(value=bool(entry.get("mask"))),
               "half": tk.BooleanVar(value=bool(entry.get("half"))),
               "sepia": tk.BooleanVar(value=bool(entry.get("sepia")))}
        row["thumb"] = ttk.Label(frame, width=12)
        row["thumb"].pack(side="left", padx=(0, 8))
        ttk.Label(frame, text="Item").pack(side="left")
        row["combo"] = ttk.Combobox(frame, textvariable=row["item"],
                                    width=32, values=self._unique_items())
        row["combo"].pack(side="left", padx=(4, 12))
        ttk.Label(frame, text="Image").pack(side="left")
        ttk.Entry(frame, textvariable=row["path"], width=34).pack(
            side="left", padx=4)
        ttk.Button(frame, text="Browse...", command=lambda: self.browse_image(
            row["path"], "Historic moment image")).pack(side="left")
        mask_check = ttk.Checkbutton(frame, text="Fade mask",
                                     variable=row["mask"])
        mask_check.pack(side="left", padx=(10, 0))
        if not asset_path(MOMENT_MASK):
            mask_check.state(["disabled"])
            mask_check.configure(text="Fade mask (assets/{} not found)"
                                 .format(MOMENT_MASK))
        ttk.Checkbutton(frame, text="50% transparent",
                        variable=row["half"]).pack(side="left", padx=(6, 0))
        ttk.Checkbutton(frame, text="Sepia",
                        variable=row["sepia"]).pack(side="left", padx=(6, 0))
        ttk.Button(frame, text="Remove",
                   command=lambda: self._remove_moment_row(row)).pack(
            side="left", padx=(10, 0))
        for var in ("path", "mask", "half", "sepia"):
            row[var].trace_add("write",
                               lambda *_: self._refresh_moment_thumb(row))
        self.moment_rows.append(row)
        self._refresh_moment_thumb(row)

    def _remove_moment_row(self, row):
        row["frame"].destroy()
        self.moment_rows.remove(row)

    def _refresh_moment_thumb(self, row):
        """Preview cropped (and masked / faded) like the generated
        illustration (456 x 332), on a dark backdrop so transparency
        shows."""
        row["photo"] = None
        path = row["path"].get().strip()
        try:
            from PIL import Image, ImageTk
            if path and os.path.isfile(path):
                img = apply_image_mask(
                    path, asset_path(MOMENT_MASK) if row["mask"].get()
                    else None, size=(91, 66),
                    opacity=MOMENT_HALF_OPACITY if row["half"].get()
                    else 1.0, sepia=row["sepia"].get())
                backdrop = Image.new("RGBA", img.size, (43, 43, 43, 255))
                row["photo"] = ImageTk.PhotoImage(
                    Image.alpha_composite(backdrop, img))
        except Exception:               # no Pillow / unreadable image
            pass
        row["thumb"].configure(image=row["photo"] or "",
                               text="" if row["photo"] else "(no image)")

    def moment_illustrations(self):
        out = []
        for row in self.moment_rows:
            item = row["item"].get().strip().upper()
            path = row["path"].get().strip()
            if item or path:
                out.append({"item": item, "path": path,
                            "mask": bool(row["mask"].get()),
                            "half": bool(row["half"].get()),
                            "sepia": bool(row["sepia"].get())})
        return out

    def copy_original_text(self):
        """Fill empty text boxes with the original leader's English text
        (from the game cache), so it can be edited instead of retyped."""
        orig = self.orig_var.get().strip()
        if not orig:
            messagebox.showinfo("No original leader",
                                "Pick the leader to inherit from first "
                                "(General tab).", parent=self)
            return
        if not self.app.data.loc_conn:
            messagebox.showinfo("Game text not loaded",
                                "Load the game cache first (\"Load from game "
                                "cache...\" in the main window).",
                                parent=self)
            return
        filled = 0
        for key, widget in self.text_widgets.items():
            if widget.get("1.0", "end").strip():
                continue
            if key == PEDIA_HISTORY:
                paras = []
                while True:
                    text = self.app.data.loc_text("{}_PARA_{}".format(
                        key.format(L=orig), len(paras) + 1))
                    if not text:
                        break
                    paras.append(text)
                text = "\n\n".join(paras)
            else:
                text = next(filter(None, (
                    self.app.data.loc_text(c.format(L=orig))
                    for c in inherit_candidates(key))), None)
            if text:
                widget.insert("1.0", text.replace("[NEWLINE]", "\n"))
                filled += 1
        messagebox.showinfo("Text copied",
                            "Filled {} empty field(s) with the text of {}."
                            .format(filled, orig), parent=self)

    def current_texts(self):
        texts = {}
        for key, widget in self.text_widgets.items():
            text = widget.get("1.0", "end").strip()
            if text:
                texts[key] = text
        return texts

    def export_texts_json(self):
        """Put every diplomacy / Civilopedia line on the clipboard as
        JSON (both tabs, empty lines included)."""
        self.clipboard_clear()
        self.clipboard_append(texts_to_json(self.current_texts()))
        self.update()        # keep the clipboard content after closing
        messagebox.showinfo(
            "Copied", "All {} text fields were copied to the clipboard as "
            "JSON. Keys use {{L}} for the leader type.".format(
                len(self.text_widgets)), parent=self)

    def import_texts_json(self):
        """Fill text fields from JSON on the clipboard; only the lines it
        contains are changed."""
        try:
            data = self.clipboard_get()
        except tk.TclError:
            messagebox.showwarning("Nothing to paste",
                                   "The clipboard does not contain text.",
                                   parent=self)
            return
        try:
            texts, unknown = texts_from_json(data)
        except ValueError as exc:
            messagebox.showwarning("Could not paste", str(exc), parent=self)
            return
        for key, text in texts.items():
            widget = self.text_widgets[key]
            widget.delete("1.0", "end")
            widget.insert("1.0", text.replace("[NEWLINE]", "\n"))
        message = "Updated {} text field(s).".format(len(texts))
        if unknown:
            message += ("\n\n{} unrecognized key(s) were ignored:\n{}".format(
                len(unknown), "\n".join(unknown[:10])) +
                ("\n..." if len(unknown) > 10 else ""))
        messagebox.showinfo("Pasted", message, parent=self)

    # -- leader icon ----------------------------------------------------------

    def _on_icon_source_changed(self):
        # a different portrait invalidates the circle chosen on the old one
        if self.load_fg_path.get() != self._last_fg:
            self._last_fg = self.load_fg_path.get()
            self.icon_crop = None
        self._update_icon_widgets()

    def _update_icon_widgets(self):
        portrait = self.icon_mode.get() == "portrait"
        self.icon_area_btn.state(["!disabled"] if portrait else ["disabled"])
        for w in (self.icon_entry, self.icon_browse):
            w.state(["disabled"] if portrait else ["!disabled"])
        self._refresh_icon_thumb()

    def _refresh_icon_thumb(self):
        """Small preview of the icon the generator will produce."""
        self._thumb = None
        text = ""
        try:
            from PIL import Image, ImageTk
            if self.icon_mode.get() == "portrait":
                src = self.load_fg_path.get().strip()
                if src and os.path.isfile(src):
                    icon = make_circle_icon(fitted_portrait(src),
                                            self.icon_crop,
                                            self.icon_border_color,
                                            self.icon_border_width, size=64)
                else:
                    text = "(pick a loading portrait - until then the " \
                           "original leader's icon is used)"
                    icon = None
            else:
                src = self.icon_path.get().strip()
                icon = None
                if src and os.path.isfile(src):
                    icon = Image.open(src).convert("RGBA")
                    icon.thumbnail((64, 64), Image.LANCZOS)
            if icon is not None:
                self._thumb = ImageTk.PhotoImage(icon)
        except ImportError:
            text = "(install Pillow for a preview)"
        except Exception as exc:        # unreadable image
            text = "(cannot preview: {})".format(exc)
        self.icon_thumb.configure(image=self._thumb or "", text=text,
                                  wraplength=150)

    def choose_icon_area(self):
        src = self.load_fg_path.get().strip()
        if not src or not os.path.isfile(src):
            messagebox.showinfo("No loading portrait",
                                "Pick the loading portrait (foreground) "
                                "image first.", parent=self)
            return
        try:
            dialog = IconCropDialog(self, src, self.icon_crop,
                                    self.icon_border_color,
                                    self.icon_border_width)
        except ImportError:
            messagebox.showwarning("Pillow needed", "Cutting the icon out of "
                                   "the portrait needs Pillow "
                                   "(pip install Pillow).", parent=self)
            return
        except Exception as exc:
            messagebox.showwarning("Cannot open image", str(exc), parent=self)
            return
        self.wait_window(dialog)
        self.grab_set()                 # the dialog took the grab
        if dialog.result:
            (self.icon_crop, self.icon_border_color,
             self.icon_border_width) = dialog.result
            self._refresh_icon_thumb()

    def pick_color(self, which):
        initial = getattr(self, which)
        rgb, _ = colorchooser.askcolor(
            parent=self, initialcolor="#%02x%02x%02x" % tuple(initial))
        if rgb:
            setattr(self, which, tuple(int(c) for c in rgb))
            self._refresh_swatches()

    def _refresh_swatches(self):
        for attr, label in ((self.primary, self.primary_lbl),
                            (self.secondary, self.secondary_lbl)):
            r, g, b = attr
            label.config(
                text="({},{},{})".format(r, g, b),
                background="#%02x%02x%02x" % (r, g, b))

    def browse_image(self, var, title):
        path = filedialog.askopenfilename(
            parent=self, title="Choose " + title.lower(),
            filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.tga *.dds"),
                       ("All files", "*.*")])
        if path:
            var.set(path)

    # -- result -------------------------------------------------------------

    def on_ok(self):
        texts = self.current_texts()
        spec = {
            "name": self.name_var.get().strip(),
            "sex": self.sex_var.get(),
            "civ": self.civ_var.get().strip(),
            "orig": self.orig_var.get().strip(),
            "bio": self.bio.get("1.0", "end").strip(),
            "quote": self.quote_var.get().strip(),
            "texts": texts,
            "primary": tuple(self.primary),
            "secondary": tuple(self.secondary),
            "icon_path": self.icon_path.get().strip(),
            "icon_mode": self.icon_mode.get(),
            "icon_crop": tuple(self.icon_crop) if self.icon_crop else None,
            "icon_border_color": tuple(self.icon_border_color),
            "icon_border_width": int(self.icon_border_width),
            "moment_illustrations": self.moment_illustrations(),
            "agenda": self._agenda_type(),
            "agenda_name": self.agenda_name_var.get().strip(),
            "agenda_desc": self.agenda_desc.get("1.0", "end").strip(),
            "abilities": self.abilities(),
            "city_names": self.city_names(),
            "load_fg_path": self.load_fg_path.get().strip(),
            "load_bg_path": self.load_bg_path.get().strip(),
            "diplo_bg_path": self.diplo_bg_path.get().strip(),
            "diplo_bg_mask": bool(self.diplo_bg_mask.get()),
        }
        if not spec["name"]:
            messagebox.showwarning("Missing name",
                                   "Please enter the leader's name.",
                                   parent=self)
            return
        self.result = spec
        self.destroy()


# ---------------------------------------------------------------------------
# Main application window
# ---------------------------------------------------------------------------

class GeneratorApp(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("Civ 6 Alt-Leader Mod Generator")
        self.minsize(760, 520)
        self._set_window_icon()

        self.data = GameData()
        self.project = self._empty_project()
        self.project_path = None
        self._saved_state = None

        self._build_widgets()
        self._refresh_leader_list()
        self._mark_saved()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _set_window_icon(self):
        """assets/icon.png as the icon of this and every other window."""
        path = asset_path(APP_ICON)
        if not path:
            return
        try:
            from PIL import Image, ImageTk
            src = Image.open(path).convert("RGBA")
            self._icons = [ImageTk.PhotoImage(src.resize((s, s),
                                                         Image.LANCZOS))
                           for s in (256, 64, 48, 32, 16)]
        except ImportError:             # Tk 8.6 reads PNG by itself
            self._icons = [tk.PhotoImage(file=path)]
        except Exception:               # unreadable image: keep Tk's icon
            return
        self.iconphoto(True, *self._icons)

    # -- project helpers ----------------------------------------------------

    @staticmethod
    def _empty_project():
        return {
            "mod_name": "Alternate Leaders",
            "prefix": "",
            "output_dir": GeneratorApp.default_out_dir(),
            "guid": str(uuid.uuid4()),
            "leaders": [],
        }

    @staticmethod
    def default_out_dir():
        home = os.path.expanduser("~")
        for docs in (os.path.join(home, "OneDrive", "Documents"),
                     os.path.join(home, "Documents")):
            path = os.path.join(docs, "My Games",
                                "Sid Meier's Civilization VI", "Mods")
            if os.path.isdir(os.path.dirname(path)):
                return path
        return os.path.join(home, "Civ6Mods")

    def type_prefix(self):
        """The project-wide type prefix (cleaned), e.g. 'RFVS'."""
        return clean_prefix(self.prefix_var.get())

    # -- data lookups ---------------------------------------------------------

    def all_civs(self):
        return sorted(set(self.data.civ_to_leaders) | set(FALLBACK_DATA))

    def all_leaders(self):
        return sorted({l for src in (self.data.civ_to_leaders, FALLBACK_DATA)
                       for leaders in src.values() for l in leaders})

    def leaders_for_civ(self, civ):
        for src in (self.data.civ_to_leaders, FALLBACK_DATA):
            if civ in src:
                return sorted(set(src[civ]))
        return self.all_leaders()

    # -- widget construction ---------------------------------------------------

    def _build_widgets(self):
        pad = {"padx": 6, "pady": 3}
        top = ttk.Frame(self, padding=10)
        top.pack(fill="both", expand=True)

        # -- project row
        ttk.Label(top, text="Project:").grid(row=0, column=0, sticky="w",
                                             **pad)
        ttk.Button(top, text="New", command=self.on_new_project).grid(
            row=0, column=1, sticky="w", **pad)
        ttk.Button(top, text="Open...", command=self.on_open_project).grid(
            row=0, column=2, sticky="w", **pad)
        self.save_btn = ttk.Button(top, text="Save...",
                                   command=self.on_save_project)
        self.save_btn.grid(row=0, column=3, sticky="w", **pad)
        self.project_label = ttk.Label(top, text="(unsaved)")
        self.project_label.grid(row=0, column=4, sticky="w", **pad)

        # -- game cache row
        ttk.Label(top, text="Game data:").grid(row=1, column=0, sticky="w",
                                               **pad)
        ttk.Button(top, text="Load from game cache...",
                   command=self.on_load_cache).grid(row=1, column=1,
                                                    columnspan=2,
                                                    sticky="w", **pad)
        self.cache_label = ttk.Label(top, text="using built-in list")
        self.cache_label.grid(row=1, column=3, columnspan=2, sticky="w",
                              **pad)

        # -- mod name row
        ttk.Label(top, text="Mod name:").grid(row=2, column=0, sticky="w",
                                              **pad)
        self.mod_name_var = tk.StringVar(
            value=self.project["mod_name"])
        ttk.Entry(top, textvariable=self.mod_name_var, width=32).grid(
            row=2, column=1, columnspan=2, sticky="w", **pad)
        prefix_row = ttk.Frame(top)
        prefix_row.grid(row=2, column=3, columnspan=2, sticky="w", **pad)
        ttk.Label(prefix_row, text="Type prefix:").pack(side="left")
        self.prefix_var = tk.StringVar(value=self.project.get("prefix", ""))
        ttk.Entry(prefix_row, textvariable=self.prefix_var, width=10).pack(
            side="left", padx=(6, 6))
        self.prefix_hint = ttk.Label(prefix_row, text="")
        self.prefix_hint.pack(side="left")
        self.prefix_var.trace_add("write", lambda *_: self.prefix_hint.config(
            text="-> " + slug_for_name("Name", self.type_prefix())))
        self.prefix_var.set(self.prefix_var.get())   # show the hint

        # -- leader list
        # tall rows so each leader's icon fits next to their name
        ttk.Style(self).configure("Leaders.Treeview",
                                  rowheight=LIST_ICON_SIZE + 8)
        list_frame = ttk.Frame(top)
        list_frame.grid(row=3, column=0, columnspan=4, sticky="nsew", **pad)
        self.tree = ttk.Treeview(list_frame, columns=("civ", "orig", "icon"),
                                  show="tree headings", height=8,
                                  selectmode="extended",
                                  style="Leaders.Treeview")
        self.tree_scroll = ttk.Scrollbar(list_frame, orient="vertical",
                                         command=self.tree.yview)
        self.tree.configure(yscrollcommand=self._on_tree_scrolled)
        # "3 leaders" / "Showing 1-8 of 12 leaders - scroll for more"
        self.list_hint = ttk.Label(list_frame, text="")
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree_scroll.grid(row=0, column=1, sticky="ns")
        self.list_hint.grid(row=1, column=0, columnspan=2, sticky="w",
                            pady=(3, 0))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        self.tree.heading("#0", text="Leader")
        self.tree.column("#0", width=230)
        self.tree.heading("civ", text="Civilization")
        self.tree.column("civ", width=180)
        self.tree.heading("orig", text="Inherits from")
        self.tree.column("orig", width=160)
        self.tree.heading("icon", text="Custom")
        self.tree.column("icon", width=140, anchor="w")
        ttk.Label(list_frame, foreground="gray", text="   ".join(
            "{} {}".format(symbol, what) for symbol, what in CUSTOM_MARKS)
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(3, 0))
        self.tree_tip = Tooltip(self.tree)
        self.tree.bind("<Motion>", self._on_tree_motion)
        self.tree.bind("<Leave>", lambda e: self.tree_tip.hide())
        self.tree.bind("<Double-1>", lambda e: self.on_edit_leader())

        btns = ttk.Frame(top)
        btns.grid(row=3, column=4, sticky="n", pady=3)
        for text, cmd in (("Add...", self.on_add_leader),
                          ("Edit...", self.on_edit_leader),
                          ("Duplicate", self.on_duplicate_leader),
                          ("Remove", self.on_remove_leader)):
            ttk.Button(btns, text=text, command=cmd).pack(fill="x", pady=2)
        ttk.Separator(btns).pack(fill="x", pady=6)
        for text, cmd in (("Export...", self.on_export_leaders),
                          ("Import...", self.on_import_leaders)):
            ttk.Button(btns, text=text, command=cmd).pack(fill="x", pady=2)

        # -- output folder row
        ttk.Label(top, text="Output folder:").grid(row=4, column=0,
                                                   sticky="w", **pad)
        self.out_var = tk.StringVar(value=self.project["output_dir"])
        ttk.Entry(top, textvariable=self.out_var, width=44).grid(
            row=4, column=1, columnspan=3, sticky="w", **pad)
        ttk.Button(top, text="Browse...", command=self.on_browse_out).grid(
            row=4, column=4, sticky="w", **pad)

        # -- generate
        self.generate_btn = ttk.Button(top, text="Generate mod",
                                        command=self.on_generate)
        self.generate_btn.grid(row=5, column=0, sticky="w", padx=6, pady=10)

        top.columnconfigure(0, weight=0)
        top.columnconfigure(1, weight=1)
        top.rowconfigure(3, weight=1)

        for var in (self.mod_name_var, self.prefix_var, self.out_var):
            var.trace_add("write", lambda *_: self._update_save_button())

    # -- unsaved-changes tracking ----------------------------------------------

    def _project_state(self):
        """What a save writes, to compare against the last saved state."""
        return (self.mod_name_var.get().strip() or "Alternate Leaders",
                self.type_prefix(), self.out_var.get().strip(),
                copy.deepcopy(self.project["leaders"]))

    def _mark_saved(self):
        """The current state is what is on disk (or a fresh project)."""
        self._saved_state = self._project_state()
        self._update_save_button()

    def _has_unsaved_changes(self):
        return self._project_state() != self._saved_state

    def on_close(self):
        """Window close: offer to save unsaved edits first."""
        if self._has_unsaved_changes():
            answer = messagebox.askyesnocancel(
                "Unsaved changes",
                "The project has unsaved changes. Save them before "
                "closing?")
            if answer is None:          # Cancel: keep working
                return
            if answer:
                self.on_save_project()
                if self._has_unsaved_changes():     # save cancelled/failed
                    return
        self.destroy()

    def _update_save_button(self):
        if self._saved_state is None:   # still building the widgets
            return
        self.save_btn.state(["!disabled"] if self._has_unsaved_changes()
                            else ["disabled"])

    # -- list handling ---------------------------------------------------------

    def _on_tree_scrolled(self, first, last):
        """yscrollcommand: move the scrollbar and say which rows show."""
        self.tree_scroll.set(first, last)
        count = len(self.project["leaders"])
        first, last = float(first), float(last)
        if count and (first > 0 or last < 1):
            text = "Showing {}-{} of {} leaders - scroll for more".format(
                round(first * count) + 1, round(last * count), count)
        else:
            text = "{} leader{}".format(count, "" if count == 1 else "s")
        self.list_hint.config(text=text)

    def _refresh_leader_list(self):
        self.tree.delete(*self.tree.get_children())
        self._list_icons = []           # Tk drops images nobody references
        for i, spec in enumerate(self.project["leaders"]):
            photo = ""
            try:
                from PIL import ImageTk
                photo = ImageTk.PhotoImage(
                    leader_icon_preview(spec, LIST_ICON_SIZE))
                self._list_icons.append(photo)
            except ImportError:         # no Pillow: names only
                pass
            self.tree.insert("", "end", iid=str(i),
                             text="  " + spec.get("name", ""), image=photo,
                             values=(spec.get("civ", ""),
                                     spec.get("orig", ""),
                                     " ".join(symbol for symbol, _ in
                                              leader_custom_marks(spec))))
        self._on_tree_scrolled(*self.tree.yview())
        self._update_save_button()

    def _on_tree_motion(self, event):
        """Explain the Custom column's symbols under the mouse."""
        text = ""
        if self.tree.identify_column(event.x) == "#3":      # "icon"
            region = self.tree.identify_region(event.x, event.y)
            row = self.tree.identify_row(event.y)
            if region == "heading":
                text = "What each leader customizes:\n" + "\n".join(
                    "{}  {}".format(*mark) for mark in CUSTOM_MARKS)
            elif region == "cell" and row:
                marks = leader_custom_marks(
                    self.project["leaders"][int(row)])
                text = "\n".join("{}  Custom {}".format(*mark)
                                 for mark in marks) or (
                    "Uses the original leader's backgrounds, agenda,\n"
                    "texts and historic moments.")
        self.tree_tip.show(text)

    def _selected_index(self):
        sel = self.tree.selection()
        if not sel:
            return None
        return int(sel[0])

    def _selected_indices(self):
        return sorted(int(iid) for iid in self.tree.selection())

    def _edit_dialog(self, spec, title):
        editor = LeaderEditor(self, spec, title=title)
        self.wait_window(editor)
        return editor.result

    def on_add_leader(self):
        result = self._edit_dialog(new_leader_spec(), "Add leader")
        if result:
            self.project["leaders"].append(result)
            self._refresh_leader_list()
            self.tree.selection_set(str(len(self.project["leaders"]) - 1))

    def on_edit_leader(self):
        i = self._selected_index()
        if i is None:
            messagebox.showinfo("No selection",
                                "Select a leader in the list first.")
            return
        spec = self.project["leaders"][i]
        result = self._edit_dialog(dict(spec), "Edit " + spec.get("name", ""))
        if result:
            self.project["leaders"][i] = result
            self._refresh_leader_list()
            self.tree.selection_set(str(i))

    def on_duplicate_leader(self):
        i = self._selected_index()
        if i is None:
            messagebox.showinfo("No selection",
                                "Select a leader in the list first.")
            return
        spec = dict(self.project["leaders"][i])
        spec["name"] = (spec.get("name") or "Leader") + " copy"
        self.project["leaders"].insert(i + 1, spec)
        self._refresh_leader_list()
        self.tree.selection_set(str(i + 1))

    def on_remove_leader(self):
        indices = self._selected_indices()
        if not indices:
            messagebox.showinfo("No selection",
                                "Select a leader in the list first.")
            return
        if len(indices) > 1 and not messagebox.askyesno(
                "Remove leaders",
                "Remove the {} selected leaders?".format(len(indices))):
            return
        for i in reversed(indices):
            del self.project["leaders"][i]
        self._refresh_leader_list()

    def on_export_leaders(self):
        """Export the selected leaders (all of them if none is selected)
        with their images, for importing into another project."""
        leaders = self.project["leaders"]
        specs = [leaders[i] for i in self._selected_indices()] or leaders
        if not specs:
            messagebox.showinfo("No leaders",
                                "The project has no leaders to export.")
            return
        name = specs[0].get("name") if len(specs) == 1 \
            else self.mod_name_var.get()
        path = filedialog.asksaveasfilename(
            title="Export {} leader(s)".format(len(specs)),
            initialfile=safe_folder_name(name) + ".altleaders",
            defaultextension="altleaders",
            filetypes=[("Alt-leader export", "*.altleaders")])
        if not path:
            return
        try:
            missing = export_leaders(specs, path)
        except (OSError, zipfile.BadZipFile) as exc:
            messagebox.showerror("Could not export leaders", str(exc))
            return
        message = "Exported {} leader(s) to:\n{}".format(len(specs), path)
        if missing:
            message += ("\n\n{} image(s) were not found and are not "
                        "included:\n{}".format(len(missing),
                                               "\n".join(missing[:10])) +
                        ("\n..." if len(missing) > 10 else ""))
        messagebox.showinfo("Leaders exported", message)

    def on_import_leaders(self):
        """Add the leaders of an export to this project. Leaders with the
        same type as one already here replace it or are skipped."""
        path = filedialog.askopenfilename(
            title="Import leaders",
            filetypes=[("Alt-leader export", "*.altleaders"),
                       ("All files", "*.*")])
        if not path:
            return
        try:
            specs, version = import_leaders(path)
        except (ValueError, OSError) as exc:
            messagebox.showerror("Could not import leaders", str(exc))
            return
        if version < 2:
            self._migrate_icon_crops(specs)
        prefix = self.type_prefix()
        leaders = self.project["leaders"]
        slugs = {slug_for_name(s.get("name"), prefix): i
                 for i, s in enumerate(leaders)}
        slugs.pop("", None)
        clashes = [s.get("name") for s in specs
                   if slug_for_name(s.get("name"), prefix) in slugs]
        replace = False
        if clashes:
            replace = messagebox.askyesnocancel(
                "Leaders already in the project",
                "{} imported leader(s) are already in this project:\n{}\n\n"
                "Yes: replace them\nNo: skip them\nCancel: import nothing"
                .format(len(clashes), "\n".join(clashes[:10]) +
                        ("\n..." if len(clashes) > 10 else "")))
            if replace is None:
                return
        changed = []
        for spec in specs:
            slug = slug_for_name(spec.get("name"), prefix)
            i = slugs.get(slug)
            if i is None:
                leaders.append(spec)
                i = len(leaders) - 1
                if slug:
                    slugs[slug] = i
            elif replace:
                leaders[i] = spec
            else:
                continue
            changed.append(i)
        self._refresh_leader_list()
        self.tree.selection_set([str(i) for i in changed])
        messagebox.showinfo(
            "Leaders imported",
            "Imported {} of {} leader(s).".format(len(changed), len(specs)))

    # -- project save / load ----------------------------------------------------

    def on_new_project(self):
        if self.project["leaders"] and not messagebox.askyesno(
                "New project",
                "Discard the current project and start fresh?"):
            return
        self.project = self._empty_project()
        self.project_path = None
        self.mod_name_var.set(self.project["mod_name"])
        self.prefix_var.set(self.project["prefix"])
        self.out_var.set(self.project["output_dir"])
        self.project_label.config(text="(unsaved)")
        self._refresh_leader_list()
        self._mark_saved()

    def on_open_project(self):
        path = filedialog.askopenfilename(
            title="Open alt-leader project",
            filetypes=[("Alt-leader project", "*.altleader"),
                       ("All files", "*.*")])
        if not path:
            return
        try:
            with open(path, "rb") as fh:
                project = pickle.load(fh)
        except Exception as exc:
            messagebox.showerror("Could not open project", str(exc))
            return
        if (not isinstance(project, dict)
                or project.get("magic") != PROJECT_MAGIC
                or not isinstance(project.get("leaders"), list)):
            messagebox.showerror("Invalid project file",
                                 "This does not look like an alt-leader "
                                 "project file.")
            return
        for spec in project["leaders"]:
            if not isinstance(spec, dict) or "name" not in spec:
                messagebox.showerror("Invalid project file",
                                     "Project contains a malformed leader "
                                     "entry.")
                return
        if project.get("version", 1) < 2:
            self._migrate_icon_crops(project["leaders"])
        project["version"] = PROJECT_VERSION
        self.project = project
        self.project["output_dir"] = (project.get("output_dir")
                                      or self.default_out_dir())
        self.project_path = path
        self.mod_name_var.set(self.project.get("mod_name",
                                               "Alternate Leaders"))
        self.prefix_var.set(self.project.get("prefix", ""))
        self.out_var.set(self.project["output_dir"])
        self.project_label.config(text=os.path.basename(path))
        self._refresh_leader_list()
        self._mark_saved()

    @staticmethod
    def _migrate_icon_crops(leaders):
        """Version 1 projects chose the icon circle on the portrait as
        is; portraits are now fitted to PORTRAIT_SIZE first."""
        for spec in leaders:
            src = (spec.get("load_fg_path") or "").strip()
            if not spec.get("icon_crop") or not os.path.isfile(src):
                continue
            try:
                spec["icon_crop"] = fit_icon_crop(spec["icon_crop"], src)
            except Exception:           # no Pillow / unreadable image
                spec["icon_crop"] = None

    def on_save_project(self):
        self.project["mod_name"] = self.mod_name_var.get().strip() \
            or "Alternate Leaders"
        self.project["prefix"] = self.type_prefix()
        self.project["output_dir"] = self.out_var.get().strip()
        path = self.project_path
        if not path:
            path = filedialog.asksaveasfilename(
                title="Save alt-leader project",
                defaultextension="altleader",
                filetypes=[("Alt-leader project", "*.altleader")])
            if not path:
                return
            self.project_path = path
        payload = dict(self.project)
        payload["magic"] = PROJECT_MAGIC
        payload["version"] = PROJECT_VERSION
        payload["leaders"] = list(self.project["leaders"])
        try:
            with open(path, "wb") as fh:
                pickle.dump(payload, fh, protocol=pickle.HIGHEST_PROTOCOL)
        except OSError as exc:
            messagebox.showerror("Could not save project", str(exc))
            return
        self.project_label.config(text=os.path.basename(path))
        self._mark_saved()
        messagebox.showinfo("Project saved",
                            "Saved {} leader(s) to:\n{}".format(
                                len(self.project["leaders"]), path))

    # -- misc ---------------------------------------------------------------------

    def on_load_cache(self):
        path = find_game_cache()
        if not path:
            path = filedialog.askopenfilename(
                title="Locate DebugGameplay.sqlite",
                filetypes=[("Civ 6 debug cache", "DebugGameplay.sqlite"),
                           ("All files", "*.*")])
        if not path:
            return
        busy = BusyDialog(self, "Loading game data")
        busy.set_status("Reading the game cache and the DLC / mod texts...")
        try:
            busy.run(lambda: self.data.load(path))
        except sqlite3.Error as exc:
            messagebox.showerror("Could not read game data", str(exc))
            return
        self.cache_label.config(text=os.path.basename(path))
        messagebox.showinfo(
            "Game data loaded",
            "Loaded {} civilizations / {} leaders from your install. "
            "The leader editor dropdowns now use the real game data.\n\n{}"
            .format(len(self.data.civ_to_leaders), len(self.data.leader_meta),
                    "Found the colors of {} leaders.".format(
                        len(self.data.leader_colors))
                    if self.data.leader_colors else
                    "Leader colors were not found (game install folder not "
                    "detected) - pick colors by hand."))

    def on_browse_out(self):
        path = filedialog.askdirectory(title="Choose output folder")
        if path:
            self.out_var.set(path)

    # -- generation -----------------------------------------------------------------

    def on_generate(self):
        mod_name = self.mod_name_var.get().strip() or "Alternate Leaders"
        out_root = self.out_var.get().strip()
        if not out_root:
            messagebox.showwarning("Missing input", "Choose an output folder.")
            return
        if not self.project["leaders"]:
            messagebox.showwarning("No leaders",
                                   "Add at least one leader to the project.")
            return

        # 1) validate all leaders up front; collect every problem
        ctxs, errors, seen = [], [], {}
        for spec in self.project["leaders"]:
            try:
                c = normalize_spec(spec, self.data, self.type_prefix())
            except ValueError as exc:
                errors.append(str(exc))
                continue
            if c["slug"] in seen:
                errors.append("{}: duplicate type {} (already used by {}) - "
                              "rename one of them.".format(
                                  c["name"], c["slug"], seen[c["slug"]]))
                continue
            seen[c["slug"]] = c["name"]
            for m in c["moments"]:
                # MomentIllustrations is keyed by the item, not the leader
                other = seen.get(("moment", m["item"]))
                if other:
                    errors.append("{}: {} already has a historic moment "
                                  "picture from {} - the game allows one per "
                                  "item.".format(c["name"], m["item"], other))
                seen[("moment", m["item"])] = c["name"]
            ctxs.append(c)
        if errors:
            messagebox.showwarning("Problems found",
                                   "\n\n".join(errors))
            return
        existing = ["{} ({})".format(c["name"], c["slug"])
                    for c in ctxs if c["exists_in_game"]]
        if existing and not messagebox.askyesno(
                "Leaders already in the game data",
                "These leader types already exist in the loaded game data:"
                "\n\n{}\n\nThat is expected if the game cache includes an "
                "earlier version of this mod - then just make sure the old "
                "version is not enabled alongside the new one. If another "
                "mod defines them, the two mods will conflict.\n\n"
                "Generate the mod anyway?".format("\n".join(existing)),
                icon="warning"):
            return

        # 2) prepare and cook art (falls back to inherited art on failure)
        folder = safe_folder_name(mod_name)
        mod_dir = os.path.join(out_root, folder)
        report = []
        try:
            for sub in ("Config", "Gameplay", "Text"):
                os.makedirs(os.path.join(mod_dir, sub), exist_ok=True)
            # leftovers of older generator versions (loose .dds files)
            shutil.rmtree(os.path.join(mod_dir, "Art"), ignore_errors=True)
        except OSError as exc:
            messagebox.showerror("Could not create mod folder", str(exc))
            return

        # Reuse the project's mod id so re-generating updates the same mod
        # entry in Additional Content instead of creating a duplicate.
        guid = self.project.get("guid") or str(uuid.uuid4())
        self.project["guid"] = guid

        # may ask for the cooker - dialogs must happen before the worker
        cooker = (self._cooker_path() if any(needs_art(c) for c in ctxs)
                  else None)

        # 3) convert, cook and write in a thread behind a progress window
        busy = BusyDialog(self, "Generating mod")
        try:
            icon_count = busy.run(lambda: self._write_mod(
                mod_name, ctxs, folder, mod_dir, guid, cooker, report,
                busy.set_status))
        except OSError as exc:
            messagebox.showerror("Could not write mod", str(exc))
            return

        warnings = [r for r in report if r.startswith("WARNING")]
        warning_text = ("\n\n{} warning(s):\n{}\n(details in README.txt)"
                        .format(len(warnings), "\n".join(warnings[:5]))
                        if warnings else "")
        if messagebox.askyesno(
                "Done",
                "Mod written to:\n{}\n\n{} file operation(s), {} leader(s), "
                "{} custom icon(s).{}\n\nOpen the folder now?".format(
                    mod_dir, len(report), len(ctxs), icon_count,
                    warning_text)):
            self._open_folder(mod_dir)

    def _write_mod(self, mod_name, ctxs, folder, mod_dir, guid, cooker,
                   report, progress):
        """Cook the art and write every mod file (runs in a worker thread,
        so no Tk calls here; progress(text) updates the busy window).
        Returns the number of custom icons. Raises OSError."""
        (icon_leader_files, cooked_files, ui_package,
         fallback_package) = self._build_art(ctxs, folder, mod_dir, report,
                                             cooker, progress)
        progress("Writing mod files...")
        dep_file = folder + ".dep" if cooked_files else None
        has_moments = any(c["moments"] for c in ctxs)   # after art fallback

        # leaders without a diplomacy background of their own show the
        # original leader's layered scene through a patched LeaderScene.lua
        scene_lua, scene_problem = None, None
        if any(not c["diplo_bg"] for c in ctxs):
            scene_lua, scene_problem = patched_leader_scene(find_game_dir())
            if scene_problem:
                report.append("WARNING: {} - leaders without a diplomacy "
                              "background get an empty one".format(
                                  scene_problem))
        for c in ctxs:
            c["scene_from_orig"] = bool(scene_lua and not c["diplo_bg"])
        scene_path = os.path.join(mod_dir, *LEADER_SCENE_FILE.split("/"))

        mod_files = ["Config/NewLeader_Config.sql",
                     "Config/NewLeader_Colors.xml",
                     "Gameplay/NewLeader_Gameplay.sql",
                     "Text/NewLeader_Text.sql"]
        if icon_leader_files:
            mod_files.append("Config/NewLeader_Icons.xml")
        if has_moments:
            mod_files.append(MOMENTS_FILE)
        if scene_lua:
            mod_files.append(LEADER_SCENE_FILE)
        if dep_file:
            mod_files.append(dep_file)
            mod_files.extend(cooked_files)

        description = "Adds alternate leaders: {}.".format(
            ", ".join(c["name"] for c in ctxs))

        def write(rel, content):
            with open(os.path.join(mod_dir, rel), "w", encoding="utf-8",
                      newline="\n") as fh:
                fh.write(content)
            report.append("wrote " + rel)

        if dep_file:
            write(dep_file, build_dep(mod_name, guid, ui_package,
                                      fallback_package))
        elif os.path.isfile(os.path.join(mod_dir, folder + ".dep")):
            os.remove(os.path.join(mod_dir, folder + ".dep"))
        write("MyLeader.modinfo",
              build_modinfo(mod_name, description, guid,
                            bool(icon_leader_files), dep_file,
                            mod_files, has_moments, bool(scene_lua)))
        if scene_lua:
            os.makedirs(os.path.dirname(scene_path), exist_ok=True)
            write(LEADER_SCENE_FILE, scene_lua)
        elif os.path.isfile(scene_path):
            os.remove(scene_path)
        if has_moments:
            write(MOMENTS_FILE, build_moments_sql(ctxs))
        elif os.path.isfile(os.path.join(mod_dir, MOMENTS_FILE)):
            os.remove(os.path.join(mod_dir, MOMENTS_FILE))
        write("Config/NewLeader_Config.sql", build_config_sql(ctxs))
        if icon_leader_files:
            write("Config/NewLeader_Icons.xml",
                  build_icons_xml(icon_leader_files))
        write("Config/NewLeader_Colors.xml", build_colors_xml(ctxs))
        write("Gameplay/NewLeader_Gameplay.sql", build_gameplay_sql(ctxs))
        write("Text/NewLeader_Text.sql", build_text_sql(ctxs))
        write("README.txt", build_readme(mod_name, ctxs,
                                        len(icon_leader_files), report))
        return len(icon_leader_files)

    def _cooker_path(self):
        """The SDK asset cooker: remembered, auto-detected, or asked for."""
        path = self.project.get("cooker_path")
        if path and os.path.isfile(path):
            return path
        path = find_cooker()
        if not path:
            messagebox.showinfo(
                "Asset cooker needed",
                "Custom icons and loading images must be cooked with the "
                "Civ VI SDK asset cooker ({}).\n\nInstall \"Sid Meier's "
                "Civilization VI Development Tools\" from Steam, or locate "
                "the cooker in the next dialog.".format(COOKER_EXE))
            path = filedialog.askopenfilename(
                title="Locate " + COOKER_EXE,
                filetypes=[("Asset cooker", COOKER_EXE),
                           ("All files", "*.*")])
        if path:
            self.project["cooker_path"] = path
        return path or None

    def _build_art(self, ctxs, folder, mod_dir, report, cooker,
                   progress=lambda text: None):
        """Convert every custom image and cook them into .blp packages
        with cooker (None: not available). Returns (icon_leader_files,
        cooked mod-relative paths, UI package name or None, fallback
        package name or None). Art that cannot be produced falls back to
        the original leader's art. No Tk calls: runs in a worker thread."""
        ui_package, fallback_package = folder + "_UI", folder + "_Fallbacks"

        def inherit_art(c):
            c["leader_icon"] = c["icon_inherit"]
            c["load_fg"] = c["load_bg"] = c["diplo_bg"] = None
            c["moments"] = []           # no rows pointing at missing art

        def give_up(reason):
            if reason:
                report.append("WARNING: {} - using inherited art".format(
                    reason))
            for c in ctxs:
                inherit_art(c)
            for sub in ("Platforms", "ArtDefs"):
                shutil.rmtree(os.path.join(mod_dir, sub), ignore_errors=True)
            return [], [], None, None

        wanted = [c for c in ctxs if needs_art(c)]
        for c in ctxs:
            if not c["icon_custom"]:
                report.append("{} uses the icon of {}".format(
                    c["name"], c["orig"]))
            if not c["load_fg"]:
                report.append("{} has no loading portrait, so no diplomacy "
                              "image".format(c["name"]))
        if not wanted:
            return give_up(None)
        if not cooker:
            return give_up("SDK asset cooker not found")

        pantry = tempfile.mkdtemp(prefix="altleader_art_")
        try:
            ui_textures, fallbacks, icon_leader_files = [], [], []
            for i, c in enumerate(wanted, 1):
                progress("Converting images for {} ({} of {})...".format(
                    c["name"], i, len(wanted)))
                names, icons, fallback = [], [], None

                def convert(name, src, kind="ui", size=None):
                    if not add_texture(pantry, name, src, kind=kind,
                                       size=size):
                        raise RuntimeError("Pillow is not installed "
                                           "(pip install Pillow)")
                    report.append("converted " + name)

                try:
                    if c["icon_custom"]:
                        icon_src = c["icon_path"]
                        if c["icon_mode"] == "portrait":
                            # render the bordered circle once at high
                            # resolution, then scale it to every size
                            icon_src = os.path.join(
                                pantry, c["icon_name"] + "_source.png")
                            make_circle_icon(
                                fitted_portrait(c["load_fg_path"]),
                                c["icon_crop"],
                                c["icon_border_color"],
                                c["icon_border_width"]).save(icon_src)
                            report.append("cut {} out of the loading "
                                          "portrait".format(c["icon_name"]))
                        for size in ICON_SIZES:
                            tex = "{}_{}".format(c["icon_name"], size)
                            convert(tex, icon_src, size=size)
                            icons.append((size, tex))
                            names.append(tex)
                    if c["load_fg"]:
                        fg_src = os.path.join(
                            pantry, c["load_fg_name"] + "_fitted.png")
                        fitted_portrait(c["load_fg_path"]).save(fg_src)
                        report.append("fitted {} to {} x {}".format(
                            c["load_fg_name"], *PORTRAIT_SIZE))
                        convert(c["load_fg_name"], fg_src)
                        names.append(c["load_fg_name"])
                        # the diplomacy screen's 2D fallback uses the same
                        # picture, cooked as a LeaderFallback texture
                        convert(c["fallback_name"], fg_src, kind="fallback")
                        fallback = (c["slug"], c["fallback_name"])
                    if c["load_bg"]:
                        convert(c["load_bg_name"], c["load_bg_path"])
                        names.append(c["load_bg_name"])
                    if c["diplo_bg"]:
                        diplo_src = c["diplo_bg_path"]
                        mask = asset_path(DIPLO_BG_MASK)
                        if c["diplo_bg_mask"] and not mask:
                            report.append(
                                "WARNING: {} - assets/{} not found; the "
                                "diplomacy background is not masked".format(
                                    c["name"], DIPLO_BG_MASK))
                        elif c["diplo_bg_mask"]:
                            diplo_src = os.path.join(
                                pantry, c["diplo_bg_name"] + "_masked.png")
                            apply_image_mask(c["diplo_bg_path"],
                                             mask).save(diplo_src)
                            report.append("masked " + c["diplo_bg_name"])
                        convert(c["diplo_bg_name"], diplo_src)
                        names.append(c["diplo_bg_name"])
                    for m in c["moments"]:
                        moment_src = m["path"]
                        mask = asset_path(MOMENT_MASK) if m["mask"] else None
                        if m["mask"] and not mask:
                            report.append(
                                "WARNING: {} - assets/{} not found; the {} "
                                "moment picture is not masked".format(
                                    c["name"], MOMENT_MASK, m["item"]))
                        if mask or m["half"] or m["sepia"]:
                            moment_src = os.path.join(
                                pantry, m["texture"] + "_edited.png")
                            apply_image_mask(
                                m["path"], mask,
                                size=MOMENT_ILLUSTRATION_SIZE,
                                opacity=MOMENT_HALF_OPACITY if m["half"]
                                else 1.0, sepia=m["sepia"]).save(moment_src)
                            report.append("edited " + m["texture"])
                        convert(m["texture"], moment_src,
                                size=MOMENT_ILLUSTRATION_SIZE)
                        names.append(m["texture"])
                except Exception as exc:  # unreadable image, disk error, ...
                    report.append("WARNING: {} - could not convert art ({}); "
                                  "using the art of {}".format(
                                      c["name"], exc, c["orig"]))
                    inherit_art(c)
                    continue
                ui_textures.extend(names)
                if fallback:
                    fallbacks.append(fallback)
                if icons:
                    icon_leader_files.append((c, icons))

            packages = {}
            if ui_textures:
                packages[ui_package] = ("ui", ui_textures)
            if fallbacks:
                packages[fallback_package] = (
                    "fallback", [tex for _, tex in fallbacks])
            if not packages:
                return give_up(None)
            progress("Cooking art with the SDK asset cooker (this can take "
                     "a minute)...")
            cooked = cook_art(cooker, pantry, packages, fallbacks, mod_dir,
                              report)
            if not cooked:
                return give_up("cooking failed")
            return (icon_leader_files, cooked,
                    ui_package if ui_textures else None,
                    fallback_package if fallbacks else None)
        finally:
            shutil.rmtree(pantry, ignore_errors=True)

    @staticmethod
    def _open_folder(path):
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)  # noqa: S605 (Windows only API)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except OSError:
            pass


if __name__ == "__main__":
    GeneratorApp().mainloop()