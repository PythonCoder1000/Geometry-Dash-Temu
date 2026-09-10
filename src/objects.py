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
    T_REPEAT_TRIGGER, T_SWAP_TRIGGER,
    T_SCALE_TRIGGER, T_ALPHA_TRIGGER,
    T_ZOOM_TRIGGER, T_CAM_OFFSET_TRIGGER, T_CAM_ROTATE_TRIGGER,
    T_CAM_EDGE_TRIGGER, T_CAM_GUIDE_TRIGGER,
    T_GRAYSCALE_TRIGGER, T_SEPIA_TRIGGER, T_INVERT_TRIGGER, T_HUE_TRIGGER,
    T_PIXELATE_TRIGGER,
    T_SHADER_TRIGGER, T_CHROMATIC_TRIGGER, T_RADIAL_BLUR_TRIGGER,
    T_MOTION_BLUR_TRIGGER, T_BULGE_TRIGGER, T_PINCH_TRIGGER,
    T_SPLIT_SCREEN_TRIGGER,
    RADIAL_BLUR_MAX_SAMPLES, MOTION_BLUR_MAX_FRAMES, CHROMATIC_MAX_OFFSET_PX,
    T_JUMP_PREDICTOR, T_BOT_CHECKPOINT, T_DASH_STOP,
    T_JUMP_BLOCK, T_WAVE_BLOCK, T_BONK_BLOCK,
    T_ITEM_PICKUP, T_COUNT_TRIGGER, T_INSTANT_COUNT_TRIGGER,
    T_ITEM_EDIT_TRIGGER, T_ITEM_COMP_TRIGGER, T_ITEM_PERS_TRIGGER,
    T_TIME_TRIGGER, T_TIME_EVENT_TRIGGER, T_ITEM_COUNTER,
    T_KEYFRAME, T_KEYFRAME_TRIGGER,
    T_AREA_MOVE_TRIGGER, T_AREA_ROTATE_TRIGGER, T_AREA_SCALE_TRIGGER,
    T_AREA_FADE_TRIGGER, T_AREA_TINT_TRIGGER, T_AREA_STOP_TRIGGER,
    T_EDIT_AREA_MOVE_TRIGGER, T_EDIT_AREA_ROTATE_TRIGGER,
    T_EDIT_AREA_SCALE_TRIGGER, T_EDIT_AREA_FADE_TRIGGER,
    T_EDIT_AREA_TINT_TRIGGER,
    T_RANDOM_TRIGGER, T_ADVANCED_RANDOM_TRIGGER, T_FORCE_BLOCK,
    ADVANCED_RANDOM_MAX_PAIRS, ADVANCED_RANDOM_EDITOR_SLOTS,
    FORCE_BLOCK_DEFAULT_RANGE, FORCE_BLOCK_MAX_RANGE, FORCE_BLOCK_MAX_FORCE,
    T_SONG_TRIGGER, T_SFX_TRIGGER, T_EDIT_SONG_TRIGGER, T_EDIT_SFX_TRIGGER,
    SONG_CHANNEL_MAX, AUDIO_SPEED_MIN, AUDIO_SPEED_MAX, AUDIO_PITCH_MIN,
    AUDIO_PITCH_MAX, AUDIO_FADE_MAX_SECONDS, AUDIO_TIME_MAX_SECONDS,
    T_GAMEPLAY_ROTATION_TRIGGER, T_REVERSE_TRIGGER, T_TELEPORT_TRIGGER,
    T_CHECKPOINT_TRIGGER, GAMEPLAY_CHANNEL_DEFAULT, GAMEPLAY_CHANNEL_MAX,
    GAMEPLAY_VELOCITY_MAX,
    T_GROUND_TRIGGER, T_MG_TRIGGER, T_BG_SPEED_TRIGGER, T_MG_SPEED_TRIGGER,
    T_UI_TRIGGER, T_EVENT_TRIGGER, T_END_TRIGGER,
    BG_SPEED_DEFAULT_X, BG_SPEED_DEFAULT_Y, MG_SPEED_DEFAULT_X,
    MG_SPEED_DEFAULT_Y, ENV_SPEED_MIN, ENV_SPEED_MAX, ENV_PRESET_MAX,
    UI_TEXT_CHOICES, UI_OFFSET_MAX, UI_DURATION_MAX_SECONDS, LEVEL_EVENTS,
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
    C_PIXELATE_TRIGGER, C_SHADER_TRIGGER, C_CHROMATIC_TRIGGER,
    C_RADIAL_BLUR_TRIGGER, C_MOTION_BLUR_TRIGGER, C_BULGE_TRIGGER,
    C_PINCH_TRIGGER, C_SPLIT_SCREEN_TRIGGER,
    C_ITEM_PICKUP, C_COUNT_TRIGGER, C_ITEM_EDIT_TRIGGER, C_ITEM_COMP_TRIGGER,
    C_TIME_TRIGGER, C_ITEM_COUNTER, C_KEYFRAME, C_KEYFRAME_TRIGGER,
    C_AREA_TRIGGER, C_EDIT_AREA_TRIGGER, C_AREA_STOP_TRIGGER,
    C_RANDOM_TRIGGER, C_ADVANCED_RANDOM_TRIGGER, C_FORCE_BLOCK,
    C_SONG_TRIGGER, C_SFX_TRIGGER, C_EDIT_SONG_TRIGGER, C_EDIT_SFX_TRIGGER,
    C_GAMEPLAY_ROTATION_TRIGGER, C_REVERSE_TRIGGER, C_TELEPORT_TRIGGER,
    C_CHECKPOINT_TRIGGER,
    C_GROUND_TRIGGER, C_MG_TRIGGER, C_BG_SPEED_TRIGGER, C_MG_SPEED_TRIGGER,
    C_UI_TRIGGER, C_EVENT_TRIGGER, C_END_TRIGGER,
    DECORATION_TYPES, Z_LAYERS, Z_LAYER_INDEX, Z_LAYER_DEFAULT,
    Z_LAYER_DECORATION_DEFAULT, Z_ORDER_DEFAULT,
)
# The SFX Trigger's sound vocabulary is the sound library sfx.py actually
# ships (it generates every effect procedurally -- there are no .wav files
# and no licensed GD SFX catalog here), so the choice Field below is built
# from that module's own table rather than a second list kept in sync by
# hand. sfx.py imports only pygame/prefs, so this costs no import cycle
# and touches no mixer at import time.
from .sfx import SOUND_NAMES as _SFX_SOUND_NAMES


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
    # Real-GD-parity metadata (deep-research-report.md refactor, Checkpoint 0).
    # ``gd_key`` is the real Geometry Dash numeric property key this field
    # corresponds to (e.g. 51 for a target-group field), when the report
    # cites one *for this specific object type* -- property keys are reused
    # across object types with different meanings, so this is never a
    # global/shared constant, only ever set per-Field instance. Left ``None``
    # wherever the report itself has no verified key. This is documentation/
    # future-export metadata only: the live JSON save format and every
    # runtime/editor read site keep using ``key`` (the descriptive name),
    # never ``gd_key`` -- see the hybrid-metadata decision recorded near
    # ``ObjectSpec`` below.
    gd_key: object = None
    # Confidence tier for this field's report-sourced metadata, mirroring
    # the report's own confidence hierarchy: "verified" (the report cites
    # a source-backed value for it), "partial" (the key is documented but
    # its default/range is not), "unverified" (engine-invented field with
    # no real-GD equivalent).
    #
    # Usually the metadata in question is ``gd_key``, so gd_key=None and
    # "verified" rarely co-occur. Checkpoint 7's BG/MG Speed fields are
    # the documented exception: the report gives no property key for
    # Background/Middleground Speed but DOES give their exact defaults in
    # its own values table (BG 0.1/0.1, MG 0.3/0.5), so what is verified
    # there is the ``default``.
    verification: str = "unverified"

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
    # Real-GD-parity metadata (deep-research-report.md refactor, Checkpoint
    # 0). ``gd_object_id`` is the real Geometry Dash numeric Object ID for
    # this type (e.g. 901 for Move Trigger), taken from the report's
    # tables. Left ``None`` wherever the report itself marks the ID
    # "unspecified" (e.g. every current letter block) -- never invented.
    #
    # DECISION (do not re-litigate): this is metadata-only. The engine's
    # internal representation, level JSON save format, and every read site
    # in src/editor/*, src/player/triggers.py, src/play_render.py keep
    # using the descriptive ``type``/``Field.key`` strings exactly as
    # before -- there is no numeric-keyed wire format. Real GD reuses
    # numeric property keys per object type with different meanings (the
    # report explicitly warns against a global "PROPERTY_176" constant),
    # which is exactly the class of bug the existing descriptive-Field
    # design already avoids. A full flip to numeric keys would touch every
    # read-by-name call site across the codebase for a benefit (byte-
    # identical GD save-file compatibility) this project doesn't need,
    # since it never imports/exports real .gmd level files. gd_object_id/
    # Field.gd_key exist purely so a *future* numeric import/export layer
    # has a ready lookup table (see GD_ID_TO_TYPE/gd_field_map below) --
    # nothing in the current engine reads them at runtime.
    gd_object_id: object = None
    verification: str = "unverified"

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
_F_MULTI_ACTIVATE = Field("multi_activate", "Multi Activate", "bool", False,
                          gd_key=87, verification="verified")
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
                 persist="always", gd_key=51, verification="verified")
# Default is line-activated only (fired by a Spawn/Sequence/Toggle chain
# targeting this trigger's group), matching real GD trigger conventions --
# a level built entirely from touch triggers turns into unintended chaos
# once objects overlap. "Touch Activated" is the opt-in toggle that makes
# the player set it off directly, same as pre-touch-toggle levels did by
# default (see levels._migrate_objects for the old-save compatibility
# shim: any trigger saved before this toggle existed keeps firing on
# touch, since that was the only behavior available when it was placed).
# persist="always": Field's non_default persistence would strip this key
# whenever it's at its own default (False), which would make a freshly
# saved line-only trigger indistinguishable on reload from a *pre-v9*
# trigger (also keyless) that needs the touch-preserving migration shim
# in levels._migrate_objects to read True instead. Always writing it
# removes that ambiguity: after any save, "key present" means "this
# trigger type actually has the concept" and its value is authoritative.
_F_TOUCH_ACTIVATED = Field("touch_activated", "Touch Activated", "bool", False,
                           persist="always", gd_key=11,
                           verification="verified")
