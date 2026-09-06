"""Loophole-finder bot — follows a drawn path, but takes shortcuts.

The user draws a route (the editor's Bot Path tool, or the hint overlay
in play).  This bot's objective is deliberately *not* "reproduce that
route": it is "beat the level while staying near that route, deviating
wherever deviating works".  Concretely:

* :class:`PathFollowController` reproduces the drawn line as closely as
  the physics allows.  It is a closed-loop PD-style regulator with a
  per-mode lookahead — the live controller the editor's K key drives.
* :class:`LoopholeBot` runs that controller to get a seed, then hands
  the seed to the human bot's search machinery with a *path-adherence
  bias* layered onto the cost function.  Staying near the drawn line is
  rewarded, but it is only a bias — the search is free to leave the line
  entirely when leaving it reaches the end wall sooner, and the same
  bias is what pulls a strayed run back onto the line afterwards.

The distinction from the human bot is the objective, not the machinery:
the human bot optimises "win, plausibly"; this one optimises "win, near
this line, and tell me where the line was wrong".

Both are held to the same one-button input model — a loophole a human
could not physically input is not a loophole worth reporting.
"""

import os

from ..constants import (
    CELL, PLAYER_SIZE,
    MODE_CUBE, MODE_SHIP, MODE_BALL, MODE_WAVE, MODE_UFO, MODE_SPIDER,
    MODE_SWING,
    HAZARD_TYPES, SOLID_TYPES,
    T_DASH_ORB,
)
from .action_space import HUMAN, DWELL_CAP
from .human import HumanBot
from .sim import SimPlayer

# Frames of lookahead per mode — roughly one input-to-effect cycle
# (a cube jump arc, a ship thrust arc).
LOOKAHEAD_BY_MODE = {
    MODE_CUBE:   6,
    MODE_SHIP:   8,
    MODE_UFO:    5,
    MODE_BALL:   5,
    MODE_WAVE:   3,
    MODE_SPIDER: 4,
    MODE_SWING:  4,
}

# Dead-zone (pixels) per mode — how far off the line the controller
# tolerates before acting. Scaled by speed in ``compute_input``.
THRESHOLD_BY_MODE = {
    MODE_CUBE:   10,
    MODE_SHIP:   4,
    MODE_UFO:    8,
    MODE_BALL:   10,
    MODE_WAVE:   0,
    MODE_SPIDER: 14,
    MODE_SWING:  4,
}

# Half-width of the corridor the search treats as "on the drawn path".
PATH_CORRIDOR_PX = CELL * 2

# How hard the search is pulled toward the line, in the same units as
# A*'s frame-depth cost.  Large enough to bend a route through the
# corridor, small enough that a genuinely faster off-path line wins.
PATH_BIAS_WEIGHT = 1.5

DEFAULT_INPUT_FILE = "level_bot_inputs.txt"


class DrawnPath:
    """A drawn route, queryable as target-y at any world x."""

    def __init__(self, waypoints):
        pts = sorted(waypoints, key=lambda p: p[0])
        clean = []
        for p in pts:
            if not clean or p[0] != clean[-1][0]:
                clean.append(p)
            else:
                clean[-1] = p
        self.points = clean

    def __bool__(self):
        return bool(self.points)

    @property
    def end_x(self):
        return self.points[-1][0] if self.points else 0.0

    def target_y(self, x):
        """Interpolated y at world ``x``, or None when the path is empty."""
        wps = self.points
        if not wps:
            return None
        if len(wps) == 1:
            return wps[0][1]
        if x <= wps[0][0]:
            return wps[0][1]
        if x >= wps[-1][0]:
            return wps[-1][1]
        lo, hi = 0, len(wps) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if wps[mid][0] <= x:
                lo = mid
            else:
                hi = mid
        x0, y0 = wps[lo]
        x1, y1 = wps[hi]
        span = x1 - x0
        if span <= 1e-9:
            return y0
        return y0 + (y1 - y0) * (x - x0) / span

    def offset(self, cx, cy):
        """Vertical distance from the line at ``cx``, or 0 past its end.

        Past the last waypoint the user drew nothing, so there is no
        line to be off: the search gets no bias there and is free to
        finish however it likes. ``target_y`` still clamps, because the
        live controller does need a value to steer toward.
        """
        if not self.points or cx > self.points[-1][0]:
            return 0.0
        ty = self.target_y(cx)
        if ty is None:
            return 0.0
        return abs(cy - ty)


