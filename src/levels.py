"""Level loading/saving, migration, and editor autosave.

Filenames beginning with an underscore are reserved (autosave slot,
thumbnails, backups) and never appear in the level browser.

Level JSON schema (``LEVEL_FORMAT_VERSION`` in ``constants.py``;
``_default_meta()`` is the source of truth for meta defaults)::

    {
      "name": "Level Name", "v": 7, "author": "Player",
      "difficulty": "Normal", "requested_difficulty": "Normal",
      "suggested_difficulty": "", "description": "",
      "published": false, "verified": false, "rated": false,
      "music": null, "attempts": 0, "best_progress": 0,
      "coins_collected": 0, "best_time_frames": 0, "deaths": 0,
      "physics": {...optional PhysicsParams overrides...},
      "channels": {...optional color-channel table, see channels.py...},
      "objects": [{"t": "block", "x": 0, "y": 10, "r": 0,
                   "groups": [1, 2], ...}, ...]
    }

Per-object fields are declared in :mod:`objects`; :func:`normalize_object`
coerces and clamps them through that schema.  Older versions are migrated
on load (:func:`_migrate` for meta, :func:`_migrate_objects` for objects).
"""

import json
import os
import re
import time

from .constants import (
    LEVELS_DIR, LEVEL_FORMAT_VERSION, DIFFICULTIES, LEGACY_DEMON_TARGET,
    T_TELEPORT_ORB, T_TELEPORT_PORTAL, TELEPORT_LINK_TYPES,
    T_COIN, T_MOVE_TRIGGER, T_ROTATE_TRIGGER, T_CHECKPOINT,
    T_ORB, T_BLUE_ORB, T_GREEN_ORB, T_COLOR_TRIGGER,
)
from . import objects as _registry


# ---------------------------------------------------------------------------
# Filesystem helpers
# ---------------------------------------------------------------------------

def ensure_dirs():
    os.makedirs(LEVELS_DIR, exist_ok=True)
    _seed_bundled_levels()


def _seed_bundled_levels():
    """First launch of a frozen build: copy bundled sample levels into the
    writable levels dir.  Never overwrites existing files."""
    from .constants import _BUNDLED_LEVELS_DIR
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
        dst = os.path.join(LEVELS_DIR, fn)
        if os.path.exists(dst):
            continue
        try:
            with open(os.path.join(_BUNDLED_LEVELS_DIR, fn), "rb") as rf, \
                    open(dst, "wb") as wf:
                wf.write(rf.read())
        except OSError:
            pass


def _safe_filename(name):
    """Human level name -> safe JSON basename (no extension)."""
    base = "".join(c if c.isalnum() or c in "-_ " else "_" for c in name)
    base = base.strip().lower().replace(" ", "_")
    base = re.sub(r"_+", "_", base)
    base = base.lstrip("_") or "level"
    return base[:60]


