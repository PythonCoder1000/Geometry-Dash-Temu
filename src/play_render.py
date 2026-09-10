"""Rendering helpers for the play loop (``run_play`` in ``play.py``).

Each function here draws one self-contained piece of the play screen —
world objects, an overlay, the HUD, or the pause/win screens. They take
the exact state they need as explicit parameters rather than a shared
state object, so each one stays independently readable and the call
sites in ``run_play`` make it obvious what data feeds each visual.

Pulled out of ``run_play`` verbatim (no behavior changes) as the first
step of breaking that function up — see
``.claude/plans/ethereal-stargazing-backus.md``.
"""

import bisect
import math
import time as _time

import numpy as np
import pygame

from .constants import (
    WIDTH, HEIGHT, CELL, PLAYER_SIZE, PHYSICS_TPS, PX_PER_UNIT,
    C_DARK, C_PLAYER, C_GRAY, C_WHITE, C_BTN, C_COIN, C_SUCCESS, C_DANGER,
    BG_PRESETS, T_COIN, T_END, T_TELEPORT_ORB, T_TELEPORT_PORTAL, T_SPIDER_ORB,
    T_ITEM_COUNTER, RADIAL_BLUR_MAX_ZOOM,
    LEVEL_TRANSITION_FRAMES, LEVEL_TRANSITION_SCALE_START,
)
from .graphics import (
    draw_bg, draw_obj, txt, btn, lighter, darker,
    speaker_icon, icon_button, draw_end_wall, obj_scale, obj_alpha, obj_tint,
)
from . import gd_atlas
from . import music
from . import sfx
from .objects import get_z_order

# The practice checkpoint GD itself plants (its `checkpoint_01` frame,
# glow layer deliberately skipped).
GD_CHECKPOINT_SHEET = "GJ_GameSheet02"
GD_CHECKPOINT_FRAME = "checkpoint_01_001.png"
CHECKPOINT_MARKER_PX = 40


