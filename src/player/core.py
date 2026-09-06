"""Player physics / state.

The player owns the object list for the current play session (it mutates
positions for move triggers and tracks which orbs / portals have been
consumed).  One instance per attempt; call :meth:`Player.reset` between
tries.

Body-parameterised physics
--------------------------
Every physics routine takes a *body*: either the :class:`Player` itself
(the main body) or its :class:`MirrorBody` (dual mode).  Both share
``self.x``; each body owns ``y / vy / grav / on_ground / angle / mode /
size / alive / flight_budget / thrust_disabled / wave_vy_smooth / trail``.
The single implementation guarantees the mirror can never drift from the
main body's rules, which the old duplicated ``_step_mirror`` copy did.

Numerics are unchanged from the original single-body implementation.
"""

import math

import pygame

from ..constants import (
    CELL, HEIGHT, PLAYER_SIZE, MINI_PLAYER_SIZE, PLAYER_START_GX,
    MODE_CUBE, MODE_SHIP, MODE_BALL, MODE_WAVE, MODE_UFO, MODE_SPIDER,
    MODE_SWING, MODE_ROBOT, MODE_FROM_TYPE, SPEED_VALUES, PLAYER_COLORS,
    PLAYER_ICONS,
    T_BLOCK, T_SLOPE, T_SPIKE, T_HALF_SPIKE, T_SAW,
    T_ORB, T_DASH_ORB, T_DASH_ORB_GRAV, T_TELEPORT_ORB, T_BLACK_ORB,
    T_BLUE_ORB, T_GREEN_ORB, T_SPIDER_ORB, T_RED_ORB, T_PINK_ORB,
    T_PAD, T_PINK_PAD, T_RED_PAD, T_BLUE_PAD, T_SPIDER_PAD,
    T_GRAV_UP, T_GRAV_DOWN, T_END, T_START, T_COIN,
    T_MODE_MINI, T_MODE_BIG, T_MODE_DUAL, T_MODE_SOLO,
    T_CAMERA_TRIGGER, T_BG_TRIGGER, T_MOVE_TRIGGER, T_COLOR_TRIGGER,
    T_PULSE_TRIGGER, T_ROTATE_TRIGGER, T_FOLLOW_TRIGGER, T_TIME_WARP,
    PAD_TYPES, ORB_TYPES, DASH_ORB_TYPES,
    COLLISION_SUBSTEP_PX, SOLID_HITBOX_FRACTION,
    ORB_PINK_SCALE, ORB_RED_SCALE, PAD_PINK_SCALE, PAD_RED_SCALE,
    BLUE_ORB_PUSH_SCALE, BLUE_PAD_PUSH_SCALE,
)
from ..geometry import cell_rect, pad_trigger_rect, obj_scale, clamp
from ..levels import get_group_id
from ..physics import DEFAULT_PARAMS
from .. import settings
from .body import MirrorBody
from .collision import CollisionMixin, obb_corners, obb_aabb_overlap
from .triggers import TriggerMixin
from .draw import DrawMixin

# Orbs the mirror body reacts to (dash / teleport orbs are main-only).
_MIRROR_ORBS = frozenset({T_ORB, T_BLUE_ORB, T_GREEN_ORB, T_BLACK_ORB,
                          T_SPIDER_ORB, T_RED_ORB, T_PINK_ORB})
_LINE_TRAIL_MODES = frozenset({MODE_WAVE, MODE_SHIP, MODE_SPIDER, MODE_SWING})

_DIR_FROM_NAME = {"up": (0, -1), "down": (0, 1), "left": (-1, 0),
                  "right": (1, 0)}
_DIR_FROM_ROT = {90: (1, 0), 180: (0, 1), 270: (-1, 0)}


def orb_direction(obj):
    """Spider orb / pad facing: explicit ``dir`` field first, legacy ``r``
    rotation second, ``None`` (= against gravity) otherwise."""
    d = str(obj.get("dir", "")).lower()
    if d in _DIR_FROM_NAME:
        return _DIR_FROM_NAME[d]
    if d in ("", "auto"):
        try:
            return _DIR_FROM_ROT.get(int(obj.get("r", 0)) % 360)
        except (TypeError, ValueError):
            return None
    return None


