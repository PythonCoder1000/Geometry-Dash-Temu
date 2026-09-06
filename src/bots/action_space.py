"""The action space a bot is allowed to search over.

A human plays this game with ONE button.  Everything the player can do
— every orb, every pad, every dual body, every mode — is driven by the
single held/released state of that button, sampled once per physics
frame.  Two consequences follow, and both used to be violated by the
solvers:

1. ``pressed`` is not an independent degree of freedom.  It is the
   rising edge of ``held``: ``pressed = held and not prev_held``.  A
   solver that treats ``(held, pressed)`` as two free bits can emit
   ``(True, False)`` while already holding and then ``(True, True)``
   several frames later without ever releasing — a re-press mid-hold
   that no keyboard can produce.  That extra freedom is precisely how
   the old search "chose" which of several overlapping orbs to fire:
   orbs activate on the press edge (or its 6-frame input buffer), so
   being able to slide the edge along a continuous hold is the same
   thing as picking orb B instead of orb A.  Under the one-button
   model the edge lands where the hold starts and orb resolution is
   left entirely to the engine's own priority order.

2. Both dual bodies see the same bit.  ``Player.update`` already feeds
   its ``input_held`` / ``input_pressed`` straight through to
   ``_step_mirror``, so there is no per-body channel in the physics —
   the independence only ever existed in solver action spaces that
   branched on more than one boolean.  Emitting one boolean per frame
   makes independent-per-body control unrepresentable by construction.

On top of the one-button rule an :class:`InputModel` adds a *dwell*
constraint: how many frames the button must stay in a state before it
may change.  ``HUMAN`` requires ``HUMAN_MIN_DWELL_FRAMES`` — hands do
not toggle faster than that.  ``FRAME_PERFECT`` allows a change every
frame and exists only as the explicit escape hatch for levels with no
human-reachable solution.
"""

from typing import NamedTuple

# 2 frames at 60 fps is ~15 full press-release cycles per second — the
# top of what a real straight-fly / rapid-tap looks like, and the rate
# the game's flight sections are actually built around.  A solution that
# needs the button to change state on consecutive frames is asking for
# 60 Hz precision, which is not something a person reproduces.
HUMAN_MIN_DWELL_FRAMES = 2

# The escape hatch keeps the one-button rule (that one is physical, not
# a matter of skill) and only relaxes timing precision.
FRAME_PERFECT_MIN_DWELL_FRAMES = 1

# Dwell counters saturate here — anything at or above ``min_dwell`` is
# behaviourally identical, so clamping keeps search state buckets small.
DWELL_CAP = 8


class InputModel(NamedTuple):
    """How precisely the single button may be operated.

    ``name`` is surfaced in the UI so a frame-perfect result is never
    mistaken for something a person could play.
    """

    name: str
    min_dwell: int

    def actions(self, prev_held, dwell):
        """Legal ``(held, pressed, next_dwell)`` triples for one frame.

        ``dwell`` is how many frames the button has already been in the
        ``prev_held`` state.  Holding is always legal; changing state
        requires the current state to have lasted ``min_dwell`` frames.
        """
        keep_dwell = dwell + 1 if dwell < DWELL_CAP else DWELL_CAP
        out = [(prev_held, False, keep_dwell)]
        if dwell >= self.min_dwell:
            flipped = not prev_held
            out.append((flipped, flipped, 1))
        return out

    def edge(self, held, prev_held):
        """The only press value the engine can ever see for ``held``."""
        return held and not prev_held

    def stream(self, held_bits):
        """Expand a sequence of held booleans into ``(held, pressed)``."""
        out = []
        prev = False
        for held in held_bits:
            held = bool(held)
            out.append((held, held and not prev))
            prev = held
        return out

    def sanitize(self, inputs):
        """Re-derive a legal input chain from ``inputs``' held bits.

        Chains arriving from disk (saved runs), from an older solver, or
        from a hand-edited file can carry impossible press edges.  We
        keep the held track — that is the part the user actually
        recorded — and rebuild the edges, then enforce the dwell rule by
        stretching any too-short state to ``min_dwell`` frames.
        """
        held_bits = [bool(h) for h, _p in inputs]
        if self.min_dwell > 1 and held_bits:
            fixed = [held_bits[0]]
            run = 1
            for held in held_bits[1:]:
                if held != fixed[-1] and run < self.min_dwell:
                    held = fixed[-1]
                if held == fixed[-1]:
                    run += 1
                else:
                    run = 1
                fixed.append(held)
            held_bits = fixed
        return self.stream(held_bits)

    def violations(self, inputs):
        """Frames where ``inputs`` could not have come from one button.

        Returns a list of ``(frame_index, reason)``.  Empty means the
        chain is reproducible on real hardware under this model.
        """
        bad = []
        prev_held = False
        dwell = DWELL_CAP
        for i, (held, pressed) in enumerate(inputs):
            held = bool(held)
            if bool(pressed) != (held and not prev_held):
                bad.append((i, "press edge does not match the held track"))
            if held != prev_held:
                if dwell < self.min_dwell:
                    bad.append((i, "button toggled faster than min_dwell"))
                dwell = 1
            else:
                dwell = dwell + 1 if dwell < DWELL_CAP else DWELL_CAP
            prev_held = held
        return bad


HUMAN = InputModel("human", HUMAN_MIN_DWELL_FRAMES)
FRAME_PERFECT = InputModel("frame-perfect", FRAME_PERFECT_MIN_DWELL_FRAMES)


def replay_state(inputs):
    """``(prev_held, dwell)`` a search would resume with after ``inputs``."""
    prev_held = False
    dwell = DWELL_CAP
    for held, _pressed in inputs:
        held = bool(held)
        if held != prev_held:
            dwell = 1
        elif dwell < DWELL_CAP:
            dwell += 1
        prev_held = held
    return prev_held, dwell
