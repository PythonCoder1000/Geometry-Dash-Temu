# Physics Fix: Comprehensive Handoff (2026-09-07)

This document records the physics problems found during the latest gameplay
pass and gives the next session a single plan. The project began as a prototype
with unrelated constants, so several values happen to work together only by
accident.

## Symptoms reported

- Gameplay still feels too fast even after the visual grid experiment.
- Wave direction changes feel snappier than Geometry Dash.
- The bot formerly completed courses, then began dying immediately after the
  world-cell rescale. Ground starts spawned inside terrain; air starts flew
  into walls.
- Camera and editor coordinates broke under the 120 px-cell experiment.
- Utility objects rendered as question marks, blobs, or mismatched icons.

## Changes made today

- Restored the stable internal `CELL = 50`, `PLAYER_SIZE = 44`, and
  `MINI_PLAYER_SIZE = 24`. The 120 px change modified collision, spawn,
  camera, editor, and sprite assumptions globally and must not be repeated as
  a physics fix.
- Added wave heading smoothing (`WAVE_ANGLE_SMOOTHING = 0.96`) to the visual
  angle only. Wave movement remains deterministic and input-driven.
- Utility blocks now use the intended hollow white rectangle glyphs:
  `S` (dash stop), `J` (jump block), `D` (wave block), and `H` (bonk block).
- Trigger glyph fallback now derives readable labels instead of displaying `?`.
- Bumped the sprite cache version so stale cached blobs are regenerated.

## Unit model that must be made explicit

There are currently three incompatible meanings of “speed”:

1. Level coordinates are integer editor cells converted with `CELL` pixels.
2. Player `x`, `y`, `vx`, and `vy` are pixel values, but some constants are
   documented as GD units or “G” values.
3. Simulation runs at `PHYSICS_TPS = 240`, while old level timing, bot traces,
   and several literal frame counts were authored for 60 Hz.

Choose one canonical model for the next pass:

```text
world_unit = one editor block (30 GD units)
world_px   = CELL pixels (currently 50; presentation zoom is separate)
dt         = 1 / PHYSICS_TPS seconds
vx, vy     = world_px / second (prefer seconds, not pixels / tick)
```

Convert to pixels per tick exactly once at the integration boundary:
`pixels_per_tick = pixels_per_second * dt`. Do not mix per-tick and per-second
values in `Player`, bot simulation, camera, or trigger code.

## Physics audit checklist

### Horizontal motion

- Establish the real 1x GD horizontal rate in blocks/second.
- Define speed portals as dimensionless multipliers (`0.5x`, `1x`, `2x`, etc.).
- Ensure `Player`, `PlaySession.real_time_to_x`, `x_at_time`, editor previews,
  replay playback, and bot simulation all use the same rate.
- Verify camera lead and level scroll are visual offsets, never extra movement.

### Vertical motion

- Rewrite gravity, jump impulses, ship thrust, UFO flap, robot hold, and ball
  flip as per-second accelerations/velocities, then integrate with `dt`.
- Measure jump apex, time-to-apex, and horizontal distance at each speed portal.
- Apply mini scaling to hitbox and documented mode behavior only; do not use
  arbitrary compensating multipliers to hide a unit mismatch.
- Keep wave vertical velocity tied to horizontal speed and its target angle.
  Smooth only the rendered heading, with a time-constant (not a raw magic
  per-tick coefficient) so it remains stable if TPS changes.

### Collision and numerical stability

- Run swept collision/substeps from displacement, not a fixed number of steps.
- Check spawn positions against the same inner hitbox used during gameplay;
  resolve to the nearest safe surface before the first tick.
- Test wave-to-block contacts from above, below, and at both speed portals.
- Keep outer hazard hitboxes and inner solid hitboxes in one documented table.

### Bot parity

- Bot prediction must call the same physics functions and constants as the real
  player; no duplicate gravity or wave formulas.
- Add a deterministic “spawn then one tick” test for ground, air, mini, dual,
  ship, and wave starts.
- Compare bot and player state after 1, 10, 60, and 240 ticks (position,
  velocity, mode, gravity, and collision result).
- Never let a camera/editor scale factor enter bot simulation.

### Camera/editor

- Treat camera zoom as a render transform only. World coordinates remain in
  canonical pixels/cells.
- Centralize `world_to_screen` and `screen_to_world`; remove direct `CELL`
  arithmetic from editor and camera code where possible.
- Add a regression test that opening a level, scrubbing the editor, and starting
  from the cursor preserve identical world coordinates.

## Required regression tests

1. A flat cube test: 1x speed travels the expected blocks in one second.
2. A jump test: apex/time/distance are recorded for normal and mini cube.
3. Wave hold/release test: target slopes, transition time, and collision are
   deterministic at 60, 120, and 240 render FPS.
4. Bot parity test on Limbo and the previously passing sample courses.
5. Start-position safety test for every mode and gravity direction.
6. Sprite snapshot test proving S/J/D/H are hollow white letter blocks and no
   known object renders `?`.

Do not change `CELL` again until these tests exist. If the game should show
fewer blocks on screen, change a camera zoom/render scale and explicitly keep
that transform out of physics.
