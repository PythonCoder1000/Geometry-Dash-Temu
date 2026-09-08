"""Level triggers that animate objects: move, rotate, follow, pulse, plus
the Checkpoint 5 group-targeted / logic family (Spawn, Toggle, Stop,
Sequence, Scale, Alpha)."""

import math

from ..constants import (
    CELL, HEIGHT, DEFAULT_MOVE_CURVE, PHYSICS_TPS,
    T_CAMERA_TRIGGER, T_BG_TRIGGER, T_MOVE_TRIGGER, T_COLOR_TRIGGER,
    T_PULSE_TRIGGER, T_ROTATE_TRIGGER, T_FOLLOW_TRIGGER, T_TIME_WARP,
    T_BLACKOUT_TRIGGER, T_SPAWN_TRIGGER, T_TOGGLE_TRIGGER, T_STOP_TRIGGER,
    T_SEQUENCE_TRIGGER, T_SCALE_TRIGGER, T_ALPHA_TRIGGER, TRIGGER_TYPES,
    T_ZOOM_TRIGGER, T_CAM_OFFSET_TRIGGER, T_CAM_ROTATE_TRIGGER,
    T_CAM_EDGE_TRIGGER, T_CAM_GUIDE_TRIGGER,
    T_GRAYSCALE_TRIGGER, T_SEPIA_TRIGGER, T_INVERT_TRIGGER, T_HUE_TRIGGER,
    T_PIXELATE_TRIGGER,
    T_COUNT_TRIGGER, T_INSTANT_COUNT_TRIGGER, T_ITEM_EDIT_TRIGGER,
    T_ITEM_COMP_TRIGGER, T_ITEM_PERS_TRIGGER, T_TIME_TRIGGER,
    T_TIME_EVENT_TRIGGER, T_KEYFRAME_TRIGGER,
)
from ..channels import channel_color
from ..levels import get_groups
from ..geometry import obj_scale
from .collision import invalidate_pose_caches


