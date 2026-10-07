"""Unique units, buildings, districts and improvements of a new
civilization.

A unique item is usually a copy of an existing ("base") item under a
new type: every row of the base item is copied, so it plays like the base
item, then the chosen stats, yields and great person points are changed
and the editor's effects added. It normally replaces the base item for
its civilization, like the game's own uniques. Its 3D art is the base
item's (a renamed copy of its art definition), and its icons are the base
item's unless a custom icon is given.

Buildings, districts and improvements can also be new (no base): a
building built in the district of its choice, a district laid out like
another one, an improvement that looks like another; they start from the
game's usual values (see NEW_ROWS). Buildings and districts may replace
any item of their kind, or nothing; improvements never replace anything
(the game has no table for it): Builders of the civilization can build
them as well as the usual improvements.

A unique spec is a plain picklable dict:
    kind ("unit" / "building" / "district" / "improvement"), base (type
    to copy, "" = a new building / district / improvement), replaces (True = what the base item
    replaces, else the base item itself; "" / False = nothing - an extra
    item; or a type), name, desc, pedia (Civilopedia text; paragraphs
    separated by a blank line), stats ({column: value}, empty value =
    the base item's), yields ({YieldType: amount} or None = the base
    item's; buildings and improvements), gpp ({GreatPersonClassType: points} or None =
    the base item's; buildings and districts), adjacencies (bool, keep
    the base district's / improvement's adjacency bonuses), effects (see
    modifiers.py), placement (districts and improvements: where it can be
    built, see PLACEMENT_DEFAULTS / IMPROVEMENT_PLACEMENT_DEFAULTS; None =
    the base item's rules), icon_path (custom icon image, "" = the base
    item's icons), art (units: the 3D model, see unit_art.py; its look
    unit's icons are used; buildings and districts: see landmarks.py;
    improvements: {"look_from": the improvement it looks like, "" = the
    base improvement})
"""

import os

from .util import slug_for_name, sql_str
from .modifiers import effects_sql
from .texts import history_paragraphs, loc_text
from .artdefs import (BUILDINGS_ARTDEF, DISTRICTS_ARTDEF,
                      IMPROVEMENTS_ARTDEF, UNITS_ARTDEF)
from .unit_art import new_unit_art, normalize_art
from .landmarks import (new_building_art, new_district_art,
                        normalize_building_art, normalize_district_art)


KINDS = ("unit", "building", "district", "improvement")
KIND_LABELS = {"unit": "Unit", "building": "Building", "district": "District",
               "improvement": "Improvement"}

# kind -> (main table, type column, replaces table, replaces columns)
MAIN_TABLES = {
    "unit": ("Units", "UnitType", "UnitReplaces",
             ("CivUniqueUnitType", "ReplacesUnitType")),
    "building": ("Buildings", "BuildingType", "BuildingReplaces",
                 ("CivUniqueBuildingType", "ReplacesBuildingType")),
    "district": ("Districts", "DistrictType", "DistrictReplaces",
                 ("CivUniqueDistrictType", "ReplacesDistrictType")),
    # (improvements cannot replace one another)
    "improvement": ("Improvements", "ImprovementType", None, None),
}
# kinds that can replace an item of their kind
CAN_REPLACE = ("unit", "building", "district")

