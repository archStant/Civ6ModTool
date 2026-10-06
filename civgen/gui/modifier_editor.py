"""Editing effects (modifiers): a list of an owner's effects and the dialog
that edits one of them (see modifiers.py)."""

import copy

import tkinter as tk
from tkinter import messagebox, ttk

from ..modifiers import (ENUMS, KIND_LISTS, REQUIREMENTS, TEMPLATES,
                         check_effect, new_effect, summary, templates_for)
from . import theme
from .widgets import ScrollFrame
from .widgets import fit_to_screen
from .widgets import TypeCombo


# Conditions offered for an effect's scope ("unit" effects vs the rest)
UNIT_PRESETS = ("unit_class", "unit_type", "unit_domain", "opponent_class",
                "attacking", "own_territory", "enemy_territory", "has_tech",
                "has_civic", "era")
OTHER_PRESETS = ("city_district", "city_building", "district_is",
                 "plot_terrain", "plot_feature", "plot_improvement",
                 "plot_resource", "plot_river", "plot_hills", "plot_coastal",
                 "has_tech", "has_civic", "era")

OWNER_HINTS = {
    "trait": "Effects of an ability apply to the whole civilization. Unit "
             "effects are given to the player's units; add a 'Unit class "
             "is' / 'Unit is' condition to pick which.",
    "building": "Effects of a building apply once it is built: city "
                "effects to its city, the others to the whole "
                "civilization.",
    "district": "Effects of a district apply once it is built: city effects "
                "to its city, the others to the whole civilization.",
    "improvement": "Effects of an improvement apply while it stands (not "
                   "pillaged), to the whole civilization - one more for "
                   "each improvement built. Unit effects are given to the "
                   "player's units. Its own tile's yields are on the Stats "
                   "tab.",
    "unit": "Effects of a unique unit apply to that unit only.",
}


def template_label(t):
    return "{} - {}".format(t.category, t.label)


