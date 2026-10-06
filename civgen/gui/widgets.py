"""Reusable dialogs and widgets."""

import os
import re
import threading
import time

import tkinter as tk
from tkinter import ttk, colorchooser, filedialog

from ..art import default_image_crop, fitted_portrait, make_circle_icon


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
        self.elapsed_label = ttk.Label(body, text="", foreground="gray35")
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
                 background="#ffffe0", foreground="black", relief="solid",
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
    """A vertically scrollable frame; put widgets into .inner."""

    def __init__(self, parent, height=560):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, height=height, highlightthickness=0,
                                borderwidth=0)
        bar = ttk.Scrollbar(self, orient="vertical",
                            command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas, padding=(10, 6))
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all"),
            width=self.inner.winfo_reqwidth()))
        self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        # scroll with the mouse wheel while the pointer is over the frame
        self.bind("<Enter>", lambda e: self.bind_all(
            "<MouseWheel>", self._on_wheel))
        self.bind("<Leave>", lambda e: self.unbind_all("<MouseWheel>"))

    def _on_wheel(self, event):
        self.canvas.yview_scroll(int(-event.delta / 120), "units")


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
