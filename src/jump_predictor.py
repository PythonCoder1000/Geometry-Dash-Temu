"""Headless trajectory preview for the editor's T_JUMP_PREDICTOR probe.

Given a level's object list and a probe dict, simulates a single "click"
(jump for cube, gravity flip for ball, thrust for ship, flap for UFO,
teleport for spider, wave up for wave) and returns the resulting arc so
the editor can draw it and say whether the click clears the next
obstacle.

The probe is always stripped from the simulated object list — the probe
is an editor annotation, not a real object — so the player never
collides with it.

The predictor deliberately reuses the real `SimPlayer` rather than a
hand-rolled arc formula: orbs, pads, portals, gravity, and scaled
blocks all affect the trajectory, and re-deriving that physics by hand
would drift from real gameplay the moment the engine changed.
"""

from __future__ import annotations

from typing import Optional

from .constants import (
    CELL, PLAYER_SIZE, MINI_PLAYER_SIZE, T_JUMP_PREDICTOR,
    MODE_CUBE, MODE_SHIP, MODE_BALL, MODE_WAVE, MODE_UFO, MODE_SPIDER,
    MODE_SWING, MODE_ROBOT,
    T_BLOCK, T_SLAB,
    T_SPEED_SLOW, T_SPEED_NORMAL, T_SPEED_FAST, T_SPEED_FASTER,
    T_MODE_CUBE, T_MODE_SHIP, T_MODE_BALL, T_MODE_WAVE, T_MODE_UFO,
    T_MODE_SPIDER, T_MODE_MINI, T_MODE_BIG,
    SPEED_VALUES, MODE_FROM_TYPE,
)

# Keep predictor cost bounded: long wave / ship flights just show a
# truncated arc rather than hanging the editor main thread.
#
# The horizon scales with the user's simulation TPS so the probe always
# covers the same real-time window (currently 3 seconds) regardless of
# what the sim-rate setting is — raising TPS means finer per-tick
# physics resolution and proportionally more probe ticks to cover the
# same span. Falls back to 180 if the settings module isn't importable
# (headless pytest runs, import-time probes in the bots).
_PROBE_SECONDS = 3.0
_PROBE_FALLBACK_FRAMES = 180


def _probe_max_frames():
    try:
        from . import settings as _settings
        tps = int(_settings.get_tps())
    except Exception:
        return _PROBE_FALLBACK_FRAMES
    return max(30, int(_PROBE_SECONDS * tps))

# Modes that read "input_held" every frame (ship thrust, wave up). For
# these we keep the button held across the whole simulation so the
# preview shows what happens if the user holds the click — which is the
# natural interpretation for those modes. Single-pulse modes (cube
# jump, ball flip, UFO flap, spider teleport) release after frame 0.
_HELD_MODES = {MODE_SHIP, MODE_WAVE, MODE_ROBOT}

_ALL_MODES = [MODE_CUBE, MODE_SHIP, MODE_BALL, MODE_WAVE, MODE_UFO,
              MODE_SPIDER, MODE_SWING, MODE_ROBOT]

# Snap search distance — look for a floor / ceiling in this many cells
# around the probe so the simulated player rests on it naturally. 3
# cells is enough to cover any reasonable probe placement without
# snapping to a far-away surface that wasn't the author's intent.
_SNAP_SEARCH_CELLS = 3


def find_probe(objects):
    """Return the single probe dict in ``objects`` (or None)."""
    for o in objects:
        if o["t"] == T_JUMP_PREDICTOR:
            return o
    return None


def modes():
    """Stable ordering used by the edit-panel mode cycler."""
    return list(_ALL_MODES)


def detect_speed(objects, probe_x_cell: int) -> float:
    """Return the move_speed in px/frame at ``probe_x_cell`` after
    applying every speed portal to the left of it. Matches the real
    engine, which latches the most recent portal crossed."""
    speed = SPEED_VALUES.get(T_SPEED_NORMAL, 5.0)
    # Iterate in x-order so the latest-latched speed wins.
    ports = sorted(
        (o for o in objects
         if o.get("t") in SPEED_VALUES and int(o["x"]) <= probe_x_cell),
        key=lambda o: int(o["x"]),
    )
    for p in ports:
        speed = SPEED_VALUES[p["t"]]
    return speed


