"""Music menu — scrollable track browser with play / set-as-menu controls.

Replaces the old "Music: Next Track" button on the main menu (which only
cycled blindly with no preview). The user gets a list of every track in
``assets/music/`` plus the procedural chiptune fallbacks, can preview each
by clicking it, mark one as the menu music (persisted via prefs), adjust
volume, and toggle mute.

The menu doesn't own pygame state — it reuses the shared ``music`` module
so changes here take effect immediately for the rest of the game.
"""

import sys

import pygame

from constants import (
    WIDTH, HEIGHT,
    C_DARK, C_WHITE, C_GRAY, C_BLOCK_H, C_BTN, C_BTN_H, C_DANGER, C_SUCCESS,
)
from graphics import (
    draw_bg, txt, btn, make_stars, make_mountains, lighter, darker,
    speaker_icon, icon_button,
)
from input_guard import ClickGuard
import music
import settings


# Track-list scroll state survives between visits so re-opening the menu
# leaves you where you were.
_scroll = 0


def _slider(screen, mpos, mb_down, x, y, w, value):
    """Tiny slider helper (dup of menus._slider, intentionally local).

    Kept here rather than imported so the music menu has zero internal
    dependencies on the larger menus.py module — that module is becoming
    a junk drawer and isolating new screens from it makes future cleanup
    easier.
    """
    track = pygame.Rect(x, y + 10, w, 6)
    pygame.draw.rect(screen, (40, 40, 70), track, border_radius=3)
    fill = pygame.Rect(x, y + 10, int(w * value), 6)
    pygame.draw.rect(screen, (140, 200, 255), fill, border_radius=3)
    knob_x = x + int(w * value)
    knob_hover = (mpos[0] - knob_x) ** 2 + (mpos[1] - (y + 13)) ** 2 <= 18 ** 2
    pygame.draw.circle(screen,
                       (200, 230, 255) if knob_hover else (180, 210, 255),
                       (knob_x, y + 13), 10)
    pygame.draw.circle(screen, (60, 90, 160), (knob_x, y + 13), 10, 2)
    new_val = value
    track_hit = pygame.Rect(x - 4, y, w + 8, 30)
    if mb_down and track_hit.collidepoint(mpos):
        new_val = max(0.0, min(1.0, (mpos[0] - x) / max(1, w)))
    return new_val


