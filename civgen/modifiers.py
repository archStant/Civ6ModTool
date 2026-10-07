"""Effects ("modifiers") for abilities, buildings, districts and units.

An effect is a plain picklable dict the editor fills in:

    {"template": "city_yield",                  # a TEMPLATES key
     "args": {"Amount": "2", "YieldType": "YIELD_SCIENCE"},
     "reqs": [{"preset": "city_district",       # a REQUIREMENTS key
               "value": "DISTRICT_CAMPUS", "not": False}]}

effects_sql() turns a list of them into the game's Modifiers,
ModifierArguments, requirement and unit ability rows. Every template is a
modifier type the game itself uses with these arguments; the editor only
offers templates that work for the owner (see OWNER_SCOPES).
"""

from collections import namedtuple

from .util import sql_str, type_display_name


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

# owner kind -> scopes its effects may have
OWNER_SCOPES = {
    "trait": ("player", "cities", "unit"),
    "building": ("player", "cities", "city", "unit"),
    "district": ("player", "cities", "city", "unit"),
    # (an improvement's modifiers are owned by its tile: player-wide
    # effects work, single-city ones would need the tile's city)
    "improvement": ("player", "cities", "unit"),
    "unit": ("unit",),
}


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


def check_effect(effect, owner):
    """Raise ValueError if an effect is unusable for the owner kind."""
    t = TEMPLATES.get(effect.get("template"))
    if not t:
        raise ValueError("unknown effect '{}'".format(effect.get("template")))
    if t.scope not in OWNER_SCOPES[owner]:
        raise ValueError("'{}' cannot be used here".format(t.label))
    args = effect.get("args") or {}
    for a in t.args:
        value = str(args.get(a.name, a.default) or "").strip()
        if a.kind in ("text", "fixed"):
            continue
        if not value:
            raise ValueError("'{}' needs a {}".format(t.label, a.label.lower()))
        if a.kind in NUMBER_KINDS:
            try:
                (int if a.kind == "int" else float)(value)
            except ValueError:
                raise ValueError("'{}': {} must be a number".format(
                    t.label, a.label.lower()))
    for req in effect.get("reqs") or []:
        p = REQUIREMENTS.get(req.get("preset"))
        if not p:
            raise ValueError("'{}': unknown requirement '{}'".format(
                t.label, req.get("preset")))
        if p.arg and not str(req.get("value") or "").strip():
            raise ValueError("'{}': requirement '{}' needs a value".format(
                t.label, p.label))


def _display(kind, value, name_of):
    if kind in ENUMS:
        return dict(ENUMS[kind]).get(value, value)
    if kind in KIND_LISTS and value:
        return name_of(KIND_LISTS[kind], value)
    return value


def summary(effect, name_of=lambda kind, t: type_display_name(t)):
    """One line describing an effect, e.g. '+2 Science in every city
    (only if: City has district Campus)'. name_of(kind, type) gives a
    type's display name."""
    t = TEMPLATES.get(effect.get("template"))
    if not t:
        return "(unknown effect {})".format(effect.get("template"))
    args = effect.get("args") or {}
    values = {a.name: _display(a.kind, str(args.get(a.name, a.default) or ""),
                               name_of) for a in t.args}
    text = t.text.format(**values)
    reqs = []
    for req in effect.get("reqs") or []:
        p = REQUIREMENTS.get(req.get("preset"))
        if not p:
            continue
        label = ("not: " if req.get("not") else "") + p.label
        if p.arg:
            label += " " + _display(p.kind, req.get("value") or "", name_of)
        reqs.append(label)
    if reqs:
        text += " (only if: {})".format("; ".join(reqs))
    return text


# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

LINK_TABLES = {"trait": ("TraitModifiers", "TraitType"),
               "building": ("BuildingModifiers", "BuildingType"),
               "district": ("DistrictModifiers", "DistrictType"),
               "improvement": ("ImprovementModifiers", "ImprovementType")}


def _short(type_name):
    """A type without its kind prefix: UNIT_RFVS_X -> RFVS_X."""
    return type_name.split("_", 1)[-1]


