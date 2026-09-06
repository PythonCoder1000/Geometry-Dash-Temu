"""Pathfinder — generation-based randomized search.

This is the bot.md-recommended algorithm: an algorithmic search over the
deterministic physics engine, brute-forcing a sequence of jump frames
that survives the level. Not learned, not adaptive — just exhaustive
sampling guided by a fitness function and a mutation operator. Same
shape as camila314's Pathfinder mod (Geode for Geometry Dash): sample
candidate input sequences, simulate, keep the elite, mutate, commit
the safe prefix of the best survivor.

Public API:

    bot = PathfinderBot(objects, params=None,
                        seed_inputs=None, max_iterations=...)
    waypoints, inputs, won = bot.solve(screen, clock)

Single-threaded by design — an earlier parallel-candidate variant was
removed after it was found to hang under spawn-pool startup contention
on hard levels. The candidate evaluation loop is the hot path; the
amortised speedup never justified the worst-case unresponsiveness it
re-introduced.
"""

import random
import time

import pygame

from .autobot import _SimPlayer, _snap, _restore
from .constants import (
    CELL, WIDTH, HEIGHT, T_END,
    MODE_CUBE, MODE_SHIP, MODE_BALL, MODE_WAVE, MODE_UFO, MODE_SPIDER,
    MODE_SWING, MODE_ROBOT,
)


# Per-mode toggle interval (frames between flips) for the interval
# sampler. Wave wants fast flips for tight corridors; cube wants sparse
# taps because over-clicking just spends input buffer for nothing.
_MODE_INTERVAL = {
    MODE_CUBE:   (8, 60),
    MODE_BALL:   (6, 40),
    MODE_SPIDER: (6, 40),
    MODE_SWING:  (4, 30),
    MODE_ROBOT:  (4, 30),
    MODE_SHIP:   (4, 25),
    MODE_UFO:    (5, 35),
    MODE_WAVE:   (2, 12),
}

# Modes that read input every frame as a hold (ship thrust, wave up).
# In these modes we bias initial-state sampling toward "held" because
# a long flat held arc is the natural primitive — toggle-only sampling
# explores tap chains that would never come up in a real flight path.
_HOLD_MODES = (MODE_SHIP, MODE_WAVE, MODE_ROBOT, MODE_UFO)


