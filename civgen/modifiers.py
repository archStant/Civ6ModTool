"""Effects ("modifiers") for abilities, buildings, districts and units.

An effect is a plain JSON-ready dict the editor fills in, in one of two
forms. A template effect, one of the editor's list (TEMPLATES):

    {"template": "city_yield",                  # a TEMPLATES key
     "args": {"Amount": "2", "YieldType": "YIELD_SCIENCE"},
     "reqs": [...]}

or a raw effect (advanced mode): any of the game's modifier types, with
any arguments:

    {"modifier_type": "MODIFIER_PLAYER_GRANT_YIELD",
     "args": {"Amount": "100", "YieldType": "YIELD_GOLD"},
     "reqs": [...], "run_once": True, "permanent": True,
     "text": "",                 # its summary (empty: made from the args)
     "attached": {effect},       # types that attach a modifier: the effect
                                 # they attach (instead of a ModifierId)
     # kept as they are from a copied game modifier (see effect_from_game):
     "arg_types": {name: {"Type", "Extra", "SecondExtra"}},
     "columns": {"Repeatable": 1, ...},     # see MODIFIER_COLUMNS
     "strings": {"Preview": "LOC_..."}}     # ModifierStrings

Either may have "set_types": {target: "ANY"}: the requirement set of that
target is met by any one of its requirements (else all are needed).

A requirement ("only when ...") is one of

    {"preset": "city_district", "value": "DISTRICT_CAMPUS",  # REQUIREMENTS
     "not": False}
    {"type": "REQUIREMENT_PLOT_IS_HILLS", "args": {}, "not": False,
     "target": "subject"}                       # raw (advanced mode)
    {"group": "ANY", "reqs": [preset or raw requirements], "not": False,
     "target": "subject"}                       # a set in a set (advanced)

effects_sql() turns a list of effects into the game's Modifiers,
ModifierArguments, requirement and unit ability rows. Every template is a
modifier type the game itself uses with these arguments; the editor only
offers templates that work for the owner (see OWNERS). Raw effects are
written as they are, linked straight to their owner.
"""

import re
from collections import namedtuple

from .util import is_number, sql_str, type_display_name


# ---------------------------------------------------------------------------
# Argument kinds
# ---------------------------------------------------------------------------
# kind -> GameData list for the editor's dropdown (see GameData.type_choices),
# or a fixed list of (value, label) choices, or None for free input.

ENUMS = {
    "heal_type": [("ALL", "Everywhere"), ("NEUTRAL", "Neutral territory"),
                  ("ENEMY", "Enemy territory")],
    "terrain_cost": [("HILLS", "Hills"), ("FOREST", "Woods"),
                     ("ALL", "All terrain")],
    "domain": [("DOMAIN_LAND", "Land"), ("DOMAIN_SEA", "Sea"),
               ("DOMAIN_AIR", "Air")],
}
KIND_LISTS = {
    "yield": "yield", "district": "district", "building": "building",
    "unit": "unit", "promotion_class": "promotion_class",
    "feature": "feature", "terrain": "terrain",
    "improvement": "improvement", "resource": "resource", "era": "era",
    "great_person": "great_person", "tech": "tech", "civic": "civic",
    "ability": "ability",
}
NUMBER_KINDS = ("int", "number")        # number: decimals allowed

YIELD_ICONS = {"YIELD_FOOD": "[ICON_Food]",
               "YIELD_PRODUCTION": "[ICON_Production]",
               "YIELD_GOLD": "[ICON_Gold]", "YIELD_SCIENCE": "[ICON_Science]",
               "YIELD_CULTURE": "[ICON_Culture]",
               "YIELD_FAITH": "[ICON_Faith]"}


Arg = namedtuple("Arg", "name kind label default")
Template = namedtuple("Template", "id category label modifier_type args "
                                  "scope text help run_once permanent")


def T(id, category, label, modifier_type, args, scope, text, help="",
      run_once=False, permanent=False):
    return Template(id, category, label, modifier_type,
                    [Arg(*a) for a in args], scope, text, help, run_once,
                    permanent)


AMOUNT = ("Amount", "int", "Amount", "1")
PERCENT = ("Amount", "int", "Percent", "10")
YIELD = ("YieldType", "yield", "Yield", "YIELD_PRODUCTION")
TEXT = ("Description", "text", "Tooltip text (empty: automatic)", "")

