"""Collision: spatial index, block / slope resolution, hazard OBB tests.

Every routine takes a ``body`` argument (the :class:`Player` itself for
the main body, a :class:`MirrorBody` for the dual mirror).  Both bodies
share the player's ``x``; everything else is read from the body.
"""

import math

from ..constants import (
    CELL, PLAYER_SIZE, SOLID_HITBOX_FRACTION, HITBOX_SOLID_FRACTION,
    T_BLOCK, T_SLAB, T_SLOPE, T_START, T_SPIKE, T_HALF_SPIKE, T_SAW,
    SOLID_TYPES, MODE_WAVE, MODE_CUBE, MODE_ROBOT,
    T_WAVE_BLOCK, T_BONK_BLOCK,
)
from ..geometry import (
    cell_rect, slab_rect, spike_hitboxes, saw_hitbox, obj_scale,
)

# Object types the interaction pass never reacts to.
_NON_TRIGGER_TYPES = frozenset(SOLID_TYPES | {T_START, T_SLOPE})

# Per-object caches that depend on the object's pose.
_POSE_CACHE_KEYS = ("_srect", "_caabb", "_saw_aabb", "_sphb_aabbs")


def solid_hitbox_fraction(mode, size):
    """Inner ("blue" solid) hitbox as a fraction of the outer box, per the
    physics bible's §3.2 per-(mode, mini) table. ``size`` decides normal vs
    mini (mirrors the ``mini = b.size < PLAYER_SIZE`` convention used
    elsewhere in the player module)."""
    normal, mini = HITBOX_SOLID_FRACTION.get(
        mode, (SOLID_HITBOX_FRACTION, SOLID_HITBOX_FRACTION))
    return mini if size < PLAYER_SIZE else normal


def is_non_trigger(o):
    return o["t"] in _NON_TRIGGER_TYPES


def invalidate_pose_caches(o):
    """Drop cached AABBs after an object's x / y / r / scale changed."""
    for k in _POSE_CACHE_KEYS:
        if k in o:
            del o[k]


# ---------------------------------------------------------------------------
# Oriented bounding box helpers (rotated outer hitbox vs axis-aligned rect)
# ---------------------------------------------------------------------------

def obb_corners(x, y, size, angle_deg, scale=1.0):
    """Corners of a square of side ``size * scale`` centred in the
    ``(x, y, size)`` box, rotated ``angle_deg`` (screen-space clockwise)."""
    rad = -angle_deg * 0.017453292519943295
    cs = math.cos(rad)
    sn = math.sin(rad)
    cx = x + size * 0.5
    cy = y + size * 0.5
    h = size * 0.5 * scale
    return [(cx + ox * cs - oy * sn, cy + ox * sn + oy * cs)
            for ox, oy in ((-h, -h), (h, -h), (h, h), (-h, h))]


def _project(axis_x, axis_y, points):
    pmin = pmax = points[0][0] * axis_x + points[0][1] * axis_y
    for px, py in points[1:]:
        v = px * axis_x + py * axis_y
        if v < pmin:
            pmin = v
        elif v > pmax:
            pmax = v
    return pmin, pmax


def obb_aabb_overlap(corners, left, top, right, bottom):
    """Separating-axis test between a rotated square and an AABB."""
    xs = [c[0] for c in corners]
    if max(xs) < left or min(xs) > right:
        return False
    ys = [c[1] for c in corners]
    if max(ys) < top or min(ys) > bottom:
        return False
    ex = corners[1][0] - corners[0][0]
    ey = corners[1][1] - corners[0][1]
    ln = (ex * ex + ey * ey) ** 0.5
    if ln == 0.0:
        return True
    nx1, ny1 = ex / ln, ey / ln
    aabb = ((left, top), (right, top), (right, bottom), (left, bottom))
    for nx, ny in ((nx1, ny1), (-ny1, nx1)):
        a0, a1 = _project(nx, ny, corners)
        b0, b1 = _project(nx, ny, aabb)
        if a1 < b0 or a0 > b1:
            return False
    return True