# Rows of the base item copied for the new one: (table, column holding the
# base type). Gathering Storm tables (GS = True) only exist with that
# expansion, so they go to a file that only loads then.
CLONE_TABLES = {
    "unit": [
        ("UnitAiInfos", "UnitType", False),
        ("TypeTags", "Type", False),
        ("UnitUpgrades", "Unit", False),
        ("Unit_BuildingPrereqs", "Unit", False),
        ("Units_MODE", "UnitType", False),
        ("Units_XP2", "UnitType", True),
    ],
    "building": [
        ("BuildingPrereqs", "Building", False),
        ("Building_YieldChanges", "BuildingType", False),
        ("Building_GreatPersonPoints", "BuildingType", False),
        ("Building_GreatWorks", "BuildingType", False),
        ("Building_CitizenYieldChanges", "BuildingType", False),
        ("Building_ValidTerrains", "BuildingType", False),
        ("Building_ValidFeatures", "BuildingType", False),
        ("Building_RequiredFeatures", "BuildingType", False),
        ("Building_YieldDistrictCopies", "BuildingType", False),
        ("Building_YieldsPerEra", "BuildingType", False),
        ("BuildingConditions", "BuildingType", False),
        ("BuildingModifiers", "BuildingType", False),
        ("MutuallyExclusiveBuildings", "Building", False),
        ("MutuallyExclusiveBuildings", "MutuallyExclusiveBuilding", False),
        # religious units bought with the base building (temples...)
        ("Unit_BuildingPrereqs", "PrereqBuilding", False),
        ("Buildings_XP2", "BuildingType", True),
        ("Building_YieldChangesBonusWithPower", "BuildingType", True),
        ("Building_ResourceCosts", "BuildingType", True),
    ],
    "district": [
        ("District_Adjacencies", "DistrictType", False),
        ("District_GreatPersonPoints", "DistrictType", False),
        ("District_TradeRouteYields", "DistrictType", False),
        ("District_CitizenYieldChanges", "DistrictType", False),
        ("District_CitizenGreatPersonPoints", "DistrictType", False),
        ("District_ValidTerrains", "DistrictType", False),
        ("District_RequiredFeatures", "DistrictType", False),
        ("DistrictModifiers", "DistrictType", False),
        ("MutuallyExclusiveDistricts", "District", False),
        ("MutuallyExclusiveDistricts", "MutuallyExclusiveDistrict", False),
        ("Districts_XP2", "DistrictType", True),
        ("District_BuildChargeProductions", "DistrictType", True),
    ],
    "improvement": [
        ("Improvement_ValidBuildUnits", "ImprovementType", False),
        ("Improvement_ValidTerrains", "ImprovementType", False),
        ("Improvement_ValidFeatures", "ImprovementType", False),
        ("Improvement_ValidResources", "ImprovementType", False),
        ("Improvement_ValidAdjacentTerrains", "ImprovementType", False),
        ("Improvement_ValidAdjacentResources", "ImprovementType", False),
        ("Improvement_InvalidAdjacentFeatures", "ImprovementType", False),
        ("Improvement_YieldChanges", "ImprovementType", False),
        ("Improvement_BonusYieldChanges", "ImprovementType", False),
        ("Improvement_Adjacencies", "ImprovementType", False),
        ("Improvement_Tourism", "ImprovementType", False),
        ("Improvement_YieldsOutsideTerritories", "ImprovementType",
         False),
        ("ImprovementModifiers", "ImprovementType", False),
        ("Improvements_MODE", "ImprovementType", False),
        ("Improvements_XP2", "ImprovementType", True),
    ],
}

# A required technology / civic of "NONE": the item needs none (even if
# the copied item does)
NO_PREREQ = "NONE"

# Editable stats: kind -> [(column, label, "int" or a GameData list kind)]
STATS = {
    "unit": [("Cost", "Production cost", "int"),
             ("Maintenance", "Maintenance (gold)", "int"),
             ("Combat", "Combat strength", "int"),
             ("RangedCombat", "Ranged strength", "int"),
             ("Range", "Range", "int"),
             ("Bombard", "Bombard strength", "int"),
             ("BaseMoves", "Movement", "int"),
             ("BaseSightRange", "Sight", "int"),
             ("PrereqTech", "Required technology", "tech"),
             ("PrereqCivic", "Required civic", "civic")],
    "building": [("PrereqDistrict", "District it is built in", "district"),
                 ("Cost", "Production cost", "int"),
                 ("Maintenance", "Maintenance (gold)", "int"),
                 ("Housing", "Housing", "int"),
                 ("Entertainment", "Amenities", "int"),
                 ("CitizenSlots", "Citizen slots", "int"),
                 ("PrereqTech", "Required technology", "tech"),
                 ("PrereqCivic", "Required civic", "civic")],
    "district": [("Cost", "Production cost", "int"),
                 ("Maintenance", "Maintenance (gold)", "int"),
                 ("Housing", "Housing", "int"),
                 ("Entertainment", "Amenities", "int"),
                 ("CitizenSlots", "Citizen slots", "int"),
                 ("Appeal", "Appeal", "int"),
                 ("PrereqTech", "Required technology", "tech"),
                 ("PrereqCivic", "Required civic", "civic")],
    "improvement": [("Housing", "Housing", "int"),
                    ("Appeal", "Appeal (to the tiles around it)", "int"),
                    ("DefenseModifier", "Defense bonus of units on it",
                     "int"),
                    ("PrereqTech", "Required technology", "tech"),
                    ("PrereqCivic", "Required civic", "civic")],
}

