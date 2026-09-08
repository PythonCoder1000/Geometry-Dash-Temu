# Trigonometry Sprint — Overhaul Audit

Final report for the refactor / fix / upgrade pass (commits `2e4bbd9` … `225e2e1`,
September 2026). Sections: what changed, what was removed, what was added,
known bugs that remain, and ideas that were deliberately left out.

Verification baseline: `.venv/bin/python test_game.py` — 365 checks, all passing.
Player physics was replayed frame-by-frame against the pre-refactor build on
every bundled level (25,598 frames, zero divergence apart from the two
intentional orb-semantics changes listed under Upgrades).

---

## 1. Refactor — what changed

### Architecture
| Before | After |
|---|---|
| `src/player.py` (one 2,600-line class with the mirror body duplicated as a dict) | `src/player/` package: `body.py` (`MirrorBody`), `collision.py` (`CollisionMixin`), `triggers.py` (`TriggerMixin`), `draw.py` (`DrawMixin`), `core.py` (`Player`). One set of body-parameterised physics methods serves both the main and the mirror body. |
| `src/play.py` (one 1,400-line `run_play` function, rendering inlined) | `src/play.py` `PlaySession` class with small named steps (`_tick_input`, `_tick_alive`, `_tick_camera`, `_advance_physics`, `_render`) plus `src/play_render.py`. `run_play(...)` is kept as a thin facade. |
| `src/editor.py` + `editor_tools.py` + `editor_render.py` (per-type property code hard-wired in three places) | `src/editor/` package: `ops`, `state`, `ui`, `props`, `render`, `dialogs`, `session`, `music_names`. Properties come from the object registry. |
| `src/graphics.py` (drawing + sprite baking + geometry helpers) | `src/graphics.py` (screen drawing), `src/sprites.py` (sprite baking and cache), `src/geometry.py` (hitbox and rotation maths). `graphics` re-exports sprite names lazily so old imports keep working. |
| Object metadata scattered across editor, palette, tooltips, save/load | `src/objects.py` registry: `ObjectSpec` / `Field` per type, `PALETTE_CATEGORIES`, `TYPE_NAMES`, `TYPE_TIPS`, `seed_defaults`, `get_field_value`, `spec_for`. Adding an object type is now one registry entry plus a sprite. |
| `settings.py` with a "TPS" option that scaled physics | `settings.py` exposes a real FPS cap (`FPS_CAP_OPTIONS`); physics is fixed at `PHYSICS_RATE = 60`. |

### Smaller cleanups
- Unified the editor's triplicated tool dispatch before the rewrite (commit `9cd49cb`).
- Removed the username hack lines from `main.py`.
- Circular import between `graphics` and `sprites` broken with a lazy module `__getattr__`.
- Unused imports removed across the new packages (pyflakes clean on `src/editor`, `src/player`, `main.py`).
- `exports/` (PNG level exports) is now git-ignored.
- Bundled sprites in `assets/sprites` were rebaked with the v2 renderer and carry a `.version` marker, so packaged builds no longer re-render every sprite on first boot.

## 2. Fixes

| Bug | Fix |
|---|---|
| **Rendering judder** (the "major one"): the game rendered at whatever frame rate the loop hit, while physics stepped at 60 Hz with no interpolation, so the player and camera visibly stuttered at any refresh rate that was not exactly 60. | Physics runs on a fixed 60 Hz accumulator; the renderer interpolates player pose and camera between the previous and current tick (`Player.render_pose(alpha)`, `PlaySession._render`). The FPS cap is now a genuine setting (60 / 120 / 144 / 240 / uncapped). |
| Background did not cover the full screen height when the camera moved vertically. | Full-height background draw with camera-y offset. |
| Trail rendering re-created a surface per point per frame. | Trail sprites cached per mode/colour. |
| Blue orb launched the player like a jump instead of only flipping gravity. | Blue orb and blue pad now flip gravity with a small push (`BLUE_ORB_PUSH_SCALE`, `BLUE_PAD_PUSH_SCALE`). |
| Mirror (dual) body drifted from the main body because its physics was a hand-copied subset. | Both bodies run the same methods. |
| Checkpoints forgot player size (mini/big). | Size stored and restored. |
| Editor test runs were silent even when a track was chosen. | Music gates now depend only on the track. |
| Editor exposed a Test-speed selector that desynced music and physics. | Removed; physics rate is fixed. |
| Editor could lose work on an exception. | `run_editor` wraps the session, shows a modal, and the autosave is offered on next open. |
| Zoom did not anchor on the cursor and grid drifted at fractional zoom. | `EditorState.set_zoom(anchor=...)`, grid rebuilt per effective cell size. |
| Scaled objects were culled while still on screen. | Scale-aware culling in `render._in_view`. |