def render_world(screen, cam_x, cam_y, shake_x, shake_y, stars, mountains,
                  bg_top, bg_bot, pulse, z_layers, coins_collected,
                  bg_scale=None, mg_scale=None, bg_index=0):
    """Background + every in-bounds level object, in Z-Layer order.

    ``z_layers`` is a sequence of ``(objs, xs)`` pairs, one per
    :data:`constants.Z_LAYERS` entry back-to-front (b4..b1..t1..t3), each
    already x-sorted for bisect culling. Within a layer, objects draw in
    Z-Order (``get_z_order``, higher = front) so authors can stack detail
    without needing a new layer for every sliver of depth.

    ``bg_scale``/``mg_scale`` come from the player's Background/
    Middleground Speed triggers (Checkpoint 7) and pass straight through
    to draw_bg, where ``None`` means the stock parallax rates."""
    cur_top = tuple(int(c) for c in bg_top)
    cur_bot = tuple(int(c) for c in bg_bot)
    draw_bg(screen, cam_x + shake_x, stars, mountains,
            cam_y=cam_y + shake_y, bg_top=cur_top, bg_bot=cur_bot,
            bg_scale=bg_scale, mg_scale=mg_scale, bg_index=bg_index)
    left_gx = int(cam_x // CELL) - 1
    right_gx = left_gx + WIDTH // CELL + 3
    # The bisect slice keys on each object's ORIGINAL x (stable across
    # move triggers), so give it a generous margin — objects that have
    # been displaced far from their origin by a move trigger should
    # still fall inside the slice. Per-object `_fx` is tested below.
    slice_margin = 200
    lo = left_gx - slice_margin
    hi = right_gx + slice_margin
    for layer, xs in z_layers:
        i = bisect.bisect_left(xs, lo)
        j = bisect.bisect_right(xs, hi)
        visible = sorted(layer[i:j], key=get_z_order)
        for o in visible:
            ox = o.get("_fx", o["x"])
            oy = o.get("_fy", o["y"])
            if not (left_gx - 1 <= ox <= right_gx + 1):
                continue
            # Skip collected coins so they disappear on pickup.
            if o["t"] == T_COIN and o.get("coin_id", 0) in coins_collected:
                continue
            if o["t"] == T_END:
                # Win line is an infinite-height wall, not a 50x50 sprite.
                draw_end_wall(screen, ox * CELL - cam_x + shake_x,
                              oy * CELL - cam_y + shake_y, CELL, pulse)
                continue
            # Invisible objects: every behavior still runs (player.py
            # reads by type, not visibility) but the sprite is
            # skipped so authors can hide blocks, orbs, hazards, etc.
            # behind scale-based teleport gauntlets and other
            # hidden-path tricks.
            if o.get("invisible"):
                continue
            draw_obj(screen, o["t"], ox * CELL - cam_x + shake_x,
                     oy * CELL - cam_y + shake_y, CELL, pulse, o.get("r", 0),
                     o if o["t"] in (T_TELEPORT_ORB, T_TELEPORT_PORTAL,
                                     T_SPIDER_ORB) else None,
                     scale=obj_scale(o), alpha=obj_alpha(o), tint=obj_tint(o))
            # Bot-only object marker: a translucent purple X overlay so
            # the level author can see at a glance that this hazard is
            # phantom (won't kill the live player) but is part of the Y
            # bot's reality. The collision filter in player.py already
            # excludes ``_bot_only`` objects from the live tick, so this
            # is purely a visual tag.
            if o.get("_bot_only"):
                bx = int(ox * CELL - cam_x + shake_x)
                by = int(oy * CELL - cam_y + shake_y)
                pygame.draw.line(screen, (180, 100, 230),
                                 (bx + 6, by + 6),
                                 (bx + CELL - 6, by + CELL - 6), 2)
                pygame.draw.line(screen, (180, 100, 230),
                                 (bx + CELL - 6, by + 6),
                                 (bx + 6, by + CELL - 6), 2)


def render_hint_overlay(screen, overlay_scratch, clear_color, hint_visible,
                         hint_path, hint_mirror_path, cam_x, cam_y,
                         shake_x, shake_y):
    """Autobot hint-mode ghost path (H key) — orange main body, blue mirror."""
    if not (hint_visible and hint_path):
        return
    hint_surf = overlay_scratch
    hint_surf.fill(clear_color)
    prev_pt = None
    for wx, wy in hint_path:
        sx = int(wx - cam_x - shake_x)
        sy = int(wy - cam_y - shake_y)
        if -40 < sx < WIDTH + 40 and -200 < sy < HEIGHT + 200:
            # Tinted dot per waypoint — orange so it visually reads
            # as "guidance" without blending into the player trail.
            pygame.draw.circle(hint_surf, (255, 200, 80, 120), (sx, sy), 4)
            if prev_pt is not None:
                pygame.draw.line(hint_surf, (255, 200, 80, 70),
                                 prev_pt, (sx, sy), 2)
            prev_pt = (sx, sy)
        else:
            prev_pt = None
    # Mirror path (when the level enters dual): blue so the user can
    # tell the two bodies apart at a glance.
    if hint_mirror_path:
        prev_pt = None
        for wx, wy in hint_mirror_path:
            sx = int(wx - cam_x - shake_x)
            sy = int(wy - cam_y - shake_y)
            if -40 < sx < WIDTH + 40 and -200 < sy < HEIGHT + 200:
                pygame.draw.circle(hint_surf, (90, 170, 255, 120), (sx, sy), 4)
                if prev_pt is not None:
                    pygame.draw.line(hint_surf, (90, 170, 255, 70),
                                     prev_pt, (sx, sy), 2)
                prev_pt = (sx, sy)
            else:
                prev_pt = None
    screen.blit(hint_surf, (0, 0))


def render_predicted_path(screen, overlay_scratch, clear_color,
                           pred_path_sorted, pred_path_xs, player_x,
                           player_size, cam_x, cam_y, shake_x, shake_y):
    """Y-bot's planned route: a forward-fading green line ahead of the player."""
    if not pred_path_sorted:
        return
    pp_player_x = player_x + player_size / 2
    # Window: a few seconds ahead at base speed (≈ 5 px/frame × 60 fps =
    # 300 px/sec → 900 px ≈ 3 s of preview).
    pp_window = 900.0
    i_lo = bisect.bisect_left(pred_path_xs, pp_player_x)
    i_hi = bisect.bisect_right(pred_path_xs, pp_player_x + pp_window)
    if i_hi - i_lo < 2:
        return
    pred_surf = overlay_scratch
    pred_surf.fill(clear_color)
    slice_pts = pred_path_sorted[i_lo:i_hi]
    span = max(1.0, pp_window)
    prev_pt = None
    for wx, wy in slice_pts:
        sx = int(wx - cam_x - shake_x)
        sy = int(wy - cam_y - shake_y)
        if -40 < sx < WIDTH + 40 and -200 < sy < HEIGHT + 200:
            # Alpha decays linearly with distance ahead.
            d = max(0.0, wx - pp_player_x)
            a = max(40, int(220 * (1.0 - d / span)))
            if prev_pt is not None:
                pygame.draw.line(pred_surf, (90, 255, 150, a),
                                 prev_pt, (sx, sy), 3)
            prev_pt = (sx, sy)
        else:
            prev_pt = None
    screen.blit(pred_surf, (0, 0))


def render_ghost_paths(screen, overlay_scratch, clear_color, ghost_paths,
                        bot_frame, playback_inputs, bot_controller,
                        cam_x, cam_y, shake_x, shake_y):
    """Y-bot click/no-click probe overlays with death/win end markers."""
    if not ghost_paths:
        return
    gp_surf = overlay_scratch
    gp_surf.fill(clear_color)
    # The bot's NEXT action — the one whose probe rollouts the ghost
    # lines visualize. For precomputed playback, ``bot_frame`` indexes
    # the next input to consume; for the LIVE bot the controller
    # exposes its just-decided forecast on ``last_forecast`` and we
    # read which branch it picked from there.
    next_idx = bot_frame
    cur_held = False
    if playback_inputs is not None and 0 <= next_idx < len(playback_inputs):
        cur_held = bool(playback_inputs[next_idx][0])
    elif bot_controller is not None:
        live_fc = getattr(bot_controller, "last_forecast", None)
        if live_fc:
            cur_held = (live_fc.get("chosen") == "click")
    for gp in ghost_paths:
        # Three schemas:
        #   * static "waypoints": one fixed trajectory.
        #   * precomputed "frames": indexed by bot_frame.
        #   * live "live=True, branch=...": pulls from the
        #     bot_controller's just-decided forecast.
        live = gp.get("live", False)
        frames = gp.get("frames")
        if live and bot_controller is not None:
            fc = getattr(bot_controller, "last_forecast", None)
            if not fc:
                continue
            branch_key = gp.get("branch", "click")
            fr = fc.get(branch_key) or {}
            wps = fr.get("wp") or []
            death = fr.get("death")
            won_flag = fr.get("won", False)
            chosen_when = gp.get("chosen_when")
            is_chosen = (
                (chosen_when == "click" and cur_held)
                or (chosen_when == "noclick" and not cur_held))
        elif frames is not None:
            if not frames:
                continue
            idx = next_idx
            if idx >= len(frames):
                idx = len(frames) - 1
            if idx < 0:
                idx = 0
            fr = frames[idx]
            wps = fr.get("wp") or []
            death = fr.get("death")
            won_flag = fr.get("won", False)
            chosen_when = gp.get("chosen_when")
            is_chosen = (
                (chosen_when == "click" and cur_held)
                or (chosen_when == "noclick" and not cur_held))
        else:
            wps = gp.get("waypoints") or []
            death = gp.get("death")
            won_flag = gp.get("won", False)
            is_chosen = False
        if len(wps) < 2:
            continue
        col = gp.get("color", (200, 200, 200))
        # Tint the line red when this branch's rollout died — without
        # this, an off-screen death (the death position is past the
        # camera's right edge) made the line look fine and the user
        # couldn't tell why the bot picked the other branch. The red
        # tint blends with the branch's base color so the user can
        # still tell the click line from the no-click line, but
        # there's an unmistakable "this branch is doomed" signal even
        # when the actual death marker is off-screen.
        if death is not None:
            col = (max(40, min(255, (col[0] + 240) // 2)),
                   max(40, min(255, (col[1] + 70) // 2)),
                   max(40, min(255, (col[2] + 70) // 2)))
        # Brighten the actively-chosen branch so the user can see at a
        # glance which one the bot picked this frame.
        line_alpha = 220 if is_chosen else 110
        line_w = 3 if is_chosen else 2
        rgba = (col[0], col[1], col[2], line_alpha)
        prev_pt = None
        for wx, wy in wps:
            sx = int(wx - cam_x - shake_x)
            sy = int(wy - cam_y - shake_y)
            if -60 < sx < WIDTH + 60 and -200 < sy < HEIGHT + 200:
                if prev_pt is not None:
                    pygame.draw.line(gp_surf, rgba, prev_pt, (sx, sy), line_w)
                prev_pt = (sx, sy)
            else:
                prev_pt = None
        # End-of-line marker.
        if death is not None or won_flag:
            end_x, end_y = wps[-1]
            sz = int(death["size"]) if death else PLAYER_SIZE
            if death:
                # Last hitbox before death — use the death's own x/y
                # (corner of the player rect at the moment of death) so
                # it lines up with the actual collision pose, not the
                # last sampled centre.
                bx = int(death["x"] - cam_x - shake_x)
                by = int(death["y"] - cam_y - shake_y)
            else:
                # Win marker centred on the last waypoint.
                bx = int(end_x - cam_x - shake_x) - sz // 2
                by = int(end_y - cam_y - shake_y) - sz // 2
            rect = pygame.Rect(bx, by, sz, sz)
            if death:
                # Red death box.
                pygame.draw.rect(gp_surf, (255, 70, 70, 110), rect)
                pygame.draw.rect(gp_surf, (255, 110, 110, 240), rect, 2)
            else:
                # Gold win flag.
                pygame.draw.rect(gp_surf, (255, 220, 80, 90), rect)
                pygame.draw.rect(gp_surf, (255, 240, 130, 240), rect, 2)
    # Legend in the top-left corner so the viewer knows which colour
    # means what.
    legend_x = 16
    legend_y = 16
    for gp in ghost_paths:
        col = gp.get("color", (200, 200, 200))
        pygame.draw.rect(gp_surf, (col[0], col[1], col[2], 220),
                         (legend_x, legend_y, 18, 4))
        txt(gp_surf, gp.get("label", ""), legend_x + 24, legend_y - 6,
            13, (220, 230, 240), shadow=True)
        legend_y += 18
    screen.blit(gp_surf, (0, 0))


def render_death_hitbox_marker(screen, overlay_scratch, clear_color,
                                predicted_path, death_hitbox, death_timer,
                                cam_x, cam_y, shake_x, shake_y):
    """Frozen red hitbox at the exact death position (Y-bot predicted runs)."""
    if not (predicted_path and death_hitbox is not None and death_timer > 0):
        return
    dh_x, dh_y, dh_size, dh_angle, dh_reason = death_hitbox
    dh_surf = overlay_scratch
    dh_surf.fill(clear_color)
    sx = int(dh_x - cam_x - shake_x)
    sy = int(dh_y - cam_y - shake_y)
    # Rect outline + half-fill in red so it reads as a fault marker
    # rather than yet another player ghost.
    rect = pygame.Rect(sx, sy, int(dh_size), int(dh_size))
    pygame.draw.rect(dh_surf, (255, 60, 60, 90), rect)
    pygame.draw.rect(dh_surf, (255, 100, 100, 220), rect, 2)
    screen.blit(dh_surf, (0, 0))


def render_best_run_ghost(screen, overlay_scratch, clear_color, best_run,
                           attempt_frames, cam_x, cam_y, shake_x, shake_y):
    """Fading trail of the player's own best prior attempt this session."""
    if not best_run:
        return
    ghost_surf = overlay_scratch
    ghost_surf.fill(clear_color)
    # Find the segment near current time +/- some window so the ghost
    # "runs alongside" rather than rendering the entire track.
    window = 120  # frames before and after
    lo = attempt_frames - window
    hi = attempt_frames + window
    for gf, gx, gy in best_run:
        if gf < lo or gf > hi:
            continue
        sx = int(gx - cam_x - shake_x)
        sy = int(gy - cam_y - shake_y)
        if -30 < sx < WIDTH + 30 and -30 < sy < HEIGHT + 30:
            # Alpha fades with distance from current frame.
            dist = abs(gf - attempt_frames)
            a = max(0, int(110 * (1.0 - dist / window)))
            pygame.draw.circle(ghost_surf, (200, 200, 255, a),
                               (sx + 22, sy + 22), 10)
    screen.blit(ghost_surf, (0, 0))


def render_player_and_particles(screen, player, particles, death_timer,
                                 bot_click_flash, cam_x, cam_y,
                                 shake_x, shake_y, alpha=None):
    """The live player sprite + bot-click ring flash, then all particles.
    ``alpha`` interpolates the player between physics ticks."""
    if player.alive and death_timer == 0:
        player.draw(screen, cam_x + shake_x, cam_y + shake_y, alpha)
        if bot_click_flash > 0:
            t = 1.0 - (bot_click_flash / 48.0)  # matches play.bot_click_flash=48 (240 TPS)
            radius = int(26 + 28 * t)
            alpha = int(220 * (1.0 - t))
            # Center on the player's visual midpoint, which shrinks
            # with `player.size` in mini mode — a fixed +22 offset
            # placed the ring 10 px off-center for mini cubes.
            cx = int(player.x_px - cam_x - shake_x + player.size_px / 2)
            cy = int(player.y_px - cam_y - shake_y + player.size_px / 2)
            ring_side = radius * 2 + 8
            ring_surf = pygame.Surface((ring_side, ring_side), pygame.SRCALPHA)
            pygame.draw.circle(ring_surf, (255, 200, 80, alpha),
                               (radius + 4, radius + 4), radius, 3)
            screen.blit(ring_surf, (cx - radius - 4, cy - radius - 4))
    particles.draw(screen, cam_x + shake_x, cam_y + shake_y)


def render_checkpoint_markers(screen, practice_mode, player, pulse,
                               cam_x, cam_y, shake_x, shake_y):
    """Practice-mode checkpoint markers planted with the C key.

    These never go through ``draw_obj`` (they are player state, not level
    objects), so the real-GD ``checkpoint_01`` texture is pulled straight
    from the atlas here; without it the hand-drawn flag still renders.
    """
    if not (practice_mode and player.checkpoints and not player.won):
        return
    pulse_t = (pulse % PHYSICS_TPS) / PHYSICS_TPS  # `pulse` ticks once/tick
    glow = int(90 + 40 * math.sin(pulse_t * math.tau))
    marker = gd_atlas.compose(GD_CHECKPOINT_SHEET, GD_CHECKPOINT_FRAME,
                              CHECKPOINT_MARKER_PX, fit="contain")
    for i, cp in enumerate(player.checkpoints):
        fx = int(cp["x"] * PX_PER_UNIT - cam_x - shake_x)
        fy = int(cp["y"] * PX_PER_UNIT - cam_y - shake_y)
        # Cull off-screen markers cheaply.
        if fx < -40 or fx > WIDTH + 40:
            continue
        pole_top = fy - 28
        if marker is not None:
            screen.blit(marker, (fx + 8 - CHECKPOINT_MARKER_PX // 2, pole_top))
        else:
            pole_bot = fy + 44
            pygame.draw.line(screen, (230, 230, 240),
                             (fx + 8, pole_top), (fx + 8, pole_bot), 2)
            flag_pts = [(fx + 8, pole_top),
                        (fx + 30, pole_top + 8),
                        (fx + 8, pole_top + 16)]
            pygame.draw.polygon(screen, (90, 220, 140), flag_pts)
            pygame.draw.polygon(screen, (20, 100, 50), flag_pts, 2)
        # Soft pulsing halo around the flag so it reads as "interactive"
        # rather than part of the level art.
        halo = pygame.Surface((44, 44), pygame.SRCALPHA)
        pygame.draw.circle(halo, (120, 255, 160, glow), (22, 22), 22)
        screen.blit(halo, (fx - 14, pole_top - 6))
        # Number label on the flag (1-indexed).
        txt(screen, str(i + 1), fx + 14, pole_top + 4, 11,
            (20, 40, 20), center=True)


def render_death_reason(screen, death_timer, player):
    """Short "Hit a spike" style readout shown right after death."""
    if not (death_timer > 0 and getattr(player, "death_reason", "")):
        return
    # DEATH_FRAMES=180 (was 45 pre-240TPS-migration): fade in over the first
    # 48 ticks (was 12) of the death pause, same real-time duration as before.
    fade = max(0.0, min(1.0, (180 - death_timer) / 48.0))
    reason = player.death_reason
    rtxt = f"☠  {reason}"
    reason_surf = pygame.Surface((WIDTH, 46), pygame.SRCALPHA)
    reason_surf.fill((0, 0, 0, int(140 * fade)))
    screen.blit(reason_surf, (0, HEIGHT // 2 + 60))
    txt(screen, rtxt, WIDTH // 2, HEIGHT // 2 + 82,
        22, (255, 220, 220), True, shadow=True)


def render_toast(screen, text, timer):
    """Brief centred notice (Start Position switches and the like)."""
    if timer <= 0 or not text:
        return
    txt(screen, text, WIDTH // 2, HEIGHT // 2 - 120, 20, C_WHITE, True,
        shadow=True)


def render_slowmo_vignette(screen, overlay_scratch, clear_color,
                            death_slowmo_timer):
    """Bordered darkening while the punchy death slow-mo is active."""
    if death_slowmo_timer <= 0:
        return
    alpha = int(120 * (death_slowmo_timer / 120.0))  # matches DEATH_SLOWMO_FRAMES=120 (240 TPS)
    if alpha <= 0:
        return
    border = 120
    dark = (0, 0, 0, alpha)
    overlay_scratch.fill(clear_color)
    overlay_scratch.fill(dark, (0, 0, WIDTH, border))
    overlay_scratch.fill(dark, (0, HEIGHT - border, WIDTH, border))
    overlay_scratch.fill(dark, (0, 0, border, HEIGHT))
    overlay_scratch.fill(dark, (WIDTH - border, 0, border, HEIGHT))
    screen.blit(overlay_scratch, (0, 0))


def render_pulse_flash(screen, overlay_scratch, pulse_amp, color=(255, 240, 255)):
    """BPM-modulated screen tint from a level's pulse trigger, optionally
    tinted to a color-channel (see ``Player.pulse_color``)."""
    if pulse_amp <= 0.01:
        return
    r, g, b = color
    overlay_scratch.fill((r, g, b, int(60 * pulse_amp)))
    screen.blit(overlay_scratch, (0, 0))


def level_transition_state(kind, attempt_frames):
    """``(blackout_amount, zoom_multiplier)`` for the level-start
    transition (Checkpoint 7, ``meta["transition"]``).

    Deliberately a pure function of the attempt's tick counter rather
    than a piece of session state: play.py already resets
    ``attempt_frames`` to 0 on every attempt (``_init_attempt_state``),
    so the transition restarts on every retry for free and there is
    nothing extra to keep in sync.

    Both outputs feed EXISTING render stages instead of adding one:
    ``blackout_amount`` goes into render_blackout (the Blackout Trigger's
    fade-to-black, max'd with it) and ``zoom_multiplier`` into
    apply_camera_post's zoom (the Zoom Trigger's). "none" and any
    finished/unknown transition return the identity pair.
    """
    if kind not in ("fade", "scale") or attempt_frames >= LEVEL_TRANSITION_FRAMES:
        return (0.0, 1.0)
    t = max(0.0, attempt_frames / LEVEL_TRANSITION_FRAMES)
    eased = 1.0 - (1.0 - t) * (1.0 - t)  # ease-out
    if kind == "fade":
        return (1.0 - eased, 1.0)
    return (0.0, LEVEL_TRANSITION_SCALE_START
            + (1.0 - LEVEL_TRANSITION_SCALE_START) * eased)


def render_blackout(screen, overlay_scratch, amount):
    """Full-screen solid-black fade from a Blackout Trigger — drawn over
    the world, hint/path overlays, player, trail and particles so an
    ``amount`` of 1.0 hides everything underneath it."""
    if amount <= 0.001:
        return
    if amount >= 0.999:
        screen.fill((0, 0, 0))
        return
    overlay_scratch.fill((0, 0, 0, int(255 * amount)))
    screen.blit(overlay_scratch, (0, 0))


def _rgb_to_hsv_np(rgb):
    """Vectorised RGB->HSV, ``rgb`` shape (..., 3) in [0, 1]."""
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    maxc = np.max(rgb, axis=-1)
    minc = np.min(rgb, axis=-1)
    v = maxc
    delta = maxc - minc
    delta_safe = np.where(delta == 0, 1.0, delta)
    s = np.where(maxc == 0, 0.0, delta / np.where(maxc == 0, 1.0, maxc))
    rc = (maxc - r) / delta_safe
    gc = (maxc - g) / delta_safe
    bc = (maxc - b) / delta_safe
    h = np.zeros_like(maxc)
    h = np.where(maxc == b, 4.0 + gc - rc, h)
    h = np.where(maxc == g, 2.0 + rc - bc, h)
    h = np.where(maxc == r, bc - gc, h)
    h = (h / 6.0) % 1.0
    h = np.where(delta == 0, 0.0, h)
    return np.stack([h, s, v], axis=-1)


def _hsv_to_rgb_np(hsv):
    """Vectorised HSV->RGB, ``hsv`` shape (..., 3) in [0, 1]."""
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    i = np.floor(h * 6.0)
    f = h * 6.0 - i
    p = v * (1.0 - s)
    q = v * (1.0 - s * f)
    t = v * (1.0 - s * (1.0 - f))
    i = (i.astype(np.int64)) % 6
    conditions = [i == k for k in range(6)]
    r = np.select(conditions, [v, q, p, p, t, v])
    g = np.select(conditions, [t, v, v, q, p, p])
    b = np.select(conditions, [p, p, t, v, v, q])
    return np.stack([r, g, b], axis=-1)


# The bookkeeping half of an active_effect_anims entry — everything that
# drives the tween itself rather than the pixel operation.
_EFFECT_TWEEN_KEYS = frozenset({"start", "cur", "target", "frame",
                                "duration", "easing"})
# The effects that share one pass over one float32 copy of the frame.
_COLOR_EFFECTS = frozenset({"grayscale", "sepia", "invert", "hue"})


def build_screen_effects(active_effect_anims):
    """Player.active_effect_anims -> the sparse ``effects`` dict
    :func:`apply_screen_effects` consumes (near-zero intensities
    dropped so an idle level pays no per-frame numpy cost).

    One uniform shape per effect: ``{name: {"amount": cur, **knobs}}``,
    where the knobs are whatever ``triggers.SCREEN_EFFECT_PARAMS`` put
    on the animation entry, passed through untouched. This function
    therefore stays generic -- adding a screen effect means adding a
    param row and a render branch, never a case here.
    """
    out = {}
    for name, anim in active_effect_anims.items():
        cur = anim.get("cur", 0.0)
        if cur <= 0.001:
            continue
        params = {k: v for k, v in anim.items() if k not in _EFFECT_TWEEN_KEYS}
        params["amount"] = cur
        out[name] = params
    return out


# Bulge/Pinch geometry cache: the per-pixel distance field only depends
# on the frame size and the effect's center/radius, none of which change
# while the effect merely fades in, so recomputing four full-screen
# float arrays every frame would be pure waste. Bounded because the key
# includes the (author-controlled) center and radius.
_RADIAL_FIELD_CACHE = {}
_RADIAL_FIELD_CACHE_MAX = 8


def _radial_falloff_field(w, h, cx, cy, radius):
    """``(dx, dy, falloff)`` for a ``w x h`` frame about ``(cx, cy)``.

    ``falloff`` is 1 at the center and 0 at/outside ``radius``, squared
    so the displacement eases off instead of ending on a visible ring.
    Arrays are (w, h) to match pygame's surfarray x-major layout.
    """
    key = (w, h, round(cx, 1), round(cy, 1), round(radius, 1))
    hit = _RADIAL_FIELD_CACHE.get(key)
    if hit is not None:
        return hit
    dx = np.arange(w, dtype=np.float32)[:, None] - cx
    dy = np.arange(h, dtype=np.float32)[None, :] - cy
    dist = np.sqrt(dx * dx + dy * dy)
    falloff = np.clip(1.0 - dist / radius, 0.0, 1.0)
    np.square(falloff, out=falloff)
    if len(_RADIAL_FIELD_CACHE) >= _RADIAL_FIELD_CACHE_MAX:
        _RADIAL_FIELD_CACHE.clear()
    _RADIAL_FIELD_CACHE[key] = (dx, dy, falloff)
    return dx, dy, falloff


def _apply_radial_displace(surf, params, sign):
    """Bulge (``sign`` -1) / Pinch (``sign`` +1): resample each pixel from
    a point pushed toward or away from the effect center.

    A nearest-neighbour numpy gather -- one fancy-index read of the frame,
    the same cost class as Pixelate's existing scale-down/scale-up pair.
    No interpolation: a bilinear gather would be four gathers plus the
    blend, and at frame rate the aliasing is not worth 4x the cost.
    """
    amt = params["amount"] * params.get("strength", 0.5)
    if amt <= 0.001:
        return
    w, h = surf.get_size()
    cx = w * 0.5 + params.get("center_x", 0)
    cy = h * 0.5 + params.get("center_y", 0)
    dx, dy, falloff = _radial_falloff_field(w, h, cx, cy,
                                            max(1.0, params.get("radius", 240.0)))
    scale = 1.0 + sign * amt * falloff
    src_x = np.clip(cx + dx * scale, 0, w - 1).astype(np.int32)
    src_y = np.clip(cy + dy * scale, 0, h - 1).astype(np.int32)
    arr = pygame.surfarray.array3d(surf)
    pygame.surfarray.blit_array(surf, arr[src_x, src_y])


def _apply_split_screen(surf, params):
    """BEST-EFFORT. deep-research-report.md gives Split Screen an object
    id (2924) but marks its exact fields "unspecified", so this
    implements only the visually obvious reading of the name: split the
    frame in half on one axis and mirror the first half onto the second.
    Nothing here is claimed to match real GD's parameters."""
    amt = params["amount"]
    if amt <= 0.001:
        return
    arr = pygame.surfarray.array3d(surf)
    w, h = arr.shape[0], arr.shape[1]
    mirrored = arr.copy()
    if params.get("axis", "vertical") == "horizontal":
        half = h // 2
        mirrored[:, half:] = arr[:, :h - half][:, ::-1]
    else:
        half = w // 2
        mirrored[half:] = arr[:w - half][::-1]
    if amt < 0.999:
        mirrored = (arr.astype(np.float32) * (1 - amt)
                    + mirrored.astype(np.float32) * amt).astype(np.uint8)
    pygame.surfarray.blit_array(surf, mirrored)


def _apply_chromatic(surf, params):
    """Chromatic aberration: slide the red channel one way and the blue
    channel the other, leaving green put. Two ``np.roll``s -- the
    cheapest of the Checkpoint-4 effects."""
    shift = int(round(params.get("offset_px", 6) * params["amount"]))
    if shift == 0:
        return
    arr = pygame.surfarray.array3d(surf)
    out = arr.copy()
    out[..., 0] = np.roll(arr[..., 0], shift, axis=0)
    out[..., 2] = np.roll(arr[..., 2], -shift, axis=0)
    pygame.surfarray.blit_array(surf, out)


def _apply_radial_blur(surf, params):
    """Radial (zoom) blur: average N copies of the frame scaled out from
    center by increasing amounts.

    PERF: each sample costs a full smoothscale + blit + array read, so
    this is by far the most expensive screen effect -- sample_count is
    capped at RADIAL_BLUR_MAX_SAMPLES for exactly that reason. Four
    samples reads as a blur while staying at roughly the cost of the
    existing colour pipeline; eight is the ceiling, not a suggestion.
    """
    amt = params["amount"] * params.get("strength", 0.5)
    if amt <= 0.001:
        return
    samples = max(2, int(params.get("sample_count", 4)))
    w, h = surf.get_size()
    acc = pygame.surfarray.array3d(surf).astype(np.float32)
    scratch = pygame.Surface((w, h))
    used = 1
    for i in range(1, samples):
        zoom = 1.0 + RADIAL_BLUR_MAX_ZOOM * amt * (i / (samples - 1))
        nw, nh = int(w * zoom), int(h * zoom)
        if nw <= w and nh <= h:
            continue
        scaled = pygame.transform.smoothscale(surf, (nw, nh))
        scratch.blit(scaled, (-(nw - w) // 2, -(nh - h) // 2))
        acc += pygame.surfarray.array3d(scratch)
        used += 1
    if used > 1:
        pygame.surfarray.blit_array(surf, (acc / used).astype(np.uint8))


def _apply_motion_blur(surf, params, frame_history):
    """Blend the last N rendered frames into this one.

    ``frame_history`` is a plain list owned by the render session (see
    ``PlaySession._init_attempt_state``) rather than by ``Player``: it
    holds raw frame buffers, which are render-side state the physics
    ``Player`` (and every bot that snapshots one) must not carry.

    The frames stored are the *pre-blend* ones, so this is a bounded box
    average over the last N frames rather than a feedback loop that
    would smear a bright frame forever.
    """
    cur = pygame.surfarray.array3d(surf)
    weight = params["amount"] * params.get("strength", 0.5)
    history = [f for f in frame_history if f.shape == cur.shape]
    if history and weight > 0.001:
        avg = np.mean(np.stack(history, axis=0), axis=0, dtype=np.float32)
        blended = cur.astype(np.float32) * (1 - weight) + avg * weight
        pygame.surfarray.blit_array(surf, blended.astype(np.uint8))
    frame_history.append(cur)
    depth = max(1, int(params.get("frame_count", 3)) - 1)
    del frame_history[:-depth]


def apply_screen_effects(surf, effects, frame_history=None):
    """Apply every active screen effect in place on ``surf``.

    Checkpoint 6 (editor reference Sec 4) brought the colour remaps and
    block resampling; Checkpoint 4 (deep-research-report.md, "Shader and
    visual effects") added the displacement/accumulation shaders that a
    numpy pipeline can still do honestly. Gradient (2903), Shock Wave
    (2905), Shock Line (2907), Glitch (2909), Chromatic Glitch (2911)
    and Lens Circle (2913) remain unimplemented: they need true
    per-pixel GPU-shader displacement/noise, which pygame cannot do at
    frame rate.

    Order is an engine convention (the report specifies none): geometry
    first (bulge/pinch, then the split/mirror), then the per-channel and
    resampling passes, then colour, and motion blur last so what gets
    remembered is the frame the player actually saw.
    """
    if not effects:
        return surf
    if "bulge" in effects:
        _apply_radial_displace(surf, effects["bulge"], -1.0)
    if "pinch" in effects:
        _apply_radial_displace(surf, effects["pinch"], 1.0)
    if "split_screen" in effects:
        _apply_split_screen(surf, effects["split_screen"])
    if "chromatic" in effects:
        _apply_chromatic(surf, effects["chromatic"])
    if "radial_blur" in effects:
        _apply_radial_blur(surf, effects["radial_blur"])
    if "pixelate" in effects:
        params = effects["pixelate"]
        amt = params["amount"]
        psize = max(2, int(params.get("pixel_size", 8)))
        if amt > 0:
            w, h = surf.get_size()
            small = pygame.transform.scale(surf, (max(1, w // psize),
                                                   max(1, h // psize)))
            pixelated = pygame.transform.scale(small, (w, h))
            if amt >= 0.999:
                surf = pixelated
            else:
                a = pygame.surfarray.array3d(surf).astype(np.float32)
                b = pygame.surfarray.array3d(pixelated).astype(np.float32)
                blended = (a * (1 - amt) + b * amt).astype(np.uint8)
                pygame.surfarray.blit_array(surf, blended)
    color_effects = {k: v for k, v in effects.items() if k in _COLOR_EFFECTS}
    if color_effects:
        arr = pygame.surfarray.array3d(surf).astype(np.float32)
        base = arr
        result = arr.copy()
        if "grayscale" in color_effects:
            amt = color_effects["grayscale"]["amount"]
            gray = (base[..., 0] * 0.299 + base[..., 1] * 0.587
                    + base[..., 2] * 0.114)
            gray3 = np.repeat(gray[..., None], 3, axis=2)
            result = result * (1 - amt) + gray3 * amt
        if "sepia" in color_effects:
            amt = color_effects["sepia"]["amount"]
            r, g, b = base[..., 0], base[..., 1], base[..., 2]
            sr = r * 0.393 + g * 0.769 + b * 0.189
            sg = r * 0.349 + g * 0.686 + b * 0.168
            sb = r * 0.272 + g * 0.534 + b * 0.131
            sepia = np.clip(np.stack([sr, sg, sb], axis=-1), 0, 255)
            result = result * (1 - amt) + sepia * amt
        if "invert" in color_effects:
            amt = color_effects["invert"]["amount"]
            inv = 255.0 - base
            result = result * (1 - amt) + inv * amt
        if "hue" in color_effects:
            amt = color_effects["hue"]["amount"]
            degrees = color_effects["hue"].get("hue_shift", 60.0)
            if amt > 0 and degrees:
                norm = np.clip(result, 0, 255) / 255.0
                hsv = _rgb_to_hsv_np(norm)
                hsv[..., 0] = (hsv[..., 0] + (degrees * amt) / 360.0) % 1.0
                rgb = _hsv_to_rgb_np(hsv)
                result = rgb * 255.0
        result = np.clip(result, 0, 255).astype(np.uint8)
        pygame.surfarray.blit_array(surf, result)
    if "motion_blur" in effects and frame_history is not None:
        _apply_motion_blur(surf, effects["motion_blur"], frame_history)
    return surf


def apply_camera_post(screen, zoom, rotation, effects, frame_history=None):
    """Checkpoint 6: post-process the fully-drawn world frame (zoom/
    rotate the whole view, then any active screen effects) — called once
    per frame after every world-affecting draw but before the HUD, so
    the HUD itself is never zoomed/rotated/tinted, matching real GD.

    ``frame_history`` is the Motion Blur ring buffer (Checkpoint 4),
    owned by the caller. Dropped as soon as Motion Blur stops, so
    re-enabling it never blends in a frame from minutes ago."""
    if frame_history is not None and "motion_blur" not in effects:
        frame_history.clear()
    if zoom == 1.0 and rotation == 0.0 and not effects:
        return
    w, h = screen.get_size()
    surf = screen.copy()
    if effects:
        surf = apply_screen_effects(surf, effects, frame_history)
    if rotation != 0.0:
        surf = pygame.transform.rotate(surf, rotation)
    if zoom != 1.0:
        new_w = max(1, int(surf.get_width() * zoom))
        new_h = max(1, int(surf.get_height() * zoom))
        surf = pygame.transform.smoothscale(surf, (new_w, new_h))
    if rotation != 0.0 or zoom != 1.0:
        rw, rh = surf.get_size()
        screen.fill((0, 0, 0))
        screen.blit(surf, ((w - rw) // 2, (h - rh) // 2))
    else:
        screen.blit(surf, (0, 0))


def render_hud(screen, player, max_x, attempts, attempt_frames, meta,
                is_sim_run, bot_press_frames, bot_press_total,
                manual_takeover, takeover_idle_frames, manual_takeover_grace,
                level_name, total_coins, practice_mode, hint_visible,
                hint_path, hint_status, editor_test, test_speed_idx,
                test_speeds, bot_controller, playback_inputs, bot_frame,
                playback_wp_sorted, desync_alert_timer, desync_max_px):
    """Progress bar, attempt/time readout, coin tally, and status labels."""
    progress = max(0.0, min(1.0, player.x / max_x))
    bar_x = 50
    bar_y = 10
    bar_h = 12
    bw = WIDTH - 2 * bar_x
    if progress < 0.5:
        bar_color = (255, int(255 * (progress / 0.5)), 0)
    else:
        bar_color = (int(255 * (1 - (progress - 0.5) / 0.5)), 255, 0)
    pygame.draw.rect(screen, C_DARK, (bar_x, bar_y, bw, bar_h),
                     border_radius=4)
    pygame.draw.rect(screen, bar_color,
                     (bar_x, bar_y, max(1, int(bw * progress)), bar_h),
                     border_radius=4)
    for pct in range(10, 100, 10):
        tx = bar_x + int(bw * pct / 100)
        pygame.draw.rect(screen, (0, 0, 0, 80),
                         (tx, bar_y + 2, 1, bar_h - 4))
    progress_percent = int(progress * 100)
    txt(screen, f"{progress_percent}%",
        bar_x + int(bw * progress) + 10, bar_y - 4, 14, C_GRAY, shadow=True)

    # Attempt / time stack sits BELOW the progress bar, clearly separated
    # so nothing visually collides with the coin HUD.
    hud_text_y = bar_y + bar_h + 10
    txt(screen, f"Attempt {attempts}", 20, hud_text_y, 17, C_GRAY, shadow=True)
    # `attempt_frames`/`best_time_frames` count physics ticks; converting
    # to seconds via PHYSICS_TPS keeps this correct at the new 240 TPS
    # rate. NOTE: any `best_time_frames` persisted from before the
    # Checkpoint-3 tick-rate migration was recorded at 60 TPS and will
    # now read ~4x too fast until the level is re-completed — same
    # staleness the plan already flags for saved bot runs.
    cur_time_s = attempt_frames / PHYSICS_TPS
    timer_label = f"Time {int(cur_time_s // 60):d}:{cur_time_s % 60:05.2f}"
    txt(screen, timer_label, 20, hud_text_y + 20, 14, C_GRAY, shadow=True)
    prev_best_time = int((meta or {}).get("best_time_frames", 0)) if meta else 0
    cps_baseline_y = hud_text_y + 38
    if prev_best_time > 0:
        best_s = prev_best_time / PHYSICS_TPS
        best_label = f"Best {int(best_s // 60):d}:{best_s % 60:05.2f}"
        txt(screen, best_label, 20, hud_text_y + 38, 13, C_SUCCESS, shadow=True)
        cps_baseline_y = hud_text_y + 56
    # Bot CPS / press tally — surfaced in the top-left HUD so the viewer
    # can monitor the bot's input cadence at a glance, independent of any
    # speed/test labels in the corner. The rolling window pops samples
    # older than 1 second so the CPS number reads as instantaneous, not
    # session average.
    if is_sim_run:
        cps_cutoff = attempt_frames - PHYSICS_TPS  # 1-second rolling window
        while bot_press_frames and bot_press_frames[0] < cps_cutoff:
            bot_press_frames.pop(0)
        cps_now = len(bot_press_frames)
        txt(screen, f"CPS {cps_now}  ·  {bot_press_total} presses",
            20, cps_baseline_y, 13, (255, 220, 160), shadow=True)
        if manual_takeover and player.alive and not player.won:
            grace_left = max(0, manual_takeover_grace - takeover_idle_frames)
            txt(screen, f"TAKEOVER · {grace_left / PHYSICS_TPS:.1f}s",
                20, cps_baseline_y + 18, 13, (255, 120, 120), shadow=True)
        elif is_sim_run and player.alive and not player.won:
            txt(screen, "Press P to take over",
                20, cps_baseline_y + 18, 11, (160, 160, 160), shadow=True)
    txt(screen, level_name, WIDTH // 2, 8, 15, C_WHITE, True, shadow=True)
    txt(screen, f"{player.mode.title()} · {player.move_speed:.1f}x",
        WIDTH - 170, 28, 14, C_GRAY, shadow=True)
    if player.noclip:
        txt(screen, "IGNORE DAMAGE", WIDTH - 170, 46, 13, (255, 120, 255), shadow=True)

    # Coin HUD (top-right)
    if total_coins > 0:
        got = len(player.coins_collected)
        coin_y = 52
        for i in range(total_coins):
            cx = WIDTH - 30 - (total_coins - 1 - i) * 28
            filled = i < got
            col = C_COIN if filled else darker(C_COIN, 120)
            pygame.draw.circle(screen, darker(col, 40), (cx + 1, coin_y + 1), 10)
            pygame.draw.circle(screen, col, (cx, coin_y), 10)
            if filled:
                pygame.draw.circle(screen, lighter(C_COIN, 70), (cx, coin_y), 6, 2)
        txt(screen, f"{got}/{total_coins}", WIDTH - 30 - total_coins * 28 - 8,
            coin_y - 8, 14, C_WHITE, shadow=True)

    # Item Counter HUD (Checkpoint 7): a passive readout row per placed
    # Item Counter object, stacked top-right below the coin HUD. Reuses
    # the same `txt()` helper as every other HUD label rather than a new
    # text-rendering pathway; placement position is unused (see the
    # object's own tip in objects.py) since this is a HUD row, not a
    # world-space overlay.
    counter_y = 52 + (28 if total_coins > 0 else 0)
    for o in player.objects:
        if o.get("t") != T_ITEM_COUNTER:
            continue
        cid = int(o.get("item_id", 0))
        if o.get("label") == "Timer":
            val = player.timers.get(cid, 0.0)
            label = f"Timer {cid}: {val:.2f}s"
        else:
            val = player.items.get(cid, 0.0)
            label = f"Item {cid}: {val:g}"
        txt(screen, label, WIDTH - 170, counter_y, 13, C_WHITE, shadow=True)
        counter_y += 18

    # UI Trigger labels (Checkpoint 7): the same HUD pass, the same txt()
    # helper, and the same read-by-id shape as the Item Counter rows just
    # above -- an Item Counter row reads player.items by item id, a UI
    # label reads player.ui_labels by ui id. The only difference is that
    # these are camera-anchored: offset from the screen centre rather than
    # stacked in a corner, which is what "camera-relative custom UI" means
    # once the scope is one text label (see objects.py's T_UI_TRIGGER).
    for entry in player.active_ui_labels():
        txt(screen, entry["text"], WIDTH // 2 + entry["x_offset"],
            HEIGHT // 2 + entry["y_offset"], 22, C_WHITE, True, shadow=True)

    if practice_mode:
        # Stack the CP chip ABOVE the PRACTICE label so the two never
        # collide horizontally — on narrow windows the centred PRACTICE
        # text and the right-anchored chip used to share a row and risked
        # overlap.
        cp_n = len(player.checkpoints)
        cp_label = (f"CP: {cp_n}  ·  C drop · X pop" if cp_n
                    else "CP: 0  ·  press C to drop a checkpoint")
        txt(screen, cp_label, WIDTH - 140, HEIGHT - 46, 12,
            (180, 220, 255) if cp_n else C_GRAY, True, shadow=True)
        txt(screen, "PRACTICE MODE", WIDTH // 2, HEIGHT - 22, 15, (0, 255, 0),
            True, shadow=True)
    # Hint-mode status: a subtle top-left line the player can ignore
    # unless they've opted in by pressing H.
    if hint_visible and hint_path:
        badge = "HINT · bot path"
        if hint_status == "partial":
            badge += " (partial)"
        txt(screen, badge, 20, 78, 13, (255, 200, 80), shadow=True)
    elif hint_path is not None and not hint_visible:
        txt(screen, "HINT off — press H", 20, 78, 12, C_GRAY, shadow=True)
    if editor_test or (practice_mode and
                       test_speed_idx != len(test_speeds) - 1):
        speed_label = ("Test" if editor_test else "Practice")
        txt(screen, f"{speed_label} {test_speeds[test_speed_idx]:.2f}x",
            WIDTH - 110, 26, 15, C_GRAY, shadow=True)
        if bot_controller is not None:
            txt(screen, "BOT", WIDTH // 2 - 220, HEIGHT - 22, 18,
                (255, 180, 60), True, shadow=True)
        elif playback_inputs is not None:
            pb_pct = min(100, int(bot_frame / max(1, len(playback_inputs)) * 100))
            txt(screen, f"PLAYBACK {pb_pct}%", WIDTH // 2 - 220, HEIGHT - 22,
                18, (100, 220, 255), True, shadow=True)
        # Playback desync badge: red alert while current drift is above
        # threshold, dimmer readout of peak drift otherwise so the user
        # always knows whether the replay has drifted even once the
        # trajectory has re-converged.
        if playback_wp_sorted and playback_inputs is not None:
            if desync_alert_timer > 0:
                txt(screen, "DRIFT — replay off-route",
                    WIDTH // 2 + 40, HEIGHT - 42, 14, (255, 110, 110),
                    True, shadow=True)
            if desync_max_px > 2.0:
                txt(screen, f"peak drift {desync_max_px:.0f}px",
                    WIDTH // 2 + 40, HEIGHT - 22, 12,
                    (210, 180, 180), True, shadow=True)
        txt(screen, "[/- slower  ]/= faster  0 reset", WIDTH // 2,
            HEIGHT - 22, 15, C_GRAY, True, shadow=True)


def render_debug_overlay(screen, show_debug, objects, cam_x, cam_y, player,
                          attempts, dbg_frame_times):
    """F3 debug HUD — jump-predictor probe readout if the level has one,
    otherwise a generic FPS/physics-state panel."""
    if show_debug:
        from .jump_predictor import (
            find_probe as pred_find_probe, predict as pred_predict,
            draw_overlay as pred_draw_overlay,
            summary_text as pred_summary_text,
        )
        probe = pred_find_probe(objects)
    else:
        probe = None
    if show_debug and probe is not None:
        pred_result = pred_predict(objects, probe, params=player.params)
        pred_draw_overlay(
            screen, pred_result, cam_x, cam_y, zoom_level=1.0,
            clip_rect=pygame.Rect(0, 0, WIDTH, HEIGHT),
        )
        # Summary panel replaces the normal debug readout.
        lines = [("JUMP PROBE", (255, 235, 120))]
        for ln in pred_summary_text(pred_result):
            lines.append((ln, (210, 230, 255)))
        dbg_w, dbg_h = 300, 16 * len(lines) + 12
        pad = pygame.Rect(WIDTH - dbg_w - 10, HEIGHT - dbg_h - 40, dbg_w, dbg_h)
        bg = pygame.Surface((dbg_w, dbg_h), pygame.SRCALPHA)
        bg.fill((0, 0, 0, 190))
        screen.blit(bg, pad.topleft)
        pygame.draw.rect(screen, (255, 235, 120), pad, 1, border_radius=2)
        for i, (ln, col) in enumerate(lines):
            txt(screen, ln, pad.x + 8, pad.y + 6 + i * 16, 12, col, shadow=True)
    elif show_debug:
        now = _time.perf_counter()
        dbg_frame_times.append(now)
        # Keep only the last ~1 sec of timestamps for FPS calc.
        cutoff = now - 1.0
        while dbg_frame_times and dbg_frame_times[0] < cutoff:
            dbg_frame_times.pop(0)
        fps = (len(dbg_frame_times) - 1) / max(
            0.001, (dbg_frame_times[-1] - dbg_frame_times[0])
            if len(dbg_frame_times) > 1 else 0.001)
        frame_ms = (now - dbg_frame_times[-2]) * 1000 \
            if len(dbg_frame_times) > 1 else 0.0
        lines = [
            (f"FPS {fps:.1f}  ·  {frame_ms:.1f}ms", None),
            (f"pos ({player.x:.1f}, {player.y:.1f})", None),
            (f"vy {player.vy:.2f}  grav {player.grav}", None),
            (f"mode {player.mode}  speed {player.move_speed:.1f}x", None),
            (f"on_ground {player.on_ground}  size {player.size}", None),
            (f"grounded_frames {player.grounded_frames}", None),
            (f"frame {player.frame}  attempts {attempts}", None),
            (f"objects {len(objects)}", None),
        ]
        lj = player.last_jump
        if lj is not None:
            # Colour the readout so the user can eyeball frame-perfect
            # jumps at a glance: green == perfect (landed + acted on the
            # same frame), yellow == 1 frame late, red past that.
            gf = lj["grounded_frames"]
            if gf == 1:
                col = (120, 255, 140)
                tag = "PERFECT"
            elif gf == 2:
                col = (255, 235, 120)
                tag = f"{gf - 1}f late"
            else:
                col = (255, 160, 140)
                tag = f"{gf - 1}f late"
            tap = "tap" if lj["fresh_press"] else "held"
            ago = player.frame - lj["frame"]
            lines.append((
                f"last {lj['kind']}: fr{lj['frame']} "
                f"gnd={gf} {tap} {tag} ({ago}f ago)",
                col,
            ))
        if player.mirror is not None:
            mm = player.mirror
            lines.append((f"mirror y {mm['y']:.1f} vy {mm['vy']:.2f} "
                          f"grav {mm['grav']}", None))
        dbg_w, dbg_h = 300, 14 * len(lines) + 12
        pad = pygame.Rect(WIDTH - dbg_w - 10, HEIGHT - dbg_h - 40, dbg_w, dbg_h)
        bg = pygame.Surface((dbg_w, dbg_h), pygame.SRCALPHA)
        bg.fill((0, 0, 0, 180))
        screen.blit(bg, pad.topleft)
        for i, (ln, col) in enumerate(lines):
            txt(screen, ln, pad.x + 8, pad.y + 6 + i * 14,
                11, col if col else (180, 240, 180))


def render_state_hud(screen, show_state, player):
    """Toggle-I panel: mode / speed / size / gravity / dual / time / pos."""
    if not show_state:
        return
    from .constants import (
        MODE_CUBE as MC, MODE_SHIP as MS, MODE_BALL as MB,
        MODE_WAVE as MW, MODE_UFO as MU, MODE_SPIDER as MSP,
        MODE_SWING as MSW, MODE_ROBOT as MR,
        MINI_PLAYER_SIZE_UNITS as MINI,
        C_MODE_CUBE as C_CUBE, C_MODE_SHIP as C_SHIP, C_MODE_BALL as C_BALL,
        C_MODE_WAVE as C_WAVE, C_MODE_UFO as C_UFO, C_MODE_SPIDER as C_SPIDER,
        C_MODE_SWING as C_SWING, C_MODE_ROBOT as C_ROBOT,
    )
    mode_labels = {
        MC: "Cube", MS: "Ship", MB: "Ball", MW: "Wave",
        MU: "UFO", MSP: "Spider", MSW: "Swing", MR: "Robot",
    }
    mode_colors = {
        MC: C_CUBE, MS: C_SHIP, MB: C_BALL, MW: C_WAVE,
        MU: C_UFO, MSP: C_SPIDER, MSW: C_SWING, MR: C_ROBOT,
    }
    mode_label = mode_labels.get(player.mode, str(player.mode))
    mode_col = mode_colors.get(player.mode, (200, 220, 240))
    base_speed = float(player.params.base_move_speed)
    # Speed multiplier relative to the level's base speed — what a level
    # author thinks of as "1.0x / 1.35x / 1.65x".
    speed_mult = (player.move_speed / base_speed if base_speed > 0 else 1.0)
    size_label = ("Mini" if int(player.size) == int(MINI) else "Normal")
    grav_label = "Flipped" if player.grav < 0 else "Normal"
    dual_label = "ON" if player.mirror is not None else "off"
    tw = float(getattr(player, "time_warp", 1.0))
    # Highlight non-default values so the user can scan the panel and
    # immediately spot what's NOT vanilla here.
    neutral = (210, 220, 235)
    accent = (255, 220, 120)
    speed_col = neutral if abs(speed_mult - 1.0) < 0.01 else accent
    size_col = neutral if size_label == "Normal" else accent
    grav_col = neutral if grav_label == "Normal" else accent
    dual_col = neutral if player.mirror is None else accent
    tw_col = neutral if abs(tw - 1.0) < 0.01 else accent
    from .constants import UNITS_PER_BLOCK
    cell_x = int(player.x // UNITS_PER_BLOCK)
    state_lines = [
        ("Mode",     mode_label,                     mode_col),
        ("Speed",    f"{speed_mult:.2f}x",           speed_col),
        ("Size",     size_label,                     size_col),
        ("Gravity",  grav_label,                     grav_col),
        ("Dual",     dual_label,                     dual_col),
        ("Time",     f"{tw:.2f}x",                   tw_col),
        ("Pos",      f"x={player.x_px:.0f} (cell {cell_x})", neutral),
    ]
    sw, sh = 220, 14 * len(state_lines) + 30
    sx0 = WIDTH - sw - 10
    sy0 = 10
    sbg = pygame.Surface((sw, sh), pygame.SRCALPHA)
    sbg.fill((0, 0, 0, 180))
    screen.blit(sbg, (sx0, sy0))
    pygame.draw.rect(screen, (90, 110, 140),
                     pygame.Rect(sx0, sy0, sw, sh), 1, border_radius=2)
    txt(screen, "LEVEL STATE  [I]", sx0 + 10, sy0 + 6, 11,
        (180, 200, 230), shadow=True)
    for i, (label, value, col) in enumerate(state_lines):
        row_y = sy0 + 24 + i * 14
        txt(screen, label, sx0 + 10, row_y, 12, (160, 175, 200))
        txt(screen, value, sx0 + 78, row_y, 12, col, shadow=True)


def render_pause_overlay(screen, paused, mpos, attempts, player, max_x,
                          practice_mode, pause_menu_buttons):
    """Pause menu. Returns (r_mute_music, r_mute_sfx) hit-test rects —
    empty rects when not paused, so a stale rect can't catch a click."""
    if not paused:
        return pygame.Rect(0, 0, 0, 0), pygame.Rect(0, 0, 0, 0)
    ov = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    ov.fill((0, 0, 0, 180))
    screen.blit(ov, (0, 0))
    txt(screen, "PAUSED", WIDTH // 2, HEIGHT // 2 - 140, 56, C_PLAYER, True)
    # Status sub-line: show attempt count + current % so the pause menu
    # is informative, not just a cover (QoL B5).
    pct = int(max(0.0, min(1.0, player.x / max_x)) * 100)
    txt(screen, f"Attempt {attempts}  ·  {pct}%",
        WIDTH // 2, HEIGHT // 2 - 100, 16, C_GRAY, True)
    btn(screen, "Resume", pause_menu_buttons["resume"].centerx,
        pause_menu_buttons["resume"].centery, 220, 48, C_BTN, mpos)
    btn(screen, "Restart", pause_menu_buttons["restart"].centerx,
        pause_menu_buttons["restart"].centery, 220, 48, C_BTN, mpos)
    practice_label = "Practice: ON" if practice_mode else "Practice: OFF"
    practice_col = C_SUCCESS if practice_mode else C_BTN
    btn(screen, practice_label, pause_menu_buttons["practice_toggle"].centerx,
        pause_menu_buttons["practice_toggle"].centery, 220, 48, practice_col, mpos)
    btn(screen, "Settings", pause_menu_buttons["settings"].centerx,
        pause_menu_buttons["settings"].centery, 220, 48, (80, 100, 160), mpos)
    btn(screen, "Main Menu", pause_menu_buttons["menu"].centerx,
        pause_menu_buttons["menu"].centery, 220, 48, C_DANGER, mpos)
    # Mute toggles — bottom row, centered below menu button
    r_mute_music = icon_button(
        screen, speaker_icon(22, music.is_muted()),
        WIDTH // 2 - 30, HEIGHT // 2 + 220, 44, 44, C_BTN, mpos,
        active=music.is_muted(),
    )
    r_mute_sfx = icon_button(
        screen, speaker_icon(20, sfx.is_muted()),
        WIDTH // 2 + 30, HEIGHT // 2 + 220, 44, 44, (80, 60, 140), mpos,
        active=sfx.is_muted(),
    )
    txt(screen, "Music", r_mute_music.centerx, r_mute_music.bottom + 4,
        11, C_GRAY, True)
    txt(screen, "SFX", r_mute_sfx.centerx, r_mute_sfx.bottom + 4, 11,
        C_GRAY, True)
    txt(screen, "M: mute music  ·  N: mute SFX  ·  H: toggle hint path",
        WIDTH // 2, HEIGHT // 2 + 280, 13, C_GRAY, True)
    return r_mute_music, r_mute_sfx


def render_win_overlay(screen, player, mpos, win_sfx_played, level_music,
                        meta, attempts, deaths_this_session, attempt_frames,
                        total_coins, meta_persisted, is_sim_run,
                        rc_menu, rc_replay, on_first_win):
    """Win screen. ``on_first_win`` is called once (SFX + persist) the
    first frame ``player.won`` is seen. Returns the new ``win_sfx_played``."""
    if not player.won:
        return win_sfx_played
    if not win_sfx_played:
        sfx.play("win", 0.6)
        win_sfx_played = True
        if level_music:
            music.fadeout(1500)
        on_first_win()
    ov = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    ov.fill((0, 0, 0, 160))
    screen.blit(ov, (0, 0))
    txt(screen, "LEVEL COMPLETE!", WIDTH // 2, HEIGHT // 2 - 110, 54,
        C_PLAYER, True)
    # Stats panel: attempts, deaths, time, best time, coins.
    cur_time_s_win = attempt_frames / PHYSICS_TPS
    cur_time_str = (f"{int(cur_time_s_win // 60):d}:"
                    f"{cur_time_s_win % 60:05.2f}")
    best_t_frames = int((meta or {}).get("best_time_frames", 0)) if meta else 0
    best_str = "—"
    if best_t_frames > 0:
        bts = best_t_frames / PHYSICS_TPS
        best_str = f"{int(bts // 60):d}:{bts % 60:05.2f}"
    row_y = HEIGHT // 2 - 50
    txt(screen, f"Attempts: {attempts}", WIDTH // 2 - 130, row_y, 20,
        C_WHITE, True)
    txt(screen, f"Deaths: {deaths_this_session}", WIDTH // 2 + 130, row_y,
        20, C_DANGER, True)
    txt(screen, f"Time: {cur_time_str}", WIDTH // 2 - 130, row_y + 28, 20,
        C_WHITE, True)
    txt(screen, f"Best: {best_str}", WIDTH // 2 + 130, row_y + 28, 20,
        C_SUCCESS, True)
    if total_coins > 0:
        coins = len(player.coins_collected)
        colour = C_COIN if coins == total_coins else C_GRAY
        txt(screen, f"Coins: {coins} / {total_coins}", WIDTH // 2,
            row_y + 60, 22, colour, True)
    if meta_persisted:
        txt(screen, "Verified!", WIDTH // 2, row_y + 90, 18, C_SUCCESS, True)
    elif is_sim_run:
        txt(screen, "(Bot run -- not verified)", WIDTH // 2,
            row_y + 90, 16, C_GRAY, True)
    btn(screen, "Menu", rc_menu.centerx, rc_menu.centery, rc_menu.w,
        rc_menu.h, C_BTN, mpos)
    btn(screen, "Replay", rc_replay.centerx, rc_replay.centery,
        rc_replay.w, rc_replay.h, C_SUCCESS, mpos)
    return win_sfx_played
