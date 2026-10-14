"""Leader specs: validation and their mod file fragments."""

import os
import re

from .util import asset_path, slug_for_name, sql_str, value_or_column
from .gamedata import TRAIT_RULE_TABLES
from .modifiers import check_effects, effects_sql, summary
from .agendas import normalize_own_agenda, own_agenda_sql
from .civs import STANDARD_DOMAINS
from .uniques import player_item_sql
from .moments import normalize_moments
from .moods import SLOT_KEYS as MOOD_SLOT_KEYS, slot_label as mood_label
from .art import (DEFAULT_ICON_BORDER_COLOR, DEFAULT_ICON_BORDER_WIDTH,
                  DEFAULT_LOAD_BG,
                  _cached, fitted_portrait, make_circle_icon,
                  placeholder_icon)
from .texts import (DIPLO_TEXT, PEDIA_HISTORY, PEDIA_PREFIX, PEDIA_TEXT,
                    history_paragraphs, inherit_candidates, loc_text,
                    spec_texts)


# (symbol, what it marks) for the leader list's "Custom" column, in the
# order they are shown. Non-BMP emoji need Tk 8.6.10+ (drawn monochrome).
CUSTOM_MARKS = [
    ("\U0001F5BC", "loading background"),
    ("\U0001F3DB", "diplomacy background"),
    ("\U0001F3AD", "diplomacy portraits"),
    ("\U0001F3AF", "agenda"),
    ("\U0001F396", "leader ability"),
    ("\U0001F4AC", "diplomacy text"),
    ("\U0001F4D6", "Civilopedia"),
    # ("⭐", "historic moments"),
]


def leader_custom_marks(spec):
    """The CUSTOM_MARKS entries (symbol, what) for what a leader
    customizes."""
    def filled(value):
        return bool((value or "").strip())
    texts = {k for k, v in spec_texts(spec).items() if filled(v)}
    checks = [
        filled(spec.get("load_bg_path")) or bool(spec.get("load_bg_default"))
        or bool(spec.get("load_bg_hue")),
        filled(spec.get("diplo_bg_path")),
        any(filled(path) for path in (spec.get("mood_images") or {}).values()),
        any(filled(spec.get(k)) for k in ("agenda", "agenda_name",
                                          "agenda_desc"))
        or bool(spec.get("own_agenda")),
        any(filled(text.get("name")) or filled(text.get("desc"))
            for text in (spec.get("abilities") or {}).values()),
        any(k in texts for _, lines in DIPLO_TEXT for k, _ in lines),
        any(k in texts for k, _, _, _ in PEDIA_TEXT),
        any(filled(entry.get("path"))
            for entry in spec.get("moment_illustrations") or []),
    ]
    return [mark for mark, on in zip(CUSTOM_MARKS, checks) if on]


# ---------------------------------------------------------------------------
# Leader spec: validation and derived fields
# ---------------------------------------------------------------------------
# A leader spec is a plain picklable dict with these keys:
#   name, sex, civ, orig ("" = a new leader that inherits from nobody),
#   bio, quote, texts ({tag template: text}, see
#   DIPLO_TEXT / PEDIA_TEXT), primary, secondary,
#   icon_path, load_fg_path, load_bg_path, diplo_bg_path,
#   load_bg_default (no load_bg_path: use assets/bg_loading_default.png),
#   load_bg_hue (turn the loading background's colors by that many
#   degrees, -180..180),
#   diplo_bg_mask (fade the diplomacy background out with assets/mask.png),
#   icon_mode ('portrait' or 'file'), icon_crop ((x, y, r) in fitted
#   portrait pixels, see fit_portrait, or None), icon_border_color,
#   icon_border_width,
#   mood_images ({mood slot key: image path}: diplomacy-screen images by
#   mood or moment, see moods.py; the portrait is the neutral one),
#   moment_illustrations (older projects only: see moments.py; they now
#   belong to civilizations),
#   agenda (AGENDA_ type, "" = the original leader's), agenda_name,
#   agenda_desc (either one filled = a renamed copy of that agenda),
#   own_agenda (advanced mode: an agenda of its own instead, {"name",
#   "desc", "reactions"} - see agendas.py; None or absent: none),
#   abilities ({TraitType: {"name": ..., "desc": ...}} of the original
#   leader's ability traits; either one filled = a renamed copy),
#   city_names ([name, ...], the first is the capital; [] = the
#   civilization's own names),
#   new_ability ({"name", "desc", "replace", "effects"}: an ability of
#   its own; required without orig),
#   ai_traits ([TraitType] of AI_TRAITS: the AI's personality, for a
#   leader without orig; one inheriting gets the original's),
#   scene_leader (a game leader whose layered diplomacy scene is shown
#   when there is no diplomacy background; "" = the original leader's,
#   or the game's default scene without orig)
# (older projects may also have greet_happy/neutral/unhappy)

