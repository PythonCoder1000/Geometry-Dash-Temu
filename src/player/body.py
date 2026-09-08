"""Dual-mode mirror body.

The main player *is* the :class:`Player` instance; the mirror is a small
object holding the per-body physics state (everything except ``x``, which
both bodies share).  Attribute names deliberately match the main body's so
the physics code in :mod:`player.core` can step either one::

    body.vy += params.gravity * body.grav

For backwards compatibility with the bot snapshot code and older tests the
mirror also answers dict-style access (``m["y"]``, ``m.get("mode")``).
"""

from ..constants import MODE_CUBE, PLAYER_SIZE_UNITS, PX_PER_UNIT


class MirrorBody:
    __slots__ = ("y", "vy", "grav", "on_ground", "angle", "alive", "mode",
                 "size", "flight_budget", "thrust_disabled",
                 "wave_vy_smooth", "trail", "prev_y", "prev_angle")

    _DEFAULTS = {
        "y": 0.0, "vy": 0.0, "grav": -1, "on_ground": False, "angle": 0.0,
        "alive": True, "mode": MODE_CUBE, "size": PLAYER_SIZE_UNITS,
        "flight_budget": 0, "thrust_disabled": False, "wave_vy_smooth": 0.0,
    }

    def __init__(self, **kw):
        for k, v in self._DEFAULTS.items():
            setattr(self, k, kw.get(k, v))
        self.trail = []
        self.prev_y = float(self.y)
        self.prev_angle = float(self.angle)

    @classmethod
    def from_dict(cls, d):
        kw = dict(d)
        if "thrust_disabled" not in kw and "_robot_thrust_disabled" in kw:
            kw["thrust_disabled"] = kw.pop("_robot_thrust_disabled")
        return cls(**{k: v for k, v in kw.items() if k in cls._DEFAULTS})

    # ---- dict compatibility --------------------------------------------
    def __getitem__(self, key):
        try:
            return getattr(self, key)
        except AttributeError:
            raise KeyError(key) from None

    def __setitem__(self, key, value):
        if key not in self._DEFAULTS:
            raise KeyError(key)
        setattr(self, key, value)

    def __contains__(self, key):
        return key in self._DEFAULTS

    def get(self, key, default=None):
        return getattr(self, key, default) if key in self._DEFAULTS else default

    def to_dict(self):
        return {k: getattr(self, k) for k in self._DEFAULTS}

    # ---- render-space (px) compatibility --------------------------------
    @property
    def y_px(self):
        return self.y * PX_PER_UNIT

    @property
    def size_px(self):
        return self.size * PX_PER_UNIT

    def __repr__(self):
        return f"MirrorBody({self.to_dict()})"
