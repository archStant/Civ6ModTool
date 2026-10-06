"""The Placement tab of unique districts: where they can be built."""

import tkinter as tk
from tkinter import ttk

from ..uniques import IMPROVEMENT_PLACEMENT_DEFAULTS, PLACEMENT_DEFAULTS
from ..util import type_display_name
from .widgets import HelpBox, ScrollFrame, add_tooltip

# used when no game cache is loaded
TERRAINS = ["TERRAIN_GRASS", "TERRAIN_GRASS_HILLS", "TERRAIN_PLAINS",
            "TERRAIN_PLAINS_HILLS", "TERRAIN_DESERT", "TERRAIN_DESERT_HILLS",
            "TERRAIN_TUNDRA", "TERRAIN_TUNDRA_HILLS", "TERRAIN_SNOW",
            "TERRAIN_SNOW_HILLS", "TERRAIN_COAST", "TERRAIN_OCEAN"]
FEATURES = ["FEATURE_FOREST", "FEATURE_JUNGLE", "FEATURE_MARSH",
            "FEATURE_OASIS", "FEATURE_FLOODPLAINS",
            "FEATURE_FLOODPLAINS_GRASSLAND", "FEATURE_FLOODPLAINS_PLAINS",
            "FEATURE_REEF", "FEATURE_ICE", "FEATURE_GEOTHERMAL_FISSURE",
            "FEATURE_VOLCANIC_SOIL"]

HELP = """
The game checks these rules when a player picks a tile for the district. Whatever you choose, districts can never be built on mountains, natural wonders, or tiles with a wonder, and must be within the city's 3 tiles.

Land or water: most districts are built on land. A water district (like the Harbor) is built on a coast or lake tile next to land instead.

Terrains: tick terrains to allow only those - e.g. only the hills, like the Acropolis. Nothing ticked: any terrain (of land, or water) the game allows.

Features: tick features if the tile must have one of them - e.g. woods or rainforest, like the Mbanza, or floodplains, like the Dam. Building on a feature usually removes it (woods, rainforest, marsh), except floodplains. Nothing ticked: no feature needed.

Not next to the city center: it cannot be built on a tile touching the city center. One per city: a city can have only one. At most per civilization: a limit for the whole civilization (like the Government Plaza's 1); -1 means no limit.
"""


def _name(app, kind, type_name):
    name = app.data.type_name(kind, type_name) if app.data.conn else ""
    return name or type_display_name(type_name)