_F_EASING = Field("easing", "Easing", "choice", "linear",
                  choices=("linear", "ease_in", "ease_out", "ease_in_out"),
                  persist="always", gd_key=30, verification="partial")
# Same-frame precedence (deep-research-report.md, "Same-frame precedence"):
# triggers firing on the same tick run in ascending Trigger Order, so two
# non-commutative effects on one target (an Item Edit that adds and one
# that multiplies, say) resolve predictably. The report cites no numeric GD
# property key for it, hence gd_key=None/"unverified". persist="non_default"
# keeps every existing saved level byte-identical: the overwhelmingly
# common value is the default 0, which is never written out.
_F_TRIGGER_ORDER = Field("trigger_order", "Trigger Order", "int", 0,
                         persist="non_default", gd_key=None,
                         verification="unverified")
_TRIGGER_COMMON_FIELDS = (_F_GROUP, _F_TOUCH_ACTIVATED, _F_MULTI_ACTIVATE,
                          _F_TRIGGER_ORDER)
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
# The activation vocabulary of a trigger that targets no group: it acts
# on the camera (Checkpoint 6), the whole screen (Checkpoint 6 + 4) or
# the mixer (Checkpoint 5's audio family), so it skips _F_GROUP but keeps
# the touch-activated / multi-activate / trigger-order concepts every
# trigger needs. (Named _CAMERA_COMMON_FIELDS when only the camera family
# used it; renamed once the screen-effect and audio families -- neither of
# them cameras -- turned out to want exactly the same three fields.)
_UNTARGETED_COMMON_FIELDS = (_F_TOUCH_ACTIVATED, _F_MULTI_ACTIVATE,
                             _F_TRIGGER_ORDER)
# Every screen-effect trigger (Checkpoint 6's five, Checkpoint 4's six)
# shares the same tween tail: turn the effect on or off (``state``), how
# far toward it (``intensity``), over how long (``duration``), on what
# curve (``easing``). That quartet is exactly what _start_effect_trigger
# reads, so a spec that omits it has no animation -- see
# T_SHADER_TRIGGER, which deliberately carries none of it. Effect-
# specific knobs (hue degrees, pixel size, bulge radius...) go BEFORE
# the tween tail so the property panel reads "what, then how much".
_F_EFFECT_STATE = Field("state", "Enable", "bool", True, persist="always")
_F_EFFECT_INTENSITY = Field("intensity", "Intensity", "float", 1.0, 0.0, 1.0,
                            step=0.1, decimals=2, persist="always")
_F_EFFECT_DURATION = Field("duration", "Duration (s)", "float", 1.0, 0.0,
                           30.0, step=0.1, decimals=2, persist="always")
_SCREEN_EFFECT_TWEEN_FIELDS = (_F_EFFECT_INTENSITY, _F_EFFECT_DURATION,
                               _F_EASING)

# Checkpoint 2 (deep-research-report.md, "Area and keyframe system"): the
# vocabulary every Area trigger shares. The report cites each numeric key
# below directly; only ``length``'s *unit* is officially documented
# ("Length 1 = 0.1 grid square"), so this engine stores Length as a plain
# grid-square float and never as GD's raw tenths-int -- one less unit
# conversion on every distance test in _step_area_effects, and the editor
# panel reads in the same units the level author sees on the grid.
#
# ``effect_id`` is the one id that ties the family together: an Area
# Move/Rotate/Scale/Fade/Tint STARTS the effect registered under it, an
# Edit Area PATCHES the live effect with that id, and Area Stop ENDS it.
_F_EFFECT_ID = Field("effect_id", "Effect id", "int", 0, 0, None,
                     persist="always", gd_key=225, verification="verified")
_F_AREA_LENGTH = Field("length", "Length (grid squares)", "float", 3.0, 0.0,
                       500.0, step=0.5, decimals=2, persist="always",
                       gd_key=222, verification="verified")
# Length +/-: how far past ``length`` the effect fades out. 0 (the
# default) means a hard edge at ``length``.
_F_AREA_LENGTH_VARIANCE = Field("length_variance", "Length +/- (falloff)",
                                "float", 0.0, 0.0, 500.0, step=0.5,
                                decimals=2, persist="always", gd_key=223,
                                verification="partial")
# The report names keys 220/252 "offset"/"Y-offset" but not what they
# offset; this engine reads them as a shift of the effect's center away
# from the center group's centroid, in grid squares (engine-chosen).
_F_AREA_OFFSET = Field("offset", "Offset x (grid)", "float", 0.0, -500.0,
                       500.0, step=0.5, decimals=2, persist="always",
                       gd_key=220, verification="partial")
_F_AREA_Y_OFFSET = Field("y_offset", "Offset y (grid)", "float", 0.0, -500.0,
                         500.0, step=0.5, decimals=2, persist="always",
                         gd_key=252, verification="partial")
# Key 71: the group whose member centroid the falloff measures from
# (distinct from _F_GROUP/key 51, the group the effect acts ON). With no
# members the effect falls back to the trigger object's own cell.
_F_AREA_CENTER_GROUP = Field("center_group", "Center group", "int", 0, 0,
                             None, persist="always", gd_key=71,
                             verification="verified")
# Key 341. Stored for parity only: the report cites the key but no
# semantics, and this engine's documented composition rule for two areas
# touching one object is last-processed-wins (see _step_area_effects), so
# nothing reads it yet rather than inventing an ordering law for it.
_F_AREA_PRIORITY = Field("priority", "Priority", "int", 0, None, None,
                         persist="always", gd_key=341,
                         verification="partial")
# target_group (key 51) rides in via _TRIGGER_COMMON_FIELDS -- listing
# _F_GROUP here as well would duplicate the "Target group" row in the
# edit panel (the pre-existing Scale/Alpha Trigger bug noted below).
_AREA_COMMON_FIELDS = (_F_EFFECT_ID, _F_AREA_LENGTH, _F_AREA_LENGTH_VARIANCE,
                       _F_AREA_OFFSET, _F_AREA_Y_OFFSET,
                       _F_AREA_CENTER_GROUP, _F_AREA_PRIORITY,
                       *_TRIGGER_COMMON_FIELDS)

# Checkpoint 3 (deep-research-report.md, "Representative full-format
# records"): Advanced Random's authoritative storage is the report's own
# dot-separated "group.weight.group.weight..." string of up to
# ADVANCED_RANDOM_MAX_PAIRS (20) pairs, parsed/serialized generically by
# parse_weighted_list/format_weighted_list at the bottom of this module.
#
# DELIBERATE EDITOR-UX SCOPE TRIM (recorded here so it is not mistaken
# for an oversight): Field has no free-text kind, and PropPanel.layout()
# renders every non-bool field as a +/- nudge row, so there is nowhere to
# type "2.10.3.15". Rather than build generic text-entry plumbing for one
# field, the property panel exposes only the first
# ADVANCED_RANDOM_EDITOR_SLOTS (4) pairs as plain int rows. Those slots
# are serialized INTO the report's string form at the editor/engine
# boundary (advanced_random_weighted_list) so the weighted pick itself
# has exactly one code path and it is the generic 20-pair one. A level
# authored programmatically -- or a future real-GD importer -- can set
# the full "weighted_list" string on the object directly and it wins over
# the slots; levels.normalize_object carries that string through saves
# the same way it carries Move Trigger's target_oids list.
#
# Weight 0 marks an unused slot: it drops out of the sum, so a freshly
# placed Advanced Random with every weight at 0 is inert until authored.
_ADV_RANDOM_SLOT_FIELDS = tuple(
    f
    for i in range(1, ADVANCED_RANDOM_EDITOR_SLOTS + 1)
    for f in (Field(f"group{i}", f"Group {i}", "int", 0, 0, None,
                    persist="always"),
              Field(f"weight{i}", f"Weight {i}", "int", 0, 0, None,
                    persist="always"))
)

# Checkpoint 5 (deep-research-report.md, "Audio, timers, and
# arithmetic"): the audio family's shared vocabulary. Every gd_key below
# is quoted directly from the report's Song/SFX property map
# (song=392, speed=404, pitch=405, volume=406, reverb=407, start=408,
# fade_in=409, end=410, fade_out=411, loop=413, unique_id=416,
# song_channel=432); every range/default is an engine choice, because the
# report cites the keys and no ranges at all.
#
# WHAT IS REAL AND WHAT IS STORED-ONLY (see player/triggers.py for the
# handlers, and keep the two lists in agreement):
#   real  -- song, channel (as an Edit Song address), volume, start,
#            fade_in, fade_out, loop, sfx, unique_id, stop
#   store -- speed, end, pitch, reverb
# The stored-only four have no engine capability behind them at all:
# pygame's music stream has no playback-rate control (speed) and no
# scheduled stop (end); pygame.mixer.Sound has no pitch shift (pitch) and
# there is no DSP stage anywhere in this project (reverb). They are still
# authored, saved and round-tripped so a level written in the report's
# vocabulary survives intact -- the same "stored but inert, documented"
# precedent the Area family's `priority` and the Shader Trigger's layer
# range already set. Do not fake them by resampling audio here.
_F_AUDIO_VOLUME = Field("volume", "Volume", "float", 1.0, 0.0, 1.0, step=0.05,
                        decimals=2, persist="always", gd_key=406,
                        verification="verified")
_F_AUDIO_SPEED = Field("speed", "Speed (stored, no-op)", "float", 1.0,
                       AUDIO_SPEED_MIN, AUDIO_SPEED_MAX, step=0.1, decimals=2,
                       persist="always", gd_key=404, verification="verified")
