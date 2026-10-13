"""Images: DDS conversion, cooking .blp packages, icons, previews."""

import os
import shutil
import struct
import subprocess

from .util import steam_libraries, xml_escape
from .artdefs import FALLBACK_ARTDEF, build_fallback_artdef


ICON_SIZES = [32, 45, 48, 50, 55, 64, 80, 256]


# ---------------------------------------------------------------------------
# DDS writing (uncompressed 32-bit RGBA; no external tools needed)
# ---------------------------------------------------------------------------

def write_dds(path, width, height, levels):
    """Write an uncompressed DDS file (32bpp RGBA).

    levels: pixel data of the base image followed by any mipmaps (each
    half the size of the previous, minimum 1 pixel).

    Layout: magic + dwSize, dwFlags, dwHeight, dwWidth, dwPitch, dwDepth,
    dwMipMapCount, dwReserved1[11], pixel format (32 bytes), 5 caps DWORDs.
    Total header (incl. magic) = 128 bytes. Mirrors Firaxis' own source
    textures (e.g. the SDK leader template).

    Byte order must be R,G,B,A (red mask 0xFF), like Firaxis' own source
    textures: the asset cooker ignores the channel masks and copies the
    bytes straight into PF_R8G8B8A8_UNORM, so BGRA data comes out with
    red and blue swapped.
    """
    DDSD_CAPS, DDSD_HEIGHT, DDSD_WIDTH, DDSD_PITCH, DDSD_PIXELFORMAT = (
        0x1, 0x2, 0x4, 0x8, 0x1000)
    DDSD_MIPMAPCOUNT = 0x20000
    DDPF_ALPHAPIXELS, DDPF_RGB = 0x1, 0x40
    DDSCAPS_COMPLEX, DDSCAPS_TEXTURE, DDSCAPS_MIPMAP = 0x8, 0x1000, 0x400000

    flags = DDSD_CAPS | DDSD_HEIGHT | DDSD_WIDTH | DDSD_PIXELFORMAT
    caps = DDSCAPS_TEXTURE
    if len(levels) > 1:
        flags |= DDSD_MIPMAPCOUNT
        caps |= DDSCAPS_COMPLEX | DDSCAPS_MIPMAP
        pitch, mip_count = 0, len(levels)
    else:
        flags |= DDSD_PITCH
        pitch, mip_count = width * 4, 0
    hdr = struct.pack("<4s7I", b"DDS ", 124, flags, height, width,
                      pitch, 0, mip_count)
    hdr += b"\x00" * 44                                   # dwReserved1[11]
    hdr += struct.pack("<2I4s5I", 32, DDPF_RGB | DDPF_ALPHAPIXELS,
                       b"\x00\x00\x00\x00",
                       32, 0x000000FF, 0x0000FF00, 0x00FF0000, 0xFF000000)
    hdr += struct.pack("<5I", caps, 0, 0, 0, 0)
    with open(path, "wb") as fh:
        fh.write(hdr)
        for data in levels:
            fh.write(data)


