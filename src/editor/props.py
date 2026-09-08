"""Registry-driven object property panel ("Edit Object").

Every row comes from the object's :class:`objects.ObjectSpec` fields, so
a new object type with new parameters gets an editable panel with no
editor code.  A few rows are special: rotation / scale (every object),
the move-trigger speed curve, stack order, link buttons and the
invisible / bot-only flags.
"""

import pygame

from ..constants import (
    WIDTH, C_WHITE, C_GRAY, C_BTN, C_DANGER, MOVE_CURVE_SPEED_MAX,
    T_MOVE_TRIGGER, T_ROTATE_TRIGGER, T_FOLLOW_TRIGGER, TELEPORT_LINK_TYPES,
    T_COLOR_TRIGGER, T_PULSE_TRIGGER,
)
from ..graphics import txt, draw_obj, lighter
from ..geometry import obj_scale, normalize_rotation
from ..objects import (
    spec_for, get_field_value, set_active_start, TYPE_NAMES,
)
from ..levels import get_groups
from .state import TOP_H, BAR_Y
from . import ops

PANEL_W = 244
PANEL_X = WIDTH - PANEL_W - 8
PANEL_Y = TOP_H + 8
ROW_H = 30
HEADER_H = 104
CURVE_H = 96
CURVE_PAD = 8
CURVE_HIT_R2 = 100


def _parse_groups_text(text):
    """"1, 2,3" -> sorted unique positive ints; malformed tokens ignored."""
    out = set()
    for tok in text.replace(",", " ").split():
        try:
            g = int(tok)
        except ValueError:
            continue
        if g > 0:
            out.add(g)
    return sorted(out)


class Row:
    __slots__ = ("kind", "key", "label", "rect", "minus", "plus", "field",
                 "action", "arg")

    def __init__(self, kind, key, label, rect, minus=None, plus=None,
                 field=None, action=None, arg=None):
        self.kind = kind
        self.key = key
        self.label = label
        self.rect = rect
        self.minus = minus
        self.plus = plus
        self.field = field
        self.action = action
        self.arg = arg


def _value_row(y, key, label, field=None):
    box = pygame.Rect(PANEL_X + 92, y + 3, PANEL_W - 92 - 62, ROW_H - 6)
    minus = pygame.Rect(box.right + 4, y + 3, 26, ROW_H - 6)
    plus = pygame.Rect(minus.right + 4, y + 3, 26, ROW_H - 6)
    return Row("value", key, label, box, minus, plus, field)


def _toggle_row(y, key, label, field=None):
    return Row("toggle", key, label, pygame.Rect(PANEL_X + 12, y + 3, PANEL_W - 24, ROW_H - 6), field=field)


def _button_row(y, label, action, arg=None, color=C_BTN):
    r = Row("button", None, label, pygame.Rect(PANEL_X + 12, y + 3, PANEL_W - 24, ROW_H - 6), action=action, arg=arg)
    r.field = color
    return r


