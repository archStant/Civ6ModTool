"""Explanations shown on the 3D model tabs (in "How this works" boxes)
and as tooltips."""

# ---------------------------------------------------------------------------
# Unique units: the 3D model tab
# ---------------------------------------------------------------------------

UNIT_MODEL = """
What a unit looks like: on the map a unit is a small group of figures. Each group of figures is a "model" (a soldier, a horseman, a ship...) shown a number of times at some scale. The formation decides where the figures stand and how they move together, the combat animations how they fight, and the sound what you hear.

Looks like: the easiest change. Pick any unit and the unique unit takes over its whole look - models, formation, animations, sound and also its icons and portraits. Leave it empty to look like the unit it copies.

Models: tick "Own models" to choose the figures yourself. Count is how many figures of that model stand in the unit; scale 1 is the normal size (1.2 = 20% bigger). You can mix models, e.g. 3 Legion figures led by 1 Swordsman. Formations are made for a certain number of figures (most land units have 3 to 5), so a very different total may stand oddly. "Use its model as a starting point" copies the look unit's models into the table for you to change.

Designed models (below): your own models put together from the game's parts - armour, weapons, shields, helmets, horses. Once designed, a model appears in the Model list as @NAME and is used like any other.

Culture: most models change with the civilization's unit style (General tab of the civilization) - e.g. other faces and hair for South American units. Your choices keep that variety.

Good to know: everything here uses models the game already has, so it works without extra art files - but there is no 3D preview in the generator; check the unit in game. If the game cannot find a model, formation or animation you typed, the README's generation log says so.
"""

UNIT_TIPS = {
    "look": "Any unit: the unique unit takes over its whole look and its "
            "icons.",
    "count": "How many figures of this model the unit shows.",
    "scale": "Size of the figures: 1 = normal, 1.2 = 20% bigger.",
    "formation": "How the figures stand and move together. Cavalry "
                 "formations (e.g. Horsemen) suit mounted models.",
    "combat": "How the figures fight (attack, defend and die "
              "animations).",
    "sound": "Any unit: the unique unit makes its sounds (moving, "
             "fighting).",
}

# ---------------------------------------------------------------------------
# The model designer
# ---------------------------------------------------------------------------

DESIGNER = """
How the game builds a figure: every unit model is a skeleton with parts hung on it - a body, a head, armour, a helmet, a weapon, a shield... Each part is a mesh from the game's catalogue of parts. The designer lets you swap, remove and add those parts, so you can e.g. give a swordsman a spear and a knight's shield, or put a foot soldier on a horse.

Start from: the model whose skeleton, animations and parts you begin with. The animations stay those of this model whatever parts you choose, so start from a model holding the same kind of weapon you want (a spearman for spears, an archer for bows) - a sword model with a spear still swings it like a sword.

Mount: to make a mounted model, start from a figure on foot and pick a mounted model as the mount. Your figure becomes the rider of that model's horse (or chariot, camel, elephant...) and the model moves and fights like the mount's unit. The table then has two parts: the rider and the mount. Give such a unit a cavalry formation (e.g. Horsemen) and combat animations (e.g. Knight) on the 3D model tab.

The columns:
- Slot: the part's name (Armor, Weapon, Shield, Hats, Body, Head...). Slots of the model you started from keep their names; new parts can have any name.
- Point: where on the skeleton the part hangs. Root is the whole body (armour, clothes, body), WeaponPrimary the right hand, WeaponSecondary the left hand (shields), Hat the head (helmets, hair, beards), RiderAttach the saddle.
- Category and Mesh: which mesh the part shows, e.g. Armor / Knight or Spears / Hoplite. The category limits the mesh list; meshes are named after the unit that uses them in the game.
- Extra meshes: more meshes for the same part, comma separated (Category/Mesh). Each figure picks one of them at random, for variety - the game uses this for heads, hair and beards.
- Tint: colors painted over the part. USE_CIV_COLOR paints it in the player's colors (like the game's banners and tabards); empty keeps the mesh's own colors.

Remove drops a part (e.g. no helmet); Add part adds one (e.g. a cape: Capes / Swordsman at point Root). "Load its parts" starts over from the chosen model and mount.

Good to know: a mesh made for another body may not fit perfectly - riders in the game wear rider armour, so infantry armour on a horse can look odd. There is no 3D preview; check the unit in game.
"""

DESIGNER_TIPS = {
    "slot": "The part's name: Armor, Weapon, Shield, Hats, Body, Head...",
    "point": "Where the part hangs: Root = body, WeaponPrimary = right "
             "hand, WeaponSecondary = left hand, Hat = head.",
    "category": "The kind of part (Armor, Swords, Shields, Hats...); it "
                "limits the mesh list.",
    "mesh": "The mesh, named after the game unit that uses it.",
    "extra": "More meshes (Category/Mesh, comma separated); each figure "
             "picks one at random.",
    "tint": "USE_CIV_COLOR paints the part in the player's colors; empty "
            "keeps its own colors.",
    "template": "Its skeleton and animations are used: pick a model with "
                "the same kind of weapon.",
    "mount": "A mounted model: your figure rides its horse / chariot and "
             "uses its animations.",
}

