"""The 3D model tabs of unique buildings and districts (see landmarks.py):
which of the game's meshes they show."""

import tkinter as tk
from tkinter import messagebox, ttk

from ..landmarks import (ERA_LABELS, ERAS, building_districts,
                         landmark_buildings, landmark_sets, merged_landmark,
                         new_building_art,
                         new_district_art, variant_key, variant_label)
from ..landmarks import _text as variant_text
from ..util import find_game_dir
from . import theme
from . import help_texts
from .widgets import HelpBox, ScrollFrame, TypeCombo, add_tooltip

KEEP = ""                               # mesh combobox: keep the game's


def mesh_of(text):
    """The mesh name of a mesh combobox text 'MESH (users)'."""
    return (text or "").split(" (")[0].strip()


def era_label(era):
    return "{} ({})".format(ERA_LABELS.get(era, era), era)


def era_of(text):
    return text.split("(")[-1].rstrip(")").strip() if "(" in text else text


class BuildingModelFrame(ttk.Frame):
    """The look of a unique building: another building's meshes, or meshes
    of its own per era, and the building whose place it takes in its
    district. base() gives the building it copies ("" = new), district()
    the district it is built in."""

    def __init__(self, parent, app, art, base, district=lambda: ""):
        super().__init__(parent)
        self.app, self.base, self.district = app, base, district
        art = dict(new_building_art(), **(art or {}))
        pad = {"padx": 6, "pady": 3}
        head = ttk.Frame(self)
        head.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        ttk.Label(head, wraplength=760, justify="left", text=(
            "How the building looks in its district: by default like the "
            "building it copies. It can instead look like any other "
            "building, or use meshes you pick (one per art era; 'any era' "
            "is used where no other era fits). Every mesh is one the game "
            "already has; the game shows the result only in game.")).pack(
            anchor="w", pady=(0, 2))
        HelpBox(head, help_texts.BUILDING_MODEL, wraplength=820).pack(
            anchor="w")
        ttk.Label(self, text="Looks like").grid(row=1, column=0, sticky="w",
                                                **pad)
        self.look_from = TypeCombo(self, app.data.unique_choices("building"),
                                   art.get("look_from", ""), width=44)
        self.look_from.grid(row=1, column=1, sticky="w", **pad)
        add_tooltip(self.look_from, "Any building: yours uses its meshes.")
        ttk.Label(self, text="(empty: the building it copies)",
                  foreground=theme.hint()).grid(row=1, column=2, sticky="w",
                                            **pad)
        self.info = ttk.Label(self, wraplength=640, justify="left",
                              foreground=theme.hint())
        self.info.grid(row=2, column=1, columnspan=2, sticky="w", **pad)
        label = ttk.Label(self, text="Drawn in the place of (?)")
        label.grid(row=3, column=0, sticky="w", **pad)
        add_tooltip(label, (
            "The building of its district whose spot it takes - only for a "
            "building that replaces nothing there (an extra building). "
            "Empty: the district's first building."))
        self.stand_in = TypeCombo(self, [], art.get("stand_in", ""),
                                  width=44)
        self.stand_in.grid(row=3, column=1, sticky="w", **pad)
        ttk.Label(self, text="(where it stands; if both are built they "
                             "overlap)", foreground=theme.hint()).grid(
            row=3, column=2, sticky="w", **pad)

        box = ttk.LabelFrame(self, text="Own meshes", padding=(8, 4))
        box.grid(row=4, column=0, columnspan=3, sticky="we", pady=(8, 0))
        self.own = tk.BooleanVar(value=art.get("meshes") is not None)
        ttk.Checkbutton(box, variable=self.own, text=(
            "Use these meshes (otherwise those of the building it looks "
            "like)")).grid(row=0, column=0, columnspan=3, sticky="w")
        self.box, self.rows = box, []
        for m in art.get("meshes") or []:
            self._add_row(m)
        ttk.Button(box, text="Add mesh", command=lambda: (
            self._add_row({"era": "DEFAULT", "mesh": ""}),
            self.own.set(True))).grid(row=99, column=0, sticky="w",
                                      pady=(6, 0))
        if not app.data.meshes["building"]:
            ttk.Label(self, foreground=theme.hint(), text=(
                "(load the game cache - with the game installed - to list "
                "the meshes)")).grid(row=5, column=0, columnspan=3,
                                     sticky="w", **pad)
        self.look_from.var.trace_add("write", lambda *_: self.refresh())
        self.stand_in.var.trace_add("write", lambda *_: self.refresh())
        self.refresh()

    def _add_row(self, mesh):
        r = 1 + len(self.rows)
        row = {"era": tk.StringVar(value=era_label(mesh.get("era",
                                                            "DEFAULT"))),
               "mesh": tk.StringVar(value=mesh.get("mesh", ""))}
        widgets = [
            ttk.Combobox(self.box, textvariable=row["era"], width=24,
                         state="readonly", values=[era_label(e)
                                                   for e in ERAS]),
            ttk.Combobox(self.box, textvariable=row["mesh"], width=56,
                         values=[label for _, label in
                                 self.app.data.meshes["building"]]),
            ttk.Button(self.box, text="Remove",
                       command=lambda: self._remove_row(row))]
        for col, widget in enumerate(widgets):
            widget.grid(row=r, column=col, sticky="w", padx=4, pady=2)
        row["widgets"] = widgets
        self.rows.append(row)

    def _remove_row(self, row):
        for widget in row["widgets"]:
            widget.destroy()
        self.rows.remove(row)

    def refresh(self):
        game_dir = find_game_dir()
        district = self.district()
        landmark = merged_landmark(game_dir, district) if district else None
        drawn = landmark_buildings(landmark) if landmark else []
        stand_in = self.stand_in.get_type()
        self.stand_in.set_choices(
            [(b, self.app.data.type_name("building", b)) for b in drawn] or
            self.app.data.unique_choices("building"))
        self.stand_in.set_type(stand_in)
        look = self.look_from.get_type() or self.base() or stand_in or \
            (drawn[0] if drawn else "")
        if not look:
            text = ("(pick the building it copies on the General tab, or "
                    "its district on the Stats tab)")
        else:
            districts = building_districts(game_dir, look)
            meshes = []
            for district in districts[:1]:
                landmark = merged_landmark(game_dir, district) or {}
                meshes = sorted({"{} ({})".format(
                    variant_text(v, "Asset"),
                    ERA_LABELS.get(variant_text(v, "Tag_Era"), "?"))
                    for v in landmark.get("buildings", [])
                    if variant_text(v, "Tag_HeroBuilding") == look})
            text = ("{}: drawn in {}; meshes {}".format(
                self.app.data.type_name("building", look),
                ", ".join(self.app.data.type_name("district", d)
                          for d in districts),
                ", ".join(meshes)) if districts else
                "{} has no 3D model in a district (e.g. a wonder or a "
                "building drawn by the city center).".format(look))
        self.info.configure(text=text)

    def art(self):
        meshes = None
        if self.own.get():
            meshes = [{"era": era_of(r["era"].get()),
                       "mesh": mesh_of(r["mesh"].get())}
                      for r in self.rows if mesh_of(r["mesh"].get())]
        return {"look_from": self.look_from.get_type(), "meshes": meshes,
                "stand_in": self.stand_in.get_type()}


