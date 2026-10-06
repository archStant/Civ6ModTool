"""The 3D look of unique buildings and districts, from the game's meshes.

A district's look is its landmark in Landmarks.artdef (collection
"Districts", keyed by district type; the base game and every DLC add to
it, merged by name):

    BaseVariants      the ground and layout mesh, chosen by which set of
                      buildings the district has (Set_HeroBuildings), the
                      art era, culture and appeal
    BuildingVariants  one mesh per building (Tag_HeroBuilding), by era,
                      culture and appeal
    BuildingSets      named combinations of buildings ("LIBRARY,
                      UNIVERSITY")

A building inside a district is drawn as a BuildingVariant of its
district's landmark, with sets and base variants that include it - as
the game's own unique buildings (Madrasa, Navigation School...) do.

Art specs (all optional; empty = the base item's look):

    building: {"look_from": BUILDING_ type whose meshes it uses ("" = the
               copied building's),
               "meshes": None or [{"era": ART era, "mesh": mesh name}] -
               its own building meshes instead}
    district: {"ground": {variant key: mesh name} - other ground/layout
               meshes (see variant_key),
               "buildings": {BUILDING_ type: mesh name} - other meshes of
               the buildings in it}

A district with ground or building changes gets a landmark of its own (a
copy of its base district's, changed); otherwise it shows its base
district's landmark. Every mesh is one the game already has.
"""

import collections
import copy
import xml.etree.ElementTree as ET

from .artdefs import (_artdef_root, _elements, element_name,
                      game_artdef_files)

LANDMARKS_ARTDEF = "Landmarks.artdef"
SECTIONS = {"BaseVariants": "base", "BuildingVariants": "buildings",
            "BuildingSets": "sets"}
ERAS = ["DEFAULT", "ARTERA_ANCIENT", "ARTERA_CLASSICAL",
        "ARTERA_INDUSTRIAL", "ARTERA_MODERN"]
ERA_LABELS = {"DEFAULT": "any era", "ARTERA_ANCIENT": "Ancient",
              "ARTERA_CLASSICAL": "Classical",
              "ARTERA_INDUSTRIAL": "Industrial", "ARTERA_MODERN": "Modern"}


def new_building_art():
    return {"look_from": "", "meshes": None, "stand_in": ""}


def new_district_art():
    return {"look_from": "", "ground": {}, "buildings": {}}


def is_custom(kind, art):
    art = art or {}
    if kind == "building":
        return bool(art.get("look_from") or art.get("meshes") is not None
                    or art.get("stand_in"))
    return bool(art.get("look_from") or art.get("ground") or
                art.get("buildings"))


# ---------------------------------------------------------------------------
# Reading the game's landmarks
# ---------------------------------------------------------------------------

def _field(element, param):
    for v in element.findall("./m_Fields/m_Values/Element"):
        p = v.find("m_ParamName")
        if p is not None and p.get("text") == param:
            return v
    return None


def _text(element, param):
    v = _field(element, param)
    if v is None:
        return ""
    for tag in ("m_ElementName", "m_Value", "m_EntryName"):
        if v.find(tag) is not None:
            return v.find(tag).get("text") or ""
    return ""


def set_buildings(set_element):
    """The building types of a BuildingSets element."""
    v = _field(set_element, "Set")
    return [e.get("text") for e in v.iter("m_ElementName")] \
        if v is not None else []


def variant_key(variant):
    """'set|era|culture|appeal' of a BaseVariants element - how a
    district's ground meshes are told apart."""
    return "|".join(_text(variant, p) for p in
                    ("Set_HeroBuildings", "Tag_Era", "Tag_Culture",
                     "Tag_Appeal"))


def variant_label(key, sets=None):
    """A readable ground variant: 'Library + University, Industrial'."""
    set_name, era, culture, appeal = (key.split("|") + ["", "", "", ""])[:4]
    buildings = (sets or {}).get(set_name)
    what = " + ".join(b.replace("BUILDING_", "").replace("_", " ").title()
                      for b in buildings) if buildings else \
        ("no buildings" if set_name in ("EMPTY", "") else set_name.title())
    parts = [what, ERA_LABELS.get(era, era)]
    if culture and culture != "DEFAULT":
        parts.append(culture)
    if appeal and appeal != "ANY":
        parts.append(appeal.lower())
    return ", ".join(parts)


