"""Auto-pathfinding bot — beam search that explores many parallel paths
to find one that reaches the finish.  Press L in the editor to run it;
the result is drawn as bot-path waypoints and the exact inputs are saved
for replay with K."""

import multiprocessing as _mp
import os as _os
import pickle as _pickle
import time as _time
from typing import NamedTuple

# Spawn workers re-import this module (and therefore pygame) to unpickle
# the solver entry point. Each fresh pygame import prints its support
# banner, so a parallel solve on a many-core box spams the console with
# one line per worker. The parent process has already imported pygame via
# main.py before this module is first loaded, so this setdefault is a
# no-op there; it only matters for the spawned subprocesses that haven't
# imported pygame yet.
_os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "hide")

import pygame

from .constants import (
    CELL, PLAYER_SIZE, HEIGHT, WIDTH,
    MODE_CUBE, MODE_SHIP, MODE_BALL, MODE_WAVE, MODE_UFO, MODE_SPIDER,
    HAZARD_TYPES, ORB_TYPES,
    T_END,
    C_PLAYER,
)
from .player import Player
from . import sfx
# Snapshot value tuple — every reader (_dedup_key, _restore, tests) used
# to index this by raw integer position. Naming the fields eliminates the
# class of bug where extending the tuple but forgetting to update a
# downstream positional read silently breaks dedup / restore logic. A
# NamedTuple is still a regular tuple for pickling and indexing, so the
# existing cross-process and cross-format-version compat is preserved.
class SnapVals(NamedTuple):
    x: float
    y: float
    vy: float
    on_ground: bool
    alive: bool
    won: bool
    angle: float
    grav: int
    frame: int
    mode: str
    move_speed: float
    dash_timer: int
    input_buffer: int
    teleport_cooldown: int
    target_cam_y: float
    bg_preset: int
    color_index: int
    grav_flip_grace: int
    wall_frames: int
    mirror_input_buffer: int
    size: int


# ---------------------------------------------------------------------------
# Fast simulation player with spatial grid
# ---------------------------------------------------------------------------

class _SimPlayer(Player):
    """Player subclass optimised for headless simulation.

    Uses a flat-array spatial grid for O(1) nearby_for_rect (no tuple hashing,
    no hash-table probing — just integer indexing). All physics is inherited
    unchanged from Player so the simulation matches real play frame-for-frame
    — duplicating the physics here previously caused silent drift (different
    inflate radius, missing spider branch, extra ground probe) that made
    beam-search "wins" fail on replay.
    """

    # Extra cells of padding around the initial object bounds so move-trigger
    # animations don't overrun the flat-array grid. ±50 cells = ±2500px is
    # comfortably larger than any move trigger in practice. A move that does
    # escape triggers _rebuild_grid to widen the bounds on the fly.
    _GRID_MARGIN = 50

    def __init__(self, objects, params=None):
        # Build flat-array grid BEFORE super().__init__ (which calls reset).
        self._init_grid(objects)
        # id(obj) -> obj index used by _restore to translate snap ids back
        # to live object refs. Made an instance attribute (was a module
        # global) so two _SimPlayer instances in the same process can't
        # silently trample each other's index mid-restore.
        self._obj_index = {id(o): o for o in objects}
        super().__init__(objects, params=params)

    def _init_grid(self, objects):
        """Allocate the flat array and fill it with the current objects.
        Bounds span all object positions plus _GRID_MARGIN on every side."""
        if not objects:
            self._grid_ox = 0
            self._grid_oy = 0
            self._grid_w = 1
            self._grid_h = 1
            self._grid_arr = [None]
            return
        min_x = min(o["x"] for o in objects) - self._GRID_MARGIN
        max_x = max(o["x"] for o in objects) + self._GRID_MARGIN
        min_y = min(o["y"] for o in objects) - self._GRID_MARGIN
        max_y = max(o["y"] for o in objects) + self._GRID_MARGIN
        self._grid_ox = min_x
        self._grid_oy = min_y
        self._grid_w = max_x - min_x + 1
        self._grid_h = max_y - min_y + 1
        arr = [None] * (self._grid_w * self._grid_h)
        w = self._grid_w
        for o in objects:
            idx = (o["y"] - min_y) * w + (o["x"] - min_x)
            cell = arr[idx]
            if cell is None:
                arr[idx] = [o]
            else:
                cell.append(o)
        self._grid_arr = arr

    def nearby_for_rect(self, rect, extra=2):
        # Hot path: called ~2M times per solve. Local names + no tuple hash.
        ox = self._grid_ox
        oy = self._grid_oy
        left = rect.left // CELL - extra - ox
        right = rect.right // CELL + extra - ox
        top = rect.top // CELL - extra - oy
        bottom = rect.bottom // CELL + extra - oy
        w = self._grid_w
        h = self._grid_h
        if left < 0:
            left = 0
        if top < 0:
            top = 0
        if right >= w:
            right = w - 1
        if bottom >= h:
            bottom = h - 1
        if left > right or top > bottom:
            return []
        result = []
        arr = self._grid_arr
        for gy in range(top, bottom + 1):
            base = gy * w
            for gx in range(left, right + 1):
                cell = arr[base + gx]
                if cell is not None:
                    result.extend(cell)
        return result

    def _rebuild_grid(self):
        """Rebuild grid after object positions change (move triggers).
        Re-derives bounds, so moves that escape the original margin are
        tolerated at the cost of one full rebuild."""
        self._init_grid(self.objects)

    def _step_move_animations(self):
        """Run move animations and refresh the grid when objects shift."""
        if not self.move_animations:
            return
        super()._step_move_animations()
        self._rebuild_grid()

    def update(self, input_held, input_pressed):
        """Run the inherited physics, then drop trail to keep memory bounded."""
        super().update(input_held, input_pressed)
        if self.trail:
            self.trail.clear()


# ---------------------------------------------------------------------------
# State snapshot / restore for beam search
# ---------------------------------------------------------------------------

_SNAP_KEYS = [
    'x', 'y', 'vy', 'on_ground', 'alive', 'won', 'angle', 'grav',
    'frame', 'mode', 'move_speed', 'dash_timer', 'input_buffer',
    'teleport_cooldown', 'target_cam_y', 'bg_preset',
    'color_index', '_grav_flip_grace', '_wall_frames',
    'mirror_input_buffer', 'size',
]

# Historically `_obj_index` and `_build_obj_index` lived as module globals;
# they're now held per-instance on `_SimPlayer`. `_restore` reads
# `player._obj_index`, so every caller that snapshots/restores MUST use a
# `_SimPlayer` (not a bare `Player`). `_verify_inputs` needs no build step
# because it never rewinds. The helper below is kept as a compat shim —
# external callers (and tests) can invoke it to (re)populate the index.
def _build_obj_index(player):
    player._obj_index = {id(o): o for o in player.objects}


