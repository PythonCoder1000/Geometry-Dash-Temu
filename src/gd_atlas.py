"""Reader for official Geometry Dash cocos2d texture atlases.

The sheets live in ``assets/sprites/gd_official/`` as ``GJ_GameSheet*.png``
plus a paired ``.plist`` frame index.  They are RobTop Games' copyrighted
art, are gitignored, and are strictly a LOCAL asset: the game runs fine
without them (``sprites.py`` falls back to its procedural renderers), so
nothing here may raise when a sheet is missing.

Format notes (TexturePacker "format 3", what cocos2d ships):
  * ``textureRect``      ``{{x,y},{w,h}}`` — where the pixels live in the
    atlas.  When ``textureRotated`` is set the packer stored the sprite
    turned 90° clockwise, so the region on the atlas is ``(h, w)`` and
    the crop needs un-rotating before use.
  * ``spriteSize``       size of the *trimmed* pixels.
  * ``spriteSourceSize`` size of the untrimmed logical sprite.
  * ``spriteOffset``     centre of the trimmed box relative to the centre
    of the untrimmed box, in cocos coordinates (y points **up**).

``compose`` reassembles a trimmed frame back onto its untrimmed box and
scales that at this engine's cell scale — returning a canvas LARGER than
one cell for the art GD itself draws bigger than a cell (portals, saws,
speed arrows), so those overhang their placement cell the way they do in
the real game instead of being cropped or shrunk to fit.
"""

import math
import os
import plistlib
import re

import pygame

from .constants import ASSETS_DIR

GD_SHEETS_DIR = os.path.join(ASSETS_DIR, "sprites", "gd_official")

# GD ships its backgrounds and ground tiles as loose PNGs rather than
# atlas frames, so they need no plist at all — just the same "may be
# missing, never raise" contract as the sheets.
GD_BACKGROUNDS_DIR = os.path.join(GD_SHEETS_DIR, "backgrounds")
GD_GROUNDS_DIR = os.path.join(GD_SHEETS_DIR, "grounds")

# One Geometry Dash grid cell is 30 texture pixels on the base-resolution
# sheets. Everything scales relative to that so a 30x30 frame lands
# exactly on this engine's CELL square.
#
# GD also ships each sheet at higher densities under a filename suffix,
# packing the SAME frame names at a multiple of that unit — so the unit
# is a property of the SHEET, not a property of the game, and resolving
# it per sheet is what lets a base and an -hd sheet coexist without one
# of them silently rendering at the wrong scale.
GD_UNIT_PX = 30

# Resolution tiers, best first: GD's own suffix convention, where the
# plain name is 1x and "-hd" is 2x.  A tier only counts as installed when
# BOTH its PNG and its plist are present, so a half-finished download
# falls through to the next tier instead of loading a mismatched pair.
#
# At this engine's CELL=50 the -hd sheets are DOWNSCALED (60 -> 50 px per
# cell) where the base sheets had to be upscaled (30 -> 50); downsampling
# keeps detail that upsampling can only interpolate, which is the whole
# reason the tier exists.  Base sheets remain a working middle tier for a
# checkout that only has them, and no sheets at all still falls back to
# the procedural renderers in sprites.py.
SHEET_TIERS = (("-hd", 2), ("", 1))

_POINT_RE = re.compile(r"-?\d+(?:\.\d+)?")

_sheet_variant_cache = {}  # logical sheet -> best installed variant name
_frame_index_cache = {}   # sheet -> {name: spec} or None when unavailable
_sheet_surface_cache = {}  # sheet -> Surface or None
_frame_surface_cache = {}  # (sheet, name) -> Surface
_loose_surface_cache = {}  # (directory, name) -> Surface or None


def parse_numbers(value):
    """Pull the numbers out of a cocos ``{x,y}`` / ``{{x,y},{w,h}}`` string."""
    return [float(n) for n in _POINT_RE.findall(value or "")]


def sheet_paths(sheet):
    """``(png_path, plist_path)`` for an EXACT sheet name.

    Takes the name literally — :func:`resolve_sheet` is what turns a
    logical name into the variant that is actually installed, and it
    calls this to test each candidate.
    """
    base = os.path.join(GD_SHEETS_DIR, sheet)
    return base + ".png", base + ".plist"


def has_explicit_tier(sheet):
    """True when ``sheet`` already names a resolution tier itself."""
    return any(suffix and sheet.endswith(suffix) for suffix, _ in SHEET_TIERS)


def sheet_unit_px(sheet):
    """Texture pixels per GD grid unit on ``sheet``.

    30 for a base sheet, 60 for an ``-hd`` one.  Read off the filename
    rather than measured, because the suffix IS GD's declaration of the
    density and every frame on a sheet shares it.
    """
    for suffix, scale in SHEET_TIERS:
        if suffix and sheet.endswith(suffix):
            return GD_UNIT_PX * scale
    return GD_UNIT_PX


