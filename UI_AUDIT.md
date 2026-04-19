# UI Audit — Geometry Dash Temu

I ran the game headlessly (`SDL_VIDEODRIVER=dummy`) and grabbed a PNG of every
menu, dialog and HUD. This doc walks screen-by-screen, flags every overlap,
overflow, misalignment, or sizing problem I could see, and proposes a concrete
fix for each one. Screens are numbered the same as the files in
`ui_shots/`.

Root causes keep repeating, so before the per-screen list here are the
**three systemic bugs** that together explain most of what's wrong:

1. **Help text lives outside the panel.** Almost every dialog draws its
   keyboard-hint footer (e.g. `Esc: back · Enter: confirm`) at a *fixed screen
   Y* (roughly `HEIGHT - 20`), which sits just below, on top of, or clipping
   through the panel's bottom border depending on how tall the panel ended
   up. The right fix is to anchor the footer to the **panel's bottom rect**
   — either *inside* the panel (a few px above the border) or *clearly
   outside* (>= 12 px below the border). Pick one rule and apply it
   everywhere.
2. **Panel sizing is hard-coded, content is variable.** Several panels
   (settings, music, snippet picker, bot menu) have a fixed `w,h` but the
   widgets inside are sized off the widest row / longest list, so content
   either gets cut off (snippet picker) or the panel has enormous dead
   vertical space (bot menu, load level). Panels should measure their
   content and size to fit, with a min/max clamp.
3. **Top-bar "speaker" widgets move.** The SFX / MUS quick-mute buttons
   live in the **top-right** on the main menu but in the **top-left** on
   Select-Level. Pick one corner and use it for every screen so muscle
   memory works.

Once those three are fixed, you'll have resolved roughly 60% of the
per-screen issues listed below. The rest are one-offs.

---

## 01 — Main menu

**What's wrong**

- The **SFX / MUS labels under the two speaker icons** (top-right) are
  clipped — the text is rendered with the baseline sitting at the very edge
  of the icon, so "SFX" and "MUS" read as half-height letters. At the
  screen resolution it looks like "5FX / MU5".
- A decorative **falling-cube** sprite in the background passes directly
  *over* the PLAY button mid-animation, which is visually noisy — the
  background squares should render *behind* the menu stack, not on top.
- "GEOMETRY DASH" title has no drop-shadow / outline, so the bright green
  fights the starfield for legibility on certain frames.

**Fixes**

- Move the icon-label text to the *left of the icon*, horizontally
  aligned and vertically centred: `label_rect.right = icon.left - 6;
  label_rect.centery = icon.centery`. Frees both the clipping and the
  stacked look.
- Render background decoration first, then dim-overlay at ~30% alpha,
  *then* draw buttons. The dim-overlay already exists for some menus —
  just apply it here too.
- Draw the title with a 2px black outline + 1px vertical offset soft
  shadow. Utility already exists in `graphics.py` (`draw_text_glow`
  from the neon suggestion in `installation_and_ui.md`).

---

## 02 — Level select

**What's wrong**

- **SFX / MUS speakers are in the top-LEFT here**, but the main menu puts
  them in the top-RIGHT. Classic menu-drift bug.
- The `3 levels` count label sits directly below the speakers, so on a
  cramped screen it gets visually tangled with the icons.
- `Filter: All` button hugs the right edge — no matching element on the
  left aside from the counter, so the header looks unbalanced.

**Fixes**

- Pick one corner for the mute widget and apply it everywhere. Top-right
  is more conventional; move it there on this screen.
- Move the `N levels` counter under the SELECT LEVEL title (centred),
  so the top-left becomes free real estate.
- Consider swapping `Filter: All` for a search box on the left and a
  filter dropdown on the right — but that's a nice-to-have, not a bug.

---

## 03 — Settings panel  **(multiple overflows)**

**What's wrong**

- The **Music / SFX volume sliders extend past the right border of the
  panel**, and the `49%` / `45%` labels sit *outside* the panel entirely.
  The slider track looks like it was sized for the full screen but the
  panel got narrowed.
