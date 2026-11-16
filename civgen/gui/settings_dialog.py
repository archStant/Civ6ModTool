"""The app's settings (remembered in the user's settings.json, see theme)."""

import tkinter as tk
from tkinter import messagebox, ttk

from ..art import ART_CACHE_MAX_BYTES, art_cache_root, cache_usage, clear_cache
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
            "text does not fit.")).grid(row=1, column=0, columnspan=3,
                                        sticky="w", pady=(4, 0))

        label = ttk.Label(body, text="Art cache limit (GB) (?)")
        label.grid(row=2, column=0, sticky="w", padx=(0, 8), pady=(12, 3))
        add_tooltip(label, "Converted images and cooked art are kept "
                    "between builds, so images that have not changed are "
                    "not made again. The art of the mod being built is "
                    "always kept; above the limit, the art of other "
                    "projects is deleted, the longest unused first. A "
                    "large mod's art can take a few GB.")
        low, high = theme.ART_CACHE_GB_RANGE
        self.cache_gb = tk.StringVar(value=str(
            theme.art_cache_gb() or ART_CACHE_MAX_BYTES // 1024 ** 3))
        ttk.Spinbox(body, from_=low, to=high, width=6,
                    textvariable=self.cache_gb).grid(
            row=2, column=1, sticky="w", pady=(12, 3))
        ttk.Button(body, text="Clear cache", command=self.on_clear_cache
                   ).grid(row=2, column=2, sticky="w", padx=(8, 0),
                          pady=(12, 3))
        self.usage = ttk.Label(body, foreground=theme.hint())
        self.usage.grid(row=3, column=0, columnspan=3, sticky="w",
                        pady=(4, 0))
        self._show_usage()

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

    def _show_usage(self):
        self.usage.configure(text="In use: {:.2f} GB  ({})".format(
            cache_usage() / 1024.0 ** 3, art_cache_root()))

    def on_clear_cache(self):
        if messagebox.askyesno(
                "Clear art cache", "Delete every cached image? The next "
                "build of each project converts and cooks all its art "
                "again.", parent=self):
            clear_cache()
            self._show_usage()

    def on_apply(self):
        percent = int(self.scale.get().rstrip("%"))
        if percent != theme.ui_scale():
            theme.apply_ui_scale(percent)
            theme.save_setting("ui_scale", percent)
            fit_to_screen(self)
        low, high = theme.ART_CACHE_GB_RANGE
        current = theme.art_cache_gb() or ART_CACHE_MAX_BYTES // 1024 ** 3
        try:
            gb = min(max(int(self.cache_gb.get()), low), high)
        except ValueError:                    # not a number: unchanged
            gb = current
        self.cache_gb.set(str(gb))
        if gb != current:     # (untouched, the default can still change)
            theme.save_setting("art_cache_gb", gb)

    def on_ok(self):
        self.on_apply()
        self.destroy()
