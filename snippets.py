"""Editor snippet library — reusable level fragments stamped onto the canvas.

A snippet is a pair `(name, [object_dict, ...])`. Object positions are stored
relative to the snippet's anchor (typically the upper-left of its bounding
box). The editor uses `_clone_objects` from editor.py to drop a snippet at
the cursor with fresh oid/link ids.

Built-in snippets ship with the game; user-defined snippets are persisted to
`snippets_user.json` next to `prefs.json`. The editor's "Save selection as
snippet" command appends to that file, and `get_snippets()` returns built-ins
followed by user entries.
"""

import json
import os

from constants import (
    LEVELS_DIR,
    T_BLOCK, T_SLAB, T_SPIKE, T_HALF_SPIKE, T_SAW,
    T_PAD, T_BLUE_PAD, T_ORB, T_DASH_ORB, T_GRAV,
    T_BLACK_ORB, T_GREEN_ORB,
    T_COIN, T_MODE_MINI, T_MODE_BIG, T_MODE_SHIP, T_MODE_CUBE,
    T_MODE_BALL, T_MODE_WAVE, T_MODE_UFO,
    T_SPEED_FAST, T_SPEED_NORMAL, T_SPEED_FASTER,
    T_CHECKPOINT,
)


_USER_SNIPPETS_PATH = os.path.join(os.path.dirname(LEVELS_DIR),
                                   "snippets_user.json")


def _o(t, x, y, **extra):
    """Build a snippet object dict — keeps the snippet table compact."""
    out = {"t": t, "x": int(x), "y": int(y), "r": 0}
    out.update(extra)
    return out


# ---------------------------------------------------------------------------
# Built-in snippets — deliberately small, useful, opinionated fragments.
# Coordinates are local: typical floor row is y=10 (matches editor's default),
# and the snippet's leftmost cell is at x=0.
# ---------------------------------------------------------------------------

