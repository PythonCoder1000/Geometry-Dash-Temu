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
    BG_PRESETS,
    MODE_CUBE, MODE_SHIP, MODE_BALL, MODE_WAVE, MODE_UFO, MODE_SPIDER,
    MODE_SWING, MODE_ROBOT,
    T_BLOCK, T_SLAB, T_SLOPE, T_SPIKE, T_HALF_SPIKE, T_SAW,
    T_ORB, T_PINK_ORB, T_RED_ORB, T_BLUE_ORB, T_GREEN_ORB, T_BLACK_ORB,
    T_DASH_ORB, T_DASH_ORB_GRAV, T_SPIDER_ORB, T_TELEPORT_ORB,
    T_TELEPORT_PORTAL,
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
    T_BLACKOUT_TRIGGER,
    T_SPAWN_TRIGGER, T_TOGGLE_TRIGGER, T_STOP_TRIGGER, T_SEQUENCE_TRIGGER,
    T_SCALE_TRIGGER, T_ALPHA_TRIGGER,
    T_ZOOM_TRIGGER, T_CAM_OFFSET_TRIGGER, T_CAM_ROTATE_TRIGGER,
    T_CAM_EDGE_TRIGGER, T_CAM_GUIDE_TRIGGER,
    T_GRAYSCALE_TRIGGER, T_SEPIA_TRIGGER, T_INVERT_TRIGGER, T_HUE_TRIGGER,
    T_PIXELATE_TRIGGER,
    T_JUMP_PREDICTOR, T_BOT_CHECKPOINT, T_DASH_STOP,
    T_JUMP_BLOCK, T_WAVE_BLOCK, T_BONK_BLOCK,
    T_ITEM_PICKUP, T_COUNT_TRIGGER, T_INSTANT_COUNT_TRIGGER,
    T_ITEM_EDIT_TRIGGER, T_ITEM_COMP_TRIGGER, T_ITEM_PERS_TRIGGER,
    T_TIME_TRIGGER, T_TIME_EVENT_TRIGGER, T_ITEM_COUNTER,
    T_KEYFRAME, T_KEYFRAME_TRIGGER,
    C_BLOCK, C_SLAB, C_SPIKE, C_SAW, C_ORB, C_PINK_ORB, C_RED_ORB,
    C_BLUE_ORB, C_GREEN_ORB, C_BLACK_ORB, C_DASH_ORB, C_DASH_ORB_GRAV,
    C_SPIDER_ORB, C_TELEPORT_ORB, C_TELEPORT_PORTAL,
    C_PAD, C_PINK_PAD, C_RED_PAD, C_BLUE_PAD,
    C_SPIDER_PAD, C_GPORTAL_UP, C_GPORTAL_DOWN, C_END, C_START, C_COIN,
    C_CHECKPOINT, C_MODE_CUBE, C_MODE_SHIP, C_MODE_BALL, C_MODE_WAVE,
    C_MODE_UFO, C_MODE_SPIDER, C_MODE_SWING, C_MODE_ROBOT, C_MODE_MINI,
    C_MODE_BIG, C_MODE_DUAL, C_MODE_SOLO, C_SPEED_SLOW, C_SPEED_NORMAL,
    C_SPEED_FAST, C_SPEED_FASTER, C_SPEED_FASTEST, C_DECO_CRYSTAL,
    C_DECO_PILLAR, C_DECO_GLOW, C_CAM_TRIGGER, C_BG_TRIGGER, C_MOVE_TRIGGER,
    C_COLOR_TRIGGER, C_PULSE_TRIGGER, C_ROTATE_TRIGGER, C_FOLLOW_TRIGGER,
    C_BLACKOUT_TRIGGER,
    C_TIME_WARP, C_JUMP_PREDICTOR, C_BOT_CHECKPOINT, C_DASH_STOP,
    C_JUMP_BLOCK, C_WAVE_BLOCK, C_BONK_BLOCK,
    C_ZOOM_TRIGGER, C_CAM_OFFSET_TRIGGER, C_CAM_ROTATE_TRIGGER,
    C_CAM_EDGE_TRIGGER, C_CAM_GUIDE_TRIGGER,
    C_GRAYSCALE_TRIGGER, C_SEPIA_TRIGGER, C_INVERT_TRIGGER, C_HUE_TRIGGER,
    C_PIXELATE_TRIGGER,
    C_ITEM_PICKUP, C_COUNT_TRIGGER, C_ITEM_EDIT_TRIGGER, C_ITEM_COMP_TRIGGER,
    C_TIME_TRIGGER, C_ITEM_COUNTER, C_KEYFRAME, C_KEYFRAME_TRIGGER,
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
        try:
            base = float(value)
        except (TypeError, ValueError):
            base = float(self.default) if isinstance(self.default, (int, float)) else 0.0
        return self.coerce(base + direction * self.step)


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
    # ``invisible`` is a universal per-instance flag rather than a schema
    # Field, so a type that should start hidden declares it here and
    # ``seed_defaults`` writes it on placement.
    invisible_by_default: bool = False

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
# Orbs fire once per attempt by default (historical behaviour every
# existing level is built around).  Turning this on makes an orb
# re-triggerable, matching real GD "orb spam" / bunny-hopping.
_F_MULTI_ACTIVATE = Field("multi_activate", "Multi Activate", "bool", False)
_F_DIR = Field("dir", "Direction", "choice", "auto",
               choices=("auto", "up", "down", "left", "right"))
