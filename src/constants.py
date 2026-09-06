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
CELL = 50
# Canonical physics tick rate.  Every velocity / acceleration constant
# below is in "px per (1/60)s" units, so this must stay 60 unless all of
# them are rescaled.  The renderer runs at any FPS and interpolates
# between ticks (see play.PlaySession).
FPS = 60
PHYSICS_TPS = 60
GROUND_Y = 550

# Maximum motion (px) covered by a single inner collision substep.
COLLISION_SUBSTEP_PX = 1.0

# Two-hitbox model: the OUTER rect (full sprite size, rotated with the
# player) triggers hazards / orbs / pads / triggers; the INNER rect (this
# fraction of the size, centred, axis-aligned) triggers block death.
SOLID_HITBOX_FRACTION = 0.50

# ---------------------------------------------------------------------------
# Player tunables (physics — do not change casually, levels depend on them)
# ---------------------------------------------------------------------------
PLAYER_SIZE = 44
MINI_PLAYER_SIZE = 24
BASE_MOVE_SPEED = 5.0
GRAVITY = 1.0
SHIP_GRAVITY = 0.72
SHIP_THRUST = 1.22
JUMP_FORCE = -16.0
PAD_FORCE = -18.0
BALL_FLIP_FORCE = 10.0
DASH_SPEED = 16.0
DASH_TIME = 9
WAVE_ANGLE = 45.0
PLAYER_START_GX = 3
UFO_JUMP_FORCE = -13.5
SPIDER_TELEPORT_RANGE = 6  # cells (legacy; teleports are now unbounded)
# Robot: held thrust applied each tick while the button is down, limited
# by a flight budget (seconds) that refills on landing.
ROBOT_THRUST = 1.45
ROBOT_FLIGHT_SECONDS = 1.5

# Orb / pad strength multipliers relative to JUMP_FORCE / PAD_FORCE.
# Mirrors GD: pink = small, yellow = medium, red = big.
ORB_PINK_SCALE = 0.75
ORB_RED_SCALE = 1.35
PAD_PINK_SCALE = 0.75
PAD_RED_SCALE = 1.35
# Blue orb: gravity flip with a modest push in the new direction.
BLUE_ORB_PUSH_SCALE = 0.45
BLUE_PAD_PUSH_SCALE = 0.5

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
LEVEL_FORMAT_VERSION = 7

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
# Editor-only helpers (inert at play time).
T_JUMP_PREDICTOR = "jump_predictor"
T_BOT_CHECKPOINT = "bot_checkpoint"

# ---------------------------------------------------------------------------
# Logical type sets
# ---------------------------------------------------------------------------
DECORATION_TYPES = frozenset({T_DECO_CRYSTAL, T_DECO_PILLAR, T_DECO_GLOW})
TRIGGER_TYPES = frozenset({T_CAMERA_TRIGGER, T_BG_TRIGGER, T_MOVE_TRIGGER,
                           T_COLOR_TRIGGER, T_PULSE_TRIGGER, T_ROTATE_TRIGGER,
                           T_TIME_WARP, T_FOLLOW_TRIGGER})
SOLID_TYPES = frozenset({T_BLOCK, T_SLAB})
# Slopes have diagonal collision handled by a dedicated pass.
SLOPE_TYPES = frozenset({T_SLOPE})
HAZARD_TYPES = frozenset({T_SPIKE, T_HALF_SPIKE, T_SAW})
ORB_TYPES = frozenset({T_ORB, T_PINK_ORB, T_RED_ORB, T_BLUE_ORB, T_GREEN_ORB,
                       T_BLACK_ORB, T_DASH_ORB, T_DASH_ORB_GRAV, T_SPIDER_ORB,
                       T_TELEPORT_ORB})
DASH_ORB_TYPES = frozenset({T_DASH_ORB, T_DASH_ORB_GRAV})
PAD_TYPES = frozenset({T_PAD, T_PINK_PAD, T_RED_PAD, T_BLUE_PAD, T_SPIDER_PAD})
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

# Speed portal px/tick values.  Slow / normal / fast / faster are the
# historical tunings (levels depend on them); fastest is the GD 4x tier.
SPEED_VALUES = {
    T_SPEED_SLOW: 4.0,
    T_SPEED_NORMAL: 5.0,
    T_SPEED_FAST: 6.7,
    T_SPEED_FASTER: 8.4,
    T_SPEED_FASTEST: 9.6,
}

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
C_TIME_WARP = (200, 140, 255)
C_JUMP_PREDICTOR = (255, 235, 120)
C_BOT_CHECKPOINT = (120, 230, 255)

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
