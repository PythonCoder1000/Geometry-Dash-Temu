"""Canvas rendering for the editor: background, grid, objects, overlays."""

import math

import pygame

from ..constants import (
    WIDTH, HEIGHT, C_GRID, C_WHITE,
    T_BLOCK, T_SLAB, T_SLOPE, T_SPIKE, T_HALF_SPIKE, T_SAW, T_END,
    T_MOVE_TRIGGER, T_CAMERA_TRIGGER, T_MODE_DUAL, T_ROTATE_TRIGGER,
    T_FOLLOW_TRIGGER, SOLID_HITBOX_FRACTION, T_TELEPORT_ORB,
)
from ..graphics import draw_bg, draw_obj, draw_end_wall
from ..geometry import (
    obj_scale, spike_hitboxes, saw_hitbox, cell_rect, slab_rect, slope_polygon,
)
from ..levels import get_group_id
from ..objects import active_start
from ..jump_predictor import find_probe, predict, draw_overlay
from .state import TOP_H, BAR_Y, MODE_BUILD, MODE_DELETE, TOOL_LINK, TOOL_BOT_PATH
from . import ops

CANVAS_RECT = pygame.Rect(0, TOP_H, WIDTH, BAR_Y - TOP_H)

_grid_cache = {"cell": 0, "surf": None}
_scratch = [None]


def _grid_surface(eff):
    if _grid_cache["cell"] != eff or _grid_cache["surf"] is None:
        w = WIDTH + eff
        h = (BAR_Y - TOP_H) + eff
        surf = pygame.Surface((w, h), pygame.SRCALPHA)
        for x in range(0, w, eff):
            pygame.draw.line(surf, C_GRID, (x, 0), (x, h), 1)
        for y in range(0, h, eff):
            pygame.draw.line(surf, C_GRID, (0, y), (w, y), 1)
        _grid_cache["cell"] = eff
        _grid_cache["surf"] = surf
    return _grid_cache["surf"]


def _overlay():
    if _scratch[0] is None:
        _scratch[0] = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    s = _scratch[0]
    s.fill((0, 0, 0, 0))
    return s


