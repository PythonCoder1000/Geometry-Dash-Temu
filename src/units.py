"""Canonical Geometry Dash unit system.

Real GD measures the world in "GD units", with ``1 block = 30 units``
(verified live 2026-09-07 against the Move Trigger's "Small Step" behavior
— Small Step only changes the trigger UI's input granularity, 10 vs 30
units per click; the underlying scale is always 30 units/block). This
module is the single place that knows the ratio between GD units, this
engine's grid-cell integers (as stored in level JSON / ``objects.py``),
and screen pixels.

Physics, collision, and bot simulation should all work in **GD units**
and **units/second**, importing from here rather than reaching for
``CELL``. ``CELL`` (in :mod:`constants`) is a *render-only* constant —
pixels per block on screen at zoom 1 — and should not appear outside the
rendering/editor-display boundary once the migration described in
``docs/development/UNITS_REFACTOR.md`` is complete.

During that migration, both unit systems are in play at once: this module
also exposes the px-based helpers so callers can convert one call site at
a time without a single flag-day rewrite.
"""

from .constants import CELL

UNITS_PER_BLOCK = 30.0

# Pixels on screen per GD unit, at camera zoom 1.0. Rendering multiplies
# world units by this (and then by zoom) to get screen pixels; nothing in
# physics/collision/bot code should use this constant.
PX_PER_UNIT = CELL / UNITS_PER_BLOCK


def block_to_units(g):
    """Grid-cell index -> GD units (left/top edge of that cell)."""
    return g * UNITS_PER_BLOCK


def units_to_block(u):
    """GD units -> grid-cell index (floor)."""
    return u / UNITS_PER_BLOCK


def units_to_px(u):
    """GD units -> render pixels at zoom 1 (no camera offset)."""
    return u * PX_PER_UNIT


def px_to_units(px):
    """Render pixels at zoom 1 -> GD units (no camera offset)."""
    return px / PX_PER_UNIT


def world_to_screen(x_units, y_units, cam_x_px, cam_y_px, zoom=1.0):
    """GD-unit world position -> screen pixels under a pixel-space camera.

    ``cam_x_px``/``cam_y_px`` are the existing camera offsets, which
    remain in pixels (they're a render concern, not a physics one).
    """
    return (
        x_units * PX_PER_UNIT * zoom - cam_x_px,
        y_units * PX_PER_UNIT * zoom - cam_y_px,
    )


def screen_to_world(sx_px, sy_px, cam_x_px, cam_y_px, zoom=1.0):
    """Inverse of :func:`world_to_screen` — screen pixels -> GD units."""
    return (
        (sx_px + cam_x_px) / (PX_PER_UNIT * zoom),
        (sy_px + cam_y_px) / (PX_PER_UNIT * zoom),
    )