# Icons copied from the base item: icon names with the base type in them
# ({T} = type). Unit portraits also exist per ethnicity.
ICON_NAMES = {
    "unit": ["ICON_{T}", "ICON_{T}_FOW", "ICON_{T}_PORTRAIT",
             "ICON_{T}_WHITE", "ICON_{T}_BLACK"],
    "building": ["ICON_{T}", "ICON_{T}_FOW"],
    "district": ["ICON_{T}", "ICON_{T}_FOW", "{T}"],   # {T}: font icon
    "improvement": ["ICON_{T}"],
}
# Sizes of a custom ICON_<type> (as the game's own atlases)
ICON_SIZES = {
    # (units: an atlas of portrait and icon side by side, at the sizes
    # of the template mod's unit atlas)
    "unit": [22, 32, 38, 50, 70, 80, 95, 200, 256],
    "building": [32, 38, 50, 80, 128, 256],
    "district": [22, 32, 38, 50, 80, 128, 256],
    "improvement": [38, 50, 80, 256],
}
# kind -> (.artdef file, root collection)
ART = {"unit": (UNITS_ARTDEF, "Units"),
       "building": (BUILDINGS_ARTDEF, "Building"),
       "district": (DISTRICTS_ARTDEF, "District"),
       "improvement": (IMPROVEMENTS_ARTDEF, "Improvement")}

PEDIA_PAGES = {"unit": "UNITS", "building": "BUILDINGS",
               "district": "DISTRICTS", "improvement": "IMPROVEMENTS"}

# New (not copied) buildings and districts: the columns they start with -
# the game's usual values (a district like the Campus); the stats change
# them. The other columns keep their schema defaults.
NEW_ROWS = {
    "building": [("Cost", "100"), ("PurchaseYield", "'YIELD_GOLD'")],
    "district": [("Cost", "54"), ("RequiresPlacement", "1"),
                 ("RequiresPopulation", "1"), ("NoAdjacentCity", "0"),
                 ("Aqueduct", "0"), ("InternalOnly", "0"),
                 ("CaptureRemovesBuildings", "0"),
                 ("CaptureRemovesCityDefenses", "0"),
                 ("PlunderType", "'NO_PLUNDER'"), ("PlunderAmount", "0"),
                 ("MilitaryDomain", "'NO_DOMAIN'"),
                 ("CostProgressionModel",
                  "'COST_PROGRESSION_NUM_UNDER_AVG_PLUS_TECH'"),
                 ("CostProgressionParam1", "40"), ("Maintenance", "1"),
                 ("CitizenSlots", "1")],
    "improvement": [("Buildable", "1"), ("PlunderType", "'PLUNDER_HEAL'"),
                    ("PlunderAmount", "50")],
}
CAN_BE_NEW = ("building", "district", "improvement")

# Where a district can be built (its placement spec; None = the copied
# district's rules):
#   water: on a coast or lake tile next to land (Harbor), else on land
#   terrains: the only terrains it may be built on ([] = any)
#   features: features one of which the tile must have ([] = none needed)
#   no_adjacent_city: not next to the city center
#   one_per_city: at most one per city; max_per_player: per civilization
#   (-1 = no limit)
PLACEMENT_DEFAULTS = {"water": False, "terrains": [], "features": [],
                      "no_adjacent_city": False, "one_per_city": True,
                      "max_per_player": -1}


def normalize_placement(placement, label):
    """A validated placement spec, or None (keep the copied rules)."""
    if placement is None:
        return None
    out = dict(PLACEMENT_DEFAULTS)
    for key in ("water", "no_adjacent_city", "one_per_city"):
        out[key] = bool(placement.get(key, out[key]))
    for key, prefix in (("terrains", "TERRAIN_"), ("features", "FEATURE_")):
        values = [str(v).strip().upper() for v in placement.get(key) or []
                  if str(v).strip()]
        bad = [v for v in values if not v.startswith(prefix)]
        if bad:
            raise ValueError("{}: '{}' is not a {} type.".format(
                label, bad[0], prefix))
        out[key] = sorted(set(values))
    try:
        out["max_per_player"] = int(placement.get("max_per_player", -1))
    except (TypeError, ValueError):
        raise ValueError("{}: the number per civilization must be a whole "
                         "number (-1 = no limit).".format(label))
    if out["max_per_player"] == 0 or out["max_per_player"] < -1:
        raise ValueError("{}: the number per civilization must be 1 or more "
                         "(-1 = no limit).".format(label))
    return out


def placement_sql(slug, p):
    """SQL setting a district's placement rules (replacing copied ones)."""
    s = sql_str(slug)
    out = ["-- where it can be built\n"
           "UPDATE Districts SET Coast = {w}, AdjacentToLand = {w}, "
           "NoAdjacentCity = {n}, OnePerCity = {o}, MaxPerPlayer = {m}\n"
           "WHERE DistrictType = {s};\n"
           "DELETE FROM District_ValidTerrains WHERE DistrictType = {s};\n"
           "DELETE FROM District_RequiredFeatures WHERE DistrictType = {s};\n"
           .format(w=int(p["water"]), n=int(p["no_adjacent_city"]),
                   o=int(p["one_per_city"]), m=p["max_per_player"], s=s)]
    for table, column, key in (("District_ValidTerrains", "TerrainType",
                                "terrains"),
                               ("District_RequiredFeatures", "FeatureType",
                                "features")):
        if p[key]:
            out.append("INSERT INTO {} (DistrictType, {}) VALUES\n{};\n"
                       .format(table, column, ",\n".join(
                           "({}, {})".format(s, sql_str(v))
                           for v in p[key])))
    return "".join(out)


