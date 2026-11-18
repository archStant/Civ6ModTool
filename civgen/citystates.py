"""New city-states: specs, validation and their mod file fragments.

A city-state spec is a plain dict:
    id (stable across renames), name, description, adjective,
    category (one of CATEGORIES: what kind of city-state it is - the envoy
    bonuses, AI, colors and type icon all follow it), icon_path (custom
    icon image) or icon_from (a civilization or city-state whose icon it
    uses), bonus {name, desc, clone ([TraitType] of game city-states whose
    suzerain bonus it copies), effects (see modifiers.py; the suzerain
    gets them)}, city_names ([name], the first is its city's name),
    start_bias (as a civilization's, see civs.py), pedia {history}.

In the game a city-state is a civilization of CIVILIZATION_LEVEL_CITY_STATE
with one leader (LEADER_MINOR_CIV_<name>) inheriting from its category's
leader (LEADER_MINOR_CIV_MILITARISTIC, ...), which gives it the envoy
bonuses and AI of its kind. Its own trait carries the suzerain bonus: each
effect is attached to the players that are its suzerain (the game's
PLAYER_IS_SUZERAIN requirement set). The setup screen's City-States list
reads the configuration's CityStates table (one row per ruleset).
"""

import os
import uuid

from .civs import START_BIAS, _names, _tier, civ_icon_preview
from .modifiers import check_effects, effects_sql
from .texts import history_paragraphs, loc_text
from .util import slug_for_name, sql_str, type_display_name

# category -> (label, the color name part of its secondary color: the
# game calls the scientific one SCIENCE)
CATEGORIES = {
    "MILITARISTIC": ("Militaristic", "MILITARISTIC"),
    "SCIENTIFIC": ("Scientific", "SCIENCE"),
    "CULTURAL": ("Cultural", "CULTURAL"),
    "RELIGIOUS": ("Religious", "RELIGIOUS"),
    "TRADE": ("Trade", "TRADE"),
    "INDUSTRIAL": ("Industrial", "INDUSTRIAL"),
}
DEFAULT_CATEGORY = "MILITARISTIC"
# the colors every city-state of a category has (the game's
# COLOR_PLAYER_CITY_STATE_* values, for previews)
CITY_STATE_PRIMARY = (24, 24, 24)
CATEGORY_COLORS = {
    "MILITARISTIC": (202, 20, 21), "SCIENTIFIC": (116, 163, 243),
    "CULTURAL": (255, 0, 255), "RELIGIOUS": (249, 249, 249),
    "TRADE": (247, 216, 1), "INDUSTRIAL": (255, 129, 18),
}
# the setup screen's city-state lists, one per ruleset
CITY_STATE_DOMAINS = ("StandardCityStates", "Expansion1CityStates",
                      "Expansion2CityStates")
# the icon of a city-state without one of its own
FALLBACK_ICON = "ICON_CIVILIZATION_UNKNOWN"


def new_city_state_spec():
    return {
        "id": str(uuid.uuid4()), "name": "", "description": "",
        "adjective": "", "category": DEFAULT_CATEGORY,
        "icon_path": "", "icon_from": "",
        "bonus": {"name": "", "desc": "", "clone": [], "effects": []},
        "city_names": [],
        "start_bias": {"terrain": {}, "feature": {}, "resource": {},
                       "river": None},
        "pedia": {"history": ""},
    }


def city_state_slug(spec, prefix=""):
    return slug_for_name(spec.get("name"), prefix, kind="CIVILIZATION")


def category_label(category):
    return CATEGORIES.get(category, (type_display_name(category or ""),))[0]


def category_colors(category):
    """(primary, secondary) rgb of a category's city-states."""
    return CITY_STATE_PRIMARY, CATEGORY_COLORS.get(
        category, CATEGORY_COLORS[DEFAULT_CATEGORY])


