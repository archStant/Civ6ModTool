"""Reusable dialogs and widgets."""

import os
import sys
import re
import threading
import time

import tkinter as tk
from tkinter import ttk, colorchooser, filedialog, messagebox

from ..art import default_image_crop, fitted_portrait, make_circle_icon
from . import theme


class IconCropDialog(tk.Toplevel):
    """Pick the icon's circle on the loading portrait: drag inside the
    circle to move it, drag its edge (or use the mouse wheel) to resize."""

    MAX_W, MAX_H = 760, 600
    EDGE = 9          # pixels around the circle's edge that start a resize

    def __init__(self, parent, src, crop, border_color, border_width):
        from PIL import Image, ImageEnhance
        super().__init__(parent)
        self.title("Choose icon area")
        self.resizable(False, False)
        self.transient(parent)
        self.result = None

        self.src = fitted_portrait(src)
        w, h = self.src.size
        self.scale = min(1.0, self.MAX_W / float(w), self.MAX_H / float(h))
        dw, dh = max(1, int(w * self.scale)), max(1, int(h * self.scale))
        # show transparent portraits on a checker-free dark background
        backdrop = Image.new("RGBA", (dw, dh), (40, 40, 40, 255))
        self.disp = Image.alpha_composite(
            backdrop, self.src.resize((dw, dh), Image.LANCZOS))
        self.dark = ImageEnhance.Brightness(self.disp).enhance(0.35)
        self.crop = list(crop or default_image_crop(self.src))
        self.border_color = tuple(border_color)
        self.drag = None
        self._pending = False

        body = ttk.Frame(self, padding=10)
        body.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(body, width=dw, height=dh,
                                highlightthickness=0, background="black")
        self.canvas.grid(row=0, column=0, rowspan=2, sticky="nw")
        self.img_item = self.canvas.create_image(0, 0, anchor="nw")
        self.ring_item = self.canvas.create_oval(0, 0, 1, 1, outline="white",
                                                 width=2, dash=(6, 4))
        self.handle_item = self.canvas.create_rectangle(
            0, 0, 1, 1, outline="black", fill="white")
        for seq, fn in (("<ButtonPress-1>", self.on_press),
                        ("<B1-Motion>", self.on_drag),
                        ("<ButtonRelease-1>", self.on_release),
                        ("<Motion>", self.on_hover),
                        ("<MouseWheel>", self.on_wheel)):
            self.canvas.bind(seq, fn)

        side = ttk.Frame(body, padding=(12, 0, 0, 0))
        side.grid(row=0, column=1, sticky="n")
        ttk.Label(side, text="Preview").pack(anchor="w")
        self.preview = tk.Canvas(side, width=200, height=140,
                                 highlightthickness=0, background="#2b2b2b")
        self.preview.pack(anchor="w", pady=(2, 10))
        self.preview_big = self.preview.create_image(8, 6, anchor="nw")
        self.preview_small = self.preview.create_image(144, 38, anchor="nw")

        ttk.Label(side, text="Border width").pack(anchor="w")
        self.width_var = tk.IntVar(value=int(border_width))
        tk.Scale(side, from_=0, to=40, orient="horizontal", length=200,
                 variable=self.width_var,
                 command=lambda *_: self.schedule()).pack(anchor="w")
        color_row = ttk.Frame(side)
        color_row.pack(anchor="w", pady=(8, 0))
        ttk.Label(color_row, text="Border color").pack(side="left")
        self.swatch = tk.Label(color_row, width=4, relief="sunken")
        self.swatch.pack(side="left", padx=6)
        ttk.Button(color_row, text="Pick...",
                   command=self.pick_color).pack(side="left")
        ttk.Label(side, wraplength=200, justify="left", text=(
            "Drag inside the circle to move it. Drag its edge or the "
            "handle, or use the mouse wheel, to resize.")).pack(
            anchor="w", pady=(14, 0))
        ttk.Button(side, text="Reset circle",
                   command=self.reset).pack(anchor="w", pady=(10, 0))

        btns = ttk.Frame(body)
        btns.grid(row=1, column=1, sticky="se")
        ttk.Button(btns, text="OK", command=self.on_ok).pack(side="left",
                                                             padx=4)
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(
            side="left", padx=4)

        self._refresh_swatch()
        self.redraw()
        self.grab_set()
        self.bind("<Return>", lambda e: self.on_ok())
        self.bind("<Escape>", lambda e: self.destroy())

    # -- geometry helpers ---------------------------------------------------

    def _disp_circle(self):
        cx, cy, r = self.crop
        return cx * self.scale, cy * self.scale, r * self.scale

    def _clamp(self):
        w, h = self.src.size
        cx, cy, r = self.crop
        r = min(max(r, 8.0 / self.scale, 4.0), max(w, h))
        self.crop = [min(max(cx, 0.0), w), min(max(cy, 0.0), h), r]

    # -- drawing ------------------------------------------------------------

    def schedule(self):
        """Coalesce redraws while dragging."""
        if not self._pending:
            self._pending = True
            self.after_idle(self.redraw)

    def redraw(self):
        from PIL import Image, ImageDraw, ImageTk
        self._pending = False
        cx, cy, r = self._disp_circle()
        mask = Image.new("L", self.disp.size, 0)
        ImageDraw.Draw(mask).ellipse((cx - r, cy - r, cx + r, cy + r),
                                     fill=255)
        self._photo = ImageTk.PhotoImage(
            Image.composite(self.disp, self.dark, mask))
        self.canvas.itemconfig(self.img_item, image=self._photo)
        self.canvas.coords(self.ring_item, cx - r, cy - r, cx + r, cy + r)
        self.canvas.coords(self.handle_item, cx + r - 5, cy - 5,
                           cx + r + 5, cy + 5)

        icon = make_circle_icon(self.src, self.crop, self.border_color,
                                self.width_var.get(), size=128)
        self._preview_big = ImageTk.PhotoImage(icon)
        self._preview_small = ImageTk.PhotoImage(
            icon.resize((48, 48), Image.LANCZOS))
        self.preview.itemconfig(self.preview_big, image=self._preview_big)
        self.preview.itemconfig(self.preview_small,
                                image=self._preview_small)

    # -- mouse --------------------------------------------------------------

    def _hit(self, x, y):
        cx, cy, r = self._disp_circle()
        d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
        if abs(d - r) <= self.EDGE:
            return "resize"
        return "move" if d < r else None

    def on_hover(self, event):
        hit = self._hit(event.x, event.y)
        self.canvas.configure(cursor={"resize": "sizing",
                                      "move": "fleur"}.get(hit, ""))

    def on_press(self, event):
        hit = self._hit(event.x, event.y)
        cx, cy, _ = self._disp_circle()
        if hit is None:                 # click outside: jump there
            self.crop[0], self.crop[1] = (event.x / self.scale,
                                          event.y / self.scale)
            hit, cx, cy = "move", event.x, event.y
        self.drag = (hit, event.x - cx, event.y - cy)
        self._clamp()
        self.schedule()

    def on_drag(self, event):
        if not self.drag:
            return
        mode, dx, dy = self.drag
        if mode == "move":
            self.crop[0] = (event.x - dx) / self.scale
            self.crop[1] = (event.y - dy) / self.scale
        else:
            cx, cy, _ = self._disp_circle()
            self.crop[2] = ((event.x - cx) ** 2 +
                            (event.y - cy) ** 2) ** 0.5 / self.scale
        self._clamp()
        self.schedule()

    def on_release(self, _event):
        self.drag = None

    def on_wheel(self, event):
        self.crop[2] *= 1.05 if event.delta > 0 else 1 / 1.05
        self._clamp()
        self.schedule()

    # -- controls -----------------------------------------------------------

    def _refresh_swatch(self):
        self.swatch.configure(background="#%02x%02x%02x" % self.border_color)

    def pick_color(self):
        rgb, _ = colorchooser.askcolor(
            parent=self, initialcolor="#%02x%02x%02x" % self.border_color)
        if rgb:
            self.border_color = tuple(int(c) for c in rgb)
            self._refresh_swatch()
            self.schedule()

    def reset(self):
        self.crop = list(default_image_crop(self.src))
        self.schedule()

    def on_ok(self):
        self.result = (tuple(self.crop), self.border_color,
                       int(self.width_var.get()))
        self.destroy()