def new_leader_spec():
    return {
        "name": "", "sex": "Female", "civ": "", "orig": "",
        "bio": "", "quote": "", "texts": {},
        "primary": (30, 90, 170), "secondary": (230, 230, 230),
        "icon_path": "", "load_fg_path": "", "load_bg_path": "",
        "load_bg_default": False, "load_bg_hue": 0,
        "diplo_bg_path": "", "diplo_bg_mask": False,
        "icon_mode": "portrait", "icon_crop": None,
        "icon_border_color": DEFAULT_ICON_BORDER_COLOR,
        "icon_border_width": DEFAULT_ICON_BORDER_WIDTH,
        "mood_images": {},
        "moment_illustrations": [],
        "agenda": "", "agenda_name": "", "agenda_desc": "",
        "abilities": {},
        "city_names": [],
        "ai_traits": list(DEFAULT_AI_TRAITS), "scene_leader": "",
    }


# The AI personality of a leader that inherits from nobody: traits without
# effects of their own that steer the AI (AiLists keyed by the trait).
# (type, label, explanation)
AI_TRAITS = [
    ("TRAIT_LEADER_SCIENCE_MAJOR_CIV", "Scientific",
     "Favors science and a science victory."),
    ("TRAIT_LEADER_CULTURAL_MAJOR_CIV", "Cultural",
     "Favors culture, great works and a culture victory."),
    ("TRAIT_LEADER_RELIGIOUS_MAJOR_CIV", "Religious",
     "Founds and spreads a religion; favors a religious victory."),
    ("TRAIT_LEADER_NONRELIGIOUS_MAJOR_CIV", "Not religious",
     "Puts little effort into religion."),
    ("TRAIT_LEADER_AGGRESSIVE_MILITARY", "Aggressive",
     "Builds a bigger army and goes to war more readily."),
    ("TRAIT_LEADER_EXPANSIONIST", "Expansionist",
     "Settles more cities."),
    ("TRAIT_LEADER_PURSUE_DIPLOMATIC_VICTORY", "Diplomatic",
     "Favors a diplomatic victory (Gathering Storm)."),
    ("TRAIT_LEADER_LOW_RELIGIOUS_PREFERENCE", "Low interest in religion",
     "Less likely to found a religion (most leaders have this)."),
    ("TRAIT_LEADER_LOW_CITY_STATE_PREFERENCE_WAR",
     "Leaves city-states alone",
     "Less likely to attack city-states (many leaders have this)."),
]
DEFAULT_AI_TRAITS = ["TRAIT_LEADER_LOW_RELIGIOUS_PREFERENCE",
                     "TRAIT_LEADER_LOW_CITY_STATE_PREFERENCE_WAR"]
# icon of a leader without orig and without art of its own
DEFAULT_LEADER_ICON = "ICON_LEADER_DEFAULT"


def spec_icon_mode(spec):
    """'portrait' (cut a circle out of the loading portrait) or 'file'
    (use icon_path). Projects from before the mode existed keep using
    their icon file if they had one."""
    mode = spec.get("icon_mode")
    if mode in ("portrait", "file"):
        return mode
    return "file" if (spec.get("icon_path") or "").strip() else "portrait"


