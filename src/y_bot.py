"""Y-key greedy bot — at each frame, simulate two literal futures:

  * "click/hold": held=True every frame for the lookahead horizon.
  * "no click":   held=False every frame for the lookahead horizon.

The bot picks whichever survives longer (alive_frames is the primary
score, x progress the tie-breaker). Each real frame the bot
RE-DECIDES from scratch, so a steady "click" decision means the bot
will commit to holding only as long as that's still the better
trajectory.

Branch semantics on different modes:

  * Cube / ball / spider / swing / ufo (tap): click branch holds the
    button, which means a fresh edge-press triggers each landing —
    the lookahead naturally bunny-hops and the bot picks click only
    when bunny-hopping survives more frames than walking.
  * Ship / wave / robot (hold): click branch sustains the upward
    thrust, no-click branch falls. Per-frame decision keeps the
    player band-keeping in the corridor.
  * Dash orbs: hold maintains the dash; release ends it (the engine
    zeroes ``dash_timer`` when ``input_held=False``). The click
    branch's "hold forever" naturally rides out the dash to its
    end, exactly the user's "Y bot can't do dash orbs" requirement.

Public API:

    bot = YBot(objects, params=None, lookahead=600)
    inputs, waypoints, won, death, forecasts = bot.solve()

    # Live (no precompute):
    controller = YBotController(params=...)
    # then: run_play(..., bot_controller=controller)
"""

from __future__ import annotations

import time
from typing import NamedTuple

from .autobot import _SimPlayer, _snap, _restore
from .constants import CELL, PLAYER_SIZE, T_END


class _ProbeState(NamedTuple):
    """Frozen snapshot of a probe rollout's terminal state. Captured
    BEFORE the sim is restored back to snap0 for the other branch's
    rollout, so the decision logic can compare both branches without
    depending on the sim's current pose. ``alive_frames`` is the
    primary score so the bot's goal is literally "don't die"."""
    x: float
    y: float
    alive: bool
    won: bool
    alive_frames: int
    size: int
    angle: float
    death_reason: str


# Tolerance for x-progress comparisons. Without this, jump-vs-walk
# branches that land at the same conceptual cell can differ by
# floating-point epsilons (the jump trajectory accumulates more
# multiplications) and the bot reads that as "click is +1e-13 px
# better, click!" — producing rhythmic hopping at the cube's
# natural jump cycle whenever both branches die at the same hazard.
_X_TOL = 1.0

# Minimum survival-frame advantage required for the click branch to
# be preferred over no-click when both branches die. Set above the
# typical "jump arc takes a few frames before hitting the same spike"
# noise (~5 frames) and below a single jump cycle (~30 frames) — 30
# means "the click cleared one obstacle and survived until the next",
# which is the click we actually want to commit to.
_AF_BOOST = 30


def _decide(probe_a, probe_b):
    """Pick which probe's terminal state is preferable. Returns True
    for "click" (probe_a) and False for "no click" (probe_b).

    Decision ladder:
      1. Won beats not-won.
      2. Alive at lookahead horizon beats dead.
      3. Both alive → click only if x is at least ``_X_TOL`` ahead.
         Tie → no-click.
      4. Both dead → click only if survival is at least
         ``_AF_BOOST`` frames longer. Otherwise no-click.
    """
    a_alive = probe_a.alive
    a_won = probe_a.won
    b_alive = probe_b.alive
    b_won = probe_b.won
    if a_won and not b_won:
        return True
    if b_won and not a_won:
        return False
    if a_alive and not b_alive:
        return True
    if b_alive and not a_alive:
        return False
    if a_alive and b_alive:
        return probe_a.x > probe_b.x + _X_TOL
    # Both dead. Survival gap > _AF_BOOST → click.
    return (probe_a.alive_frames - probe_b.alive_frames) >= _AF_BOOST