def convert_image_to_dds(src, dst, size=None, mips=False):
    """Convert any Pillow-readable image to DDS, optionally center-cropped
    and resized (size: int for a square, or (width, height)), optionally
    with a full mipmap chain.
    Returns (width, height, mipmap count excluding the base level), or
    None when Pillow is not installed."""
    try:
        from PIL import Image
    except ImportError:
        return None
    img = Image.open(src).convert("RGBA")
    if size:
        # int: square; (w, h): that size. Centre-crop to the target aspect
        # first so nothing is stretched.
        tw, th = (size, size) if isinstance(size, int) else size
        w, h = img.size
        if w * th > h * tw:                       # too wide
            cw, ch = h * tw // th, h
        else:                                     # too tall (or exact)
            cw, ch = w, w * th // tw
        left, top = (w - cw) // 2, (h - ch) // 2
        img = img.crop((left, top, left + cw, top + ch))
        img = img.resize((tw, th), Image.LANCZOS)
    width, height = img.size
    levels = [img.tobytes()]                                 # RGBA order
    if mips:
        w, h = width, height
        while w > 1 or h > 1:
            w, h = max(1, w // 2), max(1, h // 2)
            levels.append(img.resize((w, h), Image.BOX).tobytes())
    write_dds(dst, width, height, levels)
    return width, height, len(levels) - 1


# ---------------------------------------------------------------------------
# Art cooking (SDK asset cooker -> .blp packages the game can load)
# ---------------------------------------------------------------------------
# The game only loads textures from cooked .blp packages, never loose
# .dds files. We therefore write a tiny art "pantry" (textures + .tex
# descriptors + .xlp package lists + artdefs) to a temp folder and run
# the SDK's asset cooker on it, exactly like ModBuddy does, then reference
# the results from a .dep file loaded by UpdateArt.
#
# Two kinds of texture are produced:
#   * UI textures (icons, loading screen, setup portrait) in a UITexture
#     package, looked up by texture name.
#   * Leader fallbacks (the 2D image the diplomacy screen shows for
#     leaders without a 3D scene) in a LeaderFallback package, mapped to
#     the leader type by FallbackLeaders.artdef.

COOKER_EXE = "Civ6AssetCooker_FinalRelease.exe"
COOKER_PLATFORMS = ("Windows", "MacOS")

# Per-kind texture settings, as the Asset Editor writes them.
TEXTURE_KINDS = {
    "ui": {
        "xlp_class": "UITexture", "class_name": "UserInterface",
        "tags": ["UserInterface"], "filter": "FT_LANCZOS6", "mips": False,
        "cook_params": """
			<Element class="AssetObjects::BoolValue">
				<m_bValue>false</m_bValue>
				<m_ParamName text="IsScalable"/>
			</Element>
			<Element class="AssetObjects::IntValue">
				<m_nValue>2</m_nValue>
				<m_ParamName text="TexturePadding"/>
			</Element>
			<Element class="AssetObjects::BoolValue">
				<m_bValue>false</m_bValue>
				<m_ParamName text="IsStandalone"/>
			</Element>
			<Element class="AssetObjects::BoolValue">
				<m_bValue>false</m_bValue>
				<m_ParamName text="IsTiled"/>
			</Element>
		""",
    },
    "fallback": {
        "xlp_class": "LeaderFallback", "class_name": "Leader_Fallback",
        "tags": ["Leader_Fallback", "Leader", "Fallback"],
        "filter": "FT_BOX", "mips": True, "cook_params": "",
    },
}


def find_cooker():
    """Locate the Civ VI SDK asset cooker in any Steam library."""
    for lib in steam_libraries():
        path = os.path.join(lib, "steamapps", "common",
                            "Sid Meier's Civilization VI SDK",
                            "AssetModTools", "Cooker", COOKER_EXE)
        if os.path.isfile(path):
            return path
    return None


TEX_TEMPLATE = """<?xml version="1.0" encoding="UTF-8" ?>
<AssetObjects::TextureInstance>
	<m_ExportSettings>
		<ePixelformat>PF_R8G8B8A8_UNORM</ePixelformat>
		<eFilterType>{filter}</eFilterType>
		<bUseMips>{use_mips}</bUseMips>
		<iNumManualMips>0</iNumManualMips>
		<bCompleteMipChain>false</bCompleteMipChain>
		<fValueClampMin>0.000000</fValueClampMin>
		<fValueClampMax>1.000000</fValueClampMax>
		<fSupportScale>1.000000</fSupportScale>
		<fGammaIn>2.200000</fGammaIn>
		<fGammaOut>2.200000</fGammaOut>
		<iSlabWidth>0</iSlabWidth>
		<iSlabHeight>0</iSlabHeight>
		<iColorKeyX>64</iColorKeyX>
		<iColorKeyY>64</iColorKeyY>
		<iColorKeyZ>64</iColorKeyZ>
		<eExportMode>TEXTURE_2D</eExportMode>
		<bSampleFromTopLayer>false</bSampleFromTopLayer>
	</m_ExportSettings>
	<m_CookParams>
		<m_Values>{cook_params}</m_Values>
	</m_CookParams>
	<m_Version>
		<major>4</major>
		<minor>0</minor>
		<build>253</build>
		<revision>293</revision>
	</m_Version>
	<m_Height>{height}</m_Height>
	<m_Width>{width}</m_Width>
	<m_Depth>1</m_Depth>
	<m_NumMipMaps>{num_mips}</m_NumMipMaps>
	<m_SourceFilePath text="{source}"/>
	<m_SourceObjectName text=""/>
	<m_ImportedTime>0</m_ImportedTime>
	<m_ExportedTime>0</m_ExportedTime>
	<m_ClassName text="{class_name}"/>
	<m_DataFiles>
		<Element>
			<m_ID text="DDS"/>
			<m_RelativePath text="{name}.dds"/>
		</Element>
	</m_DataFiles>
	<m_Name text="{name}"/>
	<m_Description text=""/>
	<m_Tags>
{tags}
	</m_Tags>
	<m_Groups/>
</AssetObjects::TextureInstance>
"""


def add_texture(pantry, name, src, kind="ui", size=None):
    """Convert src into pantry/Textures/<name>.dds plus its .tex
    descriptor. Returns False when Pillow is not installed."""
    settings = TEXTURE_KINDS[kind]
    tex_dir = os.path.join(pantry, "Textures")
    os.makedirs(tex_dir, exist_ok=True)
    result = convert_image_to_dds(src, os.path.join(tex_dir, name + ".dds"),
                                  size=size, mips=settings["mips"])
    if not result:
        return False
    width, height, num_mips = result
    with open(os.path.join(tex_dir, name + ".tex"), "w",
              encoding="utf-8", newline="\n") as fh:
        fh.write(TEX_TEMPLATE.format(
            width=width, height=height, name=name, source=xml_escape(src),
            filter=settings["filter"], num_mips=num_mips,
            use_mips="true" if settings["mips"] else "false",
            cook_params=settings["cook_params"],
            class_name=settings["class_name"],
            tags="\n".join('\t\t<Element text="{}"/>'.format(t)
                           for t in settings["tags"])))
    return True


def atlas_image(paths, size):
    """Images side by side in one row of size x size cells (an icon
    atlas, like the template mod's unit atlas: portrait, then icon). Each
    image is centre-cropped to a square and fitted to its cell. Returns
    an RGBA image."""
    from PIL import Image, ImageOps
    out = Image.new("RGBA", (size * len(paths), size), (0, 0, 0, 0))
    for i, path in enumerate(paths):
        img = Image.open(path).convert("RGBA")
        out.alpha_composite(ImageOps.fit(img, (size, size), Image.LANCZOS),
                            (i * size, 0))
    return out


def build_xlp(xlp_class, package, texture_names):
    entries = "\n".join(
        "\t\t<Element>\n"
        "\t\t\t<m_EntryID text=\"{0}\"/>\n"
        "\t\t\t<m_ObjectName text=\"{0}\"/>\n"
        "\t\t</Element>".format(n) for n in texture_names)
    return """<?xml version="1.0" encoding="UTF-8" ?>
<AssetObjects..XLP>
	<m_Version>
		<major>4</major>
		<minor>0</minor>
		<build>253</build>
		<revision>293</revision>
	</m_Version>
	<m_ClassName text="{xlp_class}"/>
	<m_PackageName text="{package}"/>
	<m_Entries>
{entries}
	</m_Entries>
	<m_AllowedPlatforms>
		<Element>WINDOWS</Element>
		<Element>LINUX</Element>
		<Element>MACOS</Element>
		<Element>IOS</Element>
	</m_AllowedPlatforms>
</AssetObjects..XLP>
""".format(xlp_class=xlp_class, package=package, entries=entries)


def run_cooker(cooker, args, report, what, cwd=None):
    """Run the asset cooker with ModBuddy's standard arguments.
    Returns True when it reports success. The cooker writes cooker.log
    into its working directory, so pass the (temporary) pantry as cwd."""
    cooker_dir = os.path.dirname(cooker)
    # Same command lines ModBuddy's Civ6.targets uses.
    cmd = ([cooker, "--absolute_paths", "--no_mt"] + args[:-1] +
           ["--shaders", cooker_dir,
            "--config", os.path.join(cooker_dir, "Civ6.cfg"), args[-1]])
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, errors="replace",
            timeout=600, cwd=cwd, creationflags=getattr(subprocess,
                                               "CREATE_NO_WINDOW", 0))
        output = proc.stdout + proc.stderr
    except (OSError, subprocess.SubprocessError) as exc:
        output = str(exc)
    if "cook completed with success" not in output:
        report.append("WARNING: cooking {} failed:".format(what))
        report.extend("    " + line for line in output.splitlines()[-15:])
        return False
    report.append("cooked " + what)
    return True


