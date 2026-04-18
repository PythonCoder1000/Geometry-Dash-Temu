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

import pygame

from constants import (
    WIDTH, HEIGHT,
    C_DARK, C_WHITE, C_GRAY, C_BLOCK_H, C_BTN, C_DANGER, C_SUCCESS,
)
from graphics import (
    draw_bg, txt, btn, make_stars, make_mountains, lighter, darker,
)
from input_guard import ClickGuard
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

# Last solve result (kept for "Replay last" so re-opening the menu doesn't
# force a re-solve on the same level).
_last_waypoints = None
_last_inputs = None
_last_status = ""            # "" | "ok" | "partial" | "failed"


def get_last_inputs():
    """Editor uses this to drive the K-style replay against a live player."""
    return list(_last_inputs) if _last_inputs else []


def clear_last_solve():
    """Discard the cached solution. Call after edits invalidate the path."""
    global _last_waypoints, _last_inputs, _last_status
    _last_waypoints = None
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


def _run_solver(screen, clock, objects):
    """Invoke the autobot with the current beam-width / max-frames knobs.

    Returns ``(waypoints, inputs, status, error)``. ``error`` is a short
    string describing why the solver returned no path (or empty when it
    succeeded / partially succeeded). Wraps the solver in a try/except so a
    malformed level can't crash the menu — but the exception class is
    surfaced via ``error`` so the user has *something* to act on instead of
    a silent "failed".

    Passes the previously-solved input sequence to the solver as ``seed_inputs``
    so unchanged regions of the level don't have to be re-explored. The solver
    verifies the cached path against the current level first; if it still wins
    (e.g. the user only added decoration), the solve returns instantly.
    """
    try:
        from autobot import AutoBot
        clean = _strip_internal(objects)
        solver = AutoBot(clean)
        solver.BEAM_WIDTH = _bot_beam_widths[_bot_beam_idx]
        max_frames = _bot_max_frames_opts[_bot_max_frames_idx]
        seed = list(_last_inputs) if _last_inputs else None
        wp, inputs, won = solver.solve(screen, clock, max_frames=max_frames,
                                       seed_inputs=seed)
        if not wp:
            # Solver ran but couldn't even produce a partial path. This
            # usually means every beam candidate died on frame 1 (e.g.
            # spike at spawn) — tell the user, don't just silently fail.
            return None, [], "failed", "no path found (level may be unsolvable)"
        return list(wp), list(inputs), ("ok" if won else "partial"), ""
    except Exception as exc:
        # Surface the exception class — full traceback would be unreadable
        # in a one-line status, but the type name often points at the bug
        # (KeyError on object dict, AttributeError on missing field, etc.)
        return None, [], "failed", f"crash: {type(exc).__name__}: {exc}"


