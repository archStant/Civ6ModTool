"""Tests: generate mods without the GUI and run their SQL against copies of
the game's own databases (the debug caches the game writes), so every
table, column and foreign key the mod uses is checked against the real
schema.

    python -m unittest discover -s tests -t .

Tests needing the game cache (DebugGameplay.sqlite) or install are
skipped when it is missing.
"""

import os
import shutil
import sqlite3
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zlib

from civgen import (civs, landmarks, leaders, modbuild, modifiers,
                    moments, project, unit_art, unit_models, uniques)
from civgen.gamedata import GameData
from civgen.util import find_game_cache, find_game_dir

CACHE = find_game_cache()
MOMENT_IMAGE = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "assets", "icon.png")
GAME_DIR = find_game_dir()
DATA = None


def game_data():
    global DATA
    if DATA is None:
        DATA = GameData()
        DATA.load(CACHE)
    return DATA


def database(name, tmp):
    """A copy of one of the game's debug databases, with foreign keys on
    and the game's Make_Hash function (used by its triggers)."""
    path = os.path.join(tmp, name)
    shutil.copy(os.path.join(os.path.dirname(CACHE), name), path)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.create_function("Make_Hash", 1,
                         lambda s: zlib.crc32(s.encode()) - (1 << 31))
    return conn


def read(mod_dir, rel):
    with open(os.path.join(mod_dir, *rel.split("/")), encoding="utf-8") as fh:
        return fh.read()


def designed_models():
    """A foot design (Swordsman with a spear, a civ-colored Knight shield,
    no hat and a cape) and a mounted one (Swordsman on the Knight's
    horse)."""
    foot = unit_models.model_sections(GAME_DIR, "Swordsman")["body"]
    for part in foot:
        if part["slot"] == "Weapon":
            part["bins"] = ["Spears/Hoplite"]
        if part["slot"] == "Shield":
            part.update(bins=["Shields/Knight"],
                        tint=unit_models.CIV_COLOR)
    foot = [p for p in foot if p["slot"] != "Hats"]
    foot.append({"slot": "Cape", "point": "Root", "tint": "",
                 "bins": ["Capes/Swordsman"]})
    mounted = unit_models.model_sections(GAME_DIR, "Swordsman", "Knight")
    for part in mounted["horse"]:
        if part["slot"] == "Armor":
            part["bins"] = ["Armor_Horse/Mamluk"]
    return [{"id": "Spearwoman", "template": "Swordsman", "mount": "",
             "parts": {"body": foot}},
            {"id": "RIDER", "template": "Swordsman", "mount": "Knight",
             "parts": mounted}]


def sample_project():
    """(leader specs, civ specs) using every feature that needs no art."""
    alt = leaders.new_leader_spec()
    alt.update(name="Jeanne", civ="CIVILIZATION_FRANCE",
               orig="LEADER_CATHERINE_DE_MEDICI", city_names=["Orleans"])

    civ = civs.new_civ_spec()
    civ.update(name="Amazons", adjective="Amazonian",
               city_names=["Themiscyra", "Lykastia", "Chadesia"],
               music_from="CIVILIZATION_INCA", icon_from="CIVILIZATION_INCA",
               culture="SouthAmerican", unit_culture="SouthAmerican")
    civ["citizen_names"]["female"] = ["Hippolyta", "Penthesilea"]
    civ["start_bias"].update(feature={"FEATURE_JUNGLE": 2}, river=3)
    civ["pedia"].update(history="First.\n\nSecond.", location="Pontus")
    yields = modifiers.new_effect("city_yield")
    combat = modifiers.new_effect("combat_strength")
    combat["reqs"] = [{"preset": "unit_class",
                       "value": "PROMOTION_CLASS_MELEE"},
                      {"preset": "attacking"}]
    adjacency = modifiers.new_effect("feature_adjacency")
    adjacency["args"].update(DistrictType="DISTRICT_CAMPUS",
                             FeatureType="FEATURE_JUNGLE",
                             YieldType="YIELD_SCIENCE")
    adjacency["reqs"] = [{"preset": "has_tech", "value": "TECH_WRITING",
                          "not": True}]
    civ["ability"].update(name="Daughters of Ares", desc="Strong.",
                          clone=["TRAIT_CIVILIZATION_FIRST_CIVILIZATION"],
                          effects=[yields, combat, adjacency])
    unit = uniques.new_unique_spec("unit")
    unit.update(base="UNIT_SWORDSMAN", name="Amazon Warrior",
                stats={"Combat": "40", "BaseMoves": "3",
                       "PrereqTech": "None"},
                effects=[modifiers.new_effect("movement"),
                         modifiers.new_effect("combat_strength")],
                art={"look_from": "UNIT_ROMAN_LEGION",
                     "members": [{"type": "RomanLegion", "count": 3,
                                  "scale": 1.1},
                                 {"type": "Swordsman", "count": "1",
                                  "scale": "0.9"}],
                     "formation": "Swordsman", "combat": "",
                     "sound_from": "UNIT_KNIGHT"})
    if GAME_DIR:
        unit["art"]["models"] = designed_models()
        unit["art"]["members"] += [
            {"type": "@SPEARWOMAN", "count": 2, "scale": 1},
            {"type": "@RIDER", "count": 1, "scale": 1}]
    building = uniques.new_unique_spec("building")
    building.update(base="BUILDING_TEMPLE", name="Temple of Ares",
                    desc="A temple.", pedia="Built for war.",
                    yields={"YIELD_FAITH": "4"},
                    gpp={"GREAT_PERSON_CLASS_PROPHET": "2"},
                    effects=[modifiers.new_effect("free_unit")])
    district = uniques.new_unique_spec("district")
    district.update(base="DISTRICT_HANSA", name="Amazon Forge",
                    stats={"Cost": "30"})
    # own meshes: the temple looks like a University; the forge's empty
    # ground and its Workshop look different
    building["art"] = {"look_from": "", "meshes": [
        {"era": "DEFAULT", "mesh": "DIS_CMP_University"}]}
    district["art"] = {"ground": {"EMPTY|DEFAULT|DEFAULT|ANY":
                                  "DIS_CMP_Ancient_Base_01"},
                       "buildings": {"BUILDING_WORKSHOP": "DIS_CMP_Library"}}
    # new (not copied) items: a district laid out like a Theater Square,
    # a building in it, and an extra building in the game's Campus
    arena = uniques.new_unique_spec("district")
    arena.update(name="Amazon Arena", base="", replaces="",
                 stats={"Cost": "60"},
                 art={"look_from": "DISTRICT_THEATER"},
                 placement={"water": False,
                            "terrains": ["TERRAIN_GRASS_HILLS",
                                         "TERRAIN_PLAINS_HILLS"],
                            "features": ["FEATURE_FOREST", "FEATURE_JUNGLE"],
                            "no_adjacent_city": True, "one_per_city": True,
                            "max_per_player": "2"})
    hall = uniques.new_unique_spec("building")
    hall.update(name="Hall of Heroines", base="", replaces="",
                stats={"PrereqDistrict": "DISTRICT_TST_AMAZON_ARENA",
                       "Cost": "150"},
                yields={"YIELD_CULTURE": "3"},
                art={"look_from": "BUILDING_AMPHITHEATER"})
    academy = uniques.new_unique_spec("building")
    academy.update(name="War Academy", base="", replaces="",
                   stats={"PrereqDistrict": "DISTRICT_CAMPUS"})
    # improvements: a copy of the Chateau, and a new one in the woods
    lodge = uniques.new_unique_spec("improvement")
    lodge.update(name="Hunting Lodge", base="IMPROVEMENT_CHATEAU",
                 stats={"Housing": "1", "PrereqCivic": "None"},
                 yields={"YIELD_FOOD": "1", "YIELD_FAITH": "2"},
                 adjacencies=False)
    grove = uniques.new_unique_spec("improvement")
    grove.update(name="Sacred Grove", base="",
                 art={"look_from": "IMPROVEMENT_PAIRIDAEZA"},
                 stats={"PrereqTech": "TECH_ASTROLOGY", "Appeal": "1"},
                 yields={"YIELD_FAITH": "2"},
                 placement={"terrains": ["TERRAIN_GRASS", "TERRAIN_PLAINS"],
                            "features": ["FEATURE_FOREST", "FEATURE_JUNGLE"],
                            "no_same_adjacent": True},
                 effects=[modifiers.new_effect("tourism")])
    civ["uniques"] = [unit, building, district, arena, hall, academy, lodge,
                      grove]

    queen = leaders.new_leader_spec()
    queen.update(name="Hippolyta", civ="CIVILIZATION_TST_AMAZONS",
                 orig="LEADER_GILGAMESH",
                 new_ability={"name": "Girdle of Ares", "replace": True,
                              "effects": [modifiers.new_effect("tourism")]})
    second = leaders.new_leader_spec()
    second.update(name="Penthesilea", civ="CIVILIZATION_TST_AMAZONS",
                  orig="LEADER_TRAJAN", city_names=["Troy"])
    # leaders that inherit from nobody, of the new and of a game civ
    third = leaders.new_leader_spec()
    third.update(name="Antiope", civ="CIVILIZATION_TST_AMAZONS", orig="",
                 agenda="AGENDA_IRON_CROWN", agenda_name="Amazon Pride",
                 ai_traits=["TRAIT_LEADER_AGGRESSIVE_MILITARY"],
                 new_ability={"name": "Queen of the Hunt", "effects": [
                     modifiers.new_effect("tourism")]})
    fourth = leaders.new_leader_spec()
    fourth.update(name="Liberty", civ="CIVILIZATION_AMERICA", orig="",
                  agenda="AGENDA_BIG_STICK_POLICY",
                  scene_leader="LEADER_T_ROOSEVELT",
                  ai_traits=leaders.DEFAULT_AI_TRAITS,
                  new_ability={"name": "Torch of Freedom"})
    return [alt, queen, second, third, fourth], [civ]


