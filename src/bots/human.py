"""Human-realism bot — solves a level the way a person could play it.

The search is the phased solver that used to live in ``autobot.py``
(canned chains → greedy warm start → weighted A* → backtracking →
toggle search), with three behavioural changes:

**One button.**  Every phase emits a stream of held booleans and derives
the press edge from it (see :mod:`.action_space`).  The old three-way
``(F,F) / (T,T) / (T,F)`` action space let the search re-press without
releasing, which is how it "chose" between overlapping orbs — orbs fire
on the press edge, so a freely-placed edge inside a continuous hold is
an orb picker.  It also meant nothing stopped a solver from steering the
two dual bodies apart.  With one boolean per frame both are
unrepresentable, and orb priority is resolved only by the engine.

**Backtracking that actually abandons a branch.**  Progress is committed
to a :class:`CheckpointLadder`.  When a search stalls, the next attempt
restarts from a progressively *earlier* committed checkpoint instead of
pushing forward from the deepest one, so a locally-best-but-dead branch
can be abandoned.

**A monotone floor.**  :class:`BestSolution` never accepts a replacement
that reaches less far, so a later phase (or a later run) cannot lose a
section the bot already cleared.

Levels that genuinely have no human-reachable solution fall back to an
explicitly-labelled frame-perfect pass; ``used_frame_perfect`` records
whether that happened so the UI never presents it as a human run.
"""

import os as _os
import time

_os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "hide")

from ..constants import (
    UNITS_PER_BLOCK, HEIGHT_UNITS, PLAYER_SIZE_UNITS, PX_PER_UNIT,
    px_to_units,
    MODE_CUBE, MODE_BALL, MODE_SPIDER,
    HAZARD_TYPES, ORB_TYPES,
    T_END, T_SPEED_NORMAL, SPEED_VALUES_UT as SPEED_VALUES,
    T_COIN, T_JUMP_PREDICTOR, T_BOT_CHECKPOINT,
)
from ..player import Player
from .. import sfx
from .action_space import (
    HUMAN, FRAME_PERFECT, DWELL_CAP, replay_state,
)
from .brute_force import BruteForceSearch
from .progress import SolveProgress, win_x_for_objects
from .sim import SimPlayer, snapshot, restore, player_dedup_key, dedup_key
from .toggle_search import ToggleSearch


class BestSolution:
    """Deepest result seen so far, with a floor it will not fall below.

    ``offer`` accepts a replacement only when it is a win the current
    best is not, or when it reaches strictly farther at the same win
    status.  This is what stops the bot regressing on a section it had
    already cleared: every phase, every restart, and every re-run funnel
    their output through here.
    """

    __slots__ = ("waypoints", "mirror_waypoints", "inputs", "deepest_x", "won")

    def __init__(self):
        self.waypoints = []
        self.mirror_waypoints = []
        self.inputs = []
        self.deepest_x = -1.0
        self.won = False

    def offer(self, waypoints, mirror_waypoints, inputs, won=False):
        if not waypoints and not inputs:
            return False
        # Where this candidate's path actually ends, not any transient peak
        # along the way — a bounce/collision nudge can push x briefly past
        # where the returned inputs finish, which would otherwise report
        # more progress than the committed path really reaches.
        x = waypoints[-1][0] if waypoints else -1.0
        if self.won and not won:
            return False
        if won == self.won and x <= self.deepest_x:
            return False
        self.deepest_x = x
        self.waypoints = list(waypoints)
        self.mirror_waypoints = list(mirror_waypoints)
        self.inputs = list(inputs)
        self.won = bool(won)
        return True

    def result(self):
        return (self.waypoints, self.mirror_waypoints, self.inputs, self.won)


class CheckpointLadder:
    """Committed input prefixes at increasing x, plus a walk-back cursor.

    The old pipeline only ever handed the *deepest* partial forward, so
    once a phase committed to a prefix that could not be completed there
    was no mechanism to give it up — the classic local minimum.  The
    ladder keeps every checkpoint the run passed through and, on a
    stall, hands back an earlier one (walking back 1, 2, 4, 8 … rungs)
    so the search can rebuild that section differently.
    """

    # Cells of forward progress between committed rungs.  Too fine and
    # the ladder is thousands of near-identical prefixes; too coarse and
    # a walk-back throws away more work than the stall cost.
    STRIDE_PX = UNITS_PER_BLOCK * 4

    def __init__(self):
        self.rungs = [(0.0, [])]
        self._back = 0
        self._step = 1

    def record(self, x, inputs):
        if x <= self.rungs[-1][0] + self.STRIDE_PX:
            return
        self.rungs.append((float(x), list(inputs)))

    def record_chain(self, inputs, xs_by_frame):
        """Record a rung wherever ``xs_by_frame`` crosses the stride."""
        for i, x in enumerate(xs_by_frame):
            self.record(x, inputs[: i + 1])

    def on_progress(self):
        """Reset the walk-back — the deepest rung is worth pushing on."""
        self._back = 0
        self._step = 1

    def on_stall(self):
        """Give up on the current rung and step further back."""
        self._back += self._step
        self._step *= 2

    def rung_index(self):
        return max(0, len(self.rungs) - 1 - self._back)

    def exhausted(self):
        return self._back >= len(self.rungs)

    def prefix(self):
        idx = max(0, len(self.rungs) - 1 - self._back)
        return list(self.rungs[idx][1])


