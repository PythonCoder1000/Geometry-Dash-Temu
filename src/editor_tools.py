"""Per-tool behaviour for the level editor's canvas.

The editor exposes five canvas tools (Brush / Erase / Group / Edit / Bot Path).
Each one can act at up to three distinct moments:

  * ``on_click``   — a fresh left-click landed on the canvas
  * ``on_hold``    — the left button is held and dragged across cells
  * ``on_preview`` — the per-frame cursor ghost drawn under the mouse

Those three moments used to be three separate ``if tool == ...`` chains
scattered a thousand lines apart inside ``_run_editor_impl``. Adding or
changing a tool meant editing all three, and whenever one copy drifted the
tool behaved differently depending on whether you clicked, dragged, or just
hovered. :data:`TOOL_HANDLERS` is the single table those three call sites now
dispatch through, so a tool is defined in exactly one place.

Handlers take explicit keyword parameters — there is no shared editor-state
object. Because a callee cannot rebind its caller's locals, ``on_click`` and
``on_hold`` report state changes by returning a result object whose unset
fields are the :data:`KEEP` sentinel; the editor applies only the fields that
actually changed.

The snippet "stamp" (:func:`stamp_click` / :func:`stamp_preview`) is not a
tool — it pre-empts whichever tool is active while armed — so it lives beside
the table rather than in it.
"""

import pygame

from .constants import C_WHITE, T_TELEPORT_ORB
from .graphics import draw_obj, obj_scale
from .levels import next_group_id
from .editor import (
    TOOL_BRUSH, TOOL_ERASE, TOOL_GROUP, TOOL_EDIT, TOOL_BOT_PATH,
    objects_at_cell,
    _place_object as place_object,
    _erase_at as erase_at,
    _link_click as link_click,
    _clone_objects as clone_objects,
)


class KeepSentinel:
    """Marker meaning 'this handler did not touch that piece of state'."""

    def __repr__(self):
        return "KEEP"


KEEP = KeepSentinel()


class ToolClickResult:
    """State the editor should adopt after a canvas click.

    Every field defaults to :data:`KEEP`, so a handler only names what it
    actually changed and the editor leaves the rest of its locals alone.
    ``message`` is a ``(text, frames)`` pair.
    """

    __slots__ = ("selected_objs", "last_edit_cell", "last_brush_cell",
                 "current_group_id", "pending_link", "drag_mode",
                 "drag_start_screen", "drag_rubber_shift", "drag_anchor_cell",
                 "drag_positions", "drag_moved", "bot_exact_inputs",
                 "bot_mirror_waypoints", "snippet_stamp",
                 "snippet_stamp_name", "message")

    def __init__(self, **changes):
        for name in self.__slots__:
            setattr(self, name, changes.pop(name, KEEP))
        if changes:
            raise TypeError(f"unknown ToolClickResult fields: {sorted(changes)}")


class ToolHoldResult:
    """State the editor should adopt after a held-mouse paint step.

    ``changed`` says whether the level was actually mutated (the editor uses
    it to flip its dirty / unsaved flags).
    """

    __slots__ = ("changed", "last_brush_cell")

    def __init__(self, changed=False, last_brush_cell=KEEP):
        self.changed = changed
        self.last_brush_cell = last_brush_cell


# --- Brush -----------------------------------------------------------------

def brush_click(*, objects, gx, gy, mx, my, cam_x, cam_y, zoom_level,
                selected_type, current_rotation, current_group_id,
                selected_objs, last_edit_cell, pending_link, bot_waypoints,
                push_undo):
    push_undo()
    gid = current_group_id if selected_type == T_TELEPORT_ORB else 0
    place_object(objects, gx, gy, selected_type, current_rotation, gid)
    # Mark this cell as already stamped so the held-mouse loop later in the
    # same frame doesn't re-stamp it (one click was producing two objects
    # since same-type stacking was opened up).
    result = ToolClickResult(last_brush_cell=(gx, gy))
    if selected_type == T_TELEPORT_ORB:
        result.current_group_id = next_group_id(objects)
    return result


def brush_hold(*, objects, gx, gy, selected_type, current_rotation,
               current_group_id, last_brush_cell):
    # Skip if we already stamped this cell on the current mouse-hold —
    # drag-to-paint still flows across cells because the cell key changes each
    # grid step, but holding still on one cell stops re-stamping after the
    # first frame.
    if (gx, gy) == last_brush_cell:
        return ToolHoldResult()
    gid = current_group_id if selected_type == T_TELEPORT_ORB else 0
    place_object(objects, gx, gy, selected_type, current_rotation, gid)
    return ToolHoldResult(changed=True, last_brush_cell=(gx, gy))


