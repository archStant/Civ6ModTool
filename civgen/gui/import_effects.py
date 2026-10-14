"""Copying effects from anything in the game (advanced mode): pick a
kind of item (abilities, beliefs, buildings...), an item, and which of
its modifiers to copy into an owner's effects."""

import tkinter as tk
from tkinter import ttk

from ..gamedata import MODIFIER_SOURCES
from ..modifiers import describe_game_modifier, effect_from_game, is_raw
from . import theme
from .widgets import FilterCombo, ScrollFrame, fit_to_screen, type_label

OWNER_WORDS = {"trait": "an ability", "building": "a building",
               "district": "a district", "improvement": "an improvement",
               "unit": "a unit", "attached": "an attached effect"}


class ImportEffectsDialog(tk.Toplevel):
    """data: the GameData; owner: the owner kind the effects are for (see
    modifiers.OWNERS); name_of(kind, type): display names. .result: the
    chosen effects (see modifiers.effect_from_game) after OK, else
    None."""

    def __init__(self, parent, data, owner, name_of):
        super().__init__(parent)
        self.title("Import effects from the game")
        self.transient(parent)
        self.data, self.owner, self.name_of = data, owner, name_of
        self.result = None
        self.rows = []                  # (BooleanVar, game modifier)
        self.items = {}                 # combobox label -> type

        btns = ttk.Frame(self, padding=(10, 0, 10, 10))
        btns.pack(side="bottom", anchor="e")
        top = ttk.Frame(self, padding=(10, 8))
        top.pack(side="top", fill="x")
        ttk.Label(top, wraplength=640, justify="left",
                  foreground=theme.hint(), text=(
                      "Copies the effects of one of the game's items. An "
                      "effect acts on what owns it, so one taken from "
                      "something else (a belief, a governor title...) may "
                      "act differently on {} - check it in the game."
                      .format(OWNER_WORDS.get(owner, owner)))).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        ttk.Label(top, text="From").grid(row=1, column=0, sticky="w")
        self.sources = {spec[3]: source
                        for source, spec in MODIFIER_SOURCES.items()}
        self.source_var = tk.StringVar(value=next(iter(self.sources)))
        source = ttk.Combobox(top, textvariable=self.source_var, width=40,
                              state="readonly", values=list(self.sources))
        source.grid(row=1, column=1, sticky="w", padx=6, pady=3)
        source.bind("<<ComboboxSelected>>", lambda e: self._load_items())
        ttk.Label(top, text="Item").grid(row=2, column=0, sticky="w")
        self.item_combo = FilterCombo(top, width=64)
        self.item_combo.grid(row=2, column=1, sticky="w", padx=6, pady=3)
        self.item_combo.bind("<<ComboboxSelected>>", lambda e: self._show())
        self.item_combo.bind("<Return>", lambda e: self._show())

        scroll = ScrollFrame(self, height=320)
        scroll.pack(fill="both", expand=True, padx=10)
        self.list = scroll.inner
        ttk.Button(btns, text="OK", command=self.on_ok).pack(side="left",
                                                             padx=4)
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(
            side="left", padx=4)
        self._load_items()
        fit_to_screen(self)
        self.grab_set()
        self.bind("<Escape>", lambda e: self.destroy())

    def _source(self):
        return self.sources[self.source_var.get()]

    def _load_items(self):
        self.items = {type_label(t, name): t for t, name in
                      self.data.source_items(self._source())}
        self.item_combo.set_choices(list(self.items))
        self.item_combo.var.set("")
        self._show()

    def _show(self):
        for widget in self.list.winfo_children():
            widget.destroy()
        self.rows = []
        text = self.item_combo.value()
        item = self.items.get(text) or text.upper()
        if not item:
            ttk.Label(self.list, foreground=theme.hint(),
                      text="Pick an item to see its effects.").pack(
                anchor="w")
            return
        mods = self.data.game_modifiers(self._source(), item)
        if not mods:
            ttk.Label(self.list, foreground=theme.hint(),
                      text="It has no effects of its own.").pack(anchor="w")
            return
        for mod in mods:
            var = tk.BooleanVar(value=True)
            row = ttk.Frame(self.list)
            row.pack(anchor="w", fill="x", pady=1)
            ttk.Checkbutton(row, variable=var).pack(side="left", anchor="n")
            effect = effect_from_game(mod, self.owner)
            ttk.Label(row, foreground=theme.hint(), width=14, anchor="nw",
                      text="game modifier" if is_raw(effect)
                      else "from the list").pack(side="left", anchor="n")
            ttk.Label(row, wraplength=520, justify="left",
                      text=describe_game_modifier(
                          mod, self.name_of, self.data.read_modifier)).pack(
                side="left")
            self.rows.append((var, mod))

    def on_ok(self):
        self.result = [effect_from_game(mod, self.owner)
                       for var, mod in self.rows if var.get()]
        self.destroy()
