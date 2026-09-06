"""Physics / state for the player.

The player owns the object list for the current play session (it mutates
positions for move triggers and tracks which orbs/portals have been
consumed). One instance per attempt — call ``reset()`` between tries.
"""

import math

import pygame

from .constants import (
    CELL, WIDTH, HEIGHT, PLAYER_SIZE, MINI_PLAYER_SIZE, PLAYER_START_GX,
    MODE_CUBE, MODE_SHIP, MODE_BALL, MODE_WAVE, MODE_UFO, MODE_SPIDER,
    MODE_SWING, MODE_ROBOT, MODE_FROM_TYPE, SPEED_VALUES, PLAYER_COLORS,
    PLAYER_ICONS,
    T_BLOCK, T_SLAB, T_SLOPE, T_SPIKE, T_HALF_SPIKE, T_SAW,
    T_ORB, T_DASH_ORB, T_TELEPORT_ORB, T_BLACK_ORB, T_BLUE_ORB, T_GREEN_ORB,
    T_SPIDER_ORB, T_RED_ORB, T_PINK_ORB,
    T_PAD, T_BLUE_PAD, T_GRAV_UP, T_GRAV_DOWN, T_END, T_START, T_COIN,
    T_MODE_MINI, T_MODE_BIG, T_MODE_DUAL, T_MODE_SOLO,
    T_CAMERA_TRIGGER, T_BG_TRIGGER, T_MOVE_TRIGGER, T_COLOR_TRIGGER,
    T_PULSE_TRIGGER, T_ROTATE_TRIGGER, T_FOLLOW_TRIGGER, T_TIME_WARP,
    C_PLAYER, C_DASH_ORB, C_PAD, C_MODE_WAVE, C_MODE_UFO, C_MODE_SPIDER,
    C_MODE_SWING, C_MODE_ROBOT,
    DEFAULT_MOVE_CURVE, PAD_TYPES, ORB_TYPES, SOLID_TYPES,
    COLLISION_SUBSTEP_PX, SOLID_HITBOX_FRACTION,
)
from .graphics import (
    cell_rect, slab_rect, spike_hitboxes, pad_trigger_rect, saw_hitbox,
    obj_scale,
    lighter, darker, clamp, draw_cube_icon_glyph,
)
from .levels import get_group_id
from .physics import PhysicsParams, DEFAULT_PARAMS
from . import settings
# ---------------------------------------------------------------------------
# Move-trigger timing curve integration
# ---------------------------------------------------------------------------

def _curve_progress(curve, total_area, t):
    """Integrate the speed curve up to time t, normalised to [0,1]."""
    if not curve or len(curve) < 2 or total_area <= 1e-9:
        return t
    if t <= 0.0:
        return 0.0
    if t >= 1.0:
        return 1.0
    area = 0.0
    for i in range(len(curve) - 1):
        t0, s0 = curve[i]
        t1, s1 = curve[i + 1]
        if t >= t1:
            area += (t1 - t0) * (s0 + s1) * 0.5
            continue
        if t <= t0:
            break
        span = t1 - t0
        if span <= 1e-9:
            continue
        frac = (t - t0) / span
        s_at = s0 + (s1 - s0) * frac
        area += (t - t0) * (s0 + s_at) * 0.5
        break
    return max(0.0, min(1.0, area / total_area))


# ---------------------------------------------------------------------------
# Rotated hitbox helpers (Oriented Bounding Box)
# ---------------------------------------------------------------------------
# These let the player's outer / inner hitboxes track the visual
# rotation (spider mid-air, ball roll, ship pitch) so a tilted player
# doesn't have a phantom-shaped kill volume that misses what the eye
# clearly sees as a hit.
#
# OBB representation: a list of four (x, y) corners in world space,
# wound clockwise from top-left. SAT only needs the two unique edge
# normals of a rectangle (x and y axis after rotation), so we don't
# enumerate four axes — just the two from the rotated rect plus the
# two world-axis ones from the AABB (which collapse to the same two
# in the AABB case, leaving us with three unique axes total).

def _obb_corners(x, y, size, angle_deg, scale):
    """Build the four corners of a square hitbox of side
    ``size * scale`` centred on (x + size/2, y + size/2) and rotated
    ``angle_deg`` degrees clockwise (matches pygame's screen-y-down
    rotation convention used by the player draw code).
    """
    # Negative because pygame draws with positive angle = CCW visually
    # but the player's `self.angle` is treated as a CW rotation in
    # rendering. Negating keeps the OBB visually aligned with the
    # rendered sprite.
    rad = -angle_deg * 0.017453292519943295
    cs = math.cos(rad)
    sn = math.sin(rad)
    cx = x + size * 0.5
    cy = y + size * 0.5
    h = size * 0.5 * scale
    # Local corners (-h,-h) (h,-h) (h,h) (-h,h) → rotate around centre.
    out = []
    for ox, oy in ((-h, -h), (h, -h), (h, h), (-h, h)):
        out.append((cx + ox * cs - oy * sn,
                    cy + ox * sn + oy * cs))
    return out


def _project_aabb(min_v, max_v, axis_x, axis_y, points):
    """Project AABB-aligned points onto an axis. Used by SAT below."""
    pmin = points[0][0] * axis_x + points[0][1] * axis_y
    pmax = pmin
    for px, py in points[1:]:
        v = px * axis_x + py * axis_y
        if v < pmin:
            pmin = v
        elif v > pmax:
            pmax = v
    return pmin, pmax


def _obb_aabb_overlap(obb_corners, ax_left, ax_top, ax_right, ax_bottom):
    """Separating Axis Theorem: returns True if the rotated rect and
    the AABB overlap. Tests three unique axes:
      * world X (AABB normal 1)
      * world Y (AABB normal 2)
      * the OBB's rotated X axis (which gives both OBB normals at
        once for a rectangle, since its Y axis is just the same
        thing rotated 90° — projecting onto one and onto its
        perpendicular covers both).
    """
    # AABB corners.
    aabb_pts = ((ax_left, ax_top), (ax_right, ax_top),
                (ax_right, ax_bottom), (ax_left, ax_bottom))
    # Axis 1: world X (AABB).
    obb_min_x = obb_corners[0][0]
    obb_max_x = obb_min_x
    for cx, _ in obb_corners[1:]:
        if cx < obb_min_x:
            obb_min_x = cx
        elif cx > obb_max_x:
            obb_max_x = cx
    if obb_max_x < ax_left or obb_min_x > ax_right:
        return False
    # Axis 2: world Y (AABB).
    obb_min_y = obb_corners[0][1]
    obb_max_y = obb_min_y
    for _, cy in obb_corners[1:]:
        if cy < obb_min_y:
            obb_min_y = cy
        elif cy > obb_max_y:
            obb_max_y = cy
    if obb_max_y < ax_top or obb_min_y > ax_bottom:
        return False
    # Axis 3 + 4: the OBB's two rotated normals. Compute from the first
    # two corners — that edge gives the X-axis normal; rotate 90° for
    # the Y normal. Both axes are unit vectors so projections are
    # signed scalars on the axis line.
    ex = obb_corners[1][0] - obb_corners[0][0]
    ey = obb_corners[1][1] - obb_corners[0][1]
    inv_len = (ex * ex + ey * ey) ** 0.5
    if inv_len == 0.0:
        return True  # degenerate OBB (size 0) — defer to the AABB tests
    inv_len = 1.0 / inv_len
    nx1 = ex * inv_len
    ny1 = ey * inv_len
    nx2 = -ny1
    ny2 = nx1
    # Project both shapes onto axis 3.
    obb_a, obb_b = _project_aabb(0.0, 0.0, nx1, ny1, obb_corners)
    aabb_a, aabb_b = _project_aabb(0.0, 0.0, nx1, ny1, aabb_pts)
    if obb_b < aabb_a or obb_a > aabb_b:
        return False
    # Axis 4.
    obb_a, obb_b = _project_aabb(0.0, 0.0, nx2, ny2, obb_corners)
    aabb_a, aabb_b = _project_aabb(0.0, 0.0, nx2, ny2, aabb_pts)
    if obb_b < aabb_a or obb_a > aabb_b:
        return False
    return True


# Object types that ``_handle_interactions`` never reacts to — solids,
# slopes (handled by _resolve_slopes), and start markers. Cached as a
# frozenset so the trigger-index filter is one lookup per object.
_NON_TRIGGER_TYPES = SOLID_TYPES | {T_START, T_SLOPE}


def _is_non_trigger(o):
    return o["t"] in _NON_TRIGGER_TYPES


# ---------------------------------------------------------------------------
# Player
# ---------------------------------------------------------------------------

