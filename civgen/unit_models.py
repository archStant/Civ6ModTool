"""Designing unit models from the game's own model parts.

The game builds every unit model ("member type" in Units.artdef) from
parts. A member type has animations (Movement, Combat), and per unit
culture one or more variations; each variation is a list of attachments:

    slot ("Armor", "Weapon", "Shield", "Hats", "Body", "Head"...),
    point (where on the skeleton: Root, WeaponPrimary, WeaponSecondary,
           Hat...),
    tint ("" or e.g. USE_CIV_COLOR: painted in the player's colors),
    bins (the meshes, "Category/Group" in Unit_Bins.artdef, e.g.
          "Armor/Knight", "Swords/RomanLegion"; with several the game
          picks one per figure, for variety)

A mounted model is a mount variation ("Horse": body, horse armour, tail
and a "Rider" slot whose bin is "V:Rider") plus an attached ("rider")
variation with the rider's parts.

A design is a plain dict:

    {"id": "AMAZON",               # names the new member type
     "template": "Swordsman",      # model to start from: its skeleton,
                                   # animations and default parts
     "mount": "" or "Knight",      # put the (foot) model on the horse of
                                   # this mounted model
     "parts": {section: [part]}}   # the designed parts (see sections)

with part = {"slot", "point", "tint", "bins": [bin]}. Sections are "body"
for a foot model, "rider" and "horse" for a mounted one. The parts are
stored in full; generation applies them as changes to the starting
model's own parts, so per-culture differences (hair, beards...) stay
where a part was not changed.
"""

import collections
import copy
import re
import xml.etree.ElementTree as ET

from .artdefs import (UNITS_ARTDEF, _artdef_root, _elements, element_name,
                      find_game_element, game_artdef_files)

BINS_ARTDEF = "Unit_Bins.artdef"
CIV_COLOR = "USE_CIV_COLOR"
SECTION_LABELS = {"body": "Figure", "rider": "Rider",
                  "horse": "Mount (horse, chariot...)"}
ID_RE = re.compile(r"^[A-Z0-9_]+$")


def clean_id(text):
    return re.sub(r"[^0-9A-Za-z]+", "_", text or "").strip("_").upper()


# ---------------------------------------------------------------------------
# The game's catalogue of parts
# ---------------------------------------------------------------------------

_catalogue = {}


def catalogue(game_dir):
    """{"bins": {category: [group]}, "points": [...], "tints": [...],
    "models": [member type], "mounted": [member type]} of the game's unit
    art (base game and DLC), cached."""
    if game_dir in _catalogue:
        return _catalogue[game_dir]
    bins = collections.OrderedDict()
    for path in game_artdef_files(game_dir, BINS_ARTDEF):
        root = _artdef_root(path)
        if root is None:
            continue
        for cat in _elements(root, "UnitAttachmentBins"):
            groups = bins.setdefault(element_name(cat), [])
            for coll in cat.findall("./m_ChildCollections/Element"):
                for group in coll.findall("Element"):
                    if element_name(group) not in groups:
                        groups.append(element_name(group))
    points, tints, models, mounted = (collections.Counter(), set(), [],
                                      set())
    for path in game_artdef_files(game_dir, UNITS_ARTDEF):
        root = _artdef_root(path)
        if root is None:
            continue
        for tint in _elements(root, "UnitTintTypes"):
            tints.add(element_name(tint))
        for member in _elements(root, "UnitMemberTypes"):
            name = element_name(member)
            if name and name not in models:
                models.append(name)
            for _, var in variations(member):
                if is_attachment(var):
                    mounted.add(name)
                for att in attachments(var):
                    point = _field_text(att, "Point")
                    if point:
                        points[point] += 1
    for groups in bins.values():
        groups.sort(key=str.lower)
    out = {"bins": bins,
           "points": [p for p, _ in points.most_common()],
           "tints": [CIV_COLOR] + sorted(t for t in tints if t),
           "models": sorted(models, key=str.lower),
           "mounted": sorted(mounted, key=str.lower)}
    _catalogue[game_dir] = out
    return out


