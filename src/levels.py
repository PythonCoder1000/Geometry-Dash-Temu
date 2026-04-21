"""Level loading/saving and progress tracking.

Filenames beginning with an underscore are reserved (e.g. `_autosave.json`)
and never appear in the level browser — see `list_levels()`.

Level JSON schema (current version — see `LEVEL_FORMAT_VERSION` in
`constants.py` for the exact number; `_default_meta()` is the source of
truth for field defaults). Example:
    {
      "name": "Level Name",
      "v": LEVEL_FORMAT_VERSION,
      "author": "Player",
      "difficulty": "Normal",          # current official rating (verifier can set)
      "requested_difficulty": "Normal",# what the publisher asked for
      "description": "",
      "published": false,   # set true on publish (otherwise treated as draft)
      "verified": false,    # set true after someone beats it without the autobot
      "music": "song.mp3",  # null if no music
      "attempts": 0,        # best stored attempts count
      "best_progress": 0,   # 0-100, best fraction reached
      "coins_collected": 0, # 0..3 — max coins ever collected in one run
      "best_time_frames": 0,# best completion time; 0 means no record
      "deaths": 0,          # total deaths across all attempts
      "objects": [ ... ]    # objects may carry a "group" field (v6+)
    }

Older versions are migrated on load.
"""

import json
import os

from .constants import (
    LEVELS_DIR, LEVEL_FORMAT_VERSION, DIFFICULTIES, LEGACY_DEMON_TARGET,
    T_BLOCK, T_SLAB, T_SPIKE, T_HALF_SPIKE, T_SAW,
    T_ORB, T_DASH_ORB, T_TELEPORT_ORB, T_BLUE_ORB, T_GREEN_ORB, T_BLACK_ORB,
    T_PAD, T_BLUE_PAD, T_GRAV, T_END, T_START, T_COIN,
    T_MODE_SHIP, T_MODE_BALL, T_MODE_CUBE, T_MODE_WAVE, T_MODE_UFO, T_MODE_SPIDER,
    T_MODE_DUAL,
    T_SPEED_SLOW, T_SPEED_NORMAL, T_SPEED_FAST, T_SPEED_FASTER,
    T_DECO_CRYSTAL, T_DECO_PILLAR, T_DECO_GLOW,
    T_CAMERA_TRIGGER, T_BG_TRIGGER, T_MOVE_TRIGGER, T_COLOR_TRIGGER,
    T_PULSE_TRIGGER, T_ROTATE_TRIGGER,
)


# ---------------------------------------------------------------------------
# Filesystem helpers
# ---------------------------------------------------------------------------

def ensure_dirs():
    os.makedirs(LEVELS_DIR, exist_ok=True)
    _seed_bundled_levels()


def _seed_bundled_levels():
    """First-launch: copy any levels shipped in the bundle's read-only
    directory into the user's writable LEVELS_DIR so the level browser
    isn't empty on a fresh install. Skips files that already exist so
    subsequent launches don't stomp edits.
    """
    try:
        from .constants import _BUNDLED_LEVELS_DIR
    except ImportError:
        return
    # Same path → dev checkout, nothing to seed.
    if os.path.abspath(_BUNDLED_LEVELS_DIR) == os.path.abspath(LEVELS_DIR):
        return
    if not os.path.isdir(_BUNDLED_LEVELS_DIR):
        return
    try:
        entries = os.listdir(_BUNDLED_LEVELS_DIR)
    except OSError:
        return
    for fn in entries:
        if not fn.endswith(".json") or fn.startswith("_"):
            continue
        src = os.path.join(_BUNDLED_LEVELS_DIR, fn)
        dst = os.path.join(LEVELS_DIR, fn)
        if os.path.exists(dst):
            continue
        try:
            with open(src, "rb") as rf, open(dst, "wb") as wf:
                wf.write(rf.read())
        except OSError:
            pass