def _snap(player):
    """Capture player state as a lightweight tuple-based snapshot.

    Layout: ``(vals, passed, anims, obj_pos, mirror, mirror_passed)`` where
    ``mirror`` is None when the player has not crossed a dual portal, or
    an 8-tuple ``(y, vy, grav, on_ground, angle, alive, mode, size)``
    mirroring `_enter_dual`'s state dict. ``mirror_passed`` is a frozenset
    of (type, x, y) keys for portals the mirror has consumed (independent
    of the main body's `passed`). Beam search MUST round-trip both or every
    restore after a dual portal silently desyncs from reality.

    Hot path: called 100k+ times per solve. Explicit attribute access beats
    ``tuple(getattr(p, k) for k in _SNAP_KEYS)`` by ~3× because we skip the
    per-key ``__getattribute__`` dispatch with a string name.
    """
    vals = SnapVals(
        player.x, player.y, player.vy, player.on_ground, player.alive,
        player.won, player.angle, player.grav, player.frame, player.mode,
        player.move_speed, player.dash_timer, player.input_buffer,
        player.teleport_cooldown, player.target_cam_y, player.bg_preset,
        player.color_index, player._grav_flip_grace, player._wall_frames,
        player.mirror_input_buffer, player.size,
    )
    passed = frozenset(player.passed)
    anims = player.move_animations
    if anims:
        anims = tuple(
            (id(a['obj']), a['sx'], a['sy'], a['ex'], a['ey'],
             a['frame'], a['duration'], a['curve'], a['curve_area'])
            for a in anims
        )
    else:
        anims = ()
    # Object positions — only track objects that have moved (have _fx/_fy).
    obj_pos_list = []
    for o in player.objects:
        if '_fx' in o or '_fy' in o:
            obj_pos_list.append((id(o), o['x'], o['y'],
                                 o.get('_fx'), o.get('_fy')))
    obj_pos = tuple(obj_pos_list)
    m = player.mirror
    if m is None:
        mirror = None
    else:
        mirror = (m["y"], m["vy"], m["grav"], m["on_ground"],
                  m.get("angle", 0.0), m["alive"],
                  m.get("mode", MODE_CUBE), m.get("size", PLAYER_SIZE))
    mirror_passed = frozenset(player.mirror_passed)
    return (vals, passed, anims, obj_pos, mirror, mirror_passed)


def _restore(player, snap):
    """Restore player state from snapshot — tuple-unpack into attributes
    rather than iterating _SNAP_KEYS with setattr (same speed-win rationale
    as _snap)."""
    # Forward-compat pad: older 4/5-tuple snapshots are never written by the
    # current _snap, but the bot_menu cache on disk might hold one from a
    # mid-upgrade run. Cheap branches that never fire in normal operation.
    n = len(snap)
    if n == 4:
        vals, passed, anims, obj_pos = snap
        mirror = None
        mirror_passed = frozenset()
    elif n == 5:
        vals, passed, anims, obj_pos, mirror = snap
        mirror_passed = frozenset()
    else:
        vals, passed, anims, obj_pos, mirror, mirror_passed = snap
    (player.x, player.y, player.vy, player.on_ground, player.alive,
     player.won, player.angle, player.grav, player.frame, player.mode,
     player.move_speed, player.dash_timer, player.input_buffer,
     player.teleport_cooldown, player.target_cam_y, player.bg_preset,
     player.color_index, player._grav_flip_grace, player._wall_frames,
     player.mirror_input_buffer, player.size) = vals
    player.passed = set(passed)
    player.mirror_passed = set(mirror_passed)
    player.trail = []
    if anims:
        obj_index = getattr(player, "_obj_index", None)
        if obj_index is None:
            player.move_animations = []
        else:
            player.move_animations = [
                {'obj': obj_index[oid], 'sx': sx, 'sy': sy, 'ex': ex, 'ey': ey,
                 'frame': fr, 'duration': dur, 'curve': crv, 'curve_area': ca}
                for oid, sx, sy, ex, ey, fr, dur, crv, ca in anims
                if oid in obj_index
            ]
    else:
        player.move_animations = []
    # Un-move any object the snap doesn't mention that has nevertheless been
    # moved since (because a move trigger fired between snap and this
    # restore — _snap only captures currently-animating objects, so it
    # misses objects whose animations fired *after* the snap was taken).
    # Without this the beam search's sibling expansions see inconsistent
    # object geometry across branches.
    ever_moved = getattr(player, "_ever_moved", None)
    need_rebuild = False
    if ever_moved:
        snap_oids = {entry[0] for entry in obj_pos} if obj_pos else ()
        for oid, o in ever_moved.items():
            if oid in snap_oids:
                continue
            ox = o.get("_orig_x")
            if ox is None:
                continue
            oy = o["_orig_y"]
            if o["x"] != ox or o["y"] != oy or "_fx" in o or "_fy" in o:
                o["x"] = ox
                o["y"] = oy
                o.pop("_fx", None)
                o.pop("_fy", None)
                need_rebuild = True
    if obj_pos:
        obj_index = getattr(player, "_obj_index", None)
        if obj_index is None:
            obj_pos = ()
        for oid, x, y, fx, fy in obj_pos:
            o = obj_index.get(oid)
            if o is None:
                continue
            o['x'], o['y'] = x, y
            if fx is not None:
                o['_fx'] = fx
            else:
                o.pop('_fx', None)
            if fy is not None:
                o['_fy'] = fy
            else:
                o.pop('_fy', None)
        need_rebuild = True
    if need_rebuild:
        player._rebuild_grid()
    if mirror is None:
        player.mirror = None
    else:
        if len(mirror) == 6:
            my, mvy, mgrav, mog, mang, malive = mirror
            mmode = MODE_CUBE
            msize = PLAYER_SIZE
        else:
            my, mvy, mgrav, mog, mang, malive, mmode, msize = mirror
        player.mirror = {
            "y": float(my), "vy": float(mvy), "grav": int(mgrav),
            "on_ground": bool(mog), "angle": float(mang),
            "alive": bool(malive),
            "mode": mmode,
            "size": int(msize),
        }


_CONTINUOUS_Y_MODES = (MODE_SHIP, MODE_WAVE, MODE_UFO)