@unittest.skipUnless(CACHE and GAME_DIR, "needs the game and its cache")
class GeneratedModTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="civgen_test_")
        cls.mod_dir = os.path.join(cls.tmp, "TestMod")
        for sub in ("Config", "Gameplay", "Text"):
            os.makedirs(os.path.join(cls.mod_dir, sub))
        leader_specs, civ_specs = sample_project()
        cls.civs, cls.ctxs, errors = modbuild.prepare_project(
            leader_specs, civ_specs, game_data(), "TST")
        assert not errors, errors
        cls.report = []
        modbuild.write_mod("Test Mod", cls.ctxs, "TestMod", cls.mod_dir,
                           "guid", None, cls.report, lambda text: None,
                           cls.civs, game_data().type_name)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_gameplay_sql_runs(self):
        db = database("DebugGameplay.sqlite", self.tmp)
        self.addCleanup(db.close)
        db.executescript(read(self.mod_dir, "Gameplay/NewLeader_Gameplay.sql"))
        db.executescript(read(self.mod_dir, modbuild.XP2_FILE))
        self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
        q = lambda sql: db.execute(sql).fetchall()    # noqa: E731
        self.assertEqual(q("SELECT StartingCivilizationLevelType FROM "
                           "Civilizations WHERE CivilizationType = "
                           "'CIVILIZATION_TST_AMAZONS'"),
                         [("CIVILIZATION_LEVEL_FULL_CIV",)])
        self.assertEqual(len(q("SELECT * FROM CivilizationLeaders WHERE "
                               "CivilizationType = "
                               "'CIVILIZATION_TST_AMAZONS'")), 3)
        self.assertEqual(q("SELECT Combat, BaseMoves, PrereqTech FROM Units "
                           "WHERE UnitType = 'UNIT_TST_AMAZON_WARRIOR'"),
                         [(40, 3, None)])     # Swordsman: Iron Working
        self.assertIn(("CLASS_MELEE",), q(
            "SELECT Tag FROM TypeTags WHERE Type = 'UNIT_TST_AMAZON_WARRIOR'"))
        self.assertEqual(len(q("SELECT * FROM Units_XP2 WHERE UnitType = "
                               "'UNIT_TST_AMAZON_WARRIOR'")), 1)
        self.assertEqual(q("SELECT ReplacesDistrictType FROM DistrictReplaces "
                           "WHERE CivUniqueDistrictType = "
                           "'DISTRICT_TST_AMAZON_FORGE'"),
                         [("DISTRICT_INDUSTRIAL_ZONE",)])
        self.assertEqual(q("SELECT YieldType, YieldChange FROM "
                           "Building_YieldChanges WHERE BuildingType = "
                           "'BUILDING_TST_TEMPLE_OF_ARES'"),
                         [("YIELD_FAITH", 4)])
        # new items: their own rows, built where chosen, replacing nothing
        self.assertEqual(q("SELECT PrereqDistrict, Cost, TraitType FROM "
                           "Buildings WHERE BuildingType = "
                           "'BUILDING_TST_HALL_OF_HEROINES'"),
                         [("DISTRICT_TST_AMAZON_ARENA", 150,
                           "TRAIT_CIVILIZATION_BUILDING_TST_HALL_OF_"
                           "HEROINES")])
        self.assertEqual(q("SELECT Cost, RequiresPlacement, PlunderType, "
                           "Coast, NoAdjacentCity, OnePerCity, MaxPerPlayer "
                           "FROM Districts WHERE DistrictType = "
                           "'DISTRICT_TST_AMAZON_ARENA'"),
                         [(60, 1, "NO_PLUNDER", 0, 1, 1, 2)])
        self.assertEqual(q("SELECT TerrainType FROM District_ValidTerrains "
                           "WHERE DistrictType = 'DISTRICT_TST_AMAZON_ARENA' "
                           "ORDER BY 1"),
                         [("TERRAIN_GRASS_HILLS",), ("TERRAIN_PLAINS_HILLS",)])
        self.assertEqual(q("SELECT FeatureType FROM District_RequiredFeatures "
                           "WHERE DistrictType = 'DISTRICT_TST_AMAZON_ARENA' "
                           "ORDER BY 1"),
                         [("FEATURE_FOREST",), ("FEATURE_JUNGLE",)])
        # a copied district without own rules keeps the copied ones (and a
        # new one may be next to the city center unless told otherwise)
        self.assertEqual(q("SELECT NoAdjacentCity, OnePerCity FROM Districts "
                           "WHERE DistrictType = "
                           "'DISTRICT_TST_AMAZON_FORGE'"), [(0, 1)])
        self.assertEqual(q("SELECT * FROM BuildingReplaces WHERE "
                           "CivUniqueBuildingType LIKE '%WAR_ACADEMY' OR "
                           "CivUniqueBuildingType LIKE '%HEROINES'"), [])
        self.assertEqual(q("SELECT * FROM DistrictReplaces WHERE "
                           "CivUniqueDistrictType LIKE '%ARENA'"), [])
        self.assertEqual(q("SELECT YieldType, YieldChange FROM "
                           "Building_YieldChanges WHERE BuildingType = "
                           "'BUILDING_TST_HALL_OF_HEROINES'"),
                         [("YIELD_CULTURE", 3)])
        # improvements
        self.assertEqual(q("SELECT Icon, TraitType, Housing, PrereqCivic, "
                           "Buildable FROM Improvements WHERE "
                           "ImprovementType = 'IMPROVEMENT_TST_HUNTING_LODGE'"),
                         [("ICON_IMPROVEMENT_TST_HUNTING_LODGE",
                           "TRAIT_CIVILIZATION_IMPROVEMENT_TST_HUNTING_LODGE",
                           1, None, 1)])
        self.assertEqual(q("SELECT YieldType, YieldChange FROM "
                           "Improvement_YieldChanges WHERE ImprovementType = "
                           "'IMPROVEMENT_TST_HUNTING_LODGE' ORDER BY 1"),
                         [("YIELD_FAITH", 2), ("YIELD_FOOD", 1)])
        self.assertEqual(q("SELECT * FROM Improvement_Adjacencies WHERE "
                           "ImprovementType = "
                           "'IMPROVEMENT_TST_HUNTING_LODGE'"), [])
        # (the Chateau's placement rules are copied)
        self.assertEqual(
            q("SELECT COUNT(*) FROM Improvement_ValidTerrains WHERE "
              "ImprovementType = 'IMPROVEMENT_TST_HUNTING_LODGE'"),
            q("SELECT COUNT(*) FROM Improvement_ValidTerrains WHERE "
              "ImprovementType = 'IMPROVEMENT_CHATEAU'"))
        grove = "'IMPROVEMENT_TST_SACRED_GROVE'"
        self.assertEqual(q("SELECT PrereqTech, Appeal, SameAdjacentValid, "
                           "Domain, PlunderType FROM Improvements WHERE "
                           "ImprovementType = " + grove),
                         [("TECH_ASTROLOGY", 1, 0, "DOMAIN_LAND",
                           "PLUNDER_HEAL")])
        self.assertEqual(q("SELECT UnitType FROM Improvement_ValidBuildUnits "
                           "WHERE ImprovementType = " + grove),
                         [("UNIT_BUILDER",)])
        self.assertEqual(q("SELECT FeatureType FROM Improvement_ValidFeatures "
                           "WHERE ImprovementType = " + grove + " ORDER BY 1"),
                         [("FEATURE_FOREST",), ("FEATURE_JUNGLE",)])
        self.assertEqual(len(q("SELECT * FROM ImprovementModifiers WHERE "
                               "ImprovementType = " + grove)), 1)
        self.assertIn(("TRAIT_CIVILIZATION_IMPROVEMENT_TST_SACRED_GROVE",),
                      q("SELECT TraitType FROM CivilizationTraits WHERE "
                        "CivilizationType = 'CIVILIZATION_TST_AMAZONS'"))
        # the new leader ability replaced Gilgamesh's ability
        traits = {t for (t,) in q("SELECT TraitType FROM LeaderTraits WHERE "
                                  "LeaderType = 'LEADER_TST_HIPPOLYTA'")}
        self.assertIn("TRAIT_LEADER_TST_HIPPOLYTA", traits)
        for a in game_data().abilities("LEADER_GILGAMESH"):
            self.assertNotIn(a["type"], traits)
        # leaders that inherit from nobody
        self.assertEqual(q("SELECT InheritFrom, SceneLayers FROM Leaders "
                           "WHERE LeaderType = 'LEADER_TST_ANTIOPE'"),
                         [("LEADER_DEFAULT", 0)])
        self.assertEqual(
            {t for (t,) in q("SELECT TraitType FROM LeaderTraits WHERE "
                             "LeaderType = 'LEADER_TST_ANTIOPE'")},
            {"TRAIT_LEADER_TST_ANTIOPE", "TRAIT_LEADER_AGGRESSIVE_MILITARY"})
        self.assertEqual(q("SELECT AgendaType FROM HistoricalAgendas WHERE "
                           "LeaderType = 'LEADER_TST_ANTIOPE'"),
                         [("AGENDA_TST_ANTIOPE",)])
        self.assertEqual(q("SELECT CapitalName FROM CivilizationLeaders "
                           "WHERE LeaderType = 'LEADER_TST_ANTIOPE'"),
                         [("LOC_CITY_NAME_CIVILIZATION_TST_AMAZONS_1",)])
        self.assertEqual(q("SELECT CapitalName FROM CivilizationLeaders "
                           "WHERE LeaderType = 'LEADER_TST_LIBERTY'"),
                         [("LOC_CITY_NAME_WASHINGTON",)])
        self.assertEqual(q("SELECT AgendaType FROM HistoricalAgendas WHERE "
                           "LeaderType = 'LEADER_TST_LIBERTY'"),
                         [("AGENDA_BIG_STICK_POLICY",)])
        self.assertEqual(q("SELECT PlayDawnOfManAudio, LeaderText FROM "
                           "LoadingInfo WHERE LeaderType = "
                           "'LEADER_TST_LIBERTY'"),
                         [(0, "LOC_LOADING_INFO_LEADER_TST_LIBERTY")])
        self.assertEqual(q("SELECT SceneLeaderType FROM AltLeaderScenes "
                           "WHERE LeaderType = 'LEADER_TST_LIBERTY'"),
                         [("LEADER_T_ROOSEVELT",)])
        self.assertEqual(q("SELECT * FROM AltLeaderScenes WHERE LeaderType "
                           "= 'LEADER_TST_ANTIOPE'"), [])

    def test_config_sql_runs(self):
        db = database("DebugConfiguration.sqlite", self.tmp)
        self.addCleanup(db.close)
        db.executescript(read(self.mod_dir, "Config/NewLeader_Config.sql"))
        self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
        domains = {d for (d,) in db.execute(
            "SELECT Domain FROM Players WHERE LeaderType = "
            "'LEADER_TST_HIPPOLYTA'")}
        self.assertEqual(domains, set(civs.STANDARD_DOMAINS))
        items = db.execute(
            "SELECT Type FROM PlayerItems WHERE LeaderType = "
            "'LEADER_TST_HIPPOLYTA' AND Domain = 'Players:Expansion2_Players' "
            "ORDER BY SortIndex").fetchall()
        self.assertEqual([t for (t,) in items],
                         ["UNIT_TST_AMAZON_WARRIOR",
                          "BUILDING_TST_TEMPLE_OF_ARES",
                          "DISTRICT_TST_AMAZON_FORGE",
                          "DISTRICT_TST_AMAZON_ARENA",
                          "BUILDING_TST_HALL_OF_HEROINES",
                          "BUILDING_TST_WAR_ACADEMY",
                          "IMPROVEMENT_TST_HUNTING_LODGE",
                          "IMPROVEMENT_TST_SACRED_GROVE"])
        # leaders that inherit from nobody: every ruleset; a game civ's
        # own items, not those of its leaders (the Rough Rider)
        for leader in ("LEADER_TST_ANTIOPE", "LEADER_TST_LIBERTY"):
            self.assertEqual({d for (d,) in db.execute(
                "SELECT Domain FROM Players WHERE LeaderType = ?",
                (leader,))}, set(civs.STANDARD_DOMAINS))
        self.assertEqual(db.execute(
            "SELECT CivilizationName, LeaderIcon, LeaderAbilityName FROM "
            "Players WHERE LeaderType = 'LEADER_TST_LIBERTY' AND Domain = "
            "'Players:Expansion2_Players'").fetchall(),
            [("LOC_CIVILIZATION_AMERICA_NAME", "ICON_LEADER_DEFAULT",
              "LOC_TRAIT_LEADER_TST_LIBERTY_NAME")])
        self.assertEqual(sorted(t for (t,) in db.execute(
            "SELECT Type FROM PlayerItems WHERE LeaderType = "
            "'LEADER_TST_LIBERTY' AND Domain = 'Players:Expansion2_Players'")),
            ["BUILDING_FILM_STUDIO", "UNIT_AMERICAN_P51"])
        self.assertEqual(len(db.execute(
            "SELECT * FROM PlayerItems WHERE LeaderType = "
            "'LEADER_TST_ANTIOPE' AND Domain = 'Players:Expansion2_Players'")
            .fetchall()), 8)
        # the alternate leader of a game civilization is unchanged
        self.assertTrue(db.execute(
            "SELECT 1 FROM Players WHERE LeaderType = 'LEADER_TST_JEANNE' AND "
            "CivilizationType = 'CIVILIZATION_FRANCE'").fetchall())

    def test_text_sql_runs(self):
        db = sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        db.execute("CREATE TABLE LocalizedText (Language TEXT NOT NULL, "
                   "Tag TEXT NOT NULL, Text TEXT, Gender TEXT, "
                   "Plurality TEXT, PRIMARY KEY (Language, Tag))")
        db.executescript(read(self.mod_dir, "Text/NewLeader_Text.sql"))
        tags = {t for (t,) in db.execute("SELECT Tag FROM LocalizedText")}
        for tag in ("LOC_CIVILIZATION_TST_AMAZONS_NAME",
                    "LOC_TRAIT_CIVILIZATION_TST_AMAZONS_NAME",
                    "LOC_UNIT_TST_AMAZON_WARRIOR_NAME",
                    "LOC_PEDIA_BUILDINGS_PAGE_BUILDING_TST_TEMPLE_OF_ARES_"
                    "CHAPTER_HISTORY_PARA_1",
                    "LOC_TRAIT_LEADER_TST_HIPPOLYTA_DESCRIPTION",
                    "LOC_CITY_NAME_CIVILIZATION_TST_AMAZONS_1"):
            self.assertIn(tag, tags)

    def test_every_text_tag_used_is_defined(self):
        """Every LOC_ tag of the new civilization's rows has text (in this
        mod or the game)."""
        text = read(self.mod_dir, "Text/NewLeader_Text.sql")
        gameplay = read(self.mod_dir, "Gameplay/NewLeader_Gameplay.sql")
        import re
        used = set(re.findall(r"'(LOC_[A-Z0-9_]*TST[A-Z0-9_]*)'", gameplay))
        missing = [t for t in used if "'{}'".format(t) not in text]
        self.assertEqual(missing, [])

    def test_icons_sql_runs(self):
        db = sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        with open(os.path.join(GAME_DIR, "Base", "Assets", "Database",
                               "IconManager.sql"), encoding="utf-8") as fh:
            db.executescript(fh.read())
        db.executescript(
            "INSERT INTO IconTextureAtlases (Name, IconSize, FileName) VALUES "
            "('ICON_ATLAS_UNITS', 32, 'x'), ('ICON_ATLAS_CIVILIZATION_INCA', "
            "32, 'x'); INSERT INTO IconDefinitions (Name, Atlas, \"Index\") "
            "VALUES ('ICON_UNIT_ROMAN_LEGION', 'ICON_ATLAS_UNITS', 34), "
            "('ICON_IMPROVEMENT_PAIRIDAEZA', 'ICON_ATLAS_UNITS', 7), "
            "('ICON_CIVILIZATION_INCA', 'ICON_ATLAS_CIVILIZATION_INCA', 0);")
        db.executescript(read(self.mod_dir, modbuild.ICONS_SQL_FILE))
        self.assertEqual(db.execute(
            "SELECT Atlas, \"Index\" FROM IconDefinitions WHERE Name = "
            "'ICON_UNIT_TST_AMAZON_WARRIOR'").fetchall(),
            [("ICON_ATLAS_UNITS", 34)])
        self.assertEqual(db.execute(
            "SELECT Atlas FROM IconDefinitions WHERE Name = "
            "'ICON_CIVILIZATION_TST_AMAZONS'").fetchall(),
            [("ICON_ATLAS_CIVILIZATION_INCA",)])
        self.assertEqual(db.execute(
            "SELECT \"Index\" FROM IconDefinitions WHERE Name = "
            "'ICON_IMPROVEMENT_TST_SACRED_GROVE'").fetchall(), [(7,)])

    def test_xml_files_parse(self):
        files = ["MyLeader.modinfo", "TestMod.dep",
                 "Config/NewLeader_Colors.xml"]
        files += ["ArtDefs/" + f for f in os.listdir(
            os.path.join(self.mod_dir, "ArtDefs"))]
        for rel in files:
            ET.fromstring(read(self.mod_dir, rel).encode("utf-8"))
        modinfo = ET.fromstring(read(self.mod_dir, "MyLeader.modinfo"))
        listed = {f.text for f in modinfo.iter("File")}
        for rel in files[1:] + [modbuild.XP2_FILE, modbuild.ICONS_SQL_FILE]:
            self.assertIn(rel, listed)
        ids = [a.get("id") for actions in modinfo
               if actions.tag.endswith("Actions") for a in actions]
        self.assertEqual(len(ids), len(set(ids)), "action ids must be unique")

    def test_unique_art_is_copied(self):
        self.assertEqual(
            sorted(os.listdir(os.path.join(self.mod_dir, "ArtDefs"))),
            ["Buildings.artdef", "Civilizations.artdef", "Cultures.artdef",
             "Districts.artdef", "Improvements.artdef", "Landmarks.artdef",
             "Units.artdef"])
        improvements = read(self.mod_dir, "ArtDefs/Improvements.artdef")
        self.assertIn('<m_CollectionName text="Improvement"/>', improvements)
        for name in ("IMPROVEMENT_TST_HUNTING_LODGE",
                     "IMPROVEMENT_TST_SACRED_GROVE"):
            self.assertIn('<m_Name text="{}" />'.format(name), improvements)
        # the new one is drawn like the Pairidaeza
        self.assertIn('text="LM_PAIRIDAEZA"', improvements)
        dep = read(self.mod_dir, "TestMod.dep")
        self.assertIn('<ConsumerName text="Improvements"/>', dep)
        units = read(self.mod_dir, "ArtDefs/Units.artdef")
        self.assertIn('text="UNIT_TST_AMAZON_WARRIOR"', units)
        self.assertNotIn('<m_Name text="UNIT_SWORDSMAN"', units)
        self.assertEqual([r for r in self.report if r.startswith("WARNING")],
                         [])

    def test_unit_3d_model(self):
        root = ET.fromstring(read(self.mod_dir, "ArtDefs/Units.artdef"))
        unit = next(e for e in root.iter("Element")
                    if e.find("m_Name") is not None and
                    e.find("m_Name").get("text") == "UNIT_TST_AMAZON_WARRIOR")
        members = [(m.find(".//m_ElementName").get("text"),
                    m.find(".//m_nValue").text, m.find(".//m_fValue").text)
                   for c in unit.findall("./m_ChildCollections/Element")
                   if c.find("m_CollectionName").get("text") == "Members"
                   for m in c.findall("Element")]
        self.assertEqual(members, [
            ("RomanLegion", "3", "1.100000"), ("Swordsman", "1", "0.900000"),
            ("UNIT_TST_AMAZON_WARRIOR_SPEARWOMAN", "2", "1.000000"),
            ("UNIT_TST_AMAZON_WARRIOR_RIDER", "1", "1.000000")])
        fields = {v.find("m_ParamName").get("text"):
                  v.find("m_ElementName").get("text")
                  for v in unit.findall("./m_Fields/m_Values/Element")
                  if v.find("m_ElementName") is not None}
        self.assertEqual(fields["Formation"], "Swordsman")
        self.assertEqual(fields["UnitCombat"], "Archer")  # the Legion's
        audio = [v.get("text") for v in unit.iter("m_Value")]
        self.assertEqual(audio, ["Knight"])
        # the portrait and icons follow the look: the Legion's
        icons = read(self.mod_dir, modbuild.ICONS_SQL_FILE)
        self.assertIn("REPLACE(Name, 'UNIT_ROMAN_LEGION', "
                      "'UNIT_TST_AMAZON_WARRIOR')", icons)


