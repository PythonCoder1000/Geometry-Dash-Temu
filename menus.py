"""Menu screens: main menu, level-select grid, text input and load dialog."""

import math
import os
import sys

import pygame

from constants import (
    WIDTH, HEIGHT, FPS, LEVELS_DIR,
    C_PLAYER, C_GRAY, C_WHITE, C_BTN, C_BTN_H, C_DANGER, C_DARK, C_BLOCK_H,
    C_SUCCESS, C_PUBLISH, C_COIN,
    DIFFICULTIES, DIFFICULTY_COLORS,
    PLAYER_COLORS, PLAYER_ICONS, PLAYER_SIZE,
)
from graphics import (
    draw_bg, txt, btn, make_stars, make_mountains, lighter, darker,
    speaker_icon, icon_button, draw_obj, draw_cube_icon_glyph,
)
from levels import list_levels, list_level_summaries, load_level_full
import music
import sfx
import settings
import gamepad
import thumbnails
from input_guard import ClickGuard


# Thumbnail cache — avoid hitting disk every frame for the same level.
_THUMB_CACHE = {}


def _get_thumb_for(filename):
    """Return a Surface (or None) for this level's thumbnail.

    Lazy-regenerates if the file is missing — covers levels saved before the
    thumbnail feature shipped, and any time the cache file gets cleared.
    """
    if filename in _THUMB_CACHE:
        return _THUMB_CACHE[filename]
    surf = thumbnails.load_thumbnail(filename)
    if surf is None:
        try:
            _meta, objs = load_level_full(os.path.join(LEVELS_DIR, filename))
            thumbnails.save_thumbnail(filename, objs)
            surf = thumbnails.load_thumbnail(filename)
        except (OSError, ValueError):
            surf = None
    _THUMB_CACHE[filename] = surf
    return surf