class PathFollowController:
    """Follows a drawn path by choosing a button state each frame.

    Implements the ``bot_controller`` protocol ``play.run_play`` calls.
    Output is a single held boolean per frame; the press edge is derived,
    so the controller can no more pick between overlapping orbs than a
    player can.
    """

    # Frames a flipped hold decision must persist before the output
    # actually toggles.  1 = per-frame flap, 3+ = visibly laggy; 2 kills
    # PD jitter on near-zero error while still reacting inside ~33 ms.
    HOLD_CONFIRM_FRAMES = 2

    def __init__(self, waypoints, objects=None, model=HUMAN):
        self.path = DrawnPath(waypoints)
        self.model = model
        self.inputs = []
        self.frame = 0
        self._prev_held = False
        self._dwell = DWELL_CAP

        self._hazard_cells = set()
        self._solid_cells = set()
        self._dash_orb_cells = set()
        if objects:
            self.bind_objects(objects)

        self._hold_state = False
        self._hold_flip_confirm = 0

    # ---- level geometry ------------------------------------------------

    def bind_objects(self, objects):
        self._hazard_cells = {(o["x"], o["y"]) for o in objects
                              if o["t"] in HAZARD_TYPES}
        self._solid_cells = {(o["x"], o["y"]) for o in objects
                             if o["t"] in SOLID_TYPES}
        # The PD logic presses to clear hazards and to flip gravity, so
        # it has no reason of its own to fire a dash orb — it would sail
        # straight through one. Stamping a hold as the player enters the
        # cell lets the engine activate whichever orb is actually there.
        self._dash_orb_cells = {(o["x"], o["y"]) for o in objects
                                if o["t"] == T_DASH_ORB}

    def hazard_ahead(self, gx_from, gx_to, gy_center, y_tol=1,
                      follow_path=False):
        if not self._hazard_cells or gx_to < gx_from:
            return False
        for gx in range(gx_from, gx_to + 1):
            center = gy_center
            if follow_path:
                ty = self.path.target_y(gx * CELL + CELL // 2)
                if ty is not None:
                    center = int(ty // CELL)
            for dy in range(-y_tol, y_tol + 1):
                if (gx, center + dy) in self._hazard_cells:
                    return True
        return False

    def path_crosses_hazard(self, pcx, pcy, vx, vy, frames, y_tol=1):
        """True if straight-line motion crosses a hazard within ``frames``.

        Used by the flight modes to check that the PD controller's chosen
        direction will not fly into a spike inside the control horizon.
        """
        if not self._hazard_cells or frames <= 0:
            return False
        for k in range(1, frames + 1):
            gx = int((pcx + vx * k) // CELL)
            gy = int((pcy + vy * k) // CELL)
            for dy in range(-y_tol, y_tol + 1):
                if (gx, gy + dy) in self._hazard_cells:
                    return True
        return False

    def mirror_crosses_hazard(self, player, held, pressed, frames):
        """True if the dual mirror would fly into a hazard under ``held``.

        First-order on purpose: one frame of the mirror's own physics,
        then a linear extrapolation.  Enough to catch "ship thrusts up,
        mirror wave ploughs into a spike" without duplicating the physics
        loop.  The two bodies share one input, so the controller has to
        pick a direction that keeps both alive.
        """
        m = getattr(player, "mirror", None)
        if m is None or not m.get("alive", False):
            return False
        if not self._hazard_cells or frames <= 0:
            return False
        mmode = m.get("mode", MODE_CUBE)
        mgrav = m["grav"]
        msize = int(m.get("size", PLAYER_SIZE))
        speed = max(1.0, player.move_speed)
        params = player.params
        mvy = m["vy"]
        if mmode == MODE_SHIP:
            mvy += params.ship_gravity * mgrav
            if held:
                mvy -= params.ship_thrust * mgrav
        elif mmode == MODE_WAVE:
            mvy = speed * (-1 if held else 1) * mgrav
        elif mmode == MODE_UFO:
            mvy += params.gravity * mgrav
            if held and m.get("on_ground", False):
                mvy = params.jump_force * mgrav
            elif pressed and not m.get("on_ground", False):
                mvy = params.ufo_jump_force * mgrav
        elif mmode == MODE_SWING:
            mvy += params.gravity * mgrav
        elif mmode == MODE_BALL:
            mvy += params.gravity * mgrav
            if pressed and m.get("on_ground", False):
                mvy = params.ball_flip_force * (-mgrav)
        elif mmode == MODE_SPIDER:
            # A press resolves the teleport instantly, so extrapolating
            # the fall would be a false positive. Skip the check.
            if pressed and m.get("on_ground", False):
                return False
            mvy += params.gravity * mgrav
        else:
            mvy += params.gravity * mgrav
            if held and m.get("on_ground", False):
                mvy = params.jump_force * mgrav
        return self.path_crosses_hazard(
            player.x + msize / 2, m["y"] + msize / 2, speed, mvy, frames)

    # ---- hold hysteresis -----------------------------------------------

    def hysteretic_hold(self, want_hold):
        if want_hold == self._hold_state:
            self._hold_flip_confirm = 0
        else:
            self._hold_flip_confirm += 1
            if self._hold_flip_confirm >= self.HOLD_CONFIRM_FRAMES:
                self._hold_state = want_hold
                self._hold_flip_confirm = 0
        return self._hold_state

    def get_target_y(self, x):
        return self.path.target_y(x)

    # ---- control -------------------------------------------------------

    def compute_input(self, player):
        """Decide this frame's button state; returns ``(held, pressed)``."""
        return self._emit(self._want_hold(player))

    def _emit(self, want_hold):
        """Apply the dwell rule and derive the press edge."""
        if want_hold != self._prev_held and self._dwell < self.model.min_dwell:
            want_hold = self._prev_held
        pressed = self.model.edge(want_hold, self._prev_held)
        self._dwell = (1 if want_hold != self._prev_held
                       else min(DWELL_CAP, self._dwell + 1))
        self._prev_held = want_hold
        self.inputs.append((want_hold, pressed))
        self.frame += 1
        return want_hold, pressed

    def _want_hold(self, player):
        # A directional dash ends the moment the button is released, so
        # hold for its full duration.
        if getattr(player, "dash_timer", 0) > 0:
            return True

        size = getattr(player, "size", PLAYER_SIZE)
        pcx = player.x + size / 2
        pcy = player.y + size / 2

        if self._dash_orb_cells:
            gx_now = int(pcx // CELL)
            gy_now = int(pcy // CELL)
            for dgx in range(0, 3):
                for dgy in (-1, 0, 1):
                    if (gx_now + dgx, gy_now + dgy) in self._dash_orb_cells:
                        return True

        mode = player.mode
        grav = player.grav
        speed = max(1.0, player.move_speed)
        look = LOOKAHEAD_BY_MODE.get(mode, 5)
        future_x = pcx + look * speed

        target_now = self.path.target_y(pcx)
        target_future = self.path.target_y(future_x)
        if target_now is None and target_future is None:
            return False
        if target_now is None:
            target_now = target_future
        if target_future is None:
            target_future = target_now

        threshold = THRESHOLD_BY_MODE.get(mode, 10) * (speed / 5.0)
        error_now = pcy - target_now      # +ve → below the line
        error_future = pcy - target_future

        if mode == MODE_WAVE:
            # Fly angle matters more than exact position: blend the two
            # errors and act on the average displacement.
            blended = 0.35 * error_now + 0.65 * error_future
            want_hold = blended > 0 if grav == 1 else blended < 0
            return self.hysteretic_hold(
                self.avoid_hazards(player, want_hold, look,
                                    lambda h: speed * (-1 if h else 1) * grav,
                                    pcx, pcy, speed))

        if mode == MODE_SHIP:
            v_drift = player.vy + player.params.ship_gravity * look * grav
            y_drift = pcy + (player.vy + v_drift) * 0.5 * look
            drift_err = y_drift - target_future
            want_hold = (drift_err > threshold if grav == 1
                         else drift_err < -threshold)

            def _mean_vy(h):
                accel = player.params.ship_gravity * grav
                if h:
                    accel -= player.params.ship_thrust * grav
                return player.vy + accel * look * 0.5

            return self.hysteretic_hold(
                self.avoid_hazards(player, want_hold, look, _mean_vy,
                                    pcx, pcy, speed))

        if mode == MODE_UFO:
            need_up = (grav == 1 and error_future > threshold
                       and player.vy * grav > -4)
            need_down = (grav == -1 and error_future < -threshold
                         and player.vy * grav > -4)
            return need_up or need_down

        if mode in (MODE_SWING, MODE_BALL, MODE_SPIDER):
            # All three act on a press: swing flips gravity, ball flips
            # on the ground, spider teleports to the opposite surface.
            want = (error_future > threshold if grav == 1
                    else error_future < -threshold)
            if mode in (MODE_BALL, MODE_SPIDER) and not player.on_ground:
                return False
            return want

        # Cube.
        want = (error_future > threshold if grav == 1
                else error_future < -threshold)
        should_jump = want and player.on_ground
        if player.on_ground and self._hazard_cells and not should_jump:
            # A line that dips just above a spike row may not trip the
            # threshold in time — sample the interpolated path so arc
            # peaks after a pad launch still see the hazard.
            gx_now = int(pcx // CELL)
            gx_ahead = int(future_x // CELL) + 1
            if self.hazard_ahead(gx_now, gx_ahead, int(pcy // CELL),
                                  y_tol=1, follow_path=True):
                should_jump = True
        return should_jump

    def avoid_hazards(self, player, want_hold, look, vy_for, pcx, pcy, speed):
        """Flip ``want_hold`` when the alternative is strictly safer.

        "Safer" counts bodies about to hit a hazard, so in dual mode the
        controller only flips when the flip helps both — otherwise it
        would flap between two fatal choices.
        """
        main_bad = self.path_crosses_hazard(
            pcx, pcy, speed, vy_for(want_hold), look)
        mirror_bad = self.mirror_crosses_hazard(player, want_hold, False, look)
        if not (main_bad or mirror_bad):
            return want_hold
        alt = not want_hold
        alt_cost = (int(self.path_crosses_hazard(
                        pcx, pcy, speed, vy_for(alt), look))
                    + int(self.mirror_crosses_hazard(player, alt, False,
                                                      look)))
        return alt if alt_cost < int(main_bad) + int(mirror_bad) else want_hold

    # ---- recording ------------------------------------------------------

    def reset(self):
        self.inputs = []
        self.frame = 0
        self._prev_held = False
        self._dwell = DWELL_CAP
        # A stale latch would inject a phantom hold into the next run.
        self._hold_state = False
        self._hold_flip_confirm = 0

    def save_inputs(self, filepath=DEFAULT_INPUT_FILE):
        return save_bot_inputs(self.inputs, filepath)


def save_bot_inputs(inputs, filepath=DEFAULT_INPUT_FILE):
    """Write an input chain for later playback. Returns the path."""
    if not inputs:
        return filepath
    with open(filepath, "w") as f:
        f.write("# Bot inputs: frame,held,pressed\n")
        f.write("# Play back with K in editor (no path drawn)\n")
        for i, (held, pressed) in enumerate(inputs):
            f.write(f"{i},{1 if held else 0},{1 if pressed else 0}\n")
    return filepath


def load_bot_inputs(filepath=DEFAULT_INPUT_FILE):
    """Load a saved input chain for playback."""
    inputs = []
    if not os.path.exists(filepath):
        return inputs
    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(",")
            if len(parts) >= 3:
                inputs.append((bool(int(parts[1])), bool(int(parts[2]))))
    return inputs


class LoopholeBot:
    """Beats the level while hugging a drawn path — and reports shortcuts.

    ``solve`` returns the same ``(waypoints, mirror_waypoints, inputs,
    won)`` shape as :class:`~.human.HumanBot`.  Afterwards
    ``max_deviation_px`` and ``off_path_fraction`` describe how far the
    winning route strayed from what the user drew, and ``deviated``
    answers "did it find a loophole?".
    """

    def __init__(self, objects, waypoints, params=None, *,
                 frontier_cap=None, backtrack_depth=None):
        self.objects = objects
        self.params = params
        self.frontier_cap = frontier_cap
        self.backtrack_depth = backtrack_depth
        self.path = DrawnPath(waypoints)
        self.max_deviation_px = 0.0
        self.off_path_fraction = 0.0
        self.used_frame_perfect = False

    @property
    def deviated(self):
        return self.max_deviation_px > PATH_CORRIDOR_PX

    def path_bias(self, player):
        """Reward for being inside the drawn corridor, 0 outside it.

        Returned as a *progress* term, so hugging the line lowers A*'s
        f-value.  It is a bias and not a constraint: the search keeps
        every off-path option open and takes one whenever it reaches the
        end wall in fewer frames than the bonus is worth.
        """
        if not self.path:
            return 0.0
        size = getattr(player, "size", PLAYER_SIZE)
        offset = self.path.offset(player.x + size / 2, player.y + size / 2)
        if offset >= PATH_CORRIDOR_PX:
            return 0.0
        return PATH_BIAS_WEIGHT * (1.0 - offset / PATH_CORRIDOR_PX)

    def _follow_seed(self, max_frames):
        """Simulate the PD controller to get a starting input chain."""
        if not self.path:
            return [], False
        controller = PathFollowController(self.path.points,
                                          objects=self.objects)
        sim = SimPlayer([dict(o) for o in self.objects], params=self.params)
        sim.trail = []
        for _ in range(max_frames):
            if not sim.alive or sim.won:
                break
            held, pressed = controller.compute_input(sim)
            sim.update(held, pressed)
        return controller.inputs, sim.won

    def _measure_deviation(self, inputs):
        sim = SimPlayer([dict(o) for o in self.objects], params=self.params)
        sim.trail = []
        worst = 0.0
        off = 0
        total = 0
        for held, pressed in inputs:
            sim.update(held, pressed)
            if not sim.alive or sim.won:
                break
            size = sim.size
            cx = sim.x + size / 2
            if cx > self.path.end_x:
                break
            offset = self.path.offset(cx, sim.y + size / 2)
            total += 1
            worst = max(worst, offset)
            if offset > PATH_CORRIDOR_PX:
                off += 1
        self.max_deviation_px = worst
        self.off_path_fraction = (off / total) if total else 0.0

    def solve(self, screen=None, clock=None, max_frames=10000,
              seed_inputs=None, time_budget=None):
        """Follow the path, then search for a better line around it."""
        seed = list(seed_inputs) if seed_inputs else []
        if not seed:
            seed, follow_won = self._follow_seed(max_frames)
        else:
            follow_won = False

        solver = HumanBot(self.objects, params=self.params)
        solver.route_bias = self.path_bias
        solver.progress_title = "LOOPHOLE BOT SEARCH"
        if self.frontier_cap:
            solver.FRONTIER_CAP = self.frontier_cap
        if self.backtrack_depth is not None:
            solver.BACKTRACK_DEPTH = self.backtrack_depth
        wp, mwp, inputs, won = solver.solve(
            screen, clock, max_frames=max_frames,
            seed_inputs=seed or None, time_budget=time_budget)
        self.used_frame_perfect = solver.used_frame_perfect
        if not won and follow_won and seed:
            # The plain follow beat the level and the search did not
            # improve on it — keep the route the user drew.
            inputs = seed
            wp, mwp, won = solver.replay_for_waypoints(seed)
        self._measure_deviation(inputs)
        return wp, mwp, inputs, won
