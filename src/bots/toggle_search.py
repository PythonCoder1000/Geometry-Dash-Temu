"""Randomised toggle search — the generation-based engine.

This is the search that used to be ``pathfinder_bot.py``.  It is not a
bot: it has no opinion about what a good route is, it just samples
button-toggle patterns, keeps the ones that survive furthest, mutates
them, and commits the front of the winner.  Both bots use it as a phase
when their directed search runs out of ideas — the human bot to break
out of a stalled A* frontier, the loophole bot to explore off-path.

A candidate is a *set of toggle frames*, which is a one-button
representation by construction: the button flips at those frames and
holds otherwise, so the press edge always lands where a hold begins.
The engine simply refuses to place two toggles closer together than the
active :class:`~.action_space.InputModel` allows.

Rollback is what gives the engine its escape from a dead end.  On
repeated failure it rewinds the committed prefix — preferentially to a
frame where the player was grounded, which is a well-defined physics
state to rebuild from rather than the apex of some previous arc.
"""

import random
import time

from ..constants import (
    UNITS_PER_BLOCK, MODE_CUBE, MODE_BALL, MODE_SPIDER, MODE_SWING,
    MODE_ROBOT, MODE_SHIP, MODE_UFO, MODE_WAVE, T_END,
)
from .action_space import DWELL_CAP, HUMAN, replay_state
from .sim import SimPlayer, snapshot, restore

# Frames between toggles for the interval sampler, per mode.  Wave needs
# fast flips to hold a corridor; cube wants sparse taps because extra
# clicks just spend input buffer.
MODE_INTERVAL = {
    MODE_CUBE:   (8, 60),
    MODE_BALL:   (6, 40),
    MODE_SPIDER: (6, 40),
    MODE_SWING:  (4, 30),
    MODE_ROBOT:  (4, 30),
    MODE_SHIP:   (4, 25),
    MODE_UFO:    (5, 35),
    MODE_WAVE:   (2, 12),
}

# Modes flown with sustained holds rather than taps.
HOLD_MODES = (MODE_SHIP, MODE_WAVE, MODE_ROBOT, MODE_UFO)


