"""Bot menu — replaces the old L/K hotkeys with a proper UI.

Opened from the editor (B key) and from a play session (B key). Lets the
user run the autobot solver, watch its progress, view the result, tweak a
couple of search-quality knobs, and (for the editor) replay the solved
inputs against the live player.

The menu is intentionally non-modal in spirit — it only blocks while the
solver is actually crunching. When idle it just sits there waiting for a
button click.

Returns either ``None`` (cancelled, no path produced) or ``(waypoints,
status)`` where ``status`` is one of ``"ok"`` / ``"partial"`` / ``"failed"``
and ``waypoints`` is a list of ``(x, y)`` world-pixel coordinates that
visualise the route. The caller (play / editor) uses the path as a hint
overlay and ``status`` to colour the badge.
"""

import sys
import time
import traceback

import pygame

from constants import (
    WIDTH, HEIGHT,
    C_DARK, C_WHITE, C_GRAY, C_BLOCK_H, C_BTN, C_DANGER, C_SUCCESS,
)
from graphics import (
    draw_bg, txt, btn, make_stars, make_mountains, lighter, darker,
)
from input_guard import ClickGuard
import bot_saves
import settings


# ---------------------------------------------------------------------------
# Persistent (within-session) bot tuning knobs
# ---------------------------------------------------------------------------
# Stored at module level so the values survive between menu invocations
# without having to round-trip through prefs (the user is unlikely to want
# bot-tuning persisted across sessions; each level wants different values).
_bot_beam_widths = [32, 48, 96, 192]
_bot_beam_idx = 1            # default = 48 (matches AutoBot.BEAM_WIDTH)
_bot_max_frames_opts = [5000, 10000, 20000, 40000]
_bot_max_frames_idx = 1      # default = 10000
_bot_use_parallel = True
_bot_n_attempts_opts = [1, 2, 3, 4, 5, 6, 8]
_bot_n_attempts_idx = 3      # default = 4
_bot_n_workers_opts = [1, 2, 3, 4, 6, 8]
_bot_n_workers_idx = 2       # default = 3
# Fix-only: when True, Find Path only verifies the current seed and, if it
# doesn't still win, runs ONE short beam search to patch the break. No
# wider retries, no multi-attempt ramp, no gap-fill / brute-force. Meant
# for "I just added a decoration, just re-verify".
_bot_fix_only = False

# Last solve result (kept for "Replay last" so re-opening the menu doesn't
# force a re-solve on the same level).
_last_waypoints = None
_last_mirror_waypoints = None
_last_inputs = None
_last_status = ""            # "" | "ok" | "partial" | "failed"


def get_last_inputs():
    """Editor uses this to drive the K-style replay against a live player."""
    return list(_last_inputs) if _last_inputs else []


def get_last_mirror_waypoints():
    """Editor / play overlay reads this to draw the dual mirror's path in
    blue alongside the main yellow path. Empty list when no dual segment."""
    return list(_last_mirror_waypoints) if _last_mirror_waypoints else []


def clear_last_solve():
    """Discard the cached solution. Call after edits invalidate the path."""
    global _last_waypoints, _last_mirror_waypoints, _last_inputs, _last_status
    _last_waypoints = None
    _last_mirror_waypoints = None
    _last_inputs = None
    _last_status = ""


def _strip_internal(objects):
    """Drop the live-player bookkeeping fields (``_orig_x`` etc.) so the
    solver sees clean object dicts."""
    out = []
    for o in objects:
        co = {k: v for k, v in o.items()
              if not (isinstance(k, str) and k.startswith("_"))}
        out.append(co)
    return out