def normalize_spec(spec, data, prefix="", civs=None):
    """Validate a leader spec and compute derived fields (slug, text keys,
    icon handling). prefix is the project-wide type prefix; civs: the
    project's civilization contexts by type (see civs.normalize_civ), for
    leaders of a new civilization. Raises ValueError with a
    human-friendly message. A type that already exists in the game data
    is not an error; it is flagged as exists_in_game."""
    name = (spec.get("name") or "").strip()
    civ = (spec.get("civ") or "").strip()
    orig = (spec.get("orig") or "").strip()
    if not name:
        raise ValueError("A leader has no name.")
    if not civ:
        raise ValueError("{}: pick (or type) its civilization.".format(name))
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
    # diplomacy-screen images by mood (the portrait is the neutral one)
    mood_paths = {}
    for key, path in (spec.get("mood_images") or {}).items():
        path = (path or "").strip()
        if not path:
            continue
        if key == "NEUTRAL" or key not in MOOD_SLOT_KEYS:
            raise ValueError("{}: '{}' is not a diplomacy portrait.".format(
                name, key))
        if not os.path.isfile(path):
            raise ValueError("{}: {} diplomacy portrait not found: {}".format(
                name, mood_label(key).lower(), path))
        mood_paths[key] = path
    if mood_paths and not images["load_fg_path"]:
        raise ValueError("{}: the diplomacy portraits need a Portrait "
                         "(General tab) too - it is the neutral one."
                         .format(name))
    # (older projects: pictures of a game civilization's items; the
    # project's civilizations hold their own)
    moments = normalize_moments(spec.get("moment_illustrations"), name, slug)
    agenda = (spec.get("agenda") or "").strip().upper()
    if agenda and not agenda.startswith("AGENDA_"):
        raise ValueError("{}: agenda '{}' must be an AGENDA_ type."
                         .format(name, agenda))
    agenda_name = (spec.get("agenda_name") or "").strip()
    agenda_desc = (spec.get("agenda_desc") or "").strip()
    agenda_type = "AGENDA_" + slug[len("LEADER_"):]
    own_agenda = None
    if spec.get("own_agenda"):
        # (instead of a game agenda or a renamed copy of one)
        own_agenda = normalize_own_agenda(spec["own_agenda"], name,
                                          slug[len("LEADER_"):], data)
        agenda = ""
        agenda_name, agenda_desc = own_agenda["name"], own_agenda["desc"]
    known = {a["type"]: a for a in data.abilities(orig)}
    abilities = []
    # (without orig there is nothing inherited to rename)
    for trait, text in sorted((spec.get("abilities") or {}).items()
                              if orig else ()):
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
    if not images["load_bg_path"] and spec.get("load_bg_default"):
        images["load_bg_path"] = asset_path(DEFAULT_LOAD_BG) or ""
        if not images["load_bg_path"]:
            raise ValueError("{}: the default loading background "
                             "(assets/{}) was not found.".format(
                                 name, DEFAULT_LOAD_BG))
    try:
        load_bg_hue = int(spec.get("load_bg_hue") or 0)
    except (TypeError, ValueError):
        raise ValueError("{}: the hue of the loading background must be a "
                         "whole number of degrees.".format(name))
    if not -180 <= load_bg_hue <= 180:
        raise ValueError("{}: the hue of the loading background must be "
                         "-180 to 180 degrees.".format(name))
    load_bg_name = slug + "_BACKGROUND"
    icon_path = images["icon_path"]
    # portrait mode without a portrait: keep the inherited icon
    icon_custom = bool(icon_path if icon_mode == "file"
                       else images["load_fg_path"])
    # one fallback texture per distinct image, named after the first slot
    # that uses it (each is a full-size texture in the mod)
    fallback_name = "FALLBACK_NEUTRAL_" + slug[len("LEADER_"):]
    textures = {os.path.normcase(os.path.abspath(images["load_fg_path"])):
                fallback_name} if images["load_fg_path"] else {}
    mood_images = []
    for key in MOOD_SLOT_KEYS:
        if key in mood_paths:
            texture = textures.setdefault(
                os.path.normcase(os.path.abspath(mood_paths[key])),
                "FALLBACK_{}_{}".format(key, slug[len("LEADER_"):]))
            mood_images.append((key, mood_paths[key], texture))

    # a new ability of the leader's own, with effects from the editor
    given = spec.get("new_ability") or {}
    new_ability = None
    if (given.get("name") or "").strip() or given.get("effects"):
        ability_name = (given.get("name") or "").strip()
        if not ability_name:
            raise ValueError("{}: give the new leader ability a name."
                             .format(name))
        trait = "TRAIT_" + slug
        check_effects(given.get("effects"), "trait", data,
                      "{} (leader ability)".format(name))
        sql, texts = effects_sql("trait", trait, given.get("effects") or [],
                                 ability_name, data.type_name)
        new_ability = {
            "trait": trait, "name": ability_name,
            # no description: one made of the effects
            "desc": (given.get("desc") or "").strip() or "[NEWLINE]".join(
                summary(e, data.type_name)
                for e in given.get("effects") or []) or ability_name,
            "replace": bool(given.get("replace")),
            "name_tag": "LOC_{}_NAME".format(trait),
            "desc_tag": "LOC_{}_DESCRIPTION".format(trait),
            "effects_sql": sql, "effects_texts": texts}

    ai_traits, scene_leader = [], ""
    if not orig:
        # a new leader: everything the original would have given
        if not new_ability:
            raise ValueError(
                "{}: a leader that inherits from nobody needs an ability "
                "of its own - give it a name on the Ability tab.".format(
                    name))
        new_ability["replace"] = True       # nothing to add it to
        if not agenda and not own_agenda:
            raise ValueError("{}: a leader that inherits from nobody needs "
                             "an AI agenda - pick one on the Agenda tab."
                             .format(name))
        for trait in spec.get("ai_traits") or []:
            trait = str(trait).strip().upper()
            if not re.fullmatch(r"TRAIT_[A-Z0-9_]+", trait):
                raise ValueError("{}: AI trait '{}' is not a trait type."
                                 .format(name, trait))
            if trait not in ai_traits:
                ai_traits.append(trait)
    scene_leader = (spec.get("scene_leader") or "").strip().upper()
    if scene_leader and not scene_leader.startswith("LEADER_"):
        raise ValueError("{}: diplomacy scene '{}' must be a LEADER_ type."
                         .format(name, scene_leader))

    meta = data.meta(orig)
    icon_inherit = (meta.get("icon") or "ICON_{}".format(orig)) if orig \
        else DEFAULT_LEADER_ICON
    return {
        "name": name,
        "slug": slug,
        # the type is already in the loaded game data - usually an earlier
        # build of this very mod; the caller decides whether that is fine
        "exists_in_game": slug in data.leader_meta,
        "civ": civ,
        # the project's civilization the leader leads, or None (a game
        # civilization)
        "project_civ": (civs or {}).get(civ),
        "orig": orig,
        # what the leader inherits from, for comments and the report
        "orig_label": orig or "nobody",
        # unique items of the original leader's own (to show on the setup
        # screen of a new civilization's leader)
        "orig_items": data.leader_unique_items(orig) if orig else [],
        # a game civilization's own unique items (setup screen of a leader
        # without orig; None without the game cache)
        "civ_items": data.uniques_for(civ, "") if data.conn else None,
        "ai_traits": ai_traits,
        # the leader whose layered diplomacy scene is shown without a
        # background of its own ("" = the game's default scene)
        "scene_source": scene_leader or orig,
        "new_ability": new_ability,
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
        "load_bg_hue": load_bg_hue,
        "load_fg": slug + "_NEUTRAL" if images["load_fg_path"] else None,
        "load_bg": load_bg_name if images["load_bg_path"] else None,
        # 2D diplomacy-screen image (made from the loading portrait),
        # named like the SDK template's FALLBACK_NEUTRAL_JASPERKITTY
        "fallback_name": fallback_name,
        # ... and the ones it changes to by mood: [(slot, path, texture)]
        # (a texture may be shared, also with the portrait's)
        "mood_images": mood_images,
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
        "agenda_clone": bool(agenda_name or agenda_desc) and not own_agenda,
        # ... or an agenda of its own (see agendas.normalize_own_agenda;
        # its name and description are agenda_name / agenda_desc)
        "own_agenda": own_agenda,
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


def ability_config_column(c, column, key):
    """SQL for a setup-screen ability column (key 'name' or 'desc'): the
    renamed ability's new text tag where the original shows its source's
    tag, or the column as is. A new ability of the leader's own is the
    one shown."""
    if c.get("new_ability"):
        return sql_str(c["new_ability"]["{}_tag".format(key)])
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
    if c.get("project_civ"):
        return new_civ_config_block(c)
    if not c["orig"]:
        return new_leader_config_block(c)
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


def value_or_null(value):
    return sql_str(value) if value else "NULL"


def new_leader_config_block(c):
    """Setup-screen rows of a leader that inherits from nobody, of a game
    civilization: the civilization's fields and rulesets from its other
    leaders' rows, and the civilization's own unique items."""
    civ = sql_str(c["civ"])
    if c["civ_items"] is not None:
        items = """INSERT INTO PlayerItems (Domain, CivilizationType, LeaderType, Type, Name, Description, Icon, SortIndex)
SELECT Domain, CivilizationType, '{slug}', Type, Name, Description, Icon, MIN(SortIndex)
FROM PlayerItems WHERE CivilizationType = {civ} AND LeaderType != '{slug}'
AND Type IN ({items})
GROUP BY Domain, Type;
""".format(slug=c["slug"], civ=civ,
           items=", ".join(map(sql_str, c["civ_items"])) or "NULL")
    else:
        # no game cache: the items every leader of the civilization has
        items = """INSERT INTO PlayerItems (Domain, CivilizationType, LeaderType, Type, Name, Description, Icon, SortIndex)
SELECT i.Domain, i.CivilizationType, '{slug}', i.Type, i.Name, i.Description, i.Icon, MIN(i.SortIndex)
FROM PlayerItems i WHERE i.CivilizationType = {civ} AND i.LeaderType != '{slug}'
GROUP BY i.Domain, i.Type
HAVING COUNT(DISTINCT i.LeaderType) = (
    SELECT COUNT(*) FROM Players p WHERE p.Domain = i.Domain
    AND p.CivilizationType = {civ} AND p.LeaderType != '{slug}');
""".format(slug=c["slug"], civ=civ)
    return """-----------------------------------------------
-- Setup-screen rows for {slug}, a new leader of {civ_name}
-- (the civilization's fields from its other leaders)
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
FROM Players WHERE CivilizationType = {civ} AND LeaderType != '{slug}'
GROUP BY Domain;

{items}""".format(
        slug=c["slug"], civ=civ, civ_name=c["civ"], name_tag=c["name_tag"],
        leader_icon=sql_str(c["leader_icon"]),
        ability_name=sql_str(c["new_ability"]["name_tag"]),
        ability_desc=sql_str(c["new_ability"]["desc_tag"]),
        portrait=value_or_null(c["load_fg"]),
        portrait_bg=value_or_null(c["load_bg"]), items=items)


def new_civ_config_block(c):
    """Setup-screen rows of a leader of one of the project's new
    civilizations: the civilization's own fields, the original leader's
    rulesets (domains), and the civilization's uniques plus the original
    leader's own unique items."""
    civ = c["project_civ"]
    domains = ", ".join(map(sql_str, STANDARD_DOMAINS))
    items = "".join(player_item_sql(u, c["slug"], 10 * i)
                    for i, u in enumerate(civ["uniques"], 1))
    if c["orig_items"]:
        items += """INSERT INTO PlayerItems (Domain, CivilizationType, LeaderType, Type, Name, Description, Icon, SortIndex)
SELECT Domain, {civ}, '{slug}', Type, Name, Description, Icon, SortIndex + 100
FROM PlayerItems WHERE LeaderType = '{orig}' AND Domain IN ({domains})
AND Type IN ({items});
""".format(civ=sql_str(civ["slug"]), slug=c["slug"], orig=c["orig"],
           domains=domains, items=", ".join(map(sql_str, c["orig_items"])))
    if c["orig"]:
        # the original leader's rulesets
        source = "FROM Players WHERE LeaderType = '{}' AND Domain IN ({})" \
            .format(c["orig"], domains)
        portrait = value_or_column(c["load_fg"], "Portrait")
        portrait_bg = value_or_column(c["load_bg"], "PortraitBackground")
    else:
        source = "FROM ({})".format(" UNION ALL ".join(
            "SELECT {} AS Domain".format(sql_str(d))
            for d in STANDARD_DOMAINS))
        portrait = value_or_null(c["load_fg"])
        portrait_bg = value_or_null(c["load_bg"])
    return """-----------------------------------------------
-- Setup-screen rows for {slug} of the new civilization {civ}
-- (inherits from {orig})
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
    Domain, {civ_s}, '{slug}',
    {civ_name}, {civ_icon},
    {ability_name}, {ability_desc}, {civ_icon},
    '{name_tag}', {leader_icon},
    {leader_ability_name}, {leader_ability_desc}, {leader_icon},
    {portrait}, {portrait_bg}
{source};

{items}""".format(
        slug=c["slug"], orig=c["orig_label"], civ=civ["slug"],
        source=source,
        civ_s=sql_str(civ["slug"]), civ_name=sql_str(civ["name_tag"]),
        civ_icon=sql_str(civ["icon_name"]),
        ability_name=sql_str(civ["ability"]["name_tag"]),
        ability_desc=sql_str(civ["ability"]["desc_tag"]),
        name_tag=c["name_tag"], leader_icon=sql_str(c["leader_icon"]),
        leader_ability_name=ability_config_column(c, "LeaderAbilityName",
                                                  "name"),
        leader_ability_desc=ability_config_column(
            c, "LeaderAbilityDescription", "desc"),
        portrait=portrait, portrait_bg=portrait_bg, items=items)


def agenda_block(c):
    """HistoricalAgendas SQL for one leader: the original leader's agenda,
    another existing agenda, or a renamed copy of either. A copy shares the
    source's traits, so its behaviour (modifiers and AI lists, which are
    keyed by trait) is identical; only its name / description differ."""
    slug, orig = c["slug"], c["orig"]
    if c["own_agenda"]:
        return own_agenda_sql(slug, c["own_agenda"])
    if not orig:
        return new_agenda_block(c)
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
        out = agenda_copy_sql(c, source)
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


def new_agenda_block(c):
    """HistoricalAgendas SQL of a leader that inherits from nobody: the
    chosen agenda, or a renamed copy of it."""
    source = sql_str(c["agenda"])
    if c["agenda_clone"]:
        target = sql_str(c["agenda_type"])
        out = agenda_copy_sql(c, source)
    else:
        target = source
        out = "-- AI agenda\n"
    return out + """INSERT INTO HistoricalAgendas (LeaderType, AgendaType)
SELECT '{slug}', AgendaType FROM Agendas WHERE AgendaType = {target};
""".format(slug=c["slug"], target=target)


def agenda_copy_sql(c, source):
    """SQL making the leader's renamed copy of the agenda source (an SQL
    expression)."""
    return """-- AI agenda: a copy of {what} with its own name / description.
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

""".format(what=c["agenda"] or "the agenda of " + c["orig"],
           target=sql_str(c["agenda_type"]), source=source,
           name=value_or_column(c["agenda_name"] and c["agenda_name_tag"],
                                "Name"),
           desc=value_or_column(c["agenda_desc"] and c["agenda_desc_tag"],
                                "Description"))


def ability_block(c):
    """LeaderTraits SQL for one leader: the inherited traits (see
    inherited_ability_block) plus a new ability of its own, if any, which
    may replace the inherited abilities."""
    new = c.get("new_ability")
    if not new:
        return inherited_ability_block(c)
    if not c["orig"]:
        out = "-- a new leader: its own ability and AI personality\n"
        if c["ai_traits"]:
            out += """INSERT INTO LeaderTraits (LeaderType, TraitType)
SELECT '{slug}', TraitType FROM Traits WHERE TraitType IN ({traits});
""".format(slug=c["slug"], traits=", ".join(map(sql_str, c["ai_traits"])))
    elif new["replace"]:
        # keep the original's other traits (AI preferences, unique items)
        out = """-- INHERIT the original leader's traits, except its abilities: the
-- new ability below replaces them
INSERT INTO LeaderTraits (LeaderType, TraitType)
SELECT '{slug}', TraitType FROM LeaderTraits WHERE LeaderType = '{orig}'
AND TraitType NOT IN (
    SELECT TraitType FROM Traits WHERE Name IS NOT NULL AND InternalOnly = 0
    AND TraitType NOT IN (
        SELECT TraitType FROM Units WHERE TraitType IS NOT NULL UNION
        SELECT TraitType FROM Buildings WHERE TraitType IS NOT NULL UNION
        SELECT TraitType FROM Districts WHERE TraitType IS NOT NULL UNION
        SELECT TraitType FROM Improvements WHERE TraitType IS NOT NULL));
""".format(slug=c["slug"], orig=c["orig"])
    else:
        out = inherited_ability_block(c)
    return out + """
-- the leader's own new ability
INSERT INTO Types (Type, Kind) VALUES ({trait}, 'KIND_TRAIT');
INSERT INTO Traits (TraitType, Name, Description) VALUES ({trait}, {name}, {desc});
INSERT INTO LeaderTraits (LeaderType, TraitType) VALUES ('{slug}', {trait});
{effects}""".format(trait=sql_str(new["trait"]), name=sql_str(new["name_tag"]),
                    desc=sql_str(new["desc_tag"]), slug=c["slug"],
                    effects=new["effects_sql"])


def inherited_ability_block(c):
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
    the original leader's capital (a new civilization's: its first city
    name)."""
    if c["city_names"]:
        return """-- capital: the first of this leader's own city names
