# Physics calibration

The simulation runs at 240 ticks/second. One editor cell represents 30 GD
units; velocity values are converted from GD units at 60 Hz to pixels per
simulation tick. Horizontal speed and vertical motion use the same scale.

The previous defaults combined a 6-block/second run speed with a roughly
3.5-block-high cube jump. The corrected normal-speed fresh jump peaks at
about 2.36 blocks, lasts about 0.43 seconds, and travels about 4.4 blocks.
Normal running covers 10.386 blocks/second. Holding cube repeats jumps;
a fresh press includes gravity on the launch tick.

The player body is **one full block — 30 GD units — and 18 units in mini**,
per the reference's §3.2 hitbox table (every box gamemode shares the same
30-unit main box). Size is a physics quantity, not a render one: it fixes
what "a 2-block gap" means, how tall a jump reads against the blocks it
clears, and how many body-lengths of world scroll past per second. It was
44 px / 24 px (26.4 / 14.4 units) until 2026-09-09 — px literals from the
pre-GD-units prototype that the units cutover converted by ratio instead of
re-deriving — which left the body 12% small against a world grid that is in
real GD units, so every jump read ~12% high and the world scrolled ~14%
fast relative to the player. `HITBOX_SOLID_FRACTION`'s entries are
literally reference_blue/reference_red (`9/30`, `10/18`, ...), so they now
yield the reference's 9- and 10-unit solid boxes exactly.

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
  no longer used. §3.2's hitbox table supplies the player body size.

## Known remaining divergences from the reference

These are measured, not guessed — the numbers above were traced tick by
tick against the reference's tables:

- **Ship's hold/release acceleration is unsourced.** The reference itself
  calls ship "genuinely unresolved"; the engine's 46 blocks/s² is roughly
  1.8x its single-source 25 blocks/s² estimate. Max rise (8G) and max
  fall (6.4G) do match.
- **Robot uses 0.9x cube gravity** while not thrusting, and **UFO/Ball/
  Spider/Swing use per-mode fractions of the 0.9582 flying acceleration**.
  Only the action velocities and fall caps for these modes are sourced.
- **`MAX_RISE_UFO` (8 Vel) has no reference figure.** §1.3 gives UFO a
  fall cap (-6.4G) and a click velocity (7G) but no rise cap. The clamp
  is unreachable in practice (a click *sets* vy to 7G and gravity only
  reduces it), so it is inert rather than wrong — left alone rather than
  invent a number.
- **Dual mirror placement is screen-relative**, not the reference's
  §1.7 "9 / 10 vertical unit" grid lock. §1.7 states that figure in
  "units" while its own glossary makes 9 units = 0.3 blocks, so the
  source is self-inconsistent here and was not acted on.

## Camera framing (applied 2026-09-10)

Sourced target: GD is a cocos2d-x game whose design resolution is
**480 x 320** applied with **`ResolutionPolicy::FIXED_HEIGHT`** (per
`Grasshopper67/Geometry-Dash`, the open-source GD reimplementation), and
GDRWeb's camera maps screen size to world size 1:1 at zoom 1
(`screenSize / zoom`). So **1 GD unit = 1 point, the vertical FOV is
locked at 320 units = 10.67 blocks, and horizontal follows the aspect
ratio**. Corroborated independently by NamuWiki ("if the camera zoom is
not set separately, the height of the floor and ceiling is fixed to 10
blocks") and by §1.7's 10-block dual grid lock fitting exactly inside it.

`CELL` is therefore derived rather than picked:
`round(HEIGHT * 30 / CAMERA_FOV_UNITS)` = `round(700 * 30 / 320)` = **66**
px, up from 50. It is rounded to a whole pixel because sprites are baked
at that size and pygame surfaces are integer-sized; the residual FOV is
318.2 units instead of 320 (0.6% tighter). Measured off real rendered
frames, the view went from **24.00 x 14.00 blocks to 18.18 x 10.61**.

Because the FOV shrank, the camera can no longer be pinned to world row
0 — that would crop the ground plane and the play lane off the bottom.
The default view is now defined by where it puts the **ground** (11/14 of
the way down, this engine's long-standing framing) and the camera's top
edge falls out of that: `CAMERA_BASE_Y_UNITS`. At the old 14-block FOV
that expression is exactly 0, so it generalises the previous behaviour
rather than replacing it.

**What had to be fixed first.** `CELL` was documented as "render-only"
and was not. The px -> unit shim was **duplicated**
(`constants.PX_TO_UNIT_RATIO` and a private `geometry._PX_TO_UNIT_RATIO`)
and ~26 physics call sites spelled lengths as `px_to_units(<px literal>)`,
so `CELL` silently set the collision substep, the trigger-touch pad, the
inner-hitbox floor, the slope snap band, the fall-off bounds and the bot
search buckets. A bare `CELL = 66` failed 12 tests.

The fix was not to freeze a shim at a magic legacy value. Every one of
those lengths is now stated directly in GD units in `constants.py`
(`COLLISION_SUBSTEP_UNITS`, `TOUCH_PAD_UNITS`,
`GROUND_CONTACT_MARGIN_UNITS`, `SLOPE_SNAP_MARGIN_UNITS`,
`MIN_INNER_HITBOX_UNITS`, `TELEPORT_BEAM_STEP_UNITS`,
`FALL_OFF_*_CAM_UNITS`), `geometry.py`'s **unit** builders became the
primary shape definitions with the integer-px ones derived from them,
the `*_UT` physics constants are now derived from the reference's
units/second figures instead of from their own px twins, and
`HEIGHT_UNITS` split into `CAMERA_HEIGHT_UNITS` (the FOV, render-derived)
and `PLAYFIELD_HEIGHT_UNITS` (a frozen 14 blocks — what the dual mirror,
the fall-off bound and the bots' void floor actually wanted). The dead
third copy of the shim, `src/units.py`, was deleted.

**Verified** by running the same scripted multi-gamemode simulation at
`CELL` = 50, 66 and 99 and diffing: every unit-space physics field, every
hitbox, every `*_UT`/`*_UNITS` constant and the bot dedup key are
bit-identical across all three; the only value that moves is
`target_cam_y`, which is the camera. `test_game.py` 892/892 and
`test_physics.py` 32/32 pass at all three scales.

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
