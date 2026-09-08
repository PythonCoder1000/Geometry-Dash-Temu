"""Editor modals: exit confirmation, crash modal, shortcut cheat sheet."""

import time

import pygame

from ..constants import WIDTH, HEIGHT, C_DARK, C_DANGER, C_SUCCESS, C_WHITE, C_GRAY, C_BTN
from ..graphics import txt
from ..input_guard import ClickGuard

EDITOR_SHORTCUTS = [
    ("Modes", [
        ("B / I / E", "Build / Edit / Delete mode"),
        ("N", "Link tool (teleports, triggers)"),
        ("Enter", "Confirm link targets"),
        ("F2", "Snippet library"),
    ]),
    ("Build", [
        ("Tab / Shift+Tab", "Cycle category"),
        ("1 - 9", "Pick item on the current page"),
        ("R / Q", "Rotate brush (or selection)"),
        ("Wheel on bar", "Rotate brush"),
        ("Right-click", "Erase at cursor"),
    ]),
    ("Edit", [
        ("Click / Shift+click", "Select / add to selection"),
        ("Drag", "Marquee (Swipe on) or move selection"),
        ("Arrows + Shift", "Nudge selection (Ctrl = 5 cells)"),
        ("Ctrl+A", "Select all"),
        ("Ctrl+C / X / V", "Copy / cut / paste"),
        ("Ctrl+D", "Duplicate in place"),
        ("Del", "Delete selection"),
        ("Shift+B", "Toggle bot-only on selection"),
        ("1 / 2", "Previous / next active Start Pos (not in Build mode)"),
    ]),
    ("View", [
        ("Arrows / WASD", "Pan (Shift = faster)"),
        ("Right / middle drag", "Pan"),
        ("Wheel on canvas", "Zoom (Shift = finer)"),
        ("Ctrl + = / -  /  Ctrl+0", "Zoom in / out / reset"),
        ("G / H", "Grid / hitbox overlay"),
    ]),
    ("Run / save", [
        ("T / Shift+T", "Test play / test from cursor"),
        ("K", "Run drawn path live"),
        ("L", "Bot menu"),
        ("S / Ctrl+L", "Save / load"),
        ("Ctrl+E", "Export PNG"),
        ("Ctrl+Shift+S", "Save selection as snippet"),
        ("F5", "Cycle music track"),
        ("Ctrl+Z / Ctrl+Y", "Undo / redo"),
        ("Esc", "Back to menu"),
    ]),
]


