#!/usr/bin/env python3
"""Entry point.

Initializes pygame/audio, seeds the levels directory with a Tutorial, and
owns the top-level state machine (menu ↔ select ↔ play ↔ editor).
"""

import os
import sys

# Game modules live under src/. Make them importable before anything
# else is loaded. PyInstaller uses the spec's `pathex` for the same
# reason at freeze time; this block covers plain `python main.py`.
_SRC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
if os.path.isdir(_SRC_DIR) and _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

import pygame

from constants import WIDTH, HEIGHT, ASSETS_DIR
from editor import run_editor

from levels import ensure_dirs, load_level_full
import music
import sfx
import settings
import gamepad
from menus import (run_menu, run_select, run_settings, run_customize,
                   run_editor_picker)
from music_menu import run_music_menu
from play import run_play


def _set_window_icon():
    """Set the window icon from `assets/icon.png` if it's shipped.

    The OS launcher / taskbar icon is controlled by the packaging step
    (Windows `.ico`, macOS `.icns`); this only sets the in-session
    window icon, which pygame draws in the titlebar on platforms that
    have one. Silent on missing file so headless runs and dev checkouts
    without the asset still boot.
    """
    for name in ("icon.png", "icon.bmp"):
        path = os.path.join(ASSETS_DIR, name)
        if os.path.isfile(path):
            try:
                pygame.display.set_icon(pygame.image.load(path))
            except pygame.error:
                pass
            return


def apply_display_mode():
    """Re-apply the windowed/fullscreen setting and return the surface.

    Called on startup and again whenever the Settings screen toggles
    fullscreen so the change takes effect immediately.
    """
    flags = pygame.FULLSCREEN if settings.get_fullscreen() else 0
    return pygame.display.set_mode((WIDTH, HEIGHT), flags)


def main():
    pygame.init()
    screen = apply_display_mode()
    pygame.display.set_caption("Trigonometry Sprint")
    _set_window_icon()
    clock = pygame.time.Clock()

    # Filesystem + audio init. Built-in levels were removed — the user
    # creates their own. `ensure_dirs()` only guarantees the empty
    # `levels/` directory exists.
    ensure_dirs()
    music.init()
    sfx.init()
    gamepad.init()

    state = "menu"
    while state != "quit":
        if state == "menu":
            state = run_menu(screen, clock)
        elif state in ("play", "practice"):
            _practice = state == "practice"
            path = run_select(screen, clock, practice=_practice)
            if path:
                try:
                    meta, objects = load_level_full(path)
                except (OSError, ValueError):
                    state = "menu"
                    continue
                run_play(
                    screen, clock, objects,
                    level_name=meta["name"],
                    level_music=meta.get("music"),
                    meta=meta,
                    level_path=path,
                    practice_mode=_practice,
                )
            state = "menu"
        elif state == "editor":
            pick = run_editor_picker(screen, clock)
            if pick is not None:
                action, fn = pick
                # The editor owns its own load flow (autosave recovery
                # prompt, internal Load dialog); for now "New" just
                # runs the editor with its default empty level, and
                # "Open" loads via the editor's Ctrl+L path. A proper
                # preloaded-level path is Chunk E+F work.
                run_editor(screen, clock, preload_filename=fn if action == "open" else None)
            state = "menu"
        elif state == "settings":
            # Settings is a modal now — opens over the menu, returns
            # directly when closed. run_settings handles fullscreen
            # toggles internally so we just re-apply the display in
            # case one happened.
            run_settings(screen, clock, on_fullscreen_change=apply_display_mode)
            screen = apply_display_mode()
            state = "menu"
        elif state == "auth":
            # Chunk F will wire this to the real AuthStore. For now the
            # stub just toggles a local pref so the main menu shows
            # either "Login/Signup" or "Signed in: X".
            _auth_stub(screen, clock)
            state = "menu"
    pygame.quit()
    sys.exit()


def _auth_stub(screen, clock):
    """Login / signup modal.

    Uses the `AuthStore` factory from `stores.py` so it works against
    the real FastAPI server when `TRIGSPRINT_SERVER_URL` is set, and
    falls back to the local disk store when offline / for tests.
    """
    from menus import text_input_dialog, confirm_dialog
    from stores import get_stores
    auth, _ = get_stores()
    cur = auth.current_username()
    if cur:
        if confirm_dialog(screen, clock,
                          f"Sign out of '{cur}'?",
                          ok_label="Sign out", cancel_label="Stay"):
            auth.logout()
        return
    username = text_input_dialog(screen, clock,
                                 prompt="Username:")
    if not username:
        return
    password = text_input_dialog(screen, clock,
                                 prompt="Password (min 8):")
    if not password:
        return
    # Try login first; if that fails with a valid-looking username/
    # password, offer signup.
    if auth.login(username, password):
        return
    if confirm_dialog(screen, clock,
                      f"Create account '{username}'?",
                      subtitle="No existing user — sign up instead.",
                      ok_label="Sign up", cancel_label="Cancel"):
        if not auth.signup(username, password):
            confirm_dialog(screen, clock,
                           "Signup failed.",
                           subtitle="Username taken or password too short.",
                           ok_label="OK", cancel_label="")


if __name__ == "__main__":
    main()
