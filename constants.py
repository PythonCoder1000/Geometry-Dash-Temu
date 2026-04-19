"""Game constants, colors, and object/type tables.

Any change to object types, the default move curve, or `LEVEL_FORMAT_VERSION`
must be paired with a migration in ``levels.normalize_object`` so existing
levels keep loading.
"""
import os
import sys

# ---------------------------------------------------------------------------
# Window / grid
# ---------------------------------------------------------------------------
WIDTH, HEIGHT = 1200, 700
CELL = 50
FPS = 60
GROUND_Y = 550

# Design spacing scale — use these instead of hard-coded magic numbers
# so any future theme pass can rescale everything by editing one file.
# Mnemonic: 4/8/16/24/48 — powers-of-two + double-sized gutter.
SPACING_XS = 4
SPACING_SM = 8
SPACING_MD = 16
SPACING_LG = 24
SPACING_XL = 48

# ---------------------------------------------------------------------------
# Player tunables
# ---------------------------------------------------------------------------
PLAYER_SIZE = 44
MINI_PLAYER_SIZE = 24  # "mini portal" shrinks the hitbox to this
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
SPIDER_TELEPORT_RANGE = 6  # cells

# ---------------------------------------------------------------------------
# Paths — split between app-root (read-only in a packaged build) and the
# per-user writable data dir. Editable dev checkouts still write to the
# repo when `GDT_DEV_LOCAL=1` is set, so the workflow of "clone, run,
# mess with levels" doesn't change. Packaged builds bounce writes to
# the OS's standard per-user data directory.
# ---------------------------------------------------------------------------

