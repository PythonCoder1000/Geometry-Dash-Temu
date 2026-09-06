"""Auto-pathfinding bot — single-threaded A* + reverse-DFS + pathfinder.

The L key (editor & play) opens the bot menu, which calls into AutoBot.
The result is drawn as bot-path waypoints; the exact input chain is
cached for replay with K (or via the bot menu's Replay button).

Pipeline (single-threaded — no multiprocessing, no random retries):

  Phase 0  Seed verify         (replay supplied seed, return early on win)
  Phase 1  Trivial canned      (walk, hold, press, every-N rhythms)
  Phase 2  Greedy lookahead    (k-step lookahead warm-start)
  Phase 3  A* search           (weighted, frontier-bounded with
                                coin / checkpoint / probe / click heuristic)
  Phase 4  Reverse-DFS brute   (try alternative inputs at deepest stuck)
  Phase 5  Pathfinder seed     (randomized generation search seeded
                                with the deepest deterministic partial)

Each phase that fails feeds its deepest-x partial chain into the next
phase as ``seed_inputs`` so cumulative progress is never thrown away.
ESC is pumped on a wall-clock cadence so cancellation is responsive
even mid-loop in a hot search — fixes the old "search hangs and ESC
doesn't work" bug. The previous parallel widening / parallel pathfinder
phases were removed: they were CPU-pegging without giving the search
much that single-threaded A* + pathfinder couldn't already do.
"""

import os as _os
import time as _time
from typing import NamedTuple

# Spawn workers historically re-imported pygame and printed its support
# banner; the env-var keep is harmless and avoids regressions if ever
# re-introduced.
_os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "hide")

import pygame

from .constants import (
    CELL, PLAYER_SIZE, HEIGHT, WIDTH,
    MODE_CUBE, MODE_SHIP, MODE_BALL, MODE_WAVE, MODE_UFO, MODE_SPIDER,
    MODE_SWING, MODE_ROBOT,
    HAZARD_TYPES, ORB_TYPES, SOLID_TYPES,
    T_END, T_START, T_BLOCK, T_SLAB, T_SLOPE,
    T_SPEED_SLOW, T_SPEED_NORMAL, T_SPEED_FAST, T_SPEED_FASTER,
    SPEED_VALUES,
    T_COIN, T_JUMP_PREDICTOR, T_BOT_CHECKPOINT,
)

# Object types that ``_handle_interactions`` actually fires logic for —
# everything else is a solid block / slab / slope or T_START. Building
# a parallel "trigger-only" spatial grid alongside the full grid means
# the interaction loop iterates 2-5× fewer objects on block-heavy levels.
_NON_TRIGGER_TYPES = SOLID_TYPES | {T_START, T_SLOPE}

from .player import Player
from . import sfx


# ---------------------------------------------------------------------------
# Snapshot / restore for state-space search
# ---------------------------------------------------------------------------

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
    dash_vx: float
    dash_vy: float
    flight_budget: int
    robot_thrust_disabled: bool


# ---------------------------------------------------------------------------
# Fast simulation player with spatial grid
# ---------------------------------------------------------------------------

class _SimPlayer(Player):
    """Player subclass optimised for headless simulation.

    Uses a flat-array spatial grid for O(1) nearby_for_rect (no tuple
    hashing, no hash-table probing). All physics is inherited unchanged
    from Player so the simulation matches real play frame-for-frame —
    duplicating the physics here previously caused silent drift that made
    search wins fail on replay.
    """

    __slots__ = (
        "_grid_ox", "_grid_oy", "_grid_w", "_grid_h",
        "_grid_arr", "_trigger_grid_arr",
        "_obj_index",
    )

    _GRID_MARGIN = 50

    def __init__(self, objects, params=None):
        self._init_grid(objects)
        self._obj_index = {id(o): o for o in objects}
        self._nearby_cache_key = None
        self._nearby_cache_result = []
        self._nearby_trigger_cache_key = None
        self._nearby_trigger_cache_result = []
        # Solver probe sees bot-only objects by default — that's the
        # whole point of the "bot only" toggle: the bot must reason
        # about the phantom hazard even though the real player walks
        # through it.
        self._bot_visibility = True
        super().__init__(objects, params=params)

    def _init_grid(self, objects):
        if not objects:
            self._grid_ox = 0
            self._grid_oy = 0
            self._grid_w = 1
            self._grid_h = 1
            self._grid_arr = [None]
            self._trigger_grid_arr = [None]
            return
        min_x = min(o["x"] for o in objects) - self._GRID_MARGIN
        max_x = max(o["x"] for o in objects) + self._GRID_MARGIN
        min_y = min(o["y"] for o in objects) - self._GRID_MARGIN
        max_y = max(o["y"] for o in objects) + self._GRID_MARGIN
        self._grid_ox = min_x
        self._grid_oy = min_y
        self._grid_w = max_x - min_x + 1
        self._grid_h = max_y - min_y + 1
        size = self._grid_w * self._grid_h
        arr = [None] * size
        trig_arr = [None] * size
        w = self._grid_w
        non_trigger = _NON_TRIGGER_TYPES
        for o in objects:
            idx = (o["y"] - min_y) * w + (o["x"] - min_x)
            cell = arr[idx]
            if cell is None:
                arr[idx] = [o]
            else:
                cell.append(o)
            if o["t"] not in non_trigger:
                tcell = trig_arr[idx]
                if tcell is None:
                    trig_arr[idx] = [o]
                else:
                    tcell.append(o)
        self._grid_arr = arr
        self._trigger_grid_arr = trig_arr

    def nearby_for_rect(self, rect, extra=2):
        return self._nearby_for_aabb(rect.left, rect.top,
                                     rect.right, rect.bottom, extra)

    def _nearby_for_aabb(self, left_px, top_px, right_px, bottom_px, extra=2):
        ox = self._grid_ox
        oy = self._grid_oy
        left = left_px // CELL - extra - ox
        right = right_px // CELL + extra - ox
        top = top_px // CELL - extra - oy
        bottom = bottom_px // CELL + extra - oy
        bot_vis = bool(getattr(self, "_bot_visibility", False))
        cache_key = (left, top, right, bottom, extra, bot_vis)
        if cache_key == self._nearby_cache_key:
            return self._nearby_cache_result
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
            self._nearby_cache_key = cache_key
            self._nearby_cache_result = []
            return self._nearby_cache_result
        result = []
        arr = self._grid_arr
        for gy in range(top, bottom + 1):
            base = gy * w
            for gx in range(left, right + 1):
                cell = arr[base + gx]
                if cell is not None:
                    result.extend(cell)
        if not bot_vis and result:
            # Mirror Player._nearby_for_aabb's bot-only filter.
            # _SimPlayer is used by the autobot pipelines (which want
            # bot_only visible) so the default flag stays False here
            # — solver subclasses that need "see everything" bump
            # ``self._bot_visibility = True`` themselves.
            for o in result:
                if o.get("_bot_only"):
                    result = [o for o in result
                              if not o.get("_bot_only")]
                    break
        self._nearby_cache_key = cache_key
        self._nearby_cache_result = result
        return result

    def _nearby_triggers_for_aabb(self, left_px, top_px, right_px,
                                  bottom_px, extra=2):
        ox = self._grid_ox
        oy = self._grid_oy
        left = left_px // CELL - extra - ox
        right = right_px // CELL + extra - ox
        top = top_px // CELL - extra - oy
        bottom = bottom_px // CELL + extra - oy
        cache_key = (left, top, right, bottom, extra)
        if cache_key == self._nearby_trigger_cache_key:
            return self._nearby_trigger_cache_result
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
            self._nearby_trigger_cache_key = cache_key
            self._nearby_trigger_cache_result = []
            return self._nearby_trigger_cache_result
        result = []
        arr = self._trigger_grid_arr
        for gy in range(top, bottom + 1):
            base = gy * w
            for gx in range(left, right + 1):
                cell = arr[base + gx]
                if cell is not None:
                    result.extend(cell)
        self._nearby_trigger_cache_key = cache_key
        self._nearby_trigger_cache_result = result
        return result

    def _rebuild_grid(self):
        self._init_grid(self.objects)
        self._nearby_cache_key = None
        self._nearby_trigger_cache_key = None

    def _step_move_animations(self):
        if not self.move_animations:
            return
        super()._step_move_animations()
        self._rebuild_grid()

    def update(self, input_held, input_pressed):
        super().update(input_held, input_pressed)
        if self.trail:
            self.trail.clear()


# ---------------------------------------------------------------------------
# Snapshot helpers
# ---------------------------------------------------------------------------

_SNAP_KEYS = [
    'x', 'y', 'vy', 'on_ground', 'alive', 'won', 'angle', 'grav',
    'frame', 'mode', 'move_speed', 'dash_timer', 'input_buffer',
    'teleport_cooldown', 'target_cam_y', 'bg_preset',
    'color_index', '_grav_flip_grace', '_wall_frames',
    'mirror_input_buffer', 'size',
]