def cook_art(cooker, pantry, packages, fallbacks, mod_dir, report):
    """Cook the texture packages and write the fallback artdef (if any).

    packages: {package name: (texture kind, [texture names])}
    fallbacks: (leader type, {mood slot: fallback texture name}) pairs
    Writes mod_dir/Platforms/*/BLPs/*.blp and mod_dir/ArtDefs/*.artdef.
    Returns the mod-relative paths of all cooked files ([] on failure)."""
    pantry_arg = os.path.join(pantry, "")
    xlp_dir = os.path.join(pantry, "XLPs")
    os.makedirs(xlp_dir, exist_ok=True)
    xlps = []
    for package, (kind, names) in sorted(packages.items()):
        path = os.path.join(xlp_dir, package + ".xlp")
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(build_xlp(TEXTURE_KINDS[kind]["xlp_class"], package,
                               names))
        xlps.append((package, path))

    for sub in ("Platforms", "ArtDefs"):               # drop stale output
        shutil.rmtree(os.path.join(mod_dir, sub), ignore_errors=True)

    for platform in COOKER_PLATFORMS:
        stewpot = os.path.join(mod_dir, "Platforms", platform, "BLPs")
        os.makedirs(stewpot, exist_ok=True)
        for package, xlp in xlps:
            ok = run_cooker(
                cooker, ["--mode", "XLP", "--platform", platform,
                         "--pantry", pantry_arg, "--stewpot", stewpot, xlp],
                report, "{}.blp for {}".format(package, platform),
                cwd=pantry)
            if not ok or not os.path.isfile(
                    os.path.join(stewpot, package + ".blp")):
                return []

    if fallbacks:
        # Written in cooked form directly: the command-line cooker cannot
        # cook artdefs outside ModBuddy, and cooking only changes the
        # BLPEntryValue class separator ("::" -> ".."), as a diff of the
        # SDK template's source and cooked FallbackLeaders.artdef shows.
        fallback_package = next(p for p, (kind, _) in packages.items()
                                if kind == "fallback")
        artdef_dir = os.path.join(mod_dir, "ArtDefs")
        os.makedirs(artdef_dir, exist_ok=True)
        with open(os.path.join(artdef_dir, FALLBACK_ARTDEF), "w",
                  encoding="utf-8", newline="\n") as fh:
            fh.write(build_fallback_artdef(fallback_package, fallbacks))
        report.append("wrote ArtDefs/" + FALLBACK_ARTDEF)

    cooked = []
    for sub in ("Platforms", "ArtDefs"):
        for dirpath, _, filenames in os.walk(os.path.join(mod_dir, sub)):
            for fname in filenames:
                rel = os.path.relpath(os.path.join(dirpath, fname), mod_dir)
                cooked.append(rel.replace(os.sep, "/"))
    return sorted(cooked)