def resolve_sheet(sheet):
    """The highest-resolution installed variant of a logical sheet name.

    Every call site names sheets logically (``"GJ_GameSheet02"``); this
    is the single point that decides which file that actually reads, so
    adding a resolution tier needs no change anywhere else.  Falls back
    to the name as given when nothing is installed, which leaves the
    frame index ``None`` and hands the caller to the procedural path.
    """
    cached = _sheet_variant_cache.get(sheet)
    if cached is not None:
        return cached
    actual = sheet
    if not has_explicit_tier(sheet):
        for suffix, _ in SHEET_TIERS:
            candidate = sheet + suffix
            if all(os.path.isfile(p) for p in sheet_paths(candidate)):
                actual = candidate
                break
    _sheet_variant_cache[sheet] = actual
    return actual


def sheet_unit_scale(sheet):
    """Texture pixels per BASE GD pixel on the installed ``sheet``.

    1.0 on a base sheet, 2.0 on ``-hd``.  Only needed by callers that
    read raw frame pixels via :func:`frame_surface` and compare them
    against a length written in base GD units; everything going through
    :func:`compose` is already resolution-independent.
    """
    return sheet_unit_px(resolve_sheet(sheet)) / GD_UNIT_PX


def load_frame_index(sheet):
    """``{frame_name: spec}`` for one sheet, or ``None`` when unavailable.

    ``spec`` carries the already-parsed numeric fields:
    ``texture_rect`` (x, y, w, h), ``sprite_size``, ``sprite_offset``,
    ``sprite_source_size`` and ``rotated``.

    ``sheet`` is a logical name; the installed tier is resolved here.
    """
    sheet = resolve_sheet(sheet)
    if sheet in _frame_index_cache:
        return _frame_index_cache[sheet]
    png_path, plist_path = sheet_paths(sheet)
    index = None
    if os.path.isfile(png_path) and os.path.isfile(plist_path):
        try:
            with open(plist_path, "rb") as fh:
                raw = plistlib.load(fh)
            index = {}
            for name, entry in raw.get("frames", {}).items():
                rect = parse_numbers(entry.get("textureRect"))
                size = parse_numbers(entry.get("spriteSize"))
                offset = parse_numbers(entry.get("spriteOffset"))
                source = parse_numbers(entry.get("spriteSourceSize"))
                if len(rect) < 4 or len(size) < 2 or len(source) < 2:
                    continue
                index[name] = {
                    "texture_rect": tuple(rect[:4]),
                    "sprite_size": tuple(size[:2]),
                    "sprite_offset": tuple(offset[:2]) if len(offset) >= 2
                                     else (0.0, 0.0),
                    "sprite_source_size": tuple(source[:2]),
                    "rotated": bool(entry.get("textureRotated")),
                }
        except (OSError, ValueError, plistlib.InvalidFileException):
            index = None
    _frame_index_cache[sheet] = index
    return index


def load_sheet_surface(sheet):
    """The atlas PNG, or ``None``.

    Deliberately skips ``convert_alpha`` — sprite baking happens before
    any display exists in some contexts (headless tests, the asset
    rebake script) and conversion needs an initialised video mode.
    """
    if sheet in _sheet_surface_cache:
        return _sheet_surface_cache[sheet]
    png_path, _ = sheet_paths(sheet)
    surface = None
    if os.path.isfile(png_path):
        try:
            surface = pygame.image.load(png_path)
        except (pygame.error, OSError):
            surface = None
    _sheet_surface_cache[sheet] = surface
    return surface


def loose_texture(directory, name):
    """A non-atlas GD PNG (a background or ground tile), or ``None``.

    These are greyscale masters that GD multiplies by the level's colour
    channel, so callers tint what they get back.
    """
    key = (directory, name)
    if key in _loose_surface_cache:
        return _loose_surface_cache[key]
    path = os.path.join(directory, name)
    surface = None
    if os.path.isfile(path):
        try:
            surface = pygame.image.load(path)
        except (pygame.error, OSError):
            surface = None
    _loose_surface_cache[key] = surface
    return surface


def atlas_installed():
    """True when at least one sheet is present, at any resolution tier."""
    return any(all(os.path.isfile(p)
                   for p in sheet_paths(resolve_sheet(sheet)))
               for sheet in ("GJ_GameSheet", "GJ_GameSheet02"))