class DistrictModelFrame(ttk.Frame):
    """The look of a unique district: the district it is laid out like,
    other ground / layout meshes and other meshes for the buildings in it.
    base() gives the district it copies ("" = new)."""

    def __init__(self, parent, app, art, base, district=None):
        super().__init__(parent)
        self.app, self.base = app, base
        art = dict(new_district_art(), **(art or {}))
        self.ground = dict(art.get("ground") or {})
        self.buildings = dict(art.get("buildings") or {})
        head = ttk.Frame(self)
        head.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))
        ttk.Label(head, wraplength=760, justify="left", text=(
            "How the district looks: its ground and layout (one mesh for "
            "each combination of buildings, era and culture the game "
            "draws) and the meshes of the buildings in it. Empty fields "
            "keep the copied district's mesh. Every mesh is one the game "
            "already has - from any district - and the game shows the "
            "result only in game.")).pack(anchor="w", pady=(0, 2))
        HelpBox(head, help_texts.DISTRICT_MODEL, wraplength=820).pack(
            anchor="w")
        look = ttk.Frame(self)
        look.grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 6))
        label = ttk.Label(look, text="Looks like (?)")
        label.pack(side="left")
        add_tooltip(label, (
            "The district whose layout (landmark) it starts from: its "
            "ground, building spots and meshes. Empty: the district it "
            "copies. A new district needs one."))
        self.look_from = TypeCombo(look, app.data.type_choices("district"),
                                   art.get("look_from", ""), width=36)
        self.look_from.pack(side="left", padx=6)
        ttk.Label(look, text="(empty: the district it copies)",
                  foreground=theme.hint()).pack(side="left")
        self.look_from.var.trace_add("write", lambda *_: self.refresh())
        helper = ttk.Frame(self)
        helper.grid(row=2, column=0, columnspan=3, sticky="w", pady=(0, 6))
        ttk.Label(helper, text="Fill the ground from district").pack(
            side="left")
        self.fill_from = TypeCombo(helper, app.data.type_choices("district"),
                                   width=36)
        self.fill_from.pack(side="left", padx=6)
        add_tooltip(self.fill_from, "Fills every ground row with this "
                    "district's ground for the same era and number of "
                    "buildings.")
        ttk.Button(helper, text="Fill", command=self.fill).pack(side="left")
        ttk.Button(helper, text="Clear all", command=self.clear).pack(
            side="left", padx=(12, 0))
        self.scroll = ScrollFrame(self, height=380)
        self.scroll.grid(row=3, column=0, columnspan=3, sticky="nsew")
        self.loaded_base = None
        self.refresh()

    def _store(self):
        for key, var in getattr(self, "ground_vars", {}).items():
            self.ground[key] = mesh_of(var.get())
        for key, var in getattr(self, "building_vars", {}).items():
            self.buildings[key] = mesh_of(var.get())

    def source(self):
        """The district whose landmark it starts from."""
        return self.look_from.get_type() or self.base()

    def refresh(self):
        """Rebuild the tables for the district it looks like (when that
        changes)."""
        base = self.source()
        if base == self.loaded_base:
            return
        self._store()
        self.loaded_base = base
        inner = self.scroll.inner
        for widget in inner.winfo_children():
            widget.destroy()
        self.ground_vars, self.building_vars = {}, {}
        landmark = merged_landmark(find_game_dir(), base) if base else None
        if landmark is None:
            ttk.Label(inner, foreground=theme.hint(), text=(
                "(pick the district it copies on the General tab, or the "
                "district it looks like above - the game must be "
                "installed)" if not base else
                "{} has no landmark in the game's art.".format(base))).grid(
                row=0, column=0, sticky="w")
            return
        data = self.app.data
        ground_values = [KEEP] + [l for _, l in data.meshes["ground"]]
        building_values = [KEEP] + [l for _, l in data.meshes["building"]]
        sets = landmark_sets(landmark)
        r = 0
        ttk.Label(inner, text="Buildings", font=("TkDefaultFont", 9,
                                                 "bold")).grid(
            row=r, column=0, sticky="w", pady=(0, 2))
        r += 1
        seen = []
        for v in landmark["buildings"]:
            b = variant_text(v, "Tag_HeroBuilding")
            if b in seen:
                continue
            seen.append(b)
            meshes = sorted({variant_text(x, "Asset")
                             for x in landmark["buildings"]
                             if variant_text(x, "Tag_HeroBuilding") == b})
            ttk.Label(inner, text=data.type_name("building", b)).grid(
                row=r, column=0, sticky="w", padx=(0, 8))
            var = tk.StringVar(value=self.buildings.get(b, ""))
            ttk.Combobox(inner, textvariable=var, width=56,
                         values=building_values).grid(row=r, column=1,
                                                      sticky="w", pady=1)
            ttk.Label(inner, text="now: " + ", ".join(meshes),
                      foreground=theme.hint()).grid(row=r, column=2,
                                                sticky="w", padx=6)
            self.building_vars[b] = var
            r += 1
        ttk.Label(inner, text="Ground and layout", font=(
            "TkDefaultFont", 9, "bold")).grid(row=r, column=0, sticky="w",
                                               pady=(10, 2))
        r += 1
        for v in landmark["base"]:
            key = variant_key(v)
            if key in self.ground_vars:
                continue
            ttk.Label(inner, text=variant_label(key, sets)).grid(
                row=r, column=0, sticky="w", padx=(0, 8))
            var = tk.StringVar(value=self.ground.get(key, ""))
            ttk.Combobox(inner, textvariable=var, width=56,
                         values=ground_values).grid(row=r, column=1,
                                                    sticky="w", pady=1)
            ttk.Label(inner, text="now: " + variant_text(v, "Asset"),
                      foreground=theme.hint()).grid(row=r, column=2,
                                                sticky="w", padx=6)
            self.ground_vars[key] = var
            r += 1

    def fill(self):
        """Ground meshes from another district: for each ground variant,
        that district's mesh for the same era with as many buildings."""
        source = self.fill_from.get_type()
        landmark = merged_landmark(find_game_dir(), source) if source \
            else None
        if not landmark:
            messagebox.showinfo("No district", "Pick a district (with the "
                                "game installed) to take the ground from.",
                                parent=self)
            return
        sets = landmark_sets(landmark)
        by_size = {}
        for v in landmark["base"]:
            set_name, era = variant_text(v, "Set_HeroBuildings"), \
                variant_text(v, "Tag_Era")
            by_size.setdefault((era, len(sets.get(set_name, []))),
                               variant_text(v, "Asset"))
        own_sets = landmark_sets(merged_landmark(find_game_dir(),
                                                 self.loaded_base))
        filled = 0
        for key, var in self.ground_vars.items():
            set_name, era = key.split("|")[:2]
            size = len(own_sets.get(set_name, []))
            mesh = by_size.get((era, size)) or by_size.get(("DEFAULT", size))
            if mesh:
                var.set(mesh)
                filled += 1
        messagebox.showinfo("Ground filled", "Took {} ground mesh(es) from "
                            "{}.".format(filled, source), parent=self)

    def clear(self):
        for var in list(self.ground_vars.values()) + \
                list(self.building_vars.values()):
            var.set("")

    def art(self):
        """The art spec: what the tables show (or, without them - no game
        to read the district from - what the spec had)."""
        look = self.look_from.get_type()
        if not self.ground_vars and not self.building_vars:
            return {"look_from": look, "ground": dict(self.ground),
                    "buildings": dict(self.buildings)}
        return {"look_from": look,
                "ground": {k: mesh_of(v.get())
                           for k, v in self.ground_vars.items()
                           if mesh_of(v.get())},
                "buildings": {k: mesh_of(v.get())
                              for k, v in self.building_vars.items()
                              if mesh_of(v.get())}}


