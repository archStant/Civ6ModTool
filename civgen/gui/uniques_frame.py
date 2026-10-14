"""The unique items of a civilization or a leader (see uniques.py): a list
with Add / Edit / Duplicate / Remove, editing each in a UniqueEditor."""

import copy

from tkinter import ttk

from ..references import retarget, unique_type
from ..uniques import KINDS, KIND_LABELS, MAIN_TABLES, new_unique_spec
from ..util import slug_for_name
from .unique_editor import UniqueEditor


def unique_choices(uniques, kind, prefix):
    """[(type, name)] of the unique specs of a kind (effect dropdowns,
    moment pictures)."""
    out = []
    for u in uniques or []:
        if u.get("kind") == kind and u.get("name"):
            word = MAIN_TABLES[kind][1][:-len("Type")].upper()
            out.append((slug_for_name(u["name"], prefix, kind=word),
                        u["name"]))
    return out


class UniquesFrame(ttk.Frame):
    """app: the main window; uniques: the unique specs; owner_name(): the
    owner's name (for the editor's title); others(kind): [(type, name)] of
    the project's other uniques the owner's may refer to (a leader's
    civilization's); changed(): called after every change; renamed(
    mapping): called with {old type: new type} when a unique is renamed
    (after its references among these uniques followed it)."""

    def __init__(self, parent, app, uniques, owner_name, intro,
                 others=lambda kind: [], changed=lambda: None,
                 renamed=lambda mapping: None):
        super().__init__(parent)
        self.app, self.owner_name, self.others = app, owner_name, others
        self.changed, self.renamed = changed, renamed
        self.items = copy.deepcopy(list(uniques or []))
        ttk.Label(self, wraplength=760, justify="left", text=intro).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        self.tree = ttk.Treeview(self, columns=("kind", "base"),
                                 show="tree headings", height=10,
                                 selectmode="browse")
        self.tree.heading("#0", text="Name")
        self.tree.column("#0", width=240)
        self.tree.heading("kind", text="Kind")
        self.tree.column("kind", width=90)
        self.tree.heading("base", text="Copy of")
        self.tree.column("base", width=260)
        self.tree.grid(row=1, column=0, sticky="nsew")
        self.tree.bind("<Double-1>", lambda e: self.on_edit())
        btns = ttk.Frame(self)
        btns.grid(row=1, column=1, sticky="n", padx=(8, 0))
        for kind in KINDS:
            ttk.Button(btns, text="Add {}...".format(
                KIND_LABELS[kind].lower()),
                command=lambda k=kind: self.on_add(k)).pack(fill="x", pady=2)
        ttk.Separator(btns).pack(fill="x", pady=6)
        for text, cmd in (("Edit...", self.on_edit),
                          ("Duplicate", self.on_duplicate),
                          ("Remove", self.on_remove)):
            ttk.Button(btns, text=text, command=cmd).pack(fill="x", pady=2)
        self.refresh()

    def refresh(self):
        tree, data = self.tree, self.app.data
        tree.delete(*tree.get_children())
        for i, u in enumerate(self.items):
            tree.insert("", "end", iid=str(i), text=u.get("name", ""),
                        values=(KIND_LABELS.get(u.get("kind"), ""),
                                data.type_name(u.get("kind"), u["base"])
                                if u.get("base") else "(new)"))

    def _changed(self):
        self.refresh()
        self.changed()

    def own_types(self, kind):
        """[(type, name)] of these uniques of a kind."""
        return unique_choices(self.items, kind, self.app.type_prefix())

    def types(self, kind):
        """These uniques of a kind and the others the owner's may refer
        to."""
        own = self.own_types(kind)
        known = {t for t, _ in own}
        return own + [c for c in self.others(kind) if c[0] not in known]

    def _dialog(self, spec):
        editor = UniqueEditor(self.winfo_toplevel(), self.app, spec,
                              self.owner_name(), self.types)
        self.wait_window(editor)
        self.winfo_toplevel().grab_set()        # the editor took the grab
        return editor.result

    def _selected(self):
        sel = self.tree.selection()
        return int(sel[0]) if sel else None

    def on_add(self, kind):
        result = self._dialog(new_unique_spec(kind))
        if result:
            self.items.append(result)
            self._changed()

    def on_edit(self):
        i = self._selected()
        if i is None:
            return
        old = unique_type(self.items[i], self.app.type_prefix())
        result = self._dialog(copy.deepcopy(self.items[i]))
        if result:
            self.items[i] = result
            new = unique_type(result, self.app.type_prefix())
            if old and new and old != new:      # renamed
                # (other uniques' districts and effects follow it)
                retarget(self.items, {old: new})
                self.renamed({old: new})
            self._changed()

    def on_duplicate(self):
        i = self._selected()
        if i is not None:
            u = copy.deepcopy(self.items[i])
            u["name"] = (u.get("name") or "Unique") + " copy"
            self.items.insert(i + 1, u)
            self._changed()

    def on_remove(self):
        i = self._selected()
        if i is not None:
            del self.items[i]
            self._changed()

    def uniques(self):
        return copy.deepcopy(self.items)
