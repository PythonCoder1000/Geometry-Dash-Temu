"""Menu screens: main menu, level-select grid, text input and load dialog."""

import math
import os
import sys
from collections import OrderedDict

import pygame

from .constants import (
    WIDTH, HEIGHT, FPS, LEVELS_DIR,
    C_PLAYER, C_GRAY, C_WHITE, C_BTN, C_BTN_H, C_DANGER, C_DARK, C_BLOCK_H,
    C_SUCCESS, C_PUBLISH, C_COIN,
    DIFFICULTIES, DIFFICULTY_COLORS,
    PLAYER_COLORS, PLAYER_ICONS, PLAYER_SIZE,
)
from .graphics import (
    draw_bg, txt, btn, make_stars, make_mountains, lighter, darker,
    speaker_icon, icon_button, draw_obj, draw_cube_icon_glyph,
    draw_panel_footer, draw_title_glow,
)
from .levels import list_levels, list_level_summaries, load_level_full
from . import music
from . import sfx
from . import settings
from . import gamepad
from . import thumbnails
from .input_guard import ClickGuard


def _maybe_click_sfx(pos, rects):
    """Play the UI click sound if `pos` lies inside any of the given
    button rects. Used to keep sfx.play calls DRY across a menu's worth
    of collidepoint checks without touching each call site."""
    for r in rects:
        if r is not None and r.collidepoint(pos):
            sfx.play("click", 0.45)
            return


# Thumbnail cache — avoid hitting disk every frame for the same level.
# LRU-ordered (OrderedDict) so the raw-surface and scaled-surface caches
# stay bounded even if the user browses through very long level lists.
_THUMB_CACHE = OrderedDict()          # filename -> raw Surface | None
_THUMB_SCALED_CACHE = OrderedDict()   # (filename, w, h) -> Surface
_THUMB_CACHE_MAX = 128
_THUMB_SCALED_CACHE_MAX = 128
_THUMB_SENTINEL = object()


def _get_thumb_for(filename):
    """Return a Surface (or None) for this level's thumbnail.

    Lazy-regenerates if the file is missing — covers levels saved before the
    thumbnail feature shipped, and any time the cache file gets cleared.
    """
    cached = _THUMB_CACHE.get(filename, _THUMB_SENTINEL)
    if cached is not _THUMB_SENTINEL:
        _THUMB_CACHE.move_to_end(filename)
        return cached
    surf = thumbnails.load_thumbnail(filename)
    if surf is None:
        try:
            _meta, objs = load_level_full(os.path.join(LEVELS_DIR, filename))
            thumbnails.save_thumbnail(filename, objs)
            surf = thumbnails.load_thumbnail(filename)
        except (OSError, ValueError):
            surf = None
    _THUMB_CACHE[filename] = surf
    while len(_THUMB_CACHE) > _THUMB_CACHE_MAX:
        _THUMB_CACHE.popitem(last=False)
    return surf


def _get_scaled_thumb(filename, w, h):
    """Cached smoothscale of the raw thumbnail to (w, h).

    `smoothscale` is expensive enough that scaling every visible card every
    frame is a measurable cost in the level-select grid. The scaled surface
    is keyed on (filename, w, h) so zoom / layout changes invalidate cleanly.
    """
    key = (filename, w, h)
    cached = _THUMB_SCALED_CACHE.get(key)
    if cached is not None:
        _THUMB_SCALED_CACHE.move_to_end(key)
        return cached
    raw = _get_thumb_for(filename)
    if raw is None:
        return None
    scaled = pygame.transform.smoothscale(raw, (w, h))
    _THUMB_SCALED_CACHE[key] = scaled
    while len(_THUMB_SCALED_CACHE) > _THUMB_SCALED_CACHE_MAX:
        _THUMB_SCALED_CACHE.popitem(last=False)
    return scaled


# Module-global starfield / mountain silhouette — regenerated lazily so the
# background keeps visual continuity as the user navigates between dialogs.
_STARS_CACHE = None
_MOUNTAINS_CACHE = None


def _stars():
    global _STARS_CACHE
    if _STARS_CACHE is None:
        _STARS_CACHE = make_stars()
    return _STARS_CACHE


def _mountains():
    global _MOUNTAINS_CACHE
    if _MOUNTAINS_CACHE is None:
        _MOUNTAINS_CACHE = make_mountains()
    return _MOUNTAINS_CACHE


def _draw_gear_icon(screen, cx, cy, size=18, color=C_WHITE):
    """Simple six-tooth gear glyph for the Settings button."""
    import pygame as _pg
    outer = size
    inner = size - 5
    hub = size // 3
    pts = []
    for i in range(12):
        ang = math.radians(i * 30)
        r = outer if i % 2 == 0 else inner
        pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    _pg.draw.polygon(screen, color, pts)
    _pg.draw.circle(screen, (20, 20, 30), (cx, cy), hub)
    _pg.draw.circle(screen, color, (cx, cy), hub, 2)


_MENU_HELP_GROUPS = [
    ("Navigation", [
        ("Click", "Pick an option from the stack"),
        ("Esc", "Quit"),
    ]),
    ("Audio", [
        ("M", "Toggle music mute"),
        ("Gear (top-right)", "Open settings"),
    ]),
    ("Help", [
        ("? / F1 / /", "Show this help"),
    ]),
]

_SELECT_HELP_GROUPS = [
    ("Browsing", [
        ("← / →", "Cycle levels"),
        ("Enter", "Play current level"),
        ("/  or  Ctrl+F", "Search by name or author"),
        ("Esc", "Back to main menu"),
    ]),
    ("Audio", [
        ("M", "Toggle music mute"),
    ]),
    ("Help", [
        ("? / F1", "Show this help"),
    ]),
]

_PLAY_HELP_GROUPS = [
    ("Gameplay", [
        ("Space / ↑ / Click", "Jump or hold"),
        ("P", "Pause / resume"),
        ("R", "Retry from start"),
        ("Esc", "Back to menu (saves Best %)"),
    ]),
    ("Practice mode", [
        ("C", "Drop a checkpoint here"),
        ("X", "Remove the most recent checkpoint"),
        ("H", "Toggle hint (auto-bot path)"),
        ("+  /  -", "Change practice speed"),
    ]),
    ("Help", [
        ("? / F1", "Show this help"),
    ]),
]