def _build_obj_index(player):
    """Compatibility shim — populates the per-instance obj index used by
    ``_restore`` to translate snap ids back to live object refs."""
    player._obj_index = {id(o): o for o in player.objects}


def _snap(player):
    """Capture player state as a tuple-based snapshot."""
    vals = SnapVals(
        player.x, player.y, player.vy, player.on_ground, player.alive,
        player.won, player.angle, player.grav, player.frame, player.mode,
        player.move_speed, player.dash_timer, player.input_buffer,
        player.teleport_cooldown, player.target_cam_y, player.bg_preset,
        player.color_index, player._grav_flip_grace, player._wall_frames,
        player.mirror_input_buffer, player.size,
        player.dash_vx, player.dash_vy,
        player.flight_budget,
        player._robot_thrust_disabled,
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
    # Snapshot every ever-moved object whose current position is NOT
    # at its original cell, OR which is still mid-animation. Critical
    # bug fix: when an animation completes, _step_move_animations pops
    # _fx/_fy but the object stays at its destination — the old "if
    # _fx in o or _fy in o" filter dropped those completed objects
    # from the snap entirely. On restore, the reset-to-_orig_x loop
    # then saw the object in _ever_moved but NOT in obj_pos and
    # teleported it BACK to its original cell, even though the snap
    # was taken AFTER the animation completed. Replays diverged from
    # search ("solver found a path through the moved orb but the
    # replay's orb is at origin"), matching the "dies on things it
    # used to be able to do" failure mode. We also exclude objects
    # currently AT their origin (e.g. a previous restore reset them)
    # so two states with the same world layout collapse to one
    # dedup key regardless of history.
    obj_pos_list = []
    ever_moved = getattr(player, "_ever_moved", None)
    if ever_moved:
        for oid, o in ever_moved.items():
            ox = o.get("_orig_x")
            oy = o.get("_orig_y")
            displaced = (ox is None or oy is None
                         or o["x"] != ox or o["y"] != oy
                         or "_fx" in o or "_fy" in o)
            if displaced:
                obj_pos_list.append((oid, o['x'], o['y'],
                                     o.get('_fx'), o.get('_fy')))
    else:
        # Fallback for callers that don't populate _ever_moved.
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
                  m.get("mode", MODE_CUBE), m.get("size", PLAYER_SIZE),
                  m.get("flight_budget", 0),
                  m.get("thrust_disabled", False))
    mirror_passed = frozenset(player.mirror_passed)
    coins = frozenset(player.coins_collected)
    return (vals, passed, anims, obj_pos, mirror, mirror_passed, coins)


def _restore(player, snap):
    """Restore player state from snapshot (tolerates 4/5/6/7 length variants
    so older on-disk caches still load)."""
    n = len(snap)
    if n == 4:
        vals, passed, anims, obj_pos = snap
        mirror = None
        mirror_passed = frozenset()
        coins = frozenset()
    elif n == 5:
        vals, passed, anims, obj_pos, mirror = snap
        mirror_passed = frozenset()
        coins = frozenset()
    elif n == 6:
        vals, passed, anims, obj_pos, mirror, mirror_passed = snap
        coins = frozenset()
    else:
        vals, passed, anims, obj_pos, mirror, mirror_passed, coins = snap
    (player.x, player.y, player.vy, player.on_ground, player.alive,
     player.won, player.angle, player.grav, player.frame, player.mode,
     player.move_speed, player.dash_timer, player.input_buffer,
     player.teleport_cooldown, player.target_cam_y, player.bg_preset,
     player.color_index, player._grav_flip_grace, player._wall_frames,
     player.mirror_input_buffer, player.size) = tuple(vals)[:21]
    if len(vals) >= 23:
        player.dash_vx = vals[21]
        player.dash_vy = vals[22]
    else:
        player.dash_vx = 0.0
        player.dash_vy = 0.0
    if len(vals) >= 24:
        player.flight_budget = int(vals[23])
    else:
        player.flight_budget = int(player.params.robot_flight_seconds * 60)
    if len(vals) >= 25:
        player._robot_thrust_disabled = bool(vals[24])
    else:
        player._robot_thrust_disabled = False
    player.passed = set(passed)
    player.mirror_passed = set(mirror_passed)
    player.coins_collected = set(coins)
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
            mfb = int(player.params.robot_flight_seconds * 60)
            mtd = False
        elif len(mirror) == 8:
            my, mvy, mgrav, mog, mang, malive, mmode, msize = mirror
            mfb = int(player.params.robot_flight_seconds * 60)
            mtd = False
        elif len(mirror) == 9:
            (my, mvy, mgrav, mog, mang, malive, mmode, msize,
             mfb) = mirror
            mtd = False
        else:
            (my, mvy, mgrav, mog, mang, malive, mmode, msize,
             mfb, mtd) = mirror
        player.mirror = {
            "y": float(my), "vy": float(mvy), "grav": int(mgrav),
            "on_ground": bool(mog), "angle": float(mang),
            "alive": bool(malive),
            "mode": mmode,
            "size": int(msize),
            "flight_budget": int(mfb),
            "thrust_disabled": bool(mtd),
        }


_CONTINUOUS_Y_MODES = (MODE_SHIP, MODE_WAVE, MODE_UFO, MODE_ROBOT)


def _dedup_key(snap):
    """Discretised state key for pruning duplicate trajectories.

    Branches with active move-trigger animations can have an orb /
    block in different mid-animation positions even at the same
    player x/y bucket — collapsing them via a player-only key would
    let A* pick the "earlier orb" branch and discard the path that
    cleared the level only because the orb had advanced further.
    Fold the active animation state (frame counts + currently-moved
    object positions) into the key so those branches stay separate.
    """
    vals = snap[0]
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
        mode = vals[9]
        y = vals[1]
        vy = vals[2]
        grav = vals[7]
        on_ground = vals[3]
        input_buffer = vals[12]
        dash_timer = vals[11]
        mirror_input_buffer = vals[19]
    if mode in _CONTINUOUS_Y_MODES:
        y_bucket = round(y / 1.5)
        vy_bucket = round(vy / 0.75)
    else:
        y_bucket = round(y / 2.5)
        vy_bucket = round(vy / 1.0)
    # Hash active animation frames + moved-object positions into the
    # dedup key. Empty tuples (no movement) collapse to a no-op.
    anims_t = snap[2] if len(snap) > 2 else ()
    obj_pos_t = snap[3] if len(snap) > 3 else ()
    if anims_t:
        # (id, frame) per anim — coarsen the frame to the nearest
        # tick so sub-frame timing differences don't pointlessly
        # split otherwise-identical states.
        anim_key = tuple(sorted((a[0], a[5]) for a in anims_t))
    else:
        anim_key = ()
    if obj_pos_t:
        # (id, gx, gy) per moved object — bucket coordinates so
        # near-identical positions collapse but cell-level
        # differences don't.
        obj_pos_key = tuple(sorted(
            (entry[0], int(entry[1]), int(entry[2]))
            for entry in obj_pos_t))
    else:
        obj_pos_key = ()
    base = (
        y_bucket, vy_bucket, grav, mode, on_ground,
        1 if input_buffer > 0 else 0,
        1 if dash_timer > 0 else 0,
        anim_key, obj_pos_key,
    )
    mirror = snap[4] if len(snap) > 4 else None
    if mirror is None:
        return base + (None,)
    if len(mirror) == 6:
        my, mvy, _mgrav, _mog, _mang, malive = mirror
        mmode, msize = 0, 0
    elif len(mirror) == 8:
        my, mvy, _mgrav, _mog, _mang, malive, mmode, msize = mirror
    elif len(mirror) == 9:
        (my, mvy, _mgrav, _mog, _mang, malive, mmode, msize,
         _mfb) = mirror
    else:
        (my, mvy, _mgrav, _mog, _mang, malive, mmode, msize,
         _mfb, _mtd) = mirror
    mirror_buf = 1 if mirror_input_buffer > 0 else 0
    return base + (round(my / 2.5), round(mvy / 1.0),
                   1 if malive else 0, mmode, msize,
                   _mgrav, 1 if _mog else 0, mirror_buf)


