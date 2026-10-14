"""Editing effects (modifiers): a list of an owner's effects and the dialog
that edits one of them (see modifiers.py). Advanced mode (the toolbar's
switch) adds the game's own modifier and requirement types, groups of
requirements and effects copied from anything in the game."""

import copy

import tkinter as tk
from tkinter import messagebox, ttk

from ..gamedata import GameData
from ..modifiers import (ENUMS, KIND_LISTS, TEMPLATES, check_effect,
                         effect_warnings, is_advanced, is_raw, new_effect,
                         summary, templates_for)
from . import theme
from .effect_parts import RawEffectFrame, RequirementsFrame
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
    "attached": "The effect another effect attaches: it is given to each "
                "of what that one applies to (its players, cities, "
                "units...), and applies to it.",
}
RAW_HINT = ("Any of the game's modifier types, with the arguments the game "
            "gives it (picked from its own uses), applied as it is to its "
            "owner - a unit effect is not given to the player's units "
            "here: attach it to them instead.")
ADVANCED_ONLY = ("This effect uses advanced features - turn on Advanced "
                 "mode in the toolbar to edit it.")
# keys only raw effects have (dropped when one becomes a template's)
RAW_KEYS = ("modifier_type", "run_once", "permanent", "text", "attached",
            "arg_types", "columns", "strings")


def template_label(t):
    return "{} - {}".format(t.category, t.label)


def value_widget(parent, kind, value, choices, changed, width=36):
    """(widget, getter) for a value of an argument / condition kind (an
    ENUMS or KIND_LISTS key; anything else is typed in). choices(kind):
    [(type, name)] of a GameData list; changed(): called on each edit."""
    if kind in ENUMS:
        labels = dict(ENUMS[kind])
        var = tk.StringVar(value=labels.get(value, value))
        widget = ttk.Combobox(parent, textvariable=var, width=width,
                              state="readonly",
                              values=[label for _, label in ENUMS[kind]])
        back = {label: v for v, label in ENUMS[kind]}
        widget.bind("<<ComboboxSelected>>", lambda e: changed())
        return widget, lambda: back.get(var.get(), var.get())
    if kind in KIND_LISTS:
        widget = TypeCombo(parent, choices(KIND_LISTS[kind]), value,
                           width=width)
        widget.var.trace_add("write", lambda *_: changed())
        return widget, widget.get_type
    var = tk.StringVar(value=value)
    var.trace_add("write", lambda *_: changed())
    widget = ttk.Entry(parent, textvariable=var,
                       width=10 if kind in ("int", "number") else width)
    return widget, lambda: var.get().strip()


