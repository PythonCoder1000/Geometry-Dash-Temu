"""Gameplay loop.

:class:`PlaySession` runs one play session: input, fixed-rate physics
stepping (via :class:`Player`), camera, HUD / overlays, pause and win
screens, practice checkpoints, and (on a legitimate win) persisting the
level's verification / progress metadata.  :func:`run_play` is the
thin entry point every caller uses.

Timing model
------------
Physics ticks at a fixed ``PHYSICS_RATE`` (60 Hz); every movement
constant is tuned for that rate.  The render loop runs at whatever FPS
cap the user picked.  A wall-clock accumulator decides how many ticks to
run per rendered frame, and the leftover fraction (``sim_accum``) is
used as the interpolation ``alpha`` so the player and camera are drawn
between the last two ticks.  That is what makes 120/144 FPS output
smooth instead of showing every physics pose twice.
"""

import os
import sys

import pygame

from .constants import (
    WIDTH, HEIGHT, CELL, PLAYER_START_GX,
    C_PLAYER, C_BG_TOP, C_BG_BOT, C_DASH_ORB,
    DECORATION_TYPES, TRIGGER_TYPES, BG_PRESETS, PAD_TYPES,
    T_COIN, T_ORB, T_DASH_ORB, T_DASH_ORB_GRAV, T_BLACK_ORB,
    T_BLUE_ORB, T_GREEN_ORB, T_SPIDER_ORB, T_RED_ORB, T_PINK_ORB,
    T_GRAV_UP, T_GRAV_DOWN, T_TIME_WARP, SPEED_VALUES, T_END,
    TELEPORT_LINK_TYPES,
)
from .graphics import (
    make_rect, make_stars, make_mountains,
    update_shake, apply_shake, shake_offset,
)
from . import settings
from . import gamepad
from . import music
from . import sfx
from . import prefs
from .input_guard import ClickGuard
from .particles import Particles
from .physics import PhysicsParams
from .player import Player
from .levels import update_meta, get_group_id
from .objects import cycle_active_start, start_objects
from .play_render import (
    render_world, render_hint_overlay, render_predicted_path,
    render_ghost_paths, render_death_hitbox_marker, render_best_run_ghost,
    render_player_and_particles, render_checkpoint_markers,
    render_death_reason, render_slowmo_vignette, render_pulse_flash,
    render_blackout, render_toast,
    render_hud, render_debug_overlay, render_state_hud,
    render_pause_overlay, render_win_overlay,
)

PHYSICS_RATE = 60          # physics ticks per second (fixed)
CAMERA_LEAD_PX = 200.0     # player sits this far right of the left edge
CAM_Y_EASE = 0.08
CAM_Y_MAX_STEP = 14.0      # px per tick
DEATH_FRAMES = 45
DEATH_SLOWMO_FRAMES = 30
MANUAL_TAKEOVER_GRACE = 60  # ticks of silence before a takeover dies
TEST_SPEEDS = (0.01, 0.05, 0.1, 0.25, 0.5, 1.0)
DESYNC_ALERT_PX = 24.0

