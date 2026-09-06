"""NumPy-vectorized batch simulator for the bot's hot path.

Runs N independent player candidates in lockstep using NumPy arrays so
the per-frame physics dispatch happens once across the whole batch
instead of N times in Python. Used by the bot's greedy lookahead and
pathfinder candidate evaluation when the level only contains features
this simulator handles natively.

Supported features (cube mode):
  * Gravity + clamped vy
  * Cube jump on held-input from ground
  * Block (T_BLOCK) collision — full cell AABB
  * Slab (T_SLAB) collision — half-cell AABB (rotation 0/90/180/270)
  * Spike + half-spike + saw kill — AABB hazard test
  * Speed portals — per-player ``move_speed`` updated on x-cross
  * End line — first-cross sets ``won``
  * Coin pickup count (informational; no physics effect)

Not supported (level fails ``BatchSim.is_compatible`` if present):
  * Ship / wave / ball / UFO / spider / swing / robot modes
  * Mini / big / dual / mode-change portals
  * Orbs, pads, gravity portals, dash orbs, teleport orbs
  * Move / color / BG / pulse / rotate / time-warp triggers
  * Slopes
  * Dual mode (mirror player)

The caller flow is:

    if BatchSim.is_compatible(objects):
        sim = BatchSim(objects, params, n=len(candidates))
        # run frame loop, calling sim.step(held_arr, pressed_arr)
    else:
        # fall back to per-candidate _SimPlayer simulation

The simulator is verified against ``Player.update`` frame-for-frame in
``test_game.py`` so any drift breaks the test suite immediately.
"""

from __future__ import annotations

import numpy as np

from .constants import (
    CELL, PLAYER_SIZE, MINI_PLAYER_SIZE, COLLISION_SUBSTEP_PX,
    SOLID_HITBOX_FRACTION,
    HEIGHT,
    T_BLOCK, T_SLAB, T_SPIKE, T_HALF_SPIKE, T_SAW,
    T_END, T_START, T_COIN, T_JUMP_PREDICTOR, T_BOT_CHECKPOINT,
    T_SPEED_SLOW, T_SPEED_NORMAL, T_SPEED_FAST, T_SPEED_FASTER,
    SPEED_VALUES,
)
from .physics import DEFAULT_PARAMS


# Types BatchSim handles natively. Anything else means the level falls
# back to per-candidate Player simulation.
_BATCH_COMPATIBLE_TYPES = frozenset({
    T_BLOCK, T_SLAB, T_SPIKE, T_HALF_SPIKE, T_SAW,
    T_END, T_START, T_COIN, T_JUMP_PREDICTOR, T_BOT_CHECKPOINT,
    T_SPEED_SLOW, T_SPEED_NORMAL, T_SPEED_FAST, T_SPEED_FASTER,
})


def is_compatible(objects):
    """Return True if every object in ``objects`` is something BatchSim
    can handle. Falls back to per-candidate Player simulation otherwise.

    Module-level entry point so callers don't need a class instance to
    decide whether to construct one.
    """
    for o in objects:
        t = o.get("t")
        if t not in _BATCH_COMPATIBLE_TYPES:
            return False
        if t == T_BLOCK and o.get("invisible"):
            # Invisible blocks still collide — supported.
            pass
        # Scaled solids: graphics.cell_rect honours scale, so the AABB
        # extraction below picks up scaled bounds correctly. No reject.
    return True


