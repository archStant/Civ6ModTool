"""New civilizations: specs, validation and their mod file fragments.

A civilization spec is a plain picklable dict:
    id (stable across renames; leaders refer to the civilization by its
    type, which the editor keeps in step), name, description, adjective,
    ethnicity (unit portraits), culture / unit_culture (city and unit art
    styles, Cultures.artdef), music_from (civilization whose music it
    plays), icon_path (custom icon image) or icon_from (civilization whose
    icon it uses),
    ability {name, desc, clone ([TraitType] whose effects it copies),
    effects (see modifiers.py)},
    city_names ([name], the first is the capital),
    citizen_names {male, female, modern_male, modern_female: [name]},
    start_bias {terrain / feature / resource: {type: tier 1-5},
    river: tier or None},
    pedia {history, location, size, population, capital},
    uniques ([unique spec], see uniques.py)
Every civilization needs at least one leader (a leader spec whose civ is
the civilization's type).
"""

import os
import uuid

from .moments import normalize_moments
from .util import slug_for_name, sql_str, type_display_name
from .gamedata import TRAIT_RULE_TABLES
from .art import _cached, placeholder_icon
from .modifiers import check_effects, effects_sql
from .texts import history_paragraphs, loc_text
from .uniques import normalize_unique, unique_sql, unique_text_rows


# Sizes of ICON_ATLAS_CIVILIZATIONS and the DLC civilization atlases
CIV_ICON_SIZES = [22, 30, 32, 36, 44, 45, 48, 50, 64, 80, 128, 200, 256]

CITIZEN_GROUPS = [("male", "Male", 0, 0), ("female", "Female", 1, 0),
                  ("modern_male", "Modern male", 0, 1),
                  ("modern_female", "Modern female", 1, 1)]
CIV_INFO = [("location", "Location", "LOC_CIVINFO_LOCATION", 10),
            ("size", "Size", "LOC_CIVINFO_SIZE", 20),
            ("population", "Population", "LOC_CIVINFO_POPULATION", 30),
            ("capital", "Capital", "LOC_CIVINFO_CAPITAL", 40)]
# start bias kind -> (table, type column); tiers: 1 = strongest
START_BIAS = {"terrain": ("StartBiasTerrains", "TerrainType"),
              "feature": ("StartBiasFeatures", "FeatureType"),
              "resource": ("StartBiasResources", "ResourceType")}
# the setup screen's rulesets (scenarios have domains of their own)
STANDARD_DOMAINS = ("Players:StandardPlayers", "Players:Expansion1_Players",
                    "Players:Expansion2_Players")
DEFAULT_MUSIC = "Sumeria"


def new_civ_spec():
    return {
        "id": str(uuid.uuid4()), "name": "", "description": "",
        "adjective": "", "ethnicity": "ETHNICITY_EURO",
        "culture": "Mediterranean", "unit_culture": "European",
        "music_from": "", "icon_path": "", "icon_from": "",
        "ability": {"name": "", "desc": "", "clone": [], "effects": []},
        "city_names": [],
        "citizen_names": {key: [] for key, _, _, _ in CITIZEN_GROUPS},
        "start_bias": {"terrain": {}, "feature": {}, "resource": {},
                       "river": None},
        "pedia": {"history": "", "location": "", "size": "",
                  "population": "", "capital": ""},
        "uniques": [],
        # historic moment pictures of its uniques (see moments.py)
        "moment_illustrations": [],
    }


def civ_slug(spec, prefix=""):
    return slug_for_name(spec.get("name"), prefix, kind="CIVILIZATION")


def _names(values):
    """Stripped names without duplicates (case-insensitive), in order."""
    out = []
    for value in values or []:
        value = (value or "").strip()
        if value and value.lower() not in (v.lower() for v in out):
            out.append(value)
    return out


def _tier(value, what):
    try:
        tier = int(value)
    except (TypeError, ValueError):
        raise ValueError("{}: start bias tier must be 1-5.".format(what))
    if not 1 <= tier <= 5:
        raise ValueError("{}: start bias tier must be 1-5.".format(what))
    return tier


