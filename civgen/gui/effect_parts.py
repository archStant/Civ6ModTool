"""Parts of the effect dialog (modifier_editor.EffectDialog): the
arguments of any of the game's modifier types (advanced mode) and an
effect's requirements - the editor's conditions and, in advanced mode,
the game's requirement types, groups of them and sets met by any one."""

import tkinter as tk
from tkinter import ttk

from ..modifiers import (ARG_KINDS, REQUIREMENTS, readable_type, req_kind,
                         summary, usual_args)
from . import theme
from .widgets import FilterCombo

TARGET_LABELS = {"subject": "what it applies to", "owner": "its owner",
                 "units": "which units get it"}
GROUP_LABELS = {"ANY": "Any of these", "ALL": "All of these"}


def _labelled_combo(parent, labels, value, width=18, command=None):
    """A read-only combobox of {value: label}; returns (widget, getter)."""
    var = tk.StringVar(value=labels.get(value, value))
    widget = ttk.Combobox(parent, textvariable=var, width=width,
                          state="readonly", values=list(labels.values()))
    back = {label: v for v, label in labels.items()}
    if command:
        widget.bind("<<ComboboxSelected>>", lambda e: command())
    return widget, lambda: back.get(var.get(), var.get())


class ArgsTable(ttk.Frame):
    """Arguments (name: value) of a raw effect or requirement: a row each,
    and a list to add one from (the names the game gives the type, with
    an example value), or any name typed in. dialog: the EffectDialog."""

    def __init__(self, parent, dialog, args=None):
        super().__init__(parent)
        self.dialog = dialog
        self.rows = []                  # (name, getter, frame)
        self.known = []                 # [(name, uses, example, numeric)]
        self.rows_frame = ttk.Frame(self)
        self.rows_frame.pack(anchor="w", fill="x")
        add = ttk.Frame(self)
        add.pack(anchor="w", pady=(2, 0))
        self.add_var = tk.StringVar()
        self.add_combo = ttk.Combobox(add, textvariable=self.add_var,
                                      width=34)
        self.add_combo.pack(side="left")
        ttk.Button(add, text="Add argument",
                   command=self._add_chosen).pack(side="left", padx=6)
        for name, value in (args or {}).items():
            self.add(name, value)

    def set_known(self, known):
        self.known = list(known)
        self._refresh_choices()

    def _refresh_choices(self):
        have = self.names()
        self.add_combo["values"] = [
            "{} (e.g. {})".format(name, example)
            for name, _, example, _ in self.known if name not in have]

    def _add_chosen(self):
        name = self.add_var.get().split("(", 1)[0].strip()
        if not name or name in self.names():
            return
        example = next((e for n, _, e, _ in self.known if n == name), "")
        self.add(name, example)
        self.add_var.set("")

    def add(self, name, value=""):
        frame = ttk.Frame(self.rows_frame)
        frame.pack(anchor="w", pady=1)
        ttk.Label(frame, text=name, width=24).pack(side="left")
        widget, getter = self.dialog.value_widget(frame, ARG_KINDS.get(name),
                                                  str(value))
        widget.pack(side="left")
        row = (name, getter, frame)
        ttk.Button(frame, text="Remove",
                   command=lambda: self._remove(row)).pack(side="left",
                                                           padx=6)
        self.rows.append(row)
        self._refresh_choices()
        self.dialog.refresh()

    def _remove(self, row):
        row[2].destroy()
        self.rows.remove(row)
        self._refresh_choices()
        self.dialog.refresh()

    def clear(self):
        for row in list(self.rows):
            row[2].destroy()
        self.rows = []
        self._refresh_choices()

    def names(self):
        return {name for name, _, _ in self.rows}

    def values(self):
        return {name: getter() for name, getter, _ in self.rows}


