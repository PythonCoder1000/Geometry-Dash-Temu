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

# ---------------------------------------------------------------------------
# Physics tick rate + collision substep granularity
# ---------------------------------------------------------------------------
# All gameplay constants (gravity, jump force, spike arcs, orb timings) are
# tuned for a 60 Hz physics tick. ``PHYSICS_TPS`` is the canonical name —
# play.py / autobot / jump_predictor read this single value so a tps change
# never has to chase down hardcoded ``60``s in five files. The value stays
# 60 because every velocity / acceleration constant is in "px per (1/60)s"
# units; bumping it without rescaling those constants would speed up the
# whole game proportionally.
PHYSICS_TPS = 60

# Maximum motion (px) covered by a single inner collision substep inside
# Player.update / _step_mirror / spider-teleport beam fills. Smaller =
# finer collision detection AND denser hitbox / trail samples (recorded
# once per substep). Was implicitly 4.0; tightening to 1.0 quadruples the
# substep count — collision precision and hitbox-overlay density both go
# 4× without touching any physics tunings, so frame-perfect arcs the
# probe shows are also resolvable at the fine grain.
COLLISION_SUBSTEP_PX = 1.0

# Two-hitbox model. The OUTER rect (Player.rect()) is the player's
# exact visual size and drives hazards / orbs / pads / triggers /
# coins (rotated to match the player's visual angle). The INNER rect
# (Player.solid_hitbox()) is a smaller box centred on the player that
# triggers BLOCK DEATH — if the inner hits a block, the player dies.
# Block resolution still snaps the outer AABB to the surface so the
# player can land cleanly on tops without the inner overlapping. 0.50
# is the GD-standard "central 50% kills" inner; smaller = more
# lenient corner-clipping, larger = stricter.
SOLID_HITBOX_FRACTION = 0.50

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

# Robot mode — held thrust (no instant jump impulse). The thrust is
# applied EACH FRAME the button is held, so the per-tick value sets
# how fast the robot climbs at the same gravity. Net upward
# acceleration per tick = (ROBOT_THRUST - GRAVITY) so 1.45 - 1.0 = 0.45,
# i.e. a 0.45 px/tick² climb when fully thrusting (≈30% of the original
# 1.5 to give a controllable, gentler boost). ROBOT_FLIGHT_SECONDS is
# the budget — fully refilled the moment the robot lands. 1.5 sec at
# the canonical 60 Hz internal physics rate = 90 frames of held
# thrust before the boosters cut out. The hold is also one-shot per
# takeoff: once the player releases the button mid-air, the thruster
# locks until the next landing (Player._robot_thrust_disabled).
ROBOT_THRUST = 1.45
ROBOT_FLIGHT_SECONDS = 1.5

# ---------------------------------------------------------------------------
# Paths — split between app-root (read-only in a packaged build) and the
# per-user writable data dir. Editable dev checkouts still write to the
# repo when `GDT_DEV_LOCAL=1` is set, so the workflow of "clone, run,
# mess with levels" doesn't change. Packaged builds bounce writes to
# the OS's standard per-user data directory.
# ---------------------------------------------------------------------------