def installed_tiers():
    """``{logical_sheet: actual_variant}`` for the sheets in use.

    Feeds the sprite-cache signature: swapping a base sheet for its -hd
    twin re-bakes every mapped sprite at a different source density, so
    the cached PNGs on disk have to be invalidated by it.
    """
    return {sheet: resolve_sheet(sheet)
            for sheet in ("GJ_GameSheet", "GJ_GameSheet02",
                          "GJ_GameSheet03", "GJ_GameSheet04")}


def frame_surface(sheet, name):
    """The trimmed, un-rotated pixels of one frame, or ``None``."""
    sheet = resolve_sheet(sheet)
    key = (sheet, name)
    if key in _frame_surface_cache:
        return _frame_surface_cache[key]
    index = load_frame_index(sheet)
    atlas = load_sheet_surface(sheet)
    result = None
    if index is not None and atlas is not None and name in index:
        spec = index[name]
        x, y, w, h = spec["texture_rect"]
        if spec["rotated"]:
            # Packed turned 90° clockwise: the atlas region is transposed,
            # and rotating the crop counter-clockwise restores it.
            region = pygame.Rect(int(x), int(y), int(h), int(w))
        else:
            region = pygame.Rect(int(x), int(y), int(w), int(h))
        region = region.clip(atlas.get_rect())
        if region.w > 0 and region.h > 0:
            crop = pygame.Surface((region.w, region.h), pygame.SRCALPHA)
            crop.blit(atlas, (0, 0), region)
            if spec["rotated"]:
                crop = pygame.transform.rotate(crop, 90)
            result = crop
    _frame_surface_cache[key] = result
    return result


def frame_source_size(sheet, name):
    """``(w, h)`` of the frame's *untrimmed* box, or ``None``.

    Multi-layer GD sprites (a player icon is a base shape plus a detail
    overlay) must be composed at one shared scale, so the caller needs
    the base layer's dimensions to pass as ``compose``'s ``unit``.
    """
    index = load_frame_index(sheet)
    if index is None or name not in index:
        return None
    return index[name]["sprite_source_size"]


# Animated frames are built at this multiple of the target size and
# scaled back down.  Surfaces can only be blitted at whole pixels, so an
# animation that changes a sprite's size a little every frame — a
# breathing orb, a turning blade — also nudges it up to half a pixel
# sideways every frame, and that sideways component reads as jitter
# rather than as the animation.  Working at 2x halves the nudge and the
# downscale spreads what is left across neighbouring pixels instead of
# snapping it.  Static frames skip this: they have nothing to jitter
# against, and a straight one-step scale from the atlas is sharper.
SUB_PIXEL_SUPERSAMPLE = 2


def cell_extent(size, src_w, src_h, fit="cell", unit=None):
    """``(w, h)`` of the canvas :func:`compose` builds for this source box.

    Never smaller than one ``size`` cell, and deliberately independent of
    ``pad``: a breathing sprite whose canvas changed size per frame would
    make the centred blit in ``draw_obj`` jitter by a pixel.
    """
    if src_w <= 0 or src_h <= 0:
        return int(size), int(size)
    if fit == "contain":
        scale = size / max(src_w, src_h)
    else:
        scale = size / (unit or GD_UNIT_PX)
    return (max(int(size), int(math.ceil(src_w * scale - 1e-6))),
            max(int(size), int(math.ceil(src_h * scale - 1e-6))))