def merged_landmark(game_dir, district):
    """{"fields": m_Fields element (base game's), "base" / "buildings" /
    "sets": [elements]} of a district's landmark, merged over the game's
    files (copies), or None."""
    out = {"fields": None, "base": [], "buildings": [], "sets": []}
    found = False
    for path in game_artdef_files(game_dir, LANDMARKS_ARTDEF):
        root = _artdef_root(path)
        if root is None:
            continue
        for element in _elements(root, "Districts"):
            if element_name(element) != district:
                continue
            found = True
            if out["fields"] is None:
                out["fields"] = copy.deepcopy(element.find("m_Fields"))
            for coll in element.findall("./m_ChildCollections/Element"):
                key = SECTIONS.get(coll.find("m_CollectionName").get("text"))
                if key:
                    out[key] += [copy.deepcopy(e)
                                 for e in coll.findall("Element")]
    return out if found else None


def landmark_sets(landmark):
    """{set name: [building types]} of a merged landmark."""
    return {element_name(s): set_buildings(s) for s in landmark["sets"]}


_catalogue = {}


def catalogue(game_dir):
    """The game's meshes, cached: {"building": {mesh: (asset element,
    [buildings using it])}, "ground": {mesh: (asset element, [districts
    using it])}}."""
    if game_dir in _catalogue:
        return _catalogue[game_dir]
    out = {"building": collections.OrderedDict(),
           "ground": collections.OrderedDict()}
    for path in game_artdef_files(game_dir, LANDMARKS_ARTDEF):
        root = _artdef_root(path)
        if root is None:
            continue
        for district in _elements(root, "Districts"):
            for coll in district.findall("./m_ChildCollections/Element"):
                kind = {"BaseVariants": "ground",
                        "BuildingVariants": "building"}.get(
                    coll.find("m_CollectionName").get("text"))
                if not kind:
                    continue
                for variant in coll.findall("Element"):
                    asset = _field(variant, "Asset")
                    if asset is None or asset.find("m_EntryName") is None:
                        continue
                    mesh = asset.find("m_EntryName").get("text")
                    user = _text(variant, "Tag_HeroBuilding") \
                        if kind == "building" else element_name(district)
                    entry = out[kind].setdefault(
                        mesh, (copy.deepcopy(asset), []))
                    if user and user not in entry[1]:
                        entry[1].append(user)
    _catalogue[game_dir] = out
    return out


def mesh_choices(game_dir, kind):
    """[(mesh, label)] of a catalogue kind, sorted, for dropdowns."""
    entries = catalogue(game_dir)[kind]
    return sorted(((mesh, "{} ({})".format(mesh, ", ".join(
        u.replace("BUILDING_", "").replace("DISTRICT_", "").title()
        for u in users[:3]) + (", ..." if len(users) > 3 else "")))
        for mesh, (_, users) in entries.items()), key=lambda c: c[0].lower())


def building_districts(game_dir, building):
    """The districts whose landmarks draw a building (from the game's
    landmarks): [district type]."""
    out = []
    for path in game_artdef_files(game_dir, LANDMARKS_ARTDEF):
        root = _artdef_root(path)
        if root is None:
            continue
        for district in _elements(root, "Districts"):
            for coll in district.findall("./m_ChildCollections/Element"):
                if coll.find("m_CollectionName").get("text") != \
                        "BuildingVariants":
                    continue
                for variant in coll.findall("Element"):
                    if (_text(variant, "Tag_HeroBuilding") == building and
                            element_name(district) not in out):
                        out.append(element_name(district))
    return out


# ---------------------------------------------------------------------------
# Building XML
# ---------------------------------------------------------------------------

def _set_reference(element, param, name):
    v = _field(element, param)
    v.find("m_ElementName").set("text", name)


def _set_asset(variant, game_dir, kind, mesh):
    """Point a variant at another mesh (a copy of the game's reference, so
    its package is right). Returns False if the mesh is unknown."""
    entry = catalogue(game_dir)[kind].get(mesh)
    if entry is None:
        return False
    values = variant.find("./m_Fields/m_Values")
    old = _field(variant, "Asset")
    index = list(values).index(old) if old is not None else len(values)
    if old is not None:
        values.remove(old)
    values.insert(index, copy.deepcopy(entry[0]))
    return True


def _rename(element, name):
    element.find("m_Name").set("text", name)
    element.tail = None
    return element