class _Writer:
    """Collects the rows of one owner's effects."""

    def __init__(self, owner_id):
        self.owner_id = owner_id
        self.lines = []
        self.texts = []                 # (tag, English text)

    def modifier(self, mod_id, t_type, args, run_once=False,
                 permanent=False, subject_reqs=(), owner_reqs=()):
        subject = self.req_set(mod_id + "_SUBJECT_REQS", subject_reqs)
        owner = self.req_set(mod_id + "_OWNER_REQS", owner_reqs)
        self.lines.append(
            "INSERT INTO Modifiers (ModifierId, ModifierType, RunOnce, "
            "Permanent, SubjectRequirementSetId, OwnerRequirementSetId)\n"
            "VALUES ({}, {}, {}, {}, {}, {});".format(
                sql_str(mod_id), sql_str(t_type), int(run_once),
                int(permanent), sql_str(subject) if subject else "NULL",
                sql_str(owner) if owner else "NULL"))
        if args:
            self.lines.append(
                "INSERT INTO ModifierArguments (ModifierId, Name, Type, "
                "Value) VALUES\n{};".format(",\n".join(
                    "({}, {}, 'ARGTYPE_IDENTITY', {})".format(
                        sql_str(mod_id), sql_str(name), sql_str(value))
                    for name, value in args)))

    def req_set(self, set_id, reqs):
        """RequirementSets rows for (preset, value, inverse) triples;
        returns the set id, or None for no requirements."""
        if not reqs:
            return None
        self.lines.append(
            "INSERT INTO RequirementSets (RequirementSetId, "
            "RequirementSetType) VALUES ({}, 'REQUIREMENTSET_TEST_ALL');"
            .format(sql_str(set_id)))
        for i, (p, value, inverse) in enumerate(reqs, 1):
            req_id = "{}_{}".format(set_id, i)
            self.lines.append(
                "INSERT INTO Requirements (RequirementId, RequirementType, "
                "Inverse) VALUES ({}, {}, {});\n"
                "INSERT INTO RequirementSetRequirements (RequirementSetId, "
                "RequirementId) VALUES ({}, {});".format(
                    sql_str(req_id), sql_str(p.requirement_type),
                    int(bool(inverse)), sql_str(set_id), sql_str(req_id)))
            if p.arg:
                self.lines.append(
                    "INSERT INTO RequirementArguments (RequirementId, Name, "
                    "Type, Value) VALUES ({}, {}, 'ARGTYPE_IDENTITY', {});"
                    .format(sql_str(req_id), sql_str(p.arg),
                            sql_str(value)))
        return set_id

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
        t = TEMPLATES[effect["template"]]
        mod_id = "{}_MOD_{}".format(_short(owner_type), n)
        reqs = [(REQUIREMENTS[r["preset"]], (r.get("value") or "").strip(),
                 r.get("not")) for r in effect.get("reqs") or []]
        subject = [r for r in reqs if r[0].target == "subject"]
        owner_reqs = [r for r in reqs if r[0].target == "owner"]
        units = [r for r in reqs if r[0].target == "units"]
        args = _arguments(effect, t, mod_id, w, name_of)
        if t.scope == "unit" and owner == "unit":
            w.modifier(mod_id, t.modifier_type, args, t.run_once,
                       t.permanent, subject + units, owner_reqs)
            w.lines.append(
                "INSERT INTO UnitAbilityModifiers (UnitAbilityType, "
                "ModifierId) VALUES ({}, {});".format(
                    sql_str(unit_ability), sql_str(mod_id)))
            _preview(w, mod_id, t, display_name)
            continue
        if t.scope == "unit":
            # the player's units get an ability that holds the effect;
            # the ability may apply to any unit class, the grant's
            # requirements pick the units
            ability = "ABILITY_{}_{}".format(_short(owner_type), n)
            w.ability(ability, display_name, summary(effect, name_of), True,
                      "INSERT INTO TypeTags (Type, Tag)\nSELECT {}, Tag FROM "
                      "Tags WHERE Vocabulary = 'ABILITY_CLASS';".format(
                          sql_str(ability)))
            inner = mod_id + "_EFFECT"
            w.modifier(inner, t.modifier_type, args, t.run_once,
                       t.permanent, subject)
            w.lines.append(
                "INSERT INTO UnitAbilityModifiers (UnitAbilityType, "
                "ModifierId) VALUES ({}, {});".format(
                    sql_str(ability), sql_str(inner)))
            _preview(w, inner, t, display_name)
            w.modifier(mod_id, "MODIFIER_PLAYER_UNITS_GRANT_ABILITY",
                       [("AbilityType", ability)], subject_reqs=units,
                       owner_reqs=owner_reqs)
        else:
            w.modifier(mod_id, t.modifier_type, args, t.run_once,
                       t.permanent, subject + units, owner_reqs)
        table, column = LINK_TABLES[owner]
        w.lines.append("INSERT INTO {} ({}, ModifierId) VALUES ({}, {});"
                       .format(table, column, sql_str(owner_type),
                               sql_str(mod_id)))
    sql = "-- effects of {}\n{}\n".format(owner_type, "\n".join(w.lines))
    return sql, w.texts


