"""Historic moment illustrations (Rise and Fall / Gathering Storm).

Mods cannot add new moments - their triggers are engine code - but the
engine's "first unique unit / building / district / improvement" moments
take their picture from MomentIllustrations, keyed by the item's type. A
civilization spec holds them in moment_illustrations: [{"item":
"UNIT_X", "path": image, "mask": bool (fade frame from
assets/mask_historical.png), "half": bool (50% transparent), "sepia":
bool (old-photo brown tint)}, ...]. (Older projects kept them on
leaders; see move_to_civs.)
"""

import os

# item type prefix -> (MomentIllustrationType, MomentDataType)
MOMENT_KINDS = {
    "UNIT_": ("MOMENT_ILLUSTRATION_UNIQUE_UNIT", "MOMENT_DATA_UNIT"),
    "BUILDING_": ("MOMENT_ILLUSTRATION_UNIQUE_BUILDING",
                  "MOMENT_DATA_BUILDING"),
    "DISTRICT_": ("MOMENT_ILLUSTRATION_UNIQUE_DISTRICT",
                  "MOMENT_DATA_DISTRICT"),
    "IMPROVEMENT_": ("MOMENT_ILLUSTRATION_UNIQUE_IMPROVEMENT",
                     "MOMENT_DATA_IMPROVEMENT"),
}
MOMENT_ILLUSTRATION_SIZE = (456, 332)     # size of Firaxis' own illustrations


def moment_kind(item):
    return next((kind for prefix, kind in MOMENT_KINDS.items()
                 if item.startswith(prefix)), None)


def normalize_moments(entries, owner, slug):
    """Validated moment contexts of a spec's moment_illustrations. owner:
    the spec's name (for messages); slug: its type (texture names).
    Raises ValueError."""
    moments = []
    for entry in entries or []:
        item = (entry.get("item") or "").strip().upper()
        path = (entry.get("path") or "").strip()
        if not item and not path:
            continue                    # empty editor row
        kind = moment_kind(item)
        if not kind:
            raise ValueError(
                "{}: historic moment item '{}' must be a unique UNIT_, "
                "BUILDING_, DISTRICT_ or IMPROVEMENT_ type.".format(owner,
                                                                    item))
        if not path or not os.path.isfile(path):
            raise ValueError("{}: historic moment image for {} not found: {}"
                             .format(owner, item, path or "(none)"))
        if any(m["item"] == item for m in moments):
            raise ValueError("{}: {} has two historic moment pictures - the "
                             "game allows one per item.".format(owner, item))
        moments.append({"item": item, "illustration": kind[0],
                        "data_type": kind[1], "path": path,
                        "texture": "MOMENT_{}_{}".format(slug, item),
                        "mask": bool(entry.get("mask")),
                        "half": bool(entry.get("half")),
                        "sepia": bool(entry.get("sepia"))})
    return moments


def move_to_civs(leaders, civs, civ_of):
    """Move the moment illustrations of leaders of the project's
    civilizations (older projects kept them on the leader) to the
    civilization. civ_of(leader spec) -> its civilization spec or None.
    Leaders of game civilizations keep theirs. Returns how many were
    moved."""
    moved = 0
    for spec in leaders:
        entries = spec.get("moment_illustrations") or []
        civ = civ_of(spec) if entries else None
        if civ is None:
            continue
        own = civ.setdefault("moment_illustrations", [])
        have = {(e.get("item") or "").strip().upper() for e in own}
        for entry in entries:
            item = (entry.get("item") or "").strip().upper()
            if item not in have:        # the civilization's own one wins
                own.append(dict(entry))
                have.add(item)
                moved += 1
        spec["moment_illustrations"] = []
    return moved