def _building_set(name, buildings, template):
    """A BuildingSets element (built from a game set element)."""
    element = _rename(copy.deepcopy(template), name)
    coll = _field(element, "Set").find("m_Values")
    refs = coll.findall("Element")
    if not refs:                        # an empty set (EMPTY): make one
        ref = ET.SubElement(coll, "Element", {
            "class": "AssetObjects..ArtDefReferenceValue"})
        for tag, text in (("m_ElementName", ""),
                          ("m_RootCollectionName", "Building"),
                          ("m_ArtDefPath", "Buildings.artdef")):
            ET.SubElement(ref, tag, text=text)
        ET.SubElement(ref, "m_CollectionIsLocked").text = "true"
        ET.SubElement(ref, "m_TemplateName", text="Buildings")
        ET.SubElement(ref, "m_ParamName", text="Set")
        refs = [ref]
    for ref in refs[1:]:
        coll.remove(ref)
    for n, building in enumerate(buildings):
        ref = copy.deepcopy(refs[0]) if n else refs[0]
        ref.find("m_ElementName").set("text", building)
        ref.find("m_ParamName").set("text", "Set" if not n else
                                    "Set_{}".format(n))
        if n:
            coll.append(ref)
    return element


def _building_variant(template, building, era, name):
    element = _rename(copy.deepcopy(template), name)
    _set_reference(element, "Tag_HeroBuilding", building)
    _set_reference(element, "Tag_Era", era)
    return element


def landmark_xml(name, fields, base, buildings, sets):
    """A Landmarks.artdef "Districts" element (merged into the game's by
    name) with the given child elements."""
    element = ET.Element("Element")
    element.append(fields if fields is not None else ET.Element("m_Fields"))
    children = ET.SubElement(element, "m_ChildCollections")
    for coll_name, items in (("BaseVariants", base),
                             ("BuildingVariants", buildings),
                             ("BuildingSets", sets)):
        coll = ET.SubElement(children, "Element")
        ET.SubElement(coll, "m_CollectionName", text=coll_name)
        ET.SubElement(coll, "m_ReplaceMergedCollectionElements").text = \
            "false"
        coll.extend(items)
    ET.SubElement(element, "m_Name", text=name)
    ET.SubElement(element, "m_AppendMergedParameterCollections").text = \
        "false"
    return element


# ---------------------------------------------------------------------------
# Unique districts
# ---------------------------------------------------------------------------

def district_landmark(game_dir, slug, base, art, warn):
    """The own landmark (a merged landmark dict, to be named slug - see
    landmark_xml) of a unique district with a look of its own: a copy of
    the landmark of the district it looks like (its base district, or
    art's look_from), changed. None if it has no changes (it shows its
    base district's landmark). A new district (no base) always gets one."""
    if base and not is_custom("district", art):
        return None
    source = art.get("look_from") or base
    landmark = merged_landmark(game_dir, source) if source else None
    if landmark is None:
        warn("no landmark found for {}; it {}".format(
            source or "(no district to look like)",
            "keeps its look" if base else "is not drawn"))
        return None
    for variant in landmark["base"]:
        mesh = art["ground"].get(variant_key(variant))
        if mesh and not _set_asset(variant, game_dir, "ground", mesh):
            warn("the game has no ground mesh '{}'".format(mesh))
    for variant in landmark["buildings"]:
        mesh = art["buildings"].get(_text(variant, "Tag_HeroBuilding"))
        if mesh and not _set_asset(variant, game_dir, "building", mesh):
            warn("the game has no building mesh '{}'".format(mesh))
    for i, element in enumerate(landmark["base"] + landmark["buildings"]):
        _rename(element, "{}_{}".format(slug, i))     # unique in the merge
    return landmark


def set_landmark_xref(district_element, landmark):
    """Point a Districts.artdef element at another landmark."""
    for coll in district_element.findall("./m_ChildCollections/Element"):
        if coll.find("m_CollectionName").get("text") == "Landmark":
            for e in coll.iter("m_ElementName"):
                e.set("text", landmark)
            return True
    return False


# ---------------------------------------------------------------------------
# Unique buildings
# ---------------------------------------------------------------------------

def building_variants(game_dir, slug, look, art, template, warn):
    """The BuildingVariants of a unique building: its own meshes, or
    copies of the look building's variants."""
    out = []
    if art.get("meshes") is not None:
        for n, m in enumerate(art["meshes"]):
            variant = _building_variant(template, slug, m["era"],
                                        "{}_{}".format(slug, n))
            if not _set_asset(variant, game_dir, "building", m["mesh"]):
                warn("the game has no building mesh '{}'".format(m["mesh"]))
                continue
            out.append(variant)
        return out
    districts = building_districts(game_dir, look)
    landmark = merged_landmark(game_dir, districts[0]) if districts else None
    for n, variant in enumerate(v for v in (landmark or {}).get(
            "buildings", []) if _text(v, "Tag_HeroBuilding") == look):
        variant = _rename(copy.deepcopy(variant), "{}_{}".format(slug, n))
        _set_reference(variant, "Tag_HeroBuilding", slug)
        out.append(variant)
    if not out:
        warn("no 3D model found for {}; it is not drawn".format(look))
    return out


