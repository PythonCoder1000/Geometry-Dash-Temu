"""Editor chrome: top bar, left tool strip, GD-style bottom bar.

Layouts are computed each frame from the state so the same rect list is
used for drawing and for hit-testing.  A :class:`Button` carries an
``action`` string the session dispatches on.
"""

import pygame

from ..constants import (
    WIDTH, HEIGHT, C_WHITE, C_GRAY, C_BTN, C_DANGER, C_PUBLISH, C_GRID,
    T_TELEPORT_ORB,
)
from ..graphics import txt, draw_obj, lighter, darker
from ..objects import PALETTE_CATEGORIES, TYPE_NAMES, TYPE_TIPS
from .state import (
    MODE_BUILD, MODE_EDIT, MODE_DELETE, TOOL_LINK,
    TOOL_BOT_PATH, TOP_H, BAR_Y, SIDE_W,
)
from . import music_names  # noqa: F401  (import side effect free)

C_PANEL = (18, 16, 36)
C_PANEL_EDGE = (60, 70, 120)
C_MODE_BUILD = (60, 110, 210)
C_MODE_EDIT = (70, 160, 100)
C_MODE_DELETE = (200, 70, 70)
C_TOGGLE_ON = (70, 150, 220)
C_TOGGLE_OFF = (46, 48, 74)

# Bottom bar geometry.
MODE_COL_X = 8
MODE_COL_W = 84
CONTENT_X = MODE_COL_X + MODE_COL_W + 10
CONTENT_W = WIDTH - CONTENT_X - 10
PAL_TAB_H = 24
PAL_ITEM = 50
PAL_GAP = 6
PAL_ROWS = 2


class Button:
    __slots__ = ("rect", "label", "action", "color", "active", "arg",
                 "sprite", "tip", "small", "disabled")

    def __init__(self, rect, label, action, color=C_BTN, active=False,
                 arg=None, sprite=None, tip="", small=False, disabled=False):
        self.rect = rect
        self.label = label
        self.action = action
        self.color = color
        self.active = active
        self.arg = arg
        self.sprite = sprite
        self.tip = tip
        self.small = small
        self.disabled = disabled


def draw_button(screen, b, mpos, pulse=0):
    r = b.rect
    hov = r.collidepoint(mpos) and not b.disabled
    col = b.color
    if b.disabled:
        col = darker(col, 60)
    elif b.active:
        col = lighter(col, 35)
    elif hov:
        col = lighter(col, 20)
    pygame.draw.rect(screen, darker(col, 45), r.move(0, 2), border_radius=6)
    pygame.draw.rect(screen, col, r, border_radius=6)
    if b.active:
        pygame.draw.rect(screen, C_WHITE, r, 2, border_radius=6)
    if b.sprite is not None:
        s = min(r.w, r.h) - 6
        draw_obj(screen, b.sprite, r.x + (r.w - s) // 2, r.y + (r.h - s) // 2,
                 s, pulse, 0)
    if b.label:
        size = 11 if b.small else 13
        txt(screen, b.label, r.centerx, r.centery, size,
            C_GRAY if b.disabled else C_WHITE, True)


def hit(buttons, pos):
    for b in buttons:
        if not b.disabled and b.rect.collidepoint(pos):
            return b
    return None


# ---------------------------------------------------------------------------
# Top bar
# ---------------------------------------------------------------------------

def layout_top(st):
    bts = []
    x = 8
    for label, action, col, w in (
            ("Menu", "menu", C_DANGER, 64), ("Test [T]", "test", (40, 130, 80), 76),
            ("Bot", "bot_menu", (180, 120, 30), 56)):
        bts.append(Button(pygame.Rect(x, 6, w, 32), label, action, col))
        x += w + 6
    x = WIDTH - 8
    right = [
        ("?", "help", (60, 60, 90), 30),
        ("SFX", "mute_sfx", (80, 60, 140), 44),
        ("Music", "mute_music", (80, 60, 140), 52),
        ("Track", "cycle_music", (80, 60, 140), 56),
        ("Load", "load", C_BTN, 56),
        ("Publish", "publish", C_PUBLISH, 66),
        ("Save [S]", "save", C_BTN, 70),
        ("Redo", "redo", (60, 60, 90), 52),
        ("Undo", "undo", (60, 60, 90), 52),
    ]
    for label, action, col, w in right:
        x -= w
        b = Button(pygame.Rect(x, 6, w, 32), label, action, col)
        if action == "undo":
            b.disabled = not st.undo_stack
        elif action == "redo":
            b.disabled = not st.redo_stack
        bts.append(b)
        x -= 6
    return bts


