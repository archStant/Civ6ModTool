"""New religions: specs, validation and their mod file fragments.

A religion spec is a plain dict:
    id (stable across renames; leaders that favor the religion refer to
    it by id), name, icon_path (custom icon image) or icon_from (a game
    religion whose icon it uses), color ((r, g, b): its color on the map,
    in the religion lens and on its icon's badge), glow (add a soft glow
    around the icon image's shapes, like the game's own religion icons
    have), glow_strength (1-100) and opacity (10-100: how see-through
    the icon image is, its glow included), pedia {history} (its
    Civilopedia page: paragraphs separated by a blank line), moment
    {path, mask, half, sepia} (the "religion founded" historic moment's
    picture; no path: automatic, see religion_moments), renameable (the
    player names it when founding it, like the game's spare "Custom
    Religion"s; its name is then only its label in the founding list).

The game needs a Religions row (with a Colors row for its color) and an
icon named ICON_<ReligionType> at the sizes the UI asks for. A religion
appears on the religion-founding screen by itself; how many religions a
game allows depends on the map size, not on how many exist.
"""

import functools
import os
import random
import uuid

from .texts import history_paragraphs, loc_text
from .util import slug_for_name, sql_str

# The UI's religion icon sizes (Icons_Religions.xml: 22 / 50 / 100 in
# ICON_ATLAS_RELIGIONS, 270 in an atlas per religion)
RELIGION_ICON_SIZES = [22, 50, 100, 270]
DEFAULT_RELIGION_COLOR = (200, 160, 60)
# the icon of a religion without an icon of its own (or whose image
# could not be cooked)
FALLBACK_RELIGION_ICON = "RELIGION_CUSTOM_1"
# The soft glow around an icon's shapes: its blur radius, as a share of
# the icon's size (so every size looks alike), and its strength
GLOW_RADIUS = 0.03
DEFAULT_GLOW_STRENGTH = 50
# the icon image's opacity, in percent (below the minimum it would be
# nearly invisible)
MIN_OPACITY, MAX_OPACITY = 10, 100

# The "religion founded" historic moment (Rise and Fall / Gathering
# Storm): its picture is keyed by the religion and drawn on the left page
# of the game's book picture (HistoricMoments.xml: ReligionIllustration,
# 166 x 122)
MOMENT_RELIGION = ("MOMENT_ILLUSTRATION_RELIGION", "MOMENT_DATA_RELIGION")
RELIGION_MOMENT_SIZE = (166, 122)
# the game's pictures: the symbol in brown ink, foreshortened like the
# page, about 105 x 78 around this centre
INK_COLOR = (70, 52, 22)
INK_ALPHA = 0.85
INK_BOX = (105, 78)
# In the game the picture shows a little higher on the book than the
# preview put it. This many pixels move the ink symbol down in the
# picture, and the picture up on the preview's book - so the preview
# looks the same and the game shows the symbol where the preview does.
# Fine-tune it here: larger moves the symbol further down in the game.
GAME_Y_CORRECTION = 8
INK_CENTRE = (88, 57 + GAME_Y_CORRECTION)
# The book the game draws the picture on (456 x 332, uncooked only in the
# SDK Assets; for previews - the mod never contains it), and where on it
# the picture goes: centred, moved by this offset (ReligionIllustration's
# Offset="-47,47", corrected as above)
MOMENT_BOOK_TEXTURE = "PM_FoundedReligion"
MOMENT_PAGE_OFFSET = (-47, 47 - GAME_Y_CORRECTION)
INK_SQUASH = 0.74
# The symbol's angle, in degrees. Slant: a shear like the page's slope
# (negative: the bottom leans right, as in the game's own pictures);
# rotation: anticlockwise.
DEFAULT_INK_SLANT = -14       # (measured on the game's Buddhism picture)
MAX_INK_SLANT, MAX_INK_ROTATION = 30, 45
# Its size (percent of INK_BOX) and place (pixels from INK_CENTRE, right
# and down); it is always kept inside the picture
MIN_INK_SCALE, MAX_INK_SCALE = 50, 150
MAX_INK_X, MAX_INK_Y = 40, 30
# the moment spec's ink keys: (key, default, low, high)
INK_SETTINGS = [("ink_slant", DEFAULT_INK_SLANT, -MAX_INK_SLANT,
                 MAX_INK_SLANT),
                ("ink_rotation", 0, -MAX_INK_ROTATION, MAX_INK_ROTATION),
                ("ink_scale", 100, MIN_INK_SCALE, MAX_INK_SCALE),
                ("ink_x", 0, -MAX_INK_X, MAX_INK_X),
                ("ink_y", 0, -MAX_INK_Y, MAX_INK_Y)]


