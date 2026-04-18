"""Runtime user-settable knobs — thin typed layer over `prefs`.

These are the things exposed by the in-game Settings menu. Storing them all
here gives every consumer (the main loop, editor, audio modules) a single
authoritative place to read from, and keeps the keys/defaults in one spot
so the rest of the codebase doesn't have to remember "is it 60 or 144?".

Anything more game-mechanical (level progress, best times, etc.) stays in
`levels.py` — this module is strictly for player preferences.
"""

import prefs
from constants import FPS as DEFAULT_FPS

# ---------------------------------------------------------------------------
# Defaults — also serve as the "Reset to defaults" target.
# ---------------------------------------------------------------------------
DEFAULTS = {
    "fps_cap": DEFAULT_FPS,   # 0 means "uncapped" (passes 0 to clock.tick)
    "fullscreen": False,
    "music_vol": 0.5,         # 0.0..1.0
    "sfx_vol": 0.5,           # 0.0..1.0
    "music_muted": False,
    "sfx_muted": False,
    "player_color_index": 0,  # index into constants.PLAYER_COLORS
    "player_icon_index": 0,   # index into constants.PLAYER_ICONS
}

# Whitelist of FPS caps the UI cycles through. 0 means "no cap".
FPS_CAP_OPTIONS = [30, 60, 75, 120, 144, 240, 0]


# ---------------------------------------------------------------------------
# Typed accessors. Defensive: corrupted/missing prefs always fall back to the
# default rather than throwing or returning None.
# ---------------------------------------------------------------------------

def _coerce_float_01(v, default):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    if f < 0.0:
        return 0.0
    if f > 1.0:
        return 1.0
    return f


def _coerce_int(v, default):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _coerce_bool(v, default):
    if isinstance(v, bool):
        return v
    if v is None:
        return default
    return bool(v)


def get_fps_cap():
    """Return the cap to pass to `clock.tick()`. 0 means uncapped."""
    raw = prefs.get("fps_cap", DEFAULTS["fps_cap"])
    val = _coerce_int(raw, DEFAULTS["fps_cap"])
    if val < 0:
        return DEFAULTS["fps_cap"]
    if val == 0:
        return 0
    # Clamp to a sane range so a corrupted pref can't freeze the game.
    return max(15, min(1000, val))


def set_fps_cap(value):
    """Persist the FPS cap (0 = uncapped). Coerces invalid input to default."""
    val = _coerce_int(value, DEFAULTS["fps_cap"])
    if val < 0:
        val = DEFAULTS["fps_cap"]
    prefs.set("fps_cap", val)


def cycle_fps_cap():
    """Advance to the next option in `FPS_CAP_OPTIONS`. Returns the new cap."""
    cur = get_fps_cap()
    try:
        idx = FPS_CAP_OPTIONS.index(cur)
    except ValueError:
        idx = -1
    new = FPS_CAP_OPTIONS[(idx + 1) % len(FPS_CAP_OPTIONS)]
    set_fps_cap(new)
    return new


def fps_cap_label(cap=None):
    """Human-friendly label for an FPS cap value."""
    if cap is None:
        cap = get_fps_cap()
    return "Unlimited" if cap == 0 else f"{cap}"


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
    # music.py owns the live volume but the persistence key matches so the
    # two stay aligned. Returning prefs gives the menu a snapshot to show.
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
        import music
        music.set_volume(v)
    except Exception:
        pass


def set_sfx_vol(value):
    """Persist the SFX volume. Applied at next play() call (per-sound vol)."""
    v = _coerce_float_01(value, DEFAULTS["sfx_vol"])
    prefs.set("sfx_vol", v)


def get_player_color_index():
    """Return the persistent starting color index for the player."""
    raw = prefs.get("player_color_index", DEFAULTS["player_color_index"])
    val = _coerce_int(raw, DEFAULTS["player_color_index"])
    if val < 0:
        return DEFAULTS["player_color_index"]
    # Don't clamp by len(PLAYER_COLORS) here — Player applies the modulo so
    # it always picks a real color. This keeps the prefs file forward-
    # compatible if the palette later grows or shrinks.
    return val


def set_player_color_index(value):
    val = _coerce_int(value, DEFAULTS["player_color_index"])
    if val < 0:
        val = DEFAULTS["player_color_index"]
    prefs.set("player_color_index", val)


def get_player_icon_index():
    """Return the persistent player icon (cube glyph) index."""
    raw = prefs.get("player_icon_index", DEFAULTS["player_icon_index"])
    val = _coerce_int(raw, DEFAULTS["player_icon_index"])
    if val < 0:
        return DEFAULTS["player_icon_index"]
    return val


def set_player_icon_index(value):
    val = _coerce_int(value, DEFAULTS["player_icon_index"])
    if val < 0:
        val = DEFAULTS["player_icon_index"]
    prefs.set("player_icon_index", val)


def reset_to_defaults():
    """Restore every key managed here to its default value."""
    for k, v in DEFAULTS.items():
        prefs.set(k, v)
    # Push live audio values too so the change is audible right away.
    try:
        import music
        music.set_volume(DEFAULTS["music_vol"])
    except Exception:
        pass
