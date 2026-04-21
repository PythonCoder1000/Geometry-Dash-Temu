"""Persistence for named bot runs.

Each saved run is a JSON file under ``bot_runs/`` containing the solver's
input sequence, waypoints, and some metadata. The bot menu can re-load a
saved run and hand it straight to the solver as `seed_inputs` (for a
"fix only" tweak) or install it as the hint/replay source without running
the solver at all.

Files are keyed by a short level hash so the same save name on two
different levels doesn't collide. Runs are listed per level — listing a
level the user has never saved for just returns an empty list.

On-disk layout (flat, one file per run):
    bot_runs/<level_key>__<safe_name>.json

The flat structure keeps deletion / renaming trivial — no empty directory
hygiene to worry about — and matches how the `levels/` and `thumbnails/`
dirs store files.
"""

import hashlib
import json
import os
import time

from constants import BOT_RUNS_DIR


# Fields that the solver adds at runtime and that shouldn't change the
# level's identity (move-animation floats, spatial-index bookkeeping,
# etc.). Stripped before hashing so a saved run still applies after a
# fresh play session shuffles these.
_RUNTIME_FIELDS = ("_orig_x", "_orig_y", "_fx", "_fy", "_cell")


def _ensure_dir():
    os.makedirs(BOT_RUNS_DIR, exist_ok=True)


def _clean_objects(objects):
    """Strip runtime-only fields so the level hash is stable across runs."""
    cleaned = []
    for o in objects:
        cleaned.append({k: v for k, v in o.items()
                        if not (isinstance(k, str) and
                                (k in _RUNTIME_FIELDS or k.startswith("_")))})
    return cleaned


def level_key_from_objects(objects):
    """Short stable hash of the level's object list.

    The JSON uses ``sort_keys`` and a strict separator so two semantically
    identical levels always hash the same, even when one dict happens to
    have been built in a different key order.
    """
    cleaned = _clean_objects(objects)
    blob = json.dumps(cleaned, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


def level_key_from_filename(filename):
    """Prefer the filename when one is known — it's a stable, human-
    debuggable identifier. Falls back to ``level_key_from_objects`` when
    the caller doesn't know a filename yet (unsaved editor work)."""
    if not filename:
        return None
    base = os.path.basename(filename)
    if base.endswith(".json"):
        base = base[:-5]
    return "f_" + base


def _safe_name(name):
    """Sanitise a user-supplied save name for use as a filename fragment."""
    out = "".join(c if c.isalnum() or c in "-_ " else "_" for c in name)
    out = out.strip().replace(" ", "_")
    return out or "run"


def _path_for(level_key, name):
    _ensure_dir()
    return os.path.join(BOT_RUNS_DIR,
                        f"{level_key}__{_safe_name(name)}.json")


def save_run(level_key, name, *, inputs, waypoints, mirror_waypoints,
             status, beam_width=None, attempts=None):
    """Persist one bot run. Overwrites any prior save with the same name."""
    if not level_key or not name:
        return False
    payload = {
        "name": name,
        "level_key": level_key,
        "saved_at": int(time.time()),
        "status": status,
        "inputs": [[bool(h), bool(p)] for h, p in (inputs or [])],
        "waypoints": [[float(x), float(y)] for x, y in (waypoints or [])],
        "mirror_waypoints": [[float(x), float(y)]
                             for x, y in (mirror_waypoints or [])],
        "beam_width": beam_width,
        "attempts": attempts,
    }
    path = _path_for(level_key, name)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        os.replace(tmp, path)
        return True
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def list_runs(level_key):
    """Return a list of summary dicts for every saved run on this level.

    Each entry has: ``name``, ``saved_at``, ``status``, ``input_frames``,
    ``path``. Sorted newest-first.
    """
    if not level_key:
        return []
    _ensure_dir()
    prefix = level_key + "__"
    out = []
    try:
        names = os.listdir(BOT_RUNS_DIR)
    except OSError:
        return []
    for fn in names:
        if not fn.startswith(prefix) or not fn.endswith(".json"):
            continue
        path = os.path.join(BOT_RUNS_DIR, fn)
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        out.append({
            "name": data.get("name") or fn[len(prefix):-5],
            "saved_at": int(data.get("saved_at", 0)),
            "status": data.get("status", ""),
            "input_frames": len(data.get("inputs", [])),
            "path": path,
        })
    out.sort(key=lambda e: e["saved_at"], reverse=True)
    return out


def load_run(level_key, name):
    """Return the full saved payload or ``None`` if missing / malformed."""
    path = _path_for(level_key, name)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    # Normalise list-of-lists back into the tuple shapes the callers want.
    data["inputs"] = [(bool(h), bool(p)) for h, p in data.get("inputs", [])]
    data["waypoints"] = [(float(x), float(y))
                         for x, y in data.get("waypoints", [])]
    data["mirror_waypoints"] = [(float(x), float(y))
                                for x, y in data.get("mirror_waypoints", [])]
    return data


def delete_run(level_key, name):
    path = _path_for(level_key, name)
    try:
        os.remove(path)
        return True
    except OSError:
        return False