class PropPanel:
    def __init__(self):
        self.rows = []
        self.rect = pygame.Rect(PANEL_X, PANEL_Y, PANEL_W, 0)
        self.shared_type = None

    # ---- layout ----------------------------------------------------------
    def layout(self, st):
        objs = st.selected
        self.rows = []
        if not objs:
            self.rect.h = 0
            return
        t = ops.shared_type(objs)
        self.shared_type = t
        single = objs[0] if len(objs) == 1 else None
        y = PANEL_Y + HEADER_H
        self.rows.append(_value_row(y, "r", "Rotation"))
        y += ROW_H
        self.rows.append(_value_row(y, "scale", "Scale"))
        y += ROW_H
        self.rows.append(_value_row(y, "groups", "Groups"))
        y += ROW_H
        if single is not None:
            stack = ops.objects_at_cell(st.objects, single["x"], single["y"])
            if len(stack) > 1:
                r = Row("stack", None, "Stack", pygame.Rect(PANEL_X + 12, y + 3, PANEL_W - 24, ROW_H - 6))
                r.minus = pygame.Rect(PANEL_X + 12, y + 3, 28, ROW_H - 6)
                r.plus = pygame.Rect(PANEL_X + PANEL_W - 40, y + 3, 28, ROW_H - 6)
                self.rows.append(r)
                y += ROW_H
        if t is not None:
            spec = spec_for(t)
            for f in spec.fields:
                if f.kind == "bool":
                    self.rows.append(_toggle_row(y, f.key, f.label, f))
                else:
                    self.rows.append(_value_row(y, f.key, f.label, f))
                y += ROW_H
                if f.default_from:
                    # Fields like "Target row" / "Spawn row" snapshot the
                    # object's own x/y at placement time and don't follow it
                    # if the object is later moved (e.g. by a Move Trigger)
                    # — this re-snaps them to the object's current cell.
                    self.rows.append(_button_row(
                        y, f"Resync {f.label} to current pos",
                        "sync_field", arg=(f.key, f.default_from),
                        color=(80, 90, 60)))
                    y += ROW_H
            if t in (T_MOVE_TRIGGER, T_ROTATE_TRIGGER, T_FOLLOW_TRIGGER):
                self.rows.append(_button_row(y, "Set targets (Link tool)", "link", color=(120, 80, 190)))
                y += ROW_H
            elif t in TELEPORT_LINK_TYPES:
                self.rows.append(_button_row(y, "Link partner orb/portal", "link", color=(120, 80, 190)))
                y += ROW_H
            if t in (T_COLOR_TRIGGER, T_PULSE_TRIGGER):
                self.rows.append(_button_row(y, "Edit this channel's color", "edit_channel", color=(160, 100, 60)))
                y += ROW_H
            if single is not None and t == T_MOVE_TRIGGER:
                self.rows.append(Row("curve", "curve", "Speed curve",
                                     pygame.Rect(PANEL_X + 12, y + 14, PANEL_W - 24, CURVE_H)))
                y += CURVE_H + 20
        self.rows.append(_toggle_row(y, "invisible", "Invisible"))
        y += ROW_H
        self.rows.append(_toggle_row(y, "_bot_only", "Bot-only (phantom)"))
        y += ROW_H
        self.rows.append(_button_row(y, "Delete [Del]", "delete", color=C_DANGER))
        y += ROW_H
        self.rows.append(_button_row(y, "Close", "close", color=(50, 50, 70)))
        y += ROW_H + 6
        self.rect = pygame.Rect(PANEL_X, PANEL_Y, PANEL_W, min(y - PANEL_Y, BAR_Y - PANEL_Y - 6))

    def contains(self, pos):
        return self.rect.h > 0 and self.rect.collidepoint(pos)

    # ---- value helpers ---------------------------------------------------
    @staticmethod
    def _rotation_text(objs):
        vals = {round(float(o.get("r", 0)), 3) for o in objs}
        if len(vals) > 1:
            return "Mixed"
        v = vals.pop()
        return f"{int(v)}°" if abs(v - round(v)) < 1e-3 else f"{v:.1f}°"

    @staticmethod
    def _scale_text(objs):
        vals = {(round(obj_scale(o)[0], 3), round(obj_scale(o)[1], 3)) for o in objs}
        if len(vals) > 1:
            return "Mixed"
        sx, sy = vals.pop()
        return f"{sx:.2f}x" if abs(sx - sy) < 1e-6 else f"{sx:.2f} x {sy:.2f}"

    @staticmethod
    def _groups_text(objs):
        vals = {tuple(get_groups(o)) for o in objs}
        if len(vals) > 1:
            return "Mixed"
        groups = vals.pop()
        return ",".join(str(g) for g in groups) if groups else "None"

    @staticmethod
    def _field_text(objs, f):
        vals = {repr(get_field_value(o, f)) for o in objs}
        if len(vals) > 1:
            return "Mixed"
        return f.format(get_field_value(objs[0], f))

    # ---- drawing ---------------------------------------------------------
    def draw(self, screen, st, mpos):
        objs = st.selected
        if not objs or self.rect.h <= 0:
            return
        prev_clip = screen.get_clip()
        pygame.draw.rect(screen, (18, 14, 36), self.rect, border_radius=8)
        pygame.draw.rect(screen, (70, 170, 110) if len(objs) > 1 else (70, 90, 170),
                         self.rect, 2, border_radius=8)
        screen.set_clip(self.rect)
        t = self.shared_type
        obj = objs[0]
        title = f"EDIT {len(objs)} OBJECTS" if len(objs) > 1 else "EDIT OBJECT"
        txt(screen, title, self.rect.centerx, PANEL_Y + 16, 16, C_WHITE, True)
        pv = pygame.Rect(PANEL_X + 14, PANEL_Y + 30, 60, 60)
        pygame.draw.rect(screen, (10, 8, 24), pv, border_radius=6)
        if t is None:
            txt(screen, "MIXED", pv.centerx, pv.centery, 14, C_GRAY, True)
        else:
            draw_obj(screen, t, pv.x + 6, pv.y + 6, 48, st.pulse, obj.get("r", 0), obj,
                     scale=obj_scale(obj))
        name = TYPE_NAMES.get(t, t) if t else "Mixed types"
        txt(screen, name, pv.right + 10, PANEL_Y + 36, 15, C_WHITE)
        sub = (f"{len(objs)} selected" if len(objs) > 1
               else f"cell ({obj['x']}, {obj['y']})"
               + (f"   oid {obj['oid']}" if obj.get("oid") else ""))
        txt(screen, sub, pv.right + 10, PANEL_Y + 58, 12, C_GRAY)
        if t and spec_for(t).tip:
            txt(screen, spec_for(t).tip[:38], pv.right + 10, PANEL_Y + 76, 10, C_GRAY)
        for row in self.rows:
            self._draw_row(screen, st, row, objs, mpos)
        screen.set_clip(prev_clip)

    def _draw_box(self, screen, rect, text, mpos, base=C_BTN, size=13):
        c = lighter(base, 30) if rect.collidepoint(mpos) else base
        pygame.draw.rect(screen, c, rect, border_radius=4)
        pygame.draw.rect(screen, lighter(c, 40), rect, 1, border_radius=4)
        txt(screen, text, rect.centerx, rect.centery, size, C_WHITE, True)

    def _draw_row(self, screen, st, row, objs, mpos):
        if row.kind == "value":
            txt(screen, row.label, PANEL_X + 12, row.rect.centery - 7, 12, C_GRAY)
            if row.key == "r":
                text = self._rotation_text(objs)
            elif row.key == "scale":
                text = self._scale_text(objs)
            elif row.key == "groups":
                text = self._groups_text(objs)
            else:
                text = self._field_text(objs, row.field)
            self._draw_box(screen, row.rect, text, mpos)
            self._draw_box(screen, row.minus, "-", mpos, (60, 60, 90))
            self._draw_box(screen, row.plus, "+", mpos, (60, 60, 90))
        elif row.kind == "toggle":
            if row.field is not None:
                vals = {bool(get_field_value(o, row.field)) for o in objs}
            else:
                vals = {bool(o.get(row.key)) for o in objs}
            state = "Mixed" if len(vals) > 1 else ("ON" if vals.pop() else "OFF")
            on = state == "ON"
            base = (60, 140, 80) if on else (50, 50, 70)
            self._draw_box(screen, row.rect, f"{row.label}: {state}", mpos, base)
        elif row.kind == "button":
            self._draw_box(screen, row.rect, row.label, mpos, row.field or C_BTN)
        elif row.kind == "stack":
            single = objs[0]
            stack = ops.objects_at_cell(st.objects, single["x"], single["y"])
            found = ops.index_by_id(stack, single)
            idx = found + 1 if found != -1 else 0
            txt(screen, f"Stack {idx}/{len(stack)}  (F/B: to front / back)",
                row.rect.centerx, row.rect.centery, 11, C_WHITE, True)
            self._draw_box(screen, row.minus, "<", mpos, (60, 60, 90))
            self._draw_box(screen, row.plus, ">", mpos, (60, 60, 90))
        elif row.kind == "curve":
            self._draw_curve(screen, row.rect, objs[0])

    def _draw_curve(self, screen, cr, obj):
        txt(screen, "Speed curve: click add · drag move · right-click delete",
            cr.centerx, cr.y - 8, 9, C_GRAY, True)
        pygame.draw.rect(screen, (10, 8, 22), cr, border_radius=4)
        pygame.draw.rect(screen, (70, 90, 160), cr, 1, border_radius=4)
        x0, y0 = cr.x + CURVE_PAD, cr.y + CURVE_PAD
        x1, y1 = cr.right - CURVE_PAD, cr.bottom - CURVE_PAD
        for i in range(1, 4):
            ly = y0 + (y1 - y0) * i / 4
            lx = x0 + (x1 - x0) * i / 4
            pygame.draw.line(screen, (30, 32, 60), (x0, ly), (x1, ly), 1)
            pygame.draw.line(screen, (30, 32, 60), (lx, y0), (lx, y1), 1)
        y_one = y0 + (1.0 - 1.0 / MOVE_CURVE_SPEED_MAX) * (y1 - y0)
        pygame.draw.line(screen, (70, 80, 130), (x0, y_one), (x1, y_one), 1)
        curve = ops.ensure_curve(obj)
        pts = [self.curve_point_to_px(cr, p[0], p[1]) for p in sorted(curve, key=lambda p: p[0])]
        if len(pts) >= 2:
            fill = pygame.Surface((cr.w, cr.h), pygame.SRCALPHA)
            poly = [(pts[0][0] - cr.x, y1 - cr.y)] + [(px - cr.x, py - cr.y) for px, py in pts] + [(pts[-1][0] - cr.x, y1 - cr.y)]
            pygame.draw.polygon(fill, (255, 180, 80, 45), poly)
            screen.blit(fill, cr.topleft)
            pygame.draw.lines(screen, (255, 200, 100), False, pts, 2)
        for i, sp in enumerate(pts):
            col = (255, 230, 160) if i in (0, len(pts) - 1) else (255, 200, 100)
            pygame.draw.circle(screen, (10, 6, 22), sp, 6)
            pygame.draw.circle(screen, col, sp, 4)

    @staticmethod
    def curve_point_to_px(rect, t, s):
        w = rect.w - 2 * CURVE_PAD
        h = rect.h - 2 * CURVE_PAD
        px = rect.x + CURVE_PAD + t * w
        py = rect.y + CURVE_PAD + (1.0 - min(MOVE_CURVE_SPEED_MAX, max(0.0, s)) / MOVE_CURVE_SPEED_MAX) * h
        return int(round(px)), int(round(py))

    @staticmethod
    def px_to_curve_point(rect, px, py):
        w = max(1, rect.w - 2 * CURVE_PAD)
        h = max(1, rect.h - 2 * CURVE_PAD)
        t = (px - rect.x - CURVE_PAD) / w
        s = (1.0 - (py - rect.y - CURVE_PAD) / h) * MOVE_CURVE_SPEED_MAX
        return max(0.0, min(1.0, t)), max(0.0, min(MOVE_CURVE_SPEED_MAX, s))

    # ---- interaction -------------------------------------------------------
    def click(self, st, pos, session, button=1):
        """Handle a mouse press inside the panel.  Returns True if the
        panel consumed the click."""
        if not self.contains(pos):
            return False
        objs = st.selected
        for row in self.rows:
            if row.kind == "value":
                if row.rect.collidepoint(pos):
                    self._type_value(st, row, objs, session)
                elif row.minus and row.minus.collidepoint(pos):
                    self._nudge(st, row, objs, -1)
                elif row.plus and row.plus.collidepoint(pos):
                    self._nudge(st, row, objs, 1)
                else:
                    continue
                return True
            if row.kind == "toggle" and row.rect.collidepoint(pos):
                st.push_undo()
                if row.field is not None:
                    new = any(not get_field_value(o, row.field) for o in objs)
                    for o in objs:
                        o[row.key] = new
                    if row.key == "active" and new:
                        # Only one Start Pos may be active at a time.
                        set_active_start(st.objects, objs[0])
                else:
                    ops.toggle_flag(objs, row.key)
                return True
            if row.kind == "button" and row.rect.collidepoint(pos):
                session.panel_action(row.action, row.arg)
                return True
            if row.kind == "stack":
                single = objs[0]
                stack = ops.objects_at_cell(st.objects, single["x"], single["y"])
                idx = ops.index_by_id(stack, single)
                if row.minus.collidepoint(pos) and idx != -1:
                    st.selected = [stack[(idx - 1) % len(stack)]]
                elif row.plus.collidepoint(pos) and idx != -1:
                    st.selected = [stack[(idx + 1) % len(stack)]]
                elif row.rect.collidepoint(pos):
                    return True
                else:
                    continue
                return True
            if row.kind == "curve" and row.rect.collidepoint(pos):
                self._curve_press(st, row.rect, objs[0], pos, button)
                return True
        return True

    def _type_value(self, st, row, objs, session):
        obj = objs[0]
        if row.key == "r":
            cur = float(obj.get("r", 0))
            typed = session.ask_text("Rotation (deg):",
                                     str(int(cur)) if abs(cur - round(cur)) < 1e-3 else f"{cur:.1f}")
            if typed is None:
                return
            v = ops.parse_rotation_text(typed)
            if v is None:
                return
            st.push_undo()
            for o in objs:
                o["r"] = v
        elif row.key == "scale":
            sx, sy = obj_scale(obj)
            typed = session.ask_text("Scale (1.5  or  1.5,0.75):",
                                     f"{sx:.2f}" if abs(sx - sy) < 1e-6 else f"{sx:.2f},{sy:.2f}")
            if typed is None:
                return
            parsed = ops.parse_scale_text(typed)
            if parsed is None:
                return
            st.push_undo()
            for o in objs:
                ops.set_scale(o, *parsed)
        elif row.key == "groups":
            typed = session.ask_text("Groups (comma-separated ids, blank = none):",
                                     ",".join(str(g) for g in get_groups(obj)))
            if typed is None:
                return
            groups = _parse_groups_text(typed)
            st.push_undo()
            for o in objs:
                if groups:
                    o["groups"] = list(groups)
                else:
                    o.pop("groups", None)
                o.pop("group", None)
        else:
            f = row.field
            typed = session.ask_text(f"{f.label}:", f.format(get_field_value(obj, f)))
            if typed is None or not typed.strip():
                return
            st.push_undo()
            for o in objs:
                o[f.key] = f.coerce(typed, get_field_value(o, f))

    def _nudge(self, st, row, objs, direction):
        st.push_undo()
        if row.key == "r":
            for o in objs:
                o["r"] = normalize_rotation(float(o.get("r", 0)) + 90 * direction)
        elif row.key == "scale":
            ops.scale_objects(objs, direction)
        elif row.key == "groups":
            # + adds the next unused small group id to every selected
            # object; - drops each object's own highest group id.
            for o in objs:
                groups = get_groups(o)
                if direction > 0:
                    existing = set(groups)
                    gid = 1
                    while gid in existing:
                        gid += 1
                    groups = sorted(existing | {gid})
                elif groups:
                    groups = groups[:-1]
                if groups:
                    o["groups"] = groups
                else:
                    o.pop("groups", None)
                o.pop("group", None)
        else:
            f = row.field
            for o in objs:
                o[f.key] = f.nudge(get_field_value(o, f), direction)

    def _curve_press(self, st, cr, obj, pos, button):
        curve = ops.ensure_curve(obj)
        hit_idx = None
        for i, p in enumerate(curve):
            sp = self.curve_point_to_px(cr, p[0], p[1])
            if (sp[0] - pos[0]) ** 2 + (sp[1] - pos[1]) ** 2 <= CURVE_HIT_R2:
                hit_idx = i
                break
        if button == 3:
            if hit_idx is not None and 0 < hit_idx < len(curve) - 1:
                st.push_undo()
                curve.pop(hit_idx)
            return
        if hit_idx is not None:
            st.curve_drag_idx = hit_idx
            return
        st.push_undo()
        nt, ns = self.px_to_curve_point(cr, *pos)
        insert_at = len(curve) - 1
        for i, p in enumerate(curve):
            if p[0] > nt:
                insert_at = max(1, i)
                break
        curve.insert(insert_at, [nt, ns])
        st.curve_drag_idx = insert_at

    def curve_drag(self, st, mpos):
        """Called every frame while the mouse is held with a curve point
        grabbed."""
        if st.curve_drag_idx is None or len(st.selected) != 1:
            return
        row = next((r for r in self.rows if r.kind == "curve"), None)
        if row is None:
            st.curve_drag_idx = None
            return
        curve = ops.ensure_curve(st.selected[0])
        i = st.curve_drag_idx
        if not 0 <= i < len(curve):
            st.curve_drag_idx = None
            return
        nt, ns = self.px_to_curve_point(row.rect, *mpos)
        if i == 0:
            curve[0] = [0.0, ns]
        elif i == len(curve) - 1:
            curve[-1] = [1.0, ns]
        else:
            nt = max(curve[i - 1][0] + 0.001, min(curve[i + 1][0] - 0.001, nt))
            curve[i] = [nt, ns]
        st.mark_dirty()
