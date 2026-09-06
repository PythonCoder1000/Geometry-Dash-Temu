"""Pure object-list operations for the editor (no drawing, no pygame UI).

Everything here takes the level's ``objects`` list (and plain values)
and mutates / returns data.  The session module wires these to input.
"""

import os
import re
import time

import pygame

from ..constants import (
    CELL, DEFAULT_MOVE_CURVE, _USER_DATA,
    T_START, T_TELEPORT_ORB, T_MOVE_TRIGGER, T_FOLLOW_TRIGGER,
    T_ROTATE_TRIGGER, T_COIN, T_JUMP_PREDICTOR, T_SLOPE, T_SLAB,
    DASH_ORB_TYPES, T_SPIDER_ORB, T_SPIDER_PAD,
)
from ..geometry import obj_scale, normalize_rotation, slope_polygon, slab_rect
from ..graphics import draw_obj
from ..levels import (
    next_group_id, next_object_id, next_coin_id, get_group_id,
)
from ..objects import seed_defaults, spec_for

MAX_UNDO_STACK = 60

# Objects whose sprite is an arrow-like direction indicator: a horizontal
# flip reverses the pointing direction (r -> 180 - r) instead of
# mirroring a symmetric shape (r -> -r).
_ARROW_TYPES = frozenset(DASH_ORB_TYPES)
_DIR_FLIP_H = {"left": "right", "right": "left"}
_DIR_FLIP_V = {"up": "down", "down": "up"}


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def objects_at_cell(objects, gx, gy):
    return [o for o in objects if o["x"] == gx and o["y"] == gy]


def object_at_cell(objects, gx, gy, prefer_non_start=True):
    hits = objects_at_cell(objects, gx, gy)
    if not hits:
        return None
    if prefer_non_start:
        non_start = [o for o in hits if o["t"] != T_START]
        if non_start:
            return non_start[-1]
    return hits[-1]


def objects_in_cells(objects, gx0, gy0, gx1, gy1):
    return [o for o in objects
            if gx0 <= o["x"] <= gx1 and gy0 <= o["y"] <= gy1]


def selection_bounds(objs):
    """``(min_x, min_y, max_x, max_y)`` in cells."""
    xs = [o["x"] for o in objs]
    ys = [o["y"] for o in objs]
    return min(xs), min(ys), max(xs), max(ys)


def shared_type(objs):
    if not objs:
        return None
    t = objs[0]["t"]
    return t if all(o["t"] == t for o in objs) else None


def initial_objects():
    from ..constants import T_BLOCK
    return [{"t": T_BLOCK, "x": gx, "y": 10, "r": 0} for gx in range(60)]


# ---------------------------------------------------------------------------
# Placement / deletion
# ---------------------------------------------------------------------------

def place_object(objects, gx, gy, selected_type, rotation, group_id_counter=0):
    """Append a new object of ``selected_type`` at a cell.  Registry
    defaults are seeded; single-instance types move instead of stack."""
    if selected_type == T_START:
        objects[:] = [o for o in objects if o["t"] != T_START]
        objects.append({"t": T_START, "x": gx, "y": gy, "r": rotation})
        return objects[-1]
    if selected_type == T_JUMP_PREDICTOR:
        from ..jump_predictor import detect_mode, detect_mini
        existing = next((o for o in objects if o["t"] == T_JUMP_PREDICTOR), None)
        if existing is None:
            existing = {"t": T_JUMP_PREDICTOR, "x": gx, "y": gy, "r": 0}
            objects.append(existing)
        existing.update(x=gx, y=gy, dx=0, dy=0,
                        mode=detect_mode(objects, gx),
                        mini=detect_mini(objects, gx))
        seed_defaults(existing)
        return existing
    obj = {"t": selected_type, "x": gx, "y": gy, "r": rotation}
    seed_defaults(obj)
    if selected_type == T_TELEPORT_ORB:
        obj["group_id"] = group_id_counter or next_group_id(objects)
    elif selected_type == T_COIN:
        obj["coin_id"] = next_coin_id(objects)
    elif selected_type == T_MOVE_TRIGGER:
        obj["curve"] = [list(p) for p in DEFAULT_MOVE_CURVE]
    objects.append(obj)
    return obj


