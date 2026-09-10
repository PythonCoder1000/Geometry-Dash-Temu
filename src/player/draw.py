"""Player rendering: per-mode sprite, ghost / line trails, mirror body.

Sprites and ghost-trail stamps are cached per (mode, size, colour, ...)
so a frame never allocates a fresh Surface for a trail sample; the old
renderer allocated one per ghost per frame (plus a full-screen surface
per line trail) which was a large part of the frame budget.
"""

import pygame

from ..constants import (
    WIDTH, HEIGHT, PLAYER_SIZE, ALL_MODES, PX_PER_UNIT, icon_size_units,
    MODE_CUBE, MODE_SHIP, MODE_BALL, MODE_WAVE, MODE_UFO, MODE_SPIDER,
    MODE_SWING, MODE_ROBOT,
    C_DASH_ORB, C_PAD, C_MODE_WAVE, C_MODE_UFO, C_MODE_SPIDER,
    C_MODE_SWING, C_MODE_ROBOT,
)
from ..graphics import (
    lighter, darker, draw_cube_icon_glyph, draw_bevel_rect, draw_bevel_circle,
    draw_outlined_poly, draw_gloss, outline_col,
)
from .. import gd_atlas

# Every mode draws the same thing: one solid, opaque ribbon of the
# player's colour through the trail samples.  Only its thickness is
# per-mode (unlisted modes take _LINE_THICKNESS_DEFAULT).  Because the
# whole sample list is redrawn each frame in the CURRENT mode's style,
# a mode portal instantly restyles the trail already on screen.
_LINE_TRAIL_MODES = frozenset(ALL_MODES)
_LINE_THICKNESS = {MODE_SHIP: 5, MODE_SPIDER: 4, MODE_CUBE: 6, MODE_BALL: 6,
                   MODE_UFO: 5, MODE_ROBOT: 6}
_LINE_THICKNESS_DEFAULT = 3

# Icons are drawn on a canvas this many times larger than PLAYER_SIZE and
# smoothscaled down. GD icons are dense (outline + bevel + glyph); drawn
# straight at 44 px those details land on half-pixels and read as mush.
# The result is cached per (mode, colour, icon, state) so the cost is paid
# once per distinct icon, not per frame.
PLAYER_SUPERSAMPLE = 3

# Non-player-coloured accents shared by several modes.
C_HULL = (78, 84, 104)          # ship / spider chassis metal
C_GLASS = (150, 225, 255)       # canopy + UFO dome glass
C_FLAME_CORE = (255, 245, 190)  # inner flame

# Module-level caches (shared by every Player instance).
_SPRITE_CACHE = {}
_LINE_SURF = [None]


def _frect(s, x, y, w, h):
    """Rect from fractions of the icon canvas size `s`."""
    return pygame.Rect(int(s * x), int(s * y), max(1, int(s * w)),
                       max(1, int(s * h)))


def _fpts(s, pts):
    return [(s * px, s * py) for px, py in pts]


def _draw_flame(surf, s, tip_x, cy, back_x, spread, col):
    """Rear thruster flame — two nested tapered triangles."""
    outer = [(s * tip_x, s * cy), (s * back_x, s * (cy - spread)),
             (s * back_x, s * (cy + spread))]
    pygame.draw.polygon(surf, col, outer)
    inner_tip = tip_x + (back_x - tip_x) * 0.4
    pygame.draw.polygon(surf, C_FLAME_CORE, [
        (s * inner_tip, s * cy), (s * back_x, s * (cy - spread * 0.5)),
        (s * back_x, s * (cy + spread * 0.5))])


