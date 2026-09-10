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
# Real GD units per editor block (verified live 2026-09-07 against the
# Move Trigger's "Small Step" behavior: Small Step only changes the
# trigger UI's input granularity, not the underlying scale, which is
# always 30). This is the canonical world unit.
# Every physics/collision/trigger/bot length is stated in these units.
UNITS_PER_BLOCK = 30.0

# ---------------------------------------------------------------------------
# Camera framing.
#
# GD is a cocos2d-x game whose design resolution is 480 x 320 applied with
# ``ResolutionPolicy::FIXED_HEIGHT``, and its camera maps screen size to
# world size 1:1 at zoom 1.  So 1 GD unit == 1 point, the VERTICAL field
# of view is locked at 320 units (10.67 blocks) regardless of window
# size, and the horizontal extent falls out of the display aspect ratio.
# Corroborated independently by NamuWiki ("if the camera zoom is not set
# separately, the height of the floor and ceiling is fixed to 10 blocks").
# See docs/PHYSICS.md, "Camera framing".
CAMERA_FOV_UNITS = 320.0
# Pixels per block on screen at zoom 1 — a PURE RENDER constant, derived
# from the FOV above and this window's height.  Nothing in the physics,
# collision, trigger or bot path may read it (or PX_PER_UNIT below, or
# anything derived from either): those paths state every length in GD
# units directly, so the render scale can move without retuning them.
#
# Rounded to a whole pixel: sprites are baked at this size and the PNG
# cache is keyed on it, and pygame surfaces are integer-sized, so a
# fractional CELL would put an int() at every render call site and
# reintroduce exactly the px/unit rounding this file just removed.  The
# residual is 700 * 30 / 66 = 318.2 units of vertical FOV rather than
# 320 — 0.6% tighter than the sourced figure.
CELL = int(round(HEIGHT * UNITS_PER_BLOCK / CAMERA_FOV_UNITS))
# Canonical physics tick rate. Physics bible Part 0 / §2.7: real GD
# standardized its physics loop to 240 TPS in Update 2.2 (Dec 19, 2023);
# this engine now matches. Every "per tick" constant below is expressed
# in terms of PHYSICS_TPS (see GRAVITY_UT / BASE_MOVE_SPEED_UT), so
# most of them rescale automatically when this changes — the ones that
# don't (BASE_MOVE_SPEED, INPUT_BUFFER_TICKS, and any literal frame count
# elsewhere) are called out at their own definition. The renderer runs at
# any FPS and interpolates between ticks (see play.PlaySession).
FPS = 240
PHYSICS_TPS = 240

# Two-hitbox model: the OUTER rect (full sprite size, rotated with the
# player) triggers hazards / orbs / pads / triggers; the INNER rect (a
# per-gamemode fraction of the size, centred, axis-aligned) triggers block
# death. The fraction now varies by (mode, mini) per the physics bible's
# §3.2 hitbox table — see HITBOX_SOLID_FRACTION / SOLID_HITBOX_FRACTION
# further down (after the mode constants they're keyed on).

# ---------------------------------------------------------------------------
# The render boundary.
#
# PX_PER_UNIT and px_to_units are the ONLY px<->unit conversion in the
# codebase (``geometry.py`` used to carry a second, independent copy).
# They belong to rendering and to the two authoring surfaces that hand
# the engine a genuine screen/world PIXEL — the editor's px-authored
# jump-predictor nudge fields and its "test from cursor" spawn x — and
# nothing else may use them.  A physics length routed through here would
# silently change meaning whenever CELL moved.
# ---------------------------------------------------------------------------
PX_PER_UNIT = CELL / UNITS_PER_BLOCK
PX_TO_UNIT_RATIO = 1.0 / PX_PER_UNIT


def px_to_units(v_px):
    """A screen/world PIXEL length -> GD units at the current render scale."""
    return v_px * PX_TO_UNIT_RATIO


# ---------------------------------------------------------------------------
# Player tunables (physics)
#
# Calibration: docs/PHYSICS.md; archived research under docs/reference/.
# The reference states gamemode speeds in "Vels" (1 Vel = 60 GD units/
# second) and distances in GD units (1 editor block = 30 units).  Every
# tunable below is therefore derived in GD units per tick FIRST, straight
# from the reference's own numbers; the ``*_PX``-scale twins are the
# derived ones (``value_ut * PX_PER_UNIT``), for render/HUD code only.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Player body size.
#
# Defined in GD units FIRST (the px twins are derived), because the size is
# a physics quantity, not a render one: it decides what "a 2-block gap"
# means, how tall a jump reads against the blocks it clears, and how many
# body-lengths of world scroll past per second.
#
# Bible Sec 3.2: every box gamemode (Cube/Ship/Ball/UFO/Robot/Swing) has a
# main "red" hitbox of exactly 30 units at normal size and 18 units in mini
# — i.e. the player IS one full block, and mini is 0.6 of one.
#
# These were 44 px / 24 px (= 26.4 / 14.4 units, 0.88 / 0.48 blocks): px
# literals inherited from the pre-GD-units prototype that the units cutover
# converted by ratio instead of re-deriving from the bible. That left the
# body 12% small against a world grid that IS in real GD units, so every
# jump read ~12% higher and the world scrolled ~14% faster *relative to the
# player* than real GD — and HITBOX_SOLID_FRACTION (whose entries are
# literally bible_blue/bible_red, e.g. 9/30) silently produced a 7.92-unit
# solid box instead of the bible's 9.
# ---------------------------------------------------------------------------
PLAYER_SIZE_UNITS = UNITS_PER_BLOCK          # 30 units = 1 block
MINI_PLAYER_SIZE_UNITS = UNITS_PER_BLOCK * 0.6   # 18 units = 0.6 blocks
PLAYER_SIZE = int(round(PLAYER_SIZE_UNITS * PX_PER_UNIT))
MINI_PLAYER_SIZE = int(round(MINI_PLAYER_SIZE_UNITS * PX_PER_UNIT))

# ---------------------------------------------------------------------------
# Canonical GD-unit constants (units/second, units/second^2).
#
# The bible expresses velocities in "Vels" (1 Vel = 60 GD units/second —
# the legacy 60 fps-per-frame convention) and accelerations as a Vel-like
# factor times 60^2. VEL_UNIT_PER_S below IS that "1 Vel", named for what
# it actually is instead of leaving it as an inline literal. These _UPS /
# _UPS2 constants are the ones player/collision/bot code should migrate
# to; the *_UT (units/tick) constants below are derived straight from
# them, and the *_PX-scale names are in turn derived from the *_UT ones
# for render/HUD code only.
# ---------------------------------------------------------------------------
VEL_UNIT_PER_S = 60.0  # 1 "Vel" (bible units)

def _vel_ups(vels):
    """Bible "Vels" -> GD units/second."""
    return vels * VEL_UNIT_PER_S


def _accel_ups2(factor):
    """Bible acceleration factor -> GD units/second^2."""
    return factor * VEL_UNIT_PER_S ** 2


def _ups_to_units_per_tick(v_ups):
    """GD units/second -> GD units/tick. No render scale involved."""
    return v_ups / PHYSICS_TPS


