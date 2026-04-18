"""Auto-pathfinding bot — beam search that explores many parallel paths
to find one that reaches the finish.  Press L in the editor to run it;
the result is drawn as bot-path waypoints and the exact inputs are saved
for replay with K."""

import multiprocessing as _mp
import os as _os
import time as _time

import pygame

from constants import (
    CELL, PLAYER_SIZE, HEIGHT, WIDTH,
    MODE_CUBE, MODE_SHIP, MODE_BALL, MODE_WAVE, MODE_UFO, MODE_SPIDER,
    HAZARD_TYPES, ORB_TYPES,
    T_END,
    C_PLAYER,
)
from player import Player
import sfx


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

    def __init__(self, objects):
        # Build flat-array grid BEFORE super().__init__ (which calls reset).
        self._init_grid(objects)
        super().__init__(objects)

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
    'mirror_input_buffer',
]

# Pre-built index for fast object position restore
_obj_index = None  # dict: id(obj) -> obj, built once per solve


def _build_obj_index(player):
    global _obj_index
    _obj_index = {id(o): o for o in player.objects}


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
    vals = (
        player.x, player.y, player.vy, player.on_ground, player.alive,
        player.won, player.angle, player.grav, player.frame, player.mode,
        player.move_speed, player.dash_timer, player.input_buffer,
        player.teleport_cooldown, player.target_cam_y, player.bg_preset,
        player.color_index, player._grav_flip_grace, player._wall_frames,
        player.mirror_input_buffer,
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
     player.mirror_input_buffer) = vals
    player.passed = set(passed)
    player.mirror_passed = set(mirror_passed)
    player.trail = []
    if anims:
        obj_index = _obj_index
        player.move_animations = [
            {'obj': obj_index[oid], 'sx': sx, 'sy': sy, 'ex': ex, 'ey': ey,
             'frame': fr, 'duration': dur, 'curve': crv, 'curve_area': ca}
            for oid, sx, sy, ex, ey, fr, dur, crv, ca in anims
        ]
    else:
        player.move_animations = []
    if obj_pos:
        obj_index = _obj_index
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
    # _SNAP_KEYS indices: 1=y, 2=vy, 3=on_ground, 7=grav, 9=mode,
    #                    11=dash_timer, 12=input_buffer, 13=teleport_cooldown
    mode = vals[9]
    if mode in _CONTINUOUS_Y_MODES:
        # Finer y/vy resolution — flight paths diverge by small amounts
        # that matter for clearing tight gaps.
        y_bucket = round(vals[1] / 3)
        vy_bucket = round(vals[2] / 1.5)
    else:
        y_bucket = round(vals[1] / 5)
        vy_bucket = round(vals[2] / 2)
    base = (
        y_bucket,
        vy_bucket,
        vals[7],                  # grav
        mode,
        vals[3],                  # on_ground
        1 if vals[12] > 0 else 0, # input_buffer boolean (matters for orbs)
        1 if vals[11] > 0 else 0, # dash_timer boolean
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
    return base + (round(my / 5), round(mvy / 2),
                   1 if malive else 0, mmode, msize)


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
    objects, width, max_frames, prefix_inputs, attempt_idx = args
    bot = AutoBot(objects)
    wp, mwp, inp, won = bot._beam_search(
        width, max_frames, None, None, attempt_idx,
        prefix_inputs=prefix_inputs)
    return wp, mwp, inp, won, attempt_idx


class AutoBot:
    """Finds a path through a level using beam search — maintains K parallel
    candidate paths, expanding each with all possible inputs and keeping the
    best K after deduplication."""

    BEAM_WIDTH = 48

    def __init__(self, objects):
        self.objects = objects
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

    # Frames of cached input we discard before resuming beam search after a
    # divergence. Gives the beam wiggle-room around the change point — without
    # it, the search would have to find an alternative on the very frame the
    # cached path died, which usually requires deviating earlier.
    _SEED_SAFETY_MARGIN = 60

    def solve(self, screen=None, clock=None, max_frames=10000,
              seed_inputs=None):
        """Return (waypoints, mirror_waypoints, inputs, won).
        - waypoints: list of (x, y) world-pixel coords for the bot path
        - mirror_waypoints: parallel list for the dual mirror, empty if the
          level never enters dual mode
        - inputs: list of (held, pressed) per physics frame for exact replay
        - won: True if solution reaches the end

        If ``seed_inputs`` is provided (e.g. the previous solve's inputs),
        the solver tries them first against the current level. If the cached
        sequence still wins — typical when the user only added unrelated
        decoration — it returns instantly. Otherwise it truncates the cached
        sequence to its last-safe frame and seeds the first beam-search
        attempt from there, so unchanged level prefixes don't have to be
        re-explored from scratch.
        """
        # Mute sfx during simulation
        was_enabled = sfx.is_enabled()
        if was_enabled:
            sfx.toggle()

        # Track the best (highest-x) failed attempt across retries so we can
        # return *something* informative even if no attempt fully solves.
        best_failed_waypoints = []
        best_failed_mirror_waypoints = []
        best_failed_inputs = []
        best_failed_x = -1.0
        waypoints = []
        mirror_waypoints = []
        inputs = []
        won = False

        try:
            # 1) Cache verification: replay seed_inputs against the current
            #    level. If it still wins, we're done.
            prefix_inputs = None
            if seed_inputs:
                wp, mwp, won_replay, last_alive = self._verify_inputs(seed_inputs)
                if won_replay:
                    return wp, mwp, list(seed_inputs), True
                # Truncate to last-safe frame so beam search has somewhere
                # solid to resume from. last_alive is the last input index
                # the player survived; back off by the safety margin so the
                # search has room to deviate before the divergence point.
                if last_alive > self._SEED_SAFETY_MARGIN:
                    cut = last_alive - self._SEED_SAFETY_MARGIN
                    prefix_inputs = list(seed_inputs[:cut])

            # 2) Try with increasing beam widths. Each retry doubles the beam
            #    so harder levels get more parallel exploration before giving
            #    up. The 4th attempt also extends max_frames since the bigger
            #    beam explores more states per frame and may need more frames
            #    to commit to a route. The seed-prefix is only used on the
            #    first attempt — if it fails, we drop it and retry from
            #    scratch in case the cached prefix itself was misleading.
            #
            #    Attempt 1 runs in-process (fast path: most easy levels win
            #    here, and subprocess spawn overhead would double their
            #    wall-clock time). If it fails, attempts 2-4 run concurrently
            #    in worker subprocesses — the first one to win terminates
            #    the others. This is pure parallelism: identical beam widths,
            #    identical scoring, identical dedup, no quality loss.
            widths = [self.BEAM_WIDTH,
                      self.BEAM_WIDTH * 2,
                      self.BEAM_WIDTH * 4,
                      self.BEAM_WIDTH * 8]

            # Attempt 1 sequentially.
            waypoints, mirror_waypoints, inputs, won = self._beam_search(
                widths[0], max_frames, screen, clock, 0,
                prefix_inputs=prefix_inputs)
            if not won and waypoints:
                farthest = max((wp[0] for wp in waypoints), default=-1.0)
                if farthest > best_failed_x:
                    best_failed_x = farthest
                    best_failed_waypoints = waypoints
                    best_failed_mirror_waypoints = mirror_waypoints
                    best_failed_inputs = inputs

            # Attempts 2-4 in parallel (skipped if attempt 1 already won).
            if not won:
                remaining = []
                for attempt in (1, 2, 3):
                    frames = max_frames if attempt < 3 else int(max_frames * 1.5)
                    remaining.append(
                        (self.objects, widths[attempt], frames, None, attempt))
                try:
                    par_wp, par_mwp, par_in, par_won, par_failed = \
                        self._solve_attempts_parallel(remaining, screen, clock)
                except Exception:
                    # Multiprocessing is best-effort. If it fails (e.g. in
                    # restricted environments or sandboxes that can't spawn
                    # subprocesses), fall back to the original sequential
                    # retry loop so behaviour is preserved exactly.
                    par_won = False
                    par_failed = None
                    for attempt in (1, 2, 3):
                        frames = (max_frames if attempt < 3
                                  else int(max_frames * 1.5))
                        waypoints, mirror_waypoints, inputs, won = \
                            self._beam_search(widths[attempt], frames,
                                              screen, clock, attempt,
                                              prefix_inputs=None)
                        if won:
                            break
                        if waypoints:
                            farthest = max((wp[0] for wp in waypoints),
                                           default=-1.0)
                            if farthest > best_failed_x:
                                best_failed_x = farthest
                                best_failed_waypoints = waypoints
                                best_failed_mirror_waypoints = mirror_waypoints
                                best_failed_inputs = inputs
                else:
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

            if not won and best_failed_waypoints:
                waypoints = best_failed_waypoints
                mirror_waypoints = best_failed_mirror_waypoints
                inputs = best_failed_inputs
        finally:
            if was_enabled:
                sfx.toggle()

        return waypoints, mirror_waypoints, inputs, won

    def _verify_inputs(self, inputs):
        """Replay ``inputs`` against a fresh sim of the current level.

        Returns ``(waypoints, mirror_waypoints, won, last_alive_frame)``.
        ``last_alive_frame`` is the highest index in ``inputs`` for which
        the player was still alive after that frame, or -1 if the player
        died on frame 0. ``mirror_waypoints`` is empty unless a dual portal
        was active during the replay.
        """
        work_objects = [dict(o) for o in self.objects]
        player = _SimPlayer(work_objects)
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
                    mirror_waypoints.append((
                        player.x + size / 2,
                        player.mirror["y"] + size / 2,
                    ))
            if player.alive:
                last_alive = i
            if not player.alive or player.won:
                break
        return waypoints, mirror_waypoints, player.won, last_alive

    def _beam_search(self, beam_width, max_frames, screen, clock, attempt,
                     prefix_inputs=None):
        """Core beam search. Returns (waypoints, inputs, won).

        If ``prefix_inputs`` is provided, the search first replays those
        inputs as a single-candidate "beam of one" so the cached prefix
        carries over into history with parent_idx=0. The beam then expands
        normally from the player's post-prefix state. Reconstruction walks
        the parent chain back through the prefix automatically because every
        prefix frame's parent is 0.
        """
        work_objects = [dict(o) for o in self.objects]
        player = _SimPlayer(work_objects)
        player.trail = []
        _build_obj_index(player)

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
            # Input options depend on mode of best candidate. The (False, True)
            # 'tap' option activates orbs / pads without committing to a hold —
            # essential for cube/spider orb-chain routes.
            mode = beam[0][0][0][_MODE]
            if mode in (MODE_BALL, MODE_UFO, MODE_CUBE, MODE_SPIDER):
                default_options = [(False, False), (True, True), (False, True)]
            else:
                default_options = [(False, False), (True, True)]

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
                options = default_options
                if (cand_mode in _TAP_PRUNABLE_MODES
                        and not vals[_ON_GROUND]):
                    mirror_forbids = False
                    m_snap = snap[_MIRROR]
                    if m_snap is not None and len(m_snap) >= 7:
                        # mirror tuple: (y, vy, grav, on_ground, angle,
                        #                alive, mode, size)
                        if m_snap[5] and m_snap[6] in _HOLD_SENSITIVE_MODES:
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
                        # Composite score (higher = preferred):
                        #  • x-progress dominates (raw pixels).
                        #  • clearance_bonus favours paths well clear of
                        #    saws/spikes (tiebreaker, weight 0.01).
                        #  • passed-count bonus rewards consuming orbs /
                        #    portals / coins this frame — usually the
                        #    designer-intended route.
                        #  • velocity bonus rewards forward momentum, so
                        #    the beam prefers candidates building speed
                        #    over candidates with the same x but stalled.
                        #  • end-proximity pull strengthens as the player
                        #    nears the finish, so the beam commits to the
                        #    final approach instead of wandering sideways.
                        score = player.x
                        score += self._clearance_bonus(player) * 0.01
                        newly_passed = len(player.passed) - parent_pcount
                        if newly_passed > 0:
                            score += newly_passed * 3.0
                        # Forward momentum: getattr because move_speed exists
                        # on Player but only post-init.
                        score += getattr(player, "move_speed", 5) * 0.4
                        if self._end_x > 0:
                            dist_to_end = max(0.0, self._end_x - player.x)
                            # Closer to end = stronger pull. Weight ramps
                            # from ~0.02 at far range to ~5 in the last
                            # 200 px (final committal).
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
            unique = unique[:beam_width]

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
                    else STAGNATION_BASE
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

            # Progress display (every 80 frames to reduce overhead)
            if screen is not None and total_frames % 80 == 0:
                alive_xs = [b[0][0][_X] for b in beam if b[0][0][_ALIVE]]
                best_x = max(alive_xs) if alive_xs else max(b[0][0][_X] for b in beam)
                cancelled = self._draw_progress(
                    screen, clock, total_frames, best_x, max_frames,
                    len(beam), beam_width, attempt)
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
        empty for levels that never use a dual portal."""
        work_objects = [dict(o) for o in self.objects]
        player = Player(work_objects)
        player.trail = []

        # Mute sfx for replay
        was_enabled = sfx.is_enabled()
        if was_enabled:
            sfx.toggle()

        try:
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
                        mirror_waypoints.append((
                            player.x + size / 2,
                            player.mirror["y"] + size / 2,
                        ))
                if not player.alive or player.won:
                    break
        finally:
            if was_enabled:
                sfx.toggle()

        return waypoints, mirror_waypoints, player.won

    def _solve_attempts_parallel(self, attempts_args, screen, clock):
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
        n_workers = min(len(attempts_args),
                        max(1, _os.cpu_count() or 1))
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
                    wp, mwp, inp, won, _aidx = pending_results[i].get()
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

    def _draw_parallel_progress(self, screen, clock, n_pending, n_workers):
        """Minimal progress display for the parallel phase. Returns True
        if the user pressed ESC (cancel)."""
        from graphics import txt
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

    def _draw_progress(self, screen, clock, frame, best_x, max_frames,
                       n_alive, beam_width, attempt):
        from graphics import txt
        pct = min(99, int(frame / max_frames * 100))
        screen.fill((10, 8, 24))
        title = "AUTO-BOT  BEAM SEARCH"
        if attempt > 0:
            title += f"  (attempt {attempt + 1})"
        txt(screen, title, WIDTH // 2, HEIGHT // 2 - 60,
            32, (255, 180, 60), True)
        txt(screen, f"Frame {frame}  |  X {int(best_x)}  |  Beam {n_alive}/{beam_width}",
            WIDTH // 2, HEIGHT // 2 - 10, 18, (180, 180, 200), True)
        # progress bar
        bw = 400
        bx = WIDTH // 2 - bw // 2
        by = HEIGHT // 2 + 40
        pygame.draw.rect(screen, (40, 40, 60), (bx, by, bw, 22), border_radius=6)
        pygame.draw.rect(screen, (255, 180, 60),
                         (bx, by, max(1, int(bw * pct / 100)), 22), border_radius=6)
        txt(screen, f"{pct}%", WIDTH // 2, by + 6, 14, (255, 255, 255), True)
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
                return True
        return False
