"""Auto-generated level thumbnails — small previews shown in the browser.

A thumbnail is a PNG snapshot of a level's object layout, rendered to a fixed
4:1 aspect-ratio surface. Each object is drawn as a tiny colored rect so the
overall shape, length, and density of the level reads at a glance — sprite
art would be illegible at thumbnail scale.

Files live in `levels/_thumbs/`. Filenames are reserved (`_thumbs/` starts
with an underscore so it's invisible to `list_levels()`) and named after the
source level: `levels/<slug>.json` → `levels/_thumbs/<slug>.png`.

Generation is hooked into `levels.save_level` so a thumbnail is always fresh
after a write. The browser also lazily generates a missing thumbnail on
first load, which covers levels saved before this feature shipped.
"""

import os

import pygame

from constants import (
    LEVELS_DIR,
    T_BLOCK, T_SLAB, T_SPIKE, T_HALF_SPIKE, T_SAW,
    T_ORB, T_DASH_ORB, T_TELEPORT_ORB, T_BLUE_ORB, T_GREEN_ORB, T_BLACK_ORB,
    T_PAD, T_BLUE_PAD, T_GRAV, T_END, T_START, T_COIN, T_CHECKPOINT,
    T_MODE_SHIP, T_MODE_BALL, T_MODE_CUBE, T_MODE_WAVE, T_MODE_UFO,
    T_MODE_SPIDER, T_MODE_MINI, T_MODE_BIG,
    T_SPEED_SLOW, T_SPEED_NORMAL, T_SPEED_FAST, T_SPEED_FASTER,
    T_DECO_CRYSTAL, T_DECO_PILLAR, T_DECO_GLOW,
    T_CAMERA_TRIGGER, T_BG_TRIGGER, T_MOVE_TRIGGER, T_COLOR_TRIGGER,
    T_PULSE_TRIGGER, T_ROTATE_TRIGGER,
)


THUMBS_DIR = os.path.join(LEVELS_DIR, "_thumbs")
THUMB_W = 320
THUMB_H = 80

# Background gradient — matches the in-game sky so thumbnails feel like the
# real thing. Top color → bottom color.
_BG_TOP = (14, 8, 42)
_BG_BOT = (42, 14, 72)
_GROUND = (8, 30, 90)

# Per-type color map. Categories use shared hues so a "wall of blue" instantly
# means "lots of blocks", "wall of red" means "spike field", etc.
_TYPE_COLORS = {
    T_BLOCK: (60, 150, 255),
    T_SLAB: (60, 150, 255),
    T_SPIKE: (255, 80, 90),
    T_HALF_SPIKE: (255, 80, 90),
    T_SAW: (255, 100, 60),
    T_ORB: (255, 230, 60),
    T_DASH_ORB: (255, 100, 220),
    T_TELEPORT_ORB: (120, 240, 255),
    T_BLUE_ORB: (80, 170, 255),
    T_GREEN_ORB: (110, 255, 130),
    T_BLACK_ORB: (200, 200, 220),
    T_PAD: (255, 175, 30),
    T_BLUE_PAD: (90, 180, 255),
    T_GRAV: (0, 235, 215),
    T_END: (90, 255, 115),
    T_START: (130, 230, 130),
    T_COIN: (255, 215, 60),
    T_CHECKPOINT: (160, 220, 255),
    T_MODE_SHIP: (255, 130, 80),
    T_MODE_BALL: (190, 130, 255),
    T_MODE_CUBE: (100, 225, 255),
    T_MODE_WAVE: (130, 255, 220),
    T_MODE_UFO: (255, 200, 90),
    T_MODE_SPIDER: (200, 100, 255),
    T_MODE_MINI: (180, 220, 255),
    T_MODE_BIG: (255, 220, 180),
    T_SPEED_SLOW: (90, 200, 90),
    T_SPEED_NORMAL: (120, 220, 120),
    T_SPEED_FAST: (160, 235, 100),
    T_SPEED_FASTER: (220, 255, 80),
    T_DECO_CRYSTAL: (180, 220, 255),
    T_DECO_PILLAR: (140, 130, 200),
    T_DECO_GLOW: (255, 240, 200),
    T_CAMERA_TRIGGER: (200, 180, 100),
    T_BG_TRIGGER: (140, 110, 200),
    T_MOVE_TRIGGER: (255, 160, 80),
    T_COLOR_TRIGGER: (255, 120, 200),
    T_PULSE_TRIGGER: (200, 200, 255),
    T_ROTATE_TRIGGER: (180, 180, 255),
}
_DEFAULT_COLOR = (160, 160, 180)


def _ensure_dir():
    os.makedirs(THUMBS_DIR, exist_ok=True)


def thumbnail_path(level_filename):
    """Return the absolute thumbnail path for a level filename.

    `level_filename` may be just the basename (e.g. "my_level.json") or a
    full path — only the basename is used.
    """
    base = os.path.basename(level_filename)
    if base.endswith(".json"):
        base = base[:-5]
    return os.path.join(THUMBS_DIR, base + ".png")