class EffectDialog(tk.Toplevel):
    """Edit one effect. owner: "trait", "building", "district", "unit"
    (or "attached": the effect another one attaches); choices(kind) gives
    [(type, name)] for a GameData list kind; data: the GameData (the
    game's modifier types, for advanced mode). advanced: also edit raw
    effects and requirements (an effect that needs it opens so anyway).
    The edited effect is in .result after OK (None if cancelled); keys the
    dialog does not edit are kept."""

    def __init__(self, parent, owner, effect, choices, name_of, data=None,
                 advanced=False, depth=0):
        super().__init__(parent)
        self.title("Attached effect" if owner == "attached" else "Effect")
        self.resizable(False, False)
        self.transient(parent)
        self.owner, self.choices, self.name_of = owner, choices, name_of
        self.data = data if data is not None else GameData()
        self.depth = depth
        self.result = None
        self._ready = False
        self.base = copy.deepcopy(effect)
        # (never edit an advanced effect with the basic editor: it would
        # drop what it cannot show)
        self.advanced = advanced or is_advanced(self.base)
        raw = is_raw(self.base)
        self.values = {} if raw else dict(self.base.get("args") or {})
        self.templates = templates_for(owner)
        template = self.base.get("template")
        if template not in [t.id for t in self.templates]:
            template = self.templates[0].id     # not usable here
        self.mode = tk.StringVar(value="raw" if raw else "template")

        # OK / Cancel first: they keep their place on a small screen
        btns = ttk.Frame(self, padding=(10, 0, 10, 10))
        btns.pack(side="bottom", anchor="e")
        scroll = ScrollFrame(self, height=None)
        scroll.pack(fill="both", expand=True)
        body = scroll.inner
        ttk.Label(body, text=OWNER_HINTS[owner], wraplength=560,
                  justify="left", foreground=theme.hint()).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        if self.advanced:
            modes = ttk.Frame(body)
            modes.grid(row=1, column=0, columnspan=2, sticky="w",
                       pady=(0, 6))
            ttk.Radiobutton(modes, text="From the list", value="template",
                            variable=self.mode,
                            command=self._show_mode).pack(side="left")
            ttk.Radiobutton(modes, text="Any game modifier", value="raw",
                            variable=self.mode,
                            command=self._show_mode).pack(side="left",
                                                          padx=12)

        self.template_frame = ttk.Frame(body)
        self.template_frame.grid(row=2, column=0, columnspan=2, sticky="w")
        ttk.Label(self.template_frame, text="Effect").grid(row=0, column=0,
                                                           sticky="w")
        self.template_var = tk.StringVar(value=template_label(
            TEMPLATES[template]))
        combo = ttk.Combobox(self.template_frame,
                             textvariable=self.template_var, width=56,
                             state="readonly", values=[
                                 template_label(t) for t in self.templates])
        combo.grid(row=0, column=1, sticky="w", padx=6, pady=3)
        combo.bind("<<ComboboxSelected>>", lambda e: self._build_args())
        self.help = ttk.Label(self.template_frame, wraplength=520,
                              justify="left", foreground=theme.hint())
        self.help.grid(row=1, column=1, sticky="w", padx=6)
        self.args_frame = ttk.Frame(self.template_frame)
        self.args_frame.grid(row=2, column=0, columnspan=2, sticky="w",
                             pady=(6, 0))

        self.raw_frame = ttk.Frame(body)
        self.raw_frame.grid(row=3, column=0, columnspan=2, sticky="w")
        if self.advanced:
            ttk.Label(self.raw_frame, text=RAW_HINT, wraplength=560,
                      justify="left", foreground=theme.hint()).pack(
                anchor="w", pady=(0, 6))
            self.raw = RawEffectFrame(self.raw_frame, self,
                                      self.base if raw else {})
            self.raw.pack(anchor="w", fill="x")

        self.reqs = RequirementsFrame(body, self, self.base.get("reqs"),
                                      self.base.get("set_types"),
                                      self.advanced)
        self.reqs.grid(row=4, column=0, columnspan=2, sticky="we",
                       pady=(10, 0))

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
        self._show_mode()
        self._ready = True
        self.refresh()
        fit_to_screen(self)
        self.grab_set()
        self.bind("<Escape>", lambda e: self.destroy())

    # -- template and arguments -------------------------------------------

    def template(self):
        label = self.template_var.get()
        return next(t for t in self.templates if template_label(t) == label)

    def value_widget(self, parent, kind, value, width=36):
        return value_widget(parent, kind, value, self.choices, self.refresh,
                            width)

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
            widget, getter = self.value_widget(
                self.args_frame, a.kind, self.values.get(a.name, a.default),
                width=56 if a.kind == "text" else 36)
            widget.grid(row=row, column=1, sticky="w", pady=2)
            self.arg_widgets[a.name] = getter
            row += 1
        self._offer_requirements()
        self.refresh()

    def _store_args(self):
        for name, getter in getattr(self, "arg_widgets", {}).items():
            self.values[name] = getter()

    # -- raw / template ---------------------------------------------------

    def _show_mode(self):
        raw = self.mode.get() == "raw"
        if raw:
            self.template_frame.grid_remove()
            self.raw_frame.grid()
            if not self.raw.modifier_type():
                # start from the template's modifier and arguments
                self._store_args()
                t = self.template()
                self.raw.set_from(t.modifier_type, {
                    a.name: a.default if a.kind == "fixed" else
                    self.values.get(a.name, a.default)
                    for a in t.args if a.kind != "text"},
                    t.run_once, t.permanent)
        else:
            self.raw_frame.grid_remove()
            self.template_frame.grid()
        self._offer_requirements()
        self.refresh()

    def targets(self):
        """The requirement sets of the effect being edited: what it
        applies to, its owner, and for a template's unit effect from
        another owner, which units get it."""
        out = ["subject", "owner"]
        if self.mode.get() == "template" and \
                self.template().scope == "unit" and \
                self.owner not in ("unit", "attached"):
            out.append("units")
        return out

    def _offer_requirements(self):
        if not hasattr(self, "reqs"):
            return
        if self.mode.get() == "raw" or self.owner == "attached":
            presets = list(dict.fromkeys(OTHER_PRESETS + UNIT_PRESETS))
        else:
            presets = UNIT_PRESETS if self.template().scope == "unit" \
                else OTHER_PRESETS
        self.reqs.set_presets(presets)
        self.reqs.set_targets(self.targets())

    # -- result ---------------------------------------------------------------

    def effect(self):
        out = copy.deepcopy(self.base)
        if self.mode.get() == "raw":
            out.pop("template", None)
            out.update(self.raw.values())
            for key in ("attached", "text"):
                if not out.get(key):
                    out.pop(key, None)
        else:
            for key in RAW_KEYS:
                out.pop(key, None)
            self._store_args()
            t = self.template()
            out["template"] = t.id
            out["args"] = {a.name: self.values.get(a.name, a.default)
                           for a in t.args}
        out["reqs"], set_types = self.reqs.values()
        if set_types:
            out["set_types"] = set_types
        else:
            out.pop("set_types", None)
        return out

    def refresh(self):
        """Show the summary of the effect as edited."""
        if not self._ready:
            return
        try:
            text = summary(self.effect(), self.name_of)
        except (AttributeError, KeyError, ValueError, IndexError,
                StopIteration):
            text = ""
        self.summary.configure(text=text)

    def on_ok(self):
        effect = self.effect()
        try:
            check_effect(effect, self.owner, self.data, self.depth)
        except ValueError as exc:
            messagebox.showwarning("Incomplete effect", str(exc), parent=self)
            return
        warnings = effect_warnings(effect, self.owner, self.data)
        if warnings and not messagebox.askokcancel(
                "Check the effect", "This effect may not work as meant:\n\n"
                "{}\n\nKeep it anyway?".format("\n".join(
                    "- " + w for w in warnings)), parent=self):
            return
        self.result = effect
        self.destroy()


