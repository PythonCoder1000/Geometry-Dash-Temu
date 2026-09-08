"""Runtime user-settable knobs: a thin typed layer over :mod:`prefs`.

Everything exposed by the in-game Settings menu lives here so every
consumer (main loop, editor, audio) reads one authoritative place.
Level progress and similar mechanics stay in :mod:`levels`.

Timing: physics always ticks at :data:`PHYSICS_RATE` (240 Hz); the
render FPS cap is a free setting because the play loop interpolates
between physics ticks (see :mod:`play`).
"""

from . import prefs
from .constants import PHYSICS_TPS

PHYSICS_RATE = PHYSICS_TPS
# Kept as the default FPS cap for backwards compatibility with callers
# that import it.
GAME_RATE = 120

DEFAULTS = {
    "fps_cap": GAME_RATE,
    "fullscreen": False,
    "music_vol": 0.5,         # 0.0..1.0
    "sfx_vol": 0.5,           # 0.0..1.0
    "music_muted": False,
    "sfx_muted": False,
    "player_color_index": 0,  # index into constants.PLAYER_COLORS
    "player_icon_index": 0,   # index into constants.PLAYER_ICONS
}

# 0 = uncapped (pygame's clock.tick(0) never sleeps).
FPS_CAP_OPTIONS = [60, 120, 144, 240, 0]


# ---------------------------------------------------------------------------
# Coercion helpers: corrupted prefs always fall back to the default.
# ---------------------------------------------------------------------------

def _coerce_float_01(v, default):
    try:
        f = float(v)
    except (TypeError, ValueError, OverflowError):
        return default
    return min(1.0, max(0.0, f))


def _coerce_int(v, default):
    try:
        return int(v)
    except (TypeError, ValueError, OverflowError):
        return default


def _coerce_bool(v, default):
    if isinstance(v, bool):
        return v
    if v is None:
        return default
    if isinstance(v, str):
        value = v.strip().lower()
        if value in ("true", "1", "yes", "on"):
            return True
        if value in ("false", "0", "no", "off", ""):
            return False
        return default
    return bool(v)


# ---------------------------------------------------------------------------
# Frame rate
# ---------------------------------------------------------------------------

def get_fps_cap():
    """Render FPS cap for ``clock.tick()``; only whitelisted values count."""
    val = _coerce_int(prefs.get("fps_cap", DEFAULTS["fps_cap"]),
                      DEFAULTS["fps_cap"])
    return val if val in FPS_CAP_OPTIONS else DEFAULTS["fps_cap"]


def set_fps_cap(value):
    val = _coerce_int(value, DEFAULTS["fps_cap"])
    if val not in FPS_CAP_OPTIONS:
        val = DEFAULTS["fps_cap"]
    prefs.set("fps_cap", val)


def cycle_fps_cap():
    """Advance to the next option and return it."""
    cur = get_fps_cap()
    idx = FPS_CAP_OPTIONS.index(cur)
    new = FPS_CAP_OPTIONS[(idx + 1) % len(FPS_CAP_OPTIONS)]
    set_fps_cap(new)
    return new


def fps_cap_label(cap=None):
    cap = get_fps_cap() if cap is None else cap
    return "Uncapped" if cap == 0 else f"{cap} FPS"


def get_tps():
    """Physics ticks per second (fixed)."""
    return PHYSICS_RATE


# ---------------------------------------------------------------------------
# Display / audio
# ---------------------------------------------------------------------------

def get_fullscreen():
    return _coerce_bool(prefs.get("fullscreen", DEFAULTS["fullscreen"]),
                        DEFAULTS["fullscreen"])


def set_fullscreen(value):
    prefs.set("fullscreen", bool(value))


def toggle_fullscreen():
    new = not get_fullscreen()
    set_fullscreen(new)
    return new


def get_music_vol():
    return _coerce_float_01(prefs.get("music_vol", DEFAULTS["music_vol"]),
                            DEFAULTS["music_vol"])


def get_sfx_vol():
    return _coerce_float_01(prefs.get("sfx_vol", DEFAULTS["sfx_vol"]),
                            DEFAULTS["sfx_vol"])


def set_music_vol(value):
    """Persist the music volume and apply it to the live music module."""
    v = _coerce_float_01(value, DEFAULTS["music_vol"])
    prefs.set("music_vol", v)
    try:
        from . import music
        music.set_volume(v)
    except Exception:
        pass


def set_sfx_vol(value):
    v = _coerce_float_01(value, DEFAULTS["sfx_vol"])
    prefs.set("sfx_vol", v)


# ---------------------------------------------------------------------------
# Player cosmetics
# ---------------------------------------------------------------------------

def _get_index(key):
    val = _coerce_int(prefs.get(key, DEFAULTS[key]), DEFAULTS[key])
    # Not clamped to the palette length: Player applies the modulo, so
    # the prefs file stays valid if the palette grows or shrinks.
    return DEFAULTS[key] if val < 0 else val


def _set_index(key, value):
    val = _coerce_int(value, DEFAULTS[key])
    prefs.set(key, DEFAULTS[key] if val < 0 else val)


def get_player_color_index():
    return _get_index("player_color_index")


def set_player_color_index(value):
    _set_index("player_color_index", value)


def get_player_icon_index():
    return _get_index("player_icon_index")


def set_player_icon_index(value):
    _set_index("player_icon_index", value)


def reset_to_defaults():
    for k, v in DEFAULTS.items():
        prefs.set(k, v)
    try:
        from . import music
        music.set_volume(DEFAULTS["music_vol"])
    except Exception:
        pass
