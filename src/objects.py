"""Object-type registry — the single source of truth for every level object.

Adding a new object type used to mean touching eight tables spread over
five files (name, tip, colour, palette tab, animated-sprite flag, the
``normalize_object`` field list, the editor's placement defaults, and the
edit panel's parameter readout).  Every one of those is now derived from
one :class:`ObjectSpec` entry in :data:`SPECS`.

A spec declares:

* ``type``        the string stored in level JSON (``constants.T_*``)
* ``name`` / ``tip`` / ``color``   user-facing metadata
* ``category``    which palette tab shows it (``None`` = not placeable)
* ``animated``    whether the sprite renderer bakes ``SPRITE_FRAMES`` frames
* ``fields``      typed, bounded per-object parameters.  The level loader
                  coerces + clamps them, the editor seeds defaults on
                  placement, and the edit panel renders a value box per
                  field — all without type-specific code.

Behaviour (what the player does when it touches the object) still lives
in :mod:`player`; the registry only describes *data*.
"""

from dataclasses import dataclass

from .constants import (
    BG_PRESETS, DASH_SPEED, DASH_TIME, PLAYER_COLORS,
    MODE_CUBE, MODE_SHIP, MODE_BALL, MODE_WAVE, MODE_UFO, MODE_SPIDER,
    MODE_SWING, MODE_ROBOT,
    T_BLOCK, T_SLAB, T_SLOPE, T_SPIKE, T_HALF_SPIKE, T_SAW,
    T_ORB, T_PINK_ORB, T_RED_ORB, T_BLUE_ORB, T_GREEN_ORB, T_BLACK_ORB,
    T_DASH_ORB, T_DASH_ORB_GRAV, T_SPIDER_ORB, T_TELEPORT_ORB,
    T_PAD, T_PINK_PAD, T_RED_PAD, T_BLUE_PAD, T_SPIDER_PAD,
    T_GRAV_UP, T_GRAV_DOWN, T_END, T_START, T_COIN, T_CHECKPOINT,
    T_MODE_CUBE, T_MODE_SHIP, T_MODE_BALL, T_MODE_WAVE, T_MODE_UFO,
    T_MODE_SPIDER, T_MODE_SWING, T_MODE_ROBOT, T_MODE_MINI, T_MODE_BIG,
    T_MODE_DUAL, T_MODE_SOLO,
    T_SPEED_SLOW, T_SPEED_NORMAL, T_SPEED_FAST, T_SPEED_FASTER,
    T_SPEED_FASTEST,
    T_DECO_CRYSTAL, T_DECO_PILLAR, T_DECO_GLOW,
    T_CAMERA_TRIGGER, T_BG_TRIGGER, T_MOVE_TRIGGER, T_COLOR_TRIGGER,
    T_PULSE_TRIGGER, T_ROTATE_TRIGGER, T_FOLLOW_TRIGGER, T_TIME_WARP,
    T_JUMP_PREDICTOR, T_BOT_CHECKPOINT,
    C_BLOCK, C_SLAB, C_SPIKE, C_SAW, C_ORB, C_PINK_ORB, C_RED_ORB,
    C_BLUE_ORB, C_GREEN_ORB, C_BLACK_ORB, C_DASH_ORB, C_DASH_ORB_GRAV,
    C_SPIDER_ORB, C_TELEPORT_ORB, C_PAD, C_PINK_PAD, C_RED_PAD, C_BLUE_PAD,
    C_SPIDER_PAD, C_GPORTAL_UP, C_GPORTAL_DOWN, C_END, C_START, C_COIN,
    C_CHECKPOINT, C_MODE_CUBE, C_MODE_SHIP, C_MODE_BALL, C_MODE_WAVE,
    C_MODE_UFO, C_MODE_SPIDER, C_MODE_SWING, C_MODE_ROBOT, C_MODE_MINI,
    C_MODE_BIG, C_MODE_DUAL, C_MODE_SOLO, C_SPEED_SLOW, C_SPEED_NORMAL,
    C_SPEED_FAST, C_SPEED_FASTER, C_SPEED_FASTEST, C_DECO_CRYSTAL,
    C_DECO_PILLAR, C_DECO_GLOW, C_CAM_TRIGGER, C_BG_TRIGGER, C_MOVE_TRIGGER,
    C_COLOR_TRIGGER, C_PULSE_TRIGGER, C_ROTATE_TRIGGER, C_FOLLOW_TRIGGER,
    C_TIME_WARP, C_JUMP_PREDICTOR, C_BOT_CHECKPOINT,
)


