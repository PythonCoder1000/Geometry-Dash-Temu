"""Game constants: window/grid, physics tunables, paths, object type names,
type sets, and the colour palette.

Per-type *metadata* (display names, tips, palette tabs, editable fields)
lives in :mod:`objects` — see :data:`objects.SPECS`.  Any change to an
object type or to ``LEVEL_FORMAT_VERSION`` must be paired with a migration
in :mod:`levels` so existing levels keep loading.
"""
import os
import sys

# ---------------------------------------------------------------------------
# Window / grid / timing
# ---------------------------------------------------------------------------
WIDTH, HEIGHT = 1200, 700
# Internal editor/world cell.  Gameplay and level files are authored against
# this stable value; presentation zoom is handled by the camera/editor.
CELL = 50
# Real GD units per editor block (verified live 2026-09-07 against the
# Move Trigger's "Small Step" behavior: Small Step only changes the
# trigger UI's input granularity, not the underlying scale, which is
# always 30). This is the canonical world unit — see src/units.py and
# docs/development/UNITS_REFACTOR.md. CELL above is a RENDER-ONLY
# constant (px per block on screen at zoom 1); it must not be used by
# physics/collision/bot code once that refactor is complete.
UNITS_PER_BLOCK = 30.0
# Canonical physics tick rate. Physics bible Part 0 / §2.7: real GD
# standardized its physics loop to 240 TPS in Update 2.2 (Dec 19, 2023);
# this engine now matches. Every "per tick" constant below is expressed
# in terms of PHYSICS_TPS (see VEL_PX_PER_TICK / GRAVITY's formulas), so
# most of them rescale automatically when this changes — the ones that
# don't (BASE_MOVE_SPEED, INPUT_BUFFER_TICKS, and any literal frame count
# elsewhere) are called out at their own definition. The renderer runs at
# any FPS and interpolates between ticks (see play.PlaySession).
FPS = 240
PHYSICS_TPS = 240
GROUND_Y = 550

# Maximum motion (px) covered by a single inner collision substep.
COLLISION_SUBSTEP_PX = 1.0

# Two-hitbox model: the OUTER rect (full sprite size, rotated with the
# player) triggers hazards / orbs / pads / triggers; the INNER rect (a
# per-gamemode fraction of the size, centred, axis-aligned) triggers block
# death. The fraction now varies by (mode, mini) per the physics bible's
# §3.2 hitbox table — see HITBOX_SOLID_FRACTION / SOLID_HITBOX_FRACTION
# further down (after the mode constants they're keyed on).

# ---------------------------------------------------------------------------
# Player tunables (physics)
#
# Calibration: docs/PHYSICS.md; archived research under docs/reference/.
# The reference states
# gamemode speeds in "Vels" (1 Vel = 60 GD units/second) and distances in
# GD units (1 editor block = 30 units = one CELL on screen).  We convert
# through this engine's existing px/CELL scale so every constant below is
# auditable against the bible's numbers:
#
#     PX_PER_UNIT     = CELL / 30          (px per GD unit)
#     VEL_PX_PER_TICK = 60 * PX_PER_UNIT / PHYSICS_TPS   (px/tick per 1 Vel)
#
# Horizontal and vertical quantities must use the SAME unit conversion.
# Keeping the old 300 px/s scroll with GD jump velocities made arcs narrow.
# ---------------------------------------------------------------------------
PLAYER_SIZE = 44
MINI_PLAYER_SIZE = 24

PX_PER_UNIT = CELL / UNITS_PER_BLOCK
VEL_PX_PER_TICK = 60.0 * PX_PER_UNIT / PHYSICS_TPS  # == PX_PER_UNIT at 60 TPS
# Public: any px-space length/velocity/accel literal -> its GD-unit
# equivalent (the tick-based integration means the same factor applies to
# positions, velocities and accelerations alike). Used both to derive the
# *_UT constants below and for one-off literal conversions in player/
# collision code migrated to units.
PX_TO_UNIT_RATIO = 1.0 / PX_PER_UNIT


def px_to_units(v_px):
    return v_px * PX_TO_UNIT_RATIO

# ---------------------------------------------------------------------------
# Canonical GD-unit constants (units/second, units/second^2).
#
# The bible expresses velocities in "Vels" (1 Vel = 60 GD units/second —
# the legacy 60 fps-per-frame convention) and accelerations as a Vel-like
# factor times 60^2. VEL_UNIT_PER_S below IS that "1 Vel", named for what
# it actually is instead of leaving it as an inline literal. These _UPS /
# _UPS2 constants are the ones player/collision/bot code should migrate
# to (see docs/development/UNITS_REFACTOR.md); the legacy *_PX-scale names
# further down are still derived from them so nothing else has to change
# yet, and their numeric values are unchanged by this refactor.
# ---------------------------------------------------------------------------
VEL_UNIT_PER_S = 60.0  # 1 "Vel" (bible units)

def _vel_ups(vels):
    """Bible "Vels" -> GD units/second."""
    return vels * VEL_UNIT_PER_S


def _accel_ups2(factor):
    """Bible acceleration factor -> GD units/second^2."""
    return factor * VEL_UNIT_PER_S ** 2


def _ups_to_px_per_tick(v_ups):
    """GD units/second -> px/tick, at this engine's render/tick scale."""
    return v_ups * PX_PER_UNIT / PHYSICS_TPS


def _ups2_to_px_per_tick2(a_ups2):
    """GD units/second^2 -> px/tick^2."""
    return a_ups2 * PX_PER_UNIT / PHYSICS_TPS ** 2


BASE_MOVE_SPEED_UPS = _vel_ups(5.193)
BASE_MOVE_SPEED = _ups_to_px_per_tick(BASE_MOVE_SPEED_UPS)