def _player_dedup_key(player):
    """Same as ``_dedup_key(_snap(player))`` but reads attributes
    directly from the player — used to dedup BEFORE allocating the
    full snap. Includes active move-animation frames + moved-object
    positions so branches with mid-animation orbs in different
    cells don't collapse to a single dedup slot."""
    mode = player.mode
    y = player.y
    vy = player.vy
    if mode in _CONTINUOUS_Y_MODES:
        y_bucket = round(y / 1.5)
        vy_bucket = round(vy / 0.75)
    else:
        y_bucket = round(y / 2.5)
        vy_bucket = round(vy / 1.0)
    anims = player.move_animations
    if anims:
        anim_key = tuple(sorted((id(a['obj']), a['frame']) for a in anims))
    else:
        anim_key = ()
    # Match _snap's filter exactly: include any ever-moved object
    # currently displaced from its origin OR mid-animation. The old
    # "if _fx in o or _fy in o" filter dropped completed-animation
    # objects, producing dedup keys that didn't reflect the world
    # state and let A* collapse genuinely-different branches.
    objs = getattr(player, "_ever_moved", None)
    if objs:
        rows = []
        for oid, o in objs.items():
            ox = o.get("_orig_x")
            oy = o.get("_orig_y")
            displaced = (ox is None or oy is None
                         or o["x"] != ox or o["y"] != oy
                         or "_fx" in o or "_fy" in o)
            if displaced:
                rows.append((oid, int(o["x"]), int(o["y"])))
        obj_pos_key = tuple(sorted(rows))
    else:
        obj_pos_key = ()
    base = (
        y_bucket, vy_bucket, player.grav, mode, player.on_ground,
        1 if player.input_buffer > 0 else 0,
        1 if player.dash_timer > 0 else 0,
        anim_key, obj_pos_key,
    )
    m = player.mirror
    if m is None:
        return base + (None,)
    mirror_buf = 1 if player.mirror_input_buffer > 0 else 0
    return base + (
        round(m["y"] / 2.5), round(m["vy"] / 1.0),
        1 if m["alive"] else 0,
        m.get("mode", MODE_CUBE),
        int(m.get("size", PLAYER_SIZE)),
        m["grav"],
        1 if m["on_ground"] else 0,
        mirror_buf,
    )


# ---------------------------------------------------------------------------
# Best-partial tracker
# ---------------------------------------------------------------------------

class _BestPartial:
    """Tracks the deepest-x partial chain seen across phases."""
    __slots__ = ("waypoints", "mirror_waypoints", "inputs", "deepest_x")

    def __init__(self):
        self.waypoints = []
        self.mirror_waypoints = []
        self.inputs = []
        self.deepest_x = -1.0

    def update(self, waypoints, mirror_waypoints, inputs):
        if not waypoints:
            return
        x = max((p[0] for p in waypoints), default=-1.0)
        if x > self.deepest_x:
            self.deepest_x = x
            self.waypoints = list(waypoints)
            self.mirror_waypoints = list(mirror_waypoints)
            self.inputs = list(inputs)


# ---------------------------------------------------------------------------
# Solver
# ---------------------------------------------------------------------------