def _app_root():
    """Directory of the app's read-only assets. Inside a PyInstaller
    --onefile bundle this is the extracted temp dir (``sys._MEIPASS``).

    For dev checkouts the module's own directory is no longer the app
    root — now that source lives under ``src/`` the repo root sits one
    level up. Walk a couple of levels up looking for the ``assets/``
    folder so the lookup works whether constants.py lives at the repo
    root (legacy) or inside ``src/`` (current layout).
    """
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
        return _app_root()
    if override != "0" and not _is_frozen():
        # Default for dev checkouts: stay in the repo so existing
        # workflows don't silently migrate levels to a new directory.
        return _app_root()
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME",
                              os.path.expanduser("~/.local/share"))
    path = os.path.join(base, "TrigonometrySprint")
    # Migrate from the old "GeometryDashTemu" directory — copy any
    # existing content so pre-rename users don't lose their levels,
    # bot saves, prefs, etc. One-shot: once the new dir exists, the
    # migration is skipped.
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
        # If the user data dir is unwritable (read-only home, CI, etc.)
        # fall back to the app root so at least in-memory state works.
        path = _app_root()
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
T_SLOPE = "slope"
T_SPIKE = "spike"
T_HALF_SPIKE = "half_spike"
T_SAW = "saw"
T_ORB = "orb"
T_DASH_ORB = "dash_orb"
T_TELEPORT_ORB = "teleport_orb"
T_BLACK_ORB = "black_orb"
T_BLUE_ORB = "blue_orb"
T_GREEN_ORB = "green_orb"   # new: reverse-gravity jump
T_SPIDER_ORB = "spider_orb"  # spider-teleport + gravity-flip, available in any mode
T_RED_ORB = "red_orb"       # 2× yellow-orb jump strength
T_PINK_ORB = "pink_orb"     # 0.5× yellow-orb jump strength
T_PAD = "pad"
T_BLUE_PAD = "blue_pad"     # new: gravity-flip pad
T_GRAV_UP = "grav_up"      # blue portal — SETS gravity to up (grav=-1)
T_GRAV_DOWN = "grav_down"  # yellow portal — SETS gravity to down (grav=1)
T_END = "end"
T_START = "start"
T_COIN = "coin"             # new: collectible (3 per level)
# TRANSIENT type — checkpoints are a player-session mechanic placed with
# the C key in practice mode. They are NEVER serialized to level JSON
# (levels.py strips them on load) and are NOT in PALETTE_CATEGORIES, so
# the editor can't stamp them. T_CHECKPOINT lives in constants only so
# render/sfx code can key color/tip/name tables off a single source.
T_CHECKPOINT = "checkpoint"
T_MODE_CUBE = "mode_cube"
T_MODE_SHIP = "mode_ship"
T_MODE_BALL = "mode_ball"
T_MODE_WAVE = "mode_wave"
T_MODE_UFO = "mode_ufo"
T_MODE_SPIDER = "mode_spider"
T_MODE_SWING = "mode_swing"  # GD 2.2 swing copter — click flips gravity
# Robot — cube body, but the jump is replaced by a held thrust. While
# the button is down the robot fires its boosters upward; release lets
# gravity take over. Total flight budget is ROBOT_FLIGHT_SECONDS, fully
# refilled the moment the robot lands. Hold a tiny bit = tiny jump,
# hold longer = bigger jump (capped by the budget).
T_MODE_ROBOT = "mode_robot"
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
# Follow trigger — links a target object's position to a source
# object's, so the target moves whenever the source does (e.g. via a
# move trigger or another follow). The initial offset is preserved.
# When ``always_on`` is True the link activates the moment the
# level starts; otherwise it arms when the player first passes
# through the trigger's cell.
T_FOLLOW_TRIGGER = "follow_trigger"
# Time warp trigger — sets the play loop's time scale. Persistent in the
# same way speed portals are: contact latches the new factor on the
# player and it stays in effect until another T_TIME_WARP overrides it.
# Factor 1.0 = real time; 0.5 = slow-mo (half speed); 2.0 = fast forward.
T_TIME_WARP = "time_warp"
# Editor-only probe: simulates a "click" at the probe's cell in the
# selected game mode and previews the resulting trajectory until the
# simulated player lands or dies. Single-instance, inert at play time
# (the player passes through it — no collision, no interaction).
T_JUMP_PREDICTOR = "jump_predictor"
# Bot checkpoint — author-placed waypoint that pulls the bot search
# toward the marked cell. The closer a candidate is to a checkpoint,
# the higher its score; passed checkpoints are remembered so the bot
# weights successive ones in level order. Inert at play time (no
# collision, no interaction with the live player).
T_BOT_CHECKPOINT = "bot_checkpoint"

# Logical type sets
DECORATION_TYPES = {T_DECO_CRYSTAL, T_DECO_PILLAR, T_DECO_GLOW}
TRIGGER_TYPES = {T_CAMERA_TRIGGER, T_BG_TRIGGER, T_MOVE_TRIGGER, T_COLOR_TRIGGER,
                 T_PULSE_TRIGGER, T_ROTATE_TRIGGER, T_TIME_WARP,
                 T_FOLLOW_TRIGGER}
SOLID_TYPES = {T_BLOCK, T_SLAB}
# Slopes are NOT in SOLID_TYPES because their collision is diagonal:
# the standard rectangular x/y resolution would treat the slope as a
# wall and let the player walk into the slanted face. Player.py
# handles slopes in a dedicated post-pass that snaps the player to
# the diagonal surface; everywhere else can ignore them.
SLOPE_TYPES = {T_SLOPE}
HAZARD_TYPES = {T_SPIKE, T_HALF_SPIKE, T_SAW}
ORB_TYPES = {T_ORB, T_DASH_ORB, T_TELEPORT_ORB, T_BLACK_ORB, T_BLUE_ORB,
             T_GREEN_ORB, T_SPIDER_ORB, T_RED_ORB, T_PINK_ORB}
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
# Gamemode portal types that accept the "free_mode" flag — when set,
# the camera follows the player vertically while that mode is active
# (until another gamemode portal overrides it).
MODE_PORTAL_TYPES = frozenset(MODE_FROM_TYPE.keys())

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
# 11 tiers: the spec listed 9 (easy/medium/hard/insane + 5 demon), but we
# mirror the canonical Geometry Dash ladder which also includes "Auto" (for
# one-button trivial runs) and "Harder" (between Hard and Insane). "Normal"
# is the project's name for the spec's "medium". If you trim the extras to
# match the spec exactly, note that levels._migrate auto-demotes unknown
# tags to "Normal", so dropping "Auto"/"Harder" is safe but loses prior
# level ratings that used those names.
DIFFICULTIES = [
    "Auto", "Easy", "Normal", "Hard", "Harder", "Insane",
    "Easy Demon", "Medium Demon", "Hard Demon",
    "Insane Demon", "Extreme Demon",
]
# Backward-compat alias — old levels saved with the plain "Demon" tag
# migrate to "Hard Demon". levels._migrate maps this at load time.
LEGACY_DEMON_TARGET = "Hard Demon"

