"""Art definition (.artdef) and dependency (.dep) files."""

import copy
import os
import xml.etree.ElementTree as ET

from .util import xml_escape


FALLBACK_ARTDEF = "FallbackLeaders.artdef"


def build_fallback_artdef(package, fallbacks):
    """Cooked FallbackLeaders.artdef: leader type -> its fallback texture.
    fallbacks: (leader type, texture name) pairs. The game merges this
    with the other FallbackLeaders.artdef files by element name."""
    leaders = "\n".join("""			<Element>
				<m_Fields>
					<m_Values/>
				</m_Fields>
				<m_ChildCollections>
					<Element>
						<m_CollectionName text="Animations"/>
						<m_ReplaceMergedCollectionElements>false</m_ReplaceMergedCollectionElements>
						<Element>
							<m_Fields>
								<m_Values>
									<Element class="AssetObjects..BLPEntryValue">
										<m_EntryName text="{texture}"/>
										<m_XLPClass text="LeaderFallback"/>
										<m_XLPPath text="{package}.xlp"/>
										<m_BLPPackage text="{package}"/>
										<m_LibraryName text="LeaderFallback"/>
										<m_ParamName text="BLP Entry"/>
									</Element>
								</m_Values>
							</m_Fields>
							<m_ChildCollections/>
							<m_Name text="DEFAULT"/>
							<m_AppendMergedParameterCollections>false</m_AppendMergedParameterCollections>
						</Element>
					</Element>
				</m_ChildCollections>
				<m_Name text="{leader}"/>
				<m_AppendMergedParameterCollections>false</m_AppendMergedParameterCollections>
			</Element>""".format(leader=leader, texture=texture, package=package)
        for leader, texture in fallbacks)
    return """<?xml version="1.0" encoding="UTF-8" ?>
<AssetObjects..ArtDefSet>
	<m_Version>
		<major>4</major>
		<minor>0</minor>
		<build>253</build>
		<revision>293</revision>
	</m_Version>
	<m_TemplateName text="LeaderFallback"/>
	<m_RootCollections>
		<Element>
			<m_CollectionName text="Leaders"/>
			<m_ReplaceMergedCollectionElements>false</m_ReplaceMergedCollectionElements>
{leaders}
		</Element>
	</m_RootCollections>
</AssetObjects..ArtDefSet>
""".format(leaders=leaders)


def build_dep(mod_name, guid, ui_package, fallback_package,
              artdef_files=()):
    """Art dependency file: makes the game load our cooked packages (and
    the fallback artdef). Either package may be None. artdef_files: the
    other .artdef files the mod ships (see ARTDEF_CONSUMERS)."""
    consumers, artdefs, libraries = [], "\t<ArtDefDependencies/>", []
    artdef_files = set(artdef_files)
    if ui_package:
        consumers.append("""		<Element>
			<ConsumerName text="UI"/>
			<ArtDefDependencyPaths/>
			<LibraryDependencies>
				<Element text="UITexture"/>
			</LibraryDependencies>
			<LoadsLibraries>true</LoadsLibraries>
		</Element>""")
        libraries.append(("UITexture", ui_package))
    if fallback_package:
        consumers.append("""		<Element>
			<ConsumerName text="LeaderFallback"/>
			<ArtDefDependencyPaths>
				<Element text="{artdef}"/>
			</ArtDefDependencyPaths>
			<LibraryDependencies>
				<Element text="LeaderFallback"/>
			</LibraryDependencies>
			<LoadsLibraries>true</LoadsLibraries>
		</Element>""".format(artdef=FALLBACK_ARTDEF))
        artdefs = """	<ArtDefDependencies>
		<Element>
			<ArtDefPath text="{artdef}"/>
			<ArtDefDependencyPaths/>
		</Element>
	</ArtDefDependencies>""".format(artdef=FALLBACK_ARTDEF)
        libraries.append(("LeaderFallback", fallback_package))
    if artdef_files:
        consumers += [consumer_xml(name, [p for p in paths
                                          if p in artdef_files], libs)
                      for name, paths, libs in ARTDEF_CONSUMERS
                      if artdef_files & set(paths)]
        deps = [(FALLBACK_ARTDEF, [])] if fallback_package else []
        deps += [(f, [d for d in ARTDEF_DEPENDENCIES.get(f, ())
                      if d in artdef_files])
                 for f in sorted(artdef_files)]
        artdefs = "\t<ArtDefDependencies>\n{}\n\t</ArtDefDependencies>".format(
            "\n".join("\t\t<Element>\n\t\t\t<ArtDefPath text=\"{}\"/>\n"
                      "\t\t\t{}\n\t\t</Element>".format(
                          f, path_list(d, "\t\t\t")) for f, d in deps))
        packaged = {lib for lib, _ in libraries}
        libraries += [(lib, None) for lib in sorted({
            lib for _, paths, libs in ARTDEF_CONSUMERS
            if artdef_files & set(paths) for lib in libs} - packaged)]
    library_xml = "\n".join("""		<Element>
			<LibraryName text="{0}"/>
			<PackageDependencies>
				<Element text="{1}.blp"/>
			</PackageDependencies>
		</Element>""".format(lib, pkg) if pkg else """		<Element>
			<LibraryName text="{0}"/>
			<PackageDependencies/>
		</Element>""".format(lib) for lib, pkg in sorted(libraries))
    return """<?xml version="1.0" encoding="UTF-8" ?>
<AssetObjects..GameDependencyData>
	<ID>
		<name text="{name}"/>
		<id text="{guid}"/>
	</ID>
	<RequiredGameArtIDs/>
	<SystemDependencies>
{consumers}
	</SystemDependencies>
{artdefs}
	<LibraryDependencies>
{libraries}
	</LibraryDependencies>
</AssetObjects..GameDependencyData>
""".format(name=xml_escape(mod_name), guid=guid,
           consumers="\n".join(consumers), artdefs=artdefs,
           libraries=library_xml)