def _safe_filename(name):
    """Turn a human level name into a safe JSON filename (no extension).

    Leading underscores are stripped because filenames starting with `_` are
    reserved (see `list_levels()` and the autosave slot). Runs of `_` are
    collapsed to a single underscore so a name like "Blast   !!!" doesn't
    produce `blast______.json`. A level whose sanitized name is empty falls
    back to `level`.
    """
    import re
    base = "".join(c if c.isalnum() or c in "-_ " else "_" for c in name)
    base = base.strip().lower().replace(" ", "_")
    base = re.sub(r"_+", "_", base)
    base = base.lstrip("_") or "level"
    return base[:60]


# ---------------------------------------------------------------------------
# Object normalization (migration-friendly)
# ---------------------------------------------------------------------------

def _normalize_rotation(r):
    try:
        return int(round(float(r) / 90.0) * 90) % 360
    except (TypeError, ValueError):
        return 0


def get_group_id(o):
    """Return an object's group id, reading either ``group_id`` (current
    field name) or the legacy ``link`` field (for backwards compatibility
    with levels saved before the rename). Returns 0 when neither is set.

    Centralised so callers don't have to know about the old field — see the
    teleport-orb pairing logic in :mod:`player`, sprite-variant selection
    in :mod:`graphics`, and the editor's grouping tool.
    """
    gid = o.get("group_id")
    if gid is None:
        gid = o.get("link", 0)
    try:
        return int(gid) if gid else 0
    except (TypeError, ValueError):
        return 0


def normalize_object(o):
    """Produce a clean canonical object dict. Strips unknown keys, coerces ints.

    Backwards-compat note: levels saved with the old ``link`` field for
    teleport orbs are migrated forward to ``group_id`` here so the rest of
    the engine only has to look at one field.
    """
    out = {
        "t": o["t"],
        "x": int(o.get("x", 0)),
        "y": int(o.get("y", 0)),
        "r": _normalize_rotation(o.get("r", 0)),
    }
    if o["t"] == T_TELEPORT_ORB:
        out["group_id"] = get_group_id(o)
        if o.get("dest"):
            out["dest"] = 1
    if o["t"] == T_CAMERA_TRIGGER:
        out["cy"] = int(o.get("cy", out["y"]))
    if o["t"] == T_MODE_DUAL:
        # Optional: cell row where the mirror player spawns. Older levels
        # without this field fall back to the symmetric placement around
        # screen center inside Player._enter_dual.
        if "spawn_y" in o and o["spawn_y"] is not None:
            out["spawn_y"] = int(o["spawn_y"])
    if o["t"] == T_BG_TRIGGER:
        out["bg"] = int(o.get("bg", 0))
    if o["t"] == T_COLOR_TRIGGER:
        out["col_idx"] = int(o.get("col_idx", 0))
    if o["t"] == T_MOVE_TRIGGER:
        out["target_oid"] = int(o.get("target_oid", 0))
        target_oids = o.get("target_oids")
        if isinstance(target_oids, list) and target_oids:
            out["target_oids"] = [int(t) for t in target_oids if int(t) > 0]
        out["tx"] = int(o.get("tx", out["x"]))
        out["ty"] = int(o.get("ty", out["y"]))
        out["duration"] = max(1, int(o.get("duration", 30)))
        curve = o.get("curve")
        if isinstance(curve, list) and len(curve) >= 2:
            out["curve"] = [[float(p[0]), float(p[1])] for p in curve]
    if o["t"] == T_COIN:
        out["coin_id"] = int(o.get("coin_id", 0)) or 0  # 0 = unassigned
    if o["t"] == T_PULSE_TRIGGER:
        out["bpm"] = max(30, min(300, int(o.get("bpm", 128))))
        out["duration"] = max(0.1, min(20.0, float(o.get("duration", 2.0))))
    if o["t"] == T_ROTATE_TRIGGER:
        out["target_oid"] = int(o.get("target_oid", 0))
        target_oids = o.get("target_oids")
        if isinstance(target_oids, list) and target_oids:
            out["target_oids"] = [int(t) for t in target_oids if int(t) > 0]
        # Degrees per second; positive = clockwise.
        out["spin"] = float(o.get("spin", 90.0))
        out["duration"] = max(0.1, min(60.0, float(o.get("duration", 4.0))))
    if o.get("oid"):
        out["oid"] = int(o["oid"])
    if o.get("group"):
        out["group"] = int(o["group"])
    return out


