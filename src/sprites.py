"""Object sprites: per-type renderers, the on-disk/in-memory sprite cache,
and :func:`draw_obj`.

Sprites are rendered once at 2x, downsampled for anti-aliasing, and saved
as PNGs under the per-user ``sprite_cache/`` dir (and shipped pre-baked in
``assets/sprites``).  ``SPRITE_CACHE_VERSION`` must be bumped whenever a
renderer's output changes so stale PNGs are regenerated.
"""

import hashlib
import math
import os
from collections import OrderedDict

import pygame

from .constants import (
    ASSETS_DIR, CELL, _USER_DATA, TRIGGER_TYPES, PHYSICS_TPS,
    C_WHITE, C_GRAY, C_BLOCK_H, C_BLOCK_D, C_BLOCK_INNER,
    C_SPIKE, C_SAW, C_ORB, C_DASH_ORB,
    C_DASH_ORB_GRAV, C_TELEPORT_ORB, C_TELEPORT_PORTAL,
    C_GREEN_ORB, C_SPIDER_ORB, C_RED_ORB,
    C_PINK_ORB, C_PAD, C_PINK_PAD, C_RED_PAD, C_BLUE_PAD, C_SPIDER_PAD,
    C_GPORTAL_UP, C_GPORTAL_DOWN, C_END, C_PLAYER, C_DECO_CRYSTAL,
    C_DECO_PILLAR, C_DECO_GLOW, C_COIN, C_CHECKPOINT,
    C_JUMP_BLOCK, C_WAVE_BLOCK, C_BONK_BLOCK, C_ITEM_PICKUP,
    C_ITEM_COUNTER, C_KEYFRAME,
    SPEED_VALUES, MODE_FROM_TYPE,
    T_BLOCK, T_SLAB, T_SLOPE, T_SPIKE, T_HALF_SPIKE, T_SAW, T_ORB, T_DASH_ORB,
    T_DASH_ORB_GRAV, T_TELEPORT_ORB, T_TELEPORT_PORTAL,
    T_BLACK_ORB, T_BLUE_ORB, T_GREEN_ORB,
    T_SPIDER_ORB, T_RED_ORB, T_PINK_ORB,
    T_PAD, T_PINK_PAD, T_RED_PAD, T_BLUE_PAD, T_SPIDER_PAD,
    T_GRAV_UP, T_GRAV_DOWN, T_END, T_START, T_COIN, T_CHECKPOINT,
    T_MODE_CUBE, T_MODE_SHIP, T_MODE_BALL, T_MODE_WAVE, T_MODE_UFO,
    T_MODE_SPIDER, T_MODE_SWING, T_MODE_ROBOT, T_MODE_MINI, T_MODE_BIG,
    T_MODE_DUAL, T_MODE_SOLO,
    T_DECO_CRYSTAL, T_DECO_PILLAR, T_DECO_GLOW,
    T_CAMERA_TRIGGER, T_BG_TRIGGER, T_MOVE_TRIGGER, T_COLOR_TRIGGER,
    T_PULSE_TRIGGER, T_ROTATE_TRIGGER, T_FOLLOW_TRIGGER, T_TIME_WARP,
    T_BLACKOUT_TRIGGER,
    T_GROUND_TRIGGER, T_MG_TRIGGER, T_BG_SPEED_TRIGGER, T_MG_SPEED_TRIGGER,
    T_UI_TRIGGER, T_EVENT_TRIGGER, T_END_TRIGGER,
    T_JUMP_PREDICTOR, T_BOT_CHECKPOINT, T_DASH_STOP,
    T_ITEM_PICKUP, T_ITEM_COUNTER, T_JUMP_BLOCK, T_WAVE_BLOCK, T_BONK_BLOCK,
    T_KEYFRAME,
    T_SPEED_SLOW, T_SPEED_NORMAL, T_SPEED_FAST, T_SPEED_FASTER,
    T_SPEED_FASTEST,
)
from . import gd_atlas
from .objects import TYPE_COLS, ANIMATED_TYPES
from .geometry import normalize_rotation, _resolve_scale, clamp
from .graphics import (
    txt, lighter, darker, lerp_col, draw_bevel_rect, draw_bevel_circle,
    draw_gloss, draw_outlined_poly, outline_col,
)

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
SPRITE_CACHE_VERSION = "8"
BUNDLED_SPRITES_DIR = os.path.join(ASSETS_DIR, "sprites")
SPRITES_DIR = os.path.join(_USER_DATA, "sprite_cache")
_SPRITE_VERSION_MARKER = os.path.join(SPRITES_DIR, ".version")
SPRITE_FRAMES = 8            # animation frames baked per animated type
_SUPERSAMPLE = 2             # render at this multiple, smooth-scale down
_OBJECT_CACHE = OrderedDict()  # (t, s, frame, variant) -> Surface; LRU-ordered
_OBJECT_CACHE_MAX = 600


def sprite_cache_signature():
    """What the cached PNGs on disk were baked from.

    The renderer version alone is not enough now that art can also come
    from the optional real-GD atlas: installing or removing those sheets
    changes every mapped sprite without touching any code, so the
    signature carries their presence too — and, past that, a digest of
    the atlas recipe itself.

    That digest is what stops a half-stale cache.  Editing a frame name,
    a tint, a ``fit`` or a ``spin`` in ``GD_SPRITE_MAP`` changes what
    every affected sprite bakes to, and only some of a type's eight
    frames are usually on disk at any moment; without the digest, the
    already-cached frames keep rendering under the OLD recipe while the
    rest render under the new one, and the animation flickers once per
    loop.  Hand-bumping SPRITE_CACHE_VERSION prevented that only when
    somebody remembered to.
    """
    if not gd_atlas.atlas_installed():
        return SPRITE_CACHE_VERSION
    # The installed resolution tier is part of the recipe: the same frame
    # names off the -hd sheets bake to visibly sharper PNGs, so dropping
    # those sheets in (or removing them) has to invalidate the cache on
    # its own, exactly as editing a frame name does.
    recipe = (GD_ART_RECIPE, sorted(gd_atlas.installed_tiers().items()))
    digest = hashlib.sha1(repr(recipe).encode()).hexdigest()[:8]
    return f"{SPRITE_CACHE_VERSION}+gd{digest}"


def _check_sprite_cache_version():
    """Wipe the writable sprite cache when the signature changes.

    Prevents stale PNGs (from an older render pass) from shadowing the
    current renderer's output — that was the "asset glitch" class where
    a user who updated the game saw the old visuals.
    """
    try:
        os.makedirs(SPRITES_DIR, exist_ok=True)
    except OSError:
        return
    want = sprite_cache_signature()
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
            return f.read().strip() == sprite_cache_signature()
    except OSError:
        return False


# Set by init_sprite_cache() at the bottom of the module — the signature
# it checks against hashes GD_ART_RECIPE, which is defined further down.
_BUNDLED_OK = False


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
    """Soft top highlight — one-sided gradient, fading from top.

    Drawn into a scratch surface and blitted: ``pygame.draw`` *writes*
    alpha rather than blending it, so painting these translucent lines
    straight onto the sprite punched a transparent band through the top
    of every block, slab and portal.
    """
    h = max(2, int(rect.h * height_frac))
    w = max(1, rect.w - 4)
    layer = pygame.Surface((w, h), pygame.SRCALPHA)
    for y in range(h):
        t = y / max(1, h - 1)
        a = int(alpha * (1 - t) ** 2)
        if a <= 0:
            continue
        pygame.draw.line(layer, (255, 255, 255, a), (0, y), (w - 1, y))
    surf.blit(layer, (rect.x + 2, rect.y))


def _drop_shadow(surf, rect, offset=3, alpha=80, border_radius=0):
    sh = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
    pygame.draw.rect(sh, (0, 0, 0, alpha), sh.get_rect(), border_radius=border_radius)
    surf.blit(sh, (rect.x, rect.y + offset))


