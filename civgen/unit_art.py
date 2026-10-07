"""The 3D model of unique units, built from the game's own unit art.

A unit's look (its Units.artdef element) is a formation (how its members
stand and move), a set of combat animations, a sound and its members:
groups of models ("member types" such as Swordsman, RomanLegion or
ScoutCat - each with variants per unit culture), each with a count and a
scale. A unique unit normally looks like the unit it copies; its "art"
spec can instead take the look of any other unit and change each part:

    {"look_from": UNIT_ type whose art to start from ("" = the copied
                  unit's),
     "members": [{"type": member type, "count": int, "scale": float}]
                or None (= the look unit's members),
     "formation": UnitFormationTypes name ("" = the look unit's),
     "combat": UnitCombat name ("" = the look unit's),
     "sound_from": UNIT_ type whose sound it makes ("" = the look unit's),
     "models": [design] - models designed from the game's model parts
               (armour, weapons, mounts..., see unit_models.py); members
               use one as type "@" + its id}

New 3D meshes (Blender -> Asset Editor) are outside the generator's
scope; every part here is one the game already has.
"""

import xml.etree.ElementTree as ET

from .artdefs import UNITS_ARTDEF, find_game_element, game_element_names
from .unit_models import (designed_member, member_type_name,
                          normalize_design)
from .unit_models import describe as describe_design

COLLECTIONS = {"members": "UnitMemberTypes", "formation": "UnitFormationTypes",
               "combat": "UnitCombat"}
MAX_COUNT = 12                          # the game's largest formations
SCALE_RANGE = (0.1, 5.0)


def new_unit_art():
    return {"look_from": "", "members": None, "formation": "", "combat": "",
            "sound_from": "", "models": []}


def art_lists(game_dir):
    """{"members" / "formation" / "combat": [names]} of the game's unit
    art, for the editor's dropdowns."""
    return {key: sorted(game_element_names(game_dir, UNITS_ARTDEF,
                                           collection), key=str.lower)
            for key, collection in COLLECTIONS.items()}


def is_custom(art):
    """Whether a unit art spec changes anything."""
    art = art or {}
    return bool(art.get("look_from") or art.get("members") is not None or
                art.get("formation") or art.get("combat") or
                art.get("sound_from") or art.get("models"))


def normalize_art(art, label):
    """A validated copy of a unit art spec. Raises ValueError."""
    art = dict(new_unit_art(), **(art or {}))
    out = {key: (art.get(key) or "").strip()
           for key in ("formation", "combat")}
    for key in ("look_from", "sound_from"):
        out[key] = (art.get(key) or "").strip().upper()
        if out[key] and not out[key].startswith("UNIT_"):
            raise ValueError("{}: '{}' is not a unit (UNIT_ type).".format(
                label, out[key]))
    out["models"] = []
    for design in art.get("models") or []:
        design = normalize_design(design, label)
        if any(d["id"] == design["id"] for d in out["models"]):
            raise ValueError("{}: two designed models are called {}.".format(
                label, design["id"]))
        out["models"].append(design)
    designed = {"@" + d["id"] for d in out["models"]}
    out["members"] = None
    if art.get("members") is not None:
        members = []
        for m in art["members"]:
            member_type = (m.get("type") or "").strip()
            if not member_type:
                continue                # empty editor row
            try:
                count = int(m.get("count", 1))
                scale = float(m.get("scale", 1.0))
            except (TypeError, ValueError):
                raise ValueError("{}: model {} needs a whole number count and "
                                 "a number scale.".format(label, member_type))
            if not 1 <= count <= MAX_COUNT:
                raise ValueError("{}: model {} - count must be 1-{}.".format(
                    label, member_type, MAX_COUNT))
            if not SCALE_RANGE[0] <= scale <= SCALE_RANGE[1]:
                raise ValueError("{}: model {} - scale must be {}-{}.".format(
                    label, member_type, *SCALE_RANGE))
            if member_type.startswith("@") and                     member_type.upper() not in designed:
                raise ValueError("{}: there is no designed model {}.".format(
                    label, member_type[1:]))
            members.append({"type": member_type.upper()
                            if member_type.startswith("@") else member_type,
                            "count": count, "scale": scale})
        if not members:
            raise ValueError("{}: the unit's 3D model has no members - add "
                             "at least one model.".format(label))
        out["members"] = members
    return out