def normalize_civ(spec, data, prefix=""):
    """Validate a civilization spec and derive its type, tags and the
    contexts of its uniques. Raises ValueError with a human-friendly
    message."""
    name = (spec.get("name") or "").strip()
    if not name:
        raise ValueError("A civilization has no name.")
    slug = civ_slug(spec, prefix)
    if not slug:
        raise ValueError("{} does not produce a valid type name.".format(
            name))
    short = slug[len("CIVILIZATION_"):]
    adjective = (spec.get("adjective") or "").strip() or name
    city_names = _names(spec.get("city_names"))
    if not city_names:
        raise ValueError("{}: give the civilization at least one city name "
                         "(the first is its capital).".format(name))

    ability = spec.get("ability") or {}
    clone = [t.strip().upper() for t in ability.get("clone") or []
             if t.strip()]
    ability_name = (ability.get("name") or "").strip()
    ability_desc = (ability.get("desc") or "").strip()
    known = {a["type"]: a for _, a in data.all_abilities()}
    if not ability_name and not (len(clone) == 1 and clone[0] in known):
        raise ValueError("{}: give the civilization ability a name (or copy "
                         "exactly one existing ability to use its name)."
                         .format(name))
    trait = "TRAIT_" + slug
    source = known.get(clone[0]) if len(clone) == 1 else None
    ability_ctx = {
        "trait": trait, "clone": clone,
        "effects": list(ability.get("effects") or []),
        "name": ability_name, "desc": ability_desc,
        # own text, or the copied ability's
        "name_tag": "LOC_{}_NAME".format(trait) if ability_name
                    else source["name_tag"],
        "desc_tag": "LOC_{}_DESCRIPTION".format(trait)
                    if ability_desc or not source else source["desc_tag"],
    }
    check_effects(ability_ctx["effects"], "trait", data,
                  "{} (civilization ability)".format(name))

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
    pedia = spec.get("pedia") or {}
    civ = {
        "name": name, "slug": slug, "short": short, "id": spec.get("id"),
        "exists_in_game": slug in data.civ_names,
        "description": (spec.get("description") or "").strip() or
                       "{} civilization".format(adjective),
        "adjective": adjective,
        "ethnicity": (spec.get("ethnicity") or "").strip() or None,
        "culture": (spec.get("culture") or "").strip(),
        "unit_culture": (spec.get("unit_culture") or "").strip(),
        "music_from": (spec.get("music_from") or "").strip(),
        "icon_path": icon_path,
        "icon_custom": bool(icon_path),
        "icon_from": (spec.get("icon_from") or "").strip(),
        "icon_name": "ICON_" + slug,
        "icon_atlas": "ICON_ATLAS_" + slug,
        "ability": ability_ctx,
        "city_names": [("LOC_CITY_NAME_{}_{}".format(slug, i), city)
                       for i, city in enumerate(city_names, 1)],
        "citizen_names": [
            (female, modern, "LOC_CITIZEN_{}_{}_{}".format(
                short, key.upper(), i), citizen)
            for key, _, female, modern in CITIZEN_GROUPS
            for i, citizen in enumerate(
                _names((spec.get("citizen_names") or {}).get(key)), 1)],
        "start_bias": start_bias,
        "history": history_paragraphs(pedia.get("history")),
        "info": [(header, "LOC_CIVINFO_{}_{}".format(short, key.upper()),
                  (pedia.get(key) or "").strip(), sort)
                 for key, _, header, sort in CIV_INFO
                 if (pedia.get(key) or "").strip()],
        "name_tag": "LOC_{}_NAME".format(slug),
        "desc_tag": "LOC_{}_DESCRIPTION".format(slug),
        "adjective_tag": "LOC_{}_ADJECTIVE".format(slug),
        "moments": normalize_moments(spec.get("moment_illustrations"), name,
                                     slug),
    }
    civ["uniques"] = []
    seen = {}
    for unique in spec.get("uniques") or []:
        u = normalize_unique(unique, civ, data, prefix)
        if u["slug"] in seen:
            raise ValueError("{}: two uniques have the type {} - rename one."
                             .format(name, u["slug"]))
        seen[u["slug"]] = True
        civ["uniques"].append(u)
    return civ


# ---------------------------------------------------------------------------
# SQL and text
# ---------------------------------------------------------------------------