def _dedup_key(snap):
    """Discretised state key for pruning duplicate trajectories.

    Two candidates collapsed to the same key are treated as the same
    trajectory and only the higher-scoring one survives. Finer keys keep
    more candidates alive (helps in tight corridors) at the cost of beam
    diversity; coarser keys let the beam explore more of the x axis.

    Ship/wave/UFO modes use continuous y (no ground snapping), so a coarse
    y bucket collapses meaningfully different flight paths. We use a finer
    bucket for those modes — at the cost of beam slots they save in
    cube/ball/spider where y snaps to the grid anyway.
    """
    vals = snap[0]
    # Named-field access via SnapVals — no more positional-index footguns
    # (round 3 #4 was exactly that class of bug: tuple extended, one
    # downstream index missed). Plain tuples coming off old disk caches
    # still work because NamedTuple is a tuple subclass.
    if isinstance(vals, SnapVals):
        mode = vals.mode
        y = vals.y
        vy = vals.vy
        grav = vals.grav
        on_ground = vals.on_ground
        input_buffer = vals.input_buffer
        dash_timer = vals.dash_timer
        mirror_input_buffer = vals.mirror_input_buffer
    else:
        # Legacy positional layout.
        mode = vals[9]
        y = vals[1]
        vy = vals[2]
        grav = vals[7]
        on_ground = vals[3]
        input_buffer = vals[12]
        dash_timer = vals[11]
        mirror_input_buffer = vals[19]
    if mode in _CONTINUOUS_Y_MODES:
        # Finer y/vy resolution — flight paths diverge by small amounts
        # that matter for clearing tight gaps.
        y_bucket = round(y / 3)
        vy_bucket = round(vy / 1.5)
    else:
        y_bucket = round(y / 5)
        vy_bucket = round(vy / 2)
    base = (
        y_bucket,
        vy_bucket,
        grav,
        mode,
        on_ground,
        1 if input_buffer > 0 else 0,  # matters for orbs
        1 if dash_timer > 0 else 0,
    )
    # Dual-mode discriminator: two candidates with similar player state but
    # very different mirror states are NOT the same trajectory — the
    # mirror can die independently and now carries its own mode/size that
    # change physics. Fold the mirror's discretised y/vy + alive + mode +
    # size into the key. Pre-portal candidates collapse on the same `None`
    # sentinel, so single-player levels are unaffected.
    mirror = snap[4] if len(snap) > 4 else None
    if mirror is None:
        return base + (None,)
    if len(mirror) == 6:
        my, mvy, _mgrav, _mog, _mang, malive = mirror
        mmode, msize = 0, 0
    else:
        my, mvy, _mgrav, _mog, _mang, malive, mmode, msize = mirror
    mirror_buf = 1 if mirror_input_buffer > 0 else 0
    return base + (round(my / 5), round(mvy / 2),
                   1 if malive else 0, mmode, msize,
                   _mgrav, 1 if _mog else 0, mirror_buf)


# ---------------------------------------------------------------------------
# Beam search solver
# ---------------------------------------------------------------------------


def _solve_attempt_worker(args):
    """Module-level (picklable) worker for parallel beam-search attempts.

    Runs ONE attempt headless in a subprocess and returns its raw result.
    Must be at module scope so multiprocessing's spawn context can pickle it.
    No screen / clock — workers can't drive pygame display from a subprocess;
    the parent process polls for completion and shows progress instead.
    """
    # args may be the legacy 5-tuple (objects, width, max_frames,
    # prefix_inputs, attempt_idx) or the B5 6-tuple that appends params.
    # Accepting both keeps bot_menu compatible with older pickled args.
    if len(args) == 6:
        objects, width, max_frames, prefix_inputs, attempt_idx, params = args
    else:
        objects, width, max_frames, prefix_inputs, attempt_idx = args
        params = None
    bot = AutoBot(objects, params=params)
    wp, mwp, inp, won = bot._beam_search(
        width, max_frames, None, None, attempt_idx,
        prefix_inputs=prefix_inputs)
    return wp, mwp, inp, won, attempt_idx


