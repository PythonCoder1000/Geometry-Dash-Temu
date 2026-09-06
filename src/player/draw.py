"""Player rendering: per-mode sprite, ghost / line trails, mirror body.

Sprites and ghost-trail stamps are cached per (mode, size, colour, ...)
so a frame never allocates a fresh Surface for a trail sample; the old
renderer allocated one per ghost per frame (plus a full-screen surface
per line trail) which was a large part of the frame budget.
"""

import pygame

from ..constants import (
    WIDTH, HEIGHT, PLAYER_SIZE,
    MODE_SHIP, MODE_BALL, MODE_WAVE, MODE_UFO, MODE_SPIDER, MODE_SWING,
    MODE_ROBOT,
    C_DASH_ORB, C_PAD, C_MODE_WAVE, C_MODE_UFO, C_MODE_SPIDER,
    C_MODE_SWING, C_MODE_ROBOT,
)
from ..graphics import lighter, darker, draw_cube_icon_glyph

_LINE_TRAIL_MODES = frozenset({MODE_WAVE, MODE_SHIP, MODE_SPIDER, MODE_SWING})
_LINE_THICKNESS = {MODE_SHIP: 5, MODE_SPIDER: 4}

# Module-level caches (shared by every Player instance).
_SPRITE_CACHE = {}
_GHOST_CACHE = {}
_LINE_SURF = [None]


