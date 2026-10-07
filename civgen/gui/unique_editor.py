"""The editor of a civilization's unique unit, building, district or
improvement."""

import tkinter as tk
from tkinter import messagebox, ttk

from ..util import find_game_dir, slug_for_name
from ..unit_art import MAX_COUNT, new_unit_art, normalize_art, unit_look
from ..unit_models import describe as describe_design
from ..unit_models import clean_id, new_design
from . import theme
from .model_designer import ModelDesigner
from .landmark_editor import (BuildingModelFrame, DistrictModelFrame,
                              ImprovementModelFrame)
from .placement_editor import ImprovementPlacementFrame, PlacementFrame
from ..modifiers import describe_game_modifier, effect_from_game
from ..uniques import (normalize_improvement_art,
                       normalize_improvement_placement, normalize_placement)
from ..landmarks import normalize_building_art, normalize_district_art
from ..uniques import (CAN_BE_NEW, CAN_REPLACE, KIND_LABELS, MAIN_TABLES,
                       NO_PREREQ, STATS, describe_unique)
from .modifier_editor import EffectsFrame
from . import help_texts
from .widgets import WRITE_TIP, write_description
from .widgets import fit_to_screen
from .widgets import icon_text
from .widgets import (HelpBox, ImagePreview, ScrollFrame, TypeCombo,
                      add_tooltip, browse_image)

NEW = "NEW"            # "Copy of": nothing - a new building / district
SAME = "SAME"          # "Replaces": what the copied item stands for
NOTHING = "NOTHING"    # "Replaces": nothing - an extra item

BASE_HINTS = {
    "unit": "The unit to copy: the unique unit plays like it (stats, "
            "promotions, upgrades, 3D model) apart from what you change "
            "here, and normally replaces it for this civilization.",
    "building": "The building to copy: the unique building works like it "
                "(district, prerequisites, yields, effects) apart from "
                "what you change here, and normally replaces it for this "
                "civilization. Or 'Nothing - a new building': it starts "
                "from the game's usual values, in the district you pick "
                "on the Stats tab.",
    "district": "The district to copy: the unique district works like it "
                "(buildings, adjacency bonuses, 3D model) apart from what "
                "you change here, and normally replaces it for this "
                "civilization. Or 'Nothing - a new district': a specialty "
                "district with the game's usual values, laid out like the "
                "district you pick on the 3D model tab; give it buildings "
                "by building them in it (a new building's Stats tab).",
    "improvement": "The improvement to copy: the unique improvement works "
                   "like it (yields, where it can be built, adjacency "
                   "bonuses, 3D model) apart from what you change here. Or "
                   "'Nothing - a new improvement': it starts from the "
                   "game's usual values; pick where it can be built on the "
                   "Placement tab and its look on the 3D model tab. "
                   "Builders of the civilization build it as well as the "
                   "usual improvements.",
}

PLACEMENT_FRAMES = {"district": PlacementFrame,
                    "improvement": ImprovementPlacementFrame}
MODEL_FRAMES = {"building": BuildingModelFrame,
                "district": DistrictModelFrame,
                "improvement": ImprovementModelFrame}