_F_FREE_MODE = Field("free_mode", "Free camera", "bool", False)
# Checkpoint 5 (editor reference "Key trigger concepts"): every trigger
# can target a whole group instead of/alongside a single oid, be fired
# only by a Spawn/Sequence trigger instead of player touch, and either
# fire once (default) or every touch (multi-activate, reusing the orb
# field of the same name/meaning).
# Deliberately NOT named "group": levels.get_groups() reads a bare
# "group" int as legacy group MEMBERSHIP (which group this object
# belongs to). A trigger's *target* is a different concept (which group
# it ACTS ON) -- if it also called itself "group" a Spawn/Toggle/
# Sequence trigger without an explicit "groups" list would become a
# member of its own target group and self-refire without end the first
# time it targeted that group (see triggers.py's TriggerMixin.
# _resolve_targets docstring-comment for the mechanics).
_F_GROUP = Field("target_group", "Target group", "int", 0, 0, None,
                 persist="always")
_F_SPAWN_TRIGGERED = Field("spawn_triggered", "Spawn Triggered (no touch)",
                           "bool", False)
_F_EASING = Field("easing", "Easing", "choice", "linear",
                  choices=("linear", "ease_in", "ease_out", "ease_in_out"),
                  persist="always")
_TRIGGER_COMMON_FIELDS = (_F_GROUP, _F_SPAWN_TRIGGERED, _F_MULTI_ACTIVATE)
# Checkpoint 7 (editor reference Sec 4, "Item/counter/timer system"): the
# numbered item id every item-logic trigger reads/writes. Deliberately its
# own field (not reusing _F_GROUP) -- an item id and a target group id are
# different id-spaces that only happen to both be small ints.
_F_ITEM_ID = Field("item_id", "Item id", "int", 0, 0, None, persist="always")
_F_COMPARATOR = Field("comparator", "Comparator", "choice", ">=",
                      choices=(">=", "<=", "==", "!=", ">", "<"),
                      persist="always")
# Checkpoint 8 (simplified keyframe system): which animation a Keyframe
# belongs to / which animation a Keyframe Animation Trigger plays back.
# Its own id-space, like _F_ITEM_ID -- deliberately not _F_GROUP, since an
# animation id and a target group id mean different things that only
# happen to both be small ints.
_F_ANIMATION_ID = Field("animation_id", "Animation id", "int", 0, 0, None,
                        persist="always")
