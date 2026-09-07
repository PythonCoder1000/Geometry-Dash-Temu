"""Bot menu — UI in front of the two bots.

Opened from the editor (L key) and from a play session (B key).  Lets
the user pick which bot to run, watch its progress, view the result,
tweak a couple of search-quality knobs, save / load runs, and (for the
editor) replay the solved inputs against the live player.

The two choices are the whole roster:

  * **Human** — :class:`~.bots.human.HumanBot`. Solves with inputs a
    person could physically produce. Flags the result when it had to
    fall back to frame-perfect timing.
  * **Loophole** — :class:`~.bots.loophole.LoopholeBot`. Needs a drawn
    path; hugs it but takes any shortcut that still wins, and reports
    how far it strayed.

Returns either ``None`` (cancelled, no path produced) or ``(waypoints,
status)`` where ``status`` is one of ``"ok"`` / ``"partial"`` / ``"failed"``
and ``waypoints`` is a list of ``(x, y)`` world-pixel coordinates that
visualise the route. The caller (play / editor) uses the path as a hint
overlay and ``status`` to colour the badge.

``([], "cleared")`` is the one other shape: the user pressed "Clear
result", so the caller must drop its own overlay / replay inputs too.
The cached result is otherwise sticky — :func:`_record_result` refuses
anything worse than what it holds, which without a clear action leaves a
spuriously "solved" run permanently on screen and seeding every re-solve.

The earlier Parallel / Workers / Attempts knobs were removed when the
solver moved to single-threaded — they were UI for a feature that caused
the CPU-peg / unresponsive-ESC bug. The replacement knob is a ``Time
budget`` cap that bounds the whole pipeline's wall-clock so a hard level
can't run forever in the background.
"""

import sys
import time
import traceback

import pygame

from .constants import (
    WIDTH, HEIGHT,
    C_DARK, C_WHITE, C_GRAY, C_BLOCK_H, C_BTN, C_DANGER, C_SUCCESS,
)
from .graphics import (
    draw_bg, txt, btn, make_stars, make_mountains, lighter, darker,
)
from .input_guard import ClickGuard
from . import bot_saves
from . import settings


# ---------------------------------------------------------------------------
# Persistent (within-session) bot tuning knobs
# ---------------------------------------------------------------------------
# A* frontier cap — bounds the open-set size. Default 384 matches
# AutoBot.FRONTIER_CAP. Higher = wider search (more likely to crack
# tight corridors) at linear time + memory cost.
_bot_frontier_caps = [64, 128, 256, 384, 512, 1024, 2048]
_bot_frontier_idx = 3
_bot_max_frames_opts = [5000, 10000, 20000, 40000]
_bot_max_frames_idx = 1
# Reverse-DFS depth — when A* gets stuck, the brute-force fallback
# walks back through the partial trail this many actions, trying
# alternatives at each step. 0 disables the brute-force fallback.
_bot_backtrack_depths = [0, 20, 40, 80, 160, 320]
_bot_backtrack_idx = 4         # default = 160 (matches AutoBot.BACKTRACK_DEPTH)
# Wall-clock cap for the whole pipeline. Replaces the old Attempts /
# Parallel knobs — the search is single-threaded now, so the only
# thing the user can usefully bound is total wall-clock.
_bot_time_budget_opts = [10, 20, 30, 60, 120, 300]
_bot_time_budget_idx = 3       # default = 60 s
# Fix-only: when True, Find Path only verifies the current seed and,
# if it doesn't still win, runs ONE short A* repair to patch the break.
_bot_fix_only = False

# Which bot runs. Exactly two exist; there is no third code path.
BOT_HUMAN = "human"
BOT_LOOPHOLE = "loophole"
_BOT_KINDS = (BOT_HUMAN, BOT_LOOPHOLE)
_BOT_LABELS = {BOT_HUMAN: "Human", BOT_LOOPHOLE: "Loophole"}
_BOT_BLURBS = {
    BOT_HUMAN: "Plays like a person could — one button, human timing",
    BOT_LOOPHOLE: "Hugs your drawn path, takes shortcuts that still win",
}
_bot_kind_idx = 0

