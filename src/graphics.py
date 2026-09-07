"""UI drawing helpers: fonts, text, buttons, colour helpers, screen shake,
the parallax background, and small icons.

Sprite rendering lives in :mod:`sprites`; hitbox geometry in
:mod:`geometry`.  Both are re-exported here so existing ``from .graphics
import ...`` call sites keep working.
"""

import functools
import math
import random

import pygame

from .constants import (
    WIDTH, HEIGHT, GROUND_Y,
    C_BG_TOP, C_BG_BOT, C_GROUND, C_GROUND_L, C_GROUND_DARK, C_WHITE, C_GRAY,
    C_BTN, C_DANGER,
)
from .geometry import (  # noqa: F401  (re-exported)
    clamp, lerp, normalize_rotation, obj_scale, cell_rect, slab_rect,
    rotate_local_rect, spike_hitboxes, pad_trigger_rect, slope_polygon,
    saw_hitbox,
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


# ---------------------------------------------------------------------------
# GD-style shape primitives
#
# Geometry Dash art is built from flat-shaded shapes carrying three cues:
# a dark outer contour, a lighter inner bevel on the top-left, and a
# darker one on the bottom-right. These helpers apply that treatment
# consistently so objects (src/sprites.py) and the player icons
# (src/player/draw.py) read as one art style instead of each renderer
# inventing its own shading.
# ---------------------------------------------------------------------------
OUTLINE_DARKEN = 95      # how much darker than the fill a contour line is
BEVEL_LIGHTEN = 60       # top-left inner bevel lift
BEVEL_DARKEN = 45        # bottom-right inner bevel drop


def outline_col(col, amount=OUTLINE_DARKEN):
    """Contour colour for `col` — dark enough to read at 24 px."""
    return darker(col, amount)


def draw_outlined_poly(surf, pts, col, width=2, line_col=None):
    """Flat polygon with a GD contour."""
    pygame.draw.polygon(surf, col, pts)
    pygame.draw.polygon(surf, line_col or outline_col(col), pts, width)


@functools.lru_cache(maxsize=256)
def _corner_inset(radius, outline):
    """How far in from the fill edge a bevel line must start to stay
    inside a `radius` corner arc.

    The binding row is the outermost one the bevel band covers, `outline`
    px inside the panel edge: there the arc has already curved in by
    ``radius - sqrt(radius**2 - (radius - outline)**2)``.  Returned
    relative to the inner (post-outline) rect, so it is 0 for square
    panels.
    """
    if radius <= 0:
        return 0
    dy = max(0, radius - outline)
    dx = math.sqrt(max(0.0, radius * radius - dy * dy))
    # +2 of slack: pygame rasterises the arc a hair tighter than the exact
    # circle, and by a further pixel on the bottom/right edges, so the
    # analytic figure on its own still leaks a couple of corner pixels.
    return max(0, math.ceil(radius - dx) + 2 - outline)


def draw_bevel_rect(surf, rect, col, radius=0, outline=2, bevel=None,
                    line_col=None):
    """Panel with a dark contour and a two-tone inner bevel.

    This is the workhorse for blocks, robot torsos, pads and portal
    plates — anything that in GD reads as a solid slab with depth
    rather than a flat ``pygame.draw.rect``.
    """
    bevel = bevel if bevel is not None else max(1, min(rect.w, rect.h) // 12)
    pygame.draw.rect(surf, col, rect, border_radius=radius)
    inner = rect.inflate(-outline * 2, -outline * 2)
    # ``pygame.draw.line`` knows nothing about ``border_radius``, so on a
    # rounded panel the bevel end-caps would spill past the corner arc and
    # paint stray pixels on the background.  Pull the endpoints in far
    # enough that the outermost row/column of each bevel band still sits
    # inside the arc.
    pad = max(bevel, _corner_inset(radius, outline))
    if inner.w > pad * 2 and inner.h > pad * 2:
        half = max(1, bevel // 2)
        hi = lighter(col, BEVEL_LIGHTEN)
        lo = darker(col, BEVEL_DARKEN)
        pygame.draw.line(surf, hi, (inner.left + pad, inner.top + half),
                         (inner.right - pad, inner.top + half), bevel)
        pygame.draw.line(surf, hi, (inner.left + half, inner.top + pad),
                         (inner.left + half, inner.bottom - pad), bevel)
        pygame.draw.line(surf, lo, (inner.left + pad, inner.bottom - half),
                         (inner.right - pad, inner.bottom - half), bevel)
        pygame.draw.line(surf, lo, (inner.right - half, inner.top + pad),
                         (inner.right - half, inner.bottom - pad), bevel)
    if outline > 0:
        pygame.draw.rect(surf, line_col or outline_col(col), rect, outline,
                         border_radius=radius)


def draw_bevel_circle(surf, center, r, col, outline=2, gloss=True,
                      line_col=None):
    """Sphere-ish disc: shaded crescent, contour ring and a gloss cap."""
    cx, cy = int(center[0]), int(center[1])
    r = int(r)
    if r <= 1:
        pygame.draw.circle(surf, col, (cx, cy), max(1, r))
        return
    pygame.draw.circle(surf, darker(col, BEVEL_DARKEN), (cx, cy), r)
    off = max(1, r // 8)
    pygame.draw.circle(surf, col, (cx - off, cy - off), r - off)
    if gloss:
        draw_gloss(surf, pygame.Rect(cx - r, cy - r, r * 2, r * 2))
    if outline > 0:
        pygame.draw.circle(surf, line_col or outline_col(col), (cx, cy), r,
                           outline)


def draw_gloss(surf, rect, alpha=120, width_frac=0.62, height_frac=0.34):
    """Glossy highlight cap sitting in the upper part of `rect`."""
    w = max(2, int(rect.w * width_frac))
    h = max(2, int(rect.h * height_frac))
    g = pygame.Surface((w, h), pygame.SRCALPHA)
    pygame.draw.ellipse(g, (255, 255, 255, alpha), g.get_rect())
    surf.blit(g, (rect.centerx - w // 2, rect.y + int(rect.h * 0.09)))


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
    # Strong contrast: GD icon glyphs read as a near-black cut-out of
    # the body, not a slightly darker tint.
    inset = darker(color, 110)
    if icon_index == 1:  # Star
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
        # Proportional so the glyph survives supersampled player renders.
        half = max(2, int(s * 0.16))
        pygame.draw.rect(surf, inset, (cx - half, cy - half, half * 2, half * 2),
                         border_radius=max(1, s // 20))


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
    """GD-style pill button: chunky bevel fill, thick white ring, drop
    shadow — the look of the game's PLAY / BUILD / EDIT chrome rather
    than a flat web button."""
    r = pygame.Rect(cx - w // 2, cy - h // 2, w, h)
    hovered = (mpos is not None) and r.collidepoint(mpos) and not disabled
    radius = h // 2
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
    pygame.draw.rect(surf, darker(base, 55), r.move(0, 4), border_radius=radius)
    draw_bevel_rect(surf, r, base, radius=radius, outline=max(2, h // 15),
                    bevel=max(2, h // 6),
                    line_col=None if disabled else C_WHITE)
    if hovered:
        draw_gloss(surf, r.inflate(-r.w // 4, -r.h // 3), alpha=70)
    txt(surf, label, cx, cy, font_size, lbl_col, True, shadow=True)
    return r


def make_rect(cx, cy, w, h):
    return pygame.Rect(cx - w // 2, cy - h // 2, w, h)


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
        surf = pygame.Surface((1, HEIGHT))
        for y in range(HEIGHT):
            t = y / max(1, HEIGHT - 1)
            surf.set_at((0, y), (int(top[0] + (bot[0] - top[0]) * t),
                                 int(top[1] + (bot[1] - top[1]) * t),
                                 int(top[2] + (bot[2] - top[2]) * t)))
        _bg_gradient_cache["key"] = key
        _bg_gradient_cache["surf"] = pygame.transform.scale(surf, (WIDTH, HEIGHT))
    return _bg_gradient_cache["surf"]


_MOUNTAIN_SPEEDS = (0.18, 0.32, 0.5)
_MOUNTAIN_SHADES = ((22, 18, 54), (32, 26, 70), (46, 34, 92))


def draw_bg(surf, cam_x=0, stars=None, mountains=None, cam_y=0, bg_top=None,
            bg_bot=None, ground_y=GROUND_Y):
    """Parallax background.  Always paints the entire viewport (the old
    version left the strip below the ground line unpainted whenever the
    camera scrolled the ground off-screen, which smeared previous frames
    across vertical sections)."""
    top = bg_top if bg_top is not None else C_BG_TOP
    bot = bg_bot if bg_bot is not None else C_BG_BOT
    surf.blit(_gradient_bg(top, bot), (0, 0))
    ground_screen_y = int(ground_y - cam_y)
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
        for i, layer in enumerate(mountains):
            speed = _MOUNTAIN_SPEEDS[i] if i < 3 else 0.6
            shade = _MOUNTAIN_SHADES[i] if i < 3 else (60, 44, 110)
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
    if ground_screen_y < HEIGHT:
        gy = max(0, ground_screen_y)
        surf.fill(C_GROUND_DARK, (0, gy, WIDTH, HEIGHT - gy))
    if -14 <= ground_screen_y < HEIGHT:
        pygame.draw.rect(surf, C_GROUND, (0, ground_screen_y, WIDTH, 14))
        pygame.draw.line(surf, C_GROUND_L, (0, ground_screen_y),
                         (WIDTH, ground_screen_y), 3)
        stripe_off = int(-cam_x) % 60
        for sx in range(-60 + stripe_off, WIDTH, 60):
            pygame.draw.line(surf, lighter(C_GROUND, 15),
                             (sx, ground_screen_y + 14),
                             (sx + 40, ground_screen_y + 14), 2)


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
    """Round button with an icon centred — GD's gear / undo / redo chrome.

    `icon` may be None when the caller wants the chrome only and plans
    to draw its own glyph on top (e.g. the gear icon overlay on the
    main menu).
    """
    # The chrome is a circle of `min(w, h)`, so the hit rect is squared off
    # to match — otherwise a non-square call leaves strips that click but
    # show no button under the cursor.
    radius = min(w, h) // 2
    r = pygame.Rect(cx - radius, cy - radius, radius * 2, radius * 2)
    hovered = mpos is not None and r.collidepoint(mpos)
    base = lighter(col, 35) if hovered else col
    if active:
        base = darker(base, 20)
    pygame.draw.circle(surf, darker(base, 55), (cx, cy + 3), radius)
    draw_bevel_circle(surf, (cx, cy), radius, base,
                      outline=max(2, radius // 6), line_col=C_WHITE)
    if icon is not None:
        ir = icon.get_rect(center=r.center)
        surf.blit(icon, ir)
    return r


# Sprite API re-exported for backwards compatibility.  Resolved lazily
# (PEP 562) because ``sprites`` itself imports ``txt`` / colour helpers
# from this module.
_SPRITE_EXPORTS = frozenset({
    "draw_obj", "draw_end_wall", "clear_obj_cache", "regenerate_sprite_assets",
    "SPRITE_FRAMES", "SPRITES_DIR", "BUNDLED_SPRITES_DIR",
    "SPRITE_CACHE_VERSION", "_OBJECT_CACHE", "_OBJECT_CACHE_MAX",
    "_load_or_render",
})


def __getattr__(name):
    if name in _SPRITE_EXPORTS:
        from . import sprites
        return getattr(sprites, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