# Where an improvement can be built (its placement spec; None = the
# copied improvement's rules):
#   terrains: the terrains it may be built on (all coast / ocean: a water
#   improvement, like the Kampung)
#   features: features it may be built on (other features must be removed
#   first)
#   resources: resources it may be built on
#   river: only next to a river; no_same_adjacent: not next to another of
#   its kind; one_per_city: one per city; outside_territory: also outside
#   the civilization's borders
WATER_TERRAINS = ("TERRAIN_COAST", "TERRAIN_OCEAN")
IMPROVEMENT_PLACEMENT_DEFAULTS = {
    "terrains": ["TERRAIN_DESERT", "TERRAIN_DESERT_HILLS", "TERRAIN_GRASS",
                 "TERRAIN_GRASS_HILLS", "TERRAIN_PLAINS",
                 "TERRAIN_PLAINS_HILLS", "TERRAIN_TUNDRA",
                 "TERRAIN_TUNDRA_HILLS"],
    "features": [], "resources": [], "river": False,
    "no_same_adjacent": False, "one_per_city": False,
    "outside_territory": False}


def normalize_improvement_placement(placement, label):
    """A validated improvement placement spec, or None (keep the copied
    rules)."""
    if placement is None:
        return None
    out = dict(IMPROVEMENT_PLACEMENT_DEFAULTS)
    for key in ("river", "no_same_adjacent", "one_per_city",
                "outside_territory"):
        out[key] = bool(placement.get(key, out[key]))
    for key, prefix in (("terrains", "TERRAIN_"), ("features", "FEATURE_"),
                        ("resources", "RESOURCE_")):
        values = [str(v).strip().upper() for v in placement.get(key) or []
                  if str(v).strip()]
        bad = [v for v in values if not v.startswith(prefix)]
        if bad:
            raise ValueError("{}: '{}' is not a {} type.".format(
                label, bad[0], prefix))
        out[key] = sorted(set(values))
    if not (out["terrains"] or out["features"] or out["resources"]):
        raise ValueError("{}: pick at least one terrain, feature or "
                         "resource it can be built on (Placement tab)."
                         .format(label))
    return out


def improvement_placement_sql(slug, p):
    """SQL setting an improvement's placement rules (replacing copied
    ones)."""
    s = sql_str(slug)
    water = bool(p["terrains"]) and all(t in WATER_TERRAINS
                                        for t in p["terrains"])
    out = ["-- where it can be built\n"
           "UPDATE Improvements SET Domain = {d}, RequiresRiver = {r}, "
           "SameAdjacentValid = {a}, OnePerCity = {o}, "
           "CanBuildOutsideTerritory = {t}\nWHERE ImprovementType = {s};\n"
           .format(d=sql_str("DOMAIN_SEA" if water else "DOMAIN_LAND"),
                   r=int(p["river"]), a=int(not p["no_same_adjacent"]),
                   o=int(p["one_per_city"]), t=int(p["outside_territory"]),
                   s=s)]
    for table, column, key in (
            ("Improvement_ValidTerrains", "TerrainType", "terrains"),
            ("Improvement_ValidFeatures", "FeatureType", "features"),
            ("Improvement_ValidResources", "ResourceType", "resources")):
        out.append("DELETE FROM {} WHERE ImprovementType = {};\n".format(
            table, s))
        if p[key]:
            out.append("INSERT INTO {} (ImprovementType, {}) VALUES\n{};\n"
                       .format(table, column, ",\n".join(
                           "({}, {})".format(s, sql_str(v))
                           for v in p[key])))
    return "".join(out)


def new_improvement_art():
    return {"look_from": ""}


def normalize_improvement_art(art, label):
    look = ((art or {}).get("look_from") or "").strip().upper()
    if look and not look.startswith("IMPROVEMENT_"):
        raise ValueError("{}: '{}' is not an improvement.".format(label,
                                                                   look))
    return {"look_from": look}


