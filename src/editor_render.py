"""Rendering for the level editor's per-frame draw pass.

``_run_editor_impl`` used to inline ~520 lines of drawing between its event
handling and ``display.flip()``. Everything that only paints pixels lives here
instead, as standalone functions with explicit parameters (no shared state
object) — the same shape as :mod:`play_render` does for ``run_play``.

Tool cursor ghosts are *not* implemented here: they are the ``on_preview``
callbacks of :data:`editor_tools.TOOL_HANDLERS`, so a tool's cursor is defined
in the same place as its click and drag behaviour.
"""

import math

import pygame

from .constants import (
    WIDTH, HEIGHT, CELL,
    C_GRID, C_WHITE, C_GRAY, C_PLAYER, C_BTN, C_DANGER, C_PUBLISH,
    TYPE_NAMES, TYPE_TIPS,
    T_BLOCK, T_SLAB, T_SLOPE, T_SPIKE, T_HALF_SPIKE, T_SAW,
    T_TELEPORT_ORB, T_CAMERA_TRIGGER, T_BG_TRIGGER, T_MOVE_TRIGGER,
    T_COLOR_TRIGGER, T_SPIDER_ORB, T_END, T_MODE_DUAL,
    SOLID_HITBOX_FRACTION,
)
from .graphics import (
    draw_bg, draw_obj, txt, btn,
    speaker_icon, icon_button, draw_end_wall,
    spike_hitboxes, saw_hitbox, cell_rect, slab_rect, slope_polygon,
    obj_scale,
)
from .jump_predictor import find_probe, predict, draw_overlay
from . import music
from . import sfx
from . import editor_tools
from .editor import (
    TOP_H, BAR_Y,
    TOOL_BRUSH, TOOL_ERASE, TOOL_GROUP, TOOL_EDIT, TOOL_BOT_PATH,
    _get_grid_surface as get_grid_surface,
)

# Reused full-screen alpha layer for the hitbox trace overlay — reallocating a
# 1200x700 SRCALPHA surface every frame was the overlay's whole cost.
HITBOX_SCRATCH = [None]