def _ease(kind, t):
    """[0, 1] progress -> eased [0, 1]. Unknown/'linear' passes through."""
    if kind == "ease_in":
        return t * t
    if kind == "ease_out":
        return 1.0 - (1.0 - t) * (1.0 - t)
    if kind == "ease_in_out":
        return t * t * (3.0 - 2.0 * t)  # smoothstep
    return t


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
        # NOTE: this reads "target_group", never the bare "groups"/"group"
        # membership fields get_groups() resolves -- those name which
        # groups an object BELONGS to; this names which group a trigger
        # ACTS ON. Conflating the two would make a Spawn/Toggle/Sequence
        # trigger a member of its own target group (get_groups()'s legacy
        # singular-"group" fallback), which self-refires forever the
        # first time such a trigger targets its own group.
        group = trig.get("target_group")
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
        easing = trig.get("easing", "linear")
        first = targets[0]
        dx = float(trig.get("tx", first["x"])) - float(first.get("_fx", first["x"]))
        dy = float(trig.get("ty", first["y"])) - float(first.get("_fy", first["y"]))
        for target in targets:
            sx = float(target.get("_fx", target["x"]))
            sy = float(target.get("_fy", target["y"]))
            self.move_animations.append({
                "obj": target, "sx": sx, "sy": sy, "ex": sx + dx, "ey": sy + dy,
                "frame": 0, "duration": duration,
                "curve": curve, "curve_area": area, "easing": easing,
            })

    def _step_move_animations(self):
        if not self.move_animations:
            return
        remaining = []
        for anim in self.move_animations:
            anim["frame"] += 1
            t = min(1.0, anim["frame"] / anim["duration"])
            # A custom speed curve (authored via the editor's move-ghost
            # tool) and a fixed easing choice both reshape progress the
            # same way -- apply curve first, then compose the easing
            # curve on top (a no-op "linear" easing on the common case
            # where only the curve is authored).
            te = curve_progress(anim["curve"], anim["curve_area"], t)
            te = _ease(anim.get("easing", "linear"), te)
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
        # `duration` is authored in seconds; convert via the live tick
        # rate (not a hardcoded 60) so this stays correct at 240 TPS.
        frames = max(1, int(float(trig.get("duration", 4.0)) * PHYSICS_TPS))
        self.active_rotations.append({
            "targets": targets,
            "spin_per_frame": spin_dps / PHYSICS_TPS,
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

    # ---- scale (Checkpoint 5) -----------------------------------------------
    def _start_scale_trigger(self, trig):
        targets = self._resolve_targets(trig)
        if not targets:
            return
        duration = max(1, int(float(trig.get("duration", 0.5)) * PHYSICS_TPS))
        tsx = float(trig.get("sx", 1.0))
        tsy = float(trig.get("sy", 1.0))
        easing = trig.get("easing", "linear")
        for target in targets:
            ssx, ssy = obj_scale(target)
            self.active_scales.append({
                "obj": target, "ssx": ssx, "ssy": ssy,
                "esx": tsx, "esy": tsy, "frame": 0, "duration": duration,
                "easing": easing,
            })

    def _step_scale_animations(self):
        if not self.active_scales:
            return
        remaining = []
        for anim in self.active_scales:
            anim["frame"] += 1
            t = min(1.0, anim["frame"] / anim["duration"])
            te = _ease(anim["easing"], t)
            o = anim["obj"]
            o["sx"] = anim["ssx"] + (anim["esx"] - anim["ssx"]) * te
            o["sy"] = anim["ssy"] + (anim["esy"] - anim["ssy"]) * te
            invalidate_pose_caches(o)
            if anim["frame"] < anim["duration"]:
                remaining.append(anim)
        self.active_scales = remaining

    # ---- alpha (Checkpoint 5) -----------------------------------------------
    def _start_alpha_trigger(self, trig):
        targets = self._resolve_targets(trig)
        if not targets:
            return
        duration = max(1, int(float(trig.get("duration", 0.5)) * PHYSICS_TPS))
        target_alpha = max(0.0, min(1.0, float(trig.get("alpha", 1.0))))
        easing = trig.get("easing", "linear")
        for target in targets:
            start_alpha = float(target.get("_alpha", 1.0))
            self.active_alphas.append({
                "obj": target, "sa": start_alpha, "ea": target_alpha,
                "frame": 0, "duration": duration, "easing": easing,
            })

    def _step_alpha_animations(self):
        if not self.active_alphas:
            return
        remaining = []
        for anim in self.active_alphas:
            anim["frame"] += 1
            t = min(1.0, anim["frame"] / anim["duration"])
            te = _ease(anim["easing"], t)
            o = anim["obj"]
            o["_alpha"] = anim["sa"] + (anim["ea"] - anim["sa"]) * te
            if anim["frame"] < anim["duration"]:
                remaining.append(anim)
        self.active_alphas = remaining

    # ---- keyframe animation (Checkpoint 8, simplified) ----------------------
    def _start_keyframe_trigger(self, trig):
        """Play the target group through every Keyframe sharing this
        trigger's animation id, in Order. Position is delta-based (like
        Move Trigger: the *first* target member is the anchor, and every
        member keeps its own offset from the anchor, preserving group
        formation); rotation/scale snap every member to the keyframe's
        absolute value (like Rotate/Scale Trigger), since per-member
        relative rotation/scale has no single sensible anchor."""
        group = trig.get("target_group")
        if not group:
            return
        targets = list(self._by_group.get(group, ()))
        if not targets:
            return
        anim_id = trig.get("animation_id", 0)
        kfs = self._by_animation.get(anim_id)
        if not kfs:
            return
        anchor = targets[0]
        start_x = float(anchor.get("_fx", anchor["x"]))
        start_y = float(anchor.get("_fy", anchor["y"]))
        start_r = float(anchor.get("r", 0.0))
        start_sx, start_sy = obj_scale(anchor)

        timing_mode = trig.get("timing_mode", "time")
        total_duration = max(0.0, float(trig.get("total_duration", 2.0)))
        n = len(kfs)
        if timing_mode == "even":
            seg_secs = [total_duration / n] * n
        elif timing_mode == "dist":
            # Distance-based spacing: each segment's share of the total
            # duration is proportional to how far the anchor's target
            # position moves during that segment (bible gives no numeric
            # spec for Dist -- this is a reasonable, documented
            # approximation, not a rewrite of the real editor's algorithm).
            dists = []
            px, py = start_x, start_y
            for kf in kfs:
                tx = float(kf.get("tx", px))
                ty = float(kf.get("ty", py))
                dists.append(max(math.hypot(tx - px, ty - py), 1e-6))
                px, py = tx, ty
            total_d = sum(dists)
            seg_secs = ([total_duration * d / total_d for d in dists]
                       if total_d > 1e-9 else [total_duration / n] * n)
        else:
            seg_secs = [max(0.0, float(kf.get("time", 0.5))) for kf in kfs]

        segments = []
        px, py, pr, psx, psy = start_x, start_y, start_r, start_sx, start_sy
        for kf, secs in zip(kfs, seg_secs):
            tx = float(kf.get("tx", px))
            ty = float(kf.get("ty", py))
            tr = float(kf.get("rotation", pr))
            tsx = float(kf.get("sx", psx))
            tsy = float(kf.get("sy", psy))
            duration = max(1, int(round(secs * PHYSICS_TPS)))
            segments.append({
                "sx": px, "sy": py, "sr": pr, "ssx": psx, "ssy": psy,
                "ex": tx, "ey": ty, "er": tr, "esx": tsx, "esy": tsy,
                "duration": duration, "easing": kf.get("easing", "linear"),
            })
            px, py, pr, psx, psy = tx, ty, tr, tsx, tsy

        offsets = []
        for t in targets:
            ox = float(t.get("_fx", t["x"])) - start_x
            oy = float(t.get("_fy", t["y"])) - start_y
            offsets.append((t, ox, oy))

        self.active_keyframe_anims.append({
            "targets": offsets, "segments": segments,
            "seg_idx": 0, "frame": 0,
        })

    def _step_keyframe_animations(self):
        if not self.active_keyframe_anims:
            return
        remaining = []
        for anim in self.active_keyframe_anims:
            segs = anim["segments"]
            idx = anim["seg_idx"]
            if idx >= len(segs):
                continue
            seg = segs[idx]
            anim["frame"] += 1
            t = min(1.0, anim["frame"] / seg["duration"])
            te = _ease(seg["easing"], t)
            cx = seg["sx"] + (seg["ex"] - seg["sx"]) * te
            cy = seg["sy"] + (seg["ey"] - seg["sy"]) * te
            cr = seg["sr"] + (seg["er"] - seg["sr"]) * te
            csx = seg["ssx"] + (seg["esx"] - seg["ssx"]) * te
            csy = seg["ssy"] + (seg["esy"] - seg["ssy"]) * te
            for o, ox, oy in anim["targets"]:
                self._set_object_pos(o, cx + ox, cy + oy)
                o["r"] = cr % 360.0
                o["sx"] = csx
                o["sy"] = csy
                invalidate_pose_caches(o)
            if anim["frame"] >= seg["duration"]:
                anim["seg_idx"] += 1
                anim["frame"] = 0
            if anim["seg_idx"] < len(segs):
                remaining.append(anim)
        self.active_keyframe_anims = remaining

    # ---- camera family (Checkpoint 6) ---------------------------------------
    def _start_zoom_trigger(self, trig):
        duration = max(1, int(round(max(0.0, float(trig.get("duration", 1.0)))
                                    * PHYSICS_TPS)))
        target_zoom = max(0.1, float(trig.get("zoom", 1.5)))
        easing = trig.get("easing", "linear")
        self.active_zooms.append({
            "start": self.zoom, "end": target_zoom, "frame": 0,
            "duration": duration, "easing": easing,
        })

    def _step_zoom_animations(self):
        if not self.active_zooms:
            return
        remaining = []
        for anim in self.active_zooms:
            anim["frame"] += 1
            t = min(1.0, anim["frame"] / anim["duration"])
            te = _ease(anim["easing"], t)
            self.zoom = anim["start"] + (anim["end"] - anim["start"]) * te
            if anim["frame"] < anim["duration"]:
                remaining.append(anim)
        self.active_zooms = remaining

    def _start_cam_offset_trigger(self, trig):
        duration = max(1, int(round(max(0.0, float(trig.get("duration", 1.0)))
                                    * PHYSICS_TPS)))
        tx = float(trig.get("offset_x", 0))
        ty = float(trig.get("offset_y", 0))
        easing = trig.get("easing", "linear")
        self.active_cam_offsets.append({
            "sx": self.cam_offset_x, "sy": self.cam_offset_y,
            "ex": tx, "ey": ty, "frame": 0, "duration": duration,
            "easing": easing,
        })

    def _step_cam_offset_animations(self):
        if not self.active_cam_offsets:
            return
        remaining = []
        for anim in self.active_cam_offsets:
            anim["frame"] += 1
            t = min(1.0, anim["frame"] / anim["duration"])
            te = _ease(anim["easing"], t)
            self.cam_offset_x = anim["sx"] + (anim["ex"] - anim["sx"]) * te
            self.cam_offset_y = anim["sy"] + (anim["ey"] - anim["sy"]) * te
            if anim["frame"] < anim["duration"]:
                remaining.append(anim)
        self.active_cam_offsets = remaining

    def _start_cam_rotate_trigger(self, trig):
        duration = max(1, int(round(max(0.0, float(trig.get("duration", 2.0)))
                                    * PHYSICS_TPS)))
        target_angle = float(trig.get("angle", 15.0))
        easing = trig.get("easing", "linear")
        self.active_cam_rotations.append({
            "start": self.cam_rotation, "end": target_angle, "frame": 0,
            "duration": duration, "easing": easing,
        })

    def _step_cam_rotation_animations(self):
        if not self.active_cam_rotations:
            return
        remaining = []
        for anim in self.active_cam_rotations:
            anim["frame"] += 1
            t = min(1.0, anim["frame"] / anim["duration"])
            te = _ease(anim["easing"], t)
            self.cam_rotation = anim["start"] + (anim["end"] - anim["start"]) * te
            if anim["frame"] < anim["duration"]:
                remaining.append(anim)
        self.active_cam_rotations = remaining

    def _apply_cam_edge_trigger(self, trig):
        if not trig.get("state", True):
            self.cam_edge = None
            return
        self.cam_edge = (
            float(trig.get("min_x", -100000)), float(trig.get("max_x", 100000)),
            float(trig.get("min_y", -100000)), float(trig.get("max_y", 100000)),
        )

    def _apply_cam_guide_trigger(self, trig):
        if trig.get("state", True):
            self.cam_guide_ease = max(0.001, min(1.0,
                                      float(trig.get("smoothing", 0.5))))
        else:
            self.cam_guide_ease = None

    # ---- screen effects (Checkpoint 6, best-effort subset) ------------------
    def _start_effect_trigger(self, trig, name):
        duration = max(1, int(round(max(0.0, float(trig.get("duration", 1.0)))
                                    * PHYSICS_TPS)))
        state = trig.get("state", True)
        intensity = max(0.0, min(1.0, float(trig.get("intensity", 1.0))))
        target = intensity if state else 0.0
        easing = trig.get("easing", "linear")
        existing = self.active_effect_anims.get(name)
        start = existing["cur"] if existing else 0.0
        entry = {"start": start, "cur": start, "target": target, "frame": 0,
                 "duration": duration, "easing": easing}
        if name == "hue":
            entry["degrees"] = float(trig.get("hue_shift", 60.0))
        elif name == "pixelate":
            entry["pixel_size"] = max(2, int(trig.get("pixel_size", 8)))
        self.active_effect_anims[name] = entry

    def _step_screen_effects(self):
        for anim in self.active_effect_anims.values():
            if anim["frame"] < anim["duration"]:
                anim["frame"] += 1
                t = min(1.0, anim["frame"] / anim["duration"])
                te = _ease(anim.get("easing", "linear"), t)
                anim["cur"] = anim["start"] + (anim["target"] - anim["start"]) * te

    # ---- logic family: Spawn / Toggle / Stop / Sequence (Checkpoint 5) -----
    def _trigger_active(self, o):
        """False while every group this trigger belongs to is disabled by
        a Toggle Trigger. A trigger with no groups is never disableable."""
        if not self._trigger_disabled:
            return True
        return not (self._trigger_disabled & set(get_groups(o)))

    def _start_spawn_trigger(self, trig):
        delay = max(0.0, float(trig.get("delay", 0.0)))
        frames = int(round(delay * PHYSICS_TPS))
        group = trig.get("target_group")
        if not group:
            return
        self.pending_spawns.append({
            "due_frame": self.frame + frames, "group": group,
        })

    def _start_sequence_trigger(self, trig):
        step_delay = max(0.0, float(trig.get("step_delay", 0.5)))
        step_frames = max(1, int(round(step_delay * PHYSICS_TPS)))
        groups = [trig.get(k) for k in ("target_group", "target_group2",
                                        "target_group3", "target_group4")]
        step = 0
        for group in groups:
            if not group:
                continue
            self.pending_spawns.append({
                "due_frame": self.frame + step_frames * step, "group": group,
            })
            step += 1

    def _step_pending_spawns(self):
        if not self.pending_spawns:
            return
        remaining = []
        for spawn in self.pending_spawns:
            if self.frame >= spawn["due_frame"]:
                self._fire_group(spawn["group"])
            else:
                remaining.append(spawn)
        self.pending_spawns = remaining

    def _fire_group(self, group):
        """Run every trigger in ``group`` immediately -- shared by Spawn/
        Sequence's delayed dispatch and the Checkpoint 7 item/counter
        family (Count, Item Comp, Time Event), which all "fire a target
        group" as their effect rather than animating an object."""
        if not group:
            return
        for o in self._by_group.get(group, ()):
            if o.get("t") in TRIGGER_TYPES and self._trigger_active(o):
                self._execute_trigger_effect(o)

    def _apply_toggle_trigger(self, trig):
        group = trig.get("target_group")
        if not group:
            return
        if trig.get("state", True):
            self._trigger_disabled.discard(group)
        else:
            self._trigger_disabled.add(group)

    def _apply_stop_trigger(self, trig):
        group = trig.get("target_group")
        if not group:
            return
        members = set(id(o) for o in self._by_group.get(group, ()))
        if not members:
            return
        self.move_animations = [a for a in self.move_animations
                                if id(a["obj"]) not in members]
        self.active_rotations = [
            r for r in self.active_rotations
            if not any(id(o) in members for o in r["targets"])]
        self.active_scales = [a for a in self.active_scales
                              if id(a["obj"]) not in members]
        self.active_alphas = [a for a in self.active_alphas
                              if id(a["obj"]) not in members]

    # ---- Checkpoint 7: item / counter / timer family ------------------

    @staticmethod
    def _compare(lhs, op, rhs):
        if op == ">=":
            return lhs >= rhs
        if op == "<=":
            return lhs <= rhs
        if op == "==":
            return lhs == rhs
        if op == "!=":
            return lhs != rhs
        if op == ">":
            return lhs > rhs
        if op == "<":
            return lhs < rhs
        return False

    def _count_condition(self, o):
        """Item id vs. Value/comparator, per the object's own fields."""
        item_id = int(o.get("item_id", 0))
        lhs = self.items.get(item_id, 0.0)
        try:
            rhs = float(o.get("value", 0.0))
        except (TypeError, ValueError):
            rhs = 0.0
        return self._compare(lhs, o.get("comparator", ">="), rhs)

    def _apply_item_edit_trigger(self, o):
        item_id = int(o.get("item_id", 0))
        cur = self.items.get(item_id, 0.0)
        op_item = int(o.get("operand_item_id", 0))
        if op_item:
            operand = self.items.get(op_item, 0.0)
        else:
            try:
                operand = float(o.get("operand", 1.0))
            except (TypeError, ValueError):
                operand = 1.0
        op = o.get("operation", "add")
        if op == "add":
            cur = cur + operand
        elif op == "subtract":
            cur = cur - operand
        elif op == "multiply":
            cur = cur * operand
        elif op == "divide":
            cur = cur / operand if operand else cur
        elif op == "set":
            cur = operand
        self.items[item_id] = cur

    def _apply_item_comp_trigger(self, o):
        item_id = int(o.get("item_id", 0))
        lhs = self.items.get(item_id, 0.0)
        cmp_item = int(o.get("compare_item_id", 0))
        if cmp_item:
            rhs = self.items.get(cmp_item, 0.0)
        else:
            try:
                rhs = float(o.get("value", 0.0))
            except (TypeError, ValueError):
                rhs = 0.0
        if self._compare(lhs, o.get("comparator", ">="), rhs):
            self._fire_group(o.get("target_group"))

    def _apply_item_pers_trigger(self, o):
        item_id = int(o.get("item_id", 0))
        self.items_pers[item_id] = self.items.get(item_id, 0.0)

    def _apply_time_trigger(self, o):
        timer_id = int(o.get("timer_id", 0))
        action = o.get("action", "start")
        if action == "start":
            self.timers_running.add(timer_id)
        elif action == "stop":
            self.timers_running.discard(timer_id)
        elif action == "reset":
            self.timers[timer_id] = 0.0

    def _step_timers(self):
        if not self.timers_running:
            return
        dt = 1.0 / PHYSICS_TPS
        for timer_id in self.timers_running:
            self.timers[timer_id] = self.timers.get(timer_id, 0.0) + dt

    def _step_count_watchers(self):
        """Count / Time Event triggers watch continuously rather than only
        on touch/spawn -- edge-triggered per object (``_count_armed``) so
        each fires once per false->true transition, not once per tick
        while the condition holds. Reset() clears ``_count_armed`` on
        every object so a fresh attempt re-arms all watchers."""
        for o in self._count_watchers:
            if not self._trigger_active(o):
                continue
            if o["t"] == T_COUNT_TRIGGER:
                cond = self._count_condition(o)
            else:  # T_TIME_EVENT_TRIGGER
                timer_id = int(o.get("timer_id", 0))
                try:
                    threshold = float(o.get("threshold", 0.0))
                except (TypeError, ValueError):
                    threshold = 0.0
                cond = self.timers.get(timer_id, 0.0) >= threshold
            armed = o.get("_count_armed", False)
            if cond and not armed:
                self._fire_group(o.get("target_group"))
                o["_count_armed"] = True
            elif not cond and armed:
                o["_count_armed"] = False

    def _execute_trigger_effect(self, o):
        """Run one trigger's effect immediately. Shared by touch-activation
        (player/core.py) and by Spawn/Sequence dispatch above, so a
        spawned trigger behaves identically to a touched one."""
        t = o.get("t")
        if t == T_CAMERA_TRIGGER:
            mode = o.get("cam_mode", "pan")
            if mode == "static":
                self.camera_locked = True
                # Checkpoint 6: an explicit target_group makes Static
                # track that group's centre every tick (real GD's "lock
                # camera onto a specific object") instead of just
                # freezing wherever the camera already was.
                grp = o.get("target_group")
                self.static_cam_group = grp if grp else None
            elif mode == "follow":
                self.camera_locked = False
                self.static_cam_group = None
                self.free_cam_mode = True
            else:
                self.camera_locked = False
                self.static_cam_group = None
                row = o.get("cy", o["y"])
                self.target_cam_y = row * CELL + CELL / 2 - HEIGHT / 2
                try:
                    self.cam_pan_duration = max(0.0, float(o.get("duration", 1.0)))
                except (TypeError, ValueError):
                    self.cam_pan_duration = 1.0
        elif t == T_BG_TRIGGER:
            self.bg_preset = int(o.get("bg", 0))
        elif t == T_MOVE_TRIGGER:
            self._start_move_trigger(o)
        elif t == T_COLOR_TRIGGER:
            self.color_index = int(o.get("channel", o.get("col_idx", 0)))
            self.player_color = channel_color(self.channels,
                                              self.color_index)[:3]
        elif t == T_PULSE_TRIGGER:
            self._start_pulse_trigger(o)
        elif t == T_ROTATE_TRIGGER:
            self._start_rotate_trigger(o)
        elif t == T_FOLLOW_TRIGGER:
            if not o.get("always_on"):
                self._start_follow_trigger(o)
        elif t == T_TIME_WARP:
            try:
                self.time_warp = float(o.get("factor", 1.0))
            except (TypeError, ValueError):
                self.time_warp = 1.0
        elif t == T_BLACKOUT_TRIGGER:
            self._start_blackout_trigger(o)
        elif t == T_SCALE_TRIGGER:
            self._start_scale_trigger(o)
        elif t == T_ALPHA_TRIGGER:
            self._start_alpha_trigger(o)
        elif t == T_SPAWN_TRIGGER:
            self._start_spawn_trigger(o)
        elif t == T_TOGGLE_TRIGGER:
            self._apply_toggle_trigger(o)
        elif t == T_STOP_TRIGGER:
            self._apply_stop_trigger(o)
        elif t == T_SEQUENCE_TRIGGER:
            self._start_sequence_trigger(o)
        elif t == T_ZOOM_TRIGGER:
            self._start_zoom_trigger(o)
        elif t == T_CAM_OFFSET_TRIGGER:
            self._start_cam_offset_trigger(o)
        elif t == T_CAM_ROTATE_TRIGGER:
            self._start_cam_rotate_trigger(o)
        elif t == T_CAM_EDGE_TRIGGER:
            self._apply_cam_edge_trigger(o)
        elif t == T_CAM_GUIDE_TRIGGER:
            self._apply_cam_guide_trigger(o)
        elif t == T_GRAYSCALE_TRIGGER:
            self._start_effect_trigger(o, "grayscale")
        elif t == T_SEPIA_TRIGGER:
            self._start_effect_trigger(o, "sepia")
        elif t == T_INVERT_TRIGGER:
            self._start_effect_trigger(o, "invert")
        elif t == T_HUE_TRIGGER:
            self._start_effect_trigger(o, "hue")
        elif t == T_PIXELATE_TRIGGER:
            self._start_effect_trigger(o, "pixelate")
        elif t in (T_COUNT_TRIGGER, T_INSTANT_COUNT_TRIGGER):
            # A direct touch/spawn is an immediate check-and-fire,
            # independent of Count Trigger's own continuous watcher
            # (_step_count_watchers) -- so touching one still works even
            # if the item value never changes again after this frame.
            if self._count_condition(o):
                self._fire_group(o.get("target_group"))
        elif t == T_ITEM_EDIT_TRIGGER:
            self._apply_item_edit_trigger(o)
        elif t == T_ITEM_COMP_TRIGGER:
            self._apply_item_comp_trigger(o)
        elif t == T_ITEM_PERS_TRIGGER:
            self._apply_item_pers_trigger(o)
        elif t == T_TIME_TRIGGER:
            self._apply_time_trigger(o)
        elif t == T_TIME_EVENT_TRIGGER:
            timer_id = int(o.get("timer_id", 0))
            try:
                threshold = float(o.get("threshold", 0.0))
            except (TypeError, ValueError):
                threshold = 0.0
            if self.timers.get(timer_id, 0.0) >= threshold:
                self._fire_group(o.get("target_group"))
        elif t == T_KEYFRAME_TRIGGER:
            self._start_keyframe_trigger(o)

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
        # `duration` is authored in seconds; PHYSICS_TPS, not a hardcoded
        # 60, keeps this correct regardless of the physics tick rate.
        frames = max(1, int(float(trig.get("duration", 2.0)) * PHYSICS_TPS))
        self.active_pulses.append({
            "start_frame": self.frame,
            "end_frame": self.frame + frames,
            "bpm": int(trig.get("bpm", 128)),
            "channel": int(trig.get("channel", -1)),
        })

    def pulse_intensity(self):
        """[0, 1] flash intensity from active pulse triggers."""
        if not self.active_pulses:
            return 0.0
        total = 0.0
        for p in self.active_pulses:
            # frames_per_beat = ticks/sec * sec/min / beats-per-min.
            frames_per_beat = (PHYSICS_TPS * 60.0) / max(1, p["bpm"])
            phase = ((self.frame - p["start_frame"]) / frames_per_beat) * math.tau
            total += math.sin(phase) ** 2
        return min(1.0, total)

    def pulse_color(self):
        """RGB tint for the current pulse flash. Most-recently-started
        active pulse wins when several overlap; channel -1 (the default)
        keeps the classic near-white flash."""
        if not self.active_pulses:
            return (255, 240, 255)
        channel = self.active_pulses[-1]["channel"]
        if channel < 0:
            return (255, 240, 255)
        return channel_color(self.channels, channel)[:3]

    # ---- blackout ------------------------------------------------------
    def _start_blackout_trigger(self, trig):
        """Fade the full-screen blackout overlay toward on (1.0) or off
        (0.0) over ``duration`` seconds, smoothstep-eased."""
        target = 1.0 if trig.get("state", True) else 0.0
        duration = max(0.0, float(trig.get("duration", 1.0)))
        self.blackout_start = self.blackout_value
        self.blackout_target = target
        self.blackout_start_frame = self.frame
        # `duration` is authored in seconds; PHYSICS_TPS, not a hardcoded
        # 60, keeps this correct regardless of the physics tick rate.
        self.blackout_frames = max(1, int(round(duration * PHYSICS_TPS)))

    def _step_blackout(self):
        if self.blackout_value == self.blackout_target:
            return
        t = min(1.0, (self.frame - self.blackout_start_frame) / self.blackout_frames)
        te = t * t * (3.0 - 2.0 * t)  # smoothstep
        self.blackout_value = (self.blackout_start
                               + (self.blackout_target - self.blackout_start) * te)