# Last solve result. Replaced only by a STRICTLY better one — see
# _record_result. Overwriting unconditionally is what used to let a
# re-run lose a section the bot had already cleared.
_last_waypoints = None
_last_mirror_waypoints = None
_last_inputs = None
_last_status = ""
_last_note = ""


def _deepest_x(waypoints):
    return max((p[0] for p in waypoints), default=-1.0)


def _record_result(waypoints, mirror_waypoints, inputs, status, note=""):
    """Adopt a new solve only if it beats the cached one.

    A solve is better when it wins and the cached one did not, or when
    it reaches farther at the same win status. Without this floor,
    pressing Find Path a second time could replace a solved run with a
    shallower partial — the "bot fails a section it already cleared"
    report, which was a UI bookkeeping bug rather than a search bug.
    """
    global _last_waypoints, _last_mirror_waypoints, _last_inputs
    global _last_status, _last_note
    if not waypoints:
        return False
    was_ok = _last_status == "ok"
    now_ok = status == "ok"
    if was_ok and not now_ok:
        return False
    if was_ok == now_ok and _last_waypoints is not None:
        if _deepest_x(waypoints) <= _deepest_x(_last_waypoints):
            return False
    _last_waypoints = list(waypoints)
    _last_mirror_waypoints = list(mirror_waypoints)
    _last_inputs = list(inputs)
    _last_status = status
    _last_note = note
    return True


def get_last_inputs():
    """Editor uses this to drive the K-style replay against a live player."""
    return list(_last_inputs) if _last_inputs else []


def get_last_mirror_waypoints():
    """Editor / play overlay reads this to draw the dual mirror's path."""
    return list(_last_mirror_waypoints) if _last_mirror_waypoints else []


def clear_last_solve():
    """Discard the cached solution. Call after edits invalidate the path."""
    global _last_waypoints, _last_mirror_waypoints, _last_inputs
    global _last_status, _last_note
    _last_waypoints = None
    _last_mirror_waypoints = None
    _last_inputs = None
    _last_status = ""
    _last_note = ""


def _strip_internal(objects):
    """Drop the live-player bookkeeping fields so the solver sees clean
    object dicts."""
    out = []
    for o in objects:
        co = {k: v for k, v in o.items()
              if not (isinstance(k, str) and k.startswith("_"))}
        out.append(co)
    return out


def _run_solver(screen, clock, objects, params=None, kind=None,
                drawn_path=None):
    """Run the selected bot with the current knobs.

    Returns ``(waypoints, mirror_waypoints, inputs, status, error)``.
    ``error`` is "" on success/partial and non-empty on hard failure, so
    a crash surfaces to the user instead of collapsing into a bare
    "failed".
    """
    global _last_note
    kind = kind or _BOT_KINDS[_bot_kind_idx]
    try:
        clean = _strip_internal(objects)
        max_frames = _bot_max_frames_opts[_bot_max_frames_idx]
        seed = list(_last_inputs) if _last_inputs else None
        time_budget = _bot_time_budget_opts[_bot_time_budget_idx]
        if _bot_fix_only and not seed:
            return None, [], [], "failed", (
                "fix-only needs a saved run to repair — "
                "solve once or load a saved run first")

        if kind == BOT_LOOPHOLE:
            if not drawn_path:
                return None, [], [], "failed", (
                    "the loophole bot needs a drawn path — "
                    "draw one with the Bot Path tool first")
            from .bots import LoopholeBot
            bot = LoopholeBot(
                clean, list(drawn_path), params=params,
                frontier_cap=_bot_frontier_caps[_bot_frontier_idx],
                backtrack_depth=_bot_backtrack_depths[_bot_backtrack_idx])
            wp, mwp, inputs, won = bot.solve(
                screen, clock, max_frames=max_frames, seed_inputs=seed,
                time_budget=time_budget)
            note = ""
            if won and bot.deviated:
                note = (f"loophole found — strayed up to "
                        f"{int(bot.max_deviation_px)} px off your path")
            elif won:
                note = "stayed on your drawn path"
            if bot.used_frame_perfect:
                note = "frame-perfect fallback — not humanly playable"
        else:
            from .bots import HumanBot
            bot = HumanBot(clean, params=params)
            bot.FRONTIER_CAP = _bot_frontier_caps[_bot_frontier_idx]
            bot.BACKTRACK_DEPTH = _bot_backtrack_depths[_bot_backtrack_idx]
            wp, mwp, inputs, won = bot.solve(
                screen, clock, max_frames=max_frames, seed_inputs=seed,
                fix_only=_bot_fix_only, time_budget=time_budget)
            note = ("frame-perfect fallback — not humanly playable"
                    if bot.used_frame_perfect else
                    "played within human timing" if won else "")

        if not wp:
            return None, [], [], "failed", (
                "no path found (level may be unsolvable)")
        _last_note = note
        return (list(wp), list(mwp), list(inputs),
                ("ok" if won else "partial"), "")
    except Exception as exc:
        traceback.print_exc()
        return None, [], [], "failed", f"crash: {type(exc).__name__}: {exc}"


