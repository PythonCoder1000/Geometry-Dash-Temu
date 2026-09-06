"""Object sprites: per-type renderers, the on-disk/in-memory sprite cache,
and :func:`draw_obj`.

Sprites are rendered once at 2x, downsampled for anti-aliasing, and saved
as PNGs under the per-user ``sprite_cache/`` dir (and shipped pre-baked in
``assets/sprites``).  ``SPRITE_CACHE_VERSION`` must be bumped whenever a
renderer's output changes so stale PNGs are regenerated.
"""

import math
import os
from collections import OrderedDict

import pygame

from .constants import (
    ASSETS_DIR, CELL, _USER_DATA, TRIGGER_TYPES,
    C_WHITE, C_GRAY, C_BLOCK_H, C_BLOCK_D, C_SPIKE, C_SAW, C_ORB, C_DASH_ORB,
    C_DASH_ORB_GRAV, C_TELEPORT_ORB, C_GREEN_ORB, C_SPIDER_ORB, C_RED_ORB,
    C_PINK_ORB, C_PAD, C_PINK_PAD, C_RED_PAD, C_BLUE_PAD, C_SPIDER_PAD,
    C_GPORTAL_UP, C_GPORTAL_DOWN, C_END, C_PLAYER, C_DECO_CRYSTAL,
    C_DECO_PILLAR, C_DECO_GLOW, C_COIN, C_CHECKPOINT,
    SPEED_VALUES, MODE_FROM_TYPE,
    T_BLOCK, T_SLAB, T_SLOPE, T_SPIKE, T_HALF_SPIKE, T_SAW, T_ORB, T_DASH_ORB,
    T_DASH_ORB_GRAV, T_TELEPORT_ORB, T_BLACK_ORB, T_BLUE_ORB, T_GREEN_ORB,
    T_SPIDER_ORB, T_RED_ORB, T_PINK_ORB,
    T_PAD, T_PINK_PAD, T_RED_PAD, T_BLUE_PAD, T_SPIDER_PAD,
    T_GRAV_UP, T_GRAV_DOWN, T_END, T_START, T_COIN, T_CHECKPOINT,
    T_MODE_CUBE, T_MODE_SHIP, T_MODE_BALL, T_MODE_WAVE, T_MODE_UFO,
    T_MODE_SPIDER, T_MODE_SWING, T_MODE_ROBOT, T_MODE_MINI, T_MODE_BIG,
    T_MODE_DUAL, T_MODE_SOLO,
    T_DECO_CRYSTAL, T_DECO_PILLAR, T_DECO_GLOW,
    T_CAMERA_TRIGGER, T_BG_TRIGGER, T_MOVE_TRIGGER, T_COLOR_TRIGGER,
    T_PULSE_TRIGGER, T_ROTATE_TRIGGER, T_FOLLOW_TRIGGER, T_TIME_WARP,
    T_JUMP_PREDICTOR, T_BOT_CHECKPOINT,
    T_SPEED_SLOW, T_SPEED_NORMAL, T_SPEED_FAST, T_SPEED_FASTER,
    T_SPEED_FASTEST,
)
from .objects import TYPE_COLS, ANIMATED_TYPES
from .geometry import normalize_rotation, _resolve_scale, clamp
from .graphics import txt, lighter, darker, lerp_col

# ---------------------------------------------------------------------------
# Object sprite images — rendered at 2x and downsampled for AA, then saved
# so they load as real images on next launch.
#
# Two locations: the BUNDLED_SPRITES_DIR ships the pre-rendered sprites
# inside the app bundle (read-only), and SPRITES_DIR is a writable cache
# under the user data dir. At runtime we read either location, but WRITE
# only to the user cache so packaged builds can rebake on render-code
# changes without needing write access to the bundle.
#
# SPRITE_CACHE_VERSION is bumped whenever a renderer output changes in a
# way that would make stale PNGs look wrong. On mismatch the user cache
# is wiped and regenerated on demand.
# ---------------------------------------------------------------------------
SPRITE_CACHE_VERSION = "2"
BUNDLED_SPRITES_DIR = os.path.join(ASSETS_DIR, "sprites")
SPRITES_DIR = os.path.join(_USER_DATA, "sprite_cache")
_SPRITE_VERSION_MARKER = os.path.join(SPRITES_DIR, ".version")
SPRITE_FRAMES = 8            # animation frames baked per animated type
_SUPERSAMPLE = 2             # render at this multiple, smooth-scale down
_OBJECT_CACHE = OrderedDict()  # (t, s, frame, variant) -> Surface; LRU-ordered
_OBJECT_CACHE_MAX = 600


def _check_sprite_cache_version():
    """Wipe the writable sprite cache when SPRITE_CACHE_VERSION changes.

    Prevents stale PNGs (from an older render pass) from shadowing the
    current renderer's output — that was the "asset glitch" class where
    a user who updated the game saw the old visuals.
    """
    try:
        os.makedirs(SPRITES_DIR, exist_ok=True)
    except OSError:
        return
    want = SPRITE_CACHE_VERSION
    cur = None
    try:
        with open(_SPRITE_VERSION_MARKER, encoding="utf-8") as f:
            cur = f.read().strip()
    except OSError:
        pass
    if cur == want:
        return
    # Version mismatch (or first run) — nuke old PNGs. We only touch the
    # writable cache; the bundled sprites dir stays untouched.
    try:
        for fn in os.listdir(SPRITES_DIR):
            if fn.endswith(".png"):
                try:
                    os.remove(os.path.join(SPRITES_DIR, fn))
                except OSError:
                    pass
        with open(_SPRITE_VERSION_MARKER, "w", encoding="utf-8") as f:
            f.write(want)
    except OSError:
        pass


_check_sprite_cache_version()

# Static types get a single image. Animated types get SPRITE_FRAMES.
_ANIMATED_TYPES = ANIMATED_TYPES


def _frame_count(t):
    return SPRITE_FRAMES if t in _ANIMATED_TYPES else 1


def _sprite_filename(t, s, frame):
    if t in _ANIMATED_TYPES:
        return f"{t}_s{s}_f{frame}.png"
    return f"{t}_s{s}.png"


def _sprite_path(t, s, frame):
    """Writable per-user sprite-cache path."""
    return os.path.join(SPRITES_DIR, _sprite_filename(t, s, frame))


def _bundled_sprites_valid():
    """Bundled PNGs are only trusted when they were baked by this
    renderer version — otherwise a stale bundle would shadow new art."""
    try:
        with open(os.path.join(BUNDLED_SPRITES_DIR, ".version"),
                  encoding="utf-8") as f:
            return f.read().strip() == SPRITE_CACHE_VERSION
    except OSError:
        return False


_BUNDLED_OK = _bundled_sprites_valid()


def _bundled_sprite_path(t, s, frame):
    """Read-only bundled sprite path (``None`` when the bundle is stale)."""
    if not _BUNDLED_OK:
        return None
    return os.path.join(BUNDLED_SPRITES_DIR, _sprite_filename(t, s, frame))


# ---- HQ drawing primitives ------------------------------------------------
def _radial_fill(surf, center, radius, inner_col, outer_col):
    """Filled radial gradient circle — inner→outer from centre outwards."""
    cx, cy = center
    for r in range(radius, 0, -1):
        t = 1.0 - (r / radius)
        col = lerp_col(outer_col, inner_col, t)
        pygame.draw.circle(surf, col, (cx, cy), r)


def _glow(surf, center, radius, col, max_alpha=90, layers=10):
    """Soft glow halo around a point — additive-looking without BLEND ops."""
    cx, cy = center
    for i in range(layers, 0, -1):
        t = i / layers
        a = int(max_alpha * (1 - t) * (1 - t))
        if a <= 0:
            continue
        pygame.draw.circle(surf, (*col, a), (cx, cy), int(radius + i * radius * 0.15))