def visible_cell_range(st, margin=2):
    e = st.eff_cell
    left = int(st.cam_x // e) - margin
    right = left + WIDTH // e + 2 * margin + 1
    top = int(st.cam_y // e) - margin
    bot = top + HEIGHT // e + 2 * margin + 1
    return left, right, top, bot


def _in_view(o, left, right, top, bot):
    """Culling that respects scaled objects (a 4x block reaches far
    outside its own cell)."""
    sx, sy = obj_scale(o)
    ex = max(0, int(math.ceil(sx)))
    ey = max(0, int(math.ceil(sy)))
    return (left - ex <= o["x"] <= right + ex) and (top - ey <= o["y"] <= bot + ey)


def render_canvas(screen, st, stars, mountains):
    e = st.eff_cell
    prev_clip = screen.get_clip()
    screen.set_clip(CANVAS_RECT)
    draw_bg(screen, st.cam_x / st.zoom, stars, mountains,
            cam_y=st.cam_y / st.zoom - TOP_H / st.zoom)
    if st.show_grid:
        ox = int(-st.cam_x % e) - e
        oy = int(-st.cam_y % e) - e
        screen.blit(_grid_surface(e), (ox, TOP_H + oy))
    left, right, top, bot = visible_cell_range(st)
    pulse = st.pulse
    # Several Start Pos objects may sit in a level; only one spawns the
    # player, so it gets a ring the inactive ones do not have.
    live_start = active_start(st.objects)
    for o in st.objects:
        if not _in_view(o, left, right, top, bot):
            continue
        sx = o["x"] * e - st.cam_x
        sy = o["y"] * e - st.cam_y
        if o["t"] == T_END:
            draw_end_wall(screen, sx, sy, e, pulse)
            continue
        if st.show_hitboxes:
            continue
        draw_obj(screen, o["t"], sx, sy, e, pulse, o.get("r", 0), o,
                 scale=obj_scale(o))
        if o.get("invisible"):
            dim = pygame.Surface((e, e), pygame.SRCALPHA)
            dim.fill((0, 0, 0, 140))
            screen.blit(dim, (sx, sy))
            pygame.draw.rect(screen, (200, 200, 255), (sx, sy, e, e), 1)
        if o is live_start:
            pygame.draw.rect(screen, (120, 255, 140),
                             (sx - 2, sy - 2, e + 4, e + 4), 2,
                             border_radius=4)
        if o.get("_bot_only"):
            bx, by = int(sx), int(sy)
            pygame.draw.line(screen, (180, 100, 230), (bx + 6, by + 6), (bx + e - 6, by + e - 6), 2)
            pygame.draw.line(screen, (180, 100, 230), (bx + e - 6, by + 6), (bx + 6, by + e - 6), 2)
    _render_trigger_links(screen, st)
    screen.set_clip(prev_clip)


def _center(st, gx, gy):
    e = st.eff_cell
    return gx * e - st.cam_x + e // 2, gy * e - st.cam_y + e // 2


def _render_trigger_links(screen, st):
    by_oid = {o["oid"]: o for o in st.objects if o.get("oid")}
    for o in st.objects:
        t = o["t"]
        if t not in (T_MOVE_TRIGGER, T_ROTATE_TRIGGER, T_FOLLOW_TRIGGER):
            continue
        sx, sy = _center(st, o["x"], o["y"])
        if t == T_FOLLOW_TRIGGER:
            src = by_oid.get(o.get("source_oid"))
            tgt = by_oid.get(o.get("target_oid"))
            if src:
                pygame.draw.line(screen, (120, 220, 200), (sx, sy), _center(st, src["x"], src["y"]), 1)
            if tgt and not o.get("follow_player"):
                pygame.draw.line(screen, (120, 220, 200), (sx, sy), _center(st, tgt["x"], tgt["y"]), 1)
            continue
        oids = o.get("target_oids") or ([o["target_oid"]] if o.get("target_oid") else [])
        col = (200, 150, 255) if t == T_MOVE_TRIGGER else (255, 170, 200)
        first = None
        for oid in oids:
            tgt = by_oid.get(oid)
            if tgt is None:
                continue
            first = first or tgt
            pygame.draw.line(screen, col, (sx, sy), _center(st, tgt["x"], tgt["y"]), 1)
        if t == T_MOVE_TRIGGER and first is not None:
            ex, ey = _center(st, o.get("tx", first["x"]), o.get("ty", first["y"]))
            tx, ty = _center(st, first["x"], first["y"])
            pygame.draw.line(screen, (255, 200, 100), (tx, ty), (ex, ey), 1)
            pygame.draw.circle(screen, (255, 200, 100), (int(ex), int(ey)), 6, 1)


def render_jump_predictor(screen, st):
    probe = find_probe(st.objects)
    if probe is None:
        return
    result = predict(st.objects, probe)
    draw_overlay(screen, result, st.cam_x, st.cam_y, st.zoom, clip_rect=CANVAS_RECT,
                 show_hitbox=bool(probe.get("show_hitbox")))
    if result is None:
        return
    from ..graphics import txt
    e = st.eff_cell
    sx = int(probe["x"] * e - st.cam_x + e / 2)
    sy = int(probe["y"] * e - st.cam_y - 6)
    if result["hit"]:
        label, col = f"{result['mode']} · f{result['hit'][3]} HIT: {result['hit'][2]}", (255, 120, 120)
    elif result["landing"]:
        label, col = f"{result['mode']} · f{result['landing'][2]} LAND", (140, 255, 170)
    else:
        label, col = f"{result['mode']} · open", (255, 210, 120)
    if TOP_H < sy < BAR_Y:
        txt(screen, label, sx, sy, 12, col, True, shadow=True)


def render_hitbox_overlay(screen, st):
    """Player hitbox trace of the last run + level kill / land rects."""
    layer = _overlay()
    z = st.zoom
    cx0, cy0 = st.cam_x, st.cam_y
    wl = cx0 / z - 60
    wr = (cx0 + WIDTH) / z + 60
    wt = cy0 / z - 60
    wb = (cy0 + HEIGHT) / z + 60

    def draw_obb(hx, hy, hsz, hangle, outer_col, inner_col):
        cx = hx + hsz / 2.0
        cy = hy + hsz / 2.0
        rad = -math.radians(hangle)
        cs, sn = math.cos(rad), math.sin(rad)
        half = hsz / 2.0
        pts = [(int((cx + ox * cs - oy * sn) * z - cx0), int((cy + ox * sn + oy * cs) * z - cy0))
               for ox, oy in ((-half, -half), (half, -half), (half, half), (-half, half))]
        pygame.draw.polygon(layer, outer_col, pts, 1)
        ih = half * SOLID_HITBOX_FRACTION
        pygame.draw.rect(layer, inner_col, (int((cx - ih) * z - cx0), int((cy - ih) * z - cy0),
                                            max(1, int(ih * 2 * z)), max(1, int(ih * 2 * z))), 1)

    for trace, outer in ((st.last_run_hitboxes, (120, 255, 140, 70)),
                         (st.last_run_mirror_hitboxes, (120, 220, 255, 70))):
        for sample in trace:
            hx, hy, hsz = sample[0], sample[1], sample[2]
            if hx + hsz < wl or hx > wr or hy + hsz < wt or hy > wb:
                continue
            draw_obb(hx, hy, hsz, sample[3] if len(sample) > 3 else 0.0, outer, (90, 160, 255, 90))
    left, right, top, bot = visible_cell_range(st)
    for o in st.objects:
        t = o["t"]
        if t not in (T_SPIKE, T_HALF_SPIKE, T_SAW, T_BLOCK, T_SLAB, T_SLOPE):
            continue
        if not _in_view(o, left, right, top, bot):
            continue
        gx, gy = o["x"], o["y"]
        sc = obj_scale(o)
        if t == T_SLOPE:
            pts = [(int(px * z - cx0), int(py * z - cy0)) for px, py in slope_polygon(gx, gy, o.get("r", 0), sc)]
            pygame.draw.polygon(layer, (120, 180, 255, 50), pts)
            pygame.draw.polygon(layer, (100, 160, 240, 220), pts, 1)
            continue
        if t == T_SAW:
            rects, fill, outline = [saw_hitbox(gx, gy, sc)], (255, 80, 80, 60), (255, 60, 60, 220)
        elif t in (T_SPIKE, T_HALF_SPIKE):
            rects = spike_hitboxes(gx, gy, o.get("r", 0), half=(t == T_HALF_SPIKE), scale=sc)
            fill, outline = (255, 80, 80, 60), (255, 60, 60, 220)
        elif t == T_BLOCK:
            rects, fill, outline = [cell_rect(gx, gy, sc)], (120, 180, 255, 50), (100, 160, 240, 220)
        else:
            rects, fill, outline = [slab_rect(gx, gy, o.get("r", 0), sc)], (120, 180, 255, 50), (100, 160, 240, 220)
        for rr in rects:
            r = (int(rr.x * z - cx0), int(rr.y * z - cy0), max(1, int(rr.w * z)), max(1, int(rr.h * z)))
            pygame.draw.rect(layer, fill, r)
            pygame.draw.rect(layer, outline, r, 1)
    screen.blit(layer, (0, 0))


def render_bot_paths(screen, st):
    for pts_src, col, end_col, rad in ((st.bot_waypoints, (255, 180, 60), (255, 220, 100), 5),
                                       (st.bot_mirror_waypoints, (90, 170, 255), (90, 170, 255), 4)):
        if not pts_src:
            continue
        pts = [(int(wx * st.zoom - st.cam_x), int(wy * st.zoom - st.cam_y)) for wx, wy in pts_src]
        if len(pts) >= 2:
            pygame.draw.lines(screen, col, False, pts, 2)
        for i, pt in enumerate(pts):
            pygame.draw.circle(screen, end_col if i in (0, len(pts) - 1) else col, pt, rad)
            pygame.draw.circle(screen, (0, 0, 0), pt, rad, 1)


def render_pending_link(screen, st, mpos, in_canvas):
    pl = st.pending_link
    kind = pl.get("kind")
    if kind == "teleport":
        src, col = pl["first"], (255, 220, 90)
    elif kind == "targets":
        src, col = pl["trigger"], (255, 180, 100)
        for tgt in pl.get("targets", ()):
            pygame.draw.circle(screen, (200, 255, 150), [int(v) for v in _center(st, tgt["x"], tgt["y"])], 22, 2)
    else:
        src, col = pl["trigger"], (120, 220, 200)
        if pl.get("source") is not None:
            pygame.draw.circle(screen, (200, 255, 150), [int(v) for v in _center(st, pl["source"]["x"], pl["source"]["y"])], 22, 2)
    c = _center(st, src["x"], src["y"])
    pygame.draw.circle(screen, col, (int(c[0]), int(c[1])), 26, 2)
    if in_canvas:
        pygame.draw.line(screen, col, c, mpos, 1)


def render_selection(screen, st):
    e = st.eff_cell
    single = st.selected[0] if len(st.selected) == 1 else None
    for o in st.selected:
        sx, sy = obj_scale(o)
        w = max(1, int(e * sx))
        h = max(1, int(e * sy))
        cx, cy = _center(st, o["x"], o["y"])
        pygame.draw.rect(screen, (120, 255, 140), (cx - w // 2, cy - h // 2, w, h), 2)
        if o.get("oid"):
            from ..graphics import txt
            txt(screen, f"#{o['oid']}", cx - w // 2 + 2, cy - h // 2 - 12, 10, (200, 255, 200))
        if o["t"] == T_TELEPORT_ORB and get_group_id(o):
            from ..graphics import txt
            txt(screen, f"g{get_group_id(o)}", cx + w // 2 - 16, cy - h // 2 - 12, 10, (255, 230, 150))
    if single is None:
        if len(st.selected) > 1:
            x0, y0, x1, y1 = ops.selection_bounds(st.selected)
            sx0, sy0 = st.cell_to_screen(x0, y0)
            sx1, sy1 = st.cell_to_screen(x1 + 1, y1 + 1)
            pygame.draw.rect(screen, (120, 255, 140, 90), (sx0 - 3, sy0 - 3, sx1 - sx0 + 6, sy1 - sy0 + 6), 1)
        return
    if single["t"] == T_CAMERA_TRIGGER:
        cx, cy = _center(st, single["x"], single["y"])
        ty = single.get("cy", single["y"]) * e - st.cam_y + e // 2
        pygame.draw.line(screen, (255, 225, 80), (cx, cy), (cx, ty), 2)
        pygame.draw.line(screen, (255, 225, 80), (0, ty), (WIDTH, ty), 1)
    elif single["t"] == T_MODE_DUAL:
        cx, cy = _center(st, single["x"], single["y"])
        row = single.get("spawn_y", single["y"])
        gy = row * e - st.cam_y
        ghost = pygame.Rect(cx - e // 2, gy, e, e)
        layer = pygame.Surface((e, e), pygame.SRCALPHA)
        layer.fill((120, 220, 255, 90))
        screen.blit(layer, ghost.topleft)
        pygame.draw.rect(screen, (140, 230, 255), ghost, 2)
        pygame.draw.line(screen, (140, 230, 255), (cx, cy), (cx, gy + e // 2), 2)


def render_marquee(screen, start, mpos):
    x0, y0 = start
    x1, y1 = mpos
    rr = pygame.Rect(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
    if rr.w > 0 and rr.h > 0:
        fill = pygame.Surface(rr.size, pygame.SRCALPHA)
        fill.fill((120, 255, 140, 40))
        screen.blit(fill, rr.topleft)
        pygame.draw.rect(screen, (120, 255, 140), rr, 1)


def render_cursor(screen, st, mpos):
    """Ghost preview under the cursor for the active mode / tool."""
    e = st.eff_cell
    gx, gy = st.screen_to_cell(*mpos)
    sx, sy = st.cell_to_screen(gx, gy)
    if st.snippet_stamp is not None:
        _render_stamp_preview(screen, st, gx, gy)
        return
    if st.mode == MODE_BUILD:
        ghost = pygame.Surface((e, e), pygame.SRCALPHA)
        ghost.set_alpha(130)
        draw_obj(ghost, st.selected_type, 0, 0, e, st.pulse, st.rotation)
        screen.blit(ghost, (sx, sy))
        pygame.draw.rect(screen, C_WHITE, (sx, sy, e, e), 1)
    elif st.mode == MODE_DELETE:
        red = (255, 80, 80)
        pygame.draw.rect(screen, red, (sx, sy, e, e), 2)
        pygame.draw.line(screen, red, (sx + 8, sy + 8), (sx + e - 8, sy + e - 8), 2)
        pygame.draw.line(screen, red, (sx + e - 8, sy + 8), (sx + 8, sy + e - 8), 2)
    elif st.edit_tool == TOOL_LINK:
        pygame.draw.rect(screen, (200, 160, 255), (sx, sy, e, e), 2)
    elif st.edit_tool == TOOL_BOT_PATH:
        amber = (255, 180, 60)
        pygame.draw.circle(screen, amber, mpos, 6, 2)
        if st.bot_waypoints:
            lx = int(st.bot_waypoints[-1][0] * st.zoom - st.cam_x)
            ly = int(st.bot_waypoints[-1][1] * st.zoom - st.cam_y)
            pygame.draw.line(screen, amber, (lx, ly), mpos, 1)
    else:
        pygame.draw.rect(screen, (120, 255, 140), (sx, sy, e, e), 1)


def _render_stamp_preview(screen, st, gx, gy):
    e = st.eff_cell
    stamp = st.snippet_stamp
    xs = [o["x"] for o in stamp]
    ys = [o["y"] for o in stamp]
    min_x, min_y = min(xs), min(ys)
    for so in stamp:
        cx = (gx + so["x"] - min_x) * e - st.cam_x
        cy = (gy + so["y"] - min_y) * e - st.cam_y
        ghost = pygame.Surface((e, e), pygame.SRCALPHA)
        ghost.set_alpha(140)
        draw_obj(ghost, so["t"], 0, 0, e, st.pulse, so.get("r", 0), scale=obj_scale(so))
        screen.blit(ghost, (cx, cy))
    sx, sy = st.cell_to_screen(gx, gy)
    pygame.draw.rect(screen, (160, 220, 255),
                     (sx, sy, (max(xs) - min_x + 1) * e, (max(ys) - min_y + 1) * e), 1)