# ---------------------------------------------------------------------------
# Art definitions of new civilizations and unique items
# ---------------------------------------------------------------------------
# Unlike leader fallbacks these reference only the game's own art: a new
# civilization joins existing city / unit cultures and borrows another
# civilization's music, and a unique unit, building or district is a
# renamed copy of its base item's art definition (same 3D models). The
# .artdef files are plain XML that the game reads as is.

CIVILIZATIONS_ARTDEF = "Civilizations.artdef"
CULTURES_ARTDEF = "Cultures.artdef"
UNITS_ARTDEF = "Units.artdef"
DISTRICTS_ARTDEF = "Districts.artdef"
BUILDINGS_ARTDEF = "Buildings.artdef"
LANDMARKS_ARTDEF = "Landmarks.artdef"
IMPROVEMENTS_ARTDEF = "Improvements.artdef"

# (consumer, artdef files it reads, libraries it loads), as in the DLC's
# own .dep files; only the files the mod ships are listed.
ARTDEF_CONSUMERS = [
    ("Units", [CULTURES_ARTDEF, UNITS_ARTDEF], ["Unit", "VFX", "Light"]),
    ("Landmarks", [LANDMARKS_ARTDEF, DISTRICTS_ARTDEF, IMPROVEMENTS_ARTDEF,
                   BUILDINGS_ARTDEF, CIVILIZATIONS_ARTDEF, CULTURES_ARTDEF],
     ["CityBuildings", "TileBase"]),
    ("Improvements", [IMPROVEMENTS_ARTDEF, LANDMARKS_ARTDEF,
                      BUILDINGS_ARTDEF, CIVILIZATIONS_ARTDEF,
                      CULTURES_ARTDEF], []),
    ("Civilizations", [CIVILIZATIONS_ARTDEF], []),
    ("Cultures", [CIVILIZATIONS_ARTDEF, CULTURES_ARTDEF], []),
    ("WorldView_Translate", [CIVILIZATIONS_ARTDEF, DISTRICTS_ARTDEF,
                             IMPROVEMENTS_ARTDEF, LANDMARKS_ARTDEF,
                             BUILDINGS_ARTDEF, CULTURES_ARTDEF], []),
    ("Audio", [CIVILIZATIONS_ARTDEF, UNITS_ARTDEF, DISTRICTS_ARTDEF,
               IMPROVEMENTS_ARTDEF, CULTURES_ARTDEF, LANDMARKS_ARTDEF,
               BUILDINGS_ARTDEF], []),
]
# artdef -> the artdefs it references
ARTDEF_DEPENDENCIES = {
    UNITS_ARTDEF: [UNITS_ARTDEF, CULTURES_ARTDEF],
    DISTRICTS_ARTDEF: [LANDMARKS_ARTDEF, DISTRICTS_ARTDEF],
    BUILDINGS_ARTDEF: [BUILDINGS_ARTDEF, DISTRICTS_ARTDEF],
    IMPROVEMENTS_ARTDEF: [IMPROVEMENTS_ARTDEF, LANDMARKS_ARTDEF],
    LANDMARKS_ARTDEF: [BUILDINGS_ARTDEF, CIVILIZATIONS_ARTDEF,
                       LANDMARKS_ARTDEF, CULTURES_ARTDEF],
}