# Only this signed-in username can flip a published level's `verified`
# flag and stamp its official difficulty. Every other user who beats a
# level still gets their attempts / best_progress / coins tracked, but
# the ✓ badge and the canonical rating are locked to the admin account.
ADMIN_USERNAME = "TopRob"

DIFFICULTY_COLORS = {
    "Auto":           (180, 255, 180),
    "Easy":           (100, 230, 255),
    "Normal":         (100, 255, 120),
    "Hard":           (255, 220, 80),
    "Harder":         (255, 150, 60),
    "Insane":         (255, 80, 80),
    # Demon tiers — progressive purple→pink→red gradient so the rank
    # reads at-a-glance even without reading the full label.
    "Easy Demon":     (200, 120, 255),
    "Medium Demon":   (230, 80, 230),
    "Hard Demon":     (255, 40, 220),
    "Insane Demon":   (255, 30, 140),
    "Extreme Demon":  (255, 0, 60),
    # Legacy alias kept so a level JSON still in flight with "Demon"
    # renders with a sane color while being migrated on next save.
    "Demon":          (255, 40, 220),
}

TYPE_NAMES = {
    T_BLOCK: "Block",
    T_SLAB: "Slab",
    T_SLOPE: "Slope",
    T_SPIKE: "Spike",
    T_HALF_SPIKE: "Half Spike",
    T_SAW: "Saw",
    T_ORB: "Jump Orb",
    T_DASH_ORB: "Dash Orb",
    T_TELEPORT_ORB: "Teleport Orb",
    T_BLACK_ORB: "Black Orb",
    T_BLUE_ORB: "Blue Orb",
    T_GREEN_ORB: "Green Orb",
    T_SPIDER_ORB: "Spider Orb",
    T_RED_ORB: "Red Orb",
    T_PINK_ORB: "Pink Orb",
    T_PAD: "Jump Pad",
    T_BLUE_PAD: "Blue Pad",
    T_GRAV_UP: "Gravity Up Portal",
    T_GRAV_DOWN: "Gravity Down Portal",
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
    T_MODE_SWING: "Swing Portal",
    T_MODE_MINI: "Mini Portal",
    T_MODE_BIG: "Big Portal",
    T_MODE_DUAL: "Dual Portal",
    T_MODE_SOLO: "Solo Portal",
    T_MODE_ROBOT: "Robot Portal",
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
    T_FOLLOW_TRIGGER: "Follow Trigger",
    T_TIME_WARP: "Time Warp",
    T_JUMP_PREDICTOR: "Jump Probe",
    T_BOT_CHECKPOINT: "Bot Checkpoint",
}

