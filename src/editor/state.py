"""Editor session state: level data, camera, mode, selection, history."""

from ..constants import CELL, WIDTH, HEIGHT
from ..objects import PALETTE_CATEGORIES
from . import ops

MODE_BUILD = "build"
MODE_EDIT = "edit"
MODE_DELETE = "delete"
MODES = (MODE_BUILD, MODE_EDIT, MODE_DELETE)

# Sub-tools available while in Edit mode.
TOOL_SELECT = "select"
TOOL_LINK = "link"
TOOL_BOT_PATH = "bot_path"
TOOL_MUSIC_PREVIEW = "music_preview"

ZOOM_MIN = 0.3
ZOOM_MAX = 3.0

# Layout (also used by render / ui).
TOP_H = 44
BOTTOM_H = 150
BAR_Y = HEIGHT - BOTTOM_H
SIDE_W = 56


class EditorState:
    """All mutable editor state.  Kept as plain attributes so the
    session methods read naturally (``st.zoom``) and tests can poke."""

    def __init__(self, objects):
        # ---- level ---------------------------------------------------
        self.objects = objects
        self.level_name = "Untitled"
        self.level_music = None
        self.level_filename = None
        self.level_meta = None
        # ---- history / dirty tracking --------------------------------
        self.undo_stack = []
        self.redo_stack = []
        self.dirty = False               # autosave needs a write
        self.unsaved_changes = False     # exit warning
        self.autosave_timer = 0
        self.autosave_toast_frames = 0
        self.last_autosave_secs = None
        # ---- camera --------------------------------------------------
        self.cam_x = 0.0
        self.cam_y = 0.0
        self.zoom = 1.0
        self.show_grid = True
        self.show_hitboxes = False
        # ---- mode / tools --------------------------------------------
        self.mode = MODE_BUILD
        self.edit_tool = TOOL_SELECT
        self.swipe = True
        self.rotate_drag = False
        self.free_move = False
        self.delete_filter = False       # delete only the active build type
        self.noclip = False              # test-play invincibility (editor only)
        self.music_preview_offset = None  # seconds; None when not previewing
        self.active_cat = 0
        self.palette_page = 0
        self.selected_type = PALETTE_CATEGORIES[0][1][0]
        self.rotation = 0                # brush rotation
        self.group_id_counter = 1
        # ---- selection / interaction ---------------------------------
        self.selected = []
        self.last_edit_cell = None
        self.last_brush_cell = None
        self.pending_link = None
        self.clipboard = []
        self.props_open = False
        self.drag = None                 # dict describing the live drag
        self.curve_drag_idx = None
        self.snippet_stamp = None
        self.snippet_stamp_name = ""
        # ---- bots ----------------------------------------------------
        self.bot_waypoints = []
        self.bot_mirror_waypoints = []
        self.bot_exact_inputs = None
        self.last_run_hitboxes = []
        self.last_run_mirror_hitboxes = []
        # ---- UI ------------------------------------------------------
        self.msg = ""
        self.msg_timer = 0
        self.pulse = 0
        self.show_shortcuts = False

    # ---- helpers -------------------------------------------------------
    @property
    def eff_cell(self):
        return max(1, int(CELL * self.zoom))

    def screen_to_cell(self, mx, my):
        e = self.eff_cell
        return int((mx + self.cam_x) // e), int((my + self.cam_y) // e)

    def screen_to_world(self, mx, my):
        return (mx + self.cam_x) / self.zoom, (my + self.cam_y) / self.zoom

    def cell_to_screen(self, gx, gy):
        e = self.eff_cell
        return gx * e - self.cam_x, gy * e - self.cam_y

    def center_on_cell(self, gx, gy):
        """Put a grid cell in the middle of the visible canvas."""
        e = self.eff_cell
        self.cam_x = (gx + 0.5) * e - WIDTH / 2
        self.cam_y = (gy + 0.5) * e - (TOP_H + BAR_Y) / 2

    def say(self, text, frames=90):
        self.msg = text
        self.msg_timer = frames

    def mark_dirty(self):
        self.dirty = True
        self.unsaved_changes = True

    def push_undo(self):
        ops.push_undo(self.undo_stack, self.redo_stack, self.objects)
        self.mark_dirty()

    def undo(self):
        if not self.undo_stack:
            return False
        self.redo_stack.append(ops.snapshot(self.objects))
        self.objects[:] = self.undo_stack.pop()
        self.clear_selection()
        self.mark_dirty()
        return True

    def redo(self):
        if not self.redo_stack:
            return False
        self.undo_stack.append(ops.snapshot(self.objects))
        self.objects[:] = self.redo_stack.pop()
        self.clear_selection()
        self.mark_dirty()
        return True

    def clear_selection(self):
        self.selected = []
        self.last_edit_cell = None
        self.drag = None
        self.props_open = False
        self.curve_drag_idx = None

    def prune_selection(self):
        if self.selected:
            live = {id(o) for o in self.objects}
            self.selected = [o for o in self.selected if id(o) in live]
        if not self.selected:
            self.last_edit_cell = None
            self.props_open = False

    def set_zoom(self, new_zoom, anchor=None):
        """Zoom keeping the world point under ``anchor`` fixed."""
        new_zoom = max(ZOOM_MIN, min(ZOOM_MAX, round(new_zoom, 2)))
        if anchor is None:
            anchor = (WIDTH // 2, (TOP_H + BAR_Y) // 2)
        eff_old = self.eff_cell
        eff_new = max(1, int(CELL * new_zoom))
        ax, ay = anchor
        wx = (ax + self.cam_x) / eff_old
        wy = (ay + self.cam_y) / eff_old
        self.zoom = new_zoom
        self.cam_x = wx * eff_new - ax
        self.cam_y = wy * eff_new - ay

    def palette_items(self):
        return PALETTE_CATEGORIES[self.active_cat][1]

    def set_category(self, idx):
        self.active_cat = idx % len(PALETTE_CATEGORIES)
        self.palette_page = 0
        self.selected_type = self.palette_items()[0]