# scope: what the modifier applies to, which decides where it can be used
#   player - the owning player (abilities, buildings, districts)
#   cities - all of the player's cities / districts / tiles (same)
#   city   - the city of the building or district only
#   unit   - a unit: the unique unit itself, or (from an ability, building
#            or district) the player's units, through a granted unit
#            ability; requirements of the "units" target pick which
TEMPLATES = [
    # -- yields
    T("city_yield", "Yields", "Yield in every city",
      "MODIFIER_PLAYER_CITIES_ADJUST_CITY_YIELD_CHANGE", [AMOUNT, YIELD],
      "cities", "+{Amount} {YieldType} in every city"),
    T("city_yield_pct", "Yields", "Yield percentage in every city",
      "MODIFIER_PLAYER_CITIES_ADJUST_CITY_YIELD_MODIFIER", [PERCENT, YIELD],
      "cities", "+{Amount}% {YieldType} in every city"),
    T("capital_yield", "Yields", "Yield in the capital",
      "MODIFIER_PLAYER_CAPITAL_CITY_ADJUST_CITY_YIELD_CHANGE",
      [AMOUNT, YIELD], "cities", "+{Amount} {YieldType} in the capital"),
    T("city_yield_per_pop", "Yields", "Yield per citizen in every city",
      "MODIFIER_PLAYER_CITIES_ADJUST_CITY_YIELD_PER_POPULATION",
      [("Amount", "number", "Amount per citizen", "0.5"), YIELD], "cities",
      "+{Amount} {YieldType} per citizen in every city"),
    T("district_yield", "Yields", "Yield from districts",
      "MODIFIER_PLAYER_DISTRICTS_ADJUST_YIELD_CHANGE", [AMOUNT, YIELD],
      "cities", "+{Amount} {YieldType} from each district",
      help="Add a 'District is' requirement to pick the districts."),
    T("building_yield", "Yields", "Yield from a building",
      "MODIFIER_PLAYER_CITIES_ADJUST_BUILDING_YIELD_CHANGE",
      [AMOUNT, ("BuildingType", "building", "Building", ""), YIELD],
      "cities", "+{Amount} {YieldType} from every {BuildingType}"),
    T("plot_yield", "Yields", "Yield on tiles",
      "MODIFIER_PLAYER_ADJUST_PLOT_YIELD", [AMOUNT, YIELD], "cities",
      "+{Amount} {YieldType} on tiles",
      help="Add tile requirements (terrain, feature, improvement, "
           "resource...) to pick the tiles - without them every tile "
           "gets the yield."),
    T("this_city_yield_pct", "Yields", "Yield percentage in this city",
      "MODIFIER_SINGLE_CITY_ADJUST_CITY_YIELD_MODIFIER", [PERCENT, YIELD],
      "city", "+{Amount}% {YieldType} in this city"),
    # -- adjacency
    T("feature_adjacency", "Adjacency", "District adjacency: feature",
      "MODIFIER_PLAYER_CITIES_FEATURE_ADJACENCY",
      [AMOUNT, ("DistrictType", "district", "District", ""),
       ("FeatureType", "feature", "Adjacent feature", ""), YIELD, TEXT],
      "cities", "{DistrictType}: +{Amount} {YieldType} per adjacent "
                "{FeatureType}"),
    T("terrain_adjacency", "Adjacency", "District adjacency: terrain",
      "MODIFIER_PLAYER_CITIES_TERRAIN_ADJACENCY",
      [AMOUNT, ("DistrictType", "district", "District", ""),
       ("TerrainType", "terrain", "Adjacent terrain", ""), YIELD,
       ("TilesRequired", "int", "Tiles per bonus", "1"), TEXT],
      "cities", "{DistrictType}: +{Amount} {YieldType} per {TilesRequired} "
                "adjacent {TerrainType}"),
    T("improvement_adjacency", "Adjacency", "District adjacency: improvement",
      "MODIFIER_PLAYER_CITIES_IMPROVEMENT_ADJACENCY",
      [AMOUNT, ("DistrictType", "district", "District", ""),
       ("ImprovementType", "improvement", "Adjacent improvement", ""), YIELD,
       ("TilesRequired", "int", "Tiles per bonus", "1"), TEXT],
      "cities", "{DistrictType}: +{Amount} {YieldType} per {TilesRequired} "
                "adjacent {ImprovementType}"),
    T("district_adjacency", "Adjacency", "District adjacency: districts",
      "MODIFIER_PLAYER_CITIES_DISTRICT_ADJACENCY",
      [AMOUNT, ("DistrictType", "district", "District", ""), YIELD, TEXT],
      "cities", "{DistrictType}: +{Amount} {YieldType} per adjacent "
                "district"),
    # -- production
    T("district_production", "Production", "Faster district production",
      "MODIFIER_PLAYER_CITIES_ADJUST_DISTRICT_PRODUCTION",
      [PERCENT, ("DistrictType", "district", "District", "")], "cities",
      "+{Amount}% Production towards {DistrictType}"),
    T("all_districts_production", "Production",
      "Faster production of all districts",
      "MODIFIER_PLAYER_CITIES_ADJUST_ALL_DISTRICTS_PRODUCTION", [PERCENT],
      "cities", "+{Amount}% Production towards districts"),
    T("building_production", "Production", "Faster building production",
      "MODIFIER_PLAYER_CITIES_ADJUST_BUILDING_PRODUCTION",
      [PERCENT, ("BuildingType", "building", "Building", "")], "cities",
      "+{Amount}% Production towards {BuildingType}"),
    T("unit_production", "Production", "Faster unit production",
      "MODIFIER_PLAYER_CITIES_ADJUST_UNIT_TAG_ERA_PRODUCTION",
      [PERCENT, ("UnitPromotionClass", "promotion_class", "Unit class", ""),
       ("EraType", "era", "Units of era", "ERA_ANCIENT")], "cities",
      "+{Amount}% Production towards {EraType} {UnitPromotionClass} units",
      help="One era per effect, like the game's own bonuses (add one per "
           "era for more)."),
    # -- great people
    T("gpp_cities", "Great people", "Great person points in every city",
      "MODIFIER_PLAYER_CITIES_ADJUST_GREAT_PERSON_POINT",
      [AMOUNT, ("GreatPersonClassType", "great_person", "Great person",
                "GREAT_PERSON_CLASS_SCIENTIST")], "cities",
      "+{Amount} {GreatPersonClassType} points in every city"),
    T("gpp_player", "Great people", "Great person points",
      "MODIFIER_PLAYER_ADJUST_GREAT_PERSON_POINTS",
      [AMOUNT, ("GreatPersonClassType", "great_person", "Great person",
                "GREAT_PERSON_CLASS_SCIENTIST")], "player",
      "+{Amount} {GreatPersonClassType} points per turn"),
    T("gpp_city", "Great people", "Great person points in this city",
      "MODIFIER_SINGLE_CITY_ADJUST_GREAT_PERSON_POINT",
      [AMOUNT, ("GreatPersonClassType", "great_person", "Great person",
                "GREAT_PERSON_CLASS_SCIENTIST")], "city",
      "+{Amount} {GreatPersonClassType} points in this city"),
    # -- cities
    T("housing", "Cities", "Housing in every city",
      "MODIFIER_PLAYER_CITIES_ADJUST_POLICY_HOUSING", [AMOUNT], "cities",
      "+{Amount} Housing in every city"),
    T("amenities", "Cities", "Amenities in every city",
      "MODIFIER_PLAYER_CITIES_ADJUST_TRAIT_AMENITY", [AMOUNT], "cities",
      "+{Amount} Amenities in every city"),
    T("city_housing", "Cities", "Housing in this city",
      "MODIFIER_SINGLE_CITY_ADJUST_BUILDING_HOUSING", [AMOUNT], "city",
      "+{Amount} Housing in this city"),
    T("free_unit", "Cities", "Free unit in this city",
      "MODIFIER_SINGLE_CITY_GRANT_UNIT_IN_CITY",
      [("UnitType", "unit", "Unit", "UNIT_BUILDER"),
       ("Amount", "int", "How many", "1")], "city",
      "Grants {Amount} {UnitType} when completed", run_once=True,
      permanent=True),
    T("culture_bomb_district", "Cities", "Culture bomb: district",
      "MODIFIER_PLAYER_ADD_CULTURE_BOMB_TRIGGER",
      [("DistrictType", "district", "District", "")], "player",
      "Completing a {DistrictType} claims the surrounding tiles"),
    T("culture_bomb_improvement", "Cities", "Culture bomb: improvement",
      "MODIFIER_PLAYER_ADD_CULTURE_BOMB_TRIGGER",
      [("ImprovementType", "improvement", "Improvement", "")], "player",
      "Building a {ImprovementType} claims the surrounding tiles"),
    # -- empire
    T("tourism", "Empire", "Tourism percentage",
      "MODIFIER_PLAYER_ADJUST_TOURISM", [PERCENT], "player",
      "+{Amount}% Tourism"),
    T("trade_capacity", "Empire", "Trade route capacity",
      "MODIFIER_PLAYER_ADJUST_TRADE_ROUTE_CAPACITY", [AMOUNT], "player",
      "+{Amount} Trade Route capacity"),
    T("trade_domestic", "Empire", "Domestic trade route yield",
      "MODIFIER_PLAYER_ADJUST_TRADE_ROUTE_YIELD_FOR_DOMESTIC",
      [AMOUNT, YIELD], "player",
      "+{Amount} {YieldType} from domestic trade routes"),
    T("trade_international", "Empire", "International trade route yield",
      "MODIFIER_PLAYER_ADJUST_TRADE_ROUTE_YIELD_FOR_INTERNATIONAL",
      [AMOUNT, YIELD], "player",
      "+{Amount} {YieldType} from international trade routes"),
    T("envoys", "Empire", "Envoys",
      "MODIFIER_PLAYER_GRANT_INFLUENCE_TOKEN", [AMOUNT], "player",
      "+{Amount} Envoys", run_once=True, permanent=True),
    T("governor_points", "Empire", "Governor titles",
      "MODIFIER_PLAYER_ADJUST_GOVERNOR_POINTS",
      [("Delta", "int", "Titles", "1")], "player",
      "+{Delta} Governor Titles", run_once=True, permanent=True),
    # -- units
    T("combat_strength", "Units", "Combat strength",
      "MODIFIER_UNIT_ADJUST_COMBAT_STRENGTH", [AMOUNT], "unit",
      "+{Amount} Combat Strength",
      help="Requirements such as 'attacking' or 'fighting a unit of class' "
           "limit when the bonus applies."),
    T("movement", "Units", "Movement",
      "MODIFIER_PLAYER_UNIT_ADJUST_MOVEMENT", [AMOUNT], "unit",
      "+{Amount} Movement"),
    T("sight", "Units", "Sight", "MODIFIER_PLAYER_UNIT_ADJUST_SIGHT",
      [AMOUNT], "unit", "+{Amount} Sight"),
    T("experience", "Units", "Experience percentage",
      "MODIFIER_PLAYER_UNIT_ADJUST_UNIT_EXPERIENCE_MODIFIER", [PERCENT],
      "unit", "+{Amount}% combat experience"),
    T("heal", "Units", "Healing per turn",
      "MODIFIER_PLAYER_UNIT_ADJUST_HEAL_PER_TURN",
      [AMOUNT, ("Type", "heal_type", "Where", "ALL")], "unit",
      "+{Amount} HP healed per turn ({Type})"),
    T("ignore_terrain", "Units", "Ignore terrain movement cost",
      "MODIFIER_PLAYER_UNIT_ADJUST_IGNORE_TERRAIN_COST",
      [("Type", "terrain_cost", "Terrain", "HILLS"),
       ("Ignore", "fixed", "", "1")], "unit",
      "Ignores the movement cost of {Type}"),
    T("ignore_zoc", "Units", "Ignore zone of control",
      "MODIFIER_PLAYER_UNIT_ADJUST_IGNORE_ZOC", [("Ignore", "fixed", "", "1")],
      "unit", "Ignores zone of control"),
]
TEMPLATES = {t.id: t for t in TEMPLATES}