def _vgradient(surf, rect, top_col, bot_col, border_radius=0):
    """Vertical gradient filling a rect (with optional rounded corners via mask)."""
    if border_radius <= 0:
        for y in range(rect.h):
            t = y / max(1, rect.h - 1)
            col = lerp_col(top_col, bot_col, t)
            pygame.draw.line(surf, col, (rect.x, rect.y + y), (rect.right - 1, rect.y + y))
        return
    # Rounded: draw gradient into a throwaway surface and mask with a rounded rect.
    grad = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
    for y in range(rect.h):
        t = y / max(1, rect.h - 1)
        col = lerp_col(top_col, bot_col, t)
        pygame.draw.line(grad, col, (0, y), (rect.w - 1, y))
    mask = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
    pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=border_radius)
    grad.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
    surf.blit(grad, rect.topleft)


def _specular_highlight(surf, rect, alpha=90, height_frac=0.45):
    """Soft top highlight — one-sided gradient, fading from top."""
    h = max(2, int(rect.h * height_frac))
    for y in range(h):
        t = y / max(1, h - 1)
        a = int(alpha * (1 - t) ** 2)
        if a <= 0:
            continue
        pygame.draw.line(surf, (255, 255, 255, a),
                         (rect.x + 2, rect.y + y), (rect.right - 2, rect.y + y))


def _drop_shadow(surf, rect, offset=3, alpha=80, border_radius=0):
    sh = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
    pygame.draw.rect(sh, (0, 0, 0, alpha), sh.get_rect(), border_radius=border_radius)
    surf.blit(sh, (rect.x, rect.y + offset))