# ---------------------------------------------------------------------------
# Level (full metadata) I/O
# ---------------------------------------------------------------------------

def _default_meta(name="Untitled"):
    return {
        "name": name,
        "v": LEVEL_FORMAT_VERSION,
        "author": "Player",
        "difficulty": "Normal",
        "requested_difficulty": "Normal",
        # Filled in by the first player (non-author) who beats a
        # published level. Stays as an informational "community
        # suggested" rating until ADMIN_USERNAME locks the final
        # rating via the Rate Levels menu.
        "suggested_difficulty": "",
        "description": "",
        "published": False,
        # True when someone (not the author) has beaten a published
        # level at least once. Official `difficulty` is still the
        # publisher's request; `suggested_difficulty` holds the
        # beater's opinion.
        "verified": False,
        # True only after ADMIN_USERNAME rates the verified level.
        # Once true, `difficulty` = admin's final rating; the
        # "unconfirmed difficulty" label disappears from the UI.
        "rated": False,
        "music": None,
        "attempts": 0,
        "best_progress": 0,
        "coins_collected": 0,
        "best_time_frames": 0,  # 0 = no record yet
        "deaths": 0,            # total deaths across all attempts
    }


def _migrate(data):
    """Upgrade any older level dict in-place to the current schema."""
    meta = _default_meta(data.get("name", "Untitled"))
    for k, v in data.items():
        if k != "objects":
            meta[k] = v
    # Normalize fields. Legacy "Demon" tier → "Hard Demon" (the new
    # middle-of-the-stack demon), so old levels don't jump to
    # "Easy Demon" (too lenient) or "Extreme Demon" (undeserved credit).
    if meta.get("difficulty") == "Demon":
        meta["difficulty"] = LEGACY_DEMON_TARGET
    if meta.get("requested_difficulty") == "Demon":
        meta["requested_difficulty"] = LEGACY_DEMON_TARGET
    if meta.get("difficulty") not in DIFFICULTIES:
        meta["difficulty"] = "Normal"
    if meta.get("requested_difficulty") not in DIFFICULTIES:
        meta["requested_difficulty"] = meta["difficulty"]
    meta["published"] = bool(meta.get("published", False))
    meta["verified"] = bool(meta.get("verified", False))
    meta["rated"] = bool(meta.get("rated", False))
    _sg = meta.get("suggested_difficulty", "") or ""
    if _sg and _sg not in DIFFICULTIES:
        _sg = ""
    meta["suggested_difficulty"] = _sg
    try:
        meta["attempts"] = max(0, int(meta.get("attempts", 0)))
    except (TypeError, ValueError):
        meta["attempts"] = 0
    try:
        meta["best_progress"] = max(0, min(100, int(meta.get("best_progress", 0))))
    except (TypeError, ValueError):
        meta["best_progress"] = 0
    try:
        meta["coins_collected"] = max(0, min(3, int(meta.get("coins_collected", 0))))
    except (TypeError, ValueError):
        meta["coins_collected"] = 0
    try:
        meta["best_time_frames"] = max(0, int(meta.get("best_time_frames", 0)))
    except (TypeError, ValueError):
        meta["best_time_frames"] = 0
    try:
        meta["deaths"] = max(0, int(meta.get("deaths", 0)))
    except (TypeError, ValueError):
        meta["deaths"] = 0
    music = meta.get("music")
    if music is not None and not isinstance(music, str):
        meta["music"] = None
    meta["v"] = LEVEL_FORMAT_VERSION
    return meta


