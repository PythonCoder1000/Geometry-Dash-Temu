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

---

# Addendum — GD Trigger Parity Overhaul (September 2026)

Third pass, built against `deep-research-report.md` (repo root), which documents real
Geometry Dash's editor trigger system — ~133–143 trigger/object types, real numeric
Object IDs and property keys, activation semantics, and same-frame precedence rules —
and is explicit that large parts of the spec are the literal string `"unspecified"`
(defaults, ranges, several IDs, and universal composition/collision rules). That
honesty is preserved here rather than silently upgraded to invented precision: nothing
in this pass converts an `"unspecified"` report value into a plausible-looking number.

This pass extends, not replaces, the registry-driven object/trigger system from the
prior overhaul (§8–17 above): `src/objects.py`'s `SPECS`/`ObjectSpec`/`Field` schema
still drives serialization and editor UI generically. Nine checkpoints, each left
uncommitted for review, physics untouched throughout (confirmed: no `.py` file other
than the trigger/object/render/bot plumbing listed in `git diff --stat` was touched by
this documentation pass itself, and this pass did not modify any of those files either
— see §25).

**Verification baseline:** `.venv/bin/python test_game.py` — baseline before
Checkpoint 0 was **504 passed** (the final count from the prior addendum, §15).
**Final count after Checkpoint 8: 844 passed, 0 failed**, confirmed by running the
suite directly for this addendum.

## 18. Data model: `gd_object_id` / `gd_key` / `verification` (Checkpoint 0)