def path_list(paths, indent):
    """<ArtDefDependencyPaths> with one <Element> per path."""
    if not paths:
        return "<ArtDefDependencyPaths/>"
    return "<ArtDefDependencyPaths>\n{}\n{}</ArtDefDependencyPaths>".format(
        "\n".join('{}\t<Element text="{}"/>'.format(indent, p)
                  for p in paths), indent)


def consumer_xml(name, paths, libraries):
    libs = ("<LibraryDependencies>\n{}\n\t\t\t</LibraryDependencies>".format(
        "\n".join('\t\t\t\t<Element text="{}"/>'.format(lib)
                  for lib in libraries)) if libraries
            else "<LibraryDependencies/>")
    return ("\t\t<Element>\n"
            "\t\t\t<ConsumerName text=\"{name}\"/>\n"
            "\t\t\t{paths}\n"
            "\t\t\t{libs}\n"
            "\t\t\t<LoadsLibraries>{loads}</LoadsLibraries>\n"
            "\t\t</Element>").format(
                name=name, paths=path_list(paths, "\t\t\t"), libs=libs,
                loads="true" if libraries else "false")


# -- the game's own art definitions -----------------------------------------

_artdef_cache = {}


def game_artdef_files(game_dir, filename):
    """The game's copies of an .artdef file in load order (base game, then
    DLC and expansions; scenarios are left out). Later ones win."""
    if not game_dir:
        return []
    files = [os.path.join(game_dir, "Base", "ArtDefs", filename)]
    dlc = os.path.join(game_dir, "DLC")
    if os.path.isdir(dlc):
        files += [os.path.join(dlc, name, "ArtDefs", filename)
                  for name in sorted(os.listdir(dlc))
                  if "scenario" not in name.lower()]
    return [f for f in files if os.path.isfile(f)]


def _artdef_root(path):
    if path not in _artdef_cache:
        try:
            _artdef_cache[path] = ET.parse(path).getroot()
        except (OSError, ET.ParseError):
            _artdef_cache[path] = None
    return _artdef_cache[path]


def _elements(root, collection):
    """The elements of one root collection of a parsed .artdef."""
    for coll in root.findall("./m_RootCollections/Element"):
        name = coll.find("m_CollectionName")
        if name is not None and name.get("text") == collection:
            for element in coll.findall("Element"):
                yield element


def element_name(element):
    name = element.find("m_Name")
    return name.get("text") if name is not None else None


def game_element_names(game_dir, filename, collection):
    """Names of a root collection's elements in the game's .artdef files,
    in order of first appearance."""
    names = []
    for path in game_artdef_files(game_dir, filename):
        root = _artdef_root(path)
        if root is not None:
            names += [n for n in map(element_name, _elements(root, collection))
                      if n and n not in names]
    return names


def find_game_element(game_dir, filename, collection, name):
    """The game's art definition of name (the last file defining it
    wins), as a copy, or None."""
    found = None
    for path in game_artdef_files(game_dir, filename):
        root = _artdef_root(path)
        if root is None:
            continue
        for element in _elements(root, collection):
            if element_name(element) == name:
                found = element
    return copy.deepcopy(found) if found is not None else None


