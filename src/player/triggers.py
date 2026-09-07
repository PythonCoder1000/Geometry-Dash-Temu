"""Level triggers that animate objects: move, rotate, follow, pulse."""

import math

from ..constants import CELL, DEFAULT_MOVE_CURVE, T_FOLLOW_TRIGGER
from .collision import invalidate_pose_caches


def curve_progress(curve, total_area, t):
    """Integrate a speed curve up to time ``t``, normalised to [0, 1]."""
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


def curve_area(curve):
    if not curve or len(curve) < 2:
        return 1.0
    return sum((curve[i + 1][0] - curve[i][0]) * (curve[i][1] + curve[i + 1][1])
               * 0.5 for i in range(len(curve) - 1))


class TriggerMixin:
    __slots__ = ()

    def _resolve_targets(self, trig):
        """Objects a move / rotate trigger targets: explicit oids first,
        then group members, duplicates dropped."""
        seen = set()
        out = []
        for oid in (trig.get("target_oids") or ()):
            if oid and oid not in seen:
                o = self._by_oid.get(oid)
                if o is not None:
                    seen.add(oid)
                    out.append(o)
        single = trig.get("target_oid")
        if single and single not in seen:
            o = self._by_oid.get(single)
            if o is not None:
                seen.add(single)
                out.append(o)
        group = trig.get("group")
        if group:
            for o in self._by_group.get(group, ()):
                oid = o.get("oid")
                if oid is None:
                    out.append(o)
                elif oid not in seen:
                    seen.add(oid)
                    out.append(o)
        return out

    def _set_object_pos(self, obj, fx, fy, final=False):
        """Write a (fractional) position, refresh caches + spatial index."""
        obj["x"] = int(round(fx))
        obj["y"] = int(round(fy))
        if final:
            obj.pop("_fx", None)
            obj.pop("_fy", None)
        else:
            obj["_fx"] = fx
            obj["_fy"] = fy
        invalidate_pose_caches(obj)
        self._spatial_rebucket(obj)
        self._ever_moved[self._oid_index[id(obj)]] = obj

    # ---- move --------------------------------------------------------------
    def _start_move_trigger(self, trig):
        targets = self._resolve_targets(trig)
        if not targets:
            return
        duration = max(1, int(trig.get("duration", 30)))
        curve = trig.get("curve", DEFAULT_MOVE_CURVE)
        area = curve_area(curve)
        first = targets[0]
        dx = float(trig.get("tx", first["x"])) - float(first.get("_fx", first["x"]))
        dy = float(trig.get("ty", first["y"])) - float(first.get("_fy", first["y"]))
        for target in targets:
            sx = float(target.get("_fx", target["x"]))
            sy = float(target.get("_fy", target["y"]))
            self.move_animations.append({
                "obj": target, "sx": sx, "sy": sy, "ex": sx + dx, "ey": sy + dy,
                "frame": 0, "duration": duration,
                "curve": curve, "curve_area": area,
            })

    def _step_move_animations(self):
        if not self.move_animations:
            return
        remaining = []
        for anim in self.move_animations:
            anim["frame"] += 1
            t = min(1.0, anim["frame"] / anim["duration"])
            te = curve_progress(anim["curve"], anim["curve_area"], t)
            fx = anim["sx"] + (anim["ex"] - anim["sx"]) * te
            fy = anim["sy"] + (anim["ey"] - anim["sy"]) * te
            done = anim["frame"] >= anim["duration"]
            if done:
                self._set_object_pos(anim["obj"], anim["ex"], anim["ey"], True)
            else:
                self._set_object_pos(anim["obj"], fx, fy)
                remaining.append(anim)
        self.move_animations = remaining

    # ---- rotate ------------------------------------------------------------
    def _start_rotate_trigger(self, trig):
        targets = self._resolve_targets(trig)
        if not targets:
            return
        spin_dps = float(trig.get("spin", 90.0))
        frames = max(1, int(float(trig.get("duration", 4.0)) * 60))
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
                o["r"] = (float(o.get("r", 0)) + rot["spin_per_frame"]) % 360.0
                invalidate_pose_caches(o)
            remaining.append(rot)
        self.active_rotations = remaining

    # ---- follow ------------------------------------------------------------
    def _start_follow_trigger(self, trig):
        """Link a target to a source (or a source to the live player).
        Idempotent."""
        src_oid = trig.get("source_oid")
        tgt_oid = trig.get("target_oid")
        if trig.get("follow_player"):
            source = self._by_oid.get(src_oid) if src_oid else None
            if source is None:
                return
            for f in self.active_follows:
                if f["source"] is None and f["target"] is source:
                    return
            self.active_follows.append({
                "source": None, "target": source,
                "offset_x": float(int(trig.get("offset_cx", 0))),
                "offset_y": float(int(trig.get("offset_cy", 0))),
            })
            self._ever_moved[self._oid_index[id(source)]] = source
            return
        if not src_oid or not tgt_oid or src_oid == tgt_oid:
            return
        source = self._by_oid.get(src_oid)
        target = self._by_oid.get(tgt_oid)
        if source is None or target is None:
            return
        for f in self.active_follows:
            if f["source"] is source and f["target"] is target:
                return
        sx = float(source.get("_fx", source["x"]))
        sy = float(source.get("_fy", source["y"]))
        self.active_follows.append({
            "source": source, "target": target,
            "offset_x": float(target.get("_fx", target["x"])) - sx,
            "offset_y": float(target.get("_fy", target["y"])) - sy,
        })
        self._ever_moved[self._oid_index[id(source)]] = source
        self._ever_moved[self._oid_index[id(target)]] = target

    def _step_follow_triggers(self):
        if not self.active_follows:
            return
        for link in self.active_follows:
            source = link["source"]
            if source is None:  # follows the live player (cell coords)
                sx = self.x / CELL
                sy = self.y / CELL
            else:
                sx = float(source.get("_fx", source["x"]))
                sy = float(source.get("_fy", source["y"]))
            self._set_object_pos(link["target"], sx + link["offset_x"],
                                 sy + link["offset_y"])

    def _arm_always_on_follows(self):
        for o in self.objects:
            if o.get("t") == T_FOLLOW_TRIGGER and o.get("always_on"):
                self._start_follow_trigger(o)

    # ---- pulse -------------------------------------------------------------
    def _start_pulse_trigger(self, trig):
        frames = max(1, int(float(trig.get("duration", 2.0)) * 60))
        self.active_pulses.append({
            "start_frame": self.frame,
            "end_frame": self.frame + frames,
            "bpm": int(trig.get("bpm", 128)),
        })

    def pulse_intensity(self):
        """[0, 1] flash intensity from active pulse triggers."""
        if not self.active_pulses:
            return 0.0
        total = 0.0
        for p in self.active_pulses:
            frames_per_beat = 3600.0 / max(1, p["bpm"])
            phase = ((self.frame - p["start_frame"]) / frames_per_beat) * math.tau
            total += math.sin(phase) ** 2
        return min(1.0, total)

    # ---- blackout ------------------------------------------------------
    def _start_blackout_trigger(self, trig):
        """Fade the full-screen blackout overlay toward on (1.0) or off
        (0.0) over ``duration`` seconds, smoothstep-eased."""
        target = 1.0 if trig.get("state", True) else 0.0
        duration = max(0.0, float(trig.get("duration", 1.0)))
        self.blackout_start = self.blackout_value
        self.blackout_target = target
        self.blackout_start_frame = self.frame
        self.blackout_frames = max(1, int(round(duration * 60)))

    def _step_blackout(self):
        if self.blackout_value == self.blackout_target:
            return
        t = min(1.0, (self.frame - self.blackout_start_frame) / self.blackout_frames)
        te = t * t * (3.0 - 2.0 * t)  # smoothstep
        self.blackout_value = (self.blackout_start
                               + (self.blackout_target - self.blackout_start) * te)
