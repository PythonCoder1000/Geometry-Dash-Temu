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