# ---------------------------------------------------------------------------
# Mixin
# ---------------------------------------------------------------------------

class CollisionMixin:
    __slots__ = ()

    # ---- spatial index ---------------------------------------------------
    def _rebuild_spatial_index(self):
        """(Re)build the full and trigger-only ``(gx, gy) -> [obj]`` maps."""
        self._spatial_index = {}
        self._trigger_index = {}
        for o in self.objects:
            cell = (o["x"], o["y"])
            o["_cell"] = cell
            self._spatial_index.setdefault(cell, []).append(o)
            if not is_non_trigger(o):
                self._trigger_index.setdefault(cell, []).append(o)
        self._nearby_cache_key = None
        self._nearby_trigger_cache_key = None

    def _spatial_rebucket(self, obj):
        """Move ``obj`` between buckets after its cell changed."""
        old = obj.get("_cell")
        new = (obj["x"], obj["y"])
        if old == new:
            return
        self._nearby_cache_key = None
        self._nearby_trigger_cache_key = None
        indexes = [self._spatial_index]
        if not is_non_trigger(obj):
            indexes.append(self._trigger_index)
        for index in indexes:
            if old is not None:
                bucket = index.get(old)
                if bucket is not None:
                    for i, o in enumerate(bucket):
                        if o is obj:
                            bucket.pop(i)
                            break
                    if not bucket:
                        index.pop(old, None)
            index.setdefault(new, []).append(obj)
        obj["_cell"] = new

    def nearby_for_rect(self, rect, extra=2):
        return self._nearby_for_aabb(rect.left, rect.top, rect.right,
                                     rect.bottom, extra)

    def _nearby_for_aabb(self, left_px, top_px, right_px, bottom_px, extra=2):
        """Objects in the cells around a pixel box.  Bot-only objects are
        phantom unless ``self._bot_visibility`` is set."""
        left = left_px // CELL - extra
        right = right_px // CELL + extra
        top = top_px // CELL - extra
        bottom = bottom_px // CELL + extra
        bot_vis = self._bot_visibility
        key = (left, top, right, bottom, extra, bot_vis)
        if key == self._nearby_cache_key:
            return self._nearby_cache_result
        out = []
        index = self._spatial_index
        for gx in range(left, right + 1):
            for gy in range(top, bottom + 1):
                bucket = index.get((gx, gy))
                if bucket:
                    out.extend(bucket)
        if not bot_vis and out:
            for o in out:
                if o.get("_bot_only"):
                    out = [o for o in out if not o.get("_bot_only")]
                    break
        self._nearby_cache_key = key
        self._nearby_cache_result = out
        return out

    def _nearby_triggers_for_aabb(self, left_px, top_px, right_px,
                                  bottom_px, extra=2):
        left = left_px // CELL - extra
        right = right_px // CELL + extra
        top = top_px // CELL - extra
        bottom = bottom_px // CELL + extra
        bot_vis = self._bot_visibility
        key = (left, top, right, bottom, extra, bot_vis)
        if key == self._nearby_trigger_cache_key:
            return self._nearby_trigger_cache_result
        out = []
        index = self._trigger_index
        for gx in range(left, right + 1):
            for gy in range(top, bottom + 1):
                bucket = index.get((gx, gy))
                if bucket:
                    out.extend(bucket)
        if not bot_vis:
            out = [o for o in out if not o.get("_bot_only")]
        self._nearby_trigger_cache_key = key
        self._nearby_trigger_cache_result = out
        return out

    # ---- solid rects -----------------------------------------------------
    def _solid_rect(self, o):
        """``(left, top, right, bottom)`` int bounds for a block / slab, or
        ``None`` for anything else (slopes are handled diagonally)."""
        cached = o.get("_srect")
        if cached is not None:
            return cached
        t = o["t"]
        if t == T_BLOCK:
            r = cell_rect(o["x"], o["y"], obj_scale(o))
        elif t == T_SLAB:
            r = slab_rect(o["x"], o["y"], o.get("r", 0), obj_scale(o))
        else:
            return None
        aabb = (r.left, r.top, r.right, r.bottom)
        o["_srect"] = aabb
        return aabb

    _invalidate_solid_rect = staticmethod(invalidate_pose_caches)

    def _letter_block_nearby(self, px, py, size, block_type):
        """D/H Block (bible Sec 4.3/4.4): true when a marker of
        ``block_type`` overlaps this pixel box. Both blocks are inert,
        non-solid objects (never returned by ``_solid_rect``) placed at
        or near the solid the player would otherwise die against, so
        this is a separate presence check, not a collision one."""
        for o in self._nearby_for_aabb(px, py, px + size, py + size):
            if o["t"] != block_type:
                continue
            cr = o.get("_caabb")
            if cr is None:
                r = cell_rect(o["x"], o["y"], obj_scale(o))
                cr = (r.left, r.top, r.right, r.bottom)
                o["_caabb"] = cr
            cl, ct, crr, cb = cr
            if px < crr and px + size > cl and py < cb and py + size > ct:
                return True
        return False

    @staticmethod
    def _inner_bounds(x, y, size, mode=None):
        frac = solid_hitbox_fraction(mode, size)
        inner = max(2, int(size * frac))
        cx = round(x) + size // 2
        cy = round(y) + size // 2
        left = cx - inner // 2
        top = cy - inner // 2
        return left, top, left + inner, top + inner

    # ---- block resolution ------------------------------------------------
    def _resolve_x_collision(self, b, dx_step):
        """Kill the body if its inner hitbox is inside a block after the
        x step (walls are always lethal).  Returns True on death.

        Pure death-trap, not real solid support (unlike landing on a
        floor) — under noclip the position snap and substep-abort are
        skipped so the body doesn't get pinned to the wall, but ``_kill``
        still runs (it no-ops the actual death) so a dash that would
        have ended here still ends, instead of dashing forever."""
        size = b.size
        px = round(self.x)
        py = round(b.y)
        il, it, ir, ib = self._inner_bounds(self.x, b.y, size, b.mode)
        solid_rect = self._solid_rect
        for o in self._nearby_for_aabb(px, py, px + size, py + size):
            br = o.get("_srect") or solid_rect(o)
            if br is None:
                continue
            bl, bt, brr, bb = br
            if il < brr and ir > bl and it < bb and ib > bt:
                if ((b.mode == MODE_WAVE
                     and self._letter_block_nearby(px, py, size, T_WAVE_BLOCK))
                        or (b.mode in (MODE_CUBE, MODE_ROBOT)
                            and self._letter_block_nearby(
                                px, py, size, T_BONK_BLOCK))):
                    if dx_step > 0:
                        self.x = bl - size
                    elif dx_step < 0:
                        self.x = brr
                    b.vy = 0.0
                    return False
                if self.noclip:
                    self._kill(b, "Crashed into a wall")
                    return False
                if dx_step > 0:
                    self.x = bl - size
                elif dx_step < 0:
                    self.x = brr
                self._kill(b, "Crashed into a wall")
                return True
        return False

    def _resolve_y_collision(self, b, dy_step):
        """Resolve a crossed surface using the outer feet/head and inner
        horizontal span. Side penetration is handled by the lethal box.

        Waiting for the inner vertical box to enter the floor makes the
        icon sink, then pop upward by a third of its height every landing.
        """
        size = b.size
        px = round(self.x)
        py = round(b.y)
        il, it, ir, ib = self._inner_bounds(self.x, b.y, size, b.mode)
        hits = []
        solid_rect = self._solid_rect
        for o in self._nearby_for_aabb(px, py, px + size, py + size):
            br = o.get("_srect") or solid_rect(o)
            if br is None:
                continue
            bl, bt, brr, bb = br
            old_y = b.y - dy_step
            crossed = ((dy_step > 0 and old_y + size <= bt + 1e-7
                        and b.y + size >= bt)
                       or (dy_step < 0 and old_y >= bb - 1e-7
                           and b.y <= bb))
            if il < brr and ir > bl and crossed:
                hits.append(br)
        if not hits:
            return
        if len(hits) > 1:
            hits.sort(key=(lambda r: r[1]) if dy_step > 0 else (lambda r: -r[1]))
        for bl, bt, brr, bb in hits:
            landing = (dy_step >= 0) if b.grav == 1 else (dy_step <= 0)
            exempt = self._letter_block_nearby(
                px, py, size, T_WAVE_BLOCK if b.mode == MODE_WAVE else T_BONK_BLOCK)
            if ((b.mode == MODE_WAVE or
                 (b.mode in (MODE_CUBE, MODE_ROBOT) and not landing))
                    and not exempt):
                self._kill(b, "Hit a solid surface" if b.mode == MODE_WAVE
                           else "Hit the underside of a block")
                if not self.noclip:
                    return
            if (b.grav == 1) == landing:
                b.y = bt - size  # feet on top (grav 1) / head hits top (grav -1 rising)
            else:
                b.y = bb
            b.vy = 0.0
            if landing:
                b.on_ground = True
            break

    def _inner_in_block_dies(self, b):
        """Belt-and-braces wall death for the rare case a teleport / pad
        shoved the inner hitbox into a block without a normal resolve."""
        if b.on_ground:
            return False
        size = b.size
        px = round(self.x)
        py = round(b.y)
        il, it, ir, ib = self._inner_bounds(self.x, b.y, size, b.mode)
        solid_rect = self._solid_rect
        for o in self._nearby_for_aabb(px, py, px + size, py + size):
            br = o.get("_srect") or solid_rect(o)
            if br is None:
                continue
            bl, bt, brr, bb = br
            if il < brr and ir > bl and it < bb and ib > bt:
                if ((b.mode == MODE_WAVE
                     and self._letter_block_nearby(px, py, size, T_WAVE_BLOCK))
                        or (b.mode in (MODE_CUBE, MODE_ROBOT)
                            and self._letter_block_nearby(
                                px, py, size, T_BONK_BLOCK))):
                    # D/H Block: bonk/slide instead of dying. Push the
                    # body back out along whichever axis it's less deeply
                    # embedded on, so it doesn't stay stuck inside.
                    pen_x = min(brr - il, ir - bl)
                    pen_y = min(bb - it, ib - bt)
                    if pen_x < pen_y:
                        self.x = bl - size if (il - bl) < (brr - ir) else brr
                    else:
                        b.y = bt - size if (it - bt) < (bb - ib) else bb
                        b.vy = 0.0
                    return False
                self._kill(b, "Crashed into a wall")
                return True
        return False

    def _check_ground_adjacency(self, b):
        """Preserve support only while the gravity-facing edge touches."""
        if not b.alive:
            return
        size = b.size
        # Only preserve real contact. A hitbox-sized magnetic gap used to
        # shorten falls and permit jumps before reaching the platform.
        gap = 1e-6
        px = round(self.x)
        edge = b.y + size if b.grav == 1 else b.y
        p_top = math.floor(edge - 1)
        p_bottom = math.ceil(edge + 1)
        il, _, ir, _ = self._inner_bounds(self.x, b.y, size, b.mode)
        solid_rect = self._solid_rect
        for o in self._nearby_for_aabb(px, p_top, px + size, p_bottom):
            br = o.get("_srect") or solid_rect(o)
            if br is None:
                continue
            bl, bt, brr, bb = br
            surface = bt if b.grav == 1 else bb
            if il < brr and ir > bl and abs(edge - surface) <= gap:
                # Never cancel a jump that is departing the surface.
                if b.grav == 1 and b.vy >= 0:
                    b.on_ground = True
                    b.y = bt - size
                    b.vy = 0.0
                elif b.grav == -1 and b.vy <= 0:
                    b.on_ground = True
                    b.y = bb
                    b.vy = 0.0
                return

    # ---- slopes ----------------------------------------------------------
    @staticmethod
    def _slope_orientation(o):
        """``r // 90`` mod 4: 0 = / floor, 1 = \\ floor, 2 = \\ ceiling,
        3 = / ceiling."""
        try:
            r = float(o.get("r", 0))
        except (TypeError, ValueError):
            r = 0.0
        return int(round(r / 90.0)) % 4

    def _slope_surface_y(self, o, player_left, player_right):
        # Scaled around the cell centre, same convention as cell_rect /
        # slab_rect, so a scaled slope's collision surface tracks its
        # rendered footprint instead of always using the base cell.
        sx, sy = obj_scale(o)
        cx = o["x"] * CELL + CELL / 2.0
        cy = o["y"] * CELL + CELL / 2.0
        w = CELL * sx
        h = CELL * sy
        cell_left = cx - w / 2.0
        cell_right = cx + w / 2.0
        px_l = max(player_left, cell_left)
        px_r = min(player_right, cell_right)
        if px_l > px_r:
            return None
        cell_top = cy - h / 2.0
        r = self._slope_orientation(o)
        x = px_r if r in (0, 3) else px_l
        t = min(1.0, max(0.0, (x - cell_left) / w)) if w else 0.0
        if r in (0, 2):
            surface_y = cell_top + (1.0 - t) * h
        else:
            surface_y = cell_top + t * h
        return surface_y, r >= 2

    def _resolve_slopes(self, b):
        """Snap the body onto the most constraining nearby slope surface."""
        if not self._has_slopes:
            return
        size = b.size
        px = round(self.x)
        py = round(b.y)
        left = float(self.x)
        right = float(self.x + size)
        best_floor = None
        best_ceiling = None
        for o in self._nearby_for_aabb(px, py, px + size, py + size):
            if o["t"] != T_SLOPE:
                continue
            res = self._slope_surface_y(o, left, right)
            if res is None:
                continue
            surface_y, is_ceiling = res
            if not is_ceiling:
                if best_floor is None or surface_y < best_floor:
                    best_floor = surface_y
            elif best_ceiling is None or surface_y > best_ceiling:
                best_ceiling = surface_y
        if best_floor is not None:
            bottom = b.y + size
            if best_floor < bottom <= best_floor + CELL + 4:
                if b.mode == MODE_WAVE and not self._letter_block_nearby(px, py, size, T_WAVE_BLOCK):
                    self._kill(b, "Hit a slope")
                    if not self.noclip:
                        return
                b.y = best_floor - size
                if b.vy * b.grav > 0:
                    b.vy = 0.0
                if b.grav == 1:
                    b.on_ground = True
        if best_ceiling is not None:
            if best_ceiling - CELL - 4 <= b.y < best_ceiling:
                if b.mode == MODE_WAVE and not self._letter_block_nearby(px, py, size, T_WAVE_BLOCK):
                    self._kill(b, "Hit a slope")
                    if not self.noclip:
                        return
                b.y = best_ceiling
                if b.vy * b.grav > 0:
                    b.vy = 0.0
                if b.grav == -1:
                    b.on_ground = True

    # ---- hazards ---------------------------------------------------------
    @staticmethod
    def _spike_aabbs(o):
        sphbs = o.get("_sphb_aabbs")
        if sphbs is None:
            sphbs = [(r.left, r.top, r.right, r.bottom) for r in
                     spike_hitboxes(o["x"], o["y"], o.get("r", 0),
                                    o["t"] == T_HALF_SPIKE, obj_scale(o))]
            o["_sphb_aabbs"] = sphbs
        return sphbs

    @staticmethod
    def _saw_aabb(o):
        saabb = o.get("_saw_aabb")
        if saabb is None:
            r = saw_hitbox(o["x"], o["y"], obj_scale(o))
            saabb = (r.left, r.top, r.right, r.bottom)
            o["_saw_aabb"] = saabb
        return saabb

    def _hazard_hit(self, o, hz, corners):
        """True if hazard ``o`` overlaps the hazard box ``hz``
        (``(l, t, r, b)``), refined by the rotated outer OBB when given."""
        t = o["t"]
        if t in (T_SPIKE, T_HALF_SPIKE):
            aabbs = self._spike_aabbs(o)
        elif t == T_SAW:
            aabbs = (self._saw_aabb(o),)
        else:
            return False
        hl, ht, hr, hb = hz
        for sl, st, sr, sb in aabbs:
            if not (hl < sr and hr > sl and ht < sb and hb > st):
                continue
            if corners is not None and not obb_aabb_overlap(
                    corners, sl, st, sr, sb):
                continue
            return True
        return False

    def _swept_hazard_death(self, b, x0, y0, x1, y1):
        """Kill ``b`` if the swept box between two poses crosses a hazard
        (used by instantaneous teleports)."""
        size = b.size
        shrink = max(2, int(6 * size / PLAYER_SIZE))
        l = min(round(x0), round(x1)) + shrink
        t = min(round(y0), round(y1)) + shrink
        r = max(round(x0), round(x1)) + size - shrink
        bt = max(round(y0), round(y1)) + size - shrink
        for o in self._nearby_for_aabb(l - 3, t - 3, r + 3, bt + 3, 2):
            if self._hazard_hit(o, (l, t, r, bt), None):
                reason = ("Teleported into a saw" if o["t"] == T_SAW
                          else "Teleported into a spike")
                self._kill(b, reason)
                return True
        return False

    # ---- spider teleport target search ----------------------------------
    def _find_spider_surface(self, b, direction):
        """Nearest block surface from body ``b`` in ``direction``.
        Returns ``(new_x, new_y)`` or ``None``."""
        dx, dy = direction
        size = b.size
        pl = round(self.x)
        pr = pl + size
        pt = round(b.y)
        pb = pt + size
        best = None
        solid_rect = self._solid_rect
        if dy != 0 and dx == 0:
            lc = pl // CELL - 1
            rc = (pr - 1) // CELL + 1
            for (gx, _gy), bucket in self._spatial_index.items():
                if gx < lc or gx > rc:
                    continue
                for o in bucket:
                    br = solid_rect(o)
                    if br is None:
                        continue
                    bl, bt, brr, bb = br
                    if not (bl < pr and brr > pl):
                        continue
                    if dy < 0 and bb <= pt:
                        d = pt - bb
                        if best is None or d < best[0]:
                            best = (d, self.x, float(bb))
                    elif dy > 0 and bt >= pb:
                        d = bt - pb
                        if best is None or d < best[0]:
                            best = (d, self.x, float(bt - size))
        elif dx != 0 and dy == 0:
            tc = pt // CELL - 1
            bc = (pb - 1) // CELL + 1
            for (_gx, gy), bucket in self._spatial_index.items():
                if gy < tc or gy > bc:
                    continue
                for o in bucket:
                    br = solid_rect(o)
                    if br is None:
                        continue
                    bl, bt, brr, bb = br
                    if not (bt < pb and bb > pt):
                        continue
                    if dx > 0 and bl >= pr:
                        d = bl - pr
                        if best is None or d < best[0]:
                            best = (d, float(bl - size), b.y)
                    elif dx < 0 and brr <= pl:
                        d = pl - brr
                        if best is None or d < best[0]:
                            best = (d, float(brr), b.y)
        if best is None:
            return None
        return best[1], best[2]
