"""The two bots.

* :class:`~.human.HumanBot` — beats a level using only inputs a person
  could physically produce, and says so when it had to fall back to
  frame-perfect timing because no human-reachable solution exists.
* :class:`~.loophole.LoopholeBot` — beats a level while hugging a drawn
  path, deviating wherever a shortcut works and reporting where it
  strayed.

Everything else in the package is shared machinery: :mod:`.sim` for
headless replay, :mod:`.action_space` for the one-button input model,
:mod:`.toggle_search` for the randomised generation engine, and
:mod:`.progress` for the solver screen.
"""

from .action_space import FRAME_PERFECT, HUMAN, InputModel
from .brute_force import BruteForceSearch
from .human import BestSolution, CheckpointLadder, HumanBot
from .loophole import (
    DrawnPath, LoopholeBot, PathFollowController,
    load_bot_inputs, save_bot_inputs,
)
from .progress import SolveProgress, win_x_for_objects
from .sim import (
    SimPlayer, SnapVals, build_obj_index, dedup_key, player_dedup_key,
    restore, snapshot,
)
from .toggle_search import ToggleSearch

__all__ = [
    "BestSolution", "BruteForceSearch", "CheckpointLadder", "DrawnPath",
    "FRAME_PERFECT", "HUMAN", "HumanBot", "InputModel", "LoopholeBot",
    "PathFollowController",
    "SimPlayer", "SnapVals", "SolveProgress", "ToggleSearch",
    "build_obj_index", "dedup_key", "load_bot_inputs", "player_dedup_key",
    "restore", "save_bot_inputs", "snapshot", "win_x_for_objects",
]
