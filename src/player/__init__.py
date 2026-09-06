"""Player package: physics state machine for one play attempt.

Layout
------
``body.py``       MirrorBody (dual-mode second body)
``collision.py``  spatial index, block / slope resolution, hazard OBB tests
``triggers.py``   move / rotate / follow / pulse trigger animation
``draw.py``       sprite + trail rendering (with caches)
``core.py``       Player: mode physics, orbs / pads / portals, update loop
"""

from .core import Player, orb_direction
from .body import MirrorBody
from .collision import _NON_TRIGGER_TYPES, is_non_trigger, obb_corners, \
    obb_aabb_overlap
from .draw import render_player_sprite

__all__ = ["Player", "MirrorBody", "orb_direction", "_NON_TRIGGER_TYPES",
           "is_non_trigger", "obb_corners", "obb_aabb_overlap",
           "render_player_sprite"]
