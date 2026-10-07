"""
Civ 6 Mod Generator
===================

A tkinter GUI that generates Sid Meier's Civilization VI mods with new
civilizations and leaders. One mod ("pack") can contain any
number of each.

Leaders (alternate leaders for game civilizations, or the leaders of the
pack's new civilizations):

  * inherit an existing leader's ability (traits, name and description)
    and AI agenda - or use another of the game's agendas, optionally
    under a new name and description - and can get a new ability of
    their own, made of effects (see below), on top of or instead of it,
  * and have customizable cosmetics: name, loading bio, quote, all
    diplomacy lines, Civilopedia page, leader icon, loading/diplomacy
    images and leader colors.

New civilizations have their own name, icon, city and citizen names,
start bias, Civilopedia page, city / unit art style and music (the
game's own art), and:

  * an ability that copies the effects of existing abilities and/or has
    effects of its own, built from a library of the game's modifier
    types with optional conditions (modifiers.py),
  * unique units, buildings and districts: copies of an existing item
    (3D art and icons too) with changed stats, yields, great person
    points and extra effects, normally replacing that item.

Work-in-progress projects can be saved and re-opened (*.civmod files,
plain JSON), so you can build a mod over several sessions. Projects of
older versions (*.altleader) still open and are saved as *.civmod.

Usage:
    python main.py

Optional dependency:
    Pillow (pip install Pillow) - converts your images into the .dds
    textures the SDK asset cooker packs for the game. Without it, art
    falls back to the inherited leader's / copied item's.

Data source (recommended):
    Click "Load from game cache" and point it at the game's
    DebugGameplay.sqlite (auto-detected from the usual locations). This
    fills the dropdowns with the real content of YOUR install, including
    DLC and other mods, and pre-fills inherited fields.

Tests:
    python -m unittest discover -s tests -t .

Note:
    Older *.altleader project files are Python pickles, which can run
    code when opened: only open ones you or people you trust created.
    *.civmod files are plain JSON and safe to open.
"""
