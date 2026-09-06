"""Bot controller — follows a drawn path by computing frame-by-frame inputs.

The controller is a closed-loop PD-style regulator with a short lookahead:
each frame it predicts where the player will be a few ticks from now,
compares that to the drawn target-y, and chooses the input most likely to
close the gap. It also peeks at the level geometry (if provided) to jump
preemptively over spikes and saws that sit on the planned path.
"""

import os

from .constants import (
    CELL, PLAYER_SIZE,
    MODE_CUBE, MODE_SHIP, MODE_BALL, MODE_WAVE, MODE_UFO, MODE_SPIDER,
    MODE_SWING,
    HAZARD_TYPES, SOLID_TYPES,
    T_DASH_ORB,
)


# Frames of lookahead per mode. Picked to roughly match the duration of one
# input-to-effect cycle (e.g. one cube jump peak, one ship thrust arc).
_LOOKAHEAD_BY_MODE = {
    MODE_CUBE:   6,
    MODE_SHIP:   8,
    MODE_UFO:    5,
    MODE_BALL:   5,
    MODE_WAVE:   3,
    MODE_SPIDER: 4,
    MODE_SWING:  4,
}

# Dead-zone thresholds (pixels) per mode — how far off the path we tolerate
# before acting. Scaled by speed in compute_input.
_THRESHOLD_BY_MODE = {
    MODE_CUBE:   10,
    MODE_SHIP:   4,
    MODE_UFO:    8,
    MODE_BALL:   10,
    MODE_WAVE:   0,
    MODE_SPIDER: 14,
    MODE_SWING:  4,
}


