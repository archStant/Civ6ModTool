"""Light and dark mode.

ttk widgets follow the ttk theme: light mode is the platform's own theme
(e.g. "vista"), dark mode is "clam" with a dark palette (the Windows
themes cannot recolor fields and buttons). Classic Tk widgets (Text,
Listbox, Canvas, the tooltip) get their colors from the option database
when created, and are recolored when the mode changes - only colors that
are still the theme's, so color swatches and image previews keep theirs.
Hint text (grey) uses hint(), which follows the mode.

The choice is remembered in the user's settings (settings.json in the
app's folder under %APPDATA%); without one, the Windows app theme decides.

The UI scale (a percentage, also in the settings) multiplies the screen's
own scaling: fonts and the sizes Tk measures in points grow with it.
"""

import json
import os
import sys

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

# role -> color; LIGHT is filled in from the platform's defaults (init)
DARK = {
    "bg": "#202124", "fg": "#e8eaed", "field": "#2b2c30",
    "field_fg": "#e8eaed", "select": "#3a5f99", "select_fg": "#ffffff",
    "border": "#4a4c52", "button": "#34363b", "button_active": "#43464c",
    "disabled": "#80868b", "hint": "#a8adb3", "heading": "#2b2c30",
    "tooltip": "#3c4043", "tooltip_fg": "#e8eaed", "accent": "#8ab4f8",
}
LIGHT = {"hint": "gray25", "tooltip": "#ffffe0", "tooltip_fg": "black",
         "accent": "#1a73e8"}

_state = {"dark": False, "light_theme": None, "root": None,
          "on_change": [], "base_scaling": None, "font_sizes": {},
          "ui_scale": 100}
# the UI scale's choices, in percent
UI_SCALES = (75, 90, 100, 110, 125, 150, 175, 200, 250, 300)
# classic widget option -> palette role, per widget class
CLASSIC = {
    "Text": {"background": "field", "foreground": "field_fg",
             "insertbackground": "field_fg", "selectbackground": "select",
             "selectforeground": "select_fg",
             "highlightbackground": "border", "highlightcolor": "select"},
    "Listbox": {"background": "field", "foreground": "field_fg",
                "selectbackground": "select", "selectforeground":
                "select_fg", "highlightbackground": "border",
                "highlightcolor": "select"},
    "Canvas": {"background": "bg", "highlightbackground": "bg"},
    "Toplevel": {"background": "bg"},
    "Tk": {"background": "bg"},
    "Frame": {"background": "bg"},
    "Label": {"background": "bg", "foreground": "fg"},
}


def palette():
    return DARK if _state["dark"] else LIGHT


def is_dark():
    return _state["dark"]


def hint():
    """The color of hint text (grey on light, light grey on dark)."""
    return palette()["hint"]


def color(role):
    return palette()[role]


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def settings_path():
    base = os.environ.get("APPDATA") or os.path.join(
        os.path.expanduser("~"), ".config")
    return os.path.join(base, "CivModTool", "settings.json")