def draw_shortcuts(screen):
    ov = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    ov.fill((0, 0, 0, 200))
    screen.blit(ov, (0, 0))
    pw, ph = 940, 600
    panel = pygame.Rect((WIDTH - pw) // 2, (HEIGHT - ph) // 2, pw, ph)
    pygame.draw.rect(screen, (16, 16, 28), panel, border_radius=14)
    pygame.draw.rect(screen, (90, 110, 190), panel, 2, border_radius=14)
    txt(screen, "EDITOR SHORTCUTS", panel.centerx, panel.y + 26, 24, C_WHITE, True, shadow=True)
    total = sum(1 + len(items) for _, items in EDITOR_SHORTCUTS)
    left, right, acc = [], [], 0
    for grp in EDITOR_SHORTCUTS:
        rows = 1 + len(grp[1])
        if acc + rows <= total / 2 + 3:
            left.append(grp)
            acc += rows
        else:
            right.append(grp)
    col_w = (pw - 80) // 2

    def col(groups, x):
        y = panel.y + 66
        for title, items in groups:
            txt(screen, title, x, y, 16, (150, 190, 255))
            y += 22
            for key, desc in items:
                txt(screen, key, x + 10, y, 13, (255, 220, 120))
                txt(screen, desc, x + 190, y, 13, C_WHITE)
                y += 18
            y += 10

    col(left, panel.x + 40)
    col(right, panel.x + 40 + col_w + 20)
    txt(screen, "Press ? / F1 or Esc to close", panel.centerx, panel.bottom - 22, 12, (170, 170, 190), True)


def confirm_exit(screen, clock, *, unsaved):
    """Exit-confirm modal that ignores ESC mashing: the user must click
    Leave or Stay (Enter = Stay)."""
    box = pygame.Rect((WIDTH - 560) // 2, (HEIGHT - 220) // 2, 560, 220)
    r_leave = pygame.Rect(WIDTH // 2 - 150, box.bottom - 60, 130, 40)
    r_stay = pygame.Rect(WIDTH // 2 + 20, box.bottom - 60, 130, 40)
    guard = ClickGuard()
    esc_times = []
    msg = ""
    while True:
        guard.tick()
        mpos = pygame.mouse.get_pos()
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                # The OS window-close button reaffirms the exit the user
                # already asked for (that's why this modal is open) —
                # honour it as "Leave" instead of trapping them here with
                # no way out but the mouse.
                return True
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                now = time.monotonic()
                esc_times.append(now)
                esc_times[:] = [t for t in esc_times if now - t < 1.5]
                if len(esc_times) >= 3:
                    msg = "Hint: ESC won't exit — click Stay or Leave."
                continue
            if ev.type == pygame.KEYDOWN and ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                return False
            if (ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1
                    and guard.consume_click(ev)):
                if r_leave.collidepoint(ev.pos):
                    return True
                if r_stay.collidepoint(ev.pos):
                    return False
        ov = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 180))
        screen.blit(ov, (0, 0))
        pygame.draw.rect(screen, C_DARK, box, border_radius=10)
        pygame.draw.rect(screen, (90, 110, 140), box, 2, border_radius=10)
        txt(screen, "Leave the editor?", box.centerx, box.y + 30, 26, C_WHITE, True, shadow=True)
        txt(screen, "You have unsaved changes." if unsaved
            else "Camera, selection and drag state will reset.",
            box.centerx, box.y + 70, 14, C_GRAY, True)
        txt(screen, "Autosave is on disk for recovery.", box.centerx, box.y + 92, 13, (170, 200, 220), True)
        if msg:
            txt(screen, msg, box.centerx, box.y + 122, 13, (255, 200, 100), True, shadow=True)
        for r, lab, base in ((r_leave, "Leave", C_DANGER), (r_stay, "Stay", C_SUCCESS)):
            c = base if not r.collidepoint(mpos) else tuple(min(255, v + 30) for v in base)
            pygame.draw.rect(screen, c, r, border_radius=6)
            txt(screen, lab, r.centerx, r.centery, 16, C_WHITE, True)
        pygame.display.flip()
        clock.tick(60)


def layers_dialog(screen, clock, st):
    """Editor Layers panel (GD reference doc §5): per-layer visibility
    and lock, plus which layer new placements land on. Minimal list UI,
    not GD's full panel — matches the plan's scoped-down ambition."""
    guard = ClickGuard()
    row_h = 34
    while True:
        layers = st.used_layers()
        pw = 480
        ph = 90 + row_h * len(layers) + 60
        box = pygame.Rect((WIDTH - pw) // 2, (HEIGHT - ph) // 2, pw, ph)
        r_add = pygame.Rect(box.centerx - 70, box.bottom - 46, 140, 32)
        r_close = pygame.Rect(box.right - 90, box.y + 10, 70, 26)
        rows = []
        y = box.y + 56
        for layer in layers:
            r_active = pygame.Rect(box.x + 20, y, 90, row_h - 6)
            r_hide = pygame.Rect(box.x + 220, y, 90, row_h - 6)
            r_lock = pygame.Rect(box.x + 320, y, 90, row_h - 6)
            rows.append((layer, r_active, r_hide, r_lock))
            y += row_h
        guard.tick()
        mpos = pygame.mouse.get_pos()
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                return
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1 and guard.consume_click(ev):
                if r_close.collidepoint(ev.pos):
                    return
                if r_add.collidepoint(ev.pos):
                    st.active_layer = (max(layers) + 1) if layers else 1
                    continue
                for layer, r_active, r_hide, r_lock in rows:
                    if r_active.collidepoint(ev.pos):
                        st.active_layer = layer
                    elif r_hide.collidepoint(ev.pos):
                        if st.layer_hidden.get(layer):
                            st.layer_hidden.pop(layer, None)
                        else:
                            st.layer_hidden[layer] = True
                    elif r_lock.collidepoint(ev.pos):
                        if st.layer_locked.get(layer):
                            st.layer_locked.pop(layer, None)
                        else:
                            st.layer_locked[layer] = True
        ov = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 170))
        screen.blit(ov, (0, 0))
        pygame.draw.rect(screen, C_DARK, box, border_radius=10)
        pygame.draw.rect(screen, (90, 110, 190), box, 2, border_radius=10)
        txt(screen, "EDITOR LAYERS", box.x + 20, box.y + 22, 18, C_WHITE, False, shadow=True)
        for r, lab in ((r_close, "Close"),):
            pygame.draw.rect(screen, C_BTN, r, border_radius=6)
            txt(screen, lab, r.centerx, r.centery, 13, C_WHITE, True)
        for layer, r_active, r_hide, r_lock in rows:
            is_active = layer == st.active_layer
            hidden = bool(st.layer_hidden.get(layer))
            locked = bool(st.layer_locked.get(layer))
            txt(screen, f"Layer {layer}", box.x + 20, r_active.y - 2, 13, (200, 210, 255))
            active_col = C_SUCCESS if is_active else C_BTN
            pygame.draw.rect(screen, active_col, r_active, border_radius=6)
            txt(screen, "Active" if is_active else "Use", r_active.centerx, r_active.centery, 12, C_WHITE, True)
            hide_col = C_DANGER if hidden else C_BTN
            pygame.draw.rect(screen, hide_col, r_hide, border_radius=6)
            txt(screen, "Hidden" if hidden else "Visible", r_hide.centerx, r_hide.centery, 12, C_WHITE, True)
            lock_col = C_DANGER if locked else C_BTN
            pygame.draw.rect(screen, lock_col, r_lock, border_radius=6)
            txt(screen, "Locked" if locked else "Unlocked", r_lock.centerx, r_lock.centery, 12, C_WHITE, True)
        c = tuple(min(255, v + 30) for v in C_BTN) if r_add.collidepoint(mpos) else C_BTN
        pygame.draw.rect(screen, c, r_add, border_radius=6)
        txt(screen, "+ New Layer", r_add.centerx, r_add.centery, 14, C_WHITE, True)
        pygame.display.flip()
        clock.tick(60)


def select_filter_dialog(screen, clock, st):
    """Select Filter (GD reference doc §5's most-cited pain point): pick
    a type or a group id and select every matching, unlocked object —
    a first-class dialog instead of real GD's buried pause-menu control."""
    from ..objects import TYPE_NAMES
    guard = ClickGuard()
    types = sorted({o["t"] for o in st.objects}, key=lambda t: TYPE_NAMES.get(t, t))
    groups = sorted({g for o in st.objects for g in (o.get("groups") or [])})
    pw, ph = 560, 460
    box = pygame.Rect((WIDTH - pw) // 2, (HEIGHT - ph) // 2, pw, ph)
    col_w = (pw - 60) // 2
    r_close = pygame.Rect(box.right - 90, box.y + 10, 70, 26)

    def type_rows():
        y = box.y + 70
        out = []
        for t in types:
            out.append((t, pygame.Rect(box.x + 20, y, col_w, 26)))
            y += 28
        return out

    def group_rows():
        y = box.y + 70
        out = []
        for g in groups:
            out.append((g, pygame.Rect(box.x + 40 + col_w, y, col_w - 20, 26)))
            y += 28
        return out

    while True:
        guard.tick()
        mpos = pygame.mouse.get_pos()
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                return
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1 and guard.consume_click(ev):
                if r_close.collidepoint(ev.pos):
                    return
                for t, r in type_rows():
                    if r.collidepoint(ev.pos):
                        st.selected = st.filter_locked([o for o in st.objects if o["t"] == t])
                        st.say(f"Selected all {TYPE_NAMES.get(t, t)} ({len(st.selected)})", 100)
                        return
                for g, r in group_rows():
                    if r.collidepoint(ev.pos):
                        st.selected = st.filter_locked(
                            [o for o in st.objects if g in (o.get("groups") or [])])
                        st.say(f"Selected group {g} ({len(st.selected)})", 100)
                        return
        ov = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 170))
        screen.blit(ov, (0, 0))
        pygame.draw.rect(screen, C_DARK, box, border_radius=10)
        pygame.draw.rect(screen, (90, 110, 190), box, 2, border_radius=10)
        txt(screen, "SELECT FILTER", box.x + 20, box.y + 22, 18, C_WHITE, False, shadow=True)
        pygame.draw.rect(screen, C_BTN, r_close, border_radius=6)
        txt(screen, "Close", r_close.centerx, r_close.centery, 13, C_WHITE, True)
        txt(screen, "By type", box.x + 20, box.y + 48, 13, (150, 190, 255))
        for t, r in type_rows():
            hov = r.collidepoint(mpos)
            pygame.draw.rect(screen, (46, 50, 90) if not hov else (66, 72, 130), r, border_radius=4)
            txt(screen, TYPE_NAMES.get(t, t), r.x + 8, r.centery, 12, C_WHITE)
        txt(screen, "By group", box.x + 40 + col_w, box.y + 48, 13, (150, 190, 255))
        if not groups:
            txt(screen, "(no grouped objects)", box.x + 40 + col_w, box.y + 70, 12, C_GRAY)
        for g, r in group_rows():
            hov = r.collidepoint(mpos)
            pygame.draw.rect(screen, (46, 50, 90) if not hov else (66, 72, 130), r, border_radius=4)
            txt(screen, f"Group {g}", r.x + 8, r.centery, 12, C_WHITE)
        pygame.display.flip()
        clock.tick(60)


