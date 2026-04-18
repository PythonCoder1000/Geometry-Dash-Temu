"""User preferences persistence.

A tiny JSON-backed key/value store for things the player sets once and
expects to stick across sessions (mute, volume, menu track, etc.).

Keys in use:
    music_muted : bool
    sfx_muted   : bool
    music_vol   : float 0..1
    sfx_vol     : float 0..1
    menu_track  : int (index into music._tracks)
"""

import json
import os

from constants import LEVELS_DIR

# Sit the prefs file next to the levels directory so it shares the same
# writeable root in packaged builds.
_PREFS_PATH = os.path.join(os.path.dirname(LEVELS_DIR), "prefs.json")
_cache = None


def _load():
    global _cache
    if _cache is not None:
        return _cache
    _cache = {}
    try:
        with open(_PREFS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            _cache = data
    except (OSError, ValueError):
        pass
    return _cache


def _save():
    try:
        with open(_PREFS_PATH, "w", encoding="utf-8") as f:
            json.dump(_cache, f, indent=2)
    except OSError:
        pass


def get(key, default=None):
    return _load().get(key, default)


def set(key, value):
    _load()
    _cache[key] = value
    _save()


def toggle(key, default=False):
    """Flip a boolean pref and persist. Returns new value."""
    cur = bool(get(key, default))
    set(key, not cur)
    return not cur