- **"Gamepad: not detected"** and **"Esc: back · Drag sliders to adjust"**
  are drawn *below the panel*, not inside it. On a dark background these
  lines float in dead space — if the panel ever moves / resizes they'll
  look detached.
- The **Reset-to-defaults** button uses brown, which doesn't match the
  rest of the palette (every other destructive-ish action is red, every
  other secondary is gray/blue).

**Fixes**

- Clamp slider width: `slider_w = panel_rect.width - label_w - 48`, and
  place the percent label **inside** the panel to the slider's right
  (`label.right = panel_rect.right - 16`).
- Pull the footer text **inside the panel**: add 28 px to the panel
  height for a footer strip, then draw the hint + gamepad-status lines
  at `panel_rect.bottom - 24` and `-10`. Alternatively hide "Gamepad:
  not detected" entirely when there's no controller — it's noise when
  there is no controller to plug in.
- Re-colour Reset to a neutral gray (`SOFT_GRAY`). The red BACK already
  anchors the row visually.

---

## 04 — Customize

**What's wrong**

- "Click a tile to select · Arrows: cycle · Esc: back" help line sits
  *outside* the panel (below the bottom border).
- Preview cube is quite large; Icon row (8 tiles) and Color row (8 tiles)
  are visually tight next to that preview but fine.

**Fixes**

