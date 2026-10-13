"""Whole-mod file builders (.modinfo, SQL, XML, README)."""

import os
import shutil
import tempfile
import xml.etree.ElementTree as ET

from .util import (asset_path, find_game_dir, sql_str, type_display_name,
                   xml_escape)
from .artdefs import (CIVILIZATIONS_ARTDEF, CULTURES_ARTDEF,
                      UNITS_ARTDEF, build_artdef, build_dep,
                      civilization_element_xml, civilization_music,
                      culture_element_xml, element_name, find_game_element,
                      renamed_element_xml)
from .art import (DIPLO_BG_MASK, ICON_SIZES, MOMENT_HALF_OPACITY, MOMENT_MASK,
                  PORTRAIT_SIZE, add_texture, apply_image_mask, cook_art,
                  atlas_image, fitted_portrait, make_circle_icon,
                  shift_hue)
from .workshop import STAMP_FILE
from .moments import MOMENT_ILLUSTRATION_SIZE
from .moods import fallback_slot, resolve_slot
from .moods import slot_label as mood_label
from .leaders import (colors_fragment, config_block,
                      gameplay_block, icons_fragment, inherited_text_sql,
                      needs_art, normalize_spec, text_rows)
from .civs import (CIV_ICON_SIZES, DEFAULT_MUSIC, civ_gameplay_sql,
                   civ_icons_sql, civ_text_rows, normalize_civ)
from .uniques import ART as UNIQUE_ART
from .uniques import ICON_SIZES as UNIQUE_ICON_SIZES
from .uniques import unique_icons_sql
from .unit_art import describe as describe_unit_art
from .unit_art import is_custom as is_custom_art
from .unit_art import unique_unit_art
from .landmarks import (LANDMARKS_ARTDEF, building_districts,
                        building_landmark_parts, district_landmark,
                        landmark_buildings, landmark_xml, merged_landmark,
                        set_landmark_xref)

# .artdef file -> root collection of unique items' art definitions
UNIQUE_ART_COLLECTIONS = dict(UNIQUE_ART.values())


# ---------------------------------------------------------------------------
# Whole-mod file builders
# ---------------------------------------------------------------------------

# Every action needs a unique id attribute - the game silently skips
# actions without one. The high LoadOrder makes our SQL run after DLC
# content, so INSERT ... SELECT can copy rows of DLC leaders too.
ICONS_ACTION = ("\n    <UpdateIcons id=\"{scope}Icons\">\n"
                "      <File>Config/NewLeader_Icons.xml</File>\n"
                "    </UpdateIcons>")
ART_ACTION = ("\n    <UpdateArt id=\"{scope}Art\">\n"
              "      <File>{dep}</File>\n"
              "    </UpdateArt>")


# Historic moments only exist with Rise and Fall / Gathering Storm; without
# them the MomentIllustrations table is missing, so the rows get their own
# action that only runs then (criteria as in Firaxis' DLC modinfos).
EXPANSION1_CRITERION = """
    <Criteria id="Expansion1AndBeyond" any="1">
      <GameCoreInUse>Expansion1</GameCoreInUse>
      <GameCoreInUse>Expansion2</GameCoreInUse>
      <RuleSetInUse>RULESET_EXPANSION_1,RULESET_EXPANSION_2</RuleSetInUse>
    </Criteria>"""
MOMENTS_FILE = "Gameplay/NewLeader_Moments.sql"
MOMENTS_ACTION = """
    <UpdateDatabase id="InGameMoments">
      <Properties><LoadOrder>1000</LoadOrder></Properties>
      <Criteria>Expansion1AndBeyond</Criteria>
      <File>{}</File>
    </UpdateDatabase>""".format(MOMENTS_FILE)

# Rows of unique items in Gathering Storm-only tables (Units_XP2, ...)
EXPANSION2_CRITERION = """
    <Criteria id="Expansion2AndBeyond" any="1">
      <GameCoreInUse>Expansion2</GameCoreInUse>
      <RuleSetInUse>RULESET_EXPANSION_2</RuleSetInUse>
    </Criteria>"""
XP2_FILE = "Gameplay/NewCiv_XP2.sql"
XP2_ACTION = """
    <UpdateDatabase id="InGameXP2">
      <Properties><LoadOrder>1001</LoadOrder></Properties>
      <Criteria>Expansion2AndBeyond</Criteria>
      <File>{}</File>
    </UpdateDatabase>""".format(XP2_FILE)

# Icons of new civilizations and uniques that are the game's own icons
# under new names (copied IconDefinitions rows)
ICONS_SQL_FILE = "Config/NewCiv_Icons.sql"
ICONS_SQL_ACTION = ("\n    <UpdateIcons id=\"{scope}Icons\">\n"
                    "      <Properties><LoadOrder>1000</LoadOrder></Properties>\n"
                    "{xml}"
                    "      <File>" + ICONS_SQL_FILE + "</File>\n"
                    "    </UpdateIcons>")


# Diplomacy-screen backgrounds. LeaderScene.lua shows DiplomacyInfo's single
# image if the leader has one, else the layered scene textures named after
# the leader type (VICTORIA_1..SceneLayers). Base-game leaders have no
# DiplomacyInfo row, and a generated leader has no layers under its own
# name, so the mod ships a copy of the game's LeaderScene.lua that shows
# the scene of the leader named in AltLeaderScenes instead. All generated
# packs share the table and the patch, so whichever copy wins works for
# every pack.
LEADER_SCENE_FILE = "UI/LeaderScene.lua"
LEADER_SCENE_SOURCE = os.path.join("Base", "Assets", "UI", "LeaderScene.lua")
LEADER_SCENE_ANCHOR = "m_oldLeaderName = leaderName;"
LEADER_SCENE_PATCH = """
		-- Alt Leader Generator: a leader without a diplomacy background of
		-- its own shows the scene of the leader it was made from.
		local altInfo = GameInfo.DiplomacyInfo[leaderName];
		local altScene = GameInfo.AltLeaderScenes and GameInfo.AltLeaderScenes[leaderName];
		if altScene and not (altInfo and altInfo.BackgroundImage) and GameInfo.Leaders[altScene.SceneLeaderType] then
			leaderName = altScene.SceneLeaderType;
		end"""
