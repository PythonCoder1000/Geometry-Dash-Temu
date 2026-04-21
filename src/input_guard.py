"""Click-through guard.

Pygame doesn't reset mouse-button state when a new screen takes over —
if the user clicked a button to enter screen B, the LMB is still held on
screen B's first frame, and any code that polls
``pygame.mouse.get_pressed()`` or processes a queued MOUSEBUTTONDOWN
will see the residual press as a real click.

The fix: on screen entry, capture whether the button is currently held.
If it is, we treat it as "stale" and ignore all click input until the
user has released the mouse at least once. After that release, normal
click handling resumes.

Usage:
    guard = ClickGuard()  # construct on screen entry
    while True:
        guard.tick()  # once per frame, before reading mouse state
        for ev in pygame.event.get():
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if not guard.consume_click(ev):
                    continue  # swallow stale entry click
                # ...real click handling here...
        # When polling held state instead of events:
        held = guard.mouse_held()
"""

import pygame


class ClickGuard:
    """Suppress the residual mouse-down state inherited from screen entry."""

    def __init__(self):
        try:
            self._waiting_for_release = bool(pygame.mouse.get_pressed()[0])
        except pygame.error:
            self._waiting_for_release = False

    def tick(self):
        """Call once per frame before reading mouse state."""
        if self._waiting_for_release:
            try:
                if not pygame.mouse.get_pressed()[0]:
                    self._waiting_for_release = False
            except pygame.error:
                self._waiting_for_release = False

    def consume_click(self, ev=None):
        """Return True if this click should be processed, False if stale.

        The ``ev`` argument is accepted for symmetry but ignored — the
        guard works on entry-state, not on individual event metadata.
        """
        return not self._waiting_for_release

    def mouse_held(self):
        """True only when the button is held AND not stale from entry."""
        if self._waiting_for_release:
            return False
        try:
            return bool(pygame.mouse.get_pressed()[0])
        except pygame.error:
            return False

    def is_settled(self):
        """True once the entry click has been released."""
        return not self._waiting_for_release

    def reset(self):
        """Re-arm the guard — useful after returning from a sub-screen."""
        try:
            self._waiting_for_release = bool(pygame.mouse.get_pressed()[0])
        except pygame.error:
            self._waiting_for_release = False