# ---------------------------------------------------------------------------
# Leader icon cut out of the loading portrait
# ---------------------------------------------------------------------------

DEFAULT_ICON_BORDER_COLOR = (0, 0, 0)     # black
DEFAULT_ICON_BORDER_WIDTH = 5                 # pixels at 256 x 256


PORTRAIT_SIZE = (800, 1080)     # every loading portrait is fitted to this


def _portrait_placement(width, height):
    """(scale, left, top) that fits a width x height image inside
    PORTRAIT_SIZE, centred horizontally and resting on the bottom edge."""
    pw, ph = PORTRAIT_SIZE
    scale = min(pw / float(width), ph / float(height))
    w, h = max(1, int(round(width * scale))), max(1, int(round(height * scale)))
    return scale, (pw - w) // 2, ph - h


def fit_portrait(src):
    """The loading portrait at src as a PORTRAIT_SIZE RGBA image: scaled to
    fit (aspect kept), centred horizontally, aligned to the bottom, with a
    transparent margin."""
    from PIL import Image
    img = Image.open(src).convert("RGBA")
    scale, left, top = _portrait_placement(*img.size)
    size = (max(1, int(round(img.width * scale))),
            max(1, int(round(img.height * scale))))
    out = Image.new("RGBA", PORTRAIT_SIZE, (0, 0, 0, 0))
    out.alpha_composite(img.resize(size, Image.LANCZOS), (left, top))
    return out


