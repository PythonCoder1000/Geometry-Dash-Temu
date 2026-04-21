import os

import pygame

from constants import (
    WIDTH, HEIGHT, CELL, FPS,
    C_GRID, C_WHITE, C_GRAY, C_PLAYER, C_BTN, C_DANGER, C_DARK,
    C_PUBLISH, C_SUCCESS,
    PALETTE_CATEGORIES, TYPE_NAMES, TYPE_TIPS, ALL_TYPES, BG_PRESETS,
    T_BLOCK, T_START, T_TELEPORT_ORB, T_CAMERA_TRIGGER, T_BG_TRIGGER,
    T_MOVE_TRIGGER, T_SAW, T_COLOR_TRIGGER, T_COIN, T_END, T_MODE_DUAL,
    DEFAULT_MOVE_CURVE, MOVE_CURVE_SPEED_MAX,
)
from graphics import (
    draw_bg, draw_obj, txt, btn, make_rect, make_stars, make_mountains,
    lighter, darker, normalize_rotation,
    speaker_icon, icon_button, draw_end_wall,
    spike_hitboxes, saw_hitbox,
)
from levels import (
    save_level, load_level, load_level_full, update_meta,
    next_group_id, next_object_id, next_coin_id, get_group_id,
    save_autosave, load_autosave, has_autosave, clear_autosave,
)
from menus import (
    text_input_dialog, load_level_dialog, difficulty_picker, confirm_dialog,
    snippet_picker,
)
from snippets import save_user_snippet, normalize_to_origin
import music
import sfx
import settings
from input_guard import ClickGuard


# Reusable fullscreen SRCALPHA scratch for the hitbox overlay — allocated on
# first use and retained across editor sessions so repeated toggles don't
# allocate a new WIDTH*HEIGHT surface each frame. Stored as a single-slot
# list to keep the lazy-init pattern readable.
_hb_scratch = [None]


def _export_level_png(objects, level_name, cell_px=10):
    """Render the whole level to a single PNG and return the filepath.

    Writes to ``{USER_DATA}/exports/`` so frozen builds work without
    needing write access to the bundle. Each object renders at
    ``cell_px`` pixels per grid cell (small enough that a 1000-cell-wide
    level fits in a manageable image).
    """
    import os as _os_exp
    import re as _re_exp
    import time as _time_exp
    from constants import _USER_DATA
    if not objects:
        return None
    min_x = min(o["x"] for o in objects)
    max_x = max(o["x"] for o in objects)
    min_y = min(o["y"] for o in objects)
    max_y = max(o["y"] for o in objects)
    # Pad 2 cells on each side so the frame doesn't hug the bounds.
    pad = 2
    w_cells = max(1, (max_x - min_x) + 1 + 2 * pad)
    h_cells = max(1, (max_y - min_y) + 1 + 2 * pad)
    surf_w = w_cells * cell_px
    surf_h = h_cells * cell_px
    # Guard absurdly large exports (e.g. levels with stray far-x objects).
    MAX_PIXELS = 16000 * 2000
    if surf_w * surf_h > MAX_PIXELS:
        return None
    surf = pygame.Surface((surf_w, surf_h), pygame.SRCALPHA)
    surf.fill((18, 14, 30))
    for o in objects:
        sx = (o["x"] - min_x + pad) * cell_px
        sy = (o["y"] - min_y + pad) * cell_px
        meta_arg = (o if o["t"] in
                    (T_TELEPORT_ORB, T_CAMERA_TRIGGER, T_BG_TRIGGER,
                     T_MOVE_TRIGGER, T_COLOR_TRIGGER) else None)
        try:
            draw_obj(surf, o["t"], sx, sy, cell_px, 0,
                     o.get("r", 0), meta_arg)
        except Exception:
            continue
    out_dir = _os_exp.path.join(_USER_DATA, "exports")
    try:
        _os_exp.makedirs(out_dir, exist_ok=True)
    except OSError:
        return None
    safe = _re_exp.sub(r"[^\w\-]+", "_", level_name or "level").strip("_") \
        or "level"
    fn = f"{safe}_{_time_exp.strftime('%Y%m%d_%H%M%S')}.png"
    path = _os_exp.path.join(out_dir, fn)
    try:
        pygame.image.save(surf, path)
    except (pygame.error, OSError):
        return None
    return path


# Editor keyboard cheat sheet — rendered centered on demand (press `?` /
# F1 / `/`). Grouped by function so the user can skim for what they
# want. Update this list when a new shortcut lands; cramming more
# shortcuts into the bottom hints strip is the footgun this replaces.
_EDITOR_SHORTCUTS = [
    ("Tools", [
        ("B", "Brush (place objects)"),
        ("E", "Erase"),
        ("N", "Group tool"),
        ("I", "Edit / inspect"),
        ("F2", "Snippet library"),
    ]),
    ("Palette / placement", [
        ("Tab / Shift+Tab", "Cycle category"),
        ("1 – 9", "Pick item in current row"),
        ("R / Q", "Rotate selection"),
        ("Wheel on palette", "Rotate current item"),
    ]),
    ("Navigation", [
        ("Arrows / WASD", "Pan canvas (Shift = 2×)"),
        ("Middle click drag", "Pan canvas"),
        ("Wheel on canvas", "Zoom (Shift = finer)"),
        ("Ctrl + = / -", "Zoom in / out (centre)"),
        ("Ctrl + 0", "Reset zoom to 1.0×"),
    ]),
    ("Selection", [
        ("Click + drag", "Marquee select"),
        ("^A", "Select all"),
        ("Del", "Delete selection"),
        ("^C / ^X / ^V", "Copy / cut / paste"),
        ("^D", "Duplicate"),
    ]),
    ("History / view", [
        ("^Z / ^Y", "Undo / redo"),
        ("G", "Toggle grid"),
        ("H", "Toggle hitbox overlay"),
    ]),
    ("Run / save", [
        ("T", "Test play"),
        ("Shift+T", "Test from cursor (music seeks)"),
        ("K", "Bot menu"),
        ("L", "Auto-solve hint"),
        ("S", "Save level"),
        ("^L", "Load level"),
        ("^E", "Export as PNG"),
        ("Esc", "Back to menu"),
    ]),
    ("Help", [
        ("? / F1 / /", "Toggle this cheat sheet"),
    ]),
]


def _draw_editor_cheat_sheet(screen):
    ov = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    ov.fill((0, 0, 0, 200))
    screen.blit(ov, (0, 0))
    panel_w, panel_h = 880, 560
    panel = pygame.Rect((WIDTH - panel_w) // 2,
                        (HEIGHT - panel_h) // 2,
                        panel_w, panel_h)
    pygame.draw.rect(screen, (16, 16, 28), panel, border_radius=14)
    pygame.draw.rect(screen, (90, 110, 190), panel, 2, border_radius=14)
    txt(screen, "KEYBOARD SHORTCUTS",
        panel.centerx, panel.y + 26, 24, C_WHITE, True, shadow=True)
    # Two-column layout — split by row-count so adding / removing a
    # group keeps columns roughly balanced without having to re-tune a
    # hardcoded index.
    total_rows = sum(1 + len(items) for _, items in _EDITOR_SHORTCUTS)
    left_groups = []
    right_groups = []
    acc = 0
    for grp in _EDITOR_SHORTCUTS:
        rows_here = 1 + len(grp[1])
        if acc < total_rows / 2 and acc + rows_here <= total_rows / 2 + rows_here / 2:
            left_groups.append(grp)
            acc += rows_here
        else:
            right_groups.append(grp)
    col_w = (panel_w - 80) // 2
    col_gap = 20

    def _draw_col(groups, col_x):
        y = panel.y + 68
        for title, items in groups:
            txt(screen, title, col_x, y, 16, (150, 190, 255))
            y += 22
            for key, desc in items:
                txt(screen, key, col_x + 10, y, 13, (255, 220, 120))
                txt(screen, desc, col_x + 150, y, 13, C_WHITE)
                y += 18
            y += 10

    _draw_col(left_groups, panel.x + 40)
    _draw_col(right_groups, panel.x + 40 + col_w + col_gap)
    txt(screen, "Press ? / F1 / / or Esc to close",
        panel.centerx, panel.bottom - 22, 12, (170, 170, 190), True)

# Pre-rendered grid-line surface, keyed on effective_cell size (== CELL *
# zoom_level rounded to int). Replaces ~48 pygame.draw.line calls per
# frame with a single offset blit. Rebuilt lazily when the zoom changes.
_grid_cache = {"cell": 0, "surf": None}


def _get_grid_surface(effective_cell):
    if (_grid_cache["cell"] != effective_cell or
            _grid_cache["surf"] is None):
        surf_w = WIDTH + effective_cell
        surf_h = (BAR_Y - TOP_H) + effective_cell
        surf = pygame.Surface((surf_w, surf_h), pygame.SRCALPHA)
        for x in range(0, surf_w, effective_cell):
            pygame.draw.line(surf, C_GRID, (x, 0), (x, surf_h), 1)
        for y in range(0, surf_h, effective_cell):
            pygame.draw.line(surf, C_GRID, (0, y), (surf_w, y), 1)
        _grid_cache["cell"] = effective_cell
        _grid_cache["surf"] = surf
    return _grid_cache["surf"]
from play import run_play
from bot import BotController, load_bot_inputs
# `autobot` is no longer imported here — the bot menu (`bot_menu.py`) owns
# all solver invocations. The legacy K-key shortcut still uses BotController.


TAB_H = 32
PAL_Y = TAB_H
PAL_H = 62
TOP_H = TAB_H + PAL_H
BAR_Y = HEIGHT - 55

TOOL_BRUSH = "brush"
TOOL_ERASE = "erase"
TOOL_GROUP = "group"  # was "link" — see _group_click for the pairing logic
TOOL_EDIT = "edit"
TOOL_BOT_PATH = "bot_path"

# Backwards-compat alias for any external code that still imports the old
# constant. Editor's bot/snippet history may pickle this string.
TOOL_LINK = TOOL_GROUP

CURVE_H = 110
CURVE_PAD = 10
CURVE_HIT_R2 = 110

MAX_UNDO_STACK = 50

# Auto-save: write a recovery snapshot every AUTOSAVE_INTERVAL frames whenever
# the level has unsaved changes. The snapshot lives in `_autosave.json` and is
# offered for recovery when the editor is next opened.
AUTOSAVE_INTERVAL = 30 * FPS  # 30 seconds at 60Hz
AUTOSAVE_FLASH_FRAMES = 90    # how long the "Auto-saved" toast lingers


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


def _initial_objects():
    return [{"t": T_BLOCK, "x": gx, "y": 10, "r": 0} for gx in range(60)]


def _place_object(objects, gx, gy, selected_type, rotation, group_id_counter):
    if selected_type == T_START:
        objects[:] = [o for o in objects if o["t"] != T_START]
        objects.append({"t": T_START, "x": gx, "y": gy, "r": rotation})
        return
    for o in objects:
        if (o["x"] == gx and o["y"] == gy and o["t"] == selected_type
                and o.get("r", 0) == rotation):
            return
    obj = {"t": selected_type, "x": gx, "y": gy, "r": rotation}
    if selected_type == T_TELEPORT_ORB:
        obj["group_id"] = group_id_counter
    elif selected_type == T_CAMERA_TRIGGER:
        obj["cy"] = gy
    elif selected_type == T_BG_TRIGGER:
        obj["bg"] = 0
    elif selected_type == T_COLOR_TRIGGER:
        obj["col_idx"] = 0
    elif selected_type == T_COIN:
        obj["coin_id"] = next_coin_id(objects)
    elif selected_type == T_MOVE_TRIGGER:
        obj["target_oid"] = 0
        obj["tx"] = gx
        obj["ty"] = gy
        obj["duration"] = 30
        obj["curve"] = [list(p) for p in DEFAULT_MOVE_CURVE]
    elif selected_type == T_MODE_DUAL:
        # Default the mirror's spawn row to the portal's own row so the
        # editor immediately shows it as an editable parameter (use < / >
        # in the edit panel to move it up or down).
        obj["spawn_y"] = gy
    objects.append(obj)


def _ensure_curve(obj):
    curve = obj.get("curve")
    if not isinstance(curve, list) or len(curve) < 2:
        curve = [list(p) for p in DEFAULT_MOVE_CURVE]
        obj["curve"] = curve
    return curve


def _curve_point_to_px(rect, t, s):
    inner_x = rect.x + CURVE_PAD
    inner_y = rect.y + CURVE_PAD
    inner_w = rect.w - 2 * CURVE_PAD
    inner_h = rect.h - 2 * CURVE_PAD
    px = inner_x + t * inner_w
    py = inner_y + (1.0 - min(MOVE_CURVE_SPEED_MAX, max(0.0, s)) / MOVE_CURVE_SPEED_MAX) * inner_h
    return int(round(px)), int(round(py))


def _px_to_curve_point(rect, px, py):
    inner_x = rect.x + CURVE_PAD
    inner_y = rect.y + CURVE_PAD
    inner_w = max(1, rect.w - 2 * CURVE_PAD)
    inner_h = max(1, rect.h - 2 * CURVE_PAD)
    t = (px - inner_x) / inner_w
    s = (1.0 - (py - inner_y) / inner_h) * MOVE_CURVE_SPEED_MAX
    return max(0.0, min(1.0, t)), max(0.0, min(MOVE_CURVE_SPEED_MAX, s))


def _erase_at(objects, gx, gy):
    objects[:] = [o for o in objects if not (o["x"] == gx and o["y"] == gy)]


def _push_undo(undo_stack, redo_stack, objects):
    """Push current object state to undo stack."""
    undo_stack.append([dict(o) for o in objects])
    if len(undo_stack) > MAX_UNDO_STACK:
        undo_stack.pop(0)
    redo_stack.clear()