INSERT INTO CivilizationLeaders (CivilizationType, LeaderType, CapitalName)
VALUES ('{civ}', '{slug}', '{capital}');
""".format(civ=c["civ"], slug=c["slug"], capital=c["city_names"][0][0])
    if c.get("project_civ"):
        return """-- capital: the first of the civilization's city names
INSERT INTO CivilizationLeaders (CivilizationType, LeaderType, CapitalName)
VALUES ('{civ}', '{slug}', '{capital}');
""".format(civ=c["civ"], slug=c["slug"],
           capital=c["project_civ"]["city_names"][0][0])
    if not c["orig"]:
        return """-- CapitalName is NOT NULL; the capital of the civilization's other
-- leaders
INSERT INTO CivilizationLeaders (CivilizationType, LeaderType, CapitalName)
SELECT '{civ}', '{slug}', CapitalName
FROM CivilizationLeaders WHERE CivilizationType = '{civ}' AND LeaderType != '{slug}'
LIMIT 1;
""".format(civ=c["civ"], slug=c["slug"])
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
    """AltLeaderScenes row: show the layered diplomacy scene of the
    original leader or the chosen scene leader (or, for a generated one,
    the scene it shows)."""
    if not c["scene_from_orig"]:
        return ""
    return """
-- no diplomacy background of its own: show {orig}'s layered scene
INSERT OR REPLACE INTO AltLeaderScenes (LeaderType, SceneLeaderType)
SELECT '{slug}', COALESCE((SELECT SceneLeaderType FROM AltLeaderScenes
                           WHERE LeaderType = '{orig}'), '{orig}');
