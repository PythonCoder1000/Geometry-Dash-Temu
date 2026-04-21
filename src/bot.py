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
    HAZARD_TYPES, SOLID_TYPES,
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
        if objects:
            self.bind_objects(objects)

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
        size = getattr(player, "size", PLAYER_SIZE)
        pcx = player.x + size / 2
        pcy = player.y + size / 2
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
                held = blended > 0
            else:
                held = blended < 0

        elif mode == MODE_SHIP:
            # Predict where gravity drifts us without thrust.
            # Use the player's own ship_gravity so per-level physics
            # overrides still produce accurate drift predictions.
            v_drift = player.vy + player.params.ship_gravity * look * grav
            y_drift = pcy + (player.vy + v_drift) * 0.5 * look
            drift_err = y_drift - target_future
            if grav == 1:
                held = drift_err > threshold
            else:
                held = drift_err < -threshold

        elif mode == MODE_UFO:
            # UFO jumps on 'pressed'. Only press if we're below and not already
            # moving up fast.  Hold piggybacks 'pressed' so orb buffering works.
            need_up = (grav == 1 and error_future > threshold and
                       player.vy * grav > -4)
            need_down = (grav == -1 and error_future < -threshold and
                         player.vy * grav > -4)
            if need_up or need_down:
                pressed = True
                held = True

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