# Checkpoint 6: camera/screen-effect triggers act on the camera or the
# whole screen, not on a targeted group of objects, so they skip
# _F_GROUP but keep the spawn-triggered/multi-activate concepts.
_CAMERA_COMMON_FIELDS = (_F_SPAWN_TRIGGERED, _F_MULTI_ACTIVATE)

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
# Split out of CAT_TRIGGERS (Checkpoint 9, editor reference §5's category
# list) purely for editor-tab organization — same ObjectSpec machinery,
# just a less overloaded single "Triggers" tab.
CAT_CAMERA = "Camera"
CAT_ITEMS = "Items"
CAT_MISC = "Misc"
CAT_EDITOR_UTILS = "Utils"
CATEGORY_ORDER = (CAT_BLOCKS, CAT_HAZARDS, CAT_ORBS, CAT_PADS, CAT_PORTALS,
                  CAT_SPEED, CAT_DECO, CAT_TRIGGERS, CAT_CAMERA, CAT_ITEMS,
                  CAT_MISC, CAT_EDITOR_UTILS)


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
               C_ORB, CAT_ORBS, animated=True,
               fields=(_F_MULTI_ACTIVATE,)),
    ObjectSpec(T_PINK_ORB, "Pink Orb", "Click for a small hop.",
               C_PINK_ORB, CAT_ORBS, animated=True,
               fields=(_F_MULTI_ACTIVATE,)),
    ObjectSpec(T_RED_ORB, "Red Orb", "Click for a big jump.",
               C_RED_ORB, CAT_ORBS, animated=True,
               fields=(_F_MULTI_ACTIVATE,)),
    ObjectSpec(T_BLUE_ORB, "Blue Orb", "Click to flip gravity.",
               C_BLUE_ORB, CAT_ORBS, animated=True,
               fields=(_F_MULTI_ACTIVATE,)),
    ObjectSpec(T_GREEN_ORB, "Green Orb", "Click to jump AND flip gravity.",
               C_GREEN_ORB, CAT_ORBS, animated=True,
               fields=(_F_MULTI_ACTIVATE,)),
    ObjectSpec(T_BLACK_ORB, "Black Orb", "Click to slam downward.",
               C_BLACK_ORB, CAT_ORBS, animated=True,
               fields=(_F_MULTI_ACTIVATE,)),
    ObjectSpec(T_DASH_ORB, "Dash Orb", "Click to dash in the orb's "
               "direction; dashes until an S Block stops it.", C_DASH_ORB,
               CAT_ORBS, animated=True, fields=(_F_MULTI_ACTIVATE,)),
    ObjectSpec(T_DASH_ORB_GRAV, "Gravity Dash Orb", "Click to dash until an "
               "S Block stops it; gravity flips when the dash ends.",
               C_DASH_ORB_GRAV, CAT_ORBS, animated=True,
               fields=(_F_MULTI_ACTIVATE,)),
    ObjectSpec(T_SPIDER_ORB, "Spider Orb", "Click to teleport to the "
               "nearest surface + flip gravity.", C_SPIDER_ORB, CAT_ORBS,
               animated=True, fields=(_F_DIR, _F_MULTI_ACTIVATE)),
    ObjectSpec(T_TELEPORT_ORB, "Teleport Orb", "Link two with the Group "
               "tool to teleport.", C_TELEPORT_ORB, CAT_ORBS, animated=True,
               fields=(Field("group_id", "Group ID", "int", 0, 0, None,
                             persist="always"),
                       Field("dest", "Destination", "bool", False),
                       _F_MULTI_ACTIVATE)),
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
    ObjectSpec(T_TELEPORT_PORTAL, "Teleport Portal", "Link two with the "
               "Group tool. Teleports instantly on touch — no click "
               "needed.", C_TELEPORT_PORTAL, CAT_PORTALS, animated=True,
               fields=(Field("group_id", "Group ID", "int", 0, 0, None,
                             persist="always"),
                       Field("dest", "Destination", "bool", False))),
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
               "target row, freezes it in place (Static), or resumes "
               "following the player (Follow). Pan eases smoothly over "
               "Duration.", C_CAM_TRIGGER, CAT_TRIGGERS,
               fields=(Field("cam_mode", "Mode", "choice", "pan",
                             choices=("pan", "static", "follow"),
                             persist="always"),
                       Field("cy", "Target row", "int", 0, default_from="y",
                             persist="always"),
                       Field("duration", "Duration (s)", "float", 1.0, 0.0,
                             10.0, step=0.1, decimals=2,
                             persist="always"),
                       *_TRIGGER_COMMON_FIELDS)),
    ObjectSpec(T_BG_TRIGGER, "BG Trigger", "Changes the background "
               "preset.", C_BG_TRIGGER, CAT_TRIGGERS,
               fields=(Field("bg", "BG preset", "int", 0, 0,
                             len(BG_PRESETS) - 1, persist="always"),
                       *_TRIGGER_COMMON_FIELDS)),
    ObjectSpec(T_MOVE_TRIGGER, "Move Trigger", "Moves target objects (or a "
               "whole Group) to a destination.", C_MOVE_TRIGGER,
               CAT_TRIGGERS,
               fields=(_F_TARGET_OID,
                       Field("tx", "Dest x", "int", 0, default_from="x",
                             persist="always"),
                       Field("ty", "Dest y", "int", 0, default_from="y",
                             persist="always"),
                       Field("duration", "Duration (f)", "int", 30, 1, 600,
                             step=5, persist="always"),
                       Field("show_ghost", "Show ghost (editor)", "bool",
                             False, persist="non_default"),
                       _F_EASING, *_TRIGGER_COMMON_FIELDS)),
    ObjectSpec(T_COLOR_TRIGGER, "Color Trigger", "Sets the player's color "
               "to the given color channel (edit the channel's own RGB "
               "from the panel below to restyle every user of it at "
               "once).", C_COLOR_TRIGGER, CAT_TRIGGERS,
               fields=(Field("channel", "Channel", "int", 0, 0, None,
                             persist="always"),
                       *_TRIGGER_COMMON_FIELDS)),
    ObjectSpec(T_PULSE_TRIGGER, "Pulse Trigger", "Screen pulse at a BPM, "
               "optionally tinted to a color channel (-1 = white).",
               C_PULSE_TRIGGER, CAT_TRIGGERS,
               fields=(Field("bpm", "BPM", "int", 128, 30, 300, step=4,
                             persist="always"),
                       Field("duration", "Duration (s)", "float", 2.0, 0.1,
                             20.0, step=0.5, decimals=1,
                             persist="always"),
                       Field("channel", "Channel (-1=white)", "int", -1, -1,
                             None, persist="always"),
                       *_TRIGGER_COMMON_FIELDS)),
    ObjectSpec(T_ROTATE_TRIGGER, "Rotate Trigger", "Spins target objects "
               "(or a whole Group).", C_ROTATE_TRIGGER, CAT_TRIGGERS,
               fields=(_F_TARGET_OID,
                       Field("spin", "Spin (deg/s)", "float", 90.0, -3600.0,
                             3600.0, step=15.0, decimals=1,
                             persist="always"),
                       Field("duration", "Duration (s)", "float", 4.0, 0.1,
                             60.0, step=0.5, decimals=1,
                             persist="always"),
                       _F_EASING, *_TRIGGER_COMMON_FIELDS)),
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
                             step=0.1, persist="always"),
                       *_TRIGGER_COMMON_FIELDS)),
    ObjectSpec(T_BLACKOUT_TRIGGER, "Blackout Trigger", "Fades the whole "
               "screen to solid black (or back to clear) — hides "
               "everything, including the player and its trail.",
               C_BLACKOUT_TRIGGER, CAT_TRIGGERS,
               fields=(Field("state", "Go dark", "bool", True,
                             persist="always"),
                       Field("duration", "Duration (s)", "float", 1.0, 0.0,
                             10.0, step=0.1, decimals=2,
                             persist="always"),
                       *_TRIGGER_COMMON_FIELDS)),
    ObjectSpec(T_SPAWN_TRIGGER, "Spawn Trigger", "Fires every trigger in "
               "the target group after Delay seconds — the 'glue' trigger "
               "that chains sequences together.", (150, 220, 255),
               CAT_TRIGGERS,
               fields=(_F_GROUP,
                       Field("delay", "Delay (s)", "float", 0.0, 0.0, 60.0,
                             step=0.1, decimals=2, persist="always"),
                       _F_MULTI_ACTIVATE)),
    ObjectSpec(T_TOGGLE_TRIGGER, "Toggle Trigger", "Enables or disables "
               "every trigger in the target group (disabled triggers "
               "ignore touch and Spawn until re-enabled).",
               (255, 200, 90), CAT_TRIGGERS,
               fields=(_F_GROUP,
                       Field("state", "Enable", "bool", True,
                             persist="always"),
                       _F_MULTI_ACTIVATE)),
    ObjectSpec(T_STOP_TRIGGER, "Stop Trigger", "Halts any in-progress Move/"
               "Rotate/Scale/Alpha animation on the target group, freezing "
               "it where it currently is.", (255, 120, 120), CAT_TRIGGERS,
               fields=(_F_GROUP, _F_MULTI_ACTIVATE)),
    ObjectSpec(T_SEQUENCE_TRIGGER, "Sequence Trigger", "Fires up to four "
               "groups in order, Step Delay seconds apart.",
               (200, 160, 255), CAT_TRIGGERS,
               fields=(_F_GROUP,
                       Field("target_group2", "Group 2", "int", 0, 0, None,
                             persist="always"),
                       Field("target_group3", "Group 3", "int", 0, 0, None,
                             persist="always"),
                       Field("target_group4", "Group 4", "int", 0, 0, None,
                             persist="always"),
                       Field("step_delay", "Step Delay (s)", "float", 0.5,
                             0.0, 30.0, step=0.1, decimals=2,
                             persist="always"),
                       _F_MULTI_ACTIVATE)),
    ObjectSpec(T_SCALE_TRIGGER, "Scale Trigger", "Resizes the target group "
               "(optionally per-axis) over Duration.", (120, 255, 180),
               CAT_TRIGGERS,
               fields=(Field("sx", "Scale X", "float", 1.0, 0.1, 8.0,
                             step=0.05, decimals=2, persist="always"),
                       Field("sy", "Scale Y", "float", 1.0, 0.1, 8.0,
                             step=0.05, decimals=2, persist="always"),
                       Field("duration", "Duration (s)", "float", 0.5, 0.0,
                             30.0, step=0.1, decimals=2, persist="always"),
                       _F_EASING, *_TRIGGER_COMMON_FIELDS)),
    ObjectSpec(T_ALPHA_TRIGGER, "Alpha Trigger", "Fades the target group's "
               "transparency over Duration.", (200, 200, 200), CAT_TRIGGERS,
               fields=(Field("alpha", "Alpha", "float", 1.0, 0.0, 1.0,
                             step=0.05, decimals=2, persist="always"),
                       Field("duration", "Duration (s)", "float", 0.5, 0.0,
                             30.0, step=0.1, decimals=2, persist="always"),
                       _F_EASING, *_TRIGGER_COMMON_FIELDS)),
    # ---- Item / counter / timer family (Checkpoint 7) -----------------
    ObjectSpec(T_COUNT_TRIGGER, "Count Trigger", "Continuously watches an "
               "item id; the FIRST tick the comparison becomes true, fires "
               "the target group once (re-arms if the comparison later "
               "goes false again).", C_COUNT_TRIGGER, CAT_ITEMS,
               fields=(_F_GROUP, _F_ITEM_ID, _F_COMPARATOR,
                       Field("value", "Value", "float", 0.0, None, None,
                             persist="always"),
                       _F_MULTI_ACTIVATE)),
    ObjectSpec(T_INSTANT_COUNT_TRIGGER, "Instant Count Trigger", "Checks an "
               "item id against Value once, the instant it's touched/"
               "spawned (no re-arming) — fires the target group if true.",
               C_COUNT_TRIGGER, CAT_ITEMS,
               fields=(_F_GROUP, _F_ITEM_ID, _F_COMPARATOR,
                       Field("value", "Value", "float", 0.0, None, None,
                             persist="always"),
                       _F_MULTI_ACTIVATE)),
    ObjectSpec(T_ITEM_EDIT_TRIGGER, "Item Edit Trigger", "Applies Operation "
               "(with Operand, or a second item id) to Item id's stored "
               "value.", C_ITEM_EDIT_TRIGGER, CAT_ITEMS,
               fields=(_F_ITEM_ID,
                       Field("operation", "Operation", "choice", "add",
                             choices=("add", "subtract", "multiply",
                                      "divide", "set"), persist="always"),
                       Field("operand", "Operand", "float", 1.0, None, None,
                             persist="always"),
                       Field("operand_item_id", "Operand item id (0=none)",
                             "int", 0, 0, None, persist="always"),
                       *_TRIGGER_COMMON_FIELDS)),
    ObjectSpec(T_ITEM_COMP_TRIGGER, "Item Comp Trigger", "Compares Item id "
               "against Value (or Compare item id, if nonzero); fires the "
               "target group if true.", C_ITEM_COMP_TRIGGER, CAT_ITEMS,
               fields=(_F_GROUP, _F_ITEM_ID, _F_COMPARATOR,
                       Field("value", "Value", "float", 0.0, None, None,
                             persist="always"),
                       Field("compare_item_id", "Compare item id (0=none)",
                             "int", 0, 0, None, persist="always"),
                       _F_MULTI_ACTIVATE)),
    ObjectSpec(T_ITEM_PERS_TRIGGER, "Item Pers Trigger", "Snapshots Item "
               "id's current value into persistent storage — the next "
               "retry/respawn re-seeds that item from the snapshot instead "
               "of resetting it to 0.", (255, 235, 255), CAT_ITEMS,
               fields=(_F_ITEM_ID, _F_MULTI_ACTIVATE)),
    ObjectSpec(T_TIME_TRIGGER, "Timer Trigger", "Starts, stops, or resets a "
               "numbered timer (seconds, counts up while running).",
               C_TIME_TRIGGER, CAT_ITEMS,
               fields=(Field("timer_id", "Timer id", "int", 0, 0, None,
                             persist="always"),
                       Field("action", "Action", "choice", "start",
                             choices=("start", "stop", "reset"),
                             persist="always"),
                       *_TRIGGER_COMMON_FIELDS)),
    ObjectSpec(T_TIME_EVENT_TRIGGER, "Time Event Trigger", "Continuously "
               "watches a timer; the FIRST tick it crosses Threshold "
               "seconds, fires the target group once.", C_TIME_TRIGGER,
               CAT_ITEMS,
               fields=(_F_GROUP,
                       Field("timer_id", "Timer id", "int", 0, 0, None,
                             persist="always"),
                       Field("threshold", "Threshold (s)", "float", 5.0, 0.0,
                             None, step=0.5, decimals=2, persist="always"),
                       _F_MULTI_ACTIVATE)),
    # ---- Keyframe animation (Checkpoint 8, simplified) -----------------
    # A Keyframe is data, not a trigger: place several sharing one
    # Animation id, give each a distinct Order (ascending = playback
    # order -- explicit, not inferred from placement position, so
    # reordering never requires moving the object), and a Keyframe
    # Animation Trigger with the same Animation id plays a target group
    # through them in Order, one segment per keyframe.
    ObjectSpec(T_KEYFRAME, "Keyframe", "Marks one pose (position/rotation/"
               "scale) in an animation. Give matching Keyframes the same "
               "Animation id; Order picks playback sequence (ascending).",
               C_KEYFRAME, CAT_TRIGGERS,
               fields=(_F_ANIMATION_ID,
                       Field("order", "Order", "int", 0, 0, None,
                             persist="always"),
                       Field("tx", "Pos x", "int", 0, default_from="x",
                             persist="always"),
                       Field("ty", "Pos y", "int", 0, default_from="y",
                             persist="always"),
                       Field("rotation", "Rotation (deg)", "float", 0.0,
                             None, None, step=15.0, decimals=1,
                             persist="always"),
                       Field("sx", "Scale X", "float", 1.0, 0.1, 8.0,
                             step=0.05, decimals=2, persist="always"),
                       Field("sy", "Scale Y", "float", 1.0, 0.1, 8.0,
                             step=0.05, decimals=2, persist="always"),
                       Field("time", "Time (s, Time mode)", "float", 0.5,
                             0.0, 30.0, step=0.1, decimals=2,
                             persist="always"),
                       _F_EASING)),
    ObjectSpec(T_KEYFRAME_TRIGGER, "Keyframe Animation Trigger", "Plays "
               "the target group through every Keyframe sharing Animation "
               "id, in Order — position moves relative to the group's "
               "current formation, rotation/scale snap the whole group to "
               "each keyframe's absolute value.", C_KEYFRAME_TRIGGER,
               CAT_TRIGGERS,
               # NOTE: don't add _F_GROUP here -- _TRIGGER_COMMON_FIELDS
               # already includes it. (Scale/Alpha Trigger, Checkpoint 5,
               # list it a second time on top of *_TRIGGER_COMMON_FIELDS,
               # which duplicates the "Target group" row in the edit
               # panel -- a real pre-existing bug, flagged for Checkpoint
               # 10's audit, not fixed here since it's out of this
               # checkpoint's scope.)
               fields=(_F_ANIMATION_ID,
                       Field("timing_mode", "Timing", "choice", "time",
                             choices=("time", "even", "dist"),
                             persist="always"),
                       Field("total_duration", "Total duration (s, Even/"
                             "Dist)", "float", 2.0, 0.0, 60.0, step=0.1,
                             decimals=2, persist="always"),
                       *_TRIGGER_COMMON_FIELDS)),
    # ---- Camera family (Checkpoint 6) ---------------------------------
    ObjectSpec(T_ZOOM_TRIGGER, "Zoom Trigger", "Dollies the camera in/out "
               "to Zoom over Duration.", C_ZOOM_TRIGGER, CAT_CAMERA,
               fields=(Field("zoom", "Zoom", "float", 1.5, 0.1, 5.0,
                             step=0.1, decimals=2, persist="always"),
                       Field("duration", "Duration (s)", "float", 1.0, 0.0,
                             30.0, step=0.1, decimals=2, persist="always"),
                       _F_EASING, *_CAMERA_COMMON_FIELDS)),
    ObjectSpec(T_CAM_OFFSET_TRIGGER, "Cam Offset Trigger", "Shifts the "
               "camera away from its normal follow position by (Offset x, "
               "Offset y) over Duration.", C_CAM_OFFSET_TRIGGER,
               CAT_CAMERA,
               fields=(Field("offset_x", "Offset x", "int", 0, -2000, 2000,
                             step=20, persist="always"),
                       Field("offset_y", "Offset y", "int", 0, -2000, 2000,
                             step=20, persist="always"),
                       Field("duration", "Duration (s)", "float", 1.0, 0.0,
                             30.0, step=0.1, decimals=2, persist="always"),
                       _F_EASING, *_CAMERA_COMMON_FIELDS)),
    ObjectSpec(T_CAM_ROTATE_TRIGGER, "Cam Rotate Trigger", "Spins the "
               "whole camera view to Angle degrees over Duration.",
               C_CAM_ROTATE_TRIGGER, CAT_CAMERA,
               fields=(Field("angle", "Angle (deg)", "float", 15.0, -360.0,
                             360.0, step=5.0, decimals=1,
                             persist="always"),
                       Field("duration", "Duration (s)", "float", 2.0, 0.0,
                             30.0, step=0.1, decimals=2, persist="always"),
                       _F_EASING, *_CAMERA_COMMON_FIELDS)),
    ObjectSpec(T_CAM_EDGE_TRIGGER, "Cam Edge Trigger", "Clamps camera "
               "travel to a rectangular bound in px (Enable off clears "
               "the clamp).", C_CAM_EDGE_TRIGGER, CAT_CAMERA,
               fields=(Field("state", "Enable", "bool", True,
                             persist="always"),
                       Field("min_x", "Min x (px)", "int", -100000,
                             -100000, 100000, step=50, persist="always"),
                       Field("max_x", "Max x (px)", "int", 100000,
                             -100000, 100000, step=50, persist="always"),
                       Field("min_y", "Min y (px)", "int", -100000,
                             -100000, 100000, step=50, persist="always"),
                       Field("max_y", "Max y (px)", "int", 100000,
                             -100000, 100000, step=50, persist="always"),
                       *_CAMERA_COMMON_FIELDS)),
    ObjectSpec(T_CAM_GUIDE_TRIGGER, "Cam Guide Trigger", "Overrides how "
               "smoothly the camera eases toward the player (lower = "
               "smoother); Enable off restores the default.",
               C_CAM_GUIDE_TRIGGER, CAT_CAMERA,
               fields=(Field("state", "Enable", "bool", True,
                             persist="always"),
                       Field("smoothing", "Smoothing", "float", 0.5, 0.001,
                             1.0, step=0.05, decimals=3,
                             persist="always"),
                       *_CAMERA_COMMON_FIELDS)),
    # ---- Screen effects (Checkpoint 6, best-effort subset) ------------
    ObjectSpec(T_GRAYSCALE_TRIGGER, "Grayscale Trigger", "Desaturates the "
               "screen toward Intensity over Duration.",
               C_GRAYSCALE_TRIGGER, CAT_CAMERA,
               fields=(Field("state", "Enable", "bool", True,
                             persist="always"),
                       Field("intensity", "Intensity", "float", 1.0, 0.0,
                             1.0, step=0.1, decimals=2, persist="always"),
                       Field("duration", "Duration (s)", "float", 1.0, 0.0,
                             30.0, step=0.1, decimals=2, persist="always"),
                       _F_EASING, *_CAMERA_COMMON_FIELDS)),
    ObjectSpec(T_SEPIA_TRIGGER, "Sepia Trigger", "Tints the screen sepia "
               "toward Intensity over Duration.", C_SEPIA_TRIGGER,
               CAT_CAMERA,
               fields=(Field("state", "Enable", "bool", True,
                             persist="always"),
                       Field("intensity", "Intensity", "float", 1.0, 0.0,
                             1.0, step=0.1, decimals=2, persist="always"),
                       Field("duration", "Duration (s)", "float", 1.0, 0.0,
                             30.0, step=0.1, decimals=2, persist="always"),
                       _F_EASING, *_CAMERA_COMMON_FIELDS)),
    ObjectSpec(T_INVERT_TRIGGER, "Invert Trigger", "Inverts screen colors "
               "toward Intensity over Duration.", C_INVERT_TRIGGER,
               CAT_CAMERA,
               fields=(Field("state", "Enable", "bool", True,
                             persist="always"),
                       Field("intensity", "Intensity", "float", 1.0, 0.0,
                             1.0, step=0.1, decimals=2, persist="always"),
                       Field("duration", "Duration (s)", "float", 1.0, 0.0,
                             30.0, step=0.1, decimals=2, persist="always"),
                       _F_EASING, *_CAMERA_COMMON_FIELDS)),
    ObjectSpec(T_HUE_TRIGGER, "Hue Trigger", "Rotates screen hue by Hue "
               "Shift degrees, scaled by Intensity, over Duration.",
               C_HUE_TRIGGER, CAT_CAMERA,
               fields=(Field("state", "Enable", "bool", True,
                             persist="always"),
                       Field("hue_shift", "Hue Shift (deg)", "float", 60.0,
                             -360.0, 360.0, step=10.0, decimals=1,
                             persist="always"),
                       Field("intensity", "Intensity", "float", 1.0, 0.0,
                             1.0, step=0.1, decimals=2, persist="always"),
                       Field("duration", "Duration (s)", "float", 1.0, 0.0,
                             30.0, step=0.1, decimals=2, persist="always"),
                       _F_EASING, *_CAMERA_COMMON_FIELDS)),
    ObjectSpec(T_PIXELATE_TRIGGER, "Pixelate Trigger", "Pixelates the "
               "screen to Pixel Size blocks, blended by Intensity, over "
               "Duration.", C_PIXELATE_TRIGGER, CAT_CAMERA,
               fields=(Field("state", "Enable", "bool", True,
                             persist="always"),
                       Field("pixel_size", "Pixel Size", "int", 8, 2, 64,
                             step=2, persist="always"),
                       Field("intensity", "Intensity", "float", 1.0, 0.0,
                             1.0, step=0.1, decimals=2, persist="always"),
                       Field("duration", "Duration (s)", "float", 1.0, 0.0,
                             30.0, step=0.1, decimals=2, persist="always"),
                       _F_EASING, *_CAMERA_COMMON_FIELDS)),
    # ---- Misc --------------------------------------------------------
    ObjectSpec(T_START, "Start Pos", "Player spawn point. A level may hold "
               "several; the active one is where every attempt begins.",
               C_START, CAT_MISC,
               fields=(Field("active", "Active", "bool", False,
                             persist="always"),)),
    ObjectSpec(T_END, "Finish", "Finish line.", C_END, CAT_MISC,
               animated=True),
    ObjectSpec(T_COIN, "Coin", "Collect all 3 to verify mastery!", C_COIN,
               CAT_MISC, animated=True,
               fields=(Field("coin_id", "Coin id", "int", 0, 0, None,
                             persist="always"),)),
    ObjectSpec(T_ITEM_PICKUP, "Item Pickup", "Touch to add Amount to Item "
               "id's stored value (like a coin, but feeds the item/counter "
               "system instead of the coin tally).", C_ITEM_PICKUP, CAT_ITEMS,
               animated=True,
               fields=(Field("item_id", "Item id", "int", 0, 0, None,
                             persist="always"),
                       Field("amount", "Amount", "float", 1.0, None, None,
                             persist="always"))),
    ObjectSpec(T_ITEM_COUNTER, "Item Counter", "HUD readout of a live item "
               "(or timer) value — placement position is unused, this is a "
               "top-left HUD row.", C_ITEM_COUNTER, CAT_ITEMS,
               fields=(Field("label", "Label", "choice", "Item",
                             choices=("Item", "Timer"), persist="always"),
                       Field("item_id", "Item/timer id", "int", 0, 0, None,
                             persist="always"))),
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
    # ---- Editor utils ------------------------------------------------
    ObjectSpec(T_DASH_STOP, "S Block", "Stops an active dash — invisible "
               "by default.", C_DASH_STOP, CAT_EDITOR_UTILS,
               invisible_by_default=True),
    ObjectSpec(T_JUMP_BLOCK, "J Block", "Suppresses the one auto-jump that "
               "fires on landing after holding through an orb — invisible "
               "by default.", C_JUMP_BLOCK, CAT_EDITOR_UTILS,
               invisible_by_default=True),
    ObjectSpec(T_WAVE_BLOCK, "D Block", "Lets Wave slide on top of this "
               "block instead of dying on contact — invisible by default.",
               C_WAVE_BLOCK, CAT_EDITOR_UTILS, invisible_by_default=True),
    ObjectSpec(T_BONK_BLOCK, "H Block", "Cube/Robot bonk off this block's "
               "underside or side instead of dying — invisible by default.",
               C_BONK_BLOCK, CAT_EDITOR_UTILS, invisible_by_default=True),
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
# Start positions
# ---------------------------------------------------------------------------
# A level may hold any number of Start Pos objects; exactly one carries
# ``active=True`` and that is where every attempt begins.  Levels saved
# before the field existed (and corrupt ones flagging none or several)
# fall back to the historical leftmost-wins rule, so the spawn point is
# always well defined.  Player, editor and play session all resolve the
# spawn through these three functions so they can never disagree.