class HumanBot:
    """Phased solver constrained to inputs a person could produce.

    Public knobs (set as instance attributes by the bot menu):

      ``FRONTIER_CAP``     — A* open-set bound.
      ``BACKTRACK_DEPTH``  — how far the reverse walk-back may reach, in
                             input frames. 0 disables it.
      ``HEURISTIC_WEIGHT`` — weighted-A* h multiplier.
      ``CLICK_PENALTY``    — cost per press; biases toward calm play.
      ``COIN_BONUS`` / ``CHECKPOINT_BONUS`` — route rewards.
      ``ALLOW_FRAME_PERFECT`` — enable the superhuman escape hatch.
    """

    FRONTIER_CAP = 384
    BACKTRACK_DEPTH = 160
    HEURISTIC_WEIGHT = 4.0

    CLICK_PENALTY = 0.5
    HOLD_PENALTY = 0.1

    CLEARANCE_RADIUS = 2
    CLEARANCE_PENALTY = 2.0

    COIN_BONUS = 200.0
    CHECKPOINT_BONUS = 600.0

    SEED_SAFETY_MARGIN = 60
    BRUTE_FRAMES = 320
    BRUTE_FRONTIER = 1200

    # Fraction of the wall-clock budget the humanlike pass gets before
    # the frame-perfect escape hatch may start.
    HUMAN_BUDGET_FRACTION = 0.7

    ALLOW_FRAME_PERFECT = True

    # When True, Phase 3/4 (A* + checkpoint backtracking + toggle
    # search) is replaced by a single BruteForceSearch run — see
    # brute_force.py. That engine handles its own dead-branch pruning
    # and dedup, so no ladder phase runs alongside it.
    USE_BRUTE_FORCE = False
    # Dedup granularity passed straight through to BruteForceSearch —
    # see that module's docstring for the completeness/speed tradeoff.
    BRUTE_FORCE_POS_BUCKET = px_to_units(1.0)
    BRUTE_FORCE_VEL_BUCKET = px_to_units(0.5)
    # Opt-in multi-process macro-scan for BruteForceSearch — see that
    # module's "Parallel search" block for the design and the earlier
    # CPU-peg / unresponsive-ESC bug it's built to avoid. Off by
    # default: it changes nothing about search correctness (never part
    # of the completeness guarantee), only wall-clock speed, and a
    # toggle exists specifically so it can be turned back off if it
    # ever misbehaves on someone's machine.
    USE_PARALLEL_SEARCH = False

    def __init__(self, objects, params=None):
        self.objects = objects
        self.params = params
        self.model = HUMAN
        self.used_frame_perfect = False
        self.progress = None
        # Optional ``callable(player) -> float`` added to A*'s progress
        # term. The loophole bot injects path adherence here; left None
        # the search optimises purely for reaching the end wall.
        self.route_bias = None
        # Shown on the progress screen so the user can tell which bot is
        # running without leaving it.
        self.progress_title = "HUMAN BOT SEARCH"
        self._deadline = None

        end_xs = [o["x"] * UNITS_PER_BLOCK for o in objects if o["t"] == T_END]
        self.end_x = max(end_xs) if end_xs else 0
        self.has_end = bool(end_xs)
        self.win_x = win_x_for_objects(objects)

        # The physics has no bottomless-pit death, so a branch that
        # falls past every last piece of placed geometry just keeps
        # falling forever, alive, with x still climbing from forward
        # move speed. Nothing in its future can ever touch level
        # geometry again, but nothing here knows that from ``alive``
        # alone — it looks like the best partial result any phase has
        # found (its x only ever grows) and, once ``commit`` accepts
        # it, it becomes an unbeatable floor: a later phase (brute
        # force in particular) that seeds from ``best.inputs`` inherits
        # a start point already deep in the void, where every branch
        # dies immediately. Trimming to just before the void in
        # ``replay_for_waypoints`` — the one real-Player re-verification
        # every non-win candidate already funnels through — keeps this
        # from ever being treated as real, recoverable progress.
        max_y = max((o["y"] for o in objects), default=0)
        # Generous on purpose — see brute_force.py's matching comment.
        # A real drop can run several screen heights before it's done;
        # too tight a margin kills a still-recoverable fall before it
        # ever reaches what it was falling toward.
        self._void_y = max_y * UNITS_PER_BLOCK + HEIGHT_UNITS * 4

        self._orb_cells = set()
        for o in objects:
            if o["t"] in ORB_TYPES:
                self._orb_cells.add((o["x"], o["y"]))
        self._orb_xs = set(c[0] for c in self._orb_cells)
        self._coin_xs = set(o["x"] for o in objects if o["t"] == T_COIN)
        self._coin_objs_for_gx = {}
        for o in objects:
            if o.get("t") != T_COIN:
                continue
            cx = o["x"] * UNITS_PER_BLOCK + UNITS_PER_BLOCK // 2
            cy = o["y"] * UNITS_PER_BLOCK + UNITS_PER_BLOCK // 2
            for dgx in range(-6, 1):
                self._coin_objs_for_gx.setdefault(o["x"] + dgx, []).append(
                    (cx, cy))
        self._probe_xs = tuple(int(o["x"]) for o in objects
                               if o.get("t") == T_JUMP_PREDICTOR)

        self._checkpoints = sorted(
            ((int(o["x"]) * UNITS_PER_BLOCK + UNITS_PER_BLOCK // 2,
              int(o["y"]) * UNITS_PER_BLOCK + UNITS_PER_BLOCK // 2)
             for o in objects if o.get("t") == T_BOT_CHECKPOINT),
            key=lambda p: p[0])
        self._checkpoint_xs = [c[0] for c in self._checkpoints]
        self._checkpoint_ys = [c[1] for c in self._checkpoints]

        self._hazard_col = {}
        hazard_cells = []
        for o in objects:
            if o.get("t") in HAZARD_TYPES:
                gx, gy = int(o["x"]), int(o["y"])
                self._hazard_col[gx] = self._hazard_col.get(gx, 0) + 1
                hazard_cells.append((gx, gy))

        self._hazard_clearance = {}
        cr = int(self.CLEARANCE_RADIUS)
        for hx, hy in hazard_cells:
            for dgx in range(-cr, cr + 1):
                for dgy in range(-cr, cr + 1):
                    d = abs(dgx) if abs(dgx) > abs(dgy) else abs(dgy)
                    if d > cr or d == 0:
                        continue
                    key = (hx + dgx, hy + dgy)
                    prev = self._hazard_clearance.get(key)
                    if prev is None or d < prev:
                        self._hazard_clearance[key] = d

        self._build_speed_segments()

    # ------------------------------------------------------------------
    # Cancellation / budget
    # ------------------------------------------------------------------

    @property
    def cancelled(self):
        return bool(self.progress is not None and self.progress.cancelled)

    def pump(self, force=False):
        if self.progress is None:
            return False
        return self.progress.pump(force=force)

    def budget_expired(self):
        return (self._deadline is not None
                and time.monotonic() > self._deadline)

    def _phase_budget(self, fraction):
        if self._deadline is None:
            return None
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            return 0
        return max(0.5, remaining * fraction)

    def _stop(self):
        return self.cancelled or self.budget_expired()

    # ------------------------------------------------------------------
    # Heuristic (admissible lower bound on frames-to-finish)
    # ------------------------------------------------------------------

    def _build_speed_segments(self):
        base_speed = (self.params.base_move_speed if self.params is not None
                      else SPEED_VALUES[T_SPEED_NORMAL])
        events = sorted(
            ((int(o["x"]) * UNITS_PER_BLOCK, SPEED_VALUES[o["t"]])
             for o in self.objects if o.get("t") in SPEED_VALUES),
            key=lambda e: e[0])
        seg_starts = [0]
        seg_speeds = [base_speed]
        for ex, esp in events:
            if ex <= seg_starts[-1]:
                seg_speeds[-1] = esp
                continue
            if abs(esp - seg_speeds[-1]) < 1e-9:
                continue
            seg_starts.append(ex)
            seg_speeds.append(esp)
        seg_ends = seg_starts[1:] + [self.end_x]
        cumul = [0.0] * len(seg_starts)
        running = 0.0
        for i in range(len(seg_starts) - 1, -1, -1):
            cumul[i] = running
            seg_len = max(0, seg_ends[i] - seg_starts[i])
            if seg_speeds[i] > 0:
                running += seg_len / seg_speeds[i]

        n_cells = int(self.end_x // UNITS_PER_BLOCK) + 2 if self.end_x > 0 else 1
        recips = [0.0] * n_cells
        seg_end_px = [self.end_x] * n_cells
        cumul_after = [0.0] * n_cells
        for cell in range(n_cells):
            x_px = cell * UNITS_PER_BLOCK
            i = 0
            for j, ss in enumerate(seg_starts):
                if ss <= x_px:
                    i = j
                else:
                    break
            if seg_speeds[i] > 0:
                recips[cell] = 1.0 / seg_speeds[i]
            seg_end_px[cell] = seg_ends[i]
            cumul_after[cell] = cumul[i]
        self._h_recips = recips
        self._h_seg_end = seg_end_px
        self._h_cumul = cumul_after
        self._h_n_cells = n_cells

    def _h(self, x):
        if self.end_x <= 0 or x >= self.end_x:
            return 0.0
        cell = int(x // UNITS_PER_BLOCK)
        if cell >= self._h_n_cells:
            return 0.0
        if cell < 0:
            cell = 0
        recip = self._h_recips[cell]
        if recip <= 0.0:
            return 0.0
        return max(0, self._h_seg_end[cell] - x) * recip + self._h_cumul[cell]

    def _frontier_cap(self):
        return max(16, int(getattr(self, "FRONTIER_CAP", 384) or 384))

    def _backtrack_depth(self):
        return max(0, int(getattr(self, "BACKTRACK_DEPTH", 80)))

    # ------------------------------------------------------------------
    # Simulation helpers
    # ------------------------------------------------------------------

    def _new_sim(self):
        sim = SimPlayer([dict(o) for o in self.objects], params=self.params)
        sim.trail = []
        return sim

    def verify(self, inputs):
        """Replay ``inputs``. Returns ``(waypoints, mirror_waypoints, won,
        last_alive_frame)``; ``last_alive_frame`` is -1 on a frame-0 death."""
        # Internal sim state (player.x/y/size) is real GD units; this
        # method's public contract (waypoints) is px, matching the
        # editor/render consumers — convert once, right here.
        player = self._new_sim()
        size = player.size
        waypoints = [((player.x + size / 2) * PX_PER_UNIT,
                      (player.y + size / 2) * PX_PER_UNIT)]
        mirror_waypoints = []
        last_alive = -1
        for i, (held, pressed) in enumerate(inputs):
            player.update(held, pressed)
            size = player.size
            if i % 4 == 0 or not player.alive or player.won:
                waypoints.append(((player.x + size / 2) * PX_PER_UNIT,
                                  (player.y + size / 2) * PX_PER_UNIT))
                if player.mirror is not None and player.mirror.get("alive"):
                    msize = player.mirror.get("size", PLAYER_SIZE_UNITS)
                    mirror_waypoints.append(
                        ((player.x + size / 2) * PX_PER_UNIT,
                         (player.mirror["y"] + msize / 2) * PX_PER_UNIT))
            if player.alive:
                last_alive = i
            if not player.alive or player.won:
                break
        return waypoints, mirror_waypoints, player.won, last_alive

    def replay_for_waypoints(self, inputs):
        """Replay against a real ``Player`` — the same class the game runs
        — so a search win is only reported after it survives the exact
        code path a replay will take.

        Returns ``(waypoints, mirror_waypoints, won, stopped_at)``;
        ``stopped_at`` is how many leading ``inputs`` frames actually ran
        before death/win cut the replay short (``len(inputs)`` if
        neither happened) — the caller's chain routinely runs longer
        than that, and trimming to it keeps a committed result from
        carrying dead frames past where it actually ends.
        """
        player = Player([dict(o) for o in self.objects], params=self.params)
        player.trail = []
        size = player.size
        waypoints = [((player.x + size / 2) * PX_PER_UNIT,
                      (player.y + size / 2) * PX_PER_UNIT)]
        mirror_waypoints = []
        stopped_at = len(inputs)
        for i, (held, pressed) in enumerate(inputs):
            player.update(held, pressed)
            size = player.size
            if i % 4 == 0 or not player.alive or player.won:
                waypoints.append(((player.x + size / 2) * PX_PER_UNIT,
                                  (player.y + size / 2) * PX_PER_UNIT))
                if player.mirror is not None and player.mirror.get("alive"):
                    msize = player.mirror.get("size", PLAYER_SIZE_UNITS)
                    mirror_waypoints.append(
                        ((player.x + size / 2) * PX_PER_UNIT,
                         (player.mirror["y"] + msize / 2) * PX_PER_UNIT))
            if not player.alive or player.won:
                stopped_at = i + 1
                break
            if player.y > self._void_y:
                # See __init__'s comment on _void_y: falling this far
                # below every last object in the level is unrecoverable,
                # so it's cut off exactly like a death would be.
                stopped_at = i + 1
                break
        return waypoints, mirror_waypoints, player.won, stopped_at

    def _x_track(self, inputs):
        """Per-frame x for ``inputs`` — feeds the checkpoint ladder."""
        player = self._new_sim()
        xs = []
        for held, pressed in inputs:
            player.update(held, pressed)
            xs.append(player.x)
            if not player.alive or player.won:
                break
        return xs

    def _trim_to_win(self, inputs):
        player = self._new_sim()
        for i, (h, p) in enumerate(inputs):
            player.update(h, p)
            if player.won:
                return list(inputs[: i + 1])
            if not player.alive:
                return list(inputs[: max(1, i)])
        return list(inputs)

    # ------------------------------------------------------------------
    # Public solve
    # ------------------------------------------------------------------

    def solve(self, screen=None, clock=None, max_frames=10000,
              seed_inputs=None, fix_only=False, time_budget=None):
        """Return ``(waypoints, mirror_waypoints, inputs, won)``.

        ``fix_only`` skips the warm starts and runs one short A* repair
        from the seed's last surviving prefix.

        ``time_budget`` (seconds) caps the whole pipeline.  The humanlike
        pass gets ``HUMAN_BUDGET_FRACTION`` of it; only if that fails
        does the frame-perfect escape hatch run with the remainder, and
        ``used_frame_perfect`` records that it did.
        """
        was_enabled = sfx.is_enabled()
        if was_enabled:
            # Transient — don't persist this to prefs (see set_enabled's
            # docstring): a solve does this every run, and a crash between
            # here and the ``finally`` restore below must not leave SFX
            # permanently muted on disk.
            sfx.set_enabled(False, persist=False)
        if not time_budget or time_budget <= 0:
            time_budget = 60.0
        started = time.monotonic()
        self.progress = SolveProgress(screen, clock, self.win_x,
                                      title=self.progress_title,
                                      has_end=self.has_end)
        self.used_frame_perfect = False
        best = BestSolution()
        try:
            self.model = HUMAN
            self._deadline = started + time_budget * self.HUMAN_BUDGET_FRACTION
            self._run_pipeline(best, max_frames, seed_inputs, fix_only)
            if best.won or self.cancelled or not self.ALLOW_FRAME_PERFECT:
                return best.result()

            # Escape hatch.  Reaching here means no chain the human model
            # can express beat the level inside its budget, so the level
            # is (as far as this search can tell) not humanly playable.
            # Relax timing precision only — the one-button rule stays.
            self.model = FRAME_PERFECT
            self._deadline = started + time_budget
            if self.budget_expired():
                return best.result()
            self.progress.paint(
                "No human-timing solution — frame-perfect fallback",
                force=True)
            frame_perfect = BestSolution()
            self._run_pipeline(frame_perfect, max_frames,
                               best.inputs or seed_inputs, fix_only)
            if frame_perfect.won:
                self.used_frame_perfect = True
                return frame_perfect.result()
            best.offer(*frame_perfect.result())
            return best.result()
        finally:
            self._deadline = None
            if was_enabled:
                sfx.set_enabled(True, persist=False)

    def _run_pipeline(self, best, max_frames, seed_inputs, fix_only):
        model = self.model
        ladder = CheckpointLadder()

        def commit(waypoints, mirror_waypoints, inputs, won=False):
            """Funnel every phase result through the monotone floor.

            Callers (canned chains, warm starts, brute force) hand over
            whatever raw input chain they generated, which routinely runs
            longer than the player actually survives — planners don't
            stop early just because the replay would die at frame 199 of
            a 556-frame attempt. ``waypoints`` already gets cut off at
            the real death frame (``replay_for_waypoints``/``verify``
            break their loop there), so trim ``inputs`` to match before
            it can ever reach ``best``. Otherwise a bloated candidate
            that dies at the same x as a cleanly-trimmed one ties on x
            and keeps its dead weight forever, since ``offer`` has no
            way to prefer the shorter of two equal-x results.
            """
            if won:
                self.progress.report_win("SOLVED")
            elif inputs:
                # Re-check against the real Player regardless of which
                # (possibly SimPlayer-based) engine the caller used —
                # this is the one authoritative "what does this chain
                # actually reach" pass every non-win candidate goes
                # through before it can become the committed best.
                waypoints, mirror_waypoints, _, stopped_at = (
                    self.replay_for_waypoints(inputs))
                inputs = list(inputs[:stopped_at])
            improved = best.offer(waypoints, mirror_waypoints, inputs, won)
            if improved and inputs:
                ladder.record_chain(inputs, self._x_track(inputs))
                self.progress.note_x(best.deepest_x)
            return improved

        # ---- Phase 0 — seed verify -----------------------------------
        if seed_inputs:
            seed = model.sanitize(seed_inputs)
            wp, mwp, won, last_alive = self.verify(seed)
            if won:
                commit(wp, mwp, self._trim_to_win(seed), True)
                return
            if wp:
                commit(wp, mwp, seed[: max(0, last_alive)])

        if fix_only:
            if not best.inputs:
                return
            prefix = self._safe_prefix(best.inputs)
            wp, mwp, inp, won = self._astar(
                max_frames, prefix_inputs=prefix,
                status_text="Fix-only: repairing seed")
            commit(wp, mwp, inp, won)
            return

        if self._stop():
            return

        require_pickups = bool(self._coin_xs or self._checkpoints)

        # ---- Phase 1 — canned chains ---------------------------------
        if not seed_inputs:
            for label, bits in self._canned_chains(max_frames):
                if self._stop():
                    break
                self.progress.paint(f"Canned: {label}")
                chain = model.stream(bits)
                wp, mwp, won, _ = self.verify(chain)
                if won:
                    commit(wp, mwp, self._trim_to_win(chain), True)
                    if not require_pickups:
                        return
                elif wp:
                    commit(wp, mwp, chain)

        # ---- Phase 2 — greedy warm start -----------------------------
        if not seed_inputs and not self._stop():
            for label, fn in (
                    ("orb taps", lambda: self._orb_tap_chain(max_frames)),
                    ("greedy-2", lambda: self._greedy_lookahead(max_frames, 2)),
                    ("greedy-3", lambda: self._greedy_lookahead(max_frames, 3)),
            ):
                if self._stop():
                    break
                self.progress.paint(f"Warm start: {label}")
                inp, won = fn()
                if not inp:
                    continue
                wp, mwp, real_won, _ = self.replay_for_waypoints(inp)
                if won and real_won:
                    commit(wp, mwp, inp, True)
                    if not require_pickups:
                        return
                else:
                    commit(wp, mwp, inp)

        # ---- Phase 3/4 — directed search -------------------------------
        if self.USE_BRUTE_FORCE:
            self._brute_force_phase(best, commit, seed_inputs, max_frames)
            return

        # ---- Phase 3 — A* with checkpoint backtracking ---------------
        if best.inputs:
            ladder.record_chain(best.inputs, self._x_track(best.inputs))
        self._search_with_backtracking(best, ladder, max_frames, commit)
        if best.won or self._stop():
            return

        # ---- Phase 4 — toggle search from an earlier checkpoint -------
        if best.inputs:
            self._toggle_phase(best, ladder, commit)

    def _safe_prefix(self, inputs):
        """The part of ``inputs`` that is comfortably before the death."""
        _, _, _, last_alive = self.verify(inputs)
        if last_alive <= self.SEED_SAFETY_MARGIN:
            return []
        return list(inputs[: last_alive - self.SEED_SAFETY_MARGIN])

    # ------------------------------------------------------------------
    # Backtracking driver
    # ------------------------------------------------------------------

    def _search_with_backtracking(self, best, ladder, max_frames, commit):
        """Run A* repeatedly, walking back down the ladder on a stall.

        The loop is what makes "stuck in a local minimum" recoverable:
        an attempt that fails to improve on the floor is not retried
        deeper, it is retried from an earlier committed prefix — and the
        frontier is widened each time so the retry explores differently
        rather than replaying the same expansion order.
        """
        cap = self._frontier_cap()
        attempt = 0
        while not self._stop() and not ladder.exhausted():
            prefix = ladder.prefix()
            budget = self._phase_budget(0.4 if attempt == 0 else 0.5)
            if budget is not None and budget <= 0:
                break
            rung = ladder.rung_index()
            status = ("A* search" if attempt == 0
                      else f"A* restart from checkpoint {rung + 1}"
                           f"/{len(ladder.rungs)}")
            floor = best.deepest_x
            wp, mwp, inp, won = self._astar(
                max_frames, prefix_inputs=prefix, status_text=status,
                frontier_cap=cap, time_budget=budget)
            if won:
                commit(wp, mwp, inp, True)
                return
            improved = commit(wp, mwp, inp)
            attempt += 1
            if improved and best.deepest_x > floor:
                ladder.on_progress()
            else:
                # This rung is a dead end as far as the frontier can
                # see. Abandon it and rebuild the level from earlier.
                ladder.on_stall()
                cap = min(self.BRUTE_FRONTIER, cap * 2)
                if self._backtrack_depth() > 0 and best.inputs:
                    self._reverse_walk(best, max_frames, commit)
                    if best.won:
                        return

    def _reverse_walk(self, best, max_frames, commit):
        """Flip the button at each of the last N decision points.

        Under the one-button model there is exactly one alternative at
        any frame — invert the held state — so this is a linear scan
        rather than the old three-way fan-out.  Branches are ranked by
        the x they reach, never by how long they survive: ranking on
        survival is what let the old reverse-DFS adopt a chain that
        hovered longer but got less far, undoing cleared ground.
        """
        partial = best.inputs
        depth = self._backtrack_depth()
        if depth <= 0 or not partial:
            return
        _, _, won, last_alive = self.verify(partial)
        if won or last_alive <= 0:
            return
        per_branch_total = self._phase_budget(0.25)
        per_branch = (per_branch_total / max(1, depth)
                      if per_branch_total else None)
        for d in range(1, depth + 1):
            if self._stop():
                return
            cut = last_alive - d
            if cut < 0:
                return
            head = list(partial[:cut])
            prev_held, dwell = replay_state(head)
            if dwell < self.model.min_dwell:
                # A flip here would break the dwell rule; skip it rather
                # than emit a chain a human could not reproduce.
                continue
            flipped = not prev_held
            prefix = head + [(flipped, flipped)]
            horizon = max(max_frames, len(prefix) + self.BRUTE_FRAMES)
            wp, mwp, inp, won = self._astar(
                horizon, prefix_inputs=prefix,
                frontier_cap=self.BRUTE_FRONTIER,
                time_budget=per_branch,
                status_text=f"Backtrack {d}/{depth}")
            if won:
                commit(wp, mwp, inp, True)
                return
            commit(wp, mwp, inp)

    def _toggle_phase(self, best, ladder, commit):
        """Randomised toggle search seeded from an earlier checkpoint.

        Deliberately seeded from a rung *behind* the deepest one: the
        deepest prefix is exactly the branch A* could not finish, so
        re-randomising its tail tends to rediscover the same wall.
        """
        budget = self._phase_budget(1.0)
        if not budget or budget <= 0:
            return
        ladder.on_stall()
        seed = ladder.prefix() or self._safe_prefix(best.inputs)
        search = ToggleSearch(self.objects, params=self.params,
                              model=self.model, seed_inputs=seed,
                              time_budget=budget, progress=self.progress)
        try:
            inputs, won = search.run()
        except Exception:
            return
        if not inputs:
            return
        wp, mwp, replay_won, _ = self.replay_for_waypoints(inputs)
        commit(wp, mwp, inputs, won and replay_won)

    def _brute_force_phase(self, best, commit, seed_inputs, max_frames):
        """Exhaustive decision-point search — see ``USE_BRUTE_FORCE`` and
        ``brute_force.py``'s module docstring for the full argument.

        Unlike the old MCTS phase, seeding doesn't fight this engine the
        same way — it's not sampling-based, so a mediocre warm-start
        prefix just gets explored and superseded rather than locking in
        a bad opening. Still prefers the caller's own ``seed_inputs``
        (a real run to repair/continue) over the internal warm start
        when both exist, for the same reason as before: a run someone
        actually asked to continue from should be honored as a seed,
        an internally-generated one shouldn't be treated as a floor.

        Doesn't use ``route_bias`` — this engine has no cost function to
        bias, only "is this frame a real decision" and "have we seen
        this state." A loophole-bot run through here will find *a* win,
        not necessarily one that hugs the drawn path.
        """
        budget = self._phase_budget(1.0)
        if not budget or budget <= 0:
            return
        seed = seed_inputs or best.inputs or None
        if seed:
            seed = self._safe_prefix(seed)
        search = BruteForceSearch(
            self.objects, params=self.params, model=self.model,
            seed_inputs=seed, time_budget=budget, max_frames=max_frames,
            pos_bucket=self.BRUTE_FORCE_POS_BUCKET,
            vel_bucket=self.BRUTE_FORCE_VEL_BUCKET,
            parallel=self.USE_PARALLEL_SEARCH,
            progress=self.progress)
        try:
            inputs, won = search.run()
        except Exception:
            return
        if not inputs:
            return
        wp, mwp, replay_won, _ = self.replay_for_waypoints(inputs)
        commit(wp, mwp, inputs, won and replay_won)
        # The search reports live progress off its own SimPlayer as it
        # explores (see BruteForceSearch.run's note_x calls), which can
        # run ahead of what a real Player replay confirms. Realign the
        # displayed x with the actual committed result now that this
        # phase is done, instead of leaving an optimistic overshoot
        # stuck on screen (note_x alone can't correct it downward).
        if not self.progress.solved:
            self.progress.set_x(best.deepest_x)

    # ------------------------------------------------------------------
    # Canned / greedy warm starts (all one-button by construction)
    # ------------------------------------------------------------------

    def _canned_chains(self, max_frames):
        """Held-bit patterns worth trying before searching properly."""
        dwell = self.model.min_dwell
        out = [("walk", [False] * max_frames),
               ("hold", [True] * max_frames)]
        for period in (dwell, dwell * 2, dwell * 4):
            bits = [(i // period) % 2 == 0 for i in range(max_frames)]
            out.append((f"tap/{period}", bits))
        return out

    def _orb_tap_chain(self, max_frames):
        """Hold whenever an orb is within tap range, release otherwise.

        The engine decides which orb the resulting press edge activates;
        the chain never names one.
        """
        sim = self._new_sim()
        orb_xs = self._orb_xs
        orb_cells = self._orb_cells
        model = self.model
        inputs = []
        prev_held = False
        dwell = DWELL_CAP
        for _ in range(max_frames):
            if not sim.alive or sim.won or self._stop():
                break
            gx = int(sim.x // UNITS_PER_BLOCK)
            gy = int(sim.y // UNITS_PER_BLOCK)
            on_orb = False
            if gx in orb_xs or (gx + 1) in orb_xs or (gx - 1) in orb_xs:
                for dx in range(-1, 3):
                    for dy in range(-2, 3):
                        if (gx + dx, gy + dy) in orb_cells:
                            on_orb = True
                            break
                    if on_orb:
                        break
            held = on_orb if dwell >= model.min_dwell else prev_held
            pressed = model.edge(held, prev_held)
            sim.update(held, pressed)
            inputs.append((held, pressed))
            dwell = 1 if held != prev_held else min(DWELL_CAP, dwell + 1)
            prev_held = held
        return inputs, sim.won

    def _greedy_lookahead(self, max_frames, lookahead=2):
        """Pick, each frame, the legal button state whose short rollout
        gets furthest while staying alive."""
        model = self.model
        live = self._new_sim()
        probe = self._new_sim()
        ckpt_xs = self._checkpoint_xs
        inputs = []
        prev_held = False
        dwell = DWELL_CAP
        for _ in range(max_frames):
            if not live.alive or live.won or self._stop():
                break
            snap = snapshot(live)
            best_score = (-1, -float("inf"))
            best_action = (prev_held, False, min(DWELL_CAP, dwell + 1))
            for held, pressed, next_dwell in model.actions(prev_held, dwell):
                restore(probe, snap)
                probe.update(held, pressed)
                follow_prev = held
                for _ in range(lookahead - 1):
                    if not probe.alive or probe.won:
                        break
                    probe.update(follow_prev, False)
                if probe.won:
                    live.update(held, pressed)
                    inputs.append((held, pressed))
                    return inputs, True
                score_x = probe.x + len(probe.coins_collected) * px_to_units(80.0)
                if self.route_bias is not None:
                    score_x += self.route_bias(probe) * UNITS_PER_BLOCK
                if ckpt_xs:
                    next_ckpt = next((cx for cx in ckpt_xs
                                      if cx >= probe.x - UNITS_PER_BLOCK), None)
                    if next_ckpt is not None:
                        score_x += (self.CHECKPOINT_BONUS * px_to_units(50.0)
                                    / max(1.0, abs(next_ckpt - probe.x)))
                score = (1 if probe.alive else 0, score_x)
                if score > best_score:
                    best_score = score
                    best_action = (held, pressed, next_dwell)
            held, pressed, dwell = best_action
            live.update(held, pressed)
            inputs.append((held, pressed))
            prev_held = held
        return inputs, live.won

    # ------------------------------------------------------------------
    # Weighted A*
    # ------------------------------------------------------------------

    def _astar(self, max_frames, prefix_inputs=None, frontier_cap=None,
               status_text="", time_budget=None):
        """Weighted A* over ``(snapshot, button state)``.

        ``f = HEURISTIC_WEIGHT * h(x) + depth - progress``; ``progress``
        carries the large route signals (coins, checkpoints, orbs) and
        the secondary key carries the soft biases.

        The node state includes ``(prev_held, dwell)`` because under the
        one-button model the legal successors depend on them — that pair
        is as much a part of the search state as the player's velocity.
        """
        import heapq

        model = self.model
        min_dwell = model.min_dwell
        call_deadline = (time.monotonic() + time_budget
                         if time_budget else None)
        cap = max(16, int(frontier_cap if frontier_cap is not None
                          else self._frontier_cap()))

        h_weight = self.HEURISTIC_WEIGHT
        click_pen = self.CLICK_PENALTY
        hold_pen = self.HOLD_PENALTY
        coin_bonus = self.COIN_BONUS
        ckpt_bonus = self.CHECKPOINT_BONUS
        coin_xs = self._coin_xs
        probe_xs = self._probe_xs
        hazard_get = self._hazard_col.get
        hazard_col = self._hazard_col
        hazard_clearance = self._hazard_clearance
        clearance_get = hazard_clearance.get
        clearance_radius = int(self.CLEARANCE_RADIUS)
        clearance_pen = float(self.CLEARANCE_PENALTY)
        h_recips = self._h_recips
        h_seg_end = self._h_seg_end
        h_cumul = self._h_cumul
        h_n_cells = self._h_n_cells
        end_x = self.end_x
        ckpt_xs_list = self._checkpoint_xs
        ckpt_ys_list = self._checkpoint_ys
        n_ckpts = len(ckpt_xs_list)
        route_bias = self.route_bias

        def _h_local(x):
            if end_x <= 0 or x >= end_x:
                return 0.0
            cell = int(x // UNITS_PER_BLOCK)
            if cell >= h_n_cells:
                return 0.0
            if cell < 0:
                cell = 0
            r = h_recips[cell]
            if r <= 0.0:
                return 0.0
            return max(0, h_seg_end[cell] - x) * r + h_cumul[cell]

        _X = 0
        _ON_GROUND = 3
        _MODE = 9
        _DASH_TIMER = 11
        _MIRROR = 4
        _TAP_PRUNABLE = (MODE_CUBE, MODE_BALL, MODE_SPIDER)
        _X_BUCKET = 4

        orb_xs_expanded = set()
        for ox in self._orb_xs:
            for dx in range(-3, 2):
                orb_xs_expanded.add(ox + dx)

        player = self._new_sim()

        nodes = [(-1, False, False)]
        terminal = 0
        if prefix_inputs:
            for held, pressed in prefix_inputs:
                player.update(held, pressed)
                nodes.append((terminal, held, pressed))
                terminal = len(nodes) - 1
                if player.won:
                    inputs = self._reconstruct(nodes, terminal)
                    self.progress.report_win("SOLVED")
                    wp, mwp, ok, _ = self.replay_for_waypoints(inputs)
                    return wp, mwp, inputs, ok
                if not player.alive:
                    return [], [], [], False
        prefix_depth = terminal
        prev_held0, dwell0 = replay_state(prefix_inputs or [])

        def _key(snap_, x_val, prev_held, dwell):
            return (int(x_val) // _X_BUCKET, dedup_key(snap_),
                    prev_held, dwell if dwell < min_dwell else min_dwell)

        init_snap = snapshot(player)
        open_heap = [(h_weight * _h_local(player.x), 0.0, 0, init_snap,
                      prefix_depth, prefix_depth, prev_held0, dwell0)]
        counter = 1
        visited = {_key(init_snap, player.x, prev_held0, dwell0): prefix_depth}
        best_partial_node = prefix_depth
        best_alive_x = player.x

        stagnant_pops = 0
        h_min_seen = float("inf")
        pops_since_h_improved = 0
        STAGNATION_BASE = 32000
        STAGNATION_DUAL = 64000

        death_counts = {}
        _DEATH_PEN_PER_HIT = 0.02
        _DEATH_PEN_MAX = 1.0

        expansions = 0
        max_expansions = max_frames * 12

        while open_heap:
            if expansions >= max_expansions:
                break
            if self.pump() or self.budget_expired():
                break
            if call_deadline is not None and time.monotonic() > call_deadline:
                break
            (f, _neg_pref, _c, snap, node_id, depth,
             prev_held, dwell) = heapq.heappop(open_heap)

            key = _key(snap, snap[0][_X], prev_held, dwell)
            if visited.get(key, depth) < depth:
                continue
            if depth >= max_frames:
                continue

            best_x_before_pop = best_alive_x
            popped_h = _h_local(snap[0][_X])
            if popped_h < h_min_seen:
                h_min_seen = popped_h
                pops_since_h_improved = 0
            else:
                pops_since_h_improved += 1

            vals = snap[0]
            cand_mode = vals[_MODE]
            mirror_active = snap[_MIRROR] is not None
            in_dash = int(vals[_DASH_TIMER]) > 0

            options = model.actions(prev_held, dwell)
            # Starting a hold mid-air in a tap mode, away from any orb,
            # can only burn the input buffer — prune the rising edge but
            # never the release (which still ends a dash or a hold).
            if (not in_dash and not mirror_active
                    and cand_mode in _TAP_PRUNABLE
                    and not vals[_ON_GROUND]
                    and (int(vals[_X] // UNITS_PER_BLOCK)) not in orb_xs_expanded):
                options = [o for o in options if not (o[0] and not prev_held)]

            parent_pcount = len(snap[1])
            parent_coins = len(snap[6]) if len(snap) >= 7 else 0
            new_depth = depth + 1

            for held, pressed, next_dwell in options:
                restore(player, snap)
                player.update(held, pressed)
                expansions += 1

                if player.won:
                    nodes.append((node_id, held, pressed))
                    inputs = self._reconstruct(nodes, len(nodes) - 1)
                    self.progress.report_win("SOLVED")
                    wp, mwp, ok, _ = self.replay_for_waypoints(inputs)
                    return wp, mwp, inputs, ok

                if not player.alive:
                    dgx = int(player.x // UNITS_PER_BLOCK)
                    death_counts[dgx] = death_counts.get(dgx, 0) + 1
                    continue

                child_key = (int(player.x) // _X_BUCKET,
                             player_dedup_key(player), held,
                             next_dwell if next_dwell < min_dwell
                             else min_dwell)
                prev_g = visited.get(child_key)
                if prev_g is not None and prev_g <= new_depth:
                    continue
                visited[child_key] = new_depth
                child_snap = snapshot(player)

                progress = 0.0
                pref = 0.0

                newly_passed = len(player.passed) - parent_pcount
                if newly_passed > 0:
                    progress += newly_passed * 5.0

                newly_coins = len(player.coins_collected) - parent_coins
                if newly_coins > 0:
                    progress += newly_coins * coin_bonus

                gx_now = int(player.x // UNITS_PER_BLOCK)
                pcx_now = float(player.x)

                if pressed and probe_xs:
                    for px in probe_xs:
                        if abs(px - gx_now) <= 2:
                            progress += 0.6
                            break

                if n_ckpts:
                    parent_x = float(snap[0][_X])
                    pcy_now = float(player.y)
                    passed_now = sum(1 for cx in ckpt_xs_list
                                     if cx <= pcx_now)
                    passed_before = sum(1 for cx in ckpt_xs_list
                                        if cx <= parent_x)
                    for i in range(passed_before, passed_now):
                        dyp = abs(ckpt_ys_list[i] - pcy_now)
                        scale = max(0.25, 1.0 - dyp / (UNITS_PER_BLOCK * 1.5))
                        progress += ckpt_bonus * scale
                    if passed_now < n_ckpts:
                        dxa = abs(ckpt_xs_list[passed_now] - pcx_now)
                        dya = abs(ckpt_ys_list[passed_now] - pcy_now)
                        prox = max(0.0, 1.0 - (dxa + dya) / (UNITS_PER_BLOCK * 6.0))
                        progress += ckpt_bonus * prox

                if pressed:
                    progress -= click_pen
                elif held and cand_mode in _TAP_PRUNABLE:
                    progress -= hold_pen

                if coin_xs:
                    near_coin = any((gx_now + d) in coin_xs for d in range(6))
                    if near_coin:
                        py = float(player.y)
                        for cx, cy in self._coin_objs_for_gx.get(gx_now, ()):
                            dxp = cx - pcx_now
                            dyp = cy - py
                            dist = max(1.0, (dxp * dxp + dyp * dyp) ** 0.5)
                            progress += min(coin_bonus * 0.3,
                                            coin_bonus * 20.0 / dist)
                            break
                    else:
                        pref += 0.05

                if route_bias is not None:
                    progress += route_bias(player)

                if player.mirror is not None and player.mirror["alive"]:
                    pref += 0.2

                if death_counts:
                    dpen = (death_counts.get(gx_now, 0)
                            + death_counts.get(gx_now + 1, 0))
                    if dpen:
                        pref -= min(_DEATH_PEN_MAX,
                                    dpen * _DEATH_PEN_PER_HIT)

                if hazard_col:
                    hcount = (hazard_get(gx_now, 0)
                              + hazard_get(gx_now + 1, 0))
                    if hcount:
                        pref -= hcount * 0.005

                if hazard_clearance:
                    gy_now = int(player.y // UNITS_PER_BLOCK)
                    d_here = clearance_get((gx_now, gy_now))
                    d_next = clearance_get((gx_now + 1, gy_now))
                    nearest = None
                    for d in (d_here, d_next):
                        if d is not None and (nearest is None or d < nearest):
                            nearest = d
                    if nearest is not None:
                        scale = max(0.0, 1.0 - (nearest - 1)
                                    / float(clearance_radius))
                        progress -= clearance_pen * scale

                f_new = h_weight * _h_local(player.x) + new_depth - progress
                nodes.append((node_id, held, pressed))
                nid = len(nodes) - 1

                if player.x > best_alive_x:
                    best_alive_x = player.x
                    best_partial_node = nid
                    self.progress.note_x(best_alive_x)

                heapq.heappush(open_heap,
                               (f_new, -pref, counter, child_snap, nid,
                                new_depth, held, next_dwell))
                counter += 1

            if len(open_heap) > cap * 2:
                open_heap = heapq.nsmallest(cap, open_heap)
                heapq.heapify(open_heap)

            if best_alive_x > best_x_before_pop + 0.5:
                stagnant_pops = 0
            else:
                stagnant_pops += 1
            stag_limit = STAGNATION_DUAL if mirror_active else STAGNATION_BASE
            plateau_limit = stag_limit // 4
            if (stagnant_pops > plateau_limit
                    and pops_since_h_improved > plateau_limit):
                break
            if stagnant_pops > stag_limit:
                break

            if self.progress.paint(status_text):
                break

        if best_partial_node > 0:
            inputs = self._reconstruct(nodes, best_partial_node)
        else:
            inputs = list(prefix_inputs) if prefix_inputs else []
        wp, mwp, ok, _ = self.replay_for_waypoints(inputs)
        if ok:
            self.progress.report_win("SOLVED")
        return wp, mwp, inputs, ok

    def _reconstruct(self, nodes, terminal_id):
        out = []
        idx = terminal_id
        while idx > 0:
            parent, held, pressed = nodes[idx]
            out.append((held, pressed))
            idx = parent
        out.reverse()
        return out