def _write_json(path, data):
    """Atomic write: dump to a sibling temp file, then replace."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Object normalization
# ---------------------------------------------------------------------------

def _normalize_rotation(r):
    """Wrap any rotation into ``[0, 360)``; whole degrees stay ints."""
    try:
        v = float(r) % 360.0
    except (TypeError, ValueError):
        return 0
    iv = int(round(v))
    if abs(v - iv) < 1e-6:
        return iv % 360
    return v


def get_group_id(o):
    """Teleport-orb group id, reading ``group_id`` or the legacy ``link``."""
    gid = o.get("group_id")
    if gid is None:
        gid = o.get("link", 0)
    try:
        return int(gid) if gid else 0
    except (TypeError, ValueError):
        return 0


def _clamp_scale(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 1.0
    return max(0.25, min(8.0, f))


def _oid_list(raw):
    out = []
    if isinstance(raw, list):
        for t in raw:
            try:
                t = int(t)
            except (TypeError, ValueError):
                continue
            if t > 0:
                out.append(t)
    return out


def get_groups(o):
    """An object's group memberships as a list of positive ints, reading
    the current ``groups`` list or (falling back) the legacy singular
    ``group`` int a level may still carry."""
    groups = _oid_list(o.get("groups"))
    if groups:
        return sorted(set(groups))
    try:
        g = int(o.get("group", 0))
    except (TypeError, ValueError):
        g = 0
    return [g] if g > 0 else []


def normalize_object(o):
    """Produce a clean canonical object dict: known keys only, typed and
    clamped through the :mod:`objects` field schema."""
    t = o["t"]
    out = {
        "t": t,
        "x": int(o.get("x", 0)),
        "y": int(o.get("y", 0)),
        "r": _normalize_rotation(o.get("r", 0)),
    }
    # v8 legacy shim: Color Trigger's old palette-index field renamed to
    # ``channel`` (still means the same thing — DEFAULT_CHANNEL_COLORS in
    # channels.py is seeded 1:1 from the same PLAYER_COLORS palette).
    if t == T_COLOR_TRIGGER and "channel" not in o and "col_idx" in o:
        o = dict(o)
        o["channel"] = o["col_idx"]
    # Scale: legacy uniform ``scale`` or per-axis ``sx``/``sy``.
    legacy = _clamp_scale(o["scale"]) if o.get("scale") is not None else None
    sx = _clamp_scale(o["sx"]) if o.get("sx") is not None else legacy
    sy = _clamp_scale(o["sy"]) if o.get("sy") is not None else legacy
    sx = 1.0 if sx is None else sx
    sy = 1.0 if sy is None else sy
    if abs(sx - sy) < 1e-6:
        if abs(sx - 1.0) > 1e-6:
            out["scale"] = sx
    else:
        out["sx"] = sx
        out["sy"] = sy
    # Legacy teleport-orb ``link`` -> ``group_id`` before the schema pass.
    if t in TELEPORT_LINK_TYPES:
        src = dict(o)
        src["group_id"] = get_group_id(o)
        if not src.get("dest"):
            src.pop("dest", None)
        o = src
    _registry.normalize_fields(o, out)
    # Fields the schema can't express (lists / curves).
    if t in (T_MOVE_TRIGGER, T_ROTATE_TRIGGER):
        oids = _oid_list(o.get("target_oids"))
        if oids:
            out["target_oids"] = oids
    if t == T_MOVE_TRIGGER:
        curve = o.get("curve")
        if isinstance(curve, list) and len(curve) >= 2:
            try:
                out["curve"] = [[float(p[0]), float(p[1])] for p in curve]
            except (TypeError, ValueError, IndexError):
                pass
    if o.get("oid"):
        out["oid"] = int(o["oid"])
    groups = get_groups(o)
    if groups:
        out["groups"] = groups
    layer = o.get("layer", 0)
    if layer:
        try:
            out["layer"] = int(layer)
        except (TypeError, ValueError):
            pass
    if o.get("invisible"):
        out["invisible"] = True
    if o.get("_bot_only"):
        out["_bot_only"] = True
    return out


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

def _default_meta(name="Untitled"):
    return {
        "name": name,
        "v": LEVEL_FORMAT_VERSION,
        "author": "Player",
        "difficulty": "Normal",
        "requested_difficulty": "Normal",
        "suggested_difficulty": "",
        "description": "",
        "published": False,
        "verified": False,
        "rated": False,
        "music": None,
        "attempts": 0,
        "best_progress": 0,
        "coins_collected": 0,
        "best_time_frames": 0,
        "deaths": 0,
    }


def _int_field(meta, key, lo=0, hi=None):
    try:
        v = int(meta.get(key, 0))
    except (TypeError, ValueError):
        v = 0
    v = max(lo, v)
    if hi is not None:
        v = min(hi, v)
    meta[key] = v


def _migrate(data):
    """Upgrade an older level's META dict to the current schema."""
    if not isinstance(data, dict):
        data = {}
    meta = _default_meta(data.get("name", "Untitled"))
    for k, v in data.items():
        if k != "objects":
            meta[k] = v
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
    sg = meta.get("suggested_difficulty", "") or ""
    meta["suggested_difficulty"] = sg if sg in DIFFICULTIES else ""
    _int_field(meta, "attempts")
    _int_field(meta, "best_progress", 0, 100)
    _int_field(meta, "coins_collected", 0, 3)
    _int_field(meta, "best_time_frames")
    _int_field(meta, "deaths")
    if meta.get("music") is not None and not isinstance(meta["music"], str):
        meta["music"] = None
    meta["v"] = LEVEL_FORMAT_VERSION
    return meta


# Object-type renames per format version.  Version 7 aligned orb colours
# with Geometry Dash: the old blue orb (flip + full jump) is GD's GREEN
# orb, and the old green orb (plain jump) is GD's YELLOW orb.  Renaming on
# load keeps every existing level playing exactly as authored.
_OBJECT_RENAMES = {
    7: {T_BLUE_ORB: T_GREEN_ORB, T_GREEN_ORB: T_ORB},
}


def _migrate_objects(raw_objects, from_version):
    """Return normalized objects, applying type renames for old files."""
    if not isinstance(raw_objects, list):
        raw_objects = []
    objs = [o for o in raw_objects
            if isinstance(o, dict) and "t" in o and o.get("t") != T_CHECKPOINT]
    try:
        from_version = int(from_version or 0)
    except (TypeError, ValueError):
        from_version = 0
    for ver in sorted(_OBJECT_RENAMES):
        if from_version < ver:
            table = _OBJECT_RENAMES[ver]
            for o in objs:
                new_t = table.get(o.get("t"))
                if new_t is not None:
                    o["t"] = new_t
    out = [normalize_object(o) for o in objs]
    # Deterministic coin ids so progress tracks them stably.
    next_cid = 1
    used = {o.get("coin_id", 0) for o in out if o["t"] == T_COIN}
    for o in out:
        if o["t"] == T_COIN and not o.get("coin_id"):
            while next_cid in used:
                next_cid += 1
            o["coin_id"] = next_cid
            used.add(next_cid)
    return out


# ---------------------------------------------------------------------------
# Level I/O
# ---------------------------------------------------------------------------