class BusyDialog(tk.Toplevel):
    """Modal 'working...' window with a moving progress bar, a status line
    and the elapsed time, shown while run() does the work in a thread."""

    def __init__(self, parent, title):
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", lambda: None)   # cannot be closed
        self._status = "Starting..."
        self._start = time.monotonic()

        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)
        self.status_label = ttk.Label(body, text=self._status, width=60)
        self.status_label.pack(anchor="w")
        self.bar = ttk.Progressbar(body, mode="indeterminate", length=380)
        self.bar.pack(fill="x", pady=(10, 4))
        self.bar.start(12)
        self.elapsed_label = ttk.Label(body, text="", foreground=theme.hint())
        self.elapsed_label.pack(anchor="e")

        self.update_idletasks()         # center over the parent
        x = parent.winfo_rootx() + (parent.winfo_width() -
                                    self.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() -
                                    self.winfo_height()) // 3
        self.geometry("+{}+{}".format(max(x, 0), max(y, 0)))
        self.grab_set()

    def set_status(self, text):
        """Safe to call from the worker thread (only stores the text)."""
        self._status = text

    def run(self, work):
        """Run work() in a thread while the window stays responsive, then
        close. Returns work()'s result or re-raises its exception here.
        work() must not touch Tk."""
        result = {}

        def target():
            try:
                result["value"] = work()
            except BaseException as exc:    # re-raised on the main thread
                result["error"] = exc

        thread = threading.Thread(target=target, daemon=True)
        thread.start()

        def poll():
            if thread.is_alive():
                self.status_label.configure(text=self._status)
                self.elapsed_label.configure(text="{:.0f} s".format(
                    time.monotonic() - self._start))
                self.after(100, poll)
            else:
                self.bar.stop()
                self.grab_release()
                self.destroy()

        poll()
        self.wait_window()
        if "error" in result:
            raise result["error"]
        return result.get("value")


