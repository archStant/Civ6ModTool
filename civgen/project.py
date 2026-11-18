"""Project files and leader / civilization export and import."""

import json
import os
import zipfile

from .util import safe_folder_name


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
    text = _project_text(project)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    os.replace(tmp, path)


def _project_text(project):
    """The JSON a project file holds."""
    payload = dict(project, magic=PROJECT_MAGIC, version=PROJECT_VERSION)
    return json.dumps(payload, ensure_ascii=False, indent=2)


def load_project(path):
    """Read a project file: a *.civmod (JSON) or an older *.altleader
    (pickle). Returns (project dict, version it was saved with); the
    caller migrates older versions. File paths relative to the project
    file (a package's, see package_project) are made absolute. Raises
    ValueError with a message for the user."""
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
    project.setdefault("religions", [])     # projects before religions
    if not isinstance(project["religions"], list) or not all(
            isinstance(r, dict) and "name" in r
            for r in project["religions"]):
        raise ValueError("The project contains a malformed religion entry.")
    # files of the user's own added to the mod (see
    # modbuild.check_extra_files)
    project.setdefault("extra_files", [])
    if not isinstance(project["extra_files"], list) or not all(
            isinstance(f, dict) and isinstance(f.get("path"), str)
            for f in project["extra_files"]):
        raise ValueError("The project contains a malformed custom file "
                         "entry.")
    # JSON turned the tuples into lists
    for spec in project["leaders"] + project["religions"]:
        for key in TUPLE_KEYS:
            if isinstance(spec.get(key), list):
                spec[key] = tuple(spec[key])
    folder = os.path.dirname(os.path.abspath(path))
    for holder, key, _ in _project_files(project):
        src = holder.get(key)
        if (isinstance(src, str) and src.strip()
                and not os.path.isabs(src.strip())):
            holder[key] = os.path.normpath(os.path.join(folder, src.strip()))
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
IMAGE_KEYS = ("icon_path", "load_fg_path", "load_bg_path", "diplo_bg_path",
              "diplo_fg_path")
TUPLE_KEYS = ("primary", "secondary", "icon_border_color", "icon_crop",
              "color")
# a leader's images (IMAGE_KEYS) -> their file name in a package
IMAGE_NAMES = {"icon_path": "icon", "load_fg_path": "portrait",
               "load_bg_path": "loading_background",
               "diplo_bg_path": "diplomacy_background",
               "diplo_fg_path": "diplomacy_foreground"}


def _named_images(spec):
    """(holder, key, name) of every image path a leader, civilization or
    religion spec refers to (their uniques' too); name: the image's path
    in a package below the spec's folder, without the extension."""
    if "orig" in spec:                  # a leader
        refs = [(spec, key, IMAGE_NAMES[key]) for key in IMAGE_KEYS]
        moods = spec.get("mood_images")
        if isinstance(moods, dict):     # diplomacy portraits by mood
            refs += [(moods, slot, "mood_" + str(slot).lower())
                     for slot in sorted(moods)]
    else:
        refs = [(spec, "icon_path", "icon")]
    for n, u in enumerate(spec.get("uniques") or [], 1):
        if isinstance(u, dict):
            folder = "uniques/" + safe_folder_name(
                str(u.get("name") or ""), "unique_{}".format(n))
            refs += [(u, "icon_path", folder + "/icon"),
                     (u, "portrait_path", folder + "/portrait")]
    for n, entry in enumerate(spec.get("moment_illustrations") or [], 1):
        if isinstance(entry, dict):
            refs.append((entry, "path", "moments/" + safe_folder_name(
                str(entry.get("item") or ""), "moment_{}".format(n))))
    if isinstance(spec.get("moment"), dict):    # a religion's picture
        refs.append((spec["moment"], "path", "moment"))
    return refs


def _spec_images(spec):
    """(holder, key) of every image path a leader, civilization or
    religion spec refers to (their uniques' too)."""
    return [(holder, key) for holder, key, _ in _named_images(spec)]


def export_leaders(specs, path, civs=(), religions=()):
    """Write leader (and civilization and religion) specs and their
    images to the zip at path. Returns the image paths that were not
    found (exported as bare paths)."""
    images = {}                         # original path -> name in the zip
    missing = []
    civs = list(civs)
    religions = list(religions)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for spec in list(specs) + civs + religions:
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
            "leaders": specs, "civs": civs, "religions": religions,
            "images": images}, indent=2,
            ensure_ascii=False))
    return missing