LEADER_SCENE_ACTION = """
    <ImportFiles id="InGameLeaderScene">
      <File>{}</File>
    </ImportFiles>""".format(LEADER_SCENE_FILE)
ALT_SCENES_TABLE = """-- leader -> leader whose layered diplomacy scene it shows (read by this
-- mod's UI/LeaderScene.lua; shared by every generated alt-leader pack)
CREATE TABLE IF NOT EXISTS AltLeaderScenes (
	LeaderType TEXT NOT NULL PRIMARY KEY,
	SceneLeaderType TEXT NOT NULL);
"""


def patched_leader_scene(game_dir):
    """The game's LeaderScene.lua with LEADER_SCENE_PATCH added, or
    (None, reason) when it cannot be patched. Returns (text, None)."""
    if not game_dir:
        return None, "the Civ VI install folder was not found"
    path = os.path.join(game_dir, LEADER_SCENE_SOURCE)
    try:
        with open(path, encoding="utf-8-sig") as fh:
            text = fh.read()
    except OSError as exc:
        return None, "cannot read {} ({})".format(path, exc)
    if "AltLeaderScenes" in text:
        return text, None               # already patched
    if text.count(LEADER_SCENE_ANCHOR) != 1:
        return None, "{} has changed; cannot patch it".format(path)
    return text.replace(LEADER_SCENE_ANCHOR,
                        LEADER_SCENE_ANCHOR + LEADER_SCENE_PATCH), None


def modinfo_name(folder):
    """The .modinfo's file name: the mod's folder name (what the Steam
    Workshop uploader's file dialog shows)."""
    return folder + ".modinfo"


def build_modinfo(mod_name, description, guid, has_icons, dep_file, files,
                  has_moments=False, has_scene=False, icons_sql=False,
                  has_xp2=False, has_civs=False, version=1, authors=""):
    """dep_file: mod-relative .dep path when art (cooked or .artdef files)
    exists, else None. has_moments: add the expansion-only historic moment
    action. has_scene: import the patched UI/LeaderScene.lua. icons_sql:
    add ICONS_SQL_FILE (icons copied from the game's) to the icon action.
    has_xp2: add the Gathering Storm-only XP2_FILE action. has_civs: the
    mod adds civilizations. version: the mod's version (raise it for each
    Workshop update); authors: shown in the game's mod list. The mod
    changes gameplay, so saved games need it (AffectsSavedGames)."""
    def icons(scope):
        if has_icons and not icons_sql:
            out = ICONS_ACTION.format(scope=scope)
        elif icons_sql:
            out = ICONS_SQL_ACTION.format(scope=scope, xml=(
                "      <File>Config/NewLeader_Icons.xml</File>\n"
                if has_icons else ""))
        else:
            out = ""
        if dep_file:
            out += ART_ACTION.format(scope=scope, dep=xml_escape(dep_file))
        if scope == "InGame" and has_moments:
            out += MOMENTS_ACTION
        if scope == "InGame" and has_xp2:
            out += XP2_ACTION
        if scope == "InGame" and has_scene:
            out += LEADER_SCENE_ACTION
        return out

    criteria = "\n  <ActionCriteria/>"
    if has_moments or has_xp2:
        criteria = "\n  <ActionCriteria>{}{}\n  </ActionCriteria>".format(
            EXPANSION1_CRITERION if has_moments else "",
            EXPANSION2_CRITERION if has_xp2 else "")
    return """<?xml version="1.0" encoding="utf-8"?>
<Mod id="{guid}" version="{version}">
  <Properties>
    <Name>{mod_name}</Name>
    <Teaser>{teaser}</Teaser>
    <Description>{description}</Description>
    <Authors>{authors}</Authors>
    <AffectsSavedGames>1</AffectsSavedGames>
    <CompatibleVersions>1.2,2.0</CompatibleVersions>
  </Properties>
  <Dependencies/>{criteria}
  <InGameActions>
    <UpdateDatabase id="InGameDatabase">
      <Properties><LoadOrder>1000</LoadOrder></Properties>
      <File>Gameplay/NewLeader_Gameplay.sql</File>
    </UpdateDatabase>{ingame_icons}
    <UpdateColors id="InGameColors">
      <File>Config/NewLeader_Colors.xml</File>
    </UpdateColors>
    <UpdateText id="InGameText">
      <Properties><LoadOrder>1000</LoadOrder></Properties>
      <File>Text/NewLeader_Text.sql</File>
    </UpdateText>
  </InGameActions>
  <FrontEndActions>
    <UpdateDatabase id="FrontEndDatabase">
      <Properties><LoadOrder>1000</LoadOrder></Properties>
      <File>Config/NewLeader_Config.sql</File>
    </UpdateDatabase>{frontend_icons}
    <UpdateColors id="FrontEndColors">
      <File>Config/NewLeader_Colors.xml</File>
    </UpdateColors>
    <UpdateText id="FrontEndText">
      <Properties><LoadOrder>1000</LoadOrder></Properties>
      <File>Text/NewLeader_Text.sql</File>
    </UpdateText>
  </FrontEndActions>
  <Files>
{files}
  </Files>
</Mod>
""".format(guid=guid, mod_name=xml_escape(mod_name),
           description=xml_escape(description), version=int(version),
           authors=xml_escape(authors or "Made with Civ 6 Mod Generator"),
           ingame_icons=icons("InGame"), frontend_icons=icons("FrontEnd"),
           criteria=criteria,
           teaser="New civilizations and leaders" if has_civs
           else "Alternate leaders for existing civilizations",
           files="\n".join("    <File>{}</File>".format(xml_escape(f))
                           for f in files))


def build_config_sql(ctxs):
    return "\n".join(config_block(c) for c in ctxs)


def build_gameplay_sql(ctxs):
    head = ALT_SCENES_TABLE if any(c["scene_from_orig"] for c in ctxs) \
        else ""
    return head + "\n\n".join(gameplay_block(c) for c in ctxs)


def text_row(tag, text):
    return "({}, {}, {})".format(sql_str("en_US"), sql_str(tag),
                                 sql_str(text))