def _draw_cube_body(surf, s, rect, col, icon_index):
    """The player cube — used solo and as the pilot inside ship/UFO."""
    radius = max(2, int(rect.w * 0.16))
    draw_bevel_rect(surf, rect, col, radius=radius,
                    outline=max(2, int(rect.w * 0.10)),
                    bevel=max(1, int(rect.w * 0.09)))
    draw_cube_icon_glyph(surf, rect.x, rect.y, rect.w, col, icon_index)
    draw_gloss(surf, rect.inflate(-rect.w // 4, -rect.h // 3), alpha=60,
               width_frac=0.9, height_frac=0.8)


def _draw_ship(surf, s, col, icon_index, dashing):
    cy = 0.5
    # Sleek wedge hull: pointed nose, flat-ish belly, swept back edge.
    hull = _fpts(s, [(0.99, 0.52), (0.74, 0.28), (0.34, 0.24), (0.14, 0.34),
                     (0.07, 0.50), (0.13, 0.66), (0.38, 0.78), (0.80, 0.68)])
    # Low tail fin behind the hull adds a ship silhouette without
    # swamping the shape at mini size.
    pygame.draw.polygon(surf, darker(C_HULL, 40),
                        _fpts(s, [(0.36, 0.26), (0.20, 0.06), (0.12, 0.32)]))
    draw_outlined_poly(surf, hull, C_HULL, max(2, int(s * 0.045)))
    # Bright nose panel + belly shadow give the flat hull some form.
    pygame.draw.polygon(surf, lighter(C_HULL, 55),
                        _fpts(s, [(0.99, 0.52), (0.74, 0.28), (0.68, 0.40),
                                  (0.88, 0.52)]))
    pygame.draw.polygon(surf, darker(C_HULL, 35),
                        _fpts(s, [(0.14, 0.62), (0.78, 0.62), (0.80, 0.68),
                                  (0.38, 0.78)]))
    _draw_flame(surf, s, 0.00, cy, 0.10, 0.12,
                C_DASH_ORB if dashing else C_PAD)
    cube = _frect(s, 0.28, 0.28, 0.38, 0.38)
    _draw_cube_body(surf, s, cube, col, icon_index)
    # Glass canopy arching over the pilot.
    canopy = _frect(s, 0.26, 0.14, 0.44, 0.24)
    glass = pygame.Surface(canopy.size, pygame.SRCALPHA)
    pygame.draw.ellipse(glass, (*C_GLASS, 95), glass.get_rect())
    pygame.draw.ellipse(glass, (*lighter(C_GLASS, 60), 210), glass.get_rect(),
                        max(2, int(s * 0.02)))
    surf.blit(glass, canopy.topleft)


def _draw_ball(surf, s, col, icon_index):
    c = s // 2
    r = int(s * 0.46)
    draw_bevel_circle(surf, (c, c), r, col, outline=max(2, int(s * 0.06)))
    # GD's ball is banded: a darker equator ring with a lighter hub.
    ring = darker(col, 55)
    pygame.draw.circle(surf, ring, (c, c), int(r * 0.68))
    pygame.draw.circle(surf, lighter(col, 35), (c, c), int(r * 0.68),
                       max(2, int(s * 0.025)))
    pygame.draw.circle(surf, lighter(col, 25), (c, c), int(r * 0.30))
    pygame.draw.circle(surf, outline_col(col), (c, c), int(r * 0.30),
                       max(1, int(s * 0.02)))
    draw_gloss(surf, pygame.Rect(c - r, c - r, r * 2, r * 2), alpha=90)


def _draw_wave(surf, s, col):
    # GD wave is a clean triangle, not the old diamond-with-tail shape.
    pts = _fpts(s, [(0.96, 0.50), (0.08, 0.10), (0.08, 0.90)])
    draw_outlined_poly(surf, pts, col, max(2, int(s * 0.05)))
    inner = _fpts(s, [(0.76, 0.50), (0.18, 0.20), (0.18, 0.80)])
    pygame.draw.polygon(surf, lighter(col, 55), inner)


def _draw_ufo(surf, s, col, icon_index):
    cy = int(s * 0.58)
    # Saucer hull carries the player colour (GD tints the UFO body, the
    # dome stays glassy) so colour triggers still read on this mode.
    hull = _frect(s, 0.02, 0.50, 0.96, 0.20)
    pygame.draw.ellipse(surf, col, hull)
    pygame.draw.ellipse(surf, outline_col(col), hull, max(2, int(s * 0.04)))
    pygame.draw.ellipse(surf, lighter(col, 70),
                        _frect(s, 0.10, 0.52, 0.80, 0.05))
    skirt = _frect(s, 0.24, 0.64, 0.52, 0.14)
    pygame.draw.ellipse(surf, darker(col, 55), skirt)
    pygame.draw.ellipse(surf, outline_col(col), skirt, max(2, int(s * 0.03)))
    dome = _frect(s, 0.30, 0.22, 0.40, 0.38)
    pygame.draw.ellipse(surf, C_MODE_UFO, dome)
    pygame.draw.ellipse(surf, outline_col(C_MODE_UFO), dome,
                        max(2, int(s * 0.04)))
    draw_gloss(surf, dome, alpha=130)
    for fx in (0.18, 0.50, 0.82):
        pygame.draw.circle(surf, (255, 255, 255), (int(s * fx), cy + 2),
                           max(2, int(s * 0.035)))
        pygame.draw.circle(surf, outline_col(col), (int(s * fx), cy + 2),
                           max(2, int(s * 0.035)), max(1, int(s * 0.012)))


def _draw_spider(surf, s, col):
    c = s // 2
    leg_w = max(2, int(s * 0.075))
    leg = darker(C_MODE_SPIDER, 55)
    # Jointed legs: out-and-down from the body, drawn before it so the
    # chassis covers the hips.
    for sx in (-1, 1):
        for i, (kx, ky, fx, fy) in enumerate(
                ((0.30, -0.30, 0.46, -0.06),
                 (0.34, -0.02, 0.50, 0.26),
                 (0.28, 0.24, 0.42, 0.44))):
            knee = (c + sx * s * kx, c + s * ky)
            foot = (c + sx * s * fx, c + s * fy)
            pygame.draw.line(surf, leg, (c, c), knee, leg_w)
            pygame.draw.line(surf, leg, knee, foot, leg_w)
            pygame.draw.circle(surf, darker(leg, 40), (int(foot[0]),
                                                       int(foot[1])),
                               max(1, leg_w // 2))
    body = _fpts(s, [(0.50, 0.16), (0.80, 0.34), (0.80, 0.66), (0.50, 0.84),
                     (0.20, 0.66), (0.20, 0.34)])
    draw_outlined_poly(surf, body, col, max(2, int(s * 0.05)))
    visor = _frect(s, 0.30, 0.36, 0.40, 0.16)
    pygame.draw.rect(surf, darker(C_MODE_SPIDER, 40), visor,
                     border_radius=max(1, int(s * 0.04)))
    pygame.draw.rect(surf, lighter(C_MODE_SPIDER, 70),
                     visor.inflate(-int(s * 0.05), -int(s * 0.06)),
                     border_radius=max(1, int(s * 0.03)))
    draw_gloss(surf, _frect(s, 0.28, 0.18, 0.44, 0.20), alpha=70)


def _draw_swing(surf, s, col):
    c = s // 2
    # Wings first — two swept blades either side of the core.
    for sx in (-1, 1):
        wing = [(c + sx * s * 0.10, c - s * 0.06),
                (c + sx * s * 0.50, c - s * 0.30),
                (c + sx * s * 0.46, c + s * 0.10),
                (c + sx * s * 0.12, c + s * 0.12)]
        draw_outlined_poly(surf, wing, C_MODE_SWING, max(2, int(s * 0.035)))
    core = _fpts(s, [(0.50, 0.06), (0.72, 0.50), (0.50, 0.94), (0.28, 0.50)])
    draw_outlined_poly(surf, core, col, max(2, int(s * 0.05)))
    pygame.draw.polygon(surf, lighter(col, 60),
                        _fpts(s, [(0.50, 0.22), (0.63, 0.50), (0.50, 0.78),
                                  (0.37, 0.50)]))
    pygame.draw.circle(surf, darker(col, 60), (c, c), max(2, int(s * 0.07)))


def _draw_robot(surf, s, col, icon_index, burning):
    torso = _frect(s, 0.14, 0.06, 0.72, 0.50)
    _draw_cube_body(surf, s, torso, col, icon_index)
    visor = _frect(s, 0.22, 0.14, 0.56, 0.14)
    pygame.draw.rect(surf, darker(C_MODE_ROBOT, 55), visor,
                     border_radius=max(1, int(s * 0.03)))
    pygame.draw.rect(surf, lighter(C_MODE_ROBOT, 40),
                     visor.inflate(-int(s * 0.05), -int(s * 0.05)),
                     border_radius=max(1, int(s * 0.03)))
    # Hips, thighs and feet — a jointed leg silhouette, not two bars.
    hip = _frect(s, 0.24, 0.54, 0.52, 0.10)
    draw_bevel_rect(surf, hip, darker(col, 30),
                    radius=max(1, int(s * 0.03)),
                    outline=max(2, int(s * 0.03)))
    for fx in (0.20, 0.54):
        thigh = _frect(s, fx, 0.62, 0.26, 0.22)
        draw_bevel_rect(surf, thigh, darker(col, 45),
                        radius=max(1, int(s * 0.03)),
                        outline=max(2, int(s * 0.03)))
        foot = _frect(s, fx - 0.03, 0.82, 0.32, 0.12)
        draw_bevel_rect(surf, foot, darker(C_MODE_ROBOT, 30),
                        radius=max(1, int(s * 0.03)),
                        outline=max(2, int(s * 0.03)))
    if burning:
        for fx in (0.28, 0.62):
            pygame.draw.polygon(surf, C_DASH_ORB, [
                (s * fx, s * 0.94), (s * (fx + 0.20), s * 0.94),
                (s * (fx + 0.10), s * 1.00)])
            pygame.draw.polygon(surf, C_FLAME_CORE, [
                (s * (fx + 0.04), s * 0.94), (s * (fx + 0.16), s * 0.94),
                (s * (fx + 0.10), s * 0.99)])


_MODE_BODIES = {
    MODE_SHIP: lambda surf, s, col, icon, dash, burn: _draw_ship(
        surf, s, col, icon, dash),
    MODE_BALL: lambda surf, s, col, icon, dash, burn: _draw_ball(
        surf, s, col, icon),
    MODE_WAVE: lambda surf, s, col, icon, dash, burn: _draw_wave(surf, s, col),
    MODE_UFO: lambda surf, s, col, icon, dash, burn: _draw_ufo(
        surf, s, col, icon),
    MODE_SPIDER: lambda surf, s, col, icon, dash, burn: _draw_spider(
        surf, s, col),
    MODE_SWING: lambda surf, s, col, icon, dash, burn: _draw_swing(
        surf, s, col),
    MODE_ROBOT: lambda surf, s, col, icon, dash, burn: _draw_robot(
        surf, s, col, icon, burn),
}


# ---------------------------------------------------------------------------
# Real-GD default icons.
#
# Each GD icon is two frames composited on one origin: a base shape that
# GD tints with the player's primary colour channel, and a smaller detail
# overlay tinted with the secondary channel. This engine carries a single
# player colour, so the primary is that colour and the secondary is a
# lighter shade of it — which keeps every colour trigger and palette slot
# driving the icon exactly as it drove the procedural body.
#
# ROBOT and SWING are deliberately absent, for two different reasons —
# both re-checked against the installed sheets, so neither is worth
# searching for again:
#
#   ROBOT: the art IS here, but not as an icon. `GJ_GameSheet02` carries
#     `robot_NN_01..04` as four SEPARATE rig pieces (head 28x20, thigh
#     10x13, shin 5x13, foot 14x9) whose spriteOffset is 0 on every one,
#     because GD poses them from the joint table in `Robot_AnimDesc.plist`
#     — which these sheets do not ship. Standing the robot up would mean
#     inventing a skeleton, which is exactly the faked texture this
#     mapping refuses to draw. The same is true of the spider's legs;
#     the spider entry below uses only its single-piece BODY frame.
#
#   SWING: genuinely absent. There is no `swing_*` frame on any of the
#     four sheets — they predate the 2.2 update that added the mode.
# ---------------------------------------------------------------------------
GD_ICON_SHEET = "GJ_GameSheet02"
GD_PLAYER_ICONS = {
    MODE_CUBE:   ("player_01_001.png", "player_01_2_001.png"),
    MODE_SHIP:   ("ship_01_001.png", "ship_01_2_001.png"),
    MODE_BALL:   ("player_ball_01_001.png", "player_ball_01_2_001.png"),
    # GD's internal names: the UFO is a "bird", the wave is a "dart".
    MODE_UFO:    ("bird_01_001.png", "bird_01_2_001.png"),
    MODE_WAVE:   ("dart_01_001.png", "dart_01_2_001.png"),
    MODE_SPIDER: ("spider_01_01_001.png", "spider_01_01_2_001.png"),
}
GD_ICON_PAD = 0.04              # breathing room so rotation never clips
GD_ICON_DETAIL_LIGHTEN = 90     # secondary channel, derived from primary
GD_ICON_GLYPH_FRAC = 0.44       # face box the engine's icon glyph fills


def _tint(img, col):
    """GD ships its icons as white silhouettes over a black outline, so a
    multiply colours the body and leaves the outline black."""
    img.fill((*col, 255), special_flags=pygame.BLEND_RGBA_MULT)
    return img


def _draw_gd_icon(surf, s, mode, col, icon_index):
    """Composite the real-GD icon for ``mode``, or ``False`` when it has
    no mapping / the atlas is missing and the procedural body must run."""
    frames = GD_PLAYER_ICONS.get(mode)
    if frames is None:
        return False
    base_name, detail_name = frames
    source = gd_atlas.frame_source_size(GD_ICON_SHEET, base_name)
    if source is None:
        return False
    # Both layers scale off the BASE frame's longest side so the detail
    # keeps its real proportion instead of being re-fitted on its own.
    unit = max(source)
    base = gd_atlas.compose(GD_ICON_SHEET, base_name, s, pad=GD_ICON_PAD,
                            unit=unit)
    if base is None:
        return False
    surf.blit(_tint(base, col), (0, 0))
    if mode == MODE_CUBE and icon_index:
        # GD's cube detail layer IS the classic inset square, so a player
        # who picked another icon gets that glyph in its place.
        face = int(s * GD_ICON_GLYPH_FRAC)
        draw_cube_icon_glyph(surf, (s - face) // 2, (s - face) // 2, face,
                             col, icon_index)
        return True
    detail = gd_atlas.compose(GD_ICON_SHEET, detail_name, s, pad=GD_ICON_PAD,
                              unit=unit)
    if detail is not None:
        surf.blit(_tint(detail, lighter(col, GD_ICON_DETAIL_LIGHTEN)), (0, 0))
    return True


def render_player_sprite(mode, col, icon_index, dashing=False, burning=False):
    """Full-size (PLAYER_SIZE) sprite for ``mode`` in colour ``col``."""
    key = (mode, tuple(col), icon_index, dashing, burning)
    ps = _SPRITE_CACHE.get(key)
    if ps is not None:
        return ps
    s = PLAYER_SIZE * PLAYER_SUPERSAMPLE
    big = pygame.Surface((s, s), pygame.SRCALPHA)
    if not _draw_gd_icon(big, s, mode, col, icon_index):
        body = _MODE_BODIES.get(mode)
        if body is not None:
            body(big, s, col, icon_index, dashing, burning)
        else:
            _draw_cube_body(big, s, pygame.Rect(0, 0, s, s), col, icon_index)
    ps = pygame.transform.smoothscale(big, (PLAYER_SIZE, PLAYER_SIZE))
    if len(_SPRITE_CACHE) > 256:
        _SPRITE_CACHE.clear()
    _SPRITE_CACHE[key] = ps
    return ps


def _line_surface():
    s = _LINE_SURF[0]
    if s is None or s.get_size() != (WIDTH, HEIGHT):
        s = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        _LINE_SURF[0] = s
    else:
        s.fill((0, 0, 0, 0))
    return s


def draw_trail(surf, trail, mode, size, col, cam_x, cam_y, flip=False):
    """Draw the trail as one solid ribbon in the player's colour.

    ``flip`` is accepted for call-site symmetry with the mirror body; a
    colour ribbon has no orientation, so it does not affect the drawing.
    """
    if len(trail) < 2:
        return
    thickness = _LINE_THICKNESS.get(mode, _LINE_THICKNESS_DEFAULT)
    line_surf = _line_surface()
    half = size // 2
    drew = False
    # Trail samples are recorded in GD units (player.core._sample_trails);
    # this function draws in px, so convert once per sample here.
    for i in range(len(trail) - 1):
        x1, y1 = trail[i][0] * PX_PER_UNIT, trail[i][1] * PX_PER_UNIT
        x2, y2 = trail[i + 1][0] * PX_PER_UNIT, trail[i + 1][1] * PX_PER_UNIT
        sx1 = x1 - cam_x + half
        sx2 = x2 - cam_x + half
        if (sx1 < -60 and sx2 < -60) or (sx1 > WIDTH + 60 and sx2 > WIDTH + 60):
            continue
        # GD's trail is a solid ribbon, not a fading line — full alpha.
        pygame.draw.line(line_surf, (*col, 255),
                         (int(sx1), int(y1 - cam_y + half)),
                         (int(sx2), int(y2 - cam_y + half)), thickness)
        drew = True
    if drew:
        surf.blit(line_surf, (0, 0))


class DrawMixin:
    __slots__ = ()

    def _player_color(self):
        return self.player_color

    def _draw_player_surface(self):
        """Current main-body sprite at PLAYER_SIZE (unscaled)."""
        return render_player_sprite(
            self.mode, self._player_color(), self.icon_index,
            dashing=self.dash_timer > 0,
            burning=self.mode == MODE_ROBOT and self.flight_budget > 0
            and self.vy < 0)

    def draw(self, surf, cam_x, cam_y=0, alpha=None):
        """Draw trails, the main body and the mirror. ``alpha`` (0..1)
        interpolates between the previous and current physics tick so a
        render rate above the tick rate stays smooth.

        Player position/size are real GD units internally; everything in
        this method is px (screen space), so every read goes through the
        ``*_px`` conversion properties (see docs/development/UNITS_REFACTOR.md).
        """
        col = self._player_color()
        size = round(self.size_px)
        # The drawn icon is NOT the hitbox: GD authors every icon at its own
        # art size (see constants.ICON_SIZE_UNITS) and centres it on the
        # body.  Wave is the visible case — a 26-unit dart over a 10-unit
        # box — so `size` still places the sprite while `icon` scales it.
        icon = round(icon_size_units(self.mode, self.size) * PX_PER_UNIT)
        draw_trail(surf, self.trail, self.mode, size, col, cam_x, cam_y)
        x, y, angle = self.render_pose_px(alpha)
        sx = x - cam_x
        sy = y - cam_y
        ps = self._draw_player_surface()
        if icon != PLAYER_SIZE:
            ps = pygame.transform.smoothscale(ps, (icon, icon))
        if self.grav == -1:
            ps = pygame.transform.flip(ps, False, True)
        rot = pygame.transform.rotate(ps, angle) if angle else ps
        surf.blit(rot, rot.get_rect(center=(sx + size // 2, sy + size // 2)))
        m = self.mirror
        if m is None:
            return
        msize = round(m.size_px)
        micon = round(icon_size_units(m.mode, m.size) * PX_PER_UNIT)
        draw_trail(surf, m.trail, m.mode, msize, col, cam_x, cam_y, flip=True)
        if alpha is None or alpha >= 1.0:
            my, mangle = m.y_px, m.angle
        else:
            a = max(0.0, alpha)
            my = (m.prev_y + (m.y - m.prev_y) * a) * PX_PER_UNIT
            mangle = m.prev_angle + (m.angle - m.prev_angle) * a
        msurf = render_player_sprite(
            m.mode, col, self.icon_index,
            burning=m.mode == MODE_ROBOT and m.flight_budget > 0 and m.vy < 0)
        if micon != PLAYER_SIZE:
            msurf = pygame.transform.smoothscale(msurf, (micon, micon))
        if m.grav == -1:
            msurf = pygame.transform.flip(msurf, False, True)
        if not m.alive:
            # ``msurf`` may still be the shared _SPRITE_CACHE surface
            # (when no scale/flip copied it) — never mutate that in place.
            msurf = msurf.copy()
            msurf.set_alpha(90)
        mrot = pygame.transform.rotate(msurf, mangle) if mangle else msurf
        surf.blit(mrot, mrot.get_rect(
            center=(sx + msize // 2, my - cam_y + msize // 2)))
