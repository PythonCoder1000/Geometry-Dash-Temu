"""Pure geometry: object hitbox rects, rotation snapping, scale helpers.

No pygame drawing here — only ``pygame.Rect`` construction — so the
physics, the bots and the editor's hitbox overlay all read collision
shapes from one place.

Every shape is defined ONCE, in GD units, by the ``*_units`` builders in
the second half of this module.  The integer-pixel builders in the first
half are thin wrappers that scale those unit shapes by ``PX_PER_UNIT``
for the editor's hitbox overlay; they carry no independent numbers of
their own.  (They used to: both halves spelled their insets as pixel
literals against a hardcoded CELL=50, plus a private duplicate of the
px<->unit ratio, so the two families desynced the moment the render
scale moved.)
"""

import functools

import pygame

from .constants import CELL, UNITS_PER_BLOCK, PX_PER_UNIT


# ---------------------------------------------------------------------------
# Local shape insets, in GD units, measured from the top-left of the cell.
#
# These are the single source of truth for every hitbox in this module.
# They were pixel literals against CELL=50 until the render scale became
# adjustable; each is the exact same fraction of a block it always was
# (px * 30/50), just stated in the unit system physics actually runs in.
# ---------------------------------------------------------------------------
HALF_BLOCK_UNITS = UNITS_PER_BLOCK / 2.0

# GD-style internal rectangular danger zone for a spike: narrower and
# taller than the visible triangle so corner approaches stay forgiving
# (0.30 x 0.64 of the tile, centred horizontally, clear of the floor).
SPIKE_LOCAL_UNITS = (10.2, 10.2, 9.0, 19.2)
HALF_SPIKE_LOCAL_UNITS = (10.2, 19.2, 9.0, 10.2)
# Pad activation strip: a shallow band across the bottom of the cell.
PAD_LOCAL_UNITS = (3.0, 19.2, 24.0, 10.8)
# Total (both sides) shrink from the cell to the saw's danger circle —
# the visible teeth spin but the danger region stays static at roughly
# 70% of the visible radius, and an even delta keeps it cell-centred.
SAW_INSET_UNITS = 9.6


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def lerp(a, b, t):
    return a + (b - a) * t


def normalize_rotation(r):
    try:
        return int(round(float(r) / 90.0) * 90) % 360
    except (TypeError, ValueError):
        return 0


def obj_scale(o):
    """Return the ``(sx, sy)`` tuple for an object dict.

    Pulls per-axis values from ``sx`` / ``sy`` when present, otherwise
    falls back to the legacy uniform ``scale``, otherwise ``(1.0, 1.0)``.
    Single source of truth so collision/draw callsites don't each
    re-derive the back-compat dance.
    """
    legacy = o.get("scale", 1.0)
    try:
        legacy = float(legacy)
    except (TypeError, ValueError):
        legacy = 1.0
    sx = o.get("sx", legacy)
    sy = o.get("sy", legacy)
    try:
        sx = float(sx)
    except (TypeError, ValueError):
        sx = 1.0
    try:
        sy = float(sy)
    except (TypeError, ValueError):
        sy = 1.0
    return sx, sy


def obj_alpha(o):
    """Return an object's render alpha as an int in [0, 255].

    ``_alpha`` (Checkpoint 5's Alpha Trigger) stores a [0.0, 1.0] float;
    objects that were never targeted by one simply have no key and
    render fully opaque, same as before this existed.
    """
    a = o.get("_alpha")
    if a is None:
        return 255
    try:
        a = float(a)
    except (TypeError, ValueError):
        return 255
    return max(0, min(255, int(round(a * 255))))


def obj_tint(o):
    """Return an object's multiply tint as an ``(r, g, b)`` tuple, or
    ``None`` when it is untinted.

    ``_tint`` (Checkpoint 2's Area Tint) is written by the area stepper
    already blended by the effect's falloff, i.e. it is the colour to
    multiply the sprite by (255 = leave that channel alone). Objects no
    area ever tinted simply have no key and render as before.
    """
    tint = o.get("_tint")
    if not tint:
        return None
    try:
        r, g, b = (max(0, min(255, int(c))) for c in tint[:3])
    except (TypeError, ValueError):
        return None
    return (r, g, b)


def _resolve_scale(scale, scale_y=None):
    """Normalize the various scale-arg shapes into ``(sx, sy)``.

    Accepts:
      * a single number (uniform scale, legacy callsites)
      * a ``(sx, sy)`` tuple/list (new per-axis form)
      * an explicit ``scale_y`` paired with a numeric ``scale`` (= sx)

    Returns ``(sx, sy)`` as floats. ``None`` / unparseable inputs map to
    the identity ``(1.0, 1.0)`` rather than raising — a malformed save
    file shouldn't crash the renderer, just look unscaled.
    """
    if isinstance(scale, (tuple, list)) and len(scale) >= 2:
        try:
            return float(scale[0]), float(scale[1])
        except (TypeError, ValueError):
            return 1.0, 1.0
    try:
        sx = float(scale)
    except (TypeError, ValueError):
        sx = 1.0
    if scale_y is None:
        return sx, sx
    try:
        return sx, float(scale_y)
    except (TypeError, ValueError):
        return sx, sx