class Tooltip:
    """A small text box shown near the mouse after it rests on a widget.
    The owner calls show(text) on mouse motion ("" hides it) and hide()
    when the mouse leaves."""

    DELAY_MS = 400

    def __init__(self, widget):
        self.widget = widget
        self.text = ""
        self.tip = None
        self.pending = None

    def show(self, text):
        if text == self.text:
            return                      # already shown (or scheduled)
        self.hide()
        self.text = text
        if text:
            self.pending = self.widget.after(self.DELAY_MS, self._open)

    def _open(self):
        self.pending = None
        x, y = self.widget.winfo_pointerxy()
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry("+{}+{}".format(x + 16, y + 16))
        tk.Label(self.tip, text=self.text, justify="left",
                 background=theme.color("tooltip"),
                 foreground=theme.color("tooltip_fg"), relief="solid",
                 borderwidth=1, padx=6, pady=3).pack()

    def hide(self):
        if self.pending:
            self.widget.after_cancel(self.pending)
            self.pending = None
        if self.tip is not None:
            self.tip.destroy()
            self.tip = None
        self.text = ""


class ScrollFrame(ttk.Frame):
    """A vertically scrollable frame; put widgets into .inner. height:
    the visible height, or None: as tall as the content (it only scrolls
    when its window is made smaller, see fit_to_screen)."""

    def __init__(self, parent, height=560):
        super().__init__(parent)
        self.natural = height is None
        self.canvas = tk.Canvas(self, height=height or 1,
                                highlightthickness=0, borderwidth=0)
        # scroll bars, shown only while there is more to see; packed
        # before the canvas, so a small window squeezes the canvas only
        self.vbar = ttk.Scrollbar(self, orient="vertical",
                                  command=self.canvas.yview)
        self.hbar = ttk.Scrollbar(self, orient="horizontal",
                                  command=self.canvas.xview)
        self.inner = ttk.Frame(self.canvas, padding=(10, 6))
        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(
            yscrollcommand=lambda a, b: self._bar(self.vbar, "right", "y",
                                                  a, b),
            xscrollcommand=lambda a, b: self._bar(self.hbar, "bottom", "x",
                                                  a, b))
        self.canvas.pack(side="left", fill="both", expand=True)
        # the mouse wheel scrolls the frame under the pointer
        # (through the main window, which outlives every frame)
        self.bind_all("<MouseWheel>",
                      lambda e, root=self._root(): _wheel_router(e, root))

    def _on_inner_configure(self, _event=None):
        size = {"scrollregion": self.canvas.bbox("all"),
                "width": self.inner.winfo_reqwidth()}
        if self.natural:
            size["height"] = self.inner.winfo_reqheight()
        self.canvas.configure(**size)

    def _bar(self, bar, side, fill, first, last):
        """Show bar only while part of the content is hidden."""
        needed = float(first) > 0 or float(last) < 1
        if needed and not bar.winfo_ismapped():
            bar.pack(side=side, fill=fill, before=self.canvas)
        elif not needed and bar.winfo_ismapped():
            bar.pack_forget()
        bar.set(first, last)

    def can_scroll(self):
        first, last = self.canvas.yview()
        return first > 0 or last < 1