class RawEffectFrame(ttk.Frame):
    """A raw effect (advanced mode): its modifier type, arguments, run
    once / permanent, own summary text and - for a type that attaches a
    modifier - what it attaches: one of the game's modifiers, or an
    effect of its own."""

    def __init__(self, parent, dialog, effect):
        super().__init__(parent)
        self.dialog = dialog
        data = dialog.data
        self.attached = effect.get("attached")
        modifier_type = effect.get("modifier_type") or ""
        args = dict(effect.get("args") or {})
        game_mod = args.pop("ModifierId", "") \
            if data.is_attach(modifier_type) else ""

        top = ttk.Frame(self)
        top.pack(anchor="w", fill="x")
        ttk.Label(top, text="Modifier type").grid(row=0, column=0,
                                                  sticky="w")
        self.type_combo = FilterCombo(top, data.modifier_types(),
                                      modifier_type, width=56)
        self.type_combo.grid(row=0, column=1, sticky="w", padx=6, pady=3)
        self.type_combo.bind("<<ComboboxSelected>>",
                             lambda e: self._type_changed())
        self.type_combo.bind("<FocusOut>", lambda e: self._type_changed())
        self.type_combo.var.trace_add("write", lambda *_: dialog.refresh())
        self.info = ttk.Label(top, wraplength=520, justify="left",
                              foreground=theme.hint())
        self.info.grid(row=1, column=1, sticky="w", padx=6)

        ttk.Label(self, text="Arguments").pack(anchor="w", pady=(6, 0))
        self.args = ArgsTable(self, dialog, args)
        self.args.pack(anchor="w", padx=(16, 0))

        # what it attaches
        self.attach_box = ttk.LabelFrame(self, text="What it attaches",
                                         padding=(8, 4))
        self.attach_mode = tk.StringVar(
            value="own" if self.attached else "game")
        ttk.Radiobutton(self.attach_box, text="One of the game's modifiers",
                        variable=self.attach_mode, value="game",
                        command=dialog.refresh).grid(row=0, column=0,
                                                     sticky="w")
        self.mod_combo = FilterCombo(self.attach_box,
                                     sorted(data.modifier_ids), game_mod,
                                     width=50)
        self.mod_combo.grid(row=0, column=1, sticky="w", padx=6, pady=2)
        self.mod_combo.var.trace_add("write", lambda *_: dialog.refresh())
        ttk.Radiobutton(self.attach_box, text="An effect of its own",
                        variable=self.attach_mode, value="own",
                        command=dialog.refresh).grid(row=1, column=0,
                                                     sticky="w")
        ttk.Button(self.attach_box, text="Define...",
                   command=self._edit_attached).grid(row=1, column=1,
                                                     sticky="w", padx=6)
        self.attached_label = ttk.Label(self.attach_box, wraplength=520,
                                        justify="left",
                                        foreground=theme.hint())
        self.attached_label.grid(row=2, column=0, columnspan=2, sticky="w")

        options = ttk.Frame(self)
        options.pack(anchor="w", pady=(6, 0), fill="x")
        self.run_once = tk.BooleanVar(value=bool(effect.get("run_once")))
        self.permanent = tk.BooleanVar(value=bool(effect.get("permanent")))
        ttk.Checkbutton(options, text="Run once (e.g. a one-off grant)",
                        variable=self.run_once).pack(side="left")
        ttk.Checkbutton(options, text="Permanent (stays when its owner is "
                                      "gone)",
                        variable=self.permanent).pack(side="left", padx=12)
        text_row = ttk.Frame(self)
        text_row.pack(anchor="w", pady=(6, 0), fill="x")
        ttk.Label(text_row, text="Summary (optional)").pack(side="left")
        self.text_var = tk.StringVar(value=effect.get("text") or "")
        self.text_var.trace_add("write", lambda *_: dialog.refresh())
        ttk.Entry(text_row, textvariable=self.text_var, width=60).pack(
            side="left", padx=6)
        kept = []
        if effect.get("arg_types"):
            kept.append("argument types ({})".format(", ".join(
                "{}: {}".format(n, (s or {}).get("Type"))
                for n, s in sorted(effect["arg_types"].items()))))
        if effect.get("columns"):
            kept.append(", ".join("{} {}".format(c, v) for c, v in
                                  sorted(effect["columns"].items())))
        if effect.get("strings"):
            kept.append("texts ({})".format(", ".join(
                sorted(effect["strings"]))))
        if kept:
            ttk.Label(self, wraplength=560, justify="left",
                      foreground=theme.hint(), text=(
                          "Copied from the game as it is: {}.".format(
                              "; ".join(kept)))).pack(anchor="w",
                                                      pady=(6, 0))
        self._type_changed(prefill=False)

    def modifier_type(self):
        return self.type_combo.value().upper()

    def _type_changed(self, prefill=True):
        data, t = self.dialog.data, self.modifier_type()
        info = data.modifier_info(t)
        if info:
            self.info.configure(text="Applies to: {}. Does: {}. The game "
                                "uses it {} times.".format(
                                    readable_type(info["collection"],
                                                  ("COLLECTION_",)),
                                    readable_type(info["effect"],
                                                  ("EFFECT_",)),
                                    info["uses"]))
        else:
            self.info.configure(text="" if not t or not data.conn else
                                "Not one of the game's modifier types.")
        attach = bool(t) and data.is_attach(t)
        skip = ("ModifierId",) if attach else ()
        self.args.set_known([a for a in data.modifier_args(t)
                             if a[0] not in skip])
        if prefill and info and not self.args.rows:
            for name, value in usual_args(info["args"], info["uses"],
                                          skip).items():
                self.args.add(name, value)
        if attach:
            self.attach_box.pack(anchor="w", fill="x", pady=(6, 0),
                                 after=self.args)
        else:
            self.attach_box.pack_forget()
        self._show_attached()
        self.dialog.refresh()

    def _show_attached(self):
        self.attached_label.configure(
            text=summary(self.attached, self.dialog.name_of)
            if self.attached else "(none yet)")

    def _edit_attached(self):
        from ..modifiers import new_effect, templates_for
        from .modifier_editor import EffectDialog
        effect = self.attached or new_effect(
            templates_for("attached")[0].id)
        dialog = EffectDialog(self.winfo_toplevel(), "attached", effect,
                              self.dialog.choices, self.dialog.name_of,
                              self.dialog.data, advanced=True,
                              depth=self.dialog.depth + 1)
        self.wait_window(dialog)
        self.winfo_toplevel().grab_set()        # the dialog took the grab
        if dialog.result:
            self.attached = dialog.result
            self.attach_mode.set("own")
            self._show_attached()
            self.dialog.refresh()

    def values(self):
        """The raw effect's keys as edited (see the modifiers.py
        docstring); "attached" None: attaches none of its own."""
        t = self.modifier_type()
        out = {"modifier_type": t, "args": self.args.values(),
               "run_once": bool(self.run_once.get()),
               "permanent": bool(self.permanent.get()),
               "text": self.text_var.get().strip(), "attached": None}
        if t and self.dialog.data.is_attach(t):
            if self.attach_mode.get() == "own" and self.attached:
                out["attached"] = self.attached
            elif self.mod_combo.value():
                out["args"]["ModifierId"] = self.mod_combo.value()
        return out

    def set_from(self, modifier_type, args, run_once, permanent):
        """Start from a template's modifier type and arguments."""
        self.type_combo.var.set(modifier_type)
        self.args.clear()
        for name, value in args.items():
            self.args.add(name, value)
        self.run_once.set(bool(run_once))
        self.permanent.set(bool(permanent))
        self._type_changed(prefill=False)


