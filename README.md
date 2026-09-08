# Trigonometry Sprint

A Geometry Dash style rhythm platformer in Python + pygame-ce, with a
GD-style level editor and several auto-play bots.

## Run

```
python -m venv .venv
.venv/bin/pip install pygame-ce
.venv/bin/python main.py
```

Tests (headless movement contracts and game/editor/bot regressions):

```
.venv/bin/python test_game.py
.venv/bin/python -m unittest test_physics
```

## Layout

| Path | Purpose |
|---|---|
| `main.py` | Menu state machine |
| `src/play.py`, `src/play_render.py` | `PlaySession`: fixed 240 Hz physics, interpolated rendering |
| `src/player/` | Player physics (`core`, `collision`, `triggers`, `body`, `draw`) |
| `src/objects.py` | Object registry: one `ObjectSpec` per type drives palette, tooltips, property panel and save/load |
| `src/editor/` | Level editor (`session`, `ui`, `ops`, `props`, `render`, `state`, `dialogs`) |
| `src/geometry.py`, `src/sprites.py`, `src/graphics.py` | Hitbox maths, sprite baking, screen drawing |
| `src/levels.py` | Level files and format migrations |
| `src/bots/` (`human.py`, `loophole.py` + shared sim/search), `src/bot_menu.py` | Bots |
| `docs/` | Physics guide, development notes, and research references |
| `tests/fixtures/` | Sample input data used by regression tests |
| `reports/benchmarks/` | Local benchmark reports and logs |

## Editor

Press `F1` inside the editor for the full shortcut sheet.

- **Build / Edit / Delete** tabs on the bottom bar (`B` / `I` / `E`).
- Build: category tabs, `1`–`9` pick an object, `R`/`Q` rotate the brush, drag to paint, right-click to erase.
- Edit: click / marquee / Shift-click to select, drag to move, Rotate toggle for drag-rotate, toolbar for rotate / flip / scale / copy / paste / duplicate / nudge, `Edit Object` opens the property panel, `Link` wires teleports and triggers, `Bot Path` draws a path for `K`.
- Delete: click or swipe, optional filter to the current object type.
- `T` test, `Shift+T` test from cursor, `K` bot, `L` bot menu, `S` save, `Ctrl+Z`/`Ctrl+Y` undo/redo, wheel zooms on the cursor.

See the [documentation index](docs/README.md), [physics guide](docs/PHYSICS.md),
and [development audit](docs/development/AUDIT.md).
