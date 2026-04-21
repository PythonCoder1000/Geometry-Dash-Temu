"""Per-level physics parameters.

Historically every gameplay constant (gravity, jump force, wave angle,
etc.) lived as a module-level value in ``constants.py``. That made every
level play with identical feel, which is a design ceiling — GD itself
ships with explicit "speed portals" and level-specific physics quirks.

``PhysicsParams`` is a thin dataclass that defaults to the historical
constants and is passed into ``Player``. Each gameplay site that used to
read ``GRAVITY`` now reads ``self.params.gravity``. Per-level overrides
are loaded from the level JSON's ``meta["physics"]`` dict — an absent
field, an empty dict, or a missing key each fall through to the default.

The wire-format is a flat dict:

    {
      ...level meta...,
      "physics": {
        "gravity": 0.8,
        "wave_angle": 60.0
      }
    }

Unknown keys are ignored by :meth:`PhysicsParams.from_meta` so a newer
save file can still round-trip through an older client. Only the keys
listed in :attr:`PhysicsParams._FIELDS` are applied; each value is
coerced through the default's type so a malformed "1.0" string doesn't
crash the physics loop.
"""

from dataclasses import dataclass, fields, asdict

from .constants import (
    GRAVITY as _GRAVITY,
    SHIP_GRAVITY as _SHIP_GRAVITY,
    SHIP_THRUST as _SHIP_THRUST,
    JUMP_FORCE as _JUMP_FORCE,
    PAD_FORCE as _PAD_FORCE,
    BALL_FLIP_FORCE as _BALL_FLIP_FORCE,
    DASH_SPEED as _DASH_SPEED,
    DASH_TIME as _DASH_TIME,
    WAVE_ANGLE as _WAVE_ANGLE,
    UFO_JUMP_FORCE as _UFO_JUMP_FORCE,
    BASE_MOVE_SPEED as _BASE_MOVE_SPEED,
    SPIDER_TELEPORT_RANGE as _SPIDER_TELEPORT_RANGE,
)


@dataclass(frozen=True)
class PhysicsParams:
    """Immutable bundle of every per-level-overrideable gameplay tunable.

    Defaults mirror the module-level constants so a level without a
    ``meta.physics`` block plays identically to levels authored before
    this abstraction existed.
    """
    gravity: float = _GRAVITY
    ship_gravity: float = _SHIP_GRAVITY
    ship_thrust: float = _SHIP_THRUST
    jump_force: float = _JUMP_FORCE
    pad_force: float = _PAD_FORCE
    ball_flip_force: float = _BALL_FLIP_FORCE
    dash_speed: float = _DASH_SPEED
    dash_time: int = _DASH_TIME
    wave_angle: float = _WAVE_ANGLE
    ufo_jump_force: float = _UFO_JUMP_FORCE
    base_move_speed: float = _BASE_MOVE_SPEED
    spider_teleport_range: int = _SPIDER_TELEPORT_RANGE

    @classmethod
    def from_meta(cls, meta):
        """Build params from a level meta dict. None / missing → defaults."""
        if not meta:
            return cls()
        overrides = meta.get("physics")
        if not overrides or not isinstance(overrides, dict):
            return cls()
        return cls.from_dict(overrides)

    @classmethod
    def from_dict(cls, data):
        """Build params from a bare dict of overrides (unknown keys ignored,
        values coerced through the default's type).
        """
        if not data:
            return cls()
        defaults = cls()
        kwargs = {}
        for f in fields(cls):
            if f.name not in data:
                continue
            raw = data[f.name]
            default = getattr(defaults, f.name)
            try:
                # bool is a subclass of int, so type(default)(raw) would
                # mean bool("False") == True (any non-empty string is
                # truthy). Parse strings explicitly before coercing.
                if isinstance(default, bool):
                    if isinstance(raw, str):
                        low = raw.strip().lower()
                        if low in ("true", "1", "yes", "on"):
                            kwargs[f.name] = True
                        elif low in ("false", "0", "no", "off", ""):
                            kwargs[f.name] = False
                        else:
                            continue
                    else:
                        kwargs[f.name] = bool(raw)
                else:
                    kwargs[f.name] = type(default)(raw)
            except (TypeError, ValueError):
                # Keep the default rather than crash — a malformed
                # override should degrade to vanilla physics, not brick
                # the level.
                continue
        return cls(**kwargs)

    def to_meta_dict(self):
        """Return a dict of fields that differ from defaults — meant for
        round-tripping to level JSON without bloating the meta block with
        redundant default values."""
        defaults = PhysicsParams()
        out = {}
        for f in fields(self):
            v = getattr(self, f.name)
            if v != getattr(defaults, f.name):
                out[f.name] = v
        return out


DEFAULT_PARAMS = PhysicsParams()