def fit_icon_crop(crop, src):
    """Convert an icon crop chosen on the unfitted portrait at src (projects
    from before portraits were fitted) to fitted-portrait pixels."""
    from PIL import Image
    scale, left, top = _portrait_placement(*Image.open(src).size)
    cx, cy, r = crop
    return (cx * scale + left, cy * scale + top, r * scale)


def default_icon_crop(width, height):
    """(center x, center y, radius) in source pixels. Faces usually sit
    in the upper part of a leader portrait."""
    r = min(width, height) * 0.3
    return (width / 2.0, max(r, min(height * 0.35, height - r)), r)


def default_image_crop(img):
    """default_icon_crop for a Pillow image, within its non-transparent
    part (a fitted portrait can have transparent margins)."""
    left, top, right, bottom = (img.getchannel("A").getbbox()
                                if img.mode == "RGBA" else None) or         (0, 0) + img.size
    cx, cy, r = default_icon_crop(right - left, bottom - top)
    return (cx + left, cy + top, r)


def make_circle_icon(src, crop, border_color=DEFAULT_ICON_BORDER_COLOR,
                     border_width=DEFAULT_ICON_BORDER_WIDTH, size=512):
    """Cut a circle out of an image and put a border ring around it.

    src: a path or a Pillow image. crop: (center x, center y, radius) in
    source pixels, or None for default_icon_crop. border_width is in
    pixels of a 256 x 256 icon and scales with size. Areas of the circle
    outside the image stay transparent. Returns a size x size RGBA image
    with transparent corners."""
    from PIL import Image, ImageChops, ImageDraw
    img = src if isinstance(src, Image.Image) else \
        Image.open(src).convert("RGBA")
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    cx, cy, r = crop or default_image_crop(img)
    box = tuple(int(round(v)) for v in (cx - r, cy - r, cx + r, cy + r))
    face = img.crop(box).resize((size, size), Image.LANCZOS)   # pads out of
                                                               # bounds with 0
    ss = 4                                     # supersampling for smooth edges
    big = size * ss

    def disc(inset=0.0):
        mask = Image.new("L", (big, big), 0)
        ImageDraw.Draw(mask).ellipse(
            (inset, inset, big - 1 - inset, big - 1 - inset), fill=255)
        return mask

    outer = disc()
    face.putalpha(ImageChops.multiply(face.getchannel("A"),
                                      outer.resize((size, size),
                                                   Image.LANCZOS)))
    if border_width <= 0:
        return face
    ring = ImageChops.subtract(outer, disc(border_width * size / 256.0 * ss))
    ring = ring.resize((size, size), Image.LANCZOS)
    color = Image.new("RGBA", (size, size), tuple(border_color) + (255,))
    # outside the circle the face is transparent, so the ring's
    # anti-aliased outer edge blends into transparency
    return Image.composite(color, face, ring)


APP_ICON = "icon.png"
DIPLO_BG_MASK = "mask.png"
MOMENT_MASK = "mask_historical.png"
MOMENT_HALF_OPACITY = 0.75
# the loading background a leader can use instead of an image of its own
DEFAULT_LOAD_BG = "bg_loading_default.png"


def shift_hue(img, degrees):
    """img (a Pillow image) with every color's hue turned by degrees
    (-180..180) on the color wheel; brightness, saturation and
    transparency stay. Returns an RGBA image."""
    from PIL import Image
    img = img.convert("RGBA")
    turn = int(round(degrees % 360 * 256 / 360.0)) % 256
    if not turn:
        return img
    h, s, v = img.convert("RGB").convert("HSV").split()
    h = h.point(lambda x: (x + turn) % 256)
    out = Image.merge("HSV", (h, s, v)).convert("RGB").convert("RGBA")
    out.putalpha(img.getchannel("A"))
    return out


SEPIA_TONES = ("#2b1d0e", "#8c6a43", "#f4e6c8")   # shadows, mid, highlights


