"""Tests: generate mods without the GUI and run their SQL against copies of
the game's own databases (the debug caches the game writes), so every
table, column and foreign key the mod uses is checked against the real
schema.

    python -m unittest discover -s tests -t .

Tests needing the game cache (DebugGameplay.sqlite) or install are
skipped when it is missing.
"""

import json
import os
import shutil
import sqlite3
import tempfile
import unittest
import uuid
import xml.etree.ElementTree as ET
import zlib

from civgen import (agendas, artdefs, civs, landmarks, leaders, modbuild,
                    modifiers, moments, moods, project, unit_art, unit_models,
                    uniques)
from civgen.gamedata import GameData
from civgen.util import find_game_cache, find_game_dir

CACHE = find_game_cache()
MOMENT_IMAGE = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "assets", "icon.png")
GAME_DIR = find_game_dir()
DATA = None


def gathering_storm_cache():
    """Whether the game's cache is of a Gathering Storm game: the game
    rewrites it for the ruleset last played, and Gathering Storm's tables
    and types only exist then."""
    if not CACHE:
        return False
    db = sqlite3.connect(CACHE)
    try:
        return bool(db.execute("SELECT 1 FROM sqlite_master WHERE name = "
                               "'Units_XP2'").fetchall())
    finally:
        db.close()


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


def attaching_effect():
    """A raw effect attaching an effect of its own to the player's cities
    with a Campus or a Library (an 'any of' group)."""
    effect = modifiers.new_raw_effect(
        "MODIFIER_PLAYER_CITIES_ATTACH_MODIFIER")
    effect["attached"] = modifiers.new_effect("this_city_yield_pct")
    effect["reqs"] = [{"group": "ANY", "target": "subject", "reqs": [
        {"preset": "city_district", "value": "DISTRICT_CAMPUS"},
        {"type": "REQUIREMENT_CITY_HAS_BUILDING",
         "args": {"BuildingType": "BUILDING_LIBRARY"}}]}]
    return effect


def own_agenda():
    """An agenda of a leader's own (advanced mode): a like and a dislike."""
    culture = {"value": "8", "text": "Admires cultured civilizations",
               "reason": "(You have a rich culture.)",
               "reqs": [{"type": "REQUIREMENT_PLAYER_YIELD_LEAD",
                         "args": {"YieldType": "YIELD_CULTURE",
                                  "YieldRatio": "1.15",
                                  "MinimumDelta": "5"}}]}
    neighbors = {"value": "-6", "text": "Distrusts neighbors who rule "
                                        "differently", "reason": "",
                 "reqs": [{"type": "REQUIREMENT_PLAYER_IS_NEIGHBOR"},
                          {"type": "REQUIREMENT_PLAYER_HAS_SAME_GOVERNMENT",
                           "not": True}]}
    # an event (written "+12", as typed)
    backstab = {"value": "+12", "text": "Admires bold strikes",
                "reason": "",
                "reqs": [{"type": "REQUIREMENT_PLAYER_DECLARED_WAR",
                          "args": {"WarType": "SURPRISE_WAR"}}]}
    return {"name": "Queen of the Steppe", "desc": "",
            "reactions": [culture, neighbors, backstab]}