def _ups2_to_units_per_tick2(a_ups2):
    """GD units/second^2 -> GD units/tick^2. No render scale involved."""
    return a_ups2 / PHYSICS_TPS ** 2


def _ut_to_px(v_ut):
    """A GD-unit quantity -> its px twin, for render/HUD/menu code only."""
    return v_ut * PX_PER_UNIT


BASE_MOVE_SPEED_UPS = _vel_ups(5.193)
BASE_MOVE_SPEED_UT = _ups_to_units_per_tick(BASE_MOVE_SPEED_UPS)
BASE_MOVE_SPEED = _ut_to_px(BASE_MOVE_SPEED_UT)

# 0.216 velocity units per 240 Hz tick (reference §1.3). The old
# 72 blocks/s² estimate contradicted that and produced a 3.5-block jump.
GRAVITY_UPS2 = _accel_ups2(0.864)
GRAVITY_UT = _ups2_to_units_per_tick2(GRAVITY_UPS2)
GRAVITY = _ut_to_px(GRAVITY_UT)

# Flying modes use 0.9582 base acceleration in updateJump's decompilation.
# Ship's baseline ascent factor is 0.4; release depends on momentum.
SHIP_GRAVITY_UPS2 = _accel_ups2(0.9582 * 0.4)
SHIP_GRAVITY_UT = _ups2_to_units_per_tick2(SHIP_GRAVITY_UPS2)
SHIP_GRAVITY = _ut_to_px(SHIP_GRAVITY_UT)
SHIP_THRUST_UPS2 = SHIP_GRAVITY_UPS2 * 2.0
SHIP_THRUST_UT = SHIP_GRAVITY_UT * 2.0
SHIP_THRUST = SHIP_GRAVITY * 2.0

# Cube jump velocity, 1x speed portal: bible §1.4 table, 11.18G.
JUMP_FORCE_UPS = -_vel_ups(11.18)
JUMP_FORCE_UT = _ups_to_units_per_tick(JUMP_FORCE_UPS)
JUMP_FORCE = _ut_to_px(JUMP_FORCE_UT)
# Pads: no distinct bible figure (the bible documents gamemode click
# velocities, not a separate pad table) — ratio to JUMP_FORCE preserved
# from the pre-retune tuning (pads hit ~12% harder than the yellow orb).
PAD_FORCE_UPS = JUMP_FORCE_UPS * 1.125
PAD_FORCE_UT = JUMP_FORCE_UT * 1.125
PAD_FORCE = JUMP_FORCE * 1.125
# Ball click velocity, 1x speed: bible §1.4 / §1.3, "3.354G (3/10 of cube)".
BALL_FLIP_FORCE_UPS = _vel_ups(3.354)
BALL_FLIP_FORCE_UT = _ups_to_units_per_tick(BALL_FLIP_FORCE_UPS)
BALL_FLIP_FORCE = _ut_to_px(BALL_FLIP_FORCE_UT)
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
UFO_JUMP_FORCE_UT = _ups_to_units_per_tick(UFO_JUMP_FORCE_UPS)
UFO_JUMP_FORCE = _ut_to_px(UFO_JUMP_FORCE_UT)
SPIDER_TELEPORT_RANGE = 6  # cells (legacy; teleports are now unbounded)
# Robot: bible §1.4, "Hold velocity 5.59G (1/2 of cube jump)... gravity
# disabled while held." Repurposed from a per-tick thrust subtracted
# against gravity into the fixed hold velocity itself (gravity is now
# skipped entirely while the hold is active — see core.py).
ROBOT_THRUST_UPS = _vel_ups(5.59)
ROBOT_THRUST_UT = _ups_to_units_per_tick(ROBOT_THRUST_UPS)
ROBOT_THRUST = _ut_to_px(ROBOT_THRUST_UT)
# The decompiled timer advances by dt/10 with dt in 60 Hz units:
# its 1.5 limit represents 15/60 seconds, not 1.5 seconds.
ROBOT_FLIGHT_SECONDS = 0.25

# Per-mode max-fall / max-rise magnitudes (bible §1.3 table). Modes not
# listed here (Wave has no gravity; Spider's fall is defined by its
# instant teleport, not acceleration, per §1.4) don't use a fall clamp.
MAX_FALL_BOX_UPS = _vel_ups(15.0)           # Cube / Ball / Robot / Spider: -15G
MAX_FALL_BOX_UT = _ups_to_units_per_tick(MAX_FALL_BOX_UPS)
MAX_FALL_BOX = _ut_to_px(MAX_FALL_BOX_UT)
MAX_FALL_UFO_UPS = _vel_ups(6.4)            # UFO: -6.4G
MAX_FALL_UFO_UT = _ups_to_units_per_tick(MAX_FALL_UFO_UPS)
MAX_FALL_UFO = _ut_to_px(MAX_FALL_UFO_UT)
MAX_RISE_UFO_UPS = _vel_ups(8.0)
MAX_RISE_UFO_UT = _ups_to_units_per_tick(MAX_RISE_UFO_UPS)
MAX_RISE_UFO = _ut_to_px(MAX_RISE_UFO_UT)
MAX_FALL_SWING_UPS = _vel_ups(8.0)          # Swing: -8G
MAX_FALL_SWING_UT = _ups_to_units_per_tick(MAX_FALL_SWING_UPS)
MAX_FALL_SWING = _ut_to_px(MAX_FALL_SWING_UT)
SHIP_MAX_RISE_UPS = _vel_ups(8.0)           # Ship (holding): 8G
SHIP_MAX_RISE_UT = _ups_to_units_per_tick(SHIP_MAX_RISE_UPS)
SHIP_MAX_RISE = _ut_to_px(SHIP_MAX_RISE_UT)
SHIP_MAX_FALL_UPS = _vel_ups(6.4)           # Ship (released): -6.4G
SHIP_MAX_FALL_UT = _ups_to_units_per_tick(SHIP_MAX_FALL_UPS)
SHIP_MAX_FALL = _ut_to_px(SHIP_MAX_FALL_UT)
# Swing click: bible §1.4, "multiplies the y-velocity by 0.8, then
# toggles the gravity" — applied in core.py's MODE_SWING branch.
SWING_VY_MULTIPLIER = 0.8

# ---------------------------------------------------------------------------
# Collision / interaction margins, in GD units.
#
# Every one of these used to be spelled ``px_to_units(<pixel literal>)``
# at the old CELL=50 render scale, which meant a physics tolerance
# silently retuned itself whenever the camera zoom moved.  None of them
# has a reference figure — they are engine-internal tolerances — so each
# is restated here at exactly the GD-unit value that expression produced
# (px * 30/50), and is now independent of CELL.
# ---------------------------------------------------------------------------
# Maximum motion covered by a single inner collision substep (was 1 px).
COLLISION_SUBSTEP_UNITS = 0.6
# Outward slack on the body box when testing orb/pad/trigger touch, so a
# contact that lands exactly on an edge still registers (was 3 px).
TOUCH_PAD_UNITS = 1.8
# How far above/below a surface still counts as standing on it, for the
# ground-adjacency test (was 1 px).
GROUND_CONTACT_MARGIN_UNITS = 0.6
# Slack on the one-block snap band a slope may pull the body through
# (was 4 px).
SLOPE_SNAP_MARGIN_UNITS = 2.4
# Floor on the inner ("solid") hitbox so a tiny body can never degenerate
# to a zero-area box (was 2 px).
MIN_INNER_HITBOX_UNITS = 1.2
# Spacing of the sampled beam a teleport draws between its two poses
# (was 8 px).
TELEPORT_BEAM_STEP_UNITS = 4.8