def _scale_rect_around_cell_center(rect, gx, gy, scale, scale_y=None):
    """Return ``rect`` scaled around the cell's center point.

    Accepts a uniform scalar (legacy) or a ``(sx, sy)`` tuple — when
    the two axes differ the rect is stretched independently along x
    and y. Used by every collision helper so a scaled object's visual
    footprint and its hitbox stay in lock-step regardless of where
    within the cell the base rect was anchored.
    """
    sx, sy = _resolve_scale(scale, scale_y)
    if sx == 1.0 and sy == 1.0:
        return rect
    cx = gx * CELL + CELL / 2.0
    cy = gy * CELL + CELL / 2.0
    nw = rect.w * sx
    nh = rect.h * sy
    nx = cx + (rect.x - cx) * sx
    ny = cy + (rect.y - cy) * sy
    return pygame.Rect(round(nx), round(ny), max(1, round(nw)), max(1, round(nh)))


def cell_rect(gx, gy, scale=1.0, scale_y=None):
    base = pygame.Rect(gx * CELL, gy * CELL, CELL, CELL)
    return _scale_rect_around_cell_center(base, gx, gy, scale, scale_y)


def _units_rect_to_px(x, y, w, h):
    """A GD-unit cell-local rect -> its integer-pixel twin.

    Rounds the two EDGES rather than the origin and the size, so a shape
    that ends exactly on a cell boundary in units still ends exactly on
    it in pixels at any render scale.
    """
    x0, y0 = round(x * PX_PER_UNIT), round(y * PX_PER_UNIT)
    x1, y1 = round((x + w) * PX_PER_UNIT), round((y + h) * PX_PER_UNIT)
    return pygame.Rect(x0, y0, x1 - x0, y1 - y0)


# Slab local offsets (pre-rotation) in cell-local coords. Precomputed so
# slab_rect just branches the table and does one Rect alloc — no repeated
# normalize_rotation / if-chain per call.
_SLAB_LOCAL_UNITS = {
    0:   (0.0,              HALF_BLOCK_UNITS, UNITS_PER_BLOCK,  HALF_BLOCK_UNITS),
    180: (0.0,              0.0,              UNITS_PER_BLOCK,  HALF_BLOCK_UNITS),
    90:  (0.0,              0.0,              HALF_BLOCK_UNITS, UNITS_PER_BLOCK),
    270: (HALF_BLOCK_UNITS, 0.0,              HALF_BLOCK_UNITS, UNITS_PER_BLOCK),
}
_SLAB_LOCAL = {rot: tuple(_units_rect_to_px(*local))
               for rot, local in _SLAB_LOCAL_UNITS.items()}


def slab_rect(gx, gy, rotation=0, scale=1.0, scale_y=None):
    """Slab is half-height; rotation determines which edge it sits on."""
    lx, ly, lw, lh = _SLAB_LOCAL[normalize_rotation(rotation)]
    base = pygame.Rect(gx * CELL + lx, gy * CELL + ly, lw, lh)
    return _scale_rect_around_cell_center(base, gx, gy, scale, scale_y)


def rotate_local_rect(local_rect, rotation, size=CELL):
    rot = normalize_rotation(rotation)
    if rot == 0:
        return pygame.Rect(local_rect)
    cx = size / 2.0
    cy = size / 2.0
    points = [
        (local_rect.left, local_rect.top),
        (local_rect.right, local_rect.top),
        (local_rect.right, local_rect.bottom),
        (local_rect.left, local_rect.bottom),
    ]
    rotated = []
    for px, py in points:
        dx = px - cx
        dy = py - cy
        if rot == 90:
            rdx, rdy = -dy, dx
        elif rot == 180:
            rdx, rdy = -dx, -dy
        else:
            rdx, rdy = dy, -dx
        rotated.append((cx + rdx, cy + rdy))
    min_x = min(p[0] for p in rotated)
    max_x = max(p[0] for p in rotated)
    min_y = min(p[1] for p in rotated)
    max_y = max(p[1] for p in rotated)
    return pygame.Rect(round(min_x), round(min_y), round(max_x - min_x), round(max_y - min_y))