# ---------------------------------------------------------------------------
# Unique buildings and districts
# ---------------------------------------------------------------------------

MESH_NAMES = """
Mesh names start with the district they come from: DIS_CMP Campus, DIS_REL Holy Site, DIS_THR Theater Square, DIS_COM Commercial Hub, DIS_HBR Harbor, DIS_PRD Industrial Zone, DIS_ENC Encampment, DIS_ENT Entertainment Complex, DIS_AERO Aerodrome, DIS_AQD Aqueduct, DIS_GOV Government Plaza, DIS_DIP Diplomatic Quarter, DIS_NBH Neighborhood, DIS_CTY City Center, DIS_SPACE Spaceport, DIS_DAM Dam, DIS_CNL Canal. Era words in a name (Ancient, CLA/Classical, IND/Industrial, MOD/Modern) tell which era it was made for. Avoid TB_EMPTY and the *_ERROR meshes: they are empty placeholders.
"""

BUILDING_MODEL = """
How the game draws a building: a building is not a separate object on the map - it is drawn as part of its district. The district tile has a ground (its layout, roads and decoration) and one mesh for each of its buildings, chosen by the player's art era. The generator adds your building to every district that draws the building it copies (a unique Temple also shows in a Lavra), with the same ground layouts as that building.

Looks like: pick any building and yours uses its meshes - e.g. a unique Library that looks like a University. Leave it empty to look like the building it copies.

Where it is drawn: a building that replaces one in its district takes that building's place (and its ground layouts). A building that replaces nothing there - a new building, or one moved to another district on the Stats tab - is added to the district: every combination of buildings the district knows gets a copy with your building in it, so the ground stays right. "Drawn in the place of" says where it stands; its mesh is placed where that building stands, so if both are built they overlap - pick a building the civilization rarely builds there, or give it meshes that fit.

Own meshes: tick the box and pick the meshes yourself. Each mesh has an era: the game shows the one for the player's current art era - Ancient, Classical, Industrial or Modern - and the "any era" mesh where no era-specific one is given. One "any era" mesh is enough for a building that always looks the same.
""" + MESH_NAMES + """
Good to know: the mesh is placed where the copied building stands in its district, so a mesh from another district (e.g. a Campus building in a Holy Site) may overlap the ground or float slightly. Buildings without a district (wonders, buildings in the city center) have no model here. There is no 3D preview; check it in game.
"""

IMPROVEMENT_MODEL = """
How the game draws an improvement: its tile shows the improvement's landmark (its 3D model, which may change with era or culture like the game's own), plus a picture in the strategic view.

Looks like: the improvement whose look it uses - empty: the improvement it copies. A new improvement (Copy of: nothing) needs one: e.g. a "Sacred Grove" that looks like the Pairidaeza. Any of the game's improvements can be picked, also those of other civilizations; one from a DLC only shows when that DLC is on.

The map and the city screen show your improvement's icon: the icon of the improvement it looks like, unless you give it an icon image on the General tab.
"""

DISTRICT_MODEL = """
How the game draws a district: a district tile shows a ground mesh (the layout: paths, plazas, walls, decoration) and on it one mesh per building built there. The ground changes as the district grows - there is one ground for every combination of buildings the game knows (no buildings, the first building, the first two...), and often one per art era (Ancient, Classical, Industrial, Modern; "any era" is used where no era-specific one exists). Some districts also have grounds for particular cultures or civilizations, or for the tile's appeal (breathtaking ... disgusting).

Buildings: the meshes of the buildings this district shows. Pick another mesh to change how a building looks in your district only; leave a field empty to keep the game's ("now:" shows the current meshes).

Ground and layout: one row per ground the copied district has. Pick another ground mesh for any of them; empty keeps the game's. Ground meshes are numbered by how many buildings they leave room for - "Base_01" is usually the empty district, "Base_02" one building, "Base_03" two - so pick a ground with the same number for each row.

Fill the ground from district: fills every row at once with the grounds of another district, matching era and number of buildings - e.g. a unique Industrial Zone that is laid out like a Campus. Clear all empties every field.

Looks like: the district whose landmark (layout, building spots, meshes) it starts from - empty: the district it copies. A new district (Copy of: nothing) needs one: e.g. a new "Arena" laid out like a Theater Square. The tables below then list that district's buildings and grounds.

Your district gets a landmark of its own (a copy of the one it looks like, with your changes); a copied district with no changes simply looks like the district it copies. Buildings of your civilization built in it are added to it automatically - for a new district its own new buildings, each drawn in the place of one of the look district's buildings (see a building's 3D model tab).
""" + MESH_NAMES + """
Good to know: buildings are placed where the game expects them on the ground, so mixing meshes from different districts can overlap or leave gaps. There is no 3D preview; check it in game.
"""
