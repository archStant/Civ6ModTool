"""The editor of a new religion."""

import copy
import os

import tkinter as tk
from tkinter import colorchooser, messagebox, ttk

from ..art import (LIST_ICON_SIZE, MOMENT_HALF_OPACITY, MOMENT_MASK,
                   apply_image_mask)
from ..religions import (DEFAULT_GLOW_STRENGTH, DEFAULT_RELIGION_COLOR,
                         FALLBACK_RELIGION_ICON, MAX_OPACITY, MIN_OPACITY,
                         RELIGION_MOMENT_SIZE, glow_strength, glowing_icon,
                         icon_opacity, religion_icon_preview,
                         religion_moment_ink, religion_slug)
from ..util import asset_path
from . import theme
from .widgets import (ImagePreview, TypeCombo, add_tooltip, browse_image,
                      fit_to_screen)

ICON_FILE, ICON_RELIGION = "file", "religion"
# the background of the preview that shows the glow best
DARK_BACKDROP_RGB = (24, 22, 28, 255)
DARK_BACKDROP = "#18161c"
# the historic moment picture: automatic (from the icon) or an own image,
# previewed on the colour of the book's page
MOMENT_AUTO, MOMENT_OWN = "auto", "own"
PARCHMENT_RGB = (226, 204, 156, 255)
PARCHMENT_HEX = "#e2cc9c"


def _hex(rgb):
    return "#{:02x}{:02x}{:02x}".format(*rgb)