# ---------------------------------------------------------------------------
# Field schema
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Field:
    """One typed, bounded per-object parameter.

    ``kind`` is one of ``int``, ``float``, ``bool``, ``choice``.
    ``default_from`` names another object key (``"x"`` / ``"y"``) whose
    value seeds the field at placement time — used by "target row"
    style parameters that should start at the object's own cell.
    ``persist`` controls JSON output: ``"always"`` writes the field on
    every save, ``"non_default"`` only when it differs from the default.
    ``step`` is the +/- nudge amount the edit panel applies.
    """
    key: str
    label: str
    kind: str
    default: object = 0
    lo: object = None
    hi: object = None
    choices: tuple = ()
    step: float = 1.0
    persist: str = "non_default"
    default_from: str = ""
    decimals: int = 2

    def coerce(self, raw, fallback=None):
        """Return a clamped, typed value or ``fallback`` when unparseable."""
        if fallback is None:
            fallback = self.default
        try:
            if self.kind == "int":
                v = int(round(float(raw)))
            elif self.kind == "float":
                v = float(raw)
            elif self.kind == "bool":
                if isinstance(raw, str):
                    v = raw.strip().lower() in ("1", "true", "yes", "on")
                else:
                    v = bool(raw)
                return v
            elif self.kind == "choice":
                s = str(raw).strip().lower()
                for c in self.choices:
                    if str(c).lower() == s or (s and str(c).lower().startswith(s)):
                        return c
                return fallback
            else:
                return raw
        except (TypeError, ValueError):
            return fallback
        if self.lo is not None and v < self.lo:
            v = self.lo
        if self.hi is not None and v > self.hi:
            v = self.hi
        if self.kind == "float":
            v = round(v, max(self.decimals, 3))
        return v

    def default_for(self, obj):
        if self.default_from and self.default_from in obj:
            return obj[self.default_from]
        return self.default

    def format(self, value):
        """Human-readable rendering for the edit panel."""
        if self.kind == "float":
            return f"{float(value):.{self.decimals}f}"
        if self.kind == "bool":
            return "ON" if value else "OFF"
        return str(value)

    def nudge(self, value, direction):
        """Value after one +/- click. Choice fields cycle, bools flip."""
        if self.kind == "bool":
            return not bool(value)
        if self.kind == "choice":
            try:
                i = self.choices.index(value)
            except ValueError:
                i = 0
            return self.choices[(i + direction) % len(self.choices)]
        return self.coerce(float(value) + direction * self.step)


@dataclass(frozen=True)
class ObjectSpec:
    type: str
    name: str
    tip: str
    color: tuple
    category: str = None
    animated: bool = False
    fields: tuple = ()
    single_instance: bool = False
    editor_only: bool = False

    def field(self, key):
        for f in self.fields:
            if f.key == key:
                return f
        return None


# ---------------------------------------------------------------------------
# Shared field definitions
# ---------------------------------------------------------------------------

_F_TARGET_OID = Field("target_oid", "Target oid", "int", 0, 0, None,
                      persist="always")
_F_DASH = (
    Field("dash_speed", "Dash speed", "float", DASH_SPEED, 1.0, 60.0,
          step=1.0, decimals=1),
    Field("dash_dur", "Dash duration (f)", "int", DASH_TIME, 1, 240,
          step=5),
)
_F_DIR = Field("dir", "Direction", "choice", "auto",
               choices=("auto", "up", "down", "left", "right"))
_F_FREE_MODE = Field("free_mode", "Free camera", "bool", False)

