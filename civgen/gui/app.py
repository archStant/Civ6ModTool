"""The main application window."""

import copy
import os
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
from ..civs import (CIV_BADGE_COLOR, civ_icon_preview, civ_slug,
                    new_civ_spec)
from ..uniques import KINDS, MAIN_TABLES
from ..modbuild import (all_uniques, check_extra_files, prepare_project,
                        write_mod)
from ..moments import move_to_civs as move_moments_to_civs
from ..workshop import (UPLOADER_EXE, build_stamp, find_uploader,
                        new_workshop_spec, normalize_workshop, plain_text,
                        resolved)
from ..references import (prefix_change, retarget,
                          repair as repair_references)
from ..project import (LEGACY_EXT, PROJECT_EXT, json_ready, load_project,
                       project_path_for, save_project, export_leaders,
                       import_leaders)
from . import theme
from .widgets import install_icon_context_menu
from .widgets import BusyDialog, Tooltip, add_tooltip
from .workshop_dialog import WorkshopDialog
from .leader_editor import LeaderEditor
from .civ_editor import CivEditor


# ---------------------------------------------------------------------------
# Main application window
# ---------------------------------------------------------------------------

class GeneratorApp(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("Civ 6 Mod Generator")
        self.minsize(760, 520)
        self._set_window_icon()
        # light / dark mode before any widget, so they start in its colors
        theme.init(self, self._configure_styles)
        theme.apply(theme.preferred_dark())

        self.data = GameData()
        self.project = self._empty_project()
        self.project_path = None
        self._saved_state = None

        self._build_widgets()
        self.on_advanced_mode(save=False)
        # right-click in any text field: insert a game icon
        install_icon_context_menu(self)
        self._refresh_lists()
        self._mark_saved()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.maximize()

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
            "mod_name": "New Mod",
            "prefix": "",
            "output_dir": default_out_dir(),
            "guid": str(uuid.uuid4()),
            "leaders": [],
            "civs": [],
            # Steam Workshop details (see workshop.py)
            "workshop": new_workshop_spec(),
            # files of the user's own (see modbuild.check_extra_files)
            "extra_files": [],
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

    def _configure_styles(self):
        """The app's own styles; they belong to the ttk theme in use, so
        the theme module calls this after every light / dark switch."""
        style = ttk.Style(self)
        style.configure("Toolbar.TFrame", padding=(6, 4))
        style.configure("Toolbutton", padding=(10, 5))
        style.configure("Generate.TButton", font=("TkDefaultFont", 10,
                                                  "bold"), padding=(12, 4))
        style.configure("Status.TLabel", foreground=theme.hint(),
                        padding=(8, 2))
        # the status bar's warning: white on red, like a badge
        style.configure("Warning.TLabel", foreground="#ffffff",
                        background="#d64541",
                        font=("TkDefaultFont", 10, "bold"), padding=(4, 0))
        # tall rows so each leader's icon fits next to their name
        style.configure("Leaders.Treeview", rowheight=LIST_ICON_SIZE + 16)

    def on_dark_mode(self):
        """The toolbar's Dark mode switch: apply and remember it."""
        dark = bool(self.dark_var.get())
        theme.apply(dark)
        theme.save_setting("dark_mode", dark)

    def on_advanced_mode(self, save=True):
        """The toolbar's Advanced mode switch: remember it (the editors
        read it when they open) and show the Custom files button."""
        advanced = bool(self.advanced_var.get())
        if save:
            theme.save_setting("advanced_mode", advanced)
        if advanced:
            self.custom_btn.pack(side="left", padx=1, after=self.export_btn)
        else:
            self.custom_btn.pack_forget()
        self._refresh_custom_note()

    def _refresh_custom_note(self):
        """The status bar's note of the project's custom files."""
        count = len(self.project.get("extra_files") or [])
        self.custom_label.configure(text="{} custom file{}".format(
            count, "" if count == 1 else "s") if count else "")

    def on_custom_files(self):
        from .custom_files import CustomFilesDialog
        dialog = CustomFilesDialog(self, self.project.get("extra_files"))
        self.wait_window(dialog)
        if dialog.result is not None:
            self.project["extra_files"] = dialog.result
            self._refresh_custom_note()
            self._update_save_button()

    def _build_widgets(self):
        pad = {"padx": 6, "pady": 3}

        # -- toolbar: project, game data, import / export, generate
        toolbar = ttk.Frame(self, style="Toolbar.TFrame")
        toolbar.pack(side="top", fill="x")

        def tool(text, command, tip, **kw):
            button = ttk.Button(toolbar, text=text, command=command,
                                style="Toolbutton", **kw)
            button.pack(side="left", padx=1)
            add_tooltip(button, tip)
            return button

        def separator():
            ttk.Separator(toolbar, orient="vertical").pack(
                side="left", fill="y", padx=6, pady=2)

        tool("New", self.on_new_project, "Start a new project (Ctrl+N)")
        tool("Open...", self.on_open_project, "Open a project (Ctrl+O)")
        self.save_btn = tool("Save", self.on_save_project,
                             "Save the project (Ctrl+S)")
        tool("Save as...", self.on_save_project_as,
             "Save the project under another name (Ctrl+Shift+S)")
        separator()
        tool("Load game data...", self.on_load_cache,
             "Read civilizations, leaders, units, buildings... from the "
             "game's own cache, for the editors' lists")
        separator()
        tool("Import...", self.on_import_leaders,
             "Add the leaders (and civilizations) of an export to this "
             "project")
        self.export_btn = tool(
            "Export...", self.on_export_leaders,
            "Export the selected leaders (and their civilizations), with "
            "their images, to share or move them")
        # (advanced mode only, see on_advanced_mode)
        self.custom_btn = tool(
            "Custom files...", self.on_custom_files,
            "Add files of your own - SQL, XML, Lua... - to the mod, for "
            "what the editors cannot make")
        self.generate_btn = ttk.Button(toolbar, text="Generate mod",
                                       style="Generate.TButton",
                                       command=self.on_generate)
        self.generate_btn.pack(side="right", padx=(6, 2))
        add_tooltip(self.generate_btn, "Write the mod into the output "
                    "folder (F5)")
        publish = ttk.Button(toolbar, text="Publish to Workshop...",
                             style="Toolbutton", command=self.on_publish)
        publish.pack(side="right", padx=1)
        add_tooltip(publish, "Check the generated mod and publish it on the "
                    "Steam Workshop with the Civ VI SDK's uploader")
        self.fullscreen_btn = tool("Fullscreen", self.toggle_fullscreen,
                                   "Fill the whole screen (F11; Esc "
                                   "leaves it)")
        self.fullscreen_btn.pack_configure(side="right")
        self.dark_var = tk.BooleanVar(value=theme.is_dark())
        dark = ttk.Checkbutton(toolbar, text="Dark mode",
                               variable=self.dark_var, style="Toolbutton",
                               command=self.on_dark_mode)
        dark.pack(side="right", padx=1)
        add_tooltip(dark, "Switch between light and dark colors (remembered "
                    "for next time)")
        self.advanced_var = tk.BooleanVar(
            value=bool(theme.load_settings().get("advanced_mode")))
        advanced = ttk.Checkbutton(toolbar, text="Advanced mode",
                                   variable=self.advanced_var,
                                   style="Toolbutton",
                                   command=self.on_advanced_mode)
        advanced.pack(side="right", padx=1)
        add_tooltip(advanced, (
            "Advanced mode: effects can be any of the game's modifiers, "
            "with any of its requirements (and 'any of' groups of them), "
            "and can be copied from anything in the game - abilities, "
            "beliefs, promotions, great people...\n\nBasic mode keeps to "
            "the effect list. Advanced effects made before stay in the "
            "mod either way. Remembered for next time."))
        ttk.Separator(self, orient="horizontal").pack(side="top", fill="x")

        # -- status bar: project file and game data
        status = ttk.Frame(self)
        status.pack(side="bottom", fill="x")
        ttk.Separator(status, orient="horizontal").pack(side="top",
                                                        fill="x")
        self.project_label = ttk.Label(status, text="(unsaved)",
                                       style="Status.TLabel")
        self.project_label.pack(side="left")
        self.custom_label = ttk.Label(status, style="Status.TLabel")
        self.custom_label.pack(side="left")
        add_tooltip(self.custom_label, "Files of your own the mod gets as "
                    "they are (Custom files... in Advanced mode)")
        # without the game's own data: a warning, which loads it on click
        self.data_warning = ttk.Label(status, text=" ! ",
                                      style="Warning.TLabel",
                                      cursor="hand2")
        self.data_warning.pack(side="right", padx=(0, 6))
        self.data_warning.bind("<Button-1>", lambda e: self.on_load_cache())
        add_tooltip(self.data_warning, (
            "Using the built-in list of game data: only a handful of "
            "civilizations and leaders, and none of the game's units, "
            "buildings, districts, improvements, abilities or agendas - "
            "the editors' lists are nearly empty and copied items cannot "
            "be checked.\n\nClick here (or Load game data... in the "
            "toolbar) to read the real data of your game, DLC and mods "
            "included. Tip: start the game once with Gathering Storm "
            "first, so its data is in the game's cache."))
        self.cache_label = ttk.Label(status, text="using built-in list",
                                     style="Status.TLabel")
        self.cache_label.pack(side="right")
        ttk.Label(status, text="Game data:", style="Status.TLabel").pack(
            side="right")

        top = ttk.Frame(self, padding=(10, 6, 10, 6))
        top.pack(fill="both", expand=True)

        # -- mod settings, on one line
        settings = ttk.LabelFrame(top, text="Mod", padding=(8, 4))
        settings.grid(row=0, column=0, sticky="we", pady=(0, 6))
        ttk.Label(settings, text="Name").grid(row=0, column=0, sticky="w",
                                              **pad)
        self.mod_name_var = tk.StringVar(
            value=self.project["mod_name"])
        ttk.Entry(settings, textvariable=self.mod_name_var, width=28).grid(
            row=0, column=1, sticky="w", **pad)
        label = ttk.Label(settings, text="Type prefix (?)")
        label.grid(row=0, column=2, sticky="w", padx=(18, 6), pady=3)
        add_tooltip(label, "Put in front of every type the mod makes, so "
                    "it cannot clash with other mods' (e.g. your initials).")
        self.prefix_var = tk.StringVar(value=self.project.get("prefix", ""))
        ttk.Entry(settings, textvariable=self.prefix_var, width=10).grid(
            row=0, column=3, sticky="w", **pad)
        self.prefix_hint = ttk.Label(settings, text="", foreground=theme.hint())
        self.prefix_hint.grid(row=0, column=4, sticky="w", **pad)
        self.prefix_var.trace_add("write", lambda *_: self.prefix_hint.config(
            text="-> " + slug_for_name("Name", self.type_prefix())))
        self.prefix_var.set(self.prefix_var.get())   # show the hint
        ttk.Label(settings, text="Output folder").grid(
            row=0, column=5, sticky="w", padx=(18, 6), pady=3)
        self.out_var = tk.StringVar(value=self.project["output_dir"])
        ttk.Entry(settings, textvariable=self.out_var).grid(
            row=0, column=6, sticky="we", **pad)
        ttk.Button(settings, text="Browse...",
                   command=self.on_browse_out).grid(row=0, column=7,
                                                    sticky="w", **pad)
        settings.columnconfigure(6, weight=1)

        # -- leaders and civilizations, one tab each
        notebook = ttk.Notebook(top)
        notebook.grid(row=1, column=0, sticky="nsew")
        leader_tab = ttk.Frame(notebook, padding=6)
        civ_tab = ttk.Frame(notebook, padding=6)
        notebook.add(leader_tab, text="Leaders")
        notebook.add(civ_tab, text="Civilizations")
        leader_tab.columnconfigure(0, weight=1)
        leader_tab.rowconfigure(0, weight=1)
        self._build_civ_tab(civ_tab)
        top.columnconfigure(0, weight=1)
        top.rowconfigure(1, weight=1)

        # -- leader list
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
        ttk.Label(list_frame, foreground=theme.hint(), text="   ".join(
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

        for var in (self.mod_name_var, self.prefix_var, self.out_var):
            var.trace_add("write", lambda *_: self._update_save_button())
        # civilization types include the prefix
        self.prefix_var.trace_add("write", lambda *_: self._refresh_lists())
        # references to the project's uniques follow the prefix
        self._last_prefix = self.type_prefix()
        self.prefix_var.trace_add("write", lambda *_: self._prefix_changed())

        # -- keyboard shortcuts
        for keys, command in (("<Control-n>", self.on_new_project),
                              ("<Control-o>", self.on_open_project),
                              ("<Control-s>", self.on_save_project),
                              ("<Control-S>", self.on_save_project_as),
                              ("<F5>", self.on_generate),
                              ("<F11>", self.toggle_fullscreen)):
            self.bind(keys, lambda e, c=command: c())
        self.bind("<Escape>", lambda e: self.toggle_fullscreen(False))

    def maximize(self):
        """Fill the screen (as a normal, maximized window)."""
        try:
            self.state("zoomed")                # Windows, macOS
        except tk.TclError:
            try:
                self.attributes("-zoomed", True)    # X11
            except tk.TclError:
                self.geometry("{}x{}+0+0".format(self.winfo_screenwidth(),
                                                 self.winfo_screenheight()))

    def toggle_fullscreen(self, on=None):
        """Fullscreen without title bar and taskbar (on: True / False,
        None = switch)."""
        if on is None:
            on = not self.attributes("-fullscreen")
        self.attributes("-fullscreen", bool(on))
        self.fullscreen_btn.configure(text="Exit fullscreen" if on
                                      else "Fullscreen")

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
        ttk.Label(tab, foreground=theme.hint(), wraplength=640, justify="left",
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
        """What a save writes, to compare against the last saved state
        (as JSON keeps it: a tuple and a list of the same values are
        the same)."""
        return json_ready([
            self.mod_name_var.get().strip() or "New mod",
            self.type_prefix(), self.out_var.get().strip(),
            self.project["leaders"], self.project["civs"],
            self.project.get("workshop"),
            self.project.get("extra_files") or []])

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

    def _update_save_button(self, force=False):
        """force: the project has unsaved changes whatever its state
        (_saved_state None, e.g. not yet saved in the current format)."""
        if self._saved_state is None and not force:
            return                      # still building the widgets
        unsaved = self._saved_state is None or self._has_unsaved_changes()
        self.save_btn.state(["!disabled"] if unsaved else ["disabled"])
        name = os.path.basename(self.project_path) if self.project_path             else "New project (not saved yet)"
        self.project_label.config(text="Project: {}{}".format(
            name, " - unsaved changes" if unsaved else ""))

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
        if hasattr(self, "custom_label"):
            self._refresh_custom_note()

    def _refresh_civ_list(self):
        tree = self.civ_tree
        selected = tree.selection()
        tree.delete(*tree.get_children())
        self._civ_icons = []
        led, colors = {}, {}
        for spec in self.project["leaders"]:
            civ_type = self.resolve_civ(spec)
            led.setdefault(civ_type, []).append(spec.get("name", ""))
            # the badge behind the icon: its first leader's color
            colors.setdefault(civ_type, tuple(spec.get("primary") or
                                              CIV_BADGE_COLOR))
        for i, spec in enumerate(self.project["civs"]):
            civ_type = civ_slug(spec, self.type_prefix())
            photo = ""
            try:
                from PIL import ImageTk
                photo = ImageTk.PhotoImage(civ_icon_preview(
                    spec, LIST_ICON_SIZE,
                    badge=colors.get(civ_type, CIV_BADGE_COLOR)))
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
        spec = copy.deepcopy(self.project["leaders"][i])
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
        # (a project of its own: not a prefix change)
        self._last_prefix = clean_prefix(self.project.get("prefix", ""))
        self.prefix_var.set(self.project["prefix"])
        self.out_var.set(self.project["output_dir"])
        self._refresh_lists()
        self._mark_saved()

    PROJECT_TYPES = [("Civ mod project", "*" + PROJECT_EXT),
                     ("Older project (alt-leader)", "*" + LEGACY_EXT),
                     ("All files", "*.*")]

    def on_open_project(self):
        path = filedialog.askopenfilename(
            title="Open project", filetypes=[
                ("Projects", "*{} *{}".format(PROJECT_EXT, LEGACY_EXT))] +
            self.PROJECT_TYPES)
        if not path:
            return
        try:
            project, version = load_project(path)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Could not open project", str(exc))
            return
        project["workshop"] = normalize_workshop(project.get("workshop"))
        if version < 2:
            self._migrate_icon_crops(project["leaders"])
        self._move_moments(project["leaders"], project["civs"],
                           clean_prefix(project.get("prefix", "")))
        self.project = project
        self.project["output_dir"] = (project.get("output_dir")
                                      or default_out_dir())
        # an older *.altleader is saved as a *.civmod next to it
        self.project_path = project_path_for(path)
        self.mod_name_var.set(self.project.get("mod_name",
                                               "unnamed_mod"))
        # (a project of its own: not a prefix change)
        self._last_prefix = clean_prefix(self.project.get("prefix", ""))
        self.prefix_var.set(self.project.get("prefix", ""))
        self.out_var.set(self.project["output_dir"])
        self._refresh_lists()
        self._mark_saved()
        if self.project_path != path:
            # not saved in the new format yet
            self._saved_state = None
            self._update_save_button(force=True)
            messagebox.showinfo(
                "Older project",
                "This project was made with an older version and is "
                "stored as a Python pickle ({}).\n\nSaving it writes a "
                "{} file next to it instead:\n{}\n\nThe old file is not "
                "changed.".format(os.path.basename(path), PROJECT_EXT,
                                  self.project_path))

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
            or "unnamed_mod"
        self.project["prefix"] = self.type_prefix()
        self.project["output_dir"] = self.out_var.get().strip()
        path = self.project_path
        if not path:
            name = self.project["mod_name"]
            path = filedialog.asksaveasfilename(
                title="Save project",
                initialfile=safe_folder_name(name) + PROJECT_EXT,
                defaultextension=PROJECT_EXT,
                filetypes=self.PROJECT_TYPES[:1])
            if not path:
                return
            self.project_path = path
        try:
            save_project(self.project, path)
        except (OSError, TypeError, ValueError) as exc:
            messagebox.showerror("Could not save project", str(exc))
            return
        self._mark_saved()
        messagebox.showinfo("Project saved",
                            "Saved {} leader(s) and {} civilization(s) "
                            "to:\n{}".format(len(self.project["leaders"]),
                                             len(self.project["civs"]), path))

    def on_save_project_as(self):
        """Save under a new file name (the project then lives there)."""
        old = self.project_path
        self.project_path = None
        self.on_save_project()
        if not self.project_path:       # cancelled
            self.project_path = old
            self._update_save_button()

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
        self.cache_label.config(text="{} ({} civilizations, {} leaders)".format(
            os.path.basename(path), len(self.data.civ_to_leaders),
            len(self.data.leader_meta)))
        self.data_warning.pack_forget()     # the real data now
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

    def _prefix_changed(self):
        """Point references to the uniques (the civilizations' and the
        leaders': moment pictures, districts, effects) at their types with
        the new prefix."""
        new = self.type_prefix()
        old, self._last_prefix = getattr(self, "_last_prefix", new), new
        if old == new:
            return
        mapping = prefix_change(self.project["civs"], old, new,
                                self.project["leaders"])
        if mapping:
            retarget(self.project["civs"], mapping)
            retarget(self.project["leaders"], mapping)

    def on_generate(self, ask_open=True):
        """Generate the mod. ask_open: offer to open its folder after.
        Returns True when the mod was written."""
        # references left behind by an earlier prefix (older projects)
        fixed = repair_references(self.project["leaders"],
                                  self.project["civs"], self.type_prefix(),
                                  self.data)
        if fixed:
            self._update_save_button()
            messagebox.showinfo(
                "References updated",
                "These references to the project's uniques used an old "
                "type and now use the current one:\n\n{}\n\n(Save the "
                "project to keep this.)".format("\n".join(
                    "{}  ->  {}".format(old, new) for old, new in fixed)))
        mod_name = self.mod_name_var.get().strip() or "unnamed_mod"
        out_root = self.out_var.get().strip()
        if not out_root:
            messagebox.showwarning("Missing input", "Choose an output folder.")
            return False
        if not self.project["leaders"]:
            messagebox.showwarning("No leaders",
                                   "Add at least one leader to the project.")
            return False

        # 1) validate everything up front; collect every problem
        civs, ctxs, errors = prepare_project(
            self.project["leaders"], self.project["civs"], self.data,
            self.type_prefix())
        extra_files, file_errors = check_extra_files(
            self.project.get("extra_files"))
        errors += file_errors
        if errors:
            messagebox.showwarning("Problems found",
                                   "\n\n".join(errors))
            return False
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
            return False

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
            return False

        # Reuse the project's mod id so re-generating updates the same mod
        # entry in Additional Content instead of creating a duplicate.
        guid = self.project.get("guid") or str(uuid.uuid4())
        self.project["guid"] = guid

        # may ask for the cooker - dialogs must happen before the worker
        wants_art = any(needs_art(c) for c in ctxs) or \
            any(cc["icon_custom"] for cc in civs) or \
            any(u["icon_custom"] for u in all_uniques(civs, ctxs))
        cooker = self._cooker_path() if wants_art else None

        # 3) convert, cook and write in a thread behind a progress window
        busy = BusyDialog(self, "Generating mod")
        try:
            publish, stamp = self.publish_values(), self.build_stamp()
            icon_count = busy.run(lambda: write_mod(
                mod_name, ctxs, folder, mod_dir, guid, cooker, report,
                busy.set_status, civs, self.data.type_name,
                {"version": publish["version"], "author": publish["author"],
                 "description": plain_text(publish["description"])},
                stamp, extra_files))
        except OSError as exc:
            messagebox.showerror("Could not write mod", str(exc))
            return False
        if not ask_open:
            return True

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
        return True

    # -- Steam Workshop ---------------------------------------------------------

    def mod_dir(self):
        """Where the mod is generated."""
        name = self.mod_name_var.get().strip() or "unnamed_mod"
        return os.path.join(self.out_var.get().strip(),
                            safe_folder_name(name))

    def civ_display_name(self, leader_spec):
        """The name of a leader's civilization (a project's or the
        game's)."""
        civ_type = self.resolve_civ(leader_spec)
        for spec in self.project["civs"]:
            if civ_slug(spec, self.type_prefix()) == civ_type:
                return spec.get("name") or civ_type
        return self.data.type_name("civilization", civ_type) or civ_type

    def publish_values(self):
        """The Workshop settings with the empty ones filled in (see
        workshop.resolved)."""
        return resolved(self.project.get("workshop"),
                        self.mod_name_var.get().strip() or
                        "unnamed_mod", self.project["civs"],
                        self.project["leaders"], self.civ_display_name)

    def build_stamp(self):
        """A hash of everything the generated mod is made from."""
        publish = self.publish_values()
        # (a custom file changed since is as new as an edited leader)
        custom = [dict(f, mtime=os.path.getmtime(f["path"])
                       if os.path.isfile(f.get("path") or "") else None)
                  for f in self.project.get("extra_files") or []]
        return build_stamp(self._project_state()[:2],
                           self.project["leaders"], self.project["civs"],
                           publish["version"], publish["author"],
                           publish["description"], *([custom] if custom
                                                     else []))

    def uploader_path(self, ask=True):
        """The SDK's Workshop uploader: remembered, found, or asked for."""
        path = self.project.get("uploader_path")
        if path and os.path.isfile(path):
            return path
        path = find_uploader()
        if not path and ask:
            messagebox.showinfo(
                "Workshop uploader needed",
                "Publishing uses the Steam Workshop uploader of the Civ VI "
                "SDK ({}).\n\nInstall \"Sid Meier's Civilization VI "
                "Development Tools\" from Steam (Library - Tools), or "
                "locate the uploader in the next dialog.".format(
                    UPLOADER_EXE), parent=self.focus_get() or self)
            path = filedialog.askopenfilename(
                title="Locate " + UPLOADER_EXE,
                filetypes=[("Workshop uploader", UPLOADER_EXE),
                           ("All files", "*.*")])
        if path:
            self.project["uploader_path"] = path
        return path or None

    def on_publish(self):
        WorkshopDialog(self)

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