# ---------------------------------------------------------------------------
# Play-field vs camera height — two different things that used to share
# one CELL-derived ``HEIGHT_UNITS``.
#
#   * CAMERA_HEIGHT_UNITS is how much world the screen SHOWS. It is a
#     render quantity and therefore moves with CELL: it is the FOV.
#   * PLAYFIELD_HEIGHT_UNITS is a gameplay bound — the dual mirror
#     reflects about its midpoint and the bots' void floor is a multiple
#     of it. Freezing it at 14 blocks keeps every existing level and
#     saved bot run playing identically now that the FOV has changed.
# ---------------------------------------------------------------------------
CAMERA_HEIGHT_UNITS = HEIGHT * UNITS_PER_BLOCK / CELL
PLAYFIELD_HEIGHT_UNITS = 14.0 * UNITS_PER_BLOCK
# The world row the drawn ground band starts on, and where the player's
# feet rest when a level places no Start Pos (see
# ``Player._default_ground_y``). This was the px literal 550, which only
# meant "row 11" at the old CELL=50 scale.
GROUND_Y_UNITS = 11.0 * UNITS_PER_BLOCK
# Default camera top edge, when no camera trigger is driving the view.
#
# It cannot be 0 any more. A camera pinned to world row 0 was fine while
# the view was 14 rows tall — the ground plane at row 11 landed 11/14 of
# the way down the screen. With the FOV cut to GD's 320 units the same
# pin would crop the bottom of the world away, taking the ground and the
# play lane with it. So the default view is defined by where it puts the
# GROUND, keeping this engine's long-standing 11-above / 3-below split
# of the screen, and the camera's top edge falls out of that.
#
# At the old CELL=50 this expression is exactly 0, i.e. it generalises
# the previous behaviour rather than replacing it.
GROUND_SCREEN_FRACTION = 11.0 / 14.0
CAMERA_BASE_Y_UNITS = (GROUND_Y_UNITS
                       - GROUND_SCREEN_FRACTION * CAMERA_HEIGHT_UNITS)
# World-px twins, for the camera and for graphics.draw_bg's parallax
# layout (both work in world px and subtract cam_y).
GROUND_Y = round(GROUND_Y_UNITS * PX_PER_UNIT)
CAMERA_BASE_Y_PX = CAMERA_BASE_Y_UNITS * PX_PER_UNIT
# "Fell off the screen" band, measured from the camera's top edge. Stated
# as absolute unit distances (previously PLAYFIELD + 300 px below and
# 500 px above) so shrinking the FOV cannot make a level unwinnable.
FALL_OFF_BELOW_CAM_UNITS = PLAYFIELD_HEIGHT_UNITS + 180.0
FALL_OFF_ABOVE_CAM_UNITS = 300.0

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
# the player than this are dropped so the list doesn't grow without bound
# over a long run. 72 blocks — several screens' worth at any zoom.
TRAIL_MAX_DISTANCE_UNITS = 72.0 * UNITS_PER_BLOCK

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
# v9: triggers default to line-activated only, with an opt-in "Touch
# Activated" toggle replacing the old always-touch default (see
# levels._migrate_objects's version-gated shim for pre-v9 levels).
LEVEL_FORMAT_VERSION = 9

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
T_REPEAT_TRIGGER = "repeat_trigger"
T_SCALE_TRIGGER = "scale_trigger"
T_ALPHA_TRIGGER = "alpha_trigger"
# Engine-original (no real-GD id, like Repeat Trigger above): every
# Interval seconds, for Count cycles, randomly permutes the target
# group's positions among themselves -- optionally tweened (Smooth) like
# a Move Trigger instead of snapping.
T_SWAP_TRIGGER = "swap_trigger"
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
# shader stage (per-pixel color remaps + block resampling).
T_GRAYSCALE_TRIGGER = "grayscale_trigger"
T_SEPIA_TRIGGER = "sepia_trigger"
T_INVERT_TRIGGER = "invert_trigger"
T_HUE_TRIGGER = "hue_trigger"
T_PIXELATE_TRIGGER = "pixelate_trigger"
# Checkpoint 4 (deep-research-report.md, "Shader and visual effects"):
# the rest of the 2.2 shader family that a numpy/surfarray pipeline can
# still do honestly -- channel rolls, scaled-blit averaging, a frame ring
# buffer, and a radial index gather. Every one of these runs through the
# SAME active_effect_anims -> build_screen_effects -> apply_screen_effects
# path the five above already use; there is no second pipeline.
#
# Still deliberately NOT implemented, for the reason the report gives
# itself (they need true per-pixel GPU-shader displacement/noise that
# pygame cannot do at frame rate): Gradient 2903, Shock Wave 2905,
# Shock Line 2907, Glitch 2909, Chromatic Glitch 2911, Lens Circle 2913.
# See docs/development/AUDIT.md.
T_SHADER_TRIGGER = "shader_trigger"
T_CHROMATIC_TRIGGER = "chromatic_trigger"
T_RADIAL_BLUR_TRIGGER = "radial_blur_trigger"
T_MOTION_BLUR_TRIGGER = "motion_blur_trigger"
T_BULGE_TRIGGER = "bulge_trigger"
T_PINCH_TRIGGER = "pinch_trigger"
T_SPLIT_SCREEN_TRIGGER = "split_screen_trigger"

# Cost ceilings for the Checkpoint 4 shader effects. These are not GD
# values (the report cites no ranges) -- they are engine budget caps,
# because each unit of them costs a whole extra full-screen operation
# every rendered frame while the effect is live:
#   * one extra smoothscale + array3d per radial-blur sample,
#   * one retained full-screen frame buffer per motion-blur frame,
#   * one np.roll per chromatic channel offset (cheap, but the offset is
#     capped so a mis-authored value cannot roll the frame off itself).
RADIAL_BLUR_MAX_SAMPLES = 8
MOTION_BLUR_MAX_FRAMES = 6
CHROMATIC_MAX_OFFSET_PX = 64
# How far out the outermost radial-blur sample is scaled at Strength 1
# (6% of the frame). This is a fidelity/reach tradeoff against the
# sample cap above: the samples are evenly spaced, so a wider reach with
# the same handful of samples separates them into individually visible
# ghost copies instead of a smear. 6% keeps 4-8 samples reading as a
# blur; wider also starts pulling off-frame edge pixels inward.
RADIAL_BLUR_MAX_ZOOM = 0.06

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