""".format(slug=c["slug"], orig=c["scene_source"])


def gameplay_block(c):
    """Core gameplay SQL fragment for one leader."""
    if not c["orig"]:
        return new_gameplay_block(c)
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
           orig=c["orig"], sex=sql_str(c["sex"]),
           bio_tag=c["bio_tag"], quote_tag=c["quote_tag"],
           load_fg=value_or_column(c["load_fg"], "ForegroundImage"),
           load_bg=value_or_column(c["load_bg"], "BackgroundImage"))


def new_gameplay_block(c):
    """Core gameplay SQL of a leader that inherits from nobody."""
    return """-----------------------------------------------
-- {name} ({slug}), a new leader
-----------------------------------------------
INSERT INTO Types (Type, Kind)
VALUES ('{slug}', 'KIND_LEADER');

-- InheritFrom LEADER_DEFAULT, like every leader: it gives the traits all
-- major civilizations share
INSERT INTO Leaders (LeaderType, Name, InheritFrom, Sex, SceneLayers)
VALUES ('{slug}', '{name_tag}', 'LEADER_DEFAULT', {sex}, 0);

{capital}{city_names}
{ability}
{agenda}
-- Loading screen: this leader's own bio and images (none: an empty
-- portrait)
INSERT INTO LoadingInfo (LeaderType, ForegroundImage, BackgroundImage, PlayDawnOfManAudio, LeaderText)
VALUES ('{slug}', {load_fg}, {load_bg}, 0, '{bio_tag}');