## 3. Upgrades (synced with Geometry Dash)

Physics numerics (gravity, jump force, speeds, hitbox fractions) are untouched.

- **Orb colours re-mapped to GD** (level format v7, automatic migration): old "blue" (jump + flip) is now **green**, old "green" (medium jump) is now **yellow**, and **blue** is a pure gravity flip.
- Pink orb / pad = 0.75× jump, red orb / pad = 1.35×, matching GD's relative strengths.
- Gravity dash orb (pink dash) flips gravity when the dash ends.
- Spider pad teleports to the opposite surface instantly; spider orb does the same on click.
- Wave mode ignores pads, as in GD.
- Jump predictor understands swing and robot modes.
- **Editor rebuilt in the GD layout**:
  - Bottom bar with **Build / Edit / Delete** tabs, category tabs and a paged object grid (1–9 picks, Tab cycles categories).
  - Edit toolbar: rotate ±90/±45, flip H/V, scale ±, copy / cut / paste / duplicate, nudge (Ctrl = 5 cells), invisible, bot-only, Edit Object (registry-driven property panel), Link tool, Bot Path, snippets.
  - Delete toolbar: delete selected, delete all of a type, clear, delete-filter.
  - Left strip: Swipe, Rotate (drag-rotate with 15° snap, Shift = free), Free move, Grid, Hitbox overlay, Zoom ±, 1:1.
  - Top bar: Menu, Test, Bot | Undo, Redo, Save, Publish, Load, Track, Music, SFX, ?.
  - Marquee select, Shift-click add/remove, click-again to cycle a stack, right/middle drag pan, wheel zoom anchored on cursor, F1 shortcut sheet.

## 4. Removed

- `src/editor.py`, `src/editor_tools.py`, `src/editor_render.py`, `src/player.py` (replaced by packages).
- The editor's Test-speed selector and the "TPS" setting.
- Old bundled sprites for sizes no longer drawn (26, 40, 44, 52, 10 px) and for retired types.
- Username hack in `main.py`.

## 5. Known bugs that remain

- **Two orbs in consecutive sub-steps** can both fire in one frame (visible on `death_corridor` at frame 19). GD applies a per-frame orb lock. Fixing it changes the physics outcome of existing levels, which the brief forbids.
- **Rotate-drag on a mixed selection** rotates each object about its own centre, not the selection centre, so relative positions do not orbit. Orbiting would require fractional positions (see Free move below).
- **Free move** is a toggle in the side strip but positions stay cell-snapped; the level format has no fractional coordinates yet.
- **Autosave recovery modal** is blocking; if the game is launched headless (dummy video driver) with an autosave present, it waits forever. Only affects scripted runs.
- **Choice fields** in the property panel are cycled with the +/- buttons or typed by name; there is no dropdown list, so an unfamiliar choice set has to be stepped through.
- Level thumbnails are regenerated only on save, so a level edited via autosave recovery keeps its old thumbnail until saved.

## 6. Ideas deferred (blocked, risky, or out of scope)

- **Toggle / spawn / trigger orbs and touch triggers**: need a group-toggle state machine in the player and a "groups" concept in the editor. Doable, but it doubles the trigger system and risks the physics-equivalence guarantee.
- **Mirror portals and teleport portals**: mirror requires a horizontally flipped render and input path; teleport portals conflict with the existing teleport-orb group scheme.
- **22.5° / 2:1 slopes**: geometry and hitbox code assume 45° slopes in several places; adding a second slope angle touches collision maths that must stay identical for existing levels.
- **Fractional (pixel) object positions** for true free move and rotation about a selection centre: needs level format v8, editor snapping rules and updated spatial-index buckets.
- **Swipe defaults to ON**, whereas GD defaults it off. Kept ON because every existing user flow expected drag-paint; a single flag in `EditorState`.
- **Reinforcement-learning bots**: the existing search bots already solve bundled levels; an RL agent would need a headless environment and a training budget that is out of scope.
- **Undo for property-panel edits per keystroke**: the panel pushes one undo entry per committed field, not per character, to keep the undo stack usable.
- **Camera triggers with easing curves and zoom**: current camera trigger only sets offset; GD's zoom/rotate camera would require the renderer to support scale, which the interpolation path does not yet.