`src/objects.py` gained three pieces of metadata, populated only where the report
gives a verified value and left `None` everywhere the report itself says
`"unspecified"` (e.g. all four pre-existing letter blocks — S/J/D/H — carry no
`gd_object_id`, matching the report's own "every letter block ID is unspecified where
not independently verified" line):

- `ObjectSpec.gd_object_id: int | None` — the real GD Object ID.
- `Field.gd_key: int | None` — the real GD numeric property key.
- `verification: str` on both — `"verified"` / `"partial"` / `"unverified"`, mirroring
  the report's own confidence tiers (its Unverified tier is literally "anything not
  corroborated sufficiently; literal `\"unspecified\"`").
- `GD_ID_TO_TYPE` (a `{gd_object_id: type}` dict) and `gd_field_map(t)` (module bottom,
  `src/objects.py:1779-1783`) — lazy lookup plumbing for future capability (e.g. a real
  `.gmd` import/export path), not called anywhere yet.

Grepping the current tree: **64 fields/specs are `verification="partial"`**, **18 are
`"unverified"`** (mostly Trigger Order and a handful of best-effort fields), **26 are
`"verified"`** (the pre-existing families from the prior overhaul that the report also
corroborates). No format change was made to level JSON — `src/levels.py` keeps its
descriptive string keys; this was a deliberate scope decision (see the plan's
"Numeric IDs: hybrid/metadata-only" note) since GD's numeric keys are reused per
object type with different meanings, and this project never imports/exports real
`.gmd` files.

## 19. Dispatcher refactor: registry + ordered event queue (Checkpoint 1)

The old `_execute_trigger_effect` if/elif chain (`src/player/triggers.py`, previously
~110 lines) is now a single dict lookup against `TRIGGER_HANDLERS`
(`src/player/trigger_registry.py`), populated at import time by a registration block
at the bottom of `triggers.py`. Existing `_start_*`/`_apply_*` method bodies were
**not rewritten** — only registered — keeping behavior risk near zero for every
pre-existing trigger.

The real change is the ordered event queue. Both prior direct-call sites
(`core.py`'s touch handling, `triggers.py`'s `_fire_group`) now call
`_enqueue_trigger_event(o, family)` instead of executing inline; `Player.update()`
calls `_drain_trigger_event_queue()` once, as its last step, after all of that tick's
touch/spawn/watcher enqueuing. The sort key is:

```
(activation_family_rank, trigger_order, x, placement_priority, stable_object_index)
```

**⚠ Engine convention, not a GD-verified fact.** The report specifies ordering
*within* the spawn family (left-to-right by x) and an ascending Trigger Order for
regular/touch triggers, but explicitly does **not** say how families rank against
each other. `trigger_registry.py`'s own docstring calls this out directly:

| Rank component | Value / source | Status |
|---|---|---|
| `activation_family_rank` | `TRIGGER_FAMILY_SPAWN=0`, `TRIGGER_FAMILY_TOUCH=1`, `TRIGGER_FAMILY_REGULAR=2` (unused currently) | **engine-invented** — report leaves cross-family order unspecified |
| `trigger_order` | new `_F_TRIGGER_ORDER` field (`objects.py:339`) on `_TRIGGER_COMMON_FIELDS` | report names the concept ("ascending Trigger Order value") but cites **no GD property key** — `gd_key=None`, `verification="unverified"` |
| `x` (spawn horizontal order) | triggering object's x position | report-sourced (spawn processes left-to-right) |
| `placement_priority` | **always `0`** | report's "most recently created wins" tiebreak has no timestamp available in this engine's data model; the slot exists only so the key shape matches the report — **documented gap, never actually discriminates** |
| stable object index | `self._oid_index[id(obj)]` | final deterministic tiebreak, engine-internal |

A handler may enqueue further events mid-drain (Spawn firing a group, Item Comp
firing on comparison); the drain loop re-sorts and re-runs newly appended entries,
bounded by `TRIGGER_DRAIN_MAX_PASSES = 64` — the same defensive posture as the
previously-fixed self-refire bug (§12 above).

## 20. New trigger families (grep-generated from `gd_object_id`/`verification` metadata)

| Family (Checkpoint) | Types | Real GD Object ID(s) | Report section | `verification` |
|---|---|---|---|---|
| Area (2) | Move/Rotate/Scale/Fade/Tint/Stop + 5 Edit-Area (11 types) | `3006`–`3015` range family, `3024` (Edit) — see spec comments | "Area and keyframe system" | `partial` |
| Random (3) | Random Trigger | `1912` | "Core object..." | `partial` |
| Advanced Random (3) | Advanced Random Trigger | `2068` | "Core object..." | `partial` |
| Force Block (3) | Force Block | `2069` | "Force and state precedence" | `partial` |
| Shader/screen (4) | Shader Trigger (base), Chromatic Aberration, Radial Blur, Motion Blur, Bulge, Pinch, Split Screen | `2904`, `2910`, `2914`, `2915`, `2916`, `2917`, `2924` | "Shader and visual effects" | `partial` |
| Audio (5) | Song, SFX, Edit Song, Edit SFX | `1934`, `3602`, `3605`, `3603` | "Audio, timers, and arithmetic" | `partial` |
| Gameplay/player-state (6) | Gameplay Rotation, Reverse, Teleport Trigger, Checkpoint Trigger | `2900`, `1917`, `3022`, `2063` | "Gameplay, camera, UI, and environment" | `partial` |
| Environment/UI/event/end (7) | Change Ground, Change MG, BG Speed, MG Speed, UI Trigger, Event Trigger, End Trigger | `3030`, `3031`, `3606`, `3612`, `3613`, `3604` (`unverified`), `3600` | "Gameplay, camera, UI, and environment" | mostly `partial`, Event Trigger `unverified` |

Every row above is pulled from each spec's own `gd_object_id=`/`verification=`
metadata (`src/objects.py`), not hand-transcribed — confirmed via
`grep -n 'gd_object_id=' src/objects.py`, which currently lists all 53 populated
values in file order. None of this family carries `verification="verified"`: the
report's own numeric IDs for these types are corroborated but the field-level
semantics (defaults, ranges, composition rules) are engine interpretation on top of
report-cited keys, hence `partial` rather than `verified`.

### Checkpoint 2 — Area system details
- Runtime store: `self.active_areas: dict[effect_id, dict]`, mirroring the pre-existing
  `active_effect_anims` pattern. `priority` (gd_key `341`) is **stored but never
  consumed** — `_step_area_effects` walks `active_areas` in insertion order rather
  than reading `priority`, an explicit trim documented at `triggers.py:705`
  ("Deliberately unlike..."). Two overlapping areas on one object resolve
  last-write-wins, marked best-effort since the report gives no composition rule.
- Tint render pipeline: `src/sprites.py`'s `draw_obj` gained a `tint` parameter
  (`(r, g, b)` multiply-blend via `pygame.BLEND_RGBA_MULT`), wired through
  `play_render.py`'s `obj_tint(o)` call. No specific pre-existing rendering bug was
  found attributed to this addition during verification — the plan's suggested "P1
  bug in `sprites.draw_obj`" did not surface as a discrete fixed defect in the current
  code/history; if one was found and fixed by the Checkpoint 2 agent, it is not
  independently documented in code comments, so it is **not** claimed here as a
  verified finding (see §24 for the audit's general caution about unverifiable prior
  claims).

### Checkpoint 3 — Random / Advanced Random / Force Block
- Force Block's one exact, quotable precedence rule is implemented literally:
  **different `force_id` stacks, same `force_id` does not**, via a per-frame
  `self._force_ids_this_frame: set()` cleared each tick (`core.py:1151-1246`).
- **Bot-determinism flag (new, prominent):** `_apply_random_trigger` and
  `_apply_advanced_random_trigger` both call `random.random()` directly
  (`triggers.py:1188`, `1211`) with no seed control exposed to the bot layer. Grepping
  `src/bots/*.py` and `src/bot_menu.py` for `RANDOM_TRIGGER_TYPES`/`T_RANDOM_TRIGGER`/
  `T_ADVANCED_RANDOM_TRIGGER` returns **nothing** — no bot special-cases or seeds
  these triggers. **This means bot solves (brute-force, human-heuristic, loophole) for
  any level that places a Random or Advanced Random Trigger are not reproducible run
  to run**, since the RNG draw that picks the fired group is not part of any bot's
  action space or replay determinism model. This is a genuine open item from this
  checkpoint, not inherited from the report.

### Checkpoint 4 — Shader/screen effects
- Implemented (6, feasible in the existing numpy `apply_screen_effects` pipeline):
  Chromatic Aberration, Radial Blur, Motion Blur, Bulge, Pinch, Split Screen, plus the
  base Shader Trigger (`disable_all`/`lowest_layer`/`highest_layer`).
- **Explicitly not implemented** (6): Gradient (`2903`), Shock Wave (`2905`), Shock
  Line (`2907`), Glitch (`2909`), Chromatic Glitch (`2911`), Lens Circle (`2913`) —
  `constants.py:465-466` and `play_render.py:725-727` both record the reason: these
  need true per-pixel GPU-shader-style displacement that plain pygame/numpy cannot do
  at frame rate, the same reasoning the prior overhaul already used for this effect
  class (§11 above).
- `SCREEN_EFFECT_PARAMS` (`triggers.py:142`) consolidates every effect's field list
  into one table consumed by `_start_effect_trigger`/`apply_screen_effects`.
- Motion Blur's ring buffer of recent rendered frames lives on `PlaySession`
  (`self.motion_blur_frames`, `play.py:439-444`), **not** on `Player`. Reason: it is
  render history (composited frames), not player/physics state — `Player`/`SimPlayer`
  is replayed and copied for bot search without a display surface at all, so a frame
  buffer has no meaning there and would bloat every simulation copy for no benefit.
- Base Shader Trigger's `lowest_layer`/`highest_layer` are stored but read by nothing:
  this engine has no render-layer concept, so `disable_all` (clears every entry in
  `active_effect_anims`) is the only field implemented literally.

### Checkpoint 5 — Audio triggers
Real vs. stored-only fields, per `_SONG_PARAMS`/`_SFX_PARAMS` (`triggers.py:252-270`):

| Trigger | Real fields | Stored-only no-ops | Why |
|---|---|---|---|
| Song | `song`, `volume`, `start`, `fade_in`, `fade_out`, `loop`, `channel` | `speed`, `end` | no playback-rate control exists on `pygame.mixer.music`; no scheduled-stop primitive exists (Edit Song's `stop` + the song's own `fade_out` is the only way to end one) |
| SFX | `sfx`, `volume`, `loop`, `unique_id` | `pitch`, `reverb` | `sfx.py` has no pitch-shift primitive on `Sound`; no DSP stage exists for reverb — best-effort no-op rather than building either from scratch |
| Edit Song / Edit SFX | patch by `channel`/`unique_id`, `stop`, absolute (not delta) value updates | same inherited no-ops as above | mirrors the Area family's "patch live state by id, absolute values" pattern |

- **`SimPlayer.audio_output_enabled = False`** (`src/bots/sim.py:98`, vs.
  `TriggerMixin.audio_output_enabled = True` default) — every audio trigger still
  updates `active_songs`/`active_sfx` state (so a bot's simulated world state stays
  identical to real play, e.g. for anything that later reads "is a song playing"),
  but no actual `pygame.mixer` calls happen during bot search. This matters for **bot
  search correctness**: without this flag, thousands of simulated ticks per search
  iteration would each try to start/stop real audio playback, which is both wrong
  (search shouldn't have side effects on the real mixer) and prohibitively slow.
- **P1 bug avoided, not found-and-fixed:** `music.py` maintains two separate volume
  scalars — `_volume` (user's saved preference, written to disk via `prefs.set`) and
  `_level_volume` (a per-level multiplier set by `set_level_volume`, `music.py:240`).
  A Song/Edit Song Trigger's `volume` field calls `set_level_volume` exclusively
  (`triggers.py:810`, `868`) and never touches `_volume`/`prefs`. This was evidently a
  deliberate design choice made *during* this checkpoint (the multiplier abstraction
  exists specifically so a level's authored song volume can never overwrite the
  player's saved system volume preference) rather than a bug discovered after the
  fact — the comment at `music.py:31` documents the distinction directly.

### Checkpoint 6 — Gameplay Rotation, Reverse, Teleport Trigger, Checkpoint Trigger
- **New public-ish attribute:** `Player.move_dir` (`core.py:146,417`, `+1`/`-1`) is a
  genuine new addition to `Player`'s public-ish surface, not an internal-only field —
  it is included in both bots' dedup/state-hash keys
  (`src/bots/sim.py:396,739,830` and `src/bots/brute_force.py:589`), so any bot code
  that hashes player state to detect duplicate search nodes now depends on it. This is
  additive (a new field), not a rename/removal, so it does not violate the project's
  stability contract, but it is a real, load-bearing new public surface worth
  recording as such.
- **Scope limit:** Reverse (`1917`) and Gameplay Rotation's `direction="reverse"`
  only flip the auto-scroll step's sign and the dash-vector's `move_dir` multiplier
  (`core.py:825-831`, `1660-1662`). Camera lead, progress-percentage calculation, the
  finish-wall check, and the bots' left-to-right search heuristics were **not**
  retargeted for backwards play — documented directly in `_apply_reverse_trigger`'s
  docstring (`triggers.py:1477-1489`) as "minimal viable scope." **Real
  reverse-gameplay levels are not fully playable end-to-end** with this checkpoint
  alone; only the player's own motion direction is mechanically correct.
- `channel` field on Gameplay Rotation (default `0`, the report's one hard default) is
  read by nothing — this engine has no gameplay-channel gating concept, documented at
  `triggers.py:1451`.
- Gameplay Rotation's documented Wiki quirk (a non-touch/spawn-triggered Gameplay
  Rotation interfering with camera triggers active from level start) was **found in
  the report and intentionally not reproduced** — recorded directly in a code comment
  (`objects.py:1410-1415`) as "the report describes it as a bug, not a behaviour to
  match."
- `T_CHECKPOINT_TRIGGER` is a genuinely new placeable spec wired into the pre-existing
  `Player.save_checkpoint()`/`load_checkpoint()` plumbing; the older internal
  `T_CHECKPOINT` transient marker is untouched.
- **`bot_runs/f_nine_circles__run_nine_circles.json`** (the one saved bot run in the
  repo) predates the *prior* physics-bible overhaul (April 2026, 60 TPS / pre-retune
  constants) and was already flagged stale in that overhaul's own §16. It remains
  stale here too — **not caused by this Checkpoint-0-8 pass**, but still an open item
  worth carrying forward: the game's existing re-verify-on-load behavior will
  correctly detect the mismatch rather than trust a stale "solved" status, but no
  attempt was made to re-record the run.

### Checkpoint 7 — Environment/UI/Event/End triggers, legacy transitions
- **Change Ground (`3030`) / Change MG (`3031`): stored-only, deliberate no-ops.**
  Both handlers exist (registered in `TRIGGER_HANDLERS` so the table stays pinned to
  cover `TRIGGER_TYPES` exactly rather than silently omitting them) but read nothing —
  `_apply_ground_trigger`/`_apply_mg_trigger` docstrings (`triggers.py:1543-1566`)
  state directly that no ground-palette or middleground-preset table exists anywhere
  in `graphics.py`/`play_render.py`; the ground is drawn from fixed
  `C_GROUND`/`C_GROUND_L`/`C_GROUND_DARK` constants and the middleground from a fixed
  `graphics._MOUNTAIN_SHADES` tuple.
- **BG Speed (`3606`) / MG Speed (`3612`): real**, wired into the parallax rate via
  `Player.bg_scroll_scale()`/`mg_scroll_scale()` (`triggers.py:1589-1597`), consumed
  by `graphics.draw_bg`'s parallax draw. Exact report-cited defaults implemented
  verbatim: BG `0.1`/`0.1`, MG `0.3`/`0.5` (`BG_SPEED_DEFAULT_X/Y`,
  `MG_SPEED_DEFAULT_X/Y`) — a trigger left at defaults changes nothing, matching the
  report's stated identity point.
- **UI Trigger** scoped to a fixed choice list of preset text labels
  (`UI_TEXT_CHOICES`), not free text — the same precedent as Advanced Random's
  fixed-slot weighted-list editor. Reuses the existing Item-Counter HUD render pass
  rather than a new UI layer; camera-anchored, untargeted (no `target_group`) like the
  camera trigger family.
- **Event Trigger** fires from exactly **5 real hook points**, confirmed via
  `_arm_event_triggers`/`_fire_event` (`triggers.py:1648-1668`) and their call sites in
  `core.py`: `EVENT_LEVEL_START` (`core.py:486`), `EVENT_DEATH` (`core.py:949, 1754`),
  `EVENT_WIN` (`core.py:1311`, plus End Trigger's own `_fire_event(EVENT_WIN)` at
  `triggers.py:1707`), `EVENT_CHECKPOINT` (`core.py:614`), `EVENT_RESPAWN`
  (`core.py:659`). Marked `verification="unverified"` — the report gives no further
  field detail for this trigger.
- **End Trigger (`3600`)** is a second, group-targeted activation path into the
  existing `self.won` win flag (`_apply_end_trigger`, `triggers.py:1692-1707`), guarded
  so the win event fires exactly once per attempt regardless of how many End Triggers
  a group holds. The pre-existing `T_END` touch-based finish zone is untouched.
- **Legacy transitions** scoped to level-meta `meta["transition"]`
  (`LEVEL_TRANSITIONS`/`LEVEL_TRANSITION_DEFAULT` in `levels.py`/`play.py`), consumed
  only at level **start** (`play.py:330-331`) — no level-**end** transition was
  implemented, matching the plan's "their whole semantic is how does the level begin"
  scope note. An unknown/legacy value falls back to the default on load
  (`levels.py:318-319`).

### Checkpoint 8 — Explicitly deferred, zero code
`grep -rn "T_OBJECT_CONTROL\|T_LINK_VISIBLE\|T_PERSISTENT_ITEM_SETUP\|object_control\|link_visible\|persistent_item_setup" src/ test_game.py`
returns **no matches** — independently re-confirmed for this addendum. Object Control,
Link Visible, and Persistent Item Setup remain entirely unimplemented, per the
report's own `"unspecified"` table: Object Control ("Wiki says template does nothing
as of 2.2"), Link Visible ("exact field map... unspecified"), Persistent Item Setup
(`3641`, distinct from the already-implemented Item Pers Trigger — unverified object
ID).

## 21. Deferred / best-effort items (report's own `"unspecified"` table + this plan's scope trims)

Carried forward verbatim from the report's own caveats (`deep-research-report.md:585-594`):
- Exact engine-frame latency of every trigger — `"unspecified"`.
- Every field's editor slider min/max — `"unspecified"` unless cited.
- Every field's implicit serialization default — `"unspecified"` unless cited.
- Universal collision/stacking semantics for overlapping transforms — `"unspecified"`.
- Universal rule for two simultaneous duration-based transforms on one object —
  `"unspecified"` beyond known ordering.
- Exact Split Screen serialization fields — `"unspecified"` in the report's own artifact.
- Link Visible / Object Control field maps — `"unspecified"` (Checkpoint 8, zero code).
- Item Persistent's stable public Object ID — `"unspecified"`.
- Every letter block's exact ID mapping — `"unspecified"` where not independently verified.

This plan's own accumulated scope trims:
- Advanced Random's editor UI capped to a fixed 4–8 weighted slots rather than
  generic free-text entry (the engine still parses/stores the report's full
  dot-separated `group.weight...` format up to 20 pairs).
- UI Trigger's fixed-choice-list text scope (no free text).
- Event Trigger's minimal 5-hook-point field set (`event_type`, `target_group`).
- Legacy-transition's level-start-only simplification (no level-end transition).
- The 6 unimplemented shader effects (Gradient, Shock Wave, Shock Line, Glitch,
  Chromatic Glitch, Lens Circle) — need true per-pixel GPU-shader displacement.
- Song Trigger's `speed`/`end` no-ops (no playback-rate control, no scheduled-stop
  primitive).
- SFX Trigger's `pitch`/`reverb` no-ops (no pitch-shift primitive, no DSP stage).
- Change Ground / Change MG stored-only status (no preset tables exist to select
  from).
- Object Control, Link Visible, Persistent Item Setup — zero code (Checkpoint 8).

## 22. Known-unfixable / open items

Inherited from the report's own caveats:
- Trigger Order has no numeric GD key — it is an engine-invented field
  (`_F_TRIGGER_ORDER`, `verification="unverified"`) implementing a report-named
  concept the report never assigns a property key to.
- Force Block's `range`/`min_force`/`max_force` application semantics are a
  best-effort interpretation — the report gives FlowVix's field names/keys
  (`force=149`, `min_force=526`, `max_force=527`, `range=529`, `force_id=530`,
  `relative=528`) but not the exact numeric application rules.
- Gameplay Rotation's documented camera-interaction bug was intentionally **not**
  reproduced.
- F-Block remains deferred — predates this refactor (prior overhaul's §9/§13), still
  true, still unresolved even in the community sources the physics bible cites.

New findings from this pass, not inherited from either prior document:
- **Random/Advanced Random Triggers make bot-search non-deterministic** for any level
  that uses them (Checkpoint 3) — `random.random()` calls with no seed/replay control
  exposed to `src/bots/*`.
- **`Player.move_dir` is a new public-ish attribute** bots now depend on for state
  dedup (Checkpoint 6) — additive, not a removal/rename, so it does not violate the
  stability contract, but it is new load-bearing surface worth recording.
- **Reverse-gameplay levels are only mechanically correct, not fully playable
  end-to-end** (Checkpoint 6) — camera lead, progress percentage, the finish wall, and
  the bots' left-to-right heuristics don't know about reverse direction.
- `bot_runs/f_nine_circles__run_nine_circles.json` is stale from an **earlier**
  physics retune (the prior overhaul's own already-documented staleness, §16 above) —
  unrelated to this pass, but still an open item since it was not re-recorded here
  either.
- Ground/middleground preset tables don't exist in `graphics.py`/`play_render.py`, so
  Change Ground's `ground` field and Change MG's `mg` field are permanently inert
  until someone builds that feature — they round-trip through save/load but nothing
  reads them.

## 23. "MORE RECOMMENDATIONS" — not found

This addendum searched for explicit "not done" / "awaiting approval" / "MORE
RECOMMENDATIONS" / TODO-style markers left in code comments or docstrings by prior
checkpoint agents (`grep -rn "MORE RECOMMENDATIONS\|awaiting approval\|not done\b"` and
a `TODO` grep across `src/player/triggers.py`, `src/player/core.py`, `src/objects.py`,
`src/constants.py`, `src/play_render.py`). **No matches were found.** Per this task's
own instruction, no recommendations are fabricated here — this sub-item is skipped
rather than invented.

## 24. A note on verifying this addendum

Every specific code-location claim above (line numbers, field names, docstring
wording) was re-derived directly from the current working tree via `grep`/`Read` for
this addendum, rather than transcribed from the task's own summary of what landed —
per this project's established practice (§9's "Process note" above, about a prior
fork's false report), a couple of items in the original task description were
softened or corrected on that basis:
- The "P1 bug fix in `sprites.draw_obj`" claim (Checkpoint 2) could not be
  independently verified as a *discovered-and-fixed* defect from current code/history
  — the tint parameter itself is real and wired, but no comment or history evidence
  ties it to a specific pre-existing rendering bug, so §20's Checkpoint 2 entry
  reports this honestly rather than asserting a bug that wasn't confirmed.
- The "MORE RECOMMENDATIONS" sub-item (§23) turned up no markers at all, so it is
  reported as empty rather than reconstructed from guesswork.
Everything else in §18–22 — object IDs, field names, defaults, docstring quotes, file
paths, and line numbers — was confirmed against the current tree at the time of
writing.

## 25. Verification performed for this addendum

- Full `.venv/bin/python test_game.py`: **844 passed, 0 failed** (baseline before
  Checkpoint 0 was 504, per §15 above).
- `git status`/`git diff --stat` confirm this addendum touched only
  `docs/development/AUDIT.md`; the `.py` files shown as modified in the working tree
  (`src/bot_menu.py`, `src/bots/*.py`, `src/constants.py`, `src/editor/render.py`,
  `src/geometry.py`, `src/graphics.py`, `src/levels.py`, `src/music.py`,
  `src/objects.py`, `src/play.py`, `src/play_render.py`, `src/player/core.py`,
  `src/player/triggers.py`, `src/sfx.py`, `src/sprites.py`, `test_game.py`) are
  Checkpoints 0–8's own pre-existing uncommitted work from before this documentation
  pass started, not changes made while writing this addendum.
- `grep`-reconfirmed Checkpoint 8's zero-code claim directly (§20).
- `grep`-reconfirmed the `gd_object_id`/`verification` counts cited in §18/§20 directly
  against the current `src/objects.py`.
