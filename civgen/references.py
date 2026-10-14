"""Keeping references to the project's own items up to date.

A project refers to its civilizations' unique items by their type in
several places: historic moment pictures (moment_illustrations[].item), a
building's district (stats PrereqDistrict), effect arguments (e.g. an
adjacency to the civilization's own district). A type is made of the
project's prefix and the item's name (UNIT_SZ_ASKARI), so changing the
prefix or renaming the item leaves those references pointing at a type the
mod does not make - and the game refuses a mod with such references.

- retarget(): replace types everywhere in specs (the GUI calls it when the
  prefix changes or a unique is renamed),
- repair(): before generating, point references that only differ from an
  own item's type in the prefix (UNIT_ASKARI, UNIT_XX_ASKARI) at its
  current type.
"""

import re

from .uniques import MAIN_TABLES
from .util import slug_for_name


def kind_word(kind):
    """UNIT / BUILDING / DISTRICT / IMPROVEMENT for a unique kind."""
    return MAIN_TABLES[kind][1][:-len("Type")].upper()


def own_types(specs, prefix):
    """[(current type, kind, name part)] of the uniques of civilization
    and leader specs: UNIT_SZ_ASKARI, "unit", "ASKARI"."""
    out = []
    for owner in specs:
        for u in owner.get("uniques") or []:
            kind = u.get("kind")
            if kind not in MAIN_TABLES or not (u.get("name") or "").strip():
                continue
            word = kind_word(kind)
            bare = slug_for_name(u["name"], "", kind=word)
            out.append((slug_for_name(u["name"], prefix, kind=word), kind,
                        bare[len(word) + 1:]))
    return out


def unique_type(spec, prefix):
    """The type of one unique spec (or "")."""
    if spec.get("kind") not in MAIN_TABLES:
        return ""
    return slug_for_name(spec.get("name"), prefix,
                         kind=kind_word(spec["kind"]))


def retarget(value, mapping):
    """Replace, in place, every string in value (dicts and lists, nested)
    that is a key of mapping by its value. Returns the number replaced.
    Only whole strings are replaced, so names and texts are left alone."""
    count = 0
    if isinstance(value, dict):
        items = value.items()
    elif isinstance(value, list):
        items = enumerate(value)
    else:
        return 0
    for key, item in list(items):
        if isinstance(item, str) and item in mapping:
            value[key] = mapping[item]
            count += 1
        elif isinstance(item, (dict, list)):
            count += retarget(item, mapping)
    # dict keys (e.g. yields keyed by type) too
    if isinstance(value, dict):
        for key in [k for k in value if isinstance(k, str) and k in mapping]:
            value[mapping[key]] = value.pop(key)
            count += 1
    return count


def prefix_change(civ_specs, old_prefix, new_prefix, leader_specs=()):
    """{type with the old prefix: type with the new} of the uniques (the
    civilizations' and the leaders' own)."""
    specs = list(civ_specs) + list(leader_specs)
    return {o: n for (o, _, _), (n, _, _) in zip(
        own_types(specs, old_prefix), own_types(specs, new_prefix))
        if o != n}


def _strings(value, out):
    if isinstance(value, str):
        out.add(value)
    elif isinstance(value, dict):
        for k, v in value.items():
            _strings(k, out)
            _strings(v, out)
    elif isinstance(value, list):
        for v in value:
            _strings(v, out)
    return out


def stale_references(leader_specs, civ_specs, prefix, is_game_type):
    """{stale type: current type}: strings in the specs that look like one
    of the uniques (the civilizations' and the leaders') under another
    (or no) prefix - UNIT_ASKARI or UNIT_XX_ASKARI for UNIT_SZ_ASKARI -
    and are not a type of the game (is_game_type(type))."""
    own = own_types(list(civ_specs) + list(leader_specs), prefix)
    current = {t for t, _, _ in own}
    found = _strings([leader_specs, civ_specs], set())
    mapping = {}
    for text in found:
        if text in current or not re.fullmatch(r"[A-Z0-9_]+", text):
            continue
        for new, kind, name in own:
            word = kind_word(kind)
            if not re.fullmatch(r"{}_(?:[A-Z0-9]+_)?{}".format(
                    re.escape(word), re.escape(name)), text):
                continue
            if is_game_type(text):
                break                   # a game item of that name
            mapping.setdefault(text, new)
            break
    return mapping


def repair(leader_specs, civ_specs, prefix, data):
    """Point stale references to the civilizations' own uniques at their
    current type, in place. Without the game cache, a bare type
    (UNIT_ASKARI) could be one of the game's, so only types with another
    prefix are fixed then. Returns [(stale, current)]."""
    def is_game_type(t):
        return bool(data.conn) and any(t in (data.items.get(k) or {})
                                       for k in MAIN_TABLES)
    mapping = stale_references(leader_specs, civ_specs, prefix,
                               is_game_type)
    if not data.conn:                   # bare forms may be the game's
        bare = {"{}_{}".format(kind_word(k), n)
                for _, k, n in own_types(list(civ_specs) +
                                         list(leader_specs), prefix)}
        mapping = {s: c for s, c in mapping.items() if s not in bare}
    if mapping:
        retarget(leader_specs, mapping)
        retarget(civ_specs, mapping)
    return sorted(mapping.items())