# Checkpoint 2 of the deep-research-report.md refactor ("Area and keyframe
# system", real GD object ids 3006-3015 + 3024): an Area trigger starts a
# *continuous* effect (identified by its own EffectID) that transforms
# every member of a target group by how close it sits to a center group,
# rather than tweening a group once like Move/Rotate/Scale do. The Edit
# Area variants patch a live effect's parameters mid-flight (the report is
# explicit that they modify existing state and never create it), and Area
# Stop ends one by EffectID.
T_AREA_MOVE_TRIGGER = "area_move_trigger"
T_AREA_ROTATE_TRIGGER = "area_rotate_trigger"
T_AREA_SCALE_TRIGGER = "area_scale_trigger"
T_AREA_FADE_TRIGGER = "area_fade_trigger"
T_AREA_TINT_TRIGGER = "area_tint_trigger"
T_EDIT_AREA_MOVE_TRIGGER = "edit_area_move_trigger"
T_EDIT_AREA_ROTATE_TRIGGER = "edit_area_rotate_trigger"
T_EDIT_AREA_SCALE_TRIGGER = "edit_area_scale_trigger"
T_EDIT_AREA_FADE_TRIGGER = "edit_area_fade_trigger"
T_EDIT_AREA_TINT_TRIGGER = "edit_area_tint_trigger"
T_AREA_STOP_TRIGGER = "area_stop_trigger"

# Checkpoint 3 of the deep-research-report.md refactor ("Core object,
# paired, and item triggers"): the two random-selection triggers and the
# contact force object.
#
# Random (real GD id 1912) picks between two target groups by a
# percentage; Advanced Random (2068) picks one of up to 20 groups by
# weight. Both END in "fire a target group", so they are triggers.
#
# Force Block (2069) is NOT a trigger: it targets no group and runs no
# handler. It is a placed object the player makes contact with, like the
# S/J/D/H letter blocks, and its effect (a velocity impulse) is applied
# from core.py's _handle_interactions -- see FORCE_BLOCK_* below and
# Player._apply_force_block.
T_RANDOM_TRIGGER = "random_trigger"
T_ADVANCED_RANDOM_TRIGGER = "advanced_random_trigger"
T_FORCE_BLOCK = "force_block"

# Checkpoint 5 of the deep-research-report.md refactor ("Audio, timers,
# and arithmetic", real GD object ids 1934 / 3602 / 3603 / 3605): the
# audio family. Song and SFX START playback of one of the project's OWN
# bundled tracks/sounds (the licensed GD song + SFX library is explicitly
# out of scope); Edit Song and Edit SFX PATCH already-playing audio,
# addressed by song channel and by unique id respectively -- exactly the
# Edit-Area relationship, where the Edit variant modifies live state by
# id and never creates it.
#
# All four are one-shot activations fired by touch or by a Spawn/
# Sequence/Repeat chain, so they are ordinary TRIGGER_TYPES members that
# run through the enqueue -> drain -> TRIGGER_HANDLERS path. None of them
# targets a group (they act on the mixer), so they are NOT in
# CONTROL_TRIGGER_TYPES -- like the camera/screen-effect families, a
# Toggle-disabled audio trigger is inert.
T_SONG_TRIGGER = "song_trigger"
T_SFX_TRIGGER = "sfx_trigger"
T_EDIT_SONG_TRIGGER = "edit_song_trigger"
T_EDIT_SFX_TRIGGER = "edit_sfx_trigger"

# Checkpoint 6 of the deep-research-report.md refactor ("Gameplay, camera,
# UI, and environment", real GD object ids 2900 / 1917 / 3022 / 2063): the
# four triggers whose target is the PLAYER itself -- its gameplay
# direction, gravity, velocity, position and practice checkpoint -- rather
# than an object group (Move/Rotate), the camera, the screen or the mixer.
#
# All four are group-TARGETED in the activation sense (fired by touch or by
# a Spawn/Sequence/Repeat chain through the enqueue -> drain ->
# TRIGGER_HANDLERS path) and none of them runs other triggers, so like the
# camera/audio families they are ordinary TRIGGER_TYPES members and are NOT
# in CONTROL_TRIGGER_TYPES: a Toggle-disabled one is inert.
#
# T_CHECKPOINT_TRIGGER is deliberately a DIFFERENT type from the existing
# T_CHECKPOINT above: that one is the transient, never-placeable practice
# marker (category None, dropped on save by levels.py); this one is the
# placeable object a level author drops in, whose only effect is to call
# the same Player.save_checkpoint() the manual practice hotkey calls.
T_GAMEPLAY_ROTATION_TRIGGER = "gameplay_rotation_trigger"
T_REVERSE_TRIGGER = "reverse_trigger"
T_TELEPORT_TRIGGER = "teleport_trigger"
T_CHECKPOINT_TRIGGER = "checkpoint_trigger"

# Checkpoint 7 of the deep-research-report.md refactor ("Gameplay, camera,
# UI, and environment", real GD object ids 3030 / 3031 / 3606 / 3612 /
# 3613 / 3604 / 3600). Five sub-families, all ordinary TRIGGER_TYPES
# members fired by touch or a Spawn/Sequence/Repeat chain through the
# enqueue -> drain -> TRIGGER_HANDLERS path, and none of them in
# CONTROL_TRIGGER_TYPES (none of them runs other triggers as its own
# effect -- the Event Trigger comes closest, but the ENGINE fires it, it
# does not decide whether other triggers may fire):
#
#   * Change Ground (3030) / Change Middleground (3031) EXTEND the
#     existing T_BG_TRIGGER (Change Background, 3029) rather than
#     replacing it. Both are STORED-ONLY: BG_PRESETS is the only
#     environment palette table this engine has -- there is no ground or
#     middleground preset table in graphics.py/play_render.py to select
#     from (the ground is the C_GROUND* constants and the middleground
#     is graphics._MOUNTAIN_SHADES, both fixed), so the preset index is
#     authored, saved and round-tripped but nothing reads it back. Same
#     precedent as the Shader Trigger's lowest_layer/highest_layer and
#     the audio family's speed/pitch/reverb: honest inert storage, never
#     a faked effect.
#   * Background Speed (3606) / Middleground Speed (3612) are REAL:
#     graphics.draw_bg already parallax-scrolls the star field and the
#     mountain layers at fixed rates, and these two scale those rates.
#   * UI Trigger (3613) posts a camera-anchored HUD text label.
#   * Event Trigger (3604) fires its target group when a named ENGINE
#     event happens (see LEVEL_EVENTS below) instead of on touch/spawn.
#   * End Trigger (3600) is a second activation path into the win flag
#     the existing T_END finish wall already sets; T_END is untouched.
T_GROUND_TRIGGER = "ground_trigger"
T_MG_TRIGGER = "mg_trigger"
T_BG_SPEED_TRIGGER = "bg_speed_trigger"
T_MG_SPEED_TRIGGER = "mg_speed_trigger"
T_UI_TRIGGER = "ui_trigger"
T_EVENT_TRIGGER = "event_trigger"
T_END_TRIGGER = "end_trigger"