def render_player_sprite(mode, col, icon_index, dashing=False, burning=False):
    """Full-size (PLAYER_SIZE) sprite for ``mode`` in colour ``col``."""
    key = (mode, tuple(col), icon_index, dashing, burning)
    ps = _SPRITE_CACHE.get(key)
    if ps is not None:
        return ps
    ps = pygame.Surface((PLAYER_SIZE, PLAYER_SIZE), pygame.SRCALPHA)
    cx = PLAYER_SIZE // 2
    cy = PLAYER_SIZE // 2
    if mode == MODE_SHIP:
        hull = (70, 76, 94)
        hull_hi = lighter(hull, 40)
        hull_lo = darker(hull, 30)
        nose = PLAYER_SIZE - 4
        tail = 7
        top = 9
        bot = PLAYER_SIZE - 9
        hull_pts = [(nose, cy), (nose - 10, top), (tail + 2, top + 1),
                    (tail - 1, cy), (tail + 2, bot - 1), (nose - 10, bot)]
        pygame.draw.polygon(ps, darker(hull_lo, 30),
                            [(p[0], p[1] + 2) for p in hull_pts])
        pygame.draw.polygon(ps, hull, hull_pts)
        pygame.draw.polygon(ps, hull_hi, hull_pts, 2)
        canopy = pygame.Rect(cx - 2, cy - 10, 16, 8)
        pygame.draw.ellipse(ps, darker((120, 210, 255), 40), canopy)
        pygame.draw.ellipse(ps, (120, 210, 255), canopy.inflate(-2, -2))
        cube = max(12, PLAYER_SIZE // 2 - 2)
        cx0 = cx - cube // 2 - 1
        cy0 = cy - cube // 2 + 1
        pygame.draw.rect(ps, darker(col, 30), (cx0, cy0 + 2, cube, cube),
                         border_radius=3)
        pygame.draw.rect(ps, col, (cx0, cy0, cube, cube), border_radius=3)
        pygame.draw.rect(ps, lighter(col, 60),
                         (cx0 + 1, cy0 + 1, cube - 2, cube - 2), 1,
                         border_radius=2)
        draw_cube_icon_glyph(ps, cx0, cy0, cube, col, icon_index)
        flame_col = C_DASH_ORB if dashing else C_PAD
        flame_tip = tail - 5 if dashing else tail - 3
        pygame.draw.polygon(ps, flame_col, [(flame_tip, cy), (tail + 3, cy - 5),
                                            (tail + 3, cy + 5)])
        pygame.draw.polygon(ps, lighter(flame_col, 60),
                            [(flame_tip + 2, cy), (tail + 3, cy - 3),
                             (tail + 3, cy + 3)])
    elif mode == MODE_BALL:
        pygame.draw.circle(ps, darker(col, 30), (cx, cy + 2), cx - 2)
        pygame.draw.circle(ps, col, (cx, cy), cx - 2)
        pygame.draw.circle(ps, lighter(col, 60), (cx, cy), cx - 8, 2)
        pygame.draw.circle(ps, darker(col, 40), (cx, cy), 6)
    elif mode == MODE_WAVE:
        pts = [(PLAYER_SIZE - 3, cx), (3, 4), (3, PLAYER_SIZE - 4)]
        pygame.draw.polygon(ps, darker(C_MODE_WAVE, 40),
                            [(p[0], p[1] + 2) for p in pts])
        pygame.draw.polygon(ps, col, pts)
        pygame.draw.polygon(ps, lighter(col, 60), pts, 2)
    elif mode == MODE_UFO:
        body_rect = pygame.Rect(3, cy - 2, PLAYER_SIZE - 6, 10)
        pygame.draw.ellipse(ps, darker(C_MODE_UFO, 40), body_rect.move(0, 2))
        pygame.draw.ellipse(ps, C_MODE_UFO, body_rect)
        pygame.draw.ellipse(ps, lighter(C_MODE_UFO, 60),
                            body_rect.inflate(-6, -4), 2)
        dome = pygame.Rect(cx - 10, cy - 12, 20, 16)
        pygame.draw.ellipse(ps, darker(col, 30), dome.move(0, 2))
        pygame.draw.ellipse(ps, col, dome)
        pygame.draw.ellipse(ps, lighter(col, 70), dome.inflate(-6, -6), 2)
        for ox in (-12, 0, 12):
            pygame.draw.circle(ps, (255, 255, 255), (cx + ox, cy + 8), 2)
    elif mode == MODE_SPIDER:
        pygame.draw.circle(ps, darker(C_MODE_SPIDER, 30), (cx, cy + 1), cx - 6)
        pygame.draw.circle(ps, C_MODE_SPIDER, (cx, cy), cx - 6)
        pygame.draw.circle(ps, col, (cx, cy), cx - 12)
        for ox in (-2, 2):
            for oy in (-1, 1):
                pygame.draw.line(ps, darker(C_MODE_SPIDER, 40), (cx, cy),
                                 (cx + ox * cx, cy + oy * cy), 3)
    elif mode == MODE_ROBOT:
        torso = pygame.Rect(3, 4, PLAYER_SIZE - 6, PLAYER_SIZE - 14)
        pygame.draw.rect(ps, darker(col, 30), torso.move(0, 2), border_radius=3)
        pygame.draw.rect(ps, col, torso, border_radius=3)
        pygame.draw.rect(ps, lighter(col, 60), torso.inflate(-6, -6), 2,
                         border_radius=3)
        visor = pygame.Rect(8, 8, PLAYER_SIZE - 16, 6)
        pygame.draw.rect(ps, darker(C_MODE_ROBOT, 40), visor, border_radius=2)
        pygame.draw.rect(ps, lighter(C_MODE_ROBOT, 30), visor.inflate(-4, -2),
                         border_radius=2)
        leg_y = PLAYER_SIZE - 10
        for ox in (6, PLAYER_SIZE - 12):
            pygame.draw.rect(ps, darker(col, 40), (ox, leg_y, 6, 8),
                             border_radius=1)
        glow_col = C_DASH_ORB if burning else darker(C_MODE_ROBOT, 20)
        pygame.draw.polygon(ps, glow_col, [(cx - 6, PLAYER_SIZE - 3),
                                           (cx + 6, PLAYER_SIZE - 3),
                                           (cx, PLAYER_SIZE - 1)])
    elif mode == MODE_SWING:
        outer = [(PLAYER_SIZE - 4, cy), (cx, 3), (3, cy), (cx, PLAYER_SIZE - 4)]
        pygame.draw.polygon(ps, darker(C_MODE_SWING, 40),
                            [(p[0], p[1] + 2) for p in outer])
        pygame.draw.polygon(ps, C_MODE_SWING, outer)
        pygame.draw.polygon(ps, lighter(C_MODE_SWING, 60), outer, 2)
        inner = [(PLAYER_SIZE - 12, cy), (cx, 11), (11, cy),
                 (cx, PLAYER_SIZE - 12)]
        pygame.draw.polygon(ps, col, inner)
        pygame.draw.polygon(ps, darker(col, 40), inner, 1)
    else:
        pygame.draw.rect(ps, darker(col, 30),
                         (1, 3, PLAYER_SIZE - 2, PLAYER_SIZE - 2), border_radius=3)
        pygame.draw.rect(ps, col, (0, 0, PLAYER_SIZE, PLAYER_SIZE),
                         border_radius=3)
        pygame.draw.rect(ps, lighter(col, 60),
                         (3, 3, PLAYER_SIZE - 6, PLAYER_SIZE - 6), 2,
                         border_radius=3)
        draw_cube_icon_glyph(ps, 0, 0, PLAYER_SIZE, col, icon_index)
    if len(_SPRITE_CACHE) > 256:
        _SPRITE_CACHE.clear()
    _SPRITE_CACHE[key] = ps
    return ps


def _ghost_stamp(mode, size, col, alpha, flip):
    """Cached translucent silhouette used for ghost-trail samples."""
    a = max(0, min(255, alpha))
    key = (mode, size, tuple(col), a // 8, flip)
    ts = _GHOST_CACHE.get(key)
    if ts is not None:
        return ts
    al_sm = int(a * 0.35)
    al_fill = int(a * 0.4)
    ts = pygame.Surface((PLAYER_SIZE, PLAYER_SIZE), pygame.SRCALPHA)
    c = PLAYER_SIZE // 2
    if mode == MODE_BALL:
        pygame.draw.circle(ts, (*col, al_sm), (c, c), c - 2)
    elif mode == MODE_UFO:
        pygame.draw.ellipse(ts, (*col, al_sm), (4, c - 2, PLAYER_SIZE - 8, 10))
    elif mode == MODE_SPIDER:
        pygame.draw.circle(ts, (*col, al_sm), (c, c), c - 4)
    else:
        ts.fill((*col, al_fill))
    if size != PLAYER_SIZE:
        ts = pygame.transform.smoothscale(ts, (size, size))
    if flip:
        ts = pygame.transform.flip(ts, False, True)
    if len(_GHOST_CACHE) > 512:
        _GHOST_CACHE.clear()
    _GHOST_CACHE[key] = ts
    return ts


def _line_surface():
    s = _LINE_SURF[0]
    if s is None or s.get_size() != (WIDTH, HEIGHT):
        s = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        _LINE_SURF[0] = s
    else:
        s.fill((0, 0, 0, 0))
    return s


def draw_trail(surf, trail, mode, size, col, cam_x, cam_y, flip=False):
    if not trail:
        return
    if mode in _LINE_TRAIL_MODES:
        if len(trail) < 2:
            return
        thickness = _LINE_THICKNESS.get(mode, 3)
        line_surf = _line_surface()
        half = size // 2
        drew = False
        for i in range(len(trail) - 1):
            x1, y1, _, al1 = trail[i]
            x2, y2, _, al2 = trail[i + 1]
            sx1 = x1 - cam_x + half
            sx2 = x2 - cam_x + half
            if (sx1 < -60 and sx2 < -60) or (sx1 > WIDTH + 60 and sx2 > WIDTH + 60):
                continue
            avg_al = max(0, min(255, int((al1 + al2) * 0.5 * 0.7)))
            pygame.draw.line(line_surf, (*col, avg_al),
                             (int(sx1), int(y1 - cam_y + half)),
                             (int(sx2), int(y2 - cam_y + half)), thickness)
            drew = True
        if drew:
            surf.blit(line_surf, (0, 0))
        return
    for tx, ty, ta, al in trail:
        sx = tx - cam_x
        if sx < -60 or sx > WIDTH + 60:
            continue
        stamp = _ghost_stamp(mode, size, col, int(al), flip)
        rot = pygame.transform.rotate(stamp, ta) if ta else stamp
        rr = rot.get_rect(center=(sx + size // 2, ty - cam_y + size // 2))
        surf.blit(rot, rr)


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
        render rate above the tick rate stays smooth."""
        col = self._player_color()
        size = self.size
        draw_trail(surf, self.trail, self.mode, size, col, cam_x, cam_y)
        x, y, angle = self.render_pose(alpha)
        sx = x - cam_x
        sy = y - cam_y
        ps = self._draw_player_surface()
        if size != PLAYER_SIZE:
            ps = pygame.transform.smoothscale(ps, (size, size))
        rot = pygame.transform.rotate(ps, angle) if angle else ps
        surf.blit(rot, rot.get_rect(center=(sx + size // 2, sy + size // 2)))
        m = self.mirror
        if m is None:
            return
        msize = int(m.size)
        draw_trail(surf, m.trail, m.mode, msize, col, cam_x, cam_y, flip=True)
        if alpha is None or alpha >= 1.0:
            my, mangle = m.y, m.angle
        else:
            a = max(0.0, alpha)
            my = m.prev_y + (m.y - m.prev_y) * a
            mangle = m.prev_angle + (m.angle - m.prev_angle) * a
        msurf = render_player_sprite(
            m.mode, col, self.icon_index,
            burning=m.mode == MODE_ROBOT and m.flight_budget > 0 and m.vy < 0)
        if msize != PLAYER_SIZE:
            msurf = pygame.transform.smoothscale(msurf, (msize, msize))
        msurf = pygame.transform.flip(msurf, False, True)
        if not m.alive:
            msurf.set_alpha(90)
        mrot = pygame.transform.rotate(msurf, mangle) if mangle else msurf
        surf.blit(mrot, mrot.get_rect(
            center=(sx + msize // 2, my - cam_y + msize // 2)))