def compose(sheet, name, size, fit="cell", anchor="center", pad=0.0,
            mirror=False, spin=0.0, unit=None):
    """Rebuild one frame as an SRCALPHA surface with its cell centred.

    ``fit`` picks how the untrimmed source box maps onto the cell:
      ``"cell"``    — 30 GD pixels == ``size`` px.  Art bigger than one
                      cell keeps its true proportions and the canvas
                      GROWS around the cell so the overhang survives
                      (GD's portals really are ~1.5 x 3 cells).
      ``"contain"`` — scale the whole source box down to fit inside one
                      cell; the canvas stays ``size`` x ``size``.

    The returned surface is therefore at least ``size`` x ``size`` but may
    be larger, always with the object's grid cell at its exact centre —
    callers must blit it centred on the cell, not at the cell's top-left.
    :func:`cell_extent` predicts that size without building the surface.

    ``unit`` overrides the per-sheet cell size assumed by ``"cell"`` (30
    source pixels on a base sheet, 60 on an ``-hd`` one): pass the same
    value for every layer of a multi-part sprite and they land on one
    another exactly as GD assembles them (each layer stays centred on the
    shared origin via its own ``spriteOffset``).  Such a value must come
    from the SAME sheet, e.g. via :func:`frame_source_size`, so it is
    already in that sheet's pixels.

    ``anchor`` is ``"center"`` or ``"bottom"`` (sprites that sit on the
    floor, e.g. jump pads, whose source box carries no cell context); the
    bottom edge meant is the *cell's*, not the grown canvas's.
    ``pad`` shrinks the drawn sprite by that fraction of ``size`` per side
    without changing the canvas size.

    ``mirror`` re-adds the horizontally-flipped half for the sprites GD
    only ships as one side (portals, and ``sawblade_01``); the flip is
    taken about the untrimmed box's centre line.  ``spin`` rotates the
    result by that many degrees about the cell centre, for the animated
    blades.

    Returns ``None`` when the frame or its sheet is unavailable, which is
    the caller's signal to fall back to the procedural renderer.
    """
    trimmed = frame_surface(sheet, name)
    if trimmed is None:
        return None
    spec = load_frame_index(sheet)[name]
    # A cell is 30 source pixels on a base sheet and 60 on an -hd one, so
    # the divisor has to come from the sheet that actually got loaded.
    # An explicit `unit` still wins: multi-layer sprites pass the base
    # layer's own source size, which is already in that sheet's pixels.
    if unit is None:
        unit = sheet_unit_px(resolve_sheet(sheet))
    src_w, src_h = spec["sprite_source_size"]
    if src_w <= 0 or src_h <= 0:
        return None
    target = cell_extent(size, src_w, src_h, fit, unit)

    if spin or pad:
        big = place_frame(trimmed, spec, size * SUB_PIXEL_SUPERSAMPLE,
                          fit, anchor, pad, mirror, unit)
        if spin:
            turned = pygame.transform.rotate(big, spin)
            holder = pygame.Surface(big.get_size(), pygame.SRCALPHA)
            holder.blit(turned,
                        turned.get_rect(center=holder.get_rect().center))
            big = holder
        return pygame.transform.smoothscale(big, target)
    return place_frame(trimmed, spec, size, fit, anchor, pad, mirror, unit)


def place_frame(trimmed, spec, size, fit, anchor, pad, mirror, unit):
    """Scale one frame's pixels onto its cell-centred canvas, no spin."""
    src_w, src_h = spec["sprite_source_size"]
    spr_w, spr_h = spec["sprite_size"]
    off_x, off_y = spec["sprite_offset"]

    usable = size * (1.0 - 2.0 * pad)
    if fit == "contain":
        scale = usable / max(src_w, src_h)
    else:
        scale = usable / (unit or GD_UNIT_PX)

    canvas_w, canvas_h = cell_extent(size, src_w, src_h, fit, unit)
    cell_x = (canvas_w - size) / 2.0
    cell_y = (canvas_h - size) / 2.0

    # Place the trimmed box inside the untrimmed box. spriteOffset is
    # centre-to-centre with y up, so the y term is subtracted.
    inner_x = (src_w - spr_w) / 2.0 + off_x
    inner_y = (src_h - spr_h) / 2.0 - off_y

    out_w = max(1, int(round(spr_w * scale)))
    out_h = max(1, int(round(spr_h * scale)))
    scaled = pygame.transform.smoothscale(trimmed, (out_w, out_h))

    canvas = pygame.Surface((canvas_w, canvas_h), pygame.SRCALPHA)
    box_x = cell_x + (size - src_w * scale) / 2.0
    if anchor == "bottom":
        box_y = cell_y + size - src_h * scale - size * pad
    else:
        box_y = cell_y + (size - src_h * scale) / 2.0

    # Round the drawn art's CENTRE rather than its top-left corner. A
    # breathing sprite moves its own left edge by a fraction of a pixel
    # every frame, and rounding that edge independently of the already
    # rounded width let the sprite TRANSLATE by up to a pixel per frame
    # instead of only changing size — which reads as random jitter, not
    # as a pulse.  Centring makes the placement depend on the sprite's
    # size alone, and for the usual zero spriteOffset it is identical
    # on every frame.
    def centred(left, top):
        return (int(round(left + spr_w * scale / 2.0 - out_w / 2.0)),
                int(round(top + spr_h * scale / 2.0 - out_h / 2.0)))

    art_y = box_y + inner_y * scale
    canvas.blit(scaled, centred(box_x + inner_x * scale, art_y))
    if mirror:
        canvas.blit(pygame.transform.flip(scaled, True, False),
                    centred(box_x + (src_w - inner_x - spr_w) * scale, art_y))
    return canvas


def clear_caches():
    """Drop parsed indexes and decoded surfaces.

    Called by ``sprites.regenerate_sprite_assets`` so a rebake picks up
    atlas files that were swapped since import — including a resolution
    tier that was installed after the first resolve.
    """
    _sheet_variant_cache.clear()
    _frame_index_cache.clear()
    _sheet_surface_cache.clear()
    _frame_surface_cache.clear()
    _loose_surface_cache.clear()
