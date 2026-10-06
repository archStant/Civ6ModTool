"""The unit model designer: a model put together from the game's own
model parts (see unit_models.py)."""

import copy

import tkinter as tk
from tkinter import messagebox, ttk

from ..unit_models import (SECTION_LABELS, model_sections, new_design,
                           normalize_design)
from ..util import find_game_dir
from . import help_texts
from .widgets import HelpBox, ScrollFrame, add_tooltip

ON_FOOT = "(on foot)"

HINT = ("Build a figure from the game's own parts: start from a model, "
        "optionally put it on a mount, then swap, remove or add parts. "
        "Hover over a column name for a hint.")


class ModelDesigner(tk.Toplevel):
    """Edit a design (see unit_models.py); .result holds it after OK.
    taken: ids of the unit's other designs."""

    def __init__(self, parent, app, design, taken=()):
        super().__init__(parent)
        self.app, self.taken = app, set(taken)
        self.result = None
        self.title("Model designer")
        self.transient(parent)
        self.resizable(True, True)
        design = copy.deepcopy(design)
        parts = app.data.unit_parts

        outer = ttk.Frame(self, padding=10)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text=HINT, wraplength=980, justify="left",
                  foreground="gray25").pack(anchor="w", pady=(0, 2))
        HelpBox(outer, help_texts.DESIGNER, wraplength=980).pack(
            anchor="w", pady=(0, 6))
        top = ttk.Frame(outer)
        top.pack(anchor="w", fill="x")
        ttk.Label(top, text="Name").grid(row=0, column=0, sticky="w")
        self.id_var = tk.StringVar(value=design.get("id", ""))
        ttk.Entry(top, textvariable=self.id_var, width=20).grid(
            row=0, column=1, sticky="w", padx=6)
        label = ttk.Label(top, text="Start from (?)")
        label.grid(row=0, column=2, sticky="w", padx=(12, 0))
        add_tooltip(label, help_texts.DESIGNER_TIPS["template"])
        self.template_var = tk.StringVar(value=design.get("template", ""))
        ttk.Combobox(top, textvariable=self.template_var, width=28,
                     values=parts["models"]).grid(row=0, column=3,
                                                  sticky="w", padx=6)
        label = ttk.Label(top, text="Mount (?)")
        label.grid(row=0, column=4, sticky="w", padx=(12, 0))
        add_tooltip(label, help_texts.DESIGNER_TIPS["mount"])
        self.mount_var = tk.StringVar(value=design.get("mount") or ON_FOOT)
        ttk.Combobox(top, textvariable=self.mount_var, width=24,
                     values=[ON_FOOT] + parts["mounted"]).grid(
            row=0, column=5, sticky="w", padx=6)
        ttk.Button(top, text="Load its parts", command=self.on_load).grid(
            row=0, column=6, sticky="w", padx=(12, 0))

        self.scroll = ScrollFrame(outer, height=440)
        self.scroll.pack(fill="both", expand=True, pady=(8, 0))
        self.rows = {}                  # section -> [row dict]
        self.loaded = (design.get("template", ""), design.get("mount", ""))
        sections = design.get("parts") or {}
        if not sections and design.get("template"):
            sections = model_sections(find_game_dir(), design["template"],
                                      design.get("mount", "")) or {}
        self._build_sections(sections)

        btns = ttk.Frame(outer)
        btns.pack(anchor="e", pady=(10, 0))
        ttk.Button(btns, text="OK", command=self.on_ok).pack(side="left",
                                                             padx=4)
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(
            side="left", padx=4)
        self.grab_set()
        self.bind("<Escape>", lambda e: self.destroy())

    # -- parts ----------------------------------------------------------------

    def _mount(self):
        mount = self.mount_var.get().strip()
        return "" if mount == ON_FOOT else mount

    def on_load(self):
        template, mount = self.template_var.get().strip(), self._mount()
        if not template:
            messagebox.showinfo("No model", "Pick the model to start from.",
                                parent=self)
            return
        if template in self.app.data.unit_parts["mounted"] and mount:
            messagebox.showinfo(
                "Already mounted", "{} is mounted already - pick a figure on "
                "foot to put it on another mount.".format(template),
                parent=self)
            return
        sections = model_sections(find_game_dir(), template, mount)
        if sections is None:
            messagebox.showwarning("Model not found", "{} was not found in "
                                   "the game's art.".format(
                                       mount or template), parent=self)
            return
        if any(self.rows.values()) and not messagebox.askyesno(
                "Replace parts", "Replace the parts with those of {}?".format(
                    template + (" on " + mount if mount else "")),
                parent=self):
            return
        self.loaded = (template, mount)
        self._build_sections(sections)

    def _build_sections(self, sections):
        inner = self.scroll.inner
        for widget in inner.winfo_children():
            widget.destroy()
        self.rows = {}
        for r, section in enumerate(s for s in ("body", "rider", "horse")
                                    if s in sections):
            box = ttk.LabelFrame(inner, text=SECTION_LABELS[section],
                                 padding=(6, 4))
            box.grid(row=r, column=0, sticky="we", pady=(0, 8))
            for col, (text, tip) in enumerate((
                    ("Slot", "slot"), ("Point", "point"),
                    ("Category", "category"), ("Mesh", "mesh"),
                    ("Extra meshes", "extra"), ("Tint", "tint"))):
                header = ttk.Label(box, text=text + " (?)")
                header.grid(row=0, column=col, sticky="w", padx=3)
                add_tooltip(header, help_texts.DESIGNER_TIPS[tip])
            self.rows[section] = []
            for part in sections[section]:
                self._add_row(box, section, part)
            ttk.Button(box, text="Add part", command=lambda b=box, s=section:
                       self._add_row(b, s, {"slot": "", "point": "Root",
                                            "tint": "", "bins": []})).grid(
                row=999, column=0, sticky="w", pady=(4, 0))
        if not sections:
            ttk.Label(inner, foreground="gray25", text=(
                "(pick the model to start from and press 'Load its parts' - "
                "the game must be installed)")).grid(row=0, column=0,
                                                     sticky="w")

    def _add_row(self, box, section, part):
        parts = self.app.data.unit_parts
        bins = list(part.get("bins") or [])
        first = bins[0] if bins else ""
        category, _, group = first.partition("/")
        row = {"slot": tk.StringVar(value=part.get("slot", "")),
               "point": tk.StringVar(value=part.get("point", "")),
               "category": tk.StringVar(value=category),
               "group": tk.StringVar(value=group),
               "extra": tk.StringVar(value=", ".join(bins[1:])),
               "tint": tk.StringVar(value=part.get("tint", ""))}
        r = len(self.rows[section]) + 1
        group_combo = ttk.Combobox(box, textvariable=row["group"], width=24,
                                   values=parts["bins"].get(category, []))

        def category_changed(*_):
            group_combo["values"] = parts["bins"].get(
                row["category"].get().strip(), [])

        row["category"].trace_add("write", category_changed)
        widgets = [
            ttk.Entry(box, textvariable=row["slot"], width=14),
            ttk.Combobox(box, textvariable=row["point"], width=16,
                         values=parts["points"]),
            ttk.Combobox(box, textvariable=row["category"], width=22,
                         values=list(parts["bins"])),
            group_combo,
            ttk.Entry(box, textvariable=row["extra"], width=30),
            ttk.Combobox(box, textvariable=row["tint"], width=18,
                         values=[""] + parts["tints"]),
            ttk.Button(box, text="Remove",
                       command=lambda: self._remove_row(section, row))]
        for col, widget in enumerate(widgets):
            widget.grid(row=r, column=col, sticky="w", padx=3, pady=1)
        row["widgets"] = widgets
        self.rows[section].append(row)

    def _remove_row(self, section, row):
        for widget in row["widgets"]:
            widget.destroy()
        self.rows[section].remove(row)

    # -- result ---------------------------------------------------------------

    def design(self):
        parts = {}
        for section, rows in self.rows.items():
            parts[section] = []
            for row in rows:
                category = row["category"].get().strip()
                group = row["group"].get().strip()
                first = "{}/{}".format(category, group) if group else category
                bins = [first] if first else []
                bins += [b.strip() for b in row["extra"].get().split(",")
                         if b.strip()]
                parts[section].append({
                    "slot": row["slot"].get().strip(),
                    "point": row["point"].get().strip(),
                    "tint": row["tint"].get().strip(), "bins": bins})
        template, mount = self.loaded
        return dict(new_design(template, mount), id=self.id_var.get(),
                    parts=parts)

    def on_ok(self):
        design = self.design()
        if (self.template_var.get().strip(), self._mount()) != self.loaded:
            messagebox.showinfo(
                "Parts not loaded", "The model to start from or the mount "
                "changed - press 'Load its parts' first (or set them back).",
                parent=self)
            return
        try:
            design = normalize_design(design, "Model")
        except ValueError as exc:
            messagebox.showwarning("Model", str(exc), parent=self)
            return
        if design["id"] in self.taken:
            messagebox.showwarning("Model", "The unit already has a model "
                                   "called {}.".format(design["id"]),
                                   parent=self)
            return
        self.result = design
        self.destroy()