def _preview(w, mod_id, t, display_name):
    """Combat preview line for combat strength bonuses."""
    if t.modifier_type != "MODIFIER_UNIT_ADJUST_COMBAT_STRENGTH":
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
# The game's own modifiers (of an item a unique copies)
# ---------------------------------------------------------------------------

def _reqs_from_game(mod):
    """The modifier's conditions as editor requirements ([{"preset",
    "not", "value"}]), or None if a condition has no preset (or a set
    needs only one of its conditions)."""
    reqs = []
    for key, target in (("subject_reqs", "subject"), ("owner_reqs", "owner")):
        if mod[key] and mod.get("set_types", {}).get(key) not in (
                None, "REQUIREMENTSET_TEST_ALL"):
            return None                 # "any of": no preset for that
        for req in mod[key]:
            preset = next((p for p in REQUIREMENTS.values()
                           if p.requirement_type == req["type"]
                           and p.target == target
                           and set(req["args"]) <= ({p.arg} if p.arg
                                                    else set())), None)
            if preset is None:
                return None
            reqs.append({"preset": preset.id, "not": req["inverse"],
                         "value": req["args"].get(preset.arg, "")
                         if preset.arg else ""})
    return reqs


def effect_from_game(mod):
    """An editor effect (see new_effect) doing what the game's modifier
    mod does (GameData.base_effects), or None when no template and
    condition presets express it exactly."""
    reqs = _reqs_from_game(mod)
    if reqs is None:
        return None
    for t in TEMPLATES.values():
        if (t.modifier_type != mod["modifier_type"] or
                t.run_once != mod["run_once"] or
                t.permanent != mod["permanent"]):
            continue
        names = {a.name for a in t.args}
        needed = {a.name for a in t.args if a.kind != "text"}
        if set(mod["args"]) <= names and needed <= set(mod["args"]):
            return {"template": t.id,
                    "args": {a.name: mod["args"].get(a.name, a.default)
                             for a in t.args},
                    "reqs": reqs}
    return None


def describe_game_modifier(mod, name_of=lambda kind, t: type_display_name(t)):
    """One line for a game modifier: its effect's summary when it has a
    template, else its modifier type and arguments made readable."""
    effect = effect_from_game(mod)
    if effect:
        return summary(effect, name_of)
    what = mod["modifier_type"]
    for word in ("MODIFIER_", "PLAYER_", "SINGLE_"):
        what = what.replace(word, "", 1) if what.startswith(word) else what
    what = what.replace("_", " ").capitalize()
    args = ", ".join("{} {}".format(k, type_display_name(v) if
                                    str(v).isupper() else v)
                     for k, v in sorted(mod["args"].items()))
    conditions = " (with conditions)" if mod["subject_reqs"] or \
        mod["owner_reqs"] else ""
    return "{}{}{}".format(what, ": " + args if args else "", conditions)