class BotController:
    """Follows a drawn path using real physics by deciding hold/press each frame.

    Parameters
    ----------
    waypoints : list of (world_x, world_y) tuples
        The drawn path in play-mode pixel coordinates.
    objects : optional, the level's object list. If passed, the bot builds
        a hazard grid and will jump early over spikes/saws on the path.
    """

    # Number of consecutive frames a flipped hold-decision must persist
    # before the BotController actually toggles the held output. Tuned by
    # eye: 1 = no hysteresis (per-frame flap), 3+ = visibly laggy. 2 is the
    # sweet spot — kills PD-style jitter on near-zero error while still
    # reacting in under ~33ms.
    _HOLD_CONFIRM_FRAMES = 2

    def __init__(self, waypoints, objects=None):
        # Sort and de-duplicate consecutive points so get_target_y is O(log n)-ish.
        pts = sorted(waypoints, key=lambda p: p[0])
        clean = []
        for p in pts:
            if not clean or p[0] != clean[-1][0]:
                clean.append(p)
            else:
                # Keep the most recent y for duplicate x.
                clean[-1] = p
        self.waypoints = clean
        self.inputs = []  # recorded (held, pressed) per physics frame
        self.frame = 0

        # Hazard/solid awareness built from the level geometry.
        self._hazard_cells = set()   # {(gx, gy)}
        self._solid_cells = set()
        self._dash_orb_cells = set()
        if objects:
            self.bind_objects(objects)

        # Hysteresis state for hold-dominant modes (wave / ship). Wave's
        # PD controller flips held as soon as the blended error crosses
        # zero, which in practice happens every 1-2 frames and causes
        # the sprite to flap and stalls forward progress. Gate the flip
        # behind `_HOLD_CONFIRM_FRAMES` identical requests.
        self._hold_state = False
        self._hold_flip_confirm = 0

    # ------------------------------------------------------------------
    # Level geometry
    # ------------------------------------------------------------------

    def bind_objects(self, objects):
        """(Re)build hazard + solid indices from the level's object list."""
        self._hazard_cells = {
            (o["x"], o["y"]) for o in objects if o["t"] in HAZARD_TYPES
        }
        self._solid_cells = {
            (o["x"], o["y"]) for o in objects if o["t"] in SOLID_TYPES
        }
        # Dash-orb index: the path-following bot doesn't know to press
        # for orbs (its press logic is mode/error driven), so it would
        # otherwise sail straight through a dash orb without firing it.
        # When the player straddles or is about to enter a dash-orb
        # cell, the bot stamps a press so the orb activates and the
        # subsequent dash_timer>0 branch holds for the full dash window.
        self._dash_orb_cells = {
            (o["x"], o["y"]) for o in objects if o["t"] == T_DASH_ORB
        }

    def _hazard_ahead(self, gx_from, gx_to, gy_center, y_tol=1,
                       follow_path=False):
        """True if any hazard cell sits on the planned path within x-range.

        ``follow_path``: when True, the y center for each column is sampled
        from the interpolated target path instead of fixed ``gy_center``.
        This catches hazards on arc peaks after a pad/orb launch that would
        otherwise sit above a flat ``gy_center ± y_tol`` window.
        """
        if not self._hazard_cells or gx_to < gx_from:
            return False
        for gx in range(gx_from, gx_to + 1):
            center = gy_center
            if follow_path:
                ty = self.get_target_y(gx * CELL + CELL // 2)
                if ty is not None:
                    center = int(ty // CELL)
            for dy in range(-y_tol, y_tol + 1):
                if (gx, center + dy) in self._hazard_cells:
                    return True
        return False

    def _solid_at(self, gx, gy):
        return (gx, gy) in self._solid_cells

    # ------------------------------------------------------------------
    # Short-horizon safety lookahead
    # ------------------------------------------------------------------

    def _path_crosses_hazard(self, pcx, pcy, vx, vy, frames, y_tol=1):
        """True if straight-line motion (``vx``, ``vy``) from ``(pcx, pcy)``
        crosses a hazard cell within the next ``frames`` physics ticks.

        Used by wave/ship decisions to verify that the PD controller's
        chosen hold direction won't sail the player into a spike or saw
        inside the control horizon. ``y_tol`` expands the column sample
        by ±1 cell so a hazard that sits just off the exact pixel line
        still trips the check — matches how hazards are read in
        ``_hazard_ahead``.
        """
        if not self._hazard_cells or frames <= 0:
            return False
        for k in range(1, frames + 1):
            fx = pcx + vx * k
            fy = pcy + vy * k
            gx = int(fx // CELL)
            gy = int(fy // CELL)
            for dy in range(-y_tol, y_tol + 1):
                if (gx, gy + dy) in self._hazard_cells:
                    return True
        return False

    def _mirror_path_crosses_hazard(self, player, held, pressed, frames):
        """True if a live dual-mode mirror would fly through a hazard
        under the chosen input over ``frames`` physics ticks.

        Intentionally a first-order approximation: we compute a single
        vy the mirror would take on THIS frame under the chosen input
        (per its own mode) and extrapolate linearly. That's enough to
        catch the common "ship thrusts up, mirror wave ploughs down
        into a spike" class of cases without duplicating the full
        physics loop. Uses move_speed and the player's own
        PhysicsParams so per-level overrides stay honoured.
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
        # Per-mode vy after one frame of physics under the chosen input.
        # Matches _step_mirror's dispatch so lookahead drift stays small.
        mvy = m["vy"]
        if mmode == MODE_SHIP:
            mvy = mvy + params.ship_gravity * mgrav
            if held:
                mvy -= params.ship_thrust * mgrav
        elif mmode == MODE_WAVE:
            direction = -1 if held else 1
            mvy = speed * direction * mgrav
        elif mmode == MODE_UFO:
            mvy = mvy + params.gravity * mgrav
            # UFO now uses cube physics on the ground (hold-to-jump)
            # plus a mid-air flap on press. Mirror the same dispatch
            # so lookahead trajectories stay accurate.
            if held and m.get("on_ground", False):
                mvy = params.jump_force * mgrav
            elif pressed and not m.get("on_ground", False):
                mvy = params.ufo_jump_force * mgrav
        elif mmode == MODE_SWING:
            # Press flips grav but preserves vy (the swing keeps its
            # momentum across the flip — gravity then decelerates and
            # reverses the existing velocity).
            mvy = mvy + params.gravity * mgrav
            if pressed:
                mgrav = -mgrav
        elif mmode == MODE_BALL:
            mvy = mvy + params.gravity * mgrav
            # A flip fires on pressed + on_ground; treat it as an
            # instant vy = flip_force * (-grav) for the lookahead.
            if pressed and m.get("on_ground", False):
                mvy = params.ball_flip_force * (-mgrav)
        elif mmode == MODE_SPIDER:
            # Spider-teleport resolves instantly; a press cancels the
            # fall so lookahead under "pressed" is meaningless. Skip
            # the check rather than returning a false positive.
            if pressed and m.get("on_ground", False):
                return False
            mvy = mvy + params.gravity * mgrav
        else:  # cube
            mvy = mvy + params.gravity * mgrav
            if held and m.get("on_ground", False):
                mvy = params.jump_force * mgrav
        mcx = player.x + msize / 2
        mcy = m["y"] + msize / 2
        return self._path_crosses_hazard(mcx, mcy, speed, mvy, frames)

    # ------------------------------------------------------------------
    # Hold-state hysteresis
    # ------------------------------------------------------------------

    def _hysteretic_hold(self, want_hold):
        """Return the current held state, advancing the confirm counter.

        Calling this with a different ``want_hold`` than the latched
        state increments the confirm counter. Only after
        ``_HOLD_CONFIRM_FRAMES`` consecutive opposing requests does the
        latched state flip. Calling with the same state resets the
        counter to 0 (single-frame dissent is ignored). This mirrors
        PDF 3.2 — the two-frame confirm is the cheapest way to kill PD
        flap on error-crossings and matches how the physics loop reads
        hold state (once per tick).
        """
        if want_hold == self._hold_state:
            self._hold_flip_confirm = 0
        else:
            self._hold_flip_confirm += 1
            if self._hold_flip_confirm >= self._HOLD_CONFIRM_FRAMES:
                self._hold_state = want_hold
                self._hold_flip_confirm = 0
        return self._hold_state

    # ------------------------------------------------------------------
    # Path interpolation
    # ------------------------------------------------------------------

    def get_target_y(self, x):
        """Interpolate the path to find target y at a given world x."""
        wps = self.waypoints
        if not wps:
            return None
        if len(wps) == 1:
            return wps[0][1]
        if x <= wps[0][0]:
            return wps[0][1]
        if x >= wps[-1][0]:
            return wps[-1][1]
        # Binary search the bracketing pair.
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
        t = (x - x0) / span
        return y0 + (y1 - y0) * t

    # ------------------------------------------------------------------
    # Control logic
    # ------------------------------------------------------------------

    def compute_input(self, player):
        """Decide (held, pressed) for the current physics frame."""
        # Dash orb in-flight: the directional dash ends immediately if
        # the button is released (see Player.update's dash branch), so
        # keep the input held for the full duration. No press edge —
        # orbs only activate on the press that starts the dash, and a
        # re-press mid-dash would just waste the input buffer.
        if getattr(player, "dash_timer", 0) > 0:
            self._record(True, False)
            return True, False
        size = getattr(player, "size", PLAYER_SIZE)
        pcx = player.x + size / 2
        pcy = player.y + size / 2
        # Dash-orb activation. Mode-specific PD never has a reason to
        # press for a dash orb — it presses to clear hazards or to flip
        # gravity, not to consume an orb on the ground line. Detect a
        # dash orb the player overlaps right now (or in the next ~2
        # cells of forward travel, which fits the input_buffer window)
        # and stamp a press. Direction-agnostic: works for dash orbs
        # facing any rotation since the orb's own ``r`` field drives
        # the dash vector inside player.activate_dash_orb.
        if self._dash_orb_cells:
            gx_now = int(pcx // CELL)
            gy_now = int(pcy // CELL)
            for dgx in range(0, 3):
                for dgy in (-1, 0, 1):
                    if (gx_now + dgx, gy_now + dgy) in self._dash_orb_cells:
                        self._record(True, True)
                        return True, True
        mode = player.mode
        grav = player.grav
        speed = max(1.0, player.move_speed)

        look = _LOOKAHEAD_BY_MODE.get(mode, 5)
        future_x = pcx + look * speed

        target_now = self.get_target_y(pcx)
        target_future = self.get_target_y(future_x)
        if target_now is None and target_future is None:
            # No path → idle (but keep moving forward, which happens anyway).
            self._record(False, False)
            return False, False
        if target_now is None:
            target_now = target_future
        if target_future is None:
            target_future = target_now

        # Scale threshold with speed: faster player needs to react earlier.
        threshold = _THRESHOLD_BY_MODE.get(mode, 10) * (speed / 5.0)
        error_now = pcy - target_now           # +ve → below target (screen y grows down)
        error_future = pcy - target_future

        held = False
        pressed = False

        if mode == MODE_WAVE:
            # Wave: fly angle matters more than position. Blend errors and act
            # based on average displacement above/below the line.
            blended = 0.35 * error_now + 0.65 * error_future
            if grav == 1:
                want_hold = blended > 0
            else:
                want_hold = blended < 0

            # Hazard lookahead (PDF 4.2). Wave's vy is locked to
            # ±move_speed, so the PD decision — if followed blindly —
            # can drive the dart straight into a spike when the drawn
            # path skims a hazard column. Simulate the chosen direction
            # forward `look` frames and flip it if the trajectory walks
            # through a hazard cell. In dual, ALSO validate the mirror
            # — the two bodies share one input, so the bot has to pick
            # a direction that keeps both alive or the mirror dies
            # "under independent control" (user-visible dual bug).
            direction = -1 if want_hold else 1
            future_vy = speed * direction * grav
            main_bad = self._path_crosses_hazard(
                pcx, pcy, speed, future_vy, look)
            mirror_bad = self._mirror_path_crosses_hazard(
                player, want_hold, False, look)
            if main_bad or mirror_bad:
                alt_hold = not want_hold
                alt_vy = -future_vy
                alt_main_bad = self._path_crosses_hazard(
                    pcx, pcy, speed, alt_vy, look)
                alt_mirror_bad = self._mirror_path_crosses_hazard(
                    player, alt_hold, False, look)
                # Only flip when the alternative is strictly safer —
                # otherwise we'd flap back and forth between two dying
                # choices. "Safer" = fewer bodies about to hit a hazard.
                cost_now = int(main_bad) + int(mirror_bad)
                cost_alt = int(alt_main_bad) + int(alt_mirror_bad)
                if cost_alt < cost_now:
                    want_hold = alt_hold

            # Hysteresis (PDF 3.2): wave's error-cross flipping is the
            # single biggest cause of input flap. Two-frame confirm
            # damps it without adding perceptible lag.
            held = self._hysteretic_hold(want_hold)

        elif mode == MODE_SHIP:
            # Predict where gravity drifts us without thrust.
            # Use the player's own ship_gravity so per-level physics
            # overrides still produce accurate drift predictions.
            v_drift = player.vy + player.params.ship_gravity * look * grav
            y_drift = pcy + (player.vy + v_drift) * 0.5 * look
            drift_err = y_drift - target_future
            if grav == 1:
                want_hold = drift_err > threshold
            else:
                want_hold = drift_err < -threshold

            # Hazard lookahead: approximate ship trajectory under the
            # chosen thrust. If held, we add thrust (accelerate against
            # gravity); otherwise we just drift. Verify neither hits a
            # hazard in the short horizon. Trajectory approximated as a
            # parabola sampled at `look` frames — precise enough for
            # cell-granularity hazard checks. Dual validation mirrors
            # the wave case — same tie-break rule keeps flap in check.
            accel = player.params.ship_gravity * grav
            if want_hold:
                accel -= player.params.ship_thrust * grav
            mean_vy = player.vy + accel * look * 0.5
            main_bad = self._path_crosses_hazard(
                pcx, pcy, speed, mean_vy, look)
            mirror_bad = self._mirror_path_crosses_hazard(
                player, want_hold, False, look)
            if main_bad or mirror_bad:
                alt_hold = not want_hold
                alt_accel = player.params.ship_gravity * grav
                if alt_hold:
                    alt_accel -= player.params.ship_thrust * grav
                alt_mean_vy = player.vy + alt_accel * look * 0.5
                alt_main_bad = self._path_crosses_hazard(
                    pcx, pcy, speed, alt_mean_vy, look)
                alt_mirror_bad = self._mirror_path_crosses_hazard(
                    player, alt_hold, False, look)
                cost_now = int(main_bad) + int(mirror_bad)
                cost_alt = int(alt_main_bad) + int(alt_mirror_bad)
                if cost_alt < cost_now:
                    want_hold = alt_hold

            held = self._hysteretic_hold(want_hold)

        elif mode == MODE_UFO:
            # UFO now jumps cube-style on 'held + on_ground' and flaps
            # on 'pressed' mid-air. Pick the right control depending
            # on whether the player is currently grounded.
            need_up = (grav == 1 and error_future > threshold and
                       player.vy * grav > -4)
            need_down = (grav == -1 and error_future < -threshold and
                         player.vy * grav > -4)
            if need_up or need_down:
                if player.on_ground:
                    held = True
                    pressed = True
                else:
                    pressed = True
                    held = True

        elif mode == MODE_SWING:
            # Press flips gravity. Treat the path the same way as ball:
            # if the path is far above (grav=1) or below (grav=-1) we
            # need to flip. Press+hold so the buffer carries through to
            # any orb on the same frame.
            want_flip = False
            if grav == 1 and error_future > threshold:
                want_flip = True
            elif grav == -1 and error_future < -threshold:
                want_flip = True
            if want_flip:
                held = True
                pressed = True

        elif mode == MODE_CUBE:
            # Gap jump: use future error. Reinforce with hazard-scan ahead.
            want_up = (grav == 1 and error_future > threshold)
            want_down = (grav == -1 and error_future < -threshold)
            should_jump = (want_up or want_down) and player.on_ground

            # If the target dips just above a spike row, the raw threshold
            # may not fire in time — force a jump when a hazard sits directly
            # on our planned corridor within the lookahead window. Sample
            # the interpolated path (instead of the player's current row)
            # so arc peaks after a pad / orb launch see hazards above the
            # current gy_center.
            if player.on_ground and self._hazard_cells:
                gy_now = int(pcy // CELL)
                gx_now = int(pcx // CELL)
                gx_ahead = int(future_x // CELL) + 1
                if self._hazard_ahead(gx_now, gx_ahead, gy_now,
                                      y_tol=1, follow_path=True):
                    should_jump = True

            if should_jump:
                held = True
                pressed = True

        elif mode == MODE_BALL:
            # Flip gravity when a clear side-switch is needed. Press+hold so
            # orb/pad buffers fire too.
            want_flip = False
            if grav == 1 and error_future > threshold and player.on_ground:
                want_flip = True
            elif grav == -1 and error_future < -threshold and player.on_ground:
                want_flip = True
            if want_flip:
                held = True
                pressed = True

        elif mode == MODE_SPIDER:
            # Spider teleports AGAINST gravity to the opposite surface and
            # flips. From the floor (grav=1), a press shoots the player up
            # to the ceiling — so we want to fire when the drawn path goes
            # well ABOVE the player (target_future < pcy → error_future > 0).
            # From the ceiling (grav=-1), the press takes us back down, so
            # fire when the path goes well BELOW (error_future < 0).
            teleport_up = (grav == 1 and error_future > threshold and
                           player.on_ground)
            teleport_down = (grav == -1 and error_future < -threshold and
                             player.on_ground)
            if teleport_up or teleport_down:
                pressed = True
                held = True

        self._record(held, pressed)
        return held, pressed

    # ------------------------------------------------------------------
    # Recording / persistence
    # ------------------------------------------------------------------

    def _record(self, held, pressed):
        self.inputs.append((held, pressed))
        self.frame += 1

    def reset(self):
        """Reset recording for a new attempt."""
        self.inputs = []
        self.frame = 0
        # Clear hysteresis latch — a stale held state from the prior
        # attempt would otherwise bleed into the first few frames of
        # the next run and inject a phantom hold.
        self._hold_state = False
        self._hold_flip_confirm = 0

    def save_inputs(self, filepath="level_bot_inputs.txt"):
        """Save recorded inputs to a file for later playback."""
        if not self.inputs:
            return filepath
        with open(filepath, "w") as f:
            f.write("# Bot inputs: frame,held,pressed\n")
            f.write("# Play back with K in editor (no path drawn)\n")
            for i, (held, pressed) in enumerate(self.inputs):
                f.write(f"{i},{1 if held else 0},{1 if pressed else 0}\n")
        return filepath


def load_bot_inputs(filepath="level_bot_inputs.txt"):
    """Load bot inputs from file for playback."""
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
                held = bool(int(parts[1]))
                pressed = bool(int(parts[2]))
                inputs.append((held, pressed))
    return inputs
