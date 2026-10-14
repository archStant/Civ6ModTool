"""Editing an agenda of a leader's own (advanced mode, see agendas.py): its
likes and dislikes of other civilizations, and the dialog that edits one
of them."""

import copy

import tkinter as tk
from tkinter import messagebox, ttk

from ..agendas import (CONDITIONS, EVENT_CONDITIONS, MET_TURNS,
                       check_reaction, fade_turns, is_event, new_reaction,
                       reaction_summary)
from ..modifiers import arg_display, usual_args
from . import theme
from .effect_parts import ArgsTable
from .modifier_editor import value_widget
from .widgets import FilterCombo, ScrollFrame, fit_to_screen, parse_type

REACTION_HINT = (
    "A like (a positive change) or a dislike (a negative one) of other "
    "civilizations: when a major civilization this leader met at least {} "
    "turns ago meets all the conditions, the leader's opinion of it "
    "changes by that much - the diplomacy screen shows the text, and the "
    "AI gives the reason when it praises or warns you. With an event among "
    "the conditions (declaring war, denouncing a friend...), it changes "
    "when the event happens, and fades.".format(MET_TURNS))


def condition_choices(data):
    """Labels of the conditions to pick from: the game's agendas' ones by
    name, then every other requirement type of the game."""
    named = sorted("{} ({})".format(label, t)
                   for t, label in CONDITIONS.items())
    return named + [t for t in data.requirement_types()
                    if t not in CONDITIONS]


def condition_text(requirement_type):
    """A condition's combobox text."""
    if requirement_type in CONDITIONS:
        return "{} ({})".format(CONDITIONS[requirement_type],
                                requirement_type)
    return requirement_type


class ConditionRow(ttk.Frame):
    """One condition of a reaction: the game requirement type, 'not', its
    arguments, and how the game's agendas use it."""

    def __init__(self, parent, dialog, req):
        super().__init__(parent)
        self.dialog = dialog
        line = ttk.Frame(self)
        line.pack(anchor="w")
        self.not_var = tk.BooleanVar(value=bool(req.get("not")))
        ttk.Checkbutton(line, text="not", variable=self.not_var,
                        command=dialog.refresh).pack(side="left")
        self.combo = FilterCombo(line, dialog.conditions,
                                 condition_text(req.get("type") or ""),
                                 width=64)
        self.combo.pack(side="left", padx=4)
        self.combo.bind("<<ComboboxSelected>>", lambda e: self._changed())
        self.combo.bind("<FocusOut>", lambda e: self._changed())
        ttk.Button(line, text="Remove",
                   command=lambda: dialog.remove_condition(self)).pack(
            side="left", padx=6)
        self.args = ArgsTable(self, dialog, req.get("args"))
        self.args.pack(anchor="w", padx=(28, 0))
        self.example = ttk.Label(self, wraplength=600, justify="left",
                                 foreground=theme.hint())
        self.example.pack(anchor="w", padx=(28, 0))
        self._changed(prefill=False)

    def requirement_type(self):
        return parse_type(self.combo.value())

    def _changed(self, prefill=True):
        data, t = self.dialog.data, self.requirement_type()
        self.args.set_known(data.requirement_args(t))
        examples = data.agenda_examples().get(t) or []
        if prefill and not self.args.rows:
            if examples:
                start = examples[0]["args"]
            else:
                info = data.requirement_info(t) or {}
                start = usual_args(info.get("args") or [],
                                   info.get("uses") or 0)
            for name, value in start.items():
                self.args.add(name, value)
        text = ("An event: the opinion changes when it happens, then fades. "
                if t in EVENT_CONDITIONS else "")
        if examples:
            e = examples[0]
            args = ", ".join("{} {}".format(
                n, arg_display(n, v, self.dialog.name_of))
                for n, v in sorted(e["args"].items()))
            text += "In the game: {}{}{}{}{}".format(
                e["value"] if e["value"].startswith("-")
                else "+" + e["value"], " if not" if e["not"] else "",
                " with " + args if args else "",
                " - \"{}\"".format(e["text"]) if e["text"] else "",
                " (and {} more)".format(len(examples) - 1)
                if len(examples) > 1 else "")
        self.example.configure(text=text)
        self.dialog.refresh()

    def get(self):
        return {"type": self.requirement_type(), "args": self.args.values(),
                "not": bool(self.not_var.get()), "target": "subject"}