def _bounds(objects):
    """Return (min_x, min_y, max_x, max_y) over the playable objects.

    Skips trigger types (camera/bg/move/color/pulse/rotate) since their
    positions are usually off in deadspace and would force the thumbnail to
    zoom way out. If there's nothing left to bound, falls back to the
    standard play strip (0..40, 0..15).
    """
    skip = {T_CAMERA_TRIGGER, T_BG_TRIGGER, T_MOVE_TRIGGER, T_COLOR_TRIGGER,
            T_PULSE_TRIGGER, T_ROTATE_TRIGGER}
    xs, ys = [], []
    for o in objects:
        if o.get("t") in skip:
            continue
        xs.append(int(o.get("x", 0)))
        ys.append(int(o.get("y", 0)))
    if not xs:
        return 0, 0, 40, 15
    return min(xs), min(ys), max(xs), max(ys)


def render_thumbnail(objects, size=(THUMB_W, THUMB_H)):
    """Render a level to a small pygame Surface and return it.

    The level is fitted to the surface preserving aspect ratio (letterboxed
    horizontally if it's tall, vertically if it's wide). Empty levels still
    produce a valid placeholder surface.
    """
    w, h = size
    surf = pygame.Surface((w, h)).convert()
    # Sky gradient (cheap row-by-row paint).
    for y in range(h):
        t = y / max(1, h - 1)
        r = int(_BG_TOP[0] + (_BG_BOT[0] - _BG_TOP[0]) * t)
        g = int(_BG_TOP[1] + (_BG_BOT[1] - _BG_TOP[1]) * t)
        b = int(_BG_TOP[2] + (_BG_BOT[2] - _BG_TOP[2]) * t)
        pygame.draw.line(surf, (r, g, b), (0, y), (w, y))

    if not objects:
        return surf

    min_x, min_y, max_x, max_y = _bounds(objects)
    span_x = max(1, max_x - min_x + 1)
    span_y = max(1, max_y - min_y + 1)
    # Pad slightly so edge objects aren't clipped against the frame.
    pad = 1
    span_x += pad * 2
    span_y += pad * 2

    # Pick a uniform scale that fits the level into the surface.
    sx = w / span_x
    sy = h / span_y
    scale = min(sx, sy)
    # Centering offsets — keeps the level vertically centered if it's short.
    used_w = span_x * scale
    used_h = span_y * scale
    off_x = (w - used_w) / 2
    off_y = (h - used_h) / 2

    # Faint ground line so the thumbnail reads as "platformer level".
    ground_world_y = max_y + 1
    gy_px = int(off_y + (ground_world_y - min_y + pad) * scale)
    gy_px = max(0, min(h - 1, gy_px))
    pygame.draw.rect(surf, _GROUND, (0, gy_px, w, h - gy_px))

    # Sort so big background-y solids paint first and shiny stuff (orbs,
    # end-flag, start) sits on top.
    paint_order = sorted(objects, key=lambda o: _z(o.get("t")))
    cell_px = max(1, int(round(scale)))
    for o in paint_order:
        t = o.get("t")
        col = _TYPE_COLORS.get(t, _DEFAULT_COLOR)
        ox = int(off_x + (int(o.get("x", 0)) - min_x + pad) * scale)
        oy = int(off_y + (int(o.get("y", 0)) - min_y + pad) * scale)
        pygame.draw.rect(surf, col, (ox, oy, cell_px, cell_px))

    # Subtle 1-px frame so the thumbnail visually contains itself when laid
    # over a same-color card background.
    pygame.draw.rect(surf, (90, 100, 140), surf.get_rect(), 1)
    return surf


# Z-order map: lower paints first. Solids → hazards → orbs/portals → markers.
_Z_ORDER = {
    T_DECO_PILLAR: -2, T_DECO_CRYSTAL: -2, T_DECO_GLOW: -2,
    T_BLOCK: 0, T_SLAB: 0,
    T_SPIKE: 1, T_HALF_SPIKE: 1, T_SAW: 1,
    T_PAD: 2, T_BLUE_PAD: 2, T_GRAV: 2,
    T_ORB: 3, T_DASH_ORB: 3, T_TELEPORT_ORB: 3,
    T_BLUE_ORB: 3, T_GREEN_ORB: 3, T_BLACK_ORB: 3,
    T_COIN: 4,
    T_MODE_SHIP: 5, T_MODE_BALL: 5, T_MODE_CUBE: 5, T_MODE_WAVE: 5,
    T_MODE_UFO: 5, T_MODE_SPIDER: 5, T_MODE_MINI: 5, T_MODE_BIG: 5,
    T_SPEED_SLOW: 5, T_SPEED_NORMAL: 5, T_SPEED_FAST: 5, T_SPEED_FASTER: 5,
    T_CHECKPOINT: 6,
    T_START: 7, T_END: 7,
}


def _z(t):
    return _Z_ORDER.get(t, 0)


def save_thumbnail(level_filename, objects):
    """Render and save a thumbnail PNG. Returns the path, or None on failure."""
    _ensure_dir()
    surf = render_thumbnail(objects)
    path = thumbnail_path(level_filename)
    try:
        pygame.image.save(surf, path)
    except (OSError, pygame.error):
        return None
    return path


def load_thumbnail(level_filename):
    """Return a pygame Surface for the level's thumbnail, or None if missing.

    Does NOT auto-generate — callers can choose to lazily call
    `save_thumbnail` when this returns None.
    """
    path = thumbnail_path(level_filename)
    if not os.path.isfile(path):
        return None
    try:
        return pygame.image.load(path).convert()
    except (OSError, pygame.error):
        return None


def clear_thumbnail(level_filename):
    """Delete the thumbnail file for a level, if any."""
    path = thumbnail_path(level_filename)
    try:
        os.remove(path)
    except OSError:
        pass