# What effects belong to: the owner kind, the table linking an owner to
# its modifiers (and its type column) and the scopes of the templates it
# may use
Owner = namedtuple("Owner", "id table column scopes")
OWNERS = {o.id: o for o in [
    Owner("trait", "TraitModifiers", "TraitType",
          ("player", "cities", "unit")),
    Owner("building", "BuildingModifiers", "BuildingType",
          ("player", "cities", "city", "unit")),
    Owner("district", "DistrictModifiers", "DistrictType",
          ("player", "cities", "city", "unit")),
    # (an improvement's modifiers are owned by its tile: player-wide
    # effects work, single-city ones would need the tile's city)
    Owner("improvement", "ImprovementModifiers", "ImprovementType",
          ("player", "cities", "unit")),
    # a unique unit: through a unit ability of its own (see effects_sql)
    Owner("unit", None, None, ("unit",)),
    # the effect another effect attaches (see "attached"): it applies to
    # whatever the attaching one collects, so any template may do
    Owner("attached", None, None, ("player", "cities", "city", "unit")),
]}
# owner kind -> scopes its effects may have
OWNER_SCOPES = {o.id: o.scopes for o in OWNERS.values()}


def templates_for(owner):
    """The templates an owner kind ("trait", "building", "district",
    "unit") can use, in TEMPLATES order."""
    return [t for t in TEMPLATES.values() if t.scope in OWNER_SCOPES[owner]]


# ---------------------------------------------------------------------------
# Requirements ("only when ...")
# ---------------------------------------------------------------------------
# target: which requirement set the requirement joins
#   subject - what the effect applies to (city, district, tile, unit...)
#   owner   - the owner (the player of an ability, the city of a building)
#   units   - which of the player's units get a unit effect granted by an
#             ability, building or district (a unique unit's own effects
#             apply to it only, so there it joins the subject set)

Preset = namedtuple("Preset", "id label requirement_type arg kind target")
REQUIREMENTS = [
    Preset("city_district", "City has district", "REQUIREMENT_CITY_HAS_DISTRICT",
           "DistrictType", "district", "subject"),
    Preset("city_building", "City has building", "REQUIREMENT_CITY_HAS_BUILDING",
           "BuildingType", "building", "subject"),
    Preset("district_is", "District is", "REQUIREMENT_DISTRICT_TYPE_MATCHES",
           "DistrictType", "district", "subject"),
    Preset("plot_terrain", "Tile terrain is",
           "REQUIREMENT_PLOT_TERRAIN_TYPE_MATCHES", "TerrainType", "terrain",
           "subject"),
    Preset("plot_feature", "Tile feature is",
           "REQUIREMENT_PLOT_FEATURE_TYPE_MATCHES", "FeatureType", "feature",
           "subject"),
    Preset("plot_improvement", "Tile improvement is",
           "REQUIREMENT_PLOT_IMPROVEMENT_TYPE_MATCHES", "ImprovementType",
           "improvement", "subject"),
    Preset("plot_resource", "Tile resource is",
           "REQUIREMENT_PLOT_RESOURCE_TYPE_MATCHES", "ResourceType",
           "resource", "subject"),
    Preset("plot_river", "Tile is next to a river",
           "REQUIREMENT_PLOT_ADJACENT_TO_RIVER", None, None, "subject"),
    Preset("plot_hills", "Tile is hills", "REQUIREMENT_PLOT_IS_HILLS", None,
           None, "subject"),
    Preset("plot_coastal", "Tile is coastal land",
           "REQUIREMENT_PLOT_IS_COASTAL_LAND", None, None, "subject"),
    Preset("has_tech", "Player has technology",
           "REQUIREMENT_PLAYER_HAS_TECHNOLOGY", "TechnologyType", "tech",
           "owner"),
    Preset("has_civic", "Player has civic", "REQUIREMENT_PLAYER_HAS_CIVIC",
           "CivicType", "civic", "owner"),
    Preset("era", "Player's era is at least",
           "REQUIREMENT_PLAYER_ERA_AT_LEAST", "EraType", "era", "owner"),
    Preset("unit_class", "Unit class is",
           "REQUIREMENT_UNIT_PROMOTION_CLASS_MATCHES", "UnitPromotionClass",
           "promotion_class", "units"),
    Preset("unit_type", "Unit is", "REQUIREMENT_UNIT_TYPE_MATCHES",
           "UnitType", "unit", "units"),
    Preset("unit_domain", "Unit domain is", "REQUIREMENT_UNIT_DOMAIN_MATCHES",
           "UnitDomain", "domain", "units"),
    Preset("opponent_class", "Fighting a unit of class",
           "REQUIREMENT_OPPONENT_UNIT_PROMOTION_CLASS_MATCHES",
           "UnitPromotionClass", "promotion_class", "subject"),
    Preset("attacking", "Unit is attacking", "REQUIREMENT_PLAYER_IS_ATTACKING",
           None, None, "subject"),
    Preset("own_territory", "Unit is in own territory",
           "REQUIREMENT_UNIT_IN_OWNER_TERRITORY", None, None, "subject"),
    Preset("enemy_territory", "Unit is in enemy territory",
           "REQUIREMENT_UNIT_IN_ENEMY_TERRITORY", None, None, "subject"),
]
REQUIREMENTS = {p.id: p for p in REQUIREMENTS}