class ReactionDialog(tk.Toplevel):
    """Edit one like or dislike (see agendas.py). data: the GameData;
    choices(kind) / name_of(kind, type): game types for the arguments'
    dropdowns and summaries. The edited reaction is in .result after OK
    (None if cancelled)."""

    def __init__(self, parent, reaction, data, choices, name_of):
        super().__init__(parent)
        self.title("Like or dislike")
        self.resizable(False, False)
        self.transient(parent)
        self.data, self.choices, self.name_of = data, choices, name_of
        self.conditions = condition_choices(data)
        self.result = None
        self._ready = False
        self.base = copy.deepcopy(reaction)

        btns = ttk.Frame(self, padding=(10, 0, 10, 10))
        btns.pack(side="bottom", anchor="e")
        scroll = ScrollFrame(self, height=None)
        scroll.pack(fill="both", expand=True)
        body = scroll.inner
        pad = {"padx": 6, "pady": 3}
        ttk.Label(body, text=REACTION_HINT, wraplength=640, justify="left",
                  foreground=theme.hint()).grid(row=0, column=0,
                                                columnspan=2, sticky="w",
                                                pady=(0, 8))
        ttk.Label(body, text="Opinion change").grid(row=1, column=0,
                                                    sticky="w", **pad)
        value = ttk.Frame(body)
        value.grid(row=1, column=1, sticky="w", **pad)
        self.value_var = tk.StringVar(value=str(self.base.get("value", "")))
        self.value_var.trace_add("write", lambda *_: self.refresh())
        ttk.Entry(value, textvariable=self.value_var, width=6).pack(
            side="left")
        ttk.Label(value, foreground=theme.hint(), text=(
            "positive: likes, negative: dislikes (the game's agendas use "
            "-12 to +15)")).pack(side="left", padx=8)

        box = ttk.LabelFrame(body, padding=(8, 4), text=(
            "Only when the other civilization (all of these)"))
        box.grid(row=2, column=0, columnspan=2, sticky="we", pady=(8, 0))
        self.rows_frame = ttk.Frame(box)
        self.rows_frame.pack(anchor="w", fill="x")
        ttk.Button(box, text="Add condition",
                   command=lambda: self.add_condition(
                       {"type": "", "args": {}})).pack(anchor="w",
                                                       pady=(4, 0))
        self.rows = []
        # (only for an event, see agendas.EVENT_CONDITIONS)
        self.fade_frame = ttk.Frame(box)
        ttk.Label(self.fade_frame, text="An event: the opinion fades by 1 "
                                        "every").pack(side="left")
        self.fade_var = tk.StringVar(value=fade_turns(self.base))
        self.fade_var.trace_add("write", lambda *_: self.refresh())
        ttk.Entry(self.fade_frame, textvariable=self.fade_var,
                  width=5).pack(side="left", padx=4)
        ttk.Label(self.fade_frame, text="turns").pack(side="left")
        self._fade_shown = False

        ttk.Label(body, text="Diplomacy screen text").grid(
            row=3, column=0, sticky="w", **pad)
        self.text_var = tk.StringVar(value=self.base.get("text") or "")
        self.text_var.trace_add("write", lambda *_: self.refresh())
        ttk.Entry(body, textvariable=self.text_var, width=70).grid(
            row=3, column=1, sticky="w", **pad)
        ttk.Label(body, text="Reason in praise and\nwarnings (optional)",
                  justify="left").grid(row=4, column=0, sticky="w", **pad)
        self.reason_var = tk.StringVar(value=self.base.get("reason") or "")
        ttk.Entry(body, textvariable=self.reason_var, width=70).grid(
            row=4, column=1, sticky="w", **pad)
        ttk.Label(body, foreground=theme.hint(), wraplength=560,
                  justify="left", text=(
                      "e.g. text: \"Hippolyta admires your strong army\", "
                      "reason: \"(You keep a strong army.)\" - an empty "
                      "reason repeats the text.")).grid(
            row=5, column=1, sticky="w", padx=6)
        self.summary = ttk.Label(body, wraplength=640, justify="left",
                                 font=("TkDefaultFont", 9, "italic"))
        self.summary.grid(row=6, column=0, columnspan=2, sticky="w",
                          pady=(10, 0))
        ttk.Button(btns, text="OK", command=self.on_ok).pack(side="left",
                                                             padx=4)
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(
            side="left", padx=4)
        for req in self.base.get("reqs") or []:
            self.add_condition(req)
        self._ready = True
        self.refresh()
        fit_to_screen(self)
        self.grab_set()
        self.bind("<Escape>", lambda e: self.destroy())

    def value_widget(self, parent, kind, value, width=36):
        return value_widget(parent, kind, value, self.choices, self.refresh,
                            width)

    def add_condition(self, req):
        row = ConditionRow(self.rows_frame, self, req)
        row.pack(anchor="w", fill="x", pady=2)
        self.rows.append(row)
        self.refresh()

    def remove_condition(self, row):
        row.destroy()
        self.rows.remove(row)
        self.refresh()

    def reaction(self):
        out = copy.deepcopy(self.base)
        out.update(value=self.value_var.get().strip(),
                   reqs=[row.get() for row in self.rows],
                   text=self.text_var.get().strip(),
                   reason=self.reason_var.get().strip())
        if is_event(out):
            out["fade_turns"] = self.fade_var.get().strip()
        else:
            out.pop("fade_turns", None)
        return out

    def refresh(self):
        if not self._ready:
            return
        reaction = self.reaction()
        event = is_event(reaction)
        if event != self._fade_shown:
            if event:
                self.fade_frame.pack(anchor="w", pady=(6, 0))
            else:
                self.fade_frame.pack_forget()
            self._fade_shown = event
        self.summary.configure(text=reaction_summary(reaction, self.name_of))

    def on_ok(self):
        reaction = self.reaction()
        try:
            check_reaction(reaction, self.data)
        except ValueError as exc:
            messagebox.showwarning("Incomplete like or dislike", str(exc),
                                   parent=self)
            return
        self.result = reaction
        self.destroy()