class UniqueEditor(tk.Toplevel):
    """Edit a unique spec (see uniques.py); .result holds the edited spec
    after OK. civ_name: the civilization's name, for the window title."""

    def __init__(self, parent, app, spec, civ_name,
                 civ_types=lambda kind: []):
        super().__init__(parent)
        self.app, self.kind = app, spec["kind"]
        # civ_types(kind): [(type, name)] of the civilization's own uniques
        # (e.g. its districts, to build a building in)
        self.civ_types = civ_types
        self.result = None
        label = KIND_LABELS[self.kind]
        self.title("{} unique {}".format(civ_name or "New civilization's",
                                         label.lower()))
        self.resizable(False, False)
        self.transient(parent)

        outer = ttk.Frame(self, padding=10)
        outer.pack(fill="both", expand=True)
        notebook = ttk.Notebook(outer)
        notebook.pack(fill="both", expand=True)
        # every tab scrolls if the screen is too small for it
        general_tab = ScrollFrame(notebook, height=None)
        stats_tab = ScrollFrame(notebook, height=None)
        effects_tab = ScrollFrame(notebook, height=None)
        pedia_tab = ScrollFrame(notebook, height=None)
        general, stats = general_tab.inner, stats_tab.inner
        effects, pedia = effects_tab.inner, pedia_tab.inner
        notebook.add(general_tab, text="General")
        notebook.add(stats_tab, text="Stats")
        if self.kind in PLACEMENT_FRAMES:
            placement_scroll = ScrollFrame(notebook, height=None)
            placement_tab = placement_scroll.inner
            notebook.add(placement_scroll, text="Placement")
        if self.kind == "unit":         # tall: it scrolls
            model_tab = ScrollFrame(notebook, height=620)
            model = model_tab.inner
        else:
            model_tab = ScrollFrame(notebook, height=None)
            model = model_tab.inner
        notebook.add(model_tab, text="3D model")
        notebook.add(effects_tab, text="Effects")
        notebook.add(pedia_tab, text="Civilopedia")
        self._build_general(general, spec)
        self._build_stats(stats, spec)
        self.placement_frame = None
        if self.kind in PLACEMENT_FRAMES:
            self.placement_frame = PLACEMENT_FRAMES[self.kind](
                placement_tab, app, spec.get("placement"), self._base)
            self.placement_frame.pack(fill="both", expand=True)
            self.base.var.trace_add(
                "write", lambda *_: self.placement_frame.refresh())
        self.landmark_frame = None
        if self.kind == "unit":
            self._build_model(model, spec.get("art") or new_unit_art())
        else:
            frame = MODEL_FRAMES[self.kind]
            self.landmark_frame = frame(model, app, spec.get("art"),
                                        self._base, self._district)
            self.landmark_frame.pack(fill="both", expand=True)
            self.base.var.trace_add(
                "write", lambda *_: self.landmark_frame.refresh())
            if "PrereqDistrict" in self.stat_vars:
                self.stat_vars["PrereqDistrict"].trace_add(
                    "write", lambda *_: self.landmark_frame.refresh())
        ttk.Label(effects, wraplength=700, justify="left", text=(
            "Extra effects of the {0}, on top of those of the {0} it copies. "
            "Describe them in the description on the General tab - the game "
            "does not describe effects by itself.").format(
                label.lower())).pack(anchor="w", pady=(0, 8))
        # the copied item's own effects: kept, dropped, or made editable
        self.skip_effects = set(spec.get("skip_effects") or [])
        self.copied_box = ttk.LabelFrame(effects, padding=(8, 4))
        self.copied_box.pack(fill="x", pady=(0, 10))
        self.copied_rows = {}           # ModifierId -> (BooleanVar, mod)
        self.effects = EffectsFrame(effects, app, self.kind,
                                    spec.get("effects"), self._own_types)
        self.effects.pack(fill="both", expand=True)
        self._refresh_copied_effects()
        self.base.var.trace_add("write",
                                lambda *_: self._refresh_copied_effects())
        ttk.Label(pedia, text="Civilopedia history (separate paragraphs with "
                              "a blank line)").pack(anchor="w")
        self.pedia = tk.Text(pedia, height=16, width=80, wrap="word",
                             undo=True)
        self.pedia.insert("1.0", spec.get("pedia", ""))
        self.pedia.pack(fill="both", expand=True, pady=(4, 0))

        btns = ttk.Frame(outer)
        # (before the tabs: they keep their place on a small screen)
        btns.pack(side="bottom", anchor="e", pady=(10, 0), before=notebook)
        ttk.Button(btns, text="OK", command=self.on_ok).pack(side="left",
                                                             padx=4)
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(
            side="left", padx=4)
        fit_to_screen(self)
        self.grab_set()
        self.bind("<Escape>", lambda e: self.destroy())

    # -- tabs ---------------------------------------------------------------

    def _build_general(self, body, spec):
        pad = {"padx": 6, "pady": 3}
        data = self.app.data
        ttk.Label(body, text="Copy of").grid(row=0, column=0, sticky="w",
                                              **pad)
        choices = list(data.unique_choices(self.kind))
        if self.kind in CAN_BE_NEW:
            choices.insert(0, (NEW, "Nothing - a new {}".format(self.kind)))
        self.base = TypeCombo(body, choices, spec.get("base", "") or (
            NEW if self.kind in CAN_BE_NEW and spec.get("name") else ""),
            width=48)
        self.base.grid(row=0, column=1, columnspan=2, sticky="w", **pad)
        self.base.var.trace_add("write", lambda *_: self._refresh_base())
        ttk.Label(body, text=BASE_HINTS[self.kind], wraplength=520,
                  justify="left", foreground=theme.hint()).grid(
            row=1, column=1, columnspan=2, sticky="w", **pad)
        self.base_info = ttk.Label(body, wraplength=520, justify="left")
        self.base_info.grid(row=2, column=1, columnspan=2, sticky="w", **pad)
        ttk.Label(body, text="Replaces").grid(row=3, column=0, sticky="w",
                                              **pad)
        if self.kind in CAN_REPLACE:
            self.replaces = TypeCombo(body, [], width=48)
            self.replaces.grid(row=3, column=1, columnspan=2, sticky="w",
                               **pad)
            add_tooltip(self.replaces, "The {0} it stands in for in this "
                        "civilization's cities (like the game's own "
                        "uniques), or nothing: an extra {0}.".format(
                            self.kind))
            replaces = spec.get("replaces", True)
            self._refresh_replaces()
            value = SAME if replaces is True else (replaces or NOTHING)
            if value not in self.replaces.names:    # e.g. SAME of a new item
                value = NOTHING
            self.replaces.set_type(value)
        else:
            self.replaces = None
            ttk.Label(body, foreground=theme.hint(), text=(
                "Nothing - the game has no unique improvements replacing "
                "others: its Builders build it as well.")).grid(
                row=3, column=1, columnspan=2, sticky="w", **pad)

        ttk.Label(body, text="Name").grid(row=4, column=0, sticky="w", **pad)
        self.name_var = tk.StringVar(value=spec.get("name", ""))
        ttk.Entry(body, textvariable=self.name_var, width=32).grid(
            row=4, column=1, sticky="w", **pad)
        self.slug_label = ttk.Label(body)
        self.slug_label.grid(row=4, column=2, sticky="w", **pad)
        self.name_var.trace_add("write", lambda *_: self._refresh_slug())
        ttk.Label(body, text="Description").grid(row=5, column=0,
                                                 sticky="nw", **pad)
        box, self.desc = icon_text(
            body, buttons=[("Write from effects", self.write_description,
                            WRITE_TIP)],
            height=5, width=64, wrap="word", undo=True)
        self.desc.insert("1.0", spec.get("desc", ""))
        box.grid(row=5, column=1, columnspan=2, sticky="w", **pad)
        ttk.Label(body, text="(empty: the copied item's description)",
                  foreground=theme.hint()).grid(row=6, column=1, columnspan=2,
                                            sticky="w", padx=6)

        ttk.Label(body, text="Icon").grid(row=7, column=0, sticky="nw",
                                          **pad)
        icon_row = ttk.Frame(body)
        icon_row.grid(row=7, column=1, columnspan=2, sticky="w", **pad)
        self.icon_path = tk.StringVar(value=spec.get("icon_path", ""))
        ImagePreview(icon_row, self.icon_path).pack(side="left")
        ttk.Entry(icon_row, textvariable=self.icon_path, width=40).pack(
            side="left", padx=6)
        ttk.Button(icon_row, text="Browse...", command=lambda: browse_image(
            self, self.icon_path, "Icon image")).pack(side="left")
        ttk.Label(body, text="(empty: the copied item's icons; an image "
                             "replaces its main icon - square, transparent "
                             "background)", foreground=theme.hint()).grid(
            row=8, column=1, columnspan=2, sticky="w", padx=6)
        self.portrait_path = tk.StringVar(value=spec.get("portrait_path", ""))
        if self.kind == "unit":
            # the unit's portrait: in the same atlas as its icon
            label = ttk.Label(body, text="Portrait (?)")
            label.grid(row=9, column=0, sticky="nw", **pad)
            add_tooltip(label, (
                "The picture in the unit panel and the production list. "
                "Icon and portrait go into one icon atlas, side by side "
                "(portrait first), like the game's own unique units."))
            portrait_row = ttk.Frame(body)
            portrait_row.grid(row=9, column=1, columnspan=2, sticky="w",
                              **pad)
            ImagePreview(portrait_row, self.portrait_path).pack(side="left")
            ttk.Entry(portrait_row, textvariable=self.portrait_path,
                      width=40).pack(side="left", padx=6)
            ttk.Button(portrait_row, text="Browse...",
                       command=lambda: browse_image(
                           self, self.portrait_path,
                           "Portrait image")).pack(side="left")
            ttk.Label(body, text=(
                "(square; empty: the icon image is used for the portrait "
                "too - or, with neither, the copied unit's)"),
                foreground=theme.hint()).grid(
                row=10, column=1, columnspan=2, sticky="w", padx=6)
        self._refresh_slug()

    def _build_stats(self, body, spec):
        pad = {"padx": 6, "pady": 3}
        ttk.Label(body, wraplength=700, justify="left", text=(
            "Leave a field empty to keep the copied item's value (shown on "
            "the right) - for a new building or district, the game's usual "
            "value.")).grid(row=0, column=0, columnspan=3, sticky="w",
                                 pady=(0, 8))
        given = spec.get("stats") or {}
        self.stat_getters, self.base_labels = {}, {}
        self.stat_vars = {}             # column -> its StringVar
        row = 1
        for column, label, kind in STATS[self.kind]:
            ttk.Label(body, text=label).grid(row=row, column=0, sticky="w",
                                             **pad)
            if kind == "int":
                var = tk.StringVar(value=str(given.get(column, "")))
                ttk.Entry(body, textvariable=var, width=8).grid(
                    row=row, column=1, sticky="w", **pad)
                self.stat_getters[column] = var.get
                self.stat_vars[column] = var
            else:
                # "None": needs no technology / civic, even if the
                # copied item does (empty: the copied item's)
                if kind == "district":  # its own districts first
                    choices = list(self.civ_types("district")) + list(
                        self.app.data.type_choices(kind))
                    tip = ("The district the building is built in. Empty: "
                           "the copied building's (a new building needs "
                           "one).")
                else:
                    choices = [(NO_PREREQ, "None - needs no {}".format(
                        {"tech": "technology"}.get(kind, kind)))] + list(
                        self.app.data.type_choices(kind))
                    tip = ("Empty: the copied item's. 'None': no {} needed "
                           "at all.".format({"tech": "technology"}.get(
                               kind, kind)))
                combo = TypeCombo(body, choices, given.get(column, ""),
                                  width=36)
                add_tooltip(combo, tip)
                combo.grid(row=row, column=1, sticky="w", **pad)
                self.stat_getters[column] = combo.get_type
                self.stat_vars[column] = combo.var
            self.base_labels[column] = ttk.Label(body, foreground=theme.hint())
            self.base_labels[column].grid(row=row, column=2, sticky="w",
                                          **pad)
            row += 1
        self.number_tables = {}
        self.copy_buttons = {}          # key -> (button, title)
        if self.kind in ("building", "improvement"):
            row = self._number_table(body, row, "yields", "Yields",
                                     "yield", spec.get("yields"))
        if self.kind in ("building", "district"):
            row = self._number_table(body, row, "gpp",
                                     "Great person points", "great_person",
                                     spec.get("gpp"))
        if self.kind in ("district", "improvement"):
            self.adjacencies = tk.BooleanVar(
                value=spec.get("adjacencies", True))
            ttk.Checkbutton(body, variable=self.adjacencies, text=(
                "Keep the copied {}'s adjacency bonuses (add more on the "
                "Effects tab)".format(self.kind))).grid(
                row=row, column=0, columnspan=3, sticky="w", pady=(10, 0))
        self._refresh_base()

    def _refresh_copied_effects(self):
        """List the copied item's effects, each with a Keep box."""
        for var, mod in self.copied_rows.values():     # remember choices
            if var.get():
                self.skip_effects.discard(mod["id"])
            else:
                self.skip_effects.add(mod["id"])
        box = self.copied_box
        for widget in box.winfo_children():
            widget.destroy()
        self.copied_rows = {}
        base = self._base()
        if not base or self.kind == "unit":     # nothing copied to show
            box.pack_forget()
            return
        if not box.winfo_ismapped():
            box.pack(fill="x", pady=(0, 10), before=self.effects)
        mods = self.app.data.base_effects(self.kind, base)
        if not mods:
            box.configure(text="Effects of the copied {}".format(
                self.app.data.type_name(self.kind, base)))
            ttk.Label(box, foreground=theme.hint(), text=(
                "It has no effects of its own (or load the game data to "
                "see them).")).grid(row=0, column=0, sticky="w")
            return
        box.configure(text="Effects of the copied {} ({})".format(
            self.app.data.type_name(self.kind, base), len(mods)))
        ttk.Label(box, wraplength=820, justify="left",
                  foreground=theme.hint(), text=(
                      "Kept effects work as in the game. Untick one to "
                      "leave it out. \"Copy into my effects\" turns those "
                      "the effect list below can express into effects you "
                      "can edit (the others stay as they are).")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 4))
        name_of = self._name_of
        for i, mod in enumerate(mods, 1):
            var = tk.BooleanVar(value=mod["id"] not in self.skip_effects)
            ttk.Checkbutton(box, text="Keep", variable=var).grid(
                row=i, column=0, sticky="w", padx=(0, 8))
            editable = effect_from_game(mod) is not None
            ttk.Label(box, text=describe_game_modifier(mod, name_of)).grid(
                row=i, column=1, sticky="w")
            ttk.Label(box, foreground=theme.hint(),
                      text="editable" if editable else "as in the game"
                      ).grid(row=i, column=2, sticky="w", padx=(12, 0))
            self.copied_rows[mod["id"]] = (var, mod)
        ttk.Button(box, text="Copy into my effects",
                   command=self.copy_effects).grid(
            row=len(mods) + 1, column=0, columnspan=2, sticky="w",
            pady=(6, 0))

    def copy_effects(self):
        """The kept copied effects the editor can express become effects
        of the unique's own (and are no longer copied)."""
        copied, left = 0, 0
        for var, mod in self.copied_rows.values():
            if not var.get():
                continue
            effect = effect_from_game(mod)
            if effect is None:
                left += 1
                continue
            self.effects.items.append(effect)
            var.set(False)              # now one of its own
            copied += 1
        self.effects.refresh()
        messagebox.showinfo(
            "Effects copied", "{} effect{} copied into this {}'s own "
            "effects{}.".format(
                copied, "" if copied == 1 else "s", self.kind,
                "; {} cannot be edited here and stay{} copied as in the "
                "game".format(left, "s" if left == 1 else "")
                if left else ""), parent=self)

    def skipped_effects(self):
        """ModifierIds of the copied item's effects not to copy."""
        skip = set(self.skip_effects)
        for var, mod in self.copied_rows.values():
            (skip.discard if var.get() else skip.add)(mod["id"])
        return sorted(skip)

    def _number_table(self, body, row, key, title, kind, values):
        """An optional table of amounts per type (yields, great person
        points) replacing the copied item's."""
        own = tk.BooleanVar(value=values is not None)
        frame = ttk.LabelFrame(body, padding=(8, 4))
        ttk.Checkbutton(frame, variable=own, text="Own {} (replace the "
                        "copied item's)".format(title.lower())).grid(
            row=0, column=0, columnspan=6, sticky="w")
        entries = {}
        choices = self.app.data.type_choices(kind) or [
            (t, t) for t in sorted(values or {})]
        for i, (type_name, name) in enumerate(choices):
            r, c = 1 + i // 3, (i % 3) * 2
            ttk.Label(frame, text=name).grid(row=r, column=c, sticky="w",
                                             padx=(0, 4), pady=2)
            var = tk.StringVar(value=str((values or {}).get(type_name, "")))
            ttk.Entry(frame, textvariable=var, width=5).grid(
                row=r, column=c + 1, sticky="w", padx=(0, 14), pady=2)
            entries[type_name] = var
        copy_btn = ttk.Button(frame, command=lambda: self.copy_numbers(
            key))
        copy_btn.grid(row=1 + (len(choices) + 2) // 3, column=0,
                      columnspan=6, sticky="w", pady=(6, 0))
        frame.grid(row=row, column=0, columnspan=3, sticky="we", pady=(10, 0))
        self.number_tables[key] = (own, entries)
        self.copy_buttons[key] = (copy_btn, title)
        return row + 1

    def copy_numbers(self, key):
        """Fill a table with the copied item's values, to change them."""
        base = self._base()
        own, entries = self.number_tables[key]
        values = self.app.data.base_numbers(self.kind, base, key)
        for type_name, var in entries.items():
            var.set(str(values.get(type_name, "")))
        own.set(True)

    def _refresh_copy_buttons(self):
        base = self._base()
        for key, (button, title) in getattr(self, "copy_buttons",
                                            {}).items():
            if base:
                button.configure(text="Copy the {}'s {}".format(
                    self.app.data.type_name(self.kind, base),
                    title.lower()))
                button.grid()
            else:
                button.grid_remove()    # a new item: nothing to copy

    # -- 3D model (units) ------------------------------------------------------

    def _build_model(self, body, art):
        pad = {"padx": 6, "pady": 3}
        lists = self.app.data.unit_art
        units = self.app.data.type_choices("unit")
        head = ttk.Frame(body)
        head.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        ttk.Label(head, wraplength=760, justify="left", text=(
            "The unit's 3D model, made of the game's own models. By default "
            "it looks like the unit it copies; it can instead look like any "
            "other unit, and use other models (any number of groups, e.g. "
            "4 Swordsman + 1 RomanLegion), formation, animations and sound. "
            "Models follow the civilization's unit style. New 3D models "
            "(Blender / Asset Editor) are not supported.")).pack(
            anchor="w", pady=(0, 2))
        HelpBox(head, help_texts.UNIT_MODEL, wraplength=820).pack(
            anchor="w")

        ttk.Label(body, text="Looks like").grid(row=1, column=0, sticky="w",
                                                **pad)
        self.look_from = TypeCombo(body, units, art.get("look_from", ""),
                                   width=44)
        self.look_from.grid(row=1, column=1, sticky="w", **pad)
        add_tooltip(self.look_from, help_texts.UNIT_TIPS["look"])
        ttk.Label(body, text="(empty: the unit it copies; its icons come "
                             "along)", foreground=theme.hint()).grid(
            row=1, column=2, sticky="w", **pad)
        self.look_info = ttk.Label(body, wraplength=640, justify="left",
                                   foreground=theme.hint())
        self.look_info.grid(row=2, column=1, columnspan=2, sticky="w", **pad)
        ttk.Button(body, text="Use its model as a starting point",
                   command=self._load_look).grid(row=3, column=1, sticky="w",
                                                 **pad)

        box = ttk.LabelFrame(body, text="Models", padding=(8, 4))
        box.grid(row=4, column=0, columnspan=3, sticky="we", pady=(8, 3))
        self.own_members = tk.BooleanVar(value=art.get("members") is not None)
        ttk.Checkbutton(box, variable=self.own_members, text=(
            "Own models (otherwise: those of the unit it looks like)")).grid(
            row=0, column=0, columnspan=4, sticky="w")
        for col, (text, tip) in enumerate((
                ("Model", "A game model, or @NAME of a designed model."),
                ("Count", help_texts.UNIT_TIPS["count"]),
                ("Scale", help_texts.UNIT_TIPS["scale"]))):
            header = ttk.Label(box, text=text + " (?)")
            header.grid(row=1, column=col, sticky="w", padx=4)
            add_tooltip(header, tip)
        self.member_box = box
        self.member_rows = []
        for m in art.get("members") or []:
            self._add_member(m)
        ttk.Button(box, text="Add model", command=lambda: (
            self._add_member({"type": "", "count": 1, "scale": 1.0}),
            self.own_members.set(True))).grid(row=99, column=0, sticky="w",
                                              pady=(6, 0))

        self.formation = tk.StringVar(value=art.get("formation", ""))
        self.combat = tk.StringVar(value=art.get("combat", ""))
        for r, (label, var, values, hint, tip) in enumerate((
                ("Formation", self.formation, lists["formation"],
                 "how the models stand and move together",
                 help_texts.UNIT_TIPS["formation"]),
                ("Combat animations", self.combat, lists["combat"],
                 "how they fight", help_texts.UNIT_TIPS["combat"])), 5):
            name = ttk.Label(body, text=label)
            name.grid(row=r, column=0, sticky="w", **pad)
            add_tooltip(name, tip)
            ttk.Combobox(body, textvariable=var, values=values,
                         width=42).grid(row=r, column=1, sticky="w", **pad)
            ttk.Label(body, text="(empty: the look unit's) " + hint,
                      foreground=theme.hint()).grid(row=r, column=2,
                                                sticky="w", **pad)
        ttk.Label(body, text="Sounds like").grid(row=7, column=0, sticky="w",
                                                 **pad)
        self.sound_from = TypeCombo(body, units, art.get("sound_from", ""),
                                    width=44)
        self.sound_from.grid(row=7, column=1, sticky="w", **pad)
        add_tooltip(self.sound_from, help_texts.UNIT_TIPS["sound"])
        ttk.Label(body, text="(empty: the look unit's)",
                  foreground=theme.hint()).grid(row=7, column=2, sticky="w",
                                            **pad)
        if not lists["members"]:
            ttk.Label(body, foreground=theme.hint(), text=(
                "(load the game cache - with the game installed - to list "
                "the models, formations and animations)")).grid(
                row=8, column=0, columnspan=3, sticky="w", **pad)

        designs = ttk.LabelFrame(body, text=(
            "Designed models (armour, weapons, mount... from the game's "
            "parts; use them above as @NAME)"), padding=(8, 4))
        designs.grid(row=9, column=0, columnspan=3, sticky="we",
                     pady=(10, 0))
        self.designs = [dict(d, id=clean_id(d.get("id")))
                        for d in art.get("models") or []]
        self.design_list = tk.Listbox(designs, height=4, width=80,
                                      activestyle="none")
        self.design_list.grid(row=0, column=0, rowspan=3, sticky="w")
        self.design_list.bind("<Double-1>", lambda e: self._edit_design())
        for r, (text, cmd) in enumerate((("Design...", self._add_design),
                                         ("Edit...", self._edit_design),
                                         ("Remove", self._remove_design))):
            ttk.Button(designs, text=text, command=cmd).grid(
                row=r, column=1, sticky="we", padx=(8, 0), pady=1)
        self._refresh_designs()
        self.look_from.var.trace_add("write", lambda *_: self._refresh_look())
        self.base.var.trace_add("write", lambda *_: self._refresh_look())
        self._refresh_look()

    def _member_choices(self):
        return (["@" + d["id"] for d in getattr(self, "designs", [])] +
                self.app.data.unit_art["members"])

    def _refresh_designs(self):
        self.design_list.delete(0, "end")
        for d in self.designs:
            self.design_list.insert("end", "@{}  -  {}".format(
                d["id"], describe_design(d)))
        for row in self.member_rows:
            row["widgets"][0]["values"] = self._member_choices()

    def _design_dialog(self, design, taken):
        dialog = ModelDesigner(self, self.app, design, taken)
        self.wait_window(dialog)
        self.grab_set()                 # the designer took the grab
        return dialog.result

    def _add_design(self):
        look = unit_look(find_game_dir(), self._look_unit()) or {}
        first = (look.get("members") or [{}])[0].get("type", "")
        design = new_design(first)      # start from the unit's own model
        design["id"] = "MODEL{}".format(len(self.designs) + 1)
        result = self._design_dialog(design, [d["id"] for d in self.designs])
        if not result:
            return
        self.designs.append(result)
        if not self.own_members.get():  # show it: the unit's only model
            for row in list(self.member_rows):
                self._remove_member(row)
            count = sum(m["count"] for m in look.get("members") or []) or 4
            self._add_member({"type": "@" + result["id"], "count": count,
                              "scale": 1.0})
            self.own_members.set(True)
        self._refresh_designs()

    def _edit_design(self):
        sel = self.design_list.curselection()
        if not sel:
            return
        i = sel[0]
        old = self.designs[i]["id"]
        result = self._design_dialog(
            self.designs[i], [d["id"] for j, d in enumerate(self.designs)
                              if j != i])
        if not result:
            return
        self.designs[i] = result
        for row in self.member_rows:    # follow a rename
            if row["type"].get().strip().upper() == "@" + old:
                row["type"].set("@" + result["id"])
        self._refresh_designs()

    def _remove_design(self):
        sel = self.design_list.curselection()
        if sel:
            del self.designs[sel[0]]
            self._refresh_designs()

    def _add_member(self, member):
        r = 2 + len(self.member_rows)
        row = {"type": tk.StringVar(value=member.get("type", "")),
               "count": tk.StringVar(value=str(member.get("count", 1))),
               "scale": tk.StringVar(value="{:g}".format(
                   float(member.get("scale", 1.0))))}
        widgets = [
            ttk.Combobox(self.member_box, textvariable=row["type"], width=34,
                         values=self._member_choices()),
            ttk.Spinbox(self.member_box, from_=1, to=MAX_COUNT, width=5,
                        textvariable=row["count"]),
            ttk.Spinbox(self.member_box, from_=0.1, to=5.0, increment=0.05,
                        width=6, textvariable=row["scale"]),
            ttk.Button(self.member_box, text="Remove",
                       command=lambda: self._remove_member(row))]
        for col, widget in enumerate(widgets):
            widget.grid(row=r, column=col, sticky="w", padx=4, pady=2)
        row["widgets"] = widgets
        self.member_rows.append(row)

    def _remove_member(self, row):
        for widget in row["widgets"]:
            widget.destroy()
        self.member_rows.remove(row)

    def _look_unit(self):
        return self.look_from.get_type() or self.base.get_type()

    def _refresh_look(self):
        unit = self._look_unit()
        look = unit_look(find_game_dir(), unit) if unit else None
        if not unit:
            text = "(pick the unit it copies on the General tab)"
        elif look is None:
            text = "{}: no 3D model found in the game's art.".format(unit)
        else:
            text = "{}: {}; formation {}, animations {}, sound {}".format(
                self.app.data.type_name("unit", unit),
                ", ".join("{} x{} ({:g})".format(m["type"], m["count"],
                                                  m["scale"])
                          for m in look["members"]) or "no models",
                look["formation"] or "-", look["combat"] or "-",
                look["sound"] or "-")
        self.look_info.configure(text=text)

    def _load_look(self):
        unit = self._look_unit()
        look = unit_look(find_game_dir(), unit) if unit else None
        if not look:
            messagebox.showinfo("No model", "No 3D model found for {} (is "
                                "the game installed?).".format(
                                    unit or "the unit"), parent=self)
            return
        for row in list(self.member_rows):
            self._remove_member(row)
        for m in look["members"]:
            self._add_member(m)
        self.own_members.set(True)
        self.formation.set(look["formation"])
        self.combat.set(look["combat"])

    def model_spec(self):
        members = None
        if self.own_members.get():
            members = [{"type": r["type"].get().strip(),
                        "count": r["count"].get().strip(),
                        "scale": r["scale"].get().strip()}
                       for r in self.member_rows if r["type"].get().strip()]
        return {"look_from": self.look_from.get_type(),
                "members": members,
                "formation": self.formation.get().strip(),
                "combat": self.combat.get().strip(),
                "sound_from": self.sound_from.get_type(),
                "models": [dict(d) for d in self.designs]}

    # -- live info ----------------------------------------------------------

    def _own_types(self, kind):
        """The unique itself, offered in its own kind's lists (e.g. a
        district's adjacency effects)."""
        if kind != self.kind or not self._slug():
            return []
        return [(self._slug(), self.name_var.get().strip())]

    def _slug(self):
        word = MAIN_TABLES[self.kind][1][:-len("Type")].upper()
        return slug_for_name(self.name_var.get(), self.app.type_prefix(),
                             kind=word)

    def _refresh_slug(self):
        self.slug_label.configure(text="type: " + (self._slug() or
                                                    "(type a name)"))

    def _base(self):
        """The base item ("" = a new building / district)."""
        base = self.base.get_type()
        return "" if base == NEW else base

    def _refresh_replaces(self):
        """The Replaces choices: what the copied item stands for, nothing,
        or any item of the kind."""
        if self.replaces is None:
            return
        data = self.app.data
        base = self._base()
        row = data.item(self.kind, base)
        replaced = (row or {}).get("replaces") or base
        current = self.replaces.get_type()
        choices = []
        if replaced:
            choices.append((SAME, "{} (as the {} it copies)".format(
                data.type_name(self.kind, replaced), self.kind)))
        choices.append((NOTHING, "Nothing - an extra {}".format(self.kind)))
        choices += list(data.unique_choices(self.kind))
        self.replaces.set_choices(choices)
        if current == SAME and not replaced:
            current = NOTHING           # a new item has no "same"
        self.replaces.set_type(current or (SAME if replaced else NOTHING))

    def _district(self):
        """A building's district: the one chosen on the Stats tab, else
        the copied building's ("" if unknown)."""
        getter = getattr(self, "stat_getters", {}).get("PrereqDistrict")
        district = getter() if getter else ""
        if not district:
            row = self.app.data.item(self.kind, self._base())
            district = (row or {}).get("PrereqDistrict") or ""
        return district

    def _replaces_value(self):
        if self.replaces is None:
            return ""
        value = self.replaces.get_type()
        return True if value == SAME else ("" if value in (NOTHING, "")
                                           else value)

    def _refresh_base(self):
        data = self.app.data
        base = self._base()
        self._refresh_copy_buttons()
        row = data.item(self.kind, base)
        if hasattr(self, "replaces"):
            self._refresh_replaces()
        if not base and self.kind in CAN_BE_NEW:
            self.base_info.configure(text=(
                "A new {}: it starts from the game's usual values - set its "
                "{} on the Stats tab, its look on the 3D model tab.".format(
                    self.kind, {"building": "district and stats",
                                "district": "cost and stats",
                                "improvement": "yields and stats (and where "
                                "it can be built on the Placement tab)"}[
                        self.kind])))
        elif row:
            stats = ", ".join("{} {}".format(label.lower(), row.get(col))
                              for col, label, kind in STATS[self.kind]
                              if kind == "int" and row.get(col))
            note = "{}: {}".format(row["name"], stats)
            if row.get("replaces"):
                note += " (itself a unique {} replacing {})".format(
                    self.kind, data.type_name(self.kind, row["replaces"]))
            self.base_info.configure(text=note)
        else:
            self.base_info.configure(text="" if data.conn else
                                     "(load the game cache to list the "
                                     "game's items and their stats)")
        for column, label in getattr(self, "base_labels", {}).items():
            value = (row or {}).get(column)
            if column in ("PrereqTech", "PrereqCivic", "PrereqDistrict"):
                value = data.type_name(
                    {"PrereqTech": "tech", "PrereqCivic": "civic"}.get(
                        column, "district"), value) if value else "none"
            label.configure(text="copied: {}".format(value) if row else "")

    # -- result ---------------------------------------------------------------

    def _name_of(self, kind, type_name):
        """Display names, the civilization's own items included."""
        own = dict(self.civ_types(kind))
        own.update(self._own_types(kind))
        return own.get(type_name) or self.app.data.type_name(kind,
                                                            type_name)

    def write_description(self):
        spec = {"kind": self.kind, "base": self._base(),
                "replaces": self._replaces_value(),
                "stats": {c: get() for c, get in self.stat_getters.items()
                          if str(get()).strip()},
                "effects": self.effects.effects()}
        for key, (own, entries) in self.number_tables.items():
            if own.get():
                spec[key] = {t: var.get().strip()
                             for t, var in entries.items()
                             if var.get().strip()}
        write_description(self.desc, describe_unique(
            spec, self.app.data, self._name_of), self)

    def on_ok(self):
        spec = {
            "kind": self.kind,
            "base": self._base(),
            "replaces": self._replaces_value(),
            "name": self.name_var.get().strip(),
            "desc": self.desc.get("1.0", "end").strip(),
            "pedia": self.pedia.get("1.0", "end").strip(),
            "stats": {c: get() for c, get in self.stat_getters.items()
                      if str(get()).strip()},
            "yields": None, "gpp": None,
            "adjacencies": bool(getattr(self, "adjacencies",
                                        tk.BooleanVar(value=True)).get()),
            "effects": self.effects.effects(),
            "icon_path": self.icon_path.get().strip(),
            "skip_effects": self.skipped_effects(),
            "portrait_path": self.portrait_path.get().strip(),
        }
        spec["art"] = self.model_spec() if self.kind == "unit" \
            else self.landmark_frame.art()
        check = {"unit": normalize_art, "building": normalize_building_art,
                 "district": normalize_district_art,
                 "improvement": normalize_improvement_art}[self.kind]
        try:
            check(spec["art"], spec["name"] or "The " + self.kind)
        except ValueError as exc:
            messagebox.showwarning("3D model", str(exc), parent=self)
            return
        if self.placement_frame is not None:
            spec["placement"] = self.placement_frame.placement()
            check = normalize_placement if self.kind == "district" \
                else normalize_improvement_placement
            try:
                check(spec["placement"], spec["name"] or "The " + self.kind)
            except ValueError as exc:
                messagebox.showwarning("Placement", str(exc), parent=self)
                return
        for key, (own, entries) in self.number_tables.items():
            if own.get():
                spec[key] = {t: var.get().strip()
                             for t, var in entries.items()
                             if var.get().strip()}
        if not spec["name"]:
            messagebox.showwarning("Missing name", "Please enter the name.",
                                   parent=self)
            return
        if not spec["base"] and self.kind not in CAN_BE_NEW:
            messagebox.showwarning("Missing item", "Pick the {} to copy."
                                   .format(self.kind), parent=self)
            return
        self.result = spec
        self.destroy()