class EffectDialog(tk.Toplevel):
    """Edit one effect. owner: "trait", "building", "district" or "unit";
    choices(kind) gives [(type, name)] for a GameData list kind. The
    edited effect is in .result after OK (None if cancelled)."""

    def __init__(self, parent, owner, effect, choices, name_of):
        super().__init__(parent)
        self.title("Effect")
        self.resizable(False, False)
        self.transient(parent)
        self.owner, self.choices, self.name_of = owner, choices, name_of
        self.result = None
        effect = copy.deepcopy(effect)
        self.values = dict(effect.get("args") or {})   # kept across templates
        self.templates = templates_for(owner)
        if effect.get("template") not in [t.id for t in self.templates]:
            effect["template"] = self.templates[0].id   # not usable here

        # OK / Cancel first: they keep their place on a small screen
        btns = ttk.Frame(self, padding=(10, 0, 10, 10))
        btns.pack(side="bottom", anchor="e")
        scroll = ScrollFrame(self, height=None)
        scroll.pack(fill="both", expand=True)
        body = scroll.inner
        ttk.Label(body, text=OWNER_HINTS[owner], wraplength=560,
                  justify="left", foreground=theme.hint()).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        ttk.Label(body, text="Effect").grid(row=1, column=0, sticky="w")
        self.template_var = tk.StringVar(value=template_label(
            TEMPLATES[effect["template"]]))
        combo = ttk.Combobox(body, textvariable=self.template_var, width=56,
                             state="readonly", values=[
                                 template_label(t) for t in self.templates])
        combo.grid(row=1, column=1, sticky="w", padx=6, pady=3)
        combo.bind("<<ComboboxSelected>>", lambda e: self._build_args())
        self.help = ttk.Label(body, wraplength=520, justify="left",
                              foreground=theme.hint())
        self.help.grid(row=2, column=1, sticky="w", padx=6)
        self.args_frame = ttk.Frame(body)
        self.args_frame.grid(row=3, column=0, columnspan=2, sticky="w",
                             pady=(6, 0))

        reqs = ttk.LabelFrame(body, text="Only when (all of these)",
                              padding=(8, 4))
        reqs.grid(row=4, column=0, columnspan=2, sticky="we", pady=(10, 0))
        self.req_list = ttk.Frame(reqs)
        self.req_list.pack(anchor="w", fill="x")
        add = ttk.Frame(reqs)
        add.pack(anchor="w", pady=(4, 0))
        self.preset_var = tk.StringVar()
        self.preset_combo = ttk.Combobox(add, textvariable=self.preset_var,
                                         width=36, state="readonly")
        self.preset_combo.pack(side="left")
        ttk.Button(add, text="Add condition",
                   command=self._add_selected_req).pack(side="left", padx=6)
        self.req_rows = []

        self.summary = ttk.Label(body, wraplength=560, justify="left",
                                 font=("TkDefaultFont", 9, "italic"))
        self.summary.grid(row=5, column=0, columnspan=2, sticky="w",
                          pady=(10, 0))

        ttk.Button(btns, text="OK", command=self.on_ok).pack(side="left",
                                                             padx=4)
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(
            side="left", padx=4)

        self.arg_widgets = {}
        self._build_args()
        for req in effect.get("reqs") or []:
            if req.get("preset") in REQUIREMENTS:
                self._add_req(req)
        self._refresh_summary()
        fit_to_screen(self)
        self.grab_set()
        self.bind("<Escape>", lambda e: self.destroy())

    # -- template and arguments -------------------------------------------

    def template(self):
        label = self.template_var.get()
        return next(t for t in self.templates if template_label(t) == label)

    def _value_widget(self, parent, kind, value, width=36):
        """(widget, getter) for a value of an argument / condition kind."""
        if kind in ENUMS:
            labels = dict(ENUMS[kind])
            var = tk.StringVar(value=labels.get(value, value))
            widget = ttk.Combobox(parent, textvariable=var, width=width,
                                  state="readonly",
                                  values=[label for _, label in ENUMS[kind]])
            back = {label: v for v, label in ENUMS[kind]}
            widget.bind("<<ComboboxSelected>>",
                        lambda e: self._refresh_summary())
            return widget, lambda: back.get(var.get(), var.get())
        if kind in KIND_LISTS:
            widget = TypeCombo(parent, self.choices(KIND_LISTS[kind]), value,
                               width=width)
            widget.var.trace_add("write", lambda *_: self._refresh_summary())
            return widget, widget.get_type
        var = tk.StringVar(value=value)
        var.trace_add("write", lambda *_: self._refresh_summary())
        widget = ttk.Entry(parent, textvariable=var,
                           width=10 if kind in ("int", "number") else width)
        return widget, lambda: var.get().strip()

    def _build_args(self):
        self._store_args()
        for widget in self.args_frame.winfo_children():
            widget.destroy()
        self.arg_widgets = {}
        t = self.template()
        self.help.configure(text=t.help)
        row = 0
        for a in t.args:
            if a.kind == "fixed":
                continue
            ttk.Label(self.args_frame, text=a.label).grid(
                row=row, column=0, sticky="w", padx=(0, 6), pady=2)
            widget, getter = self._value_widget(
                self.args_frame, a.kind, self.values.get(a.name, a.default),
                width=56 if a.kind == "text" else 36)
            widget.grid(row=row, column=1, sticky="w", pady=2)
            self.arg_widgets[a.name] = getter
            row += 1
        allowed = UNIT_PRESETS if t.scope == "unit" else OTHER_PRESETS
        self.preset_combo["values"] = [REQUIREMENTS[p].label
                                       for p in allowed]
        self._refresh_summary()

    def _store_args(self):
        for name, getter in getattr(self, "arg_widgets", {}).items():
            self.values[name] = getter()

    # -- conditions ---------------------------------------------------------

    def _add_selected_req(self):
        label = self.preset_var.get()
        preset = next((p for p in REQUIREMENTS.values() if p.label == label),
                      None)
        if preset:
            self._add_req({"preset": preset.id, "value": ""})

    def _add_req(self, req):
        p = REQUIREMENTS[req["preset"]]
        frame = ttk.Frame(self.req_list)
        frame.pack(anchor="w", pady=2)
        row = {"frame": frame, "preset": p.id,
               "not": tk.BooleanVar(value=bool(req.get("not")))}
        ttk.Checkbutton(frame, text="not", variable=row["not"],
                        command=self._refresh_summary).pack(side="left")
        ttk.Label(frame, text=p.label, width=26).pack(side="left", padx=4)
        if p.arg:
            widget, row["value"] = self._value_widget(frame, p.kind,
                                                      req.get("value") or "")
            widget.pack(side="left")
        else:
            row["value"] = lambda: ""
        ttk.Button(frame, text="Remove",
                   command=lambda: self._remove_req(row)).pack(side="left",
                                                               padx=6)
        self.req_rows.append(row)
        self._refresh_summary()

    def _remove_req(self, row):
        row["frame"].destroy()
        self.req_rows.remove(row)
        self._refresh_summary()

    # -- result ---------------------------------------------------------------

    def effect(self):
        self._store_args()
        t = self.template()
        return {"template": t.id,
                "args": {a.name: self.values.get(a.name, a.default)
                         for a in t.args},
                "reqs": [{"preset": r["preset"], "value": r["value"](),
                          "not": bool(r["not"].get())}
                         for r in self.req_rows]}

    def _refresh_summary(self):
        if not hasattr(self, "summary"):
            return
        try:
            text = summary(self.effect(), self.name_of)
        except (KeyError, ValueError, IndexError):
            text = ""
        self.summary.configure(text=text)

    def on_ok(self):
        effect = self.effect()
        try:
            check_effect(effect, self.owner)
        except ValueError as exc:
            messagebox.showwarning("Incomplete effect", str(exc), parent=self)
            return
        self.result = effect
        self.destroy()