# widgets that scroll by themselves on the mouse wheel
SELF_SCROLLING = ("Text", "Listbox", "Treeview", "TCombobox")


def _wheel_router(event, root):
    """Mouse wheel: scroll the innermost ScrollFrame under the pointer
    that has more to show. root: the main window - event.widget is only
    a name for widgets Tk makes itself (a combobox's drop-down list)."""
    try:
        widget = root.winfo_containing(event.x_root, event.y_root)
    except (KeyError, tk.TclError):     # e.g. over a combobox's popdown
        return
    if widget is None or widget.winfo_class() in SELF_SCROLLING:
        return
    while widget is not None:
        if isinstance(widget, ScrollFrame) and widget.can_scroll():
            widget.canvas.yview_scroll(int(-event.delta / 120), "units")
            return
        widget = widget.master


def work_area(window):
    """(left, top, right, bottom) of the screen minus the taskbar."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            rect = wintypes.RECT()
            if ctypes.windll.user32.SystemParametersInfoW(
                    0x30, 0, ctypes.byref(rect), 0):   # SPI_GETWORKAREA
                return rect.left, rect.top, rect.right, rect.bottom
        except Exception:
            pass
    return 0, 0, window.winfo_screenwidth(), window.winfo_screenheight()


def fit_to_screen(window):
    """Size and place a dialog so it is all on screen: no larger than the
    work area (its scrollable parts shrink and scroll instead), centred
    on it. A dialog that had to shrink can be resized."""
    window.update_idletasks()
    left, top, right, bottom = work_area(window)
    scale = float(window.tk.call("tk", "scaling")) / 1.33
    title_bar = int(36 * scale)         # the frame Windows adds
    avail_w = right - left - int(16 * scale)
    avail_h = bottom - top - title_bar - int(8 * scale)
    width, height = window.winfo_reqwidth(), window.winfo_reqheight()
    if width > avail_w or height > avail_h:
        width, height = min(width, avail_w), min(height, avail_h)
        window.resizable(True, True)
        window.minsize(min(width, int(400 * scale)),
                       min(height, int(300 * scale)))
    x = left + max(0, (right - left - width) // 2)
    y = top + max(0, (bottom - top - title_bar - height) // 2)
    window.geometry("{}x{}+{}+{}".format(width, height, x, y))


def add_tooltip(widget, text):
    """Show text in a tooltip while the mouse rests on widget."""
    tip = Tooltip(widget)
    widget.bind("<Enter>", lambda e: tip.show(text), add="+")
    widget.bind("<Leave>", lambda e: tip.hide(), add="+")
    return tip


class HelpBox(ttk.Frame):
    """A collapsible explanation: a "How this works" toggle and the text
    (paragraphs separated by blank lines; a paragraph starting with "- "
    lines is shown as a list)."""

    def __init__(self, parent, text, title="How this works",
                 wraplength=900, open_=False):
        super().__init__(parent)
        self.title = title
        self.button = ttk.Button(self, command=self.toggle,
                                 style="Toolbutton")
        self.button.pack(anchor="w")
        self.body = ttk.Frame(self, padding=(16, 2, 0, 6))
        for paragraph in text.strip().split("\n\n"):
            ttk.Label(self.body, text=paragraph.strip(), justify="left",
                      wraplength=wraplength).pack(anchor="w", pady=(0, 6))
        self.open = not open_
        self.toggle()

    def toggle(self):
        self.open = not self.open
        self.button.configure(text=("▾ " if self.open else "▸ ") +
                              self.title)
        if self.open:
            self.body.pack(anchor="w", fill="x")
        else:
            self.body.pack_forget()


# ---------------------------------------------------------------------------
# Game type pickers
# ---------------------------------------------------------------------------

TYPE_RE = re.compile(r"\(([A-Z0-9_]+)\)\s*$")


def type_label(type_name, name):
    """Combobox text of a type: 'Campus (DISTRICT_CAMPUS)'."""
    return "{} ({})".format(name, type_name) if name else type_name


def parse_type(text):
    """The type in a combobox text ('Campus (DISTRICT_CAMPUS)' or a typed
    'DISTRICT_CAMPUS'), or ""."""
    text = (text or "").strip()
    m = TYPE_RE.search(text)
    return m.group(1) if m else text.upper()


class TypeCombo(ttk.Combobox):
    """An editable combobox of game types shown as 'Name (TYPE)'; get_type
    returns the type (a typed TYPE works too). choices: [(type, name)]."""

    def __init__(self, parent, choices=(), value="", width=40, **kw):
        self.var = tk.StringVar()
        super().__init__(parent, textvariable=self.var, width=width, **kw)
        self.names = {}
        self.set_choices(choices)
        self.set_type(value)

    def _label(self, type_name, name):
        # special choices (NEW, NONE...: no "_") show just their name
        return name if name and "_" not in type_name else \
            type_label(type_name, name)

    def set_choices(self, choices):
        choices = list(choices)
        self.names = dict(choices)
        self.labels = {self._label(t, n): t for t, n in choices}
        self["values"] = list(self.labels)

    def set_type(self, type_name):
        if type_name and type_name not in self.names and \
                type_name.upper() in self.names:
            type_name = type_name.upper()   # e.g. "none" -> NONE
        self.var.set(self._label(type_name, self.names.get(type_name))
                     if type_name else "")

    def get_type(self):
        text = self.var.get().strip()
        return self.labels.get(text) or parse_type(text)


def names_text(parent, names, height=12, width=30):
    """A text box with one name per line (and a scrollbar); returns
    (frame, tk.Text)."""
    frame = ttk.Frame(parent)
    text = tk.Text(frame, height=height, width=width, wrap="none", undo=True)
    bar = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
    text.configure(yscrollcommand=bar.set)
    text.pack(side="left", fill="both", expand=True)
    bar.pack(side="left", fill="y")
    text.insert("1.0", "\n".join(names or []))
    return frame, text


def text_lines(text):
    """The non-empty, stripped lines of a tk.Text."""
    return [line.strip() for line in text.get("1.0", "end").splitlines()
            if line.strip()]


def browse_image(parent, var, title):
    path = filedialog.askopenfilename(
        parent=parent, title="Choose " + title.lower(),
        filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.tga *.dds"),
                   ("All files", "*.*")])
    if path:
        var.set(path)


class ImagePreview(ttk.Label):
    """A small preview of the image file in a StringVar (updated as it
    changes), on a dark backdrop so transparency shows."""

    def __init__(self, parent, var, size=64):
        super().__init__(parent, width=12)
        self.var, self.size, self._photo = var, size, None
        var.trace_add("write", lambda *_: self.refresh())
        self.refresh()

    def refresh(self):
        self._photo, text = None, ""
        path = self.var.get().strip()
        try:
            from PIL import Image, ImageTk
            if path and os.path.isfile(path):
                img = Image.open(path).convert("RGBA")
                img.thumbnail((self.size, self.size), Image.LANCZOS)
                out = Image.new("RGBA", (self.size, self.size),
                                (43, 43, 43, 255))
                out.alpha_composite(img, ((self.size - img.width) // 2,
                                          (self.size - img.height) // 2))
                self._photo = ImageTk.PhotoImage(out)
            elif path:
                text = "(file not found)"
        except ImportError:
            text = "(install Pillow for a preview)"
        except Exception as exc:        # unreadable image
            text = "(cannot preview: {})".format(exc)
        self.configure(image=self._photo or "", text=text)


# ---------------------------------------------------------------------------
# Icons in text: buttons inserting the game's [ICON_...] tags
# ---------------------------------------------------------------------------

# the yields, shown as colored chips: (tag, label, chip color)
YIELD_CHIPS = [
    ("[ICON_Food]", "Food", "#6aa84f"),
    ("[ICON_Production]", "Production", "#c97a32"),
    ("[ICON_Gold]", "Gold", "#d4a72c"),
    ("[ICON_Science]", "Science", "#4a86c5"),
    ("[ICON_Culture]", "Culture", "#9b5fc0"),
    ("[ICON_Faith]", "Faith", "#8fb3c9"),
]
# the others, in the "More icons" menu: (group, [(tag, label)])
TEXT_ICONS = [
    ("Yields and resources", [
        ("[ICON_Food]", "Food"), ("[ICON_Production]", "Production"),
        ("[ICON_Gold]", "Gold"), ("[ICON_Science]", "Science"),
        ("[ICON_Culture]", "Culture"), ("[ICON_Faith]", "Faith"),
        ("[ICON_Tourism]", "Tourism"),
        ("[ICON_Favor]", "Diplomatic Favor (Gathering Storm)"),
        ("[ICON_Power]", "Power (Gathering Storm)")]),
    ("Cities", [
        ("[ICON_Citizen]", "Citizen"), ("[ICON_Housing]", "Housing"),
        ("[ICON_Amenities]", "Amenities"), ("[ICON_Capital]", "Capital"),
        ("[ICON_TradeRoute]", "Trade route"),
        ("[ICON_TradingPost]", "Trading post"),
        ("[ICON_Envoy]", "Envoy"),
        ("[ICON_Governor]", "Governor (Rise and Fall)"),
        ("[ICON_Religion]", "Religion")]),
    ("Combat", [
        ("[ICON_Strength]", "Combat strength"),
        ("[ICON_Ranged]", "Ranged strength"), ("[ICON_Range]", "Range"),
        ("[ICON_Bombard]", "Bombard strength"),
        ("[ICON_Movement]", "Movement")]),
    ("Great people", [
        ("[ICON_GreatPerson]", "Great person (any)"),
        ("[ICON_GreatGeneral]", "Great General"),
        ("[ICON_GreatAdmiral]", "Great Admiral"),
        ("[ICON_GreatEngineer]", "Great Engineer"),
        ("[ICON_GreatMerchant]", "Great Merchant"),
        ("[ICON_GreatProphet]", "Great Prophet"),
        ("[ICON_GreatScientist]", "Great Scientist"),
        ("[ICON_GreatWriter]", "Great Writer"),
        ("[ICON_GreatArtist]", "Great Artist"),
        ("[ICON_GreatMusician]", "Great Musician")]),
    ("Great works", [
        ("[ICON_GreatWork_Writing]", "Writing"),
        ("[ICON_GreatWork_Landscape]", "Art"),
        ("[ICON_GreatWork_Sculpture]", "Sculpture"),
        ("[ICON_GreatWork_Music]", "Music"),
        ("[ICON_GreatWork_Relic]", "Relic"),
        ("[ICON_GreatWork_Artifact]", "Artifact")]),
    ("Other", [
        ("[ICON_Bullet]", "Bullet (list item)"), ("[ICON_Turn]", "Turns"),
        ("[ICON_TechBoosted]", "Eureka (technology boost)"),
        ("[ICON_CivicBoosted]", "Inspiration (civic boost)")]),
]


def insert_tag(widget, tag):
    """Insert tag at the cursor of a Text or Entry widget (replacing a
    selection) and put the focus back there."""
    try:
        if isinstance(widget, tk.Text):
            if widget.tag_ranges("sel"):
                widget.delete("sel.first", "sel.last")
            widget.insert("insert", tag)
        else:
            if widget.selection_present():
                widget.delete("sel.first", "sel.last")
            widget.insert("insert", tag)
        widget.focus_set()
    except tk.TclError:                 # read-only or gone
        pass


def icon_menu(parent, target):
    """A menu of every TEXT_ICONS tag, by group, inserting into target."""
    menu = tk.Menu(parent, tearoff=False)
    for group, icons in TEXT_ICONS:
        sub = tk.Menu(menu, tearoff=False)
        for tag, label in icons:
            sub.add_command(label="{}   {}".format(label, tag),
                            command=lambda t=tag: insert_tag(target, t))
        menu.add_cascade(label=group, menu=sub)
    return menu


class IconBar(ttk.Frame):
    """Buttons inserting icon tags into a text field: a chip per yield
    and a "More icons" menu. The game shows the tags as its icons."""

    def __init__(self, parent, target):
        super().__init__(parent)
        label = ttk.Label(self, text="Insert icon:",
                          foreground=theme.hint())
        label.pack(side="left", padx=(0, 4))
        add_tooltip(label, "Puts the game's icon tag at the cursor - e.g. "
                    "+2 [ICON_Faith] Faith shows the Faith icon in game.")
        for tag, text, color in YIELD_CHIPS:
            chip = tk.Label(self, text=text, background=color,
                            foreground="black", padx=6, pady=0,
                            cursor="hand2", font=("TkDefaultFont", 8))
            chip.pack(side="left", padx=1)
            chip.bind("<Button-1>", lambda e, t=tag: insert_tag(target, t))
            add_tooltip(chip, tag)
        more = ttk.Menubutton(self, text="More icons ▾", style="Toolbutton")
        more["menu"] = icon_menu(more, target)
        more.pack(side="left", padx=(6, 0))


def icon_text(parent, buttons=(), **options):
    """A Text with an IconBar under it: (frame to place, Text).
    buttons: (text, command, tooltip) of buttons after the icon bar."""
    frame = ttk.Frame(parent)
    text = tk.Text(frame, **options)
    text.pack(side="top", fill="both", expand=True)
    row = ttk.Frame(frame)
    row.pack(side="top", anchor="w", fill="x", pady=(2, 0))
    IconBar(row, text).pack(side="left")
    for label, command, tip in buttons:
        ttk.Separator(row, orient="vertical").pack(side="left", fill="y",
                                                   padx=8, pady=2)
        button = ttk.Button(row, text=label, command=command,
                            style="Toolbutton")
        button.pack(side="left")
        if tip:
            add_tooltip(button, tip)
    return frame, text


WRITE_TIP = ("Writes the description from the effects (and what else "
             "makes it what it is), in the game's style with its icons. "
             "Edit it afterwards as you like.")


def write_description(widget, text, parent):
    """Put text into a description Text, asking before replacing what is
    there."""
    if not text.strip():
        messagebox.showinfo("Nothing to describe", "Add some effects (or "
                            "changes) first.", parent=parent)
        return
    current = widget.get("1.0", "end").strip()
    if current == text.strip():
        return
    if current and not messagebox.askyesno(
            "Replace description", "Replace the description with one "
            "written from the effects?", parent=parent):
        return
    widget.delete("1.0", "end")
    widget.insert("1.0", text)


def install_icon_context_menu(root):
    """Right-click in any text field (Text or ttk Entry): an "Insert
    icon" menu."""
    def popup(event):
        widget = event.widget
        if str(widget.cget("state")) in ("disabled", "readonly"):
            return
        menu = tk.Menu(widget, tearoff=False)
        menu.add_cascade(label="Insert icon", menu=icon_menu(menu, widget))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
    for cls in ("Text", "TEntry"):
        root.bind_class(cls, "<Button-3>", popup, add="+")