- Pull help text inside the panel (see systemic fix #1).
- Optional: split the panel into a left column (preview + name) and
  right column (Icon / Color rows) so the preview doesn't eat half the
  vertical space.

---

## 05 — Music menu

**What's wrong**

- **"Space: play/stop · M: mute · Esc: back"** help text sits directly
  on top of the panel's bottom border — the text and the blue rounded-rect
  outline intersect.
- **"+ Add music from file…"** button is inside the panel but only ~4 px
  above the bottom border — it looks crammed.
- The "Music volume" row and the button row are both glued to the
  bottom half with a big empty gap above — panel is taller than its
  content needs.

**Fixes**

- Size the panel to fit: `panel.height = header_h + list_h + controls_h
  + footer_h + 3*padding`. Put help text inside the footer strip.
- Move "+ Add music from file…" into its own row *above* the Back / Stop
  / Prev / Next row, with 12 px of margin on each side.
- Shrink the vertical gap between the list and the volume slider.

---

## 06 — Confirm dialog

**What's wrong**

- "Enter/Y: yes · Esc/N: no" help text **overlaps the blue bottom
  border** of the dialog (sits exactly on the line).
- Lots of empty vertical space between "This cannot be undone." and the
  OK / Cancel buttons.

**Fixes**

- Same systemic footer-anchor fix.
- Reduce dialog height by ~40 px so subtitle → buttons feels like one
  cohesive block. A modal should always feel compact.

---

## 07 — Text input dialog

No layout issues — this one is fine. Hint text is inside the panel,
input field is correctly sized. Leave it alone.

**Minor polish suggestion:** make the caret blink (looks dead in the
screenshot), and highlight the default text so typing replaces it
(currently you'd have to clear it by hand).

---

## 08 — Difficulty picker  **(bad overlaps)**

**What's wrong**

- "Enter: confirm · Esc: cancel" hint text **sits on top of the bottom
  blue border** — reads as garbled because the border cuts the letters.
- Button grid is **asymmetric**: row 1 has 4 buttons (Auto, Easy,
  Normal, Hard), row 2 has 3 (Harder, Insane, Demon). Looks unbalanced.
- Labels like "Harder" and "Insane" barely fit inside their button
  widths — the text nearly touches both rounded corners.

**Fixes**

- Anchor help text inside the panel (systemic fix #1).
- Make the grid 4×2 with an explicit empty slot (or better, add a
  "Cancel" tile in slot 8 styled as subdued gray, so the pad is full).
  Or use a 7×1 row if the window is wide enough.
- Pad each button by at least `font_height/2` on the horizontal axis:
  `btn_w = max(MIN_W, text_w + 24)`.

---

## 09 — Load level dialog

**What's wrong**

- The **tiny "o" / circle glyph on the right side of every row** (what I
  assume is the delete affordance) is roughly 10 px across — effectively
  un-clickable with a mouse and invisible at a glance.
- The dialog reserves space for ~10 rows but shows 3 — enormous empty
  middle region.
- No indication that rows are clickable (no hover state visible in the
  snapshot — though that may just be headless capture).

**Fixes**

- Replace the tiny glyph with a **proper trash-can icon button** (22×22
  px), right-aligned with 12 px of padding. Use `hazard_red` on hover,
  gray when inactive.
- Size dialog height to `header + N_rows*row_h + footer`, with a hard
  max (e.g. 7 rows visible, scroll beyond that). Stop reserving empty
  space.
- Add a faint row hover rect (`(255,255,255, 24)` alpha fill).

---

## 10 — Snippet picker  **(content cut off)**

**What's wrong**

- The panel shows 6 full snippets (Spike Trio through Jump Pad Combo)
  and a **7th row peeking up above the "Esc: cancel" footer** — clearly
  cut off. The user can't see what the 7th option is.
- Scroll affordance ("Scroll to browse") is in the footer, but it's not
  obvious that there's more content because the partial row *looks*
  like a clipping bug, not intentional.

**Fixes**

- Make the list area end on a whole-row boundary:
  `visible_rows = (list_height - header_h - footer_h) // row_h`
  then `list_height = header_h + visible_rows*row_h + footer_h`.
  No half-rows.
- Add a small **scroll indicator on the right** (a thin faded bar
  showing current position) — tells the user there's more below.

---

## 11 — Editor  **(the worst offender)**

**What's wrong**

- The keyboard-hints strip above the bottom button row is **completely
  squished together**: `Tab:tabs 1-9:pick B/E/N/I:tools F2:snippets
  K:bot L:auto T:test ^L:load ^Z/Y:undo H:hitboxes` renders with no
  spaces between commands because it's drawn at too-small a font for
  the available width. It reads like a hash.
- **Save / Publish / Load / Test / Bot** — the labels of these bottom
  buttons overlap each other's edges. "Publish[S]" bleeds into
  "Load[^L]", etc.
- The two **speaker icons floating in the bottom centre** (between
  Menu and the stats readout) have no panel / frame around them and
  look accidentally placed.
- **"Block"** label + **"Rot 0°"** label at top-left are free-floating
  text on the level background — no contrast strip, so they disappear
  when the camera moves over a dark region.
- Object palette (row of variant tiles below the tab bar) shows 2 tiles
  but they're scrunched in a tiny left-hand corner.
- **Tab strip** (Solid / Hazards / Interact / Portals / Speed / Deco /
  Triggers / Misc) is fine, but "Solid" tab is highlighted with a
  square shape that doesn't match the other pills — clean that up.

**Fixes**

- **Bottom hints strip:** split into two lines, or put the entire hints
  block behind a `?` icon that shows a modal keyboard cheat sheet.
  Trying to cram 9 shortcut groups on one line at any reasonable font
  size was never going to work.
- **Bottom buttons:** give each button a fixed minimum width
  (`btn_w = max(text_w + 28, 88)`) and a uniform gap (`gap = 10`).
  If that overflows the window, wrap into a right-side toolbar instead.
- **Bottom speakers:** group them with the M/S mute indicator into a
  mini panel, or just move them into the Menu overlay. Having them
  floating mid-bar is odd.
- **"Block" / "Rot" indicators:** wrap both in a small dark pill
  background `Surface((120, 22), pygame.SRCALPHA)` with `(0,0,0,160)`
  fill, then draw the text on top. This also makes them readable no
  matter what's underneath.
- **Palette row:** expand to use the full top strip width. Currently
  you're only using ~10% of the horizontal space.

---

## 12 — Play HUD

**What's wrong**

- The **progress bar at top-left overlaps the big yellow coin / star
  icon** — the "Attempt 1" and "Time 0:00.05" text is drawn under the
  icon, which occludes them entirely.
- The progress bar itself is quite short (looks like 140 px) — the
  `7%` is correct, but visually you can't see micro-progress.
- `Cube · 5.0x` top-right is fine.

**Fixes**

- Move the Attempt/Time block to **below the progress bar**, not
  beside the coin icon. Or shrink the coin indicator substantially
  — currently it's ~64×64 covering two lines of text.
- Make the progress bar stretch across 60% of the screen width,
  centred at the top, like canonical GD. The coin counter can sit to
  its right.
- Consider a **thin % tick** every 10% to give the bar structure.

---

## 13 — Bot menu

**What's wrong**

- "BACK" button sits flush against the panel's bottom border, and the
  **"Enter: solve · Esc: back"** help text is clearly drawn **outside**
  the panel (below the border).
- The middle of the panel has a big **empty region** between the "No
  path computed yet." line and the Find-Path button cluster. Dead space.
- "Use as Hint Overlay" button is noticeably darker green than "Find
  Path (Solve)" — looks disabled even though it isn't.

**Fixes**

- Pull help text inside the panel (systemic fix #1). Reduce panel
  height by ~50 px.
- Either collapse the empty space or put "No path computed yet."
  directly above the buttons (4px margin) and make the status line
  grow into a progress/log readout once solving starts — it's a
  natural place for solver output (`nodes=…`, `depth=…`, `elapsed=…`).
- Use the same green tone as Find Path for Use-as-Hint, or change it
  to a secondary blue. "Save run" and "Load run" can stay green.

---

## Cross-cutting polish

These aren't per-screen bugs but they'll visibly lift the whole UI once
the specific issues above are fixed:

- **Consistent focus ring.** Whatever button / tile is "currently
  selected" should have a 2-px cyan outline at `(120, 200, 255)`. The
  customize screen has this, the other menus don't. Add it.
- **Hover states.** Almost nothing changes on hover in the screenshots.
  A 5% lighten (`lerp(color, WHITE, 0.08)`) is enough.
- **Font hierarchy.** There are at least 4 distinct font sizes in use
  (title, header, body, hint). Normalise to three: 48/32/18, and have
  the shared `ui.py` helpers only accept those three via enum.
- **Footer template.** Write one function `draw_panel_footer(surf,
  panel_rect, text)` that draws hint text at `panel_rect.bottom - 18`,
  centred. Replace the ad-hoc code in every menu. This single helper
  eliminates bugs 1/3/4/5/6/8/13 above.
- **Dead keys.** Some dialogs describe shortcuts (`Enter/Y`, `Esc/N`)
  but the keyboard handler in `menus.py` may not actually handle `Y`
  and `N` — spot-check that the documented shortcuts really work.

---

## Suggested fix order

If you want a ruthlessly prioritised list:

1. **Write `draw_panel_footer()` + `size_panel_to_fit()` helpers** and
   replace all ad-hoc footer drawing (~30 min, fixes ~7 bugs at once).
2. **Editor bottom bar overhaul** — split hints onto two lines, size
   buttons uniformly. This is the highest-impact visual fix.
3. **Settings slider overflow** — clamp slider width, move percent
   inside panel. Trivial, looks awful as-is.
4. **Snippet picker whole-row clipping** — `visible_rows = floor(...)`.
5. **Play-HUD: stop coin icon from covering Attempt/Time.**
6. **Speaker widget position consistency** (main menu vs level select).
7. **Difficulty-picker grid symmetry + button width clamp.**
8. **Load-level delete button** — real icon at 22 px.
9. Nice-to-haves: focus ring, hover states, typography normalisation.

Total rough effort: 4–6 hours of focused work gets you through items
1–6; items 7–9 plus the cross-cutting polish is another afternoon.