# Environment-family bounds/defaults (Checkpoint 7).
#
# The four SPEED defaults below are the report's own verbatim documented
# values ("Default BG speed X 0.1 / Y 0.1, Default MG speed X 0.3 / Y
# 0.5") -- the only hard numbers the report gives this family, so they
# are used exactly, not rounded or reinterpreted.
#
# How they reach the screen: draw_bg's parallax rates are FIXED engine
# constants (stars scroll at BG_PARALLAX_BASE, mountains at
# graphics._MOUNTAIN_SPEEDS). A Background/Middleground Speed trigger
# does not replace those rates, it SCALES them by speed/default -- so a
# level that never fires one, or fires one carrying the report's default,
# renders pixel-identically to before this checkpoint.
BG_SPEED_DEFAULT_X = 0.1
BG_SPEED_DEFAULT_Y = 0.1
MG_SPEED_DEFAULT_X = 0.3
MG_SPEED_DEFAULT_Y = 0.5
# Engine-chosen authoring bounds (the report cites no range). Negative is
# allowed on purpose: it is the one authoring trick this scaling model
# gives for free (a layer that drifts against the camera).
ENV_SPEED_MIN = -10.0
ENV_SPEED_MAX = 10.0
# Engine-chosen authoring ceiling for the stored-only Change Ground /
# Change Middleground preset index. Deliberately NOT len(BG_PRESETS) - 1:
# that would imply the index selects from the background palette, and it
# selects from nothing at all.
ENV_PRESET_MAX = 7

# UI Trigger (3613) authoring vocabulary.
#
# DELIBERATE SCOPE TRIM, recorded so it is not mistaken for an oversight:
# Field has no free-text kind (see the same note on Advanced Random's
# weighted_list above), so the label is a fixed choice list rather than
# typed text -- the same precedent Checkpoint 3 set when it capped
# Advanced Random's editor UI instead of building text-entry plumbing.
# The engine reads whatever string is on the object, so a level authored
# programmatically can carry any label; only the editor is capped.
UI_TEXT_CHOICES = ("Ready", "Go!", "Jump!", "Wait", "Nice!", "Danger",
                   "Almost", "Hold", "Release")
# Screen-space offset bounds for a UI label, in pixels from the screen
# centre. Bounded by the window so an authored label cannot land where
# nothing can ever see it.
UI_OFFSET_MAX = 600
# 0 = persist until another UI Trigger with the same ui_id clears it.
UI_DURATION_MAX_SECONDS = 60.0

# Event Trigger (3604) event vocabulary. The report says only "in-game
# events -> spawned group" and gives no field map at all, so the list
# below is entirely engine-chosen (verification="unverified"): these are
# the five discrete, already-existing moments in Player's lifecycle that
# something can be hung off without inventing new machinery --
#   level_start  Player.reset() finished (every attempt, retries too)
#   death        the main body died (Player._kill / mirror collapse)
#   win          the win flag flipped (finish wall OR End Trigger)
#   checkpoint   Player.save_checkpoint() stored one
#   respawn      Player.load_checkpoint() restored one
EVENT_LEVEL_START = "level_start"
EVENT_DEATH = "death"
EVENT_WIN = "win"
EVENT_CHECKPOINT = "checkpoint"
EVENT_RESPAWN = "respawn"
LEVEL_EVENTS = (EVENT_LEVEL_START, EVENT_DEATH, EVENT_WIN, EVENT_CHECKPOINT,
                EVENT_RESPAWN)

# Legacy transition objects (report, "Transition, letter, and legacy
# objects": ids 22-59 plus the 2.2 Enter Move/Rotate/Scale/Fade/Tint
# 3017-3021 and Enter Stop 3023).
#
# DELIBERATE SIMPLIFICATION, and the report invites it: it describes the
# public taxonomy as "none, four directional transitions, expanding/
# shrinking, diagonal variants, plus a custom-transition stop" and then
# explicitly marks the low-id legacy records as a taxonomy it cannot
# cleanly map onto current trigger types. So this engine models the
# CONCEPT ("how does the level begin") as a level-META enum rather than
# ~20 placeable objects: one representative per documented shape --
# "none" (id 22), "fade" (the 23-26/55-59 fade family), "scale" (the
# 27/28 Scale Up/Down pair). Consumed at attempt start by play.py.
LEVEL_TRANSITIONS = ("none", "fade", "scale")
LEVEL_TRANSITION_DEFAULT = "none"
# How long the level-start transition runs, in physics ticks, and how far
# out "scale" starts zoomed. Both engine choices (the report documents no
# duration for any transition record). Half a second is short enough not
# to eat into the first jump's reaction window at 240 TPS.
LEVEL_TRANSITION_FRAMES = PHYSICS_TPS // 2
LEVEL_TRANSITION_SCALE_START = 1.35

# Gameplay-family bounds/defaults.
#   * GAMEPLAY_CHANNEL_DEFAULT: the report's one hard documented default in
#     this family ("the active gameplay channel ... defaults to channel 0").
#     GAMEPLAY_CHANNEL_MAX is an engine-chosen authoring ceiling: this
#     engine has no gameplay-channel gating at all (no other trigger type
#     carries a channel), so the field is stored-only -- see the
#     T_GAMEPLAY_ROTATION_TRIGGER spec in objects.py.
#   * GAMEPLAY_VELOCITY_MAX: the +/- bound on Gameplay Rotation's optional
#     velocity override, in units/tick, an engine choice (the report names
#     the capability, not a range). Same scale reference as the Force Block
#     numbers above: a cube jump is about 2.8 units/tick.
GAMEPLAY_CHANNEL_DEFAULT = 0
GAMEPLAY_CHANNEL_MAX = 9
GAMEPLAY_VELOCITY_MAX = 30.0

# Audio-family bounds. The report gives the property KEYS for every field
# below but no ranges or defaults for any of them, so every number here
# is an engine choice, chosen to keep an authored value inside what this
# engine can actually do:
#   * SONG_CHANNEL_MAX: GD 2.2 exposes a handful of song channels; this
#     engine has exactly ONE music stream (pygame.mixer.music), so the
#     channel is an addressing id for Edit Song rather than real mixing --
#     see Player._apply_song_trigger. Kept small so the editor's +/- row
#     can't author a channel nothing will ever be able to sound.
#   * AUDIO_SPEED_*: stored only -- pygame has no playback-rate control.
#   * AUDIO_PITCH_*: semitones, stored only -- no pitch-shift primitive.
#   * AUDIO_FADE_MAX_SECONDS / AUDIO_TIME_MAX_SECONDS: sane authoring
#     ceilings for the fade and start/end second fields.
SONG_CHANNEL_MAX = 3
AUDIO_SPEED_MIN = 0.1
AUDIO_SPEED_MAX = 4.0
AUDIO_PITCH_MIN = -12.0
AUDIO_PITCH_MAX = 12.0
AUDIO_FADE_MAX_SECONDS = 30.0
AUDIO_TIME_MAX_SECONDS = 3600.0