def all_bins(game_dir):
    return {"{}/{}".format(cat, group)
            for cat, groups in catalogue(game_dir)["bins"].items()
            for group in groups}


# ---------------------------------------------------------------------------
# Reading member types
# ---------------------------------------------------------------------------

def _field(element, param):
    for v in element.findall("./m_Fields/m_Values/Element"):
        p = v.find("m_ParamName")
        if p is not None and p.get("text") == param:
            return v
    return None


def _field_text(element, param):
    v = _field(element, param)
    if v is None:
        return ""
    for tag in ("m_Value", "m_ElementName"):
        if v.find(tag) is not None:
            return v.find(tag).get("text") or ""
    for tag in ("m_bValue", "m_fValue", "m_nValue"):
        if v.find(tag) is not None:
            return v.find(tag).text or ""
    return ""


def cultures(member):
    """The culture elements of a member type ("Any", "SouthAmerican"...)."""
    return member.findall("./m_ChildCollections/Element/Element")


def variations(member, culture=None):
    """(culture element, variation element) pairs of a member type."""
    for cult in [culture] if culture is not None else cultures(member):
        for var in cult.findall("./m_ChildCollections/Element/Element"):
            yield cult, var


def is_attachment(variation):
    return _field_text(variation, "IsAttachment") == "true"


def attachments(variation):
    coll = variation.find("./m_ChildCollections/Element")
    return coll.findall("Element") if coll is not None else []


def _attachment_collection(variation):
    coll = variation.find("./m_ChildCollections/Element")
    if coll is None:
        children = variation.find("m_ChildCollections")
        coll = ET.SubElement(children, "Element")
        ET.SubElement(coll, "m_CollectionName", text="Attachments")
        ET.SubElement(coll, "m_ReplaceMergedCollectionElements").text = \
            "false"
    return coll


def part_of(att):
    """A part dict of an attachment element."""
    bins = [element_name(b)
            for b in att.findall("./m_ChildCollections/Element/Element")]
    return {"slot": element_name(att) or "", "point": _field_text(att, "Point"),
            "tint": _field_text(att, "Tint"), "bins": bins}


def section_variations(member, culture=None):
    """{section: [variation elements]} of a member type (or of one of its
    cultures): "rider" + "horse" for a model with attached variations,
    else "body"."""
    vars_ = [v for _, v in variations(member, culture)]
    riders = [v for v in vars_ if is_attachment(v)]
    if riders:
        return {"rider": riders,
                "horse": [v for v in vars_ if not is_attachment(v)]}
    return {"body": vars_}


def _reference_culture(member):
    """The culture whose parts the editor shows: "Any", else the first."""
    found = cultures(member)
    return next((c for c in found if element_name(c) == "Any"),
                found[0] if found else None)


def model_sections(game_dir, template, mount=""):
    """{section: [part]} of a design's starting point: the template's own
    parts, or (with a mount) its parts as the rider of the mount. None
    if a model is not found."""
    member = find_game_element(game_dir, UNITS_ARTDEF, "UnitMemberTypes",
                               template)
    if member is None or not cultures(member):
        return None
    sections = {key: [part_of(a) for a in vars_[0].findall(
        "./m_ChildCollections/Element/Element")] if vars_ else []
        for key, vars_ in section_variations(
            member, _reference_culture(member)).items()}
    if not mount:
        return sections
    horse = find_game_element(game_dir, UNITS_ARTDEF, "UnitMemberTypes",
                              mount)
    if horse is None or not cultures(horse):
        return None
    mount_sections = section_variations(horse, _reference_culture(horse))
    if "horse" not in mount_sections:
        return None
    return {"rider": sections.get("body", []),
            "horse": [part_of(a) for a in attachments(
                mount_sections["horse"][0])]}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def new_design(template="", mount=""):
    return {"id": "", "template": template, "mount": mount, "parts": {}}