def erase_at(objects, gx, gy, only_type=None):
    """Remove every object at a cell (or only those of ``only_type``).
    Returns the number removed."""
    before = len(objects)
    objects[:] = [o for o in objects
                  if not (o["x"] == gx and o["y"] == gy
                          and (only_type is None or o["t"] == only_type))]
    return before - len(objects)


def remove_objects(objects, victims):
    ids = {id(o) for o in victims}
    objects[:] = [o for o in objects if id(o) not in ids]


def ensure_curve(obj):
    curve = obj.get("curve")
    if not isinstance(curve, list) or len(curve) < 2:
        curve = [list(p) for p in DEFAULT_MOVE_CURVE]
        obj["curve"] = curve
    return curve


def move_in_stack(objects, obj, delta):
    """Reorder ``obj`` among the objects sharing its cell."""
    if obj not in objects:
        return
    positions = [i for i, o in enumerate(objects)
                 if o["x"] == obj["x"] and o["y"] == obj["y"]]
    cur = positions.index(objects.index(obj))
    new = cur + delta
    if 0 <= new < len(positions):
        a, b = positions[cur], positions[new]
        objects[a], objects[b] = objects[b], objects[a]


# ---------------------------------------------------------------------------
# Undo
# ---------------------------------------------------------------------------

def snapshot(objects):
    return [dict(o) for o in objects]


def push_undo(undo_stack, redo_stack, objects):
    undo_stack.append(snapshot(objects))
    if len(undo_stack) > MAX_UNDO_STACK:
        undo_stack.pop(0)
    redo_stack.clear()


# ---------------------------------------------------------------------------
# Clone / clipboard
# ---------------------------------------------------------------------------

def clone_objects(srcs, target_first_xy, all_objects):
    """Copies of ``srcs`` anchored so the first lands at
    ``target_first_xy``; fresh ``oid`` / ``group_id`` values so cloned
    triggers reference their cloned siblings.  ``coin_id`` is dropped
    (reassigned on load)."""
    if not srcs:
        return []
    base = srcs[0]
    if "_offset_x" in base:
        def get_offset(s):
            return s.get("_offset_x", 0), s.get("_offset_y", 0)
    else:
        bx, by = base["x"], base["y"]

        def get_offset(s):
            return s["x"] - bx, s["y"] - by
    target_x, target_y = target_first_xy
    used_oids = {o.get("oid", 0) for o in all_objects if o.get("oid", 0) > 0}
    used_groups = {get_group_id(o) for o in all_objects
                   if o.get("t") == T_TELEPORT_ORB and get_group_id(o) > 0}

    def alloc(used):
        i = 1
        while i in used:
            i += 1
        used.add(i)
        return i

    oid_map = {}
    group_map = {}
    for src in srcs:
        soid = src.get("oid")
        if soid and soid not in oid_map:
            oid_map[soid] = alloc(used_oids)
        if src.get("t") == T_TELEPORT_ORB:
            sgid = get_group_id(src)
            if sgid and sgid not in group_map:
                group_map[sgid] = alloc(used_groups)
    cloned = []
    for src in srcs:
        new = {k: v for k, v in src.items() if not k.startswith("_offset_")}
        ox, oy = get_offset(src)
        new["x"] = target_x + ox
        new["y"] = target_y + oy
        if new.get("oid") in oid_map:
            new["oid"] = oid_map[new["oid"]]
        if new.get("t") == T_TELEPORT_ORB:
            sgid = get_group_id(new)
            if sgid in group_map:
                new["group_id"] = group_map[sgid]
            elif sgid:
                new["group_id"] = sgid
            new.pop("link", None)
        for key in ("target_oid", "source_oid"):
            if new.get(key) in oid_map:
                new[key] = oid_map[new[key]]
        tgts = new.get("target_oids")
        if isinstance(tgts, list) and tgts:
            new["target_oids"] = [oid_map.get(t, t) for t in tgts]
        if isinstance(new.get("curve"), list):
            new["curve"] = [list(p) for p in new["curve"]]
        new.pop("coin_id", None)
        cloned.append(new)
    return cloned


