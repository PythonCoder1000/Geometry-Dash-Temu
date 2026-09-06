#!/usr/bin/env python3
"""Entry point.

Initializes pygame/audio, seeds the levels directory with a Tutorial, and
owns the top-level state machine (menu ↔ select ↔ play ↔ editor).
"""

import os
import sys

# When the script is launched as ``python main.py`` the CWD is usually
# the repo root; when launched via a frozen bundle the parent of this
# file is the app root. Either way, make sure the repo root is on
# sys.path so `import src.*` resolves cleanly.
_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import pygame

from src.constants import WIDTH, HEIGHT, ASSETS_DIR
from src.editor import run_editor
from src.levels import ensure_dirs, load_level_full
from src import music, sfx, settings, gamepad
from src.menus import (run_menu, run_select, run_settings,
                       run_editor_picker, run_rate_menu)
from src.play import run_play


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
        try:
            state = _dispatch_state(screen, clock, state)
        except SystemExit:
            raise
        except Exception as exc:
            # Don't crash the process on an uncaught exception —
            # print the traceback so the user can read what went
            # wrong, then surface a modal so they can save / quit
            # deliberately. The editor's autosave keeps in-progress
            # level work on disk regardless.
            import traceback as _tb
            _tb.print_exc()
            from src.editor import _show_error_modal
            _show_error_modal(screen, clock, exc, where="game")
            # Bounce back to the main menu — the only screen that's
            # guaranteed to be safe after a crash. The user can re-
            # open the editor to load their autosave.
            state = "menu"
        # If a settings toggle re-created the display surface during
        # this iteration, the local ``screen`` reference is stale —
        # refresh it from pygame so the next dispatch draws onto the
        # current surface.
        cur = pygame.display.get_surface()
        if cur is not None:
            screen = cur
    pygame.quit()
    sys.exit()


def _dispatch_state(screen, clock, state):
    """One iteration of the top-level state machine. Pulled out so
    main() can wrap it in a try/except per iteration without
    indenting the whole loop body. Returns the next state string."""
    if state == "menu":
        return run_menu(screen, clock) or "quit"
    if state in ("play", "practice"):
        _practice = state == "practice"
        path = run_select(screen, clock, practice=_practice)
        if path:
            try:
                meta, objects = load_level_full(path)
            except (OSError, ValueError):
                return "menu"
            run_play(
                screen, clock, objects,
                level_name=meta["name"],
                level_music=meta.get("music"),
                meta=meta,
                level_path=path,
                practice_mode=_practice,
            )
        return "menu"
    if state == "rate":
        # Admin-only level rating screen. run_rate_menu itself
        # guards against non-admin access, so even if the button
        # somehow fires for a wrong user we bounce back cleanly.
        run_rate_menu(screen, clock)
        return "menu"
    if state == "editor":
        # Strict mode: editing is a per-account action. Require a
        # signed-in user before we even show the picker — without
        # an account there's no way to stamp authorship, and
        # giving unsigned sessions full access bypasses the owner
        # lock on everyone else's levels. Bounce back to menu and
        # surface the auth screen as the suggested next step.
        from src.prefs import get as _pget
        from src.menus import confirm_dialog
        if not _pget("signed_in_username", None):
            go_auth = confirm_dialog(
                screen, clock,
                "Sign in to edit levels.",
                subtitle="The editor stamps your username as the "
                         "level's author so only you can re-save or "
                         "delete it.",
                ok_label="Sign in", cancel_label="Back",
            )
            return "auth" if go_auth else "menu"
        pick = run_editor_picker(screen, clock)
        if pick is not None:
            action, fn = pick
            run_editor(screen, clock,
                       preload_filename=fn if action == "open" else None)
        return "menu"
    if state == "settings":
        # Settings is a modal now — opens over the menu, returns
        # directly when closed. run_settings handles fullscreen
        # toggles internally so we just re-apply the display in
        # case one happened.
        run_settings(screen, clock, on_fullscreen_change=apply_display_mode)
        apply_display_mode()
        return "menu"
    if state == "auth":
        # Chunk F will wire this to the real AuthStore. For now the
        # stub just toggles a local pref so the main menu shows
        # either "Login/Signup" or "Signed in: X".
        _auth_stub(screen, clock)
        return "menu"
    # Unknown state — fall back to menu rather than infinite-loop.
    return "menu"


def _auth_stub(screen, clock):
    """Login / signup modal.

    Uses the `AuthStore` factory from `stores.py` so it works against
    the real FastAPI server when `TRIGSPRINT_SERVER_URL` is set, and
    falls back to the local disk store when offline / for tests.
    """
    from src.menus import text_input_dialog, confirm_dialog
    from src.stores import get_stores
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
    # In frozen PyInstaller builds, each multiprocessing.spawn child
    # re-executes this binary. Without freeze_support() it re-enters
    # main() and opens another game window; the parallel autobot would
    # spawn one extra window per worker. freeze_support intercepts the
    # spawn handoff and runs only the worker code path instead. No-op
    # in regular `python main.py` runs.
    from multiprocessing import freeze_support
    freeze_support()
    main()