def normalize_design(design, label):
    """A validated copy of a design. Raises ValueError."""
    design_id = clean_id(design.get("id"))
    if not design_id:
        raise ValueError("{}: a designed model has no name.".format(label))
    what = "{}: model {}".format(label, design_id)
    template = (design.get("template") or "").strip()
    if not template:
        raise ValueError("{} - pick the model to start from.".format(what))
    out = {"id": design_id, "template": template,
           "mount": (design.get("mount") or "").strip(), "parts": {}}
    for section, parts in (design.get("parts") or {}).items():
        if section not in SECTION_LABELS:
            raise ValueError("{} - unknown part section '{}'.".format(
                what, section))
        clean = []
        for part in parts or []:
            slot = (part.get("slot") or "").strip()
            bins = [b.strip() for b in part.get("bins") or [] if b.strip()]
            if not slot and not bins:
                continue                # empty editor row
            if not slot:
                raise ValueError("{} - a part has no slot name.".format(what))
            if not bins:
                raise ValueError("{} - part {} has no mesh (bin).".format(
                    what, slot))
            clean.append({"slot": slot,
                          "point": (part.get("point") or "").strip(),
                          "tint": (part.get("tint") or "").strip(),
                          "bins": bins})
        out["parts"][section] = clean
    return out


# ---------------------------------------------------------------------------
# Building a designed member type
# ---------------------------------------------------------------------------

def _set_text_field(att, param, value):
    v = _field(att, param)
    if v is not None and v.find("m_Value") is not None:
        v.find("m_Value").set("text", value)
        return
    values = att.find("./m_Fields/m_Values")
    if v is not None:
        values.remove(v)
    e = ET.SubElement(values, "Element",
                      {"class": "AssetObjects..StringValue"})
    ET.SubElement(e, "m_Value", text=value)
    ET.SubElement(e, "m_ParamName", text=param)


def _set_tint(att, tint):
    values = att.find("./m_Fields/m_Values")
    old = _field(att, "Tint")
    if old is not None:
        values.remove(old)
    e = ET.SubElement(values, "Element",
                      {"class": "AssetObjects..ArtDefReferenceValue"})
    for tag, text in (("m_ElementName", tint),
                      ("m_RootCollectionName", "UnitTintTypes" if tint
                       else ""),
                      ("m_ArtDefPath", UNITS_ARTDEF if tint else "")):
        ET.SubElement(e, tag, text=text)
    ET.SubElement(e, "m_CollectionIsLocked").text = \
        "true" if tint else "false"
    ET.SubElement(e, "m_TemplateName", text="Units" if tint else "")
    ET.SubElement(e, "m_ParamName", text="Tint")


def _set_bins(att, bins):
    children = att.find("m_ChildCollections")
    for old in children.findall("Element"):
        children.remove(old)
    coll = ET.SubElement(children, "Element")
    ET.SubElement(coll, "m_CollectionName", text="Bins")
    ET.SubElement(coll, "m_ReplaceMergedCollectionElements").text = "false"
    for b in bins:
        e = ET.SubElement(coll, "Element")
        ET.SubElement(ET.SubElement(e, "m_Fields"), "m_Values")
        ET.SubElement(e, "m_ChildCollections")
        ET.SubElement(e, "m_Name", text=b)
        ET.SubElement(e, "m_AppendMergedParameterCollections").text = \
            "false"


def _new_attachment(part):
    att = ET.Element("Element")
    ET.SubElement(ET.SubElement(att, "m_Fields"), "m_Values")
    ET.SubElement(att, "m_ChildCollections")
    ET.SubElement(att, "m_Name", text=part["slot"])
    ET.SubElement(att, "m_AppendMergedParameterCollections").text = "false"
    _write_part(att, part)
    return att