def build_moments_sql(ctxs):
    """Custom pictures for the engine's 'first unique ...' historic
    moments. OR REPLACE: the row replaces Firaxis' picture for that item."""
    rows = ["({}, {}, {}, {})".format(
        sql_str(m["illustration"]), sql_str(m["data_type"]),
        sql_str(m["item"]), sql_str(m["texture"] + ".dds"))
        for c in ctxs for m in c["moments"]]
    return ("-- Historic moment illustrations (Rise and Fall / Gathering "
            "Storm only).\n"
            "INSERT OR REPLACE INTO MomentIllustrations\n"
            "    (MomentIllustrationType, MomentDataType, GameDataType, "
            "Texture)\nVALUES\n{};\n".format(",\n".join(rows)))


def build_text_sql(ctxs, extra=()):
    """extra: (tag, English text) pairs of the new civilizations."""
    rows = [text_row(tag, text) for tag, text in extra]
    for c in ctxs:
        rows.extend(text_rows(c))
    inherited = []
    for c in ctxs:
        lines = inherited_text_sql(c)
        if lines:
            inherited.append("\n-- {}: lines left empty reuse the text of {}"
                             .format(c["name"], c["orig"] or
                                     "the game's generic lines"))
            inherited.extend(lines)
    return ("-- All customizable text for {} leader(s).\n"
            "INSERT OR REPLACE INTO LocalizedText (Language, Tag, Text) "
            "VALUES\n{};\n{}\n".format(len(ctxs), ",\n".join(rows),
                                        "\n".join(inherited)))


def build_colors_xml(ctxs):
    color_rows, player_rows = [], []
    for c in ctxs:
        cr, pr = colors_fragment(c)
        color_rows.append(cr)
        player_rows.append(pr)
    return """<?xml version="1.0" encoding="utf-8"?>
<!-- Leader colors: city banners, map tint, diplo screen tint. -->
<GameData>
  <Colors>
{colors}
  </Colors>
  <PlayerColors>
{players}
  </PlayerColors>
</GameData>
""".format(colors="\n".join(color_rows), players="\n".join(player_rows))


def build_icons_xml(icon_leader_files):
    """icon_leader_files: list of (ctx, icon_files)."""
    atlas_rows, def_rows = [], []
    for c, files in icon_leader_files:
        ar, dr = icons_fragment(c, files)
        atlas_rows.append(ar)
        def_rows.append(dr)
    return """<?xml version="1.0" encoding="utf-8"?>
<!-- Leader icon atlases. The .dds files live in the Art/ folder and are
     referenced relative to the mod root. -->
<GameData>
  <IconTextureAtlases>
{atlases}
  </IconTextureAtlases>
  <IconDefinitions>
{defs}
  </IconDefinitions>
</GameData>
""".format(atlases="\n".join(atlas_rows), defs="\n".join(def_rows))


def readme_agenda(c):
    """README note on a leader's agenda, or "" if it is the original's."""
    if not c["agenda"] and not c["agenda_clone"]:
        return ""
    note = ", agenda: " + (c["agenda"] or "inherited")
    if c["agenda_name"]:
        note += ' renamed "{}"'.format(c["agenda_name"])
    elif c["agenda_clone"]:
        note += " with a new description"
    return note


def readme_abilities(c):
    """README note on a leader's renamed abilities, or ""."""
    return "".join(
        ", ability {}{}".format(a["source"], ' renamed "{}"'.format(a["name"])
                                if a["name"] else " with a new description")
        for a in c["abilities"])


def readme_civs(civs):
    """README section on new civilizations, or ""."""
    if not civs:
        return ""
    lines = []
    for cc in civs:
        lines.append("  * {} ({}) - ability \"{}\", {} city names, {} "
                     "unique(s)".format(
                         cc["name"], cc["slug"],
                         cc["ability"]["name"] or cc["ability"]["clone"][0],
                         len(cc["city_names"]), len(cc["uniques"])))
        lines += ["      {} {} ({}), {}{}{}".format(
            u["kind"], u["name"], u["slug"],
            "a copy of " + u["base"] if u["base"] else
            "new" + (" (in {})".format(u["district"]) if u["district"]
                     else ""),
            ", replacing " + u["replaced"] if u["replaced"] else
            ", replacing nothing",
            "; 3D model: " + describe_unit_art(u["art"])
            if is_custom_art(u.get("art")) else "")
            for u in cc["uniques"]]
    return """CIVILIZATIONS
{}

  New civilizations use existing art: a city and unit style
  (ArtDefs/Cultures.artdef), another civilization's music
  (ArtDefs/Civilizations.artdef) and, for unique units, buildings and
  districts, the 3D art and icons of the item they copy (ArtDefs/Units /
  Buildings / Districts.artdef, Config/NewCiv_Icons.sql). A unique
  building has no 3D model of its own inside its district (like many
  mods' uniques). Effects ("modifiers") are the game's own modifier types;
  ability descriptions are the text you wrote, not generated from the
  effects. Rows of Gathering Storm-only tables are in
  Gameplay/NewCiv_XP2.sql, which only loads with Gathering Storm.

""".format("\n".join(lines))