# 0.216 velocity units per 240 Hz tick (reference §1.3). The old
# 72 blocks/s² estimate contradicted that and produced a 3.5-block jump.
GRAVITY_UPS2 = _accel_ups2(0.864)
GRAVITY = _ups2_to_px_per_tick2(GRAVITY_UPS2)

# Flying modes use 0.9582 base acceleration in updateJump's decompilation.
# Ship's baseline ascent factor is 0.4; release depends on momentum.
SHIP_GRAVITY_UPS2 = _accel_ups2(0.9582 * 0.4)
SHIP_GRAVITY = _ups2_to_px_per_tick2(SHIP_GRAVITY_UPS2)
SHIP_THRUST_UPS2 = SHIP_GRAVITY_UPS2 * 2.0
SHIP_THRUST = SHIP_GRAVITY * 2.0

# Cube jump velocity, 1x speed portal: bible §1.4 table, 11.18G.
JUMP_FORCE_UPS = -_vel_ups(11.18)
JUMP_FORCE = _ups_to_px_per_tick(JUMP_FORCE_UPS)
# Pads: no distinct bible figure (the bible documents gamemode click
# velocities, not a separate pad table) — ratio to JUMP_FORCE preserved
# from the pre-retune tuning (pads hit ~12% harder than the yellow orb).
PAD_FORCE_UPS = JUMP_FORCE_UPS * 1.125
PAD_FORCE = JUMP_FORCE * 1.125
# Ball click velocity, 1x speed: bible §1.4 / §1.3, "3.354G (3/10 of cube)".
BALL_FLIP_FORCE_UPS = _vel_ups(3.354)
BALL_FLIP_FORCE = _ups_to_px_per_tick(BALL_FLIP_FORCE_UPS)
DASH_SPEED = 16.0
# Dash duration: not given numerically anywhere in the bible (only
# qualitative orb-buffering behavior around dash orbs, §2.4). Also dead
# in practice: a dash's `dash_timer` is only ever set to 0 or
# DASH_TIMER_INFINITE at the call sites in player/core.py, never to this
# value, so DASH_TIME/PhysicsParams.dash_time is unused — a dash now runs
# until something stops it (S Block / wall / death), not for a fixed
# tick count. Left unscaled since no live code reads it.
DASH_TIME = 9
# A dash now runs until something stops it (an S Block, a wall, death),
# so the per-tick countdown is seeded with a value it can never reach.
DASH_TIMER_INFINITE = 10 ** 9
# Wave: bible §1.4, "Normal trail = 45 degrees" — already matched, kept.
WAVE_ANGLE = 45.0
# The wave's movement direction changes on button edges, but its icon does
# not visually snap to the new diagonal in one 240 Hz tick.  This is the
# per-tick retention used by the render-facing angle filter.
WAVE_ANGLE_SMOOTHING = 0.96
PLAYER_START_GX = 3
# UFO: bible §1.4, "constant 7G at every speed portal" — this single
# value is now used for BOTH the grounded launch and the midair flap
# (see player/core.py's _apply_mode_physics, MODE_UFO branch).
UFO_JUMP_FORCE_UPS = -_vel_ups(7.0)
UFO_JUMP_FORCE = _ups_to_px_per_tick(UFO_JUMP_FORCE_UPS)
SPIDER_TELEPORT_RANGE = 6  # cells (legacy; teleports are now unbounded)
# Robot: bible §1.4, "Hold velocity 5.59G (1/2 of cube jump)... gravity
# disabled while held." Repurposed from a per-tick thrust subtracted
# against gravity into the fixed hold velocity itself (gravity is now
# skipped entirely while the hold is active — see core.py).
ROBOT_THRUST_UPS = _vel_ups(5.59)
ROBOT_THRUST = _ups_to_px_per_tick(ROBOT_THRUST_UPS)
# The decompiled timer advances by dt/10 with dt in 60 Hz units:
# its 1.5 limit represents 15/60 seconds, not 1.5 seconds.
ROBOT_FLIGHT_SECONDS = 0.25

# Per-mode max-fall / max-rise magnitudes (bible §1.3 table). Modes not
# listed here (Wave has no gravity; Spider's fall is defined by its
# instant teleport, not acceleration, per §1.4) don't use a fall clamp.
MAX_FALL_BOX_UPS = _vel_ups(15.0)           # Cube / Ball / Robot / Spider: -15G
MAX_FALL_BOX = _ups_to_px_per_tick(MAX_FALL_BOX_UPS)
MAX_FALL_UFO_UPS = _vel_ups(6.4)            # UFO: -6.4G
MAX_FALL_UFO = _ups_to_px_per_tick(MAX_FALL_UFO_UPS)
MAX_RISE_UFO_UPS = _vel_ups(8.0)
MAX_RISE_UFO = _ups_to_px_per_tick(MAX_RISE_UFO_UPS)
MAX_FALL_SWING_UPS = _vel_ups(8.0)          # Swing: -8G
MAX_FALL_SWING = _ups_to_px_per_tick(MAX_FALL_SWING_UPS)
SHIP_MAX_RISE_UPS = _vel_ups(8.0)           # Ship (holding): 8G
SHIP_MAX_RISE = _ups_to_px_per_tick(SHIP_MAX_RISE_UPS)
SHIP_MAX_FALL_UPS = _vel_ups(6.4)           # Ship (released): -6.4G
SHIP_MAX_FALL = _ups_to_px_per_tick(SHIP_MAX_FALL_UPS)
# Swing click: bible §1.4, "multiplies the y-velocity by 0.8, then
# toggles the gravity" — applied in core.py's MODE_SWING branch.
SWING_VY_MULTIPLIER = 0.8