def normalize_city_state(spec, data, prefix=""):
    """Validate a city-state spec and derive its types and tags. Raises
    ValueError with a human-friendly message."""
    name = (spec.get("name") or "").strip()
    if not name:
        raise ValueError("A city-state has no name.")
    slug = city_state_slug(spec, prefix)
    if not slug:
        raise ValueError("{} does not produce a valid type name.".format(
            name))
    short = slug[len("CIVILIZATION_"):]
    category = (spec.get("category") or "").strip().upper()
    if category not in CATEGORIES:
        raise ValueError("{}: pick its kind of city-state (militaristic, "
                         "scientific, ...).".format(name))
    adjective = (spec.get("adjective") or "").strip() or name
    city_names = _names(spec.get("city_names"))
    if not city_names:
        raise ValueError("{}: give the city-state at least one city name "
                         "(the first is its city's name).".format(name))

    bonus = spec.get("bonus") or {}
    clone = []
    for t in bonus.get("clone") or []:
        t = t.strip().upper()
        if t and t not in clone:
            clone.append(t)
    known = data.city_state_bonuses() if data.conn else {}
    for t in clone:
        if known and t not in known:
            raise ValueError("{}: the game has no city-state bonus {} (to "
                             "copy).".format(name, t))
    bonus_name = (bonus.get("name") or "").strip()
    bonus_desc = (bonus.get("desc") or "").strip()
    source = known.get(clone[0]) if len(clone) == 1 else None
    if source and not (source["name_tag"] and source["desc_tag"]):
        source = None
    if not bonus_name and not source:
        raise ValueError("{}: give the suzerain bonus a name (or copy "
                         "exactly one existing city-state's bonus to use "
                         "its name).".format(name))
    trait = "MINOR_CIV_{}_TRAIT".format(short)
    bonus_ctx = {
        "trait": trait, "clone": clone,
        "effects": list(bonus.get("effects") or []),
        "name": bonus_name, "desc": bonus_desc,
        # own text, or the copied bonus's
        "name_tag": "LOC_{}_NAME".format(trait) if bonus_name
                    else source["name_tag"],
        "desc_tag": "LOC_{}_DESCRIPTION".format(trait)
                    if bonus_desc or not source else source["desc_tag"],
    }
    check_effects(bonus_ctx["effects"], "suzerain", data,
                  "{} (suzerain bonus)".format(name))

    bias = spec.get("start_bias") or {}
    start_bias = {}
    for key in START_BIAS:
        start_bias[key] = {t.strip().upper(): _tier(tier, name)
                           for t, tier in (bias.get(key) or {}).items()
                           if t.strip()}
    river = bias.get("river")
    start_bias["river"] = _tier(river, name) if river not in (None, "") \
        else None

    icon_path = (spec.get("icon_path") or "").strip()
    if icon_path and not os.path.isfile(icon_path):
        raise ValueError("{}: icon image not found: {}".format(name,
                                                              icon_path))
    icon_from = (spec.get("icon_from") or "").strip().upper()
    if icon_from and not icon_from.startswith("CIVILIZATION_"):
        raise ValueError("{}: '{}' is not a civilization or city-state "
                         "(its icon).".format(name, icon_from))
    game_states = data.city_state_types() if data.conn else set()
    return {
        "id": spec.get("id") or "", "name": name, "slug": slug,
        "short": short, "label": name + " (city-state)",
        "category": category,
        "color_name": CATEGORIES[category][1],
        "leader": "LEADER_MINOR_CIV_" + short,
        "inherit_from": "LEADER_MINOR_CIV_" + category,
        "exists_in_game": slug in game_states or
                          slug in (getattr(data, "civ_names", None) or {}),
        "description": (spec.get("description") or "").strip() or
                       "{} city-state".format(name),
        "adjective": adjective,
        "icon_path": icon_path, "icon_custom": bool(icon_path),
        "icon_from": icon_from,
        "icon_name": "ICON_" + slug, "icon_atlas": "ICON_ATLAS_" + slug,
        "bonus": bonus_ctx,
        "city_names": [("LOC_CITY_NAME_{}_{}".format(slug, i), city)
                       for i, city in enumerate(city_names, 1)],
        "start_bias": start_bias,
        "history": history_paragraphs(
            (spec.get("pedia") or {}).get("history")),
        "name_tag": "LOC_{}_NAME".format(slug),
        "desc_tag": "LOC_{}_DESCRIPTION".format(slug),
        "adjective_tag": "LOC_{}_ADJECTIVE".format(slug),
        # (no historic moment pictures)
        "moments": [],
    }


