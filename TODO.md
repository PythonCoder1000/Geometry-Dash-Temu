# TODO

- [ ] Gravity-flip icon bug: when gravity is switched (gravity portals, black/blue
  orbs, etc.), the on-screen icon(s) don't flip to match the new gravity
  direction. Likely in `src/player/draw.py` / `src/sprites.py` — the sprite
  orientation probably isn't keyed off `body.grav`.