def save_level(objects, name, filename=None, music_file=None, meta=None):
    """Write a level JSON.

    `meta` may be an existing metadata dict to preserve (e.g. when editing a
    previously published level). If absent, sensible defaults are used and
    `music_file` overrides the meta's music.

    Also refreshes the level's thumbnail (best-effort — failures don't block
    the save). Thumbnails live in `levels/_thumbs/`.
    """
    ensure_dirs()
    file_meta = dict(meta) if meta else _default_meta(name)
    file_meta["name"] = name
    file_meta["v"] = LEVEL_FORMAT_VERSION
    if music_file is not None:
        file_meta["music"] = music_file
    file_meta = _migrate(file_meta)

    data = dict(file_meta)
    data["objects"] = [normalize_object(o) for o in objects]

    fn = filename or _safe_filename(name)
    if not fn.endswith(".json"):
        fn += ".json"
    path = os.path.join(LEVELS_DIR, fn)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)

    # Best-effort thumbnail refresh — kept lazy-imported so headless callers
    # that haven't initialized pygame display can still save levels.
    try:
        from .thumbnails import save_thumbnail
        save_thumbnail(fn, data["objects"])
    except Exception:
        pass

    return path


# ---------------------------------------------------------------------------
# Editor autosave (separate slot, never appears in the level browser)
# ---------------------------------------------------------------------------

AUTOSAVE_FILENAME = "_autosave.json"
# Rolling backup directory for time-stamped snapshots. QoL §A12 — the
# single `_autosave.json` only covers the very last state; this rolling
# history means a user can recover from mistakes they already saved
# over.
AUTOSAVE_BACKUP_DIR = "_autosave_backups"
AUTOSAVE_BACKUP_MAX = 10


def _autosave_path():
    return os.path.join(LEVELS_DIR, AUTOSAVE_FILENAME)


def _autosave_backup_dir():
    return os.path.join(LEVELS_DIR, AUTOSAVE_BACKUP_DIR)


def _rotate_autosave_backups(data):
    """Drop a timestamped copy of `data` into the rolling backup dir,
    pruning the oldest entries so at most AUTOSAVE_BACKUP_MAX remain."""
    import time
    bdir = _autosave_backup_dir()
    try:
        os.makedirs(bdir, exist_ok=True)
    except OSError:
        return
    fn = time.strftime("autosave-%Y%m%d-%H%M%S.json")
    path = os.path.join(bdir, fn)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError:
        return
    # Prune oldest.
    try:
        entries = [f for f in os.listdir(bdir)
                   if f.startswith("autosave-") and f.endswith(".json")]
    except OSError:
        return
    if len(entries) <= AUTOSAVE_BACKUP_MAX:
        return
    entries.sort()  # timestamp prefix sorts chronologically
    for stale in entries[:-AUTOSAVE_BACKUP_MAX]:
        try:
            os.remove(os.path.join(bdir, stale))
        except OSError:
            pass


def list_autosave_backups():
    """Return a list of (filename, mtime, meta) tuples for every
    available backup, newest first. Used by the load-recovery dialog."""
    bdir = _autosave_backup_dir()
    if not os.path.isdir(bdir):
        return []
    out = []
    for fn in os.listdir(bdir):
        if not (fn.startswith("autosave-") and fn.endswith(".json")):
            continue
        path = os.path.join(bdir, fn)
        try:
            stat = os.stat(path)
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        out.append((fn, int(stat.st_mtime), data))
    out.sort(key=lambda e: e[1], reverse=True)
    return out


def save_autosave(objects, name, music_file=None, meta=None,
                  source_filename=None):
    """Write the editor's auto-save snapshot.

    Mirrors `save_level` but writes to a fixed reserved filename and tags the
    snapshot with the original filename (if any) so recovery can restore it
    to the same slot. The autosave file is filtered out of `list_levels()`.
    Also drops a timestamped copy into the rolling backup directory.
    """
    ensure_dirs()
    file_meta = dict(meta) if meta else _default_meta(name)
    file_meta["name"] = name
    file_meta["v"] = LEVEL_FORMAT_VERSION
    if music_file is not None:
        file_meta["music"] = music_file
    file_meta = _migrate(file_meta)
    # Tag so recovery knows where to restore.
    file_meta["_autosave_source"] = source_filename or ""
    file_meta["_autosave_ts"] = int(__import__("time").time())

    data = dict(file_meta)
    data["objects"] = [normalize_object(o) for o in objects]

    path = _autosave_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    _rotate_autosave_backups(data)
    return path