class ToggleSearch:
    """Generation search over toggle-frame sets.

    Parameters
    ----------
    objects, params : the level and its physics override.
    model : :class:`~.action_space.InputModel` — bounds how close two
        toggles may be placed.
    seed_inputs : input chain to commit before searching.
    fitness : optional ``callable(sim) -> float`` added to a candidate's
        score.  The loophole bot passes a path-adherence term here; with
        no fitness the engine ranks purely on x reached.
    """

    HORIZON_MIN = 150
    HORIZON_MAX = 300
    POPULATION = 400
    ELITE_KEEP = 12
    TOGGLES_PER_CANDIDATE = 14
    COMMIT_FRACTION = 1.0 / 3.0
    ROLLBACK_INITIAL = 5
    ROLLBACK_GROWTH = 5
    MAX_ITERATIONS = 8000
    # Generations without progress before the horizon grows / the RNG is
    # reseeded to leave the current basin of attraction.
    STAGNATION_GROW = 60
    STAGNATION_RESTART = 240
    MAX_SEED_RESTARTS = 4

    def __init__(self, objects, params=None, *, model=HUMAN,
                 seed_inputs=None, time_budget=None, progress=None,
                 rng_seed=None, fitness=None):
        self.objects = [dict(o) for o in objects]
        self.params = params
        self.model = model
        self.time_budget = float(time_budget) if time_budget else None
        self.progress = progress
        self.fitness = fitness
        self.rng = random.Random(rng_seed)

        end_xs = [o["x"] * UNITS_PER_BLOCK for o in self.objects if o.get("t") == T_END]
        self.end_x = max(end_xs) if end_xs else 0.0
        self.horizon = self.HORIZON_MIN

        self.sim = SimPlayer([dict(o) for o in self.objects], params=params)
        self.sim.trail = []
        self.sim.hitbox_trace = None
        self.sim.mirror_hitbox_trace = None
        # history[i] = (snapshot after i frames, held state during frame i-1)
        self.history = [(snapshot(self.sim), False)]
        self.inputs = []
        # Frames the button has been in its current state at the commit
        # head. Gates toggles that would land too soon after the last one.
        self.committed_dwell = DWELL_CAP
        if seed_inputs:
            self._apply_seed(seed_inputs)

    # ---- committed-prefix bookkeeping ---------------------------------

    def _apply_seed(self, seed_inputs):
        for held, pressed in self.model.sanitize(seed_inputs):
            if not self.sim.alive or self.sim.won:
                break
            self.sim.update(held, pressed)
            self.inputs.append((held, pressed))
            self.history.append((snapshot(self.sim), held))
        _prev, self.committed_dwell = replay_state(self.inputs)

    def live_frame(self):
        return len(self.inputs)

    def live_held(self):
        return self.history[-1][1]

    def commit_frame(self, held):
        prev = self.live_held()
        pressed = self.model.edge(held, prev)
        self.sim.update(held, pressed)
        self.inputs.append((held, pressed))
        self.history.append((snapshot(self.sim), held))
        self.committed_dwell = 1 if held != prev else self.committed_dwell + 1

    def rollback_to(self, frame):
        """Rewind to the last grounded frame at or before ``frame``.

        Grounded frames are clean checkpoints in the tap modes and cost
        nothing in flight modes (where none exist and we land on the
        requested frame anyway).
        """
        frame = max(0, min(frame, self.live_frame()))
        target = frame
        for f in range(min(frame, len(self.history) - 1), -1, -1):
            snap, _ = self.history[f]
            if snap[0][3]:  # SnapVals.on_ground
                target = f
                break
        self.history = self.history[: target + 1]
        self.inputs = self.inputs[: target]
        restore(self.sim, self.history[-1][0])
        # Recompute rather than carry the old counter: a rewind changes
        # how long the button has been in its state at the commit head.
        _prev, self.committed_dwell = replay_state(self.inputs)

    # ---- candidate sampling -------------------------------------------

    def _mode(self):
        return getattr(self.sim, "mode", MODE_CUBE)

    def _spaced(self, frames, start):
        """Drop toggles that would violate the model's dwell rule."""
        gap = self.model.min_dwell
        if gap <= 1:
            return set(frames)
        out = []
        for f in sorted(frames):
            if not out or f - out[-1] >= gap:
                out.append(f)
        return set(out)

    def _interval_candidate(self, start):
        lo, hi = MODE_INTERVAL.get(self._mode(), (6, 40))
        lo = max(lo, self.model.min_dwell)
        hi = max(hi, lo)
        out = set()
        cur = start
        for _ in range(self.TOGGLES_PER_CANDIDATE):
            cur += self.rng.randint(lo, hi)
            if cur >= start + self.horizon:
                break
            out.add(cur)
        return out

    def _uniform_candidate(self, start):
        out = {start + self.rng.randint(0, self.horizon - 1)
               for _ in range(self.TOGGLES_PER_CANDIDATE)}
        return self._spaced(out, start)

    def _sparse_candidate(self, start):
        """One or two toggles — most real jumps are 'press once'."""
        out = {start + self.rng.randint(0, self.horizon - 1)
               for _ in range(self.rng.randint(0, 2))}
        return self._spaced(out, start)

    def _hold_candidate(self, start):
        """A few flips inside an otherwise held window, for flight modes."""
        out = {start + self.rng.randint(0, self.horizon - 1)
               for _ in range(self.rng.randint(1, 3))}
        return self._spaced(out, start)

    def _mutate(self, base, start):
        if not base:
            return self._interval_candidate(start)
        rng = self.rng
        out = set(base)
        end = start + self.horizon
        op = rng.randrange(8)

        def _place(value):
            out.add(max(start, min(end - 1, value)))

        if op == 0:
            pick = rng.choice(tuple(out))
            out.discard(pick)
            _place(pick + rng.randint(-10, 10))
        elif op == 1:
            _place(start + rng.randint(0, self.horizon - 1))
        elif op == 2 and len(out) > 1:
            out.discard(rng.choice(tuple(out)))
        elif op == 3:
            for pick in rng.sample(tuple(out), min(3, len(out))):
                out.discard(pick)
                _place(pick + rng.randint(-3, 3))
        elif op == 4:
            # Single-frame jitter — the exploit operator that tightens a
            # roughly-right arc into an exact one.
            for pick in rng.sample(tuple(out), min(2, len(out))):
                out.discard(pick)
                _place(pick + rng.choice((-1, 1)))
        elif op == 5:
            # Burst replace: regenerate a window so the search can drop a
            # wrong head while keeping a right tail.
            lo = start + rng.randint(0, self.horizon - 1)
            hi = min(end - 1, lo + rng.randint(20, max(40, self.horizon // 3)))
            out = {t for t in out if t < lo or t > hi}
            for _ in range(rng.randint(1, 4)):
                if hi > lo:
                    out.add(rng.randint(lo, hi))
        elif op == 6:
            pick = rng.choice(tuple(out))
            out.discard(pick)
            _place(2 * (start + self.horizon // 2) - pick)
        else:
            for pick in rng.sample(tuple(out), min(2, len(out))):
                out.discard(pick)
            for _ in range(rng.randint(1, 2)):
                _place(start + rng.randint(0, self.horizon - 1))
        return self._spaced(out, start)

    def _crossover(self, a, b, start):
        if not a:
            return set(b)
        if not b:
            return set(a)
        mid = start + self.rng.randint(0, self.horizon - 1)
        out = {t for t in a if t < mid}
        out.update(t for t in b if mid <= t < start + self.horizon)
        return self._spaced(out, start)

    def _population(self, start, elites):
        n = self.POPULATION
        out = []
        if elites:
            counts = ((n * 4) // 10, (n * 1) // 10, (n * 3) // 10,
                      max(1, n // 10), max(1, n // 10))
        else:
            counts = (0, 0, (n * 5) // 10, (n * 3) // 10, max(1, (n * 2) // 10))
        n_mut, n_cross, n_int, n_uni, n_sparse = counts
        for _ in range(n_mut):
            out.append(self._mutate(self.rng.choice(elites)[0], start))
        for _ in range(n_cross):
            if len(elites) > 1:
                a, b = self.rng.sample(elites, 2)
            else:
                a = b = elites[0]
            out.append(self._crossover(a[0], b[0], start))
        for _ in range(n_int):
            out.append(self._interval_candidate(start))
        for _ in range(n_uni):
            out.append(self._uniform_candidate(start))
        for _ in range(n_sparse):
            out.append(self._sparse_candidate(start))
        if self._mode() in HOLD_MODES:
            for _ in range(max(1, n // 10)):
                out.append(self._hold_candidate(start))
        while len(out) < n:
            out.append(self._uniform_candidate(start))
        return out[:n]

    def _diverse_elites(self, scored):
        """Top-K spread across toggle-count buckets.

        Taking the flat top-K produces twelve near-duplicates of one
        shape; bucketing by density guarantees the pool spans sparse,
        medium and dense timing patterns.
        """
        if not scored:
            return []
        buckets = {}
        for cand, key, mx, terminal in scored:
            tc = len(cand)
            b = 0 if tc <= 1 else 1 if tc <= 4 else 2 if tc <= 8 else 3
            buckets.setdefault(b, []).append((cand, key, mx, terminal))
        out = []
        seen = set()
        per_bucket = max(1, self.ELITE_KEEP // max(1, len(buckets)))
        for b in sorted(buckets):
            for tup in buckets[b][:per_bucket]:
                out.append(tup)
                seen.add(id(tup[0]))
                if len(out) >= self.ELITE_KEEP:
                    return out
        for tup in scored:
            if len(out) >= self.ELITE_KEEP:
                break
            if id(tup[0]) not in seen:
                out.append((tup[0], tup[1], tup[2], tup[3]))
                seen.add(id(tup[0]))
        return out

    # ---- evaluation ----------------------------------------------------

    def _evaluate(self, candidate, start, snap0, initial_held):
        """Simulate ``candidate`` from ``snap0``.

        Returns ``(score, won, max_x, terminal)``.  ``score`` is the
        terminal frame (survival) plus any caller-supplied fitness, so a
        candidate that lives longer on a viable line outranks one that
        dives further and dies. ``terminal`` is kept separate from
        ``score`` because callers that need an actual frame index (e.g.
        sizing a commit window) can't use ``score`` once a fitness
        function has skewed it away from a frame count.
        """
        sim = self.sim
        restore(sim, snap0)
        held = initial_held
        prev_held = held
        cur = start
        # Candidates are spaced internally, but the first toggle can still
        # land too soon after the flip that ended the committed prefix.
        # Drop toggles that would break the dwell rule rather than let an
        # unplayable chain score.
        dwell = self.committed_dwell
        toggles = set(candidate)
        last_toggle = max(toggles) if toggles else cur
        # 60-frame tail so a candidate gets credit for coasting past its
        # last instruction.
        sim_until = last_toggle + 60
        max_x = sim.x
        stuck_x = max_x
        stuck_at = cur
        sim_update = sim.update
        extra = 0.0
        while cur < sim_until:
            if cur in toggles:
                toggles.discard(cur)
                if dwell >= self.model.min_dwell:
                    held = not held
            sim_update(held, held and not prev_held)
            dwell = 1 if held != prev_held else dwell + 1
            prev_held = held
            if not sim.alive or sim.won:
                break
            if self.fitness is not None:
                extra += self.fitness(sim)
            sx = sim.x
            if sx > max_x:
                max_x = sx
                stuck_x = sx
                stuck_at = cur
            elif not toggles and cur - stuck_at > 30 and sx <= stuck_x + 0.5:
                cur += 1
                break
            cur += 1
        won = bool(sim.won)
        terminal = cur if (sim.alive or sim.won) else cur - 1
        restore(sim, snap0)
        return terminal + extra, won, max_x, terminal

    def _commit_front(self, candidate, start, end):
        toggles = set(candidate)
        held = self.live_held()
        stop = start + max(1, int((end - start) * self.COMMIT_FRACTION))
        for f in range(start, stop):
            if f in toggles and self.committed_dwell >= self.model.min_dwell:
                held = not held
            self.commit_frame(held)
            if not self.sim.alive or self.sim.won:
                break
        return self.live_frame()

    def _commit_all(self, candidate, start):
        toggles = set(candidate)
        held = self.live_held()
        cur = start
        cap = self.horizon * 4
        while self.sim.alive and not self.sim.won:
            if cur in toggles and self.committed_dwell >= self.model.min_dwell:
                held = not held
            self.commit_frame(held)
            cur += 1
            if cur - start > cap:
                break

    # ---- driver --------------------------------------------------------

    def run(self):
        """Search until solved, cancelled, or out of budget.

        Returns ``(inputs, won)``.  ``inputs`` is the deepest committed
        chain seen, never a shallower late one.
        """
        best_inputs = list(self.inputs)
        best_x = float(self.sim.x)
        fail = self.ROLLBACK_INITIAL
        elites = []
        gens_without_progress = 0
        seed_restarts = 0
        deadline = (time.monotonic() + self.time_budget
                    if self.time_budget else None)

        for it in range(self.MAX_ITERATIONS):
            if self.progress is not None and self.progress.pump():
                break
            if deadline is not None and time.monotonic() > deadline:
                break
            if self.sim.won:
                return list(self.inputs), True
            if not self.sim.alive:
                self.rollback_to(max(0, self.live_frame() - fail))
                elites = []
                fail += self.ROLLBACK_GROWTH
                continue

            start = self.live_frame()
            snap0 = snapshot(self.sim)
            initial_held = self.live_held()
            scored = []
            winner = None
            for cand in self._population(start, elites):
                score, won, mx, terminal = self._evaluate(cand, start, snap0,
                                                           initial_held)
                if won:
                    winner = cand
                    break
                scored.append((cand, (score, mx), mx, terminal))
            if winner is not None:
                self._commit_all(winner, start)
                if self.sim.won:
                    return list(self.inputs), True
                continue

            scored.sort(key=lambda row: row[1], reverse=True)
            elites = self._diverse_elites(scored)
            if not elites:
                self.rollback_to(max(0, start - fail))
                fail += self.ROLLBACK_GROWTH
                continue

            top_cand, top_key, top_x, top_terminal = elites[0]
            self._commit_front(top_cand, start, top_terminal)

            if self.sim.x > best_x + 0.5:
                best_x = float(self.sim.x)
                best_inputs = list(self.inputs)
                fail = self.ROLLBACK_INITIAL
                gens_without_progress = 0
                self.horizon = self.HORIZON_MIN
                if self.progress is not None:
                    self.progress.note_x(best_x)
            else:
                gens_without_progress += 1
                if gens_without_progress > self.STAGNATION_GROW:
                    self.horizon = min(self.HORIZON_MAX, self.horizon + 25)
                if (gens_without_progress > self.STAGNATION_RESTART
                        and seed_restarts < self.MAX_SEED_RESTARTS):
                    # Every elite has converged to the same dead basin —
                    # a fresh RNG plus a deeper rollback is the cheapest
                    # way out.
                    self.rng = random.Random()
                    seed_restarts += 1
                    gens_without_progress = 0
                    fail += self.ROLLBACK_GROWTH * 4
                    elites = []
                self.rollback_to(max(0, self.live_frame() - fail))
                fail += self.ROLLBACK_GROWTH

            if self.progress is not None:
                self.progress.paint(
                    f"Toggle search · gen {it} · {self.live_frame()} frames")

        if self.sim.won:
            return list(self.inputs), True
        # Monotone floor: hand back the deepest chain, not the last one.
        if len(self.inputs) and self.sim.x > best_x:
            return list(self.inputs), False
        return best_inputs, False