def to_clipboard(objs):
    """Clipboard entries carry offsets relative to the first object."""
    if not objs:
        return []
    first = objs[0]
    out = []
    for o in objs:
        c = dict(o)
        c["_offset_x"] = o["x"] - first["x"]
        c["_offset_y"] = o["y"] - first["y"]
        out.append(c)
    return out


# ---------------------------------------------------------------------------
# Transforms (rotate / flip / nudge / scale)
# ---------------------------------------------------------------------------

def rotate_objects(objs, delta_deg, about_center=False):
    """Rotate every object's ``r`` by ``delta_deg``.  With
    ``about_center`` (multi-select) positions also orbit the selection's
    centre in 90-degree steps."""
    if about_center and len(objs) > 1 and delta_deg % 90 == 0:
        x0, y0, x1, y1 = selection_bounds(objs)
        cx = (x0 + x1) / 2.0
        cy = (y0 + y1) / 2.0
        turns = (int(round(delta_deg / 90)) % 4)
        for o in objs:
            dx = o["x"] - cx
            dy = o["y"] - cy
            for _ in range(turns):
                dx, dy = -dy, dx
            o["x"] = int(round(cx + dx))
            o["y"] = int(round(cy + dy))
    for o in objs:
        o["r"] = normalize_rotation(float(o.get("r", 0)) + delta_deg)


def _slope_flip_rotation(o, axis):
    """Rotation that makes the slope's triangle equal its mirror image."""
    gx, gy = o["x"], o["y"]
    pts = slope_polygon(gx, gy, o.get("r", 0))
    cx = gx * CELL + CELL / 2.0
    cy = gy * CELL + CELL / 2.0
    if axis == "h":
        mirrored = {(round(2 * cx - px), round(py)) for px, py in pts}
    else:
        mirrored = {(round(px), round(2 * cy - py)) for px, py in pts}
    for r in (0, 90, 180, 270):
        cand = {(round(px), round(py)) for px, py in slope_polygon(gx, gy, r)}
        if cand == mirrored:
            return r
    return normalize_rotation(o.get("r", 0))


def _slab_flip_rotation(o, axis):
    gx, gy = o["x"], o["y"]
    r0 = slab_rect(gx, gy, o.get("r", 0))
    cx = gx * CELL + CELL / 2.0
    cy = gy * CELL + CELL / 2.0
    if axis == "h":
        target = (round(2 * cx - r0.right), r0.top, round(2 * cx - r0.left), r0.bottom)
    else:
        target = (r0.left, round(2 * cy - r0.bottom), r0.right, round(2 * cy - r0.top))
    for r in (0, 90, 180, 270):
        rr = slab_rect(gx, gy, r)
        if (rr.left, rr.top, rr.right, rr.bottom) == target:
            return r
    return normalize_rotation(o.get("r", 0))


def flip_objects(objs, axis):
    """Mirror the selection horizontally (``"h"``) or vertically
    (``"v"``) about its centre, updating each sprite's rotation so the
    result looks like a true mirror image."""
    if not objs:
        return
    x0, y0, x1, y1 = selection_bounds(objs)
    for o in objs:
        if axis == "h":
            o["x"] = x0 + x1 - o["x"]
        else:
            o["y"] = y0 + y1 - o["y"]
        t = o["t"]
        r = float(o.get("r", 0))
        if t == T_SLOPE:
            o["r"] = _slope_flip_rotation(o, axis)
        elif t == T_SLAB:
            o["r"] = _slab_flip_rotation(o, axis)
        elif t in _ARROW_TYPES:
            o["r"] = normalize_rotation((180 - r) if axis == "h" else -r)
        else:
            o["r"] = normalize_rotation(-r if axis == "h" else (180 - r))
        if t in (T_SPIDER_ORB, T_SPIDER_PAD):
            table = _DIR_FLIP_H if axis == "h" else _DIR_FLIP_V
            o["dir"] = table.get(o.get("dir", "auto"), o.get("dir", "auto"))
        if t == T_MOVE_TRIGGER and "tx" in o:
            if axis == "h":
                o["tx"] = x0 + x1 - o["tx"]
            else:
                o["ty"] = y0 + y1 - o["ty"]


def nudge_objects(objs, dx, dy):
    for o in objs:
        o["x"] += dx
        o["y"] += dy
        if o["t"] == T_MOVE_TRIGGER:
            if "tx" in o:
                o["tx"] += dx
            if "ty" in o:
                o["ty"] += dy