class AutoBot:
    """Finds a path through a level using beam search — maintains K parallel
    candidate paths, expanding each with all possible inputs and keeping the
    best K after deduplication."""

    BEAM_WIDTH = 48

    def __init__(self, objects, params=None):
        self.objects = objects
        # PhysicsParams override for per-level tunables (B5). None means
        # "use defaults" — the worker subprocesses pickle the params when
        # they pickle the AutoBot args, so overrides propagate through
        # to parallel attempts too.
        self.params = params
        # User-initiated cancellation latch — set by the progress drawing
        # paths when ESC is pressed. Every phase boundary in `solve`
        # (wider-beam fallback, gap-fill, brute-force) checks this so a
        # single ESC aborts the whole solve, not just the current step.
        self._cancelled = False
        # Precompute the finish-line x so scoring can weight final approach.
        end_xs = [o["x"] * CELL for o in objects if o["t"] == T_END]
        self._end_x = max(end_xs) if end_xs else 0
        # Precompute which cell columns contain an orb. Input pruning uses
        # this to decide "tap inputs irrelevant here" in O(1). Only orbs
        # care about input_buffer — pads, portals and triggers fire on
        # contact regardless of input state.
        self._orb_cells = set()
        for o in objects:
            if o["t"] in ORB_TYPES:
                self._orb_cells.add((o["x"], o["y"]))
        # Cheaper column-only variant for fast "is any orb within a few
        # cells of this x?" without iterating the full grid each time.
        self._orb_xs = set(c[0] for c in self._orb_cells)
        # Coin columns — used by the scoring heuristic to nudge the beam
        # toward opportunistic coin pickups (part of an "easy / clean"
        # solve is picking up the coins on the way).
        from .constants import T_COIN as _T_COIN
        self._coin_xs = set(o["x"] for o in objects if o["t"] == _T_COIN)

    # Frames of cached input we discard before resuming beam search after a
    # divergence. Gives the beam wiggle-room around the change point — without
    # it, the search would have to find an alternative on the very frame the
    # cached path died, which usually requires deviating earlier.
    _SEED_SAFETY_MARGIN = 60

    _GAP_FILL_RETRIES = 4
    _BRUTE_FORCE_FRAMES = 120
    _BRUTE_FORCE_WIDTH = 400

    def solve(self, screen=None, clock=None, max_frames=10000,
              seed_inputs=None, n_attempts=4, use_parallel=True,
              n_workers=None, fix_only=False):
        """Return (waypoints, mirror_waypoints, inputs, won).

        Phase 1: run all attempts in parallel (attempt 0 in-process for
        progress display, attempts 1-N in worker subprocesses launched
        concurrently). Phase 2: if still partial, gap-fill by replaying the
        best partial path as prefix and running progressively wider beam
        searches from the failure point. Phase 3: brute-force short stuck
        segments with very wide beam and no stagnation cutoff.

        ``fix_only`` runs a minimal repair pass: the seed is replayed, and
        if the replay still wins (the level wasn't meaningfully changed)
        we return instantly; otherwise one short beam search is launched
        from the last-alive prefix to patch the break. Wider fallback
        attempts, parallel workers, and the gap-fill + brute-force phases
        are skipped — the caller wants a quick tweak, not a full re-solve.
        Fix-only requires ``seed_inputs``; without a seed there's nothing
        to repair and the caller should use a regular solve.
        """
        was_enabled = sfx.is_enabled()
        if was_enabled:
            sfx.toggle()

        best_failed_waypoints = []
        best_failed_mirror_waypoints = []
        best_failed_inputs = []
        best_failed_x = -1.0
        waypoints = []
        mirror_waypoints = []
        inputs = []
        won = False

        n_attempts = max(1, min(8, n_attempts))
        pool = None

        try:
            prefix_inputs = None
            if seed_inputs:
                wp, mwp, won_replay, last_alive = self._verify_inputs(seed_inputs)
                if won_replay:
                    return wp, mwp, list(seed_inputs), True
                if last_alive > self._SEED_SAFETY_MARGIN:
                    cut = last_alive - self._SEED_SAFETY_MARGIN
                    prefix_inputs = list(seed_inputs[:cut])

            # Fix-only: one short repair beam from the prefix and stop —
            # no wider retries, no gap-fill, no brute-force. Matches the
            # caller's intent to "tweak, don't re-solve".
            if fix_only:
                if not seed_inputs:
                    # Nothing to repair against — refuse rather than do a
                    # silent full solve (the caller asked explicitly for
                    # a fix-only pass).
                    return [], [], [], False
                waypoints, mirror_waypoints, inputs, won = self._beam_search(
                    self.BEAM_WIDTH, max_frames, screen, clock, 0,
                    prefix_inputs=prefix_inputs,
                    status_text="Fix-only: repairing seed")
                if won:
                    return waypoints, mirror_waypoints, inputs, True
                return waypoints, mirror_waypoints, inputs, False

            widths = []
            w = self.BEAM_WIDTH
            for _ in range(n_attempts):
                widths.append(w)
                w *= 2

            def _update_best(wp, mwp, inp):
                nonlocal best_failed_x, best_failed_waypoints
                nonlocal best_failed_mirror_waypoints, best_failed_inputs
                if wp:
                    fx = max((p[0] for p in wp), default=-1.0)
                    if fx > best_failed_x:
                        best_failed_x = fx
                        best_failed_waypoints = wp
                        best_failed_mirror_waypoints = mwp
                        best_failed_inputs = inp

            # === Phase 1: Initial search =============================
            # One pass from the start at default beam width. Quick, gets
            # as far as the narrow beam can; whatever it finds seeds
            # every later phase. We also fast-path a width-16 pre-pass
            # for trivial levels — solves a flat corridor in ~100 ms
            # without the attempt-0 overhead.
            _FAST_WIDTH = 16
            if not prefix_inputs and _FAST_WIDTH < self.BEAM_WIDTH:
                fast_wp, fast_mwp, fast_inp, fast_won = self._beam_search(
                    _FAST_WIDTH, max_frames, screen, clock, 0,
                    prefix_inputs=None,
                    status_text="Phase 1: Initial search (fast)")
                if fast_won:
                    return fast_wp, fast_mwp, fast_inp, True
                if self._cancelled:
                    return fast_wp, fast_mwp, fast_inp, False
                if fast_inp:
                    _update_best(fast_wp, fast_mwp, fast_inp)

            waypoints, mirror_waypoints, inputs, won = self._beam_search(
                widths[0], max_frames, screen, clock, 0,
                prefix_inputs=prefix_inputs,
                status_text="Phase 1: Initial search")
            if not won:
                _update_best(waypoints, mirror_waypoints, inputs)
            if self._cancelled:
                return waypoints, mirror_waypoints, inputs, False

            # === Phase 2: Gap fill ===================================
            # Before spinning up any parallel workers, try to extend the
            # best partial we have using retries with progressively
            # wider beams. Brute force is held back for Phase 4 so the
            # phase boundaries stay clean.
            if not won and best_failed_inputs and not self._cancelled:
                gf_wp, gf_mwp, gf_inp, gf_won = self._gap_fill(
                    best_failed_inputs, screen, clock, max_frames,
                    allow_brute=False)
                if gf_won:
                    waypoints, mirror_waypoints, inputs, won = \
                        gf_wp, gf_mwp, gf_inp, True
                elif gf_inp:
                    _update_best(gf_wp, gf_mwp, gf_inp)
            if self._cancelled:
                return waypoints, mirror_waypoints, inputs, won

            # === Phase 3: Parallel wider beam ========================
            # N - 1 wider-beam attempts running in separate processes
            # (plus a sequential fallback on platforms where spawn is
            # restricted). Meant to unstick gaps that Phase 2's narrow
            # retries couldn't bridge.
            pool = None
            async_results = []
            parallel_launched = False
            if not won and n_attempts > 1 and use_parallel:
                try:
                    ctx = _mp.get_context("spawn")
                    nw = n_workers if n_workers else min(
                        n_attempts - 1, max(1, _os.cpu_count() or 1))
                    pool = ctx.Pool(processes=nw)
                    for attempt in range(1, n_attempts):
                        last = (attempt == n_attempts - 1)
                        frames = int(max_frames * 1.5) if last else max_frames
                        args = (self.objects, widths[attempt], frames,
                                None, attempt, self.params)
                        async_results.append(
                            pool.apply_async(_solve_attempt_worker, (args,)))
                    parallel_launched = True
                except (OSError, RuntimeError, _pickle.PickleError):
                    pool = None
                    async_results = []

            if not won and pool and parallel_launched:
                par_wp, par_mwp, par_in, par_won, par_failed = \
                    self._solve_attempts_parallel_wait(
                        async_results, screen, clock,
                        n_workers=len(async_results))
                if par_won:
                    waypoints, mirror_waypoints, inputs, won = \
                        par_wp, par_mwp, par_in, True
                elif par_failed is not None:
                    fwp, fmwp, fin, fx = par_failed
                    if fx > best_failed_x:
                        best_failed_x = fx
                        best_failed_waypoints = fwp
                        best_failed_mirror_waypoints = fmwp
                        best_failed_inputs = fin

            if pool:
                pool.terminate()
                pool.join()
                pool = None

            # Sequential fallback: if the parallel pool never launched
            # (pickling failure, etc.) we still want wider retries.
            if (not won and not parallel_launched and n_attempts > 1
                    and not self._cancelled):
                for attempt in range(1, n_attempts):
                    if self._cancelled:
                        break
                    last = (attempt == n_attempts - 1)
                    frames = int(max_frames * 1.5) if last else max_frames
                    waypoints, mirror_waypoints, inputs, won = \
                        self._beam_search(
                            widths[attempt], frames, screen, clock, attempt,
                            prefix_inputs=None,
                            status_text="Phase 3: Parallel search (sequential)")
                    if won:
                        break
                    _update_best(waypoints, mirror_waypoints, inputs)

            if self._cancelled:
                return waypoints, mirror_waypoints, inputs, won

            # === Phase 4: Brute force ================================
            # Very wide beam on the short segment where all prior
            # phases stalled. Exits as soon as any candidate wins.
            if not won and best_failed_inputs and not self._cancelled:
                bf_wp, bf_mwp, bf_inp, bf_won = self._gap_fill(
                    best_failed_inputs, screen, clock, max_frames,
                    allow_brute=True)
                if bf_won:
                    waypoints, mirror_waypoints, inputs, won = \
                        bf_wp, bf_mwp, bf_inp, True
                elif bf_inp:
                    _update_best(bf_wp, bf_mwp, bf_inp)

            if not won and best_failed_waypoints:
                waypoints = best_failed_waypoints
                mirror_waypoints = best_failed_mirror_waypoints
                inputs = best_failed_inputs
        finally:
            if pool:
                pool.terminate()
                pool.join()
            if was_enabled:
                sfx.toggle()

        return waypoints, mirror_waypoints, inputs, won

    def _gap_fill(self, partial_inputs, screen, clock, max_frames,
                  allow_brute=True):
        """Extend a partial path by replaying it as prefix and running wider
        beam searches from the failure point. With ``allow_brute=False``
        the brute-force fallback is skipped so the caller can run brute
        force as a distinct phase after parallel search has had a chance
        to unstick things."""
        best_inputs = list(partial_inputs)
        best_wp = []
        best_mwp = []
        prev_alive = -1

        for retry in range(self._GAP_FILL_RETRIES):
            if self._cancelled:
                break
            _, _, won_check, last_alive = self._verify_inputs(best_inputs)
            if won_check:
                wp, mwp, verified = self._replay_for_waypoints(best_inputs)
                return wp, mwp, best_inputs, verified

            if last_alive <= self._SEED_SAFETY_MARGIN:
                break

            if last_alive == prev_alive:
                if not allow_brute:
                    # Same alive-x two retries in a row and brute force
                    # isn't our job — bail so the caller runs the next
                    # phase (parallel / brute).
                    break
                bf_wp, bf_mwp, bf_inp, bf_won = self._brute_force_segment(
                    best_inputs[:last_alive - self._SEED_SAFETY_MARGIN],
                    self._BRUTE_FORCE_FRAMES, screen, clock, retry)
                if bf_won:
                    return bf_wp, bf_mwp, bf_inp, True
                if bf_inp and len(bf_inp) > len(best_inputs):
                    best_inputs = bf_inp
                    best_wp = bf_wp
                    best_mwp = bf_mwp
                else:
                    break
            else:
                prev_alive = last_alive

            cut = last_alive - self._SEED_SAFETY_MARGIN
            prefix = list(best_inputs[:cut])
            width = self.BEAM_WIDTH * (2 ** (retry + 2))
            status = f"Phase 2: Gap fill (retry {retry + 1}/{self._GAP_FILL_RETRIES})"

            wp, mwp, inp, gap_won = self._beam_search(
                width, max_frames, screen, clock, 0,
                prefix_inputs=prefix, status_text=status)

            if gap_won:
                return wp, mwp, inp, True
            if inp and len(inp) > len(best_inputs):
                best_inputs = inp
                best_wp = wp
                best_mwp = mwp

        if best_wp:
            return best_wp, best_mwp, best_inputs, False
        wp, mwp, _ = self._replay_for_waypoints(best_inputs)
        return wp, mwp, best_inputs, False

    def _brute_force_segment(self, prefix_inputs, n_frames, screen, clock,
                             retry_idx=0):
        """Very wide beam for a short window to power through stuck segments."""
        status = f"Phase 4: Brute force"
        return self._beam_search(
            self._BRUTE_FORCE_WIDTH,
            len(prefix_inputs) + n_frames,
            screen, clock, 0,
            prefix_inputs=prefix_inputs,
            status_text=status)

    def _verify_inputs(self, inputs):
        """Replay ``inputs`` against a fresh sim of the current level.

        Returns ``(waypoints, mirror_waypoints, won, last_alive_frame)``.
        ``last_alive_frame`` is the highest index in ``inputs`` for which
        the player was still alive after that frame, or -1 if the player
        died on frame 0. ``mirror_waypoints`` is empty unless a dual portal
        was active during the replay.
        """
        work_objects = [dict(o) for o in self.objects]
        player = _SimPlayer(work_objects, params=self.params)
        player.trail = []

        size = getattr(player, "size", PLAYER_SIZE)
        waypoints = [(player.x + size / 2, player.y + size / 2)]
        mirror_waypoints = []
        last_alive = -1
        for i, (held, pressed) in enumerate(inputs):
            player.update(held, pressed)
            size = getattr(player, "size", PLAYER_SIZE)
            sample = i % 4 == 0 or not player.alive or player.won
            if sample:
                waypoints.append((
                    player.x + size / 2,
                    player.y + size / 2,
                ))
                if player.mirror is not None and player.mirror.get("alive"):
                    msize = player.mirror.get("size", PLAYER_SIZE)
                    mirror_waypoints.append((
                        player.x + size / 2,
                        player.mirror["y"] + msize / 2,
                    ))
            if player.alive:
                last_alive = i
            if not player.alive or player.won:
                break
        return waypoints, mirror_waypoints, player.won, last_alive

    def _beam_search(self, beam_width, max_frames, screen, clock, attempt,
                     prefix_inputs=None, status_text=""):
        """Core beam search. Returns (waypoints, inputs, won).

        If ``prefix_inputs`` is provided, the search first replays those
        inputs as a single-candidate "beam of one" so the cached prefix
        carries over into history with parent_idx=0. The beam then expands
        normally from the player's post-prefix state. Reconstruction walks
        the parent chain back through the prefix automatically because every
        prefix frame's parent is 0.
        """
        work_objects = [dict(o) for o in self.objects]
        player = _SimPlayer(work_objects, params=self.params)
        player.trail = []

        # Snapshot field indices (from _SNAP_KEYS):
        # 0=x, 1=y, 2=vy, 3=on_ground, 4=alive, 5=won, 7=grav, 9=mode
        _X = 0; _ALIVE = 4; _MODE = 9

        # Input history: for each frame, store list parallel to beam of (parent_idx, held, pressed)
        history = []

        won = False
        won_idx = -1
        total_frames = 0

        # Replay the seed prefix as a single-candidate beam. The prefix
        # should already be truncated to a known-safe length by the caller,
        # so deaths here are surprising — bail out if one happens so the
        # outer retry loop can fall back to a from-scratch attempt.
        if prefix_inputs:
            for held, pressed in prefix_inputs:
                player.update(held, pressed)
                history.append([(0, held, pressed)])
                total_frames += 1
                if player.won:
                    inputs = self._reconstruct(history, 0)
                    waypoints, mwp, verified_won = self._replay_for_waypoints(inputs)
                    return waypoints, mwp, inputs, verified_won
                if not player.alive:
                    return [], [], [], False

        # Initial state
        init_snap = _snap(player)

        # Beam: list of (snap, parent_index_in_prev_beam, x_progress)
        beam = [(init_snap, -1, player.x)]

        # Stuck detection: track best alive x and bail if it doesn't grow.
        # The player normally advances ~5px/frame, so a few hundred frames
        # of zero forward motion means every alive candidate is wedged
        # against a wall or stuck looping a hazard. Bail out and let the
        # next (wider-beam) attempt try, instead of churning max_frames.
        #
        # The actual limit is adaptive: when many candidates are still
        # alive, give the beam more patience (it's still exploring); when
        # alive count crashes, abandon faster (the route is probably dead).
        best_alive_x = player.x
        stagnant_frames = 0
        STAGNATION_BASE = 220
        STAGNATION_THIN_BEAM = 90  # used when <= 4 alive candidates left

        # Snap field indices (locals to avoid attribute lookups in the loop)
        _ON_GROUND = 3
        _MIRROR = 4  # snap[4] is the mirror tuple or None
        _TAP_PRUNABLE_MODES = (MODE_CUBE, MODE_BALL, MODE_SPIDER)
        _HOLD_SENSITIVE_MODES = (MODE_SHIP, MODE_WAVE, MODE_UFO)
        orb_xs = self._orb_xs

        # Cell radius around the candidate where an orb can still be
        # activated by a tap made RIGHT NOW. input_buffer=6 frames, max
        # move_speed ~10px/frame, so 60px of forward travel = ~1.2 cells.
        # Round up to 2 for safety margin; add 1 more for the player's own
        # width straddling two cells. Total: 3 cells forward, 1 back.
        _TAP_LOOKAHEAD = 3
        _TAP_LOOKBACK = 1

        def _has_orb_near_x(gx):
            """True if any orb sits in the window of cell columns the
            player can reach before input_buffer expires."""
            for dx in range(-_TAP_LOOKBACK, _TAP_LOOKAHEAD + 1):
                if (gx + dx) in orb_xs:
                    return True
            return False

        while total_frames < max_frames and not won:
            any_dual = any(
                b[0][4] is not None
                for b in beam if b[0][0][_ALIVE]
            )
            effective_width = beam_width * 2 if any_dual else beam_width

            # Per-candidate option selection happens in the loop below —
            # sampling the option list from beam[0]'s mode alone dropped
            # expansions on mixed-mode beams (e.g. wave beam[0] stripped
            # (False, True) from every cube candidate in the same beam).
            _opts_dual = [(False, False), (True, True),
                          (False, True), (True, False)]
            _opts_tappable = [(False, False), (True, True), (False, True)]
            _opts_hold = [(False, False), (True, True)]

            # Expand all beam entries with all input options
            candidates = []
            # How much passed-object credit was in the parent beam entries —
            # used to reward newly-consumed orbs / portals this frame.
            parent_passed = [len(b[0][1]) for b in beam]

            for beam_idx, (snap, _, _) in enumerate(beam):
                parent_pcount = parent_passed[beam_idx]
                # Per-candidate input pruning (safe — no missed paths).
                # When the candidate is in cube/ball/spider mid-air AND
                # there's no orb close enough to catch a tap (buffer decays
                # in ~6 frames), (True, True) and (False, True) produce
                # physics identical to (False, False); they differ only in
                # input_buffer which has no target to activate before it
                # expires. Skip them. Mirror-check: if the mirror body is
                # in a hold-sensitive mode (ship/wave/ufo) we can't prune,
                # since input_held still steers the mirror.
                vals = snap[0]
                cand_mode = vals[_MODE]
                if any_dual:
                    options = _opts_dual
                elif cand_mode in (MODE_BALL, MODE_UFO, MODE_CUBE, MODE_SPIDER):
                    options = _opts_tappable
                else:
                    options = _opts_hold
                if (cand_mode in _TAP_PRUNABLE_MODES
                        and not vals[_ON_GROUND]):
                    mirror_forbids = False
                    m_snap = snap[_MIRROR]
                    if m_snap is not None and len(m_snap) >= 6:
                        if m_snap[5]:  # mirror alive — any mode needs input
                            mirror_forbids = True
                    if not mirror_forbids:
                        gx = int(vals[0]) // CELL
                        if not _has_orb_near_x(gx):
                            options = [(False, False)]
                for held, pressed in options:
                    _restore(player, snap)
                    player.update(held, pressed)
                    new_snap = _snap(player)

                    if player.won:
                        history.append([(beam_idx, held, pressed)])
                        won = True
                        won_idx = 0
                        candidates = [(new_snap, beam_idx, player.x, held, pressed)]
                        break
                    if not player.alive:
                        candidates.append((new_snap, beam_idx, player.x - 1e6, held, pressed))
                    else:
                        # Composite score (higher = preferred). Tuned
                        # toward "easiest / cleanest" solves:
                        #  • x-progress still dominates (raw pixels).
                        #  • clearance_bonus is weighted higher so the
                        #    bot prefers paths that stay well clear of
                        #    spikes/saws — the "easy" path a human would
                        #    pick.
                        #  • tap-count penalty in tap-prunable modes so
                        #    the bot picks hold-heavy (fewer input
                        #    changes) solutions when they both win.
                        #  • passed-count bonus rewards consuming orbs /
                        #    pads / portals / coins.
                        #  • velocity bonus rewards forward momentum.
                        #  • end-proximity pull commits the beam to the
                        #    final approach.
                        score = player.x
                        score += self._clearance_bonus(player) * 0.05
                        newly_passed = len(player.passed) - parent_pcount
                        if newly_passed > 0:
                            score += newly_passed * 3.0
                        # Prefer fewer taps — every "pressed" frame in a
                        # tap-prunable mode costs a small amount. Cube
                        # on-ground jump is unavoidable; flag it with a
                        # smaller penalty so it doesn't get pruned.
                        cand_mode = vals[_MODE]
                        if pressed:
                            if cand_mode in _TAP_PRUNABLE_MODES:
                                score -= 0.35
                            else:
                                score -= 0.1
                        # Coin attraction — when a coin is within a
                        # short window forward of the player, nudge the
                        # beam toward it so the "easy" solve tends to
                        # collect coins opportunistically.
                        gx_now = int(player.x) // CELL
                        for dcx in range(0, 4):
                            if (gx_now + dcx) in getattr(
                                    self, "_coin_xs", ()):
                                score += 0.3
                                break
                        # Forward momentum: getattr because move_speed exists
                        # on Player but only post-init.
                        score += getattr(player, "move_speed", 5) * 0.4
                        if player.mirror is not None and player.mirror["alive"]:
                            score += 3.0
                            score += self._mirror_clearance_bonus(player) * 0.005
                        if self._end_x > 0:
                            dist_to_end = max(0.0, self._end_x - player.x)
                            if dist_to_end < 200:
                                score += (200 - dist_to_end) * 0.5
                            else:
                                score += max(0.0, 200.0 - dist_to_end * 0.02)
                        candidates.append((new_snap, beam_idx, score, held, pressed))

                if won:
                    break

            if won:
                break

            # Deduplicate: group by state key, keep best score per group
            by_key = {}
            lead_x = beam[0][0][0][_X]
            for c in candidates:
                snap, parent_idx, score, held, pressed = c
                # Skip dead candidates far behind the leader
                if not snap[0][_ALIVE] and snap[0][_X] < lead_x - 500:
                    continue
                key = _dedup_key(snap)
                if key not in by_key or score > by_key[key][2]:
                    by_key[key] = c

            unique = sorted(by_key.values(), key=lambda c: c[2], reverse=True)
            unique = unique[:effective_width]

            if not unique:
                break

            # Early-stop when every surviving candidate is dead. Continuing
            # would just call player.update() on dead snaps that no-op out,
            # burning frames until max_frames with no chance of recovery.
            alive_in_beam = [c for c in unique if c[0][0][_ALIVE]]
            if not alive_in_beam:
                break

            # Stuck detection: if the best alive x hasn't grown in a while,
            # we're not going to find a path from here — abandon this attempt.
            best_x_now = max(c[0][0][_X] for c in alive_in_beam)
            if best_x_now > best_alive_x + 0.5:
                best_alive_x = best_x_now
                stagnant_frames = 0
            else:
                stagnant_frames += 1
                stagnation_limit = (
                    STAGNATION_THIN_BEAM
                    if len(alive_in_beam) <= 4
                    else (STAGNATION_BASE * 2 if any_dual else STAGNATION_BASE)
                )
                if stagnant_frames > stagnation_limit:
                    break

            frame_history = []
            new_beam = []
            for i, (snap, parent_idx, score, held, pressed) in enumerate(unique):
                frame_history.append((parent_idx, held, pressed))
                new_beam.append((snap, i, score))

            history.append(frame_history)
            beam = new_beam
            total_frames += 1

            if screen is not None and total_frames % 80 == 0:
                alive_xs = [b[0][0][_X] for b in beam if b[0][0][_ALIVE]]
                best_x = max(alive_xs) if alive_xs else max(b[0][0][_X] for b in beam)
                cancelled = self._draw_progress(
                    screen, clock, total_frames, best_x, max_frames,
                    len(beam), effective_width, attempt,
                    status_text=status_text, any_dual=any_dual)
                if cancelled:
                    break

        # Reconstruct input sequence
        if won and history:
            inputs = self._reconstruct(history, won_idx if won_idx >= 0 else 0)
        elif history:
            # Even if not won, return the best path we found
            inputs = self._reconstruct(history, 0)
        else:
            inputs = []

        # Build waypoints by replaying inputs with a fresh player
        waypoints, mirror_waypoints, verified_won = self._replay_for_waypoints(inputs)

        return waypoints, mirror_waypoints, inputs, verified_won

    def _reconstruct(self, history, final_idx):
        """Walk parent chain backwards to build input sequence."""
        inputs = []
        idx = final_idx
        for frame in range(len(history) - 1, -1, -1):
            parent_idx, held, pressed = history[frame][idx]
            inputs.append((held, pressed))
            idx = parent_idx
        inputs.reverse()
        return inputs

    def _replay_for_waypoints(self, inputs):
        """Replay the solved inputs with a real Player to get waypoints
        and verify the solution works (including move triggers).

        Returns ``(waypoints, mirror_waypoints, won)``. Mirror waypoints are
        only sampled while the dual mirror is active, so the list may be
        empty for levels that never use a dual portal.

        Callers (solve / _solve_attempt_worker) are responsible for muting
        sfx before entering the solve loop — this method does not toggle sfx
        itself, which avoids corrupting prefs.json from subprocess workers.
        """
        work_objects = [dict(o) for o in self.objects]
        player = Player(work_objects)
        player.trail = []

        size = getattr(player, "size", PLAYER_SIZE)
        waypoints = [(player.x + size / 2, player.y + size / 2)]
        mirror_waypoints = []
        for i, (held, pressed) in enumerate(inputs):
            player.update(held, pressed)
            size = getattr(player, "size", PLAYER_SIZE)
            sample = i % 4 == 0 or not player.alive or player.won
            if sample:
                waypoints.append((
                    player.x + size / 2,
                    player.y + size / 2,
                ))
                if player.mirror is not None and player.mirror.get("alive"):
                    msize = player.mirror.get("size", PLAYER_SIZE)
                    mirror_waypoints.append((
                        player.x + size / 2,
                        player.mirror["y"] + msize / 2,
                    ))
            if not player.alive or player.won:
                break

        return waypoints, mirror_waypoints, player.won

    def _solve_attempts_parallel(self, attempts_args, screen, clock,
                                    n_workers=None):
        """Run beam-search attempts concurrently in worker subprocesses.

        ``attempts_args`` is a list of tuples shaped like the input to
        ``_solve_attempt_worker``. Returns
        ``(wp, mwp, inputs, won, best_failed)`` where ``best_failed`` is
        ``None`` if no attempt produced a non-empty trajectory or
        ``(wp, mwp, inputs, farthest_x)`` for the deepest failing run.

        Uses the 'spawn' multiprocessing context so worker state is clean
        — the parent process may already have pygame / SDL initialized,
        which doesn't fork cleanly. The first worker to return ``won=True``
        causes the pool to terminate immediately; other in-flight workers
        are killed.

        While workers run the parent polls for completion every ~50ms,
        repainting the progress display and watching for ESC / QUIT so the
        user can still cancel a long solve.
        """
        ctx = _mp.get_context("spawn")
        if n_workers is None:
            n_workers = min(len(attempts_args),
                            max(1, _os.cpu_count() or 1))
        else:
            n_workers = max(1, min(n_workers, len(attempts_args)))
        pool = ctx.Pool(processes=n_workers)
        try:
            pending_results = [
                pool.apply_async(_solve_attempt_worker, (a,))
                for a in attempts_args
            ]
            pending = list(range(len(pending_results)))

            won_tuple = None             # (wp, mwp, inp, True)
            best_failed = None           # (wp, mwp, inp, x)
            cancelled = False
            last_paint = 0.0
            paint_interval = 0.2

            while pending and won_tuple is None and not cancelled:
                ready_now = [i for i in pending
                             if pending_results[i].ready()]
                for i in ready_now:
                    pending.remove(i)
                    try:
                        wp, mwp, inp, won, _aidx = pending_results[i].get()
                    except Exception:
                        continue
                    if won:
                        won_tuple = (wp, mwp, inp, True)
                        break
                    if wp:
                        farthest = max((p[0] for p in wp), default=-1.0)
                        if best_failed is None or farthest > best_failed[3]:
                            best_failed = (wp, mwp, inp, farthest)
                if won_tuple is not None:
                    break
                if not pending:
                    break

                # Paint & poll ESC. Only when we have a screen — otherwise
                # (tests / headless tools) just sleep briefly.
                if screen is not None:
                    now = _time.monotonic()
                    if now - last_paint >= paint_interval:
                        last_paint = now
                        if self._draw_parallel_progress(
                                screen, clock,
                                len(pending), n_workers):
                            cancelled = True
                            break
                    else:
                        _time.sleep(0.02)
                else:
                    _time.sleep(0.05)

            if won_tuple is not None:
                wp, mwp, inp, _ = won_tuple
                return wp, mwp, inp, True, best_failed
            if cancelled:
                return [], [], [], False, best_failed
            return [], [], [], False, best_failed
        finally:
            # terminate() sends SIGTERM to workers still running the beam
            # search; join() waits for them to exit before returning.
            pool.terminate()
            pool.join()

    def _solve_attempts_parallel_wait(self, async_results, screen, clock,
                                        n_workers=1):
        """Wait on already-launched async results, polling for completion.
        Returns same shape as _solve_attempts_parallel."""
        pending = list(range(len(async_results)))
        won_tuple = None
        best_failed = None
        cancelled = False
        last_paint = 0.0
        paint_interval = 0.2

        while pending and won_tuple is None and not cancelled:
            ready_now = [i for i in pending if async_results[i].ready()]
            for i in ready_now:
                pending.remove(i)
                try:
                    wp, mwp, inp, won, _aidx = async_results[i].get()
                except Exception:
                    continue
                if won:
                    won_tuple = (wp, mwp, inp, True)
                    break
                if wp:
                    farthest = max((p[0] for p in wp), default=-1.0)
                    if best_failed is None or farthest > best_failed[3]:
                        best_failed = (wp, mwp, inp, farthest)
            if won_tuple is not None:
                break
            if not pending:
                break
            if screen is not None:
                now = _time.monotonic()
                if now - last_paint >= paint_interval:
                    last_paint = now
                    if self._draw_parallel_progress(
                            screen, clock, len(pending), n_workers):
                        cancelled = True
                        break
                else:
                    _time.sleep(0.02)
            else:
                _time.sleep(0.05)

        if won_tuple is not None:
            wp, mwp, inp, _ = won_tuple
            return wp, mwp, inp, True, best_failed
        if cancelled:
            return [], [], [], False, best_failed
        return [], [], [], False, best_failed

    def _draw_parallel_progress(self, screen, clock, n_pending, n_workers):
        """Minimal progress display for the parallel phase. Returns True
        if the user pressed ESC (cancel)."""
        from .graphics import txt
        completed = n_workers - n_pending
        screen.fill((10, 8, 24))
        txt(screen, "AUTO-BOT  PARALLEL BEAM SEARCH",
            WIDTH // 2, HEIGHT // 2 - 60, 28, (255, 180, 60), True)
        txt(screen,
            f"{completed}/{n_workers} attempts done  |  {n_pending} running",
            WIDTH // 2, HEIGHT // 2 - 10, 18, (180, 180, 200), True)
        # Simple running-bar: each worker shown as a cell.
        bw = 400
        bx = WIDTH // 2 - bw // 2
        by = HEIGHT // 2 + 30
        pygame.draw.rect(screen, (40, 40, 60), (bx, by, bw, 22),
                         border_radius=6)
        if n_workers > 0:
            cell_w = bw // n_workers
            for i in range(n_workers):
                color = ((90, 220, 120) if i < completed
                         else (255, 180, 60))
                pygame.draw.rect(
                    screen, color,
                    (bx + i * cell_w + 2, by + 2,
                     cell_w - 4, 18),
                    border_radius=4)
        txt(screen, "Escape to cancel",
            WIDTH // 2, HEIGHT // 2 + 100, 16, (140, 140, 155), True)
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

    def _clearance_bonus(self, player):
        """Small bonus for distance from hazards, used as tiebreaker."""
        px, py = player.x, player.y
        min_d = 999.0
        for o in player.nearby_for_rect(
            pygame.Rect(int(px) - CELL, int(py) - CELL * 3, CELL * 5, CELL * 7)
        ):
            if o['t'] not in HAZARD_TYPES:
                continue
            dx = o['x'] * CELL - px
            dy = o['y'] * CELL - py
            d = (dx * dx + dy * dy) ** 0.5
            if d < min_d:
                min_d = d
        return min(min_d, 300.0)

    def _mirror_clearance_bonus(self, player):
        m = player.mirror
        if m is None or not m["alive"]:
            return 0.0
        mx, my = player.x, m["y"]
        min_d = 999.0
        for o in player.nearby_for_rect(
            pygame.Rect(int(mx) - CELL, int(my) - CELL * 3, CELL * 5, CELL * 7)
        ):
            if o['t'] not in HAZARD_TYPES:
                continue
            dx = o['x'] * CELL - mx
            dy = o['y'] * CELL - my
            d = (dx * dx + dy * dy) ** 0.5
            if d < min_d:
                min_d = d
        return min(min_d, 300.0)

    def _draw_progress(self, screen, clock, frame, best_x, max_frames,
                       n_alive, beam_width, attempt, status_text="",
                       any_dual=False):
        """Progress screen for every solver phase. Minimalist by design —
        the user only cares about the phase, where the solver currently
        is (X), and how much of the level is left. Frame count / dual
        marker / beam count were dropped because they confused more than
        they informed."""
        from .graphics import txt
        level_pct = 0
        if self._end_x > 0:
            level_pct = min(100, max(0, int(best_x / self._end_x * 100)))
        screen.fill((10, 8, 24))
        # Title (same as before) — centered a bit higher so the phase
        # line sits just under it.
        txt(screen, "AUTO-BOT SEARCH", WIDTH // 2, HEIGHT // 2 - 86,
            32, (255, 180, 60), True)
        # Phase label — smaller, directly below the title.
        if status_text:
            txt(screen, status_text, WIDTH // 2, HEIGHT // 2 - 52,
                16, (180, 220, 255), True)
        # Just the current X position. No frame count, no beam counts,
        # no dual marker.
        txt(screen, f"X {int(best_x)}",
            WIDTH // 2, HEIGHT // 2 - 18, 18, (180, 180, 200), True)
        # Progress bar — always level % (distance toward the finish
        # line), never frame count. Single bar, no secondary.
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
                             (bx, by, max(1, int(bw * level_pct / 100)), bh),
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
