"""The editor of a new religion."""

import copy
import os

import tkinter as tk
from tkinter import colorchooser, messagebox, ttk

from ..art import (LIST_ICON_SIZE, MOMENT_HALF_OPACITY, MOMENT_MASK,
                   apply_image_mask)
from ..religions import (DEFAULT_GLOW_STRENGTH, DEFAULT_INK_SLANT,
                         DEFAULT_RELIGION_COLOR, FALLBACK_RELIGION_ICON,
                         INK_SETTINGS, MAX_INK_ROTATION, MAX_INK_SLANT,
                         MAX_OPACITY,
                         MIN_OPACITY,
                         RELIGION_MOMENT_SIZE, glow_strength, glowing_icon,
                         game_moment_picture, icon_opacity, moment_book,
                         on_book, religion_icon_preview,
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
        # renameable, like the game's spare "Custom Religion"s
        self.renameable_var = tk.BooleanVar(
            value=bool(spec.get("renameable")))
        renameable = ttk.Checkbutton(
            body, text="Player names it when founding it",
            variable=self.renameable_var)
        renameable.grid(row=2, column=1, columnspan=2, sticky="w", **pad)
        add_tooltip(renameable, (
            "Like the game's own spare religions: the founding screen "
            "asks the player for the religion's name. The name above is "
            "then only its label in the founding screen's list.\n\nThe "
            "game makes no Civilopedia page for such a religion."))
        self.renameable_var.trace_add(
            "write", lambda *_: self._refresh_pedia())

        ttk.Label(body, text="Color").grid(row=3, column=0, sticky="w", **pad)
        color_row = ttk.Frame(body)
        color_row.grid(row=3, column=1, columnspan=2, sticky="w", **pad)
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
        icon.grid(row=4, column=0, columnspan=3, sticky="we", pady=(10, 3))
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
        preview.grid(row=5, column=0, columnspan=3, sticky="w", pady=(8, 0))
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
        # (shown for a renameable religion, which has no page)
        self.pedia_note = ttk.Label(body, foreground=theme.hint(),
                                    wraplength=640, justify="left")
        self.pedia_note.pack(anchor="w", pady=(0, 8))
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
        self._history_fg = self.history.cget("foreground")
        self._refresh_pedia()

    def _refresh_pedia(self):
        """A renameable religion has no Civilopedia page: its history is
        kept (for if it is made a named one again) but greyed out."""
        if not hasattr(self, "history"):
            return                      # (still building the tabs)
        renameable = self.renameable_var.get()
        self.history.configure(
            state="disabled" if renameable else "normal",
            foreground=theme.hint() if renameable else self._history_fg)
        self.pedia_note.configure(text=(
            "This religion is named by the player when founding it, and "
            "the game makes no Civilopedia page for such religions (as for "
            "its own \"Custom Religion\"s) - the history below is not "
            "used.") if renameable else "")

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
        # the ink symbol's angle (automatic, from the icon image)
        angle = ttk.Frame(body)
        angle.grid(row=2, column=1, sticky="w", padx=6, pady=(0, 6))
        slant = ttk.Label(angle, text="Slant")
        slant.grid(row=0, column=0, sticky="w")
        add_tooltip(slant, (
            "How the symbol leans, like the book's page: negative leans "
            "its bottom to the right, as the game's own symbols do "
            "({}° by default).".format(DEFAULT_INK_SLANT)))
        self.ink_slant, self.slant_scale, self.slant_label = self._slider(
            angle, 0, moment.get("ink_slant", DEFAULT_INK_SLANT),
            -MAX_INK_SLANT, MAX_INK_SLANT, DEFAULT_INK_SLANT)
        self.slant_reset = ttk.Button(
            angle, text="Game default", command=lambda: (
                self.slant_scale.set(DEFAULT_INK_SLANT),
                self.ink_slant.set(DEFAULT_INK_SLANT)))
        self.slant_reset.grid(row=0, column=4, sticky="w", padx=(6, 0))
        rotation = ttk.Label(angle, text="Rotation")
        rotation.grid(row=1, column=0, sticky="w", pady=(4, 0),
                      padx=(0, 14))
        add_tooltip(rotation, "Turns the symbol: positive turns it "
                    "anticlockwise, negative clockwise.")
        self.ink_rotation, self.rotation_scale, self.rotation_label = \
            self._slider(angle, 1, moment.get("ink_rotation", 0),
                         -MAX_INK_ROTATION, MAX_INK_ROTATION, 0)
        # its size and place on the page: {key: (var, scale, label,
        # default, unit)}
        self.ink_place = {}
        for row, (key, text, unit, tip) in enumerate((
                ("ink_scale", "Size", "%",
                 "The symbol's size (100%: like the game's own)."),
                ("ink_x", "Left / right", " px",
                 "Moves the symbol right (positive) or left (negative) on "
                 "the page. It always stays inside the picture."),
                ("ink_y", "Up / down", " px",
                 "Moves the symbol down (positive) or up (negative) on the "
                 "page. It always stays inside the picture.")), 2):
            default, low, high = next((d, lo, hi) for k, d, lo, hi in
                                      INK_SETTINGS if k == key)
            label = ttk.Label(angle, text=text)
            label.grid(row=row, column=0, sticky="w", pady=(4, 0))
            add_tooltip(label, tip)
            var, scale, value = self._slider(
                angle, row, moment.get(key, default), low, high, default)
            self.ink_place[key] = (var, scale, value, default, unit)
        self.place_reset = ttk.Button(angle, text="Centre",
                                      command=self._reset_ink_place)
        self.place_reset.grid(row=2, column=4, sticky="w", padx=(6, 0))
        add_tooltip(self.place_reset, "Back to the game's size and place.")
        ttk.Radiobutton(body, text="Own image", value=MOMENT_OWN,
                        variable=self.moment_mode).grid(
            row=3, column=0, sticky="w", padx=6, pady=3)
        own = ttk.Frame(body)
        own.grid(row=3, column=1, sticky="w", padx=6, pady=3)
        self.moment_path = tk.StringVar(value=moment.get("path", ""))
        ttk.Entry(own, textvariable=self.moment_path, width=40).pack(
            side="left")
        ttk.Button(own, text="Browse...", command=lambda: (
            browse_image(self, self.moment_path, "Historic moment image"),
            self.moment_mode.set(MOMENT_OWN))).pack(side="left", padx=6)
        checks = ttk.Frame(body)
        checks.grid(row=4, column=1, sticky="w", padx=6)
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
        preview.grid(row=5, column=0, columnspan=2, sticky="w", pady=(12, 0))
        ttk.Label(preview, text="Preview").pack(side="left", padx=6,
                                                anchor="n")
        # on the game's own book (from the SDK Assets) when installed,
        # else on its page's colour, twice the size; the room is kept
        # from the start, so the (fixed-size) window never grows
        self.moment_book = moment_book()
        width, height = self.moment_book.size if self.moment_book \
            else (RELIGION_MOMENT_SIZE[0] * 2, RELIGION_MOMENT_SIZE[1] * 2)
        room = ttk.Frame(preview, width=width, height=height)
        room.pack(side="left", padx=6)
        room.pack_propagate(False)
        self.moment_preview = tk.Label(room, bd=0)
        self.moment_preview.pack(expand=True)
        # (below the picture: beside it, it would not fit the window)
        self.moment_note = ttk.Label(body, foreground=theme.hint(),
                                     wraplength=width, justify="left")
        self.moment_note.grid(row=6, column=0, columnspan=2, sticky="w",
                              padx=(70, 6), pady=(4, 0))
        for var in [self.moment_mode, self.moment_path, self.ink_slant,
                    self.ink_rotation] + [
                v for v, _ in self.moment_flags.values()] + [
                place[0] for place in self.ink_place.values()]:
            var.trace_add("write", lambda *_: self._refresh_moment())
        self._refresh_moment()

    def _reset_ink_place(self):
        """The ink symbol's size and place back to the game's."""
        for var, scale, _, default, _ in self.ink_place.values():
            scale.set(default)
            var.set(default)

    def _ink_args(self):
        """religion_moment_ink's angle, size and place arguments."""
        return [self.ink_slant.get(), self.ink_rotation.get()] + [
            self.ink_place[key][0].get()
            for key in ("ink_scale", "ink_x", "ink_y")]

    def _refresh_moment(self):
        """The moment picture as it will be made, on the game's book as
        the moment shows it (or on a page-coloured backdrop, twice the
        size, without the SDK Assets)."""
        if self.moment_preview is None:
            return
        own = self.moment_mode.get() == MOMENT_OWN
        for key, (_, check) in self.moment_flags.items():
            usable = own and (key != "mask" or asset_path(MOMENT_MASK))
            check.state(["!disabled"] if usable else ["disabled"])
        icon = self.icon_path.get().strip() \
            if self.icon_mode.get() == ICON_FILE else ""
        # the angle only matters for the ink drawn from the icon image
        inked = not own and bool(icon)
        for widget in [self.slant_scale, self.rotation_scale,
                       self.slant_reset, self.place_reset] + [
                place[1] for place in self.ink_place.values()]:
            widget.state(["!disabled"] if inked else ["disabled"])
        self.slant_label.configure(text="{}°".format(self.ink_slant.get()))
        self.rotation_label.configure(
            text="{}°".format(self.ink_rotation.get()))
        for var, _, label, _, unit in self.ink_place.values():
            label.configure(text="{}{}".format(var.get(), unit))
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
                img = religion_moment_ink(icon, *self._ink_args())
            else:
                source = self.icon_from.get_type() or \
                    FALLBACK_RELIGION_ICON
                note = "Uses the picture of {}.".format(
                    self.app.data.type_name("religion", source))
                img = game_moment_picture(source)
            if img is not None and self.moment_book is not None:
                self._moment_photo = ImageTk.PhotoImage(
                    on_book(img, self.moment_book))
            elif img is not None:
                page = Image.new("RGBA", img.size, PARCHMENT_RGB)
                page.alpha_composite(img)
                self._moment_photo = ImageTk.PhotoImage(page.resize(
                    (img.width * 2, img.height * 2), Image.LANCZOS))
            if self.moment_book is None and not note:
                note = ("(The game's book picture shows here when the "
                        "Civ VI SDK Assets are installed.)")
        except ImportError:
            note = "(install Pillow for a preview)"
        except Exception as exc:        # unreadable image
            note = "(cannot preview: {})".format(exc)
        self.moment_preview.configure(image=self._moment_photo or "")
        self.moment_note.configure(text=note)

    def _slider(self, parent, row, value, low, high, default=None):
        """A slider in row of parent's grid (columns 2-3): (IntVar, scale,
        label for its value). default: for an unreadable value (None:
        high)."""
        try:
            value = int(round(float(value)))
        except (TypeError, ValueError):
            value = high if default is None else default
        var = tk.IntVar(value=max(low, min(high, value)))
        scale = ttk.Scale(parent, from_=low, to=high,
                          length=theme.scaled(160),
                          command=lambda v: var.set(int(float(v))))
        scale.set(var.get())
        scale.grid(row=row, column=2, sticky="w", pady=(4 if row else 0, 0))
        label = ttk.Label(parent, width=7)      # (room for "-40 px")
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
            "renameable": bool(self.renameable_var.get()),
            "pedia": dict(spec.get("pedia") or {},
                          history=self.history.get("1.0", "end").strip()),
            "moment": dict(
                {key: bool(var.get()) for key, (var, _) in
                 self.moment_flags.items()},
                path=self.moment_path.get().strip()
                if self.moment_mode.get() == MOMENT_OWN else "",
                ink_slant=int(self.ink_slant.get()),
                ink_rotation=int(self.ink_rotation.get()),
                **{key: int(place[0].get())
                   for key, place in self.ink_place.items()}),
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