class PlacementFrame(ttk.Frame):
    """Edit a district's placement spec (see uniques.PLACEMENT_DEFAULTS).
    base() gives the district it copies ("" = new): its rules are shown,
    and used unless "own rules" is ticked."""

    def __init__(self, parent, app, placement, base):
        super().__init__(parent)
        self.app, self.base = app, base
        pad = {"padx": 6, "pady": 3}
        ttk.Label(self, wraplength=760, justify="left", text=(
            "Where the district can be built: on land or water, on which "
            "terrains, whether the tile needs a feature, and how many there "
            "can be.")).grid(row=0, column=0, columnspan=2, sticky="w")
        HelpBox(self, HELP, wraplength=820).grid(row=1, column=0,
                                                 columnspan=2, sticky="w",
                                                 pady=(0, 6))
        self.own = tk.BooleanVar(value=placement is not None)
        self.own_check = ttk.Checkbutton(
            self, variable=self.own, command=self._own_toggled,
            text="Own placement rules (otherwise the copied district's)")
        self.own_check.grid(row=2, column=0, columnspan=2, sticky="w", **pad)
        self.info = ttk.Label(self, foreground="gray25", wraplength=760,
                              justify="left")
        self.info.grid(row=3, column=0, columnspan=2, sticky="w", **pad)

        self.water = tk.BooleanVar()
        where = ttk.Frame(self)
        where.grid(row=4, column=0, columnspan=2, sticky="w", **pad)
        ttk.Label(where, text="Built").pack(side="left")
        ttk.Radiobutton(where, text="on land", variable=self.water,
                        value=False).pack(side="left", padx=(8, 0))
        ttk.Radiobutton(where, text="on water (coast or lake, next to land)",
                        variable=self.water, value=True).pack(side="left",
                                                              padx=(8, 0))

        terrains = [t for t, _ in app.data.type_choices("terrain")
                    if "MOUNTAIN" not in t] or TERRAINS
        # (burning woods are temporary; volcanoes are mountains)
        features = [f for f, _ in app.data.type_choices("plain_feature")
                    if not any(w in f for w in ("BURNING", "BURNT",
                                                "VOLCANO"))] or FEATURES
        self.terrain_vars = self._checks(
            6, "Only on these terrains (none ticked: any)", "terrain",
            terrains, 4, "Tick terrains to allow only those.")
        self.feature_vars = self._checks(
            7, "Needs one of these features (none ticked: no feature "
               "needed)", "plain_feature", features, 4,
            "The tile must have one of the ticked features.")

        limits = ttk.Frame(self)
        limits.grid(row=8, column=0, columnspan=2, sticky="w", **pad)
        self.no_adjacent_city = tk.BooleanVar()
        self.one_per_city = tk.BooleanVar(value=True)
        self.max_per_player = tk.StringVar(value="-1")
        ttk.Checkbutton(limits, text="Not next to the city center",
                        variable=self.no_adjacent_city).pack(side="left")
        ttk.Checkbutton(limits, text="One per city",
                        variable=self.one_per_city).pack(side="left",
                                                         padx=(16, 0))
        label = ttk.Label(limits, text="At most per civilization (?)")
        label.pack(side="left", padx=(16, 4))
        add_tooltip(label, "-1: no limit; 1: one in the whole "
                           "civilization (like the Government Plaza).")
        ttk.Spinbox(limits, from_=-1, to=99, width=5,
                    textvariable=self.max_per_player).pack(side="left")
        self.inputs = [where, limits] + [
            w for vars_ in (self.terrain_vars, self.feature_vars)
            for w in vars_["widgets"]]
        self._set(placement or self._copied() or PLACEMENT_DEFAULTS)
        self.refresh()

    def _checks(self, row, title, kind, types, columns, tip):
        box = ttk.LabelFrame(self, text=title, padding=(8, 4))
        box.grid(row=row, column=0, columnspan=2, sticky="we", padx=6,
                 pady=(6, 0))
        out = {"vars": {}, "widgets": []}
        for i, t in enumerate(types):
            var = tk.BooleanVar()
            check = ttk.Checkbutton(box, text=_name(self.app, kind, t),
                                    variable=var)
            check.grid(row=i // columns, column=i % columns, sticky="w",
                       padx=(0, 18), pady=1)
            add_tooltip(check, "{} - {}".format(t, tip))
            out["vars"][t] = var
            out["widgets"].append(check)
        return out

    def _copied(self):
        base = self.base()
        return self.app.data.district_placement(base) if base else None

    def _set(self, p):
        p = dict(PLACEMENT_DEFAULTS, **(p or {}))
        self.water.set(bool(p["water"]))
        for vars_, key in ((self.terrain_vars, "terrains"),
                           (self.feature_vars, "features")):
            for t, var in vars_["vars"].items():
                var.set(t in p[key])
        self.no_adjacent_city.set(bool(p["no_adjacent_city"]))
        self.one_per_city.set(bool(p["one_per_city"]))
        self.max_per_player.set(str(p["max_per_player"]))

    def _own_toggled(self):
        if not self.own.get():          # back to the copied rules
            self._set(self._copied() or PLACEMENT_DEFAULTS)
        self.refresh()

    def refresh(self):
        """Follow the copied district: new districts always have their own
        rules; copies show the copied rules until "own" is ticked."""
        base = self.base()
        if not base:
            self.own.set(True)
            self.own_check.state(["disabled"])
            self.info.configure(text="A new district: these are its rules.")
        else:
            self.own_check.state(["!disabled"])
            copied = self._copied()
            self.info.configure(text=(
                "{}: {}".format(_name(self.app, "district", base),
                                self.describe(copied)) if copied else
                "(load the game cache to see the copied district's rules)"))
            if not self.own.get():
                self._set(copied or PLACEMENT_DEFAULTS)
        state = ["!disabled"] if self.own.get() else ["disabled"]
        for widget in self._all_inputs():
            try:
                widget.state(state)
            except (AttributeError, tk.TclError):
                pass

    def _all_inputs(self):
        for w in self.inputs:
            yield w
            yield from w.winfo_children()

    def describe(self, p):
        p = dict(PLACEMENT_DEFAULTS, **p)
        parts = ["on water" if p["water"] else "on land"]
        if p["terrains"]:
            parts.append("only on " + ", ".join(
                _name(self.app, "terrain", t) for t in p["terrains"]))
        if p["features"]:
            parts.append("needs " + " or ".join(
                _name(self.app, "plain_feature", f) for f in p["features"]))
        if p["no_adjacent_city"]:
            parts.append("not next to the city center")
        if not p["one_per_city"]:
            parts.append("several per city")
        if p["max_per_player"] != -1:
            parts.append("at most {} per civilization".format(
                p["max_per_player"]))
        return "; ".join(parts)

    def placement(self):
        """The placement spec, or None (the copied district's rules)."""
        if not self.own.get():
            return None
        return {"water": bool(self.water.get()),
                "terrains": [t for t, v in self.terrain_vars["vars"].items()
                             if v.get()],
                "features": [f for f, v in self.feature_vars["vars"].items()
                             if v.get()],
                "no_adjacent_city": bool(self.no_adjacent_city.get()),
                "one_per_city": bool(self.one_per_city.get()),
                "max_per_player": self.max_per_player.get().strip()}


