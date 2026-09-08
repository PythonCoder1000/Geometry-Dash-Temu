# TODO

- [x] Gravity-flip icon bug: when gravity is switched (gravity portals, black/blue
  orbs, etc.), the on-screen icon(s) don't flip to match the new gravity
  direction. Fixed in `src/player/draw.py` — sprite draw now flips vertically
  when `grav == -1` for both the main body and the mirror body (mirror
  previously always flipped unconditionally).