# ---------------------------------------------------------------------------
# Validation and summaries
# ---------------------------------------------------------------------------

def new_effect(template_id):
    t = TEMPLATES[template_id]
    return {"template": template_id,
            "args": {a.name: a.default for a in t.args},
            "reqs": []}


# -- raw effects and requirements (advanced mode) --------------------------

# set_types values -> RequirementSetType
SET_TYPES = {"ALL": "REQUIREMENTSET_TEST_ALL",
             "ANY": "REQUIREMENTSET_TEST_ANY"}
TARGETS = ("subject", "owner", "units")
ARG_TYPES = ("ARGTYPE_IDENTITY", "ScaleByGameSpeed",
             "LinearScaleFromDefaultHandicap")
# optional columns of a copied game modifier / requirement -> their default
MODIFIER_COLUMNS = {"NewOnly": 0, "Repeatable": 0, "OwnerStackLimit": None,
                    "SubjectStackLimit": None}
REQUIREMENT_COLUMNS = {"Likeliness": 0, "Impact": 0, "Reverse": 0,
                       "Persistent": 0, "ProgressWeight": 1, "Triggered": 0}
STRING_CONTEXTS = ("Preview", "Summary", "Sample")
MAX_DEPTH = 3           # effects attaching effects attaching effects
NESTED_SET = "REQUIREMENT_REQUIREMENTSET_IS_MET"

# argument name -> the kind of value it takes (a KIND_LISTS or ENUMS key),
# for raw effects' dropdowns and summaries; others are typed in
ARG_KINDS = {
    "YieldType": "yield", "DistrictType": "district",
    "BuildingType": "building", "UnitType": "unit",
    "TerrainType": "terrain", "FeatureType": "feature",
    "ResourceType": "resource", "ImprovementType": "improvement",
    "EraType": "era", "StartEraType": "era", "EndEraType": "era",
    "TechnologyType": "tech", "TechType": "tech", "CivicType": "civic",
    "GreatPersonClassType": "great_person",
    "UnitPromotionClass": "promotion_class",
    "PromotionClassType": "promotion_class", "UnitDomain": "domain",
    "AbilityType": "ability",
}

TYPE_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
# (one of the game's requirements has an argument "Min Turns")
ARG_NAME = re.compile(r"^[A-Za-z](?:[A-Za-z0-9_ ]*[A-Za-z0-9_])?$")


def is_raw(effect):
    """Whether an effect is a raw one (any game modifier type) rather than
    one of TEMPLATES."""
    return not effect.get("template") and "modifier_type" in effect


def new_raw_effect(modifier_type="", args=None):
    return {"modifier_type": modifier_type, "args": dict(args or {}),
            "reqs": [], "run_once": False, "permanent": False}


def req_kind(req):
    """"preset", "raw" or "group": the form of a requirement."""
    if "group" in req:
        return "group"
    return "preset" if "preset" in req else "raw"


def req_target(req):
    """The requirement set ("subject", "owner", "units") it joins."""
    if req_kind(req) == "preset":
        p = REQUIREMENTS.get(req.get("preset"))
        return p.target if p else "subject"
    return req.get("target") or "subject"


def is_advanced(effect):
    """Whether an effect needs the advanced editor: a raw effect, one
    with raw or grouped requirements, or a set met by any requirement."""
    return (is_raw(effect) or
            any(v != "ALL" for v in (effect.get("set_types") or {}).values())
            or any(req_kind(r) != "preset" for r in effect.get("reqs") or []))


def usual_args(found, uses, skip=()):
    """{name: an example value} of the arguments every one of the game's
    uses of a type gives it, from found ([(name, uses, example, numeric)],
    see GameData.modifier_args) and uses (how often the game uses the
    type), but those in skip: what a new raw effect / requirement of the
    type starts with."""
    return {name: example for name, n, example, _ in found
            if uses and n >= uses and name not in skip}


def readable_type(type_name, prefixes=("MODIFIER_", "PLAYER_", "SINGLE_")):
    """A game type as words, without its kind's prefixes:
    MODIFIER_PLAYER_GRANT_YIELD -> 'Grant yield'."""
    what = type_name or ""
    for word in prefixes:
        what = what[len(word):] if what.startswith(word) else what
    return what.replace("_", " ").strip().capitalize()


def check_effect(effect, owner, data=None, depth=0):
    """Raise ValueError if an effect is unusable for the owner kind. With
    the game data loaded (data.conn), the modifier and requirement types,
    modifiers and requirement sets it names must be the game's too."""
    known = bool(getattr(data, "conn", None))
    if is_raw(effect):
        label = _check_raw(effect, data, known, depth)
    else:
        t = TEMPLATES.get(effect.get("template"))
        if not t:
            raise ValueError("unknown effect '{}'".format(
                effect.get("template")))
        label = t.label
        if t.scope not in OWNER_SCOPES[owner]:
            raise ValueError("'{}' cannot be used here".format(t.label))
        args = effect.get("args") or {}
        for a in t.args:
            value = str(args.get(a.name, a.default) or "").strip()
            if a.kind in ("text", "fixed"):
                continue
            if not value:
                raise ValueError("'{}' needs a {}".format(t.label,
                                                          a.label.lower()))
            if a.kind in NUMBER_KINDS:
                try:
                    (int if a.kind == "int" else float)(value)
                except ValueError:
                    raise ValueError("'{}': {} must be a number".format(
                        t.label, a.label.lower()))
    for target, set_type in (effect.get("set_types") or {}).items():
        if target not in TARGETS or set_type not in SET_TYPES:
            raise ValueError("'{}': unknown requirement set {} {}".format(
                label, target, set_type))
    _check_reqs(effect.get("reqs") or [], label, data, known)


def check_effects(effects, owner, data, label):
    """check_effect of each of an owner's effects; the ValueError names
    the owner (label) and the effect."""
    for n, effect in enumerate(effects or [], 1):
        try:
            check_effect(effect, owner, data)
        except ValueError as exc:
            raise ValueError("{}: effect {} - {}.".format(label, n, exc))


