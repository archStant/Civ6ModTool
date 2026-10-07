"""Publishing a generated mod with the Civ VI SDK's Steam Workshop
uploader (ModUploader/Firaxis.SteamWorkshop.exe).

The uploader is a wizard without a command line: it reads the mod's
.modinfo (id - a GUID -, version, Name, Description, Files) and asks for a
title (<= 128 characters), a description (<= 8000), a preview image
(.jpg / .png under 1 MB) and visibility, then uploads the folder.
It refuses mods with missing files, archives or executables. The mod id is
stored on the Workshop item: the same GUID updates the same item.

This module prepares all of that - the project's Workshop settings, a
generated description and preview image, the uploader's own checks - so
the GUI can launch the uploader and show what to fill in.

A project's Workshop settings (project["workshop"], see
new_workshop_spec): title ("" = the mod name), description ("" =
generated), visibility, version (the .modinfo's),
author, preview_path ("" = made from the project), preview_style (how
"Make from project" draws it, see PREVIEW_STYLES), change_notes,
published_id (the item's id or URL, once uploaded).
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET

from .util import steam_libraries

UPLOADER_EXE = "Firaxis.SteamWorkshop.exe"
# the uploader's limits
MAX_TITLE = 128
MAX_DESCRIPTION = 8000
MAX_PREVIEW_BYTES = 1024 * 1024
PREVIEW_SIZE = 512
VISIBILITIES = ["Public", "Friends Only", "Private"]
# files the uploader refuses
FORBIDDEN = (".zip", ".7z", ".rar", ".gz", ".tar", ".exe", ".dll", ".bat",
             ".cmd", ".com", ".msi", ".ps1")
# a hash of what the mod was generated from (see build_stamp)
STAMP_FILE = ".civgen_build"
WORKSHOP_URL = "https://steamcommunity.com/sharedfiles/filedetails/?id={}"


def new_workshop_spec():
    return {"title": "", "description": "",
            "visibility": "Public", "version": 1, "author": "",
            "preview_path": "", "preview_style": "simple",
            "change_notes": "", "published_id": ""}


def normalize_workshop(spec):
    """spec with every key (older projects have none or some)."""
    out = new_workshop_spec()
    out.update({k: v for k, v in (spec or {}).items() if k in out})
    try:
        out["version"] = max(1, int(out["version"]))
    except (TypeError, ValueError):
        out["version"] = 1
    if out["visibility"] not in VISIBILITIES:
        out["visibility"] = "Public"
    if out["preview_style"] not in dict(PREVIEW_STYLES):
        out["preview_style"] = "simple"
    return out


# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------

def strip_game_markup(text):
    """Game text -> plain text: icon tags ([ICON_Faith]) dropped,
    [NEWLINE] as a line break."""
    text = (text or "").replace("[NEWLINE]", "\n")
    text = re.sub(r"\[ICON_[A-Za-z0-9_]+\]\s*", "", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def plain_text(bbcode):
    """Steam BBCode -> plain text (for the .modinfo's Description)."""
    text = re.sub(r"\[\*\]", "- ", bbcode or "")
    text = re.sub(r"\[/?[a-z0-9]+(=[^\]]*)?\]", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def generated_description(mod_name, civ_specs, leader_specs,
                          civ_name=lambda spec: spec.get("civ", "")):
    """A Workshop description in Steam BBCode, from the project's specs.
    civ_name(leader spec): the name of the leader's civilization."""
    out = ["[h1]{}[/h1]".format(mod_name)]
    what = []
    if civ_specs:
        what.append("{} new civilization{}".format(
            len(civ_specs), "" if len(civ_specs) == 1 else "s"))
    if leader_specs:
        what.append("{} leader{}".format(
            len(leader_specs), "" if len(leader_specs) == 1 else "s"))
    out.append("Adds {}.".format(" and ".join(what) or "content"))
    for civ in civ_specs:
        out.append("")
        out.append("[h2]{}[/h2]".format(civ.get("name", "")))
        if (civ.get("description") or "").strip():
            out.append(civ["description"].strip())
        ability = civ.get("ability") or {}
        if (ability.get("name") or "").strip():
            out.append("[b]{}[/b]: {}".format(
                ability["name"].strip(),
                strip_game_markup(ability.get("desc"))).rstrip(": "))
        uniques = [u for u in civ.get("uniques") or []
                   if (u.get("name") or "").strip()]
        if uniques:
            out.append("[list]")
            for u in uniques:
                desc = strip_game_markup(u.get("desc"))
                out.append("[*][b]{}[/b] (unique {}){}".format(
                    u["name"].strip(), u.get("kind", ""),
                    ": " + desc if desc else ""))
            out.append("[/list]")
    if leader_specs:
        out.append("")
        out.append("[h2]Leaders[/h2]")
        out.append("[list]")
        for spec in leader_specs:
            line = "[*][b]{}[/b] - {}".format(spec.get("name", ""),
                                              civ_name(spec))
            ability = spec.get("new_ability") or {}
            if (ability.get("name") or "").strip():
                desc = strip_game_markup(ability.get("desc"))
                line += ": {}{}".format(ability["name"].strip(),
                                        " - " + desc if desc else "")
            out.append(line)
        out.append("[/list]")
    out.append("")
    out.append("Works with the base game, Rise and Fall and Gathering "
               "Storm.")
    out.append("[i]Made with Civ 6 Mod Generator.[/i]")
    text = "\n".join(out)
    if len(text) > MAX_DESCRIPTION:
        text = text[:MAX_DESCRIPTION - 3].rstrip() + "..."
    return text


def resolved(workshop, mod_name, civ_specs, leader_specs,
             civ_name=lambda spec: spec.get("civ", "")):
    """The values to upload: the settings, with the empty ones filled in
    (title: the mod name; description: generated)."""
    w = normalize_workshop(workshop)
    return dict(
        w, title=(w["title"].strip() or mod_name)[:MAX_TITLE],
        description=w["description"].strip() or generated_description(
            mod_name, civ_specs, leader_specs, civ_name))


# ---------------------------------------------------------------------------
# Preview image
# ---------------------------------------------------------------------------

PREVIEW_STYLES = [("simple", "Simple"), ("busy", "Busy")]


def make_preview(path, title, civ_specs, leader_specs, style="simple"):
    """A PREVIEW_SIZE square JPEG under MAX_PREVIEW_BYTES, with the title
    on a banner. style "simple": the first civilization's icon (on a badge
    in its first leader's color), else the first leader's portrait. "busy":
    a collage of the mod's own images (see _busy_preview; simple when the
    project has none). Returns path. Raises ImportError without Pillow."""
    img = None
    if style == "busy":
        img = _busy_preview(title, civ_specs, leader_specs)
    if img is None:
        img = _simple_preview(title, civ_specs, leader_specs)
    rgb = img.convert("RGB")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    for quality in (92, 85, 75, 60, 45):
        rgb.save(path, "JPEG", quality=quality, optimize=True)
        if os.path.getsize(path) < MAX_PREVIEW_BYTES:
            break
    return path


def _leader_color(leader_specs):
    return tuple((leader_specs[0].get("primary") if leader_specs else None)
                 or (60, 90, 150))


def _gradient(size):
    """A dark backdrop with a soft vertical gradient."""
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (size, size), (28, 30, 36, 255))
    draw = ImageDraw.Draw(img)
    for y in range(size):
        shade = int(28 + 30 * y / size)
        draw.line([(0, y), (size, y)], fill=(shade, shade + 4, shade + 14))
    return img


def _simple_preview(title, civ_specs, leader_specs):
    from PIL import Image
    from .art import fitted_portrait
    from .civs import civ_icon_preview
    size = PREVIEW_SIZE
    img = _gradient(size)
    picture = None
    color = _leader_color(leader_specs)
    for civ in civ_specs:
        if (civ.get("icon_path") or "").strip():
            picture = civ_icon_preview(civ, int(size * 0.62), badge=color)
            break
    if picture is None:
        for spec in leader_specs:
            src = (spec.get("load_fg_path") or "").strip()
            if src and os.path.isfile(src):
                picture = fitted_portrait(src).copy()
                picture.thumbnail((int(size * 0.78), int(size * 0.78)),
                                  Image.LANCZOS)
                break
    if picture is None and civ_specs:
        picture = civ_icon_preview(civ_specs[0], int(size * 0.62))
    if picture is not None:
        img.alpha_composite(picture.convert("RGBA"),
                            ((size - picture.width) // 2,
                             int(size * 0.40) - picture.height // 2))
    _banner(img, title)
    return img


def _files(*paths):
    return [p for p in paths if p and os.path.isfile(p)]


def _background(leader_specs):
    """(image path, hue) of the collage background: a leader's loading
    background (its own, or the default with its hue), else a diplomacy
    background, else the default loading background."""
    from .art import DEFAULT_LOAD_BG
    from .util import asset_path
    default = asset_path(DEFAULT_LOAD_BG)
    for spec in leader_specs:
        hue = int(spec.get("load_bg_hue") or 0)
        own = (spec.get("load_bg_path") or "").strip()
        if _files(own):
            return own, hue
        if spec.get("load_bg_default") and default:
            return default, hue
    for spec in leader_specs:
        if _files((spec.get("diplo_bg_path") or "").strip()):
            return spec["diplo_bg_path"].strip(), 0
    return default, 0


def _badge(img, size, ring):
    """img fitted into a round badge of size px with a ring of color."""
    from PIL import Image, ImageDraw, ImageOps
    ss = 4
    big = size * ss
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, big - 1, big - 1), fill=255)
    mask = mask.resize((size, size), Image.LANCZOS)
    face = ImageOps.fit(img.convert("RGBA"), (size, size), Image.LANCZOS)
    back = Image.new("RGBA", (size, size), (20, 22, 28, 255))
    back.alpha_composite(face)
    back.putalpha(mask)
    out = Image.new("RGBA", (size + 6, size + 6), (0, 0, 0, 0))
    ring_img = Image.new("RGBA", (big + 6 * ss, big + 6 * ss), (0, 0, 0, 0))
    ImageDraw.Draw(ring_img).ellipse(
        (0, 0, big + 6 * ss - 1, big + 6 * ss - 1), fill=tuple(ring) + (255,))
    out.alpha_composite(ring_img.resize(out.size, Image.LANCZOS))
    out.alpha_composite(back, (3, 3))
    return out


def _card(entry, width, angle):
    """A historic moment picture, tilted: edited like the mod's (fade
    mask, 50% transparent, sepia - see moments.py). An opaque picture gets
    a white frame, like a photo; one with transparency is shown as it is,
    so what is behind it shows through."""
    from PIL import Image
    from .art import (MOMENT_HALF_OPACITY, MOMENT_MASK, apply_image_mask)
    from .moments import MOMENT_ILLUSTRATION_SIZE
    from .util import asset_path
    w, h = MOMENT_ILLUSTRATION_SIZE
    height = int(width * h / w)
    mask = asset_path(MOMENT_MASK) if entry.get("mask") else None
    pic = apply_image_mask(entry["path"], mask, size=(width, height),
                           opacity=MOMENT_HALF_OPACITY if entry.get("half")
                           else 1.0, sepia=bool(entry.get("sepia")))
    if pic.getchannel("A").getextrema()[0] < 250:      # see-through
        return pic.rotate(angle, resample=Image.BICUBIC, expand=True)
    border = max(3, width // 30)
    card = Image.new("RGBA", (width + 2 * border, height + 2 * border),
                     (238, 232, 218, 255))
    card.alpha_composite(pic, (border, border))
    return card.rotate(angle, resample=Image.BICUBIC, expand=True)


def _shadow(img, offset=6, blur=8):
    """A soft drop shadow under img's opaque parts: (shadow, (dx, dy))."""
    from PIL import Image, ImageFilter
    alpha = img.getchannel("A").point(lambda a: a * 0.7)
    shadow = Image.new("RGBA", (img.width + 4 * blur, img.height + 4 * blur),
                       (0, 0, 0, 0))
    black = Image.new("RGBA", img.size, (0, 0, 0, 255))
    black.putalpha(alpha)
    shadow.alpha_composite(black, (2 * blur, 2 * blur))
    shadow = shadow.filter(ImageFilter.GaussianBlur(blur))
    return shadow, (offset - 2 * blur, offset - 2 * blur)


def _composite(canvas, img, x, y):
    """img onto canvas at (x, y), clipped to the canvas (which
    alpha_composite does not do for negative positions)."""
    sx, sy = max(0, -x), max(0, -y)
    w = min(img.width - sx, canvas.width - max(0, x))
    h = min(img.height - sy, canvas.height - max(0, y))
    if w > 0 and h > 0:
        canvas.alpha_composite(img.crop((sx, sy, sx + w, sy + h)),
                               (max(0, x), max(0, y)))


def _paste(canvas, img, x, y, shadow=True):
    """img onto canvas at (x, y), with a soft drop shadow."""
    if shadow:
        s, (dx, dy) = _shadow(img)
        _composite(canvas, s, x + dx, y + dy)
    _composite(canvas, img, x, y)


def _busy_preview(title, civ_specs, leader_specs):
    """A collage of the mod's own images, or None if it has none:
    - the background: a leader's loading background (darkened)
    - the leaders' loading portraits, side by side (up to 3)
    - historic moment pictures as tilted cards (up to 2)
    - the civilization's icon on a badge, top left
    - the uniques' icons / portraits in a row of badges (up to 6)
    - the title on a banner, with what the mod adds."""
    from PIL import Image, ImageEnhance, ImageOps
    from .art import fitted_portrait, shift_hue
    from .civs import civ_icon_preview
    size = PREVIEW_SIZE
    banner = int(size * 0.2)
    color = _leader_color(leader_specs)
    portraits = [fitted_portrait(p) for p in _files(*[
        (s.get("load_fg_path") or "").strip() for s in leader_specs])][:3]
    moments = [m for m in [m for c in civ_specs
                           for m in c.get("moment_illustrations") or []] +
               [m for s in leader_specs
                for m in s.get("moment_illustrations") or []]
               if _files((m.get("path") or "").strip())][:2]
    civ_icons = [c for c in civ_specs if _files(
        (c.get("icon_path") or "").strip())][:2]
    unique_pics = _files(*[
        (u.get("portrait_path") or u.get("icon_path") or "").strip()
        for c in civ_specs for u in c.get("uniques") or []])[:6]
    bg_path, hue = _background(leader_specs)
    if not (portraits or moments or civ_icons or unique_pics or
            any((s.get("load_bg_path") or "").strip() for s in leader_specs)):
        return None                     # nothing of the mod's own to show

    # background: cover the square, darken, fade into the banner
    img = _gradient(size)
    if bg_path:
        # over the backdrop: a background with transparency would turn
        # black in the JPEG
        bg = ImageOps.fit(Image.open(bg_path).convert("RGBA"),
                          (size, size), Image.LANCZOS)
        if hue:
            bg = shift_hue(bg, hue)
        img.alpha_composite(ImageEnhance.Brightness(bg).enhance(0.55))
    fade = Image.new("L", (1, size))
    for y in range(size):
        fade.putpixel((0, y), int(200 * max(0, (y - size * 0.45) /
                                            (size * 0.55))))
    dark = Image.new("RGBA", (size, size), (0, 0, 0, 255))
    dark.putalpha(fade.resize((size, size)))
    img.alpha_composite(dark)

    # moments: tilted cards behind the leaders, left and right
    for i, entry in enumerate(moments):
        card = _card(dict(entry, path=entry["path"].strip()),
                     int(size * 0.36), 8 if i == 0 else -7)
        x = int(size * 0.03) if i == 0 else size - card.width - \
            int(size * 0.03)
        _paste(img, card, x, int(size * 0.26))

    # leaders: standing on the banner, the first in front and centre
    if portraits:
        height = int(size * (0.72 if len(portraits) == 1 else 0.62))
        fitted = []
        for p in portraits:
            p = p.copy()
            p.thumbnail((size, height), Image.LANCZOS)
            fitted.append(p)
        spots = {1: [0.5], 2: [0.33, 0.67], 3: [0.5, 0.2, 0.8]}[len(fitted)]
        # back ones first, smaller
        order = sorted(range(len(fitted)), key=lambda i: -i)
        for i in order:
            p = fitted[i]
            if i:
                p = p.resize((int(p.width * 0.86), int(p.height * 0.86)),
                             Image.LANCZOS)
            x = int(size * spots[i] - p.width / 2)
            _paste(img, p, x, size - banner - p.height + int(size * 0.02))

    # the civilization's icon, top left (a second one next to it)
    x = int(size * 0.03)
    for civ in civ_icons:
        badge = civ_icon_preview(civ, int(size * 0.2), badge=color)
        _paste(img, badge, x, int(size * 0.03))
        x += badge.width + int(size * 0.02)

    # the uniques: a row of small badges, top right
    if unique_pics:
        small = int(size * 0.105)
        gap = int(size * 0.012)
        x = size - int(size * 0.03) - len(unique_pics) * (small + 6 + gap)
        for path in unique_pics:
            badge = _badge(Image.open(path), small, color)
            _paste(img, badge, x, int(size * 0.04))
            x += badge.width + gap

    adds = []
    if civ_specs:
        adds.append("{} civilization{}".format(
            len(civ_specs), "" if len(civ_specs) == 1 else "s"))
    if leader_specs:
        adds.append("{} leader{}".format(
            len(leader_specs), "" if len(leader_specs) == 1 else "s"))
    uniques = sum(len(c.get("uniques") or []) for c in civ_specs)
    if uniques:
        adds.append("{} unique{}".format(uniques, "" if uniques == 1
                                         else "s"))
    _banner(img, title, " · ".join(adds), color)
    return img


CREDIT = "Made with Civ 6 Mod Generator"


def _banner(img, title, subtitle="", accent=None):
    """The title (and a subtitle) on a dark banner along the bottom, with
    a small CREDIT in its bottom right corner; a thin accent line in the
    leader's color on top of it."""
    from PIL import ImageDraw
    size = img.width
    banner = int(size * 0.2)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, size - banner, size, size], fill=(0, 0, 0, 255))
    if accent:
        draw.rectangle([0, size - banner, size, size - banner + 3],
                       fill=tuple(accent) + (255,))
    font = _font(int(banner * (0.36 if subtitle else 0.42)))
    text = title if len(title) <= 34 else title[:32] + "..."
    lines = [(text, font, (240, 236, 226, 255))]
    if subtitle:
        lines.append((subtitle, _font(int(banner * 0.2)),
                      (190, 186, 176, 255)))
    sizes = [_text_size(draw, t, f) for t, f, _ in lines]
    total = sum(h for _, h, _, _ in sizes) + (int(banner * 0.06)
                                              if subtitle else 0)
    # the credit: a strip of its own along the bottom edge
    credit_font = _font(max(9, int(banner * 0.12)))
    cw, ch, cleft, ctop = _text_size(draw, CREDIT, credit_font)
    margin = max(4, int(size * 0.012))
    draw.text((size - margin - cw - cleft, size - margin - ch - ctop),
              CREDIT, fill=(130, 128, 122, 255), font=credit_font)
    room = banner - ch - margin         # above the credit
    y = size - banner + max(int(banner * 0.08), (room - total) // 2)
    for (t, f, fill), (w, h, left, top) in zip(lines, sizes):
        draw.text(((size - w) // 2 - left, y - top), t, fill=fill, font=f)
        y += h + int(banner * 0.06)


def _text_size(draw, text, font):
    """(width, height, left, top) of text."""
    try:
        left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
        return right - left, bottom - top, left, top
    except AttributeError:              # old Pillow
        w, h = draw.textsize(text, font=font)
        return w, h, 0, 0


def _font(px):
    from PIL import ImageFont
    for name in ("seguisb.ttf", "segoeui.ttf", "arialbd.ttf", "arial.ttf",
                 "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=px)
    except TypeError:                   # old Pillow
        return ImageFont.load_default()


# ---------------------------------------------------------------------------
# Checks (the uploader's own) and the build stamp
# ---------------------------------------------------------------------------

def build_stamp(*parts):
    """A short hash of what a mod is generated from (to tell whether the
    mod folder is up to date with the project)."""
    blob = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


def read_stamp(mod_dir):
    try:
        with open(os.path.join(mod_dir, STAMP_FILE), encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return None


def find_modinfo(mod_dir):
    """The mod folder's .modinfo (the newest, if several), or None."""
    try:
        found = [os.path.join(mod_dir, f) for f in os.listdir(mod_dir)
                 if f.lower().endswith(".modinfo")]
    except OSError:
        return None
    return max(found, key=os.path.getmtime) if found else None


def check_mod(mod_dir, values, stamp=None):
    """[(ok, message)]: the checks the uploader makes, and a few of ours.
    values: resolved() settings (title, description, preview_path); stamp:
    the project's current build_stamp (None: not checked)."""
    results = []

    def check(ok, good, bad):
        results.append((bool(ok), good if ok else bad))

    modinfo = find_modinfo(mod_dir) if os.path.isdir(mod_dir) else None
    check(modinfo, "Mod found: " + (modinfo or ""),
          "No generated mod in {} - generate it first".format(mod_dir))
    if not modinfo:
        return results
    if stamp is not None:
        check(read_stamp(mod_dir) == stamp, "The mod is up to date",
              "The project has changed since the mod was generated - "
              "generate it again")
    try:
        root = ET.parse(modinfo).getroot()
    except (ET.ParseError, OSError) as exc:
        check(False, "", "The .modinfo cannot be read ({})".format(exc))
        return results
    try:
        uuid.UUID(root.get("id") or "")
        guid_ok = True
    except ValueError:
        guid_ok = False
    check(guid_ok, "Mod id is a GUID ({})".format(root.get("id")),
          "Mod id is not a GUID: {}".format(root.get("id")))
    name = (root.findtext("Properties/Name") or "").strip()
    check(name, "Mod name: " + name, "The mod has no name")
    title, description = values["title"], values["description"]
    check(title.strip() and len(title) <= MAX_TITLE,
          "Title: {} of {} characters".format(len(title), MAX_TITLE),
          "Title must be 1 to {} characters ({} now)".format(
              MAX_TITLE, len(title)))
    check(description.strip() and len(description) <= MAX_DESCRIPTION,
          "Description: {} of {} characters".format(len(description),
                                                    MAX_DESCRIPTION),
          "Description must be 1 to {} characters ({} now)".format(
              MAX_DESCRIPTION, len(description)))
    missing = [f.text for f in root.iter("File")
               if f.text and not os.path.isfile(os.path.join(mod_dir,
                                                             f.text))]
    check(not missing, "All files the mod lists exist",
          "Missing files: " + ", ".join(sorted(set(missing))[:5]))
    forbidden = []
    for folder, _, files in os.walk(mod_dir):
        forbidden += [os.path.relpath(os.path.join(folder, f), mod_dir)
                      for f in files if f.lower().endswith(FORBIDDEN)]
    check(not forbidden, "No archives or programs in the mod folder",
          "The uploader refuses archives / programs: " +
          ", ".join(forbidden[:5]))
    preview = values.get("preview_path") or ""
    if not preview or not os.path.isfile(preview):
        check(False, "", "No preview image (make one on the Details tab)")
    else:
        size = os.path.getsize(preview)
        check(size < MAX_PREVIEW_BYTES and preview.lower().endswith(
            (".jpg", ".jpeg", ".png")),
            "Preview image: {} KB".format(size // 1024),
            "The preview must be a .jpg or .png under 1 MB ({} KB)".format(
                size // 1024))
    return results


# ---------------------------------------------------------------------------
# The uploader
# ---------------------------------------------------------------------------

def find_uploader():
    """The SDK's Workshop uploader in any Steam library, or None."""
    for lib in steam_libraries():
        path = os.path.join(lib, "steamapps", "common",
                            "Sid Meier's Civilization VI SDK",
                            "ModUploader", UPLOADER_EXE)
        if os.path.isfile(path):
            return path
    return None


def steam_running():
    """Whether Steam is running (True when it cannot be told)."""
    if sys.platform != "win32":
        return True
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq steam.exe"],
                             capture_output=True, text=True, timeout=10,
                             creationflags=getattr(subprocess,
                                                   "CREATE_NO_WINDOW", 0))
        return "steam.exe" in out.stdout.lower()
    except (OSError, subprocess.SubprocessError):
        return True


def launch_uploader(path):
    """Start the uploader (from its own folder: it reads steam_appid.txt
    and the Steam API from there)."""
    return subprocess.Popen([path], cwd=os.path.dirname(path))


def workshop_url(published_id):
    """The item's page from an id or a pasted URL, or None."""
    m = re.search(r"(\d{6,})", published_id or "")
    return WORKSHOP_URL.format(m.group(1)) if m else None
