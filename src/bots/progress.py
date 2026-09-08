"""Solver progress screen shared by both bots.

Two things here used to be wrong and are worth spelling out, because
they produced the "stuck at 98%, only says SOLVED after you hit ESC"
report:

* **The denominator was the wrong x.**  The bar divided the deepest
  reached ``player.x`` by ``T_END``'s pixel column.  But ``player.x`` is
  the player's LEFT edge and the win fires when its RIGHT edge crosses
  the end wall (against a slightly inflated trigger rect), so a winning
  run's final x is ``end_x - size - 3``.  On a 44 px player that caps the
  bar at 96-98% no matter how the run goes.
  :func:`win_x_for_objects` returns the x the player actually wins at,
  which is what the percentage is measured against now.

* **The win was surfaced lazily.**  A search returned the instant it
  found a win, but the caller then spent up to five more seconds
  polishing the input chain with the stale progress frame still on
  screen.  ESC aborted the polish, which is why cancelling was what
  "revealed" the solve.  :meth:`SolveProgress.report_win` is called from
  inside the search on the very frame ``player.won`` flips, repaints at
  100% immediately, and every later paint stays pinned at 100%.
"""

import time

import pygame

from ..constants import (
    UNITS_PER_BLOCK, PLAYER_SIZE_UNITS, WIDTH, HEIGHT, T_END, px_to_units,
)

# Wall-clock cadence for repaints and for draining the event queue.
PAINT_INTERVAL = 0.2
PUMP_INTERVAL = 0.05

COLOR_BG = (10, 8, 24)
COLOR_TITLE = (255, 180, 60)
COLOR_STATUS = (180, 220, 255)
COLOR_MUTED = (180, 180, 200)
COLOR_HINT = (140, 140, 155)
COLOR_TRACK = (40, 40, 60)
COLOR_BAR_LOW = (230, 130, 80)
COLOR_BAR_MID = (255, 180, 60)
COLOR_BAR_HIGH = (90, 255, 120)
COLOR_SOLVED = (90, 255, 120)


# ``Player`` tests the end wall against a trigger rect inflated by this
# many GD units on each side, so the win fires slightly before the
# player's true right edge reaches the wall. Mirrored here so the bar's
# 100% mark is the x a winning run actually stops at.
TRIGGER_INFLATE = px_to_units(3)


def win_x_for_objects(objects, player_size=PLAYER_SIZE_UNITS):
    """The ``player.x`` (in GD units) at which the level is won, or 0.

    ``Player._handle_interactions`` sets ``won`` when the player's
    inflated right edge crosses an end wall, so the winning left-edge x
    is the wall column minus the player's size and that inflation — not
    the wall column itself, which is what the bar used to divide by.
    """
    end_xs = [o["x"] * UNITS_PER_BLOCK for o in objects if o.get("t") == T_END]
    if not end_xs:
        return 0.0
    return max(1.0, max(end_xs) - player_size - TRIGGER_INFLATE)


class SolveProgress:
    """Progress bar + ESC latch for a running solve.

    Owns cancellation so both bots share one definition of "responsive
    ESC": the queue is drained on a wall-clock cadence from inside the
    hot loop and unconditionally on every paint.
    """

    def __init__(self, screen, clock, win_x, title="BOT SEARCH", has_end=True):
        self.screen = screen
        self.clock = clock
        self.win_x = max(1.0, float(win_x))
        # win_x_for_objects() falls back to 0 (clamped to 1.0 above) when
        # the level has no T_END at all — without this flag, percent()
        # would divide against that dummy 1px target and claim 100% the
        # instant the player moves, even though nothing was ever reached.
        self.has_end = has_end
        self.title = title
        self.cancelled = False
        self.solved = False
        self.best_x = 0.0
        self._last_pump = 0.0
        self._last_paint = 0.0

    # ---- cancellation -------------------------------------------------

    def pump(self, force=False):
        """Drain events, latching ESC. Returns True once cancelled."""
        now = time.monotonic()
        if not force and (now - self._last_pump) < PUMP_INTERVAL:
            return self.cancelled
        self._last_pump = now
        try:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    pygame.quit()
                    raise SystemExit
                if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                    self.cancelled = True
        except pygame.error:
            # Headless runs have no display; pygame.event.get() raises.
            pass
        return self.cancelled

    # ---- state --------------------------------------------------------

    def note_x(self, x):
        if x > self.best_x:
            self.best_x = float(x)

    def set_x(self, x):
        """Force the displayed x, even downward.

        ``note_x`` is monotonic so a live preview from an unverified
        search (e.g. brute force reporting its own SimPlayer's frontier
        mid-search) can never be corrected once the real, Player-replay
        -verified result turns out lower. Call this once a phase has a
        confirmed final value to realign the bar with what was actually
        committed.
        """
        self.best_x = float(x)

    def percent(self):
        if self.solved:
            return 100
        if not self.has_end:
            # No T_END in the level — there is no goal to measure
            # progress against, so don't fabricate one against the 1px
            # placeholder win_x falls back to (that would hit 100% the
            # instant the player takes a single step).
            return 0
        pct = int(self.best_x / self.win_x * 100)
        return min(100, max(0, pct))

    def report_win(self, status_text="SOLVED"):
        """Latch the win and repaint at 100% on this very frame.

        Called from inside the search the moment the simulator reports
        ``won`` — before any polish / verification work — so the screen
        never sits on a stale sub-100% frame while the solve is already
        decided.
        """
        self.solved = True
        self.best_x = max(self.best_x, self.win_x)
        self.paint(status_text, force=True)

    # ---- painting -----------------------------------------------------

    def paint(self, status_text="", force=False):
        """Repaint if due. Returns True when the user has cancelled."""
        if self.screen is None:
            return self.pump()
        now = time.monotonic()
        if not force and (now - self._last_paint) < PAINT_INTERVAL:
            return self.cancelled
        self._last_paint = now
        pct = self.percent()
        screen = self.screen
        screen.fill(COLOR_BG)
        from ..graphics import txt

        title_color = COLOR_SOLVED if self.solved else COLOR_TITLE
        txt(screen, self.title, WIDTH // 2, HEIGHT // 2 - 86, 32,
            title_color, True)
        if status_text:
            txt(screen, status_text, WIDTH // 2, HEIGHT // 2 - 52, 16,
                COLOR_STATUS, True)
        from ..constants import PX_PER_UNIT
        txt(screen, f"X {int(self.best_x * PX_PER_UNIT)}", WIDTH // 2,
            HEIGHT // 2 - 18, 18, COLOR_MUTED, True)
        bw = 460
        bx = WIDTH // 2 - bw // 2
        by = HEIGHT // 2 + 14
        bh = 24
        pygame.draw.rect(screen, COLOR_TRACK, (bx, by, bw, bh),
                         border_radius=6)
        if pct > 0:
            bar_color = (COLOR_BAR_HIGH if pct > 80
                         else COLOR_BAR_MID if pct > 40
                         else COLOR_BAR_LOW)
            pygame.draw.rect(screen, bar_color,
                             (bx, by, max(1, int(bw * pct / 100)), bh),
                             border_radius=6)
        txt(screen, f"{pct}%", WIDTH // 2, by + 4, 14, (255, 255, 255), True)
        txt(screen, "Escape to cancel", WIDTH // 2, HEIGHT // 2 + 90, 14,
            COLOR_HINT, True)
        pygame.display.flip()
        if self.clock:
            self.clock.tick(60)
        return self.pump(force=True)
