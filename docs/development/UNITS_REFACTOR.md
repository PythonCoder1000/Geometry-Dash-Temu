# Units refactor: pixels → real Geometry Dash units

## Why

The engine's physics constants were already retuned to match real GD numbers
(`docs/reference/geometry-dash-physics-bible.md`), but they're expressed as
pixels-per-tick, derived from GD units via `PX_PER_UNIT = CELL / 30` baked
into every constant in `src/constants.py`. Runtime state (`Player.x/y/vx/vy`,
collision rects, bot simulation) is stored in **pixels**, with `CELL`
(currently 50 px/block) multiplied in ad hoc at dozens of call sites. This is
the "boat built in meters against a blueprint in feet" problem: the numbers
happen to work out, but the unit system itself is borrowed from rendering,
not from GD. Every future physics change has to fight through a
render-pixel lens instead of reasoning in GD's own units.

Confirmed live (2026-09-07, GD Creator School / community docs cross-check
via the Move Trigger's "Small Step" behavior): **1 block = 30 GD units**,
always — Small Step only changes the trigger UI's input granularity (10 vs
30 per click), not the underlying scale. This matches what the bible doc
already assumed, so the *physics numbers* don't change. What changes is
*where the pixel conversion happens*.

## Target model

- Canonical world unit: **GD units** (`1 block = 30 units`, matches the
  level format's existing grid-cell integers — `world_units = grid_cell *
  30`).
- `Player.x/y/vx/vy` and all collision/hitbox math run in **units** and
  **units/second**, integrated with `dt = 1 / PHYSICS_TPS`.
- `CELL` becomes a pure **render** constant: px-per-block on screen at
  zoom 1. It must not appear in `player/`, `physics.py`, `bots/`, or
  `jump_predictor.py` after this refactor.
- A single boundary module owns unit↔pixel conversion for rendering:
  `world_to_screen(x_units, y_units, camera) -> (px, py)` and the inverse
  `screen_to_world` for editor picking. Every renderer (`play_render.py`,
  `graphics.py`, `sprites.py`, `src/editor/render.py`) goes through it —
  no inline `gx * CELL` left scattered around.

## Scouting findings (already confirmed, no further investigation needed)

- `src/objects.py` and `src/levels.py` already store object positions as
  **scale-agnostic grid-cell integers** — zero `CELL` references in either
  file. The on-disk level format needs **no migration**; `LEVEL_FORMAT_VERSION`
  stays at 8.
- `src/particles.py` has zero `CELL` coupling — no changes needed.
- `GROUND_Y` is isolated to background parallax decoration in
  `graphics.py` — not gameplay-coupled, low risk, but move it to a render
  constant explicitly for clarity.
- `src/physics.py`'s `PlayerPhysicsParams` methods are unit-agnostic
  (they just use whatever constants are passed in) — safe once the
  constants passed to them are in real units.
- Three independent, currently-duplicated grid→px reconstructions exist:
  `player/collision.py`, `bots/sim.py`, and `jump_predictor.py`. This
  refactor is the opportunity to make the latter two call shared helpers
  instead of re-deriving the math a third and fourth time (fixes a
  pre-existing parity risk as a side effect, not the primary goal).
- Most existing test assertions in `test_physics.py`/`test_game.py`
  already express values as ratios/multiples of `C.CELL` rather than raw
  pixel literals, so most should survive with `CELL` redefined as a pure
  render constant. A handful of literal-px assertions will need converting
  to unit-space.

## Phases (checklist — kept in sync here and restated in chat each turn)

- [ ] **Phase 0 — scouting** (done: coupling map above)
- [ ] **Phase 1 — foundation**: add `UNITS_PER_BLOCK = 30` and a
      `src/units.py` (or extend `geometry.py`) with `block_to_units`,
      `world_to_screen`, `screen_to_world`. Rewrite `constants.py` physics
      block so gravity/jump/speed constants are defined directly in
      units/second (no `PX_PER_UNIT`/`VEL_PX_PER_TICK` bake-in). Keep `CELL`
      as a render-only constant.
- [ ] **Phase 2 — player core**: migrate `Player.x/y/vx/vy` and every
      spawn/checkpoint/teleport/mode-transition site in `player/core.py` to
      units.
- [ ] **Phase 3 — collision & geometry**: migrate `player/collision.py` and
      `geometry.py` hitbox/rect construction to unit-space.
- [ ] **Phase 4 — bot parity**: migrate `bots/sim.py` and
      `jump_predictor.py` onto the same shared unit-space helpers as
      `player/core.py`/`collision.py` (delegate, don't re-derive).
- [ ] **Phase 5 — rendering boundary**: introduce `world_to_screen` calls in
      `play_render.py`, `graphics.py`, `sprites.py`; remove inline
      `gx * CELL - cam_x` math.
      **Requires a real GUI/display playtest — cannot be verified headless.**
- [ ] **Phase 6 — editor**: untangle `editor/state.py`'s `CELL * zoom`
      conflation into separate unit-scale vs. camera-zoom concepts; route
      `editor/render.py` / `editor/ops.py` through the same boundary.
      **Requires a real GUI/display playtest.**
- [ ] **Phase 7 — play.py**: camera lead/offset and speed-portal/move-trigger
      x-lookup tables to unit-space.
- [ ] **Phase 8 — tests**: update `test_physics.py`/`test_game.py`
      literal-px assertions to unit-space; full regression pass.
- [ ] **Phase 9 — full playtest & sign-off**: GUI playtest every gamemode,
      editor placement/zoom, bot solve on a bundled level; update
      `docs/PHYSICS.md` to describe the unit model as implemented; remove
      `docs/PHYSICS_FIX.md` (superseded) or fold its outcome into
      `docs/development/AUDIT.md`.

Physics *numbers* (gravity, jump forces, speed ratios, hitbox fractions)
are not being retuned in this pass — only the unit system they're expressed
and computed in. Any numeric drift measured by `test_physics.py` after each
phase is a bug to fix, not an expected outcome.