IMPROVEMENT_HELP = """
Builders of the civilization can build the improvement on a tile in its borders (unless "also outside the borders" is ticked) whose terrain, feature or resource is ticked here.

Terrains: the terrains it may be built on. Ticking only Coast (and/or Ocean) makes it a water improvement, like the Kampung.

Features: features it may be built on - e.g. woods or rainforest. On a tile with a feature that is not ticked, the feature has to be removed first. Building on a ticked feature keeps it.

Resources: resources it may be built on (the improvement then also works the resource, like a Mine or Plantation would). Nothing ticked: none.

Next to a river: only on tiles next to a river. Not next to another: two of them may not be next to each other (like the Pairidaeza). One per city: a city can have only one.
"""


class ImprovementPlacementFrame(PlacementFrame):
    """Edit an improvement's placement spec (see
    uniques.IMPROVEMENT_PLACEMENT_DEFAULTS). base() gives the improvement
    it copies ("" = new)."""

    def __init__(self, parent, app, placement, base):
        ttk.Frame.__init__(self, parent)
        self.app, self.base = app, base
        pad = {"padx": 6, "pady": 3}
        ttk.Label(self, wraplength=760, justify="left", text=(
            "Where Builders can build the improvement: on which terrains, "
            "features and resources, and other rules.")).grid(
            row=0, column=0, columnspan=2, sticky="w")
        HelpBox(self, IMPROVEMENT_HELP, wraplength=820).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(0, 6))
        self.own = tk.BooleanVar(value=placement is not None)
        self.own_check = ttk.Checkbutton(
            self, variable=self.own, command=self._own_toggled,
            text="Own placement rules (otherwise the copied improvement's)")
        self.own_check.grid(row=2, column=0, columnspan=2, sticky="w", **pad)
        self.info = ttk.Label(self, foreground="gray25", wraplength=760,
                              justify="left")
        self.info.grid(row=3, column=0, columnspan=2, sticky="w", **pad)
        terrains = [t for t, _ in app.data.type_choices("terrain")
                    if "MOUNTAIN" not in t] or TERRAINS
        features = [f for f, _ in app.data.type_choices("plain_feature")
                    if not any(w in f for w in ("BURNING", "BURNT",
                                                "VOLCANO"))] or FEATURES
        resources = [r for r, _ in app.data.type_choices("resource")]
        self.terrain_vars = self._checks(
            4, "Terrains it may be built on", "terrain", terrains, 4,
            "Tick the terrains it may be built on.")
        self.feature_vars = self._checks(
            5, "Features it may be built on", "plain_feature", features, 4,
            "It may be built on this feature (others must be removed "
            "first).")
        self.resource_vars = self._resource_box(6, resources)
        rules = ttk.Frame(self)
        rules.grid(row=7, column=0, columnspan=2, sticky="w", **pad)
        self.flags = {}
        for key, text in (("river", "Next to a river"),
                          ("no_same_adjacent", "Not next to another"),
                          ("one_per_city", "One per city"),
                          ("outside_territory",
                           "Also outside the borders")):
            var = tk.BooleanVar()
            ttk.Checkbutton(rules, text=text, variable=var).pack(
                side="left", padx=(0, 16))
            self.flags[key] = var
        self.inputs = [rules] + [
            w for vars_ in (self.terrain_vars, self.feature_vars,
                            self.resource_vars)
            for w in vars_["widgets"]]
        self._set(placement or self._copied() or
                  IMPROVEMENT_PLACEMENT_DEFAULTS)
        self.refresh()

    def _resource_box(self, row, resources):
        """The resource checks, in a scrolling box (there are many)."""
        box = ttk.LabelFrame(self, text="Resources it may be built on "
                             "(none ticked: none)", padding=(8, 4))
        box.grid(row=row, column=0, columnspan=2, sticky="we", padx=6,
                 pady=(6, 0))
        scroll = ScrollFrame(box, height=120)
        scroll.pack(fill="both", expand=True)
        out = {"vars": {}, "widgets": []}
        for i, r in enumerate(resources):
            var = tk.BooleanVar()
            check = ttk.Checkbutton(scroll.inner,
                                    text=_name(self.app, "resource", r),
                                    variable=var)
            check.grid(row=i // 5, column=i % 5, sticky="w", padx=(0, 18),
                       pady=1)
            add_tooltip(check, r)
            out["vars"][r] = var
            out["widgets"].append(check)
        return out

    def _copied(self):
        base = self.base()
        return self.app.data.improvement_placement(base) if base else None

    def _set(self, p):
        p = dict(IMPROVEMENT_PLACEMENT_DEFAULTS, **(p or {}))
        for vars_, key in ((self.terrain_vars, "terrains"),
                           (self.feature_vars, "features"),
                           (self.resource_vars, "resources")):
            for t, var in vars_["vars"].items():
                var.set(t in p[key])
        for key, var in self.flags.items():
            var.set(bool(p[key]))

    def _own_toggled(self):
        if not self.own.get():
            self._set(self._copied() or IMPROVEMENT_PLACEMENT_DEFAULTS)
        self.refresh()

    def refresh(self):
        base = self.base()
        if not base:
            self.own.set(True)
            self.own_check.state(["disabled"])
            self.info.configure(text="A new improvement: these are its "
                                     "rules.")
        else:
            self.own_check.state(["!disabled"])
            copied = self._copied()
            self.info.configure(text=(
                "{}: {}".format(_name(self.app, "improvement", base),
                                self.describe(copied)) if copied else
                "(load the game cache to see the copied improvement's "
                "rules)"))
            if not self.own.get():
                self._set(copied or IMPROVEMENT_PLACEMENT_DEFAULTS)
        state = ["!disabled"] if self.own.get() else ["disabled"]
        for widget in self._all_inputs():
            try:
                widget.state(state)
            except (AttributeError, tk.TclError):
                pass

    def describe(self, p):
        p = dict(IMPROVEMENT_PLACEMENT_DEFAULTS, **p)
        parts = []
        for key, kind, word in (("terrains", "terrain", "on"),
                                ("features", "plain_feature", "on"),
                                ("resources", "resource", "on")):
            if p[key]:
                parts.append("{} {}".format(word, ", ".join(
                    _name(self.app, kind, t) for t in p[key])))
        for key, text in (("river", "next to a river"),
                          ("no_same_adjacent", "not next to another"),
                          ("one_per_city", "one per city"),
                          ("outside_territory", "also outside the borders")):
            if p[key]:
                parts.append(text)
        return "; ".join(parts) or "nowhere"

    def placement(self):
        if not self.own.get():
            return None
        out = {key: [t for t, v in vars_["vars"].items() if v.get()]
               for key, vars_ in (("terrains", self.terrain_vars),
                                  ("features", self.feature_vars),
                                  ("resources", self.resource_vars))}
        out.update({key: bool(var.get()) for key, var in self.flags.items()})
        return out
