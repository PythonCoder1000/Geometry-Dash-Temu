"""Per-level physics parameters.

Historically every gameplay constant (gravity, jump force, wave angle,
etc.) lived as a module-level value in ``constants.py``. That made every
level play with identical feel, which is a design ceiling — GD itself
ships with explicit "speed portals" and level-specific physics quirks.

``PhysicsParams`` is a thin dataclass that defaults to the calibrated
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

Only declared dataclass fields are applied. Unknown keys and invalid or
non-finite values are ignored; numeric strings are accepted.
"""

from dataclasses import dataclass, fields
import math

# Unit-space (GD units / units-per-tick) constants — see
# docs/development/UNITS_REFACTOR.md. PhysicsParams now hands out values
# in real GD units so player/core.py's integration is unit-native; the
# legacy px-per-tick constants in constants.py remain only as the
# derivation source (value_ut * PX_PER_UNIT == value_px, exact).
from .constants import (
    GRAVITY_UT as _GRAVITY,
    SHIP_GRAVITY_UT as _SHIP_GRAVITY,
    SHIP_THRUST_UT as _SHIP_THRUST,
    JUMP_FORCE_UT as _JUMP_FORCE,
    PAD_FORCE_UT as _PAD_FORCE,
    BALL_FLIP_FORCE_UT as _BALL_FLIP_FORCE,
    DASH_SPEED as _DASH_SPEED,
    DASH_TIME as _DASH_TIME,
    WAVE_ANGLE as _WAVE_ANGLE,
    UFO_JUMP_FORCE_UT as _UFO_JUMP_FORCE,
    BASE_MOVE_SPEED_UT as _BASE_MOVE_SPEED,
    SPIDER_TELEPORT_RANGE as _SPIDER_TELEPORT_RANGE,
    ROBOT_THRUST_UT as _ROBOT_THRUST,
    ROBOT_FLIGHT_SECONDS as _ROBOT_FLIGHT_SECONDS,
    MINI_GRAVITY_SCALE as _MINI_GRAVITY_SCALE,
    MINI_JUMP_SCALE as _MINI_JUMP_SCALE,
    MINI_WAVE_ANGLE_SCALE as _MINI_WAVE_ANGLE_SCALE,
    MINI_WAVE_VY_SCALE as _MINI_WAVE_VY_SCALE,
    SHIP_MAX_RISE_UT as SHIP_MAX_RISE, SHIP_MAX_FALL_UT as SHIP_MAX_FALL,
)


@dataclass(frozen=True)
class PhysicsParams:
    """Immutable bundle of every per-level-overrideable gameplay tunable.

    Defaults mirror the module-level calibration constants. A missing
    ``meta.physics`` block always selects the current default behavior.
    """
    gravity: float = _GRAVITY
    ship_gravity: float = _SHIP_GRAVITY
    ship_thrust: float = _SHIP_THRUST
    jump_force: float = _JUMP_FORCE
    pad_force: float = _PAD_FORCE
    ball_flip_force: float = _BALL_FLIP_FORCE
    # Kept only so old level ``meta.physics`` overrides still round-trip.
    # A dash now moves at the player's current ``move_speed`` (so it can
    # never desync from the music) instead of this fixed value.
    dash_speed: float = _DASH_SPEED
    dash_time: int = _DASH_TIME
    wave_angle: float = _WAVE_ANGLE
    ufo_jump_force: float = _UFO_JUMP_FORCE
    base_move_speed: float = _BASE_MOVE_SPEED
    spider_teleport_range: int = _SPIDER_TELEPORT_RANGE
    robot_thrust: float = _ROBOT_THRUST
    robot_flight_seconds: float = _ROBOT_FLIGHT_SECONDS
    # Additional mini-only tuning; mode-specific factors are applied in
    # the shared movement code. Ground jump defaults scale to 0.8.
    mini_gravity_scale: float = _MINI_GRAVITY_SCALE
    mini_jump_scale: float = _MINI_JUMP_SCALE
    mini_wave_angle_scale: float = _MINI_WAVE_ANGLE_SCALE
    mini_wave_vy_scale: float = _MINI_WAVE_VY_SCALE

    def wave_velocity(self, speed, grav, mini, held):
        """Instant diagonal velocity shared by gameplay and bot previews.

        mini_wave_angle_scale is retained for old level files. New files
        should use mini_wave_vy_scale; an explicit old angle override is
        interpreted as a path angle rather than a cosmetic-only change.
        """
        angle = self.wave_angle
        scale = self.mini_wave_vy_scale if mini else 1.0
        if mini and self.mini_wave_angle_scale != _MINI_WAVE_ANGLE_SCALE:
            angle *= self.mini_wave_angle_scale
            scale /= _MINI_WAVE_VY_SCALE
        slope = math.tan(math.radians(max(0.0, min(89.0, angle))))
        return speed * slope * scale * grav * (-1 if held else 1)

    def ship_velocity(self, vy, grav, mini, held):
        """One ship tick, including momentum-dependent acceleration/caps."""
        falling = vy * grav > 0
        size_factor = 1.0 / 0.85 if mini else 1.0
        gmul = self.mini_gravity_scale if mini else 1.0
        if held:
            accel = (self.ship_gravity - self.ship_thrust) * (1.25 if falling else 1.0)
        else:
            accel = self.ship_gravity * (0.8 if falling else 1.2)
        local_vy = vy * grav + accel * size_factor * gmul
        return max(-SHIP_MAX_RISE * size_factor,
                   min(SHIP_MAX_FALL * size_factor, local_vy)) * grav

    @classmethod
    def from_meta(cls, meta):
        """Build params from a level meta dict. None / missing → defaults."""
        if not isinstance(meta, dict):
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
        if not isinstance(data, dict):
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
                    value = type(default)(raw)
                    if not math.isfinite(value):
                        continue
                    # All magnitudes are nonnegative; run speed and mini
                    # scales must be positive. Impulses use screen-space
                    # negatives and may be zero to disable jumping.
                    if f.name in ("jump_force", "pad_force", "ufo_jump_force"):
                        if value > 0:
                            continue
                    elif value < 0:
                        continue
                    if (f.name == "base_move_speed" or f.name.startswith("mini_")) and value == 0:
                        continue
                    if f.name == "wave_angle" and value >= 90:
                        continue
                    kwargs[f.name] = value
            except (TypeError, ValueError, OverflowError):
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