SCALE_STEP = 0.25
SCALE_MIN = 0.25
SCALE_MAX = 4.0


def step_scale(current, delta):
    new = current + delta * SCALE_STEP
    return max(SCALE_MIN, min(SCALE_MAX, round(new / SCALE_STEP) * SCALE_STEP))


def set_scale(o, sx, sy=None):
    """Write a uniform ``scale`` or per-axis ``sx``/``sy``."""
    sy = sx if sy is None else sy
    sx = max(SCALE_MIN, min(SCALE_MAX, round(sx, 3)))
    sy = max(SCALE_MIN, min(SCALE_MAX, round(sy, 3)))
    if abs(sx - sy) < 1e-6:
        o["scale"] = sx
        o.pop("sx", None)
        o.pop("sy", None)
    else:
        o["sx"] = sx
        o["sy"] = sy
        o.pop("scale", None)


def scale_objects(objs, delta):
    for o in objs:
        sx, sy = obj_scale(o)
        set_scale(o, step_scale(sx, delta), step_scale(sy, delta))


def parse_scale_text(raw):
    """``"1.5"`` / ``"200%"`` / ``"1.5,0.75"`` -> ``(sx, sy)`` or None."""
    s = (raw or "").strip().lower()
    parts = [p for p in s.replace("x", " ").replace(",", " ").replace("/", " ").split() if p]
    if not parts:
        return None

    def one(tok):
        pct = tok.endswith("%")
        tok = tok.rstrip("%")
        try:
            v = float(tok)
        except ValueError:
            return None
        return v / 100.0 if pct else v

    sx = one(parts[0])
    sy = one(parts[1]) if len(parts) > 1 else sx
    if sx is None or sy is None:
        return None
    return sx, sy


def parse_rotation_text(raw):
    s = (raw or "").strip().lower()
    for suf in ("degrees", "deg", "°"):
        if s.endswith(suf):
            s = s[:-len(suf)].strip()
    try:
        return normalize_rotation(float(s))
    except ValueError:
        return None


def toggle_flag(objs, key):
    """All-on-or-all-off boolean toggle across a selection.  Returns the
    new state."""
    new_state = any(not o.get(key) for o in objs)
    for o in objs:
        if new_state:
            o[key] = True
        else:
            o.pop(key, None)
    return new_state


# ---------------------------------------------------------------------------
# Link (group) tool state machine
# ---------------------------------------------------------------------------

