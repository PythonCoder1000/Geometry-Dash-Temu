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

## Decision: collision precision (2026-09-07)

`pygame.Rect` snaps to integer pixels — at `CELL=50` that's 50
subdivisions/block. Naively rebuilding the same hitboxes as integer *GD
units* (30/block) would coarsen collision precision: a real physics
regression, not just a representation change. Real GD (cocos2d) uses
floating-point coordinates internally, not integer-snapped ones. Decided:
**Phase 3 uses `pygame.FRect` (float rect, available in pygame-ce) in
unit-space** for all collision/hitbox math, matching GD's actual float
model. Rects are rasterized to integer-pixel `pygame.Rect` only at the
render boundary (`world_to_screen`), never for collision resolution.
Existing pixel-literal hitbox insets (e.g. spike's `Rect(17, 32, 15, 17)`)
are fractions of `CELL` by design (see geometry.py's own comments); they
convert exactly via `px_literal * (UNITS_PER_BLOCK / CELL)` = `px_literal
* 0.6`, preserving the identical fraction-of-block ratio, not retuning it.

## Phases (checklist — kept in sync here and restated in chat each turn)

- [x] **Phase 0 — scouting** (done: coupling map above)
- [x] **Phase 1 — foundation**: `UNITS_PER_BLOCK = 30`, `src/units.py`
      (`block_to_units`, `world_to_screen`, `screen_to_world`), physics
      constants redefined in units/second first, px/tick derived from them.
      Zero behavior change (test_physics.py 28/28, test_game.py 504/504
      bit-for-bit). Committed `1079450`.
- [x] **Phase 2 — player core**: `Player.x/y/vx/vy` and every
      spawn/checkpoint/teleport/mode-transition site in `player/core.py`
      migrated to units. `x_px`/`y_px`/`size_px`/`target_cam_y_px`/
      `render_pose_px()` added as the px boundary for renderers/camera.
- [x] **Phase 3 — collision & geometry**: `pygame.FRect` unit-space hitbox
      builders added to `geometry.py` (`cell_rect_units`, `slab_rect_units`,
      `spike_hitboxes_units`, `pad_trigger_rect_units`, `slope_polygon_units`,
      `saw_hitbox_units`, `rotate_local_frect`); `player/collision.py` fully
      migrated to consume them (float, no `round()`).
- [x] **Phase 4 — bot parity**: `bots/sim.py`, `jump_predictor.py`,
      `bots/loophole.py`, `bots/human.py`, `bots/brute_force.py`,
      `bots/toggle_search.py`, `bots/progress.py` all migrated to unit-space
      internals with a px boundary at every public output (waypoints,
      `SolveProgress`/`win_x_for_objects`, `nudge_coarse_px`,
      `BRUTE_FORCE_POS_BUCKET`/`VEL_BUCKET`, `scripts/bench_bots.py`'s CLI
      bucket args). Fixed several real float//int and px/unit scale-mismatch
      bugs caught by manual review (not by any failing test) along the way —
      see git log for `src/bots/*.py` this session.
- [x] **Phase 5 — rendering boundary** (code-complete, playtest still
      pending): `play.py`'s camera (`cam_x`/`cam_y`, `render_pose_px`,
      `target_cam_y_px`), death/best-run/particle/predicted-path/checkpoint-
      marker rendering in `play.py`/`play_render.py` all fixed to convert
      through the px boundary instead of mixing `player.x` (units) with
      `cam_x`/waypoints/particles (px). `graphics.py`/`sprites.py` needed no
      changes (already pure px, grid-cell driven).
      **Still requires a real GUI/display playtest — cannot be verified
      headless.**
- [x] **Phase 6 — editor** (code-complete, playtest still pending):
      audited `editor/state.py`/`render.py`/`ops.py`/`session.py` — the
      editor's own world/grid math is untouched (still px/CELL, by design,
      since the level format and editor canvas stay scale-agnostic grid
      integers). Fixed the one real bug found: `base_move_speed` (now
      unit-scale) fed unconverted into the px-space `real_time_to_x`/
      `x_at_time` music-preview helpers in `editor/session.py` and
      `editor/render.py`.
      **Requires a real GUI/display playtest.**
- [x] **Phase 7 — play.py**: camera lead/offset, speed-portal/move-trigger/
      teleport x-lookup tables confirmed self-consistently px (level-object
      grid math, untouched); the actual bugs were `player.x`/`render_pose`/
      `base_move_speed` leaking unit-scale values into this px-space code —
      fixed as part of Phase 5/6 above.
- [x] **Phase 8 — tests**: `test_physics.py` (28/28) and `test_game.py`
      (504/504) fully migrated to unit-scale assertions; one genuine stale
      test found (`wave_velocity` mirror estimate expected raw units where
      the code now correctly returns px) and fixed rather than papered over.
- [ ] **Phase 9 — full playtest & sign-off**: GUI playtest every gamemode,
      editor placement/zoom, bot solve on a bundled level; update
      `docs/PHYSICS.md` to describe the unit model as implemented; remove
      `docs/PHYSICS_FIX.md` (superseded) or fold its outcome into
      `docs/development/AUDIT.md`.

Physics *numbers* (gravity, jump forces, speed ratios, hitbox fractions)
are not being retuned in this pass — only the unit system they're expressed
and computed in. Any numeric drift measured by `test_physics.py` after each
phase is a bug to fix, not an expected outcome.