class ReligionEditor(tk.Toplevel):
    """Edit a religion spec (see religions.py); .result holds the edited
    spec after OK."""

    def __init__(self, app, spec, title="Religion"):
        super().__init__(app)
        self.app = app
        self.spec = copy.deepcopy(spec)
        self.result = None
        self.title(title)
        self.resizable(False, False)
        self.transient(app)
        try:
            self.color = tuple(int(v) for v in spec.get("color"))[:3]
        except (TypeError, ValueError):
            self.color = ()
        if len(self.color) != 3:
            self.color = DEFAULT_RELIGION_COLOR

        outer = ttk.Frame(self, padding=10)
        outer.pack(fill="both", expand=True)
        # (packed first: the buttons keep their place whatever the body's
        # size - fit_to_screen fixes the window's size when it opens)
        btns = ttk.Frame(outer)
        btns.pack(side="bottom", anchor="e", pady=(10, 0))
        notebook = ttk.Notebook(outer)
        notebook.pack(fill="both", expand=True)
        body = ttk.Frame(notebook, padding=8)
        pedia = ttk.Frame(notebook, padding=8)
        moment = ttk.Frame(notebook, padding=8)
        notebook.add(body, text="General")
        notebook.add(pedia, text="Civilopedia")
        notebook.add(moment, text="Historic moment")
        self.moment_preview = None      # (built after the General tab)
        self._build(body)
        self._build_pedia(pedia)
        self._build_moment(moment)
        ttk.Button(btns, text="OK", command=self.on_ok).pack(side="left",
                                                             padx=4)
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(
            side="left", padx=4)
        fit_to_screen(self)
        self.grab_set()
        self.bind("<Escape>", lambda e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _build(self, body):
        pad = {"padx": 6, "pady": 3}
        spec = self.spec
        ttk.Label(body, wraplength=640, justify="left", text=(
            "A religion players can found: it is offered on the religion "
            "founding screen next to the game's own. How many religions "
            "can be founded in a game depends on the map size, not on how "
            "many there are.")).grid(row=0, column=0, columnspan=3,
                                     sticky="w", pady=(0, 8))
        ttk.Label(body, text="Name").grid(row=1, column=0, sticky="w", **pad)
        self.name_var = tk.StringVar(value=spec.get("name", ""))
        ttk.Entry(body, textvariable=self.name_var, width=30).grid(
            row=1, column=1, sticky="w", **pad)
        self.slug_label = ttk.Label(body)
        self.slug_label.grid(row=1, column=2, sticky="w", **pad)
        self.name_var.trace_add("write", lambda *_: self._refresh())

        ttk.Label(body, text="Color").grid(row=2, column=0, sticky="w", **pad)
        color_row = ttk.Frame(body)
        color_row.grid(row=2, column=1, columnspan=2, sticky="w", **pad)
        self.swatch = tk.Label(color_row, width=4, relief="solid", bd=1,
                               cursor="hand2")
        self.swatch.pack(side="left")
        self.swatch.bind("<Button-1>", lambda e: self.on_pick_color())
        ttk.Button(color_row, text="Pick...",
                   command=self.on_pick_color).pack(side="left", padx=6)
        ttk.Label(color_row, foreground=theme.hint(),
                  text="its color on the map, in the religion lens and "
                       "behind its icon").pack(side="left")

        icon = ttk.LabelFrame(body, text="Icon", padding=(8, 4))
        icon.grid(row=3, column=0, columnspan=3, sticky="we", pady=(10, 3))
        self.icon_mode = tk.StringVar(
            value=ICON_FILE if spec.get("icon_path") else ICON_RELIGION)
        self.icon_path = tk.StringVar(value=spec.get("icon_path", ""))
        ttk.Radiobutton(icon, text="Image file", value=ICON_FILE,
                        variable=self.icon_mode).grid(row=0, column=0,
                                                      sticky="w", **pad)
        file_row = ttk.Frame(icon)
        file_row.grid(row=0, column=1, sticky="w", **pad)
        # the thumbnail's room from the start: picking an image must not
        # grow the (fixed-size) window
        thumb = ttk.Frame(file_row, width=theme.scaled(64) + 8,
                          height=theme.scaled(64) + 8)
        thumb.pack(side="left")
        thumb.pack_propagate(False)
        ImagePreview(thumb, self.icon_path).pack(expand=True)
        ttk.Entry(file_row, textvariable=self.icon_path, width=36).pack(
            side="left", padx=6)
        ttk.Button(file_row, text="Browse...", command=lambda: (
            browse_image(self, self.icon_path, "Religion icon"),
            self.icon_mode.set(ICON_FILE))).pack(side="left")
        ttk.Label(icon, foreground=theme.hint(), wraplength=560,
                  justify="left",
                  text="A white symbol on a transparent background, like the "
                       "game's own (the game draws it on the religion's "
                       "color). Needs the SDK asset cooker.").grid(
            row=1, column=1, sticky="w", padx=6)
        # how the image is drawn: its glow and its opacity (added when the
        # mod is generated; the image file is not changed)
        style = ttk.Frame(icon)
        style.grid(row=2, column=1, sticky="w", **pad)
        self.glow_var = tk.BooleanVar(value=bool(spec.get("glow")))
        self.glow_check = ttk.Checkbutton(style, text="Soft glow",
                                          variable=self.glow_var)
        self.glow_check.grid(row=0, column=0, sticky="w")
        add_tooltip(self.glow_check, (
            "A faint glow around the symbol's lines, like the game's own "
            "religion icons have. Added to the image when the mod is "
            "generated (your image file is not changed)."))
        ttk.Label(style, text="Strength").grid(row=0, column=1, sticky="w",
                                               padx=(14, 4))
        self.glow_strength, self.glow_scale, self.glow_label = \
            self._slider(style, 0, spec.get("glow_strength",
                                            DEFAULT_GLOW_STRENGTH), 1, 100)
        opacity = ttk.Label(style, text="Opacity")
        opacity.grid(row=1, column=0, sticky="w", pady=(4, 0))
        add_tooltip(opacity, (
            "How see-through the icon is (its glow too): 100% is solid. "
            "Applied when the mod is generated (your image file is not "
            "changed)."))
        self.opacity, self.opacity_scale, self.opacity_label = \
            self._slider(style, 1, spec.get("opacity", MAX_OPACITY),
                         MIN_OPACITY, MAX_OPACITY)
        ttk.Radiobutton(icon, text="Icon of", value=ICON_RELIGION,
                        variable=self.icon_mode).grid(row=3, column=0,
                                                      sticky="w", **pad)
        self.icon_from = TypeCombo(icon, self.app.data.religion_choices(),
                                   spec.get("icon_from", ""), width=30)
        self.icon_from.grid(row=3, column=1, sticky="w", **pad)
        self.icon_from.var.trace_add("write",
                                     lambda *_: self._refresh_moment())
        add_tooltip(self.icon_from, "Use the icon of one of the game's "
                    "religions (empty: a spare icon of the game's)")

        preview = ttk.Frame(body)
        preview.grid(row=4, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Label(preview, text="Preview").pack(side="left", padx=6)
        self.preview = ttk.Label(preview)
        self.preview.pack(side="left", padx=6)
        # (the glow shows best on a dark background, as on the founding
        # screen)
        self.dark_preview = tk.Label(preview, background=DARK_BACKDROP,
                                     bd=0)
        self.dark_preview.pack(side="left", padx=6)
        for var in (self.icon_path, self.icon_mode, self.glow_var,
                    self.glow_strength, self.opacity):
            var.trace_add("write", lambda *_: self._refresh())
        self._refresh()

    def _build_pedia(self, body):
        pedia = self.spec.get("pedia") or {}
        ttk.Label(body, wraplength=640, justify="left", text=(
            "The religion's page in the Civilopedia (Religions section): "
            "its History chapter. The page also shows the religion's icon "
            "and the leaders who favor it.")).pack(anchor="w", pady=(0, 8))
        ttk.Label(body, text="History (separate paragraphs with a blank "
                             "line)").pack(anchor="w", pady=(0, 2))
        box = ttk.Frame(body)
        box.pack(fill="both", expand=True)
        self.history = tk.Text(box, height=14, width=80, wrap="word",
                               undo=True)
        scroll = ttk.Scrollbar(box, orient="vertical",
                               command=self.history.yview)
        self.history.configure(yscrollcommand=scroll.set)
        self.history.pack(side="left", fill="both", expand=True)
        scroll.pack(side="left", fill="y")
        self.history.insert("1.0", pedia.get("history", ""))

    def _build_moment(self, body):
        moment = self.spec.get("moment") or {}
        ttk.Label(body, wraplength=640, justify="left", text=(
            "The picture of the historic moment shown when the religion is "
            "founded (Rise and Fall / Gathering Storm). The game draws it "
            "on the left page of an open book, at 166 x 122.")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        self.moment_mode = tk.StringVar(
            value=MOMENT_OWN if moment.get("path") else MOMENT_AUTO)
        ttk.Radiobutton(body, text="Automatic", value=MOMENT_AUTO,
                        variable=self.moment_mode).grid(
            row=1, column=0, sticky="nw", padx=6, pady=3)
        ttk.Label(body, foreground=theme.hint(), wraplength=520,
                  justify="left", text=(
                      "The icon image in brown ink, like the game's own "
                      "religions (best with a symbol rather than a "
                      "picture). With the icon of one of the game's "
                      "religions: that religion's picture.")).grid(
            row=1, column=1, sticky="w", padx=6, pady=3)
        ttk.Radiobutton(body, text="Own image", value=MOMENT_OWN,
                        variable=self.moment_mode).grid(
            row=2, column=0, sticky="w", padx=6, pady=3)
        own = ttk.Frame(body)
        own.grid(row=2, column=1, sticky="w", padx=6, pady=3)
        self.moment_path = tk.StringVar(value=moment.get("path", ""))
        ttk.Entry(own, textvariable=self.moment_path, width=40).pack(
            side="left")
        ttk.Button(own, text="Browse...", command=lambda: (
            browse_image(self, self.moment_path, "Historic moment image"),
            self.moment_mode.set(MOMENT_OWN))).pack(side="left", padx=6)
        checks = ttk.Frame(body)
        checks.grid(row=3, column=1, sticky="w", padx=6)
        self.moment_flags = {}
        for key, text in (("mask", "Fade mask"), ("half", "75% transparent"),
                          ("sepia", "Sepia")):
            var = tk.BooleanVar(value=bool(moment.get(key)))
            check = ttk.Checkbutton(checks, text=text, variable=var)
            check.pack(side="left", padx=(0, 10))
            self.moment_flags[key] = (var, check)
        if not asset_path(MOMENT_MASK):
            self.moment_flags["mask"][1].configure(
                text="Fade mask (assets/{} not found)".format(MOMENT_MASK))
        preview = ttk.Frame(body)
        preview.grid(row=4, column=0, columnspan=2, sticky="w", pady=(12, 0))
        ttk.Label(preview, text="Preview").pack(side="left", padx=6,
                                                anchor="n")
        self.moment_preview = tk.Label(preview, bd=0,
                                       background=PARCHMENT_HEX)
        self.moment_preview.pack(side="left", padx=6)
        self.moment_note = ttk.Label(preview, foreground=theme.hint(),
                                     wraplength=260, justify="left")
        self.moment_note.pack(side="left", padx=6, anchor="n")
        for var in [self.moment_mode, self.moment_path] + [
                v for v, _ in self.moment_flags.values()]:
            var.trace_add("write", lambda *_: self._refresh_moment())
        self._refresh_moment()

    def _refresh_moment(self):
        """The moment picture as it will be made, on a page-coloured
        backdrop, twice the size."""
        if self.moment_preview is None:
            return
        own = self.moment_mode.get() == MOMENT_OWN
        for key, (_, check) in self.moment_flags.items():
            usable = own and (key != "mask" or asset_path(MOMENT_MASK))
            check.state(["!disabled"] if usable else ["disabled"])
        icon = self.icon_path.get().strip() \
            if self.icon_mode.get() == ICON_FILE else ""
        note, img = "", None
        self._moment_photo = None
        try:
            from PIL import Image, ImageTk
            if own:
                path = self.moment_path.get().strip()
                if path and os.path.isfile(path):
                    flags = {k: v.get() for k, (v, _) in
                             self.moment_flags.items()}
                    img = apply_image_mask(
                        path, asset_path(MOMENT_MASK) if flags["mask"]
                        else None, size=RELIGION_MOMENT_SIZE,
                        opacity=MOMENT_HALF_OPACITY if flags["half"]
                        else 1.0, sepia=flags["sepia"])
                else:
                    note = "(pick an image)"
            elif icon and os.path.isfile(icon):
                img = religion_moment_ink(icon)
            else:
                source = self.icon_from.get_type() or \
                    FALLBACK_RELIGION_ICON
                note = "Uses the picture of {}.".format(
                    self.app.data.type_name("religion", source))
            if img is not None:
                page = Image.new("RGBA", img.size, PARCHMENT_RGB)
                page.alpha_composite(img)
                self._moment_photo = ImageTk.PhotoImage(page.resize(
                    (img.width * 2, img.height * 2), Image.LANCZOS))
        except ImportError:
            note = "(install Pillow for a preview)"
        except Exception as exc:        # unreadable image
            note = "(cannot preview: {})".format(exc)
        self.moment_preview.configure(image=self._moment_photo or "")
        self.moment_note.configure(text=note)

    def _slider(self, parent, row, value, low, high):
        """A percentage slider in row of parent's grid: (IntVar, scale,
        label showing the value)."""
        try:
            value = int(float(value))
        except (TypeError, ValueError):
            value = high
        var = tk.IntVar(value=max(low, min(high, value)))
        scale = ttk.Scale(parent, from_=low, to=high,
                          length=theme.scaled(160),
                          command=lambda v: var.set(int(float(v))))
        scale.set(var.get())
        scale.grid(row=row, column=2, sticky="w", pady=(4 if row else 0, 0))
        label = ttk.Label(parent, width=5)
        label.grid(row=row, column=3, sticky="w", padx=4,
                   pady=(4 if row else 0, 0))
        return var, scale, label

    def _refresh(self):
        slug = religion_slug({"name": self.name_var.get()},
                             self.app.type_prefix())
        self.slug_label.configure(text="type: " + (slug or "(type a name)"))
        self.swatch.configure(background=_hex(self.color))
        use_file = self.icon_mode.get() == ICON_FILE
        path = self.icon_path.get().strip() if use_file else ""
        glow = self.glow_var.get()
        self.glow_check.state(["!disabled"] if use_file else ["disabled"])
        self.glow_scale.state(["!disabled"] if use_file and glow
                              else ["disabled"])
        self.opacity_scale.state(["!disabled"] if use_file
                                 else ["disabled"])
        self.glow_label.configure(text="{}%".format(self.glow_strength.get()))
        self.opacity_label.configure(text="{}%".format(self.opacity.get()))
        spec = {"name": self.name_var.get(), "icon_path": path,
                "color": self.color, "glow": glow,
                "glow_strength": self.glow_strength.get(),
                "opacity": self.opacity.get()}
        size = theme.scaled(LIST_ICON_SIZE * 2)
        try:
            from PIL import Image, ImageTk
            self._photo = ImageTk.PhotoImage(religion_icon_preview(spec,
                                                                   size))
            self.preview.configure(image=self._photo)
            self._dark_photo = None
            if path and os.path.isfile(path):
                try:
                    icon = glowing_icon(path, size, glow_strength(spec),
                                        icon_opacity(spec))
                    dark = Image.new("RGBA", icon.size, DARK_BACKDROP_RGB)
                    dark.alpha_composite(icon)
                    self._dark_photo = ImageTk.PhotoImage(dark)
                except Exception:       # unreadable image
                    pass
            self.dark_preview.configure(image=self._dark_photo or "")
            if self._dark_photo:
                self.dark_preview.pack(side="left", padx=6)
            else:
                self.dark_preview.pack_forget()
        except ImportError:             # no Pillow: no preview
            pass
        self._refresh_moment()          # (automatic: drawn from the icon)

    def on_pick_color(self):
        rgb, _ = colorchooser.askcolor(color=_hex(self.color),
                                       title="Religion color", parent=self)
        if rgb:
            self.color = tuple(int(round(v)) for v in rgb)
            self._refresh()

    def on_ok(self):
        spec = dict(self.spec)
        use_file = self.icon_mode.get() == ICON_FILE
        spec.update({
            "name": self.name_var.get().strip(),
            "icon_path": self.icon_path.get().strip() if use_file else "",
            "icon_from": "" if use_file else self.icon_from.get_type(),
            "color": tuple(self.color),
            "glow": bool(self.glow_var.get()),
            "glow_strength": int(self.glow_strength.get()),
            "opacity": int(self.opacity.get()),
            "pedia": dict(spec.get("pedia") or {},
                          history=self.history.get("1.0", "end").strip()),
            "moment": dict(
                {key: bool(var.get()) for key, (var, _) in
                 self.moment_flags.items()},
                path=self.moment_path.get().strip()
                if self.moment_mode.get() == MOMENT_OWN else ""),
        })
        if self.moment_mode.get() == MOMENT_OWN and \
                not spec["moment"]["path"]:
            messagebox.showwarning("Missing image",
                                   "Pick the historic moment's image (or "
                                   "make it automatic).", parent=self)
            return
        if not spec["name"]:
            messagebox.showwarning("Missing name",
                                   "Please enter the religion's name.",
                                   parent=self)
            return
        if use_file and not spec["icon_path"]:
            messagebox.showwarning("Missing icon",
                                   "Pick the icon's image file (or use the "
                                   "icon of one of the game's religions).",
                                   parent=self)
            return
        self.result = spec
        self.destroy()