BUILTIN_SNIPPETS = [
    ("Spike Trio", [
        _o(T_SPIKE, 0, 10),
        _o(T_SPIKE, 1, 10),
        _o(T_SPIKE, 2, 10),
    ]),
    ("Spike + Slab Cap", [
        _o(T_SPIKE, 0, 10),
        _o(T_SLAB, 0, 9),
    ]),
    ("Floating Platform", [
        _o(T_BLOCK, 0, 7),
        _o(T_BLOCK, 1, 7),
        _o(T_BLOCK, 2, 7),
        _o(T_BLOCK, 3, 7),
        _o(T_BLOCK, 4, 7),
    ]),
    ("Coin Trio", [
        _o(T_COIN, 0, 8),
        _o(T_COIN, 1, 7),
        _o(T_COIN, 2, 8),
    ]),
    ("Saw Pit", [
        _o(T_BLOCK, 0, 10),
        _o(T_BLOCK, 0, 9),
        _o(T_SAW, 1, 9),
        _o(T_SAW, 2, 9),
        _o(T_BLOCK, 3, 10),
        _o(T_BLOCK, 3, 9),
    ]),
    ("Jump Pad Combo", [
        _o(T_PAD, 0, 10),
        _o(T_ORB, 3, 7),
        _o(T_DASH_ORB, 6, 6),
    ]),
    ("Speed Burst (Fast→Normal)", [
        _o(T_SPEED_FAST, 0, 8),
        _o(T_SPEED_NORMAL, 12, 8),
    ]),
    ("Mini Sprint", [
        _o(T_MODE_MINI, 0, 8),
        _o(T_SPIKE, 3, 10),
        _o(T_SPIKE, 4, 10),
        _o(T_SPIKE, 5, 10),
        _o(T_MODE_BIG, 9, 8),
    ]),
    ("Ship Corridor", [
        _o(T_MODE_SHIP, 0, 8),
        _o(T_BLOCK, 3, 5),
        _o(T_BLOCK, 4, 5),
        _o(T_BLOCK, 5, 5),
        _o(T_BLOCK, 3, 10),
        _o(T_BLOCK, 4, 10),
        _o(T_BLOCK, 5, 10),
        _o(T_MODE_CUBE, 9, 8),
    ]),
    ("Gravity Flip Pair", [
        _o(T_GRAV, 0, 9),
        _o(T_GRAV, 6, 9),
    ]),
    ("Stair Step Up", [
        _o(T_BLOCK, 0, 10),
        _o(T_BLOCK, 1, 10), _o(T_BLOCK, 1, 9),
        _o(T_BLOCK, 2, 10), _o(T_BLOCK, 2, 9), _o(T_BLOCK, 2, 8),
        _o(T_BLOCK, 3, 10), _o(T_BLOCK, 3, 9), _o(T_BLOCK, 3, 8), _o(T_BLOCK, 3, 7),
    ]),
    ("Blue Pad Bounce", [
        _o(T_BLUE_PAD, 0, 10),
        _o(T_BLOCK, 4, 5),
        _o(T_BLOCK, 5, 5),
    ]),
    # --- New patterns ---
    ("Wave Gauntlet", [
        _o(T_MODE_WAVE, 0, 8),
        _o(T_BLOCK, 3, 5), _o(T_BLOCK, 3, 6), _o(T_BLOCK, 3, 7),
        _o(T_BLOCK, 5, 9), _o(T_BLOCK, 5, 10),
        _o(T_BLOCK, 7, 5), _o(T_BLOCK, 7, 6), _o(T_BLOCK, 7, 7),
        _o(T_BLOCK, 9, 9), _o(T_BLOCK, 9, 10),
        _o(T_MODE_CUBE, 12, 8),
    ]),
    ("Ball Roll", [
        _o(T_MODE_BALL, 0, 8),
        _o(T_BLOCK, 0, 10), _o(T_BLOCK, 1, 10), _o(T_BLOCK, 2, 10),
        _o(T_BLOCK, 3, 10), _o(T_BLOCK, 4, 10), _o(T_BLOCK, 5, 10),
        _o(T_BLOCK, 6, 10), _o(T_BLOCK, 7, 10), _o(T_BLOCK, 8, 10),
        _o(T_BLOCK, 6, 4), _o(T_BLOCK, 7, 4), _o(T_BLOCK, 8, 4),
        _o(T_MODE_CUBE, 11, 8),
    ]),
    ("UFO Cluster", [
        _o(T_MODE_UFO, 0, 8),
        _o(T_BLOCK, 4, 4), _o(T_BLOCK, 5, 4),
        _o(T_BLOCK, 8, 6),
        _o(T_BLOCK, 11, 4), _o(T_BLOCK, 12, 4),
        _o(T_MODE_CUBE, 15, 8),
    ]),
    ("Orb Chain", [
        _o(T_ORB, 0, 7),
        _o(T_ORB, 4, 5),
        _o(T_DASH_ORB, 8, 4),
        _o(T_GREEN_ORB, 12, 5),
    ]),
    ("Black Orb Slam", [
        _o(T_BLACK_ORB, 0, 6),
        _o(T_BLOCK, 0, 10), _o(T_BLOCK, 1, 10),
        _o(T_BLOCK, 2, 10), _o(T_BLOCK, 3, 10),
    ]),
    ("Speed Dash (Faster)", [
        _o(T_SPEED_FASTER, 0, 8),
        _o(T_BLOCK, 0, 10), _o(T_BLOCK, 1, 10), _o(T_BLOCK, 2, 10),
        _o(T_BLOCK, 3, 10), _o(T_BLOCK, 4, 10), _o(T_BLOCK, 5, 10),
        _o(T_SPIKE, 7, 10), _o(T_SPIKE, 8, 10),
        _o(T_BLOCK, 9, 10), _o(T_BLOCK, 10, 10),
        _o(T_SPEED_NORMAL, 14, 8),
    ]),
    ("Half-Spike Trap", [
        _o(T_HALF_SPIKE, 0, 10),
        _o(T_HALF_SPIKE, 1, 10),
        _o(T_HALF_SPIKE, 2, 10),
        _o(T_BLOCK, 4, 7),
    ]),
    ("Checkpoint Marker", [
        _o(T_CHECKPOINT, 0, 9),
    ]),
    ("Saw Tunnel", [
        _o(T_BLOCK, 0, 4), _o(T_BLOCK, 1, 4), _o(T_BLOCK, 2, 4),
        _o(T_BLOCK, 3, 4), _o(T_BLOCK, 4, 4), _o(T_BLOCK, 5, 4),
        _o(T_SAW, 1, 5), _o(T_SAW, 4, 5),
        _o(T_BLOCK, 0, 10), _o(T_BLOCK, 1, 10), _o(T_BLOCK, 2, 10),
        _o(T_BLOCK, 3, 10), _o(T_BLOCK, 4, 10), _o(T_BLOCK, 5, 10),
    ]),
    ("Stair Step Down", [
        _o(T_BLOCK, 0, 7), _o(T_BLOCK, 0, 8), _o(T_BLOCK, 0, 9), _o(T_BLOCK, 0, 10),
        _o(T_BLOCK, 1, 8), _o(T_BLOCK, 1, 9), _o(T_BLOCK, 1, 10),
        _o(T_BLOCK, 2, 9), _o(T_BLOCK, 2, 10),
        _o(T_BLOCK, 3, 10),
    ]),
]


