"""The level editor session: input routing, actions and the frame loop.

Layout (GD style)::

    +------------------------------------------------------------------+
    | Menu  Test  Bot          level · status         Undo Redo Save … |
    +----+-------------------------------------------------------------+
    |Swp |                                             [property panel] |
    |Rot |                     canvas                                   |
    |Free|                                                              |
    |Grid|                                                              |
    +----+-------------------------------------------------------------+
    |BUILD | category tabs / object pages           (build)             |
    |EDIT  | rotate flip scale copy paste … nudge  (edit)               |
    |DELETE| delete selected / all of type / filter (delete)            |
    +------------------------------------------------------------------+
"""

import math
import os
import time
import traceback

import pygame

from ..constants import (
    WIDTH, FPS, LEVELS_DIR, T_START, T_TELEPORT_ORB,
)
from ..graphics import make_stars, make_mountains
from ..input_guard import ClickGuard
from ..levels import (
    save_level, load_level_full, next_group_id,
    save_autosave, load_autosave, has_autosave, clear_autosave,
    _default_meta,
)
from ..menus import (
    text_input_dialog, load_level_dialog, difficulty_picker, confirm_dialog,
    snippet_picker,
)
from ..objects import TYPE_NAMES, cycle_active_start, start_objects
from ..play import run_play
from ..snippets import save_user_snippet, normalize_to_origin
from .. import music, sfx, settings, prefs
from . import ops, ui, render, music_names
from .dialogs import confirm_exit, show_error_modal, draw_shortcuts
from .props import PropPanel
from .state import (
    EditorState, MODE_BUILD, MODE_EDIT, MODE_DELETE, TOOL_SELECT, TOOL_LINK,
    TOOL_BOT_PATH, TOP_H, BAR_Y, SIDE_W,
)

AUTOSAVE_INTERVAL = 30 * FPS     # frames between autosaves while dirty
AUTOSAVE_FLASH_FRAMES = 90
ROTATE_SNAP_DEG = 15
PAN_SPEED = 11


def run_editor(screen, clock, preload_filename=None):
    """Editor entry point; a crash inside becomes a modal, never a dead
    process (the autosave is on disk)."""
    try:
        return EditorSession(screen, clock, preload_filename).run()
    except SystemExit:
        raise
    except Exception as exc:
        traceback.print_exc()
        show_error_modal(screen, clock, exc, where="editor")
        try:
            music.stop()
        except Exception:
            pass
        return None


