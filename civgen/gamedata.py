"""Game data from the game's debug SQLite cache and XML files."""

import os
import sqlite3
import xml.etree.ElementTree as ET

from .util import (WORKSHOP_APP_ID, default_out_dir, find_game_dir,
                   is_number, type_display_name, xml_under)
from .modifiers import MODIFIER_COLUMNS, REQUIREMENT_COLUMNS
from .artdefs import CULTURES_ARTDEF, civilization_music, game_element_names
from .unit_art import art_lists
from .unit_models import catalogue as unit_parts_catalogue
from .landmarks import mesh_choices


# Lists the editors offer: kind -> (table, type column, ORDER BY)
TYPE_KINDS = {
    "civilization": ("Civilizations", "CivilizationType", "CivilizationType"),
    "yield": ("Yields", "YieldType", "rowid"),
    "terrain": ("Terrains", "TerrainType", "rowid"),
    "feature": ("Features", "FeatureType", "FeatureType"),
    "resource": ("Resources", "ResourceType", "ResourceType"),
    "improvement": ("Improvements", "ImprovementType", "ImprovementType"),
    "era": ("Eras", "EraType", "ChronologyIndex"),
    "tech": ("Technologies", "TechnologyType", "Cost"),
    "civic": ("Civics", "CivicType", "Cost"),
    "promotion_class": ("UnitPromotionClasses", "PromotionClassType",
                        "PromotionClassType"),
    "great_person": ("GreatPersonClasses", "GreatPersonClassType",
                     "GreatPersonClassType"),
    "ability": ("UnitAbilities", "UnitAbilityType", "UnitAbilityType"),
}
# What in the game has modifiers whose effects the effect editor can
# copy: source -> (table linking an item to its modifiers, item column,
# item table, label)
MODIFIER_SOURCES = {
    "trait": ("TraitModifiers", "TraitType", "Traits",
              "Leader and civilization abilities"),
    "belief": ("BeliefModifiers", "BeliefType", "Beliefs", "Beliefs"),
    "building": ("BuildingModifiers", "BuildingType", "Buildings",
                 "Buildings and wonders"),
    "district": ("DistrictModifiers", "DistrictType", "Districts",
                 "Districts"),
    "improvement": ("ImprovementModifiers", "ImprovementType",
                    "Improvements", "Improvements"),
    "unit_ability": ("UnitAbilityModifiers", "UnitAbilityType",
                     "UnitAbilities", "Unit abilities"),
    "unit_promotion": ("UnitPromotionModifiers", "UnitPromotionType",
                       "UnitPromotions", "Unit promotions"),
    "governor_promotion": ("GovernorPromotionModifiers",
                           "GovernorPromotionType", "GovernorPromotions",
                           "Governor titles"),
    "great_person": ("GreatPersonIndividualActionModifiers",
                     "GreatPersonIndividualType", "GreatPersonIndividuals",
                     "Great people"),
}
# Kinds of unique items: kind -> (table, type column, replaces table)
ITEM_TABLES = {
    "unit": ("Units", "UnitType", "UnitReplaces"),
    "building": ("Buildings", "BuildingType", "BuildingReplaces"),
    "district": ("Districts", "DistrictType", "DistrictReplaces"),
    "improvement": ("Improvements", "ImprovementType", None),
}
# Gathering Storm-only columns of items, in their own table (only in the
# cache of a Gathering Storm game): kind -> (table, type column, {column:
# value of an item without a row})
ITEM_XP2_COLUMNS = {
    "unit": ("Units_XP2", "UnitType", {"ResourceCost": 0,
                                       "ResourceMaintenanceType": None,
                                       "ResourceMaintenanceAmount": 0}),
}
# Civilizations.Ethnicity values (unit portraits); used without the cache
ETHNICITIES = ["ETHNICITY_AFRICAN", "ETHNICITY_ASIAN", "ETHNICITY_EURO",
               "ETHNICITY_MEDIT", "ETHNICITY_SOUTHAM"]


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
    files += xml_under(default_out_dir(), exts)
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
    files += xml_under(default_out_dir())
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
        # CivilizationType -> abilities, like leader_abilities
        self.civ_abilities = {}
        self.civ_names = {}     # CivilizationType -> English name
        self.types = {}         # TYPE_KINDS key -> [(type, English name)]
        # "unit" / "building" / "district" -> {type: {column: value, ...,
        # "name": English name, "replaces": type or None}}
        self.items = {}
        self.cultures = []      # city art styles (Cultures.artdef)
        self.unit_cultures = []  # unit art styles
        self.civ_music = {}     # CivilizationType -> audio XrefName
        self.ethnicities = list(ETHNICITIES)
        # unit 3D model parts: {"members" / "formation" / "combat": [names]}
        self.unit_art = {"members": [], "formation": [], "combat": []}
        # unit model parts (see unit_models.catalogue)
        self.unit_parts = {"bins": {}, "points": [], "tints": [],
                           "models": [], "mounted": []}
        # building / district meshes: {"building" / "ground": [(mesh,
        # label)]} (see landmarks.mesh_choices)
        self.meshes = {"building": [], "ground": []}
        # the game's modifier types: {type: {"collection", "effect", "uses"
        # (how many of the game's modifiers have it), "args": [(name,
        # uses, an example value, whether always a number)]}}
        self.modifier_schema = {}
        # the game's requirement types: {type: {"uses", "args"}}, likewise
        self.requirement_schema = {}
        self.modifier_ids = set()           # the game's ModifierIds
        self.requirement_set_ids = set()    # and RequirementSetIds
        self._agenda_examples = None        # see agenda_examples

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
        self.civ_abilities = {}
        for civ, trait, name, desc in self._query(
                "SELECT CivilizationType, TraitType, Name, Description "
                "FROM CivilizationTraits JOIN Traits USING (TraitType) "
                "WHERE InternalOnly = 0 AND Name IS NOT NULL "
                "ORDER BY CivilizationType, TraitType"):
            if trait in item_traits:
                continue
            self.civ_abilities.setdefault(civ, []).append({
                "type": trait,
                "name": self.loc_text(name) or self._loc(name) or
                        type_display_name(trait),
                "desc": self.loc_text(desc) or self._loc(desc) or "",
                "name_tag": name, "desc_tag": desc})
        self._load_types()
        self._load_items()
        self._load_modifier_schema()
        game_dir = find_game_dir()
        self.cultures = game_element_names(game_dir, CULTURES_ARTDEF,
                                           "Culture")
        self.unit_cultures = game_element_names(game_dir, CULTURES_ARTDEF,
                                                "UnitCulture")
        self.civ_music = civilization_music(game_dir)
        self.unit_art = art_lists(game_dir)
        if game_dir:
            self.unit_parts = unit_parts_catalogue(game_dir)
            self.meshes = {kind: mesh_choices(game_dir, kind)
                           for kind in ("building", "ground")}
        found = [e for (e,) in self._query(
            "SELECT DISTINCT Ethnicity FROM Civilizations "
            "WHERE Ethnicity IS NOT NULL ORDER BY 1")]
        self.ethnicities = found or list(ETHNICITIES)

    def _name(self, tag, type_name):
        return (self.loc_text(tag) or self._loc(tag) or
                type_display_name(type_name)) if tag else \
            type_display_name(type_name)

    def _load_types(self):
        """Every TYPE_KINDS list, with English names, for the editors'
        dropdowns."""
        self.types = {}
        for kind, (table, column, order) in TYPE_KINDS.items():
            where = ""
            if kind == "civilization":
                where = (" WHERE StartingCivilizationLevelType = "
                         "'CIVILIZATION_LEVEL_FULL_CIV'")
            self.types[kind] = [
                (t, self._name(name, t)) for t, name in self._query(
                    'SELECT {}, Name FROM "{}"{} ORDER BY {}'.format(
                        column, table, where, order))]
        self.civ_names = dict(self.types.get("civilization", []))
        # features that are not natural wonders (district placement)
        self.types["plain_feature"] = [
            (t, self._name(name, t)) for t, name in self._query(
                "SELECT FeatureType, Name FROM Features WHERE "
                "NaturalWonder = 0 ORDER BY FeatureType")]
        # resources a unit can cost (and use up each turn)
        self.types["strategic_resource"] = [
            (t, self._name(name, t)) for t, name in self._query(
                "SELECT ResourceType, Name FROM Resources WHERE "
                "ResourceClassType = 'RESOURCECLASS_STRATEGIC' "
                "ORDER BY ResourceType")]

    def _load_items(self):
        """Every unit, building and district with all its columns, to
        clone as a unique item and show the base item's stats."""
        self.items = {}
        for kind, (table, column, replaces) in ITEM_TABLES.items():
            cur = None
            try:
                cur = self.conn.execute('SELECT * FROM "{}"'.format(table))
            except sqlite3.Error:
                self.items[kind] = {}
                continue
            columns = [d[0] for d in cur.description]
            rows = {}
            for values in cur.fetchall():
                row = dict(zip(columns, values))
                row["name"] = self._name(row.get("Name"), row[column])
                row["replaces"] = None
                rows[row[column]] = row
            for unique, base in self._query(
                    'SELECT * FROM "{}"'.format(replaces)) if replaces \
                    else ():
                if unique in rows:
                    rows[unique]["replaces"] = base
            if kind in ITEM_XP2_COLUMNS:
                self._load_xp2_columns(kind, rows)
            if kind == "unit":          # what it upgrades to (None: nothing)
                for row in rows.values():
                    row["UpgradeUnit"] = None
                for unit, upgrade in self._query(
                        "SELECT Unit, UpgradeUnit FROM UnitUpgrades"):
                    if unit in rows:
                        rows[unit]["UpgradeUnit"] = upgrade
            self.items[kind] = rows

    def _load_modifier_schema(self):
        """The game's modifier and requirement types and the arguments
        its own modifiers give them (the advanced effect editor's
        suggestions and checks), and its modifier and requirement set
        ids."""
        self.modifier_schema = {
            t: {"collection": c, "effect": e, "uses": 0, "args": []}
            for t, c, e in self._query(
                "SELECT ModifierType, CollectionType, EffectType FROM "
                "DynamicModifiers")}
        self.requirement_schema = {t: {"uses": 0, "args": []} for (t,) in
                                   self._query(
            "SELECT Type FROM Types WHERE Kind = 'KIND_REQUIREMENT' UNION "
            "SELECT RequirementType FROM Requirements")}
        for schema, uses, args in (
                (self.modifier_schema,
                 "SELECT ModifierType, COUNT(*) FROM Modifiers GROUP BY 1",
                 "SELECT m.ModifierType, a.Name, a.Value FROM Modifiers m "
                 "JOIN ModifierArguments a USING (ModifierId) "
                 "ORDER BY a.rowid"),
                (self.requirement_schema,
                 "SELECT RequirementType, COUNT(*) FROM Requirements "
                 "GROUP BY 1",
                 "SELECT r.RequirementType, a.Name, a.Value FROM "
                 "Requirements r JOIN RequirementArguments a USING "
                 "(RequirementId) ORDER BY a.rowid")):
            for t, n in self._query(uses):
                if t in schema:
                    schema[t]["uses"] = n
            found = {}
            for t, name, value in self._query(args):
                entry = found.setdefault((t, name), [0, value, True])
                entry[0] += 1
                entry[2] = entry[2] and is_number(value)
            for (t, name), (n, example, numeric) in found.items():
                if t in schema:
                    schema[t]["args"].append((name, n, example, numeric))
            for entry in schema.values():
                entry["args"].sort(key=lambda a: (-a[1], a[0]))
        self._agenda_examples = None        # (read when first needed)
        self.modifier_ids = {m for (m,) in self._query(
            "SELECT ModifierId FROM Modifiers")}
        self.requirement_set_ids = {s for (s,) in self._query(
            "SELECT RequirementSetId FROM RequirementSets")}

    def _load_xp2_columns(self, kind, rows):
        """Add an item kind's Gathering Storm-only columns to its rows
        (see ITEM_XP2_COLUMNS), if the cache has them."""
        table, column, defaults = ITEM_XP2_COLUMNS[kind]
        try:
            found = self.conn.execute('SELECT {}, {} FROM "{}"'.format(
                column, ", ".join(defaults), table)).fetchall()
        except sqlite3.Error:
            return                      # not a Gathering Storm game
        for row in rows.values():
            row.update(defaults)
        for values in found:
            if values[0] in rows:
                rows[values[0]].update(zip(defaults, values[1:]))

    def type_choices(self, kind):
        """[(type, English name)] of a TYPE_KINDS list ([] without the
        cache)."""
        if kind in ITEM_TABLES:
            return [(t, row["name"]) for t, row in sorted(
                (self.items.get(kind) or {}).items(),
                key=lambda kv: kv[1]["name"])]
        return self.types.get(kind) or []

    def unique_choices(self, kind):
        """type_choices for a unique to copy, replace or look like: no
        wonders among the buildings (a wonder is one of a kind in the
        world, and is built and drawn differently)."""
        choices = self.type_choices(kind)
        if kind == "building":
            items = self.items.get("building") or {}
            choices = [(t, n) for t, n in choices
                       if not (items.get(t) or {}).get("IsWonder")]
        return choices

    def type_name(self, kind, type_name):
        """English name of a type, or a readable stand-in."""
        if kind in ITEM_TABLES:
            row = (self.items.get(kind) or {}).get(type_name)
            if row:
                return row["name"]
        for t, name in self.types.get(kind) or []:
            if t == type_name:
                return name
        return type_display_name(type_name) if type_name else ""

    def item(self, kind, type_name):
        """A unit / building / district row (see items), or None."""
        return (self.items.get(kind) or {}).get(type_name)

    def district_placement(self, district):
        """A district's placement rules as a placement spec (see
        uniques.PLACEMENT_DEFAULTS), or None if it is unknown."""
        row = self.item("district", district)
        if not row:
            return None
        return {
            "water": bool(row.get("Coast")),
            "terrains": [t for (t,) in self._query(
                "SELECT TerrainType FROM District_ValidTerrains WHERE "
                "DistrictType = ? ORDER BY 1", (district,))],
            "features": [f for (f,) in self._query(
                "SELECT FeatureType FROM District_RequiredFeatures WHERE "
                "DistrictType = ? ORDER BY 1", (district,))],
            "no_adjacent_city": bool(row.get("NoAdjacentCity")),
            "one_per_city": bool(row.get("OnePerCity", 1)),
            "max_per_player": int(row.get("MaxPerPlayer") or -1)}

    def improvement_placement(self, improvement):
        """An improvement's placement rules as a placement spec (see
        uniques.IMPROVEMENT_PLACEMENT_DEFAULTS), or None if unknown."""
        row = self.item("improvement", improvement)
        if not row:
            return None

        def types(table, column):
            return [t for (t,) in self._query(
                "SELECT {} FROM {} WHERE ImprovementType = ? ORDER BY 1"
                .format(column, table), (improvement,))]
        return {
            "terrains": types("Improvement_ValidTerrains", "TerrainType"),
            "features": types("Improvement_ValidFeatures", "FeatureType"),
            "resources": types("Improvement_ValidResources", "ResourceType"),
            "river": bool(row.get("RequiresRiver")),
            "no_same_adjacent": not row.get("SameAdjacentValid", 1),
            "one_per_city": bool(row.get("OnePerCity")),
            "outside_territory": bool(row.get("CanBuildOutsideTerritory"))}

    # (kind, "yields" / "gpp") -> (table, item column, type column, amount)
    NUMBER_TABLES = {
        ("building", "yields"): ("Building_YieldChanges", "BuildingType",
                                 "YieldType", "YieldChange"),
        ("improvement", "yields"): ("Improvement_YieldChanges",
                                    "ImprovementType", "YieldType",
                                    "YieldChange"),
        ("building", "gpp"): ("Building_GreatPersonPoints", "BuildingType",
                              "GreatPersonClassType", "PointsPerTurn"),
        ("district", "gpp"): ("District_GreatPersonPoints", "DistrictType",
                              "GreatPersonClassType", "PointsPerTurn")}

    def base_numbers(self, kind, item, key):
        """{type: amount} of an item's yields ("yields") or great person
        points ("gpp"), or {}."""
        spec = self.NUMBER_TABLES.get((kind, key))
        if not spec or not self.conn:
            return {}
        table, column, type_column, amount = spec
        return {t: n for t, n in self._query(
            'SELECT {}, {} FROM "{}" WHERE {} = ?'.format(
                type_column, amount, table, column), (item,)) if n}

    def base_effects(self, kind, item):
        """The game's modifiers of a building, district or improvement (a
        unique's base item; see game_modifiers)."""
        if kind not in ("building", "district", "improvement"):
            return []
        return self.game_modifiers(kind, item)

    def source_items(self, source):
        """[(type, English name)] of the items of a MODIFIER_SOURCES kind
        that have modifiers, by name."""
        table, column, items, _ = MODIFIER_SOURCES[source]
        return sorted(((t, self._name(name, t)) for t, name in self._query(
            'SELECT DISTINCT i.{0}, i.Name FROM "{1}" l JOIN "{2}" i '
            'ON i.{0} = l.{0}'.format(column, table, items))),
            key=lambda c: (c[1].lower(), c[0]))

    def game_modifiers(self, source, item):
        """The game's modifiers of an item of a MODIFIER_SOURCES kind:
        [{"id", "modifier_type", "args" {name: value}, "run_once",
        "permanent", "arg_types" {name: {"Type", "Extra", "SecondExtra"}}
        and "columns" {column: value} (both only where not the default),
        "strings" {context: text}, "subject_reqs" and "owner_reqs"
        ([{"type", "args", "inverse", "columns"}]), "set_types"
        {"subject_reqs" / "owner_reqs": RequirementSetType}}]."""
        if source not in MODIFIER_SOURCES or not self.conn:
            return []
        table, column = MODIFIER_SOURCES[source][:2]
        out = []
        for (mod_id,) in self._query(
                'SELECT ModifierId FROM "{}" WHERE {} = ? ORDER BY rowid'
                .format(table, column), (item,)):
            mod = self.read_modifier(mod_id)
            if mod:
                out.append(mod)
        return out

    def _row(self, sql, args=()):
        """The first row as {column: value}, or None."""
        try:
            cur = self.conn.execute(sql, args)
        except sqlite3.Error:
            return None
        row = cur.fetchone()
        return dict(zip([d[0] for d in cur.description], row)) if row \
            else None

    def read_modifier(self, mod_id):
        """One of the game's modifiers, as game_modifiers gives them, or
        None."""
        if not self.conn:
            return None
        row = self._row("SELECT * FROM Modifiers WHERE ModifierId = ?",
                        (mod_id,))
        if not row:
            return None
        mod = {"id": mod_id, "modifier_type": row["ModifierType"],
               "run_once": bool(row.get("RunOnce")),
               "permanent": bool(row.get("Permanent")),
               "args": {}, "arg_types": {}, "strings": {}, "set_types": {},
               "columns": {c: row[c] for c, default in
                           MODIFIER_COLUMNS.items()
                           if row.get(c, default) != default}}
        for name, value, arg_type, extra, second in self._query(
                "SELECT Name, Value, Type, Extra, SecondExtra FROM "
                "ModifierArguments WHERE ModifierId = ? ORDER BY rowid",
                (mod_id,)):
            mod["args"][name] = "" if value is None else str(value)
            if arg_type not in (None, "ARGTYPE_IDENTITY") or \
                    extra is not None or second is not None:
                mod["arg_types"][name] = {"Type": arg_type or
                                          "ARGTYPE_IDENTITY",
                                          "Extra": extra,
                                          "SecondExtra": second}
        mod["strings"] = dict(self._query(
            "SELECT Context, Text FROM ModifierStrings WHERE ModifierId = ?",
            (mod_id,)))
        for key, set_id in (("subject_reqs",
                             row.get("SubjectRequirementSetId")),
                            ("owner_reqs", row.get("OwnerRequirementSetId"))):
            mod[key] = []
            if not set_id:
                continue
            set_type = self._query(
                "SELECT RequirementSetType FROM RequirementSets WHERE "
                "RequirementSetId = ?", (set_id,))
            mod["set_types"][key] = set_type[0][0] if set_type else None
            for (req_id,) in self._query(
                    "SELECT RequirementId FROM RequirementSetRequirements "
                    "WHERE RequirementSetId = ? ORDER BY rowid", (set_id,)):
                req = self._row("SELECT * FROM Requirements WHERE "
                                "RequirementId = ?", (req_id,))
                if not req:
                    continue
                mod[key].append({
                    "type": req["RequirementType"],
                    "inverse": bool(req.get("Inverse")),
                    "columns": {c: req[c] for c, default in
                                REQUIREMENT_COLUMNS.items()
                                if req.get(c, default) != default},
                    "args": {n: "" if v is None else str(v)
                             for n, v in self._query(
                                 "SELECT Name, Value FROM "
                                 "RequirementArguments WHERE "
                                 "RequirementId = ?", (req_id,))}})
        return mod

    # -- the game's modifier and requirement types (advanced effects) ---

    def modifier_types(self):
        """The game's modifier types, sorted ([] without the cache)."""
        return sorted(self.modifier_schema)

    def modifier_info(self, modifier_type):
        """{"collection", "effect", "uses", "args"} of a modifier type
        (see modifier_schema), or None."""
        return self.modifier_schema.get(modifier_type)

    def modifier_args(self, modifier_type):
        """[(name, uses, example, numeric)] the game's own modifiers of
        a type give it, the most used first."""
        return (self.modifier_schema.get(modifier_type) or {}).get(
            "args") or []

    def requirement_types(self):
        return sorted(self.requirement_schema)

    def requirement_info(self, requirement_type):
        """{"uses", "args"} of a requirement type, or None."""
        return self.requirement_schema.get(requirement_type)

    def requirement_args(self, requirement_type):
        return (self.requirement_schema.get(requirement_type) or {}).get(
            "args") or []

    def agenda_examples(self):
        """How the game's agendas use each condition in their likes and
        dislikes (see agendas.py): {requirement type: [{"value", "args",
        "not", "text"}]} ({} without the cache)."""
        if self._agenda_examples is None and self.conn:
            from .agendas import SIMPLE_MODIFIER, STANDARD_REQS
            standard = {r["type"] for r in STANDARD_REQS}
            found = {}
            for mod_id, req_id, req_type, inverse in self._query(
                    "SELECT m.ModifierId, r.RequirementId, "
                    "r.RequirementType, r.Inverse FROM AgendaTraits a "
                    "JOIN TraitModifiers t USING (TraitType) JOIN Modifiers "
                    "m USING (ModifierId) JOIN RequirementSetRequirements s "
                    "ON s.RequirementSetId = m.SubjectRequirementSetId JOIN "
                    "Requirements r USING (RequirementId) WHERE "
                    "m.ModifierType = ? ORDER BY m.rowid",
                    (SIMPLE_MODIFIER,)):
                if req_type in standard:
                    continue
                args = dict(self._query(
                    "SELECT Name, Value FROM ModifierArguments WHERE "
                    "ModifierId = ?", (mod_id,)))
                tag = args.get("SimpleModifierDescription")
                found.setdefault(req_type, []).append({
                    "value": args.get("InitialValue", ""),
                    "args": dict(self._query(
                        "SELECT Name, Value FROM RequirementArguments "
                        "WHERE RequirementId = ?", (req_id,))),
                    "not": bool(inverse),
                    "text": (self.loc_text(tag) or self._loc(tag) or "")
                    if tag else ""})
            self._agenda_examples = found
        return self._agenda_examples or {}

    def is_attach(self, modifier_type):
        """Whether a modifier type attaches another modifier (named by its
        ModifierId argument)."""
        info = self.modifier_schema.get(modifier_type)
        if info:
            return info["effect"].startswith("EFFECT_ATTACH")
        return "ATTACH" in modifier_type        # (not known: a guess)

    # (without the cache, anything may be the game's)
    def has_modifier_type(self, modifier_type):
        return not self.modifier_schema or \
            modifier_type in self.modifier_schema

    def has_requirement_type(self, requirement_type):
        return not self.requirement_schema or \
            requirement_type in self.requirement_schema

    def has_modifier(self, mod_id):
        return not self.modifier_ids or mod_id in self.modifier_ids

    def has_requirement_set(self, set_id):
        return not self.requirement_set_ids or \
            set_id in self.requirement_set_ids

    def leader_unique_items(self, leader):
        """Unique items a leader's own traits unlock (e.g. a leader's
        unique unit), in PlayerItems order: [type]."""
        if not self.conn:
            return []
        items = []
        for table, column in (("Units", "UnitType"),
                              ("Buildings", "BuildingType"),
                              ("Districts", "DistrictType"),
                              ("Improvements", "ImprovementType")):
            items += [r[0] for r in self._query(
                "SELECT {} FROM {} WHERE TraitType IN (SELECT TraitType "
                "FROM LeaderTraits WHERE LeaderType=?) ORDER BY 1".format(
                    column, table), (leader,))]
        return items

    def all_abilities(self):
        """Every civilization and leader ability the game defines, to copy
        into a new ability: [(owner type, ability dict)]."""
        out = [(civ, a) for civ, abilities in sorted(
            self.civ_abilities.items()) for a in abilities]
        out += [(leader, a) for leader, abilities in sorted(
            self.leader_abilities.items()) for a in abilities]
        return out

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


# Tables of rules a trait sets besides its modifiers: {table: the other
# key column}. A renamed ability copies their rows.
TRAIT_RULE_TABLES = {
    "ExcludedAdjacencies": "YieldChangeId",
    "ExcludedDistricts": "DistrictType",
    "ExcludedGreatPersonClasses": "GreatPersonClassType",
}