class ImprovementModelFrame(ttk.Frame):
    """The look of a unique improvement: the improvement it looks like.
    base() gives the improvement it copies ("" = new)."""

    def __init__(self, parent, app, art, base, district=None):
        super().__init__(parent)
        self.app, self.base = app, base
        ttk.Label(self, wraplength=760, justify="left", text=(
            "How the improvement looks on the map: the 3D model of one of "
            "the game's improvements.")).grid(row=0, column=0, columnspan=3,
                                               sticky="w", pady=(0, 2))
        HelpBox(self, help_texts.IMPROVEMENT_MODEL, wraplength=820).grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(0, 6))
        label = ttk.Label(self, text="Looks like (?)")
        label.grid(row=2, column=0, sticky="w")
        add_tooltip(label, "The improvement whose 3D model it shows. "
                    "Empty: the improvement it copies. A new improvement "
                    "needs one.")
        self.look_from = TypeCombo(
            self, app.data.type_choices("improvement"),
            (art or {}).get("look_from", ""), width=40)
        self.look_from.grid(row=2, column=1, sticky="w", padx=6)
        self.info = ttk.Label(self, foreground=theme.hint())
        self.info.grid(row=2, column=2, sticky="w")
        self.look_from.var.trace_add("write", lambda *_: self.refresh())
        self.refresh()

    def refresh(self):
        look, base = self.look_from.get_type(), self.base()
        if look:
            text = ""
        elif base:
            text = "(empty: looks like {})".format(
                self.app.data.type_name("improvement", base))
        else:
            text = "(a new improvement: pick one)"
        self.info.configure(text=text)

    def art(self):
        return {"look_from": self.look_from.get_type()}
