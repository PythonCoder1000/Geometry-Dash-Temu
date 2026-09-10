"""Level triggers that animate objects: move, rotate, follow, pulse, plus
the Checkpoint 5 group-targeted / logic family (Spawn, Toggle, Stop,
Sequence, Scale, Alpha)."""

import math
import random

from ..constants import (
    UNITS_PER_BLOCK, CAMERA_HEIGHT_UNITS, DEFAULT_MOVE_CURVE, PHYSICS_TPS,
    T_CAMERA_TRIGGER, T_BG_TRIGGER, T_MOVE_TRIGGER, T_COLOR_TRIGGER,
    T_PULSE_TRIGGER, T_ROTATE_TRIGGER, T_FOLLOW_TRIGGER, T_TIME_WARP,
    T_BLACKOUT_TRIGGER, T_SPAWN_TRIGGER, T_TOGGLE_TRIGGER, T_STOP_TRIGGER,
    T_SEQUENCE_TRIGGER, T_REPEAT_TRIGGER, T_SCALE_TRIGGER, T_ALPHA_TRIGGER,
    T_SWAP_TRIGGER,
    TRIGGER_TYPES,
    T_ZOOM_TRIGGER, T_CAM_OFFSET_TRIGGER, T_CAM_ROTATE_TRIGGER,
    T_CAM_EDGE_TRIGGER, T_CAM_GUIDE_TRIGGER,
    T_GRAYSCALE_TRIGGER, T_SEPIA_TRIGGER, T_INVERT_TRIGGER, T_HUE_TRIGGER,
    T_PIXELATE_TRIGGER,
    T_SHADER_TRIGGER, T_CHROMATIC_TRIGGER, T_RADIAL_BLUR_TRIGGER,
    T_MOTION_BLUR_TRIGGER, T_BULGE_TRIGGER, T_PINCH_TRIGGER,
    T_SPLIT_SCREEN_TRIGGER,
    RADIAL_BLUR_MAX_SAMPLES, MOTION_BLUR_MAX_FRAMES, CHROMATIC_MAX_OFFSET_PX,
    T_COUNT_TRIGGER, T_INSTANT_COUNT_TRIGGER, T_ITEM_EDIT_TRIGGER,
    T_ITEM_COMP_TRIGGER, T_ITEM_PERS_TRIGGER, T_TIME_TRIGGER,
    T_TIME_EVENT_TRIGGER, T_KEYFRAME_TRIGGER,
    T_AREA_MOVE_TRIGGER, T_AREA_ROTATE_TRIGGER, T_AREA_SCALE_TRIGGER,
    T_AREA_FADE_TRIGGER, T_AREA_TINT_TRIGGER, T_AREA_STOP_TRIGGER,
    T_EDIT_AREA_MOVE_TRIGGER, T_EDIT_AREA_ROTATE_TRIGGER,
    T_EDIT_AREA_SCALE_TRIGGER, T_EDIT_AREA_FADE_TRIGGER,
    T_EDIT_AREA_TINT_TRIGGER,
    T_RANDOM_TRIGGER, T_ADVANCED_RANDOM_TRIGGER,
    T_SONG_TRIGGER, T_SFX_TRIGGER, T_EDIT_SONG_TRIGGER, T_EDIT_SFX_TRIGGER,
    SONG_CHANNEL_MAX,
    T_GAMEPLAY_ROTATION_TRIGGER, T_REVERSE_TRIGGER, T_TELEPORT_TRIGGER,
    T_CHECKPOINT_TRIGGER,
    T_GROUND_TRIGGER, T_MG_TRIGGER, T_BG_SPEED_TRIGGER, T_MG_SPEED_TRIGGER,
    T_UI_TRIGGER, T_EVENT_TRIGGER, T_END_TRIGGER,
    BG_SPEED_DEFAULT_X, BG_SPEED_DEFAULT_Y, MG_SPEED_DEFAULT_X,
    MG_SPEED_DEFAULT_Y, ENV_SPEED_MIN, ENV_SPEED_MAX,
    UI_TEXT_CHOICES, LEVEL_EVENTS, EVENT_WIN,
)
from .. import music, sfx
from ..channels import channel_color
from ..levels import get_groups
from ..geometry import obj_scale
from ..objects import advanced_random_weighted_list, parse_weighted_list
from .collision import invalidate_pose_caches
from .trigger_registry import (
    TRIGGER_HANDLERS, TRIGGER_FAMILY_SPAWN, TRIGGER_DRAIN_MAX_PASSES,
)


# Checkpoint 6: the Gameplay Rotation trigger's gravity_dir vocabulary,
# mapped to the same signs the T_GRAV_UP / T_GRAV_DOWN portals use in
# core.py's _handle_interactions (up = -1, down = +1). "none" is absent on
# purpose -- a missing entry is what makes the field a no-op.
_GRAVITY_DIR_SIGN = {"up": -1, "down": 1}


def _env_speed(raw, fallback):
    """One parallax-speed field, clamped to the authoring bounds.

    Checkpoint 7. Unparseable falls back to the report's documented
    default for that layer, which is also the renderer's identity point
    (see TriggerMixin.bg_scroll_scale) -- so a malformed value shows the
    stock parallax rather than freezing the layer.
    """
    try:
        return max(ENV_SPEED_MIN, min(ENV_SPEED_MAX, float(raw)))
    except (TypeError, ValueError):
        return fallback


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


def _clamped_int(lo, hi):
    return lambda v: max(lo, min(hi, int(v)))


def _clamped_float(lo, hi):
    return lambda v: max(lo, min(hi, float(v)))


def _one_of(*allowed):
    return lambda v: v if v in allowed else allowed[0]


# Per-effect knobs beyond the shared state/intensity/duration/easing
# tween, as ``{effect name: ((object field key, default, coercer), ...)}``.
# The field key doubles as the key inside the active_effect_anims entry,
# so play_render's per-effect branch reads exactly the name the editor
# shows -- there is no second naming layer to keep in sync.
#
# The coercers are the runtime floor under objects.py's Field ranges: a
# level file edited by hand (or written by an older schema) can carry an
# out-of-range value, and these effects turn straight into per-frame
# full-screen work, so the caps in constants.py are enforced here rather
# than trusted from disk.
SCREEN_EFFECT_PARAMS = {
    "hue": (("hue_shift", 60.0, _clamped_float(-360.0, 360.0)),),
    "pixelate": (("pixel_size", 8, _clamped_int(2, 256)),),
    "chromatic": (("offset_px", 6, _clamped_int(1, CHROMATIC_MAX_OFFSET_PX)),),
    "radial_blur": (
        ("strength", 0.5, _clamped_float(0.0, 1.0)),
        ("sample_count", 4, _clamped_int(2, RADIAL_BLUR_MAX_SAMPLES)),
    ),
    "motion_blur": (
        ("strength", 0.5, _clamped_float(0.0, 1.0)),
        ("frame_count", 3, _clamped_int(2, MOTION_BLUR_MAX_FRAMES)),
    ),
    "bulge": (
        ("strength", 0.5, _clamped_float(0.0, 1.0)),
        ("radius", 240.0, _clamped_float(1.0, 100000.0)),
        ("center_x", 0, int),
        ("center_y", 0, int),
    ),
    "pinch": (
        ("strength", 0.5, _clamped_float(0.0, 1.0)),
        ("radius", 240.0, _clamped_float(1.0, 100000.0)),
        ("center_x", 0, int),
        ("center_y", 0, int),
    ),
    "split_screen": (("axis", "vertical", _one_of("vertical", "horizontal")),),
}


