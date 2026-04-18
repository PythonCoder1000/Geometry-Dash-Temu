"""Auto-pathfinding bot — beam search that explores many parallel paths
to find one that reaches the finish.  Press L in the editor to run it;
the result is drawn as bot-path waypoints and the exact inputs are saved
for replay with K."""

import pygame

from constants import (
    CELL, PLAYER_SIZE, HEIGHT, WIDTH,
    MODE_CUBE, MODE_SHIP, MODE_BALL, MODE_WAVE, MODE_UFO, MODE_SPIDER,
    HAZARD_TYPES,
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

    Uses a spatial grid for O(1) nearby_for_rect instead of O(N) scan.
    All physics is inherited unchanged from Player so the simulation matches
    real play frame-for-frame — duplicating the physics here previously caused
    silent drift (different inflate radius, missing spider branch, extra
    ground probe) that made beam-search "wins" fail on replay.
    """

    def __init__(self, objects):
        # Build spatial grid BEFORE super().__init__ (which calls reset).
        self._grid = {}
        for o in objects:
            gx, gy = o["x"], o["y"]
            self._grid.setdefault((gx, gy), []).append(o)
        super().__init__(objects)

    def nearby_for_rect(self, rect, extra=2):
        left = rect.left // CELL - extra
        right = rect.right // CELL + extra
        top = rect.top // CELL - extra
        bottom = rect.bottom // CELL + extra
        result = []
        grid = self._grid
        for gx in range(int(left), int(right) + 1):
            for gy in range(int(top), int(bottom) + 1):
                cell = grid.get((gx, gy))
                if cell:
                    result.extend(cell)
        return result

    def _rebuild_grid(self):
        """Rebuild grid after object positions change (move triggers)."""
        self._grid.clear()
        for o in self.objects:
            gx, gy = o["x"], o["y"]
            self._grid.setdefault((gx, gy), []).append(o)

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
]

# Pre-built index for fast object position restore
_obj_index = None  # dict: id(obj) -> obj, built once per solve


def _build_obj_index(player):
    global _obj_index
    _obj_index = {id(o): o for o in player.objects}


def _snap(player):
    """Capture player state as a lightweight tuple-based snapshot.

    Layout: ``(vals, passed, anims, obj_pos, mirror)`` where ``mirror`` is
    None when the player has not crossed a dual portal, or a 6-tuple
    ``(y, vy, grav, on_ground, angle, alive)`` mirroring `_enter_dual`'s
    state dict. Beam search MUST round-trip the mirror or every restore
    after a dual portal silently desyncs from reality.
    """
    vals = tuple(getattr(player, k, 0) for k in _SNAP_KEYS)
    passed = frozenset(player.passed)
    # Animations: store minimal data needed to restore
    anims = tuple(
        (id(a['obj']), a['sx'], a['sy'], a['ex'], a['ey'],
         a['frame'], a['duration'],
         a['curve'], a['curve_area'])
        for a in player.move_animations
    ) if player.move_animations else ()
    # Object positions: only track moved objects
    obj_pos = tuple(
        (id(o), o['x'], o['y'], o.get('_fx'), o.get('_fy'))
        for o in player.objects
        if '_fx' in o or '_fy' in o
    )
    # Dual-mode mirror — None pre-portal, populated tuple after.
    m = player.mirror
    if m is None:
        mirror = None
    else:
        mirror = (m["y"], m["vy"], m["grav"], m["on_ground"],
                  m.get("angle", 0.0), m["alive"])
    return (vals, passed, anims, obj_pos, mirror)


def _restore(player, snap):
    """Restore player state from snapshot."""
    # Backwards-compat for old 4-tuple snapshots: pad with mirror=None so a
    # mid-solve format upgrade doesn't throw.
    if len(snap) == 4:
        vals, passed, anims, obj_pos = snap
        mirror = None
    else:
        vals, passed, anims, obj_pos, mirror = snap
    for i, k in enumerate(_SNAP_KEYS):
        setattr(player, k, vals[i])
    player.passed = set(passed)
    player.trail = []
    # Restore animations
    if anims:
        player.move_animations = [
            {'obj': _obj_index[oid], 'sx': sx, 'sy': sy, 'ex': ex, 'ey': ey,
             'frame': fr, 'duration': dur, 'curve': crv, 'curve_area': ca}
            for oid, sx, sy, ex, ey, fr, dur, crv, ca in anims
        ]
    else:
        player.move_animations = []
    # Restore object positions
    if obj_pos:
        for oid, x, y, fx, fy in obj_pos:
            o = _obj_index.get(oid)
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
    # Restore dual mirror — must come AFTER scalar state so the mirror's
    # independent vy/grav/y aren't accidentally tied to the player's.
    if mirror is None:
        player.mirror = None
    else:
        my, mvy, mgrav, mog, mang, malive = mirror
        player.mirror = {
            "y": float(my),
            "vy": float(mvy),
            "grav": int(mgrav),
            "on_ground": bool(mog),
            "angle": float(mang),
            "alive": bool(malive),
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
    # mirror can die independently. Fold the mirror's discretised y/vy
    # plus its alive flag into the key. Pre-portal candidates collapse on
    # the same `None` sentinel, so single-player levels are unaffected.
    mirror = snap[4] if len(snap) > 4 else None
    if mirror is None:
        return base + (None,)
    my, mvy, _mgrav, _mog, _mang, malive = mirror
    return base + (round(my / 5), round(mvy / 2), 1 if malive else 0)


# ---------------------------------------------------------------------------
# Beam search solver
# ---------------------------------------------------------------------------

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
            widths = [self.BEAM_WIDTH,
                      self.BEAM_WIDTH * 2,
                      self.BEAM_WIDTH * 4,
                      self.BEAM_WIDTH * 8]
            for attempt, width in enumerate(widths):
                # Last attempt also gets 50% more frames.
                attempt_frames = max_frames if attempt < 3 else int(max_frames * 1.5)
                attempt_prefix = prefix_inputs if attempt == 0 else None
                waypoints, mirror_waypoints, inputs, won = self._beam_search(
                    width, attempt_frames, screen, clock, attempt,
                    prefix_inputs=attempt_prefix)
                if won:
                    break
                # Remember the deepest failed run so we can show it to the user
                # if no full solution is found.
                if waypoints:
                    farthest = max((wp[0] for wp in waypoints), default=-1.0)
                    if farthest > best_failed_x:
                        best_failed_x = farthest
                        best_failed_waypoints = waypoints
                        best_failed_mirror_waypoints = mirror_waypoints
                        best_failed_inputs = inputs
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

        while total_frames < max_frames and not won:
            # Input options depend on mode of best candidate. The (False, True)
            # 'tap' option activates orbs / pads without committing to a hold —
            # essential for cube/spider orb-chain routes.
            mode = beam[0][0][0][_MODE]
            if mode in (MODE_BALL, MODE_UFO, MODE_CUBE, MODE_SPIDER):
                options = [(False, False), (True, True), (False, True)]
            else:
                options = [(False, False), (True, True)]

            # Expand all beam entries with all input options
            candidates = []
            # How much passed-object credit was in the parent beam entries —
            # used to reward newly-consumed orbs / portals this frame.
            parent_passed = [len(b[0][1]) for b in beam]

            for beam_idx, (snap, _, _) in enumerate(beam):
                parent_pcount = parent_passed[beam_idx]
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
