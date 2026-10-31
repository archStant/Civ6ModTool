"""The app's settings (remembered in the user's settings.json, see theme)."""

import tkinter as tk
from tkinter import ttk

from . import theme
from .widgets import add_tooltip, fit_to_screen


def _label(percent):
    return "{}%".format(percent)


class SettingsDialog(tk.Toplevel):
    """Change and remember the app's settings; OK and Apply apply them
    at once."""

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Settings")
        self.transient(parent)
        self.resizable(False, False)

        body = ttk.Frame(self, padding=(12, 10, 12, 6))
        body.pack(side="top", fill="both", expand=True)
        label = ttk.Label(body, text="UI scale (?)")
        label.grid(row=0, column=0, sticky="w", padx=(0, 8), pady=3)
        add_tooltip(label, "The size of text and controls, on top of "
                    "Windows' own display scaling. Raise it if the app "
                    "looks small on a large or high resolution screen.")
        self.scale = ttk.Combobox(body, width=8, state="readonly",
                                  values=[_label(p) for p in
                                          theme.UI_SCALES])
        self.scale.set(_label(theme.ui_scale()))
        self.scale.grid(row=0, column=1, sticky="w", pady=3)
        ttk.Label(body, foreground=theme.hint(), text=(
            "Spacing and images keep their size; restart the app if some "
            "text does not fit.")).grid(row=1, column=0, columnspan=2,
                                        sticky="w", pady=(4, 0))

        btns = ttk.Frame(self, padding=(12, 0, 12, 10))
        btns.pack(side="bottom", fill="x")
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(
            side="right", padx=4)
        ttk.Button(btns, text="Apply", command=self.on_apply).pack(
            side="right", padx=4)
        ttk.Button(btns, text="OK", command=self.on_ok).pack(side="right",
                                                             padx=4)
        fit_to_screen(self)
        self.grab_set()
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self.on_ok())

    def on_apply(self):
        percent = int(self.scale.get().rstrip("%"))
        if percent != theme.ui_scale():
            theme.apply_ui_scale(percent)
            theme.save_setting("ui_scale", percent)
            fit_to_screen(self)

    def on_ok(self):
        self.on_apply()
        self.destroy()