# Advanced Random's weighted list (report, "Representative full-format
# records"): FlowVix documents it as a dot-separated
# "group.weight.group.weight..." string of at most 20 pairs, with
# P(i) = 100 * w_i / sum(w_j). The engine parses/serializes the full
# 20-pair form (see objects.parse_weighted_list); the property panel
# only exposes the first ADVANCED_RANDOM_EDITOR_SLOTS pairs as plain int
# rows, because the panel has no free-text field kind and building one
# was a deliberate scope trim for this checkpoint.
ADVANCED_RANDOM_MAX_PAIRS = 20
ADVANCED_RANDOM_EDITOR_SLOTS = 4

# Force Block defaults. The report cites FlowVix's field *names* and
# numeric keys but no source it located documents their ranges,
# defaults, or exact application semantics, so every number here is an
# engine choice -- see Player._apply_force_block for the reading each
# one encodes. Scale reference: JUMP_FORCE_UT is about -2.8 units/tick,
# so a force of +/-3 is roughly one cube jump's worth of impulse.
FORCE_BLOCK_DEFAULT_RANGE = 1.0
# Bounded by the 2-cell margin _nearby_triggers_for_aabb queries with:
# a block farther than that from the player is never even considered,
# so a larger radius would silently do nothing.
FORCE_BLOCK_MAX_RANGE = 2.0
FORCE_BLOCK_MAX_FORCE = 30.0

# ---------------------------------------------------------------------------
# Logical type sets
# ---------------------------------------------------------------------------
LETTER_BLOCK_TYPES = frozenset({T_DASH_STOP, T_JUMP_BLOCK, T_WAVE_BLOCK,
                                T_BONK_BLOCK})
DECORATION_TYPES = frozenset({T_DECO_CRYSTAL, T_DECO_PILLAR, T_DECO_GLOW})

# ---------------------------------------------------------------------------
# Z-Layer / Z-Order (real GD draw-order system)
#
# GD separates "what draws in front of what" from the Editor Layers panel
# (organizational only -- see editor/state.py's active_layer/layer_hidden).
# Every object sits on one of 7 named Z-Layers, back to front; within a
# layer, integer Z-Order breaks ties (higher draws in front). Z-Layer
# always wins over Z-Order -- an object on t1/-5 still draws above one on
# b1/500. Objects with no explicit z_layer keep this engine's original
# behavior: DECORATION_TYPES sit on "b1" (behind gameplay), everything
# else on "t1", so existing levels render exactly as before.
Z_LAYERS = ("b4", "b3", "b2", "b1", "t1", "t2", "t3")
Z_LAYER_INDEX = {name: i for i, name in enumerate(Z_LAYERS)}
Z_LAYER_LABELS = {
    "b4": "Bottom 4", "b3": "Bottom 3", "b2": "Bottom 2", "b1": "Bottom 1",
    "t1": "Top 1", "t2": "Top 2", "t3": "Top 3",
}
Z_LAYER_DEFAULT = "t1"
Z_LAYER_DECORATION_DEFAULT = "b1"
Z_ORDER_DEFAULT = 0
Z_ORDER_STEP = 5  # GD's own guidance: leave gaps of 3-5 between orders
TRIGGER_TYPES = frozenset({T_CAMERA_TRIGGER, T_BG_TRIGGER, T_MOVE_TRIGGER,
                           T_COLOR_TRIGGER, T_PULSE_TRIGGER, T_ROTATE_TRIGGER,
                           T_TIME_WARP, T_FOLLOW_TRIGGER, T_BLACKOUT_TRIGGER,
                           T_SPAWN_TRIGGER, T_TOGGLE_TRIGGER, T_STOP_TRIGGER,
                           T_SEQUENCE_TRIGGER, T_REPEAT_TRIGGER, T_SCALE_TRIGGER,
                           T_ALPHA_TRIGGER, T_SWAP_TRIGGER, T_ZOOM_TRIGGER,
                           T_CAM_OFFSET_TRIGGER, T_CAM_ROTATE_TRIGGER,
                           T_CAM_EDGE_TRIGGER, T_CAM_GUIDE_TRIGGER,
                           T_GRAYSCALE_TRIGGER, T_SEPIA_TRIGGER,
                           T_INVERT_TRIGGER, T_HUE_TRIGGER,
                           T_PIXELATE_TRIGGER, T_SHADER_TRIGGER,
                           T_CHROMATIC_TRIGGER, T_RADIAL_BLUR_TRIGGER,
                           T_MOTION_BLUR_TRIGGER, T_BULGE_TRIGGER,
                           T_PINCH_TRIGGER, T_SPLIT_SCREEN_TRIGGER,
                           T_COUNT_TRIGGER, T_INSTANT_COUNT_TRIGGER,
                           T_ITEM_EDIT_TRIGGER, T_ITEM_COMP_TRIGGER,
                           T_ITEM_PERS_TRIGGER, T_TIME_TRIGGER,
                           T_TIME_EVENT_TRIGGER, T_KEYFRAME_TRIGGER,
                           T_AREA_MOVE_TRIGGER, T_AREA_ROTATE_TRIGGER,
                           T_AREA_SCALE_TRIGGER, T_AREA_FADE_TRIGGER,
                           T_AREA_TINT_TRIGGER, T_EDIT_AREA_MOVE_TRIGGER,
                           T_EDIT_AREA_ROTATE_TRIGGER,
                           T_EDIT_AREA_SCALE_TRIGGER,
                           T_EDIT_AREA_FADE_TRIGGER,
                           T_EDIT_AREA_TINT_TRIGGER, T_AREA_STOP_TRIGGER,
                           T_RANDOM_TRIGGER, T_ADVANCED_RANDOM_TRIGGER,
                           T_SONG_TRIGGER, T_SFX_TRIGGER,
                           T_EDIT_SONG_TRIGGER, T_EDIT_SFX_TRIGGER,
                           T_GAMEPLAY_ROTATION_TRIGGER, T_REVERSE_TRIGGER,
                           T_TELEPORT_TRIGGER, T_CHECKPOINT_TRIGGER,
                           T_GROUND_TRIGGER, T_MG_TRIGGER,
                           T_BG_SPEED_TRIGGER, T_MG_SPEED_TRIGGER,
                           T_UI_TRIGGER, T_EVENT_TRIGGER, T_END_TRIGGER})
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
                                   T_STOP_TRIGGER, T_SEQUENCE_TRIGGER,
                                   T_REPEAT_TRIGGER, T_RANDOM_TRIGGER,
                                   T_ADVANCED_RANDOM_TRIGGER}
                                  ) | ITEM_LOGIC_TRIGGER_TYPES
# Checkpoint 3: the two triggers whose whole effect is "pick a target
# group at random, then fire it". They sit in CONTROL_TRIGGER_TYPES
# above (unlike the Area family, which does not) for the reason that set
# documents: their effect IS running other triggers, so a Toggle-disabled
# Random must stay live to be able to re-enable a chain, exactly like
# Spawn/Sequence/Repeat.
RANDOM_TRIGGER_TYPES = frozenset({T_RANDOM_TRIGGER,
                                  T_ADVANCED_RANDOM_TRIGGER})