class Player(CollisionMixin, TriggerMixin, DrawMixin):
    # __slots__: the physics inner loops touch x / y / vy / size / angle
    # hundreds of times per substep, so skipping the instance __dict__
    # is a measurable win.  Subclasses (``_SimPlayer`` in autobot.py)
    # declare their own __slots__ for extra fields.
    __slots__ = (
        "objects", "params",
        "_teleport_index", "_by_oid", "_by_group", "_end_walls_x",
        "practice_mode", "checkpoints", "attempt_count", "_has_slopes",
        "hitbox_trace", "mirror_hitbox_trace",
        "_nearby_cache_key", "_nearby_cache_result",
        "_nearby_trigger_cache_key", "_nearby_trigger_cache_result",
        "_spatial_index", "_trigger_index", "_ever_moved",
        # main body
        "x", "y", "vy", "grav", "on_ground", "alive", "won", "size",
        "angle", "mode", "flight_budget", "thrust_disabled",
        "wave_vy_smooth", "trail",
        # shared
        "grounded_frames", "last_jump", "death_reason",
        "target_cam_y", "free_cam_mode",
        "color_index", "player_color", "icon_index", "bg_preset",
        "move_speed", "dash_timer", "dash_vx", "dash_vy",
        "_dash_flip_on_end",
        "input_buffer", "mirror_input_buffer", "teleport_cooldown",
        "_mirror", "mirror_passed", "passed", "coins_collected", "frame",
        "_checkpoint_request", "_x_at_frame_start",
        "_hold_consumed", "_was_on_ground",
        "move_animations", "active_rotations", "active_pulses",
        "active_follows", "time_warp", "_bot_visibility",
        # render interpolation
        "prev_x", "prev_y", "prev_angle",
        "_trail_cache",
    )

    def __init__(self, objects, params=None):
        self.objects = objects
        self.params = params if params is not None else DEFAULT_PARAMS
        for o in self.objects:
            o.setdefault("_orig_x", o["x"])
            o.setdefault("_orig_y", o["y"])
        self._teleport_index = {}
        self._rebuild_teleport_index()
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
        self._end_walls_x = sorted({
            o["x"] * CELL for o in self.objects if o["t"] == T_END})
        self.practice_mode = False
        self.checkpoints = []
        self.attempt_count = 0
        self._has_slopes = any(o["t"] == T_SLOPE for o in self.objects)
        # Optional per-frame hitbox recorders (editor "Hitbox" view).
        # Left untouched by reset() so the caller's list survives.
        self.hitbox_trace = None
        self.mirror_hitbox_trace = None
        self._nearby_cache_key = None
        self._nearby_cache_result = []
        self._nearby_trigger_cache_key = None
        self._nearby_trigger_cache_result = []
        self._trail_cache = {}
        self._mirror = None
        self.reset()

    def _rebuild_teleport_index(self):
        groups = {}
        for o in self.objects:
            if o["t"] == T_TELEPORT_ORB:
                gid = get_group_id(o)
                if gid:
                    groups.setdefault(gid, []).append(o)
        self._teleport_index = groups

    # ---- mirror property (dict-compatible for bots / tests) ------------
    @property
    def mirror(self):
        return self._mirror

    @mirror.setter
    def mirror(self, value):
        if value is None or isinstance(value, MirrorBody):
            self._mirror = value
        else:
            self._mirror = MirrorBody.from_dict(value)

    @property
    def mirror_trail(self):
        """Mirror trail samples (empty list when there is no mirror)."""
        return self._mirror.trail if self._mirror is not None else []

    @mirror_trail.setter
    def mirror_trail(self, value):
        if self._mirror is not None:
            self._mirror.trail = value

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
        self.active_rotations = []
        self.active_pulses = []
        # id(obj) -> obj for everything a trigger ever moved this
        # session (the autobot's restore needs the candidate set).
        self._ever_moved = {}
        self._rebuild_spatial_index()
        self.x, self.y = self._spawn_point()
        self.vy = 0.0
        self.on_ground = False
        self.grounded_frames = 0
        self.last_jump = None
        self.alive = True
        self.death_reason = ""
        self.won = False
        self.angle = 0.0
        self.grav = 1
        self.trail = []
        self.passed = set()
        self.frame = 0
        self.mode = MODE_CUBE
        self.move_speed = self.params.base_move_speed
        self.dash_timer = 0
        self.dash_vx = 0.0
        self.dash_vy = 0.0
        self._dash_flip_on_end = False
        self.input_buffer = 0
        # The mirror keeps its own buffer so one click serves both orbs.
        self.mirror_input_buffer = 0
        self.teleport_cooldown = 0
        self.target_cam_y = 0.0
        self.free_cam_mode = False
        self.bg_preset = 0
        self.color_index = settings.get_player_color_index() % len(PLAYER_COLORS)
        self.player_color = PLAYER_COLORS[self.color_index]
        self.icon_index = settings.get_player_icon_index() % len(PLAYER_ICONS)
        self._checkpoint_request = False
        self._x_at_frame_start = self.x
        self._was_on_ground = False
        self.wave_vy_smooth = 0.0
        # Hold-after-spider gate: a spider warp consumes the held button
        # until release so the cube doesn't auto-jump off the new surface.
        self._hold_consumed = False
        self.size = PLAYER_SIZE
        self.coins_collected = set()
        self._mirror = None
        # Portals the mirror consumed independently (mode / size / grav).
        self.mirror_passed = set()
        self.time_warp = 1.0
        self.flight_budget = int(self.params.robot_flight_seconds * 60)
        self.thrust_disabled = False
        self._bot_visibility = False
        self.prev_x = self.x
        self.prev_y = self.y
        self.prev_angle = 0.0
        self._arm_always_on_follows()
        self.attempt_count += 1

    # ---- spawn -----------------------------------------------------------
    def _start_object(self):
        starts = [o for o in self.objects if o["t"] == T_START]
        if starts:
            return min(starts, key=lambda o: (o["x"], o["y"]))
        return None

    def _spawn_point(self):
        start = self._start_object()
        if start:
            return (float(start["x"] * CELL + (CELL - PLAYER_SIZE) / 2),
                    float(start["y"] * CELL + (CELL - PLAYER_SIZE) / 2))
        return float(PLAYER_START_GX * CELL), float(self._default_ground_y())

    def _default_ground_y(self):
        col_blocks = [o for o in self.objects
                      if o["t"] == T_BLOCK and o["x"] == PLAYER_START_GX]
        if col_blocks:
            return min(o["y"] for o in col_blocks) * CELL - PLAYER_SIZE
        return 10 * CELL - PLAYER_SIZE

    # ---- rects -----------------------------------------------------------
    def rect(self):
        return pygame.Rect(round(self.x), round(self.y), self.size, self.size)

    hitbox = rect

    def solid_hitbox(self):
        """Inner death hitbox: 50 % of the player size, centred."""
        l, t, r, b = self._inner_bounds(self.x, self.y, self.size)
        return pygame.Rect(l, t, r - l, b - t)

    def _outer_obb_corners(self):
        return obb_corners(self.x, self.y, self.size, self.angle, 1.0)

    def _record_hitbox(self):
        if self.hitbox_trace is not None:
            self.hitbox_trace.append((self.x, self.y, self.size, self.angle))

    def _record_mirror_hitbox(self):
        m = self._mirror
        if self.mirror_hitbox_trace is None or m is None:
            return
        self.mirror_hitbox_trace.append(
            (self.x, m.y, int(m.size), float(m.angle)))

    def render_pose(self, alpha=None):
        """``(x, y, angle)`` for drawing, interpolated between the last
        two physics ticks when ``alpha`` (0..1) is given."""
        if alpha is None or alpha >= 1.0:
            return self.x, self.y, self.angle
        if alpha <= 0.0:
            return self.prev_x, self.prev_y, self.prev_angle
        return (self.prev_x + (self.x - self.prev_x) * alpha,
                self.prev_y + (self.y - self.prev_y) * alpha,
                self.prev_angle + (self.angle - self.prev_angle) * alpha)

    def _sync_prev_pose(self):
        """Collapse the interpolation window (after a teleport or reset
        so the renderer doesn't smear across the jump)."""
        self.prev_x = self.x
        self.prev_y = self.y
        self.prev_angle = self.angle
        m = self._mirror
        if m is not None:
            m.prev_y = m.y
            m.prev_angle = m.angle

    # ---- checkpoints -----------------------------------------------------
    def save_checkpoint(self):
        self.checkpoints.append({
            "x": self.x, "y": self.y, "vy": self.vy, "grav": self.grav,
            "mode": self.mode, "move_speed": self.move_speed,
            "angle": self.angle, "bg_preset": self.bg_preset,
            "target_cam_y": self.target_cam_y,
            "free_cam_mode": self.free_cam_mode,
            "color_index": self.color_index,
            "size": self.size,
            "coins": set(self.coins_collected),
            "passed": set(self.passed),
        })

    def load_checkpoint(self):
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
        self.size = int(cp.get("size", PLAYER_SIZE))
        self.coins_collected = set(cp.get("coins", set()))
        self.passed = set(cp.get("passed", set()))
        self.on_ground = False
        self.alive = True
        self.won = False
        self.trail = []
        self._mirror = None
        self.dash_timer = 0
        self._sync_prev_pose()
        return True

    # ---- jump / orb actions ---------------------------------------------
    def _record_jump_timing(self, kind, input_pressed):
        """Snapshot timing of a ground-triggered action for the debug HUD.
        ``grounded_frames == 1`` means it fired on the landing frame."""
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

    def _orb_jump(self, b, force_scale=1.0):
        """Jump-orb impulse for body ``b`` with the per-mode falloff
        (ship 0.85, UFO 0.9); wave / swing flip gravity instead because
        they overwrite vy every tick."""
        if b.mode in (MODE_WAVE, MODE_SWING):
            b.grav *= -1
        elif b.mode == MODE_SHIP:
            b.vy = self.params.jump_force * 0.85 * force_scale * b.grav
        elif b.mode == MODE_UFO:
            b.vy = self.params.jump_force * 0.9 * force_scale * b.grav
        else:
            b.vy = self.params.jump_force * force_scale * b.grav
        b.on_ground = False

    def activate_orb(self, force_scale=1.0):
        """Yellow orb (main body)."""
        self._orb_jump(self, force_scale)

    def activate_red_orb(self):
        self._orb_jump(self, ORB_RED_SCALE)

    def activate_pink_orb(self):
        self._orb_jump(self, ORB_PINK_SCALE)

    def activate_black_orb(self):
        """Black orb: slam in the gravity direction."""
        self.vy = -self.params.jump_force * self.grav
        self.on_ground = False
        self.input_buffer = 0

    def activate_blue_orb(self):
        """Blue orb (GD): flip gravity with a small push, no jump."""
        self._blue_flip(self, BLUE_ORB_PUSH_SCALE)
        self.input_buffer = 0

    def activate_green_orb(self):
        """Green orb (GD): flip gravity and jump."""
        self.grav *= -1
        self._orb_jump(self, 1.0)
        self.input_buffer = 0

    def _blue_flip(self, b, push_scale):
        b.grav *= -1
        if b.mode not in (MODE_WAVE, MODE_SWING):
            b.vy = self.params.jump_force * push_scale * b.grav
        b.on_ground = False

    def activate_dash_orb(self, orb):
        """Directional hold-dash from the orb's rotation. The gravity
        variant flips gravity when the dash ends."""
        speed = float(orb.get("dash_speed", self.params.dash_speed))
        duration = int(orb.get("dash_dur", self.params.dash_time))
        angle = math.radians(float(orb.get("r", 0)))
        self.dash_vx = speed * math.cos(angle)
        self.dash_vy = speed * math.sin(angle)
        self.dash_timer = max(1, duration)
        self._dash_flip_on_end = orb["t"] == T_DASH_ORB_GRAV
        self.input_buffer = 0

    def _end_dash(self):
        self.dash_timer = 0
        if self._dash_flip_on_end:
            self._dash_flip_on_end = False
            self.grav *= -1
            self.on_ground = False

    def activate_spider_orb(self, orb=None):
        self._spider_teleport(self, orb_direction(orb) if orb else None)
        self.input_buffer = 0
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
        self.x = dest["x"] * CELL + (CELL - self.size) / 2
        self.y = dest["y"] * CELL + (CELL - self.size) / 2
        self.vy *= 0.25
        self.teleport_cooldown = 10
        self.trail = []
        if self._mirror is not None:
            self._mirror.trail = []
        self._sync_prev_pose()

    def flip_gravity(self):
        self.grav *= -1
        self.on_ground = False

    def _spider_teleport(self, b, direction=None):
        """Teleport body ``b`` to the nearest block surface in
        ``direction`` (``None`` = against its gravity). Vertical
        teleports flip gravity so the body clings to the new surface."""
        if direction is None:
            direction = (0, -b.grav)
        found = self._find_spider_surface(b, direction)
        if found is None:
            return
        new_x, new_y = found
        prev_x = self.x
        prev_y = b.y
        if self._swept_hazard_death(b, prev_x, prev_y, new_x, new_y):
            return
        # Beam samples so the trail reads as a continuous warp line.
        beam_step = max(8, b.size // 2)
        dx_b = new_x - prev_x
        dy_b = new_y - prev_y
        beam_n = max(1, int(((dx_b * dx_b + dy_b * dy_b) ** 0.5) // beam_step))
        for i in range(beam_n + 1):
            t = i / beam_n
            b.trail.append([prev_x + dx_b * t, prev_y + dy_b * t, b.angle, 100])
        if b is self:
            self.x = new_x
        b.y = new_y
        if direction[1] != 0:
            b.grav *= -1
        b.vy = 0.0
        b.on_ground = False

    # ---- mode / size / dual ---------------------------------------------
    def _set_body_mode(self, b, mode):
        b.mode = mode
        if mode in (MODE_CUBE, MODE_BALL):
            b.angle = round(b.angle / 90) * 90
        elif mode in (MODE_WAVE, MODE_SWING):
            b.vy = 0.0
        elif mode == MODE_ROBOT:
            b.flight_budget = int(self.params.robot_flight_seconds * 60)
            b.thrust_disabled = False

    def set_mode(self, mode):
        self._set_body_mode(self, mode)

    def set_speed(self, speed_type):
        self.move_speed = SPEED_VALUES.get(speed_type, self.params.base_move_speed)

    def _set_body_size(self, b, new_size):
        """Resize keeping the gravity-facing edge anchored."""
        if new_size == b.size:
            return
        delta = b.size - new_size
        if b.grav == 1:
            b.y += delta
        if b is self:
            self.x += delta / 2.0
        b.size = int(new_size)

    def _set_size(self, new_size):
        self._set_body_size(self, new_size)

    def _enter_dual(self, obj=None):
        """Spawn the mirror with opposite gravity, inheriting the main
        body's motion (vy / angle sign-flipped)."""
        if self._mirror is not None:
            return
        spawn_row = obj.get("spawn_y") if obj else None
        if spawn_row is not None:
            mirror_y = float(spawn_row) * CELL
        else:
            mirror_y = HEIGHT - self.y - self.size
        self._mirror = MirrorBody(
            y=float(mirror_y), vy=-float(self.vy), grav=-self.grav,
            on_ground=bool(self._was_on_ground), angle=-float(self.angle),
            alive=True, mode=MODE_CUBE, size=int(self.size),
            flight_budget=int(self.params.robot_flight_seconds * 60),
            thrust_disabled=False)

    def _collapse_dual(self):
        """Solo portal: the mirror becomes the main body's pose."""
        m = self._mirror
        self.y = float(m.y)
        self.vy = float(m.vy)
        self.grav = int(m.grav)
        self.on_ground = bool(m.on_ground)
        self.angle = float(m.angle)
        self._mirror = None

    def _kill(self, b, reason):
        b.alive = False
        if b is self:
            self.death_reason = reason
        elif not self.death_reason:
            self.death_reason = reason + " (mirror)"

    # ---- mode physics (shared by both bodies) ---------------------------
    def _apply_mode_physics(self, b, mode_held, mode_pressed, raw_held,
                            input_pressed):
        p = self.params
        mode = b.mode
        main = b is self
        if mode == MODE_SHIP:
            b.vy += p.ship_gravity * b.grav
            if mode_held:
                b.vy -= p.ship_thrust * b.grav
            b.vy = clamp(b.vy, -13.0, 13.0)
        elif mode == MODE_WAVE:
            target_vy = self.move_speed * (-1 if mode_held else 1) * b.grav
            b.vy = b.vy * 0.6 + target_vy * 0.4
        elif mode == MODE_UFO:
            b.vy += p.gravity * b.grav
            b.vy = clamp(b.vy, -18.0, 18.0)
            if mode_held and b.on_ground:
                if main:
                    self._record_jump_timing("ufo", input_pressed)
                b.vy = p.jump_force * b.grav
                b.on_ground = False
            elif mode_pressed and not b.on_ground:
                b.vy = p.ufo_jump_force * b.grav
                if main:
                    self.input_buffer = 0
        elif mode == MODE_SPIDER:
            b.vy += p.gravity * b.grav
            b.vy = clamp(b.vy, -18.0, 18.0)
            if mode_pressed and b.on_ground:
                if main:
                    self._record_jump_timing("spider", input_pressed)
                self._spider_teleport(b)
                if main:
                    self.input_buffer = 0
        elif mode == MODE_SWING:
            b.vy += p.gravity * b.grav
            b.vy = clamp(b.vy, -18.0, 18.0)
            if mode_pressed:
                if main:
                    self._record_jump_timing("swing", input_pressed)
                b.grav *= -1
                b.on_ground = False
                if main:
                    self.input_buffer = 0
        elif mode == MODE_ROBOT:
            # Held thruster, one boost per takeoff, budget refills on landing.
            if not raw_held and not b.on_ground:
                b.thrust_disabled = True
            b.vy += p.gravity * b.grav
            if mode_held and b.flight_budget > 0 and not b.thrust_disabled:
                b.vy -= p.robot_thrust * b.grav
                b.flight_budget -= 1
                if b.on_ground:
                    if main:
                        self._record_jump_timing("robot", input_pressed)
                    b.on_ground = False
            if b.grav == 1:
                b.vy = clamp(b.vy, -5.4, 18.0)
            else:
                b.vy = clamp(b.vy, -18.0, 5.4)
        elif mode == MODE_BALL:
            b.vy += p.gravity * b.grav
            b.vy = clamp(b.vy, -18.0, 18.0)
            if mode_pressed and b.on_ground:
                if main:
                    self._record_jump_timing("ball", input_pressed)
                b.grav *= -1
                b.vy = p.ball_flip_force * b.grav
                b.on_ground = False
        else:  # cube
            b.vy += p.gravity * b.grav
            b.vy = clamp(b.vy, -18.0, 18.0)
            if mode_held and b.on_ground:
                if main:
                    self._record_jump_timing("cube", input_pressed)
                b.vy = p.jump_force * b.grav
                b.on_ground = False

    def _apply_rotation(self, b):
        mode = b.mode
        if mode == MODE_SHIP:
            b.angle = clamp(-b.vy * 4.2, -55, 55)
        elif mode == MODE_UFO:
            b.angle = clamp(-b.vy * 2.8, -30, 30)
        elif mode == MODE_WAVE:
            # Low-pass vy so rapid taps don't jitter the nose.
            b.wave_vy_smooth = b.wave_vy_smooth * 0.55 + b.vy * 0.45
            commit = clamp(b.wave_vy_smooth / max(1.0, self.move_speed),
                           -1.0, 1.0)
            b.angle = b.angle * 0.55 + (-commit * self.params.wave_angle) * 0.45
        elif mode == MODE_BALL:
            if b.on_ground:
                b.angle = round(b.angle / 90) * 90
            else:
                b.angle -= 10 * b.grav
        elif mode == MODE_SPIDER:
            b.angle = 0 if b.on_ground else b.angle - 6 * b.grav
        elif mode == MODE_SWING:
            b.angle = clamp(-b.vy * 3.0, -45, 45)
        elif mode == MODE_ROBOT:
            if b.on_ground:
                b.angle = b.angle * 0.6
            else:
                b.angle = b.angle * 0.7 + clamp(-b.vy * 2.5, -35, 35) * 0.3
        else:
            if not b.on_ground:
                b.angle -= 5 * b.grav
            else:
                b.angle = round(b.angle / 90) * 90

    def _apply_pad(self, b, o):
        t = o["t"]
        p = self.params
        if t == T_SPIDER_PAD:
            self._spider_teleport(b, orb_direction(o))
            return
        if t == T_BLUE_PAD:
            self._blue_flip(b, BLUE_PAD_PUSH_SCALE)
            return
        if b.mode == MODE_WAVE:
            return  # GD: pads don't affect the wave
        scale = (PAD_PINK_SCALE if t == T_PINK_PAD
                 else PAD_RED_SCALE if t == T_RED_PAD else 1.0)
        if b.mode == MODE_SHIP:
            b.vy = p.jump_force * 0.95 * scale * b.grav
        else:
            b.vy = p.pad_force * scale * b.grav
        b.on_ground = False

    def _apply_orb(self, b, o):
        """Fire orb ``o`` on body ``b``. Returns False when the orb was
        skipped (teleport on cooldown)."""
        t = o["t"]
        main = b is self
        if t == T_ORB:
            self._orb_jump(b, 1.0)
        elif t == T_RED_ORB:
            self._orb_jump(b, ORB_RED_SCALE)
        elif t == T_PINK_ORB:
            self._orb_jump(b, ORB_PINK_SCALE)
        elif t == T_BLACK_ORB:
            b.vy = -self.params.jump_force * b.grav
            b.on_ground = False
        elif t == T_BLUE_ORB:
            self._blue_flip(b, BLUE_ORB_PUSH_SCALE)
        elif t == T_GREEN_ORB:
            b.grav *= -1
            self._orb_jump(b, 1.0)
        elif t == T_SPIDER_ORB:
            self._spider_teleport(b, orb_direction(o))
            self._hold_consumed = True
        elif t in DASH_ORB_TYPES:
            if not main:
                return False
            self.activate_dash_orb(o)
        elif t == T_TELEPORT_ORB:
            if not main or self.teleport_cooldown != 0:
                return False
            self.activate_teleport(o)
        return True

    # ---- interactions (shared) ------------------------------------------
    def _handle_interactions(self, b, trigger_rect, hazard_rect, input_active):
        """Hazards, pads, orbs, portals and triggers around body ``b``.

        Returns True when the frame must stop (death, win, teleport,
        solo-collapse).  Per-body portals (mode / size / gravity) use
        ``passed`` for the main body and ``mirror_passed`` for the
        mirror; global one-shots (orbs, pads, coins, triggers) share
        ``passed``."""
        main = b is self
        body_passed = self.passed if main else self.mirror_passed
        p = self.params
        tr_left, tr_top = trigger_rect.left, trigger_rect.top
        tr_right, tr_bottom = trigger_rect.right, trigger_rect.bottom
        hz = (hazard_rect.left, hazard_rect.top,
              hazard_rect.right, hazard_rect.bottom)
        # Only an off-axis rotation needs the SAT narrow phase.
        ang_mod = b.angle % 90.0
        corners = None
        use_obb = 0.5 < ang_mod < 89.5
        if main:
            prev_right = self._x_at_frame_start + self.size
            for wall_x in self._end_walls_x:
                if (tr_right > wall_x and tr_left < wall_x + CELL
                        and prev_right <= wall_x):
                    self.won = True
                    return True
        activated_orb_cell = None
        for o in self._nearby_triggers_for_aabb(
                tr_left, tr_top, tr_right, tr_bottom, 2):
            t = o["t"]
            if t == T_END:
                continue
            if t in (T_SPIKE, T_HALF_SPIKE, T_SAW):
                if use_obb and corners is None:
                    corners = obb_corners(self.x, b.y, b.size, b.angle, 1.0)
                if self._hazard_hit(o, hz, corners if use_obb else None):
                    self._kill(b, "Hit a saw" if t == T_SAW else "Hit a spike")
                    return True
                continue
            key = (t, o["x"], o["y"])
            if t in PAD_TYPES:
                if key not in self.passed and trigger_rect.colliderect(
                        pad_trigger_rect(o["x"], o["y"], o.get("r", 0))):
                    self._apply_pad(b, o)
                    self.passed.add(key)
                    if not b.alive:
                        return True
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
            if t in ORB_TYPES:
                if key in self.passed or (not main and t not in _MIRROR_ORBS):
                    continue
                cell = (o["x"], o["y"])
                if activated_orb_cell is None:
                    # Held OR buffered input fires orbs (GD hold-through).
                    if not input_active:
                        continue
                    if t == T_TELEPORT_ORB and self.teleport_cooldown != 0:
                        continue
                    activated_orb_cell = cell
                elif cell != activated_orb_cell:
                    continue
                if self._apply_orb(b, o):
                    self.passed.add(key)
                    if t == T_TELEPORT_ORB:
                        self.input_buffer = 0
                        return True
                    if not b.alive:
                        return True
                continue
            if t in (T_GRAV_UP, T_GRAV_DOWN):
                if key not in body_passed:
                    target = -1 if t == T_GRAV_UP else 1
                    if b.grav != target:
                        b.grav = target
                        b.on_ground = False
                    body_passed.add(key)
            elif t in MODE_FROM_TYPE:
                if key not in body_passed:
                    self._set_body_mode(b, MODE_FROM_TYPE[t])
                    self.free_cam_mode = bool(o.get("free_mode", False))
                    body_passed.add(key)
            elif t == T_MODE_MINI:
                if key not in body_passed:
                    self._set_body_size(b, MINI_PLAYER_SIZE)
                    body_passed.add(key)
            elif t == T_MODE_BIG:
                if key not in body_passed:
                    self._set_body_size(b, PLAYER_SIZE)
                    body_passed.add(key)
            elif t == T_MODE_DUAL:
                if key not in self.passed:
                    if main:
                        self._enter_dual(o)
                    self.passed.add(key)
            elif t == T_MODE_SOLO:
                if key not in self.passed:
                    self.passed.add(key)
                    if main:
                        self._mirror = None
                    else:
                        self._collapse_dual()
                        return True
            elif t in SPEED_VALUES:
                if key not in self.passed:
                    self.set_speed(t)
                    self.passed.add(key)
            elif key in self.passed:
                continue
            elif t == T_CAMERA_TRIGGER:
                row = o.get("cy", o["y"])
                self.target_cam_y = row * CELL + CELL / 2 - HEIGHT / 2
                self.passed.add(key)
            elif t == T_BG_TRIGGER:
                self.bg_preset = int(o.get("bg", 0))
                self.passed.add(key)
            elif t == T_MOVE_TRIGGER:
                self._start_move_trigger(o)
                self.passed.add(key)
            elif t == T_COLOR_TRIGGER:
                self.color_index = (self.color_index + 1) % len(PLAYER_COLORS)
                self.player_color = PLAYER_COLORS[self.color_index]
                self.passed.add(key)
            elif t == T_PULSE_TRIGGER:
                self._start_pulse_trigger(o)
                self.passed.add(key)
            elif t == T_ROTATE_TRIGGER:
                self._start_rotate_trigger(o)
                self.passed.add(key)
            elif t == T_FOLLOW_TRIGGER:
                if not o.get("always_on"):
                    self._start_follow_trigger(o)
                self.passed.add(key)
            elif t == T_TIME_WARP:
                try:
                    self.time_warp = float(o.get("factor", 1.0))
                except (TypeError, ValueError):
                    self.time_warp = 1.0
                self.passed.add(key)
        if activated_orb_cell is not None:
            if main:
                self.input_buffer = 0
            else:
                self.mirror_input_buffer = 0
        return False

    # ---- mirror step -----------------------------------------------------
    def _step_mirror(self, input_held, input_pressed):
        """Step the dual-mode mirror. It shares ``self.x`` (already moved
        this frame) and steps only its own y."""
        m = self._mirror
        if not m.alive:
            return
        mode_held = input_held and not self._hold_consumed
        mode_pressed = input_pressed and not self._hold_consumed
        self._apply_mode_physics(m, mode_held, mode_pressed, input_held,
                                 input_pressed)
        if self._mirror is None or not m.alive:
            return
        m.on_ground = False
        prev_y = m.y
        steps = max(1, int(math.ceil(abs(m.vy) / COLLISION_SUBSTEP_PX)))
        dy_step = m.vy / steps
        for _ in range(steps):
            m.y += dy_step
            self._resolve_y_collision(m, dy_step)
        self._resolve_slopes(m)
        if m.y > HEIGHT + 300 or m.y < -500:
            self._kill(m, "Fell off the screen")
            return
        self._check_ground_adjacency(m)
        if m.mode == MODE_ROBOT and m.on_ground:
            m.flight_budget = int(self.params.robot_flight_seconds * 60)
            m.thrust_disabled = False
        # Sweep the whole vertical travel so fast falls can't tunnel a spike.
        size = m.size
        shrink = max(2, int(6 * size / PLAYER_SIZE))
        x_int = round(self.x)
        y0 = min(round(prev_y), round(m.y))
        y1 = max(round(prev_y), round(m.y))
        hazard_rect = pygame.Rect(x_int + shrink, y0 + shrink,
                                  size - shrink * 2, y1 - y0 + size - shrink * 2)
        trigger_rect = pygame.Rect(x_int - 3, y0 - 3, size + 6, y1 - y0 + size + 6)
        input_active = input_held or self.mirror_input_buffer > 0
        if self._handle_interactions(m, trigger_rect, hazard_rect, input_active):
            return
        self._apply_rotation(m)

    # ---- per-frame update ------------------------------------------------
    def update(self, input_held, input_pressed):
        if not self.alive or self.won:
            return
        self.frame += 1
        self.prev_x = self.x
        self.prev_y = self.y
        self.prev_angle = self.angle
        m = self._mirror
        if m is not None:
            m.prev_y = m.y
            m.prev_angle = m.angle
        # Frame-start snapshots: end-wall gate + dual-portal grounding.
        self._x_at_frame_start = self.x
        self._was_on_ground = self.on_ground
        if self._was_on_ground:
            self.grounded_frames += 1
        else:
            self.grounded_frames = 0
        self._step_move_animations()
        self._step_rotate_triggers()
        self._step_follow_triggers()
        if self.active_pulses:
            self.active_pulses = [p for p in self.active_pulses
                                  if p["end_frame"] > self.frame]
        if self.teleport_cooldown > 0:
            self.teleport_cooldown -= 1
        self._sample_trails()
        if input_pressed:
            self.input_buffer = 6
            self.mirror_input_buffer = 6
        else:
            if self.input_buffer > 0:
                self.input_buffer -= 1
            if self.mirror_input_buffer > 0:
                self.mirror_input_buffer -= 1
        if not input_held:
            self._hold_consumed = False
        dashing = self.dash_timer > 0 and input_held
        mode_held = input_held and not self._hold_consumed
        mode_pressed = input_pressed and not self._hold_consumed
        if not dashing:
            if self.dash_timer > 0 and not input_held:
                self._end_dash()
            self._apply_mode_physics(self, mode_held, mode_pressed,
                                     input_held, input_pressed)
            if not self.alive:
                self._record_hitbox()
                return
            dx = self.move_speed
        else:
            self.vy = self.dash_vy
            dx = self.dash_vx
            self.dash_timer -= 1
            if self.dash_timer == 0:
                self._end_dash()
        self.on_ground = False
        steps = max(1, int(math.ceil(
            max(abs(dx), abs(self.vy)) / COLLISION_SUBSTEP_PX)))
        dx_step = dx / steps
        input_active = input_held or self.input_buffer > 0
        size = self.size
        haz_shrink = max(2, int(6 * size / PLAYER_SIZE))
        for _ in range(steps):
            prev_x_int = round(self.x)
            prev_y_int = round(self.y)
            self.x += dx_step
            # Slope x-pass lifts the cube up a ramp before the wall test.
            self._resolve_slopes(self)
            if self._resolve_x_collision(self, dx_step):
                self._record_hitbox()
                return
            dy_step = self.vy / steps
            self.y += dy_step
            self._resolve_y_collision(self, dy_step)
            self._resolve_slopes(self)
            if self._inner_in_block_dies(self):
                self._record_hitbox()
                return
            cur_x_int = round(self.x)
            cur_y_int = round(self.y)
            tr_left = min(prev_x_int, cur_x_int) - 3
            tr_top = min(prev_y_int, cur_y_int) - 3
            tr_right = max(prev_x_int, cur_x_int) + size + 3
            tr_bottom = max(prev_y_int, cur_y_int) + size + 3
            trigger_rect = pygame.Rect(tr_left, tr_top, tr_right - tr_left,
                                       tr_bottom - tr_top)
            hazard_rect = pygame.Rect(cur_x_int + haz_shrink,
                                      cur_y_int + haz_shrink,
                                      size - haz_shrink * 2,
                                      size - haz_shrink * 2)
            if self._handle_interactions(self, trigger_rect, hazard_rect,
                                         input_active):
                self._check_ground_adjacency(self)
                self._record_hitbox()
                return
            size = self.size  # portals may have resized us mid-frame
        self._check_ground_adjacency(self)
        if self.mode == MODE_ROBOT and self.on_ground:
            self.flight_budget = int(self.params.robot_flight_seconds * 60)
            self.thrust_disabled = False
        cam_y = self.target_cam_y
        if self.y > cam_y + HEIGHT + 300 or self.y < cam_y - 500:
            self._kill(self, "Fell off the screen")
            return
        if self._mirror is not None:
            # A dash consumes input for its whole window; don't let the
            # mirror re-react to the mechanical hold.
            if dashing:
                self._step_mirror(False, False)
            else:
                self._step_mirror(input_held, input_pressed)
            if self._mirror is not None and not self._mirror.alive:
                self.alive = False
                if not self.death_reason:
                    self.death_reason = "Mirror died"
                return
        self._apply_rotation(self)
        # Player-following links need the post-physics pose.
        self._step_follow_triggers()
        self._record_hitbox()
        self._record_mirror_hitbox()

    def _sample_trails(self):
        if self.frame % 3 == 0:
            self.trail.append([self.x, self.y, self.angle, 100])
            m = self._mirror
            if m is not None and m.alive:
                m.trail.append([self.x, m.y, m.angle, 100])
        for seg in self.trail:
            seg[3] -= 5
        if self.trail:
            self.trail = [seg for seg in self.trail if seg[3] > 5]
        m = self._mirror
        if m is not None and m.trail:
            for seg in m.trail:
                seg[3] -= 5
            m.trail = [seg for seg in m.trail if seg[3] > 5]