class PathfinderBot:
    """Randomized generation-based pathfinder.

    Parameters
    ----------
    objects : list of dict
        Level objects. Deep-copied for the internal sim so the caller's
        list is not perturbed.
    params : PhysicsParams or None
        Per-level physics override. Must match the live ``Player`` to
        avoid replay desync.
    horizon : int
        Forward window (frames) inside which candidate toggles are
        sampled.
    population : int
        Candidates evaluated per generation. Higher = more thorough at
        linear cost.
    elite_keep : int
        Top-K candidates that seed the next generation's mutation pool.
    toggles_per_candidate : int
        Cap on how many toggle frames a single candidate carries.
    commit_fraction : float in (0, 1]
        How much of the best surviving window to commit before
        re-planning. Smaller values re-plan more often (better when the
        physics is highly chaotic) but waste sim work.
    rollback_initial : int
        First rollback step when a generation fails to make progress.
    rollback_growth : int
        Amount ``fail`` grows on each consecutive failure.
    max_iterations : int
        Hard cap on generations. Defends against pathological levels.
    seed : int or None
        RNG seed for determinism. None = nondeterministic.
    seed_inputs : list[(held, pressed)] or None
        Optional input prefix to commit before searching. Lets a caller
        (e.g. AutoBot's pathfinder phase) hand in a partial path that
        already gets to frame K so we pick up from there.
    """

    def __init__(self, objects, params=None, *,
                 horizon=300, population=400, elite_keep=12,
                 toggles_per_candidate=14,
                 commit_fraction=1.0 / 3.0,
                 rollback_initial=5, rollback_growth=5,
                 max_iterations=8000, time_budget=None,
                 seed=None, seed_inputs=None,
                 # Accepted but ignored — kept for API compat with
                 # callers that still pass them.
                 use_parallel=False, n_workers=None):
        self._objects_template = [dict(o) for o in objects]
        self._params = params
        # Horizon, population, elites, toggle cap default tuned for hard
        # corridors — bigger search per generation finds more frame-perfect
        # arcs at the cost of more sim work per step. Caller can dial back
        # via constructor kwargs for fast/cheap solves.
        self.horizon_min = max(60, int(horizon) // 2)
        self.horizon_max = int(horizon)
        self.horizon = int(horizon)
        self.population = int(population)
        self.elite_keep = max(1, int(elite_keep))
        self.toggles_per_candidate = int(toggles_per_candidate)
        self.commit_fraction = float(commit_fraction)
        self.rollback_initial = int(rollback_initial)
        self.rollback_growth = int(rollback_growth)
        self.max_iterations = int(max_iterations)
        # Wall-clock budget in seconds — when set, the search bails as
        # soon as elapsed > time_budget regardless of iteration count.
        # Used by AutoBot's phase-budgeting so a single pathfinder
        # attempt doesn't burn the entire wall-clock budget. None means
        # unbounded (only iteration count matters).
        self.time_budget = float(time_budget) if time_budget else None
        self._initial_seed = seed
        self._rng = random.Random(seed)

        end_xs = [o["x"] * CELL for o in self._objects_template
                  if o.get("t") == T_END]
        self._end_x = max(end_xs) if end_xs else 0.0

        # Adaptive horizon state — starts at horizon_min and grows toward
        # horizon_max on stagnation, snaps back on progress. Keeps fast
        # iteration on flat corridors while letting hard arcs see the
        # full long lookahead they need.
        self._horizon_cur = self.horizon_min

        self._build_sim()

        if seed_inputs:
            self._apply_seed(seed_inputs)

        # ESC latch — set by _draw_progress when the user cancels.
        self._cancelled = False

        # Lazy BatchSim — built on first use if the level is
        # cube-only-compatible. Used to evaluate the whole population
        # in one numpy pass per generation; gives ~5-10× speedup over
        # the per-candidate Python loop on hard cube levels.
        from .batch_sim import is_compatible as _bsim_compat
        self._batch_compatible = _bsim_compat(self._objects_template)
        self._batch_sim = None

    # ------------------------------------------------------------------
    # Live sim / history bookkeeping
    # ------------------------------------------------------------------

    def _build_sim(self):
        self._sim_objects = [dict(o) for o in self._objects_template]
        self._sim = _SimPlayer(self._sim_objects, params=self._params)
        self._sim.trail = []
        self._sim.hitbox_trace = None
        self._sim.mirror_hitbox_trace = None
        # Per-frame history of (snap_after_frame, pressed_during_frame).
        # Index 0 holds the spawn snapshot before any update has run.
        self._history = [(_snap(self._sim), False)]
        self._inputs = []

    def _apply_seed(self, seed_inputs):
        """Replay ``seed_inputs`` into the live sim/history. Stops on
        the first frame that kills the sim — partial seeds still leave
        the bot at the deepest survivable point."""
        for held, pressed in seed_inputs:
            if not self._sim.alive or self._sim.won:
                break
            self._sim.update(held, pressed)
            self._inputs.append((held, pressed))
            self._history.append((_snap(self._sim), held))

    def _live_frame(self):
        return len(self._inputs)

    def _live_pressed(self):
        return self._history[-1][1]

    def _commit_one_frame(self, pressed):
        prev_pressed = self._live_pressed()
        edge = pressed and not prev_pressed
        self._sim.update(pressed, edge)
        self._inputs.append((pressed, edge))
        self._history.append((_snap(self._sim), pressed))

    def _rollback_to(self, frame):
        if frame < 0:
            frame = 0
        if frame > self._live_frame():
            return
        self._history = self._history[: frame + 1]
        self._inputs = self._inputs[: frame]
        snap, _pressed = self._history[-1]
        _restore(self._sim, snap)

    def _select_diverse_elites(self, scored_sorted):
        """Pick a diverse top-K from a sorted candidate list.

        Strategy: split candidates into ``ceil(elite_keep / 3)`` buckets
        by toggle count (sparse / medium / dense), take the best
        scorer from each bucket first, then fill remaining slots from
        the global ranking. This guarantees that the elite pool
        represents at least three regions of the search space rather
        than 12 near-duplicates of the current top scorer.

        Returns a list of ``(candidate_set, score_key, max_x)`` tuples
        in the same shape the previous top-K selector produced."""
        if not scored_sorted:
            return []
        k = self.elite_keep
        # Bucket survivors by toggle count.
        buckets = {}
        for cand, key, _end, mx in scored_sorted:
            tc = len(cand)
            if tc <= 1:
                bucket = 0
            elif tc <= 4:
                bucket = 1
            elif tc <= 8:
                bucket = 2
            else:
                bucket = 3
            buckets.setdefault(bucket, []).append((cand, key, mx))
        out = []
        seen_ids = set()
        # Round-robin pick from each bucket so the elite pool always
        # contains entries from multiple complexity classes.
        n_buckets = len(buckets)
        if n_buckets > 0:
            per_bucket = max(1, k // n_buckets)
            for b in sorted(buckets.keys()):
                for tup in buckets[b][:per_bucket]:
                    out.append(tup)
                    seen_ids.add(id(tup[0]))
                    if len(out) >= k:
                        break
                if len(out) >= k:
                    break
        # Fill the rest with the next-best globally.
        for cand, key, _end, mx in scored_sorted:
            if len(out) >= k:
                break
            if id(cand) in seen_ids:
                continue
            out.append((cand, key, mx))
            seen_ids.add(id(cand))
        return out

    def _smart_rollback(self, requested_frame):
        """Roll back to the most recent ``stable`` history frame at or
        before ``requested_frame``. A frame is stable when the snapshot's
        ``on_ground`` flag is True — these are clean checkpoints in
        cube/ball/spider/robot modes and matter zero in flight modes
        (where every frame is mid-air anyway, and we just fall through
        to the requested frame). Stable rollback is more useful than
        blind N-frames-back because the bot resumes from a well-defined
        physics state instead of a random apex of a previous arc."""
        if requested_frame < 0:
            requested_frame = 0
        if requested_frame > self._live_frame():
            return
        # _ON_GROUND index in SnapVals is 3 — see autobot._snap.
        target = requested_frame
        for f in range(min(requested_frame, len(self._history) - 1), -1, -1):
            snap, _ = self._history[f]
            vals = snap[0]
            try:
                if vals[3]:  # on_ground
                    target = f
                    break
            except (IndexError, TypeError):
                # Snap layout drifted (legacy on-disk cache?) — just
                # use the requested frame.
                break
        self._rollback_to(target)

    # ------------------------------------------------------------------
    # Candidate generation
    # ------------------------------------------------------------------

    def _current_mode(self):
        return getattr(self._sim, "mode", MODE_CUBE)

    def _interval_candidate(self, start_frame):
        """Sample toggles by stepping in mode-aware intervals — wave
        gets short steps, cube long ones. Empirically much stronger
        than uniform-random for tight corridors."""
        lo, hi = _MODE_INTERVAL.get(self._current_mode(), (6, 40))
        rng_int = self._rng.randint
        out = set()
        cur = start_frame
        for _ in range(self.toggles_per_candidate):
            cur += rng_int(lo, hi)
            if cur >= start_frame + self._horizon_cur:
                break
            out.add(cur)
        return out

    def _uniform_candidate(self, start_frame):
        """Pure-random uniform toggle frames in [start, start+horizon).
        Coverage of timing patterns the interval sampler would miss."""
        rng_int = self._rng.randint
        horizon = self._horizon_cur
        out = set()
        # Uniform distribution can collide on the same frame; the set
        # collapses dupes naturally so the actual count varies.
        for _ in range(self.toggles_per_candidate):
            out.add(start_frame + rng_int(0, horizon - 1))
        return out

    def _sparse_candidate(self, start_frame):
        """Single- or twin-toggle candidate. Many real jumps are 'press
        once' or 'press twice' — spending a whole population slot on
        cluttered noise here is worse than dedicating some to the small,
        clean shapes."""
        rng_int = self._rng.randint
        n = self._rng.randint(0, 2)
        out = set()
        for _ in range(n):
            out.add(start_frame + rng_int(0, self._horizon_cur - 1))
        return out

    def _hold_candidate(self, start_frame):
        """Long-hold candidate for ship/wave/robot. The toggle set is
        a small number of mode-changes inside an otherwise held window
        — closer to how a human flies these modes (steady press with
        occasional release) than alternating taps."""
        rng_int = self._rng.randint
        out = set()
        n = self._rng.randint(1, 3)
        for _ in range(n):
            out.add(start_frame + rng_int(0, self._horizon_cur - 1))
        return out

    def _mutate(self, base, start_frame):
        """Mutation operators — chosen uniformly from a set tuned to
        balance exploration (burst replace, jitter) against exploitation
        (small shifts on existing toggles). Returns a NEW set so the
        caller can keep the parent intact."""
        if not base:
            return self._interval_candidate(start_frame)
        rng = self._rng
        out = set(base)
        end = start_frame + self._horizon_cur
        op = rng.randrange(8)

        if op == 0 and out:
            # Shift one toggle by a wide window — coarse re-aim.
            pick = rng.choice(tuple(out))
            out.discard(pick)
            shift = rng.randint(-10, 10)
            out.add(max(start_frame, min(end - 1, pick + shift)))
        elif op == 1:
            # Add a fresh random toggle.
            out.add(start_frame + rng.randint(0, self._horizon_cur - 1))
        elif op == 2 and len(out) > 1:
            # Drop a random toggle (simplification mutator).
            out.discard(rng.choice(tuple(out)))
        elif op == 3:
            # Shift several toggles by ±3 frames each.
            picks = rng.sample(tuple(out), min(3, len(out)))
            for pick in picks:
                out.discard(pick)
                shift = rng.randint(-3, 3)
                out.add(max(start_frame, min(end - 1, pick + shift)))
        elif op == 4 and out:
            # ±1 frame jitter — frame-perfect timing tightening. This is
            # the exploit op that lets the search converge on a
            # frame-perfect arc once the rough shape is right.
            picks = rng.sample(tuple(out), min(2, len(out)))
            for pick in picks:
                out.discard(pick)
                shift = rng.choice((-1, 1))
                out.add(max(start_frame, min(end - 1, pick + shift)))
        elif op == 5:
            # Burst replace — pick a random window inside the horizon
            # and regenerate every toggle that falls in it. Lets the
            # search escape a local minimum where the tail of the
            # candidate has the right shape but the head is wrong.
            burst_lo = start_frame + rng.randint(0, self._horizon_cur - 1)
            burst_hi = burst_lo + rng.randint(20, max(40, self._horizon_cur // 3))
            burst_hi = min(end - 1, burst_hi)
            out = {t for t in out if t < burst_lo or t > burst_hi}
            n_new = rng.randint(1, 4)
            for _ in range(n_new):
                if burst_hi > burst_lo:
                    out.add(rng.randint(burst_lo, burst_hi))
        elif op == 6 and out:
            # Reflect a toggle around the horizon midpoint — explores
            # late-vs-early symmetric arcs without changing toggle count.
            pick = rng.choice(tuple(out))
            out.discard(pick)
            mid = start_frame + self._horizon_cur // 2
            new = 2 * mid - pick
            out.add(max(start_frame, min(end - 1, new)))
        else:
            # Wholesale replace 1-2 toggles with fresh randoms.
            if out:
                picks = rng.sample(tuple(out), min(2, len(out)))
                for pick in picks:
                    out.discard(pick)
            for _ in range(rng.randint(1, 2)):
                out.add(start_frame + rng.randint(0, self._horizon_cur - 1))
        return out

    def _crossover(self, a, b, start_frame):
        """Splice two elites: pick a midpoint, take toggles before it
        from one parent and after from the other. Cheap diversification
        when two elites discovered different sub-routes."""
        if not a:
            return set(b)
        if not b:
            return set(a)
        end = start_frame + self._horizon_cur
        mid = start_frame + self._rng.randint(0, self._horizon_cur - 1)
        out = {t for t in a if t < mid}
        out.update(t for t in b if t >= mid and t < end)
        return out

    # ------------------------------------------------------------------
    # Candidate evaluation
    # ------------------------------------------------------------------

    def _try_inputs(self, candidate, start_frame, snap0, initial_pressed):
        """Simulate ``candidate`` from ``snap0`` and return
        ``(score, won, terminal_frame, max_x)``. Score blends
        max_x_reached with frame_survived so a candidate that flies
        high but crashes one cell sooner doesn't out-rank one that
        crawled a foot farther.

        Hot path — called population × generations times per solve. Local
        binds for ``sim.update`` and the toggle set membership shave
        ~20% off Python overhead; max_x is updated as a plain float
        without ``float(sim.x)`` re-conversion since ``sim.x`` already
        is a float."""
        sim = self._sim
        _restore(sim, snap0)
        pressed = initial_pressed
        prev_pressed = pressed
        cur = start_frame
        toggles = set(candidate)
        if toggles:
            last_toggle = max(toggles)
        else:
            last_toggle = cur
        # 60-frame tail past the final toggle so a candidate gets credit
        # for flying past its instructions.
        sim_until = last_toggle + 60
        max_x = sim.x
        # Local-bind the update method — a single ``LOAD_ATTR`` saved per
        # frame compounds because this is the loop's hottest call.
        sim_update = sim.update
        toggles_discard = toggles.discard
        # Stuck-detection: candidates that don't advance x for ~30
        # frames are wasting sim time. Bail early once the trailing
        # toggles are exhausted and the sim has plateaued.
        stuck_x = max_x
        stuck_at = cur
        while cur < sim_until:
            if cur in toggles:
                pressed = not pressed
                toggles_discard(cur)
            edge = pressed and not prev_pressed
            sim_update(pressed, edge)
            prev_pressed = pressed
            if not sim.alive or sim.won:
                break
            sx = sim.x
            if sx > max_x:
                max_x = sx
                stuck_x = sx
                stuck_at = cur
            elif not toggles and cur - stuck_at > 30 and sx <= stuck_x + 0.5:
                # No more toggles to fire AND haven't advanced x for 30
                # frames — this candidate has converged. Stop wasting
                # sim ticks and let scoring rank it on what we have.
                cur += 1
                break
            cur += 1
        won = bool(sim.won)
        # terminal frame = frame index just past the last successful update.
        terminal = cur if (sim.alive or sim.won) else cur - 1
        _restore(sim, snap0)
        return terminal, won, terminal, max_x

    def _commit_first_part(self, candidate, start_frame, end_frame):
        """Commit [start_frame, stop_frame) of the best candidate to
        the live sim. ``stop_frame`` is start_frame + commit_fraction
        of (end_frame - start_frame). Returns the new live frame."""
        span = max(0, end_frame - start_frame)
        stop_frame = start_frame + max(1, int(span * self.commit_fraction))
        toggles = set(candidate)
        pressed = self._live_pressed()
        for f in range(start_frame, stop_frame):
            if f in toggles:
                pressed = not pressed
            self._commit_one_frame(pressed)
            if not self._sim.alive or self._sim.won:
                break
        return self._live_frame()

    def _commit_winning(self, candidate, start_frame):
        """Commit a winning candidate's toggles in full to the live sim."""
        toggles = set(candidate)
        pressed = self._live_pressed()
        cur = start_frame
        # Defensive cap so a buggy "won" candidate can't loop forever.
        cap = self._horizon_cur * 4
        while self._sim.alive and not self._sim.won:
            if cur in toggles:
                pressed = not pressed
            self._commit_one_frame(pressed)
            cur += 1
            if cur - start_frame > cap:
                break

    # ------------------------------------------------------------------
    # Population builder
    # ------------------------------------------------------------------

    def _build_population(self, start_frame, elites):
        """Mixture: elites' mutations + crossovers + fresh samples.

        The split is tuned for empirical performance:
          ~40% mutations of elites (intensification)
          ~10% crossovers between elite pairs (recombination)
          ~30% interval / hold candidates (mode-aware exploration)
          ~20% uniform / sparse candidates (random exploration)

        With no elites yet, mutation slots are redirected to fresh
        samples so the first generation is broad-coverage."""
        n = self.population
        out = []

        if elites:
            n_mutate = (n * 4) // 10
            n_cross = (n * 1) // 10
            n_interval = (n * 3) // 10
            n_uniform = max(1, (n * 1) // 10)
            n_sparse = max(1, (n * 1) // 10)
        else:
            n_mutate = 0
            n_cross = 0
            n_interval = (n * 5) // 10
            n_uniform = (n * 3) // 10
            n_sparse = max(1, (n * 2) // 10)

        for _ in range(n_mutate):
            base = self._rng.choice(elites)[0]
            out.append(self._mutate(base, start_frame))
        for _ in range(n_cross):
            a, b = self._rng.sample(elites,
                                    min(2, len(elites))) if len(elites) > 1 else (elites[0], elites[0])
            out.append(self._crossover(a[0], b[0], start_frame))
        for _ in range(n_interval):
            out.append(self._interval_candidate(start_frame))
        for _ in range(n_uniform):
            out.append(self._uniform_candidate(start_frame))
        for _ in range(n_sparse):
            out.append(self._sparse_candidate(start_frame))

        # Mode-aware bonus: in continuous-y modes, spend a slice on
        # hold-shaped candidates that toggle infrequently.
        if self._current_mode() in _HOLD_MODES:
            for _ in range(max(1, n // 10)):
                out.append(self._hold_candidate(start_frame))

        # Pad to population size with uniform fills if integer division
        # left us short.
        while len(out) < n:
            out.append(self._uniform_candidate(start_frame))
        return out[:n]

    # ------------------------------------------------------------------
    # Public solve entry point
    # ------------------------------------------------------------------

    def _eval_population_batch(self, population, start_frame,
                                initial_pressed):
        """Evaluate every candidate in ``population`` against the
        committed-input prefix using BatchSim's vectorised cube-mode
        physics. Returns a list of ``(terminal, won, end_frame, max_x)``
        tuples in the same order as ``population``.

        Falls back to ``None`` when the level isn't BatchSim-compatible
        (caller runs the per-candidate Python loop instead).

        The batch path replays the committed prefix ONCE for the whole
        population — Player.update gets called len(prefix) times
        instead of N × len(prefix) — and then evaluates the toggle
        windows per-player in lockstep numpy steps.
        """
        if not self._batch_compatible:
            return None
        try:
            import numpy as np
            from .batch_sim import BatchSim
            n = len(population)
            sim = BatchSim(self._objects_template, params=self._params, n=n)
            # ---- Replay committed inputs (same for all N players) ---
            # We can't directly snap from the live sim into BatchSim
            # (different state representations), so we rebuild from
            # spawn. The prefix replay is dirt cheap thanks to numpy
            # — it's roughly one Player.update per frame regardless
            # of N.
            committed = self._inputs
            held_arr = np.zeros(n, dtype=bool)
            pressed_arr = np.zeros(n, dtype=bool)
            for h, p in committed:
                held_arr.fill(h)
                pressed_arr.fill(p)
                sim.step(held_arr, pressed_arr)
            if not np.any(sim.alive & ~sim.won):
                # Prefix already killed/won everyone — return uniform
                # tuples so the caller stays in lockstep with the
                # serial path's contract.
                return [(start_frame, bool(sim.won[0]),
                         start_frame, float(sim.x[0]))
                        for _ in range(n)]
            # ---- Per-player toggle window ---------------------------
            # Pre-build per-frame toggle masks: for each (frame, player)
            # whether to flip the held state. Keeping the toggle sets
            # in a dict-of-frame->mask form makes each step's flip a
            # bool-array AND.
            toggle_frames = {}
            last_toggles = []
            for k, cand in enumerate(population):
                if not cand:
                    last_toggles.append(start_frame)
                    continue
                lt = max(cand)
                last_toggles.append(lt)
                for f in cand:
                    if f not in toggle_frames:
                        toggle_frames[f] = np.zeros(n, dtype=bool)
                    toggle_frames[f][k] = True
            sim_until = max(last_toggles) + 60 if last_toggles else (
                start_frame + 60)
            pressed_state = np.full(n, bool(initial_pressed), dtype=bool)
            prev_pressed = pressed_state.copy()
            max_x = sim.x.copy()
            terminal = np.full(n, start_frame, dtype=np.int32)
            ended = np.zeros(n, dtype=bool)
            stuck_x = sim.x.copy()
            stuck_at = np.full(n, start_frame, dtype=np.int32)
            cur = start_frame
            while cur < sim_until:
                # Flip pressed_state where this frame is in the
                # candidate's toggle set.
                if cur in toggle_frames:
                    pressed_state ^= toggle_frames[cur]
                edge = pressed_state & ~prev_pressed
                sim.step(pressed_state, edge)
                prev_pressed = pressed_state.copy()
                # Newly ended (died this frame).
                live = sim.alive & ~sim.won
                newly_dead = ~live & ~ended
                if np.any(newly_dead):
                    terminal[newly_dead] = cur
                    ended[newly_dead] = True
                # Update max_x for live players.
                progressed = sim.x > max_x
                max_x = np.where(progressed, sim.x, max_x)
                stuck_x = np.where(progressed, sim.x, stuck_x)
                stuck_at = np.where(progressed, cur, stuck_at)
                cur += 1
                # Bail when every player has ended.
                if ended.all():
                    break
            # Mark survivors' terminal as ``cur`` (matches serial
            # contract: terminal = frame past last successful update
            # for alive/won; cur-1 for dead).
            terminal = np.where(ended, terminal, cur)
            results = []
            for k in range(n):
                results.append((
                    int(terminal[k]),
                    bool(sim.won[k]),
                    int(terminal[k]),
                    float(max_x[k]),
                ))
            return results
        except Exception:
            # Any unexpected divergence — fall back to serial. The
            # batch path is an optimisation; correctness lives in the
            # original per-candidate loop.
            return None

    def solve(self, screen=None, clock=None):
        """Run the generation-based search and return
        ``(waypoints, inputs, won)``."""
        from . import sfx
        was_enabled = sfx.is_enabled()
        if was_enabled:
            sfx.toggle()
        try:
            return self._solve_inner(screen, clock)
        finally:
            if was_enabled:
                sfx.toggle()

    def _solve_inner(self, screen, clock):
        # Best-ever live position so a stuck rollback chain still
        # returns its deepest reached macro.
        best_inputs_seen = list(self._inputs)
        best_history_len = len(self._history)
        best_x = float(self._sim.x)
        won = False

        fail = self.rollback_initial
        last_progress_x = best_x
        ui_last_t = 0.0

        # Elite pool: list of (toggles, score, max_x). Reset on rollback
        # since stale toggle sets steer us back into the corridor that
        # just killed us.
        elites = []

        # Adaptive horizon — start tight (cheap iterations on flat
        # corridors) and grow toward horizon_max on stagnation. Snapped
        # back to horizon_min on every progress event so the next hard
        # arc starts cheap.
        self._horizon_cur = self.horizon_min
        gens_without_progress = 0
        # Random-seed restart: when extreme stagnation hits, swap the RNG
        # for a fresh seed and bump the rollback. Lets the search escape
        # a basin of attraction that all current elites converge to.
        seed_restarts = 0
        MAX_SEED_RESTARTS = 4
        STAGNATION_GROW = 60     # gens before horizon grows
        STAGNATION_RESTART = 240  # gens before RNG-restart

        # Wall-clock budget — sampled once per generation. The flag is
        # also flipped by ESC (via _draw_progress) so cancellation is
        # detected on the same boundary.
        deadline = (time.time() + self.time_budget
                    if self.time_budget else None)

        # Event-pump throttle: pumping pygame.event.get() per generation
        # keeps ESC responsive without dominating the inner loop. Wrapped
        # in try/except so headless tests (no display) don't crash.
        last_pump = 0.0
        for it in range(self.max_iterations):
            if self._cancelled:
                break
            if deadline is not None and time.time() > deadline:
                break
            now_t = time.time()
            if (now_t - last_pump) > 0.05:
                last_pump = now_t
                try:
                    for ev in pygame.event.get():
                        if ev.type == pygame.QUIT:
                            pygame.quit()
                            raise SystemExit
                        if (ev.type == pygame.KEYDOWN
                                and ev.key == pygame.K_ESCAPE):
                            self._cancelled = True
                except pygame.error:
                    pass
                if self._cancelled:
                    break
            if not self._sim.alive:
                # Smart rollback: skip back to the most recent on-ground
                # frame at or before the blind ``fail`` step. Resuming
                # from a stable physics state is much more productive
                # than resuming mid-air on the apex of a previous arc.
                self._smart_rollback(self._live_frame() - fail)
                fail += self.rollback_growth
                elites = []
                continue
            if self._sim.won:
                won = True
                break

            start_frame = self._live_frame()
            snap0 = _snap(self._sim)
            initial_pressed = self._live_pressed()

            population = self._build_population(start_frame, elites)

            # Score every candidate. Track the best by (won, max_x,
            # terminal_frame). A win short-circuits the generation.
            scored = []
            best_won = False
            best_won_cand = None
            best_won_end = 0
            best_score_idx = -1
            best_score = (-1.0, -1)  # (max_x, terminal_frame)

            # Inverse-press probe runs only on a sparse cadence + on
            # stagnation. Every-generation eval (the previous default)
            # was nearly doubling sim work in flight modes; the
            # inverse-press case is genuinely useful but only as a
            # diversifier when the primary search isn't finding a
            # winning arc.
            try_inverse = (self._current_mode() in _HOLD_MODES
                           and (it % 3 == 0
                                or gens_without_progress > 20))
            # Mid-generation deadline check — a single generation of
            # population × _try_inputs can take seconds; without an
            # in-loop check we'd overrun budget by a full generation
            # whenever the deadline lands mid-population.
            deadline_break = False

            # ---- Batch fast path ------------------------------------
            # When the level is BatchSim-compatible (cube only, no
            # orbs/portals/triggers), evaluate the whole population
            # in one numpy pass and skip the serial per-candidate
            # loop entirely. Try-inverse runs separately as a
            # diversifier on stagnation rounds.
            batch_results = self._eval_population_batch(
                population, start_frame, initial_pressed)
            if batch_results is not None:
                for cand, (term, c_won, end_f, mx) in zip(
                        population, batch_results):
                    if c_won:
                        best_won = True
                        best_won_cand = cand
                        best_won_end = end_f
                        break
                    key = (mx, term)
                    scored.append((cand, key, end_f, mx))
                    if key > best_score:
                        best_score = key
                        best_score_idx = len(scored) - 1
                # Skip the serial loop below.
                population = ()

            for cand in population:
                if (deadline is not None
                        and time.time() > deadline):
                    deadline_break = True
                    break
                term, c_won, end_f, mx = self._try_inputs(
                    cand, start_frame, snap0, initial_pressed)
                if c_won:
                    best_won = True
                    best_won_cand = cand
                    best_won_end = end_f
                    break
                key = (mx, term)
                scored.append((cand, key, end_f, mx))
                if key > best_score:
                    best_score = key
                    best_score_idx = len(scored) - 1
                # ALSO try the candidate with the inverse initial pressed
                # state — covers cases where the right action is "release
                # immediately then press at frame K". Without this branch
                # the search can never even consider releasing a held
                # ship/wave at the very start of a new commit window.
                if try_inverse:
                    term2, c_won2, end_f2, mx2 = self._try_inputs(
                        cand, start_frame, snap0, not initial_pressed)
                    if c_won2:
                        best_won = True
                        best_won_cand = cand
                        best_won_end = end_f2
                        break
                    key2 = (mx2, term2)
                    if key2 > best_score:
                        best_score = key2
                        # Re-score: store the inverse-pressed entry as
                        # the surviving candidate so commit-first-part
                        # uses its toggle layout.
                        scored[-1] = (cand, key2, end_f2, mx2)
                        best_score_idx = len(scored) - 1

            _restore(self._sim, snap0)

            # Honor the mid-generation deadline break: skip commit /
            # elite update so the loop top sees the deadline check and
            # exits cleanly. Otherwise we'd commit one more partial
            # candidate past the wall-clock cap.
            if deadline_break and not best_won:
                break

            if best_won:
                self._commit_winning(best_won_cand, start_frame)
                won = self._sim.won
                if won:
                    break
                # Rare: a "winning" candidate's commit phase died (e.g.
                # gravity flip during the commit window changed state).
                # Treat as no-progress and rollback.
                self._smart_rollback(start_frame - fail)
                fail += self.rollback_growth
                elites = []
                continue

            if best_score_idx < 0 or best_score[0] <= float(self._sim.x) + 0.5:
                # No candidate beat the start frame — rollback and grow
                # the rollback step. Drop elites: they were tuned to a
                # state we're no longer in.
                self._smart_rollback(start_frame - fail)
                fail += self.rollback_growth
                elites = []
                gens_without_progress += 1
            else:
                cand, _key, end_f, mx = scored[best_score_idx]
                self._commit_first_part(cand, start_frame, end_f)
                # Diverse elite selection — bucket survivors by toggle
                # count, then take the top scorer from each bucket
                # before falling back to global top-K. Pure top-K tends
                # to fill the elite pool with near-duplicates of the
                # current best, which collapses the next generation's
                # mutation pool to a single basin. Bucketing forces
                # the search to keep candidates of varying complexity
                # alive.
                scored.sort(key=lambda t: t[1], reverse=True)
                elites = self._select_diverse_elites(scored)
                cur_x = float(self._sim.x)
                if cur_x > last_progress_x + 0.5:
                    fail = self.rollback_initial
                    last_progress_x = cur_x
                    gens_without_progress = 0
                    # Snap horizon back to min on real progress so the
                    # next arc starts iterating fast again.
                    self._horizon_cur = self.horizon_min
                else:
                    gens_without_progress += 1

            # Adaptive horizon: grow on stagnation so harder arcs can be
            # planned over a longer lookahead.
            if gens_without_progress >= STAGNATION_GROW:
                self._horizon_cur = min(
                    self.horizon_max,
                    int(self._horizon_cur * 1.5) + 30)

            # Random-seed restart: extreme stagnation means every elite
            # converges to a dead-end basin. Re-seed the RNG and drop
            # elites so the next gen is full-coverage uniform sampling.
            if (gens_without_progress >= STAGNATION_RESTART
                    and seed_restarts < MAX_SEED_RESTARTS):
                seed_restarts += 1
                base_seed = (self._initial_seed
                             if self._initial_seed is not None else 0)
                self._rng = random.Random(base_seed + seed_restarts * 9173)
                elites = []
                gens_without_progress = 0
                # Big rollback on restart — escape the local minimum.
                self._rollback_to(self._live_frame() - fail * 4)
                fail = self.rollback_initial

            cur_x = float(self._sim.x)
            if cur_x > best_x:
                best_x = cur_x
                best_inputs_seen = list(self._inputs)
                best_history_len = len(self._history)

            if screen is not None and (time.time() - ui_last_t) > 0.1:
                ui_last_t = time.time()
                if self._draw_progress(screen, clock, it, best_x,
                                       fail, len(self._inputs)):
                    break

            if self._sim.won:
                won = True
                break

        if won:
            inputs_out = list(self._inputs)
            history_for_wp = self._history
        elif best_x > float(self._sim.x):
            inputs_out = list(best_inputs_seen)
            history_for_wp = self._history[:best_history_len]
        else:
            inputs_out = list(self._inputs)
            history_for_wp = self._history

        waypoints = self._waypoints_from_history(history_for_wp)
        return waypoints, inputs_out, won

    # ------------------------------------------------------------------
    # Waypoint export (for run_play's overlay + desync watchdog)
    # ------------------------------------------------------------------

    def _waypoints_from_history(self, history):
        """Replay history's pressed states against a fresh sim to
        sample (x, y) every 2 frames. The dense sampling makes the
        predicted-path overlay read as a smooth line rather than dots."""
        if not history or not self._inputs:
            return []
        replay_objects = [dict(o) for o in self._objects_template]
        replay = _SimPlayer(replay_objects, params=self._params)
        replay.trail = []
        size_attr = getattr(replay, "size", 0) or 0
        wp = [(replay.x + size_attr / 2, replay.y + size_attr / 2)]
        for i, (pressed, edge) in enumerate(self._inputs):
            replay.update(pressed, edge)
            if i % 2 == 0 or not replay.alive or replay.won:
                size_attr = getattr(replay, "size", 0) or 0
                wp.append((replay.x + size_attr / 2,
                           replay.y + size_attr / 2))
            if not replay.alive or replay.won:
                break
        return wp

    # ------------------------------------------------------------------
    # Progress UI
    # ------------------------------------------------------------------

    def _draw_progress(self, screen, clock, iteration, best_x,
                       fail, n_inputs):
        from .graphics import txt
        level_pct = 0
        if self._end_x > 0:
            level_pct = min(100, max(0, int(best_x / self._end_x * 100)))
        screen.fill((10, 8, 24))
        txt(screen, "PATHFINDER SEARCH", WIDTH // 2, HEIGHT // 2 - 86,
            32, (120, 200, 255), True)
        txt(screen,
            f"gen {iteration} · committed {n_inputs} frames · rollback {fail}",
            WIDTH // 2, HEIGHT // 2 - 52, 16, (180, 220, 255), True)
        txt(screen, f"X {int(best_x)}",
            WIDTH // 2, HEIGHT // 2 - 18, 18, (180, 180, 200), True)
        bw = 460
        bx = WIDTH // 2 - bw // 2
        by = HEIGHT // 2 + 14
        bh = 24
        pygame.draw.rect(screen, (40, 40, 60), (bx, by, bw, bh),
                         border_radius=6)
        if self._end_x > 0 and level_pct > 0:
            bar_color = ((90, 255, 120) if level_pct > 80
                         else (255, 180, 60) if level_pct > 40
                         else (230, 130, 80))
            pygame.draw.rect(screen, bar_color,
                             (bx, by,
                              max(1, int(bw * level_pct / 100)), bh),
                             border_radius=6)
        txt(screen, f"{level_pct}%", WIDTH // 2, by + 4,
            14, (255, 255, 255), True)
        txt(screen, "Escape to cancel",
            WIDTH // 2, HEIGHT // 2 + 90, 14, (140, 140, 155), True)
        pygame.display.flip()
        if clock:
            clock.tick(60)
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit()
                raise SystemExit
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                self._cancelled = True
                return True
        return False