_F_AUDIO_PITCH = Field("pitch", "Pitch (stored, no-op)", "float", 0.0,
                       AUDIO_PITCH_MIN, AUDIO_PITCH_MAX, step=1.0, decimals=2,
                       persist="always", gd_key=405, verification="verified")
# Key 432. This engine has exactly one music stream (pygame.mixer.music),
# so a channel is an ADDRESS -- what an Edit Song names to find the song
# state it should patch -- rather than a real mixing slot. Starting a song
# on a second channel replaces what was sounding; only the most recently
# started channel is audible. See _apply_song_trigger.
_F_SONG_CHANNEL = Field("channel", "Song channel", "int", 0, 0,
                        SONG_CHANNEL_MAX, persist="always", gd_key=432,
                        verification="verified")
# Key 416. 0 means "anonymous": the sound plays but nothing tracks it, so
# Edit SFX can never find it (and a loop is refused, since an untracked
# loop could never be stopped). A nonzero id makes the instance
# addressable, and re-firing that id replaces the previous instance --
# the same last-fired-wins rule an Area effect id already uses.
_F_SFX_UNIQUE_ID = Field("unique_id", "Unique id (0 = anonymous)", "int", 0, 0,
                         None, persist="always", gd_key=416,
                         verification="verified")
# The report describes Edit SFX / Edit Song as "stop/edit" but cites no
# key for the stop switch itself, hence gd_key=None/"unverified".
_F_AUDIO_STOP = Field("stop", "Stop", "bool", False, persist="always",
                      gd_key=None, verification="unverified")
_AUDIO_LOOP_FIELD = Field("loop", "Loop", "bool", False, persist="always",
                          gd_key=413, verification="verified")

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
# Checkpoint 2 (deep-research-report.md, "Area and keyframe system"): the
# 11 Area/Edit-Area/Area-Stop triggers, split out of CAT_TRIGGERS for the
# same reason CAT_CAMERA was -- one family, one tab.
CAT_AREA = "Area"
# Checkpoint 5 (deep-research-report.md, "Audio, timers, and
# arithmetic"): Song / SFX / Edit Song / Edit SFX. Its own tab rather
# than a corner of CAT_MISC (which holds non-trigger placeables -- Start
# Pos, Finish, Coin) or of an already-crowded CAT_TRIGGERS, for exactly
# the reason CAT_AREA and CAT_CAMERA were split out: one family, one tab.
# Four types is a small tab, but the family is closed (the report lists
# no further audio triggers this engine can honour) and the editor's tab
# row still fits: 14 tabs end at x=1124 of the 1200px window (see
# editor/ui.py's _build_buttons, which lays the tabs out in one
# unwrapped row -- a 15th long-named tab is the one that will not fit).
CAT_AUDIO = "Audio"
CAT_ITEMS = "Items"
CAT_MISC = "Misc"
CAT_EDITOR_UTILS = "Utils"
CATEGORY_ORDER = (CAT_BLOCKS, CAT_HAZARDS, CAT_ORBS, CAT_PADS, CAT_PORTALS,
                  CAT_SPEED, CAT_DECO, CAT_TRIGGERS, CAT_CAMERA, CAT_AREA,
                  CAT_AUDIO, CAT_ITEMS, CAT_MISC, CAT_EDITOR_UTILS)


def _mode_portal(t, name, tip, col):
    return ObjectSpec(t, name, tip, col, CAT_PORTALS, animated=True,
                      fields=(_F_FREE_MODE,))