class ReactionsFrame(ttk.Frame):
    """The likes and dislikes of an agenda of a leader's own, as a list
    with Add / Edit / Duplicate / Remove. editable False (basic mode):
    shown, not changed."""

    def __init__(self, parent, app, reactions, editable=True):
        super().__init__(parent)
        self.app, self.editable = app, editable
        self.items = copy.deepcopy(list(reactions or []))
        box = ttk.Frame(self)
        box.pack(side="left", fill="both", expand=True)
        self.listbox = tk.Listbox(box, height=7, width=90,
                                  activestyle="none")
        bar = ttk.Scrollbar(box, orient="vertical",
                            command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=bar.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        bar.pack(side="left", fill="y")
        self.listbox.bind("<Double-1>", lambda e: self.on_edit())
        btns = ttk.Frame(self)
        btns.pack(side="left", anchor="n", padx=(8, 0))
        for text, cmd in (("Add...", self.on_add), ("Edit...", self.on_edit),
                          ("Duplicate", self.on_duplicate),
                          ("Remove", self.on_remove)):
            ttk.Button(btns, text=text, command=cmd,
                       state="normal" if editable else "disabled").pack(
                fill="x", pady=2)
        self.refresh()

    def name_of(self, kind, type_name):
        return self.app.data.type_name(kind, type_name)

    def refresh(self):
        self.listbox.delete(0, "end")
        for reaction in self.items:
            self.listbox.insert("end", reaction_summary(reaction,
                                                        self.name_of))
        if not self.items:
            self.listbox.insert("end", "(no likes or dislikes yet - Add... "
                                       "to give it some)")

    def _selected(self):
        sel = self.listbox.curselection()
        return sel[0] if sel and self.items else None

    def _dialog(self, reaction):
        dialog = ReactionDialog(self.winfo_toplevel(), reaction,
                                self.app.data, self.app.data.type_choices,
                                self.name_of)
        self.wait_window(dialog)
        self.winfo_toplevel().grab_set()        # the dialog took the grab
        return dialog.result

    def on_add(self):
        result = self._dialog(new_reaction())
        if result:
            self.items.append(result)
            self.refresh()

    def on_edit(self):
        i = self._selected()
        if i is None or not self.editable:
            return
        result = self._dialog(self.items[i])
        if result:
            self.items[i] = result
            self.refresh()

    def on_duplicate(self):
        i = self._selected()
        if i is not None:
            self.items.insert(i + 1, copy.deepcopy(self.items[i]))
            self.refresh()

    def on_remove(self):
        i = self._selected()
        if i is not None:
            del self.items[i]
            self.refresh()

    def reactions(self):
        return copy.deepcopy(self.items)