def detect_mode(objects, probe_x_cell: int) -> str:
    """Return the player mode at ``probe_x_cell`` based on the most
    recent mode portal to the left of it. Defaults to cube."""
    mode = MODE_CUBE
    ports = sorted(
        (o for o in objects
         if o.get("t") in MODE_FROM_TYPE and int(o["x"]) <= probe_x_cell),
        key=lambda o: int(o["x"]),
    )
    for p in ports:
        mode = MODE_FROM_TYPE[p["t"]]
    return mode


def detect_mini(objects, probe_x_cell: int) -> bool:
    """True if the last size portal to the left of the probe was a mini."""
    is_mini = False
    ports = sorted(
        (o for o in objects
         if o.get("t") in (T_MODE_MINI, T_MODE_BIG)
         and int(o["x"]) <= probe_x_cell),
        key=lambda o: int(o["x"]),
    )
    for p in ports:
        is_mini = (p["t"] == T_MODE_MINI)
    return is_mini


def _solid_rect(obj):
    """Minimal solid-rect resolver — the predictor only cares about
    landable surfaces, and we deliberately skip the rotation/scale
    complexity of graphics.slab_rect (it pulls pygame). A rotated slab
    still snaps to its own cell row, which is accurate for the common
    'top-half slab on the floor' case the author actually probes."""
    t = obj.get("t")
    if t == T_BLOCK:
        gx = int(obj["x"])
        gy = int(obj["y"])
        return (gx * CELL, gy * CELL, CELL, CELL)
    if t == T_SLAB:
        gx = int(obj["x"])
        gy = int(obj["y"])
        r = int(obj.get("r", 0)) % 360
        # Local offsets match graphics._SLAB_LOCAL so the physics-side
        # collision surface is what we snap to.
        if r == 0:
            lx, ly, lw, lh = 0, CELL // 2, CELL, CELL // 2
        elif r == 180:
            lx, ly, lw, lh = 0, 0, CELL, CELL // 2
        elif r == 90:
            lx, ly, lw, lh = 0, 0, CELL // 2, CELL
        else:
            lx, ly, lw, lh = CELL // 2, 0, CELL // 2, CELL
        return (gx * CELL + lx, gy * CELL + ly, lw, lh)
    return None


def _snap_spawn_y(objects, probe_gx: int, probe_gy: int,
                  grav: int, size: int) -> float:
    """Rest the simulated player on whichever solid surface is nearest
    in the gravity direction, so the arc starts at the same y the real
    player would have after standing in that cell. If no surface is
    within ``_SNAP_SEARCH_CELLS``, fall back to the cell's vertical
    center — the probe is mid-air and the click will behave like a
    mid-air click (no-op for cube/ball/spider)."""
    # Player's x-span in pixels (centered on the probe cell). Any block
    # whose x-range overlaps this column counts as "below" / "above".
    px_left = probe_gx * CELL + (CELL - size) / 2.0
    px_right = px_left + size
    best = None
    for o in objects:
        rect = _solid_rect(o)
        if rect is None:
            continue
        rx, ry, rw, rh = rect
        # Horizontal overlap gate.
        if rx + rw <= px_left or rx >= px_right:
            continue
        cell_dy = int(o["y"]) - probe_gy
        if grav == 1:
            if cell_dy <= 0 or cell_dy > _SNAP_SEARCH_CELLS:
                continue
            resting_y = ry - size
            dist = cell_dy
        else:
            # Gravity up: look for ceilings above. The player rests with
            # y = bottom-of-ceiling.
            if cell_dy >= 0 or -cell_dy > _SNAP_SEARCH_CELLS:
                continue
            resting_y = ry + rh
            dist = -cell_dy
        if best is None or dist < best[0]:
            best = (dist, resting_y)
    if best is None:
        return probe_gy * CELL + (CELL - size) / 2.0
    return float(best[1])


