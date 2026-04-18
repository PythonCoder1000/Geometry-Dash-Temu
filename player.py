"""Physics / state for the player.

The player owns the object list for the current play session (it mutates
positions for move triggers and tracks which orbs/portals have been
consumed). One instance per attempt — call ``reset()`` between tries.
"""

import math

import pygame

from constants import (
    CELL, WIDTH, HEIGHT, PLAYER_SIZE, MINI_PLAYER_SIZE, PLAYER_START_GX,
    BASE_MOVE_SPEED, GRAVITY, SHIP_GRAVITY, SHIP_THRUST,
    JUMP_FORCE, PAD_FORCE, BALL_FLIP_FORCE, DASH_SPEED, DASH_TIME, WAVE_ANGLE,
    UFO_JUMP_FORCE, SPIDER_TELEPORT_RANGE,
    MODE_CUBE, MODE_SHIP, MODE_BALL, MODE_WAVE, MODE_UFO, MODE_SPIDER,
    MODE_FROM_TYPE, SPEED_VALUES, PLAYER_COLORS, PLAYER_ICONS,
    T_BLOCK, T_SLAB, T_SPIKE, T_HALF_SPIKE, T_SAW,
    T_ORB, T_DASH_ORB, T_TELEPORT_ORB, T_BLACK_ORB, T_BLUE_ORB, T_GREEN_ORB,
    T_PAD, T_BLUE_PAD, T_GRAV, T_END, T_START, T_COIN, T_CHECKPOINT,
    T_MODE_MINI, T_MODE_BIG, T_MODE_DUAL, T_MODE_SOLO,
    T_CAMERA_TRIGGER, T_BG_TRIGGER, T_MOVE_TRIGGER, T_COLOR_TRIGGER,
    T_PULSE_TRIGGER, T_ROTATE_TRIGGER,
    C_PLAYER, C_DASH_ORB, C_PAD, C_MODE_WAVE, C_MODE_UFO, C_MODE_SPIDER,
    DEFAULT_MOVE_CURVE, PAD_TYPES,
)
from graphics import (
    cell_rect, slab_rect, spike_hitboxes, pad_trigger_rect, saw_hitbox,
    lighter, darker, clamp, draw_cube_icon_glyph,
)
from levels import get_group_id
import settings


# ---------------------------------------------------------------------------
# Move-trigger timing curve integration
# ---------------------------------------------------------------------------

def _curve_progress(curve, total_area, t):
    """Integrate the speed curve up to time t, normalised to [0,1]."""
    if not curve or len(curve) < 2 or total_area <= 1e-9:
        return t
    if t <= 0.0:
        return 0.0
    if t >= 1.0:
        return 1.0
    area = 0.0
    for i in range(len(curve) - 1):
        t0, s0 = curve[i]
        t1, s1 = curve[i + 1]
        if t >= t1:
            area += (t1 - t0) * (s0 + s1) * 0.5
            continue
        if t <= t0:
            break
        span = t1 - t0
        if span <= 1e-9:
            continue
        frac = (t - t0) / span
        s_at = s0 + (s1 - s0) * frac
        area += (t - t0) * (s0 + s_at) * 0.5
        break
    return max(0.0, min(1.0, area / total_area))


# ---------------------------------------------------------------------------
# Player
# ---------------------------------------------------------------------------