TYPE_TIPS = {
    T_BLOCK: "Solid. Player lands on top.",
    T_SLAB: "Half-height block.",
    T_SLOPE: "1:1 ramp — cube rides up/down without dying.",
    T_SPIKE: "Kills on touch.",
    T_HALF_SPIKE: "Smaller, forgiving spike.",
    T_SAW: "Spinning saw — lethal.",
    T_ORB: "Click in air for jump.",
    T_DASH_ORB: "Click for dash + jump.",
    T_TELEPORT_ORB: "Link two to teleport.",
    T_BLACK_ORB: "Click for downward slam.",
    T_BLUE_ORB: "Click to flip gravity.",
    T_GREEN_ORB: "Click to jump in same direction.",
    T_SPIDER_ORB: "Click to teleport to nearest surface + flip gravity.",
    T_RED_ORB: "Click for a tall jump (2× yellow orb).",
    T_PINK_ORB: "Click for a tiny jump (½× yellow orb).",
    T_PAD: "Auto-jumps (spring).",
    T_BLUE_PAD: "Auto-flips gravity.",
    T_GRAV_UP: "Sets gravity to up.",
    T_GRAV_DOWN: "Sets gravity to down.",
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
    T_MODE_SWING: "Switch to swing copter (click to flip gravity).",
    T_MODE_ROBOT: "Switch to robot (hold to thrust diagonally; "
                  "2s flight budget refills on landing).",
    T_MODE_MINI: "Shrinks the player to half-size.",
    T_MODE_BIG: "Restores the player to full size.",
    T_MODE_DUAL: "Spawns a second player flipped in gravity. Edit to set spawn row.",
    T_MODE_SOLO: "Returns to a single player.",
    T_TIME_WARP: "Time warp: rescales the play loop until the next "
                 "warp trigger. <1 = slow-mo, >1 = fast forward.",
    T_FOLLOW_TRIGGER: "Links a target object to a source: target "
                      "moves whenever the source does. Toggle "
                      "'always on' in the edit panel to bind the "
                      "pair at level start instead of on contact.",
    T_JUMP_PREDICTOR: "Editor probe: previews the arc of a click here. "
                      "Replaces F3 debug HUD while placed.",
    T_BOT_CHECKPOINT: "Bot waypoint: pulls the auto-bot search toward "
                      "this cell. Place a chain to dictate the route.",
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
C_SPIDER_ORB = (190, 120, 255)
C_RED_ORB = (255, 70, 70)
C_PINK_ORB = (255, 150, 210)
C_PAD = (255, 165, 0)
C_BLUE_PAD = (90, 170, 255)
C_GPORTAL_UP = (80, 160, 255)     # blue — gravity-up portal
C_GPORTAL_DOWN = (255, 215, 70)   # yellow — gravity-down portal
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
C_FOLLOW_TRIGGER = (120, 220, 200)
C_TIME_WARP = (200, 140, 255)
C_SLAB = (50, 140, 220)
C_SAW = (255, 80, 80)
C_COIN = (255, 215, 0)
C_CHECKPOINT = (120, 255, 180)

TYPE_COLS = {
    T_BLOCK: C_BLOCK,
    T_SLAB: C_SLAB,
    T_SLOPE: C_BLOCK,
    T_SPIKE: C_SPIKE,
    T_HALF_SPIKE: (255, 95, 95),
    T_SAW: C_SAW,
    T_ORB: C_ORB,
    T_DASH_ORB: C_DASH_ORB,
    T_TELEPORT_ORB: C_TELEPORT_ORB,
    T_BLACK_ORB: C_BLACK_ORB,
    T_BLUE_ORB: C_BLUE_ORB,
    T_GREEN_ORB: C_GREEN_ORB,
    T_SPIDER_ORB: C_SPIDER_ORB,
    T_RED_ORB: C_RED_ORB,
    T_PINK_ORB: C_PINK_ORB,
    T_PAD: C_PAD,
    T_BLUE_PAD: C_BLUE_PAD,
    T_GRAV_UP: C_GPORTAL_UP,
    T_GRAV_DOWN: C_GPORTAL_DOWN,
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
    T_MODE_SWING: C_MODE_SWING,
    T_MODE_ROBOT: C_MODE_ROBOT,
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
    T_FOLLOW_TRIGGER: C_FOLLOW_TRIGGER,
    T_TIME_WARP: C_TIME_WARP,
    T_JUMP_PREDICTOR: (255, 235, 120),
    T_BOT_CHECKPOINT: (120, 230, 255),
}

PALETTE_CATEGORIES = [
    ("Solid",    [T_BLOCK, T_SLAB, T_SLOPE]),
    ("Hazards",  [T_SPIKE, T_HALF_SPIKE, T_SAW]),
    ("Interact", [T_ORB, T_RED_ORB, T_PINK_ORB, T_DASH_ORB, T_TELEPORT_ORB,
                  T_BLACK_ORB, T_BLUE_ORB, T_GREEN_ORB, T_SPIDER_ORB,
                  T_PAD, T_BLUE_PAD, T_GRAV_UP, T_GRAV_DOWN]),
    ("Portals",  [T_MODE_CUBE, T_MODE_SHIP, T_MODE_BALL, T_MODE_WAVE, T_MODE_UFO,
                  T_MODE_SPIDER, T_MODE_SWING, T_MODE_ROBOT, T_MODE_MINI,
                  T_MODE_BIG, T_MODE_DUAL, T_MODE_SOLO]),
    ("Speed",    [T_SPEED_SLOW, T_SPEED_NORMAL, T_SPEED_FAST, T_SPEED_FASTER]),
    ("Deco",     [T_DECO_CRYSTAL, T_DECO_PILLAR, T_DECO_GLOW]),
    ("Triggers", [T_CAMERA_TRIGGER, T_BG_TRIGGER, T_MOVE_TRIGGER, T_COLOR_TRIGGER,
                  T_PULSE_TRIGGER, T_ROTATE_TRIGGER, T_FOLLOW_TRIGGER,
                  T_TIME_WARP]),
    ("Misc",     [T_START, T_END, T_COIN, T_JUMP_PREDICTOR, T_BOT_CHECKPOINT]),
]

ALL_TYPES = [t for _, items in PALETTE_CATEGORIES for t in items]