COLLECTIBLE_ITEM_TYPES = frozenset({T_ITEM_PICKUP})
# Checkpoint 8: data-only keyframe markers, indexed by animation id
# (Player._by_animation) rather than executed as a trigger themselves.
KEYFRAME_TYPES = frozenset({T_KEYFRAME})
# Checkpoint 2 (deep-research-report.md, "Area and keyframe system"): the
# five triggers that START a continuous area effect, the five that PATCH a
# live one, and the one that ENDS one. Deliberately NOT folded into
# CONTROL_TRIGGER_TYPES: an Edit Area / Area Stop trigger acts on
# area-effect state, not on whether other triggers may fire, so it stays
# gated by Toggle exactly like Move/Rotate/Scale (only the "run other
# triggers" family needs the disabled-group bypass).
AREA_START_TRIGGER_TYPES = frozenset({
    T_AREA_MOVE_TRIGGER, T_AREA_ROTATE_TRIGGER, T_AREA_SCALE_TRIGGER,
    T_AREA_FADE_TRIGGER, T_AREA_TINT_TRIGGER,
})
EDIT_AREA_TRIGGER_TYPES = frozenset({
    T_EDIT_AREA_MOVE_TRIGGER, T_EDIT_AREA_ROTATE_TRIGGER,
    T_EDIT_AREA_SCALE_TRIGGER, T_EDIT_AREA_FADE_TRIGGER,
    T_EDIT_AREA_TINT_TRIGGER,
})
AREA_TRIGGER_TYPES = (AREA_START_TRIGGER_TYPES | EDIT_AREA_TRIGGER_TYPES
                      | frozenset({T_AREA_STOP_TRIGGER}))
# Checkpoint 5 (deep-research-report.md, "Audio, timers, and
# arithmetic"): the two triggers that START audio and the two that PATCH
# live audio. Same split-by-role shape as the Area sets above, for the
# same reason -- the start/edit distinction is the family's whole
# structure, so code that needs one half never has to re-list types.
AUDIO_START_TRIGGER_TYPES = frozenset({T_SONG_TRIGGER, T_SFX_TRIGGER})
EDIT_AUDIO_TRIGGER_TYPES = frozenset({T_EDIT_SONG_TRIGGER,
                                      T_EDIT_SFX_TRIGGER})