# ---------------------------------------------------------------------------
# Area effects (Checkpoint 2 -- deep-research-report.md, "Area and keyframe
# system")
# ---------------------------------------------------------------------------
# ``{param: (cast, default)}`` per area-effect kind. One table read by both
# the Area-* handlers (which build a whole effect entry, defaults included)
# and the Edit Area-* handlers (which patch only the keys their own trigger
# actually carries), so a live effect can never end up holding a value the
# start path would have coerced differently.
_AREA_COMMON_PARAMS = {
    "target_group": (int, 0),
    "center_group": (int, 0),
    "length": (float, 3.0),
    "length_variance": (float, 0.0),
    "offset": (float, 0.0),
    "y_offset": (float, 0.0),
    "priority": (int, 0),
}
_AREA_KIND_PARAMS = {
    # Move/Rotate are *rates* (grid squares and degrees per second): an
    # area effect has no end frame to tween toward, so it accumulates for
    # as long as an object stays inside it. Scale/Fade/Tint are *targets*
    # blended by the falloff, which makes them self-restoring -- an object
    # that leaves the radius blends back to unscaled/opaque/untinted on
    # its own, where a rate would just stop accumulating.
    "move": {"dx": (float, 0.0), "dy": (float, 0.0)},
    "rotate": {"degrees": (float, 0.0)},
    "scale": {"sx": (float, 1.0), "sy": (float, 1.0)},
    "fade": {"target_alpha": (float, 1.0)},
    "tint": {"target_channel": (int, 0)},
}


def _area_effect_id(trig):
    """The Effect id (GD key 225) a trigger names, or ``None`` when it is
    unreadable -- every handler in the family keys off this one value."""
    try:
        return int(trig.get("effect_id", 0) or 0)
    except (TypeError, ValueError):
        return None


def _coerced_params(trig, tables, present_only):
    """Coerced parameters read off a trigger object, per ``{key: (cast,
    default)}`` tables.

    ``present_only`` distinguishes the two kinds of caller a start/edit
    trigger family has: the trigger that STARTS an effect wants a
    complete parameter set (missing keys fall back to their defaults),
    while the Edit variant must only patch what it actually carries.
    Shared by the Area family (Checkpoint 2) and the audio family
    (Checkpoint 5), which have exactly this same start/edit split.
    """
    params = {}
    for table in tables:
        for key, (cast, default) in table.items():
            if present_only and key not in trig:
                continue
            raw = trig.get(key, default)
            try:
                params[key] = cast(default if raw is None else raw)
            except (TypeError, ValueError):
                params[key] = default
    return params


def _area_params(trig, kind, present_only):
    """Coerced area parameters read off a trigger object."""
    return _coerced_params(
        trig, (_AREA_COMMON_PARAMS, _AREA_KIND_PARAMS[kind]), present_only)


# ---------------------------------------------------------------------------
# Audio (Checkpoint 5 -- deep-research-report.md, "Audio, timers, and
# arithmetic")
# ---------------------------------------------------------------------------
# The live state a Song / SFX trigger records, in the same
# ``{param: (cast, default)}`` form the area tables use, and read by both
# halves of the family for the same reason: a Song/SFX trigger builds a
# whole entry, an Edit Song/Edit SFX patches only the keys its own object
# carries, so a live entry can never hold a value the start path would
# have coerced differently.
_SONG_PARAMS = {
    "song": (int, 0),
    "volume": (float, 1.0),
    "speed": (float, 1.0),
    "start": (float, 0.0),
    "end": (float, 0.0),
    "fade_in": (float, 0.0),
    "fade_out": (float, 0.0),
    "loop": (bool, False),
}
_SFX_PARAMS = {
    # Same default as the spec's choice Field, read from the same list,
    # so a trigger dict built without a sound still names a real one.
    "sfx": (str, sfx.SOUND_NAMES[0] if sfx.SOUND_NAMES else ""),
    "volume": (float, 1.0),
    "pitch": (float, 0.0),
    "reverb": (float, 0.0),
    "loop": (bool, False),
}


def _song_channel(trig):
    """The song channel (GD key 432) a trigger addresses, clamped to the
    range the editor can author."""
    try:
        channel = int(trig.get("channel", 0) or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, min(SONG_CHANNEL_MAX, channel))


def _sfx_unique_id(trig):
    """The SFX instance id (GD key 416) a trigger addresses. 0 means
    "anonymous" -- untracked, and unreachable by Edit SFX."""
    try:
        return int(trig.get("unique_id", 0) or 0)
    except (TypeError, ValueError):
        return 0