def apply_image_mask(src, mask_path, size=None, opacity=1.0, sepia=False):
    """Fade an image out with a greyscale mask: white keeps the image,
    black makes it transparent, grey partially. The image is centre-cropped
    and resized to size (default: the mask's size); the mask is stretched
    to that size, since it acts as a frame. mask_path may be None to only
    apply opacity (0..1, multiplies the alpha). sepia recolours the image
    in SEPIA_TONES. Returns an RGBA image."""
    from PIL import Image, ImageChops, ImageOps
    mask = Image.open(mask_path).convert("L") if mask_path else None
    size = tuple(size or mask.size)
    img = ImageOps.fit(Image.open(src).convert("RGBA"), size, Image.LANCZOS)
    alpha = img.getchannel("A")
    if sepia:
        dark, mid, light = SEPIA_TONES
        img = ImageOps.colorize(img.convert("L"), black=dark, white=light,
                                mid=mid).convert("RGBA")
    if mask is not None:
        alpha = ImageChops.multiply(alpha, mask.resize(size, Image.LANCZOS))
    if opacity < 1.0:
        alpha = alpha.point(lambda a: int(round(a * opacity)))
    img.putalpha(alpha)
    return img


# ---------------------------------------------------------------------------
# Previews (Pillow images for the GUI; cached, since sources can be large)
# ---------------------------------------------------------------------------

PREVIEW_BACKDROP = (43, 43, 43, 255)
PREVIEW_BOX = (208, 117)                  # 16:9, like the screens
LIST_ICON_SIZE = 32
_preview_cache = {}


def _cached(key_parts, path, make):
    """make() cached on key_parts plus the file's modification time, so an
    edited image is picked up again."""
    try:
        key = key_parts + (os.path.abspath(path), os.path.getmtime(path))
    except OSError:
        return None
    if key not in _preview_cache:
        if len(_preview_cache) > 200:
            _preview_cache.clear()
        _preview_cache[key] = make()
    return _preview_cache[key]


def fitted_portrait(path):
    """fit_portrait(path), cached. Raises ImportError without Pillow."""
    return _cached(("portrait",), path, lambda: fit_portrait(path))


def preview_image(path, box, mask_path=None, portrait=False, hue=0):
    """The image at path fitted into box (w, h) and centred on a dark
    backdrop of that size, so transparency shows. With mask_path the image
    is faded out with that mask first (cropped to the mask's aspect, like
    the generated texture). portrait: show path fitted like a loading
    portrait (fit_portrait). Returns an RGBA image or None if path is not
    a file. hue: turn the colors by that many degrees (see shift_hue).
    Raises ImportError without Pillow."""
    from PIL import Image
    if not path or not os.path.isfile(path):
        return None

    def make():
        if mask_path:
            mw, mh = Image.open(mask_path).size
            scale = min(box[0] / float(mw), box[1] / float(mh))
            img = apply_image_mask(path, mask_path,
                                   size=(max(1, int(mw * scale)),
                                         max(1, int(mh * scale))))
        elif portrait:
            img = fitted_portrait(path).copy()
            img.thumbnail(box, Image.LANCZOS)
        else:
            img = Image.open(path)
            img.draft("RGB", box)       # fast JPEG downscale on load
            img = img.convert("RGBA")
            img.thumbnail(box, Image.LANCZOS)
        if hue:
            img = shift_hue(img, hue)
        out = Image.new("RGBA", tuple(box), PREVIEW_BACKDROP)
        out.alpha_composite(img, ((box[0] - img.width) // 2,
                                  (box[1] - img.height) // 2))
        return out
    return _cached(("preview", tuple(box), mask_path, portrait, hue), path,
                   make)


def placeholder_icon(name, primary, secondary, size):
    """A round icon in the leader's colors with their initials, for leaders
    whose icon is inherited from the original leader."""
    from PIL import Image, ImageDraw, ImageFont
    ss = 4
    big = size * ss
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((0, 0, big - 1, big - 1), fill=tuple(secondary))
    inset = max(ss, big // 16)
    draw.ellipse((inset, inset, big - 1 - inset, big - 1 - inset),
                 fill=tuple(primary))
    initials = "".join(w[0] for w in (name or "?").split()[:2]).upper()
    try:
        font = ImageFont.load_default(size=int(big * 0.4))
        draw.text((big / 2.0, big / 2.0), initials, fill=tuple(secondary),
                  font=font, anchor="mm")
    except (TypeError, ValueError):     # old Pillow: no scalable font
        pass
    return img.resize((size, size), Image.LANCZOS)
