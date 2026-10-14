"""Project files and leader / civilization export and import."""

import json
import os
import zipfile


PROJECT_MAGIC = "civ6-mod-generator-project"
PROJECT_VERSION = 4              # 2: icon crops are in fitted-portrait pixels
                                 # 3: projects have civilizations ("civs")
                                 # 4: saved as JSON (*.civmod)
PROJECT_EXT = ".civmod"
# projects before version 4: Python pickles (*.altleader)
LEGACY_EXT = ".altleader"
LEGACY_MAGIC = "civ6-alt-leader-generator-project"


# ---------------------------------------------------------------------------
# Project files
# ---------------------------------------------------------------------------

def json_ready(value):
    """value as JSON keeps it (tuples become lists): for comparing a
    project with what was saved."""
    return json.loads(json.dumps(value, ensure_ascii=False))


def save_project(project, path):
    """Write project (a dict of the GUI's state: mod_name, prefix,
    output_dir, guid, leaders, civs, workshop, extra_files, ...) to path
    as JSON.
    Written to a temporary file first, so a failed save never leaves a
    broken project behind. Raises OSError (or TypeError for a value JSON
    cannot hold)."""
    payload = dict(project, magic=PROJECT_MAGIC, version=PROJECT_VERSION)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    os.replace(tmp, path)


def load_project(path):
    """Read a project file: a *.civmod (JSON) or an older *.altleader
    (pickle). Returns (project dict, version it was saved with); the
    caller migrates older versions. Raises ValueError with a message for
    the user."""
    with open(path, "rb") as fh:
        raw = fh.read()
    if raw.lstrip()[:1] == b"{":
        try:
            project = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise ValueError("The project file is damaged ({}).".format(exc))
        magic = PROJECT_MAGIC
    else:
        # an older project: a pickle. Pickles can run code when loaded,
        # so only *.altleader files are read this way.
        if not path.lower().endswith(LEGACY_EXT):
            raise ValueError("This is not a project file.")
        import pickle
        try:
            project = pickle.loads(raw)
        except Exception as exc:        # anything a bad pickle raises
            raise ValueError("Could not read the old project ({}).".format(
                exc))
        magic = LEGACY_MAGIC
    if (not isinstance(project, dict) or project.get("magic") != magic
            or not isinstance(project.get("leaders"), list)):
        raise ValueError("This does not look like a project file.")
    if not all(isinstance(s, dict) and "name" in s
               for s in project["leaders"]):
        raise ValueError("The project contains a malformed leader entry.")
    project.setdefault("civs", [])      # projects before version 3
    if not isinstance(project["civs"], list) or not all(
            isinstance(c, dict) and "name" in c for c in project["civs"]):
        raise ValueError("The project contains a malformed civilization "
                         "entry.")
    # files of the user's own added to the mod (see
    # modbuild.check_extra_files)
    project.setdefault("extra_files", [])
    if not isinstance(project["extra_files"], list) or not all(
            isinstance(f, dict) and isinstance(f.get("path"), str)
            for f in project["extra_files"]):
        raise ValueError("The project contains a malformed custom file "
                         "entry.")
    for spec in project["leaders"]:     # JSON turned the tuples into lists
        for key in TUPLE_KEYS:
            if isinstance(spec.get(key), list):
                spec[key] = tuple(spec[key])
    version = project.pop("version", 1)
    project.pop("magic", None)
    return project, version


def project_path_for(path):
    """Where a project read from path is saved: an older *.altleader
    becomes a *.civmod next to it."""
    root, ext = os.path.splitext(path)
    return root + PROJECT_EXT if ext.lower() != PROJECT_EXT else path


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
        moods = spec.get("mood_images")
        if isinstance(moods, dict):     # diplomacy portraits by mood
            refs += [(moods, slot) for slot in sorted(moods)]
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