@unittest.skipUnless(CACHE, "needs the game cache")
class GameDataTest(unittest.TestCase):

    def test_templates_use_game_modifier_types(self):
        db = sqlite3.connect(CACHE)
        self.addCleanup(db.close)
        known = {t for (t,) in db.execute(
            "SELECT ModifierType FROM DynamicModifiers")}
        for t in modifiers.TEMPLATES.values():
            self.assertIn(t.modifier_type, known, t.id)

    def test_requirements_are_game_requirement_types(self):
        db = sqlite3.connect(CACHE)
        self.addCleanup(db.close)
        known = {t for (t,) in db.execute(
            "SELECT DISTINCT RequirementType FROM Requirements")}
        for p in modifiers.REQUIREMENTS.values():
            self.assertIn(p.requirement_type, known, p.id)

    def test_clone_tables_exist(self):
        db = sqlite3.connect(CACHE)
        self.addCleanup(db.close)
        tables = {t for (t,) in db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        for kind, rows in uniques.CLONE_TABLES.items():
            for table, column, _ in rows:
                self.assertIn(table, tables)
                columns = [r[1] for r in db.execute(
                    'PRAGMA table_info("{}")'.format(table))]
                self.assertIn(column, columns, table)


def designed(root, name):
    """{culture: {variation: [part]}} of a designed member type."""
    member = next(e for e in root.iter("Element")
                  if e.find("m_Name") is not None and
                  e.find("m_Name").get("text") == name)
    out = {}
    for cult in unit_models.cultures(member):
        out[unit_models.element_name(cult)] = {
            unit_models.element_name(var): [
                unit_models.part_of(a) for a in unit_models.attachments(var)]
            for _, var in unit_models.variations(member, cult)}
    return out


@unittest.skipUnless(CACHE and GAME_DIR, "needs the game and its cache")
class DesignedModelTest(unittest.TestCase):
    """The designed models of the sample unit (a mod generated like
    GeneratedModTest's)."""

    setUpClass = classmethod(GeneratedModTest.setUpClass.__func__)
    tearDownClass = classmethod(GeneratedModTest.tearDownClass.__func__)

    def setUp(self):
        self.root = ET.fromstring(read(self.mod_dir, "ArtDefs/Units.artdef"))

    def test_foot_model(self):
        model = designed(self.root, "UNIT_TST_AMAZON_WARRIOR_SPEARWOMAN")
        self.assertEqual(sorted(model), ["Any", "NativeAmerican",
                                         "SouthAmerican"])
        for cult, variations in model.items():
            parts = {p["slot"]: p for p in variations["A"]}
            self.assertEqual(parts["Weapon"]["bins"], ["Spears/Hoplite"])
            self.assertEqual(parts["Shield"]["bins"], ["Shields/Knight"])
            self.assertEqual(parts["Shield"]["tint"], unit_models.CIV_COLOR)
            self.assertNotIn("Hats", parts)
            self.assertEqual(parts["Cape"]["bins"], ["Capes/Swordsman"])
            self.assertEqual(parts["Head"]["bins"], ["BaseMale_Heads/Heads"])

    def test_mounted_model(self):
        model = designed(self.root, "UNIT_TST_AMAZON_WARRIOR_RIDER")
        rider = {p["slot"]: p for p in model["Any"]["Rider"]}
        horse = {p["slot"]: p for p in model["Any"]["Horse"]}
        self.assertEqual(rider["Weapon"]["bins"], ["Swords/Swordsman"])
        self.assertIn("Body", rider)            # the foot figure's body
        self.assertEqual(horse["Armor"]["bins"], ["Armor_Horse/Mamluk"])
        self.assertEqual(horse["Rider"]["bins"], ["V:Rider"])
        member = next(e for e in self.root.iter("Element")
                      if e.find("m_Name") is not None and e.find(
                          "m_Name").get("text") ==
                      "UNIT_TST_AMAZON_WARRIOR_RIDER")
        self.assertEqual(unit_models._field_text(member, "Movement"),
                         "Cavalry")

    def test_members_collection_in_artdef(self):
        names = [c.find("m_CollectionName").get("text")
                 for c in self.root.find("m_RootCollections")]
        self.assertEqual(names, ["Units", "UnitMemberTypes"])


@unittest.skipUnless(CACHE and GAME_DIR, "needs the game and its cache")
class LandmarkTest(unittest.TestCase):
    """The building and district looks of the sample (a mod generated
    like GeneratedModTest's)."""

    setUpClass = classmethod(GeneratedModTest.setUpClass.__func__)
    tearDownClass = classmethod(GeneratedModTest.tearDownClass.__func__)

    def setUp(self):
        root = ET.fromstring(read(self.mod_dir, "ArtDefs/Landmarks.artdef"))
        self.landmarks = {}
        for e in root.find("m_RootCollections").find("Element").findall(
                "Element"):
            parts = {c.find("m_CollectionName").get("text"):
                     c.findall("Element")
                     for c in e.findall("./m_ChildCollections/Element")}
            self.landmarks[e.find("m_Name").get("text")] = parts

    def mesh(self, variant):
        return landmarks._text(variant, "Asset")

    def test_temple_joins_the_holy_site(self):
        holy = self.landmarks["DISTRICT_HOLY_SITE"]
        temple = "BUILDING_TST_TEMPLE_OF_ARES"
        variants = holy["BuildingVariants"]
        self.assertEqual([(landmarks._text(v, "Tag_HeroBuilding"),
                           self.mesh(v)) for v in variants],
                         [(temple, "DIS_CMP_University")])
        sets = {landmarks.element_name(s): landmarks.set_buildings(s)
                for s in holy["BuildingSets"]}
        self.assertIn("SHRINE, TEMPLE [{}]".format(temple), sets)
        self.assertEqual(sets["SHRINE, TEMPLE [{}]".format(temple)],
                         ["BUILDING_SHRINE", temple])
        self.assertTrue(all(temple in b for b in sets.values()))
        # every new set has ground meshes
        grounds = {landmarks._text(v, "Set_HeroBuildings")
                   for v in holy["BaseVariants"]}
        self.assertEqual(grounds, set(sets))

    def test_district_has_its_own_landmark(self):
        forge = self.landmarks["DISTRICT_TST_AMAZON_FORGE"]
        hansa = landmarks.merged_landmark(GAME_DIR, "DISTRICT_HANSA")
        self.assertEqual(len(forge["BaseVariants"]), len(hansa["base"]))
        keys = {landmarks.variant_key(v): self.mesh(v)
                for v in forge["BaseVariants"]}
        self.assertEqual(keys["EMPTY|DEFAULT|DEFAULT|ANY"],
                         "DIS_CMP_Ancient_Base_01")
        workshops = [self.mesh(v) for v in forge["BuildingVariants"]
                     if landmarks._text(v, "Tag_HeroBuilding") ==
                     "BUILDING_WORKSHOP"]
        self.assertEqual(set(workshops), {"DIS_CMP_Library"})
        districts = read(self.mod_dir, "ArtDefs/Districts.artdef")
        self.assertIn('<m_ElementName text="DISTRICT_TST_AMAZON_FORGE" />',
                      districts)

    def test_every_set_has_grounds(self):
        """Each building set of the civilization's own landmarks has
        ground variants - also the empty district's (EMPTY), which adding
        a building to the district must not take away (it once did: the
        empty district then showed the game's error model)."""
        for name, source in (("DISTRICT_TST_AMAZON_ARENA", "DISTRICT_THEATER"),
                             ("DISTRICT_TST_AMAZON_FORGE", "DISTRICT_HANSA")):
            parts = self.landmarks[name]
            sets = {landmarks.element_name(s) for s in parts["BuildingSets"]}
            grounds = {landmarks._text(v, "Set_HeroBuildings")
                       for v in parts["BaseVariants"]}
            # (the game's own landmark may lack grounds for some sets)
            game = landmarks.merged_landmark(GAME_DIR, source)
            missing = set(landmarks.landmark_sets(game)) - {
                landmarks._text(v, "Set_HeroBuildings") for v in game["base"]}
            self.assertEqual(sets - grounds - missing, set(), name)
            self.assertIn("EMPTY", grounds, name)

    def test_new_district_and_its_building(self):
        arena = self.landmarks["DISTRICT_TST_AMAZON_ARENA"]
        theater = landmarks.merged_landmark(GAME_DIR, "DISTRICT_THEATER")
        hall = "BUILDING_TST_HALL_OF_HEROINES"
        sets = {landmarks.element_name(s): landmarks.set_buildings(s)
                for s in arena["BuildingSets"]}
        # every Theater set, and a copy of each with the hall added
        theater_sets = landmarks.landmark_sets(theater)
        self.assertEqual(len(sets), 2 * len(theater_sets))
        for name, members in theater_sets.items():
            self.assertEqual(sets["{} [{}]".format(name, hall)],
                             members + [hall])
        meshes = {self.mesh(v) for v in arena["BuildingVariants"]
                  if landmarks._text(v, "Tag_HeroBuilding") == hall}
        amphitheater = {landmarks._text(v, "Asset")
                        for v in theater["buildings"]
                        if landmarks._text(v, "Tag_HeroBuilding") ==
                        "BUILDING_AMPHITHEATER"}
        self.assertEqual(meshes, amphitheater)
        districts = read(self.mod_dir, "ArtDefs/Districts.artdef")
        self.assertIn('<m_Name text="DISTRICT_TST_AMAZON_ARENA" />',
                      districts)

    def test_extra_building_joins_the_campus(self):
        campus = self.landmarks["DISTRICT_CAMPUS"]
        academy = "BUILDING_TST_WAR_ACADEMY"
        game = landmarks.landmark_sets(
            landmarks.merged_landmark(GAME_DIR, "DISTRICT_CAMPUS"))
        sets = {landmarks.element_name(s): landmarks.set_buildings(s)
                for s in campus["BuildingSets"]}
        self.assertEqual(sets, {"{} [{}]".format(n, academy): m + [academy]
                                for n, m in game.items()})
        # drawn like (and with the icons of) the Campus' first building
        icons = read(self.mod_dir, modbuild.ICONS_SQL_FILE)
        self.assertIn("REPLACE(Name, 'BUILDING_LIBRARY', '{}')".format(
            academy), icons)

    def test_mesh_references_keep_their_package(self):
        forge = self.landmarks["DISTRICT_TST_AMAZON_FORGE"]
        library = next(v for v in forge["BuildingVariants"]
                       if self.mesh(v) == "DIS_CMP_Library")
        asset = landmarks._field(library, "Asset")
        self.assertEqual(asset.find("m_BLPPackage").get("text"),
                         "landmarks/hero_buildings")


class NewItemTest(unittest.TestCase):

    class NoData:
        conn = None

    civ = {"name": "X", "slug": "CIVILIZATION_X"}

    def normalize(self, **spec):
        u = uniques.new_unique_spec(spec.pop("kind", "building"))
        u.update(name="Y", **spec)
        return uniques.normalize_unique(u, self.civ, self.NoData())

    def test_replaces(self):
        self.assertEqual(self.normalize(base="BUILDING_LIBRARY")["replaced"],
                         "BUILDING_LIBRARY")       # True: the base item
        self.assertIsNone(self.normalize(base="BUILDING_LIBRARY",
                                         replaces="")["replaced"])
        self.assertEqual(self.normalize(
            base="BUILDING_LIBRARY", replaces="BUILDING_SHRINE")["replaced"],
            "BUILDING_SHRINE")
        with self.assertRaises(ValueError):
            self.normalize(base="BUILDING_LIBRARY", replaces="UNIT_X")

    def test_placement(self):
        u = self.normalize(kind="district", base="DISTRICT_CAMPUS")
        self.assertIsNone(u["placement"])         # the copied rules
        u = self.normalize(kind="district", base="",
                           art={"look_from": "DISTRICT_CAMPUS"})
        self.assertEqual(u["placement"], uniques.PLACEMENT_DEFAULTS)
        sql = uniques.unique_sql(u, lambda kind, t: t)[0]
        self.assertIn("NoAdjacentCity = 0", sql)
        for bad in ({"terrains": ["FEATURE_FOREST"]},
                    {"max_per_player": "0"}, {"max_per_player": "x"}):
            with self.assertRaises(ValueError):
                self.normalize(kind="district", base="DISTRICT_CAMPUS",
                               placement=bad)

    def test_new_items_need_a_place(self):
        with self.assertRaises(ValueError):      # no district
            self.normalize(base="")
        u = self.normalize(base="", stats={"PrereqDistrict":
                                           "DISTRICT_CAMPUS"})
        self.assertTrue(u["new"])
        self.assertIsNone(u["replaced"])
        sql = uniques.unique_sql(u, lambda kind, t: t)[0]
        self.assertIn("INSERT INTO Buildings (BuildingType", sql)
        self.assertNotIn("CivGenClone", sql)
        with self.assertRaises(ValueError):      # no look
            self.normalize(kind="district", base="")
        with self.assertRaises(ValueError):      # units are always copies
            self.normalize(kind="unit", base="")


class PrereqTest(unittest.TestCase):

    def test_none_and_bad_prereqs(self):
        class NoData:
            conn = None
        civ = {"name": "X", "slug": "CIVILIZATION_X"}
        spec = uniques.new_unique_spec("unit")
        spec.update(base="UNIT_SWORDSMAN", name="Y",
                    stats={"PrereqTech": "none", "PrereqCivic": ""})
        u = uniques.normalize_unique(spec, civ, NoData())
        self.assertEqual(u["stats"], {"PrereqTech": None})
        self.assertIn("PrereqTech = NULL", uniques.unique_sql(
            u, lambda kind, t: t)[0])
        spec["stats"] = {"PrereqTech": "CIVIC_X"}
        with self.assertRaises(ValueError):
            uniques.normalize_unique(spec, civ, NoData())


class UnitArtTest(unittest.TestCase):

    def test_normalize(self):
        art = unit_art.normalize_art(
            {"members": [{"type": "Knight", "count": "2", "scale": "1"},
                         {"type": "", "count": 1, "scale": 1}]}, "X")
        self.assertEqual(art["members"], [{"type": "Knight", "count": 2,
                                           "scale": 1.0}])
        self.assertFalse(unit_art.is_custom(unit_art.new_unit_art()))
        for bad in ({"members": []}, {"look_from": "BUILDING_X"},
                    {"members": [{"type": "@NOPE"}]},
                    {"models": [{"id": "", "template": "Swordsman"}]},
                    {"models": [{"id": "A", "template": "Swordsman",
                                 "parts": {"body": [{"slot": "Armor",
                                                     "bins": []}]}}]},
                    {"members": [{"type": "Knight", "count": 0}]},
                    {"members": [{"type": "Knight", "scale": 9}]}):
            with self.assertRaises(ValueError):
                unit_art.normalize_art(bad, "X")

    @unittest.skipUnless(GAME_DIR, "needs the game")
    def test_default_look_is_the_base_unit(self):
        element = unit_art.unique_unit_element(
            GAME_DIR, "UNIT_SWORDSMAN", unit_art.new_unit_art())
        look = unit_art.unit_look(GAME_DIR, "UNIT_SWORDSMAN")
        self.assertEqual(ET.tostring(element), ET.tostring(
            modbuild.find_game_element(GAME_DIR, "Units.artdef", "Units",
                                       "UNIT_SWORDSMAN")))
        self.assertEqual(look["members"], [{"type": "Swordsman", "count": 4,
                                            "scale": 1.0}])


class LeaderOnlyTest(unittest.TestCase):
    """Projects without civilizations generate what they always did."""

    def test_modinfo_unchanged(self):
        self.assertEqual(
            modbuild.build_modinfo("M", "d", "g", True, "M.dep", ["a"],
                                   True, True),
            modbuild.build_modinfo("M", "d", "g", True, "M.dep", ["a"],
                                   True, True, False, False, False))
        modinfo = modbuild.build_modinfo("M", "d", "g", True, None, ["a"])
        self.assertIn("<ActionCriteria/>", modinfo)
        self.assertNotIn(modbuild.ICONS_SQL_FILE, modinfo)

    def test_effect_summary_and_check(self):
        effect = modifiers.new_effect("city_yield")
        effect["reqs"] = [{"preset": "city_district",
                           "value": "DISTRICT_CAMPUS"}]
        self.assertEqual(modifiers.summary(effect),
                         "+1 Production in every city (only if: City has "
                         "district Campus)")
        modifiers.check_effect(effect, "trait")
        with self.assertRaises(ValueError):
            modifiers.check_effect(modifiers.new_effect("free_unit"), "trait")


if __name__ == "__main__":
    unittest.main()


class NewLeaderTest(unittest.TestCase):
    """Leaders that inherit from nobody (no game cache needed)."""

    class NoData:
        conn = None
        leader_meta = {}

        def abilities(self, leader):
            return []

        def meta(self, leader):
            return {}

        def type_name(self, kind, type_name):
            return ""

    def normalize(self, **spec):
        s = leaders.new_leader_spec()
        s.update(name="Liberty", civ="CIVILIZATION_AMERICA", orig="",
                 agenda="AGENDA_BIG_STICK_POLICY",
                 new_ability={"name": "Torch"})
        s.update(spec)
        return leaders.normalize_spec(s, self.NoData(), "TST")

    def test_needs_ability_and_agenda(self):
        with self.assertRaisesRegex(ValueError, "ability"):
            self.normalize(new_ability={})
        with self.assertRaisesRegex(ValueError, "agenda"):
            self.normalize(agenda="")
        with self.assertRaisesRegex(ValueError, "civilization"):
            self.normalize(civ="")

    def test_defaults(self):
        c = self.normalize(ai_traits=["trait_leader_expansionist"],
                           abilities={"TRAIT_X": {"name": "ignored"}})
        self.assertEqual(c["leader_icon"], "ICON_LEADER_DEFAULT")
        self.assertEqual(c["ai_traits"], ["TRAIT_LEADER_EXPANSIONIST"])
        self.assertEqual(c["abilities"], [])
        self.assertTrue(c["new_ability"]["replace"])
        self.assertEqual(c["scene_source"], "")
        # no cache: the items all of the civilization's leaders share
        self.assertIn("HAVING COUNT(DISTINCT", leaders.config_block(c))
        self.assertIn("'LOC_DIPLO_GREETING_ANY_ANY'",
                      "\n".join(leaders.inherited_text_sql(c)))


class MomentsTest(unittest.TestCase):
    """Historic moment pictures belong to civilizations."""

    class NoData:
        conn = None
        leader_meta = civ_names = {}

        def abilities(self, leader):
            return []

        def all_abilities(self):
            return []

        def meta(self, leader):
            return {}

        def leader_unique_items(self, leader):
            return []

        def type_name(self, kind, type_name):
            return ""

    def civ(self, **spec):
        civ = civs.new_civ_spec()
        civ.update(name="Amazons", city_names=["Themiscyra"],
                   ability={"name": "X"}, **spec)
        return civ

    def leader(self, **spec):
        lead = leaders.new_leader_spec()
        lead.update(name="Q", civ="CIVILIZATION_TST_AMAZONS",
                    orig="LEADER_GILGAMESH")
        lead.update(spec)
        return lead

    def test_civ_moments(self):
        entry = {"item": "unit_tst_x", "path": MOMENT_IMAGE, "half": True}
        civ_ctxs, ctxs, errors = modbuild.prepare_project(
            [self.leader()], [self.civ(moment_illustrations=[entry])],
            self.NoData(), "TST")
        self.assertEqual(errors, [])
        m, = civ_ctxs[0]["moments"]
        self.assertEqual((m["item"], m["texture"], m["half"]),
                         ("UNIT_TST_X",
                          "MOMENT_CIVILIZATION_TST_AMAZONS_UNIT_TST_X", True))
        sql = modbuild.build_moments_sql(civ_ctxs + ctxs)
        self.assertIn("'UNIT_TST_X', "
                      "'MOMENT_CIVILIZATION_TST_AMAZONS_UNIT_TST_X.dds'", sql)
        # one picture per item, whoever has it
        _, _, errors = modbuild.prepare_project(
            [self.leader(moment_illustrations=[entry])],
            [self.civ(moment_illustrations=[entry])], self.NoData(), "TST")
        self.assertEqual(len(errors), 1)
        self.assertIn("one per item", errors[0])
        with self.assertRaisesRegex(ValueError, "two historic moment"):
            civs.normalize_civ(self.civ(moment_illustrations=[entry, entry]),
                               self.NoData(), "TST")

    def test_older_projects_move_to_the_civ(self):
        civ = self.civ(moment_illustrations=[
            {"item": "UNIT_A", "path": "civ.png"}])
        mine = self.leader(moment_illustrations=[
            {"item": "UNIT_A", "path": "leader.png"},
            {"item": "UNIT_B", "path": "b.png"}])
        game = self.leader(civ="CIVILIZATION_FRANCE", moment_illustrations=[
            {"item": "UNIT_C", "path": "c.png"}])
        moved = moments.move_to_civs(
            [mine, game], [civ],
            lambda spec: civ if spec["civ"] == "CIVILIZATION_TST_AMAZONS"
            else None)
        self.assertEqual(moved, 1)
        self.assertEqual([(e["item"], e["path"])
                          for e in civ["moment_illustrations"]],
                         [("UNIT_A", "civ.png"), ("UNIT_B", "b.png")])
        self.assertEqual(mine["moment_illustrations"], [])
        self.assertEqual(len(game["moment_illustrations"]), 1)

    def test_exported_with_the_civ(self):
        civ = self.civ(moment_illustrations=[
            {"item": "UNIT_A", "path": "pic.png"}])
        self.assertIn("pic.png", [holder.get(key) for holder, key in
                                  project._spec_images(civ)])


class ImprovementTest(unittest.TestCase):
    """Unique improvements (no game cache needed)."""

    class NoData:
        conn = None

    civ = {"name": "X", "slug": "CIVILIZATION_X"}

    def normalize(self, **spec):
        u = uniques.new_unique_spec("improvement")
        u.update(name="Y", **spec)
        return uniques.normalize_unique(u, self.civ, self.NoData())

    def test_never_replaces(self):
        u = self.normalize(base="IMPROVEMENT_FARM", replaces=True)
        self.assertIsNone(u["replaced"])
        self.assertIsNone(u["placement"])       # the Farm's rules

    def test_new_needs_a_look_and_a_place(self):
        with self.assertRaisesRegex(ValueError, "looks like"):
            self.normalize(base="")
        u = self.normalize(base="", art={"look_from": "improvement_farm"})
        self.assertEqual(u["placement"],
                         uniques.IMPROVEMENT_PLACEMENT_DEFAULTS)
        self.assertEqual(u["model_from"], "IMPROVEMENT_FARM")
        with self.assertRaisesRegex(ValueError, "at least one terrain"):
            self.normalize(base="", art={"look_from": "IMPROVEMENT_FARM"},
                           placement={"terrains": []})

    def test_water_improvement(self):
        u = self.normalize(base="", art={"look_from": "IMPROVEMENT_FISHERY"},
                           placement={"terrains": ["TERRAIN_COAST"],
                                      "resources": ["RESOURCE_FISH"],
                                      "river": True})
        sql = uniques.improvement_placement_sql(u["slug"], u["placement"])
        self.assertIn("Domain = 'DOMAIN_SEA', RequiresRiver = 1", sql)
        self.assertIn("('IMPROVEMENT_Y', 'RESOURCE_FISH')", sql)


class OwnerTablesTest(unittest.TestCase):
    """Every kind that has effects (abilities and each unique kind) is in
    every per-owner table, so its effect dialog and SQL work."""

    def test_every_owner_is_known(self):
        from civgen.gui.modifier_editor import OWNER_HINTS
        for owner in ("trait",) + uniques.KINDS:
            self.assertIn(owner, OWNER_HINTS)
            self.assertIn(owner, modifiers.OWNER_SCOPES)
            self.assertTrue(modifiers.templates_for(owner))
            if owner != "unit":         # units: through a unit ability
                self.assertIn(owner, modifiers.LINK_TABLES)


class LoadingBackgroundTest(unittest.TestCase):
    """The default loading background and its hue."""

    class NoData(NewLeaderTest.NoData):
        def leader_unique_items(self, leader):
            return []

    def normalize(self, **spec):
        s = leaders.new_leader_spec()
        s.update(name="Q", civ="CIVILIZATION_SUMERIA",
                 orig="LEADER_GILGAMESH", **spec)
        return leaders.normalize_spec(s, self.NoData(), "TST")

    def test_shift_hue(self):
        from PIL import Image
        from civgen.art import shift_hue
        red = Image.new("RGBA", (1, 1), (255, 0, 0, 128))
        r, g, b, a = shift_hue(red, 120).getpixel((0, 0))
        self.assertTrue(g > 240 and r < 10 and b < 10, (r, g, b))
        self.assertEqual(a, 128)                # transparency stays
        r, g, b, _ = shift_hue(red, -120).getpixel((0, 0))
        self.assertTrue(b > 240 and r < 10 and g < 10, (r, g, b))
        self.assertEqual(shift_hue(red, 0).getpixel((0, 0)),
                         (255, 0, 0, 128))

    def test_default_background(self):
        from civgen.art import DEFAULT_LOAD_BG
        from civgen.util import asset_path
        c = self.normalize()
        self.assertIsNone(c["load_bg"])         # the original's
        c = self.normalize(load_bg_default=True, load_bg_hue=90)
        self.assertEqual(c["load_bg_path"], asset_path(DEFAULT_LOAD_BG))
        self.assertEqual(c["load_bg"], "LEADER_TST_Q_BACKGROUND")
        self.assertEqual(c["load_bg_hue"], 90)
        self.assertTrue(leaders.needs_art(c))
        # an image of its own wins over the default
        c = self.normalize(load_bg_default=True, load_bg_path=MOMENT_IMAGE)
        self.assertEqual(c["load_bg_path"], MOMENT_IMAGE)
        with self.assertRaisesRegex(ValueError, "-180 to 180"):
            self.normalize(load_bg_hue=200)
        self.assertIn(("\U0001F5BC", "loading background"),
                      leaders.leader_custom_marks(
                          dict(leaders.new_leader_spec(),
                               load_bg_default=True)))
