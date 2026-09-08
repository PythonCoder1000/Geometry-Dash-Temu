"""Shared headless simulation for the bots.

Both bots (``human.HumanBot`` and ``loophole.LoopholeBot``) search over
input sequences by replaying them against :class:`SimPlayer` — a
``Player`` subclass that swaps the dict-based spatial lookup for a flat
array grid and drops trail bookkeeping.  All physics is inherited
unchanged so a search result replays frame-for-frame against the real
game.

``snapshot`` / ``restore`` capture and rewind the full mutable world
state (player, mirror body, move-trigger animations, displaced objects,
collected coins) so a search can branch without rebuilding the level.
``dedup_key`` / ``player_dedup_key`` bucket a state for duplicate
pruning.
"""

from typing import NamedTuple

from ..constants import (
    CELL, PLAYER_SIZE, ORB_TYPES, T_TELEPORT_PORTAL, PHYSICS_TPS,
    MODE_CUBE, MODE_SHIP, MODE_WAVE, MODE_UFO, MODE_ROBOT,
)

# ``passed`` entries for these types gate a real future action (a
# not-yet-fired orb/portal can still be clicked; a fired one can't), so
# they have to be part of the dedup key — see the comment inside
# ``dedup_key`` for why.
_DEDUP_TRACKED_PASSED_TYPES = ORB_TYPES | {T_TELEPORT_PORTAL}
from ..player import Player, _NON_TRIGGER_TYPES, is_non_trigger

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
    dash_flip_on_end: bool
    hold_consumed: bool
    mirror_input_buffer: int
    size: int
    dash_vx: float
    dash_vy: float
    flight_budget: int
    robot_thrust_disabled: bool
    wave_vy_smooth: float = 0.0
    time_warp: float = 1.0
    jump_block_armed: bool = False


# ---------------------------------------------------------------------------
# Fast simulation player with spatial grid
# ---------------------------------------------------------------------------

class SimPlayer(Player):
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
        # Keyed by position in `objects`, not id() — restore() uses this
        # to resolve the portable indices snapshot() embeds for moved
        # objects/animations, which must resolve correctly even when
        # restoring a snapshot taken from a *different* SimPlayer
        # instance (their independently-copied dicts have different
        # id()s but the same list order).
        self._obj_index = {i: o for i, o in enumerate(objects)}
        self._nearby_cache_key = None
        self._nearby_cache_result = []
        self._nearby_trigger_cache_key = None
        self._nearby_trigger_cache_result = []
        super().__init__(objects, params=params)
        # Solver probe sees bot-only objects by default — that's the
        # whole point of the "bot only" toggle: the bot must reason
        # about the phantom hazard even though the real player walks
        # through it. Must be set *after* super().__init__() /
        # reset(), which otherwise forces this back to False.
        self._bot_visibility = True

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
            # Tracked so _spatial_rebucket can find (and remove) an
            # object's *previous* slot after a move-trigger animation
            # displaces it, without rescanning every object in the
            # level to find it.
            o["_cell"] = (o["x"], o["y"])
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
            # Solvers set ``_bot_visibility = True`` themselves when
            # they want bot-only phantom hazards to count.
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
        bot_vis = bool(getattr(self, "_bot_visibility", False))
        cache_key = (left, top, right, bottom, extra, bot_vis)
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
        if not bot_vis and result:
            for o in result:
                if o.get("_bot_only"):
                    result = [o for o in result
                              if not o.get("_bot_only")]
                    break
        self._nearby_trigger_cache_key = cache_key
        self._nearby_trigger_cache_result = result
        return result

    def _rebuild_grid(self):
        self._init_grid(self.objects)
        self._nearby_cache_key = None
        self._nearby_trigger_cache_key = None

    def _spatial_rebucket(self, obj):
        """Move ``obj`` to its new grid cell in place, instead of the
        base class's dict-based ``_spatial_index`` update.

        SimPlayer's own lookups (``_nearby_for_aabb``) read the flat
        array grid, not ``_spatial_index`` — so the base implementation
        here would just be wasted work. This used to be handled by
        overriding ``_step_move_animations`` to call ``_init_grid``
        (a full rebuild over every object in the level) after *any*
        animation stepped, every single frame one was active. On a
        level with many move triggers that's the dominant cost of a
        search by a wide margin (profiled at ~45% of total wall time
        on a 342-object level) for a change that only ever touches one
        object. Bucket-swapping just that object is the same operation
        ``_rebuild_spatial_index``/``_spatial_rebucket`` already do for
        the real ``Player`` class — SimPlayer just wasn't using it.
        """
        old = obj.get("_cell")
        new = (obj["x"], obj["y"])
        if old == new:
            return
        ox, oy, w, h = self._grid_ox, self._grid_oy, self._grid_w, self._grid_h
        trigger = not is_non_trigger(obj)

        def _idx(cell):
            gx = cell[0] - ox
            gy = cell[1] - oy
            if 0 <= gx < w and 0 <= gy < h:
                return gy * w + gx
            return None

        if old is not None:
            oidx = _idx(old)
            if oidx is not None:
                bucket = self._grid_arr[oidx]
                if bucket is not None:
                    try:
                        bucket.remove(obj)
                    except ValueError:
                        pass
                    if not bucket:
                        self._grid_arr[oidx] = None
                if trigger:
                    tbucket = self._trigger_grid_arr[oidx]
                    if tbucket is not None:
                        try:
                            tbucket.remove(obj)
                        except ValueError:
                            pass
                        if not tbucket:
                            self._trigger_grid_arr[oidx] = None

        nidx = _idx(new)
        obj["_cell"] = new
        if nidx is None:
            # The move carried the object outside the grid's
            # precomputed bounds (extents of every object at
            # construction time, plus a fixed margin) — rare, since
            # in-level animations don't normally travel further than
            # the level's own extents. Only this case still needs a
            # full rebuild.
            self._rebuild_grid()
            return
        cell = self._grid_arr[nidx]
        if cell is None:
            self._grid_arr[nidx] = [obj]
        else:
            cell.append(obj)
        if trigger:
            tcell = self._trigger_grid_arr[nidx]
            if tcell is None:
                self._trigger_grid_arr[nidx] = [obj]
            else:
                tcell.append(obj)
        self._nearby_cache_key = None
        self._nearby_trigger_cache_key = None

    def update(self, input_held, input_pressed):
        super().update(input_held, input_pressed)
        if self.trail:
            self.trail.clear()