class EffectsFrame(ttk.Frame):
    """The effects of one owner (an ability, unique unit, building or
    district) as a list with Add / Edit / Duplicate / Remove (and, in
    advanced mode, Import from game). extra(kind) gives types to offer on
    top of the game's (e.g. the project's own uniques)."""

    def __init__(self, parent, app, owner, effects, extra=lambda kind: []):
        super().__init__(parent)
        self.app, self.owner, self.extra = app, owner, extra
        # (dialogs are modal: the mode cannot change while one is open)
        self.advanced = bool(app.advanced_var.get()) \
            if hasattr(app, "advanced_var") else False
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
        if self.advanced:
            ttk.Button(btns, text="Import from game...",
                       command=self.on_import,
                       state="normal" if app.data.conn else "disabled").pack(
                fill="x", pady=(10, 2))
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
            text = summary(effect, self.name_of)
            if is_advanced(effect):
                text = "(advanced) " + text
            self.listbox.insert("end", text)
        if not self.items:
            self.listbox.insert("end", "(no effects - Add... to give it some)")

    def _selected(self):
        sel = self.listbox.curselection()
        return sel[0] if sel and self.items else None

    def _dialog(self, effect):
        dialog = EffectDialog(self.winfo_toplevel(), self.owner, effect,
                              self.choices, self.name_of, self.app.data,
                              self.advanced)
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
        if is_advanced(self.items[i]) and not self.advanced:
            messagebox.showinfo("Advanced effect", ADVANCED_ONLY,
                                parent=self.winfo_toplevel())
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

    def on_import(self):
        from .import_effects import ImportEffectsDialog
        dialog = ImportEffectsDialog(self.winfo_toplevel(), self.app.data,
                                     self.owner, self.name_of)
        self.wait_window(dialog)
        self.winfo_toplevel().grab_set()
        if dialog.result:
            self.items += dialog.result
            self.refresh()

    def effects(self):
        return copy.deepcopy(self.items)
