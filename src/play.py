"""Gameplay loop.

Runs a single play session — handles input, physics stepping (via Player),
HUD rendering, pause/win overlays, practice-mode checkpoints, and — on a
legitimate win — bumps the level's ``verified`` / ``best_progress`` /
``coins_collected`` metadata so the playlist can mark it verified.
"""

import sys

import pygame

from .constants import (
    WIDTH, HEIGHT, CELL, FPS, PLAYER_START_GX,
    C_PLAYER, C_BG_TOP, C_BG_BOT, C_PUBLISH, C_DASH_ORB,
    DECORATION_TYPES, TRIGGER_TYPES, BG_PRESETS, PAD_TYPES,
    T_COIN, T_ORB, T_DASH_ORB, T_BLACK_ORB,
    T_BLUE_ORB, T_GREEN_ORB, T_SPIDER_ORB, T_RED_ORB, T_PINK_ORB,
    T_GRAV_UP, T_GRAV_DOWN,
    T_TIME_WARP, SPEED_VALUES,
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
from .player import Player
from .levels import update_meta
from .play_render import (
    render_world, render_hint_overlay, render_predicted_path,
    render_ghost_paths, render_death_hitbox_marker, render_best_run_ghost,
    render_player_and_particles, render_checkpoint_markers,
    render_death_reason, render_slowmo_vignette, render_pulse_flash,
    render_hud, render_debug_overlay, render_state_hud,
    render_pause_overlay, render_win_overlay,
)


# Keys / cells that, when added to player.passed during an update(),
# should trigger a named SFX.
_SFX_FOR_TYPE = {
    T_ORB: ("orb", 0.5),
    T_DASH_ORB: ("orb", 0.55),
    T_BLACK_ORB: ("orb", 0.5),
    T_BLUE_ORB: ("gravity", 0.45),
    T_GREEN_ORB: ("orb", 0.5),
    T_SPIDER_ORB: ("gravity", 0.5),
    T_RED_ORB: ("orb", 0.6),
    T_PINK_ORB: ("orb", 0.4),
    T_GRAV_UP: ("gravity", 0.45),
    T_GRAV_DOWN: ("gravity", 0.45),
}


def _real_time_to_x(objects, target_x, base_speed):
    """Compute the wall-clock seconds the player would have spent
    reaching ``target_x`` from spawn (x=0), integrating across speed
    portals AND time-warp triggers placed before that x.

    Speed portals change the game-rate at which x advances. Time
    warps change how fast game-frames map to real seconds (the
    music plays at real time, regardless of warp). Each contributes
    a per-segment factor:

        real_seconds_in_segment = length / (game_speed * 60 * warp)

    Used to seek the music to the right beat when the player
    spawns mid-level via "Test from cursor" or shift+T — without
    this, a level that has a 0.5x slow-mo section in the first
    half would have its music ahead of the visuals after the seek.
    """
    if target_x <= 0:
        return 0.0
    base_speed = max(1.0, float(base_speed))
    # Build event lists: speed-change events and warp-change events,
    # both keyed by world-x (cell × CELL).
    speed_events = sorted(
        ((int(o["x"]) * CELL, float(SPEED_VALUES[o["t"]]))
         for o in objects if o.get("t") in SPEED_VALUES),
        key=lambda e: e[0])
    warp_events = sorted(
        ((int(o["x"]) * CELL, float(o.get("factor", 1.0)))
         for o in objects if o.get("t") == T_TIME_WARP),
        key=lambda e: e[0])
    # Scan from spawn-x to target_x, advancing the latched speed
    # and warp values whenever an event x is crossed.
    cur_speed = base_speed
    cur_warp = 1.0
    cur_x = 0.0
    elapsed = 0.0
    # Merge events by x. We integrate the constant (speed, warp)
    # span from cur_x to next_event_x, then update the latched
    # value, then continue.
    si = 0  # speed event index
    wi = 0  # warp event index
    while cur_x < target_x:
        next_speed_x = (speed_events[si][0]
                        if si < len(speed_events) else float("inf"))
        next_warp_x = (warp_events[wi][0]
                       if wi < len(warp_events) else float("inf"))
        next_event_x = min(next_speed_x, next_warp_x, target_x)
        seg_len = max(0.0, next_event_x - cur_x)
        if cur_speed > 0 and cur_warp > 0:
            # frames in this segment = seg_len / cur_speed
            # real seconds = frames / (60 * warp)
            elapsed += seg_len / (cur_speed * 60.0 * cur_warp)
        cur_x = next_event_x
        if cur_x >= target_x:
            break
        # Latch whichever event(s) fired at this x.
        if next_speed_x == cur_x:
            cur_speed = speed_events[si][1]
            si += 1
        if next_warp_x == cur_x:
            cur_warp = warp_events[wi][1]
            wi += 1
    return elapsed


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
             playback_inputs=None, playback_waypoints=None, meta=None,
             level_path=None, out_hitboxes=None, out_mirror_hitboxes=None,
             start_x=None, predicted_path=None, ghost_paths=None):
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

    ``ghost_paths`` (optional list of dict): translucent ghost
    trajectories rendered alongside the main playback. Two shapes
    are accepted:

      Static (one fixed trajectory, e.g. spawn-to-end baseline):
        ``label``     short string for legend
        ``waypoints`` list of (x, y) icon-centre samples
        ``color``     (r, g, b) base RGB tuple
        ``death``     None or dict with ``x``, ``y``, ``size``, ``reason``
                      drawn as a hitbox marker at the tail
        ``won``       bool — overrides the death marker with a win flag

      Per-frame (Y bot live overlay):
        ``label``       short string for legend
        ``color``       (r, g, b) base RGB tuple
        ``frames``      list aligned to ``playback_inputs`` — each entry
                        is a dict ``{"wp": [(x,y),...], "death": ...,
                        "won": bool}`` describing the probe rolled
                        forward FROM that frame. The renderer indexes
                        by current ``bot_frame`` so the line updates
                        live as the playback advances.
        ``chosen_when`` "click" / "noclick" — when the bot's actual
                        choice this frame matches, the line is drawn
                        brighter so the user can read the decision.
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
    # Music-seek offset in seconds matching ``start_x``. The music
    # plays at real time, so we need the REAL-time elapsed for the
    # player to reach ``start_x`` from spawn — that's what's been
    # spinning while the player was traversing earlier sections,
    # and where the music should be cued so the beat still aligns.
    #
    # Two factors stretch / compress the per-pixel real time and
    # both matter:
    #   * Speed portals change the player's px/frame rate
    #     (``move_speed``). A 1.65× section covers x faster, so
    #     the music-time elapsed per cell is shorter there.
    #   * Time warps change how fast the WHOLE game ticks against
    #     wall clock (``step_scale *= time_warp`` in this file's
    #     main loop). A slow-mo section spends more real seconds
    #     per game-frame, stretching the music time across the
    #     same x.
    # Real-time per cell of length L in a segment with game speed
    # s (px/frame) and time-warp w is ``L / (s * 60 * w)``.
    # Music seek offset = wall-clock seconds the player WOULD have
    # spent reaching the spawn x from the level origin (x=0). Two
    # places set the spawn x:
    #   1. ``start_x`` parameter — used by Test-from-cursor (Shift+T)
    #      and similar mid-level entry flows.
    #   2. The T_START item's cell position — when the level author
    #      places the start marker at, say, cell 50, the player
    #      spawns at x≈2528 and the music should already be at the
    #      beat that would have been playing if they'd actually
    #      walked there. Without this, moving the start item just
    #      teleports the player while the music plays from 0.
    # The music's t=0 corresponds to the player at their DEFAULT
    # spawn (PLAYER_START_GX * CELL), not world x=0. So a level with
    # the default start spawning at x=150 plays music from file
    # position 0 — the first second is what the level designer
    # intended you to hear when you press play. Only when the actual
    # spawn (start_x or T_START item) sits past the default do we
    # fast-forward the music to where it would have been if you'd
    # walked there from the default spawn.
    _music_offset_sec = 0.0
    spawn_world_x = float(player.x)
    if start_x and start_x > 0:
        spawn_world_x = max(spawn_world_x, float(start_x))
    default_spawn_x = float(PLAYER_START_GX * CELL)
    if spawn_world_x > default_spawn_x + 1.0:
        base_speed = float(player.params.base_move_speed)
        offset_total = _real_time_to_x(objects, spawn_world_x, base_speed)
        offset_default = _real_time_to_x(
            objects, default_spawn_x, base_speed)
        _music_offset_sec = max(0.0, offset_total - offset_default)
    particles = Particles()
    stars = make_stars()
    mountains = make_mountains()
    # Camera follows player.x - 200, with no lower clamp so the
    # camera can pan into negative space (showing the area "before"
    # the level start) — useful when the player is teleported
    # backward or the spawn sits within 200 px of x=0. Initialize
    # to the spawn position so the very first rendered frame shows
    # the player even when start_x puts them deep into the level.
    cam_x = float(player.x) - 200.0
    cam_y = 0.0
    bg_top = [float(c) for c in C_BG_TOP]
    bg_bot = [float(c) for c in C_BG_BOT]
    attempts = 1
    death_timer = 0
    death_slowmo_timer = 0
    death_flash_timer = 0
    # Last attempt's death pose for the bot-path overlay's red hitbox
    # marker. Tuple of (x, y, size, angle, reason) or None if the
    # current attempt hasn't died yet. Cleared on _full_reset.
    _death_hitbox = None
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
    #
    # The player writes ONE sample per logical physics tick (60 Hz) via
    # its ``hitbox_trace`` hook — early-exit paths (a wall hit, hazard
    # death, win line) emit a single sample at the death/win position
    # instead of the end-of-frame sample, so the trace never doubles up.
    # Opt-in: only enabled when the caller passed ``out_hitboxes``.
    current_hitboxes = []
    best_hitboxes_progress = 0.0
    if out_hitboxes is not None:
        player.hitbox_trace = current_hitboxes
    # Parallel buffer for the dual-mode mirror's hitbox trace. Same
    # commit-on-best-attempt rule as the main buffer; populated only
    # while the player has a mirror, otherwise the list just stays
    # empty for that attempt.
    current_mirror_hitboxes = []
    if out_mirror_hitboxes is not None:
        player.mirror_hitbox_trace = current_mirror_hitboxes

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
    # Level-state HUD: mode / speed / size / gravity / dual / time warp /
    # position. Toggled with `I`. Auto-on during editor_test so the
    # author can see what triggers fired without remembering the
    # binding — when you're tweaking a level you almost always want
    # to know "what mode am I in here, what's the speed, am I dual?".
    show_state = bool(editor_test)

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
    # Click counter rather than a boolean: every mouse-down / key-down
    # edge captured from the event queue bumps this by one, and every
    # physics tick consumes exactly one press. That means rapid taps
    # (or any click that happens between render frames, or multiple
    # physics ticks within one render frame) each produce their own
    # discrete jump instead of being collapsed to a single "pressed".
    pending_presses = 0
    bot_frame = 0
    bot_click_flash = 0
    # Rolling window of recent bot presses (physics frame indices). Used
    # to compute the HUD CPS readout during bot / playback runs so the
    # viewer can see how click-heavy the solver's solution actually is.
    # Frames older than 1s (60 ticks) are popped each render frame.
    bot_press_frames = []
    bot_press_total = 0
    # Press-edge latch for the bot click counter. A "click" is when the
    # held input rises from False→True — counting `b_pressed` directly
    # missed ship/wave clicks (those modes only set held, never pressed)
    # and double-counted when the autobot picked consecutive (True, True)
    # ticks. Tracking the held edge instead matches what a human player
    # would call a click in every mode.
    prev_b_held = False
    # Manual takeover: pressing P during a bot / playback run hands
    # control back to the human, replacing the recorded inputs from
    # that frame onward. To keep the takeover honest (and stop the
    # bot from "coasting" through the recorded path with no input),
    # the player dies after `MANUAL_TAKEOVER_GRACE` physics frames
    # with neither a jump press nor a held jump key.
    manual_takeover = False
    takeover_idle_frames = 0
    MANUAL_TAKEOVER_GRACE = 60
    # Playback desync watchdog (PDF 11.1). When the caller hands in
    # `playback_waypoints`, we compare the live player's y to the
    # solver's expected y at the current x each tick. Exact-input
    # playbacks are sensitive to any physics drift — floating-point
    # rounding, a post-solve edit to the level, a PhysicsParams change
    # — and the player dies "for no reason" ten frames later. Surfacing
    # drift early lets the user know the replay is off-route instead
    # of blaming the solver.
    playback_wp_sorted = None
    playback_wp_xs = None
    if playback_waypoints:
        wp = sorted(playback_waypoints, key=lambda p: p[0])
        # De-dup consecutive-x entries (matches BotController's cleanup).
        wp_clean = []
        for px, py in wp:
            if not wp_clean or px != wp_clean[-1][0]:
                wp_clean.append((px, py))
            else:
                wp_clean[-1] = (px, py)
        playback_wp_sorted = wp_clean
        playback_wp_xs = [p[0] for p in wp_clean]
    desync_max_px = 0.0  # peak absolute drift seen this attempt
    desync_alert_timer = 0  # frames left to show the "DRIFT" badge
    # Predicted-path overlay (Y bot): the pathfinder's planned (x, y)
    # samples, sorted by x. Drawn each frame as a forward-fading line
    # from the player's current x into the future so the viewer sees
    # the bot's plan. Sorted once here; the per-frame draw uses bisect.
    pred_path_sorted = None
    pred_path_xs = None
    if predicted_path:
        _ppc = sorted(predicted_path, key=lambda p: p[0])
        pred_path_sorted = _ppc
        pred_path_xs = [p[0] for p in _ppc]
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
        nonlocal prev_input_held, pending_presses, sim_accum, bot_frame
        nonlocal bot_click_flash, bot_press_frames, bot_press_total
        nonlocal prev_b_held, _death_hitbox
        nonlocal manual_takeover, takeover_idle_frames
        nonlocal desync_max_px, desync_alert_timer
        nonlocal cam_y, bg_top, bg_bot
        nonlocal attempt_frames, current_run, best_run, best_run_progress_x
        nonlocal best_hitboxes_progress
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
            # Commit the mirror trace alongside it so the editor's
            # H-overlay always shows a matched pair from the same
            # attempt — otherwise the bands would drift apart when one
            # body's progress beats the other's.
            if out_mirror_hitboxes is not None:
                out_mirror_hitboxes[:] = current_mirror_hitboxes
            best_hitboxes_progress = player.x
        # In-place clear so `player.hitbox_trace` still points at the
        # same list after reset — otherwise the next attempt would
        # append into a list run_play no longer reads from.
        current_hitboxes.clear()
        current_mirror_hitboxes.clear()
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
        _death_hitbox = None
        attempt_frames = 0
        prev_input_held = False
        pending_presses = 0
        sim_accum = 0.0
        if bot_controller:
            bot_controller.reset()
        bot_frame = 0
        bot_click_flash = 0
        bot_press_frames = []
        bot_press_total = 0
        prev_b_held = False
        manual_takeover = False
        takeover_idle_frames = 0
        desync_max_px = 0.0
        desync_alert_timer = 0
        # Re-derive cam_x from the post-reset player position so the
        # first frame after a death/restart already shows the player.
        # Without this, cam_x stays where it was at death and the
        # respawned player is rendered off-screen until the first
        # physics tick reassigns cam_x.
        cam_x = float(player.x) - 200.0
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
            if out_mirror_hitboxes is not None:
                out_mirror_hitboxes[:] = current_mirror_hitboxes
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

        Level lifecycle:
          drafted   → private, no win counts anything
          published → public, shows publisher's requested difficulty
          verified  → first non-author beater flipped verified=True
                       and recorded their suggested_difficulty; the
                       official `difficulty` still mirrors the
                       publisher's request, but the carousel shows
                       "unconfirmed: <suggested>" alongside it
          rated     → ADMIN_USERNAME picked the final difficulty via
                       the Rate Levels menu; `difficulty` is their
                       choice and `suggested_difficulty` is no longer
                       displayed

        Every win updates session stats. Only a non-author winning an
        unverified published level triggers the "suggest difficulty"
        prompt. Rating is never touched here — that's the Rate menu's
        job.
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
        # First non-author win on a published-but-unverified level:
        # prompt the beater for their difficulty suggestion and flip
        # `verified`. The publisher's `difficulty` / `requested_difficulty`
        # is NOT overwritten — only `suggested_difficulty` records the
        # new opinion. ADMIN_USERNAME's rating in the Rate menu is what
        # eventually locks the final difficulty.
        from .prefs import get as _pget_usr
        _cur_user = _pget_usr("signed_in_username", None)
        _author = (meta or {}).get("author", "") or ""
        _is_author = (_cur_user is not None and _cur_user == _author)
        _is_published = bool((meta or {}).get("published", False))
        _is_verified = bool((meta or {}).get("verified", False))
        _is_rated = bool((meta or {}).get("rated", False))
        if (not _is_author and _is_published and not _is_verified
                and not _is_rated):
            from .menus import difficulty_picker
            requested = (meta or {}).get("requested_difficulty",
                                         (meta or {}).get("difficulty",
                                                          "Normal"))
            chosen = difficulty_picker(
                screen, clock,
                prompt="You beat this level!",
                default=requested,
                subtitle=f"Publisher requested: {requested}.  "
                         f"What difficulty do you think this is?",
            )
            if chosen:
                updates["verified"] = True
                updates["suggested_difficulty"] = chosen
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
        new_presses_this_frame = 0
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
                    if is_sim_run and player.alive:
                        # Hand control from the bot / playback to the
                        # human. One-way for the rest of the attempt:
                        # the recorded inputs would desync with live
                        # state if we tried to switch back. Reset the
                        # idle counter so the grace window starts now.
                        manual_takeover = True
                        takeover_idle_frames = 0
                        pending_presses = 0
                    else:
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
                elif ev.key == pygame.K_i:
                    show_state = not show_state
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
                new_presses_this_frame += 1
            # Capture jump-key press edges from the event queue too so
            # a tap-and-release that falls entirely between two polled
            # frames (possible at low FPS / high TPS) still registers
            # as exactly one press.
            if ev.type == pygame.KEYDOWN and ev.key in (
                    pygame.K_SPACE, pygame.K_UP, pygame.K_w):
                new_presses_this_frame += 1
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

        # Also count a polled "just-became-held" edge from gamepad /
        # any held source the event queue didn't surface (headless
        # envs, input shim). `prev_input_held` keeps its role as the
        # latch for this fallback edge detection.
        if jump_held and not prev_input_held and new_presses_this_frame == 0:
            new_presses_this_frame += 1
        prev_input_held = jump_held
        pending_presses += new_presses_this_frame

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
            # A paused click should never trigger a jump — swallow any
            # presses queued for the physics tick.
            pending_presses = 0

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
        # T_TIME_WARP triggers latch ``player.time_warp`` on contact;
        # fold it in here so the sim accumulator advances faster (>1) or
        # slower (<1) than wall clock for the rest of the level. Default
        # 1.0 means the trigger has no effect when none is placed.
        # Allow factor=0.0 (game freeze, useful for cinematic stops);
        # capped at 10.0 to match the editor's range.
        step_scale *= max(0.0, min(10.0,
                                   getattr(player, "time_warp", 1.0)))

        # Internal physics tick rate is pinned to 60 Hz — every movement
        # constant (gravity, jump force, speed values, spike arcs, orb
        # timings) is tuned for that rate, so changing it without
        # rescaling every tunable would speed up the whole game. The
        # render loop runs at ``settings.GAME_RATE`` (locked to 120) for
        # smooth visuals; the accumulator emits exactly two physics
        # ticks per render frame so motion stays buttery while the
        # 60 Hz physics tunings stay valid. Hitbox samples / bot inputs
        # are emitted at this 60 Hz internal rate.
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
                        pending_presses = 0
                    else:
                        _full_reset()
            elif player.alive and not player.won and not paused:
                before_passed = set(player.passed)
                before_pads = sum(1 for k in before_passed if k[0] in PAD_TYPES)
                before_coins = len(player.coins_collected)
                if manual_takeover:
                    # Human has wrested control from the bot. Drive the
                    # player from real input, exactly like the human-
                    # play branch below, AND enforce the 1-second-of-
                    # silence death rule so a player can't just press
                    # P and let the bot's momentum coast through the
                    # rest of the level untouched.
                    b_held = jump_held
                    press_this_tick = pending_presses > 0
                    if press_this_tick:
                        pending_presses -= 1
                    b_pressed = press_this_tick
                    if jump_held or press_this_tick:
                        takeover_idle_frames = 0
                    else:
                        takeover_idle_frames += 1
                    player.update(jump_held, press_this_tick)
                    if (player.alive and not player.won
                            and takeover_idle_frames >= MANUAL_TAKEOVER_GRACE):
                        player.alive = False
                        if not player.death_reason:
                            player.death_reason = (
                                "Took over but stopped pressing")
                elif bot_controller is not None:
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
                    b_held = jump_held
                    b_pressed = False
                    press_this_tick = pending_presses > 0
                    if press_this_tick:
                        pending_presses -= 1
                    player.update(jump_held, press_this_tick)
                # Bot-click cue: short SFX (user-toggleable) + ring flash
                # around the player so the viewer can see / hear every
                # autobot press. Gated on ``is_sim_run`` so human play
                # never fires it. A click is a False→True edge of the
                # held input — `b_pressed` alone misses ship/wave (which
                # never set pressed) and double-counts consecutive
                # (True, True) ticks the beam search can produce.
                if is_sim_run:
                    click_now = b_held and not prev_b_held
                    prev_b_held = b_held
                    if click_now:
                        if prefs.get("bot_click_sfx_enabled", True):
                            sfx.play("bot_click", 0.5)
                        bot_click_flash = 12
                        bot_press_frames.append(attempt_frames)
                        bot_press_total += 1
                    elif bot_click_flash > 0:
                        bot_click_flash -= 1
                # Desync watchdog: exact-input playbacks are bit-sensitive
                # to any physics drift (level edits, PhysicsParams change,
                # floating-point rounding). Compare live y to the solver's
                # recorded main waypoint at the current x; peak drift is
                # latched across the attempt so a transient spike during
                # a jump arc isn't lost, and a live banner flashes while
                # the drift is currently above threshold so the user
                # notices before the replay dies to a "ghost spike".
                if playback_wp_sorted and playback_inputs is not None:
                    # Binary-search the waypoint bracketing current x.
                    px = player.x + player.size / 2
                    xs = playback_wp_xs
                    if px <= xs[0]:
                        exp_y = playback_wp_sorted[0][1]
                    elif px >= xs[-1]:
                        exp_y = playback_wp_sorted[-1][1]
                    else:
                        lo, hi = 0, len(xs) - 1
                        while hi - lo > 1:
                            mid = (lo + hi) // 2
                            if xs[mid] <= px:
                                lo = mid
                            else:
                                hi = mid
                        x0, y0 = playback_wp_sorted[lo]
                        x1, y1 = playback_wp_sorted[hi]
                        span = x1 - x0
                        t = 0.0 if span <= 1e-9 else (px - x0) / span
                        exp_y = y0 + (y1 - y0) * t
                    drift = abs((player.y + player.size / 2) - exp_y)
                    if drift > desync_max_px:
                        desync_max_px = drift
                    if drift > 24.0:
                        desync_alert_timer = 30
                    elif desync_alert_timer > 0:
                        desync_alert_timer -= 1
                # Dash-orb exhaust: while dash_timer is live, spawn an
                # exhaust puff behind the player's dash vector so the
                # directional-dash reads as a streak instead of a
                # teleport. Emitted from the physics tick (not the
                # render loop) so the density scales with TPS rather
                # than FPS — a 30 FPS display and a 60 FPS display see
                # the same trail density.
                if player.alive and player.dash_timer > 0:
                    particles.dash_trail(
                        player.x + player.size / 2,
                        player.y + player.size / 2,
                        player.dash_vx, player.dash_vy,
                        C_DASH_ORB,
                    )
                # Speedrun timer ticks once per physics frame (60 Hz).
                attempt_frames += 1
                # Ghost replay: sample every 2 frames to keep the list modest.
                if attempt_frames % 2 == 0:
                    current_run.append((attempt_frames, player.x, player.y))
                # Hitbox trace is filled per-substep by the player itself
                # via its `hitbox_trace` hook — see the assignment where
                # `current_hitboxes` was declared. Nothing to sample here.
                # No lower clamp — letting cam_x go negative keeps the
                # camera centred on the player even when they sit
                # within 200 px of x=0 or get teleported backward.
                cam_x = float(player.x) - 200.0

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
                particles.explosion(
                    player.x + player.size / 2,
                    player.y + player.size / 2,
                    C_PLAYER,
                )
                apply_shake(12)
                sfx.play("death", 0.6)
                if level_music:
                    music.stop()
                # Capture death position for the predicted-path overlay's
                # red hitbox marker — drawn while death_timer > 0 so the
                # viewer sees exactly where the bot's plan went wrong.
                _death_hitbox = (player.x, player.y, player.size,
                                 getattr(player, "angle", 0.0),
                                 getattr(player, "death_reason", ""))
                death_timer = 45
                # Slow-mo on the last dying moment — longer + slower than
                # before so the death is more visually punchy. 30 frames
                # at 0.2x = 2.5 seconds of slow-mo.
                death_slowmo_timer = 30
                death_flash_timer = 30
                deaths_this_session += 1
                pending_presses = 0
            particles.update()
            # Free-mode camera: certain gamemode portals flip the camera
            # to follow the player vertically each frame instead of
            # holding the row last set by a camera trigger. We retarget
            # target_cam_y here (rather than at portal-entry) so the
            # easing below tracks the player smoothly through the mode.
            if player.free_cam_mode:
                player.target_cam_y = (
                    player.y + player.size / 2 - HEIGHT / 2)
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
        shake_x, shake_y = shake_offset
        render_world(screen, cam_x, cam_y, shake_x, shake_y, stars, mountains,
                     bg_top, bg_bot, pulse, _deco_layer, _deco_xs,
                     _main_layer, _main_xs, player.coins_collected)
        # Hint path overlay: when the player has toggled hint mode on, draw
        # the autobot's solved waypoints as a translucent dotted line so
        # they can preview the optimal route. Drawn BEFORE the per-run
        # ghost so the live ghost (player's own best) sits on top.
        render_hint_overlay(screen, _overlay_scratch, _CLEAR, hint_visible,
                            hint_path, hint_mirror_path, cam_x, cam_y,
                            shake_x, shake_y)
        # Pathfinder predicted-path overlay (Y bot): draw the bot's
        # planned (x, y) sequence as a forward-fading green line that
        # starts at the player's current x and extends a few seconds
        # into the future. Persists across the whole attempt — every
        # frame slices a fresh forward window via bisect.
        render_predicted_path(screen, _overlay_scratch, _CLEAR,
                              pred_path_sorted, pred_path_xs,
                              player.x, player.size, cam_x, cam_y,
                              shake_x, shake_y)
        # Y-bot ghost overlay: render the click and no-click probe
        # trajectories as translucent lines so the viewer can compare
        # the bot's actual decisions against both candidates.
        render_ghost_paths(screen, _overlay_scratch, _CLEAR, ghost_paths,
                          bot_frame, playback_inputs, bot_controller,
                          cam_x, cam_y, shake_x, shake_y)
        # Death hitbox marker (Y bot): on death, freeze a translucent
        # red rect at the player's death position so the viewer can
        # see exactly where the plan failed. Only drawn while
        # death_timer > 0 so a fresh attempt doesn't show stale marks.
        render_death_hitbox_marker(screen, _overlay_scratch, _CLEAR,
                                   predicted_path, _death_hitbox,
                                   death_timer, cam_x, cam_y,
                                   shake_x, shake_y)
        # Ghost overlay: draw a fading trail of the best prior run so the
        # player can see where they previously got further.
        render_best_run_ghost(screen, _overlay_scratch, _CLEAR, best_run,
                              attempt_frames, cam_x, cam_y, shake_x, shake_y)
        render_player_and_particles(screen, player, particles, death_timer,
                                    bot_click_flash, cam_x, cam_y,
                                    shake_x, shake_y)

        # Checkpoint markers — little flag drawn at every saved spot.
        # Only in practice mode (that's the only mode that saves them)
        # and before the player wins, so the win card isn't cluttered.
        render_checkpoint_markers(screen, practice_mode, player, pulse,
                                  cam_x, cam_y, shake_x, shake_y)

        # (Red full-screen death flash removed — the slow-mo vignette,
        # explosion particles, camera shake and "Hit a spike" readout
        # below already signal death clearly, and the flash felt
        # visually heavy.)

        # Death reason readout — shows shortly after death so the
        # player gets a short explanation of what killed them ("Hit a
        # spike", "Fell off the screen", etc.) before the next attempt.
        render_death_reason(screen, death_timer, player)

        # Slow-mo vignette: bordered darkening when death_slowmo_timer is active.
        render_slowmo_vignette(screen, _overlay_scratch, _CLEAR,
                               death_slowmo_timer)

        # Pulse trigger: brief screen-tinted flash modulated by BPM.
        pulse_amp = player.pulse_intensity()
        render_pulse_flash(screen, _overlay_scratch, pulse_amp)
        if death_flash_timer > 0:
            death_flash_timer -= 1
        # (Checkpoint green flash removed — the in-world flag markers
        # now convey "saved here" more clearly and don't obscure the
        # player's surroundings at the moment the save happens.)

        # ---- HUD ----------------------------------------------------------
        render_hud(screen, player, max_x, attempts, attempt_frames, meta,
                  is_sim_run, bot_press_frames, bot_press_total,
                  manual_takeover, takeover_idle_frames,
                  MANUAL_TAKEOVER_GRACE, level_name, total_coins,
                  practice_mode, hint_visible, hint_path, hint_status,
                  editor_test, test_speed_idx, test_speeds, bot_controller,
                  playback_inputs, bot_frame, playback_wp_sorted,
                  desync_alert_timer, desync_max_px)

        # ---- Debug overlay (F3) -------------------------------------------
        # If the level has a T_JUMP_PREDICTOR probe, F3 switches from the
        # generic debug HUD to the predictor's arc + summary instead —
        # the probe exists specifically to answer "does this click work?",
        # and stacking both readouts would just obscure the arc.
        render_debug_overlay(screen, show_debug, objects, cam_x, cam_y,
                             player, attempts, _dbg_frame_times)

        # ---- Level-state HUD (toggle: I) ---------------------------------
        # Shows the player's CURRENT mode / speed / size / gravity / dual
        # / time warp / position so a level author can verify in-place
        # what a given trigger arrangement actually produces. Auto-on in
        # editor_test runs because that's exactly when this readout is
        # most useful — manually re-creating "is this section dual at
        # 1.65x in mini wave?" by reading triggers off the screen is
        # what this overlay exists to avoid.
        render_state_hud(screen, show_state, player)

        # ---- Pause overlay ------------------------------------------------
        r_mute_music, r_mute_sfx = render_pause_overlay(
            screen, paused, mpos, attempts, player, max_x, practice_mode,
            pause_menu_buttons)

        # ---- Win overlay --------------------------------------------------
        win_sfx_played = render_win_overlay(
            screen, player, mpos, win_sfx_played, level_music, meta,
            attempts, deaths_this_session, attempt_frames, total_coins,
            meta_persisted, is_sim_run, rc_menu, rc_replay, _persist_win)

        pygame.display.flip()
        # clock.tick sleeps to cap at fps_cap and returns the ms that
        # elapsed since the previous call — stash it as the next frame's
        # dt so sim_accum can advance by wall-clock * TPS.
        _dt_ms = clock.tick(settings.get_fps_cap())
        last_dt_sec = _dt_ms / 1000.0