def run_bot_menu(screen, clock, objects, precomputed_path=None,
                 allow_replay=False, replay_callback=None):
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

    Returns
    -------
    Either ``None`` (no path to hand back to caller) or
    ``(waypoints, status)`` — caller installs as the hint overlay.
    """
    global _bot_beam_idx, _bot_max_frames_idx
    global _last_waypoints, _last_inputs, _last_status

    if precomputed_path is not None and not _last_waypoints:
        # Adopt the caller's path so "View overlay" works immediately.
        _last_waypoints = list(precomputed_path)
        _last_status = "ok"

    stars = make_stars()
    mountains = make_mountains()
    guard = ClickGuard()

    panel_w = 560
    panel_h = 520
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
                    wp, inputs, status, err = _run_solver(
                        screen, clock, objects)
                    if wp:
                        _last_waypoints = wp
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
        row_y = panel.y + 100

        # ---- Beam width ---------------------------------------------------
        txt(screen, "Beam width", col_x, row_y, 16, C_WHITE)
        bw_label = f"{_bot_beam_widths[_bot_beam_idx]}"
        b_bw = btn(screen, f"< {bw_label} >", val_x + 80, row_y + 12, 200, 36,
                   (60, 90, 160), mpos, font_size=15)
        if click_pos and b_bw.collidepoint(click_pos):
            # Cycle: left half decreases, right half increases.
            if click_pos[0] < b_bw.centerx:
                _bot_beam_idx = (_bot_beam_idx - 1) % len(_bot_beam_widths)
            else:
                _bot_beam_idx = (_bot_beam_idx + 1) % len(_bot_beam_widths)
        row_y += 60

        # ---- Max frames ---------------------------------------------------
        txt(screen, "Max frames", col_x, row_y, 16, C_WHITE)
        mf_label = f"{_bot_max_frames_opts[_bot_max_frames_idx]:,}"
        b_mf = btn(screen, f"< {mf_label} >", val_x + 80, row_y + 12, 200, 36,
                   (60, 90, 160), mpos, font_size=15)
        if click_pos and b_mf.collidepoint(click_pos):
            if click_pos[0] < b_mf.centerx:
                _bot_max_frames_idx = (_bot_max_frames_idx - 1) % len(_bot_max_frames_opts)
            else:
                _bot_max_frames_idx = (_bot_max_frames_idx + 1) % len(_bot_max_frames_opts)
        row_y += 60

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
            txt(screen, label, col_x, row_y, 16, status_color)
            wp_count = len(_last_waypoints) if _last_waypoints else 0
            in_count = len(_last_inputs) if _last_inputs else 0
            txt(screen, f"{wp_count} waypoints  ·  {in_count} input frames",
                col_x, row_y + 22, 13, C_GRAY)
        else:
            txt(screen, "No path computed yet.", col_x, row_y, 14, C_GRAY)
        row_y += 60

        # ---- Action buttons ----------------------------------------------
        b_solve = btn(screen, "Find Path (Solve)",
                      panel.centerx, row_y + 16, 320, 44, C_BTN, mpos)
        if click_pos and b_solve.collidepoint(click_pos):
            wp, inputs, status, err = _run_solver(screen, clock, objects)
            if wp:
                _last_waypoints = wp
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
        row_y += 56

        # Buttons that depend on having a solve cached: render them with the
        # `disabled` flag when there's nothing to act on so the user can SEE
        # they're inactive. Clicks on the disabled rect surface a one-line
        # hint instead of silently no-op-ing — that "silent no-op" is what
        # made these feel "completely broken".
        view_disabled = not _last_waypoints
        b_view = btn(screen, "Use as Hint Overlay",
                     panel.centerx, row_y + 16, 320, 38,
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
        row_y += 48

        if allow_replay:
            replay_disabled = not _last_inputs
            b_replay = btn(screen, "Replay solved inputs",
                           panel.centerx, row_y + 16, 320, 38,
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
            row_y += 48

        clear_disabled = not _last_waypoints
        b_clear = btn(screen, "Clear cached path",
                      panel.centerx, row_y + 16, 320, 32,
                      (140, 90, 50), mpos, font_size=13,
                      disabled=clear_disabled)
        if click_pos and b_clear.collidepoint(click_pos):
            if clear_disabled:
                info_msg = "Nothing to clear."
                info_color = C_GRAY
            else:
                clear_last_solve()
                info_msg = "Cleared."
                info_color = C_GRAY
                return_value = None

        # ---- Status line / Back ------------------------------------------
        if info_msg:
            txt(screen, info_msg, panel.centerx, panel.bottom - 60, 13,
                info_color, True)

        b_back = btn(screen, "BACK", panel.centerx,
                     panel.bottom - 28, 200, 34, C_DANGER, mpos, font_size=14)
        if click_pos and b_back.collidepoint(click_pos):
            return return_value

        txt(screen, "Enter: solve  ·  Esc: back",
            panel.centerx, panel.bottom + 16, 12, C_GRAY, True)
        pygame.display.flip()
        clock.tick(settings.get_fps_cap())