def new_unique_spec(kind="unit"):
    spec = {"kind": kind, "base": "", "replaces": True, "name": "",
            "desc": "", "pedia": "", "stats": {}, "yields": None,
            "gpp": None, "adjacencies": True, "effects": [],
            "icon_path": "", "portrait_path": ""}
    spec["art"] = {"unit": new_unit_art, "building": new_building_art,
                   "district": new_district_art,
                   "improvement": new_improvement_art}[kind]()
    return spec


def normalize_unique(spec, civ, data, prefix=""):
    """Validate a unique spec of the civilization context civ and derive
    its type and tags. Raises ValueError."""
    kind = spec.get("kind")
    name = (spec.get("name") or "").strip()
    if kind not in KINDS:
        raise ValueError("{}: unknown unique kind '{}'.".format(
            civ["name"], kind))
    if not name:
        raise ValueError("{}: a unique {} has no name.".format(
            civ["name"], kind))
    label = "{} ({})".format(name, civ["name"])
    base = (spec.get("base") or "").strip().upper()
    prefix_word = MAIN_TABLES[kind][1][:-len("Type")].upper()
    if base and not base.startswith(prefix_word + "_") or \
            not base and kind not in CAN_BE_NEW:
        raise ValueError("{}: pick the {} to copy (a {}_ type).".format(
            label, kind, prefix_word))
    slug = slug_for_name(name, prefix, kind=prefix_word)
    if not slug or slug == base:
        raise ValueError("{}: its type ({}) collides with the base {}. "
                         "Change the name.".format(label, slug, kind))
    stats = {}
    for column, stat_label, stat_kind in STATS[kind]:
        value = str((spec.get("stats") or {}).get(column, "") or "").strip()
        if not value:
            continue
        if stat_kind == "int":
            try:
                value = int(value)
            except ValueError:
                raise ValueError("{}: {} must be a whole number.".format(
                    label, stat_label.lower()))
        elif value.upper() == NO_PREREQ and stat_kind in ("tech", "civic"):
            value = None                # explicitly none (SQL NULL)
        else:
            value = value.upper()
            prefix = {"tech": "TECH_", "civic": "CIVIC_",
                      "district": "DISTRICT_"}.get(stat_kind)
            if prefix and not value.startswith(prefix):
                raise ValueError("{}: {} must be a {} type{}.".format(
                    label, stat_label.lower(), prefix,
                    "" if stat_kind == "district" else " or " + NO_PREREQ))
        stats[column] = value
    numbers = {}
    for key in ("yields", "gpp"):
        given = spec.get(key)
        if given is None:
            numbers[key] = None
            continue
        numbers[key] = {}
        for type_name, amount in given.items():
            try:
                amount = int(amount)
            except (TypeError, ValueError):
                raise ValueError("{}: {} of {} must be a whole number."
                                 .format(label, key, type_name))
            if amount:
                numbers[key][type_name] = amount
    icon_path = (spec.get("icon_path") or "").strip()
    if icon_path and not os.path.isfile(icon_path):
        raise ValueError("{}: icon image not found: {}".format(label,
                                                                icon_path))
    # units: the portrait (unit panel, production list) next to the icon
    portrait_path = (spec.get("portrait_path") or "").strip() \
        if kind == "unit" else ""
    if portrait_path and not os.path.isfile(portrait_path):
        raise ValueError("{}: portrait image not found: {}".format(
            label, portrait_path))
    art = {"unit": normalize_art, "building": normalize_building_art,
           "district": normalize_district_art,
           "improvement": normalize_improvement_art}[kind](spec.get("art"),
                                                          label)
    base_row = data.item(kind, base) if data.conn and base else None
    if base and data.conn and not base_row:
        raise ValueError("{}: {} is not in the loaded game data.".format(
            label, base))
    # what it replaces: True = what the base item replaces (if it is a
    # unique item itself), else the base item; "" / False = nothing
    replaces = spec.get("replaces", True)
    if kind not in CAN_REPLACE:
        replaced = None
    elif replaces is True:
        replaced = ((base_row or {}).get("replaces") or base) or None
    elif not replaces or str(replaces).strip().upper() == NO_PREREQ:
        replaced = None
    else:
        replaced = str(replaces).strip().upper()
        if not replaced.startswith(prefix_word + "_"):
            raise ValueError("{}: it can only replace a {} ({}_ type)."
                             .format(label, kind, prefix_word))
    placement = normalize_placement(spec.get("placement"), label) \
        if kind == "district" else None
    if kind == "district" and not base and placement is None:
        placement = dict(PLACEMENT_DEFAULTS)    # a new district: on land
    if kind == "improvement":
        placement = normalize_improvement_placement(spec.get("placement"),
                                                    label)
        if not base and placement is None:      # a new one: on land
            placement = dict(IMPROVEMENT_PLACEMENT_DEFAULTS)
        if not base and not art.get("look_from"):
            raise ValueError("{}: pick the improvement a new improvement "
                             "looks like (3D model tab).".format(label))
    district = None
    if kind == "building":
        district = stats.get("PrereqDistrict") or \
            (base_row or {}).get("PrereqDistrict")
        if not base and not district:
            raise ValueError("{}: pick the district a new building is built "
                             "in (Stats tab).".format(label))
        if not base:
            stats.setdefault("PrereqDistrict", district)
    if kind == "district" and not base and not art.get("look_from"):
        raise ValueError("{}: pick the district a new district looks like "
                         "(3D model tab).".format(label))
    # the game item its art definition and icons start from
    model_from = base or art.get("look_from") or replaced
    return {
        "kind": kind, "name": name, "base": base, "slug": slug,
        "label": label, "civ": civ["slug"], "new": not base,
        # what the base item replaces, if it is itself a unique item
        "base_replaces": (base_row or {}).get("replaces"),
        "replaced": replaced,
        # buildings: the district it is built in (None: unknown)
        "district": district,
        "placement": placement,
        "model_from": model_from,
        "desc": (spec.get("desc") or "").strip(),
        "pedia": (spec.get("pedia") or "").strip(),
        "stats": stats, "yields": numbers["yields"], "gpp": numbers["gpp"],
        "adjacencies": bool(spec.get("adjacencies", True)),
        "effects": list(spec.get("effects") or []),
        "icon_path": icon_path,
        "art": art,
        # the item whose icons it uses: the unit / building it looks
        # like, else its base item or what it replaces
        "icon_from": art.get("look_from") or model_from,
        "trait": "TRAIT_CIVILIZATION_" + slug,
        "name_tag": "LOC_{}_NAME".format(slug),
        # no description of its own: the base item's (setup screen)
        "desc_tag": "LOC_{}_DESCRIPTION".format(slug)
                    if (spec.get("desc") or "").strip() or not base
                    else (base_row or {}).get("Description") or
                    "LOC_{}_DESCRIPTION".format(base),
        "icon_name": "ICON_" + slug,
        "icon_atlas": "ICON_ATLAS_" + slug,
        "icon_custom": bool(icon_path or portrait_path),
        # units: the images of the atlas cells (portrait, icon - either
        # one stands in for a missing other) and their icon names
        "portrait_path": portrait_path,
        "atlas_paths": [portrait_path or icon_path, icon_path or
                        portrait_path] if kind == "unit" else None,
        "icon_defs": [("ICON_{}_PORTRAIT".format(slug), 0),
                      ("ICON_" + slug, 1)] if kind == "unit" else None,
    }


# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

def clone_rows(table, column, base, new, updates=()):
    """Copy every row of table whose column is base, with new instead.
    Through a temporary table, so every column is copied - also those an
    expansion or another mod adds. updates: (column, SQL value) pairs to
    change in the copy."""
    sets = ", ".join("{} = {}".format(c, v) for c, v in
                     [(column, sql_str(new))] + list(updates))
    return ("DROP TABLE IF EXISTS CivGenClone;\n"
            "CREATE TEMPORARY TABLE CivGenClone AS SELECT * FROM {table} "
            "WHERE {column} = {base};\n"
            "UPDATE CivGenClone SET {sets};\n"
            "INSERT INTO {table} SELECT * FROM CivGenClone;\n"
            "DROP TABLE CivGenClone;\n").format(
                table=table, column=column, base=sql_str(base), sets=sets)


def _stat_value(value):
    if value is None:                   # e.g. no required technology
        return "NULL"
    return str(value) if isinstance(value, int) else sql_str(value)


def unique_sql(u, name_of):
    """(gameplay SQL, Gathering Storm-only SQL, [(text tag, text)]) of a
    unique item context."""
    kind, slug, base = u["kind"], u["slug"], u["base"]
    table, column, replaces_table, replaces_cols = MAIN_TABLES[kind]
    updates = [("Name", sql_str(u["name_tag"])),
               ("Description", sql_str(u["desc_tag"])),
               ("TraitType", sql_str(u["trait"]))]
    if not u["desc"] and base:          # keep the base item's description
        del updates[1]
    updates += [(c, _stat_value(v)) for c, v in sorted(u["stats"].items())]
    if kind == "improvement":
        # its own icon (copied from the one it looks like, or custom)
        updates.append(("Icon", sql_str(u["icon_name"])))
    out = ["""-----------------------------------------------
-- {label}: {what} ({slug})
-----------------------------------------------
INSERT INTO Types (Type, Kind) VALUES ({s}, 'KIND_{k}');
INSERT INTO Types (Type, Kind) VALUES ({trait}, 'KIND_TRAIT');
INSERT INTO Traits (TraitType, Name) VALUES ({trait}, {name_tag});
INSERT INTO CivilizationTraits (CivilizationType, TraitType)
VALUES ({civ}, {trait});
""".format(label=u["label"], slug=slug, s=sql_str(slug),
           what="a copy of " + base if base else "a new " + kind,
           k=kind.upper(), trait=sql_str(u["trait"]),
           name_tag=sql_str(u["name_tag"]), civ=sql_str(u["civ"]))]
    xp2 = []
    if base:
        out.append(clone_rows(table, column, base, slug, updates))
        for clone_table, clone_column, gs in CLONE_TABLES[kind]:
            if clone_table in ("District_Adjacencies",
                               "Improvement_Adjacencies") and \
                    not u["adjacencies"]:
                continue
            (xp2 if gs else out).append(
                clone_rows(clone_table, clone_column, base, slug))
    else:                               # new: the usual values, then stats
        columns = [(column, sql_str(slug))] + updates
        given = {c for c, _ in columns}
        columns += [(c, v) for c, v in NEW_ROWS[kind] if c not in given]
        out.append("INSERT INTO {} ({}) VALUES ({});\n".format(
            table, ", ".join(c for c, _ in columns),
            ", ".join(v for _, v in columns)))
    if kind == "improvement" and not base:
        # built by Builders; tourism from its culture after Flight, like
        # the game's own unique improvements
        updates_after = (
            "INSERT INTO Improvement_ValidBuildUnits (ImprovementType, "
            "UnitType) VALUES ({s}, 'UNIT_BUILDER');\n"
            "INSERT INTO Improvement_Tourism (ImprovementType, "
            "TourismSource, PrereqTech, ScalingFactor) VALUES ({s}, "
            "'TOURISMSOURCE_CULTURE', 'TECH_FLIGHT', 100);\n").format(
                s=sql_str(slug))
    else:
        updates_after = ""
    if u.get("placement"):
        out.append(placement_sql(slug, u["placement"]) if kind == "district"
                   else improvement_placement_sql(slug, u["placement"]))
    if u["replaced"]:
        out.append("INSERT INTO {} ({}, {}) VALUES ({}, {});\n".format(
            replaces_table, replaces_cols[0], replaces_cols[1],
            sql_str(slug), sql_str(u["replaced"])))
    for key, child, child_column, value_column in (
            ("yields", "{}_YieldChanges".format(table[:-1]), "YieldType",
             "YieldChange"),
            ("gpp", "{}_GreatPersonPoints".format(table[:-1]),
             "GreatPersonClassType", "PointsPerTurn")):
        if u[key] is None or (key == "yields" and kind not in (
                "building", "improvement")) or \
                (key == "gpp" and kind not in ("building", "district")):
            continue
        out.append("DELETE FROM {} WHERE {} = {};\n".format(
            child, column, sql_str(slug)))
        if u[key]:
            out.append("INSERT INTO {} ({}, {}, {}) VALUES\n{};\n".format(
                child, column, child_column, value_column, ",\n".join(
                    "({}, {}, {})".format(sql_str(slug), sql_str(t), n)
                    for t, n in sorted(u[key].items()))))
    out.append(updates_after)
    effects, texts = effects_sql(kind, slug, u["effects"], u["name"],
                                 name_of)
    out.append(effects)
    return "".join(out), "".join(xp2), texts