def _clone_objects(srcs, target_first_xy, all_objects):
    """Clone `srcs` so they can be inserted into `all_objects` as a fresh copy.

    Anchors the first source's clone at `target_first_xy` and preserves the
    relative positions of the rest. Allocates fresh `oid` / `group_id` ids
    so any cloned move-trigger or teleport-orb references its cloned siblings
    rather
    than the originals it was copied from. `coin_id` is dropped — load_level
    will reassign deterministically.

    `srcs` items may be either live editor objects or clipboard objects with
    `_offset_x`/`_offset_y` keys recording their relative offset at copy time.

    Returns a new list of clone dicts; the caller is responsible for appending
    them to `all_objects`.
    """
    if not srcs:
        return []
    base = srcs[0]
    if "_offset_x" in base:
        # Clipboard items already carry per-item offsets; the first item's
        # offset is implicitly (0, 0).
        get_offset = lambda s: (s.get("_offset_x", 0), s.get("_offset_y", 0))
    else:
        bx, by = base["x"], base["y"]
        get_offset = lambda s, _bx=bx, _by=by: (s["x"] - _bx, s["y"] - _by)
    target_x, target_y = target_first_xy

    used_oids = {o.get("oid", 0) for o in all_objects if o.get("oid", 0) > 0}
    used_groups = {get_group_id(o) for o in all_objects
                   if o.get("t") == T_TELEPORT_ORB and get_group_id(o) > 0}

    def _alloc(used):
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
            oid_map[soid] = _alloc(used_oids)
        if src.get("t") == T_TELEPORT_ORB:
            sgid = get_group_id(src)
            if sgid and sgid not in group_map:
                group_map[sgid] = _alloc(used_groups)

    cloned = []
    for src in srcs:
        new_obj = {k: v for k, v in src.items()
                   if not k.startswith("_offset_")}
        ox, oy = get_offset(src)
        new_obj["x"] = target_x + ox
        new_obj["y"] = target_y + oy
        if "oid" in new_obj and new_obj["oid"] in oid_map:
            new_obj["oid"] = oid_map[new_obj["oid"]]
        # Migrate the legacy "link" field on the source as we re-id; the new
        # clone always uses "group_id".
        if new_obj.get("t") == T_TELEPORT_ORB:
            sgid = get_group_id(new_obj)
            if sgid in group_map:
                new_obj["group_id"] = group_map[sgid]
            elif sgid:
                new_obj["group_id"] = sgid
            new_obj.pop("link", None)
        if new_obj.get("target_oid") in oid_map:
            new_obj["target_oid"] = oid_map[new_obj["target_oid"]]
        tgts = new_obj.get("target_oids")
        if isinstance(tgts, list) and tgts:
            new_obj["target_oids"] = [oid_map.get(t, t) for t in tgts]
        new_obj.pop("coin_id", None)  # reassigned at load time
        cloned.append(new_obj)
    return cloned


def _link_click(objects, gx, gy, pending_link):
    """Group-tool click handler — pairs teleport orbs and connects move triggers.

    The internal nickname is still ``_link_click`` because the function
    handles two unrelated forms of "linking": teleport-orb pairing (now
    keyed on ``group_id``) and move-trigger target/destination wiring.
    User-facing labels read "group" everywhere for consistency with the
    ``group_id`` field on disk.
    """
    clicked = object_at_cell(objects, gx, gy, prefer_non_start=True)
    if pending_link is None:
        if not clicked:
            return None, "Click a teleport orb or move trigger"
        if clicked["t"] == T_TELEPORT_ORB:
            return ({"kind": "teleport", "first": clicked},
                    f"Select partner orb (group={get_group_id(clicked)})")
        if clicked["t"] == T_MOVE_TRIGGER:
            return ({"kind": "move", "trigger": clicked, "targets": [],
                     "phase": "select"},
                    "Click objects to move (Enter/Space when done)")
        return None, "Click a teleport orb or move trigger"
    kind = pending_link.get("kind")
    if kind == "teleport":
        first = pending_link["first"]
        if clicked is first:
            return None, "Group cancelled"
        if not clicked or clicked["t"] != T_TELEPORT_ORB:
            return pending_link, "Click another teleport orb"
        gid = (get_group_id(first) or get_group_id(clicked)
               or next_group_id(objects))
        first["group_id"] = gid
        clicked["group_id"] = gid
        # Legacy "link" key is now redundant — drop it so future saves are clean.
        first.pop("link", None)
        clicked.pop("link", None)
        return None, f"Grouped orbs as id {gid}"
    if kind == "move":
        trig = pending_link["trigger"]
        phase = pending_link.get("phase", "select")
        if phase == "select":
            # Selecting target objects
            if clicked is trig:
                return None, "Move target selection cancelled"
            if not clicked:
                return pending_link, "Click objects to move (Enter/Space when done)"
            # Toggle selection
            targets = pending_link["targets"]
            if clicked in targets:
                targets.remove(clicked)
                return pending_link, f"{len(targets)} target(s) selected — click more or Enter/Space"
            else:
                oid = clicked.get("oid") or next_object_id(objects)
                clicked["oid"] = oid
                targets.append(clicked)
                return pending_link, f"{len(targets)} target(s) selected — click more or Enter/Space"
        elif phase == "dest":
            # Setting destination
            oids = []
            for t_obj in pending_link["targets"]:
                oids.append(t_obj.get("oid", 0))
            trig["target_oids"] = oids
            # Keep backward compat: set target_oid to first
            trig["target_oid"] = oids[0] if oids else 0
            trig["tx"] = gx
            trig["ty"] = gy
            return None, f"Move trigger → ({gx},{gy}) for {len(oids)} object(s)"
    return None, "Group cleared"


def _link_confirm_targets(pending_link):
    """Confirm target selection for move trigger and move to dest phase."""
    if pending_link is None:
        return pending_link, ""
    if pending_link.get("kind") != "move":
        return pending_link, ""
    targets = pending_link.get("targets", [])
    if not targets:
        return pending_link, "Select at least one target object first"
    pending_link["phase"] = "dest"
    return pending_link, f"Click destination cell for {len(targets)} object(s)"


PANEL_X = WIDTH - 240
PANEL_Y = 104
PANEL_W = 230


def _palette_rects(active_cat):
    tab_rects = []
    x = 10
    for i in range(len(PALETTE_CATEGORIES)):
        r = pygame.Rect(x, 4, 92, TAB_H - 6)
        tab_rects.append(r)
        x += 96
    items = PALETTE_CATEGORIES[active_cat][1]
    item_rects = [(pygame.Rect(20 + i * 64, PAL_Y + 6, 52, 52), t)
                  for i, t in enumerate(items)]
    tools_x = WIDTH - 410
    tool_ids = [TOOL_BRUSH, TOOL_ERASE, TOOL_GROUP, TOOL_EDIT, TOOL_BOT_PATH]
    tool_rects = {
        tid: pygame.Rect(tools_x + i * 80, PAL_Y + 8, 76, 48)
        for i, tid in enumerate(tool_ids)
    }
    return tab_rects, item_rects, tool_rects


def _panel_button_rects(obj, stack_len=1):
    rects = {}
    y = PANEL_Y + 156
    if stack_len > 1:
        rects["stack_prev"] = pygame.Rect(PANEL_X + 20, y, 28, 26)
        rects["stack_next"] = pygame.Rect(PANEL_X + PANEL_W - 48, y, 28, 26)
        y += 32
        rects["stack_up"] = pygame.Rect(PANEL_X + 20, y, 28, 26)
        rects["stack_down"] = pygame.Rect(PANEL_X + PANEL_W - 48, y, 28, 26)
        y += 34
    rects["rot_prev"] = pygame.Rect(PANEL_X + 70, y + 6, 30, 30)
    rects["rot_next"] = pygame.Rect(PANEL_X + 170, y + 6, 30, 30)
    y += 44
    t = obj["t"]
    if t in (T_TELEPORT_ORB, T_CAMERA_TRIGGER, T_BG_TRIGGER, T_MOVE_TRIGGER, T_COLOR_TRIGGER, T_MODE_DUAL):
        rects["param_prev"] = pygame.Rect(PANEL_X + 70, y + 6, 30, 30)
        rects["param_next"] = pygame.Rect(PANEL_X + 170, y + 6, 30, 30)
        y += 44
    if t == T_TELEPORT_ORB:
        rects["dest_toggle"] = pygame.Rect(PANEL_X + 20, y + 4, PANEL_W - 40, 30)
        y += 38
    if t == T_MOVE_TRIGGER:
        rects["curve"] = pygame.Rect(PANEL_X + 15, y + 14, PANEL_W - 30, CURVE_H)
        y += CURVE_H + 34
    rects["delete"] = pygame.Rect(PANEL_X + 20, y + 4, PANEL_W - 40, 34)
    y += 42
    rects["close"] = pygame.Rect(PANEL_X + 20, y, PANEL_W - 40, 30)
    y += 38
    panel_h = y - PANEL_Y
    return rects, panel_h


def _move_in_stack(objects, obj, delta):
    if obj not in objects:
        return
    stack_positions = [i for i, o in enumerate(objects)
                       if o["x"] == obj["x"] and o["y"] == obj["y"]]
    global_idx = objects.index(obj)
    curr_pos = stack_positions.index(global_idx)
    new_pos = curr_pos + delta
    if not (0 <= new_pos < len(stack_positions)):
        return
    swap_global = stack_positions[new_pos]
    objects[global_idx], objects[swap_global] = objects[swap_global], objects[global_idx]


def _param_info(obj):
    t = obj["t"]
    if t == T_TELEPORT_ORB:
        return "Group ID", str(get_group_id(obj))
    if t == T_CAMERA_TRIGGER:
        return "Target Row", str(obj.get("cy", obj["y"]))
    if t == T_BG_TRIGGER:
        return "BG Preset", f"{obj.get('bg', 0)}/{len(BG_PRESETS) - 1}"
    if t == T_COLOR_TRIGGER:
        return "Color Index", str(obj.get("col_idx", 0))
    if t == T_MOVE_TRIGGER:
        return "Duration", f"{obj.get('duration', 30)}f"
    if t == T_MODE_DUAL:
        return "Spawn Row", str(obj.get("spawn_y", obj["y"]))
    return None, None


def _adjust_param(obj, delta):
    t = obj["t"]
    if t == T_TELEPORT_ORB:
        obj["group_id"] = max(1, get_group_id(obj) + delta)
        # Drop the legacy field so the new value is the source of truth.
        obj.pop("link", None)
    elif t == T_CAMERA_TRIGGER:
        obj["cy"] = obj.get("cy", obj["y"]) + delta
    elif t == T_BG_TRIGGER:
        obj["bg"] = (obj.get("bg", 0) + delta) % len(BG_PRESETS)
    elif t == T_COLOR_TRIGGER:
        obj["col_idx"] = max(0, obj.get("col_idx", 0) + delta)
    elif t == T_MOVE_TRIGGER:
        obj["duration"] = max(1, min(600, obj.get("duration", 30) + delta * 5))
    elif t == T_MODE_DUAL:
        obj["spawn_y"] = obj.get("spawn_y", obj["y"]) + delta