class EffectsFrame(ttk.Frame):
    """The effects of one owner (an ability, unique unit, building or
    district) as a list with Add / Edit / Duplicate / Remove. extra(kind)
    gives types to offer on top of the game's (e.g. the project's own
    uniques)."""

    def __init__(self, parent, app, owner, effects, extra=lambda kind: []):
        super().__init__(parent)
        self.app, self.owner, self.extra = app, owner, extra
        self.items = copy.deepcopy(list(effects or []))
        box = ttk.Frame(self)
        box.pack(side="left", fill="both", expand=True)
        self.listbox = tk.Listbox(box, height=8, width=90,
                                  activestyle="none")
        bar = ttk.Scrollbar(box, orient="vertical",
                            command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=bar.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        bar.pack(side="left", fill="y")
        self.listbox.bind("<Double-1>", lambda e: self.on_edit())
        btns = ttk.Frame(self)
        btns.pack(side="left", anchor="n", padx=(8, 0))
        for text, cmd in (("Add...", self.on_add), ("Edit...", self.on_edit),
                          ("Duplicate", self.on_duplicate),
                          ("Remove", self.on_remove)):
            ttk.Button(btns, text=text, command=cmd).pack(fill="x", pady=2)
        self.refresh()

    def choices(self, kind):
        extra = list(self.extra(kind))
        known = {t for t, _ in extra}
        return extra + [c for c in self.app.data.type_choices(kind)
                        if c[0] not in known]

    def name_of(self, kind, type_name):
        for t, name in self.extra(kind):
            if t == type_name:
                return name
        return self.app.data.type_name(kind, type_name)

    def refresh(self):
        self.listbox.delete(0, "end")
        for effect in self.items:
            self.listbox.insert("end", summary(effect, self.name_of))
        if not self.items:
            self.listbox.insert("end", "(no effects - Add... to give it some)")

    def _selected(self):
        sel = self.listbox.curselection()
        return sel[0] if sel and self.items else None

    def _dialog(self, effect):
        dialog = EffectDialog(self.winfo_toplevel(), self.owner, effect,
                              self.choices, self.name_of)
        self.wait_window(dialog)
        self.winfo_toplevel().grab_set()        # the dialog took the grab
        return dialog.result

    def on_add(self):
        first = templates_for(self.owner)[0]
        result = self._dialog(new_effect(first.id))
        if result:
            self.items.append(result)
            self.refresh()

    def on_edit(self):
        i = self._selected()
        if i is None:
            return
        result = self._dialog(self.items[i])
        if result:
            self.items[i] = result
            self.refresh()

    def on_duplicate(self):
        i = self._selected()
        if i is not None:
            self.items.insert(i + 1, copy.deepcopy(self.items[i]))
            self.refresh()

    def on_remove(self):
        i = self._selected()
        if i is not None:
            del self.items[i]
            self.refresh()

    def effects(self):
        return copy.deepcopy(self.items)