def ability_sql(civ, name_of):
    """The civilization ability trait: copies of the chosen abilities'
    effects plus the editor's effects. Returns (sql, texts)."""
    a = civ["ability"]
    trait = sql_str(a["trait"])
    out = ["""-- civilization ability
INSERT INTO Types (Type, Kind) VALUES ({trait}, 'KIND_TRAIT');
INSERT INTO Traits (TraitType, Name, Description) VALUES ({trait}, {name}, {desc});
INSERT INTO CivilizationTraits (CivilizationType, TraitType) VALUES ({civ}, {trait});
""".format(trait=trait, name=sql_str(a["name_tag"]),
           desc=sql_str(a["desc_tag"]), civ=sql_str(civ["slug"]))]
    for source in a["clone"]:
        rules = "".join(
            "INSERT INTO {table} (TraitType, {column})\nSELECT {new}, "
            "{column} FROM {table} WHERE TraitType = {source};\n".format(
                table=table, column=column, new=trait,
                source=sql_str(source))
            for table, column in TRAIT_RULE_TABLES.items())
        out.append("""
-- the effects of {source}
INSERT INTO TraitModifiers (TraitType, ModifierId)
SELECT {new}, ModifierId FROM TraitModifiers WHERE TraitType = {source_s};
{rules}-- the AI's preference lists for it
INSERT INTO AiListTypes (ListType)
SELECT ListType || {suffix} FROM AiLists WHERE LeaderType = {source_s};
INSERT INTO AiLists (ListType, LeaderType, AgendaType, System, MinDifficulty, MaxDifficulty)
SELECT ListType || {suffix}, {new}, AgendaType, System, MinDifficulty, MaxDifficulty
FROM AiLists WHERE LeaderType = {source_s};
INSERT INTO AiFavoredItems (ListType, Item, Favored, Value, StringVal, MinDifficulty, MaxDifficulty, TooltipString)
SELECT ListType || {suffix}, Item, Favored, Value, StringVal, MinDifficulty, MaxDifficulty, TooltipString
FROM AiFavoredItems
WHERE ListType IN (SELECT ListType FROM AiLists WHERE LeaderType = {source_s});
""".format(source=source, source_s=sql_str(source), new=trait, rules=rules,
           suffix=sql_str("_" + civ["short"])))
    effects, texts = effects_sql("trait", a["trait"], a["effects"],
                                 a["name"] or civ["name"], name_of)
    out.append(effects)
    return "".join(out), texts


def civ_gameplay_sql(civ, name_of=lambda kind, t: type_display_name(t)):
    """(gameplay SQL, Gathering Storm-only SQL, [(tag, text)]) of one
    civilization and its uniques."""
    slug = sql_str(civ["slug"])
    out = ["""-----------------------------------------------
-- Civilization: {name} ({civ})
-----------------------------------------------
INSERT INTO Types (Type, Kind) VALUES ({slug}, 'KIND_CIVILIZATION');
INSERT INTO Civilizations (CivilizationType, Name, Description, Adjective,
    StartingCivilizationLevelType, RandomCityNameDepth, Ethnicity)
VALUES ({slug}, {name_tag}, {desc_tag}, {adj_tag},
    'CIVILIZATION_LEVEL_FULL_CIV', 10, {ethnicity});

""".format(name=civ["name"], civ=civ["slug"], slug=slug,
           name_tag=sql_str(civ["name_tag"]), desc_tag=sql_str(civ["desc_tag"]),
           adj_tag=sql_str(civ["adjective_tag"]),
           ethnicity=sql_str(civ["ethnicity"]) if civ["ethnicity"]
           else "NULL")]
    ability, texts = ability_sql(civ, name_of)
    out.append(ability)
    out.append("\n-- city names (the first is the capital)\n"
               "INSERT INTO CityNames (CivilizationType, CityName) VALUES\n"
               "{};\n".format(",\n".join("({}, {})".format(
                   slug, sql_str(tag)) for tag, _ in civ["city_names"])))
    if civ["citizen_names"]:
        out.append("\nINSERT INTO CivilizationCitizenNames (CivilizationType,"
                   " CitizenName, Female, Modern) VALUES\n{};\n".format(
                       ",\n".join("({}, {}, {}, {})".format(
                           slug, sql_str(tag), female, modern)
                           for female, modern, tag, _ in
                           civ["citizen_names"])))
    if civ["info"]:
        out.append("\n-- Civilopedia facts\nINSERT INTO CivilizationInfo "
                   "(CivilizationType, Header, Caption, SortIndex) VALUES\n"
                   "{};\n".format(",\n".join("({}, {}, {}, {})".format(
                       slug, sql_str(header), sql_str(tag), sort)
                       for header, tag, _, sort in civ["info"])))
    bias = civ["start_bias"]
    for key, (table, column) in START_BIAS.items():
        if bias[key]:
            out.append("\nINSERT INTO {} (CivilizationType, {}, Tier) VALUES"
                       "\n{};\n".format(table, column, ",\n".join(
                           "({}, {}, {})".format(slug, sql_str(t), tier)
                           for t, tier in sorted(bias[key].items()))))
    if bias["river"]:
        out.append("\nINSERT INTO StartBiasRivers (CivilizationType, Tier) "
                   "VALUES ({}, {});\n".format(slug, bias["river"]))
    xp2 = []
    for u in civ["uniques"]:
        sql, gs, unique_texts = unique_sql(u, name_of)
        out.append("\n" + sql)
        if gs:
            xp2.append(sql_header(u) + gs)
        texts += unique_texts
    return "".join(out), "".join(xp2), texts