def show_error_modal(screen, clock, exc, *, where="editor"):
    """Crash notice: the traceback is already on stdout; this tells the
    user their autosave is safe.  Dismissed with Enter / Space / click."""
    box = pygame.Rect((WIDTH - 640) // 2, (HEIGHT - 280) // 2, 640, 280)
    r_ok = pygame.Rect(WIDTH // 2 - 80, box.bottom - 60, 160, 40)
    guard = ClickGuard()
    err_type = type(exc).__name__
    err_msg = str(exc)
    if len(err_msg) > 70:
        err_msg = err_msg[:67] + "..."
    while True:
        guard.tick()
        mpos = pygame.mouse.get_pos()
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                # Same reasoning as confirm_exit: don't trap the user in
                # a modal with no way to honour the OS close button.
                return
            if ev.type == pygame.KEYDOWN and ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                return
            if (ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1
                    and guard.consume_click(ev) and r_ok.collidepoint(ev.pos)):
                return
        ov = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 200))
        screen.blit(ov, (0, 0))
        pygame.draw.rect(screen, C_DARK, box, border_radius=10)
        pygame.draw.rect(screen, (240, 90, 90), box, 2, border_radius=10)
        txt(screen, "An error occurred", box.centerx, box.y + 32, 26, (255, 200, 100), True, shadow=True)
        txt(screen, f"{err_type}: {err_msg}", box.centerx, box.y + 78, 14, C_WHITE, True)
        txt(screen, "Full traceback printed to the console.", box.centerx, box.y + 110, 13, C_GRAY, True)
        txt(screen, f"The {where}'s autosave is on disk — your work is recoverable.",
            box.centerx, box.y + 134, 13, (170, 220, 200), True)
        txt(screen, "Re-open the editor to load the autosave.", box.centerx, box.y + 156, 12, (140, 180, 220), True)
        c = tuple(min(255, v + 30) for v in C_BTN) if r_ok.collidepoint(mpos) else C_BTN
        pygame.draw.rect(screen, c, r_ok, border_radius=6)
        txt(screen, "OK (Return to menu)", r_ok.centerx, r_ok.centery, 15, C_WHITE, True)
        pygame.display.flip()
        clock.tick(60)