INSERT INTO LeaderQuotes (LeaderType, Quote)
VALUES ('{slug}', '{quote_tag}');

-- Diplomacy-screen background (none: the game's default scene, or the
-- chosen leader's scene below)
INSERT INTO DiplomacyInfo (Type, BackgroundImage)
VALUES ('{slug}', {diplo_bg});
{scene}""".format(name=c["name"], slug=c["slug"], name_tag=c["name_tag"],
           agenda=agenda_block(c), ability=ability_block(c),
           capital=capital_block(c), scene=scene_block(c),
           city_names=city_names_block(c), sex=sql_str(c["sex"]),
           bio_tag=c["bio_tag"], quote_tag=c["quote_tag"],
           load_fg=value_or_null(c["load_fg"]),
           load_bg=value_or_null(c["load_bg"]),
           diplo_bg=value_or_null(c["diplo_bg"]))


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
    if c["own_agenda"]:
        pairs += c["own_agenda"]["texts"]
    for a in c["abilities"]:
        pairs += [(a["name_tag"], a["name"]), (a["desc_tag"], a["desc"])]
    new = c.get("new_ability")
    if new:
        pairs += [(new["name_tag"], new["name"]),
                  (new["desc_tag"], new["desc"])]
        pairs += new["effects_texts"]
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
    leader's text, in every language the game has it in - or, for a leader
    that inherits from nobody, the game's generic lines (where there are
    some)."""
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
                    sql_str(candidate.format(L=c["orig"] or "ANY"))))
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
    # an atlas may hold several icons in a row (c["icon_defs"]: [(icon
    # name, index)], e.g. a unique unit's portrait and icon)
    defs = c.get("icon_defs") or [(c["icon_name"], 0)]
    atlas_rows = "\n".join(
        '    <Row Name="{atlas}" IconSize="{size}" IconsPerRow="{per_row}" '
        'IconsPerColumn="1" Filename="{texture}"/>'.format(
            atlas=c["icon_atlas"], size=size, texture=texture,
            per_row=len(defs))
        for size, texture in icon_files)
    def_row = "\n".join(
        '    <Row Name="{icon}" Atlas="{atlas}" Index="{index}"/>'.format(
            icon=name, atlas=c["icon_atlas"], index=index)
        for name, index in defs)
    return atlas_rows, def_row


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