def build_readme(mod_name, ctxs, icon_count, report, civs=(),
                 modinfo="MyLeader.modinfo"):
    lines = "\n".join(
        "  * {name} ({slug}) - {civ}, inherits from {orig}{ability}{agenda}"
        "{cities}".format(
            name=c["name"], slug=c["slug"], civ=c["civ"],
            orig=c["orig_label"],
            ability=readme_abilities(c), agenda=readme_agenda(c),
            cities="; {} own city names, capital {}".format(
                len(c["city_names"]), c["city_names"][0][1])
            if c["city_names"] else "")
        for c in ctxs)
    return """{mod_name} (generated)
======================================================

An alternate-leader pack. Each leader inherits the ability of its
original leader and, unless another one was chosen, its AI agenda, and
shares the civilization's uniques. All gameplay effects are inherited;
everything textual and visual is defined by this mod's own files.

{civs}LEADERS
{lines}

FILES
  {modinfo:<30}mod registration
  Config/NewLeader_Config.sql   setup screen rows (Players / PlayerItems)
  Config/NewLeader_Icons.xml    leader icon atlases ({icon_count} custom)
  Config/NewLeader_Colors.xml    leader colors
  Gameplay/NewLeader_Gameplay.sql leaders, trait & agenda inheritance
  Gameplay/NewLeader_Moments.sql  historic moment pictures (if any;
                                  Rise and Fall / Gathering Storm only)
  Text/NewLeader_Text.sql       names, bios, quotes, diplomacy lines,
                                Civilopedia
  <ModFolder>.dep                art dependencies (loads the cooked .blp)
  Platforms/*/BLPs/              cooked icons, loading-screen and
                                 diplomacy (fallback) images
  ArtDefs/FallbackLeaders.artdef diplomacy-screen image(s) per leader

INSTALL
  Copy this folder into:
    Documents/My Games/Sid Meier's Civilization VI/Mods
  Enable it under Additional Content. If anything misbehaves, check
  Logs/Database.log in that same folder.

NOTES
  * Publishing: use "Publish to Workshop..." in the generator, which
    checks this folder and guides you through the Civ VI SDK's Steam
    Workshop uploader. The mod keeps its id between builds, so uploading
    again updates the same Workshop item ({modinfo}, id and version).
    .civgen_build only records what the mod was generated from.
  * The leader ability (traits) and its name/description are those of
    the original leader.
  * No 3D leader scene is generated; the diplomacy screen shows the 2D
    fallback image made from the loading portrait. A 3D scene requires
    the Blender -> Asset Editor art pipeline and is outside this
    generator's scope. Leaders with diplomacy portraits by mood list
    them in FallbackLeaders.artdef under the names of the animations
    the diplomacy screen plays (HAPPY_IDLE, UNHAPPY_NEGATIVE,
    DECLARE_WAR_FROM_AI, ...); other names show the DEFAULT (neutral)
    image.
  * Custom icons, loading portraits, loading backgrounds and diplomacy
    backgrounds are cooked into .blp packages with the Civ VI SDK asset
    cooker (install "Sid Meier's Civilization VI Development Tools" from
    Steam). The loading portrait is also used as the setup-screen
    portrait and the diplomacy-screen leader image. Art that is not
    customized is inherited from the original leader. Base-game leaders'
    diplomacy backgrounds are layered scenes that the database cannot
    point to, so leaders without a custom diplomacy background get a
    patched copy of the game's UI/LeaderScene.lua that shows the original
    leader's scene (listed in the AltLeaderScenes table). Another mod
    that also replaces LeaderScene.lua can override it.
  * Historic moment pictures replace the picture of the engine's
    "first unique unit / building / district / improvement" moments for
    that item. Mods cannot add new moments (their triggers are engine
    code), the picture is per item (so it applies to every leader of the
    civilization), and tech/civic moment pictures depend on the era only.
  * The "fade mask" options use the generator's assets/mask.png
    (diplomacy background) and assets/mask_historical.png (historic
    moment pictures, stretched to 456 x 332): white keeps the image, black
    becomes transparent. Historic moment pictures can also be made 75%
    transparent and/or sepia-toned. A packaged generator needs the
    assets folder next to the exe, or built in with Nuitka
    --include-data-dir=assets=assets.
  * Leaders with their own city names found their capital under the
    first name and name new cities from their list first; once it runs
    out, the civilization's own names are used.
  * Leaders inheriting from DLC leaders require that DLC installed;
    add <Dependencies> entries to the .modinfo to enforce it.

GENERATION LOG
{log}
""".format(mod_name=mod_name, lines=lines, icon_count=icon_count,
           modinfo=modinfo,
           civs=readme_civs(civs),
           log="\n".join("  " + r for r in report))


# ---------------------------------------------------------------------------
# Validating a whole project
# ---------------------------------------------------------------------------

def prepare_project(leader_specs, civ_specs, data, prefix=""):
    """Validate every civilization and leader spec of a project. Returns
    (civ contexts, leader contexts, errors); every problem found is in
    errors (human-friendly messages)."""
    errors, seen = [], {}
    civ_ctxs = []
    for spec in civ_specs:
        try:
            cc = normalize_civ(spec, data, prefix)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        types = [cc["slug"]] + [u["slug"] for u in cc["uniques"]]
        clash = next((t for t in types if t in seen), None)
        if clash:
            errors.append("{}: duplicate type {} (already used by {}) - "
                          "rename one of them.".format(cc["name"], clash,
                                                       seen[clash]))
            continue
        seen.update((t, cc["name"]) for t in types)
        civ_ctxs.append(cc)
    civs = {cc["slug"]: cc for cc in civ_ctxs}
    by_id = {cc["id"]: cc["slug"] for cc in civ_ctxs if cc["id"]}
    ctxs = []
    for spec in leader_specs:
        if spec.get("civ_id") in by_id:
            # the leader's civilization may have been renamed since
            spec = dict(spec, civ=by_id[spec["civ_id"]])
        try:
            c = normalize_spec(spec, data, prefix, civs)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if c["slug"] in seen:
            errors.append("{}: duplicate type {} (already used by {}) - "
                          "rename one of them.".format(
                              c["name"], c["slug"], seen[c["slug"]]))
            continue
        seen[c["slug"]] = c["name"]
        ctxs.append(c)
    for owner in civ_ctxs + ctxs:
        for m in owner["moments"]:
            # MomentIllustrations is keyed by the item
            other = seen.get(("moment", m["item"]))
            if other:
                errors.append("{}: {} already has a historic moment "
                              "picture from {} - the game allows one per "
                              "item.".format(owner["name"], m["item"],
                                             other))
            seen[("moment", m["item"])] = owner["name"]
    # references to items: one of the project's or of the game's - the
    # game refuses a mod referring to a type that does not exist
    own = {u["slug"]: u["kind"] for cc in civ_ctxs for u in cc["uniques"]}

    def known(item, kind=None):
        if item in own:
            return kind is None or own[item] == kind
        if not data.conn:
            return True                 # cannot tell; assume the game's
        kinds = [kind] if kind else ["unit", "building", "district",
                                     "improvement"]
        return any(data.item(k, item) for k in kinds)
    for owner in civ_ctxs + ctxs:
        for m in owner["moments"]:
            if not known(m["item"]):
                errors.append(
                    "{}: the historic moment picture is for {}, which is "
                    "neither one of the project's uniques nor in the game "
                    "(was the unique renamed, or the type prefix "
                    "changed?). Pick its item again on the Historic "
                    "moments tab.".format(owner["name"], m["item"]))
    for cc in civ_ctxs:
        for u in cc["uniques"]:
            if u["kind"] == "building" and u["district"] and \
                    not known(u["district"], "district"):
                errors.append(
                    "{}: it is built in {}, which is neither one of the "
                    "project's districts nor in the game. Pick its "
                    "district again (Stats tab).".format(u["label"],
                                                        u["district"]))
    led = {c["civ"] for c in ctxs}
    for cc in civ_ctxs:
        if cc["slug"] not in led:
            errors.append("{}: a civilization needs at least one leader - "
                          "add a leader whose civilization is {}.".format(
                              cc["name"], cc["slug"]))
    return civ_ctxs, ctxs, errors