# ---------------------------------------------------------------------------
# Requirements
# ---------------------------------------------------------------------------

class _Rows:
    """A list of requirement rows: an effect's, or a group's."""

    def _init_rows(self, parent, dialog, advanced, grouped):
        self.dialog, self.advanced, self.grouped = dialog, advanced, grouped
        self.rows = []
        self.presets = []               # REQUIREMENTS ids offered
        self.list = ttk.Frame(parent)
        self.list.pack(anchor="w", fill="x")

    def add(self, req):
        if req_kind(req) == "group":
            row = GroupBox(self.list, self, req)
        else:
            row = ReqRow(self.list, self, req)
        row.pack(anchor="w", fill="x", pady=2)
        self.rows.append(row)
        self.dialog.refresh()

    def remove(self, row):
        row.destroy()
        self.rows.remove(row)
        self.dialog.refresh()

    def reqs(self):
        return [row.get() for row in self.rows]

    def build_add_bar(self, parent):
        bar = ttk.Frame(parent)
        self.preset_var = tk.StringVar()
        self.preset_combo = ttk.Combobox(bar, textvariable=self.preset_var,
                                         width=36, state="readonly")
        self.preset_combo.pack(side="left")
        ttk.Button(bar, text="Add condition",
                   command=self._add_preset).pack(side="left", padx=6)
        if self.advanced:
            ttk.Button(bar, text="Add game requirement",
                       command=lambda: self.add({
                           "type": "", "args": {}, "not": False,
                           "target": "subject"})).pack(side="left")
            if not self.grouped:
                ttk.Button(bar, text="Add group",
                           command=lambda: self.add({
                               "group": "ANY", "reqs": [], "not": False,
                               "target": "subject"})).pack(side="left",
                                                           padx=6)
        return bar

    def _add_preset(self):
        label = self.preset_var.get()
        preset = next((p for p in self.presets
                       if REQUIREMENTS[p].label == label), None)
        if preset:
            self.add({"preset": preset, "value": ""})

    def set_presets(self, presets):
        self.presets = list(presets)
        self.preset_combo["values"] = [REQUIREMENTS[p].label
                                       for p in self.presets]
        for row in self.rows:
            if isinstance(row, GroupBox):
                row.set_presets(presets)