_MODE_CHOICES = (MODE_CUBE, MODE_SHIP, MODE_BALL, MODE_WAVE, MODE_UFO,
                 MODE_SPIDER, MODE_SWING, MODE_ROBOT)

# Category (palette tab) names, in display order.
CAT_BLOCKS = "Blocks"
CAT_HAZARDS = "Hazards"
CAT_ORBS = "Orbs"
CAT_PADS = "Pads"
CAT_PORTALS = "Portals"
CAT_SPEED = "Speed"
CAT_DECO = "Deco"
CAT_TRIGGERS = "Triggers"
CAT_MISC = "Misc"
CATEGORY_ORDER = (CAT_BLOCKS, CAT_HAZARDS, CAT_ORBS, CAT_PADS, CAT_PORTALS,
                  CAT_SPEED, CAT_DECO, CAT_TRIGGERS, CAT_MISC)


def _mode_portal(t, name, tip, col):
    return ObjectSpec(t, name, tip, col, CAT_PORTALS, animated=True,
                      fields=(_F_FREE_MODE,))


_SPEC_LIST = [
    # ---- Blocks ------------------------------------------------------
    ObjectSpec(T_BLOCK, "Block", "Solid. Player lands on top.", C_BLOCK,
               CAT_BLOCKS),
    ObjectSpec(T_SLAB, "Slab", "Half-height block.", C_SLAB, CAT_BLOCKS),
    ObjectSpec(T_SLOPE, "Slope", "1:1 ramp — cube rides up/down without "
               "dying.", C_BLOCK, CAT_BLOCKS),
    # ---- Hazards -----------------------------------------------------
    ObjectSpec(T_SPIKE, "Spike", "Kills on touch.", C_SPIKE, CAT_HAZARDS),
    ObjectSpec(T_HALF_SPIKE, "Half Spike", "Smaller, forgiving spike.",
               (255, 95, 95), CAT_HAZARDS),
    ObjectSpec(T_SAW, "Saw", "Spinning saw — lethal.", C_SAW, CAT_HAZARDS,
               animated=True),
    # ---- Orbs (GD semantics) -----------------------------------------
    ObjectSpec(T_ORB, "Yellow Orb", "Click in air for a medium jump.",
               C_ORB, CAT_ORBS, animated=True),
    ObjectSpec(T_PINK_ORB, "Pink Orb", "Click for a small hop.",
               C_PINK_ORB, CAT_ORBS, animated=True),
    ObjectSpec(T_RED_ORB, "Red Orb", "Click for a big jump.",
               C_RED_ORB, CAT_ORBS, animated=True),
    ObjectSpec(T_BLUE_ORB, "Blue Orb", "Click to flip gravity.",
               C_BLUE_ORB, CAT_ORBS, animated=True),
    ObjectSpec(T_GREEN_ORB, "Green Orb", "Click to jump AND flip gravity.",
               C_GREEN_ORB, CAT_ORBS, animated=True),
    ObjectSpec(T_BLACK_ORB, "Black Orb", "Click to slam downward.",
               C_BLACK_ORB, CAT_ORBS, animated=True),
    ObjectSpec(T_DASH_ORB, "Dash Orb", "Hold to dash in the orb's "
               "direction; release to stop.", C_DASH_ORB, CAT_ORBS,
               animated=True, fields=_F_DASH),
    ObjectSpec(T_DASH_ORB_GRAV, "Gravity Dash Orb", "Hold to dash; gravity "
               "flips when the dash ends.", C_DASH_ORB_GRAV, CAT_ORBS,
               animated=True, fields=_F_DASH),
    ObjectSpec(T_SPIDER_ORB, "Spider Orb", "Click to teleport to the "
               "nearest surface + flip gravity.", C_SPIDER_ORB, CAT_ORBS,
               animated=True, fields=(_F_DIR,)),
    ObjectSpec(T_TELEPORT_ORB, "Teleport Orb", "Link two with the Group "
               "tool to teleport.", C_TELEPORT_ORB, CAT_ORBS, animated=True,
               fields=(Field("group_id", "Group ID", "int", 0, 0, None,
                             persist="always"),
                       Field("dest", "Destination", "bool", False))),
    # ---- Pads --------------------------------------------------------
    ObjectSpec(T_PAD, "Yellow Pad", "Auto medium jump (spring).", C_PAD,
               CAT_PADS),
    ObjectSpec(T_PINK_PAD, "Pink Pad", "Auto small jump.", C_PINK_PAD,
               CAT_PADS),
    ObjectSpec(T_RED_PAD, "Red Pad", "Auto big jump.", C_RED_PAD, CAT_PADS),
    ObjectSpec(T_BLUE_PAD, "Blue Pad", "Auto gravity flip.", C_BLUE_PAD,
               CAT_PADS),
    ObjectSpec(T_SPIDER_PAD, "Spider Pad", "Instantly teleports to the "
               "opposite surface.", C_SPIDER_PAD, CAT_PADS,
               fields=(_F_DIR,)),
    # ---- Portals -----------------------------------------------------
    ObjectSpec(T_GRAV_UP, "Gravity Up Portal", "Sets gravity to up.",
               C_GPORTAL_UP, CAT_PORTALS, animated=True),
    ObjectSpec(T_GRAV_DOWN, "Gravity Down Portal", "Sets gravity to down.",
               C_GPORTAL_DOWN, CAT_PORTALS, animated=True),
    _mode_portal(T_MODE_CUBE, "Cube Portal", "Switch to cube mode.",
                 C_MODE_CUBE),
    _mode_portal(T_MODE_SHIP, "Ship Portal",
                 "Switch to ship (hold to thrust).", C_MODE_SHIP),
    _mode_portal(T_MODE_BALL, "Ball Portal",
                 "Switch to ball (click to flip gravity).", C_MODE_BALL),
    _mode_portal(T_MODE_WAVE, "Wave Portal",
                 "Switch to wave (hold to go up).", C_MODE_WAVE),
    _mode_portal(T_MODE_UFO, "UFO Portal", "Switch to UFO (tap to flap).",
                 C_MODE_UFO),
    _mode_portal(T_MODE_SPIDER, "Spider Portal",
                 "Switch to spider (teleport to ceiling/floor).",
                 C_MODE_SPIDER),
    _mode_portal(T_MODE_SWING, "Swing Portal",
                 "Switch to swing copter (click to flip gravity).",
                 C_MODE_SWING),
    _mode_portal(T_MODE_ROBOT, "Robot Portal",
                 "Switch to robot (hold to thrust; budget refills on "
                 "landing).", C_MODE_ROBOT),
    ObjectSpec(T_MODE_MINI, "Mini Portal", "Shrinks the player to "
               "half-size.", C_MODE_MINI, CAT_PORTALS, animated=True),
    ObjectSpec(T_MODE_BIG, "Big Portal", "Restores the player to full "
               "size.", C_MODE_BIG, CAT_PORTALS, animated=True),
    ObjectSpec(T_MODE_DUAL, "Dual Portal", "Spawns a second player flipped "
               "in gravity.", C_MODE_DUAL, CAT_PORTALS, animated=True,
               fields=(Field("spawn_y", "Spawn row", "int", 0,
                             default_from="y", persist="always"),)),
    ObjectSpec(T_MODE_SOLO, "Solo Portal", "Returns to a single player.",
               C_MODE_SOLO, CAT_PORTALS, animated=True),
    # ---- Speed -------------------------------------------------------
    ObjectSpec(T_SPEED_SLOW, "0.5x Speed", "Slow speed.", C_SPEED_SLOW,
               CAT_SPEED, animated=True),
    ObjectSpec(T_SPEED_NORMAL, "1x Speed", "Normal speed.", C_SPEED_NORMAL,
               CAT_SPEED, animated=True),
    ObjectSpec(T_SPEED_FAST, "2x Speed", "Fast speed.", C_SPEED_FAST,
               CAT_SPEED, animated=True),
    ObjectSpec(T_SPEED_FASTER, "3x Speed", "Faster speed.", C_SPEED_FASTER,
               CAT_SPEED, animated=True),
    ObjectSpec(T_SPEED_FASTEST, "4x Speed", "Fastest speed.",
               C_SPEED_FASTEST, CAT_SPEED, animated=True),
    # ---- Deco --------------------------------------------------------
    ObjectSpec(T_DECO_CRYSTAL, "Crystal", "Decoration only.", C_DECO_CRYSTAL,
               CAT_DECO),
    ObjectSpec(T_DECO_PILLAR, "Pillar", "Decoration only.", C_DECO_PILLAR,
               CAT_DECO),
    ObjectSpec(T_DECO_GLOW, "Glow Dot", "Decoration only.", C_DECO_GLOW,
               CAT_DECO, animated=True),
    # ---- Triggers ----------------------------------------------------
    ObjectSpec(T_CAMERA_TRIGGER, "Camera Trigger", "Pans the camera to the "
               "target row.", C_CAM_TRIGGER, CAT_TRIGGERS,
               fields=(Field("cy", "Target row", "int", 0, default_from="y",
                             persist="always"),)),
    ObjectSpec(T_BG_TRIGGER, "BG Trigger", "Changes the background "
               "preset.", C_BG_TRIGGER, CAT_TRIGGERS,
               fields=(Field("bg", "BG preset", "int", 0, 0,
                             len(BG_PRESETS) - 1, persist="always"),)),
    ObjectSpec(T_MOVE_TRIGGER, "Move Trigger", "Moves target objects to "
               "a destination.", C_MOVE_TRIGGER, CAT_TRIGGERS,
               fields=(_F_TARGET_OID,
                       Field("tx", "Dest x", "int", 0, default_from="x",
                             persist="always"),
                       Field("ty", "Dest y", "int", 0, default_from="y",
                             persist="always"),
                       Field("duration", "Duration (f)", "int", 30, 1, 600,
                             step=5, persist="always"))),
    ObjectSpec(T_COLOR_TRIGGER, "Color Trigger", "Cycles the player "
               "colour.", C_COLOR_TRIGGER, CAT_TRIGGERS,
               fields=(Field("col_idx", "Color index", "int", 0, 0,
                             len(PLAYER_COLORS) - 1, persist="always"),)),
    ObjectSpec(T_PULSE_TRIGGER, "Pulse Trigger", "Screen pulse at a BPM.",
               C_PULSE_TRIGGER, CAT_TRIGGERS,
               fields=(Field("bpm", "BPM", "int", 128, 30, 300, step=4,
                             persist="always"),
                       Field("duration", "Duration (s)", "float", 2.0, 0.1,
                             20.0, step=0.5, decimals=1,
                             persist="always"))),
    ObjectSpec(T_ROTATE_TRIGGER, "Rotate Trigger", "Spins target objects.",
               C_ROTATE_TRIGGER, CAT_TRIGGERS,
               fields=(_F_TARGET_OID,
                       Field("spin", "Spin (deg/s)", "float", 90.0, -3600.0,
                             3600.0, step=15.0, decimals=1,
                             persist="always"),
                       Field("duration", "Duration (s)", "float", 4.0, 0.1,
                             60.0, step=0.5, decimals=1,
                             persist="always"))),
    ObjectSpec(T_FOLLOW_TRIGGER, "Follow Trigger", "Links a target to a "
               "source so it moves with it.", C_FOLLOW_TRIGGER, CAT_TRIGGERS,
               fields=(Field("source_oid", "Source oid", "int", 0, 0, None,
                             persist="always"),
                       _F_TARGET_OID,
                       Field("always_on", "Always on", "bool", False),
                       Field("follow_player", "Follow player", "bool",
                             False),
                       Field("offset_cx", "Offset x", "int", 0, -200, 200),
                       Field("offset_cy", "Offset y", "int", 0, -200, 200))),
    ObjectSpec(T_TIME_WARP, "Time Warp", "Rescales game time (<1 slow-mo, "
               ">1 fast forward).", C_TIME_WARP, CAT_TRIGGERS,
               fields=(Field("factor", "Factor", "float", 1.0, 0.0, 10.0,
                             step=0.1, persist="always"),)),
    # ---- Misc --------------------------------------------------------
    ObjectSpec(T_START, "Start Pos", "Player spawn point.", C_START, CAT_MISC,
               single_instance=True),
    ObjectSpec(T_END, "Finish", "Finish line.", C_END, CAT_MISC,
               animated=True),
    ObjectSpec(T_COIN, "Coin", "Collect all 3 to verify mastery!", C_COIN,
               CAT_MISC, animated=True,
               fields=(Field("coin_id", "Coin id", "int", 0, 0, None,
                             persist="always"),)),
    ObjectSpec(T_JUMP_PREDICTOR, "Jump Probe", "Editor probe: previews the "
               "arc of a click here.", C_JUMP_PREDICTOR, CAT_MISC,
               single_instance=True, editor_only=True,
               fields=(Field("mode", "Sim mode", "choice", MODE_CUBE,
                             choices=_MODE_CHOICES, persist="always"),
                       Field("grav", "Gravity", "choice", 1, choices=(1, -1),
                             persist="always"),
                       Field("mini", "Mini", "bool", False,
                             persist="always"),
                       Field("dx", "Nudge x", "int", 0, -400, 400,
                             persist="always"),
                       Field("dy", "Nudge y", "int", 0, -400, 400,
                             persist="always"),
                       Field("show_hitbox", "Show hitbox", "bool", False))),
    ObjectSpec(T_BOT_CHECKPOINT, "Bot Checkpoint", "Bot waypoint: pulls the "
               "auto-bot search toward this cell.", C_BOT_CHECKPOINT,
               CAT_MISC, editor_only=True),
    # ---- Transient (never placeable) ---------------------------------
    ObjectSpec(T_CHECKPOINT, "Checkpoint", "Practice-mode save spot.",
               C_CHECKPOINT, None, animated=True),
]