# ---------------------------------------------------------------------------
# Writing a whole mod (no Tk: runs in a worker thread)
# ---------------------------------------------------------------------------

def write_mod(mod_name, ctxs, folder, mod_dir, guid, cooker, report,
              progress, civs=(), name_of=None, publish=None, stamp=None):
    """Cook the art and write every mod file (runs in a worker thread,
    so no Tk calls here; progress(text) updates the busy window). civs:
    contexts of the project's new civilizations (civs.normalize_civ);
    name_of(kind, type): English name of a game type (effect texts).
    publish: the .modinfo's Workshop values ({"version", "author",
    "description" - plain text}); stamp: written to STAMP_FILE (see
    workshop.build_stamp). Returns the number of custom icons. Raises
    OSError."""
    name_of = name_of or (lambda kind, t: type_display_name(t))
    icon_jobs = [(cc, cc["icon_path"], CIV_ICON_SIZES) for cc in civs
                 if cc["icon_custom"]]
    # (a unit's source: its atlas cells, see uniques.normalize_unique)
    icon_jobs += [(u, u["atlas_paths"] or u["icon_path"],
                   UNIQUE_ICON_SIZES[u["kind"]])
                  for cc in civs for u in cc["uniques"] if u["icon_custom"]]
    (icon_leader_files, cooked_files, ui_package,
     fallback_package) = build_art(ctxs, folder, mod_dir, report,
                                   cooker, progress, icon_jobs,
                                   [cc for cc in civs if cc["moments"]])
    progress("Writing mod files...")
    # after build_art, which clears ArtDefs/ unless it cooked fallbacks
    artdef_files = write_civ_artdefs(civs, mod_dir, report)
    dep_file = folder + ".dep" if cooked_files or artdef_files else None
    # (after the art fallback, which drops pictures it could not make)
    has_moments = any(c["moments"] for c in list(ctxs) + list(civs))
    civ_sql, xp2_sql, civ_texts = [], [], []
    for cc in civs:
        sql, xp2, texts = civ_gameplay_sql(cc, name_of)
        civ_sql.append(sql)
        if xp2:
            xp2_sql.append(xp2)
        civ_texts += civ_text_rows(cc) + texts
    icons_sql = "\n".join(filter(None, [civ_icons_sql(cc) for cc in civs] +
                                 [unique_icons_sql(u) for cc in civs
                                  for u in cc["uniques"]]))

    # leaders without a diplomacy background of their own show the
    # original leader's layered scene through a patched LeaderScene.lua
    scene_lua, scene_problem = None, None
    if any(not c["diplo_bg"] and c["scene_source"] for c in ctxs):
        scene_lua, scene_problem = patched_leader_scene(find_game_dir())
        if scene_problem:
            report.append("WARNING: {} - leaders without a diplomacy "
                          "background get an empty one".format(
                              scene_problem))
    for c in ctxs:
        c["scene_from_orig"] = bool(scene_lua and not c["diplo_bg"] and
                                    c["scene_source"])
    scene_path = os.path.join(mod_dir, *LEADER_SCENE_FILE.split("/"))

    mod_files = ["Config/NewLeader_Config.sql",
                 "Config/NewLeader_Colors.xml",
                 "Gameplay/NewLeader_Gameplay.sql",
                 "Text/NewLeader_Text.sql"]
    if icon_leader_files:
        mod_files.append("Config/NewLeader_Icons.xml")
    if icons_sql:
        mod_files.append(ICONS_SQL_FILE)
    if has_moments:
        mod_files.append(MOMENTS_FILE)
    if xp2_sql:
        mod_files.append(XP2_FILE)
    if scene_lua:
        mod_files.append(LEADER_SCENE_FILE)
    if dep_file:
        mod_files.append(dep_file)
        mod_files.extend(cooked_files)
        mod_files.extend("ArtDefs/" + f for f in artdef_files)

    publish = publish or {}
    description = "Adds alternate leaders: {}.".format(
        ", ".join(c["name"] for c in ctxs))
    if civs:
        description = "Adds civilizations: {}; leaders: {}.".format(
            ", ".join(cc["name"] for cc in civs),
            ", ".join(c["name"] for c in ctxs))
    # the Workshop description, as plain text (the game's mod list and
    # the uploader show it)
    description = publish.get("description") or description

    def write(rel, content):
        with open(os.path.join(mod_dir, rel), "w", encoding="utf-8",
                  newline="\n") as fh:
            fh.write(content)
        report.append("wrote " + rel)

    if dep_file:
        write(dep_file, build_dep(mod_name, guid, ui_package,
                                  fallback_package, artdef_files))
    elif os.path.isfile(os.path.join(mod_dir, folder + ".dep")):
        os.remove(os.path.join(mod_dir, folder + ".dep"))
    modinfo = modinfo_name(folder)
    write(modinfo,
          build_modinfo(mod_name, description, guid,
                        bool(icon_leader_files), dep_file,
                        mod_files, has_moments, bool(scene_lua),
                        bool(icons_sql), bool(xp2_sql), bool(civs),
                        publish.get("version", 1), publish.get("author", "")))
    # a .modinfo of an earlier build under another name would register
    # the mod twice
    for old in os.listdir(mod_dir):
        if old.lower().endswith(".modinfo") and old != modinfo:
            os.remove(os.path.join(mod_dir, old))
            report.append("removed old " + old)
    for rel, content in ((ICONS_SQL_FILE, icons_sql),
                         (XP2_FILE, "\n".join(xp2_sql))):
        if content:
            write(rel, content)
        elif os.path.isfile(os.path.join(mod_dir, rel)):
            os.remove(os.path.join(mod_dir, rel))
    if scene_lua:
        os.makedirs(os.path.dirname(scene_path), exist_ok=True)
        write(LEADER_SCENE_FILE, scene_lua)
    elif os.path.isfile(scene_path):
        os.remove(scene_path)
    if has_moments:
        write(MOMENTS_FILE, build_moments_sql(list(civs) + list(ctxs)))
    elif os.path.isfile(os.path.join(mod_dir, MOMENTS_FILE)):
        os.remove(os.path.join(mod_dir, MOMENTS_FILE))
    write("Config/NewLeader_Config.sql", build_config_sql(ctxs))
    if icon_leader_files:
        write("Config/NewLeader_Icons.xml",
              build_icons_xml(icon_leader_files))
    write("Config/NewLeader_Colors.xml", build_colors_xml(ctxs))
    # civilizations first: their leaders' rows refer to them
    write("Gameplay/NewLeader_Gameplay.sql",
          "\n".join(civ_sql) + build_gameplay_sql(ctxs))
    write("Text/NewLeader_Text.sql", build_text_sql(ctxs, civ_texts))
    write("README.txt", build_readme(mod_name, ctxs,
                                    len(icon_leader_files), report, civs,
                                    modinfo))
    if stamp:                           # what it was generated from
        write(STAMP_FILE, stamp)
    return len(icon_leader_files)


