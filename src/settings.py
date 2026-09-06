"""Runtime user-settable knobs — thin typed layer over `prefs`.

These are the things exposed by the in-game Settings menu. Storing them all
here gives every consumer (the main loop, editor, audio modules) a single
authoritative place to read from, and keeps the keys/defaults in one spot
so the rest of the codebase doesn't have to remember "is it 60 or 144?".

Anything more game-mechanical (level progress, best times, etc.) stays in
`levels.py` — this module is strictly for player preferences.
"""

from . import prefs
from .constants import FPS as DEFAULT_FPS

# ---------------------------------------------------------------------------
# Defaults — also serve as the "Reset to defaults" target.
# ---------------------------------------------------------------------------
# Single locked rate that drives both render FPS and simulation TPS. Was
# previously two independent knobs (a 30 Hz monitor could run physics at
# 240 Hz, etc.) but the cycle UI was too easy to leave in a misaligned
# state. The locked value is exposed through both ``get_fps_cap`` and
# ``get_tps`` so existing callsites keep working — they always see the
# same number, so the render loop emits exactly one physics tick per
# rendered frame.
GAME_RATE = 120

DEFAULTS = {
    "fps_cap": GAME_RATE,
    "tps": GAME_RATE,
    "fullscreen": False,
    "music_vol": 0.5,         # 0.0..1.0
    "sfx_vol": 0.5,           # 0.0..1.0
    "music_muted": False,
    "sfx_muted": False,
    "player_color_index": 0,  # index into constants.PLAYER_COLORS
    "player_icon_index": 0,   # index into constants.PLAYER_ICONS
}

# Both options lists collapse to the single locked value — the cycle
# helpers below stay no-ops, so the menu's "FPS cap" button still
# clicks but the value never changes. Tests that probe the option
# list still see a non-empty whitelist.
FPS_CAP_OPTIONS = [GAME_RATE]
TPS_OPTIONS = [GAME_RATE]


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
    """Return the locked render-rate cap to pass to ``clock.tick()``.

    Was a free knob; now hard-locked to ``GAME_RATE`` so render FPS and
    simulation TPS always stay in lockstep — a 30 Hz render loop driving
    a 240 Hz physics tick was a footgun nobody actually wanted.
    """
    return GAME_RATE


def set_fps_cap(value):
    """No-op kept for backward compat — the render rate is locked. Old
    callsites that flip the FPS cap simply do nothing now."""
    return


def cycle_fps_cap():
    """No-op cycle — the render rate is locked at ``GAME_RATE``. Returns
    the locked value so the UI still gets something to display."""
    return GAME_RATE


def fps_cap_label(cap=None):
    """Human-friendly label for the locked render rate."""
    return f"{GAME_RATE} (locked)"


def get_tps():
    """Return the locked simulation tick rate. Always equals the render
    rate so the sim accumulator emits exactly one tick per rendered
    frame and there is no mismatch between visible motion and physics.
    """
    return GAME_RATE


def set_tps(value):
    """No-op — the tick rate is locked to ``GAME_RATE``."""
    return


def cycle_tps():
    return GAME_RATE


def tps_label(tps=None):
    return f"{GAME_RATE} (locked)"


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
        from . import music
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
        from . import music
        music.set_volume(DEFAULTS["music_vol"])
    except Exception:
        pass