def run_menu(screen, clock):
    """Main menu — Trigonometry Sprint.

    Layout: title at top, vertical button stack (Play / Practice /
    Level Editor / Quit), gear icon top-right for Settings, small
    quick-mute cluster beside it, login/signup indicator top-left.
    """
    stars = _stars()
    mountains = _mountains()
    (b_play, b_practice, b_edit, b_quit,
     r_mute_music, r_mute_sfx, r_gear, r_auth, r_help) = (
        pygame.Rect(0, 0, 0, 0) for _ in range(9))
    if music.is_enabled() and not music.is_playing():
        music.play_menu_music()
    guard = ClickGuard()
    _menu_t0 = pygame.time.get_ticks()
    while True:
        guard.tick()
        # Drive animations from wall-clock ms, not render frames, so the
        # spinning cubes / glow / bg scroll run at the same visual speed
        # regardless of the user's FPS cap. 60 "pulse units" per real
        # second matches the old 60 Hz frame-counter feel.
        pulse = (pygame.time.get_ticks() - _menu_t0) * 60 // 1000
        mpos = pygame.mouse.get_pos()
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return "quit"
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    return "quit"
                if ev.key == pygame.K_m:
                    music.toggle_mute()
                if ev.key in (pygame.K_SLASH, pygame.K_F1,
                              pygame.K_QUESTION):
                    help_modal(screen, clock, "Main Menu — Help",
                               _MENU_HELP_GROUPS)
                    guard.reset()
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if not guard.consume_click(ev):
                    continue
                _maybe_click_sfx(ev.pos, [
                    b_play, b_practice, b_edit, b_quit,
                    r_mute_music, r_mute_sfx, r_gear, r_auth, r_help])
                if r_help.collidepoint(ev.pos):
                    help_modal(screen, clock, "Main Menu — Help",
                               _MENU_HELP_GROUPS)
                    guard.reset()
                    continue
                if r_mute_music.collidepoint(ev.pos):
                    music.toggle_mute()
                    continue
                if r_mute_sfx.collidepoint(ev.pos):
                    sfx.toggle_mute()
                    continue
                if r_gear.collidepoint(ev.pos):
                    return "settings"
                if r_auth.collidepoint(ev.pos):
                    return "auth"
                if b_play.collidepoint(ev.pos):
                    return "play"
                if b_practice.collidepoint(ev.pos):
                    return "practice"
                if b_edit.collidepoint(ev.pos):
                    return "editor"
                if b_quit.collidepoint(ev.pos):
                    return "quit"
        draw_bg(screen, pulse * 0.5, stars, mountains)
        title = "TRIGONOMETRY SPRINT"
        _gr = 10 + int(2 * math.sin(pulse / 18.0))
        draw_title_glow(screen, title, WIDTH // 2, 160, size=56,
                        col=C_PLAYER, glow_col=C_PLAYER,
                        glow_radius=_gr, glow_alpha=200)

        # Vertical stack: Play · Practice · Level Editor · Quit.
        stack_cx = WIDTH // 2
        stack_y = 280
        gap = 60
        b_play = btn(screen, "PLAY", stack_cx, stack_y, 260, 50, C_BTN, mpos)
        b_practice = btn(screen, "PRACTICE", stack_cx, stack_y + gap,
                         260, 50, (90, 130, 90), mpos)
        b_edit = btn(screen, "LEVEL EDITOR", stack_cx, stack_y + 2 * gap,
                     260, 50, (80, 100, 160), mpos)
        b_quit = btn(screen, "QUIT", stack_cx, stack_y + 3 * gap,
                     260, 50, C_DANGER, mpos)

        # Decorative squares orbiting behind the stack.
        for i in range(6):
            a = pulse * 2 + i * 60
            bx = WIDTH // 2 + int(math.cos(math.radians(a)) * 320)
            by = 400 + int(math.sin(math.radians(a)) * 130)
            s = pygame.Surface((24, 24), pygame.SRCALPHA)
            pygame.draw.rect(s, (*C_PLAYER, 90), (0, 0, 24, 24), border_radius=3)
            rot = pygame.transform.rotate(s, a)
            screen.blit(rot, rot.get_rect(center=(bx, by)))

        # Top-right cluster: gear (settings) + two mute speakers + help.
        r_gear = icon_button(screen, None, WIDTH - 35, 35, 40, 40,
                             (60, 80, 140), mpos)
        _draw_gear_icon(screen, r_gear.centerx, r_gear.centery, size=14)
        r_mute_music = icon_button(
            screen, speaker_icon(22, music.is_muted()),
            WIDTH - 80, 35, 40, 40, C_BTN, mpos, active=music.is_muted())
        r_mute_sfx = icon_button(
            screen, speaker_icon(18, sfx.is_muted()),
            WIDTH - 125, 35, 40, 40, (80, 60, 140), mpos,
            active=sfx.is_muted())
        # "?" help button — advertises the F1 / ? keybind so new users
        # actually discover the modal instead of relying on memorised
        # shortcuts.
        r_help = icon_button(screen, None, WIDTH - 170, 35, 40, 40,
                             (70, 100, 140), mpos)
        txt(screen, "?", r_help.centerx, r_help.centery, 20, C_WHITE,
            True, shadow=True)

        # Top-left: auth indicator. Label changes based on whether the
        # user is signed in. Opens the auth modal on click (chunk F).
        _user = _current_username()
        auth_label = f"Signed in: {_user}" if _user else "Login / Signup"
        r_auth = btn(screen, auth_label, 130, 35, 240, 36,
                     (50, 70, 110) if _user else (70, 60, 120),
                     mpos, font_size=13)

        pygame.display.flip()
        clock.tick(settings.get_fps_cap())


def _current_username():
    """Small local-only helper — reads the signed-in username from
    prefs. Chunk F will replace this with a proper AuthStore call; for
    now it lets the main menu show a placeholder indicator without
    crashing when the server isn't wired up yet."""
    try:
        from .prefs import get as _pget
        return _pget("signed_in_username", None)
    except Exception:
        return None


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


def _best_practice_key(filename):
    return f"best_practice_{filename}" if filename else None


def _get_best_practice(filename):
    """Best % reached in practice mode for a given level filename.
    Stored per-level in prefs until the server-backed progress store
    lands in Chunk F."""
    try:
        from .prefs import get as _pget
        key = _best_practice_key(filename)
        return int(_pget(key, 0)) if key else 0
    except Exception:
        return 0


def _set_best_practice(filename, pct):
    try:
        from .prefs import set as _pset
        key = _best_practice_key(filename)
        if key:
            _pset(key, max(0, min(100, int(pct))))
    except Exception:
        pass


def _draw_coin_row(screen, cx, cy, collected, total=3):
    """Three coin slots — filled yellow for collected, hollow outline
    otherwise. Matches the spec's "2/3 with filled/empty coin icons"."""
    coin_w = 22
    gap = 8
    row_w = total * coin_w + (total - 1) * gap
    x = cx - row_w // 2
    for i in range(total):
        filled = i < collected
        c = x + i * (coin_w + gap) + coin_w // 2
        if filled:
            pygame.draw.circle(screen, darker(C_COIN, 40), (c + 1, cy + 1), 10)
            pygame.draw.circle(screen, C_COIN, (c, cy), 10)
            pygame.draw.circle(screen, lighter(C_COIN, 80), (c, cy), 5, 2)
        else:
            pygame.draw.circle(screen, (40, 40, 60), (c, cy), 10, 2)