# Spike / pad base rects are pure functions of (rotation, half) — the
# rotation math ran in the collision inner loop every call. Cache the
# rotated bases; per-call allocation reduces to a single `.move()` per
# rect. The bases themselves are NOT returned to callers (`.move()`
# produces fresh Rects), so the cached Rects can't be mutated externally.
@functools.lru_cache(maxsize=16)
def _spike_base_rotated(rotation, half):
    local = HALF_SPIKE_LOCAL_UNITS if half else SPIKE_LOCAL_UNITS
    return (rotate_local_rect(_units_rect_to_px(*local), rotation),)


def spike_hitboxes(gx, gy, rotation=0, half=False, scale=1.0, scale_y=None):
    x = gx * CELL
    y = gy * CELL
    rects = [r.move(x, y) for r in
             _spike_base_rotated(normalize_rotation(rotation), bool(half))]
    sx, sy = _resolve_scale(scale, scale_y)
    if sx == 1.0 and sy == 1.0:
        return rects
    return [_scale_rect_around_cell_center(r, gx, gy, (sx, sy)) for r in rects]


@functools.lru_cache(maxsize=8)
def _pad_trigger_base_rotated(rotation):
    return rotate_local_rect(_units_rect_to_px(*PAD_LOCAL_UNITS), rotation)


def pad_trigger_rect(gx, gy, rotation=0):
    return _pad_trigger_base_rotated(normalize_rotation(rotation)).move(
        gx * CELL, gy * CELL)


def slope_polygon(gx, gy, rotation=0, scale=1.0, scale_y=None):
    """Return the slope's solid triangle as a list of world-pixel points.

    Mirrors the orientation table used by ``Player._slope_orientation``
    (in player.py) — keep the two in sync. The triangle is the SOLID
    half of the cell, so the hitbox view paints the side the player
    can't enter; the hypotenuse opposite is the ride surface.

    ``scale`` matches the cube-rect helpers — the triangle is scaled
    around the cell's center so a half-scale slope occupies the inner
    half of the cell, not a quadrant of it. Accepts a uniform scalar
    or a ``(sx, sy)`` pair for non-uniform stretching.
    """
    cl = gx * CELL
    cr = cl + CELL
    ct = gy * CELL
    cb = ct + CELL
    try:
        r = int(round(float(rotation) / 90.0)) % 4
    except (TypeError, ValueError):
        r = 0
    if r == 0:    # / floor — solid lower-right
        pts = [(cl, cb), (cr, cb), (cr, ct)]
    elif r == 1:  # \ floor — solid lower-left
        pts = [(cl, cb), (cr, cb), (cl, ct)]
    elif r == 2:  # / ceiling — solid upper-left
        pts = [(cl, ct), (cr, ct), (cl, cb)]
    else:         # \ ceiling — solid upper-right
        pts = [(cl, ct), (cr, ct), (cr, cb)]
    sx, sy = _resolve_scale(scale, scale_y)
    if sx == 1.0 and sy == 1.0:
        return pts
    cx = cl + CELL / 2.0
    cy = ct + CELL / 2.0
    return [(cx + (px - cx) * sx, cy + (py - cy) * sy) for px, py in pts]


def saw_hitbox(gx, gy, scale=1.0, scale_y=None):
    """Circular saw hitbox — smaller than the grid cell for fairness.

    See :data:`SAW_INSET_UNITS`; the inset is rounded to an even number
    of pixels so the hitbox center stays exactly on the cell center.
    """
    inset = 2 * round(SAW_INSET_UNITS * PX_PER_UNIT / 2)
    base = cell_rect(gx, gy).inflate(-inset, -inset)
    return _scale_rect_around_cell_center(base, gx, gy, scale, scale_y)


# ---------------------------------------------------------------------------
# Unit-space (GD units, float) hitbox builders — the PRIMARY definitions.
#
# These are what physics, collision and the bots collide against, using
# pygame.FRect so nothing is snapped to a pixel grid (see
# docs/development/UNITS_REFACTOR.md, "Decision: collision precision").
# The integer-px builders above are derived from the same
# ``*_LOCAL_UNITS`` tables, so the two families cannot drift apart when
# the render scale changes.
# ---------------------------------------------------------------------------

def _scale_frect_around_cell_center(frect, gx, gy, scale, scale_y=None):
    """Float-rect analogue of :func:`_scale_rect_around_cell_center`."""
    sx, sy = _resolve_scale(scale, scale_y)
    if sx == 1.0 and sy == 1.0:
        return frect
    cx = gx * UNITS_PER_BLOCK + UNITS_PER_BLOCK / 2.0
    cy = gy * UNITS_PER_BLOCK + UNITS_PER_BLOCK / 2.0
    nw = frect.w * sx
    nh = frect.h * sy
    nx = cx + (frect.x - cx) * sx
    ny = cy + (frect.y - cy) * sy
    return pygame.FRect(nx, ny, max(1e-6, nw), max(1e-6, nh))