class ReqRow(ttk.Frame):
    """One requirement: one of the editor's conditions (a preset), or
    (advanced) any of the game's requirement types with its arguments."""

    def __init__(self, parent, rows, req):
        super().__init__(parent)
        self.rows = rows
        dialog = rows.dialog
        self.kind = req_kind(req)
        line = ttk.Frame(self)
        line.pack(anchor="w")
        self.not_var = tk.BooleanVar(value=bool(req.get("not")))
        ttk.Checkbutton(line, text="not", variable=self.not_var,
                        command=dialog.refresh).pack(side="left")
        self.target = lambda: "subject"
        if self.kind == "preset":
            p = REQUIREMENTS[req["preset"]]
            self.preset = p.id
            ttk.Label(line, text=p.label, width=26).pack(side="left",
                                                         padx=4)
            if p.arg:
                widget, self.value = dialog.value_widget(
                    line, p.kind, req.get("value") or "")
                widget.pack(side="left")
            else:
                self.value = lambda: ""
        else:
            self.columns = req.get("columns")
            self.type_combo = FilterCombo(line, dialog.data.requirement_types(),
                                          req.get("type") or "", width=46)
            self.type_combo.pack(side="left", padx=4)
            self.type_combo.bind("<<ComboboxSelected>>",
                                 lambda e: self._type_changed())
            self.type_combo.bind("<FocusOut>", lambda e: self._type_changed())
            self.type_combo.var.trace_add("write",
                                          lambda *_: dialog.refresh())
            if not rows.grouped:
                ttk.Label(line, text="of").pack(side="left")
                widget, self.target = _labelled_combo(
                    line, {t: TARGET_LABELS[t] for t in dialog.targets()},
                    req.get("target") or "subject", width=20,
                    command=dialog.refresh)
                widget.pack(side="left", padx=4)
        ttk.Button(line, text="Remove",
                   command=lambda: rows.remove(self)).pack(side="left",
                                                           padx=6)
        if self.kind != "preset":
            self.args = ArgsTable(self, dialog, req.get("args"))
            self.args.pack(anchor="w", padx=(28, 0))
            self._type_changed(prefill=False)

    def _type_changed(self, prefill=True):
        data = self.rows.dialog.data
        t = self.type_combo.value().upper()
        self.args.set_known(data.requirement_args(t))
        info = data.requirement_info(t)
        if prefill and info and not self.args.rows:
            for name, value in usual_args(info["args"],
                                          info["uses"]).items():
                self.args.add(name, value)

    def get(self):
        out = {"not": bool(self.not_var.get())}
        if self.kind == "preset":
            out.update(preset=self.preset, value=self.value())
            return out
        out.update(type=self.type_combo.value().upper(),
                   args=self.args.values(), target=self.target())
        if self.columns:
            out["columns"] = self.columns
        return out


