"""Publishing on the Steam Workshop: the project's Workshop details, the
uploader's checks, and a guide through the SDK's uploader (see
workshop.py)."""

import os
import webbrowser

import tkinter as tk
from tkinter import messagebox, ttk

from ..workshop import (MAX_DESCRIPTION, MAX_TITLE, PREVIEW_STYLES,
                        VISIBILITIES,
                        check_mod, find_modinfo, generated_description,
                        launch_uploader, make_preview, normalize_workshop,
                        steam_running, workshop_url)
from . import theme
from .widgets import (HelpBox, ImagePreview, ScrollFrame, add_tooltip,
                      browse_image, fit_to_screen)

HELP = """
The Civ VI SDK's Steam Workshop uploader publishes the mod. It has no way to be filled in automatically, so this window prepares everything and tells you what to enter.

Details: what the Workshop page shows. Empty title: the mod's name; empty description: one made of the project's civilizations, leaders and uniques (Regenerate refreshes it). The description and version also go into the mod's .modinfo - generate the mod again after changing them.

Updates: the mod keeps its id (a GUID) from build to build, and the uploader updates the Workshop item with that id instead of making a new one. Raise the version for each update and write what changed in the change notes.

Publish: generate the mod, fix anything the checks flag, then open the uploader. In it, pick the .modinfo shown here, fill in the details (Copy buttons), choose the visibility and upload. Paste the item's address back here afterwards to keep a link to it.
"""


