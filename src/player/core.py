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
    UNITS_PER_BLOCK, CAMERA_HEIGHT_UNITS, PLAYFIELD_HEIGHT_UNITS,
    FALL_OFF_BELOW_CAM_UNITS, FALL_OFF_ABOVE_CAM_UNITS, CAMERA_BASE_Y_UNITS,
    TOUCH_PAD_UNITS, TELEPORT_BEAM_STEP_UNITS, PLAYER_SIZE_UNITS,
    PLAYER_START_GX, body_size_units, is_mini_size,
    TRAIL_MAX_DISTANCE_UNITS, PHYSICS_TPS, INPUT_BUFFER_TICKS,
    WAVE_ANGLE_SMOOTHING,
    TELEPORT_COOLDOWN_TICKS,
    MODE_CUBE, MODE_SHIP, MODE_BALL, MODE_WAVE, MODE_UFO, MODE_SPIDER,
    MODE_SWING, MODE_ROBOT, MODE_FROM_TYPE, SPEED_VALUES_UT as SPEED_VALUES,
    PLAYER_COLORS,
    PLAYER_ICONS,
    T_BLOCK, T_SLOPE, T_SPIKE, T_HALF_SPIKE, T_SAW,
    T_ORB, T_DASH_ORB_GRAV, T_TELEPORT_ORB, T_TELEPORT_PORTAL, T_BLACK_ORB,
    T_BLUE_ORB, T_GREEN_ORB, T_SPIDER_ORB, T_RED_ORB, T_PINK_ORB,
    T_PINK_PAD, T_RED_PAD, T_BLUE_PAD, T_SPIDER_PAD,
    T_GRAV_UP, T_GRAV_DOWN, T_END, T_START, T_COIN,
    T_MODE_MINI, T_MODE_BIG, T_MODE_DUAL, T_MODE_SOLO,
    TRIGGER_TYPES, CONTROL_TRIGGER_TYPES,
    PAD_TYPES, ORB_TYPES, DASH_ORB_TYPES, T_DASH_STOP,
    T_JUMP_BLOCK, T_WAVE_BLOCK, T_BONK_BLOCK,
    T_FORCE_BLOCK, FORCE_BLOCK_DEFAULT_RANGE,
    T_ITEM_PICKUP, T_COUNT_TRIGGER, T_TIME_EVENT_TRIGGER, T_KEYFRAME,
    COLLISION_SUBSTEP_UNITS, DASH_TIMER_INFINITE,
    ORB_PINK_SCALE, ORB_RED_SCALE, PAD_PINK_SCALE, PAD_RED_SCALE,
    MAX_FALL_BOX_UT as MAX_FALL_BOX, MAX_FALL_UFO_UT as MAX_FALL_UFO,
    MAX_RISE_UFO_UT as MAX_RISE_UFO, MAX_FALL_SWING_UT as MAX_FALL_SWING,
    SWING_VY_MULTIPLIER, PX_PER_UNIT,
    BG_SPEED_DEFAULT_X, BG_SPEED_DEFAULT_Y, MG_SPEED_DEFAULT_X,
    MG_SPEED_DEFAULT_Y, EVENT_LEVEL_START, EVENT_DEATH, EVENT_WIN,
    EVENT_CHECKPOINT, EVENT_RESPAWN,
)
from ..geometry import (
    cell_rect_units as cell_rect, pad_trigger_rect_units as pad_trigger_rect,
    obj_scale, clamp,
)
from ..levels import get_group_id, get_groups
from ..objects import active_start
from ..physics import DEFAULT_PARAMS
from ..channels import channel_color
from .. import settings
from .body import MirrorBody
from .collision import CollisionMixin, obb_corners, invalidate_pose_caches
from .triggers import TriggerMixin
from .trigger_registry import TRIGGER_FAMILY_TOUCH
from .draw import DrawMixin

# Orbs the mirror body reacts to (dash / teleport orbs are main-only).
_MIRROR_ORBS = frozenset({T_ORB, T_BLUE_ORB, T_GREEN_ORB, T_BLACK_ORB,
                          T_SPIDER_ORB, T_RED_ORB, T_PINK_ORB})
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


# GD dash orbs never fire a purely vertical dash: the rotation is capped
# to this many degrees off whichever horizontal axis (right- or
# left-facing) it's closest to.
_DASH_ANGLE_MAX = 70.0


def _clamp_dash_angle_rad(r_deg):
    """Dash-orb rotation -> radians, with the vertical tilt capped to
    ``_DASH_ANGLE_MAX`` off horizontal. The left/right facing is kept
    intact — only how steep the dash is up/down gets clamped."""
    try:
        rad = math.radians(float(r_deg))
    except (TypeError, ValueError):
        rad = 0.0
    nx, ny = math.cos(rad), math.sin(rad)
    sign_x = 1.0 if nx >= 0 else -1.0
    dev = clamp(math.degrees(math.atan2(ny, abs(nx))),
                -_DASH_ANGLE_MAX, _DASH_ANGLE_MAX)
    dev_rad = math.radians(dev)
    return math.atan2(math.sin(dev_rad), sign_x * math.cos(dev_rad))