def landmark_buildings(landmark):
    """The building types a merged landmark draws, in order."""
    out = []
    for v in landmark["buildings"]:
        b = _text(v, "Tag_HeroBuilding")
        if b and b not in out:
            out.append(b)
    return out


def building_landmark_parts(game_dir, slug, base, replaced, art, landmark,
                            name, warn):
    """(base variants, building variants, sets) adding a unique building
    to one district landmark (a merged landmark dict, named name).

    Its meshes: art's own, else those of the building it looks like
    (look_from, else its base building, else the building whose place it
    takes - stand_in, by default the landmark's first building).
    Its sets: if the landmark draws the building it stands for (its base,
    else the one it replaces), a copy of each set with that building,
    with the unique building instead; otherwise (an extra building) a
    copy of every set with the unique building added. Each new set gets
    copies of the ground variants of the set it was made from."""
    sets = landmark_sets(landmark)
    templates = [v for v in landmark["buildings"]]
    if not templates:
        warn("{} draws no buildings; the building is not drawn".format(name))
        return [], [], []
    drawn = landmark_buildings(landmark)
    substitute = next((b for b in (base, replaced)
                       if b and any(b in s for s in sets.values())), None)
    stand_in = art.get("stand_in") or substitute or drawn[0]
    look = art.get("look_from") or base or stand_in
    variants = building_variants(game_dir, slug, look, art, templates[0],
                                 warn)
    for v in variants:                  # unique in the merged landmark
        _rename(v, "{}_{}".format(name, element_name(v)))
    new_sets, renamed = [], {}
    set_elements = {element_name(s): s for s in landmark["sets"]}
    for set_name, buildings in sets.items():
        if substitute:                  # in the place of a building
            if substitute not in buildings:
                continue
            members = [slug if b == substitute else b for b in buildings]
        else:                           # an extra building
            members = buildings + [slug]
        new_name = "{} [{}]".format(set_name, slug)
        renamed[set_name] = new_name
        new_sets.append(_building_set(new_name, members,
                                      set_elements[set_name]))
    ground = []
    for n, variant in enumerate(v for v in landmark["base"]
                                if _text(v, "Set_HeroBuildings") in renamed):
        # a copy: the landmark keeps its own grounds (e.g. EMPTY, for the
        # district without buildings)
        variant = _rename(copy.deepcopy(variant),
                          "{}_{}_BASE_{}".format(name, slug, n))
        _set_reference(variant, "Set_HeroBuildings",
                       renamed[_text(variant, "Set_HeroBuildings")])
        ground.append(variant)
    if not new_sets:
        warn("{} has no building sets; the building may not be drawn"
             .format(name))
    return ground, variants, new_sets


def normalize_building_art(art, label):
    art = dict(new_building_art(), **(art or {}))
    out = {key: (art.get(key) or "").strip().upper()
           for key in ("look_from", "stand_in")}
    out["meshes"] = None
    for key in ("look_from", "stand_in"):
        if out[key] and not out[key].startswith("BUILDING_"):
            raise ValueError("{}: '{}' is not a building.".format(
                label, out[key]))
    if art.get("meshes") is not None:
        meshes = [{"era": (m.get("era") or "DEFAULT").strip(),
                   "mesh": (m.get("mesh") or "").strip()}
                  for m in art["meshes"] if (m.get("mesh") or "").strip()]
        if not meshes:
            raise ValueError("{}: the building's 3D model has no mesh - add "
                             "at least one.".format(label))
        out["meshes"] = meshes
    return out


def normalize_district_art(art, label):
    art = dict(new_district_art(), **(art or {}))
    out = {key: {k.strip(): v.strip() for k, v in (art.get(key) or {})
                 .items() if k.strip() and (v or "").strip()}
           for key in ("ground", "buildings")}
    out["look_from"] = (art.get("look_from") or "").strip().upper()
    if out["look_from"] and not out["look_from"].startswith("DISTRICT_"):
        raise ValueError("{}: '{}' is not a district.".format(
            label, out["look_from"]))
    return out