def _area_spec(t, name, tip, gd_id, transform_fields, color=C_AREA_TRIGGER):
    """One Area / Edit Area trigger.

    ``verification="partial"`` throughout, the convention Checkpoint 0
    established: the object ids and every ``gd_key`` come from the
    report's tables, but the transform fields' ranges, defaults and
    per-tick semantics are engine choices the report does not specify.
    """
    return ObjectSpec(t, name, tip, color, CAT_AREA,
                      fields=(*transform_fields, *_AREA_COMMON_FIELDS),
                      gd_object_id=gd_id, verification="partial")


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
    # Real GD "Change Background" (3029). The id is metadata added in
    # Checkpoint 7, when the rest of its family (Change Ground 3030 /
    # Change Middleground 3031 / BG Speed 3606 / MG Speed 3612) landed --
    # the spec itself is otherwise untouched, and BG_PRESETS is still the
    # only environment palette this engine has.
    ObjectSpec(T_BG_TRIGGER, "BG Trigger", "Changes the background "
               "preset.", C_BG_TRIGGER, CAT_TRIGGERS,
               fields=(Field("bg", "BG preset", "int", 0, 0,
                             len(BG_PRESETS) - 1, persist="always"),
                       *_TRIGGER_COMMON_FIELDS),
               gd_object_id=3029, verification="partial"),
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
                       _F_EASING, *_TRIGGER_COMMON_FIELDS),
               gd_object_id=901, verification="partial"),
    ObjectSpec(T_COLOR_TRIGGER, "Color Trigger", "Sets the player's color "
               "to the given color channel (edit the channel's own RGB "
               "from the panel below to restyle every user of it at "
               "once).", C_COLOR_TRIGGER, CAT_TRIGGERS,
               fields=(Field("channel", "Channel", "int", 0, 0, None,
                             persist="always"),
                       *_TRIGGER_COMMON_FIELDS),
               gd_object_id=899, verification="partial"),
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
                       *_TRIGGER_COMMON_FIELDS),
               gd_object_id=1006, verification="partial"),
    ObjectSpec(T_ROTATE_TRIGGER, "Rotate Trigger", "Spins target objects "
               "(or a whole Group).", C_ROTATE_TRIGGER, CAT_TRIGGERS,
               fields=(_F_TARGET_OID,
                       Field("spin", "Spin (deg/s)", "float", 90.0, -3600.0,
                             3600.0, step=15.0, decimals=1,
                             persist="always"),
                       Field("duration", "Duration (s)", "float", 4.0, 0.1,
                             60.0, step=0.5, decimals=1,
                             persist="always"),
                       _F_EASING, *_TRIGGER_COMMON_FIELDS),
               gd_object_id=1346, verification="partial"),
    ObjectSpec(T_FOLLOW_TRIGGER, "Follow Trigger", "Links a target to a "
               "source so it moves with it.", C_FOLLOW_TRIGGER, CAT_TRIGGERS,
               fields=(Field("source_oid", "Source oid", "int", 0, 0, None,
                             persist="always"),
                       _F_TARGET_OID,
                       Field("always_on", "Always on", "bool", False),
                       Field("follow_player", "Follow player", "bool",
                             False),
                       Field("offset_cx", "Offset x", "int", 0, -200, 200),
                       Field("offset_cy", "Offset y", "int", 0, -200, 200),
                       _F_TRIGGER_ORDER),
               gd_object_id=1347, verification="partial"),
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
                       _F_MULTI_ACTIVATE, _F_TRIGGER_ORDER),
               gd_object_id=1268, verification="partial"),
    ObjectSpec(T_TOGGLE_TRIGGER, "Toggle Trigger", "Enables or disables "
               "every trigger in the target group (disabled triggers "
               "ignore touch and Spawn until re-enabled).",
               (255, 200, 90), CAT_TRIGGERS,
               fields=(_F_GROUP,
                       Field("state", "Enable", "bool", True,
                             persist="always"),
                       _F_MULTI_ACTIVATE, _F_TRIGGER_ORDER),
               gd_object_id=1049, verification="partial"),
    ObjectSpec(T_STOP_TRIGGER, "Stop Trigger", "Halts any in-progress Move/"
               "Rotate/Scale/Alpha animation on the target group, freezing "
               "it where it currently is.", (255, 120, 120), CAT_TRIGGERS,
               fields=(_F_GROUP, _F_MULTI_ACTIVATE, _F_TRIGGER_ORDER),
               gd_object_id=1616, verification="partial"),
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
                       _F_MULTI_ACTIVATE, _F_TRIGGER_ORDER),
               gd_object_id=3607, verification="partial"),
    ObjectSpec(T_REPEAT_TRIGGER, "Repeat Trigger", "Fires every trigger in "
               "the target group once every Interval seconds, for Count "
               "cycles total — a loop for chaining Spawn-style triggers "
               "without stacking them by hand.", (255, 160, 220),
               CAT_TRIGGERS,
               fields=(_F_GROUP,
                       Field("interval", "Interval (s)", "float", 0.5,
                             0.05, 60.0, step=0.05, decimals=2,
                             persist="always"),
                       Field("count", "Count", "int", 10, 1, 10000,
                             persist="always"),
                       _F_MULTI_ACTIVATE, _F_TRIGGER_ORDER)),
    ObjectSpec(T_SWAP_TRIGGER, "Swap Trigger", "Randomly swaps the target "
               "group's positions among themselves once every Interval "
               "seconds, for Count cycles total. Smooth tweens each swap "
               "like a Move Trigger instead of snapping.",
               (120, 220, 200), CAT_TRIGGERS,
               fields=(_F_GROUP,
                       Field("interval", "Interval (s)", "float", 1.0,
                             0.05, 60.0, step=0.05, decimals=2,
                             persist="always"),
                       Field("count", "Count", "int", 5, 1, 10000,
                             persist="always"),
                       Field("smooth", "Smooth", "bool", False,
                             persist="always"),
                       # Clamped at apply time (triggers._start_swap_
                       # trigger) to at most one Interval, so a slow tween
                       # can never still be running when the next swap
                       # fires and fight it for the same objects.
                       Field("smooth_duration", "Smooth Duration (s)",
                             "float", 0.3, 0.0, 60.0, step=0.05, decimals=2,
                             persist="always"),
                       _F_EASING,
                       _F_MULTI_ACTIVATE, _F_TRIGGER_ORDER)),
    # Checkpoint 3 (deep-research-report.md, "Core object, paired, and
    # item triggers"): the report lists both of these in the *Paired*
    # family -- "Randomly select one of two groups" (1912) and "Weighted
    # random, up to 20 groups" (2068). Their effect is Spawn's effect
    # with a die roll in front of it, so they live in CAT_TRIGGERS beside
    # Spawn/Sequence/Toggle rather than in a family tab of their own.
    #
    # target_group (key 51) rides in via _TRIGGER_COMMON_FIELDS -- listing
    # _F_GROUP here as well would duplicate the "Target group" row in the
    # edit panel (the same pre-existing Scale/Alpha Trigger bug the Area
    # family's comment calls out).
    ObjectSpec(T_RANDOM_TRIGGER, "Random Trigger", "Fires Target group with "
               "Chance% probability, and Group 2 the rest of the time.",
               C_RANDOM_TRIGGER, CAT_TRIGGERS,
               fields=(Field("target_group2", "Group 2", "int", 0, 0, None,
                             persist="always"),
                       # The report documents no default for Chance (its
                       # "unspecified" table covers every field's implicit
                       # default), so an even 50/50 split is this engine's
                       # choice, not a transcribed GD value.
                       Field("chance", "Chance (%)", "float", 50.0, 0.0,
                             100.0, step=5.0, decimals=2, persist="always"),
                       *_TRIGGER_COMMON_FIELDS),
               gd_object_id=1912, verification="partial"),
    ObjectSpec(T_ADVANCED_RANDOM_TRIGGER, "Advanced Random Trigger",
               "Fires one of up to 4 groups, each picked with probability "
               "100 * its Weight / the total Weight. Weight 0 = slot "
               "unused.", C_ADVANCED_RANDOM_TRIGGER, CAT_TRIGGERS,
               fields=(*_ADV_RANDOM_SLOT_FIELDS, _F_TOUCH_ACTIVATED,
                       _F_MULTI_ACTIVATE, _F_TRIGGER_ORDER),
               gd_object_id=2068, verification="partial"),
    ObjectSpec(T_SCALE_TRIGGER, "Scale Trigger", "Resizes the target group "
               "(optionally per-axis) over Duration.", (120, 255, 180),
               CAT_TRIGGERS,
               fields=(Field("sx", "Scale X", "float", 1.0, 0.1, 8.0,
                             step=0.05, decimals=2, persist="always"),
                       Field("sy", "Scale Y", "float", 1.0, 0.1, 8.0,
                             step=0.05, decimals=2, persist="always"),
                       Field("duration", "Duration (s)", "float", 0.5, 0.0,
                             30.0, step=0.1, decimals=2, persist="always"),
                       _F_EASING, *_TRIGGER_COMMON_FIELDS),
               gd_object_id=2067, verification="partial"),
    ObjectSpec(T_ALPHA_TRIGGER, "Alpha Trigger", "Fades the target group's "
               "transparency over Duration.", (200, 200, 200), CAT_TRIGGERS,
               fields=(Field("alpha", "Alpha", "float", 1.0, 0.0, 1.0,
                             step=0.05, decimals=2, persist="always"),
                       Field("duration", "Duration (s)", "float", 0.5, 0.0,
                             30.0, step=0.1, decimals=2, persist="always"),
                       _F_EASING, *_TRIGGER_COMMON_FIELDS),
               gd_object_id=1007, verification="partial"),
    # ---- Item / counter / timer family (Checkpoint 7) -----------------
    ObjectSpec(T_COUNT_TRIGGER, "Count Trigger", "Continuously watches an "
               "item id; the FIRST tick the comparison becomes true, fires "
               "the target group once (re-arms if the comparison later "
               "goes false again).", C_COUNT_TRIGGER, CAT_ITEMS,
               fields=(_F_GROUP, _F_ITEM_ID, _F_COMPARATOR,
                       Field("value", "Value", "float", 0.0, None, None,
                             persist="always"),
                       _F_MULTI_ACTIVATE, _F_TRIGGER_ORDER),
               gd_object_id=1611, verification="partial"),
    ObjectSpec(T_INSTANT_COUNT_TRIGGER, "Instant Count Trigger", "Checks an "
               "item id against Value once, the instant it's touched/"
               "spawned (no re-arming) — fires the target group if true.",
               C_COUNT_TRIGGER, CAT_ITEMS,
               fields=(_F_GROUP, _F_ITEM_ID, _F_COMPARATOR,
                       Field("value", "Value", "float", 0.0, None, None,
                             persist="always"),
                       _F_MULTI_ACTIVATE, _F_TRIGGER_ORDER),
               gd_object_id=1811, verification="partial"),
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
                       *_TRIGGER_COMMON_FIELDS),
               gd_object_id=3619, verification="partial"),
    ObjectSpec(T_ITEM_COMP_TRIGGER, "Item Comp Trigger", "Compares Item id "
               "against Value (or Compare item id, if nonzero); fires the "
               "target group if true.", C_ITEM_COMP_TRIGGER, CAT_ITEMS,
               fields=(_F_GROUP, _F_ITEM_ID, _F_COMPARATOR,
                       Field("value", "Value", "float", 0.0, None, None,
                             persist="always"),
                       Field("compare_item_id", "Compare item id (0=none)",
                             "int", 0, 0, None, persist="always"),
                       _F_MULTI_ACTIVATE, _F_TRIGGER_ORDER),
               gd_object_id=3620, verification="partial"),
    ObjectSpec(T_ITEM_PERS_TRIGGER, "Item Pers Trigger", "Snapshots Item "
               "id's current value into persistent storage — the next "
               "retry/respawn re-seeds that item from the snapshot instead "
               "of resetting it to 0.", (255, 235, 255), CAT_ITEMS,
               fields=(_F_ITEM_ID, _F_MULTI_ACTIVATE, _F_TRIGGER_ORDER)),
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
                       _F_MULTI_ACTIVATE, _F_TRIGGER_ORDER)),
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
                       _F_EASING, *_UNTARGETED_COMMON_FIELDS),
               gd_object_id=1913, verification="partial"),
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
                       _F_EASING, *_UNTARGETED_COMMON_FIELDS),
               gd_object_id=1916, verification="partial"),
    ObjectSpec(T_CAM_ROTATE_TRIGGER, "Cam Rotate Trigger", "Spins the "
               "whole camera view to Angle degrees over Duration.",
               C_CAM_ROTATE_TRIGGER, CAT_CAMERA,
               fields=(Field("angle", "Angle (deg)", "float", 15.0, -360.0,
                             360.0, step=5.0, decimals=1,
                             persist="always"),
                       Field("duration", "Duration (s)", "float", 2.0, 0.0,
                             30.0, step=0.1, decimals=2, persist="always"),
                       _F_EASING, *_UNTARGETED_COMMON_FIELDS),
               gd_object_id=2015, verification="partial"),
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
                       *_UNTARGETED_COMMON_FIELDS),
               gd_object_id=2062, verification="partial"),
    ObjectSpec(T_CAM_GUIDE_TRIGGER, "Cam Guide Trigger", "Overrides how "
               "smoothly the camera eases toward the player (lower = "
               "smoother); Enable off restores the default.",
               C_CAM_GUIDE_TRIGGER, CAT_CAMERA,
               fields=(Field("state", "Enable", "bool", True,
                             persist="always"),
                       Field("smoothing", "Smoothing", "float", 0.5, 0.001,
                             1.0, step=0.05, decimals=3,
                             persist="always"),
                       *_UNTARGETED_COMMON_FIELDS)),
    # ---- Screen effects (Checkpoint 6, best-effort subset) ------------
    ObjectSpec(T_GRAYSCALE_TRIGGER, "Grayscale Trigger", "Desaturates the "
               "screen toward Intensity over Duration.",
               C_GRAYSCALE_TRIGGER, CAT_CAMERA,
               fields=(_F_EFFECT_STATE, *_SCREEN_EFFECT_TWEEN_FIELDS,
                       *_UNTARGETED_COMMON_FIELDS),
               gd_object_id=2919, verification="partial"),
    ObjectSpec(T_SEPIA_TRIGGER, "Sepia Trigger", "Tints the screen sepia "
               "toward Intensity over Duration.", C_SEPIA_TRIGGER,
               CAT_CAMERA,
               fields=(_F_EFFECT_STATE, *_SCREEN_EFFECT_TWEEN_FIELDS,
                       *_UNTARGETED_COMMON_FIELDS),
               gd_object_id=2920, verification="partial"),
    ObjectSpec(T_INVERT_TRIGGER, "Invert Trigger", "Inverts screen colors "
               "toward Intensity over Duration.", C_INVERT_TRIGGER,
               CAT_CAMERA,
               fields=(_F_EFFECT_STATE, *_SCREEN_EFFECT_TWEEN_FIELDS,
                       *_UNTARGETED_COMMON_FIELDS),
               gd_object_id=2921, verification="partial"),
    ObjectSpec(T_HUE_TRIGGER, "Hue Trigger", "Rotates screen hue by Hue "
               "Shift degrees, scaled by Intensity, over Duration.",
               C_HUE_TRIGGER, CAT_CAMERA,
               fields=(_F_EFFECT_STATE,
                       Field("hue_shift", "Hue Shift (deg)", "float", 60.0,
                             -360.0, 360.0, step=10.0, decimals=1,
                             persist="always", gd_key=176,
                             verification="verified"),
                       *_SCREEN_EFFECT_TWEEN_FIELDS,
                       *_UNTARGETED_COMMON_FIELDS),
               gd_object_id=2922, verification="partial"),
    ObjectSpec(T_PIXELATE_TRIGGER, "Pixelate Trigger", "Pixelates the "
               "screen to Pixel Size blocks, blended by Intensity, over "
               "Duration.", C_PIXELATE_TRIGGER, CAT_CAMERA,
               fields=(_F_EFFECT_STATE,
                       Field("pixel_size", "Pixel Size", "int", 8, 2, 64,
                             step=2, persist="always"),
                       *_SCREEN_EFFECT_TWEEN_FIELDS,
                       *_UNTARGETED_COMMON_FIELDS),
               gd_object_id=2912, verification="partial"),
    # ---- Shader family (Checkpoint 4) ---------------------------------
    # deep-research-report.md, "Shader and visual effects": the rest of
    # the 2.2 shader table that a CPU/numpy pipeline can do honestly.
    # Every one of these tweens exactly one entry in
    # Player.active_effect_anims and gets one branch in
    # play_render.apply_screen_effects -- same mechanism as the five
    # above, no parallel pipeline. Ranges/defaults below are engine
    # choices (verification="partial"): the report publishes object IDs
    # for this family but leaves per-shader field ranges unspecified
    # except for the base trigger's keys, which are set exactly.
    ObjectSpec(T_SHADER_TRIGGER, "Shader Trigger", "Base shader control. "
               "Disable All clears every running screen effect at once. "
               "The layer range is stored but inert -- this engine has no "
               "render layers.", C_SHADER_TRIGGER, CAT_CAMERA,
               # NOTE (engine gap, deliberately not faked): real GD's base
               # Shader Trigger scopes the affected RENDER-LAYER RANGE via
               # lowest_layer/highest_layer. This engine draws one flat
               # world pass with no layer concept at all, so there is
               # nothing to scope to. The two fields are kept (authored,
               # saved, round-tripped) so a level written against them
               # survives a future layer system, but nothing consumes them
               # -- the same "stored but not consumed, documented" pattern
               # the Area family's `priority` field uses. Do not invent a
               # layer meaning for them here.
               #
               # No state/intensity/duration/easing on purpose: disable_all
               # is an instant clear, not a tween, so this spec is the one
               # screen-effect-family type that is NOT in
               # SCREEN_EFFECT_TRIGGER_TYPES.
               fields=(Field("disable_all", "Disable All", "bool", False,
                             persist="always", gd_key=192,
                             verification="verified"),
                       Field("lowest_layer", "Lowest Layer", "int", 0,
                             -1000, 1000, persist="always", gd_key=196,
                             verification="verified"),
                       Field("highest_layer", "Highest Layer", "int", 0,
                             -1000, 1000, persist="always", gd_key=197,
                             verification="verified"),
                       *_UNTARGETED_COMMON_FIELDS),
               gd_object_id=2904, verification="partial"),
    ObjectSpec(T_CHROMATIC_TRIGGER, "Chromatic Trigger", "Splits the red "
               "and blue channels Offset pixels apart horizontally, "
               "scaled by Intensity, over Duration.",
               C_CHROMATIC_TRIGGER, CAT_CAMERA,
               fields=(_F_EFFECT_STATE,
                       Field("offset_px", "Offset (px)", "int", 6, 1,
                             CHROMATIC_MAX_OFFSET_PX, persist="always"),
                       *_SCREEN_EFFECT_TWEEN_FIELDS,
                       *_UNTARGETED_COMMON_FIELDS),
               gd_object_id=2910, verification="partial"),
    ObjectSpec(T_RADIAL_BLUR_TRIGGER, "Radial Blur Trigger", "Averages "
               "Samples copies of the frame scaled out from screen "
               "center, smeared by Strength, over Duration.",
               C_RADIAL_BLUR_TRIGGER, CAT_CAMERA,
               fields=(_F_EFFECT_STATE,
                       Field("strength", "Strength", "float", 0.5, 0.0, 1.0,
                             step=0.1, decimals=2, persist="always"),
                       # Each extra sample is a whole extra smoothscale +
                       # array read per rendered frame, hence the hard cap.
                       Field("sample_count", "Samples", "int", 4, 2,
                             RADIAL_BLUR_MAX_SAMPLES, persist="always"),
                       *_SCREEN_EFFECT_TWEEN_FIELDS,
                       *_UNTARGETED_COMMON_FIELDS),
               gd_object_id=2914, verification="partial"),
    ObjectSpec(T_MOTION_BLUR_TRIGGER, "Motion Blur Trigger", "Blends the "
               "last Frames rendered frames into the current one at "
               "Strength, over Duration.", C_MOTION_BLUR_TRIGGER, CAT_CAMERA,
               fields=(_F_EFFECT_STATE,
                       Field("strength", "Strength", "float", 0.5, 0.0, 1.0,
                             step=0.1, decimals=2, persist="always"),
                       # Each retained frame is a full-screen buffer held
                       # for the effect's lifetime, hence the hard cap.
                       Field("frame_count", "Frames", "int", 3, 2,
                             MOTION_BLUR_MAX_FRAMES, persist="always"),
                       *_SCREEN_EFFECT_TWEEN_FIELDS,
                       *_UNTARGETED_COMMON_FIELDS),
               gd_object_id=2915, verification="partial"),
    # Bulge/Pinch share a spec shape and one render branch (they differ
    # only in the sign of the radial displacement). Center X/Y are
    # OFFSETS in pixels from screen center, not absolute screen
    # coordinates: that makes the overwhelmingly common "centered"
    # authoring the 0 default, so persist="non_default" keeps it out of
    # save files entirely. Radius is in screen pixels -- the only other
    # screen effect with a spatial extent, Pixelate's pixel_size, is in
    # px too, so px is this family's unit.
    ObjectSpec(T_BULGE_TRIGGER, "Bulge Trigger", "Magnifies the frame "
               "outward from Center within Radius px, by Strength, over "
               "Duration.", C_BULGE_TRIGGER, CAT_CAMERA,
               fields=(_F_EFFECT_STATE,
                       Field("strength", "Strength", "float", 0.5, 0.0, 1.0,
                             step=0.1, decimals=2, persist="always"),
                       Field("radius", "Radius (px)", "float", 240.0, 16.0,
                             4000.0, step=20.0, decimals=1,
                             persist="always"),
                       Field("center_x", "Center X offset (px)", "int", 0,
                             -4000, 4000, step=10, persist="non_default"),
                       Field("center_y", "Center Y offset (px)", "int", 0,
                             -4000, 4000, step=10, persist="non_default"),
                       *_SCREEN_EFFECT_TWEEN_FIELDS,
                       *_UNTARGETED_COMMON_FIELDS),
               gd_object_id=2916, verification="partial"),
    ObjectSpec(T_PINCH_TRIGGER, "Pinch Trigger", "Squeezes the frame "
               "inward toward Center within Radius px, by Strength, over "
               "Duration.", C_PINCH_TRIGGER, CAT_CAMERA,
               fields=(_F_EFFECT_STATE,
                       Field("strength", "Strength", "float", 0.5, 0.0, 1.0,
                             step=0.1, decimals=2, persist="always"),
                       Field("radius", "Radius (px)", "float", 240.0, 16.0,
                             4000.0, step=20.0, decimals=1,
                             persist="always"),
                       Field("center_x", "Center X offset (px)", "int", 0,
                             -4000, 4000, step=10, persist="non_default"),
                       Field("center_y", "Center Y offset (px)", "int", 0,
                             -4000, 4000, step=10, persist="non_default"),
                       *_SCREEN_EFFECT_TWEEN_FIELDS,
                       *_UNTARGETED_COMMON_FIELDS),
               gd_object_id=2917, verification="partial"),
    # BEST-EFFORT. deep-research-report.md lists Split Screen's object id
    # (2924) but its exact fields are "unspecified" in the report's
    # verified mapping, so only the visually obvious reading is
    # implemented: split the frame on one axis and mirror the first half
    # onto the second. Axis is an engine-invented field with no claimed
    # GD equivalent (gd_key=None). Do not upgrade this to invented
    # precision without a source.
    ObjectSpec(T_SPLIT_SCREEN_TRIGGER, "Split Screen Trigger", "Mirrors "
               "the first half of the frame onto the second across Axis, "
               "blended by Intensity, over Duration.",
               C_SPLIT_SCREEN_TRIGGER, CAT_CAMERA,
               fields=(_F_EFFECT_STATE,
                       Field("axis", "Axis", "choice", "vertical",
                             choices=("vertical", "horizontal"),
                             persist="always", gd_key=None,
                             verification="unverified"),
                       *_SCREEN_EFFECT_TWEEN_FIELDS,
                       *_UNTARGETED_COMMON_FIELDS),
               gd_object_id=2924, verification="partial"),
    # ---- Area family (Checkpoint 2) -----------------------------------
    # An Area trigger starts a *continuous* effect: every tick, every
    # member of Target group is transformed by how close it sits to
    # Center group's centroid -- full strength within Length grid
    # squares, fading to nothing Length +/- squares past that. Unlike
    # Move/Rotate/Scale, which tween a group once and finish, an area
    # effect keeps running until an Area Stop with the same Effect id
    # ends it, and an Edit Area with that id can retune it mid-flight.
    _area_spec(T_AREA_MOVE_TRIGGER, "Area Move", "Drifts objects near "
               "Center group at Move x/y grid squares per second, scaled "
               "by how deep inside Length they are.", 3006,
               (Field("dx", "Move x (grid/s)", "int", 0, -200, 200,
                      persist="always"),
                Field("dy", "Move y (grid/s)", "int", 0, -200, 200,
                      persist="always"))),
    _area_spec(T_AREA_ROTATE_TRIGGER, "Area Rotate", "Spins objects near "
               "Center group at Rotate degrees per second, scaled by how "
               "deep inside Length they are.", 3007,
               (Field("degrees", "Rotate (deg/s)", "float", 90.0, -3600.0,
                      3600.0, step=15.0, decimals=1, persist="always"),)),
    _area_spec(T_AREA_SCALE_TRIGGER, "Area Scale", "Scales objects near "
               "Center group toward Scale X/Y — full scale at the center, "
               "unscaled beyond Length.", 3008,
               (Field("sx", "Scale X", "float", 1.0, 0.1, 8.0, step=0.05,
                      decimals=2, persist="always"),
                Field("sy", "Scale Y", "float", 1.0, 0.1, 8.0, step=0.05,
                      decimals=2, persist="always"))),
    _area_spec(T_AREA_FADE_TRIGGER, "Area Fade", "Fades objects near Center "
               "group toward Target alpha — fully faded at the center, "
               "fully opaque beyond Length.", 3009,
               (Field("target_alpha", "Target alpha", "float", 0.0, 0.0, 1.0,
                      step=0.05, decimals=2, persist="always"),)),
    _area_spec(T_AREA_TINT_TRIGGER, "Area Tint", "Tints objects near Center "
               "group toward a color channel — full tint at the center, "
               "untinted beyond Length.", 3010,
               (Field("target_channel", "Tint channel", "int", 0, 0, None,
                      persist="always"),)),
    # Edit Area: same field set as the variant it edits (the report is
    # explicit that these MODIFY an effect identified by Effect id and
    # never create one), so every parameter of a live effect is
    # retunable mid-flight. Firing one whose Effect id has no live
    # effect does nothing at all.
    _area_spec(T_EDIT_AREA_MOVE_TRIGGER, "Edit Area Move", "Retunes the "
               "live Area Move effect with this Effect id. No-op if none "
               "is running.", 3011,
               (Field("dx", "Move x (grid/s)", "int", 0, -200, 200,
                      persist="always"),
                Field("dy", "Move y (grid/s)", "int", 0, -200, 200,
                      persist="always")), color=C_EDIT_AREA_TRIGGER),
    _area_spec(T_EDIT_AREA_ROTATE_TRIGGER, "Edit Area Rotate", "Retunes the "
               "live Area Rotate effect with this Effect id. No-op if none "
               "is running.", 3012,
               (Field("degrees", "Rotate (deg/s)", "float", 90.0, -3600.0,
                      3600.0, step=15.0, decimals=1, persist="always"),),
               color=C_EDIT_AREA_TRIGGER),
    _area_spec(T_EDIT_AREA_SCALE_TRIGGER, "Edit Area Scale", "Retunes the "
               "live Area Scale effect with this Effect id. No-op if none "
               "is running.", 3013,
               (Field("sx", "Scale X", "float", 1.0, 0.1, 8.0, step=0.05,
                      decimals=2, persist="always"),
                Field("sy", "Scale Y", "float", 1.0, 0.1, 8.0, step=0.05,
                      decimals=2, persist="always")),
               color=C_EDIT_AREA_TRIGGER),
    _area_spec(T_EDIT_AREA_FADE_TRIGGER, "Edit Area Fade", "Retunes the "
               "live Area Fade effect with this Effect id. No-op if none "
               "is running.", 3014,
               (Field("target_alpha", "Target alpha", "float", 0.0, 0.0, 1.0,
                      step=0.05, decimals=2, persist="always"),),
               color=C_EDIT_AREA_TRIGGER),
    _area_spec(T_EDIT_AREA_TINT_TRIGGER, "Edit Area Tint", "Retunes the "
               "live Area Tint effect with this Effect id. No-op if none "
               "is running.", 3015,
               (Field("target_channel", "Tint channel", "int", 0, 0, None,
                      persist="always"),), color=C_EDIT_AREA_TRIGGER),
    # Area Stop carries no area vocabulary of its own -- only the Effect
    # id to end (report: "Stop Area effect by EffectID") plus the
    # activation fields every trigger needs. No target group: what it
    # acts on is already recorded in the effect it ends.
    ObjectSpec(T_AREA_STOP_TRIGGER, "Area Stop", "Ends the live area effect "
               "with this Effect id, wherever it was started from.",
               C_AREA_STOP_TRIGGER, CAT_AREA,
               fields=(_F_EFFECT_ID, _F_TOUCH_ACTIVATED, _F_MULTI_ACTIVATE,
                       _F_TRIGGER_ORDER),
               gd_object_id=3024, verification="partial"),
    # ---- Audio family (Checkpoint 5) ----------------------------------
    # deep-research-report.md, "Audio, timers, and arithmetic". Song/SFX
    # start playback of one of the project's OWN bundled tracks/sounds --
    # the licensed GD song and SFX libraries are explicitly out of scope,
    # so `song` indexes music.get_tracks() and `sfx` chooses from
    # sfx.SOUND_NAMES. Edit Song/Edit SFX patch live audio addressed by
    # channel / unique id and never start any, exactly like Edit Area.
    #
    # `song` is an INDEX, not a filename, unlike the level's own music
    # meta field: the track list is scanned at runtime (a player can
    # import their own files, and the three generated chiptunes are
    # always last), while a choice Field's options must be a fixed tuple
    # at import time. An index is also the form music.py already uses for
    # a stored track selection -- prefs' "menu_track" is exactly this.
    ObjectSpec(T_SONG_TRIGGER, "Song Trigger", "Plays bundled track "
               "#Song on a song channel. Speed and End are stored but "
               "have no effect (no playback-rate or scheduled-stop "
               "primitive exists).", C_SONG_TRIGGER, CAT_AUDIO,
               fields=(Field("song", "Song (track index)", "int", 0, 0, None,
                             persist="always", gd_key=392,
                             verification="verified"),
                       _F_SONG_CHANNEL, _F_AUDIO_VOLUME, _F_AUDIO_SPEED,
                       Field("start", "Start (s)", "float", 0.0, 0.0,
                             AUDIO_TIME_MAX_SECONDS, step=1.0, decimals=2,
                             persist="always", gd_key=408,
                             verification="verified"),
                       Field("end", "End (s, stored, no-op)", "float", 0.0,
                             0.0, AUDIO_TIME_MAX_SECONDS, step=1.0,
                             decimals=2, persist="always", gd_key=410,
                             verification="verified"),
                       Field("fade_in", "Fade in (s)", "float", 0.0, 0.0,
                             AUDIO_FADE_MAX_SECONDS, step=0.1, decimals=2,
                             persist="always", gd_key=409,
                             verification="verified"),
                       Field("fade_out", "Fade out (s)", "float", 0.0, 0.0,
                             AUDIO_FADE_MAX_SECONDS, step=0.1, decimals=2,
                             persist="always", gd_key=411,
                             verification="verified"),
                       _AUDIO_LOOP_FIELD, *_UNTARGETED_COMMON_FIELDS),
               gd_object_id=1934, verification="partial"),
    # The report lists SFX's own sound-id key among the audio-domain keys
    # it says SFX "reuses" without naming which one it is, so `sfx` gets
    # gd_key=None rather than a guessed 392 -- the honest reading, and the
    # field is a name here anyway, not a numeric library id.
    ObjectSpec(T_SFX_TRIGGER, "SFX Trigger", "Plays one of the built-in "
               "sound effects. Give it a nonzero Unique id to loop it or "
               "to let an Edit SFX Trigger reach it. Pitch and Reverb are "
               "stored but have no effect (no pitch-shift or DSP stage "
               "exists).", C_SFX_TRIGGER, CAT_AUDIO,
               fields=(Field("sfx", "Sound", "choice", _SFX_SOUND_NAMES[0],
                             choices=_SFX_SOUND_NAMES, persist="always",
                             gd_key=None, verification="unverified"),
                       _F_AUDIO_VOLUME, _F_AUDIO_PITCH,
                       Field("reverb", "Reverb (stored, no-op)", "float", 0.0,
                             0.0, 1.0, step=0.05, decimals=2,
                             persist="always", gd_key=407,
                             verification="verified"),
                       _AUDIO_LOOP_FIELD, _F_SFX_UNIQUE_ID,
                       *_UNTARGETED_COMMON_FIELDS),
               gd_object_id=3602, verification="partial"),
    ObjectSpec(T_EDIT_SONG_TRIGGER, "Edit Song Trigger", "Patches the song "
               "playing on this channel — Volume takes effect, Speed is "
               "stored only, Stop ends it (fading out over the song's own "
               "Fade out). No-op if that channel has no song.",
               C_EDIT_SONG_TRIGGER, CAT_AUDIO,
               fields=(_F_SONG_CHANNEL, _F_AUDIO_STOP, _F_AUDIO_VOLUME,
                       _F_AUDIO_SPEED, *_UNTARGETED_COMMON_FIELDS),
               gd_object_id=3605, verification="partial"),
    ObjectSpec(T_EDIT_SFX_TRIGGER, "Edit SFX Trigger", "Patches the sound "
               "playing under this Unique id — Volume takes effect, Pitch "
               "is stored only, Stop ends it. No-op if nothing is playing "
               "under that id.", C_EDIT_SFX_TRIGGER, CAT_AUDIO,
               fields=(_F_SFX_UNIQUE_ID, _F_AUDIO_STOP, _F_AUDIO_VOLUME,
                       _F_AUDIO_PITCH, *_UNTARGETED_COMMON_FIELDS),
               gd_object_id=3603, verification="partial"),
    # ---- Player-state family (Checkpoint 6) ---------------------------
    # deep-research-report.md, "Gameplay, camera, UI, and environment":
    # Gameplay Rotation 2900, Reverse 1917, Teleport 3022, Checkpoint 2063.
    # These four act on the PLAYER (direction, gravity, velocity, position,
    # practice checkpoint), which is why they carry no transform fields;
    # they are still ordinary group-fired triggers, activated by touch or by
    # a Spawn/Sequence/Repeat chain like everything else in CAT_TRIGGERS.
    #
    # target_group rides in via _TRIGGER_COMMON_FIELDS for all four -- for
    # Teleport it names the DESTINATION object (see triggers.py's
    # _apply_teleport_trigger); for the other three it is unused, kept only
    # so the whole family shares one activation vocabulary.
    #
    # KNOWN GD QUIRK, deliberately not reproduced: the Wiki documents a bug
    # where a Gameplay Rotation trigger that is NOT touch/spawn-triggered
    # interferes with camera triggers active from level start. This engine
    # has no such interaction (the camera family is untouched by these
    # handlers) and the report describes it as a bug, not a behaviour to
    # match, so it is recorded here and nowhere else.
    ObjectSpec(T_GAMEPLAY_ROTATION_TRIGGER, "Gameplay Rotation",
               "Retargets the player: gameplay direction, gravity "
               "direction, and an optional vertical velocity override. "
               "Each field's 'none' leaves that part of the player alone.",
               C_GAMEPLAY_ROTATION_TRIGGER, CAT_TRIGGERS,
               fields=(Field("direction", "Direction", "choice", "none",
                             choices=("none", "forward", "reverse", "flip"),
                             persist="always"),
                       Field("gravity_dir", "Gravity", "choice", "none",
                             choices=("none", "up", "down"),
                             persist="always"),
                       # 0 = leave velocity alone, so there is deliberately
                       # no way to author "stop dead"; the report specifies
                       # only that the trigger CAN set player velocity, not
                       # how an unset value is distinguished from zero.
                       # Absolute screen space (+ = down), matching the vy
                       # sign convention everywhere else in the engine, so
                       # it does not silently mean two different things
                       # either side of a gravity flip.
                       Field("velocity_override", "Velocity (0 = keep)",
                             "float", 0.0, -GAMEPLAY_VELOCITY_MAX,
                             GAMEPLAY_VELOCITY_MAX, step=0.5, decimals=2,
                             persist="always"),
                       # The report's one hard default in this family
                       # ("the active gameplay channel ... defaults to 0")
                       # but it cites no property key for the field, and
                       # this engine has no channel gating to spend it on
                       # (no other trigger type carries a channel), so it
                       # is stored-only -- honest about being unverified
                       # rather than inventing a key or a gating rule.
                       Field("channel", "Gameplay channel (stored, no-op)",
                             "int", GAMEPLAY_CHANNEL_DEFAULT, 0,
                             GAMEPLAY_CHANNEL_MAX, persist="always",
                             gd_key=None, verification="unverified"),
                       *_TRIGGER_COMMON_FIELDS),
               gd_object_id=2900, verification="partial"),
    ObjectSpec(T_REVERSE_TRIGGER, "Reverse Trigger", "Flips the gameplay "
               "direction: the player auto-scrolls the other way until "
               "something flips it back.", C_REVERSE_TRIGGER, CAT_TRIGGERS,
               fields=_TRIGGER_COMMON_FIELDS,
               gd_object_id=1917, verification="partial"),
    # Distinct from the touch-based Teleport Orb / Portal pair: those are
    # linked by a shared group id and fire on contact; this one is fired
    # like any other trigger and snaps the player onto the first member of
    # its target group. x_only/y_only are best-effort names -- the report
    # documents the trigger as "player teleport/force redirect" and gives
    # no field map for it at all.
    ObjectSpec(T_TELEPORT_TRIGGER, "Teleport Trigger", "Snaps the player "
               "onto the first object in the target group. X only / Y only "
               "restrict the snap to that axis (both on = neither axis "
               "moves).", C_TELEPORT_TRIGGER, CAT_TRIGGERS,
               fields=(Field("x_only", "X only", "bool", False,
                             persist="always", gd_key=None,
                             verification="unverified"),
                       Field("y_only", "Y only", "bool", False,
                             persist="always", gd_key=None,
                             verification="unverified"),
                       *_TRIGGER_COMMON_FIELDS),
               gd_object_id=3022, verification="partial"),
    # The placeable counterpart to the transient T_CHECKPOINT marker at the
    # bottom of this list (which stays exactly as it was: category None,
    # never in the palette, stripped on save). This one only wires an
    # activation path into the existing Player.save_checkpoint().
    ObjectSpec(T_CHECKPOINT_TRIGGER, "Checkpoint Trigger", "Saves a "
               "practice checkpoint at the player's current state when "
               "activated. Does nothing outside practice mode.",
               C_CHECKPOINT_TRIGGER, CAT_TRIGGERS,
               fields=_TRIGGER_COMMON_FIELDS,
               gd_object_id=2063, verification="partial"),
    # ---- Environment / UI / event / end (Checkpoint 7) ----------------
    # deep-research-report.md, "Gameplay, camera, UI, and environment".
    # All seven sit in CAT_TRIGGERS beside T_BG_TRIGGER (their family's
    # existing member) rather than opening a CAT_ENVIRONMENT tab: the
    # editor's tab row is a single unwrapped line that already ends at
    # x=1124 of a 1200px window with 14 tabs -- see the CAT_AUDIO note
    # above, which called that the last tab that fits.
    #
    # The four scenery triggers carry _TRIGGER_COMMON_FIELDS (target_group
    # included) rather than _UNTARGETED_COMMON_FIELDS even though they act
    # on the scenery and not on a group: that is the vocabulary their
    # family's existing member T_BG_TRIGGER has always had, and this
    # checkpoint extends that family instead of splitting it in two.
    # (target_group is what a trigger ACTS ON; being FIRED by a Spawn
    # chain works off group MEMBERSHIP -- the "groups" list -- so nothing
    # here depends on the field.) The UI Trigger, which has no such
    # sibling, uses _UNTARGETED_COMMON_FIELDS like the camera/audio
    # families it resembles.
    #
    # STORED-ONLY, and deliberately so (same precedent as the Shader
    # Trigger's lowest_layer/highest_layer and the audio family's
    # speed/pitch/reverb): Change Ground and Change Middleground carry a
    # preset index that NOTHING reads back. BG_PRESETS is the only
    # environment palette table in this engine; the ground is drawn from
    # the fixed C_GROUND/C_GROUND_L/C_GROUND_DARK constants and the
    # middleground from graphics._MOUNTAIN_SHADES, neither of which is a
    # selectable table. Rather than invent two palettes the report says
    # nothing about, the field is authored, saved and round-tripped so a
    # level written in the report's vocabulary survives intact, and the
    # handler is an explicit documented no-op. Do not "helpfully" wire
    # these to a colour without adding a real preset table first.
    ObjectSpec(T_GROUND_TRIGGER, "Ground Trigger", "Selects a ground "
               "preset. Stored and saved, but this engine has no ground "
               "palette to select from, so nothing changes on screen.",
               C_GROUND_TRIGGER, CAT_TRIGGERS,
               fields=(Field("ground", "Ground preset (stored, no-op)",
                             "int", 0, 0, ENV_PRESET_MAX, persist="always",
                             gd_key=None, verification="unverified"),
                       *_TRIGGER_COMMON_FIELDS),
               gd_object_id=3030, verification="partial"),
    ObjectSpec(T_MG_TRIGGER, "MG Trigger", "Selects a middleground "
               "preset. Stored and saved, but this engine has no "
               "middleground palette to select from, so nothing changes "
               "on screen.", C_MG_TRIGGER, CAT_TRIGGERS,
               fields=(Field("mg", "MG preset (stored, no-op)", "int", 0, 0,
                             ENV_PRESET_MAX, persist="always", gd_key=None,
                             verification="unverified"),
                       *_TRIGGER_COMMON_FIELDS),
               gd_object_id=3031, verification="partial"),
    # REAL, unlike the two above: graphics.draw_bg already parallax-
    # scrolls the star field (background) and the mountain layers
    # (middleground) at fixed rates, so there is an existing rate to
    # scale. speed/default is the multiplier -- see Player.bg_scroll_scale
    # -- which is why the defaults below have to be the report's exact
    # numbers: they are the identity point of the whole model, and a
    # level that never fires one of these renders exactly as it did
    # before this checkpoint.
    ObjectSpec(T_BG_SPEED_TRIGGER, "BG Speed", "Sets how fast the "
               "background parallax layer scrolls, relative to the "
               "camera. 0.1 / 0.1 is the default rate; 0 freezes the "
               "layer and a negative value drifts it the other way.",
               C_BG_SPEED_TRIGGER, CAT_TRIGGERS,
               fields=(Field("speed_x", "Speed x", "float",
                             BG_SPEED_DEFAULT_X, ENV_SPEED_MIN,
                             ENV_SPEED_MAX, step=0.05, decimals=2,
                             persist="always", gd_key=None,
                             verification="verified"),
                       Field("speed_y", "Speed y", "float",
                             BG_SPEED_DEFAULT_Y, ENV_SPEED_MIN,
                             ENV_SPEED_MAX, step=0.05, decimals=2,
                             persist="always", gd_key=None,
                             verification="verified"),
                       *_TRIGGER_COMMON_FIELDS),
               gd_object_id=3606, verification="partial"),
    ObjectSpec(T_MG_SPEED_TRIGGER, "MG Speed", "Sets how fast the "
               "middleground (mountain) parallax layers scroll, relative "
               "to the camera. 0.3 / 0.5 is the default rate.",
               C_MG_SPEED_TRIGGER, CAT_TRIGGERS,
               fields=(Field("speed_x", "Speed x", "float",
                             MG_SPEED_DEFAULT_X, ENV_SPEED_MIN,
                             ENV_SPEED_MAX, step=0.05, decimals=2,
                             persist="always", gd_key=None,
                             verification="verified"),
                       Field("speed_y", "Speed y", "float",
                             MG_SPEED_DEFAULT_Y, ENV_SPEED_MIN,
                             ENV_SPEED_MAX, step=0.05, decimals=2,
                             persist="always", gd_key=None,
                             verification="verified"),
                       *_TRIGGER_COMMON_FIELDS),
               gd_object_id=3612, verification="partial"),
    # DELIBERATE SCOPE TRIM: real GD's UI Trigger anchors an arbitrary
    # object group to the camera as custom UI. This engine has no UI
    # layer to hang a group off, and building a generic one for a single
    # trigger is exactly the kind of speculative machinery this project
    # has trimmed before (Advanced Random's text entry, Checkpoint 3), so
    # the scope here is ONE camera-anchored text label per ``ui_id``,
    # rendered by the same play_render.render_hud pass that draws the
    # Item Counter rows -- read by id out of Player.ui_labels, exactly as
    # an Item Counter row is read by item id out of Player.items.
    #
    # ``text`` is a choice, not free text, for the reason recorded on
    # UI_TEXT_CHOICES in constants.py (Field has no free-text kind); the
    # engine renders whatever string the object carries, so only the
    # editor is capped.
    ObjectSpec(T_UI_TRIGGER, "UI Trigger", "Posts a text label on the "
               "HUD, offset from the screen centre. Firing another UI "
               "Trigger with the same UI id replaces that label; one "
               "with Show off clears it.", C_UI_TRIGGER, CAT_TRIGGERS,
               fields=(Field("ui_id", "UI id", "int", 0, 0, None,
                             persist="always", gd_key=None,
                             verification="unverified"),
                       Field("text", "Text", "choice", UI_TEXT_CHOICES[0],
                             choices=UI_TEXT_CHOICES, persist="always",
                             gd_key=None, verification="unverified"),
                       Field("x_offset", "Offset x (px)", "int", 0,
                             -UI_OFFSET_MAX, UI_OFFSET_MAX, step=10,
                             persist="always", gd_key=None,
                             verification="unverified"),
                       Field("y_offset", "Offset y (px)", "int", -80,
                             -UI_OFFSET_MAX, UI_OFFSET_MAX, step=10,
                             persist="always", gd_key=None,
                             verification="unverified"),
                       # 0 = stays until a UI Trigger with the same ui_id
                       # clears it (Show off) or replaces it.
                       Field("duration", "Duration (s, 0 = keep)", "float",
                             2.0, 0.0, UI_DURATION_MAX_SECONDS, step=0.5,
                             decimals=2, persist="always", gd_key=None,
                             verification="unverified"),
                       Field("state", "Show", "bool", True,
                             persist="always", gd_key=None,
                             verification="unverified"),
                       *_UNTARGETED_COMMON_FIELDS),
               gd_object_id=3613, verification="partial"),
    # The one trigger in the whole registry the ENGINE fires rather than
    # the player: it is registered by event_type at level start
    # (Player._arm_event_triggers, mirroring _arm_always_on_follows) and
    # activated from the code path that actually implements the event.
    # It still carries the standard activation vocabulary, so a touch or
    # a Spawn chain fires it too -- the event is an EXTRA path in, the
    # same way the End Trigger is an extra path into the win flag.
    #
    # verification="unverified" for the whole spec: the report gives this
    # trigger one line ("in-game events -> spawned group") and no field
    # map at all, so every field below is an engine choice. See
    # LEVEL_EVENTS in constants.py for why these five moments.
    ObjectSpec(T_EVENT_TRIGGER, "Event Trigger", "Fires its target group "
               "when the chosen in-game event happens (level start, "
               "death, win, checkpoint saved, checkpoint respawn).",
               C_EVENT_TRIGGER, CAT_TRIGGERS,
               fields=(Field("event_type", "Event", "choice",
                             LEVEL_EVENTS[0], choices=LEVEL_EVENTS,
                             persist="always", gd_key=None,
                             verification="unverified"),
                       *_TRIGGER_COMMON_FIELDS),
               gd_object_id=3604, verification="unverified"),
    # A SECOND ACTIVATION PATH into the existing win flag, not new win
    # logic: the handler sets the same Player.won the T_END finish wall
    # sets in core.py's _handle_interactions, and T_END itself is
    # untouched (it stays the touch-based finish line).
    ObjectSpec(T_END_TRIGGER, "End Trigger", "Ends the level when fired, "
               "exactly as crossing the Finish line does.",
               C_END_TRIGGER, CAT_TRIGGERS,
               fields=_TRIGGER_COMMON_FIELDS,
               gd_object_id=3600, verification="partial"),
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
    # Checkpoint 3 (deep-research-report.md, "Force and state
    # precedence"). Categorised with the letter blocks above, not with
    # the triggers: it targets no group, runs no handler and is absent
    # from TRIGGER_TYPES/TRIGGER_HANDLERS on purpose. Like S/J/D/H it is
    # a placed object whose effect fires from a direct contact test in
    # core.py's _handle_interactions.
    #
    # Every gd_key below is FlowVix's, quoted by the report; every
    # default/range is an engine choice, because the report cites the
    # field names and keys but no ranges or defaults for them. See
    # Player._apply_force_block for the application semantics each field
    # was given, and constants.FORCE_BLOCK_* for the numbers.
    ObjectSpec(T_FORCE_BLOCK, "Force Block", "Adds Force to the player's "
               "vertical velocity on contact. Blocks with different Force "
               "ids stack; blocks sharing a Force id apply only once per "
               "frame.", C_FORCE_BLOCK, CAT_EDITOR_UTILS,
               fields=(Field("relative", "Relative to gravity", "bool", False,
                             persist="always", gd_key=528,
                             verification="partial"),
                       Field("force", "Force (units/tick)", "float", 0.0,
                             -FORCE_BLOCK_MAX_FORCE, FORCE_BLOCK_MAX_FORCE,
                             step=0.5, decimals=2, persist="always",
                             gd_key=149, verification="partial"),
                       Field("min_force", "Min force (0 = none)", "float",
                             0.0, 0.0, FORCE_BLOCK_MAX_FORCE, step=0.5,
                             decimals=2, persist="always", gd_key=526,
                             verification="partial"),
                       Field("max_force", "Max force (0 = none)", "float",
                             0.0, 0.0, FORCE_BLOCK_MAX_FORCE, step=0.5,
                             decimals=2, persist="always", gd_key=527,
                             verification="partial"),
                       # Named force_range, not range: "range" as a dict
                       # key would read as the builtin at every call site
                       # that unpacks an object's fields.
                       Field("force_range", "Range (grid squares)", "float",
                             FORCE_BLOCK_DEFAULT_RANGE, 0.0,
                             FORCE_BLOCK_MAX_RANGE, step=0.25, decimals=2,
                             persist="always", gd_key=529,
                             verification="partial"),
                       Field("force_id", "Force id", "int", 0, 0, None,
                             persist="always", gd_key=530,
                             verification="partial")),
               gd_object_id=2069, verification="partial"),
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