def load_settings():
    try:
        with open(settings_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_setting(key, value):
    data = load_settings()
    data[key] = value
    try:
        os.makedirs(os.path.dirname(settings_path()), exist_ok=True)
        with open(settings_path(), "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
    except OSError:
        pass                            # not remembered; still applied


def system_prefers_dark():
    """Whether Windows is set to dark mode for apps (False elsewhere)."""
    if sys.platform != "win32":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion"
                            r"\Themes\Personalize") as key:
            return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
    except OSError:
        return False


def preferred_dark():
    """The remembered choice, else the system's."""
    value = load_settings().get("dark_mode")
    return system_prefers_dark() if value is None else bool(value)


def preferred_ui_scale():
    """The remembered UI scale in percent (100 without one)."""
    try:
        value = int(load_settings().get("ui_scale", 100))
    except (TypeError, ValueError):
        return 100
    return min(max(value, UI_SCALES[0]), UI_SCALES[-1])


def ui_scale():
    """The UI scale in use, in percent."""
    return _state["ui_scale"]


# ---------------------------------------------------------------------------
# UI scale
# ---------------------------------------------------------------------------

def apply_ui_scale(percent):
    """Scale fonts and point sizes to percent of the screen's own scaling
    (call after init; re-applies the styles, so open windows follow)."""
    root = _state["root"]
    _state["ui_scale"] = int(percent)
    factor = percent / 100.0
    root.tk.call("tk", "scaling", _state["base_scaling"] * factor)
    # named fonts in points follow the new scaling once reconfigured;
    # those in pixels (negative sizes) are scaled by hand
    for name in tkfont.names(root):
        named = tkfont.nametofont(name, root=root)
        size = _state["font_sizes"].setdefault(name, int(named.cget("size")))
        named.configure(size=size if size > 0 else
                        min(-1, int(round(size * factor))))
    apply(_state["dark"])


def scaled(size):
    """A size in pixels (or a (width, height) of them) at the UI scale:
    for images and the frames around them, which do not grow by
    themselves."""
    if isinstance(size, (tuple, list)):
        return tuple(scaled(n) for n in size)
    return max(1, int(round(size * _state["ui_scale"] / 100.0)))


def row_height(minimum=0):
    """A Treeview row height that fits a line of the default font."""
    root = _state["root"]
    line = tkfont.nametofont("TkDefaultFont", root=root).metrics("linespace")
    return max(minimum, line + 5)


# ---------------------------------------------------------------------------
# Applying a mode
# ---------------------------------------------------------------------------

def init(root, on_change=None):
    """Remember the platform's light look (call once, before any mode
    change). on_change(): re-applies the app's own style settings, which
    belong to the ttk theme in use."""
    style = ttk.Style(root)
    _state["root"] = root
    _state["light_theme"] = style.theme_use()
    # (the screen's own; Tk shares it between interpreters, so read it once)
    if _state["base_scaling"] is None:
        _state["base_scaling"] = float(root.tk.call("tk", "scaling"))
    if on_change:
        _state["on_change"].append(on_change)
    # the platform's own classic widget colors, read from fresh widgets
    probes = {"Text": tk.Text(root), "Listbox": tk.Listbox(root),
              "Frame": tk.Frame(root)}
    LIGHT.update({
        "bg": probes["Frame"].cget("background"),
        "fg": tk.Label(root).cget("foreground"),
        "field": probes["Text"].cget("background"),
        "field_fg": probes["Text"].cget("foreground"),
        "select": probes["Text"].cget("selectbackground"),
        "select_fg": probes["Text"].cget("selectforeground"),
        "border": probes["Text"].cget("highlightbackground"),
        "disabled": "gray50"})
    for widget in probes.values():
        widget.destroy()
    # dark title bars and recoloring for windows opened later
    root.bind_class("Toplevel", "<Map>", _on_map, add="+")
    root.bind("<Map>", _on_map, add="+")


def apply(dark):
    """Switch every window to dark (True) or light (False) mode."""
    root = _state["root"]
    old = palette()
    _state["dark"] = bool(dark)
    new = palette()
    style = ttk.Style(root)
    if dark:
        style.theme_use("clam")
        _dark_styles(style)
    else:
        style.theme_use(_state["light_theme"])
    # Treeview rows do not grow with the font by themselves
    style.configure("Treeview", rowheight=row_height())
    _option_database(root, new)
    for callback in _state["on_change"]:
        callback()
    _recolor(root, old, new)
    _title_bar(root)


def _dark_styles(style):
    p = DARK
    # clam draws check / radio marks in pixels: grow them with the screen
    # scaling (1.33 pixels per point at 100%)
    try:
        scaling = float(style.tk.call("tk", "scaling"))
    except (tk.TclError, ValueError):
        scaling = 1.33
    indicator = max(10, int(round(11 * scaling / 1.33)))
    style.configure(".", background=p["bg"], foreground=p["fg"],
                    fieldbackground=p["field"], bordercolor=p["border"],
                    darkcolor=p["bg"], lightcolor=p["bg"],
                    troughcolor=p["field"], selectbackground=p["select"],
                    selectforeground=p["select_fg"],
                    insertcolor=p["field_fg"], focuscolor=p["select"])
    style.map(".", foreground=[("disabled", p["disabled"])],
              background=[("disabled", p["bg"])])
    style.configure("TButton", background=p["button"],
                    bordercolor=p["border"], lightcolor=p["button"],
                    darkcolor=p["button"])
    style.map("TButton",
              background=[("disabled", p["bg"]),
                          ("pressed", p["select"]),
                          ("active", p["button_active"])],
              foreground=[("disabled", p["disabled"])])
    style.configure("Toolbutton", background=p["bg"],
                    bordercolor=p["bg"], lightcolor=p["bg"],
                    darkcolor=p["bg"])
    style.map("Toolbutton",
              background=[("disabled", p["bg"]), ("pressed", p["select"]),
                          ("selected", p["select"]),
                          ("active", p["button_active"])],
              foreground=[("disabled", p["disabled"])])
    for name in ("TEntry", "TCombobox", "TSpinbox"):
        style.configure(name, fieldbackground=p["field"],
                        foreground=p["field_fg"], background=p["button"],
                        arrowcolor=p["fg"], bordercolor=p["border"],
                        lightcolor=p["field"], darkcolor=p["field"],
                        insertcolor=p["field_fg"])
        style.map(name,
                  fieldbackground=[("readonly", p["field"]),
                                   ("disabled", p["bg"])],
                  foreground=[("disabled", p["disabled"])],
                  background=[("active", p["button_active"])],
                  selectbackground=[("!focus", p["select"])],
                  selectforeground=[("!focus", p["select_fg"])])
    for name in ("TCheckbutton", "TRadiobutton"):
        style.configure(name, background=p["bg"], foreground=p["fg"],
                        indicatorbackground=p["field"],
                        indicatorforeground=p["fg"],
                        indicatorsize=indicator,
                        indicatordiameter=indicator,
                        indicatormargin=(0, 0, 4, 0))
        style.map(name,
                  background=[("active", p["bg"])],
                  indicatorbackground=[("selected", p["select"]),
                                       ("disabled", p["bg"]),
                                       ("pressed", p["button_active"])],
                  foreground=[("disabled", p["disabled"])])
    style.configure("TNotebook", background=p["bg"],
                    bordercolor=p["border"], tabmargins=(2, 4, 2, 0))
    style.configure("TNotebook.Tab", background=p["button"],
                    foreground=p["fg"], bordercolor=p["border"],
                    lightcolor=p["button"], padding=(10, 3))
    style.map("TNotebook.Tab",
              background=[("selected", p["bg"]),
                          ("active", p["button_active"])],
              lightcolor=[("selected", p["bg"])])
    style.configure("Treeview", background=p["field"],
                    fieldbackground=p["field"], foreground=p["field_fg"],
                    bordercolor=p["border"])
    style.map("Treeview", background=[("selected", p["select"])],
              foreground=[("selected", p["select_fg"])])
    style.configure("Treeview.Heading", background=p["heading"],
                    foreground=p["fg"], bordercolor=p["border"],
                    lightcolor=p["heading"], darkcolor=p["heading"])
    style.map("Treeview.Heading",
              background=[("active", p["button_active"])])
    style.configure("TLabelframe", background=p["bg"],
                    bordercolor=p["border"], lightcolor=p["bg"],
                    darkcolor=p["bg"])
    style.configure("TLabelframe.Label", background=p["bg"],
                    foreground=p["fg"])
    style.configure("TScrollbar", background=p["button"],
                    troughcolor=p["bg"], bordercolor=p["bg"],
                    arrowcolor=p["fg"], lightcolor=p["button"],
                    darkcolor=p["button"])
    style.map("TScrollbar", background=[("active", p["button_active"])])
    style.configure("Horizontal.TScale", background=p["button"],
                    troughcolor=p["field"], bordercolor=p["border"],
                    lightcolor=p["button"], darkcolor=p["button"])
    style.configure("TSeparator", background=p["border"])
    style.configure("TProgressbar", background=p["select"],
                    troughcolor=p["field"], bordercolor=p["border"])


def _option_database(root, p):
    """Colors of classic widgets created from now on."""
    for pattern, role in (
            ("*Text.background", "field"), ("*Text.foreground", "field_fg"),
            ("*Text.insertBackground", "field_fg"),
            ("*Text.selectBackground", "select"),
            ("*Text.selectForeground", "select_fg"),
            ("*Listbox.background", "field"),
            ("*Listbox.foreground", "field_fg"),
            ("*Listbox.selectBackground", "select"),
            ("*Listbox.selectForeground", "select_fg"),
            ("*Canvas.background", "bg"),
            ("*Canvas.highlightBackground", "bg"),
            ("*Toplevel.background", "bg"),
            ("*TCombobox*Listbox.background", "field"),
            ("*TCombobox*Listbox.foreground", "field_fg"),
            ("*TCombobox*Listbox.selectBackground", "select"),
            ("*TCombobox*Listbox.selectForeground", "select_fg")):
        root.option_add(pattern, p[role], "interactive")


def _same(widget, a, b):
    try:
        return widget.winfo_rgb(a) == widget.winfo_rgb(b)
    except tk.TclError:
        return False


def _recolor(widget, old, new):
    """Swap old palette colors for new ones in widget and its children:
    the classic widgets' colors and ttk labels' hint color."""
    cls = widget.winfo_class()
    for option, role in CLASSIC.get(cls, {}).items():
        try:
            current = widget.cget(option)
        except tk.TclError:
            continue
        if current and _same(widget, current, old[role]):
            widget.configure(**{option: new[role]})
    if cls == "TLabel":
        try:
            current = str(widget.cget("foreground"))
            if current and _same(widget, current, old["hint"]):
                widget.configure(foreground=new["hint"])
        except tk.TclError:
            pass
    for child in widget.winfo_children():
        _recolor(child, old, new)


def _on_map(event):
    widget = event.widget
    if isinstance(widget, (tk.Tk, tk.Toplevel)):
        _title_bar(widget)


def _title_bar(window):
    """Windows 10/11: a dark (or light) title bar to match."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        value = ctypes.c_int(1 if _state["dark"] else 0)
        for attribute in (20, 19):      # DWMWA_USE_IMMERSIVE_DARK_MODE
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attribute, ctypes.byref(value),
                    ctypes.sizeof(value)) == 0:
                break
    except Exception:                   # older Windows: keep the default
        pass