def draw_top(screen, st, buttons, mpos):
    from .. import music, sfx
    pygame.draw.rect(screen, C_PANEL, (0, 0, WIDTH, TOP_H))
    pygame.draw.line(screen, C_GRID, (0, TOP_H), (WIDTH, TOP_H), 1)
    for b in buttons:
        if b.action == "mute_music":
            b.active = music.is_muted()
            b.label = "Music" + (" x" if music.is_muted() else "")
        elif b.action == "mute_sfx":
            b.active = sfx.is_muted()
            b.label = "SFX" + (" x" if sfx.is_muted() else "")
        draw_button(screen, b, mpos)
    # Level status in the middle.
    status = [st.level_name]
    if st.unsaved_changes:
        status.append("unsaved")
    if st.level_meta:
        if st.level_meta.get("verified"):
            status.append("verified")
        elif st.level_meta.get("published"):
            status.append("published")
    if st.level_music:
        status.append("music: " + music_names.track_label(st.level_music))
    txt(screen, "  ·  ".join(status), 420, 12, 14, C_WHITE)
    txt(screen, f"{len(st.objects)} objects  ·  zoom {st.zoom:.1f}x",
        420, 28, 11, C_GRAY)


# ---------------------------------------------------------------------------
# Left strip
# ---------------------------------------------------------------------------

def layout_side(st):
    bts = []
    y = TOP_H + 10
    items = [
        ("Swipe", "toggle_swipe", st.swipe),
        ("Rotate", "toggle_rotate", st.rotate_drag),
        ("Free", "toggle_free", st.free_move),
        ("Grid", "toggle_grid", st.show_grid),
        ("Hitbox", "toggle_hitbox", st.show_hitboxes),
        ("Zoom +", "zoom_in", False),
        ("Zoom -", "zoom_out", False),
        ("1:1", "zoom_reset", False),
    ]
    for label, action, active in items:
        bts.append(Button(pygame.Rect(6, y, SIDE_W - 12, 36), label, action,
                          C_TOGGLE_ON if active else C_TOGGLE_OFF, active=active,
                          small=True))
        y += 42
    return bts


def draw_side(screen, buttons, mpos):
    pygame.draw.rect(screen, (14, 12, 28), (0, TOP_H, SIDE_W, BAR_Y - TOP_H))
    pygame.draw.line(screen, C_GRID, (SIDE_W, TOP_H), (SIDE_W, BAR_Y), 1)
    for b in buttons:
        draw_button(screen, b, mpos)


# ---------------------------------------------------------------------------
# Bottom bar
# ---------------------------------------------------------------------------

def _mode_buttons(st):
    out = []
    h = (HEIGHT - BAR_Y - 16) // 3 - 4
    y = BAR_Y + 8
    for label, mode, col in (("BUILD", MODE_BUILD, C_MODE_BUILD),
                             ("EDIT", MODE_EDIT, C_MODE_EDIT),
                             ("DELETE", MODE_DELETE, C_MODE_DELETE)):
        out.append(Button(pygame.Rect(MODE_COL_X, y, MODE_COL_W, h), label,
                          "mode", col, active=st.mode == mode, arg=mode))
        y += h + 4
    return out


def palette_page_size():
    cols = (CONTENT_W - 60) // (PAL_ITEM + PAL_GAP)
    return cols * PAL_ROWS, cols