def brush_preview(*, screen, sx, sy, mx, my, effective_cell, cam_x, cam_y,
                  zoom_level, pulse, selected_type, current_rotation,
                  bot_waypoints):
    ghost = pygame.Surface((effective_cell, effective_cell), pygame.SRCALPHA)
    ghost.set_alpha(130)
    draw_obj(ghost, selected_type, 0, 0, effective_cell, pulse,
             current_rotation)
    screen.blit(ghost, (sx, sy))
    pygame.draw.rect(screen, C_WHITE, (sx, sy, effective_cell, effective_cell),
                     1)


# --- Erase -----------------------------------------------------------------

def erase_click(*, objects, gx, gy, mx, my, cam_x, cam_y, zoom_level,
                selected_type, current_rotation, current_group_id,
                selected_objs, last_edit_cell, pending_link, bot_waypoints,
                push_undo):
    push_undo()
    erase_at(objects, gx, gy)
    return ToolClickResult()


def erase_hold(*, objects, gx, gy, selected_type, current_rotation,
               current_group_id, last_brush_cell):
    erase_at(objects, gx, gy)
    return ToolHoldResult(changed=True)


def erase_preview(*, screen, sx, sy, mx, my, effective_cell, cam_x, cam_y,
                  zoom_level, pulse, selected_type, current_rotation,
                  bot_waypoints):
    red = (255, 80, 80)
    pygame.draw.rect(screen, red, (sx, sy, effective_cell, effective_cell), 2)
    pygame.draw.line(screen, red, (sx + 8, sy + 8),
                     (sx + effective_cell - 8, sy + effective_cell - 8), 2)
    pygame.draw.line(screen, red, (sx + effective_cell - 8, sy + 8),
                     (sx + 8, sy + effective_cell - 8), 2)


# --- Group -----------------------------------------------------------------

def group_click(*, objects, gx, gy, mx, my, cam_x, cam_y, zoom_level,
                selected_type, current_rotation, current_group_id,
                selected_objs, last_edit_cell, pending_link, bot_waypoints,
                push_undo):
    new_pending, message = link_click(objects, gx, gy, pending_link)
    return ToolClickResult(pending_link=new_pending, message=(message, 110))


def group_preview(*, screen, sx, sy, mx, my, effective_cell, cam_x, cam_y,
                  zoom_level, pulse, selected_type, current_rotation,
                  bot_waypoints):
    pygame.draw.rect(screen, (200, 160, 255),
                     (sx, sy, effective_cell, effective_cell), 2)


# --- Edit ------------------------------------------------------------------

def edit_click(*, objects, gx, gy, mx, my, cam_x, cam_y, zoom_level,
               selected_type, current_rotation, current_group_id,
               selected_objs, last_edit_cell, pending_link, bot_waypoints,
               push_undo):
    shift_held = bool(pygame.key.get_mods() & pygame.KMOD_SHIFT)
    stack = objects_at_cell(objects, gx, gy)
    top = stack[-1] if stack else None
    if shift_held and top:
        selection = list(selected_objs)
        if top in selection:
            selection.remove(top)
        else:
            selection.append(top)
        return ToolClickResult(selected_objs=selection, last_edit_cell=None,
                               message=(f"{len(selection)} selected", 70))
    if shift_held:
        return ToolClickResult(drag_mode="rubber", drag_start_screen=(mx, my),
                               drag_rubber_shift=True)
    if top and top in selected_objs and len(selected_objs) > 1:
        return ToolClickResult(
            drag_mode="move",
            drag_anchor_cell=(gx, gy),
            drag_positions={id(o): (o["x"], o["y"]) for o in selected_objs},
            drag_moved=False,
            last_edit_cell=None,
        )
    if top:
        if (last_edit_cell == (gx, gy) and len(selected_objs) == 1
                and selected_objs[0] in stack):
            idx = (stack.index(selected_objs[0]) + 1) % len(stack)
            selection = [stack[idx]]
        else:
            selection = [top]
        result = ToolClickResult(
            selected_objs=selection,
            last_edit_cell=(gx, gy),
            drag_mode="move",
            drag_anchor_cell=(gx, gy),
            drag_positions={id(o): (o["x"], o["y"]) for o in selection},
            drag_moved=False,
        )
        if len(stack) > 1:
            result.message = (
                f"Stack {stack.index(selection[0]) + 1}/{len(stack)}"
                " — click again to cycle", 120)
        return result
    return ToolClickResult(selected_objs=[], last_edit_cell=None,
                           drag_mode="rubber", drag_start_screen=(mx, my),
                           drag_rubber_shift=False)


