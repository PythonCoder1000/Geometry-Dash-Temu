# Trigonometry Sprint

A Geometry Dash style rhythm platformer in Python + pygame-ce, with a
GD-style level editor and several auto-play bots.

## Run

```
python -m venv .venv
.venv/bin/pip install pygame-ce
.venv/bin/python main.py
```

Tests (custom check script, replays golden playthroughs and flags physics drift):

```
.venv/bin/python test_game.py
```

## Layout

| Path | Purpose |
|---|---|
| `main.py` | Menu state machine |
| `src/play.py`, `src/play_render.py` | `PlaySession`: fixed 60 Hz physics, interpolated rendering |
| `src/player/` | Player physics (`core`, `collision`, `triggers`, `body`, `draw`) |
| `src/objects.py` | Object registry: one `ObjectSpec` per type drives palette, tooltips, property panel and save/load |
| `src/editor/` | Level editor (`session`, `ui`, `ops`, `props`, `render`, `state`, `dialogs`) |
| `src/geometry.py`, `src/sprites.py`, `src/graphics.py` | Hitbox maths, sprite baking, screen drawing |
| `src/levels.py` | Level files and format migrations |
| `src/autobot.py`, `src/bot.py`, `src/y_bot.py`, `src/bot_menu.py` | Bots |

## Editor

Press `F1` inside the editor for the full shortcut sheet.

- **Build / Edit / Delete** tabs on the bottom bar (`B` / `I` / `E`).
- Build: category tabs, `1`–`9` pick an object, `R`/`Q` rotate the brush, drag to paint, right-click to erase.
- Edit: click / marquee / Shift-click to select, drag to move, Rotate toggle for drag-rotate, toolbar for rotate / flip / scale / copy / paste / duplicate / nudge, `Edit Object` opens the property panel, `Link` wires teleports and triggers, `Bot Path` draws a path for `K`.
- Delete: click or swipe, optional filter to the current object type.
- `T` test, `Shift+T` test from cursor, `K` bot, `L` bot menu, `S` save, `Ctrl+Z`/`Ctrl+Y` undo/redo, wheel zooms on the cursor.

See `AUDIT.md` for the change log, known issues and deferred ideas.
