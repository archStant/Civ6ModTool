"""The project's custom files (advanced mode): SQL, XML, Lua... of the
user's own, added to the mod as they are (see modbuild.check_extra_files)."""

import copy
import os

import tkinter as tk
from tkinter import filedialog, ttk

from ..modbuild import (CUSTOM_ACTIONS, CUSTOM_CRITERIA, CUSTOM_DIR,
                        new_custom_file)
from . import theme
from .widgets import HelpBox, ScrollFrame, add_tooltip, fit_to_screen

HELP = """Each file is copied into the mod's {dir} folder under its own name, and the mod's .modinfo loads it with the action chosen:

- UpdateDatabase: SQL or XML changing the game's rules (in a game: InGame; on the setup screens: FrontEnd)
- UpdateText: text (LOC_ tags), UpdateIcons: icon definitions, UpdateColors: colors
- AddGameplayScripts: a Lua script running in the game
- AddUserInterfaces: a UI (its .xml - add its .lua with ImportFiles)
- ImportFiles: any file the others use, e.g. a Lua include or a replaced UI file

The load order decides what loads after what: the generated files load at 1000 and 1001, so 1100 (the default) comes after them and can change what they add.

Effects are checked against the game data, so they cannot use types, modifiers or requirement sets that only these files add. Exports (Export...) do not carry these files.""".format(dir=CUSTOM_DIR)


class CustomFilesDialog(tk.Toplevel):
    """Edit the project's custom files ([{"path", "action", "scope",
    "load_order", "criteria"}]); the edited list is in .result after OK
    (None if cancelled)."""

    def __init__(self, parent, entries):
        super().__init__(parent)
        self.title("Custom files")
        self.transient(parent)
        self.result = None
        self.rows = []

        btns = ttk.Frame(self, padding=(10, 0, 10, 10))
        btns.pack(side="bottom", fill="x")
        top = ttk.Frame(self, padding=(10, 8, 10, 0))
        top.pack(side="top", fill="x")
        ttk.Label(top, wraplength=760, justify="left", text=(
            "Files of your own - SQL, XML, Lua... - added to the mod as "
            "they are, for what the editors cannot make.")).pack(anchor="w")
        HelpBox(top, HELP, wraplength=760).pack(anchor="w", fill="x")
        scroll = ScrollFrame(self, height=260)
        scroll.pack(fill="both", expand=True, padx=10)
        self.list = scroll.inner
        for column, text in enumerate(("File", "Action", "Where", "When",
                                       "Load order")):
            ttk.Label(self.list, text=text, foreground=theme.hint()).grid(
                row=0, column=column, sticky="w", padx=3)
        self.empty = ttk.Label(self.list, foreground=theme.hint(),
                               text="(no custom files - Add files...)")
        ttk.Button(btns, text="Add files...", command=self.on_add).pack(
            side="left")
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(
            side="right", padx=4)
        ttk.Button(btns, text="OK", command=self.on_ok).pack(side="right",
                                                             padx=4)
        for entry in entries or []:
            self.add(entry)
        self._show_empty()
        fit_to_screen(self)
        self.grab_set()
        self.bind("<Escape>", lambda e: self.destroy())

    def _show_empty(self):
        if self.rows:
            self.empty.grid_forget()
        else:
            self.empty.grid(row=1, column=0, columnspan=6, sticky="w",
                            pady=4)

    def add(self, entry):
        entry = dict(new_custom_file(), **copy.deepcopy(entry))
        r = len(self.rows) + 1
        while self.list.grid_slaves(row=r):
            r += 1
        row = {"widgets": []}
        path_var = tk.StringVar(value=entry["path"])
        path = ttk.Entry(self.list, textvariable=path_var, width=48)
        add_tooltip(path, entry["path"] or "No file")
        action = ttk.Combobox(self.list, width=20, state="readonly",
                              values=list(CUSTOM_ACTIONS))
        action.set(entry["action"])
        scope = ttk.Combobox(self.list, width=9, state="readonly",
                             values=["InGame", "FrontEnd"])
        scope.set(entry["scope"])
        when = ttk.Combobox(self.list, width=34, state="readonly",
                            values=list(CUSTOM_CRITERIA.values()))
        when.set(CUSTOM_CRITERIA.get(entry["criteria"], "Always"))
        order_var = tk.StringVar(value=str(entry["load_order"]))
        order = ttk.Entry(self.list, textvariable=order_var, width=7)
        remove = ttk.Button(self.list, text="Remove",
                            command=lambda: self._remove(row))
        for column, widget in enumerate((path, action, scope, when, order,
                                         remove)):
            widget.grid(row=r, column=column, sticky="w", padx=3, pady=2)
        criteria = {label: c for c, label in CUSTOM_CRITERIA.items()}
        row.update(widgets=[path, action, scope, when, order, remove],
                   get=lambda: {"path": path_var.get().strip(),
                                "action": action.get(),
                                "scope": scope.get(),
                                "criteria": criteria.get(when.get(), ""),
                                "load_order": _int(order_var.get())})
        self.rows.append(row)
        self._show_empty()

    def _remove(self, row):
        for widget in row["widgets"]:
            widget.destroy()
        self.rows.remove(row)
        self._show_empty()

    def on_add(self):
        paths = filedialog.askopenfilenames(
            parent=self, title="Add custom files", filetypes=[
                ("Mod files", "*.sql *.xml *.lua *.dds *.txt"),
                ("All files", "*.*")])
        for path in paths:
            self.add(new_custom_file(os.path.normpath(path)))

    def on_ok(self):
        self.result = [row["get"]() for row in self.rows]
        self.destroy()


def _int(text):
    try:
        return int(text.strip())
    except ValueError:
        return text.strip()             # (check_extra_files reports it)