def _run_solver(screen, clock, objects, params=None):
    """Invoke the autobot with the current beam-width / max-frames knobs.

    Returns ``(waypoints, mirror_waypoints, inputs, status, error)``.
    ``mirror_waypoints`` is the parallel path of the dual mirror (empty
    list if the level never enters dual mode). ``error`` is a short string
    describing why the solver returned no path (or empty when it succeeded
    / partially succeeded). Wraps the solver in a try/except so a malformed
    level can't crash the menu — but the exception class is surfaced via
    ``error`` so the user has *something* to act on instead of a silent
    "failed".

    Passes the previously-solved input sequence to the solver as ``seed_inputs``
    so unchanged regions of the level don't have to be re-explored. The solver
    verifies the cached path against the current level first; if it still wins
    (e.g. the user only added decoration), the solve returns instantly.
    """
    try:
        from autobot import AutoBot
        clean = _strip_internal(objects)
        solver = AutoBot(clean, params=params)
        solver.BEAM_WIDTH = _bot_beam_widths[_bot_beam_idx]
        max_frames = _bot_max_frames_opts[_bot_max_frames_idx]
        seed = list(_last_inputs) if _last_inputs else None
        n_attempts = _bot_n_attempts_opts[_bot_n_attempts_idx]
        n_workers = _bot_n_workers_opts[_bot_n_workers_idx] if _bot_use_parallel else 1
        # Fix-only: refuse at this layer if there's no seed to repair —
        # the solver itself does the same check, but surfacing it as an
        # error string gives the user something actionable instead of a
        # bare "failed".
        if _bot_fix_only and not seed:
            return None, [], [], "failed", (
                "fix-only needs a saved run to repair — "
                "solve once or load a saved run first")
        wp, mwp, inputs, won = solver.solve(
            screen, clock, max_frames=max_frames, seed_inputs=seed,
            n_attempts=n_attempts, use_parallel=_bot_use_parallel,
            n_workers=n_workers, fix_only=_bot_fix_only)
        if not wp:
            # Solver ran but couldn't even produce a partial path. This
            # usually means every beam candidate died on frame 1 (e.g.
            # spike at spawn) — tell the user, don't just silently fail.
            return None, [], [], "failed", "no path found (level may be unsolvable)"
        return list(wp), list(mwp), list(inputs), ("ok" if won else "partial"), ""
    except Exception as exc:
        traceback.print_exc()
        return None, [], [], "failed", f"crash: {type(exc).__name__}: {exc}"