class TriggerMixin:
    __slots__ = ()

    # Whether this player's audio triggers (Checkpoint 5) actually reach
    # the mixer. Deliberately a CLASS attribute and not a __slots__ field:
    # it is a property of the kind of player, never of a moment in a run,
    # so there is nothing for reset()/snapshot()/restore() to carry.
    # SimPlayer (bots/sim.py) turns it off -- a bot search replays a level
    # thousands of times per solve, and every replay restarting the music
    # or firing a sound would be both deafening and slow. The live entries
    # in active_songs/active_sfx are still recorded either way, so the
    # simulation a bot sees stays identical to real play.
    audio_output_enabled = True

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

    # ---- area effects (Checkpoint 2) ----------------------------------------
    def _start_area_effect(self, trig, kind):
        """Register the live area effect this trigger's Effect id names.

        An Effect id maps to exactly one live effect, because that id is
        how Edit Area and Area Stop later name what they act on. Starting
        a second effect under an id that is already live therefore
        replaces it (last-fired-wins) rather than stacking -- the report
        documents the id's role but no rule for two effects claiming one
        id, so this is an engine choice.
        """
        effect_id = _area_effect_id(trig)
        if effect_id is None:
            return
        entry = {
            "kind": kind, "effect_id": effect_id,
            # Fallback center for an effect whose center group is empty
            # or unset: the trigger's own cell.
            "home_x": float(trig.get("x", 0)), "home_y": float(trig.get("y", 0)),
            # Per-target pre-effect scale/alpha, filled lazily by
            # _step_area_effects so a target that leaves the radius
            # blends back to exactly what it looked like before.
            "base_pose": {},
        }
        entry.update(_area_params(trig, kind, False))
        self.active_areas[effect_id] = entry

    def _start_area_move_trigger(self, trig):
        self._start_area_effect(trig, "move")

    def _start_area_rotate_trigger(self, trig):
        self._start_area_effect(trig, "rotate")

    def _start_area_scale_trigger(self, trig):
        self._start_area_effect(trig, "scale")

    def _start_area_fade_trigger(self, trig):
        self._start_area_effect(trig, "fade")

    def _start_area_tint_trigger(self, trig):
        self._start_area_effect(trig, "tint")

    def _apply_edit_area_effect(self, trig, kind):
        """Patch the live effect this trigger's Effect id names.

        Per the report, an Edit Area trigger MODIFIES state identified by
        Effect id and never creates it: with no live effect under that id
        (or one of a different kind) this does nothing at all. Only the
        parameters the trigger itself carries are patched, so the effect
        keeps everything else it was started with.
        """
        effect_id = _area_effect_id(trig)
        entry = self.active_areas.get(effect_id) if effect_id is not None else None
        if entry is None or entry["kind"] != kind:
            return
        entry.update(_area_params(trig, kind, True))

    def _apply_edit_area_move_trigger(self, trig):
        self._apply_edit_area_effect(trig, "move")

    def _apply_edit_area_rotate_trigger(self, trig):
        self._apply_edit_area_effect(trig, "rotate")

    def _apply_edit_area_scale_trigger(self, trig):
        self._apply_edit_area_effect(trig, "scale")

    def _apply_edit_area_fade_trigger(self, trig):
        self._apply_edit_area_effect(trig, "fade")

    def _apply_edit_area_tint_trigger(self, trig):
        self._apply_edit_area_effect(trig, "tint")

    def _apply_area_stop_trigger(self, trig):
        """End the live effect with this Effect id (report: "Stop Area
        effect by EffectID"). Objects keep whatever the effect last wrote
        -- they simply stop being advanced, exactly like a Stop Trigger
        freezing a Move/Rotate animation where it stands."""
        effect_id = _area_effect_id(trig)
        if effect_id is not None:
            self.active_areas.pop(effect_id, None)

    def _area_center(self, entry):
        """(x, y) in grid cells the effect's falloff measures from: the
        centroid of its center group's members, shifted by the authored
        offset. An effect whose center group is empty or unset measures
        from the trigger's own cell instead."""
        members = self._by_group.get(entry["center_group"], ())
        if members:
            n = float(len(members))
            cx = sum(float(o.get("_fx", o["x"])) for o in members) / n
            cy = sum(float(o.get("_fy", o["y"])) for o in members) / n
        else:
            cx, cy = entry["home_x"], entry["home_y"]
        return cx + entry["offset"], cy + entry["y_offset"]

    def _step_area_effects(self):
        """Advance every live area effect by one tick.

        Per effect: resolve its center (see _area_center), then transform
        every target-group member by a strength that is 1.0 within
        ``length`` grid squares of that center and falls linearly to 0.0
        over the next ``length_variance`` squares (so variance 0 is a hard
        edge at ``length``).

        Engine-chosen, NOT report-sourced -- the report fixes the Length
        unit and the property keys but neither of these:
        * the falloff is linear (best-effort: no curve is documented);
        * two effects touching one object compose last-processed-wins,
          i.e. by ``active_areas`` insertion order. Deliberately unlike
          Force Block (Checkpoint 3), whose stacking law the report DOES
          state exactly -- the two must not be conflated. ``priority``
          (key 341) is stored but not consumed for the same reason.
        """
        if not self.active_areas:
            return
        for entry in self.active_areas.values():
            targets = self._resolve_targets(entry)
            if not targets:
                continue
            cx, cy = self._area_center(entry)
            inner = max(0.0, entry["length"])
            outer = inner + max(0.0, entry["length_variance"])
            kind = entry["kind"]
            base_pose = entry["base_pose"]
            for o in targets:
                ox = float(o.get("_fx", o["x"]))
                oy = float(o.get("_fy", o["y"]))
                dist = math.hypot(ox - cx, oy - cy)
                if dist <= inner:
                    weight = 1.0
                elif dist >= outer:
                    weight = 0.0
                else:
                    weight = 1.0 - (dist - inner) / (outer - inner)
                if kind == "move":
                    # A rate, integrated per tick: an object deep inside
                    # the area drifts at the authored grid squares/second
                    # for as long as it stays there.
                    if weight <= 0.0:
                        continue
                    step = weight / PHYSICS_TPS
                    dx = entry["dx"] * step
                    dy = entry["dy"] * step
                    if dx or dy:
                        self._set_object_pos(o, ox + dx, oy + dy)
                elif kind == "rotate":
                    if weight <= 0.0:
                        continue
                    o["r"] = (float(o.get("r", 0.0))
                              + entry["degrees"] * weight / PHYSICS_TPS) % 360.0
                    invalidate_pose_caches(o)
                elif kind == "scale":
                    key = self._oid_index[id(o)]
                    base = base_pose.get(key)
                    if base is None:
                        base = obj_scale(o)
                        base_pose[key] = base
                    sx = base[0] + (entry["sx"] - base[0]) * weight
                    sy = base[1] + (entry["sy"] - base[1]) * weight
                    # Skipping the no-change case keeps the pose caches
                    # of everything sitting outside the radius warm.
                    if abs(o.get("sx", base[0]) - sx) > 1e-9 \
                            or abs(o.get("sy", base[1]) - sy) > 1e-9:
                        o["sx"] = sx
                        o["sy"] = sy
                        invalidate_pose_caches(o)
                elif kind == "fade":
                    key = self._oid_index[id(o)]
                    base = base_pose.get(key)
                    if base is None:
                        base = float(o.get("_alpha", 1.0))
                        base_pose[key] = base
                    o["_alpha"] = base + (entry["target_alpha"] - base) * weight
                else:  # tint
                    if weight <= 0.0:
                        o.pop("_tint", None)
                    else:
                        col = channel_color(self.channels,
                                            entry["target_channel"])
                        # Stored as the multiply colour the renderer
                        # applies directly (255 = leave this channel
                        # alone), so nothing downstream has to know about
                        # colour channels or falloff weights.
                        o["_tint"] = tuple(
                            int(round(255.0 - (255.0 - c) * weight))
                            for c in col[:3])

    # ---- audio family (Checkpoint 5) ----------------------------------------
    # Song/SFX start playback; Edit Song/Edit SFX patch what is already
    # playing, addressed by song channel and by unique id -- the Area
    # family's start/edit/id relationship exactly, and the reason both
    # halves share _coerced_params above.
    #
    # Engine capabilities these handlers are built on, so the no-ops below
    # are unsurprising: music.py drives ONE pygame.mixer.music stream
    # (load/play with loop, start-seek and fade-in, fadeout, stop, plus
    # the level-volume scaling added for this family so a trigger never
    # writes the user's saved volume preference); sfx.py plays cached
    # procedurally-generated Sounds and hands back the mixer Channel.
    # Neither has a playback-rate, seek-to-end, pitch or reverb primitive,
    # so `speed`/`end`/`pitch`/`reverb` are recorded in the live entry
    # (they round-trip, and an Edit trigger can still change them) but
    # deliberately reach no mixer call. Building any of them from scratch
    # -- resampling audio per frame in Python -- is out of scope and would
    # not run at frame rate.

    def _play_song_entry(self, entry):
        """Start ``entry``'s track at its authored volume/loop/seek/fade.

        Volume is set BEFORE play so a fade-in ramps toward the right
        level: pygame's fade is a volume ramp, and setting the volume
        part-way through one would cancel it.
        """
        music.set_level_volume(entry["volume"])
        music.play_track(entry["song"],
                         loops=-1 if entry["loop"] else 0,
                         start_sec=entry["start"],
                         fade_ms=int(entry["fade_in"] * 1000))

    def _apply_song_trigger(self, trig):
        """Song Trigger (real GD id 1934) -- play a bundled track.

        ``song`` indexes music.get_tracks() (see the spec in objects.py
        for why an index and not a filename). ``channel`` is an address,
        not a mixing slot: this engine has one music stream, so the most
        recently started channel is the one that is audible, while every
        channel keeps its own live entry for an Edit Song to patch.
        Starting a channel that already has a song replaces its entry --
        the Area family's last-fired-wins rule for a reused id.
        """
        channel = _song_channel(trig)
        entry = _coerced_params(trig, (_SONG_PARAMS,), False)
        self.active_songs[channel] = entry
        self.active_song_channel = channel
        if self.audio_output_enabled:
            self._play_song_entry(entry)

    def _apply_edit_song_trigger(self, trig):
        """Edit Song Trigger (3605) -- patch the song on a channel.

        Mirrors _apply_edit_area_effect: the live state is found by id
        (here the song channel), a channel with nothing playing is a
        complete no-op, and only the parameters the trigger itself
        carries are patched. Patched values are ABSOLUTE, not deltas --
        the same choice Edit Area makes, and the one that keeps re-firing
        a trigger idempotent.

        ``stop`` ends playback, fading out over the *song's own* authored
        Fade out (0 = stop immediately), which is what gives key 411 a
        real effect in an engine with no scheduled song end.
        """
        channel = _song_channel(trig)
        entry = self.active_songs.get(channel)
        if entry is None:
            return
        entry.update(_coerced_params(trig, (_SONG_PARAMS,), True))
        sounding = channel == self.active_song_channel
        if trig.get("stop"):
            self.active_songs.pop(channel, None)
            if sounding:
                self.active_song_channel = None
                if self.audio_output_enabled:
                    fade_ms = int(entry["fade_out"] * 1000)
                    if fade_ms > 0:
                        music.fadeout(fade_ms)
                    else:
                        music.stop()
            return
        # Only the sounding channel can be re-levelled: patching a
        # silent channel's entry must not change what the player hears.
        if sounding and self.audio_output_enabled:
            music.set_level_volume(entry["volume"])

    def _apply_sfx_trigger(self, trig):
        """SFX Trigger (3602) -- play one of sfx.py's bundled sounds.

        A nonzero ``unique_id`` makes the instance addressable: the mixer
        Channel sfx.play() returns is stored under it so an Edit SFX can
        re-level or stop it, and re-firing that id stops the previous
        instance first (last-fired-wins, as for an Area effect id).

        ``unique_id`` 0 is anonymous -- fire and forget, nothing to
        track, and ``loop`` is refused for it: an untracked looping
        channel could never be stopped by anything, not even a level
        restart, so it would outlive the attempt that started it.
        """
        entry = _coerced_params(trig, (_SFX_PARAMS,), False)
        uid = _sfx_unique_id(trig)
        entry["unique_id"] = uid
        entry["channel"] = None
        if uid:
            previous = self.active_sfx.get(uid)
            if previous is not None:
                sfx.stop_channel(previous.get("channel"))
        loops = -1 if (entry["loop"] and uid) else 0
        if self.audio_output_enabled:
            entry["channel"] = sfx.play(entry["sfx"], entry["volume"], loops)
        if uid:
            self.active_sfx[uid] = entry

    def _apply_edit_sfx_trigger(self, trig):
        """Edit SFX Trigger (3603) -- patch a live sound by unique id.

        Same contract as Edit Song / Edit Area: look the instance up by
        id, do nothing at all when it is absent (or anonymous), patch
        only the fields this trigger carries, absolute values.
        """
        uid = _sfx_unique_id(trig)
        entry = self.active_sfx.get(uid) if uid else None
        if entry is None:
            return
        entry.update(_coerced_params(trig, (_SFX_PARAMS,), True))
        if trig.get("stop"):
            self.active_sfx.pop(uid, None)
            sfx.stop_channel(entry.get("channel"))
            return
        sfx.set_channel_volume(entry.get("channel"), entry["volume"])

    def _stop_trigger_audio(self):
        """Silence and forget everything this player's audio triggers
        started -- called from reset() so a retry never inherits the
        previous attempt's looping sound or song state.

        Music is only stopped when this player actually started a song:
        a level whose audio comes from its own music meta field (or an
        editor preview running over the menu music) must keep playing.
        SFX channels are always stopped, since a looping instance would
        otherwise survive every retry.
        """
        for entry in self.active_sfx.values():
            sfx.stop_channel(entry.get("channel"))
        if self.active_songs and self.audio_output_enabled:
            music.stop()
        self.active_sfx = {}
        self.active_songs = {}
        self.active_song_channel = None

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

    # ---- screen effects (Checkpoint 6 + Checkpoint 4) -----------------------
    def _start_effect_trigger(self, trig, name):
        """Start/retarget one named entry in ``active_effect_anims``.

        Every screen effect -- the five Checkpoint-6 colour remaps and
        the six Checkpoint-4 shader effects -- goes through here. The
        shared part is a tween of ``cur`` toward ``target`` over
        ``duration`` frames; the per-effect knobs are copied verbatim
        from the object into the entry by SCREEN_EFFECT_PARAMS, so
        ``play_render.build_screen_effects`` can hand them to the render
        branch without knowing what any of them mean.
        """
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
        for key, default, coerce in SCREEN_EFFECT_PARAMS.get(name, ()):
            entry[key] = coerce(trig.get(key, default))
        self.active_effect_anims[name] = entry

    def _apply_shader_trigger(self, trig):
        """Base Shader Trigger (2904).

        The report documents exactly two behaviours for it: a Disable All
        switch, and a lowest/highest render-layer range. Only the first
        is implementable here -- this engine draws one flat world pass
        and has no render-layer concept at all, so lowest_layer/
        highest_layer are authored and saved but nothing consumes them
        (see the spec's comment in objects.py; same "stored but inert,
        documented" precedent as the Area family's `priority`).

        Disable All clears the whole animation dict rather than tweening
        each entry to 0 -- "disable" in the report is a switch, not a
        fade, and this is the same shape as _apply_stop_trigger dropping
        animations outright.
        """
        if trig.get("disable_all", False):
            self.active_effect_anims.clear()

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

    def _start_repeat_trigger(self, trig):
        """Fire the target group once every Interval seconds, Count times
        total -- a Spawn Trigger that loops instead of firing once, so a
        mapper doesn't have to stack N Spawn Triggers by hand to run
        something "every 0.5s for 50 cycles"."""
        interval = max(0.05, float(trig.get("interval", 0.5)))
        interval_frames = max(1, int(round(interval * PHYSICS_TPS)))
        count = max(1, int(trig.get("count", 10)))
        group = trig.get("target_group")
        if not group:
            return
        self.pending_repeats.append({
            "due_frame": self.frame + interval_frames, "group": group,
            "interval_frames": interval_frames, "remaining": count,
        })

    def _step_pending_repeats(self):
        if not self.pending_repeats:
            return
        remaining = []
        for rep in self.pending_repeats:
            if self.frame >= rep["due_frame"]:
                self._fire_group(rep["group"])
                rep["remaining"] -= 1
                if rep["remaining"] > 0:
                    rep["due_frame"] += rep["interval_frames"]
                    remaining.append(rep)
            else:
                remaining.append(rep)
        self.pending_repeats = remaining

    # ---- swap ---------------------------------------------------------------
    def _start_swap_trigger(self, trig):
        """Randomly permute the target group's positions once every
        Interval seconds, Count times total -- like Repeat Trigger's
        interval/count loop, but the effect is "shuffle these objects"
        instead of "fire this group". Re-resolves the group fresh at
        every swap (see :meth:`_step_pending_swaps`), mirroring how
        Repeat re-resolves via ``_fire_group`` rather than caching."""
        interval = max(0.05, float(trig.get("interval", 1.0)))
        interval_frames = max(1, int(round(interval * PHYSICS_TPS)))
        count = max(1, int(trig.get("count", 5)))
        group = trig.get("target_group")
        if not group:
            return
        self.pending_swaps.append({
            "due_frame": self.frame + interval_frames, "trig": trig,
            "interval_frames": interval_frames, "remaining": count,
        })

    def _step_pending_swaps(self):
        if not self.pending_swaps:
            return
        remaining = []
        for sw in self.pending_swaps:
            if self.frame >= sw["due_frame"]:
                self._swap_target_positions(sw["trig"])
                sw["remaining"] -= 1
                if sw["remaining"] > 0:
                    sw["due_frame"] += sw["interval_frames"]
                    remaining.append(sw)
            else:
                remaining.append(sw)
        self.pending_swaps = remaining

    def _swap_target_positions(self, trig):
        """One swap event: assign every target a random OTHER target's
        current position. Smooth rides the exact same tween machinery a
        Move Trigger uses (``move_animations`` / ``_step_move_
        animations``) -- for free, that also means a Stop Trigger
        targeting these objects interrupts a still-running smooth swap
        exactly like it would a Move Trigger."""
        targets = self._resolve_targets(trig)
        if len(targets) < 2:
            return
        positions = [(float(t.get("_fx", t["x"])), float(t.get("_fy", t["y"])))
                    for t in targets]
        shuffled = positions[:]
        random.shuffle(shuffled)
        # Retry until the shuffle actually moves something -- a "swap"
        # that silently lands on the identity permutation would look
        # like the trigger did nothing. Guaranteed to terminate (with
        # >= 2 targets a non-identity permutation always exists), and
        # converges in a handful of tries even at low target counts.
        while shuffled == positions:
            random.shuffle(shuffled)
        if trig.get("smooth", False):
            interval_frames = max(1, int(round(
                max(0.05, float(trig.get("interval", 1.0))) * PHYSICS_TPS)))
            duration = max(0.0, float(trig.get("smooth_duration", 0.3)))
            frames = max(1, min(interval_frames,
                                int(round(duration * PHYSICS_TPS))))
            easing = trig.get("easing", "linear")
            area = curve_area(DEFAULT_MOVE_CURVE)
            for target, (sx, sy), (ex, ey) in zip(targets, positions, shuffled):
                self.move_animations.append({
                    "obj": target, "sx": sx, "sy": sy, "ex": ex, "ey": ey,
                    "frame": 0, "duration": frames,
                    "curve": DEFAULT_MOVE_CURVE, "curve_area": area,
                    "easing": easing,
                })
        else:
            for target, (ex, ey) in zip(targets, shuffled):
                self._set_object_pos(target, ex, ey, True)

    def _fire_group(self, group):
        """Run every trigger in ``group`` immediately -- shared by Spawn/
        Sequence's delayed dispatch and the Checkpoint 7 item/counter
        family (Count, Item Comp, Time Event), which all "fire a target
        group" as their effect rather than animating an object.

        "Immediately" now means "queued for this tick's ordered drain"
        (_drain_trigger_event_queue) rather than "executed inline at this
        exact point in the call stack" -- see _enqueue_trigger_event."""
        if not group:
            return
        for o in self._by_group.get(group, ()):
            if o.get("t") in TRIGGER_TYPES and self._trigger_active(o):
                self._enqueue_trigger_event(o, TRIGGER_FAMILY_SPAWN)

    # ---- random selection (Checkpoint 3) --------------------------------
    def _apply_random_trigger(self, trig):
        """Random Trigger (real GD id 1912) -- the report's Paired-family
        "Randomly select one of two groups".

        ``chance`` is the percentage the FIRST target group wins; the
        remainder goes to ``target_group2``. The report documents no
        default for it, so the spec's 50 is an engine choice.

        The roll is exact at both ends, which is what the headless tests
        pin: ``random.random()`` is in [0, 1), so ``chance=100`` always
        takes group 1 and ``chance=0`` never does.

        Firing goes through _fire_group, the same path Spawn/Sequence/
        Repeat and the item-logic family use, so the chosen group's
        triggers land in this tick's ordered event queue rather than
        running inline -- a Random trigger is a Spawn with a die roll in
        front of it, and behaves identically once the group is picked.
        """
        try:
            chance = float(trig.get("chance", 50.0))
        except (TypeError, ValueError):
            chance = 50.0
        if random.random() * 100.0 < chance:
            self._fire_group(trig.get("target_group"))
        else:
            self._fire_group(trig.get("target_group2"))

    def _apply_advanced_random_trigger(self, trig):
        """Advanced Random Trigger (real GD id 2068) -- "weighted random,
        up to 20 groups".

        The report's probability law is ``P(i) = 100 * w_i / sum(w_j)``,
        implemented as a single uniform draw over the cumulative weight
        so it holds exactly for any weights (the 10/15 example in the
        report's own records is a 40/60 split).

        Weights and groups come from objects.advanced_random_weighted_list
        -> parse_weighted_list, which reads the report's dot-separated
        "group.weight..." string. Slots with weight 0 never reach here,
        so an unauthored trigger has a total of 0 and is a no-op.
        """
        pairs = parse_weighted_list(advanced_random_weighted_list(trig))
        total = sum(w for _, w in pairs)
        if total <= 0:
            return
        roll = random.random() * total
        cumulative = 0
        for group, weight in pairs:
            cumulative += weight
            if roll < cumulative:
                self._fire_group(group)
                return
        # random() < 1 makes roll < total, so the loop always returns;
        # this only catches a float-rounding tail on huge weight sums.
        self._fire_group(pairs[-1][0])

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
        # A Follow link's "target" is the object actually being moved each
        # tick (mirrors Move/Rotate/Scale/Alpha's own "obj"/"targets" key) --
        # without this a Stop Trigger silently left Follow Triggers running,
        # since it only ever filtered the other four animation lists.
        self.active_follows = [f for f in self.active_follows
                               if id(f["target"]) not in members]

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

    # ---- effects that had no named method of their own ------------------
    # These were inline bodies of the old _execute_trigger_effect if/elif
    # chain; they are named methods now purely so every trigger type can be
    # one TRIGGER_HANDLERS entry. Bodies are unchanged.

    def _apply_camera_trigger(self, o):
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
            self.target_cam_y = (row * UNITS_PER_BLOCK
                                 + UNITS_PER_BLOCK / 2 - CAMERA_HEIGHT_UNITS / 2)
            try:
                self.cam_pan_duration = max(0.0, float(o.get("duration", 1.0)))
            except (TypeError, ValueError):
                self.cam_pan_duration = 1.0

    def _apply_bg_trigger(self, o):
        self.bg_preset = int(o.get("bg", 0))

    def _apply_color_trigger(self, o):
        self.color_index = int(o.get("channel", o.get("col_idx", 0)))
        self.player_color = channel_color(self.channels, self.color_index)[:3]

    def _apply_time_warp_trigger(self, o):
        try:
            self.time_warp = float(o.get("factor", 1.0))
        except (TypeError, ValueError):
            self.time_warp = 1.0

    def _apply_follow_trigger(self, o):
        """An always-on Follow link is armed once at level start
        (_arm_always_on_follows), so activating it again is a no-op."""
        if not o.get("always_on"):
            self._start_follow_trigger(o)

    def _apply_count_trigger(self, o):
        # A direct touch/spawn is an immediate check-and-fire,
        # independent of Count Trigger's own continuous watcher
        # (_step_count_watchers) -- so touching one still works even
        # if the item value never changes again after this frame.
        if self._count_condition(o):
            self._fire_group(o.get("target_group"))

    def _apply_time_event_trigger(self, o):
        timer_id = int(o.get("timer_id", 0))
        try:
            threshold = float(o.get("threshold", 0.0))
        except (TypeError, ValueError):
            threshold = 0.0
        if self.timers.get(timer_id, 0.0) >= threshold:
            self._fire_group(o.get("target_group"))

    # ---- player state (Checkpoint 6) ------------------------------------
    # deep-research-report.md, "Gameplay, camera, UI, and environment".
    # These four handlers own no state of their own: each one is a thin
    # activation path into a primitive that already existed in core.py
    # (set_body_gravity / teleport_to_cell / save_checkpoint) or into the
    # one new primitive this checkpoint added (set_gameplay_direction).

    def _apply_gameplay_rotation_trigger(self, o):
        """Gameplay Rotation (real GD id 2900): retarget the player's
        direction, gravity and vertical velocity in one activation.

        Every field's "none"/0 means "leave that part of the player
        alone", so one trigger can flip gravity without touching
        direction, or vice versa.

        ``gravity_dir`` goes through Player.set_body_gravity -- the same
        call the T_GRAV_UP/T_GRAV_DOWN portals make in _handle_interactions
        -- so "up" lands on exactly the state touching a Gravity Up portal
        lands on, no-op-when-already-there included. ``channel`` is read
        by nothing: this engine has no gameplay-channel gating (see the
        spec in objects.py).
        """
        direction = str(o.get("direction", "none"))
        if direction == "forward":
            self.set_gameplay_direction(1)
        elif direction == "reverse":
            self.set_gameplay_direction(-1)
        elif direction == "flip":
            self.set_gameplay_direction(-self.move_dir)
        gravity = _GRAVITY_DIR_SIGN.get(str(o.get("gravity_dir", "none")))
        if gravity is not None:
            self.set_body_gravity(self, gravity)
        try:
            velocity = float(o.get("velocity_override", 0.0))
        except (TypeError, ValueError):
            velocity = 0.0
        if velocity:
            # Absolute screen space (+ = down), like vy everywhere else.
            # on_ground goes false so a grounded body actually leaves the
            # floor instead of having the new velocity resolved away on
            # the next collision pass -- the same pairing every other
            # velocity-writing action here makes (jump, orbs, portals).
            self.vy = velocity
            self.on_ground = False

    def _apply_reverse_trigger(self, o):
        """Reverse (real GD id 1917): flip the gameplay direction.

        Minimal viable scope, documented as such: before this checkpoint
        the engine had no notion of gameplay direction at all (the player
        auto-scrolled rightwards at ``move_speed``, full stop). "Reverse"
        here therefore means the auto-scroll step's SIGN flips -- see
        Player.set_gameplay_direction and update()'s ``dx`` -- not a full
        bidirectional level model: nothing else in the engine (camera
        lead, progress percentage, the finish wall, the bots' left-to-
        right search heuristics) has been retargeted for backwards play.
        """
        self.set_gameplay_direction(-self.move_dir)

    def _apply_teleport_trigger(self, o):
        """Teleport (real GD id 3022): snap the player onto the first
        member of the target group.

        Distinct from the touch-based Teleport Orb / Portal pair, which
        link to each other by a shared group id and fire on contact; this
        one is fired like any other trigger and reads ``target_group``
        through the standard _resolve_targets path (so an explicit
        ``target_oid`` works too, exactly as it does for Move/Rotate).

        A group with several members resolves to its FIRST member --
        _resolve_targets returns objects in a stable order, and a
        teleport has exactly one destination.

        The snap itself is Player.teleport_to_cell, which is also what
        the orb/portal pair calls, so a triggered teleport is
        indistinguishable from an orb teleport in its end state
        (centring, quarter-damped vy, teleport cooldown, cleared trail).
        """
        targets = self._resolve_targets(o)
        if not targets:
            return
        x_only = bool(o.get("x_only", False))
        y_only = bool(o.get("y_only", False))
        self.teleport_to_cell(targets[0], move_x=not y_only,
                              move_y=not x_only)

    def _apply_checkpoint_trigger(self, o):
        """Checkpoint (real GD id 2063): save a practice checkpoint here.

        Purely an activation path into the pre-existing
        Player.save_checkpoint() -- no new restore logic, and no new data
        shape: what this writes is byte-for-byte what pressing C in
        practice mode writes.

        Gated on ``practice_mode`` because that is the only mode that
        ever reads ``checkpoints`` back (play.py restores the last one on
        death), and because an ungated one inside a Repeat chain would
        append a checkpoint dict per tick -- unbounded growth during a
        bot search, which replays a level thousands of times.
        """
        if not self.practice_mode:
            return
        self.save_checkpoint()
        if self.audio_output_enabled:
            # The same cue play.py's manual C-key path plays, so a
            # triggered checkpoint is as audible as a manual one.
            sfx.play("practice_checkpoint", 0.4)

    # ---- environment / UI / events / end (Checkpoint 7) -----------------
    # deep-research-report.md, "Gameplay, camera, UI, and environment".

    def _apply_ground_trigger(self, o):
        """Change Ground (real GD id 3030) -- DELIBERATE NO-OP.

        There is no ground palette in this engine to select from: the
        ground is drawn from the fixed C_GROUND / C_GROUND_L /
        C_GROUND_DARK constants in graphics.draw_bg, and BG_PRESETS is
        the only environment preset table that exists. The trigger's
        ``ground`` index is authored, saved and round-tripped (so a level
        written in the report's vocabulary survives), and this handler
        deliberately reads nothing -- the same honest inert-storage
        precedent as the Shader Trigger's layer range and the audio
        family's speed/pitch/reverb fields.

        The handler exists rather than being omitted because
        TRIGGER_HANDLERS is required to cover TRIGGER_TYPES exactly (a
        pinned invariant); a missing entry would read as an oversight,
        while this reads as a decision.
        """

    def _apply_mg_trigger(self, o):
        """Change Middleground (real GD id 3031) -- DELIBERATE NO-OP, for
        exactly the reason _apply_ground_trigger documents: the
        middleground is graphics._MOUNTAIN_SHADES, a fixed tuple, not a
        selectable preset table. The ``mg`` index is stored only."""

    def _apply_bg_speed_trigger(self, o):
        """Background Speed (real GD id 3606): how fast the background
        parallax layer scrolls relative to the camera.

        The report's documented defaults (0.1 / 0.1) are the identity
        point: what reaches the renderer is speed/default, a MULTIPLIER
        on the fixed star-field scroll rate draw_bg already uses. So a
        trigger left at its defaults changes nothing, and a level with no
        BG Speed trigger renders exactly as it did before this
        checkpoint. See Player.bg_scroll_scale.
        """
        self.bg_speed_x = _env_speed(o.get("speed_x"), BG_SPEED_DEFAULT_X)
        self.bg_speed_y = _env_speed(o.get("speed_y"), BG_SPEED_DEFAULT_Y)

    def _apply_mg_speed_trigger(self, o):
        """Middleground Speed (real GD id 3612): the same multiplier model
        as _apply_bg_speed_trigger, applied to the mountain layers, whose
        report-documented defaults are 0.3 / 0.5."""
        self.mg_speed_x = _env_speed(o.get("speed_x"), MG_SPEED_DEFAULT_X)
        self.mg_speed_y = _env_speed(o.get("speed_y"), MG_SPEED_DEFAULT_Y)

    def bg_scroll_scale(self):
        """(x, y) multiplier for the background parallax rate."""
        return (self.bg_speed_x / BG_SPEED_DEFAULT_X,
                self.bg_speed_y / BG_SPEED_DEFAULT_Y)

    def mg_scroll_scale(self):
        """(x, y) multiplier for the middleground parallax rate."""
        return (self.mg_speed_x / MG_SPEED_DEFAULT_X,
                self.mg_speed_y / MG_SPEED_DEFAULT_Y)

    def _apply_ui_trigger(self, o):
        """UI Trigger (real GD id 3613): post/replace/clear one HUD label.

        Scoped to a camera-anchored text label (see the spec in
        objects.py for why). ``ui_id`` addresses the label the same way
        an Item Counter row addresses an item id -- firing a second UI
        Trigger with the same id replaces that row rather than stacking a
        new one, and one with ``state`` off removes it.

        ``duration`` 0 means "keep until replaced or cleared"; anything
        else expires ``duration`` seconds later, measured in physics
        ticks so it is correct at any tick rate (the same PHYSICS_TPS
        conversion the pulse/blackout/spawn-delay code uses).
        """
        uid = int(o.get("ui_id", 0) or 0)
        if not o.get("state", True):
            self.ui_labels.pop(uid, None)
            return
        try:
            duration = max(0.0, float(o.get("duration", 0.0)))
        except (TypeError, ValueError):
            duration = 0.0
        self.ui_labels[uid] = {
            "text": str(o.get("text", UI_TEXT_CHOICES[0])),
            "x_offset": int(o.get("x_offset", 0) or 0),
            "y_offset": int(o.get("y_offset", 0) or 0),
            # None = persistent; otherwise the frame it stops rendering.
            "expire_frame": (None if duration <= 0.0
                             else self.frame + max(1, round(duration * PHYSICS_TPS))),
        }

    def active_ui_labels(self):
        """Live UI Trigger labels, oldest ``ui_id`` first.

        Called once per rendered frame by play_render.render_hud, which
        is also the only place expired labels get dropped -- there is no
        per-tick stepper for this, because a label that has expired is
        indistinguishable from one that was never posted until something
        tries to draw it.
        """
        if not self.ui_labels:
            return ()
        expired = [uid for uid, e in self.ui_labels.items()
                   if e["expire_frame"] is not None
                   and self.frame >= e["expire_frame"]]
        for uid in expired:
            del self.ui_labels[uid]
        return tuple(self.ui_labels[uid] for uid in sorted(self.ui_labels))

    def _arm_event_triggers(self):
        """Index every Event Trigger in the level by its event_type.

        The same one-scan-at-level-load shape as _arm_always_on_follows,
        so the event hook points (Player._kill, save_checkpoint, the win
        flag) cost a lookup on a usually-empty dict rather than a scan.
        Called from Player.__init__ rather than reset(), like
        _count_watchers: an object's event_type cannot change during a
        session, so rebuilding this per attempt would be pure waste in a
        bot search.
        """
        index = {}
        for o in self.objects:
            if o.get("t") != T_EVENT_TRIGGER:
                continue
            event = str(o.get("event_type", LEVEL_EVENTS[0]))
            if event in LEVEL_EVENTS:
                index.setdefault(event, []).append(o)
        self._event_triggers = index

    def _fire_event(self, event):
        """Activate every Event Trigger registered for ``event``.

        Queued through _enqueue_trigger_event like any other activation,
        so an engine-fired Event Trigger obeys the same same-frame
        ordering rules (and the same recursion bound) as a touched or
        spawned one. Gated by _trigger_active so a Toggle-disabled Event
        Trigger stays silent, exactly like a spawned trigger.
        """
        for o in self._event_triggers.get(event, ()):
            if self._trigger_active(o):
                self._enqueue_trigger_event(o, TRIGGER_FAMILY_SPAWN)

    def _apply_event_trigger(self, o):
        """Event Trigger (real GD id 3604): fire the target group.

        The handler itself is an ordinary "fire a group" -- what makes
        this trigger different is WHO activates it (_fire_event, called
        from the engine's own death/win/checkpoint/level-start code
        paths), not what it does once activated. Touch/Spawn activation
        works too and lands here identically.
        """
        self._fire_group(o.get("target_group"))

    def _apply_end_trigger(self, o):
        """End Trigger (real GD id 3600): end the level.

        A SECOND ACTIVATION PATH into the win flag core.py's finish-wall
        check already sets -- deliberately not new win logic. Everything
        downstream (play.py's win overlay, best-time persistence, the
        bots' success test) reads Player.won and cannot tell the two
        apart, which is the whole point.

        Guarded on ``self.won`` so the win event fires exactly once per
        attempt no matter how many End Triggers a group holds.
        """
        if self.won:
            return
        self.won = True
        self._fire_event(EVENT_WIN)

    # ---- dispatch ------------------------------------------------------
    def _execute_trigger_effect(self, o):
        """Run one trigger's effect immediately, via the flat handler table
        in trigger_registry.py. Called only from
        _drain_trigger_event_queue: both activation paths (player touch in
        core.py, Spawn/Sequence/item-logic dispatch in _fire_group) enqueue
        an ordered event instead of calling this directly, so a spawned
        trigger behaves identically to a touched one and same-frame order
        is deterministic."""
        handler = TRIGGER_HANDLERS.get(o.get("t"))
        if handler is not None:
            handler(self, o)

    def _enqueue_trigger_event(self, o, family):
        """Queue one activation of trigger ``o`` for this tick's drain.

        Sort key, per deep-research-report.md's "Same-frame precedence"
        section:
        - ``family``: engine-chosen cross-family rank (trigger_registry's
          TRIGGER_FAMILY_* constants -- the report leaves this unspecified).
        - ``trigger_order``: the report's ascending Trigger Order value.
        - ``x``: the report's left-to-right spawn ordering.
        - ``placement_priority``: always 0. The report's final documented
          tiebreak is "most recently created wins", but objects carry no
          creation timestamp in this engine, so there is nothing to rank
          on; the slot is kept so the key shape matches the report.
        - stable object index: ``_oid_index`` (a position in
          ``self.objects``, portable across SimPlayer copies) as the last
          deterministic tiebreak.
        The object itself rides along as the tuple's tail and is excluded
        from the sort key (dicts are not orderable, and the same object can
        legitimately be enqueued twice in one tick via Multi Activate);
        the sort being stable makes enqueue order the final fallback.
        """
        try:
            order = int(o.get("trigger_order", 0) or 0)
        except (TypeError, ValueError):
            order = 0
        self._trigger_event_queue.append((
            family, order, float(o.get("x", 0)), 0,
            self._oid_index.get(id(o), 0), o,
        ))

    def _drain_trigger_event_queue(self):
        """Execute every trigger queued this tick, in key order.

        Handlers may enqueue further events (Spawn firing a group, Item
        Comp firing on a comparison), so each pass takes the whole queue,
        sorts it, runs it, and repeats on whatever the run appended --
        bounded by TRIGGER_DRAIN_MAX_PASSES so a self-refiring trigger
        cycle drops its tick instead of hanging the simulation."""
        for _ in range(TRIGGER_DRAIN_MAX_PASSES):
            if not self._trigger_event_queue:
                return
            batch = self._trigger_event_queue
            self._trigger_event_queue = []
            batch.sort(key=lambda ev: ev[:-1])
            for ev in batch:
                self._execute_trigger_effect(ev[-1])
        self._trigger_event_queue = []

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
                sx, sy = self._player_center_cell_pos()
            else:
                sx = float(source.get("_fx", source["x"]))
                sy = float(source.get("_fy", source["y"]))
            self._set_object_pos(link["target"], sx + link["offset_x"],
                                 sy + link["offset_y"])

    def _player_center_cell_pos(self):
        """The live player's position in the same "grid cell" units as a
        placed object's ``x``/``y``, corrected so a Follow Trigger's
        target sprite -- always drawn at full cell size, filling its cell
        -- visually CENTERS on the player rather than sharing its raw
        top-left anchor.

        The player's body (``self.size``, e.g. 18 units in mini) can be
        smaller than a grid cell (``UNITS_PER_BLOCK``) and is drawn
        centered around ``x + size / 2`` (``player/draw.py``), while an
        object sprite fills its whole cell and is anchored at its
        top-left -- the two anchors differ by half the size shortfall.
        Without this correction a "Follow player" orb renders a few
        pixels down-right of the player it's supposed to be centered on.
        """
        offset_cells = (self.size - UNITS_PER_BLOCK) / (2.0 * UNITS_PER_BLOCK)
        return (self.x / UNITS_PER_BLOCK + offset_cells,
                self.y / UNITS_PER_BLOCK + offset_cells)

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