class Player:
    # __slots__ saves the per-instance __dict__ on every attribute
    # access. The physics inner loops touch self.x / self.y / self.vy /
    # self.size / self.angle hundreds of times per substep — the
    # per-attribute speedup compounds. Subclasses (e.g. ``_SimPlayer``
    # in autobot.py) declare their own __slots__ for the extra fields
    # they add.
    __slots__ = (
        "objects", "params",
        "_teleport_index", "_by_oid", "_by_group",
        "_end_walls_x",
        "practice_mode", "checkpoints", "attempt_count",
        "_has_slopes",
        "hitbox_trace", "mirror_hitbox_trace",
        "_nearby_cache_key", "_nearby_cache_result",
        "_nearby_trigger_cache_key", "_nearby_trigger_cache_result",
        "_spatial_index", "_trigger_index",
        "_ever_moved",
        "x", "y", "vy", "grav", "on_ground", "alive", "won",
        "size", "angle",
        "grounded_frames", "last_jump", "death_reason",
        "target_cam_y", "free_cam_mode",
        "color_index", "player_color", "icon_index",
        "bg_preset", "mode", "move_speed",
        "dash_timer", "dash_vx", "dash_vy",
        "input_buffer", "mirror_input_buffer",
        "teleport_cooldown",
        "trail", "mirror_trail",
        "mirror", "mirror_passed",
        "passed", "coins_collected",
        "frame",
        "_grav_flip_grace", "_wall_frames",
        "_checkpoint_request", "_x_at_frame_start",
        "_wave_vy_smooth", "_mirror_wave_vy_smooth",
        "_hold_consumed", "_was_on_ground",
        "move_animations", "active_rotations", "active_pulses",
        "active_follows",
        "time_warp",
        "flight_budget", "_robot_thrust_disabled",
        "_bot_visibility",
    )

    def __init__(self, objects, params=None):
        self.objects = objects
        # PhysicsParams is read on every physics tick — stash locally so
        # subclasses (e.g. _SimPlayer in autobot.py) inherit the same
        # feel. None falls through to the global defaults so the shim
        # doesn't change behavior for callers that haven't opted in.
        self.params = params if params is not None else DEFAULT_PARAMS
        for o in self.objects:
            o.setdefault("_orig_x", o["x"])
            o.setdefault("_orig_y", o["y"])
        self._teleport_index = {}
        self._rebuild_teleport_index()
        # Trigger target indexes — built once and reused by every move /
        # rotate trigger fire. Before, each fire scanned `self.objects`
        # twice (once to collect group oids, once to filter by the oid
        # set), so a trigger-heavy level paid O(N_objects × N_triggers)
        # on every crossing.
        self._by_oid = {}
        self._by_group = {}
        for o in self.objects:
            oid = o.get("oid")
            if oid:
                self._by_oid[oid] = o
            g = o.get("group")
            if g:
                self._by_group.setdefault(g, []).append(o)
        # End walls span the full screen height: collision is x-only.
        # Sorted so we can stop scanning once player.x is past all of them.
        self._end_walls_x = sorted({
            o["x"] * CELL for o in self.objects if o["t"] == T_END
        })
        self.practice_mode = False
        self.checkpoints = []
        self.attempt_count = 0
        # Level-wide fast-outs: many levels never use slopes (or end walls,
        # or move triggers). Each substep otherwise pays the cost of an
        # iteration over nearby_for_rect just to filter for slopes that
        # don't exist. A single bool gate at the top of _resolve_slopes
        # short-circuits the call entirely.
        self._has_slopes = any(o["t"] == T_SLOPE for o in self.objects)
        # Optional per-substep hitbox recorder. When the caller (run_play
        # via the editor's Hitbox view) assigns a list here, the player
        # appends (x, y, size) at every collision-check point — each
        # substep of the physics loop and the bracket positions around
        # spider-teleport / teleport-orb warps. Left untouched by
        # reset() so the caller's reference survives across attempts.
        self.hitbox_trace = None
        # Parallel trace for the dual-mode mirror body — recorded only
        # while ``self.mirror`` is non-None. Shape matches hitbox_trace
        # so the editor can render both with the same logic + a
        # different colour. Left untouched by reset().
        self.mirror_hitbox_trace = None
        # Single-shot cache for nearby_for_rect. Multiple per-substep
        # collision passes query the same broad-phase footprint; caching
        # the rebuilt list saves ~80% of nearby_for_rect work in the
        # bot solver. Invalidated on grid rebuilds (move triggers).
        self._nearby_cache_key = None
        self._nearby_cache_result = []
        # Parallel cache for the trigger-only nearby query used by
        # _handle_interactions to skip solid blocks during the broad
        # phase. The key matches but the cached list is smaller.
        self._nearby_trigger_cache_key = None
        self._nearby_trigger_cache_result = []
        self.reset()

    def _rebuild_teleport_index(self):
        groups = {}
        for o in self.objects:
            if o["t"] == T_TELEPORT_ORB:
                gid = get_group_id(o)
                if gid:
                    groups.setdefault(gid, []).append(o)
        self._teleport_index = groups

    def _resolve_targets(self, trig):
        """Return the list of objects a move/rotate/etc. trigger targets.

        Handles the `target_oid` / `target_oids` / `group` resolution in
        one place (previously open-coded at every trigger's start-site).
        Preserves identity ordering — oids first, then group members, with
        any duplicates dropped.
        """
        seen = set()
        out = []
        oids = trig.get("target_oids")
        if oids:
            for oid in oids:
                if oid and oid not in seen:
                    o = self._by_oid.get(oid)
                    if o is not None:
                        seen.add(oid)
                        out.append(o)
        single = trig.get("target_oid")
        if single and single not in seen:
            o = self._by_oid.get(single)
            if o is not None:
                seen.add(single)
                out.append(o)
        group = trig.get("group")
        if group:
            for o in self._by_group.get(group, ()):
                oid = o.get("oid")
                # Skip objects already covered by the explicit oid list;
                # unident group-members (no oid) still get appended so
                # purely-group-addressed targets aren't dropped.
                if oid is None:
                    out.append(o)
                elif oid not in seen:
                    seen.add(oid)
                    out.append(o)
        return out

    def reset(self):
        for o in self.objects:
            if "_orig_x" in o:
                o["x"] = o["_orig_x"]
                o["y"] = o["_orig_y"]
            o.pop("_fx", None)
            o.pop("_fy", None)
            o.pop("_cell", None)
        self.move_animations = []
        self.active_follows = []
        # `id(obj) -> obj` for every object ever touched by a move trigger
        # this session. The autobot's `_restore` needs to un-move objects
        # that moved *after* a snapshot was taken; this is the universe
        # of candidates to check. Rebuilt on reset because positions are
        # restored to `_orig_x`/`_orig_y` above.
        self._ever_moved = {}
        self._rebuild_spatial_index()
        self.x, self.y = self._spawn_point()
        self.vy = 0.0
        self.on_ground = False
        # Running count of consecutive physics frames the player has been
        # grounded at frame-start. Used to judge jump timing: a cube/ball/
        # spider action that fires when this reads 1 landed + acted on the
        # same frame — i.e. frame-perfect. Reset to 0 when airborne.
        self.grounded_frames = 0
        # Telemetry for the most recent ground-triggered action (cube jump,
        # ball flip, spider teleport). Consumed by the play-mode debug HUD
        # so the user can verify whether a jump was frame-perfect.
        self.last_jump = None
        self.alive = True
        # Human-readable reason for the last death — displayed on the
        # death overlay so the player can tell "hit a spike" from "fell
        # off the screen". Populated at every `self.alive = False` site.
        self.death_reason = ""
        self.won = False
        self.angle = 0.0
        self.grav = 1
        self.trail = []
        # Parallel trail for the mirror body — sampled and decayed the
        # same way as ``trail``, only populated while in dual mode.
        # Drawn flipped vertically so the ghost silhouettes / line
        # segments match the mirror's upside-down sprite render.
        self.mirror_trail = []
        self.passed = set()
        self.frame = 0
        self.mode = MODE_CUBE
        self.move_speed = self.params.base_move_speed
        self.dash_timer = 0
        self.dash_vx = 0.0
        self.dash_vy = 0.0
        self.input_buffer = 0
        # Mirror keeps its own input buffer so a single click registers for
        # both bodies' orbs. With one shared buffer, the main consumes it
        # first and the mirror's orb (if any) silently misses out — the
        # bot's beam search never noticed because it just retries the next
        # frame, but a human only gets the one tap.
        self.mirror_input_buffer = 0
        self.teleport_cooldown = 0
        self.target_cam_y = 0.0
        # When True, play.py drives target_cam_y to follow the player
        # vertically every frame (set by gamemode portals with the
        # "free_mode" flag). Cleared by any non-free-mode gamemode portal.
        self.free_cam_mode = False
        self.bg_preset = 0
        # Player cosmetics persisted across runs via the Settings module.
        # Modulo on every read keeps things sane even if PLAYER_COLORS
        # shrinks or the prefs file held a stale, larger index.
        self.color_index = settings.get_player_color_index() % len(PLAYER_COLORS)
        self.player_color = PLAYER_COLORS[self.color_index]
        self.icon_index = settings.get_player_icon_index() % len(PLAYER_ICONS)
        self._grav_flip_grace = 0
        self._wall_frames = 0
        self._checkpoint_request = False
        self._x_at_frame_start = self.x
        # Low-pass-filtered vy used by the wave-mode sprite angle so
        # rapid input toggles (bot taps, human mashing) don't read as
        # jitter — instantaneous vy snaps between ±move_speed every
        # frame in wave, but the visible heading should track the
        # sustained direction.
        self._wave_vy_smooth = 0.0
        self._mirror_wave_vy_smooth = 0.0
        # Hold-after-spider gate. A spider orb that fires while the
        # player is holding input used to bleed the held button straight
        # into the next frame's cube auto-jump (cube fires on
        # `input_held + on_ground`), so the player would teleport to a
        # surface and immediately jump off it. Setting this on spider
        # activation makes the cube wait for a release+repress before
        # auto-jumping again.
        self._hold_consumed = False
        # Player scale: PLAYER_SIZE normally, MINI_PLAYER_SIZE after a mini
        # portal. Reset to full on every new attempt.
        self.size = PLAYER_SIZE
        self.coins_collected = set()  # coin_ids picked up this attempt
        # Dual-mode mirror body. None when single-player. A dict with y/vy/
        # grav/on_ground/angle/alive/mode/size when a dual portal is active.
        self.mirror = None
        # Portals/grav-flips that the mirror has consumed independently of
        # the main player. Mode and size portals fire per-body so each can
        # have its own loadout — kept separate from `passed` (which is
        # shared for one-shot physical objects like orbs / pads / coins).
        self.mirror_passed = set()
        # Active pulse triggers — list of dicts {start_frame, bpm, end_frame}.
        # play.py reads this to compute a pulse intensity for visual flash.
        self.active_pulses = []
        # Active rotation triggers — list of dicts {target_oids, spin,
        # end_frame}. _step_rotate_triggers ticks rotation each frame.
        self.active_rotations = []
        # Active follow links — list of dicts {source, target,
        # offset_x, offset_y}. Each frame _step_follow_triggers
        # snaps each target's position to its source's current
        # position plus the recorded offset, so chained move
        # triggers propagate through the link.
        self.active_follows = []
        # Time-warp factor latched by T_TIME_WARP triggers. Read by
        # play.py each render frame and folded into ``step_scale`` so
        # the sim accumulator advances faster (>1) or slower (<1) than
        # real time. Persistent until another warp trigger or a death
        # reset; defaults to 1.0 (real time) on every fresh attempt.
        self.time_warp = 1.0
        # Robot-mode held-thrust budget, in physics ticks. Drains while
        # the button is held in MODE_ROBOT and refills to full the moment
        # the robot lands. The cap is derived from PhysicsParams (so
        # per-level overrides take effect) at the 60 Hz internal physics
        # rate. Kept full when not in robot mode so a portal-in mid-level
        # gives the player the full budget to start.
        self.flight_budget = int(self.params.robot_flight_seconds * 60)
        # Bot-only collision visibility. Default False = real player
        # tick: bot-only objects are filtered out of every nearby
        # query. The Y bot's lookahead temporarily flips this to True.
        self._bot_visibility = False
        # Robot mid-air release lock. Set the moment the player lets go
        # of the button while airborne in robot mode; cleared on landing
        # (or on a fresh portal entry into robot mode). While locked,
        # subsequent re-presses do NOT thrust — the robot has to land
        # first. Implements "one boost per takeoff": tap=tiny, hold=big,
        # but no second wind in mid-air.
        self._robot_thrust_disabled = False
        # Always-on follow links arm at level start instead of waiting
        # for the player to physically pass through their cell. Run
        # AFTER the position resets above so the captured initial
        # offset reflects the level's spawn-time layout, not whatever
        # mid-flight pose lingered from the previous attempt.
        for o in self.objects:
            if o.get("t") == T_FOLLOW_TRIGGER and o.get("always_on"):
                self._start_follow_trigger(o)
        self.attempt_count += 1

    def _start_object(self):
        starts = [o for o in self.objects if o["t"] == T_START]
        if starts:
            return min(starts, key=lambda o: (o["x"], o["y"]))
        return None

    def _spawn_point(self):
        start = self._start_object()
        if start:
            return (
                float(start["x"] * CELL + (CELL - PLAYER_SIZE) / 2),
                float(start["y"] * CELL + (CELL - PLAYER_SIZE) / 2),
            )
        return float(PLAYER_START_GX * CELL), float(self._default_ground_y())

    def _default_ground_y(self):
        col_blocks = [o for o in self.objects
                      if o["t"] == T_BLOCK and o["x"] == PLAYER_START_GX]
        if col_blocks:
            top = min(o["y"] for o in col_blocks)
            return top * CELL - PLAYER_SIZE
        return 10 * CELL - PLAYER_SIZE

    def rect(self):
        return pygame.Rect(round(self.x), round(self.y), self.size, self.size)

    def hitbox(self):
        """Hazard hitbox — exactly the player's outer rect, full size.
        Returned as the broad-phase Rect; the rotated-OBB narrow phase
        runs in ``_outer_obb_corners`` for the actual hazard test."""
        return pygame.Rect(round(self.x), round(self.y),
                           self.size, self.size)

    def solid_hitbox(self):
        """Inner death hitbox — 50% of the player size, centred. Used
        only for the BLOCK-DEATH check (``_inner_in_block_dies`` runs
        OBB-vs-AABB SAT against nearby blocks). Block resolution snaps
        the outer rect, so this only fires when the player is genuinely
        clipping into a wall / ceiling that resolution couldn't reject.
        """
        inner = max(2, int(self.size * SOLID_HITBOX_FRACTION))
        cx = round(self.x) + self.size // 2
        cy = round(self.y) + self.size // 2
        return pygame.Rect(cx - inner // 2, cy - inner // 2, inner, inner)

    def _solid_hitbox_at(self, x, y, size):
        """Inner solid hitbox at an arbitrary (x, y, size) — lets
        ``_step_mirror`` build the same shape for the mirror body
        without fabricating a Player instance."""
        inner = max(2, int(size * SOLID_HITBOX_FRACTION))
        cx = round(x) + size // 2
        cy = round(y) + size // 2
        return pygame.Rect(cx - inner // 2, cy - inner // 2, inner, inner)

    # ---- rotated hitboxes (OBB) -----------------------------------------
    def _outer_obb_corners(self):
        """Four corners of the OUTER hitbox, rotated by ``self.angle``
        about the player's visual centre. Used by the hazard hit-test
        so the kill volume tracks the rotating player visual exactly.
        Returns a list of (x, y) floats in world space.
        """
        return _obb_corners(self.x, self.y, self.size, self.angle, 1.0)

    def _inner_obb_corners(self):
        """Four corners of the INNER 50% hitbox.

        Inner is INTENTIONALLY axis-aligned regardless of ``self.angle``
        — its job is to fire the block-death rule (any solid block /
        slab that pokes into the central 50% kills the player). Tilting
        it with the outer rect was the legacy behaviour, but it made
        block-deaths fire/miss unpredictably as the cube spun mid-air.
        Outer keeps rotating (drives the visual + the hazard test);
        inner stays a fixed 50% square.
        """
        return _obb_corners(self.x, self.y, self.size, 0.0,
                            SOLID_HITBOX_FRACTION)

    def _inner_in_block_dies(self):
        """Return True (and set alive=False) if the inner death hitbox
        overlaps any nearby solid block / slab.

        With the inner now permanently axis-aligned, the ``_resolve_x``
        / ``_resolve_y`` AABB inner-vs-block checks already handle the
        whole story — but those passes only fire on the SAME substep
        as the corresponding move. The end-of-substep call here is a
        belt-and-braces check for the rare frame where a teleport / pad
        / orb shoves the player INTO a block without going through a
        normal x or y resolve pass. Cheap AABB-vs-AABB; no SAT needed
        anymore.
        """
        if self.on_ground:
            return False
        size = self.size
        px = round(self.x)
        py = round(self.y)
        inner = max(2, int(size * SOLID_HITBOX_FRACTION))
        cx_pixel = px + size // 2
        cy_pixel = py + size // 2
        ix0 = cx_pixel - inner // 2
        iy0 = cy_pixel - inner // 2
        ix1 = ix0 + inner
        iy1 = iy0 + inner
        _solid_rect = self._solid_rect
        for o in self._nearby_for_aabb(px, py, px + size, py + size):
            br = o.get("_srect")
            if br is None:
                br = _solid_rect(o)
                if br is None:
                    continue
            bl, bt, brr, bb = br
            if (ix0 < brr and ix1 > bl and iy0 < bb and iy1 > bt):
                self.alive = False
                self.death_reason = "Crashed into a wall"
                return True
        return False

    def _record_hitbox(self):
        """Append the current (x, y, size, angle) to hitbox_trace if
        recording. Called once per logical (60 Hz) frame at the end of
        ``update``; per-substep sampling produced an unreadable smear
        on fast falls / teleports. Angle is stored so the editor can
        draw the rotated outer + inner OBBs exactly as the physics
        sees them.
        """
        if self.hitbox_trace is not None:
            self.hitbox_trace.append(
                (self.x, self.y, self.size, self.angle))

    def _record_mirror_hitbox(self):
        """Mirror-side counterpart to ``_record_hitbox``. The mirror's
        x is always self.x; only y/size differ from the main body.
        Records the mirror's own angle so its rotated overlay tracks
        independent ball / spider rotation when the two bodies diverge.
        Skips silently when there's no mirror or no trace assigned, so
        callers in ``_step_mirror`` don't need their own guard."""
        if self.mirror_hitbox_trace is None or self.mirror is None:
            return
        m = self.mirror
        self.mirror_hitbox_trace.append(
            (self.x, m["y"], int(m.get("size", PLAYER_SIZE)),
             float(m.get("angle", 0.0))))

    def save_checkpoint(self):
        """Save current player state as a checkpoint for practice mode."""
        checkpoint = {
            "x": self.x,
            "y": self.y,
            "vy": self.vy,
            "grav": self.grav,
            "mode": self.mode,
            "move_speed": self.move_speed,
            "angle": self.angle,
            "bg_preset": self.bg_preset,
            "target_cam_y": self.target_cam_y,
            "free_cam_mode": self.free_cam_mode,
            "color_index": self.color_index,
            "coins": set(self.coins_collected),
            "passed": set(self.passed),
        }
        self.checkpoints.append(checkpoint)

    def load_checkpoint(self):
        """Restore player state from last checkpoint."""
        if not self.checkpoints:
            return False
        cp = self.checkpoints[-1]
        self.x = cp["x"]
        self.y = cp["y"]
        self.vy = cp["vy"]
        self.grav = cp["grav"]
        self.mode = cp["mode"]
        self.move_speed = cp["move_speed"]
        self.angle = cp["angle"]
        self.bg_preset = cp["bg_preset"]
        self.target_cam_y = cp["target_cam_y"]
        self.free_cam_mode = bool(cp.get("free_cam_mode", False))
        self.color_index = cp.get("color_index", 0)
        self.player_color = PLAYER_COLORS[self.color_index % len(PLAYER_COLORS)]
        self.coins_collected = set(cp.get("coins", set()))
        self.passed = set(cp.get("passed", set()))
        self.on_ground = False
        self.alive = True
        self.won = False
        self.trail = []
        self.mirror_trail = []
        return True

    def _rebuild_spatial_index(self):
        """(Re)build both the full and trigger-only (gx, gy) -> list[obj]
        indexes from current positions.

        Called on init and reset. Any stale `_cell` markers are cleared by
        the reset-loop before this runs, so every object gets reinserted.

        The trigger-only index excludes T_BLOCK / T_SLAB / T_SLOPE /
        T_START so ``_handle_interactions`` can iterate ~5× fewer
        candidates on block-heavy levels (the hot path that dominated
        the bot solve profile).
        """
        self._spatial_index = {}
        self._trigger_index = {}
        for o in self.objects:
            cell = (o["x"], o["y"])
            o["_cell"] = cell
            self._spatial_index.setdefault(cell, []).append(o)
            if not _is_non_trigger(o):
                self._trigger_index.setdefault(cell, []).append(o)

    def _spatial_rebucket(self, obj):
        """Move obj between index buckets when its (x, y) cell changes."""
        old = obj.get("_cell")
        new = (obj["x"], obj["y"])
        if old == new:
            return
        # Both nearby caches could now be stale (a moved object might
        # be in our footprint). Cheap to drop; the next query rebuilds.
        self._nearby_cache_key = None
        self._nearby_trigger_cache_key = None
        is_trig = not _is_non_trigger(obj)
        if old is not None:
            bucket = self._spatial_index.get(old)
            if bucket is not None:
                for i in range(len(bucket)):
                    if bucket[i] is obj:
                        bucket.pop(i)
                        break
                if not bucket:
                    self._spatial_index.pop(old, None)
            if is_trig:
                tbucket = self._trigger_index.get(old)
                if tbucket is not None:
                    for i in range(len(tbucket)):
                        if tbucket[i] is obj:
                            tbucket.pop(i)
                            break
                    if not tbucket:
                        self._trigger_index.pop(old, None)
        obj["_cell"] = new
        self._spatial_index.setdefault(new, []).append(obj)
        if is_trig:
            self._trigger_index.setdefault(new, []).append(obj)

    def nearby_for_rect(self, rect, extra=2):
        return self._nearby_for_aabb(rect.left, rect.top,
                                     rect.right, rect.bottom, extra)

    def _nearby_for_aabb(self, left_px, top_px, right_px, bottom_px, extra=2):
        """Same as ``nearby_for_rect`` but takes raw integer pixel bounds —
        avoids the per-call ``pygame.Rect`` allocation that the rect-based
        path forces on hot callers.

        Bot-only objects are PHANTOM during real play: visible to the
        Y bot's lookahead probe (``self._bot_visibility = True``) but
        filtered out of every collision / trigger loop otherwise. The
        cache key includes the visibility flag so the bot's
        hypothetical ticks and the real player's ticks don't share a
        stale cached list."""
        left = left_px // CELL - extra
        right = right_px // CELL + extra
        top = top_px // CELL - extra
        bottom = bottom_px // CELL + extra
        bot_vis = bool(getattr(self, "_bot_visibility", False))
        # Per-substep cache — every collision / interaction pass
        # queries the same footprint, so caching by (left, top, right,
        # bottom, extra, bot_vis) avoids rebuilding the list ~5× per
        # substep.
        cache_key = (left, top, right, bottom, extra, bot_vis)
        if cache_key == self._nearby_cache_key:
            return self._nearby_cache_result
        out = []
        index = self._spatial_index
        for gx in range(left, right + 1):
            for gy in range(top, bottom + 1):
                bucket = index.get((gx, gy))
                if bucket:
                    out.extend(bucket)
        if not bot_vis and out:
            # One pass: scan for bot_only objects, only allocate a
            # filtered list if any are present.
            has_bo = False
            for o in out:
                if o.get("_bot_only"):
                    has_bo = True
                    break
            if has_bo:
                out = [o for o in out if not o.get("_bot_only")]
        self._nearby_cache_key = cache_key
        self._nearby_cache_result = out
        return out

    def _nearby_triggers_for_aabb(self, left_px, top_px, right_px,
                                  bottom_px, extra=2):
        """Trigger-only nearby query — iterates the smaller index that
        excludes solids / slopes / start markers."""
        left = left_px // CELL - extra
        right = right_px // CELL + extra
        top = top_px // CELL - extra
        bottom = bottom_px // CELL + extra
        bot_vis = bool(getattr(self, "_bot_visibility", False))
        cache_key = (left, top, right, bottom, extra, bot_vis)
        if cache_key == self._nearby_trigger_cache_key:
            return self._nearby_trigger_cache_result
        out = []
        index = self._trigger_index
        for gx in range(left, right + 1):
            for gy in range(top, bottom + 1):
                bucket = index.get((gx, gy))
                if bucket:
                    out.extend(bucket)
        if not bot_vis:
            # Same bot-only filter as nearby_for_rect — but cached
            # separately because triggers and solids share neither
            # the lookup nor the eviction lifecycle.
            out = [o for o in out if not o.get("_bot_only")]
        self._nearby_trigger_cache_key = cache_key
        self._nearby_trigger_cache_result = out
        return out

    # ---- actions ----------------------------------------------------------
    def _record_jump_timing(self, kind, input_pressed):
        """Snapshot the timing of a ground-triggered action.

        `grounded_frames` is read *before* the action mutates `on_ground`,
        so a reading of 1 means the action fired on the landing frame
        itself — the tightest possible ("frame-perfect") release window.
        `fresh_press` distinguishes a tap on exactly this frame from a
        held input that auto-fired on landing.
        """
        self.last_jump = {
            "frame": self.frame,
            "grounded_frames": self.grounded_frames,
            "kind": kind,
            "fresh_press": bool(input_pressed),
            "perfect": self.grounded_frames == 1,
        }

    def jump(self, force=None):
        if force is None:
            force = self.params.jump_force
        self.vy = force * self.grav
        self.on_ground = False

    def activate_orb(self, force_scale=1.0):
        """Yellow-orb tap-to-jump. ``force_scale`` lets the red and pink
        orbs reuse the same per-mode falloff (ship 0.85, UFO 0.9) without
        duplicating the dispatch — they pass 2.0 / 0.5 to scale the
        cube-strength impulse."""
        if self.mode in (MODE_WAVE, MODE_SWING):
            # Wave/swing lock vy to mode-driven values every frame, so
            # any vy nudge would evaporate next tick. Flip gravity for
            # a visible response that respects each mode's vy rule.
            # Force scale doesn't apply — these modes ignore the impulse.
            self.grav *= -1
        elif self.mode == MODE_SHIP:
            self.vy = self.params.jump_force * 0.85 * force_scale * self.grav
        elif self.mode == MODE_UFO:
            self.vy = self.params.jump_force * 0.9 * force_scale * self.grav
        else:
            # Cube, ball, spider — uniform full-strength jump in the
            # current gravity direction. Ball used to flip+launch and
            # spider used to teleport, both of which fought the orb's
            # natural "tap to jump" intent.
            self.vy = self.params.jump_force * force_scale * self.grav
        self.on_ground = False

    def activate_red_orb(self):
        """Red orb: 2× yellow orb jump. Per-mode falloff still applies."""
        self.activate_orb(force_scale=2.0)

    def activate_pink_orb(self):
        """Pink orb: ½× yellow orb jump (a small hop)."""
        self.activate_orb(force_scale=0.5)

    def activate_dash_orb(self, orb):
        """Directional hold-dash: velocity vector set from the orb's
        facing rotation, magnitude from its ``dash_speed``, held for
        ``dash_dur`` frames or until the player releases. Both are
        per-orb editor fields; missing values fall back to the physics
        params defaults so old levels keep working."""
        speed = float(orb.get("dash_speed", self.params.dash_speed))
        duration = int(orb.get("dash_dur", self.params.dash_time))
        angle = math.radians(float(orb.get("r", 0)))
        self.dash_vx = speed * math.cos(angle)
        self.dash_vy = speed * math.sin(angle)
        self.dash_timer = max(1, duration)
        self.input_buffer = 0

    def activate_black_orb(self):
        self.vy = -self.params.jump_force * self.grav
        self.on_ground = False
        self.input_buffer = 0

    def activate_blue_orb(self):
        self.grav *= -1
        self.on_ground = False
        self.input_buffer = 0

    def activate_green_orb(self):
        """Green orb: jump in the current gravity direction (opposite of blue)."""
        self.vy = self.params.jump_force * self.grav
        self.on_ground = False
        self.input_buffer = 0

    def activate_spider_orb(self, orb=None):
        """Spider orb: teleport to the nearest solid surface in the orb's
        facing direction, flipping gravity when the teleport is vertical.

        Direction resolution, in order:
          1. Explicit ``dir`` field set via the editor toggle —
             ``"auto"`` (against-gravity, default), ``"up"``, ``"down"``,
             ``"left"`` or ``"right"``.
          2. Legacy ``r`` rotation (0 / 90 / 180 / 270) maps to
             auto / right / down / left for levels authored before the
             explicit toggle existed.
          3. Fallback ``None`` = against-gravity.

        Horizontal teleports keep the player's current gravity (no
        ceiling concept to flip against); vertical teleports still
        invert it so the player clings to the new surface GD-style.
        The swept hazard check in _spider_teleport covers the full
        span regardless of direction, so an orb pointed into a spike
        still kills the player.
        """
        direction = None
        if orb is not None:
            d = str(orb.get("dir", "")).lower()
            if d == "up":
                direction = (0, -1)
            elif d == "down":
                direction = (0, 1)
            elif d == "left":
                direction = (-1, 0)
            elif d == "right":
                direction = (1, 0)
            elif d == "auto" or d == "":
                # No explicit direction — honour the legacy rotation
                # picker so older levels still behave correctly.
                r = int(orb.get("r", 0)) % 360
                if r == 90:
                    direction = (1, 0)
                elif r == 180:
                    direction = (0, 1)
                elif r == 270:
                    direction = (-1, 0)
        self._spider_teleport(direction=direction)
        self.input_buffer = 0
        # Mark the held button as consumed so cube/ball/etc. don't
        # auto-jump on the same hold once the spider warps the player
        # onto a surface. Cleared on the next frame the user is not
        # holding (i.e., a real release).
        self._hold_consumed = True

    def activate_teleport(self, orb):
        gid = get_group_id(orb)
        if not gid:
            return
        group = [o for o in self._teleport_index.get(gid, []) if o is not orb]
        if not group:
            return
        dests = [o for o in group if o.get("dest")]
        dest = dests[0] if dests else group[0]
        # 60 Hz sampling: the end-of-frame _record_hitbox covers the
        # post-teleport pose. The pre-teleport pose was already
        # recorded by the previous frame's sample, so we don't need
        # bracket calls here.
        self.x = dest["x"] * CELL + (CELL - PLAYER_SIZE) / 2
        self.y = dest["y"] * CELL + (CELL - PLAYER_SIZE) / 2
        self.vy *= 0.25
        self.teleport_cooldown = 10
        self.trail = []
        self.mirror_trail = []

    def flip_gravity(self):
        self.grav *= -1
        self.on_ground = False

    def _spider_teleport(self, direction=None):
        """Spider: teleport to the nearest block surface in ``direction``,
        flipping gravity on vertical teleports so the player clings to
        the new surface GD-style.

        ``direction`` is a unit vector ``(dx, dy)``. ``None`` falls back
        to the classic against-gravity behaviour: (0, -1) on grav=1 and
        (0, +1) on grav=-1. Cardinal orb rotations pass (0, +1) / (0, -1)
        / (+1, 0) / (-1, 0) explicitly to pick a direction that ignores
        the player's current gravity.

        Range is unlimited: the teleport finds the nearest block surface
        in the direction regardless of distance. Scans the spatial index
        in the matching axis range directly rather than using
        ``nearby_for_rect`` so the search stays bounded by populated
        cells (a few thousand per level) instead of a hardcoded radius.
        """
        if direction is None:
            direction = (0, -self.grav)
        dx, dy = direction
        probe = self.rect()
        # Vertical scan: column range fixed; look up (dy<0) or down.
        # Horizontal scan: row range fixed; look right (dx>0) or left.
        best = None           # (distance, new_x, new_y)
        if dy != 0 and dx == 0:
            probe_left = probe.left
            probe_right = probe.right
            probe_top = probe.top
            probe_bottom = probe.bottom
            left_cell = int(probe_left // CELL)
            right_cell = int((probe_right - 1) // CELL)
            for (gx, _gy), bucket in self._spatial_index.items():
                if gx < left_cell - 1 or gx > right_cell + 1:
                    continue
                for o in bucket:
                    br = self._solid_rect(o)
                    if br is None:
                        continue
                    bl, bt, brr, bb = br
                    if not (bl < probe_right and brr > probe_left):
                        continue
                    if dy < 0:
                        if bb <= probe_top:
                            dist = probe_top - bb
                            if best is None or dist < best[0]:
                                best = (dist, self.x, float(bb))
                    else:
                        if bt >= probe_bottom:
                            dist = bt - probe_bottom
                            if best is None or dist < best[0]:
                                best = (dist, self.x,
                                        float(bt - self.size))
        elif dx != 0 and dy == 0:
            probe_left = probe.left
            probe_right = probe.right
            probe_top = probe.top
            probe_bottom = probe.bottom
            top_cell = int(probe_top // CELL)
            bot_cell = int((probe_bottom - 1) // CELL)
            for (_gx, gy), bucket in self._spatial_index.items():
                if gy < top_cell - 1 or gy > bot_cell + 1:
                    continue
                for o in bucket:
                    br = self._solid_rect(o)
                    if br is None:
                        continue
                    bl, bt, brr, bb = br
                    if not (bt < probe_bottom and bb > probe_top):
                        continue
                    if dx > 0:
                        if bl >= probe_right:
                            dist = bl - probe_right
                            if best is None or dist < best[0]:
                                best = (dist, float(bl - self.size),
                                        self.y)
                    else:
                        if brr <= probe_left:
                            dist = probe_left - brr
                            if best is None or dist < best[0]:
                                best = (dist, float(brr), self.y)
        if best is not None:
            # Swept-volume hazard check — the teleport is instantaneous
            # but it still can't phase through spikes or saws. Build the
            # union of pre- and post-teleport hitboxes and test every
            # hazard whose cell falls inside that swept band. The AABB
            # pre-filter is shrunk for grace; the rotated-OBB narrow
            # phase below uses the full outer (so OUTER detects hazards
            # per the two-hitbox design).
            from .graphics import spike_hitboxes as _sh, saw_hitbox as _saw
            prev_x = self.x
            prev_y = self.y
            new_x = float(best[1])
            new_y = float(best[2])
            shrink = max(2, int(6 * self.size / PLAYER_SIZE))
            pre_hazard = pygame.Rect(
                round(prev_x) + shrink, round(prev_y) + shrink,
                self.size - shrink * 2, self.size - shrink * 2)
            post_hazard = pygame.Rect(
                round(new_x) + shrink, round(new_y) + shrink,
                self.size - shrink * 2, self.size - shrink * 2)
            swept = pre_hazard.union(post_hazard)
            swept_trigger = swept.inflate(6, 6)
            # 60 Hz hitbox sampling: a single ``_record_hitbox`` call at
            # the end of ``update`` captures the post-teleport pose. We
            # used to fan-fill the swept volume so the overlay showed
            # the exact span the hazard check covered, but per-substep
            # samples made the overlay unreadable on a fast spider chain.
            # The hazard sweep itself still tests the union below.
            for o in self.nearby_for_rect(swept_trigger, 2):
                t = o["t"]
                if t in (T_SPIKE, T_HALF_SPIKE):
                    sc = obj_scale(o)
                    for sr in _sh(o["x"], o["y"], o.get("r", 0),
                                  t == T_HALF_SPIKE, sc):
                        if swept.colliderect(sr):
                            self.alive = False
                            self.death_reason = "Teleported into a spike"
                            return
                elif t == T_SAW:
                    sc = obj_scale(o)
                    if swept.colliderect(_saw(o["x"], o["y"], sc)):
                        self.alive = False
                        self.death_reason = "Teleported into a saw"
                        return
            # Fill the swept beam with trail samples in the current
            # mode's style — line-trail modes (wave/ship/spider) get a
            # continuous beam between pre and post, ghost-trail modes
            # (cube/ball/UFO) get evenly-spaced ghost samples along the
            # path. Without these intermediate samples the teleport
            # used to read as a hard jump-cut. Sample density tracks
            # player size so a mini cube doesn't get over-stamped.
            # Alpha stays at the regular 100 cap so the decay-and-
            # filter cleanup stays uniform (a higher value here used
            # to break the age-ordering invariant and leave negative-
            # alpha entries mid-list that crashed the renderer).
            beam_step = max(8, self.size // 2)
            dx_b = new_x - prev_x
            dy_b = new_y - prev_y
            beam_len = (dx_b * dx_b + dy_b * dy_b) ** 0.5
            beam_n = max(1, int(beam_len // beam_step))
            for i in range(beam_n + 1):
                t = i / beam_n if beam_n else 0.0
                bx = prev_x + dx_b * t
                by = prev_y + dy_b * t
                self.trail.append([bx, by, self.angle, 100])
            self.x = new_x
            self.y = new_y
            # Only flip gravity on vertical teleports — clinging to a
            # ceiling / floor is the intent. Horizontal teleports keep
            # the player's current gravity (there's no ceiling to cling
            # to on a sideways jump).
            if dy != 0:
                self.grav *= -1
                self._grav_flip_grace = 4
            self.vy = 0.0
            self.on_ground = False

    def _start_move_trigger(self, trig):
        """Kick off the move animation for one or more target oids."""
        targets = self._resolve_targets(trig)
        if not targets:
            return
        duration = max(1, int(trig.get("duration", 30)))
        curve = trig.get("curve", DEFAULT_MOVE_CURVE)
        curve_area = sum(
            (curve[i + 1][0] - curve[i][0]) * (curve[i][1] + curve[i + 1][1]) * 0.5
            for i in range(len(curve) - 1)
        ) if curve and len(curve) >= 2 else 1.0
        first = targets[0]
        end_x = float(trig.get("tx", first["x"]))
        end_y = float(trig.get("ty", first["y"]))
        dx = end_x - float(first.get("_fx", first["x"]))
        dy = end_y - float(first.get("_fy", first["y"]))
        for target in targets:
            start_x = float(target.get("_fx", target["x"]))
            start_y = float(target.get("_fy", target["y"]))
            self.move_animations.append({
                "obj": target,
                "sx": start_x, "sy": start_y,
                "ex": start_x + dx, "ey": start_y + dy,
                "frame": 0, "duration": duration,
                "curve": curve, "curve_area": curve_area,
            })

    def pulse_intensity(self):
        """Return a [0,1] intensity from active pulse triggers, where 1 is
        a peak flash. Sums sin^2 contributions of every active pulse and
        clips. Called by play.py during rendering — purely presentational."""
        if not self.active_pulses:
            return 0.0
        total = 0.0
        for p in self.active_pulses:
            bpm = max(1, p["bpm"])
            elapsed_frames = self.frame - p["start_frame"]
            # 60 fps; one beat = 60/bpm seconds = 60*60/bpm frames.
            frames_per_beat = 3600.0 / bpm
            phase = (elapsed_frames / frames_per_beat) * math.tau
            total += math.sin(phase) ** 2
        return min(1.0, total)

    def _start_rotate_trigger(self, trig):
        """Begin a rotation animation on one or more target oids. Targets
        keep their visual rotation in their `r` field. Resolves group ids
        too — if `group` is set on the trigger, all objects with the
        matching group field are added as targets."""
        targets = self._resolve_targets(trig)
        if not targets:
            return
        spin_dps = float(trig.get("spin", 90.0))  # degrees per second
        duration_s = float(trig.get("duration", 4.0))
        frames = max(1, int(duration_s * 60))
        self.active_rotations.append({
            "targets": targets,
            "spin_per_frame": spin_dps / 60.0,
            "end_frame": self.frame + frames,
        })

    def _step_rotate_triggers(self):
        if not self.active_rotations:
            return
        remaining = []
        for rot in self.active_rotations:
            if self.frame >= rot["end_frame"]:
                continue
            for o in rot["targets"]:
                # Visual `r` is in degrees; we keep it modulo 360 for sanity.
                o["r"] = (float(o.get("r", 0)) + rot["spin_per_frame"]) % 360.0
                # Slab orientation depends on r — drop the cached AABB
                # so the next collision query rebuilds it at the new
                # rotation. Cheap (dict del) for the common no-cache case.
                if "_srect" in o:
                    del o["_srect"]
                if "_caabb" in o:
                    del o["_caabb"]
                if "_saw_aabb" in o:
                    del o["_saw_aabb"]
                if "_sphb_aabbs" in o:
                    del o["_sphb_aabbs"]
            remaining.append(rot)
        self.active_rotations = remaining

    def _start_follow_trigger(self, trig):
        """Activate a follow link.

        Two modes:
          * Default — target follows source. Initial offset (target -
            source) is captured here so the link doesn't snap on
            activation.
          * ``follow_player=True`` — source follows the live player.
            Offset (in cells) is read from the trigger's
            ``offset_cx``/``offset_cy`` fields rather than captured at
            activation, so the level author dictates exactly where
            the source sits relative to the player. ``target_oid`` is
            not used in this mode (place a second follow trigger if
            you want a chain).

        Idempotent: re-passing the same trigger is a no-op."""
        follow_player = bool(trig.get("follow_player", False))
        src_oid = trig.get("source_oid")
        tgt_oid = trig.get("target_oid")
        if follow_player:
            if not src_oid:
                return
            source = self._by_oid.get(src_oid)
            if source is None:
                return
            # Dedup: already linked this object to the player?
            for f in self.active_follows:
                if (f.get("source") == "PLAYER"
                        and f["target"].get("oid") == src_oid):
                    return
            ocx = int(trig.get("offset_cx", 0))
            ocy = int(trig.get("offset_cy", 0))
            # Offsets are stored in CELLS — matches the object→object
            # path below, where ``offset_x = tx - sx`` is the
            # difference of two cell coords. ``_step_follow_triggers``
            # adds this to the player's *cell* position (not pixels),
            # so the units must agree or the target lands ~CELL× too
            # far out and ends up off the spatial index.
            self.active_follows.append({
                "source": "PLAYER",
                "target": source,
                "offset_x": float(ocx),
                "offset_y": float(ocy),
            })
            self._ever_moved[id(source)] = source
            return
        if not src_oid or not tgt_oid or src_oid == tgt_oid:
            return
        # No duplicate links for the same (source, target).
        for f in self.active_follows:
            if f.get("source") == "PLAYER":
                continue
            if (f["source"].get("oid") == src_oid
                    and f["target"].get("oid") == tgt_oid):
                return
        source = self._by_oid.get(src_oid)
        target = self._by_oid.get(tgt_oid)
        if source is None or target is None:
            return
        # Use the live (post-anim) positions so an offset captured
        # mid-animation is the visible offset, not the original-grid
        # offset.
        sx = float(source.get("_fx", source["x"]))
        sy = float(source.get("_fy", source["y"]))
        tx = float(target.get("_fx", target["x"]))
        ty = float(target.get("_fy", target["y"]))
        self.active_follows.append({
            "source": source,
            "target": target,
            "offset_x": tx - sx,
            "offset_y": ty - sy,
        })
        # Both source and target are now in the "ever moved" universe
        # so the autobot's snap/restore can correctly reset their
        # positions on a state restore.
        self._ever_moved[id(source)] = source
        self._ever_moved[id(target)] = target

    def _step_follow_triggers(self):
        """Snap each linked target's position to its source's
        position plus the recorded offset. Runs every frame so the
        link reacts to move-trigger animations on the source mid-
        flight, not just at link-activation time. The "PLAYER"
        sentinel source reads the live player's pose."""
        if not self.active_follows:
            return
        for link in self.active_follows:
            source = link["source"]
            target = link["target"]
            if source == "PLAYER":
                # ``self.x``/``self.y`` are pixel coords; the rest of
                # the follow plumbing (object x/y, _fx/_fy, cell_rect)
                # works in CELL coords. Convert so the orb/object the
                # author wired up lands on the player's cell rather
                # than CELL² away (which threw it off the spatial
                # index and made it unclickable mid-play).
                sx = self.x / CELL
                sy = self.y / CELL
            else:
                sx = float(source.get("_fx", source["x"]))
                sy = float(source.get("_fy", source["y"]))
            new_fx = sx + link["offset_x"]
            new_fy = sy + link["offset_y"]
            # Mirror what _step_move_animations does on each tick:
            # write both the integer cell anchor (target["x"],
            # target["y"]) AND the fractional ``_fx``/``_fy`` so
            # collision / render code sees a consistent pose.
            target["_fx"] = new_fx
            target["_fy"] = new_fy
            target["x"] = int(round(new_fx))
            target["y"] = int(round(new_fy))
            # Drop cached collision AABBs that depend on (x, y).
            if "_srect" in target:
                del target["_srect"]
            if "_caabb" in target:
                del target["_caabb"]
            if "_saw_aabb" in target:
                del target["_saw_aabb"]
            if "_sphb_aabbs" in target:
                del target["_sphb_aabbs"]
            # Keep the spatial index in sync — same hook the move
            # animation uses so nearby_for_rect can still find the
            # target at its new cell.
            self._spatial_rebucket(target)

    def _step_move_animations(self):
        if not self.move_animations:
            return
        remaining = []
        for anim in self.move_animations:
            anim["frame"] += 1
            t = min(1.0, anim["frame"] / anim["duration"])
            te = _curve_progress(anim["curve"], anim["curve_area"], t)
            fx = anim["sx"] + (anim["ex"] - anim["sx"]) * te
            fy = anim["sy"] + (anim["ey"] - anim["sy"]) * te
            obj = anim["obj"]
            obj["_fx"] = fx
            obj["_fy"] = fy
            obj["x"] = int(round(fx))
            obj["y"] = int(round(fy))
            if anim["frame"] < anim["duration"]:
                remaining.append(anim)
            else:
                obj["x"] = int(round(anim["ex"]))
                obj["y"] = int(round(anim["ey"]))
                obj.pop("_fx", None)
                obj.pop("_fy", None)
            # Block pose changed — drop the cached solid AABB so the
            # next collision query rebuilds it at the new cell. The
            # cell/saw/spike AABB caches all live on the same object
            # dict, so invalidate them in lockstep.
            if "_srect" in obj:
                del obj["_srect"]
            if "_caabb" in obj:
                del obj["_caabb"]
            if "_saw_aabb" in obj:
                del obj["_saw_aabb"]
            if "_sphb_aabbs" in obj:
                del obj["_sphb_aabbs"]
            # Keep the spatial index in sync with the new (x, y) cell so
            # nearby_for_rect can find the moved object at its new location.
            self._spatial_rebucket(obj)
            # Track every object ever touched by a move animation so the
            # autobot's `_restore` can un-move entries that drifted since
            # the snapshot was taken.
            self._ever_moved[id(obj)] = obj
        self.move_animations = remaining

    def set_mode(self, mode):
        self.mode = mode
        if mode in (MODE_CUBE, MODE_BALL):
            self.angle = round(self.angle / 90) * 90
        elif mode in (MODE_WAVE, MODE_SWING):
            self.vy = 0.0
        elif mode == MODE_ROBOT:
            # Top up the budget AND unlock the thruster so a mid-air
            # portal-in gets the full budget of fuel. The robot's
            # normal landing refill keeps it synced after that.
            self.flight_budget = int(self.params.robot_flight_seconds * 60)
            self._robot_thrust_disabled = False

    def set_speed(self, speed_type):
        self.move_speed = SPEED_VALUES.get(speed_type, self.params.base_move_speed)

    def _set_size(self, new_size):
        """Change the player's bounding size while preserving the
        gravity-facing edge (feet for grav=1, head for grav=-1). This keeps
        the player visually planted on the current surface when a mini or
        big portal changes the size mid-level."""
        if new_size == self.size:
            return
        delta = self.size - new_size
        # Keep the gravity-facing edge anchored. For grav=1 (normal), the
        # feet are at y + size, so y must shift by +delta to keep feet put.
        # For grav=-1 (inverted), the head is at y, which is already anchored.
        if self.grav == 1:
            self.y += delta
        # Also re-center horizontally on the player's current centre so the
        # shrink doesn't pop sideways into a wall.
        self.x += delta / 2.0
        self.size = new_size
        if self.mirror:
            if -self.grav == 1:
                self.mirror["y"] += delta
            # Mirror x always follows main, so no x shift needed.

    def _enter_dual(self, obj=None):
        """Initialize a mirror body with opposite gravity. The mirror
        inherits the player's current motion state — vy, on_ground, angle —
        with vy and angle sign-flipped because the mirror runs under
        opposite gravity. That way a dual portal crossed mid-jump produces
        a symmetric arc instead of a stalled mirror that drops from rest.

        If the portal object carries a ``spawn_y`` cell row, the mirror
        spawns at the top of that cell. Otherwise the mirror y falls back
        to a symmetric placement around the screen's horizontal midline so
        existing levels keep their old behaviour.
        """
        if self.mirror is not None:
            return
        spawn_row = obj.get("spawn_y") if obj else None
        if spawn_row is not None:
            mirror_y = float(spawn_row) * CELL
        else:
            center = HEIGHT / 2.0
            mirror_y = 2.0 * center - self.y - self.size
        self.mirror = {
            "y": float(mirror_y),
            # Sign-flip vy: a player falling at +vy under +grav corresponds
            # to a mirror "falling" (toward its own ground) at -vy under
            # -grav. Both bodies trace symmetric arcs in screen space.
            "vy": -float(self.vy),
            "grav": -self.grav,
            # Inherit on_ground so a portal crossed mid-stride doesn't
            # spawn a mirror that "falls" out of a grounded pose. We read
            # _was_on_ground (captured at the top of update()) rather than
            # self.on_ground because the latter is reset to False before
            # the substep loop where this trigger fires; the pre-frame
            # value reflects whether the player was stably on ground.
            "on_ground": bool(getattr(self, "_was_on_ground", self.on_ground)),
            # Sign-flip angle so the mirror's rotation reads as a vertical
            # mirror image of the player.
            "angle": -float(getattr(self, "angle", 0.0)),
            "alive": True,
            # Mode and size start as cube + main's current size. Mode and
            # mini/big portals the mirror crosses change THESE fields only
            # — they don't sync to the main body. (See _handle_mirror_
            # interactions for the per-body portal handlers.)
            "mode": MODE_CUBE,
            "size": int(self.size),
            # Robot held-thrust budget for the mirror body. Starts full
            # so a robot-portal crossing immediately lets the mirror fly,
            # and refills on each mirror landing (see _step_mirror).
            "flight_budget": int(self.params.robot_flight_seconds * 60),
            # Robot air-release lock for the mirror. Cleared on landing
            # or on a fresh robot-portal entry (_set_mirror_mode).
            "thrust_disabled": False,
        }

    # ---- collision -------------------------------------------------------
    def _solid_rect(self, o):
        # Hot path: ~5M calls per bot solve. Returns a 4-tuple
        # ``(left, top, right, bottom)`` of integer pixel bounds so callers
        # can run inline AABB tests without paying for ``pygame.Rect``
        # construction or attribute lookups. Cached on the object dict;
        # ``_invalidate_solid_rect`` drops the cache when a move trigger
        # or rotation edits the block's pose.
        cached = o.get("_srect")
        if cached is not None:
            return cached
        t = o["t"]
        if t == T_BLOCK:
            sc = obj_scale(o)
            r = cell_rect(o["x"], o["y"], sc)
        elif t == T_SLAB:
            sc = obj_scale(o)
            r = slab_rect(o["x"], o["y"], o.get("r", 0), sc)
        else:
            # Slopes are diagonal — handled in _resolve_slopes after the
            # standard rect-collision pass. Returning None here keeps
            # them invisible to the rectangular x/y resolvers (which
            # would otherwise treat the bounding box as a wall and kill
            # on x). Don't cache the None — type filtering elsewhere
            # short-circuits before us.
            return None
        # Store as int tuple — Rect.left/.top/.right/.bottom attribute
        # access dominated the inner loops; tuple indexing is ~3× faster.
        aabb = (r.left, r.top, r.right, r.bottom)
        o["_srect"] = aabb
        return aabb

    @staticmethod
    def _invalidate_solid_rect(o):
        """Drop the cached solid AABB so the next ``_solid_rect`` call
        rebuilds it from the current x/y/scale/rotation. Called from
        move-trigger animation steps and any other site that mutates a
        block's pose. Also drops the trigger ``_caabb`` cache and saw /
        spike AABB caches so the next handle_interactions pass rebuilds
        at the new pose."""
        if "_srect" in o:
            del o["_srect"]
        if "_caabb" in o:
            del o["_caabb"]
        if "_saw_aabb" in o:
            del o["_saw_aabb"]
        if "_sphb_aabbs" in o:
            del o["_sphb_aabbs"]

    @staticmethod
    def _slope_orientation(o):
        """Snap the slope's free rotation to one of 4 cardinal cases.

        Returns ``r // 90`` mod 4: 0=/floor, 1=\\floor, 2=\\ceiling,
        3=/ceiling. Free rotation is allowed for the visual sprite but
        slope collision still snaps to the nearest 90° step — a 45°
        slope hitbox would have non-trivial axis-aligned resolution
        and isn't what the 1:1 ramp is for.
        """
        try:
            r = float(o.get("r", 0))
        except (TypeError, ValueError):
            r = 0.0
        return int(round(r / 90.0)) % 4

    def _slope_surface_y(self, o, player_left, player_right):
        """Return ``(surface_y, is_ceiling)`` for slope ``o`` based on
        the player's horizontal overlap with the slope's cell.

        Sampling the slope at the player's *center x* leaves the cube's
        leading edge poking into the next cell when the slope is
        rising (it embeds in the next solid block before the slope has
        a chance to lift the cube high enough). Instead, evaluate the
        slope at whichever overlap edge gives the most constraining
        surface — the highest point on a floor slope, the lowest point
        on a ceiling slope.
        """
        cell_left = o["x"] * CELL
        cell_right = cell_left + CELL
        px_l = max(player_left, cell_left)
        px_r = min(player_right, cell_right)
        if px_l > px_r:
            return None
        cell_top = o["y"] * CELL
        r = self._slope_orientation(o)
        is_ceiling = r >= 2
        # Pick the overlap edge that produces the binding surface.
        # / shape (r=0 floor, r=2 ceiling) rises as t grows — the high
        # point sits at the larger x. \ shape (r=1 floor, r=3 ceiling)
        # rises as t shrinks — the high point sits at the smaller x.
        # Floors want the high point (smallest y) so the cube doesn't
        # clip the slope; ceilings want the low point (largest y).
        if r == 0:
            x = px_r
        elif r == 1:
            x = px_l
        elif r == 2:
            x = px_l
        else:
            x = px_r
        t = (x - cell_left) / CELL
        if t < 0.0:
            t = 0.0
        elif t > 1.0:
            t = 1.0
        if r in (0, 2):
            surface_y = cell_top + (1.0 - t) * CELL
        else:
            surface_y = cell_top + t * CELL
        return (surface_y, is_ceiling)

    def _resolve_slopes(self):
        # Fast-out for slope-free levels — most levels have zero slopes,
        # but this method runs ~2× per substep regardless. The bool
        # gate makes the no-slope case a single attribute lookup.
        if not self._has_slopes:
            return
        self._resolve_slopes_inner()

    def _resolve_slopes_inner(self):
        """Snap the player to any nearby slope's diagonal surface.

        Called after the rect-based y-collision pass each substep. For
        each slope cell the player's bounding box overlaps:
          * Floor slope: if the player's bottom is below the surface
            line, lift them onto it (normal gravity rides on top).
          * Ceiling slope: if the player's top is above the surface
            line, drop them under it (inverted gravity rides under).

        The ``CELL + 4`` reach guard keeps the snap from teleporting a
        player that fell *below* the slope (e.g., off a cliff next to
        it) back onto the surface from far away — only a player that
        was already at slope height gets the ride. When two slopes
        overlap (or a slope sits next to another), the most-constraining
        surface wins (highest for floors, lowest for ceilings) so the
        player can't slip off through a gap.
        """
        size = self.size
        px = round(self.x)
        py = round(self.y)
        player_left = float(self.x)
        player_right = float(self.x + size)
        best_floor = None       # smallest surface_y among floor slopes
        best_ceiling = None     # largest surface_y among ceiling slopes
        for o in self._nearby_for_aabb(px, py, px + size, py + size):
            if o["t"] != T_SLOPE:
                continue
            result = self._slope_surface_y(o, player_left, player_right)
            if result is None:
                continue
            surface_y, is_ceiling = result
            if not is_ceiling:
                if best_floor is None or surface_y < best_floor:
                    best_floor = surface_y
            else:
                if best_ceiling is None or surface_y > best_ceiling:
                    best_ceiling = surface_y
        if best_floor is not None:
            player_bottom = self.y + self.size
            if (player_bottom > best_floor
                    and player_bottom <= best_floor + CELL + 4):
                self.y = best_floor - self.size
                if self.vy * self.grav > 0:
                    self.vy = 0.0
                if self.grav == 1:
                    self.on_ground = True
        if best_ceiling is not None:
            if (self.y < best_ceiling
                    and self.y >= best_ceiling - CELL - 4):
                self.y = best_ceiling
                if self.vy * self.grav > 0:
                    self.vy = 0.0
                if self.grav == -1:
                    self.on_ground = True

    def _check_ground_adjacency(self):
        """Set self.on_ground = True when the OUTER rect is sitting on a
        block surface, AND snap y / zero vy if the outer is dipping into
        a block from above (or below for inverted gravity). Without the
        snap, inner-hitbox collision creates a ~SOLID_HITBOX_FRACTION/2
        × size gap before triggering, so vy would accumulate and the
        player would visibly bounce on every grounded frame.

        The probe extends from the outer rect's edge into the would-be
        clipping zone — half the inner-hitbox gap — so any contact in
        that range counts as "feet on the floor"."""
        if not self.alive:
            return
        # The clipping zone is the gap between the outer edge and the
        # inner solid_hitbox edge. Probe just into that zone so a
        # newly-resolved player still registers as grounded.
        gap = max(2, int(self.size * (1.0 - SOLID_HITBOX_FRACTION) * 0.5))
        size = self.size
        px = round(self.x)
        py = round(self.y)
        if self.grav == 1:
            p_left = px
            p_right = px + size
            p_top = py + size - 1
        else:
            p_left = px
            p_right = px + size
            p_top = py - gap
        p_bottom = p_top + gap + 1
        _solid_rect = self._solid_rect
        for o in self._nearby_for_aabb(p_left, p_top, p_right, p_bottom):
            br = o.get("_srect")
            if br is None:
                br = _solid_rect(o)
                if br is None:
                    continue
            bl, bt, brr, bb = br
            if (p_left < brr and p_right > bl
                    and p_top < bb and p_bottom > bt):
                self.on_ground = True
                # Snap outer rect to the surface and zero vy so we don't
                # accumulate gravity while sitting on the block.
                if self.grav == 1 and self.vy >= 0:
                    self.y = bt - size
                    self.vy = 0.0
                elif self.grav == -1 and self.vy <= 0:
                    self.y = bb
                    self.vy = 0.0
                return

    def _check_mirror_ground_adjacency(self):
        """Mirror counterpart to _check_ground_adjacency."""
        m = self.mirror
        if m is None or not m.get("alive", False):
            return
        msize = int(m.get("size", PLAYER_SIZE))
        gap = max(2, int(msize * (1.0 - SOLID_HITBOX_FRACTION) * 0.5))
        px = round(self.x)
        py = round(m["y"])
        if m["grav"] == 1:
            p_left = px
            p_right = px + msize
            p_top = py + msize - 1
        else:
            p_left = px
            p_right = px + msize
            p_top = py - gap
        p_bottom = p_top + gap + 1
        _solid_rect = self._solid_rect
        for o in self._nearby_for_aabb(p_left, p_top, p_right, p_bottom):
            br = o.get("_srect")
            if br is None:
                br = _solid_rect(o)
                if br is None:
                    continue
            bl, bt, brr, bb = br
            if (p_left < brr and p_right > bl
                    and p_top < bb and p_bottom > bt):
                m["on_ground"] = True
                if m["grav"] == 1 and m["vy"] >= 0:
                    m["y"] = float(bt - msize)
                    m["vy"] = 0.0
                elif m["grav"] == -1 and m["vy"] <= 0:
                    m["y"] = float(bb)
                    m["vy"] = 0.0
                return

    def _resolve_x_collision(self, dx_step):
        # Two-hitbox model: nearby_for_rect uses the OUTER rect (broad
        # phase — anything within a cell of the player's footprint) but
        # the actual collision trigger is the small centred solid_hitbox.
        # That makes corner clipping forgiving without pretending blocks
        # outside the broad phase don't exist.
        size = self.size
        px = round(self.x)
        py = round(self.y)
        # Inline solid_hitbox bounds — avoids a pygame.Rect alloc per
        # call (this path runs millions of times in a bot solve).
        inner = max(2, int(size * SOLID_HITBOX_FRACTION))
        cx = px + size // 2
        cy = py + size // 2
        sh_left = cx - inner // 2
        sh_top = cy - inner // 2
        sh_right = sh_left + inner
        sh_bottom = sh_top + inner
        # Outer-rect AABB for the broad phase — fed straight to the
        # bounds-based nearby query so we never alloc a Rect.
        # Inline the _solid_rect cache hit (`o.get("_srect")`) and only
        # fall back to the method on miss; the method-call overhead
        # alone was several seconds of bot solve time.
        _solid_rect = self._solid_rect
        for o in self._nearby_for_aabb(px, py, px + size, py + size):
            br = o.get("_srect")
            if br is None:
                br = _solid_rect(o)
                if br is None:
                    continue
            bl, bt, brr, bb = br
            if (sh_left < brr and sh_right > bl
                    and sh_top < bb and sh_bottom > bt):
                if dx_step > 0:
                    self.x = bl - size
                elif dx_step < 0:
                    self.x = brr
                self.alive = False
                self.death_reason = "Crashed into a wall"
                return True
        return False

    def _resolve_y_collision(self, dy_step):
        # Broad phase against the outer rect, narrow phase against the
        # small inner solid_hitbox — same split as the x pass. Resolution
        # snaps the OUTER rect to the block edge so the player visually
        # rests cleanly on top / against the block.
        size = self.size
        px = round(self.x)
        py = round(self.y)
        # Inline solid_hitbox bounds.
        inner = max(2, int(size * SOLID_HITBOX_FRACTION))
        size_half = size // 2
        inner_half = inner // 2
        cx = px + size_half
        cy = py + size_half
        sh_left = cx - inner_half
        sh_top = cy - inner_half
        sh_right = sh_left + inner
        sh_bottom = sh_top + inner
        # Filter to only blocks whose AABB intersects the inner hitbox.
        # Sorting all broad-phase candidates wasted time on blocks that
        # never collide; sort just the narrow-phase hits instead.
        hits = []
        _solid_rect = self._solid_rect
        for o in self._nearby_for_aabb(px, py, px + size, py + size):
            br = o.get("_srect")
            if br is None:
                br = _solid_rect(o)
                if br is None:
                    continue
            bl, bt, brr, bb = br
            if (sh_left < brr and sh_right > bl
                    and sh_top < bb and sh_bottom > bt):
                hits.append(br)
        if not hits:
            return False
        if len(hits) > 1:
            if dy_step > 0:
                hits.sort(key=lambda b: b[1])
            elif dy_step < 0:
                hits.sort(key=lambda b: -b[1])
        for br in hits:
            bl, bt, brr, bb = br
            # Re-check after snapping shifts the inner hitbox: a
            # subsequent block may now be out of contact.
            if not (sh_left < brr and sh_right > bl
                    and sh_top < bb and sh_bottom > bt):
                continue
            if self.grav == 1:
                if dy_step >= 0:
                    self.y = bt - size
                    self.vy = 0.0
                    self.on_ground = True
                else:
                    self.y = bb
                    self.vy = 0.0
            else:
                if dy_step <= 0:
                    self.y = bb
                    self.vy = 0.0
                    self.on_ground = True
                else:
                    self.y = bt - size
                    self.vy = 0.0
            py = round(self.y)
            cy = py + size_half
            sh_top = cy - inner_half
            sh_bottom = sh_top + inner
        return False

    # ---- interactions ----------------------------------------------------
    def _handle_interactions(self, trigger_rect, hazard_rect, input_active):
        # End walls are infinite-height: any x-overlap with the wall column
        # wins, *if the player was behind the wall at the start of the frame*.
        # The frame-start gate prevents teleport orbs that sweep backward
        # through the finish column from triggering a premature win; if
        # you were already past the wall at tick start, you'd have won
        # already the previous frame.
        tr_left = trigger_rect.left
        tr_right = trigger_rect.right
        tr_top = trigger_rect.top
        tr_bottom = trigger_rect.bottom
        # Hazard AABB extracted once — saw / spike collision tests inline
        # the AABB overlap on these int bounds rather than alloc-ing
        # rects via colliderect each pass.
        hz_left = hazard_rect.left
        hz_right = hazard_rect.right
        hz_top = hazard_rect.top
        hz_bottom = hazard_rect.bottom
        # Outer rotated OBB used for hazard checks. A square rotated
        # by any multiple of 90° is still axis-aligned, so the cheap
        # AABB pre-filter is exact in those cases — only off-axis
        # rotations actually need SAT.
        outer_obb = None
        _ang_mod = self.angle % 90.0
        outer_use_obb = 0.5 < _ang_mod < 89.5
        prev_right = getattr(self, "_x_at_frame_start", self.x) + self.size
        for wall_x in self._end_walls_x:
            # Overlap test against the wall column plus a "was behind at
            # frame start" gate. The gate rejects wins caused by teleport
            # sweeps that briefly pass through the wall from in front to
            # behind (or that end behind it).
            if (tr_right > wall_x and tr_left < wall_x + CELL
                    and prev_right <= wall_x):
                self.won = True
                return True
        activated_orb_cell = None
        # Trigger-only iteration — see Player._rebuild_spatial_index. The
        # ``if t in SOLID_TYPES or t == T_START: continue`` guard is now
        # implicit in the index itself, so on a block-heavy level this
        # loop iterates ~5× fewer objects.
        for o in self._nearby_triggers_for_aabb(
                tr_left, tr_top, tr_right, tr_bottom, 2):
            t = o["t"]
            key = (t, o["x"], o["y"])
            if t in (T_SPIKE, T_HALF_SPIKE):
                # Spike hitbox AABBs cached as int tuples on the
                # object — spike_hitboxes() rebuild was 0.25s of bot
                # solve time before. Stationary spikes never need
                # invalidation; rotated/scaled ones get cleared
                # alongside _srect/_caabb.
                sphbs = o.get("_sphb_aabbs")
                if sphbs is None:
                    sc = obj_scale(o)
                    sphbs = []
                    for sr in spike_hitboxes(o["x"], o["y"],
                                             o.get("r", 0),
                                             t == T_HALF_SPIKE, sc):
                        sphbs.append((sr.left, sr.top,
                                      sr.right, sr.bottom))
                    o["_sphb_aabbs"] = sphbs
                for sl, st, sr_r, sb in sphbs:
                    # Fast AABB pre-filter against the player outer.
                    if not (hz_left < sr_r and hz_right > sl
                            and hz_top < sb and hz_bottom > st):
                        continue
                    if outer_use_obb:
                        # Narrow phase: rotated outer OBB vs spike AABB
                        # via SAT. Catches the case where the AABB
                        # straddles the spike but the rotated player
                        # body actually misses.
                        if outer_obb is None:
                            outer_obb = self._outer_obb_corners()
                        if not _obb_aabb_overlap(outer_obb, sl, st, sr_r, sb):
                            continue
                    self.alive = False
                    self.death_reason = "Hit a spike"
                    return True
                continue
            if t == T_SAW:
                # Saw hitbox is a single AABB cached as an int tuple.
                # ~7.7M saw_hitbox calls / 4s in a bot solve before;
                # the cache turns each into an `o.get` + 4-int compare.
                saabb = o.get("_saw_aabb")
                if saabb is None:
                    sc = obj_scale(o)
                    sr = saw_hitbox(o["x"], o["y"], sc)
                    saabb = (sr.left, sr.top, sr.right, sr.bottom)
                    o["_saw_aabb"] = saabb
                sl, st, sr_r, sb = saabb
                if not (hz_left < sr_r and hz_right > sl
                        and hz_top < sb and hz_bottom > st):
                    continue
                if outer_use_obb:
                    if outer_obb is None:
                        outer_obb = self._outer_obb_corners()
                    if not _obb_aabb_overlap(outer_obb, sl, st, sr_r, sb):
                        continue
                self.alive = False
                self.death_reason = "Hit a saw"
                return True
            if t in PAD_TYPES and key not in self.passed:
                if trigger_rect.colliderect(pad_trigger_rect(o["x"], o["y"], o.get("r", 0))):
                    if t == T_BLUE_PAD:
                        self.flip_gravity()
                        self.vy = self.params.pad_force * 0.5 * self.grav
                    elif self.mode == MODE_SHIP:
                        self.vy = self.params.jump_force * 0.95 * self.grav
                    elif self.mode != MODE_WAVE:
                        self.vy = self.params.pad_force * self.grav
                    self.on_ground = False
                    self.passed.add(key)
                continue
            # Cell AABB cache: most trigger objects are stationary, so
            # paying cell_rect's branch + Rect alloc on every substep
            # was wasted. Drop into a cached int AABB tuple (parallel
            # to ``_srect``); ``_invalidate_solid_rect`` clears
            # ``_caabb`` too on any move/rotate trigger pose change.
            caabb = o.get("_caabb")
            if caabb is None:
                cr = cell_rect(o["x"], o["y"], obj_scale(o))
                caabb = (cr.left, cr.top, cr.right, cr.bottom)
                o["_caabb"] = caabb
            cl, ct, crr, cb = caabb
            if not (tr_left < crr and tr_right > cl
                    and tr_top < cb and tr_bottom > ct):
                continue
            if t == T_COIN:
                cid = o.get("coin_id", 0)
                if cid and cid not in self.coins_collected:
                    self.coins_collected.add(cid)
                continue
            # T_CHECKPOINT was removed from the editor — checkpoints
            # are a player-session mechanic (placed with the C key in
            # practice mode), not level data. Any old level files with
            # checkpoint objects get stripped on load (see levels.py).
            if t in ORB_TYPES and key not in self.passed:
                cell = (o["x"], o["y"])
                if activated_orb_cell is None:
                    # Orbs fire whenever the input is "active" — held
                    # OR within the post-press buffer window. The
                    # previous check was buffer-only, which let the
                    # bot's (held=True, pressed=False) sequences (the
                    # cube auto-jump path) sail through orbs without
                    # firing them: buffer was 0 the whole time, the
                    # cube still bunny-hopped via mode_held, and the
                    # bot's path "ignored" every orb on the route.
                    # Holding the button now correctly activates orbs
                    # the player crosses, matching how a human's
                    # held-button play fires orbs in standard GD.
                    if not input_active:
                        continue
                    if t == T_TELEPORT_ORB and self.teleport_cooldown != 0:
                        continue
                    activated_orb_cell = cell
                elif cell != activated_orb_cell:
                    continue
                if t == T_ORB:
                    self.activate_orb()
                    self.passed.add(key)
                elif t == T_RED_ORB:
                    self.activate_red_orb()
                    self.passed.add(key)
                elif t == T_PINK_ORB:
                    self.activate_pink_orb()
                    self.passed.add(key)
                elif t == T_DASH_ORB:
                    self.activate_dash_orb(o)
                    self.passed.add(key)
                elif t == T_BLACK_ORB:
                    self.activate_black_orb()
                    self.passed.add(key)
                elif t == T_BLUE_ORB:
                    self.activate_blue_orb()
                    self.passed.add(key)
                elif t == T_GREEN_ORB:
                    self.activate_green_orb()
                    self.passed.add(key)
                elif t == T_SPIDER_ORB:
                    self.activate_spider_orb(o)
                    self.passed.add(key)
                elif t == T_TELEPORT_ORB and self.teleport_cooldown == 0:
                    self.activate_teleport(o)
                    self.passed.add(key)
                    self.input_buffer = 0
                    return False
                continue
            if t in (T_GRAV_UP, T_GRAV_DOWN) and key not in self.passed:
                # SET gravity (rather than flip): blue forces grav=-1 (up),
                # yellow forces grav=1 (down). No-op when already pointing
                # that way so the player isn't bumped off the ground.
                target = -1 if t == T_GRAV_UP else 1
                if self.grav != target:
                    self.grav = target
                    self.on_ground = False
                self.passed.add(key)
            elif t in MODE_FROM_TYPE and key not in self.passed:
                self.set_mode(MODE_FROM_TYPE[t])
                # Per-portal "free_mode" toggle. Each gamemode portal
                # decides whether the camera should follow the player
                # vertically while that mode runs — un-flagged portals
                # explicitly turn it OFF so authors can drop a vanilla
                # portal to hand control back to camera triggers.
                self.free_cam_mode = bool(o.get("free_mode", False))
                self.passed.add(key)
            elif t == T_MODE_MINI and key not in self.passed:
                self._set_size(MINI_PLAYER_SIZE)
                self.passed.add(key)
            elif t == T_MODE_BIG and key not in self.passed:
                self._set_size(PLAYER_SIZE)
                self.passed.add(key)
            elif t == T_MODE_DUAL and key not in self.passed:
                self._enter_dual(o)
                self.passed.add(key)
            elif t == T_MODE_SOLO and key not in self.passed:
                self.mirror = None
                self.passed.add(key)
            elif t in SPEED_VALUES and key not in self.passed:
                self.set_speed(t)
                self.passed.add(key)
            elif t == T_CAMERA_TRIGGER and key not in self.passed:
                target_row = o.get("cy", o["y"])
                self.target_cam_y = target_row * CELL + CELL / 2 - HEIGHT / 2
                self.passed.add(key)
            elif t == T_BG_TRIGGER and key not in self.passed:
                self.bg_preset = int(o.get("bg", 0))
                self.passed.add(key)
            elif t == T_MOVE_TRIGGER and key not in self.passed:
                self._start_move_trigger(o)
                self.passed.add(key)
            elif t == T_COLOR_TRIGGER and key not in self.passed:
                self.color_index = (self.color_index + 1) % len(PLAYER_COLORS)
                self.player_color = PLAYER_COLORS[self.color_index]
                self.passed.add(key)
            elif t == T_PULSE_TRIGGER and key not in self.passed:
                bpm = int(o.get("bpm", 128))
                duration_s = float(o.get("duration", 2.0))
                # Convert seconds to frames (60 FPS canonical).
                frames = max(1, int(duration_s * 60))
                self.active_pulses.append({
                    "start_frame": self.frame,
                    "end_frame": self.frame + frames,
                    "bpm": bpm,
                })
                self.passed.add(key)
            elif t == T_ROTATE_TRIGGER and key not in self.passed:
                self._start_rotate_trigger(o)
                self.passed.add(key)
            elif t == T_FOLLOW_TRIGGER and key not in self.passed:
                # always_on follows are activated by player.reset()
                # at level-start, so by the time the live player
                # crosses one of those it already has its link and
                # this branch is a no-op (the dedup inside
                # _start_follow_trigger handles it). Manual follows
                # arm the link the moment the player passes through.
                if not o.get("always_on"):
                    self._start_follow_trigger(o)
                self.passed.add(key)
            elif t == T_TIME_WARP and key not in self.passed:
                # Latch the new time-scale on the player. play.py reads
                # ``self.time_warp`` each frame and folds it into
                # ``step_scale`` so the sim accumulator advances faster
                # or slower without otherwise touching physics tuning.
                # Persistent until another T_TIME_WARP (or a death
                # reset) — same model as the speed portals.
                try:
                    self.time_warp = float(o.get("factor", 1.0))
                except (TypeError, ValueError):
                    self.time_warp = 1.0
                self.passed.add(key)
            # T_END is handled at the top of this method as a column wall.
        if activated_orb_cell is not None:
            self.input_buffer = 0
        return False

    # ---- dual-mode mirror ------------------------------------------------
    def _step_mirror(self, input_held, input_pressed):
        """Update the dual-mode mirror body. The mirror shares x with the
        main player (its x always equals self.x) and has independent y
        physics, gravity, mode, and size. Mode portals the mirror crosses
        change `m["mode"]` only — they don't sync to the main body.

        If the mirror hits a hazard or falls off-screen, sets
        mirror["alive"]=False so the main update loop can kill the player.
        """
        m = self.mirror
        if not m["alive"]:
            return
        msize = int(m["size"])
        mmode = m.get("mode", MODE_CUBE)
        # The mirror shares the main body's hold-consumed gate so a
        # spider orb fired by either body fully consumes the click —
        # otherwise the mirror would keep thrusting / wave-climbing /
        # auto-jumping on the new surface from the same hold.
        mode_held = input_held and not self._hold_consumed
        mode_pressed = input_pressed and not self._hold_consumed
        # ---- per-mode vy and input handling ----
        # Mirrors update()'s mode dispatch but writes into m["vy"] /
        # m["on_ground"] instead of self.vy / self.on_ground.
        if mmode == MODE_SHIP:
            m["vy"] += self.params.ship_gravity * m["grav"]
            if mode_held:
                m["vy"] -= self.params.ship_thrust * m["grav"]
            m["vy"] = clamp(m["vy"], -13.0, 13.0)
        elif mmode == MODE_WAVE:
            direction = -1 if mode_held else 1
            target_vy = self.move_speed * direction * m["grav"]
            # Same low-pass as the main body's wave physics — rapid
            # toggles average toward straight rather than jittering.
            m["vy"] = m["vy"] * 0.6 + target_vy * 0.4
        elif mmode == MODE_UFO:
            m["vy"] += self.params.gravity * m["grav"]
            m["vy"] = clamp(m["vy"], -18.0, 18.0)
            if mode_held and m["on_ground"]:
                m["vy"] = self.params.jump_force * m["grav"]
                m["on_ground"] = False
            elif mode_pressed and not m["on_ground"]:
                m["vy"] = self.params.ufo_jump_force * m["grav"]
        elif mmode == MODE_SPIDER:
            m["vy"] += self.params.gravity * m["grav"]
            m["vy"] = clamp(m["vy"], -18.0, 18.0)
            if mode_pressed and m["on_ground"]:
                self._mirror_spider_teleport()
        elif mmode == MODE_SWING:
            m["vy"] += self.params.gravity * m["grav"]
            m["vy"] = clamp(m["vy"], -18.0, 18.0)
            if mode_pressed:
                m["grav"] = -m["grav"]
                m["on_ground"] = False
        elif mmode == MODE_BALL:
            m["vy"] += self.params.gravity * m["grav"]
            m["vy"] = clamp(m["vy"], -18.0, 18.0)
            if mode_pressed and m["on_ground"]:
                m["grav"] = -m["grav"]
                m["vy"] = self.params.ball_flip_force * m["grav"]
                m["on_ground"] = False
        elif mmode == MODE_ROBOT:
            # Mirror robot: same one-shot held-thrust mechanic as main,
            # with its own flight budget AND its own air-release lock so
            # the two bodies don't share fuel or thrust state. Releasing
            # the button mid-air locks the mirror's thruster until it
            # lands again. Same 30% climb cap as the main body.
            if not input_held and not m["on_ground"]:
                m["thrust_disabled"] = True
            m["vy"] += self.params.gravity * m["grav"]
            budget = m.get("flight_budget", 0)
            if (mode_held and budget > 0
                    and not m.get("thrust_disabled", False)):
                m["vy"] -= self.params.robot_thrust * m["grav"]
                m["flight_budget"] = budget - 1
                if m["on_ground"]:
                    m["on_ground"] = False
            if m["grav"] == 1:
                m["vy"] = clamp(m["vy"], -5.4, 18.0)
            else:
                m["vy"] = clamp(m["vy"], -18.0, 5.4)
        else:  # MODE_CUBE (default)
            m["vy"] += self.params.gravity * m["grav"]
            m["vy"] = clamp(m["vy"], -18.0, 18.0)
            if mode_held and m["on_ground"]:
                m["vy"] = self.params.jump_force * m["grav"]
                m["on_ground"] = False
        m["on_ground"] = False
        # Track the pre-step y so the hazard sweep below covers the full
        # vertical travel — a spike between prev_y and final y would
        # otherwise be missed when |vy| > the ±6 trigger inflate.
        prev_y = m["y"]
        # Step y in small substeps so we don't tunnel through thin platforms.
        # `mrect` is allocated once and reused via topleft assignment — see
        # A7 in CR4 for why the allocation rate matters on fast falls. The
        # per-substep px budget is the canonical COLLISION_SUBSTEP_PX so a
        # single tunable controls collision precision and hitbox-overlay
        # density across both bodies.
        steps = max(1, int(math.ceil(abs(m["vy"]) / COLLISION_SUBSTEP_PX)))
        dy_step = m["vy"] / steps
        mrect = pygame.Rect(round(self.x), round(m["y"]), msize, msize)
        # Inline solid_hitbox bounds — same shape as
        # ``_solid_hitbox_at`` but without the per-call Rect alloc.
        inner = max(2, int(msize * SOLID_HITBOX_FRACTION))
        inner_half = inner // 2
        size_half = msize // 2
        for _ in range(steps):
            m["y"] += dy_step
            mx = round(self.x)
            my = round(m["y"])
            mrect.topleft = (mx, my)
            cx = mx + size_half
            cy = my + size_half
            mhit_left = cx - inner_half
            mhit_top = cy - inner_half
            mhit_right = mhit_left + inner
            mhit_bottom = mhit_top + inner
            _solid_rect = self._solid_rect
            for o in self.nearby_for_rect(mrect):
                br = o.get("_srect")
                if br is None:
                    br = _solid_rect(o)
                    if br is None:
                        continue
                bl, bt, brr, bb = br
                if (mhit_left < brr and mhit_right > bl
                        and mhit_top < bb and mhit_bottom > bt):
                    if m["grav"] == 1:
                        if dy_step >= 0:
                            m["y"] = bt - msize
                            m["vy"] = 0.0
                            m["on_ground"] = True
                        else:
                            m["y"] = bb
                            m["vy"] = 0.0
                    else:
                        if dy_step <= 0:
                            m["y"] = bb
                            m["vy"] = 0.0
                            m["on_ground"] = True
                        else:
                            m["y"] = bt - msize
                            m["vy"] = 0.0
                    mx = round(self.x)
                    my = round(m["y"])
                    mrect.topleft = (mx, my)
                    cx = mx + size_half
                    cy = my + size_half
                    mhit_left = cx - inner_half
                    mhit_top = cy - inner_half
                    mhit_right = mhit_left + inner
                    mhit_bottom = mhit_top + inner
        # Off-screen kill
        if m["y"] > HEIGHT + 300 or m["y"] < -500:
            m["alive"] = False
            return
        # Same outer-rect adjacency probe the main body uses, so the
        # mirror's on_ground stays sticky after an inner-hitbox y-resolve.
        self._check_mirror_ground_adjacency()
        # Refill the mirror's robot flight budget AND clear its
        # air-release lock the moment it lands.
        if mmode == MODE_ROBOT and m["on_ground"]:
            m["flight_budget"] = int(self.params.robot_flight_seconds * 60)
            m["thrust_disabled"] = False
        # Hazard collision (spikes, saws) using mirror's hitbox. Sweep the
        # union of the pre-step and post-step rects so fast vertical moves
        # (UFO / spider at max vy) can't tunnel past a spike between
        # substeps. Both the broad-phase trigger_rect and the narrow-phase
        # hazard_rect are widened to the union — otherwise a spike halfway
        # through the sweep would be in trigger_rect but miss hazard_rect.
        # AABB pre-filter is shrunk for grace; OBB narrow phase below
        # uses the full rotated outer so OUTER still authoritatively
        # detects hazards (matches the two-hitbox design).
        shrink = max(2, int(6 * msize / PLAYER_SIZE))
        final_rect = pygame.Rect(round(self.x), round(m["y"]),
                                 msize, msize)
        prev_rect = pygame.Rect(round(self.x), round(prev_y),
                                msize, msize)
        prev_hazard = pygame.Rect(
            round(self.x) + shrink, round(prev_y) + shrink,
            msize - shrink * 2, msize - shrink * 2)
        final_hazard = pygame.Rect(
            round(self.x) + shrink, round(m["y"]) + shrink,
            msize - shrink * 2, msize - shrink * 2)
        hazard_rect = prev_hazard.union(final_hazard)
        trigger_rect = prev_rect.union(final_rect).inflate(6, 6)
        hz_left = hazard_rect.left
        hz_right = hazard_rect.right
        hz_top = hazard_rect.top
        hz_bottom = hazard_rect.bottom
        for o in self._nearby_triggers_for_aabb(
                trigger_rect.left, trigger_rect.top,
                trigger_rect.right, trigger_rect.bottom, 2):
            t = o["t"]
            if t in (T_SPIKE, T_HALF_SPIKE):
                sphbs = o.get("_sphb_aabbs")
                if sphbs is None:
                    sc = obj_scale(o)
                    sphbs = []
                    for sr in spike_hitboxes(o["x"], o["y"],
                                             o.get("r", 0),
                                             t == T_HALF_SPIKE, sc):
                        sphbs.append((sr.left, sr.top,
                                      sr.right, sr.bottom))
                    o["_sphb_aabbs"] = sphbs
                for sl, st, sr_r, sb in sphbs:
                    if (hz_left < sr_r and hz_right > sl
                            and hz_top < sb and hz_bottom > st):
                        m["alive"] = False
                        return
            elif t == T_SAW:
                saabb = o.get("_saw_aabb")
                if saabb is None:
                    sc = obj_scale(o)
                    sr = saw_hitbox(o["x"], o["y"], sc)
                    saabb = (sr.left, sr.top, sr.right, sr.bottom)
                    o["_saw_aabb"] = saabb
                sl, st, sr_r, sb = saabb
                if (hz_left < sr_r and hz_right > sl
                        and hz_top < sb and hz_bottom > st):
                    m["alive"] = False
                    return
        # Pads / orbs / gravity portal / mode portals / solo portal collapse.
        # Returns True if the mirror collapsed back into the main player —
        # in that case stop touching m (it's None now) and skip rotation.
        # Use the mirror's own input_buffer here so a single click registers
        # for the mirror's orb even if the main already consumed its buffer
        # this frame.
        input_active = input_held or self.mirror_input_buffer > 0
        if self._handle_mirror_interactions(trigger_rect, input_active,
                                            input_pressed):
            return
        # ---- visual rotation (mode-specific, mirrors update()'s logic) ----
        cur_angle = m.get("angle", 0.0)
        mmode = m.get("mode", MODE_CUBE)  # may have changed via portal above
        if mmode == MODE_SHIP:
            m["angle"] = clamp(-m["vy"] * 4.2, -55, 55)
        elif mmode == MODE_UFO:
            m["angle"] = clamp(-m["vy"] * 2.8, -30, 30)
        elif mmode == MODE_WAVE:
            # Match main-body wave: low-pass-filter vy first, then ease
            # the angle toward a target proportional to the smoothed
            # commitment. Cancels the jitter at up→down input flips.
            # Lerp factor matches the main wave (0.55 / 0.45) — was
            # 0.78 / 0.22 which felt sluggish.
            self._mirror_wave_vy_smooth = (
                self._mirror_wave_vy_smooth * 0.55 + m["vy"] * 0.45)
            v = self._mirror_wave_vy_smooth
            speed = max(1.0, self.move_speed)
            commit = clamp(v / speed, -1.0, 1.0)
            target_a = -commit * self.params.wave_angle
            m["angle"] = cur_angle * 0.55 + target_a * 0.45
        elif mmode == MODE_BALL:
            if m["on_ground"]:
                m["angle"] = round(cur_angle / 90) * 90
            else:
                m["angle"] = cur_angle - 10 * m["grav"]
        elif mmode == MODE_SPIDER:
            if m["on_ground"]:
                m["angle"] = 0
            else:
                m["angle"] = cur_angle - 6 * m["grav"]
        else:  # cube
            if not m["on_ground"]:
                m["angle"] = cur_angle - 5 * m["grav"]
            else:
                m["angle"] = round(cur_angle / 90) * 90

    def _mirror_spider_teleport(self, direction=None):
        """Spider teleport for the mirror body.

        Mirrors `_spider_teleport`'s directional semantics: ``direction``
        is ``(dx, dy)`` — ``None`` falls back to against-gravity along
        the mirror's own ``m["grav"]``. Horizontal teleports keep the
        mirror's gravity; vertical teleports flip it (so the mirror
        clings to the opposite surface)."""
        m = self.mirror
        msize = int(m["size"])
        if direction is None:
            direction = (0, -m["grav"])
        dx, dy = direction
        probe = pygame.Rect(round(self.x), round(m["y"]), msize, msize)
        best = None  # (dist, new_x, new_y)
        probe_left = probe.left
        probe_right = probe.right
        probe_top = probe.top
        probe_bottom = probe.bottom
        if dy != 0 and dx == 0:
            left_cell = int(probe_left // CELL)
            right_cell = int((probe_right - 1) // CELL)
            for (gx, _gy), bucket in self._spatial_index.items():
                if gx < left_cell - 1 or gx > right_cell + 1:
                    continue
                for o in bucket:
                    br = self._solid_rect(o)
                    if br is None:
                        continue
                    bl, bt, brr, bb = br
                    if not (bl < probe_right and brr > probe_left):
                        continue
                    if dy < 0:
                        if bb <= probe_top:
                            dist = probe_top - bb
                            if best is None or dist < best[0]:
                                best = (dist, self.x, float(bb))
                    else:
                        if bt >= probe_bottom:
                            dist = bt - probe_bottom
                            if best is None or dist < best[0]:
                                best = (dist, self.x,
                                        float(bt - msize))
        elif dx != 0 and dy == 0:
            top_cell = int(probe_top // CELL)
            bot_cell = int((probe_bottom - 1) // CELL)
            for (_gx, gy), bucket in self._spatial_index.items():
                if gy < top_cell - 1 or gy > bot_cell + 1:
                    continue
                for o in bucket:
                    br = self._solid_rect(o)
                    if br is None:
                        continue
                    bl, bt, brr, bb = br
                    if not (bt < probe_bottom and bb > probe_top):
                        continue
                    if dx > 0:
                        if bl >= probe_right:
                            dist = bl - probe_right
                            if best is None or dist < best[0]:
                                best = (dist, float(bl - msize),
                                        m["y"])
                    else:
                        if brr <= probe_left:
                            dist = probe_left - brr
                            if best is None or dist < best[0]:
                                best = (dist, float(brr), m["y"])
        if best is not None:
            # Same swept hazard check as _spider_teleport so the mirror
            # can't phase through spikes on its jump either. Mirror x
            # follows main's x, so the horizontal-teleport case leaves
            # the mirror decoupled from the main body for one frame —
            # _step_mirror resynchronises on the next tick. We still
            # sweep from the mirror's actual travel endpoints here so
            # the hazard check covers the right volume.
            from .graphics import spike_hitboxes as _sh, saw_hitbox as _saw
            prev_x = self.x
            prev_y = m["y"]
            new_x = float(best[1])
            new_y = float(best[2])
            # AABB pre-filter shrunk for grace; OBB narrow phase
            # (further below) uses full outer.
            shrink = max(2, int(6 * msize / PLAYER_SIZE))
            pre_hazard = pygame.Rect(
                round(prev_x) + shrink, round(prev_y) + shrink,
                msize - shrink * 2, msize - shrink * 2)
            post_hazard = pygame.Rect(
                round(new_x) + shrink, round(new_y) + shrink,
                msize - shrink * 2, msize - shrink * 2)
            swept = pre_hazard.union(post_hazard)
            for o in self.nearby_for_rect(swept.inflate(6, 6), 2):
                t = o["t"]
                if t in (T_SPIKE, T_HALF_SPIKE):
                    sc = obj_scale(o)
                    for sr in _sh(o["x"], o["y"], o.get("r", 0),
                                  t == T_HALF_SPIKE, sc):
                        if swept.colliderect(sr):
                            m["alive"] = False
                            return
                elif t == T_SAW:
                    sc = obj_scale(o)
                    if swept.colliderect(_saw(o["x"], o["y"], sc)):
                        m["alive"] = False
                        return
            # 60 Hz sampling: end-of-frame _record_mirror_hitbox covers
            # the post-teleport pose. Trail beam samples are still
            # filled so the visual line trail draws as a continuous
            # band between pre- and post-teleport positions.
            beam_step = max(8, msize // 2)
            dx_b = new_x - prev_x
            dy_b = new_y - prev_y
            beam_len = (dx_b * dx_b + dy_b * dy_b) ** 0.5
            beam_n = max(1, int(beam_len // beam_step))
            cur_angle = m.get("angle", 0.0)
            for i in range(beam_n + 1):
                t = i / beam_n if beam_n else 0.0
                bx = prev_x + dx_b * t
                by = prev_y + dy_b * t
                self.mirror_trail.append([bx, by, cur_angle, 100])
            m["y"] = new_y
            if dy != 0:
                m["grav"] = -m["grav"]
            m["vy"] = 0.0
            m["on_ground"] = False

    def _set_mirror_size(self, new_size):
        """Resize the mirror body while keeping its gravity-facing edge
        anchored — same trick as `_set_size` but on m["size"] / m["y"]."""
        m = self.mirror
        if m is None or new_size == m["size"]:
            return
        delta = m["size"] - new_size
        # For grav=1 the feet are at y+size, so y shifts by +delta to keep
        # them planted; for grav=-1 the head is at y, already anchored.
        if m["grav"] == 1:
            m["y"] += delta
        m["size"] = int(new_size)

    def _set_mirror_mode(self, new_mode):
        """Change the mirror's mode with the same per-mode entry tweaks
        `set_mode` applies to the main body — snap angle to a right angle
        for cube/ball, zero vy for wave so it doesn't keep falling."""
        m = self.mirror
        if m is None:
            return
        m["mode"] = new_mode
        if new_mode in (MODE_CUBE, MODE_BALL):
            m["angle"] = round(m.get("angle", 0.0) / 90) * 90
        elif new_mode in (MODE_WAVE, MODE_SWING):
            m["vy"] = 0.0
        elif new_mode == MODE_ROBOT:
            m["flight_budget"] = int(self.params.robot_flight_seconds * 60)
            m["thrust_disabled"] = False

    def _handle_mirror_interactions(self, trigger_rect, input_active,
                                    input_pressed):
        """Mirror-side interaction pass: pads, orbs, gravity / mode / size
        portals, the solo portal (which collapses the mirror state into the
        main player), and global triggers. Hazards are handled in
        _step_mirror.

        Mode and size portals (mini/big/cube/ship/ball/wave/ufo/spider) and
        the gravity portal are tracked in ``self.mirror_passed`` so they
        fire independently for the mirror — the main body still consumes
        them via ``self.passed``. Triggers, orbs, pads and coins remain in
        the shared ``self.passed`` set since they represent global one-shot
        effects (a coin can only be collected once; a colour trigger only
        flips the palette once).

        Returns True if the mirror was just collapsed (caller must stop
        touching ``self.mirror``)."""
        m = self.mirror
        tr_left = trigger_rect.left
        tr_right = trigger_rect.right
        tr_top = trigger_rect.top
        tr_bottom = trigger_rect.bottom
        activated_orb_cell = None
        # Trigger-only iteration — solids and slopes were filtered here
        # before but the dedicated index now omits them upstream. The
        # mirror still skips spikes/saws/end (handled in _step_mirror's
        # hazard pass and the main body's wall logic).
        for o in self._nearby_triggers_for_aabb(
                tr_left, tr_top, tr_right, tr_bottom, 2):
            t = o["t"]
            if t in (T_END, T_SPIKE, T_HALF_SPIKE, T_SAW):
                continue
            key = (t, o["x"], o["y"])
            if t in PAD_TYPES and key not in self.passed:
                if trigger_rect.colliderect(
                        pad_trigger_rect(o["x"], o["y"], o.get("r", 0))):
                    if t == T_BLUE_PAD:
                        m["grav"] *= -1
                        m["vy"] = self.params.pad_force * 0.5 * m["grav"]
                    else:
                        m["vy"] = self.params.pad_force * m["grav"]
                    m["on_ground"] = False
                    self.passed.add(key)
                continue
            caabb = o.get("_caabb")
            if caabb is None:
                cr = cell_rect(o["x"], o["y"], obj_scale(o))
                caabb = (cr.left, cr.top, cr.right, cr.bottom)
                o["_caabb"] = caabb
            cl, ct, crr, cb = caabb
            if not (tr_left < crr and tr_right > cl
                    and tr_top < cb and tr_bottom > ct):
                continue
            if t == T_COIN:
                cid = o.get("coin_id", 0)
                if cid and cid not in self.coins_collected:
                    self.coins_collected.add(cid)
                continue
            # Cube-style orbs the mirror reacts to. Dash/teleport orbs are
            # skipped — those imply mode-specific behaviour the mirror lacks.
            # Gates on the MIRROR's buffer, so the main consuming its buffer
            # this frame doesn't lock the mirror out of its own orb.
            if t in (T_ORB, T_BLUE_ORB, T_GREEN_ORB, T_BLACK_ORB,
                     T_SPIDER_ORB, T_RED_ORB, T_PINK_ORB) \
                    and key not in self.passed:
                cell = (o["x"], o["y"])
                if activated_orb_cell is None:
                    # Mirror's orb gate: same fix as the main
                    # player — held OR buffered counts as "input
                    # active" so a sustained-hold sequence still
                    # fires the mirror's orbs. ``input_active`` is
                    # the boolean already computed for the mirror
                    # in _step_mirror.
                    if not input_active:
                        continue
                    activated_orb_cell = cell
                elif cell != activated_orb_cell:
                    continue
                if t == T_ORB:
                    m["vy"] = self.params.jump_force * m["grav"]
                elif t == T_RED_ORB:
                    m["vy"] = self.params.jump_force * 2.0 * m["grav"]
                elif t == T_PINK_ORB:
                    m["vy"] = self.params.jump_force * 0.5 * m["grav"]
                elif t == T_BLUE_ORB:
                    m["grav"] *= -1
                elif t == T_GREEN_ORB:
                    m["vy"] = self.params.jump_force * m["grav"]
                elif t == T_BLACK_ORB:
                    m["vy"] = -self.params.jump_force * m["grav"]
                elif t == T_SPIDER_ORB:
                    # Reuse the mirror spider teleport routine — same
                    # unlimited-range scan, same swept hazard check,
                    # same gravity flip on success. Forward the orb's
                    # explicit direction (editor toggle) so both
                    # bodies teleport together; fall back to the
                    # legacy rotation mapping for older levels.
                    _m_dir = None
                    _m_d = str(o.get("dir", "")).lower()
                    if _m_d == "up":
                        _m_dir = (0, -1)
                    elif _m_d == "down":
                        _m_dir = (0, 1)
                    elif _m_d == "left":
                        _m_dir = (-1, 0)
                    elif _m_d == "right":
                        _m_dir = (1, 0)
                    elif _m_d in ("", "auto"):
                        _r = int(o.get("r", 0)) % 360
                        if _r == 90:
                            _m_dir = (1, 0)
                        elif _r == 180:
                            _m_dir = (0, 1)
                        elif _r == 270:
                            _m_dir = (-1, 0)
                    self._mirror_spider_teleport(direction=_m_dir)
                    # Mirror's spider orb also consumes the click so
                    # the main body's mode physics doesn't re-fire on
                    # its surface from the same hold (matches
                    # activate_spider_orb on the main body).
                    self._hold_consumed = True
                m["on_ground"] = False
                self.passed.add(key)
                continue
            # Per-body portals: tracked in mirror_passed so the main body's
            # `passed` doesn't gate them. Each clone consumes the portal
            # once for itself.
            if t in (T_GRAV_UP, T_GRAV_DOWN) and key not in self.mirror_passed:
                target = -1 if t == T_GRAV_UP else 1
                if m["grav"] != target:
                    m["grav"] = target
                    m["on_ground"] = False
                self.mirror_passed.add(key)
            elif t in MODE_FROM_TYPE and key not in self.mirror_passed:
                self._set_mirror_mode(MODE_FROM_TYPE[t])
                # Camera mode is shared across bodies — same convention as
                # camera triggers — so the mirror's portal flips it too.
                self.free_cam_mode = bool(o.get("free_mode", False))
                self.mirror_passed.add(key)
            elif t == T_MODE_MINI and key not in self.mirror_passed:
                self._set_mirror_size(MINI_PLAYER_SIZE)
                self.mirror_passed.add(key)
            elif t == T_MODE_BIG and key not in self.mirror_passed:
                self._set_mirror_size(PLAYER_SIZE)
                self.mirror_passed.add(key)
            elif t == T_MODE_SOLO and key not in self.passed:
                # Collapse: the mirror "becomes" the main player. Adopt its
                # y/vy/grav/on_ground/angle so the player keeps the mirror's
                # arc instead of snapping back to the main body's pose.
                self.y = float(m["y"])
                self.vy = float(m["vy"])
                self.grav = int(m["grav"])
                self.on_ground = bool(m["on_ground"])
                self.angle = float(m.get("angle", 0.0))
                self.mirror = None
                self.passed.add(key)
                return True
            elif t == T_MODE_DUAL and key not in self.passed:
                # Already dual — consume the portal so it doesn't re-fire on
                # the main body either.
                self.passed.add(key)
            elif t == T_CAMERA_TRIGGER and key not in self.passed:
                target_row = o.get("cy", o["y"])
                self.target_cam_y = target_row * CELL + CELL / 2 - HEIGHT / 2
                self.passed.add(key)
            elif t == T_BG_TRIGGER and key not in self.passed:
                self.bg_preset = int(o.get("bg", 0))
                self.passed.add(key)
            elif t == T_MOVE_TRIGGER and key not in self.passed:
                self._start_move_trigger(o)
                self.passed.add(key)
            elif t == T_COLOR_TRIGGER and key not in self.passed:
                self.color_index = (self.color_index + 1) % len(PLAYER_COLORS)
                self.player_color = PLAYER_COLORS[self.color_index]
                self.passed.add(key)
            elif t == T_PULSE_TRIGGER and key not in self.passed:
                bpm = int(o.get("bpm", 128))
                duration_s = float(o.get("duration", 2.0))
                frames = max(1, int(duration_s * 60))
                self.active_pulses.append({
                    "start_frame": self.frame,
                    "end_frame": self.frame + frames,
                    "bpm": bpm,
                })
                self.passed.add(key)
            elif t == T_ROTATE_TRIGGER and key not in self.passed:
                self._start_rotate_trigger(o)
                self.passed.add(key)
            elif t == T_FOLLOW_TRIGGER and key not in self.passed:
                # always_on follows are activated by player.reset()
                # at level-start, so by the time the live player
                # crosses one of those it already has its link and
                # this branch is a no-op (the dedup inside
                # _start_follow_trigger handles it). Manual follows
                # arm the link the moment the player passes through.
                if not o.get("always_on"):
                    self._start_follow_trigger(o)
                self.passed.add(key)
            elif t == T_TIME_WARP and key not in self.passed:
                # Mirror also picks up time warps so a dual-segment that
                # uses the trigger gets a consistent time scale on both
                # bodies (the warp is global anyway — but ``self.passed``
                # is shared so a single trigger fires once across both).
                try:
                    self.time_warp = float(o.get("factor", 1.0))
                except (TypeError, ValueError):
                    self.time_warp = 1.0
                self.passed.add(key)
        if activated_orb_cell is not None:
            # Mirror consumed its own orb — clear ONLY the mirror's buffer.
            # The main's buffer is untouched so its orb (if any) still fires
            # this frame, matching the user expectation that one click acts
            # on both bodies.
            self.mirror_input_buffer = 0
        return False

    # ---- per-frame update ------------------------------------------------
    def update(self, input_held, input_pressed):
        if not self.alive or self.won:
            return
        self.frame += 1
        # Snapshot x before anything moves this frame. End-wall crossing is
        # evaluated against this so that teleport orbs that sweep backward
        # through the finish column don't trigger a premature win.
        self._x_at_frame_start = self.x
        # Stash on_ground BEFORE any mode-physics can clear or change it.
        # Portal triggers (e.g. _enter_dual) fire mid-substep and read this
        # to know whether the player was stably grounded at the start of
        # the frame — before any jump / thrust lifted them off.
        self._was_on_ground = self.on_ground
        # Count consecutive grounded frames at frame-start. A ground-based
        # jump that fires while this equals 1 was timed on the landing
        # frame itself — the tightest possible ("frame-perfect") release.
        if self._was_on_ground:
            self.grounded_frames += 1
        else:
            self.grounded_frames = 0
        self._step_move_animations()
        self._step_rotate_triggers()
        # Follow links run AFTER move animations so each linked
        # target snaps to its source's NEW position this frame
        # (otherwise the target would lag the source by one tick).
        self._step_follow_triggers()
        # Drop pulse triggers that have expired.
        if self.active_pulses:
            self.active_pulses = [p for p in self.active_pulses
                                  if p["end_frame"] > self.frame]
        if self.teleport_cooldown > 0:
            self.teleport_cooldown -= 1
        if self._grav_flip_grace > 0:
            self._grav_flip_grace -= 1
        if self.frame % 3 == 0:
            self.trail.append([self.x, self.y, self.angle, 100])
            # Mirror runs in lockstep with the main body's x — sample
            # at the same cadence so the dual-mode trail reads as a
            # single coordinated band rather than two desynced streams.
            if self.mirror is not None and self.mirror.get("alive", True):
                m = self.mirror
                self.mirror_trail.append(
                    [self.x, m["y"], m.get("angle", 0.0), 100])
        # In-place alpha decrement. We used to pop only from the front,
        # assuming chronological FIFO decay — but _spider_teleport
        # appends beam samples with al=220 mixed in among al=100 normal
        # samples, breaking the invariant. Normal samples queued AFTER
        # a high-alpha spider sample would decay below zero while the
        # spider sample at the front still registered al>5, leaving
        # negative-alpha entries in the middle of the list that crash
        # the trail renderer on the next frame. Filter expired entries
        # globally so order no longer has to match alpha ordering.
        for seg in self.trail:
            seg[3] -= 5
        if self.trail:
            self.trail = [seg for seg in self.trail if seg[3] > 5]
        # Mirror trail decays on the same schedule as the main trail —
        # keeps both bands fading in lockstep so a long ship hover in
        # dual reads as one band, not one ghost twice as long as the
        # other. Filtered to drop expired samples for the same reason
        # the main trail is (mixed-alpha samples from teleport beams).
        for seg in self.mirror_trail:
            seg[3] -= 5
        if self.mirror_trail:
            self.mirror_trail = [seg for seg in self.mirror_trail
                                 if seg[3] > 5]
        if input_pressed:
            self.input_buffer = 6
            self.mirror_input_buffer = 6
        else:
            if self.input_buffer > 0:
                self.input_buffer -= 1
            if self.mirror_input_buffer > 0:
                self.mirror_input_buffer -= 1
        # Clear the spider-orb-set hold gate as soon as the user lets
        # go. A fresh press (or holding through a release) re-enables
        # cube auto-jump on landing.
        if not input_held:
            self._hold_consumed = False
        # Directional dash orb: while the timer is live AND the player
        # still holds the button, the orb's configured velocity vector
        # replaces mode physics entirely — no gravity, no jump, no thrust.
        # Release or timer expiry hands control back to the mode block
        # on the same frame.
        dashing = self.dash_timer > 0 and input_held
        # A spider orb consumes the click whole — no continuous-thrust
        # mode (ship / wave) keeps applying physics on the new surface
        # from the same hold, and no edge-trigger mode (cube / ball /
        # ufo / spider) re-fires until the user releases and re-presses.
        # The gate clears in the not-input_held branch above as soon as
        # the user lets go.
        mode_held = input_held and not self._hold_consumed
        mode_pressed = input_pressed and not self._hold_consumed
        if not dashing:
            if self.dash_timer > 0 and not input_held:
                self.dash_timer = 0
            # Mode physics
            if self.mode == MODE_SHIP:
                self.vy += self.params.ship_gravity * self.grav
                if mode_held:
                    self.vy -= self.params.ship_thrust * self.grav
                self.vy = clamp(self.vy, -13.0, 13.0)
            elif self.mode == MODE_WAVE:
                direction = -1 if mode_held else 1
                target_vy = self.move_speed * direction * self.grav
                # Low-pass vy so rapid input toggles (bot spam, human
                # mashing) average toward straight-line travel rather
                # than jittering ±move_speed every frame. A sustained
                # hold still ramps to ~92% of full speed in 5 frames.
                self.vy = self.vy * 0.6 + target_vy * 0.4
            elif self.mode == MODE_UFO:
                # Cube-style auto-jump on the ground (hold-to-jump),
                # plus the UFO's signature mid-air click flap. The flap
                # is gated by ``not self.on_ground`` so a single press
                # while standing fires the cube-strength jump, not the
                # weaker flap force.
                self.vy += self.params.gravity * self.grav
                self.vy = clamp(self.vy, -18.0, 18.0)
                if mode_held and self.on_ground:
                    self._record_jump_timing("ufo", input_pressed)
                    self.jump()
                elif mode_pressed and not self.on_ground:
                    self.vy = self.params.ufo_jump_force * self.grav
                    self.input_buffer = 0
            elif self.mode == MODE_SPIDER:
                self.vy += self.params.gravity * self.grav
                self.vy = clamp(self.vy, -18.0, 18.0)
                if mode_pressed and self.on_ground:
                    self._record_jump_timing("spider", input_pressed)
                    self._spider_teleport()
                    self.input_buffer = 0
            elif self.mode == MODE_SWING:
                # Swing copter: gravity drives a continuous fall in the
                # current grav direction; a press flips gravity so the
                # player swings the other way. vy is preserved across
                # the flip so the player keeps momentum — gravity then
                # decelerates the existing vy, brings it to zero, and
                # reverses it, giving the swing its pendulum feel.
                self.vy += self.params.gravity * self.grav
                self.vy = clamp(self.vy, -18.0, 18.0)
                if mode_pressed:
                    self._record_jump_timing("swing", input_pressed)
                    self.grav *= -1
                    self.on_ground = False
                    self.input_buffer = 0
            elif self.mode == MODE_ROBOT:
                # Robot: cube-style gravity, but the jump button is a
                # held thruster (no instant impulse). Thrust is one-shot
                # per takeoff — once the player releases mid-air the
                # boosters lock until the next landing, so a "tap" gives
                # a tiny hop and a "hold" gives a tall climb but there's
                # no second pump in mid-air. Budget refills on landing.
                if not input_held and not self.on_ground:
                    self._robot_thrust_disabled = True
                self.vy += self.params.gravity * self.grav
                if (mode_held and self.flight_budget > 0
                        and not self._robot_thrust_disabled):
                    self.vy -= self.params.robot_thrust * self.grav
                    self.flight_budget -= 1
                    if self.on_ground:
                        # Note the take-off as a "jump" so timing
                        # logging / autobot replay records this frame.
                        self._record_jump_timing("robot", input_pressed)
                        self.on_ground = False
                # Cap climb speed against gravity at 30% of the global
                # ±18 limit (5.4 px/tick) so the robot reads as a gentle
                # diagonal boost rather than a wave-speed shoot. Fall
                # speed stays at the full 18 so gravity still feels
                # sharp on the way down.
                if self.grav == 1:
                    self.vy = clamp(self.vy, -5.4, 18.0)
                else:
                    self.vy = clamp(self.vy, -18.0, 5.4)
            else:
                self.vy += self.params.gravity * self.grav
                self.vy = clamp(self.vy, -18.0, 18.0)
                if (self.mode == MODE_CUBE and mode_held
                        and self.on_ground):
                    self._record_jump_timing("cube", input_pressed)
                    self.jump()
                elif self.mode == MODE_BALL and mode_pressed and self.on_ground:
                    self._record_jump_timing("ball", input_pressed)
                    self.grav *= -1
                    self.vy = self.params.ball_flip_force * self.grav
                    self.on_ground = False
            dx = self.move_speed
        else:
            self.vy = self.dash_vy
            dx = self.dash_vx
            self.dash_timer -= 1
        self.on_ground = False
        # Substep granularity is governed by COLLISION_SUBSTEP_PX —
        # tighter values catch fast tunnel-through collisions but cost
        # iteration count. Hitbox samples are emitted ONCE at the end
        # of the logical frame (see line ~2727) regardless of the
        # substep count, so the editor overlay reads as one rect per
        # tick instead of a smear of per-substep rects (which produced
        # the "weird solid mass" the user reported).
        steps = max(1, int(math.ceil(
            max(abs(dx), abs(self.vy)) / COLLISION_SUBSTEP_PX)))
        dx_step = dx / steps
        input_active = input_held or self.input_buffer > 0
        size = self.size
        # Two-hitbox design (OUTER for hazards, INNER for platform
        # deaths): the AABB pre-filter is a shrunk outer for grace +
        # perf, and the OBB narrow phase against rotated outer (in
        # `_handle_interactions`) is the authoritative hazard test.
        haz_shrink = max(2, int(6 * size / PLAYER_SIZE))
        for _ in range(steps):
            # Snapshot prev position as ints — used to build the trigger
            # union below without allocating a prev_rect Rect.
            prev_x_int = round(self.x)
            prev_y_int = round(self.y)
            self.x += dx_step
            # Slope x-pass: lift the player up the diagonal BEFORE the
            # rect-based x-collision. Without this, a / slope that
            # ends at a taller block would fail — x-collision sees the
            # cube's right edge poking into the next block (at the old
            # y) and registers a wall hit, even though the slope is
            # about to lift the cube above the block's top.
            self._resolve_slopes()
            if self._resolve_x_collision(dx_step):
                self._record_hitbox()
                return
            dy_step = self.vy / steps
            self.y += dy_step
            if self._resolve_y_collision(dy_step):
                self._record_hitbox()
                return
            # Slope y-pass: catch the case where the player fell onto
            # a slope (or rode over one with vy>0) — snap to surface.
            self._resolve_slopes()
            # Inner-vs-block death check: AFTER y-snap, if the inner
            # 50% rect is still poking inside any block (running into a
            # wall, head-clipping a ceiling), kill. Y-resolve only snaps
            # to top/bottom; x doesn't snap at all, so this is the
            # canonical "wall death" trigger.
            if self._inner_in_block_dies():
                self._record_hitbox()
                return
            cur_x_int = round(self.x)
            cur_y_int = round(self.y)
            # Trigger rect = union of prev/cur outer rects, inflated by
            # pygame's inflate(6, 6) — which adds 3 px on each side.
            tr_left = (prev_x_int if prev_x_int < cur_x_int else cur_x_int) - 3
            tr_top = (prev_y_int if prev_y_int < cur_y_int else cur_y_int) - 3
            tr_right = (prev_x_int if prev_x_int > cur_x_int else cur_x_int) + size + 3
            tr_bottom = (prev_y_int if prev_y_int > cur_y_int else cur_y_int) + size + 3
            trigger_rect = pygame.Rect(tr_left, tr_top,
                                       tr_right - tr_left,
                                       tr_bottom - tr_top)
            hazard_rect = pygame.Rect(
                cur_x_int + haz_shrink, cur_y_int + haz_shrink,
                size - haz_shrink * 2, size - haz_shrink * 2)
            if self._handle_interactions(trigger_rect, hazard_rect, input_active):
                # Inner-hitbox collision lifts the inner above the surface
                # after a y-resolve; if a win / interaction triggers
                # mid-substep we still want on_ground correct for the
                # caller (e.g. test assertions on a freshly-won attempt).
                self._check_ground_adjacency()
                self._record_hitbox()
                return
        # End-of-frame adjacency probe: run ONCE per frame instead of
        # per substep. Sets on_ground / snaps y so the next frame's
        # mode physics sees the right grounded state.
        self._check_ground_adjacency()
        # Robot mode: refill the held-thrust budget AND clear the mid-air
        # release lock the moment we land. Done after _check_ground_
        # adjacency so a robot that just touched down regains a full
        # tank — and the option to thrust again — before the next
        # frame's hold check.
        if self.mode == MODE_ROBOT and self.on_ground:
            self.flight_budget = int(self.params.robot_flight_seconds * 60)
            self._robot_thrust_disabled = False
        # Fell off the *visible* screen: kill cutoff is relative to the
        # camera's target Y so vertical-camera sections (ship segments
        # rising into the sky, UFO drops) don't false-kill when the player
        # is still in frame at a high/low world-Y.
        _cam_y = self.target_cam_y
        if self.y > _cam_y + HEIGHT + 300 or self.y < _cam_y - 500:
            self.alive = False
            self.death_reason = "Fell off the screen"
            return
        # Dual-mode: step the mirror body. If the mirror dies, the attempt
        # dies with it. This must run after the main physics so the mirror
        # sees the post-step x position.
        if self.mirror is not None:
            # Directional dash consumes the input signal for its whole
            # window — the held flag during a dash is a mechanical "keep
            # the dash alive" requirement, not a fresh user hold. If we
            # forward it to the mirror, the mirror's own mode re-reacts
            # every frame (cube auto-jumps on the ground, ship thrusts
            # upward, wave flies up) and the two bodies desync into what
            # looks like independent control. Suppress for the full dash
            # window so main and mirror stay locked to the same intent.
            if dashing:
                self._step_mirror(False, False)
            else:
                self._step_mirror(input_held, input_pressed)
            if self.mirror is not None and not self.mirror["alive"]:
                self.alive = False
                if not self.death_reason:
                    self.death_reason = "Mirror died"
                return
        # Rotation (visual)
        if self.mode == MODE_SHIP:
            self.angle = clamp(-self.vy * 4.2, -55, 55)
        elif self.mode == MODE_UFO:
            self.angle = clamp(-self.vy * 2.8, -30, 30)
        elif self.mode == MODE_WAVE:
            # Angle = where the wave is actually going. Wave vy is
            # ±move_speed every frame, so an unfiltered vy reading
            # snaps the target angle between ±wave_angle every time
            # the input toggles — that is the visible "wave jitter"
            # at the up→down flip. Low-pass the vy reading first so
            # rapid alternating taps average toward 0 (target stays
            # neutral) and only sustained direction shifts the nose.
            # Lerp factor was 0.78 / 0.22 (slow, sluggish nose): bumped
            # to 0.55 / 0.45 so a held direction reaches its target
            # angle in a few frames instead of a long drift, and the
            # wave responds tightly to taps.
            self._wave_vy_smooth = (
                self._wave_vy_smooth * 0.55 + self.vy * 0.45)
            v = self._wave_vy_smooth
            speed = max(1.0, self.move_speed)
            # Scale the target by how committed the smoothed vy is —
            # a fully-held direction reaches ±wave_angle, a flickering
            # signal stays close to 0 instead of yanking the nose.
            commit = clamp(v / speed, -1.0, 1.0)
            target_a = -commit * self.params.wave_angle
            self.angle = self.angle * 0.55 + target_a * 0.45
        elif self.mode == MODE_BALL:
            if self.on_ground:
                self.angle = round(self.angle / 90) * 90
            else:
                self.angle -= 10 * self.grav
        elif self.mode == MODE_SPIDER:
            if self.on_ground:
                self.angle = 0
            else:
                self.angle -= 6 * self.grav
        elif self.mode == MODE_SWING:
            # Tilt the swing's nose toward where it's actually moving —
            # vy>0 falls in the current grav, so pitch the symbol that
            # way, clamped so the icon stays readable.
            self.angle = clamp(-self.vy * 3.0, -45, 45)
        elif self.mode == MODE_ROBOT:
            # Robot: stand upright on the ground, tilt back slightly
            # while thrusting/falling. Smooth pitch from vy so the
            # silhouette reads as a controlled boost rather than the
            # cube's hard 90° snap.
            if self.on_ground:
                self.angle = self.angle * 0.6
            else:
                target_a = clamp(-self.vy * 2.5, -35, 35)
                self.angle = self.angle * 0.7 + target_a * 0.3
        else:
            if not self.on_ground:
                self.angle -= 5 * self.grav
            else:
                self.angle = round(self.angle / 90) * 90
        # Re-run follow links AFTER the player's physics updated
        # ``self.x``/``self.y`` this frame. Object→object links
        # are idempotent (target = source + offset, same result),
        # but player→object links need this second pass — without
        # it the source object lagged the player by one frame
        # (the early pass at frame-start saw last frame's x/y).
        self._step_follow_triggers()
        # 60 Hz hitbox sample — one append per logical frame after
        # rotation has settled, so the editor's overlay reads as a
        # tidy strobe rather than a dense per-substep smear.
        self._record_hitbox()
        self._record_mirror_hitbox()

    # ---- draw -----------------------------------------------------------
    def _player_color(self):
        return self.player_color

    def _draw_player_surface(self):
        col = self._player_color()
        ps = pygame.Surface((PLAYER_SIZE, PLAYER_SIZE), pygame.SRCALPHA)
        if self.mode == MODE_SHIP:
            # Ship = cube riding in a hull. The hull is a neutral
            # chassis so the pilot cube's colour reads through. Nose
            # points right (forward); the rotation applied in draw()
            # pitches the whole thing per ship_angle. An exhaust flame
            # hangs off the tail and switches to the dash palette while
            # a directional-dash orb is active.
            cx = PLAYER_SIZE // 2
            cy = PLAYER_SIZE // 2
            hull = (70, 76, 94)
            hull_hi = lighter(hull, 40)
            hull_lo = darker(hull, 30)
            nose = PLAYER_SIZE - 4
            tail = 7
            top = 9
            bot = PLAYER_SIZE - 9
            hull_pts = [
                (nose, cy),                 # nose tip
                (nose - 10, top),           # upper shoulder
                (tail + 2, top + 1),        # upper tail corner
                (tail - 1, cy),              # tail notch (flame seat)
                (tail + 2, bot - 1),         # lower tail corner
                (nose - 10, bot),           # lower shoulder
            ]
            pygame.draw.polygon(ps, darker(hull_lo, 30),
                                [(p[0], p[1] + 2) for p in hull_pts])
            pygame.draw.polygon(ps, hull, hull_pts)
            pygame.draw.polygon(ps, hull_hi, hull_pts, 2)
            # Cockpit canopy sits above/forward of the pilot cube so the
            # cube doesn't read as a floating block.
            canopy = pygame.Rect(cx - 2, cy - 10, 16, 8)
            pygame.draw.ellipse(ps, darker((120, 210, 255), 40), canopy)
            pygame.draw.ellipse(ps, (120, 210, 255), canopy.inflate(-2, -2))
            # Pilot cube (classic look with the player's chosen glyph)
            cube = max(12, PLAYER_SIZE // 2 - 2)
            cx0 = cx - cube // 2 - 1
            cy0 = cy - cube // 2 + 1
            pygame.draw.rect(ps, darker(col, 30),
                             (cx0, cy0 + 2, cube, cube), border_radius=3)
            pygame.draw.rect(ps, col,
                             (cx0, cy0, cube, cube), border_radius=3)
            pygame.draw.rect(ps, lighter(col, 60),
                             (cx0 + 1, cy0 + 1, cube - 2, cube - 2),
                             1, border_radius=2)
            draw_cube_icon_glyph(ps, cx0, cy0, cube, col, self.icon_index)
            # Flame — seated in the tail notch. Dashing ships burn hotter.
            flame_col = C_DASH_ORB if self.dash_timer > 0 else C_PAD
            flame_tip = tail - 5 if self.dash_timer > 0 else tail - 3
            pygame.draw.polygon(ps, flame_col,
                                [(flame_tip, cy),
                                 (tail + 3, cy - 5),
                                 (tail + 3, cy + 5)])
            pygame.draw.polygon(ps, lighter(flame_col, 60),
                                [(flame_tip + 2, cy),
                                 (tail + 3, cy - 3),
                                 (tail + 3, cy + 3)])
        elif self.mode == MODE_BALL:
            pygame.draw.circle(ps, darker(col, 30),
                               (PLAYER_SIZE // 2, PLAYER_SIZE // 2 + 2), PLAYER_SIZE // 2 - 2)
            pygame.draw.circle(ps, col,
                               (PLAYER_SIZE // 2, PLAYER_SIZE // 2), PLAYER_SIZE // 2 - 2)
            pygame.draw.circle(ps, lighter(col, 60),
                               (PLAYER_SIZE // 2, PLAYER_SIZE // 2), PLAYER_SIZE // 2 - 8, 2)
            pygame.draw.circle(ps, darker(col, 40),
                               (PLAYER_SIZE // 2, PLAYER_SIZE // 2), 6)
        elif self.mode == MODE_WAVE:
            # Single forward-pointing triangle (nose at the right edge).
            # The rotation applied in draw() comes from self.angle,
            # which is smoothed toward ±wave_angle based on a low-pass-
            # filtered vy so the nose tracks sustained direction rather
            # than every per-frame input toggle.
            cx = PLAYER_SIZE // 2
            pts = [
                (PLAYER_SIZE - 3, cx),    # nose (forward)
                (3, 4),                    # upper tail
                (3, PLAYER_SIZE - 4),     # lower tail
            ]
            pygame.draw.polygon(ps, darker(C_MODE_WAVE, 40),
                                [(p[0], p[1] + 2) for p in pts])
            pygame.draw.polygon(ps, col, pts)
            pygame.draw.polygon(ps, lighter(col, 60), pts, 2)
        elif self.mode == MODE_UFO:
            cx = PLAYER_SIZE // 2
            cy = PLAYER_SIZE // 2
            body_rect = pygame.Rect(3, cy - 2, PLAYER_SIZE - 6, 10)
            pygame.draw.ellipse(ps, darker(C_MODE_UFO, 40), body_rect.move(0, 2))
            pygame.draw.ellipse(ps, C_MODE_UFO, body_rect)
            pygame.draw.ellipse(ps, lighter(C_MODE_UFO, 60), body_rect.inflate(-6, -4), 2)
            dome = pygame.Rect(cx - 10, cy - 12, 20, 16)
            pygame.draw.ellipse(ps, darker(col, 30), dome.move(0, 2))
            pygame.draw.ellipse(ps, col, dome)
            pygame.draw.ellipse(ps, lighter(col, 70), dome.inflate(-6, -6), 2)
            for ox in (-12, 0, 12):
                pygame.draw.circle(ps, (255, 255, 255), (cx + ox, cy + 8), 2)
        elif self.mode == MODE_SPIDER:
            cx = PLAYER_SIZE // 2
            cy = PLAYER_SIZE // 2
            # Body
            pygame.draw.circle(ps, darker(C_MODE_SPIDER, 30), (cx, cy + 1), cx - 6)
            pygame.draw.circle(ps, C_MODE_SPIDER, (cx, cy), cx - 6)
            pygame.draw.circle(ps, col, (cx, cy), cx - 12)
            # Legs (four)
            for ox in (-2, 2):
                for oy in (-1, 1):
                    pygame.draw.line(ps, darker(C_MODE_SPIDER, 40),
                                     (cx, cy), (cx + ox * cx, cy + oy * cy), 3)
        elif self.mode == MODE_ROBOT:
            # Robot: cube body with stubby legs and a small thruster
            # vent at the bottom. Visually distinct from cube, but
            # close enough that the silhouette still reads as a player
            # square. The thruster glow brightens while the flight
            # budget is burning so the player can see fuel state.
            cx = PLAYER_SIZE // 2
            torso = pygame.Rect(3, 4, PLAYER_SIZE - 6, PLAYER_SIZE - 14)
            pygame.draw.rect(ps, darker(col, 30),
                             torso.move(0, 2), border_radius=3)
            pygame.draw.rect(ps, col, torso, border_radius=3)
            pygame.draw.rect(ps, lighter(col, 60),
                             torso.inflate(-6, -6), 2, border_radius=3)
            # Eye / visor band so the silhouette reads as a robot head.
            visor = pygame.Rect(8, 8, PLAYER_SIZE - 16, 6)
            pygame.draw.rect(ps, darker(C_MODE_ROBOT, 40), visor,
                             border_radius=2)
            pygame.draw.rect(ps, lighter(C_MODE_ROBOT, 30),
                             visor.inflate(-4, -2), border_radius=2)
            # Stubby legs (cosmetic) below the torso.
            leg_y = PLAYER_SIZE - 10
            for ox in (6, PLAYER_SIZE - 12):
                pygame.draw.rect(ps, darker(col, 40),
                                 (ox, leg_y, 6, 8), border_radius=1)
            # Thruster glow at the base — stronger when budget is burning.
            burning = self.flight_budget > 0 and self.vy < 0
            glow_col = C_DASH_ORB if burning else darker(C_MODE_ROBOT, 20)
            pygame.draw.polygon(ps, glow_col,
                                [(cx - 6, PLAYER_SIZE - 3),
                                 (cx + 6, PLAYER_SIZE - 3),
                                 (cx, PLAYER_SIZE - 1)])
        elif self.mode == MODE_SWING:
            # Vertical lozenge with a nose pointing forward (right) so
            # rotation reads as pitching into the current grav. The
            # body uses C_MODE_SWING so the player colour reads through
            # the inner diamond.
            cx = PLAYER_SIZE // 2
            cy = PLAYER_SIZE // 2
            outer = [
                (PLAYER_SIZE - 4, cy),
                (cx, 3),
                (3, cy),
                (cx, PLAYER_SIZE - 4),
            ]
            pygame.draw.polygon(ps, darker(C_MODE_SWING, 40),
                                [(p[0], p[1] + 2) for p in outer])
            pygame.draw.polygon(ps, C_MODE_SWING, outer)
            pygame.draw.polygon(ps, lighter(C_MODE_SWING, 60), outer, 2)
            inner = [
                (PLAYER_SIZE - 12, cy),
                (cx, 11),
                (11, cy),
                (cx, PLAYER_SIZE - 12),
            ]
            pygame.draw.polygon(ps, col, inner)
            pygame.draw.polygon(ps, darker(col, 40), inner, 1)
        else:
            pygame.draw.rect(ps, darker(col, 30),
                             (1, 3, PLAYER_SIZE - 2, PLAYER_SIZE - 2), border_radius=3)
            pygame.draw.rect(ps, col,
                             (0, 0, PLAYER_SIZE, PLAYER_SIZE), border_radius=3)
            pygame.draw.rect(ps, lighter(col, 60),
                             (3, 3, PLAYER_SIZE - 6, PLAYER_SIZE - 6), 2, border_radius=3)
            # Inset glyph: chosen by the player from the customize menu.
            # Defaults to the classic inset square if icon_index is invalid.
            draw_cube_icon_glyph(ps, 0, 0, PLAYER_SIZE, col, self.icon_index)
        return ps

    def draw(self, surf, cam_x, cam_y=0):
        col = self._player_color()
        # Trails are drawn at the size the player had at the time the trail
        # sample was stored. For simplicity we draw them at the current
        # self.size so shrinking/growing doesn't leave mismatched ghosts.
        size = self.size
        # Wave / ship / spider all use the continuous LINE trail style:
        # wave & ship because it matches GD's trail rendering, spider
        # because the teleport beam (pre→post) needs to show as an
        # instant line rather than as a discrete ghost between samples.
        # The line connects consecutive trail samples on one SRCALPHA
        # surface so each segment can fade independently.
        if (self.mode in (MODE_WAVE, MODE_SHIP, MODE_SPIDER, MODE_SWING)
                and len(self.trail) >= 2):
            trail_thickness = (5 if self.mode == MODE_SHIP
                               else 4 if self.mode == MODE_SPIDER
                               else 3)
            line_surf = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            half = size // 2
            for i in range(len(self.trail) - 1):
                x1, y1, _, al1 = self.trail[i]
                x2, y2, _, al2 = self.trail[i + 1]
                sx1 = x1 - cam_x + half
                sy1 = y1 - cam_y + half
                sx2 = x2 - cam_x + half
                sy2 = y2 - cam_y + half
                # Skip segments fully off-screen on both ends.
                if (sx1 < -60 and sx2 < -60) or (sx1 > WIDTH + 60 and sx2 > WIDTH + 60):
                    continue
                # Average the two endpoints' alphas so each segment fades
                # smoothly with its position in the trail.
                avg_al = max(0, min(255, int((al1 + al2) * 0.5 * 0.7)))
                pygame.draw.line(
                    line_surf, (*col, avg_al),
                    (int(sx1), int(sy1)), (int(sx2), int(sy2)),
                    trail_thickness,
                )
            surf.blit(line_surf, (0, 0))
        else:
            for tx, ty, ta, al in self.trail:
                sx = tx - cam_x
                sy_t = ty - cam_y
                if sx < -60 or sx > WIDTH + 60:
                    continue
                # Defensive clamp: pygame rejects alphas outside [0, 255]
                # with a fatal ValueError, and a stray high-alpha injection
                # (spider teleport uses 220) combined with a decayed sample
                # could otherwise crash the whole frame.
                _al_sm = max(0, min(255, int(al * 0.35)))
                _al_fill = max(0, min(255, int(al * 0.4)))
                ts = pygame.Surface((PLAYER_SIZE, PLAYER_SIZE), pygame.SRCALPHA)
                if self.mode == MODE_BALL:
                    pygame.draw.circle(ts, (*col, _al_sm),
                                       (PLAYER_SIZE // 2, PLAYER_SIZE // 2), PLAYER_SIZE // 2 - 2)
                elif self.mode == MODE_UFO:
                    cy = PLAYER_SIZE // 2
                    pygame.draw.ellipse(ts, (*col, _al_sm),
                                        (4, cy - 2, PLAYER_SIZE - 8, 10))
                elif self.mode == MODE_SPIDER:
                    pygame.draw.circle(ts, (*col, _al_sm),
                                       (PLAYER_SIZE // 2, PLAYER_SIZE // 2), PLAYER_SIZE // 2 - 4)
                else:
                    ts.fill((*col, _al_fill))
                if size != PLAYER_SIZE:
                    ts = pygame.transform.smoothscale(ts, (size, size))
                rot = pygame.transform.rotate(ts, ta)
                rr = rot.get_rect(center=(sx + size // 2, sy_t + size // 2))
                surf.blit(rot, rr)
        sx = self.x - cam_x
        sy = self.y - cam_y
        ps = self._draw_player_surface()
        if size != PLAYER_SIZE:
            ps = pygame.transform.smoothscale(ps, (size, size))
        rot = pygame.transform.rotate(ps, self.angle)
        rr = rot.get_rect(center=(sx + size // 2, sy + size // 2))
        surf.blit(rot, rr)
        # Mirror trail — same rendering split as the main body but
        # keyed off the mirror's own mode and drawn at the mirror's y.
        # Ghost silhouettes are flipped vertically so they match the
        # mirror's upside-down sprite; line-trail samples are direct
        # coordinate connections so no flip is needed.
        if self.mirror is not None and self.mirror_trail:
            mmode = self.mirror.get("mode", MODE_CUBE)
            msize = int(self.mirror.get("size", PLAYER_SIZE))
            if (mmode in (MODE_WAVE, MODE_SHIP, MODE_SPIDER, MODE_SWING)
                    and len(self.mirror_trail) >= 2):
                m_thickness = (5 if mmode == MODE_SHIP
                               else 4 if mmode == MODE_SPIDER
                               else 3)
                line_surf_m = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
                half_m = msize // 2
                for i in range(len(self.mirror_trail) - 1):
                    x1, y1, _, al1 = self.mirror_trail[i]
                    x2, y2, _, al2 = self.mirror_trail[i + 1]
                    sx1 = x1 - cam_x + half_m
                    sy1 = y1 - cam_y + half_m
                    sx2 = x2 - cam_x + half_m
                    sy2 = y2 - cam_y + half_m
                    if (sx1 < -60 and sx2 < -60) or (sx1 > WIDTH + 60 and sx2 > WIDTH + 60):
                        continue
                    avg_al = max(0, min(255, int((al1 + al2) * 0.5 * 0.7)))
                    pygame.draw.line(
                        line_surf_m, (*col, avg_al),
                        (int(sx1), int(sy1)), (int(sx2), int(sy2)),
                        m_thickness,
                    )
                surf.blit(line_surf_m, (0, 0))
            else:
                for tx, ty, ta, al in self.mirror_trail:
                    sx_t = tx - cam_x
                    sy_t = ty - cam_y
                    if sx_t < -60 or sx_t > WIDTH + 60:
                        continue
                    _al_sm = max(0, min(255, int(al * 0.35)))
                    _al_fill = max(0, min(255, int(al * 0.4)))
                    ts = pygame.Surface((PLAYER_SIZE, PLAYER_SIZE), pygame.SRCALPHA)
                    if mmode == MODE_BALL:
                        pygame.draw.circle(ts, (*col, _al_sm),
                                           (PLAYER_SIZE // 2, PLAYER_SIZE // 2),
                                           PLAYER_SIZE // 2 - 2)
                    elif mmode == MODE_UFO:
                        cy_g = PLAYER_SIZE // 2
                        pygame.draw.ellipse(ts, (*col, _al_sm),
                                            (4, cy_g - 2, PLAYER_SIZE - 8, 10))
                    elif mmode == MODE_SPIDER:
                        pygame.draw.circle(ts, (*col, _al_sm),
                                           (PLAYER_SIZE // 2, PLAYER_SIZE // 2),
                                           PLAYER_SIZE // 2 - 4)
                    else:
                        ts.fill((*col, _al_fill))
                    if msize != PLAYER_SIZE:
                        ts = pygame.transform.smoothscale(ts, (msize, msize))
                    ts = pygame.transform.flip(ts, False, True)
                    rot_t = pygame.transform.rotate(ts, ta)
                    rr_t = rot_t.get_rect(
                        center=(sx_t + msize // 2, sy_t + msize // 2))
                    surf.blit(rot_t, rr_t)
        # Dual-mode mirror — render in the mirror's own mode/size, flipped
        # vertically, at mirror["y"]. Alive-dimming if the mirror died.
        if self.mirror is not None:
            m = self.mirror
            msize = int(m.get("size", size))
            my = m["y"] - cam_y
            # _draw_player_surface() reads self.mode/self.size, so swap them
            # in for the mirror render and restore right after. Cleaner than
            # threading a mode arg through the cube/ball/wave/etc branches.
            saved_mode, saved_size = self.mode, self.size
            self.mode = m.get("mode", MODE_CUBE)
            self.size = msize
            try:
                msurf = self._draw_player_surface()
            finally:
                self.mode, self.size = saved_mode, saved_size
            if msize != PLAYER_SIZE:
                msurf = pygame.transform.smoothscale(msurf, (msize, msize))
            # Flip vertically so the mirror reads as upside-down (matches
            # its inverted gravity).
            msurf = pygame.transform.flip(msurf, False, True)
            if not m["alive"]:
                msurf.set_alpha(90)
            mrot = pygame.transform.rotate(msurf, m.get("angle", 0.0))
            mrr = mrot.get_rect(center=(sx + size // 2, my + msize // 2))
            surf.blit(mrot, mrr)
