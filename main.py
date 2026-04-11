#!/usr/bin/env python3

import pygame
import json
import os
import math
import sys
import random

WIDTH, HEIGHT = 1200, 700
CELL = 50
FPS = 60

PLAYER_SIZE = 44
BASE_MOVE_SPEED = 5.0
GRAVITY = 1.0
SHIP_GRAVITY = 0.72
SHIP_THRUST = 1.22
JUMP_FORCE = -16.0
PAD_FORCE = -18.0
BALL_FLIP_FORCE = 10.0
DASH_SPEED = 16.0
DASH_TIME = 9
PLAYER_START_GX = 3

LEVELS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "levels")

T_BLOCK = "block"
T_SPIKE = "spike"
T_HALF_SPIKE = "half_spike"
T_ORB = "orb"
T_DASH_ORB = "dash_orb"
T_PAD = "pad"
T_GRAV = "grav"
T_END = "end"
T_MODE_CUBE = "mode_cube"
T_MODE_SHIP = "mode_ship"
T_MODE_BALL = "mode_ball"
T_SPEED_SLOW = "speed_slow"
T_SPEED_NORMAL = "speed_normal"
T_SPEED_FAST = "speed_fast"
T_SPEED_FASTER = "speed_faster"
T_START = "start"

ALL_TYPES = [
    T_BLOCK,
    T_SPIKE,
    T_HALF_SPIKE,
    T_ORB,
    T_DASH_ORB,
    T_PAD,
    T_GRAV,
    T_END,
    T_MODE_CUBE,
    T_MODE_SHIP,
    T_MODE_BALL,
    T_SPEED_SLOW,
    T_SPEED_NORMAL,
    T_SPEED_FAST,
    T_SPEED_FASTER,
    T_START,
]

TYPE_NAMES = {
    T_BLOCK: "Block",
    T_SPIKE: "Spike",
    T_HALF_SPIKE: "Half Spike",
    T_ORB: "Orb",
    T_DASH_ORB: "Dash Orb",
    T_PAD: "Pad",
    T_GRAV: "Gravity",
    T_END: "Finish",
    T_MODE_CUBE: "Cube Portal",
    T_MODE_SHIP: "Ship Portal",
    T_MODE_BALL: "Ball Portal",
    T_SPEED_SLOW: "0.8x Speed",
    T_SPEED_NORMAL: "1.0x Speed",
    T_SPEED_FAST: "1.35x Speed",
    T_SPEED_FASTER: "1.65x Speed",
    T_START: "Start Pos",
}

C_BG = (10, 5, 35)
C_GROUND = (0, 25, 80)
C_GROUND_L = (0, 70, 160)
C_GRID = (30, 25, 55)
C_WHITE = (255, 255, 255)
C_GRAY = (130, 130, 140)
C_DARK = (35, 35, 55)
C_PLAYER = (80, 255, 80)
C_BLOCK = (0, 100, 230)
C_BLOCK_H = (50, 150, 255)
C_SPIKE = (255, 50, 50)
C_ORB = (255, 255, 50)
C_DASH_ORB = (255, 80, 220)
C_PAD = (255, 165, 0)
C_GPORTAL = (0, 230, 210)
C_END = (80, 255, 100)
C_BTN = (40, 75, 170)
C_BTN_H = (60, 100, 210)
C_DANGER = (190, 50, 50)
C_MODE_CUBE = (90, 220, 255)
C_MODE_SHIP = (255, 120, 80)
C_MODE_BALL = (180, 120, 255)
C_SPEED_SLOW = (100, 255, 160)
C_SPEED_NORMAL = (100, 180, 255)
C_SPEED_FAST = (255, 220, 90)
C_SPEED_FASTER = (255, 110, 110)
C_START = (255, 255, 255)

TYPE_COLS = {
    T_BLOCK: C_BLOCK,
    T_SPIKE: C_SPIKE,
    T_HALF_SPIKE: (255, 90, 90),
    T_ORB: C_ORB,
    T_DASH_ORB: C_DASH_ORB,
    T_PAD: C_PAD,
    T_GRAV: C_GPORTAL,
    T_END: C_END,
    T_MODE_CUBE: C_MODE_CUBE,
    T_MODE_SHIP: C_MODE_SHIP,
    T_MODE_BALL: C_MODE_BALL,
    T_SPEED_SLOW: C_SPEED_SLOW,
    T_SPEED_NORMAL: C_SPEED_NORMAL,
    T_SPEED_FAST: C_SPEED_FAST,
    T_SPEED_FASTER: C_SPEED_FASTER,
    T_START: C_START,
}

GROUND_Y = 550

SPEED_VALUES = {
    T_SPEED_SLOW: 4.0,
    T_SPEED_NORMAL: 5.0,
    T_SPEED_FAST: 6.7,
    T_SPEED_FASTER: 8.4,
}

MODE_CUBE = "cube"
MODE_SHIP = "ship"
MODE_BALL = "ball"

MODE_FROM_TYPE = {
    T_MODE_CUBE: MODE_CUBE,
    T_MODE_SHIP: MODE_SHIP,
    T_MODE_BALL: MODE_BALL,
}

_fonts = {}


def get_font(size):
    if size not in _fonts:
        _fonts[size] = pygame.font.SysFont("arial", size, bold=True)
    return _fonts[size]


def lighter(c, a=50):
    return tuple(min(255, v + a) for v in c)


def darker(c, a=50):
    return tuple(max(0, v - a) for v in c)


def txt(surf, text, x, y, size=22, col=C_WHITE, center=False):
    s = get_font(size).render(str(text), True, col)
    r = s.get_rect(center=(x, y)) if center else s.get_rect(topleft=(x, y))
    surf.blit(s, r)
    return r