def link_click(objects, gx, gy, pending):
    """Advance the link tool.  Returns ``(new_pending, message)``.

    * teleport orb -> click a partner orb to share a group id
    * move / rotate trigger -> click target objects, Enter, then click
      the destination cell (move) / finish (rotate)
    * follow trigger -> click source then target (or just the follower
      when ``follow_player`` is set)
    """
    clicked = object_at_cell(objects, gx, gy, prefer_non_start=True)
    if pending is None:
        if not clicked:
            return None, "Click a teleport orb or a move / rotate / follow trigger"
        t = clicked["t"]
        if t == T_TELEPORT_ORB:
            return ({"kind": "teleport", "first": clicked},
                    f"Select partner orb (group={get_group_id(clicked)})")
        if t in (T_MOVE_TRIGGER, T_ROTATE_TRIGGER):
            return ({"kind": "targets", "trigger": clicked, "targets": [],
                     "phase": "select"},
                    "Click objects to target (Enter when done)")
        if t == T_FOLLOW_TRIGGER:
            what = ("the object that follows the player"
                    if clicked.get("follow_player")
                    else "the SOURCE object (the one being followed)")
            return {"kind": "follow", "trigger": clicked, "source": None}, f"Click {what}"
        return None, "Click a teleport orb or a move / rotate / follow trigger"
    kind = pending.get("kind")
    if kind == "teleport":
        first = pending["first"]
        if clicked is first:
            return None, "Link cancelled"
        if not clicked or clicked["t"] != T_TELEPORT_ORB:
            return pending, "Click another teleport orb"
        gid = get_group_id(first) or get_group_id(clicked) or next_group_id(objects)
        first["group_id"] = gid
        clicked["group_id"] = gid
        first.pop("link", None)
        clicked.pop("link", None)
        return None, f"Linked orbs as group {gid}"
    if kind == "targets":
        trig = pending["trigger"]
        if pending.get("phase") == "select":
            if clicked is trig:
                return None, "Target selection cancelled"
            if not clicked:
                return pending, "Click objects to target (Enter when done)"
            targets = pending["targets"]
            if clicked in targets:
                targets.remove(clicked)
            else:
                clicked["oid"] = clicked.get("oid") or next_object_id(objects)
                targets.append(clicked)
            return pending, f"{len(targets)} target(s) — click more or press Enter"
        oids = [t.get("oid", 0) for t in pending["targets"]]
        trig["target_oids"] = oids
        trig["target_oid"] = oids[0] if oids else 0
        trig["tx"] = gx
        trig["ty"] = gy
        return None, f"Move trigger -> ({gx},{gy}) for {len(oids)} object(s)"
    if kind == "follow":
        trig = pending["trigger"]
        if clicked is trig:
            return None, "Link cancelled"
        if not clicked:
            return pending, "Click an object (click the trigger to cancel)"
        if trig.get("follow_player"):
            clicked["oid"] = clicked.get("oid") or next_object_id(objects)
            trig["source_oid"] = clicked["oid"]
            return None, f"Follow player: oid {clicked['oid']} tracks the player"
        if pending.get("source") is None:
            clicked["oid"] = clicked.get("oid") or next_object_id(objects)
            pending["source"] = clicked
            return pending, "Now click the TARGET object (the one that follows)"
        if clicked is pending["source"]:
            return pending, "Source and target must differ"
        clicked["oid"] = clicked.get("oid") or next_object_id(objects)
        trig["source_oid"] = pending["source"]["oid"]
        trig["target_oid"] = clicked["oid"]
        return None, f"Follow link: oid {trig['source_oid']} -> {clicked['oid']}"
    return None, "Link cleared"


def link_confirm_targets(objects, pending):
    """Enter pressed while selecting targets: move triggers proceed to
    the destination phase, rotate triggers finish immediately."""
    if not pending or pending.get("kind") != "targets":
        return pending, ""
    targets = pending.get("targets", [])
    if not targets:
        return pending, "Select at least one target object first"
    trig = pending["trigger"]
    if trig["t"] == T_ROTATE_TRIGGER:
        oids = [t.get("oid", 0) for t in targets]
        trig["target_oids"] = oids
        trig["target_oid"] = oids[0]
        return None, f"Rotate trigger targets {len(oids)} object(s)"
    pending["phase"] = "dest"
    return pending, f"Click the destination cell for {len(targets)} object(s)"


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export_level_png(objects, level_name, cell_px=10):
    """Render the whole level to one PNG under the user data dir.
    Returns the path, or None on failure / empty level."""
    if not objects:
        return None
    min_x = min(o["x"] for o in objects)
    max_x = max(o["x"] for o in objects)
    min_y = min(o["y"] for o in objects)
    max_y = max(o["y"] for o in objects)
    pad = 2
    w = max(1, (max_x - min_x) + 1 + 2 * pad) * cell_px
    h = max(1, (max_y - min_y) + 1 + 2 * pad) * cell_px
    if w * h > 16000 * 2000:
        return None
    surf = pygame.Surface((w, h), pygame.SRCALPHA)
    surf.fill((18, 14, 30))
    for o in objects:
        sx = (o["x"] - min_x + pad) * cell_px
        sy = (o["y"] - min_y + pad) * cell_px
        try:
            draw_obj(surf, o["t"], sx, sy, cell_px, 0, o.get("r", 0), o,
                     scale=obj_scale(o))
        except Exception:
            continue
    out_dir = os.path.join(_USER_DATA, "exports")
    try:
        os.makedirs(out_dir, exist_ok=True)
    except OSError:
        return None
    safe = re.sub(r"[^\w\-]+", "_", level_name or "level").strip("_") or "level"
    path = os.path.join(out_dir, f"{safe}_{time.strftime('%Y%m%d_%H%M%S')}.png")
    try:
        pygame.image.save(surf, path)
    except (pygame.error, OSError):
        return None
    return path


def type_name(t):
    return spec_for(t).name
