"""Drawing / asset helpers.

Sprites are real PNG images on disk under ``assets/sprites/``. Each sprite
is rendered once (at 2x and downsampled for anti-aliasing) then written to
disk; subsequent runs load the PNG directly. An in-memory cache keyed by
(type, size, frame, variant) avoids repeated disk hits per frame.

``draw_obj`` looks up the right frame based on ``pulse`` and blits — no
per-frame drawing primitives are used for object sprites.
"""

import functools
import math
import os
import random
from collections import OrderedDict

import pygame

from .constants import (
    ASSETS_DIR, CELL, WIDTH, HEIGHT, GROUND_Y, _USER_DATA,
    C_BG_TOP, C_BG_BOT, C_GROUND, C_GROUND_L, C_GROUND_DARK, C_WHITE, C_GRAY,
    C_BLOCK, C_BLOCK_H, C_BLOCK_D, C_SPIKE, C_ORB, C_DASH_ORB, C_TELEPORT_ORB,
    C_PAD, C_BLUE_PAD, C_GPORTAL, C_END, C_PLAYER, C_BTN, C_DARK,
    C_DECO_CRYSTAL, C_DECO_PILLAR, C_DECO_GLOW, C_COIN, C_CHECKPOINT,
    C_GREEN_ORB, C_SLAB, C_SAW, C_DANGER,
    TYPE_COLS, SPEED_VALUES, MODE_FROM_TYPE,
    T_BLOCK, T_SLAB, T_SPIKE, T_HALF_SPIKE, T_SAW, T_ORB, T_DASH_ORB,
    T_TELEPORT_ORB, T_BLACK_ORB, T_BLUE_ORB, T_GREEN_ORB, T_PAD, T_BLUE_PAD,
    T_GRAV, T_END, T_START, T_COIN, T_CHECKPOINT,
    T_MODE_CUBE, T_MODE_SHIP, T_MODE_BALL, T_MODE_WAVE, T_MODE_UFO, T_MODE_SPIDER,
    T_MODE_MINI, T_MODE_BIG, T_MODE_DUAL, T_MODE_SOLO,
    T_DECO_CRYSTAL, T_DECO_PILLAR, T_DECO_GLOW,
    T_CAMERA_TRIGGER, T_BG_TRIGGER, T_MOVE_TRIGGER, T_COLOR_TRIGGER,
    T_PULSE_TRIGGER, T_ROTATE_TRIGGER,
    T_SPEED_SLOW, T_SPEED_NORMAL, T_SPEED_FAST, T_SPEED_FASTER,
)

# ---------------------------------------------------------------------------
# Font cache + screen shake
# ---------------------------------------------------------------------------
_fonts = {}
_bg_gradient_cache = {"key": None, "surf": None}
shake_offset = [0, 0]
shake_intensity = 0


def get_font(size):
    if size not in _fonts:
        try:
            _fonts[size] = pygame.font.SysFont("arial", size, bold=True)
        except Exception:
            _fonts[size] = pygame.font.Font(None, size)
    return _fonts[size]


# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------
def lighter(c, a=50):
    return tuple(min(255, v + a) for v in c[:3])