AUDIO_TRIGGER_TYPES = AUDIO_START_TRIGGER_TYPES | EDIT_AUDIO_TRIGGER_TYPES
# Checkpoint 6 (deep-research-report.md, "Gameplay, camera, UI, and
# environment"): the triggers that act on the PLAYER's own state --
# direction/gravity/velocity (Gameplay Rotation, Reverse), position
# (Teleport Trigger) and practice checkpoint (Checkpoint Trigger). Named
# for what they act ON, the same way AREA_/AUDIO_TRIGGER_TYPES are, so
# code (and the audit) can address the family without re-listing it.
PLAYER_STATE_TRIGGER_TYPES = frozenset({
    T_GAMEPLAY_ROTATION_TRIGGER, T_REVERSE_TRIGGER, T_TELEPORT_TRIGGER,
    T_CHECKPOINT_TRIGGER,
})
# Checkpoint 7: the triggers that act on the SCENERY -- which background /
# ground / middleground preset is showing and how fast each parallax layer
# scrolls. T_BG_TRIGGER (the pre-existing Change Background) is a member:
# this set names a family, and splitting the family's oldest member out of
# it would be exactly the kind of "one more list to keep in sync" the
# registry design avoids. The two CHANGE triggers with no preset table
# behind them are called out separately below.
ENVIRONMENT_TRIGGER_TYPES = frozenset({
    T_BG_TRIGGER, T_GROUND_TRIGGER, T_MG_TRIGGER, T_BG_SPEED_TRIGGER,
    T_MG_SPEED_TRIGGER,
})
# The subset of the above whose authored preset index this engine stores
# but never reads (no ground/middleground palette exists to select from).
# Named rather than commented so the audit -- and the test that pins the
# never-read property -- can address it without re-listing types.
INERT_PRESET_TRIGGER_TYPES = frozenset({T_GROUND_TRIGGER, T_MG_TRIGGER})
# Checkpoint 6 / Checkpoint 4: screen-effect triggers, for render code
# that needs to iterate "every effect type" without listing them by name.
# The membership rule is precise: a type belongs here iff activating it
# tweens one named entry in Player.active_effect_anims toward an
# intensity over a duration, i.e. iff it is dispatched through
# _start_effect_trigger. Shader Trigger (2904) is deliberately NOT a
# member -- it animates nothing and has no apply_screen_effects branch;
# its whole documented behavior is clearing that dict. Adding it here
# would promise build_screen_effects an "shader_trigger" anim entry that
# never exists.
SCREEN_EFFECT_TRIGGER_TYPES = frozenset({
    T_GRAYSCALE_TRIGGER, T_SEPIA_TRIGGER, T_INVERT_TRIGGER, T_HUE_TRIGGER,
    T_PIXELATE_TRIGGER, T_CHROMATIC_TRIGGER, T_RADIAL_BLUR_TRIGGER,
    T_MOTION_BLUR_TRIGGER, T_BULGE_TRIGGER, T_PINCH_TRIGGER,
    T_SPLIT_SCREEN_TRIGGER,
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

# ---------------------------------------------------------------------------
# Body ("red" hazard) size per (mode, mini) — physics bible §3.2, in GD units.
#
# The fractions above are literally bible_blue/bible_red (9/30, 3/10, 9/27.5,
# ...), so they only yield the bible's blue box when the body size IS that
# row's red box.  A single PLAYER_SIZE_UNITS for every mode therefore made
# Wave's solid box 9 units instead of 3 and Spider's 9.8 instead of 9 — the
# same coupling that made the pre-cutover 26.4-unit body produce a 7.92 solid
# box (see PLAYER_SIZE_UNITS above).  This table is the missing half of it.
#
# §3.4: Wave "threads tight gaps" precisely because its 10-unit box is a
# third of every other normal-size mode's; Spider's 27.5 is the only other
# sub-30 value.  Mini is 0.6x the red box on every row (30->18, 10->6,
# 27.5->16.5); the bible flags Spider's 16.5 as its one uncertain figure.
#
# This is the HITBOX only.  GD draws each icon at its own art size, which is
# not the hitbox size for any mode — see ICON_SIZE_UNITS.
# ---------------------------------------------------------------------------
BODY_SIZE_UNITS = {
    # mode: (normal, mini)
    MODE_CUBE:   (PLAYER_SIZE_UNITS, MINI_PLAYER_SIZE_UNITS),
    MODE_SHIP:   (PLAYER_SIZE_UNITS, MINI_PLAYER_SIZE_UNITS),
    MODE_BALL:   (PLAYER_SIZE_UNITS, MINI_PLAYER_SIZE_UNITS),
    MODE_UFO:    (PLAYER_SIZE_UNITS, MINI_PLAYER_SIZE_UNITS),
    MODE_ROBOT:  (PLAYER_SIZE_UNITS, MINI_PLAYER_SIZE_UNITS),
    MODE_SWING:  (PLAYER_SIZE_UNITS, MINI_PLAYER_SIZE_UNITS),
    MODE_WAVE:   (10.0, 6.0),
    MODE_SPIDER: (27.5, 16.5),
}


def body_size_units(mode, mini):
    """The bible §3.2 red-hitbox side for ``mode``, in GD units."""
    return BODY_SIZE_UNITS.get(
        mode, (PLAYER_SIZE_UNITS, MINI_PLAYER_SIZE_UNITS))[1 if mini else 0]


def is_mini_size(mode, size):
    """Whether ``size`` is ``mode``'s mini body.

    Mini state is derived from the stored size rather than carried as its
    own field, so every existing snapshot / checkpoint / bot-search tuple
    that already round-trips ``size`` keeps working unchanged.  This
    generalises the old ``size < PLAYER_SIZE_UNITS`` test, which read a
    normal-size Wave (10 units) as mini.
    """
    return size < BODY_SIZE_UNITS.get(
        mode, (PLAYER_SIZE_UNITS, MINI_PLAYER_SIZE_UNITS))[0]


# ---------------------------------------------------------------------------
# Icon (drawn sprite) size per mode, in GD units — measured off RobTop's own
# `GJ_GameSheet02` cocos2d plist (`spriteSourceSize`, which is authored in GD
# units), NOT off the hitbox:
#
#     player_01 (cube) 30x30   dart_01 (wave) 26x21   ship_01 37x23
#     bird_01 (UFO)    37x16   spider_01_01   30x20   player_ball_01 35x35
#
# So no GD gamemode draws its icon at its hitbox size, and Wave is the
# extreme case: a 26-unit icon over a 10-unit box.  Shrinking the wave
# *sprite* to its new 10-unit hitbox would have made the dart 2.6x smaller
# than RobTop draws it; this table keeps the art at its sourced size while
# the hitbox alone follows §3.2.
#
# Only the longest side is modelled, because the renderer composes every
# icon on a square canvas (player/draw.py).  Modes whose art is markedly
# non-square (ship/UFO 37-unit spans, ball 35) are deliberately left at
# PLAYER_SIZE_UNITS: growing them on a square canvas would stretch their
# height too, which is a further divergence, not a fix.  Wave is included
# because its long side (26) is what the square canvas already scales by.
# ---------------------------------------------------------------------------
ICON_SIZE_UNITS = {MODE_WAVE: 26.0}


def icon_size_units(mode, size):
    """Drawn icon side for ``mode`` at body ``size``, in GD units."""
    icon = ICON_SIZE_UNITS.get(mode)
    if icon is None:
        return size
    return icon * (0.6 if is_mini_size(mode, size) else 1.0)

# Speed portal units/tick values. Bible §1.8 (community-measured, via
# move-trigger testing / official Fandom wiki): the portal labels are
# misleading multiples of 1x baseline (BASE_MOVE_SPEED) —
# 0.5x=~0.807x, 1x=1.0x, 2x=~1.243x, 3x=~1.502x, 4x=~1.849x. Ratios are
# more reliable than the bible's absolute blocks/sec figures (which carry
# measurement error across sources), so BASE_MOVE_SPEED_UT anchors 1x and
# every other tier is BASE_MOVE_SPEED_UT * ratio.
SPEED_RATIOS = {
    T_SPEED_SLOW: 0.807,
    T_SPEED_NORMAL: 1.0,
    T_SPEED_FAST: 1.243,
    T_SPEED_FASTER: 1.502,
    T_SPEED_FASTEST: 1.849,
}
SPEED_VALUES_UT = {k: BASE_MOVE_SPEED_UT * r for k, r in SPEED_RATIOS.items()}
# px/tick twin, for the render-side music/time-to-x mapping in play.py.
SPEED_VALUES = {k: _ut_to_px(v) for k, v in SPEED_VALUES_UT.items()}

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
# GD splits a block between two colour channels: "Base" paints the bright
# outline and "Black" paints the interior, which defaults to black. The
# full block's texture has that interior baked in; the half block ships as
# a white silhouette and has to be tinted with it explicitly.
C_BLOCK_INNER = (0, 0, 0)
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
C_SHADER_TRIGGER = (120, 120, 160)
C_CHROMATIC_TRIGGER = (255, 90, 140)
C_RADIAL_BLUR_TRIGGER = (140, 170, 255)
C_MOTION_BLUR_TRIGGER = (110, 140, 220)
C_BULGE_TRIGGER = (255, 160, 110)
C_PINCH_TRIGGER = (200, 130, 255)
C_SPLIT_SCREEN_TRIGGER = (90, 200, 170)
C_ITEM_PICKUP = (255, 235, 80)
C_COUNT_TRIGGER = (140, 255, 210)
C_ITEM_EDIT_TRIGGER = (255, 170, 210)
C_ITEM_COMP_TRIGGER = (170, 210, 255)
C_TIME_TRIGGER = (210, 255, 140)
C_ITEM_COUNTER = (255, 255, 255)
C_KEYFRAME = (255, 190, 255)
C_KEYFRAME_TRIGGER = (220, 150, 255)
# Area family (Checkpoint 2): one hue per role -- start an effect, patch a
# live one, end one -- so a chain of them reads at a glance in the palette.
C_AREA_TRIGGER = (120, 200, 255)
C_EDIT_AREA_TRIGGER = (90, 150, 220)
C_AREA_STOP_TRIGGER = (255, 130, 150)
# Checkpoint 3: the two random pickers share a hue (one family, two
# precisions); Force Block is a contact object, not a trigger, so it
# takes a block-ish colour rather than a trigger one.
C_RANDOM_TRIGGER = (190, 255, 120)
C_ADVANCED_RANDOM_TRIGGER = (150, 220, 90)
C_FORCE_BLOCK = (255, 120, 40)
# Audio family (Checkpoint 5): one hue per role, like the Area family --
# the two that start playback read brighter than the two that patch it.
C_SONG_TRIGGER = (255, 150, 200)
C_SFX_TRIGGER = (255, 190, 130)
C_EDIT_SONG_TRIGGER = (200, 110, 160)
C_EDIT_SFX_TRIGGER = (210, 150, 100)
# Player-state family (Checkpoint 6): the two direction/gravity triggers
# share the gravity-portal blue so they read as "this changes how you
# move"; the Teleport Trigger borrows the teleport portal's orange, and
# the Checkpoint Trigger the practice-checkpoint green.
C_GAMEPLAY_ROTATION_TRIGGER = (110, 180, 255)
C_REVERSE_TRIGGER = (70, 140, 235)
C_TELEPORT_TRIGGER = (255, 165, 60)
C_CHECKPOINT_TRIGGER = (120, 230, 150)
# Environment family (Checkpoint 7): the ground/middleground change pair
# and the two speed triggers share the existing C_BG_TRIGGER teal at
# decreasing brightness, so the whole scenery family reads as one group
# in the palette. UI / Event / End take their own hues -- none of them
# touches scenery.
C_GROUND_TRIGGER = (60, 210, 175)
C_MG_TRIGGER = (45, 175, 150)
C_BG_SPEED_TRIGGER = (120, 255, 225)
C_MG_SPEED_TRIGGER = (90, 220, 200)
C_UI_TRIGGER = (250, 250, 210)
C_EVENT_TRIGGER = (210, 160, 255)
C_END_TRIGGER = C_END

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
