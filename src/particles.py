import math
import random

import pygame


class Particles:
    def __init__(self):
        self.ps = []
        self.rings = []

    def burst(self, x, y, col, n=25, speed=7.0):
        for _ in range(n):
            self.ps.append([
                x, y,
                random.uniform(-speed, speed),
                random.uniform(-speed, speed * 0.3),
                random.randint(18, 34),
                random.randint(3, 8),
                col,
            ])

    def explosion(self, x, y, col):
        for _ in range(55):
            ang = random.uniform(0, math.tau)
            spd = random.uniform(2.5, 10.0)
            self.ps.append([
                x, y,
                math.cos(ang) * spd,
                math.sin(ang) * spd - 2.5,
                random.randint(20, 42),
                random.randint(3, 9),
                random.choice([col, (255, 255, 255), (255, 220, 120), (255, 140, 80)]),
            ])
        self.rings.append([x, y, 6.0, 90.0, col, 26])
        self.rings.append([x, y, 2.0, 60.0, (255, 255, 255), 20])

    def trail(self, x, y, col):
        self.ps.append([
            x, y,
            random.uniform(-1.0, 1.0),
            random.uniform(-1.0, 1.0),
            random.randint(10, 20),
            random.randint(2, 5),
            col,
        ])

    def update(self):
        alive = []
        for p in self.ps:
            p[0] += p[2]
            p[1] += p[3]
            p[3] += 0.25
            p[2] *= 0.98
            p[4] -= 1
            if p[4] > 0:
                alive.append(p)
        self.ps = alive
        alive_rings = []
        for r in self.rings:
            r[2] += r[3] * 0.04
            r[5] -= 1
            if r[5] > 0:
                alive_rings.append(r)
        self.rings = alive_rings

    def draw(self, surf, cam_x=0, cam_y=0):
        for p in self.ps:
            sz = max(1, int(p[5] * p[4] / 30))
            pygame.draw.rect(surf, p[6], (int(p[0] - cam_x), int(p[1] - cam_y), sz, sz))
        for rx, ry, r, _mr, col, life in self.rings:
            alpha = max(0, min(255, int(life * 10)))
            ring = pygame.Surface((int(r * 2 + 8), int(r * 2 + 8)), pygame.SRCALPHA)
            pygame.draw.circle(ring, (*col, alpha), (int(r + 4), int(r + 4)), int(r), 3)
            surf.blit(ring, (int(rx - cam_x - r - 4), int(ry - cam_y - r - 4)))
