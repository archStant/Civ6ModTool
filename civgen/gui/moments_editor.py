"""Editing historic moment illustrations (see moments.py)."""

import os

import tkinter as tk
from tkinter import ttk

from ..art import MOMENT_HALF_OPACITY, MOMENT_MASK, apply_image_mask
from ..util import asset_path
from .widgets import browse_image

HELP = (
    "Custom pictures for the historic moment shown when the civilization "
    "first trains or builds one of its unique units, buildings or "
    "districts (Rise and Fall / Gathering Storm).\n\n"
    "Mods cannot add new moments - when a moment fires is decided by the "
    "game itself - so this replaces the picture of that existing moment. "
    "The picture belongs to the item: it is shown for every leader of the "
    "civilization. Tech and civic moments have no per-item pictures. "
    "Images are cropped to 456 x 332 like the game's own.")


class MomentsFrame(ttk.Frame):
    """A list of moment illustration rows (item, image, mask, 75%,
    sepia). items(): the item types offered in the item dropdowns."""

    def __init__(self, parent, entries, items, help_text=HELP):
        super().__init__(parent)
        self.items = items
        ttk.Label(self, wraplength=860, justify="left",
                  text=help_text).grid(row=0, column=0, sticky="w",
                                       pady=(0, 10))
        self.moment_list = ttk.Frame(self)
        self.moment_list.grid(row=1, column=0, sticky="w")
        self.rows = []
        for entry in entries or []:
            self.add_row(entry)
        ttk.Button(self, text="Add illustration",
                   command=self.add_row).grid(row=2, column=0, sticky="w",
                                              pady=8)

    def refresh_items(self):
        items = self.items()
        for row in self.rows:
            row["combo"]["values"] = items

    def add_row(self, entry=None):
        entry = entry or {}
        frame = ttk.Frame(self.moment_list)
        frame.pack(anchor="w", pady=3)
        row = {"frame": frame,
               "item": tk.StringVar(value=entry.get("item", "")),
               "path": tk.StringVar(value=entry.get("path", "")),
               "mask": tk.BooleanVar(value=bool(entry.get("mask"))),
               "half": tk.BooleanVar(value=bool(entry.get("half"))),
               "sepia": tk.BooleanVar(value=bool(entry.get("sepia")))}
        row["thumb"] = ttk.Label(frame, width=12)
        row["thumb"].pack(side="left", padx=(0, 8))
        ttk.Label(frame, text="Item").pack(side="left")
        row["combo"] = ttk.Combobox(frame, textvariable=row["item"],
                                    width=32, values=self.items())
        row["combo"].pack(side="left", padx=(4, 12))
        ttk.Label(frame, text="Image").pack(side="left")
        ttk.Entry(frame, textvariable=row["path"], width=34).pack(
            side="left", padx=4)
        ttk.Button(frame, text="Browse...", command=lambda: browse_image(
            self, row["path"], "Historic moment image")).pack(side="left")
        mask_check = ttk.Checkbutton(frame, text="Fade mask",
                                     variable=row["mask"])
        mask_check.pack(side="left", padx=(10, 0))
        if not asset_path(MOMENT_MASK):
            mask_check.state(["disabled"])
            mask_check.configure(text="Fade mask (assets/{} not found)"
                                 .format(MOMENT_MASK))
        ttk.Checkbutton(frame, text="75% transparent",
                        variable=row["half"]).pack(side="left", padx=(6, 0))
        ttk.Checkbutton(frame, text="Sepia",
                        variable=row["sepia"]).pack(side="left", padx=(6, 0))
        ttk.Button(frame, text="Remove",
                   command=lambda: self._remove_row(row)).pack(
            side="left", padx=(10, 0))
        for var in ("path", "mask", "half", "sepia"):
            row[var].trace_add("write", lambda *_: self._refresh_thumb(row))
        self.rows.append(row)
        self._refresh_thumb(row)

    def _remove_row(self, row):
        row["frame"].destroy()
        self.rows.remove(row)

    def _refresh_thumb(self, row):
        """Preview cropped (and masked / faded) like the generated
        illustration (456 x 332), on a dark backdrop so transparency
        shows."""
        row["photo"] = None
        path = row["path"].get().strip()
        try:
            from PIL import Image, ImageTk
            if path and os.path.isfile(path):
                img = apply_image_mask(
                    path, asset_path(MOMENT_MASK) if row["mask"].get()
                    else None, size=(91, 66),
                    opacity=MOMENT_HALF_OPACITY if row["half"].get()
                    else 1.0, sepia=row["sepia"].get())
                backdrop = Image.new("RGBA", img.size, (43, 43, 43, 255))
                row["photo"] = ImageTk.PhotoImage(
                    Image.alpha_composite(backdrop, img))
        except Exception:               # no Pillow / unreadable image
            pass
        row["thumb"].configure(image=row["photo"] or "",
                               text="" if row["photo"] else "(no image)")

    def entries(self):
        out = []
        for row in self.rows:
            item = row["item"].get().strip().upper()
            path = row["path"].get().strip()
            if item or path:
                out.append({"item": item, "path": path,
                            "mask": bool(row["mask"].get()),
                            "half": bool(row["half"].get()),
                            "sepia": bool(row["sepia"].get())})
        return out
