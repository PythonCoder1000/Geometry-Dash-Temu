#!/usr/bin/env python3
"""Tests for Geometry Dash Temu game logic."""

import os
import sys
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"

import pygame
pygame.init()
screen = pygame.display.set_mode((1, 1))

from main import (
    Player, Bot, SpatialGrid, Particles,
    T_BLOCK, T_SPIKE, T_HALF_SPIKE, T_ORB, T_DASH_ORB, T_PAD, T_GRAV,
    T_END, T_MODE_SHIP, T_MODE_BALL, T_MODE_CUBE, T_START,
    T_SPEED_FAST, T_SPEED_SLOW, T_SPEED_NORMAL,
    CELL, PLAYER_SIZE, GROUND_Y, BASE_MOVE_SPEED,
    MODE_CUBE, MODE_SHIP, MODE_BALL,
    spike_hitboxes, pad_trigger_rect, cell_rect,
    normalize_rotation, flush_input, load_level, save_level, create_tutorial,
    ensure_dirs, list_levels, SpatialGrid, LEVELS_DIR,
)

passed = 0
failed = 0

def test(name, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def make_flat_level(width=30):
    """Create a simple flat level with ground blocks."""
    objs = [{"t": T_START, "x": 3, "y": 9, "r": 0}]
    for gx in range(width):
        objs.append({"t": T_BLOCK, "x": gx, "y": 10, "r": 0})
    objs.append({"t": T_END, "x": width - 2, "y": 9, "r": 0})
    return objs


# --- Player Spawning ---
print("\n=== Player Spawning ===")

objs = make_flat_level()
p = Player(objs)
test("Player spawns alive", p.alive)
test("Player spawns not won", not p.won)
test("Player starts in cube mode", p.mode == MODE_CUBE)
test("Player x near start object", abs(p.x - (3 * CELL + (CELL - PLAYER_SIZE) / 2)) < 1)
test("Player y near start object", abs(p.y - (9 * CELL + (CELL - PLAYER_SIZE) / 2)) < 1)
test("Player vertical velocity starts at 0", p.vy == 0.0)
test("Player gravity starts positive", p.grav == 1)


# --- Player Physics (Gravity) ---
print("\n=== Player Physics ===")

objs_no_ground = [{"t": T_START, "x": 3, "y": 5, "r": 0}]
p = Player(objs_no_ground)
initial_y = p.y
p.update(False, False)
test("Gravity pulls player down (vy increases)", p.vy > 0)
p.update(False, False)
test("Player falls when no ground", p.y > initial_y)

# Test ground collision
objs = make_flat_level()
p = Player(objs)
for _ in range(10):
    p.update(False, False)
test("Player lands on ground (on_ground)", p.on_ground)
test("Player alive on flat ground", p.alive)
ground_y = p.y
p.update(False, False)
test("Player stays on ground", abs(p.y - ground_y) < 2)


# --- Jumping ---
print("\n=== Jumping ===")

objs = make_flat_level()
p = Player(objs)
for _ in range(10):
    p.update(False, False)
test("On ground before jump", p.on_ground)
pre_jump_y = p.y
p.update(True, True)  # press jump
test("Player leaves ground after jump", not p.on_ground or p.vy < 0)
p.update(False, False)
test("Player moves up after jump", p.y < pre_jump_y)


# --- Player moves forward ---
print("\n=== Forward Movement ===")

objs = make_flat_level(60)
p = Player(objs)
initial_x = p.x
for _ in range(30):
    p.update(False, False)
test("Player moves right over time", p.x > initial_x)
test("Player moves at base speed", p.x > initial_x + 100)


# --- Spike Death ---
print("\n=== Spike Death ===")

objs = [{"t": T_START, "x": 0, "y": 9, "r": 0}]
for gx in range(20):
    objs.append({"t": T_BLOCK, "x": gx, "y": 10, "r": 0})
objs.append({"t": T_SPIKE, "x": 5, "y": 9, "r": 0})
p = Player(objs)
for _ in range(200):
    if not p.alive:
        break
    p.update(False, False)
test("Player dies on spike", not p.alive)


# --- Pad Auto-Jump ---
print("\n=== Pad Auto-Jump ===")

objs = [{"t": T_START, "x": 0, "y": 9, "r": 0}]
for gx in range(30):
    objs.append({"t": T_BLOCK, "x": gx, "y": 10, "r": 0})
objs.append({"t": T_PAD, "x": 5, "y": 9, "r": 0})
p = Player(objs)
hit_pad = False
for _ in range(200):
    if not p.alive:
        break
    old_vy = p.vy
    p.update(False, False)
    if p.vy < old_vy - 10:
        hit_pad = True
        break
test("Pad activates auto-jump", hit_pad)


# --- Orb Interaction (needs input) ---
print("\n=== Orb Interaction ===")

objs = [{"t": T_START, "x": 0, "y": 9, "r": 0}]
for gx in range(30):
    objs.append({"t": T_BLOCK, "x": gx, "y": 10, "r": 0})
objs.append({"t": T_ORB, "x": 5, "y": 8, "r": 0})
p = Player(objs)
orb_activated = False
for i in range(200):
    if not p.alive:
        break
    near_orb = abs(p.x / CELL - 5) < 2
    p.update(near_orb, near_orb)
    if (T_ORB, 5, 8) in p.passed:
        orb_activated = True
        break
test("Orb activates with input", orb_activated)

# Orb should NOT activate without input
objs2 = [{"t": T_START, "x": 0, "y": 9, "r": 0}]
for gx in range(30):
    objs2.append({"t": T_BLOCK, "x": gx, "y": 10, "r": 0})
objs2.append({"t": T_ORB, "x": 5, "y": 8, "r": 0})
p2 = Player(objs2)
for _ in range(200):
    if not p2.alive:
        break
    p2.update(False, False)
test("Orb does NOT activate without input", (T_ORB, 5, 8) not in p2.passed)


# --- Gravity Portal ---
print("\n=== Gravity Portal ===")

objs = [{"t": T_START, "x": 0, "y": 9, "r": 0}]
for gx in range(30):
    objs.append({"t": T_BLOCK, "x": gx, "y": 10, "r": 0})
    objs.append({"t": T_BLOCK, "x": gx, "y": 3, "r": 0})
objs.append({"t": T_GRAV, "x": 5, "y": 9, "r": 0})
p = Player(objs)
test("Gravity starts positive", p.grav == 1)
for _ in range(200):
    if (T_GRAV, 5, 9) in p.passed:
        break
    p.update(False, False)
test("Gravity flips after portal", p.grav == -1)


# --- Mode Portals ---
print("\n=== Mode Portals ===")

objs = [{"t": T_START, "x": 0, "y": 9, "r": 0}]
for gx in range(30):
    objs.append({"t": T_BLOCK, "x": gx, "y": 10, "r": 0})
objs.append({"t": T_MODE_SHIP, "x": 5, "y": 9, "r": 0})
p = Player(objs)
test("Starts in cube mode", p.mode == MODE_CUBE)
for _ in range(200):
    if p.mode != MODE_CUBE:
        break
    p.update(False, False)
test("Switches to ship mode", p.mode == MODE_SHIP)


# --- Speed Portals ---
print("\n=== Speed Portals ===")

objs = [{"t": T_START, "x": 0, "y": 9, "r": 0}]
for gx in range(30):
    objs.append({"t": T_BLOCK, "x": gx, "y": 10, "r": 0})
objs.append({"t": T_SPEED_FAST, "x": 5, "y": 9, "r": 0})
p = Player(objs)
test("Starts at base speed", p.move_speed == BASE_MOVE_SPEED)
for _ in range(200):
    if p.move_speed != BASE_MOVE_SPEED:
        break
    p.update(False, False)
test("Speed changes after portal", p.move_speed == 6.7)


# --- Level Completion ---
print("\n=== Level Completion ===")

objs = make_flat_level(20)
p = Player(objs)
for _ in range(600):
    if p.won:
        break
    p.update(False, False)
test("Player reaches end and wins", p.won)


# --- Player Reset ---
print("\n=== Player Reset ===")

objs = make_flat_level()
p = Player(objs)
for _ in range(30):
    p.update(True, True)
p.alive = False
old_x = p.x
p.reset()
test("Reset restores alive state", p.alive)
test("Reset clears won state", not p.won)
test("Reset moves player to spawn", p.x < old_x)
test("Reset clears velocity", p.vy == 0.0)
test("Reset clears passed set", len(p.passed) == 0)


# --- SpatialGrid ---
print("\n=== SpatialGrid ===")

objs = make_flat_level()
grid = SpatialGrid(objs)
blocks = grid.query_rect(0, 5, 10, 10)
test("SpatialGrid finds blocks in range", len(blocks) == 6)
empty = grid.query_rect(100, 110, 100, 110)
test("SpatialGrid returns empty for out of range", len(empty) == 0)
start = grid.query_rect(3, 3, 9, 9)
test("SpatialGrid finds start object", any(o["t"] == T_START for o in start))


# --- Bot ---
print("\n=== Bot ===")

# Bot on flat ground with no obstacles should not jump
objs = make_flat_level(60)
p = Player(objs)
for _ in range(10):
    p.update(False, False)
bot = Bot(objs)
hold, press = bot.decide(p)
test("Bot doesn't jump on safe flat ground", not press)

# Bot facing a spike should jump
objs_spike = [{"t": T_START, "x": 0, "y": 9, "r": 0}]
for gx in range(30):
    objs_spike.append({"t": T_BLOCK, "x": gx, "y": 10, "r": 0})
objs_spike.append({"t": T_SPIKE, "x": 6, "y": 9, "r": 0})
objs_spike.append({"t": T_END, "x": 25, "y": 9, "r": 0})
p = Player(objs_spike)
bot = Bot(objs_spike)
jumped = False
for _ in range(200):
    if not p.alive or p.won:
        break
    hold, press = bot.decide(p)
    if press:
        jumped = True
    p.update(hold, press)
test("Bot jumps to avoid spike", jumped)
test("Bot survives the spike", p.alive)

# Bot should complete a simple flat level
objs_simple = make_flat_level(40)
p = Player(objs_simple)
bot = Bot(objs_simple)
for _ in range(1000):
    if p.won or not p.alive:
        break
    hold, press = bot.decide(p)
    p.update(hold, press)
test("Bot completes flat level", p.won)

# Bot on dead player should return no action
objs = make_flat_level()
p = Player(objs)
p.alive = False
bot = Bot(objs)
hold, press = bot.decide(p)
test("Bot returns no action for dead player", not hold and not press)


# --- Spike Hitbox Rotation ---
print("\n=== Spike Hitboxes ===")

boxes_0 = spike_hitboxes(0, 0, 0)
test("Spike hitbox at rotation 0 exists", len(boxes_0) == 2)

boxes_90 = spike_hitboxes(0, 0, 90)
test("Spike hitbox at rotation 90 exists", len(boxes_90) == 2)

boxes_half = spike_hitboxes(0, 0, 0, half=True)
test("Half-spike hitbox exists", len(boxes_half) == 2)


# --- Normalize Rotation ---
print("\n=== Normalize Rotation ===")

test("0 stays 0", normalize_rotation(0) == 0)
test("90 stays 90", normalize_rotation(90) == 90)
test("360 becomes 0", normalize_rotation(360) == 0)
test("-90 becomes 270", normalize_rotation(-90) == 270)
test("45 rounds to 0", normalize_rotation(45) == 0)
test("135 rounds to 180 (banker's rounding)", normalize_rotation(135) == 180)


# --- Particles ---
print("\n=== Particles ===")

particles = Particles()
particles.burst(100, 100, (255, 0, 0), 10)
test("Particles created on burst", len(particles.ps) == 10)
for _ in range(100):
    particles.update()
test("Particles decay over time", len(particles.ps) == 0)


# --- Wall Death ---
print("\n=== Wall Collision ===")

objs = [{"t": T_START, "x": 0, "y": 9, "r": 0}]
for gx in range(10):
    objs.append({"t": T_BLOCK, "x": gx, "y": 10, "r": 0})
# Place a wall directly in front
objs.append({"t": T_BLOCK, "x": 4, "y": 9, "r": 0})
objs.append({"t": T_BLOCK, "x": 4, "y": 8, "r": 0})
p = Player(objs)
for _ in range(200):
    if not p.alive:
        break
    p.update(False, False)
test("Player dies on wall collision", not p.alive)


# --- Out of Bounds Death ---
print("\n=== Out of Bounds ===")

objs = [{"t": T_START, "x": 0, "y": 5, "r": 0}]
# No ground - player falls forever
p = Player(objs)
for _ in range(500):
    if not p.alive:
        break
    p.update(False, False)
test("Player dies when falling out of bounds", not p.alive)


# --- Dash Orb ---
print("\n=== Dash Orb ===")

objs = [{"t": T_START, "x": 0, "y": 9, "r": 0}]
for gx in range(40):
    objs.append({"t": T_BLOCK, "x": gx, "y": 10, "r": 0})
objs.append({"t": T_DASH_ORB, "x": 5, "y": 8, "r": 0})
objs.append({"t": T_END, "x": 35, "y": 9, "r": 0})
p = Player(objs)
dash_activated = False
for i in range(300):
    if not p.alive or p.won:
        break
    near_orb = abs(p.x / CELL - 5) < 2
    p.update(near_orb, near_orb)
    if p.dash_timer > 0:
        dash_activated = True
test("Dash orb activates dash timer", dash_activated)


# --- Level I/O ---
print("\n=== Level I/O ===")

ensure_dirs()
test_objs = [{"t": T_BLOCK, "x": 0, "y": 10, "r": 0}, {"t": T_START, "x": 1, "y": 9, "r": 0}]
save_level(test_objs, "Test Level", "__test_io")
test("Level file saved", os.path.exists(os.path.join("levels", "__test_io.json")))
name, loaded = load_level(os.path.join("levels", "__test_io.json"))
test("Level name loaded correctly", name == "Test Level")
test("Level objects loaded", len(loaded) == 2)
os.remove(os.path.join("levels", "__test_io.json"))


# --- flush_input ---
print("\n=== flush_input ===")

# Just verify it doesn't crash
flush_input()
test("flush_input runs without error", True)


# --- Bot with multiple obstacles ---
print("\n=== Bot Complex Scenario ===")

objs_complex = [{"t": T_START, "x": 0, "y": 9, "r": 0}]
for gx in range(50):
    objs_complex.append({"t": T_BLOCK, "x": gx, "y": 10, "r": 0})
# Two spikes with gaps
objs_complex.append({"t": T_SPIKE, "x": 6, "y": 9, "r": 0})
objs_complex.append({"t": T_SPIKE, "x": 14, "y": 9, "r": 0})
objs_complex.append({"t": T_END, "x": 45, "y": 9, "r": 0})
p = Player(objs_complex)
bot = Bot(objs_complex)
for _ in range(2000):
    if p.won or not p.alive:
        break
    hold, press = bot.decide(p)
    p.update(hold, press)
test("Bot navigates two spikes", p.alive)
test("Bot completes two-spike level", p.won)


# --- Bot with gap in ground ---
print("\n=== Bot Gap Navigation ===")

objs_gap = [{"t": T_START, "x": 0, "y": 9, "r": 0}]
for gx in range(50):
    if gx < 8 or gx > 10:  # Gap from grid 8-10
        objs_gap.append({"t": T_BLOCK, "x": gx, "y": 10, "r": 0})
objs_gap.append({"t": T_END, "x": 45, "y": 9, "r": 0})
p = Player(objs_gap)
bot = Bot(objs_gap)
for _ in range(2000):
    if p.won or not p.alive:
        break
    hold, press = bot.decide(p)
    p.update(hold, press)
test("Bot jumps over gap", p.alive)
test("Bot completes gap level", p.won)


# --- Bot with pad ---
print("\n=== Bot with Pad ===")

objs_pad = [{"t": T_START, "x": 0, "y": 9, "r": 0}]
for gx in range(50):
    objs_pad.append({"t": T_BLOCK, "x": gx, "y": 10, "r": 0})
objs_pad.append({"t": T_PAD, "x": 8, "y": 9, "r": 0})
objs_pad.append({"t": T_END, "x": 45, "y": 9, "r": 0})
p = Player(objs_pad)
bot = Bot(objs_pad)
for _ in range(2000):
    if p.won or not p.alive:
        break
    hold, press = bot.decide(p)
    p.update(hold, press)
test("Bot survives pad activation", p.alive)
test("Bot completes level with pad", p.won)


# --- Bot with three spikes ---
print("\n=== Bot Three Spikes ===")

objs_3s = [{"t": T_START, "x": 0, "y": 9, "r": 0}]
for gx in range(60):
    objs_3s.append({"t": T_BLOCK, "x": gx, "y": 10, "r": 0})
objs_3s.append({"t": T_SPIKE, "x": 6, "y": 9, "r": 0})
objs_3s.append({"t": T_SPIKE, "x": 14, "y": 9, "r": 0})
objs_3s.append({"t": T_SPIKE, "x": 22, "y": 9, "r": 0})
objs_3s.append({"t": T_END, "x": 55, "y": 9, "r": 0})
p = Player(objs_3s)
bot = Bot(objs_3s)
for _ in range(3000):
    if p.won or not p.alive:
        break
    hold, press = bot.decide(p)
    p.update(hold, press)
test("Bot navigates three spikes", p.alive)
test("Bot completes three-spike level", p.won)


# --- Bot Tutorial Level ---
print("\n=== Bot Tutorial Completion ===")
create_tutorial()
_tname, t_objs = load_level(os.path.join(LEVELS_DIR, "tutorial.json"))
tp = Player(t_objs)
tbot = Bot(t_objs)
for _ in range(5000):
    if tp.won or not tp.alive:
        break
    hold, press = tbot.decide(tp)
    tp.update(hold, press)
test("Bot completes tutorial level", tp.won)
test("Bot alive after tutorial", tp.alive)


# --- Summary ---
print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed out of {passed + failed}")
if failed:
    sys.exit(1)
else:
    print("All tests passed!")
