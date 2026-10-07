"""Small helpers: SQL / XML escaping, type names, game folders."""

import os
import re
import sys


# ---------------------------------------------------------------------------
# Escaping and type names
# ---------------------------------------------------------------------------

def sql_str(value):
    """Escape a value for a single-quoted SQL string literal."""
    return "'" + str(value).replace("'", "''") + "'"


def value_or_column(value, column):
    """SQL for INSERT ... SELECT: a literal override, or copy the column."""
    return sql_str(value) if value else column


def xml_escape(value):
    """Escape a string for use as XML text (modinfo Name/Description)."""
    return (str(value)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))


def clean_prefix(prefix):
    """Project type prefix as used in type names, e.g. 'rfvs' -> 'RFVS'."""
    return re.sub(r"[^0-9A-Za-z]+", "_", prefix or "").strip("_").upper()


def slug_for_name(name, prefix="", kind="LEADER"):
    """Turn a display name into a Civ 6 type slug, e.g. 'Jeanne d'Arc'
    -> 'LEADER_JEANNE_D_ARC', or with prefix 'RFVS' ->
    'LEADER_RFVS_JEANNE_D_ARC'. The prefix keeps the types (and every
    icon, texture and text tag derived from them) from colliding with
    other mods' types. kind is the type's first word: LEADER,
    CIVILIZATION, UNIT, BUILDING, DISTRICT..."""
    base = re.sub(r"[^0-9A-Za-z]+", "_", name or "").strip("_").upper()
    if not base:
        return ""
    prefix = clean_prefix(prefix)
    if prefix and base != prefix and not base.startswith(prefix + "_"):
        base = prefix + "_" + base
    return kind + "_" + base


def type_display_name(type_name):
    """Readable stand-in for a type whose text is not in the cache, e.g.
    'AGENDA_ANGEVIN_EMPIRE' -> 'Angevin Empire'."""
    return type_name.split("_", 1)[-1].replace("_", " ").title()


def safe_folder_name(name):
    """Filesystem-safe folder name for a mod pack."""
    base = re.sub(r"[^0-9A-Za-z]+", "_", name or "").strip("_")
    return base or "AltLeaderPack"


# ---------------------------------------------------------------------------
# Folders: the game, its cache, Steam, mods, the generator's assets
# ---------------------------------------------------------------------------

GAME_FOLDER = "Sid Meier's Civilization VI"
WORKSHOP_APP_ID = "289070"


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


def find_game_dir():
    """The Civ VI install folder (Steam or Epic), or None."""
    candidates = [os.path.join(lib, "steamapps", "common", GAME_FOLDER)
                  for lib in steam_libraries()]
    candidates.append(r"C:\Program Files\Epic Games\SidMeiersCivilizationVI")
    return next((c for c in candidates
                 if os.path.isdir(os.path.join(c, "Base"))), None)


def default_out_dir():
    """The game's Mods folder (where generated mods go by default)."""
    home = os.path.expanduser("~")
    for docs in (os.path.join(home, "OneDrive", "Documents"),
                 os.path.join(home, "Documents")):
        path = os.path.join(docs, "My Games",
                            "Sid Meier's Civilization VI", "Mods")
        if os.path.isdir(os.path.dirname(path)):
            return path
    return os.path.join(home, "Civ6Mods")


def xml_under(folder, exts=(".xml",)):
    """Every file below folder with one of the extensions, sorted."""
    out = []
    for root, _dirs, files in os.walk(folder):
        out += [os.path.join(root, f) for f in files
                if f.lower().endswith(exts)]
    return sorted(out)


def asset_path(name):
    """Path of assets/<name> shipped with the generator, or None. Looks next
    to the civgen package (the script, or Nuitka's onefile extraction
    folder when built with --include-data-dir=assets=assets) and next to
    the executable."""
    bases = [os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
             os.path.dirname(os.path.abspath(sys.executable)),
             os.path.dirname(os.path.abspath(sys.argv[0] or "."))]
    for base in bases:
        path = os.path.join(base, "assets", name)
        if os.path.isfile(path):
            return path
    return None