def import_leaders(path):
    """Read an export_leaders zip. Returns (leader specs, civilization
    specs, version, religion specs). An image that
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
                or not isinstance(data.get("civs", []), list)
                or not isinstance(data.get("religions", []), list)):
            raise ValueError("This is not a leader export.")
        specs = data["leaders"]
        civs = data.get("civs", [])
        religions = data.get("religions", [])
        if not all(isinstance(r, dict) and "name" in r for r in religions):
            raise ValueError("The export contains a malformed religion "
                             "entry.")
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
                    or not isinstance(spec.get("uniques", []), list)
                    or not all(isinstance(u, dict)
                               for u in spec.get("uniques", []))
                    or not all(isinstance(entry, dict) for entry in
                               spec.get("moment_illustrations") or [])):
                raise ValueError("The export contains a malformed leader "
                                 "entry.")
        images = data.get("images", {})
        image_dir = os.path.splitext(path)[0] + " images"
        unpacked = {}                   # original path -> unpacked copy
        for spec in specs + civs + religions:
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
    return specs, civs, data.get("version", 1), religions


# ---------------------------------------------------------------------------
# Project packages (a project with every file it uses, to back it up or
# move it to another machine)
# ---------------------------------------------------------------------------

# A package is a zip: the project (<zip name>.civmod) and a copy of every
# image and custom file it uses next to it, in images/leaders/<leader>/,
# images/civilizations/<civilization>/, images/religions/<religion>/,
# images/workshop/ and
# custom_files/. The project names them by paths relative to itself, which
# load_project makes absolute again, so the unpacked folder opens anywhere.
IMAGES_DIR = "images"
CUSTOM_FILES_DIR = "custom_files"


def _project_files(project):
    """(holder, key, name) of every file path a project refers to: the
    images of its leaders, civilizations and religions, the Workshop
    preview and the
    custom files. name: the file's path in a package, without the
    extension (None for a custom file, which keeps its own name - the mod
    uses it)."""
    refs = []
    for group, specs in (("leaders", project.get("leaders")),
                         ("civilizations", project.get("civs")),
                         ("religions", project.get("religions"))):
        used = set()                    # the folders of this group
        for n, spec in enumerate(specs or [], 1):
            if not isinstance(spec, dict):
                continue
            base = safe_folder_name(str(spec.get("name") or ""), "{}_{}"
                                    .format(group[:-1], n))
            folder, i = base, 1
            while folder.lower() in used:   # two of the same name
                i += 1
                folder = "{}_{}".format(base, i)
            used.add(folder.lower())
            refs += [(holder, key, "/".join((IMAGES_DIR, group, folder,
                                             name)))
                     for holder, key, name in _named_images(spec)]
    workshop = project.get("workshop")
    if isinstance(workshop, dict):
        refs.append((workshop, "preview_path",
                     IMAGES_DIR + "/workshop/preview"))
    refs += [(entry, "path", None) for entry in
             project.get("extra_files") or [] if isinstance(entry, dict)]
    return refs


def _package_name(name, src, used):
    """The path in a package of the file src: name plus src's extension
    (CUSTOM_FILES_DIR/src's own name for name None), numbered if another
    file has it. used: the (lowercased) paths taken, updated."""
    n = 1
    while True:
        if name is None:                # in a numbered folder: same name
            parts = [CUSTOM_FILES_DIR] + ([str(n)] if n > 1 else [])
            path = "/".join(parts + [os.path.basename(src)])
        else:
            path = name + ("_{}".format(n) if n > 1 else "") + \
                os.path.splitext(src)[1]
        if path.lower() not in used:
            used.add(path.lower())
            return path
        n += 1


def package_project(project, path):
    """Write project and a copy of every file it uses to the zip at path
    (see IMAGES_DIR). The project in it is named after the zip and is a
    copy: project itself is not changed. Returns the paths that were not
    found (kept as they are)."""
    project = json_ready(project)
    packed = {}                         # file -> its path in the zip
    used = set()
    missing = []
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for holder, key, name in _project_files(project):
            src = holder.get(key)
            if not isinstance(src, str) or not src.strip():
                continue
            src = src.strip()
            file = os.path.normcase(os.path.abspath(src))
            if file not in packed:
                if not os.path.isfile(src):
                    if src not in missing:
                        missing.append(src)
                    continue
                packed[file] = _package_name(name, src, used)
                zf.write(src, packed[file])
            holder[key] = packed[file]
        stem = os.path.splitext(os.path.basename(path))[0]
        zf.writestr(stem + PROJECT_EXT, _project_text(project))
    return missing