# Real-GD-parity lookups (deep-research-report.md refactor, Checkpoint 0).
# Future-capability plumbing only -- nothing in the current engine reads
# these at runtime; see the hybrid-metadata decision on ObjectSpec above.
GD_ID_TO_TYPE = {s.gd_object_id: s.type for s in _SPEC_LIST
                 if s.gd_object_id is not None}


def gd_field_map(t):
    """``{gd_key: field_key}`` for type ``t``'s fields that carry a real GD
    numeric property key. Empty dict if the type or none of its fields have
    verified keys. Lazy/on-demand -- not cached, since it's not on any hot
    path."""
    spec = SPECS.get(t)
    if spec is None:
        return {}
    return {f.gd_key: f.key for f in spec.fields if f.gd_key is not None}


# ---------------------------------------------------------------------------
# Advanced Random's weighted list (Checkpoint 3)
# ---------------------------------------------------------------------------
# Serialization lives here, next to the schema, because the dot-separated
# string is the *storage* form and the editor's fixed slots are the UI
# form -- triggers.py only ever sees the parsed pairs.

def parse_weighted_list(text):
    """``"2.10.3.15"`` -> ``[(2, 10), (3, 15)]``.

    The report's format, read generically: dot-separated group/weight
    pairs, at most ``ADVANCED_RANDOM_MAX_PAIRS`` of them. Entries with a
    non-positive weight (an unused editor slot) or a non-positive group
    (no such group id exists) are dropped rather than kept at zero
    probability, so ``P(i) = 100 * w_i / sum(w_j)`` is computed over
    exactly the entries that can actually fire. A trailing unpaired
    token, or any token that is not an integer, is ignored.
    """
    if not text:
        return []
    parts = str(text).split(".")
    pairs = []
    for i in range(0, len(parts) - 1, 2):
        try:
            group = int(parts[i])
            weight = int(parts[i + 1])
        except (TypeError, ValueError):
            continue
        if group > 0 and weight > 0:
            pairs.append((group, weight))
        if len(pairs) >= ADVANCED_RANDOM_MAX_PAIRS:
            break
    return pairs