def _app_root():
    """Directory of the app's read-only assets. Inside a PyInstaller
    --onefile bundle this is the extracted temp dir (``sys._MEIPASS``)."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return meipass
    return os.path.dirname(os.path.abspath(__file__))


def _is_frozen():
    """True when running from a PyInstaller / Nuitka frozen bundle.
    Those builds ship a read-only app dir, so all writes must go
    elsewhere. A plain `python main.py` checkout returns False.
    """
    return getattr(sys, "frozen", False) or hasattr(sys, "_MEIPASS")


def _user_data_dir():
    """OS-standard per-user directory for level files, prefs, progress,
    bot saves. Kept outside the bundle so writes work in frozen builds.

    Dev override: setting ``GDT_DEV_LOCAL=1`` forces writes back into
    the repo. It's also implied automatically for non-frozen runs so
    "clone the repo, python main.py, edit levels" keeps working without
    an extra env var. Set ``GDT_DEV_LOCAL=0`` to opt a dev build into
    the per-user dir explicitly.
    """
    override = os.environ.get("GDT_DEV_LOCAL")
    if override == "1":
        return os.path.dirname(os.path.abspath(__file__))
    if override != "0" and not _is_frozen():
        # Default for dev checkouts: stay in the repo so existing
        # workflows don't silently migrate levels to a new directory.
        return os.path.dirname(os.path.abspath(__file__))
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME",
                              os.path.expanduser("~/.local/share"))
    path = os.path.join(base, "GeometryDashTemu")
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        # If the user data dir is unwritable (read-only home, CI, etc.)
        # fall back to the app root so at least in-memory state works.
        path = os.path.dirname(os.path.abspath(__file__))
    return path


_ROOT = _app_root()
_USER_DATA = _user_data_dir()

# Read-only — shipped inside the bundle.
ASSETS_DIR = os.path.join(_ROOT, "assets")

# Writable — per-user persistent state.
LEVELS_DIR = os.path.join(_USER_DATA, "levels")
PROGRESS_FILE = os.path.join(_USER_DATA, "progress.json")
BOT_RUNS_DIR = os.path.join(_USER_DATA, "bot_runs")
PREFS_FILE = os.path.join(_USER_DATA, "prefs.json")
# User-imported music. Separate from the read-only bundled tracks so
# packaged builds can accept new files without requiring write access
# to the bundle. music.py scans both dirs; names must not collide.
USER_MUSIC_DIR = os.path.join(_USER_DATA, "music")

# Sample levels shipped with the app live under `assets/sample_levels/`;
# on first launch a seed-copy pushes them into the user's LEVELS_DIR so
# the level browser has something to show.
_BUNDLED_LEVELS_DIR = os.path.join(_ROOT, "levels")

LEVEL_FORMAT_VERSION = 6  # bumped: best_time_frames/deaths + group field

# ---------------------------------------------------------------------------
# Object type names (strings stored in level JSON — do not rename casually)
# ---------------------------------------------------------------------------
T_BLOCK = "block"
T_SLAB = "slab"
T_SPIKE = "spike"
T_HALF_SPIKE = "half_spike"
T_SAW = "saw"
T_ORB = "orb"
T_DASH_ORB = "dash_orb"
T_TELEPORT_ORB = "teleport_orb"
T_BLACK_ORB = "black_orb"
T_BLUE_ORB = "blue_orb"
T_GREEN_ORB = "green_orb"   # new: reverse-gravity jump
T_PAD = "pad"
T_BLUE_PAD = "blue_pad"     # new: gravity-flip pad
T_GRAV = "grav"
T_END = "end"
T_START = "start"
T_COIN = "coin"             # new: collectible (3 per level)
T_CHECKPOINT = "checkpoint" # new: practice checkpoint
T_MODE_CUBE = "mode_cube"
T_MODE_SHIP = "mode_ship"
T_MODE_BALL = "mode_ball"
T_MODE_WAVE = "mode_wave"
T_MODE_UFO = "mode_ufo"
T_MODE_SPIDER = "mode_spider"
T_MODE_MINI = "mode_mini"   # shrinks player ~50%
T_MODE_BIG = "mode_big"     # restores normal size
T_MODE_DUAL = "mode_dual"   # spawns a mirrored second player
T_MODE_SOLO = "mode_solo"   # returns to single player
T_SPEED_SLOW = "speed_slow"
T_SPEED_NORMAL = "speed_normal"
T_SPEED_FAST = "speed_fast"
T_SPEED_FASTER = "speed_faster"
T_DECO_CRYSTAL = "deco_crystal"
T_DECO_PILLAR = "deco_pillar"
T_DECO_GLOW = "deco_glow"
T_CAMERA_TRIGGER = "camera_trigger"
T_BG_TRIGGER = "bg_trigger"
T_MOVE_TRIGGER = "move_trigger"
T_COLOR_TRIGGER = "color_trigger"
T_PULSE_TRIGGER = "pulse_trigger"
T_ROTATE_TRIGGER = "rotate_trigger"

# Logical type sets
DECORATION_TYPES = {T_DECO_CRYSTAL, T_DECO_PILLAR, T_DECO_GLOW}
TRIGGER_TYPES = {T_CAMERA_TRIGGER, T_BG_TRIGGER, T_MOVE_TRIGGER, T_COLOR_TRIGGER,
                 T_PULSE_TRIGGER, T_ROTATE_TRIGGER}
SOLID_TYPES = {T_BLOCK, T_SLAB}
HAZARD_TYPES = {T_SPIKE, T_HALF_SPIKE, T_SAW}
ORB_TYPES = {T_ORB, T_DASH_ORB, T_TELEPORT_ORB, T_BLACK_ORB, T_BLUE_ORB, T_GREEN_ORB}
PAD_TYPES = {T_PAD, T_BLUE_PAD}
COLLECTIBLE_TYPES = {T_COIN}

# ---------------------------------------------------------------------------
# Mode strings (used in Player.mode). Keep separate from the portal type names
# so renaming a portal doesn't break saved player state.
# ---------------------------------------------------------------------------
MODE_CUBE = "cube"
MODE_SHIP = "ship"
MODE_BALL = "ball"
MODE_WAVE = "wave"
MODE_UFO = "ufo"
MODE_SPIDER = "spider"

MODE_FROM_TYPE = {
    T_MODE_CUBE: MODE_CUBE,
    T_MODE_SHIP: MODE_SHIP,
    T_MODE_BALL: MODE_BALL,
    T_MODE_WAVE: MODE_WAVE,
    T_MODE_UFO: MODE_UFO,
    T_MODE_SPIDER: MODE_SPIDER,
}

# ---------------------------------------------------------------------------
# Move trigger curve
# ---------------------------------------------------------------------------
DEFAULT_MOVE_CURVE = [[0.0, 1.0], [1.0, 1.0]]
MOVE_CURVE_SPEED_MAX = 3.0

# ---------------------------------------------------------------------------
# Player colors (cycled by color triggers)
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

# Player icon names — index matches the glyph drawing branch in
# graphics.draw_cube_icon_glyph. The customize screen iterates these.
PLAYER_ICONS = [
    "Classic",
    "Star",
    "Triangle",
    "Diamond",
    "Circle",
    "Plus",
    "Heart",
    "Bolt",
]

SPEED_VALUES = {
    T_SPEED_SLOW: 4.0,
    T_SPEED_NORMAL: 5.0,
    T_SPEED_FAST: 6.7,
    T_SPEED_FASTER: 8.4,
}

# ---------------------------------------------------------------------------
# Difficulty
# ---------------------------------------------------------------------------
DIFFICULTIES = ["Auto", "Easy", "Normal", "Hard", "Harder", "Insane", "Demon"]
DIFFICULTY_COLORS = {
    "Auto":   (180, 255, 180),
    "Easy":   (100, 230, 255),
    "Normal": (100, 255, 120),
    "Hard":   (255, 220, 80),
    "Harder": (255, 150, 60),
    "Insane": (255, 80, 80),
    "Demon":  (255, 40, 220),
}

TYPE_NAMES = {
    T_BLOCK: "Block",
    T_SLAB: "Slab",
    T_SPIKE: "Spike",
    T_HALF_SPIKE: "Half Spike",
    T_SAW: "Saw",
    T_ORB: "Jump Orb",
    T_DASH_ORB: "Dash Orb",
    T_TELEPORT_ORB: "Teleport Orb",
    T_BLACK_ORB: "Black Orb",
    T_BLUE_ORB: "Blue Orb",
    T_GREEN_ORB: "Green Orb",
    T_PAD: "Jump Pad",
    T_BLUE_PAD: "Blue Pad",
    T_GRAV: "Gravity Portal",
    T_END: "Finish",
    T_START: "Start Pos",
    T_COIN: "Coin",
    T_CHECKPOINT: "Checkpoint",
    T_MODE_CUBE: "Cube Portal",
    T_MODE_SHIP: "Ship Portal",
    T_MODE_BALL: "Ball Portal",
    T_MODE_WAVE: "Wave Portal",
    T_MODE_UFO: "UFO Portal",
    T_MODE_SPIDER: "Spider Portal",
    T_MODE_MINI: "Mini Portal",
    T_MODE_BIG: "Big Portal",
    T_MODE_DUAL: "Dual Portal",
    T_MODE_SOLO: "Solo Portal",
    T_SPEED_SLOW: "0.8x Speed",
    T_SPEED_NORMAL: "1.0x Speed",
    T_SPEED_FAST: "1.35x Speed",
    T_SPEED_FASTER: "1.65x Speed",
    T_DECO_CRYSTAL: "Crystal",
    T_DECO_PILLAR: "Pillar",
    T_DECO_GLOW: "Glow Dot",
    T_CAMERA_TRIGGER: "Camera Trigger",
    T_BG_TRIGGER: "BG Trigger",
    T_MOVE_TRIGGER: "Move Trigger",
    T_COLOR_TRIGGER: "Color Trigger",
    T_PULSE_TRIGGER: "Pulse Trigger",
    T_ROTATE_TRIGGER: "Rotate Trigger",
}

TYPE_TIPS = {
    T_BLOCK: "Solid. Player lands on top.",
    T_SLAB: "Half-height block.",
    T_SPIKE: "Kills on touch.",
    T_HALF_SPIKE: "Smaller, forgiving spike.",
    T_SAW: "Spinning saw — lethal.",
    T_ORB: "Click in air for jump.",
    T_DASH_ORB: "Click for dash + jump.",
    T_TELEPORT_ORB: "Link two to teleport.",
    T_BLACK_ORB: "Click for downward slam.",
    T_BLUE_ORB: "Click to flip gravity.",
    T_GREEN_ORB: "Click to jump in same direction.",
    T_PAD: "Auto-jumps (spring).",
    T_BLUE_PAD: "Auto-flips gravity.",
    T_GRAV: "Flips gravity on pass.",
    T_END: "Finish line.",
    T_START: "Player spawn point.",
    T_COIN: "Collect all 3 to verify mastery!",
    T_CHECKPOINT: "Practice-mode save spot.",
    T_MODE_CUBE: "Switch to cube mode.",
    T_MODE_SHIP: "Switch to ship (hold to thrust).",
    T_MODE_BALL: "Switch to ball (click to flip gravity).",
    T_MODE_WAVE: "Switch to wave (hold to go up).",
    T_MODE_UFO: "Switch to UFO (tap to flap).",
    T_MODE_SPIDER: "Switch to spider (teleport to ceiling/floor).",
    T_MODE_MINI: "Shrinks the player to half-size.",
    T_MODE_BIG: "Restores the player to full size.",
    T_MODE_DUAL: "Spawns a second player flipped in gravity. Edit to set spawn row.",
    T_MODE_SOLO: "Returns to a single player.",
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
# Colors
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
C_SPIKE = (255, 60, 70)
C_ORB = (255, 230, 60)
C_DASH_ORB = (255, 80, 220)
C_TELEPORT_ORB = (120, 240, 255)
C_BLACK_ORB = (45, 45, 55)
C_BLUE_ORB = (80, 160, 255)
C_GREEN_ORB = (110, 255, 130)
C_PAD = (255, 165, 0)
C_BLUE_PAD = (90, 170, 255)
C_GPORTAL = (0, 235, 215)
C_END = (90, 255, 115)
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
C_MODE_MINI = (120, 255, 180)
C_MODE_BIG = (255, 180, 120)
C_MODE_DUAL = (255, 110, 160)
C_MODE_SOLO = (160, 230, 255)
C_SPEED_SLOW = (110, 255, 170)
C_SPEED_NORMAL = (110, 190, 255)
C_SPEED_FAST = (255, 225, 100)
C_SPEED_FASTER = (255, 120, 120)
C_START = (255, 255, 255)
C_DECO_CRYSTAL = (180, 220, 255)
C_DECO_PILLAR = (80, 55, 130)
C_DECO_GLOW = (255, 245, 200)
C_CAM_TRIGGER = (255, 225, 80)
C_BG_TRIGGER = (80, 245, 200)
C_MOVE_TRIGGER = (255, 160, 80)
C_COLOR_TRIGGER = (255, 200, 140)
C_PULSE_TRIGGER = (255, 90, 200)
C_ROTATE_TRIGGER = (180, 255, 100)
C_SLAB = (50, 140, 220)
C_SAW = (255, 80, 80)
C_COIN = (255, 215, 0)
C_CHECKPOINT = (120, 255, 180)

TYPE_COLS = {
    T_BLOCK: C_BLOCK,
    T_SLAB: C_SLAB,
    T_SPIKE: C_SPIKE,
    T_HALF_SPIKE: (255, 95, 95),
    T_SAW: C_SAW,
    T_ORB: C_ORB,
    T_DASH_ORB: C_DASH_ORB,
    T_TELEPORT_ORB: C_TELEPORT_ORB,
    T_BLACK_ORB: C_BLACK_ORB,
    T_BLUE_ORB: C_BLUE_ORB,
    T_GREEN_ORB: C_GREEN_ORB,
    T_PAD: C_PAD,
    T_BLUE_PAD: C_BLUE_PAD,
    T_GRAV: C_GPORTAL,
    T_END: C_END,
    T_START: C_START,
    T_COIN: C_COIN,
    T_CHECKPOINT: C_CHECKPOINT,
    T_MODE_CUBE: C_MODE_CUBE,
    T_MODE_SHIP: C_MODE_SHIP,
    T_MODE_BALL: C_MODE_BALL,
    T_MODE_WAVE: C_MODE_WAVE,
    T_MODE_UFO: C_MODE_UFO,
    T_MODE_SPIDER: C_MODE_SPIDER,
    T_MODE_MINI: C_MODE_MINI,
    T_MODE_BIG: C_MODE_BIG,
    T_MODE_DUAL: C_MODE_DUAL,
    T_MODE_SOLO: C_MODE_SOLO,
    T_SPEED_SLOW: C_SPEED_SLOW,
    T_SPEED_NORMAL: C_SPEED_NORMAL,
    T_SPEED_FAST: C_SPEED_FAST,
    T_SPEED_FASTER: C_SPEED_FASTER,
    T_DECO_CRYSTAL: C_DECO_CRYSTAL,
    T_DECO_PILLAR: C_DECO_PILLAR,
    T_DECO_GLOW: C_DECO_GLOW,
    T_CAMERA_TRIGGER: C_CAM_TRIGGER,
    T_BG_TRIGGER: C_BG_TRIGGER,
    T_MOVE_TRIGGER: C_MOVE_TRIGGER,
    T_COLOR_TRIGGER: C_COLOR_TRIGGER,
    T_PULSE_TRIGGER: C_PULSE_TRIGGER,
    T_ROTATE_TRIGGER: C_ROTATE_TRIGGER,
}

PALETTE_CATEGORIES = [
    ("Solid",    [T_BLOCK, T_SLAB]),
    ("Hazards",  [T_SPIKE, T_HALF_SPIKE, T_SAW]),
    ("Interact", [T_ORB, T_DASH_ORB, T_TELEPORT_ORB, T_BLACK_ORB, T_BLUE_ORB,
                  T_GREEN_ORB, T_PAD, T_BLUE_PAD, T_GRAV]),
    ("Portals",  [T_MODE_CUBE, T_MODE_SHIP, T_MODE_BALL, T_MODE_WAVE, T_MODE_UFO,
                  T_MODE_SPIDER, T_MODE_MINI, T_MODE_BIG,
                  T_MODE_DUAL, T_MODE_SOLO]),
    ("Speed",    [T_SPEED_SLOW, T_SPEED_NORMAL, T_SPEED_FAST, T_SPEED_FASTER]),
    ("Deco",     [T_DECO_CRYSTAL, T_DECO_PILLAR, T_DECO_GLOW]),
    ("Triggers", [T_CAMERA_TRIGGER, T_BG_TRIGGER, T_MOVE_TRIGGER, T_COLOR_TRIGGER,
                  T_PULSE_TRIGGER, T_ROTATE_TRIGGER]),
    ("Misc",     [T_START, T_END, T_COIN, T_CHECKPOINT]),
]

ALL_TYPES = [t for _, items in PALETTE_CATEGORIES for t in items]
