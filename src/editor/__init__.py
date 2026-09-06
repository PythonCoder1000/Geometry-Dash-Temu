"""Level editor package (GD-style Build / Edit / Delete editor).

``ops``      pure object-list operations (place, clone, flip, link, ...)
``state``    EditorState + layout constants
``ui``       top bar, side strip, bottom bar widgets
``props``    registry-driven property panel
``render``   canvas + overlay drawing
``dialogs``  exit / crash modals, shortcut sheet
``session``  EditorSession: input routing, actions, frame loop
"""

from .session import run_editor, EditorSession
from .state import (
    EditorState, MODE_BUILD, MODE_EDIT, MODE_DELETE, TOOL_SELECT, TOOL_LINK,
    TOOL_BOT_PATH, TOP_H, BAR_Y, SIDE_W,
)
from .ops import (
    objects_at_cell, object_at_cell, initial_objects, place_object, erase_at,
    clone_objects, link_click, link_confirm_targets, export_level_png,
    rotate_objects, flip_objects, nudge_objects, scale_objects,
)
from .dialogs import show_error_modal, confirm_exit

# Historical names kept for callers / tests.
_show_error_modal = show_error_modal
_confirm_exit = confirm_exit
_clone_objects = clone_objects
_place_object = place_object
_erase_at = erase_at
_link_click = link_click
_initial_objects = initial_objects
_export_level_png = export_level_png

__all__ = [
    "run_editor", "EditorSession", "EditorState",
    "MODE_BUILD", "MODE_EDIT", "MODE_DELETE", "TOOL_SELECT", "TOOL_LINK",
    "TOOL_BOT_PATH", "TOP_H", "BAR_Y", "SIDE_W",
    "objects_at_cell", "object_at_cell", "initial_objects", "place_object",
    "erase_at", "clone_objects", "link_click", "link_confirm_targets",
    "export_level_png", "rotate_objects", "flip_objects", "nudge_objects",
    "scale_objects", "show_error_modal", "confirm_exit",
]