## 7. How to continue

- Run `.venv/bin/python test_game.py` after any change; it replays golden playthroughs and will flag physics drift.
- Add an object type by adding an `ObjectSpec` in `src/objects.py`, a sprite in `src/sprites.py`, and (if it moves the player) a branch in `src/player/core.py`. The editor palette, tooltips, property panel and save/load pick it up automatically.
- Bump `LEVEL_FORMAT_VERSION` and add a `_migrate_objects` step for any rename.

---

# Addendum — Physics-Bible / Editor-Reference Overhaul (September 2026)

Second, larger pass, explicitly superseding this file's §3 line "Physics
numerics ... are untouched." The user authorized replacing every physics
constant with values derived from a sourced community reference,
`docs/reference/geometry-dash-physics-bible.md`, and overhauling the editor to match
`docs/reference/gd_editor_complete_reference.md`. Verification
baseline: **`.venv/bin/python test_game.py` — 504 checks, all passing**
(one failure was open through most of this pass; root-caused and fixed,
see §14). Ten checkpoints, done in order (physics first, per the user's
instruction), each left uncommitted for review.

## 8. Physics constants changed (Checkpoints 1–3)

All in `src/constants.py`, each with an inline source citation and
confidence flag added at the point of definition (reproduced here so this
file is self-contained):

| Constant | Bible source | Confidence | Note |
|---|---|---|---|
| `PHYSICS_TPS`/`FPS` 60→240 | Part 0, §2.7 | well-corroborated | 240 TPS is GD 2.2's standardized loop |
| `GRAVITY` (cube accel) | §1.4 | single-source estimate | ~72 blocks/s², happens to reproduce the old value exactly once expressed in the new tick system |
| `JUMP_FORCE` (cube, 1x) | §1.3/§1.4 | well-corroborated | 11.18G |
| `BALL_FLIP_FORCE` | §1.3/§1.4 | well-corroborated | 3.354G, "3/10 of cube" |
| `UFO_JUMP_FORCE` | §1.4 | well-corroborated | constant 7G at every speed, used for both grounded launch and midair flap |
| `ROBOT_THRUST` (repurposed as fixed hold velocity) | §1.4 | well-corroborated | 5.59G, "1/2 of cube"; gravity now fully disabled while held, not just countered |
| `SHIP_GRAVITY`/`SHIP_THRUST` | §1.4 | **single-source estimate, and the bible itself calls ship "genuinely unresolved... don't rely on it"** | ratio-preserved from pre-retune tuning; `SHIP_THRUST` has no bible figure at all |
| `MAX_FALL_BOX/UFO/SWING`, `SHIP_MAX_RISE/FALL` | §1.3 | well-corroborated | −15G / −6.4G / −8G / 8G / −6.4G |
| `SWING_VY_MULTIPLIER = 0.8` | §1.4 | well-corroborated | "multiplies y-velocity by 0.8, then toggles gravity" |
| `SPEED_VALUES` (speed portals) | §1.8 | well-corroborated (ratios), labels are known-misleading | 0.807/1.0/1.243/1.502/1.849 × `BASE_MOVE_SPEED` |
| `MINI_WAVE_ANGLE_SCALE` | §1.6 | well-corroborated | 63.43°/45° exact |
| `MINI_GRAVITY_SCALE`/`MINI_JUMP_SCALE`/`MINI_WAVE_VY_SCALE` | §1.6 | **undocumented — qualitative only** | kept as pre-retune tuning, not bible-derived |
| `ORB_PINK/RED_SCALE`, `PAD_PINK/RED_SCALE`, `PAD_FORCE` ratio | — | **no bible figure exists** | retained from pre-retune tuning |
| `DASH_TIME = 9` | — | **dead constant** | a dash now runs until stopped (S/wall/death); nothing reads this value |
| `HITBOX_SOLID_FRACTION` per-mode table | §3.2 | well-corroborated, except: | Cube/Ship/Ball/UFO/Robot/Swing 9/30 (10/18 mini); Wave 3/10 (3/6 mini); Spider 9/27.5 (10/16.5 mini) |
| Spider mini-red (16.5) | §3.2 | **flagged uncertain by the bible itself** | kept as-is, not resolved |
| `TICKS_HELD` table | §2.6 | well-corroborated as a *documented fact*, but **not wired as a gameplay gate** | see §13 below — deliberate scope decision |
| `INPUT_BUFFER_TICKS = 24`, `TELEPORT_COOLDOWN_TICKS = 40` | — | **no bible figure** ("no numeric orb buffer window is published anywhere," §2.6) | both are the engine's pre-existing windows, rescaled 4× to preserve real-world duration at 240 TPS |
| Hazard/block/slope hitbox sizes (spikes, saws) | §3.3 | **undocumented numerically** | left untouched, as directed |
| Slope hitbox as "inscribed circle" | §3.1 | **qualitative only, no numeric spec** | left as the existing diagonal-rect resolution, not rewritten |