# ---------------------------------------------------------------------------
# Snapshot helpers
# ---------------------------------------------------------------------------

def build_obj_index(player):
    """Compatibility shim — populates the per-instance obj index used by
    ``restore`` to translate snap ids back to live object refs."""
    player._obj_index = {i: o for i, o in enumerate(player.objects)}


def snapshot(player):
    """Capture player state as a tuple-based snapshot."""
    vals = SnapVals(
        player.x, player.y, player.vy, player.on_ground, player.alive,
        player.won, player.angle, player.grav, player.frame, player.mode,
        player.move_speed, player.dash_timer, player.input_buffer,
        player.teleport_cooldown, player.target_cam_y, player.bg_preset,
        player.color_index, player._dash_flip_on_end, player._hold_consumed,
        player.mirror_input_buffer, player.size,
        player.dash_vx, player.dash_vy,
        player.flight_budget,
        player.thrust_disabled,
        player.wave_vy_smooth,
        player.time_warp,
        player._jump_block_armed,
    )
    passed = frozenset(player.passed)
    anims = player.move_animations
    if anims:
        oid_index = player._oid_index
        anims = tuple(
            (oid_index[id(a['obj'])], a['sx'], a['sy'], a['ex'], a['ey'],
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
        for i, o in enumerate(player.objects):
            if '_fx' in o or '_fy' in o:
                obj_pos_list.append((i, o['x'], o['y'],
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
    held_orbs = frozenset(player.held_orbs)
    return (vals, passed, anims, obj_pos, mirror, mirror_passed, coins,
            held_orbs)


def restore(player, snap):
    """Restore player state from snapshot (tolerates 4/5/6/7/8 length
    variants so older on-disk caches still load)."""
    n = len(snap)
    held_orbs = frozenset()
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
    elif n == 7:
        vals, passed, anims, obj_pos, mirror, mirror_passed, coins = snap
    else:
        (vals, passed, anims, obj_pos, mirror, mirror_passed, coins,
         held_orbs) = snap
    (player.x, player.y, player.vy, player.on_ground, player.alive,
     player.won, player.angle, player.grav, player.frame, player.mode,
     player.move_speed, player.dash_timer, player.input_buffer,
     player.teleport_cooldown, player.target_cam_y, player.bg_preset,
     player.color_index, player._dash_flip_on_end, player._hold_consumed,
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
        player.flight_budget = int(player.params.robot_flight_seconds * PHYSICS_TPS)
    if len(vals) >= 25:
        player.thrust_disabled = bool(vals[24])
    else:
        player.thrust_disabled = False
    if len(vals) >= 27:
        player.wave_vy_smooth = float(vals[25])
        player.time_warp = float(vals[26])
    else:
        player.wave_vy_smooth = 0.0
        player.time_warp = 1.0
    if len(vals) >= 28:
        player._jump_block_armed = bool(vals[27])
    else:
        player._jump_block_armed = False
    player.passed = set(passed)
    player.held_orbs = set(held_orbs)
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
    # Both loops below used to just flag need_rebuild and let a single
    # player._rebuild_grid() at the end redo the *entire* level's grid
    # placement — for a full rebuild's cost regardless of how many
    # objects actually moved. restore() runs on every probe restore
    # (several times per simulated frame across the search's probes),
    # so on any level with even one ever-moved object this was by far
    # the dominant cost of a search (profiled at ~45% of wall time on
    # a 342-object level). _spatial_rebucket only touches the object
    # that actually moved, so call it per-object here instead — same
    # fix as SimPlayer._spatial_rebucket for _step_move_animations.
    ever_moved = getattr(player, "_ever_moved", None)
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
                player._spatial_rebucket(o)
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
            player._spatial_rebucket(o)
    if mirror is None:
        player.mirror = None
    else:
        if len(mirror) == 6:
            my, mvy, mgrav, mog, mang, malive = mirror
            mmode = MODE_CUBE
            msize = PLAYER_SIZE
            mfb = int(player.params.robot_flight_seconds * PHYSICS_TPS)
            mtd = False
        elif len(mirror) == 8:
            my, mvy, mgrav, mog, mang, malive, mmode, msize = mirror
            mfb = int(player.params.robot_flight_seconds * PHYSICS_TPS)
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


def dedup_key(snap):
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
        teleport_cooldown = vals.teleport_cooldown
        mirror_input_buffer = vals.mirror_input_buffer
        size = vals.size
        move_speed = vals.move_speed
    else:
        mode = vals[9]
        y = vals[1]
        vy = vals[2]
        grav = vals[7]
        on_ground = vals[3]
        input_buffer = vals[12]
        dash_timer = vals[11]
        teleport_cooldown = vals[13]
        mirror_input_buffer = vals[19]
        size = vals[20]
        move_speed = vals[10]
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
    # A one-shot orb/portal already fired closes off a real future
    # action that an otherwise-identical position/velocity/mode state
    # (from before the orb was used) still has open — most visibly a
    # *backward* teleport orb, whose destination often lands right back
    # in a bucket the search already visited, at shallower depth, before
    # the orb was ever used. Without this, that earlier, orb-still-live
    # visit wins the dedup and the branch that actually used the orb —
    # which can reach places the other branch cannot — gets silently
    # discarded. Only orb/portal types are tracked, not the full
    # ``passed`` set, so this stays cheap.
    passed = snap[1] if len(snap) > 1 else ()
    passed_orbs = (tuple(sorted(
        k for k in passed if k[0] in _DEDUP_TRACKED_PASSED_TYPES))
        if passed else ())
    base = (
        y_bucket, vy_bucket, grav, mode, on_ground,
        1 if input_buffer > 0 else 0,
        1 if dash_timer > 0 else 0,
        1 if teleport_cooldown > 0 else 0,
        int(size), round(move_speed, 4),
        anim_key, obj_pos_key, passed_orbs,
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


def player_dedup_key(player):
    """Same as ``dedup_key(snapshot(player))`` but reads attributes
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
        oid_index = player._oid_index
        anim_key = tuple(sorted(
            (oid_index[id(a['obj'])], a['frame']) for a in anims))
    else:
        anim_key = ()
    # Match snapshot()'s filter exactly: include any ever-moved object
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
    # See dedup_key's comment: a fired one-shot orb/portal has to be
    # part of the key or a backward teleport's destination can alias
    # with an earlier, shallower visit where the orb was still live.
    passed_orbs = (tuple(sorted(
        k for k in player.passed if k[0] in _DEDUP_TRACKED_PASSED_TYPES))
        if player.passed else ())
    base = (
        y_bucket, vy_bucket, player.grav, mode, player.on_ground,
        1 if player.input_buffer > 0 else 0,
        1 if player.dash_timer > 0 else 0,
        1 if player.teleport_cooldown > 0 else 0,
        int(player.size), round(player.move_speed, 4),
        anim_key, obj_pos_key, passed_orbs,
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