def edit_preview(*, screen, sx, sy, mx, my, effective_cell, cam_x, cam_y,
                 zoom_level, pulse, selected_type, current_rotation,
                 bot_waypoints):
    pygame.draw.rect(screen, (120, 255, 140),
                     (sx, sy, effective_cell, effective_cell), 1)


# --- Bot path --------------------------------------------------------------

def bot_path_click(*, objects, gx, gy, mx, my, cam_x, cam_y, zoom_level,
                   selected_type, current_rotation, current_group_id,
                   selected_objs, last_edit_cell, pending_link, bot_waypoints,
                   push_undo):
    bot_waypoints.append(((mx + cam_x) / zoom_level, (my + cam_y) / zoom_level))
    # Manual editing invalidates the autobot pairing.
    return ToolClickResult(
        bot_exact_inputs=None,
        bot_mirror_waypoints=[],
        message=(f"Bot path: {len(bot_waypoints)} pts"
                 " (K=run, R-click=undo)", 90),
    )


def bot_path_preview(*, screen, sx, sy, mx, my, effective_cell, cam_x, cam_y,
                     zoom_level, pulse, selected_type, current_rotation,
                     bot_waypoints):
    amber = (255, 180, 60)
    pygame.draw.circle(screen, amber, (mx, my), 6, 2)
    if bot_waypoints:
        last_sx = int(bot_waypoints[-1][0] * zoom_level - cam_x)
        last_sy = int(bot_waypoints[-1][1] * zoom_level - cam_y)
        pygame.draw.line(screen, amber, (last_sx, last_sy), (mx, my), 1)


TOOL_HANDLERS = {
    TOOL_BRUSH: {"on_click": brush_click, "on_hold": brush_hold,
                 "on_preview": brush_preview},
    TOOL_ERASE: {"on_click": erase_click, "on_hold": erase_hold,
                 "on_preview": erase_preview},
    TOOL_GROUP: {"on_click": group_click, "on_preview": group_preview},
    TOOL_EDIT: {"on_click": edit_click, "on_preview": edit_preview},
    TOOL_BOT_PATH: {"on_click": bot_path_click,
                    "on_preview": bot_path_preview},
}


# --- Snippet stamp (pre-empts the active tool while armed) ------------------

def stamp_click(*, objects, gx, gy, snippet_stamp, snippet_stamp_name,
                push_undo):
    """Drop a fresh-id clone of the armed stamp anchored at the cursor cell.

    The stamp stays armed so the user can place multiple copies; Esc cancels.
    Shift drops then disarms — handy for "place once and continue".
    """
    push_undo()
    new_objs = clone_objects(snippet_stamp, (gx, gy), objects)
    objects.extend(new_objs)
    result = ToolClickResult(selected_objs=list(new_objs), last_edit_cell=None)
    placed = f"Stamped {snippet_stamp_name} ({len(new_objs)} obj)"
    if pygame.key.get_mods() & pygame.KMOD_SHIFT:
        result.snippet_stamp = None
        result.snippet_stamp_name = ""
        result.message = (placed, 120)
    else:
        result.message = (
            placed + " — click to repeat, Esc to cancel", 120)
    return result


def stamp_preview(*, screen, sx, sy, gx, gy, effective_cell, cam_x, cam_y,
                  pulse, snippet_stamp):
    """Translucent ghost of every stamp object, anchored to the cursor cell.

    Shows exactly where each piece will land, plus a bounding-box outline of
    the footprint.
    """
    stamp_xs = [o["x"] for o in snippet_stamp]
    stamp_ys = [o["y"] for o in snippet_stamp]
    min_sx = min(stamp_xs) if stamp_xs else 0
    min_sy = min(stamp_ys) if stamp_ys else 0
    max_sx = max(stamp_xs) if stamp_xs else 0
    max_sy = max(stamp_ys) if stamp_ys else 0
    for so in snippet_stamp:
        cx = (gx + so["x"] - min_sx) * effective_cell - cam_x
        cy = (gy + so["y"] - min_sy) * effective_cell - cam_y
        ghost = pygame.Surface((effective_cell, effective_cell),
                               pygame.SRCALPHA)
        ghost.set_alpha(140)
        draw_obj(ghost, so["t"], 0, 0, effective_cell, pulse, so.get("r", 0),
                 scale=obj_scale(so))
        screen.blit(ghost, (cx, cy))
    bw = (max_sx - min_sx + 1) * effective_cell
    bh = (max_sy - min_sy + 1) * effective_cell
    pygame.draw.rect(screen, (160, 220, 255), (sx, sy, bw, bh), 1)