# ---------------------------------------------------------------------------
# Reading the game's unit art
# ---------------------------------------------------------------------------

def _child_collection(element, name):
    for c in element.findall("./m_ChildCollections/Element"):
        coll = c.find("m_CollectionName")
        if coll is not None and coll.get("text") == name:
            return c
    return None


def _field(element, param):
    """A unit (or member) element's field value element by its name."""
    for v in element.findall("./m_Fields/m_Values/Element"):
        p = v.find("m_ParamName")
        if p is not None and p.get("text") == param:
            return v
    return None


def _value(field):
    if field is None:
        return None
    for tag in ("m_ElementName", "m_Value"):
        if field.find(tag) is not None:
            return field.find(tag).get("text")
    for tag in ("m_fValue", "m_nValue", "m_bValue"):
        if field.find(tag) is not None:
            return field.find(tag).text
    return None


def unit_look(game_dir, unit):
    """{"members", "formation", "combat", "sound"} of a game unit's art,
    or None if it has none."""
    element = find_game_element(game_dir, UNITS_ARTDEF, "Units", unit)
    if element is None:
        return None
    members = []
    coll = _child_collection(element, "Members")
    for m in coll.findall("Element") if coll is not None else []:
        try:
            members.append({"type": _value(_field(m, "Type")) or "",
                            "count": int(_value(_field(m, "Count")) or 1),
                            "scale": float(_value(_field(m, "Scale")) or 1)})
        except ValueError:
            continue
    return {"members": members,
            "formation": _value(_field(element, "Formation")) or "",
            "combat": _value(_field(element, "UnitCombat")) or "",
            "sound": unit_sound(element)}


def unit_sound(element):
    """The audio XrefName of a unit art element ("" if none)."""
    coll = _child_collection(element, "Audio")
    for a in coll.findall("Element") if coll is not None else []:
        xref = _value(_field(a, "XrefName"))
        if xref:
            return xref
    return ""


# ---------------------------------------------------------------------------
# Building a unique unit's art
# ---------------------------------------------------------------------------

def _reference(param, name, collection):
    """An ArtDefReferenceValue to an element of Units.artdef."""
    e = ET.Element("Element", {"class": "AssetObjects..ArtDefReferenceValue"})
    for tag, text in (("m_ElementName", name),
                      ("m_RootCollectionName", collection),
                      ("m_ArtDefPath", UNITS_ARTDEF)):
        ET.SubElement(e, tag, text=text)
    ET.SubElement(e, "m_CollectionIsLocked").text = "true"
    ET.SubElement(e, "m_TemplateName", text="Units")
    ET.SubElement(e, "m_ParamName", text=param)
    return e


def _member(n, member):
    e = ET.Element("Element")
    values = ET.SubElement(ET.SubElement(e, "m_Fields"), "m_Values")
    scale = ET.SubElement(values, "Element",
                          {"class": "AssetObjects..FloatValue"})
    ET.SubElement(scale, "m_fValue").text = "{:.6f}".format(member["scale"])
    ET.SubElement(scale, "m_ParamName", text="Scale")
    count = ET.SubElement(values, "Element",
                          {"class": "AssetObjects..IntValue"})
    ET.SubElement(count, "m_nValue").text = str(member["count"])
    ET.SubElement(count, "m_ParamName", text="Count")
    values.append(_reference("Type", member["type"], "UnitMemberTypes"))
    ET.SubElement(e, "m_ChildCollections")
    ET.SubElement(e, "m_Name", text="Members{}".format(n))
    ET.SubElement(e, "m_AppendMergedParameterCollections").text = "false"
    return e


def _set_reference(element, param, name, collection):
    field = _field(element, param)
    if field is not None and field.find("m_ElementName") is not None:
        field.find("m_ElementName").set("text", name)
        field.find("m_TemplateName").set("text", "Units")
        return
    values = element.find("./m_Fields/m_Values")
    if field is not None:
        values.remove(field)
    values.append(_reference(param, name, collection))