# ---------------------------------------------------------------------------
# Unit-space (GD units / GD units-per-tick) twins of the constants above,
# for player/collision code migrated to units (see
# docs/development/UNITS_REFACTOR.md, Phase 2/3). Derived by dividing the
# already-verified px constant by PX_PER_UNIT rather than re-deriving from
# the bible numbers a second time, so `value_ut * PX_PER_UNIT ==
# value_px` is exact by construction — no room for the two families to
# drift apart.
# ---------------------------------------------------------------------------
GRAVITY_UT = px_to_units(GRAVITY)
SHIP_GRAVITY_UT = px_to_units(SHIP_GRAVITY)
SHIP_THRUST_UT = px_to_units(SHIP_THRUST)
JUMP_FORCE_UT = px_to_units(JUMP_FORCE)
PAD_FORCE_UT = px_to_units(PAD_FORCE)
BALL_FLIP_FORCE_UT = px_to_units(BALL_FLIP_FORCE)
UFO_JUMP_FORCE_UT = px_to_units(UFO_JUMP_FORCE)
BASE_MOVE_SPEED_UT = px_to_units(BASE_MOVE_SPEED)
ROBOT_THRUST_UT = px_to_units(ROBOT_THRUST)
MAX_FALL_BOX_UT = px_to_units(MAX_FALL_BOX)
MAX_FALL_UFO_UT = px_to_units(MAX_FALL_UFO)
MAX_RISE_UFO_UT = px_to_units(MAX_RISE_UFO)
MAX_FALL_SWING_UT = px_to_units(MAX_FALL_SWING)
SHIP_MAX_RISE_UT = px_to_units(SHIP_MAX_RISE)
SHIP_MAX_FALL_UT = px_to_units(SHIP_MAX_FALL)
PLAYER_SIZE_UNITS = px_to_units(PLAYER_SIZE)
MINI_PLAYER_SIZE_UNITS = px_to_units(MINI_PLAYER_SIZE)
COLLISION_SUBSTEP_UNITS = px_to_units(COLLISION_SUBSTEP_PX)
# HEIGHT is the render/screen-space height in px (window size), used by
# player/core.py for the "fell off the screen" bound and free-cam target
# alongside a unit-space player position — needs the same conversion.
HEIGHT_UNITS = px_to_units(HEIGHT)

# Mini ground modes scale jump velocity by 0.8. Flying modes have their
# own acceleration factors in core.py; extra per-level scaling stays optional.
MINI_GRAVITY_SCALE = 1.0
MINI_JUMP_SCALE = 0.8
# Bible §1.6: "Wave takes sharper diagonals (~63.43 degrees vs 45)" in
# mini mode — an exact 2:1-slope figure, so this scale is now sourced:
# 63.43 / WAVE_ANGLE(45).
MINI_WAVE_ANGLE_SCALE = 63.43 / 45.0
# Mini wave travels at twice the vertical speed, with no ramp.
MINI_WAVE_VY_SCALE = 2.0

# Player trail: solid (no fade) while on screen; samples further behind
# the player than this (world px) are dropped so the list doesn't grow
# without bound over a long run.
TRAIL_MAX_DISTANCE = WIDTH * 3
TRAIL_MAX_DISTANCE_UNITS = px_to_units(TRAIL_MAX_DISTANCE)

# Orb / pad strength multipliers relative to JUMP_FORCE / PAD_FORCE.
# Mirrors GD: pink = small, yellow = medium, red = big. No bible figure
# exists for these ratios (the bible documents gamemode click velocities,
# not per-orb-color scales) — retained from pre-retune tuning.
ORB_PINK_SCALE = 0.75
ORB_RED_SCALE = 1.35
PAD_PINK_SCALE = 0.75
PAD_RED_SCALE = 1.35

# ---------------------------------------------------------------------------
# Input buffering (physics bible Part 2)
# ---------------------------------------------------------------------------
# player.core.Player pre-remembers a click for this many *ticks* so a
# press slightly before landing / before entering an orb's hitbox still
# fires the instant it becomes valid (bible §2.2-§2.5: a real, code-level
# mechanic, not just a player habit). Bible §2.6 is explicit that "no
# numeric orb buffer window is published anywhere" — this engine's own
# window predates the bible and was 6 frames at the old 60 TPS (0.1s);
# rescaled here to the same real-world duration at the new 240 TPS
# (6 * 240/60 = 24) rather than invented from the bible, which has no
# figure to invent from.
INPUT_BUFFER_TICKS = 24