def civilization_music(game_dir):
    """{CivilizationType: audio XrefName} from Civilizations.artdef."""
    out = {}
    for path in game_artdef_files(game_dir, CIVILIZATIONS_ARTDEF):
        root = _artdef_root(path)
        if root is None:
            continue
        for element in _elements(root, "Civilization"):
            xref = element.find(
                "./m_ChildCollections/Element/Element/m_Fields/m_Values/"
                "Element/m_Value")
            if element_name(element) and xref is not None:
                out[element_name(element)] = xref.get("text")
    return out


# -- writing ------------------------------------------------------------------

ARTDEF_VERSION = """	<m_Version>
		<major>4</major>
		<minor>0</minor>
		<build>253</build>
		<revision>293</revision>
	</m_Version>"""


def build_artdef(template, collections):
    """An .artdef file. collections: [(root collection name, [element
    XML])]; elements merge into the game's by name."""
    blocks = []
    for name, elements in collections:
        blocks.append("""		<Element>
			<m_CollectionName text="{name}"/>
			<m_ReplaceMergedCollectionElements>false</m_ReplaceMergedCollectionElements>
{elements}
		</Element>""".format(name=name, elements="\n".join(elements)))
    return """<?xml version="1.0" encoding="UTF-8" ?>
<AssetObjects..ArtDefSet>
{version}
	<m_TemplateName text="{template}"/>
	<m_RootCollections>
{blocks}
	</m_RootCollections>
</AssetObjects..ArtDefSet>
""".format(version=ARTDEF_VERSION, template=template,
           blocks="\n".join(blocks))


def renamed_element_xml(element, new_name):
    """A game art definition element under a new name, as XML text."""
    element.find("m_Name").set("text", new_name)
    element.tail = None
    return "\t\t\t" + ET.tostring(element, encoding="unicode").strip()


def civilization_element_xml(civ, music_xref):
    """Civilizations.artdef element: the civilization's music (the audio
    of the civilization named music_xref)."""
    return """			<Element>
				<m_Fields>
					<m_Values/>
				</m_Fields>
				<m_ChildCollections>
					<Element>
						<m_CollectionName text="Audio"/>
						<m_ReplaceMergedCollectionElements>false</m_ReplaceMergedCollectionElements>
						<Element>
							<m_Fields>
								<m_Values>
									<Element class="AssetObjects..StringValue">
										<m_Value text="{xref}"/>
										<m_ParamName text="XrefName"/>
									</Element>
								</m_Values>
							</m_Fields>
							<m_ChildCollections/>
							<m_Name text="Entry"/>
							<m_AppendMergedParameterCollections>false</m_AppendMergedParameterCollections>
						</Element>
					</Element>
				</m_ChildCollections>
				<m_Name text="{civ}"/>
				<m_AppendMergedParameterCollections>false</m_AppendMergedParameterCollections>
			</Element>""".format(civ=civ, xref=xml_escape(music_xref))


def culture_element_xml(culture, civs):
    """Cultures.artdef element adding civilizations to an existing culture
    (its other members are kept: the parameter collection is appended)."""
    refs = "\n".join("""								<Element class="AssetObjects..ArtDefReferenceValue">
									<m_ElementName text="{civ}"/>
									<m_RootCollectionName text="Civilization"/>
									<m_ArtDefPath text="Civilizations.artdef"/>
									<m_CollectionIsLocked>true</m_CollectionIsLocked>
									<m_TemplateName text="Civilizations"/>
									<m_ParamName text="Civilizations{n:03d}"/>
								</Element>""".format(civ=civ, n=n)
                     for n, civ in enumerate(civs, 1))
    return """			<Element>
				<m_Fields>
					<m_Values>
						<Element class="AssetObjects..CollectionValue">
							<m_eObjectType>INVALID</m_eObjectType>
							<m_eValueType>ARTDEF_REF</m_eValueType>
							<m_Values>
{refs}
							</m_Values>
							<m_ParamName text="Civilizations"/>
						</Element>
					</m_Values>
				</m_Fields>
				<m_ChildCollections/>
				<m_Name text="{culture}"/>
				<m_AppendMergedParameterCollections>true</m_AppendMergedParameterCollections>
			</Element>""".format(culture=xml_escape(culture), refs=refs)