def run_menu(screen, clock):
    stars = make_stars()
    mountains = make_mountains()
    pulse = 0
    b_play = b_edit = b_settings = b_customize = b_quit = b_music = pygame.Rect(0, 0, 0, 0)
    r_mute_music = r_mute_sfx = pygame.Rect(0, 0, 0, 0)
    if music.is_enabled() and not music.is_playing():
        music.play_menu_music()
    guard = ClickGuard()
    while True:
        guard.tick()
        pulse += 1
        mpos = pygame.mouse.get_pos()
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return "quit"
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    return "quit"
                if ev.key == pygame.K_m:
                    music.toggle_mute()
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if not guard.consume_click(ev):
                    continue
                if r_mute_music.collidepoint(ev.pos):
                    music.toggle_mute()
                    continue
                if r_mute_sfx.collidepoint(ev.pos):
                    sfx.toggle_mute()
                    continue
                if b_play.collidepoint(ev.pos):
                    return "play"
                if b_edit.collidepoint(ev.pos):
                    return "editor"
                if b_settings.collidepoint(ev.pos):
                    return "settings"
                if b_customize.collidepoint(ev.pos):
                    return "customize"
                if b_music.collidepoint(ev.pos):
                    return "music"
                if b_quit.collidepoint(ev.pos):
                    return "quit"
        draw_bg(screen, pulse * 0.5, stars, mountains)
        title = "GEOMETRY DASH"
        glow = pygame.Surface((900, 120), pygame.SRCALPHA)
        txt(glow, title, 450, 60, 56, (*C_PLAYER, 60), True)
        screen.blit(glow, (WIDTH // 2 - 450, 100))
        txt(screen, title, WIDTH // 2, 160, 56, C_PLAYER, True, shadow=True)
        txt(screen, "TEMU EDITION", WIDTH // 2, 220, 28, C_GRAY, True, shadow=True)
        b_play = btn(screen, "PLAY", WIDTH // 2, 290, 240, 48, C_BTN, mpos)
        b_edit = btn(screen, "LEVEL EDITOR", WIDTH // 2, 346, 240, 48, C_BTN, mpos)
        b_customize = btn(screen, "CUSTOMIZE", WIDTH // 2, 402, 240, 48,
                          (140, 80, 180), mpos)
        b_settings = btn(screen, "SETTINGS", WIDTH // 2, 458, 240, 48,
                         (60, 90, 160), mpos)
        b_music = btn(screen, "MUSIC", WIDTH // 2, 510, 240, 36,
                      (80, 60, 140), mpos, font_size=16)
        b_quit = btn(screen, "QUIT", WIDTH // 2, 560, 240, 42, C_DANGER, mpos)
        for i in range(6):
            a = pulse * 2 + i * 60
            bx = WIDTH // 2 + int(math.cos(math.radians(a)) * 320)
            by = 400 + int(math.sin(math.radians(a)) * 130)
            s = pygame.Surface((24, 24), pygame.SRCALPHA)
            pygame.draw.rect(s, (*C_PLAYER, 100), (0, 0, 24, 24), border_radius=3)
            rot = pygame.transform.rotate(s, a)
            screen.blit(rot, rot.get_rect(center=(bx, by)))
        # Mute buttons (top-right)
        r_mute_music = icon_button(
            screen, speaker_icon(22, music.is_muted()),
            WIDTH - 35, 35, 40, 40, C_BTN, mpos, active=music.is_muted(),
        )
        r_mute_sfx = icon_button(
            screen, speaker_icon(18, sfx.is_muted()),
            WIDTH - 80, 35, 40, 40, (80, 60, 140), mpos, active=sfx.is_muted(),
        )
        txt(screen, "MUS", r_mute_music.centerx, r_mute_music.bottom + 2, 10,
            C_GRAY, True, shadow=True)
        txt(screen, "SFX", r_mute_sfx.centerx, r_mute_sfx.bottom + 2, 10,
            C_GRAY, True, shadow=True)
        txt(screen, "Space / Click to jump  ·  Hold in ship / wave  ·  WASD in editor",
            WIDTH // 2, HEIGHT - 30, 15, C_GRAY, True, shadow=True)
        pygame.display.flip()
        clock.tick(settings.get_fps_cap())


# ---------------------------------------------------------------------------
# Level-select grid
# ---------------------------------------------------------------------------

CARD_W = 340
CARD_H = 150  # bumped to fit a 4:1 thumbnail strip across the top
CARD_GAP = 14
CARDS_PER_ROW = 3
LIST_TOP_Y = 140
LIST_BOT_Y = HEIGHT - 90
THUMB_STRIP_W = CARD_W - 24    # full width minus side padding
THUMB_STRIP_H = THUMB_STRIP_W // 4  # 4:1 ratio (matches thumbnails.py)


def _card_rect(col, row, scroll):
    x = (WIDTH - (CARD_W * CARDS_PER_ROW + CARD_GAP * (CARDS_PER_ROW - 1))) // 2
    sx = x + col * (CARD_W + CARD_GAP)
    sy = LIST_TOP_Y + row * (CARD_H + CARD_GAP) - scroll
    return pygame.Rect(sx, sy, CARD_W, CARD_H)


def _draw_level_card(screen, rect, meta, hovered, filename=None):
    col = C_BTN_H if hovered else C_BTN
    pygame.draw.rect(screen, darker(col, 60), rect.move(0, 4), border_radius=12)
    pygame.draw.rect(screen, col, rect, border_radius=12)
    pygame.draw.rect(screen, lighter(col, 40), rect, 2, border_radius=12)
    # Difficulty color chip (left edge)
    diff = meta.get("difficulty", "Normal")
    dc = DIFFICULTY_COLORS.get(diff, C_GRAY)
    chip = pygame.Rect(rect.x + 6, rect.y + 6, 8, rect.h - 12)
    pygame.draw.rect(screen, dc, chip, border_radius=4)

    # Thumbnail strip across the top — gives an instant "shape of the level"
    # cue. Falls back to a flat tinted strip when generation isn't possible
    # (e.g. legacy meta-only summary).
    thumb_x = rect.x + 18
    thumb_y = rect.y + 8
    thumb_rect = pygame.Rect(thumb_x, thumb_y, THUMB_STRIP_W, THUMB_STRIP_H)
    thumb_surf = _get_thumb_for(filename) if filename else None
    if thumb_surf is not None:
        scaled = pygame.transform.smoothscale(
            thumb_surf, (THUMB_STRIP_W, THUMB_STRIP_H))
        screen.blit(scaled, thumb_rect.topleft)
        pygame.draw.rect(screen, lighter(col, 30), thumb_rect, 1, border_radius=4)
    else:
        pygame.draw.rect(screen, darker(col, 80), thumb_rect, border_radius=4)
        pygame.draw.rect(screen, lighter(col, 30), thumb_rect, 1, border_radius=4)
        txt(screen, "(no preview)", thumb_rect.centerx, thumb_rect.centery - 6,
            11, C_GRAY, True)

    text_y = thumb_rect.bottom + 6
    # Title
    title = meta.get("name", "Untitled")
    if len(title) > 26:
        title = title[:25] + "…"
    txt(screen, title, rect.x + 24, text_y, 18, C_WHITE, shadow=True)
    # Author & difficulty line
    author = meta.get("author", "Player")
    txt(screen, f"by {author}  ·  {diff}", rect.x + 24, text_y + 24, 12, C_GRAY)
    # Status badge (bottom-right)
    if meta.get("verified"):
        badge_col = C_SUCCESS
        label = "✓ VERIFIED"
    elif meta.get("published"):
        badge_col = C_PUBLISH
        label = "UNVERIFIED"
    else:
        badge_col = (90, 90, 110)
        label = "DRAFT"
    bw, bh = 110, 22
    br = pygame.Rect(rect.right - bw - 10, rect.bottom - bh - 10, bw, bh)
    pygame.draw.rect(screen, darker(badge_col, 30), br, border_radius=11)
    pygame.draw.rect(screen, badge_col, br.inflate(-2, -2), border_radius=10)
    txt(screen, label, br.centerx, br.centery, 12, C_WHITE, True)
    # Progress bar (small, bottom-left)
    progress = int(meta.get("best_progress", 0))
    if progress > 0:
        pb_w = 160
        pb = pygame.Rect(rect.x + 24, rect.bottom - 20, pb_w, 6)
        pygame.draw.rect(screen, darker(col, 60), pb, border_radius=3)
        pygame.draw.rect(screen, (90, 255, 120),
                         (pb.x, pb.y, int(pb_w * progress / 100), pb.h), border_radius=3)
        txt(screen, f"{progress}%", pb.right + 6, pb.y - 3, 11, C_GRAY)
    # Coin count (top-right corner of card, overlaid on thumbnail with shadow)
    coins = int(meta.get("coins_collected", 0))
    if coins > 0:
        txt(screen, f"{coins}/3", rect.right - 32, rect.y + 12, 13, C_COIN,
            shadow=True)
    # Best time (if record exists) — bottom-right above the badge
    best_t = int(meta.get("best_time_frames", 0))
    if best_t > 0:
        bts = best_t / 60.0
        best_str = f"{int(bts // 60):d}:{bts % 60:05.2f}"
        txt(screen, best_str, br.x - 8, br.centery - 7, 12, C_GRAY, False,
            shadow=True)


def run_select(screen, clock):
    """Show a card grid of all levels. Returns path or None."""
    summaries = list_level_summaries()
    # Sort: verified first, then published, then drafts; within each alpha.
    def _sort_key(item):
        fn, m = item
        if m.get("verified"):
            bucket = 0
        elif m.get("published"):
            bucket = 1
        else:
            bucket = 2
        return (bucket, m.get("name", fn).lower())
    summaries.sort(key=_sort_key)

    scroll = 0
    stars = make_stars()
    mountains = make_mountains()
    b_back = pygame.Rect(0, 0, 0, 0)
    r_mute_music = r_mute_sfx = pygame.Rect(0, 0, 0, 0)
    guard = ClickGuard()
    filter_mode = 0  # 0 = all, 1 = verified, 2 = unverified, 3 = drafts
    b_filter = pygame.Rect(0, 0, 0, 0)

    def _filtered():
        if filter_mode == 1:
            return [s for s in summaries if s[1].get("verified")]
        if filter_mode == 2:
            return [s for s in summaries if s[1].get("published") and not s[1].get("verified")]
        if filter_mode == 3:
            return [s for s in summaries if not s[1].get("published")]
        return list(summaries)

    while True:
        guard.tick()
        mpos = pygame.mouse.get_pos()
        mx, my = mpos
        items = _filtered()
        rows = (len(items) + CARDS_PER_ROW - 1) // CARDS_PER_ROW
        content_h = rows * (CARD_H + CARD_GAP)
        visible_h = LIST_BOT_Y - LIST_TOP_Y
        max_scroll = max(0, content_h - visible_h)

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    return None
                if ev.key == pygame.K_m:
                    music.toggle_mute()
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if not guard.consume_click(ev):
                    continue
                if r_mute_music.collidepoint(ev.pos):
                    music.toggle_mute()
                    continue
                if r_mute_sfx.collidepoint(ev.pos):
                    sfx.toggle_mute()
                    continue
                if b_back.collidepoint(ev.pos):
                    return None
                if b_filter.collidepoint(ev.pos):
                    filter_mode = (filter_mode + 1) % 4
                    scroll = 0
                    continue
                for i, (fn, meta) in enumerate(items):
                    col = i % CARDS_PER_ROW
                    row = i // CARDS_PER_ROW
                    r = _card_rect(col, row, scroll)
                    if r.bottom < LIST_TOP_Y or r.top > LIST_BOT_Y:
                        continue
                    if r.collidepoint(ev.pos):
                        return os.path.join(LEVELS_DIR, fn)
            if ev.type == pygame.MOUSEWHEEL:
                scroll = max(0, min(max_scroll, scroll - ev.y * 40))

        draw_bg(screen, 0, stars, mountains)
        # Clip the cards to the list area so they don't draw over title/back btn.
        txt(screen, "SELECT LEVEL", WIDTH // 2, 56, 40, C_WHITE, True, shadow=True)
        filter_names = ["All", "Verified", "Unverified", "Drafts"]
        b_filter = btn(screen, f"Filter: {filter_names[filter_mode]}",
                       WIDTH - 130, 60, 200, 36, (70, 90, 160), mpos, font_size=15)
        txt(screen, f"{len(items)} level{'s' if len(items) != 1 else ''}",
            130, 60, 18, C_GRAY, True, shadow=True)
        # Clip cards to list window
        prev_clip = screen.get_clip()
        screen.set_clip(pygame.Rect(0, LIST_TOP_Y - 8, WIDTH, visible_h + 16))
        if not items:
            msg = ("No levels found. Create one in the editor!"
                   if filter_mode == 0 else
                   f"No {filter_names[filter_mode].lower()} levels.")
            txt(screen, msg, WIDTH // 2, HEIGHT // 2 - 20, 22, C_GRAY, True)
        else:
            for i, (fn, meta) in enumerate(items):
                col = i % CARDS_PER_ROW
                row = i // CARDS_PER_ROW
                r = _card_rect(col, row, scroll)
                if r.bottom < LIST_TOP_Y - 20 or r.top > LIST_BOT_Y + 20:
                    continue
                _draw_level_card(screen, r, meta, r.collidepoint(mpos),
                                 filename=fn)
        screen.set_clip(prev_clip)

        # Scroll indicator
        if max_scroll > 0:
            bar_h = max(30, int(visible_h * visible_h / content_h))
            bar_y = LIST_TOP_Y + int((visible_h - bar_h) * (scroll / max_scroll))
            pygame.draw.rect(screen, (50, 60, 110),
                             (WIDTH - 14, LIST_TOP_Y, 6, visible_h), border_radius=3)
            pygame.draw.rect(screen, (140, 180, 255),
                             (WIDTH - 14, bar_y, 6, bar_h), border_radius=3)

        b_back = btn(screen, "BACK", WIDTH // 2, HEIGHT - 45, 180, 44, C_DANGER, mpos)
        txt(screen, "Scroll: mouse wheel · Esc to return",
            WIDTH // 2, HEIGHT - 82, 13, C_GRAY, True, shadow=True)
        # Mute buttons (top-left corner)
        r_mute_music = icon_button(
            screen, speaker_icon(20, music.is_muted()),
            30, 30, 36, 36, C_BTN, mpos, active=music.is_muted(),
        )
        r_mute_sfx = icon_button(
            screen, speaker_icon(18, sfx.is_muted()),
            72, 30, 36, 36, (80, 60, 140), mpos, active=sfx.is_muted(),
        )
        pygame.display.flip()
        clock.tick(settings.get_fps_cap())


# ---------------------------------------------------------------------------
# Text input / load dialogs — used by the editor
# ---------------------------------------------------------------------------

def confirm_dialog(screen, clock, prompt, subtitle=None,
                   ok_label="OK", cancel_label="Cancel",
                   ok_color=None, cancel_color=None):
    """Modal yes/no confirmation. Returns True (OK) or False (Cancel/Esc)."""
    stars = make_stars()
    guard = ClickGuard()
    if ok_color is None:
        ok_color = C_SUCCESS
    if cancel_color is None:
        cancel_color = C_DANGER
    box_w, box_h = 520, 220
    while True:
        guard.tick()
        mpos = pygame.mouse.get_pos()
        box = pygame.Rect(WIDTH // 2 - box_w // 2, HEIGHT // 2 - box_h // 2,
                          box_w, box_h)
        r_ok = pygame.Rect(WIDTH // 2 - 130, box.bottom - 60, 120, 40)
        r_cancel = pygame.Rect(WIDTH // 2 + 10, box.bottom - 60, 120, 40)
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if ev.type == pygame.KEYDOWN:
                if ev.key in (pygame.K_RETURN, pygame.K_y):
                    return True
                if ev.key in (pygame.K_ESCAPE, pygame.K_n):
                    return False
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if not guard.consume_click(ev):
                    continue
                if r_ok.collidepoint(ev.pos):
                    return True
                if r_cancel.collidepoint(ev.pos):
                    return False
        draw_bg(screen, 0, stars)
        ov = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 200))
        screen.blit(ov, (0, 0))
        pygame.draw.rect(screen, darker(C_DARK, 10), box.move(0, 4),
                         border_radius=14)
        pygame.draw.rect(screen, C_DARK, box, border_radius=14)
        pygame.draw.rect(screen, C_BLOCK_H, box, 2, border_radius=14)
        txt(screen, prompt, WIDTH // 2, box.y + 38, 22, C_WHITE, True)
        if subtitle:
            # Word-wrap the subtitle on commas/periods if too long.
            txt(screen, subtitle, WIDTH // 2, box.y + 78, 14, C_GRAY, True)
        for r, label, col in [(r_ok, ok_label, ok_color),
                              (r_cancel, cancel_label, cancel_color)]:
            hov = r.collidepoint(mpos)
            c = lighter(col, 30) if hov else col
            pygame.draw.rect(screen, darker(c, 60), r.move(0, 3),
                             border_radius=8)
            pygame.draw.rect(screen, c, r, border_radius=8)
            txt(screen, label, r.centerx, r.centery, 16, C_WHITE, True)
        txt(screen, "Enter/Y: yes  ·  Esc/N: no",
            WIDTH // 2, box.bottom - 12, 12, C_GRAY, True)
        pygame.display.flip()
        clock.tick(settings.get_fps_cap())


def text_input_dialog(screen, clock, prompt="Enter name:", default=""):
    text = default
    stars = make_stars()
    guard = ClickGuard()
    while True:
        guard.tick()
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_RETURN and text.strip():
                    return text.strip()
                if ev.key == pygame.K_ESCAPE:
                    return None
                if ev.key == pygame.K_BACKSPACE:
                    text = text[:-1]
                elif len(text) < 30 and ev.unicode.isprintable():
                    text += ev.unicode
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if not guard.consume_click(ev):
                    continue
        draw_bg(screen, 0, stars)
        ov = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 180))
        screen.blit(ov, (0, 0))
        box = pygame.Rect(WIDTH // 2 - 240, HEIGHT // 2 - 100, 480, 200)
        pygame.draw.rect(screen, darker(C_DARK, 10), box.move(0, 4), border_radius=14)
        pygame.draw.rect(screen, C_DARK, box, border_radius=14)
        pygame.draw.rect(screen, C_BLOCK_H, box, 2, border_radius=14)
        txt(screen, prompt, WIDTH // 2, HEIGHT // 2 - 55, 24, C_WHITE, True)
        tf = pygame.Rect(WIDTH // 2 - 180, HEIGHT // 2 - 18, 360, 40)
        pygame.draw.rect(screen, (15, 15, 30), tf, border_radius=6)
        pygame.draw.rect(screen, C_BLOCK_H, tf, 1, border_radius=6)
        txt(screen, text + "|", tf.x + 10, tf.y + 10, 20, C_WHITE)
        txt(screen, "Enter to confirm  ·  Esc to cancel",
            WIDTH // 2, HEIGHT // 2 + 55, 15, C_GRAY, True)
        pygame.display.flip()
        clock.tick(settings.get_fps_cap())


def difficulty_picker(screen, clock, prompt="Choose difficulty:", default="Normal",
                      subtitle=None):
    """Modal difficulty picker. Returns the chosen difficulty string or None.

    Used both by the editor's publish flow (publisher *requests* a difficulty)
    and by the play win-screen on first verification (verifier *sets* the
    final official difficulty).
    """
    stars = make_stars()
    guard = ClickGuard()
    selected = default if default in DIFFICULTIES else "Normal"
    btn_h = 38
    btn_w = 130
    gap = 8
    cols = 4
    rows = (len(DIFFICULTIES) + cols - 1) // cols
    box_w = cols * btn_w + (cols - 1) * gap + 60
    box_h = 130 + rows * (btn_h + gap) + 60
    while True:
        guard.tick()
        mpos = pygame.mouse.get_pos()
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    return None
                if ev.key == pygame.K_RETURN:
                    return selected
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if not guard.consume_click(ev):
                    continue
                # Hit-test difficulty buttons + confirm/cancel
                for i, diff in enumerate(DIFFICULTIES):
                    r = _diff_btn_rect(i, btn_w, btn_h, gap, cols, box_w, box_h)
                    if r.collidepoint(ev.pos):
                        selected = diff
                        break
                if r_ok.collidepoint(ev.pos):
                    return selected
                if r_cancel.collidepoint(ev.pos):
                    return None
        draw_bg(screen, 0, stars)
        ov = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 200))
        screen.blit(ov, (0, 0))
        box = pygame.Rect(WIDTH // 2 - box_w // 2, HEIGHT // 2 - box_h // 2, box_w, box_h)
        pygame.draw.rect(screen, darker(C_DARK, 10), box.move(0, 4), border_radius=14)
        pygame.draw.rect(screen, C_DARK, box, border_radius=14)
        pygame.draw.rect(screen, C_BLOCK_H, box, 2, border_radius=14)
        txt(screen, prompt, WIDTH // 2, box.y + 24, 24, C_WHITE, True)
        if subtitle:
            txt(screen, subtitle, WIDTH // 2, box.y + 56, 14, C_GRAY, True)
        for i, diff in enumerate(DIFFICULTIES):
            r = _diff_btn_rect(i, btn_w, btn_h, gap, cols, box_w, box_h)
            base = DIFFICULTY_COLORS.get(diff, C_GRAY)
            is_sel = (diff == selected)
            border_col = C_WHITE if is_sel else darker(base, 30)
            fill = lighter(base, 25) if is_sel or r.collidepoint(mpos) else base
            pygame.draw.rect(screen, darker(fill, 50), r.move(0, 3), border_radius=8)
            pygame.draw.rect(screen, fill, r, border_radius=8)
            pygame.draw.rect(screen, border_col, r, 2 if is_sel else 1, border_radius=8)
            txt(screen, diff, r.centerx, r.centery, 16, C_WHITE, True, shadow=True)
        # Confirm + Cancel
        r_ok = pygame.Rect(WIDTH // 2 - 110, box.bottom - 50, 100, 36)
        r_cancel = pygame.Rect(WIDTH // 2 + 10, box.bottom - 50, 100, 36)
        for r, label, col in [(r_ok, "OK", C_SUCCESS), (r_cancel, "Cancel", C_DANGER)]:
            hov = r.collidepoint(mpos)
            c = lighter(col, 30) if hov else col
            pygame.draw.rect(screen, darker(c, 60), r.move(0, 3), border_radius=8)
            pygame.draw.rect(screen, c, r, border_radius=8)
            txt(screen, label, r.centerx, r.centery, 16, C_WHITE, True)
        txt(screen, "Enter: confirm  ·  Esc: cancel",
            WIDTH // 2, box.bottom - 12, 12, C_GRAY, True)
        pygame.display.flip()
        clock.tick(settings.get_fps_cap())


def _diff_btn_rect(idx, btn_w, btn_h, gap, cols, box_w, box_h):
    """Compute the rect for difficulty button index `idx` inside the picker box."""
    bx0 = WIDTH // 2 - (cols * btn_w + (cols - 1) * gap) // 2
    by0 = HEIGHT // 2 - box_h // 2 + 90
    col = idx % cols
    row = idx // cols
    return pygame.Rect(bx0 + col * (btn_w + gap),
                       by0 + row * (btn_h + gap),
                       btn_w, btn_h)


def load_level_dialog(screen, clock):
    """Editor's load dialog — returns path or None."""
    summaries = list_level_summaries()
    summaries.sort(key=lambda it: it[1].get("name", it[0]).lower())
    scroll = 0
    stars = make_stars()
    guard = ClickGuard()
    while True:
        guard.tick()
        mpos = pygame.mouse.get_pos()
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                return None
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if not guard.consume_click(ev):
                    continue
                for i, (fn, meta) in enumerate(summaries):
                    y = 220 + i * 44 - scroll
                    r = pygame.Rect(WIDTH // 2 - 190, y, 380, 38)
                    if 190 < y < 510 and r.collidepoint(ev.pos):
                        return os.path.join(LEVELS_DIR, fn)
            if ev.type == pygame.MOUSEWHEEL:
                scroll = max(0, scroll - ev.y * 30)
        draw_bg(screen, 0, stars)
        ov = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 180))
        screen.blit(ov, (0, 0))
        box = pygame.Rect(WIDTH // 2 - 230, 130, 460, 440)
        pygame.draw.rect(screen, C_DARK, box, border_radius=14)
        pygame.draw.rect(screen, C_BLOCK_H, box, 2, border_radius=14)
        txt(screen, "Load Level", WIDTH // 2, 160, 28, C_WHITE, True)
        prev_clip = screen.get_clip()
        screen.set_clip(pygame.Rect(box.x + 4, 195, box.w - 8, 325))
        if not summaries:
            txt(screen, "No levels found.", WIDTH // 2, 300, 20, C_GRAY, True)
        for i, (fn, meta) in enumerate(summaries):
            y = 220 + i * 44 - scroll
            if 195 < y < 515:
                r = pygame.Rect(WIDTH // 2 - 190, y, 380, 38)
                c = C_BTN_H if r.collidepoint(mpos) else C_BTN
                pygame.draw.rect(screen, c, r, border_radius=6)
                diff = meta.get("difficulty", "Normal")
                dc = DIFFICULTY_COLORS.get(diff, C_GRAY)
                pygame.draw.rect(screen, dc, (r.x + 4, r.y + 4, 6, r.h - 8), border_radius=3)
                title = meta.get("name") or fn.replace(".json", "")
                txt(screen, title[:32], r.x + 18, r.y + 11, 17, C_WHITE)
                # Status icon
                if meta.get("verified"):
                    txt(screen, "✓", r.right - 22, r.y + 11, 16, C_SUCCESS)
                elif meta.get("published"):
                    txt(screen, "◦", r.right - 22, r.y + 11, 16, C_PUBLISH)
        screen.set_clip(prev_clip)
        txt(screen, "Esc to cancel", WIDTH // 2, 548, 15, C_GRAY, True)
        pygame.display.flip()
        clock.tick(settings.get_fps_cap())


def snippet_picker(screen, clock):
    """Modal snippet picker. Returns (name, objects, is_user) or None.

    Shows the built-in snippets followed by user snippets, with miniature
    thumbnails rendered using the live `draw_obj`. Click a row to "pick up"
    that snippet; the editor then drops it where the user clicks next.
    Right-click a user snippet to delete it (built-ins are immutable).
    """
    from snippets import get_snippets, delete_user_snippet

    stars = make_stars()
    guard = ClickGuard()
    scroll = 0
    box_x = WIDTH // 2 - 280
    box_y = 90
    box_w = 560
    box_h = 540
    list_x = box_x + 18
    list_y = box_y + 70
    list_w = box_w - 36
    row_h = 70
    visible_h = box_h - 110

    while True:
        guard.tick()
        snippets = get_snippets()
        mpos = pygame.mouse.get_pos()
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                return None
            if ev.type == pygame.MOUSEWHEEL:
                max_scroll = max(0, len(snippets) * row_h - visible_h)
                scroll = max(0, min(max_scroll, scroll - ev.y * 30))
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button in (1, 3):
                if not guard.consume_click(ev):
                    continue
                for i, (name, objs, is_user) in enumerate(snippets):
                    ry = list_y + i * row_h - scroll
                    if ry < list_y - row_h or ry > list_y + visible_h:
                        continue
                    rrect = pygame.Rect(list_x, ry, list_w, row_h - 6)
                    if rrect.collidepoint(ev.pos):
                        if ev.button == 1:
                            return (name, objs, is_user)
                        if ev.button == 3 and is_user:
                            # Compute the user-list index (built-ins are first).
                            n_builtin = sum(
                                1 for _, _, u in snippets if not u
                            )
                            delete_user_snippet(i - n_builtin)
                            # fall through to redraw with refreshed list
        draw_bg(screen, 0, stars)
        ov = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 200))
        screen.blit(ov, (0, 0))
        box = pygame.Rect(box_x, box_y, box_w, box_h)
        pygame.draw.rect(screen, darker(C_DARK, 10), box.move(0, 4),
                         border_radius=14)
        pygame.draw.rect(screen, C_DARK, box, border_radius=14)
        pygame.draw.rect(screen, C_BLOCK_H, box, 2, border_radius=14)
        txt(screen, "Snippet Palette", WIDTH // 2, box_y + 24, 24, C_WHITE, True)
        txt(screen, "Click to stamp · Right-click to delete user snippets",
            WIDTH // 2, box_y + 50, 12, C_GRAY, True)
        # Clip the scroll region.
        prev_clip = screen.get_clip()
        screen.set_clip(pygame.Rect(list_x - 4, list_y - 4,
                                     list_w + 8, visible_h + 8))
        for i, (name, objs, is_user) in enumerate(snippets):
            ry = list_y + i * row_h - scroll
            if ry < list_y - row_h or ry > list_y + visible_h:
                continue
            rrect = pygame.Rect(list_x, ry, list_w, row_h - 6)
            hov = rrect.collidepoint(mpos)
            base = (40, 50, 110) if is_user else (28, 32, 70)
            col = lighter(base, 30) if hov else base
            pygame.draw.rect(screen, col, rrect, border_radius=6)
            pygame.draw.rect(screen, lighter(col, 50), rrect, 1, border_radius=6)
            # Thumbnail: shrink-fit the snippet into a 200x52 strip.
            thumb_x = rrect.x + 8
            thumb_y = rrect.y + 6
            thumb_w = 200
            thumb_h = rrect.h - 12
            if objs:
                xs = [o["x"] for o in objs]
                ys = [o["y"] for o in objs]
                snip_w = max(1, max(xs) - min(xs) + 1)
                snip_h = max(1, max(ys) - min(ys) + 1)
                cell_px = max(6, min(thumb_w // snip_w, thumb_h // snip_h))
                ox = thumb_x + (thumb_w - cell_px * snip_w) // 2
                oy = thumb_y + (thumb_h - cell_px * snip_h) // 2
                min_x, min_y = min(xs), min(ys)
                pygame.draw.rect(screen, (10, 8, 22),
                                 (thumb_x, thumb_y, thumb_w, thumb_h),
                                 border_radius=4)
                for o in objs:
                    draw_obj(screen, o["t"],
                             ox + (o["x"] - min_x) * cell_px,
                             oy + (o["y"] - min_y) * cell_px,
                             cell_px, 0, o.get("r", 0))
            tag = "[user]" if is_user else "[built-in]"
            txt(screen, name, thumb_x + thumb_w + 18, rrect.y + 14, 17, C_WHITE)
            txt(screen, f"{len(objs)} obj · {tag}",
                thumb_x + thumb_w + 18, rrect.y + 40, 12, C_GRAY)
        if not snippets:
            txt(screen, "No snippets available.",
                WIDTH // 2, list_y + visible_h // 2 - 8, 18, C_GRAY, True)
        screen.set_clip(prev_clip)
        txt(screen, "Esc: cancel  ·  Scroll to browse",
            WIDTH // 2, box_y + box_h - 22, 12, C_GRAY, True)
        pygame.display.flip()
        clock.tick(settings.get_fps_cap())


# ---------------------------------------------------------------------------
# Settings screen — volume sliders, FPS cap cycle, fullscreen toggle, etc.
# ---------------------------------------------------------------------------

def _slider(screen, mpos, mb_down, x, y, w, value):
    """Draw a horizontal slider and return (new_value, dragging).

    `value` is 0..1. Returns the new value (clamped) and whether the cursor
    is currently engaging the slider — caller decides what to do with that.
    """
    track = pygame.Rect(x, y + 10, w, 6)
    pygame.draw.rect(screen, (40, 40, 70), track, border_radius=3)
    fill = pygame.Rect(x, y + 10, int(w * value), 6)
    pygame.draw.rect(screen, (140, 200, 255), fill, border_radius=3)
    knob_x = x + int(w * value)
    knob_r = 10
    knob_hover = (mpos[0] - knob_x) ** 2 + (mpos[1] - (y + 13)) ** 2 <= 18 ** 2
    pygame.draw.circle(screen, (200, 230, 255) if knob_hover else (180, 210, 255),
                       (knob_x, y + 13), knob_r)
    pygame.draw.circle(screen, (60, 90, 160), (knob_x, y + 13), knob_r, 2)
    new_val = value
    # Drag-to-adjust whenever the mouse is held over the track.
    track_hit = pygame.Rect(x - 4, y, w + 8, 30)
    if mb_down and track_hit.collidepoint(mpos):
        new_val = max(0.0, min(1.0, (mpos[0] - x) / max(1, w)))
    return new_val, track_hit.collidepoint(mpos)


def run_settings(screen, clock, on_fullscreen_change=None):
    """Settings panel — adjusts FPS cap, fullscreen, volumes and mutes.

    `on_fullscreen_change` is an optional callable invoked after the
    fullscreen toggle is flipped, so the host can re-create its surface.
    Returns when the user clicks Back or presses Esc.
    """
    stars = make_stars()
    mountains = make_mountains()
    guard = ClickGuard()

    panel_w = 540
    panel_h = 480
    panel = pygame.Rect((WIDTH - panel_w) // 2, 80, panel_w, panel_h)

    while True:
        guard.tick()
        mpos = pygame.mouse.get_pos()
        mb_down = guard.mouse_held()
        click_pos = None
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                return
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if not guard.consume_click(ev):
                    continue
                click_pos = ev.pos

        # ---- background --------------------------------------------------
        draw_bg(screen, 0, stars, mountains)
        ov = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 160))
        screen.blit(ov, (0, 0))
        pygame.draw.rect(screen, darker(C_DARK, 10), panel.move(0, 6),
                         border_radius=14)
        pygame.draw.rect(screen, C_DARK, panel, border_radius=14)
        pygame.draw.rect(screen, C_BLOCK_H, panel, 2, border_radius=14)
        txt(screen, "SETTINGS", panel.centerx, panel.y + 22, 30, C_WHITE,
            True, shadow=True)

        col_x = panel.x + 32
        val_x = panel.x + panel.w - 200
        row_y = panel.y + 80

        # ---- FPS cap (button cycles through options) ---------------------
        txt(screen, "Frame rate cap", col_x, row_y, 18, C_WHITE)
        b_fps = btn(screen, settings.fps_cap_label(), val_x + 80, row_y + 12,
                    160, 36, C_BTN, mpos, font_size=15)
        if click_pos and b_fps.collidepoint(click_pos):
            settings.cycle_fps_cap()
        row_y += 60

        # ---- Fullscreen toggle ------------------------------------------
        txt(screen, "Fullscreen", col_x, row_y, 18, C_WHITE)
        fs_label = "On" if settings.get_fullscreen() else "Off"
        fs_color = C_SUCCESS if settings.get_fullscreen() else (90, 90, 110)
        b_fs = btn(screen, fs_label, val_x + 80, row_y + 12, 160, 36,
                   fs_color, mpos, font_size=15)
        if click_pos and b_fs.collidepoint(click_pos):
            settings.toggle_fullscreen()
            if on_fullscreen_change is not None:
                try:
                    on_fullscreen_change()
                except Exception:
                    pass
        row_y += 60

        # ---- Music volume slider ----------------------------------------
        txt(screen, "Music volume", col_x, row_y, 18, C_WHITE)
        cur_music = settings.get_music_vol()
        new_music, _ = _slider(screen, mpos, mb_down, val_x, row_y, 240,
                               cur_music)
        if abs(new_music - cur_music) > 0.005:
            settings.set_music_vol(new_music)
        txt(screen, f"{int(round(new_music * 100))}%", val_x + 256,
            row_y + 6, 14, C_GRAY)
        row_y += 50

        # ---- SFX volume slider ------------------------------------------
        txt(screen, "SFX volume", col_x, row_y, 18, C_WHITE)
        cur_sfx = settings.get_sfx_vol()
        new_sfx, sfx_drag = _slider(screen, mpos, mb_down, val_x, row_y, 240,
                                    cur_sfx)
        if abs(new_sfx - cur_sfx) > 0.005:
            settings.set_sfx_vol(new_sfx)
            # Play a click on release/drag so the user hears the new level.
            sfx.play("click", 0.6)
        txt(screen, f"{int(round(new_sfx * 100))}%", val_x + 256,
            row_y + 6, 14, C_GRAY)
        row_y += 50

        # ---- Music mute ---------------------------------------------------
        txt(screen, "Mute music", col_x, row_y, 18, C_WHITE)
        mm_label = "Muted" if music.is_muted() else "On"
        mm_color = C_DANGER if music.is_muted() else C_SUCCESS
        b_mm = btn(screen, mm_label, val_x + 80, row_y + 12, 160, 36, mm_color,
                   mpos, font_size=15)
        if click_pos and b_mm.collidepoint(click_pos):
            music.toggle_mute()
        row_y += 60

        # ---- SFX mute -----------------------------------------------------
        txt(screen, "Mute SFX", col_x, row_y, 18, C_WHITE)
        sm_label = "Muted" if sfx.is_muted() else "On"
        sm_color = C_DANGER if sfx.is_muted() else C_SUCCESS
        b_sm = btn(screen, sm_label, val_x + 80, row_y + 12, 160, 36, sm_color,
                   mpos, font_size=15)
        if click_pos and b_sm.collidepoint(click_pos):
            sfx.toggle_mute()
        row_y += 70

        # ---- Reset + Back -------------------------------------------------
        b_reset = btn(screen, "Reset to defaults", panel.x + 130,
                      panel.bottom - 50, 200, 38, (140, 90, 50), mpos,
                      font_size=14)
        if click_pos and b_reset.collidepoint(click_pos):
            settings.reset_to_defaults()
            # Apply mute defaults to the live audio modules too.
            if music.is_muted():
                music.toggle_mute()
            if sfx.is_muted():
                sfx.toggle_mute()
            # Fullscreen default is off; if currently fullscreen, flip.
            if settings.get_fullscreen() != settings.DEFAULTS["fullscreen"]:
                settings.set_fullscreen(settings.DEFAULTS["fullscreen"])
                if on_fullscreen_change is not None:
                    try:
                        on_fullscreen_change()
                    except Exception:
                        pass

        b_back = btn(screen, "BACK", panel.x + panel.w - 130,
                     panel.bottom - 50, 200, 38, C_DANGER, mpos, font_size=14)
        if click_pos and b_back.collidepoint(click_pos):
            return

        # Gamepad status — read-only, just so the user knows whether the pad
        # was detected. Shown below the panel since it doesn't need a button.
        if gamepad.is_connected():
            label = f"Gamepad: {gamepad.name() or 'connected'}"
            color = C_SUCCESS
        else:
            label = "Gamepad: not detected"
            color = C_GRAY
        txt(screen, label, panel.centerx, panel.bottom + 4, 13, color, True)

        txt(screen, "Esc: back  ·  Drag sliders to adjust",
            panel.centerx, panel.bottom + 22, 12, C_GRAY, True)
        pygame.display.flip()
        clock.tick(settings.get_fps_cap())


# ---------------------------------------------------------------------------
# Customize screen — pick player icon glyph + body color.
# ---------------------------------------------------------------------------

def _draw_player_swatch(screen, rect, color, icon_index, hovered, selected):
    """Render one cube preview tile inside `rect`.

    Used both as the icon grid (current color, varying icon) and the color
    grid (current icon, varying color). Selection gets a bright outline,
    hover gets a subtle one — keeps the picker readable at a glance.
    """
    bg = lighter(C_DARK, 12) if hovered else C_DARK
    pygame.draw.rect(screen, bg, rect, border_radius=8)
    if selected:
        pygame.draw.rect(screen, C_SUCCESS, rect, 3, border_radius=8)
    else:
        pygame.draw.rect(screen, lighter(C_BLOCK_H, 10), rect, 1,
                         border_radius=8)
    # Cube body — same drawing recipe as Player._draw_player_surface so the
    # preview matches what you'll see in-game.
    cube_size = min(rect.w, rect.h) - 16
    cube = pygame.Surface((cube_size, cube_size), pygame.SRCALPHA)
    pygame.draw.rect(cube, darker(color, 30),
                     (1, 3, cube_size - 2, cube_size - 2), border_radius=3)
    pygame.draw.rect(cube, color,
                     (0, 0, cube_size, cube_size), border_radius=3)
    pygame.draw.rect(cube, lighter(color, 60),
                     (3, 3, cube_size - 6, cube_size - 6), 2, border_radius=3)
    draw_cube_icon_glyph(cube, 0, 0, cube_size, color, icon_index)
    cr = cube.get_rect(center=rect.center)
    screen.blit(cube, cr.topleft)


def run_customize(screen, clock):
    """Picker for the player icon glyph + body color.

    Two grids: top is the icon picker (current color shown across all
    glyphs), bottom is the color picker (current icon shown in each
    color). Click a tile to select; selection persists immediately via
    the settings module so the change is visible the next time the
    player spawns.

    Returns when the user clicks Back or presses Esc.
    """
    stars = make_stars()
    mountains = make_mountains()
    guard = ClickGuard()

    panel_w = 640
    panel_h = 540
    panel = pygame.Rect((WIDTH - panel_w) // 2, 60, panel_w, panel_h)

    # Grid layout — 8 icons and 8 colors, both rendered as a single row of
    # tiles. If either palette later grows past what fits, we fall back to
    # smaller tiles rather than overflowing.
    n_icons = len(PLAYER_ICONS)
    n_colors = len(PLAYER_COLORS)
    inner_w = panel_w - 60
    icon_tile = max(48, min(72, inner_w // max(1, n_icons) - 6))
    color_tile = max(48, min(72, inner_w // max(1, n_colors) - 6))

    while True:
        guard.tick()
        mpos = pygame.mouse.get_pos()
        click_pos = None
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    return
                # Arrow keys cycle for keyboard-only users.
                if ev.key == pygame.K_RIGHT:
                    cur = settings.get_player_icon_index() % n_icons
                    settings.set_player_icon_index((cur + 1) % n_icons)
                elif ev.key == pygame.K_LEFT:
                    cur = settings.get_player_icon_index() % n_icons
                    settings.set_player_icon_index((cur - 1) % n_icons)
                elif ev.key == pygame.K_DOWN:
                    cur = settings.get_player_color_index() % n_colors
                    settings.set_player_color_index((cur + 1) % n_colors)
                elif ev.key == pygame.K_UP:
                    cur = settings.get_player_color_index() % n_colors
                    settings.set_player_color_index((cur - 1) % n_colors)
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if not guard.consume_click(ev):
                    continue
                click_pos = ev.pos

        cur_color_idx = settings.get_player_color_index() % n_colors
        cur_icon_idx = settings.get_player_icon_index() % n_icons
        cur_color = PLAYER_COLORS[cur_color_idx]

        # ---- background --------------------------------------------------
        draw_bg(screen, 0, stars, mountains)
        ov = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 160))
        screen.blit(ov, (0, 0))
        pygame.draw.rect(screen, darker(C_DARK, 10), panel.move(0, 6),
                         border_radius=14)
        pygame.draw.rect(screen, C_DARK, panel, border_radius=14)
        pygame.draw.rect(screen, C_BLOCK_H, panel, 2, border_radius=14)

        txt(screen, "CUSTOMIZE", panel.centerx, panel.y + 22, 30, C_WHITE,
            True, shadow=True)

        # ---- Big preview tile (current selection) ------------------------
        prev_size = 96
        prev_rect = pygame.Rect(0, 0, prev_size + 20, prev_size + 20)
        prev_rect.center = (panel.centerx, panel.y + 100)
        _draw_player_swatch(screen, prev_rect, cur_color, cur_icon_idx,
                            False, True)
        txt(screen, f"{PLAYER_ICONS[cur_icon_idx]}",
            panel.centerx, prev_rect.bottom + 14, 18, C_WHITE, True,
            shadow=True)

        # ---- Icon grid ---------------------------------------------------
        icons_y = prev_rect.bottom + 50
        txt(screen, "Icon", panel.x + 30, icons_y - 22, 16, C_GRAY)
        icon_total_w = n_icons * icon_tile + (n_icons - 1) * 6
        icon_x0 = panel.centerx - icon_total_w // 2
        for i in range(n_icons):
            r = pygame.Rect(icon_x0 + i * (icon_tile + 6), icons_y,
                            icon_tile, icon_tile)
            hov = r.collidepoint(mpos)
            sel = (i == cur_icon_idx)
            _draw_player_swatch(screen, r, cur_color, i, hov, sel)
            if click_pos and r.collidepoint(click_pos):
                settings.set_player_icon_index(i)
                sfx.play("click", 0.5)

        # ---- Color grid --------------------------------------------------
        colors_y = icons_y + icon_tile + 50
        txt(screen, "Color", panel.x + 30, colors_y - 22, 16, C_GRAY)
        color_total_w = n_colors * color_tile + (n_colors - 1) * 6
        color_x0 = panel.centerx - color_total_w // 2
        for i in range(n_colors):
            r = pygame.Rect(color_x0 + i * (color_tile + 6), colors_y,
                            color_tile, color_tile)
            hov = r.collidepoint(mpos)
            sel = (i == cur_color_idx)
            _draw_player_swatch(screen, r, PLAYER_COLORS[i], cur_icon_idx,
                                hov, sel)
            if click_pos and r.collidepoint(click_pos):
                settings.set_player_color_index(i)
                sfx.play("click", 0.5)

        # ---- Back / Reset ------------------------------------------------
        b_reset = btn(screen, "Reset", panel.x + 130,
                      panel.bottom - 50, 200, 38, (140, 90, 50), mpos,
                      font_size=14)
        if click_pos and b_reset.collidepoint(click_pos):
            settings.set_player_color_index(
                settings.DEFAULTS["player_color_index"])
            settings.set_player_icon_index(
                settings.DEFAULTS["player_icon_index"])

        b_back = btn(screen, "BACK", panel.x + panel.w - 130,
                     panel.bottom - 50, 200, 38, C_DANGER, mpos, font_size=14)
        if click_pos and b_back.collidepoint(click_pos):
            return

        txt(screen, "Click a tile to select  ·  Arrows: cycle  ·  Esc: back",
            panel.centerx, panel.bottom + 16, 12, C_GRAY, True)
        pygame.display.flip()
        clock.tick(settings.get_fps_cap())
