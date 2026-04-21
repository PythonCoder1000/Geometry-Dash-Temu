"""Gameplay loop.

Runs a single play session — handles input, physics stepping (via Player),
HUD rendering, pause/win overlays, practice-mode checkpoints, and — on a
legitimate win — bumps the level's ``verified`` / ``best_progress`` /
``coins_collected`` metadata so the playlist can mark it verified.
"""

import bisect
import math
import sys

import pygame

from .constants import (
    WIDTH, HEIGHT, CELL, FPS,
    C_DARK, C_PLAYER, C_GRAY, C_WHITE, C_BTN, C_BG_TOP, C_BG_BOT,
    C_COIN, C_SUCCESS, C_PUBLISH, C_DANGER,
    DECORATION_TYPES, TRIGGER_TYPES, BG_PRESETS, PAD_TYPES,
    T_TELEPORT_ORB, T_COIN, T_END, T_ORB, T_DASH_ORB, T_BLACK_ORB,
    T_BLUE_ORB, T_GREEN_ORB, T_GRAV,
    ADMIN_USERNAME,
)
from .graphics import (
    draw_bg, draw_obj, txt, btn, make_rect, make_stars, make_mountains,
    update_shake, apply_shake, shake_offset, lighter, darker,
    speaker_icon, icon_button, draw_end_wall,
)
from . import settings
from . import gamepad
from . import music
from . import sfx
from .input_guard import ClickGuard
from .particles import Particles
from .player import Player
from .levels import update_meta


# Keys / cells that, when added to player.passed during an update(),
# should trigger a named SFX.
_SFX_FOR_TYPE = {
    T_ORB: ("orb", 0.5),
    T_DASH_ORB: ("orb", 0.55),
    T_BLACK_ORB: ("orb", 0.5),
    T_BLUE_ORB: ("gravity", 0.45),
    T_GREEN_ORB: ("orb", 0.5),
    T_GRAV: ("gravity", 0.45),
}


def _total_coins(objects):
    return sum(1 for o in objects if o["t"] == T_COIN)


def _play_interaction_sounds(before_passed, after_passed, before_pads, after_pads,
                             before_coins, after_coins):
    """Emit one-shot SFX for orbs/pads/coins consumed this frame."""
    for key in after_passed - before_passed:
        t = key[0] if isinstance(key, tuple) and key else None
        info = _SFX_FOR_TYPE.get(t)
        if info:
            sfx.play(*info)
    if after_pads > before_pads:
        sfx.play("pad", 0.5)
    if after_coins > before_coins:
        sfx.play("click", 0.55)