def has_autosave():
    return os.path.isfile(_autosave_path())


def load_autosave():
    """Return (meta, objects) for the autosave slot, or (None, None)."""
    path = _autosave_path()
    if not os.path.isfile(path):
        return None, None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None, None
    meta = _migrate(data)
    # `_migrate` already copies every non-"objects" key, so the autosave
    # fields carry across automatically. These explicit re-copies are kept
    # as a belt-and-braces guard in case `_migrate` is ever tightened to
    # whitelist only default_meta keys.
    if "_autosave_source" in data:
        meta["_autosave_source"] = data["_autosave_source"]
    if "_autosave_ts" in data:
        meta["_autosave_ts"] = data["_autosave_ts"]
    objects = [normalize_object(o) for o in data.get("objects", [])]
    return meta, objects


def clear_autosave():
    """Remove the autosave file if present. Safe to call when none exists."""
    path = _autosave_path()
    try:
        os.remove(path)
    except OSError:
        pass


def load_level(path):
    """Return (name, objects, music_file). Kept backward-compatible with old callers."""
    meta, objects = load_level_full(path)
    return meta["name"], objects, meta.get("music")


def load_level_full(path):
    """Return (meta, objects) — meta contains all level metadata."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    meta = _migrate(data)
    # Strip legacy "checkpoint" objects — checkpoints are a player-
    # session mechanic (C key in practice mode), not level data.
    raw_objects = [o for o in data.get("objects", [])
                   if o.get("t") != "checkpoint"]
    objects = [normalize_object(o) for o in raw_objects]
    # Assign missing coin_ids deterministically so progress tracks them stably.
    next_cid = 1
    used = {o.get("coin_id", 0) for o in objects if o["t"] == T_COIN}
    for o in objects:
        if o["t"] == T_COIN and not o.get("coin_id"):
            while next_cid in used:
                next_cid += 1
            o["coin_id"] = next_cid
            used.add(next_cid)
    return meta, objects


def update_meta(path, **updates):
    """Merge updates into a level's meta, leaving objects untouched."""
    meta, objects = load_level_full(path)
    meta.update(updates)
    save_level(objects, meta["name"], os.path.basename(path), meta=meta)


def list_levels():
    """Return sorted list of JSON filenames in the levels dir.

    Filenames starting with `_` are reserved (e.g. the editor autosave slot)
    and never surface in the level browser.
    """
    ensure_dirs()
    return sorted(
        f for f in os.listdir(LEVELS_DIR)
        if f.endswith(".json") and not f.startswith("_")
    )


def list_level_summaries():
    """Return list of (filename, meta) tuples for all stored levels."""
    out = []
    for f in list_levels():
        path = os.path.join(LEVELS_DIR, f)
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            meta = _migrate(data)
            out.append((f, meta))
        except (json.JSONDecodeError, OSError):
            continue
    return out


# ---------------------------------------------------------------------------
# Object-id helpers (used by the editor)
# ---------------------------------------------------------------------------

def next_group_id(objects):
    """Return the smallest unused group_id among teleport orbs (1-based).

    Reads both the new ``group_id`` field and the legacy ``link`` field so
    fresh ids never collide with already-loaded levels.
    """
    used = {get_group_id(o) for o in objects
            if o["t"] == T_TELEPORT_ORB and get_group_id(o) > 0}
    i = 1
    while i in used:
        i += 1
    return i


# Legacy alias — older code (and the editor's import line) still references
# the original name. Removed once all call-sites migrate.
next_teleport_link = next_group_id


def next_object_id(objects):
    used = {o.get("oid", 0) for o in objects if o.get("oid", 0) > 0}
    i = 1
    while i in used:
        i += 1
    return i


def next_coin_id(objects):
    used = {o.get("coin_id", 0) for o in objects if o["t"] == T_COIN and o.get("coin_id", 0) > 0}
    i = 1
    while i in used:
        i += 1
    return i