def start_objects(objects):
    """Every Start Pos in ``objects``, in cycling order (left to right)."""
    return sorted((o for o in objects if o.get("t") == T_START),
                  key=lambda o: (o["x"], o["y"]))


def active_start(objects):
    """The Start Pos attempts spawn from, or ``None`` if the level has none."""
    starts = start_objects(objects)
    if not starts:
        return None
    flagged = [o for o in starts if o.get("active")]
    return flagged[0] if len(flagged) == 1 else starts[0]


def set_active_start(objects, target):
    """Make ``target`` the one and only active Start Pos.  Returns it."""
    for o in objects:
        if o.get("t") == T_START:
            o["active"] = o is target
    return target


def cycle_active_start(objects, delta):
    """Move the active flag ``delta`` places along the x-ordered Start Pos
    list.  Returns the newly active object, or ``None`` if there are none."""
    starts = start_objects(objects)
    if not starts:
        return None
    current = active_start(objects)
    index = next((i for i, o in enumerate(starts) if o is current), 0)
    return set_active_start(objects, starts[(index + delta) % len(starts)])


# ---------------------------------------------------------------------------
# Generic field helpers used by the loader and the editor
# ---------------------------------------------------------------------------

def seed_defaults(obj):
    """Fill in every schema field missing from a freshly placed object."""
    spec = spec_for(obj["t"])
    for f in spec.fields:
        if f.key not in obj:
            obj[f.key] = f.default_for(obj)
    if spec.invisible_by_default and "invisible" not in obj:
        obj["invisible"] = True
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