def _pick_saved_run(screen, clock, level_key):
    """Modal picker listing saved bot runs for this level.

    Returns the loaded-and-hydrated payload (see ``bot_saves.load_run``)
    or ``None`` if the user cancels / deletes the only entry / there are
    no saves yet. Supports delete via a small "×" button on each row so
    the user can prune old saves without leaving the menu.
    """
    guard = ClickGuard()
    stars = make_stars()
    panel_w = 520
    panel_h = 520
    panel = pygame.Rect((WIDTH - panel_w) // 2,
                        (HEIGHT - panel_h) // 2,
                        panel_w, panel_h)
    info_msg = ""
    info_color = C_GRAY

    while True:
        guard.tick()
        mpos = pygame.mouse.get_pos()
        click_pos = None
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                return None
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if not guard.consume_click(ev):
                    continue
                click_pos = ev.pos

        runs = bot_saves.list_runs(level_key)

        draw_bg(screen, 0, stars)
        ov = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 200))
        screen.blit(ov, (0, 0))
        pygame.draw.rect(screen, darker(C_DARK, 10), panel.move(0, 6),
                         border_radius=14)
        pygame.draw.rect(screen, C_DARK, panel, border_radius=14)
        pygame.draw.rect(screen, C_BLOCK_H, panel, 2, border_radius=14)

        txt(screen, "LOAD SAVED BOT RUN", panel.centerx, panel.y + 24, 22,
            C_WHITE, True, shadow=True)
        txt(screen, "Click a row to load, × to delete.",
            panel.centerx, panel.y + 52, 13, C_GRAY, True)

        row_h = 56
        list_top = panel.y + 82
        list_bottom = panel.bottom - 70
        max_rows = max(1, (list_bottom - list_top) // row_h)

        if not runs:
            txt(screen, "No saved runs for this level yet.",
                panel.centerx, list_top + 40, 15, C_GRAY, True)
        for i, entry in enumerate(runs[:max_rows]):
            ry = list_top + i * row_h
            row_rect = pygame.Rect(panel.x + 16, ry, panel.w - 32, row_h - 8)
            hov = row_rect.collidepoint(mpos)
            bg = lighter(C_BTN, 20) if hov else C_BTN
            pygame.draw.rect(screen, darker(bg, 40), row_rect.move(0, 3),
                             border_radius=8)
            pygame.draw.rect(screen, bg, row_rect, border_radius=8)
            pygame.draw.rect(screen, C_BLOCK_H, row_rect, 1, border_radius=8)
            # Name + status badge
            status_col = {
                "ok": C_SUCCESS,
                "partial": (250, 200, 80),
                "failed": C_DANGER,
            }.get(entry["status"], C_GRAY)
            txt(screen, entry["name"], row_rect.x + 14, row_rect.y + 8,
                17, C_WHITE, shadow=True)
            ts = entry["saved_at"]
            age = "never" if not ts else time.strftime(
                "%Y-%m-%d %H:%M", time.localtime(ts))
            txt(screen, f"{age}  ·  {entry['input_frames']} frames  ·  "
                f"{entry['status'] or '—'}",
                row_rect.x + 14, row_rect.y + 30, 12, status_col)
            # Delete button on the right edge.
            del_rect = pygame.Rect(row_rect.right - 40, row_rect.y + 10,
                                   28, row_rect.h - 20)
            del_hov = del_rect.collidepoint(mpos)
            dcol = C_DANGER if del_hov else darker(C_DANGER, 30)
            pygame.draw.rect(screen, dcol, del_rect, border_radius=6)
            txt(screen, "×", del_rect.centerx, del_rect.centery, 18,
                C_WHITE, True)
            if click_pos:
                if del_rect.collidepoint(click_pos):
                    bot_saves.delete_run(level_key, entry["name"])
                    info_msg = f"Deleted \"{entry['name']}\"."
                    info_color = C_GRAY
                    click_pos = None  # consumed
                elif row_rect.collidepoint(click_pos):
                    data = bot_saves.load_run(level_key, entry["name"])
                    if data is not None:
                        return data
                    info_msg = "Load failed (file malformed?)."
                    info_color = C_DANGER
                    click_pos = None

        if info_msg:
            txt(screen, info_msg, panel.centerx, panel.bottom - 50, 13,
                info_color, True)

        b_back = btn(screen, "BACK", panel.centerx,
                     panel.bottom - 24, 200, 34, C_DANGER, mpos, font_size=14)
        if click_pos and b_back.collidepoint(click_pos):
            return None

        pygame.display.flip()
        clock.tick(settings.get_fps_cap())


def run_bot_menu(screen, clock, objects, precomputed_path=None,
                 allow_replay=False, replay_callback=None,
                 level_filename=None, meta=None):
    """Show the bot menu.

    Parameters
    ----------
    screen, clock : pygame Surface and Clock
    objects : list of object dicts
        The level the bot will solve. The solver gets a deep-copied,
        sanitised version so it can't perturb the caller's state.
    precomputed_path : list of (x, y) or ``None``
        If the caller already has a path (e.g. play.py's hint cache),
        passing it in shows the "View overlay" choice immediately without
        forcing a re-solve.
    allow_replay : bool
        If True (editor), shows a "Replay (K)" button that calls
        ``replay_callback`` after closing the menu. The replay is run by
        the caller because only the caller has the full editor context.
    replay_callback : callable or None
        Invoked with the solved input list when the user clicks Replay.
    level_filename : str or None
        Identifies the level for Save / Load-run. When None, a content
        hash of ``objects`` is used so unsaved editor work still gets a
        stable (if less friendly) key.

    Returns
    -------
    Either ``None`` (no path to hand back to caller) or
    ``(waypoints, status)`` — caller installs as the hint overlay.
    """
    global _bot_beam_idx, _bot_max_frames_idx
    global _bot_use_parallel, _bot_n_attempts_idx, _bot_n_workers_idx
    global _bot_fix_only
    global _last_waypoints, _last_mirror_waypoints, _last_inputs, _last_status

    if precomputed_path is not None and not _last_waypoints:
        # Adopt the caller's path so "View overlay" works immediately.
        _last_waypoints = list(precomputed_path)
        _last_status = "ok"

    # B5: per-level physics override — fetch once so Find Path and the
    # Enter-to-solve shortcut both see the level's feel, not vanilla.
    from physics import PhysicsParams
    params = PhysicsParams.from_meta(meta)

    # Prefer filename-based keys (human-debuggable, stable across edits
    # that don't change the save file) and fall back to a content hash for
    # unsaved editor work.
    level_key = (bot_saves.level_key_from_filename(level_filename)
                 or bot_saves.level_key_from_objects(_strip_internal(objects)))

    stars = make_stars()
    mountains = make_mountains()
    guard = ClickGuard()

    panel_w = 560
    # Panel clamped to HEIGHT so nothing clips off the screen. Rows below
    # are tightened (48 → 40-44 per step) to keep everything visible
    # without the old 720-tall panel that went off-screen.
    panel_h = min(660, HEIGHT - 20)
    panel = pygame.Rect((WIDTH - panel_w) // 2,
                        (HEIGHT - panel_h) // 2,
                        panel_w, panel_h)

    # Result for the caller — set by the relevant button.
    return_value = None
    info_msg = ""
    info_color = C_GRAY

    while True:
        guard.tick()
        mpos = pygame.mouse.get_pos()
        click_pos = None
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    return return_value
                if ev.key == pygame.K_RETURN:
                    # Quick-action: re-solve.
                    wp, mwp, inputs, status, err = _run_solver(
                        screen, clock, objects, params=params)
                    if wp:
                        _last_waypoints = wp
                        _last_mirror_waypoints = mwp
                        _last_inputs = inputs
                        _last_status = status
                        return_value = (wp, status)
                        info_msg = {
                            "ok": "Solved! Path drawn as hint overlay.",
                            "partial": "Partial path found — bot got stuck.",
                        }.get(status, "Solver failed.")
                        info_color = (C_SUCCESS if status == "ok"
                                      else (250, 200, 80) if status == "partial"
                                      else C_DANGER)
                    else:
                        info_msg = (f"Solver failed — {err}"
                                    if err else "Solver failed.")
                        info_color = C_DANGER
                    guard.reset()
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if not guard.consume_click(ev):
                    continue
                click_pos = ev.pos

        # ---- background --------------------------------------------------
        draw_bg(screen, 0, stars, mountains)
        ov = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 180))
        screen.blit(ov, (0, 0))
        pygame.draw.rect(screen, darker(C_DARK, 10), panel.move(0, 6),
                         border_radius=14)
        pygame.draw.rect(screen, C_DARK, panel, border_radius=14)
        pygame.draw.rect(screen, C_BLOCK_H, panel, 2, border_radius=14)

        txt(screen, "AUTO-BOT", panel.centerx, panel.y + 22, 30, C_WHITE,
            True, shadow=True)
        txt(screen, "Beam-search solver", panel.centerx, panel.y + 56, 14,
            C_GRAY, True)

        col_x = panel.x + 32
        val_x = panel.x + panel.w - 220
        row_y = panel.y + 90
        # Tighter row pitch than before so the six toggle rows + summary +
        # action buttons all fit inside a panel that doesn't clip the
        # screen (old 720 panel ran off the bottom).
        _STEP = 44

        # ---- Beam width ---------------------------------------------------
        txt(screen, "Beam width", col_x, row_y, 16, C_WHITE)
        bw_label = f"{_bot_beam_widths[_bot_beam_idx]}"
        b_bw = btn(screen, f"< {bw_label} >", val_x + 80, row_y + 12, 200, 32,
                   (60, 90, 160), mpos, font_size=15)
        if click_pos and b_bw.collidepoint(click_pos):
            # Cycle: left half decreases, right half increases.
            if click_pos[0] < b_bw.centerx:
                _bot_beam_idx = (_bot_beam_idx - 1) % len(_bot_beam_widths)
            else:
                _bot_beam_idx = (_bot_beam_idx + 1) % len(_bot_beam_widths)
        row_y += _STEP

        # ---- Max frames ---------------------------------------------------
        txt(screen, "Max frames", col_x, row_y, 16, C_WHITE)
        mf_label = f"{_bot_max_frames_opts[_bot_max_frames_idx]:,}"
        b_mf = btn(screen, f"< {mf_label} >", val_x + 80, row_y + 12, 200, 32,
                   (60, 90, 160), mpos, font_size=15)
        if click_pos and b_mf.collidepoint(click_pos):
            if click_pos[0] < b_mf.centerx:
                _bot_max_frames_idx = (_bot_max_frames_idx - 1) % len(_bot_max_frames_opts)
            else:
                _bot_max_frames_idx = (_bot_max_frames_idx + 1) % len(_bot_max_frames_opts)
        row_y += _STEP

        # ---- Attempts -----------------------------------------------------
        txt(screen, "Attempts", col_x, row_y, 16, C_WHITE)
        na_label = f"{_bot_n_attempts_opts[_bot_n_attempts_idx]}"
        b_na = btn(screen, f"< {na_label} >", val_x + 80, row_y + 12, 200, 32,
                   (60, 90, 160), mpos, font_size=15)
        if click_pos and b_na.collidepoint(click_pos):
            if click_pos[0] < b_na.centerx:
                _bot_n_attempts_idx = (_bot_n_attempts_idx - 1) % len(_bot_n_attempts_opts)
            else:
                _bot_n_attempts_idx = (_bot_n_attempts_idx + 1) % len(_bot_n_attempts_opts)
        row_y += _STEP

        # ---- Parallel toggle ----------------------------------------------
        par_label = "ON" if _bot_use_parallel else "OFF"
        par_col = (60, 130, 60) if _bot_use_parallel else (130, 60, 60)
        txt(screen, "Parallel", col_x, row_y, 16, C_WHITE)
        b_par = btn(screen, par_label, val_x + 80, row_y + 12, 200, 32,
                    par_col, mpos, font_size=15)
        if click_pos and b_par.collidepoint(click_pos):
            _bot_use_parallel = not _bot_use_parallel
        row_y += _STEP

        # ---- Workers (only meaningful when parallel is on) ----------------
        if _bot_use_parallel:
            txt(screen, "Workers", col_x, row_y, 16, C_WHITE)
            nw_label = f"{_bot_n_workers_opts[_bot_n_workers_idx]}"
            b_nw = btn(screen, f"< {nw_label} >", val_x + 80, row_y + 12, 200, 32,
                       (60, 90, 160), mpos, font_size=15)
            if click_pos and b_nw.collidepoint(click_pos):
                if click_pos[0] < b_nw.centerx:
                    _bot_n_workers_idx = (_bot_n_workers_idx - 1) % len(_bot_n_workers_opts)
                else:
                    _bot_n_workers_idx = (_bot_n_workers_idx + 1) % len(_bot_n_workers_opts)
        row_y += _STEP

        # ---- Fix-only toggle ----------------------------------------------
        # "Fix only" means: keep the current seed, run a minimal repair
        # beam from the last-alive prefix and stop. Much faster than a
        # full solve when the level has only been tweaked slightly.
        fo_label = "ON" if _bot_fix_only else "OFF"
        fo_col = (130, 90, 60) if _bot_fix_only else (70, 70, 80)
        txt(screen, "Fix only", col_x, row_y, 16, C_WHITE)
        b_fo = btn(screen, fo_label, val_x + 80, row_y + 12, 200, 32,
                   fo_col, mpos, font_size=15)
        if click_pos and b_fo.collidepoint(click_pos):
            _bot_fix_only = not _bot_fix_only
        row_y += _STEP

        # ---- Last solve summary -------------------------------------------
        if _last_status:
            status_color = {
                "ok": C_SUCCESS,
                "partial": (250, 200, 80),
                "failed": C_DANGER,
            }.get(_last_status, C_GRAY)
            label = {
                "ok": "Last result: SOLVED",
                "partial": "Last result: PARTIAL",
                "failed": "Last result: FAILED",
            }.get(_last_status, "—")
            txt(screen, label, col_x, row_y, 15, status_color)
            wp_count = len(_last_waypoints) if _last_waypoints else 0
            in_count = len(_last_inputs) if _last_inputs else 0
            txt(screen, f"{wp_count} waypoints  ·  {in_count} input frames",
                col_x, row_y + 20, 12, C_GRAY)
        else:
            txt(screen, "No path computed yet.", col_x, row_y, 14, C_GRAY)
        row_y += 48

        # ---- Action buttons ----------------------------------------------
        b_solve = btn(screen, "Find Path (Solve)",
                      panel.centerx, row_y + 14, 320, 40, C_BTN, mpos)
        if click_pos and b_solve.collidepoint(click_pos):
            wp, mwp, inputs, status, err = _run_solver(
                screen, clock, objects, params=params)
            if wp:
                _last_waypoints = wp
                _last_mirror_waypoints = mwp
                _last_inputs = inputs
                _last_status = status
                return_value = (wp, status)
                info_msg = {
                    "ok": "Solved! Path drawn as hint overlay.",
                    "partial": "Partial path found — bot got stuck.",
                }.get(status, "Solver failed.")
                info_color = (C_SUCCESS if status == "ok"
                              else (250, 200, 80) if status == "partial"
                              else C_DANGER)
            else:
                # Show the actual reason instead of a generic "try wider".
                # Crashes (KeyError, etc.) need the user to know there's a
                # bug to report, not to keep retrying with bigger beams.
                info_msg = (f"Solver failed — {err}"
                            if err else "Solver failed. Try a wider beam.")
                info_color = C_DANGER
            guard.reset()
        row_y += 46

        # Buttons that depend on having a solve cached: render them with the
        # `disabled` flag when there's nothing to act on so the user can SEE
        # they're inactive. Clicks on the disabled rect surface a one-line
        # hint instead of silently no-op-ing — that "silent no-op" is what
        # made these feel "completely broken".
        view_disabled = not _last_waypoints
        b_view = btn(screen, "Use as Hint Overlay",
                     panel.centerx, row_y + 14, 320, 34,
                     (80, 130, 80), mpos, font_size=15,
                     disabled=view_disabled)
        if click_pos and b_view.collidepoint(click_pos):
            if view_disabled:
                info_msg = "Solve a path first (or use Find Path)."
                info_color = (250, 200, 80)
            else:
                return_value = (list(_last_waypoints), _last_status or "ok")
                info_msg = "Hint overlay enabled."
                info_color = C_SUCCESS
        row_y += 40

        if allow_replay:
            replay_disabled = not _last_inputs
            b_replay = btn(screen, "Replay solved inputs",
                           panel.centerx, row_y + 14, 320, 34,
                           (140, 80, 180), mpos, font_size=15,
                           disabled=replay_disabled)
            if click_pos and b_replay.collidepoint(click_pos):
                if replay_disabled:
                    # Drawn-only waypoints (Bot tool) don't carry inputs —
                    # the user has to run Find Path to get a replayable
                    # input sequence. Spell that out.
                    info_msg = "Run Find Path first to get replayable inputs."
                    info_color = (250, 200, 80)
                elif replay_callback is not None:
                    try:
                        replay_callback(list(_last_inputs))
                    except Exception as exc:
                        # Don't swallow silently — show the user what
                        # crashed so they can report it.
                        info_msg = (
                            f"Replay crashed: {type(exc).__name__}")
                        info_color = C_DANGER
                    else:
                        return return_value
            row_y += 40

        # ---- Save / Load saved runs --------------------------------------
        # Save is disabled when there's no solved run to persist (the bot
        # tool's drawn waypoints have no `_last_inputs`, so there's
        # nothing meaningful to save). Load is always enabled — even if
        # no runs exist yet, the picker shows a friendly "no runs" state.
        save_disabled = not _last_inputs
        b_save = btn(screen, "Save run...",
                     panel.centerx - 82, row_y + 14, 156, 34,
                     (80, 150, 110), mpos, font_size=14,
                     disabled=save_disabled)
        b_load = btn(screen, "Load run...",
                     panel.centerx + 82, row_y + 14, 156, 34,
                     (80, 110, 160), mpos, font_size=14)
        if click_pos and b_save.collidepoint(click_pos):
            if save_disabled:
                info_msg = "Solve first — nothing to save."
                info_color = (250, 200, 80)
            else:
                from menus import text_input_dialog
                name = text_input_dialog(
                    screen, clock, prompt="Save bot run as:",
                    default=f"run_{time.strftime('%Y%m%d_%H%M')}")
                guard.reset()
                if name:
                    ok = bot_saves.save_run(
                        level_key, name,
                        inputs=_last_inputs,
                        waypoints=_last_waypoints,
                        mirror_waypoints=_last_mirror_waypoints,
                        status=_last_status or "ok",
                        beam_width=_bot_beam_widths[_bot_beam_idx],
                        attempts=_bot_n_attempts_opts[_bot_n_attempts_idx])
                    if ok:
                        info_msg = f"Saved run \"{name}\"."
                        info_color = C_SUCCESS
                    else:
                        info_msg = "Save failed (disk error)."
                        info_color = C_DANGER
                else:
                    info_msg = "Save cancelled."
                    info_color = C_GRAY
        if click_pos and b_load.collidepoint(click_pos):
            picked = _pick_saved_run(screen, clock, level_key)
            guard.reset()
            if picked is not None:
                _last_inputs = list(picked["inputs"])
                _last_waypoints = list(picked["waypoints"])
                _last_mirror_waypoints = list(picked["mirror_waypoints"])
                _last_status = picked.get("status") or "ok"
                return_value = (list(_last_waypoints), _last_status)
                info_msg = (f"Loaded \"{picked['name']}\" "
                            f"({len(_last_inputs)} frames).")
                info_color = C_SUCCESS
            else:
                info_msg = info_msg or ""

        # ---- Status line / Back ------------------------------------------
        # Info + BACK sit in a reserved footer zone near panel bottom; the
        # "Clear cached path" button was removed (save/load pickers cover
        # the same need without an overflow-prone extra row).
        if info_msg:
            txt(screen, info_msg, panel.centerx, panel.bottom - 55, 13,
                info_color, True)

        b_back = btn(screen, "BACK", panel.centerx,
                     panel.bottom - 26, 200, 32, C_DANGER, mpos, font_size=14)
        if click_pos and b_back.collidepoint(click_pos):
            return return_value

        # Keep the keyboard hint INSIDE the panel (old code placed it at
        # panel.bottom + 16 which clipped off the screen).
        txt(screen, "Enter: solve  ·  Esc: back",
            panel.centerx, panel.bottom - 8, 11, C_GRAY, True)
        pygame.display.flip()
        clock.tick(settings.get_fps_cap())