def _write_part(att, part):
    _set_text_field(att, "Point", part["point"])
    _set_tint(att, part["tint"])
    _set_bins(att, part["bins"])


def _keyed(parts):
    """{(slot, n): part}: the n-th part with that slot name."""
    out, seen = {}, collections.Counter()
    for part in parts:
        out[(part["slot"], seen[part["slot"]])] = part
        seen[part["slot"]] += 1
    return out


def apply_parts(variation, design_parts, reference_parts):
    """Change a variation's attachments by the difference between the
    designed parts and the reference parts (what the editor started
    from): changed parts are rewritten, removed ones dropped, new ones
    added."""
    design, reference = _keyed(design_parts), _keyed(reference_parts)
    coll = _attachment_collection(variation)
    seen = collections.Counter()
    for att in list(coll.findall("Element")):
        key = (element_name(att), seen[element_name(att)])
        seen[element_name(att)] += 1
        if key not in reference:
            continue                    # a culture's own extra part
        if key not in design:
            coll.remove(att)
        elif design[key] != reference[key]:
            _write_part(att, design[key])
    for key, part in design.items():
        if key not in reference:
            coll.append(_new_attachment(part))


def designed_member(game_dir, design, member_name, report=None, label=""):
    """The UnitMemberTypes element of a (normalized) design, named
    member_name, or None if its models are not in the game's art."""
    def warn(text):
        if report is not None:
            report.append("WARNING: {} - {}".format(label, text))

    template = find_game_element(game_dir, UNITS_ARTDEF, "UnitMemberTypes",
                                 design["template"])
    if template is None or not cultures(template):
        warn("model {} not found; designed model {} left out".format(
            design["template"], design["id"]))
        return None
    if design["mount"] and "body" not in section_variations(template):
        warn("model {} is already mounted - it cannot ride {}; designed "
             "model {} left out".format(design["template"], design["mount"],
                                        design["id"]))
        return None
    reference = model_sections(game_dir, design["template"],
                               design["mount"])
    if reference is None:
        warn("mount {} not found; designed model {} left out".format(
            design["mount"], design["id"]))
        return None
    parts = {key: design["parts"].get(key, reference[key])
             for key in reference}
    known = all_bins(game_dir)
    for section in parts.values():
        for part in section:
            for b in part["bins"]:
                if not b.startswith("V:") and b not in known:
                    warn("model {}: the game has no part '{}'; it is used "
                         "anyway (it may come from another mod)".format(
                             design["id"], b))
    if design["mount"]:
        member = find_game_element(game_dir, UNITS_ARTDEF,
                                   "UnitMemberTypes", design["mount"])
        by_culture = {element_name(c): c for c in cultures(template)}
        for cult in cultures(member):
            source = by_culture.get(element_name(cult),
                                    _reference_culture(template))
            figure = section_variations(template, source).get("body") or []
            sections = section_variations(member, cult)
            for var in sections.get("rider", []):
                coll = _attachment_collection(var)
                for old in coll.findall("Element"):
                    coll.remove(old)
                if figure:
                    coll.extend(copy.deepcopy(attachments(figure[0])))
                apply_parts(var, parts["rider"], reference["rider"])
            for var in sections.get("horse", []):
                apply_parts(var, parts["horse"], reference["horse"])
    else:
        member = template
        for cult in cultures(member):
            for key, vars_ in section_variations(member, cult).items():
                for var in vars_:
                    apply_parts(var, parts[key], reference[key])
    member.find("m_Name").set("text", member_name)
    member.tail = None
    return member


def member_type_name(unit_slug, design_id):
    """The member type name of a unit's designed model."""
    return "{}_{}".format(unit_slug, design_id)


def describe(design):
    """One line describing a design (README)."""
    text = "{}: {}".format(design["id"], design["template"])
    if design["mount"]:
        text += " on the mount of " + design["mount"]
    changed = sum(len(p) for p in design["parts"].values())
    return text + (" ({} parts)".format(changed) if changed else "")