## 9. Letter blocks added (Checkpoint 3, bible §4)

- **S-Block** (pre-existing `T_DASH_STOP`) — verified against §4.2: fires the dash orb, then ends the dash early, doesn't prevent it. Already correct, no change needed.
- **J-Block** (`T_JUMP_BLOCK`) — suppresses the landing auto-jump after holding through an orb (§4.1).
- **D-Block** (`T_WAVE_BLOCK`) — lets Wave slide on a block's top surface instead of dying on contact (§4.3).
- **H-Block** (`T_BONK_BLOCK`) — Cube/Robot bonk harmlessly off a block's underside/side instead of dying (§4.4).
- **F-Block — deliberately not implemented.** Bible §4.5 marks it the least-documented letter block ("can't figure out exactly what it does" even in the community sources it cites); the plan explicitly allowed deferring it. Open item, not a bug.

**Process note:** a fork tasked with this exact sub-step initially reported all three new blocks implemented and tested; a follow-up `grep` before trusting that report found none of the code had actually landed on disk. It was redone and re-verified with grep proof pasted into the report. Every checkpoint after that one was explicitly instructed to prove its work the same way.

## 10. Editor systems added (Checkpoints 4–9, `gd_editor_complete_reference.md`)

| System | Doc source | Summary |
|---|---|---|
| Real Group IDs | §4 (intro) | `groups: list[int]` per-object membership, decoupled from the pre-existing teleport-pairing `group_id`; both coexist |
| Color channels | §4 (intro), §5 ("RGB and HEX code input") | level-meta channel table (`src/channels.py`), same override pattern as `PhysicsParams`; Color/Pulse Trigger reference a `channel`, not a literal palette index |
| Spawn / Toggle / Stop / Sequence / Scale / Alpha Triggers | §4 | full group-targeted trigger family, spawn-triggered/touch-triggered/multi-activate flags, `ease_in`/`ease_out`/`ease_in_out` easing |
| Camera family (Zoom, Static, Offset, Rotate, Edge, Guide) | §4 "Camera" | extends the existing basic camera trigger and `play.py`'s camera state, doesn't replace it |
| Screen effects (Grayscale, Sepia, Invert, Hue, Pixelate) | §4 | numpy-based per-frame post-process in `play_render.py` |
| Item/Pickup, Count/Instant Count, Item Edit, Item Comp, Item Pers, Timer/Time Event, Item Counter HUD | §4 "Item/counter/timer" | per-attempt `Player.items` dict + persistent `items_pers` (survives `reset()`, not cross-launch — see §13) |
| Keyframe object + Keyframe Trigger | §4 | Time/Even/Dist timing modes, position delta-based / rotation-scale absolute, reuses Checkpoint 5's easing |
| Editor layers (visibility + lock), Select Filter | §5 | lock enforcement centralized at every selection-assignment site via `state.filter_locked`, so it transitively covers move/rotate/scale/delete/cut |
| UI reorg | §5 | split the overloaded Triggers tab into Triggers/Camera/Items categories; `CATEGORY_ORDER` is hand-authored, not auto-discovered — a future category needs a manual addition there |

## 11. Explicitly deferred / excluded (both docs)