def sql_header(u):
    return "-- {}: Gathering Storm rows of {}\n".format(u["label"], u["base"])


def civ_text_rows(civ):
    """[(tag, English text)] of a civilization (not its effects')."""
    rows = [(civ["name_tag"], civ["name"]),
            (civ["desc_tag"], civ["description"]),
            (civ["adjective_tag"], civ["adjective"])]
    a = civ["ability"]
    if a["name"]:
        rows.append((a["name_tag"], a["name"]))
    if a["desc"]:
        rows.append((a["desc_tag"], loc_text(a["desc"])))
    elif a["name"] and a["desc_tag"].startswith("LOC_" + a["trait"]):
        rows.append((a["desc_tag"], a["name"]))
    rows += civ["city_names"]
    rows += [(tag, citizen) for _, _, tag, citizen in civ["citizen_names"]]
    page = "LOC_PEDIA_CIVILIZATIONS_PAGE_{}_CHAPTER_HISTORY_PARA_".format(
        civ["slug"])
    rows += [(page + str(i), loc_text(p))
             for i, p in enumerate(civ["history"], 1)]
    rows += [(tag, loc_text(text)) for _, tag, text, _ in civ["info"]]
    for u in civ["uniques"]:
        rows += unique_text_rows(u)
    return rows


def civ_icons_sql(civ):
    """IconDefinitions row copying another civilization's icon (when the
    civilization has no icon of its own)."""
    if civ["icon_custom"]:
        return ""
    source = "ICON_" + civ["icon_from"] if civ["icon_from"] \
        else "ICON_CIVILIZATION_UNKNOWN"
    return ("-- {name}: the icon of {source}\n"
            "INSERT OR REPLACE INTO IconDefinitions (Name, Atlas, \"Index\")\n"
            "SELECT {icon}, Atlas, \"Index\" FROM IconDefinitions "
            "WHERE Name = {source_s};\n").format(
                name=civ["name"], source=source, icon=sql_str(civ["icon_name"]),
                source_s=sql_str(source))


CIV_BADGE_COLOR = (43, 43, 43)          # badge without a leader color


def civ_icon_preview(spec, size, badge=None):
    """The civilization's icon image (size x size RGBA), or a placeholder
    with its initials. badge: an (r, g, b) color to draw the icon on a
    round badge of, like the game does (the game's civilization icons are
    white, which a light list background would hide). Raises ImportError
    without Pillow."""
    from PIL import Image, ImageDraw
    path = (spec.get("icon_path") or "").strip()
    if path and os.path.isfile(path):
        def make():
            img = Image.open(path).convert("RGBA")
            # on a badge the icon keeps clear of the badge's edge
            inner = int(round(size * 0.72)) if badge else size
            img.thumbnail((inner, inner), Image.LANCZOS)
            out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            if badge:
                ss = 4                  # supersampled, for a smooth edge
                disc = Image.new("RGBA", (size * ss, size * ss),
                                 (0, 0, 0, 0))
                ImageDraw.Draw(disc).ellipse(
                    (0, 0, size * ss - 1, size * ss - 1),
                    fill=tuple(badge) + (255,))
                out = disc.resize((size, size), Image.LANCZOS)
            out.alpha_composite(img, ((size - img.width) // 2,
                                      (size - img.height) // 2))
            return out
        try:
            icon = _cached(("civ_icon", size, tuple(badge or ())), path,
                           make)
            if icon is not None:
                return icon
        except Exception:               # unreadable image
            pass
    return placeholder_icon(spec.get("name"), (70, 70, 70), (230, 230, 230),
                            size)
