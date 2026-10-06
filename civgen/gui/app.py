"""The main application window."""

import copy
import os
import pickle
import shutil
import sqlite3
import subprocess
import sys
import uuid
import zipfile

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from ..util import (asset_path, clean_prefix, default_out_dir,
                    find_game_cache, safe_folder_name, slug_for_name)
from ..gamedata import FALLBACK_DATA, GameData
from ..art import (APP_ICON, COOKER_EXE, LIST_ICON_SIZE, find_cooker,
                   fit_icon_crop)
from ..leaders import (CUSTOM_MARKS, leader_custom_marks, leader_icon_preview,
                       needs_art, new_leader_spec)
from ..civs import civ_icon_preview, civ_slug, new_civ_spec
from ..uniques import KINDS, MAIN_TABLES
from ..modbuild import prepare_project, write_mod
from ..moments import move_to_civs as move_moments_to_civs
from ..project import (PROJECT_MAGIC, PROJECT_VERSION, export_leaders,
                       import_leaders)
from .widgets import BusyDialog, Tooltip
from .leader_editor import LeaderEditor
from .civ_editor import CivEditor


# ---------------------------------------------------------------------------
# Main application window
# ---------------------------------------------------------------------------

class GeneratorApp(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("Civ 6 Mod Generator - civilizations and leaders")
        self.minsize(760, 520)
        self._set_window_icon()

        self.data = GameData()
        self.project = self._empty_project()
        self.project_path = None
        self._saved_state = None

        self._build_widgets()
        self._refresh_lists()
        self._mark_saved()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _set_window_icon(self):
        """assets/icon.png as the icon of this and every other window."""
        path = asset_path(APP_ICON)
        if not path:
            return
        try:
            from PIL import Image, ImageTk
            src = Image.open(path).convert("RGBA")
            self._icons = [ImageTk.PhotoImage(src.resize((s, s),
                                                         Image.LANCZOS))
                           for s in (256, 64, 48, 32, 16)]
        except ImportError:             # Tk 8.6 reads PNG by itself
            self._icons = [tk.PhotoImage(file=path)]
        except Exception:               # unreadable image: keep Tk's icon
            return
        self.iconphoto(True, *self._icons)

    # -- project helpers ----------------------------------------------------

    @staticmethod
    def _empty_project():
        return {
            "mod_name": "Alternate Leaders",
            "prefix": "",
            "output_dir": default_out_dir(),
            "guid": str(uuid.uuid4()),
            "leaders": [],
            "civs": [],
        }

    def type_prefix(self):
        """The project-wide type prefix (cleaned), e.g. 'RFVS'."""
        return clean_prefix(self.prefix_var.get())

    # -- data lookups ---------------------------------------------------------

    def all_civs(self):
        """The project's civilizations, then the game's."""
        return list(self.project_civs()) + sorted(
            set(self.data.civ_to_leaders) | set(FALLBACK_DATA))

    def project_civs(self):
        """{type: spec} of the project's civilizations (types follow the
        current name and prefix)."""
        return {civ_slug(spec, self.type_prefix()): spec
                for spec in self.project["civs"]}

    def project_civ_uniques(self, civ_type):
        """Types of a project civilization's uniques, or None if civ_type
        is not one of the project's civilizations."""
        spec = self.project_civs().get(civ_type)
        if spec is None:
            return None
        out = []
        for u in spec.get("uniques") or []:
            word = MAIN_TABLES[u["kind"]][1][:-len("Type")].upper()
            out.append(slug_for_name(u.get("name"), self.type_prefix(),
                                     kind=word))
        return [t for t in out if t]

    def resolve_civ(self, spec):
        """A leader spec's civilization type: a project civilization's
        current type (by civ_id), or the civ field."""
        for civ_type, civ in self.project_civs().items():
            if spec.get("civ_id") and civ.get("id") == spec.get("civ_id"):
                return civ_type
        return spec.get("civ", "")

    def _link_civ(self, spec):
        """Remember which project civilization (if any) a leader leads, so
        renaming it keeps the leader."""
        civ = self.project_civs().get((spec.get("civ") or "").strip())
        if civ is not None:
            spec["civ_id"] = civ.get("id")
        else:
            spec.pop("civ_id", None)
        return spec

    def all_leaders(self):
        return sorted({l for src in (self.data.civ_to_leaders, FALLBACK_DATA)
                       for leaders in src.values() for l in leaders})

    def leaders_for_civ(self, civ):
        for src in (self.data.civ_to_leaders, FALLBACK_DATA):
            if civ in src:
                return sorted(set(src[civ]))
        return self.all_leaders()

    # -- widget construction ---------------------------------------------------

    def _build_widgets(self):
        pad = {"padx": 6, "pady": 3}
        top = ttk.Frame(self, padding=10)
        top.pack(fill="both", expand=True)

        # -- project row
        ttk.Label(top, text="Project:").grid(row=0, column=0, sticky="w",
                                             **pad)
        ttk.Button(top, text="New", command=self.on_new_project).grid(
            row=0, column=1, sticky="w", **pad)
        ttk.Button(top, text="Open...", command=self.on_open_project).grid(
            row=0, column=2, sticky="w", **pad)
        self.save_btn = ttk.Button(top, text="Save...",
                                   command=self.on_save_project)
        self.save_btn.grid(row=0, column=3, sticky="w", **pad)
        self.project_label = ttk.Label(top, text="(unsaved)")
        self.project_label.grid(row=0, column=4, sticky="w", **pad)

        # -- game cache row
        ttk.Label(top, text="Game data:").grid(row=1, column=0, sticky="w",
                                               **pad)
        ttk.Button(top, text="Load from game cache...",
                   command=self.on_load_cache).grid(row=1, column=1,
                                                    columnspan=2,
                                                    sticky="w", **pad)
        self.cache_label = ttk.Label(top, text="using built-in list")
        self.cache_label.grid(row=1, column=3, columnspan=2, sticky="w",
                              **pad)

        # -- mod name row
        ttk.Label(top, text="Mod name:").grid(row=2, column=0, sticky="w",
                                              **pad)
        self.mod_name_var = tk.StringVar(
            value=self.project["mod_name"])
        ttk.Entry(top, textvariable=self.mod_name_var, width=32).grid(
            row=2, column=1, columnspan=2, sticky="w", **pad)
        prefix_row = ttk.Frame(top)
        prefix_row.grid(row=2, column=3, columnspan=2, sticky="w", **pad)
        ttk.Label(prefix_row, text="Type prefix:").pack(side="left")
        self.prefix_var = tk.StringVar(value=self.project.get("prefix", ""))
        ttk.Entry(prefix_row, textvariable=self.prefix_var, width=10).pack(
            side="left", padx=(6, 6))
        self.prefix_hint = ttk.Label(prefix_row, text="")
        self.prefix_hint.pack(side="left")
        self.prefix_var.trace_add("write", lambda *_: self.prefix_hint.config(
            text="-> " + slug_for_name("Name", self.type_prefix())))
        self.prefix_var.set(self.prefix_var.get())   # show the hint

        # -- leaders and civilizations, one tab each
        notebook = ttk.Notebook(top)
        notebook.grid(row=3, column=0, columnspan=5, sticky="nsew", **pad)
        leader_tab = ttk.Frame(notebook, padding=6)
        civ_tab = ttk.Frame(notebook, padding=6)
        notebook.add(leader_tab, text="Leaders")
        notebook.add(civ_tab, text="Civilizations")
        leader_tab.columnconfigure(0, weight=1)
        leader_tab.rowconfigure(0, weight=1)
        self._build_civ_tab(civ_tab)

        # -- leader list
        # tall rows so each leader's icon fits next to their name
        ttk.Style(self).configure("Leaders.Treeview",
                                  rowheight=LIST_ICON_SIZE + 8)
        list_frame = ttk.Frame(leader_tab)
        list_frame.grid(row=0, column=0, sticky="nsew")
        self.tree = ttk.Treeview(list_frame, columns=("civ", "orig", "icon"),
                                  show="tree headings", height=8,
                                  selectmode="extended",
                                  style="Leaders.Treeview")
        self.tree_scroll = ttk.Scrollbar(list_frame, orient="vertical",
                                         command=self.tree.yview)
        self.tree.configure(yscrollcommand=self._on_tree_scrolled)
        # "3 leaders" / "Showing 1-8 of 12 leaders - scroll for more"
        self.list_hint = ttk.Label(list_frame, text="")
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree_scroll.grid(row=0, column=1, sticky="ns")
        self.list_hint.grid(row=1, column=0, columnspan=2, sticky="w",
                            pady=(3, 0))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        self.tree.heading("#0", text="Leader")
        self.tree.column("#0", width=230)
        self.tree.heading("civ", text="Civilization")
        self.tree.column("civ", width=180)
        self.tree.heading("orig", text="Inherits from")
        self.tree.column("orig", width=160)
        self.tree.heading("icon", text="Custom")
        self.tree.column("icon", width=140, anchor="w")
        ttk.Label(list_frame, foreground="gray", text="   ".join(
            "{} {}".format(symbol, what) for symbol, what in CUSTOM_MARKS)
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(3, 0))
        self.tree_tip = Tooltip(self.tree)
        self.tree.bind("<Motion>", self._on_tree_motion)
        self.tree.bind("<Leave>", lambda e: self.tree_tip.hide())
        self.tree.bind("<Double-1>", lambda e: self.on_edit_leader())

        btns = ttk.Frame(leader_tab)
        btns.grid(row=0, column=1, sticky="n", padx=(8, 0))
        for text, cmd in (("Add...", self.on_add_leader),
                          ("Edit...", self.on_edit_leader),
                          ("Duplicate", self.on_duplicate_leader),
                          ("Remove", self.on_remove_leader)):
            ttk.Button(btns, text=text, command=cmd).pack(fill="x", pady=2)
        ttk.Separator(btns).pack(fill="x", pady=6)
        for text, cmd in (("Export...", self.on_export_leaders),
                          ("Import...", self.on_import_leaders)):
            ttk.Button(btns, text=text, command=cmd).pack(fill="x", pady=2)

        # -- output folder row
        ttk.Label(top, text="Output folder:").grid(row=4, column=0,
                                                   sticky="w", **pad)
        self.out_var = tk.StringVar(value=self.project["output_dir"])
        ttk.Entry(top, textvariable=self.out_var, width=44).grid(
            row=4, column=1, columnspan=3, sticky="w", **pad)
        ttk.Button(top, text="Browse...", command=self.on_browse_out).grid(
            row=4, column=4, sticky="w", **pad)

        # -- generate
        self.generate_btn = ttk.Button(top, text="Generate mod",
                                        command=self.on_generate)
        self.generate_btn.grid(row=5, column=0, sticky="w", padx=6, pady=10)

        top.columnconfigure(0, weight=0)
        top.columnconfigure(1, weight=1)
        top.rowconfigure(3, weight=1)

        for var in (self.mod_name_var, self.prefix_var, self.out_var):
            var.trace_add("write", lambda *_: self._update_save_button())
        # civilization types include the prefix
        self.prefix_var.trace_add("write", lambda *_: self._refresh_lists())

    def _build_civ_tab(self, tab):
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)
        self.civ_tree = ttk.Treeview(tab, columns=("type", "leaders",
                                                   "uniques"),
                                     show="tree headings", height=8,
                                     selectmode="browse",
                                     style="Leaders.Treeview")
        self.civ_tree.heading("#0", text="Civilization")
        self.civ_tree.column("#0", width=230)
        self.civ_tree.heading("type", text="Type")
        self.civ_tree.column("type", width=230)
        self.civ_tree.heading("leaders", text="Leaders")
        self.civ_tree.column("leaders", width=160)
        self.civ_tree.heading("uniques", text="Uniques")
        self.civ_tree.column("uniques", width=170)
        self.civ_tree.grid(row=0, column=0, sticky="nsew")
        self.civ_tree.bind("<Double-1>", lambda e: self.on_edit_civ())
        ttk.Label(tab, foreground="gray", wraplength=640, justify="left",
                  text="A new civilization needs at least one leader: add "
                       "one on the Leaders tab and pick the civilization "
                       "there (any leader can be the one it inherits "
                       "from).").grid(row=1, column=0, sticky="w",
                                      pady=(3, 0))
        btns = ttk.Frame(tab)
        btns.grid(row=0, column=1, sticky="n", padx=(8, 0))
        for text, cmd in (("Add...", self.on_add_civ),
                          ("Edit...", self.on_edit_civ),
                          ("Duplicate", self.on_duplicate_civ),
                          ("Remove", self.on_remove_civ)):
            ttk.Button(btns, text=text, command=cmd).pack(fill="x", pady=2)

    # -- unsaved-changes tracking ----------------------------------------------

    def _project_state(self):
        """What a save writes, to compare against the last saved state."""
        return (self.mod_name_var.get().strip() or "Alternate Leaders",
                self.type_prefix(), self.out_var.get().strip(),
                copy.deepcopy(self.project["leaders"]),
                copy.deepcopy(self.project["civs"]))

    def _mark_saved(self):
        """The current state is what is on disk (or a fresh project)."""
        self._saved_state = self._project_state()
        self._update_save_button()

    def _has_unsaved_changes(self):
        return self._project_state() != self._saved_state

    def on_close(self):
        """Window close: offer to save unsaved edits first."""
        if self._has_unsaved_changes():
            answer = messagebox.askyesnocancel(
                "Unsaved changes",
                "The project has unsaved changes. Save them before "
                "closing?")
            if answer is None:          # Cancel: keep working
                return
            if answer:
                self.on_save_project()
                if self._has_unsaved_changes():     # save cancelled/failed
                    return
        self.destroy()

    def _update_save_button(self):
        if self._saved_state is None:   # still building the widgets
            return
        self.save_btn.state(["!disabled"] if self._has_unsaved_changes()
                            else ["disabled"])

    # -- list handling ---------------------------------------------------------

    def _on_tree_scrolled(self, first, last):
        """yscrollcommand: move the scrollbar and say which rows show."""
        self.tree_scroll.set(first, last)
        count = len(self.project["leaders"])
        first, last = float(first), float(last)
        if count and (first > 0 or last < 1):
            text = "Showing {}-{} of {} leaders - scroll for more".format(
                round(first * count) + 1, round(last * count), count)
        else:
            text = "{} leader{}".format(count, "" if count == 1 else "s")
        self.list_hint.config(text=text)

    def _refresh_leader_list(self):
        self.tree.delete(*self.tree.get_children())
        self._list_icons = []           # Tk drops images nobody references
        for i, spec in enumerate(self.project["leaders"]):
            photo = ""
            try:
                from PIL import ImageTk
                photo = ImageTk.PhotoImage(
                    leader_icon_preview(spec, LIST_ICON_SIZE))
                self._list_icons.append(photo)
            except ImportError:         # no Pillow: names only
                pass
            self.tree.insert("", "end", iid=str(i),
                             text="  " + spec.get("name", ""), image=photo,
                             values=(self.resolve_civ(spec),
                                     spec.get("orig") or "(nobody)",
                                     " ".join(symbol for symbol, _ in
                                              leader_custom_marks(spec))))
        self._on_tree_scrolled(*self.tree.yview())
        self._update_save_button()

    def _refresh_lists(self):
        self._refresh_leader_list()
        self._refresh_civ_list()

    def _refresh_civ_list(self):
        tree = self.civ_tree
        selected = tree.selection()
        tree.delete(*tree.get_children())
        self._civ_icons = []
        led = {}
        for spec in self.project["leaders"]:
            led.setdefault(self.resolve_civ(spec), []).append(
                spec.get("name", ""))
        for i, spec in enumerate(self.project["civs"]):
            civ_type = civ_slug(spec, self.type_prefix())
            photo = ""
            try:
                from PIL import ImageTk
                photo = ImageTk.PhotoImage(civ_icon_preview(
                    spec, LIST_ICON_SIZE))
                self._civ_icons.append(photo)
            except ImportError:         # no Pillow: names only
                pass
            kinds = [u.get("kind") for u in spec.get("uniques") or []]
            tree.insert("", "end", iid=str(i), image=photo,
                        text="  " + spec.get("name", ""),
                        values=(civ_type,
                                ", ".join(led.get(civ_type, [])) or
                                "(none yet - add one)",
                                ", ".join("{} {}".format(kinds.count(k), k)
                                          for k in KINDS if k in kinds)))
        if selected and tree.exists(selected[0]):
            tree.selection_set(selected)
        self._update_save_button()

    def _on_tree_motion(self, event):
        """Explain the Custom column's symbols under the mouse."""
        text = ""
        if self.tree.identify_column(event.x) == "#3":      # "icon"
            region = self.tree.identify_region(event.x, event.y)
            row = self.tree.identify_row(event.y)
            if region == "heading":
                text = "What each leader customizes:\n" + "\n".join(
                    "{}  {}".format(*mark) for mark in CUSTOM_MARKS)
            elif region == "cell" and row:
                marks = leader_custom_marks(
                    self.project["leaders"][int(row)])
                text = "\n".join("{}  Custom {}".format(*mark)
                                 for mark in marks) or (
                    "Uses the original leader's backgrounds, agenda\n"
                    "and texts.")
        self.tree_tip.show(text)

    def _selected_index(self):
        sel = self.tree.selection()
        if not sel:
            return None
        return int(sel[0])

    def _selected_indices(self):
        return sorted(int(iid) for iid in self.tree.selection())

    def _edit_dialog(self, spec, title):
        spec = dict(spec, civ=self.resolve_civ(spec))
        editor = LeaderEditor(self, spec, title=title)
        self.wait_window(editor)
        return self._link_civ(editor.result) if editor.result else None

    def on_add_leader(self):
        result = self._edit_dialog(new_leader_spec(), "Add leader")
        if result:
            self.project["leaders"].append(result)
            self._refresh_lists()
            self.tree.selection_set(str(len(self.project["leaders"]) - 1))

    def on_edit_leader(self):
        i = self._selected_index()
        if i is None:
            messagebox.showinfo("No selection",
                                "Select a leader in the list first.")
            return
        spec = self.project["leaders"][i]
        result = self._edit_dialog(dict(spec), "Edit " + spec.get("name", ""))
        if result:
            self.project["leaders"][i] = result
            self._refresh_lists()
            self.tree.selection_set(str(i))

    def on_duplicate_leader(self):
        i = self._selected_index()
        if i is None:
            messagebox.showinfo("No selection",
                                "Select a leader in the list first.")
            return
        spec = dict(self.project["leaders"][i])
        spec["name"] = (spec.get("name") or "Leader") + " copy"
        self.project["leaders"].insert(i + 1, spec)
        self._refresh_leader_list()
        self.tree.selection_set(str(i + 1))

    def on_remove_leader(self):
        indices = self._selected_indices()
        if not indices:
            messagebox.showinfo("No selection",
                                "Select a leader in the list first.")
            return
        if len(indices) > 1 and not messagebox.askyesno(
                "Remove leaders",
                "Remove the {} selected leaders?".format(len(indices))):
            return
        for i in reversed(indices):
            del self.project["leaders"][i]
        self._refresh_lists()

    # -- civilization list -----------------------------------------------------

    def _selected_civ(self):
        sel = self.civ_tree.selection()
        if not sel:
            messagebox.showinfo("No selection",
                                "Select a civilization in the list first.")
            return None
        return int(sel[0])

    def _civ_dialog(self, spec, title):
        editor = CivEditor(self, spec, title=title)
        self.wait_window(editor)
        return editor.result

    def on_add_civ(self):
        result = self._civ_dialog(new_civ_spec(), "Add civilization")
        if result:
            self.project["civs"].append(result)
            self._refresh_lists()
            self.civ_tree.selection_set(str(len(self.project["civs"]) - 1))

    def on_edit_civ(self):
        i = self._selected_civ()
        if i is None:
            return
        spec = self.project["civs"][i]
        result = self._civ_dialog(spec, "Edit " + spec.get("name", ""))
        if result:
            self.project["civs"][i] = result
            self._refresh_lists()
            self.civ_tree.selection_set(str(i))

    def on_duplicate_civ(self):
        i = self._selected_civ()
        if i is None:
            return
        spec = copy.deepcopy(self.project["civs"][i])
        spec["name"] = (spec.get("name") or "Civilization") + " copy"
        spec["id"] = str(uuid.uuid4())
        self.project["civs"].insert(i + 1, spec)
        self._refresh_lists()
        self.civ_tree.selection_set(str(i + 1))

    def on_remove_civ(self):
        i = self._selected_civ()
        if i is None:
            return
        spec = self.project["civs"][i]
        civ_type = civ_slug(spec, self.type_prefix())
        led = [s.get("name", "") for s in self.project["leaders"]
               if self.resolve_civ(s) == civ_type]
        if not messagebox.askyesno(
                "Remove civilization",
                "Remove {}{}?".format(spec.get("name", ""), (
                    " (its leaders {} stay in the project and need another "
                    "civilization)".format(", ".join(led)) if led else ""))):
            return
        del self.project["civs"][i]
        self._refresh_lists()

    def on_export_leaders(self):
        """Export the selected leaders (all of them, and every
        civilization, if none is selected) with their images and the
        project civilizations they lead, for importing into another
        project."""
        leaders = self.project["leaders"]
        specs = [leaders[i] for i in self._selected_indices()] or leaders
        if not specs and not self.project["civs"]:
            messagebox.showinfo("No leaders",
                                "The project has no leaders to export.")
            return
        ids = {s.get("civ_id") for s in specs}
        civs = [c for c in self.project["civs"]
                if specs is leaders or c.get("id") in ids]
        name = specs[0].get("name") if len(specs) == 1 and not civs \
            else self.mod_name_var.get()
        path = filedialog.asksaveasfilename(
            title="Export {} leader(s)".format(len(specs)),
            initialfile=safe_folder_name(name) + ".altleaders",
            defaultextension="altleaders",
            filetypes=[("Alt-leader export", "*.altleaders")])
        if not path:
            return
        try:
            missing = export_leaders(specs, path, civs)
        except (OSError, zipfile.BadZipFile) as exc:
            messagebox.showerror("Could not export leaders", str(exc))
            return
        message = "Exported {} leader(s){} to:\n{}".format(
            len(specs), " and {} civilization(s)".format(len(civs))
            if civs else "", path)
        if missing:
            message += ("\n\n{} image(s) were not found and are not "
                        "included:\n{}".format(len(missing),
                                               "\n".join(missing[:10])) +
                        ("\n..." if len(missing) > 10 else ""))
        messagebox.showinfo("Leaders exported", message)

    def on_import_leaders(self):
        """Add the leaders of an export to this project. Leaders with the
        same type as one already here replace it or are skipped."""
        path = filedialog.askopenfilename(
            title="Import leaders",
            filetypes=[("Alt-leader export", "*.altleaders"),
                       ("All files", "*.*")])
        if not path:
            return
        try:
            specs, civ_specs, version = import_leaders(path)
        except (ValueError, OSError) as exc:
            messagebox.showerror("Could not import leaders", str(exc))
            return
        if version < 2:
            self._migrate_icon_crops(specs)
        self._move_moments(specs, civ_specs)
        prefix = self.type_prefix()
        leaders = self.project["leaders"]
        slugs = {slug_for_name(s.get("name"), prefix): i
                 for i, s in enumerate(leaders)}
        slugs.pop("", None)
        clashes = [s.get("name") for s in specs
                   if slug_for_name(s.get("name"), prefix) in slugs]
        civ_ids = {c.get("id"): i for i, c in enumerate(self.project["civs"])}
        clashes += [c.get("name") for c in civ_specs
                    if c.get("id") in civ_ids]
        replace = False
        if clashes:
            replace = messagebox.askyesnocancel(
                "Already in the project",
                "{} imported leader(s) / civilization(s) are already in "
                "this project:\n{}\n\n"
                "Yes: replace them\nNo: skip them\nCancel: import nothing"
                .format(len(clashes), "\n".join(clashes[:10]) +
                        ("\n..." if len(clashes) > 10 else "")))
            if replace is None:
                return
        changed = []
        for spec in specs:
            slug = slug_for_name(spec.get("name"), prefix)
            i = slugs.get(slug)
            if i is None:
                leaders.append(spec)
                i = len(leaders) - 1
                if slug:
                    slugs[slug] = i
            elif replace:
                leaders[i] = spec
            else:
                continue
            changed.append(i)
        civ_count = 0
        for civ in civ_specs:
            i = civ_ids.get(civ.get("id"))
            if i is None:
                self.project["civs"].append(civ)
            elif replace:
                self.project["civs"][i] = civ
            else:
                continue
            civ_count += 1
        self._refresh_lists()
        self.tree.selection_set([str(i) for i in changed])
        messagebox.showinfo(
            "Leaders imported",
            "Imported {} of {} leader(s){}.".format(
                len(changed), len(specs),
                " and {} of {} civilization(s)".format(
                    civ_count, len(civ_specs)) if civ_specs else ""))

    # -- project save / load ----------------------------------------------------

    def on_new_project(self):
        if (self.project["leaders"] or self.project["civs"]) and \
                not messagebox.askyesno(
                    "New project",
                    "Discard the current project and start fresh?"):
            return
        self.project = self._empty_project()
        self.project_path = None
        self.mod_name_var.set(self.project["mod_name"])
        self.prefix_var.set(self.project["prefix"])
        self.out_var.set(self.project["output_dir"])
        self.project_label.config(text="(unsaved)")
        self._refresh_lists()
        self._mark_saved()

    def on_open_project(self):
        path = filedialog.askopenfilename(
            title="Open alt-leader project",
            filetypes=[("Alt-leader project", "*.altleader"),
                       ("All files", "*.*")])
        if not path:
            return
        try:
            with open(path, "rb") as fh:
                project = pickle.load(fh)
        except Exception as exc:
            messagebox.showerror("Could not open project", str(exc))
            return
        if (not isinstance(project, dict)
                or project.get("magic") != PROJECT_MAGIC
                or not isinstance(project.get("leaders"), list)):
            messagebox.showerror("Invalid project file",
                                 "This does not look like an alt-leader "
                                 "project file.")
            return
        for spec in project["leaders"]:
            if not isinstance(spec, dict) or "name" not in spec:
                messagebox.showerror("Invalid project file",
                                     "Project contains a malformed leader "
                                     "entry.")
                return
        project.setdefault("civs", [])      # projects before version 3
        if not isinstance(project["civs"], list) or not all(
                isinstance(c, dict) and "name" in c for c in project["civs"]):
            messagebox.showerror("Invalid project file",
                                 "Project contains a malformed civilization "
                                 "entry.")
            return
        if project.get("version", 1) < 2:
            self._migrate_icon_crops(project["leaders"])
        project["version"] = PROJECT_VERSION
        self._move_moments(project["leaders"], project["civs"],
                           clean_prefix(project.get("prefix", "")))
        self.project = project
        self.project["output_dir"] = (project.get("output_dir")
                                      or default_out_dir())
        self.project_path = path
        self.mod_name_var.set(self.project.get("mod_name",
                                               "Alternate Leaders"))
        self.prefix_var.set(self.project.get("prefix", ""))
        self.out_var.set(self.project["output_dir"])
        self.project_label.config(text=os.path.basename(path))
        self._refresh_lists()
        self._mark_saved()

    def _move_moments(self, leaders, civs, prefix=None):
        """Historic moment pictures now belong to civilizations: move
        those of leaders of the given (project) civilizations there.
        prefix: the type prefix of those civilizations (default: this
        project's)."""
        prefix = self.type_prefix() if prefix is None else prefix
        by_id = {c.get("id"): c for c in civs if c.get("id")}
        by_type = {civ_slug(c, prefix): c for c in civs}

        def civ_of(spec):
            return (by_id.get(spec.get("civ_id")) or
                    by_type.get((spec.get("civ") or "").strip()))
        move_moments_to_civs(leaders, civs, civ_of)

    @staticmethod
    def _migrate_icon_crops(leaders):
        """Version 1 projects chose the icon circle on the portrait as
        is; portraits are now fitted to PORTRAIT_SIZE first."""
        for spec in leaders:
            src = (spec.get("load_fg_path") or "").strip()
            if not spec.get("icon_crop") or not os.path.isfile(src):
                continue
            try:
                spec["icon_crop"] = fit_icon_crop(spec["icon_crop"], src)
            except Exception:           # no Pillow / unreadable image
                spec["icon_crop"] = None

    def on_save_project(self):
        self.project["mod_name"] = self.mod_name_var.get().strip() \
            or "Alternate Leaders"
        self.project["prefix"] = self.type_prefix()
        self.project["output_dir"] = self.out_var.get().strip()
        path = self.project_path
        if not path:
            path = filedialog.asksaveasfilename(
                title="Save alt-leader project",
                defaultextension="altleader",
                filetypes=[("Alt-leader project", "*.altleader")])
            if not path:
                return
            self.project_path = path
        payload = dict(self.project)
        payload["magic"] = PROJECT_MAGIC
        payload["version"] = PROJECT_VERSION
        payload["leaders"] = list(self.project["leaders"])
        payload["civs"] = list(self.project["civs"])
        try:
            with open(path, "wb") as fh:
                pickle.dump(payload, fh, protocol=pickle.HIGHEST_PROTOCOL)
        except OSError as exc:
            messagebox.showerror("Could not save project", str(exc))
            return
        self.project_label.config(text=os.path.basename(path))
        self._mark_saved()
        messagebox.showinfo("Project saved",
                            "Saved {} leader(s) and {} civilization(s) "
                            "to:\n{}".format(len(self.project["leaders"]),
                                            len(self.project["civs"]), path))

    # -- misc ---------------------------------------------------------------------

    def on_load_cache(self):
        path = find_game_cache()
        if not path:
            path = filedialog.askopenfilename(
                title="Locate DebugGameplay.sqlite",
                filetypes=[("Civ 6 debug cache", "DebugGameplay.sqlite"),
                           ("All files", "*.*")])
        if not path:
            return
        busy = BusyDialog(self, "Loading game data")
        busy.set_status("Reading the game cache and the DLC / mod texts...")
        try:
            busy.run(lambda: self.data.load(path))
        except sqlite3.Error as exc:
            messagebox.showerror("Could not read game data", str(exc))
            return
        self.cache_label.config(text=os.path.basename(path))
        messagebox.showinfo(
            "Game data loaded",
            "Loaded {} civilizations / {} leaders from your install. "
            "The leader editor dropdowns now use the real game data.\n\n{}"
            .format(len(self.data.civ_to_leaders), len(self.data.leader_meta),
                    "Found the colors of {} leaders.".format(
                        len(self.data.leader_colors))
                    if self.data.leader_colors else
                    "Leader colors were not found (game install folder not "
                    "detected) - pick colors by hand."))

    def on_browse_out(self):
        path = filedialog.askdirectory(title="Choose output folder")
        if path:
            self.out_var.set(path)

    # -- generation -----------------------------------------------------------------

    def on_generate(self):
        mod_name = self.mod_name_var.get().strip() or "Alternate Leaders"
        out_root = self.out_var.get().strip()
        if not out_root:
            messagebox.showwarning("Missing input", "Choose an output folder.")
            return
        if not self.project["leaders"]:
            messagebox.showwarning("No leaders",
                                   "Add at least one leader to the project.")
            return

        # 1) validate everything up front; collect every problem
        civs, ctxs, errors = prepare_project(
            self.project["leaders"], self.project["civs"], self.data,
            self.type_prefix())
        if errors:
            messagebox.showwarning("Problems found",
                                   "\n\n".join(errors))
            return
        existing = ["{} ({})".format(c["name"], c["slug"])
                    for c in civs + ctxs if c["exists_in_game"]]
        if existing and not messagebox.askyesno(
                "Already in the game data",
                "These types already exist in the loaded game data:"
                "\n\n{}\n\nThat is expected if the game cache includes an "
                "earlier version of this mod - then just make sure the old "
                "version is not enabled alongside the new one. If another "
                "mod defines them, the two mods will conflict.\n\n"
                "Generate the mod anyway?".format("\n".join(existing)),
                icon="warning"):
            return

        # 2) prepare and cook art (falls back to inherited art on failure)
        folder = safe_folder_name(mod_name)
        mod_dir = os.path.join(out_root, folder)
        report = []
        try:
            for sub in ("Config", "Gameplay", "Text"):
                os.makedirs(os.path.join(mod_dir, sub), exist_ok=True)
            # leftovers of older generator versions (loose .dds files)
            shutil.rmtree(os.path.join(mod_dir, "Art"), ignore_errors=True)
        except OSError as exc:
            messagebox.showerror("Could not create mod folder", str(exc))
            return

        # Reuse the project's mod id so re-generating updates the same mod
        # entry in Additional Content instead of creating a duplicate.
        guid = self.project.get("guid") or str(uuid.uuid4())
        self.project["guid"] = guid

        # may ask for the cooker - dialogs must happen before the worker
        wants_art = any(needs_art(c) for c in ctxs) or any(
            cc["icon_custom"] or any(u["icon_custom"] for u in cc["uniques"])
            for cc in civs)
        cooker = self._cooker_path() if wants_art else None

        # 3) convert, cook and write in a thread behind a progress window
        busy = BusyDialog(self, "Generating mod")
        try:
            icon_count = busy.run(lambda: write_mod(
                mod_name, ctxs, folder, mod_dir, guid, cooker, report,
                busy.set_status, civs, self.data.type_name))
        except OSError as exc:
            messagebox.showerror("Could not write mod", str(exc))
            return

        warnings = [r for r in report if r.startswith("WARNING")]
        warning_text = ("\n\n{} warning(s):\n{}\n(details in README.txt)"
                        .format(len(warnings), "\n".join(warnings[:5]))
                        if warnings else "")
        if messagebox.askyesno(
                "Done",
                "Mod written to:\n{}\n\n{} file operation(s), {} "
                "civilization(s), {} leader(s), {} custom icon(s).{}\n\n"
                "Open the folder now?".format(
                    mod_dir, len(report), len(civs), len(ctxs), icon_count,
                    warning_text)):
            self._open_folder(mod_dir)

    def _cooker_path(self):
        """The SDK asset cooker: remembered, auto-detected, or asked for."""
        path = self.project.get("cooker_path")
        if path and os.path.isfile(path):
            return path
        path = find_cooker()
        if not path:
            messagebox.showinfo(
                "Asset cooker needed",
                "Custom icons and loading images must be cooked with the "
                "Civ VI SDK asset cooker ({}).\n\nInstall \"Sid Meier's "
                "Civilization VI Development Tools\" from Steam, or locate "
                "the cooker in the next dialog.".format(COOKER_EXE))
            path = filedialog.askopenfilename(
                title="Locate " + COOKER_EXE,
                filetypes=[("Asset cooker", COOKER_EXE),
                           ("All files", "*.*")])
        if path:
            self.project["cooker_path"] = path
        return path or None

    @staticmethod
    def _open_folder(path):
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)  # noqa: S605 (Windows only API)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except OSError:
            pass


def main():
    GeneratorApp().mainloop()