def unique_text_rows(u):
    """[(tag, English text)] of a unique item."""
    rows = [(u["name_tag"], u["name"])]
    if u["desc"]:
        rows.append((u["desc_tag"], loc_text(u["desc"])))
    elif u["new"]:                      # a new item has no description
        rows.append((u["desc_tag"], u["name"]))
    page = "LOC_PEDIA_{}_PAGE_{}_CHAPTER_HISTORY_PARA_".format(
        PEDIA_PAGES[u["kind"]], u["slug"])
    rows += [(page + str(i), loc_text(p))
             for i, p in enumerate(history_paragraphs(u["pedia"]), 1)]
    return rows


def unique_icons_sql(u):
    """IconDefinitions rows copied from the icons of the item it looks
    like (the base item, or the unit whose art it uses). A custom icon
    replaces ICON_<type> (see atlas rows)."""
    source = u["icon_from"]
    if not source:
        return "-- {}: no icons to copy (give it an icon image)\n".format(
            u["label"])
    names = [n.format(T=source) for n in ICON_NAMES[u["kind"]]]
    if u["icon_custom"]:
        # the atlas has these (a unit: its icon and portrait)
        for name, _ in u.get("icon_defs") or [("ICON_" + u["slug"], 0)]:
            name = name.replace(u["slug"], source)
            if name in names:
                names.remove(name)
    where = "Name IN ({})".format(", ".join(map(sql_str, names)))
    # (the game shows an ethnicity's portrait before the unit's own, so
    # a unit with its own portrait gets none of those)
    if u["kind"] == "unit" and not u["icon_custom"]:
        where += " OR Name GLOB {}".format(sql_str(
            "ICON_ETHNICITY_*_{}_PORTRAIT".format(source)))
    return ("-- {label}: the icons of {base}\n"
            "INSERT OR REPLACE INTO IconDefinitions (Name, Atlas, \"Index\")\n"
            "SELECT REPLACE(Name, {base_s}, {slug_s}), Atlas, \"Index\" "
            "FROM IconDefinitions\nWHERE {where};\n").format(
                label=u["label"], base=source, base_s=sql_str(source),
                slug_s=sql_str(u["slug"]), where=where)