# Teleport-orb re-trigger cooldown: was 10 ticks at 60 TPS (~0.167s); no
# bible figure exists for this (it's an engine-internal debounce, not a
# documented GD mechanic), so it's rescaled to preserve the same real
# duration at 240 TPS: 10 * 240/60 = 40.
TELEPORT_COOLDOWN_TICKS = 40

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _app_root():
    """Directory holding the read-only ``assets/`` folder."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return meipass
    here = os.path.dirname(os.path.abspath(__file__))
    for _ in range(4):
        if os.path.isdir(os.path.join(here, "assets")):
            return here
        parent = os.path.dirname(here)
        if parent == here:
            break
        here = parent
    return os.path.dirname(os.path.abspath(__file__))


def _is_frozen():
    return getattr(sys, "frozen", False) or hasattr(sys, "_MEIPASS")


def _user_data_dir():
    """Per-user writable directory.  Dev checkouts write into the repo
    (override with ``GDT_DEV_LOCAL=0``); frozen builds use the OS data dir."""
    override = os.environ.get("GDT_DEV_LOCAL")
    if override == "1" or (override != "0" and not _is_frozen()):
        return _app_root()
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME",
                              os.path.expanduser("~/.local/share"))
    path = os.path.join(base, "TrigonometrySprint")
    legacy = os.path.join(base, "GeometryDashTemu")
    if not os.path.isdir(path) and os.path.isdir(legacy):
        try:
            import shutil
            shutil.copytree(legacy, path)
        except OSError:
            pass
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        path = _app_root()
    return path


_ROOT = _app_root()
_USER_DATA = _user_data_dir()

ASSETS_DIR = os.path.join(_ROOT, "assets")
LEVELS_DIR = os.path.join(_USER_DATA, "levels")
BOT_RUNS_DIR = os.path.join(_USER_DATA, "bot_runs")
PREFS_FILE = os.path.join(_USER_DATA, "prefs.json")
USER_MUSIC_DIR = os.path.join(_USER_DATA, "music")
_BUNDLED_LEVELS_DIR = os.path.join(_ROOT, "levels")

# v7: blue/green orb semantics aligned with Geometry Dash (see
# levels._migrate_objects), speed_fastest + new pads added.
# v8: arbitrary multi-membership object groups (``groups: [int, ...]``,
# generalizing the old single ``group`` int) and a level-level color-
# channel table (see channels.py) replacing the Color/Pulse Trigger's
# direct ``col_idx`` palette lookup with a ``channel`` reference — both
# migrated transparently in levels.normalize_object, no version-gated
# migration function needed (same pattern as the teleport ``link`` ->
# ``group_id`` shim already there).
LEVEL_FORMAT_VERSION = 8

# ---------------------------------------------------------------------------
# Object type names (strings stored in level JSON — do not rename casually)
# ---------------------------------------------------------------------------
T_BLOCK = "block"
T_SLAB = "slab"
T_SLOPE = "slope"
T_SPIKE = "spike"
T_HALF_SPIKE = "half_spike"
T_SAW = "saw"
T_ORB = "orb"                    # yellow: medium jump
T_PINK_ORB = "pink_orb"          # small jump
T_RED_ORB = "red_orb"            # big jump
T_BLUE_ORB = "blue_orb"          # gravity flip
T_GREEN_ORB = "green_orb"        # jump + gravity flip
T_BLACK_ORB = "black_orb"        # downward slam
T_DASH_ORB = "dash_orb"          # green dash: hold to dash
T_DASH_ORB_GRAV = "dash_orb_grav"  # pink dash: dash, flip gravity on release
T_SPIDER_ORB = "spider_orb"
T_TELEPORT_ORB = "teleport_orb"
# GD "orange" teleport portal: same group-linked pairing as the teleport
# orb, but fires the instant it's touched — no click needed.
T_TELEPORT_PORTAL = "teleport_portal"
T_PAD = "pad"                    # yellow
T_PINK_PAD = "pink_pad"
T_RED_PAD = "red_pad"
T_BLUE_PAD = "blue_pad"          # gravity flip
T_SPIDER_PAD = "spider_pad"      # instant spider teleport
T_GRAV_UP = "grav_up"
T_GRAV_DOWN = "grav_down"
T_END = "end"
T_START = "start"
T_COIN = "coin"
# Transient: practice-mode checkpoints are never serialized.
T_CHECKPOINT = "checkpoint"
T_MODE_CUBE = "mode_cube"
T_MODE_SHIP = "mode_ship"
T_MODE_BALL = "mode_ball"
T_MODE_WAVE = "mode_wave"
T_MODE_UFO = "mode_ufo"
T_MODE_SPIDER = "mode_spider"
T_MODE_SWING = "mode_swing"
T_MODE_ROBOT = "mode_robot"
T_MODE_MINI = "mode_mini"
T_MODE_BIG = "mode_big"
T_MODE_DUAL = "mode_dual"
T_MODE_SOLO = "mode_solo"
T_SPEED_SLOW = "speed_slow"
T_SPEED_NORMAL = "speed_normal"
T_SPEED_FAST = "speed_fast"
T_SPEED_FASTER = "speed_faster"
T_SPEED_FASTEST = "speed_fastest"
T_DECO_CRYSTAL = "deco_crystal"
T_DECO_PILLAR = "deco_pillar"
T_DECO_GLOW = "deco_glow"
T_CAMERA_TRIGGER = "camera_trigger"
T_BG_TRIGGER = "bg_trigger"
T_MOVE_TRIGGER = "move_trigger"
T_COLOR_TRIGGER = "color_trigger"
T_PULSE_TRIGGER = "pulse_trigger"
T_ROTATE_TRIGGER = "rotate_trigger"
T_FOLLOW_TRIGGER = "follow_trigger"
T_TIME_WARP = "time_warp"
T_BLACKOUT_TRIGGER = "blackout_trigger"
# Checkpoint 5 (editor reference Sec 4, "logic/spawn family"): the
# "glue" triggers that chain other triggers together via group ids.
T_SPAWN_TRIGGER = "spawn_trigger"
T_TOGGLE_TRIGGER = "toggle_trigger"
T_STOP_TRIGGER = "stop_trigger"
T_SEQUENCE_TRIGGER = "sequence_trigger"
T_SCALE_TRIGGER = "scale_trigger"
T_ALPHA_TRIGGER = "alpha_trigger"
# Editor-only helpers (inert at play time).
T_JUMP_PREDICTOR = "jump_predictor"
T_BOT_CHECKPOINT = "bot_checkpoint"
# Editor utility: stops an active dash on contact (invisible by default).
T_DASH_STOP = "dash_stop"
# Letter blocks (physics bible Part 4) -- invisible-by-default editor
# utilities, same "checked directly by type" pattern as T_DASH_STOP (S
# Block) above, not part of any collision-shape frozenset.
# J Block: suppresses the one landing auto-jump that fires when the
# player held input through an orb (bible Sec 4.1).
T_JUMP_BLOCK = "jump_block"
# D Block: lets Wave slide along a block's top surface instead of dying
# on contact (bible Sec 4.3).
T_WAVE_BLOCK = "wave_block"
# H Block: Cube/Robot bonk off a block's underside/side instead of dying
# (bible Sec 4.4).
T_BONK_BLOCK = "bonk_block"

# Checkpoint 6 (editor reference Sec 4, "Camera" family): expands the
# existing pan/static/follow T_CAMERA_TRIGGER with dedicated zoom,
# detached-offset, view-rotate, travel-bound, and follow-smoothing
# triggers.
T_ZOOM_TRIGGER = "zoom_trigger"
T_CAM_OFFSET_TRIGGER = "cam_offset_trigger"
T_CAM_ROTATE_TRIGGER = "cam_rotate_trigger"
T_CAM_EDGE_TRIGGER = "cam_edge_trigger"
T_CAM_GUIDE_TRIGGER = "cam_guide_trigger"
# Checkpoint 6 (editor reference Sec 4, "Screen effects / shaders"): the
# best-effort subset feasible in pygame's surface pipeline without a GPU
# shader stage (per-pixel color remaps + block resampling). Chromatic,
# Chromatic Glitch, Radial Blur, Motion Blur, Bulge, Pinch, Lens Circle,
# Split Screen, Shock Wave and Shock Line need real per-pixel
# displacement/convolution and are deliberately NOT implemented — see
# docs/development/AUDIT.md.
T_GRAYSCALE_TRIGGER = "grayscale_trigger"
T_SEPIA_TRIGGER = "sepia_trigger"
T_INVERT_TRIGGER = "invert_trigger"
T_HUE_TRIGGER = "hue_trigger"
T_PIXELATE_TRIGGER = "pixelate_trigger"

# Checkpoint 7 (editor reference Sec 4, "Item / counter / timer system"):
# a touch-collectible that grants/removes a value from a numbered item id
# (self.items on Player), plus the logic triggers that read/write it and
# an on-screen display object. Item Pickup is collectible-shaped (touched
# at its own position, like a coin), not a trigger-volume, so it is NOT
# in TRIGGER_TYPES; Item Counter is a passive HUD display, also not a
# trigger.
T_ITEM_PICKUP = "item_pickup"
T_COUNT_TRIGGER = "count_trigger"
T_INSTANT_COUNT_TRIGGER = "instant_count_trigger"
T_ITEM_EDIT_TRIGGER = "item_edit_trigger"
T_ITEM_COMP_TRIGGER = "item_comp_trigger"
T_ITEM_PERS_TRIGGER = "item_pers_trigger"
T_TIME_TRIGGER = "time_trigger"
T_TIME_EVENT_TRIGGER = "time_event_trigger"
T_ITEM_COUNTER = "item_counter"

# Checkpoint 8 (editor reference Sec 4, simplified keyframe system): a
# data-only marker object (position/rotation/scale target + per-keyframe
# timing/easing), grouped by an ``animation_id`` the same way a group id
# groups objects a trigger acts on, plus the trigger that plays a target
# group through an animation's keyframes in order -- replaces chaining
# separate Move+Rotate+Scale triggers for a complex sequence. A Keyframe
# is never touch-activated (pure data, read by whichever Keyframe
# Animation Trigger names its animation id), so it is NOT in
# TRIGGER_TYPES -- same reasoning as Item Pickup above.
T_KEYFRAME = "keyframe"
T_KEYFRAME_TRIGGER = "keyframe_trigger"

# ---------------------------------------------------------------------------
# Logical type sets
# ---------------------------------------------------------------------------
LETTER_BLOCK_TYPES = frozenset({T_DASH_STOP, T_JUMP_BLOCK, T_WAVE_BLOCK,
                                T_BONK_BLOCK})
DECORATION_TYPES = frozenset({T_DECO_CRYSTAL, T_DECO_PILLAR, T_DECO_GLOW})
TRIGGER_TYPES = frozenset({T_CAMERA_TRIGGER, T_BG_TRIGGER, T_MOVE_TRIGGER,
                           T_COLOR_TRIGGER, T_PULSE_TRIGGER, T_ROTATE_TRIGGER,
                           T_TIME_WARP, T_FOLLOW_TRIGGER, T_BLACKOUT_TRIGGER,
                           T_SPAWN_TRIGGER, T_TOGGLE_TRIGGER, T_STOP_TRIGGER,
                           T_SEQUENCE_TRIGGER, T_SCALE_TRIGGER,
                           T_ALPHA_TRIGGER, T_ZOOM_TRIGGER,
                           T_CAM_OFFSET_TRIGGER, T_CAM_ROTATE_TRIGGER,
                           T_CAM_EDGE_TRIGGER, T_CAM_GUIDE_TRIGGER,
                           T_GRAYSCALE_TRIGGER, T_SEPIA_TRIGGER,
                           T_INVERT_TRIGGER, T_HUE_TRIGGER,
                           T_PIXELATE_TRIGGER,
                           T_COUNT_TRIGGER, T_INSTANT_COUNT_TRIGGER,
                           T_ITEM_EDIT_TRIGGER, T_ITEM_COMP_TRIGGER,
                           T_ITEM_PERS_TRIGGER, T_TIME_TRIGGER,
                           T_TIME_EVENT_TRIGGER, T_KEYFRAME_TRIGGER})
# Checkpoint 7: item/counter-family triggers that fire a target group by
# reading the item-value store, rather than animating an object.
ITEM_LOGIC_TRIGGER_TYPES = frozenset({
    T_COUNT_TRIGGER, T_INSTANT_COUNT_TRIGGER, T_ITEM_EDIT_TRIGGER,
    T_ITEM_COMP_TRIGGER, T_ITEM_PERS_TRIGGER, T_TIME_TRIGGER,
    T_TIME_EVENT_TRIGGER,
})
# Triggers whose effect is "run other triggers" (or, for the item-logic
# family, "read/write the item store and maybe fire a group") rather than
# animating an object directly -- Toggle/Stop/item-logic triggers always
# execute even while their own group is disabled (so a disabled chain can
# be re-enabled, and a Count trigger deciding whether to re-enable a
# chain must itself remain live), and their own touch is never gated by
# _trigger_active.
CONTROL_TRIGGER_TYPES = frozenset({T_SPAWN_TRIGGER, T_TOGGLE_TRIGGER,
                                   T_STOP_TRIGGER, T_SEQUENCE_TRIGGER}
                                  ) | ITEM_LOGIC_TRIGGER_TYPES
COLLECTIBLE_ITEM_TYPES = frozenset({T_ITEM_PICKUP})
# Checkpoint 8: data-only keyframe markers, indexed by animation id
# (Player._by_animation) rather than executed as a trigger themselves.
KEYFRAME_TYPES = frozenset({T_KEYFRAME})
# Checkpoint 6: screen-effect triggers, for render code that needs to
# iterate "every effect type" without listing them by name.
SCREEN_EFFECT_TRIGGER_TYPES = frozenset({
    T_GRAYSCALE_TRIGGER, T_SEPIA_TRIGGER, T_INVERT_TRIGGER, T_HUE_TRIGGER,
    T_PIXELATE_TRIGGER,
})
SOLID_TYPES = frozenset({T_BLOCK, T_SLAB})
# Slopes have diagonal collision handled by a dedicated pass.
SLOPE_TYPES = frozenset({T_SLOPE})
HAZARD_TYPES = frozenset({T_SPIKE, T_HALF_SPIKE, T_SAW})
ORB_TYPES = frozenset({T_ORB, T_PINK_ORB, T_RED_ORB, T_BLUE_ORB, T_GREEN_ORB,
                       T_BLACK_ORB, T_DASH_ORB, T_DASH_ORB_GRAV, T_SPIDER_ORB,
                       T_TELEPORT_ORB})
DASH_ORB_TYPES = frozenset({T_DASH_ORB, T_DASH_ORB_GRAV})
PAD_TYPES = frozenset({T_PAD, T_PINK_PAD, T_RED_PAD, T_BLUE_PAD, T_SPIDER_PAD})
# Group-linked teleport pair types: the orb requires a click, the portal
# fires automatically on touch. Both share the same group/dest pairing
# machinery (editor Link tool, group-id allocation, level normalization).
TELEPORT_LINK_TYPES = frozenset({T_TELEPORT_ORB, T_TELEPORT_PORTAL})
COLLECTIBLE_TYPES = frozenset({T_COIN})
EDITOR_ONLY_TYPES = frozenset({T_JUMP_PREDICTOR, T_BOT_CHECKPOINT})

# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------
MODE_CUBE = "cube"
MODE_SHIP = "ship"
MODE_BALL = "ball"
MODE_WAVE = "wave"
MODE_UFO = "ufo"
MODE_SPIDER = "spider"
MODE_SWING = "swing"
MODE_ROBOT = "robot"

MODE_FROM_TYPE = {
    T_MODE_CUBE: MODE_CUBE,
    T_MODE_SHIP: MODE_SHIP,
    T_MODE_BALL: MODE_BALL,
    T_MODE_WAVE: MODE_WAVE,
    T_MODE_UFO: MODE_UFO,
    T_MODE_SPIDER: MODE_SPIDER,
    T_MODE_SWING: MODE_SWING,
    T_MODE_ROBOT: MODE_ROBOT,
}
MODE_PORTAL_TYPES = frozenset(MODE_FROM_TYPE.keys())
ALL_MODES = (MODE_CUBE, MODE_SHIP, MODE_BALL, MODE_WAVE, MODE_UFO,
             MODE_SPIDER, MODE_SWING, MODE_ROBOT)

# Bible §2.6/§1.3's "Ticks Held" column: 1 tick for Cube/Ball/Robot/Spider
# (one-shot actions — jump, flip, hold-launch, teleport), 2 ticks for
# Ship/UFO/Wave/Swing (continuous hold-while-held actions). Retained here
# as sourced documentation only — it is NOT wired in as an artificial
# action-delay gate. Reading bible §2.1 closely, "Ticks Held" describes
# an *internal* tick-ordering detail (why a buffered second jump lands
# fractionally higher than a fresh one, because gravity is applied
# before vs. after the velocity is set within the same tick) rather than
# a player-visible hold-before-acting delay; Ship/UFO/Wave/Swing already
# act every tick they're held in this engine, which is the correct
# player-facing behavior, so adding a literal 1/2-tick wait here would
# introduce input lag real GD does not have. Left as a reference table
# for any future, more faithful modeling of the tick-ordering quirk
# itself (not attempted in this pass — see docs/development/AUDIT.md follow-up).
TICKS_HELD = {
    MODE_CUBE: 1, MODE_BALL: 1, MODE_ROBOT: 1, MODE_SPIDER: 1,
    MODE_SHIP: 2, MODE_UFO: 2, MODE_WAVE: 2, MODE_SWING: 2,
}

# ---------------------------------------------------------------------------
# Hitboxes (physics bible §3.2)
# ---------------------------------------------------------------------------
# The OUTER rect (full sprite size, rotated with the player) already stands
# in for the bible's "red" hazard hitbox — it's what triggers hazards/orbs/
# pads/triggers (see player.core.Player.rect / _outer_obb_corners). The
# bible's per-mode INNER "blue" solid hitbox is documented as a fraction of
# that red box (units, §3.2 table), not an absolute size, so it translates
# cleanly to a per-(mode, mini) fraction of the existing outer box instead of
# a flat 0.50 for every mode:
#   box modes (Cube/Ship/Ball/UFO/Robot/Swing): normal 9/30, mini 10/18
#   Wave:                                        normal 3/10, mini 3/6
#   Spider:                                       normal 9/27.5, mini 10/16.5
#     (mini-red 16.5 is the one figure GD Docs itself flags uncertain)
# Note the counter-intuitive direction in every row: mini SHRINKS the red
# (hazard) box but GROWS the blue (solid) box relative to it, so minis are
# safer around hazards but slightly worse squeezing through solid gaps —
# exactly the effect this fraction table now reproduces.
HITBOX_SOLID_FRACTION = {
    # mode: (normal_fraction, mini_fraction)
    MODE_CUBE: (9 / 30, 10 / 18),
    MODE_SHIP: (9 / 30, 10 / 18),
    MODE_BALL: (9 / 30, 10 / 18),
    MODE_UFO: (9 / 30, 10 / 18),
    MODE_ROBOT: (9 / 30, 10 / 18),
    MODE_SWING: (9 / 30, 10 / 18),
    MODE_WAVE: (3 / 10, 3 / 6),
    MODE_SPIDER: (9 / 27.5, 10 / 16.5),
}
# Fallback for any mode not in the table above (there shouldn't be one).
SOLID_HITBOX_FRACTION = 9 / 30

# Speed portal px/tick values. Bible §1.8 (community-measured, via
# move-trigger testing / official Fandom wiki): the portal labels are
# misleading multiples of 1x baseline (BASE_MOVE_SPEED) —
# 0.5x=~0.807x, 1x=1.0x, 2x=~1.243x, 3x=~1.502x, 4x=~1.849x. Ratios are
# more reliable than the bible's absolute blocks/sec figures (which carry
# measurement error across sources), so BASE_MOVE_SPEED anchors 1x and
# every other tier is BASE_MOVE_SPEED * ratio.
SPEED_VALUES = {
    T_SPEED_SLOW: BASE_MOVE_SPEED * 0.807,
    T_SPEED_NORMAL: BASE_MOVE_SPEED * 1.0,
    T_SPEED_FAST: BASE_MOVE_SPEED * 1.243,
    T_SPEED_FASTER: BASE_MOVE_SPEED * 1.502,
    T_SPEED_FASTEST: BASE_MOVE_SPEED * 1.849,
}
# Unit-space twin of SPEED_VALUES (see the _UT block above).
SPEED_VALUES_UT = {k: px_to_units(v) for k, v in SPEED_VALUES.items()}

# ---------------------------------------------------------------------------
# Move trigger curve
# ---------------------------------------------------------------------------
DEFAULT_MOVE_CURVE = [[0.0, 1.0], [1.0, 1.0]]
MOVE_CURVE_SPEED_MAX = 3.0

# ---------------------------------------------------------------------------
# Player cosmetics
# ---------------------------------------------------------------------------
PLAYER_COLORS = [
    (90, 255, 120),   # Green (default)
    (255, 100, 100),  # Red
    (100, 180, 255),  # Blue
    (255, 220, 60),   # Yellow
    (255, 120, 220),  # Pink
    (180, 120, 255),  # Purple
    (255, 165, 60),   # Orange
    (120, 255, 255),  # Cyan
]
PLAYER_ICONS = ["Classic", "Star", "Triangle", "Diamond", "Circle", "Plus",
                "Heart", "Bolt"]

# ---------------------------------------------------------------------------
# Difficulty
# ---------------------------------------------------------------------------
DIFFICULTIES = [
    "Auto", "Easy", "Normal", "Hard", "Harder", "Insane",
    "Easy Demon", "Medium Demon", "Hard Demon",
    "Insane Demon", "Extreme Demon",
]
LEGACY_DEMON_TARGET = "Hard Demon"
ADMIN_USERNAME = "TopRob"

DIFFICULTY_COLORS = {
    "Auto":           (180, 255, 180),
    "Easy":           (100, 230, 255),
    "Normal":         (100, 255, 120),
    "Hard":           (255, 220, 80),
    "Harder":         (255, 150, 60),
    "Insane":         (255, 80, 80),
    "Easy Demon":     (200, 120, 255),
    "Medium Demon":   (230, 80, 230),
    "Hard Demon":     (255, 40, 220),
    "Insane Demon":   (255, 30, 140),
    "Extreme Demon":  (255, 0, 60),
    "Demon":          (255, 40, 220),
}

BG_PRESETS = [
    ((14, 8, 42), (42, 14, 72)),
    ((6, 16, 60), (18, 48, 130)),
    ((60, 10, 20), (120, 30, 50)),
    ((8, 42, 22), (26, 90, 48)),
    ((60, 28, 8), (130, 70, 18)),
    ((54, 12, 56), (120, 36, 110)),
    ((4, 4, 10), (22, 22, 36)),
    ((40, 40, 60), (120, 120, 150)),
]

# ---------------------------------------------------------------------------
# Colours
# ---------------------------------------------------------------------------
C_BG_TOP = (14, 8, 42)
C_BG_BOT = (42, 14, 72)
C_GROUND = (8, 30, 90)
C_GROUND_L = (0, 80, 180)
C_GROUND_DARK = (4, 14, 48)
C_GRID = (34, 28, 64)
C_WHITE = (255, 255, 255)
C_GRAY = (140, 140, 155)
C_DARK = (32, 30, 56)
C_PLAYER = (90, 255, 120)
C_BLOCK = (28, 120, 240)
C_BLOCK_H = (70, 175, 255)
C_BLOCK_D = (6, 62, 160)
C_SLAB = (50, 140, 220)
C_SPIKE = (255, 60, 70)
C_SAW = (255, 80, 80)
C_ORB = (255, 230, 60)
C_PINK_ORB = (255, 150, 210)
C_RED_ORB = (255, 70, 70)
C_BLUE_ORB = (80, 160, 255)
C_GREEN_ORB = (110, 255, 130)
C_BLACK_ORB = (45, 45, 55)
C_DASH_ORB = (110, 255, 110)
C_DASH_ORB_GRAV = (255, 80, 220)
C_SPIDER_ORB = (190, 120, 255)
C_TELEPORT_ORB = (120, 240, 255)
C_TELEPORT_PORTAL = (255, 165, 60)
C_PAD = (255, 220, 40)
C_PINK_PAD = (255, 140, 210)
C_RED_PAD = (255, 70, 70)
C_BLUE_PAD = (90, 170, 255)
C_SPIDER_PAD = (190, 120, 255)
C_GPORTAL_UP = (80, 160, 255)
C_GPORTAL_DOWN = (255, 215, 70)
C_END = (90, 255, 115)
C_START = (255, 255, 255)
C_COIN = (255, 215, 0)
C_CHECKPOINT = (120, 255, 180)
C_BTN = (40, 75, 170)
C_BTN_H = (70, 115, 220)
C_DANGER = (200, 55, 55)
C_PUBLISH = (220, 160, 40)
C_SUCCESS = (60, 180, 90)
C_MODE_CUBE = (100, 225, 255)
C_MODE_SHIP = (255, 130, 80)
C_MODE_BALL = (190, 130, 255)
C_MODE_WAVE = (255, 90, 180)
C_MODE_UFO = (255, 210, 70)
C_MODE_SPIDER = (160, 80, 255)
C_MODE_SWING = (255, 215, 130)
C_MODE_ROBOT = (255, 170, 60)
C_MODE_MINI = (120, 255, 180)
C_MODE_BIG = (255, 180, 120)
C_MODE_DUAL = (255, 110, 160)
C_MODE_SOLO = (160, 230, 255)
C_SPEED_SLOW = (110, 255, 170)
C_SPEED_NORMAL = (110, 190, 255)
C_SPEED_FAST = (255, 225, 100)
C_SPEED_FASTER = (255, 120, 120)
C_SPEED_FASTEST = (255, 60, 200)
C_DECO_CRYSTAL = (180, 220, 255)
C_DECO_PILLAR = (80, 55, 130)
C_DECO_GLOW = (255, 245, 200)
C_CAM_TRIGGER = (255, 225, 80)
C_BG_TRIGGER = (80, 245, 200)
C_MOVE_TRIGGER = (255, 160, 80)
C_COLOR_TRIGGER = (255, 200, 140)
C_PULSE_TRIGGER = (255, 90, 200)
C_ROTATE_TRIGGER = (180, 255, 100)
C_FOLLOW_TRIGGER = (120, 220, 200)
C_BLACKOUT_TRIGGER = (40, 40, 45)
C_TIME_WARP = (200, 140, 255)
C_JUMP_PREDICTOR = (255, 235, 120)
C_BOT_CHECKPOINT = (120, 230, 255)
C_DASH_STOP = (255, 255, 255)
C_JUMP_BLOCK = (255, 210, 60)
C_WAVE_BLOCK = (90, 190, 255)
C_BONK_BLOCK = (255, 140, 90)
C_ZOOM_TRIGGER = (255, 190, 60)
C_CAM_OFFSET_TRIGGER = (255, 205, 90)
C_CAM_ROTATE_TRIGGER = (255, 170, 40)
C_CAM_EDGE_TRIGGER = (230, 160, 255)
C_CAM_GUIDE_TRIGGER = (160, 200, 255)
C_GRAYSCALE_TRIGGER = (150, 150, 150)
C_SEPIA_TRIGGER = (170, 120, 80)
C_INVERT_TRIGGER = (240, 240, 240)
C_HUE_TRIGGER = (200, 80, 220)
C_PIXELATE_TRIGGER = (100, 220, 200)
C_ITEM_PICKUP = (255, 235, 80)
C_COUNT_TRIGGER = (140, 255, 210)
C_ITEM_EDIT_TRIGGER = (255, 170, 210)
C_ITEM_COMP_TRIGGER = (170, 210, 255)
C_TIME_TRIGGER = (210, 255, 140)
C_ITEM_COUNTER = (255, 255, 255)
C_KEYFRAME = (255, 190, 255)
C_KEYFRAME_TRIGGER = (220, 150, 255)

# Mode colours keyed by mode string (HUD, state panel).
MODE_COLORS = {
    MODE_CUBE: C_MODE_CUBE, MODE_SHIP: C_MODE_SHIP, MODE_BALL: C_MODE_BALL,
    MODE_WAVE: C_MODE_WAVE, MODE_UFO: C_MODE_UFO, MODE_SPIDER: C_MODE_SPIDER,
    MODE_SWING: C_MODE_SWING, MODE_ROBOT: C_MODE_ROBOT,
}


# ---------------------------------------------------------------------------
# Backwards-compatible access to the registry-derived tables.  Importing
# them from ``constants`` still works; they are resolved lazily so
# ``objects`` can import ``constants`` without a cycle.
# ---------------------------------------------------------------------------
_REGISTRY_EXPORTS = ("TYPE_NAMES", "TYPE_TIPS", "TYPE_COLS",
                     "PALETTE_CATEGORIES", "ALL_TYPES")


def __getattr__(name):
    if name in _REGISTRY_EXPORTS:
        from . import objects as _objects
        return getattr(_objects, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