class Player:
    def __init__(self, objects):
        self.objects = objects
        for o in self.objects:
            o.setdefault("_orig_x", o["x"])
            o.setdefault("_orig_y", o["y"])
        self._teleport_index = {}
        self._rebuild_teleport_index()
        # End walls span the full screen height: collision is x-only.
        # Sorted so we can stop scanning once player.x is past all of them.
        self._end_walls_x = sorted({
            o["x"] * CELL for o in self.objects if o["t"] == T_END
        })
        self.practice_mode = False
        self.checkpoints = []
        self.attempt_count = 0
        self.reset()

    def _rebuild_teleport_index(self):
        groups = {}
        for o in self.objects:
            if o["t"] == T_TELEPORT_ORB:
                gid = get_group_id(o)
                if gid:
                    groups.setdefault(gid, []).append(o)
        self._teleport_index = groups

    def reset(self):
        for o in self.objects:
            if "_orig_x" in o:
                o["x"] = o["_orig_x"]
                o["y"] = o["_orig_y"]
            o.pop("_fx", None)
            o.pop("_fy", None)
        self.move_animations = []
        self.x, self.y = self._spawn_point()
        self.vy = 0.0
        self.on_ground = False
        self.alive = True
        self.won = False
        self.angle = 0.0
        self.grav = 1
        self.trail = []
        self.passed = set()
        self.frame = 0
        self.mode = MODE_CUBE
        self.move_speed = BASE_MOVE_SPEED
        self.dash_timer = 0
        self.input_buffer = 0
        self.teleport_cooldown = 0
        self.target_cam_y = 0.0
        self.bg_preset = 0
        # Player cosmetics persisted across runs via the Settings module.
        # Modulo on every read keeps things sane even if PLAYER_COLORS
        # shrinks or the prefs file held a stale, larger index.
        self.color_index = settings.get_player_color_index() % len(PLAYER_COLORS)
        self.player_color = PLAYER_COLORS[self.color_index]
        self.icon_index = settings.get_player_icon_index() % len(PLAYER_ICONS)
        self._grav_flip_grace = 0
        self._wall_frames = 0
        self._checkpoint_request = False
        self._x_at_frame_start = self.x
        # Player scale: PLAYER_SIZE normally, MINI_PLAYER_SIZE after a mini
        # portal. Reset to full on every new attempt.
        self.size = PLAYER_SIZE
        self.coins_collected = set()  # coin_ids picked up this attempt
        # Dual-mode mirror body. None when single-player. A dict with y/vy/
        # grav/on_ground/angle/alive when a dual portal is active.
        self.mirror = None
        # Active pulse triggers — list of dicts {start_frame, bpm, end_frame}.
        # play.py reads this to compute a pulse intensity for visual flash.
        self.active_pulses = []
        # Active rotation triggers — list of dicts {target_oids, spin,
        # end_frame}. _step_rotate_triggers ticks rotation each frame.
        self.active_rotations = []
        self.attempt_count += 1

    def _start_object(self):
        starts = [o for o in self.objects if o["t"] == T_START]
        if starts:
            return min(starts, key=lambda o: (o["x"], o["y"]))
        return None

    def _spawn_point(self):
        start = self._start_object()
        if start:
            return (
                float(start["x"] * CELL + (CELL - PLAYER_SIZE) / 2),
                float(start["y"] * CELL + (CELL - PLAYER_SIZE) / 2),
            )
        return float(PLAYER_START_GX * CELL), float(self._default_ground_y())

    def _default_ground_y(self):
        col_blocks = [o for o in self.objects
                      if o["t"] == T_BLOCK and o["x"] == PLAYER_START_GX]
        if col_blocks:
            top = min(o["y"] for o in col_blocks)
            return top * CELL - PLAYER_SIZE
        return 10 * CELL - PLAYER_SIZE

    def rect(self):
        return pygame.Rect(round(self.x), round(self.y), self.size, self.size)

    def hitbox(self):
        """Smaller inner hitbox used for hazard collision — gives forgiveness."""
        # Scale shrink with size so mini players still get some forgiveness.
        shrink = max(2, int(6 * self.size / PLAYER_SIZE))
        return pygame.Rect(round(self.x) + shrink, round(self.y) + shrink,
                           self.size - shrink * 2, self.size - shrink * 2)

    def save_checkpoint(self):
        """Save current player state as a checkpoint for practice mode."""
        checkpoint = {
            "x": self.x,
            "y": self.y,
            "vy": self.vy,
            "grav": self.grav,
            "mode": self.mode,
            "move_speed": self.move_speed,
            "angle": self.angle,
            "bg_preset": self.bg_preset,
            "target_cam_y": self.target_cam_y,
            "color_index": self.color_index,
            "coins": set(self.coins_collected),
            "passed": set(self.passed),
        }
        self.checkpoints.append(checkpoint)

    def load_checkpoint(self):
        """Restore player state from last checkpoint."""
        if not self.checkpoints:
            return False
        cp = self.checkpoints[-1]
        self.x = cp["x"]
        self.y = cp["y"]
        self.vy = cp["vy"]
        self.grav = cp["grav"]
        self.mode = cp["mode"]
        self.move_speed = cp["move_speed"]
        self.angle = cp["angle"]
        self.bg_preset = cp["bg_preset"]
        self.target_cam_y = cp["target_cam_y"]
        self.color_index = cp.get("color_index", 0)
        self.player_color = PLAYER_COLORS[self.color_index % len(PLAYER_COLORS)]
        self.coins_collected = set(cp.get("coins", set()))
        self.passed = set(cp.get("passed", set()))
        self.on_ground = False
        self.alive = True
        self.won = False
        self.trail = []
        return True

    def nearby_for_rect(self, rect, extra=2):
        left = rect.left // CELL - extra
        right = rect.right // CELL + extra
        top = rect.top // CELL - extra
        bottom = rect.bottom // CELL + extra
        return [o for o in self.objects
                if left <= o["x"] <= right and top <= o["y"] <= bottom]

    # ---- actions ----------------------------------------------------------
    def jump(self, force=None):
        if force is None:
            force = JUMP_FORCE
        self.vy = force * self.grav
        self.on_ground = False

    def activate_orb(self):
        if self.mode == MODE_BALL:
            self.grav *= -1
            self.vy = BALL_FLIP_FORCE * self.grav
        elif self.mode == MODE_SHIP:
            self.vy = JUMP_FORCE * 0.85 * self.grav
        elif self.mode == MODE_WAVE:
            pass
        elif self.mode == MODE_UFO:
            self.vy = JUMP_FORCE * 0.9 * self.grav
        elif self.mode == MODE_SPIDER:
            self._spider_teleport()
        else:
            self.vy = JUMP_FORCE * self.grav
        self.on_ground = False

    def activate_dash_orb(self):
        self.activate_orb()
        self.dash_timer = DASH_TIME
        self.input_buffer = 0

    def activate_black_orb(self):
        self.vy = -JUMP_FORCE * self.grav
        self.on_ground = False
        self.input_buffer = 0

    def activate_blue_orb(self):
        self.grav *= -1
        self.on_ground = False
        self.input_buffer = 0

    def activate_green_orb(self):
        """Green orb: jump in the current gravity direction (opposite of blue)."""
        self.vy = JUMP_FORCE * self.grav
        self.on_ground = False
        self.input_buffer = 0

    def activate_teleport(self, orb):
        gid = get_group_id(orb)
        if not gid:
            return
        group = [o for o in self._teleport_index.get(gid, []) if o is not orb]
        if not group:
            return
        dests = [o for o in group if o.get("dest")]
        dest = dests[0] if dests else group[0]
        self.x = dest["x"] * CELL + (CELL - PLAYER_SIZE) / 2
        self.y = dest["y"] * CELL + (CELL - PLAYER_SIZE) / 2
        self.vy *= 0.25
        self.teleport_cooldown = 10
        self.trail = []

    def flip_gravity(self):
        self.grav *= -1
        self.on_ground = False

    def _spider_teleport(self):
        """Spider: teleport AGAINST gravity to the nearest block surface, then
        flip gravity so the player clings to that new surface.

        Standing on the floor (grav=1) and pressing → teleport upward to the
        ceiling, land just below it, flip to grav=-1 (clung to ceiling).
        Hanging from the ceiling (grav=-1) and pressing → teleport downward to
        the floor, land just above it, flip to grav=1.
        """
        probe = self.rect()
        best = None
        max_dist = SPIDER_TELEPORT_RANGE * CELL
        for o in self.nearby_for_rect(probe, extra=SPIDER_TELEPORT_RANGE + 1):
            if o["t"] != T_BLOCK:
                continue
            br = cell_rect(o["x"], o["y"])
            if not (br.left < probe.right and br.right > probe.left):
                continue
            if self.grav == 1:
                # Look UP for a ceiling block (br.bottom is above probe.top).
                if br.bottom <= probe.top:
                    dist = probe.top - br.bottom
                    if dist <= max_dist and (best is None or dist < best[0]):
                        best = (dist, br.bottom)
            else:
                # Look DOWN for a floor block (br.top is below probe.bottom).
                if br.top >= probe.bottom:
                    dist = br.top - probe.bottom
                    if dist <= max_dist and (best is None or dist < best[0]):
                        best = (dist, br.top - self.size)
        if best is not None:
            self.y = float(best[1])
            self.grav *= -1
            self.vy = 0.0
            self.on_ground = False
            self._grav_flip_grace = 4

    def _start_move_trigger(self, trig):
        """Kick off the move animation for one or more target oids."""
        oids = list(trig.get("target_oids") or
                    ([trig.get("target_oid", 0)] if trig.get("target_oid", 0) else []))
        # Group resolution: any object with matching `group` is also a target.
        group = trig.get("group")
        if group:
            for o in self.objects:
                if o.get("group") == group and o.get("oid"):
                    oids.append(o["oid"])
        oids = list(dict.fromkeys(oids))  # de-dupe
        if not oids:
            return
        targets = [o for o in self.objects if o.get("oid") in oids]
        if not targets:
            return
        duration = max(1, int(trig.get("duration", 30)))
        curve = trig.get("curve", DEFAULT_MOVE_CURVE)
        curve_area = sum(
            (curve[i + 1][0] - curve[i][0]) * (curve[i][1] + curve[i + 1][1]) * 0.5
            for i in range(len(curve) - 1)
        ) if curve and len(curve) >= 2 else 1.0
        first = targets[0]
        end_x = float(trig.get("tx", first["x"]))
        end_y = float(trig.get("ty", first["y"]))
        dx = end_x - float(first.get("_fx", first["x"]))
        dy = end_y - float(first.get("_fy", first["y"]))
        for target in targets:
            start_x = float(target.get("_fx", target["x"]))
            start_y = float(target.get("_fy", target["y"]))
            self.move_animations.append({
                "obj": target,
                "sx": start_x, "sy": start_y,
                "ex": start_x + dx, "ey": start_y + dy,
                "frame": 0, "duration": duration,
                "curve": curve, "curve_area": curve_area,
            })

    def pulse_intensity(self):
        """Return a [0,1] intensity from active pulse triggers, where 1 is
        a peak flash. Sums sin^2 contributions of every active pulse and
        clips. Called by play.py during rendering — purely presentational."""
        if not self.active_pulses:
            return 0.0
        total = 0.0
        for p in self.active_pulses:
            bpm = max(1, p["bpm"])
            elapsed_frames = self.frame - p["start_frame"]
            # 60 fps; one beat = 60/bpm seconds = 60*60/bpm frames.
            frames_per_beat = 3600.0 / bpm
            phase = (elapsed_frames / frames_per_beat) * math.tau
            total += math.sin(phase) ** 2
        return min(1.0, total)

    def _start_rotate_trigger(self, trig):
        """Begin a rotation animation on one or more target oids. Targets
        keep their visual rotation in their `r` field. Resolves group ids
        too — if `group` is set on the trigger, all objects with the
        matching group field are added as targets."""
        oids = list(trig.get("target_oids") or
                    ([trig.get("target_oid", 0)] if trig.get("target_oid", 0) else []))
        # Group resolution: collect oids of any object with matching group.
        group = trig.get("group")
        if group:
            for o in self.objects:
                if o.get("group") == group and o.get("oid"):
                    oids.append(o["oid"])
        oids = list(dict.fromkeys(oids))  # de-dupe, preserve order
        if not oids:
            return
        targets = [o for o in self.objects if o.get("oid") in oids]
        if not targets:
            return
        spin_dps = float(trig.get("spin", 90.0))  # degrees per second
        duration_s = float(trig.get("duration", 4.0))
        frames = max(1, int(duration_s * 60))
        self.active_rotations.append({
            "targets": targets,
            "spin_per_frame": spin_dps / 60.0,
            "end_frame": self.frame + frames,
        })

    def _step_rotate_triggers(self):
        if not self.active_rotations:
            return
        remaining = []
        for rot in self.active_rotations:
            if self.frame >= rot["end_frame"]:
                continue
            for o in rot["targets"]:
                # Visual `r` is in degrees; we keep it modulo 360 for sanity.
                o["r"] = (float(o.get("r", 0)) + rot["spin_per_frame"]) % 360.0
            remaining.append(rot)
        self.active_rotations = remaining

    def _step_move_animations(self):
        if not self.move_animations:
            return
        remaining = []
        for anim in self.move_animations:
            anim["frame"] += 1
            t = min(1.0, anim["frame"] / anim["duration"])
            te = _curve_progress(anim["curve"], anim["curve_area"], t)
            fx = anim["sx"] + (anim["ex"] - anim["sx"]) * te
            fy = anim["sy"] + (anim["ey"] - anim["sy"]) * te
            obj = anim["obj"]
            obj["_fx"] = fx
            obj["_fy"] = fy
            obj["x"] = int(round(fx))
            obj["y"] = int(round(fy))
            if anim["frame"] < anim["duration"]:
                remaining.append(anim)
            else:
                obj["x"] = int(round(anim["ex"]))
                obj["y"] = int(round(anim["ey"]))
                obj.pop("_fx", None)
                obj.pop("_fy", None)
        self.move_animations = remaining

    def set_mode(self, mode):
        self.mode = mode
        if mode in (MODE_CUBE, MODE_BALL):
            self.angle = round(self.angle / 90) * 90
        elif mode == MODE_WAVE:
            self.vy = 0.0

    def set_speed(self, speed_type):
        self.move_speed = SPEED_VALUES.get(speed_type, BASE_MOVE_SPEED)

    def _set_size(self, new_size):
        """Change the player's bounding size while preserving the
        gravity-facing edge (feet for grav=1, head for grav=-1). This keeps
        the player visually planted on the current surface when a mini or
        big portal changes the size mid-level."""
        if new_size == self.size:
            return
        delta = self.size - new_size
        # Keep the gravity-facing edge anchored. For grav=1 (normal), the
        # feet are at y + size, so y must shift by +delta to keep feet put.
        # For grav=-1 (inverted), the head is at y, which is already anchored.
        if self.grav == 1:
            self.y += delta
        # Also re-center horizontally on the player's current centre so the
        # shrink doesn't pop sideways into a wall.
        self.x += delta / 2.0
        self.size = new_size
        if self.mirror:
            if -self.grav == 1:
                self.mirror["y"] += delta
            # Mirror x always follows main, so no x shift needed.

    def _enter_dual(self):
        """Initialize a mirror body with opposite gravity. The mirror
        inherits the player's current motion state — vy, on_ground, angle —
        with vy and angle sign-flipped because the mirror runs under
        opposite gravity. That way a dual portal crossed mid-jump produces
        a symmetric arc instead of a stalled mirror that drops from rest.

        Mirror y is placed symmetrically around the screen's horizontal
        midline so the two bodies appear equidistant from center.
        """
        if self.mirror is not None:
            return
        center = HEIGHT / 2.0
        mirror_y = 2.0 * center - self.y - self.size
        self.mirror = {
            "y": float(mirror_y),
            # Sign-flip vy: a player falling at +vy under +grav corresponds
            # to a mirror "falling" (toward its own ground) at -vy under
            # -grav. Both bodies trace symmetric arcs in screen space.
            "vy": -float(self.vy),
            "grav": -self.grav,
            # Inherit on_ground so a portal crossed mid-stride doesn't
            # spawn a mirror that "falls" out of a grounded pose. We read
            # _was_on_ground (captured at the top of update()) rather than
            # self.on_ground because the latter is reset to False before
            # the substep loop where this trigger fires; the pre-frame
            # value reflects whether the player was stably on ground.
            "on_ground": bool(getattr(self, "_was_on_ground", self.on_ground)),
            # Sign-flip angle so the mirror's rotation reads as a vertical
            # mirror image of the player.
            "angle": -float(getattr(self, "angle", 0.0)),
            "alive": True,
        }

    # ---- collision -------------------------------------------------------
    def _solid_rect(self, o):
        if o["t"] == T_BLOCK:
            return cell_rect(o["x"], o["y"])
        if o["t"] == T_SLAB:
            return slab_rect(o["x"], o["y"], o.get("r", 0))
        return None

    def _resolve_x_collision(self, dx_step):
        pr = self.rect()
        for o in self.nearby_for_rect(pr):
            br = self._solid_rect(o)
            if br is None:
                continue
            if pr.colliderect(br):
                if dx_step > 0:
                    self.x = br.left - self.size
                elif dx_step < 0:
                    self.x = br.right
                self.alive = False
                return True
        return False

    def _resolve_y_collision(self, dy_step):
        pr = self.rect()
        blocks = [o for o in self.nearby_for_rect(pr) if self._solid_rect(o) is not None]
        if dy_step > 0:
            blocks.sort(key=lambda o: self._solid_rect(o).y)
        elif dy_step < 0:
            blocks.sort(key=lambda o: -self._solid_rect(o).y)
        for o in blocks:
            br = self._solid_rect(o)
            if not pr.colliderect(br):
                continue
            if self.grav == 1:
                if dy_step >= 0:
                    self.y = br.top - self.size
                    self.vy = 0.0
                    self.on_ground = True
                else:
                    self.y = br.bottom
                    self.vy = 0.0
            else:
                if dy_step <= 0:
                    self.y = br.bottom
                    self.vy = 0.0
                    self.on_ground = True
                else:
                    self.y = br.top - self.size
                    self.vy = 0.0
            pr = self.rect()
        return False

    # ---- interactions ----------------------------------------------------
    def _handle_interactions(self, trigger_rect, hazard_rect, input_active):
        # End walls are infinite-height: any x-overlap with the wall column
        # wins, *if the player was behind the wall at the start of the frame*.
        # The frame-start gate prevents teleport orbs that sweep backward
        # through the finish column from triggering a premature win; if
        # you were already past the wall at tick start, you'd have won
        # already the previous frame.
        prev_right = getattr(self, "_x_at_frame_start", self.x) + self.size
        for wall_x in self._end_walls_x:
            # Overlap test against the wall column plus a "was behind at
            # frame start" gate. The gate rejects wins caused by teleport
            # sweeps that briefly pass through the wall from in front to
            # behind (or that end behind it).
            if (trigger_rect.right > wall_x and trigger_rect.left < wall_x + CELL
                    and prev_right <= wall_x):
                self.won = True
                return True
        orb_types = (T_ORB, T_DASH_ORB, T_BLACK_ORB, T_BLUE_ORB,
                     T_GREEN_ORB, T_TELEPORT_ORB)
        activated_orb_cell = None
        for o in self.nearby_for_rect(trigger_rect, 2):
            t = o["t"]
            if t == T_BLOCK or t == T_SLAB or t == T_START:
                continue
            key = (t, o["x"], o["y"])
            if t in (T_SPIKE, T_HALF_SPIKE):
                for sr in spike_hitboxes(o["x"], o["y"], o.get("r", 0), t == T_HALF_SPIKE):
                    if hazard_rect.colliderect(sr):
                        self.alive = False
                        return True
                continue
            if t == T_SAW:
                if hazard_rect.colliderect(saw_hitbox(o["x"], o["y"])):
                    self.alive = False
                    return True
                continue
            if t in PAD_TYPES and key not in self.passed:
                if trigger_rect.colliderect(pad_trigger_rect(o["x"], o["y"], o.get("r", 0))):
                    if t == T_BLUE_PAD:
                        self.flip_gravity()
                        self.vy = PAD_FORCE * 0.5 * self.grav
                    elif self.mode == MODE_SHIP:
                        self.vy = JUMP_FORCE * 0.95 * self.grav
                    elif self.mode != MODE_WAVE:
                        self.vy = PAD_FORCE * self.grav
                    self.on_ground = False
                    self.passed.add(key)
                continue
            cr = cell_rect(o["x"], o["y"])
            if not trigger_rect.colliderect(cr):
                continue
            if t == T_COIN:
                cid = o.get("coin_id", 0)
                if cid and cid not in self.coins_collected:
                    self.coins_collected.add(cid)
                continue
            if t == T_CHECKPOINT and key not in self.passed:
                # Trigger a checkpoint save in practice mode (handled upstream).
                self.passed.add(key)
                # Mark a request flag for the play loop.
                self._checkpoint_request = True
                continue
            if t in orb_types and key not in self.passed:
                cell = (o["x"], o["y"])
                if activated_orb_cell is None:
                    if self.input_buffer <= 0:
                        continue
                    if t == T_TELEPORT_ORB and self.teleport_cooldown != 0:
                        continue
                    activated_orb_cell = cell
                elif cell != activated_orb_cell:
                    continue
                if t == T_ORB:
                    self.activate_orb()
                    self.passed.add(key)
                elif t == T_DASH_ORB:
                    self.activate_dash_orb()
                    self.passed.add(key)
                elif t == T_BLACK_ORB:
                    self.activate_black_orb()
                    self.passed.add(key)
                elif t == T_BLUE_ORB:
                    self.activate_blue_orb()
                    self.passed.add(key)
                elif t == T_GREEN_ORB:
                    self.activate_green_orb()
                    self.passed.add(key)
                elif t == T_TELEPORT_ORB and self.teleport_cooldown == 0:
                    self.activate_teleport(o)
                    self.passed.add(key)
                    self.input_buffer = 0
                    return False
                continue
            if t == T_GRAV and key not in self.passed:
                self.flip_gravity()
                self.passed.add(key)
            elif t in MODE_FROM_TYPE and key not in self.passed:
                self.set_mode(MODE_FROM_TYPE[t])
                self.passed.add(key)
            elif t == T_MODE_MINI and key not in self.passed:
                self._set_size(MINI_PLAYER_SIZE)
                self.passed.add(key)
            elif t == T_MODE_BIG and key not in self.passed:
                self._set_size(PLAYER_SIZE)
                self.passed.add(key)
            elif t == T_MODE_DUAL and key not in self.passed:
                self._enter_dual()
                self.passed.add(key)
            elif t == T_MODE_SOLO and key not in self.passed:
                self.mirror = None
                self.passed.add(key)
            elif t in SPEED_VALUES and key not in self.passed:
                self.set_speed(t)
                self.passed.add(key)
            elif t == T_CAMERA_TRIGGER and key not in self.passed:
                target_row = o.get("cy", o["y"])
                self.target_cam_y = target_row * CELL + CELL / 2 - HEIGHT / 2
                self.passed.add(key)
            elif t == T_BG_TRIGGER and key not in self.passed:
                self.bg_preset = int(o.get("bg", 0))
                self.passed.add(key)
            elif t == T_MOVE_TRIGGER and key not in self.passed:
                self._start_move_trigger(o)
                self.passed.add(key)
            elif t == T_COLOR_TRIGGER and key not in self.passed:
                self.color_index = (self.color_index + 1) % len(PLAYER_COLORS)
                self.player_color = PLAYER_COLORS[self.color_index]
                self.passed.add(key)
            elif t == T_PULSE_TRIGGER and key not in self.passed:
                bpm = int(o.get("bpm", 128))
                duration_s = float(o.get("duration", 2.0))
                # Convert seconds to frames (60 FPS canonical).
                frames = max(1, int(duration_s * 60))
                self.active_pulses.append({
                    "start_frame": self.frame,
                    "end_frame": self.frame + frames,
                    "bpm": bpm,
                })
                self.passed.add(key)
            elif t == T_ROTATE_TRIGGER and key not in self.passed:
                self._start_rotate_trigger(o)
                self.passed.add(key)
            # T_END is handled at the top of this method as a column wall.
        if activated_orb_cell is not None:
            self.input_buffer = 0
        return False

    # ---- dual-mode mirror ------------------------------------------------
    def _step_mirror(self, input_held, input_pressed):
        """Update the dual-mode mirror body. The mirror shares x with the
        main player (its x always equals self.x) and has independent y
        physics with opposite gravity. It uses cube-mode jumps only — other
        modes are not mirrored to keep implementation tractable. If it
        hits a hazard or falls off-screen, sets mirror["alive"]=False so
        the main update loop can kill the player."""
        m = self.mirror
        if not m["alive"]:
            return
        # Gravity
        m["vy"] += GRAVITY * m["grav"]
        m["vy"] = clamp(m["vy"], -18.0, 18.0)
        # Cube-like jump on input when on ground
        if input_held and m["on_ground"]:
            m["vy"] = JUMP_FORCE * m["grav"]
            m["on_ground"] = False
        m["on_ground"] = False
        # Step y in small substeps so we don't tunnel through thin platforms
        steps = max(1, int(math.ceil(abs(m["vy"]) / 4.0)))
        dy_step = m["vy"] / steps
        for _ in range(steps):
            m["y"] += dy_step
            mrect = pygame.Rect(round(self.x), round(m["y"]), self.size, self.size)
            # Block collision (y only)
            for o in self.nearby_for_rect(mrect):
                br = self._solid_rect(o)
                if br is None:
                    continue
                if mrect.colliderect(br):
                    if m["grav"] == 1:
                        if dy_step >= 0:
                            m["y"] = br.top - self.size
                            m["vy"] = 0.0
                            m["on_ground"] = True
                        else:
                            m["y"] = br.bottom
                            m["vy"] = 0.0
                    else:
                        if dy_step <= 0:
                            m["y"] = br.bottom
                            m["vy"] = 0.0
                            m["on_ground"] = True
                        else:
                            m["y"] = br.top - self.size
                            m["vy"] = 0.0
                    mrect = pygame.Rect(round(self.x), round(m["y"]),
                                        self.size, self.size)
        # Off-screen kill
        if m["y"] > HEIGHT + 300 or m["y"] < -500:
            m["alive"] = False
            return
        # Hazard collision (spikes, saws) using mirror's hitbox
        shrink = max(2, int(6 * self.size / PLAYER_SIZE))
        hazard_rect = pygame.Rect(round(self.x) + shrink, round(m["y"]) + shrink,
                                  self.size - shrink * 2, self.size - shrink * 2)
        trigger_rect = pygame.Rect(round(self.x), round(m["y"]),
                                   self.size, self.size).inflate(6, 6)
        for o in self.nearby_for_rect(trigger_rect, 2):
            t = o["t"]
            if t in (T_SPIKE, T_HALF_SPIKE):
                for sr in spike_hitboxes(o["x"], o["y"], o.get("r", 0),
                                         t == T_HALF_SPIKE):
                    if hazard_rect.colliderect(sr):
                        m["alive"] = False
                        return
            elif t == T_SAW:
                if hazard_rect.colliderect(saw_hitbox(o["x"], o["y"])):
                    m["alive"] = False
                    return
        # Mirror rotation (visual only, cube-style)
        if not m["on_ground"]:
            m["angle"] = m.get("angle", 0.0) - 5 * m["grav"]
        else:
            m["angle"] = round(m.get("angle", 0.0) / 90) * 90

    # ---- per-frame update ------------------------------------------------
    def update(self, input_held, input_pressed):
        if not self.alive or self.won:
            return
        self.frame += 1
        # Snapshot x before anything moves this frame. End-wall crossing is
        # evaluated against this so that teleport orbs that sweep backward
        # through the finish column don't trigger a premature win.
        self._x_at_frame_start = self.x
        self._step_move_animations()
        self._step_rotate_triggers()
        # Drop pulse triggers that have expired.
        if self.active_pulses:
            self.active_pulses = [p for p in self.active_pulses
                                  if p["end_frame"] > self.frame]
        if self.teleport_cooldown > 0:
            self.teleport_cooldown -= 1
        if self._grav_flip_grace > 0:
            self._grav_flip_grace -= 1
        if self.frame % 3 == 0:
            self.trail.append([self.x, self.y, self.angle, 100])
        self.trail = [[x, y, a, al - 5] for x, y, a, al in self.trail if al > 5]
        if input_pressed:
            self.input_buffer = 6
        elif self.input_buffer > 0:
            self.input_buffer -= 1
        # Mode physics
        if self.mode == MODE_SHIP:
            self.vy += SHIP_GRAVITY * self.grav
            if input_held:
                self.vy -= SHIP_THRUST * self.grav
            self.vy = clamp(self.vy, -13.0, 13.0)
        elif self.mode == MODE_WAVE:
            direction = -1 if input_held else 1
            self.vy = self.move_speed * direction * self.grav
        elif self.mode == MODE_UFO:
            self.vy += GRAVITY * self.grav
            self.vy = clamp(self.vy, -18.0, 18.0)
            if input_pressed:
                self.vy = UFO_JUMP_FORCE * self.grav
                self.on_ground = False
                self.input_buffer = 0
        elif self.mode == MODE_SPIDER:
            self.vy += GRAVITY * self.grav
            self.vy = clamp(self.vy, -18.0, 18.0)
            if input_pressed and self.on_ground:
                self._spider_teleport()
                self.input_buffer = 0
        else:
            self.vy += GRAVITY * self.grav
            self.vy = clamp(self.vy, -18.0, 18.0)
            if self.mode == MODE_CUBE and input_held and self.on_ground:
                self.jump()
            elif self.mode == MODE_BALL and input_pressed and self.on_ground:
                self.grav *= -1
                self.vy = BALL_FLIP_FORCE * self.grav
                self.on_ground = False
        dx = self.move_speed + (DASH_SPEED if self.dash_timer > 0 else 0.0)
        if self.dash_timer > 0:
            self.dash_timer -= 1
        # Stash the post-collision on_ground from last frame so portal
        # triggers — which fire mid-substep, after on_ground gets cleared
        # below — can ask "was this player stably grounded?" rather than
        # always seeing False. _enter_dual reads this so a mirror spawned
        # by a walking player inherits grounded state correctly.
        self._was_on_ground = self.on_ground
        self.on_ground = False
        steps = max(1, int(math.ceil(max(abs(dx), abs(self.vy)) / 4.0)))
        dx_step = dx / steps
        input_active = input_held or self.input_buffer > 0
        for _ in range(steps):
            prev_rect = self.rect()
            self.x += dx_step
            if self._resolve_x_collision(dx_step):
                return
            dy_step = self.vy / steps
            self.y += dy_step
            if self._resolve_y_collision(dy_step):
                return
            trigger_rect = prev_rect.union(self.rect()).inflate(6, 6)
            hazard_rect = self.hitbox()
            if self._handle_interactions(trigger_rect, hazard_rect, input_active):
                return
        if self.y > HEIGHT + 300 or self.y < -500:
            self.alive = False
            return
        # Dual-mode: step the mirror body. If the mirror dies, the attempt
        # dies with it. This must run after the main physics so the mirror
        # sees the post-step x position.
        if self.mirror is not None:
            self._step_mirror(input_held, input_pressed)
            if not self.mirror["alive"]:
                self.alive = False
                return
        # Rotation (visual)
        if self.mode == MODE_SHIP:
            self.angle = clamp(-self.vy * 4.2, -55, 55)
        elif self.mode == MODE_UFO:
            self.angle = clamp(-self.vy * 2.8, -30, 30)
        elif self.mode == MODE_WAVE:
            self.angle = WAVE_ANGLE * (-1 if (input_held and self.grav == 1) or
                                       (not input_held and self.grav == -1) else 1)
        elif self.mode == MODE_BALL:
            if self.on_ground:
                self.angle = round(self.angle / 90) * 90
            else:
                self.angle -= 10 * self.grav
        elif self.mode == MODE_SPIDER:
            if self.on_ground:
                self.angle = 0
            else:
                self.angle -= 6 * self.grav
        else:
            if not self.on_ground:
                self.angle -= 5 * self.grav
            else:
                self.angle = round(self.angle / 90) * 90

    # ---- draw -----------------------------------------------------------
    def _player_color(self):
        return self.player_color

    def _draw_player_surface(self):
        col = self._player_color()
        ps = pygame.Surface((PLAYER_SIZE, PLAYER_SIZE), pygame.SRCALPHA)
        if self.mode == MODE_SHIP:
            pygame.draw.polygon(ps, darker(col, 30),
                                [(4, PLAYER_SIZE // 2 + 1), (PLAYER_SIZE - 8, 8),
                                 (PLAYER_SIZE - 8, PLAYER_SIZE - 6)])
            pygame.draw.polygon(ps, col,
                                [(4, PLAYER_SIZE // 2), (PLAYER_SIZE - 8, 7),
                                 (PLAYER_SIZE - 8, PLAYER_SIZE - 7)])
            pygame.draw.polygon(ps, lighter(col, 60),
                                [(8, PLAYER_SIZE // 2), (PLAYER_SIZE - 14, 13),
                                 (PLAYER_SIZE - 14, PLAYER_SIZE - 13)], 2)
            flame_col = C_DASH_ORB if self.dash_timer > 0 else C_PAD
            pygame.draw.polygon(ps, flame_col,
                                [(3, PLAYER_SIZE // 2), (12, PLAYER_SIZE // 2 - 6),
                                 (12, PLAYER_SIZE // 2 + 6)])
        elif self.mode == MODE_BALL:
            pygame.draw.circle(ps, darker(col, 30),
                               (PLAYER_SIZE // 2, PLAYER_SIZE // 2 + 2), PLAYER_SIZE // 2 - 2)
            pygame.draw.circle(ps, col,
                               (PLAYER_SIZE // 2, PLAYER_SIZE // 2), PLAYER_SIZE // 2 - 2)
            pygame.draw.circle(ps, lighter(col, 60),
                               (PLAYER_SIZE // 2, PLAYER_SIZE // 2), PLAYER_SIZE // 2 - 8, 2)
            pygame.draw.circle(ps, darker(col, 40),
                               (PLAYER_SIZE // 2, PLAYER_SIZE // 2), 6)
        elif self.mode == MODE_WAVE:
            cx = PLAYER_SIZE // 2
            pts = [(cx, 4), (PLAYER_SIZE - 4, cx), (cx, PLAYER_SIZE - 4), (4, cx)]
            pygame.draw.polygon(ps, darker(C_MODE_WAVE, 40), [(p[0], p[1] + 2) for p in pts])
            pygame.draw.polygon(ps, col, pts)
            pygame.draw.polygon(ps, lighter(col, 60), pts, 2)
            pygame.draw.circle(ps, lighter(C_MODE_WAVE, 60), (cx, cx), 4)
        elif self.mode == MODE_UFO:
            cx = PLAYER_SIZE // 2
            cy = PLAYER_SIZE // 2
            body_rect = pygame.Rect(3, cy - 2, PLAYER_SIZE - 6, 10)
            pygame.draw.ellipse(ps, darker(C_MODE_UFO, 40), body_rect.move(0, 2))
            pygame.draw.ellipse(ps, C_MODE_UFO, body_rect)
            pygame.draw.ellipse(ps, lighter(C_MODE_UFO, 60), body_rect.inflate(-6, -4), 2)
            dome = pygame.Rect(cx - 10, cy - 12, 20, 16)
            pygame.draw.ellipse(ps, darker(col, 30), dome.move(0, 2))
            pygame.draw.ellipse(ps, col, dome)
            pygame.draw.ellipse(ps, lighter(col, 70), dome.inflate(-6, -6), 2)
            for ox in (-12, 0, 12):
                pygame.draw.circle(ps, (255, 255, 255), (cx + ox, cy + 8), 2)
        elif self.mode == MODE_SPIDER:
            cx = PLAYER_SIZE // 2
            cy = PLAYER_SIZE // 2
            # Body
            pygame.draw.circle(ps, darker(C_MODE_SPIDER, 30), (cx, cy + 1), cx - 6)
            pygame.draw.circle(ps, C_MODE_SPIDER, (cx, cy), cx - 6)
            pygame.draw.circle(ps, col, (cx, cy), cx - 12)
            # Legs (four)
            for ox in (-2, 2):
                for oy in (-1, 1):
                    pygame.draw.line(ps, darker(C_MODE_SPIDER, 40),
                                     (cx, cy), (cx + ox * cx, cy + oy * cy), 3)
        else:
            pygame.draw.rect(ps, darker(col, 30),
                             (1, 3, PLAYER_SIZE - 2, PLAYER_SIZE - 2), border_radius=3)
            pygame.draw.rect(ps, col,
                             (0, 0, PLAYER_SIZE, PLAYER_SIZE), border_radius=3)
            pygame.draw.rect(ps, lighter(col, 60),
                             (3, 3, PLAYER_SIZE - 6, PLAYER_SIZE - 6), 2, border_radius=3)
            # Inset glyph: chosen by the player from the customize menu.
            # Defaults to the classic inset square if icon_index is invalid.
            draw_cube_icon_glyph(ps, 0, 0, PLAYER_SIZE, col, self.icon_index)
        return ps

    def draw(self, surf, cam_x, cam_y=0):
        col = self._player_color()
        # Trails are drawn at the size the player had at the time the trail
        # sample was stored. For simplicity we draw them at the current
        # self.size so shrinking/growing doesn't leave mismatched ghosts.
        size = self.size
        # Wave and ship draw a continuous LINE trail (matches GD) instead of
        # the ghost-sprite trail used by cube/ball/UFO/spider. The line
        # connects consecutive trail samples on a single SRCALPHA surface
        # so each segment can fade independently — drawing per-segment on
        # the screen wouldn't compose alpha correctly against varying bg.
        if self.mode in (MODE_WAVE, MODE_SHIP) and len(self.trail) >= 2:
            trail_thickness = 5 if self.mode == MODE_SHIP else 3
            line_surf = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            half = size // 2
            for i in range(len(self.trail) - 1):
                x1, y1, _, al1 = self.trail[i]
                x2, y2, _, al2 = self.trail[i + 1]
                sx1 = x1 - cam_x + half
                sy1 = y1 - cam_y + half
                sx2 = x2 - cam_x + half
                sy2 = y2 - cam_y + half
                # Skip segments fully off-screen on both ends.
                if (sx1 < -60 and sx2 < -60) or (sx1 > WIDTH + 60 and sx2 > WIDTH + 60):
                    continue
                # Average the two endpoints' alphas so each segment fades
                # smoothly with its position in the trail.
                avg_al = max(0, min(255, int((al1 + al2) * 0.5 * 0.7)))
                pygame.draw.line(
                    line_surf, (*col, avg_al),
                    (int(sx1), int(sy1)), (int(sx2), int(sy2)),
                    trail_thickness,
                )
            surf.blit(line_surf, (0, 0))
        else:
            for tx, ty, ta, al in self.trail:
                sx = tx - cam_x
                sy_t = ty - cam_y
                if sx < -60 or sx > WIDTH + 60:
                    continue
                ts = pygame.Surface((PLAYER_SIZE, PLAYER_SIZE), pygame.SRCALPHA)
                if self.mode == MODE_BALL:
                    pygame.draw.circle(ts, (*col, int(al * 0.35)),
                                       (PLAYER_SIZE // 2, PLAYER_SIZE // 2), PLAYER_SIZE // 2 - 2)
                elif self.mode == MODE_UFO:
                    cy = PLAYER_SIZE // 2
                    pygame.draw.ellipse(ts, (*col, int(al * 0.35)),
                                        (4, cy - 2, PLAYER_SIZE - 8, 10))
                elif self.mode == MODE_SPIDER:
                    pygame.draw.circle(ts, (*col, int(al * 0.35)),
                                       (PLAYER_SIZE // 2, PLAYER_SIZE // 2), PLAYER_SIZE // 2 - 4)
                else:
                    ts.fill((*col, int(al * 0.4)))
                if size != PLAYER_SIZE:
                    ts = pygame.transform.smoothscale(ts, (size, size))
                rot = pygame.transform.rotate(ts, ta)
                rr = rot.get_rect(center=(sx + size // 2, sy_t + size // 2))
                surf.blit(rot, rr)
        sx = self.x - cam_x
        sy = self.y - cam_y
        ps = self._draw_player_surface()
        if size != PLAYER_SIZE:
            ps = pygame.transform.smoothscale(ps, (size, size))
        rot = pygame.transform.rotate(ps, self.angle)
        rr = rot.get_rect(center=(sx + size // 2, sy + size // 2))
        surf.blit(rot, rr)
        # Dual-mode mirror — render as a cube in the same colour, flipped
        # vertically, at mirror["y"]. Alive-dimming if the mirror died.
        if self.mirror is not None:
            my = self.mirror["y"] - cam_y
            msurf = self._draw_player_surface()
            if size != PLAYER_SIZE:
                msurf = pygame.transform.smoothscale(msurf, (size, size))
            # Flip vertically so the mirror reads as upside-down (matches
            # its inverted gravity).
            msurf = pygame.transform.flip(msurf, False, True)
            if not self.mirror["alive"]:
                msurf.set_alpha(90)
            mrot = pygame.transform.rotate(msurf, self.mirror.get("angle", 0.0))
            mrr = mrot.get_rect(center=(sx + size // 2, my + size // 2))
            surf.blit(mrot, mrr)