def player_item_sql(u, leader, sort_index):
    """PlayerItems row (setup screen) of a unique for one leader, in every
    ruleset domain the leader has a Players row in."""
    return ("INSERT INTO PlayerItems (Domain, CivilizationType, LeaderType, "
            "Type, Name, Description, Icon, SortIndex)\n"
            "SELECT Domain, CivilizationType, LeaderType, {}, {}, {}, {}, {}\n"
            "FROM Players WHERE LeaderType = {};\n").format(
                sql_str(u["slug"]), sql_str(u["name_tag"]),
                sql_str(u["desc_tag"]), sql_str(u["icon_name"]), sort_index,
                sql_str(leader))


# ---------------------------------------------------------------------------
# A description written from the unique's changes
# ---------------------------------------------------------------------------

# stats that are costs: column -> (verb, resource)
COST_WORDS = {"Cost": ("Costs", "Production"),
              "Maintenance": ("Maintenance costs", "Gold")}


def describe_unique(spec, data, name_of=None):
    """A description of a unique spec in the game's style: what it
    replaces, its stats compared with the item it copies (a new item: its
    stats), its own yields and great person points, and its effects. Lines
    are separated by newlines. data: GameData (the copied item's stats);
    name_of(kind, type): display names (default: data.type_name)."""
    from .modifiers import describe_effects, sentence, with_icons
    name_of = name_of or data.type_name
    kind = spec.get("kind")
    base = (spec.get("base") or "").strip()
    row = data.item(kind, base) if base and data.conn else None
    lines = []
    replaces = spec.get("replaces", True)
    if kind in CAN_REPLACE:
        replaced = ((row or {}).get("replaces") or base) if replaces is True \
            else ("" if not replaces or str(replaces).upper() == NO_PREREQ
                  else str(replaces))
        if replaced:
            lines.append("Replaces the {}.".format(name_of(kind, replaced)))
    stats = spec.get("stats") or {}
    district = stats.get("PrereqDistrict")
    if kind == "building" and district and district != (row or {}).get(
            "PrereqDistrict"):
        lines.append("Built in the {} district.".format(
            name_of("district", district)))
    for column, label, stat_kind in STATS.get(kind, []):
        value = str(stats.get(column, "") or "").strip()
        if stat_kind != "int" or not value:
            continue
        try:
            value = int(value)
        except ValueError:
            continue
        before = (row or {}).get(column)
        change = value - before if row and isinstance(before, int) else None
        if change == 0 or (change is None and not value):
            continue
        than = " than the {}".format(name_of(kind, base))             if change is not None else ""
        if column in COST_WORDS:        # what it costs, the game's way
            what, unit = COST_WORDS[column]
            amount = "{} {}".format(abs(change), "more" if change > 0
                                    else "less") if change is not None                 else str(value)
            lines.append(with_icons(sentence("{} {} {}{}{}".format(
                what, amount, unit, " per turn" if column == "Maintenance"
                else "", than))))
        else:
            lines.append(with_icons(sentence("{:+d} {}{}".format(
                change if change is not None else value, label,
                " (compared to the {})".format(name_of(kind, base))
                if change is not None else ""))))
    for key, list_kind, what in (("yields", "yield", ""),
                                 ("gpp", "great_person", " points")):
        for type_name, amount in sorted((spec.get(key) or {}).items()):
            try:
                amount = int(amount)
            except (TypeError, ValueError):
                continue
            if amount:
                lines.append(with_icons(sentence("{:+d} {}{}".format(
                    amount, name_of(list_kind, type_name), what))))
    effects = describe_effects(spec.get("effects"), name_of)
    if effects:
        lines.append(effects)
    return "\n".join(lines)