def _check_raw(effect, data, known, depth):
    """check_effect of a raw effect; returns its label."""
    t = str(effect.get("modifier_type") or "").strip()
    label = readable_type(t) or "effect"
    if not TYPE_NAME.match(t):
        raise ValueError("an effect needs a modifier type (MODIFIER_...), "
                         "not '{}'".format(t))
    if known and not data.has_modifier_type(t):
        raise ValueError("the game has no modifier type {} (one of an "
                         "expansion or DLC not on in the last game "
                         "played?)".format(t))
    args = effect.get("args") or {}
    attached = effect.get("attached")
    for name, value in args.items():
        if not ARG_NAME.match(str(name)):
            raise ValueError("'{}': '{}' is not an argument name".format(
                label, name))
        if not str(value).strip() and not (attached and name == "ModifierId"):
            raise ValueError("'{}': argument {} has no value".format(
                label, name))
    for name, spec in (effect.get("arg_types") or {}).items():
        if (spec or {}).get("Type", "ARGTYPE_IDENTITY") not in ARG_TYPES:
            raise ValueError("'{}': unknown type of argument {}".format(
                label, name))
    for column in effect.get("columns") or {}:
        if column not in MODIFIER_COLUMNS:
            raise ValueError("'{}': unknown column {}".format(label, column))
    for context in effect.get("strings") or {}:
        if context not in STRING_CONTEXTS:
            raise ValueError("'{}': unknown text {}".format(label, context))
    if attached:
        if depth >= MAX_DEPTH:
            raise ValueError("'{}': effects attach effects only {} deep"
                             .format(label, MAX_DEPTH))
        if known and not data.is_attach(t):
            raise ValueError("'{}' does not attach another effect".format(
                label))
        check_effect(attached, "attached", data, depth + 1)
    elif known and data.is_attach(t):
        mod = str(args.get("ModifierId") or "").strip()
        if not mod:
            raise ValueError("'{}' needs the effect it attaches (or the "
                             "ModifierId of one of the game's)".format(label))
        if not data.has_modifier(mod):
            raise ValueError("'{}': the game has no modifier {}".format(
                label, mod))
    return label


def _check_reqs(reqs, label, data, known, grouped=False):
    for req in reqs:
        kind = req_kind(req)
        if kind != "preset" and req.get("target", "subject") not in TARGETS:
            raise ValueError("'{}': unknown requirement target '{}'".format(
                label, req.get("target")))
        if kind == "group":
            if grouped:
                raise ValueError("'{}': a group of requirements cannot "
                                 "hold another group".format(label))
            if req.get("group") not in SET_TYPES:
                raise ValueError("'{}': a group of requirements is 'ALL' or "
                                 "'ANY', not '{}'".format(label,
                                                          req.get("group")))
            if not req.get("reqs"):
                raise ValueError("'{}': an empty group of requirements"
                                 .format(label))
            _check_reqs(req["reqs"], label, data, known, True)
        elif kind == "preset":
            p = REQUIREMENTS.get(req.get("preset"))
            if not p:
                raise ValueError("'{}': unknown requirement '{}'".format(
                    label, req.get("preset")))
            if p.arg and not str(req.get("value") or "").strip():
                raise ValueError("'{}': requirement '{}' needs a value"
                                 .format(label, p.label))
        else:
            t = str(req.get("type") or "").strip()
            if not TYPE_NAME.match(t):
                raise ValueError("'{}': a requirement needs a type "
                                 "(REQUIREMENT_...), not '{}'".format(
                                     label, t))
            if known and not data.has_requirement_type(t):
                raise ValueError("'{}': the game has no requirement type {}"
                                 .format(label, t))
            for name, value in (req.get("args") or {}).items():
                if not ARG_NAME.match(str(name)) or not str(value).strip():
                    raise ValueError("'{}': requirement {} needs a name and "
                                     "a value for each argument".format(
                                         label, readable_type(
                                             t, ("REQUIREMENT_",))))
                if known and name == "RequirementSetId" and \
                        not data.has_requirement_set(str(value).strip()):
                    raise ValueError("'{}': the game has no requirement set "
                                     "{}".format(label, value))
            for column in req.get("columns") or {}:
                if column not in REQUIREMENT_COLUMNS:
                    raise ValueError("'{}': unknown requirement column {}"
                                     .format(label, column))


def effect_warnings(effect, owner, data):
    """[message] of what may not work as meant in a raw effect, from how
    the game uses its modifier type; never blocking. Empty without the
    game data."""
    if not is_raw(effect) or not getattr(data, "conn", None):
        return []
    t = str(effect.get("modifier_type") or "").strip()
    info = data.modifier_info(t)
    if not info:
        return []
    out = []
    args = effect.get("args") or {}
    used = {name: (uses, example, numeric)
            for name, uses, example, numeric in info["args"]}
    if used:
        for name in args:
            if name not in used:
                out.append("The game never gives {} an argument {}.".format(
                    t, name))
    for name, (uses, example, numeric) in used.items():
        if name not in args:
            if uses >= info["uses"] and not (
                    name == "ModifierId" and effect.get("attached")):
                out.append("The game always gives it {} (e.g. {}).".format(
                    name, example))
        elif numeric and not is_number(args[name]):
            out.append("{} is a number wherever the game uses it (e.g. {})."
                       .format(name, example))
    if info["collection"] == "COLLECTION_OWNER":
        if "UNIT" in info["effect"] and owner not in ("unit", "attached"):
            out.append("It changes its owner, and the owner of a {}'s "
                       "effects is not a unit: attach it to units instead "
                       "(e.g. MODIFIER_PLAYER_UNITS_ATTACH_MODIFIER)."
                       .format(owner))
        elif "CITY" in info["effect"] and owner in ("trait", "improvement"):
            out.append("It changes its owner, which for a {}'s effects is "
                       "not a city: attach it to cities instead (e.g. "
                       "MODIFIER_PLAYER_CITIES_ATTACH_MODIFIER)."
                       .format("leader or civilization ability"
                               if owner == "trait" else owner))
    return out


def _display(kind, value, name_of):
    if kind in ENUMS:
        return dict(ENUMS[kind]).get(value, value)
    if kind in KIND_LISTS and value:
        return name_of(KIND_LISTS[kind], value)
    return value


def _arg_display(name, value, name_of):
    """An argument's value for summaries."""
    value = str(value).strip()
    if name in ARG_KINDS:
        return _display(ARG_KINDS[name], value, name_of)
    return type_display_name(value) if value.isupper() and "_" in value \
        else value


def _args_text(args, name_of, skip=()):
    return ", ".join("{} {}".format(name, _arg_display(name, value, name_of))
                     for name, value in sorted(args.items())
                     if name not in skip)


def summary(effect, name_of=lambda kind, t: type_display_name(t)):
    """One line describing an effect, e.g. '+2 Science in every city
    (only if: City has district Campus)'. name_of(kind, type) gives a
    type's display name."""
    if is_raw(effect):
        text = _raw_summary(effect, name_of)
    else:
        t = TEMPLATES.get(effect.get("template"))
        if not t:
            return "(unknown effect {})".format(effect.get("template"))
        args = effect.get("args") or {}
        values = {a.name: _display(a.kind,
                                   str(args.get(a.name, a.default) or ""),
                                   name_of) for a in t.args}
        text = t.text.format(**values)
    set_types = effect.get("set_types") or {}
    by_target = {}
    for req in effect.get("reqs") or []:
        label = _req_label(req, name_of)
        if label:
            by_target.setdefault(req_target(req), []).append(label)
    clauses = []
    for target, labels in by_target.items():
        if set_types.get(target) == "ANY" and len(labels) > 1:
            clauses.append("any of ({})".format("; ".join(labels)))
        else:
            clauses += labels
    if clauses:
        text += " (only if: {})".format("; ".join(clauses))
    return text


def _raw_summary(effect, name_of):
    text = (effect.get("text") or "").strip()
    if text:
        return text
    attached = effect.get("attached")
    what = readable_type(effect.get("modifier_type")) or "(no modifier type)"
    args = _args_text(effect.get("args") or {}, name_of,
                      ("ModifierId",) if attached else ())
    if attached:
        return "{}{}: {}".format(what, " ({})".format(args) if args else "",
                                 summary(attached, name_of))
    return what + (": " + args if args else "")