class GroupBox(ttk.LabelFrame, _Rows):
    """A group of requirements (advanced): a set of its own, met by all
    or by any one of them."""

    def __init__(self, parent, rows, req):
        ttk.LabelFrame.__init__(self, parent, text="Group", padding=(8, 4))
        dialog = rows.dialog
        head = ttk.Frame(self)
        head.pack(anchor="w")
        self.not_var = tk.BooleanVar(value=bool(req.get("not")))
        ttk.Checkbutton(head, text="not", variable=self.not_var,
                        command=dialog.refresh).pack(side="left")
        widget, self.group = _labelled_combo(head, GROUP_LABELS,
                                             req.get("group") or "ANY",
                                             width=14,
                                             command=dialog.refresh)
        widget.pack(side="left", padx=4)
        ttk.Label(head, text="on").pack(side="left")
        widget, self.target = _labelled_combo(
            head, {t: TARGET_LABELS[t] for t in dialog.targets()},
            req.get("target") or "subject", width=20,
            command=dialog.refresh)
        widget.pack(side="left", padx=4)
        ttk.Button(head, text="Remove group",
                   command=lambda: rows.remove(self)).pack(side="left",
                                                           padx=6)
        self._init_rows(self, dialog, True, True)
        self.list.pack_configure(padx=(16, 0))
        self.build_add_bar(self).pack(anchor="w", pady=(4, 0),
                                      padx=(16, 0))
        self.set_presets(rows.presets)
        for inner in req.get("reqs") or []:
            self.add(inner)

    def get(self):
        return {"group": self.group(), "reqs": self.reqs(),
                "not": bool(self.not_var.get()), "target": self.target()}


class RequirementsFrame(ttk.LabelFrame, _Rows):
    """An effect's requirements ("only when ..."). Basic mode: the
    editor's conditions, all of which are needed. Advanced mode also: the
    game's requirement types, groups, and per set whether all or any one
    of its requirements are needed."""

    def __init__(self, parent, dialog, reqs, set_types, advanced):
        ttk.LabelFrame.__init__(
            self, parent, padding=(8, 4),
            text="Only when" if advanced else "Only when (all of these)")
        self._init_rows(self, dialog, advanced, False)
        self.build_add_bar(self).pack(anchor="w", pady=(4, 0))
        self.set_types = dict(set_types or {})
        self.set_vars = {}
        self.needs = ttk.Frame(self)
        if advanced:
            self.needs.pack(anchor="w", pady=(6, 0))
        for req in reqs or []:
            self.add(req)

    def set_targets(self, targets):
        """Offer an all / any choice for the sets of these targets."""
        if not self.advanced:
            return
        self.set_types.update(self._set_types())
        for widget in self.needs.winfo_children():
            widget.destroy()
        self.set_vars = {}
        ttk.Label(self.needs, text="Needed:").pack(side="left")
        for target in targets:
            widget, getter = _labelled_combo(
                self.needs, {"ALL": "all", "ANY": "any one"},
                self.set_types.get(target, "ALL"), width=8,
                command=self.dialog.refresh)
            widget.pack(side="left", padx=(8, 2))
            ttk.Label(self.needs, text="of those on " +
                      TARGET_LABELS[target]).pack(side="left")
            self.set_vars[target] = getter

    def _set_types(self):
        return {t: getter() for t, getter in self.set_vars.items()}

    def values(self):
        """(requirements, set_types) as edited (see the modifiers.py
        docstring)."""
        set_types = self._set_types() if self.advanced else self.set_types
        return self.reqs(), {t: v for t, v in set_types.items()
                             if v == "ANY"}