def format_weighted_list(pairs):
    """``[(2, 10), (3, 15)]`` -> ``"2.10.3.15"``.

    A true inverse of :func:`parse_weighted_list`: it drops exactly the
    entries that function drops (unused editor slots, non-positive
    groups), so an empty/unauthored trigger serializes to ``""`` rather
    than to a run of ``0.0`` pairs a real-GD importer would choke on.
    """
    out = []
    for group, weight in pairs:
        try:
            group = int(group)
            weight = int(weight)
        except (TypeError, ValueError):
            continue
        if group > 0 and weight > 0:
            out.append(f"{group}.{weight}")
        if len(out) >= ADVANCED_RANDOM_MAX_PAIRS:
            break
    return ".".join(out)


def advanced_random_weighted_list(obj):
    """The weighted-list string for one Advanced Random trigger.

    An explicit ``weighted_list`` string on the object wins (that is the
    full 20-pair form, reachable programmatically and preserved across
    saves by ``levels.normalize_object``); otherwise the property
    panel's ``group1``/``weight1``... slots are serialized into the same
    format. Either way the caller gets one string in the report's own
    encoding, so the weighted pick has a single code path.
    """
    text = obj.get("weighted_list")
    if isinstance(text, str) and text.strip():
        return text.strip()
    return format_weighted_list([
        (obj.get(f"group{i}", 0) or 0, obj.get(f"weight{i}", 0) or 0)
        for i in range(1, ADVANCED_RANDOM_EDITOR_SLOTS + 1)
    ])


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


def default_z_layer(t):
    """The Z-Layer an object sits on when the author never set one --
    decorations default behind gameplay (b1), everything else in front
    (t1), matching this engine's pre-Z-Layer draw order exactly."""
    return Z_LAYER_DECORATION_DEFAULT if t in DECORATION_TYPES else Z_LAYER_DEFAULT


def get_z_layer(obj):
    z = obj.get("z_layer")
    return z if z in Z_LAYER_INDEX else default_z_layer(obj.get("t"))


def get_z_order(obj):
    try:
        return int(obj.get("z_order", Z_ORDER_DEFAULT))
    except (TypeError, ValueError):
        return Z_ORDER_DEFAULT