def _req_label(req, name_of):
    """A requirement in words, e.g. 'not: City has district Campus'."""
    kind = req_kind(req)
    if kind == "group":
        labels = [_req_label(r, name_of) for r in req.get("reqs") or []]
        label = "{} of ({})".format(
            "any" if req.get("group") == "ANY" else "all",
            "; ".join(filter(None, labels)))
    elif kind == "preset":
        p = REQUIREMENTS.get(req.get("preset"))
        if not p:
            return ""
        label = p.label
        if p.arg:
            label += " " + _display(p.kind, req.get("value") or "", name_of)
    else:
        label = readable_type(req.get("type"), ("REQUIREMENT_",))
        args = req.get("args") or {}
        if len(args) == 1:
            (name, value), = args.items()
            label += " " + _arg_display(name, value, name_of)
        elif args:
            label += " ({})".format(_args_text(args, name_of))
    return ("not: " if req.get("not") else "") + label


# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

# owner kind -> (table linking an owner to its modifiers, type column)
LINK_TABLES = {o.id: (o.table, o.column) for o in OWNERS.values()
               if o.table}


def _short(type_name):
    """A type without its kind prefix: UNIT_RFVS_X -> RFVS_X."""
    return type_name.split("_", 1)[-1]


def _sql_value(value):
    if value is None:
        return "NULL"
    if isinstance(value, (bool, int)):
        return str(int(value))
    return sql_str(str(value))


def _insert(table, row):
    """An INSERT of one row given as [(column, value)]."""
    return "INSERT INTO {} ({}) VALUES ({});".format(
        table, ", ".join(c for c, _ in row),
        ", ".join(_sql_value(v) for _, v in row))


class _Writer:
    """Collects the rows of one owner's effects."""

    def __init__(self, owner_id):
        self.owner_id = owner_id
        self.lines = []
        self.texts = []                 # (tag, English text)

    def modifier(self, mod_id, t_type, args, run_once=False,
                 permanent=False, subject_reqs=(), owner_reqs=(),
                 set_types=None, columns=None, arg_types=None,
                 strings=None):
        """The rows of one modifier. args: [(name, value)]; the
        requirements are editor requirements (see the module docstring);
        set_types, columns, arg_types and strings as in a raw effect."""
        set_types = set_types or {}
        subject = self.req_set(mod_id + "_SUBJECT_REQS", subject_reqs,
                               set_types.get("subject"))
        owner = self.req_set(mod_id + "_OWNER_REQS", owner_reqs,
                             set_types.get("owner"))
        extra = "".join(", {}".format(c) for c in sorted(columns or {}))
        self.lines.append(
            "INSERT INTO Modifiers (ModifierId, ModifierType, RunOnce, "
            "Permanent, SubjectRequirementSetId, OwnerRequirementSetId{})\n"
            "VALUES ({}, {}, {}, {}, {}, {}{});".format(
                extra, sql_str(mod_id), sql_str(t_type), int(bool(run_once)),
                int(bool(permanent)), sql_str(subject) if subject else "NULL",
                sql_str(owner) if owner else "NULL",
                "".join(", " + _sql_value(columns[c])
                        for c in sorted(columns or {}))))
        if args and arg_types:
            self.lines.append(
                "INSERT INTO ModifierArguments (ModifierId, Name, Type, "
                "Value, Extra, SecondExtra) VALUES\n{};".format(",\n".join(
                    "({}, {}, {}, {}, {}, {})".format(
                        sql_str(mod_id), sql_str(name),
                        sql_str(spec.get("Type") or "ARGTYPE_IDENTITY"),
                        sql_str(value), _sql_value(spec.get("Extra")),
                        _sql_value(spec.get("SecondExtra")))
                    for name, value, spec in (
                        (n, v, arg_types.get(n) or {}) for n, v in args))))
        elif args:
            self.lines.append(
                "INSERT INTO ModifierArguments (ModifierId, Name, Type, "
                "Value) VALUES\n{};".format(",\n".join(
                    "({}, {}, 'ARGTYPE_IDENTITY', {})".format(
                        sql_str(mod_id), sql_str(name), sql_str(value))
                    for name, value in args)))
        for context, text in sorted((strings or {}).items()):
            self.lines.append(_insert("ModifierStrings", [
                ("ModifierId", mod_id), ("Context", context),
                ("Text", text)]))

    def req_set(self, set_id, reqs, set_type=None):
        """The rows of a requirement set of editor requirements (see the
        module docstring); set_type "ALL" (default) or "ANY". Returns the
        set id, or None for no requirements."""
        if not reqs:
            return None
        self.lines.append(
            "INSERT INTO RequirementSets (RequirementSetId, "
            "RequirementSetType) VALUES ({}, {});".format(
                sql_str(set_id), sql_str(SET_TYPES[set_type or "ALL"])))
        for i, req in enumerate(reqs, 1):
            req_id = "{}_{}".format(set_id, i)
            kind = req_kind(req)
            if kind == "group":
                # a set of its own, met when the group is
                inner = self.req_set(req_id + "_SET", req["reqs"],
                                     req["group"])
                self.requirement(req_id, NESTED_SET,
                                 [("RequirementSetId", inner)],
                                 req.get("not"))
            elif kind == "preset":
                p = REQUIREMENTS[req["preset"]]
                value = str(req.get("value") or "").strip()
                self.requirement(req_id, p.requirement_type,
                                 [(p.arg, value)] if p.arg else [],
                                 req.get("not"))
            else:
                self.requirement(
                    req_id, str(req["type"]).strip(),
                    [(n, str(v).strip()) for n, v in
                     sorted((req.get("args") or {}).items())],
                    req.get("not"), req.get("columns"))
            self.lines.append(
                "INSERT INTO RequirementSetRequirements (RequirementSetId, "
                "RequirementId) VALUES ({}, {});".format(
                    sql_str(set_id), sql_str(req_id)))
        return set_id

    def requirement(self, req_id, req_type, args, inverse, columns=None):
        self.lines.append(_insert("Requirements", [
            ("RequirementId", req_id), ("RequirementType", req_type),
            ("Inverse", int(bool(inverse)))] + sorted(
                (columns or {}).items())))
        for name, value in args:
            self.lines.append(
                "INSERT INTO RequirementArguments (RequirementId, Name, "
                "Type, Value) VALUES ({}, {}, 'ARGTYPE_IDENTITY', {});"
                .format(sql_str(req_id), sql_str(name), sql_str(value)))

    def ability(self, ability, name, desc, inactive, tags_sql):
        """A unit ability (KIND_ABILITY) with its text."""
        self.lines.append(
            "INSERT INTO Types (Type, Kind) VALUES ({0}, 'KIND_ABILITY');\n"
            "INSERT INTO UnitAbilities (UnitAbilityType, Name, Description, "
            "Inactive, Permanent) VALUES ({0}, {1}, {2}, {3}, 1);\n{4}"
            .format(sql_str(ability), sql_str("LOC_{}_NAME".format(ability)),
                    sql_str("LOC_{}_DESCRIPTION".format(ability)),
                    int(inactive), tags_sql))
        self.texts += [("LOC_{}_NAME".format(ability), name),
                       ("LOC_{}_DESCRIPTION".format(ability), desc)]