def _search_modal(screen, clock, items):
    """Filter the level list by author or title. Returns a filtered
    list (possibly identical if the user hit Esc without changing the
    query)."""
    guard = ClickGuard()
    query = ""
    while True:
        guard.tick()
        mpos = pygame.mouse.get_pos()
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    return items
                if ev.key == pygame.K_RETURN:
                    return _apply_query(items, query)
                if ev.key == pygame.K_BACKSPACE:
                    query = query[:-1]
                elif ev.unicode and ev.unicode.isprintable() and len(query) < 40:
                    query += ev.unicode
        draw_bg(screen, 0, _stars())
        ov = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 180))
        screen.blit(ov, (0, 0))
        box = pygame.Rect(WIDTH // 2 - 260, HEIGHT // 2 - 110, 520, 220)
        pygame.draw.rect(screen, C_DARK, box, border_radius=14)
        pygame.draw.rect(screen, C_BLOCK_H, box, 2, border_radius=14)
        txt(screen, "Search levels", box.centerx, box.y + 24,
            22, C_WHITE, True, shadow=True)
        txt(screen, "Filters by title or author", box.centerx, box.y + 50,
            12, C_GRAY, True)
        tf = pygame.Rect(box.x + 40, box.y + 86, box.w - 80, 40)
        pygame.draw.rect(screen, (15, 15, 30), tf, border_radius=6)
        pygame.draw.rect(screen, C_BLOCK_H, tf, 1, border_radius=6)
        txt(screen, query + "|", tf.x + 10, tf.y + 10, 20, C_WHITE)
        preview = _apply_query(items, query)
        txt(screen, f"{len(preview)} match{'' if len(preview) == 1 else 'es'}",
            box.centerx, box.y + 146, 13, C_GRAY, True)
        draw_panel_footer(screen, box,
                          "Enter: apply  ·  Esc: cancel")
        pygame.display.flip()
        clock.tick(settings.get_fps_cap())


def _apply_query(items, query):
    q = query.strip().lower()
    if not q:
        return list(items)
    out = []
    for fn, meta in items:
        name = (meta.get("name") or fn).lower()
        author = (meta.get("author") or "").lower()
        if q in name or q in author:
            out.append((fn, meta))
    return out


def run_select(screen, clock, practice=False):
    """Carousel level-select. One big panel in the center, arrow
    buttons cycle through levels, thumbnail strip along the bottom.

    Only published / verified levels are listed by default. Drafts are
    author-only — they appear when the signed-in user owns them. Until
    the cloud store lands (Chunk F), we treat all local levels as
    visible and authored by the current signed-in user.
    """
    from .prefs import get as _pget
    current_user = _pget("signed_in_username", None)

    summaries = list_level_summaries()
    # Visible set: drafts authored by the current user + everything
    # published. Without a cloud store there's no reliable "who made
    # this" signal, so local drafts are shown unconditionally to keep
    # the single-user workflow working.
    visible = []
    for fn, meta in summaries:
        if meta.get("published") or meta.get("verified"):
            visible.append((fn, meta))
        elif current_user is None:
            visible.append((fn, meta))  # no auth → show everything
        elif meta.get("author") == current_user:
            visible.append((fn, meta))

    def _sort_key(item):
        fn, m = item
        if m.get("verified"):
            bucket = 0
        elif m.get("published"):
            bucket = 1
        else:
            bucket = 2
        return (bucket, (m.get("name") or fn).lower())
    visible.sort(key=_sort_key)

    items = list(visible)
    idx = 0

    stars = _stars()
    mountains = _mountains()
    guard = ClickGuard()
    r_back = r_search = r_left = r_right = r_play = pygame.Rect(0, 0, 0, 0)
    r_help = pygame.Rect(0, 0, 0, 0)

    # Card + arrow layout — defined once so hit-tests and draws share it.
    card_w, card_h = 720, 380
    card_x = WIDTH // 2 - card_w // 2
    card_y = 110
    arrow_w = 64

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
                if ev.key == pygame.K_LEFT and items:
                    idx = (idx - 1) % len(items)
                if ev.key == pygame.K_RIGHT and items:
                    idx = (idx + 1) % len(items)
                if ev.key == pygame.K_RETURN and items:
                    return os.path.join(LEVELS_DIR, items[idx][0])
                if ev.key == pygame.K_m:
                    music.toggle_mute()
                if ev.key == pygame.K_F1 or (
                        ev.key == pygame.K_SLASH and
                        pygame.key.get_mods() & pygame.KMOD_SHIFT):
                    help_modal(screen, clock, "Level Select — Help",
                               _SELECT_HELP_GROUPS)
                    guard.reset()
                elif ev.key == pygame.K_SLASH or (
                        ev.key == pygame.K_f and
                        pygame.key.get_mods() & pygame.KMOD_CTRL):
                    items = _search_modal(screen, clock, visible)
                    idx = 0
                    guard.reset()
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if not guard.consume_click(ev):
                    continue
                if r_back.collidepoint(ev.pos):
                    return None
                if r_help.collidepoint(ev.pos):
                    help_modal(screen, clock, "Level Select — Help",
                               _SELECT_HELP_GROUPS)
                    guard.reset()
                    continue
                if r_search.collidepoint(ev.pos):
                    items = _search_modal(screen, clock, visible)
                    idx = 0
                    guard.reset()
                    continue
                if items and r_left.collidepoint(ev.pos):
                    idx = (idx - 1) % len(items)
                if items and r_right.collidepoint(ev.pos):
                    idx = (idx + 1) % len(items)
                if items and r_play.collidepoint(ev.pos):
                    return os.path.join(LEVELS_DIR, items[idx][0])
            if ev.type == pygame.MOUSEWHEEL and items:
                idx = (idx - ev.y) % len(items)

        draw_bg(screen, 0, stars, mountains)

        title_text = "PRACTICE MODE" if practice else "SELECT LEVEL"
        title_col = (140, 240, 160) if practice else C_WHITE
        txt(screen, title_text, WIDTH // 2, 52, 34, title_col, True, shadow=True)

        # ---- center card ----
        if not items:
            pygame.draw.rect(screen, C_DARK,
                             pygame.Rect(card_x, card_y, card_w, card_h),
                             border_radius=14)
            pygame.draw.rect(screen, C_BLOCK_H,
                             pygame.Rect(card_x, card_y, card_w, card_h),
                             2, border_radius=14)
            txt(screen, "No levels available.",
                WIDTH // 2, card_y + card_h // 2 - 12, 22, C_GRAY, True)
            txt(screen, "Create one in the Level Editor.",
                WIDTH // 2, card_y + card_h // 2 + 16, 14, C_GRAY, True)
        else:
            fn, meta = items[idx]
            _draw_carousel_card(screen, card_x, card_y, card_w, card_h,
                                fn, meta, practice)
            # Play button — sized / coloured by mode.
            play_col = (90, 160, 110) if practice else C_SUCCESS
            play_label = "PRACTICE" if practice else "PLAY"
            r_play = btn(screen, play_label, WIDTH // 2,
                         card_y + card_h + 42, 240, 48, play_col, mpos)

        # ---- arrow buttons ----
        if len(items) > 1:
            arrow_cy = card_y + card_h // 2
            r_left = pygame.Rect(card_x - arrow_w - 12, arrow_cy - 40,
                                 arrow_w, 80)
            r_right = pygame.Rect(card_x + card_w + 12, arrow_cy - 40,
                                  arrow_w, 80)
            for r, glyph in ((r_left, "‹"), (r_right, "›")):
                hov = r.collidepoint(mpos)
                c = lighter(C_BTN, 30) if hov else C_BTN
                pygame.draw.rect(screen, darker(c, 50), r.move(0, 3),
                                 border_radius=8)
                pygame.draw.rect(screen, c, r, border_radius=8)
                pygame.draw.rect(screen, lighter(c, 30), r, 1,
                                 border_radius=8)
                txt(screen, glyph, r.centerx, r.centery, 42,
                    C_WHITE, True)

        # ---- thumbnail strip ----
        if items:
            strip_y = HEIGHT - 110
            strip_h = 52
            slot_w = 80
            slot_gap = 8
            visible_slots = 7
            strip_cx = WIDTH // 2
            # Center the selected slot; others peek on either side.
            start = idx - visible_slots // 2
            for i in range(visible_slots):
                entry_i = start + i
                sx = strip_cx + (i - visible_slots // 2) * (slot_w + slot_gap) - slot_w // 2
                sr = pygame.Rect(sx, strip_y, slot_w, strip_h)
                if 0 <= entry_i < len(items):
                    tfn, tmeta = items[entry_i]
                    scaled = _get_scaled_thumb(tfn, slot_w, strip_h)
                    pygame.draw.rect(screen, darker(C_BTN, 50),
                                     sr, border_radius=5)
                    if scaled is not None:
                        screen.blit(scaled, sr.topleft)
                    sel = (entry_i == idx)
                    border = (255, 220, 120) if sel else (60, 70, 110)
                    pygame.draw.rect(screen, border, sr,
                                     2 if sel else 1, border_radius=5)
                else:
                    # Empty slot — faded.
                    pygame.draw.rect(screen, (26, 26, 40), sr,
                                     border_radius=5)
            # Counter "3 / 27"
            if items:
                txt(screen, f"{idx + 1} / {len(items)}",
                    strip_cx, strip_y + strip_h + 18,
                    13, C_GRAY, True, shadow=True)

        # ---- top bar: search right, back bottom ----
        r_search = btn(screen, "Search", WIDTH - 90, 35, 140, 36,
                       (70, 100, 160), mpos, font_size=14)
        r_help = icon_button(screen, None, WIDTH - 180, 35, 40, 36,
                             (70, 100, 140), mpos)
        txt(screen, "?", r_help.centerx, r_help.centery, 20, C_WHITE,
            True, shadow=True)
        r_back = btn(screen, "BACK", 90, 35, 140, 36, C_DANGER, mpos,
                     font_size=14)

        txt(screen, "← →: cycle  ·  Enter: play  ·  /: search  ·  Esc: back",
            WIDTH // 2, HEIGHT - 28, 12, C_GRAY, True, shadow=True)
        pygame.display.flip()
        clock.tick(settings.get_fps_cap())


def _draw_carousel_card(screen, x, y, w, h, fn, meta, practice):
    """Full-size card for the currently selected level."""
    pygame.draw.rect(screen, darker(C_DARK, 10),
                     pygame.Rect(x, y + 6, w, h), border_radius=14)
    pygame.draw.rect(screen, C_DARK, pygame.Rect(x, y, w, h),
                     border_radius=14)
    pygame.draw.rect(screen, C_BLOCK_H, pygame.Rect(x, y, w, h),
                     2, border_radius=14)

    # Thumbnail across the top (4:1 strip).
    thumb_w = w - 48
    thumb_h = thumb_w // 4
    thumb_x = x + 24
    thumb_y = y + 20
    scaled = _get_scaled_thumb(fn, thumb_w, thumb_h) if fn else None
    if scaled is not None:
        screen.blit(scaled, (thumb_x, thumb_y))
    else:
        pygame.draw.rect(screen, (24, 22, 44),
                         (thumb_x, thumb_y, thumb_w, thumb_h),
                         border_radius=6)
        txt(screen, "(no preview)", thumb_x + thumb_w // 2,
            thumb_y + thumb_h // 2 - 8, 13, C_GRAY, True)
    pygame.draw.rect(screen, lighter(C_DARK, 40),
                     (thumb_x, thumb_y, thumb_w, thumb_h),
                     1, border_radius=6)

    # Title + author + difficulty chip.
    ty = thumb_y + thumb_h + 20
    title = meta.get("name") or (fn or "Untitled")
    if len(title) > 40:
        title = title[:39] + "…"
    txt(screen, title, x + w // 2, ty, 28, C_WHITE, True, shadow=True)
    author = meta.get("author") or "Player"
    txt(screen, f"by {author}", x + w // 2, ty + 34, 14, C_GRAY, True)

    # Difficulty pill.
    diff = meta.get("difficulty", "Normal")
    dc = DIFFICULTY_COLORS.get(diff, C_GRAY)
    pill_w = max(120, 40 + 8 * len(diff))
    pill_rect = pygame.Rect(x + w // 2 - pill_w // 2, ty + 54, pill_w, 26)
    pygame.draw.rect(screen, darker(dc, 40), pill_rect, border_radius=13)
    pygame.draw.rect(screen, dc, pill_rect.inflate(-2, -2), border_radius=12)
    txt(screen, diff, pill_rect.centerx, pill_rect.centery, 14,
        C_WHITE, True, shadow=True)

    # Coin row.
    total_coins = int(meta.get("total_coins", 3))
    got_coins = int(meta.get("coins_collected", 0))
    _draw_coin_row(screen, x + w // 2, ty + 108,
                   min(got_coins, total_coins), total=total_coins)

    # Best % rows — Normal / Practice.
    best_normal = int(meta.get("best_progress", 0))
    best_practice = _get_best_practice(fn)
    bl_y = ty + 142
    _draw_best_stat(screen, x + w // 2 - 140, bl_y,
                    "Best — Normal", best_normal, C_SUCCESS)
    _draw_best_stat(screen, x + w // 2 + 140, bl_y,
                    "Best — Practice", best_practice, (90, 190, 140))

    # Verified badge, if any — top-right of the card.
    if meta.get("verified"):
        bw_, bh_ = 118, 26
        br = pygame.Rect(x + w - bw_ - 18, y + 16, bw_, bh_)
        pygame.draw.rect(screen, darker(C_SUCCESS, 40), br,
                         border_radius=13)
        pygame.draw.rect(screen, C_SUCCESS, br.inflate(-2, -2),
                         border_radius=12)
        txt(screen, "✓ VERIFIED", br.centerx, br.centery, 13,
            C_WHITE, True, shadow=True)
    elif meta.get("published"):
        bw_, bh_ = 100, 26
        br = pygame.Rect(x + w - bw_ - 18, y + 16, bw_, bh_)
        pygame.draw.rect(screen, (50, 50, 80), br, border_radius=13)
        txt(screen, "PUBLISHED", br.centerx, br.centery, 12,
            (200, 220, 255), True)
    else:
        bw_, bh_ = 70, 26
        br = pygame.Rect(x + w - bw_ - 18, y + 16, bw_, bh_)
        pygame.draw.rect(screen, (60, 60, 80), br, border_radius=13)
        txt(screen, "DRAFT", br.centerx, br.centery, 12,
            C_GRAY, True)


def _draw_best_stat(screen, cx, cy, label, pct, color):
    txt(screen, label, cx, cy, 12, C_GRAY, True)
    bar_w = 180
    bar_h = 8
    bar = pygame.Rect(cx - bar_w // 2, cy + 16, bar_w, bar_h)
    pygame.draw.rect(screen, (30, 30, 50), bar, border_radius=4)
    fill_w = max(1, int(bar_w * max(0, min(100, pct)) / 100))
    pygame.draw.rect(screen, color, (bar.x, bar.y, fill_w, bar_h),
                     border_radius=4)
    txt(screen, f"{pct}%", cx, cy + 30, 14, C_WHITE, True, shadow=True)


# ---------------------------------------------------------------------------
# Text input / load dialogs — used by the editor
# ---------------------------------------------------------------------------

def confirm_dialog(screen, clock, prompt, subtitle=None,
                   ok_label="OK", cancel_label="Cancel",
                   ok_color=None, cancel_color=None):
    """Modal yes/no confirmation. Returns True (OK) or False (Cancel/Esc)."""
    stars = _stars()
    guard = ClickGuard()
    if ok_color is None:
        ok_color = C_SUCCESS
    if cancel_color is None:
        cancel_color = C_DANGER
    # Tighter modal — subtitle-to-buttons gap used to have ~80 px of
    # dead space. 40 px height reduction makes the block read as one
    # cohesive unit (UI_AUDIT §6).
    box_w, box_h = 520, 180
    while True:
        guard.tick()
        mpos = pygame.mouse.get_pos()
        box = pygame.Rect(WIDTH // 2 - box_w // 2, HEIGHT // 2 - box_h // 2,
                          box_w, box_h)
        r_ok = pygame.Rect(WIDTH // 2 - 130, box.bottom - 56, 120, 36)
        r_cancel = pygame.Rect(WIDTH // 2 + 10, box.bottom - 56, 120, 36)
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
        draw_panel_footer(screen, box, "Enter/Y: yes  ·  Esc/N: no")
        pygame.display.flip()
        clock.tick(settings.get_fps_cap())


def help_modal(screen, clock, title, groups):
    """Generic keybind help modal. Dismissed with any key or click.

    ``groups`` is a list of ``(group_name, [(key, description), ...])``
    tuples; ``title`` is the screen label shown in the panel header.
    """
    stars = _stars()
    guard = ClickGuard()
    rows = sum(1 + len(items) for _, items in groups)
    panel_w = 560
    panel_h = min(HEIGHT - 40, 120 + rows * 22)
    while True:
        guard.tick()
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if ev.type == pygame.KEYDOWN:
                return
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if guard.consume_click(ev):
                    return
        draw_bg(screen, 0, stars)
        ov = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 200))
        screen.blit(ov, (0, 0))
        panel = pygame.Rect((WIDTH - panel_w) // 2,
                            (HEIGHT - panel_h) // 2,
                            panel_w, panel_h)
        pygame.draw.rect(screen, darker(C_DARK, 10), panel.move(0, 4),
                         border_radius=14)
        pygame.draw.rect(screen, C_DARK, panel, border_radius=14)
        pygame.draw.rect(screen, C_BLOCK_H, panel, 2, border_radius=14)
        txt(screen, title, panel.centerx, panel.y + 22, 20, C_WHITE,
            True, shadow=True)
        y = panel.y + 54
        for grp_name, items in groups:
            txt(screen, grp_name, panel.x + 28, y, 14,
                (180, 200, 255))
            y += 22
            for key, desc in items:
                txt(screen, key, panel.x + 46, y, 13, C_WHITE)
                txt(screen, desc, panel.x + 220, y, 13, C_GRAY)
                y += 20
            y += 6
        draw_panel_footer(screen, panel,
                          "Press any key or click to close")
        pygame.display.flip()
        clock.tick(settings.get_fps_cap())


def text_input_dialog(screen, clock, prompt="Enter name:", default=""):
    text = default
    stars = _stars()
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
        draw_panel_footer(screen, box, "Enter to confirm  ·  Esc to cancel")
        pygame.display.flip()
        clock.tick(settings.get_fps_cap())


def difficulty_picker(screen, clock, prompt="Choose difficulty:", default="Normal",
                      subtitle=None):
    """Modal difficulty picker. Returns the chosen difficulty string or None.

    Used both by the editor's publish flow (publisher *requests* a difficulty)
    and by the play win-screen on first verification (verifier *sets* the
    final official difficulty).
    """
    stars = _stars()
    guard = ClickGuard()
    selected = default if default in DIFFICULTIES else "Normal"
    # Wider buttons + more gap so long labels (Harder / Insane / Demon)
    # have breathing room — the previous 130 px width put the text
    # nearly flush against the rounded corners.
    btn_h = 42
    btn_w = 150
    gap = 10
    cols = 4
    # Lay out as a grid of `cols` wide. DIFFICULTIES currently has 11
    # entries and cols=4, so rows=3 and the trailing 12th cell is
    # rendered as a subdued empty placeholder to keep the grid
    # rectangular (UI_AUDIT §8).
    rows = (len(DIFFICULTIES) + cols - 1) // cols
    box_w = cols * btn_w + (cols - 1) * gap + 60
    # +100 at the bottom reserves space for OK/Cancel AND the keyboard
    # hint line so they don't overlap (fixed a UI regression).
    box_h = 130 + rows * (btn_h + gap) + 100
    r_ok = r_cancel = pygame.Rect(0, 0, 0, 0)
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
        # Render ghost placeholders for any empty trailing slots so the
        # grid stays visually rectangular even though len(DIFFICULTIES)
        # isn't a multiple of `cols`.
        total_slots = rows * cols
        for i in range(len(DIFFICULTIES), total_slots):
            r = _diff_btn_rect(i, btn_w, btn_h, gap, cols, box_w, box_h)
            pygame.draw.rect(screen, (30, 30, 44), r, border_radius=8)
            pygame.draw.rect(screen, (55, 55, 70), r, 1, border_radius=8)
        # Confirm + Cancel — sit above the keyboard-hint line so they
        # never overlap.
        r_ok = pygame.Rect(WIDTH // 2 - 110, box.bottom - 78, 100, 36)
        r_cancel = pygame.Rect(WIDTH // 2 + 10, box.bottom - 78, 100, 36)
        for r, label, col in [(r_ok, "OK", C_SUCCESS), (r_cancel, "Cancel", C_DANGER)]:
            hov = r.collidepoint(mpos)
            c = lighter(col, 30) if hov else col
            pygame.draw.rect(screen, darker(c, 60), r.move(0, 3), border_radius=8)
            pygame.draw.rect(screen, c, r, border_radius=8)
            txt(screen, label, r.centerx, r.centery, 16, C_WHITE, True)
        draw_panel_footer(screen, box, "Enter: confirm  ·  Esc: cancel")
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
    stars = _stars()
    guard = ClickGuard()
    # Size the dialog to the actual row count (cap at 7 visible rows).
    # Old code reserved space for ~10 rows regardless, leaving a big
    # empty band in the middle when the user only had a few levels.
    row_h = 44
    header_h = 60
    footer_h = 40
    max_visible = 7
    visible_rows = max(1, min(max_visible, len(summaries) or 1))
    box_w = 460
    box_h = header_h + visible_rows * row_h + footer_h
    box_x = WIDTH // 2 - box_w // 2
    box_y = (HEIGHT - box_h) // 2
    row_x = box_x + 40
    row_w = box_w - 80
    list_top = box_y + header_h
    list_bottom = list_top + visible_rows * row_h
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
                    y = list_top + i * row_h - scroll
                    r = pygame.Rect(row_x, y + 3, row_w, row_h - 6)
                    if list_top <= y <= list_bottom and r.collidepoint(ev.pos):
                        return os.path.join(LEVELS_DIR, fn)
            if ev.type == pygame.MOUSEWHEEL:
                max_scroll = max(0, len(summaries) * row_h - visible_rows * row_h)
                scroll = max(0, min(max_scroll, scroll - ev.y * 30))
        draw_bg(screen, 0, stars)
        ov = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 180))
        screen.blit(ov, (0, 0))
        box = pygame.Rect(box_x, box_y, box_w, box_h)
        pygame.draw.rect(screen, C_DARK, box, border_radius=14)
        pygame.draw.rect(screen, C_BLOCK_H, box, 2, border_radius=14)
        txt(screen, "Load Level", box.centerx, box_y + 24, 28, C_WHITE, True)
        prev_clip = screen.get_clip()
        screen.set_clip(pygame.Rect(box.x + 4, list_top - 2,
                                    box.w - 8, visible_rows * row_h + 4))
        if not summaries:
            txt(screen, "No levels found.",
                box.centerx, list_top + 40, 18, C_GRAY, True)
        for i, (fn, meta) in enumerate(summaries):
            y = list_top + i * row_h - scroll
            if list_top - row_h < y < list_bottom:
                r = pygame.Rect(row_x, y + 3, row_w, row_h - 6)
                c = C_BTN_H if r.collidepoint(mpos) else C_BTN
                pygame.draw.rect(screen, c, r, border_radius=6)
                diff = meta.get("difficulty", "Normal")
                dc = DIFFICULTY_COLORS.get(diff, C_GRAY)
                pygame.draw.rect(screen, dc, (r.x + 4, r.y + 4, 6, r.h - 8), border_radius=3)
                # Clip the title so the status icon (at r.right - 22) has
                # guaranteed room to the right.
                title = meta.get("name") or fn.replace(".json", "")
                if len(title) > 26:
                    title = title[:25] + "…"
                txt(screen, title, r.x + 18, r.y + 11, 17, C_WHITE)
                # Status icon
                if meta.get("verified"):
                    txt(screen, "✓", r.right - 22, r.y + 11, 16, C_SUCCESS)
                elif meta.get("published"):
                    txt(screen, "◦", r.right - 22, r.y + 11, 16, C_PUBLISH)
        screen.set_clip(prev_clip)
        # Faint scroll indicator — "there's more below" affordance.
        total_rows = len(summaries)
        if total_rows > visible_rows:
            track_x = box.right - 14
            track_h = visible_rows * row_h
            pygame.draw.rect(screen, (40, 40, 60),
                             (track_x, list_top, 4, track_h), border_radius=2)
            max_scroll = max(1, total_rows * row_h - track_h)
            bar_h = max(24, int(track_h * visible_rows / total_rows))
            bar_y = list_top + int((track_h - bar_h) * (scroll / max_scroll))
            pygame.draw.rect(screen, (120, 160, 220),
                             (track_x, bar_y, 4, bar_h), border_radius=2)
        draw_panel_footer(screen, box, "Click a row to load  ·  Esc: cancel")
        pygame.display.flip()
        clock.tick(settings.get_fps_cap())


def snippet_picker(screen, clock):
    """Modal snippet picker. Returns (name, objects, is_user) or None.

    Shows the built-in snippets followed by user snippets, with miniature
    thumbnails rendered using the live `draw_obj`. Click a row to "pick up"
    that snippet; the editor then drops it where the user clicks next.
    Right-click a user snippet to delete it (built-ins are immutable).
    """
    from .snippets import get_snippets, delete_user_snippet

    stars = _stars()
    guard = ClickGuard()
    scroll = 0
    # Panel sized so the list area ends on a WHOLE-row boundary — the
    # old layout left a half-row peeking past the footer, which reads
    # as a clipping bug rather than an intentional "scroll for more"
    # affordance (UI_AUDIT §10).
    header_h = 70
    footer_h = 36
    row_h = 70
    visible_rows = 6
    box_w = 560
    box_h = header_h + visible_rows * row_h + footer_h
    box_x = WIDTH // 2 - box_w // 2
    box_y = (HEIGHT - box_h) // 2
    list_x = box_x + 18
    list_y = box_y + header_h
    list_w = box_w - 36
    visible_h = visible_rows * row_h

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
        # Scroll indicator — tells the user there's more below even when
        # no partial row is visible at the bottom.
        total_rows = len(snippets)
        if total_rows > visible_rows:
            track_x = box_x + box_w - 14
            pygame.draw.rect(screen, (40, 40, 60),
                             (track_x, list_y, 4, visible_h),
                             border_radius=2)
            max_scroll = max(1, total_rows * row_h - visible_h)
            bar_h = max(24, int(visible_h * visible_rows / total_rows))
            bar_y = list_y + int((visible_h - bar_h) * (scroll / max_scroll))
            pygame.draw.rect(screen, (120, 160, 220),
                             (track_x, bar_y, 4, bar_h), border_radius=2)
        _box = pygame.Rect(box_x, box_y, box_w, box_h)
        draw_panel_footer(screen, _box, "Esc: cancel  ·  Scroll to browse")
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


def run_editor_picker(screen, clock):
    """Pre-editor picker — lists the signed-in user's levels plus a
    "New level" tile. Returns one of:

        ("open", filename)  — open this level in the editor
        ("new", None)       — start an empty level
        None                — user backed out

    Ownership model: a level is editable only by the user whose
    username is stamped in its meta.author field. The picker filters to
    show just those — levels authored by someone else are hidden (you
    still see them in the play-side level select, you just can't edit
    them). A legacy file with no author or one stamped "Player" is
    treated as the current user's (pre-auth dev checkouts).

    Delete: each row has an ×  button in the right margin. Clicking it
    prompts for confirmation, then removes the level JSON + thumbnail.
    """
    from .prefs import get as _pget
    current_user = _pget("signed_in_username", None)

    def _load_my_levels():
        summaries = list_level_summaries()
        if current_user is None:
            # Not signed in → single-user dev workflow; everything on
            # disk is considered mine.
            out = list(summaries)
        else:
            out = []
            for fn, meta in summaries:
                author = (meta.get("author") or "").strip()
                if author == current_user or author in ("", "Player"):
                    out.append((fn, meta))
        out.sort(key=lambda e: (e[1].get("name") or e[0]).lower())
        return out

    my_levels = _load_my_levels()

    stars = _stars()
    mountains = _mountains()
    guard = ClickGuard()
    scroll = 0
    row_h = 54
    header_h = 96
    footer_h = 60
    visible_rows = 7
    box_w = 640
    box_h = header_h + (visible_rows + 1) * row_h + footer_h  # +1 = "New"
    box_x = WIDTH // 2 - box_w // 2
    box_y = (HEIGHT - box_h) // 2

    while True:
        guard.tick()
        mpos = pygame.mouse.get_pos()
        click_pos = None
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                return None
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_n:
                return ("new", None)
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if not guard.consume_click(ev):
                    continue
                click_pos = ev.pos
            if ev.type == pygame.MOUSEWHEEL:
                max_scroll = max(0, (len(my_levels)) * row_h
                                 - visible_rows * row_h)
                scroll = max(0, min(max_scroll, scroll - ev.y * 30))

        draw_bg(screen, 0, stars, mountains)
        ov = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 170))
        screen.blit(ov, (0, 0))
        box = pygame.Rect(box_x, box_y, box_w, box_h)
        pygame.draw.rect(screen, C_DARK, box, border_radius=14)
        pygame.draw.rect(screen, C_BLOCK_H, box, 2, border_radius=14)
        txt(screen, "LEVEL EDITOR", box.centerx, box_y + 26,
            26, C_WHITE, True, shadow=True)
        sub = "Open a level you've made — or start fresh."
        txt(screen, sub, box.centerx, box_y + 56, 13, C_GRAY, True)

        # "New level" tile — always at the top.
        new_rect = pygame.Rect(box_x + 24, box_y + header_h,
                               box_w - 48, row_h - 8)
        hov = new_rect.collidepoint(mpos)
        c = lighter((80, 130, 90), 20) if hov else (80, 130, 90)
        pygame.draw.rect(screen, darker(c, 40), new_rect.move(0, 3),
                         border_radius=8)
        pygame.draw.rect(screen, c, new_rect, border_radius=8)
        txt(screen, "+ New level", new_rect.x + 20, new_rect.y + 14,
            18, C_WHITE, shadow=True)
        txt(screen, "[N]", new_rect.right - 40, new_rect.y + 18,
            12, C_GRAY)
        if click_pos and new_rect.collidepoint(click_pos):
            return ("new", None)

        # Scrollable "my levels" list.
        list_top = box_y + header_h + row_h
        list_bottom = list_top + visible_rows * row_h
        prev_clip = screen.get_clip()
        screen.set_clip(pygame.Rect(box_x + 4, list_top - 2,
                                    box_w - 8, visible_rows * row_h + 4))
        if not my_levels:
            txt(screen, "No levels of your own yet — hit '+ New level'.",
                box.centerx, list_top + 40, 14, C_GRAY, True)
        pending_delete = None  # filename to delete after the render pass
        for i, (fn, meta) in enumerate(my_levels):
            y = list_top + i * row_h - scroll
            if y + row_h < list_top - row_h or y > list_bottom:
                continue
            r = pygame.Rect(box_x + 24, y + 3, box_w - 48, row_h - 8)
            hov = r.collidepoint(mpos)
            c = C_BTN_H if hov else C_BTN
            pygame.draw.rect(screen, darker(c, 40), r.move(0, 3),
                             border_radius=8)
            pygame.draw.rect(screen, c, r, border_radius=8)
            # Difficulty chip
            diff = meta.get("difficulty", "Normal")
            dc = DIFFICULTY_COLORS.get(diff, C_GRAY)
            pygame.draw.rect(screen, dc,
                             (r.x + 6, r.y + 6, 6, r.h - 12),
                             border_radius=3)
            name = meta.get("name") or fn
            if len(name) > 36:
                name = name[:35] + "…"
            txt(screen, name, r.x + 20, r.y + 8, 17, C_WHITE)
            if meta.get("verified"):
                state, state_col = "VERIFIED", C_SUCCESS
            elif meta.get("published"):
                state, state_col = "PUBLISHED", C_PUBLISH
            else:
                state, state_col = "DRAFT", C_GRAY
            txt(screen, state, r.right - 130, r.y + 14, 11, state_col)
            # Delete button (×) — inset from the right edge, only fires
            # on the button's own rect so clicking it doesn't also open
            # the level.
            del_rect = pygame.Rect(r.right - 38, r.y + 8, 26, 26)
            del_hov = del_rect.collidepoint(mpos)
            del_col = C_DANGER if del_hov else (120, 60, 70)
            pygame.draw.rect(screen, del_col, del_rect, border_radius=6)
            pygame.draw.rect(screen, darker(del_col, 40), del_rect, 1,
                             border_radius=6)
            txt(screen, "×", del_rect.centerx, del_rect.centery - 1,
                18, C_WHITE, True, shadow=True)
            if click_pos and del_rect.collidepoint(click_pos):
                pending_delete = fn
                click_pos = None  # swallow so row-click doesn't also fire
            elif click_pos and r.collidepoint(click_pos):
                screen.set_clip(prev_clip)
                return ("open", fn)
        screen.set_clip(prev_clip)

        # Handle deletion after the render pass — confirm_dialog takes
        # over the screen, so we don't want to interleave its frames
        # with the picker's loop. When it returns, refresh the list so
        # the deleted row disappears.
        if pending_delete is not None:
            _to_del = pending_delete
            _meta = next((m for f, m in my_levels if f == _to_del), {})
            _nm = _meta.get("name") or _to_del
            ok = confirm_dialog(
                screen, clock,
                f"Delete '{_nm}'?",
                subtitle="This removes the level file from your disk. "
                         "Cannot be undone.",
                ok_label="Delete", cancel_label="Keep",
            )
            guard.reset()
            if ok:
                try:
                    _path = os.path.join(LEVELS_DIR, _to_del)
                    if os.path.isfile(_path):
                        os.remove(_path)
                    # Thumbnails live in levels/_thumbs/ with a .png
                    # matching the JSON stem — drop that too so the
                    # carousel doesn't keep showing a preview for a
                    # level that no longer exists.
                    _thumb = os.path.join(LEVELS_DIR, "_thumbs",
                                          _to_del.replace(".json", ".png"))
                    if os.path.isfile(_thumb):
                        os.remove(_thumb)
                except OSError:
                    pass
                my_levels = _load_my_levels()
                # Snap scroll if we shrunk past the current window.
                max_scroll = max(0, len(my_levels) * row_h
                                 - visible_rows * row_h)
                scroll = min(scroll, max_scroll)

        b_back = btn(screen, "BACK", box.centerx,
                     box.bottom - 28, 200, 34, C_DANGER, mpos,
                     font_size=14)
        if click_pos and b_back.collidepoint(click_pos):
            return None

        pygame.display.flip()
        clock.tick(settings.get_fps_cap())


def run_settings(screen, clock, on_fullscreen_change=None):
    """Settings panel — adjusts FPS cap, fullscreen, volumes and mutes.

    This is the first pygame_gui-backed screen in the project. The rest
    of the menus still hand-roll their widgets; this one proves out the
    integration and gives us a reusable theme file at
    ``assets/ui/theme.json``.
    """
    import os
    try:
        import pygame_gui
    except ImportError:
        # Dep not installed — show a friendly modal instead of crashing
        # the gear icon. Users who skipped `pip install -r requirements.txt`
        # will see this and can install the missing package.
        confirm_dialog(
            screen, clock,
            "Settings panel needs pygame_gui.",
            subtitle="Run: pip install -r requirements.txt",
            ok_label="OK", cancel_label="",
        )
        return

    stars = _stars()
    mountains = _mountains()
    guard = ClickGuard()
    from .constants import ASSETS_DIR as _ASSETS_DIR
    theme_path = os.path.join(_ASSETS_DIR, "ui", "theme.json")
    manager = pygame_gui.UIManager((WIDTH, HEIGHT),
                                   theme_path if os.path.isfile(theme_path)
                                   else None)

    panel_w, panel_h = 540, 620
    panel_rect = pygame.Rect((WIDTH - panel_w) // 2,
                             (HEIGHT - panel_h) // 2,
                             panel_w, panel_h)
    panel_widget = pygame_gui.elements.UIPanel(
        relative_rect=panel_rect, manager=manager,
    )
    pygame_gui.elements.UILabel(
        relative_rect=pygame.Rect((0, 10), (panel_w, 40)),
        text="Settings",
        manager=manager, container=panel_widget,
        object_id=pygame_gui.core.ObjectID(object_id="#heading",
                                           class_id="@heading"),
    )

    row_y = 60
    label_x, label_w = 32, 180
    ctrl_x = 230
    ctrl_w = 260

    # ---- FPS cap cycle button --------------------------------------------
    pygame_gui.elements.UILabel(
        relative_rect=pygame.Rect((label_x, row_y + 4), (label_w, 28)),
        text="FPS cap (render)", manager=manager, container=panel_widget,
    )
    fps_btn = pygame_gui.elements.UIButton(
        relative_rect=pygame.Rect((ctrl_x, row_y), (ctrl_w, 36)),
        text=settings.fps_cap_label(),
        manager=manager, container=panel_widget,
    )
    row_y += 50

    # ---- Fullscreen toggle ------------------------------------------------
    pygame_gui.elements.UILabel(
        relative_rect=pygame.Rect((label_x, row_y + 4), (label_w, 28)),
        text="Fullscreen", manager=manager, container=panel_widget,
    )
    fs_btn = pygame_gui.elements.UIButton(
        relative_rect=pygame.Rect((ctrl_x, row_y), (ctrl_w, 36)),
        text="On" if settings.get_fullscreen() else "Off",
        manager=manager, container=panel_widget,
    )
    row_y += 50

    # ---- Music volume slider ---------------------------------------------
    pygame_gui.elements.UILabel(
        relative_rect=pygame.Rect((label_x, row_y + 4), (label_w, 28)),
        text="Music volume", manager=manager, container=panel_widget,
    )
    music_slider = pygame_gui.elements.UIHorizontalSlider(
        relative_rect=pygame.Rect((ctrl_x, row_y + 4), (ctrl_w - 60, 28)),
        start_value=settings.get_music_vol() * 100.0,
        value_range=(0.0, 100.0),
        manager=manager, container=panel_widget,
    )
    music_pct_label = pygame_gui.elements.UILabel(
        relative_rect=pygame.Rect((ctrl_x + ctrl_w - 54, row_y + 4), (54, 28)),
        text=f"{int(round(settings.get_music_vol() * 100))}%",
        manager=manager, container=panel_widget,
    )
    row_y += 46

    # ---- SFX volume slider ------------------------------------------------
    pygame_gui.elements.UILabel(
        relative_rect=pygame.Rect((label_x, row_y + 4), (label_w, 28)),
        text="SFX volume", manager=manager, container=panel_widget,
    )
    sfx_slider = pygame_gui.elements.UIHorizontalSlider(
        relative_rect=pygame.Rect((ctrl_x, row_y + 4), (ctrl_w - 60, 28)),
        start_value=settings.get_sfx_vol() * 100.0,
        value_range=(0.0, 100.0),
        manager=manager, container=panel_widget,
    )
    sfx_pct_label = pygame_gui.elements.UILabel(
        relative_rect=pygame.Rect((ctrl_x + ctrl_w - 54, row_y + 4), (54, 28)),
        text=f"{int(round(settings.get_sfx_vol() * 100))}%",
        manager=manager, container=panel_widget,
    )
    row_y += 46

    # ---- Mute toggles -----------------------------------------------------
    pygame_gui.elements.UILabel(
        relative_rect=pygame.Rect((label_x, row_y + 4), (label_w, 28)),
        text="Mute music", manager=manager, container=panel_widget,
    )
    music_mute_btn = pygame_gui.elements.UIButton(
        relative_rect=pygame.Rect((ctrl_x, row_y), (ctrl_w, 36)),
        text="Muted" if music.is_muted() else "Not muted",
        manager=manager, container=panel_widget,
        object_id=pygame_gui.core.ObjectID(
            object_id="#danger_button" if music.is_muted() else None,
            class_id="@mute_button"),
    )
    row_y += 50

    pygame_gui.elements.UILabel(
        relative_rect=pygame.Rect((label_x, row_y + 4), (label_w, 28)),
        text="Mute SFX", manager=manager, container=panel_widget,
    )
    sfx_mute_btn = pygame_gui.elements.UIButton(
        relative_rect=pygame.Rect((ctrl_x, row_y), (ctrl_w, 36)),
        text="Muted" if sfx.is_muted() else "Not muted",
        manager=manager, container=panel_widget,
        object_id=pygame_gui.core.ObjectID(
            object_id="#danger_button" if sfx.is_muted() else None,
            class_id="@mute_button"),
    )
    row_y += 60

    # ---- Links to separate screens (Customize + Music library) ----------
    # These were top-level buttons on the old main menu; the redesign
    # moved them behind the gear icon so the main menu stays focused
    # on "Play / Practice / Editor / Quit".
    extras_y = row_y + 6
    customize_btn = pygame_gui.elements.UIButton(
        relative_rect=pygame.Rect((label_x, extras_y), (ctrl_w // 2 - 8, 36)),
        text="Customize…", manager=manager, container=panel_widget,
        object_id=pygame_gui.core.ObjectID(object_id="#subtle_button"),
    )
    music_lib_btn = pygame_gui.elements.UIButton(
        relative_rect=pygame.Rect(
            (label_x + ctrl_w // 2 + 8, extras_y),
            (ctrl_w // 2 - 8, 36)),
        text="Music library…", manager=manager, container=panel_widget,
        object_id=pygame_gui.core.ObjectID(object_id="#subtle_button"),
    )

    # ---- Reset + Back (footer) -------------------------------------------
    footer_y = panel_h - 60
    reset_btn = pygame_gui.elements.UIButton(
        relative_rect=pygame.Rect((label_x, footer_y), (200, 36)),
        text="Reset to defaults",
        manager=manager, container=panel_widget,
        object_id=pygame_gui.core.ObjectID(object_id="#subtle_button"),
    )
    back_btn = pygame_gui.elements.UIButton(
        relative_rect=pygame.Rect((panel_w - 200 - label_x, footer_y),
                                  (200, 36)),
        text="Back",
        manager=manager, container=panel_widget,
        object_id=pygame_gui.core.ObjectID(object_id="#danger_button"),
    )

    def _refresh_labels():
        fps_btn.set_text(settings.fps_cap_label())
        fs_btn.set_text("On" if settings.get_fullscreen() else "Off")
        music_mute_btn.set_text("Muted" if music.is_muted() else "Not muted")
        sfx_mute_btn.set_text("Muted" if sfx.is_muted() else "Not muted")
        music_pct_label.set_text(
            f"{int(round(settings.get_music_vol() * 100))}%")
        sfx_pct_label.set_text(
            f"{int(round(settings.get_sfx_vol() * 100))}%")

    running = True
    while running:
        guard.tick()
        dt = clock.tick(settings.get_fps_cap()) / 1000.0
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                running = False
                break
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if not guard.consume_click(ev):
                    # Swallow residual entry click so pygame_gui doesn't
                    # see it — widgets otherwise fire on screen entry.
                    continue
            if ev.type == pygame_gui.UI_BUTTON_PRESSED:
                if ev.ui_element is fps_btn:
                    settings.cycle_fps_cap()
                elif ev.ui_element is fs_btn:
                    settings.toggle_fullscreen()
                    if on_fullscreen_change is not None:
                        try:
                            on_fullscreen_change()
                        except Exception:
                            pass
                elif ev.ui_element is music_mute_btn:
                    music.toggle_mute()
                elif ev.ui_element is sfx_mute_btn:
                    sfx.toggle_mute()
                elif ev.ui_element is reset_btn:
                    settings.reset_to_defaults()
                    if music.is_muted():
                        music.toggle_mute()
                    if sfx.is_muted():
                        sfx.toggle_mute()
                    if settings.get_fullscreen() != settings.DEFAULTS["fullscreen"]:
                        settings.set_fullscreen(settings.DEFAULTS["fullscreen"])
                        if on_fullscreen_change is not None:
                            try:
                                on_fullscreen_change()
                            except Exception:
                                pass
                    music_slider.set_current_value(
                        settings.get_music_vol() * 100.0)
                    sfx_slider.set_current_value(
                        settings.get_sfx_vol() * 100.0)
                elif ev.ui_element is customize_btn:
                    # Close the settings modal, open Customize, reopen
                    # settings on return. Simplest way to avoid two
                    # UIManagers fighting for events.
                    manager.clear_and_reset()
                    run_customize(screen, clock)
                    return run_settings(screen, clock,
                                        on_fullscreen_change=on_fullscreen_change)
                elif ev.ui_element is music_lib_btn:
                    from .music_menu import run_music_menu
                    manager.clear_and_reset()
                    run_music_menu(screen, clock)
                    return run_settings(screen, clock,
                                        on_fullscreen_change=on_fullscreen_change)
                elif ev.ui_element is back_btn:
                    running = False
                    break
                _refresh_labels()
            if ev.type == pygame_gui.UI_HORIZONTAL_SLIDER_MOVED:
                if ev.ui_element is music_slider:
                    settings.set_music_vol(ev.value / 100.0)
                    music_pct_label.set_text(
                        f"{int(round(ev.value))}%")
                elif ev.ui_element is sfx_slider:
                    settings.set_sfx_vol(ev.value / 100.0)
                    sfx_pct_label.set_text(f"{int(round(ev.value))}%")
            manager.process_events(ev)
        if not running:
            break
        manager.update(dt)
        # Preserve the original "parallax bg with a dim overlay" look so
        # the settings screen doesn't jump stylistically when migrated.
        draw_bg(screen, 0, stars, mountains)
        _dim = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        _dim.fill((0, 0, 0, 160))
        screen.blit(_dim, (0, 0))
        manager.draw_ui(screen)
        # Gamepad status — outside the pygame_gui tree, to match the
        # rest of the app's overlay style.
        if gamepad.is_connected():
            lbl = f"Gamepad: {gamepad.name() or 'connected'}"
            txt(screen, lbl, WIDTH // 2, panel_rect.bottom - 36,
                12, C_SUCCESS, True)
        draw_panel_footer(screen, panel_rect,
                          "Esc: back  ·  Drag sliders to adjust")
        pygame.display.flip()

    # Clean up pygame_gui's internal state so re-entering the menu builds
    # fresh widgets.
    manager.clear_and_reset()


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
    stars = _stars()
    mountains = _mountains()
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
                      panel.bottom - 64, 200, 36, (100, 100, 120), mpos,
                      font_size=14)
        if click_pos and b_reset.collidepoint(click_pos):
            settings.set_player_color_index(
                settings.DEFAULTS["player_color_index"])
            settings.set_player_icon_index(
                settings.DEFAULTS["player_icon_index"])

        b_back = btn(screen, "BACK", panel.x + panel.w - 130,
                     panel.bottom - 64, 200, 36, C_DANGER, mpos, font_size=14)
        if click_pos and b_back.collidepoint(click_pos):
            return

        draw_panel_footer(
            screen, panel,
            "Click a tile to select  ·  Arrows: cycle  ·  Esc: back")
        pygame.display.flip()
        clock.tick(settings.get_fps_cap())