def render_canvas(screen, objects, cam_x, cam_y, zoom_level, pulse,
                  stars, mountains, show_grid, show_hitboxes):
    """Background, grid, object sprites and move-trigger link lines."""
    draw_bg(screen, cam_x, stars, mountains)
    if show_grid:
        effective_cell = int(CELL * zoom_level)
        grid_surf = get_grid_surface(effective_cell)
        # Offset-and-clip blit: the grid surface is slightly larger than
        # the viewport so any sub-cell scroll offset still covers the
        # visible region. set_clip confines output to the grid band.
        ox = int(-cam_x % effective_cell) - effective_cell
        oy = int(-cam_y % effective_cell) - effective_cell
        prev_clip = screen.get_clip()
        screen.set_clip(pygame.Rect(0, TOP_H, WIDTH, BAR_Y - TOP_H))
        screen.blit(grid_surf, (ox, TOP_H + oy))
        screen.set_clip(prev_clip)
    effective_cell = int(CELL * zoom_level)
    left_gx = int(cam_x // effective_cell) - 1
    right_gx = left_gx + WIDTH // effective_cell + 3
    top_gy = int(cam_y // effective_cell) - 1
    bot_gy = top_gy + HEIGHT // effective_cell + 3
    # Hitbox-only view: skip sprite blits entirely so the canvas is a
    # clean schematic of collision rects. Start/End still render so the
    # author knows where the level begins/ends.
    if not show_hitboxes:
        for o in objects:
            if left_gx <= o["x"] <= right_gx and top_gy <= o["y"] <= bot_gy:
                if o["t"] == T_END:
                    # Win line is an infinite-height wall, not a 50x50 sprite.
                    draw_end_wall(screen,
                                  o["x"] * effective_cell - cam_x,
                                  o["y"] * effective_cell - cam_y,
                                  effective_cell, pulse)
                    continue
                meta = o if o["t"] in (T_TELEPORT_ORB, T_CAMERA_TRIGGER, T_BG_TRIGGER, T_MOVE_TRIGGER, T_COLOR_TRIGGER, T_SPIDER_ORB) else None
                sx_e = o["x"] * effective_cell - cam_x
                sy_e = o["y"] * effective_cell - cam_y
                draw_obj(screen, o["t"], sx_e, sy_e,
                         effective_cell, pulse, o.get("r", 0), meta,
                         scale=obj_scale(o))
                # Invisible flag: sprite still draws in the editor so
                # the author can select / reposition it, but we dim
                # it and outline it to signal "won't render in play".
                if o.get("invisible"):
                    dim_rect = pygame.Rect(sx_e, sy_e,
                                           effective_cell, effective_cell)
                    dim = pygame.Surface(
                        (effective_cell, effective_cell), pygame.SRCALPHA)
                    dim.fill((0, 0, 0, 140))
                    screen.blit(dim, dim_rect)
                    pygame.draw.rect(screen, (200, 200, 255), dim_rect, 1)
                # Bot-only flag: phantom hazard. Visible in editor
                # for placement, marked with a purple X so the
                # author can tell at a glance that this object
                # only exists for the Y bot's lookahead.
                if o.get("_bot_only"):
                    bx = int(sx_e)
                    by = int(sy_e)
                    cs = int(effective_cell)
                    pygame.draw.line(screen, (180, 100, 230),
                                     (bx + 6, by + 6),
                                     (bx + cs - 6, by + cs - 6), 2)
                    pygame.draw.line(screen, (180, 100, 230),
                                     (bx + cs - 6, by + 6),
                                     (bx + 6, by + cs - 6), 2)
    else:
        # Even in hitbox mode, keep a faint start-line / end-wall so the
        # level bounds are legible.
        for o in objects:
            if (left_gx <= o["x"] <= right_gx and top_gy <= o["y"] <= bot_gy
                    and o["t"] == T_END):
                draw_end_wall(screen,
                              o["x"] * effective_cell - cam_x,
                              o["y"] * effective_cell - cam_y,
                              effective_cell, pulse)
    for o in objects:
        if o["t"] != T_MOVE_TRIGGER:
            continue
        # Collect all target oids (multi or single)
        oids = o.get("target_oids", [])
        if not oids:
            single = o.get("target_oid", 0)
            if single:
                oids = [single]
        if not oids:
            continue
        sxl = o["x"] * effective_cell - cam_x + effective_cell // 2
        syl = o["y"] * effective_cell - cam_y + effective_cell // 2
        for t_oid in oids:
            target = next((x for x in objects if x.get("oid") == t_oid), None)
            if not target:
                continue
            txl = target["x"] * effective_cell - cam_x + effective_cell // 2
            tyl = target["y"] * effective_cell - cam_y + effective_cell // 2
            pygame.draw.line(screen, (200, 150, 255), (sxl, syl), (txl, tyl), 1)
        # Draw destination marker using first target as reference
        first_target = next((x for x in objects if x.get("oid") == oids[0]), None)
        if first_target:
            exl = o.get("tx", first_target["x"]) * effective_cell - cam_x + effective_cell // 2
            eyl = o.get("ty", first_target["y"]) * effective_cell - cam_y + effective_cell // 2
            txl = first_target["x"] * effective_cell - cam_x + effective_cell // 2
            tyl = first_target["y"] * effective_cell - cam_y + effective_cell // 2
            pygame.draw.line(screen, (255, 200, 100), (txl, tyl), (exl, eyl), 1)
            pygame.draw.circle(screen, (255, 200, 100), (exl, eyl), 6, 1)


def render_jump_predictor(screen, objects, cam_x, cam_y, zoom_level):
    """Live arc overlay for the jump-probe object, if one is placed.

    Re-simulated every frame (well under 1ms even on a 300-object level)
    so the arc updates as the user nudges nearby geometry.
    """
    probe = find_probe(objects)
    if probe is None:
        return
    result = predict(objects, probe)
    draw_overlay(
        screen, result, cam_x, cam_y, zoom_level,
        clip_rect=pygame.Rect(0, TOP_H, WIDTH, BAR_Y - TOP_H),
        show_hitbox=bool(probe.get("show_hitbox")),
    )
    # Floating one-liner anchored above the probe cell so the status stays
    # readable even when the arc flies off-screen.
    if result is None:
        return
    eff = int(CELL * zoom_level)
    sx = int(probe["x"] * eff - cam_x + eff / 2)
    sy = int(probe["y"] * eff - cam_y - 6)
    if result["hit"]:
        label = (f"{result['mode']} · "
                 f"f{result['hit'][3]} HIT: {result['hit'][2]}")
        col = (255, 120, 120)
    elif result["landing"]:
        label = f"{result['mode']} · f{result['landing'][2]} LAND"
        col = (140, 255, 170)
    else:
        label = f"{result['mode']} · open"
        col = (255, 210, 120)
    if TOP_H < sy < BAR_Y:
        txt(screen, label, sx, sy, 12, col, True, shadow=True)


def render_hitbox_overlay(screen, objects, cam_x, cam_y, zoom_level,
                          last_run_hitboxes, last_run_mirror_hitboxes):
    """Player hitbox trace from the most recent run, plus level kill/land rects.

    Frames are layered with alpha so a dense pass (a long ship hover) reads
    as one thick band while quick traversals stay legible. Drawn before the
    palette / bot path / selection rings so those stay on top.
    """
    if HITBOX_SCRATCH[0] is None:
        HITBOX_SCRATCH[0] = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    hb_layer = HITBOX_SCRATCH[0]
    hb_layer.fill((0, 0, 0, 0))
    world_left = cam_x / zoom_level - 60
    world_right = (cam_x + WIDTH) / zoom_level + 60
    world_top = cam_y / zoom_level - 60
    world_bot = (cam_y + HEIGHT) / zoom_level + 60

    def draw_obb(layer, hx, hy, hsz, hangle, outer_col, inner_col):
        # OUTER rect rotates with the cube — kills on hazards
        # (spike / saw). Drawn as a rotated polygon outline.
        # INNER rect is axis-aligned regardless of ``hangle`` —
        # kills on solid blocks / slabs. Drawn as a plain AABB
        # outline so the overlay shows exactly the kill rule
        # split: the rotated polygon is the "spike kills you"
        # volume, the upright square is the "wall kills you"
        # volume.
        cx = hx + hsz / 2.0
        cy = hy + hsz / 2.0
        rad = -math.radians(hangle)
        cs = math.cos(rad)
        sn = math.sin(rad)
        half = hsz / 2.0

        outer_pts = []
        for ox, oy in ((-half, -half), (half, -half),
                       (half, half), (-half, half)):
            wx = cx + ox * cs - oy * sn
            wy = cy + ox * sn + oy * cs
            outer_pts.append((int(wx * zoom_level - cam_x),
                              int(wy * zoom_level - cam_y)))
        pygame.draw.polygon(layer, outer_col, outer_pts, 1)

        inner_half = half * SOLID_HITBOX_FRACTION
        ix = int((cx - inner_half) * zoom_level - cam_x)
        iy = int((cy - inner_half) * zoom_level - cam_y)
        iw = max(1, int(inner_half * 2 * zoom_level))
        ih = max(1, int(inner_half * 2 * zoom_level))
        pygame.draw.rect(layer, inner_col, (ix, iy, iw, ih), 1)

    # Trace samples are 4-tuples (x, y, size, angle) at one per
    # logical frame. Legacy 3-tuples (saved from older runs)
    # default to angle 0 so we don't blow up reading them.
    # Outer = green rotated (hazard-kill volume); inner = blue
    # axis-aligned (block-kill volume). Alpha tuned low so a
    # dense run doesn't bleed into a solid block — each sample
    # reads as a discrete frame even when many overlap.
    for sample in last_run_hitboxes:
        hx, hy, hsz = sample[0], sample[1], sample[2]
        hangle = sample[3] if len(sample) > 3 else 0.0
        if (hx + hsz < world_left or hx > world_right
                or hy + hsz < world_top or hy > world_bot):
            continue
        draw_obb(hb_layer, hx, hy, hsz, hangle,
                  (120, 255, 140, 70),   # outer green (hazard)
                  (90, 160, 255, 90))    # inner blue (blocks)
    # Mirror trace from the same attempt. Outer = cyan rotated,
    # inner = blue axis-aligned (same rule split, just lighter
    # so it visually separates from the main body's green).
    for sample in last_run_mirror_hitboxes:
        hx, hy, hsz = sample[0], sample[1], sample[2]
        hangle = sample[3] if len(sample) > 3 else 0.0
        if (hx + hsz < world_left or hx > world_right
                or hy + hsz < world_top or hy > world_bot):
            continue
        draw_obb(hb_layer, hx, hy, hsz, hangle,
                  (120, 220, 255, 70),   # outer cyan (hazard)
                  (90, 160, 255, 90))    # inner blue (blocks)
    # Hazard + solid hitboxes so the author can see EXACTLY where
    # kill zones and landable surfaces live — distinct from the
    # rendered sprite art which has decorative margins.
    eff_left_gx = int(cam_x / zoom_level) // CELL - 1
    eff_right_gx = int((cam_x + WIDTH) / zoom_level) // CELL + 2
    eff_top_gy = int(cam_y / zoom_level) // CELL - 1
    eff_bot_gy = int((cam_y + HEIGHT) / zoom_level) // CELL + 2
    for o in objects:
        t = o["t"]
        if t not in (T_SPIKE, T_HALF_SPIKE, T_SAW,
                     T_BLOCK, T_SLAB, T_SLOPE):
            continue
        gx = o["x"]
        gy = o["y"]
        if not (eff_left_gx <= gx <= eff_right_gx
                and eff_top_gy <= gy <= eff_bot_gy):
            continue
        sc = obj_scale(o)
        # Slopes are diagonal — drawn as a filled triangle
        # rather than a rect. Skip the rect path entirely so
        # the half of the cell that is empty doesn't read as
        # solid in the overlay.
        if t == T_SLOPE:
            pts = slope_polygon(gx, gy, o.get("r", 0), sc)
            spts = [(int(px * zoom_level - cam_x),
                     int(py * zoom_level - cam_y))
                    for px, py in pts]
            pygame.draw.polygon(
                hb_layer, (120, 180, 255, 50), spts)
            pygame.draw.polygon(
                hb_layer, (100, 160, 240, 220), spts, 1)
            continue
        if t == T_SAW:
            rects = [saw_hitbox(gx, gy, sc)]
            fill = (255, 80, 80, 60)
            outline = (255, 60, 60, 220)
        elif t in (T_SPIKE, T_HALF_SPIKE):
            rects = spike_hitboxes(gx, gy, o.get("r", 0),
                                   half=(t == T_HALF_SPIKE),
                                   scale=sc)
            fill = (255, 80, 80, 60)
            outline = (255, 60, 60, 220)
        elif t == T_BLOCK:
            rects = [cell_rect(gx, gy, sc)]
            fill = (120, 180, 255, 50)
            outline = (100, 160, 240, 220)
        else:  # T_SLAB
            rects = [slab_rect(gx, gy, o.get("r", 0), sc)]
            fill = (120, 180, 255, 50)
            outline = (100, 160, 240, 220)
        for rr in rects:
            sx = int(rr.x * zoom_level - cam_x)
            sy = int(rr.y * zoom_level - cam_y)
            sw = max(1, int(rr.w * zoom_level))
            sh = max(1, int(rr.h * zoom_level))
            pygame.draw.rect(hb_layer, fill, (sx, sy, sw, sh))
            pygame.draw.rect(hb_layer, outline,
                             (sx, sy, sw, sh), 1)
    screen.blit(hb_layer, (0, 0))


def render_bot_paths(screen, bot_waypoints, bot_mirror_waypoints,
                     cam_x, cam_y, zoom_level):
    """Yellow bot path and, when the level goes dual, the blue mirror path."""
    if bot_waypoints:
        path_pts = []
        for wx, wy in bot_waypoints:
            sx = int(wx * zoom_level - cam_x)
            sy = int(wy * zoom_level - cam_y)
            path_pts.append((sx, sy))
        if len(path_pts) >= 2:
            pygame.draw.lines(screen, (255, 180, 60), False, path_pts, 2)
        for i, pt in enumerate(path_pts):
            is_end = (i == 0 or i == len(path_pts) - 1)
            col = (255, 220, 100) if is_end else (255, 180, 60)
            pygame.draw.circle(screen, col, pt, 5)
            pygame.draw.circle(screen, (0, 0, 0), pt, 5, 1)
    # Mirror path: drawn in blue to distinguish the dual body's route
    # from the main yellow path. Only present when the autobot solved
    # a level that enters dual mode.
    if bot_mirror_waypoints:
        mpath_pts = []
        for wx, wy in bot_mirror_waypoints:
            sx = int(wx * zoom_level - cam_x)
            sy = int(wy * zoom_level - cam_y)
            mpath_pts.append((sx, sy))
        if len(mpath_pts) >= 2:
            pygame.draw.lines(screen, (90, 170, 255), False, mpath_pts, 2)
        for pt in mpath_pts:
            pygame.draw.circle(screen, (90, 170, 255), pt, 4)
            pygame.draw.circle(screen, (0, 0, 0), pt, 4, 1)


def render_pending_link(screen, pending_link, effective_cell, cam_x, cam_y,
                        mpos, in_canvas):
    """Rubber-band from the half-finished Group-tool pairing to the cursor."""
    kind = pending_link.get("kind")
    if kind == "teleport":
        src = pending_link["first"]
        col = (255, 220, 90)
    elif kind == "move":
        src = pending_link.get("target") or pending_link["trigger"]
        col = (255, 180, 100)
    else:
        src = None
        col = (255, 220, 90)
    if src:
        sxl = src["x"] * effective_cell - cam_x + effective_cell // 2
        syl = src["y"] * effective_cell - cam_y + effective_cell // 2
        pygame.draw.circle(screen, col, (sxl, syl), 26, 2)
        if in_canvas:
            pygame.draw.line(screen, col, (sxl, syl), mpos, 1)
    if kind == "move" and pending_link.get("target"):
        tr = pending_link["trigger"]
        trx = tr["x"] * effective_cell - cam_x + effective_cell // 2
        trry = tr["y"] * effective_cell - cam_y + effective_cell // 2
        pygame.draw.circle(screen, (200, 150, 255), (trx, trry), 26, 2)


def render_selection(screen, selected_objs, single_selected, effective_cell,
                     cam_x, cam_y):
    """Selection rectangles, the single-selection ring, and its target guides."""
    for sobj in selected_objs:
        sx_sel, sy_sel = obj_scale(sobj)
        cell_w = max(1, int(effective_cell * sx_sel))
        cell_h = max(1, int(effective_cell * sy_sel))
        cx = sobj["x"] * effective_cell - cam_x + effective_cell // 2
        cy = sobj["y"] * effective_cell - cam_y + effective_cell // 2
        sxb = cx - cell_w // 2
        syb = cy - cell_h // 2
        pygame.draw.rect(screen, (120, 255, 140),
                         (sxb, syb, cell_w, cell_h), 2)
    if single_selected is not None:
        sx_sel, sy_sel = obj_scale(single_selected)
        cell_w = max(1, int(effective_cell * sx_sel))
        cell_h = max(1, int(effective_cell * sy_sel))
        cx = single_selected["x"] * effective_cell - cam_x + effective_cell // 2
        cy = single_selected["y"] * effective_cell - cam_y + effective_cell // 2
        sxb = cx - cell_w // 2
        syb = cy - cell_h // 2
        ring = pygame.Surface((cell_w + 12, cell_h + 12), pygame.SRCALPHA)
        pygame.draw.rect(ring, (120, 255, 140, 110), ring.get_rect(), 3, border_radius=6)
        screen.blit(ring, (sxb - 6, syb - 6))
        if single_selected["t"] == T_CAMERA_TRIGGER:
            target_y = single_selected.get("cy", single_selected["y"]) * effective_cell - cam_y + effective_cell // 2
            pygame.draw.line(screen, (255, 225, 80),
                             (sxb + effective_cell // 2, syb + effective_cell // 2),
                             (sxb + effective_cell // 2, target_y), 2)
            pygame.draw.line(screen, (255, 225, 80),
                             (0, target_y), (WIDTH, target_y), 1)
        if single_selected["t"] == T_MODE_DUAL:
            # Cyan ghost cube on the chosen spawn row so the user can
            # see exactly where the mirror will appear.
            spawn_row = single_selected.get("spawn_y", single_selected["y"])
            spawn_y_top = spawn_row * effective_cell - cam_y
            ghost = pygame.Rect(sxb, spawn_y_top, effective_cell, effective_cell)
            ghost_layer = pygame.Surface((effective_cell, effective_cell),
                                         pygame.SRCALPHA)
            ghost_layer.fill((120, 220, 255, 90))
            screen.blit(ghost_layer, ghost.topleft)
            pygame.draw.rect(screen, (140, 230, 255), ghost, 2)
            pygame.draw.line(screen, (140, 230, 255),
                             (sxb + effective_cell // 2,
                              syb + effective_cell // 2),
                             (sxb + effective_cell // 2,
                              spawn_y_top + effective_cell // 2), 2)


def render_rubber_band(screen, drag_start_screen, mpos):
    """Translucent marquee for an in-progress Edit-tool box select."""
    x0, y0 = drag_start_screen
    x1, y1 = mpos
    rr = pygame.Rect(min(x0, x1), min(y0, y1),
                     abs(x1 - x0), abs(y1 - y0))
    if rr.width > 0 and rr.height > 0:
        fill = pygame.Surface((rr.w, rr.h), pygame.SRCALPHA)
        fill.fill((120, 255, 140, 40))
        screen.blit(fill, rr.topleft)
        pygame.draw.rect(screen, (120, 255, 140), rr, 1)


def render_tool_cursor(screen, tool, gx, gy, effective_cell, mx, my,
                       cam_x, cam_y, zoom_level, pulse, selected_type,
                       current_rotation, bot_waypoints, snippet_stamp):
    """Ghost preview under the cursor for the active tool (or armed stamp).

    Delegates to the tool's own ``on_preview`` callback so the cursor can
    never drift out of sync with what a click or drag actually does.
    """
    sx = gx * effective_cell - cam_x
    sy = gy * effective_cell - cam_y
    if snippet_stamp is not None:
        # An armed snippet stamp pre-empts the active tool's cursor.
        editor_tools.stamp_preview(
            screen=screen, sx=sx, sy=sy, gx=gx, gy=gy,
            effective_cell=effective_cell, cam_x=cam_x, cam_y=cam_y,
            pulse=pulse, snippet_stamp=snippet_stamp)
    else:
        editor_tools.TOOL_HANDLERS[tool]["on_preview"](
            screen=screen, sx=sx, sy=sy, mx=mx, my=my,
            effective_cell=effective_cell, cam_x=cam_x, cam_y=cam_y,
            zoom_level=zoom_level, pulse=pulse,
            selected_type=selected_type, current_rotation=current_rotation,
            bot_waypoints=bot_waypoints)


def render_status_pills(screen, tool, selected_type, current_rotation,
                        current_group_id):
    """Tool name / rotation / next-group labels on dark pill backdrops.

    The pills exist so these labels stay readable over any level
    background (UI_AUDIT SS11).
    """
    if tool == TOOL_BRUSH:
        sel_name = TYPE_NAMES.get(selected_type, "")
    else:
        sel_name = {TOOL_ERASE: "Eraser", TOOL_GROUP: "Group Tool",
                    TOOL_EDIT: "Edit Tool", TOOL_BOT_PATH: "Bot Path"}[tool]
    # Dark pill backdrop so these status labels remain readable no
    # matter what the level background looks like (UI_AUDIT §11).
    _pill_bg = pygame.Surface((170, 22), pygame.SRCALPHA)
    _pill_bg.fill((0, 0, 0, 160))
    screen.blit(_pill_bg, (4, TOP_H))
    txt(screen, sel_name, 10, TOP_H + 2, 13, C_WHITE)
    _rot_pill = pygame.Surface((80, 22), pygame.SRCALPHA)
    _rot_pill.fill((0, 0, 0, 160))
    screen.blit(_rot_pill, (176, TOP_H))
    txt(screen, f"Rot {current_rotation}°", 180, TOP_H + 2, 13, C_GRAY)
    if selected_type == T_TELEPORT_ORB and tool == TOOL_BRUSH:
        _grp_pill = pygame.Surface((160, 22), pygame.SRCALPHA)
        _grp_pill.fill((0, 0, 0, 160))
        screen.blit(_grp_pill, (296, TOP_H))
        txt(screen, f"Next group: {current_group_id}",
            300, TOP_H + 2, 13, C_GRAY)


def render_toolbar(screen, mpos, bot_waypoints, level_music,
                   r_mute_music, r_mute_sfx):
    """Bottom button row. Returns the two mute-icon rects for hit-testing."""
    pygame.draw.rect(screen, (20, 18, 40), (0, BAR_Y, WIDTH, HEIGHT - BAR_Y))
    pygame.draw.line(screen, C_GRID, (0, BAR_Y), (WIDTH, BAR_Y), 1)
    btn(screen, "Save [S]", 70, BAR_Y + 27, 84, 38, C_BTN, mpos)
    btn(screen, "Publish", 158, BAR_Y + 27, 84, 38, C_PUBLISH, mpos)
    btn(screen, "Load [^L]", 246, BAR_Y + 27, 84, 38, C_BTN, mpos)
    btn(screen, "Test [T]", 334, BAR_Y + 27, 84, 38, (40, 120, 80), mpos)
    bot_label = (f"Bot [L] ({len(bot_waypoints)})"
                 if bot_waypoints else "Bot [L]")
    btn(screen, bot_label, 422, BAR_Y + 27, 84, 38, (180, 120, 30), mpos)
    btn(screen, "Clear", 510, BAR_Y + 27, 70, 38, C_DANGER, mpos)
    music_label = "Music" if level_music is None else "Music*"
    btn(screen, music_label, 590, BAR_Y + 27, 84, 38, (80, 60, 140), mpos)
    btn(screen, "Menu", 678, BAR_Y + 27, 84, 38, C_DANGER, mpos)
    # Mute toggles (icon-only)
    r_mute_music = icon_button(
        screen, speaker_icon(18, music.is_muted()),
        r_mute_music.centerx, r_mute_music.centery, 36, 36, C_BTN, mpos,
        active=music.is_muted(),
    )
    r_mute_sfx = icon_button(
        screen, speaker_icon(16, sfx.is_muted()),
        r_mute_sfx.centerx, r_mute_sfx.centery, 36, 36, (80, 60, 140), mpos,
        active=sfx.is_muted(),
    )
    return r_mute_music, r_mute_sfx


def render_hud(screen, objects, undo_stack, gx_disp, gy_disp, zoom_level,
               level_name, level_meta, dirty, snippet_stamp,
               snippet_stamp_name, show_hitboxes, last_run_hitboxes,
               last_autosave_secs, autosave_toast_frames, msg, msg_timer):
    """Object/undo counts, cursor cell, level status chunks, autosave age, toast."""
    txt(screen, f"Obj: {len(objects)} | Undo: {len(undo_stack)}", WIDTH - 230, BAR_Y + 6, 13, C_GRAY)
    txt(screen, f"Cell: ({gx_disp}, {gy_disp})  Zoom: {zoom_level:.1f}x", WIDTH - 230, BAR_Y + 22, 13, C_GRAY)
    status_chunks = [f"Level: {level_name}"]
    if dirty:
        status_chunks.append("● unsaved")
    if snippet_stamp is not None:
        status_chunks.append(f"⛶ {snippet_stamp_name}")
    if show_hitboxes:
        status_chunks.append(
            f"⌗ Hitboxes ({len(last_run_hitboxes)})"
            if last_run_hitboxes else "⌗ Hitboxes (no run yet)"
        )
    if level_meta:
        if level_meta.get("verified"):
            status_chunks.append("✓ Verified")
        elif level_meta.get("published"):
            status_chunks.append("◦ Published (unverified)")
    txt(screen, " · ".join(status_chunks), WIDTH - 230, BAR_Y + 38, 12, C_GRAY)
    # Autosave HUD indicator: a freshly-flashed "Auto-saved Xs ago" toast
    # appears next to the title row whenever the snapshot was just written,
    # then fades to a steady "Last autosave Xs ago" reading.
    if last_autosave_secs is not None:
        try:
            import time as _time
            ago = max(0, int(_time.time() - last_autosave_secs))
        except Exception:
            ago = 0
        if ago < 60:
            ago_str = f"{ago}s ago"
        elif ago < 3600:
            ago_str = f"{ago // 60}m ago"
        else:
            ago_str = f"{ago // 3600}h ago"
        if autosave_toast_frames > 0:
            col = (140, 230, 140)
            label = f"Auto-saved {ago_str}"
        else:
            col = (130, 130, 150)
            label = f"Last autosave {ago_str}"
        txt(screen, label, WIDTH - 230, BAR_Y + 54, 11, col)
    # One short hint line above the button row — the full list
    # lives behind "?" / F1 / "/". Two-line variants intersected the
    # button row and read as overlapping UI (UI_AUDIT §11).
    txt(screen,
        "Press ? for shortcuts  ·  Tab: categories  ·  1–9: pick",
        WIDTH // 2, BAR_Y - 14, 11, C_GRAY, True)
    if msg_timer > 0:
        txt(screen, msg, WIDTH // 2, BAR_Y - 18, 18, C_PLAYER, True)


def render_palette_tooltip(screen, hovered_item, mx):
    """Name + one-line tip for the palette entry under the cursor."""
    if hovered_item is not None:
        name = TYPE_NAMES.get(hovered_item, "")
        tip = TYPE_TIPS.get(hovered_item, "")
        if name or tip:
            tip_w = 260
            tip_x = min(WIDTH - tip_w - 8, max(8, mx - tip_w // 2))
            tip_y = TOP_H + 6
            tip_h = 40 if tip else 22
            rr = pygame.Rect(tip_x, tip_y, tip_w, tip_h)
            pygame.draw.rect(screen, (10, 8, 24), rr, border_radius=6)
            pygame.draw.rect(screen, (90, 110, 190), rr, 1, border_radius=6)
            txt(screen, name, rr.x + 8, rr.y + 4, 14, C_WHITE)
            if tip:
                txt(screen, tip, rr.x + 8, rr.y + 22, 11, C_GRAY)
