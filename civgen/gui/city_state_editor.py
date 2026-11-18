"""The editor of a new city-state."""

import copy

import tkinter as tk
from tkinter import messagebox, ttk

from ..citystates import CATEGORIES, DEFAULT_CATEGORY, category_colors
from ..citystates import city_state_slug
from ..modifiers import describe_effects
from . import theme
from .civ_editor import ICON_CIV, ICON_FILE, CivPartsMixin
from .modifier_editor import EffectsFrame
from .widgets import WRITE_TIP, write_description
from .widgets import (ImagePreview, ScrollFrame, TypeCombo, browse_image,
                      fit_to_screen, icon_text, text_lines, type_label)


def _hex(rgb):
    return "#{:02x}{:02x}{:02x}".format(*rgb)


class CityStateEditor(CivPartsMixin, tk.Toplevel):
    """Edit a city-state spec (see citystates.py); .result holds the
    edited spec after OK."""

    def __init__(self, app, spec, title="City-state"):
        super().__init__(app)
        self.app = app
        self.spec = copy.deepcopy(spec)
        self.result = None
        self.title(title)
        self.resizable(False, False)
        self.transient(app)

        outer = ttk.Frame(self, padding=10)
        outer.pack(fill="both", expand=True)
        notebook = ttk.Notebook(outer)
        notebook.pack(fill="both", expand=True)
        tabs = {}
        for key, text in (("general", "General"),
                          ("bonus", "Suzerain bonus"),
                          ("cities", "City names"), ("bias", "Start bias"),
                          ("pedia", "Civilopedia")):
            # every tab scrolls if the screen is too small for it
            tabs[key] = ScrollFrame(notebook, height=None)
            notebook.add(tabs[key], text=text)
        tabs = {key: tab.inner for key, tab in tabs.items()}
        self._build_general(tabs["general"])
        self._build_bonus(tabs["bonus"])
        self._build_city_names(tabs["cities"], (
            "City names, one per line. The first one is the city-state's "
            "city; the others name cities it may capture or be given."),
            self._civ_choices())
        self._build_bias(tabs["bias"], "city-state")
        self._build_pedia(tabs["pedia"])

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
        """The game's city-states, then its civilizations (icons and city
        names to copy)."""
        data = self.app.data
        return data.city_state_choices() + data.type_choices("civilization")

    # -- General ------------------------------------------------------------

    def _build_general(self, body):
        pad = {"padx": 6, "pady": 3}
        spec = self.spec
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
        ttk.Label(body, text="e.g. 'Kabulian' (empty: the name)",
                  foreground=theme.hint()).grid(row=row, column=2,
                                                sticky="w", **pad)
        row += 1
        ttk.Label(body, text="Description").grid(row=row, column=0,
                                                 sticky="w", **pad)
        self.description_var = tk.StringVar(value=spec.get("description", ""))
        ttk.Entry(body, textvariable=self.description_var, width=30).grid(
            row=row, column=1, sticky="w", **pad)
        ttk.Label(body, text="empty: '<name> city-state'",
                  foreground=theme.hint()).grid(row=row, column=2,
                                                sticky="w", **pad)
        row += 1

        ttk.Label(body, text="Kind").grid(row=row, column=0, sticky="w",
                                          **pad)
        kind_row = ttk.Frame(body)
        kind_row.grid(row=row, column=1, columnspan=2, sticky="w", **pad)
        self._category_labels = {label: key
                                 for key, (label, _) in CATEGORIES.items()}
        category = spec.get("category") or DEFAULT_CATEGORY
        self.category_var = tk.StringVar(
            value=CATEGORIES.get(category, CATEGORIES[DEFAULT_CATEGORY])[0])
        combo = ttk.Combobox(kind_row, textvariable=self.category_var,
                             state="readonly", width=16,
                             values=[label for label, _ in
                                     CATEGORIES.values()])
        combo.pack(side="left")
        combo.bind("<<ComboboxSelected>>", lambda e: self._refresh_swatch())
        # its kind's color on the city-states' dark primary, as the game
        # shows city-states
        self.swatch_frame = tk.Frame(kind_row, relief="solid",
                                     borderwidth=1, padx=5, pady=5)
        self.swatch_frame.pack(side="left", padx=8)
        self.swatch = tk.Frame(self.swatch_frame, width=theme.scaled(18),
                               height=theme.scaled(12))
        self.swatch.pack()
        ttk.Label(kind_row, foreground=theme.hint(), wraplength=420,
                  justify="left",
                  text="Its envoy bonuses, AI, colors and type icon are "
                       "those of its kind, as for the game's own "
                       "city-states.").pack(side="left")
        row += 1

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
            browse_image(self, self.icon_path, "City-state icon"),
            self.icon_mode.set(ICON_FILE))).pack(side="left")
        ttk.Label(icon, foreground=theme.hint(), wraplength=560,
                  justify="left",
                  text="A white symbol on a transparent background, like "
                       "the game's own (the game tints it in its kind's "
                       "color). Needs the SDK asset cooker.").grid(
            row=1, column=1, sticky="w", padx=6)
        ttk.Radiobutton(icon, text="Icon of", value=ICON_CIV,
                        variable=self.icon_mode).grid(row=2, column=0,
                                                      sticky="w", **pad)
        self.icon_from = TypeCombo(icon, self._civ_choices(),
                                   spec.get("icon_from", ""), width=30)
        self.icon_from.grid(row=2, column=1, sticky="w", **pad)
        self._refresh_slug()
        self._refresh_swatch()

    def _category(self):
        return self._category_labels.get(self.category_var.get(),
                                         DEFAULT_CATEGORY)

    def _refresh_slug(self):
        slug = city_state_slug({"name": self.name_var.get()},
                               self.app.type_prefix())
        self.slug_label.configure(text="type: " + (slug or "(type a name)"))

    def _refresh_swatch(self):
        primary, secondary = category_colors(self._category())
        self.swatch_frame.configure(background=_hex(primary))
        self.swatch.configure(background=_hex(secondary))

    # -- Suzerain bonus -------------------------------------------------------

    def _build_bonus(self, body):
        pad = {"padx": 6, "pady": 3}
        bonus = self.spec.get("bonus") or {}
        ttk.Label(body, wraplength=760, justify="left", text=(
            "What the city-state's suzerain gets: copies of existing "
            "city-states' bonuses and/or effects of its own. Write the "
            "description yourself - the game does not describe effects by "
            "itself.")).grid(row=0, column=0, columnspan=3, sticky="w",
                             pady=(0, 8))
        ttk.Label(body, text="Name").grid(row=1, column=0, sticky="w", **pad)
        self.bonus_name = tk.StringVar(value=bonus.get("name", ""))
        ttk.Entry(body, textvariable=self.bonus_name, width=40).grid(
            row=1, column=1, sticky="w", **pad)
        ttk.Label(body, text="e.g. 'Kabul Suzerain Bonus'",
                  foreground=theme.hint()).grid(row=1, column=2, sticky="w",
                                                **pad)
        ttk.Label(body, text="Description").grid(row=2, column=0,
                                                 sticky="nw", **pad)
        box, self.bonus_desc = icon_text(
            body, buttons=[("Write from effects", self.write_description,
                            WRITE_TIP)],
            height=4, width=80, wrap="word", undo=True)
        self.bonus_desc.insert("1.0", bonus.get("desc", ""))
        box.grid(row=2, column=1, columnspan=2, sticky="w", **pad)

        copies = ttk.LabelFrame(body, text="Copy the bonus of existing "
                                           "city-states", padding=(8, 4))
        copies.grid(row=3, column=0, columnspan=3, sticky="we", pady=(8, 3))
        self.clone_list = tk.Listbox(copies, height=4, width=90,
                                     activestyle="none")
        self.clone_list.grid(row=0, column=0, columnspan=3, sticky="w")
        self.clones = list(bonus.get("clone") or [])
        self.bonus_choices = self.app.data.city_state_bonus_choices()
        self.clone_combo = TypeCombo(copies, self.bonus_choices, width=70)
        self.clone_combo.grid(row=1, column=0, sticky="w", pady=4)
        ttk.Button(copies, text="Add", command=self._add_clone).grid(
            row=1, column=1, sticky="w", padx=4)
        ttk.Button(copies, text="Remove", command=self._remove_clone).grid(
            row=1, column=2, sticky="w")
        ttk.Button(copies, text="Copy its name / description into empty "
                                "fields", command=self._copy_clone_text).grid(
            row=2, column=0, sticky="w")
        if not self.bonus_choices:
            ttk.Label(copies, foreground=theme.hint(), text=(
                "(load the game cache to list the game's city-states)")
            ).grid(row=3, column=0, columnspan=3, sticky="w")
        self._refresh_clones()

        ttk.Label(body, text="Effects of its own").grid(
            row=4, column=0, columnspan=3, sticky="w", pady=(8, 2))
        self.bonus_effects = EffectsFrame(body, self.app, "suzerain",
                                          bonus.get("effects"))
        self.bonus_effects.grid(row=5, column=0, columnspan=3, sticky="we")

    def write_description(self):
        """The copied bonuses' own descriptions, then the effects."""
        known = self.app.data.city_state_bonuses()
        parts = [(known[t].get("desc") or "").replace("[NEWLINE]", "\n")
                 for t in self.clones if t in known]
        parts.append(describe_effects(self.bonus_effects.effects(),
                                      self.app.data.type_name))
        write_description(self.bonus_desc,
                          "\n".join(p for p in parts if p.strip()), self)

    def _refresh_clones(self):
        names = dict(self.bonus_choices)
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
        known = self.app.data.city_state_bonuses()
        sel = self.clone_list.curselection()
        trait = self.clones[sel[0]] if sel else \
            (self.clones[0] if self.clones else None)
        b = known.get(trait)
        if not b:
            messagebox.showinfo("No bonus text", "Add (and select) a copied "
                                "bonus first; its text comes from the game "
                                "cache.", parent=self)
            return
        if not self.bonus_name.get().strip():
            self.bonus_name.set(b["name"])
        if not self.bonus_desc.get("1.0", "end").strip():
            self.bonus_desc.insert("1.0", b["desc"].replace("[NEWLINE]",
                                                            "\n"))

    # -- Civilopedia -----------------------------------------------------------

    def _build_pedia(self, body):
        pedia = self.spec.get("pedia") or {}
        ttk.Label(body, text="History (separate paragraphs with a blank "
                             "line)").pack(anchor="w", padx=6, pady=(0, 2))
        self.history = tk.Text(body, height=18, width=86, wrap="word",
                               undo=True)
        self.history.insert("1.0", pedia.get("history", ""))
        self.history.pack(anchor="w", padx=6)

    # -- result ---------------------------------------------------------------

    def on_ok(self):
        spec = dict(self.spec)
        use_file = self.icon_mode.get() == ICON_FILE
        spec.update({
            "name": self.name_var.get().strip(),
            "adjective": self.adjective_var.get().strip(),
            "description": self.description_var.get().strip(),
            "category": self._category(),
            "icon_path": self.icon_path.get().strip() if use_file else "",
            "icon_from": "" if use_file else self.icon_from.get_type(),
            "bonus": {
                "name": self.bonus_name.get().strip(),
                "desc": self.bonus_desc.get("1.0", "end").strip(),
                "clone": list(self.clones),
                "effects": self.bonus_effects.effects()},
            "city_names": text_lines(self.city_text),
            "start_bias": self._start_bias(),
            "pedia": {"history": self.history.get("1.0", "end").strip()},
        })
        if not spec["name"]:
            messagebox.showwarning("Missing name",
                                   "Please enter the city-state's name.",
                                   parent=self)
            return
        if not spec["city_names"]:
            messagebox.showwarning("Missing city name",
                                   "Give the city-state at least one city "
                                   "name (City names tab).", parent=self)
            return
        if not (spec["bonus"]["name"] or len(spec["bonus"]["clone"]) == 1):
            messagebox.showwarning("Missing bonus name",
                                   "Give the suzerain bonus a name (or copy "
                                   "exactly one existing city-state's "
                                   "bonus to use its name).", parent=self)
            return
        self.result = spec
        self.destroy()