class AutoBot:
    """L-key auto-pathfinder. Single-threaded.

    Public knobs (settable as instance attributes by the bot menu):

      ``FRONTIER_CAP``     — A* open-set bound. Higher widens the search
                              at linear memory + time cost.
      ``BEAM_WIDTH``       — legacy alias for FRONTIER_CAP.
      ``BACKTRACK_DEPTH``  — Reverse-DFS depth in input frames. 0 disables
                              the brute-force phase entirely.
      ``HEURISTIC_WEIGHT`` — Weighted A* h multiplier. 1 is optimal, >1
                              is faster-but-suboptimal. 4 is the sweet spot.
      ``CLICK_PENALTY``    — Tiebreak penalty per press input. Encourages
                              minimum-clicks routes.
      ``COIN_BONUS``       — Reward per newly-collected coin in the search.
      ``CHECKPOINT_BONUS`` — Reward per author-placed bot checkpoint passed.
    """

    FRONTIER_CAP = 384
    BEAM_WIDTH = 384            # legacy alias
    BACKTRACK_DEPTH = 160
    HEURISTIC_WEIGHT = 4.0

    # Click penalty is now a real cost in ``f_new`` (not a tiebreak),
    # so the search PHYSICALLY prefers fewer / longer-held inputs over
    # rapid presses when both reach the same x. 0.5 means each press
    # costs half a frame of depth — meaningful but small enough that
    # any press the search needs to clear a hazard still wins by a
    # huge margin (the alternative is dying).
    CLICK_PENALTY = 0.5
    # Held-but-not-pressed (continued hold) is a much smaller cost on
    # tap-mode bunny-hops. Encourages "release between hops" timing
    # rather than mashing-and-holding.
    HOLD_PENALTY = 0.1

    # Spike clearance — at each frame, look up the player cell's
    # Chebyshev distance to the nearest hazard and add a penalty
    # that's strongest at distance 1 and tapers to 0 at radius+1.
    # ``CLEARANCE_RADIUS`` controls the band; ``CLEARANCE_PENALTY`` is
    # the per-frame f cost at distance 1. Keep this comfortably above
    # 1 so the search is willing to spend a few extra frames detouring
    # around a spike rather than skimming it.
    CLEARANCE_RADIUS = 2
    CLEARANCE_PENALTY = 2.0

    # Coin/checkpoint bonuses are subtracted directly from A*'s f-value
    # ``f = h_weight * h(x) + depth - progress``, so they need to be
    # at least as large as the typical detour cost (in frames) for
    # the search to actually deviate from the shortest x-path. The
    # earlier values of 8/12 were silently dwarfed by depth growth
    # and the bot just skipped them. Checkpoint bonus is roughly 2×
    # coin bonus because authors only place checkpoints when they
    # really want the bot routed through them — hard guidance, not
    # a soft pull.
    COIN_BONUS = 200.0
    CHECKPOINT_BONUS = 600.0

    SEED_SAFETY_MARGIN = 60
    BRUTE_FRAMES = 320
    BRUTE_FRONTIER = 1200

    def __init__(self, objects, params=None):
        self.objects = objects
        self.params = params
        self._cancelled = False

        # ESC-pump throttle. Keep it cheap (~50ms) so cancellation is
        # responsive without dominating the inner loop.
        self._last_pump = 0.0
        self._pump_interval = 0.05

        end_xs = [o["x"] * CELL for o in objects if o["t"] == T_END]
        self._end_x = max(end_xs) if end_xs else 0

        self._orb_cells = set()
        for o in objects:
            if o["t"] in ORB_TYPES:
                self._orb_cells.add((o["x"], o["y"]))
        self._orb_xs = set(c[0] for c in self._orb_cells)
        self._coin_xs = set(o["x"] for o in objects if o["t"] == T_COIN)
        # Per-gx coin position index for the A* "soft pull" — maps
        # gx → list of (cx_px, cy_px) coin centres in or near that
        # column. Bands a coin's pull-window across ~6 cells so the
        # search starts angling toward it before reaching its
        # column.
        self._coin_objs_for_gx = {}
        for o in objects:
            if o.get("t") != T_COIN:
                continue
            cx = o["x"] * CELL + CELL // 2
            cy = o["y"] * CELL + CELL // 2
            for dgx in range(-6, 1):
                bucket = self._coin_objs_for_gx.setdefault(o["x"] + dgx, [])
                bucket.append((cx, cy))
        self._probe_xs = tuple(int(o["x"]) for o in objects
                               if o.get("t") == T_JUMP_PREDICTOR)

        # Author-placed bot checkpoints — heuristic gradient that
        # pulls the search toward the marked (x, y) cells. Sorted by
        # x so the search counts how many it has passed by simply
        # comparing player.x to the next checkpoint's x. The y
        # coordinate is what makes the pull 2D: the bot routes
        # through the marked cell, not just past its column.
        self._checkpoints = sorted(
            ((int(o["x"]) * CELL + CELL // 2,
              int(o["y"]) * CELL + CELL // 2)
             for o in objects if o.get("t") == T_BOT_CHECKPOINT),
            key=lambda p: p[0])
        self._checkpoint_xs = [c[0] for c in self._checkpoints]
        self._checkpoint_ys = [c[1] for c in self._checkpoints]

        self._hazard_col = {}
        hazard_cells = []
        for o in objects:
            if o.get("t") in HAZARD_TYPES:
                gx = int(o["x"])
                gy = int(o["y"])
                self._hazard_col[gx] = self._hazard_col.get(gx, 0) + 1
                hazard_cells.append((gx, gy))

        # Hazard clearance map. For every cell within ``CLEARANCE_RADIUS``
        # Chebyshev cells of any spike / saw, store the minimum
        # distance. The A* heuristic reads this each expansion and
        # adds a per-frame penalty so routes that thread through
        # spikes cost more than routes that keep one or two cells of
        # breathing room. Cells far from every hazard are simply
        # absent from the dict (clearance penalty = 0). Built once
        # at construction; cheap because hazards are sparse vs. the
        # full grid (radius 2 expands each hazard to ~25 cells).
        self._hazard_clearance = {}
        cr = int(self.CLEARANCE_RADIUS)
        for hx, hy in hazard_cells:
            for dgx in range(-cr, cr + 1):
                for dgy in range(-cr, cr + 1):
                    d = abs(dgx) if abs(dgx) > abs(dgy) else abs(dgy)
                    if d > cr or d == 0:
                        # d == 0 is the hazard cell itself; skip — the
                        # player dies on contact, the heuristic doesn't
                        # need to discourage "being inside" the spike.
                        continue
                    key = (hx + dgx, hy + dgy)
                    prev = self._hazard_clearance.get(key)
                    if prev is None or d < prev:
                        self._hazard_clearance[key] = d

        self._build_speed_segments()

    # ------------------------------------------------------------------
    # ESC pumping (responsive cancel)
    # ------------------------------------------------------------------

    def _pump_events(self, force=False):
        """Drain the pygame event queue and flip ``_cancelled`` on ESC.

        Throttled to ``_pump_interval`` seconds so the inner loop only
        pays the syscall cost on a wall-clock cadence rather than every
        expansion. ``force=True`` bypasses the throttle for paint frames
        / phase boundaries.
        """
        now = _time.monotonic()
        if not force and (now - self._last_pump) < self._pump_interval:
            return self._cancelled
        self._last_pump = now
        try:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    pygame.quit()
                    raise SystemExit
                if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                    self._cancelled = True
        except pygame.error:
            # Headless tests run without a display — pygame.event.get()
            # raises in that case. Swallow so search still works in CI.
            pass
        return self._cancelled

    # ------------------------------------------------------------------
    # Heuristic (admissible lower bound on frames-to-finish)
    # ------------------------------------------------------------------

    def _build_speed_segments(self):
        base_speed = (self.params.base_move_speed if self.params is not None
                      else SPEED_VALUES[T_SPEED_NORMAL])
        events = sorted(
            ((int(o["x"]) * CELL, SPEED_VALUES[o["t"]])
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
        seg_ends = seg_starts[1:] + [self._end_x]
        cumul = [0.0] * len(seg_starts)
        running = 0.0
        for i in range(len(seg_starts) - 1, -1, -1):
            cumul[i] = running
            seg_len = max(0, seg_ends[i] - seg_starts[i])
            if seg_speeds[i] > 0:
                running += seg_len / seg_speeds[i]
        self._seg_starts = seg_starts
        self._seg_ends = seg_ends
        self._seg_speeds = seg_speeds
        self._seg_cumul = cumul

        if self._end_x > 0:
            n_cells = self._end_x // CELL + 2
        else:
            n_cells = 1
        recips = [0.0] * n_cells
        seg_end_px = [self._end_x] * n_cells
        cumul_after = [0.0] * n_cells
        for cell in range(n_cells):
            x_px = cell * CELL
            i = 0
            for j, ss in enumerate(seg_starts):
                if ss <= x_px:
                    i = j
                else:
                    break
            sp = seg_speeds[i]
            if sp > 0:
                recips[cell] = 1.0 / sp
            seg_end_px[cell] = seg_ends[i]
            cumul_after[cell] = cumul[i]
        self._h_recips = recips
        self._h_seg_end = seg_end_px
        self._h_cumul = cumul_after
        self._h_n_cells = n_cells

    def _h(self, x):
        end_x = self._end_x
        if end_x <= 0 or x >= end_x:
            return 0.0
        cell = int(x) // CELL
        if cell >= self._h_n_cells:
            return 0.0
        if cell < 0:
            cell = 0
        recip = self._h_recips[cell]
        if recip <= 0.0:
            return 0.0
        return max(0, self._h_seg_end[cell] - x) * recip + self._h_cumul[cell]

    def _frontier_cap(self):
        cap = getattr(self, "FRONTIER_CAP", None)
        if cap is None or cap <= 0:
            cap = getattr(self, "BEAM_WIDTH", 256)
        return max(16, int(cap))

    def _backtrack_depth(self):
        return max(0, int(getattr(self, "BACKTRACK_DEPTH", 80)))

    def _phase_budget(self, fraction):
        deadline = getattr(self, "_deadline", None)
        if deadline is None:
            return None
        remaining = deadline - _time.monotonic()
        if remaining <= 0:
            return 0
        return max(0.5, remaining * fraction)

    def _budget_expired(self):
        deadline = getattr(self, "_deadline", None)
        if deadline is None:
            return False
        return _time.monotonic() > deadline

    # ------------------------------------------------------------------
    # Public solve
    # ------------------------------------------------------------------

    def solve(self, screen=None, clock=None, max_frames=10000,
              seed_inputs=None, n_attempts=None, use_parallel=None,
              n_workers=None, fix_only=False, time_budget=None):
        """Return ``(waypoints, mirror_waypoints, inputs, won)``.

        ``n_attempts`` / ``use_parallel`` / ``n_workers`` are accepted but
        ignored — the solver is single-threaded by design (the parallel
        retry swarm in earlier versions was the cause of CPU pegging and
        unresponsive ESC).

        ``fix_only`` skips the warm-starts and runs ONE short A* repair
        from the seed's last alive prefix. Meant for "I just decorated
        the level, just re-verify".

        ``time_budget`` (seconds) caps total wall-clock for the whole
        pipeline. Phases poll a shared deadline; the final pathfinder
        phase gets the remaining budget so the caller knows the solver
        never runs longer than asked. Default budget = 60 s — keeps
        the user from leaving an unattended run pegging the CPU.
        """
        was_enabled = sfx.is_enabled()
        if was_enabled:
            sfx.toggle()
        # Default wall-clock cap — without this the pathfinder phase has
        # historically eaten arbitrarily many minutes of CPU time on hard
        # levels. 60 s is generous enough to solve everything the older
        # solver could but gives the user a guaranteed upper bound.
        if not time_budget or time_budget <= 0:
            time_budget = 60.0
        self._deadline = _time.monotonic() + time_budget
        self._cancelled = False
        self._last_pump = 0.0
        try:
            best = _BestPartial()

            # ---- Phase 0 — seed verify ---------------------------------
            prefix_inputs = None
            if seed_inputs:
                wp, mwp, won, last_alive = self._verify(seed_inputs)
                if won:
                    return wp, mwp, list(seed_inputs), True
                if last_alive > self.SEED_SAFETY_MARGIN:
                    prefix_inputs = list(
                        seed_inputs[: last_alive - self.SEED_SAFETY_MARGIN])
                if wp:
                    best.update(wp, mwp, list(seed_inputs[: max(0, last_alive)]))

            # ---- Fix-only short-circuit --------------------------------
            if fix_only:
                if not seed_inputs:
                    return [], [], [], False
                wp, mwp, inp, won = self._astar(
                    max_frames, screen, clock,
                    prefix_inputs=prefix_inputs,
                    status_text="Fix-only: repairing seed")
                return wp, mwp, inp, won
            if self._pump_events() or self._budget_expired():
                return best.waypoints, best.mirror_waypoints, best.inputs, False

            # ---- Phase 1 — trivial canned ------------------------------
            # Number of coins / checkpoints in the level — when present
            # the bot's contract is "win AND collect / route through
            # them", so a canned chain that wins by skipping them is
            # NOT a complete solution. We keep it as a fallback in
            # ``best`` and let A* try to find a path that hits them.
            n_coins = sum(1 for o in self.objects
                          if o.get("t") == T_COIN)
            n_checkpoints = len(self._checkpoints)
            require_pickups = n_coins > 0 or n_checkpoints > 0
            if not seed_inputs:
                _walk = [(False, False)] * max_frames
                _hold = [(True, False)] * max_frames
                _press = [(True, True)] * max_frames
                _press2 = [((True, True) if i % 2 == 0
                            else (False, False)) for i in range(max_frames)]
                _press3 = [((True, True) if i % 3 == 0
                            else (False, False)) for i in range(max_frames)]
                for canned in (_walk, _hold, _press, _press2, _press3):
                    if self._pump_events() or self._budget_expired():
                        break
                    wp, mwp, won, _ = self._verify(canned)
                    if won:
                        if require_pickups:
                            # Stash as a fallback win and keep
                            # searching — A* may find a route that
                            # actually grabs the coins / passes
                            # through the checkpoints.
                            best.update(wp, mwp, self._trim_to_win(canned))
                        else:
                            return wp, mwp, self._trim_to_win(canned), True
                    if wp:
                        best.update(wp, mwp, self._trim_to_win(canned))

            # ---- Phase 2 — greedy lookahead warm-start -----------------
            if not seed_inputs and not self._cancelled and not self._budget_expired():
                for label, fn in (
                        ("orb-press", lambda: self._orb_press_canned(max_frames)),
                        ("greedy-2", lambda: self._greedy_lookahead(max_frames, 2)),
                        ("greedy-3", lambda: self._greedy_lookahead(max_frames, 3)),
                ):
                    if self._pump_events() or self._budget_expired():
                        break
                    inp_g, won_g = fn()
                    if won_g:
                        wp_g, mwp_g, _ = self._replay_for_waypoints(inp_g)
                        if require_pickups:
                            best.update(wp_g, mwp_g, inp_g)
                        else:
                            return self._polish_and_return(wp_g, mwp_g, inp_g)
                    if inp_g:
                        wp_g, mwp_g, _ = self._replay_for_waypoints(inp_g)
                        best.update(wp_g, mwp_g, inp_g)

            # ---- Phase 3 — A* search ------------------------------------
            # When the level requires pickups, run A* from scratch
            # rather than from the canned-win prefix — the prefix
            # walks straight past every coin / checkpoint, so seeding
            # A* with it locks the bot onto the wrong route. Without
            # pickup goals the prefix is fine (just speeds up the
            # search to depth K).
            astar_prefix = prefix_inputs
            if (not require_pickups and best.inputs
                    and (not prefix_inputs
                         or len(best.inputs) > len(prefix_inputs)
                         + self.SEED_SAFETY_MARGIN)):
                _, _, _, last_alive = self._verify(best.inputs)
                if last_alive > self.SEED_SAFETY_MARGIN:
                    astar_prefix = list(
                        best.inputs[: last_alive - self.SEED_SAFETY_MARGIN])

            astar_budget = self._phase_budget(0.50)
            wp, mwp, inp, won = self._astar(
                max_frames, screen, clock,
                prefix_inputs=astar_prefix,
                status_text="A* search",
                time_budget=astar_budget)
            if won:
                return self._polish_and_return(wp, mwp, inp)
            best.update(wp, mwp, inp)
            if self._cancelled or self._budget_expired():
                return best.waypoints, best.mirror_waypoints, best.inputs, False

            # ---- Phase 4 — reverse-DFS brute force ----------------------
            if best.inputs and self._backtrack_depth() > 0:
                wp, mwp, inp, won = self._reverse_dfs(
                    best.inputs, screen, clock, max_frames)
                if won:
                    return self._polish_and_return(wp, mwp, inp)
                best.update(wp, mwp, inp)
            if self._cancelled or self._budget_expired():
                return best.waypoints, best.mirror_waypoints, best.inputs, False

            # ---- Phase 5 — pathfinder fallback --------------------------
            # Single-threaded — a single attempt seeded with the deepest
            # partial. The earlier multi-attempt parallel pathfinder was
            # the source of the CPU-peg / unresponsive-ESC bug.
            if best.inputs and not self._cancelled:
                pf_budget = self._phase_budget(1.0)
                if pf_budget and pf_budget > 0:
                    try:
                        pf_wp, pf_inp, pf_won = self._pathfinder(
                            best.inputs, screen, clock,
                            time_budget=pf_budget)
                        if pf_won:
                            return self._polish_and_return(pf_wp, [], pf_inp)
                        if pf_inp and len(pf_inp) > len(best.inputs):
                            best.update(pf_wp, [], pf_inp)
                    except Exception:
                        # Pathfinder is best-effort — never let a bug
                        # here crash a solve that already has a partial.
                        pass

            return best.waypoints, best.mirror_waypoints, best.inputs, False

        finally:
            if was_enabled:
                sfx.toggle()

    # ------------------------------------------------------------------
    # Pathfinder (single attempt, single-threaded)
    # ------------------------------------------------------------------

    def _pathfinder(self, partial_inputs, screen, clock, time_budget=None):
        """Run one PathfinderBot attempt seeded with the deepest partial.

        Returns ``(waypoints, inputs, won)``. The pathfinder polls the
        same ESC latch via its own progress UI, so cancellation here is
        cooperative — the bot exits when it next paints."""
        from .pathfinder_bot import PathfinderBot
        cut = max(0, len(partial_inputs) - self.SEED_SAFETY_MARGIN)
        seed = list(partial_inputs[:cut])
        bot = PathfinderBot(
            self.objects, params=self.params,
            seed_inputs=seed, seed=None,
            max_iterations=8000,
            time_budget=time_budget)
        try:
            wp, inp, won = bot.solve(screen, clock)
        except Exception:
            return [], list(partial_inputs), False
        # Propagate ESC: if the pathfinder UI flipped its cancel latch,
        # mark our solve cancelled so the caller knows to bail.
        if getattr(bot, "_cancelled", False):
            self._cancelled = True
        return wp, inp, won

    # ------------------------------------------------------------------
    # Verification / replay helpers
    # ------------------------------------------------------------------

    def _verify(self, inputs):
        """Replay ``inputs`` against a fresh sim. Returns
        ``(waypoints, mirror_waypoints, won, last_alive_frame)``.
        ``last_alive_frame`` is the highest index at which the player
        was still alive, or -1 if death on frame 0."""
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
                waypoints.append((player.x + size / 2,
                                  player.y + size / 2))
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

    _verify_inputs = _verify

    def _replay_for_waypoints(self, inputs):
        """Replay ``inputs`` with a real Player to capture waypoints
        and verify the solution."""
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
                waypoints.append((player.x + size / 2,
                                  player.y + size / 2))
                if player.mirror is not None and player.mirror.get("alive"):
                    msize = player.mirror.get("size", PLAYER_SIZE)
                    mirror_waypoints.append((
                        player.x + size / 2,
                        player.mirror["y"] + msize / 2,
                    ))
            if not player.alive or player.won:
                break
        return waypoints, mirror_waypoints, player.won

    def _trim_to_win(self, inputs):
        work_objects = [dict(o) for o in self.objects]
        player = _SimPlayer(work_objects, params=self.params)
        for i, (h, p) in enumerate(inputs):
            player.update(h, p)
            if player.won:
                return list(inputs[: i + 1])
            if not player.alive:
                return list(inputs[: max(1, i)])
        return list(inputs)

    def _greedy_lookahead(self, max_frames, lookahead=2):
        """k-step greedy lookahead: at each frame, simulate every action
        forward ``lookahead`` frames against a fresh sim copy, pick the
        action whose continuation reaches the deepest x while staying
        alive. Returns ``(inputs, won)``.

        Score combines x-progress with coin and checkpoint pickups so
        the warm-start naturally gravitates toward the marked route."""
        actions = ((False, False), (True, False), (True, True))
        work = [dict(o) for o in self.objects]
        live = _SimPlayer(work, params=self.params)
        live.trail = []
        probe_work = [dict(o) for o in self.objects]
        probe = _SimPlayer(probe_work, params=self.params)
        probe.trail = []

        deadline = getattr(self, "_deadline", None)
        ckpt_xs = self._checkpoint_xs
        checkpoints = self._checkpoints
        inputs = []
        for _ in range(max_frames):
            if not live.alive or live.won:
                break
            if deadline is not None and _time.monotonic() > deadline:
                break
            if self._pump_events():
                break
            snap = _snap(live)
            best_score = (-1, -float("inf"))
            best_action = (False, False)
            for first in actions:
                _restore(probe, snap)
                probe.update(first[0], first[1])
                follow = (first[0], False)
                for _ in range(lookahead - 1):
                    if not probe.alive or probe.won:
                        break
                    probe.update(follow[0], follow[1])
                if probe.won:
                    live.update(first[0], first[1])
                    inputs.append(first)
                    return inputs, True
                # Score: alive-or-dead first, then progress proxy.
                # Progress proxy = x reached + coin/checkpoint bonuses
                # to seed the warm-start onto the marked route.
                progress = probe.x
                progress += len(probe.coins_collected) * 80.0
                if checkpoints:
                    pcx = probe.x
                    next_ckpt = None
                    for cx in ckpt_xs:
                        if cx >= pcx - CELL:
                            next_ckpt = cx
                            break
                    if next_ckpt is not None:
                        # Reward closeness to the next checkpoint with a
                        # 0..1 falloff scaled by CHECKPOINT_BONUS so a
                        # nearby checkpoint outweighs raw x by a hair —
                        # enough to bias the choice without trapping the
                        # search on an unreachable side route.
                        dx = max(1.0, abs(next_ckpt - pcx))
                        progress += self.CHECKPOINT_BONUS * 50.0 / dx
                alive_flag = 1 if probe.alive else 0
                score = (alive_flag, progress)
                if score > best_score:
                    best_score = score
                    best_action = first
            live.update(best_action[0], best_action[1])
            inputs.append(best_action)
        return inputs, live.won

    def _orb_press_canned(self, max_frames):
        """Greedy 'press whenever an orb is in tap range' canned chain."""
        work = [dict(o) for o in self.objects]
        sim = _SimPlayer(work, params=self.params)
        sim.trail = []
        orb_xs = self._orb_xs
        orb_cells = self._orb_cells
        inputs = []
        prev_pressed = False
        deadline = getattr(self, "_deadline", None)
        for _ in range(max_frames):
            if not sim.alive or sim.won:
                break
            if deadline is not None and _time.monotonic() > deadline:
                break
            if self._pump_events():
                break
            gx = int(sim.x) // CELL
            gy = int(sim.y) // CELL
            on_orb = False
            if gx in orb_xs or (gx + 1) in orb_xs or (gx - 1) in orb_xs:
                for dx in range(-1, 3):
                    for dy in range(-2, 3):
                        if (gx + dx, gy + dy) in orb_cells:
                            on_orb = True
                            break
                    if on_orb:
                        break
            held = on_orb
            pressed = on_orb and not prev_pressed
            sim.update(held, pressed)
            inputs.append((held, pressed))
            prev_pressed = held
        return inputs, sim.won

    # ------------------------------------------------------------------
    # Polish (input downgrade for replay robustness)
    # ------------------------------------------------------------------

    def _polish_and_return(self, waypoints, mirror_waypoints, inputs):
        if not inputs or self._cancelled:
            return waypoints, mirror_waypoints, inputs, True
        # Preserve coin count and checkpoint route from the input
        # chain — polish must not strip clicks that are gathering
        # pickups. ``_polish_inputs`` honours the floor counts via
        # its acceptance check.
        baseline_coins, baseline_ckpts = self._count_pickups(inputs)
        polished = self._polish_inputs(
            inputs, min_coins=baseline_coins,
            min_checkpoints=baseline_ckpts)
        if polished and polished != inputs:
            p_wp, p_mwp, p_won = self._replay_for_waypoints(polished)
            if p_won:
                return p_wp, p_mwp, polished, True
        return waypoints, mirror_waypoints, inputs, True

    def _count_pickups(self, inputs):
        """Replay ``inputs`` and return
        ``(coins_collected, checkpoints_passed_at_y)``.

        ``checkpoints_passed_at_y`` only counts crossings where the
        player was within 1.5 cells of the marker's y at the moment
        of x-crossing — same rule the heuristic uses. A column-only
        flyover at the wrong y is NOT a checkpoint pass; otherwise
        polish would happily drop the very click that made the
        height alignment.

        Used by polish to make sure cheaper-input swaps don't lose
        pickups the original chain was collecting.
        """
        if not inputs:
            return 0, 0
        work_objects = [dict(o) for o in self.objects]
        player = _SimPlayer(work_objects, params=self.params)
        player.trail = []
        ckpt_xs = self._checkpoint_xs
        ckpt_ys = self._checkpoint_ys
        index = 0  # next checkpoint to test for x-crossing
        n_passed_at_y = 0
        for held, pressed in inputs:
            player.update(held, pressed)
            if not player.alive:
                break
            while index < len(ckpt_xs) and player.x >= ckpt_xs[index]:
                if abs(player.y - ckpt_ys[index]) <= CELL * 1.5:
                    n_passed_at_y += 1
                # Always advance the index — the column has been
                # crossed regardless of y; we don't re-test it later.
                index += 1
            if player.won:
                break
        return len(player.coins_collected), n_passed_at_y

    def _polish_inputs(self, inputs, min_coins=0, min_checkpoints=0):
        """Downgrade each ``(T, T)`` press to ``(T, F)`` or ``(F, F)``
        when the simpler form leaves the post-frame physics state
        identical (no orb buffer consumed, no jump fired).

        ``min_coins`` and ``min_checkpoints`` are floor counts the
        polished chain must still satisfy — set by the caller from
        the pre-polish chain's pickup counts so the search doesn't
        lose its coin collection or checkpoint route to a "still
        wins" cheaper chain.

        O(N) amortised — replays the original chain ONCE building a
        snapshot list, then for each candidate change tests the trial
        action's resulting snapshot against the original's. Identical =
        accept (the rest of the chain follows the same trajectory).
        Different = run a full _verify to be safe.

        The previous implementation re-verified the full chain from
        frame 0 for every trial, which on a 2000-frame chain ran
        billions of physics steps. Profiling showed it was 86% of total
        solve time.
        """
        if not inputs:
            return list(inputs)
        polished = list(inputs)
        polish_deadline = _time.monotonic() + 5.0
        deadline = getattr(self, "_deadline", None)
        if deadline is not None:
            polish_deadline = min(polish_deadline, deadline)

        # Build snapshot chain — full snaps stored so the probe can
        # restore to frame i in O(1) per trial. SnapVals slot [0] is
        # what the equality check actually compares; the rest of the
        # snap is needed only for restore.
        work_objects = [dict(o) for o in self.objects]
        sim = _SimPlayer(work_objects, params=self.params)
        sim.trail = []
        snaps = [_snap(sim)]
        for held, pressed in polished:
            sim.update(held, pressed)
            snaps.append(_snap(sim))
            if not sim.alive or sim.won:
                break

        probe_objects = [dict(o) for o in self.objects]
        probe = _SimPlayer(probe_objects, params=self.params)
        probe.trail = []

        for i in range(len(polished)):
            if self._cancelled or self._pump_events():
                break
            if _time.monotonic() > polish_deadline:
                break
            held, pressed = polished[i]
            if not held and not pressed:
                continue
            if i + 1 >= len(snaps):
                break
            candidates = ((False, False), (True, False)) if pressed \
                else ((False, False),)
            # SnapVals tuple of the post-frame state under the original
            # input. Identical SnapVals after the trial input ⇒ same
            # future trajectory ⇒ trial is a free downgrade.
            target_sig = tuple(snaps[i + 1][0])
            accepted = None
            for cand in candidates:
                if cand == (held, pressed):
                    continue
                _restore(probe, snaps[i])
                probe.update(cand[0], cand[1])
                if not probe.alive:
                    continue
                # Compare just the SnapVals tuple (probe.x, .y, .vy,
                # mode, etc.) — read attributes directly to skip the
                # frozenset/anims allocations of a full _snap.
                trial_sig = (
                    probe.x, probe.y, probe.vy, probe.on_ground,
                    probe.alive, probe.won, probe.angle, probe.grav,
                    probe.frame, probe.mode, probe.move_speed,
                    probe.dash_timer, probe.input_buffer,
                    probe.teleport_cooldown, probe.target_cam_y,
                    probe.bg_preset, probe.color_index,
                    probe._grav_flip_grace, probe._wall_frames,
                    probe.mirror_input_buffer, probe.size,
                    probe.dash_vx, probe.dash_vy,
                    probe.flight_budget, probe._robot_thrust_disabled,
                )
                if trial_sig == target_sig:
                    accepted = cand
                    break
                # Different post-state — verify the trial still wins
                # AND preserves the chain's coin/checkpoint counts.
                # Without the pickup floor a polish swap could quietly
                # drop the very click that was grabbing a coin (still
                # wins the level, just empty-handed) which is exactly
                # the route the heuristic spent A* expansions on.
                won = False
                tail_snaps = [_snap(probe)]
                for j in range(i + 1, len(polished)):
                    h2, p2 = polished[j]
                    probe.update(h2, p2)
                    tail_snaps.append(_snap(probe))
                    if probe.won:
                        won = True
                        break
                    if not probe.alive:
                        break
                # Pickup-floor check.
                if won and (min_coins > 0 or min_checkpoints > 0):
                    new_coins = len(probe.coins_collected)
                    if new_coins < min_coins:
                        won = False
                    elif min_checkpoints > 0:
                        # Re-walk a fresh sim through the prefix +
                        # candidate to count checkpoint passes — the
                        # probe doesn't track them. Cheap relative
                        # to the slow-path replay we just did.
                        trial_full = (list(polished[:i]) + [cand]
                                      + list(polished[i + 1:]))
                        c_new, p_new = self._count_pickups(trial_full)
                        if c_new < min_coins or p_new < min_checkpoints:
                            won = False
                if won:
                    accepted = cand
                    polished[i] = cand
                    snaps = snaps[: i + 1] + tail_snaps
                    break
            if accepted is not None and accepted != (held, pressed):
                polished[i] = accepted
        return polished

    # ------------------------------------------------------------------
    # A* search (single-threaded, coin/checkpoint/probe-aware)
    # ------------------------------------------------------------------

    def _astar(self, max_frames, screen, clock, prefix_inputs=None,
               frontier_cap=None, attempt_idx=0, status_text="",
               probe_weight=1.0, time_budget=None):
        """Weighted A* over (snap, depth) state. Returns
        ``(waypoints, mirror_waypoints, inputs, won)``.

        Heuristic shape:
          * f = HEURISTIC_WEIGHT * h(x) + depth - progress
          * progress includes coin pickups, checkpoint passes, and
            probe-aligned presses (large signals).
          * pref (secondary key): click penalty, coin pull, checkpoint
            proximity, hazard-density tiebreak, learned death pessimism.

        Cancellation: pumped via ``_pump_events`` on a wall-clock cadence
        so ESC is responsive even mid-loop.
        """
        import heapq

        call_deadline = (_time.monotonic() + time_budget
                         if time_budget else None)

        cap = frontier_cap if frontier_cap is not None else self._frontier_cap()
        cap = max(16, int(cap))
        h_weight = self.HEURISTIC_WEIGHT
        click_pen = self.CLICK_PENALTY
        hold_pen = self.HOLD_PENALTY
        coin_bonus = self.COIN_BONUS
        ckpt_bonus = self.CHECKPOINT_BONUS

        end_x = self._end_x
        coin_xs = self._coin_xs
        probe_xs = self._probe_xs
        hazard_col = self._hazard_col
        hazard_get = hazard_col.get
        hazard_clearance = self._hazard_clearance
        clearance_get = hazard_clearance.get
        clearance_radius = int(self.CLEARANCE_RADIUS)
        clearance_pen = float(self.CLEARANCE_PENALTY)
        orb_xs = self._orb_xs
        h_recips = self._h_recips
        h_seg_end = self._h_seg_end
        h_cumul = self._h_cumul
        h_n_cells = self._h_n_cells
        _CELL_LOCAL = CELL
        ckpt_xs_list = self._checkpoint_xs
        ckpt_ys_list = self._checkpoint_ys
        n_ckpts = len(ckpt_xs_list)

        def _h_local(x):
            if end_x <= 0 or x >= end_x:
                return 0.0
            cell = int(x) // _CELL_LOCAL
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

        _TAP_LOOKAHEAD = 3
        _TAP_LOOKBACK = 1
        orb_xs_expanded = set()
        for ox in orb_xs:
            for dx in range(-_TAP_LOOKAHEAD, _TAP_LOOKBACK + 1):
                orb_xs_expanded.add(ox + dx)

        def _has_orb_near(gx):
            return gx in orb_xs_expanded

        work_objects = [dict(o) for o in self.objects]
        player = _SimPlayer(work_objects, params=self.params)
        player.trail = []

        nodes = [(-1, False, False)]
        prefix_terminal = 0
        if prefix_inputs:
            for held, pressed in prefix_inputs:
                player.update(held, pressed)
                nid = len(nodes)
                nodes.append((prefix_terminal, held, pressed))
                prefix_terminal = nid
                if player.won:
                    inputs = self._reconstruct(nodes, prefix_terminal)
                    wp, mwp, ok = self._replay_for_waypoints(inputs)
                    return wp, mwp, inputs, ok
                if not player.alive:
                    return [], [], [], False
        prefix_depth = prefix_terminal

        _X_BUCKET = 4

        def _key(snap_, x_val):
            return (int(x_val) // _X_BUCKET, _dedup_key(snap_))

        init_snap = _snap(player)
        open_heap = []
        heapq.heappush(
            open_heap,
            (h_weight * _h_local(player.x), 0.0, 0, init_snap,
             prefix_terminal, prefix_depth))
        counter = 1

        visited = {_key(init_snap, player.x): prefix_depth}
        best_partial_node = prefix_terminal
        best_alive_x = player.x

        stagnant_pops = 0
        h_min_seen = float("inf")
        pops_since_h_improved = 0
        STAGNATION_BASE = 32000
        STAGNATION_DUAL = 64000

        _DEATH_BUCKET_PX = CELL
        _DEATH_PEN_PER_HIT = 0.02
        _DEATH_PEN_MAX = 1.0
        death_counts = {}

        expansions = 0
        max_expansions = max_frames * 12
        last_paint = 0.0

        while open_heap:
            if expansions >= max_expansions:
                break
            # Cancellation — pump events on a wall-clock cadence so the
            # search is always responsive to ESC. Throttled, so the cost
            # is bounded.
            if self._pump_events() or self._budget_expired():
                break
            if call_deadline is not None and _time.monotonic() > call_deadline:
                break
            f, _neg_pref, _, snap, node_id, depth = heapq.heappop(open_heap)

            key = _key(snap, snap[0][_X])
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

            if mirror_active:
                options = [(False, False), (True, True), (True, False)]
            elif cand_mode in (MODE_BALL, MODE_UFO, MODE_CUBE,
                               MODE_SPIDER, MODE_SWING, MODE_ROBOT):
                options = [(False, False), (True, True), (True, False)]
            else:
                gx_now = int(vals[0]) // CELL
                if _has_orb_near(gx_now):
                    options = [(False, False), (True, True), (True, False)]
                else:
                    options = [(False, False), (True, False)]

            in_dash = int(vals[_DASH_TIMER]) > 0
            if in_dash:
                options = [(True, False), (False, False)]

            if (not in_dash and cand_mode in _TAP_PRUNABLE
                    and not vals[_ON_GROUND]):
                mirror_forbids = False
                m_snap = snap[_MIRROR]
                if m_snap is not None and len(m_snap) >= 6 and m_snap[5]:
                    mirror_forbids = True
                if not mirror_forbids:
                    gx = int(vals[0]) // CELL
                    if not _has_orb_near(gx):
                        options = [(False, False)]

            parent_pcount = len(snap[1])
            parent_coins = len(snap[6]) if len(snap) >= 7 else 0
            new_depth = depth + 1

            for held, pressed in options:
                _restore(player, snap)
                player.update(held, pressed)
                expansions += 1

                if player.won:
                    nid = len(nodes)
                    nodes.append((node_id, held, pressed))
                    inputs = self._reconstruct(nodes, nid)
                    wp, mwp, ok = self._replay_for_waypoints(inputs)
                    return wp, mwp, inputs, ok

                if not player.alive:
                    death_gx = int(player.x) // _DEATH_BUCKET_PX
                    death_counts[death_gx] = (
                        death_counts.get(death_gx, 0) + 1)
                    continue

                child_key = (int(player.x) // _X_BUCKET,
                             _player_dedup_key(player))
                prev_g = visited.get(child_key)
                if prev_g is not None and prev_g <= new_depth:
                    continue
                visited[child_key] = new_depth
                child_snap = _snap(player)

                # Heuristic shaping. Large progress signals stay in f
                # (they should actually move pop order), small biases
                # live in pref (the secondary tiebreak key).
                progress = 0.0
                pref = 0.0

                # Newly-passed orbs / pads / portals.
                newly_passed = len(player.passed) - parent_pcount
                if newly_passed > 0:
                    progress += newly_passed * 5.0

                # Newly-collected coins — strong reward so the search
                # actively prioritises coin pickups when they're on or
                # near the route.
                newly_coins = len(player.coins_collected) - parent_coins
                if newly_coins > 0:
                    progress += newly_coins * coin_bonus

                gx_now = int(player.x) // CELL
                pcx_now = float(player.x)

                # Probe-aligned press bonus — author placed a probe at
                # gx, so the bot should prefer to actually press near it.
                if pressed and probe_xs:
                    for px in probe_xs:
                        if abs(px - gx_now) <= 2:
                            progress += 0.6 * probe_weight
                            break

                # Bot checkpoints — author-marked (x, y) cells the
                # search should route through. Crossing one in x
                # AND being near it in y awards the full bonus;
                # crossing only in x awards a discounted version
                # (you got the column right but the wrong height).
                # Between checkpoints, the 2D euclidean distance to
                # the next one feeds a continuous progress signal so
                # the search doesn't just teleport-detect at the
                # crossing — every step closer to the marker is
                # rewarded.
                if n_ckpts:
                    parent_x = float(snap[0][_X])
                    pcy_now = float(player.y)
                    passed_now = sum(1 for cx in ckpt_xs_list if cx <= pcx_now)
                    passed_before = sum(
                        1 for cx in ckpt_xs_list if cx <= parent_x)
                    if passed_now > passed_before:
                        # Award per checkpoint passed this frame.
                        for i in range(passed_before, passed_now):
                            cy = ckpt_ys_list[i]
                            cx = ckpt_xs_list[i]
                            # y-proximity scaling: 1.0 at <=24 px,
                            # falls to 0.25 at ~CELL away. The bot
                            # still gets credit for crossing the x
                            # column even at the wrong y, but a
                            # spot-on pass earns the full bonus and
                            # heavily steers the search toward it.
                            dyp = abs(cy - pcy_now)
                            scale = max(0.25, 1.0 - dyp / (CELL * 1.5))
                            progress += ckpt_bonus * scale
                    # Continuous pull toward the next un-passed
                    # checkpoint. Y component is what makes the bot
                    # DIVE / RISE for a marker off the natural path.
                    # Reward INCREASES as the player gets closer
                    # (linear in proximity) so every step toward the
                    # marker shaves f and A* visibly bends the route
                    # through it. Magnitude scales with ckpt_bonus
                    # so author-placed markers have authority.
                    next_idx = passed_now
                    if next_idx < n_ckpts:
                        ncx = ckpt_xs_list[next_idx]
                        ncy = ckpt_ys_list[next_idx]
                        dxp = ncx - pcx_now
                        dyp = ncy - pcy_now
                        # Linear-proximity reward in 0..1, peaking
                        # to 1 when the player is on the marker.
                        # Range is 6 cells so the gradient kicks in
                        # well before the column rather than only at
                        # the last cell. Awarded as PROGRESS so f
                        # drops with each closer step — essential
                        # for A* to prefer the detour over the
                        # straight-line walk.
                        prox_range = CELL * 6.0
                        dxa = dxp if dxp >= 0 else -dxp
                        dya = dyp if dyp >= 0 else -dyp
                        prox = max(0.0,
                                   1.0 - (dxa + dya) / prox_range)
                        progress += ckpt_bonus * prox

                # Click penalty — added to the PRIMARY cost (via
                # ``progress``) so the search physically prefers fewer
                # presses, not just as a tiebreak. A press costs
                # ``click_pen`` frames of "depth"; a sustained hold on
                # a tap-mode bunny-hop chain costs the smaller
                # ``hold_pen``. The user-visible effect is "less spam,
                # more deliberate timing": the bot only presses when
                # the alternative is dying or stalling, not whenever
                # press happens to advance x by an epsilon.
                input_cost = 0.0
                if pressed:
                    input_cost += click_pen
                elif held and cand_mode in _TAP_PRUNABLE:
                    input_cost += hold_pen
                if input_cost:
                    progress -= input_cost

                # Soft coin pull — even when we're not collecting a
                # coin this frame, lean toward routes that move toward
                # the nearest coin in 2D. Pulls into the primary
                # ``progress`` key when a coin is within 6 cells so
                # the bot will actively detour up/down for one;
                # outside that range it's just a tiebreak in
                # ``pref``.
                if coin_xs:
                    near_coin = False
                    for dcx in range(0, 6):
                        if (gx_now + dcx) in coin_xs:
                            near_coin = True
                            break
                    if near_coin:
                        # Find a 2D nearest coin within reach, pull
                        # toward it hyperbolically.
                        py = float(player.y)
                        for o in self._coin_objs_for_gx.get(gx_now, ()):
                            cx, cy = o
                            dxp = cx - pcx_now
                            dyp = cy - py
                            dist = (dxp * dxp + dyp * dyp) ** 0.5
                            if dist < 1.0:
                                dist = 1.0
                            progress += min(coin_bonus * 0.3,
                                            coin_bonus * 20.0 / dist)
                            break
                    elif coin_xs:
                        pref += 0.05

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

                # Spike clearance — push the bot to keep breathing
                # room from spikes/saws instead of skimming them.
                # The clearance map stores Chebyshev distance to the
                # nearest hazard for cells inside ``CLEARANCE_RADIUS``;
                # we sample the player's centre cell PLUS the cell
                # one ahead so the search reacts before threading the
                # gap, not after. Penalty is in the PRIMARY cost so
                # it actually changes routing — distance 1 (immediately
                # adjacent) costs ``clearance_pen`` frames; distance
                # ``CLEARANCE_RADIUS`` costs roughly nothing. Cells far
                # from any hazard are absent from the dict (no penalty).
                if hazard_clearance:
                    gy_now = int(player.y) // CELL
                    d_here = clearance_get((gx_now, gy_now))
                    d_next = clearance_get((gx_now + 1, gy_now))
                    nearest = None
                    if d_here is not None and (nearest is None
                                               or d_here < nearest):
                        nearest = d_here
                    if d_next is not None and (nearest is None
                                               or d_next < nearest):
                        nearest = d_next
                    if nearest is not None:
                        # Linear taper: dist 1 → full penalty, dist
                        # ``CLEARANCE_RADIUS`` → ~0. ``progress`` is
                        # subtracted from f_new, so subtracting the
                        # penalty FROM progress adds it TO f_new.
                        scale = max(0.0,
                                    1.0 - (nearest - 1)
                                    / float(clearance_radius))
                        progress -= clearance_pen * scale

                f_new = h_weight * _h_local(player.x) + new_depth - progress
                nid = len(nodes)
                nodes.append((node_id, held, pressed))

                if player.x > best_alive_x:
                    best_alive_x = player.x
                    best_partial_node = nid

                heapq.heappush(
                    open_heap,
                    (f_new, -pref, counter, child_snap, nid, new_depth))
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

            # Repaint progress on a wall-clock cadence (5 Hz). The paint
            # itself pumps events too; the throttle keeps the inner loop
            # cheap on plateaus.
            if screen is not None:
                now = _time.monotonic()
                if now - last_paint > 0.2:
                    last_paint = now
                    if self._draw_progress(
                            screen, clock, expansions, best_alive_x,
                            max_expansions, len(open_heap), cap, attempt_idx,
                            status_text=status_text, any_dual=mirror_active):
                        break

        if best_partial_node > 0:
            inputs = self._reconstruct(nodes, best_partial_node)
        else:
            inputs = list(prefix_inputs) if prefix_inputs else []
        wp, mwp, ok = self._replay_for_waypoints(inputs)
        return wp, mwp, inputs, ok

    # Compat aliases — older callers and tests reference these names.
    _astar_search = _astar
    _beam_search = _astar

    def _reconstruct(self, nodes, terminal_id):
        out = []
        idx = terminal_id
        while idx > 0:
            parent, held, pressed = nodes[idx]
            out.append((held, pressed))
            idx = parent
        out.reverse()
        return out

    # ------------------------------------------------------------------
    # Reverse-DFS brute force
    # ------------------------------------------------------------------

    def _reverse_dfs(self, partial_inputs, screen, clock, max_frames):
        """At the deepest stuck point in ``partial_inputs``, walk back
        one frame at a time and try alternative actions, each followed
        by a wide-frontier forward A*. Returns
        ``(waypoints, mirror_waypoints, inputs, won)``."""
        depth = self._backtrack_depth()
        if depth <= 0 or not partial_inputs:
            wp, mwp, _ = self._replay_for_waypoints(partial_inputs)
            return wp, mwp, list(partial_inputs), False

        _, _, won_check, last_alive = self._verify(partial_inputs)
        if won_check:
            wp, mwp, ok = self._replay_for_waypoints(partial_inputs)
            return wp, mwp, list(partial_inputs), ok
        if last_alive <= 0:
            wp, mwp, _ = self._replay_for_waypoints(partial_inputs)
            return wp, mwp, list(partial_inputs), False

        all_options = ((False, False), (True, True), (True, False))
        best_inputs = list(partial_inputs)
        best_alive = last_alive
        best_wp, best_mwp = [], []

        # Per-branch budget so a single slow branch can't eat the whole
        # phase budget. Reverse-DFS gets ~25% of remaining wall-clock.
        phase_budget = self._phase_budget(0.25)
        if phase_budget is not None and phase_budget > 0:
            per_branch = phase_budget / max(1, depth * 2)
        else:
            per_branch = None

        for d in range(1, depth + 1):
            if self._pump_events() or self._budget_expired():
                break
            cut = last_alive - d
            if cut < 0:
                break
            original = (partial_inputs[cut]
                        if cut < len(partial_inputs) else None)
            for held, pressed in all_options:
                if (held, pressed) == original:
                    continue
                if self._pump_events() or self._budget_expired():
                    break
                prefix = list(partial_inputs[:cut]) + [(held, pressed)]
                horizon = max(max_frames,
                              len(prefix) + self.BRUTE_FRAMES)
                wp, mwp, inp, won = self._astar(
                    horizon, screen, clock,
                    prefix_inputs=prefix,
                    frontier_cap=self.BRUTE_FRONTIER,
                    time_budget=per_branch,
                    status_text=f"Reverse-DFS ({d}/{depth})")
                if won:
                    return wp, mwp, inp, True
                if inp:
                    _, _, _, branch_alive = self._verify(inp)
                    if branch_alive > best_alive:
                        best_alive = branch_alive
                        best_inputs = list(inp)
                        best_wp = wp
                        best_mwp = mwp

        if best_wp:
            return best_wp, best_mwp, best_inputs, False
        wp, mwp, _ = self._replay_for_waypoints(best_inputs)
        return wp, mwp, best_inputs, False

    def _brute_force_segment(self, prefix_inputs, n_frames, screen, clock,
                             retry_idx=0):
        return self._reverse_dfs(
            prefix_inputs, screen, clock,
            max(n_frames, len(prefix_inputs) + self.BRUTE_FRAMES))

    # ------------------------------------------------------------------
    # Progress UI
    # ------------------------------------------------------------------

    def _draw_progress(self, screen, clock, expansions, best_x,
                       max_expansions, n_open, cap, attempt,
                       status_text="", any_dual=False):
        """Repaint the solver progress screen. Returns True if the user
        pressed ESC. Pumps events directly so cancellation is detected
        on every paint regardless of inner-loop pump throttling."""
        from .graphics import txt
        level_pct = 0
        if self._end_x > 0:
            level_pct = min(100, max(0, int(best_x / self._end_x * 100)))
        screen.fill((10, 8, 24))
        txt(screen, "AUTO-BOT SEARCH", WIDTH // 2, HEIGHT // 2 - 86,
            32, (255, 180, 60), True)
        if status_text:
            txt(screen, status_text, WIDTH // 2, HEIGHT // 2 - 52,
                16, (180, 220, 255), True)
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
        # Force a pump regardless of throttle — paints are sparse and
        # we want ESC to register on every visible frame.
        self._last_pump = 0.0
        if self._pump_events(force=True):
            return True
        return False
