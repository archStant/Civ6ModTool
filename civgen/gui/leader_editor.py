"""The leader editor dialog."""

import os
import re

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser

from ..util import asset_path, slug_for_name, type_display_name
from ..art import (DEFAULT_ICON_BORDER_COLOR, DEFAULT_ICON_BORDER_WIDTH,
                   DEFAULT_LOAD_BG, DIPLO_BG_MASK, PREVIEW_BACKDROP,
                   PREVIEW_BOX,
                   fitted_portrait, make_circle_icon, preview_image)
from ..texts import (DIPLO_TEXT, PEDIA_HISTORY, PEDIA_TEXT,
                     inherit_candidates, spec_texts, texts_from_json,
                     texts_to_json)
from ..modifiers import describe_effects
from ..leaders import AI_TRAITS, DEFAULT_AI_TRAITS, spec_icon_mode
from ..references import retarget
from ..uniques import KINDS
from ..moods import MOOD_GROUPS, MOOD_SLOTS, resolve_slot
from ..moods import slot_label as mood_label
from . import theme
from .widgets import WRITE_TIP, write_description
from .widgets import fit_to_screen
from .widgets import icon_text
from .widgets import IconCropDialog, ScrollFrame, add_tooltip
from .modifier_editor import EffectsFrame
from .agenda_editor import ReactionsFrame
from .uniques_frame import UniquesFrame, unique_choices
from .moments_editor import HELP as MOMENTS_HELP, MomentsFrame

LEGACY_MOMENTS_HELP = (
    "Historic moment pictures are now set in the civilization editor. "
    "This leader's civilization is one of the game's, so the pictures it "
    "had in an older project stay here: they still work, and can be "
    "changed or removed.\n\n" + MOMENTS_HELP)
PORTRAITS_HELP = (
    "The diplomacy screen shows the leader as a still image (generated "
    "leaders have no 3D scene): the Portrait from the General tab. Here "
    "it can change with the leader's mood and with what is happening - "
    "hover over a name to see when it is shown. An empty slot shows the "
    "image named next to it. Use pictures with the same size and framing "
    "as the Portrait (they are fitted the same way), so the leader does "
    "not jump between them. Each different picture adds about 9 MB to "
    "the mod.")