def run_play(screen, clock, objects, level_name="Level", editor_test=False,
             practice_mode=False, level_music=None, bot_controller=None,
             playback_inputs=None, meta=None, level_path=None,
             out_hitboxes=None, start_x=None):
    """Run a single play session.

    ``meta`` / ``level_path`` (optional) are used to persist verification,
    attempts, best_progress and coins_collected when the player finishes a
    published level by hand (not via autobot / playback / editor-test).

    ``out_hitboxes`` (optional list, mutated in place): if given, populated
    with ``(x, y, size)`` tuples for each frame of the *most recent*
    completed attempt. The list is cleared and refilled on every restart so
    the editor's "show hitboxes from last run" overlay always reflects the
    final attempt the user took before exiting back to the editor.

    ``start_x`` (optional, pixels): teleport the player this far into
    the level on spawn (and restart). The music is seeked to the
    matching offset so the beat still lines up with the level layout
    at the spawn position — essential for "test from cursor" when the
    level is beat-synced.
    """
    objects = [dict(o) for o in objects]
    total_coins = _total_coins(objects)
    # Per-level physics override (B5): `meta["physics"]` is a flat dict of
    # tunables; absent → vanilla defaults. Built here rather than inside
    # Player so bot replays / editor tests see the same per-level feel.
    from .physics import PhysicsParams
    params = PhysicsParams.from_meta(meta)
    player = Player(objects, params=params)
    player.practice_mode = practice_mode
    # Music-seek offset in seconds matching ``start_x``. Level traversal
    # runs at `move_speed` px/frame × 60 fps — nominally 300 px/sec so
    # a 1500px start_x seeks 5 s into the track.
    _music_offset_sec = 0.0
    if start_x and start_x > 0:
        pps = max(1.0, float(player.params.base_move_speed) * 60.0)
        _music_offset_sec = max(0.0, float(start_x) / pps)
    particles = Particles()
    stars = make_stars()
    mountains = make_mountains()
    cam_x = 0.0
    cam_y = 0.0
    bg_top = [float(c) for c in C_BG_TOP]
    bg_bot = [float(c) for c in C_BG_BOT]
    attempts = 1
    death_timer = 0
    death_slowmo_timer = 0
    death_flash_timer = 0
    # Speedrun timer: frames elapsed in the current attempt (resets on death,
    # resumes from 0 on each restart). Persisted as best_time_frames on win.
    attempt_frames = 0
    deaths_this_session = 0
    # Ghost replay: list of (frame, x, y) sampled every few frames of the
    # current attempt. On death/win, if this attempt got further than the
    # best run so far, it becomes the new ghost. Drawn on subsequent attempts
    # to show the player their previous best path. In-memory only.
    current_run = []
    best_run = []
    best_run_progress_x = 0.0

    # Hitbox recording for the editor's "show hitboxes from best run" view.
    # `current_hitboxes` is the in-progress per-attempt buffer.
    # `best_hitboxes_progress` tracks how far the best-committed trace got;
    # we only overwrite `out_hitboxes` when a new attempt beats that mark.
    # Showing the deepest attempt instead of the most-recent is what the
    # overlay is actually useful for — a last-attempt death on frame 1
    # shouldn't blow away a trace that made it to 80% on the run before.
    current_hitboxes = []
    best_hitboxes_progress = 0.0

    is_sim_run = bool(bot_controller is not None or playback_inputs is not None)
    # Don't persist progress for editor-test runs or bot/playback runs.
    can_persist = (not editor_test) and (not is_sim_run) and (level_path is not None)

    # Hint mode (autobot ghost overlay): on first H press we run the solver
    # and cache the waypoints; subsequent H presses just toggle the overlay
    # so the expensive search doesn't repeat. Disabled in sim runs because
    # the autobot would be racing itself.
    hint_path = None          # list of (x, y) waypoints when computed
    hint_mirror_path = None   # parallel mirror path for dual segments
    hint_visible = False
    hint_solving = False
    hint_status = ""          # "" | "ok" | "partial" | "failed"
    # Debug overlay: FPS, player state, frame time. Toggled with F3.
    show_debug = False
    _dbg_frame_times = []

    # GD-style music: play level music from the start. We used to gate
    # this on `not editor_test` (so the editor's Test button stayed silent),
    # but the editor now passes level_music through specifically when the
    # user wants test-mode music — so we just check level_music. Bot and
    # playback runs from the editor still pass level_music=None and stay
    # silent, since their variable speeds don't sync to audio.
    if level_music:
        music.stop()
        music.play_file(level_music, start_sec=_music_offset_sec)

    def _restart_level_music():
        """Restart level music — seeked to `start_x`'s offset if set,
        otherwise from the beginning (GD-style on death). Keeps music in
        sync with the level position when testing from cursor."""
        if level_music:
            music.stop()
            music.play_file(level_music, start_sec=_music_offset_sec)

    def _toggle_music_mute():
        """Toggle music mute without reverting to the menu track mid-level."""
        if music.is_muted():
            music.set_enabled(True)
            if level_music:
                music.play_file(level_music)
        else:
            music.set_enabled(False)

    pulse = 0
    max_x = max((o["x"] for o in objects), default=10) * CELL + CELL

    # Win-screen buttons
    rc_menu = make_rect(WIDTH // 2 - 120, HEIGHT // 2 + 80, 180, 50)
    rc_replay = make_rect(WIDTH // 2 + 120, HEIGHT // 2 + 80, 180, 50)

    prev_input_held = False
    sim_accum = 0.0
    # Last render-frame wall duration in seconds. Used to advance
    # `sim_accum` at a rate driven by the Settings-configured TPS value,
    # decoupled from the render FPS cap.
    last_dt_sec = 1.0 / 60.0
    pending_jump_press = False
    bot_frame = 0
    test_speeds = [0.01, 0.05, 0.1, 0.25, 0.5, 1.0]
    test_speed_idx = len(test_speeds) - 1
    # Apply start_x on the initial spawn too (the `_full_reset` path
    # handles subsequent attempts).
    if start_x and start_x > 0:
        player.x = float(start_x)
        player._x_at_frame_start = player.x
    # Two lists sorted by x — decorations drawn first (behind), then the rest.
    # Pre-extracted x arrays enable bisect to slice directly to the visible
    # window instead of scanning every non-trigger object per frame.
    # Sort by _orig_x (stable across moves), since move triggers mutate
    # o["x"] during play and would desync the sorted order otherwise.
    _draw_pool = [o for o in objects if o["t"] not in TRIGGER_TYPES]
    _deco_layer = sorted(
        (o for o in _draw_pool if o["t"] in DECORATION_TYPES),
        key=lambda o: o.get("_orig_x", o["x"]),
    )
    _main_layer = sorted(
        (o for o in _draw_pool if o["t"] not in DECORATION_TYPES),
        key=lambda o: o.get("_orig_x", o["x"]),
    )
    _deco_xs = [o.get("_orig_x", o["x"]) for o in _deco_layer]
    _main_xs = [o.get("_orig_x", o["x"]) for o in _main_layer]

    # One reusable fullscreen alpha surface for the per-frame overlays
    # (hint path, ghost, death flash, vignette, pulse, checkpoint flash).
    # Clear to transparent before each use — far cheaper than allocating a
    # fresh Surface every frame.
    _overlay_scratch = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    _CLEAR = (0, 0, 0, 0)

    # Pause menu state
    paused = False
    pause_menu_buttons = {
        "resume": make_rect(WIDTH // 2, HEIGHT // 2 - 60, 220, 48),
        "restart": make_rect(WIDTH // 2, HEIGHT // 2 - 6, 220, 48),
        "practice_toggle": make_rect(WIDTH // 2, HEIGHT // 2 + 48, 220, 48),
        "settings": make_rect(WIDTH // 2, HEIGHT // 2 + 102, 220, 48),
        "menu": make_rect(WIDTH // 2, HEIGHT // 2 + 156, 220, 48),
    }
    # Mute icon rects (populated each frame; only hit-tested while paused)
    r_mute_music = pygame.Rect(0, 0, 0, 0)
    r_mute_sfx = pygame.Rect(0, 0, 0, 0)

    # Practice mode checkpoint state
    checkpoint_flash_timer = 0

    # Click-through guard: the mouse-button press that brought us INTO play
    # should not be interpreted as an in-game jump on the first frame.
    # Reset on every state transition (pause, restart, win screen) so the
    # transition click never doubles as a jump in the next state.
    guard = ClickGuard()
    win_sfx_played = False
    meta_persisted = False
    best_progress = 0  # % for this session (used for save)
    best_coins_this_run = 0

    def _full_reset():
        """Reset for a fresh attempt — resets player + all local loop state."""
        nonlocal attempts, death_timer, death_slowmo_timer, death_flash_timer
        nonlocal prev_input_held, pending_jump_press, sim_accum, bot_frame
        nonlocal cam_y, bg_top, bg_bot
        nonlocal attempt_frames, current_run, best_run, best_run_progress_x
        nonlocal current_hitboxes, best_hitboxes_progress
        # Commit the finished attempt as the new ghost if it got further.
        if current_run and current_run[-1][1] > best_run_progress_x:
            best_run = list(current_run)
            best_run_progress_x = current_run[-1][1]
        current_run = []
        # Commit this attempt's hitbox trace to the editor overlay ONLY
        # if it beat the furthest trace we've seen. That keeps the H-key
        # overlay anchored on the most-informative run rather than being
        # clobbered by the next panicked restart.
        if (out_hitboxes is not None and current_hitboxes
                and player.x >= best_hitboxes_progress):
            out_hitboxes[:] = current_hitboxes
            best_hitboxes_progress = player.x
        current_hitboxes = []
        player.reset()
        # Honour the test-from-cursor start position — player.reset
        # puts the cube at the level's START object, so we teleport
        # after reset to land at `start_x`. Camera re-derives from it
        # below.
        if start_x and start_x > 0:
            player.x = float(start_x)
            player._x_at_frame_start = player.x
        attempts += 1
        death_timer = 0
        death_slowmo_timer = 0
        death_flash_timer = 0
        attempt_frames = 0
        prev_input_held = False
        pending_jump_press = False
        sim_accum = 0.0
        if bot_controller:
            bot_controller.reset()
        bot_frame = 0
        cam_y = 0.0
        bg_top[:] = [float(c) for c in C_BG_TOP]
        bg_bot[:] = [float(c) for c in C_BG_BOT]
        _restart_level_music()

    def _stop_music_and_return(result):
        if level_music:
            music.stop()
        # Commit the in-progress hitbox buffer on exit too — otherwise a
        # user who walks away mid-attempt loses the trace they just made.
        # Same "best attempt wins" guard as _full_reset: don't overwrite a
        # longer saved trace with a shorter exit-trace.
        if (out_hitboxes is not None and current_hitboxes
                and player.x >= best_hitboxes_progress):
            out_hitboxes[:] = current_hitboxes
        # Persist Best% Normal on exit even when the player didn't win.
        # Without this the carousel's "Best — Normal" bar never changes
        # for levels a player is still trying to beat. Practice runs
        # go to the local practice-best store instead.
        if (level_path and can_persist and not practice_mode
                and best_progress > 0):
            try:
                prev_best = int((meta or {}).get("best_progress", 0))
                if best_progress > prev_best:
                    update_meta(level_path, best_progress=best_progress)
                    if meta is not None:
                        meta["best_progress"] = best_progress
            except Exception:
                pass
        return result

    def _compute_hint_path():
        """Run the autobot once and cache its waypoints for the H overlay.

        Returns ``(status, waypoints, mirror_waypoints)`` where ``status``
        is ``"ok"|"partial"|"failed"``. ``mirror_waypoints`` is the dual
        mirror's parallel path (empty list when the level never goes dual).
        The solver shows its own progress UI so we don't need to draw
        anything here. We pass the ORIGINAL objects (pre-_orig_x mutations)
        so the simulator starts from the same level layout the player is
        currently attempting.
        """
        try:
            from .autobot import AutoBot
            # Strip the _orig_x/_orig_y bookkeeping fields the live Player
            # added — the solver expects clean object dicts.
            clean = []
            for o in objects:
                co = {k: v for k, v in o.items()
                      if not (isinstance(k, str) and k.startswith("_"))}
                clean.append(co)
            solver = AutoBot(clean, params=player.params)
            wp, mwp, _inputs, won = solver.solve(screen, clock)
            if not wp:
                return "failed", None, None
            return ("ok" if won else "partial"), list(wp), list(mwp)
        except Exception:
            return "failed", None, None

    def _persist_win():
        """Persist meta: attempts / best_progress / coins_collected / etc.

        Every player's win records their session stats. *Verifying* a
        published level — flipping the ✓ and stamping the canonical
        difficulty — is admin-only (constants.ADMIN_USERNAME). A
        non-admin win on an unverified published level still counts
        toward attempts / best / coins / best-time / deaths, but it
        never flips `verified` and never shows the difficulty prompt.
        """
        nonlocal meta_persisted
        if meta_persisted or not can_persist:
            return
        prev_attempts = int((meta or {}).get("attempts", 0)) if meta else 0
        prev_coins = int((meta or {}).get("coins_collected", 0)) if meta else 0
        prev_best = int((meta or {}).get("best_progress", 0)) if meta else 0
        prev_best_time = int((meta or {}).get("best_time_frames", 0)) if meta else 0
        coins_now = len(player.coins_collected)
        # Best time: lower wins. 0 means no prior record.
        if prev_best_time <= 0:
            new_best_time = attempt_frames
        else:
            new_best_time = min(prev_best_time, attempt_frames)

        prev_deaths = int((meta or {}).get("deaths", 0)) if meta else 0
        updates = {
            "attempts": prev_attempts + attempts,
            "best_progress": max(prev_best, 100),
            "coins_collected": max(prev_coins, coins_now),
            "best_time_frames": new_best_time,
            "deaths": prev_deaths + deaths_this_session,
        }
        # Admin-only verification path: only the ADMIN_USERNAME account
        # can flip `verified` and stamp an official difficulty on a
        # published level. Anyone else's first win still bumps their
        # session stats above but leaves the rating untouched.
        from .prefs import get as _pget_usr
        _cur_user = _pget_usr("signed_in_username", None)
        _is_admin = (_cur_user == ADMIN_USERNAME)
        if _is_admin:
            updates["verified"] = True
            if meta and meta.get("published") and not meta.get("verified"):
                from .menus import difficulty_picker
                requested = meta.get("requested_difficulty",
                                     meta.get("difficulty", "Normal"))
                chosen = difficulty_picker(
                    screen, clock,
                    prompt="You verified this level!",
                    default=requested,
                    subtitle=f"Publisher requested: {requested}.  "
                             f"Set the official difficulty:",
                )
                if chosen:
                    updates["difficulty"] = chosen
        try:
            update_meta(level_path, **updates)
            meta_persisted = True
            # Also mirror the updates into the in-memory `meta` dict so
            # later exit-time bookkeeping (_stop_music_and_return) sees
            # the 100% best, not the pre-win stale value — otherwise
            # the session's sub-100 best_progress would "win" a >
            # compare against stale meta and clobber the disk's 100%.
            if meta is not None:
                meta.update(updates)
        except OSError:
            # If the file is gone, just skip persistence.
            pass

    while True:
        guard.tick()
        pulse += 1
        mpos = pygame.mouse.get_pos()
        mouse_pressed_this_frame = False
        clicked_pos = None
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    if paused:
                        paused = False
                        guard.reset()
                    elif player.won:
                        return _stop_music_and_return("menu")
                    else:
                        return _stop_music_and_return("quit")
                elif ev.key == pygame.K_p and not player.won:
                    paused = not paused
                    guard.reset()
                elif ev.key == pygame.K_m:
                    _toggle_music_mute()
                elif ev.key == pygame.K_n:
                    sfx.toggle_mute()
                elif ev.key == pygame.K_r and not player.won:
                    _full_reset()
                elif (ev.key == pygame.K_c and practice_mode
                      and player.alive and not player.won):
                    # Drop a checkpoint at the player's current position.
                    # Only in practice mode — normal runs have no
                    # checkpoints. The next death respawns here. A
                    # marker is drawn in-world at this position so the
                    # player can see where they planted each one
                    # (replaces the old green screen flash).
                    player.save_checkpoint()
                    sfx.play("practice_checkpoint", 0.4)
                elif (ev.key == pygame.K_x and practice_mode
                      and player.alive and not player.won
                      and player.checkpoints):
                    # Pop the most recent checkpoint. Mirrors the GD
                    # convention (C drops, X removes). If the player
                    # already queued a checkpoint-request via an orb,
                    # clear that too so the next respawn uses whatever
                    # is left in the stack.
                    player.checkpoints.pop()
                    sfx.play("click", 0.5)
                elif ev.key == pygame.K_b and not is_sim_run and not player.won:
                    # Bot menu: opens the dedicated bot UI for solving / replay.
                    from .bot_menu import run_bot_menu, get_last_mirror_waypoints
                    # Pass the level's filename (extracted from level_path)
                    # so Save/Load bot runs key off a stable identifier.
                    _lfn = None
                    if level_path:
                        import os as _os
                        _lfn = _os.path.basename(level_path)
                    result = run_bot_menu(
                        screen, clock, [dict(o) for o in objects],
                        precomputed_path=hint_path,
                        level_filename=_lfn,
                        meta=meta,
                    )
                    if result is not None:
                        # The bot menu may return new waypoints to use as
                        # the hint overlay. Subsequent H toggles will use
                        # this path instead of recomputing.
                        new_path, new_status = result
                        if new_path:
                            hint_path = new_path
                            hint_mirror_path = get_last_mirror_waypoints()
                            hint_status = new_status
                            hint_visible = True
                    guard.reset()
                elif ev.key == pygame.K_F3:
                    show_debug = not show_debug
                elif ev.key == pygame.K_F1 or (
                        ev.key == pygame.K_SLASH and
                        pygame.key.get_mods() & pygame.KMOD_SHIFT):
                    from .menus import help_modal, _PLAY_HELP_GROUPS
                    _title = "Practice — Help" if practice_mode else "Play — Help"
                    help_modal(screen, clock, _title, _PLAY_HELP_GROUPS)
                    guard.reset()
                elif (ev.key == pygame.K_h and not is_sim_run
                      and not player.won and practice_mode):
                    # Autobot hint overlay is a practice-mode learning
                    # aid — normal attempts are meant to be unaided.
                    # Hint mode: toggle the autobot ghost overlay. First
                    # press blocks while the solver runs (its built-in
                    # progress UI takes the screen). Subsequent presses
                    # toggle visibility instantly.
                    if hint_path is None and not hint_solving:
                        hint_solving = True
                        hint_status, new_path, new_mirror = _compute_hint_path()
                        hint_path = new_path
                        hint_mirror_path = new_mirror
                        hint_visible = (hint_path is not None)
                        hint_solving = False
                        guard.reset()
                    elif hint_path is not None:
                        hint_visible = not hint_visible
                elif (editor_test or practice_mode) and ev.key in (
                        pygame.K_LEFTBRACKET, pygame.K_MINUS):
                    test_speed_idx = max(0, test_speed_idx - 1)
                elif (editor_test or practice_mode) and ev.key in (
                        pygame.K_RIGHTBRACKET, pygame.K_EQUALS):
                    test_speed_idx = min(len(test_speeds) - 1, test_speed_idx + 1)
                elif (editor_test or practice_mode) and ev.key in (
                        pygame.K_0, pygame.K_BACKQUOTE):
                    test_speed_idx = len(test_speeds) - 1
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if not guard.consume_click(ev):
                    continue
                clicked_pos = ev.pos
                mouse_pressed_this_frame = True
            # Gamepad: Start toggles pause; B button acts like Esc.
            if ev.type == pygame.JOYBUTTONDOWN:
                if ev.button == gamepad.BTN_PAUSE and not player.won:
                    paused = not paused
                    guard.reset()
                    gamepad.reset_edge_state()
                elif ev.button == gamepad.BTN_BACK:
                    if paused:
                        paused = False
                        guard.reset()
                    elif player.won:
                        return _stop_music_and_return("menu")

        keys = pygame.key.get_pressed()
        # mouse_held() is the guard-aware version of get_pressed()[0] — it
        # returns False until the user has released the entry click, so a
        # button press that opened this screen never doubles as a jump.
        jump_held = (keys[pygame.K_SPACE] or keys[pygame.K_UP]
                     or keys[pygame.K_w] or guard.mouse_held()
                     or gamepad.jump_held())

        jump_pressed = mouse_pressed_this_frame or (jump_held and not prev_input_held)
        prev_input_held = jump_held
        if jump_pressed:
            pending_jump_press = True

        # Pause menu clicks — these are handled BEFORE passing input to physics,
        # and we reset the guard on every state transition out of pause so
        # the click doesn't leak into the physics tick.
        if paused and clicked_pos:
            if r_mute_music.collidepoint(clicked_pos):
                _toggle_music_mute()
            elif r_mute_sfx.collidepoint(clicked_pos):
                sfx.toggle_mute()
            elif pause_menu_buttons["resume"].collidepoint(clicked_pos):
                paused = False
                guard.reset()
            elif pause_menu_buttons["restart"].collidepoint(clicked_pos):
                _full_reset()
                paused = False
                guard.reset()
            elif pause_menu_buttons["practice_toggle"].collidepoint(clicked_pos):
                practice_mode = not practice_mode
                player.practice_mode = practice_mode
                guard.reset()
            elif pause_menu_buttons["settings"].collidepoint(clicked_pos):
                # Open the settings screen in-place. Re-apply the display
                # surface (settings may have toggled fullscreen) and
                # reset the click guard so the returning click doesn't
                # leak into the physics tick.
                from .menus import run_settings
                if level_music and music.is_playing():
                    music.stop()  # avoid music bleeding into settings
                run_settings(screen, clock)
                _restart_level_music()
                guard.reset()
            elif pause_menu_buttons["menu"].collidepoint(clicked_pos):
                return _stop_music_and_return("menu")
            # A paused click should never trigger a jump — swallow it.
            jump_pressed = False
            pending_jump_press = False

        # Win-screen buttons
        if player.won and clicked_pos:
            if rc_menu.collidepoint(clicked_pos):
                return _stop_music_and_return("menu")
            if rc_replay.collidepoint(clicked_pos):
                _full_reset()
                attempts = 1  # Fresh replay session, not a continuation.
                win_sfx_played = False
                guard.reset()

        # Both editor-test and practice mode let the player slow the
        # physics sim for easier practice on hard sections (QoL B6).
        step_scale = (test_speeds[test_speed_idx]
                      if (editor_test or practice_mode) else 1.0)
        if death_slowmo_timer > 0:
            step_scale *= 0.2  # slower slow-mo makes the moment punchier
            death_slowmo_timer -= 1

        # Physics is pinned to 60 Hz — every movement constant (gravity,
        # jump force, speed values, spike arcs, orb timings) is tuned for
        # that rate. TPS used to be user-configurable which let the
        # player set 120/240 and found the whole game playing back 2×/4×
        # as fast, because each tick still advanced physics by a full
        # "60 Hz frame's worth" of motion. Locking the tick rate here
        # keeps the speed constant regardless of the render FPS cap:
        # the accumulator emits N ticks per real second, and a 30 FPS
        # display just gets two ticks per render frame.
        _tps = 60
        sim_accum += last_dt_sec * _tps * step_scale
        # Guard against spiral-of-death after a long stall (debugger
        # break, tab switch) — clamp the accumulator so we don't try to
        # catch up with 5000 ticks in one frame.
        if sim_accum > _tps * 0.5:
            sim_accum = _tps * 0.5
        while sim_accum >= 1.0:
            sim_accum -= 1.0
            if death_timer > 0:
                death_timer -= 1
                if death_timer <= 0:
                    if practice_mode and player.practice_mode and player.checkpoints:
                        player.load_checkpoint()
                        prev_input_held = False
                        pending_jump_press = False
                    else:
                        _full_reset()
            elif player.alive and not player.won and not paused:
                before_passed = set(player.passed)
                before_pads = sum(1 for k in before_passed if k[0] in PAD_TYPES)
                before_coins = len(player.coins_collected)
                if bot_controller is not None:
                    b_held, b_pressed = bot_controller.compute_input(player)
                    player.update(b_held, b_pressed)
                elif playback_inputs is not None:
                    if bot_frame < len(playback_inputs):
                        b_held, b_pressed = playback_inputs[bot_frame]
                    else:
                        b_held, b_pressed = False, False
                    bot_frame += 1
                    player.update(b_held, b_pressed)
                else:
                    player.update(jump_held, pending_jump_press)
                pending_jump_press = False
                # Speedrun timer ticks once per physics frame (60 Hz).
                attempt_frames += 1
                # Ghost replay: sample every 2 frames to keep the list modest.
                if attempt_frames % 2 == 0:
                    current_run.append((attempt_frames, player.x, player.y))
                # Hitbox trace for the editor's overlay. Sample every other
                # frame — matches the ghost-replay cadence and still has
                # ample resolution for a 300 px/sec hitbox (6 px per sample).
                if out_hitboxes is not None and attempt_frames % 2 == 0:
                    current_hitboxes.append(
                        (player.x, player.y, player.size))
                cam_x = max(0, player.x - 200)

                after_passed = set(player.passed)
                after_pads = sum(1 for k in after_passed if k[0] in PAD_TYPES)
                after_coins = len(player.coins_collected)
                _play_interaction_sounds(
                    before_passed, after_passed,
                    before_pads, after_pads,
                    before_coins, after_coins,
                )
                # Handle checkpoint-request from player (practice-mode
                # flag triggers). Only save when practice mode is actually
                # on.
                if getattr(player, "_checkpoint_request", False):
                    player._checkpoint_request = False
                    if practice_mode and player.practice_mode:
                        player.save_checkpoint()
                        sfx.play("practice_checkpoint", 0.4)

                # Track best progress for persistence.
                progress_now = int(max(0.0, min(1.0, player.x / max_x)) * 100)
                if progress_now > best_progress:
                    best_progress = progress_now
                    # Practice best % is per-user / per-level and stored
                    # locally for now (Chunk F moves it to the progress
                    # server). Normal mode's best is persisted on win
                    # through meta.best_progress.
                    if practice_mode and level_path:
                        try:
                            from .menus import _get_best_practice, _set_best_practice
                            import os as _os_p
                            _fn = _os_p.path.basename(level_path)
                            prev = _get_best_practice(_fn)
                            if progress_now > prev:
                                _set_best_practice(_fn, progress_now)
                        except Exception:
                            pass
                if len(player.coins_collected) > best_coins_this_run:
                    best_coins_this_run = len(player.coins_collected)

            elif not player.alive and death_timer == 0:
                particles.explosion(player.x + 22, player.y + 22, C_PLAYER)
                apply_shake(12)
                sfx.play("death", 0.6)
                if level_music:
                    music.stop()
                death_timer = 45
                # Slow-mo on the last dying moment — longer + slower than
                # before so the death is more visually punchy. 30 frames
                # at 0.2x = 2.5 seconds of slow-mo.
                death_slowmo_timer = 30
                death_flash_timer = 30
                deaths_this_session += 1
                pending_jump_press = False
            particles.update()
            # Exponential ease toward target, clamped to a max step so a
            # big jump (ball flip, gravity portal, spider teleport) doesn't
            # snap the camera by tens of pixels in one frame.
            _dy = (player.target_cam_y - cam_y) * 0.08
            _CAM_Y_MAX_STEP = 14.0  # pixels per frame
            if _dy > _CAM_Y_MAX_STEP:
                _dy = _CAM_Y_MAX_STEP
            elif _dy < -_CAM_Y_MAX_STEP:
                _dy = -_CAM_Y_MAX_STEP
            cam_y += _dy
            target_top, target_bot = BG_PRESETS[player.bg_preset % len(BG_PRESETS)]
            for i in range(3):
                bg_top[i] += (target_top[i] - bg_top[i]) * 0.06
                bg_bot[i] += (target_bot[i] - bg_bot[i]) * 0.06

        update_shake()
        cur_top = tuple(int(c) for c in bg_top)
        cur_bot = tuple(int(c) for c in bg_bot)
        shake_x, shake_y = shake_offset
        draw_bg(screen, cam_x + shake_x, stars, mountains,
                cam_y=cam_y + shake_y, bg_top=cur_top, bg_bot=cur_bot)
        left_gx = int(cam_x // CELL) - 1
        right_gx = left_gx + WIDTH // CELL + 3
        # The bisect slice keys on each object's ORIGINAL x (stable across
        # move triggers), so give it a generous margin — objects that have
        # been displaced far from their origin by a move trigger should
        # still fall inside the slice. Per-object `_fx` is tested below.
        slice_margin = 200
        lo = left_gx - slice_margin
        hi = right_gx + slice_margin
        for layer, xs in ((_deco_layer, _deco_xs), (_main_layer, _main_xs)):
            i = bisect.bisect_left(xs, lo)
            j = bisect.bisect_right(xs, hi)
            for k in range(i, j):
                o = layer[k]
                ox = o.get("_fx", o["x"])
                oy = o.get("_fy", o["y"])
                if not (left_gx - 1 <= ox <= right_gx + 1):
                    continue
                # Skip collected coins so they disappear on pickup.
                if o["t"] == T_COIN and o.get("coin_id", 0) in player.coins_collected:
                    continue
                if o["t"] == T_END:
                    # Win line is an infinite-height wall, not a 50x50 sprite.
                    draw_end_wall(screen, ox * CELL - cam_x + shake_x,
                                  oy * CELL - cam_y + shake_y, CELL, pulse)
                    continue
                draw_obj(screen, o["t"], ox * CELL - cam_x + shake_x,
                         oy * CELL - cam_y + shake_y, CELL, pulse, o.get("r", 0),
                         o if o["t"] == T_TELEPORT_ORB else None)
        # Hint path overlay: when the player has toggled hint mode on, draw
        # the autobot's solved waypoints as a translucent dotted line so
        # they can preview the optimal route. Drawn BEFORE the per-run
        # ghost so the live ghost (player's own best) sits on top.
        if hint_visible and hint_path:
            hint_surf = _overlay_scratch
            hint_surf.fill(_CLEAR)
            prev_pt = None
            for wx, wy in hint_path:
                sx = int(wx - cam_x - shake_x)
                sy = int(wy - cam_y - shake_y)
                if -40 < sx < WIDTH + 40 and -200 < sy < HEIGHT + 200:
                    # Tinted dot per waypoint — orange so it visually reads
                    # as "guidance" without blending into the player trail.
                    pygame.draw.circle(hint_surf, (255, 200, 80, 120),
                                       (sx, sy), 4)
                    if prev_pt is not None:
                        pygame.draw.line(hint_surf, (255, 200, 80, 70),
                                         prev_pt, (sx, sy), 2)
                    prev_pt = (sx, sy)
                else:
                    prev_pt = None
            # Mirror path (when the level enters dual): blue so the user can
            # tell the two bodies apart at a glance.
            if hint_mirror_path:
                prev_pt = None
                for wx, wy in hint_mirror_path:
                    sx = int(wx - cam_x - shake_x)
                    sy = int(wy - cam_y - shake_y)
                    if -40 < sx < WIDTH + 40 and -200 < sy < HEIGHT + 200:
                        pygame.draw.circle(hint_surf, (90, 170, 255, 120),
                                           (sx, sy), 4)
                        if prev_pt is not None:
                            pygame.draw.line(hint_surf, (90, 170, 255, 70),
                                             prev_pt, (sx, sy), 2)
                        prev_pt = (sx, sy)
                    else:
                        prev_pt = None
            screen.blit(hint_surf, (0, 0))
        # Ghost overlay: draw a fading trail of the best prior run so the
        # player can see where they previously got further.
        if best_run:
            ghost_surf = _overlay_scratch
            ghost_surf.fill(_CLEAR)
            # Find the segment near current time +/- some window so the ghost
            # "runs alongside" rather than rendering the entire track.
            window = 120  # frames before and after
            lo = attempt_frames - window
            hi = attempt_frames + window
            for gf, gx, gy in best_run:
                if gf < lo or gf > hi:
                    continue
                sx = int(gx - cam_x - shake_x)
                sy = int(gy - cam_y - shake_y)
                if -30 < sx < WIDTH + 30 and -30 < sy < HEIGHT + 30:
                    # Alpha fades with distance from current frame.
                    dist = abs(gf - attempt_frames)
                    a = max(0, int(110 * (1.0 - dist / window)))
                    pygame.draw.circle(ghost_surf, (200, 200, 255, a),
                                       (sx + 22, sy + 22), 10)
            screen.blit(ghost_surf, (0, 0))
        if player.alive and death_timer == 0:
            player.draw(screen, cam_x + shake_x, cam_y + shake_y)
        particles.draw(screen, cam_x + shake_x, cam_y + shake_y)

        # Checkpoint markers — little flag drawn at every saved spot.
        # Only in practice mode (that's the only mode that saves them)
        # and before the player wins, so the win card isn't cluttered.
        if practice_mode and player.checkpoints and not player.won:
            _pulse_t = (pulse % 60) / 60.0
            _glow = int(90 + 40 * math.sin(_pulse_t * math.tau))
            for _i, _cp in enumerate(player.checkpoints):
                fx = int(_cp["x"] - cam_x - shake_x)
                fy = int(_cp["y"] - cam_y - shake_y)
                # Cull off-screen markers cheaply.
                if fx < -40 or fx > WIDTH + 40:
                    continue
                # Flag pole.
                pole_top = fy - 28
                pole_bot = fy + 44
                pygame.draw.line(screen, (230, 230, 240),
                                 (fx + 8, pole_top), (fx + 8, pole_bot), 2)
                # Triangular flag.
                flag_pts = [(fx + 8, pole_top),
                            (fx + 30, pole_top + 8),
                            (fx + 8, pole_top + 16)]
                pygame.draw.polygon(screen, (90, 220, 140), flag_pts)
                pygame.draw.polygon(screen, (20, 100, 50), flag_pts, 2)
                # Soft pulsing halo around the flag so it reads as
                # "interactive" rather than part of the level art.
                halo = pygame.Surface((44, 44), pygame.SRCALPHA)
                pygame.draw.circle(halo, (120, 255, 160, _glow),
                                   (22, 22), 22)
                screen.blit(halo, (fx - 14, pole_top - 6))
                # Number label on the flag (1-indexed).
                txt(screen, str(_i + 1), fx + 14, pole_top + 4, 11,
                    (20, 40, 20), center=True)

        # (Red full-screen death flash removed — the slow-mo vignette,
        # explosion particles, camera shake and "Hit a spike" readout
        # below already signal death clearly, and the flash felt
        # visually heavy.)

        # Death reason readout — shows shortly after death so the
        # player gets a short explanation of what killed them ("Hit a
        # spike", "Fell off the screen", etc.) before the next attempt.
        if death_timer > 0 and getattr(player, "death_reason", ""):
            fade = min(1.0, (45 - death_timer) / 12.0)
            alpha = int(230 * max(0.0, fade))
            _reason = player.death_reason
            _rtxt = f"☠  {_reason}"
            reason_surf = pygame.Surface((WIDTH, 46), pygame.SRCALPHA)
            reason_surf.fill((0, 0, 0, int(140 * fade)))
            screen.blit(reason_surf, (0, HEIGHT // 2 + 60))
            txt(screen, _rtxt, WIDTH // 2, HEIGHT // 2 + 82,
                22, (255, 220, 220), True, shadow=True)

        # Slow-mo vignette: bordered darkening when death_slowmo_timer is active.
        if death_slowmo_timer > 0:
            alpha = int(120 * (death_slowmo_timer / 30.0))
            if alpha > 0:
                border = 120
                dark = (0, 0, 0, alpha)
                _overlay_scratch.fill(_CLEAR)
                _overlay_scratch.fill(dark, (0, 0, WIDTH, border))
                _overlay_scratch.fill(dark, (0, HEIGHT - border, WIDTH, border))
                _overlay_scratch.fill(dark, (0, 0, border, HEIGHT))
                _overlay_scratch.fill(dark, (WIDTH - border, 0, border, HEIGHT))
                screen.blit(_overlay_scratch, (0, 0))

        # Pulse trigger: brief screen-tinted flash modulated by BPM.
        pulse_amp = player.pulse_intensity()
        if pulse_amp > 0.01:
            _overlay_scratch.fill((255, 240, 255, int(60 * pulse_amp)))
            screen.blit(_overlay_scratch, (0, 0))
        if death_flash_timer > 0:
            death_flash_timer -= 1
        # (Checkpoint green flash removed — the in-world flag markers
        # now convey "saved here" more clearly and don't obscure the
        # player's surroundings at the moment the save happens.)

        # ---- HUD ----------------------------------------------------------
        # Progress bar — spans most of the screen width, taller so the bar
        # carries visual weight. Every 10% has a subtle tick for structure.
        progress = max(0.0, min(1.0, player.x / max_x))
        bar_x = 50
        bar_y = 10
        bar_h = 12
        bw = WIDTH - 2 * bar_x
        if progress < 0.5:
            bar_color = (255, int(255 * (progress / 0.5)), 0)
        else:
            bar_color = (int(255 * (1 - (progress - 0.5) / 0.5)), 255, 0)
        pygame.draw.rect(screen, C_DARK, (bar_x, bar_y, bw, bar_h),
                         border_radius=4)
        pygame.draw.rect(screen, bar_color,
                         (bar_x, bar_y, max(1, int(bw * progress)), bar_h),
                         border_radius=4)
        for pct in range(10, 100, 10):
            tx = bar_x + int(bw * pct / 100)
            pygame.draw.rect(screen, (0, 0, 0, 80),
                             (tx, bar_y + 2, 1, bar_h - 4))
        progress_percent = int(progress * 100)
        txt(screen, f"{progress_percent}%",
            bar_x + int(bw * progress) + 10, bar_y - 4, 14,
            C_GRAY, shadow=True)

        # Attempt / time stack sits BELOW the progress bar, clearly
        # separated so nothing visually collides with the coin HUD.
        hud_text_y = bar_y + bar_h + 10
        txt(screen, f"Attempt {attempts}", 20, hud_text_y, 17, C_GRAY,
            shadow=True)
        cur_time_s = attempt_frames / 60.0
        timer_label = f"Time {int(cur_time_s // 60):d}:{cur_time_s % 60:05.2f}"
        txt(screen, timer_label, 20, hud_text_y + 20, 14, C_GRAY, shadow=True)
        prev_best_time = int((meta or {}).get("best_time_frames", 0)) if meta else 0
        if prev_best_time > 0:
            best_s = prev_best_time / 60.0
            best_label = f"Best {int(best_s // 60):d}:{best_s % 60:05.2f}"
            txt(screen, best_label, 20, hud_text_y + 38, 13, C_SUCCESS,
                shadow=True)
        txt(screen, level_name, WIDTH // 2, 8, 15, C_WHITE, True, shadow=True)
        txt(screen, f"{player.mode.title()} · {player.move_speed:.1f}x",
            WIDTH - 170, 28, 14, C_GRAY, shadow=True)

        # Coin HUD (top-right)
        if total_coins > 0:
            got = len(player.coins_collected)
            coin_y = 52
            for i in range(total_coins):
                cx = WIDTH - 30 - (total_coins - 1 - i) * 28
                filled = i < got
                col = C_COIN if filled else darker(C_COIN, 120)
                pygame.draw.circle(screen, darker(col, 40), (cx + 1, coin_y + 1), 10)
                pygame.draw.circle(screen, col, (cx, coin_y), 10)
                if filled:
                    pygame.draw.circle(screen, lighter(C_COIN, 70), (cx, coin_y), 6, 2)
            txt(screen, f"{got}/{total_coins}", WIDTH - 30 - total_coins * 28 - 8,
                coin_y - 8, 14, C_WHITE, shadow=True)

        if practice_mode:
            # Stack the CP chip ABOVE the PRACTICE label so the two never
            # collide horizontally — on narrow windows the centred
            # PRACTICE text and the right-anchored chip used to share a
            # row and risked overlap.
            _cp_n = len(player.checkpoints)
            _cp_label = (f"CP: {_cp_n}  ·  C drop · X pop" if _cp_n
                         else "CP: 0  ·  press C to drop a checkpoint")
            txt(screen, _cp_label, WIDTH - 140, HEIGHT - 46, 12,
                (180, 220, 255) if _cp_n else C_GRAY, True, shadow=True)
            txt(screen, "PRACTICE MODE", WIDTH // 2, HEIGHT - 22, 15, (0, 255, 0),
                True, shadow=True)
        # Hint-mode status: a subtle top-left line the player can ignore
        # unless they've opted in by pressing H.
        if hint_visible and hint_path:
            badge = "HINT · autobot path"
            if hint_status == "partial":
                badge += " (partial)"
            txt(screen, badge, 20, 78, 13, (255, 200, 80), shadow=True)
        elif hint_path is not None and not hint_visible:
            txt(screen, "HINT off — press H", 20, 78, 12, C_GRAY, shadow=True)
        if editor_test or (practice_mode and
                           test_speed_idx != len(test_speeds) - 1):
            _speed_label = ("Test" if editor_test else "Practice")
            txt(screen,
                f"{_speed_label} {test_speeds[test_speed_idx]:.2f}x",
                WIDTH - 110, 26, 15, C_GRAY, shadow=True)
            if bot_controller is not None:
                txt(screen, "BOT", WIDTH // 2 - 220, HEIGHT - 22, 18,
                    (255, 180, 60), True, shadow=True)
            elif playback_inputs is not None:
                pb_pct = min(100, int(bot_frame / max(1, len(playback_inputs)) * 100))
                txt(screen, f"PLAYBACK {pb_pct}%", WIDTH // 2 - 220, HEIGHT - 22,
                    18, (100, 220, 255), True, shadow=True)
            txt(screen, "[/- slower  ]/= faster  0 reset", WIDTH // 2,
                HEIGHT - 22, 15, C_GRAY, True, shadow=True)

        # ---- Debug overlay (F3) -------------------------------------------
        if show_debug:
            import time as _time_dbg
            now = _time_dbg.perf_counter()
            _dbg_frame_times.append(now)
            # Keep only the last ~1 sec of timestamps for FPS calc.
            cutoff = now - 1.0
            while _dbg_frame_times and _dbg_frame_times[0] < cutoff:
                _dbg_frame_times.pop(0)
            _fps = (len(_dbg_frame_times) - 1) / max(
                0.001, (_dbg_frame_times[-1] - _dbg_frame_times[0])
                if len(_dbg_frame_times) > 1 else 0.001)
            _frame_ms = (now - _dbg_frame_times[-2]) * 1000 \
                if len(_dbg_frame_times) > 1 else 0.0
            lines = [
                f"FPS {_fps:.1f}  ·  {_frame_ms:.1f}ms",
                f"pos ({player.x:.1f}, {player.y:.1f})",
                f"vy {player.vy:.2f}  grav {player.grav}",
                f"mode {player.mode}  speed {player.move_speed:.1f}x",
                f"on_ground {player.on_ground}  size {player.size}",
                f"frame {player.frame}  attempts {attempts}",
                f"objects {len(objects)}",
            ]
            if player.mirror is not None:
                mm = player.mirror
                lines.append(f"mirror y {mm['y']:.1f} vy {mm['vy']:.2f} "
                             f"grav {mm['grav']}")
            dbg_w, dbg_h = 260, 14 * len(lines) + 12
            pad = pygame.Rect(WIDTH - dbg_w - 10, HEIGHT - dbg_h - 40,
                              dbg_w, dbg_h)
            bg = pygame.Surface((dbg_w, dbg_h), pygame.SRCALPHA)
            bg.fill((0, 0, 0, 180))
            screen.blit(bg, pad.topleft)
            for i, ln in enumerate(lines):
                txt(screen, ln, pad.x + 8, pad.y + 6 + i * 14,
                    11, (180, 240, 180))

        # ---- Pause overlay ------------------------------------------------
        if paused:
            ov = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            ov.fill((0, 0, 0, 180))
            screen.blit(ov, (0, 0))
            txt(screen, "PAUSED", WIDTH // 2, HEIGHT // 2 - 140, 56, C_PLAYER, True)
            # Status sub-line: show attempt count + current % so the pause
            # menu is informative, not just a cover (QoL B5).
            _pct = int(max(0.0, min(1.0, player.x / max_x)) * 100)
            txt(screen, f"Attempt {attempts}  ·  {_pct}%",
                WIDTH // 2, HEIGHT // 2 - 100, 16, C_GRAY, True)
            btn(screen, "Resume", pause_menu_buttons["resume"].centerx,
                pause_menu_buttons["resume"].centery, 220, 48, C_BTN, mpos)
            btn(screen, "Restart", pause_menu_buttons["restart"].centerx,
                pause_menu_buttons["restart"].centery, 220, 48, C_BTN, mpos)
            practice_label = "Practice: ON" if practice_mode else "Practice: OFF"
            practice_col = C_SUCCESS if practice_mode else C_BTN
            btn(screen, practice_label, pause_menu_buttons["practice_toggle"].centerx,
                pause_menu_buttons["practice_toggle"].centery, 220, 48, practice_col, mpos)
            btn(screen, "Settings", pause_menu_buttons["settings"].centerx,
                pause_menu_buttons["settings"].centery, 220, 48,
                (80, 100, 160), mpos)
            btn(screen, "Main Menu", pause_menu_buttons["menu"].centerx,
                pause_menu_buttons["menu"].centery, 220, 48, C_DANGER, mpos)
            # Mute toggles — bottom row, centered below menu button
            r_mute_music = icon_button(
                screen, speaker_icon(22, music.is_muted()),
                WIDTH // 2 - 30, HEIGHT // 2 + 220, 44, 44, C_BTN, mpos,
                active=music.is_muted(),
            )
            r_mute_sfx = icon_button(
                screen, speaker_icon(20, sfx.is_muted()),
                WIDTH // 2 + 30, HEIGHT // 2 + 220, 44, 44, (80, 60, 140), mpos,
                active=sfx.is_muted(),
            )
            txt(screen, "Music", r_mute_music.centerx, r_mute_music.bottom + 4,
                11, C_GRAY, True)
            txt(screen, "SFX", r_mute_sfx.centerx, r_mute_sfx.bottom + 4, 11,
                C_GRAY, True)
            txt(screen, "M: mute music  ·  N: mute SFX  ·  H: toggle hint path",
                WIDTH // 2, HEIGHT // 2 + 280, 13, C_GRAY, True)
        else:
            # Prevent stale pause-overlay rects from catching clicks outside pause.
            r_mute_music = pygame.Rect(0, 0, 0, 0)
            r_mute_sfx = pygame.Rect(0, 0, 0, 0)

        # ---- Win overlay --------------------------------------------------
        if player.won:
            if not win_sfx_played:
                sfx.play("win", 0.6)
                win_sfx_played = True
                if level_music:
                    music.fadeout(1500)
                _persist_win()
            ov = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            ov.fill((0, 0, 0, 160))
            screen.blit(ov, (0, 0))
            txt(screen, "LEVEL COMPLETE!", WIDTH // 2, HEIGHT // 2 - 110, 54,
                C_PLAYER, True)
            # Stats panel: attempts, deaths, time, best time, coins.
            cur_time_s_win = attempt_frames / 60.0
            cur_time_str = (f"{int(cur_time_s_win // 60):d}:"
                            f"{cur_time_s_win % 60:05.2f}")
            best_t_frames = int((meta or {}).get("best_time_frames", 0)) if meta else 0
            best_str = "—"
            if best_t_frames > 0:
                bts = best_t_frames / 60.0
                best_str = f"{int(bts // 60):d}:{bts % 60:05.2f}"
            row_y = HEIGHT // 2 - 50
            txt(screen, f"Attempts: {attempts}", WIDTH // 2 - 130, row_y, 20,
                C_WHITE, True)
            txt(screen, f"Deaths: {deaths_this_session}", WIDTH // 2 + 130, row_y,
                20, C_DANGER, True)
            txt(screen, f"Time: {cur_time_str}", WIDTH // 2 - 130, row_y + 28, 20,
                C_WHITE, True)
            txt(screen, f"Best: {best_str}", WIDTH // 2 + 130, row_y + 28, 20,
                C_SUCCESS, True)
            if total_coins > 0:
                coins = len(player.coins_collected)
                colour = C_COIN if coins == total_coins else C_GRAY
                txt(screen, f"Coins: {coins} / {total_coins}", WIDTH // 2,
                    row_y + 60, 22, colour, True)
            if meta_persisted:
                txt(screen, "Verified!", WIDTH // 2, row_y + 90, 18,
                    C_SUCCESS, True)
            elif is_sim_run:
                txt(screen, "(Bot run -- not verified)", WIDTH // 2,
                    row_y + 90, 16, C_GRAY, True)
            btn(screen, "Menu", rc_menu.centerx, rc_menu.centery, rc_menu.w,
                rc_menu.h, C_BTN, mpos)
            btn(screen, "Replay", rc_replay.centerx, rc_replay.centery,
                rc_replay.w, rc_replay.h, C_SUCCESS, mpos)

        pygame.display.flip()
        # clock.tick sleeps to cap at fps_cap and returns the ms that
        # elapsed since the previous call — stash it as the next frame's
        # dt so sim_accum can advance by wall-clock * TPS.
        _dt_ms = clock.tick(settings.get_fps_cap())
        last_dt_sec = _dt_ms / 1000.0