def new_moment_spec():
    return dict({"path": "", "mask": False, "half": False, "sepia": False},
                **{key: default for key, default, _, _ in INK_SETTINGS})


def ink_settings(moment):
    """The ink keys of a moment spec, read and kept in range (an older
    spec without them gets the defaults)."""
    out = {}
    for key, default, low, high in INK_SETTINGS:
        try:
            value = float(moment.get(key, default))
        except (TypeError, ValueError):
            value = default
        out[key] = max(low, min(high, value))
    return out


def new_religion_spec():
    return {"id": str(uuid.uuid4()), "name": "", "icon_path": "",
            "icon_from": "", "color": DEFAULT_RELIGION_COLOR,
            "glow": False, "glow_strength": DEFAULT_GLOW_STRENGTH,
            "opacity": MAX_OPACITY,
            "pedia": {"history": ""},
            "renameable": False,
            "moment": new_moment_spec()}


def religion_moment_ink(icon_path, slant=DEFAULT_INK_SLANT, rotation=0,
                        scale=100, x=0, y=0):
    """The religion's icon as the game draws religion symbols in the
    "religion founded" moment: a brown ink stamp, foreshortened like the
    book's page, with a grainy texture (RELIGION_MOMENT_SIZE RGBA). Only
    the image's shapes count (its colors, glow and opacity do not).
    slant / rotation: its angle in degrees (see DEFAULT_INK_SLANT);
    scale: its size in percent; x / y: its place, in pixels right / down
    of where the game's symbols are (see INK_SETTINGS)."""
    import math
    from PIL import Image, ImageChops, ImageFilter
    settings = ink_settings({"ink_slant": slant, "ink_rotation": rotation,
                             "ink_scale": scale, "ink_x": x, "ink_y": y})
    slant, rotation = settings["ink_slant"], settings["ink_rotation"]
    img = Image.open(icon_path).convert("RGBA")
    w, h = img.size
    side = min(w, h)
    img = img.crop(((w - side) // 2, (h - side) // 2,
                    (w - side) // 2 + side, (h - side) // 2 + side))
    work = 200
    shape = img.resize((work, work), Image.LANCZOS).getchannel("A")
    # thin outline icons: a little bolder, like stamped ink
    shape = shape.filter(ImageFilter.MaxFilter(5))
    out = Image.new("RGBA", RELIGION_MOMENT_SIZE, INK_COLOR + (0,))
    if rotation:
        shape = shape.rotate(rotation, resample=Image.BICUBIC, expand=True)
    bbox = shape.getbbox()
    if not bbox:
        return out
    shape = shape.crop(bbox)
    # squash: the page is seen at an angle
    shape = shape.resize((shape.width, max(1, int(round(
        shape.height * INK_SQUASH)))), Image.LANCZOS)
    # slant, like the page's slope: output x takes source x + k * y + c
    # (k < 0: the bottom rows move right)
    k = math.tan(math.radians(slant))
    if k:
        grow = int(math.ceil(abs(k) * shape.height))
        shape = shape.transform(
            (shape.width + grow, shape.height), Image.AFFINE,
            (1, k, -grow if k > 0 else 0, 0, 1, 0),
            resample=Image.BICUBIC)
        shape = shape.crop(shape.getbbox() or (0, 0) + shape.size)
    # fit the page's box (whatever the angle), at the chosen size - never
    # larger than the picture
    size = settings["ink_scale"] / 100.0
    box_w = min(INK_BOX[0] * size, RELIGION_MOMENT_SIZE[0])
    box_h = min(INK_BOX[1] * size, RELIGION_MOMENT_SIZE[1])
    fit = min(box_w / float(shape.width), box_h / float(shape.height))
    shape = shape.resize((max(1, int(round(shape.width * fit))),
                          max(1, int(round(shape.height * fit)))),
                         Image.LANCZOS)
    # grain, mottled like worn ink (seeded: the same every build)
    rnd = random.Random(1)
    grain = Image.frombytes("L", shape.size, bytes(
        rnd.randrange(170, 256) for _ in range(shape.width * shape.height)))
    grain = grain.filter(ImageFilter.GaussianBlur(0.7))
    alpha = ImageChops.multiply(
        shape.point(lambda v: int(v * INK_ALPHA)), grain)
    layer = Image.new("RGBA", shape.size, INK_COLOR + (0,))
    layer.putalpha(alpha)
    # its place, kept inside the picture
    left = INK_CENTRE[0] + int(round(settings["ink_x"])) - shape.width // 2
    top = INK_CENTRE[1] + int(round(settings["ink_y"])) - shape.height // 2
    left = max(0, min(out.width - shape.width, left))
    top = max(0, min(out.height - shape.height, top))
    out.alpha_composite(layer, (left, top))
    return out


def icon_opacity(spec):
    """The icon image's opacity of a religion spec as 0.1-1."""
    try:
        value = float(spec.get("opacity", MAX_OPACITY))
    except (TypeError, ValueError):
        value = MAX_OPACITY
    return max(MIN_OPACITY, min(MAX_OPACITY, value)) / 100.0


def glow_strength(spec):
    """The glow of a religion spec as 0-1 (0: no glow)."""
    if not spec.get("glow"):
        return 0.0
    try:
        value = float(spec.get("glow_strength", DEFAULT_GLOW_STRENGTH))
    except (TypeError, ValueError):
        value = DEFAULT_GLOW_STRENGTH
    return max(1.0, min(100.0, value)) / 100.0


def add_glow(img, strength, color=(255, 255, 255)):
    """img (RGBA) with a soft glow of color around its shapes: their
    blurred outline, drawn behind them. strength: 0-1."""
    from PIL import Image, ImageFilter
    if strength <= 0:
        return img
    radius = max(0.8, max(img.size) * GLOW_RADIUS)
    # (a blurred thin line is faint: up to 2x its blur's alpha)
    gain = 2.0 * strength
    alpha = img.getchannel("A").filter(ImageFilter.GaussianBlur(radius))
    alpha = alpha.point(lambda v: min(255, int(v * gain)))
    glow = Image.new("RGBA", img.size, tuple(color) + (0,))
    glow.putalpha(alpha)
    return Image.alpha_composite(glow, img)


def fade(img, opacity):
    """img (RGBA) made see-through: its alpha times opacity (0-1)."""
    if opacity >= 1:
        return img
    img = img.copy()
    img.putalpha(img.getchannel("A").point(
        lambda v: int(round(v * opacity))))
    return img


def glowing_icon(src, size, strength, opacity=1.0):
    """The icon image at src, centre-cropped and resized to size x size
    like the texture conversion does, with its glow, faded to opacity
    (RGBA)."""
    from PIL import Image
    img = Image.open(src).convert("RGBA")
    w, h = img.size
    side = min(w, h)
    img = img.crop(((w - side) // 2, (h - side) // 2,
                    (w - side) // 2 + side, (h - side) // 2 + side))
    return fade(add_glow(img.resize((size, size), Image.LANCZOS), strength),
                opacity)


def religion_slug(spec, prefix=""):
    return slug_for_name(spec.get("name"), prefix, kind="RELIGION")


def _color(value, name):
    try:
        rgb = tuple(int(v) for v in value)
    except (TypeError, ValueError):
        rgb = ()
    if len(rgb) != 3 or not all(0 <= v <= 255 for v in rgb):
        raise ValueError("{}: pick the religion's color again.".format(name))
    return rgb


def normalize_religion(spec, data, prefix=""):
    """Validate a religion spec and derive its type and tags. Raises
    ValueError with a human-friendly message."""
    name = (spec.get("name") or "").strip()
    if not name:
        raise ValueError("A religion has no name.")
    slug = religion_slug(spec, prefix)
    if not slug:
        raise ValueError("{} does not produce a valid type name.".format(
            name))
    icon_path = (spec.get("icon_path") or "").strip()
    if icon_path and not os.path.isfile(icon_path):
        raise ValueError("{}: icon image not found: {}".format(name,
                                                              icon_path))
    icon_from = (spec.get("icon_from") or "").strip().upper()
    if icon_from and not icon_from.startswith("RELIGION_"):
        raise ValueError("{}: '{}' is not a religion (its icon).".format(
            name, icon_from))
    known = ({t for t, _ in data.type_choices("religion")}
             if data.conn else set())
    if icon_from and known and icon_from not in known:
        raise ValueError("{}: the game has no religion {} (its icon)."
                         .format(name, icon_from))
    short = slug[len("RELIGION_"):]
    moments = religion_moments(spec.get("moment") or {}, name, slug,
                               icon_path)
    return {
        "id": spec.get("id") or "", "name": name, "slug": slug,
        "label": name + " (religion)",
        "name_tag": "LOC_{}_NAME".format(slug),
        "icon_path": icon_path, "icon_custom": bool(icon_path),
        "icon_from": icon_from,
        # (only for an image of its own; see add_glow)
        "icon_glow": glow_strength(spec) if icon_path else 0.0,
        "icon_opacity": icon_opacity(spec) if icon_path else 1.0,
        "icon_name": "ICON_" + slug, "icon_atlas": "ICON_ATLAS_" + slug,
        "icon_string": short.title().replace("_", ""),
        "color": _color(spec.get("color") or DEFAULT_RELIGION_COLOR, name),
        "color_type": "COLOR_" + slug,
        "exists_in_game": slug in known,
        # the "religion founded" picture of its own (none: the picture of
        # moment_from is copied; see religion_moment_sql)
        "moments": moments,
        "moment_from": icon_from or FALLBACK_RELIGION_ICON,
        # the player names it when founding it (Religions.
        # RequiresCustomName: the founding screen asks for a name)
        "renameable": bool(spec.get("renameable")),
        # its Civilopedia page's History chapter (the game makes no page
        # for a renameable religion: none then)
        "history": [] if spec.get("renameable") else history_paragraphs(
            (spec.get("pedia") or {}).get("history")),
    }


@functools.lru_cache(maxsize=32)
def sdk_texture(name):
    """A texture of the installed SDK Assets as RGBA (for previews), or
    None without them, the texture or Pillow."""
    from .fonticons import find_sdk_assets, texture_dirs
    sdk = find_sdk_assets()
    if not sdk:
        return None
    try:
        from PIL import Image
    except ImportError:
        return None
    for folder in texture_dirs(sdk):
        path = os.path.join(folder, name + ".dds")
        if os.path.isfile(path):
            try:
                with Image.open(path) as img:
                    return img.convert("RGBA")
            except Exception:           # unreadable texture
                continue
    return None


def moment_book():
    """The game's "religion founded" book picture (RGBA), read from the
    installed SDK Assets, or None (see sdk_texture)."""
    return sdk_texture(MOMENT_BOOK_TEXTURE)


def game_moment_picture(religion_type):
    """A game religion's own "religion founded" picture (166 x 122 RGBA)
    from the SDK Assets, or None: RELIGION_CUSTOM_1 ->
    PM_FoundedReligion_Custom1, as the game names them."""
    if not religion_type.startswith("RELIGION_"):
        return None
    name = "".join(part.title() for part in
                   religion_type[len("RELIGION_"):].split("_"))
    return sdk_texture("{}_{}".format(MOMENT_BOOK_TEXTURE, name))


def on_book(picture, book=None):
    """picture (RELIGION_MOMENT_SIZE RGBA) on the book where the game
    draws it, as the moment shows it; None without the book (see
    moment_book)."""
    book = book if book is not None else moment_book()
    if book is None:
        return None
    out = book.copy()
    x = (out.width - picture.width) // 2 + MOMENT_PAGE_OFFSET[0]
    y = (out.height - picture.height) // 2 + MOMENT_PAGE_OFFSET[1]
    out.alpha_composite(picture.convert("RGBA"), (x, y))
    return out


def religion_moments(moment, name, slug, icon_path):
    """The moment contexts (see moments.normalize_moments; [] or one) of
    a religion's "religion founded" picture: its own image, or (automatic)
    its icon image drawn in ink. Without either it copies another
    religion's picture. Raises ValueError."""
    path = (moment.get("path") or "").strip()
    if path and not os.path.isfile(path):
        raise ValueError("{}: historic moment image not found: {}".format(
            name, path))
    if not path and not icon_path:
        return []
    return [dict({"item": slug, "illustration": MOMENT_RELIGION[0],
                  "data_type": MOMENT_RELIGION[1], "path": path,
                  # (automatic: drawn from the icon image, with its angle,
                  # size and place - see ink_settings)
                  "ink": "" if path else icon_path,
                  "texture": "MOMENT_" + slug, "size": RELIGION_MOMENT_SIZE,
                  "mask": bool(path and moment.get("mask")),
                  "half": bool(path and moment.get("half")),
                  "sepia": bool(path and moment.get("sepia"))},
                 **ink_settings(moment))]


def religion_moment_sql(r):
    """The "religion founded" picture of a religion without one of its
    own (or whose picture could not be cooked): a copy of moment_from's
    row. "" if it has its own (see modbuild.build_moments_sql)."""
    if r["moments"]:
        return ""
    return ("-- {name}: the historic moment picture of {source}\n"
            "INSERT OR REPLACE INTO MomentIllustrations\n"
            "    (MomentIllustrationType, MomentDataType, GameDataType, "
            "Texture)\n"
            "SELECT MomentIllustrationType, MomentDataType, {slug}, Texture "
            "FROM MomentIllustrations\n"
            "WHERE GameDataType = {source_s} AND MomentIllustrationType = "
            "{kind};\n").format(
                name=r["name"], source=r["moment_from"],
                slug=sql_str(r["slug"]), source_s=sql_str(r["moment_from"]),
                kind=sql_str(MOMENT_RELIGION[0]))


def religion_sql(r):
    """Gameplay SQL of one religion. A renameable one has
    RequiresCustomName: the founding screen asks the player for its name
    (as for the game's RELIGION_CUSTOM_* religions)."""
    return """-----------------------------------------------
-- {name} ({slug}), a new {what}religion
-----------------------------------------------
INSERT INTO Types (Type, Kind)
VALUES ({slug_s}, 'KIND_RELIGION');

INSERT INTO Religions (ReligionType, Name, IconString, Pantheon, RequiresCustomName, Color)
VALUES ({slug_s}, {name_tag}, {icon_string}, 0, {custom}, {color});
""".format(name=r["name"], slug=r["slug"], slug_s=sql_str(r["slug"]),
           what="renameable " if r.get("renameable") else "",
           name_tag=sql_str(r["name_tag"]),
           icon_string=sql_str(r["icon_string"]),
           custom=1 if r.get("renameable") else 0,
           color=sql_str(r["color_type"]))


def religion_text_rows(r):
    """[(tag, English text)] of one religion: its name and its
    Civilopedia page's History paragraphs (the game makes a page for
    every religion; it shows the paragraphs whose tags exist)."""
    page = "LOC_PEDIA_RELIGIONS_PAGE_{}_CHAPTER_HISTORY_PARA_".format(
        r["slug"])
    return [(r["name_tag"], r["name"])] + [
        (page + str(i), loc_text(p))
        for i, p in enumerate(r.get("history") or [], 1)]


def religion_icons_sql(r):
    """IconDefinitions rows copying another religion's icon (when the
    religion has no icon of its own). The game defines each religion icon
    twice - in the small icons' atlas and in a 270 pixel one - so every
    row is copied."""
    if r["icon_custom"]:
        return ""
    source = "ICON_" + (r["icon_from"] or FALLBACK_RELIGION_ICON)
    return ("-- {name}: the icon of {source}\n"
            "INSERT OR REPLACE INTO IconDefinitions (Name, Atlas, \"Index\")\n"
            "SELECT {icon}, Atlas, \"Index\" FROM IconDefinitions "
            "WHERE Name = {source_s};\n").format(
                name=r["name"], source=source, icon=sql_str(r["icon_name"]),
                source_s=sql_str(source))


def religion_color_row(r):
    """The Colors row (XML) of one religion's color."""
    return "    <Row><Type>{}</Type><Color>{},{},{},255</Color></Row>".format(
        r["color_type"], *r["color"])


def religion_icon_preview(spec, size):
    """The religion's icon on a badge of its color (size x size RGBA),
    or a placeholder with its initials in its color. Raises ImportError
    without Pillow."""
    from .art import placeholder_icon
    from .civs import civ_icon_preview
    try:
        color = tuple(int(v) for v in spec.get("color") or ())[:3]
    except (TypeError, ValueError):
        color = ()
    if len(color) != 3:
        color = DEFAULT_RELIGION_COLOR
    path = (spec.get("icon_path") or "").strip()
    if not (path and os.path.isfile(path)):
        return placeholder_icon(spec.get("name"), color, (255, 255, 255),
                                size)
    strength, opacity = glow_strength(spec), icon_opacity(spec)
    if not strength and opacity >= 1:
        return civ_icon_preview(spec, size, badge=color)
    from PIL import Image, ImageDraw
    from .art import _cached

    def make():
        inner = max(1, int(round(size * 0.72)))
        icon = glowing_icon(path, inner, strength, opacity)
        ss = 4                          # supersampled, for a smooth edge
        disc = Image.new("RGBA", (size * ss, size * ss), (0, 0, 0, 0))
        ImageDraw.Draw(disc).ellipse((0, 0, size * ss - 1, size * ss - 1),
                                     fill=color + (255,))
        out = disc.resize((size, size), Image.LANCZOS)
        out.alpha_composite(icon, ((size - inner) // 2, (size - inner) // 2))
        return out
    try:
        icon = _cached(("religion_icon", size, color, strength, opacity),
                       path, make)
        if icon is not None:
            return icon
    except Exception:                   # unreadable image
        pass
    return placeholder_icon(spec.get("name"), color, (255, 255, 255), size)