def predict(objects, probe, params=None):
    """Simulate one click at ``probe``'s cell; return a result dict.

    ``params`` should be the level's :class:`~src.physics.PhysicsParams`
    (from ``meta["physics"]``) so the probe matches the physics the real
    playthrough uses; ``None`` falls back to vanilla defaults.

    Returned keys:
      ``samples``     list of (x_px, y_px, size_px) per simulated frame
      ``landing``     (x_px, y_px, frame) if the sim landed, else None
      ``hit``         (x_px, y_px, reason, frame) if the sim died, else None
      ``mode``        mode string actually used
      ``spawn``       (x_px, y_px) the simulated player's starting top-left
      ``size``        the player's size in pixels (44 or 24 for mini)
      ``frames``      number of frames simulated (<= _probe_max_frames())

    Returns None if the probe is missing, malformed, or the level has
    no objects at all (cold level — nothing to land on).
    """
    if probe is None or probe.get("t") != T_JUMP_PREDICTOR:
        return None
    # Import locally so the constants-only consumers don't drag pygame
    # (via bots.sim → player → graphics) into cold-path code paths.
    from .bots.sim import SimPlayer

    mode = probe.get("mode", MODE_CUBE)
    if mode not in _ALL_MODES:
        mode = MODE_CUBE
    grav = 1 if int(probe.get("grav", 1)) >= 0 else -1
    mini = bool(probe.get("mini", False))
    size = MINI_PLAYER_SIZE if mini else PLAYER_SIZE
    dx_px = int(probe.get("dx", 0))
    dy_px = int(probe.get("dy", 0))
    gx = int(probe["x"])
    gy = int(probe["y"])
    # Strip the probe from the world so the simulated player can't
    # collide with or react to it. SimPlayer needs at least one object
    # to size its grid; if the caller passed an empty world, bail.
    world = [o for o in objects if o.get("t") != T_JUMP_PREDICTOR]
    if not world:
        return None
    # Spawn: centered in the probe cell horizontally, and rested on the
    # nearest solid surface vertically so the arc actually starts where
    # the player would be standing. Without the snap, the spawn floats
    # ~3 px above the real resting y and the arc visibly disagrees with
    # real gameplay. The sub-cell nudge is applied last so the author's
    # ±1 px tweaks ride on top of the snap.
    spawn_x = gx * CELL + (CELL - size) / 2.0 + dx_px
    spawn_y = _snap_spawn_y(world, gx, gy, grav, size) + dy_px
    snapped = abs((spawn_y - dy_px) - (gy * CELL + (CELL - size) / 2.0)) > 0.5

    # Apply the speed portal chain up to the probe's x so 1.35x / 1.65x
    # sections aren't secretly simulated at 1.0x (the single biggest
    # source of "not accurate at all" in earlier passes).
    detected_speed = detect_speed(world, gx)

    sim = SimPlayer(world, params=params)
    sim.mode = mode
    sim.grav = grav
    sim.size = size
    sim.move_speed = detected_speed
    sim.x = float(spawn_x)
    sim.y = float(spawn_y)
    sim.vy = 0.0
    # Only force on_ground when we actually snapped to a surface. In
    # mid-air placements the sim should behave like a mid-air click —
    # cube/ball/spider go quiet, ship/wave/ufo still react.
    sim.on_ground = snapped
    # _x_at_frame_start is read during end-wall crossing checks; without
    # re-seeding, the sim thinks the player warped from x=0.
    sim._x_at_frame_start = sim.x
    sim._was_on_ground = snapped
    # Prevent the probe's initial position from being flagged as a
    # finish-wall crossing when the probe sits past an existing T_END.
    sim._end_walls_x = []

    hold = mode in _HELD_MODES

    samples = [(sim.x, sim.y, sim.size)]
    # Per-substep hitbox trace — Player.update appends one entry to
    # this list at every collision-check point (each inner substep,
    # plus teleport brackets), so the density scales naturally with
    # COLLISION_SUBSTEP_PX. The editor uses it for the probe's
    # "Show Hitbox" overlay so authors see exactly where the
    # predicted arc is collision-tested.
    sim.hitbox_trace = []
    landing = None
    hit = None
    for i in range(_probe_max_frames()):
        is_first = (i == 0)
        input_pressed = is_first
        input_held = True if (is_first or hold) else False
        sim.update(input_held, input_pressed)
        samples.append((sim.x, sim.y, sim.size))
        if not sim.alive:
            hit = (sim.x, sim.y, sim.death_reason or "Died", sim.frame)
            break
        # Landing only counts after the initial click has taken us off
        # the ground — otherwise frame-1 grounded state (= we never
        # left) would instantly close the arc at the spawn point.
        if not is_first and sim.on_ground:
            landing = (sim.x, sim.y, sim.frame)
            break
    return {
        "samples": samples,
        "hitboxes": list(sim.hitbox_trace),
        "landing": landing,
        "hit": hit,
        "mode": mode,
        "spawn": (spawn_x, spawn_y),
        "size": size,
        "frames": len(samples) - 1,
        "speed": detected_speed,
        "grounded": snapped,
    }