class WorkshopDialog(tk.Toplevel):
    """The Workshop details of app.project and the publishing guide."""

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("Publish to Steam Workshop")
        self.transient(app)
        self.workshop = normalize_workshop(app.project.get("workshop"))

        outer = ttk.Frame(self, padding=10)
        outer.pack(fill="both", expand=True)
        btns = ttk.Frame(outer)
        btns.pack(side="bottom", anchor="e", pady=(10, 0))
        ttk.Button(btns, text="Save", command=self.on_save).pack(
            side="left", padx=4)
        ttk.Button(btns, text="Close", command=self.on_close).pack(
            side="left", padx=4)
        notebook = ttk.Notebook(outer)
        notebook.pack(fill="both", expand=True)
        details = ScrollFrame(notebook, height=None)
        publish = ScrollFrame(notebook, height=None)
        notebook.add(details, text="Details")
        notebook.add(publish, text="Publish")
        self._build_details(details.inner)
        self._build_publish(publish.inner)
        notebook.bind("<<NotebookTabChanged>>",
                      lambda e: self.refresh_checks())

        fit_to_screen(self)
        self.grab_set()
        self.bind("<Escape>", lambda e: self.on_close())
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # -- details ----------------------------------------------------------

    def _build_details(self, body):
        pad = {"padx": 6, "pady": 3}
        w = self.workshop
        HelpBox(body, HELP, wraplength=860).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))

        ttk.Label(body, text="Title").grid(row=1, column=0, sticky="w",
                                           **pad)
        self.title_var = tk.StringVar(value=w["title"])
        ttk.Entry(body, textvariable=self.title_var, width=60).grid(
            row=1, column=1, sticky="w", **pad)
        self.title_count = ttk.Label(body, foreground=theme.hint())
        self.title_count.grid(row=1, column=2, sticky="w", **pad)
        self.title_var.trace_add("write", lambda *_: self._count())

        ttk.Label(body, text="Description").grid(row=2, column=0,
                                                 sticky="nw", **pad)
        self.desc = tk.Text(body, height=14, width=90, wrap="word",
                            undo=True)
        self.desc.insert("1.0", w["description"] or self._generated())
        self.desc.grid(row=2, column=1, columnspan=2, sticky="w", **pad)
        self.desc.bind("<<Modified>>", self._on_desc_modified)
        row = ttk.Frame(body)
        row.grid(row=3, column=1, columnspan=2, sticky="w", padx=6)
        ttk.Button(row, text="Regenerate from project",
                   command=self.regenerate).pack(side="left")
        self.desc_count = ttk.Label(row, foreground=theme.hint())
        self.desc_count.pack(side="left", padx=10)
        ttk.Label(row, text="Steam BBCode: [h2] heading, [b] bold, "
                            "[list][*] item [/list]",
                  foreground=theme.hint()).pack(side="left", padx=10)

        ttk.Label(body, text="Visibility").grid(row=5, column=0,
                                                sticky="w", **pad)
        vis = ttk.Frame(body)
        vis.grid(row=5, column=1, sticky="w", **pad)
        self.visibility = tk.StringVar(value=w["visibility"])
        for value in VISIBILITIES:
            ttk.Radiobutton(vis, text=value, value=value,
                            variable=self.visibility).pack(
                side="left", padx=(0, 12))

        ttk.Label(body, text="Version (?)").grid(row=6, column=0,
                                                 sticky="w", **pad)
        version_row = ttk.Frame(body)
        version_row.grid(row=6, column=1, sticky="w", **pad)
        self.version = tk.StringVar(value=str(w["version"]))
        spin = ttk.Spinbox(version_row, from_=1, to=9999, width=6,
                           textvariable=self.version)
        spin.pack(side="left")
        add_tooltip(spin, "The mod's version (in its .modinfo). Raise it "
                    "for each update you publish.")
        ttk.Label(version_row, text="Author").pack(side="left",
                                                   padx=(20, 6))
        self.author = tk.StringVar(value=w["author"])
        ttk.Entry(version_row, textvariable=self.author, width=30).pack(
            side="left")

        ttk.Label(body, text="Preview image").grid(row=7, column=0,
                                                   sticky="nw", **pad)
        preview_row = ttk.Frame(body)
        preview_row.grid(row=7, column=1, columnspan=2, sticky="w", **pad)
        self.preview = tk.StringVar(value=w["preview_path"])
        ImagePreview(preview_row, self.preview).pack(side="left")
        ttk.Entry(preview_row, textvariable=self.preview, width=50).pack(
            side="left", padx=6)
        ttk.Button(preview_row, text="Browse...", command=lambda:
                   browse_image(self, self.preview, "Preview image")).pack(
            side="left")
        ttk.Button(preview_row, text="Make from project",
                   command=self.make_preview).pack(side="left", padx=6)
        self.preview_style = tk.StringVar(value=w["preview_style"])
        for value, label in PREVIEW_STYLES:
            radio = ttk.Radiobutton(preview_row, text=label, value=value,
                                    variable=self.preview_style)
            radio.pack(side="left", padx=(4, 0))
            add_tooltip(radio, {
                "simple": "The civilization's icon (or a leader's "
                          "portrait) on a plain backdrop, with the title.",
                "busy": "A collage of the mod's own images: a loading "
                        "background, the leaders' portraits, historic "
                        "moment pictures, the civilization's icon and the "
                        "uniques' icons, with the title and what the mod "
                        "adds."}[value])
        ttk.Label(body, text="(a .jpg or .png under 1 MB, shown on the "
                             "Workshop page; square looks best)",
                  foreground=theme.hint()).grid(row=8, column=1,
                                                columnspan=2, sticky="w",
                                                padx=6)

        ttk.Label(body, text="Change notes").grid(row=9, column=0,
                                                  sticky="nw", **pad)
        self.notes = tk.Text(body, height=4, width=90, wrap="word",
                             undo=True)
        self.notes.insert("1.0", w["change_notes"])
        self.notes.grid(row=9, column=1, columnspan=2, sticky="w", **pad)

        ttk.Label(body, text="Workshop item").grid(row=10, column=0,
                                                   sticky="w", **pad)
        item_row = ttk.Frame(body)
        item_row.grid(row=10, column=1, columnspan=2, sticky="w", **pad)
        self.published = tk.StringVar(value=w["published_id"])
        ttk.Entry(item_row, textvariable=self.published, width=50).pack(
            side="left")
        self.view_btn = ttk.Button(item_row, text="View on Workshop",
                                   command=self.view_item)
        self.view_btn.pack(side="left", padx=6)
        ttk.Label(body, text="(after the first upload: paste the item's "
                             "address or id, for a link to it)",
                  foreground=theme.hint()).grid(row=11, column=1,
                                                columnspan=2, sticky="w",
                                                padx=6)
        self.published.trace_add("write", lambda *_: self._refresh_view())
        self._refresh_view()
        self._count()

    def _generated(self):
        app = self.app
        return generated_description(
            app.mod_name_var.get().strip() or "Alternate Leaders",
            app.project["civs"], app.project["leaders"],
            app.civ_display_name)

    def regenerate(self):
        if self.desc.get("1.0", "end").strip() and not messagebox.askyesno(
                "Regenerate description", "Replace the description with "
                "one made of the project?", parent=self):
            return
        self.desc.delete("1.0", "end")
        self.desc.insert("1.0", self._generated())

    def make_preview(self):
        path = os.path.join(os.path.dirname(self.app.mod_dir()),
                            os.path.basename(self.app.mod_dir()) +
                            "_Workshop", "preview.jpg")
        try:
            make_preview(path, self.title_var.get().strip() or
                         self.app.mod_name_var.get().strip(),
                         self.app.project["civs"], self.app.project["leaders"],
                         self.preview_style.get())
        except ImportError:
            messagebox.showerror("Pillow needed", "Making a preview needs "
                                 "Pillow (pip install Pillow).", parent=self)
            return
        except OSError as exc:
            messagebox.showerror("Could not make the preview", str(exc),
                                 parent=self)
            return
        self.preview.set("")            # reload the thumbnail
        self.preview.set(path)

    def view_item(self):
        url = workshop_url(self.published.get())
        if url:
            webbrowser.open(url)

    def _refresh_view(self):
        self.view_btn.state(["!disabled"] if workshop_url(
            self.published.get()) else ["disabled"])

    def _on_desc_modified(self, _event=None):
        self.desc.edit_modified(False)
        self._count()

    def _count(self):
        title = self.title_var.get().strip() or \
            self.app.mod_name_var.get().strip()
        self.title_count.configure(text="{} / {}".format(len(title),
                                                         MAX_TITLE))
        if hasattr(self, "desc_count"):
            self.desc_count.configure(text="{} / {} characters".format(
                len(self.desc.get("1.0", "end").strip()), MAX_DESCRIPTION))

    def current(self):
        """The Workshop spec as edited."""
        description = self.desc.get("1.0", "end").strip()
        try:
            version = max(1, int(self.version.get()))
        except ValueError:
            version = self.workshop["version"]
        return {
            "title": self.title_var.get().strip(),
            # the generated text is kept as "" (it follows the project)
            "description": "" if description == self._generated().strip()
            else description,
            "visibility": self.visibility.get(),
            "version": version,
            "author": self.author.get().strip(),
            "preview_path": self.preview.get().strip(),
            "preview_style": self.preview_style.get(),
            "change_notes": self.notes.get("1.0", "end").strip(),
            "published_id": self.published.get().strip()}

    # -- publish ----------------------------------------------------------

    def _build_publish(self, body):
        heading = ("TkDefaultFont", 10, "bold")
        ttk.Label(body, text="1. Check the mod", font=heading).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 4))
        self.check_frame = ttk.Frame(body)
        self.check_frame.grid(row=1, column=0, columnspan=3, sticky="w",
                              padx=12)
        row = ttk.Frame(body)
        row.grid(row=2, column=0, columnspan=3, sticky="w", padx=12,
                 pady=(4, 10))
        ttk.Button(row, text="Generate mod now",
                   command=self.generate).pack(side="left")
        ttk.Button(row, text="Check again",
                   command=self.refresh_checks).pack(side="left", padx=6)
        ttk.Button(row, text="Open mod folder", command=lambda:
                   self.app._open_folder(self.app.mod_dir())).pack(
            side="left")

        ttk.Label(body, text="2. Open the uploader", font=heading).grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(6, 4))
        row = ttk.Frame(body)
        row.grid(row=4, column=0, columnspan=3, sticky="w", padx=12)
        ttk.Button(row, text="Open Steam Workshop uploader",
                   command=self.launch).pack(side="left")
        self.launch_info = ttk.Label(row, foreground=theme.hint())
        self.launch_info.pack(side="left", padx=10)
        ttk.Label(body, wraplength=860, justify="left",
                  foreground=theme.hint(), text=(
                      "Steam must be running. The first time, the uploader "
                      "asks you to accept the Workshop legal agreement.")
                  ).grid(row=5, column=0, columnspan=3, sticky="w",
                         padx=12)

        ttk.Label(body, text="3. In the uploader", font=heading).grid(
            row=6, column=0, columnspan=3, sticky="w", pady=(12, 4))
        self.steps = ttk.Frame(body)
        self.steps.grid(row=7, column=0, columnspan=3, sticky="w",
                        padx=12)
        self.refresh_checks()

    def _values(self):
        """The values to upload (the current edits, empty ones filled)."""
        w = self.current()
        values = self.app.publish_values()
        values.update({k: v for k, v in w.items() if v not in ("", None)})
        values["title"] = values["title"][:MAX_TITLE]
        return values

    def refresh_checks(self):
        for widget in self.check_frame.winfo_children():
            widget.destroy()
        values = self._values()
        saved = self.current() == normalize_workshop(
            self.app.project.get("workshop"))
        results = check_mod(self.app.mod_dir(), values,
                            self.app.build_stamp() if saved else None)
        if not saved:
            results.insert(0, (False, "Save the details first (they go "
                                      "into the mod), then generate"))
        for i, (ok, text) in enumerate(results):
            ttk.Label(self.check_frame, text="✓" if ok else "✗",
                      foreground="#2e9e4f" if ok else "#d64541",
                      font=("TkDefaultFont", 10, "bold")).grid(
                row=i, column=0, sticky="nw")
            ttk.Label(self.check_frame, text=text, wraplength=820,
                      justify="left").grid(row=i, column=1, sticky="w",
                                           padx=(6, 0))
        self.all_ok = all(ok for ok, _ in results)
        self._build_steps(values)
        path = self.app.uploader_path(ask=False)
        self.launch_info.configure(text=path or "(the uploader was not "
                                   "found - you will be asked for it)")

    def _build_steps(self, values):
        for widget in self.steps.winfo_children():
            widget.destroy()
        modinfo = find_modinfo(self.app.mod_dir()) or \
            "(generate the mod first)"
        rows = [
            ("Upload new / update", "Choose the mod file", modinfo),
            ("Title", "", values["title"]),
            ("Description", "", values["description"]),
            ("Preview image", "", values.get("preview_path") or
             "(none yet - make one on the Details tab)"),
            ("Visibility", "choose", values["visibility"]),
            ("Change notes", "", values.get("change_notes") or "")]
        for i, (label, verb, value) in enumerate(rows):
            ttk.Label(self.steps, text=label).grid(row=i, column=0,
                                                   sticky="nw", pady=2)
            shown = value if len(value) <= 90 else value[:87] + "..."
            ttk.Label(self.steps, text=(verb + ": " if verb else "") +
                      (shown.splitlines()[0] if shown else "(empty)"),
                      foreground=theme.hint()).grid(
                row=i, column=1, sticky="w", padx=8, pady=2)
            if value and not value.startswith("("):
                ttk.Button(self.steps, text="Copy",
                           command=lambda v=value: self.copy(v)).grid(
                    row=i, column=2, sticky="w", pady=2)

    def copy(self, text):
        self.clipboard_clear()
        self.clipboard_append(text)

    def generate(self):
        self.on_save(close=False)
        if self.app.on_generate(ask_open=False):
            self.refresh_checks()

    def launch(self):
        if not self.all_ok and not messagebox.askyesno(
                "Not ready", "Some checks failed - the uploader may refuse "
                "the mod. Open it anyway?", parent=self):
            return
        path = self.app.uploader_path()
        if not path:
            return
        if not steam_running() and not messagebox.askyesno(
                "Steam is not running", "The uploader needs Steam running "
                "and logged in. Open it anyway?", parent=self):
            return
        try:
            launch_uploader(path)
        except OSError as exc:
            messagebox.showerror("Could not open the uploader", str(exc),
                                 parent=self)

    # -- result -----------------------------------------------------------

    def on_save(self, close=True):
        self.app.project["workshop"] = self.current()
        self.workshop = normalize_workshop(self.app.project["workshop"])
        self.app._update_save_button()
        self.refresh_checks()
        if close:
            self.destroy()

    def on_close(self):
        if self.current() != normalize_workshop(
                self.app.project.get("workshop")) and messagebox.askyesno(
                "Unsaved details", "Keep the changes to the Workshop "
                "details?", parent=self):
            self.on_save()
            return
        self.destroy()
