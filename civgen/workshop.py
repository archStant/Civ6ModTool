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

import functools
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
PREVIEW_SIZE = 512*4
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
    text = re.sub(r"\[(COLOR_[A-Za-z0-9_]+|ENDCOLOR)\]", "", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def plain_text(bbcode):
    """Steam BBCode -> plain text (for the .modinfo's Description)."""
    text = re.sub(r"\[\*\]", "- ", bbcode or "")
    text = re.sub(r"\[/?[a-z0-9]+(=[^\]]*)?\]", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _uniques_list(spec):
    """BBCode lines listing the named uniques of a civilization or leader
    spec ([] without any)."""
    uniques = [u for u in spec.get("uniques") or []
               if (u.get("name") or "").strip()]
    if not uniques:
        return []
    out = ["[list]"]
    for u in uniques:
        desc = strip_game_markup(u.get("desc"))
        out.append("[*][b]{}[/b] (unique {}){}".format(
            u["name"].strip(), u.get("kind", ""),
            ": " + desc if desc else ""))
    return out + ["[/list]"]


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
        out += _uniques_list(civ)
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
            out += _uniques_list(spec)
        out.append("[/list]")
    out.append("")
    out.append("Works with the base game, Rise and Fall and Gathering "
               "Storm.")
    out.append("[i]Made with [url=https://github.com/archStant/Civ6ModTool]Civ 6 Mod Generator[/url][/i]")
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
    return _save_jpeg(img, path)


def _save_jpeg(img, path):
    """img as a JPEG at path, under MAX_PREVIEW_BYTES. Returns path."""
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


def _icon_tint(leader_specs):
    """The first leader's secondary color, which the game colors the
    (white) civilization icon with."""
    return tuple((leader_specs[0].get("secondary") if leader_specs else None)
                 or (230, 230, 230))


def _gradient(size):
    """A dark backdrop with a soft vertical gradient."""
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (size, size), (28, 30, 36, 255))
    draw = ImageDraw.Draw(img)
    for y in range(size):
        shade = int(28 + 30 * y / size)
        draw.line([(0, y), (size, y)], fill=(shade, shade + 4, shade + 14))
    return img


def _fit(img, box):
    """img scaled (up or down, aspect kept) to fit inside box (w, h) -
    unlike thumbnail, which only shrinks."""
    from PIL import Image
    scale = min(box[0] / float(img.width), box[1] / float(img.height))
    return img.resize((max(1, int(img.width * scale)),
                       max(1, int(img.height * scale))), Image.LANCZOS)


def _simple_preview(title, civ_specs, leader_specs):
    from .art import fitted_portrait
    from .civs import civ_icon_preview
    size = PREVIEW_SIZE
    img = _gradient(size)
    picture = None
    color = _leader_color(leader_specs)
    for civ in civ_specs:
        if (civ.get("icon_path") or "").strip():
            picture = civ_icon_preview(civ, int(size * 0.62), badge=color,
                                       tint=_icon_tint(leader_specs))
            break
    if picture is None:
        for spec in leader_specs:
            src = (spec.get("load_fg_path") or "").strip()
            if src and os.path.isfile(src):
                picture = _fit(fitted_portrait(src),
                               (int(size * 0.78), int(size * 0.78)))
                break
    if picture is None and civ_specs:
        picture = civ_icon_preview(civ_specs[0], int(size * 0.62),
                                   badge=color, tint=_icon_tint(leader_specs))
    if picture is not None:
        img.alpha_composite(picture.convert("RGBA"),
                            ((size - picture.width) // 2,
                             int(size * 0.40) - picture.height // 2))
    _banner(img, title)
    return img


def _files(*paths):
    return [p for p in paths if p and os.path.isfile(p)]


def _background(leader_specs):
    """(image path, hue) of the collage background: the first leader's
    loading background (its own, or the default), else another leader's,
    else a diplomacy background, else the default loading background. A
    loading background is always turned by the first leader's hue, so the
    preview has the colors that leader was given."""
    from .art import DEFAULT_LOAD_BG
    from .util import asset_path
    default = asset_path(DEFAULT_LOAD_BG)
    try:
        hue = int((leader_specs[0].get("load_bg_hue") if leader_specs
                   else 0) or 0)
    except (TypeError, ValueError):
        hue = 0
    for spec in leader_specs:
        own = (spec.get("load_bg_path") or "").strip()
        if _files(own):
            return own, hue
        if spec.get("load_bg_default") and default:
            return default, hue
    for spec in leader_specs:
        if _files((spec.get("diplo_bg_path") or "").strip()):
            return spec["diplo_bg_path"].strip(), 0
    return default, hue


def _civ_colors(civ, leader_specs):
    """(badge color, icon tint) of a civilization: its own leader's primary
    and secondary colors (the leader linked to it), else the first
    leader's."""
    for spec in leader_specs:
        if civ.get("id") and spec.get("civ_id") == civ.get("id"):
            return _leader_color([spec]), _icon_tint([spec])
    return _leader_color(leader_specs), _icon_tint(leader_specs)


def _trimmed(img):
    """img cropped to its non-transparent part (fitted portraits have
    transparent margins, which would make leaders differ in height)."""
    box = img.getchannel("A").getbbox()
    return img.crop(box) if box else img


def _emblem(civ, leader_specs, width, opacity):
    """The civilization's icon, large and see-through, with a soft glow in
    its leader's color: a watermark behind the leaders."""
    from PIL import Image, ImageFilter
    from .civs import civ_icon_preview
    color, tint = _civ_colors(civ, leader_specs)
    icon = civ_icon_preview(civ, width, tint=tint).convert("RGBA")
    blur = max(2, width // 18)
    pad = 3 * blur
    out = Image.new("RGBA", (width + 2 * pad, width + 2 * pad), (0, 0, 0, 0))
    glow = Image.new("RGBA", icon.size, tuple(color) + (255,))
    glow.putalpha(icon.getchannel("A"))
    halo = Image.new("RGBA", out.size, (0, 0, 0, 0))
    halo.alpha_composite(glow, (pad, pad))
    halo = halo.filter(ImageFilter.GaussianBlur(blur))
    out.alpha_composite(halo)
    out.alpha_composite(halo)            # twice: a stronger glow
    out.alpha_composite(icon, (pad, pad))
    out.putalpha(out.getchannel("A").point(lambda a: int(a * opacity)))
    return out


def _civ_badge(civ, leader_specs, size):
    """The civilization's icon on a round badge in its leader's color,
    with a thin ring in the icon's color around it."""
    from PIL import Image, ImageDraw
    from .civs import civ_icon_preview
    color, tint = _civ_colors(civ, leader_specs)
    badge = civ_icon_preview(civ, size, badge=color, tint=tint)
    ring = max(3, size // 40)
    full = size + 2 * ring
    ss = 4
    disc = Image.new("RGBA", (full * ss, full * ss), (0, 0, 0, 0))
    ImageDraw.Draw(disc).ellipse((0, 0, full * ss - 1, full * ss - 1),
                                 fill=tuple(tint) + (255,))
    out = disc.resize((full, full), Image.LANCZOS)
    out.alpha_composite(badge.convert("RGBA"), (ring, ring))
    return out


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
    - the background: a leader's loading background (darkened), turned by
      the first leader's hue
    - the civilizations' icons, large and glowing behind the leaders
    - historic moment pictures as tilted cards (up to 2)
    - the leaders' loading portraits, side by side, all the same height
      (up to 3)
    - the civilizations' icons on big badges, top left
    - the uniques' icons / portraits in rows of badges, top right (up to 6)
    - the title on a banner, with what the mod adds."""
    from PIL import Image, ImageEnhance, ImageOps
    from .art import fitted_portrait, shift_hue
    size = PREVIEW_SIZE
    banner = int(size * 0.2)
    margin = int(size * 0.03)
    color = _leader_color(leader_specs)
    portraits = [_trimmed(fitted_portrait(p)) for p in _files(*[
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
        for c in list(civ_specs) + list(leader_specs)
        for u in c.get("uniques") or []])[:6]
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

    # the civilizations' icons: big glowing watermarks, centre stage
    if civ_icons:
        width = int(size * (0.62 if len(civ_icons) == 1 else 0.44))
        spots = {1: [0.5], 2: [0.3, 0.7]}[len(civ_icons)]
        for civ, spot in zip(civ_icons, spots):
            mark = _emblem(civ, leader_specs, width,
                           0.55 if portraits else 0.9)
            _composite(img, mark, int(size * spot - mark.width / 2),
                       int(size * 0.42 - mark.height / 2))

    # moments: tilted cards behind the leaders, left and right
    for i, entry in enumerate(moments):
        card = _card(dict(entry, path=entry["path"].strip()),
                     int(size * 0.34), 8 if i == 0 else -7)
        x = margin if i == 0 else size - card.width - margin
        _paste(img, card, x, int(size * 0.34))

    # leaders: standing on the banner, all the same height, the first in
    # front and centre
    if portraits:
        height = int(size * (0.66 if len(portraits) == 1 else 0.56))
        # the same height for all, unless that makes one too wide
        widest = max(p.width / float(p.height) for p in portraits)
        room = size * {1: 0.8, 2: 0.46, 3: 0.4}[len(portraits)]
        height = int(min(height, room / widest))
        fitted = [p.resize((max(1, int(p.width * height / float(p.height))),
                            height), Image.LANCZOS) for p in portraits]
        spots = {1: [0.5], 2: [0.3, 0.7], 3: [0.5, 0.2, 0.8]}[len(fitted)]
        for i in sorted(range(len(fitted)), key=lambda i: -i):  # back first
            p = fitted[i]
            x = int(size * spots[i] - p.width / 2)
            _paste(img, p, x, size - banner - p.height + int(size * 0.01))

    # the civilizations' icons on big badges, top left
    x = margin
    badge_size = int(size * (0.24 if len(civ_icons) == 1 else 0.2))
    for civ in civ_icons:
        badge = _civ_badge(civ, leader_specs, badge_size)
        _paste(img, badge, x, margin)
        x += badge.width + int(size * 0.015)

    # the uniques: small badges, top right, in rows of three beside the
    # civilization badges
    if unique_pics:
        small = int(size * 0.1)
        gap = int(size * 0.012)
        step = small + 6 + gap
        per_row = 3 if civ_icons else 6
        for n, path in enumerate(unique_pics):
            row, col = divmod(n, per_row)
            in_row = min(per_row, len(unique_pics) - row * per_row)
            badge = _badge(Image.open(path), small, color)
            _paste(img, badge, size - margin - (in_row - col) * step + gap,
                   margin + row * step)

    adds = []
    if civ_specs:
        adds.append("{} civilization{}".format(
            len(civ_specs), "" if len(civ_specs) == 1 else "s"))
    if leader_specs:
        adds.append("{} leader{}".format(
            len(leader_specs), "" if len(leader_specs) == 1 else "s"))
    uniques = sum(len(c.get("uniques") or [])
                  for c in list(civ_specs) + list(leader_specs))
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


FONTS = {
    "bold": ("seguisb.ttf", "segoeui.ttf", "arialbd.ttf", "arial.ttf",
             "DejaVuSans-Bold.ttf"),
    "regular": ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"),
    "italic": ("segoeuii.ttf", "ariali.ttf", "DejaVuSans-Oblique.ttf",
               "segoeui.ttf", "arial.ttf"),
    "serif": ("georgiab.ttf", "timesbd.ttf", "DejaVuSerif-Bold.ttf",
              "seguisb.ttf", "arialbd.ttf"),
}


@functools.lru_cache(maxsize=64)
def _font(px, style="bold"):
    from PIL import ImageFont
    for name in FONTS[style] + ("arial.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=px)
    except TypeError:                   # old Pillow
        return ImageFont.load_default()


# ---------------------------------------------------------------------------
# Showcase images: one per civilization and per leader, like the game's
# loading screen (the uploader takes one preview only - these are added
# on the Workshop page, under "Add/edit images & videos")
# ---------------------------------------------------------------------------

SHOWCASE_SIZE = (1920, 1080)
TEXT_COLOR = (236, 232, 222, 255)
BODY_COLOR = (206, 201, 190, 255)
UNIQUE_KINDS = {"unit": "Unique Unit", "building": "Unique Building",
                "district": "Unique District",
                "improvement": "Unique Improvement"}


def make_showcase(out_dir, civ_specs, leader_specs,
                  civ_name=lambda spec: spec.get("civ", "")):
    """A 16:9 JPEG per civilization and per leader in out_dir, each with
    its art and its abilities and uniques listed (see _civ_card,
    _leader_card); ones with nothing to show are skipped. civ_name(leader
    spec): the name of the leader's civilization. Returns the paths.
    Raises ImportError without Pillow."""
    paths, used = [], set()

    def save(img, prefix, name):
        base = re.sub(r"[^A-Za-z0-9]+", "_", name or "").strip("_") or \
            "unnamed"
        stem, n = "{}_{}".format(prefix, base), 2
        while stem.lower() in used:
            stem, n = "{}_{}_{}".format(prefix, base, n), n + 1
        used.add(stem.lower())
        paths.append(_save_jpeg(img, os.path.join(out_dir, stem + ".jpg")))

    for civ in civ_specs:
        img = _civ_card(civ, leader_specs)
        if img is not None:
            save(img, "civ", civ.get("name"))
    for spec in leader_specs:
        img = _leader_card(spec, _linked_civ(spec, civ_specs), civ_name)
        if img is not None:
            save(img, "leader", spec.get("name"))
    return paths


def _linked_civ(spec, civ_specs):
    """The project civilization a leader leads, or None."""
    for civ in civ_specs:
        if civ.get("id") and spec.get("civ_id") == civ.get("id"):
            return civ
    return None


def _named(entry):
    return bool(((entry or {}).get("name") or "").strip())


def _ability_blocks(label, ability):
    if not _named(ability):
        return []
    blocks = [("label", label), ("title", ability["name"].strip())]
    desc = _rich(ability.get("desc"))
    if desc:
        blocks.append(("body", desc))
    return blocks


def _unique_blocks(spec):
    blocks = []
    for u in spec.get("uniques") or []:
        if not _named(u):
            continue
        kind = UNIQUE_KINDS.get(u.get("kind"), "Unique")
        base = (u.get("base") or "").strip()
        if base and u.get("replaces", True):
            kind += " · replaces " + base.split("_", 1)[-1].replace(
                "_", " ").title()
        icon = _files((u.get("portrait_path") or "").strip(),
                      (u.get("icon_path") or "").strip())
        blocks.append(("unique", icon[0] if icon else None,
                       u["name"].strip(), kind, _rich(u.get("desc"))))
    return blocks


def _canvas(leader_specs):
    """The card's backdrop: a leader's loading background (darkened,
    turned by the leader's hue) covering the 16:9 canvas."""
    from PIL import Image, ImageEnhance, ImageOps
    from .art import shift_hue
    w, h = SHOWCASE_SIZE
    img = _gradient(w).crop((0, 0, w, h))
    bg_path, hue = _background(leader_specs)
    if bg_path:
        bg = ImageOps.fit(Image.open(bg_path).convert("RGBA"), (w, h),
                          Image.LANCZOS)
        if hue:
            bg = shift_hue(bg, hue)
        img.alpha_composite(ImageEnhance.Brightness(bg).enhance(0.6))
    return img


PANEL_X = 0.53                          # where the text panel starts


def _showcase_card(art, header, blocks, accent, ring, badge=None):
    """A showcase card: art (an RGBA image) on the left, a dark panel on
    the right with header (title, subtitle, quote), blocks (see _layout)
    and the credit. accent: the stripe color; ring: the color of labels
    and unique badges' rings."""
    from PIL import Image, ImageDraw
    w, h = SHOWCASE_SIZE
    img = art
    x0 = int(w * PANEL_X)
    panel = Image.new("RGBA", (w - x0, h), (10, 11, 15, 228))
    img.alpha_composite(panel, (x0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle([x0, 0, x0 + 5, h], fill=tuple(accent) + (255,))
    pad = 64
    left, right = x0 + pad, w - pad
    credit_font = _font(20, "regular")
    cw, ch, cl, ct = _text_size(draw, CREDIT, credit_font)
    bottom = h - pad // 2 - ch - 16
    # largest scale whose layout fits; else the smallest, cut short
    for scale in (1.0, 0.92, 0.84, 0.76, 0.68, 0.6):
        ops, end = _layout(draw, left, pad, right - left, header, blocks,
                           scale, ring, badge)
        if end <= bottom:
            break
    _draw_ops(img, draw, ops, bottom, right)
    draw.text((right - cw - cl, h - pad // 2 - ch - ct), CREDIT,
              fill=(130, 128, 122, 255), font=credit_font)
    return img


def _layout(draw, x, y, width, header, blocks, s, ring, badge):
    """Draw operations for the panel at scale s: [("text", x, y, text,
    font, fill, height) or ("image", x, y, img, height)], and the y they
    end at. header: (title, subtitle, quote); blocks: ("label", text),
    ("title", text), ("body", text) or ("unique", icon path or None,
    name, kind, desc)."""
    from PIL import Image
    from .art import placeholder_icon
    ops = []
    label_fill = tuple(ring) + (255,)

    def lines(text, font, fill, lx, lwidth, gap=0.25):
        """Wrapped text as ops from y 0, and their height."""
        lh = _line_height(font)
        out, ly = [], 0
        for line in _wrap(draw, text, font, lwidth):
            out.append(("text", lx, ly, line, font, fill, lh))
            ly += int(lh * (1 + gap)) if line else lh // 2
        return out, ly

    def place(chunk, top):
        for op in chunk:
            ops.append(op[:2] + (op[2] + top,) + op[3:])

    title, subtitle, quote = header
    # header: the badge, the title and subtitle beside it
    tx = x
    head_h = 0
    if badge is not None:
        size = int(150 * s)
        b = badge.resize((size, size), Image.LANCZOS)
        ops.append(("image", x, y, b, size))
        tx = x + size + int(28 * s)
        head_h = size
    chunk, th = lines(title, _font(int(68 * s), "serif"),
                      TEXT_COLOR, tx, x + width - tx, gap=0.05)
    if subtitle:
        sub, sh = lines(subtitle, _font(int(34 * s)), label_fill, tx,
                        x + width - tx)
        chunk += [op[:2] + (op[2] + th + int(6 * s),) + op[3:]
                  for op in sub]
        th += sh + int(6 * s)
    place(chunk, y + max(0, (head_h - th) // 2))
    y += max(head_h, th) + int(26 * s)
    if quote:
        chunk, qh = lines("“{}”".format(quote.strip().strip(
            '"“”')), _font(int(26 * s), "italic"),
            (186, 182, 172, 255), x, width, gap=0.15)
        place(chunk, y)
        y += qh + int(10 * s)

    for block in blocks:
        kind = block[0]
        if kind == "label":
            y += int(30 * s)
            chunk, bh = lines(block[1].upper(), _font(int(22 * s)),
                              label_fill, x, width)
            place(chunk, y)
            y += bh
        elif kind == "title":
            chunk, bh = lines(block[1], _font(int(36 * s), "serif"),
                              TEXT_COLOR, x, width, gap=0.1)
            place(chunk, y)
            y += bh + int(4 * s)
        elif kind == "body":
            chunk, bh = lines(block[1], _font(int(26 * s), "regular"),
                              BODY_COLOR, x, width, gap=0.18)
            place(chunk, y)
            y += bh
        elif kind == "unique":
            _, path, name, what, desc = block
            y += int(26 * s)
            size = int(92 * s)
            if path:
                icon = _badge(Image.open(path), size, ring)
            else:
                icon = placeholder_icon(name, (40, 42, 50), ring, size + 6)
            ops.append(("image", x, y, icon, icon.height))
            ux = x + size + 6 + int(22 * s)     # the same for every icon
            chunk, bh = lines(name, _font(int(32 * s), "serif"), TEXT_COLOR,
                              ux, x + width - ux, gap=0.05)
            sub, sh = lines(what, _font(int(20 * s)), label_fill, ux,
                            x + width - ux)
            chunk += [op[:2] + (op[2] + bh,) + op[3:] for op in sub]
            bh += sh + int(4 * s)
            if desc:
                body, dh = lines(desc, _font(int(25 * s), "regular"),
                                 BODY_COLOR, ux, x + width - ux, gap=0.18)
                chunk += [op[:2] + (op[2] + bh,) + op[3:] for op in body]
                bh += dh
            place(chunk, y)
            y += max(icon.height, bh)
    return ops, y


def _draw_ops(img, draw, ops, bottom, right):
    """Draw ops (see _layout) that end above bottom; if some do not, the
    last text line drawn ends in an ellipsis."""
    shown = []
    for op in ops:
        if op[2] + op[-1] > bottom:
            break
        shown.append(op)
    if len(shown) < len(ops):
        texts = [i for i, op in enumerate(shown) if op[0] == "text"]
        if texts:
            i = texts[-1]
            op = shown[i]
            line = op[3].rstrip(" .,;:") + "…"
            while line != "…" and _rich_width(
                    draw, line, op[4]) > right - op[1]:
                # (never leave half an icon tag behind)
                line = re.sub(r"\[[^\]]*$", "",
                              line[:-2]).rstrip() + "…"
            shown[i] = op[:3] + (line,) + op[4:]
    for op in shown:
        if op[0] == "image":
            img.alpha_composite(op[3], (int(op[1]), int(op[2])))
        else:
            _draw_rich(img, draw, op[1], op[2], op[3], op[4], op[5])


def _line_height(font):
    try:
        ascent, descent = font.getmetrics()
        return ascent + descent
    except AttributeError:              # old Pillow's bitmap font
        return 12


# Inline game icons ([ICON_Faith] -> the game's font icon, see
# fonticons.py): text keeps the tags of icons that exist, and is
# measured and drawn piece by piece.

def _font_icons():
    """The game's font icons (falsy without the game / SDK Assets)."""
    from .fonticons import default_icons
    return default_icons()


def _rich(text):
    """Game text for the showcase: like strip_game_markup, but icon tags
    the game has an image for are kept (to draw inline)."""
    from .fonticons import ICON_TAG
    icons = _font_icons()
    text = (text or "").replace("[NEWLINE]", "\n")
    text = re.sub(r"\[(COLOR_[A-Za-z0-9_]+|ENDCOLOR)\]", "", text)
    text = ICON_TAG.sub(lambda m: m.group(0) if icons and icons.get(
        m.group(1)) is not None else "", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def _icon_size(font):
    """How big an inline icon is drawn (its art, margin trimmed): a
    little taller than the capital letters, like the game's."""
    return max(8, int(round(getattr(font, "size", 12) * 1.05)))


def _inline_icon(name, font):
    icons = _font_icons()
    return icons.get(name, _icon_size(font), trim=True) if icons else None


def _pieces(text):
    """text split into ("text", str) and ("icon", name) pieces."""
    from .fonticons import ICON_TAG
    out, pos = [], 0
    for m in ICON_TAG.finditer(text):
        if m.start() > pos:
            out.append(("text", text[pos:m.start()]))
        out.append(("icon", m.group(1)))
        pos = m.end()
    if pos < len(text):
        out.append(("text", text[pos:]))
    return out


def _advance(draw, text, font):
    try:
        return draw.textlength(text, font=font)
    except AttributeError:              # old Pillow
        return _text_size(draw, text, font)[0]


def _icon_pad(font):
    return max(1, _icon_size(font) // 8)


def _rich_width(draw, text, font):
    """The width text takes, its icons included."""
    width = 0
    for kind, value in _pieces(text):
        if kind == "text":
            width += _advance(draw, value, font)
        else:
            icon = _inline_icon(value, font)
            if icon is not None:
                width += icon.width + 2 * _icon_pad(font)
    return width


def _draw_rich(img, draw, x, y, text, font, fill):
    """text at (x, y), its icon tags drawn as the game's icons, centred
    on the capital letters' height."""
    pad = _icon_pad(font)
    try:
        _, top, _, bottom = font.getbbox("H")
        middle = y + (top + bottom) / 2.0
    except AttributeError:
        middle = y + _line_height(font) / 2.0
    for kind, value in _pieces(text):
        if kind == "text":
            draw.text((x, y), value, font=font, fill=fill)
            x += _advance(draw, value, font)
            continue
        icon = _inline_icon(value, font)
        if icon is not None:
            img.alpha_composite(icon, (int(round(x + pad)),
                                       int(round(middle - icon.height / 2.0))))
            x += icon.width + 2 * pad


def _wrap(draw, text, font, width):
    """text broken into lines no wider than width (paragraphs kept; an
    empty line between them). Icon tags count as their icon's width."""
    out = []
    for n, para in enumerate((text or "").split("\n")):
        if n and out and out[-1] != "":
            out.append("")
        line = ""
        for word in para.split():
            trial = (line + " " + word) if line else word
            if line and _rich_width(draw, trial, font) > width:
                out.append(line)
                line = word
            else:
                line = trial
        if line:
            out.append(line)
    while out and out[-1] == "":
        out.pop()
    return out


def _art(img, portrait_path, civ, leader_specs):
    """The left side of a card: the civilization's glowing emblem, with
    the leader's portrait standing in front of it."""
    from .art import fitted_portrait
    w, h = SHOWCASE_SIZE
    cx = int(w * PANEL_X / 2)
    portrait = _trimmed(fitted_portrait(portrait_path)) \
        if portrait_path else None
    if civ is not None and _files((civ.get("icon_path") or "").strip()):
        mark = _emblem(civ, leader_specs, int(h * 0.68),
                       0.5 if portrait is not None else 0.95)
        _composite(img, mark, cx - mark.width // 2,
                   int(h * (0.42 if portrait is not None else 0.5)) -
                   mark.height // 2)
    if portrait is not None:
        height = int(h * 0.9)
        width = int(portrait.width * height / float(portrait.height))
        if width > w * PANEL_X * 0.95:
            width = int(w * PANEL_X * 0.95)
            height = int(portrait.height * width / float(portrait.width))
        from PIL import Image
        p = portrait.resize((max(1, width), max(1, height)), Image.LANCZOS)
        _paste(img, p, cx - p.width // 2, h - p.height)
    return img


def _leader_card(spec, civ, civ_name):
    """A leader's card: its portrait over its loading background, and its
    civilization's ability (when that is the project's), its own
    abilities and the uniques of both. None if it has nothing to show."""
    blocks = []
    if civ is not None:
        blocks += _ability_blocks("Civilization ability", civ.get("ability"))
    blocks += _ability_blocks("Leader ability", spec.get("new_ability"))
    for ability in (spec.get("abilities") or {}).values():
        blocks += _ability_blocks("Leader ability", ability)
    uniques = (_unique_blocks(civ) if civ is not None else []) + \
        _unique_blocks(spec)
    if uniques:
        blocks += [("label", "Uniques")] + uniques
    portrait = _files((spec.get("load_fg_path") or "").strip())
    if not (blocks or portrait):
        return None
    img = _art(_canvas([spec]), portrait[0] if portrait else None, civ,
               [spec])
    badge = _civ_badge(civ, [spec], 300) if civ is not None and _files(
        (civ.get("icon_path") or "").strip()) else None
    header = ((spec.get("name") or "").strip() or "Leader",
              (civ.get("name") if civ is not None else "") or civ_name(spec),
              (spec.get("quote") or "").strip())
    return _showcase_card(img, header, blocks, _leader_color([spec]),
                          _icon_tint([spec]), badge)


def _civ_card(civ, leader_specs):
    """A civilization's card: its glowing emblem over a leader's loading
    background, its ability, its uniques and its leaders. None if it has
    nothing to show."""
    led = [s for s in leader_specs
           if civ.get("id") and s.get("civ_id") == civ.get("id")]
    blocks = _ability_blocks("Civilization ability", civ.get("ability"))
    uniques = _unique_blocks(civ)
    if uniques:
        blocks += [("label", "Uniques")] + uniques
    names = [s["name"].strip() for s in led if _named(s)]
    if names:
        blocks += [("label", "Leader" + ("s" if len(names) > 1 else "")),
                   ("body", ", ".join(names))]
    has_icon = bool(_files((civ.get("icon_path") or "").strip()))
    if not (blocks or has_icon):
        return None
    colors = led or leader_specs
    img = _art(_canvas(colors), None, civ if has_icon else None, colors)
    badge = _civ_badge(civ, colors, 300) if has_icon else None
    color, tint = _civ_colors(civ, leader_specs)
    subtitle = (civ.get("description") or "").strip()
    if not subtitle or len(subtitle) > 60:
        subtitle = (civ.get("adjective") or "").strip()
    header = ((civ.get("name") or "").strip() or "Civilization", subtitle, "")
    return _showcase_card(img, header, blocks, color, tint, badge)


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