# ---------------------------------------------------------------------------
# User snippets I/O — persisted as a JSON list of {"name": ..., "objects": ...}
# ---------------------------------------------------------------------------

def _normalize_user_objs(objs):
    """Coerce x/y to ints and ensure required keys exist on user-saved objects."""
    out = []
    for o in objs:
        if not isinstance(o, dict) or "t" not in o:
            continue
        no = dict(o)
        no["x"] = int(no.get("x", 0))
        no["y"] = int(no.get("y", 0))
        no["r"] = int(no.get("r", 0)) % 360
        out.append(no)
    return out


def load_user_snippets():
    """Return list of (name, objects) tuples from the user-snippets file."""
    if not os.path.isfile(_USER_SNIPPETS_PATH):
        return []
    try:
        with open(_USER_SNIPPETS_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    out = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "Untitled"))
        objs = entry.get("objects")
        if not isinstance(objs, list) or not objs:
            continue
        out.append((name, _normalize_user_objs(objs)))
    return out


def save_user_snippet(name, objects):
    """Append a new user snippet (name, objects) to the user snippets file.

    `objects` should be supplied with positions normalized to start at (0, 0)
    — i.e. the caller has already subtracted the bounding-box origin so the
    snippet's anchor is its top-left cell. Returns the path written.
    """
    existing = load_user_snippets()
    existing.append((str(name).strip() or "Untitled", _normalize_user_objs(objects)))
    payload = [{"name": n, "objects": list(objs)} for n, objs in existing]
    os.makedirs(os.path.dirname(_USER_SNIPPETS_PATH) or ".", exist_ok=True)
    with open(_USER_SNIPPETS_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    return _USER_SNIPPETS_PATH


def delete_user_snippet(index):
    """Remove the user snippet at `index` (0-based, into load_user_snippets()).

    Returns True on success, False if the index is out of range.
    """
    existing = load_user_snippets()
    if index < 0 or index >= len(existing):
        return False
    del existing[index]
    payload = [{"name": n, "objects": list(objs)} for n, objs in existing]
    with open(_USER_SNIPPETS_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    return True


def get_snippets():
    """Return the combined snippet list: built-ins followed by user snippets.

    Each entry is a `(name, objects, is_user)` triple so callers can distinguish
    built-ins (immutable) from user snippets (deletable).
    """
    out = [(name, list(objs), False) for name, objs in BUILTIN_SNIPPETS]
    for name, objs in load_user_snippets():
        out.append((name, list(objs), True))
    return out


def normalize_to_origin(objects):
    """Shift `objects` so the upper-left cell sits at (0, 0). Returns a new list."""
    if not objects:
        return []
    min_x = min(o["x"] for o in objects)
    min_y = min(o["y"] for o in objects)
    out = []
    for o in objects:
        no = dict(o)
        no["x"] = o["x"] - min_x
        no["y"] = o["y"] - min_y
        out.append(no)
    return out