def _roll_branch(probe, branch_held, prev_held, lookahead,
                 vis_horizon=120, vis_stride=2):
    """Roll a single branch forward under the LITERAL "hold the
    button at ``branch_held`` for the entire lookahead" policy.

    Returns ``(wps, alive_frames)`` where ``wps`` is sampled
    (x, y) waypoints for the editor overlay (subset of the rollout)
    and ``alive_frames`` is how many lookahead frames the probe
    survived.

    Frame 0's pressed=edge is computed from ``prev_held`` so a first
    held=True after a held=False frame correctly fires orb / dash
    activations. Frames 1..N-1 use the same branch_held value, with
    pressed=False (no fresh edge while continuing to hold).

    Why "hold the button for the whole lookahead" and not a smarter
    autopilot:
      * Tap modes: holding bunny-hops at the natural jump cycle, so
        the bot picks "click" whenever bunny-hopping survives more
        frames than walking. The bot re-decides every frame, so a
        single click commitment doesn't leak into the next frame.
      * Hold modes (ship/wave/robot): sustained hold rises, sustained
        release falls — a stark difference that makes the per-frame
        band-keeping decision easy.
      * Dash orbs: the engine ends the dash the instant
        ``input_held=False``, so "hold forever" naturally rides
        the dash to completion.
    """
    size_attr = getattr(probe, "size", PLAYER_SIZE)
    wps = [(probe.x + size_attr / 2, probe.y + size_attr / 2)]
    alive_frames = 0
    # Frame 0.
    pressed0 = bool(branch_held) and not bool(prev_held)
    probe.update(branch_held, pressed0)
    if probe.alive and not probe.won:
        alive_frames += 1
    if vis_horizon >= 1 and 0 % vis_stride == 0:
        size_attr = getattr(probe, "size", PLAYER_SIZE)
        wps.append((probe.x + size_attr / 2,
                    probe.y + size_attr / 2))
    if not probe.alive or probe.won:
        return wps, alive_frames
    last_h = branch_held
    # Frames 1..lookahead-1 — same held value, pressed=edge only on
    # transitions (won't happen in this constant-action policy, but
    # we honour the protocol so the engine never sees a stale edge).
    for i in range(lookahead - 1):
        pressed_i = bool(branch_held) and not bool(last_h)
        probe.update(branch_held, pressed_i)
        last_h = branch_held
        if probe.alive and not probe.won:
            alive_frames += 1
        step = i + 1  # frames since first action
        if step < vis_horizon and step % vis_stride == 0:
            size_attr = getattr(probe, "size", PLAYER_SIZE)
            wps.append((probe.x + size_attr / 2,
                        probe.y + size_attr / 2))
        if not probe.alive or probe.won:
            # Tail sample at the death pose so the line ends
            # exactly where the marker will be drawn.
            size_attr = getattr(probe, "size", PLAYER_SIZE)
            tail = (probe.x + size_attr / 2,
                    probe.y + size_attr / 2)
            if not wps or wps[-1] != tail:
                wps.append(tail)
            return wps, alive_frames
    return wps, alive_frames


def _forecast_entry(probe, wps):
    """Build the per-frame ghost dict for one branch (click/no-click).
    The death dict mirrors the engine's pose at the moment of death
    so the renderer's hitbox-marker code can reuse the same path.
    ``probe`` may be a live _SimPlayer or a captured ``_ProbeState`` —
    we read attributes that exist on both."""
    death = None
    won = bool(probe.won)
    if not probe.alive and not probe.won:
        size_attr = getattr(probe, "size", PLAYER_SIZE)
        death = {
            "x": probe.x, "y": probe.y,
            "size": size_attr,
            "angle": getattr(probe, "angle", 0.0),
            "reason": getattr(probe, "death_reason", "Died"),
        }
    return {"wp": wps, "death": death, "won": won}


def _decide_and_pack(probe_a_state, probe_a_wps,
                     probe_b_state, probe_b_wps):
    """Run _decide and bundle the per-frame ghost forecast. Shared by
    both ``YBot.solve`` (precomputed) and ``YBotController.compute_input``
    (live) so both stay in lockstep on visualization shape."""
    chose_click = _decide(probe_a_state, probe_b_state)
    forecast = {
        "click": _forecast_entry(probe_a_state, probe_a_wps),
        "noclick": _forecast_entry(probe_b_state, probe_b_wps),
        "chosen": "click" if chose_click else "noclick",
    }
    return chose_click, forecast


def _capture(probe, alive_frames):
    """Freeze a probe's terminal state into a _ProbeState so it
    survives the next _restore."""
    return _ProbeState(
        x=probe.x, y=probe.y,
        alive=probe.alive, won=probe.won,
        alive_frames=alive_frames,
        size=getattr(probe, "size", PLAYER_SIZE),
        angle=getattr(probe, "angle", 0.0),
        death_reason=getattr(probe, "death_reason", "Died"),
    )