# ---------------------------------------------------------------------------
# Handler table
# ---------------------------------------------------------------------------
# One entry per trigger type, replacing the old _execute_trigger_effect
# if/elif chain. Handlers are the unbound TriggerMixin methods themselves
# (invoked as handler(player, obj)); the five screen effects share
# _start_effect_trigger and so bind their effect name via a lambda.
TRIGGER_HANDLERS.update({
    T_CAMERA_TRIGGER: TriggerMixin._apply_camera_trigger,
    T_BG_TRIGGER: TriggerMixin._apply_bg_trigger,
    T_MOVE_TRIGGER: TriggerMixin._start_move_trigger,
    T_COLOR_TRIGGER: TriggerMixin._apply_color_trigger,
    T_PULSE_TRIGGER: TriggerMixin._start_pulse_trigger,
    T_ROTATE_TRIGGER: TriggerMixin._start_rotate_trigger,
    T_FOLLOW_TRIGGER: TriggerMixin._apply_follow_trigger,
    T_TIME_WARP: TriggerMixin._apply_time_warp_trigger,
    T_BLACKOUT_TRIGGER: TriggerMixin._start_blackout_trigger,
    T_SCALE_TRIGGER: TriggerMixin._start_scale_trigger,
    T_ALPHA_TRIGGER: TriggerMixin._start_alpha_trigger,
    T_SPAWN_TRIGGER: TriggerMixin._start_spawn_trigger,
    T_TOGGLE_TRIGGER: TriggerMixin._apply_toggle_trigger,
    T_STOP_TRIGGER: TriggerMixin._apply_stop_trigger,
    T_SEQUENCE_TRIGGER: TriggerMixin._start_sequence_trigger,
    T_REPEAT_TRIGGER: TriggerMixin._start_repeat_trigger,
    T_SWAP_TRIGGER: TriggerMixin._start_swap_trigger,
    T_ZOOM_TRIGGER: TriggerMixin._start_zoom_trigger,
    T_CAM_OFFSET_TRIGGER: TriggerMixin._start_cam_offset_trigger,
    T_CAM_ROTATE_TRIGGER: TriggerMixin._start_cam_rotate_trigger,
    T_CAM_EDGE_TRIGGER: TriggerMixin._apply_cam_edge_trigger,
    T_CAM_GUIDE_TRIGGER: TriggerMixin._apply_cam_guide_trigger,
    T_GRAYSCALE_TRIGGER: lambda p, o: p._start_effect_trigger(o, "grayscale"),
    T_SEPIA_TRIGGER: lambda p, o: p._start_effect_trigger(o, "sepia"),
    T_INVERT_TRIGGER: lambda p, o: p._start_effect_trigger(o, "invert"),
    T_HUE_TRIGGER: lambda p, o: p._start_effect_trigger(o, "hue"),
    T_PIXELATE_TRIGGER: lambda p, o: p._start_effect_trigger(o, "pixelate"),
    # Checkpoint 4's shader family. The six animated ones share
    # _start_effect_trigger exactly like the five above; only the base
    # Shader Trigger gets its own handler, because clearing the effect
    # dict is not a tween.
    T_CHROMATIC_TRIGGER: lambda p, o: p._start_effect_trigger(o, "chromatic"),
    T_RADIAL_BLUR_TRIGGER: lambda p, o: p._start_effect_trigger(o, "radial_blur"),
    T_MOTION_BLUR_TRIGGER: lambda p, o: p._start_effect_trigger(o, "motion_blur"),
    T_BULGE_TRIGGER: lambda p, o: p._start_effect_trigger(o, "bulge"),
    T_PINCH_TRIGGER: lambda p, o: p._start_effect_trigger(o, "pinch"),
    T_SPLIT_SCREEN_TRIGGER: lambda p, o: p._start_effect_trigger(o, "split_screen"),
    T_SHADER_TRIGGER: TriggerMixin._apply_shader_trigger,
    T_COUNT_TRIGGER: TriggerMixin._apply_count_trigger,
    T_INSTANT_COUNT_TRIGGER: TriggerMixin._apply_count_trigger,
    T_ITEM_EDIT_TRIGGER: TriggerMixin._apply_item_edit_trigger,
    T_ITEM_COMP_TRIGGER: TriggerMixin._apply_item_comp_trigger,
    T_ITEM_PERS_TRIGGER: TriggerMixin._apply_item_pers_trigger,
    T_TIME_TRIGGER: TriggerMixin._apply_time_trigger,
    T_TIME_EVENT_TRIGGER: TriggerMixin._apply_time_event_trigger,
    T_KEYFRAME_TRIGGER: TriggerMixin._start_keyframe_trigger,
    # Area family (Checkpoint 2). These are ordinary one-shot
    # activations like every other entry here -- starting, retuning or
    # ending an area effect is a discrete event that goes through the
    # touch/spawn -> enqueue -> drain -> registry path. Only the
    # per-tick advance of an already-live effect is a stepper
    # (_step_area_effects, called from Player.update()).
    T_AREA_MOVE_TRIGGER: TriggerMixin._start_area_move_trigger,
    T_AREA_ROTATE_TRIGGER: TriggerMixin._start_area_rotate_trigger,
    T_AREA_SCALE_TRIGGER: TriggerMixin._start_area_scale_trigger,
    T_AREA_FADE_TRIGGER: TriggerMixin._start_area_fade_trigger,
    T_AREA_TINT_TRIGGER: TriggerMixin._start_area_tint_trigger,
    T_EDIT_AREA_MOVE_TRIGGER: TriggerMixin._apply_edit_area_move_trigger,
    T_EDIT_AREA_ROTATE_TRIGGER: TriggerMixin._apply_edit_area_rotate_trigger,
    T_EDIT_AREA_SCALE_TRIGGER: TriggerMixin._apply_edit_area_scale_trigger,
    T_EDIT_AREA_FADE_TRIGGER: TriggerMixin._apply_edit_area_fade_trigger,
    T_EDIT_AREA_TINT_TRIGGER: TriggerMixin._apply_edit_area_tint_trigger,
    T_AREA_STOP_TRIGGER: TriggerMixin._apply_area_stop_trigger,
    # Random family (Checkpoint 3). Force Block is deliberately absent:
    # it fires no group and has no handler -- its impulse is a contact
    # response in core.py's _handle_interactions, like the letter blocks.
    T_RANDOM_TRIGGER: TriggerMixin._apply_random_trigger,
    T_ADVANCED_RANDOM_TRIGGER: TriggerMixin._apply_advanced_random_trigger,
    # Audio family (Checkpoint 5). One-shot activations like everything
    # else here: starting, patching or stopping audio is a discrete event
    # through the touch/spawn -> enqueue -> drain -> registry path. There
    # is no audio stepper -- playback advances in the mixer's own thread,
    # not on the physics tick.
    T_SONG_TRIGGER: TriggerMixin._apply_song_trigger,
    T_SFX_TRIGGER: TriggerMixin._apply_sfx_trigger,
    T_EDIT_SONG_TRIGGER: TriggerMixin._apply_edit_song_trigger,
    T_EDIT_SFX_TRIGGER: TriggerMixin._apply_edit_sfx_trigger,
    # Player-state family (Checkpoint 6). One-shot activations like the
    # rest of this table; none of them has a stepper, because retargeting
    # the player is an instant state change, not a tween -- what happens
    # afterwards is just the physics loop running with the new state.
    T_GAMEPLAY_ROTATION_TRIGGER: TriggerMixin._apply_gameplay_rotation_trigger,
    T_REVERSE_TRIGGER: TriggerMixin._apply_reverse_trigger,
    T_TELEPORT_TRIGGER: TriggerMixin._apply_teleport_trigger,
    T_CHECKPOINT_TRIGGER: TriggerMixin._apply_checkpoint_trigger,
    # Environment / UI / event / end family (Checkpoint 7). Ground and MG
    # Change are registered on purpose even though their handlers are
    # documented no-ops: TRIGGER_HANDLERS is pinned to cover TRIGGER_TYPES
    # exactly, so an omission would read as a gap rather than a decision
    # (see _apply_ground_trigger). None of the seven has a stepper --
    # a parallax rate and a HUD label are read by the renderer where it
    # already runs, not advanced on the physics tick.
    T_GROUND_TRIGGER: TriggerMixin._apply_ground_trigger,
    T_MG_TRIGGER: TriggerMixin._apply_mg_trigger,
    T_BG_SPEED_TRIGGER: TriggerMixin._apply_bg_speed_trigger,
    T_MG_SPEED_TRIGGER: TriggerMixin._apply_mg_speed_trigger,
    T_UI_TRIGGER: TriggerMixin._apply_ui_trigger,
    T_EVENT_TRIGGER: TriggerMixin._apply_event_trigger,
    T_END_TRIGGER: TriggerMixin._apply_end_trigger,
})