def _build_buttons(st):
    out = []
    # Category tabs.
    x = CONTENT_X
    y = BAR_Y + 6
    for i, (name, _items) in enumerate(PALETTE_CATEGORIES):
        w = 78 if len(name) > 5 else 64
        out.append(Button(pygame.Rect(x, y, w, PAL_TAB_H), name, "category",
                          (40, 60, 140), active=i == st.active_cat, arg=i,
                          small=True))
        x += w + 4
    # Object grid.
    items = st.palette_items()
    per_page, cols = palette_page_size()
    pages = max(1, (len(items) + per_page - 1) // per_page)
    st.palette_page = min(st.palette_page, pages - 1)
    start = st.palette_page * per_page
    gy0 = y + PAL_TAB_H + 8
    for k, t in enumerate(items[start:start + per_page]):
        r = k // cols
        c = k % cols
        rect = pygame.Rect(CONTENT_X + c * (PAL_ITEM + PAL_GAP),
                           gy0 + r * (PAL_ITEM + PAL_GAP), PAL_ITEM, PAL_ITEM)
        out.append(Button(rect, "", "pick", (30, 34, 70),
                          active=st.selected_type == t, arg=t, sprite=t,
                          tip=TYPE_NAMES.get(t, t)))
    # Page arrows.
    ax = WIDTH - 10 - 24
    out.append(Button(pygame.Rect(ax, gy0, 24, PAL_ITEM), ">", "page", (50, 50, 80),
                      arg=1, disabled=st.palette_page >= pages - 1))
    out.append(Button(pygame.Rect(ax, gy0 + PAL_ITEM + PAL_GAP, 24, PAL_ITEM), "<",
                      "page", (50, 50, 80), arg=-1, disabled=st.palette_page <= 0))
    # Brush rotation.
    rx = ax - 30 - 48
    out.append(Button(pygame.Rect(rx, gy0, 48, PAL_ITEM), f"{st.rotation}°",
                      "brush_rot", (60, 60, 90), small=True))
    out.append(Button(pygame.Rect(rx, gy0 + PAL_ITEM + PAL_GAP, 22, PAL_ITEM), "-",
                      "brush_rot_ccw", (60, 60, 90)))
    out.append(Button(pygame.Rect(rx + 26, gy0 + PAL_ITEM + PAL_GAP, 22, PAL_ITEM),
                      "+", "brush_rot_cw", (60, 60, 90)))
    return out


def _edit_buttons(st):
    out = []
    has_sel = bool(st.selected)
    y0 = BAR_Y + 8
    bw, bh, gap = 82, 30, 6
    rows = [
        [("Rot -90", "rot", -90), ("Rot +90", "rot", 90), ("Rot -45", "rot", -45),
         ("Rot +45", "rot", 45), ("Flip H", "flip", "h"), ("Flip V", "flip", "v"),
         ("Scale -", "scale", -1), ("Scale +", "scale", 1)],
        [("Copy", "copy", None), ("Paste", "paste", None), ("Duplicate", "duplicate", None),
         ("Select All", "select_all", None), ("Deselect", "deselect", None),
         ("Invisible", "toggle_invisible", None), ("Bot-only", "toggle_bot_only", None),
         ("Delete", "delete_sel", None)],
        [("Edit Object", "props", None), ("Link", "tool", TOOL_LINK),
         ("Bot Path", "tool", TOOL_BOT_PATH), ("Snippet", "snippet", None),
         ("Save Snip", "save_snippet", None),
         ("< Nudge", "nudge", (-1, 0)), ("Nudge >", "nudge", (1, 0)),
         ("^ Nudge", "nudge", (0, -1)), ("v Nudge", "nudge", (0, 1))],
    ]
    need_sel = {"rot", "flip", "scale", "copy", "duplicate", "deselect",
                "toggle_invisible", "toggle_bot_only", "delete_sel", "props",
                "nudge", "save_snippet"}
    for ri, row in enumerate(rows):
        x = CONTENT_X
        for label, action, arg in row:
            col = C_BTN
            active = False
            if action == "tool":
                active = st.edit_tool == arg
                col = (120, 80, 190) if arg == TOOL_LINK else (180, 120, 30)
            elif action == "delete_sel":
                col = C_DANGER
            elif action == "props":
                col = C_MODE_EDIT
                active = st.props_open
            elif action == "toggle_invisible":
                active = has_sel and all(o.get("invisible") for o in st.selected)
            elif action == "toggle_bot_only":
                active = has_sel and all(o.get("_bot_only") for o in st.selected)
            w = bw if len(label) <= 9 else bw + 18
            b = Button(pygame.Rect(x, y0 + ri * (bh + gap), w, bh), label,
                       action, col, active=active, arg=arg, small=True,
                       disabled=(action in need_sel and not has_sel)
                       or (action == "paste" and not st.clipboard))
            out.append(b)
            x += w + gap
    return out


def _delete_buttons(st):
    out = []
    y0 = BAR_Y + 8
    x = CONTENT_X
    specs = [
        ("Delete Selected", "delete_sel", C_DANGER, None, not st.selected),
        ("Delete All of Type", "delete_type", C_DANGER, None, False),
        ("Clear Level", "clear", (120, 40, 40), None, False),
        (("Filter: " + TYPE_NAMES.get(st.selected_type, "?")) if st.delete_filter
         else "Filter: All", "toggle_delete_filter", C_TOGGLE_ON if st.delete_filter
         else C_TOGGLE_OFF, None, False),
    ]
    for label, action, col, arg, dis in specs:
        w = 150
        out.append(Button(pygame.Rect(x, y0, w, 34), label, action, col,
                          arg=arg, small=True, disabled=dis))
        x += w + 8
    return out


def layout_bottom(st):
    bts = _mode_buttons(st)
    if st.mode == MODE_BUILD:
        bts += _build_buttons(st)
    elif st.mode == MODE_EDIT:
        bts += _edit_buttons(st)
    else:
        bts += _delete_buttons(st)
    return bts


def draw_bottom(screen, st, buttons, mpos):
    pygame.draw.rect(screen, C_PANEL, (0, BAR_Y, WIDTH, HEIGHT - BAR_Y))
    pygame.draw.line(screen, C_PANEL_EDGE, (0, BAR_Y), (WIDTH, BAR_Y), 2)
    hovered_tip = None
    for b in buttons:
        draw_button(screen, b, mpos, st.pulse)
        if b.action == "pick" and b.rect.collidepoint(mpos):
            hovered_tip = b.arg
    if st.mode == MODE_BUILD:
        name = TYPE_NAMES.get(st.selected_type, st.selected_type)
        txt(screen, f"Placing: {name}   ·   Tab / Shift+Tab: category   ·   "
            f"1-9: pick   ·   R / Q: rotate", CONTENT_X, HEIGHT - 18, 11, C_GRAY)
        if st.selected_type == T_TELEPORT_ORB:
            txt(screen, f"next group {st.group_id_counter}", WIDTH - 140,
                HEIGHT - 18, 11, C_GRAY)
    elif st.mode == MODE_EDIT:
        n = len(st.selected)
        if st.edit_tool == TOOL_LINK:
            hint = "LINK: click a teleport orb / move / rotate / follow trigger, then its partners"
        elif st.edit_tool == TOOL_BOT_PATH:
            hint = f"BOT PATH: click to add waypoints ({len(st.bot_waypoints)}), right-click removes, K runs"
        else:
            hint = (f"{n} selected   ·   click: select (Shift adds)   ·   drag: "
                    + ("marquee" if st.swipe else "pan")
                    + "   ·   drag selection: move   ·   Shift+nudge = 5 cells")
        txt(screen, hint, CONTENT_X, HEIGHT - 18, 11, C_GRAY)
    else:
        txt(screen, "Click / swipe objects to delete them   ·   right-drag pans",
            CONTENT_X, HEIGHT - 18, 11, C_GRAY)
    return hovered_tip


def draw_palette_tooltip(screen, hovered_type, mpos):
    if hovered_type is None:
        return
    name = TYPE_NAMES.get(hovered_type, "")
    tip = TYPE_TIPS.get(hovered_type, "")
    w = 280
    x = min(WIDTH - w - 8, max(8, mpos[0] - w // 2))
    y = BAR_Y - 46
    rr = pygame.Rect(x, y, w, 40 if tip else 22)
    pygame.draw.rect(screen, (10, 8, 24), rr, border_radius=6)
    pygame.draw.rect(screen, (90, 110, 190), rr, 1, border_radius=6)
    txt(screen, name, rr.x + 8, rr.y + 4, 14, C_WHITE)
    if tip:
        txt(screen, tip, rr.x + 8, rr.y + 22, 11, C_GRAY)


def draw_toast(screen, st):
    if st.msg_timer > 0:
        w = max(200, len(st.msg) * 8 + 30)
        rr = pygame.Rect(WIDTH // 2 - w // 2, BAR_Y - 36, w, 26)
        pygame.draw.rect(screen, (0, 0, 0, 0), rr)
        s = pygame.Surface(rr.size, pygame.SRCALPHA)
        s.fill((0, 0, 0, 170))
        screen.blit(s, rr.topleft)
        txt(screen, st.msg, WIDTH // 2, rr.centery, 14, (255, 235, 160), True)


def draw_hud(screen, st, mpos):
    """Cursor cell + autosave age, top-right of the canvas."""
    gx, gy = st.screen_to_cell(*mpos)
    lines = [f"cell ({gx}, {gy})"]
    if st.last_autosave_secs is not None:
        import time
        ago = max(0, int(time.time() - st.last_autosave_secs))
        label = f"{ago}s" if ago < 60 else f"{ago // 60}m"
        lines.append(("auto-saved " if st.autosave_toast_frames > 0
                      else "last autosave ") + label + " ago")
    if st.show_hitboxes:
        n = len(st.last_run_hitboxes)
        lines.append(f"hitboxes: {n} frames" if n else "hitboxes: no run yet")
    if st.snippet_stamp is not None:
        lines.append(f"stamp: {st.snippet_stamp_name} (Esc cancels)")
    y = TOP_H + 6
    for i, ln in enumerate(lines):
        col = (140, 230, 140) if (i == 1 and st.autosave_toast_frames > 0) else C_GRAY
        txt(screen, ln, WIDTH - 8 - len(ln) * 7, y, 12, col)
        y += 16