class LeaderEditor(tk.Toplevel):

    # "Inherit from" choice of a new leader that inherits from nobody
    NOBODY = "(nobody - a new leader)"
    # "Diplomacy scene" choice: the original leader's / the game's default
    SCENE_DEFAULT = "(the original leader's, or the game's default)"

    def __init__(self, app, spec, title="Leader"):
        super().__init__(app)
        self.app = app
        self.result = None
        # (the uniques' until their tab is built)
        self.spec_uniques = spec.get("uniques") or []
        self.title(title)
        self.resizable(False, False)
        self.transient(app)

        outer = ttk.Frame(self, padding=10)
        outer.pack(fill="both", expand=True)
        notebook = ttk.Notebook(outer)
        notebook.pack(fill="both", expand=True)

        # every tab scrolls if the screen is too small for it
        general = ScrollFrame(notebook, height=None)
        diplo = ScrollFrame(notebook)
        pedia = ScrollFrame(notebook)
        notebook.add(general, text="General")
        portraits = ScrollFrame(notebook)
        notebook.add(portraits, text="Diplomacy portraits")
        ability = ScrollFrame(notebook)
        notebook.add(ability, text="Ability")
        agenda = ScrollFrame(notebook, height=None)
        notebook.add(agenda, text="Agenda")
        uniques = ScrollFrame(notebook, height=None)
        notebook.add(uniques, text="Uniques")
        cities = ScrollFrame(notebook, height=None)
        notebook.add(cities, text="City names")
        notebook.add(diplo, text="Diplomacy text")
        notebook.add(pedia, text="Civilopedia")

        self._build_general(general.inner, spec)
        self._build_portraits(portraits.inner, spec)
        self.on_name_changed()          # show the type right away
        texts = spec_texts(spec)
        self.text_widgets = {}          # tag template -> tk.Text
        self._build_diplo(diplo.inner, texts)
        self._build_pedia(pedia.inner, texts)
        self._build_abilities(ability.inner, spec)
        self._build_agenda(agenda.inner, spec)
        self._build_uniques(uniques.inner, spec)
        self._build_cities(cities.inner, spec)
        # historic moment pictures belong to civilizations now; a leader
        # of a game civilization from an older project keeps its own
        self.moments_frame = None
        if spec.get("moment_illustrations"):
            self.moments_frame = MomentsFrame(
                notebook, spec["moment_illustrations"], self._unique_items,
                help_text=LEGACY_MOMENTS_HELP)
            self.moments_frame.configure(padding=10)
            notebook.add(self.moments_frame, text="Historic moments (old)")

        # -- buttons (packed before the tabs: they keep their place when
        # the window is smaller than the tabs want)
        btns = ttk.Frame(outer)
        btns.pack(side="bottom", anchor="e", pady=(10, 0), before=notebook)
        ttk.Button(btns, text="OK", command=self.on_ok).pack(
            side="left", padx=4)
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(
            side="left", padx=4)

        fit_to_screen(self)
        self.grab_set()
        self.bind("<Return>", self.on_return)
        self.bind("<Escape>", lambda e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    # -- tabs ---------------------------------------------------------------

    def _build_general(self, body, spec):
        pad = {"padx": 6, "pady": 3}

        # -- identity
        row = 0
        ttk.Label(body, text="Name").grid(row=row, column=0, sticky="w",
                                          **pad)
        self.name_var = tk.StringVar(value=spec.get("name", ""))
        self.name_var.trace_add("write", self.on_name_changed)
        ttk.Entry(body, textvariable=self.name_var, width=28).grid(
            row=row, column=1, sticky="w", **pad)
        self.slug_label = ttk.Label(body, text="type: (auto)")
        self.slug_label.grid(row=row, column=2, sticky="w", **pad)

        row += 1
        ttk.Label(body, text="Sex").grid(row=row, column=0, sticky="w", **pad)
        self.sex_var = tk.StringVar(value=spec.get("sex", "Female"))
        ttk.Combobox(body, textvariable=self.sex_var, width=12,
                     values=["Female", "Male"], state="readonly").grid(
            row=row, column=1, sticky="w", **pad)

        # -- civ / original leader
        row += 1
        ttk.Label(body, text="Civilization").grid(row=row, column=0,
                                                  sticky="w", **pad)
        self.civ_var = tk.StringVar(value=spec.get("civ", ""))
        self.civ_combo = ttk.Combobox(body, textvariable=self.civ_var,
                                      width=40,
                                      values=self.app.all_civs())
        self.civ_combo.grid(row=row, column=1, columnspan=2, sticky="w",
                            **pad)
        self.civ_combo.bind("<<ComboboxSelected>>", self.on_civ_changed)

        row += 1
        ttk.Label(body, text="Inherit from").grid(row=row, column=0,
                                                  sticky="w", **pad)
        self.orig_var = tk.StringVar(value=spec.get("orig") or self.NOBODY)
        self.orig_combo = ttk.Combobox(body, textvariable=self.orig_var,
                                       width=40,
                                       values=[self.NOBODY] +
                                       self.app.leaders_for_civ(
                                           self.civ_var.get()))
        self.orig_combo.grid(row=row, column=1, columnspan=2, sticky="w",
                             **pad)
        add_tooltip(self.orig_combo, (
            "The leader whose ability, agenda, AI personality, art and "
            "text this one starts from - or nobody: a new leader with an "
            "ability of its own (Ability tab) and its own agenda and AI "
            "personality (Agenda tab)."))
        row += 1
        self.orig_info = ttk.Label(body, foreground=theme.hint(),
                                   wraplength=900, justify="left")
        self.orig_info.grid(row=row, column=1, columnspan=3, sticky="w",
                            padx=6)
        self.orig_var.trace_add("write", lambda *_: self._refresh_orig_info())
        self._refresh_orig_info()
        self.orig_combo.bind("<<ComboboxSelected>>",
                             lambda e: self.on_orig_selected())

        # -- flavour
        row += 1
        self.bio = tk.Text(body, height=4, width=56, wrap="word")
        self.bio.insert("1.0", spec.get("bio", ""))
        self.quote_var = tk.StringVar(value=spec.get("quote", ""))
        ttk.Label(body, text="Loading bio").grid(row=row, column=0,
                                                 sticky="ne", **pad)
        self.bio.grid(row=row, column=1, columnspan=2, sticky="w", **pad)
        row += 1
        ttk.Label(body, text="Loading quote").grid(row=row, column=0,
                                                   sticky="w", **pad)
        ttk.Entry(body, textvariable=self.quote_var, width=48).grid(
            row=row, column=1, columnspan=2, sticky="w", **pad)
        row += 1

        # -- colors
        self.primary = tuple(spec.get("primary") or (30, 90, 170))
        self.secondary = tuple(spec.get("secondary") or (230, 230, 230))
        ttk.Label(body, text="Primary color").grid(row=row, column=0,
                                                   sticky="w", **pad)
        self.primary_lbl = ttk.Label(body, text="")
        self.primary_lbl.grid(row=row, column=1, sticky="w", **pad)
        ttk.Button(body, text="Pick...",
                   command=lambda: self.pick_color("primary")).grid(
            row=row, column=2, sticky="w", **pad)
        row += 1
        ttk.Label(body, text="Secondary color").grid(row=row, column=0,
                                                     sticky="w", **pad)
        self.secondary_lbl = ttk.Label(body, text="")
        self.secondary_lbl.grid(row=row, column=1, sticky="w", **pad)
        ttk.Button(body, text="Pick...",
                   command=lambda: self.pick_color("secondary")).grid(
            row=row, column=2, sticky="w", **pad)
        self._refresh_swatches()
        row += 1

        # -- images (empty = inherit from the original leader)
        self.icon_path = tk.StringVar(value=spec.get("icon_path", ""))
        self.load_fg_path = tk.StringVar(value=spec.get("load_fg_path", ""))
        self.load_bg_path = tk.StringVar(value=spec.get("load_bg_path", ""))
        self.diplo_bg_path = tk.StringVar(
            value=spec.get("diplo_bg_path", ""))
        for label, var in (
                ("Portrait", self.load_fg_path),
                ("Loading background", self.load_bg_path),
                ("Diplomacy background", self.diplo_bg_path)):
            ttk.Label(body, text=label).grid(row=row, column=0, sticky="w",
                                             **pad)
            entry = ttk.Entry(body, textvariable=var, width=40)
            entry.grid(row=row, column=1, sticky="w", **pad)
            browse = ttk.Button(
                body, text="Browse...",
                command=lambda v=var, t=label: self.browse_image(v, t))
            browse.grid(row=row, column=2, sticky="w", **pad)
            row += 1
        # the loading background (two rows above): the default image
        # instead of one of its own, and a hue shift
        bg_options = ttk.Frame(body)
        bg_options.grid(row=row - 2, column=3, sticky="w", **pad)
        self.load_bg_default = tk.BooleanVar(
            value=bool(spec.get("load_bg_default")))
        default_check = ttk.Checkbutton(
            bg_options, text="Use default background",
            variable=self.load_bg_default,
            command=self._schedule_previews)
        default_check.pack(side="left")
        add_tooltip(default_check, (
            "Without an image of its own, the leader's loading screen "
            "shows assets/{} (instead of the original leader's "
            "background).".format(DEFAULT_LOAD_BG)))
        if not asset_path(DEFAULT_LOAD_BG):
            default_check.state(["disabled"])
            default_check.configure(text="Use default background "
                                         "(assets/{} not found)".format(
                                             DEFAULT_LOAD_BG))
        hue_label = ttk.Label(bg_options, text="Hue (?)")
        hue_label.pack(side="left", padx=(14, 4))
        add_tooltip(hue_label, (
            "Turns the colors of the loading background (its own image or "
            "the default) around the color wheel: 0 keeps them, 120 makes "
            "red green, -120 makes red blue, 180 gives the opposite "
            "colors. Brightness and saturation stay."))
        self.load_bg_hue = tk.IntVar(value=int(spec.get("load_bg_hue") or 0))
        ttk.Scale(bg_options, from_=-180, to=180, length=140,
                  variable=self.load_bg_hue,
                  command=lambda v: self.load_bg_hue.set(
                      int(round(float(v))))).pack(side="left")
        ttk.Spinbox(bg_options, from_=-180, to=180, width=5,
                    textvariable=self.load_bg_hue).pack(side="left", padx=4)
        ttk.Button(bg_options, text="Reset", width=6,
                   command=lambda: self.load_bg_hue.set(0)).pack(side="left")
        self.load_bg_hue.trace_add("write",
                                   lambda *_: self._schedule_previews())
        # optional fade mask for the diplomacy background (last row above)
        self.diplo_bg_mask = tk.BooleanVar(
            value=bool(spec.get("diplo_bg_mask")))
        mask_check = ttk.Checkbutton(body, text="Apply fade mask",
                                     variable=self.diplo_bg_mask)
        mask_check.grid(row=row - 1, column=3, sticky="w", **pad)
        if not asset_path(DIPLO_BG_MASK):
            mask_check.state(["disabled"])
            mask_check.configure(text="Apply fade mask (assets/{} not found)"
                                 .format(DIPLO_BG_MASK))
        # without a diplomacy background: whose layered scene is shown
        ttk.Label(body, text="Diplomacy scene (?)").grid(
            row=row, column=0, sticky="w", **pad)
        scene = (spec.get("scene_leader") or "").strip()
        self.scene_var = tk.StringVar(value=scene or self.SCENE_DEFAULT)
        scene_combo = ttk.Combobox(body, textvariable=self.scene_var,
                                   width=40, values=[self.SCENE_DEFAULT] +
                                   self.app.all_leaders())
        scene_combo.grid(row=row, column=1, sticky="w", **pad)
        add_tooltip(scene_combo, (
            "Shown behind the leader on the diplomacy screen when there is "
            "no diplomacy background image: the layered scene of this game "
            "leader. Default: the original leader's scene, or for a new "
            "leader the game's default scene."))
        row += 1

        # -- leader icon: cut from the loading portrait, or an image file
        self.icon_mode = tk.StringVar(value=spec_icon_mode(spec))
        self.icon_crop = spec.get("icon_crop")
        self.icon_border_color = tuple(spec.get("icon_border_color") or
                                       DEFAULT_ICON_BORDER_COLOR)
        self.icon_border_width = int(spec.get("icon_border_width",
                                              DEFAULT_ICON_BORDER_WIDTH))
        ttk.Label(body, text="Leader icon").grid(row=row, column=0,
                                                 sticky="nw", **pad)
        icon_box = ttk.Frame(body)
        icon_box.grid(row=row, column=1, columnspan=2, sticky="w", **pad)
        modes = ttk.Frame(icon_box)
        modes.grid(row=0, column=0, columnspan=3, sticky="w")
        for text, value in (("Cut from loading portrait", "portrait"),
                            ("Image file", "file")):
            ttk.Radiobutton(modes, text=text, value=value,
                            variable=self.icon_mode,
                            command=self._update_icon_widgets).pack(
                side="left", padx=(0, 12))
        self.icon_thumb = ttk.Label(icon_box)
        self.icon_thumb.grid(row=1, column=0, rowspan=2, sticky="w",
                             pady=(4, 0))
        self.icon_area_btn = ttk.Button(icon_box, text="Choose icon area...",
                                        command=self.choose_icon_area)
        self.icon_area_btn.grid(row=1, column=1, sticky="w", padx=8,
                                pady=(4, 0))
        file_row = ttk.Frame(icon_box)
        file_row.grid(row=2, column=1, columnspan=2, sticky="w", padx=8,
                      pady=(4, 0))
        self.icon_entry = ttk.Entry(file_row, textvariable=self.icon_path,
                                    width=34)
        self.icon_entry.pack(side="left")
        self.icon_browse = ttk.Button(
            file_row, text="Browse...",
            command=lambda: self.browse_image(self.icon_path,
                                              "Leader icon image"))
        self.icon_browse.pack(side="left", padx=(6, 0))
        self._last_fg = self.load_fg_path.get()
        for var in (self.load_fg_path, self.icon_path):
            var.trace_add("write", lambda *_: self._on_icon_source_changed())
        self._update_icon_widgets()

        # -- previews of the chosen images
        row += 1
        previews = ttk.LabelFrame(body, text="Preview", padding=(8, 4))
        previews.grid(row=row, column=0, columnspan=4, sticky="we",
                      padx=6, pady=(10, 3))
        self.preview_labels = {}
        for col, (key, caption) in enumerate((
                ("portrait", "Portrait"),
                ("load_bg", "Loading background"),
                ("diplo_bg", "Diplomacy background"))):
            ttk.Label(previews, text=caption).grid(row=0, column=col,
                                                   sticky="w", padx=6)
            frame = tk.Frame(previews, width=PREVIEW_BOX[0],
                             height=PREVIEW_BOX[1],
                             background="#%02x%02x%02x" %
                             PREVIEW_BACKDROP[:3])
            frame.grid(row=1, column=col, padx=6, pady=(2, 4))
            frame.grid_propagate(False)
            frame.pack_propagate(False)
            label = tk.Label(frame, background=frame["background"],
                             foreground="#bbbbbb", justify="center",
                             wraplength=PREVIEW_BOX[0] - 16)
            label.pack(fill="both", expand=True)
            self.preview_labels[key] = label
        self._preview_photos = {}
        mask_check.configure(command=self._refresh_previews)
        for var in (self.load_fg_path, self.load_bg_path,
                    self.diplo_bg_path, self.orig_var):
            var.trace_add("write", lambda *_: self._schedule_previews())
        self._refresh_previews()

    def _schedule_previews(self):
        """Refresh the previews once typing in a path field pauses."""
        if getattr(self, "_preview_job", None):
            self.after_cancel(self._preview_job)
        self._preview_job = self.after(250, self._refresh_previews)

    def _refresh_previews(self):
        self._preview_job = None
        inherited = "(inherited from {})".format(
            type_display_name(self._orig())) if self._orig() else "(none)"
        mask = asset_path(DIPLO_BG_MASK) if self.diplo_bg_mask.get() \
            else None
        load_bg = self.load_bg_path.get().strip()
        if not load_bg and self.load_bg_default.get():
            load_bg = asset_path(DEFAULT_LOAD_BG) or ""
        sources = {
            "portrait": (self.load_fg_path.get().strip(), None, True, 0),
            "load_bg": (load_bg, None, False, self._load_bg_hue()),
            "diplo_bg": (self.diplo_bg_path.get().strip(), mask, False, 0),
        }
        for key, (path, mask_path, portrait, hue) in sources.items():
            photo, text = None, inherited
            try:
                from PIL import ImageTk
                if path and not os.path.isfile(path):
                    text = "(file not found)"
                img = preview_image(path, PREVIEW_BOX, mask_path, portrait,
                                    hue)
                if img is not None:
                    photo = ImageTk.PhotoImage(img)
            except ImportError:
                text = "(install Pillow for a preview)"
            except Exception as exc:    # unreadable image
                text = "(cannot preview: {})".format(exc)
            self._preview_photos[key] = photo
            self.preview_labels[key].configure(image=photo or "",
                                               text="" if photo else text)
        if getattr(self, "mood_thumbs", None):  # (built after this tab)
            self._refresh_mood_thumbs()

    def _load_bg_hue(self):
        """The hue shift in degrees (0 while the field is being typed)."""
        try:
            return max(-180, min(180, int(self.load_bg_hue.get())))
        except (tk.TclError, ValueError):
            return 0

    # thumbnails of the diplomacy portraits (fitted to 800 x 1080)
    MOOD_THUMB = (48, 64)
    # the cycling preview next to them, and how long it shows each image
    MOOD_CYCLE_BOX = (240, 324)
    MOOD_CYCLE_MS = 1500

    def _build_portraits(self, body, spec):
        """One image per slot of MOOD_SLOTS; the neutral one is the
        General tab's portrait."""
        pad = {"padx": 6, "pady": 2}
        ttk.Label(body, text=PORTRAITS_HELP, wraplength=820,
                  justify="left").grid(row=0, column=0, columnspan=6,
                                       sticky="w", pady=(0, 4))
        given = spec.get("mood_images") or {}
        self.mood_vars, self.mood_thumbs, self.mood_notes = {}, {}, {}
        self._mood_photos = {}
        row = 1
        for group, title in MOOD_GROUPS:
            ttk.Label(body, text=title, font=("TkDefaultFont", 10, "bold")
                      ).grid(row=row, column=0, columnspan=6, sticky="w",
                             pady=(10, 2))
            row += 1
            for key, slot_group, label, tip, _, _ in MOOD_SLOTS:
                if slot_group != group:
                    continue
                name = ttk.Label(body, text=label + " (?)")
                name.grid(row=row, column=0, sticky="w", padx=(12, 6),
                          pady=2)
                add_tooltip(name, tip)
                frame = tk.Frame(body, width=self.MOOD_THUMB[0],
                                 height=self.MOOD_THUMB[1],
                                 background="#%02x%02x%02x" %
                                 PREVIEW_BACKDROP[:3])
                frame.grid(row=row, column=1, **pad)
                frame.pack_propagate(False)
                thumb = tk.Label(frame, background=frame["background"])
                thumb.pack(fill="both", expand=True)
                self.mood_thumbs[key] = thumb
                if key == "NEUTRAL":        # set on the General tab
                    ttk.Entry(body, textvariable=self.load_fg_path, width=50,
                              state="readonly").grid(row=row, column=2,
                                                     sticky="w", **pad)
                else:
                    var = tk.StringVar(value=given.get(key, ""))
                    self.mood_vars[key] = var
                    ttk.Entry(body, textvariable=var, width=50).grid(
                        row=row, column=2, sticky="w", **pad)
                    ttk.Button(
                        body, text="Browse...",
                        command=lambda v=var, t=label: self.browse_image(
                            v, t + " diplomacy portrait")).grid(
                        row=row, column=3, sticky="w", **pad)
                    ttk.Button(body, text="Clear", width=6,
                               command=lambda v=var: v.set("")).grid(
                        row=row, column=4, sticky="w", **pad)
                    var.trace_add("write",
                                  lambda *_: self._schedule_previews())
                note = ttk.Label(body, foreground=theme.hint())
                note.grid(row=row, column=5, sticky="w", **pad)
                self.mood_notes[key] = note
                row += 1

        # -- a larger preview to the right, cycling through the slots that
        # have their own image
        cycle = ttk.Frame(body)
        cycle.grid(row=1, column=6, rowspan=row - 1, sticky="n",
                   padx=(16, 0), pady=(10, 0))
        # (on the window's own colour, so transparent parts look it)
        r, g, b = (c // 257 for c in self.winfo_rgb(
            ttk.Style(self).lookup("TFrame", "background") or
            self.cget("background")))
        self._mood_cycle_backdrop = (r, g, b, 255)
        frame = tk.Frame(cycle, width=self.MOOD_CYCLE_BOX[0],
                         height=self.MOOD_CYCLE_BOX[1],
                         background="#%02x%02x%02x" % (r, g, b))
        frame.pack()
        frame.pack_propagate(False)
        self.mood_cycle_image = tk.Label(
            frame, background=frame["background"], foreground=theme.hint(),
            justify="center", wraplength=self.MOOD_CYCLE_BOX[0] - 16)
        self.mood_cycle_image.pack(fill="both", expand=True)
        self.mood_cycle_caption = ttk.Label(cycle, foreground=theme.hint())
        self.mood_cycle_caption.pack(pady=(4, 0))
        self._mood_cycle_index = 0
        self._mood_cycle_photo = None
        self._refresh_mood_thumbs()
        self._cycle_mood_preview()

    def _cycle_mood_preview(self):
        """Show the next slot with its own image, then come back later."""
        if not self.winfo_exists():
            return
        paths = {key: var.get().strip()
                 for key, var in self.mood_vars.items()}
        paths["NEUTRAL"] = self.load_fg_path.get().strip()
        shown = [key for key, *_ in MOOD_SLOTS
                 if paths.get(key) and os.path.isfile(paths[key])]
        photo, text, caption = None, "(no portraits yet)", ""
        if shown:
            index = self._mood_cycle_index % len(shown)
            self._mood_cycle_index = index + 1
            key = shown[index]
            caption = "{} ({}/{})".format(mood_label(key), index + 1,
                                         len(shown))
            try:
                from PIL import ImageTk
                img = preview_image(paths[key], self.MOOD_CYCLE_BOX,
                                    portrait=True,
                                    backdrop=self._mood_cycle_backdrop)
                if img is not None:
                    photo = ImageTk.PhotoImage(img)
            except ImportError:
                text = "(install Pillow for a preview)"
            except Exception as exc:    # unreadable image
                text = "(cannot preview: {})".format(exc)
        self._mood_cycle_photo = photo
        self.mood_cycle_image.configure(image=photo or "",
                                        text="" if photo else text)
        self.mood_cycle_caption.configure(text=caption)
        self.after(self.MOOD_CYCLE_MS, self._cycle_mood_preview)

    def _refresh_mood_thumbs(self):
        """Each slot's thumbnail shows what the diplomacy screen would: its
        own image, or (noted in grey) the one it falls back to."""
        paths = {key: var.get().strip()
                 for key, var in self.mood_vars.items()}
        paths["NEUTRAL"] = self.load_fg_path.get().strip()
        filled = {key for key, path in paths.items() if path}
        for key, thumb in self.mood_thumbs.items():
            shown = resolve_slot(key, filled)
            if key == "NEUTRAL":
                note = "the Portrait (General tab)" if paths[key] else \
                    "no Portrait: set one on the General tab first"
            else:
                note = "" if paths[key] else "uses: " + mood_label(shown)
            photo = None
            try:
                from PIL import ImageTk
                if paths[key] and not os.path.isfile(paths[key]):
                    note = "(file not found)"
                img = preview_image(paths[shown], self.MOOD_THUMB,
                                    portrait=True)
                if img is not None:
                    photo = ImageTk.PhotoImage(img)
            except ImportError:
                pass                    # no thumbnails without Pillow
            except Exception as exc:    # unreadable image
                note = "(cannot preview: {})".format(exc)
            self._mood_photos[key] = photo
            thumb.configure(image=photo or "")
            self.mood_notes[key].configure(text=note)

    def _text_field(self, parent, key, label, height, texts, row):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="nw",
                                           padx=(12, 6), pady=3)
        widget = tk.Text(parent, height=height, width=78, wrap="word",
                         undo=True)
        widget.insert("1.0", texts.get(key, ""))
        widget.grid(row=row, column=1, sticky="w", pady=3)
        self.text_widgets[key] = widget

    def _tab_header(self, parent, hint):
        ttk.Label(parent, text=hint, wraplength=820, justify="left").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
        btns = ttk.Frame(parent)
        btns.grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 6))
        ttk.Button(btns, text="Copy original leader's text into empty "
                              "fields", command=self.copy_original_text
                   ).pack(side="left")
        ttk.Button(btns, text="Copy all text as JSON",
                   command=self.export_texts_json).pack(side="left",
                                                        padx=(12, 0))
        ttk.Button(btns, text="Paste text from JSON",
                   command=self.import_texts_json).pack(side="left",
                                                        padx=(6, 0))
        return 2

    def _build_diplo(self, parent, texts):
        row = self._tab_header(
            parent, "Lines left empty reuse the original leader's line "
                    "(for HAPPY/UNHAPPY lines: the same mood, otherwise its "
                    "any-mood line). Use [NEWLINE] or line breaks for new "
                    "lines, and {LOC_...} to reference another text.")
        for section, lines in DIPLO_TEXT:
            ttk.Label(parent, text=section, font=("TkDefaultFont", 10,
                                                  "bold")).grid(
                row=row, column=0, columnspan=2, sticky="w", pady=(10, 2))
            row += 1
            for key, label in lines:
                self._text_field(parent, key, label, 2, texts, row)
                row += 1

    def _build_pedia(self, parent, texts):
        row = self._tab_header(
            parent, "Civilopedia leader page. The summary and detailed "
                    "approach reuse the original leader's text when empty "
                    "(the ability is the same); title, subtitle, quote and "
                    "history are only written when filled in.")
        for key, label, height, _ in PEDIA_TEXT:
            self._text_field(parent, key, label, height, texts, row)
            row += 1

    # -- events -------------------------------------------------------------

    def on_return(self, event):
        # Return inserts a newline in text boxes; elsewhere it means OK
        if not isinstance(event.widget, tk.Text):
            self.on_ok()

    def on_name_changed(self, *_):
        slug = slug_for_name(self.name_var.get(), self.app.type_prefix())
        self.slug_label.config(
            text="type: " + slug if slug else "type: (type a name)")

    def on_civ_changed(self, *_):
        self.orig_combo["values"] = [self.NOBODY] + self.app.leaders_for_civ(
            self.civ_var.get())
        self._refresh_moment_items()

    def _orig(self):
        """The leader to inherit from, "" = nobody (a new leader)."""
        text = self.orig_var.get().strip()
        return "" if text == self.NOBODY else text

    def _refresh_orig_info(self):
        self.orig_info.configure(text=(
            "A new leader: give it an ability of its own (Ability tab), an "
            "AI agenda and personality (Agenda tab). Empty diplomacy lines "
            "use the game's generic lines; without images the leader has "
            "the default icon and an empty portrait." if not self._orig()
            else ""))
        if hasattr(self, "icon_thumb"):     # (built after this)
            self._refresh_icon_thumb()

    def on_orig_selected(self):
        """Picking the leader to inherit from also takes its colors."""
        self._refresh_moment_items()
        colors = self.app.data.colors(self._orig())
        if colors:
            self.primary, self.secondary = colors
            self._refresh_swatches()

    # -- agenda -------------------------------------------------------------

    AGENDA_INHERIT = "(inherit from original leader)"
    # (advanced mode, see agendas.py)
    AGENDA_OWN = "(an agenda of its own: the likes and dislikes below)"

    def _agenda_label(self, agenda):
        """Combobox text for an agenda type: 'Iron Crown (AGENDA_IRON_CROWN)
        - Frederick Barbarossa' (or '- random' if no leader has it)."""
        info = self.app.data.agendas.get(agenda)
        if not info:
            return agenda
        data = self.app.data
        names = []
        for leader in info["leaders"]:
            name = data.meta(leader).get("name") or ""   # text or its tag
            if name.startswith("LOC_"):
                name = data.loc_text(name) or type_display_name(leader)
            names.append(name or type_display_name(leader))
        leaders = ", ".join(names) or "random"
        return "{} ({}) - {}".format(info["name"], agenda, leaders)

    def _agenda_type(self):
        """Agenda type picked (or typed) in the combobox, "" = inherit."""
        text = self.agenda_var.get().strip()
        if not text or text in (self.AGENDA_INHERIT, self.AGENDA_OWN):
            return ""
        m = re.search(r"\((AGENDA_[A-Z0-9_]+)\)", text)
        return m.group(1) if m else text.upper()

    def _own_agenda(self):
        """Whether the leader gets an agenda of its own."""
        return self.agenda_var.get().strip() == self.AGENDA_OWN

    def _source_agenda(self):
        """The agenda the leader gets (or copies): picked or inherited."""
        return (self._agenda_type() or
                self.app.data.historical_agenda(self._orig()))

    def _build_agenda(self, parent, spec):
        pad = {"padx": 6, "pady": 3}
        ttk.Label(parent, wraplength=760, justify="left", text=(
            "The AI agenda this leader plays by: the original leader's, or "
            "any agenda the game already defines. A new name and/or "
            "description gives this leader its own copy of the agenda - "
            "same behaviour, different text; empty fields keep the "
            "agenda's own text. The reasons the AI gives for liking or "
            "disliking you are on the Diplomacy text tab (Kudos & "
            "warnings).")).grid(row=0, column=0, columnspan=2, sticky="w",
                                pady=(0, 10))
        ttk.Label(parent, text="Agenda").grid(row=1, column=0, sticky="w",
                                              **pad)
        agenda = (spec.get("agenda") or "").strip()
        own = spec.get("own_agenda") or None
        advanced = bool(self.app.advanced_var.get()) \
            if hasattr(self.app, "advanced_var") else False
        self.agenda_var = tk.StringVar(
            value=self.AGENDA_OWN if own else self._agenda_label(agenda)
            if agenda else self.AGENDA_INHERIT)
        combo = ttk.Combobox(
            parent, textvariable=self.agenda_var, width=70,
            values=[self.AGENDA_INHERIT] +
            ([self.AGENDA_OWN] if advanced or own else []) + [
                self._agenda_label(a) for a in sorted(
                    self.app.data.agendas,
                    key=lambda a: self.app.data.agendas[a]["name"])])
        combo.grid(row=1, column=1, sticky="w", **pad)
        self.agenda_info = ttk.Label(parent, wraplength=560, justify="left",
                                     foreground=theme.hint())
        self.agenda_info.grid(row=2, column=1, sticky="w", **pad)

        self.agenda_name_label = ttk.Label(parent, text="New name")
        self.agenda_name_label.grid(row=3, column=0, sticky="w", **pad)
        self.agenda_name_var = tk.StringVar(
            value=own["name"] if own else spec.get("agenda_name", ""))
        ttk.Entry(parent, textvariable=self.agenda_name_var, width=40).grid(
            row=3, column=1, sticky="w", **pad)
        self.agenda_desc_label = ttk.Label(parent, text="New description")
        self.agenda_desc_label.grid(row=4, column=0, sticky="nw", **pad)
        box, self.agenda_desc = icon_text(parent, height=4, width=70,
                                          wrap="word", undo=True)
        self.agenda_desc.insert("1.0", own.get("desc", "") if own
                                else spec.get("agenda_desc", ""))
        box.grid(row=4, column=1, sticky="w", **pad)
        self.agenda_copy_btn = ttk.Button(
            parent, text="Copy agenda's text into empty fields",
            command=self.copy_agenda_text)
        self.agenda_copy_btn.grid(row=5, column=1, sticky="w", **pad)

        # an agenda of its own: its likes and dislikes (advanced mode)
        self.reactions_box = ttk.LabelFrame(parent, text="Likes and "
                                            "dislikes", padding=(8, 4))
        self.reactions_box.grid(row=6, column=0, columnspan=2, sticky="we",
                                pady=(12, 0))
        ttk.Label(self.reactions_box, wraplength=760, justify="left",
                  foreground=theme.hint(), text=(
                      "What this leader likes and dislikes in other "
                      "civilizations, and how much. An empty description "
                      "lists the likes' and dislikes' texts." if advanced
                      else "Turn on Advanced mode in the toolbar to edit "
                      "the likes and dislikes.")).pack(anchor="w",
                                                       pady=(0, 4))
        self.reactions = ReactionsFrame(
            self.reactions_box, self.app, (own or {}).get("reactions"),
            editable=advanced)
        self.reactions.pack(anchor="w", fill="x")

        # the AI personality of a new leader (one inheriting has the
        # original leader's)
        self.ai_box = ttk.LabelFrame(parent, text="AI personality",
                                     padding=(8, 4))
        self.ai_box.grid(row=7, column=0, columnspan=2, sticky="we",
                         pady=(12, 0))
        self.ai_info = ttk.Label(self.ai_box, foreground=theme.hint(),
                                 wraplength=760, justify="left")
        self.ai_info.grid(row=0, column=0, columnspan=3, sticky="w",
                          pady=(0, 4))
        chosen = spec.get("ai_traits")
        if chosen is None:
            chosen = DEFAULT_AI_TRAITS
        self.ai_vars = {}
        for i, (trait, label, tip) in enumerate(AI_TRAITS):
            var = tk.BooleanVar(value=trait in chosen)
            check = ttk.Checkbutton(self.ai_box, text=label, variable=var)
            check.grid(row=1 + i // 3, column=i % 3, sticky="w",
                       padx=(0, 18), pady=1)
            add_tooltip(check, "{} - {}".format(trait, tip))
            self.ai_vars[trait] = (var, check)
        self.orig_var.trace_add("write", lambda *_: self._refresh_ai_box())
        self._refresh_ai_box()

        self.agenda_var.trace_add("write",
                                  lambda *_: self._refresh_agenda_info())
        self.orig_var.trace_add("write",
                                lambda *_: self._refresh_agenda_info())
        self._refresh_agenda_info()

    def _refresh_ai_box(self):
        new = not self._orig()
        self.ai_info.configure(text=(
            "How the AI plays this leader, besides its agenda. Tick none "
            "for a balanced AI." if new else
            "Inherited from the original leader (these are only used for "
            "a leader that inherits from nobody)."))
        for var, check in self.ai_vars.values():
            check.state(["!disabled"] if new else ["disabled"])

    def ai_traits(self):
        return [t for t, (var, _) in self.ai_vars.items() if var.get()]

    def _scene_leader(self):
        text = self.scene_var.get().strip()
        return "" if text == self.SCENE_DEFAULT else text.upper()

    def _build_abilities(self, parent, spec):
        ttk.Label(parent, wraplength=760, justify="left", text=(
            "The leader ability is inherited from the original leader. A "
            "new name and/or description gives this leader its own copy of "
            "it - same effects, different text; empty fields keep the "
            "ability's own text.")).grid(row=0, column=0, sticky="w",
                                         pady=(0, 10))
        self.ability_frame = ttk.Frame(parent)
        self.ability_frame.grid(row=1, column=0, sticky="nw")
        # typed text per trait, kept while the original leader changes
        self.ability_texts = {trait: dict(text) for trait, text in
                              (spec.get("abilities") or {}).items()}
        self.ability_widgets = {}       # trait -> (name var, tk.Text)
        self.orig_var.trace_add("write", lambda *_: self._refresh_abilities())
        self._refresh_abilities()
        self._build_new_ability(parent, spec)

    def _build_new_ability(self, parent, spec):
        """A new ability of the leader's own, made of effects."""
        pad = {"padx": 6, "pady": 3}
        new = spec.get("new_ability") or {}
        box = ttk.LabelFrame(parent, padding=(8, 4))
        box.grid(row=2, column=0, sticky="we", pady=(12, 0))
        self.new_ability_box = box
        ttk.Label(box, text="Name").grid(row=0, column=0, sticky="w", **pad)
        self.new_ability_name = tk.StringVar(value=new.get("name", ""))
        ttk.Entry(box, textvariable=self.new_ability_name, width=40).grid(
            row=0, column=1, sticky="w", **pad)
        self.new_ability_replace = tk.BooleanVar(
            value=bool(new.get("replace")))
        self.new_ability_replace_check = ttk.Checkbutton(
            box, variable=self.new_ability_replace, text=(
                "Replaces the inherited abilities (keeps the original "
                "leader's unique items and AI preferences)"))
        self.new_ability_replace_check.grid(row=0, column=2, sticky="w",
                                            **pad)
        ttk.Label(box, text="Description").grid(row=1, column=0,
                                                sticky="nw", **pad)
        desc_box, self.new_ability_desc = icon_text(
            box, buttons=[("Write from effects",
                           self.write_ability_description, WRITE_TIP)],
            height=3, width=80, wrap="word", undo=True)
        self.new_ability_desc.insert("1.0", new.get("desc", ""))
        desc_box.grid(row=1, column=1, columnspan=2, sticky="w", **pad)
        ttk.Label(box, text="(empty: a list of its effects)",
                  foreground=theme.hint()).grid(row=2, column=1, sticky="w",
                                            padx=6)
        self.new_ability_effects = EffectsFrame(box, self.app, "trait",
                                                new.get("effects"),
                                                self._unique_types)
        self.new_ability_effects.grid(row=3, column=0, columnspan=3,
                                      sticky="we", pady=(6, 0))
        self.new_ability_effects.listbox.configure(height=5)
        self.orig_var.trace_add("write",
                                lambda *_: self._refresh_new_ability_box())
        self._refresh_new_ability_box()

    def _refresh_new_ability_box(self):
        new = not self._orig()
        self.new_ability_box.configure(
            text="The leader's ability (required for a new leader)" if new
            else "New ability of its own (optional)")
        self.new_ability_replace_check.state(
            ["disabled"] if new else ["!disabled"])

    def write_ability_description(self):
        write_description(self.new_ability_desc, describe_effects(
            self.new_ability_effects.effects(), self.app.data.type_name),
            self)

    def new_ability(self):
        effects = self.new_ability_effects.effects()
        name = self.new_ability_name.get().strip()
        if not name and not effects:
            return {}
        return {"name": name,
                "desc": self.new_ability_desc.get("1.0", "end").strip(),
                "replace": bool(self.new_ability_replace.get()),
                "effects": effects}

    def _shown_abilities(self):
        """[(trait, info or None)] for the tab: the original leader's
        abilities from the game cache, or (without it) the traits this
        leader already renames."""
        orig = self._orig()
        data = self.app.data
        if data.conn:
            return [(a["type"], a) for a in data.abilities(orig)]
        return [(trait, None) for trait in sorted(self.ability_texts)]

    def _store_ability_texts(self):
        for trait, (name_var, desc) in self.ability_widgets.items():
            self.ability_texts[trait] = {
                "name": name_var.get().strip(),
                "desc": desc.get("1.0", "end").strip()}

    def _refresh_abilities(self):
        self._store_ability_texts()
        frame = self.ability_frame
        for widget in frame.winfo_children():
            widget.destroy()
        self.ability_widgets = {}
        pad = {"padx": 6, "pady": 3}
        shown = self._shown_abilities()
        if not shown:
            orig = self._orig()
            if not self.app.data.conn:
                text = ("(load the game cache to list the original leader's "
                        "abilities)")
            elif not orig:
                text = ("A new leader inherits no ability: give it one of "
                        "its own below.")
            else:
                text = ("{} has no ability that can be renamed (it only "
                        "unlocks a unique item, or is not in the loaded game "
                        "data).".format(type_display_name(orig)))
            ttk.Label(frame, text=text, foreground=theme.hint()).grid(
                row=0, column=0, sticky="w", **pad)
            return
        row = 0
        for trait, info in shown:
            ttk.Label(frame, text="{} ({})".format(info["name"], trait)
                      if info else trait,
                      font=("TkDefaultFont", 10, "bold")).grid(
                row=row, column=0, columnspan=2, sticky="w",
                pady=(10 if row else 0, 2))
            row += 1
            if info and info["desc"]:
                ttk.Label(frame, text=info["desc"].replace("[NEWLINE]", "\n"),
                          wraplength=560, justify="left",
                          foreground=theme.hint()).grid(row=row, column=1,
                                                    sticky="w", **pad)
                row += 1
            text = self.ability_texts.get(trait) or {}
            ttk.Label(frame, text="New name").grid(row=row, column=0,
                                                   sticky="w", **pad)
            name_var = tk.StringVar(value=text.get("name", ""))
            ttk.Entry(frame, textvariable=name_var, width=40).grid(
                row=row, column=1, sticky="w", **pad)
            row += 1
            ttk.Label(frame, text="New description").grid(
                row=row, column=0, sticky="nw", **pad)
            desc_box, desc = icon_text(frame, height=4, width=70,
                                       wrap="word", undo=True)
            desc.insert("1.0", text.get("desc", ""))
            desc_box.grid(row=row, column=1, sticky="w", **pad)
            row += 1
            self.ability_widgets[trait] = (name_var, desc)
        if any(info for _, info in shown):
            ttk.Button(frame, text="Copy the ability's text into empty "
                       "fields", command=self.copy_ability_text).grid(
                row=row, column=1, sticky="w", **pad)

    def copy_ability_text(self):
        """Fill the empty names / descriptions with the abilities' English
        text, so it can be edited instead of retyped."""
        for trait, info in self._shown_abilities():
            name_var, desc = self.ability_widgets[trait]
            if not info:
                continue
            if not name_var.get().strip():
                name_var.set(info["name"])
            if not desc.get("1.0", "end").strip():
                desc.insert("1.0", info["desc"].replace("[NEWLINE]", "\n"))

    def abilities(self):
        """{trait: {"name", "desc"}} of the shown abilities with new text."""
        self._store_ability_texts()
        shown = {trait for trait, _ in self._shown_abilities()}
        return {trait: text for trait, text in self.ability_texts.items()
                if trait in shown and (text.get("name") or text.get("desc"))}

    def _build_cities(self, parent, spec):
        ttk.Label(parent, wraplength=760, justify="left", text=(
            "This leader's own city names, one per line. The first one is "
            "the capital; new cities take the next name on the list, and "
            "once it runs out the civilization's own names are used. Leave "
            "the list empty to use the civilization's names and the "
            "original leader's capital.")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))
        box = ttk.Frame(parent)
        box.grid(row=1, column=0, sticky="nw")
        self.city_text = tk.Text(box, height=22, width=40, wrap="none",
                                 undo=True)
        bar = ttk.Scrollbar(box, orient="vertical",
                            command=self.city_text.yview)
        self.city_text.configure(yscrollcommand=bar.set)
        self.city_text.pack(side="left", fill="y")
        bar.pack(side="left", fill="y")
        self.city_text.insert("1.0", "\n".join(spec.get("city_names") or []))
        self.city_text.bind("<<Modified>>", self._on_cities_modified)

        side = ttk.Frame(parent)
        side.grid(row=1, column=1, sticky="nw", padx=(16, 0))
        self.city_count = ttk.Label(side, justify="left")
        self.city_count.pack(anchor="w")
        ttk.Button(side, text="Copy the civilization's city names",
                   command=self.copy_civ_city_names).pack(anchor="w",
                                                          pady=(10, 0))
        ttk.Button(side, text="Clear", command=lambda: self.city_text.delete(
            "1.0", "end")).pack(anchor="w", pady=(6, 0))
        self._refresh_city_count()

    def city_names(self):
        return [line.strip() for line in
                self.city_text.get("1.0", "end").splitlines()
                if line.strip()]

    def _on_cities_modified(self, _event=None):
        self.city_text.edit_modified(False)     # re-arm <<Modified>>
        self._refresh_city_count()

    def _refresh_city_count(self):
        names = self.city_names()
        self.city_count.configure(
            text="{} names\nCapital: {}".format(len(names), names[0])
            if names else "No names: using the civilization's")

    def copy_civ_city_names(self):
        civ = self.civ_var.get().strip()
        names = self.app.data.city_names(civ)
        if not names:
            messagebox.showinfo(
                "No city names", "No city names found for {}. Load the "
                "game cache first (main window).".format(civ or "(no civ)"),
                parent=self)
            return
        if self.city_names() and not messagebox.askyesno(
                "Replace city names", "Replace the list with the {} names "
                "of {}?".format(len(names), civ), parent=self):
            return
        self.city_text.delete("1.0", "end")
        self.city_text.insert("1.0", "\n".join(names))

    def _refresh_agenda_info(self):
        own = self._own_agenda()
        self.agenda_name_label.configure(text="Name" if own else "New name")
        self.agenda_desc_label.configure(text="Description" if own
                                         else "New description")
        if own:
            self.reactions_box.grid()
            self.agenda_copy_btn.grid_remove()
            self.agenda_info.configure(text=(
                "An agenda of this leader's own: give it a name and its "
                "likes and dislikes."))
            return
        self.reactions_box.grid_remove()
        self.agenda_copy_btn.grid()
        agenda = self._source_agenda()
        info = self.app.data.agendas.get(agenda or "")
        if info:
            text = "{}: {}".format(info["name"], info["desc"])
            if not self._agenda_type():
                text = "Inherited - " + text
        elif agenda:
            text = "{} (not in the loaded game data)".format(agenda)
        elif self.app.data.conn:
            text = ("A new leader needs an agenda: pick one." if not
                    self._orig() else
                    "(pick the leader to inherit from on the General tab)")
        else:
            text = ("(load the game cache to list the agendas - or type an "
                    "AGENDA_ type)")
        self.agenda_info.configure(text=text)

    def copy_agenda_text(self):
        """Fill the empty name / description with the agenda's English
        text, so it can be edited instead of retyped."""
        info = self.app.data.agendas.get(self._source_agenda() or "")
        if not info:
            messagebox.showinfo("No agenda text",
                                "Load the game cache and pick an agenda (or "
                                "the leader to inherit from) first.",
                                parent=self)
            return
        if not self.agenda_name_var.get().strip():
            self.agenda_name_var.set(info["name"])
        if not self.agenda_desc.get("1.0", "end").strip():
            self.agenda_desc.insert("1.0",
                                    info["desc"].replace("[NEWLINE]", "\n"))

    def _unique_items(self):
        civ, orig = self.civ_var.get().strip(), self._orig()
        mine = [t for kind in KINDS for t, _ in self._own_unique_types(kind)]
        own = self.app.project_civ_uniques(civ)
        if own is not None:             # one of the project's civilizations
            return mine + own + self.app.data.leader_unique_items(orig)
        return mine + self.app.data.uniques_for(civ, orig)

    # -- uniques of its own -------------------------------------------------

    def _build_uniques(self, parent, spec):
        self.unique_frame = UniquesFrame(
            parent, self.app, spec.get("uniques"),
            lambda: self.name_var.get().strip(), (
                "Unique units, buildings, districts and improvements of "
                "this leader's own, like the game's leader uniques (Teddy "
                "Roosevelt's Rough Rider): a player with this leader has "
                "them on top of the civilization's. Each is a copy of an "
                "existing one (its 3D art and icons too) with your "
                "changes, and normally replaces it for this leader."),
            others=self._civ_unique_types, changed=self._refresh_moment_items,
            renamed=self._retarget)
        self.unique_frame.pack(fill="both", expand=True)

    def _own_unique_types(self, kind):
        frame = getattr(self, "unique_frame", None)
        if frame is None:               # (still building the tabs)
            return unique_choices(self.spec_uniques, kind,
                                  self.app.type_prefix())
        return frame.own_types(kind)

    def _civ_unique_types(self, kind):
        """The uniques of the leader's civilization, if one of the
        project's (a building of the leader's may be built in its
        district, say)."""
        civ = self.app.project_civs().get(self.civ_var.get().strip())
        return unique_choices((civ or {}).get("uniques"), kind,
                              self.app.type_prefix())

    def _unique_types(self, kind):
        """The leader's own uniques of a kind and its civilization's, for
        effect dropdowns."""
        own = self._own_unique_types(kind)
        known = {t for t, _ in own}
        return own + [c for c in self._civ_unique_types(kind)
                      if c[0] not in known]

    def _retarget(self, mapping):
        """References to a renamed unique of the leader's (its ability's
        effects, moment pictures) follow it."""
        retarget(self.new_ability_effects.items, mapping)
        self.new_ability_effects.refresh()
        if self.moments_frame:
            for row in self.moments_frame.rows:
                item = row["item"].get().strip().upper()
                if item in mapping:
                    row["item"].set(mapping[item])
        self._refresh_moment_items()

    def _refresh_moment_items(self):
        if getattr(self, "moments_frame", None):
            self.moments_frame.refresh_items()

    def copy_original_text(self):
        """Fill empty text boxes with the original leader's English text
        (from the game cache), so it can be edited instead of retyped."""
        # a new leader: the game's generic lines
        orig = self._orig() or "ANY"
        if not self.app.data.loc_conn:
            messagebox.showinfo("Game text not loaded",
                                "Load the game cache first (\"Load from game "
                                "cache...\" in the main window).",
                                parent=self)
            return
        filled = 0
        for key, widget in self.text_widgets.items():
            if widget.get("1.0", "end").strip():
                continue
            if key == PEDIA_HISTORY:
                paras = []
                while True:
                    text = self.app.data.loc_text("{}_PARA_{}".format(
                        key.format(L=orig), len(paras) + 1))
                    if not text:
                        break
                    paras.append(text)
                text = "\n\n".join(paras)
            else:
                text = next(filter(None, (
                    self.app.data.loc_text(c.format(L=orig))
                    for c in inherit_candidates(key))), None)
            if text:
                widget.insert("1.0", text.replace("[NEWLINE]", "\n"))
                filled += 1
        messagebox.showinfo("Text copied",
                            "Filled {} empty field(s) with the text of {}."
                            .format(filled, orig if orig != "ANY" else
                                    "the game's generic lines"),
                            parent=self)

    def current_texts(self):
        texts = {}
        for key, widget in self.text_widgets.items():
            text = widget.get("1.0", "end").strip()
            if text:
                texts[key] = text
        return texts

    def export_texts_json(self):
        """Put every diplomacy / Civilopedia line on the clipboard as
        JSON (both tabs, empty lines included)."""
        self.clipboard_clear()
        self.clipboard_append(texts_to_json(self.current_texts()))
        self.update()        # keep the clipboard content after closing
        messagebox.showinfo(
            "Copied", "All {} text fields were copied to the clipboard as "
            "JSON. Keys use {{L}} for the leader type.".format(
                len(self.text_widgets)), parent=self)

    def import_texts_json(self):
        """Fill text fields from JSON on the clipboard; only the lines it
        contains are changed."""
        try:
            data = self.clipboard_get()
        except tk.TclError:
            messagebox.showwarning("Nothing to paste",
                                   "The clipboard does not contain text.",
                                   parent=self)
            return
        try:
            texts, unknown = texts_from_json(data)
        except ValueError as exc:
            messagebox.showwarning("Could not paste", str(exc), parent=self)
            return
        for key, text in texts.items():
            widget = self.text_widgets[key]
            widget.delete("1.0", "end")
            widget.insert("1.0", text.replace("[NEWLINE]", "\n"))
        message = "Updated {} text field(s).".format(len(texts))
        if unknown:
            message += ("\n\n{} unrecognized key(s) were ignored:\n{}".format(
                len(unknown), "\n".join(unknown[:10])) +
                ("\n..." if len(unknown) > 10 else ""))
        messagebox.showinfo("Pasted", message, parent=self)

    # -- leader icon ----------------------------------------------------------

    def _on_icon_source_changed(self):
        # a different portrait invalidates the circle chosen on the old one
        if self.load_fg_path.get() != self._last_fg:
            self._last_fg = self.load_fg_path.get()
            self.icon_crop = None
        self._update_icon_widgets()

    def _update_icon_widgets(self):
        portrait = self.icon_mode.get() == "portrait"
        self.icon_area_btn.state(["!disabled"] if portrait else ["disabled"])
        for w in (self.icon_entry, self.icon_browse):
            w.state(["disabled"] if portrait else ["!disabled"])
        self._refresh_icon_thumb()

    def _refresh_icon_thumb(self):
        """Small preview of the icon the generator will produce."""
        self._thumb = None
        text = ""
        try:
            from PIL import Image, ImageTk
            if self.icon_mode.get() == "portrait":
                src = self.load_fg_path.get().strip()
                if src and os.path.isfile(src):
                    icon = make_circle_icon(fitted_portrait(src),
                                            self.icon_crop,
                                            self.icon_border_color,
                                            self.icon_border_width, size=64)
                else:
                    text = "(pick a loading portrait - until then the " \
                           "{} icon is used)".format(
                               "original leader's" if self._orig()
                               else "default")
                    icon = None
            else:
                src = self.icon_path.get().strip()
                icon = None
                if src and os.path.isfile(src):
                    icon = Image.open(src).convert("RGBA")
                    icon.thumbnail((64, 64), Image.LANCZOS)
            if icon is not None:
                self._thumb = ImageTk.PhotoImage(icon)
        except ImportError:
            text = "(install Pillow for a preview)"
        except Exception as exc:        # unreadable image
            text = "(cannot preview: {})".format(exc)
        self.icon_thumb.configure(image=self._thumb or "", text=text,
                                  wraplength=150)

    def choose_icon_area(self):
        src = self.load_fg_path.get().strip()
        if not src or not os.path.isfile(src):
            messagebox.showinfo("No loading portrait",
                                "Pick the loading portrait (foreground) "
                                "image first.", parent=self)
            return
        try:
            dialog = IconCropDialog(self, src, self.icon_crop,
                                    self.icon_border_color,
                                    self.icon_border_width)
        except ImportError:
            messagebox.showwarning("Pillow needed", "Cutting the icon out of "
                                   "the portrait needs Pillow "
                                   "(pip install Pillow).", parent=self)
            return
        except Exception as exc:
            messagebox.showwarning("Cannot open image", str(exc), parent=self)
            return
        self.wait_window(dialog)
        self.grab_set()                 # the dialog took the grab
        if dialog.result:
            (self.icon_crop, self.icon_border_color,
             self.icon_border_width) = dialog.result
            self._refresh_icon_thumb()

    def pick_color(self, which):
        initial = getattr(self, which)
        rgb, _ = colorchooser.askcolor(
            parent=self, initialcolor="#%02x%02x%02x" % tuple(initial))
        if rgb:
            setattr(self, which, tuple(int(c) for c in rgb))
            self._refresh_swatches()

    def _refresh_swatches(self):
        for attr, label in ((self.primary, self.primary_lbl),
                            (self.secondary, self.secondary_lbl)):
            r, g, b = attr
            # dark text on light colors, light text on dark ones
            light = 0.299 * r + 0.587 * g + 0.114 * b > 140
            label.config(
                text="({},{},{})".format(r, g, b),
                background="#%02x%02x%02x" % (r, g, b),
                foreground="black" if light else "white")

    def browse_image(self, var, title):
        path = filedialog.askopenfilename(
            parent=self, title="Choose " + title.lower(),
            filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.tga *.dds"),
                       ("All files", "*.*")])
        if path:
            var.set(path)

    # -- result -------------------------------------------------------------

    def on_ok(self):
        texts = self.current_texts()
        spec = {
            "name": self.name_var.get().strip(),
            "sex": self.sex_var.get(),
            "civ": self.civ_var.get().strip(),
            "orig": self._orig(),
            "bio": self.bio.get("1.0", "end").strip(),
            "quote": self.quote_var.get().strip(),
            "texts": texts,
            "primary": tuple(self.primary),
            "secondary": tuple(self.secondary),
            "icon_path": self.icon_path.get().strip(),
            "icon_mode": self.icon_mode.get(),
            "icon_crop": tuple(self.icon_crop) if self.icon_crop else None,
            "icon_border_color": tuple(self.icon_border_color),
            "icon_border_width": int(self.icon_border_width),
            "mood_images": {key: var.get().strip()
                            for key, var in self.mood_vars.items()
                            if var.get().strip()},
            "moment_illustrations": self.moments_frame.entries()
            if self.moments_frame else [],
            "agenda": self._agenda_type(),
            "agenda_name": self.agenda_name_var.get().strip(),
            "agenda_desc": self.agenda_desc.get("1.0", "end").strip(),
            "own_agenda": None,
            "uniques": self.unique_frame.uniques(),
            "abilities": self.abilities(),
            "city_names": self.city_names(),
            "new_ability": self.new_ability(),
            "ai_traits": self.ai_traits(),
            "scene_leader": self._scene_leader(),
            "load_fg_path": self.load_fg_path.get().strip(),
            "load_bg_path": self.load_bg_path.get().strip(),
            "load_bg_default": bool(self.load_bg_default.get()),
            "load_bg_hue": self._load_bg_hue(),
            "diplo_bg_path": self.diplo_bg_path.get().strip(),
            "diplo_bg_mask": bool(self.diplo_bg_mask.get()),
        }
        if self._own_agenda():
            # (its name and description are the agenda's own)
            spec["own_agenda"] = {"name": spec.pop("agenda_name"),
                                  "desc": spec.pop("agenda_desc"),
                                  "reactions": self.reactions.reactions()}
            spec.update(agenda_name="", agenda_desc="")
        if not spec["name"]:
            messagebox.showwarning("Missing name",
                                   "Please enter the leader's name.",
                                   parent=self)
            return
        self.result = spec
        self.destroy()