def btn(surf, label, cx, cy, w=180, h=46, col=C_BTN, mpos=None):
    r = pygame.Rect(cx - w // 2, cy - h // 2, w, h)
    c = lighter(col, 25) if mpos and r.collidepoint(mpos) else col
    pygame.draw.rect(surf, c, r, border_radius=8)
    pygame.draw.rect(surf, lighter(c, 40), r, 2, border_radius=8)
    txt(surf, label, cx, cy, 20, C_WHITE, True)
    return r


def make_rect(cx, cy, w, h):
    return pygame.Rect(cx - w // 2, cy - h // 2, w, h)


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def normalize_rotation(r):
    return int(round(r / 90.0) * 90) % 360


def cell_rect(gx, gy):
    return pygame.Rect(gx * CELL, gy * CELL, CELL, CELL)


def rotate_local_rect(local_rect, rotation, size=CELL):
    rot = normalize_rotation(rotation)
    if rot == 0:
        return pygame.Rect(local_rect)
    cx = size / 2.0
    cy = size / 2.0
    points = [
        (local_rect.left, local_rect.top),
        (local_rect.right, local_rect.top),
        (local_rect.right, local_rect.bottom),
        (local_rect.left, local_rect.bottom),
    ]
    rotated = []
    for px, py in points:
        dx = px - cx
        dy = py - cy
        if rot == 90:
            rdx, rdy = -dy, dx
        elif rot == 180:
            rdx, rdy = -dx, -dy
        else:
            rdx, rdy = dy, -dx
        rotated.append((cx + rdx, cy + rdy))
    min_x = min(p[0] for p in rotated)
    max_x = max(p[0] for p in rotated)
    min_y = min(p[1] for p in rotated)
    max_y = max(p[1] for p in rotated)
    return pygame.Rect(round(min_x), round(min_y), round(max_x - min_x), round(max_y - min_y))


def spike_hitboxes(gx, gy, rotation=0, half=False):
    if half:
        base = [
            pygame.Rect(14, 34, 22, 8),
            pygame.Rect(18, 28, 14, 6),
        ]
    else:
        base = [
            pygame.Rect(14, 34, 22, 8),
            pygame.Rect(18, 24, 14, 10),
        ]
    x = gx * CELL
    y = gy * CELL
    boxes = []
    for rect in base:
        rr = rotate_local_rect(rect, rotation)
        boxes.append(rr.move(x, y))
    return boxes


def pad_trigger_rect(gx, gy, rotation=0):
    base = pygame.Rect(5, CELL - 18, CELL - 10, 18)
    rr = rotate_local_rect(base, rotation)
    return rr.move(gx * CELL, gy * CELL)


def make_stars(n=120):
    return [
        (random.randint(-200, 4000), random.randint(0, GROUND_Y - 30), random.randint(1, 2), random.randint(80, 200))
        for _ in range(n)
    ]


def draw_bg(surf, cam_x=0, stars=None):
    surf.fill(C_BG)
    if stars:
        for sx, sy, sr, sb in stars:
            px = int((sx - cam_x * 0.12) % (WIDTH + 400) - 200)
            pygame.draw.circle(surf, (sb, sb, min(255, sb + 30)), (px, sy), sr)
    pygame.draw.rect(surf, C_GROUND, (0, GROUND_Y, WIDTH, HEIGHT - GROUND_Y))
    pygame.draw.line(surf, C_GROUND_L, (0, GROUND_Y), (WIDTH, GROUND_Y), 3)


def draw_portal_box(surf, x, y, s, col, pulse, inner_scale=0.6):
    rr = pygame.Rect(x + 8, y + 2, s - 16, s - 4)
    pulse_val = int(math.sin(pulse * 0.06) * 35)
    c = tuple(clamp(v + pulse_val, 0, 255) for v in col)
    pygame.draw.rect(surf, c, rr, 3, border_radius=8)
    inner = rr.inflate(int(-(1.0 - inner_scale) * rr.w), int(-(1.0 - inner_scale) * rr.h))
    pygame.draw.rect(surf, lighter(c, 25), inner, 0, border_radius=6)
    return rr


def draw_speed_arrows(surf, rr, col, count):
    for i in range(count):
        ox = rr.x + 8 + i * 8
        cy = rr.centery
        pts = [(ox, cy - 6), (ox + 10, cy), (ox, cy + 6)]
        pygame.draw.polygon(surf, col, pts)


def _draw_obj_base(surf, t, s=CELL, pulse=0):
    if t == T_BLOCK:
        pygame.draw.rect(surf, C_BLOCK, (0, 0, s, s))
        pygame.draw.rect(surf, C_BLOCK_H, (3, 3, s - 6, s - 6), 2)
    elif t == T_SPIKE:
        pts = [(s // 2, 3), (4, s), (s - 4, s)]
        pygame.draw.polygon(surf, C_SPIKE, pts)
        pygame.draw.polygon(surf, lighter(C_SPIKE, 30), pts, 2)
    elif t == T_HALF_SPIKE:
        pts = [(s // 2, s // 2 + 2), (4, s), (s - 4, s)]
        col = lighter(C_SPIKE, 20)
        pygame.draw.polygon(surf, col, pts)
        pygame.draw.polygon(surf, lighter(col, 25), pts, 2)
    elif t == T_ORB:
        cx2, cy2 = s // 2, s // 2
        r = 14 + int(math.sin(pulse * 0.08) * 3)
        pygame.draw.circle(surf, darker(C_ORB, 80), (cx2, cy2), r + 5)
        pygame.draw.circle(surf, C_ORB, (cx2, cy2), r)
        pygame.draw.circle(surf, lighter(C_ORB, 80), (cx2, cy2), max(2, r - 6))
    elif t == T_DASH_ORB:
        cx2, cy2 = s // 2, s // 2
        r = 15 + int(math.sin(pulse * 0.08) * 3)
        pygame.draw.circle(surf, darker(C_DASH_ORB, 90), (cx2, cy2), r + 5)
        pygame.draw.circle(surf, C_DASH_ORB, (cx2, cy2), r, 4)
        pygame.draw.line(surf, lighter(C_DASH_ORB, 70), (cx2 - 8, cy2), (cx2 + 8, cy2), 4)
        pygame.draw.polygon(surf, lighter(C_DASH_ORB, 40), [(cx2 + 10, cy2), (cx2 + 2, cy2 - 6), (cx2 + 2, cy2 + 6)])
    elif t == T_PAD:
        pygame.draw.rect(surf, C_PAD, (5, s - 16, s - 10, 16), border_radius=3)
        pygame.draw.rect(surf, lighter(C_PAD, 50), (8, s - 13, s - 16, 10), border_radius=2)
    elif t == T_GRAV:
        rr = draw_portal_box(surf, 0, 0, s, C_GPORTAL, pulse, 0.58)
        arrow = [(rr.centerx, rr.y + 8), (rr.centerx - 7, rr.y + 20), (rr.centerx - 2, rr.y + 20), (rr.centerx - 2, rr.bottom - 10), (rr.centerx + 2, rr.bottom - 10), (rr.centerx + 2, rr.y + 20), (rr.centerx + 7, rr.y + 20)]
        pygame.draw.polygon(surf, C_WHITE, arrow)
    elif t == T_END:
        rr = pygame.Rect(6, 2, s - 12, s - 4)
        pygame.draw.rect(surf, C_END, rr, 3, border_radius=6)
        pygame.draw.rect(surf, lighter(C_END, 50), rr.inflate(-8, -8), 0, border_radius=4)
        for i in range(3):
            for j in range(3):
                if (i + j) % 2 == 0:
                    pygame.draw.rect(surf, C_WHITE, (16 + i * 6, 14 + j * 6, 6, 6))
    elif t in MODE_FROM_TYPE:
        col = TYPE_COLS[t]
        rr = draw_portal_box(surf, 0, 0, s, col, pulse, 0.56)
        label = "C" if t == T_MODE_CUBE else "S" if t == T_MODE_SHIP else "B"
        txt(surf, label, rr.centerx, rr.centery, 20, C_WHITE, True)
    elif t in SPEED_VALUES:
        col = TYPE_COLS[t]
        rr = draw_portal_box(surf, 0, 0, s, col, pulse, 0.52)
        count = 1 if t == T_SPEED_SLOW else 2 if t == T_SPEED_NORMAL else 3 if t == T_SPEED_FAST else 4
        draw_speed_arrows(surf, rr, C_WHITE, count)
    elif t == T_START:
        cx2, cy2 = s // 2, s // 2
        pygame.draw.circle(surf, C_WHITE, (cx2, cy2), s // 2 - 8, 3)
        pygame.draw.circle(surf, lighter(C_PLAYER, 35), (cx2, cy2), s // 2 - 15, 2)
        arrow = [(cx2 - 10, cy2), (cx2 + 4, cy2), (cx2 + 4, cy2 - 7), (cx2 + 14, cy2 + 2), (cx2 + 4, cy2 + 11), (cx2 + 4, cy2 + 4), (cx2 - 10, cy2 + 4)]
        pygame.draw.polygon(surf, C_PLAYER, arrow)


def draw_obj(surf, t, x, y, s=CELL, pulse=0, rot=0):
    rot = normalize_rotation(rot)
    obj = pygame.Surface((s, s), pygame.SRCALPHA)
    _draw_obj_base(obj, t, s, pulse)
    if rot:
        obj = pygame.transform.rotate(obj, -rot)
        rr = obj.get_rect(center=(x + s / 2, y + s / 2))
        surf.blit(obj, rr)
    else:
        surf.blit(obj, (x, y))


class Particles:
    def __init__(self):
        self.ps = []

    def burst(self, x, y, col, n=25):
        for _ in range(n):
            self.ps.append([x, y, random.uniform(-5, 5), random.uniform(-7, 2), random.randint(15, 30), random.randint(3, 8), col])

    def update(self):
        alive = []
        for p in self.ps:
            p[0] += p[2]
            p[1] += p[3]
            p[3] += 0.25
            p[4] -= 1
            if p[4] > 0:
                alive.append(p)
        self.ps = alive

    def draw(self, surf):
        for p in self.ps:
            sz = max(1, int(p[5] * p[4] / 30))
            pygame.draw.rect(surf, p[6], (int(p[0]), int(p[1]), sz, sz))


def ensure_dirs():
    os.makedirs(LEVELS_DIR, exist_ok=True)


def normalize_object(o):
    return {
        "t": o["t"],
        "x": int(o["x"]),
        "y": int(o["y"]),
        "r": normalize_rotation(o.get("r", 0)),
    }


def save_level(objects, name, filename):
    ensure_dirs()
    data = {"name": name, "v": 3, "objects": [normalize_object(o) for o in objects]}
    fn = filename if filename.endswith(".json") else filename + ".json"
    with open(os.path.join(LEVELS_DIR, fn), "w") as f:
        json.dump(data, f)


def load_level(path):
    with open(path) as f:
        data = json.load(f)
    return data.get("name", "Untitled"), [normalize_object(o) for o in data.get("objects", [])]


def list_levels():
    ensure_dirs()
    return sorted(f for f in os.listdir(LEVELS_DIR) if f.endswith(".json"))


def create_tutorial():
    objs = [{"t": T_START, "x": 3, "y": 9, "r": 0}]
    gaps = set(range(23, 27)) | set(range(48, 52)) | set(range(78, 82))
    for gx in range(150):
        if gx not in gaps:
            objs.append({"t": T_BLOCK, "x": gx, "y": 10})
    for gx in [9, 15, 16, 20]:
        objs.append({"t": T_SPIKE, "x": gx, "y": 9})
    objs.append({"t": T_HALF_SPIKE, "x": 12, "y": 9})
    objs.append({"t": T_PAD, "x": 22, "y": 9})
    objs.append({"t": T_ORB, "x": 25, "y": 7})
    for gx in [30, 31, 36, 37, 38, 43, 44]:
        objs.append({"t": T_SPIKE, "x": gx, "y": 9})
    for gx in range(34, 37):
        objs.append({"t": T_BLOCK, "x": gx, "y": 8})
    objs.append({"t": T_SPIKE, "x": 35, "y": 7})
    objs.append({"t": T_PAD, "x": 47, "y": 9})
    objs.append({"t": T_DASH_ORB, "x": 50, "y": 7})
    objs.append({"t": T_SPEED_FAST, "x": 54, "y": 9})
    for gx in range(56, 60):
        objs.append({"t": T_BLOCK, "x": gx, "y": 8})
    for gx in range(62, 66):
        objs.append({"t": T_BLOCK, "x": gx, "y": 7})
        objs.append({"t": T_BLOCK, "x": gx, "y": 8})
    for gx in [57, 64]:
        objs.append({"t": T_SPIKE, "x": gx, "y": 9})
    objs.append({"t": T_SPIKE, "x": 63, "y": 6})
    objs.append({"t": T_PAD, "x": 77, "y": 9})
    objs.append({"t": T_ORB, "x": 80, "y": 7})
    for gx in [85, 86, 90, 91, 92, 96, 97]:
        objs.append({"t": T_SPIKE, "x": gx, "y": 9})
    objs.append({"t": T_GRAV, "x": 104, "y": 9})
    for gx in range(105, 122):
        objs.append({"t": T_BLOCK, "x": gx, "y": 3})
    objs.append({"t": T_MODE_SHIP, "x": 111, "y": 4})
    objs.append({"t": T_SPEED_SLOW, "x": 112, "y": 4})
    for gx in [114, 117, 119]:
        objs.append({"t": T_SPIKE, "x": gx, "y": 2})
    objs.append({"t": T_MODE_BALL, "x": 123, "y": 4})
    objs.append({"t": T_GRAV, "x": 124, "y": 4})
    for gx in range(126, 130):
        objs.append({"t": T_BLOCK, "x": gx, "y": 10})
        objs.append({"t": T_BLOCK, "x": gx, "y": 7})
    objs.append({"t": T_MODE_CUBE, "x": 131, "y": 9})
    objs.append({"t": T_SPEED_NORMAL, "x": 132, "y": 9})
    for gx in [126, 127, 134, 135]:
        objs.append({"t": T_SPIKE, "x": gx, "y": 9})
    objs.append({"t": T_HALF_SPIKE, "x": 136, "y": 9})
    objs.append({"t": T_END, "x": 145, "y": 9})
    save_level(objs, "Tutorial", "tutorial")


class Player:
    def __init__(self, objects):
        self.objects = objects
        self.reset()

    def reset(self):
        self.x, self.y = self._spawn_point()
        self.vy = 0.0
        self.on_ground = False
        self.alive = True
        self.won = False
        self.angle = 0.0
        self.grav = 1
        self.trail = []
        self.passed = set()
        self.frame = 0
        self.mode = MODE_CUBE
        self.move_speed = BASE_MOVE_SPEED
        self.dash_timer = 0
        self.input_buffer = 0

    def _start_object(self):
        starts = [o for o in self.objects if o["t"] == T_START]
        if starts:
            return min(starts, key=lambda o: (o["x"], o["y"]))
        return None

    def _spawn_point(self):
        start = self._start_object()
        if start:
            return (
                float(start["x"] * CELL + (CELL - PLAYER_SIZE) / 2),
                float(start["y"] * CELL + (CELL - PLAYER_SIZE) / 2),
            )
        return float(PLAYER_START_GX * CELL), float(self._ground_y())

    def _ground_y(self):
        col_blocks = [o for o in self.objects if o["t"] == T_BLOCK and o["x"] == PLAYER_START_GX]
        if col_blocks:
            top = min(o["y"] for o in col_blocks)
            return top * CELL - PLAYER_SIZE
        return 10 * CELL - PLAYER_SIZE

    def rect(self):
        return pygame.Rect(round(self.x), round(self.y), PLAYER_SIZE, PLAYER_SIZE)

    def nearby_objects(self, extra_x=3, extra_y=2):
        gx = int(self.x // CELL)
        gy = int(self.y // CELL)
        return [o for o in self.objects if gx - extra_x <= o["x"] <= gx + extra_x and gy - extra_y <= o["y"] <= gy + extra_y]

    def nearby_for_rect(self, rect, extra=2):
        left = rect.left // CELL - extra
        right = rect.right // CELL + extra
        top = rect.top // CELL - extra
        bottom = rect.bottom // CELL + extra
        return [o for o in self.objects if left <= o["x"] <= right and top <= o["y"] <= bottom]

    def jump(self, force=None):
        if force is None:
            force = JUMP_FORCE
        self.vy = force * self.grav
        self.on_ground = False

    def activate_orb(self):
        if self.mode == MODE_BALL:
            self.grav *= -1
            self.vy = BALL_FLIP_FORCE * self.grav
            self.on_ground = False
        elif self.mode == MODE_SHIP:
            self.vy = JUMP_FORCE * 0.85 * self.grav
            self.on_ground = False
        else:
            self.jump(JUMP_FORCE)

    def activate_dash_orb(self):
        self.activate_orb()
        self.dash_timer = DASH_TIME
        self.input_buffer = 0

    def flip_gravity(self):
        self.grav *= -1
        self.on_ground = False
        mag = clamp(abs(self.vy), 2.0, 10.0)
        self.vy = mag * self.grav

    def set_mode(self, mode):
        self.mode = mode
        if mode == MODE_CUBE:
            self.angle = round(self.angle / 90) * 90
        elif mode == MODE_BALL:
            self.angle = round(self.angle / 90) * 90

    def set_speed(self, speed_type):
        self.move_speed = SPEED_VALUES.get(speed_type, BASE_MOVE_SPEED)

    def _resolve_x_collision(self, dx_step):
        pr = self.rect()
        blocks = [o for o in self.nearby_for_rect(pr) if o["t"] == T_BLOCK]
        for o in blocks:
            br = cell_rect(o["x"], o["y"])
            if pr.colliderect(br):
                if dx_step > 0:
                    self.x = br.left - PLAYER_SIZE
                elif dx_step < 0:
                    self.x = br.right
                self.alive = False
                return True
        return False

    def _resolve_y_collision(self, dy_step):
        pr = self.rect()
        blocks = [o for o in self.nearby_for_rect(pr) if o["t"] == T_BLOCK]
        if dy_step > 0:
            blocks.sort(key=lambda o: o["y"])
        elif dy_step < 0:
            blocks.sort(key=lambda o: -o["y"])
        for o in blocks:
            br = cell_rect(o["x"], o["y"])
            if not pr.colliderect(br):
                continue
            if self.grav == 1:
                if dy_step >= 0:
                    self.y = br.top - PLAYER_SIZE
                    self.vy = 0.0
                    self.on_ground = True
                else:
                    self.y = br.bottom
                    self.vy = 0.0
            else:
                if dy_step <= 0:
                    self.y = br.bottom
                    self.vy = 0.0
                    self.on_ground = True
                else:
                    self.y = br.top - PLAYER_SIZE
                    self.vy = 0.0
            pr = self.rect()

    def _handle_interactions(self, trigger_rect, input_active):
        for o in self.nearby_for_rect(trigger_rect, 2):
            key = (o["t"], o["x"], o["y"])
            if o["t"] == T_BLOCK:
                continue
            if o["t"] in (T_SPIKE, T_HALF_SPIKE):
                for sr in spike_hitboxes(o["x"], o["y"], o.get("r", 0), o["t"] == T_HALF_SPIKE):
                    if trigger_rect.colliderect(sr):
                        self.alive = False
                        return True
            elif o["t"] == T_PAD and key not in self.passed:
                if trigger_rect.colliderect(pad_trigger_rect(o["x"], o["y"], o.get("r", 0))):
                    if self.mode == MODE_SHIP:
                        self.vy = JUMP_FORCE * 0.95 * self.grav
                        self.on_ground = False
                    else:
                        self.jump(PAD_FORCE)
                    self.passed.add(key)
            elif o["t"] == T_ORB and key not in self.passed:
                if input_active and trigger_rect.colliderect(cell_rect(o["x"], o["y"])):
                    self.activate_orb()
                    self.passed.add(key)
            elif o["t"] == T_DASH_ORB and key not in self.passed:
                if input_active and trigger_rect.colliderect(cell_rect(o["x"], o["y"])):
                    self.activate_dash_orb()
                    self.passed.add(key)
            elif o["t"] == T_GRAV and key not in self.passed:
                if trigger_rect.colliderect(cell_rect(o["x"], o["y"])):
                    self.flip_gravity()
                    self.passed.add(key)
            elif o["t"] in MODE_FROM_TYPE and key not in self.passed:
                if trigger_rect.colliderect(cell_rect(o["x"], o["y"])):
                    self.set_mode(MODE_FROM_TYPE[o["t"]])
                    self.passed.add(key)
            elif o["t"] in SPEED_VALUES and key not in self.passed:
                if trigger_rect.colliderect(cell_rect(o["x"], o["y"])):
                    self.set_speed(o["t"])
                    self.passed.add(key)
            elif o["t"] == T_END:
                if trigger_rect.colliderect(cell_rect(o["x"], o["y"])):
                    self.won = True
                    return True
            elif o["t"] == T_START:
                continue
        return False

    def update(self, input_held, input_pressed):
        if not self.alive or self.won:
            return
        self.frame += 1
        if self.frame % 3 == 0:
            self.trail.append([self.x, self.y, self.angle, 100])
        self.trail = [[x, y, a, al - 5] for x, y, a, al in self.trail if al > 5]
        if input_pressed:
            self.input_buffer = 6
        elif self.input_buffer > 0:
            self.input_buffer -= 1
        if self.mode == MODE_SHIP:
            self.vy += SHIP_GRAVITY * self.grav
            if input_held:
                self.vy -= SHIP_THRUST * self.grav
            self.vy = clamp(self.vy, -13.0, 13.0)
        else:
            self.vy += GRAVITY * self.grav
            self.vy = clamp(self.vy, -18.0, 18.0)
            if self.mode == MODE_CUBE and input_held and self.on_ground:
                self.jump()
            elif self.mode == MODE_BALL and input_pressed and self.on_ground:
                self.grav *= -1
                self.vy = BALL_FLIP_FORCE * self.grav
                self.on_ground = False
        dx = self.move_speed + (DASH_SPEED if self.dash_timer > 0 else 0.0)
        if self.dash_timer > 0:
            self.dash_timer -= 1
        self.on_ground = False
        steps = max(1, int(math.ceil(max(abs(dx), abs(self.vy)) / 4.0)))
        dx_step = dx / steps
        input_active = input_held or self.input_buffer > 0
        for _ in range(steps):
            prev_rect = self.rect()
            self.x += dx_step
            if self._resolve_x_collision(dx_step):
                return
            dy_step = self.vy / steps
            self.y += dy_step
            self._resolve_y_collision(dy_step)
            trigger_rect = prev_rect.union(self.rect()).inflate(6, 6)
            if self._handle_interactions(trigger_rect, input_active):
                return
        if self.y > HEIGHT + 300 or self.y < -500:
            self.alive = False
            return
        if self.mode == MODE_SHIP:
            self.angle = clamp(-self.vy * 4.2, -55, 55)
        elif self.mode == MODE_BALL:
            if self.on_ground:
                self.angle = round(self.angle / 90) * 90
            else:
                self.angle -= 10 * self.grav
        else:
            if not self.on_ground:
                self.angle -= 5 * self.grav
            else:
                self.angle = round(self.angle / 90) * 90

    def draw(self, surf, cam_x):
        for tx, ty, ta, al in self.trail:
            sx = tx - cam_x
            if sx < -60 or sx > WIDTH + 60:
                continue
            if self.mode == MODE_BALL:
                ts = pygame.Surface((PLAYER_SIZE, PLAYER_SIZE), pygame.SRCALPHA)
                pygame.draw.circle(ts, (*C_PLAYER, int(al * 0.35)), (PLAYER_SIZE // 2, PLAYER_SIZE // 2), PLAYER_SIZE // 2 - 2)
            elif self.mode == MODE_SHIP:
                ts = pygame.Surface((PLAYER_SIZE, PLAYER_SIZE), pygame.SRCALPHA)
                pygame.draw.polygon(ts, (*C_PLAYER, int(al * 0.35)), [(5, PLAYER_SIZE // 2), (PLAYER_SIZE - 6, 8), (PLAYER_SIZE - 6, PLAYER_SIZE - 8)])
            else:
                ts = pygame.Surface((PLAYER_SIZE, PLAYER_SIZE), pygame.SRCALPHA)
                ts.fill((*C_PLAYER, int(al * 0.4)))
            rot = pygame.transform.rotate(ts, ta)
            rr = rot.get_rect(center=(sx + PLAYER_SIZE // 2, ty + PLAYER_SIZE // 2))
            surf.blit(rot, rr)
        sx = self.x - cam_x
        ps = pygame.Surface((PLAYER_SIZE, PLAYER_SIZE), pygame.SRCALPHA)
        if self.mode == MODE_SHIP:
            pygame.draw.polygon(ps, C_PLAYER, [(4, PLAYER_SIZE // 2), (PLAYER_SIZE - 8, 7), (PLAYER_SIZE - 8, PLAYER_SIZE - 7)])
            pygame.draw.polygon(ps, lighter(C_PLAYER, 45), [(8, PLAYER_SIZE // 2), (PLAYER_SIZE - 14, 13), (PLAYER_SIZE - 14, PLAYER_SIZE - 13)], 2)
            flame_col = C_DASH_ORB if self.dash_timer > 0 else C_PAD
            pygame.draw.polygon(ps, flame_col, [(3, PLAYER_SIZE // 2), (12, PLAYER_SIZE // 2 - 6), (12, PLAYER_SIZE // 2 + 6)])
        elif self.mode == MODE_BALL:
            pygame.draw.circle(ps, C_PLAYER, (PLAYER_SIZE // 2, PLAYER_SIZE // 2), PLAYER_SIZE // 2 - 2)
            pygame.draw.circle(ps, lighter(C_PLAYER, 50), (PLAYER_SIZE // 2, PLAYER_SIZE // 2), PLAYER_SIZE // 2 - 8, 2)
            pygame.draw.circle(ps, darker(C_PLAYER, 40), (PLAYER_SIZE // 2, PLAYER_SIZE // 2), 6)
        else:
            pygame.draw.rect(ps, C_PLAYER, (0, 0, PLAYER_SIZE, PLAYER_SIZE))
            pygame.draw.rect(ps, lighter(C_PLAYER, 50), (3, 3, PLAYER_SIZE - 6, PLAYER_SIZE - 6), 2)
            c = PLAYER_SIZE // 2
            pygame.draw.rect(ps, darker(C_PLAYER, 40), (c - 7, c - 7, 14, 14))
        rot = pygame.transform.rotate(ps, self.angle)
        rr = rot.get_rect(center=(sx + PLAYER_SIZE // 2, self.y + PLAYER_SIZE // 2))
        surf.blit(rot, rr)


def run_menu(screen, clock):
    stars = make_stars()
    pulse = 0
    b_play = b_edit = b_quit = pygame.Rect(0, 0, 0, 0)
    while True:
        pulse += 1
        mpos = pygame.mouse.get_pos()
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return "quit"
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                return "quit"
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if b_play.collidepoint(ev.pos):
                    return "play"
                if b_edit.collidepoint(ev.pos):
                    return "editor"
                if b_quit.collidepoint(ev.pos):
                    return "quit"
        draw_bg(screen, pulse * 0.5, stars)
        txt(screen, "GEOMETRY DASH", WIDTH // 2, 160, 56, C_PLAYER, True)
        txt(screen, "TEMU EDITION", WIDTH // 2, 220, 28, C_GRAY, True)
        b_play = btn(screen, "PLAY", WIDTH // 2, 320, 220, 52, C_BTN, mpos)
        b_edit = btn(screen, "LEVEL EDITOR", WIDTH // 2, 395, 220, 52, C_BTN, mpos)
        b_quit = btn(screen, "QUIT", WIDTH // 2, 470, 220, 52, C_DANGER, mpos)
        for i in range(5):
            a = pulse * 2 + i * 72
            bx = WIDTH // 2 + int(math.cos(math.radians(a)) * 260)
            by = 350 + int(math.sin(math.radians(a)) * 100)
            s = pygame.Surface((22, 22), pygame.SRCALPHA)
            pygame.draw.rect(s, (*C_PLAYER, 90), (0, 0, 22, 22))
            rot = pygame.transform.rotate(s, a)
            screen.blit(rot, rot.get_rect(center=(bx, by)))
        txt(screen, "Space / Click to jump  |  Hold in ship  |  Arrow keys / WASD in editor", WIDTH // 2, HEIGHT - 30, 15, C_GRAY, True)
        pygame.display.flip()
        clock.tick(FPS)


def run_select(screen, clock):
    files = list_levels()
    scroll = 0
    stars = make_stars()
    b_back = pygame.Rect(0, 0, 0, 0)
    while True:
        mpos = pygame.mouse.get_pos()
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                return None
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if b_back.collidepoint(ev.pos):
                    return None
                for i, f in enumerate(files):
                    y = 200 + i * 48 - scroll
                    r = pygame.Rect(WIDTH // 2 - 200, y, 400, 42)
                    if 160 < y < HEIGHT - 80 and r.collidepoint(ev.pos):
                        return os.path.join(LEVELS_DIR, f)
            if ev.type == pygame.MOUSEWHEEL:
                scroll = max(0, scroll - ev.y * 30)
        draw_bg(screen, 0, stars)
        txt(screen, "SELECT LEVEL", WIDTH // 2, 80, 40, C_WHITE, True)
        if not files:
            txt(screen, "No levels found. Create one in the editor!", WIDTH // 2, HEIGHT // 2, 22, C_GRAY, True)
        else:
            for i, f in enumerate(files):
                y = 200 + i * 48 - scroll
                if 160 < y < HEIGHT - 80:
                    r = pygame.Rect(WIDTH // 2 - 200, y, 400, 42)
                    c = C_BTN_H if r.collidepoint(mpos) else C_BTN
                    pygame.draw.rect(screen, c, r, border_radius=8)
                    pygame.draw.rect(screen, lighter(c, 30), r, 2, border_radius=8)
                    name = f.replace(".json", "").replace("_", " ").title()
                    txt(screen, name, WIDTH // 2, y + 21, 20, C_WHITE, True)
        b_back = btn(screen, "BACK", WIDTH // 2, HEIGHT - 45, 160, 44, C_DANGER, mpos)
        pygame.display.flip()
        clock.tick(FPS)


def run_play(screen, clock, objects, level_name="Level", editor_test=False):
    player = Player(objects)
    particles = Particles()
    stars = make_stars()
    cam_x = 0.0
    attempts = 1
    death_timer = 0
    pulse = 0
    max_x = max((o["x"] for o in objects), default=10) * CELL + CELL
    rc_menu = make_rect(WIDTH // 2 - 110, HEIGHT // 2 + 60, 160, 46)
    rc_replay = make_rect(WIDTH // 2 + 110, HEIGHT // 2 + 60, 160, 46)
    prev_input_held = False
    sim_accum = 0.0
    pending_jump_press = False
    test_speeds = [0.01, 0.05, 0.1, 0.25, 0.5, 1.0]
    test_speed_idx = len(test_speeds) - 1
    while True:
        pulse += 1
        mpos = pygame.mouse.get_pos()
        mouse_pressed_this_frame = False
        clicked_pos = None
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    return "quit"
                if ev.key == pygame.K_r and not player.won:
                    player.reset()
                    attempts += 1
                    death_timer = 0
                    prev_input_held = False
                    pending_jump_press = False
                    sim_accum = 0.0
                if editor_test and ev.key in (pygame.K_LEFTBRACKET, pygame.K_MINUS):
                    test_speed_idx = max(0, test_speed_idx - 1)
                if editor_test and ev.key in (pygame.K_RIGHTBRACKET, pygame.K_EQUALS):
                    test_speed_idx = min(len(test_speeds) - 1, test_speed_idx + 1)
                if editor_test and ev.key in (pygame.K_0, pygame.K_BACKQUOTE):
                    test_speed_idx = len(test_speeds) - 1
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                clicked_pos = ev.pos
                mouse_pressed_this_frame = True
        keys = pygame.key.get_pressed()
        jump_held = keys[pygame.K_SPACE] or keys[pygame.K_UP] or keys[pygame.K_w] or pygame.mouse.get_pressed()[0]
        jump_pressed = mouse_pressed_this_frame or (jump_held and not prev_input_held)
        prev_input_held = jump_held
        if jump_pressed:
            pending_jump_press = True
        if player.won and clicked_pos:
            if rc_menu.collidepoint(clicked_pos):
                return "menu"
            if rc_replay.collidepoint(clicked_pos):
                player.reset()
                attempts = 1
                death_timer = 0
                prev_input_held = False
        step_scale = test_speeds[test_speed_idx] if editor_test else 1.0
        sim_accum += step_scale
        while sim_accum >= 1.0:
            sim_accum -= 1.0
            if death_timer > 0:
                death_timer -= 1
                if death_timer <= 0:
                    player.reset()
                    attempts += 1
                    prev_input_held = False
                    pending_jump_press = False
            elif player.alive and not player.won:
                player.update(jump_held, pending_jump_press)
                cam_x = max(0, player.x - 200)
                pending_jump_press = False
            elif not player.alive and death_timer == 0:
                particles.burst(player.x - cam_x + PLAYER_SIZE // 2, player.y + PLAYER_SIZE // 2, C_PLAYER, 30)
                death_timer = 35
                pending_jump_press = False
            particles.update()
        draw_bg(screen, cam_x, stars)
        left_gx = int(cam_x // CELL) - 1
        right_gx = left_gx + WIDTH // CELL + 3
        for o in objects:
            if left_gx <= o["x"] <= right_gx:
                draw_obj(screen, o["t"], o["x"] * CELL - cam_x, o["y"] * CELL, CELL, pulse, o.get("r", 0))
        if player.alive and death_timer == 0:
            player.draw(screen, cam_x)
        particles.draw(screen)
        progress = max(0.0, min(1.0, player.x / max_x))
        bw = WIDTH - 100
        pygame.draw.rect(screen, C_DARK, (50, 12, bw, 8), border_radius=4)
        pygame.draw.rect(screen, C_PLAYER, (50, 12, max(1, int(bw * progress)), 8), border_radius=4)
        txt(screen, f"Attempt {attempts}", 20, 28, 17, C_GRAY)
        txt(screen, level_name, WIDTH // 2, 8, 15, C_GRAY, True)
        txt(screen, player.mode.title(), WIDTH - 220, 26, 15, C_GRAY)
        txt(screen, f"Move {player.move_speed:.1f}", WIDTH - 150, 26, 15, C_GRAY)
        if editor_test:
            txt(screen, f"Test {test_speeds[test_speed_idx]:.2f}x", WIDTH - 85, 26, 15, C_GRAY)
        else:
            txt(screen, "", WIDTH - 85, 26, 15, C_GRAY)
        if editor_test:
            txt(screen, "[/- slower  ]/= faster  0 reset", WIDTH // 2, HEIGHT - 22, 15, C_GRAY, True)
        if player.won:
            ov = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            ov.fill((0, 0, 0, 130))
            screen.blit(ov, (0, 0))
            txt(screen, "LEVEL COMPLETE!", WIDTH // 2, HEIGHT // 2 - 70, 52, C_PLAYER, True)
            txt(screen, f"Attempts: {attempts}", WIDTH // 2, HEIGHT // 2 - 10, 28, C_WHITE, True)
            btn(screen, "Menu", WIDTH // 2 - 110, HEIGHT // 2 + 60, 160, 46, C_BTN, mpos)
            btn(screen, "Replay", WIDTH // 2 + 110, HEIGHT // 2 + 60, 160, 46, C_BTN, mpos)
        pygame.display.flip()
        clock.tick(FPS)


def text_input_dialog(screen, clock, prompt="Enter name:", default=""):
    text = default
    stars = make_stars()
    while True:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_RETURN and text.strip():
                    return text.strip()
                if ev.key == pygame.K_ESCAPE:
                    return None
                if ev.key == pygame.K_BACKSPACE:
                    text = text[:-1]
                elif len(text) < 30 and ev.unicode.isprintable():
                    text += ev.unicode
        draw_bg(screen, 0, stars)
        ov = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 160))
        screen.blit(ov, (0, 0))
        box = pygame.Rect(WIDTH // 2 - 220, HEIGHT // 2 - 90, 440, 180)
        pygame.draw.rect(screen, C_DARK, box, border_radius=12)
        pygame.draw.rect(screen, C_BLOCK_H, box, 2, border_radius=12)
        txt(screen, prompt, WIDTH // 2, HEIGHT // 2 - 55, 24, C_WHITE, True)
        tf = pygame.Rect(WIDTH // 2 - 170, HEIGHT // 2 - 18, 340, 38)
        pygame.draw.rect(screen, (15, 15, 30), tf, border_radius=4)
        pygame.draw.rect(screen, C_BLOCK_H, tf, 1, border_radius=4)
        txt(screen, text + "|", tf.x + 10, tf.y + 8, 20, C_WHITE)
        txt(screen, "Enter to confirm  ·  Esc to cancel", WIDTH // 2, HEIGHT // 2 + 55, 15, C_GRAY, True)
        pygame.display.flip()
        clock.tick(FPS)


def load_level_dialog(screen, clock):
    files = list_levels()
    scroll = 0
    stars = make_stars()
    while True:
        mpos = pygame.mouse.get_pos()
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                return None
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                for i, f in enumerate(files):
                    y = 220 + i * 44 - scroll
                    r = pygame.Rect(WIDTH // 2 - 170, y, 340, 38)
                    if 190 < y < 510 and r.collidepoint(ev.pos):
                        return os.path.join(LEVELS_DIR, f)
            if ev.type == pygame.MOUSEWHEEL:
                scroll = max(0, scroll - ev.y * 25)
        draw_bg(screen, 0, stars)
        ov = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 160))
        screen.blit(ov, (0, 0))
        box = pygame.Rect(WIDTH // 2 - 210, 130, 420, 440)
        pygame.draw.rect(screen, C_DARK, box, border_radius=12)
        pygame.draw.rect(screen, C_BLOCK_H, box, 2, border_radius=12)
        txt(screen, "Load Level", WIDTH // 2, 160, 28, C_WHITE, True)
        if not files:
            txt(screen, "No levels found.", WIDTH // 2, 300, 20, C_GRAY, True)
        for i, f in enumerate(files):
            y = 220 + i * 44 - scroll
            if 190 < y < 510:
                r = pygame.Rect(WIDTH // 2 - 170, y, 340, 38)
                c = C_BTN_H if r.collidepoint(mpos) else C_BTN
                pygame.draw.rect(screen, c, r, border_radius=6)
                txt(screen, f.replace(".json", ""), WIDTH // 2, y + 19, 18, C_WHITE, True)
        txt(screen, "Esc to cancel", WIDTH // 2, 548, 15, C_GRAY, True)
        pygame.display.flip()
        clock.tick(FPS)


def object_at_cell(objects, gx, gy, prefer_non_start=False):
    found = None
    for o in objects:
        if o["x"] == gx and o["y"] == gy:
            if not prefer_non_start or o["t"] != T_START:
                found = o
    if found:
        return found
    if prefer_non_start:
        for o in objects:
            if o["x"] == gx and o["y"] == gy:
                found = o
    return found


def run_editor(screen, clock):
    objects = [{"t": T_BLOCK, "x": gx, "y": 10, "r": 0} for gx in range(60)]
    level_name = "Untitled"
    cam_x, cam_y = 0.0, 0.0
    selected = 0
    show_grid = True
    pulse = 0
    msg, msg_timer = "", 0
    stars = make_stars()
    eraser = False
    current_rotation = 0
    PAL_H = 58
    BAR_Y = HEIGHT - 55
    r_save = make_rect(100, BAR_Y + 27, 130, 38)
    r_load = make_rect(250, BAR_Y + 27, 130, 38)
    r_test = make_rect(400, BAR_Y + 27, 130, 38)
    r_clear = make_rect(550, BAR_Y + 27, 110, 38)
    r_menu = make_rect(710, BAR_Y + 27, 140, 38)
    while True:
        pulse += 1
        mpos = pygame.mouse.get_pos()
        do_save = do_load = do_test = False
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    return
                if ev.key == pygame.K_g:
                    show_grid = not show_grid
                if ev.key == pygame.K_e:
                    eraser = not eraser
                if ev.key == pygame.K_s:
                    do_save = True
                if ev.key == pygame.K_l:
                    do_load = True
                if ev.key == pygame.K_t:
                    do_test = True
                if ev.key in (pygame.K_r, pygame.K_q):
                    delta = 90 if ev.key == pygame.K_r else -90
                    mx, my = pygame.mouse.get_pos()
                    if PAL_H < my < BAR_Y:
                        gx = int((mx + cam_x) // CELL)
                        gy = int((my + cam_y) // CELL)
                        target = object_at_cell(objects, gx, gy, True)
                        if target:
                            target["r"] = normalize_rotation(target.get("r", 0) + delta)
                            msg, msg_timer = f"Rotated to {target['r']}°", 70
                        else:
                            current_rotation = normalize_rotation(current_rotation + delta)
                            msg, msg_timer = f"Placement rotation: {current_rotation}°", 70
                    else:
                        current_rotation = normalize_rotation(current_rotation + delta)
                        msg, msg_timer = f"Placement rotation: {current_rotation}°", 70
                for i in range(min(len(ALL_TYPES), 9)):
                    if ev.key == pygame.K_1 + i:
                        selected = i
                        eraser = False
            if ev.type == pygame.MOUSEBUTTONDOWN:
                mx, my = ev.pos
                if ev.button == 1:
                    if my < PAL_H:
                        for i in range(len(ALL_TYPES)):
                            px = 70 + i * 62
                            pr = pygame.Rect(px - 23, 5, 50, 45)
                            if pr.collidepoint(mx, my):
                                selected = i
                                eraser = False
                        ex = 70 + len(ALL_TYPES) * 62
                        er = pygame.Rect(ex - 23, 5, 50, 45)
                        if er.collidepoint(mx, my):
                            eraser = True
                    elif my > BAR_Y:
                        if r_save.collidepoint(ev.pos):
                            do_save = True
                        elif r_load.collidepoint(ev.pos):
                            do_load = True
                        elif r_test.collidepoint(ev.pos):
                            do_test = True
                        elif r_clear.collidepoint(ev.pos):
                            objects.clear()
                            msg, msg_timer = "Cleared all objects", 90
                        elif r_menu.collidepoint(ev.pos):
                            return
                    else:
                        gx = int((mx + cam_x) // CELL)
                        gy = int((my + cam_y) // CELL)
                        if eraser:
                            objects = [o for o in objects if not (o["x"] == gx and o["y"] == gy)]
                        else:
                            selected_type = ALL_TYPES[selected]
                            if selected_type == T_START:
                                objects = [o for o in objects if o["t"] != T_START]
                                objects.append({"t": T_START, "x": gx, "y": gy, "r": current_rotation})
                            elif not any(o["x"] == gx and o["y"] == gy and o["t"] != T_START for o in objects):
                                objects.append({"t": selected_type, "x": gx, "y": gy, "r": current_rotation})
                elif ev.button == 3 and PAL_H < my < BAR_Y:
                    gx = int((mx + cam_x) // CELL)
                    gy = int((my + cam_y) // CELL)
                    objects = [o for o in objects if not (o["x"] == gx and o["y"] == gy)]
        if do_save:
            name = text_input_dialog(screen, clock, "Level name:", level_name)
            if name:
                level_name = name
                fn = name.lower().replace(" ", "_")
                save_level(objects, name, fn)
                msg, msg_timer = f"Saved as {fn}.json", 120
        if do_load:
            path = load_level_dialog(screen, clock)
            if path:
                level_name, objects = load_level(path)
                msg, msg_timer = f"Loaded: {level_name}", 120
        if do_test:
            run_play(screen, clock, list(objects), level_name + " (Test)", editor_test=True)
        mb = pygame.mouse.get_pressed()
        if (mb[0] or mb[2]) and PAL_H < mpos[1] < BAR_Y:
            gx = int((mpos[0] + cam_x) // CELL)
            gy = int((mpos[1] + cam_y) // CELL)
            if mb[0] and not eraser:
                selected_type = ALL_TYPES[selected]
                if selected_type == T_START:
                    objects = [o for o in objects if o["t"] != T_START]
                    objects.append({"t": T_START, "x": gx, "y": gy, "r": current_rotation})
                elif not any(o["x"] == gx and o["y"] == gy and o["t"] != T_START for o in objects):
                    objects.append({"t": selected_type, "x": gx, "y": gy, "r": current_rotation})
            elif mb[0] and eraser:
                objects = [o for o in objects if not (o["x"] == gx and o["y"] == gy)]
            elif mb[2]:
                objects = [o for o in objects if not (o["x"] == gx and o["y"] == gy)]
        keys = pygame.key.get_pressed()
        spd = 12
        if keys[pygame.K_LEFT]:
            cam_x -= spd
        if keys[pygame.K_RIGHT]:
            cam_x += spd
        if keys[pygame.K_UP]:
            cam_y -= spd
        if keys[pygame.K_DOWN]:
            cam_y += spd
        if msg_timer > 0:
            msg_timer -= 1
        draw_bg(screen, cam_x, stars)
        if show_grid:
            ox = int(-cam_x % CELL)
            oy = int(-cam_y % CELL)
            for x in range(ox, WIDTH, CELL):
                pygame.draw.line(screen, C_GRID, (x, 0), (x, HEIGHT), 1)
            for y in range(oy, HEIGHT, CELL):
                pygame.draw.line(screen, C_GRID, (0, y), (WIDTH, y), 1)
        left_gx = int(cam_x // CELL) - 1
        right_gx = left_gx + WIDTH // CELL + 3
        top_gy = int(cam_y // CELL) - 1
        bot_gy = top_gy + HEIGHT // CELL + 3
        for o in objects:
            if left_gx <= o["x"] <= right_gx and top_gy <= o["y"] <= bot_gy:
                draw_obj(screen, o["t"], o["x"] * CELL - cam_x, o["y"] * CELL - cam_y, CELL, pulse, o.get("r", 0))
        if PAL_H < mpos[1] < BAR_Y:
            gx = int((mpos[0] + cam_x) // CELL)
            gy = int((mpos[1] + cam_y) // CELL)
            sx = gx * CELL - cam_x
            sy = gy * CELL - cam_y
            if eraser:
                pygame.draw.rect(screen, (255, 80, 80), (sx, sy, CELL, CELL), 2)
                pygame.draw.line(screen, (255, 80, 80), (sx + 8, sy + 8), (sx + CELL - 8, sy + CELL - 8), 2)
                pygame.draw.line(screen, (255, 80, 80), (sx + CELL - 8, sy + 8), (sx + 8, sy + CELL - 8), 2)
            else:
                gs = pygame.Surface((CELL, CELL), pygame.SRCALPHA)
                gs.set_alpha(120)
                draw_obj(gs, ALL_TYPES[selected], 0, 0, CELL, pulse, current_rotation)
                screen.blit(gs, (sx, sy))
                pygame.draw.rect(screen, C_WHITE, (sx, sy, CELL, CELL), 1)
        pygame.draw.rect(screen, (20, 18, 40), (0, 0, WIDTH, PAL_H))
        pygame.draw.line(screen, C_GRID, (0, PAL_H), (WIDTH, PAL_H), 1)
        for i, t in enumerate(ALL_TYPES):
            px = 70 + i * 62
            r = pygame.Rect(px - 23, 5, 50, 45)
            if i == selected and not eraser:
                pygame.draw.rect(screen, C_WHITE, r, 2, border_radius=6)
            draw_obj(screen, t, px - 14, 10, 28, pulse, 0)
            if i < 9:
                txt(screen, str(i + 1), px, 48, 11, C_GRAY, True)
        ex = 70 + len(ALL_TYPES) * 62
        er = pygame.Rect(ex - 23, 5, 50, 45)
        if eraser:
            pygame.draw.rect(screen, C_WHITE, er, 2, border_radius=6)
        pygame.draw.rect(screen, C_DANGER, (ex - 10, 14, 24, 24), border_radius=4)
        txt(screen, "X", ex + 2, 26, 15, C_WHITE, True)
        txt(screen, "E", ex + 2, 48, 11, C_GRAY, True)
        sel_name = "Eraser" if eraser else TYPE_NAMES.get(ALL_TYPES[selected], "")
        txt(screen, sel_name, WIDTH - 300, 18, 15, C_WHITE)
        txt(screen, f"Rot: {current_rotation}°", WIDTH - 160, 18, 15, C_WHITE)
        pygame.draw.rect(screen, (20, 18, 40), (0, BAR_Y, WIDTH, HEIGHT - BAR_Y))
        pygame.draw.line(screen, C_GRID, (0, BAR_Y), (WIDTH, BAR_Y), 1)
        btn(screen, "Save [S]", 100, BAR_Y + 27, 130, 38, C_BTN, mpos)
        btn(screen, "Load [L]", 250, BAR_Y + 27, 130, 38, C_BTN, mpos)
        btn(screen, "Test [T]", 400, BAR_Y + 27, 130, 38, (40, 120, 80), mpos)
        btn(screen, "Clear", 550, BAR_Y + 27, 110, 38, C_DANGER, mpos)
        btn(screen, "Menu [Esc]", 710, BAR_Y + 27, 140, 38, C_DANGER, mpos)
        txt(screen, f"Objects: {len(objects)}", WIDTH - 200, BAR_Y + 10, 14, C_GRAY)
        gx_disp = int((mpos[0] + cam_x) // CELL)
        gy_disp = int((mpos[1] + cam_y) // CELL)
        txt(screen, f"Grid: ({gx_disp}, {gy_disp})", WIDTH - 200, BAR_Y + 28, 14, C_GRAY)
        txt(screen, f"Level: {level_name}", WIDTH - 200, BAR_Y + 46, 14, C_GRAY)
        txt(screen, "R/Q rotate  ·  [ and ] slowmo in test  ·  start pos can overlap", WIDTH // 2, 18, 14, C_GRAY, True)
        if msg_timer > 0:
            txt(screen, msg, WIDTH // 2, BAR_Y - 18, 18, C_PLAYER, True)
        pygame.display.flip()
        clock.tick(FPS)


def main():
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("Geometry Dash Temu")
    clock = pygame.time.Clock()
    ensure_dirs()
    if not list_levels():
        create_tutorial()
    state = "menu"
    while state != "quit":
        if state == "menu":
            state = run_menu(screen, clock)
        elif state == "play":
            path = run_select(screen, clock)
            if path:
                name, objs = load_level(path)
                run_play(screen, clock, objs, name)
            state = "menu"
        elif state == "editor":
            run_editor(screen, clock)
            state = "menu"
    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
