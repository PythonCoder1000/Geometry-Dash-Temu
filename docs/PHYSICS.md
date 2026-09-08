# Physics calibration

The simulation runs at 240 ticks/second. One editor cell represents 30 GD
units; velocity values are converted from GD units at 60 Hz to pixels per
simulation tick. Horizontal speed and vertical motion use the same scale.

The previous defaults combined a 6-block/second run speed with a roughly
3.5-block-high cube jump. The corrected normal-speed fresh jump peaks at
about 2.36 blocks, lasts about 0.43 seconds, and travels about 4.4 blocks.
Normal running covers 10.386 blocks/second. Holding cube repeats jumps;
a fresh press includes gravity on the launch tick.

Wave reverses immediately, following a 1:1 diagonal normally and 2:1 in
mini mode. Its angle setting changes the trajectory as well as its appearance.
Robot hold lasts 0.25 seconds and cannot restart after release in midair.
Ship, UFO, ball, spider and swing use distinct acceleration factors rather
than all inheriting cube gravity. Cube-derived impulses vary by speed tier.

Landings resolve when the feet cross the surface, using the inner box's
horizontal span. Ground adjacency no longer attracts the player from a gap.
Cube/robot ceiling impacts and wave surface impacts are lethal, subject to
H/D block exceptions. Queued short taps receive a simulation tick even if
the physical button has already been released; keyboard repeat is ignored.

Settings, editor prediction and gameplay all use the same 240 Hz rate.
The predictor respects custom starting speed and actual floor contact after
a placement nudge, and simulates a copy of editor objects. Ship and wave
flight estimates share gameplay calculations; mirror estimates run the
same mode code on isolated state. Both dual bodies sweep collisions along
their movement, including horizontal travel. UFO flaps require fresh
presses and use distinct rise/fall caps; wave also dies on ordinary slopes.

Invalid/non-finite metadata falls back to default parameters. Cached bot
wins are invalidated when geometry or physics changes, and malformed saved
runs fail to load without crashing the menu. Music position calculations
respect sub-pixel custom speed and use gameplay's time-warp limits.

## Evidence and limits

- [GD updateJump decompilation](https://github.com/camila314/gdp/blob/2.2/PlayerObject/PlayerObject_updateJump.cpp):
  mode acceleration factors, mini jump scaling, instant wave velocity,
  and robot timer units. The robot counter advances in 60 Hz time units
  divided by 10; a limit of 1.5 therefore represents 0.25 seconds.
- [Local physics reference](reference/geometry-dash-physics-bible.md): speed tiers,
  jump velocities and the 0.216-velocity-unit fresh-click gravity step.
  Its older 72 blocks/s² gravity estimate conflicts with that step and is
  no longer used.

This is a calibrated recreation, not a verified tick-for-tick GD port.
Slopes, orb/pad strengths, portal transitions and hazard shapes still use
this project's implementations. Legacy physics quirks are not emulated.
Ship's normal flight acceleration follows the decompilation, but its
special boosted/legacy states are not reproduced.

Existing level geometry is preserved. Levels and saved bot recordings
authored around the old physics may need retiming or a new solve, including
music synchronization. Explicit per-level physics overrides still apply.

## Regression checks

Run `.venv/bin/python -m unittest test_physics` for measured movement,
input, collision and Player/SimPlayer parity checks. Run
`.venv/bin/python test_game.py` for the broader game/editor/bot suite.
These checks do not substitute for side-by-side playtesting with GD.