def cell_rect_units(gx, gy, scale=1.0, scale_y=None):
    base = pygame.FRect(gx * UNITS_PER_BLOCK, gy * UNITS_PER_BLOCK,
                         UNITS_PER_BLOCK, UNITS_PER_BLOCK)
    return _scale_frect_around_cell_center(base, gx, gy, scale, scale_y)


def slab_rect_units(gx, gy, rotation=0, scale=1.0, scale_y=None):
    lx, ly, lw, lh = _SLAB_LOCAL_UNITS[normalize_rotation(rotation)]
    base = pygame.FRect(gx * UNITS_PER_BLOCK + lx, gy * UNITS_PER_BLOCK + ly,
                         lw, lh)
    return _scale_frect_around_cell_center(base, gx, gy, scale, scale_y)


def rotate_local_frect(local_frect, rotation, size=UNITS_PER_BLOCK):
    """Float-rect analogue of :func:`rotate_local_rect` — no rounding."""
    rot = normalize_rotation(rotation)
    if rot == 0:
        return pygame.FRect(local_frect)
    cx = size / 2.0
    cy = size / 2.0
    points = [
        (local_frect.left, local_frect.top),
        (local_frect.right, local_frect.top),
        (local_frect.right, local_frect.bottom),
        (local_frect.left, local_frect.bottom),
    ]
    rotated = []
    for lx, ly in points:
        dx = lx - cx
        dy = ly - cy
        if rot == 90:
            rdx, rdy = -dy, dx
        elif rot == 180:
            rdx, rdy = -dx, -dy
        else:
            rdx, rdy = dy, -dx
        rotated.append((cx + rdx, cy + rdy))
    min_x = min(p[0] for p in rotated)
    max_x = max(p[0] for p in rotated)
    min_y = min(p[1] for p in rotated)
    max_y = max(p[1] for p in rotated)
    return pygame.FRect(min_x, min_y, max_x - min_x, max_y - min_y)


@functools.lru_cache(maxsize=16)
def _spike_base_rotated_units(rotation, half):
    local = HALF_SPIKE_LOCAL_UNITS if half else SPIKE_LOCAL_UNITS
    return (rotate_local_frect(pygame.FRect(*local), rotation),)


def spike_hitboxes_units(gx, gy, rotation=0, half=False, scale=1.0, scale_y=None):
    x = gx * UNITS_PER_BLOCK
    y = gy * UNITS_PER_BLOCK
    rects = [pygame.FRect(r.x + x, r.y + y, r.w, r.h) for r in
              _spike_base_rotated_units(normalize_rotation(rotation), bool(half))]
    sx, sy = _resolve_scale(scale, scale_y)
    if sx == 1.0 and sy == 1.0:
        return rects
    return [_scale_frect_around_cell_center(r, gx, gy, (sx, sy)) for r in rects]


@functools.lru_cache(maxsize=8)
def _pad_trigger_base_rotated_units(rotation):
    return rotate_local_frect(pygame.FRect(*PAD_LOCAL_UNITS), rotation)


def pad_trigger_rect_units(gx, gy, rotation=0):
    base = _pad_trigger_base_rotated_units(normalize_rotation(rotation))
    x = gx * UNITS_PER_BLOCK
    y = gy * UNITS_PER_BLOCK
    return pygame.FRect(base.x + x, base.y + y, base.w, base.h)


def slope_polygon_units(gx, gy, rotation=0, scale=1.0, scale_y=None):
    """Unit-space analogue of :func:`slope_polygon`."""
    cl = gx * UNITS_PER_BLOCK
    cr = cl + UNITS_PER_BLOCK
    ct = gy * UNITS_PER_BLOCK
    cb = ct + UNITS_PER_BLOCK
    try:
        r = int(round(float(rotation) / 90.0)) % 4
    except (TypeError, ValueError):
        r = 0
    if r == 0:
        pts = [(cl, cb), (cr, cb), (cr, ct)]
    elif r == 1:
        pts = [(cl, cb), (cr, cb), (cl, ct)]
    elif r == 2:
        pts = [(cl, ct), (cr, ct), (cl, cb)]
    else:
        pts = [(cl, ct), (cr, ct), (cr, cb)]
    sx, sy = _resolve_scale(scale, scale_y)
    if sx == 1.0 and sy == 1.0:
        return pts
    cx = cl + UNITS_PER_BLOCK / 2.0
    cy = ct + UNITS_PER_BLOCK / 2.0
    return [(cx + (px - cx) * sx, cy + (py - cy) * sy) for px, py in pts]


def saw_hitbox_units(gx, gy, scale=1.0, scale_y=None):
    base = cell_rect_units(gx, gy).inflate(-SAW_INSET_UNITS, -SAW_INSET_UNITS)
    return _scale_frect_around_cell_center(base, gx, gy, scale, scale_y)