# ---- Helper: orb with consistent glow + core + highlight ------------------
def _render_orb_hq(surf, col, s, frame_t, outline_only=False, label=None,
                  inner_icon=None):
    """Detailed orb: halo + body + inner highlight. frame_t in [0,1)."""
    cx, cy = s // 2, s // 2
    # Gentle radius pulse
    pulse_s = 1.0 + 0.08 * math.sin(frame_t * math.tau)
    r = int(s * 0.28 * pulse_s)
    # Outer halo
    _glow(surf, (cx, cy), r, col, max_alpha=110, layers=8)
    if outline_only:
        # Ring with inner soft gradient to fake depth
        pygame.draw.circle(surf, darker(col, 40), (cx, cy), r + 2, 4)
        pygame.draw.circle(surf, col, (cx, cy), r, 3)
        pygame.draw.circle(surf, lighter(col, 80), (cx, cy), r, 1)
    else:
        # Filled body with radial gradient + rim
        _radial_fill(surf, (cx, cy), r + 2, lighter(col, 90), darker(col, 60))
        pygame.draw.circle(surf, darker(col, 60), (cx, cy), r + 2, 2)
        # Inner core highlight (offset top-left for depth)
        off = max(1, r // 4)
        highlight_r = max(2, r // 2)
        hs = pygame.Surface((highlight_r * 2, highlight_r * 2), pygame.SRCALPHA)
        _radial_fill(hs, (highlight_r, highlight_r), highlight_r,
                     (255, 255, 255), (*lighter(col, 100), 0))
        surf.blit(hs, (cx - off - highlight_r, cy - off - highlight_r))
    if label:
        txt(surf, label, cx, cy, int(s * 0.32), C_WHITE, True, shadow=True)
    if inner_icon:
        inner_icon(surf, cx, cy, r)


# ---- Helper: portal box with glow, gradient, inner core -------------------
def _render_portal_hq(surf, s, col, frame_t, inner_scale=0.58, thickness=3):
    cx = s // 2
    rr = pygame.Rect(8, 2, s - 16, s - 4)
    pulse = int(25 * math.sin(frame_t * math.tau))
    c = tuple(clamp(v + pulse, 0, 255) for v in col)
    # Glow behind the portal
    glow = pygame.Surface((rr.w + 40, rr.h + 40), pygame.SRCALPHA)
    for i in range(6, 0, -1):
        a = int(60 * (1 - i / 6) ** 2)
        pygame.draw.rect(glow, (*c, a),
                         glow.get_rect().inflate(-i * 4, -i * 4), border_radius=14)
    surf.blit(glow, (rr.x - 20, rr.y - 20))
    # Portal body: gradient-filled rect with rim
    _vgradient(surf, rr, lighter(c, 40), darker(c, 30), border_radius=9)
    pygame.draw.rect(surf, lighter(c, 60), rr, thickness, border_radius=9)
    pygame.draw.rect(surf, darker(c, 40), rr, 1, border_radius=9)
    # Inner plate
    inner = rr.inflate(int(-(1.0 - inner_scale) * rr.w),
                       int(-(1.0 - inner_scale) * rr.h))
    _vgradient(surf, inner, lighter(c, 80), c, border_radius=7)
    pygame.draw.rect(surf, darker(c, 30), inner, 1, border_radius=7)
    # Top specular
    _specular_highlight(surf, rr, alpha=60, height_frac=0.35)
    return rr


def _speed_arrows(surf, rr, count):
    total_w = count * 8
    start = rr.centerx - total_w // 2
    for i in range(count):
        ox = start + i * 8
        cy = rr.centery
        pts = [(ox, cy - 6), (ox + 10, cy), (ox, cy + 6)]
        pygame.draw.polygon(surf, C_WHITE, pts)
        pygame.draw.polygon(surf, darker(C_WHITE, 60), pts, 1)


# ---- Per-type HQ renderers ------------------------------------------------
def _render_block(surf, s, frame_t):
    rect = pygame.Rect(0, 0, s, s)
    _vgradient(surf, rect, lighter(C_BLOCK_H, 30), darker(C_BLOCK_D, 20),
               border_radius=3)
    # Inner bevel highlights
    pygame.draw.rect(surf, lighter(C_BLOCK_H, 80), rect.inflate(-2, -2), 1,
                     border_radius=2)
    pygame.draw.rect(surf, darker(C_BLOCK_D, 50), rect, 2, border_radius=3)
    # Top specular
    _specular_highlight(surf, rect.inflate(-4, -4), alpha=70, height_frac=0.45)
    # Subtle inner frame
    inset = max(3, s // 10)
    pygame.draw.rect(surf, (*lighter(C_BLOCK_H, 40), 90),
                     rect.inflate(-inset * 2, -inset * 2), 1, border_radius=2)


def _render_slab(surf, s, frame_t):
    rect = pygame.Rect(0, s // 2, s, s // 2)
    _vgradient(surf, rect, lighter(C_BLOCK_H, 30), darker(C_BLOCK_D, 20),
               border_radius=3)
    pygame.draw.rect(surf, lighter(C_BLOCK_H, 80), rect.inflate(-2, -2), 1,
                     border_radius=2)
    pygame.draw.rect(surf, darker(C_BLOCK_D, 50), rect, 2, border_radius=3)
    _specular_highlight(surf, rect.inflate(-4, -4), alpha=70, height_frac=0.45)


def _render_slope(surf, s, frame_t):
    """Right-triangle ramp filling the lower-right of the cell — base
    orientation, before any per-instance rotation. Hypotenuse runs from
    (0, s) up to (s, 0) so the cube can ride right-and-up. Other
    rotations (90/180/270) re-use this sprite via pygame's image
    rotation in ``draw_obj``; the collision code in player.py mirrors
    each orientation explicitly so the diagonal hitbox follows what the
    sprite actually shows.
    """
    pts = [(0, s), (s, s), (s, 0)]
    base = pygame.Surface((s, s), pygame.SRCALPHA)
    # Body fill: vertical gradient mirrors the regular block so a slope
    # placed next to a flat block reads as the same material.
    grad = pygame.Surface((s, s), pygame.SRCALPHA)
    _vgradient(grad, pygame.Rect(0, 0, s, s),
               lighter(C_BLOCK_H, 30), darker(C_BLOCK_D, 20),
               border_radius=0)
    # Mask the gradient with the triangle.
    mask = pygame.Surface((s, s), pygame.SRCALPHA)
    pygame.draw.polygon(mask, (255, 255, 255, 255), pts)
    grad.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    base.blit(grad, (0, 0))
    # Hypotenuse highlight — bright bevel along the ride surface.
    pygame.draw.line(base, lighter(C_BLOCK_H, 80),
                     (0, s - 1), (s - 1, 0), max(2, s // 24))
    # Outer outline for definition against the background.
    pygame.draw.polygon(base, darker(C_BLOCK_D, 50), pts, max(2, s // 28))
    surf.blit(base, (0, 0))


def _render_spike(surf, s, frame_t, half=False):
    if half:
        tip_y = s // 2 + 2
    else:
        tip_y = 3
    pts = [(s // 2, tip_y), (4, s - 2), (s - 4, s - 2)]
    col = lighter(C_SPIKE, 15) if half else C_SPIKE
    # Fake radial gradient: inner glow then body
    glow = pygame.Surface((s, s), pygame.SRCALPHA)
    pygame.draw.polygon(glow, (*col, 80),
                        [(s // 2, tip_y - 6), (-4, s + 2), (s + 4, s + 2)])
    surf.blit(glow, (0, 0))
    # Body fill with vertical gradient: bright tip → dark base
    # Simulate via filling triangle with bright then blitting a darker bottom
    pygame.draw.polygon(surf, col, pts)
    # Highlight stripe down the middle
    cx = s // 2
    for yi in range(tip_y + 2, s - 4):
        t = (yi - tip_y) / max(1, s - tip_y - 4)
        hx = 2 + int(t * (cx - 6))
        a = int(160 * (1 - t))
        pygame.draw.line(surf, (255, 255, 255, a),
                         (cx - hx // 3, yi), (cx + hx // 3, yi))
    # Darker base shadow
    pygame.draw.polygon(surf, darker(col, 40), pts, 2)
    # Sharp tip highlight
    pygame.draw.line(surf, lighter(col, 120),
                     (cx - 2, tip_y + 2), (cx + 2, tip_y + 2), 1)


def _render_saw(surf, s, frame_t):
    cx, cy = s // 2, s // 2
    r_outer = int(s * 0.46)
    r_inner = int(s * 0.2)
    # Saw rotates with frame
    angle_offset = frame_t * math.tau / 8  # one tooth per full cycle
    teeth = 8
    pts = []
    for i in range(teeth * 2):
        angle = angle_offset + i * math.pi / teeth
        rad = r_outer if i % 2 == 0 else int(r_outer * 0.72)
        pts.append((cx + int(math.cos(angle) * rad),
                    cy + int(math.sin(angle) * rad)))
    # Glow halo
    _glow(surf, (cx, cy), r_outer, C_SAW, max_alpha=60, layers=6)
    # Teeth body with gradient effect: bright top, dark bottom
    pygame.draw.polygon(surf, darker(C_SAW, 40), pts)
    # Inner lighter ring
    inner_pts = []
    for i in range(teeth * 2):
        angle = angle_offset + i * math.pi / teeth
        rad = int(r_outer * 0.78) if i % 2 == 0 else int(r_outer * 0.58)
        inner_pts.append((cx + int(math.cos(angle) * rad),
                          cy + int(math.sin(angle) * rad)))
    pygame.draw.polygon(surf, C_SAW, inner_pts)
    # Tooth tips highlight
    for i in range(0, teeth * 2, 2):
        angle = angle_offset + i * math.pi / teeth
        x = cx + int(math.cos(angle) * r_outer * 0.94)
        y = cy + int(math.sin(angle) * r_outer * 0.94)
        pygame.draw.circle(surf, lighter(C_SAW, 80), (x, y), 2)
    # Central hub
    pygame.draw.circle(surf, (190, 190, 200), (cx, cy), r_inner)
    _radial_fill(surf, (cx, cy), r_inner, (230, 230, 240), (100, 100, 115))
    pygame.draw.circle(surf, (60, 60, 70), (cx, cy), r_inner, 2)
    # Bolt
    pygame.draw.circle(surf, (20, 20, 24), (cx, cy), 3)
    pygame.draw.circle(surf, (70, 70, 80), (cx, cy), 2)


def _render_orb(surf, s, frame_t):
    _render_orb_hq(surf, C_ORB, s, frame_t)


def _render_dash_orb(surf, s, frame_t, col=C_DASH_ORB):
    def _icon(surf, cx, cy, r):
        pygame.draw.polygon(surf, lighter(col, 50),
                            [(cx + r - 2, cy), (cx - 4, cy - 7), (cx - 4, cy + 7)])
        pygame.draw.polygon(surf, C_WHITE,
                            [(cx + r - 2, cy), (cx - 4, cy - 7), (cx - 4, cy + 7)], 1)
    _render_orb_hq(surf, col, s, frame_t, outline_only=True,
                   inner_icon=_icon)


def _render_teleport_orb(surf, s, frame_t, link_label=None):
    if link_label:
        _render_orb_hq(surf, C_TELEPORT_ORB, s, frame_t, outline_only=True,
                       label=str(link_label))
    else:
        def _icon(surf, cx, cy, r):
            pygame.draw.line(surf, lighter(C_TELEPORT_ORB, 70),
                             (cx - 7, cy - 7), (cx + 7, cy + 7), 2)
            pygame.draw.line(surf, lighter(C_TELEPORT_ORB, 70),
                             (cx + 7, cy - 7), (cx - 7, cy + 7), 2)
        _render_orb_hq(surf, C_TELEPORT_ORB, s, frame_t, outline_only=True,
                       inner_icon=_icon)


def _render_black_orb(surf, s, frame_t):
    def _icon(surf, cx, cy, r):
        pygame.draw.line(surf, C_WHITE, (cx, cy - 6), (cx, cy + 6), 2)
        pygame.draw.polygon(surf, C_WHITE,
                            [(cx - 5, cy + 2), (cx + 5, cy + 2), (cx, cy + 8)])
    _render_orb_hq(surf, (60, 60, 80), s, frame_t, inner_icon=_icon)


def _render_blue_orb(surf, s, frame_t):
    def _icon(surf, cx, cy, r):
        pygame.draw.polygon(surf, (120, 190, 255),
                            [(cx - 5, cy - 2), (cx + 5, cy - 2), (cx, cy - 8)])
        pygame.draw.polygon(surf, (120, 190, 255),
                            [(cx - 5, cy + 2), (cx + 5, cy + 2), (cx, cy + 8)])
    _render_orb_hq(surf, (100, 170, 255), s, frame_t, outline_only=True,
                   inner_icon=_icon)


def _render_green_orb(surf, s, frame_t):
    def _icon(surf, cx, cy, r):
        pygame.draw.polygon(surf, C_GREEN_ORB,
                            [(cx, cy - 8), (cx - 5, cy - 2), (cx + 5, cy - 2)])
    _render_orb_hq(surf, C_GREEN_ORB, s, frame_t, outline_only=True,
                   inner_icon=_icon)


def _render_red_orb(surf, s, frame_t):
    # Tall double-up arrow signals 2× jump strength.
    def _icon(surf, cx, cy, r):
        pygame.draw.polygon(surf, C_WHITE,
                            [(cx, cy - 9), (cx - 5, cy - 3), (cx + 5, cy - 3)])
        pygame.draw.polygon(surf, C_WHITE,
                            [(cx, cy - 1), (cx - 5, cy + 5), (cx + 5, cy + 5)])
    _render_orb_hq(surf, C_RED_ORB, s, frame_t, inner_icon=_icon)


def _render_pink_orb(surf, s, frame_t):
    # Short single up-arrow signals a half-strength hop.
    def _icon(surf, cx, cy, r):
        pygame.draw.polygon(surf, C_WHITE,
                            [(cx, cy - 4), (cx - 4, cy + 2), (cx + 4, cy + 2)])
    _render_orb_hq(surf, C_PINK_ORB, s, frame_t, inner_icon=_icon)


def _render_spider_orb(surf, s, frame_t, variant=None):
    """Purple teleport orb with a directional arrow icon.

    ``variant`` controls the arrow pair so authors can tell at a glance
    which way the orb will fling them:
      ``None`` / ``"auto"`` — up + down (default against-gravity hint)
      ``"up"``    — two up arrows
      ``"down"``  — two down arrows
      ``"left"``  — two left arrows
      ``"right"`` — two right arrows
    """
    def _icon(surf, cx, cy, r):
        col = C_SPIDER_ORB

        def _up(ay):
            pygame.draw.polygon(
                surf, col,
                [(cx, ay - 4), (cx - 5, ay + 3), (cx + 5, ay + 3)])

        def _down(ay):
            pygame.draw.polygon(
                surf, col,
                [(cx, ay + 4), (cx - 5, ay - 3), (cx + 5, ay - 3)])

        def _left(ax):
            pygame.draw.polygon(
                surf, col,
                [(ax - 4, cy), (ax + 3, cy - 5), (ax + 3, cy + 5)])

        def _right(ax):
            pygame.draw.polygon(
                surf, col,
                [(ax + 4, cy), (ax - 3, cy - 5), (ax - 3, cy + 5)])

        if variant == "up":
            _up(cy - 5); _up(cy + 6)
        elif variant == "down":
            _down(cy - 6); _down(cy + 5)
        elif variant == "left":
            _left(cx - 5); _left(cx + 6)
        elif variant == "right":
            _right(cx - 6); _right(cx + 5)
        else:
            _up(cy - 4); _down(cy + 4)

    _render_orb_hq(surf, C_SPIDER_ORB, s, frame_t, outline_only=True,
                   inner_icon=_icon)


def _render_pad(surf, s, frame_t, col=C_PAD, glyph=None):
    """Spring pad strip along the bottom edge.  ``glyph`` selects the
    overlay: ``None`` (plain), ``"flip"`` (gravity arrow) or ``"spider"``
    (double arrow)."""
    # Shadow bar
    sh = pygame.Rect(5, s - 16, s - 10, 16)
    _drop_shadow(surf, sh, offset=4, alpha=70, border_radius=4)
    # Body gradient
    body = pygame.Rect(5, s - 18, s - 10, 16)
    _vgradient(surf, body, lighter(col, 50), darker(col, 20), border_radius=4)
    pygame.draw.rect(surf, darker(col, 50), body, 2, border_radius=4)
    # Top highlight stripe (bright lip)
    stripe = pygame.Rect(8, s - 16, s - 16, 3)
    pygame.draw.rect(surf, lighter(col, 100), stripe, border_radius=2)
    # Inner groove
    pygame.draw.line(surf, darker(col, 50),
                     (body.x + 3, body.bottom - 3), (body.right - 3, body.bottom - 3), 1)
    cx = s // 2
    if glyph == "flip":
        pygame.draw.polygon(surf, C_WHITE,
                            [(cx - 5, s - 11), (cx + 5, s - 11), (cx, s - 3)])
        pygame.draw.polygon(surf, darker(C_WHITE, 40),
                            [(cx - 5, s - 11), (cx + 5, s - 11), (cx, s - 3)], 1)
    elif glyph == "spider":
        for ox in (-8, 8):
            pygame.draw.polygon(surf, C_WHITE,
                                [(cx + ox, s - 16), (cx + ox - 4, s - 8),
                                 (cx + ox + 4, s - 8)])


def _render_grav(surf, s, frame_t, direction):
    """Gravity-set portal. ``direction`` is "up" (blue, sets grav=-1) or
    "down" (yellow, sets grav=+1). A single-headed arrow indicates the
    forced gravity direction (no flip)."""
    col = C_GPORTAL_UP if direction == "up" else C_GPORTAL_DOWN
    rr = _render_portal_hq(surf, s, col, frame_t, inner_scale=0.62)
    cx = rr.centerx
    # Single arrow pointing in the SET direction.
    if direction == "up":
        tip_y = rr.y + 6
        base_y = rr.bottom - 6
        head_y = rr.y + 18
        arrow = [(cx, tip_y),
                 (cx - 7, head_y), (cx - 2, head_y),
                 (cx - 2, base_y), (cx + 2, base_y),
                 (cx + 2, head_y), (cx + 7, head_y)]
    else:
        tip_y = rr.bottom - 6
        base_y = rr.y + 6
        head_y = rr.bottom - 18
        arrow = [(cx, tip_y),
                 (cx + 7, head_y), (cx + 2, head_y),
                 (cx + 2, base_y), (cx - 2, base_y),
                 (cx - 2, head_y), (cx - 7, head_y)]
    pygame.draw.polygon(surf, C_WHITE, arrow)
    pygame.draw.polygon(surf, darker(C_WHITE, 30), arrow, 1)


def _render_end(surf, s, frame_t):
    rr = pygame.Rect(6, 2, s - 12, s - 4)
    # Pulsing glow
    pulse_a = int(40 + 30 * math.sin(frame_t * math.tau))
    glow = pygame.Surface((rr.w + 20, rr.h + 20), pygame.SRCALPHA)
    pygame.draw.rect(glow, (*C_END, pulse_a), glow.get_rect(), border_radius=10)
    surf.blit(glow, (rr.x - 10, rr.y - 10))
    # Flag pole
    pygame.draw.rect(surf, (240, 240, 250), (rr.x + 2, rr.y, 3, rr.h))
    # Checker flag
    flag = pygame.Rect(rr.x + 5, rr.y + 2, rr.w - 5, rr.h - 4)
    pygame.draw.rect(surf, C_WHITE, flag)
    cells = 4
    cw = flag.w // cells
    ch = flag.h // cells
    for i in range(cells):
        for j in range(cells):
            if (i + j) % 2 == 0:
                pygame.draw.rect(surf, (20, 20, 30),
                                 (flag.x + i * cw, flag.y + j * ch, cw, ch))
    pygame.draw.rect(surf, lighter(C_END, 60), flag, 2)


def _render_dual_portal(surf, s, frame_t, t):
    """Dual/solo portal — shows two mirrored cubes or a single cube."""
    col = TYPE_COLS[t]
    rr = _render_portal_hq(surf, s, col, frame_t, inner_scale=0.65)
    cx, cy = rr.centerx, rr.centery
    if t == T_MODE_DUAL:
        top = pygame.Rect(cx - 6, cy - 11, 12, 10)
        bot = pygame.Rect(cx - 6, cy + 1, 12, 10)
        pygame.draw.rect(surf, C_WHITE, top, border_radius=2)
        pygame.draw.rect(surf, C_WHITE, bot, border_radius=2)
        pygame.draw.rect(surf, darker(col, 40), top, 1, border_radius=2)
        pygame.draw.rect(surf, darker(col, 40), bot, 1, border_radius=2)
        pygame.draw.line(surf, darker(col, 20),
                         (rr.left + 6, cy), (rr.right - 6, cy), 1)
    else:
        single = pygame.Rect(cx - 7, cy - 7, 14, 14)
        pygame.draw.rect(surf, C_WHITE, single, border_radius=2)
        pygame.draw.rect(surf, darker(col, 40), single, 1, border_radius=2)


def _render_size_portal(surf, s, frame_t, t):
    """Mini/Big portal — shows two cubes of different size, arrow between."""
    col = TYPE_COLS[t]
    rr = _render_portal_hq(surf, s, col, frame_t, inner_scale=0.65)
    cx, cy = rr.centerx, rr.centery
    # Left: big cube, Right: small cube (or reversed for T_MODE_BIG)
    if t == T_MODE_MINI:
        big_r = pygame.Rect(cx - 13, cy - 8, 16, 16)
        small_r = pygame.Rect(cx + 5, cy - 4, 8, 8)
        arrow_pts = [(cx + 1, cy - 3), (cx + 5, cy), (cx + 1, cy + 3)]
    else:
        small_r = pygame.Rect(cx - 11, cy - 4, 8, 8)
        big_r = pygame.Rect(cx - 3, cy - 8, 16, 16)
        arrow_pts = [(cx - 5, cy - 3), (cx - 1, cy), (cx - 5, cy + 3)]
    pygame.draw.rect(surf, C_WHITE, big_r, border_radius=2)
    pygame.draw.rect(surf, darker(col, 40), big_r, 1, border_radius=2)
    pygame.draw.rect(surf, C_WHITE, small_r, border_radius=1)
    pygame.draw.rect(surf, darker(col, 40), small_r, 1, border_radius=1)
    pygame.draw.polygon(surf, C_WHITE, arrow_pts)


def _render_mode_portal(surf, s, frame_t, t):
    col = TYPE_COLS[t]
    rr = _render_portal_hq(surf, s, col, frame_t, inner_scale=0.6)
    cx, cy = rr.centerx, rr.centery
    # Draw the mode's icon inside the portal
    if t == T_MODE_CUBE:
        r = pygame.Rect(cx - 9, cy - 9, 18, 18)
        pygame.draw.rect(surf, C_WHITE, r, border_radius=3)
        pygame.draw.rect(surf, darker(C_WHITE, 30), r, 1, border_radius=3)
        pygame.draw.rect(surf, darker(col, 40), r.inflate(-8, -8), border_radius=2)
    elif t == T_MODE_SHIP:
        pts = [(cx - 10, cy), (cx + 8, cy - 7), (cx + 8, cy + 7)]
        pygame.draw.polygon(surf, C_WHITE, pts)
        pygame.draw.polygon(surf, darker(col, 40), pts, 1)
        pygame.draw.polygon(surf, (255, 180, 80),
                            [(cx - 10, cy), (cx - 16, cy - 4), (cx - 16, cy + 4)])
    elif t == T_MODE_BALL:
        pygame.draw.circle(surf, C_WHITE, (cx, cy), 9)
        pygame.draw.circle(surf, darker(col, 40), (cx, cy), 9, 2)
        pygame.draw.circle(surf, darker(col, 30), (cx, cy), 3)
    elif t == T_MODE_WAVE:
        pts = [(cx, cy - 10), (cx + 10, cy), (cx, cy + 10), (cx - 10, cy)]
        pygame.draw.polygon(surf, C_WHITE, pts)
        pygame.draw.polygon(surf, darker(col, 40), pts, 1)
        pygame.draw.polygon(surf, darker(col, 20),
                            [(cx, cy - 4), (cx + 4, cy), (cx, cy + 4), (cx - 4, cy)])
    elif t == T_MODE_UFO:
        dome = pygame.Rect(cx - 7, cy - 8, 14, 10)
        pygame.draw.ellipse(surf, C_WHITE, dome)
        body = pygame.Rect(cx - 11, cy - 2, 22, 8)
        pygame.draw.ellipse(surf, C_WHITE, body)
        pygame.draw.ellipse(surf, darker(col, 40), body, 1)
        for ox in (-6, 0, 6):
            pygame.draw.circle(surf, darker(col, 40), (cx + ox, cy + 4), 1)
    elif t == T_MODE_SPIDER:
        pygame.draw.circle(surf, C_WHITE, (cx, cy), 6)
        pygame.draw.circle(surf, darker(col, 40), (cx, cy), 6, 1)
        for ox in (-9, 9):
            for oy in (-6, 6):
                pygame.draw.line(surf, C_WHITE, (cx, cy), (cx + ox, cy + oy), 2)
    elif t == T_MODE_SWING:
        # Vertical lozenge with up- and down-pointing arrowheads to
        # signal the bidirectional grav-flip mechanic.
        pts = [(cx, cy - 11), (cx + 6, cy), (cx, cy + 11), (cx - 6, cy)]
        pygame.draw.polygon(surf, C_WHITE, pts)
        pygame.draw.polygon(surf, darker(col, 40), pts, 1)
        pygame.draw.polygon(surf, darker(col, 20),
                            [(cx, cy - 5), (cx + 3, cy), (cx, cy + 5), (cx - 3, cy)])
    elif t == T_MODE_ROBOT:
        # Boxy head + visor band + flame at the base, signalling the
        # held-thrust booster mechanic.
        body = pygame.Rect(cx - 8, cy - 9, 16, 14)
        pygame.draw.rect(surf, C_WHITE, body, border_radius=2)
        pygame.draw.rect(surf, darker(col, 40), body, 1, border_radius=2)
        visor = pygame.Rect(cx - 6, cy - 6, 12, 4)
        pygame.draw.rect(surf, darker(col, 30), visor, border_radius=1)
        # Booster flame underneath
        pygame.draw.polygon(surf, (255, 180, 80),
                            [(cx - 5, cy + 5), (cx + 5, cy + 5), (cx, cy + 11)])


def _render_speed_portal(surf, s, frame_t, t):
    col = TYPE_COLS[t]
    rr = _render_portal_hq(surf, s, col, frame_t, inner_scale=0.55)
    count = {T_SPEED_SLOW: 1, T_SPEED_NORMAL: 2, T_SPEED_FAST: 3,
             T_SPEED_FASTER: 4, T_SPEED_FASTEST: 5}[t]
    _speed_arrows(surf, rr, count)


def _render_start(surf, s, frame_t):
    cx, cy = s // 2, s // 2
    r_outer = s // 2 - 6
    _glow(surf, (cx, cy), r_outer - 2, C_PLAYER, max_alpha=60, layers=6)
    pygame.draw.circle(surf, C_WHITE, (cx, cy), r_outer, 3)
    pygame.draw.circle(surf, lighter(C_PLAYER, 35), (cx, cy), r_outer - 6, 2)
    arrow = [(cx - 10, cy - 5), (cx + 3, cy - 5), (cx + 3, cy - 10),
             (cx + 12, cy), (cx + 3, cy + 10), (cx + 3, cy + 5), (cx - 10, cy + 5)]
    pygame.draw.polygon(surf, C_PLAYER, arrow)
    pygame.draw.polygon(surf, darker(C_PLAYER, 40), arrow, 1)


def _render_coin(surf, s, frame_t):
    cx, cy = s // 2, s // 2
    wobble = math.sin(frame_t * math.tau)
    r_outer = int(s * 0.34)
    # Glow halo
    _glow(surf, (cx, cy), r_outer, C_COIN, max_alpha=90, layers=8)
    body_w = max(6, r_outer * 2 - int(abs(wobble) * r_outer * 0.35))
    coin_rect = pygame.Rect(cx - body_w // 2, cy - r_outer, body_w, r_outer * 2)
    # Shadow
    _drop_shadow(surf, coin_rect, offset=3, alpha=80, border_radius=body_w // 2)
    # Body gradient
    grad = pygame.Surface((coin_rect.w, coin_rect.h), pygame.SRCALPHA)
    for y in range(coin_rect.h):
        t = y / max(1, coin_rect.h - 1)
        col = lerp_col(lighter(C_COIN, 80), darker(C_COIN, 30), t)
        pygame.draw.line(grad, col, (0, y), (coin_rect.w - 1, y))
    mask = pygame.Surface((coin_rect.w, coin_rect.h), pygame.SRCALPHA)
    pygame.draw.ellipse(mask, (255, 255, 255, 255), mask.get_rect())
    grad.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
    surf.blit(grad, coin_rect.topleft)
    # Rim
    pygame.draw.ellipse(surf, darker(C_COIN, 50), coin_rect, 2)
    pygame.draw.ellipse(surf, lighter(C_COIN, 100), coin_rect.inflate(-6, -6), 1)
    # Center star/symbol
    txt(surf, "★", cx, cy, int(s * 0.28), darker(C_COIN, 50), True, shadow=True)
    # Specular streak
    spec = pygame.Surface((coin_rect.w, coin_rect.h // 3), pygame.SRCALPHA)
    pygame.draw.ellipse(spec, (255, 255, 255, 120), spec.get_rect())
    surf.blit(spec, (coin_rect.x, coin_rect.y + 2))


def _render_checkpoint(surf, s, frame_t):
    cx = s // 2
    # Base
    base = pygame.Rect(cx - 10, s - 12, 20, 8)
    pygame.draw.ellipse(surf, darker(C_CHECKPOINT, 40), base)
    pygame.draw.ellipse(surf, C_CHECKPOINT, base.inflate(-3, -3))
    # Pole
    pygame.draw.rect(surf, (220, 220, 230), (cx - 2, 6, 3, s - 14))
    pygame.draw.rect(surf, (160, 160, 180), (cx + 1, 6, 1, s - 14))
    # Flag — pulses slightly
    wave = int(3 * math.sin(frame_t * math.tau))
    flag_pts = [(cx + 1, 8),
                (cx + 16 + wave, 12 + wave // 2),
                (cx + 14 + wave, 17 + wave // 2),
                (cx + 1, 22)]
    pygame.draw.polygon(surf, C_CHECKPOINT, flag_pts)
    pygame.draw.polygon(surf, darker(C_CHECKPOINT, 40), flag_pts, 1)
    # Highlight on flag
    pygame.draw.line(surf, lighter(C_CHECKPOINT, 80),
                     (cx + 2, 10), (cx + 12 + wave // 2, 13 + wave // 2), 1)


def _render_deco_crystal(surf, s, frame_t):
    cx, cy = s // 2, s // 2
    pts = [(cx, 6), (s - 10, cy), (cx, s - 6), (10, cy)]
    # Drop shadow
    shadow_pts = [(p[0], p[1] + 3) for p in pts]
    pygame.draw.polygon(surf, (0, 0, 0, 80), shadow_pts)
    # Body
    pygame.draw.polygon(surf, C_DECO_CRYSTAL, pts)
    # Facet lines
    pygame.draw.line(surf, lighter(C_DECO_CRYSTAL, 80), (cx, 6), (cx, s - 6), 1)
    pygame.draw.line(surf, lighter(C_DECO_CRYSTAL, 80), (10, cy), (s - 10, cy), 1)
    # Upper-left facet highlight
    hi = [(cx, 6), (cx - 2, cy), (10, cy), (cx - 2, cy - 6)]
    pygame.draw.polygon(surf, lighter(C_DECO_CRYSTAL, 60), hi)
    # Outline
    pygame.draw.polygon(surf, lighter(C_DECO_CRYSTAL, 40), pts, 2)


def _render_deco_pillar(surf, s, frame_t):
    w = 22
    body = pygame.Rect(s // 2 - w // 2, 4, w, s - 8)
    _vgradient(surf, body, lighter(C_DECO_PILLAR, 40),
               darker(C_DECO_PILLAR, 30), border_radius=2)
    # Inner shine column
    pygame.draw.rect(surf, lighter(C_DECO_PILLAR, 80),
                     (s // 2 - 4, 8, 4, s - 16), border_radius=1)
    # Capstones
    cap_top = pygame.Rect(s // 2 - w // 2 - 2, 2, w + 4, 6)
    pygame.draw.rect(surf, lighter(C_DECO_PILLAR, 20), cap_top, border_radius=2)
    pygame.draw.rect(surf, darker(C_DECO_PILLAR, 30), cap_top, 1, border_radius=2)
    cap_bot = pygame.Rect(s // 2 - w // 2 - 2, s - 8, w + 4, 6)
    pygame.draw.rect(surf, lighter(C_DECO_PILLAR, 20), cap_bot, border_radius=2)
    pygame.draw.rect(surf, darker(C_DECO_PILLAR, 30), cap_bot, 1, border_radius=2)


def _render_deco_glow(surf, s, frame_t):
    cx, cy = s // 2, s // 2
    r = 4 + 2 * math.sin(frame_t * math.tau)
    r = int(r)
    _glow(surf, (cx, cy), r, C_DECO_GLOW, max_alpha=70, layers=8)
    pygame.draw.circle(surf, C_DECO_GLOW, (cx, cy), r)
    pygame.draw.circle(surf, C_WHITE, (cx, cy), max(1, r - 2))


def _render_jump_predictor(surf, s, frame_t):
    """Editor probe icon: dashed crosshair + small arc, on a faint panel
    so the probe stays legible against any background. Intentionally a
    schematic — the user should not confuse it with a gameplay object."""
    col = TYPE_COLS.get(T_JUMP_PREDICTOR, (255, 235, 120))
    rect = pygame.Rect(6, 6, s - 12, s - 12)
    panel = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
    panel.fill((0, 0, 0, 110))
    surf.blit(panel, rect.topleft)
    pygame.draw.rect(surf, col, rect, 2, border_radius=6)
    cx, cy = s // 2, s // 2
    r = int(s * 0.22)
    pygame.draw.circle(surf, col, (cx, cy), r, 2)
    # Crosshair ticks.
    pygame.draw.line(surf, col, (cx - r - 6, cy), (cx - r - 2, cy), 2)
    pygame.draw.line(surf, col, (cx + r + 2, cy), (cx + r + 6, cy), 2)
    pygame.draw.line(surf, col, (cx, cy - r - 6), (cx, cy - r - 2), 2)
    pygame.draw.line(surf, col, (cx, cy + r + 2), (cx, cy + r + 6), 2)
    # Small preview arc from the circle up-and-right, suggesting a jump.
    arc_rect = pygame.Rect(cx - 2, cy - int(s * 0.38),
                           int(s * 0.55), int(s * 0.55))
    try:
        pygame.draw.arc(surf, lighter(col, 40), arc_rect,
                        math.radians(200), math.radians(340), 2)
    except (pygame.error, ValueError):
        pass


def _render_bot_checkpoint(surf, s, frame_t):
    """Bot checkpoint icon: a target reticle with a small flag glyph.
    Distinct enough from the jump probe (yellow square) and from coins
    (round) that authors don't confuse them at a glance."""
    col = TYPE_COLS.get(T_BOT_CHECKPOINT, (120, 230, 255))
    cx, cy = s // 2, s // 2
    # Faint backing panel — keeps the checkpoint legible against any
    # background without dominating it.
    rect = pygame.Rect(6, 6, s - 12, s - 12)
    panel = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
    panel.fill((0, 0, 0, 100))
    surf.blit(panel, rect.topleft)
    # Concentric rings (target reticle).
    r_outer = int(s * 0.34)
    r_mid = int(s * 0.22)
    r_inner = max(2, int(s * 0.10))
    pygame.draw.circle(surf, col, (cx, cy), r_outer, 2)
    pygame.draw.circle(surf, lighter(col, 30), (cx, cy), r_mid, 2)
    pygame.draw.circle(surf, C_WHITE, (cx, cy), r_inner)
    # Crosshair ticks at cardinals.
    pygame.draw.line(surf, col, (cx - r_outer - 4, cy),
                     (cx - r_outer - 1, cy), 2)
    pygame.draw.line(surf, col, (cx + r_outer + 1, cy),
                     (cx + r_outer + 4, cy), 2)
    pygame.draw.line(surf, col, (cx, cy - r_outer - 4),
                     (cx, cy - r_outer - 1), 2)
    pygame.draw.line(surf, col, (cx, cy + r_outer + 1),
                     (cx, cy + r_outer + 4), 2)


def _render_trigger(surf, s, t):
    col = TYPE_COLS.get(t, C_GRAY)
    rect = pygame.Rect(5, 5, s - 10, s - 10)
    _vgradient(surf, rect, lighter(col, 40), darker(col, 30), border_radius=6)
    pygame.draw.rect(surf, darker(col, 30), rect, 2, border_radius=6)
    pygame.draw.rect(surf, lighter(col, 80), rect.inflate(-4, -4), 1, border_radius=4)
    if t == T_CAMERA_TRIGGER:
        cx, cy = s // 2, s // 2
        pygame.draw.rect(surf, C_WHITE, (cx - 9, cy - 6, 14, 10), 2)
        pygame.draw.rect(surf, C_WHITE, (cx + 3, cy - 3, 5, 4))
    elif t == T_TIME_WARP:
        # Stopwatch glyph: a circle (the dial) + two hands. The dial
        # outline reads as the "T" of time warp; the offset hands give
        # it a clock vibe so authors don't confuse it with the rotate
        # trigger (which is also circular).
        cx, cy = s // 2, s // 2
        r = max(4, s // 3)
        pygame.draw.circle(surf, C_WHITE, (cx, cy), r, 2)
        # Tick at the 12-o'clock position.
        pygame.draw.line(surf, C_WHITE, (cx, cy - r),
                         (cx, cy - r + 3), 2)
        # Hour hand toward 11; minute hand toward 3.
        pygame.draw.line(surf, C_WHITE, (cx, cy),
                         (cx - r // 2, cy - r // 2), 2)
        pygame.draw.line(surf, C_WHITE, (cx, cy),
                         (cx + int(r * 0.7), cy), 2)
    else:
        label = {T_BG_TRIGGER: "BG", T_MOVE_TRIGGER: "MV",
                 T_COLOR_TRIGGER: "CL", T_PULSE_TRIGGER: "PL",
                 T_ROTATE_TRIGGER: "RT", T_FOLLOW_TRIGGER: "FL"}.get(t, "?")
        txt(surf, label, s // 2, s // 2, max(10, s // 4), C_WHITE, True, shadow=True)


# ---- Dispatcher: render one sprite at a given size & frame -----------------
# Table-driven sprite dispatch. Adding a new object type now means adding
# a renderer function and one entry here (plus TYPE_COLS / editor palette
# as before). The old if/elif chain was 55 lines and required adding
# branches *after* the MODE_FROM_TYPE catch-all in the right order — the
# table is order-insensitive because direct-type keys beat the set-membership
# fallbacks below.
_DIRECT_RENDERERS = {
    T_BLOCK:       lambda s, b, f, v: _render_block(s, b, f),
    T_SLAB:        lambda s, b, f, v: _render_slab(s, b, f),
    T_SLOPE:       lambda s, b, f, v: _render_slope(s, b, f),
    T_SPIKE:       lambda s, b, f, v: _render_spike(s, b, f, half=False),
    T_HALF_SPIKE:  lambda s, b, f, v: _render_spike(s, b, f, half=True),
    T_SAW:         lambda s, b, f, v: _render_saw(s, b, f),
    T_ORB:         lambda s, b, f, v: _render_orb(s, b, f),
    T_DASH_ORB:    lambda s, b, f, v: _render_dash_orb(s, b, f),
    T_DASH_ORB_GRAV: lambda s, b, f, v: _render_dash_orb(s, b, f,
                                                        C_DASH_ORB_GRAV),
    T_TELEPORT_ORB: lambda s, b, f, v: _render_teleport_orb(s, b, f, link_label=v),
    T_BLACK_ORB:   lambda s, b, f, v: _render_black_orb(s, b, f),
    T_BLUE_ORB:    lambda s, b, f, v: _render_blue_orb(s, b, f),
    T_GREEN_ORB:   lambda s, b, f, v: _render_green_orb(s, b, f),
    T_RED_ORB:     lambda s, b, f, v: _render_red_orb(s, b, f),
    T_PINK_ORB:    lambda s, b, f, v: _render_pink_orb(s, b, f),
    T_SPIDER_ORB:  lambda s, b, f, v: _render_spider_orb(s, b, f, v),
    T_SPEED_FASTEST: lambda s, b, f, v: _render_speed_portal(s, b, f,
                                                            T_SPEED_FASTEST),
    T_PAD:         lambda s, b, f, v: _render_pad(s, b, f, C_PAD),
    T_PINK_PAD:    lambda s, b, f, v: _render_pad(s, b, f, C_PINK_PAD),
    T_RED_PAD:     lambda s, b, f, v: _render_pad(s, b, f, C_RED_PAD),
    T_BLUE_PAD:    lambda s, b, f, v: _render_pad(s, b, f, C_BLUE_PAD, "flip"),
    T_SPIDER_PAD:  lambda s, b, f, v: _render_pad(s, b, f, C_SPIDER_PAD,
                                                  "spider"),
    T_GRAV_UP:     lambda s, b, f, v: _render_grav(s, b, f, "up"),
    T_GRAV_DOWN:   lambda s, b, f, v: _render_grav(s, b, f, "down"),
    T_END:         lambda s, b, f, v: _render_end(s, b, f),
    T_START:       lambda s, b, f, v: _render_start(s, b, f),
    T_COIN:        lambda s, b, f, v: _render_coin(s, b, f),
    T_CHECKPOINT:  lambda s, b, f, v: _render_checkpoint(s, b, f),
    T_DECO_CRYSTAL: lambda s, b, f, v: _render_deco_crystal(s, b, f),
    T_DECO_PILLAR:  lambda s, b, f, v: _render_deco_pillar(s, b, f),
    T_DECO_GLOW:    lambda s, b, f, v: _render_deco_glow(s, b, f),
    T_JUMP_PREDICTOR: lambda s, b, f, v: _render_jump_predictor(s, b, f),
    T_BOT_CHECKPOINT: lambda s, b, f, v: _render_bot_checkpoint(s, b, f),
}

_TRIGGER_TYPES_SET = TRIGGER_TYPES

_SIZE_PORTAL_TYPES = {T_MODE_MINI, T_MODE_BIG}
_DUAL_PORTAL_TYPES = {T_MODE_DUAL, T_MODE_SOLO}


def _render_sprite(t, s, frame_t, variant=None):
    """Render ONE sprite to a new (s,s) SRCALPHA surface.

    Rendering happens at 2x then downscales with smoothscale for free AA.
    """
    big = s * _SUPERSAMPLE
    surf = pygame.Surface((big, big), pygame.SRCALPHA)
    fn = _DIRECT_RENDERERS.get(t)
    if fn is not None:
        fn(surf, big, frame_t, variant)
    elif t in _SIZE_PORTAL_TYPES:
        _render_size_portal(surf, big, frame_t, t)
    elif t in _DUAL_PORTAL_TYPES:
        _render_dual_portal(surf, big, frame_t, t)
    elif t in MODE_FROM_TYPE:
        _render_mode_portal(surf, big, frame_t, t)
    elif t in SPEED_VALUES:
        _render_speed_portal(surf, big, frame_t, t)
    elif t in _TRIGGER_TYPES_SET:
        _render_trigger(surf, big, t)
    else:
        col = TYPE_COLS.get(t, (200, 200, 200))
        pygame.draw.rect(surf, col, (12, 12, big - 24, big - 24), border_radius=10)
    # Downsample for free AA
    return pygame.transform.smoothscale(surf, (s, s))


def _load_or_render(t, s, frame, variant=None):
    key = (t, s, frame, variant)
    cached = _OBJECT_CACHE.get(key)
    if cached is not None:
        _OBJECT_CACHE.move_to_end(key)
        return cached
    # Try to load from disk (only non-variant sprites are cached on disk).
    # The user cache is checked first so it overrides the bundled sprite
    # after a version-bump rebake; if that misses we fall back to the
    # read-only bundled dir, and only then do we render from scratch.
    if variant is None:
        for path in (_sprite_path(t, s, frame),
                     _bundled_sprite_path(t, s, frame)):
            if path and os.path.isfile(path):
                try:
                    img = pygame.image.load(path).convert_alpha()
                    _OBJECT_CACHE[key] = img
                    while len(_OBJECT_CACHE) > _OBJECT_CACHE_MAX:
                        _OBJECT_CACHE.popitem(last=False)
                    return img
                except (pygame.error, OSError):
                    pass
    frames = _frame_count(t)
    frame_t = (frame / frames) if frames > 0 else 0.0
    img = _render_sprite(t, s, frame_t, variant)
    _OBJECT_CACHE[key] = img
    # Persist rendered non-variant sprites to the USER cache so the next
    # launch avoids the rerender. Writes to the bundled dir are not
    # attempted (and would fail in a frozen build anyway).
    if variant is None:
        try:
            os.makedirs(SPRITES_DIR, exist_ok=True)
            pygame.image.save(img, _sprite_path(t, s, frame))
        except (pygame.error, OSError):
            pass
    # Evict least-recently-used entries to cap memory.
    while len(_OBJECT_CACHE) > _OBJECT_CACHE_MAX:
        _OBJECT_CACHE.popitem(last=False)
    return img


def draw_obj(surf, t, x, y, s=CELL, pulse=0, rot=0, meta=None,
             scale=1.0, scale_y=None):
    """Blit the pre-rendered sprite image for this object type.

    ``scale`` enlarges (or shrinks) the sprite around the cell center
    so scaled objects still occupy the same grid anchor. Accepts:
      * a uniform scalar (legacy)
      * a ``(sx, sy)`` tuple
      * a ``scale_y`` paired with a numeric ``scale`` (= sx)

    When ``sx != sy`` the sprite is stretched non-uniformly via
    ``pygame.transform.scale``; the cached square sprite stays the
    canonical render so other zoom levels still hit the cache.
    """
    # Visual rotation accepts any angle now (free rotation feature) —
    # only the collision helpers (slab_rect, spike_hitboxes,
    # pad_trigger_rect) round to the nearest 90°. For a clean blit at
    # cardinal angles, snap exact-90° values to int via normalize.
    try:
        rot_visual = float(rot) % 360.0
    except (TypeError, ValueError):
        rot_visual = 0.0
    if abs(rot_visual - round(rot_visual / 90.0) * 90.0) < 1e-3:
        rot_visual = normalize_rotation(rot_visual)
    rot = rot_visual
    variant = None
    if t == T_TELEPORT_ORB and meta is not None:
        # Pick a sprite variant per group_id so visually-distinct orb pairs
        # are easy to spot. Reads the legacy "link" field too for backwards
        # compat with levels saved before the rename.
        gid = meta.get("group_id")
        if gid is None:
            gid = meta.get("link")
        if gid:
            try:
                variant = int(gid)
            except (TypeError, ValueError):
                variant = None
    elif t in (T_SPIDER_ORB, T_SPIDER_PAD) and meta is not None:
        # Direction-aware spider sprite — "up" / "down" / "left" / "right"
        # render distinct arrow pairs so the editor preview matches what
        # the orb will actually do at play time.
        d = str(meta.get("dir", "")).lower()
        if d in ("up", "down", "left", "right"):
            variant = d
    sx, sy = _resolve_scale(scale, scale_y)
    frames = _frame_count(t)
    frame = int(pulse / (60 / frames)) % frames if frames > 1 else 0
    if sx != 1.0 or sy != 1.0:
        # Non-uniform path: render the sprite at the larger axis (so
        # the smaller axis can shrink without rounding artefacts), then
        # stretch to (sw, sh). One transform.scale per blit — caches
        # don't help here because every sx/sy combination is unique.
        img = _load_or_render(t, s, frame, variant)
        sw = max(1, int(round(s * sx)))
        sh = max(1, int(round(s * sy)))
        if (sw, sh) != img.get_size():
            img = pygame.transform.scale(img, (sw, sh))
        x = x + (s - sw) / 2.0
        y = y + (s - sh) / 2.0
        if rot:
            rotated = pygame.transform.rotate(img, -rot)
            rr = rotated.get_rect(center=(x + sw / 2, y + sh / 2))
            surf.blit(rotated, rr)
        else:
            surf.blit(img, (x, y))
        return
    img = _load_or_render(t, s, frame, variant)
    if rot:
        rotated = pygame.transform.rotate(img, -rot)
        rr = rotated.get_rect(center=(x + s / 2, y + s / 2))
        surf.blit(rotated, rr)
    else:
        surf.blit(img, (x, y))


def clear_obj_cache():
    """Drop cached sprites — call on palette change or resolution change."""
    _OBJECT_CACHE.clear()


def draw_end_wall(surf, screen_x, marker_screen_y, cell_size=CELL, pulse=0):
    """Draw the win-line as a glowing infinite-height column.

    ``screen_x`` is the wall column's left edge in screen pixels.
    ``marker_screen_y`` is where the small flag marker sits — usually the
    cell the level designer placed T_END at, projected to screen coords.
    The wall itself spans the full visible height; the marker just gives
    a visual handle in the editor and pre-win flair in play.
    """
    surf_h = surf.get_height()
    pulse_t = (pulse % 60) / 60.0
    pulse_a = int(70 + 50 * math.sin(pulse_t * math.tau))
    # Translucent inner column
    col_w = max(4, cell_size // 4)
    col_x = int(screen_x + (cell_size - col_w) / 2)
    glow = pygame.Surface((col_w + 16, surf_h), pygame.SRCALPHA)
    pygame.draw.rect(glow, (*C_END, pulse_a // 3),
                     glow.get_rect(), border_radius=cell_size // 4)
    surf.blit(glow, (col_x - 8, 0))
    # Bright core line
    core = pygame.Surface((col_w, surf_h), pygame.SRCALPHA)
    core.fill((*C_END, min(255, 160 + pulse_a // 2)))
    surf.blit(core, (col_x, 0))
    # White centerline for crispness
    pygame.draw.line(surf, C_WHITE,
                     (col_x + col_w // 2, 0),
                     (col_x + col_w // 2, surf_h), 2)
    # Flag marker at the placed cell so editors can see where it was put.
    flag_w = max(8, cell_size - 12)
    flag_h = max(6, cell_size // 2)
    fr = pygame.Rect(int(screen_x + (cell_size - flag_w) / 2),
                     int(marker_screen_y + (cell_size - flag_h) / 2),
                     flag_w, flag_h)
    pygame.draw.rect(surf, C_WHITE, fr)
    cells = 4
    cw = max(1, fr.w // cells)
    ch = max(1, fr.h // cells)
    for i in range(cells):
        for j in range(cells):
            if (i + j) % 2 == 0:
                pygame.draw.rect(surf, (20, 20, 30),
                                 (fr.x + i * cw, fr.y + j * ch, cw, ch))
    pygame.draw.rect(surf, lighter(C_END, 60), fr, 2)


def regenerate_sprite_assets(size=CELL):
    """Force-regenerate every sprite PNG at the given size.

    Useful after tweaking the rendering code — deletes any existing PNG
    for each (type, frame) and recomputes it so future loads pick up the
    new art.
    """
    from .objects import ALL_TYPES
    os.makedirs(SPRITES_DIR, exist_ok=True)
    _OBJECT_CACHE.clear()
    for t in ALL_TYPES:
        for f in range(_frame_count(t)):
            path = _sprite_path(t, size, f)
            try:
                if os.path.isfile(path):
                    os.remove(path)
            except OSError:
                pass
            _load_or_render(t, size, f)

