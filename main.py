#!/usr/bin/env python3
"""Entry point.

Initializes pygame/audio, seeds the levels directory with a Tutorial, and
owns the top-level state machine (menu ↔ select ↔ play ↔ editor).
"""

import sys

import pygame

from constants import WIDTH, HEIGHT
from editor import run_editor
from levels import ensure_dirs, load_level_full
import music
import sfx
import settings
import gamepad
from menus import run_menu, run_select, run_settings, run_customize
from music_menu import run_music_menu
from play import run_play


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
    pygame.display.set_caption("Geometry Dash Temu")
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
        elif state == "play":
            path = run_select(screen, clock)
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
                )
            state = "menu"
        elif state == "editor":
            run_editor(screen, clock)
            state = "menu"
        elif state == "settings":
            # run_settings may toggle fullscreen — re-apply on return so the
            # main loop keeps using the right surface.
            run_settings(screen, clock, on_fullscreen_change=apply_display_mode)
            screen = apply_display_mode()
            state = "menu"
        elif state == "customize":
            run_customize(screen, clock)
            state = "menu"
        elif state == "music":
            # The music menu may change the configured menu track. After
            # returning, kick the menu music if it isn't already playing
            # so the new track is heard immediately.
            run_music_menu(screen, clock)
            if music.is_enabled() and not music.is_playing():
                music.play_menu_music()
            state = "menu"
    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