class BatchSim:
    """Vectorized cube-mode physics simulator running N players in
    lockstep."""

    def __init__(self, objects, params=None, n=1):
        if params is None:
            params = DEFAULT_PARAMS
        self.params = params
        self.n = int(n)
        self.frame_count = 0

        # ---- static level data --------------------------------------
        self._build_solid_aabbs(objects)
        self._build_hazard_aabbs(objects)
        self._build_speed_portals(objects)
        self._build_coin_centers(objects)
        end_xs = [o["x"] * CELL for o in objects if o["t"] == T_END]
        self._end_x = float(max(end_xs)) if end_xs else 0.0

        # ---- spawn point --------------------------------------------
        starts = [o for o in objects if o["t"] == T_START]
        if starts:
            s = min(starts, key=lambda o: (o["x"], o["y"]))
            spawn_x = float(s["x"] * CELL + (CELL - PLAYER_SIZE) / 2)
            spawn_y = float(s["y"] * CELL + (CELL - PLAYER_SIZE) / 2)
        else:
            spawn_x = float(3 * CELL + (CELL - PLAYER_SIZE) / 2)
            spawn_y = 10.0 * CELL - PLAYER_SIZE

        # ---- per-player state arrays --------------------------------
        n = self.n
        self.x = np.full(n, spawn_x, dtype=np.float64)
        self.y = np.full(n, spawn_y, dtype=np.float64)
        self.vy = np.zeros(n, dtype=np.float64)
        self.alive = np.ones(n, dtype=bool)
        self.won = np.zeros(n, dtype=bool)
        self.on_ground = np.zeros(n, dtype=bool)
        self.move_speed = np.full(n, params.base_move_speed, dtype=np.float64)
        self.size = np.full(n, PLAYER_SIZE, dtype=np.int32)
        # Yes-it's-an-int input buffer mirrors Player's behavior — a
        # press is "live" for ~6 frames. Cube auto-jump from ground
        # honours both ``input_held`` and ``input_buffer > 0``.
        self.input_buffer = np.zeros(n, dtype=np.int32)
        # Coin pickup count (informational for the bot's heuristic).
        # We track a count, not which coins, since the bot only uses
        # the count to score progress.
        self.coins_collected_count = np.zeros(n, dtype=np.int32)
        # x at frame start — needed for the end-line cross test the
        # same way Player uses it (so a player that spawns past the
        # finish line on frame 1 doesn't insta-win).
        self._x_at_frame_start = self.x.copy()

        # Track which speed portals + coins each player has consumed
        # so we don't re-fire them every frame. Bitmasks per player.
        nsp = self._speed_x.shape[0]
        ncoins = self._coin_x.shape[0]
        self._speed_consumed = np.zeros((n, nsp), dtype=bool)
        self._coin_consumed = np.zeros((n, ncoins), dtype=bool)

    # ------------------------------------------------------------------
    # Static level data builders
    # ------------------------------------------------------------------

    def _build_solid_aabbs(self, objects):
        """Block + slab AABBs as numpy arrays of (left, top, right, bottom)."""
        from .graphics import cell_rect, slab_rect
        rects = []
        for o in objects:
            t = o["t"]
            scale = float(o.get("scale", 1.0))
            if t == T_BLOCK:
                r = cell_rect(o["x"], o["y"], scale=scale)
                rects.append((r.left, r.top, r.right, r.bottom))
            elif t == T_SLAB:
                r = slab_rect(o["x"], o["y"], o.get("r", 0), scale=scale)
                rects.append((r.left, r.top, r.right, r.bottom))
        if rects:
            arr = np.asarray(rects, dtype=np.float64)
            self._blk_l = arr[:, 0]
            self._blk_t = arr[:, 1]
            self._blk_r = arr[:, 2]
            self._blk_b = arr[:, 3]
        else:
            self._blk_l = np.empty(0, dtype=np.float64)
            self._blk_t = np.empty(0, dtype=np.float64)
            self._blk_r = np.empty(0, dtype=np.float64)
            self._blk_b = np.empty(0, dtype=np.float64)

    def _build_hazard_aabbs(self, objects):
        """Spike, half-spike, saw hitboxes."""
        from .graphics import spike_hitboxes, saw_hitbox
        rects = []
        for o in objects:
            t = o["t"]
            if t in (T_SPIKE, T_HALF_SPIKE):
                scale = float(o.get("scale", 1.0))
                for r in spike_hitboxes(
                        o["x"], o["y"], rotation=o.get("r", 0),
                        half=(t == T_HALF_SPIKE), scale=scale):
                    rects.append((r.left, r.top, r.right, r.bottom))
            elif t == T_SAW:
                scale = float(o.get("scale", 1.0))
                r = saw_hitbox(o["x"], o["y"], scale=scale)
                rects.append((r.left, r.top, r.right, r.bottom))
        if rects:
            arr = np.asarray(rects, dtype=np.float64)
            self._haz_l = arr[:, 0]
            self._haz_t = arr[:, 1]
            self._haz_r = arr[:, 2]
            self._haz_b = arr[:, 3]
        else:
            self._haz_l = np.empty(0, dtype=np.float64)
            self._haz_t = np.empty(0, dtype=np.float64)
            self._haz_r = np.empty(0, dtype=np.float64)
            self._haz_b = np.empty(0, dtype=np.float64)

    def _build_speed_portals(self, objects):
        """Speed portal x positions + speed values, sorted by x.

        We model speed portals as a "crossed" event: when a player's
        center crosses a portal's x cell (from left), their move_speed
        is set to the portal's speed value. Player does this via
        Player.update's interactions pass, but the cube-mode hot path
        only depends on the resulting move_speed."""
        ports = sorted(
            ((int(o["x"]) * CELL + CELL // 2, SPEED_VALUES[o["t"]])
             for o in objects if o.get("t") in SPEED_VALUES),
            key=lambda p: p[0])
        if ports:
            arr = np.asarray(ports, dtype=np.float64)
            self._speed_x = arr[:, 0]
            self._speed_val = arr[:, 1]
        else:
            self._speed_x = np.empty(0, dtype=np.float64)
            self._speed_val = np.empty(0, dtype=np.float64)

    def _build_coin_centers(self, objects):
        coins = [(o["x"] * CELL + CELL / 2, o["y"] * CELL + CELL / 2)
                 for o in objects if o.get("t") == T_COIN]
        if coins:
            arr = np.asarray(coins, dtype=np.float64)
            self._coin_x = arr[:, 0]
            self._coin_y = arr[:, 1]
        else:
            self._coin_x = np.empty(0, dtype=np.float64)
            self._coin_y = np.empty(0, dtype=np.float64)

    # ------------------------------------------------------------------
    # Snap / restore (state vectors, used by pathfinder candidate eval)
    # ------------------------------------------------------------------

    def snapshot(self):
        """Return a dict of per-player state arrays. Cheap to copy
        with .copy() — used by candidate eval to checkpoint state
        before testing each candidate's toggle window."""
        return {
            "x": self.x.copy(), "y": self.y.copy(), "vy": self.vy.copy(),
            "alive": self.alive.copy(), "won": self.won.copy(),
            "on_ground": self.on_ground.copy(),
            "move_speed": self.move_speed.copy(),
            "size": self.size.copy(),
            "input_buffer": self.input_buffer.copy(),
            "coins": self.coins_collected_count.copy(),
            "speed_consumed": self._speed_consumed.copy(),
            "coin_consumed": self._coin_consumed.copy(),
            "frame": self.frame_count,
        }

    def restore(self, snap):
        self.x[:] = snap["x"]
        self.y[:] = snap["y"]
        self.vy[:] = snap["vy"]
        self.alive[:] = snap["alive"]
        self.won[:] = snap["won"]
        self.on_ground[:] = snap["on_ground"]
        self.move_speed[:] = snap["move_speed"]
        self.size[:] = snap["size"]
        self.input_buffer[:] = snap["input_buffer"]
        self.coins_collected_count[:] = snap["coins"]
        self._speed_consumed[:] = snap["speed_consumed"]
        self._coin_consumed[:] = snap["coin_consumed"]
        self.frame_count = snap["frame"]

    def broadcast_from(self, src_index):
        """Replicate state[src_index] into every player slot. Useful
        when starting a new candidate-eval batch all from the same
        starting state."""
        for arr in (self.x, self.y, self.vy, self.alive, self.won,
                    self.on_ground, self.move_speed, self.size,
                    self.input_buffer, self.coins_collected_count):
            arr[:] = arr[src_index]
        self._speed_consumed[:] = self._speed_consumed[src_index]
        self._coin_consumed[:] = self._coin_consumed[src_index]

    # ------------------------------------------------------------------
    # Frame step
    # ------------------------------------------------------------------

    def step(self, held, pressed):
        """Advance every player one physics frame.

        ``held`` and ``pressed`` are length-N bool arrays (or any
        sequence numpy can broadcast). The step mirrors Player.update's
        cube-mode dispatch. Players that died or won in earlier frames
        are skipped via the alive/won mask.
        """
        held = np.asarray(held, dtype=bool)
        pressed = np.asarray(pressed, dtype=bool)
        if held.shape != (self.n,) or pressed.shape != (self.n,):
            raise ValueError("held/pressed must be length-N bool arrays")

        # Live mask = players still in play this frame.
        live = self.alive & ~self.won
        if not np.any(live):
            self.frame_count += 1
            return

        self.frame_count += 1
        self._x_at_frame_start = self.x.copy()

        # ---- input buffer (frames-since-press, ~6) -------------------
        # On press, set buffer to 6; otherwise decrement.
        decremented = np.maximum(self.input_buffer - 1, 0)
        self.input_buffer = np.where(pressed, 6, decremented).astype(np.int32)

        # ---- gravity + jump (cube only) ------------------------------
        gravity = self.params.gravity
        jump_force = self.params.jump_force
        # Apply gravity only to live players.
        self.vy = np.where(live, self.vy + gravity, self.vy)
        np.clip(self.vy, -18.0, 18.0, out=self.vy)
        # Cube jump: live & on_ground & (held or buffer>0) — Player
        # gates jump on `mode_held`, which is `input_held` modulo the
        # spider-orb consumed flag (no orbs here, so just held).
        jump_mask = live & self.on_ground & held
        self.vy = np.where(jump_mask, jump_force, self.vy)
        # Player.update sets on_ground=False unconditionally before the
        # substep loop runs; we mirror that.
        self.on_ground[live] = False

        # ---- single-step movement + collision ------------------------
        # Cube mode caps |vy| at 18 and dx at 8 (faster speed portals
        # cap there too); both are well below CELL (50) so a single
        # step can't tunnel through a block, slab, or spike. The
        # substep loop in Player exists to handle ship/wave (vy up to
        # 13 with smaller substep precision needs); for cube the
        # collapsed step is exact.
        dx = np.where(live, self.move_speed, 0.0)
        size_f = self.size.astype(np.float64)
        inner_int = np.maximum(2, (size_f * SOLID_HITBOX_FRACTION).astype(np.int32))
        inner = inner_int.astype(np.float64)
        haz_shrink = np.maximum(2, (6 * size_f / PLAYER_SIZE).astype(np.int32)).astype(np.float64)

        mask = self.alive & ~self.won
        # ---- x advance + x-collision (kill on solid overlap) --------
        self.x = np.where(mask, self.x + dx, self.x)
        ix_l, ix_t, ix_r, ix_b = self._inner_bounds(size_f, inner)
        self._kill_on_solid_overlap(mask, ix_l, ix_t, ix_r, ix_b)
        mask = self.alive & ~self.won

        # ---- y advance + y-collision (snap or kill) -----------------
        self.y = np.where(mask, self.y + self.vy, self.y)
        ix_l, ix_t, ix_r, ix_b = self._inner_bounds(size_f, inner)
        self._resolve_y_collision(mask, ix_l, ix_t, ix_r, ix_b,
                                   size_f, self.vy)
        mask = self.alive & ~self.won

        # Inner-in-block re-check after y-snap (Player's _inner_in_block_dies).
        ix_l, ix_t, ix_r, ix_b = self._inner_bounds(size_f, inner)
        self._kill_on_solid_overlap(mask, ix_l, ix_t, ix_r, ix_b)
        mask = self.alive & ~self.won

        # ---- hazards (spikes/saws) ----------------------------------
        hl = self.x + haz_shrink
        ht = self.y + haz_shrink
        hr = self.x + size_f - haz_shrink
        hb = self.y + size_f - haz_shrink
        self._kill_on_hazard_overlap(mask, hl, ht, hr, hb)
        mask = self.alive & ~self.won

        # ---- end-line cross -----------------------------------------
        if self._end_x > 0:
            center_x = self.x + size_f / 2.0
            prev_center_x = self._x_at_frame_start + size_f / 2.0
            cross = mask & (prev_center_x < self._end_x) & (center_x >= self._end_x)
            self.won[cross] = True

        # ---- speed portal + coin pickup -----------------------------
        self._apply_speed_portals(mask, size_f)
        self._apply_coin_pickups(mask, size_f)

        # ---- end-of-frame ground adjacency probe ---------------------
        # Player runs this once per frame: if the inner hitbox is
        # within ~2 px of a block top, snap and set on_ground.
        live = self.alive & ~self.won
        if np.any(live):
            self._ground_adjacency_probe(live, size_f)

        # ---- screen-cutoff kill --------------------------------------
        # Player kills if y > target_cam_y + HEIGHT + 300 or
        # y < target_cam_y - 500. We don't track camera, so use a
        # simple absolute world-y threshold relative to the spawn
        # row — covers the "fell off screen" case for flat levels.
        # (BatchSim's compatible levels rarely have vertical scrolls.)
        far_below = self.y > 30 * CELL  # ~1500 px below playfield
        far_above = self.y < -10 * CELL
        self.alive[far_below | far_above] = False

    # ------------------------------------------------------------------
    # Vectorized collision helpers
    # ------------------------------------------------------------------

    def _inner_bounds(self, size_f, inner):
        """Return (left, top, right, bottom) of each player's centred
        inner solid hitbox."""
        cx = self.x + size_f / 2.0
        cy = self.y + size_f / 2.0
        half = inner / 2.0
        return cx - half, cy - half, cx + half, cy + half

    def _kill_on_solid_overlap(self, mask, l, t, r, b):
        """Kill any masked player whose inner hitbox overlaps any
        block AABB."""
        if self._blk_l.size == 0 or not np.any(mask):
            return
        # Broadcast per-player vs all-blocks: shape (N, M).
        bl = self._blk_l[None, :]
        bt = self._blk_t[None, :]
        br = self._blk_r[None, :]
        bb = self._blk_b[None, :]
        l_ = l[:, None]
        t_ = t[:, None]
        r_ = r[:, None]
        b_ = b[:, None]
        overlap = (l_ < br) & (r_ > bl) & (t_ < bb) & (b_ > bt)
        any_hit = overlap.any(axis=1)
        kill = mask & any_hit
        self.alive[kill] = False

    def _kill_on_hazard_overlap(self, mask, l, t, r, b):
        if self._haz_l.size == 0 or not np.any(mask):
            return
        hl = self._haz_l[None, :]
        ht = self._haz_t[None, :]
        hr = self._haz_r[None, :]
        hb = self._haz_b[None, :]
        l_ = l[:, None]
        t_ = t[:, None]
        r_ = r[:, None]
        b_ = b[:, None]
        overlap = (l_ < hr) & (r_ > hl) & (t_ < hb) & (b_ > ht)
        any_hit = overlap.any(axis=1)
        kill = mask & any_hit
        self.alive[kill] = False

    def _resolve_y_collision(self, mask, l, t, r, b, size_f, dy_step):
        """For each masked player, snap y to the block top/bottom
        their inner hitbox is overlapping. Mirrors Player's
        `_resolve_y_collision`: with dy_step >= 0 (falling under
        gravity=1), snap y to bt - size and set on_ground."""
        if self._blk_l.size == 0 or not np.any(mask):
            return
        bl = self._blk_l[None, :]
        bt = self._blk_t[None, :]
        br = self._blk_r[None, :]
        bb = self._blk_b[None, :]
        l_ = l[:, None]
        t_ = t[:, None]
        r_ = r[:, None]
        b_ = b[:, None]
        overlap = (l_ < br) & (r_ > bl) & (t_ < bb) & (b_ > bt)
        # For falling players (dy_step >= 0), pick the topmost block
        # they overlap. For rising players, the bottommost.
        falling = dy_step >= 0
        # Build per-player chosen block index = argmin of bt for
        # falling, argmax of bt for rising — among overlapping ones.
        any_hit = overlap.any(axis=1)
        # Players with no hit don't need adjustment.
        target_idx = mask & any_hit
        if not np.any(target_idx):
            return
        # Convert overlap to a "valid bt for argmin/max" matrix.
        bt_b = np.broadcast_to(self._blk_t, overlap.shape)
        bb_b = np.broadcast_to(self._blk_b, overlap.shape)
        # For falling: among overlap, argmin(bt). Set non-overlap to inf.
        falling_bt = np.where(overlap, bt_b, np.inf)
        rising_bt = np.where(overlap, bt_b, -np.inf)
        falling_idx = falling_bt.argmin(axis=1)
        rising_idx = rising_bt.argmax(axis=1)
        # Choose per-player index based on dy_step sign.
        chosen_idx = np.where(falling, falling_idx, rising_idx)
        chosen_bt = self._blk_t[chosen_idx]
        chosen_bb = self._blk_b[chosen_idx]
        # Apply: falling -> y = chosen_bt - size, vy=0, on_ground=True.
        # Rising  -> y = chosen_bb,           vy=0, on_ground=False.
        new_y_fall = chosen_bt - size_f
        new_y_rise = chosen_bb
        new_y = np.where(falling, new_y_fall, new_y_rise)
        # Only touch players that actually overlap.
        upd = target_idx
        self.y = np.where(upd, new_y, self.y)
        self.vy = np.where(upd, 0.0, self.vy)
        self.on_ground = np.where(upd & falling, True, self.on_ground)

    def _ground_adjacency_probe(self, mask, size_f):
        """End-of-frame: snap a player whose outer rect is dipping
        into a block from above to the surface, zero vy, and set
        on_ground. Mirrors Player._check_ground_adjacency for cube
        gravity=+1 (the only mode this BatchSim handles)."""
        if self._blk_l.size == 0 or not np.any(mask):
            return
        # Probe extends from (bottom - 1) into the inner-hitbox gap
        # below — Player uses gap = max(2, int(size*(1-FRAC)*0.5))
        # which is 11 for default size and 6 for mini.
        gap = np.maximum(2, (size_f * (1.0 - SOLID_HITBOX_FRACTION) * 0.5)
                         .astype(np.int32)).astype(np.float64)
        l = self.x
        r = self.x + size_f
        # p_top = py + size - 1 in Player; we mirror that.
        p_top = self.y + size_f - 1.0
        p_bottom = p_top + gap + 1.0
        bl = self._blk_l[None, :]
        bt = self._blk_t[None, :]
        br = self._blk_r[None, :]
        bb = self._blk_b[None, :]
        l_ = l[:, None]
        r_ = r[:, None]
        pt_ = p_top[:, None]
        pb_ = p_bottom[:, None]
        h_over = (l_ < br) & (r_ > bl)
        v_over = (pt_ < bb) & (pb_ > bt)
        overlap = h_over & v_over
        any_hit = overlap.any(axis=1)
        # Only snap when player isn't moving upward (vy >= 0 in
        # gravity=+1, matching Player's `if self.grav == 1 and
        # self.vy >= 0`).
        target = mask & any_hit & (self.vy >= 0)
        if not np.any(target):
            # Players that overlap but are rising still get on_ground
            # set; Player only does that for the snap branch though, so
            # skip both for parity.
            return
        # Snap to the closest block top above the probe.
        bt_b = np.broadcast_to(self._blk_t, overlap.shape)
        bt_valid = np.where(overlap, bt_b, np.inf)
        idx = bt_valid.argmin(axis=1)
        chosen_bt = self._blk_t[idx]
        new_y = chosen_bt - size_f
        self.y = np.where(target, new_y, self.y)
        self.vy = np.where(target, 0.0, self.vy)
        self.on_ground = np.where(target, True, self.on_ground)

    def _apply_speed_portals(self, mask, size_f):
        """When a player's center crosses a speed portal x, set their
        move_speed. One-shot per portal per player."""
        if self._speed_x.size == 0 or not np.any(mask):
            return
        center_x = self.x + size_f / 2.0
        prev_x = self._x_at_frame_start + size_f / 2.0
        # Per (player, portal) check: prev < portal_x <= center.
        cx = center_x[:, None]
        pcx = prev_x[:, None]
        sx = self._speed_x[None, :]
        crossed = (pcx < sx) & (cx >= sx)
        # Only count if not already consumed.
        crossed = crossed & ~self._speed_consumed
        # Skip dead/won players entirely.
        crossed = crossed & mask[:, None]
        if not np.any(crossed):
            return
        # For each player, if any portal crossed, take the highest x
        # one (latest-latched matches Player.update behavior).
        # argmax along portal axis returns first hit if no True; so
        # filter via any_crossed.
        any_crossed = crossed.any(axis=1)
        if not np.any(any_crossed):
            return
        # Find the rightmost crossed portal per player.
        masked_x = np.where(crossed, self._speed_x[None, :], -np.inf)
        idx = masked_x.argmax(axis=1)
        new_speed = self._speed_val[idx]
        self.move_speed = np.where(any_crossed, new_speed, self.move_speed)
        # Mark all just-crossed portals consumed for that player.
        self._speed_consumed |= crossed

    def _apply_coin_pickups(self, mask, size_f):
        """Increment coin count when a player's outer rect overlaps a
        coin's center. One-shot per coin per player."""
        if self._coin_x.size == 0 or not np.any(mask):
            return
        l = self.x
        t = self.y
        r = self.x + size_f
        b = self.y + size_f
        cx = self._coin_x[None, :]
        cy = self._coin_y[None, :]
        l_ = l[:, None]
        t_ = t[:, None]
        r_ = r[:, None]
        b_ = b[:, None]
        inside = (cx >= l_) & (cx <= r_) & (cy >= t_) & (cy <= b_)
        new_pickup = inside & ~self._coin_consumed & mask[:, None]
        if not np.any(new_pickup):
            return
        self.coins_collected_count += new_pickup.sum(axis=1).astype(np.int32)
        self._coin_consumed |= new_pickup