class YBot:
    """Greedy 1-step-lookahead bot — precomputed variant. Used by
    test scripts and any caller that wants the full input chain up-
    front. The editor's Y-key now goes through ``YBotController``
    instead so the bot runs LIVE during play."""

    def __init__(self, objects, params=None, *,
                 lookahead=600, max_frames=8000,
                 vis_horizon=None, vis_stride=2):
        self._objects_template = [dict(o) for o in objects]
        self._params = params
        self.lookahead = max(1, int(lookahead))
        self.max_frames = max(1, int(max_frames))
        # Visualization horizon defaults to the FULL lookahead so the
        # ghost line covers the entire rollout the bot is reasoning
        # about. Capping it shorter (the old 120-frame default) hid
        # the death position when a probe died past the visible
        # window — the line LOOKED alive but the bot's data said it
        # died, and the user couldn't tell why the bot picked the
        # other branch.
        self.vis_horizon = max(1, int(vis_horizon or self.lookahead))
        self.vis_stride = max(1, int(vis_stride))
        end_xs = [o["x"] * CELL for o in self._objects_template
                  if o.get("t") == T_END]
        self._end_x = float(max(end_xs)) if end_xs else 0.0

    def solve(self, time_budget=None):
        """Run the bot frame by frame. Returns
        ``(inputs, waypoints, won, death_info, forecasts)``."""
        sim = self._make_sim()
        size_attr = getattr(sim, "size", PLAYER_SIZE)
        waypoints = [(sim.x + size_attr / 2, sim.y + size_attr / 2)]
        inputs = []
        forecasts = []
        prev_held = False
        deadline = (time.monotonic() + time_budget) if time_budget else None
        for f in range(self.max_frames):
            if deadline is not None and time.monotonic() > deadline:
                break
            if sim.won or not sim.alive:
                break
            snap0 = _snap(sim)
            # Branch A: hold for the entire lookahead.
            wp_a, alive_a = _roll_branch(sim, True, prev_held,
                                         self.lookahead,
                                         self.vis_horizon,
                                         self.vis_stride)
            probe_a = _capture(sim, alive_a)
            _restore(sim, snap0)
            # Branch B: release for the entire lookahead.
            wp_b, alive_b = _roll_branch(sim, False, prev_held,
                                         self.lookahead,
                                         self.vis_horizon,
                                         self.vis_stride)
            probe_b = _capture(sim, alive_b)
            chose_click, forecast = _decide_and_pack(
                probe_a, wp_a, probe_b, wp_b)
            forecasts.append(forecast)
            held = chose_click
            pressed = held and not prev_held
            _restore(sim, snap0)
            sim.update(held, pressed)
            inputs.append((held, pressed))
            prev_held = held
            if f % 2 == 0 or sim.won or not sim.alive:
                size_attr = getattr(sim, "size", PLAYER_SIZE)
                waypoints.append((sim.x + size_attr / 2,
                                  sim.y + size_attr / 2))
        death_info = None
        if not sim.alive and not sim.won:
            size_attr = getattr(sim, "size", PLAYER_SIZE)
            death_info = {
                "x": sim.x, "y": sim.y,
                "size": size_attr,
                "angle": getattr(sim, "angle", 0.0),
                "reason": getattr(sim, "death_reason", "Died"),
            }
        size_attr = getattr(sim, "size", PLAYER_SIZE)
        last_wp = (sim.x + size_attr / 2, sim.y + size_attr / 2)
        if not waypoints or waypoints[-1] != last_wp:
            waypoints.append(last_wp)
        return inputs, waypoints, bool(sim.won), death_info, forecasts

    def _make_sim(self):
        sim = _SimPlayer([dict(o) for o in self._objects_template],
                         params=self._params)
        sim.trail = []
        return sim


class YBotController:
    """LIVE Y bot — implements the ``bot_controller`` protocol that
    ``play.run_play`` calls each frame. No precomputation: the bot
    snapshots the live player, simulates branch A and branch B
    forward under the "hold forever" / "release forever" policies
    described in ``_roll_branch``, picks the better one, and returns
    that frame's input. The forecasts are exposed on
    ``self.last_forecast`` so the editor's overlay can render the
    current frame's two ghost lines without any precomputed list.

    Bot-only objects: while running its lookahead the controller
    sets ``player._bot_visibility = True`` so phantom hazards count;
    after the lookahead it restores the flag to False so the real
    update tick that follows treats them as inert. The live player
    is the probe — using the same instance avoids the id()-based
    snap/restore mismatch that breaks cross-instance restores.
    """

    def __init__(self, params=None, *, lookahead=600,
                 vis_horizon=None, vis_stride=2):
        self._params = params  # not used directly here (player has
        # already been built with params), kept for symmetry / docs.
        self.lookahead = max(1, int(lookahead))
        # Default vis_horizon = lookahead so the ghost line covers
        # the entire rollout. Anything shorter risks hiding deaths
        # that happen past the visible window — the user sees an
        # alive-looking line, the bot picks the other branch, and
        # the discrepancy makes the bot look broken when it's
        # actually following its own data correctly.
        self.vis_horizon = max(1, int(vis_horizon or self.lookahead))
        self.vis_stride = max(1, int(vis_stride))
        self._prev_held = False
        # ``last_forecast`` is read by play.py's renderer each frame.
        # Shape matches one entry from ``YBot.solve``'s ``forecasts``.
        self.last_forecast = None

    def reset(self):
        self._prev_held = False
        self.last_forecast = None

    def compute_input(self, player):
        """Per-frame: snap → branch A rollout → restore → branch B
        rollout → restore → decide → return (held, pressed)."""
        snap0 = _snap(player)
        prev_vis = bool(getattr(player, "_bot_visibility", False))
        player._bot_visibility = True
        try:
            wp_a, alive_a = _roll_branch(
                player, True, self._prev_held,
                self.lookahead, self.vis_horizon, self.vis_stride)
            probe_a = _capture(player, alive_a)
            _restore(player, snap0)
            wp_b, alive_b = _roll_branch(
                player, False, self._prev_held,
                self.lookahead, self.vis_horizon, self.vis_stride)
            probe_b = _capture(player, alive_b)
            _restore(player, snap0)
        finally:
            player._bot_visibility = prev_vis
        chose_click, forecast = _decide_and_pack(
            probe_a, wp_a, probe_b, wp_b)
        self.last_forecast = forecast
        held = chose_click
        pressed = held and not self._prev_held
        self._prev_held = held
        return held, pressed