# ---------------------------------------------------------------------------
# SQL and text
# ---------------------------------------------------------------------------

def city_state_sql(cs, name_of=lambda kind, t: type_display_name(t)):
    """(gameplay SQL, [(tag, text)] of its effects) of one city-state."""
    slug = sql_str(cs["slug"])
    leader = sql_str(cs["leader"])
    b = cs["bonus"]
    trait = sql_str(b["trait"])
    out = ["""-----------------------------------------------
-- City-state: {name} ({civ}), {category}
-----------------------------------------------
INSERT INTO Types (Type, Kind) VALUES
({slug}, 'KIND_CIVILIZATION'),
({leader}, 'KIND_LEADER'),
({trait}, 'KIND_TRAIT');

INSERT INTO TypeProperties (Type, Name, Value)
VALUES ({slug}, 'CityStateCategory', {category_s});

INSERT INTO Civilizations (CivilizationType, Name, Description, Adjective,
    StartingCivilizationLevelType, RandomCityNameDepth)
VALUES ({slug}, {name_tag}, {desc_tag}, {adj_tag},
    'CIVILIZATION_LEVEL_CITY_STATE', 1);

-- its kind's leader gives it the envoy bonuses and AI of its kind
INSERT INTO Leaders (LeaderType, Name, InheritFrom)
VALUES ({leader}, {name_tag}, {inherit});

INSERT INTO CivilizationLeaders (CivilizationType, LeaderType, CapitalName)
VALUES ({slug}, {leader}, {capital});

-- the suzerain bonus
INSERT INTO Traits (TraitType, Name, Description)
VALUES ({trait}, {bonus_name}, {bonus_desc});
INSERT INTO LeaderTraits (LeaderType, TraitType) VALUES ({leader}, {trait});
""".format(name=cs["name"], civ=cs["slug"], category=cs["category"],
           slug=slug, leader=leader, trait=trait,
           category_s=sql_str(cs["category"]),
           name_tag=sql_str(cs["name_tag"]), desc_tag=sql_str(cs["desc_tag"]),
           adj_tag=sql_str(cs["adjective_tag"]),
           inherit=sql_str(cs["inherit_from"]),
           capital=sql_str(cs["city_names"][0][0]),
           bonus_name=sql_str(b["name_tag"]),
           bonus_desc=sql_str(b["desc_tag"]))]
    for source in b["clone"]:
        # (the game's bonus modifiers already apply to the suzerain only)
        out.append("""
-- the suzerain bonus of {source}
INSERT INTO TraitModifiers (TraitType, ModifierId)
SELECT {trait}, ModifierId FROM TraitModifiers WHERE TraitType = {source_s};
""".format(source=source, source_s=sql_str(source), trait=trait))
    effects, texts = effects_sql("suzerain", b["trait"], b["effects"],
                                 b["name"] or cs["name"], name_of)
    if effects:
        out.append("\n" + effects)
    out.append("\n-- city names (the first is its city's)\n"
               "INSERT INTO CityNames (CivilizationType, CityName) VALUES\n"
               "{};\n".format(",\n".join("({}, {})".format(
                   slug, sql_str(tag)) for tag, _ in cs["city_names"])))
    bias = cs["start_bias"]
    for key, (table, column) in START_BIAS.items():
        if bias[key]:
            out.append("\nINSERT INTO {} (CivilizationType, {}, Tier) VALUES"
                       "\n{};\n".format(table, column, ",\n".join(
                           "({}, {}, {})".format(slug, sql_str(t), tier)
                           for t, tier in sorted(bias[key].items()))))
    if bias["river"]:
        out.append("\nINSERT INTO StartBiasRivers (CivilizationType, Tier) "
                   "VALUES ({}, {});\n".format(slug, bias["river"]))
    return "".join(out), texts