# ---- Helper: orb with consistent glow + core + highlight ------------------
def _render_orb_hq(surf, col, s, frame_t, outline_only=False, label=None,
                  inner_icon=None):
    """GD-style orb: glow halo, dark contour, colour annulus, bright core.

    ``outline_only`` renders the hollow "ring" orb family (dash / teleport
    / directional orbs); otherwise the orb gets a filled, glossy core.
    ``frame_t`` in [0,1) drives a gentle breathing pulse.
    """
    cx, cy = s // 2, s // 2
    pulse = 1.0 + 0.06 * math.sin(frame_t * math.tau)
    r = int(s * 0.30 * pulse)
    ring_w = max(2, int(s * 0.075))
    _glow(surf, (cx, cy), r, col, max_alpha=100, layers=8)
    # Dark contour first, so every subsequent ring sits inside a rim.
    pygame.draw.circle(surf, outline_col(col), (cx, cy), r + ring_w // 2 + 1)
    if outline_only:
        pygame.draw.circle(surf, col, (cx, cy), r, ring_w)
        pygame.draw.circle(surf, lighter(col, 90), (cx, cy),
                           r - ring_w // 3, max(1, ring_w // 3))
        # Faint interior tint keeps the hole from reading as a plain hole.
        tint = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
        pygame.draw.circle(tint, (*darker(col, 40), 70), (r, r),
                           r - ring_w)
        surf.blit(tint, (cx - r, cy - r))
    else:
        draw_bevel_circle(surf, (cx, cy), r, col,
                          outline=max(1, int(s * 0.02)), gloss=False)
        # Colour annulus + bright core — the two-band look of GD's orbs.
        pygame.draw.circle(surf, lighter(col, 70), (cx, cy),
                           int(r * 0.62))
        pygame.draw.circle(surf, darker(col, 55), (cx, cy),
                           int(r * 0.62), max(1, ring_w // 3))
        pygame.draw.circle(surf, lighter(col, 130), (cx, cy), int(r * 0.30))
    draw_gloss(surf, pygame.Rect(cx - r, cy - r, r * 2, r * 2), alpha=115,
               width_frac=0.5, height_frac=0.3)
    if label:
        txt(surf, label, cx, cy, int(s * 0.30), C_WHITE, True, shadow=True)
    if inner_icon:
        inner_icon(surf, cx, cy, r)


# ---- Helper: portal box with glow, gradient, inner core -------------------
def _render_portal_hq(surf, s, col, frame_t):
    """GD portal: a tall glowing pill-shaped ring with a dark inner plate.

    Returns the inner plate rect so per-portal glyph renderers can centre
    their icon in it.
    """
    cx = s // 2
    outer = pygame.Rect(int(s * 0.14), int(s * 0.02),
                        int(s * 0.72), int(s * 0.96))
    radius = outer.w // 2
    pulse = int(25 * math.sin(frame_t * math.tau))
    c = tuple(clamp(v + pulse, 0, 255) for v in col)
    glow = pygame.Surface((outer.w + int(s * 0.4), outer.h + int(s * 0.4)),
                          pygame.SRCALPHA)
    for i in range(6, 0, -1):
        a = int(70 * (1 - i / 6) ** 2)
        pygame.draw.rect(glow, (*c, a),
                         glow.get_rect().inflate(-i * int(s * 0.05),
                                                 -i * int(s * 0.05)),
                         border_radius=radius)
    surf.blit(glow, (outer.x - int(s * 0.2), outer.y - int(s * 0.2)))
    # Ring body: gradient shell, dark contour inside and out.
    _vgradient(surf, outer, lighter(c, 55), darker(c, 35),
               border_radius=radius)
    pygame.draw.rect(surf, darker(c, 95), outer, max(2, int(s * 0.025)),
                     border_radius=radius)
    ring = max(2, int(s * 0.07))
    inner = outer.inflate(-ring * 2, -ring * 2)
    _vgradient(surf, inner, darker(c, 70), darker(c, 40),
               border_radius=max(2, inner.w // 2))
    pygame.draw.rect(surf, darker(c, 95), inner, max(1, int(s * 0.02)),
                     border_radius=max(2, inner.w // 2))
    # Bright inner lip catches the light like GD's portal frames.
    pygame.draw.rect(surf, lighter(c, 90), outer.inflate(-ring, -ring),
                     max(1, int(s * 0.018)), border_radius=radius)
    # End caps: short bars that anchor the portal top and bottom.
    for cap_y in (outer.y - int(s * 0.01), outer.bottom - int(s * 0.05)):
        cap = pygame.Rect(cx - int(s * 0.20), cap_y, int(s * 0.40),
                          int(s * 0.06))
        draw_bevel_rect(surf, cap, darker(c, 25),
                        radius=max(1, int(s * 0.02)),
                        outline=max(1, int(s * 0.018)))
    _specular_highlight(surf, outer.inflate(-ring * 2, 0), alpha=55,
                        height_frac=0.3)
    return inner


def _speed_arrows(surf, rr, count):
    """Stacked chevrons inside a speed portal — one per speed step."""
    w = max(3, rr.w // 3)
    gap = max(2, rr.h // (count + 1))
    top = rr.centery - (count - 1) * gap // 2
    for i in range(count):
        cy = top + i * gap
        pts = [(rr.centerx - w, cy - w // 2), (rr.centerx, cy + w // 2),
               (rr.centerx + w, cy - w // 2)]
        pygame.draw.lines(surf, C_WHITE, False, pts, max(2, rr.w // 10))


# ---- Per-type HQ renderers ------------------------------------------------
def _render_block(surf, s, frame_t):
    """GD solid block: flat body, heavy contour, inset inner frame and
    corner studs — reads as a tile, not a flat rect."""
    rect = pygame.Rect(0, 0, s, s)
    _vgradient(surf, rect, lighter(C_BLOCK_H, 20), darker(C_BLOCK_D, 10),
               border_radius=max(1, int(s * 0.06)))
    line = max(2, int(s * 0.05))
    pygame.draw.rect(surf, darker(C_BLOCK_D, 70), rect, line,
                     border_radius=max(1, int(s * 0.06)))
    # Inset frame: GD blocks carry a bright inner outline a few px in.
    inset = max(2, int(s * 0.13))
    frame = rect.inflate(-inset * 2, -inset * 2)
    pygame.draw.rect(surf, lighter(C_BLOCK_H, 70), frame,
                     max(1, int(s * 0.035)),
                     border_radius=max(1, int(s * 0.04)))
    pygame.draw.rect(surf, darker(C_BLOCK_D, 40), frame.inflate(4, 4),
                     max(1, int(s * 0.015)),
                     border_radius=max(1, int(s * 0.04)))
    # Corner studs.
    stud = max(1, int(s * 0.035))
    for px in (inset // 2 + stud, s - inset // 2 - stud):
        for py in (inset // 2 + stud, s - inset // 2 - stud):
            pygame.draw.circle(surf, lighter(C_BLOCK_H, 90), (px, py), stud)
            pygame.draw.circle(surf, darker(C_BLOCK_D, 60), (px, py), stud, 1)
    _specular_highlight(surf, rect.inflate(-line * 2, -line * 2), alpha=55,
                        height_frac=0.35)


def _render_slab(surf, s, frame_t):
    """Half-height platform — same material treatment as the full block."""
    rect = pygame.Rect(0, s // 2, s, s - s // 2)
    _vgradient(surf, rect, lighter(C_BLOCK_H, 20), darker(C_BLOCK_D, 10),
               border_radius=max(1, int(s * 0.05)))
    line = max(2, int(s * 0.045))
    pygame.draw.rect(surf, darker(C_BLOCK_D, 70), rect, line,
                     border_radius=max(1, int(s * 0.05)))
    # Bright top lip: the surface the player actually lands on.
    lip = pygame.Rect(rect.x + line, rect.y + line,
                      rect.w - line * 2, max(2, int(s * 0.05)))
    pygame.draw.rect(surf, lighter(C_BLOCK_H, 90), lip,
                     border_radius=max(1, int(s * 0.02)))
    inset = max(2, int(s * 0.09))
    frame = rect.inflate(-inset * 2, -inset)
    frame.height = max(2, frame.height - inset // 2)
    pygame.draw.rect(surf, lighter(C_BLOCK_H, 45), frame,
                     max(1, int(s * 0.025)),
                     border_radius=max(1, int(s * 0.03)))


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
    # Body fill mirrors the block gradient so a slope next to a flat
    # block reads as the same material.
    grad = pygame.Surface((s, s), pygame.SRCALPHA)
    _vgradient(grad, pygame.Rect(0, 0, s, s),
               lighter(C_BLOCK_H, 20), darker(C_BLOCK_D, 10),
               border_radius=0)
    mask = pygame.Surface((s, s), pygame.SRCALPHA)
    pygame.draw.polygon(mask, (255, 255, 255, 255), pts)
    grad.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    base.blit(grad, (0, 0))
    # Inner frame echoing the block's inset outline, shrunk toward the
    # triangle's centroid.
    inset = max(2, int(s * 0.16))
    cxg = (0 + s + s) / 3.0
    cyg = (s + s + 0) / 3.0
    k = 1.0 - inset * 3.0 / s
    inner = [(cxg + (px - cxg) * k, cyg + (py - cyg) * k) for px, py in pts]
    pygame.draw.polygon(base, lighter(C_BLOCK_H, 60), inner,
                        max(1, int(s * 0.03)))
    # Hypotenuse highlight — bright bevel along the ride surface.
    pygame.draw.line(base, lighter(C_BLOCK_H, 100),
                     (0, s - 1), (s - 1, 0), max(2, int(s * 0.05)))
    pygame.draw.polygon(base, darker(C_BLOCK_D, 70), pts,
                        max(2, int(s * 0.045)))
    surf.blit(base, (0, 0))


def _render_spike(surf, s, frame_t, half=False):
    """GD spike: hard triangle, dark contour, a lighter left facet and a
    shaded right facet plus a tip glint. No soft glow — GD hazards read
    as crisp silhouettes so the player can judge the hitbox."""
    tip_y = int(s * 0.52) if half else int(s * 0.05)
    base_y = s - max(1, int(s * 0.03))
    cx = s // 2
    left_x = int(s * 0.07)
    right_x = s - left_x
    col = lighter(C_SPIKE, 15) if half else C_SPIKE
    pts = [(cx, tip_y), (left_x, base_y), (right_x, base_y)]
    # Lit left facet / shaded right facet — two flat tones, GD-style.
    pygame.draw.polygon(surf, lighter(col, 55),
                        [(cx, tip_y), (left_x, base_y), (cx, base_y)])
    pygame.draw.polygon(surf, darker(col, 45),
                        [(cx, tip_y), (cx, base_y), (right_x, base_y)])
    # Central body band ties the two facets together.
    band = int(s * 0.10)
    pygame.draw.polygon(surf, col,
                        [(cx, tip_y), (cx - band, base_y), (cx + band, base_y)])
    pygame.draw.polygon(surf, outline_col(col), pts, max(2, int(s * 0.045)))
    # Tip glint.
    glint_y = tip_y + int(s * 0.10)
    pygame.draw.polygon(surf, lighter(col, 120),
                        [(cx, tip_y + max(1, int(s * 0.02))),
                         (cx - int(s * 0.04), glint_y),
                         (cx + int(s * 0.04), glint_y)])
    # Base shadow so the spike sits on the ground instead of floating.
    pygame.draw.line(surf, darker(col, 80), (left_x, base_y),
                     (right_x, base_y), max(2, int(s * 0.04)))


def _render_saw(surf, s, frame_t):
    """Spinning sawblade: contoured teeth ring + metal hub with bolts."""
    cx, cy = s // 2, s // 2
    r_outer = int(s * 0.47)
    r_hub = int(s * 0.19)
    angle_offset = frame_t * math.tau / 8   # one tooth per full cycle
    teeth = 8
    _glow(surf, (cx, cy), r_outer, C_SAW, max_alpha=55, layers=6)

    def _tooth_ring(scale, valley=0.70):
        pts = []
        for i in range(teeth * 2):
            angle = angle_offset + i * math.pi / teeth
            rad = r_outer * scale if i % 2 == 0 else r_outer * scale * valley
            pts.append((cx + math.cos(angle) * rad,
                        cy + math.sin(angle) * rad))
        return pts

    outer_pts = _tooth_ring(1.0)
    pygame.draw.polygon(surf, outline_col(C_SAW), outer_pts)
    pygame.draw.polygon(surf, C_SAW, _tooth_ring(0.92))
    pygame.draw.polygon(surf, lighter(C_SAW, 45), _tooth_ring(0.72, 0.82))
    # Disc face under the teeth.
    pygame.draw.circle(surf, darker(C_SAW, 55), (cx, cy), int(r_outer * 0.62))
    pygame.draw.circle(surf, outline_col(C_SAW), (cx, cy),
                       int(r_outer * 0.62), max(1, int(s * 0.02)))
    # Metal hub.
    draw_bevel_circle(surf, (cx, cy), r_hub, (170, 175, 190),
                      outline=max(2, int(s * 0.025)))
    bolt_r = max(1, int(s * 0.028))
    for i in range(3):
        a = angle_offset * 3 + i * math.tau / 3
        bx = cx + int(math.cos(a) * r_hub * 0.55)
        by = cy + int(math.sin(a) * r_hub * 0.55)
        pygame.draw.circle(surf, (60, 62, 74), (bx, by), bolt_r)
    pygame.draw.circle(surf, (30, 32, 40), (cx, cy), max(2, int(s * 0.045)))
    pygame.draw.circle(surf, (110, 114, 130), (cx, cy), max(1, int(s * 0.025)))


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


def _render_teleport_portal(surf, s, frame_t, link_label=None):
    # Filled core (vs. the teleport orb's hollow ring) signals "automatic,
    # no click needed" at a glance — same visual language as pad-vs-orb.
    def _icon(surf, cx, cy, r):
        pygame.draw.polygon(surf, C_WHITE,
                            [(cx - 6, cy - 7), (cx + 3, cy - 7), (cx - 3, cy),
                             (cx + 3, cy), (cx - 6, cy + 7), (cx + 6, cy)])
    _render_orb_hq(surf, C_TELEPORT_PORTAL, s, frame_t,
                   label=str(link_label) if link_label else None,
                   inner_icon=None if link_label else _icon)


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
    """GD jump pad: a low plate on two feet with a bright domed top
    surface.  ``glyph`` selects the overlay: ``None`` (plain), ``"flip"``
    (gravity arrow) or ``"spider"`` (double arrow)."""
    cx = s // 2
    base_y = s - max(1, int(s * 0.04))
    plate_h = max(3, int(s * 0.17))
    plate = pygame.Rect(int(s * 0.10), base_y - plate_h - int(s * 0.06),
                        s - int(s * 0.20), plate_h)
    # Feet: two stubby supports under the plate.
    foot_w = max(2, int(s * 0.12))
    for fx in (plate.x + int(s * 0.06), plate.right - int(s * 0.06) - foot_w):
        foot = pygame.Rect(fx, plate.bottom - 1, foot_w,
                           base_y - plate.bottom + 1)
        draw_bevel_rect(surf, foot, darker(col, 60),
                        radius=max(1, int(s * 0.015)),
                        outline=max(1, int(s * 0.02)))
    # Glow above the plate — the "this will launch you" cue.
    halo = pygame.Surface((plate.w, int(s * 0.30)), pygame.SRCALPHA)
    for i in range(6):
        a = int(60 * (1 - i / 6) ** 2)
        pygame.draw.ellipse(halo, (*col, a),
                            halo.get_rect().inflate(-i * plate.w // 14,
                                                    -i * int(s * 0.04)))
    surf.blit(halo, (plate.x, plate.y - int(s * 0.20)))
    draw_bevel_rect(surf, plate, col, radius=max(2, int(s * 0.04)),
                    outline=max(2, int(s * 0.03)))
    # Domed bright lip across the top — GD pads look springy, not flat.
    lip = pygame.Rect(plate.x + int(s * 0.03),
                      plate.y - max(1, int(s * 0.035)),
                      plate.w - int(s * 0.06), max(2, int(s * 0.075)))
    pygame.draw.ellipse(surf, lighter(col, 100), lip)
    pygame.draw.ellipse(surf, darker(col, 70), lip, max(1, int(s * 0.018)))
    if glyph == "flip":
        arrow = [(cx - int(s * 0.09), plate.y + int(s * 0.02)),
                 (cx + int(s * 0.09), plate.y + int(s * 0.02)),
                 (cx, plate.bottom - int(s * 0.01))]
        pygame.draw.polygon(surf, C_WHITE, arrow)
        pygame.draw.polygon(surf, darker(col, 80), arrow,
                            max(1, int(s * 0.015)))
    elif glyph == "spider":
        for ox in (-int(s * 0.16), int(s * 0.16)):
            arrow = [(cx + ox, plate.y + int(s * 0.01)),
                     (cx + ox - int(s * 0.06), plate.bottom - int(s * 0.02)),
                     (cx + ox + int(s * 0.06), plate.bottom - int(s * 0.02))]
            pygame.draw.polygon(surf, C_WHITE, arrow)
            pygame.draw.polygon(surf, darker(col, 80), arrow,
                                max(1, int(s * 0.015)))


def _render_grav(surf, s, frame_t, direction):
    """Gravity-set portal. ``direction`` is "up" (blue, sets grav=-1) or
    "down" (yellow, sets grav=+1). A single-headed arrow indicates the
    forced gravity direction (no flip)."""
    col = C_GPORTAL_UP if direction == "up" else C_GPORTAL_DOWN
    rr = _render_portal_hq(surf, s, col, frame_t)
    cx = rr.centerx
    head = max(2, int(s * 0.09))
    stem = max(1, int(s * 0.028))
    if direction == "up":
        tip_y, base_y = rr.y + int(s * 0.04), rr.bottom - int(s * 0.04)
        head_y = tip_y + head * 2
        arrow = [(cx, tip_y),
                 (cx - head, head_y), (cx - stem, head_y),
                 (cx - stem, base_y), (cx + stem, base_y),
                 (cx + stem, head_y), (cx + head, head_y)]
    else:
        tip_y, base_y = rr.bottom - int(s * 0.04), rr.y + int(s * 0.04)
        head_y = tip_y - head * 2
        arrow = [(cx, tip_y),
                 (cx + head, head_y), (cx + stem, head_y),
                 (cx + stem, base_y), (cx - stem, base_y),
                 (cx - stem, head_y), (cx - head, head_y)]
    pygame.draw.polygon(surf, C_WHITE, arrow)
    pygame.draw.polygon(surf, darker(col, 80), arrow, max(1, int(s * 0.015)))


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
    rr = _render_portal_hq(surf, s, col, frame_t)
    cx, cy = rr.centerx, rr.centery
    w = max(3, int(s * 0.13))
    line = max(1, int(s * 0.015))
    rad = max(1, int(s * 0.02))
    if t == T_MODE_DUAL:
        for oy in (-1, 1):
            r = pygame.Rect(cx - w, cy + oy * int(s * 0.11) - w, w * 2, w * 2)
            pygame.draw.rect(surf, C_WHITE, r, border_radius=rad)
            pygame.draw.rect(surf, darker(col, 80), r, line, border_radius=rad)
        pygame.draw.line(surf, lighter(col, 60), (rr.left + line, cy),
                         (rr.right - line, cy), line)
    else:
        r = pygame.Rect(cx - int(s * 0.09), cy - int(s * 0.09),
                        int(s * 0.18), int(s * 0.18))
        pygame.draw.rect(surf, C_WHITE, r, border_radius=rad)
        pygame.draw.rect(surf, darker(col, 80), r, line, border_radius=rad)


def _render_size_portal(surf, s, frame_t, t):
    """Mini/Big portal — a big cube above a small one (or the reverse),
    with an arrow showing which way the size change goes."""
    col = TYPE_COLS[t]
    rr = _render_portal_hq(surf, s, col, frame_t)
    cx, cy = rr.centerx, rr.centery
    line = max(1, int(s * 0.015))
    rad = max(1, int(s * 0.02))
    big = max(4, int(s * 0.20))
    small = max(2, int(s * 0.10))
    shrinking = (t == T_MODE_MINI)
    top_sz, bot_sz = (big, small) if shrinking else (small, big)
    top = pygame.Rect(cx - top_sz // 2, cy - int(s * 0.22), top_sz, top_sz)
    bot = pygame.Rect(cx - bot_sz // 2, cy + int(s * 0.06), bot_sz, bot_sz)
    for r in (top, bot):
        pygame.draw.rect(surf, C_WHITE, r, border_radius=rad)
        pygame.draw.rect(surf, darker(col, 80), r, line, border_radius=rad)
    ay = cy + int(s * 0.02)
    pygame.draw.polygon(surf, C_WHITE,
                        [(cx, ay + int(s * 0.03)),
                         (cx - int(s * 0.05), ay - int(s * 0.02)),
                         (cx + int(s * 0.05), ay - int(s * 0.02))])


def _render_mode_portal(surf, s, frame_t, t):
    """Mode portal — the destination form's silhouette inside the ring."""
    col = TYPE_COLS[t]
    rr = _render_portal_hq(surf, s, col, frame_t)
    cx, cy = rr.centerx, rr.centery
    line = max(1, int(s * 0.018))
    dark = darker(col, 80)

    def _u(v):
        # Glyphs are sized as a fraction of the cell, scaled up to fill
        # the portal's inner plate.
        return int(s * v * 1.3)

    if t == T_MODE_CUBE:
        r = pygame.Rect(cx - _u(0.10), cy - _u(0.10), _u(0.20), _u(0.20))
        pygame.draw.rect(surf, C_WHITE, r, border_radius=max(1, _u(0.03)))
        pygame.draw.rect(surf, dark, r, line, border_radius=max(1, _u(0.03)))
        pygame.draw.rect(surf, dark, r.inflate(-_u(0.10), -_u(0.10)),
                         border_radius=max(1, _u(0.02)))
    elif t == T_MODE_SHIP:
        pts = [(cx + _u(0.11), cy), (cx - _u(0.09), cy - _u(0.09)),
               (cx - _u(0.05), cy), (cx - _u(0.09), cy + _u(0.09))]
        pygame.draw.polygon(surf, C_WHITE, pts)
        pygame.draw.polygon(surf, dark, pts, line)
        pygame.draw.polygon(surf, (255, 180, 80),
                            [(cx - _u(0.09), cy), (cx - _u(0.16), cy - _u(0.05)),
                             (cx - _u(0.16), cy + _u(0.05))])
    elif t == T_MODE_BALL:
        pygame.draw.circle(surf, C_WHITE, (cx, cy), _u(0.11))
        pygame.draw.circle(surf, dark, (cx, cy), _u(0.11), line)
        pygame.draw.circle(surf, dark, (cx, cy), _u(0.07), line)
        pygame.draw.circle(surf, dark, (cx, cy), max(1, _u(0.03)))
    elif t == T_MODE_WAVE:
        pts = [(cx + _u(0.12), cy), (cx - _u(0.10), cy - _u(0.10)),
               (cx - _u(0.03), cy), (cx - _u(0.10), cy + _u(0.10))]
        pygame.draw.polygon(surf, C_WHITE, pts)
        pygame.draw.polygon(surf, dark, pts, line)
    elif t == T_MODE_UFO:
        dome = pygame.Rect(cx - _u(0.07), cy - _u(0.11), _u(0.14), _u(0.11))
        pygame.draw.ellipse(surf, C_WHITE, dome)
        pygame.draw.ellipse(surf, dark, dome, line)
        body = pygame.Rect(cx - _u(0.14), cy - _u(0.02), _u(0.28), _u(0.08))
        pygame.draw.ellipse(surf, C_WHITE, body)
        pygame.draw.ellipse(surf, dark, body, line)
        for ox in (-_u(0.08), 0, _u(0.08)):
            pygame.draw.circle(surf, dark, (cx + ox, cy + _u(0.055)),
                               max(1, _u(0.015)))
    elif t == T_MODE_SPIDER:
        body = [(cx, cy - _u(0.10)), (cx + _u(0.09), cy - _u(0.04)),
                (cx + _u(0.09), cy + _u(0.05)), (cx, cy + _u(0.11)),
                (cx - _u(0.09), cy + _u(0.05)), (cx - _u(0.09), cy - _u(0.04))]
        for sx in (-1, 1):
            for oy in (-_u(0.07), _u(0.02), _u(0.09)):
                pygame.draw.line(surf, C_WHITE, (cx, cy),
                                 (cx + sx * _u(0.16), cy + oy),
                                 max(2, line))
        pygame.draw.polygon(surf, C_WHITE, body)
        pygame.draw.polygon(surf, dark, body, line)
        pygame.draw.rect(surf, dark, (cx - _u(0.05), cy - _u(0.02),
                                      _u(0.10), _u(0.04)),
                         border_radius=max(1, _u(0.015)))
    elif t == T_MODE_SWING:
        pts = [(cx, cy - _u(0.13)), (cx + _u(0.07), cy), (cx, cy + _u(0.13)),
               (cx - _u(0.07), cy)]
        pygame.draw.polygon(surf, C_WHITE, pts)
        pygame.draw.polygon(surf, dark, pts, line)
        for sx in (-1, 1):
            pygame.draw.polygon(surf, C_WHITE,
                                [(cx + sx * _u(0.04), cy - _u(0.02)),
                                 (cx + sx * _u(0.14), cy - _u(0.07)),
                                 (cx + sx * _u(0.12), cy + _u(0.03))])
    elif t == T_MODE_ROBOT:
        body = pygame.Rect(cx - _u(0.09), cy - _u(0.12), _u(0.18), _u(0.15))
        pygame.draw.rect(surf, C_WHITE, body, border_radius=max(1, _u(0.02)))
        pygame.draw.rect(surf, dark, body, line, border_radius=max(1, _u(0.02)))
        pygame.draw.rect(surf, dark, (cx - _u(0.06), cy - _u(0.09),
                                      _u(0.12), _u(0.04)),
                         border_radius=max(1, _u(0.01)))
        for ox in (-_u(0.06), _u(0.02)):
            pygame.draw.rect(surf, C_WHITE,
                             (cx + ox, cy + _u(0.03), _u(0.04), _u(0.06)))
        pygame.draw.polygon(surf, (255, 180, 80),
                            [(cx - _u(0.05), cy + _u(0.10)),
                             (cx + _u(0.05), cy + _u(0.10)),
                             (cx, cy + _u(0.16))])


def _render_speed_portal(surf, s, frame_t, t):
    col = TYPE_COLS[t]
    rr = _render_portal_hq(surf, s, col, frame_t)
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
    """Spinning secret coin: contoured disc with an inner ring and star."""
    cx, cy = s // 2, s // 2
    wobble = math.sin(frame_t * math.tau)
    r_outer = int(s * 0.34)
    _glow(surf, (cx, cy), r_outer, C_COIN, max_alpha=90, layers=8)
    body_w = max(4, int(r_outer * 2 - abs(wobble) * r_outer * 0.7))
    coin = pygame.Rect(cx - body_w // 2, cy - r_outer, body_w, r_outer * 2)
    pygame.draw.ellipse(surf, darker(C_COIN, 55), coin.move(0, int(s * 0.02)))
    pygame.draw.ellipse(surf, C_COIN, coin)
    pygame.draw.ellipse(surf, outline_col(C_COIN), coin,
                        max(2, int(s * 0.028)))
    inner = coin.inflate(-max(2, body_w // 4), -max(2, r_outer // 2))
    if inner.w > 2 and inner.h > 2:
        pygame.draw.ellipse(surf, lighter(C_COIN, 80), inner,
                            max(1, int(s * 0.022)))
    if body_w > s * 0.25:
        # Drawn star rather than a text glyph: the bundled system font
        # has no U+2605 in some environments and rendered a tofu box.
        star = []
        for i in range(10):
            ang = -math.pi / 2 + i * math.pi / 5
            rad = r_outer * (0.62 if i % 2 == 0 else 0.26)
            star.append((cx + math.cos(ang) * rad * (body_w / (r_outer * 2)),
                         cy + math.sin(ang) * rad))
        pygame.draw.polygon(surf, darker(C_COIN, 75), star)
    draw_gloss(surf, coin, alpha=110, width_frac=0.5, height_frac=0.3)


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


# ---- Editor-only overlay glyphs -------------------------------------------
# The jump probe, the bot checkpoint and the trigger plates are authoring
# aids, not gameplay objects, so they deliberately stay schematic: a dark
# translucent plate with a coloured frame rather than a solid GD body.
# They share this chrome so they read as one family of overlays and pick
# up the same outline/bevel/gloss finish as the real art without ever
# being mistakable for a hazard, orb or block.
def _editor_glyph_panel(surf, rect, col, fill_alpha=110, radius=6):
    """Dark translucent plate with a bevelled, coloured editor frame."""
    plate = pygame.Surface(rect.size, pygame.SRCALPHA)
    pr = plate.get_rect()
    edge = max(2, rect.w // 24)
    pygame.draw.rect(plate, (12, 14, 22, fill_alpha), pr, border_radius=radius)
    pygame.draw.line(plate, (*lighter(col, 60), 130),
                     (pr.left + radius, pr.top + edge),
                     (pr.right - radius, pr.top + edge), edge)
    pygame.draw.line(plate, (*darker(col, 50), 150),
                     (pr.left + radius, pr.bottom - edge),
                     (pr.right - radius, pr.bottom - edge), edge)
    draw_gloss(plate, pr.inflate(-rect.w // 4, -rect.h // 2), alpha=45)
    pygame.draw.rect(plate, (*col, 235), pr, edge, border_radius=radius)
    # Blueprint corner ticks — the cue that says "overlay, not object".
    tick = max(2, rect.w // 9)
    for cx, cy, dx, dy in ((pr.left + edge, pr.top + edge, 1, 1),
                           (pr.right - edge, pr.top + edge, -1, 1),
                           (pr.left + edge, pr.bottom - edge, 1, -1),
                           (pr.right - edge, pr.bottom - edge, -1, -1)):
        pygame.draw.line(plate, (*lighter(col, 70), 200), (cx, cy),
                         (cx + dx * tick, cy), edge)
        pygame.draw.line(plate, (*lighter(col, 70), 200), (cx, cy),
                         (cx, cy + dy * tick), edge)
    surf.blit(plate, rect.topleft)


def _glyph_stroke(surf, col, start, end, width):
    """Glyph line with a dark contour, so it reads over any plate."""
    pygame.draw.line(surf, outline_col(col), start, end, width + 2)
    pygame.draw.line(surf, col, start, end, width)


def _render_jump_predictor(surf, s, frame_t):
    """Editor probe icon: dashed crosshair + small arc on a schematic
    plate.  Intentionally not a gameplay-object look — the author must
    never confuse the probe with something the player can touch."""
    col = TYPE_COLS.get(T_JUMP_PREDICTOR, (255, 235, 120))
    rect = pygame.Rect(6, 6, s - 12, s - 12)
    _editor_glyph_panel(surf, rect, col)
    cx, cy = s // 2, s // 2
    r = int(s * 0.22)
    w = max(2, s // 24)
    pygame.draw.circle(surf, outline_col(col), (cx, cy), r, w + 2)
    pygame.draw.circle(surf, col, (cx, cy), r, w)
    pygame.draw.circle(surf, lighter(col, 70), (cx, cy), r - w, max(1, w // 2))
    # Crosshair ticks.
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        _glyph_stroke(surf, col,
                      (cx + dx * (r + w * 2), cy + dy * (r + w * 2)),
                      (cx + dx * (r + w * 5), cy + dy * (r + w * 5)), w)
    # Small preview arc from the circle up-and-right, suggesting a jump.
    arc_rect = pygame.Rect(cx - 2, cy - int(s * 0.38),
                           int(s * 0.55), int(s * 0.55))
    try:
        pygame.draw.arc(surf, outline_col(col), arc_rect,
                        math.radians(200), math.radians(340), w + 2)
        pygame.draw.arc(surf, lighter(col, 40), arc_rect,
                        math.radians(200), math.radians(340), w)
    except (pygame.error, ValueError):
        pass


def _render_bot_checkpoint(surf, s, frame_t):
    """Bot checkpoint icon: a target reticle on the same schematic plate
    as the jump probe.  Square plate + rings keeps it distinct from the
    round coin and from the probe's crosshair-and-arc."""
    col = TYPE_COLS.get(T_BOT_CHECKPOINT, (120, 230, 255))
    cx, cy = s // 2, s // 2
    rect = pygame.Rect(6, 6, s - 12, s - 12)
    _editor_glyph_panel(surf, rect, col, fill_alpha=100)
    r_outer = int(s * 0.34)
    r_mid = int(s * 0.22)
    r_inner = max(2, int(s * 0.10))
    w = max(2, s // 24)
    pygame.draw.circle(surf, outline_col(col), (cx, cy), r_outer, w + 2)
    pygame.draw.circle(surf, col, (cx, cy), r_outer, w)
    pygame.draw.circle(surf, outline_col(col), (cx, cy), r_mid, w + 2)
    pygame.draw.circle(surf, lighter(col, 40), (cx, cy), r_mid, w)
    draw_bevel_circle(surf, (cx, cy), r_inner, C_WHITE, outline=max(1, w // 2),
                      line_col=outline_col(col))
    # Crosshair ticks at cardinals.
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        _glyph_stroke(surf, col,
                      (cx + dx * (r_outer + w), cy + dy * (r_outer + w)),
                      (cx + dx * (r_outer + w * 4), cy + dy * (r_outer + w * 4)),
                      w)


def _render_dash_stop(surf, s, frame_t):
    """S Block: a hollow white rectangle carrying a big "S".

    A real gameplay object (it stops a dash), so it gets a plain solid
    body rather than the editor-overlay chrome — it is just invisible by
    default, which the author can turn off per instance.
    """
    col = TYPE_COLS.get(T_DASH_STOP, C_WHITE)
    rect = pygame.Rect(5, 5, s - 10, s - 10)
    w = max(2, s // 16)
    pygame.draw.rect(surf, outline_col(col), rect.inflate(w, w), w,
                     border_radius=max(3, s // 12))
    pygame.draw.rect(surf, col, rect, w, border_radius=max(3, s // 12))
    txt(surf, "S", s // 2, s // 2, max(12, int(s * 0.55)), col, True,
        shadow=True)


# A placed trigger's proportions, as fractions of the cell.  Taken from
# how GD's own `edit_e*Btn` art is laid out: a white word across the top
# third and a colour-coded disc filling the rest, over a TRANSPARENT
# cell.  GD draws no plate, no border and no gloss behind either — that
# is the whole reason its triggers read as editor annotation while a
# filled glossy panel reads as something the player can touch.
TRIGGER_LABEL_CY = 0.22       # centre of the caption
TRIGGER_LABEL_H = 0.30        # caption cap height
TRIGGER_BODY_CY = 0.63        # centre of the disc / glyph
TRIGGER_BODY_R = 0.27         # disc radius


def _render_trigger(surf, s, t):
    """Trigger marker in GD's editor grammar.

    A colour-coded disc under a short white caption, on a transparent
    cell — the layout GD uses for a placed trigger, reproduced with this
    engine's own vector drawing rather than GD's baked bitmaps.

    Going procedural rather than blitting `edit_e*Btn` is deliberate:
    those frames cover only 47 of this engine's trigger types, they bake
    GD's own English word into the pixels at GD's editor scale (so the
    long ones overflow a 50 px cell), and they would drop the per-type
    colour coding that is the only thing telling 70 types apart.  What
    was actually un-GD-like about the old look was the CONVENTION — a
    saturated, bevelled, glossy plate filling the cell — not the absence
    of GD's textures, so that is what this changes.
    """
    col = TYPE_COLS.get(t, C_GRAY)
    w = max(2, s // 24)
    cx = s // 2
    cy = int(s * TRIGGER_BODY_CY)
    if t not in (T_CAMERA_TRIGGER, T_TIME_WARP):
        # GD's colour disc, with a dark rim so a pale trigger colour
        # still separates from a bright background.
        r = int(s * TRIGGER_BODY_R)
        pygame.draw.circle(surf, outline_col(col), (cx, cy), r + w)
        pygame.draw.circle(surf, col, (cx, cy), r)
        pygame.draw.circle(surf, lighter(col, 55), (cx, cy), r,
                           max(1, w // 2))
    if t == T_CAMERA_TRIGGER:
        # Proportional to `s`: the old glyph used raw pixel offsets and
        # shrank to a few pixels once the sprite was downsampled.
        # Sized to carry the same visual weight as the colour disc the
        # other triggers get, so a row of mixed triggers reads evenly.
        body = pygame.Rect(cx - int(s * 0.24), cy - int(s * 0.13),
                           int(s * 0.34), int(s * 0.26))
        pygame.draw.rect(surf, outline_col(col), body.inflate(w, w), 0,
                         border_radius=max(1, w))
        pygame.draw.rect(surf, C_WHITE, body, w, border_radius=max(1, w))
        lens = [(body.right, cy - int(s * 0.08)),
                (body.right + int(s * 0.13), cy - int(s * 0.15)),
                (body.right + int(s * 0.13), cy + int(s * 0.15)),
                (body.right, cy + int(s * 0.08))]
        draw_outlined_poly(surf, lens, C_WHITE, w, outline_col(col))
    elif t == T_TIME_WARP:
        # Stopwatch glyph: a circle (the dial) + two hands. The dial
        # outline reads as the "T" of time warp; the offset hands give
        # it a clock vibe so authors don't confuse it with the rotate
        # trigger (which is also circular).
        r = max(4, int(s * TRIGGER_BODY_R * 0.85))
        pygame.draw.circle(surf, outline_col(col), (cx, cy), r, w + 2)
        pygame.draw.circle(surf, C_WHITE, (cx, cy), r, w)
        # Tick at the 12-o'clock position.
        pygame.draw.line(surf, C_WHITE, (cx, cy - r), (cx, cy - r + w * 2), w)
        # Hour hand toward 11; minute hand toward 3.
        _glyph_stroke(surf, C_WHITE, (cx, cy), (cx - r // 2, cy - r // 2), w)
        _glyph_stroke(surf, C_WHITE, (cx, cy), (cx + int(r * 0.7), cy), w)
        pygame.draw.circle(surf, outline_col(col), (cx, cy), max(1, w))
    # The caption runs for EVERY trigger, glyph or disc — GD labels all of
    # them, and it is the only thing separating types that share a colour.
    txt(surf, _trigger_label(t), cx, int(s * TRIGGER_LABEL_CY),
        max(10, int(s * TRIGGER_LABEL_H)), C_WHITE, True, shadow=True)


def _trigger_label(t):
    """The short caption a placed trigger carries.

    Explicit two/three-letter codes where the derived initials would be
    ambiguous -- "event_trigger" and "end_trigger" both derive to a bare
    "E", and the scenery family derives to single letters that say
    nothing.
    """
    label = {T_BG_TRIGGER: "BG", T_MOVE_TRIGGER: "MV",
             T_COLOR_TRIGGER: "CL", T_PULSE_TRIGGER: "PL",
             T_ROTATE_TRIGGER: "RT", T_FOLLOW_TRIGGER: "FL",
             T_BLACKOUT_TRIGGER: "BK",
             T_GROUND_TRIGGER: "GRD", T_MG_TRIGGER: "MG",
             T_BG_SPEED_TRIGGER: "BGS", T_MG_SPEED_TRIGGER: "MGS",
             T_UI_TRIGGER: "UI", T_EVENT_TRIGGER: "EVT",
             T_END_TRIGGER: "END",
             T_CAMERA_TRIGGER: "CAM", T_TIME_WARP: "TIME"}.get(t)
    if label is None:
        # Keep newer/extended trigger types identifiable instead of
        # displaying a confusing question mark in the editor.
        words = str(t).replace("_trigger", "").split("_")
        label = "".join(w[:1].upper() for w in words)[:4] or "TR"
    return label


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
    T_TELEPORT_PORTAL: lambda s, b, f, v: _render_teleport_portal(s, b, f, link_label=v),
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
    T_DASH_STOP:   lambda s, b, f, v: _render_dash_stop(s, b, f),
    T_KEYFRAME:    lambda s, b, f, v: _render_keyframe(s, b, f),
    T_ITEM_PICKUP:  lambda s, b, f, v: _render_item_pickup(s, b, f),
    T_ITEM_COUNTER: lambda s, b, f, v: _render_item_counter(s, b, f),
    T_JUMP_BLOCK:   lambda s, b, f, v: _render_jump_block(s, b, f),
    T_WAVE_BLOCK:   lambda s, b, f, v: _render_wave_block(s, b, f),
    T_BONK_BLOCK:   lambda s, b, f, v: _render_bonk_block(s, b, f),
}

_TRIGGER_TYPES_SET = TRIGGER_TYPES

_SIZE_PORTAL_TYPES = {T_MODE_MINI, T_MODE_BIG}
_DUAL_PORTAL_TYPES = {T_MODE_DUAL, T_MODE_SOLO}


# ---------------------------------------------------------------------------
# Real Geometry Dash art
#
# Types listed here are cut out of the official cocos2d atlases in
# ``assets/sprites/gd_official/`` instead of being drawn by the
# procedural renderers above.  The sheets are optional: when they are
# absent (they are gitignored copyrighted binaries) every lookup returns
# None and the procedural renderer runs exactly as before.
#
# Spec keys:
#   ``frames``  layered back-to-front (portals ship a back plate and a
#               front rim as two separate frames).
#   ``mirror``  GD only ships the left half of portals — the flipped copy
#               is re-added about the untrimmed box's centre line.
#   ``tint``    only for the frames GD stores as black/white silhouettes
#               (block, spikes, blade).  GD tints those by the level's
#               base colour channel; this engine substitutes its own
#               palette colour so blocks stay blue and spikes stay red.
#               Orbs, pads, portals and speed arrows already carry their
#               own colours and must NOT be tinted.
#   ``pulse``   per-frame breathing amplitude, reproducing the scale
#               throb GD applies to orbs at runtime.
#   ``spin``    degrees swept across the whole 8-frame loop.  Must stay a
#               multiple of 360/teeth or the loop does not wrap and the
#               blade visibly lurches backwards once per cycle.
#               ``sawblade_02``'s radial profile repeats every 30°
#               (measured: 12 teeth), so the sweep must be a multiple
#               of 30 — and each frame's step must stay well under half
#               a tooth (15°) or the direction reads as ambiguous.
#   ``fit``     ``"cell"`` (default) keeps GD's true size, so art bigger
#               than 30 GD units overhangs its cell exactly as in the
#               real game.  ``"contain"`` shrinks the sprite into one
#               cell — reserved for the pickup/marker art that is not
#               level geometry and should not spill onto neighbours.
# ---------------------------------------------------------------------------
GD_SHEET_BLOCKS = "GJ_GameSheet"
GD_SHEET_PORTALS = "GJ_GameSheet02"
GD_SHEET_UI = "GJ_GameSheet03"

# Portals are ~45 x 90 GD units — 1.5 cells wide and 3 cells tall — so
# they take the default true-scale fit and stick out above and below the
# row they are placed on, which is how GD draws them.
_PORTAL_OPTS = {"sheet": GD_SHEET_PORTALS, "mirror": True}
_ORB_OPTS = {"sheet": GD_SHEET_BLOCKS, "pulse": 0.05}
_PAD_OPTS = {"sheet": GD_SHEET_BLOCKS, "anchor": "bottom"}


def _gd_portal(index):
    return dict(_PORTAL_OPTS,
                frames=(f"portal_{index:02d}_back_001.png",
                        f"portal_{index:02d}_front_001.png"))


def _gd_orb(frame):
    return dict(_ORB_OPTS, frames=(frame,))


def _gd_pad(frame):
    return dict(_PAD_OPTS, frames=(frame,))


def _gd_speed(index):
    return {"sheet": GD_SHEET_PORTALS,
            "frames": (f"boost_{index:02d}_001.png",)}


GD_SPRITE_MAP = {
    # Solids and hazards — silhouettes, so they take this engine's tint.
    T_BLOCK:  {"sheet": GD_SHEET_BLOCKS, "frames": ("square_01_001.png",),
               "tint": C_BLOCK_H},
    T_SPIKE:  {"sheet": GD_SHEET_BLOCKS, "frames": ("spike_01_001.png",),
               "tint": C_SPIKE},
    T_HALF_SPIKE: {"sheet": GD_SHEET_BLOCKS, "frames": ("spike_02_001.png",),
                   "tint": C_SPIKE},
    # The blade is 60x60 GD units — a genuine 2x2 cells, twice the size
    # of a block, and it overhangs accordingly. Gameplay is unaffected:
    # `geometry.saw_hitbox` is a fixed inset of the cell rect and never
    # looks at the sprite.
    T_SAW:    {"sheet": GD_SHEET_BLOCKS, "frames": ("sawblade_02_001.png",),
               "tint": C_SAW, "spin": 60.0},

    # Orbs. GD's names are historical, so the colour is what identifies
    # them: ring_01 yellow, ring_02 red, ring_03 pink, gravring cyan,
    # gravJumpRing green, dropRing black, dashRing_01/02 the dash pair.
    T_ORB:            _gd_orb("ring_01_001.png"),
    T_RED_ORB:        _gd_orb("ring_02_001.png"),
    T_PINK_ORB:       _gd_orb("ring_03_001.png"),
    T_BLUE_ORB:       _gd_orb("gravring_01_001.png"),
    T_GREEN_ORB:      _gd_orb("gravJumpRing_01_001.png"),
    T_BLACK_ORB:      _gd_orb("dropRing_01_001.png"),
    T_DASH_ORB:       _gd_orb("dashRing_01_001.png"),
    T_DASH_ORB_GRAV:  _gd_orb("dashRing_02_001.png"),

    # Pads — GD calls them "bump"; they are thin plates that sit on the
    # floor of their cell, hence the bottom anchor.
    T_PAD:       _gd_pad("bump_01_001.png"),
    T_RED_PAD:   _gd_pad("bump_02_001.png"),
    T_PINK_PAD:  _gd_pad("bump_03_001.png"),
    T_BLUE_PAD:  _gd_pad("gravbump_01_001.png"),

    # Portals. Indices are GD's own numbering, cross-checked against the
    # object-ID table in GDRWeb's assets/object.json (10/11 gravity,
    # 12 cube, 13 ship, 47 ball, 111 UFO, 286 dual, 287 solo, 660 wave,
    # 745 robot, 1331 spider) AND against each frame's mean hue, which
    # matches GD's published portal colours one for one: 03 green cube,
    # 04 magenta ship, 07 red ball, 10 orange UFO, 11 orange dual,
    # 12 blue solo, 13 cyan wave, 14 white robot, 17 purple spider.
    #
    # The size pair was the one the object-ID table got wrong. GD's wiki
    # is explicit that the MINI portal is pink and the one restoring
    # normal size is green; `portal_08_front` measures (62,227,75) green
    # and `portal_09_front` (228,117,235) pink, so 8 is Big and 9 is
    # Mini — the reverse of what the ID table implied.
    T_GRAV_UP:      _gd_portal(1),
    T_GRAV_DOWN:    _gd_portal(2),
    T_MODE_CUBE:    _gd_portal(3),
    T_MODE_SHIP:    _gd_portal(4),
    T_MODE_BALL:    _gd_portal(7),
    T_MODE_MINI:    _gd_portal(9),
    T_MODE_BIG:     _gd_portal(8),
    T_MODE_UFO:     _gd_portal(10),
    T_MODE_DUAL:    _gd_portal(11),
    T_MODE_SOLO:    _gd_portal(12),
    T_MODE_WAVE:    _gd_portal(13),
    T_MODE_ROBOT:   _gd_portal(14),
    T_MODE_SPIDER:  _gd_portal(17),

    # Secret coin (GD object 142). The in-level frame `secretCoin_01` is
    # absent from every sheet installed here, so this uses GD's own UI
    # rendering of the same coin — identical gold disc and star, and it
    # already carries its colour, so no tint. That UI frame is 44x44,
    # i.e. drawn for an HUD slot rather than for the grid, so it keeps
    # "contain": a coin is a pickup, not level geometry, and a 1.5-cell
    # disc would sit on top of the blocks that frame a coin route.
    T_COIN: {"sheet": GD_SHEET_UI, "frames": ("secretCoinUI_001.png",),
             "fit": "contain", "pulse": 0.08},

    # Practice-mode checkpoint (the green marker GD plants on the C key).
    # `checkpoint_01_glow` is deliberately skipped, matching the general
    # decision not to bake GD's glow layers into these sprites.
    # 17x32 is a hair over one cell tall; "contain" costs 3 px of height
    # against true scale and keeps this editor/practice marker from
    # overlapping the object it marks.
    T_CHECKPOINT: {"sheet": GD_SHEET_PORTALS,
                   "frames": ("checkpoint_01_001.png",),
                   "fit": "contain", "pulse": 0.06},

    # Speed changers — GD calls them "boost"; one to four chevrons.
    T_SPEED_SLOW:    _gd_speed(1),
    T_SPEED_NORMAL:  _gd_speed(2),
    T_SPEED_FAST:    _gd_speed(3),
    T_SPEED_FASTER:  _gd_speed(4),
    T_SPEED_FASTEST: _gd_speed(5),
}

# GD has no single frame for a solid slope: it draws the block fill
# clipped to a triangle and lays the diagonal edge sprite over it. This
# reproduces that, in the same base orientation _render_slope uses —
# hypotenuse from (0, s) up to (s, 0), body filling the lower right.
GD_SLOPE_FILL_FRAME = "square_01_001.png"
GD_SLOPE_EDGE_FRAME = "blockOutline_14_001.png"

# GD's Half Block (objects 62/65/66/68) is the one block texture that is
# NOT a 30x30 cell: `square_b_01` is genuinely 30 wide x 16 tall, with a
# `blockOutline_02` cap composited across its top edge at GD's own child
# offset of +7.25 (GD's y points up). Neither layer fits compose()'s
# square-cell model, so they are placed straight into the bottom half of
# the cell — which is exactly the rect geometry.slab_rect collides
# against, so the visual and the hitbox stay aligned.
#
# The two layers take DIFFERENT colour channels, which is what makes the
# half block read as the same material as the full block: the fill is
# "Black" (the interior channel) and only the cap is "Base".
GD_SLAB_FILL_FRAME = "square_b_01_001.png"
GD_SLAB_EDGE_FRAME = "blockOutline_02_001.png"
GD_SLAB_SRC_H = 16.0
GD_SLAB_EDGE_OFFSET_Y = 7.25

# GD gives its letter-modifier blocks (Stop Dash 1755, and the jump /
# buffer variants 1813 / 1829) no unique texture at all — every one of
# them is a plain `blockOutline_01` frame with an editor-only letter on
# top, which is what this engine already drew by hand.
GD_LETTER_BLOCK_FRAME = "blockOutline_01_001.png"

# Everything above that decides what a real-GD sprite bakes to. Hashed
# into sprite_cache_signature(), so changing any of it invalidates the
# cached PNGs by itself — see that function for why hand-bumping
# SPRITE_CACHE_VERSION was not enough.
GD_ART_RECIPE = (
    GD_SPRITE_MAP,
    GD_SLOPE_FILL_FRAME, GD_SLOPE_EDGE_FRAME,
    GD_SLAB_FILL_FRAME, GD_SLAB_EDGE_FRAME,
    GD_SLAB_SRC_H, GD_SLAB_EDGE_OFFSET_Y,
    GD_LETTER_BLOCK_FRAME,
)


def _tinted(img, tint):
    if tint:
        img.fill((*tint, 255), special_flags=pygame.BLEND_RGBA_MULT)
    return img


def _render_gd_slope(s):
    """Block fill clipped to the ramp triangle + GD's diagonal edge."""
    fill = gd_atlas.compose(GD_SHEET_BLOCKS, GD_SLOPE_FILL_FRAME, s)
    edge = gd_atlas.compose(GD_SHEET_BLOCKS, GD_SLOPE_EDGE_FRAME, s)
    if fill is None or edge is None:
        return None
    mask = pygame.Surface((s, s), pygame.SRCALPHA)
    pygame.draw.polygon(mask, (255, 255, 255, 255), [(0, s), (s, s), (s, 0)])
    fill.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    _tinted(fill, C_BLOCK_H)
    fill.blit(_tinted(edge, C_BLOCK_H), (0, 0))
    return fill


def _render_gd_slab(s):
    """Half-height block fill + GD's top-edge outline, same tint-then-
    composite order as the slope."""
    fill = gd_atlas.frame_surface(GD_SHEET_BLOCKS, GD_SLAB_FILL_FRAME)
    edge = gd_atlas.frame_surface(GD_SHEET_BLOCKS, GD_SLAB_EDGE_FRAME)
    if fill is None or edge is None:
        return None
    top = s // 2
    half = s - top
    px_per_gd = half / GD_SLAB_SRC_H
    canvas = pygame.Surface((s, s), pygame.SRCALPHA)
    canvas.blit(_tinted(pygame.transform.smoothscale(fill, (s, half)),
                        C_BLOCK_INNER), (0, top))
    # This is the one place that measures RAW frame pixels against a
    # length written in base GD units (GD_SLAB_SRC_H), so it is the one
    # place that has to divide the sheet's own density back out — on an
    # -hd sheet `edge` is twice as tall for the same 30-unit cap.
    edge_units = edge.get_height() / gd_atlas.sheet_unit_scale(GD_SHEET_BLOCKS)
    edge_h = max(1, int(round(edge_units * px_per_gd)))
    edge_y = top + half / 2.0 - GD_SLAB_EDGE_OFFSET_Y * px_per_gd - edge_h / 2.0
    canvas.blit(_tinted(pygame.transform.smoothscale(edge, (s, edge_h)),
                        C_BLOCK_H), (0, int(round(edge_y))))
    return canvas


# Types GD builds by compositing several frames with per-type geometry,
# rather than by stacking whole cells the way GD_SPRITE_MAP does.
_GD_COMPOSITE_RENDERERS = {
    T_SLOPE: _render_gd_slope,
    T_SLAB: _render_gd_slab,
}


def _render_gd_sprite(t, s, frame_t):
    """Real-GD sprite for ``t``, or ``None`` to use the procedural path.

    ``None`` is returned for unmapped types *and* whenever the atlas
    files are missing, so a checkout without the sheets renders exactly
    as it did before.
    """
    composite = _GD_COMPOSITE_RENDERERS.get(t)
    if composite is not None:
        return composite(s)
    spec = GD_SPRITE_MAP.get(t)
    if spec is None:
        return None
    pulse = spec.get("pulse", 0.0)
    layers = []
    for frame in spec["frames"]:
        layer = gd_atlas.compose(
            spec["sheet"], frame, s,
            fit=spec.get("fit", "cell"),
            anchor=spec.get("anchor", "center"),
            mirror=spec.get("mirror", False),
            # Breathe by shrinking rather than growing, so the sprite
            # stays inside the canvas its widest frame needs.
            pad=pulse * (1.0 - math.sin(frame_t * math.tau)) / 2.0,
            spin=frame_t * spec.get("spin", 0.0),
        )
        if layer is None:
            return None
        layers.append(layer)
    # Layers of one sprite can need different canvases (a portal's back
    # plate is wider than its front rim), and every canvas carries the
    # grid cell at its own centre — so they stack centre-on-centre, not
    # corner-on-corner.
    w = max(l.get_width() for l in layers)
    h = max(l.get_height() for l in layers)
    if len(layers) == 1:
        canvas = layers[0]
    else:
        canvas = pygame.Surface((w, h), pygame.SRCALPHA)
        for layer in layers:
            canvas.blit(layer, (round((w - layer.get_width()) / 2.0),
                                round((h - layer.get_height()) / 2.0)))
    return _tinted(canvas, spec.get("tint"))


def _render_sprite(t, s, frame_t, variant=None):
    """Render ONE sprite to a new (s,s) SRCALPHA surface.

    Real-GD atlas art wins when this type has a mapping and the sheets
    are installed; otherwise the procedural renderers below run. Those
    render at 2x and downscale with smoothscale for free AA — the atlas
    path composes at ``s`` directly, since resampling the source art
    twice only softens it.
    """
    if variant is None:
        gd_img = _render_gd_sprite(t, s, frame_t)
        if gd_img is not None:
            return gd_img
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


def _render_keyframe(surf, s, frame_t):
    _editor_glyph_panel(surf, pygame.Rect(0, 0, s, s), C_KEYFRAME)
    cx = cy = s // 2
    pygame.draw.polygon(surf, C_WHITE, [
        (cx - s * 0.16, cy - s * 0.18),
        (cx + s * 0.05, cy - s * 0.18),
        (cx + s * 0.05, cy - s * 0.30),
        (cx + s * 0.22, cy),
        (cx + s * 0.05, cy + s * 0.30),
        (cx + s * 0.05, cy + s * 0.18),
        (cx - s * 0.16, cy + s * 0.18),
    ])


def _render_item_pickup(surf, s, frame_t):
    _editor_glyph_panel(surf, pygame.Rect(0, 0, s, s), C_ITEM_PICKUP)
    cx = cy = s // 2
    pygame.draw.circle(surf, C_WHITE, (cx, cy), max(4, s // 5), 2)
    pygame.draw.line(surf, C_WHITE, (cx, cy - s // 6), (cx, cy + s // 6), 2)
    pygame.draw.line(surf, C_WHITE, (cx - s // 6, cy), (cx + s // 6, cy), 2)


def _render_item_counter(surf, s, frame_t):
    _editor_glyph_panel(surf, pygame.Rect(0, 0, s, s), C_ITEM_COUNTER)
    cx = cy = s // 2
    for dx in (-s * 0.12, 0, s * 0.12):
        pygame.draw.circle(surf, C_WHITE, (int(cx + dx), cy), max(2, s // 14))


def _render_jump_block(surf, s, frame_t):
    _render_letter_block(surf, s, "J")


def _render_wave_block(surf, s, frame_t):
    _render_letter_block(surf, s, "D")


def _render_bonk_block(surf, s, frame_t):
    _render_letter_block(surf, s, "H")


def _render_letter_block(surf, s, letter):
    """GD-style utility block: hollow outline square + letter.

    GD draws these with a plain ``blockOutline_01`` frame and puts the
    letter on as an editor-only overlay, so the real texture replaces
    only the hand-drawn square — the glyph stays exactly as it was.
    """
    outline = gd_atlas.compose(GD_SHEET_BLOCKS, GD_LETTER_BLOCK_FRAME, s)
    if outline is not None:
        surf.blit(_tinted(outline, C_WHITE), (0, 0))
    else:
        margin = max(4, int(s * 0.10))
        rect = pygame.Rect(margin, margin, s - margin * 2, s - margin * 2)
        width = max(2, int(s * 0.07))
        pygame.draw.rect(surf, C_WHITE, rect, width,
                         border_radius=max(2, int(s * 0.04)))
    txt(surf, letter, s // 2, s // 2, max(12, int(s * 0.55)), C_WHITE,
        True, shadow=True)


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


def sprite_extent(t, s=CELL, frame=0, variant=None):
    """``(w, h)`` the sprite for ``t`` actually occupies at cell size ``s``.

    Real-GD art keeps GD's own proportions, so the types GD draws bigger
    than one cell (portals at 1.5 x 3 cells, the saw at 2 x 2, the speed
    arrows) return more than ``(s, s)`` and overhang their cell.  Callers
    that blit into a surface of their own — the editor's ghost previews —
    need this to size that surface.
    """
    return _load_or_render(t, s, frame, variant).get_size()


def draw_obj(surf, t, x, y, s=CELL, pulse=0, rot=0, meta=None,
             scale=1.0, scale_y=None, alpha=255, tint=None, fit_cell=False):
    """Blit the pre-rendered sprite image for this object type.

    ``(x, y)`` is the top-left of the object's grid cell.  The sprite is
    centred on that cell rather than pinned to its corner, because the
    real-GD art for portals, saws and speed arrows is legitimately bigger
    than one cell and overhangs it symmetrically (see
    :func:`sprite_extent`).  For a one-cell sprite this is the same blit
    as before.

    ``fit_cell`` shrinks an oversized sprite back down so its longest
    side is ``s`` — for the editor palette and property previews, whose
    buttons an overhanging sprite would spill out of.

    ``alpha`` (Checkpoint 5's Alpha Trigger) is applied to a *copy* of
    the cached sprite -- the cache is shared across every instance of a
    type/frame/variant, so mutating it in place would leak one faded
    object's transparency onto every other object using the same
    cached surface.

    ``scale`` enlarges (or shrinks) the sprite around the cell center
    so scaled objects still occupy the same grid anchor. Accepts:
      * a uniform scalar (legacy)
      * a ``(sx, sy)`` tuple
      * a ``scale_y`` paired with a numeric ``scale`` (= sx)

    When ``sx != sy`` the sprite is stretched non-uniformly via
    ``pygame.transform.scale``; the cached square sprite stays the
    canonical render so other zoom levels still hit the cache.

    ``tint`` (Checkpoint 2's Area Tint) is an ``(r, g, b)`` multiply
    colour, applied to the same copy for the same cache-safety reason.
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
    if t in (T_TELEPORT_ORB, T_TELEPORT_PORTAL) and meta is not None:
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
    img = _load_or_render(t, s, frame, variant)
    iw, ih = img.get_size()
    if fit_cell and max(iw, ih) > s:
        shrink = s / max(iw, ih)
        iw = max(1, int(round(iw * shrink)))
        ih = max(1, int(round(ih * shrink)))
    # Sizes are taken from the sprite, not the cell, so an oversized
    # sprite scales about its own centre and keeps GD's proportions.
    sw = max(1, int(round(iw * sx)))
    sh = max(1, int(round(ih * sy)))
    scaled = (sw, sh) != img.get_size()
    if scaled:
        # One transform.scale per blit — caches don't help here because
        # every sx/sy combination is unique.
        img = pygame.transform.scale(img, (sw, sh))
    if alpha < 255 or tint:
        if not scaled:
            img = img.copy()  # transform.scale already returned a copy
        if tint:
            img.fill((*tint, 255), special_flags=pygame.BLEND_RGBA_MULT)
        if alpha < 255:
            img.set_alpha(alpha)
    if rot:
        rotated = pygame.transform.rotate(img, -rot)
        surf.blit(rotated, rotated.get_rect(center=(x + s / 2, y + s / 2)))
    else:
        surf.blit(img, (x + (s - sw) / 2.0, y + (s - sh) / 2.0))


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
    pulse_t = (pulse % PHYSICS_TPS) / PHYSICS_TPS  # `pulse` ticks once/tick
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


def init_sprite_cache():
    """Validate both sprite caches against the current signature.

    Runs at import, but from the bottom of the module: the signature
    hashes GD_ART_RECIPE, so the art recipe has to be defined first.
    """
    global _BUNDLED_OK
    _check_sprite_cache_version()
    _BUNDLED_OK = _bundled_sprites_valid()


def regenerate_sprite_assets(size=CELL):
    """Force-regenerate every sprite PNG at the given size.

    Useful after tweaking the rendering code — deletes any existing PNG
    for each (type, frame) and recomputes it so future loads pick up the
    new art.
    """
    from .objects import ALL_TYPES
    os.makedirs(SPRITES_DIR, exist_ok=True)
    _OBJECT_CACHE.clear()
    gd_atlas.clear_caches()
    # Atlas sheets may have been installed or removed since import, which
    # moves the signature — re-stamp the marker so the PNGs written below
    # are not wiped as "stale" on the next launch.
    init_sprite_cache()
    for t in ALL_TYPES:
        for f in range(_frame_count(t)):
            path = _sprite_path(t, size, f)
            try:
                if os.path.isfile(path):
                    os.remove(path)
            except OSError:
                pass
            _load_or_render(t, size, f)


init_sprite_cache()
