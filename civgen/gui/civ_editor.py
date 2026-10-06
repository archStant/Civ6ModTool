"""The editor of a new civilization."""

import copy

import tkinter as tk
from tkinter import messagebox, ttk

from ..civs import CITIZEN_GROUPS, CIV_INFO, START_BIAS, civ_slug
from ..uniques import KINDS, KIND_LABELS, MAIN_TABLES, new_unique_spec
from ..util import slug_for_name, type_display_name
from . import theme
from .modifier_editor import EffectsFrame
from .moments_editor import MomentsFrame
from .unique_editor import UniqueEditor
from .widgets import fit_to_screen
from .widgets import icon_text
from .widgets import (ImagePreview, ScrollFrame, TypeCombo, browse_image,
                      names_text, text_lines, type_label)

ICON_FILE, ICON_CIV = "file", "civ"


class CivEditor(tk.Toplevel):
    """Edit a civilization spec (see civs.py); .result holds the edited
    spec after OK."""

    def __init__(self, app, spec, title="Civilization"):
        super().__init__(app)
        self.app = app
        self.spec = copy.deepcopy(spec)
        self.uniques = copy.deepcopy(self.spec.get("uniques") or [])
        self.result = None
        self.title(title)
        self.resizable(False, False)
        self.transient(app)

        outer = ttk.Frame(self, padding=10)
        outer.pack(fill="both", expand=True)
        notebook = ttk.Notebook(outer)
        notebook.pack(fill="both", expand=True)
        tabs = {}
        for key, text in (("general", "General"), ("ability", "Ability"),
                          ("uniques", "Uniques"), ("cities", "City names"),
                          ("citizens", "Citizen names"),
                          ("bias", "Start bias"), ("pedia", "Civilopedia"),
                          ("moments", "Historic moments")):
            # every tab scrolls if the screen is too small for it
            tabs[key] = ScrollFrame(notebook, height=None)
            notebook.add(tabs[key], text=text)
        tabs = {key: tab.inner for key, tab in tabs.items()}
        self._build_general(tabs["general"])
        self._build_ability(tabs["ability"])
        self._build_uniques(tabs["uniques"])
        self._build_cities(tabs["cities"])
        self._build_citizens(tabs["citizens"])
        self._build_bias(tabs["bias"])
        self._build_pedia(tabs["pedia"])
        self.moments_frame = MomentsFrame(
            tabs["moments"], self.spec.get("moment_illustrations"),
            self._moment_items)
        self.moments_frame.pack(fill="both", expand=True)

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
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _civ_choices(self):
        return self.app.data.type_choices("civilization")

    # -- General ------------------------------------------------------------

    def _build_general(self, body):
        pad = {"padx": 6, "pady": 3}
        spec, data = self.spec, self.app.data
        row = 0
        ttk.Label(body, text="Name").grid(row=row, column=0, sticky="w",
                                          **pad)
        self.name_var = tk.StringVar(value=spec.get("name", ""))
        ttk.Entry(body, textvariable=self.name_var, width=30).grid(
            row=row, column=1, sticky="w", **pad)
        self.slug_label = ttk.Label(body)
        self.slug_label.grid(row=row, column=2, sticky="w", **pad)
        self.name_var.trace_add("write", lambda *_: self._refresh_slug())
        row += 1
        ttk.Label(body, text="Adjective").grid(row=row, column=0, sticky="w",
                                               **pad)
        self.adjective_var = tk.StringVar(value=spec.get("adjective", ""))
        ttk.Entry(body, textvariable=self.adjective_var, width=30).grid(
            row=row, column=1, sticky="w", **pad)
        ttk.Label(body, text="e.g. 'Amazonian' (empty: the name)",
                  foreground=theme.hint()).grid(row=row, column=2, sticky="w",
                                            **pad)
        row += 1
        ttk.Label(body, text="Description").grid(row=row, column=0,
                                                 sticky="w", **pad)
        self.description_var = tk.StringVar(value=spec.get("description", ""))
        ttk.Entry(body, textvariable=self.description_var, width=30).grid(
            row=row, column=1, sticky="w", **pad)
        ttk.Label(body, text="e.g. 'Amazonian civilization' (empty: "
                             "'<adjective> civilization')",
                  foreground=theme.hint()).grid(row=row, column=2, sticky="w",
                                            **pad)
        row += 1

        style = ttk.LabelFrame(body, text="Look and sound (the game's own art)",
                               padding=(8, 4))
        style.grid(row=row, column=0, columnspan=3, sticky="we", pady=(10, 3))
        row += 1
        self.culture_var = tk.StringVar(value=spec.get("culture", ""))
        self.unit_culture_var = tk.StringVar(value=spec.get("unit_culture",
                                                            ""))
        self.ethnicity_var = tk.StringVar(value=spec.get("ethnicity", ""))
        for r, (label, var, values, hint) in enumerate((
                ("City style", self.culture_var, data.cultures,
                 "buildings and city look"),
                ("Unit style", self.unit_culture_var, data.unit_cultures,
                 "how units look"),
                ("Unit portraits", self.ethnicity_var, data.ethnicities,
                 "faces of units in the unit panel"))):
            ttk.Label(style, text=label).grid(row=r, column=0, sticky="w",
                                              **pad)
            ttk.Combobox(style, textvariable=var, values=values,
                         width=30).grid(row=r, column=1, sticky="w", **pad)
            ttk.Label(style, text=hint, foreground=theme.hint()).grid(
                row=r, column=2, sticky="w", **pad)
        ttk.Label(style, text="Music of").grid(row=3, column=0, sticky="w",
                                               **pad)
        self.music = TypeCombo(style, self._civ_choices(),
                               spec.get("music_from", ""), width=30)
        self.music.grid(row=3, column=1, sticky="w", **pad)
        ttk.Label(style, text="the civilization whose music it plays",
                  foreground=theme.hint()).grid(row=3, column=2, sticky="w",
                                            **pad)
        if not data.cultures:
            ttk.Label(style, foreground=theme.hint(), text=(
                "(load the game cache to list the styles - or type the "
                "names used in Cultures.artdef)")).grid(
                row=4, column=0, columnspan=3, sticky="w", **pad)

        icon = ttk.LabelFrame(body, text="Icon", padding=(8, 4))
        icon.grid(row=row, column=0, columnspan=3, sticky="we", pady=(10, 3))
        self.icon_mode = tk.StringVar(
            value=ICON_FILE if spec.get("icon_path") else ICON_CIV)
        self.icon_path = tk.StringVar(value=spec.get("icon_path", ""))
        ttk.Radiobutton(icon, text="Image file", value=ICON_FILE,
                        variable=self.icon_mode).grid(row=0, column=0,
                                                      sticky="w", **pad)
        file_row = ttk.Frame(icon)
        file_row.grid(row=0, column=1, sticky="w", **pad)
        ImagePreview(file_row, self.icon_path).pack(side="left")
        ttk.Entry(file_row, textvariable=self.icon_path, width=36).pack(
            side="left", padx=6)
        ttk.Button(file_row, text="Browse...", command=lambda: (
            browse_image(self, self.icon_path, "Civilization icon"),
            self.icon_mode.set(ICON_FILE))).pack(side="left")
        ttk.Label(icon, foreground=theme.hint(), wraplength=560, justify="left",
                  text="A white symbol on a transparent background, like the "
                       "game's own (the game tints it in the leader's "
                       "colors). Needs the SDK asset cooker.").grid(
            row=1, column=1, sticky="w", padx=6)
        ttk.Radiobutton(icon, text="Icon of", value=ICON_CIV,
                        variable=self.icon_mode).grid(row=2, column=0,
                                                      sticky="w", **pad)
        self.icon_from = TypeCombo(icon, self._civ_choices(),
                                   spec.get("icon_from", ""), width=30)
        self.icon_from.grid(row=2, column=1, sticky="w", **pad)
        self._refresh_slug()

    def _refresh_slug(self):
        slug = civ_slug({"name": self.name_var.get()},
                        self.app.type_prefix())
        self.slug_label.configure(text="type: " + (slug or "(type a name)"))

    # -- Ability -------------------------------------------------------------

    def _build_ability(self, body):
        pad = {"padx": 6, "pady": 3}
        ability = self.spec.get("ability") or {}
        ttk.Label(body, wraplength=760, justify="left", text=(
            "The civilization ability: copies of existing abilities' effects "
            "and/or effects of its own. Write the description yourself - "
            "the game does not describe effects by itself.")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        ttk.Label(body, text="Name").grid(row=1, column=0, sticky="w", **pad)
        self.ability_name = tk.StringVar(value=ability.get("name", ""))
        ttk.Entry(body, textvariable=self.ability_name, width=40).grid(
            row=1, column=1, sticky="w", **pad)
        ttk.Label(body, text="Description").grid(row=2, column=0,
                                                 sticky="nw", **pad)
        box, self.ability_desc = icon_text(body, height=4, width=80,
                                           wrap="word", undo=True)
        self.ability_desc.insert("1.0", ability.get("desc", ""))
        box.grid(row=2, column=1, columnspan=2, sticky="w", **pad)

        copies = ttk.LabelFrame(body, text="Copy the effects of existing "
                                           "abilities", padding=(8, 4))
        copies.grid(row=3, column=0, columnspan=3, sticky="we", pady=(8, 3))
        self.clone_list = tk.Listbox(copies, height=4, width=90,
                                     activestyle="none")
        self.clone_list.grid(row=0, column=0, columnspan=3, sticky="w")
        self.clones = list(ability.get("clone") or [])
        self.ability_choices = self._ability_choices()
        self.clone_combo = TypeCombo(copies, self.ability_choices, width=70)
        self.clone_combo.grid(row=1, column=0, sticky="w", pady=4)
        ttk.Button(copies, text="Add", command=self._add_clone).grid(
            row=1, column=1, sticky="w", padx=4)
        ttk.Button(copies, text="Remove", command=self._remove_clone).grid(
            row=1, column=2, sticky="w")
        ttk.Button(copies, text="Copy its name / description into empty "
                                "fields", command=self._copy_clone_text).grid(
            row=2, column=0, sticky="w")
        self._refresh_clones()

        ttk.Label(body, text="Effects of its own").grid(
            row=4, column=0, columnspan=3, sticky="w", pady=(8, 2))
        self.ability_effects = EffectsFrame(body, self.app, "trait",
                                            ability.get("effects"),
                                            self._unique_types)
        self.ability_effects.grid(row=5, column=0, columnspan=3, sticky="we")

    def _ability_choices(self):
        """[(TraitType, 'Name - owner')] of every ability in the game."""
        data = self.app.data
        out = []
        for owner, a in data.all_abilities():
            owner_name = (data.civ_names.get(owner) or
                          data.meta(owner).get("name") or
                          type_display_name(owner))
            if owner_name.startswith("LOC_"):
                owner_name = type_display_name(owner)
            out.append((a["type"], "{} - {}".format(a["name"], owner_name)))
        return out

    def _refresh_clones(self):
        names = dict(self.ability_choices)
        self.clone_list.delete(0, "end")
        for trait in self.clones:
            self.clone_list.insert("end", type_label(trait, names.get(trait)))

    def _add_clone(self):
        trait = self.clone_combo.get_type()
        if trait and trait not in self.clones:
            self.clones.append(trait)
            self._refresh_clones()

    def _remove_clone(self):
        for i in reversed(self.clone_list.curselection()):
            del self.clones[i]
        self._refresh_clones()

    def _copy_clone_text(self):
        abilities = {a["type"]: a for _, a in self.app.data.all_abilities()}
        sel = self.clone_list.curselection()
        trait = self.clones[sel[0]] if sel else \
            (self.clones[0] if self.clones else None)
        a = abilities.get(trait)
        if not a:
            messagebox.showinfo("No ability text", "Add (and select) a copied "
                                "ability first; its text comes from the game "
                                "cache.", parent=self)
            return
        if not self.ability_name.get().strip():
            self.ability_name.set(a["name"])
        if not self.ability_desc.get("1.0", "end").strip():
            self.ability_desc.insert("1.0", a["desc"].replace("[NEWLINE]",
                                                              "\n"))

    # -- Uniques -------------------------------------------------------------

    def _build_uniques(self, body):
        ttk.Label(body, wraplength=760, justify="left", text=(
            "Unique units, buildings and districts. Each is a copy of an "
            "existing one (its 3D art and icons too) with your changes, and "
            "normally replaces it for this civilization.")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        self.unique_tree = ttk.Treeview(body, columns=("kind", "base"),
                                        show="tree headings", height=10,
                                        selectmode="browse")
        self.unique_tree.heading("#0", text="Name")
        self.unique_tree.column("#0", width=240)
        self.unique_tree.heading("kind", text="Kind")
        self.unique_tree.column("kind", width=90)
        self.unique_tree.heading("base", text="Copy of")
        self.unique_tree.column("base", width=260)
        self.unique_tree.grid(row=1, column=0, sticky="nsew")
        self.unique_tree.bind("<Double-1>", lambda e: self._edit_unique())
        btns = ttk.Frame(body)
        btns.grid(row=1, column=1, sticky="n", padx=(8, 0))
        for kind in KINDS:
            ttk.Button(btns, text="Add {}...".format(KIND_LABELS[kind].lower()),
                       command=lambda k=kind: self._add_unique(k)).pack(
                fill="x", pady=2)
        ttk.Separator(btns).pack(fill="x", pady=6)
        for text, cmd in (("Edit...", self._edit_unique),
                          ("Duplicate", self._duplicate_unique),
                          ("Remove", self._remove_unique)):
            ttk.Button(btns, text=text, command=cmd).pack(fill="x", pady=2)
        self._refresh_uniques()

    def _refresh_uniques(self):
        tree, data = self.unique_tree, self.app.data
        tree.delete(*tree.get_children())
        for i, u in enumerate(self.uniques):
            tree.insert("", "end", iid=str(i), text=u.get("name", ""),
                        values=(KIND_LABELS.get(u.get("kind"), ""),
                                data.type_name(u.get("kind"), u["base"])
                                if u.get("base") else "(new)"))
        if getattr(self, "moments_frame", None):
            self.moments_frame.refresh_items()

    def _moment_items(self):
        """The civilization's uniques, for the historic moment pictures."""
        return [t for kind in KINDS for t, _ in self._unique_types(kind)]

    def _unique_dialog(self, spec):
        editor = UniqueEditor(self, self.app, spec,
                              self.name_var.get().strip(),
                              self._unique_types)
        self.wait_window(editor)
        self.grab_set()                 # the editor took the grab
        return editor.result

    def _selected_unique(self):
        sel = self.unique_tree.selection()
        return int(sel[0]) if sel else None

    def _add_unique(self, kind):
        result = self._unique_dialog(new_unique_spec(kind))
        if result:
            self.uniques.append(result)
            self._refresh_uniques()

    def _edit_unique(self):
        i = self._selected_unique()
        if i is None:
            return
        result = self._unique_dialog(copy.deepcopy(self.uniques[i]))
        if result:
            self.uniques[i] = result
            self._refresh_uniques()

    def _duplicate_unique(self):
        i = self._selected_unique()
        if i is not None:
            u = copy.deepcopy(self.uniques[i])
            u["name"] = (u.get("name") or "Unique") + " copy"
            self.uniques.insert(i + 1, u)
            self._refresh_uniques()

    def _remove_unique(self):
        i = self._selected_unique()
        if i is not None:
            del self.uniques[i]
            self._refresh_uniques()

    def _unique_types(self, kind):
        """The civilization's own uniques of a kind, for effect dropdowns."""
        out = []
        for u in self.uniques:
            if u.get("kind") == kind and u.get("name"):
                word = MAIN_TABLES[kind][1][:-len("Type")].upper()
                out.append((slug_for_name(u["name"], self.app.type_prefix(),
                                          kind=word), u["name"]))
        return out

    # -- names ----------------------------------------------------------------

    def _build_cities(self, body):
        ttk.Label(body, wraplength=760, justify="left", text=(
            "City names, one per line. The first one is the capital. Leaders "
            "with city names of their own use those first.")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        frame, self.city_text = names_text(body, self.spec.get("city_names"),
                                           height=22, width=40)
        frame.grid(row=1, column=0, sticky="nw")
        side = ttk.Frame(body)
        side.grid(row=1, column=1, sticky="nw", padx=(16, 0))
        ttk.Label(side, text="Copy the names of").pack(anchor="w")
        self.copy_names_from = TypeCombo(side, self._civ_choices(), width=30)
        self.copy_names_from.pack(anchor="w", pady=4)
        ttk.Button(side, text="Copy city names",
                   command=self._copy_city_names).pack(anchor="w")

    def _copy_city_names(self):
        civ = self.copy_names_from.get_type()
        names = self.app.data.city_names(civ)
        if not names:
            messagebox.showinfo("No city names", "No city names found for {}. "
                                "Load the game cache first (main window)."
                                .format(civ or "(no civilization)"),
                                parent=self)
            return
        if text_lines(self.city_text) and not messagebox.askyesno(
                "Replace city names", "Replace the list with the {} names "
                "of {}?".format(len(names), civ), parent=self):
            return
        self.city_text.delete("1.0", "end")
        self.city_text.insert("1.0", "\n".join(names))

    def _build_citizens(self, body):
        ttk.Label(body, wraplength=760, justify="left", text=(
            "Names of citizens (great people use their own). One per line; "
            "all lists are optional.")).grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))
        names = self.spec.get("citizen_names") or {}
        self.citizen_texts = {}
        for col, (key, label, _, _) in enumerate(CITIZEN_GROUPS):
            ttk.Label(body, text=label).grid(row=1, column=col, sticky="w",
                                             padx=4)
            frame, text = names_text(body, names.get(key), height=18,
                                     width=22)
            frame.grid(row=2, column=col, sticky="nw", padx=4)
            self.citizen_texts[key] = text

    # -- start bias -----------------------------------------------------------

    def _build_bias(self, body):
        ttk.Label(body, wraplength=760, justify="left", text=(
            "Where the civilization prefers to start: tier 1 is the "
            "strongest preference, 5 the weakest.")).grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))
        bias = self.spec.get("start_bias") or {}
        self.bias_list = ttk.Frame(body)
        self.bias_list.grid(row=1, column=0, columnspan=4, sticky="w")
        self.bias_rows = []
        for kind in START_BIAS:
            for type_name, tier in sorted((bias.get(kind) or {}).items()):
                self._add_bias(kind, type_name, tier)
        add = ttk.Frame(body)
        add.grid(row=2, column=0, columnspan=4, sticky="w", pady=6)
        for kind in START_BIAS:
            ttk.Button(add, text="Add {}".format(kind),
                       command=lambda k=kind: self._add_bias(k, "", 3)).pack(
                side="left", padx=(0, 6))
        river = ttk.Frame(body)
        river.grid(row=3, column=0, columnspan=4, sticky="w", pady=(8, 0))
        self.river_on = tk.BooleanVar(value=bias.get("river") is not None)
        self.river_tier = tk.StringVar(value=str(bias.get("river") or 3))
        ttk.Checkbutton(river, text="Rivers, tier", variable=self.river_on
                        ).pack(side="left")
        ttk.Spinbox(river, from_=1, to=5, width=4,
                    textvariable=self.river_tier).pack(side="left", padx=4)

    def _add_bias(self, kind, type_name, tier):
        frame = ttk.Frame(self.bias_list)
        frame.pack(anchor="w", pady=2)
        ttk.Label(frame, text=kind.title(), width=10).pack(side="left")
        combo = TypeCombo(frame, self.app.data.type_choices(kind), type_name,
                          width=40)
        combo.pack(side="left")
        tier_var = tk.StringVar(value=str(tier))
        ttk.Label(frame, text="tier").pack(side="left", padx=(8, 2))
        ttk.Spinbox(frame, from_=1, to=5, width=4, textvariable=tier_var
                    ).pack(side="left")
        row = {"frame": frame, "kind": kind, "combo": combo,
               "tier": tier_var}
        ttk.Button(frame, text="Remove", command=lambda: (
            frame.destroy(), self.bias_rows.remove(row))).pack(side="left",
                                                               padx=6)
        self.bias_rows.append(row)

    # -- Civilopedia -----------------------------------------------------------

    def _build_pedia(self, body):
        pedia = self.spec.get("pedia") or {}
        scroll = ScrollFrame(body, height=480)
        scroll.pack(fill="both", expand=True)
        inner = scroll.inner
        self.pedia_vars = {}
        for row, (key, label, _, _) in enumerate(CIV_INFO):
            ttk.Label(inner, text=label).grid(row=row, column=0, sticky="w",
                                              padx=6, pady=3)
            var = tk.StringVar(value=pedia.get(key, ""))
            ttk.Entry(inner, textvariable=var, width=60).grid(
                row=row, column=1, sticky="w", pady=3)
            self.pedia_vars[key] = var
        ttk.Label(inner, text="History (separate paragraphs with a blank "
                              "line)").grid(row=len(CIV_INFO), column=0,
                                            columnspan=2, sticky="w",
                                            padx=6, pady=(10, 2))
        self.history = tk.Text(inner, height=18, width=86, wrap="word",
                               undo=True)
        self.history.insert("1.0", pedia.get("history", ""))
        self.history.grid(row=len(CIV_INFO) + 1, column=0, columnspan=2,
                          sticky="w", padx=6)

    # -- result ---------------------------------------------------------------

    def on_ok(self):
        spec = dict(self.spec)
        use_file = self.icon_mode.get() == ICON_FILE
        bias = {kind: {} for kind in START_BIAS}
        for row in self.bias_rows:
            type_name = row["combo"].get_type()
            if type_name:
                bias[row["kind"]][type_name] = row["tier"].get().strip()
        bias["river"] = self.river_tier.get().strip() \
            if self.river_on.get() else None
        spec.update({
            "name": self.name_var.get().strip(),
            "adjective": self.adjective_var.get().strip(),
            "description": self.description_var.get().strip(),
            "culture": self.culture_var.get().strip(),
            "unit_culture": self.unit_culture_var.get().strip(),
            "ethnicity": self.ethnicity_var.get().strip(),
            "music_from": self.music.get_type(),
            "icon_path": self.icon_path.get().strip() if use_file else "",
            "icon_from": "" if use_file else self.icon_from.get_type(),
            "ability": {
                "name": self.ability_name.get().strip(),
                "desc": self.ability_desc.get("1.0", "end").strip(),
                "clone": list(self.clones),
                "effects": self.ability_effects.effects()},
            "uniques": copy.deepcopy(self.uniques),
            "moment_illustrations": self.moments_frame.entries(),
            "city_names": text_lines(self.city_text),
            "citizen_names": {key: text_lines(text) for key, text in
                              self.citizen_texts.items()},
            "start_bias": bias,
            "pedia": dict({key: var.get().strip()
                           for key, var in self.pedia_vars.items()},
                          history=self.history.get("1.0", "end").strip()),
        })
        if not spec["name"]:
            messagebox.showwarning("Missing name",
                                   "Please enter the civilization's name.",
                                   parent=self)
            return
        self.result = spec
        self.destroy()