def run_music_menu(screen, clock):
    """Display the music menu; returns when the user clicks Back / Esc."""
    global _scroll

    stars = make_stars()
    mountains = make_mountains()
    guard = ClickGuard()

    panel_w = 720
    panel_h = 560
    panel = pygame.Rect((WIDTH - panel_w) // 2,
                        (HEIGHT - panel_h) // 2,
                        panel_w, panel_h)

    list_x = panel.x + 32
    list_y = panel.y + 100
    list_w = panel.w - 64
    row_h = 44
    visible_h = panel.h - 240   # leave room for volume + buttons at bottom

    while True:
        guard.tick()
        mpos = pygame.mouse.get_pos()
        mb_down = guard.mouse_held()
        click_pos = None
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    return
                if ev.key == pygame.K_m:
                    music.toggle_mute()
                if ev.key == pygame.K_SPACE:
                    if music.is_playing():
                        music.stop()
                    else:
                        music.play_menu_music()
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if not guard.consume_click(ev):
                    continue
                click_pos = ev.pos
            if ev.type == pygame.MOUSEWHEEL:
                tracks = music.get_tracks()
                max_scroll = max(0, len(tracks) * row_h - visible_h)
                _scroll = max(0, min(max_scroll, _scroll - ev.y * 30))

        tracks = music.get_tracks()
        cur_idx = music.current_track_index()
        menu_idx = music.get_menu_track_index()

        # ---- background --------------------------------------------------
        draw_bg(screen, 0, stars, mountains)
        ov = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 180))
        screen.blit(ov, (0, 0))
        pygame.draw.rect(screen, darker(C_DARK, 10), panel.move(0, 6),
                         border_radius=14)
        pygame.draw.rect(screen, C_DARK, panel, border_radius=14)
        pygame.draw.rect(screen, C_BLOCK_H, panel, 2, border_radius=14)

        txt(screen, "MUSIC", panel.centerx, panel.y + 22, 30, C_WHITE,
            True, shadow=True)
        sub = "Click row to play  ·  ★ marks the menu track"
        txt(screen, sub, panel.centerx, panel.y + 56, 13, C_GRAY, True)

        # ---- Track list (scrollable) -------------------------------------
        list_rect = pygame.Rect(list_x - 4, list_y - 4,
                                list_w + 8, visible_h + 8)
        prev_clip = screen.get_clip()
        screen.set_clip(list_rect)
        if not tracks:
            txt(screen, "No tracks found in assets/music/.",
                panel.centerx, list_y + 60, 16, C_GRAY, True)
        for i, t in enumerate(tracks):
            ry = list_y + i * row_h - _scroll
            if ry < list_y - row_h or ry > list_y + visible_h:
                continue
            row = pygame.Rect(list_x, ry, list_w, row_h - 6)
            hov = row.collidepoint(mpos)
            is_playing = (cur_idx == i and music.is_playing())
            is_menu = (menu_idx == i)
            base = (50, 80, 50) if is_playing else (40, 40, 70)
            col = lighter(base, 30) if hov else base
            pygame.draw.rect(screen, col, row, border_radius=6)
            pygame.draw.rect(screen, lighter(col, 50), row, 1, border_radius=6)

            # ★ for menu track, ▶ for currently-playing
            badge_x = row.x + 12
            if is_menu:
                txt(screen, "★", badge_x, row.y + 8, 20, (255, 220, 80))
                badge_x += 24
            if is_playing:
                txt(screen, "▶", badge_x, row.y + 8, 20, (140, 240, 140))
                badge_x += 24

            txt(screen, t["name"], badge_x + 4, row.y + 11, 17, C_WHITE)
            kind = t.get("type", "file")
            ttag = "[generated]" if kind == "generated" else "[file]"
            txt(screen, ttag, row.right - 100, row.y + 13, 12, C_GRAY)

            # Two micro-buttons on the right: "Set ★" and "Stop" (if playing).
            set_btn = pygame.Rect(row.right - 200, row.y + 6, 86, row.h - 12)
            pygame.draw.rect(screen, (60, 90, 160), set_btn, border_radius=4)
            txt(screen, "Set ★", set_btn.centerx, set_btn.centery - 6, 12,
                C_WHITE, True)

            if click_pos:
                if set_btn.collidepoint(click_pos):
                    music.set_menu_track_index(i)
                elif row.collidepoint(click_pos):
                    music.play_track(i)

        screen.set_clip(prev_clip)

        # Scroll indicator
        max_scroll = max(0, len(tracks) * row_h - visible_h)
        if max_scroll > 0:
            bar_h = max(30, int(visible_h * visible_h
                                / (len(tracks) * row_h)))
            bar_y = list_y + int((visible_h - bar_h)
                                 * (_scroll / max_scroll))
            pygame.draw.rect(screen, (50, 60, 110),
                             (panel.right - 18, list_y, 4, visible_h),
                             border_radius=2)
            pygame.draw.rect(screen, (140, 180, 255),
                             (panel.right - 18, bar_y, 4, bar_h),
                             border_radius=2)

        # ---- Volume slider -----------------------------------------------
        vol_y = panel.bottom - 130
        txt(screen, "Music volume", list_x, vol_y - 2, 15, C_WHITE)
        cur_vol = settings.get_music_vol()
        new_vol = _slider(screen, mpos, mb_down,
                          list_x + 130, vol_y, 280, cur_vol)
        if abs(new_vol - cur_vol) > 0.005:
            settings.set_music_vol(new_vol)
        txt(screen, f"{int(round(new_vol * 100))}%",
            list_x + 420, vol_y + 4, 13, C_GRAY)

        # ---- Mute / Stop / Next / Prev / Back ---------------------------
        ctrl_y = panel.bottom - 80
        b_mute = btn(screen,
                     "Music: OFF" if music.is_muted() else "Music: ON",
                     list_x + 70, ctrl_y, 160, 36,
                     C_DANGER if music.is_muted() else C_SUCCESS,
                     mpos, font_size=14)
        if click_pos and b_mute.collidepoint(click_pos):
            music.toggle_mute()

        b_stop = btn(screen, "Stop", list_x + 240, ctrl_y, 90, 36,
                     C_BTN, mpos, font_size=14)
        if click_pos and b_stop.collidepoint(click_pos):
            music.stop()

        b_prev = btn(screen, "‹ Prev", list_x + 340, ctrl_y, 100, 36,
                     C_BTN, mpos, font_size=14)
        if click_pos and b_prev.collidepoint(click_pos):
            music.prev_track()

        b_next = btn(screen, "Next ›", list_x + 450, ctrl_y, 100, 36,
                     C_BTN, mpos, font_size=14)
        if click_pos and b_next.collidepoint(click_pos):
            music.next_track()

        b_back = btn(screen, "BACK", list_x + 600, ctrl_y, 90, 36,
                     C_DANGER, mpos, font_size=14)
        if click_pos and b_back.collidepoint(click_pos):
            return

        txt(screen, "Space: play/stop  ·  M: mute  ·  Esc: back",
            panel.centerx, panel.bottom - 22, 12, C_GRAY, True)
        pygame.display.flip()
        clock.tick(settings.get_fps_cap())