def city_state_xp2_sql(cs):
    """Gathering Storm-only rows: its kind of bonus (which the World
    Congress' Sovereignty resolution can switch off)."""
    return ("-- {}: its kind of suzerain bonus (World Congress)\n"
            "INSERT INTO Leaders_XP2 (LeaderType, MinorCivBonusType) "
            "VALUES ({}, {});\n").format(
                cs["name"], sql_str(cs["leader"]),
                sql_str("MINOR_CIV_BONUS_" + cs["category"]))


def city_state_config_sql(cs):
    """The setup screen's City-States list rows (one per ruleset)."""
    return ("-- {name}: the setup screen's city-state lists\n"
            "INSERT INTO CityStates (Domain, CivilizationType, Name, Icon, "
            "CityStateCategory, Bonus) VALUES\n{rows};\n").format(
                name=cs["name"], rows=",\n".join(
                    "({}, {}, {}, {}, {}, {})".format(
                        sql_str(domain), sql_str(cs["slug"]),
                        sql_str(cs["name_tag"]), sql_str(cs["icon_name"]),
                        sql_str(cs["category"]),
                        sql_str(cs["bonus"]["desc_tag"]))
                    for domain in CITY_STATE_DOMAINS))


def city_state_color_row(cs):
    """The PlayerColors row (XML): its category's colors, as every
    city-state of that kind has."""
    return ("    <Row>\n      <Type>{slug}</Type>\n      <Usage>Minor</Usage>\n"
            "      <PrimaryColor>COLOR_PLAYER_CITY_STATE_PRIMARY"
            "</PrimaryColor>\n      <SecondaryColor>COLOR_PLAYER_CITY_STATE_"
            "{color}_SECONDARY</SecondaryColor>\n    </Row>").format(slug=cs["slug"], color=cs["color_name"])


def city_state_text_rows(cs):
    """[(tag, English text)] of a city-state (not its effects')."""
    rows = [(cs["name_tag"], cs["name"]),
            (cs["desc_tag"], cs["description"]),
            (cs["adjective_tag"], cs["adjective"])]
    b = cs["bonus"]
    if b["name"]:
        rows.append((b["name_tag"], b["name"]))
    if b["desc"]:
        rows.append((b["desc_tag"], loc_text(b["desc"])))
    elif b["desc_tag"].startswith("LOC_" + b["trait"]):
        rows.append((b["desc_tag"], b["name"]))
    rows += cs["city_names"]
    page = "LOC_PEDIA_CITYSTATES_PAGE_{}_CHAPTER_HISTORY_PARA_".format(
        cs["slug"])
    rows += [(page + str(i), loc_text(p))
             for i, p in enumerate(cs["history"], 1)]
    return rows


def city_state_icons_sql(cs):
    """IconDefinitions row copying another civilization's or city-state's
    icon (when the city-state has no icon of its own)."""
    if cs["icon_custom"]:
        return ""
    source = "ICON_" + cs["icon_from"] if cs["icon_from"] else FALLBACK_ICON
    return ("-- {name}: the icon of {source}\n"
            "INSERT OR REPLACE INTO IconDefinitions (Name, Atlas, \"Index\")\n"
            "SELECT {icon}, Atlas, \"Index\" FROM IconDefinitions "
            "WHERE Name = {source_s};\n").format(
                name=cs["name"], source=source, icon=sql_str(cs["icon_name"]),
                source_s=sql_str(source))


def city_state_icon_preview(spec, size):
    """The city-state's icon in its category's colors on a dark badge,
    as the game draws city-state icons (size x size RGBA), or a
    placeholder with its initials. Raises ImportError without Pillow."""
    from .art import placeholder_icon
    primary, secondary = category_colors(spec.get("category"))
    path = (spec.get("icon_path") or "").strip()
    if path and os.path.isfile(path):
        return civ_icon_preview(spec, size, badge=primary, tint=secondary)
    return placeholder_icon(spec.get("name"), primary, secondary, size)