def _replace_collection(element, name, children):
    coll = _child_collection(element, name)
    if coll is None:
        coll = ET.SubElement(element.find("m_ChildCollections"), "Element")
        ET.SubElement(coll, "m_CollectionName", text=name)
        ET.SubElement(coll, "m_ReplaceMergedCollectionElements").text = \
            "false"
    for old in coll.findall("Element"):
        coll.remove(old)
    coll.extend(children)


def _audio(xref):
    e = ET.Element("Element")
    values = ET.SubElement(ET.SubElement(e, "m_Fields"), "m_Values")
    value = ET.SubElement(values, "Element",
                          {"class": "AssetObjects..StringValue"})
    ET.SubElement(value, "m_Value", text=xref)
    ET.SubElement(value, "m_ParamName", text="XrefName")
    ET.SubElement(e, "m_ChildCollections")
    ET.SubElement(e, "m_Name", text=xref.upper())
    ET.SubElement(e, "m_AppendMergedParameterCollections").text = "false"
    return e


def unique_unit_art(game_dir, unit_slug, base, art, report=None, label=""):
    """(the unit's art definition element - renamed to unit_slug - or None
    if the look unit has no art, [UnitMemberTypes elements of its designed
    models]) of a unique unit copying base with the (normalized) art
    spec. report: list for warnings about parts that are not found."""
    element = unique_unit_element(game_dir, base, art, report, label,
                                  unit_slug)
    if element is None:
        return None, []
    element.find("m_Name").set("text", unit_slug)
    members = []
    for design in art.get("models") or []:
        member = designed_member(game_dir, design,
                                 member_type_name(unit_slug, design["id"]),
                                 report, label)
        if member is not None:
            members.append(member)
    return element, members


def unique_unit_element(game_dir, base, art, report=None, label="",
                        unit_slug="UNIT"):
    """The art definition element of a unique unit copying base with the
    (normalized) art spec, not yet renamed, or None if the look unit has
    no art. report: list for warnings about parts that are not found.
    unit_slug names its designed models' member types."""
    warn = (lambda text: report.append("WARNING: {} - {}".format(label, text))
            ) if report is not None else (lambda text: None)
    look = art.get("look_from") or base
    element = find_game_element(game_dir, UNITS_ARTDEF, "Units", look)
    if element is None and look != base:
        warn("no art found for {}; it looks like {}".format(look, base))
        element = find_game_element(game_dir, UNITS_ARTDEF, "Units", base)
    if element is None:
        return None
    known = None

    def exists(key, name):
        nonlocal known
        if known is None:
            known = {k: set(v) for k, v in art_lists(game_dir).items()}
        if name not in known[key]:
            warn("the game has no {} '{}'; it is used anyway (it may come "
                 "from another mod)".format(COLLECTIONS[key], name))

    if art.get("members") is not None:
        members = []
        for m in art["members"]:
            if m["type"].startswith("@"):       # a designed model
                m = dict(m, type=member_type_name(unit_slug, m["type"][1:]))
            else:
                exists("members", m["type"])
            members.append(m)
        _replace_collection(element, "Members",
                            [_member(n, m) for n, m in
                             enumerate(members, 1)])
    for key, param in (("formation", "Formation"), ("combat", "UnitCombat")):
        if art.get(key):
            exists(key, art[key])
            _set_reference(element, param, art[key], COLLECTIONS[key])
    if art.get("sound_from"):
        source = find_game_element(game_dir, UNITS_ARTDEF, "Units",
                                   art["sound_from"])
        xref = unit_sound(source) if source is not None else ""
        if xref:
            _replace_collection(element, "Audio", [_audio(xref)])
        else:
            warn("no sound found for {}".format(art["sound_from"]))
    return element


def describe(art):
    """One line describing a unit art spec (README)."""
    parts = []
    if art.get("look_from"):
        parts.append("looks like " + art["look_from"])
    if art.get("members") is not None:
        parts.append("models " + ", ".join(
            "{} x{} ({:g})".format(m["type"], m["count"], m["scale"])
            for m in art["members"]))
    for key in ("formation", "combat"):
        if art.get(key):
            parts.append("{} {}".format(key, art[key]))
    if art.get("sound_from"):
        parts.append("sounds like " + art["sound_from"])
    parts += ["designed model " + describe_design(d)
              for d in art.get("models") or []]
    return "; ".join(parts)