def _build_level_data(objects, name, music_file, meta):
    file_meta = dict(meta) if meta else _default_meta(name)
    file_meta["name"] = name
    if music_file is not None:
        file_meta["music"] = music_file
    file_meta = _migrate(file_meta)
    data = dict(file_meta)
    data["objects"] = [normalize_object(o) for o in objects]
    return data


def save_level(objects, name, filename=None, music_file=None, meta=None):
    """Write a level JSON and refresh its thumbnail.  Returns the path."""
    ensure_dirs()
    data = _build_level_data(objects, name, music_file, meta)
    fn = filename or _safe_filename(name)
    if not fn.endswith(".json"):
        fn += ".json"
    path = os.path.join(LEVELS_DIR, fn)
    _write_json(path, data)
    try:
        from .thumbnails import save_thumbnail
        save_thumbnail(fn, data["objects"])
    except Exception:
        pass
    return path


def load_level_full(path):
    """Return ``(meta, objects)`` for a level file."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        data = {}
    meta = _migrate(data)
    objects = _migrate_objects(data.get("objects", []), data.get("v", 0))
    return meta, objects


def load_level(path):
    """Legacy shape: ``(name, objects, music_file)``."""
    meta, objects = load_level_full(path)
    return meta["name"], objects, meta.get("music")


def update_meta(path, **updates):
    """Merge updates into a level's meta, leaving objects untouched."""
    meta, objects = load_level_full(path)
    meta.update(updates)
    save_level(objects, meta["name"], os.path.basename(path), meta=meta)


def list_levels():
    """Sorted JSON basenames in the levels dir (reserved ``_`` files hidden)."""
    ensure_dirs()
    return sorted(
        f for f in os.listdir(LEVELS_DIR)
        if f.endswith(".json") and not f.startswith("_")
    )


def list_level_summaries():
    """``[(filename, meta), ...]`` for every stored level."""
    out = []
    for f in list_levels():
        try:
            with open(os.path.join(LEVELS_DIR, f), encoding="utf-8") as fh:
                data = json.load(fh)
            out.append((f, _migrate(data)))
        except (json.JSONDecodeError, OSError):
            continue
    return out


# ---------------------------------------------------------------------------
# Editor autosave (reserved slot + rolling backups)
# ---------------------------------------------------------------------------

AUTOSAVE_FILENAME = "_autosave.json"
AUTOSAVE_BACKUP_DIR = "_autosave_backups"
AUTOSAVE_BACKUP_MAX = 10


def _autosave_path():
    return os.path.join(LEVELS_DIR, AUTOSAVE_FILENAME)


def _autosave_backup_dir():
    return os.path.join(LEVELS_DIR, AUTOSAVE_BACKUP_DIR)


def _rotate_autosave_backups(data):
    bdir = _autosave_backup_dir()
    try:
        os.makedirs(bdir, exist_ok=True)
        _write_json(os.path.join(
            bdir, time.strftime("autosave-%Y%m%d-%H%M%S.json")), data)
        entries = sorted(f for f in os.listdir(bdir)
                         if f.startswith("autosave-") and f.endswith(".json"))
    except OSError:
        return
    for stale in entries[:-AUTOSAVE_BACKUP_MAX]:
        try:
            os.remove(os.path.join(bdir, stale))
        except OSError:
            pass


def list_autosave_backups():
    """``[(filename, mtime, data), ...]`` newest first."""
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
    """Write the editor's recovery snapshot (and a rolling backup)."""
    ensure_dirs()
    data = _build_level_data(objects, name, music_file, meta)
    data["_autosave_source"] = source_filename or ""
    data["_autosave_ts"] = int(time.time())
    path = _autosave_path()
    _write_json(path, data)
    _rotate_autosave_backups(data)
    return path


def has_autosave():
    return os.path.isfile(_autosave_path())


def load_autosave():
    """``(meta, objects)`` for the autosave slot, or ``(None, None)``."""
    path = _autosave_path()
    if not os.path.isfile(path):
        return None, None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None, None
    meta = _migrate(data)
    objects = _migrate_objects(data.get("objects", []), data.get("v", 0))
    return meta, objects


def clear_autosave():
    try:
        os.remove(_autosave_path())
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Id allocation helpers (editor)
# ---------------------------------------------------------------------------

def _smallest_unused(used):
    i = 1
    while i in used:
        i += 1
    return i


def next_group_id(objects):
    """Smallest unused teleport-orb/portal group id (reads legacy ``link``
    too)."""
    return _smallest_unused({get_group_id(o) for o in objects
                             if o["t"] in TELEPORT_LINK_TYPES
                             and get_group_id(o) > 0})


# Legacy alias.
next_teleport_link = next_group_id


def next_object_id(objects):
    return _smallest_unused({o.get("oid", 0) for o in objects
                             if o.get("oid", 0) > 0})


def next_coin_id(objects):
    return _smallest_unused({o.get("coin_id", 0) for o in objects
                             if o["t"] == T_COIN and o.get("coin_id", 0) > 0})