def _arguments(effect, t, mod_id, writer, name_of):
    """[(name, value)] of an effect; text arguments become text tags."""
    given = effect.get("args") or {}
    out = []
    for a in t.args:
        value = str(given.get(a.name, a.default) or "").strip()
        if a.kind == "fixed":
            value = a.default
        elif a.kind == "text" and value.startswith("LOC_"):
            pass                        # the game's own text (copied)
        elif a.kind == "text":
            tag = "LOC_{}_{}".format(mod_id, a.name.upper())
            writer.texts.append((tag, value or _auto_text(effect, t,
                                                          name_of)))
            value = tag
        out.append((a.name, value))
    return out


def _auto_text(effect, t, name_of):
    """Default adjacency tooltip, e.g. '+{1_num} [ICON_Science] Science
    from the adjacent Mountain.'"""
    args = effect.get("args") or {}
    yield_type = args.get("YieldType", "")
    what = next((name_of(KIND_LISTS[a.kind], args.get(a.name))
                 for a in t.args if a.name in ("FeatureType", "TerrainType",
                                               "ImprovementType")
                 and args.get(a.name)), "district")
    return "+{{1_num}} {} {} from the adjacent {}.".format(
        YIELD_ICONS.get(yield_type, ""), name_of("yield", yield_type),
        what).replace("  ", " ")


def effects_sql(owner, owner_type, effects, display_name,
                name_of=lambda kind, t: type_display_name(t)):
    """SQL for an owner's effects. owner: "trait", "building", "district"
    or "unit"; owner_type: its type (TRAIT_..., BUILDING_..., UNIT_...);
    display_name: the owner's English name (unit ability and combat
    preview text). Returns (sql, [(text tag, English text)]); empty
    effects give ("", [])."""
    if not effects:
        return "", []
    w = _Writer(owner_type)
    unit_ability = None
    if owner == "unit":
        # one always-active ability, tagged to a class only this unit has
        unit_ability = "ABILITY_" + _short(owner_type)
        tag = "CLASS_" + _short(owner_type)
        w.lines.append(
            "INSERT INTO Tags (Tag, Vocabulary) VALUES ({0}, 'ABILITY_CLASS');\n"
            "INSERT INTO TypeTags (Type, Tag) VALUES ({1}, {0});".format(
                sql_str(tag), sql_str(owner_type)))
        w.ability(unit_ability, display_name, "; ".join(
            summary(e, name_of) for e in effects), False,
            "INSERT INTO TypeTags (Type, Tag) VALUES ({}, {});".format(
                sql_str(unit_ability), sql_str(tag)))
    for n, effect in enumerate(effects, 1):
        check_effect(effect, owner)
        mod_id = "{}_MOD_{}".format(_short(owner_type), n)
        _write_effect(w, effect, mod_id, owner, display_name, name_of)
        if owner == "unit":
            w.lines.append(
                "INSERT INTO UnitAbilityModifiers (UnitAbilityType, "
                "ModifierId) VALUES ({}, {});".format(
                    sql_str(unit_ability), sql_str(mod_id)))
            continue
        table, column = LINK_TABLES[owner]
        w.lines.append("INSERT INTO {} ({}, ModifierId) VALUES ({}, {});"
                       .format(table, column, sql_str(owner_type),
                               sql_str(mod_id)))
    sql = "-- effects of {}\n{}\n".format(owner_type, "\n".join(w.lines))
    return sql, w.texts


def _write_effect(w, effect, mod_id, owner, display_name, name_of):
    """The rows of one effect as modifier mod_id (for its owner to link),
    and of the modifiers it needs: the effect it attaches, or the unit
    ability that holds a template's unit effect for a non-unit owner."""
    reqs = {target: [] for target in TARGETS}
    for req in effect.get("reqs") or []:
        reqs[req_target(req)].append(req)
    set_types = effect.get("set_types") or {}
    if is_raw(effect):
        args = [(name, str(value).strip()) for name, value in
                sorted((effect.get("args") or {}).items())]
        attached = effect.get("attached")
        if attached:
            inner = mod_id + "_ATTACHED"
            _write_effect(w, attached, inner, "attached", display_name,
                          name_of)
            args = [a for a in args if a[0] != "ModifierId"] + \
                [("ModifierId", inner)]
        modifier_type = str(effect["modifier_type"]).strip()
        w.modifier(mod_id, modifier_type, args, effect.get("run_once"),
                   effect.get("permanent"), reqs["subject"] + reqs["units"],
                   reqs["owner"], set_types, effect.get("columns"),
                   effect.get("arg_types"), effect.get("strings"))
        if "Preview" not in (effect.get("strings") or {}):
            _preview(w, mod_id, modifier_type, display_name)
        return
    t = TEMPLATES[effect["template"]]
    args = _arguments(effect, t, mod_id, w, name_of)
    if t.scope == "unit" and owner not in ("unit", "attached"):
        # the player's units get an ability that holds the effect; the
        # ability may apply to any unit class, the grant's requirements
        # pick the units
        ability = "ABILITY_{}_{}".format(*mod_id.rsplit("_MOD_", 1))
        w.ability(ability, display_name, summary(effect, name_of), True,
                  "INSERT INTO TypeTags (Type, Tag)\nSELECT {}, Tag FROM "
                  "Tags WHERE Vocabulary = 'ABILITY_CLASS';".format(
                      sql_str(ability)))
        inner = mod_id + "_EFFECT"
        w.modifier(inner, t.modifier_type, args, t.run_once, t.permanent,
                   reqs["subject"],
                   set_types={"subject": set_types.get("subject")})
        w.lines.append(
            "INSERT INTO UnitAbilityModifiers (UnitAbilityType, "
            "ModifierId) VALUES ({}, {});".format(
                sql_str(ability), sql_str(inner)))
        _preview(w, inner, t.modifier_type, display_name)
        w.modifier(mod_id, "MODIFIER_PLAYER_UNITS_GRANT_ABILITY",
                   [("AbilityType", ability)], subject_reqs=reqs["units"],
                   owner_reqs=reqs["owner"],
                   set_types={"subject": set_types.get("units"),
                              "owner": set_types.get("owner")})
        return
    w.modifier(mod_id, t.modifier_type, args, t.run_once, t.permanent,
               reqs["subject"] + reqs["units"], reqs["owner"], set_types)
    _preview(w, mod_id, t.modifier_type, display_name)


def _preview(w, mod_id, modifier_type, display_name):
    """Combat preview line for combat strength bonuses."""
    if modifier_type != "MODIFIER_UNIT_ADJUST_COMBAT_STRENGTH":
        return
    tag = "LOC_{}_PREVIEW".format(mod_id)
    w.lines.append("INSERT INTO ModifierStrings (ModifierId, Context, Text) "
                   "VALUES ({}, 'Preview', {});".format(sql_str(mod_id),
                                                        sql_str(tag)))
    w.texts.append((tag, "+{{1_Amount}} {}".format(display_name)))