def sample_project():
    """(leader specs, civ specs) using every feature that needs no art."""
    alt = leaders.new_leader_spec()
    alt.update(name="Jeanne", civ="CIVILIZATION_FRANCE",
               orig="LEADER_CATHERINE_DE_MEDICI", city_names=["Orleans"])
    # a leader's own unique (of a game civilization)
    guard = uniques.new_unique_spec("unit")
    guard.update(base="UNIT_KNIGHT", name="Pucelle Guard",
                 stats={"Combat": "52"})
    alt["uniques"] = [guard]

    civ = civs.new_civ_spec()
    civ.update(name="Amazons", adjective="Amazonian",
               city_names=["Themiscyra", "Lykastia", "Chadesia"],
               music_from="CIVILIZATION_INCA", icon_from="CIVILIZATION_INCA",
               culture="SouthAmerican", unit_culture="SouthAmerican")
    civ["citizen_names"]["female"] = ["Hippolyta", "Penthesilea"]
    civ["start_bias"].update(feature={"FEATURE_JUNGLE": 2}, river=3)
    civ["pedia"].update(history="First.\n\nSecond.", location="Pontus")
    yields = modifiers.new_effect("city_yield")
    # (advanced: met by either requirement, one of them a raw one)
    yields["reqs"] = [{"preset": "city_district", "value": "DISTRICT_CAMPUS"},
                      {"type": "REQUIREMENT_CITY_HAS_BUILDING",
                       "args": {"BuildingType": "BUILDING_LIBRARY"},
                       "target": "subject"}]
    yields["set_types"] = {"subject": "ANY"}
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
                          effects=[yields, combat, adjacency,
                                   attaching_effect()])
    unit = uniques.new_unique_spec("unit")
    unit.update(base="UNIT_SWORDSMAN", name="Amazon Warrior",
                stats={"Combat": "40", "BaseMoves": "3",
                       "PrereqTech": "None", "ResourceCost": "10",
                       "ResourceMaintenanceType": "RESOURCE_HORSES",
                       "ResourceMaintenanceAmount": "1"},
                effects=[modifiers.new_effect("movement"),
                         modifiers.new_effect("combat_strength"),
                         dict(modifiers.new_raw_effect(
                             "MODIFIER_UNIT_ADJUST_COMBAT_STRENGTH",
                             {"Amount": "3"}),
                             reqs=[{"type": "REQUIREMENT_PLOT_IS_HILLS",
                                    "target": "subject"}])],
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
                 adjacencies=False,
                 # (advanced, with what a copied game modifier keeps)
                 effects=[dict(modifiers.new_raw_effect(
                     "MODIFIER_PLAYER_GRANT_YIELD",
                     {"Amount": "50", "YieldType": "YIELD_GOLD"}),
                     run_once=True, permanent=True,
                     arg_types={"Amount": {"Type": "ScaleByGameSpeed"}},
                     columns={"Repeatable": 1})])
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
    lodge = uniques.new_unique_spec("building")
    lodge.update(base="BUILDING_BARRACKS", name="War Lodge")
    second.update(name="Penthesilea", civ="CIVILIZATION_TST_AMAZONS",
                  orig="LEADER_TRAJAN", city_names=["Troy"],
                  own_agenda=own_agenda(),
                  # a leader's own unique (of the project's civilization)
                  uniques=[lodge])
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
        # custom files (advanced mode): a SQL file, and a script for
        # Gathering Storm only
        custom = []
        for name, text, entry in (
                ("Custom.sql", "UPDATE Units SET Cost = 1 WHERE UnitType = "
                 "'UNIT_TST_AMAZON_WARRIOR';\n", {}),
                ("Extra.lua", "print('hello')\n",
                 {"criteria": "Expansion2AndBeyond"})):
            path = os.path.join(cls.tmp, name)
            with open(path, "w") as fh:
                fh.write(text)
            custom.append(dict(modbuild.new_custom_file(path), **entry))
        extra_files, errors = modbuild.check_extra_files(custom)
        assert not errors, errors
        cls.report = []
        modbuild.write_mod("Test Mod", cls.ctxs, "TestMod", cls.mod_dir,
                           "guid", None, cls.report, lambda text: None,
                           cls.civs, game_data().type_name,
                           extra_files=extra_files)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_gameplay_sql_runs(self):
        db = database("DebugGameplay.sqlite", self.tmp)
        self.addCleanup(db.close)
        db.executescript(read(self.mod_dir, "Gameplay/NewLeader_Gameplay.sql"))
        if gathering_storm_cache():     # (its own file, loaded with GS)
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
        self.assertEqual(q("SELECT StrategicResource FROM Units WHERE "
                           "UnitType = 'UNIT_TST_AMAZON_WARRIOR'"),
                         [("RESOURCE_IRON",)])      # the Swordsman's
        if gathering_storm_cache():
            self.assertEqual(q("SELECT ResourceCost, ResourceMaintenanceType, "
                               "ResourceMaintenanceAmount FROM Units_XP2 "
                               "WHERE UnitType = 'UNIT_TST_AMAZON_WARRIOR'"),
                             [(10, "RESOURCE_HORSES", 1)])
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

    def test_advanced_effects(self):
        """Raw effects, attached effects and 'any of' requirements: rows
        that refer to each other by value (no foreign keys check them)."""
        db = database("DebugGameplay.sqlite", self.tmp)
        self.addCleanup(db.close)
        db.executescript(read(self.mod_dir, "Gameplay/NewLeader_Gameplay.sql"))
        self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
        q = lambda sql: db.execute(sql).fetchall()    # noqa: E731
        self.assertEqual(q("SELECT ModifierId, ModifierType FROM Modifiers "
                           "WHERE ModifierId LIKE '%TST%' AND ModifierType "
                           "NOT IN (SELECT ModifierType FROM "
                           "DynamicModifiers)"), [])
        # the attaching effect and the effect it attaches
        attach = "CIVILIZATION_TST_AMAZONS_MOD_4"
        self.assertEqual(q("SELECT Value FROM ModifierArguments WHERE "
                           "ModifierId = '{}' AND Name = 'ModifierId'"
                           .format(attach)), [(attach + "_ATTACHED",)])
        self.assertEqual(q("SELECT ModifierType FROM Modifiers WHERE "
                           "ModifierId = '{}_ATTACHED'".format(attach)),
                         [("MODIFIER_SINGLE_CITY_ADJUST_CITY_YIELD_MODIFIER",)])
        self.assertEqual(q("SELECT * FROM TraitModifiers WHERE ModifierId = "
                           "'{}_ATTACHED'".format(attach)), [])
        self.assertEqual(q("SELECT a.Value FROM ModifierArguments a JOIN "
                           "Modifiers m USING (ModifierId) WHERE a.Name = "
                           "'ModifierId' AND m.ModifierId LIKE '%TST%' AND "
                           "a.Value NOT IN (SELECT ModifierId FROM "
                           "Modifiers)"), [])
        # its 'any of' group: a set of its own, met when the group is
        nested = q("SELECT Value FROM RequirementArguments WHERE Name = "
                   "'RequirementSetId' AND RequirementId LIKE '%TST%'")
        self.assertEqual(nested, [(attach + "_SUBJECT_REQS_1_SET",)])
        self.assertEqual(q("SELECT RequirementSetType FROM RequirementSets "
                           "WHERE RequirementSetId = '{}'".format(
                               nested[0][0])),
                         [("REQUIREMENTSET_TEST_ANY",)])
        self.assertEqual(len(q("SELECT * FROM RequirementSetRequirements "
                               "WHERE RequirementSetId = '{}'".format(
                                   nested[0][0]))), 2)
        # a template effect met by either of its requirements
        self.assertEqual(q("SELECT RequirementSetType FROM RequirementSets "
                           "WHERE RequirementSetId = "
                           "'CIVILIZATION_TST_AMAZONS_MOD_1_SUBJECT_REQS'"),
                         [("REQUIREMENTSET_TEST_ANY",)])
        # links without a foreign key
        for table, column in (("BuildingModifiers", "BuildingType"),
                              ("ImprovementModifiers", "ImprovementType")):
            self.assertEqual(q("SELECT ModifierId FROM {} WHERE {} LIKE "
                               "'%TST%' AND ModifierId NOT IN (SELECT "
                               "ModifierId FROM Modifiers)".format(
                                   table, column)), [])
        # what a copied game modifier keeps
        self.assertEqual(q("SELECT RunOnce, Permanent, Repeatable FROM "
                           "Modifiers WHERE ModifierId = "
                           "'TST_HUNTING_LODGE_MOD_1'"), [(1, 1, 1)])
        self.assertEqual(q("SELECT Name, Type FROM ModifierArguments WHERE "
                           "ModifierId = 'TST_HUNTING_LODGE_MOD_1' ORDER BY "
                           "1"), [("Amount", "ScaleByGameSpeed"),
                                  ("YieldType", "ARGTYPE_IDENTITY")])
        # the unique unit's raw effect: on its ability, with a preview
        self.assertEqual(q("SELECT UnitAbilityType FROM UnitAbilityModifiers "
                           "WHERE ModifierId = 'TST_AMAZON_WARRIOR_MOD_3'"),
                         [("ABILITY_TST_AMAZON_WARRIOR",)])
        self.assertEqual(len(q("SELECT * FROM ModifierStrings WHERE "
                               "ModifierId = 'TST_AMAZON_WARRIOR_MOD_3'")), 1)

    def test_leader_uniques(self):
        """A leader's own uniques: given by a leader trait, as the game's
        (the Rough Rider), shown on that leader's setup screen only."""
        db = database("DebugGameplay.sqlite", self.tmp)
        self.addCleanup(db.close)
        db.executescript(read(self.mod_dir, "Gameplay/NewLeader_Gameplay.sql"))
        self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
        q = lambda sql: db.execute(sql).fetchall()    # noqa: E731
        for leader, item, table, column in (
                ("LEADER_TST_JEANNE", "UNIT_TST_PUCELLE_GUARD", "Units",
                 "UnitType"),
                ("LEADER_TST_PENTHESILEA", "BUILDING_TST_WAR_LODGE",
                 "Buildings", "BuildingType")):
            trait = "TRAIT_LEADER_" + item
            self.assertEqual(q("SELECT TraitType FROM {} WHERE {} = '{}'"
                               .format(table, column, item)), [(trait,)])
            self.assertEqual(q("SELECT LeaderType FROM LeaderTraits WHERE "
                               "TraitType = '{}'".format(trait)), [(leader,)])
            self.assertEqual(q("SELECT * FROM CivilizationTraits WHERE "
                               "TraitType = '{}'".format(trait)), [])
        self.assertEqual(q("SELECT Combat FROM Units WHERE UnitType = "
                           "'UNIT_TST_PUCELLE_GUARD'"), [(52,)])
        self.assertEqual(q("SELECT ReplacesUnitType FROM UnitReplaces WHERE "
                           "CivUniqueUnitType = 'UNIT_TST_PUCELLE_GUARD'"),
                         [("UNIT_KNIGHT",)])
        # the setup screen: the leader's own items, after the civ's
        config = database("DebugConfiguration.sqlite", self.tmp)
        self.addCleanup(config.close)
        config.executescript(read(self.mod_dir, "Config/NewLeader_Config.sql"))

        def items(leader):
            return [t for (t,) in config.execute(
                "SELECT Type FROM PlayerItems WHERE LeaderType = ? AND "
                "Domain = 'Players:Expansion2_Players' ORDER BY SortIndex",
                (leader,))]
        jeanne = items("LEADER_TST_JEANNE")
        self.assertEqual(jeanne[-1], "UNIT_TST_PUCELLE_GUARD")
        self.assertEqual(set(jeanne[:-1]), set(items(
            "LEADER_CATHERINE_DE_MEDICI")))
        penthesilea = items("LEADER_TST_PENTHESILEA")
        self.assertEqual(penthesilea[-1], "BUILDING_TST_WAR_LODGE")
        self.assertIn("UNIT_TST_AMAZON_WARRIOR", penthesilea)
        self.assertNotIn("BUILDING_TST_WAR_LODGE",
                         items("LEADER_TST_HIPPOLYTA"))
        # art (a copy of the base item's) and the README
        self.assertIn('"UNIT_TST_PUCELLE_GUARD"',
                      read(self.mod_dir, "ArtDefs/Units.artdef"))
        self.assertIn("unit Pucelle Guard (UNIT_TST_PUCELLE_GUARD)",
                      read(self.mod_dir, "README.txt"))

    def test_own_agenda(self):
        """An agenda of a leader's own: its likes and dislikes are simple
        diplomacy modifiers of its trait, like the game's agendas'."""
        db = database("DebugGameplay.sqlite", self.tmp)
        self.addCleanup(db.close)
        db.executescript(read(self.mod_dir, "Gameplay/NewLeader_Gameplay.sql"))
        self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
        q = lambda sql: db.execute(sql).fetchall()    # noqa: E731
        agenda = "AGENDA_TST_PENTHESILEA"
        self.assertEqual(q("SELECT AgendaType FROM HistoricalAgendas WHERE "
                           "LeaderType = 'LEADER_TST_PENTHESILEA'"),
                         [(agenda,)])
        self.assertEqual(q("SELECT Name FROM Agendas WHERE AgendaType = "
                           "'{}'".format(agenda)),
                         [("LOC_{}_NAME".format(agenda),)])
        mods = q("SELECT m.ModifierId, m.ModifierType, "
                 "m.SubjectRequirementSetId FROM AgendaTraits a JOIN "
                 "TraitModifiers t USING (TraitType) JOIN Modifiers m USING "
                 "(ModifierId) WHERE a.AgendaType = '{}' ORDER BY 1".format(
                     agenda))
        self.assertEqual([m[1] for m in mods],
                         ["MODIFIER_PLAYER_DIPLOMACY_SIMPLE_MODIFIER"] * 3)
        args = dict(q("SELECT Name, Value FROM ModifierArguments WHERE "
                      "ModifierId = '{}'".format(mods[1][0])))
        self.assertEqual(args["InitialValue"], "-6")
        self.assertEqual(args["StatementKey"],
                         "LOC_{}_REACTION_2_REASON".format(agenda))
        # the game's standard conditions, then its own (one inverted)
        self.assertEqual(q("SELECT r.RequirementType, r.Inverse FROM "
                           "RequirementSetRequirements s JOIN Requirements r "
                           "USING (RequirementId) WHERE s.RequirementSetId = "
                           "'{}' ORDER BY r.RequirementId".format(mods[1][2])),
                         [("REQUIREMENT_CIVILIZATION_LEVEL", 0),
                          ("REQUIREMENT_PLAYER_MET_X_TURNS_AGO", 0),
                          ("REQUIREMENT_PLAYER_IS_NEIGHBOR", 0),
                          ("REQUIREMENT_PLAYER_HAS_SAME_GOVERNMENT", 1)])
        # an event: written like the game's own (Tomyris' dislike of
        # surprise wars): Triggered, met at all, fading
        args = dict(q("SELECT Name, Value FROM ModifierArguments WHERE "
                      "ModifierId = '{}'".format(mods[2][0])))
        self.assertEqual((args["InitialValue"], args["ReductionTurns"],
                          args["ReductionValue"]), ("12", "10", "-1"))
        self.assertEqual(q("SELECT r.RequirementType, r.Triggered FROM "
                           "RequirementSetRequirements s JOIN Requirements r "
                           "USING (RequirementId) WHERE s.RequirementSetId = "
                           "'{}' ORDER BY r.RequirementId".format(mods[2][2])),
                         [("REQUIREMENT_CIVILIZATION_LEVEL", 0),
                          ("REQUIREMENT_PLAYER_HAS_MET", 0),
                          ("REQUIREMENT_PLAYER_DECLARED_WAR", 1)])
        text = read(self.mod_dir, "Text/NewLeader_Text.sql")
        self.assertIn("'LOC_{}_REACTION_1_REASON', '(You have a rich "
                      "culture.)'".format(agenda), text)
        # (no reason: the text; no description: the texts)
        self.assertIn("'LOC_{}_REACTION_2_REASON', 'Distrusts neighbors"
                      .format(agenda), text)
        self.assertIn("'LOC_{}_DESCRIPTION', 'Admires cultured "
                      "civilizations[NEWLINE]Distrusts".format(agenda), text)

    def test_custom_files(self):
        """Custom files are copied as they are and loaded by their
        actions, after the generated files."""
        self.assertEqual(read(self.mod_dir, "Custom/Custom.sql"),
                         "UPDATE Units SET Cost = 1 WHERE UnitType = "
                         "'UNIT_TST_AMAZON_WARRIOR';\n")
        root = ET.fromstring(read(self.mod_dir, "TestMod.modinfo"))
        files = [f.text for f in root.find("Files")]
        self.assertIn("Custom/Custom.sql", files)
        self.assertIn("Custom/Extra.lua", files)
        actions = {a.get("id"): a for a in root.find("InGameActions")}
        self.assertEqual(len(actions), len(root.find("InGameActions")))
        sql, = [a for a in actions.values()
                if [f.text for f in a.findall("File")] ==
                ["Custom/Custom.sql"]]
        self.assertEqual((sql.tag, sql.find("Properties/LoadOrder").text),
                         ("UpdateDatabase", "1100"))
        lua, = [a for a in actions.values()
                if a.tag == "AddGameplayScripts"]
        self.assertEqual(lua.find("Criteria").text, "Expansion2AndBeyond")
        # each criterion is defined once
        ids = [c.get("id") for c in root.find("ActionCriteria")]
        self.assertEqual(sorted(ids), sorted(set(ids)))
        self.assertIn("Expansion2AndBeyond", ids)
        # (the generated SQL first, then the custom file's)
        db = database("DebugGameplay.sqlite", self.tmp)
        self.addCleanup(db.close)
        db.executescript(read(self.mod_dir, "Gameplay/NewLeader_Gameplay.sql")
                         + read(self.mod_dir, "Custom/Custom.sql"))
        self.assertEqual(db.execute(
            "SELECT Cost FROM Units WHERE UnitType = "
            "'UNIT_TST_AMAZON_WARRIOR'").fetchall(), [(1,)])
        # what the Workshop uploader checks
        from civgen import workshop
        results = dict((message, ok) for ok, message in workshop.check_mod(
            self.mod_dir, {"title": "T", "description": "D"}))
        self.assertTrue(results["All files the mod lists exist"])
        self.assertTrue(results["No archives or programs in the mod folder"])

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
        files = ["TestMod.modinfo", "TestMod.dep",
                 "Config/NewLeader_Colors.xml"]
        files += ["ArtDefs/" + f for f in os.listdir(
            os.path.join(self.mod_dir, "ArtDefs"))]
        for rel in files:
            ET.fromstring(read(self.mod_dir, rel).encode("utf-8"))
        modinfo = ET.fromstring(read(self.mod_dir, "TestMod.modinfo"))
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
        if not gathering_storm_cache():
            self.skipTest("some effects need the expansions; the game's "
                          "cache is of another ruleset")
        db = sqlite3.connect(CACHE)
        self.addCleanup(db.close)
        known = {t for (t,) in db.execute(
            "SELECT ModifierType FROM DynamicModifiers")}
        for t in modifiers.TEMPLATES.values():
            self.assertIn(t.modifier_type, known, t.id)

    def test_requirements_are_game_requirement_types(self):
        if not gathering_storm_cache():
            self.skipTest("some conditions need the expansions; the game's "
                          "cache is of another ruleset")
        db = sqlite3.connect(CACHE)
        self.addCleanup(db.close)
        known = {t for (t,) in db.execute(
            "SELECT DISTINCT RequirementType FROM Requirements")}
        for p in modifiers.REQUIREMENTS.values():
            self.assertIn(p.requirement_type, known, p.id)

    def test_no_wonders_to_copy(self):
        data = game_data()
        copyable = dict(data.unique_choices("building"))
        self.assertIn("BUILDING_LIBRARY", copyable)
        self.assertNotIn("BUILDING_PYRAMIDS", copyable)
        # (effects may still refer to wonders)
        self.assertIn("BUILDING_PYRAMIDS", dict(data.type_choices("building")))
        self.assertEqual(data.unique_choices("unit"),
                         data.type_choices("unit"))

    def test_clone_tables_exist(self):
        db = sqlite3.connect(CACHE)
        self.addCleanup(db.close)
        tables = {t for (t,) in db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        gs = gathering_storm_cache()
        for kind, rows in uniques.CLONE_TABLES.items():
            for table, column, gs_only in rows:
                if gs_only and not gs:
                    continue            # not in this ruleset's cache
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


class StrategicResourceTest(unittest.TestCase):
    """A unique unit's strategic resource, and Gathering Storm's resource
    cost and upkeep."""

    class NoData:
        conn = None

    civ = {"name": "X", "slug": "CIVILIZATION_X"}

    def normalize(self, stats, base="UNIT_SWORDSMAN", data=None):
        spec = uniques.new_unique_spec("unit")
        spec.update(base=base, name="Y", stats=stats)
        return uniques.normalize_unique(spec, self.civ, data or self.NoData(),
                                        "TST")

    def test_sql(self):
        u = self.normalize({"StrategicResource": "resource_niter",
                            "ResourceCost": "5",
                            "ResourceMaintenanceType": "None"})
        self.assertEqual(u["stats"], {"StrategicResource": "RESOURCE_NITER",
                                      "ResourceCost": 5,
                                      "ResourceMaintenanceType": None})
        sql, gs, _ = uniques.unique_sql(u, lambda kind, t: t)
        # the resource is the game's own column; the amounts Gathering
        # Storm's (a row with its defaults if the copied unit has none)
        self.assertIn("StrategicResource = 'RESOURCE_NITER'", sql)
        self.assertNotIn("ResourceCost", sql)
        self.assertIn("INSERT OR IGNORE INTO Units_XP2 (UnitType) VALUES "
                      "('UNIT_TST_Y');", gs)
        self.assertIn("ResourceCost = 5, ResourceMaintenanceType = NULL", gs)
        self.assertLess(gs.index("CivGenClone"), gs.index("INSERT OR IGNORE"))

    def test_bad_values(self):
        for stats in ({"StrategicResource": "IRON"},
                      {"ResourceCost": "x"},
                      # an amount of no resource
                      {"StrategicResource": "NONE", "ResourceCost": "5"},
                      {"ResourceMaintenanceType": "none",
                       "ResourceMaintenanceAmount": "1"}):
            with self.assertRaises(ValueError, msg=stats):
                self.normalize(stats)
        self.normalize({"StrategicResource": "NONE", "ResourceCost": "0"})

    @unittest.skipUnless(gathering_storm_cache(),
                         "needs a Gathering Storm game's cache")
    def test_game_data(self):
        data = game_data()
        swordsman = data.item("unit", "UNIT_SWORDSMAN")
        self.assertEqual((swordsman["StrategicResource"],
                          swordsman["ResourceCost"]), ("RESOURCE_IRON", 20))
        self.assertEqual(data.item("unit", "UNIT_TANK")
                         ["ResourceMaintenanceType"], "RESOURCE_OIL")
        warrior = data.item("unit", "UNIT_WARRIOR")   # no Units_XP2 row
        self.assertEqual((warrior["ResourceCost"],
                          warrior["ResourceMaintenanceType"]), (0, None))
        self.assertIn("RESOURCE_IRON",
                      [t for t, _ in data.type_choices("strategic_resource")])
        self.assertNotIn("RESOURCE_WINE",
                         [t for t, _ in data.type_choices(
                             "strategic_resource")])
        # the Warrior needs no resource: no cost of none
        with self.assertRaises(ValueError):
            self.normalize({"ResourceCost": "5"}, "UNIT_WARRIOR", data)
        u = self.normalize({"StrategicResource": "RESOURCE_IRON",
                            "ResourceCost": "5",
                            "ResourceMaintenanceType": "RESOURCE_IRON",
                            "ResourceMaintenanceAmount": "1"},
                           "UNIT_WARRIOR", data)
        sql, gs, _ = uniques.unique_sql(u, data.type_name)
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        db = database("DebugGameplay.sqlite", tmp)
        self.addCleanup(db.close)
        db.executescript(
            "INSERT INTO Types (Type, Kind) VALUES ('CIVILIZATION_X', "
            "'KIND_CIVILIZATION');"
            "INSERT INTO Civilizations (CivilizationType, Name, Description,"
            " Adjective, StartingCivilizationLevelType) VALUES "
            "('CIVILIZATION_X', 'X', 'X', 'X', 'CIVILIZATION_LEVEL_FULL_CIV');"
            + sql + gs)
        self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(db.execute(
            "SELECT StrategicResource, ResourceCost, ResourceMaintenanceType, "
            "ResourceMaintenanceAmount, Units_XP2.CanEarnExperience FROM "
            "Units JOIN Units_XP2 USING (UnitType) WHERE UnitType = "
            "'UNIT_TST_Y'"
        ).fetchall(), [("RESOURCE_IRON", 5, "RESOURCE_IRON", 1, 1)])
        text = uniques.describe_unique(
            {"kind": "unit", "base": "UNIT_TANK",
             "stats": {"ResourceMaintenanceType": "NONE"}}, data)
        self.assertIn("Maintenance costs no [ICON_RESOURCE_OIL] Oil per "
                      "turn.", text)


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

    def test_modinfo_text_newlines_use_game_token(self):
        root = ET.fromstring(modbuild.build_modinfo(
            "First\nSecond", "First\r\nSecond", "g", False, None, [],
            authors="First\rSecond"))
        properties = root.find("Properties")
        self.assertEqual(properties.findtext("Name"), "First[NEWLINE]Second")
        self.assertEqual(properties.findtext("Description"),
                         "First[NEWLINE]Second")
        self.assertEqual(properties.findtext("Authors"),
                         "First[NEWLINE]Second")

    def test_custom_files_checked(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        paths = {}
        for name in ("Rules.sql", "Script.lua", "Tool.exe"):
            paths[name] = os.path.join(tmp, name)
            open(paths[name], "w").close()
        os.makedirs(os.path.join(tmp, "other"))
        paths["again"] = os.path.join(tmp, "other", "Rules.sql")
        open(paths["again"], "w").close()
        new = modbuild.new_custom_file
        self.assertEqual(new(paths["Script.lua"])["action"],
                         "AddGameplayScripts")
        files, errors = modbuild.check_extra_files([new(paths["Rules.sql"])])
        self.assertEqual((files[0]["name"], errors),
                         ("Custom/Rules.sql", []))

        def error(entry, pattern):
            _, errors = modbuild.check_extra_files(
                [entry] if isinstance(entry, dict) else entry)
            self.assertRegex("\n".join(errors), pattern)
        error(new(os.path.join(tmp, "missing.sql")), "not found")
        error(new(""), "no file chosen")
        error(new(paths["Tool.exe"]), "Steam Workshop")
        error(dict(new(paths["Rules.sql"]), action="UpdateArt"),
              "unknown action")
        error(dict(new(paths["Script.lua"]), scope="FrontEnd"),
              "only works in a game")
        error(dict(new(paths["Rules.sql"]), criteria="Someday"),
              "unknown criteria")
        error(dict(new(paths["Rules.sql"]), load_order="soon"),
              "whole number")
        error([new(paths["Rules.sql"]), new(paths["again"])],
              "two custom files")

    def test_modinfo_custom_actions(self):
        custom = [{"name": "Custom/A.sql", "action": "UpdateDatabase",
                   "scope": "InGame", "load_order": 1100, "criteria": ""},
                  {"name": "Custom/B.sql", "action": "UpdateDatabase",
                   "scope": "InGame", "load_order": 1100, "criteria": ""},
                  {"name": "Custom/UI.xml", "action": "AddUserInterfaces",
                   "scope": "InGame", "load_order": 1100,
                   "criteria": "Expansion1AndBeyond"},
                  {"name": "Custom/Setup.sql", "action": "UpdateDatabase",
                   "scope": "FrontEnd", "load_order": 50, "criteria": ""}]
        root = ET.fromstring(modbuild.build_modinfo(
            "M", "d", "g", False, None, ["a"] + [f["name"] for f in custom],
            True, custom=custom))
        ingame = {a.get("id"): a for a in root.find("InGameActions")}
        both = ingame["InGameCustom2"]
        self.assertEqual([f.text for f in both.findall("File")],
                         ["Custom/A.sql", "Custom/B.sql"])
        ui = ingame["InGameCustom1"]
        self.assertEqual((ui.tag, ui.find("Properties/Context").text,
                          ui.find("Criteria").text),
                         ("AddUserInterfaces", "InGame",
                          "Expansion1AndBeyond"))
        front, = [a for a in root.find("FrontEndActions")
                  if a.get("id") == "FrontEndCustom1"]
        self.assertEqual(front.find("Properties/LoadOrder").text, "50")
        # (moments use the same criterion: defined once)
        self.assertEqual([c.get("id") for c in root.find("ActionCriteria")],
                         ["Expansion1AndBeyond"])

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


class MoodPortraitTest(unittest.TestCase):
    """Diplomacy portraits by mood: named entries of the fallback artdef
    (no game cache needed)."""

    # every animation the diplomacy screen asks a leader to play: the parts
    # and initial animations of LeaderAnimations' sequences, and the
    # statements' LeaderAnimation values
    GAME_ANIMATIONS = {
        "NEUTRAL_IDLE", "NEUTRAL_POSITIVE", "NEUTRAL_NEGATIVE",
        "HAPPY_IDLE", "HAPPY_POSITIVE", "HAPPY_NEGATIVE",
        "UNHAPPY_IDLE", "UNHAPPY_POSITIVE", "UNHAPPY_NEGATIVE",
        "TO_HAPPY", "TO_NEUTRAL", "TO_UNHAPPY", "NEUTRAL_GREETING",
        "NEUTRAL_TO_HAPPY", "NEUTRAL_TO_UNHAPPY", "UNHAPPY_TO_NEUTRAL",
        "ENRAGED", "KUDOS", "WARNING", "DECLARE_WAR_FROM_HUMAN",
        "DECLARE_WAR_FROM_AI", "FIRST_MEET", "DEFEAT"}

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="civgen_moods_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.happy = os.path.join(self.tmp, "happy.png")
        shutil.copy(MOMENT_IMAGE, self.happy)

    def normalize(self, **spec):
        s = leaders.new_leader_spec()
        s.update(name="Q", civ="CIVILIZATION_SUMERIA",
                 orig="LEADER_GILGAMESH", load_fg_path=MOMENT_IMAGE)
        s.update(spec)
        return leaders.normalize_spec(s, LoadingBackgroundTest.NoData(),
                                      "TST")

    def test_slots_cover_the_game(self):
        names = [name for slot in moods.MOOD_SLOTS for name in slot[5]]
        self.assertEqual(len(names), len(set(names)))
        self.assertIn("DEFAULT", names)
        self.assertEqual(self.GAME_ANIMATIONS - set(names), set())
        for i, slot in enumerate(moods.MOOD_SLOTS):     # no loops
            if slot[4]:
                self.assertLess(moods.SLOT_KEYS.index(slot[4]), i)

    def test_resolve(self):
        self.assertEqual(moods.resolve({"NEUTRAL": "N"}), [("DEFAULT", "N")])
        r = dict(moods.resolve({"NEUTRAL": "N", "HAPPY": "H"}))
        self.assertEqual([r[n] for n in ("DEFAULT", "TO_NEUTRAL",
                                         "UNHAPPY_IDLE", "NEUTRAL_POSITIVE")],
                         ["N"] * 4)
        self.assertEqual([r[n] for n in ("HAPPY_IDLE", "TO_HAPPY",
                                         "HAPPY_POSITIVE", "KUDOS")],
                         ["H"] * 4)
        r = dict(moods.resolve({"NEUTRAL": "N", "DECLARES_WAR": "W"}))
        self.assertEqual((r["DECLARE_WAR_FROM_AI"],
                          r["DECLARE_WAR_FROM_HUMAN"]), ("W", "N"))
        r = dict(moods.resolve({"NEUTRAL": "N", "ENRAGED": "E",
                                "UNHAPPY": "U"}))
        self.assertEqual((r["DECLARE_WAR_FROM_HUMAN"], r["WARNING"]),
                         ("E", "U"))

    def test_artdef(self):
        root = ET.fromstring(artdefs.build_fallback_artdef("Pkg", [
            ("LEADER_A", {"NEUTRAL": "FA"}),
            ("LEADER_B", {"NEUTRAL": "FB", "UNHAPPY": "UB"})]))
        found = {}
        for leader in root.find("m_RootCollections/Element").findall(
                "Element"):
            entries = leader.find("m_ChildCollections/Element").findall(
                "Element")
            names = [e.find("m_Name").get("text") for e in entries]
            self.assertEqual(len(names), len(set(names)))
            found[leader.find("m_Name").get("text")] = {
                e.find("m_Name").get("text"): e.find(
                    "m_Fields/m_Values/Element/m_EntryName").get("text")
                for e in entries}
        self.assertEqual(found["LEADER_A"], {"DEFAULT": "FA"})
        b = found["LEADER_B"]
        self.assertEqual((b["DEFAULT"], b["HAPPY_IDLE"], b["WARNING"],
                          b["UNHAPPY_NEGATIVE"]), ("FB", "FB", "UB", "UB"))

    def test_normalize(self):
        c = self.normalize()
        self.assertEqual((c["fallback_name"], c["mood_images"]),
                         ("FALLBACK_NEUTRAL_TST_Q", []))
        # slot order; one texture per picture, the portrait's is reused
        c = self.normalize(mood_images={
            "KUDOS": self.happy, "HAPPY": self.happy,
            "UNHAPPY": MOMENT_IMAGE, "WARNING": " "})
        self.assertEqual(c["mood_images"], [
            ("HAPPY", self.happy, "FALLBACK_HAPPY_TST_Q"),
            ("UNHAPPY", MOMENT_IMAGE, "FALLBACK_NEUTRAL_TST_Q"),
            ("KUDOS", self.happy, "FALLBACK_HAPPY_TST_Q")])
        with self.assertRaisesRegex(ValueError, "happy diplomacy portrait "
                                                "not found"):
            self.normalize(mood_images={"HAPPY": self.happy + ".gone"})
        for slot in ("NEUTRAL", "SMUG"):
            with self.assertRaisesRegex(ValueError, "not a diplomacy"):
                self.normalize(mood_images={slot: self.happy})
        with self.assertRaisesRegex(ValueError, "need a Portrait"):
            self.normalize(load_fg_path="", mood_images={"HAPPY": self.happy})
        mark = ("\U0001F3AD", "diplomacy portraits")
        self.assertIn(mark, leaders.leader_custom_marks(dict(
            leaders.new_leader_spec(), mood_images={"HAPPY": "a.png"})))
        self.assertNotIn(mark, leaders.leader_custom_marks(dict(
            leaders.new_leader_spec(), mood_images={"HAPPY": ""})))

    def test_build_art(self):
        """Each picture is converted once and the leader's slots point at
        it; one that cannot be read is dropped (the cooker is stubbed)."""
        from unittest import mock
        broken = os.path.join(self.tmp, "broken.png")
        with open(broken, "w") as fh:
            fh.write("not an image")
        c = self.normalize(mood_images={
            "HAPPY": self.happy, "KUDOS": self.happy, "UNHAPPY": broken})
        cooked = {}

        def cook_art(cooker, pantry, packages, fallbacks, mod_dir, report):
            cooked.update(packages=packages, fallbacks=fallbacks,
                          textures=sorted(os.listdir(os.path.join(
                              pantry, "Textures"))))
            return ["ArtDefs/FallbackLeaders.artdef"]

        report = []
        with mock.patch.object(modbuild, "cook_art", cook_art):
            modbuild.build_art([c], "Mod", self.tmp, report, "cooker.exe")
        self.assertEqual(cooked["fallbacks"], [("LEADER_TST_Q", {
            "NEUTRAL": "FALLBACK_NEUTRAL_TST_Q",
            "HAPPY": "FALLBACK_HAPPY_TST_Q",
            "KUDOS": "FALLBACK_HAPPY_TST_Q"})])
        self.assertEqual(cooked["packages"]["Mod_Fallbacks"], (
            "fallback", ["FALLBACK_NEUTRAL_TST_Q", "FALLBACK_HAPPY_TST_Q"]))
        self.assertIn("FALLBACK_HAPPY_TST_Q.dds", cooked["textures"])
        self.assertTrue(any("could not convert the unhappy diplomacy "
                            "portrait" in line and "the neutral one" in line
                            for line in report), report)

    def test_export_import(self):
        spec = dict(leaders.new_leader_spec(), name="Q",
                    mood_images={"HAPPY": self.happy})
        zip_path = os.path.join(self.tmp, "out.zip")
        project.export_leaders([spec], zip_path)
        os.remove(self.happy)           # imported elsewhere
        specs, _, _ = project.import_leaders(zip_path)
        moved = specs[0]["mood_images"]["HAPPY"]
        self.assertNotEqual(moved, self.happy)
        self.assertTrue(os.path.isfile(moved))


class UnitAtlasTest(unittest.TestCase):
    """A unique unit's custom icon and portrait share one atlas, portrait
    first (like the template mod's unit atlas)."""

    class NoData:
        conn = None

    civ = {"name": "X", "slug": "CIVILIZATION_X"}

    def normalize(self, **spec):
        u = uniques.new_unique_spec("unit")
        u.update(name="Y", base="UNIT_SWORDSMAN", **spec)
        return uniques.normalize_unique(u, self.civ, self.NoData())

    def test_atlas_and_definitions(self):
        from civgen.art import atlas_image
        u = self.normalize(icon_path=MOMENT_IMAGE, portrait_path=MOMENT_IMAGE)
        self.assertEqual(u["icon_defs"], [("ICON_UNIT_Y_PORTRAIT", 0),
                                          ("ICON_UNIT_Y", 1)])
        atlas, defs = leaders.icons_fragment(u, [(38, "ICON_UNIT_Y_38")])
        self.assertIn('IconSize="38" IconsPerRow="2" IconsPerColumn="1"',
                      atlas)
        self.assertIn('Name="ICON_UNIT_Y_PORTRAIT" Atlas="ICON_ATLAS_UNIT_Y"'
                      ' Index="0"', defs)
        self.assertIn('Name="ICON_UNIT_Y" Atlas="ICON_ATLAS_UNIT_Y" '
                      'Index="1"', defs)
        self.assertEqual(atlas_image(u["atlas_paths"], 38).size, (76, 38))
        # the copied icons: no icon, portrait or ethnicity portraits (the
        # game would show those before the unit's own portrait)
        sql = uniques.unique_icons_sql(u)
        self.assertNotIn("'ICON_UNIT_SWORDSMAN'", sql)
        self.assertNotIn("'ICON_UNIT_SWORDSMAN_PORTRAIT'", sql)
        self.assertNotIn("ETHNICITY", sql)
        self.assertIn("'ICON_UNIT_SWORDSMAN_FOW'", sql)

    def test_one_image_serves_both(self):
        u = self.normalize(icon_path=MOMENT_IMAGE)
        self.assertEqual(u["atlas_paths"], [MOMENT_IMAGE, MOMENT_IMAGE])
        u = self.normalize(portrait_path=MOMENT_IMAGE)
        self.assertTrue(u["icon_custom"])
        self.assertEqual(u["atlas_paths"], [MOMENT_IMAGE, MOMENT_IMAGE])
        u = self.normalize()
        self.assertFalse(u["icon_custom"])
        self.assertIn("ETHNICITY", uniques.unique_icons_sql(u))
        # other kinds keep their single icon
        b = uniques.new_unique_spec("building")
        b.update(name="Z", base="BUILDING_LIBRARY", icon_path=MOMENT_IMAGE)
        b = uniques.normalize_unique(b, self.civ, self.NoData())
        self.assertIsNone(b["icon_defs"])
        atlas, defs = leaders.icons_fragment(b, [(32, "T")])
        self.assertIn('IconsPerRow="1"', atlas)
        self.assertIn('Name="ICON_BUILDING_Z" Atlas="ICON_ATLAS_BUILDING_Z" '
                      'Index="0"', defs)


class WorkshopTest(unittest.TestCase):
    """Preparing a mod for the SDK's Steam Workshop uploader."""

    def setUp(self):
        from civgen import workshop
        self.ws = workshop
        self.leaders, self.civs = sample_project()
        self.tmp = tempfile.mkdtemp(prefix="civgen_ws_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_description(self):
        self.civs[0]["uniques"][1]["desc"] = "+4 [ICON_Faith] Faith."
        text = self.ws.generated_description("Amazons", self.civs,
                                             self.leaders)
        self.assertLessEqual(len(text), self.ws.MAX_DESCRIPTION)
        self.assertNotIn("[ICON_", text)
        self.assertIn("+4 Faith.", text)
        for name in ["Amazons", "Hippolyta", "Antiope", "Amazon Warrior",
                     "Sacred Grove"]:
            self.assertIn(name, text)
        plain = self.ws.plain_text(text)
        self.assertNotIn("[b]", plain)
        self.assertIn("- Amazon Warrior", plain)

    def test_preview(self):
        from PIL import Image
        self.civs[0]["icon_path"] = MOMENT_IMAGE
        path = self.ws.make_preview(os.path.join(self.tmp, "p.jpg"),
                                    "Amazons", self.civs, self.leaders)
        self.assertLess(os.path.getsize(path), self.ws.MAX_PREVIEW_BYTES)
        self.assertEqual(Image.open(path).size, (512, 512))

    def test_busy_preview(self):
        from PIL import Image
        self.civs[0]["icon_path"] = MOMENT_IMAGE
        self.civs[0]["uniques"][0]["portrait_path"] = MOMENT_IMAGE
        self.civs[0]["moment_illustrations"] = [
            {"item": "UNIT_X", "path": MOMENT_IMAGE}]
        self.leaders[0].update(load_fg_path=MOMENT_IMAGE,
                               load_bg_default=True, load_bg_hue=40)
        busy = self.ws.make_preview(os.path.join(self.tmp, "busy.jpg"),
                                    "Amazons", self.civs, self.leaders,
                                    style="busy")
        simple = self.ws.make_preview(os.path.join(self.tmp, "simple.jpg"),
                                      "Amazons", self.civs, self.leaders)
        self.assertEqual(Image.open(busy).size, (512, 512))
        self.assertLess(os.path.getsize(busy), self.ws.MAX_PREVIEW_BYTES)
        self.assertNotEqual(open(busy, "rb").read(),
                            open(simple, "rb").read())
        # nothing of the project's own to show: the simple preview
        leaders, civs = sample_project()
        empty_busy = self.ws.make_preview(os.path.join(self.tmp, "e1.jpg"),
                                          "X", civs, leaders, style="busy")
        empty_simple = self.ws.make_preview(os.path.join(self.tmp, "e2.jpg"),
                                            "X", civs, leaders)
        self.assertEqual(open(empty_busy, "rb").read(),
                         open(empty_simple, "rb").read())

    def test_transparent_images(self):
        """Transparent parts of the mod's images stay see-through in the
        busy preview (moment cards get no frame behind them)."""
        from PIL import Image, ImageDraw
        cut = os.path.join(self.tmp, "cut.png")
        img = Image.new("RGBA", (456, 332), (0, 0, 0, 0))
        ImageDraw.Draw(img).ellipse((100, 50, 350, 300), fill=(255, 0, 0))
        img.convert("P", palette=Image.ADAPTIVE).save(cut, transparency=0)
        opaque = os.path.join(self.tmp, "opaque.png")
        Image.new("RGB", (456, 332), (0, 0, 255)).save(opaque)
        card = self.ws._card({"path": cut}, 200, 0)
        self.assertEqual(card.getpixel((2, 2))[3], 0)     # no frame
        card = self.ws._card({"path": opaque}, 200, 0)
        self.assertEqual(card.getpixel((1, 1))[3], 255)   # framed photo
        # a see-through background is laid over the backdrop, not black
        bg = os.path.join(self.tmp, "bg.png")
        Image.new("RGBA", (64, 64), (0, 0, 0, 0)).save(bg)
        self.leaders[0].update(load_bg_path=bg, load_fg_path=MOMENT_IMAGE)
        path = self.ws.make_preview(os.path.join(self.tmp, "b.jpg"), "T",
                                    self.civs, self.leaders, style="busy")
        self.assertGreater(sum(Image.open(path).getpixel((5, 5))), 40)

    def test_settings(self):
        w = self.ws.normalize_workshop({"version": "x", "visibility": "?",
                                        "junk": 1})
        self.assertEqual((w["version"], w["visibility"]), (1, "Public"))
        self.assertEqual(w["preview_style"], "simple")
        self.assertEqual(self.ws.normalize_workshop(
            {"preview_style": "busy"})["preview_style"], "busy")
        self.assertNotIn("junk", w)
        values = self.ws.resolved({}, "My Mod", self.civs, self.leaders)
        self.assertEqual(values["title"], "My Mod")
        self.assertTrue(values["description"].startswith("[h1]My Mod"))
        self.assertEqual(self.ws.workshop_url(
            "https://steamcommunity.com/sharedfiles/filedetails/?id=123456789"),
            self.ws.WORKSHOP_URL.format("123456789"))
        self.assertIsNone(self.ws.workshop_url("not yet"))

    def test_modinfo(self):
        modinfo = modbuild.build_modinfo("M", "d", "g", False, None, [],
                                         version=3, authors="Me")
        root = ET.fromstring(modinfo)
        self.assertEqual(root.get("version"), "3")
        self.assertEqual(root.findtext("Properties/Authors"), "Me")
        self.assertEqual(root.findtext("Properties/AffectsSavedGames"), "1")

    def test_check_mod(self):
        mod = os.path.join(self.tmp, "Mod")
        os.makedirs(mod)
        open(os.path.join(mod, "Old.modinfo"), "w").close()
        guid = str(uuid.uuid4())
        with open(os.path.join(mod, "Mod.modinfo"), "w") as fh:
            fh.write(modbuild.build_modinfo("Mod", "d", guid, False, None,
                                            ["a.sql"]))
        os.remove(os.path.join(mod, "Old.modinfo"))
        # every file the .modinfo's actions load
        for rel in ["a.sql"] + [f.text for f in ET.parse(os.path.join(
                mod, "Mod.modinfo")).getroot().iter("File")]:
            os.makedirs(os.path.dirname(os.path.join(mod, rel)),
                        exist_ok=True)
            open(os.path.join(mod, rel), "w").close()
        with open(os.path.join(mod, self.ws.STAMP_FILE), "w") as fh:
            fh.write("abc")
        preview = self.ws.make_preview(os.path.join(self.tmp, "p.jpg"),
                                       "Mod", [], [])
        values = {"title": "Mod", "description": "Text",
                  "preview_path": preview}
        results = self.ws.check_mod(mod, values, stamp="abc")
        self.assertTrue(all(ok for ok, _ in results), results)

        def failed(**changes):
            return [m for ok, m in self.ws.check_mod(
                mod, dict(values, **changes), stamp="abc") if not ok]
        self.assertTrue(failed(title="x" * 129))
        self.assertTrue(failed(preview_path=""))
        self.assertEqual(len([m for ok, m in self.ws.check_mod(
            mod, values, stamp="new") if not ok]), 1)   # out of date
        open(os.path.join(mod, "art.zip"), "w").close()
        self.assertTrue(any("archives" in m for m in failed()))
        os.remove(os.path.join(mod, "art.zip"))
        os.remove(os.path.join(mod, "a.sql"))
        self.assertTrue(any("Missing" in m for m in failed()))


class ProjectFileTest(unittest.TestCase):
    """Projects are saved as JSON (*.civmod); older pickled *.altleader
    projects still open."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="civgen_proj_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        leaders, civs = sample_project()
        leaders[0]["primary"] = (10, 20, 30)
        leaders[0]["icon_crop"] = (100.5, 200.0, 80.0)
        self.project = {"mod_name": "Amazons", "prefix": "TST",
                        "output_dir": "C:/out", "guid": str(uuid.uuid4()),
                        "leaders": leaders, "civs": civs,
                        "workshop": {"version": 2},
                        "extra_files": [modbuild.new_custom_file(
                            "C:/mine/Rules.sql")]}

    def test_round_trip(self):
        path = os.path.join(self.tmp, "a" + project.PROJECT_EXT)
        project.save_project(self.project, path)
        with open(path, encoding="utf-8") as fh:
            saved = json.load(fh)               # plain JSON on disk
        self.assertEqual(saved["magic"], project.PROJECT_MAGIC)
        self.assertEqual(saved["version"], project.PROJECT_VERSION)
        loaded, version = project.load_project(path)
        self.assertEqual(version, project.PROJECT_VERSION)
        self.assertEqual(loaded, self.project)  # tuples are tuples again
        self.assertIsInstance(loaded["leaders"][0]["primary"], tuple)
        self.assertFalse(os.path.exists(path + ".tmp"))
        self.assertEqual(project.project_path_for(path), path)

    def test_older_pickled_project(self):
        import pickle
        old = dict(self.project, magic=project.LEGACY_MAGIC, version=3)
        del old["civs"]                         # older still: no civs
        del old["extra_files"]                  # (nor custom files)
        path = os.path.join(self.tmp, "old" + project.LEGACY_EXT)
        with open(path, "wb") as fh:
            pickle.dump(old, fh)
        loaded, version = project.load_project(path)
        self.assertEqual((version, loaded["civs"], loaded["extra_files"]),
                         (3, [], []))
        self.assertEqual(project.project_path_for(path),
                         os.path.join(self.tmp, "old" + project.PROJECT_EXT))
        # a pickle under another name is never unpickled
        other = os.path.join(self.tmp, "sneaky" + project.PROJECT_EXT)
        shutil.copy(path, other)
        with self.assertRaisesRegex(ValueError, "not a project"):
            project.load_project(other)

    def test_bad_files(self):
        path = os.path.join(self.tmp, "bad" + project.PROJECT_EXT)
        with open(path, "w") as fh:
            fh.write('{"magic": ')
        with self.assertRaisesRegex(ValueError, "damaged"):
            project.load_project(path)
        with open(path, "w") as fh:
            json.dump({"magic": "something else", "leaders": []}, fh)
        with self.assertRaisesRegex(ValueError, "does not look"):
            project.load_project(path)
        with open(path, "w") as fh:
            json.dump({"magic": project.PROJECT_MAGIC, "leaders": [],
                       "extra_files": ["Rules.sql"]}, fh)
        with self.assertRaisesRegex(ValueError, "custom file"):
            project.load_project(path)
        self.assertEqual(project.json_ready({"c": (1, 2)}), {"c": [1, 2]})


class DescriptionTest(unittest.TestCase):
    """Descriptions written from effects (and a unique's changes)."""

    def test_effects(self):
        e1 = modifiers.new_effect("city_yield")
        e1["args"].update(YieldType="YIELD_FAITH", Amount="2")
        e2 = modifiers.new_effect("combat_strength")
        e2["args"]["Amount"] = "5"
        text = modifiers.describe_effects(
            [e1, e2], lambda kind, t: {"YIELD_FAITH": "Faith"}.get(t, t))
        self.assertEqual(text.split("\n"), [
            "+2 [ICON_Faith] Faith in every city.",
            "+5 [ICON_Strength] Combat Strength."])
        # existing icons and tags are left alone
        self.assertEqual(modifiers.with_icons("+1 [ICON_Food] Food, ICON_Gold"),
                         "+1 [ICON_Food] Food, ICON_Gold")
        self.assertEqual(modifiers.sentence(": +1 Gold"), "+1 Gold.")

    @unittest.skipUnless(CACHE, "needs the game cache")
    def test_unique(self):
        leaders, civs = sample_project()
        unit, temple = civs[0]["uniques"][:2]
        unit["stats"]["Maintenance"] = "0"
        text = uniques.describe_unique(unit, game_data()).split("\n")
        self.assertEqual(text[0], "Replaces the Swordsman.")
        self.assertIn("+5 [ICON_Strength] Combat strength (compared to the "
                      "Swordsman).", text)
        self.assertTrue(any(line.startswith("Maintenance costs") and
                            "less [ICON_Gold] Gold per turn than the "
                            "Swordsman" in line for line in text))
        if gathering_storm_cache():     # (the Swordsman's cost is known)
            self.assertIn("Costs 10 less [ICON_RESOURCE_IRON] Iron than the "
                          "Swordsman.", text)
            self.assertIn("Maintenance costs 1 [ICON_RESOURCE_HORSES] "
                          "Horses per turn.", text)
        text = uniques.describe_unique(temple, game_data())
        self.assertIn("+4 [ICON_Faith] Faith.", text)
        arena = civs[0]["uniques"][3]
        self.assertIn("Costs 60 [ICON_Production] Production.",
                      uniques.describe_unique(arena, game_data()))


class ReferenceTest(unittest.TestCase):
    """References to the project's own uniques follow prefix changes and
    renames, and a stale one stops generation instead of breaking the
    game."""

    class NoData:
        conn = None
        items = {}

        def item(self, kind, t):
            return None

    def setUp(self):
        from civgen import references
        self.refs = references
        self.leaders, self.civs = sample_project()
        self.civs[0]["moment_illustrations"] = [
            {"item": "UNIT_AMAZON_WARRIOR", "path": MOMENT_IMAGE},  # stale
            {"item": "UNIT_XX_AMAZON_WARRIOR", "path": MOMENT_IMAGE}]

    def test_repair(self):
        fixed = self.refs.repair(self.leaders, self.civs, "TST",
                                 game_data() if CACHE else self.NoData())
        items = [m["item"] for m in self.civs[0]["moment_illustrations"]]
        if CACHE:
            self.assertEqual(items, ["UNIT_TST_AMAZON_WARRIOR"] * 2)
            self.assertEqual(len(fixed), 2)
        # what is already right is left alone
        hall = self.civs[0]["uniques"][4]
        self.assertEqual(hall["stats"]["PrereqDistrict"],
                         "DISTRICT_TST_AMAZON_ARENA")

    def test_repair_without_the_game(self):
        # a bare type could be the game's: only prefixed forms are fixed
        self.refs.repair(self.leaders, self.civs, "TST", self.NoData())
        self.assertEqual([m["item"] for m in
                          self.civs[0]["moment_illustrations"]],
                         ["UNIT_AMAZON_WARRIOR", "UNIT_TST_AMAZON_WARRIOR"])

    def test_game_types_are_not_touched(self):
        if not CACHE:
            self.skipTest("needs the game cache")
        unit = self.civs[0]["uniques"][0]
        unit["name"] = "Warrior"                # like the game's own
        self.civs[0]["moment_illustrations"] = [
            {"item": "UNIT_WARRIOR", "path": MOMENT_IMAGE}]
        self.assertEqual(self.refs.repair(self.leaders, self.civs, "TST",
                                          game_data()), [])

    def test_prefix_change_and_retarget(self):
        mapping = self.refs.prefix_change(self.civs, "TST", "SZ")
        self.assertEqual(mapping["DISTRICT_TST_AMAZON_ARENA"],
                         "DISTRICT_SZ_AMAZON_ARENA")
        self.refs.retarget(self.civs, mapping)
        self.assertEqual(self.civs[0]["uniques"][4]["stats"]
                         ["PrereqDistrict"], "DISTRICT_SZ_AMAZON_ARENA")
        self.assertEqual(self.civs[0]["uniques"][4]["name"],
                         "Hall of Heroines")   # texts are left alone

    def test_stale_reference_stops_generation(self):
        self.civs[0]["moment_illustrations"] = [
            {"item": "UNIT_TST_NOT_THERE", "path": MOMENT_IMAGE}]
        self.civs[0]["uniques"][4]["stats"]["PrereqDistrict"] = \
            "DISTRICT_TST_GONE"
        _, _, errors = modbuild.prepare_project(
            self.leaders, self.civs, game_data() if CACHE else
            self.NoData(), "TST")
        self.assertTrue(any("UNIT_TST_NOT_THERE" in e for e in errors)
                        or not CACHE, errors)
        self.assertTrue(any("DISTRICT_TST_GONE" in e for e in errors)
                        or not CACHE, errors)


@unittest.skipUnless(CACHE, "needs the game cache")
class CopiedEffectsTest(unittest.TestCase):
    """A unique's copied item: its yields, great person points and
    effects, to copy into the editor or leave out."""

    def test_numbers_and_effects(self):
        data = game_data()
        self.assertEqual(data.base_numbers("building", "BUILDING_MARKET",
                                           "yields"), {"YIELD_GOLD": 2})
        self.assertEqual(data.base_numbers("building", "BUILDING_MARKET",
                                           "gpp"),
                         {"GREAT_PERSON_CLASS_MERCHANT": 1})
        mod, = [m for m in data.base_effects("building", "BUILDING_MARKET")
                if m["id"] == "MARKET_TRADE_ROUTE_CAPACITY"]
        effect = modifiers.effect_from_game(mod)
        self.assertEqual((effect["template"], effect["args"]["Amount"]),
                         ("trade_capacity", "1"))
        self.assertEqual(modifiers.describe_game_modifier(mod),
                         "+1 Trade Route capacity")
        # one no template expresses becomes a raw (advanced) effect
        grant = [m for m in data.base_effects("building", "BUILDING_BARRACKS")
                 if m["modifier_type"] ==
                 "MODIFIER_SINGLE_CITY_GRANT_ABILITY_FOR_TRAINED_UNITS"][0]
        effect = modifiers.effect_from_game(grant, "building")
        self.assertTrue(modifiers.is_raw(effect))
        self.assertIn("AbilityType", effect["args"])
        self.assertIn("AbilityType", modifiers.describe_game_modifier(grant))
        # a unit template on another owner would become a granted one
        combat = {"id": "X", "modifier_type":
                  "MODIFIER_UNIT_ADJUST_COMBAT_STRENGTH",
                  "args": {"Amount": "5"}, "run_once": False,
                  "permanent": False, "subject_reqs": [], "owner_reqs": []}
        self.assertEqual(modifiers.effect_from_game(combat, "unit")[
            "template"], "combat_strength")
        self.assertTrue(modifiers.is_raw(
            modifiers.effect_from_game(combat, "trait")))

    def test_every_game_effect_round_trips(self):
        """Each of the game's ability and belief modifiers, copied into an
        ability, is written back as it was."""
        data = game_data()
        mods = [m for source in ("trait", "belief")
                for item, _ in data.source_items(source)
                for m in data.game_modifiers(source, item)]
        self.assertGreater(len(mods), 500)
        effects = [modifiers.effect_from_game(m, "trait") for m in mods]
        for effect in effects:
            modifiers.check_effect(effect, "trait", data)
        sql, _ = modifiers.effects_sql("trait", "TRAIT_TST_COPY", effects,
                                       "Copy", data.type_name)
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        db = database("DebugGameplay.sqlite", tmp)
        self.addCleanup(db.close)
        db.executescript("BEGIN; INSERT INTO Types (Type, Kind) VALUES "
                         "('TRAIT_TST_COPY', 'KIND_TRAIT');"
                         "INSERT INTO Traits (TraitType) VALUES "
                         "('TRAIT_TST_COPY');" + sql + "COMMIT;")
        self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(),
                         [])
        for n, (mod, effect) in enumerate(zip(mods, effects), 1):
            if not modifiers.is_raw(effect):
                continue
            mod_id = "TST_COPY_MOD_{}".format(n)
            row = db.execute("SELECT ModifierType, RunOnce, Permanent FROM "
                             "Modifiers WHERE ModifierId = ?",
                             (mod_id,)).fetchone()
            self.assertEqual(row, (mod["modifier_type"],
                                   int(mod["run_once"]),
                                   int(mod["permanent"])), mod["id"])
            args = dict(db.execute("SELECT Name, Value FROM "
                                   "ModifierArguments WHERE ModifierId = ?",
                                   (mod_id,)).fetchall())
            self.assertEqual(args, mod["args"], mod["id"])
            for key, target in (("subject_reqs", "Subject"),
                                ("owner_reqs", "Owner")):
                found = db.execute(
                    "SELECT COUNT(*) FROM RequirementSetRequirements r JOIN "
                    "Modifiers m ON r.RequirementSetId = m.{}"
                    "RequirementSetId WHERE m.ModifierId = ?".format(target),
                    (mod_id,)).fetchone()[0]
                self.assertEqual(found, len(mod[key]), mod["id"])

    def test_skipped_effects_are_not_copied(self):
        u = uniques.new_unique_spec("building")
        u.update(name="Bazaar", base="BUILDING_MARKET",
                 skip_effects=["MARKET_TRADE_ROUTE_CAPACITY"])
        ctx = uniques.normalize_unique(
            u, {"name": "X", "slug": "CIVILIZATION_X"}, game_data(), "TST")
        sql, _, _ = uniques.unique_sql(ctx, game_data().type_name)
        self.assertIn("ModifierId NOT IN ('MARKET_TRADE_ROUTE_CAPACITY')",
                      sql)
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        db = database("DebugGameplay.sqlite", tmp)
        self.addCleanup(db.close)
        db.executescript(
            "INSERT INTO Types (Type, Kind) VALUES ('CIVILIZATION_X', "
            "'KIND_CIVILIZATION');"
            "INSERT INTO Civilizations (CivilizationType, Name, Description,"
            " Adjective, StartingCivilizationLevelType) VALUES "
            "('CIVILIZATION_X', 'X', 'X', 'X', 'CIVILIZATION_LEVEL_FULL_CIV');"
            + sql)
        self.assertEqual(db.execute(
            "SELECT ModifierId FROM BuildingModifiers WHERE BuildingType = "
            "'BUILDING_TST_BAZAAR'").fetchall(), [])


class EffectFormsTest(unittest.TestCase):
    """Raw effects, raw and grouped requirements and attached effects
    (the advanced effect editor's); no game needed."""

    class FakeData:
        """Game data that knows a few modifiers and requirement sets."""
        conn = True

        def has_modifier_type(self, t):
            return t != "MODIFIER_NOPE"

        def has_requirement_type(self, t):
            return t != "REQUIREMENT_NOPE"

        def is_attach(self, t):
            return "ATTACH" in t

        def has_modifier(self, mod_id):
            return mod_id == "GAME_MODIFIER"

        def has_requirement_set(self, set_id):
            return set_id == "GAME_SET"

    def test_summaries(self):
        self.assertEqual(
            modifiers.summary(attaching_effect()),
            "Cities attach modifier: +10% Production in this city (only "
            "if: any of (City has district Campus; City has building "
            "Library))")
        gold = modifiers.new_raw_effect(
            "MODIFIER_PLAYER_GRANT_YIELD",
            {"Amount": "100", "YieldType": "YIELD_GOLD"})
        self.assertEqual(modifiers.summary(gold),
                         "Grant yield: Amount 100, YieldType Gold")
        gold["text"] = "+100 Gold"
        self.assertEqual(modifiers.summary(gold), "+100 Gold")
        yields = modifiers.new_effect("city_yield")
        yields["reqs"] = [{"preset": "city_district",
                           "value": "DISTRICT_CAMPUS"},
                          {"type": "REQUIREMENT_PLOT_IS_HILLS", "not": True}]
        self.assertEqual(modifiers.summary(yields),
                         "+1 Production in every city (only if: City has "
                         "district Campus; not: Plot is hills)")
        yields["set_types"] = {"subject": "ANY"}
        self.assertEqual(modifiers.summary(yields),
                         "+1 Production in every city (only if: any of "
                         "(City has district Campus; not: Plot is hills))")

    def test_is_advanced(self):
        effect = modifiers.new_effect("city_yield")
        self.assertFalse(modifiers.is_advanced(effect))
        effect["reqs"] = [{"preset": "has_tech", "value": "TECH_WRITING"}]
        self.assertFalse(modifiers.is_advanced(effect))
        self.assertTrue(modifiers.is_advanced(
            dict(effect, set_types={"owner": "ANY"})))
        self.assertFalse(modifiers.is_advanced(
            dict(effect, set_types={"owner": "ALL"})))
        self.assertTrue(modifiers.is_advanced(dict(effect, reqs=[
            {"type": "REQUIREMENT_PLOT_IS_HILLS"}])))
        self.assertTrue(modifiers.is_advanced(attaching_effect()))
        self.assertTrue(modifiers.is_advanced(modifiers.new_raw_effect(
            "MODIFIER_PLAYER_GRANT_YIELD")))

    def test_checks(self):
        check = modifiers.check_effect
        check(attaching_effect(), "trait")
        check(attaching_effect(), "building")

        def fails(effect, pattern, owner="trait", data=None):
            with self.assertRaisesRegex(ValueError, pattern):
                check(effect, owner, data)
        raw = modifiers.new_raw_effect
        fails(raw(""), "modifier type")
        fails(raw("modifier_lower"), "modifier type")
        fails(raw("MODIFIER_X", {"Amount": " "}), "no value")
        fails(raw("MODIFIER_X", {"1st": "1"}), "argument name")
        fails(dict(raw("MODIFIER_X"), set_types={"subject": "MOST"}),
              "requirement set")
        fails(dict(raw("MODIFIER_X"), columns={"Bogus": 1}), "column")
        fails(dict(raw("MODIFIER_X"), strings={"Bogus": "LOC_X"}), "text")
        fails(dict(raw("MODIFIER_X"), arg_types={"A": {"Type": "Bogus"}}),
              "type of argument")
        group = {"group": "ANY", "reqs": []}
        fails(dict(raw("MODIFIER_X"), reqs=[group]), "empty group")
        group["reqs"] = [{"group": "ALL", "reqs": [
            {"type": "REQUIREMENT_PLOT_IS_HILLS"}]}]
        fails(dict(raw("MODIFIER_X"), reqs=[group]), "another group")
        fails(dict(raw("MODIFIER_X"), reqs=[{"group": "SOME", "reqs": [
            {"type": "REQUIREMENT_PLOT_IS_HILLS"}]}]), "'ALL' or 'ANY'")
        fails(dict(raw("MODIFIER_X"), reqs=[{"type": ""}]), "type")
        fails(dict(raw("MODIFIER_X"), reqs=[{
            "type": "REQUIREMENT_X", "target": "nobody"}]), "target")
        fails(dict(raw("MODIFIER_X"), reqs=[{
            "type": "REQUIREMENT_X", "args": {"A": ""}}]), "a value")
        # (a template's owner checks still apply)
        fails(modifiers.new_effect("free_unit"), "cannot be used here")
        # effects attaching effects attaching ...
        deep = modifiers.new_effect("city_yield")
        for _ in range(modifiers.MAX_DEPTH + 1):
            deep = dict(raw("MODIFIER_PLAYER_CITIES_ATTACH_MODIFIER"),
                        attached=deep)
        fails(deep, "deep")

    def test_checks_with_game_data(self):
        data, raw = self.FakeData(), modifiers.new_raw_effect

        def fails(effect, pattern):
            with self.assertRaisesRegex(ValueError, pattern):
                modifiers.check_effect(effect, "trait", data)
        fails(raw("MODIFIER_NOPE"), "no modifier type")
        fails(raw("MODIFIER_X_ATTACH"), "needs the effect it attaches")
        fails(raw("MODIFIER_X_ATTACH", {"ModifierId": "OTHER"}),
              "no modifier OTHER")
        modifiers.check_effect(raw("MODIFIER_X_ATTACH",
                                   {"ModifierId": "GAME_MODIFIER"}),
                               "trait", data)
        fails(dict(raw("MODIFIER_GRANT"),
                   attached=modifiers.new_effect("city_yield")),
              "does not attach")
        fails(dict(raw("MODIFIER_X"), reqs=[{"type": "REQUIREMENT_NOPE"}]),
              "no requirement type")
        nested = {"type": modifiers.NESTED_SET,
                  "args": {"RequirementSetId": "NOPE"}}
        fails(dict(raw("MODIFIER_X"), reqs=[nested]), "no requirement set")
        nested["args"]["RequirementSetId"] = "GAME_SET"
        modifiers.check_effect(dict(raw("MODIFIER_X"), reqs=[nested]),
                               "trait", data)
        # without the game data, anything may be the game's
        modifiers.check_effect(raw("MODIFIER_NOPE"), "trait",
                               NewLeaderTest.NoData())

    def test_sql(self):
        sql, texts = modifiers.effects_sql("trait", "TRAIT_X",
                                           [attaching_effect()], "X")
        self.assertIn("('X_MOD_1', 'ModifierId', 'ARGTYPE_IDENTITY', "
                      "'X_MOD_1_ATTACHED')", sql)
        self.assertIn("('X_MOD_1_SUBJECT_REQS_1_SET', "
                      "'REQUIREMENTSET_TEST_ANY')", sql)
        self.assertIn("('X_MOD_1_SUBJECT_REQS', 'REQUIREMENTSET_TEST_ALL')",
                      sql)
        self.assertIn("('X_MOD_1_SUBJECT_REQS_1', 'RequirementSetId', "
                      "'ARGTYPE_IDENTITY', 'X_MOD_1_SUBJECT_REQS_1_SET')", sql)
        # only the attaching effect belongs to the ability
        self.assertEqual(sql.count("INSERT INTO TraitModifiers"), 1)
        self.assertEqual(texts, [])
        # a template's unit effect that is attached is not granted through
        # a unit ability (the attaching effect picks the units)
        units = dict(modifiers.new_raw_effect(
            "MODIFIER_PLAYER_UNITS_ATTACH_MODIFIER"),
            attached=modifiers.new_effect("combat_strength"))
        sql, _ = modifiers.effects_sql("trait", "TRAIT_X", [units], "X")
        self.assertNotIn("GRANT_ABILITY", sql)
        self.assertIn("('X_MOD_1_ATTACHED', 'Preview'", sql)

    def test_game_text_is_kept(self):
        """A copied adjacency's tooltip names the game's own text."""
        effect = modifiers.new_effect("district_adjacency")
        effect["args"].update(DistrictType="DISTRICT_CAMPUS",
                              Description="LOC_DISTRICT_SOMETHING")
        sql, texts = modifiers.effects_sql("trait", "TRAIT_X", [effect], "X")
        self.assertIn("'Description', 'ARGTYPE_IDENTITY', "
                      "'LOC_DISTRICT_SOMETHING'", sql)
        self.assertEqual(texts, [])


class LeaderUniquesTest(unittest.TestCase):
    """Uniques of a leader's own (no game needed)."""

    class NoData(NewLeaderTest.NoData):
        items = {}

        def item(self, kind, t):
            return None

        def leader_unique_items(self, leader):
            return []

        def uniques_for(self, civ, leader):
            return []

    def test_trait_and_sql(self):
        u = uniques.new_unique_spec("building")
        u.update(name="War Lodge", base="BUILDING_BARRACKS")
        ctx = uniques.normalize_unique(
            u, {"name": "Liberty", "slug": "LEADER_TST_LIBERTY",
                "owner": "leader"}, NewItemTest.NoData(), "TST")
        self.assertEqual((ctx["trait"], ctx["label"]),
                         ("TRAIT_LEADER_BUILDING_TST_WAR_LODGE",
                          "War Lodge (Liberty)"))
        sql, _, _ = uniques.unique_sql(ctx, lambda kind, t: t)
        self.assertIn("INSERT INTO LeaderTraits (LeaderType, TraitType)\n"
                      "VALUES ('LEADER_TST_LIBERTY', "
                      "'TRAIT_LEADER_BUILDING_TST_WAR_LODGE');", sql)
        self.assertNotIn("CivilizationTraits", sql)
        # (a civilization's, as before)
        ctx = uniques.normalize_unique(u, NewItemTest.civ,
                                       NewItemTest.NoData(), "TST")
        self.assertEqual(ctx["trait"],
                         "TRAIT_CIVILIZATION_BUILDING_TST_WAR_LODGE")

    def test_leader_spec(self):
        leader_specs, _ = sample_project()
        jeanne = leader_specs[0]
        c = leaders.normalize_spec(jeanne, self.NoData(), "TST")
        self.assertEqual([u["slug"] for u in c["uniques"]],
                         ["UNIT_TST_PUCELLE_GUARD"])
        self.assertIn("SELECT Domain, CivilizationType, LeaderType, "
                      "'UNIT_TST_PUCELLE_GUARD'", leaders.config_block(c))
        twice = dict(jeanne, uniques=jeanne["uniques"] * 2)
        with self.assertRaisesRegex(ValueError, "two uniques have the type"):
            leaders.normalize_spec(twice, self.NoData(), "TST")
        self.assertIn(("\u2694", "uniques"),
                      leaders.leader_custom_marks(jeanne))

    def test_references_export_and_workshop(self):
        from civgen import references, workshop
        leader_specs, civ_specs = sample_project()
        mapping = references.prefix_change(civ_specs, "TST", "SZ",
                                           leader_specs)
        self.assertEqual(mapping["UNIT_TST_PUCELLE_GUARD"],
                         "UNIT_SZ_PUCELLE_GUARD")
        self.assertIn("UNIT_TST_AMAZON_WARRIOR", mapping)
        jeanne = leader_specs[0]
        jeanne["uniques"][0]["icon_path"] = "C:/art/guard.png"
        holders = project._spec_images(jeanne)
        self.assertIn((jeanne["uniques"][0], "icon_path"), holders)
        self.assertIn((jeanne, "load_fg_path"), holders)
        self.assertNotIn((civ_specs[0], "load_fg_path"),
                         project._spec_images(civ_specs[0]))
        text = workshop.generated_description("Amazons", civ_specs,
                                              leader_specs)
        self.assertIn("Pucelle Guard", text)
        self.assertIn("War Lodge", text)


class OwnAgendaTest(unittest.TestCase):
    """An agenda of a leader's own (advanced mode); no game needed."""

    def normalize(self, own, **spec):
        s = leaders.new_leader_spec()
        s.update(name="Liberty", civ="CIVILIZATION_AMERICA", orig="",
                 new_ability={"name": "Torch"}, own_agenda=own)
        s.update(spec)
        return leaders.normalize_spec(s, NewLeaderTest.NoData(), "TST")

    def test_a_new_leader_may_have_only_its_own_agenda(self):
        c = self.normalize(own_agenda())
        self.assertEqual((c["agenda"], c["agenda_clone"],
                          c["agenda_name"]),
                         ("", False, "Queen of the Steppe"))
        sql = leaders.agenda_block(c)
        self.assertIn("INSERT INTO HistoricalAgendas (LeaderType, "
                      "AgendaType)\nVALUES ('LEADER_TST_LIBERTY', "
                      "'AGENDA_TST_LIBERTY');", sql)
        self.assertIn("'TRAIT_AGENDA_TST_LIBERTY', 'KIND_TRAIT'", sql)
        self.assertEqual(sql.count("INSERT INTO TraitModifiers"), 3)
        self.assertIn("('AGENDA_TST_LIBERTY_MOD_1', 'InitialValue', "
                      "'ARGTYPE_IDENTITY', '8')", sql)
        rows = "\n".join(leaders.text_rows(c))
        self.assertIn("'LOC_AGENDA_TST_LIBERTY_NAME', 'Queen of the "
                      "Steppe'", rows)
        self.assertIn("'LOC_AGENDA_TST_LIBERTY_REACTION_2_REASON', "
                      "'Distrusts neighbors who rule differently'", rows)
        # a game agenda and its text are not used then
        c = self.normalize(own_agenda(), agenda="AGENDA_IRON_CROWN",
                           agenda_name="Old")
        self.assertEqual((c["agenda"], c["agenda_name"]),
                         ("", "Queen of the Steppe"))

    def test_mistakes(self):
        def fails(own, pattern):
            with self.assertRaisesRegex(ValueError, pattern):
                self.normalize(own)
        fails(dict(own_agenda(), name=" "), "give the agenda .* a name")
        fails(dict(own_agenda(), reactions=[]), "at least one like")
        for change, pattern in (({"value": "lots"}, "whole number"),
                                ({"value": "0"}, "cannot be 0"),
                                ({"text": ""}, "diplomacy screen"),
                                ({"reqs": [{"preset": "has_tech",
                                            "value": "TECH_WRITING"}]},
                                 "requirement types"),
                                ({"reqs": [{"type": "plot"}]},
                                 "REQUIREMENT_")):
            reaction = dict(own_agenda()["reactions"][0], **change)
            fails(dict(own_agenda(), reactions=[reaction]),
                  "Liberty: like / dislike 1 of its agenda - .*" + pattern)
        # without an agenda of either kind
        with self.assertRaisesRegex(ValueError, "needs an AI agenda"):
            self.normalize(None)

    def test_events(self):
        """A like or dislike of an event is written like the game's own:
        the event Triggered, the civilization met at all, the opinion
        fading - and the value a plain number."""
        culture, _, backstab = own_agenda()["reactions"]
        self.assertTrue(agendas.is_event(backstab))
        self.assertFalse(agendas.is_event(culture))
        effect = agendas.reaction_effect(backstab, "LOC_T", "LOC_R")
        self.assertEqual(effect["args"], {
            "InitialValue": "12", "SimpleModifierDescription": "LOC_T",
            "StatementKey": "LOC_R", "ReductionTurns": "10",
            "ReductionValue": "-1"})
        self.assertEqual([(r["type"], r.get("columns"))
                          for r in effect["reqs"]],
                         [("REQUIREMENT_CIVILIZATION_LEVEL", None),
                          ("REQUIREMENT_PLAYER_HAS_MET", None),
                          ("REQUIREMENT_PLAYER_DECLARED_WAR",
                           {"Triggered": 1})])
        sql, _ = modifiers.effects_sql("trait", "TRAIT_AGENDA_X", [effect],
                                       "X")
        self.assertIn("(RequirementId, RequirementType, Inverse, Triggered) "
                      "VALUES ('AGENDA_X_MOD_1_SUBJECT_REQS_3', "
                      "'REQUIREMENT_PLAYER_DECLARED_WAR', 0, 1)", sql)
        effect = agendas.reaction_effect(dict(backstab, fade_turns="20"),
                                         "LOC_T", "LOC_R")
        self.assertEqual(effect["args"]["ReductionTurns"], "20")
        # a state: met long enough, no fading
        effect = agendas.reaction_effect(culture, "LOC_T", "LOC_R")
        self.assertNotIn("ReductionTurns", effect["args"])
        self.assertEqual(effect["reqs"][1]["type"],
                         "REQUIREMENT_PLAYER_MET_X_TURNS_AGO")
        self.assertNotIn("columns", effect["reqs"][2])
        for turns in ("0", "soon"):
            with self.assertRaisesRegex(ValueError, "fades by 1"):
                agendas.check_reaction(dict(backstab, fade_turns=turns))
        self.assertEqual(agendas.reaction_summary(backstab),
                         "+12 when: Declared war (WarType Surprise War), "
                         "fading by 1 every 10 turns - \"Admires bold "
                         "strikes\"")

    def test_summary_and_marks(self):
        culture, neighbors, _ = own_agenda()["reactions"]
        self.assertEqual(agendas.reaction_summary(culture),
                         "+8 if: Has more of a yield (MinimumDelta 5, "
                         "YieldRatio 1.15, YieldType Culture) - \"Admires "
                         "cultured civilizations\"")
        self.assertTrue(agendas.reaction_summary(neighbors).startswith(
            "-6 if: Is a neighbor; not: Has the same government"))
        self.assertEqual(agendas.reaction_summary(
            {"value": "3", "reqs": [], "text": "Hi"}),
            "+3 (every civilization met) - \"Hi\"")
        spec = leaders.new_leader_spec()
        self.assertNotIn(("\U0001F3AF", "agenda"),
                         leaders.leader_custom_marks(spec))
        spec["own_agenda"] = own_agenda()
        self.assertIn(("\U0001F3AF", "agenda"),
                      leaders.leader_custom_marks(spec))


@unittest.skipUnless(CACHE and GAME_DIR, "needs the game and its cache")
class EffectGameDataTest(unittest.TestCase):
    """The game data the advanced effect editor offers and checks."""

    def test_schema(self):
        data = game_data()
        self.assertGreater(len(data.modifier_types()), 500)
        self.assertGreater(len(data.requirement_types()), 200)
        for t in ("MODIFIER_PLAYER_CITIES_ATTACH_MODIFIER",
                  "MODIFIER_ALL_PLAYERS_ATTACH_MODIFIER"):
            self.assertTrue(data.is_attach(t), t)
        self.assertFalse(data.is_attach("MODIFIER_PLAYER_GRANT_YIELD"))
        names = [a[0] for a in data.modifier_args(
            "MODIFIER_PLAYER_GRANT_YIELD")]
        self.assertIn("Amount", names)
        self.assertIn("YieldType", names)
        self.assertEqual(data.requirement_args(
            "REQUIREMENT_PLOT_TERRAIN_TYPE_MATCHES")[0][0], "TerrainType")
        self.assertTrue(data.source_items("belief"))
        self.assertTrue(data.type_choices("ability"))
        # the agenda conditions that are events are the game's
        db = sqlite3.connect(CACHE)
        self.addCleanup(db.close)
        triggered = {t for (t,) in db.execute(
            "SELECT DISTINCT RequirementType FROM Requirements WHERE "
            "Triggered = 1 AND RequirementId NOT LIKE '%RFVS%' AND "
            "RequirementId NOT LIKE '%TST%'")}
        if gathering_storm_cache():
            self.assertLessEqual(agendas.EVENT_CONDITIONS, triggered)
        # the arguments of templates are those the game gives their types
        for t in modifiers.TEMPLATES.values():
            mined = {a[0] for a in data.modifier_args(t.modifier_type)}
            for a in t.args:
                if mined and a.kind not in ("text", "fixed"):
                    self.assertIn(a.name, mined, t.id)

    def test_prepare_reports_bad_effects(self):
        leader_specs, civ_specs = sample_project()
        civ_specs[0]["ability"]["effects"].append(
            modifiers.new_raw_effect("MODIFIER_NOPE"))
        _, _, errors = modbuild.prepare_project(leader_specs, civ_specs,
                                                game_data(), "TST")
        self.assertIn("Amazons (civilization ability): effect 5 - the game "
                      "has no modifier type MODIFIER_NOPE",
                      "\n".join(errors))
        leader_specs, civ_specs = sample_project()
        civ_specs[0]["uniques"][1]["effects"].append(
            modifiers.new_raw_effect("MODIFIER_ALL_PLAYERS_ATTACH_MODIFIER",
                                     {"ModifierId": "NO_SUCH_MODIFIER"}))
        leader_specs[1]["new_ability"]["effects"].append(
            modifiers.new_raw_effect("MODIFIER_PLAYER_GRANT_YIELD",
                                     {"Amount": ""}))
        _, _, errors = modbuild.prepare_project(leader_specs, civ_specs,
                                                game_data(), "TST")
        text = "\n".join(errors)
        self.assertIn("Temple of Ares (Amazons): effect 2 - ", text)
        self.assertIn("no modifier NO_SUCH_MODIFIER", text)
        self.assertIn("Hippolyta (leader ability): effect 2 - ", text)

    def test_leader_unique_types_clash(self):
        leader_specs, civ_specs = sample_project()
        twin = uniques.new_unique_spec("unit")
        twin.update(name="Amazon Warrior", base="UNIT_SWORDSMAN")
        leader_specs[0]["uniques"].append(twin)
        _, _, errors = modbuild.prepare_project(leader_specs, civ_specs,
                                                game_data(), "TST")
        self.assertIn("Jeanne: duplicate type UNIT_TST_AMAZON_WARRIOR "
                      "(already used by Amazons)", "\n".join(errors))

    def test_same_effect_ids(self):
        leader_specs, civ_specs = sample_project()
        twin = uniques.new_unique_spec("building")
        twin.update(name="Amazon Warrior", base="BUILDING_LIBRARY",
                    effects=[modifiers.new_effect("tourism")])
        civ_specs[0]["uniques"].append(twin)
        _, _, errors = modbuild.prepare_project(leader_specs, civ_specs,
                                                game_data(), "TST")
        self.assertIn("both have effects and the same name",
                      "\n".join(errors))
