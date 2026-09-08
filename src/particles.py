import math
import random

import pygame

# Checkpoint 3 tick-rate migration (60 -> 240 TPS): ``update()`` runs once
# per physics tick (see play.PlaySession._tick), so every per-tick value
# below is rescaled to preserve the same real-world speed/duration at the
# new rate, exactly like the rest of the tick-rate migration:
#   - velocities (px/tick)              -> old / 4   (real px/sec const.)
#   - accelerations (px/tick^2)         -> old / 16  (real px/sec^2 const.,
#                                          same TPS^2 rule as GRAVITY in
#                                          constants.py)
#   - exponential decay coefficients    -> old ** (1/4)
#   - life counters (ticks-until-death) -> old * 4   (real seconds const.)
# ``draw()``'s life-dependent size/alpha divisors are adjusted to match
# since life values now run ~4x higher.
_TICK_SCALE = 4.0  # PHYSICS_TPS(240) / old 60


class Particles:
    def __init__(self):
        self.ps = []
        self.rings = []

    def burst(self, x, y, col, n=25, speed=7.0 / _TICK_SCALE):
        for _ in range(n):
            self.ps.append([
                x, y,
                random.uniform(-speed, speed),
                random.uniform(-speed, speed * 0.3),
                random.randint(72, 136),   # 18-34 ticks * 4
                random.randint(3, 8),
                col,
            ])

    def explosion(self, x, y, col):
        for _ in range(55):
            ang = random.uniform(0, math.tau)
            spd = random.uniform(2.5, 10.0) / _TICK_SCALE
            self.ps.append([
                x, y,
                math.cos(ang) * spd,
                math.sin(ang) * spd - 2.5 / _TICK_SCALE,
                random.randint(80, 168),  # 20-42 ticks * 4
                random.randint(3, 9),
                random.choice([col, (255, 255, 255), (255, 220, 120), (255, 140, 80)]),
            ])
        self.rings.append([x, y, 6.0, 90.0, col, 104])          # 26 * 4
        self.rings.append([x, y, 2.0, 60.0, (255, 255, 255), 80])  # 20 * 4

    def trail(self, x, y, col):
        self.ps.append([
            x, y,
            random.uniform(-1.0, 1.0) / _TICK_SCALE,
            random.uniform(-1.0, 1.0) / _TICK_SCALE,
            random.randint(40, 80),   # 10-20 ticks * 4
            random.randint(2, 5),
            col,
        ])

    def dash_trail(self, x, y, vx, vy, col):
        """Exhaust puff for a player riding a directional dash orb.

        Particles stream OPPOSITE to the dash direction so the trail
        reads as motion exhaust, not an explosion. Spawn radius and
        particle size are larger than Particles.trail() so the effect
        stays visible at dash speeds (the player is moving ~5 px/frame
        at 240 TPS, so short-lived particles would barely register).
        """
        mag = (vx * vx + vy * vy) ** 0.5
        if mag < 0.1 / _TICK_SCALE:
            return
        back_x = -vx / mag
        back_y = -vy / mag
        spd = max(2.5 / _TICK_SCALE, mag * 0.35)
        for _ in range(3):
            spread = random.uniform(-0.7, 0.7)
            # Rotate the back-vector by `spread` radians for a fan.
            cs = math.cos(spread)
            sn = math.sin(spread)
            dx = back_x * cs - back_y * sn
            dy = back_x * sn + back_y * cs
            jitter = random.uniform(0.6, 1.1)
            self.ps.append([
                x + random.uniform(-3, 3),
                y + random.uniform(-3, 3),
                dx * spd * jitter,
                dy * spd * jitter,
                random.randint(64, 104),  # 16-26 ticks * 4
                random.randint(4, 7),
                col,
            ])

    def update(self):
        alive = []
        for p in self.ps:
            p[0] += p[2]
            p[1] += p[3]
            p[3] += 0.25 / (_TICK_SCALE ** 2)     # 0.0625 * 0.25 = 0.015625
            p[2] *= 0.9949620564                  # 0.98 ** (1/4)
            p[4] -= 1
            if p[4] > 0:
                alive.append(p)
        self.ps = alive
        alive_rings = []
        for r in self.rings:
            r[2] += r[3] * (0.04 / _TICK_SCALE)   # 0.01
            r[5] -= 1
            if r[5] > 0:
                alive_rings.append(r)
        self.rings = alive_rings

    def draw(self, surf, cam_x=0, cam_y=0):
        for p in self.ps:
            sz = max(1, int(p[5] * p[4] / (30 * _TICK_SCALE)))
            pygame.draw.rect(surf, p[6], (int(p[0] - cam_x), int(p[1] - cam_y), sz, sz))
        for rx, ry, r, _mr, col, life in self.rings:
            alpha = max(0, min(255, int(life * (10 / _TICK_SCALE))))
            ring = pygame.Surface((int(r * 2 + 8), int(r * 2 + 8)), pygame.SRCALPHA)
            pygame.draw.circle(ring, (*col, alpha), (int(r + 4), int(r + 4)), int(r), 3)
            surf.blit(ring, (int(rx - cam_x - r - 4), int(ry - cam_y - r - 4)))