def nudge_fine_px() -> int:
    """Per-click fine nudge — pixel-exact so the author can probe the
    literal single-pixel timing window that earns a frame-perfect tag."""
    return 1


def nudge_coarse_px() -> int:
    """Per-click coarse nudge — ~1 frame at base speed. Used for fast
    re-aiming of the probe when the author is still ballparking the
    right cell before fine-tuning with the 1 px buttons."""
    from .physics import DEFAULT_PARAMS
    return max(1, int(round(DEFAULT_PARAMS.base_move_speed)))


def next_mode(current: str, delta: int = 1) -> str:
    try:
        idx = _ALL_MODES.index(current)
    except ValueError:
        idx = 0
    return _ALL_MODES[(idx + delta) % len(_ALL_MODES)]


def draw_overlay(screen, result, cam_x, cam_y, zoom_level=1.0,
                 clip_rect=None, show_hitbox=False):
    """Render a predictor arc + end marker over the current canvas.

    Shared by the editor (zoomed canvas) and play mode (no zoom, fixed
    CELL size — pass zoom_level=1.0). World-pixel samples are projected
    through the caller's camera transform. The caller usually sets
    ``clip_rect`` to the canvas band so arcs flying off-screen don't
    scribble over the palette / bottom HUD.

    ``show_hitbox`` (default False) overlays the per-substep hitbox
    samples captured by the simulator — same shape as the editor's
    H-key trace but recorded inside this single probe sim. Useful for
    visually confirming a frame-perfect arc clears every spike on the
    way.
    """
    import pygame
    if result is None:
        return
    samples = result["samples"]
    if len(samples) < 2:
        return
    prev_clip = screen.get_clip()
    if clip_rect is not None:
        screen.set_clip(clip_rect)
    try:
        # Centre the arc on the player's midpoint so the line tracks
        # motion rather than the top-left corner jumping ~22px per frame.
        screen_pts = [
            (int((x + sz / 2.0) * zoom_level - cam_x),
             int((y + sz / 2.0) * zoom_level - cam_y))
            for (x, y, sz) in samples
        ]
        # Simulated spawn box — dashed rect at the first sample so the
        # author can visually verify where the sim actually starts,
        # catching "the probe cell looks right but the sim starts off"
        # drift at a glance. Pale yellow to match the probe sprite.
        sx, sy, sz = samples[0]
        ssz = max(1, int(sz * zoom_level))
        sbx = int(sx * zoom_level - cam_x)
        sby = int(sy * zoom_level - cam_y)
        dash = 4
        for dx in range(0, ssz, dash * 2):
            pygame.draw.line(screen, (255, 235, 120),
                             (sbx + dx, sby),
                             (sbx + min(dx + dash, ssz), sby), 1)
            pygame.draw.line(screen, (255, 235, 120),
                             (sbx + dx, sby + ssz),
                             (sbx + min(dx + dash, ssz), sby + ssz), 1)
        for dy in range(0, ssz, dash * 2):
            pygame.draw.line(screen, (255, 235, 120),
                             (sbx, sby + dy),
                             (sbx, sby + min(dy + dash, ssz)), 1)
            pygame.draw.line(screen, (255, 235, 120),
                             (sbx + ssz, sby + dy),
                             (sbx + ssz, sby + min(dy + dash, ssz)), 1)
        # Per-substep hitbox samples — drawn UNDER the arc line so the
        # cyan polyline still reads on top. Outer rect is the full
        # collision footprint; inner rect is the shrunk hazard hitbox
        # (matches the player's spike/saw check). Colours match the
        # editor's H-overlay scheme: green outer, red inner.
        if show_hitbox:
            hb = result.get("hitboxes") or []
            # Trace samples are 4-tuples (x, y, size, angle) with the
            # angle field added when the inner/outer split landed; older
            # builds stored 3-tuples (x, y, size). Tolerate both so a
            # mixed workspace doesn't crash the editor overlay.
            for sample in hb:
                if len(sample) >= 4:
                    hx, hy, hsz, _ = sample[:4]
                else:
                    hx, hy, hsz = sample[:3]
                ssz = max(1, int(hsz * zoom_level))
                sxh = int(hx * zoom_level - cam_x)
                syh = int(hy * zoom_level - cam_y)
                pygame.draw.rect(
                    screen, (120, 255, 140),
                    (sxh, syh, ssz, ssz), 1)
                shrink = max(2, int(6 * hsz / 44.0))
                ssh = max(1, int(shrink * zoom_level))
                inner_sz = max(1, ssz - 2 * ssh)
                pygame.draw.rect(
                    screen, (90, 160, 255),  # blue inner — matches editor overlay
                    (sxh + ssh, syh + ssh, inner_sz, inner_sz), 1)
        # Trail: mid-cyan polyline with soft shadow for legibility
        # against busy backgrounds (e.g. a wall of blocks).
        pygame.draw.lines(screen, (0, 0, 0), False, screen_pts, 4)
        pygame.draw.lines(screen, (120, 230, 255), False, screen_pts, 2)
        # Frame dots every ~6 frames so the user can eyeball timing:
        # denser spacing == slower motion (e.g. wave apex).
        for i in range(0, len(screen_pts), 6):
            pygame.draw.circle(screen, (220, 240, 255), screen_pts[i], 2)
        end = screen_pts[-1]
        if result["hit"]:
            # Red X. Drawn a little larger than the landing dot so the
            # failure case is the eye-catching one.
            sz = 10
            pygame.draw.line(screen, (20, 0, 0),
                             (end[0] - sz, end[1] - sz),
                             (end[0] + sz, end[1] + sz), 5)
            pygame.draw.line(screen, (20, 0, 0),
                             (end[0] - sz, end[1] + sz),
                             (end[0] + sz, end[1] - sz), 5)
            pygame.draw.line(screen, (255, 80, 80),
                             (end[0] - sz, end[1] - sz),
                             (end[0] + sz, end[1] + sz), 3)
            pygame.draw.line(screen, (255, 80, 80),
                             (end[0] - sz, end[1] + sz),
                             (end[0] + sz, end[1] - sz), 3)
        elif result["landing"]:
            pygame.draw.circle(screen, (0, 0, 0), end, 9)
            pygame.draw.circle(screen, (120, 255, 140), end, 7)
            pygame.draw.circle(screen, (240, 255, 240), end, 3)
        else:
            pygame.draw.circle(screen, (0, 0, 0), end, 8)
            pygame.draw.circle(screen, (255, 200, 80), end, 6, 2)
    finally:
        screen.set_clip(prev_clip)


def summary_text(result: Optional[dict]) -> list[str]:
    """Human-readable breakdown of a `predict()` result for the HUD."""
    if result is None:
        return ["(no probe / empty level)"]
    sz_lbl = "mini" if result["size"] == MINI_PLAYER_SIZE else "normal"
    out = [f"mode: {result['mode']}  size: {sz_lbl}  "
           f"speed: {result['speed']:.2f}px/f"]
    sp = result["spawn"]
    ground_lbl = "grounded" if result["grounded"] else "mid-air"
    out.append(f"spawn: ({sp[0]:.0f}, {sp[1]:.0f}) · {ground_lbl}")
    if result["hit"]:
        hx, hy, reason, fr = result["hit"]
        out.append(f"HIT @ f{fr}: {reason}")
        out.append(f"  at ({hx:.0f}, {hy:.0f})")
    elif result["landing"]:
        lx, ly, fr = result["landing"]
        out.append(f"LAND @ f{fr}: ({lx:.0f}, {ly:.0f})")
    else:
        out.append(f"open after {result['frames']}f (no land, no hit)")
    return out