def first_building(game_dir, district, own_landmarks):
    """The first building a district's landmark draws (the project's own
    landmark or the game's), or None."""
    if not district:
        return None
    landmark = own_landmarks[district][0] if district in own_landmarks \
        else merged_landmark(game_dir, district)
    drawn = landmark_buildings(landmark) if landmark else []
    return drawn[0] if drawn else None


def write_civ_artdefs(civs, mod_dir, report):
    """ArtDefs/*.artdef of the new civilizations (music, city and unit
    styles) and their uniques (renamed copies of the base items' art).
    Returns the file names written."""
    if not civs:
        return []
    game_dir = find_game_dir()
    music = civilization_music(game_dir)
    civ_elements, cultures, unit_cultures = [], {}, {}
    items = {filename: [] for filename, _ in UNIQUE_ART.values()}
    members = []                        # designed unit models
    own_landmarks = {}   # district slug -> (landmark, districts it stands for)
    buildings = []                      # unique buildings

    def warner(u):
        return lambda text: report.append("WARNING: {} - {}".format(
            u["label"], text))
    for cc in civs:
        xref = music.get(cc["music_from"])
        if not xref:
            xref = DEFAULT_MUSIC
            if cc["music_from"] or game_dir:
                report.append("WARNING: {} - no music found for '{}'; it "
                              "plays the music of {}".format(
                                  cc["name"], cc["music_from"] or "(none)",
                                  xref))
        civ_elements.append(civilization_element_xml(cc["slug"], xref))
        if cc["culture"]:
            cultures.setdefault(cc["culture"], []).append(cc["slug"])
        if cc["unit_culture"]:
            unit_cultures.setdefault(cc["unit_culture"], []).append(
                cc["slug"])
    # districts first: buildings may be built in them
    uniques = sorted((u for cc in civs for u in cc["uniques"]),
                     key=lambda u: u["kind"] != "district")
    landmark_of = {}     # project district -> the landmark that draws it
    for u in uniques:
        filename, collection = UNIQUE_ART[u["kind"]]
        if u["kind"] == "unit":     # with its own 3D model, if any
            element, designed = unique_unit_art(
                game_dir, u["slug"], u["base"], u["art"], report,
                u["label"])
            members += [renamed_element_xml(m, element_name(m))
                        for m in designed]
        else:
            source = u["model_from"] or first_building(
                game_dir, landmark_of.get(u["district"], u["district"]),
                own_landmarks)
            element = find_game_element(game_dir, filename, collection,
                                        source) if source else None
            # a new building with nothing to copy: the icons of the
            # building it is drawn like (see unique_icons_sql)
            u["icon_from"] = u["icon_from"] or source
        if element is None:
            report.append("WARNING: {} - no art definition found for {}; "
                          "it may be invisible on the map".format(
                              u["label"], u["model_from"] or "it"))
            if u["kind"] != "building":
                continue
        if u["kind"] == "district":     # its own landmark, if changed
            landmark = district_landmark(game_dir, u["slug"], u["base"],
                                         u["art"], warner(u))
            landmark_of[u["slug"]] = u["base"]
            if landmark is not None:
                set_landmark_xref(element, u["slug"])
                landmark_of[u["slug"]] = u["slug"]
                own_landmarks[u["slug"]] = (landmark, {
                    d for d in (u["base"], u["base_replaces"],
                                u["replaced"]) if d})
        if u["kind"] == "building":
            buildings.append(u)
        if element is not None:
            items[filename].append(renamed_element_xml(element,
                                                       u["slug"]))
    # unique buildings join their district's landmark (and the landmarks
    # of the civilizations' own districts replacing it)
    game_landmarks = {}
    for u in buildings:
        replaced = u["replaced"]
        # the district it is built in (a project district: the landmark
        # that draws it), and - unless its district was changed - every
        # district drawing the building it copies or replaces (a unique
        # Temple also shows in a Lavra)
        names = [landmark_of.get(u["district"], u["district"])] \
            if u["district"] else []
        if "PrereqDistrict" not in u["stats"]:
            names += building_districts(game_dir, u["base"]) or \
                (building_districts(game_dir, replaced) if replaced else [])
        names = [n for i, n in enumerate(names) if n and n not in names[:i]]
        targets = []
        for name in names:
            if name in own_landmarks:
                targets.append((name, own_landmarks[name][0], None))
                continue
            if name not in game_landmarks:
                game_landmarks[name] = (merged_landmark(game_dir, name), [])
            if game_landmarks[name][0] is None:
                continue                # no landmark (e.g. city center)
            targets.append((name, game_landmarks[name][0],
                            game_landmarks[name][1]))
        targets += [(slug, landmark, None) for slug, (landmark, bases)
                    in own_landmarks.items()
                    if bases & set(names) and slug not in names]
        if not targets:
            report.append("WARNING: {} - no district found that shows it; "
                          "it is not drawn".format(u["label"]))
        for name, landmark, extra in targets:
            parts = building_landmark_parts(
                game_dir, u["slug"], u["base"],
                replaced, u["art"], landmark, name,
                warner(u))
            if extra is None:           # the civilization's own landmark
                for key, items_ in zip(("base", "buildings", "sets"), parts):
                    landmark[key] += items_
            else:
                extra.append(parts)
    landmark_elements = [landmark_xml(slug, lm["fields"], lm["base"],
                                      lm["buildings"], lm["sets"])
                         for slug, (lm, _) in sorted(own_landmarks.items())]
    for district, (lm, parts) in sorted(game_landmarks.items()):
        if lm is not None and parts:
            landmark_elements.append(landmark_xml(
                district, lm["fields"], *[sum((p[i] for p in parts), [])
                                          for i in range(3)]))
    files = {CIVILIZATIONS_ARTDEF: build_artdef(
        "Civilizations", [("Civilization", civ_elements)])}
    if cultures or unit_cultures:
        files[CULTURES_ARTDEF] = build_artdef("Cultures", [
            (collection, [culture_element_xml(name, members)
                          for name, members in sorted(groups.items())])
            for collection, groups in (("Culture", cultures),
                                       ("UnitCulture", unit_cultures))
            if groups])
    for filename, elements in items.items():
        if elements:
            template = filename[:-len(".artdef")]
            collections = [(UNIQUE_ART_COLLECTIONS[filename], elements)]
            if filename == UNITS_ARTDEF and members:
                collections.append(("UnitMemberTypes", members))
            files[filename] = build_artdef(template, collections)
    if landmark_elements:
        files[LANDMARKS_ARTDEF] = build_artdef("Landmarks", [(
            "Districts", ["\t\t\t" + ET.tostring(e, encoding="unicode")
                          for e in landmark_elements])])
    artdef_dir = os.path.join(mod_dir, "ArtDefs")
    os.makedirs(artdef_dir, exist_ok=True)
    for filename, content in sorted(files.items()):
        with open(os.path.join(artdef_dir, filename), "w", encoding="utf-8",
                  newline="\n") as fh:
            fh.write(content)
        report.append("wrote ArtDefs/" + filename)
    return sorted(files)