- **F-Block** (§4.5) — least-documented letter block, deferred per plan.
- **Auto-Build, Particle Editor** — asset-pipeline-heavy (auto-build needs a large corner/edge tileset this clone doesn't have); not built.
- **Hard object/group caps** (40,000+ objects, 9,999 groups) — not meaningfully load-bearing at this clone's scale; not built.
- **Shader-heavy screen effects** — Chromatic, Chromatic Glitch, Radial Blur, Motion Blur, Bulge, Pinch, Lens Circle, Split Screen, Shock Wave/Line. No trigger types were added for these at all (confirmed via grep — no dangling half-wiring), since real per-pixel shader displacement isn't practical in plain pygame.
- **Rotate Trigger easing** — accepts an `easing` field but doesn't yet apply it (kept the pre-existing constant-rate spin math). Scope trim, not a silent drop.
- **RobTop-service-specific features** — Steam/mobile Create-button UX, level upload/servers/Lists, the Music Library/NCS *licensed content* (song/SFX trigger *mechanics* are in scope; the actual catalogs are not), third-party Editor Collab mod parity. Out of scope by design — these describe a live service, not portable game logic.

## 12. Real bugs found and fixed during this pass

- **Group/trigger field-name collision (Checkpoint 5).** `levels.get_groups()`'s legacy fallback reads a bare `"group"` int as group *membership*; the first draft of Spawn/Sequence's target field was also named `"group"`, so a Spawn trigger became a phantom member of its own target group and re-fired itself every tick (confirmed via instrumentation: 4.5M calls in one tick before being killed). Fixed by renaming every trigger's target field to `target_group`/`target_group2/3/4`. **Any future trigger field must not be named bare `group` for this exact reason.**
- **Stale `_check_ground_adjacency` grounding bug, exposed by the retune (Checkpoint 3).** Sticky-grounding ignored vy direction; the old, larger per-tick jump velocities always cleared the proximity zone in one tick, masking it. The new, slower per-tick jumps got re-grounded before they could rise. This was a real pre-existing bug, not a new one — fixed by only snapping/grounding when vy already points toward the surface.
- **`PathFollowController` threshold/lookahead tick-baseline bug (this checkpoint, §14 below).**
- Bot fairness constants `HUMAN_MIN_DWELL_FRAMES`/`DWELL_CAP` were rescaled (2→8, 8→32 ticks) to preserve real-world reaction-time semantics under 240 TPS.
- A duplicated "Target group" property-panel field on Scale/Alpha Trigger (cosmetic, harmless) was found and deduped during Checkpoint 9.

## 13. Known-unfixable / open items (inherited from the docs' own caveats)

- **Ship's hold/release acceleration is genuinely unresolved** per the bible itself — `SHIP_GRAVITY`/`SHIP_THRUST` are a ratio-preserved estimate, not a sourced constant.
- **F-Block's exact behavior is unresolved** even in the community sources the bible cites — deferred rather than guessed at.
- **Hazard/block hitbox sizes (spikes, saws, slopes) are undocumented in any accessible source** (§3.3) — left exactly as they were pre-overhaul.
- **Slope angle discrepancy** (22.5° vs 26.6° across two GD Creator School pages, per the bible) — unresolved, this codebase's existing slope geometry was not touched.
- **`TICKS_HELD` is documented but deliberately not gameplay-enforced.** The bible's "ticks held" describes an internal tick-ordering quirk (why a buffered jump lands slightly higher — gravity applies before vs. after the velocity is set within the same tick), not a player-facing wait state. Ship/UFO/Wave/Swing already act every tick they're held, which is correct GD behavior; adding a literal hold-before-acting delay would introduce input lag the real game doesn't have. Left as a reference table only, for any future, more faithful modeling of the tick-ordering effect itself — not attempted here.
- **Item Pers persists only within a session** (survives `Player.reset()`/retries via `items_pers`), **not across separate game launches** — a deliberate scope choice (the plan's persistence layer, `src/stores.py`, handles level/auth data, a different concern), not a bug.
- **No `LEVEL_FORMAT_VERSION` bump was needed for the new `layer` field** (defaults to 0 via `.get`), so no migration exists for it — this is correct as long as `layer` never becomes a non-zero-default field later.

## 14. The one open test failure — root-caused and fixed

`test_game.py`'s "a route that follows the ground line is not flagged as
a loophole" failed from Checkpoint 3 onward (503/504). It was initially
attributed to `LoopholeBot`'s A* search accepting a suboptimal
bunny-hopping route via early-exit termination (a real, pre-existing
architectural property of `HumanBot._astar`: it returns as soon as any
expanded child is a winning node, not necessarily the lowest-cost one —
left alone here since fixing it globally would touch shared search code
used by many other passing tests). A small, local mitigation was added in
`LoopholeBot.solve()` (`src/bots/loophole.py`): if the plain, undeviated
path-follow already wins in the same or fewer frames as the search route,
prefer it, since the module's own docstring says deviation should only
win when it "reaches the end wall sooner." This did not fix the test.

Direct investigation found the *actual* root cause: `PathFollowController`
itself (the PD-style controller that generates the "plain follow" seed)
was bunny-hopping on its own, on a perfectly flat level. Its jump
threshold is `THRESHOLD_BY_MODE[mode] * (speed / 5.0)` — the `5.0` was a
hardcoded stand-in for `BASE_MOVE_SPEED`'s *pre-retune* value at 60 TPS.
After the tick migration, `BASE_MOVE_SPEED` is `1.25`, so the threshold
silently shrank 4×, making the controller react to sub-pixel positional
noise as if it were a real deviation and jump for no reason. `LOOKAHEAD_BY_MODE`
had the same class of bug (tick counts authored for 60 TPS, unscaled).

**Fix** (`src/bots/loophole.py`): import `BASE_MOVE_SPEED`/`PHYSICS_TPS`
from constants; replace the literal `5.0` with `BASE_MOVE_SPEED`; scale
every `LOOKAHEAD_BY_MODE` entry by `round(PHYSICS_TPS / 60)`. Verified
directly: the seed's measured deviation on the test's flat level dropped
from 170px (63% of the run off-path) to 6px (0% off-path, well inside the
`PATH_CORRIDOR_PX` = 100px corridor). **`test_game.py` now passes 504/504.**
The local `solve()` mitigation from the first attempt was left in place
(it's correct per the module's documented intent and harmless), even
though it wasn't what fixed this particular case.

## 15. Verification performed this pass

- Full `test_game.py`: **504/504**, up from the 365 baseline in §0 (this pass added ~140 new checks across all ten checkpoints).
- Headless per-gamemode check: all 8 gamemodes (Cube baseline + 7 mode portals) run 240 ticks (1 real second) on a flat level without crashing, each advancing ~300px.
- Editor layer/lock/Select-Filter behavior verified with real headless scripts during Checkpoint 9 (hiding a layer excludes its objects from render; locking a layer blocks selection/move/delete; Select Filter by-type/by-group returns the correct subsets) — see that checkpoint's own report for the printed values.
- Trigger chains (Spawn→Toggle→Move, Scale/Alpha convergence, Sequence→Move→Stop, Item pickup→Comp→fire, Zoom/Static camera tracking, Grayscale pixel values, 3-keyframe interpolation) were each verified with real headless scripts during their respective checkpoints, not just wired and assumed — see each checkpoint's own report for exact printed output.
- **Not verified in this pass: a real GUI/display playtest.** This environment has no display. Everything above is headless (`SimPlayer`/`Player` instantiated directly, no pygame window). Before considering this overhaul shipped, a human should run the game via the `run` skill and play through one level per gamemode, open the editor and place a few of each new trigger type, and specifically look at the screen effects (Grayscale/Sepia/Invert/Hue/Pixelate) and camera triggers (Zoom/Static/Offset/Rotate/Edge/Guide), since visual feel, rendering correctness, and UI layout at real scale can't be confirmed headlessly.

## 16. Saved bot runs

One saved run exists: `bot_runs/f_nine_circles__run_nine_circles.json` (predates this overhaul, April 2026). Its recorded inputs were captured under the old 60 TPS / pre-retune physics constants and will not replay identically now — the existing "re-verify saved bot runs on load instead of trusting stored status" behavior (already shipped, see the commit log) means the game will correctly detect this on next load rather than silently trusting a stale "solved" status. No attempt was made to re-record it in this pass; that's a one-time manual step (open the level, re-run the bot) left for whoever next touches that level.

## 17. State of the working tree

All ten checkpoints are implemented and uncommitted. No git commits have been made anywhere in this overhaul — committing (and how to split it, if at all) is left as the user's decision after reviewing the diff and doing the GUI playtest from §15.
