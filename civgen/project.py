"""Project files and leader / civilization export and import."""

import json
import os
import zipfile


PROJECT_MAGIC = "civ6-alt-leader-generator-project"
PROJECT_VERSION = 3              # 2: icon crops are in fitted-portrait pixels
                                 # 3: projects have civilizations ("civs")


# ---------------------------------------------------------------------------
# Leader export / import (move leaders between projects or machines)
# ---------------------------------------------------------------------------

# An export is a zip: leaders.json (the leader and civilization specs, as
# JSON rather than a pickle so importing one is safe) plus a copy of every
# image they use.
LEADERS_MAGIC = "civ6-alt-leader-generator-leaders"
LEADERS_ENTRY = "leaders.json"
IMAGE_KEYS = ("icon_path", "load_fg_path", "load_bg_path", "diplo_bg_path")
TUPLE_KEYS = ("primary", "secondary", "icon_border_color", "icon_crop")


def _spec_images(spec):
    """(holder, key) of every image path a leader or civilization spec
    refers to."""
    if "uniques" in spec:               # a civilization
        refs = [(spec, "icon_path")] + [(u, key) for u in spec["uniques"]
                                        for key in ("icon_path",
                                                    "portrait_path")]
    else:
        refs = [(spec, key) for key in IMAGE_KEYS]
    refs += [(entry, "path") for entry in spec.get("moment_illustrations")
             or []]
    return refs


def export_leaders(specs, path, civs=()):
    """Write leader (and civilization) specs and their images to the zip
    at path. Returns the image paths that were not found (exported as
    bare paths)."""
    images = {}                         # original path -> name in the zip
    missing = []
    civs = list(civs)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for spec in list(specs) + civs:
            for holder, key in _spec_images(spec):
                src = (holder.get(key) or "").strip()
                if not src or src in images:
                    continue
                if not os.path.isfile(src):
                    if src not in missing:
                        missing.append(src)
                    continue
                images[src] = "images/{}_{}".format(len(images) + 1,
                                                    os.path.basename(src))
                zf.write(src, images[src])
        zf.writestr(LEADERS_ENTRY, json.dumps({
            "magic": LEADERS_MAGIC, "version": PROJECT_VERSION,
            "leaders": specs, "civs": civs, "images": images}, indent=2,
            ensure_ascii=False))
    return missing


def import_leaders(path):
    """Read an export_leaders zip. Returns (leader specs, civilization
    specs, version). An image that
    is still at its original path is used from there; the others are
    unpacked into '<export name> images' next to the zip. Raises
    ValueError if the file is not a leader export."""
    try:
        zf = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValueError("This is not a leader export ({}).".format(exc))
    with zf:
        try:
            data = json.loads(zf.read(LEADERS_ENTRY).decode("utf-8"))
        except (KeyError, ValueError):
            raise ValueError("This is not a leader export (no readable {})."
                             .format(LEADERS_ENTRY))
        if (not isinstance(data, dict)
                or data.get("magic") != LEADERS_MAGIC
                or not isinstance(data.get("leaders"), list)
                or not isinstance(data.get("images", {}), dict)
                or not isinstance(data.get("civs", []), list)):
            raise ValueError("This is not a leader export.")
        specs = data["leaders"]
        civs = data.get("civs", [])
        for civ in civs:
            if (not isinstance(civ, dict) or "name" not in civ
                    or not isinstance(civ.get("uniques", []), list)
                    or not all(isinstance(u, dict)
                               for u in civ.get("uniques", []))
                    or not all(isinstance(entry, dict) for entry in
                               civ.get("moment_illustrations") or [])):
                raise ValueError("The export contains a malformed "
                                 "civilization entry.")
            civ.setdefault("uniques", [])
        for spec in specs:
            if (not isinstance(spec, dict) or "name" not in spec
                    or not all(isinstance(entry, dict) for entry in
                               spec.get("moment_illustrations") or [])):
                raise ValueError("The export contains a malformed leader "
                                 "entry.")
        images = data.get("images", {})
        image_dir = os.path.splitext(path)[0] + " images"
        unpacked = {}                   # original path -> unpacked copy
        for spec in specs + civs:
            for key in TUPLE_KEYS:      # JSON turned the tuples into lists
                if isinstance(spec.get(key), list):
                    spec[key] = tuple(spec[key])
            for holder, key in _spec_images(spec):
                src = holder.get(key)
                if (not isinstance(src, str) or not src.strip()
                        or os.path.isfile(src)):
                    continue
                if src not in unpacked:
                    name = images.get(src)
                    # only the file name: never write outside image_dir
                    base = os.path.basename(name) if isinstance(name, str) \
                        else ""
                    if not base or name not in zf.namelist():
                        continue        # not bundled: keep the bare path
                    os.makedirs(image_dir, exist_ok=True)
                    dst = os.path.join(image_dir, base)
                    with open(dst, "wb") as fh:
                        fh.write(zf.read(name))
                    unpacked[src] = dst
                holder[key] = unpacked[src]
    return specs, civs, data.get("version", 1)