def build_art(ctxs, folder, mod_dir, report, cooker,
              progress=lambda text: None, icon_jobs=(), moment_owners=()):
    """Convert every custom image and cook them into .blp packages
    with cooker (None: not available). icon_jobs: (context, image path,
    icon sizes) of other icons (new civilizations and uniques; context
    needs icon_name, icon_atlas, name and icon_custom). moment_owners:
    other contexts (civilizations) with historic moment pictures
    ("moments"; a picture that cannot be made is dropped). Returns
    (icon_files [(context, [(size, texture)])], cooked mod-relative
    paths, UI package name or None, fallback package name or None). Art
    that cannot be produced falls back to the original leader's art,
    other icons to the game's icons (icon_custom is cleared). No Tk
    calls: runs in a worker thread."""
    ui_package, fallback_package = folder + "_UI", folder + "_Fallbacks"

    def inherit_art(c):
        c["leader_icon"] = c["icon_inherit"]
        c["load_fg"] = c["load_bg"] = c["diplo_bg"] = None
        c["mood_images"] = []
        c["moments"] = []           # no rows pointing at missing art

    def give_up(reason):
        if reason:
            report.append("WARNING: {} - using inherited art".format(
                reason))
        for c in ctxs:
            inherit_art(c)
        for c, _, _ in icon_jobs:
            c["icon_custom"] = False
        for c in moment_owners:
            c["moments"] = []
        for sub in ("Platforms", "ArtDefs"):
            shutil.rmtree(os.path.join(mod_dir, sub), ignore_errors=True)
        return [], [], None, None

    wanted = [c for c in ctxs if needs_art(c)]
    for c in ctxs:
        if not c["icon_custom"]:
            report.append("{} uses the icon of {}".format(
                c["name"], c["orig"] or "the default leader"))
        if not c["load_fg"]:
            report.append("{} has no loading portrait, so no diplomacy "
                          "image".format(c["name"]))
    if not wanted and not icon_jobs and not moment_owners:
        return give_up(None)
    if not cooker:
        return give_up("SDK asset cooker not found")

    pantry = tempfile.mkdtemp(prefix="altleader_art_")

    def convert(name, src, kind="ui", size=None):
        if not add_texture(pantry, name, src, kind=kind, size=size):
            raise RuntimeError("Pillow is not installed (pip install Pillow)")
        report.append("converted " + name)

    def convert_moment(owner, m):
        """Convert one moment picture (masked / faded / sepia as asked)."""
        moment_src = m["path"]
        mask = asset_path(MOMENT_MASK) if m["mask"] else None
        if m["mask"] and not mask:
            report.append(
                "WARNING: {} - assets/{} not found; the {} moment picture "
                "is not masked".format(owner["name"], MOMENT_MASK,
                                       m["item"]))
        if mask or m["half"] or m["sepia"]:
            moment_src = os.path.join(pantry, m["texture"] + "_edited.png")
            apply_image_mask(
                m["path"], mask, size=MOMENT_ILLUSTRATION_SIZE,
                opacity=MOMENT_HALF_OPACITY if m["half"] else 1.0,
                sepia=m["sepia"]).save(moment_src)
            report.append("edited " + m["texture"])
        convert(m["texture"], moment_src, size=MOMENT_ILLUSTRATION_SIZE)

    def convert_moods(c, textures):
        """Convert a leader's diplomacy portraits by mood (fitted like the
        portrait) into textures: {slot: texture}, NEUTRAL already there. A
        picture that cannot be made is dropped; its slot shows the one it
        falls back to."""
        done, failed = set(textures.values()), set()
        for slot, path, texture in c["mood_images"]:
            if texture in failed:
                continue
            if texture not in done:
                try:
                    src = os.path.join(pantry, texture + "_fitted.png")
                    fitted_portrait(path).save(src)
                    convert(texture, src, kind="fallback")
                except Exception as exc:  # unreadable image, disk error...
                    report.append(
                        "WARNING: {} - could not convert the {} diplomacy "
                        "portrait ({}); the {} one is used".format(
                            c["name"], mood_label(slot).lower(), exc,
                            mood_label(resolve_slot(fallback_slot(slot),
                                                    textures)).lower()))
                    failed.add(texture)
                    continue
                done.add(texture)
            textures[slot] = texture

    try:
        ui_textures, fallbacks, icon_leader_files = [], [], []
        for i, c in enumerate(wanted, 1):
            progress("Converting images for {} ({} of {})...".format(
                c["name"], i, len(wanted)))
            names, icons, fallback = [], [], None

            try:
                if c["icon_custom"]:
                    icon_src = c["icon_path"]
                    if c["icon_mode"] == "portrait":
                        # render the bordered circle once at high
                        # resolution, then scale it to every size
                        icon_src = os.path.join(
                            pantry, c["icon_name"] + "_source.png")
                        make_circle_icon(
                            fitted_portrait(c["load_fg_path"]),
                            c["icon_crop"],
                            c["icon_border_color"],
                            c["icon_border_width"]).save(icon_src)
                        report.append("cut {} out of the loading "
                                      "portrait".format(c["icon_name"]))
                    for size in ICON_SIZES:
                        tex = "{}_{}".format(c["icon_name"], size)
                        convert(tex, icon_src, size=size)
                        icons.append((size, tex))
                        names.append(tex)
                if c["load_fg"]:
                    fg_src = os.path.join(
                        pantry, c["load_fg_name"] + "_fitted.png")
                    fitted_portrait(c["load_fg_path"]).save(fg_src)
                    report.append("fitted {} to {} x {}".format(
                        c["load_fg_name"], *PORTRAIT_SIZE))
                    convert(c["load_fg_name"], fg_src)
                    names.append(c["load_fg_name"])
                    # the diplomacy screen's 2D fallback uses the same
                    # picture, cooked as a LeaderFallback texture
                    convert(c["fallback_name"], fg_src, kind="fallback")
                    fallback = (c["slug"], {"NEUTRAL": c["fallback_name"]})
                    convert_moods(c, fallback[1])
                if c["load_bg"]:
                    bg_src = c["load_bg_path"]
                    if c["load_bg_hue"]:
                        bg_src = os.path.join(
                            pantry, c["load_bg_name"] + "_hue.png")
                        from PIL import Image
                        with Image.open(c["load_bg_path"]) as img:
                            shift_hue(img, c["load_bg_hue"]).save(bg_src)
                        report.append("turned the hue of {} by {} "
                                      "degrees".format(c["load_bg_name"],
                                                       c["load_bg_hue"]))
                    convert(c["load_bg_name"], bg_src)
                    names.append(c["load_bg_name"])
                if c["diplo_bg"]:
                    diplo_src = c["diplo_bg_path"]
                    mask = asset_path(DIPLO_BG_MASK)
                    if c["diplo_bg_mask"] and not mask:
                        report.append(
                            "WARNING: {} - assets/{} not found; the "
                            "diplomacy background is not masked".format(
                                c["name"], DIPLO_BG_MASK))
                    elif c["diplo_bg_mask"]:
                        diplo_src = os.path.join(
                            pantry, c["diplo_bg_name"] + "_masked.png")
                        apply_image_mask(c["diplo_bg_path"],
                                         mask).save(diplo_src)
                        report.append("masked " + c["diplo_bg_name"])
                    convert(c["diplo_bg_name"], diplo_src)
                    names.append(c["diplo_bg_name"])
                for m in c["moments"]:
                    convert_moment(c, m)
                    names.append(m["texture"])
            except Exception as exc:  # unreadable image, disk error, ...
                report.append("WARNING: {} - could not convert art ({}); "
                              "using the art of {}".format(
                                  c["name"], exc,
                                  c["orig"] or "the default leader"))
                inherit_art(c)
                continue
            ui_textures.extend(names)
            if fallback:
                fallbacks.append(fallback)
            if icons:
                icon_leader_files.append((c, icons))

        for i, c in enumerate(moment_owners, 1):
            progress("Converting historic moment pictures for {} ({} of "
                     "{})...".format(c["name"], i, len(moment_owners)))
            kept = []
            for m in c["moments"]:
                try:
                    convert_moment(c, m)
                except Exception as exc:  # unreadable image, no Pillow...
                    report.append("WARNING: {} - could not convert the {} "
                                  "moment picture ({}); the game's is "
                                  "used".format(c["name"], m["item"], exc))
                    continue
                kept.append(m)
            c["moments"] = kept
            ui_textures.extend(m["texture"] for m in kept)

        for i, (c, src, sizes) in enumerate(icon_jobs, 1):
            progress("Converting icons ({} of {})...".format(
                i, len(icon_jobs)))
            icons = []
            try:
                for size in sizes:
                    tex = "{}_{}".format(c["icon_name"], size)
                    cell_src, texture_size = src, size
                    if isinstance(src, list):   # cells side by side
                        cell_src = os.path.join(pantry, tex + "_atlas.png")
                        atlas_image(src, size).save(cell_src)
                        texture_size = (size * len(src), size)
                    if not add_texture(pantry, tex, cell_src,
                                       size=texture_size):
                        raise RuntimeError("Pillow is not installed "
                                           "(pip install Pillow)")
                    report.append("converted " + tex)
                    icons.append((size, tex))
            except Exception as exc:  # unreadable image, disk error, ...
                report.append("WARNING: {} - could not convert its icon "
                              "({}); using the game's".format(c["name"],
                                                               exc))
                c["icon_custom"] = False
                continue
            ui_textures.extend(tex for _, tex in icons)
            icon_leader_files.append((c, icons))

        packages = {}
        if ui_textures:
            packages[ui_package] = ("ui", ui_textures)
        if fallbacks:
            packages[fallback_package] = (
                "fallback", list(dict.fromkeys(
                    tex for _, textures in fallbacks
                    for tex in textures.values())))
        if not packages:
            return give_up(None)
        progress("Cooking art with the SDK asset cooker (this can take "
                 "a minute)...")
        cooked = cook_art(cooker, pantry, packages, fallbacks, mod_dir,
                          report)
        if not cooked:
            return give_up("cooking failed")
        return (icon_leader_files, cooked,
                ui_package if ui_textures else None,
                fallback_package if fallbacks else None)
    finally:
        shutil.rmtree(pantry, ignore_errors=True)