class Player(CollisionMixin, TriggerMixin, DrawMixin):
    # __slots__: the physics inner loops touch x / y / vy / size / angle
    # hundreds of times per substep, so skipping the instance __dict__
    # is a measurable win.  Subclasses (``SimPlayer`` in bots/sim.py)
    # declare their own __slots__ for extra fields.
    __slots__ = (
        "objects", "params", "channels",
        "_teleport_index", "_by_oid", "_by_group", "_by_animation",
        "_end_walls_x",
        "_count_watchers",
        "practice_mode", "noclip", "checkpoints", "attempt_count", "_has_slopes",
        "hitbox_trace", "mirror_hitbox_trace",
        "_nearby_cache_key", "_nearby_cache_result",
        "_nearby_trigger_cache_key", "_nearby_trigger_cache_result",
        "_spatial_index", "_trigger_index", "_ever_moved", "_oid_index",
        # main body
        "x", "y", "vy", "grav", "on_ground", "alive", "won", "size",
        "angle", "mode", "flight_budget", "thrust_disabled",
        "wave_vy_smooth", "trail",
        # shared
        "grounded_frames", "last_jump", "death_reason",
        "target_cam_y", "free_cam_mode", "camera_locked",
        "color_index", "player_color", "icon_index", "bg_preset",
        "move_speed", "dash_timer", "dash_vx", "dash_vy",
        # Checkpoint 6 (deep-research-report.md, "Gameplay, camera, UI, and
        # environment"): which way gameplay runs, +1 rightwards (always,
        # before this checkpoint) or -1 leftwards after a Reverse /
        # Gameplay Rotation trigger. A separate sign rather than a signed
        # ``move_speed`` because move_speed is a positive magnitude
        # everywhere else (speed portals, wave velocity, the HUD's "x"
        # readout, every bot heuristic); update() multiplies the two at
        # the single place the auto-scroll step is computed. Public-ish:
        # bots/sim.py snapshots and restores it like move_speed.
        "move_dir",
        "_dash_flip_on_end",
        "input_buffer", "mirror_input_buffer", "teleport_cooldown",
        "_mirror", "mirror_passed", "passed", "held_orbs",
        "coins_collected", "frame",
        "_checkpoint_request", "_x_at_frame_start",
        "_hold_consumed", "_was_on_ground", "_jump_block_armed",
        "move_animations", "active_rotations", "active_pulses",
        "active_follows", "time_warp", "_bot_visibility",
        # Checkpoint 5 (editor reference Sec 4, logic/group family):
        # Scale/Alpha animations, Spawn/Sequence's delayed-fire queue, and
        # the set of group ids a Toggle Trigger has disabled.
        "active_scales", "active_alphas", "pending_spawns", "pending_repeats",
        "pending_swaps",
        "_trigger_disabled",
        # Trigger activations queued during the current tick, drained (and
        # left empty again) at the end of every update() -- see
        # triggers.py's _enqueue_trigger_event/_drain_trigger_event_queue.
        # Never holds state across ticks, so bots/sim.py's snapshot/restore
        # has nothing to capture here.
        "_trigger_event_queue",
        # Checkpoint 3 (deep-research-report.md, "Force and state
        # precedence"): the ForceIDs already applied to the player during
        # the current tick, cleared at the top of every update(). This is
        # what makes the report's stacking law ("different ForceID ->
        # forces stack; same ForceID -> forces do not stack") literal --
        # see _apply_force_block. Like _trigger_event_queue above it never
        # holds state across ticks, so bots/sim.py's snapshot/restore has
        # nothing to capture here.
        "_force_ids_this_frame",
        "blackout_value", "blackout_target", "blackout_start",
        "blackout_start_frame", "blackout_frames",
        "cam_pan_duration",
        # Checkpoint 6 (editor reference Sec 4, camera family + screen
        # effects): zoom/offset/rotate are eased animations like
        # scale/alpha above; edge/guide are immediate mode switches;
        # static_cam_group lets a Static camera trigger track a moving
        # group instead of freezing in place; active_effect_anims holds
        # one entry per screen-effect type (grayscale/sepia/invert/hue/
        # pixelate), keyed by name, so re-triggering resumes from the
        # current blend instead of snapping.
        "zoom", "active_zooms", "cam_offset_x", "cam_offset_y",
        "active_cam_offsets", "cam_rotation", "active_cam_rotations",
        "cam_edge", "cam_guide_ease", "static_cam_group",
        "active_effect_anims",
        # Checkpoint 8 (simplified keyframe system): one running-animation
        # entry per Keyframe Animation Trigger fired, each carrying its own
        # segment list + progress -- see triggers.py's _start_keyframe_
        # trigger/_step_keyframe_animations.
        "active_keyframe_anims",
        # Checkpoint 2 (deep-research-report.md, "Area and keyframe
        # system"): live area effects keyed by their Effect id -- an Area
        # Move/Rotate/Scale/Fade/Tint registers one, an Edit Area patches
        # it in place, an Area Stop pops it. Like active_rotations/
        # active_scales (and unlike move_animations), this is continuous
        # per-tick state the bots' snapshot/restore deliberately does not
        # capture: what the search actually rewinds is the *result* --
        # object positions, via _set_object_pos/_displaced_oids.
        "active_areas",
        # Checkpoint 5 (deep-research-report.md, "Audio, timers, and
        # arithmetic"): live audio started by the Song/SFX trigger
        # family. ``active_songs`` is keyed by song channel (GD key 432)
        # and ``active_sfx`` by unique id (key 416) -- the ids Edit Song /
        # Edit SFX address, exactly as active_areas is keyed by effect
        # id -- and ``active_song_channel`` names which of those channels
        # is the one actually sounding, since this engine has a single
        # music stream. Like active_areas, this is state the bots'
        # snapshot/restore deliberately does not capture: nothing here
        # feeds physics or collision (SimPlayer does not even emit audio,
        # see TriggerMixin.audio_output_enabled), so a search rewinding
        # to an earlier tick has nothing to undo.
        "active_songs", "active_sfx", "active_song_channel",
        # Checkpoint 7 (editor reference Sec 4, "Item/counter/timer
        # system"): ``items`` resets every attempt in reset(); ``items_pers``
        # is seeded once in __init__ and only ever written by an Item Pers
        # Trigger, so it survives every reset() (retry/respawn) within this
        # Player instance's lifetime -- reset() reseeds ``items`` FROM
        # ``items_pers`` rather than clearing to empty, so a persisted
        # item id starts each attempt at its last snapshot. ``timers``/
        # ``timers_running`` are plain per-attempt state (no persistence).
        "items", "items_pers", "timers", "timers_running",
        # Checkpoint 7 (deep-research-report.md, "Gameplay, camera, UI,
        # and environment"): the environment/UI/event family's state.
        #
        # bg_/mg_speed_* are the parallax rates a Background/Middleground
        # Speed trigger sets (seeded from the report's documented
        # defaults, which are the renderer's identity point); ui_labels
        # holds one HUD text entry per ui_id posted by a UI Trigger;
        # _event_triggers is the level's Event Triggers indexed by
        # event_type, built once per attempt by _arm_event_triggers.
        #
        # Like active_areas / active_songs above, none of this is in
        # bots/sim.py's snapshot/restore, and for the same reason: it is
        # purely presentational (two parallax multipliers and a HUD
        # string) and feeds nothing in physics or collision, so a search
        # rewinding to an earlier tick has nothing to undo. _event_
        # triggers is rebuilt from self.objects on every reset(), so it
        # is derived data, not state.
        "bg_speed_x", "bg_speed_y", "mg_speed_x", "mg_speed_y",
        "ui_labels", "_event_triggers",
        # render interpolation
        "prev_x", "prev_y", "prev_angle",
        "_trail_cache",
    )

    def __init__(self, objects, params=None, channels=None):
        self.objects = objects
        self.params = params if params is not None else DEFAULT_PARAMS
        self.channels = channels or {}
        for o in self.objects:
            o.setdefault("_orig_x", o["x"])
            o.setdefault("_orig_y", o["y"])
            o.setdefault("_orig_r", o.get("r", 0))
        # id(obj) -> position in self.objects. A dict's own id() is only
        # meaningful within this instance, but the bots' snapshot/restore
        # (sim.py) has to name objects portably across *different*
        # SimPlayer instances built from independent `[dict(o) for o in
        # objects]` copies of the same source list — those copies share
        # list order, so the index is a stable, portable identifier where
        # id() is not. _ever_moved (below) is keyed by this index rather
        # than raw id() for exactly that reason.
        self._oid_index = {id(o): i for i, o in enumerate(self.objects)}
        self._teleport_index = {}
        self._rebuild_teleport_index()
        self._by_oid = {}
        self._by_group = {}
        # Checkpoint 8: keyframes are data, never touched by oid/group
        # indexing above -- a Keyframe Animation Trigger looks its
        # animation id up here directly, pre-sorted by Order once rather
        # than on every trigger fire.
        self._by_animation = {}
        for o in self.objects:
            oid = o.get("oid")
            if oid:
                self._by_oid[oid] = o
            for g in get_groups(o):
                self._by_group.setdefault(g, []).append(o)
            if o.get("t") == T_KEYFRAME:
                anim = o.get("animation_id", 0)
                self._by_animation.setdefault(anim, []).append(o)
        for anim, kfs in self._by_animation.items():
            kfs.sort(key=lambda k: k.get("order", 0))
        # End walls span the full screen height: collision is x-only.
        self._end_walls_x = sorted({
            o["x"] * UNITS_PER_BLOCK for o in self.objects if o["t"] == T_END})
        # Checkpoint 7: Count / Time Event triggers watch continuously
        # (edge-triggered on their own object dict, see triggers.py's
        # _step_count_watchers) rather than only on touch/spawn, so the
        # candidate list is precomputed once instead of filtered per tick.
        self._count_watchers = [o for o in self.objects
                                if o["t"] in (T_COUNT_TRIGGER,
                                              T_TIME_EVENT_TRIGGER)]
        # Checkpoint 7: Event Triggers indexed by event_type, so the
        # engine's event hook points (_kill, save_checkpoint, the win
        # flag) cost one dict lookup instead of a scan. Built here rather
        # than in reset() -- an object's event_type never changes during a
        # session, so this is derived data like _count_watchers above, and
        # a bot search that calls reset() thousands of times should not
        # pay for rebuilding it every time.
        self._arm_event_triggers()
        self.practice_mode = False
        self.noclip = False
        self.checkpoints = []
        self.attempt_count = 0
        # Survives every reset() (see the __slots__ comment above).
        self.items_pers = {}
        # Seeded before the first reset() so _stop_trigger_audio has
        # something to walk: reset() SILENCES whatever the previous
        # attempt left playing rather than just dropping the references.
        self.active_songs = {}
        self.active_sfx = {}
        self.active_song_channel = None
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
            if o["t"] in (T_TELEPORT_ORB, T_TELEPORT_PORTAL):
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
            if "_orig_r" in o:
                o["r"] = o["_orig_r"]
            o.pop("_fx", None)
            o.pop("_fy", None)
            o.pop("_cell", None)
            o.pop("_count_armed", None)
            invalidate_pose_caches(o)
        self.move_animations = []
        self.active_follows = []
        self.active_rotations = []
        self.active_pulses = []
        self.active_scales = []
        self.active_alphas = []
        self.active_keyframe_anims = []
        self.active_areas = {}
        # Stops (not merely forgets) any sound the previous attempt's
        # audio triggers left playing -- see _stop_trigger_audio.
        self._stop_trigger_audio()
        self.pending_spawns = []
        self.pending_repeats = []
        self.pending_swaps = []
        self._trigger_event_queue = []
        self._force_ids_this_frame = set()
        self._trigger_disabled = set()
        # Checkpoint 7: non-persistent items start at 0; a persisted item
        # id (Item Pers Trigger) re-seeds from its last snapshot instead.
        self.items = dict(self.items_pers)
        self.timers = {}
        self.timers_running = set()
        # portable index (see _oid_index) -> obj for everything a trigger
        # ever moved this session (the bots' restore needs the candidate
        # set, across whichever SimPlayer instance is being restored).
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
        # Multi-activate orbs fired during the current hold; cleared on
        # release so one press can never fire the same orb twice.
        self.held_orbs = set()
        self.frame = 0
        self.mode = MODE_CUBE
        self.move_speed = self.params.base_move_speed
        self.move_dir = 1
        self.dash_timer = 0
        self.dash_vx = 0.0
        self.dash_vy = 0.0
        self._dash_flip_on_end = False
        self.input_buffer = 0
        # The mirror keeps its own buffer so one click serves both orbs.
        self.mirror_input_buffer = 0
        self.teleport_cooldown = 0
        self.target_cam_y = CAMERA_BASE_Y_UNITS
        self.free_cam_mode = False
        self.camera_locked = False
        self.cam_pan_duration = 1.0
        self.zoom = 1.0
        self.active_zooms = []
        self.cam_offset_x = 0.0
        self.cam_offset_y = 0.0
        self.active_cam_offsets = []
        self.cam_rotation = 0.0
        self.active_cam_rotations = []
        self.cam_edge = None
        self.cam_guide_ease = None
        self.static_cam_group = None
        self.active_effect_anims = {}
        self.bg_preset = 0
        # Checkpoint 7: seeded from the report's own documented defaults,
        # which are also the renderer's identity point -- an attempt that
        # fires no BG/MG Speed trigger scrolls at the stock parallax rate.
        self.bg_speed_x = BG_SPEED_DEFAULT_X
        self.bg_speed_y = BG_SPEED_DEFAULT_Y
        self.mg_speed_x = MG_SPEED_DEFAULT_X
        self.mg_speed_y = MG_SPEED_DEFAULT_Y
        self.ui_labels = {}
        self.blackout_value = 0.0
        self.blackout_target = 0.0
        self.blackout_start = 0.0
        self.blackout_start_frame = 0
        self.blackout_frames = 1
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
        # J Block (bible Sec 4.1): armed by touching one, consumed at the
        # next landing auto-jump to suppress it.
        self._jump_block_armed = False
        self.size = body_size_units(self.mode, False)
        self.coins_collected = set()
        self._mirror = None
        # Portals the mirror consumed independently (mode / size / grav).
        self.mirror_passed = set()
        self.time_warp = 1.0
        self.flight_budget = int(self.params.robot_flight_seconds * PHYSICS_TPS)
        self.thrust_disabled = False
        self._bot_visibility = False
        self.prev_x = self.x
        self.prev_y = self.y
        self.prev_angle = 0.0
        self._arm_always_on_follows()
        # Checkpoint 7: the level-start event, fired for every attempt
        # (retries included) exactly where the always-on Follow links are
        # armed above. It comes AFTER the queue was cleared earlier in
        # reset(), so these activations survive to the first update()'s
        # drain instead of being wiped by the clear.
        self._fire_event(EVENT_LEVEL_START)
        self.attempt_count += 1

    # ---- spawn -----------------------------------------------------------
    def _start_object(self):
        """The active Start Pos, so bots and the real player always spawn
        at the same place (see :func:`objects.active_start`)."""
        return active_start(self.objects)

    def _spawn_point(self):
        start = self._start_object()
        if start:
            return (float(start["x"] * UNITS_PER_BLOCK + (UNITS_PER_BLOCK - PLAYER_SIZE_UNITS) / 2),
                    float(start["y"] * UNITS_PER_BLOCK + (UNITS_PER_BLOCK - PLAYER_SIZE_UNITS) / 2))
        return float(PLAYER_START_GX * UNITS_PER_BLOCK), float(self._default_ground_y())

    def _default_ground_y(self):
        col_blocks = [o for o in self.objects
                      if o["t"] == T_BLOCK and o["x"] == PLAYER_START_GX]
        if col_blocks:
            return min(o["y"] for o in col_blocks) * UNITS_PER_BLOCK - PLAYER_SIZE_UNITS
        return 10 * UNITS_PER_BLOCK - PLAYER_SIZE_UNITS

    # ---- render-space (px) compatibility -----------------------------
    # Physics/collision above this point works entirely in real GD units
    # (see docs/development/UNITS_REFACTOR.md). Camera, rendering, bots,
    # jump prediction and the editor still read player position/size in
    # px; these properties are the one conversion boundary they go
    # through, instead of each call site re-deriving PX_PER_UNIT.
    @property
    def x_px(self):
        return self.x * PX_PER_UNIT

    @property
    def y_px(self):
        return self.y * PX_PER_UNIT

    @property
    def size_px(self):
        return self.size * PX_PER_UNIT

    @property
    def target_cam_y_px(self):
        return self.target_cam_y * PX_PER_UNIT

    def render_pose_px(self, alpha=None):
        """Like :meth:`render_pose`, but in px for the renderer/camera."""
        x, y, angle = self.render_pose(alpha)
        return x * PX_PER_UNIT, y * PX_PER_UNIT, angle

    # ---- rects -----------------------------------------------------------
    def rect(self):
        return pygame.FRect(self.x, self.y, self.size, self.size)

    hitbox = rect

    def solid_hitbox(self):
        """Inner death hitbox: a per-gamemode fraction of the player size,
        centred (physics bible §3.2 — see HITBOX_SOLID_FRACTION)."""
        l, t, r, b = self._inner_bounds(self.x, self.y, self.size, self.mode)
        return pygame.FRect(l, t, r - l, b - t)

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
            (self.x, m.y, float(m.size), float(m.angle)))

    def set_x(self, x):
        """Teleport horizontally (test-from-cursor spawn) keeping the
        frame-start and interpolation bookkeeping consistent."""
        self.x = float(x)
        self._x_at_frame_start = self.x
        self.prev_x = self.x

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
            "move_dir": self.move_dir,
            "angle": self.angle, "bg_preset": self.bg_preset,
            "target_cam_y": self.target_cam_y,
            "free_cam_mode": self.free_cam_mode,
            "camera_locked": self.camera_locked,
            "blackout_value": self.blackout_value,
            "blackout_target": self.blackout_target,
            "color_index": self.color_index,
            "size": self.size,
            "coins": set(self.coins_collected),
            "passed": set(self.passed),
            "items": dict(self.items),
            "timers": dict(self.timers),
            "timers_running": set(self.timers_running),
        })
        # Checkpoint 7: the checkpoint event point, fired for both the
        # manual practice hotkey and the Checkpoint Trigger, since both
        # land here.
        self._fire_event(EVENT_CHECKPOINT)

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
        # .get: a checkpoint taken before this key existed (an in-memory
        # list from an older attempt in the same session) means "the only
        # direction there used to be".
        self.move_dir = cp.get("move_dir", 1)
        self.angle = cp["angle"]
        self.bg_preset = cp["bg_preset"]
        self.target_cam_y = cp["target_cam_y"]
        self.free_cam_mode = bool(cp.get("free_cam_mode", False))
        self.camera_locked = bool(cp.get("camera_locked", False))
        self.blackout_value = cp.get("blackout_value", 0.0)
        self.blackout_target = cp.get("blackout_target", 0.0)
        self.blackout_start = self.blackout_value
        self.blackout_start_frame = self.frame
        self.blackout_frames = 1
        self.color_index = cp.get("color_index", 0)
        self.player_color = channel_color(self.channels, self.color_index)[:3]
        self.size = float(cp.get("size", PLAYER_SIZE_UNITS))
        self.coins_collected = set(cp.get("coins", set()))
        self.passed = set(cp.get("passed", set()))
        self.items = dict(cp.get("items", self.items_pers))
        self.timers = dict(cp.get("timers", {}))
        self.timers_running = set(cp.get("timers_running", set()))
        self.held_orbs = set()
        self.on_ground = False
        self.alive = True
        self.won = False
        self.trail = []
        self._mirror = None
        self.dash_timer = 0
        self._sync_prev_pose()
        # Checkpoint 7: the respawn event point. Fired last, on the fully
        # restored state, so an Event Trigger that moves the player or
        # retunes the scenery is not overwritten by the restore itself.
        self._fire_event(EVENT_RESPAWN)
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
        """Blue orb (GD): flip gravity AND reverse momentum — falling into
        one launches you back the way you came, under the new gravity."""
        self._blue_flip(self)
        self.input_buffer = 0

    def activate_green_orb(self):
        """Green orb (GD): flip gravity only — momentum carries through,
        so the arc bends smoothly into the new direction instead of
        snapping like the blue orb."""
        self.grav *= -1
        self.input_buffer = 0

    def _blue_flip(self, b):
        b.grav *= -1
        if b.mode not in (MODE_WAVE, MODE_SWING):
            b.vy = -b.vy
        b.on_ground = False

    def activate_dash_orb(self, orb):
        """Directional dash from the orb's rotation, at the player's
        current move speed (so a dash never drifts the level out of sync
        with the music) and with no duration of its own: it runs until an
        S Block, a wall, death, or the button being released ends it.
        The gravity variant flips gravity whenever the dash ends, whatever
        ended it. The rotation is capped to ±70° off horizontal so an
        orb authored pointing straight up/down still dashes on a slight
        diagonal instead of moving purely vertically. A dash runs along
        the current gameplay direction (``move_dir``), so a dash orb in a
        reversed section carries the player backwards instead of
        cancelling the reversal for the dash's duration."""
        speed = self.move_speed
        angle = _clamp_dash_angle_rad(orb.get("r", 0))
        self.dash_vx = speed * math.cos(angle) * self.move_dir
        self.dash_vy = speed * math.sin(angle)
        self.dash_timer = DASH_TIMER_INFINITE
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

    def teleport_to_cell(self, dest, move_x=True, move_y=True):
        """Snap the player onto object ``dest``'s cell, centred in it.

        The one player-teleport primitive: the touch-based Teleport Orb /
        Portal pair (``activate_teleport`` below) and Checkpoint 6's
        group-fired Teleport Trigger (triggers.py's
        _apply_teleport_trigger) both land here, so a triggered teleport
        produces exactly the orb's end state -- same centring, the same
        quarter-damped vy, the same cooldown, and the same cleared trail
        so the renderer doesn't smear a line across the jump.

        ``move_x``/``move_y`` let a caller restrict the snap to one axis
        (the trigger's x_only/y_only fields); everything else about the
        teleport still happens, so a one-axis teleport is still a
        teleport.
        """
        if move_x:
            self.x = (dest["x"] * UNITS_PER_BLOCK
                      + (UNITS_PER_BLOCK - self.size) / 2)
        if move_y:
            self.y = (dest["y"] * UNITS_PER_BLOCK
                      + (UNITS_PER_BLOCK - self.size) / 2)
        self.vy *= 0.25
        self.teleport_cooldown = TELEPORT_COOLDOWN_TICKS
        self.trail = []
        if self._mirror is not None:
            self._mirror.trail = []
        self._sync_prev_pose()

    def activate_teleport(self, orb):
        gid = get_group_id(orb)
        if not gid:
            return
        group = [o for o in self._teleport_index.get(gid, []) if o is not orb]
        if not group:
            return
        dests = [o for o in group if o.get("dest")]
        dest = dests[0] if dests else group[0]
        self.teleport_to_cell(dest)

    def flip_gravity(self):
        self.grav *= -1
        self.on_ground = False

    def set_body_gravity(self, b, target):
        """Point body ``b``'s gravity at ``target`` (``1`` down, ``-1`` up).

        The one gravity-direction primitive: the T_GRAV_UP/T_GRAV_DOWN
        portals in _handle_interactions and Checkpoint 6's Gameplay
        Rotation trigger (triggers.py's _apply_gameplay_rotation_trigger)
        both go through here, so a triggered gravity change lands on the
        identical end state to touching the matching portal -- including
        the "already pointing that way = no-op" case, which is what keeps
        it from unsticking a body that is legitimately grounded.
        """
        if b.grav != target:
            b.grav = target
            b.on_ground = False

    def set_gameplay_direction(self, sign):
        """Point gameplay along ``sign`` (``1`` rightwards, ``-1``
        leftwards) -- the direction primitive behind Checkpoint 6's
        Reverse and Gameplay Rotation triggers.

        ``move_dir`` multiplies the auto-scroll step (and a dash's
        horizontal component) in update(); it is NOT folded into
        ``move_speed``, which stays a positive magnitude every speed
        portal, HUD readout, wave-velocity computation and bot heuristic
        already treats as one.
        """
        self.move_dir = 1 if sign >= 0 else -1

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
        if self._swept_hazard_death(b, prev_x, prev_y, new_x, new_y) and not self.noclip:
            return
        # Beam samples so the trail reads as a continuous warp line.
        beam_step = max(TELEPORT_BEAM_STEP_UNITS, b.size / 2)
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
        # The §3.2 hitbox is per-(mode, mini), so a mode portal resizes the
        # body: read mini from the OLD mode's table before overwriting it.
        mini = is_mini_size(b.mode, b.size)
        b.mode = mode
        self._set_body_size(b, body_size_units(mode, mini))
        if mode in (MODE_CUBE, MODE_BALL):
            b.angle = round(b.angle / 90) * 90
        elif mode in (MODE_WAVE, MODE_SWING):
            b.vy = 0.0
        elif mode == MODE_ROBOT:
            b.flight_budget = int(self.params.robot_flight_seconds * PHYSICS_TPS)
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
        b.size = float(new_size)

    def _set_size(self, new_size):
        self._set_body_size(self, new_size)

    def _enter_dual(self, obj=None):
        """Spawn the mirror with opposite gravity, inheriting the main
        body's current gamemode, size and motion (vy / angle sign-flipped)."""
        if self._mirror is not None:
            return
        spawn_row = obj.get("spawn_y") if obj else None
        if spawn_row is not None:
            mirror_y = float(spawn_row) * UNITS_PER_BLOCK
        else:
            mirror_y = PLAYFIELD_HEIGHT_UNITS - self.y - self.size
        self._mirror = MirrorBody(
            y=float(mirror_y), vy=-float(self.vy), grav=-self.grav,
            on_ground=bool(self._was_on_ground), angle=-float(self.angle),
            alive=True, mode=self.mode, size=float(self.size),
            flight_budget=int(self.flight_budget),
            thrust_disabled=bool(self.thrust_disabled))

    def _collapse_dual(self):
        """Solo portal: the mirror becomes the main body's pose."""
        m = self._mirror
        self.y = float(m.y)
        self.vy = float(m.vy)
        self.grav = int(m.grav)
        self.on_ground = bool(m.on_ground)
        self.angle = float(m.angle)
        self.mode = m.mode
        self.size = float(m.size)
        self.flight_budget = int(m.flight_budget)
        self.thrust_disabled = bool(m.thrust_disabled)
        self.wave_vy_smooth = float(m.wave_vy_smooth)
        self._mirror = None
        self._sync_prev_pose()

    def _kill(self, b, reason):
        if self.noclip:
            # This would have ended the run, so a live dash (which
            # otherwise only stops on release / an S Block) must still
            # end here too — otherwise it persists forever, its velocity
            # silently overriding every orb touched for the rest of the
            # session.
            if b is self and self.dash_timer > 0:
                self._end_dash()
            return
        was_alive = b.alive
        b.alive = False
        if b is self:
            self.death_reason = reason
        elif not self.death_reason:
            self.death_reason = reason + " (mirror)"
        # Checkpoint 7: the death event point for Event Triggers. Gated on
        # the alive->dead transition so a second lethal contact in the
        # same tick cannot fire it twice; the mirror's own death is not an
        # event here, it is one at the point where it collapses the main
        # body (see update()).
        if b is self and was_alive:
            self._fire_event(EVENT_DEATH)

    def _consume_hold(self, main):
        """Spend the current press: one press does at most one thing (a
        jump/flip/teleport OR an orb activation, whichever it hits
        first), so a held button that already fired a jump must not
        also fire a later orb during the same unreleased hold."""
        if main:
            self.input_buffer = 0
        else:
            self.mirror_input_buffer = 0

    # ---- mode physics (shared by both bodies) ---------------------------
    def _apply_mode_physics(self, b, mode_held, mode_pressed, raw_held,
                            input_pressed):
        p = self.params
        mode = b.mode
        main = b is self
        mini = is_mini_size(mode, b.size)
        gmul = p.mini_gravity_scale if mini else 1.0
        jmul = p.mini_jump_scale if mini else 1.0
        buffered_ground_press = mode_pressed or (
            mode_held and (self.input_buffer if main else self.mirror_input_buffer) > 0)
        # Portal labels aren't literal speed multiples; cube-derived jump
        # impulses also vary slightly between the five documented tiers.
        speed_ratio = self.move_speed / max(1e-9, p.base_move_speed)
        jump_tier = min(((0.807, 10.62), (1.0, 11.18), (1.243, 11.42),
                         (1.502, 11.23), (1.849, 11.23)),
                        key=lambda tier: abs(tier[0] - speed_ratio))[1] / 11.18
        if mode == MODE_SHIP:
            b.vy = p.ship_velocity(b.vy, b.grav, mini, mode_held)
        elif mode == MODE_WAVE:
            b.vy = p.wave_velocity(self.move_speed, b.grav, mini, mode_held)
        elif mode == MODE_UFO:
            falling = b.vy * b.grav > 0
            flying_scale = (0.9582 / 0.864) / (0.85 if mini else 1.0)
            b.vy += p.gravity * flying_scale * (0.4 if falling else 0.6) * gmul * b.grav
            size_factor = 1.0 / 0.85 if mini else 1.0
            b.vy = clamp(b.vy * b.grav, -MAX_RISE_UFO * size_factor,
                         MAX_FALL_UFO * size_factor) * b.grav
            flap_scale = (8.0 * 0.85 / 7.0) if mini else 1.0
            # Bible §1.4: UFO's click velocity is "a constant 7G at every
            # speed portal" for every click — grounded launch and midair
            # flap alike, so both branches use ufo_jump_force.
            if mode_pressed and b.on_ground:
                if main:
                    self._record_jump_timing("ufo", input_pressed)
                b.vy = p.ufo_jump_force * flap_scale * b.grav
                b.on_ground = False
                self._consume_hold(main)
            elif mode_pressed and not b.on_ground:
                b.vy = p.ufo_jump_force * flap_scale * b.grav
                self._consume_hold(main)
        elif mode == MODE_SPIDER:
            b.vy += p.gravity * (0.9582 / 0.864) * 0.6 * gmul * b.grav
            b.vy = clamp(b.vy, -MAX_FALL_BOX, MAX_FALL_BOX)
            if buffered_ground_press and b.on_ground:
                if main:
                    self._record_jump_timing("spider", input_pressed)
                self._spider_teleport(b)
                self._consume_hold(main)
        elif mode == MODE_SWING:
            b.vy += p.gravity * (0.9582 / 0.864) * (0.6 if mini else 0.4) * gmul * b.grav
            b.vy = clamp(b.vy, -MAX_FALL_SWING, MAX_FALL_SWING)
            if mode_pressed:
                if main:
                    self._record_jump_timing("swing", input_pressed)
                # Bible §1.4: click "multiplies the y-velocity by 0.8,
                # then toggles the gravity" — not a bare flip.
                b.vy *= SWING_VY_MULTIPLIER
                b.grav *= -1
                b.on_ground = False
                self._consume_hold(main)
        elif mode == MODE_ROBOT:
            # Bible §1.4: "gravity disabled while held" — a fixed hold
            # velocity (5.59G, "1/2 of cube jump", ROBOT_THRUST) replaces
            # gravity entirely for as long as the flight budget lasts;
            # gravity only resumes once released or the budget runs out.
            if not raw_held and not b.on_ground:
                b.thrust_disabled = True
            holding_thrust = (mode_held and (b.on_ground or b.vy * b.grav < 0)
                              and b.flight_budget > 0
                              and not b.thrust_disabled)
            if holding_thrust and b.on_ground and main and self._jump_block_armed:
                # J Block: suppress this one landing re-launch, then let
                # the button need a fresh press (bible Sec 4.1).
                self._jump_block_armed = False
                self._hold_consumed = True
                holding_thrust = False
            if holding_thrust:
                if b.on_ground:
                    if main:
                        self._record_jump_timing("robot", input_pressed)
                    b.on_ground = False
                b.vy = -p.robot_thrust * jump_tier * jmul * b.grav
                b.flight_budget -= 1
            else:
                b.vy += p.gravity * 0.9 * gmul * b.grav
            b.vy = clamp(b.vy, -MAX_FALL_BOX, MAX_FALL_BOX)
        elif mode == MODE_BALL:
            b.vy += p.gravity * (0.9582 / 0.864) * 0.6 * gmul * b.grav
            b.vy = clamp(b.vy, -MAX_FALL_BOX, MAX_FALL_BOX)
            if buffered_ground_press and b.on_ground:
                if main:
                    self._record_jump_timing("ball", input_pressed)
                b.grav *= -1
                b.vy = p.ball_flip_force * jump_tier * jmul * b.grav
                b.on_ground = False
                self._consume_hold(main)
        else:  # cube
            b.vy += p.gravity * gmul * b.grav
            b.vy = clamp(b.vy, -MAX_FALL_BOX, MAX_FALL_BOX)
            if mode_held and b.on_ground:
                if main and self._jump_block_armed:
                    # J Block: suppress this one landing auto-jump, then
                    # require a fresh press (bible Sec 4.1).
                    self._jump_block_armed = False
                    self._hold_consumed = True
                else:
                    if main:
                        self._record_jump_timing("cube", input_pressed)
                    b.vy = p.jump_force * jump_tier * jmul * b.grav
                    if input_pressed:
                        b.vy += p.gravity * gmul * b.grav
                    b.on_ground = False

    # Checkpoint-3 tick-rate migration (60 -> 240 TPS): the visual-angle
    # code below has two families of per-tick constant that don't rescale
    # automatically the way the physics constants in constants.py do
    # (those are expressed via PHYSICS_TPS formulas; these are bare
    # literals tuned by feel at the old 60 TPS), so they're converted by
    # hand here to preserve the exact same real-time rotation behavior:
    #   - vy-to-angle multipliers (4.2/2.8/3.0/2.5): b.vy is itself 4x
    #     smaller per tick at 240 TPS for the same real velocity (it's
    #     built from PHYSICS_TPS-scaled accel/impulse constants), so the
    #     multiplier that converts it back to a steady-state angle must
    #     scale up by 4x to land on the same angle for the same speed.
    #   - flat degrees-per-tick spins (10/6/5): these represent a fixed
    #     real angular velocity (e.g. 10 deg per 1/60s = 600 deg/s), so at
    #     240 TPS the same real rate is old/4 deg per tick.
    #   - exponential smoothing coefficients (0.55/0.45, 0.6, 0.7/0.3):
    #     these are single-pole IIR decay factors applied once per tick;
    #     since 240 TPS packs 4 ticks into the time one 60 TPS tick used
    #     to cover, the equivalent decay is k_new = k_old ** (1/4), not
    #     k_old/4 (a linear scale would decay far too slowly).
    def _apply_rotation(self, b):
        mode = b.mode
        if mode == MODE_SHIP:
            b.angle = clamp(-b.vy * 16.8, -55, 55)          # 4.2 * 4
        elif mode == MODE_UFO:
            b.angle = clamp(-b.vy * 11.2, -30, 30)          # 2.8 * 4
        elif mode == MODE_WAVE:
            # Keep wave movement deterministic/instant, but ease the icon's
            # visual heading.  Applying the filter to velocity (rather than
            # degrees) avoids a harsh snap through the horizontal at input
            # transitions and remains stable at the fixed 240 Hz tick rate.
            retain = WAVE_ANGLE_SMOOTHING
            b.wave_vy_smooth = (b.wave_vy_smooth * retain
                                + b.vy * (1.0 - retain))
            b.angle = math.degrees(math.atan2(
                -b.wave_vy_smooth, abs(self.move_speed)))
        elif mode == MODE_BALL:
            if b.on_ground:
                b.angle = round(b.angle / 90) * 90
            else:
                b.angle -= 2.5 * b.grav                     # 10 / 4
        elif mode == MODE_SPIDER:
            b.angle = 0 if b.on_ground else b.angle - 1.5 * b.grav  # 6 / 4
        elif mode == MODE_SWING:
            b.angle = clamp(-b.vy * 12.0, -45, 45)          # 3.0 * 4
        elif mode == MODE_ROBOT:
            if b.on_ground:
                b.angle = b.angle * 0.8801117                # 0.6 ** 0.25
            else:
                b.angle = (b.angle * 0.9146912
                           + clamp(-b.vy * 10.0, -35, 35) * 0.0853088)
                # 0.7 ** 0.25 decay; vy-mult 2.5*4=10.0; gain = 1-decay
        else:
            if not b.on_ground:
                b.angle -= 1.25 * b.grav                     # 5 / 4
            else:
                b.angle = round(b.angle / 90) * 90

    def _apply_pad(self, b, o):
        t = o["t"]
        p = self.params
        if t == T_SPIDER_PAD:
            self._spider_teleport(b, orb_direction(o))
            return
        if t == T_BLUE_PAD:
            self._blue_flip(b)
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

    def _apply_force_block(self, b, o):
        """Force Block (real GD id 2069) contact response.

        Returns True when the block's impulse was applied this frame.

        The one rule the report states outright, quoted verbatim from
        its "Force and state precedence" section:

            different ForceID  -> forces stack
            same ForceID       -> forces do not stack
            square vs circle   -> same force semantics, different
                                  collision geometry

        Lines 1-2 are implemented literally by ``_force_ids_this_frame``
        (cleared at the top of every update()): a block whose Force id is
        already in that set is skipped, and blocks with distinct Force
        ids each add their own impulse in the same frame. Line 3 has
        nothing to vary here -- this engine has no circle collision
        geometry, so the square/radius contact test below is the only
        geometry there is, and per the quote that does not change the
        force semantics anyway.

        EVERYTHING BELOW THAT RULE IS BEST-EFFORT. FlowVix (via the
        report) gives the field *names* and numeric keys -- relative 528,
        force 149, min_force 526, max_force 527, range 529, force_id 530
        -- but no source the report located documents their ranges,
        defaults or exact application semantics. This engine's reading,
        chosen as the simplest one consistent with those names and with
        the report's own operation type for this object ("ADD only
        across distinct ForceIDs"):

        * ``force`` is a signed vertical velocity delta, ADDED to ``vy``
          (never assigned, unlike an orb or pad) once per contact frame.
          Units match ``vy``: jump_force is about -2.8 units/tick, so
          +/-3 is roughly one cube jump of impulse.
        * ``relative`` ON multiplies it by the body's gravity sign, so a
          block authored to push away from the floor keeps doing that
          after a gravity flip. OFF applies it in absolute screen space,
          where +y is down.
        * ``min_force`` / ``max_force`` bound the MAGNITUDE of the
          resulting ``vy``; 0 on either side means "unbounded that way",
          so the default 0/0 block is a pure additive impulse.
        * ``range`` (stored ``force_range``) is a contact radius in grid
          squares, measured centre to centre, and is capped by
          FORCE_BLOCK_MAX_RANGE at the 2-cell margin
          _nearby_triggers_for_aabb searches.
        """
        try:
            fid = int(o.get("force_id", 0) or 0)
        except (TypeError, ValueError):
            fid = 0
        if fid in self._force_ids_this_frame:
            return False
        # Same pose cache the trigger loop's overlap test uses, so a
        # block sitting next to the player for a whole section costs one
        # cell_rect() rather than one per collision substep.
        caabb = o.get("_caabb")
        if caabb is None:
            cr = cell_rect(o["x"], o["y"], obj_scale(o))
            caabb = (cr.left, cr.top, cr.right, cr.bottom)
            o["_caabb"] = caabb
        cl, ct, cr_right, cb = caabb
        try:
            reach = float(o.get("force_range", FORCE_BLOCK_DEFAULT_RANGE))
        except (TypeError, ValueError):
            reach = FORCE_BLOCK_DEFAULT_RANGE
        reach *= UNITS_PER_BLOCK
        dx = (self.x + b.size * 0.5) - (cl + cr_right) * 0.5
        dy = (b.y + b.size * 0.5) - (ct + cb) * 0.5
        if dx * dx + dy * dy > reach * reach:
            return False
        try:
            force = float(o.get("force", 0.0))
        except (TypeError, ValueError):
            force = 0.0
        if o.get("relative"):
            force *= b.grav
        vy = b.vy + force
        try:
            lo = abs(float(o.get("min_force", 0.0) or 0.0))
            hi = abs(float(o.get("max_force", 0.0) or 0.0))
        except (TypeError, ValueError):
            lo = hi = 0.0
        magnitude = abs(vy)
        if hi > 0.0 and magnitude > hi:
            vy = math.copysign(hi, vy)
        elif lo > 0.0 and magnitude < lo:
            # A dead-stop body has no direction of its own to preserve,
            # so the floor is applied along the push instead.
            vy = math.copysign(lo, vy if vy else (force or 1.0))
        b.vy = vy
        # Only a push away from the surface ungrounds: a downward force
        # on a grounded body should not make it airborne.
        if vy * b.grav < 0.0:
            b.on_ground = False
        self._force_ids_this_frame.add(fid)
        return True

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
            self._blue_flip(b)
        elif t == T_GREEN_ORB:
            b.grav *= -1
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
                if (tr_right > wall_x and tr_left < wall_x + UNITS_PER_BLOCK
                        and prev_right <= wall_x):
                    # Checkpoint 7 added the event fire only; the win flag
                    # and the early return are untouched, and the End
                    # Trigger's handler is a second path into this exact
                    # flag (see triggers.py's _apply_end_trigger).
                    was_won = self.won
                    self.won = True
                    if not was_won:
                        self._fire_event(EVENT_WIN)
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
                    if not self.noclip:
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
            if t == T_FORCE_BLOCK:
                # Checkpoint 3: a placed contact object, handled here
                # beside the letter blocks rather than as a trigger --
                # it targets no group and has no TRIGGER_HANDLERS entry.
                # Tested before the cell-AABB gate below (like the pads
                # above) because its reach is its own ``force_range``
                # radius, not the object's cell. Main body only, matching
                # how S/J/D/H blocks are main-body-only in this engine;
                # never recorded in ``passed`` -- the per-frame ForceID
                # set is what limits repeat application.
                if main:
                    self._apply_force_block(b, o)
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
            if t == T_ITEM_PICKUP:
                # Item Pickup (editor reference Sec 4): touched once per
                # attempt like a coin/orb (``passed``-gated), grants
                # Amount to Item id's stored value.
                if main and key not in self.passed:
                    iid = int(o.get("item_id", 0))
                    try:
                        amt = float(o.get("amount", 1.0))
                    except (TypeError, ValueError):
                        amt = 1.0
                    self.items[iid] = self.items.get(iid, 0.0) + amt
                    self.passed.add(key)
                continue
            if t == T_DASH_STOP:
                # S Block: ends the dash it lands in, every time it is
                # touched, so it is never recorded in ``passed``.
                if main and self.dash_timer > 0:
                    self._end_dash()
                continue
            if t == T_JUMP_BLOCK:
                # J Block (bible Sec 4.1): flags the next landing so the
                # buffered auto-jump (holding through a fall/orb until
                # grounded, see mode_held checks in _apply_mode_physics)
                # is suppressed once. Touched every frame it overlaps, so
                # it is never recorded in ``passed`` either.
                if main:
                    self._jump_block_armed = True
                continue
            if t in ORB_TYPES:
                if (key in self.passed or key in self.held_orbs
                        or (not main and t not in _MIRROR_ORBS)):
                    continue
                cell = (o["x"], o["y"])
                if activated_orb_cell is None:
                    # GD orbs need a *fresh* click, not a sustained hold:
                    # ``input_active`` is true only on the click frame and
                    # for a short buffer window after it (see update()),
                    # so holding through a chain of orbs only fires the
                    # first one — later orbs need their own click.
                    if not input_active:
                        continue
                    if t == T_TELEPORT_ORB and self.teleport_cooldown != 0:
                        continue
                    activated_orb_cell = cell
                elif cell != activated_orb_cell:
                    continue
                if self._apply_orb(b, o):
                    # Multi-activate orbs stay out of ``passed`` so a
                    # later touch can fire them again; ``held_orbs``
                    # still blocks a refire within the same hold.
                    if o.get("multi_activate"):
                        self.held_orbs.add(key)
                    else:
                        self.passed.add(key)
                    if t == T_TELEPORT_ORB:
                        self.input_buffer = 0
                        return True
                    if not b.alive:
                        return True
                continue
            if t == T_TELEPORT_PORTAL:
                # Auto-teleport (GD orange portal): fires on touch, no
                # click required — unlike the teleport orb.
                if main and key not in self.passed:
                    self.passed.add(key)
                    if self.teleport_cooldown == 0:
                        self.activate_teleport(o)
                        return True
                continue
            if t in (T_GRAV_UP, T_GRAV_DOWN):
                if key not in body_passed:
                    self.set_body_gravity(b, -1 if t == T_GRAV_UP else 1)
                    body_passed.add(key)
            elif t in MODE_FROM_TYPE:
                if key not in body_passed:
                    self._set_body_mode(b, MODE_FROM_TYPE[t])
                    self._sync_prev_pose()
                    self.free_cam_mode = bool(o.get("free_mode", False))
                    body_passed.add(key)
            elif t == T_MODE_MINI:
                if key not in body_passed:
                    self._set_body_size(b, body_size_units(b.mode, True))
                    self._sync_prev_pose()
                    body_passed.add(key)
            elif t == T_MODE_BIG:
                if key not in body_passed:
                    self._set_body_size(b, body_size_units(b.mode, False))
                    self._sync_prev_pose()
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
            elif t in TRIGGER_TYPES:
                # Checkpoint 5 (editor reference Sec 4, "Key trigger
                # concepts"): a trigger only fires from a touch when
                # Touch Activated is on; by default it's line-activated
                # only, fired when a Spawn/Sequence/Toggle trigger names
                # its group. ``touch_activated`` defaults True (touch
                # allowed) here so control triggers (Spawn/Toggle/Stop/
                # Sequence/Repeat/item-logic), which don't carry the
                # field at all, stay reachable by touch as always; a
                # Toggle-disabled group's other triggers are inert
                # (except those control triggers themselves, which must
                # stay reachable to re-enable a chain); Multi Activate
                # re-arms every touch instead of firing once.
                if not o.get("touch_activated", True):
                    continue
                if t not in CONTROL_TRIGGER_TYPES and not self._trigger_active(o):
                    continue
                if key in self.passed and not o.get("multi_activate"):
                    continue
                # Deferred, not executed here: the effect runs from
                # update()'s single _drain_trigger_event_queue() call, in
                # the report's same-frame precedence order. The gating
                # above (touch_activated / _trigger_active / passed /
                # multi_activate) is unchanged -- only the moment of
                # execution moved.
                self._enqueue_trigger_event(o, TRIGGER_FAMILY_TOUCH)
                self.passed.add(key)
            elif key in self.passed:
                continue
        if activated_orb_cell is not None:
            if main:
                self.input_buffer = 0
            else:
                self.mirror_input_buffer = 0
        return False

    # ---- mirror step -----------------------------------------------------
    def _step_mirror(self, input_held, input_pressed, dx_step=0.0):
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
        # Sweep both axes, as the main body does. Checking only the final
        # x and a single y-spanning rectangle missed fast horizontal
        # hazards and created false hits away from the diagonal path.
        final_x = self.x
        steps = max(1, int(math.ceil(max(abs(dx_step), abs(m.vy)) / COLLISION_SUBSTEP_UNITS)))
        input_active = input_pressed or self.mirror_input_buffer > 0
        pad = TOUCH_PAD_UNITS
        try:
            self.x = final_x - dx_step
            for _ in range(steps):
                old_x, old_y = self.x, m.y
                self.x += dx_step / steps
                self._resolve_slopes(m)
                if self._resolve_x_collision(m, dx_step / steps):
                    return
                dy = m.vy / steps
                m.y += dy
                self._resolve_y_collision(m, dy)
                if not m.alive:
                    return
                self._resolve_slopes(m)
                if self._inner_in_block_dies(m) and not self.noclip:
                    return
                size = m.size
                x, y = self.x, m.y
                trigger_rect = pygame.FRect(
                    min(old_x, x) - pad, min(old_y, y) - pad,
                    abs(x - old_x) + size + pad * 2,
                    abs(y - old_y) + size + pad * 2)
                hazard_rect = pygame.FRect(x, y, size, size)
                if self._handle_interactions(m, trigger_rect, hazard_rect, input_active):
                    return
                input_active = self.mirror_input_buffer > 0
        finally:
            self.x = final_x
        cam_y = self.target_cam_y
        if (m.y > cam_y + FALL_OFF_BELOW_CAM_UNITS
                or m.y < cam_y - FALL_OFF_ABOVE_CAM_UNITS):
            self._kill(m, "Fell off the screen")
            return
        self._check_ground_adjacency(m)
        if m.mode == MODE_ROBOT and m.on_ground:
            m.flight_budget = int(self.params.robot_flight_seconds * PHYSICS_TPS)
            m.thrust_disabled = False
        self._apply_rotation(m)

    # ---- per-frame update ------------------------------------------------
    def update(self, input_held, input_pressed):
        if not self.alive or self.won:
            return
        # try/finally, not a plain trailing call: every trigger this
        # tick queued must still run on the ticks update() leaves early
        # (teleport orb/portal, death, win), exactly as the old inline
        # _execute_trigger_effect did -- the drain is the last step of
        # the tick on every exit path, and runs exactly once per tick.
        try:
            # A complete tap can arrive between render frames. Its press must
            # still last one simulation tick for cube, robot, ship and wave.
            input_held = input_held or input_pressed
            self.frame += 1
            # New tick, new set of Force Blocks that may push: the
            # report's stacking law is per-frame, and _handle_interactions
            # runs once per collision substep (plus once more for the
            # dual mirror), so without this a single block straddling
            # several substeps would apply its impulse several times.
            self._force_ids_this_frame.clear()
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
            self._step_scale_animations()
            self._step_alpha_animations()
            self._step_keyframe_animations()
            # Last of the object-transform steppers: an area effect layers
            # its falloff-scaled transform on top of whatever the tweens
            # above just wrote this tick, rather than being overwritten by
            # them. Area effects are *continuous* (they advance every tick
            # until stopped), so like every other _step_*, they run here
            # and not through the trigger event queue -- only an Area/Edit
            # Area/Area Stop *activation* goes through the queue.
            self._step_area_effects()
            self._step_zoom_animations()
            self._step_cam_offset_animations()
            self._step_cam_rotation_animations()
            self._step_screen_effects()
            self._step_pending_spawns()
            self._step_pending_repeats()
            self._step_pending_swaps()
            self._step_timers()
            self._step_count_watchers()
            self._step_follow_triggers()
            self._step_blackout()
            if self.active_pulses:
                self.active_pulses = [p for p in self.active_pulses
                                      if p["end_frame"] > self.frame]
            if self.teleport_cooldown > 0:
                self.teleport_cooldown -= 1
            self._sample_trails()
            if input_pressed:
                self.input_buffer = INPUT_BUFFER_TICKS
                self.mirror_input_buffer = INPUT_BUFFER_TICKS
            elif not input_held:
                # Only decay while released — a still-held press stays "fresh"
                # for orb purposes until it either fires something (consumed,
                # see the zeroing at each jump/orb site) or the button is let
                # go, instead of going stale after a fixed 6 frames even
                # though nothing has used it yet.
                if self.input_buffer > 0:
                    self.input_buffer -= 1
                if self.mirror_input_buffer > 0:
                    self.mirror_input_buffer -= 1
            if not input_held:
                self._hold_consumed = False
                self.held_orbs.clear()
                # Releasing the button cancels an active dash immediately.
                if self.dash_timer > 0:
                    self._end_dash()
            dashing = self.dash_timer > 0
            mode_held = input_held and not self._hold_consumed
            mode_pressed = input_pressed and not self._hold_consumed
            if not dashing:
                self._apply_mode_physics(self, mode_held, mode_pressed,
                                         input_held, input_pressed)
                if not self.alive:
                    self._record_hitbox()
                    return
                # move_dir is +1 (rightwards) unless a Reverse / Gameplay
                # Rotation trigger flipped it -- see set_gameplay_direction.
                dx = self.move_speed * self.move_dir
            else:
                self.vy = self.dash_vy
                dx = self.dash_vx
                self.dash_timer -= 1
                if self.dash_timer == 0:
                    self._end_dash()
            self.on_ground = False
            steps = max(1, int(math.ceil(
                max(abs(dx), abs(self.vy)) / COLLISION_SUBSTEP_UNITS)))
            dx_step = dx / steps
            # Click-edge, not sustained hold: an orb fires on the click frame
            # (or within the short buffer window after it), never merely
            # because the button is still held down from an earlier click —
            # otherwise holding through a chain of orbs would fire all of
            # them instead of only the first, unlike real GD.
            input_active = input_pressed or self.input_buffer > 0
            size = self.size
            pad = TOUCH_PAD_UNITS
            for _ in range(steps):
                prev_x, prev_y = self.x, self.y
                self.x += dx_step
                # Slope x-pass lifts the cube up a ramp before the wall test.
                self._resolve_slopes(self)
                if self._resolve_x_collision(self, dx_step):
                    self._record_hitbox()
                    return
                dy_step = self.vy / steps
                self.y += dy_step
                self._resolve_y_collision(self, dy_step)
                if not self.alive:
                    self._record_hitbox()
                    return
                self._resolve_slopes(self)
                if self._inner_in_block_dies(self) and not self.noclip:
                    self._record_hitbox()
                    return
                cur_x, cur_y = self.x, self.y
                tr_left = min(prev_x, cur_x) - pad
                tr_top = min(prev_y, cur_y) - pad
                tr_right = max(prev_x, cur_x) + size + pad
                tr_bottom = max(prev_y, cur_y) + size + pad
                trigger_rect = pygame.FRect(tr_left, tr_top, tr_right - tr_left,
                                            tr_bottom - tr_top)
                # Bible §3.4: real GD's hazard forgiveness lives in the
                # HAZARD shapes (a spike's danger box is 9 x 19.2 units
                # inside its 30-unit cell — see geometry.spike_hitboxes),
                # not in a shrunken player box; §3.2's red box is the whole
                # body.  The rotated-hazard path a few lines into
                # _handle_interactions already used the full box, so the
                # old inset also made an axis-aligned spike more forgiving
                # than the same spike rotated 1 degree.
                hazard_rect = pygame.FRect(cur_x, cur_y, size, size)
                if self._handle_interactions(self, trigger_rect, hazard_rect,
                                             input_active):
                    self._check_ground_adjacency(self)
                    self._record_hitbox()
                    return
                input_active = self.input_buffer > 0
                size = self.size  # portals may have resized us mid-frame
            self._check_ground_adjacency(self)
            if self.mode == MODE_ROBOT and self.on_ground:
                self.flight_budget = int(self.params.robot_flight_seconds * PHYSICS_TPS)
                self.thrust_disabled = False
            if self.free_cam_mode:
                # Continuous camera tracking (e.g. a "follow" camera trigger):
                # the fall-off band rides with the player, so free-cam sections
                # never have a screen edge. play.py's _tick_camera derives the
                # same target for the *visual* eased camera; this keeps the
                # physics check (bots, jump predictor, headless sims — none of
                # which run _tick_camera) in sync without needing that call.
                self.target_cam_y = (self.y + self.size / 2
                                     - CAMERA_HEIGHT_UNITS / 2)
            cam_y = self.target_cam_y
            if (self.y > cam_y + FALL_OFF_BELOW_CAM_UNITS
                    or self.y < cam_y - FALL_OFF_ABOVE_CAM_UNITS):
                self._kill(self, "Fell off the screen")
                return
            if self._mirror is not None:
                dx_step = self.x - self.prev_x
                # A dash consumes input for its whole window; don't let the
                # mirror re-react to the mechanical hold.
                if dashing:
                    self._step_mirror(False, False, dx_step)
                else:
                    self._step_mirror(input_held, input_pressed, dx_step)
                if self._mirror is not None and not self._mirror.alive:
                    was_alive = self.alive
                    self.alive = False
                    if not self.death_reason:
                        self.death_reason = "Mirror died"
                    # The one death path that does not go through _kill:
                    # the mirror died and collapses the main body with it.
                    if was_alive:
                        self._fire_event(EVENT_DEATH)
                    return
            self._apply_rotation(self)
            # Player-following links need the post-physics pose.
            self._step_follow_triggers()
            self._record_hitbox()
            self._record_mirror_hitbox()
        finally:
            self._drain_trigger_event_queue()

    def _sample_trails(self):
        # GD's trail is a solid streak, not a fading dotted line — keep
        # every sample at full alpha and only drop ones the camera has
        # scrolled far enough past that they can never be on screen again
        # (bounds memory without visually fading anything).
        if self.frame % 3 == 0:
            self.trail.append([self.x, self.y, self.angle, 100])
            m = self._mirror
            if m is not None and m.alive:
                m.trail.append([self.x, m.y, m.angle, 100])
        cutoff = self.x - TRAIL_MAX_DISTANCE_UNITS
        if self.trail:
            self.trail = [seg for seg in self.trail if seg[0] > cutoff]
        m = self._mirror
        if m is not None and m.trail:
            m.trail = [seg for seg in m.trail if seg[0] > cutoff]