def _draw_edit_panel(screen, obj, mpos, pulse, stack_info=(0, 1)):
    stack_idx, stack_len = stack_info
    has_stack = stack_len > 1
    rects, panel_h = _panel_button_rects(obj, stack_len)
    panel_rect = pygame.Rect(PANEL_X, PANEL_Y, PANEL_W, panel_h)
    pygame.draw.rect(screen, (18, 14, 36), panel_rect, border_radius=8)
    pygame.draw.rect(screen, (70, 90, 170), panel_rect, 2, border_radius=8)
    txt(screen, "EDIT OBJECT", PANEL_X + PANEL_W // 2, PANEL_Y + 18, 18, C_WHITE, True)
    pv = pygame.Rect(PANEL_X + PANEL_W // 2 - 32, PANEL_Y + 36, 64, 64)
    pygame.draw.rect(screen, (10, 8, 24), pv, border_radius=6)
    meta = obj if obj["t"] in (T_TELEPORT_ORB, T_CAMERA_TRIGGER, T_BG_TRIGGER, T_MOVE_TRIGGER, T_COLOR_TRIGGER) else None
    draw_obj(screen, obj["t"], pv.x + 8, pv.y + 8, 48, pulse, obj.get("r", 0), meta)
    type_name = TYPE_NAMES.get(obj["t"], obj["t"])
    txt(screen, type_name, PANEL_X + PANEL_W // 2, PANEL_Y + 112, 16, C_WHITE, True)
    txt(screen, f"Pos ({obj['x']}, {obj['y']})",
        PANEL_X + PANEL_W // 2, PANEL_Y + 135, 14, C_GRAY, True)
    if has_stack:
        sp = rects["stack_prev"]
        txt(screen, f"Stack {stack_idx + 1}/{stack_len}",
            PANEL_X + PANEL_W // 2, sp.centery, 14, C_WHITE, True)
        for key, label in [("stack_prev", "<"), ("stack_next", ">")]:
            r = rects[key]
            c = lighter(C_BTN, 30) if r.collidepoint(mpos) else C_BTN
            pygame.draw.rect(screen, c, r, border_radius=4)
            txt(screen, label, r.centerx, r.centery, 16, C_WHITE, True)
        su = rects["stack_up"]
        txt(screen, "Order (back/front)",
            PANEL_X + PANEL_W // 2, su.centery, 12, C_GRAY, True)
        for key, label in [("stack_up", "B"), ("stack_down", "F")]:
            r = rects[key]
            c = lighter(C_BTN, 30) if r.collidepoint(mpos) else C_BTN
            pygame.draw.rect(screen, c, r, border_radius=4)
            txt(screen, label, r.centerx, r.centery, 14, C_WHITE, True)
    rp = rects["rot_prev"]
    txt(screen, "Rotation", PANEL_X + 20, rp.y - 16, 14, C_GRAY)
    for key, label in [("rot_prev", "<"), ("rot_next", ">")]:
        r = rects[key]
        c = lighter(C_BTN, 30) if r.collidepoint(mpos) else C_BTN
        pygame.draw.rect(screen, c, r, border_radius=4)
        txt(screen, label, r.centerx, r.centery, 18, C_WHITE, True)
    txt(screen, f"{obj.get('r', 0)}°",
        PANEL_X + PANEL_W // 2, rp.centery, 16, C_WHITE, True)
    param_label, param_value = _param_info(obj)
    if "param_prev" in rects and param_label is not None:
        pp = rects["param_prev"]
        txt(screen, param_label, PANEL_X + 20, pp.y - 16, 14, C_GRAY)
        for key, label in [("param_prev", "<"), ("param_next", ">")]:
            r = rects[key]
            c = lighter(C_BTN, 30) if r.collidepoint(mpos) else C_BTN
            pygame.draw.rect(screen, c, r, border_radius=4)
            txt(screen, label, r.centerx, r.centery, 18, C_WHITE, True)
        txt(screen, param_value,
            PANEL_X + PANEL_W // 2, pp.centery, 16, C_WHITE, True)
    if "dest_toggle" in rects:
        dr = rects["dest_toggle"]
        is_dest = bool(obj.get("dest"))
        base = (60, 140, 80) if is_dest else (50, 50, 70)
        c = lighter(base, 30) if dr.collidepoint(mpos) else base
        pygame.draw.rect(screen, c, dr, border_radius=5)
        label = "Destination: ON" if is_dest else "Destination: OFF"
        txt(screen, label, dr.centerx, dr.centery, 13, C_WHITE, True)
    if obj["t"] == T_MOVE_TRIGGER and "curve" in rects:
        cr = rects["curve"]
        txt(screen, "Speed curve (click=add, drag=move, R-click=del)",
            cr.centerx, cr.y - 10, 10, C_GRAY, True)
        pygame.draw.rect(screen, (10, 8, 22), cr, border_radius=4)
        pygame.draw.rect(screen, (70, 90, 160), cr, 1, border_radius=4)
        inner_x0 = cr.x + CURVE_PAD
        inner_y0 = cr.y + CURVE_PAD
        inner_x1 = cr.right - CURVE_PAD
        inner_y1 = cr.bottom - CURVE_PAD
        inner_h = inner_y1 - inner_y0
        for i in range(1, 4):
            ly = inner_y0 + inner_h * i / 4
            pygame.draw.line(screen, (30, 32, 60), (inner_x0, ly), (inner_x1, ly), 1)
        for i in range(1, 4):
            lx = inner_x0 + (inner_x1 - inner_x0) * i / 4
            pygame.draw.line(screen, (30, 32, 60), (lx, inner_y0), (lx, inner_y1), 1)
        y_one = inner_y0 + (1.0 - 1.0 / MOVE_CURVE_SPEED_MAX) * inner_h
        pygame.draw.line(screen, (70, 80, 130), (inner_x0, y_one), (inner_x1, y_one), 1)
        txt(screen, f"{MOVE_CURVE_SPEED_MAX:.0f}x", cr.x + 2, inner_y0 - 2, 9, C_GRAY)
        txt(screen, "0", cr.x + 4, inner_y1 - 10, 9, C_GRAY)
        txt(screen, "t=0", inner_x0, cr.bottom - 8, 9, C_GRAY)
        txt(screen, "t=1", inner_x1 - 12, cr.bottom - 8, 9, C_GRAY)
        curve = _ensure_curve(obj)
        sorted_pts = sorted(curve, key=lambda p: p[0])
        screen_pts = [_curve_point_to_px(cr, p[0], p[1]) for p in sorted_pts]
        if len(screen_pts) >= 2:
            fill_pts = [(screen_pts[0][0], inner_y1)] + screen_pts + [(screen_pts[-1][0], inner_y1)]
            fill_surf = pygame.Surface((cr.w, cr.h), pygame.SRCALPHA)
            offset = [(p[0] - cr.x, p[1] - cr.y) for p in fill_pts]
            pygame.draw.polygon(fill_surf, (255, 180, 80, 45), offset)
            screen.blit(fill_surf, cr.topleft)
            pygame.draw.lines(screen, (255, 200, 100), False, screen_pts, 2)
        for i, sp in enumerate(screen_pts):
            is_end = (i == 0 or i == len(screen_pts) - 1)
            col = (255, 230, 160) if is_end else (255, 200, 100)
            pygame.draw.circle(screen, (10, 6, 22), sp, 6)
            pygame.draw.circle(screen, col, sp, 4)
        tx_, ty_ = obj.get("tx", obj["x"]), obj.get("ty", obj["y"])
        oids = obj.get("target_oids", [])
        oid = obj.get("target_oid", 0)
        info_y = rects["delete"].y - 14
        if oids:
            label = f"→({tx_},{ty_}) {len(oids)} obj(s)"
        elif oid:
            label = f"→({tx_},{ty_}) oid={oid}"
        else:
            label = "(use Group tool)"
        txt(screen, label, PANEL_X + PANEL_W // 2, info_y, 12, C_GRAY, True)
    r = rects["delete"]
    c = lighter(C_DANGER, 30) if r.collidepoint(mpos) else C_DANGER
    pygame.draw.rect(screen, c, r, border_radius=6)
    txt(screen, "Delete [Del]", r.centerx, r.centery, 15, C_WHITE, True)
    r = rects["close"]
    c = (70, 70, 90) if r.collidepoint(mpos) else (50, 50, 70)
    pygame.draw.rect(screen, c, r, border_radius=6)
    txt(screen, "Close", r.centerx, r.centery, 14, C_WHITE, True)
    return panel_rect, rects


def _draw_palette(screen, mpos, active_cat, selected_type, tool, pulse,
                  tab_rects, item_rects, tool_rects):
    pygame.draw.rect(screen, (18, 16, 38), (0, 0, WIDTH, TOP_H))
    # Palette body (below tabs)
    pygame.draw.rect(screen, (24, 22, 46), (0, TAB_H, WIDTH, PAL_H))
    pygame.draw.line(screen, C_GRID, (0, TOP_H), (WIDTH, TOP_H), 1)
    for i, r in enumerate(tab_rects):
        name = PALETTE_CATEGORIES[i][0]
        hovered = r.collidepoint(mpos)
        active = i == active_cat
        if active:
            col = (60, 100, 210)
            body = pygame.Rect(r.x, r.y, r.w, r.h + 4)  # merge with palette body
            pygame.draw.rect(screen, col, body,
                             border_top_left_radius=8, border_top_right_radius=8)
            pygame.draw.rect(screen, lighter(col, 60), r,
                             1, border_top_left_radius=8, border_top_right_radius=8)
        else:
            col = (40, 60, 140) if hovered else (28, 32, 70)
            pygame.draw.rect(screen, col, r,
                             border_top_left_radius=8, border_top_right_radius=8)
            pygame.draw.rect(screen, lighter(col, 40), r,
                             1, border_top_left_radius=8, border_top_right_radius=8)
        txt(screen, name, r.centerx, r.centery, 14, C_WHITE, True)
    hovered_item_type = None
    for i, (r, t) in enumerate(item_rects):
        if tool == TOOL_BRUSH and selected_type == t:
            pygame.draw.rect(screen, (48, 38, 90), r, border_radius=6)
            pygame.draw.rect(screen, C_WHITE, r, 2, border_radius=6)
        elif r.collidepoint(mpos):
            pygame.draw.rect(screen, (30, 34, 70), r, border_radius=6)
            pygame.draw.rect(screen, (80, 90, 150), r, 2, border_radius=6)
            hovered_item_type = t
        draw_obj(screen, t, r.x + 2, r.y + 2, 48, pulse, 0)
        if i < 9:
            txt(screen, str(i + 1), r.right - 10, r.bottom - 12, 11, C_GRAY)
    labels = {TOOL_BRUSH: ("Brush [B]", C_BTN),
              TOOL_ERASE: ("Erase [E]", C_DANGER),
              TOOL_GROUP: ("Group [N]", (120, 80, 190)),
              TOOL_EDIT: ("Edit [I]", (80, 160, 90)),
              TOOL_BOT_PATH: ("Bot", (255, 180, 60))}
    for tid, r in tool_rects.items():
        label, col = labels[tid]
        active = tool == tid
        c = lighter(col, 30) if active else col
        pygame.draw.rect(screen, darker(c, 50), r.move(0, 2), border_radius=6)
        pygame.draw.rect(screen, c, r, border_radius=6)
        if active:
            pygame.draw.rect(screen, C_WHITE, r, 2, border_radius=6)
        txt(screen, label, r.centerx, r.centery, 13, C_WHITE, True)
    return hovered_item_type


def run_editor(screen, clock, preload_filename=None):
    # The editor is a "quiet" screen — menu music doesn't belong here and
    # playtest / bot replay restart music on their own. Stop on entry so
    # the menu track doesn't keep looping under the editor UI.
    music.stop()
    objects = _initial_objects()
    level_name = "Untitled"
    level_music = None  # filename of assigned music track
    level_filename = None  # last-saved filename (without path); used by Publish
    level_meta = None     # last-loaded meta dict (preserve published/verified)
    # ---- Autosave recovery ------------------------------------------------
    # Preload path: if the caller passed a specific filename (from the
    # editor picker) skip autosave recovery and load that level instead.
    if preload_filename:
        try:
            from levels import load_level_full, LEVELS_DIR
            _pre_path = os.path.join(LEVELS_DIR, preload_filename)
            pl_meta, pl_objs = load_level_full(_pre_path)
            objects = pl_objs
            level_name = pl_meta.get("name", "Untitled")
            level_music = pl_meta.get("music")
            level_filename = preload_filename
            level_meta = pl_meta
        except (OSError, ValueError):
            pass

    # If a previous editor session left a snapshot, offer to restore it before
    # the user starts editing. Declining (or any error) clears the snapshot so
    # the prompt doesn't reappear on every entry.
    recovered = False
    if not preload_filename and has_autosave():
        try:
            ameta, aobjs = load_autosave()
        except Exception:
            ameta, aobjs = None, None
        if ameta and aobjs is not None:
            src = ameta.get("_autosave_source") or "(never saved)"
            ts = ameta.get("_autosave_ts", 0)
            try:
                import time as _time
                age = max(0, int(_time.time()) - int(ts)) if ts else None
            except Exception:
                age = None
            if age is None:
                age_str = ""
            elif age < 60:
                age_str = f"{age}s ago"
            elif age < 3600:
                age_str = f"{age // 60}m ago"
            else:
                age_str = f"{age // 3600}h ago"
            subtitle = f'"{ameta.get("name", "Untitled")}" · slot {src} · {age_str}'.strip(" ·")
            recover = confirm_dialog(
                screen, clock,
                "Recover unsaved editor work?",
                subtitle=subtitle,
                ok_label="Recover", cancel_label="Discard",
            )
            if recover:
                objects = aobjs
                level_name = ameta.get("name", "Untitled")
                level_music = ameta.get("music")
                src = ameta.get("_autosave_source") or ""
                level_filename = src or None
                # Strip the autosave-private fields from the meta so a later
                # Save doesn't carry them through into the real level file.
                clean_meta = {k: v for k, v in ameta.items()
                              if not k.startswith("_autosave_")}
                level_meta = clean_meta
                recovered = True
            # Either way (recover or discard) the snapshot was consumed.
            clear_autosave()
    cam_x, cam_y = 0.0, 0.0
    show_grid = True
    pulse = 0
    msg, msg_timer = "", 0
    stars = make_stars()
    mountains = make_mountains()
    active_cat = 0
    selected_type = PALETTE_CATEGORIES[0][1][0]
    tool = TOOL_BRUSH
    current_rotation = 0
    pending_link = None
    current_group_id = 1
    selected_objs = []
    last_edit_cell = None
    curve_drag_idx = None
    drag_mode = None
    drag_anchor_cell = (0, 0)
    drag_positions = {}
    drag_start_screen = (0, 0)
    drag_rubber_shift = False
    drag_moved = False
    r_save = make_rect(70, BAR_Y + 27, 84, 38)
    r_publish = make_rect(158, BAR_Y + 27, 84, 38)
    r_load = make_rect(246, BAR_Y + 27, 84, 38)
    r_test = make_rect(334, BAR_Y + 27, 84, 38)
    r_bot = make_rect(422, BAR_Y + 27, 84, 38)
    r_clear = make_rect(510, BAR_Y + 27, 70, 38)
    r_music = make_rect(590, BAR_Y + 27, 84, 38)
    r_menu = make_rect(678, BAR_Y + 27, 84, 38)
    r_mute_music = pygame.Rect(750, BAR_Y + 8, 36, 36)
    r_mute_sfx = pygame.Rect(790, BAR_Y + 8, 36, 36)

    # Undo/Redo system
    undo_stack = []
    redo_stack = []

    # Copy/Paste system
    clipboard = []

    # Zoom system
    zoom_level = 1.0
    # Middle-click / Space+drag panning state. Tracks the mouse/camera
    # origin at drag start so motion deltas apply linearly.
    _pan_dragging = False
    _pan_anchor = (0, 0)
    _pan_cam_start = (0.0, 0.0)

    def _apply_zoom_anchor(old_zoom, new_zoom, anchor=None):
        """Keep the world point under ``anchor`` fixed across a zoom change.

        Called after `zoom_level` is mutated — re-solves cam_x/cam_y so
        the cell previously beneath ``anchor`` (screen pixel coords; defaults
        to the canvas centre) lands at the same screen pixel post-zoom.
        Without this, zoom feels glitchy because the view pivots around
        world origin instead of the user's focal point.
        """
        nonlocal cam_x, cam_y
        if anchor is None:
            anchor = (WIDTH // 2, (TOP_H + BAR_Y) // 2)
        eff_old = int(CELL * old_zoom)
        eff_new = int(CELL * new_zoom)
        if eff_old <= 0 or eff_new <= 0:
            return
        ax, ay = anchor
        world_x = (ax + cam_x) / eff_old
        world_y = (ay + cam_y) / eff_old
        cam_x = world_x * eff_new - ax
        cam_y = world_y * eff_new - ay

    # Autosave: True whenever objects have changed since the last save (or
    # autosave). The timer counts frames between disk writes; the toast frames
    # control the brief "Auto-saved" indicator on the HUD. A freshly-recovered
    # session starts dirty so the in-memory state gets re-snapshotted promptly.
    dirty = bool(recovered)
    autosave_timer = 0
    autosave_toast_frames = 0
    last_autosave_secs = None  # wall-clock time of last autosave

    def push_undo():
        """Push current state to undo stack and mark the level as dirty.

        Wraps the module-level `_push_undo` so every undo-eligible mutation
        also flips the dirty flag for the autosave subsystem. (Drag operations
        that don't push undo set dirty inline below.)
        """
        nonlocal dirty
        _push_undo(undo_stack, redo_stack, objects)
        dirty = True

    def autosave_now():
        """Write the current editor state to the autosave slot (best-effort)."""
        nonlocal dirty, autosave_toast_frames, last_autosave_secs
        try:
            save_autosave(objects, level_name,
                          music_file=level_music,
                          meta=level_meta,
                          source_filename=level_filename or "")
        except OSError:
            return False
        dirty = False
        autosave_toast_frames = AUTOSAVE_FLASH_FRAMES
        try:
            import time as _time
            last_autosave_secs = _time.time()
        except Exception:
            last_autosave_secs = None
        return True

    # Bot path system
    bot_waypoints = []
    bot_mirror_waypoints = []  # parallel path for the dual mirror (blue line)
    bot_exact_inputs = None  # exact (held, pressed) per frame from autobot

    # Snippet "stamp": when set to a list of objects, the next click on the
    # canvas drops a fresh-id clone of those objects anchored at the cursor.
    # Esc clears the stamp without dropping anything.
    snippet_stamp = None      # [object_dict, ...] in snippet-local coords
    snippet_stamp_name = ""   # for the HUD hint

    # Hitbox playback: every Test / Bot / Replay run fills `last_run_hitboxes`
    # with the player's per-frame (x, y, size). When `show_hitboxes` is True
    # the editor overlays each recorded rect on the canvas — useful for
    # debugging tight saw / spike sequences after a death. Toggled with H.
    last_run_hitboxes = []
    show_hitboxes = False

    # Keyboard cheat-sheet overlay — press `?` or F1 in the editor to see
    # every shortcut in one place, instead of squinting at the bottom
    # hint strip. Dismissed with the same key or Escape.
    show_shortcuts = False

    def screen_to_cell(mx, my):
        effective_cell = int(CELL * zoom_level)
        return int((mx + cam_x) // effective_cell), int((my + cam_y) // effective_cell)

    # Click-through guard: ignore mouse state until the user releases the
    # entry click and presses again. Reset on every transition into / out of
    # a sub-screen (load dialog, test play, autobot) so the click that
    # closed the sub-screen never leaks into the editor.
    guard = ClickGuard()

    while True:
        guard.tick()
        pulse += 1
        mpos = pygame.mouse.get_pos()
        mx, my = mpos
        in_canvas = TOP_H < my < BAR_Y
        do_save = do_load = do_test = do_bot = do_publish = False
        # Shift+T sets this alongside do_test — caller uses it to pass
        # start_x to run_play so the playtest spawns at the cursor.
        do_test_from_cursor = False
        do_bot_menu = False
        tab_rects, item_rects, tool_rects = _palette_rects(active_cat)
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit()
                raise SystemExit
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    # If a snippet stamp is active, Esc cancels the stamp
                    # rather than exiting the editor — matches the rubber-band
                    # cancel pattern users expect.
                    if snippet_stamp is not None:
                        snippet_stamp = None
                        snippet_stamp_name = ""
                        msg, msg_timer = "Snippet cancelled", 60
                        continue
                    # Flush a fresh autosave on the way out so unsaved work
                    # is offered for recovery the next time the editor opens.
                    if dirty:
                        autosave_now()
                    music.stop()
                    return
                if ev.key in (pygame.K_F1, pygame.K_QUESTION, pygame.K_SLASH):
                    # `/` without a modifier usually yields K_SLASH; with
                    # shift it yields K_QUESTION on US layouts. Accept
                    # either so the help is discoverable.
                    show_shortcuts = not show_shortcuts
                    continue
                if show_shortcuts:
                    # Any other key dismisses the cheat sheet so the
                    # editor remains responsive.
                    show_shortcuts = False
                    continue
                if ev.key == pygame.K_g:
                    show_grid = not show_grid
                elif ev.key == pygame.K_h:
                    # Hitbox overlay: shows the player's recorded rects from
                    # the most recent test/bot run. Off by default so the
                    # canvas stays clean during normal editing.
                    show_hitboxes = not show_hitboxes
                    if show_hitboxes and not last_run_hitboxes:
                        msg, msg_timer = (
                            "Hitbox view ON — run Test or Bot to record"
                        ), 120
                    else:
                        msg, msg_timer = (
                            f"Hitbox view {'ON' if show_hitboxes else 'OFF'}"
                            + (f" ({len(last_run_hitboxes)} frames)"
                               if show_hitboxes and last_run_hitboxes else "")
                        ), 90
                elif ev.key == pygame.K_m:
                    music.toggle_mute()
                    msg, msg_timer = (
                        "Music: OFF" if music.is_muted() else "Music: ON"
                    ), 80
                elif ev.key == pygame.K_b:
                    tool = TOOL_BRUSH
                elif ev.key == pygame.K_e:
                    tool = TOOL_ERASE
                elif ev.key == pygame.K_k:
                    do_bot = True
                elif ev.key == pygame.K_n:
                    tool = TOOL_GROUP
                    pending_link = None
                elif ev.key in (pygame.K_RETURN, pygame.K_SPACE) and pending_link:
                    pending_link, m = _link_confirm_targets(pending_link)
                    if m:
                        msg, msg_timer = m, 110
                elif ev.key == pygame.K_i:
                    tool = TOOL_EDIT
                elif ev.key in (pygame.K_DELETE, pygame.K_BACKSPACE) and selected_objs:
                    push_undo()
                    n = len(selected_objs)
                    for o in list(selected_objs):
                        if o in objects:
                            objects.remove(o)
                    selected_objs = []
                    last_edit_cell = None
                    msg, msg_timer = f"Deleted {n} object{'s' if n != 1 else ''}", 80
                elif ev.key == pygame.K_z and pygame.key.get_mods() & pygame.KMOD_CTRL:
                    # Undo: Ctrl+Z
                    if undo_stack:
                        redo_stack.append([dict(o) for o in objects])
                        objects[:] = [dict(o) for o in undo_stack.pop()]
                        selected_objs = []
                        last_edit_cell = None
                        msg, msg_timer = "Undo", 70
                elif ev.key == pygame.K_y and pygame.key.get_mods() & pygame.KMOD_CTRL:
                    # Redo: Ctrl+Y
                    if redo_stack:
                        undo_stack.append([dict(o) for o in objects])
                        objects[:] = [dict(o) for o in redo_stack.pop()]
                        selected_objs = []
                        last_edit_cell = None
                        msg, msg_timer = "Redo", 70
                elif ev.key == pygame.K_c and pygame.key.get_mods() & pygame.KMOD_CTRL and selected_objs:
                    # Copy: Ctrl+C
                    if selected_objs:
                        first = selected_objs[0]
                        clipboard = []
                        for o in selected_objs:
                            copy_obj = dict(o)
                            copy_obj["_offset_x"] = o["x"] - first["x"]
                            copy_obj["_offset_y"] = o["y"] - first["y"]
                            clipboard.append(copy_obj)
                        msg, msg_timer = f"Copied {len(clipboard)} object{'s' if len(clipboard) != 1 else ''}", 80
                elif ev.key == pygame.K_d and pygame.key.get_mods() & pygame.KMOD_CTRL and selected_objs:
                    # Duplicate in place (stack): Ctrl+D
                    push_undo()
                    first = selected_objs[0]
                    new_objs = _clone_objects(selected_objs,
                                              (first["x"], first["y"]), objects)
                    objects.extend(new_objs)
                    selected_objs = new_objs
                    msg, msg_timer = f"Duplicated {len(new_objs)} object{'s' if len(new_objs) != 1 else ''} in place", 90
                elif ev.key in (pygame.K_RIGHT, pygame.K_LEFT, pygame.K_UP, pygame.K_DOWN) and (
                        pygame.key.get_mods() & pygame.KMOD_SHIFT) and (
                        pygame.key.get_mods() & pygame.KMOD_CTRL) and selected_objs:
                    # Stack copies: Ctrl+Shift+Arrow
                    push_undo()
                    dx = 1 if ev.key == pygame.K_RIGHT else (-1 if ev.key == pygame.K_LEFT else 0)
                    dy = -1 if ev.key == pygame.K_UP else (1 if ev.key == pygame.K_DOWN else 0)
                    first = selected_objs[0]
                    new_objs = _clone_objects(selected_objs,
                                              (first["x"] + dx, first["y"] + dy),
                                              objects)
                    objects.extend(new_objs)
                    selected_objs = new_objs
                    msg, msg_timer = f"Stacked {len(new_objs)} → ({'+' if dx >= 0 else ''}{dx},{'+' if dy >= 0 else ''}{dy})", 80
                elif ev.key == pygame.K_v and pygame.key.get_mods() & pygame.KMOD_CTRL and clipboard:
                    # Paste: Ctrl+V
                    if clipboard and in_canvas:
                        push_undo()
                        gx, gy = screen_to_cell(mx, my)
                        new_objs = _clone_objects(clipboard, (gx, gy), objects)
                        objects.extend(new_objs)
                        # Select the pastes so the user can immediately move
                        # them, rotate, or paste again with the same offset.
                        selected_objs = new_objs
                        last_edit_cell = None
                        msg, msg_timer = (
                            f"Pasted {len(new_objs)} object"
                            f"{'s' if len(new_objs) != 1 else ''}"
                        ), 80
                elif ev.key == pygame.K_x and pygame.key.get_mods() & pygame.KMOD_CTRL and selected_objs:
                    # Cut: Ctrl+X — copy selection then delete
                    first = selected_objs[0]
                    clipboard = []
                    for o in selected_objs:
                        cb_obj = dict(o)
                        cb_obj["_offset_x"] = o["x"] - first["x"]
                        cb_obj["_offset_y"] = o["y"] - first["y"]
                        clipboard.append(cb_obj)
                    push_undo()
                    n = len(selected_objs)
                    for o in list(selected_objs):
                        if o in objects:
                            objects.remove(o)
                    selected_objs = []
                    last_edit_cell = None
                    msg, msg_timer = f"Cut {n} object{'s' if n != 1 else ''}", 80
                elif ev.key == pygame.K_e and pygame.key.get_mods() & pygame.KMOD_CTRL:
                    # Ctrl+E — export the whole level as a single PNG
                    # under `{user_data}/exports/`. Renders each object
                    # at a small fixed cell size (configurable inline).
                    out_path = _export_level_png(objects, level_name)
                    if out_path:
                        msg, msg_timer = f"Exported: {out_path}", 240
                    else:
                        msg, msg_timer = "Export failed", 180
                elif ev.key == pygame.K_a and pygame.key.get_mods() & pygame.KMOD_CTRL:
                    # Select all: Ctrl+A — pick everything except the start marker
                    selected_objs = [o for o in objects if o.get("t") != T_START]
                    last_edit_cell = None
                    if selected_objs:
                        tool = TOOL_EDIT
                        msg, msg_timer = f"Selected all ({len(selected_objs)})", 80
                    else:
                        msg, msg_timer = "Nothing to select", 60
                elif ev.key == pygame.K_EQUALS and pygame.key.get_mods() & pygame.KMOD_CTRL:
                    # Zoom in: Ctrl+= (anchored at screen center)
                    old_zoom = zoom_level
                    zoom_level = min(3.0, round(zoom_level + 0.2, 2))
                    _apply_zoom_anchor(old_zoom, zoom_level)
                    msg, msg_timer = f"Zoom: {zoom_level:.1f}x", 60
                elif ev.key == pygame.K_MINUS and pygame.key.get_mods() & pygame.KMOD_CTRL:
                    # Zoom out: Ctrl+-
                    old_zoom = zoom_level
                    zoom_level = max(0.3, round(zoom_level - 0.2, 2))
                    _apply_zoom_anchor(old_zoom, zoom_level)
                    msg, msg_timer = f"Zoom: {zoom_level:.1f}x", 60
                elif ev.key == pygame.K_0 and pygame.key.get_mods() & pygame.KMOD_CTRL:
                    # Reset zoom: Ctrl+0
                    old_zoom = zoom_level
                    zoom_level = 1.0
                    _apply_zoom_anchor(old_zoom, zoom_level)
                    msg, msg_timer = "Zoom: 1.0x (reset)", 60
                elif ev.key == pygame.K_s:
                    mods = pygame.key.get_mods()
                    if (mods & pygame.KMOD_CTRL) and (mods & pygame.KMOD_SHIFT):
                        # Ctrl+Shift+S: save current selection as a user snippet
                        if selected_objs:
                            sn_name = text_input_dialog(
                                screen, clock, "Snippet name:", "My Snippet")
                            guard.reset()
                            if sn_name:
                                snip_objs = normalize_to_origin(selected_objs)
                                save_user_snippet(sn_name, snip_objs)
                                msg, msg_timer = (
                                    f"Saved snippet '{sn_name}' "
                                    f"({len(snip_objs)} obj)"
                                ), 150
                        else:
                            msg, msg_timer = (
                                "Select objects first to save as a snippet"
                            ), 120
                    else:
                        do_save = True
                elif ev.key == pygame.K_l:
                    if pygame.key.get_mods() & pygame.KMOD_CTRL:
                        do_load = True
                    else:
                        # Open the bot menu instead of jumping straight into
                        # the solver — gives the user knobs (beam width, max
                        # frames) and a Replay button. Old direct-solve flow
                        # is still reachable as the menu's "Find Path" action.
                        do_bot_menu = True
                elif ev.key == pygame.K_o and pygame.key.get_mods() & pygame.KMOD_CTRL:
                    do_load = True
                elif ev.key == pygame.K_t:
                    do_test = True
                    # Shift+T = test starting from the current cursor's
                    # world x (music seeks to match), so authors can
                    # iterate on a late section without replaying from
                    # the start.
                    if pygame.key.get_mods() & pygame.KMOD_SHIFT:
                        do_test_from_cursor = True
                elif ev.key == pygame.K_F2:
                    # Open the snippet palette → returned snippet becomes the
                    # cursor stamp; the next canvas click drops it.
                    pick = snippet_picker(screen, clock)
                    guard.reset()
                    if pick is not None:
                        sname, sobjs, _is_user = pick
                        snippet_stamp = list(sobjs)
                        snippet_stamp_name = sname
                        msg, msg_timer = (
                            f"Stamp: {sname} — click to place, Esc to cancel"
                        ), 180
                elif ev.key == pygame.K_F5:
                    # Cycle through music tracks for this level (assign only, no playback in editor)
                    track_names = music.get_track_names()  # ["None", "Track A", ...]
                    tracks = music.get_tracks()
                    if level_music is None:
                        cur_idx = 0
                    else:
                        cur_idx = 0
                        for ti, t in enumerate(tracks):
                            if t.get("file") == level_music:
                                cur_idx = ti + 1
                                break
                    cur_idx = (cur_idx + 1) % len(track_names)
                    if cur_idx == 0:
                        level_music = None
                        msg, msg_timer = "Music: None", 90
                    else:
                        level_music = tracks[cur_idx - 1].get("file")
                        msg, msg_timer = f"Music: {track_names[cur_idx]}", 90
                    dirty = True
                elif ev.key == pygame.K_TAB:
                    active_cat = (active_cat + 1) % len(PALETTE_CATEGORIES)
                    selected_type = PALETTE_CATEGORIES[active_cat][1][0]
                elif ev.key in (pygame.K_r, pygame.K_q):
                    delta = 90 if ev.key == pygame.K_r else -90
                    if selected_objs:
                        push_undo()
                        for o in selected_objs:
                            o["r"] = normalize_rotation(o.get("r", 0) + delta)
                        if len(selected_objs) == 1:
                            msg, msg_timer = f"Rotated to {selected_objs[0]['r']}°", 70
                        else:
                            msg, msg_timer = f"Rotated {len(selected_objs)} objects", 70
                    elif in_canvas:
                        gx, gy = screen_to_cell(mx, my)
                        target = object_at_cell(objects, gx, gy)
                        if target:
                            push_undo()
                            target["r"] = normalize_rotation(target.get("r", 0) + delta)
                            msg, msg_timer = f"Rotated to {target['r']}°", 70
                        else:
                            current_rotation = normalize_rotation(current_rotation + delta)
                            msg, msg_timer = f"Rotation: {current_rotation}°", 70
                    else:
                        current_rotation = normalize_rotation(current_rotation + delta)
                        msg, msg_timer = f"Rotation: {current_rotation}°", 70
                else:
                    items = PALETTE_CATEGORIES[active_cat][1]
                    for i in range(min(len(items), 9)):
                        if ev.key == pygame.K_1 + i:
                            selected_type = items[i]
                            tool = TOOL_BRUSH
            if ev.type == pygame.MOUSEWHEEL:
                if my < TOP_H or my > BAR_Y:
                    current_rotation = normalize_rotation(current_rotation + (90 if ev.y > 0 else -90))
                    msg, msg_timer = f"Rotation: {current_rotation}°", 60
                else:
                    # Wheel over the canvas → zoom, anchored at the mouse
                    # cursor so the cell under the cursor stays put. Without
                    # anchoring, zoom jumps content around and feels glitchy.
                    old_zoom = zoom_level
                    step = 0.1 if (pygame.key.get_mods() & pygame.KMOD_SHIFT) else 0.2
                    if ev.y > 0:
                        zoom_level = min(3.0, round(zoom_level + step, 2))
                    elif ev.y < 0:
                        zoom_level = max(0.3, round(zoom_level - step, 2))
                    if zoom_level != old_zoom:
                        _apply_zoom_anchor(old_zoom, zoom_level, anchor=(mx, my))
                        msg, msg_timer = f"Zoom: {zoom_level:.1f}x", 40
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 2:
                # Middle-click: begin canvas pan (matches the cheat-sheet
                # promise of "Middle click drag: Pan canvas").
                if TOP_H <= ev.pos[1] <= BAR_Y:
                    _pan_dragging = True
                    _pan_anchor = ev.pos
                    _pan_cam_start = (cam_x, cam_y)
            if ev.type == pygame.MOUSEBUTTONUP and ev.button == 2:
                _pan_dragging = False
            if ev.type == pygame.MOUSEMOTION and _pan_dragging:
                dx = ev.pos[0] - _pan_anchor[0]
                dy = ev.pos[1] - _pan_anchor[1]
                cam_x = _pan_cam_start[0] - dx
                cam_y = _pan_cam_start[1] - dy
            if ev.type == pygame.MOUSEBUTTONDOWN and not guard.consume_click(ev):
                continue
            if ev.type == pygame.MOUSEBUTTONUP and not guard.is_settled():
                continue
            if ev.type == pygame.MOUSEBUTTONDOWN:
                panel_hit = False
                if ev.button == 1 and tool == TOOL_EDIT and len(selected_objs) == 1:
                    active_obj = selected_objs[0]
                    stack_here = objects_at_cell(objects, active_obj["x"], active_obj["y"])
                    stack_len_here = len(stack_here)
                    pbr, panel_h_here = _panel_button_rects(active_obj, stack_len_here)
                    panel_rect = pygame.Rect(PANEL_X, PANEL_Y, PANEL_W, panel_h_here)
                    if panel_rect.collidepoint(ev.pos):
                        panel_hit = True
                        zero_rect = pygame.Rect(0, 0, 0, 0)
                        if pbr["rot_prev"].collidepoint(ev.pos):
                            push_undo()
                            active_obj["r"] = normalize_rotation(active_obj.get("r", 0) - 90)
                        elif pbr["rot_next"].collidepoint(ev.pos):
                            push_undo()
                            active_obj["r"] = normalize_rotation(active_obj.get("r", 0) + 90)
                        elif pbr["delete"].collidepoint(ev.pos):
                            push_undo()
                            if active_obj in objects:
                                objects.remove(active_obj)
                            selected_objs = []
                            last_edit_cell = None
                            msg, msg_timer = "Deleted object", 80
                        elif pbr["close"].collidepoint(ev.pos):
                            selected_objs = []
                            last_edit_cell = None
                        elif pbr.get("param_prev", zero_rect).collidepoint(ev.pos):
                            push_undo()
                            _adjust_param(active_obj, -1)
                        elif pbr.get("param_next", zero_rect).collidepoint(ev.pos):
                            push_undo()
                            _adjust_param(active_obj, 1)
                        elif pbr.get("stack_prev", zero_rect).collidepoint(ev.pos):
                            if active_obj in stack_here:
                                idx = (stack_here.index(active_obj) - 1) % stack_len_here
                                selected_objs = [stack_here[idx]]
                        elif pbr.get("stack_next", zero_rect).collidepoint(ev.pos):
                            if active_obj in stack_here:
                                idx = (stack_here.index(active_obj) + 1) % stack_len_here
                                selected_objs = [stack_here[idx]]
                        elif pbr.get("stack_up", zero_rect).collidepoint(ev.pos):
                            push_undo()
                            _move_in_stack(objects, active_obj, -1)
                            msg, msg_timer = "Moved back in stack", 70
                        elif pbr.get("stack_down", zero_rect).collidepoint(ev.pos):
                            push_undo()
                            _move_in_stack(objects, active_obj, 1)
                            msg, msg_timer = "Moved forward in stack", 70
                        elif pbr.get("dest_toggle", zero_rect).collidepoint(ev.pos):
                            push_undo()
                            active_obj["dest"] = not active_obj.get("dest", False)
                            msg, msg_timer = (
                                "Marked as destination" if active_obj["dest"]
                                else "Cleared destination"), 70
                        elif ("curve" in pbr
                              and pbr["curve"].collidepoint(ev.pos)
                              and active_obj["t"] == T_MOVE_TRIGGER):
                            curve = _ensure_curve(active_obj)
                            cr = pbr["curve"]
                            hit = None
                            for i, p in enumerate(curve):
                                sp = _curve_point_to_px(cr, p[0], p[1])
                                d2 = (sp[0] - ev.pos[0]) ** 2 + (sp[1] - ev.pos[1]) ** 2
                                if d2 <= CURVE_HIT_R2:
                                    hit = i
                                    break
                            if hit is not None:
                                curve_drag_idx = hit
                            else:
                                push_undo()
                                nt, ns = _px_to_curve_point(cr, ev.pos[0], ev.pos[1])
                                insert_at = len(curve)
                                for i, p in enumerate(curve):
                                    if p[0] > nt:
                                        insert_at = i
                                        break
                                if insert_at == 0:
                                    insert_at = 1
                                if insert_at == len(curve):
                                    insert_at = len(curve) - 1
                                curve.insert(insert_at, [nt, ns])
                                curve_drag_idx = insert_at
                if panel_hit:
                    continue
                if ev.button == 1:
                    if my < TAB_H:
                        for i, r in enumerate(tab_rects):
                            if r.collidepoint(ev.pos):
                                active_cat = i
                                selected_type = PALETTE_CATEGORIES[i][1][0]
                                tool = TOOL_BRUSH
                                break
                    elif my < TOP_H:
                        for r, t in item_rects:
                            if r.collidepoint(ev.pos):
                                selected_type = t
                                tool = TOOL_BRUSH
                                if t == T_TELEPORT_ORB:
                                    current_group_id = next_group_id(objects)
                                break
                        for tid, r in tool_rects.items():
                            if r.collidepoint(ev.pos):
                                tool = tid
                                if tid != TOOL_GROUP:
                                    pending_link = None
                    elif my > BAR_Y:
                        if r_save.collidepoint(ev.pos):
                            do_save = True
                        elif r_publish.collidepoint(ev.pos):
                            do_publish = True
                        elif r_load.collidepoint(ev.pos):
                            do_load = True
                        elif r_test.collidepoint(ev.pos):
                            do_test = True
                        elif r_bot.collidepoint(ev.pos):
                            # Bot button now opens the menu (primary entry).
                            # K key still does the direct quick-replay.
                            do_bot_menu = True
                        elif r_mute_music.collidepoint(ev.pos):
                            music.toggle_mute()
                            msg, msg_timer = (
                                "Music: OFF" if music.is_muted() else "Music: ON"
                            ), 80
                        elif r_mute_sfx.collidepoint(ev.pos):
                            sfx.toggle_mute()
                            msg, msg_timer = (
                                "SFX: OFF" if sfx.is_muted() else "SFX: ON"
                            ), 80
                        elif r_clear.collidepoint(ev.pos):
                            push_undo()
                            objects = []
                            pending_link = None
                            msg, msg_timer = "Cleared all objects", 90
                        elif r_music.collidepoint(ev.pos):
                            # Cycle music track (assign only, no playback in editor)
                            track_names = music.get_track_names()
                            tracks = music.get_tracks()
                            if level_music is None:
                                cur_idx = 0
                            else:
                                cur_idx = 0
                                for ti, t in enumerate(tracks):
                                    if t.get("file") == level_music:
                                        cur_idx = ti + 1
                                        break
                            cur_idx = (cur_idx + 1) % len(track_names)
                            if cur_idx == 0:
                                level_music = None
                                msg, msg_timer = "Music: None", 90
                            else:
                                level_music = tracks[cur_idx - 1].get("file")
                                msg, msg_timer = f"Music: {track_names[cur_idx]}", 90
                            dirty = True
                        elif r_menu.collidepoint(ev.pos):
                            # Same as Esc — preserve unsaved work via autosave.
                            if dirty:
                                autosave_now()
                            music.stop()
                            return
                    else:
                        gx, gy = screen_to_cell(mx, my)
                        if snippet_stamp is not None:
                            # Drop a fresh-id clone of the stamp anchored at the
                            # cursor cell. Stamp stays armed so the user can
                            # place multiple copies; Esc cancels. Shift drops
                            # then disarms — handy for "place once and continue".
                            push_undo()
                            new_objs = _clone_objects(
                                snippet_stamp, (gx, gy), objects
                            )
                            objects.extend(new_objs)
                            selected_objs = list(new_objs)
                            last_edit_cell = None
                            shift_drop = bool(
                                pygame.key.get_mods() & pygame.KMOD_SHIFT
                            )
                            stamp_label = snippet_stamp_name
                            if shift_drop:
                                snippet_stamp = None
                                snippet_stamp_name = ""
                                msg = (
                                    f"Stamped {stamp_label} ({len(new_objs)} obj)"
                                )
                            else:
                                msg = (
                                    f"Stamped {stamp_label} ({len(new_objs)} obj)"
                                    " — click to repeat, Esc to cancel"
                                )
                            msg_timer = 120
                        elif tool == TOOL_ERASE:
                            push_undo()
                            _erase_at(objects, gx, gy)
                        elif tool == TOOL_GROUP:
                            pending_link, m = _link_click(objects, gx, gy, pending_link)
                            msg, msg_timer = m, 110
                        elif tool == TOOL_EDIT:
                            shift_held = bool(pygame.key.get_mods() & pygame.KMOD_SHIFT)
                            stack = objects_at_cell(objects, gx, gy)
                            top = stack[-1] if stack else None
                            if shift_held and top:
                                if top in selected_objs:
                                    selected_objs.remove(top)
                                else:
                                    selected_objs.append(top)
                                last_edit_cell = None
                                msg, msg_timer = f"{len(selected_objs)} selected", 70
                            elif shift_held:
                                drag_mode = "rubber"
                                drag_start_screen = (mx, my)
                                drag_rubber_shift = True
                            elif top and top in selected_objs and len(selected_objs) > 1:
                                drag_mode = "move"
                                drag_anchor_cell = (gx, gy)
                                drag_positions = {id(o): (o["x"], o["y"]) for o in selected_objs}
                                drag_moved = False
                                last_edit_cell = None
                            elif top:
                                if (last_edit_cell == (gx, gy) and len(selected_objs) == 1
                                        and selected_objs[0] in stack):
                                    idx = (stack.index(selected_objs[0]) + 1) % len(stack)
                                    selected_objs = [stack[idx]]
                                else:
                                    selected_objs = [top]
                                last_edit_cell = (gx, gy)
                                drag_mode = "move"
                                drag_anchor_cell = (gx, gy)
                                drag_positions = {id(o): (o["x"], o["y"]) for o in selected_objs}
                                drag_moved = False
                                if len(stack) > 1:
                                    msg, msg_timer = f"Stack {stack.index(selected_objs[0])+1}/{len(stack)} — click again to cycle", 120
                            else:
                                selected_objs = []
                                last_edit_cell = None
                                drag_mode = "rubber"
                                drag_start_screen = (mx, my)
                                drag_rubber_shift = False
                        elif tool == TOOL_BOT_PATH:
                            world_x = (mx + cam_x) / zoom_level
                            world_y = (my + cam_y) / zoom_level
                            bot_waypoints.append((world_x, world_y))
                            # Manual editing invalidates the autobot pairing.
                            bot_exact_inputs = None
                            bot_mirror_waypoints = []
                            msg, msg_timer = f"Bot path: {len(bot_waypoints)} pts (K=run, R-click=undo)", 90
                        else:
                            push_undo()
                            gid = (current_group_id
                                   if selected_type == T_TELEPORT_ORB else 0)
                            _place_object(objects, gx, gy, selected_type,
                                          current_rotation, gid)
                            if selected_type == T_TELEPORT_ORB:
                                current_group_id = next_group_id(objects)
                elif ev.button == 3:
                    handled_curve = False
                    if (tool == TOOL_EDIT and len(selected_objs) == 1
                            and selected_objs[0]["t"] == T_MOVE_TRIGGER):
                        ao = selected_objs[0]
                        stack_here3 = objects_at_cell(objects, ao["x"], ao["y"])
                        pbr3, _ph3 = _panel_button_rects(ao, len(stack_here3))
                        cr3 = pbr3.get("curve")
                        if cr3 is not None and cr3.collidepoint(ev.pos):
                            handled_curve = True
                            curve = _ensure_curve(ao)
                            for i, p in enumerate(curve):
                                sp = _curve_point_to_px(cr3, p[0], p[1])
                                d2 = (sp[0] - ev.pos[0]) ** 2 + (sp[1] - ev.pos[1]) ** 2
                                if d2 <= CURVE_HIT_R2:
                                    if 0 < i < len(curve) - 1:
                                        push_undo()
                                        curve.pop(i)
                                        msg, msg_timer = "Deleted curve point", 70
                                    break
                    if not handled_curve and in_canvas:
                        if tool == TOOL_BOT_PATH:
                            if bot_waypoints:
                                bot_waypoints.pop()
                                msg, msg_timer = f"Bot path: {len(bot_waypoints)} pts", 70
                        else:
                            gx, gy = screen_to_cell(mx, my)
                            push_undo()
                            _erase_at(objects, gx, gy)
            if ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
                if curve_drag_idx is not None:
                    curve_drag_idx = None
                if drag_mode == "rubber":
                    x0, y0 = drag_start_screen
                    x1, y1 = ev.pos
                    effective_cell = int(CELL * zoom_level)
                    rr = pygame.Rect(min(x0, x1), min(y0, y1),
                                     abs(x1 - x0), abs(y1 - y0))
                    if rr.width >= 3 or rr.height >= 3:
                        cgx0 = int((rr.left + cam_x) // effective_cell)
                        cgy0 = int((rr.top + cam_y) // effective_cell)
                        cgx1 = int((rr.right + cam_x) // effective_cell)
                        cgy1 = int((rr.bottom + cam_y) // effective_cell)
                        hits = [o for o in objects
                                if cgx0 <= o["x"] <= cgx1 and cgy0 <= o["y"] <= cgy1]
                        if drag_rubber_shift:
                            for h in hits:
                                if h in selected_objs:
                                    selected_objs.remove(h)
                                else:
                                    selected_objs.append(h)
                        else:
                            selected_objs = hits
                        last_edit_cell = None
                        if selected_objs:
                            msg, msg_timer = f"{len(selected_objs)} selected", 90
                elif drag_mode == "move" and drag_moved:
                    push_undo()
                    msg, msg_timer = (
                        f"Moved {len(selected_objs)} object{'s' if len(selected_objs) != 1 else ''}",
                        80,
                    )
                drag_mode = None
                drag_moved = False
        # mouse_held() is the guard-aware version of get_pressed()[0] — it
        # returns False until the user has released the entry click and
        # pressed again, so a residual mouse-down never triggers an edit.
        held_l = guard.mouse_held()
        try:
            raw = pygame.mouse.get_pressed()
            mb = (held_l, raw[1] if len(raw) > 1 else False,
                  raw[2] if len(raw) > 2 else False)
        except pygame.error:
            mb = (held_l, False, False)
        single_selected = selected_objs[0] if len(selected_objs) == 1 else None
        panel_visible = tool == TOOL_EDIT and single_selected is not None
        if panel_visible:
            panel_stack = objects_at_cell(objects, single_selected["x"], single_selected["y"])
            panel_stack_len = len(panel_stack)
            _, panel_h_loop = _panel_button_rects(single_selected, panel_stack_len)
            panel_rect = pygame.Rect(PANEL_X, PANEL_Y, PANEL_W, panel_h_loop)
        else:
            panel_stack = []
            panel_stack_len = 0
            panel_rect = None
        over_panel = panel_rect.collidepoint(mpos) if panel_rect else False
        if (mb[0] and curve_drag_idx is not None and panel_visible
                and single_selected is not None
                and single_selected["t"] == T_MOVE_TRIGGER):
            pbr_cd, _ = _panel_button_rects(single_selected, panel_stack_len or 1)
            cr_cd = pbr_cd.get("curve")
            if cr_cd is not None:
                curve_cd = _ensure_curve(single_selected)
                if 0 <= curve_drag_idx < len(curve_cd):
                    nt, ns = _px_to_curve_point(cr_cd, mx, my)
                    if curve_drag_idx == 0:
                        curve_cd[0] = [0.0, ns]
                    elif curve_drag_idx == len(curve_cd) - 1:
                        curve_cd[-1] = [1.0, ns]
                    else:
                        tmin = curve_cd[curve_drag_idx - 1][0] + 0.001
                        tmax = curve_cd[curve_drag_idx + 1][0] - 0.001
                        nt = max(tmin, min(tmax, nt))
                        curve_cd[curve_drag_idx] = [nt, ns]
                    dirty = True
            else:
                curve_drag_idx = None
        else:
            if not mb[0]:
                curve_drag_idx = None
        if mb[0] and tool == TOOL_EDIT and drag_mode == "move":
            gx, gy = screen_to_cell(mx, my)
            agx, agy = drag_anchor_cell
            dx = gx - agx
            dy = gy - agy
            moved_any = False
            for o in selected_objs:
                start = drag_positions.get(id(o))
                if start is None:
                    continue
                nx, ny = start[0] + dx, start[1] + dy
                if o["x"] != nx or o["y"] != ny:
                    o["x"], o["y"] = nx, ny
                    moved_any = True
            if moved_any:
                drag_moved = True
                dirty = True
        if in_canvas and not over_panel and (mb[0] or mb[2]) and tool != TOOL_BOT_PATH:
            gx, gy = screen_to_cell(mx, my)
            if mb[0] and tool == TOOL_BRUSH:
                gid = (current_group_id
                       if selected_type == T_TELEPORT_ORB else 0)
                _place_object(objects, gx, gy, selected_type,
                              current_rotation, gid)
                dirty = True
            elif mb[0] and tool == TOOL_ERASE:
                _erase_at(objects, gx, gy)
                dirty = True
            elif mb[2]:
                _erase_at(objects, gx, gy)
                dirty = True
        keys = pygame.key.get_pressed()
        spd = 22 if keys[pygame.K_LSHIFT] else 11
        if keys[pygame.K_LEFT] or keys[pygame.K_a]:
            cam_x -= spd
        if keys[pygame.K_RIGHT] or keys[pygame.K_d]:
            cam_x += spd
        if keys[pygame.K_UP]:
            cam_y -= spd
        if keys[pygame.K_DOWN]:
            cam_y += spd
        if msg_timer > 0:
            msg_timer -= 1
        # ---- Autosave tick -------------------------------------------------
        # Only count time when there are unsaved changes; once we save, the
        # timer resets and won't run again until the level is dirty again.
        if dirty:
            autosave_timer += 1
            if autosave_timer >= AUTOSAVE_INTERVAL:
                autosave_timer = 0
                if autosave_now():
                    msg, msg_timer = "Auto-saved", 60
        else:
            autosave_timer = 0
        if autosave_toast_frames > 0:
            autosave_toast_frames -= 1
        if do_save:
            name = text_input_dialog(screen, clock, "Level name:", level_name)
            guard.reset()  # prevent click-through from dialog
            if name:
                level_name = name
                fn = name.lower().replace(" ", "_")
                # Preserve existing meta (published/verified/etc) so saving
                # an already-published level doesn't silently un-publish it.
                save_meta = dict(level_meta) if level_meta else None
                if save_meta:
                    save_meta["name"] = name
                save_level(objects, name, fn, music_file=level_music, meta=save_meta)
                level_filename = fn + ".json"
                # Reload meta so we have the current on-disk state.
                try:
                    import os as _os
                    from constants import LEVELS_DIR as _LEVELS_DIR
                    level_meta, _ = load_level_full(_os.path.join(_LEVELS_DIR, level_filename))
                except (OSError, ValueError):
                    level_meta = None
                # Real save supersedes any pending autosave.
                clear_autosave()
                dirty = False
                autosave_timer = 0
                msg, msg_timer = f"Saved as {fn}.json", 120
        if do_publish:
            # Save (if needed) then flip the published flag on.
            name_for_pub = level_name
            if not level_filename:
                name_for_pub = text_input_dialog(screen, clock, "Publish as:", level_name)
                guard.reset()
            if name_for_pub:
                # Ask the publisher to *request* a difficulty for the level.
                # The verifier (first hand-played win) can override it later.
                cur_req = (level_meta or {}).get("requested_difficulty",
                                                 (level_meta or {}).get("difficulty", "Normal"))
                req_diff = difficulty_picker(
                    screen, clock,
                    prompt="Request a difficulty:",
                    default=cur_req,
                    subtitle="The verifier will confirm or change this when they beat it.",
                )
                guard.reset()
                if req_diff is None:
                    msg, msg_timer = "Publish cancelled", 120
                else:
                    fn = (level_filename.replace(".json", "")
                          if level_filename else name_for_pub.lower().replace(" ", "_"))
                    save_meta = dict(level_meta) if level_meta else None
                    if save_meta is None:
                        from levels import _default_meta as _dm
                        save_meta = _dm(name_for_pub)
                    save_meta["name"] = name_for_pub
                    save_meta["published"] = True
                    save_meta["requested_difficulty"] = req_diff
                    # Until verified, the displayed difficulty mirrors the request.
                    if not save_meta.get("verified"):
                        save_meta["difficulty"] = req_diff
                    # Publishing a fresh level must not carry over verified=True
                    # from a prior beaten session — leave verified as-is (starts
                    # False from _default_meta).
                    level_name = name_for_pub
                    save_level(objects, name_for_pub, fn, music_file=level_music, meta=save_meta)
                    level_filename = fn + ".json"
                    try:
                        import os as _os
                        from constants import LEVELS_DIR as _LEVELS_DIR
                        level_meta, _ = load_level_full(_os.path.join(_LEVELS_DIR, level_filename))
                    except (OSError, ValueError):
                        level_meta = save_meta
                    # Publishing also commits the work — clear any autosave.
                    clear_autosave()
                    dirty = False
                    autosave_timer = 0
                    msg, msg_timer = (f"Published {fn}.json as {req_diff} "
                                      f"— awaiting verification"), 180
        if do_load:
            path = load_level_dialog(screen, clock)
            guard.reset()  # prevent click-through from dialog
            if path:
                try:
                    level_meta, loaded_objs = load_level_full(path)
                    objects = loaded_objs
                    level_name = level_meta["name"]
                    level_music = level_meta.get("music")
                    import os as _os
                    level_filename = _os.path.basename(path)
                except (OSError, ValueError) as err:
                    msg, msg_timer = f"Load failed: {err}", 180
                else:
                    pending_link = None
                    selected_objs = []
                    last_edit_cell = None
                    drag_mode = None
                    undo_stack = []
                    redo_stack = []
                    # Loading a fresh level supersedes any pending autosave
                    # (which referred to the previous slot).
                    clear_autosave()
                    dirty = False
                    autosave_timer = 0
                    msg, msg_timer = f"Loaded: {level_name}", 120
        selected_objs = [o for o in selected_objs if o in objects]
        if not selected_objs:
            last_edit_cell = None
        single_selected = selected_objs[0] if len(selected_objs) == 1 else None
        if do_test:
            # Pass the editor's assigned music so the test playthrough has
            # GD-style music (start at 0, restart on death/R, stop on exit).
            # `last_run_hitboxes` is mutated in place by run_play so the
            # editor's H-toggle overlay always reflects the most recent run.
            last_run_hitboxes.clear()
            # Shift+T → spawn at the cursor's world x with music seeked
            # to the matching offset. Test-at-start otherwise.
            _test_start_x = None
            if do_test_from_cursor:
                _test_start_x = int((mx + cam_x) / zoom_level)
            _test_name = (level_name + " (Test)"
                          + (" @cursor" if _test_start_x else ""))
            run_play(screen, clock, list(objects), _test_name,
                     editor_test=True, level_music=level_music,
                     meta=level_meta,
                     out_hitboxes=last_run_hitboxes,
                     start_x=_test_start_x)
            guard.reset()  # prevent click-through from play
        if do_bot:
            # Bot replays now also pass level_music — the user asked for the
            # selected track to play during bot/test runs (just not while
            # editing). Variable-speed test runs (via [/]/0) will desync the
            # audio, but at the default 1.0× speed it tracks fine.
            if bot_exact_inputs:
                last_run_hitboxes.clear()
                run_play(screen, clock, list(objects), level_name + " (Bot Exact)",
                         editor_test=True, playback_inputs=bot_exact_inputs,
                         level_music=level_music, meta=level_meta,
                         out_hitboxes=last_run_hitboxes)
                msg, msg_timer = f"Exact playback done — {len(bot_exact_inputs)} frames", 180
            elif bot_waypoints:
                bot = BotController(list(bot_waypoints), objects=list(objects))
                last_run_hitboxes.clear()
                run_play(screen, clock, list(objects), level_name + " (Bot)",
                         editor_test=True, bot_controller=bot,
                         level_music=level_music, meta=level_meta,
                         out_hitboxes=last_run_hitboxes)
                bot.save_inputs()
                msg, msg_timer = f"Bot done — {len(bot.inputs)} frames saved to level_bot_inputs.txt", 180
            else:
                pb_inputs = load_bot_inputs()
                if pb_inputs:
                    last_run_hitboxes.clear()
                    run_play(screen, clock, list(objects), level_name + " (Playback)",
                             editor_test=True, playback_inputs=pb_inputs,
                             level_music=level_music, meta=level_meta,
                             out_hitboxes=last_run_hitboxes)
                    msg, msg_timer = f"Playback done — {len(pb_inputs)} frames", 120
                else:
                    msg, msg_timer = "Draw a bot path first (Bot tool) or have level_bot_inputs.txt", 120
            guard.reset()  # prevent click-through from play
        if do_bot_menu:
            # Editor-side bot menu: when the user clicks Replay, run the
            # solved inputs against a real Player in the test-play screen.
            from bot_menu import (run_bot_menu, get_last_inputs,
                                  get_last_mirror_waypoints)

            def _replay_in_editor(inputs):
                # Same level_music wiring as the other bot replays — keep
                # the audio experience consistent across all bot entry
                # points (K key, Bot button, Bot menu's Replay button).
                # Pass level_meta so PhysicsParams.from_meta returns the
                # same per-level tunables the solver used; otherwise the
                # replay silently runs on default physics and dies at the
                # first divergent jump arc.
                last_run_hitboxes.clear()
                run_play(screen, clock, list(objects),
                         level_name + " (Bot Replay)",
                         editor_test=True, playback_inputs=inputs,
                         level_music=level_music, meta=level_meta,
                         out_hitboxes=last_run_hitboxes)
                guard.reset()

            result = run_bot_menu(
                screen, clock, list(objects),
                precomputed_path=bot_waypoints if bot_waypoints else None,
                allow_replay=True,
                replay_callback=_replay_in_editor,
                level_filename=level_filename,
                meta=level_meta,
            )
            guard.reset()
            if result is not None:
                wp, status = result
                if wp:
                    bot_waypoints = list(wp)
                    bot_mirror_waypoints = get_last_mirror_waypoints()
                    bot_exact_inputs = get_last_inputs() or bot_exact_inputs
                    tool = TOOL_BOT_PATH
                    msg, msg_timer = (
                        f"Bot path ready ({status}) — "
                        f"{len(bot_waypoints)} waypoints"
                    ), 200
        draw_bg(screen, cam_x, stars, mountains)
        if show_grid:
            effective_cell = int(CELL * zoom_level)
            grid_surf = _get_grid_surface(effective_cell)
            # Offset-and-clip blit: the grid surface is slightly larger than
            # the viewport so any sub-cell scroll offset still covers the
            # visible region. set_clip confines output to the grid band.
            ox = int(-cam_x % effective_cell) - effective_cell
            oy = int(-cam_y % effective_cell) - effective_cell
            prev_clip = screen.get_clip()
            screen.set_clip(pygame.Rect(0, TOP_H, WIDTH, BAR_Y - TOP_H))
            screen.blit(grid_surf, (ox, TOP_H + oy))
            screen.set_clip(prev_clip)
        effective_cell = int(CELL * zoom_level)
        left_gx = int(cam_x // effective_cell) - 1
        right_gx = left_gx + WIDTH // effective_cell + 3
        top_gy = int(cam_y // effective_cell) - 1
        bot_gy = top_gy + HEIGHT // effective_cell + 3
        for o in objects:
            if left_gx <= o["x"] <= right_gx and top_gy <= o["y"] <= bot_gy:
                if o["t"] == T_END:
                    # Win line is an infinite-height wall, not a 50x50 sprite.
                    draw_end_wall(screen,
                                  o["x"] * effective_cell - cam_x,
                                  o["y"] * effective_cell - cam_y,
                                  effective_cell, pulse)
                    continue
                meta = o if o["t"] in (T_TELEPORT_ORB, T_CAMERA_TRIGGER, T_BG_TRIGGER, T_MOVE_TRIGGER, T_COLOR_TRIGGER) else None
                draw_obj(screen, o["t"], o["x"] * effective_cell - cam_x, o["y"] * effective_cell - cam_y,
                         effective_cell, pulse, o.get("r", 0), meta)
        for o in objects:
            if o["t"] != T_MOVE_TRIGGER:
                continue
            # Collect all target oids (multi or single)
            oids = o.get("target_oids", [])
            if not oids:
                single = o.get("target_oid", 0)
                if single:
                    oids = [single]
            if not oids:
                continue
            sxl = o["x"] * effective_cell - cam_x + effective_cell // 2
            syl = o["y"] * effective_cell - cam_y + effective_cell // 2
            for t_oid in oids:
                target = next((x for x in objects if x.get("oid") == t_oid), None)
                if not target:
                    continue
                txl = target["x"] * effective_cell - cam_x + effective_cell // 2
                tyl = target["y"] * effective_cell - cam_y + effective_cell // 2
                pygame.draw.line(screen, (200, 150, 255), (sxl, syl), (txl, tyl), 1)
            # Draw destination marker using first target as reference
            first_target = next((x for x in objects if x.get("oid") == oids[0]), None)
            if first_target:
                exl = o.get("tx", first_target["x"]) * effective_cell - cam_x + effective_cell // 2
                eyl = o.get("ty", first_target["y"]) * effective_cell - cam_y + effective_cell // 2
                txl = first_target["x"] * effective_cell - cam_x + effective_cell // 2
                tyl = first_target["y"] * effective_cell - cam_y + effective_cell // 2
                pygame.draw.line(screen, (255, 200, 100), (txl, tyl), (exl, eyl), 1)
                pygame.draw.circle(screen, (255, 200, 100), (exl, eyl), 6, 1)
        # Hitbox playback overlay: draw the player's recorded rects from
        # the most recent run on top of the level. Frames are layered with
        # alpha so dense passes (a long ship hover) read as a single thick
        # band while quick traversals stay legible. Drawn here so palette /
        # bot path / selection rings render on top.
        if show_hitboxes:
            from constants import (PLAYER_SIZE as _HB_PSZ, T_SPIKE,
                                    T_HALF_SPIKE, T_SAW)
            if _hb_scratch[0] is None:
                _hb_scratch[0] = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            hb_layer = _hb_scratch[0]
            hb_layer.fill((0, 0, 0, 0))
            world_left = cam_x / zoom_level - 60
            world_right = (cam_x + WIDTH) / zoom_level + 60
            world_top = cam_y / zoom_level - 60
            world_bot = (cam_y + HEIGHT) / zoom_level + 60
            # Player's recorded path from the last run (if any) —
            # cell-aligned 44×44 boxes in green (solid-collision
            # footprint) with the inner hazard rect in red.
            for hx, hy, hsz in last_run_hitboxes:
                if (hx + hsz < world_left or hx > world_right
                        or hy + hsz < world_top or hy > world_bot):
                    continue
                sxh = int(hx * zoom_level - cam_x)
                syh = int(hy * zoom_level - cam_y)
                ssz = max(1, int(hsz * zoom_level))
                pygame.draw.rect(hb_layer, (120, 255, 140, 90),
                                 (sxh, syh, ssz, ssz), 1)
                shrink = max(2, int(6 * hsz / _HB_PSZ))
                ssh = max(1, int(shrink * zoom_level))
                inner_sz = max(1, ssz - 2 * ssh)
                pygame.draw.rect(hb_layer, (255, 110, 110, 110),
                                 (sxh + ssh, syh + ssh,
                                  inner_sz, inner_sz), 1)
            # Hazard hitboxes (spikes, half-spikes, saws) so the author
            # can see EXACTLY where the kill zones are — distinct from
            # the rendered sprite art which has decorative margins.
            eff_left_gx = int(cam_x / zoom_level) // CELL - 1
            eff_right_gx = int((cam_x + WIDTH) / zoom_level) // CELL + 2
            eff_top_gy = int(cam_y / zoom_level) // CELL - 1
            eff_bot_gy = int((cam_y + HEIGHT) / zoom_level) // CELL + 2
            for o in objects:
                t = o["t"]
                if t not in (T_SPIKE, T_HALF_SPIKE, T_SAW):
                    continue
                gx = o["x"]
                gy = o["y"]
                if not (eff_left_gx <= gx <= eff_right_gx
                        and eff_top_gy <= gy <= eff_bot_gy):
                    continue
                if t == T_SAW:
                    hb = saw_hitbox(gx, gy)
                    rects = [hb]
                else:
                    rects = spike_hitboxes(gx, gy, o.get("r", 0),
                                           half=(t == T_HALF_SPIKE))
                for rr in rects:
                    sx = int(rr.x * zoom_level - cam_x)
                    sy = int(rr.y * zoom_level - cam_y)
                    sw = max(1, int(rr.w * zoom_level))
                    sh = max(1, int(rr.h * zoom_level))
                    # Semi-transparent fill so the hazard region reads
                    # through decorations; bright outline for clarity.
                    pygame.draw.rect(hb_layer, (255, 80, 80, 60),
                                     (sx, sy, sw, sh))
                    pygame.draw.rect(hb_layer, (255, 60, 60, 220),
                                     (sx, sy, sw, sh), 1)
            screen.blit(hb_layer, (0, 0))
        # Draw bot path waypoints
        if bot_waypoints:
            path_pts = []
            for wx, wy in bot_waypoints:
                sx = int(wx * zoom_level - cam_x)
                sy = int(wy * zoom_level - cam_y)
                path_pts.append((sx, sy))
            if len(path_pts) >= 2:
                pygame.draw.lines(screen, (255, 180, 60), False, path_pts, 2)
            for i, pt in enumerate(path_pts):
                is_end = (i == 0 or i == len(path_pts) - 1)
                col = (255, 220, 100) if is_end else (255, 180, 60)
                pygame.draw.circle(screen, col, pt, 5)
                pygame.draw.circle(screen, (0, 0, 0), pt, 5, 1)
        # Mirror path: drawn in blue to distinguish the dual body's route
        # from the main yellow path. Only present when the autobot solved
        # a level that enters dual mode.
        if bot_mirror_waypoints:
            mpath_pts = []
            for wx, wy in bot_mirror_waypoints:
                sx = int(wx * zoom_level - cam_x)
                sy = int(wy * zoom_level - cam_y)
                mpath_pts.append((sx, sy))
            if len(mpath_pts) >= 2:
                pygame.draw.lines(screen, (90, 170, 255), False, mpath_pts, 2)
            for pt in mpath_pts:
                pygame.draw.circle(screen, (90, 170, 255), pt, 4)
                pygame.draw.circle(screen, (0, 0, 0), pt, 4, 1)
        if pending_link:
            kind = pending_link.get("kind")
            if kind == "teleport":
                src = pending_link["first"]
                col = (255, 220, 90)
            elif kind == "move":
                src = pending_link.get("target") or pending_link["trigger"]
                col = (255, 180, 100)
            else:
                src = None
                col = (255, 220, 90)
            if src:
                sxl = src["x"] * effective_cell - cam_x + effective_cell // 2
                syl = src["y"] * effective_cell - cam_y + effective_cell // 2
                pygame.draw.circle(screen, col, (sxl, syl), 26, 2)
                if in_canvas:
                    pygame.draw.line(screen, col, (sxl, syl), mpos, 1)
            if kind == "move" and pending_link.get("target"):
                tr = pending_link["trigger"]
                trx = tr["x"] * effective_cell - cam_x + effective_cell // 2
                trry = tr["y"] * effective_cell - cam_y + effective_cell // 2
                pygame.draw.circle(screen, (200, 150, 255), (trx, trry), 26, 2)
        for sobj in selected_objs:
            sxb = sobj["x"] * effective_cell - cam_x
            syb = sobj["y"] * effective_cell - cam_y
            pygame.draw.rect(screen, (120, 255, 140), (sxb, syb, effective_cell, effective_cell), 2)
        if single_selected is not None:
            sxb = single_selected["x"] * effective_cell - cam_x
            syb = single_selected["y"] * effective_cell - cam_y
            ring = pygame.Surface((effective_cell + 12, effective_cell + 12), pygame.SRCALPHA)
            pygame.draw.rect(ring, (120, 255, 140, 110), ring.get_rect(), 3, border_radius=6)
            screen.blit(ring, (sxb - 6, syb - 6))
            if single_selected["t"] == T_CAMERA_TRIGGER:
                target_y = single_selected.get("cy", single_selected["y"]) * effective_cell - cam_y + effective_cell // 2
                pygame.draw.line(screen, (255, 225, 80),
                                 (sxb + effective_cell // 2, syb + effective_cell // 2),
                                 (sxb + effective_cell // 2, target_y), 2)
                pygame.draw.line(screen, (255, 225, 80),
                                 (0, target_y), (WIDTH, target_y), 1)
            if single_selected["t"] == T_MODE_DUAL:
                # Cyan ghost cube on the chosen spawn row so the user can
                # see exactly where the mirror will appear.
                spawn_row = single_selected.get("spawn_y", single_selected["y"])
                spawn_y_top = spawn_row * effective_cell - cam_y
                ghost = pygame.Rect(sxb, spawn_y_top, effective_cell, effective_cell)
                ghost_layer = pygame.Surface((effective_cell, effective_cell),
                                             pygame.SRCALPHA)
                ghost_layer.fill((120, 220, 255, 90))
                screen.blit(ghost_layer, ghost.topleft)
                pygame.draw.rect(screen, (140, 230, 255), ghost, 2)
                pygame.draw.line(screen, (140, 230, 255),
                                 (sxb + effective_cell // 2,
                                  syb + effective_cell // 2),
                                 (sxb + effective_cell // 2,
                                  spawn_y_top + effective_cell // 2), 2)
        if drag_mode == "rubber" and mb[0]:
            x0, y0 = drag_start_screen
            x1, y1 = mpos
            rr = pygame.Rect(min(x0, x1), min(y0, y1),
                             abs(x1 - x0), abs(y1 - y0))
            if rr.width > 0 and rr.height > 0:
                fill = pygame.Surface((rr.w, rr.h), pygame.SRCALPHA)
                fill.fill((120, 255, 140, 40))
                screen.blit(fill, rr.topleft)
                pygame.draw.rect(screen, (120, 255, 140), rr, 1)
        if in_canvas and not over_panel:
            gx, gy = screen_to_cell(mx, my)
            sx = gx * effective_cell - cam_x
            sy = gy * effective_cell - cam_y
            if snippet_stamp is not None:
                # Translucent ghost of every stamp object, anchored to the
                # cursor cell. Shows exactly where each piece will land.
                stamp_xs = [o["x"] for o in snippet_stamp]
                stamp_ys = [o["y"] for o in snippet_stamp]
                min_sx = min(stamp_xs) if stamp_xs else 0
                min_sy = min(stamp_ys) if stamp_ys else 0
                max_sx = max(stamp_xs) if stamp_xs else 0
                max_sy = max(stamp_ys) if stamp_ys else 0
                for so in snippet_stamp:
                    ox = so["x"] - min_sx
                    oy = so["y"] - min_sy
                    cx = (gx + ox) * effective_cell - cam_x
                    cy = (gy + oy) * effective_cell - cam_y
                    gs = pygame.Surface(
                        (effective_cell, effective_cell), pygame.SRCALPHA
                    )
                    gs.set_alpha(140)
                    draw_obj(gs, so["t"], 0, 0, effective_cell, pulse,
                             so.get("r", 0))
                    screen.blit(gs, (cx, cy))
                # Outline the bounding box so the user sees the footprint.
                bw = (max_sx - min_sx + 1) * effective_cell
                bh = (max_sy - min_sy + 1) * effective_cell
                pygame.draw.rect(screen, (160, 220, 255),
                                 (sx, sy, bw, bh), 1)
            elif tool == TOOL_ERASE:
                pygame.draw.rect(screen, (255, 80, 80), (sx, sy, effective_cell, effective_cell), 2)
                pygame.draw.line(screen, (255, 80, 80), (sx + 8, sy + 8), (sx + effective_cell - 8, sy + effective_cell - 8), 2)
                pygame.draw.line(screen, (255, 80, 80), (sx + effective_cell - 8, sy + 8), (sx + 8, sy + effective_cell - 8), 2)
            elif tool == TOOL_GROUP:
                pygame.draw.rect(screen, (200, 160, 255), (sx, sy, effective_cell, effective_cell), 2)
            elif tool == TOOL_EDIT:
                pygame.draw.rect(screen, (120, 255, 140), (sx, sy, effective_cell, effective_cell), 1)
            elif tool == TOOL_BOT_PATH:
                pygame.draw.circle(screen, (255, 180, 60), (mx, my), 6, 2)
                if bot_waypoints:
                    last_sx = int(bot_waypoints[-1][0] * zoom_level - cam_x)
                    last_sy = int(bot_waypoints[-1][1] * zoom_level - cam_y)
                    pygame.draw.line(screen, (255, 180, 60), (last_sx, last_sy), (mx, my), 1)
            else:
                gs = pygame.Surface((effective_cell, effective_cell), pygame.SRCALPHA)
                gs.set_alpha(130)
                draw_obj(gs, selected_type, 0, 0, effective_cell, pulse, current_rotation)
                screen.blit(gs, (sx, sy))
                pygame.draw.rect(screen, C_WHITE, (sx, sy, effective_cell, effective_cell), 1)
        if panel_visible:
            stack_idx = panel_stack.index(single_selected) if single_selected in panel_stack else 0
            _draw_edit_panel(screen, single_selected, mpos, pulse, (stack_idx, panel_stack_len))
        elif tool == TOOL_EDIT and len(selected_objs) > 1:
            banner_w, banner_h = 220, 44
            br = pygame.Rect(WIDTH - banner_w - 12, PANEL_Y, banner_w, banner_h)
            pygame.draw.rect(screen, (18, 14, 36), br, border_radius=8)
            pygame.draw.rect(screen, (70, 170, 110), br, 2, border_radius=8)
            txt(screen, f"{len(selected_objs)} selected",
                br.centerx, br.y + 12, 15, C_WHITE, True)
            txt(screen, "Drag=move R/Q=rot Del ^C/X/V=cpy/cut/paste ^D=dup",
                br.centerx, br.y + 30, 10, C_GRAY, True)
        hovered_item = _draw_palette(screen, mpos, active_cat, selected_type,
                                     tool, pulse, tab_rects, item_rects, tool_rects)
        if tool == TOOL_BRUSH:
            sel_name = TYPE_NAMES.get(selected_type, "")
        else:
            sel_name = {TOOL_ERASE: "Eraser", TOOL_GROUP: "Group Tool",
                        TOOL_EDIT: "Edit Tool", TOOL_BOT_PATH: "Bot Path"}[tool]
        # Dark pill backdrop so these status labels remain readable no
        # matter what the level background looks like (UI_AUDIT §11).
        _pill_bg = pygame.Surface((170, 22), pygame.SRCALPHA)
        _pill_bg.fill((0, 0, 0, 160))
        screen.blit(_pill_bg, (4, TOP_H))
        txt(screen, sel_name, 10, TOP_H + 2, 13, C_WHITE)
        _rot_pill = pygame.Surface((80, 22), pygame.SRCALPHA)
        _rot_pill.fill((0, 0, 0, 160))
        screen.blit(_rot_pill, (176, TOP_H))
        txt(screen, f"Rot {current_rotation}°", 180, TOP_H + 2, 13, C_GRAY)
        if selected_type == T_TELEPORT_ORB and tool == TOOL_BRUSH:
            _grp_pill = pygame.Surface((160, 22), pygame.SRCALPHA)
            _grp_pill.fill((0, 0, 0, 160))
            screen.blit(_grp_pill, (296, TOP_H))
            txt(screen, f"Next group: {current_group_id}",
                300, TOP_H + 2, 13, C_GRAY)
        pygame.draw.rect(screen, (20, 18, 40), (0, BAR_Y, WIDTH, HEIGHT - BAR_Y))
        pygame.draw.line(screen, C_GRID, (0, BAR_Y), (WIDTH, BAR_Y), 1)
        btn(screen, "Save [S]", 70, BAR_Y + 27, 84, 38, C_BTN, mpos)
        btn(screen, "Publish", 158, BAR_Y + 27, 84, 38, C_PUBLISH, mpos)
        btn(screen, "Load [^L]", 246, BAR_Y + 27, 84, 38, C_BTN, mpos)
        btn(screen, "Test [T]", 334, BAR_Y + 27, 84, 38, (40, 120, 80), mpos)
        bot_label = (f"Bot [L] ({len(bot_waypoints)})"
                     if bot_waypoints else "Bot [L]")
        btn(screen, bot_label, 422, BAR_Y + 27, 84, 38, (180, 120, 30), mpos)
        btn(screen, "Clear", 510, BAR_Y + 27, 70, 38, C_DANGER, mpos)
        music_label = "Music" if level_music is None else "Music*"
        btn(screen, music_label, 590, BAR_Y + 27, 84, 38, (80, 60, 140), mpos)
        btn(screen, "Menu", 678, BAR_Y + 27, 84, 38, C_DANGER, mpos)
        # Mute toggles (icon-only)
        r_mute_music = icon_button(
            screen, speaker_icon(18, music.is_muted()),
            r_mute_music.centerx, r_mute_music.centery, 36, 36, C_BTN, mpos,
            active=music.is_muted(),
        )
        r_mute_sfx = icon_button(
            screen, speaker_icon(16, sfx.is_muted()),
            r_mute_sfx.centerx, r_mute_sfx.centery, 36, 36, (80, 60, 140), mpos,
            active=sfx.is_muted(),
        )
        gx_disp, gy_disp = screen_to_cell(mx, my)
        txt(screen, f"Obj: {len(objects)} | Undo: {len(undo_stack)}", WIDTH - 230, BAR_Y + 6, 13, C_GRAY)
        txt(screen, f"Cell: ({gx_disp}, {gy_disp})  Zoom: {zoom_level:.1f}x", WIDTH - 230, BAR_Y + 22, 13, C_GRAY)
        status_chunks = [f"Level: {level_name}"]
        if dirty:
            status_chunks.append("● unsaved")
        if snippet_stamp is not None:
            status_chunks.append(f"⛶ {snippet_stamp_name}")
        if show_hitboxes:
            status_chunks.append(
                f"⌗ Hitboxes ({len(last_run_hitboxes)})"
                if last_run_hitboxes else "⌗ Hitboxes (no run yet)"
            )
        if level_meta:
            if level_meta.get("verified"):
                status_chunks.append("✓ Verified")
            elif level_meta.get("published"):
                status_chunks.append("◦ Published (unverified)")
        txt(screen, " · ".join(status_chunks), WIDTH - 230, BAR_Y + 38, 12, C_GRAY)
        # Autosave HUD indicator: a freshly-flashed "Auto-saved Xs ago" toast
        # appears next to the title row whenever the snapshot was just written,
        # then fades to a steady "Last autosave Xs ago" reading.
        if last_autosave_secs is not None:
            try:
                import time as _time
                ago = max(0, int(_time.time() - last_autosave_secs))
            except Exception:
                ago = 0
            if ago < 60:
                ago_str = f"{ago}s ago"
            elif ago < 3600:
                ago_str = f"{ago // 60}m ago"
            else:
                ago_str = f"{ago // 3600}h ago"
            if autosave_toast_frames > 0:
                col = (140, 230, 140)
                label = f"Auto-saved {ago_str}"
            else:
                col = (130, 130, 150)
                label = f"Last autosave {ago_str}"
            txt(screen, label, WIDTH - 230, BAR_Y + 54, 11, col)
        # One short hint line above the button row — the full list
        # lives behind "?" / F1 / "/". Two-line variants intersected the
        # button row and read as overlapping UI (UI_AUDIT §11).
        txt(screen,
            "Press ? for shortcuts  ·  Tab: categories  ·  1–9: pick",
            WIDTH // 2, BAR_Y - 14, 11, C_GRAY, True)
        if msg_timer > 0:
            txt(screen, msg, WIDTH // 2, BAR_Y - 18, 18, C_PLAYER, True)
        # ---- Palette hover tooltip ---------------------------------------
        if hovered_item is not None:
            name = TYPE_NAMES.get(hovered_item, "")
            tip = TYPE_TIPS.get(hovered_item, "")
            if name or tip:
                tip_w = 260
                tip_x = min(WIDTH - tip_w - 8, max(8, mx - tip_w // 2))
                tip_y = TOP_H + 6
                tip_h = 40 if tip else 22
                rr = pygame.Rect(tip_x, tip_y, tip_w, tip_h)
                pygame.draw.rect(screen, (10, 8, 24), rr, border_radius=6)
                pygame.draw.rect(screen, (90, 110, 190), rr, 1, border_radius=6)
                txt(screen, name, rr.x + 8, rr.y + 4, 14, C_WHITE)
                if tip:
                    txt(screen, tip, rr.x + 8, rr.y + 22, 11, C_GRAY)
        # Keyboard cheat sheet — toggled with `?` / F1 / `/`.
        if show_shortcuts:
            _draw_editor_cheat_sheet(screen)
        pygame.display.flip()
        clock.tick(settings.get_fps_cap())