SPECS = {s.type: s for s in _SPEC_LIST}


def spec_for(t):
    """Registry lookup; unknown types get a bland placeholder spec."""
    s = SPECS.get(t)
    if s is None:
        s = ObjectSpec(t, str(t), "", (200, 200, 200), None)
    return s


# ---------------------------------------------------------------------------
# Derived tables (kept under their historical names so callers read the
# same way they always did).
# ---------------------------------------------------------------------------
TYPE_NAMES = {s.type: s.name for s in _SPEC_LIST}
TYPE_TIPS = {s.type: s.tip for s in _SPEC_LIST}
TYPE_COLS = {s.type: s.color for s in _SPEC_LIST}
ANIMATED_TYPES = frozenset(s.type for s in _SPEC_LIST if s.animated)
EDITOR_ONLY_TYPES = frozenset(s.type for s in _SPEC_LIST if s.editor_only)

PALETTE_CATEGORIES = [
    (cat, [s.type for s in _SPEC_LIST if s.category == cat])
    for cat in CATEGORY_ORDER
]
ALL_TYPES = [t for _, items in PALETTE_CATEGORIES for t in items]


# ---------------------------------------------------------------------------
# Generic field helpers used by the loader and the editor
# ---------------------------------------------------------------------------

def seed_defaults(obj):
    """Fill in every schema field missing from a freshly placed object."""
    spec = spec_for(obj["t"])
    for f in spec.fields:
        if f.key not in obj:
            obj[f.key] = f.default_for(obj)
    return obj


def normalize_fields(src, out):
    """Copy schema fields from ``src`` into ``out`` (coerced + clamped),
    honouring each field's persistence policy."""
    spec = spec_for(src["t"])
    for f in spec.fields:
        if f.key in src and src[f.key] is not None:
            v = f.coerce(src[f.key], f.default_for(out))
        else:
            v = f.default_for(out)
        if f.persist == "always" or v != f.default_for(out):
            out[f.key] = v
    return out


def get_field_value(obj, f):
    return obj.get(f.key, f.default_for(obj))