def _pick_saved_run(screen, clock, level_key):
    """Modal picker listing saved bot runs for this level."""
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
                f"{entry['status'] or '—'}"
                + (f"  ·  {entry['bot']}" if entry.get("bot") else ""),
                row_rect.x + 14, row_rect.y + 30, 12, status_col)
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
                    click_pos = None
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


def _stepper(screen, label, value_label, x_label, x_val_center, y, w, h,
             color, mpos, click_pos, on_left, on_right, font_size=15):
    """Draw a label + a centered <value> stepper button. Splits clicks
    into left-half / right-half so the user can advance the cycle in
    either direction. Returns whether the click landed on the button."""
    txt(screen, label, x_label, y, 16, C_WHITE)
    rect = btn(screen, f"< {value_label} >", x_val_center, y + 12, w, h,
               color, mpos, font_size=font_size)
    if click_pos and rect.collidepoint(click_pos):
        if click_pos[0] < rect.centerx:
            on_left()
        else:
            on_right()
        return True
    return False


def run_bot_menu(screen, clock, objects, precomputed_path=None,
                 allow_replay=False, replay_callback=None,
                 level_filename=None, meta=None, drawn_path=None):
    """Show the bot menu.

    Parameters
    ----------
    screen, clock : pygame Surface and Clock
    objects : list of object dicts — the level the bot will solve.
    precomputed_path : optional list of (x, y) tuples
        If the caller already has a path, passing it in shows the "Use
        as Hint Overlay" choice immediately without forcing a re-solve.
    allow_replay : bool
        If True (editor), shows a "Replay" button that calls
        ``replay_callback`` after closing the menu.
    replay_callback : callable or None
    level_filename : str or None
        Identifies the level for Save / Load-run.
    meta : level meta dict (for PhysicsParams override)
    drawn_path : optional list of (x, y) tuples
        The route the loophole bot should hug. Defaults to
        ``precomputed_path`` — whatever line is currently on screen.
    """
    # The stepper closures below declare their own globals; only the
    # toggle and the result cache are written directly here.
    global _bot_fix_only
    global _last_waypoints, _last_mirror_waypoints, _last_inputs
    global _last_status, _last_note

    target_path = drawn_path if drawn_path is not None else precomputed_path
    if precomputed_path is not None and not _last_waypoints:
        _last_waypoints = list(precomputed_path)
        _last_status = "ok"

    from .physics import PhysicsParams
    params = PhysicsParams.from_meta(meta)

    level_key = (bot_saves.level_key_from_filename(level_filename)
                 or bot_saves.level_key_from_objects(_strip_internal(objects)))

    stars = make_stars()
    mountains = make_mountains()
    guard = ClickGuard()

    panel_w = 560
    # Five knob rows + summary + actions all fit in 600px.
    panel_h = min(640, HEIGHT - 20)
    panel = pygame.Rect((WIDTH - panel_w) // 2,
                        (HEIGHT - panel_h) // 2,
                        panel_w, panel_h)

    return_value = None
    info_msg = ""
    info_color = C_GRAY

    def _solve_and_record():
        """Run the selected bot and fold the result into the cache.

        Shared by the ENTER key and the Find Path button — the two used
        to carry duplicate copies of this block, which is how they drifted
        apart on error handling.
        """
        wp, mwp, inputs, status, err = _run_solver(
            screen, clock, objects, params=params,
            drawn_path=target_path)
        if not wp:
            return None, (f"Solver failed — {err}" if err
                          else "Solver failed."), C_DANGER
        adopted = _record_result(wp, mwp, inputs, status, _last_note)
        if not adopted:
            return ((list(_last_waypoints), _last_status),
                    "Kept the earlier, deeper run (this one got less far).",
                    (250, 200, 80))
        msg = {
            "ok": "Solved! Path drawn as hint overlay.",
            "partial": "Partial path found — bot got stuck.",
        }.get(status, "Solver failed.")
        if _last_note:
            msg = f"{msg}  ({_last_note})"
        color = (C_SUCCESS if status == "ok"
                 else (250, 200, 80) if status == "partial" else C_DANGER)
        return (list(_last_waypoints), _last_status), msg, color

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
                    result, info_msg, info_color = _solve_and_record()
                    if result is not None:
                        return_value = result
                    guard.reset()
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if not guard.consume_click(ev):
                    continue
                click_pos = ev.pos

        # ---- background ----------------------------------------------------
        draw_bg(screen, 0, stars, mountains)
        ov = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 180))
        screen.blit(ov, (0, 0))
        pygame.draw.rect(screen, darker(C_DARK, 10), panel.move(0, 6),
                         border_radius=14)
        pygame.draw.rect(screen, C_DARK, panel, border_radius=14)
        pygame.draw.rect(screen, C_BLOCK_H, panel, 2, border_radius=14)

        kind = _BOT_KINDS[_bot_kind_idx]
        txt(screen, "BOT", panel.centerx, panel.y + 22, 30, C_WHITE,
            True, shadow=True)
        txt(screen, _BOT_BLURBS[kind], panel.centerx, panel.y + 56, 13,
            C_GRAY, True)

        col_x = panel.x + 32
        val_x = panel.x + panel.w - 220
        row_y = panel.y + 86
        _STEP = 40

        def _cycle(arr, idx_setter, idx_getter, delta):
            new_idx = (idx_getter() + delta) % len(arr)
            idx_setter(new_idx)

        # ---- Which bot ----------------------------------------------------
        def _set_kind(i):
            global _bot_kind_idx
            _bot_kind_idx = i % len(_BOT_KINDS)

        _stepper(screen, "Bot", _BOT_LABELS[kind],
                 col_x, val_x + 80, row_y, 200, 30,
                 (110, 80, 160), mpos, click_pos,
                 lambda: _set_kind(_bot_kind_idx - 1),
                 lambda: _set_kind(_bot_kind_idx + 1))
        row_y += _STEP

        # ---- Frontier cap -------------------------------------------------
        def _set_fc(i):
            global _bot_frontier_idx
            _bot_frontier_idx = i

        _stepper(screen, "Frontier cap", f"{_bot_frontier_caps[_bot_frontier_idx]}",
                 col_x, val_x + 80, row_y, 200, 30,
                 (60, 90, 160), mpos, click_pos,
                 lambda: _set_fc((_bot_frontier_idx - 1) % len(_bot_frontier_caps)),
                 lambda: _set_fc((_bot_frontier_idx + 1) % len(_bot_frontier_caps)))
        row_y += _STEP

        # ---- Max frames ---------------------------------------------------
        def _set_mf(i):
            global _bot_max_frames_idx
            _bot_max_frames_idx = i

        _stepper(screen, "Max frames",
                 f"{_bot_max_frames_opts[_bot_max_frames_idx]:,}",
                 col_x, val_x + 80, row_y, 200, 30,
                 (60, 90, 160), mpos, click_pos,
                 lambda: _set_mf((_bot_max_frames_idx - 1) % len(_bot_max_frames_opts)),
                 lambda: _set_mf((_bot_max_frames_idx + 1) % len(_bot_max_frames_opts)))
        row_y += _STEP

        # ---- Time budget --------------------------------------------------
        def _set_tb(i):
            global _bot_time_budget_idx
            _bot_time_budget_idx = i

        tb_val = _bot_time_budget_opts[_bot_time_budget_idx]
        tb_label = f"{tb_val}s"
        _stepper(screen, "Time budget", tb_label,
                 col_x, val_x + 80, row_y, 200, 30,
                 (60, 130, 90), mpos, click_pos,
                 lambda: _set_tb((_bot_time_budget_idx - 1) % len(_bot_time_budget_opts)),
                 lambda: _set_tb((_bot_time_budget_idx + 1) % len(_bot_time_budget_opts)))
        row_y += _STEP

        # ---- Backtrack depth ---------------------------------------------
        def _set_bt(i):
            global _bot_backtrack_idx
            _bot_backtrack_idx = i

        bt_val = _bot_backtrack_depths[_bot_backtrack_idx]
        bt_label = "OFF" if bt_val == 0 else f"{bt_val}"
        bt_col = (140, 90, 60) if bt_val > 0 else (70, 70, 80)
        _stepper(screen, "Backtrack depth", bt_label,
                 col_x, val_x + 80, row_y, 200, 30,
                 bt_col, mpos, click_pos,
                 lambda: _set_bt((_bot_backtrack_idx - 1) % len(_bot_backtrack_depths)),
                 lambda: _set_bt((_bot_backtrack_idx + 1) % len(_bot_backtrack_depths)))
        row_y += _STEP

        # ---- Fix-only toggle ---------------------------------------------
        fo_label = "ON" if _bot_fix_only else "OFF"
        fo_col = (130, 90, 60) if _bot_fix_only else (70, 70, 80)
        txt(screen, "Fix only", col_x, row_y, 16, C_WHITE)
        b_fo = btn(screen, fo_label, val_x + 80, row_y + 12, 200, 30,
                   fo_col, mpos, font_size=15)
        if click_pos and b_fo.collidepoint(click_pos):
            _bot_fix_only = not _bot_fix_only
        row_y += _STEP

        # ---- Last solve summary ------------------------------------------
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
        # The waypoint/frame counts already occupy row_y + 20, so the
        # advisory line goes one row lower instead of printing on top.
        if kind == BOT_LOOPHOLE and not target_path:
            txt(screen, "Loophole bot needs a drawn path (Bot Path tool).",
                col_x, row_y + 34, 12, (250, 200, 80))
        elif _last_note:
            txt(screen, _last_note, col_x, row_y + 34, 12, C_GRAY)
        row_y += 48

        # ---- Action buttons ----------------------------------------------
        b_solve = btn(screen, f"Run {_BOT_LABELS[kind]} bot",
                      panel.centerx, row_y + 14, 320, 40, C_BTN, mpos)
        if click_pos and b_solve.collidepoint(click_pos):
            result, info_msg, info_color = _solve_and_record()
            if result is not None:
                return_value = result
            guard.reset()
        row_y += 46

        view_disabled = not _last_waypoints
        b_view = btn(screen, "Use as Hint Overlay",
                     panel.centerx, row_y + 14, 320, 34,
                     (70, 140, 80), mpos, font_size=15,
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
                    info_msg = "Run Find Path first to get replayable inputs."
                    info_color = (250, 200, 80)
                elif replay_callback is not None:
                    try:
                        replay_callback(list(_last_inputs))
                    except Exception as exc:
                        info_msg = (
                            f"Replay crashed: {type(exc).__name__}")
                        info_color = C_DANGER
                    else:
                        return return_value
            row_y += 40

        # ---- Save / Load saved runs --------------------------------------
        save_disabled = not _last_inputs
        b_save = btn(screen, "Save run...",
                     panel.centerx - 110, row_y + 14, 104, 34,
                     (80, 150, 110), mpos, font_size=14,
                     disabled=save_disabled)
        b_load = btn(screen, "Load run...",
                     panel.centerx, row_y + 14, 104, 34,
                     (80, 110, 160), mpos, font_size=14)
        # Clear sits with Save / Load because all three act on the cached
        # result rather than on the search.
        clear_disabled = not (_last_waypoints or _last_inputs or _last_status)
        b_clear = btn(screen, "Clear result",
                      panel.centerx + 110, row_y + 14, 104, 34,
                      (150, 80, 80), mpos, font_size=14,
                      disabled=clear_disabled)
        if click_pos and b_save.collidepoint(click_pos):
            if save_disabled:
                info_msg = "Solve first — nothing to save."
                info_color = (250, 200, 80)
            else:
                from .menus import text_input_dialog
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
                        beam_width=_bot_frontier_caps[_bot_frontier_idx],
                        attempts=1,
                        bot=_BOT_LABELS[kind], note=_last_note)
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
                # The level may have been edited since this run was saved
                # (same level_key, different objects) — a stale "ok" run
                # replayed against the current level could die partway or
                # not at all, so re-verify before trusting the saved
                # status instead of taking it on faith.
                from .bots import HumanBot
                inputs = list(picked["inputs"])
                verifier = HumanBot(_strip_internal(objects), params=params)
                wp, mwp, won, last_alive = verifier.verify(inputs)
                still_ok = won and (picked.get("status") or "ok") == "ok"
                _last_inputs = inputs
                _last_waypoints = list(wp) if wp else list(picked["waypoints"])
                _last_mirror_waypoints = (list(mwp) if wp
                                          else list(picked["mirror_waypoints"]))
                if still_ok:
                    _last_status = "ok"
                    _last_note = picked.get("note") or ""
                    info_msg = (f"Loaded \"{picked['name']}\" "
                                f"({len(_last_inputs)} frames).")
                    info_color = C_SUCCESS
                else:
                    _last_status = "partial" if wp else "failed"
                    _last_note = "level changed since this run was saved"
                    info_msg = (f"\"{picked['name']}\" no longer wins on "
                                f"this level — loaded as {_last_status}.")
                    info_color = (250, 200, 80)
                return_value = (list(_last_waypoints), _last_status)

        # ---- Clear cached result -----------------------------------------
        # The only escape from the monotone gate in _record_result: without
        # it a bad run that once reported "ok" can never be replaced, and
        # the user cannot see where a fresh attempt actually dies.
        if click_pos and b_clear.collidepoint(click_pos):
            if clear_disabled:
                info_msg = "Nothing cached to clear."
                info_color = C_GRAY
            else:
                clear_last_solve()
                return_value = ([], "cleared")
                info_msg = ("Cleared — the next solve starts fresh "
                            "and its result is shown as-is.")
                info_color = C_SUCCESS

        # ---- Status line / Back ------------------------------------------
        if info_msg:
            txt(screen, info_msg, panel.centerx, panel.bottom - 55, 13,
                info_color, True)

        b_back = btn(screen, "BACK", panel.centerx,
                     panel.bottom - 26, 200, 32, C_DANGER, mpos, font_size=14)
        if click_pos and b_back.collidepoint(click_pos):
            return return_value

        pygame.display.flip()
        clock.tick(settings.get_fps_cap())