def darker(c, a=50):
    return tuple(max(0, v - a) for v in c[:3])


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def draw_cube_icon_glyph(surf, x, y, size, color, icon_index):
    """Draw the inner glyph of the player's cube — one per icon variant.

    The outer cube body is drawn by the caller; this just paints the
    detail that distinguishes one icon from another. `color` is the
    base player color so the glyph harmonizes with whatever palette
    slot is active.

    Indices match constants.PLAYER_ICONS:
        0 Classic   small inset square
        1 Star      five-point star
        2 Triangle  upward triangle
        3 Diamond   diamond/rotated square
        4 Circle    circle
        5 Plus      cross/plus
        6 Heart     stylized heart
        7 Bolt      lightning bolt
    Unknown indices fall back to Classic so a stale prefs value never
    leaves the player invisible.
    """
    cx = x + size // 2
    cy = y + size // 2
    s = size
    inset = darker(color, 50)
    if icon_index == 1:  # Star
        import math
        pts = []
        for i in range(10):
            angle = -math.pi / 2 + i * math.pi / 5
            r = s * 0.32 if i % 2 == 0 else s * 0.14
            pts.append((cx + math.cos(angle) * r, cy + math.sin(angle) * r))
        pygame.draw.polygon(surf, inset, pts)
    elif icon_index == 2:  # Triangle
        pts = [(cx, y + s * 0.2), (x + s * 0.2, y + s * 0.78),
               (x + s * 0.8, y + s * 0.78)]
        pygame.draw.polygon(surf, inset, pts)
    elif icon_index == 3:  # Diamond
        r = int(s * 0.3)
        pts = [(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)]
        pygame.draw.polygon(surf, inset, pts)
    elif icon_index == 4:  # Circle
        pygame.draw.circle(surf, inset, (cx, cy), int(s * 0.28))
    elif icon_index == 5:  # Plus
        thick = max(3, s // 6)
        pygame.draw.rect(surf, inset,
                         (cx - thick // 2, y + s // 5, thick, s - 2 * s // 5))
        pygame.draw.rect(surf, inset,
                         (x + s // 5, cy - thick // 2, s - 2 * s // 5, thick))
    elif icon_index == 6:  # Heart
        # Two circles + downward triangle for a chunky heart silhouette.
        r = int(s * 0.16)
        pygame.draw.circle(surf, inset, (cx - r, cy - r // 2), r)
        pygame.draw.circle(surf, inset, (cx + r, cy - r // 2), r)
        pts = [(cx - 2 * r, cy - r // 2 + 2),
               (cx + 2 * r, cy - r // 2 + 2),
               (cx, cy + 2 * r)]
        pygame.draw.polygon(surf, inset, pts)
    elif icon_index == 7:  # Bolt
        pts = [
            (cx - s * 0.05, y + s * 0.18),
            (cx + s * 0.18, y + s * 0.18),
            (cx, cy),
            (cx + s * 0.20, cy),
            (cx - s * 0.10, y + s * 0.82),
            (cx + s * 0.05, cy + s * 0.05),
            (cx - s * 0.18, cy + s * 0.05),
        ]
        pygame.draw.polygon(surf, inset, pts)
    else:  # 0 / Classic / fallback
        pygame.draw.rect(surf, inset, (cx - 7, cy - 7, 14, 14), border_radius=2)


def lerp(a, b, t):
    return a + (b - a) * t


def lerp_col(a, b, t):
    return tuple(int(lerp(a[i], b[i], t)) for i in range(3))


# ---------------------------------------------------------------------------
# Screen shake
# ---------------------------------------------------------------------------
def update_shake():
    global shake_intensity
    if shake_intensity > 0:
        shake_offset[0] = random.randint(-shake_intensity, shake_intensity)
        shake_offset[1] = random.randint(-shake_intensity, shake_intensity)
        shake_intensity = max(0, shake_intensity - 1)
    else:
        shake_offset[0] = 0
        shake_offset[1] = 0


def apply_shake(intensity):
    global shake_intensity
    shake_intensity = max(shake_intensity, intensity)


# ---------------------------------------------------------------------------
# Text — with optional drop shadow for readability over busy backgrounds
# ---------------------------------------------------------------------------
# Rendered-text cache: (text, size, color_tuple) -> Surface. HUD f-strings
# like "Attempt 42" change at most once per second — before this cache each
# one re-ran font.render() every frame (60 Hz × 5+ lines = 300 wasted
# renders/sec). Bounded LRU so transient labels don't grow the cache.
@functools.lru_cache(maxsize=512)
def _render_text_cached(text, size, col):
    return get_font(size).render(text, True, col)


def txt(surf, text, x, y, size=22, col=C_WHITE, center=False, shadow=False):
    text = str(text)
    col_key = tuple(col)
    if shadow:
        s = _render_text_cached(text, size, (0, 0, 0))
        r = s.get_rect(center=(x + 2, y + 2)) if center else s.get_rect(topleft=(x + 1, y + 1))
        surf.blit(s, r)
    s = _render_text_cached(text, size, col_key)
    r = s.get_rect(center=(x, y)) if center else s.get_rect(topleft=(x, y))
    surf.blit(s, r)
    return r


_TITLE_GLOW_CACHE = {}


def draw_title_glow(surf, text, cx, cy, size=56, col=C_WHITE,
                    glow_col=None, glow_radius=10, glow_alpha=220):
    """Render `text` with a soft gaussian-blur halo behind it.

    Used for the main-menu title and any other "hero" label that needs
    to punch through a busy background. Cached by (text, size, col,
    glow_col, radius) so we're not re-blurring the same title every
    frame. Falls back gracefully when pygame's ``gaussian_blur`` isn't
    available (very old pygame versions).
    """
    glow_col = glow_col or col
    key = (text, size, tuple(col), tuple(glow_col), glow_radius)
    surf_glow = _TITLE_GLOW_CACHE.get(key)
    if surf_glow is None:
        font = get_font(size)
        base = font.render(text, True, glow_col)
        bw, bh = base.get_size()
        pad = glow_radius * 3 + 4
        src = pygame.Surface((bw + pad * 2, bh + pad * 2), pygame.SRCALPHA)
        src.blit(base, (pad, pad))
        try:
            blurred = pygame.transform.gaussian_blur(src, glow_radius)
        except (AttributeError, pygame.error):
            # Older pygame — use box_blur with a larger radius as proxy.
            try:
                blurred = pygame.transform.box_blur(src, glow_radius)
            except (AttributeError, pygame.error):
                blurred = src  # no blur available; still functional
        blurred.set_alpha(glow_alpha)
        surf_glow = blurred
        _TITLE_GLOW_CACHE[key] = surf_glow
        # Bound the cache — titles are small but rotating labels shouldn't
        # grow it unbounded.
        if len(_TITLE_GLOW_CACHE) > 32:
            _TITLE_GLOW_CACHE.pop(next(iter(_TITLE_GLOW_CACHE)))
    gr = surf_glow.get_rect(center=(cx, cy))
    surf.blit(surf_glow, gr)
    # Crisp text on top.
    txt(surf, text, cx, cy, size, col, center=True, shadow=True)


def draw_panel_footer(surf, panel_rect, text, size=12, col=C_GRAY):
    """Draw a keyboard-hint / help line anchored to a panel's bottom.

    Text sits INSIDE the panel, 18 px above its bottom edge and centred
    horizontally. Use this instead of ad-hoc `panel.bottom + 16` style
    placement — that pattern routinely clipped through the panel's own
    border or landed off-screen entirely (UI_AUDIT §1).
    """
    txt(surf, text, panel_rect.centerx, panel_rect.bottom - 18,
        size, col, center=True)


def size_panel_to_fit(content_h, min_h=200, max_h=HEIGHT - 40,
                      extra_padding=24):
    """Return a panel height that tightly wraps `content_h`, clamped to
    a sensible min/max. Use to kill the huge dead-space bands that
    show up when panels have hard-coded `panel_h` and variable content."""
    h = content_h + extra_padding
    return max(min_h, min(max_h, h))


def txt_wrap(surf, text, x, y, max_w, size=18, col=C_WHITE, line_h=None):
    """Simple word-wrap. Returns y after last line."""
    font = get_font(size)
    words = str(text).split()
    line_h = line_h or (size + 4)
    line = ""
    cy = y
    for w in words:
        test = w if not line else line + " " + w
        if font.size(test)[0] <= max_w:
            line = test
        else:
            if line:
                surf.blit(font.render(line, True, col), (x, cy))
                cy += line_h
            line = w
    if line:
        surf.blit(font.render(line, True, col), (x, cy))
        cy += line_h
    return cy


# ---------------------------------------------------------------------------
# Button — polished with hover + shadow
# ---------------------------------------------------------------------------
# Per-button hover-ease state. Keyed on (cx, cy, label) because those
# together uniquely identify a button location in any menu; the dict is
# bounded by manual eviction of entries that haven't been ticked
# recently (anything older than ~2s is unreachable UI).
_HOVER_EASE = {}
_HOVER_EASE_MAX = 256
_HOVER_EASE_SPEED = 0.18  # fraction of the remaining gap per frame


def _hover_t(key, target, *, _frame=[0]):
    """Return eased [0,1] hover weight for `key`, moving toward `target`.
    Simple lerp at a fixed rate — `dt` isn't threaded through the menu
    draw path yet, so frame-rate-assumed easing is close enough (menus
    run at 60 Hz via `settings.get_fps_cap`)."""
    _frame[0] += 1
    entry = _HOVER_EASE.get(key)
    if entry is None:
        t = 1.0 if target >= 1.0 else 0.0
    else:
        t = entry[0]
        t += (target - t) * _HOVER_EASE_SPEED
        if abs(t - target) < 0.01:
            t = target
    _HOVER_EASE[key] = (t, _frame[0])
    # Evict stale entries once the dict gets too full — cheap and only
    # fires occasionally because the menu vocabulary is small.
    if len(_HOVER_EASE) > _HOVER_EASE_MAX:
        cutoff = _frame[0] - 120
        for k in list(_HOVER_EASE.keys()):
            if _HOVER_EASE[k][1] < cutoff:
                del _HOVER_EASE[k]
    return t


def _lerp_rgb(a, b, t):
    return (int(a[0] + (b[0] - a[0]) * t),
            int(a[1] + (b[1] - a[1]) * t),
            int(a[2] + (b[2] - a[2]) * t))


def btn(surf, label, cx, cy, w=180, h=46, col=C_BTN, mpos=None, disabled=False,
        font_size=20):
    r = pygame.Rect(cx - w // 2, cy - h // 2, w, h)
    hovered = (mpos is not None) and r.collidepoint(mpos) and not disabled
    if disabled:
        base = darker(col, 50)
        lbl_col = (160, 160, 170)
    else:
        # Eased hover — color lerps smoothly toward the hover tint
        # instead of snapping. Makes every button feel less cheap.
        hot = lighter(col, 35)
        t = _hover_t((cx, cy, label), 1.0 if hovered else 0.0)
        base = _lerp_rgb(col, hot, t) if t > 0.0 else col
        lbl_col = C_WHITE
    pygame.draw.rect(surf, darker(base, 50), r.move(0, 3), border_radius=10)
    pygame.draw.rect(surf, base, r, border_radius=10)
    pygame.draw.rect(surf, lighter(base, 55), r, 2, border_radius=10)
    if hovered:
        gloss = pygame.Rect(r.x + 4, r.y + 3, r.w - 8, r.h // 3)
        pygame.draw.rect(surf, (*lighter(base, 80), ), gloss, border_radius=6)
    txt(surf, label, cx, cy, font_size, lbl_col, True)
    return r


def make_rect(cx, cy, w, h):
    return pygame.Rect(cx - w // 2, cy - h // 2, w, h)


# ---------------------------------------------------------------------------
# Object hitbox helpers
# ---------------------------------------------------------------------------
def normalize_rotation(r):
    try:
        return int(round(float(r) / 90.0) * 90) % 360
    except (TypeError, ValueError):
        return 0


def _scale_rect_around_cell_center(rect, gx, gy, scale):
    """Return ``rect`` scaled uniformly around the cell's center point.

    Used by every collision helper so a scaled object's visual footprint
    and its hitbox stay in lock-step regardless of where within the cell
    the base rect was anchored.
    """
    if scale == 1.0:
        return rect
    cx = gx * CELL + CELL / 2.0
    cy = gy * CELL + CELL / 2.0
    nw = rect.w * scale
    nh = rect.h * scale
    nx = cx + (rect.x - cx) * scale
    ny = cy + (rect.y - cy) * scale
    return pygame.Rect(round(nx), round(ny), max(1, round(nw)), max(1, round(nh)))


def cell_rect(gx, gy, scale=1.0):
    base = pygame.Rect(gx * CELL, gy * CELL, CELL, CELL)
    return _scale_rect_around_cell_center(base, gx, gy, scale)


# Slab local offsets (pre-rotation) in cell-local coords. Precomputed so
# slab_rect just branches the table and does one Rect alloc — no repeated
# normalize_rotation / if-chain per call.
_SLAB_LOCAL = {
    0:   (0,          CELL // 2, CELL,      CELL // 2),
    180: (0,          0,         CELL,      CELL // 2),
    90:  (0,          0,         CELL // 2, CELL),
    270: (CELL // 2,  0,         CELL // 2, CELL),
}


def slab_rect(gx, gy, rotation=0, scale=1.0):
    """Slab is half-height; rotation determines which edge it sits on."""
    lx, ly, lw, lh = _SLAB_LOCAL[normalize_rotation(rotation)]
    base = pygame.Rect(gx * CELL + lx, gy * CELL + ly, lw, lh)
    return _scale_rect_around_cell_center(base, gx, gy, scale)


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
    if half:
        base = (pygame.Rect(14, 34, 22, 8), pygame.Rect(18, 28, 14, 6))
    else:
        base = (pygame.Rect(14, 34, 22, 8), pygame.Rect(18, 24, 14, 10))
    return tuple(rotate_local_rect(r, rotation) for r in base)


def spike_hitboxes(gx, gy, rotation=0, half=False, scale=1.0):
    x = gx * CELL
    y = gy * CELL
    rects = [r.move(x, y) for r in
             _spike_base_rotated(normalize_rotation(rotation), bool(half))]
    if scale == 1.0:
        return rects
    return [_scale_rect_around_cell_center(r, gx, gy, scale) for r in rects]


@functools.lru_cache(maxsize=8)
def _pad_trigger_base_rotated(rotation):
    return rotate_local_rect(
        pygame.Rect(5, CELL - 18, CELL - 10, 18), rotation)


def pad_trigger_rect(gx, gy, rotation=0):
    return _pad_trigger_base_rotated(normalize_rotation(rotation)).move(
        gx * CELL, gy * CELL)


def saw_hitbox(gx, gy, scale=1.0):
    """Circular saw hitbox — smaller than the grid cell for fairness."""
    base = cell_rect(gx, gy).inflate(-10, -10)
    return _scale_rect_around_cell_center(base, gx, gy, scale)


# ---------------------------------------------------------------------------
# Background (stars, mountains, ground stripe)
# ---------------------------------------------------------------------------
def make_stars(n=140):
    return [
        (random.randint(-400, 6000), random.randint(0, GROUND_Y - 30),
         random.randint(1, 3), random.randint(80, 220))
        for _ in range(n)
    ]


def make_mountains(layers=3):
    layers_out = []
    for li in range(layers):
        pts = []
        x = -200
        y_base = GROUND_Y - 40 - li * 35
        while x < 8000:
            pts.append((x, y_base - random.randint(20, 80 + li * 30)))
            x += random.randint(80, 180)
        layers_out.append(pts)
    return layers_out


def _gradient_bg(top, bot):
    key = (tuple(top), tuple(bot))
    if _bg_gradient_cache["key"] != key:
        surf = pygame.Surface((1, GROUND_Y))
        for y in range(GROUND_Y):
            t = y / max(1, GROUND_Y - 1)
            r = int(top[0] + (bot[0] - top[0]) * t)
            g = int(top[1] + (bot[1] - top[1]) * t)
            b = int(top[2] + (bot[2] - top[2]) * t)
            surf.set_at((0, y), (r, g, b))
        _bg_gradient_cache["key"] = key
        _bg_gradient_cache["surf"] = pygame.transform.scale(surf, (WIDTH, GROUND_Y))
    return _bg_gradient_cache["surf"]


def draw_bg(surf, cam_x=0, stars=None, mountains=None, cam_y=0, bg_top=None, bg_bot=None):
    top = bg_top if bg_top is not None else C_BG_TOP
    bot = bg_bot if bg_bot is not None else C_BG_BOT
    surf.blit(_gradient_bg(top, bot), (0, 0))
    ground_screen_y = GROUND_Y - int(cam_y)
    if ground_screen_y < HEIGHT:
        surf.fill(C_GROUND_DARK, (0, max(0, ground_screen_y), WIDTH, HEIGHT - max(0, ground_screen_y)))
    if stars:
        for sx, sy, sr, sb in stars:
            px = int((sx - cam_x * 0.12) % (WIDTH + 400) - 200)
            py = int(sy - cam_y * 0.12)
            if py < 0 or py >= HEIGHT:
                continue
            col = (sb, sb, min(255, sb + 30))
            if sr >= 2:
                pygame.draw.circle(surf, col, (px, py), sr)
            else:
                surf.set_at((px, py), col)
    if mountains:
        speeds = [0.18, 0.32, 0.5]
        shades = [(22, 18, 54), (32, 26, 70), (46, 34, 92)]
        for i, layer in enumerate(mountains):
            speed = speeds[i] if i < len(speeds) else 0.6
            shade = shades[i] if i < len(shades) else (60, 44, 110)
            offset_x = cam_x * speed
            offset_y = cam_y * speed
            base_y = ground_screen_y
            poly = [(-50, base_y)]
            for x, y in layer:
                sx = x - offset_x
                if -300 < sx < WIDTH + 300:
                    poly.append((sx, y - offset_y))
            poly.append((WIDTH + 50, base_y))
            if len(poly) > 2:
                pygame.draw.polygon(surf, shade, poly)
    if 0 <= ground_screen_y < HEIGHT:
        pygame.draw.rect(surf, C_GROUND, (0, ground_screen_y, WIDTH, 14))
        pygame.draw.line(surf, C_GROUND_L, (0, ground_screen_y), (WIDTH, ground_screen_y), 3)
        stripe_off = int(-cam_x) % 60
        for sx in range(-60 + stripe_off, WIDTH, 60):
            pygame.draw.line(surf, lighter(C_GROUND, 15),
                             (sx, ground_screen_y + 14), (sx + 40, ground_screen_y + 14), 2)


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
SPRITE_CACHE_VERSION = "1"
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
_ANIMATED_TYPES = {
    T_SAW, T_ORB, T_DASH_ORB, T_TELEPORT_ORB, T_BLACK_ORB, T_BLUE_ORB,
    T_GREEN_ORB, T_COIN, T_DECO_GLOW, T_GRAV, T_END,
    T_MODE_CUBE, T_MODE_SHIP, T_MODE_BALL, T_MODE_WAVE, T_MODE_UFO, T_MODE_SPIDER,
    T_MODE_MINI, T_MODE_BIG, T_MODE_DUAL, T_MODE_SOLO,
    T_SPEED_SLOW, T_SPEED_NORMAL, T_SPEED_FAST, T_SPEED_FASTER,
}


def _frame_count(t):
    return SPRITE_FRAMES if t in _ANIMATED_TYPES else 1


def _sprite_filename(t, s, frame):
    if t in _ANIMATED_TYPES:
        return f"{t}_s{s}_f{frame}.png"
    return f"{t}_s{s}.png"


def _sprite_path(t, s, frame):
    """Writable per-user sprite-cache path."""
    return os.path.join(SPRITES_DIR, _sprite_filename(t, s, frame))


def _bundled_sprite_path(t, s, frame):
    """Read-only bundled sprite path."""
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


def _render_dash_orb(surf, s, frame_t):
    def _icon(surf, cx, cy, r):
        pygame.draw.polygon(surf, lighter(C_DASH_ORB, 50),
                            [(cx + r - 2, cy), (cx - 4, cy - 7), (cx - 4, cy + 7)])
        pygame.draw.polygon(surf, C_WHITE,
                            [(cx + r - 2, cy), (cx - 4, cy - 7), (cx - 4, cy + 7)], 1)
    _render_orb_hq(surf, C_DASH_ORB, s, frame_t, outline_only=True,
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


def _render_pad(surf, s, frame_t, blue=False):
    col = C_BLUE_PAD if blue else C_PAD
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
    if blue:
        cx = s // 2
        pygame.draw.polygon(surf, C_WHITE,
                            [(cx - 5, s - 11), (cx + 5, s - 11), (cx, s - 3)])
        pygame.draw.polygon(surf, darker(C_WHITE, 40),
                            [(cx - 5, s - 11), (cx + 5, s - 11), (cx, s - 3)], 1)


def _render_grav(surf, s, frame_t):
    rr = _render_portal_hq(surf, s, C_GPORTAL, frame_t, inner_scale=0.62)
    # Dual arrow (up-down)
    arrow = [(rr.centerx, rr.y + 6),
             (rr.centerx - 7, rr.y + 18), (rr.centerx - 2, rr.y + 18),
             (rr.centerx - 2, rr.bottom - 18), (rr.centerx - 7, rr.bottom - 18),
             (rr.centerx, rr.bottom - 6),
             (rr.centerx + 7, rr.bottom - 18), (rr.centerx + 2, rr.bottom - 18),
             (rr.centerx + 2, rr.y + 18), (rr.centerx + 7, rr.y + 18)]
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


def _render_speed_portal(surf, s, frame_t, t):
    col = TYPE_COLS[t]
    rr = _render_portal_hq(surf, s, col, frame_t, inner_scale=0.55)
    count = {T_SPEED_SLOW: 1, T_SPEED_NORMAL: 2, T_SPEED_FAST: 3,
             T_SPEED_FASTER: 4}[t]
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
    else:
        label = {T_BG_TRIGGER: "BG", T_MOVE_TRIGGER: "MV",
                 T_COLOR_TRIGGER: "CL", T_PULSE_TRIGGER: "PL",
                 T_ROTATE_TRIGGER: "RT"}.get(t, "?")
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
    T_SPIKE:       lambda s, b, f, v: _render_spike(s, b, f, half=False),
    T_HALF_SPIKE:  lambda s, b, f, v: _render_spike(s, b, f, half=True),
    T_SAW:         lambda s, b, f, v: _render_saw(s, b, f),
    T_ORB:         lambda s, b, f, v: _render_orb(s, b, f),
    T_DASH_ORB:    lambda s, b, f, v: _render_dash_orb(s, b, f),
    T_TELEPORT_ORB: lambda s, b, f, v: _render_teleport_orb(s, b, f, link_label=v),
    T_BLACK_ORB:   lambda s, b, f, v: _render_black_orb(s, b, f),
    T_BLUE_ORB:    lambda s, b, f, v: _render_blue_orb(s, b, f),
    T_GREEN_ORB:   lambda s, b, f, v: _render_green_orb(s, b, f),
    T_PAD:         lambda s, b, f, v: _render_pad(s, b, f, blue=False),
    T_BLUE_PAD:    lambda s, b, f, v: _render_pad(s, b, f, blue=True),
    T_GRAV:        lambda s, b, f, v: _render_grav(s, b, f),
    T_END:         lambda s, b, f, v: _render_end(s, b, f),
    T_START:       lambda s, b, f, v: _render_start(s, b, f),
    T_COIN:        lambda s, b, f, v: _render_coin(s, b, f),
    T_CHECKPOINT:  lambda s, b, f, v: _render_checkpoint(s, b, f),
    T_DECO_CRYSTAL: lambda s, b, f, v: _render_deco_crystal(s, b, f),
    T_DECO_PILLAR:  lambda s, b, f, v: _render_deco_pillar(s, b, f),
    T_DECO_GLOW:    lambda s, b, f, v: _render_deco_glow(s, b, f),
}

_TRIGGER_TYPES_SET = {
    T_CAMERA_TRIGGER, T_BG_TRIGGER, T_MOVE_TRIGGER, T_COLOR_TRIGGER,
    T_PULSE_TRIGGER, T_ROTATE_TRIGGER,
}

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
            if os.path.isfile(path):
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


def draw_obj(surf, t, x, y, s=CELL, pulse=0, rot=0, meta=None, scale=1.0):
    """Blit the pre-rendered sprite image for this object type.

    ``scale`` enlarges (or shrinks) the sprite uniformly around the cell
    center so scaled objects still occupy the same grid anchor.
    """
    rot = normalize_rotation(rot)
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
    if scale != 1.0:
        obj_s = max(1, int(round(s * scale)))
        x = x + (s - obj_s) / 2.0
        y = y + (s - obj_s) / 2.0
        s = obj_s
    frames = _frame_count(t)
    frame = int(pulse / (60 / frames)) % frames if frames > 1 else 0
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
    from .constants import ALL_TYPES
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


# ---------------------------------------------------------------------------
# UI icons — mute/speaker button graphic
# ---------------------------------------------------------------------------
_ICON_CACHE = {}


def speaker_icon(size=22, muted=False):
    """Return a cached speaker icon Surface (white on transparent)."""
    key = (size, bool(muted))
    cached = _ICON_CACHE.get(key)
    if cached is not None:
        return cached
    # Render at 2x and smoothscale down for crisp edges
    big = size * 2
    surf = pygame.Surface((big, big), pygame.SRCALPHA)
    cx, cy = big // 2, big // 2
    # Speaker body (cone + back block)
    back = pygame.Rect(cx - int(big * 0.35), cy - int(big * 0.18),
                       int(big * 0.22), int(big * 0.36))
    pygame.draw.rect(surf, C_WHITE, back)
    horn_pts = [
        (back.right, back.top),
        (back.right + int(big * 0.22), back.top - int(big * 0.16)),
        (back.right + int(big * 0.22), back.bottom + int(big * 0.16)),
        (back.right, back.bottom),
    ]
    pygame.draw.polygon(surf, C_WHITE, horn_pts)
    if muted:
        # Red "X" to the right of the speaker
        ox = back.right + int(big * 0.3)
        oy = cy
        dx = int(big * 0.14)
        pygame.draw.line(surf, C_DANGER, (ox - dx, oy - dx),
                         (ox + dx, oy + dx), max(2, big // 16))
        pygame.draw.line(surf, C_DANGER, (ox + dx, oy - dx),
                         (ox - dx, oy + dx), max(2, big // 16))
    else:
        # Three sound-wave arcs
        for i in range(3):
            r = int(big * (0.14 + i * 0.09))
            rect = pygame.Rect(0, 0, r * 2, r * 2)
            rect.center = (back.right + int(big * 0.05), cy)
            pygame.draw.arc(surf, C_WHITE, rect,
                            -math.pi / 3.2, math.pi / 3.2,
                            max(2, big // 20))
    icon = pygame.transform.smoothscale(surf, (size, size))
    _ICON_CACHE[key] = icon
    return icon


def icon_button(surf, icon, cx, cy, w=40, h=40, col=C_BTN, mpos=None, active=False):
    """Square button with an icon centred — used for mute toggle etc.

    `icon` may be None when the caller wants the chrome only and plans
    to draw its own glyph on top (e.g. the gear icon overlay on the
    main menu).
    """
    r = pygame.Rect(cx - w // 2, cy - h // 2, w, h)
    hovered = mpos is not None and r.collidepoint(mpos)
    base = lighter(col, 35) if hovered else col
    if active:
        base = darker(base, 20)
    pygame.draw.rect(surf, darker(base, 50), r.move(0, 2), border_radius=8)
    pygame.draw.rect(surf, base, r, border_radius=8)
    pygame.draw.rect(surf, lighter(base, 55), r, 1, border_radius=8)
    if icon is not None:
        ir = icon.get_rect(center=r.center)
        surf.blit(icon, ir)
    return r