# ---------------------------------------------------------------------------
# Descriptions written from effects
# ---------------------------------------------------------------------------

# words of effect summaries -> the game's icon tag shown before them (the
# longest first, so "Great Scientist" wins over "Great")
TEXT_ICONS = sorted({
    "Food": "[ICON_Food]", "Production": "[ICON_Production]",
    "Gold": "[ICON_Gold]", "Science": "[ICON_Science]",
    "Culture": "[ICON_Culture]", "Faith": "[ICON_Faith]",
    "Tourism": "[ICON_Tourism]", "Housing": "[ICON_Housing]",
    "Amenities": "[ICON_Amenities]", "Amenity": "[ICON_Amenities]",
    "Combat Strength": "[ICON_Strength]",
    "Combat strength": "[ICON_Strength]",
    "Ranged strength": "[ICON_Ranged]", "Range": "[ICON_Range]",
    "Bombard strength": "[ICON_Bombard]",
    "Movement": "[ICON_Movement]", "Trade Route": "[ICON_TradeRoute]",
    "trade routes": "[ICON_TradeRoute]", "Envoys": "[ICON_Envoy]",
    "Governor Titles": "[ICON_Governor]",
    "Great General": "[ICON_GreatGeneral]",
    "Great Admiral": "[ICON_GreatAdmiral]",
    "Great Engineer": "[ICON_GreatEngineer]",
    "Great Merchant": "[ICON_GreatMerchant]",
    "Great Prophet": "[ICON_GreatProphet]",
    "Great Scientist": "[ICON_GreatScientist]",
    "Great Writer": "[ICON_GreatWriter]",
    "Great Artist": "[ICON_GreatArtist]",
    "Great Musician": "[ICON_GreatMusician]",
}.items(), key=lambda kv: -len(kv[0]))


def with_icons(text):
    """text with the game's icon tag before each known word (+1 Faith ->
    +1 [ICON_Faith] Faith), once per word, never inside a tag."""
    import re
    # not inside a tag ([ICON_Faith]: after "_"), not after an icon
    pattern = re.compile(r"(?<![\w\]])(?<!\] )({})(?!\w)".format(
        "|".join(re.escape(word) for word, _ in TEXT_ICONS)))
    icons = dict(TEXT_ICONS)
    return pattern.sub(
        lambda m: "{} {}".format(icons[m.group(1)], m.group(1)), text)


def sentence(text):
    """A summary as a sentence: capitalised, ending with a full stop."""
    # (an adjacency without a label starts with its ": ")
    text = " ".join(text.split()).lstrip(": ")
    if not text:
        return ""
    text = text[0].upper() + text[1:]
    return text if text.endswith((".", "!", "?")) else text + "."


def describe_effects(effects, name_of=lambda kind, t: type_display_name(t)):
    """A description of effects in the game's style: one sentence per
    effect, with the game's icons (see with_icons). Lines are separated
    by newlines (the editors turn them into [NEWLINE])."""
    return "\n".join(with_icons(sentence(summary(e, name_of)))
                     for e in effects or [])




# ---------------------------------------------------------------------------
# The game's own modifiers (of an item a unique copies, or to import)
# ---------------------------------------------------------------------------

def _req_from_game(req, target):
    """A game requirement ({"type", "args", "inverse", "columns"}, see
    GameData.game_modifiers) as an editor requirement: a preset when one
    is exactly it, else a raw requirement."""
    columns = dict(req.get("columns") or {})
    if not columns:
        for p in REQUIREMENTS.values():
            if p.requirement_type == req["type"] and p.target == target \
                    and set(req["args"]) == ({p.arg} if p.arg else set()):
                return {"preset": p.id, "not": bool(req["inverse"]),
                        "value": req["args"].get(p.arg, "") if p.arg
                        else ""}
    out = {"type": req["type"], "args": dict(req["args"]),
           "not": bool(req["inverse"]), "target": target}
    if columns:
        out["columns"] = columns
    return out


def _reqs_from_game(mod):
    """The modifier's conditions as editor requirements, and its
    set_types."""
    reqs, set_types = [], {}
    for key, target in (("subject_reqs", "subject"), ("owner_reqs", "owner")):
        found = mod.get(key) or []
        if len(found) > 1 and (mod.get("set_types") or {}).get(key) == \
                SET_TYPES["ANY"]:
            set_types[target] = "ANY"
        reqs += [_req_from_game(req, target) for req in found]
    return reqs, set_types


def _template_for(mod, owner):
    """The template that is exactly the game's modifier mod for an owner
    kind (None: any), or None."""
    if mod.get("arg_types") or mod.get("columns") or mod.get("strings"):
        return None
    args = mod["args"]
    for t in TEMPLATES.values():
        if (t.modifier_type != mod["modifier_type"] or
                t.run_once != mod["run_once"] or
                t.permanent != mod["permanent"]):
            continue
        if owner and (t.scope not in OWNER_SCOPES[owner] or
                      t.scope == "unit" and owner not in ("unit",
                                                          "attached")):
            continue        # (a unit template would become a granted one)
        names = {a.name for a in t.args}
        needed = {a.name for a in t.args if a.kind != "text"}
        fixed = all(str(args.get(a.name, a.default)) == a.default
                    for a in t.args if a.kind == "fixed")
        lists = all("," not in str(args.get(a.name, "")) for a in t.args)
        if not (set(args) <= names and needed <= set(args) and fixed and
                lists):
            continue
        try:                # (values the template takes, e.g. numbers)
            check_effect({"template": t.id, "args": args}, owner or
                         "attached")
        except ValueError:
            continue
        return t
    return None


def effect_from_game(mod, owner=None):
    """An editor effect doing exactly what the game's modifier mod does
    (GameData.game_modifiers): one of TEMPLATES when one is exactly it,
    else a raw effect. owner: the owner kind it is for (a unit template
    on another owner would be given to units through an ability, so a
    raw effect is used there)."""
    reqs, set_types = _reqs_from_game(mod)
    t = _template_for(mod, owner)
    if t:
        effect = {"template": t.id,
                  "args": {a.name: mod["args"].get(a.name, a.default)
                           for a in t.args},
                  "reqs": reqs}
    else:
        effect = {"modifier_type": mod["modifier_type"],
                  "args": dict(mod["args"]), "reqs": reqs,
                  "run_once": bool(mod["run_once"]),
                  "permanent": bool(mod["permanent"])}
        for key in ("arg_types", "columns", "strings"):
            if mod.get(key):
                effect[key] = dict(mod[key])
    if set_types:
        effect["set_types"] = set_types
    return effect


def describe_game_modifier(mod, name_of=lambda kind, t: type_display_name(t),
                           read=None):
    """One line for a game modifier: the summary of its editor effect.
    read(ModifierId): another of the game's modifiers (GameData.
    read_modifier), to describe what one that attaches it does."""
    effect = effect_from_game(mod)
    attached = (effect.get("args") or {}).get("ModifierId")
    inner = read(attached) if read and is_raw(effect) and attached else None
    if inner:
        # (for the summary only: the copy attaches the game's modifier)
        effect = dict(effect, attached=effect_from_game(inner))
    return summary(effect, name_of)