class EditorSession:
    def __init__(self, screen, clock, preload_filename=None):
        self.screen = screen
        self.clock = clock
        music.stop()
        self.st = EditorState(ops.initial_objects())
        self.stars = make_stars()
        self.mountains = make_mountains()
        self.guard = ClickGuard()
        self.panel = PropPanel()
        self.top_buttons = []
        self.side_buttons = []
        self.bottom_buttons = []
        self.pending = []            # deferred actions run after the event loop
        self.mpos = (0, 0)
        self._right_press = None     # (pos, cell) for right-click erase
        if preload_filename:
            self._load_path(os.path.join(LEVELS_DIR, preload_filename), quiet=True)
        elif has_autosave():
            self._offer_autosave()

    # ------------------------------------------------------------------
    # Level I/O
    # ------------------------------------------------------------------
    def _adopt_level(self, meta, objects, filename):
        st = self.st
        st.objects[:] = objects
        st.level_meta = meta
        st.level_name = meta.get("name", "Untitled") if meta else "Untitled"
        st.level_music = meta.get("music") if meta else None
        st.level_filename = filename
        st.undo_stack = []
        st.redo_stack = []
        st.pending_link = None
        st.clear_selection()
        st.dirty = False
        st.unsaved_changes = False
        st.autosave_timer = 0
        st.group_id_counter = next_group_id(st.objects)
        # A bot path belongs to the level it was solved for.
        self.clear_bot_path()

    def _load_path(self, path, quiet=False):
        try:
            meta, objs = load_level_full(path)
        except (OSError, ValueError) as err:
            if not quiet:
                self.st.say(f"Load failed: {err}", 180)
            return False
        self._adopt_level(meta, objs, os.path.basename(path))
        clear_autosave()
        if not quiet:
            self.st.say(f"Loaded: {self.st.level_name}", 120)
        return True

    def _offer_autosave(self):
        try:
            ameta, aobjs = load_autosave()
        except Exception:
            ameta, aobjs = None, None
        if ameta and aobjs is not None:
            src = ameta.get("_autosave_source") or "(never saved)"
            ts = ameta.get("_autosave_ts", 0)
            age = max(0, int(time.time()) - int(ts)) if ts else None
            age_str = ("" if age is None else f"{age}s ago" if age < 60
                       else f"{age // 60}m ago" if age < 3600 else f"{age // 3600}h ago")
            subtitle = f'"{ameta.get("name", "Untitled")}" · slot {src} · {age_str}'.strip(" ·")
            if confirm_dialog(self.screen, self.clock, "Recover unsaved editor work?",
                              subtitle=subtitle, ok_label="Recover", cancel_label="Discard"):
                clean = {k: v for k, v in ameta.items() if not k.startswith("_autosave_")}
                self._adopt_level(clean, aobjs, (ameta.get("_autosave_source") or None))
                self.st.dirty = True
                self.st.unsaved_changes = True
        clear_autosave()

    def autosave_now(self):
        st = self.st
        try:
            save_autosave(st.objects, st.level_name, music_file=st.level_music,
                          meta=st.level_meta, source_filename=st.level_filename or "")
        except OSError:
            return False
        st.dirty = False
        st.autosave_toast_frames = AUTOSAVE_FLASH_FRAMES
        st.last_autosave_secs = time.time()
        return True

    def _owned_by_other(self, verb):
        cu = prefs.get("signed_in_username", None)
        author = (self.st.level_meta or {}).get("author", "") or ""
        if cu and author and author not in (cu, "Player"):
            self.st.say(f"Can't {verb} — owned by {author}.", 180)
            return True
        return False

    def _stamp_author(self, meta):
        cu = prefs.get("signed_in_username", None)
        if cu and (meta.get("author") or "").strip() in ("", "Player"):
            meta["author"] = cu

    def _reload_meta(self):
        try:
            self.st.level_meta, _ = load_level_full(
                os.path.join(LEVELS_DIR, self.st.level_filename))
        except (OSError, ValueError):
            pass

    def _after_disk_save(self, msg):
        st = self.st
        clear_autosave()
        st.dirty = False
        st.unsaved_changes = False
        st.autosave_timer = 0
        st.say(msg, 150)

    def do_save(self):
        st = self.st
        if self._owned_by_other("save"):
            return
        name = self.ask_text("Level name:", st.level_name)
        if not name:
            return
        st.level_name = name
        fn = name.lower().replace(" ", "_")
        meta = dict(st.level_meta) if st.level_meta else _default_meta(name)
        meta["name"] = name
        self._stamp_author(meta)
        save_level(st.objects, name, fn, music_file=st.level_music, meta=meta)
        st.level_filename = fn + ".json"
        self._reload_meta()
        self._after_disk_save(f"Saved as {fn}.json")

    def do_publish(self):
        st = self.st
        if self._owned_by_other("publish"):
            return
        name = st.level_name
        if not st.level_filename:
            name = self.ask_text("Publish as:", st.level_name)
            if not name:
                return
        cur_req = (st.level_meta or {}).get("requested_difficulty",
                                            (st.level_meta or {}).get("difficulty", "Normal"))
        req = difficulty_picker(self.screen, self.clock, prompt="Request a difficulty:",
                                default=cur_req,
                                subtitle="The verifier will confirm or change this when they beat it.")
        self.guard.reset()
        if req is None:
            st.say("Publish cancelled", 120)
            return
        fn = (st.level_filename.replace(".json", "") if st.level_filename
              else name.lower().replace(" ", "_"))
        meta = dict(st.level_meta) if st.level_meta else _default_meta(name)
        meta.update(name=name, published=True, requested_difficulty=req,
                    verified=False, rated=False, suggested_difficulty="",
                    difficulty=req)
        self._stamp_author(meta)
        st.level_name = name
        save_level(st.objects, name, fn, music_file=st.level_music, meta=meta)
        st.level_filename = fn + ".json"
        st.level_meta = meta
        self._reload_meta()
        self._after_disk_save(f"Published {fn}.json as {req} — awaiting verification")

    def do_load(self):
        path = load_level_dialog(self.screen, self.clock)
        self.guard.reset()
        if path:
            self._load_path(path)

    # ------------------------------------------------------------------
    # Play / bots
    # ------------------------------------------------------------------
    def _run(self, suffix, **kw):
        st = self.st
        st.last_run_hitboxes.clear()
        st.last_run_mirror_hitboxes.clear()
        run_play(self.screen, self.clock, list(st.objects), st.level_name + suffix,
                 editor_test=True, level_music=st.level_music, meta=st.level_meta,
                 out_hitboxes=st.last_run_hitboxes,
                 out_mirror_hitboxes=st.last_run_mirror_hitboxes, **kw)
        self.guard.reset()

    def do_test(self, from_cursor=False):
        start_x = None
        if from_cursor:
            start_x = int(self.st.screen_to_world(*self.mpos)[0])
        self._run(" (Test)" + (" @cursor" if start_x else ""), start_x=start_x)

    def do_bot(self):
        """K: replay exact inputs, else drive the drawn waypoint path,
        else play back the saved input file."""
        from ..bots import PathFollowController, load_bot_inputs
        st = self.st
        if st.bot_exact_inputs:
            self._run(" (Bot Exact)", playback_inputs=st.bot_exact_inputs,
                      playback_waypoints=list(st.bot_waypoints) or None)
            st.say(f"Exact playback done — {len(st.bot_exact_inputs)} frames", 180)
        elif st.bot_waypoints:
            bot = PathFollowController(list(st.bot_waypoints),
                                       objects=list(st.objects))
            self._run(" (Bot)", bot_controller=bot)
            bot.save_inputs()
            st.say(f"Bot done — {len(bot.inputs)} frames saved to level_bot_inputs.txt", 180)
        else:
            inputs = load_bot_inputs()
            if inputs:
                self._run(" (Playback)", playback_inputs=inputs)
                st.say(f"Playback done — {len(inputs)} frames", 120)
            else:
                st.say("Draw a bot path first (Edit > Bot Path) or solve one (Bot menu)", 150)

    def clear_bot_path(self):
        """Drop every trace of a solved/drawn bot path: the overlay the
        editor draws, the exact inputs K replays, and the bot menu's
        cached result (which also seeds and gates the next solve)."""
        from ..bot_menu import clear_last_solve
        st = self.st
        st.bot_waypoints = []
        st.bot_mirror_waypoints = []
        st.bot_exact_inputs = None
        st.last_run_hitboxes.clear()
        st.last_run_mirror_hitboxes.clear()
        clear_last_solve()

    def do_bot_menu(self):
        from ..bot_menu import run_bot_menu, get_last_inputs, get_last_mirror_waypoints
        st = self.st

        def replay(inputs):
            self._run(" (Bot Replay)", playback_inputs=inputs,
                      playback_waypoints=list(st.bot_waypoints) or None)

        result = run_bot_menu(self.screen, self.clock, list(st.objects),
                              precomputed_path=st.bot_waypoints or None,
                              drawn_path=list(st.bot_waypoints) or None,
                              allow_replay=True, replay_callback=replay,
                              level_filename=st.level_filename, meta=st.level_meta)
        self.guard.reset()
        if result is not None:
            wp, status = result
            if status == "cleared":
                self.clear_bot_path()
                st.say("Bot path cleared", 150)
            elif wp:
                st.bot_waypoints = list(wp)
                st.bot_mirror_waypoints = get_last_mirror_waypoints()
                st.bot_exact_inputs = get_last_inputs() or st.bot_exact_inputs
                st.mode = MODE_EDIT
                st.say(f"Bot path ready ({status}) — {len(st.bot_waypoints)} waypoints", 200)

    # ------------------------------------------------------------------
    # Small helpers
    # ------------------------------------------------------------------
    def ask_text(self, prompt, default=""):
        typed = text_input_dialog(self.screen, self.clock, prompt, default)
        self.guard.reset()
        return typed

    def in_canvas(self, pos):
        x, y = pos
        return (TOP_H < y < BAR_Y and x > SIDE_W
                and not (self.st.props_open and self.panel.contains(pos)))

    def _select_type(self, t):
        st = self.st
        st.selected_type = t
        if t == T_TELEPORT_ORB:
            st.group_id_counter = next_group_id(st.objects)

    def _set_mode(self, mode):
        st = self.st
        if st.mode != mode:
            st.mode = mode
            st.pending_link = None
            st.drag = None
            if mode != MODE_EDIT:
                st.clear_selection()
                st.edit_tool = TOOL_SELECT

    def _delete_selection(self):
        st = self.st
        if not st.selected:
            return
        st.push_undo()
        n = len(st.selected)
        ops.remove_objects(st.objects, st.selected)
        st.clear_selection()
        st.say(f"Deleted {n} object{'s' if n != 1 else ''}", 80)

    def _cycle_start_pos(self, delta):
        """1 / 2 (outside Build mode, where 1-9 pick palette items): make
        the previous / next Start Pos the active spawn, jump the camera to
        it and show it in the property panel."""
        st = self.st
        starts = start_objects(st.objects)
        if not starts:
            st.say("No Start Pos placed", 90)
            return
        if len(starts) == 1:
            st.center_on_cell(starts[0]["x"], starts[0]["y"])
            st.say("Only one Start Pos in this level", 90)
            return
        st.push_undo()
        new_start = cycle_active_start(st.objects, delta)
        st.center_on_cell(new_start["x"], new_start["y"])
        was_open = st.props_open
        st.selected = [new_start]
        st.props_open = was_open
        idx = next(i for i, o in enumerate(start_objects(st.objects))
                   if o is new_start)
        st.say(f"Start Pos {idx + 1}/{len(starts)} active "
               f"(cell {new_start['x']}, {new_start['y']})", 120)

    def _start_link_on(self, obj):
        st = self.st
        st.mode = MODE_EDIT
        st.edit_tool = TOOL_LINK
        st.pending_link, msg = ops.link_click(st.objects, obj["x"], obj["y"], None)
        st.say(msg, 120)

    # ------------------------------------------------------------------
    # Actions (buttons, keys, panel)
    # ------------------------------------------------------------------
    def do(self, action, arg=None):
        st = self.st
        sel = st.selected
        mods = pygame.key.get_mods()
        big = bool(mods & pygame.KMOD_CTRL)
        if action == "mode":
            self._set_mode(arg)
        elif action == "category":
            st.set_category(arg)
        elif action == "pick":
            self._select_type(arg)
        elif action == "page":
            st.palette_page = max(0, st.palette_page + arg)
        elif action in ("brush_rot", "brush_rot_cw"):
            st.rotation = (st.rotation + 90) % 360
        elif action == "brush_rot_ccw":
            st.rotation = (st.rotation - 90) % 360
        elif action == "rot" and sel:
            st.push_undo()
            ops.rotate_objects(sel, arg, about_center=True)
        elif action == "flip" and sel:
            st.push_undo()
            ops.flip_objects(sel, arg)
        elif action == "scale" and sel:
            st.push_undo()
            ops.scale_objects(sel, arg)
        elif action == "nudge" and sel:
            st.push_undo()
            k = 5 if big else 1
            ops.nudge_objects(sel, arg[0] * k, arg[1] * k)
        elif action == "copy" and sel:
            st.clipboard = ops.to_clipboard(sel)
            st.say(f"Copied {len(sel)} object{'s' if len(sel) != 1 else ''}", 80)
        elif action == "cut" and sel:
            st.clipboard = ops.to_clipboard(sel)
            self._delete_selection()
        elif action == "paste" and st.clipboard:
            gx, gy = (st.screen_to_cell(*self.mpos) if self.in_canvas(self.mpos)
                      else st.screen_to_cell(WIDTH // 2, (TOP_H + BAR_Y) // 2))
            st.push_undo()
            new = ops.clone_objects(st.clipboard, (gx, gy), st.objects)
            st.objects.extend(new)
            st.mode = MODE_EDIT
            st.selected = new
            st.say(f"Pasted {len(new)} object{'s' if len(new) != 1 else ''}", 80)
        elif action == "duplicate" and sel:
            st.push_undo()
            first = sel[0]
            new = ops.clone_objects(sel, (first["x"], first["y"]), st.objects)
            st.objects.extend(new)
            st.selected = new
            st.say(f"Duplicated {len(new)} in place — drag to move", 100)
        elif action == "select_all":
            st.mode = MODE_EDIT
            st.selected = [o for o in st.objects if o["t"] != T_START]
            st.say(f"Selected all ({len(st.selected)})", 80)
        elif action == "deselect":
            st.clear_selection()
        elif action == "toggle_invisible" and sel:
            st.push_undo()
            on = ops.toggle_flag(sel, "invisible")
            st.say(("Hid" if on else "Revealed") + f" {len(sel)} object(s)", 70)
        elif action == "toggle_bot_only" and sel:
            st.push_undo()
            on = ops.toggle_flag(sel, "_bot_only")
            st.say(f"Bot-only {'ON' if on else 'off'} ({len(sel)} obj)", 100)
        elif action == "delete_sel":
            self._delete_selection()
        elif action == "props":
            st.props_open = not st.props_open if sel else False
        elif action == "tool":
            st.edit_tool = TOOL_SELECT if st.edit_tool == arg else arg
            st.pending_link = None
        elif action == "snippet":
            pick = snippet_picker(self.screen, self.clock)
            self.guard.reset()
            if pick is not None:
                name, objs, _user = pick
                st.snippet_stamp = list(objs)
                st.snippet_stamp_name = name
                st.say(f"Stamp: {name} — click to place, Esc to cancel", 180)
        elif action == "save_snippet" and sel:
            name = self.ask_text("Snippet name:", "My Snippet")
            if name:
                objs = normalize_to_origin(sel)
                save_user_snippet(name, objs)
                st.say(f"Saved snippet '{name}' ({len(objs)} obj)", 150)
        elif action == "delete_type":
            t = st.selected_type
            victims = [o for o in st.objects if o["t"] == t]
            if victims:
                st.push_undo()
                ops.remove_objects(st.objects, victims)
                st.prune_selection()
                st.say(f"Deleted {len(victims)} x {TYPE_NAMES.get(t, t)}", 100)
            else:
                st.say(f"No {TYPE_NAMES.get(t, t)} in the level", 80)
        elif action == "clear":
            if confirm_dialog(self.screen, self.clock, "Clear the whole level?",
                              ok_label="Clear", cancel_label="Keep"):
                st.push_undo()
                st.objects[:] = []
                st.clear_selection()
                st.pending_link = None
                st.say("Cleared all objects", 90)
            self.guard.reset()
        elif action == "toggle_delete_filter":
            st.delete_filter = not st.delete_filter
        elif action == "toggle_swipe":
            st.swipe = not st.swipe
        elif action == "toggle_rotate":
            st.rotate_drag = not st.rotate_drag
        elif action == "toggle_free":
            st.free_move = not st.free_move
        elif action == "toggle_grid":
            st.show_grid = not st.show_grid
        elif action == "toggle_hitbox":
            st.show_hitboxes = not st.show_hitboxes
            n = len(st.last_run_hitboxes)
            st.say("Hitbox view " + ("ON" if st.show_hitboxes else "OFF")
                   + (f" ({n} frames)" if n else " — run Test or Bot to record"), 100)
        elif action == "zoom_in":
            st.set_zoom(st.zoom + 0.2)
        elif action == "zoom_out":
            st.set_zoom(st.zoom - 0.2)
        elif action == "zoom_reset":
            st.set_zoom(1.0)
        elif action == "help":
            st.show_shortcuts = not st.show_shortcuts
        elif action == "mute_music":
            music.toggle_mute()
        elif action == "mute_sfx":
            sfx.toggle_mute()
        elif action == "cycle_music":
            st.level_music, label = music_names.next_track(st.level_music)
            st.mark_dirty()
            st.say(f"Music: {label}", 90)
        elif action == "undo":
            st.say("Undo" if st.undo() else "Nothing to undo", 60)
        elif action == "redo":
            st.say("Redo" if st.redo() else "Nothing to redo", 60)
        elif action in ("menu", "test", "test_cursor", "bot", "bot_menu",
                        "save", "publish", "load", "export"):
            self.pending.append(action)

    def panel_action(self, action):
        st = self.st
        if action == "delete":
            self._delete_selection()
        elif action == "close":
            st.props_open = False
        elif action == "link" and st.selected:
            self._start_link_on(st.selected[0])

    def _run_pending(self):
        st = self.st
        while self.pending:
            action = self.pending.pop(0)
            if action == "menu":
                return self._try_exit()
            if action == "test":
                self.do_test()
            elif action == "test_cursor":
                self.do_test(from_cursor=True)
            elif action == "bot":
                self.do_bot()
            elif action == "bot_menu":
                self.do_bot_menu()
            elif action == "save":
                self.do_save()
            elif action == "publish":
                self.do_publish()
            elif action == "load":
                self.do_load()
            elif action == "export":
                path = ops.export_level_png(st.objects, st.level_name)
                st.say(f"Exported: {path}" if path else "Export failed", 240)
        return False

    def _try_exit(self):
        """Returns True when the editor should close."""
        st = self.st
        leave = confirm_exit(self.screen, self.clock, unsaved=st.unsaved_changes)
        self.guard.reset()
        if not leave:
            return False
        if st.dirty:
            self.autosave_now()
        music.stop()
        return True

    # ------------------------------------------------------------------
    # Keyboard
    # ------------------------------------------------------------------
    def _handle_key(self, ev):
        st = self.st
        key = ev.key
        mods = pygame.key.get_mods()
        ctrl = bool(mods & (pygame.KMOD_CTRL | pygame.KMOD_META))
        shift = bool(mods & pygame.KMOD_SHIFT)
        if key in (pygame.K_F1, pygame.K_QUESTION) or (key == pygame.K_SLASH):
            st.show_shortcuts = not st.show_shortcuts
            return
        if st.show_shortcuts:
            st.show_shortcuts = False
            return
        if key == pygame.K_ESCAPE:
            if st.snippet_stamp is not None:
                st.snippet_stamp = None
                st.snippet_stamp_name = ""
                st.say("Snippet cancelled", 60)
            elif st.pending_link is not None:
                st.pending_link = None
                st.say("Link cancelled", 60)
            elif st.props_open:
                st.props_open = False
            elif st.selected:
                st.clear_selection()
            else:
                self.pending.append("menu")
            return
        if ctrl:
            self._handle_ctrl_key(key, shift)
            return
        if key == pygame.K_g:
            self.do("toggle_grid")
        elif key == pygame.K_h:
            self.do("toggle_hitbox")
        elif key == pygame.K_m:
            music.toggle_mute()
            st.say("Music: " + ("OFF" if music.is_muted() else "ON"), 80)
        elif key == pygame.K_b:
            if shift and st.selected:
                self.do("toggle_bot_only")
            else:
                self._set_mode(MODE_BUILD)
        elif key == pygame.K_e:
            self._set_mode(MODE_DELETE)
        elif key == pygame.K_i:
            self._set_mode(MODE_EDIT)
        elif key == pygame.K_n:
            self._set_mode(MODE_EDIT)
            self.do("tool", TOOL_LINK)
        elif key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE) and st.pending_link:
            st.pending_link, msg = ops.link_confirm_targets(st.objects, st.pending_link)
            if msg:
                st.say(msg, 110)
        elif key in (pygame.K_DELETE, pygame.K_BACKSPACE):
            self._delete_selection()
        elif key == pygame.K_k:
            self.pending.append("bot")
        elif key == pygame.K_l:
            self.pending.append("bot_menu")
        elif key == pygame.K_t:
            self.pending.append("test_cursor" if shift else "test")
        elif key == pygame.K_s:
            self.pending.append("save")
        elif key == pygame.K_F2:
            self.do("snippet")
        elif key == pygame.K_F5:
            self.do("cycle_music")
        elif key == pygame.K_TAB:
            st.set_category(st.active_cat + (-1 if shift else 1))
        elif key in (pygame.K_r, pygame.K_q):
            delta = 90 if key == pygame.K_r else -90
            if st.mode == MODE_EDIT and st.selected:
                self.do("rot", delta)
            else:
                st.rotation = (st.rotation + delta) % 360
                st.say(f"Rotation: {st.rotation}°", 60)
        elif (key in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_UP, pygame.K_DOWN)
              and shift and st.mode == MODE_EDIT and st.selected):
            dx = (key == pygame.K_RIGHT) - (key == pygame.K_LEFT)
            dy = (key == pygame.K_DOWN) - (key == pygame.K_UP)
            self.do("nudge", (dx, dy))
        elif key in (pygame.K_1, pygame.K_2) and st.mode != MODE_BUILD:
            self._cycle_start_pos(-1 if key == pygame.K_1 else 1)
        elif st.mode == MODE_BUILD and pygame.K_1 <= key <= pygame.K_9:
            items = st.palette_items()
            per_page, _cols = ui.palette_page_size()
            idx = st.palette_page * per_page + (key - pygame.K_1)
            if idx < len(items):
                self._select_type(items[idx])

    def _handle_ctrl_key(self, key, shift):
        st = self.st
        if key == pygame.K_z:
            self.do("redo" if shift else "undo")
        elif key == pygame.K_y:
            self.do("redo")
        elif key == pygame.K_c:
            self.do("copy")
        elif key == pygame.K_x:
            self.do("cut")
        elif key == pygame.K_v:
            self.do("paste")
        elif key == pygame.K_d:
            self.do("duplicate")
        elif key == pygame.K_a:
            self.do("select_all")
        elif key == pygame.K_e:
            self.pending.append("export")
        elif key in (pygame.K_l, pygame.K_o):
            self.pending.append("load")
        elif key == pygame.K_s:
            if shift:
                self.do("save_snippet")
            else:
                self.pending.append("save")
        elif key in (pygame.K_EQUALS, pygame.K_PLUS):
            self.do("zoom_in")
        elif key == pygame.K_MINUS:
            self.do("zoom_out")
        elif key == pygame.K_0:
            self.do("zoom_reset")
        elif key in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_UP, pygame.K_DOWN) and st.selected:
            dx = (key == pygame.K_RIGHT) - (key == pygame.K_LEFT)
            dy = (key == pygame.K_DOWN) - (key == pygame.K_UP)
            self.do("nudge", (dx, dy))

    # ------------------------------------------------------------------
    # Mouse
    # ------------------------------------------------------------------
    def _handle_wheel(self, ev):
        st = self.st
        mx, my = self.mpos
        if self.in_canvas(self.mpos):
            step = 0.1 if pygame.key.get_mods() & pygame.KMOD_SHIFT else 0.2
            st.set_zoom(st.zoom + (step if ev.y > 0 else -step), anchor=(mx, my))
        elif my >= BAR_Y and st.mode == MODE_BUILD:
            st.rotation = (st.rotation + (90 if ev.y > 0 else -90)) % 360

    def _handle_press(self, ev):
        st = self.st
        pos = ev.pos
        if ev.button in (2, 3):
            st.drag = {"kind": "pan", "anchor": pos, "cam": (st.cam_x, st.cam_y)}
            if ev.button == 3 and self.in_canvas(pos):
                self._right_press = (pos, st.screen_to_cell(*pos))
            return
        if ev.button != 1:
            return
        if st.props_open and self.panel.contains(pos):
            self.panel.click(st, pos, self, button=1)
            return
        for group in (self.top_buttons, self.side_buttons, self.bottom_buttons):
            b = ui.hit(group, pos)
            if b is not None:
                self.do(b.action, b.arg)
                return
        if not self.in_canvas(pos):
            return
        self._canvas_press(pos)

    def _canvas_press(self, pos):
        st = self.st
        gx, gy = st.screen_to_cell(*pos)
        shift = bool(pygame.key.get_mods() & pygame.KMOD_SHIFT)
        if st.snippet_stamp is not None:
            st.push_undo()
            new = ops.clone_objects(st.snippet_stamp, (gx, gy), st.objects)
            st.objects.extend(new)
            st.mode = MODE_EDIT
            st.selected = new
            if shift:
                st.snippet_stamp = None
                st.snippet_stamp_name = ""
            st.say(f"Stamped {st.snippet_stamp_name or 'snippet'} ({len(new)} obj)"
                   + ("" if shift else " — click to repeat, Esc to cancel"), 120)
            return
        if st.mode == MODE_BUILD:
            st.push_undo()
            ops.place_object(st.objects, gx, gy, st.selected_type, st.rotation,
                             st.group_id_counter)
            if st.selected_type == T_TELEPORT_ORB:
                st.group_id_counter = next_group_id(st.objects)
            st.last_brush_cell = (gx, gy)
            st.drag = ({"kind": "paint"} if st.swipe
                       else {"kind": "pan", "anchor": pos, "cam": (st.cam_x, st.cam_y)})
            return
        if st.mode == MODE_DELETE:
            st.push_undo()
            only = st.selected_type if st.delete_filter else None
            ops.erase_at(st.objects, gx, gy, only)
            st.prune_selection()
            st.drag = ({"kind": "erase", "only": only} if st.swipe
                       else {"kind": "pan", "anchor": pos, "cam": (st.cam_x, st.cam_y)})
            return
        # ---- edit mode ----
        if st.edit_tool == TOOL_LINK:
            st.pending_link, msg = ops.link_click(st.objects, gx, gy, st.pending_link)
            st.say(msg, 110)
            return
        if st.edit_tool == TOOL_BOT_PATH:
            st.bot_waypoints.append(st.screen_to_world(*pos))
            st.bot_exact_inputs = None
            st.bot_mirror_waypoints = []
            st.say(f"Bot path: {len(st.bot_waypoints)} pts (K runs, right-click removes)", 90)
            return
        stack = ops.objects_at_cell(st.objects, gx, gy)
        top = stack[-1] if stack else None
        if shift:
            if top is not None:
                idx = ops.index_by_id(st.selected, top)
                if idx != -1:
                    st.selected.pop(idx)
                else:
                    st.selected.append(top)
                st.say(f"{len(st.selected)} selected", 70)
            else:
                st.drag = {"kind": "marquee", "start": pos, "add": True}
            return
        if top is None:
            st.clear_selection()
            st.drag = ({"kind": "marquee", "start": pos, "add": False} if st.swipe
                       else {"kind": "pan", "anchor": pos, "cam": (st.cam_x, st.cam_y)})
            return
        # Re-clicking the same cell cycles through a stack. This must be
        # checked before the "already selected" short-circuit below: after
        # the first click `top` (the stack's topmost hit) IS already the
        # selection, so `top not in st.selected` would never be true again
        # and the cycle could never advance past the first item.
        cur_idx = ops.index_by_id(stack, st.selected[0]) if len(st.selected) == 1 else -1
        if len(stack) > 1 and st.last_edit_cell == (gx, gy) and cur_idx != -1:
            top = stack[(cur_idx + 1) % len(stack)]
            st.selected = [top]
            st.say(f"Stack {ops.index_by_id(stack, top) + 1}/{len(stack)} — click again to cycle", 100)
        elif not ops.contains_id(st.selected, top):
            st.selected = [top]
            st.last_edit_cell = (gx, gy)
            if len(stack) > 1:
                st.say(f"Stack {ops.index_by_id(stack, top) + 1}/{len(stack)} — click again to cycle", 100)
        if st.rotate_drag:
            x0, y0, x1, y1 = ops.selection_bounds(st.selected)
            cx, cy = st.cell_to_screen((x0 + x1 + 1) / 2.0, (y0 + y1 + 1) / 2.0)
            st.drag = {"kind": "rotate", "center": (cx, cy),
                       "start_angle": math.degrees(math.atan2(pos[1] - cy, pos[0] - cx)),
                       "base": {id(o): float(o.get("r", 0)) for o in st.selected},
                       "snap": ops.snapshot(st.objects), "moved": False}
        else:
            st.drag = {"kind": "move", "anchor": (gx, gy),
                       "start": {id(o): (o["x"], o["y"]) for o in st.selected},
                       "snap": ops.snapshot(st.objects), "moved": False}

    def _handle_release(self, ev):
        st = self.st
        drag = st.drag
        if ev.button == 3 and self._right_press is not None:
            (px, py), cell = self._right_press
            self._right_press = None
            if abs(ev.pos[0] - px) < 4 and abs(ev.pos[1] - py) < 4:
                if st.mode == MODE_EDIT and st.edit_tool == TOOL_BOT_PATH:
                    if st.bot_waypoints:
                        st.bot_waypoints.pop()
                        st.say(f"Bot path: {len(st.bot_waypoints)} pts", 70)
                elif st.mode == MODE_BUILD:
                    st.push_undo()
                    ops.erase_at(st.objects, *cell)
                    st.prune_selection()
        if ev.button in (2, 3):
            if drag and drag["kind"] == "pan":
                st.drag = None
            return
        if ev.button != 1:
            return
        st.curve_drag_idx = None
        st.last_brush_cell = None
        if drag is None:
            return
        kind = drag["kind"]
        if kind == "marquee":
            x0, y0 = drag["start"]
            x1, y1 = ev.pos
            if abs(x1 - x0) >= 3 or abs(y1 - y0) >= 3:
                gx0, gy0 = st.screen_to_cell(min(x0, x1), min(y0, y1))
                gx1, gy1 = st.screen_to_cell(max(x0, x1), max(y0, y1))
                hits = ops.objects_in_cells(st.objects, gx0, gy0, gx1, gy1)
                if drag["add"]:
                    for h in hits:
                        if h in st.selected:
                            st.selected.remove(h)
                        else:
                            st.selected.append(h)
                else:
                    st.selected = hits
                st.last_edit_cell = None
                if st.selected:
                    st.say(f"{len(st.selected)} selected", 90)
        elif kind in ("move", "rotate") and drag.get("moved"):
            st.undo_stack.append(drag["snap"])
            if len(st.undo_stack) > ops.MAX_UNDO_STACK:
                st.undo_stack.pop(0)
            st.redo_stack.clear()
            st.mark_dirty()
            n = len(st.selected)
            st.say(("Moved" if kind == "move" else "Rotated")
                   + f" {n} object{'s' if n != 1 else ''}", 70)
        st.drag = None

    def _handle_motion(self, ev):
        st = self.st
        drag = st.drag
        if drag is None:
            return
        kind = drag["kind"]
        if kind == "pan":
            ax, ay = drag["anchor"]
            st.cam_x = drag["cam"][0] - (ev.pos[0] - ax)
            st.cam_y = drag["cam"][1] - (ev.pos[1] - ay)
        elif kind == "move":
            gx, gy = st.screen_to_cell(*ev.pos)
            dx = gx - drag["anchor"][0]
            dy = gy - drag["anchor"][1]
            for o in st.selected:
                sx, sy = drag["start"].get(id(o), (o["x"], o["y"]))
                nx, ny = sx + dx, sy + dy
                if (o["x"], o["y"]) != (nx, ny):
                    if o["t"] == "move_trigger":
                        if "tx" in o:
                            o["tx"] += nx - o["x"]
                        if "ty" in o:
                            o["ty"] += ny - o["y"]
                    o["x"], o["y"] = nx, ny
                    drag["moved"] = True
        elif kind == "rotate":
            cx, cy = drag["center"]
            ang = math.degrees(math.atan2(ev.pos[1] - cy, ev.pos[0] - cx))
            delta = ang - drag["start_angle"]
            if not pygame.key.get_mods() & pygame.KMOD_SHIFT:
                delta = round(delta / ROTATE_SNAP_DEG) * ROTATE_SNAP_DEG
            for o in st.selected:
                base = drag["base"].get(id(o), 0.0)
                new = (base + delta) % 360.0
                if abs(new - float(o.get("r", 0))) > 1e-6:
                    o["r"] = int(new) if abs(new - round(new)) < 1e-6 else new
                    drag["moved"] = True

    # ------------------------------------------------------------------
    # Per-frame continuous input
    # ------------------------------------------------------------------
    def _per_frame(self):
        st = self.st
        mx, my = self.mpos
        held = self.guard.mouse_held()
        drag = st.drag
        if held and drag is not None and self.in_canvas(self.mpos):
            gx, gy = st.screen_to_cell(mx, my)
            if drag["kind"] == "paint" and (gx, gy) != st.last_brush_cell:
                ops.place_object(st.objects, gx, gy, st.selected_type, st.rotation,
                                 st.group_id_counter)
                if st.selected_type == T_TELEPORT_ORB:
                    st.group_id_counter = next_group_id(st.objects)
                st.last_brush_cell = (gx, gy)
                st.mark_dirty()
            elif drag["kind"] == "erase":
                if ops.erase_at(st.objects, gx, gy, drag["only"]):
                    st.prune_selection()
                    st.mark_dirty()
        if held and st.curve_drag_idx is not None:
            self.panel.curve_drag(st, self.mpos)
        if not held:
            st.curve_drag_idx = None
            if drag is not None and drag["kind"] in ("paint", "erase", "marquee", "move", "rotate"):
                st.drag = None
        keys = pygame.key.get_pressed()
        mods = pygame.key.get_mods()
        if not (mods & (pygame.KMOD_CTRL | pygame.KMOD_META)):
            spd = PAN_SPEED * (2 if mods & pygame.KMOD_SHIFT else 1)
            nudging = bool(mods & pygame.KMOD_SHIFT) and st.mode == MODE_EDIT and st.selected
            if keys[pygame.K_a] or (keys[pygame.K_LEFT] and not nudging):
                st.cam_x -= spd
            if keys[pygame.K_d] or (keys[pygame.K_RIGHT] and not nudging):
                st.cam_x += spd
            if keys[pygame.K_w] or (keys[pygame.K_UP] and not nudging):
                st.cam_y -= spd
            if keys[pygame.K_DOWN] and not nudging:
                st.cam_y += spd
        if st.msg_timer > 0:
            st.msg_timer -= 1
        if st.autosave_toast_frames > 0:
            st.autosave_toast_frames -= 1
        if st.dirty:
            st.autosave_timer += 1
            if st.autosave_timer >= AUTOSAVE_INTERVAL:
                st.autosave_timer = 0
                if self.autosave_now():
                    st.say("Auto-saved", 60)
        else:
            st.autosave_timer = 0
        st.prune_selection()

    # ------------------------------------------------------------------
    # Render
    # ------------------------------------------------------------------
    def _render(self):
        st = self.st
        s = self.screen
        mpos = self.mpos
        render.render_canvas(s, st, self.stars, self.mountains)
        render.render_jump_predictor(s, st)
        if st.show_hitboxes:
            render.render_hitbox_overlay(s, st)
        render.render_bot_paths(s, st)
        in_canvas = self.in_canvas(mpos)
        if st.pending_link:
            render.render_pending_link(s, st, mpos, in_canvas)
        if st.selected:
            render.render_selection(s, st)
        if st.drag and st.drag["kind"] == "marquee":
            render.render_marquee(s, st.drag["start"], mpos)
        if in_canvas and not (st.drag and st.drag["kind"] == "pan"):
            render.render_cursor(s, st, mpos)
        if st.props_open and st.selected:
            self.panel.draw(s, st, mpos)
        ui.draw_side(s, self.side_buttons, mpos)
        ui.draw_top(s, st, self.top_buttons, mpos)
        hovered = ui.draw_bottom(s, st, self.bottom_buttons, mpos)
        ui.draw_palette_tooltip(s, hovered, mpos)
        ui.draw_hud(s, st, mpos)
        ui.draw_toast(s, st)
        if st.show_shortcuts:
            draw_shortcuts(s)
        pygame.display.flip()

    def _layout(self):
        st = self.st
        self.top_buttons = ui.layout_top(st)
        self.side_buttons = ui.layout_side(st)
        self.bottom_buttons = ui.layout_bottom(st)
        if st.props_open and st.selected:
            self.panel.layout(st)
        else:
            self.panel.rect.h = 0

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------
    def run(self):
        st = self.st
        while True:
            self.guard.tick()
            st.pulse += 1
            self.mpos = pygame.mouse.get_pos()
            self._layout()
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    if self._try_exit():
                        return None
                    continue
                if ev.type == pygame.KEYDOWN:
                    self._handle_key(ev)
                elif ev.type == pygame.MOUSEWHEEL:
                    self._handle_wheel(ev)
                elif ev.type == pygame.MOUSEBUTTONDOWN:
                    if ev.button == 1 and not self.guard.consume_click(ev):
                        continue
                    self._handle_press(ev)
                elif ev.type == pygame.MOUSEBUTTONUP:
                    if ev.button == 1 and not self.guard.is_settled():
                        continue
                    self._handle_release(ev)
                elif ev.type == pygame.MOUSEMOTION:
                    self._handle_motion(ev)
            if self._run_pending():
                return None
            self._per_frame()
            self._render()
            self.clock.tick(settings.get_fps_cap())