# Interaction keys added to player.passed during a tick -> one-shot SFX.
_SFX_FOR_TYPE = {
    T_ORB: ("orb", 0.5),
    T_DASH_ORB: ("orb", 0.55),
    T_DASH_ORB_GRAV: ("orb", 0.55),
    T_BLACK_ORB: ("orb", 0.5),
    T_BLUE_ORB: ("gravity", 0.45),
    T_GREEN_ORB: ("orb", 0.5),
    T_SPIDER_ORB: ("gravity", 0.5),
    T_RED_ORB: ("orb", 0.6),
    T_PINK_ORB: ("orb", 0.4),
    T_GRAV_UP: ("gravity", 0.45),
    T_GRAV_DOWN: ("gravity", 0.45),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _teleport_x_map(objects):
    """Teleport-orb/portal source x (px) -> paired destination x (px).

    Mirrors :meth:`Player.activate_teleport`'s pairing rule (same
    group id, prefer a member flagged ``dest``) without needing a live
    Player/teleport index."""
    groups = {}
    for o in objects:
        if o.get("t") in TELEPORT_LINK_TYPES:
            gid = get_group_id(o)
            if gid:
                groups.setdefault(gid, []).append(o)
    out = {}
    for members in groups.values():
        if len(members) < 2:
            continue
        for src in members:
            others = [m for m in members if m is not src]
            dests = [m for m in others if m.get("dest")]
            dst = dests[0] if dests else others[0]
            out[int(src["x"]) * CELL] = int(dst["x"]) * CELL
    return out


def _speed_warp_events(objects, base_speed):
    """Sorted (x_px, value) event lists for speed portals and time-warp
    triggers, plus lookup closures for "the value in effect at x" —
    shared by :func:`real_time_to_x` and its inverse, :func:`x_at_time`."""
    base_speed = max(1.0, float(base_speed))
    speed_events = sorted(
        ((int(o["x"]) * CELL, float(SPEED_VALUES[o["t"]]))
         for o in objects if o.get("t") in SPEED_VALUES),
        key=lambda e: e[0])
    warp_events = sorted(
        ((int(o["x"]) * CELL, float(o.get("factor", 1.0)))
         for o in objects if o.get("t") == T_TIME_WARP),
        key=lambda e: e[0])

    def speed_at(x):
        v = base_speed
        for ex, ev in speed_events:
            if ex > x:
                break
            v = ev
        return v

    def warp_at(x):
        v = 1.0
        for ex, ev in warp_events:
            if ex > x:
                break
            v = ev
        return v

    return speed_events, warp_events, speed_at, warp_at


def real_time_to_x(objects, target_x, base_speed):
    """Wall-clock seconds the player spends reaching ``target_x`` from
    x=0, integrating across speed portals, time-warp triggers, and
    teleport orbs/portals (an instantaneous relocation — no elapsed
    time of its own, forward or backward). Used to seek the music when
    spawning mid-level, and by the editor's music-preview tool.

    Re-scans events from the (possibly non-monotonic, after a backward
    teleport) current position each step rather than walking sorted
    array indices, since a teleport can move ``cur_x`` in either
    direction. Levels have too few trigger objects for this to matter
    performance-wise, and it's only ever called on demand, not per
    frame. A bounded step count guards against a pathological circular
    teleport loop."""
    if target_x <= 0:
        return 0.0
    speed_events, warp_events, speed_at, warp_at = _speed_warp_events(objects, base_speed)
    teleports = _teleport_x_map(objects)

    cur_x = 0.0
    elapsed = 0.0
    guard = 0
    while cur_x < target_x and guard < 4000:
        guard += 1
        cur_speed = speed_at(cur_x)
        cur_warp = warp_at(cur_x)
        next_x = target_x
        for ex, _ in speed_events:
            if cur_x < ex < next_x:
                next_x = ex
        for ex, _ in warp_events:
            if cur_x < ex < next_x:
                next_x = ex
        teleport_here = None
        for tx in teleports:
            if cur_x < tx <= next_x:
                next_x = tx
                teleport_here = tx
        if cur_speed > 0 and cur_warp > 0:
            elapsed += max(0.0, next_x - cur_x) / (cur_speed * PHYSICS_RATE * cur_warp)
        cur_x = float(teleports[teleport_here]) if teleport_here is not None else next_x
    return elapsed


def x_at_time(objects, target_t, base_speed):
    """Inverse of :func:`real_time_to_x`: the x position (px) a player
    would be at after ``target_t`` wall-clock seconds of playback,
    integrating the same speed / warp / teleport events. Drives the
    editor's live music-preview playhead."""
    if target_t <= 0:
        return 0.0
    speed_events, warp_events, speed_at, warp_at = _speed_warp_events(objects, base_speed)
    teleports = _teleport_x_map(objects)

    cur_x = 0.0
    elapsed = 0.0
    guard = 0
    while guard < 4000:
        guard += 1
        cur_speed = speed_at(cur_x)
        cur_warp = warp_at(cur_x)
        next_x = None
        for ex, _ in speed_events:
            if ex > cur_x and (next_x is None or ex < next_x):
                next_x = ex
        for ex, _ in warp_events:
            if ex > cur_x and (next_x is None or ex < next_x):
                next_x = ex
        for tx in teleports:
            if tx > cur_x and (next_x is None or tx < next_x):
                next_x = tx
        rate = cur_speed * PHYSICS_RATE * cur_warp
        if next_x is None:
            return cur_x + max(0.0, target_t - elapsed) * rate if rate > 0 else cur_x
        seg_time = (next_x - cur_x) / rate if rate > 0 else float("inf")
        if elapsed + seg_time >= target_t:
            return cur_x + max(0.0, target_t - elapsed) * rate
        elapsed += seg_time
        cur_x = float(teleports[next_x]) if next_x in teleports else next_x
    return cur_x


def _total_coins(objects):
    return sum(1 for o in objects if o["t"] == T_COIN)


def _play_interaction_sounds(before_passed, after_passed, before_pads,
                             after_pads, before_coins, after_coins):
    """Emit one-shot SFX for orbs / pads / coins consumed this tick."""
    for key in after_passed - before_passed:
        t = key[0] if isinstance(key, tuple) and key else None
        info = _SFX_FOR_TYPE.get(t)
        if info:
            sfx.play(*info)
    if after_pads > before_pads:
        sfx.play("pad", 0.5)
    if after_coins > before_coins:
        sfx.play("click", 0.55)


def _clean_objects(objects):
    """Strip the ``_``-prefixed bookkeeping the live Player adds."""
    return [{k: v for k, v in o.items()
             if not (isinstance(k, str) and k.startswith("_"))}
            for o in objects]


def _sorted_by_x(objects):
    """(layer, xs) sorted by original x for bisect culling."""
    layer = sorted(objects, key=lambda o: o.get("_orig_x", o["x"]))
    return layer, [o.get("_orig_x", o["x"]) for o in layer]


def _prepare_waypoints(waypoints):
    """Sort by x and collapse duplicate x entries. Returns (points, xs)."""
    if not waypoints:
        return None, None
    clean = []
    for px, py in sorted(waypoints, key=lambda p: p[0]):
        if clean and px == clean[-1][0]:
            clean[-1] = (px, py)
        else:
            clean.append((px, py))
    return clean, [p[0] for p in clean]


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

class PlaySession:
    """One play session.  Build it, then call :meth:`run`."""

    def __init__(self, screen, clock, objects, level_name="Level",
                 editor_test=False, practice_mode=False, level_music=None,
                 bot_controller=None, playback_inputs=None,
                 playback_waypoints=None, meta=None, level_path=None,
                 out_hitboxes=None, out_mirror_hitboxes=None, start_x=None,
                 predicted_path=None, ghost_paths=None, noclip=False):
        self.screen = screen
        self.clock = clock
        self.objects = [dict(o) for o in objects]
        self.level_name = level_name
        self.editor_test = editor_test
        self.practice_mode = practice_mode
        self.level_music = level_music
        self.bot_controller = bot_controller
        self.playback_inputs = playback_inputs
        self.meta = meta
        self.level_path = level_path
        self.out_hitboxes = out_hitboxes
        self.out_mirror_hitboxes = out_mirror_hitboxes
        self.start_x = float(start_x) if start_x and start_x > 0 else None
        self.predicted_path = predicted_path
        self.ghost_paths = ghost_paths

        self.total_coins = _total_coins(self.objects)
        # Progress is measured against the finish line the player actually
        # has to cross, not whatever object happens to sit furthest right
        # (a stray decoration past the end wall used to make 100% unreachable).
        end_xs = [o["x"] for o in self.objects if o["t"] == T_END]
        rightmost_gx = (min(end_xs) if end_xs
                        else max((o["x"] for o in self.objects), default=10))
        self.max_x = rightmost_gx * CELL + CELL
        self.player = Player(self.objects, params=PhysicsParams.from_meta(meta))
        self.player.practice_mode = practice_mode
        self.player.noclip = noclip
        self.is_sim_run = bot_controller is not None or playback_inputs is not None
        self.can_persist = (not editor_test and not self.is_sim_run
                            and level_path is not None)
        self.music_offset_sec = self._music_offset_seconds()

        # Hitbox recording (editor "H" overlay). The lists are handed to
        # the player and cleared in place so its reference stays valid.
        self.current_hitboxes = []
        self.current_mirror_hitboxes = []
        self.best_hitboxes_progress = 0.0
        if out_hitboxes is not None:
            self.player.hitbox_trace = self.current_hitboxes
        if out_mirror_hitboxes is not None:
            self.player.mirror_hitbox_trace = self.current_mirror_hitboxes

        # Render layers (decorations behind everything else).
        pool = [o for o in self.objects if o["t"] not in TRIGGER_TYPES]
        self.deco_layer, self.deco_xs = _sorted_by_x(
            [o for o in pool if o["t"] in DECORATION_TYPES])
        self.main_layer, self.main_xs = _sorted_by_x(
            [o for o in pool if o["t"] not in DECORATION_TYPES])
        self.stars = make_stars()
        self.mountains = make_mountains()
        self.particles = Particles()
        self.overlay_scratch = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        self.CLEAR = (0, 0, 0, 0)

        # Playback watchdog / predicted path lookups.
        self.playback_wp_sorted, self.playback_wp_xs = _prepare_waypoints(
            playback_waypoints)
        self.pred_path_sorted, self.pred_path_xs = _prepare_waypoints(
            predicted_path)

        # UI rects.
        self.rc_menu = make_rect(WIDTH // 2 - 120, HEIGHT // 2 + 80, 180, 50)
        self.rc_replay = make_rect(WIDTH // 2 + 120, HEIGHT // 2 + 80, 180, 50)
        self.pause_menu_buttons = {
            "resume": make_rect(WIDTH // 2, HEIGHT // 2 - 60, 220, 48),
            "restart": make_rect(WIDTH // 2, HEIGHT // 2 - 6, 220, 48),
            "practice_toggle": make_rect(WIDTH // 2, HEIGHT // 2 + 48, 220, 48),
            "settings": make_rect(WIDTH // 2, HEIGHT // 2 + 102, 220, 48),
            "menu": make_rect(WIDTH // 2, HEIGHT // 2 + 156, 220, 48),
        }
        self.r_mute_music = pygame.Rect(0, 0, 0, 0)
        self.r_mute_sfx = pygame.Rect(0, 0, 0, 0)

        # Session-wide state.
        self.attempts = 1
        self.deaths_this_session = 0
        self.best_run = []            # (frame, x, y) ghost of the best attempt
        self.best_run_progress_x = 0.0
        self.best_progress = 0        # percent, persisted on exit
        self.best_coins_this_run = 0
        self.paused = False
        self.win_sfx_played = False
        self.meta_persisted = False
        self.show_debug = False
        self.toast_text = ""
        self.toast_timer = 0
        self.show_state = bool(editor_test)
        self.dbg_frame_times = []
        self.test_speed_idx = len(TEST_SPEEDS) - 1
        self.hint_path = None
        self.hint_mirror_path = None
        self.hint_visible = False
        self.hint_status = ""
        self.pulse = 0
        self.guard = ClickGuard()
        self.sim_accum = 0.0
        self.last_dt_sec = 1.0 / PHYSICS_RATE
        self.jump_held = False
        self.prev_input_held = False
        self.pending_presses = 0
        self.cam_x = 0.0
        self.cam_y = 0.0
        self.prev_cam_y = 0.0
        self._cam_pan_target = 0.0
        self._cam_pan_start = 0.0
        self._cam_pan_timer = 0
        self._cam_pan_len = 1
        self.bg_top = [float(c) for c in C_BG_TOP]
        self.bg_bot = [float(c) for c in C_BG_BOT]
        self._init_attempt_state()
        if self.start_x is not None:
            self.player.set_x(self.start_x)
        self.cam_x = self.player.x - CAMERA_LEAD_PX

    # ---- attempt lifecycle -------------------------------------------------
    def _init_attempt_state(self):
        self.death_timer = 0
        self.death_slowmo_timer = 0
        self.death_flash_timer = 0
        self.death_hitbox = None      # (x, y, size, angle, reason)
        self.attempt_frames = 0
        self.current_run = []
        self.pending_presses = 0
        self.prev_input_held = False
        self.sim_accum = 0.0
        # Bot / playback bookkeeping.
        self.bot_frame = 0
        self.bot_click_flash = 0
        self.bot_press_frames = []
        self.bot_press_total = 0
        self.prev_b_held = False
        self.manual_takeover = False
        self.takeover_idle_frames = 0
        self.desync_max_px = 0.0
        self.desync_alert_timer = 0

    def _music_offset_seconds(self):
        """Seek offset so the music matches a mid-level spawn.  t=0 is
        the default spawn column, not world x=0."""
        spawn_x = float(self.player.x)
        if self.start_x is not None:
            spawn_x = max(spawn_x, self.start_x)
        default_x = float(PLAYER_START_GX * CELL)
        if spawn_x <= default_x + 1.0:
            return 0.0
        base = float(self.player.params.base_move_speed)
        return max(0.0, real_time_to_x(self.objects, spawn_x, base)
                   - real_time_to_x(self.objects, default_x, base))

    def _start_music(self):
        if self.level_music:
            music.stop()
            music.play_file(self.level_music, start_sec=self.music_offset_sec)

    def _toggle_music_mute(self):
        """Mute / unmute without restarting the track or falling back to
        the menu music."""
        if music.is_muted():
            music.set_enabled(True)
            if self.level_music and not music.is_playing():
                music.play_file(self.level_music)
        else:
            music.set_enabled(False)

    def _commit_hitboxes(self):
        """Publish this attempt's trace to the editor if it is the
        deepest one so far (a panicked early restart must not clobber a
        trace that reached 80 %)."""
        if (self.out_hitboxes is not None and self.current_hitboxes
                and self.player.x >= self.best_hitboxes_progress):
            self.out_hitboxes[:] = self.current_hitboxes
            if self.out_mirror_hitboxes is not None:
                self.out_mirror_hitboxes[:] = self.current_mirror_hitboxes
            self.best_hitboxes_progress = self.player.x

    def reset_attempt(self):
        """Fresh attempt: reset the player and every per-attempt counter."""
        if self.current_run and self.current_run[-1][1] > self.best_run_progress_x:
            self.best_run = list(self.current_run)
            self.best_run_progress_x = self.current_run[-1][1]
        self._commit_hitboxes()
        self.current_hitboxes.clear()
        self.current_mirror_hitboxes.clear()
        self.player.reset()
        if self.start_x is not None:
            self.player.set_x(self.start_x)
        self.attempts += 1
        self._init_attempt_state()
        if self.bot_controller:
            self.bot_controller.reset()
        self.cam_x = self.player.x - CAMERA_LEAD_PX
        self.cam_y = 0.0
        self.prev_cam_y = 0.0
        self._cam_pan_target = 0.0
        self._cam_pan_start = 0.0
        self._cam_pan_timer = 0
        self._cam_pan_len = 1
        self.bg_top[:] = [float(c) for c in C_BG_TOP]
        self.bg_bot[:] = [float(c) for c in C_BG_BOT]
        # Recompute: the spawn point may have changed (Q/E start-position
        # cycling) since __init__ or the previous reset computed this.
        self.music_offset_sec = self._music_offset_seconds()
        self._start_music()

    def _finish(self, result):
        """Leave the session: stop music, commit traces, persist best %."""
        if self.level_music:
            music.stop()
        self._commit_hitboxes()
        if (self.level_path and self.can_persist and not self.practice_mode
                and self.best_progress > 0):
            try:
                prev_best = int((self.meta or {}).get("best_progress", 0))
                if self.best_progress > prev_best:
                    update_meta(self.level_path, best_progress=self.best_progress)
                    if self.meta is not None:
                        self.meta["best_progress"] = self.best_progress
            except Exception:
                pass
        return result

    # ---- hints / persistence ---------------------------------------------
    def _compute_hint_path(self):
        """Run the human bot once for the practice-mode H overlay.
        Returns ``(status, waypoints, mirror_waypoints)``."""
        try:
            from .bots import HumanBot
            solver = HumanBot(_clean_objects(self.objects),
                              params=self.player.params)
            wp, mwp, _inputs, won = solver.solve(self.screen, self.clock)
            if not wp:
                return "failed", None, None
            return ("ok" if won else "partial"), list(wp), list(mwp)
        except Exception:
            return "failed", None, None

    def _persist_win(self):
        """Persist attempts / best progress / coins / best time.  The
        first non-author win on a published, unverified level also asks
        for a difficulty suggestion and flips ``verified``."""
        if self.meta_persisted or not self.can_persist:
            return
        meta = self.meta or {}
        prev_best_time = int(meta.get("best_time_frames", 0))
        new_best_time = (self.attempt_frames if prev_best_time <= 0
                         else min(prev_best_time, self.attempt_frames))
        updates = {
            "attempts": int(meta.get("attempts", 0)) + self.attempts,
            "best_progress": max(int(meta.get("best_progress", 0)), 100),
            "coins_collected": max(int(meta.get("coins_collected", 0)),
                                   len(self.player.coins_collected)),
            "best_time_frames": new_best_time,
            "deaths": int(meta.get("deaths", 0)) + self.deaths_this_session,
        }
        cur_user = prefs.get("signed_in_username", None)
        is_author = cur_user is not None and cur_user == (meta.get("author") or "")
        if (not is_author and meta.get("published") and not meta.get("verified")
                and not meta.get("rated")):
            from .menus import difficulty_picker
            requested = meta.get("requested_difficulty",
                                 meta.get("difficulty", "Normal"))
            chosen = difficulty_picker(
                self.screen, self.clock, prompt="You beat this level!",
                default=requested,
                subtitle=f"Publisher requested: {requested}.  "
                         f"What difficulty do you think this is?")
            if chosen:
                updates["verified"] = True
                updates["suggested_difficulty"] = chosen
        try:
            update_meta(self.level_path, **updates)
            self.meta_persisted = True
            if self.meta is not None:
                self.meta.update(updates)
        except OSError:
            pass

    def _record_practice_progress(self, progress_now):
        if not (self.practice_mode and self.level_path):
            return
        try:
            from .menus import _get_best_practice, _set_best_practice
            fn = os.path.basename(self.level_path)
            if progress_now > _get_best_practice(fn):
                _set_best_practice(fn, progress_now)
        except Exception:
            pass

    # ---- input -------------------------------------------------------------
    def _open_bot_menu(self):
        from .bot_menu import run_bot_menu, get_last_mirror_waypoints
        lfn = os.path.basename(self.level_path) if self.level_path else None
        result = run_bot_menu(
            self.screen, self.clock, [dict(o) for o in self.objects],
            precomputed_path=self.hint_path, drawn_path=self.hint_path,
            level_filename=lfn, meta=self.meta)
        if result is not None:
            new_path, new_status = result
            if new_status == "cleared":
                self.hint_path = None
                self.hint_mirror_path = None
                self.hint_status = ""
                self.hint_visible = False
            elif new_path:
                self.hint_path = new_path
                self.hint_mirror_path = get_last_mirror_waypoints()
                self.hint_status = new_status
                self.hint_visible = True
        self.guard.reset()

    def _toggle_hint(self):
        if self.hint_path is None:
            self.hint_status, path, mirror = self._compute_hint_path()
            self.hint_path = path
            self.hint_mirror_path = mirror
            self.hint_visible = path is not None
            self.guard.reset()
        else:
            self.hint_visible = not self.hint_visible

    def toast(self, text, frames=110):
        self.toast_text = text
        self.toast_timer = frames

    def _cycle_start_position(self, delta):
        """Q / E: make the previous / next Start Pos active and restart the
        attempt there right away.  Practice checkpoints belong to the start
        position they were dropped from, so they go with it."""
        starts = start_objects(self.objects)
        if len(starts) < 2:
            self.toast("Level has only one Start Position")
            return
        new_start = cycle_active_start(self.objects, delta)
        index = next(i for i, o in enumerate(start_objects(self.objects))
                     if o is new_start) + 1
        self.start_x = None          # a test-from-cursor spawn no longer applies
        self.player.checkpoints.clear()
        self.paused = False
        # A cached hint path was solved from the previous Start Pos — it
        # is meaningless (often unwinnable outright) from this one, so
        # drop it rather than show a stale "solved" badge for the wrong
        # spawn.
        self.hint_path = None
        self.hint_mirror_path = None
        self.hint_status = ""
        self.hint_visible = False
        self.reset_attempt()
        self.toast(f"Start Position {index}/{len(starts)}")

    def _handle_key(self, key):
        """Returns a session result to exit with, or None."""
        p = self.player
        can_slow = self.editor_test or self.practice_mode
        if key == pygame.K_ESCAPE:
            if self.paused:
                self.paused = False
                self.guard.reset()
                return None
            return self._finish("menu" if p.won else "quit")
        if key == pygame.K_p and not p.won:
            if self.is_sim_run and p.alive:
                # One-way takeover: the human drives from here on.
                self.manual_takeover = True
                self.takeover_idle_frames = 0
                self.pending_presses = 0
            else:
                self.paused = not self.paused
                self.guard.reset()
        elif key == pygame.K_m:
            self._toggle_music_mute()
        elif key == pygame.K_n:
            sfx.toggle_mute()
        elif key == pygame.K_r and not p.won:
            self.reset_attempt()
        elif (key in (pygame.K_q, pygame.K_e) and not p.won
              and not self.is_sim_run):
            self._cycle_start_position(-1 if key == pygame.K_q else 1)
        elif key == pygame.K_c and self.practice_mode and p.alive and not p.won:
            p.save_checkpoint()
            sfx.play("practice_checkpoint", 0.4)
        elif (key == pygame.K_x and self.practice_mode and p.alive
              and not p.won and p.checkpoints):
            p.checkpoints.pop()
            sfx.play("click", 0.5)
        elif key == pygame.K_b and not self.is_sim_run and not p.won:
            self._open_bot_menu()
        elif key == pygame.K_F3:
            self.show_debug = not self.show_debug
        elif key == pygame.K_i:
            self.show_state = not self.show_state
        elif key == pygame.K_F1 or (key == pygame.K_SLASH
                                    and pygame.key.get_mods() & pygame.KMOD_SHIFT):
            from .menus import help_modal, _PLAY_HELP_GROUPS
            title = "Practice — Help" if self.practice_mode else "Play — Help"
            help_modal(self.screen, self.clock, title, _PLAY_HELP_GROUPS)
            self.guard.reset()
        elif (key == pygame.K_h and not self.is_sim_run and not p.won
              and self.practice_mode):
            self._toggle_hint()
        elif can_slow and key in (pygame.K_LEFTBRACKET, pygame.K_MINUS):
            self.test_speed_idx = max(0, self.test_speed_idx - 1)
        elif can_slow and key in (pygame.K_RIGHTBRACKET, pygame.K_EQUALS):
            self.test_speed_idx = min(len(TEST_SPEEDS) - 1, self.test_speed_idx + 1)
        elif can_slow and key in (pygame.K_0, pygame.K_BACKQUOTE):
            self.test_speed_idx = len(TEST_SPEEDS) - 1
        return None

    def _poll_input(self):
        """Drain the event queue.  Returns ``(result, clicked_pos)``;
        ``result`` is non-None when the session should exit."""
        new_presses = 0
        clicked_pos = None
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if ev.type == pygame.KEYDOWN:
                result = self._handle_key(ev.key)
                if result is not None:
                    return result, None
                if ev.key in (pygame.K_SPACE, pygame.K_UP, pygame.K_w):
                    new_presses += 1
            elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if not self.guard.consume_click(ev):
                    continue
                clicked_pos = ev.pos
                new_presses += 1
            elif ev.type == pygame.JOYBUTTONDOWN:
                if ev.button == gamepad.BTN_PAUSE and not self.player.won:
                    self.paused = not self.paused
                    self.guard.reset()
                    gamepad.reset_edge_state()
                elif ev.button == gamepad.BTN_BACK:
                    if self.paused:
                        self.paused = False
                        self.guard.reset()
                    elif self.player.won:
                        return self._finish("menu"), None
        keys = pygame.key.get_pressed()
        self.jump_held = bool(keys[pygame.K_SPACE] or keys[pygame.K_UP]
                              or keys[pygame.K_w] or self.guard.mouse_held()
                              or gamepad.jump_held())
        # Polled rising edge (gamepad / input shims that skip the queue).
        if self.jump_held and not self.prev_input_held and new_presses == 0:
            new_presses += 1
        self.prev_input_held = self.jump_held
        # Presses are counted, not latched: each one becomes exactly one
        # physics-tick press even when several land between frames.
        self.pending_presses += new_presses
        return None, clicked_pos

    def _handle_pause_click(self, pos):
        b = self.pause_menu_buttons
        if self.r_mute_music.collidepoint(pos):
            self._toggle_music_mute()
        elif self.r_mute_sfx.collidepoint(pos):
            sfx.toggle_mute()
        elif b["resume"].collidepoint(pos):
            self.paused = False
            self.guard.reset()
        elif b["restart"].collidepoint(pos):
            self.reset_attempt()
            self.paused = False
            self.guard.reset()
        elif b["practice_toggle"].collidepoint(pos):
            self.practice_mode = not self.practice_mode
            self.player.practice_mode = self.practice_mode
            self.guard.reset()
        elif b["settings"].collidepoint(pos):
            from .menus import run_settings
            if self.level_music and music.is_playing():
                music.stop()
            run_settings(self.screen, self.clock)
            self._start_music()
            self.guard.reset()
        elif b["menu"].collidepoint(pos):
            return self._finish("menu")
        self.pending_presses = 0
        return None

    def _handle_win_click(self, pos):
        if self.rc_menu.collidepoint(pos):
            return self._finish("menu")
        if self.rc_replay.collidepoint(pos):
            self.reset_attempt()
            self.attempts = 1
            self.win_sfx_played = False
            self.guard.reset()
        return None

    # ---- physics ---------------------------------------------------------
    def _step_scale(self):
        scale = (TEST_SPEEDS[self.test_speed_idx]
                 if (self.editor_test or self.practice_mode) else 1.0)
        if self.death_slowmo_timer > 0:
            scale *= 0.2
            self.death_slowmo_timer -= 1
        # A "0" time-warp trigger is a legitimate slow-mo-to-a-crawl value
        # in the editor, but a literal 0 multiplier stops physics forever
        # with no way for the player to reach whatever would undo it — so
        # floor it just above zero instead of allowing a hard freeze.
        return scale * max(0.01, min(10.0, float(self.player.time_warp)))

    def _tick_input(self):
        """Pick this tick's ``(held, pressed)`` from human / bot / playback."""
        if self.manual_takeover or (self.bot_controller is None
                                    and self.playback_inputs is None):
            pressed = self.pending_presses > 0
            if pressed:
                self.pending_presses -= 1
            if self.manual_takeover:
                if self.jump_held or pressed:
                    self.takeover_idle_frames = 0
                else:
                    self.takeover_idle_frames += 1
            return self.jump_held, pressed
        if self.bot_controller is not None:
            return self.bot_controller.compute_input(self.player)
        if self.bot_frame < len(self.playback_inputs):
            held, pressed = self.playback_inputs[self.bot_frame]
        else:
            held, pressed = False, False
        self.bot_frame += 1
        return held, pressed

    def _tick_alive(self):
        p = self.player
        before_passed = set(p.passed)
        before_pads = sum(1 for k in before_passed if k[0] in PAD_TYPES)
        before_coins = len(p.coins_collected)
        held, pressed = self._tick_input()
        p.update(held, pressed)
        if (self.manual_takeover and p.alive and not p.won
                and self.takeover_idle_frames >= MANUAL_TAKEOVER_GRACE):
            p.alive = False
            p.death_reason = p.death_reason or "Took over but stopped pressing"
        if self.is_sim_run:
            self._note_bot_click(held)
        if self.playback_wp_sorted and self.playback_inputs is not None:
            self._check_playback_drift()
        if p.alive and p.dash_timer > 0:
            self.particles.dash_trail(p.x + p.size / 2, p.y + p.size / 2,
                                      p.dash_vx, p.dash_vy, C_DASH_ORB)
        self.attempt_frames += 1
        if self.attempt_frames % 2 == 0:
            self.current_run.append((self.attempt_frames, p.x, p.y))
        if not p.camera_locked:
            self.cam_x = p.x - CAMERA_LEAD_PX
        after_passed = set(p.passed)
        _play_interaction_sounds(
            before_passed, after_passed, before_pads,
            sum(1 for k in after_passed if k[0] in PAD_TYPES),
            before_coins, len(p.coins_collected))
        if p._checkpoint_request:
            p._checkpoint_request = False
            if self.practice_mode and p.practice_mode:
                p.save_checkpoint()
                sfx.play("practice_checkpoint", 0.4)
        progress_now = int(max(0.0, min(1.0, p.x / self.max_x)) * 100)
        if progress_now > self.best_progress:
            self.best_progress = progress_now
            self._record_practice_progress(progress_now)
        if len(p.coins_collected) > self.best_coins_this_run:
            self.best_coins_this_run = len(p.coins_collected)

    def _note_bot_click(self, held):
        """Click cue for bot / playback runs: a click is a False->True
        edge of the held input (ship / wave never set ``pressed``)."""
        click_now = held and not self.prev_b_held
        self.prev_b_held = held
        if click_now:
            if prefs.get("bot_click_sfx_enabled", True):
                sfx.play("bot_click", 0.5)
            self.bot_click_flash = 12
            self.bot_press_frames.append(self.attempt_frames)
            self.bot_press_total += 1
        elif self.bot_click_flash > 0:
            self.bot_click_flash -= 1

    def _check_playback_drift(self):
        """Compare live y against the recorded waypoint at this x so a
        desynced replay is flagged before it dies to a 'ghost spike'."""
        p = self.player
        px = p.x + p.size / 2
        xs = self.playback_wp_xs
        pts = self.playback_wp_sorted
        if px <= xs[0]:
            exp_y = pts[0][1]
        elif px >= xs[-1]:
            exp_y = pts[-1][1]
        else:
            lo, hi = 0, len(xs) - 1
            while hi - lo > 1:
                mid = (lo + hi) // 2
                if xs[mid] <= px:
                    lo = mid
                else:
                    hi = mid
            x0, y0 = pts[lo]
            x1, y1 = pts[hi]
            span = x1 - x0
            t = 0.0 if span <= 1e-9 else (px - x0) / span
            exp_y = y0 + (y1 - y0) * t
        drift = abs((p.y + p.size / 2) - exp_y)
        self.desync_max_px = max(self.desync_max_px, drift)
        if drift > DESYNC_ALERT_PX:
            self.desync_alert_timer = 30
        elif self.desync_alert_timer > 0:
            self.desync_alert_timer -= 1

    def _on_death(self):
        p = self.player
        self.particles.explosion(p.x + p.size / 2, p.y + p.size / 2, C_PLAYER)
        apply_shake(12)
        sfx.play("death", 0.6)
        if self.level_music:
            music.stop()
        self.death_hitbox = (p.x, p.y, p.size, p.angle, p.death_reason)
        self.death_timer = DEATH_FRAMES
        self.death_slowmo_timer = DEATH_SLOWMO_FRAMES
        self.death_flash_timer = 30
        self.deaths_this_session += 1
        self.pending_presses = 0

    def _tick_camera(self):
        p = self.player
        if p.free_cam_mode:
            p.target_cam_y = p.y + p.size / 2 - HEIGHT / 2
        self.prev_cam_y = self.cam_y
        if not p.camera_locked:
            if p.free_cam_mode:
                # Continuous tracking (e.g. resumed "follow" mode): the
                # target moves every tick, so a fixed-duration ease has
                # no fixed endpoint to aim at — keep the old responsive
                # exponential chase.
                self._cam_pan_len = 1
                dy = (p.target_cam_y - self.cam_y) * CAM_Y_EASE
                self.cam_y += max(-CAM_Y_MAX_STEP, min(CAM_Y_MAX_STEP, dy))
            else:
                # One-shot "pan" trigger: ease smoothly to the target
                # over the trigger's configured duration instead of a
                # magic-number exponential chase, so mappers control how
                # smooth/fast the transition looks.
                if p.target_cam_y != self._cam_pan_target:
                    self._cam_pan_target = p.target_cam_y
                    self._cam_pan_start = self.cam_y
                    self._cam_pan_timer = 0
                    self._cam_pan_len = max(1, round(p.cam_pan_duration * PHYSICS_RATE))
                if self._cam_pan_timer < self._cam_pan_len:
                    self._cam_pan_timer += 1
                    t = self._cam_pan_timer / self._cam_pan_len
                    t = t * t * (3.0 - 2.0 * t)  # smoothstep
                    self.cam_y = (self._cam_pan_start
                                 + (self._cam_pan_target - self._cam_pan_start) * t)
                else:
                    self.cam_y = self._cam_pan_target
        target_top, target_bot = BG_PRESETS[p.bg_preset % len(BG_PRESETS)]
        for i in range(3):
            self.bg_top[i] += (target_top[i] - self.bg_top[i]) * 0.06
            self.bg_bot[i] += (target_bot[i] - self.bg_bot[i]) * 0.06

    def _tick(self):
        """One fixed physics tick."""
        p = self.player
        if self.death_timer > 0:
            self.death_timer -= 1
            if self.death_timer <= 0:
                if self.practice_mode and p.practice_mode and p.checkpoints:
                    p.load_checkpoint()
                    self.prev_input_held = False
                    self.pending_presses = 0
                else:
                    self.reset_attempt()
        elif p.alive and not p.won and not self.paused:
            self._tick_alive()
        elif not p.alive and self.death_timer == 0:
            self._on_death()
        self.particles.update()
        self._tick_camera()

    def _advance_physics(self):
        """Run as many ticks as wall-clock time owes us."""
        self.sim_accum += self.last_dt_sec * PHYSICS_RATE * self._step_scale()
        # Never try to catch up more than half a second (debugger stall).
        self.sim_accum = min(self.sim_accum, PHYSICS_RATE * 0.5)
        while self.sim_accum >= 1.0:
            self.sim_accum -= 1.0
            self._tick()

    # ---- render ------------------------------------------------------------
    def _render(self, mpos):
        p = self.player
        # Interpolate between the last two ticks; while the game is not
        # advancing (pause / dead) draw the latest pose.
        alpha = self.sim_accum if (p.alive and not p.won and not self.paused) else 1.0
        rx, _ry, _ = p.render_pose(alpha)
        cam_x = (rx - CAMERA_LEAD_PX
                 if self.death_timer == 0 and not p.camera_locked
                 else self.cam_x)
        cam_y = self.prev_cam_y + (self.cam_y - self.prev_cam_y) * alpha
        update_shake()
        shake_x, shake_y = shake_offset
        s = self.screen
        os_ = self.overlay_scratch
        render_world(s, cam_x, cam_y, shake_x, shake_y, self.stars,
                     self.mountains, self.bg_top, self.bg_bot, self.pulse,
                     self.deco_layer, self.deco_xs, self.main_layer,
                     self.main_xs, p.coins_collected)
        render_hint_overlay(s, os_, self.CLEAR, self.hint_visible,
                            self.hint_path, self.hint_mirror_path, cam_x, cam_y,
                            shake_x, shake_y)
        render_predicted_path(s, os_, self.CLEAR, self.pred_path_sorted,
                              self.pred_path_xs, p.x, p.size, cam_x, cam_y,
                              shake_x, shake_y)
        render_ghost_paths(s, os_, self.CLEAR, self.ghost_paths, self.bot_frame,
                           self.playback_inputs, self.bot_controller,
                           cam_x, cam_y, shake_x, shake_y)
        render_death_hitbox_marker(s, os_, self.CLEAR, self.predicted_path,
                                   self.death_hitbox, self.death_timer,
                                   cam_x, cam_y, shake_x, shake_y)
        render_best_run_ghost(s, os_, self.CLEAR, self.best_run,
                              self.attempt_frames, cam_x, cam_y, shake_x, shake_y)
        render_player_and_particles(s, p, self.particles, self.death_timer,
                                    self.bot_click_flash, cam_x, cam_y,
                                    shake_x, shake_y, alpha)
        render_checkpoint_markers(s, self.practice_mode, p, self.pulse,
                                  cam_x, cam_y, shake_x, shake_y)
        render_blackout(s, os_, p.blackout_value)
        render_death_reason(s, self.death_timer, p)
        render_toast(s, self.toast_text, self.toast_timer)
        render_slowmo_vignette(s, os_, self.CLEAR, self.death_slowmo_timer)
        render_pulse_flash(s, os_, p.pulse_intensity())
        if self.death_flash_timer > 0:
            self.death_flash_timer -= 1
        render_hud(s, p, self.max_x, self.attempts, self.attempt_frames,
                   self.meta, self.is_sim_run, self.bot_press_frames,
                   self.bot_press_total, self.manual_takeover,
                   self.takeover_idle_frames, MANUAL_TAKEOVER_GRACE,
                   self.level_name, self.total_coins, self.practice_mode,
                   self.hint_visible, self.hint_path, self.hint_status,
                   self.editor_test, self.test_speed_idx, TEST_SPEEDS,
                   self.bot_controller, self.playback_inputs, self.bot_frame,
                   self.playback_wp_sorted, self.desync_alert_timer,
                   self.desync_max_px)
        render_debug_overlay(s, self.show_debug, self.objects, cam_x, cam_y,
                             p, self.attempts, self.dbg_frame_times)
        render_state_hud(s, self.show_state, p)
        self.r_mute_music, self.r_mute_sfx = render_pause_overlay(
            s, self.paused, mpos, self.attempts, p, self.max_x,
            self.practice_mode, self.pause_menu_buttons)
        self.win_sfx_played = render_win_overlay(
            s, p, mpos, self.win_sfx_played, self.level_music, self.meta,
            self.attempts, self.deaths_this_session, self.attempt_frames,
            self.total_coins, self.meta_persisted, self.is_sim_run,
            self.rc_menu, self.rc_replay, self._persist_win)
        pygame.display.flip()

    # ---- main loop ---------------------------------------------------------
    def run(self):
        self._start_music()
        while True:
            self.guard.tick()
            self.pulse += 1
            if self.toast_timer > 0:
                self.toast_timer -= 1
            mpos = pygame.mouse.get_pos()
            result, clicked_pos = self._poll_input()
            if result is not None:
                return result
            if clicked_pos:
                if self.paused:
                    result = self._handle_pause_click(clicked_pos)
                elif self.player.won:
                    result = self._handle_win_click(clicked_pos)
                if result is not None:
                    return result
            self._advance_physics()
            self._render(mpos)
            # tick() sleeps to honour the cap and returns the elapsed ms,
            # which drives the next frame's physics accumulator.
            self.last_dt_sec = self.clock.tick(settings.get_fps_cap()) / 1000.0


def run_play(screen, clock, objects, level_name="Level", editor_test=False,
             practice_mode=False, level_music=None, bot_controller=None,
             playback_inputs=None, playback_waypoints=None, meta=None,
             level_path=None, out_hitboxes=None, out_mirror_hitboxes=None,
             start_x=None, predicted_path=None, ghost_paths=None, noclip=False):
    """Run a single play session and return ``"menu"`` or ``"quit"``.

    ``meta`` / ``level_path`` let a hand-played win persist verification,
    attempts, best progress and coins.  ``out_hitboxes`` /
    ``out_mirror_hitboxes`` (lists, mutated in place) receive the
    per-tick ``(x, y, size, angle)`` trace of the deepest attempt for the
    editor overlay.  ``start_x`` spawns the player mid-level with the
    music seeked to match.  ``predicted_path`` / ``ghost_paths`` are the
    Y-bot overlays (see :mod:`play_render`).
    """
    session = PlaySession(
        screen, clock, objects, level_name=level_name, editor_test=editor_test,
        practice_mode=practice_mode, level_music=level_music,
        bot_controller=bot_controller, playback_inputs=playback_inputs,
        playback_waypoints=playback_waypoints, meta=meta, level_path=level_path,
        out_hitboxes=out_hitboxes, out_mirror_hitboxes=out_mirror_hitboxes,
        start_x=start_x, predicted_path=predicted_path, ghost_paths=ghost_paths,
        noclip=noclip)
    return session.run()
