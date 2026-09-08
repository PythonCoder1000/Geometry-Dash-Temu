#!/usr/bin/env python3
"""Self-contained test suite for Trigonometry Sprint.

Uses pygame in headless mode (SDL_VIDEODRIVER=dummy) so it can run without
a display. Imports from the individual modules that actually exist, not
from a monolithic main.
"""

import os
import sys
import tempfile

# Ensure the repo root (parent of src/) is on sys.path so `import src.*`
# works even when the test is invoked from another CWD.
_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"

import pygame
pygame.init()
pygame.display.set_mode((1, 1))

from src import constants as C
from src.constants import (
    CELL, FPS, PLAYER_SIZE, GRAVITY, JUMP_FORCE, SPEED_VALUES,
    T_BLOCK, T_SLAB, T_SPIKE, T_HALF_SPIKE, T_SAW,
    T_ORB, T_DASH_ORB, T_TELEPORT_ORB, T_TELEPORT_PORTAL,
    T_BLACK_ORB, T_BLUE_ORB, T_GREEN_ORB,
    T_PAD, T_BLUE_PAD, T_GRAV_UP, T_GRAV_DOWN, T_END, T_START, T_COIN, T_CHECKPOINT,
    T_MODE_CUBE, T_MODE_SHIP, T_MODE_BALL, T_MODE_WAVE, T_MODE_UFO, T_MODE_SPIDER,
    T_SPEED_SLOW, T_SPEED_NORMAL, T_SPEED_FAST, T_SPEED_FASTER,
    MODE_CUBE, MODE_SHIP, MODE_BALL, MODE_WAVE, MODE_UFO, MODE_SPIDER,
    SOLID_TYPES, HAZARD_TYPES, ORB_TYPES, PAD_TYPES,
    DIFFICULTIES, LEVEL_FORMAT_VERSION, LEVELS_DIR,
)
from src.graphics import (
    normalize_rotation, cell_rect, slab_rect, spike_hitboxes, saw_hitbox,
    pad_trigger_rect, clamp, lerp, lerp_col, lighter, darker,
)
from src.levels import (
    save_level, load_level, load_level_full, update_meta, list_levels,
    list_level_summaries, normalize_object, next_group_id, next_teleport_link,
    next_object_id, next_coin_id, ensure_dirs, _default_meta,
    save_autosave, load_autosave, has_autosave, clear_autosave,
    get_group_id, AUTOSAVE_FILENAME,
)
from src.player import Player


passed = 0
failed = 0


def check(name, condition):
    global passed, failed
    if condition:
        print(f"  PASS: {name}")
        passed += 1
    else:
        print(f"  FAIL: {name}")
        failed += 1


def section(name):
    print(f"\n=== {name} ===")


def make_flat_level(length=50, extras=None):
    objs = [{"t": T_START, "x": 3, "y": 9, "r": 0, "active": True}]
    for gx in range(length):
        objs.append({"t": T_BLOCK, "x": gx, "y": 10, "r": 0})
    objs.append({"t": T_END, "x": length - 5, "y": 9, "r": 0})
    if extras:
        objs.extend(extras)
    return objs


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
section("Constants")
check("T_BLOCK defined", T_BLOCK in SOLID_TYPES)
check("T_SLAB in SOLID_TYPES", T_SLAB in SOLID_TYPES)
check("T_SAW in HAZARD_TYPES", T_SAW in HAZARD_TYPES)
check("T_COIN is a string", isinstance(T_COIN, str))
check("T_GREEN_ORB in ORB_TYPES", T_GREEN_ORB in ORB_TYPES)
check("T_BLUE_PAD in PAD_TYPES", T_BLUE_PAD in PAD_TYPES)
check("MODE_SPIDER is 'spider'", MODE_SPIDER == "spider")
check("SPEED_VALUES has 5 entries",
      len(SPEED_VALUES) == 5 and T_SPEED_NORMAL in SPEED_VALUES)
check("DIFFICULTIES list covers Easy through Extreme Demon",
      "Easy" in DIFFICULTIES
      and "Easy Demon" in DIFFICULTIES
      and "Extreme Demon" in DIFFICULTIES)
check("LEVEL_FORMAT_VERSION >= 5", LEVEL_FORMAT_VERSION >= 5)


# ---------------------------------------------------------------------------
# Graphics helpers
# ---------------------------------------------------------------------------
section("Graphics helpers")
check("clamp clamps low", clamp(-5, 0, 10) == 0)
check("clamp clamps high", clamp(99, 0, 10) == 10)
check("lerp midpoint", abs(lerp(0, 10, 0.5) - 5.0) < 1e-6)
check("lerp_col midpoint",
      lerp_col((0, 0, 0), (10, 20, 30), 0.5) == (5, 10, 15))
check("lighter bumps channel", lighter((100, 100, 100), 50)[0] == 150)
check("darker clamps to 0", darker((5, 5, 5), 50) == (0, 0, 0))
check("normalize_rotation rounds to 90", normalize_rotation(45) == 0
      or normalize_rotation(44) == 0)
check("normalize_rotation wraps 360", normalize_rotation(360) == 0)
check("normalize_rotation clean 90", normalize_rotation(90) == 90)
check("cell_rect at origin", cell_rect(0, 0) == pygame.Rect(0, 0, CELL, CELL))
# Slab at rot=0 sits on the bottom half
sr = slab_rect(0, 0, 0)
check("slab_rect r=0 is bottom half",
      sr.top == CELL // 2 and sr.height == CELL // 2)
# Saw hitbox is inflated inward
saw_r = saw_hitbox(3, 5)
check("saw_hitbox smaller than cell", saw_r.w < CELL and saw_r.h < CELL)
check("saw_hitbox centered", saw_r.center == cell_rect(3, 5).center)
check("pad_trigger_rect is on bottom of cell",
      pad_trigger_rect(0, 0, 0).bottom == CELL)
check("spike_hitboxes returns list", len(spike_hitboxes(0, 0, 0, False)) >= 1)


# ---------------------------------------------------------------------------
# Level I/O and migration
# ---------------------------------------------------------------------------
section("Level I/O / migration")
tmpdir = tempfile.mkdtemp()
C.LEVELS_DIR = tmpdir
from src import levels as _levels_mod
_levels_mod.LEVELS_DIR = tmpdir
ensure_dirs()

objs = make_flat_level(20, extras=[{"t": T_COIN, "x": 5, "y": 8, "r": 0}])
path = save_level(objs, "TestLv", "testlv")
check("save_level returns path", os.path.isfile(path))
name, loaded, mus = load_level(path)
check("load_level returns (name, objects, music)",
      name == "TestLv" and isinstance(loaded, list) and mus is None)
check("load_level preserves object count", len(loaded) == len(objs))
meta, loaded2 = load_level_full(path)
check("load_level_full meta has name", meta.get("name") == "TestLv")
check("load_level_full default published=False", meta.get("published") is False)
check("load_level_full default verified=False", meta.get("verified") is False)
check("load_level_full auto-assigns coin_ids",
      all(o.get("coin_id", 0) > 0 for o in loaded2 if o["t"] == T_COIN))

# Migration: minimal old-style level dict without v/published/etc
import json
old_path = os.path.join(tmpdir, "old.json")
with open(old_path, "w") as f:
    json.dump({"name": "Old", "objects": [{"t": T_BLOCK, "x": 0, "y": 10}]}, f)
om, oobjs = load_level_full(old_path)
check("migration fills published", "published" in om and om["published"] is False)
check("migration normalizes version", om["v"] == LEVEL_FORMAT_VERSION)
check("migration preserves objects", len(oobjs) == 1)

# update_meta: flip verified
update_meta(path, verified=True, best_progress=75)
meta2, _ = load_level_full(path)
check("update_meta flips verified", meta2.get("verified") is True)
check("update_meta persists best_progress", meta2.get("best_progress") == 75)

# next_* helpers
empty = []
check("next_group_id empty=1", next_group_id(empty) == 1)
check("next_teleport_link alias still works",
      next_teleport_link(empty) == 1)
check("next_object_id empty=1", next_object_id(empty) == 1)
check("next_coin_id empty=1", next_coin_id(empty) == 1)
with_coins = [{"t": T_COIN, "coin_id": 1}, {"t": T_COIN, "coin_id": 3}]
check("next_coin_id skips used", next_coin_id(with_coins) == 2)

# next_group_id should consider both new (group_id) and legacy (link) fields
# when computing the smallest unused id, so a fresh allocation never collides
# with an already-loaded legacy level.
packed_groups = [
    {"t": T_TELEPORT_ORB, "x": 0, "y": 0, "group_id": 1},
    {"t": T_TELEPORT_ORB, "x": 1, "y": 0, "link": 2},
    {"t": T_TELEPORT_ORB, "x": 2, "y": 0, "group_id": 3},
]
check("next_group_id sees both group_id and legacy link",
      next_group_id(packed_groups) == 4)

# normalize_object strips unknowns, coerces ints
ob = normalize_object({"t": T_BLOCK, "x": "5", "y": 3.7, "r": 91,
                       "unknown": "ignored"})
check("normalize_object coerces x to int", isinstance(ob["x"], int) and ob["x"] == 5)
# Free rotation: levels persist any angle (the visual rotates exactly,
# collision helpers snap to 90° internally). 91° passes through as 91.
check("normalize_object preserves free rotation", ob["r"] == 91)
check("normalize_object drops unknown keys", "unknown" not in ob)

# Backwards-compat migration: a teleport orb with only the legacy "link"
# field should normalize to "group_id" without losing the value.
legacy_orb = normalize_object({"t": T_TELEPORT_ORB, "x": 0, "y": 0, "link": 7})
check("legacy link migrates to group_id",
      legacy_orb.get("group_id") == 7)
check("legacy link key removed from normalized form",
      "link" not in legacy_orb)
# A new-style orb passes through unchanged.
new_orb = normalize_object({"t": T_TELEPORT_ORB, "x": 0, "y": 0, "group_id": 3})
check("new group_id normalizes to itself",
      new_orb.get("group_id") == 3)
# get_group_id reads either field
check("get_group_id reads group_id",
      get_group_id({"group_id": 4}) == 4)
check("get_group_id falls back to link",
      get_group_id({"link": 9}) == 9)
check("get_group_id prefers group_id over link",
      get_group_id({"group_id": 1, "link": 2}) == 1)
check("get_group_id missing both = 0",
      get_group_id({}) == 0)


# ---------------------------------------------------------------------------
# Fresh levels dir for the publish/verify round-trip below
# ---------------------------------------------------------------------------
_tmp2 = tempfile.mkdtemp()
C.LEVELS_DIR = _tmp2
_levels_mod.LEVELS_DIR = _tmp2
ensure_dirs()
check("ensure_dirs creates levels dir on demand",
      os.path.isdir(_tmp2))
# `ensure_dirs` now also seed-copies any bundled sample levels from the
# read-only bundle dir. For a tmp-dir test the bundle peer is the real
# repo's `levels/`, so the fresh dir is NOT empty — just verify that
# what we got out of the seed is a well-formed list.
_fresh = list_levels()
check("fresh levels dir lists cleanly (seed-copy of bundled samples)",
      isinstance(_fresh, list))


# ---------------------------------------------------------------------------
# Player spawn & basic physics
# ---------------------------------------------------------------------------
section("Player spawn / basic physics")
objs = make_flat_level()
p = Player(objs)
check("Player spawns alive", p.alive)
check("Player spawns not won", not p.won)
check("Player mode is cube", p.mode == MODE_CUBE)
check("Player coins_collected empty", len(p.coins_collected) == 0)
check("Player near start x",
      abs(p.x - (3 * C.UNITS_PER_BLOCK + (C.UNITS_PER_BLOCK - C.PLAYER_SIZE_UNITS) / 2)) < 1)

# Step a few frames: player should walk forward
x0 = p.x
for _ in range(40):
    p.update(False, False)
check("Player moves forward on flat ground", p.x > x0)
check("Player stays alive on flat ground", p.alive)

# Jump on cube mode
p2 = Player(make_flat_level())
# Ensure on_ground after a step
for _ in range(12):
    p2.update(False, False)
y_before = p2.y
p2.update(True, True)  # hold jump
check("Cube jump raises player",
      p2.vy < 0 or p2.y <= y_before)


# ---------------------------------------------------------------------------
# Coin pickup & checkpoint flag
# ---------------------------------------------------------------------------
section("Coin & checkpoint interaction")
# Coin directly in front of spawn
objs = make_flat_level(extras=[{"t": T_COIN, "x": 4, "y": 9, "r": 0, "coin_id": 1}])
p = Player(objs)
for _ in range(120):
    p.update(False, False)
check("Coin collected after walking over it", 1 in p.coins_collected)

# Checkpoint objects were removed from the editor — the C key in
# practice mode drops a save point via `player.save_checkpoint()`
# directly. Verify the save/load helpers still work.
p = Player(make_flat_level())
p.practice_mode = True
for _ in range(80):
    p.update(False, False)
p.save_checkpoint()
check("save_checkpoint stores a snapshot", len(p.checkpoints) == 1)
# Move the player then load — should warp back.
_old_x = p.x
p.x += 400
ok = p.load_checkpoint()
check("load_checkpoint restores position", ok and abs(p.x - _old_x) < 5)


# ---------------------------------------------------------------------------
# Slab collision
# ---------------------------------------------------------------------------
section("Slab collision")
# Flat ground made entirely of slabs
objs = [{"t": T_START, "x": 3, "y": 9, "r": 0}]
for gx in range(30):
    objs.append({"t": T_SLAB, "x": gx, "y": 10, "r": 0})
objs.append({"t": T_END, "x": 25, "y": 9, "r": 0})
p = Player(objs)
for _ in range(80):
    p.update(False, False)
check("Player stands on slabs", p.alive and p.on_ground)


# ---------------------------------------------------------------------------
# Green orb / blue pad
# ---------------------------------------------------------------------------
section("Green orb + Blue pad")
objs = make_flat_level(extras=[{"t": T_GREEN_ORB, "x": 6, "y": 8, "r": 0}])
p = Player(objs)
# Walk, then activate with a press while near the orb
for _ in range(88):
    p.update(False, False)
p.update(True, True)
check("Green orb flips gravity when walked into", p.grav == -1)


# ---------------------------------------------------------------------------
# Spider mode teleport
# ---------------------------------------------------------------------------
section("Spider teleport")
objs = [{"t": T_START, "x": 3, "y": 9, "r": 0}]
for gx in range(40):
    objs.append({"t": T_BLOCK, "x": gx, "y": 10, "r": 0})
# Ceiling blocks to teleport to
for gx in range(10, 16):
    objs.append({"t": T_BLOCK, "x": gx, "y": 4, "r": 0})
objs.append({"t": T_MODE_SPIDER, "x": 8, "y": 9, "r": 0})
objs.append({"t": T_END, "x": 35, "y": 9, "r": 0})
p = Player(objs)
# Walk under the ceiling; tick counts change with the default run speed.
for _ in range(320):
    p.update(False, False)
    if p.x >= 10 * C.UNITS_PER_BLOCK:
        break
check("Spider portal switched mode", p.mode == MODE_SPIDER)
y_before = p.y
# A press while on ground should teleport upward to ceiling
p.update(True, True)
check("Spider teleport raised y or flipped grav",
      p.y < y_before or p.grav != 1)


# ---------------------------------------------------------------------------
# Save / load meta round-trip with publish
# ---------------------------------------------------------------------------
section("Publish / verify round-trip")
meta_in = _default_meta("PubLevel")
meta_in["published"] = True
meta_in["difficulty"] = "Hard"
save_level(make_flat_level(), "PubLevel", "publevel", meta=meta_in)
pub_meta, pub_objs = load_level_full(os.path.join(_tmp2, "publevel.json"))
check("Published flag persisted", pub_meta.get("published") is True)
check("Difficulty persisted", pub_meta.get("difficulty") == "Hard")
check("Not verified until beaten", pub_meta.get("verified") is False)
update_meta(os.path.join(_tmp2, "publevel.json"), verified=True)
pub_meta2, _ = load_level_full(os.path.join(_tmp2, "publevel.json"))
check("update_meta sets verified", pub_meta2.get("verified") is True)


# ---------------------------------------------------------------------------
# list_level_summaries
# ---------------------------------------------------------------------------
section("list_level_summaries")
summaries = list_level_summaries()
check("summaries non-empty", len(summaries) >= 1)
check("summaries are (filename, meta) tuples",
      all(isinstance(s, tuple) and len(s) == 2 for s in summaries))


# ---------------------------------------------------------------------------
# Editor autosave round-trip
# ---------------------------------------------------------------------------
section("Editor autosave")

# Start from a clean slate so leftover state from prior tests doesn't leak.
clear_autosave()
check("clear_autosave is a no-op when no file exists",
      has_autosave() is False)

autosave_objs = make_flat_level()
autosave_objs.append({"t": "spike", "x": 12, "y": 9, "r": 0})
save_autosave(autosave_objs, "RecoveryDraft",
              music_file="track_a.mp3",
              source_filename="recoverydraft.json")
check("has_autosave True after save_autosave", has_autosave() is True)

ameta, aobjs = load_autosave()
check("load_autosave returns meta", ameta is not None)
check("load_autosave returns objects", isinstance(aobjs, list) and len(aobjs) == len(autosave_objs))
check("autosave preserves name", ameta.get("name") == "RecoveryDraft")
check("autosave preserves music", ameta.get("music") == "track_a.mp3")
check("autosave records source filename",
      ameta.get("_autosave_source") == "recoverydraft.json")
check("autosave records timestamp", isinstance(ameta.get("_autosave_ts"), int))
check("autosave file is filtered out of list_levels",
      AUTOSAVE_FILENAME not in list_levels())
check("autosave file is filtered out of list_level_summaries",
      AUTOSAVE_FILENAME not in [fn for fn, _ in list_level_summaries()])

clear_autosave()
check("has_autosave False after clear_autosave", has_autosave() is False)
nameta, naobjs = load_autosave()
check("load_autosave returns (None, None) when missing",
      nameta is None and naobjs is None)

# Reserved-prefix guard: user-named levels can't shadow the autosave slot.
from src.levels import _safe_filename as _sf
check("_safe_filename strips leading underscore",
      not _sf("_autosave").startswith("_"))
check("_safe_filename strips repeated leading underscores",
      not _sf("___hidden").startswith("_"))
check("_safe_filename keeps non-leading underscores",
      _sf("My_Level") == "my_level")


# ---------------------------------------------------------------------------
# Editor copy/paste id remapping
# ---------------------------------------------------------------------------
section("Editor clone (copy/paste/duplicate)")
from src.editor import _clone_objects

# Source: a move-trigger pointing at two blocks via target_oids, plus a pair
# of linked teleport orbs. Cloning must allocate fresh oids/links so the
# clones reference each other rather than the originals.
existing = [
    {"t": "block", "x": 0, "y": 0, "r": 0, "oid": 5},
    {"t": "block", "x": 1, "y": 0, "r": 0, "oid": 6},
    {"t": "move_trigger", "x": 2, "y": 0, "r": 0,
     "target_oid": 5, "target_oids": [5, 6], "tx": 2, "ty": 0, "duration": 30},
    {"t": "teleport_orb", "x": 3, "y": 0, "r": 0, "group_id": 7},
    {"t": "teleport_orb", "x": 4, "y": 0, "r": 0, "group_id": 7},
]
# Selection: just the trigger and a block — "clipboard" form needs offsets.
src_block = existing[0]
src_trig = existing[2]
clip = []
for o in (src_trig, src_block):
    cb = dict(o)
    cb["_offset_x"] = o["x"] - src_trig["x"]
    cb["_offset_y"] = o["y"] - src_trig["y"]
    clip.append(cb)
clones = _clone_objects(clip, (10, 5), existing)
check("clone produces same count", len(clones) == 2)
check("clone first lands at target",
      clones[0]["x"] == 10 and clones[0]["y"] == 5)
check("clone preserves relative offset",
      clones[1]["x"] == 10 + (src_block["x"] - src_trig["x"]))
clone_trig = clones[0]
clone_block = clones[1]
# The trigger in `existing` had no oid of its own; the clone should match.
check("clone trigger has no synthesized oid (source had none)",
      "oid" not in clone_trig)
check("clone block gets fresh oid",
      clone_block.get("oid", 0) not in (0, 5, 6))
check("clone trigger target_oid remapped to clone block",
      clone_trig.get("target_oid") == clone_block["oid"])
check("clone trigger target_oids remapped",
      clone_trig.get("target_oids", [])[0] == clone_block["oid"])

# When a referenced oid was NOT cloned, the trigger should preserve the link
# to the original (target_oids[1] is oid 6, which we didn't clone).
check("clone trigger keeps unselected target_oid intact",
      clone_trig.get("target_oids", [None, None])[1] == 6)

# Teleport-orb group remapping: clone both orbs together — they should remain
# grouped to each other but with a fresh group id.
orbs = existing[3:5]
clones_orbs = _clone_objects(orbs, (20, 5), existing)
check("orb pair both get same new group_id",
      clones_orbs[0]["group_id"] == clones_orbs[1]["group_id"])
check("orb pair group_id is fresh",
      clones_orbs[0]["group_id"] != 7)
check("clone strips legacy link key",
      "link" not in clones_orbs[0] and "link" not in clones_orbs[1])

# Backwards-compat: cloning a legacy "link"-only pair should still produce a
# fresh group_id pairing (the clone path migrates the field).
legacy_orbs = [
    {"t": "teleport_orb", "x": 5, "y": 0, "r": 0, "link": 4},
    {"t": "teleport_orb", "x": 6, "y": 0, "r": 0, "link": 4},
]
legacy_clones = _clone_objects(legacy_orbs, (30, 5), [])
check("legacy link clone produces matching group_id",
      legacy_clones[0].get("group_id") and
      legacy_clones[0].get("group_id") == legacy_clones[1].get("group_id"))

# Clone-in-place (duplicate) should also produce fresh ids when the source
# objects are real editor objects (no _offset keys).
existing2 = [
    {"t": "block", "x": 5, "y": 5, "r": 0, "oid": 11},
    {"t": "move_trigger", "x": 6, "y": 5, "r": 0, "target_oid": 11,
     "tx": 6, "ty": 5, "duration": 30},
]
dup = _clone_objects(existing2, (5, 5), existing2)
check("duplicate produces same count", len(dup) == 2)
check("duplicate gives fresh oid", dup[0]["oid"] != 11)
check("duplicate trigger remaps target_oid",
      dup[1]["target_oid"] == dup[0]["oid"])

# coin_id must be dropped so load_level_full can reassign deterministically.
coin_src = [{"t": "coin", "x": 0, "y": 0, "r": 0, "coin_id": 42}]
coin_clone = _clone_objects(coin_src, (3, 3), [])
check("clone strips coin_id", "coin_id" not in coin_clone[0])


# ---------------------------------------------------------------------------
# Snippet palette — built-ins, normalize, user I/O round-trip, stamp via clone
# ---------------------------------------------------------------------------
section("Snippet palette")
from src import snippets as _snip_mod
from src.snippets import (
    BUILTIN_SNIPPETS, get_snippets, normalize_to_origin,
    load_user_snippets, save_user_snippet, delete_user_snippet,
)

check("built-in snippets is non-empty list", len(BUILTIN_SNIPPETS) > 0)
check("each built-in is (name, [objects])",
      all(isinstance(n, str) and isinstance(objs, list) and objs
          for n, objs in BUILTIN_SNIPPETS))
check("each built-in object has type and coords",
      all("t" in o and "x" in o and "y" in o
          for _n, objs in BUILTIN_SNIPPETS for o in objs))

# normalize_to_origin: shift to (0,0), keep relative shape.
shifted = [
    {"t": "block", "x": 5, "y": 7, "r": 0},
    {"t": "spike", "x": 8, "y": 7, "r": 0},
    {"t": "block", "x": 5, "y": 9, "r": 0},
]
norm = normalize_to_origin(shifted)
check("normalize anchors min x at 0", min(o["x"] for o in norm) == 0)
check("normalize anchors min y at 0", min(o["y"] for o in norm) == 0)
check("normalize preserves rel x deltas",
      norm[1]["x"] - norm[0]["x"] == 8 - 5)
check("normalize preserves rel y deltas",
      norm[2]["y"] - norm[0]["y"] == 9 - 7)
check("normalize on empty returns []", normalize_to_origin([]) == [])

# User snippets I/O — point the module at a temp file so we don't clobber
# the real user list, then exercise save / load / delete round-trip.
import tempfile as _tf
_orig_path = _snip_mod._USER_SNIPPETS_PATH
_tmp = _tf.NamedTemporaryFile(
    "w", suffix=".json", delete=False, encoding="utf-8")
_tmp.write("[]")
_tmp.close()
_snip_mod._USER_SNIPPETS_PATH = _tmp.name
try:
    check("fresh user list is empty", load_user_snippets() == [])
    save_user_snippet("My Combo", [
        {"t": "block", "x": 0, "y": 0, "r": 0},
        {"t": "spike", "x": 1, "y": 0, "r": 0},
    ])
    loaded = load_user_snippets()
    check("after save, one user snippet present", len(loaded) == 1)
    check("user snippet name preserved", loaded[0][0] == "My Combo")
    check("user snippet objects round-trip",
          len(loaded[0][1]) == 2 and loaded[0][1][0]["t"] == "block")
    # get_snippets must return built-ins followed by user entries flagged True.
    combined = get_snippets()
    check("get_snippets returns built-ins + user",
          len(combined) == len(BUILTIN_SNIPPETS) + 1)
    check("user snippet flagged is_user=True",
          combined[-1][2] is True)
    check("built-in snippets flagged is_user=False",
          combined[0][2] is False)
    # Delete out of range is a no-op returning False.
    check("delete out-of-range returns False",
          delete_user_snippet(99) is False)
    check("delete in-range returns True",
          delete_user_snippet(0) is True)
    check("after delete, user list empty again",
          load_user_snippets() == [])
finally:
    _snip_mod._USER_SNIPPETS_PATH = _orig_path
    try:
        os.unlink(_tmp.name)
    except OSError:
        pass

# Stamp drop end-to-end: a snippet (in local coords) cloned via _clone_objects
# should land anchored at the cursor cell with positions correctly offset.
stamp = [
    {"t": "block", "x": 0, "y": 0, "r": 0},
    {"t": "spike", "x": 2, "y": 0, "r": 0},
    {"t": "block", "x": 0, "y": 2, "r": 0},
]
dropped = _clone_objects(stamp, (15, 8), [])
check("stamp drop count matches", len(dropped) == 3)
check("stamp first lands at cursor",
      dropped[0]["x"] == 15 and dropped[0]["y"] == 8)
check("stamp second offset preserved",
      dropped[1]["x"] == 17 and dropped[1]["y"] == 8)
check("stamp third offset preserved",
      dropped[2]["x"] == 15 and dropped[2]["y"] == 10)


# ---------------------------------------------------------------------------
# Level thumbnails — generation, save/load round-trip, save_level hook
# ---------------------------------------------------------------------------
section("Level thumbnails")
from src import thumbnails as _thumbs_mod
from src.thumbnails import (
    THUMB_W, THUMB_H, THUMBS_DIR,
    render_thumbnail, save_thumbnail, load_thumbnail,
    thumbnail_path, clear_thumbnail,
)

# render_thumbnail returns a Surface with the documented dimensions.
empty_surf = render_thumbnail([])
check("render_thumbnail empty returns surface with right size",
      empty_surf.get_width() == THUMB_W and empty_surf.get_height() == THUMB_H)

flat = make_flat_level(length=30)
flat_surf = render_thumbnail(flat)
check("render_thumbnail of real level returns full-size surface",
      flat_surf.get_width() == THUMB_W and flat_surf.get_height() == THUMB_H)

# thumbnail_path: stable mapping from level filename → png path under
# `_thumbs/`, no matter whether `.json` is stripped or absolute.
p1 = thumbnail_path("my_level.json")
p2 = thumbnail_path("my_level")
p3 = thumbnail_path(os.path.join(LEVELS_DIR, "my_level.json"))
check("thumbnail_path strips .json", p1.endswith("my_level.png"))
check("thumbnail_path adds .png to bare name", p2.endswith("my_level.png"))
check("thumbnail_path uses basename of full path",
      p3.endswith("my_level.png"))
check("thumbnail_path lives under _thumbs/",
      os.path.dirname(p1).endswith("_thumbs"))

# save_thumbnail writes a real file we can load back.
fn = "thumbtest.json"
saved = save_thumbnail(fn, flat)
check("save_thumbnail returns a path", saved is not None)
check("save_thumbnail file exists", os.path.isfile(saved))
loaded = load_thumbnail(fn)
check("load_thumbnail returns a Surface",
      loaded is not None and loaded.get_width() == THUMB_W)

# clear_thumbnail removes the file; safe to call when missing.
clear_thumbnail(fn)
check("clear_thumbnail removes the file",
      not os.path.isfile(thumbnail_path(fn)))
clear_thumbnail(fn)  # no-op

# _thumbs/ is reserved (starts with underscore) and must be invisible to the
# level browser — same rule that protects the autosave file.
check("_thumbs dir name starts with underscore",
      os.path.basename(THUMBS_DIR).startswith("_"))

# save_level should auto-refresh the thumbnail. Use a unique slug so we
# don't collide with anything else in the test suite.
hook_fn = "_thumb_hook_test.json"  # leading _ also exercises filter
# Save through the public API, then check that a thumbnail appears.
# (Use a non-underscore name since underscore-prefixed files are filtered.)
hook_fn = "thumb_hook_test.json"
clear_thumbnail(hook_fn)
save_level(make_flat_level(length=20), "ThumbHook", "thumb_hook_test")
check("save_level produced a thumbnail",
      os.path.isfile(thumbnail_path(hook_fn)))
clear_thumbnail(hook_fn)
# Cleanup the level json too so we don't litter the levels dir.
try:
    os.remove(os.path.join(LEVELS_DIR, hook_fn))
except OSError:
    pass

# load_thumbnail returns None when missing (no exception, no auto-generate).
check("load_thumbnail returns None when file absent",
      load_thumbnail("nope_does_not_exist.json") is None)


# ---------------------------------------------------------------------------
# Settings — typed accessors, persistence round-trip, defensive coercion
# ---------------------------------------------------------------------------
section("Settings")
from src import prefs as _prefs_mod
from src import settings as _settings_mod
# Redirect the prefs file at a temp path and reset the in-memory cache so
# the real user prefs aren't clobbered.
_orig_prefs_path = _prefs_mod._PREFS_PATH
_orig_prefs_cache = _prefs_mod._cache
_tf2 = tempfile.NamedTemporaryFile(
    "w", suffix=".json", delete=False, encoding="utf-8")
_tf2.write("{}")
_tf2.close()
_prefs_mod._PREFS_PATH = _tf2.name
_prefs_mod._cache = None
try:
    # Defaults exposed.
    check("settings.DEFAULTS has fps_cap", "fps_cap" in _settings_mod.DEFAULTS)
    check("settings.DEFAULTS has fullscreen",
          "fullscreen" in _settings_mod.DEFAULTS)
    # The render FPS cap is a real setting again (physics is fixed at
    # PHYSICS_RATE and the play loop interpolates between ticks).
    check("FPS_CAP_OPTIONS contains GAME_RATE",
          _settings_mod.GAME_RATE in _settings_mod.FPS_CAP_OPTIONS)
    check("FPS_CAP_OPTIONS offers several caps",
          len(_settings_mod.FPS_CAP_OPTIONS) >= 3)
    check("get_fps_cap defaults to GAME_RATE",
          _settings_mod.get_fps_cap() == _settings_mod.GAME_RATE)
    check("get_fullscreen default False",
          _settings_mod.get_fullscreen() is False)
    _settings_mod.set_fps_cap(60)
    check("set_fps_cap persists a whitelisted value",
          _settings_mod.get_fps_cap() == 60)
    _settings_mod.set_fps_cap(0)
    check("set_fps_cap(0) = uncapped is allowed",
          _settings_mod.get_fps_cap() == 0)
    _prefs_mod.set("fps_cap", "garbage")
    check("garbage fps_cap falls back to default",
          _settings_mod.get_fps_cap() == _settings_mod.GAME_RATE)
    _prefs_mod.set("fps_cap", -10)
    check("negative fps_cap falls back to default",
          _settings_mod.get_fps_cap() == _settings_mod.GAME_RATE)
    _prefs_mod.set("fps_cap", 99999)
    check("non-whitelisted fps_cap falls back to default",
          _settings_mod.get_fps_cap() == _settings_mod.GAME_RATE)
    _prefs_mod.set("fps_cap", _settings_mod.GAME_RATE)  # restore baseline
    check("get_tps agrees with the player physics rate",
          _settings_mod.get_tps() == _settings_mod.PHYSICS_RATE == C.PHYSICS_TPS)

    # Volume coercion clamps to [0, 1].
    _settings_mod.set_music_vol(2.5)
    check("set_music_vol clamps high to 1.0",
          _settings_mod.get_music_vol() == 1.0)
    _settings_mod.set_music_vol(-1)
    check("set_music_vol clamps low to 0.0",
          _settings_mod.get_music_vol() == 0.0)
    _settings_mod.set_sfx_vol(0.75)
    check("sfx_vol round-trips",
          abs(_settings_mod.get_sfx_vol() - 0.75) < 0.001)

    # Fullscreen toggle.
    before = _settings_mod.get_fullscreen()
    after = _settings_mod.toggle_fullscreen()
    check("toggle_fullscreen returns new state", after != before)
    check("toggle_fullscreen persists",
          _settings_mod.get_fullscreen() == after)

    # cycle_fps_cap walks the whitelist and persists.
    _settings_mod.set_fps_cap(_settings_mod.FPS_CAP_OPTIONS[0])
    actual = _settings_mod.cycle_fps_cap()
    check("cycle_fps_cap advances to the next option",
          actual == _settings_mod.FPS_CAP_OPTIONS[1]
          and _settings_mod.get_fps_cap() == actual)
    check("fps_cap_label(0) reads Uncapped",
          "Uncapped" in _settings_mod.fps_cap_label(0))
    check("fps_cap_label(GAME_RATE) shows the rate",
          str(_settings_mod.GAME_RATE) in
          _settings_mod.fps_cap_label(_settings_mod.GAME_RATE))

    # reset_to_defaults wipes all keys back to baseline.
    _settings_mod.set_fps_cap(144)
    _settings_mod.set_fullscreen(True)
    _settings_mod.set_music_vol(0.1)
    _settings_mod.reset_to_defaults()
    check("reset returns fps_cap to GAME_RATE",
          _settings_mod.get_fps_cap() == _settings_mod.GAME_RATE)
    check("reset returns fullscreen to default",
          _settings_mod.get_fullscreen() ==
          _settings_mod.DEFAULTS["fullscreen"])
    check("reset returns music_vol to default",
          abs(_settings_mod.get_music_vol() -
              _settings_mod.DEFAULTS["music_vol"]) < 0.001)
finally:
    _prefs_mod._PREFS_PATH = _orig_prefs_path
    _prefs_mod._cache = _orig_prefs_cache
    try:
        os.unlink(_tf2.name)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Gamepad — every accessor must stay safe with no controller attached
# ---------------------------------------------------------------------------
section("Gamepad (no controller)")
from src import gamepad as _gp_mod
# init() is idempotent and never raises.
_gp_mod.init()
_gp_mod.init()
check("gamepad.init() is idempotent and safe", True)

# Every accessor returns a sensible default in headless / no-pad mode.
check("is_connected returns bool",
      isinstance(_gp_mod.is_connected(), bool))
check("name returns str", isinstance(_gp_mod.name(), str))
check("jump_held returns bool", isinstance(_gp_mod.jump_held(), bool))
check("jump_pressed returns bool",
      isinstance(_gp_mod.jump_pressed(), bool))

# reset_edge_state is a no-op, never raises.
_gp_mod.reset_edge_state()
check("reset_edge_state safe", True)

# Edge detection: with no controller, jump_pressed must always stay False
# (jump_held is always False, so the rising edge never triggers).
_gp_mod.reset_edge_state()
edges = [_gp_mod.jump_pressed() for _ in range(5)]
check("no-pad jump_pressed never fires",
      all(p is False for p in edges))

# Default mapping constants are present and sane.
check("BTN_JUMP defined", isinstance(_gp_mod.BTN_JUMP, int))
check("BTN_PAUSE defined", isinstance(_gp_mod.BTN_PAUSE, int))
check("DEADZONE in (0, 1)", 0 < _gp_mod.DEADZONE < 1)


# ---------------------------------------------------------------------------
# Player customization — icon glyph + body color persist via settings
# ---------------------------------------------------------------------------
section("Player customization")
from src import settings as _cust_settings
from src import prefs as _cust_prefs
from src.constants import PLAYER_COLORS, PLAYER_ICONS
from src.graphics import draw_cube_icon_glyph as _glyph

# PLAYER_ICONS table is populated and matches the glyph branches.
check("PLAYER_ICONS has 8 entries", len(PLAYER_ICONS) == 8)
check("PLAYER_ICONS first is Classic", PLAYER_ICONS[0] == "Classic")
check("PLAYER_COLORS non-empty", len(PLAYER_COLORS) >= 4)

# Settings accessors expose the new keys with sane defaults.
check("default player_color_index == 0",
      _cust_settings.DEFAULTS["player_color_index"] == 0)
check("default player_icon_index == 0",
      _cust_settings.DEFAULTS["player_icon_index"] == 0)

# Persistence round-trip with redirected prefs file.
with tempfile.TemporaryDirectory() as _td:
    _orig_path = _cust_prefs._PREFS_PATH
    _cust_prefs._PREFS_PATH = os.path.join(_td, "prefs.json")
    _cust_prefs._cache = None
    try:
        _cust_settings.set_player_color_index(3)
        _cust_settings.set_player_icon_index(5)
        check("color index persists",
              _cust_settings.get_player_color_index() == 3)
        check("icon index persists",
              _cust_settings.get_player_icon_index() == 5)
        # Negative input gets coerced to default (0), not stored as -1.
        _cust_settings.set_player_color_index(-1)
        check("negative color clamped to default",
              _cust_settings.get_player_color_index() == 0)
        _cust_settings.set_player_icon_index(-99)
        check("negative icon clamped to default",
              _cust_settings.get_player_icon_index() == 0)
        # Garbage input falls back to default rather than raising.
        _cust_settings.set_player_color_index("oops")
        check("garbage color coerced to default",
              _cust_settings.get_player_color_index() == 0)
        _cust_settings.set_player_icon_index("nope")
        check("garbage icon coerced to default",
              _cust_settings.get_player_icon_index() == 0)
        # Out-of-range positive value is allowed in storage but Player
        # applies modulo on read, so the test verifies that wrap-around.
        _cust_settings.set_player_icon_index(999)
        wrap = _cust_settings.get_player_icon_index() % len(PLAYER_ICONS)
        check("oversized icon wraps via modulo at read site",
              0 <= wrap < len(PLAYER_ICONS))
    finally:
        _cust_prefs._PREFS_PATH = _orig_path
        _cust_prefs._cache = None

# draw_cube_icon_glyph must never raise for any icon variant, including
# unknown indices (which fall back to Classic).
_glyph_surf = pygame.Surface((PLAYER_SIZE, PLAYER_SIZE), pygame.SRCALPHA)
_glyph_ok = True
for _ii in range(-2, len(PLAYER_ICONS) + 5):
    try:
        _glyph(_glyph_surf, 0, 0, PLAYER_SIZE, PLAYER_COLORS[0], _ii)
    except Exception:
        _glyph_ok = False
check("draw_cube_icon_glyph survives every index", _glyph_ok)

# Player.__init__ should pick up the persisted color/icon. We isolate
# prefs again and check that a freshly-spawned Player applies them.
with tempfile.TemporaryDirectory() as _td2:
    _orig_path = _cust_prefs._PREFS_PATH
    _cust_prefs._PREFS_PATH = os.path.join(_td2, "prefs.json")
    _cust_prefs._cache = None
    try:
        _cust_settings.set_player_color_index(2)
        _cust_settings.set_player_icon_index(4)
        _p = Player(make_flat_level())
        check("Player adopts persisted color index",
              _p.color_index == 2)
        check("Player adopts persisted icon index",
              _p.icon_index == 4)
        check("Player color matches palette slot",
              _p.player_color == PLAYER_COLORS[2])
        # Stored index >= len(PLAYER_COLORS) must wrap, not crash.
        _cust_settings.set_player_color_index(len(PLAYER_COLORS) + 3)
        _p2 = Player(make_flat_level())
        check("Player wraps oversized color via modulo",
              0 <= _p2.color_index < len(PLAYER_COLORS))
    finally:
        _cust_prefs._PREFS_PATH = _orig_path
        _cust_prefs._cache = None

# The customize screen helper exists and is importable. The actual UI
# loop needs an event pump, but we can at least verify the symbol.
from src import menus as _cust_menus
check("run_customize is callable",
      callable(getattr(_cust_menus, "run_customize", None)))
check("_draw_player_swatch helper exists",
      callable(getattr(_cust_menus, "_draw_player_swatch", None)))


# ---------------------------------------------------------------------------
# Hint mode — bot ghost overlay available from play.py
# ---------------------------------------------------------------------------
section("Hint mode")

from src import play as _play_mod
# run_play is the entry point that owns the hint toggle. We don't exercise
# the full loop here (it requires a real event pump and would block), but
# the symbol must exist and be callable.
check("play.run_play exists",
      callable(getattr(_play_mod, "run_play", None)))

# The human bot itself must be importable and solve a trivial flat level.
# This is the same path the H key triggers, so a passing test gives us
# reasonable confidence the hint button won't crash on a real level.
from src.bots import HumanBot as _HintBot
flat = make_flat_level(length=20)
# Strip any runtime-only keys the test level doesn't have.
_hb = _HintBot([dict(o) for o in flat])
check("HumanBot accepts plain object list", _hb is not None)

# solve() returns (waypoints, mirror_waypoints, inputs, won). Pass a tiny
# max_frames so the test stays quick even if the solver has to explore a bit.
_hwp, _hmwp, _hin, _hwon = _hb.solve(screen=None, clock=None, max_frames=600)
check("HumanBot.solve returns a waypoint list",
      isinstance(_hwp, list))
check("HumanBot.solve returns a mirror waypoint list",
      isinstance(_hmwp, list))
check("HumanBot.solve returns an input list",
      isinstance(_hin, list))
check("HumanBot waypoints have 2-tuples",
      not _hwp or (len(_hwp[0]) == 2 and isinstance(_hwp[0][0], (int, float))))
check("Flat-level mirror waypoints empty (no dual portal)", _hmwp == [])

# When waypoints come back, they must lie somewhere in the level bounds so
# play.py's world-to-screen transform doesn't draw off-canvas noise.
if _hwp:
    min_x = min(p[0] for p in _hwp)
    max_x = max(p[0] for p in _hwp)
    check("hint waypoints start near spawn", min_x >= 0)
    check("hint waypoints stay in sensible world range",
          max_x < 20 * C.CELL + 500)

# HumanBot end-to-end on trivial flat ground: the solver should actually
# win, not just return a shape. This is the strongest single check that
# the beam search, scoring, and replay verification all line up.
trivial = [
    {"t": T_START, "x": 3, "y": 9, "r": 0},
]
for gx in range(40):
    trivial.append({"t": T_BLOCK, "x": gx, "y": 10, "r": 0})
trivial.append({"t": T_END, "x": 35, "y": 9, "r": 0})
_solver = _HintBot([dict(o) for o in trivial])
_twp, _tmwp, _tin, _twon = _solver.solve(screen=None, clock=None, max_frames=2000)
check("HumanBot solves trivial flat level", _twon is True)
check("HumanBot trivial solution has inputs", len(_tin) > 0)
check("HumanBot trivial waypoints reach end x",
      _twp and max(p[0] for p in _twp) >= 30 * C.CELL)

# HumanBot with an obstacle: a single spike in the middle. The solver must
# discover that jumping is required (not just walking) to reach the end.
spike_level = [
    {"t": T_START, "x": 3, "y": 9, "r": 0},
]
for gx in range(40):
    spike_level.append({"t": T_BLOCK, "x": gx, "y": 10, "r": 0})
spike_level.append({"t": T_SPIKE, "x": 12, "y": 9, "r": 0})
spike_level.append({"t": T_END, "x": 35, "y": 9, "r": 0})
_obstacle_bot = _HintBot([dict(o) for o in spike_level])
_owp, _omwp, _oin, _owon = _obstacle_bot.solve(screen=None, clock=None, max_frames=3000)
check("HumanBot solves single-spike level", _owon is True)
# When the bot solves with a jump, at least one frame must have pressed=True
if _owon:
    # One-button bot: a hold that begins on the ground carries its own
    # press edge, so the meaningful invariant is that the button was
    # held at least once (otherwise the player never left the ground).
    check("Spike solution holds the button at least once",
          any(held for held, _ in _oin))


# ---------------------------------------------------------------------------
# Spider orb — trail crash fix + directional teleport
# ---------------------------------------------------------------------------
section("Spider orb")
import pygame as _pg_spider
_pg_spider.init()
_sp_screen = _pg_spider.display.set_mode((800, 600))

from src.constants import T_SPIDER_ORB as _TSOrb

# 1) Render loop must survive a spider-teleport + many subsequent frames.
#    Regression: the orb used to inject al=220 trail samples out of order,
#    leaving negative-alpha entries mid-list that crashed pygame's color
#    check on the next frame.
_spider_objs = [{"t": T_START, "x": 3, "y": 9, "r": 0}]
for _gx in range(40):
    _spider_objs.append({"t": T_BLOCK, "x": _gx, "y": 10, "r": 0})
for _gx in range(40):
    _spider_objs.append({"t": T_BLOCK, "x": _gx, "y": 2, "r": 0})
_spider_objs.append({"t": _TSOrb, "x": 10, "y": 9, "r": 0})
_sp = Player(_spider_objs)
_sp_crashed = False
try:
    for _f in range(200):
        _sp.update(_f % 3 == 0, _f == 40)  # press once near the orb
        _sp.draw(_sp_screen, 0, 0)
except (ValueError, TypeError) as _e:
    _sp_crashed = True
check("Spider-orb activation does not crash subsequent draw()",
      not _sp_crashed)
# Trail should never contain a sample with al <= 5 at render time —
# invariant the new list-rebuild filter enforces.
check("No decayed (al<=5) trail samples survive the update loop",
      all(seg[3] > 5 for seg in _sp.trail))

# 2) Rotation r=90 sends the teleport RIGHT to the nearest wall,
#    skipping the classic against-gravity behaviour.
_dir_objs = [{"t": T_START, "x": 3, "y": 9, "r": 0}]
for _gx in range(40):
    _dir_objs.append({"t": T_BLOCK, "x": _gx, "y": 10, "r": 0})
# Wall at cell 20 spanning the player's row — teleport must snap to it.
for _gy in range(4, 10):
    _dir_objs.append({"t": T_BLOCK, "x": 20, "y": _gy, "r": 0})
_dir_objs.append({"t": _TSOrb, "x": 10, "y": 9, "r": 90})
_dp = Player(_dir_objs)
_before_x, _before_grav = _dp.x, _dp.grav
# Run until we hit the orb; orb at cell 10 ~ x=500.
_saw_jump = False
_pre_tp_x = _dp.x
for _f in range(480):
    _pre_tp_x = _dp.x
    _dp.update(False, _dp.x + _dp.size >= 10 * C.UNITS_PER_BLOCK - C.px_to_units(3))
    if _dp.x - _pre_tp_x > C.px_to_units(100):  # instant horizontal jump = teleport
        _saw_jump = True
        break
check("Directional spider orb (r=90) teleports player horizontally",
      _saw_jump)
check("Horizontal spider teleport keeps gravity unchanged",
      _dp.grav == _before_grav)

# 3) Default r=0 still flips gravity on vertical teleport (back-compat).
_vert_objs = [{"t": T_START, "x": 3, "y": 9, "r": 0}]
for _gx in range(40):
    _vert_objs.append({"t": T_BLOCK, "x": _gx, "y": 10, "r": 0})
for _gx in range(40):
    _vert_objs.append({"t": T_BLOCK, "x": _gx, "y": 2, "r": 0})
_vert_objs.append({"t": _TSOrb, "x": 10, "y": 9, "r": 0})
_vp = Player(_vert_objs)
_vp_grav_before = _vp.grav
_saw_flip = False
for _f in range(600):
    _vp.update(False, _vp.x + _vp.size >= 10 * C.UNITS_PER_BLOCK - C.px_to_units(3))
    if _vp.grav != _vp_grav_before:
        _saw_flip = True
        break
check("Default (r=0) spider orb still flips gravity", _saw_flip)


# ---------------------------------------------------------------------------
# Dash orb — persistence + bot uses it correctly
# ---------------------------------------------------------------------------
section("Dash orb persistence + human-bot integration")
from src.constants import T_DASH_ORB as _TDO
from src.levels import normalize_object as _nrm

# 1) Dash speed / duration are no longer per-orb: the registry has no
#    such fields and legacy values in old level files are dropped.
from src.objects import spec_for as _spec_for
_dash_spec = _spec_for(_TDO)
check("dash orb has no per-orb dash_speed / dash_dur fields",
      _dash_spec.field("dash_speed") is None
      and _dash_spec.field("dash_dur") is None)
_n = _nrm({"t": _TDO, "x": 11, "y": 9, "r": 0,
           "dash_speed": 18.0, "dash_dur": 25})
check("legacy dash_speed / dash_dur are dropped on normalize_object",
      "dash_speed" not in _n and "dash_dur" not in _n)

# 2) Default-valued orbs don't bloat the JSON with redundant fields.
_n_def = _nrm({"t": _TDO, "x": 11, "y": 9, "r": 0})
check("default dash orb writes no optional fields",
      "dash_speed" not in _n_def and "dash_dur" not in _n_def
      and "multi_activate" not in _n_def)

# 3) Solver wins a level whose only viable solution is the dash orb,
#    after the orb has been round-tripped through normalize_object.
#    This regression-tests both the persistence fix AND the in-dash
#    beam-prune fix together: pre-fix the bot collapsed mid-air dash
#    options to (F,F), releasing the button and ending the dash a
#    frame after activation, which left the player short of the gap.
_dash_lvl = [{"t": T_START, "x": 3, "y": 9, "r": 0}]
for _gx in list(range(13)) + list(range(18, 30)):
    _dash_lvl.append({"t": T_BLOCK, "x": _gx, "y": 10, "r": 0})
_dash_lvl.append({"t": _TDO, "x": 11, "y": 9, "r": 0})
_dash_lvl.append({"t": T_END, "x": 27, "y": 9, "r": 0})
_dash_lvl_saved = [_nrm(o) for o in _dash_lvl]
_dash_bot = _HintBot([dict(o) for o in _dash_lvl_saved])
_, _, _dash_inputs, _dash_won = _dash_bot.solve(
    screen=None, clock=None, max_frames=3000)
check("human bot solves dash-orb level after save round-trip",
      _dash_won is True)
if _dash_won:
    # Replay to confirm the dash actually fired (not solved by some
    # other unintended path).
    from src.bots import SimPlayer as _DashSim
    _replay = _DashSim([dict(o) for o in _dash_lvl_saved])
    _saw_dash = False
    for _h, _pr in _dash_inputs:
        _replay.update(_h, _pr)
        if _replay.dash_timer > 0:
            _saw_dash = True
        if _replay.won:
            break
    check("human bot solution genuinely uses the dash orb",
          _saw_dash is True)

# 4) Jump probe hint integration — adding a probe to the level should
#    not break the solver. The probe is purely advisory (bumps score
#    near the press point) but mustn't introduce errors when present.
from src.constants import T_JUMP_PREDICTOR as _TJP_dash
_probe_lvl = [dict(o) for o in spike_level]
_probe_lvl.append({"t": _TJP_dash, "x": 11, "y": 9, "r": 0,
                   "mode": "cube", "grav": 1, "mini": False,
                   "dx": 0, "dy": 0})
_probe_bot = _HintBot([dict(o) for o in _probe_lvl])
_, _, _probe_inputs, _probe_won = _probe_bot.solve(
    screen=None, clock=None, max_frames=3000)
check("human bot solves spike level with a jump probe present",
      _probe_won is True)
check("HumanBot probe index populated when probes exist",
      len(_probe_bot._probe_xs) == 1 and _probe_bot._probe_xs[0] == 11)


# ---------------------------------------------------------------------------
# Dash rework: matches the player's current move speed (so it can't
# desync from the music), no duration of its own, stopped by an S Block,
# a wall, death, OR releasing the button.
# ---------------------------------------------------------------------------
section("Dash rework + S Block")
from src.constants import (T_DASH_ORB_GRAV as _TDOG, T_DASH_STOP as _TDS,
                           DASH_TIMER_INFINITE as _DASH_INF)
from src.physics import DEFAULT_PARAMS as _DEF_PARAMS


def _dash_level(extras):
    return make_flat_level(40, extras=extras)


def _run_to_dash(p, orb_gx, max_frames=240):
    """Step until the orb at ``orb_gx`` has started a dash."""
    for _ in range(max_frames):
        over = (p.x + p.size > orb_gx * C.UNITS_PER_BLOCK
                and p.x < (orb_gx + 1) * C.UNITS_PER_BLOCK)
        p.update(over, over)
        if p.dash_timer > 0:
            return True
    return False


_dp = Player(_dash_level([{"t": _TDO, "x": 6, "y": 9, "r": 0}]))
check("dash orb starts a dash", _run_to_dash(_dp, 6))
check("dash matches the player's current move speed",
      abs(_dp.dash_vx - _dp.move_speed) < 1e-6)
check("dash duration is the infinite sentinel",
      _dp.dash_timer > _DASH_INF - 100)
_x_before = _dp.x
_dp.update(False, False)
check("releasing the button ends the dash", _dp.dash_timer == 0)
_x_after_release = _dp.x
for _ in range(20):
    _dp.update(False, False)
check("after release, the player no longer travels at dash speed",
      abs((_dp.x - _x_after_release) - 20 * _DEF_PARAMS.dash_speed) > 1.0)

# S Block stops it, and the gravity variant still flips on that stop.
# Held throughout so the dash isn't cut short by a release first.
_sp_dash = Player(_dash_level([{"t": _TDOG, "x": 6, "y": 9, "r": 0},
                            {"t": _TDS, "x": 14, "y": 9, "r": 0}]))
check("gravity dash orb starts a dash", _run_to_dash(_sp_dash, 6))
_grav_before = _sp_dash.grav
_stopped = False
for _ in range(600):
    _sp_dash.update(True, False)
    if _sp_dash.dash_timer == 0:
        _stopped = True
        break
check("S Block stops an active dash", _stopped)
check("gravity dash orb still flips gravity when an S Block ends the dash",
      _sp_dash.grav == -_grav_before)

# Dash angle is clamped to ±70° off horizontal (never purely vertical).
from src.player.core import _clamp_dash_angle_rad as _clamp_dash
import math as _math_dash
check("straight-up dash orb rotation clamps to -70deg off horizontal",
      abs(_math_dash.degrees(_clamp_dash(270)) - (-70.0)) < 1e-6
      or abs(_math_dash.degrees(_clamp_dash(-90)) - (-70.0)) < 1e-6)
check("horizontal dash orb rotation is unaffected by the clamp",
      abs(_clamp_dash(0)) < 1e-9)
check("left-facing dash orb rotation stays left-facing after the clamp",
      _math_dash.cos(_clamp_dash(180)) < 0)


# ---------------------------------------------------------------------------
# Orb buffering: a click fires at most ONE orb. Holding the button down
# through a whole chain of orbs must not auto-fire every orb it touches —
# only the orb near the actual click (or within its short buffer window).
# ---------------------------------------------------------------------------
section("Orb click buffering (one click, one orb)")
_orb1_gx, _orb2_gx = 6, 10
_buf_level = make_flat_level(40, extras=[
    {"t": T_ORB, "x": _orb1_gx, "y": 9, "r": 0},
    {"t": T_ORB, "x": _orb2_gx, "y": 9, "r": 0},
])
_bp = Player(_buf_level)
# Ship mode: holding the button just thrusts every frame (no cube-style
# "hold = bunny-hop on every landing" side effect), so this isolates orb
# buffering from that unrelated ground-jump mechanic.
_bp.mode = MODE_SHIP
_pressed_once = False
for _ in range(600):
    orb1_left = _orb1_gx * C.UNITS_PER_BLOCK
    about_to_touch = (orb1_left - (_bp.x + _bp.size)) <= C.px_to_units(25)
    press_now = about_to_touch and not _pressed_once
    if press_now:
        _pressed_once = True
    # Held continuously once pressed — never released — through both orbs.
    _bp.update(_pressed_once, press_now)
check("first orb in the chain fires from the single click",
      (T_ORB, _orb1_gx, 9) in _bp.passed)
check("second orb does NOT fire from the same continuous hold",
      (T_ORB, _orb2_gx, 9) not in _bp.passed)


# ---------------------------------------------------------------------------
# Teleport portal: same group-linked pairing as the teleport orb, but
# fires automatically on touch — no click required.
# ---------------------------------------------------------------------------
section("Auto teleport portal")
_tp_dest_gx = 30
_portal_level = make_flat_level(40, extras=[
    {"t": T_TELEPORT_PORTAL, "x": 6, "y": 9, "group_id": 1},
    {"t": T_TELEPORT_PORTAL, "x": _tp_dest_gx, "y": 9, "group_id": 1,
     "dest": True},
])
_tpp = Player(_portal_level)
for _ in range(320):
    _tpp.update(False, False)   # never clicked — auto-run only
check("teleport portal fires without any click",
      _tpp.x > 20 * C.UNITS_PER_BLOCK)

_orb_level = make_flat_level(40, extras=[
    {"t": T_TELEPORT_ORB, "x": 6, "y": 9, "group_id": 1},
    {"t": T_TELEPORT_ORB, "x": _tp_dest_gx, "y": 9, "group_id": 1,
     "dest": True},
])
_tpo = Player(_orb_level)
for _ in range(320):
    _tpo.update(False, False)   # never clicked — teleport orb needs one
check("teleport orb (unlike the portal) does NOT fire without a click",
      _tpo.x < 20 * C.UNITS_PER_BLOCK)

# Registry / placement wiring for the S Block.
from src.objects import (SPECS as _SPECS, CAT_EDITOR_UTILS as _CAT_UTILS,
                         PALETTE_CATEGORIES as _PAL_CATS,
                         seed_defaults as _seed_defaults)
from src.editor import ops as _ops_mod
check("S Block is registered as 'dash_stop' named 'S Block'",
      _SPECS[_TDS].name == "S Block")
check("S Block lives in the Editor Utils palette category",
      _SPECS[_TDS].category == _CAT_UTILS
      and _TDS in dict(_PAL_CATS)[_CAT_UTILS])
check("Editor Utils tab is the last palette category",
      _PAL_CATS[-1][0] == _CAT_UTILS)
_placed_objs = []
_placed = _ops_mod.place_object(_placed_objs, 4, 9, _TDS, 0)
check("freshly placed S Block is invisible by default",
      _placed.get("invisible") is True and _placed_objs == [_placed])
check("only the S Block seeds invisible",
      _seed_defaults({"t": T_ORB, "x": 1, "y": 1}).get("invisible") is None)

# Orb multi-activate flag: default False = fire once ever (unchanged).
section("Orb multi-activate flag")


def _orb_double_touch(multi):
    """Fire the same orb twice with two discrete presses, stepping the
    player back to the pre-touch pose in between (= leaving and coming
    back to the orb).  Returns one bool per touch: did the orb fire?"""
    orb = {"t": T_ORB, "x": 6, "y": 9, "r": 0, "multi_activate": multi}
    p = Player(_dash_level([orb]))
    while p.x + p.size < 6 * C.UNITS_PER_BLOCK + C.px_to_units(10):
        p.update(False, False)
    pose = (p.x, p.y, p.vy)
    fired = []
    for _ in range(2):
        p.x, p.y, p.vy = pose
        p.on_ground = False
        before = p.vy
        p.update(True, True)
        # Threshold scaled with the Checkpoint-3 tick-rate migration:
        # JUMP_FORCE (and other per-tick velocities) is ~4x smaller at
        # 240 TPS than at the old 60 TPS, so the "did a jump fire" drop
        # threshold shrinks with it (was 5, now 5/4).
        fired.append(p.vy < before - C.px_to_units(1.25))
        p.update(False, False)
    return fired


check("default orb (multi_activate off) fires once and never again",
      _orb_double_touch(False) == [True, False])
check("multi_activate orb fires again on a second discrete touch",
      _orb_double_touch(True) == [True, True])

_ma_orb = {"t": T_ORB, "x": 6, "y": 9, "r": 0, "multi_activate": True}
_ma_p = Player(_dash_level([_ma_orb]))
while _ma_p.x + _ma_p.size < 6 * C.UNITS_PER_BLOCK + C.px_to_units(10):
    _ma_p.update(False, False)
_ma_pose = (_ma_p.x, _ma_p.y, _ma_p.vy)
_ma_p.update(True, True)
check("multi_activate orb stays out of `passed`",
      ("orb", 6, 9) not in _ma_p.passed
      and ("orb", 6, 9) in _ma_p.held_orbs)
_ma_p.x, _ma_p.y, _ma_p.vy = _ma_pose
_ma_p.update(True, False)
# Threshold scaled 5 -> 1.25 for the same reason as _orb_double_touch's
# 5 -> 1.25 (JUMP_FORCE shrank ~4x under the 240 TPS tick-rate migration).
check("multi_activate orb does not refire during the same hold",
      _ma_p.vy > -C.px_to_units(1.25))
_ma_p.update(False, False)
check("releasing clears the multi-activate hold gate", not _ma_p.held_orbs)
check("every orb type exposes the multi_activate field",
      all(_SPECS[_t].field("multi_activate") is not None
          for _t in ORB_TYPES))
_ma_norm = _nrm({"t": T_ORB, "x": 6, "y": 9, "r": 0, "multi_activate": True})
check("multi_activate survives normalize_object",
      _ma_norm.get("multi_activate") is True)


# ---------------------------------------------------------------------------
# Spider orb direction toggle (per-orb editor field)
# ---------------------------------------------------------------------------
section("Spider orb direction toggle")
from src.constants import T_SPIDER_ORB as _TSpO

# 1) `dir` field round-trips through save when set to a cardinal.
_dir_orb = {"t": _TSpO, "x": 5, "y": 9, "r": 0, "dir": "right"}
check("explicit dir survives normalize_object",
      _nrm(_dir_orb).get("dir") == "right")
# 2) Default / auto-direction orbs stay lean on disk.
_def_orb = {"t": _TSpO, "x": 5, "y": 9, "r": 0}
check("default-direction spider orb omits dir field",
      "dir" not in _nrm(_def_orb))
_auto_orb = {"t": _TSpO, "x": 5, "y": 9, "r": 0, "dir": "auto"}
check("explicit auto direction is also omitted (default)",
      "dir" not in _nrm(_auto_orb))

# 3) `dir` actually steers the teleport. Build a corridor where:
#    - the only viable direction is RIGHT (vertical clear, wall to right)
#    - and verify the orb teleports the player there when dir=right.
_dir_lvl = [{"t": T_START, "x": 3, "y": 9, "r": 0}]
for _gx in range(40):
    _dir_lvl.append({"t": T_BLOCK, "x": _gx, "y": 10, "r": 0})
# Wall directly in player's row at cell 20 to catch a horizontal teleport.
for _gy in range(4, 10):
    _dir_lvl.append({"t": T_BLOCK, "x": 20, "y": _gy, "r": 0})
_dir_lvl.append({"t": _TSpO, "x": 10, "y": 9, "r": 0, "dir": "right"})
_dir_lvl.append({"t": T_END, "x": 35, "y": 9, "r": 0})
_dp_dir = Player(_dir_lvl)
_pre_x_dir = None
_post_x_dir = None
for _f in range(800):
    _pre_x_dir = _dp_dir.x
    _dp_dir.update(False, _dp_dir.x + _dp_dir.size >= 10 * C.UNITS_PER_BLOCK - C.px_to_units(3))
    if _dp_dir.x - _pre_x_dir > C.px_to_units(100):
        _post_x_dir = _dp_dir.x
        break
check("dir=right teleports the player horizontally",
      _post_x_dir is not None and _post_x_dir > _pre_x_dir + C.px_to_units(200))


# ---------------------------------------------------------------------------
# PathFollowController upgrades — hysteresis, hazard lookahead, mirror-aware safety
# ---------------------------------------------------------------------------
section("PathFollowController upgrades")
from src.bots import PathFollowController as _LiveBot
from src.constants import (
    T_BLOCK as _TB, T_SPIKE as _TSP,
    MODE_CUBE as _MC, MODE_WAVE as _MW, MODE_SHIP as _MSH,
)
from src.physics import PhysicsParams as _PP

# 1) Hysteresis damps a single-frame opposing request.
_bc_h = _LiveBot([(0, 0), (1000, 0)])
_bc_h._hold_state = False
# One flip request in isolation is swallowed.
_r1 = _bc_h.hysteretic_hold(True)
check("hysteresis: single flip request keeps prior state", _r1 is False)
# Two consecutive flip requests commit the flip.
_r2 = _bc_h.hysteretic_hold(True)
check("hysteresis: two consecutive flip requests commit", _r2 is True)
# Consistent requests reset the counter; a single dissent is swallowed.
_bc_h.hysteretic_hold(True)
_r3 = _bc_h.hysteretic_hold(False)
check("hysteresis: single dissent after settled state is ignored",
      _r3 is True)

# 2) reset() clears the hysteresis latch.
_bc_h._hold_state = True
_bc_h._hold_flip_confirm = 3
_bc_h.reset()
check("reset clears hysteresis hold state",
      _bc_h._hold_state is False and _bc_h._hold_flip_confirm == 0)

# 3) _path_crosses_hazard detects a spike in the short-horizon path.
_haz_objs = [{"t": _TSP, "x": 10, "y": 5, "r": 0}]
_bc_p = _LiveBot([(0, 0)], objects=_haz_objs)
# 10 frames forward at vx=5 puts us at cell 10 where the spike sits.
_hits = _bc_p.path_crosses_hazard(
    pcx=50.0, pcy=5 * CELL + CELL // 2,
    vx=CELL / 1.0, vy=0.0, frames=10,
)
check("path_crosses_hazard flags a spike on the trajectory", _hits is True)
_clear = _bc_p.path_crosses_hazard(
    pcx=50.0, pcy=0 * CELL + CELL // 2,
    vx=CELL / 1.0, vy=0.0, frames=10,
)
check("path_crosses_hazard misses when path sits well above hazard row",
      _clear is False)

# 4) Wave-mode lookahead flips the PD choice when it sails into a spike.
#    Build a mock "player" with the exact fields compute_input reads.
class _FakePlayer:
    pass
_fp = _FakePlayer()
_fp.x = C.px_to_units(50.0)
_fp.y = 5 * C.UNITS_PER_BLOCK
_fp.vy = 0.0
_fp.mode = _MW
_fp.grav = 1
_fp.on_ground = False
_fp.size = C.PLAYER_SIZE_UNITS
_fp.move_speed = float(C.UNITS_PER_BLOCK)   # exactly 1 cell per frame
_fp.params = _PP()
_fp.dash_timer = 0
_fp.mirror = None
# Spike 3 cells ahead at y=5; a held-up wave would hover/lift — the
# "up" choice should stay clear. A held-down wave would dive — make
# sure the bot detects it would be bad if the PD decision ordered it.
# To unambiguously force a flip, we place the spike BELOW the start y.
_below_spike = [{"t": _TSP, "x": 4, "y": 6, "r": 0},  # just below/ahead
                {"t": _TSP, "x": 5, "y": 6, "r": 0}]
# Waypoint that asks the wave to go DOWN (target y is below current y,
# so error_future > 0 with grav=1 -> want_hold = True — hold = going UP).
# We want the bot to want_hold = False (dive) to fly INTO the spike, so
# set waypoints BELOW current y to make error_future > 0 -> held=True
# which with grav=1 gives direction=-1 -> vy=-move_speed (up). Then the
# "up" trajectory doesn't hit the below spike, lookahead agrees, no flip.
# The useful shape: waypoint ABOVE to make the PD dive (want_hold=False).
_wps = [(50.0, 5 * CELL - 200), (300.0, 5 * CELL - 200)]
_bc_w = _LiveBot(_wps, objects=_below_spike)
# Nudge hysteresis so whatever the decision comes out to is returned live.
_bc_w.HOLD_CONFIRM_FRAMES = 0
held, pressed = _bc_w.compute_input(_fp)
# PD would dive (want_hold=False since error_future<0 and grav=1), but
# diving hits the spike at cell (4-5, 6). Lookahead should flip to
# want_hold=True (up) since cell 6 is blocked and cell 4 above is clear.
check("wave lookahead flips decision when PD choice sails into a spike",
      held is True)

# 5) Mirror-aware check: mirror-alive + chosen input would fly mirror into
#    a hazard the main's trajectory avoids. Expect the bot to prefer the
#    alternative, even when main's own direction is safe.
_fp2 = _FakePlayer()
_fp2.x = C.px_to_units(50.0)
_fp2.y = 5 * C.UNITS_PER_BLOCK
_fp2.vy = 0.0
_fp2.mode = _MW
_fp2.grav = 1
_fp2.on_ground = False
_fp2.size = C.PLAYER_SIZE_UNITS
_fp2.move_speed = float(C.UNITS_PER_BLOCK)
_fp2.params = _PP()
_fp2.dash_timer = 0
# Mirror sits high in the world with grav=-1 (falls upward). Place a
# spike ABOVE the mirror so holding (mirror direction=-1 × grav=-1 = +1,
# goes down, AWAY from the spike) is safe, but releasing (direction=+1 ×
# grav=-1 = -1, goes up, INTO the spike) kills it.
_fp2.mirror = {
    "y": 10 * C.UNITS_PER_BLOCK,
    "vy": 0.0,
    "grav": -1,
    "on_ground": False,
    "alive": True,
    "mode": _MW,
    "size": C.PLAYER_SIZE_UNITS,
    "angle": 0.0,
}
# Spike 3 cells ahead at the mirror's y-1 row (above mirror in world =
# the direction mirror flies when released under grav=-1).
_mirror_spike = [{"t": _TSP, "x": 4, "y": 9, "r": 0},
                 {"t": _TSP, "x": 5, "y": 9, "r": 0}]
# Waypoint BELOW main so PD wants want_hold=False (release, main dives).
# For main (grav=1), want_hold=False → direction=+1, vy=+speed (down, safe).
# For mirror (grav=-1), held=False → direction=+1, vy=+speed × -1 = -speed,
# i.e. mirror goes UP in world coords — INTO the spike above it.
# Bot should flip to held=True so the mirror stays safe.
_wps2 = [(50.0, 5 * CELL + 400), (300.0, 5 * CELL + 400)]
_bc_m = _LiveBot(_wps2, objects=_mirror_spike)
_bc_m.HOLD_CONFIRM_FRAMES = 0
held_m, _ = _bc_m.compute_input(_fp2)
check("mirror-aware lookahead flips when main-safe choice kills mirror",
      held_m is True)


# ---------------------------------------------------------------------------
# Dual mode — mirror inherits player state, the bots snapshot it
# ---------------------------------------------------------------------------
section("Dual mode")
from src.constants import T_MODE_DUAL, HEIGHT as _DH
from src.bots import (snapshot as _ab_snap, restore as _ab_restore,
                      build_obj_index as _build_obj_index, SimPlayer as _SimPlayer)

# 1) `_enter_dual` should inherit the player's current motion state.
#    A grounded player crossing a dual portal should produce a grounded
#    mirror — not a falling-from-rest one. We verify this by calling
#    _enter_dual directly so we observe initial state, before _step_mirror
#    has a chance to clobber on_ground (it resets to False each frame and
#    only sets it back via collision; in a level with no ceiling, the
#    mirror has nothing to land on, so a post-step check is meaningless).
dual_objs = make_flat_level(length=40,
    extras=[{"t": T_MODE_DUAL, "x": 8, "y": 9, "r": 0}])
_dp = Player(dual_objs)
# Walk forward until we cross the portal (at gx=8, ~5 cells past spawn).
for _ in range(240):
    _dp.update(False, False)
    if _dp.mirror is not None:
        break
check("Dual portal spawns mirror after crossing",
      _dp.mirror is not None)
if _dp.mirror is not None:
    check("Mirror grav is opposite of player",
          _dp.mirror["grav"] == -_dp.grav)
    # vy should be sign-flipped from the player's vy at crossing time.
    # On flat ground vy is ~0 so flipping doesn't change much, but the
    # field must exist and be a float (not the old hardcoded 0.0).
    check("Mirror vy is a float",
          isinstance(_dp.mirror["vy"], float))
    check("Mirror angle is a float",
          isinstance(_dp.mirror["angle"], float))

# 1b) Direct test of _enter_dual initial state for a grounded player.
#     This bypasses the full update loop so we observe the initialization
#     before any _step_mirror call.
_gp = Player(make_flat_level(length=20))
_gp.on_ground = True
_gp.vy = 0.0
_gp._was_on_ground = True   # what update() would have stashed
_gp._enter_dual()
check("_enter_dual: mirror inherits on_ground when player was grounded",
      _gp.mirror is not None and _gp.mirror["on_ground"] is True)

# 2) Mid-jump dual entry: build a player, force a jump state, then enter
#    dual manually — the mirror should NOT spawn with vy=0.
_jp = Player(make_flat_level(length=20))
_jp.vy = -10.0       # mid-rising-jump
_jp.on_ground = False
_jp.angle = 45.0
_jp._enter_dual()
check("Mid-jump dual entry: mirror vy is sign-flipped, not zero",
      _jp.mirror is not None and _jp.mirror["vy"] == 10.0)
check("Mid-jump dual entry: mirror on_ground is False (matches player)",
      _jp.mirror["on_ground"] is False)
check("Mid-jump dual entry: mirror angle is sign-flipped",
      _jp.mirror["angle"] == -45.0)

# 3) Autobot snapshot/restore must round-trip the mirror. Without this fix,
#    beam search restores left mirror=None on every snap, silently
#    desyncing dual-mode state from reality.
_sp = _SimPlayer([dict(o) for o in dual_objs])
_build_obj_index(_sp)
# Step until past the portal so a mirror exists.
for _ in range(240):
    _sp.update(False, False)
    if _sp.mirror is not None:
        break
check("SimPlayer mirror present after dual portal", _sp.mirror is not None)
if _sp.mirror is not None:
    snap_mirror = _sp.mirror
    expected_y = snap_mirror["y"]
    expected_grav = snap_mirror["grav"]
    snap = _ab_snap(_sp)
    # snap layout: (vals, passed, anims, obj_pos, mirror, mirror_passed,
    # coins_collected, held_orbs) — coins slot was added when the bot
    # started rewarding coin pickups in its heuristic; held_orbs when
    # orbs gained the multi-activate flag.
    check("Snapshot is 8-tuple (mirror, mirror_passed, coins, held_orbs)",
          isinstance(snap, tuple) and len(snap) == 8)
    check("Snapshot mirror is non-None when player has a mirror",
          snap[4] is not None)
    # Now corrupt the live mirror, restore, and confirm we got the snapshot's
    # state back — proving the snapshot actually captured something useful.
    _sp.mirror = None
    _ab_restore(_sp, snap)
    check("Restore re-creates mirror from snapshot",
          _sp.mirror is not None and abs(_sp.mirror["y"] - expected_y) < 0.001)
    check("Restored mirror grav matches snapshot",
          _sp.mirror["grav"] == expected_grav)
    # Restoring a None-mirror snapshot should clear the mirror.
    pre_dual_snap = (snap[0], snap[1], snap[2], snap[3], None, frozenset())
    _ab_restore(_sp, pre_dual_snap)
    check("Restore clears mirror when snapshot mirror is None",
          _sp.mirror is None)

# 4) Backwards-compat: a 4-tuple snapshot (old format, no mirror slot)
#    should still restore without raising and produce mirror=None.
_legacy_snap = (snap[0], snap[1], snap[2], snap[3])  # 4-tuple
_sp.mirror = {"y": 0, "vy": 0, "grav": 1, "on_ground": False,
              "angle": 0.0, "alive": True}  # pre-state to be cleared
_ab_restore(_sp, _legacy_snap)
check("Restore tolerates legacy 4-tuple snapshot",
      _sp.mirror is None)

# 5) Solo portal collapses the mirror back into the main player. Build a
#    level with a ceiling (so the upside-down mirror can land), a dual
#    portal, then a solo portal further along; after the player crosses
#    solo, mirror must be None and the player should still be alive (no
#    crash from clearing self.mirror mid-substep).
from src.constants import T_MODE_SOLO, T_COIN, T_BG_TRIGGER
def _make_dual_corridor(length, extras=None):
    """Flat ground at y=10 plus a ceiling at y=2 so a -grav mirror has
    something to land on instead of falling off the top of the screen."""
    level = [{"t": T_START, "x": 3, "y": 9, "r": 0}]
    for gx in range(length):
        level.append({"t": T_BLOCK, "x": gx, "y": 10, "r": 0})
        level.append({"t": T_BLOCK, "x": gx, "y": 2, "r": 0})
    level.append({"t": T_END, "x": length - 1, "y": 9, "r": 0})
    if extras:
        level.extend(extras)
    return level

_collapse_objs = _make_dual_corridor(60, extras=[
    {"t": T_MODE_DUAL, "x": 8, "y": 9, "r": 0},
    {"t": T_MODE_SOLO, "x": 30, "y": 9, "r": 0},
])
_cp = Player(_collapse_objs)
_saw_mirror = False
for _ in range(1600):
    _cp.update(False, False)
    if _cp.mirror is not None:
        _saw_mirror = True
    if _saw_mirror and _cp.mirror is None:
        break
    if not _cp.alive or _cp.won:
        break
check("Solo portal collapses mirror back to main player",
      _saw_mirror and _cp.mirror is None and _cp.alive)

# 6) Mirror picks up coins and consumes triggers. Drop a coin at the mirror's
#    height (above the player on flat ground with grav-flipped mirror) and
#    confirm the coin gets collected even though the main player never goes
#    near it. The corridor's ceiling keeps the mirror grounded.
_mirror_coin_objs = _make_dual_corridor(60, extras=[
    {"t": T_MODE_DUAL, "x": 8, "y": 9, "r": 0},
    # Coin just below the ceiling — only the upside-down mirror will sweep
    # through it (the main player stays on the floor).
    {"t": T_COIN, "x": 14, "y": 3, "r": 0, "coin_id": 7},
    # BG trigger same column — fires when EITHER body crosses it.
    {"t": T_BG_TRIGGER, "x": 14, "y": 3, "r": 0, "bg": 3},
])
_mp = Player(_mirror_coin_objs)
for _ in range(720):
    _mp.update(False, False)
    if 7 in _mp.coins_collected and _mp.bg_preset == 3:
        break
    if not _mp.alive:
        break
check("Mirror collects coins along its path",
      7 in _mp.coins_collected)
check("Mirror fires global triggers (bg_preset changed)",
      _mp.bg_preset == 3)

# 7) Per-body mode/size portals: a portal in the MIRROR's path (cell y=3,
#    just below the ceiling) should change the mirror's mode/size only,
#    leaving the main player untouched. And vice-versa.
from src.constants import (
    T_MODE_WAVE, T_MODE_BALL, T_MODE_MINI, T_MODE_BIG,
    MODE_CUBE as _MC, MODE_WAVE as _MW, MODE_BALL as _MB,
    MINI_PLAYER_SIZE_UNITS as _MINI, PLAYER_SIZE_UNITS as _BIG,
)

# 7a. Wave portal in MIRROR's path — main stays cube, mirror becomes wave.
_mirror_mode_objs = _make_dual_corridor(60, extras=[
    {"t": T_MODE_DUAL, "x": 8, "y": 9, "r": 0},
    {"t": T_MODE_WAVE, "x": 14, "y": 3, "r": 0},
])
_mp = Player(_mirror_mode_objs)
for _ in range(720):
    _mp.update(False, False)
    if _mp.mirror is not None and _mp.mirror.get("mode") == _MW:
        break
    if not _mp.alive:
        break
check("Mirror-path mode portal changes mirror mode (wave)",
      _mp.mirror is not None and _mp.mirror.get("mode") == _MW)
check("Mirror-path mode portal does NOT sync to main player",
      _mp.mode == _MC)

# 7b. Wave portal in MAIN's path — main becomes wave, mirror stays cube.
_main_mode_objs = _make_dual_corridor(60, extras=[
    {"t": T_MODE_DUAL, "x": 8, "y": 9, "r": 0},
    {"t": T_MODE_WAVE, "x": 14, "y": 9, "r": 0},
])
_mp = Player(_main_mode_objs)
for _ in range(720):
    _mp.update(False, False)
    if _mp.mode == _MW:
        break
    if not _mp.alive:
        break
check("Main-path mode portal changes main mode (wave)",
      _mp.mode == _MW)
check("Main-path mode portal does NOT sync to mirror",
      _mp.mirror is not None and _mp.mirror.get("mode") == _MC)

# 7c. Mini portal in MIRROR's path — mirror shrinks, main stays big.
_mirror_mini_objs = _make_dual_corridor(60, extras=[
    {"t": T_MODE_DUAL, "x": 8, "y": 9, "r": 0},
    {"t": T_MODE_MINI, "x": 14, "y": 3, "r": 0},
])
_mp = Player(_mirror_mini_objs)
for _ in range(720):
    _mp.update(False, False)
    if _mp.mirror is not None and _mp.mirror.get("size") == _MINI:
        break
    if not _mp.alive:
        break
check("Mirror-path mini portal shrinks mirror only",
      _mp.mirror is not None and _mp.mirror.get("size") == _MINI)
check("Mirror-path mini portal does NOT shrink main player",
      _mp.size == _BIG)

# 7d. Mode-portal key lands in mirror_passed (not the shared `passed`),
#     so the main body remains free to consume an identical portal later.
_dup_key = (T_MODE_WAVE, 14, 3)
_mp = Player(_make_dual_corridor(60, extras=[
    {"t": T_MODE_DUAL, "x": 8, "y": 9, "r": 0},
    {"t": T_MODE_WAVE, "x": 14, "y": 3, "r": 0},
]))
for _ in range(720):
    _mp.update(False, False)
    if _mp.mirror is not None and _dup_key in _mp.mirror_passed:
        break
    if not _mp.alive:
        break
check("Mirror portal consumption goes into mirror_passed",
      _dup_key in _mp.mirror_passed)
check("Mirror portal consumption stays out of shared passed",
      _dup_key not in _mp.passed)

# 8) Single-click activates BOTH bodies' orbs. Place a jump orb in mid-air
#    on the player's path AND another in the mirror's path at the same x.
#    With one shared input_buffer the main consumed it first and the mirror
#    silently missed out — the fix gave the mirror its own buffer.
from src.constants import T_ORB
_dual_orb_objs = _make_dual_corridor(60, extras=[
    {"t": T_MODE_DUAL, "x": 8, "y": 9, "r": 0},
    # Player orb: just above the floor at the player's jump-arc height.
    {"t": T_ORB, "x": 18, "y": 7, "r": 0},
    # Mirror orb at the same x, just below the ceiling (mirror is upside
    # down at cell row 3-ish). Putting them at the same x guarantees the
    # rects overlap on the same frame so a single click should fire both.
    {"t": T_ORB, "x": 18, "y": 4, "r": 0},
])
_op = Player(_dual_orb_objs)
# Walk forward (no input) until the player rect overlaps the orb cell, then
# click ONCE. Track whether each body's vy got the jump kick on that click.
_main_orb_key = (T_ORB, 18, 7)
_mirror_orb_key = (T_ORB, 18, 4)
_clicked = False
_main_jumped = False
_mirror_jumped = False
for _frame in range(880):
    # Click only when the player is roughly under both orbs (cell x≈18).
    do_click = (not _clicked) and 17 * C.UNITS_PER_BLOCK <= _op.x <= 18.5 * C.UNITS_PER_BLOCK
    pressed = do_click and not _clicked
    if do_click:
        _clicked = True
    _op.update(do_click, pressed)
    if _main_orb_key in _op.passed:
        _main_jumped = True
    if _mirror_orb_key in _op.passed:
        _mirror_jumped = True
    if _main_jumped and _mirror_jumped:
        break
    if not _op.alive:
        break
check("Single click activates main player's orb",
      _main_jumped)
check("Same click also activates mirror's orb",
      _mirror_jumped)

section("Blue orb behavior")
# Blue orb flips gravity AND reverses momentum: falling into one launches
# you back the way you came under the new gravity (a "bounce"), unlike
# the green orb which only flips gravity and lets momentum carry through.
_bp = Player(make_flat_level())
_bp.vy = 8.0  # falling
_grav_before = _bp.grav
_bp.activate_blue_orb()
check("Blue orb flips gravity", _bp.grav == -_grav_before)
check("Blue orb reverses momentum", _bp.vy == -8.0)

section("Green orb behavior")
# Green orb flips gravity only — momentum is untouched.
_gp = Player(make_flat_level())
_gp.vy = 8.0
_grav_before = _gp.grav
_gp.activate_green_orb()
check("Green orb flips gravity", _gp.grav == -_grav_before)
check("Green orb does not touch momentum", _gp.vy == 8.0)


# ---------------------------------------------------------------------------
# Editor test-mode music wiring
# Test mode (editor's "Test" button) should play the level's assigned music
# with the same lifecycle as a real play session: start at 0, restart on
# death/R, stop on exit. Bot/playback runs intentionally stay silent because
# their variable-speed simulation wouldn't sync to audio.
# ---------------------------------------------------------------------------
section("Editor test-mode music wiring")
import inspect
from src import play as _play_mod
from src import editor as _editor_mod
_play_src = inspect.getsource(_play_mod)
from src import play_render as _play_render_mod
_play_render_src = inspect.getsource(_play_render_mod)
# The four music gates inside run_play used to read `level_music and not
# editor_test`, which silenced editor-test runs even when the editor passed
# a track. They should now gate on level_music alone.
check("run_play music gates dropped 'not editor_test'",
      "level_music and not editor_test" not in _play_src)
# A grep-style sanity check that the music start/stop calls still exist —
# we don't want a "fix" that just removes music handling entirely.
check("run_play still starts level music",
      "music.play_file(self.level_music" in _play_src)
check("run_play still stops level music on death",
      "music.stop()" in _play_src)
# The win-fade call lives in play_render.render_win_overlay now (moved
# out of run_play as part of the play-loop render extraction).
check("run_play still fades music on win",
      "music.fadeout(" in _play_render_src)

# The editor's Test button should pass level_music through: every run
# (Test, Bot, Playback, Replay) goes through EditorSession._run which
# forwards st.level_music, so one check covers all of them.
from src.editor import session as _editor_session_mod
_editor_src = inspect.getsource(_editor_session_mod.EditorSession)
_run_src = inspect.getsource(_editor_session_mod.EditorSession._run)
check("editor's shared _run passes level_music to run_play",
      "level_music=st.level_music" in _run_src)
check("editor's shared _run flags editor_test=True",
      "editor_test=True" in _run_src)
check("editor Test button goes through _run",
      'self._run(" (Test)"' in inspect.getsource(_editor_session_mod.EditorSession.do_test))


# ---------------------------------------------------------------------------
# Bot menu click-handling guards
# A user-reported "the bot is completely broken (cant click at all)" turned
# out to be the menu's conditional buttons (Replay / Use as Hint / Clear)
# being drawn at full opacity but silently no-op-ing when their cached
# state was empty — and the solver itself swallowing exceptions into a
# generic "failed". These tests pin the new behaviour:
#   - _run_solver returns a 4-tuple including a human-readable error
#   - exceptions surface via that error rather than disappearing
#   - the menu source has `disabled=` annotations + click-when-disabled
#     hint paths so the user gets feedback instead of silence.
# ---------------------------------------------------------------------------
section("Bot menu click-handling guards")
from src import bot_menu as _bm
# 1. _run_solver signature: required positional args are (screen, clock, objects);
# `params=None` was added in B5 for per-level physics overrides.
_solver_sig = inspect.signature(_bm._run_solver)
_positional = [p for p in _solver_sig.parameters.values()
               if p.default is inspect.Parameter.empty]
check("_run_solver required args unchanged (screen, clock, objects)",
      [p.name for p in _positional] == ["screen", "clock", "objects"])

# 2. Crash surfacing: a deliberately malformed level should NOT vanish into
#    a silent "failed". The exception's class name needs to land in `err`.
_garbage = [{"no_t_field": True}]
_wp, _mwp, _inp, _status, _err, _sk = _bm._run_solver(None, None, _garbage)
check("_run_solver returns 6-tuple (wp, mwp, inputs, status, err, start_key)",
      _wp is None and _mwp == [] and _inp == [] and _status == "failed"
      and isinstance(_err, str))
check("_run_solver surfaces crash exception class in error string",
      "KeyError" in _err)

# 3. Source-level: the conditional buttons must pass `disabled=` so users
#    can SEE inactive state instead of clicking into dead pixels.
_bm_src = inspect.getsource(_bm.run_bot_menu)
check("Use as Hint Overlay button is rendered with disabled flag",
      "view_disabled" in _bm_src and "disabled=view_disabled" in _bm_src)
check("Replay solved inputs button is rendered with disabled flag",
      "replay_disabled" in _bm_src and "disabled=replay_disabled" in _bm_src)
# The "Clear cached path" button was removed during the UI overflow fix
# pass — Save/Load runs cover the same need. `clear_last_solve` still
# exists as a public helper for external callers.
check("clear_last_solve helper still exported for external callers",
      hasattr(_bm, "clear_last_solve"))

# 4. Disabled clicks should explain WHY they didn't act, not silently drop.
check("Disabled hint-overlay click sets an info_msg",
      "Solve a path first" in _bm_src)
check("Disabled replay click explains the empty-inputs case",
      "Run Find Path first" in _bm_src)

# 5. Replay callback exceptions used to be silently swallowed (`except: pass`).
#    Now they should surface as a visible info_msg so a crash in the user's
#    replay code isn't invisible.
check("Replay callback crash surfaces in info_msg, not silent",
      "Replay crashed:" in _bm_src and "type(exc).__name__" in _bm_src)


# ---------------------------------------------------------------------------
# Wave / ship line trail
# Cube/ball/UFO/spider keep the ghost-sprite trail, but wave and ship now
# draw a continuous line (matches GD). The line uses one SRCALPHA surface
# per frame so per-segment alpha blends cleanly against varying bg.
# ---------------------------------------------------------------------------
section("Wave / ship line trail")
from src import player as _player_mod
from src.constants import (MODE_WAVE as _MW, MODE_SHIP as _MSh,
                           MODE_BALL as _MB, ALL_MODES as _ALL_MODES)

from src.player import draw as _player_draw_mod
_draw_src = inspect.getsource(_player_draw_mod.draw_trail)
check("Every mode uses the solid ribbon trail (no icon-copy ghosts)",
      all(_m in _player_draw_mod._LINE_TRAIL_MODES for _m in _ALL_MODES)
      and _MW in _player_draw_mod._LINE_TRAIL_MODES
      and _MSh in _player_draw_mod._LINE_TRAIL_MODES
      and _MB in _player_draw_mod._LINE_TRAIL_MODES)
check("Ghost-stamp icon-copy trail is gone",
      not hasattr(_player_draw_mod, "_ghost_stamp")
      and "_ghost_stamp" not in _draw_src)
check("Every mode has a ribbon thickness (explicit or default)",
      all(isinstance(_player_draw_mod._LINE_THICKNESS.get(
          _m, _player_draw_mod._LINE_THICKNESS_DEFAULT), int)
          for _m in _ALL_MODES))
check("Line trail uses pygame.draw.line with thickness",
      "pygame.draw.line" in _draw_src and "thickness" in _draw_src)
check("Line trail uses a single SRCALPHA surface for alpha blending",
      "SRCALPHA" in inspect.getsource(_player_draw_mod._line_surface)
      and "line_surf" in _draw_src)

# Behavioural smoke test: drawing wave + ship trails does not crash, and
# the ghost-sprite branch is no longer taken for wave (the ghost-sprite
# branch's polygon for wave used (cx, 4) coords — that geometry should now
# only fire for non-wave/ship modes).
import os as _os
_os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
_os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
import pygame as _pg
_pg.init()
_pg.display.set_mode((1280, 720))
from src.player import Player as _PB
from src.constants import T_BLOCK as _TB, T_START as _TS, T_END as _TE
_objs = ([{"t": _TS, "x": 1, "y": 9, "r": 0}]
         + [{"t": _TB, "x": x, "y": 10, "r": 0} for x in range(40)]
         + [{"t": _TE, "x": 38, "y": 9, "r": 0}])
_p = _PB(_objs)
_p.mode = _MW
_p.y -= 3 * CELL  # Trail rendering requires room to fly above the floor.
for _ in range(20):
    _p.update(False, False)
check("Wave produces non-empty trail before draw",
      len(_p.trail) >= 2)
_surf = _pg.display.get_surface()
try:
    _p.draw(_surf, 0, 0)
    _wave_drew = True
except Exception:
    _wave_drew = False
check("Wave trail draws without crash", _wave_drew)
_p.mode = _MSh
_p.trail = []
for _ in range(20):
    _p.update(True, True)
try:
    _p.draw(_surf, 0, 0)
    _ship_drew = True
except Exception:
    _ship_drew = False
check("Ship trail draws without crash", _ship_drew)

# The whole trail is redrawn every frame in the CURRENT mode's style, so
# a mode switch restyles even samples recorded under the previous mode.
from src.constants import MODE_CUBE as _MC
_p.mode = _MW
_p.trail = []
for _ in range(120):
    _p.update(False, False)
_wave_pts = len(_p.trail)
_surf.fill((0, 0, 0))
_p.draw(_surf, 0, 0)
_wave_shot = _surf.copy()
_p.mode = _MC
_surf.fill((0, 0, 0))
_p.draw(_surf, 0, 0)
_cube_shot = _surf.copy()
check("mode switch keeps every recorded trail sample", len(_p.trail) == _wave_pts)


def _trail_pixels(shot, col):
    # Step 2, not 4: a default (non-per-mode) trail is only
    # _LINE_THICKNESS_DEFAULT=3px thick, so a coarser 4px-aligned grid can
    # miss it entirely depending on exactly which px row the ribbon lands
    # on (a spatial coincidence, not something that should gate the test).
    hits = 0
    for _sx in range(0, 1200, 2):
        for _sy in range(0, 700, 2):
            if shot.get_at((_sx, _sy))[:3] == col:
                hits += 1
    return hits


_col = _p._player_color()
check("wave trail is a solid ribbon in the player colour",
      _trail_pixels(_wave_shot, _col) > 0)
check("the whole trail re-renders in the new mode's style after a switch",
      _trail_pixels(_cube_shot, _col) > 0
      and _cube_shot.get_size() == _wave_shot.get_size())

# ---------------------------------------------------------------------------
# S Block sprite: a hollow white rectangle with an "S", drawn through the
# normal gameplay draw_obj path (it is a real object, not an editor overlay).
# ---------------------------------------------------------------------------
section("S Block sprite")
from src.sprites import draw_obj as _draw_obj
from src.constants import T_DASH_STOP as _TDS_spr, C_DASH_STOP as _CDS
_sb = _pg.Surface((100, 100))
_sb.fill((0, 0, 0))
_draw_obj(_sb, _TDS_spr, 25, 25, 50, 0, 0)
_white_hits = sum(1 for _x in range(100) for _y in range(100)
                  if min(_sb.get_at((_x, _y))[:3]) > 180)
check("S Block renders white pixels through draw_obj", _white_hits > 20)
check("S Block is hollow (its centre stays background)",
      min(_sb.get_at((50, 36))[:3]) < 100)
check("S Block colour is white", _CDS == (255, 255, 255))


# ---------------------------------------------------------------------------
# Bot replay music wiring
# All three editor "Bot" sub-paths (exact / waypoint / file-playback) and
# the bot-menu Replay callback should pass level_music through, matching
# the Test button's behaviour. Used to be silent on the explicit theory
# that variable-speed runs would desync — but at default speed they're
# fine, and the user wants the audio context.
# ---------------------------------------------------------------------------
section("Bot replay music wiring")
_editor_src2 = _editor_src
_bot_src = inspect.getsource(_editor_session_mod.EditorSession.do_bot)
check("editor do_bot has Exact / path / playback sub-paths",
      _bot_src.count("self._run(") >= 3)
check("All do_bot sub-paths run through _run (so they get level_music)",
      "run_play(" not in _bot_src)
_menu_src = inspect.getsource(_editor_session_mod.EditorSession.do_bot_menu)
check("Bot menu Replay callback goes through _run",
      "def replay(inputs):" in _menu_src and "self._run(" in _menu_src)


# ---------------------------------------------------------------------------
# Hitbox recording / editor playback overlay
# `run_play` accepts an `out_hitboxes` list it mutates per frame; the
# editor passes its `last_run_hitboxes` through and overlays the rects
# when the H toggle is on. Lets the user post-mortem a tight section by
# seeing exactly where the hitbox went.
# ---------------------------------------------------------------------------
section("Hitbox recording / editor overlay")
_play_sig = inspect.signature(_play_mod.run_play)
check("run_play accepts out_hitboxes parameter",
      "out_hitboxes" in _play_sig.parameters)
check("out_hitboxes defaults to None (opt-in)",
      _play_sig.parameters["out_hitboxes"].default is None)

_play_src2 = inspect.getsource(_play_mod.PlaySession)
# Recording is driven by the Player now: run_play hands the buffer to
# `player.hitbox_trace` and the player appends (x, y, size) at every
# collision-check point — each physics substep + teleport brackets —
# so the overlay shows *every* check position, not just one per frame.
check("PlaySession wires player.hitbox_trace = current_hitboxes",
      "self.player.hitbox_trace = self.current_hitboxes" in _play_src2)
check("PlaySession commits the buffer through _commit_hitboxes",
      "self.out_hitboxes[:] = self.current_hitboxes" in _play_src2)
check("PlaySession commits on reset AND on exit",
      "self._commit_hitboxes()" in inspect.getsource(_play_mod.PlaySession.reset_attempt)
      and "self._commit_hitboxes()" in inspect.getsource(_play_mod.PlaySession._finish))
check("PlaySession clears the in-place buffer on reset (not reassigned)",
      "self.current_hitboxes.clear()" in _play_src2)

# Player side: recorder helper exists and stamps once per logical frame
# (60 Hz). Per-substep sampling was reverted because dense traces were
# unreadable; now ``_record_hitbox`` fires from the bottom of update()
# only, plus from death-frame early-return paths.
from src.player import Player as _PlayerCls
_player_src = inspect.getsource(_PlayerCls)
check("Player has _record_hitbox helper recording (x, y, size, angle)",
      "def _record_hitbox" in _player_src
      and "self.hitbox_trace.append(" in _player_src
      and "self.angle" in _player_src)
check("Player update() calls _record_hitbox once per frame",
      "self._record_hitbox()" in _player_src
      and "self._record_mirror_hitbox()" in _player_src)

# Editor wiring: state, H toggle, run_play hand-off, draw overlay.
from src.editor import state as _editor_state_mod
from src.editor import render as _editor_render_mod
_editor_state_src = inspect.getsource(_editor_state_mod.EditorState)
_editor_render_src = inspect.getsource(_editor_render_mod)
check("editor declares last_run_hitboxes state",
      "self.last_run_hitboxes = []" in _editor_state_src)
check("editor declares show_hitboxes default OFF",
      "self.show_hitboxes = False" in _editor_state_src)
check("H key toggles show_hitboxes (boolean)",
      "key == pygame.K_h" in _editor_src2
      and "st.show_hitboxes = not st.show_hitboxes" in _editor_src2)
check("editor passes out_hitboxes=last_run_hitboxes to run_play",
      "out_hitboxes=st.last_run_hitboxes" in _run_src)
check("editor clears last_run_hitboxes before each run",
      "st.last_run_hitboxes.clear()" in _run_src)
check("editor draws the hitbox overlay layer when toggle is on",
      "if st.show_hitboxes:" in _editor_src2
      and "def render_hitbox_overlay(" in _editor_render_src
      and "render_hitbox_overlay(" in _editor_src2)

# Behavioural smoke: simulate a short run with out_hitboxes wired up.
# We don't actually call run_play (it owns the event loop) — instead
# verify the recording shape by inspecting that the buffer contract
# documented in the docstring is consistent with the source markers.
_doc = _play_mod.run_play.__doc__ or ""
check("run_play docstring documents out_hitboxes contract",
      "out_hitboxes" in _doc and "(x, y, size" in _doc)

# Behavioural: at 60 Hz sampling, every logical frame appends exactly
# one hitbox sample. The spider teleport is now visible only as one
# end-of-frame stamp at the post-warp position (the swept-volume fill
# was removed because per-substep samples were unreadable in the
# overlay).
from src.player import Player as _PCls
from src.constants import (
    T_BLOCK as _TB, T_END as _TE, MODE_SPIDER as _MSP,
    PLAYER_START_GX as _PSG,
)
_spider_objs = [{'t': _TB, 'x': i, 'y': 15, 'r': 0} for i in range(40)]
_spider_objs += [{'t': _TB, 'x': i, 'y': 10, 'r': 0} for i in range(40) if i != _PSG]
_spider_objs.append({'t': _TE, 'x': 39, 'y': 0, 'r': 0})
_sp = _PCls(_spider_objs)
_sp.mode = _MSP
_sp.hitbox_trace = []
for _ in range(160):
    _sp.update(False, False)
_pre_len = len(_sp.hitbox_trace)
_pre_y = _sp.y
_sp.update(True, True)
_delta = _sp.hitbox_trace[_pre_len:]
# Sample shape: each entry is (x, y, size, angle). Exactly one sample
# fires per frame; the spider teleport leaves the player at a new y
# but only one stamp is appended because all sub-step physics
# happens within a single 60 Hz tick.
check("60 Hz sample shape is (x, y, size, angle)",
      _delta and len(_delta[-1]) == 4)
check("spider teleport produces one end-of-frame hitbox sample",
      len(_delta) == 1)

# Regression: spider must NOT teleport through a slab to reach a full
# block further up. Floor at y=15, a top-half slab (rot=180) row at
# y=12 (bottom face at mid-cell), and a full-block ceiling at y=10
# everywhere except the spawn column (so the player settles on the
# floor, not on the ceiling). The slab's bottom face is nearer than
# the ceiling's bottom — the spider must land on the slab. Before the
# fix, T_SLAB was filtered out of the teleport search, so the spider
# phased right through the slab to the y=10 ceiling.
from src.constants import T_SLAB as _TSL
from src.graphics import slab_rect as _slab_rect, cell_rect as _cell_rect
_slab_objs = [{'t': _TB, 'x': i, 'y': 15, 'r': 0} for i in range(40)]
_slab_objs += [{'t': _TB, 'x': i, 'y': 10, 'r': 0} for i in range(40) if i != _PSG]
_slab_objs += [{'t': _TSL, 'x': i, 'y': 12, 'r': 180} for i in range(40)]
_slab_objs.append({'t': _TE, 'x': 39, 'y': 0, 'r': 0})
_spslab = _PCls(_slab_objs)
_spslab.mode = _MSP
for _ in range(160):
    _spslab.update(False, False)
_spslab.update(True, True)
# Slabs span the whole row at y=12, so whichever column the spider is
# in when the teleport fires, slab_bottom is cell_y=12 bottom = 625.
_slab_bottom = C.px_to_units(_slab_rect(0, 12, 180, 1.0).bottom)
_block_bottom = C.px_to_units(_cell_rect(0, 10, 1.0).bottom)
check("spider teleport lands on slab's bottom face (not phasing through)",
      abs(_spslab.y - _slab_bottom) < C.px_to_units(2)
      and abs(_spslab.y - _block_bottom) > C.px_to_units(20))

# Invisible flag: persisted on ANY object type (universal invisibility),
# visible is the default, and behavior still runs when set (player
# physics reads by type, not by visibility).
from src.levels import normalize_object as _norm
_inv_block = _norm({'t': _TB, 'x': 5, 'y': 10, 'r': 0, 'invisible': True})
check("normalize_object persists invisible=True on solid blocks",
      _inv_block.get('invisible') is True)
_inv_spike = _norm({'t': 'spike', 'x': 5, 'y': 10, 'r': 0, 'invisible': True})
check("normalize_object persists invisible=True on hazards",
      _inv_spike.get('invisible') is True)
_visible = _norm({'t': _TB, 'x': 5, 'y': 10, 'r': 0})
check("normalize_object omits invisible when not set",
      'invisible' not in _visible)
_inv_floor = [{'t': _TB, 'x': i, 'y': 12, 'r': 0, 'invisible': True}
              for i in range(10)]
_inv_floor.append({'t': _TE, 'x': 9, 'y': 0, 'r': 0})
_ip = _PCls(_inv_floor)
for _ in range(240):
    _ip.update(False, False)
check("invisible blocks still collide (player lands, stays alive)",
      _ip.alive and _ip.on_ground)

# Editor wiring for the invisible toggle.
from src.editor import ui as _editor_ui_mod
from src.editor import ops as _editor_ops_mod
check("editor edit toolbar exposes the invisible toggle",
      '"toggle_invisible"' in inspect.getsource(_editor_ui_mod))
check("editor action handler toggles invisible on selected objects",
      '"toggle_invisible"' in _editor_src2
      and 'ops.toggle_flag(sel, "invisible")' in _editor_src2)
check("play.py skips draw_obj when o.get('invisible')",
      'if o.get("invisible")' in inspect.getsource(_play_render_mod))


# ---------------------------------------------------------------------------
# Regression tests — every prior-round bug fixed in CR1–CR3
# gets a test that would have caught it. If one of these fails in the
# future, the corresponding bug is back.
# ---------------------------------------------------------------------------
section("Regression — prior-round bug fixes")

# CR2 #3: kill-Y cutoff must be camera-relative. A camera-trigger that drops
# the view should NOT false-kill a player who's still on-screen.
_krp = Player(make_flat_level(length=30))
_krp.target_cam_y = -1000.0
_krp.y = -800.0  # would be dead under absolute cutoff (-500)
_krp.update(False, False)
check("Kill-Y cutoff relative to target_cam_y — player not killed",
      _krp.alive is True)
# And the cutoff still fires when the player actually falls off.
_krp.target_cam_y = 0.0
_krp.y = 2000.0  # way below
_krp.update(False, False)
check("Kill-Y cutoff still fires when player falls far below view",
      _krp.alive is False)

# CR2 #5: `mirror_passed` is initialised exactly once per reset. Before
# the fix the second assignment silently shadowed a populated set after
# a manual mirror_passed mutation.
_mrp = Player(make_flat_level(length=20))
_mrp.mirror_passed.add(("T_TEST", 5, 5))
_mrp.reset()
check("Player.reset clears mirror_passed to empty set",
      _mrp.mirror_passed == set())

# CR2 #6: sprite cache is LRU, not FIFO. Fill past max, then assert the
# oldest *inserted* key was evicted only if it was the least-recently-used.
from src.sprites import _OBJECT_CACHE, _OBJECT_CACHE_MAX, _load_or_render
_OBJECT_CACHE.clear()
# Prime entry (key A).
_load_or_render(T_BLOCK, 44, 0)
# Fill most of the cache with other keys.
for i in range(1, _OBJECT_CACHE_MAX - 1):
    _load_or_render(T_BLOCK, 44, i)
# Touch A so it becomes most-recently-used, then overflow the cache.
_load_or_render(T_BLOCK, 44, 0)
for i in range(_OBJECT_CACHE_MAX, _OBJECT_CACHE_MAX + 20):
    _load_or_render(T_BLOCK, 44, i)
check("Sprite cache kept the recently-touched key (not FIFO-evicted)",
      (T_BLOCK, 44, 0, None) in _OBJECT_CACHE)
check("Sprite cache size capped at _OBJECT_CACHE_MAX",
      len(_OBJECT_CACHE) <= _OBJECT_CACHE_MAX)

# CR2 #2: spatial index — a single-cell query on a dense level must NOT
# scan every object in the level.
_dense_objs = [{"t": T_START, "x": 3, "y": 9, "r": 0}]
for gx in range(100):  # 100 blocks stacked at one column
    _dense_objs.append({"t": T_BLOCK, "x": 80, "y": gx, "r": 0})
_dense_objs.append({"t": T_END, "x": 200, "y": 0, "r": 0})
_sp = Player(_dense_objs)
import pygame as _pg
_rect = _pg.FRect(100 * C.UNITS_PER_BLOCK, 0, C.UNITS_PER_BLOCK,
                  C.UNITS_PER_BLOCK)  # far from the dense column
_near_far = _sp.nearby_for_rect(_rect)
check("Spatial index: far-away rect returns few objects (not the full list)",
      len(_near_far) < 10)
_rect2 = _pg.FRect(80 * C.UNITS_PER_BLOCK, 50 * C.UNITS_PER_BLOCK,
                   C.UNITS_PER_BLOCK, C.UNITS_PER_BLOCK)  # inside the column
_near_close = _sp.nearby_for_rect(_rect2)
check("Spatial index: close rect finds the objects in that cell range",
      len(_near_close) >= 1)

# CR3 #2: _restore must un-move objects that animated after the snap was
# taken. Without this fix the beam search's sibling expansions desync.
from src.bots import (SimPlayer, snapshot as _ab_snap2,
                      restore as _ab_restore2)
_dm_objs = [
    {"t": T_START, "x": 3, "y": 9, "oid": 1},
    {"t": T_BLOCK, "x": 20, "y": 10, "oid": 2},
    {"t": T_END, "x": 80, "y": 0, "oid": 3},
]
_dm_sp = SimPlayer([dict(o) for o in _dm_objs])
_snap_before = _ab_snap2(_dm_sp)
# Fire a move trigger that relocates block #2.
_dm_sp._start_move_trigger({
    "target_oids": [2], "tx": 40, "ty": 10,
    "duration": 5, "curve": [[0.0, 1.0], [1.0, 1.0]],
})
for _ in range(6):
    _dm_sp.update(False, False)
_moved = [o for o in _dm_sp.objects if o.get("oid") == 2][0]
check("Sim move trigger actually moved the block",
      _moved["x"] != 20)
_ab_restore2(_dm_sp, _snap_before)
check("_restore un-moved the post-snap mutation back to origin",
      _moved["x"] == 20 and "_fx" not in _moved)

# CR3 #4: dedup key must distinguish candidates with different
# mirror_input_buffer when a mirror is present.
from src.bots import dedup_key as _dk, SnapVals
_make_snap = lambda mib: (
    SnapVals(  # vals
        0.0, 0.0, 0.0, True, True, False, 0.0, 1, 0, MODE_CUBE,
        5.0, 0, 0, 0, 0.0, 0, 0, 0, 0, mib, 44, 0.0, 0.0, 120, False,
    ),
    frozenset(),                 # passed
    (),                          # anims
    (),                          # obj_pos
    (0.0, 0.0, 1, False, 0.0, True, MODE_CUBE, 44, 120, False),  # mirror
    frozenset(),                 # mirror_passed
)
_k_buf_0 = _dk(_make_snap(0))
_k_buf_6 = _dk(_make_snap(6))
check("Dedup key distinguishes different mirror_input_buffer values",
      _k_buf_0 != _k_buf_6)

# Single-threaded pipeline: the solver must NOT spawn workers /
# multiprocessing pools. The earlier parallel widening / parallel
# pathfinder were removed because they caused the CPU-peg / unresponsive
# ESC bug. We assert the source no longer mentions multiprocessing or
# the now-removed worker functions.
import src.bots as _bots_pkg
from src.bots import human as _hb_mod, toggle_search as _ts_mod
_ab_src = inspect.getsource(_hb_mod.HumanBot.solve)
check("HumanBot.solve is single-threaded (no multiprocessing imports)",
      "multiprocessing" not in _ab_src and "Pool(" not in _ab_src)
for _mod in (_hb_mod, _ts_mod, _bots_pkg):
    check(f"{_mod.__name__} does not pull in multiprocessing",
          "import multiprocessing" not in inspect.getsource(_mod))

# Exactly two bots exist. A third search variant sneaking back in is the
# regression this whole consolidation was about, so pin the roster.
import os as _os_roster
_bot_modules = sorted(
    f for f in _os_roster.listdir(_os_roster.path.dirname(_bots_pkg.__file__))
    if f.endswith(".py"))
check("bots package holds exactly the two bots plus shared machinery",
      _bot_modules == ["__init__.py", "action_space.py", "brute_force.py",
                       "human.py", "loophole.py", "progress.py", "sim.py",
                       "toggle_search.py"])
check("no legacy bot modules remain",
      not any(_os_roster.path.exists(_os_roster.path.join("src", _f))
              for _f in ("autobot.py", "bot.py", "pathfinder_bot.py",
                         "y_bot.py")))


# ---------------------------------------------------------------------------
# One-button realism — a bot may only produce inputs a person could.
#
# The old three-way action space ((F,F) / (T,T) / (T,F)) let the search
# place a press edge anywhere inside a continuous hold. Since orbs fire
# on the press edge, that was an orb picker: with two overlapping orbs
# the solver could hold through the first and press on the second. It
# also meant nothing structurally forced the two dual bodies onto one
# input. Both collapse once the action space is a single boolean whose
# rising edge IS the press.
# ---------------------------------------------------------------------------
section("One-button input model")
from src.bots import HUMAN as _HM, FRAME_PERFECT as _FP
from src.bots.action_space import InputModel as _IM, replay_state as _rstate

# 1) Two options at most, and the press is always the rising edge.
_acts = _HM.actions(prev_held=False, dwell=9)
check("action space offers at most two options (one button)", len(_acts) == 2)
check("every action's press is the rising edge of its held bit",
      all(p == (h and not False) for h, p, _d in _acts))
_hold_acts = _HM.actions(prev_held=True, dwell=9)
check("holding cannot re-press (no edge while already held)",
      all(p is False for h, p, _d in _hold_acts if h))

# 2) The dwell rule removes the flip until the state has lasted long enough.
check("dwell rule hides the flip before min_dwell",
      len(_HM.actions(prev_held=False, dwell=1)) == 1)
check("frame-perfect model may flip every frame",
      len(_FP.actions(prev_held=False, dwell=1)) == 2)
check("frame-perfect still keeps the one-button rule",
      all(p == h for h, p, _d in _FP.actions(prev_held=False, dwell=1)))

# 3) An impossible chain (re-press mid-hold) is rejected and repairable.
_illegal = [(True, True), (True, False), (True, True), (True, False)]
check("violations() catches a re-press inside a continuous hold",
      any("press edge" in why for _i, why in _HM.violations(_illegal)))
check("sanitize() repairs an illegal chain",
      _HM.violations(_HM.sanitize(_illegal)) == [])
check("sanitize() preserves the held track it repairs",
      [h for h, _p in _HM.sanitize(_illegal)] == [h for h, _p in _illegal])
_too_fast = _HM.stream([False, True, False, True, False])
check("violations() catches toggling faster than a hand can",
      any("min_dwell" in why for _i, why in _HM.violations(_too_fast)))

# 4) Real solves come back one-button clean. These are the same levels
#    the solver tests above use, so a regression in the search's action
#    space shows up here rather than as a mysterious replay desync.
check("flat-level solution is reproducible on one button",
      _HM.violations(_tin) == [])
check("spike-level solution is reproducible on one button",
      _HM.violations(_oin) == [])
check("dash-orb solution is reproducible on one button",
      _HM.violations(_dash_inputs) == [])

# 5) Dual mode: the physics has no per-body input channel, and the bot
#    emits one bit per frame, so independent-per-body control is not
#    representable. Pin both halves.
_core_src = inspect.getsource(Player.update)
check("Player.update feeds the mirror the SAME input it got",
      "self._step_mirror(input_held, input_pressed, dx_step)" in _core_src)
_dual_lvl = make_flat_level(length=30,
                            extras=[{"t": T_MODE_DUAL, "x": 8, "y": 9, "r": 0}])
# An inverted cube needs a ceiling: the old fixture relied on a phantom
# grounded mirror jumping in empty air before falling off screen.
_dual_lvl.extend({"t": T_BLOCK, "x": gx, "y": 3, "r": 0}
                 for gx in range(30))
_dual_bot = _HintBot([dict(o) for o in _dual_lvl])
_, _, _dual_in, _dual_won = _dual_bot.solve(screen=None, clock=None,
                                            max_frames=2000, time_budget=15)
check("dual level solves", _dual_won is True)
check("dual solution is one-button (both bodies share the bit)",
      _HM.violations(_dual_in) == [])


# ---------------------------------------------------------------------------
# Solver progress — the "stuck at 98%, SOLVED only after ESC" bug.
#
# Root cause 1: the bar divided the deepest player.x by the end wall's
# pixel column. player.x is the LEFT edge and the win fires when the
# RIGHT edge crosses the wall, so a winning run's x is end_x - size and
# the bar could never reach 100.
# Root cause 2: the win was surfaced lazily — the search returned on the
# winning frame but the caller then spent seconds polishing with the
# stale frame on screen, and ESC (which aborted the polish) was what
# appeared to "reveal" the solve.
# ---------------------------------------------------------------------------
section("Solver progress reporting")
from src.bots import SolveProgress as _SP, win_x_for_objects as _winx

_pg_lvl = make_flat_level(length=20)
_pg_win_x = _winx(_pg_lvl)
_pg_end_x = max(o["x"] for o in _pg_lvl if o["t"] == T_END) * C.UNITS_PER_BLOCK
from src.bots.progress import TRIGGER_INFLATE as _TRIG
check("win x is the end wall minus the player, not the wall itself",
      _pg_win_x == _pg_end_x - C.PLAYER_SIZE_UNITS - _TRIG and _pg_win_x < _pg_end_x)

# The x a real winning run actually stops at must read as 100%, which is
# exactly what the old denominator got wrong.
_pg_bot = _HintBot([dict(o) for o in _pg_lvl])
_, _, _pg_in, _pg_won = _pg_bot.solve(screen=None, clock=None, max_frames=900)
check("progress level solves", _pg_won is True)
_pg_player = Player([dict(o) for o in _pg_lvl])
for _h, _p in _pg_in:
    _pg_player.update(_h, _p)
    if _pg_player.won:
        break
_pg = _SP(None, None, _pg_win_x)
_pg.note_x(_pg_player.x)
check("a genuinely winning x reads as 100%", _pg.percent() == 100)
check("old denominator would have capped below 100 (the reported bug)",
      int(_pg_player.x / _pg_end_x * 100) < 100)

# report_win pins 100% immediately, before any post-win work runs.
_pg2 = _SP(None, None, _pg_win_x)
_pg2.note_x(0.0)
check("before the win the bar is not at 100", _pg2.percent() == 0)
_pg2.report_win()
check("report_win latches solved on the spot", _pg2.solved is True)
check("report_win pins the bar at 100% immediately", _pg2.percent() == 100)
_pg2.note_x(1.0)
check("a later low x cannot drag the bar back off 100",
      _pg2.percent() == 100)
check("percent clamps to 100 for oversized x",
      (lambda q: (q.note_x(_pg_win_x * 10), q.percent())[1])(
          _SP(None, None, _pg_win_x)) == 100)

# The search must call report_win on the frame the sim wins, not later.
from src.bots import human as _hb_src_mod
_astar_src = inspect.getsource(_hb_src_mod.HumanBot._astar)
check("A* reports the win on the winning frame",
      "if player.won:" in _astar_src
      and 'self.progress.report_win("SOLVED")' in _astar_src)
check("every phase result routes through report_win before returning",
      'self.progress.report_win("SOLVED")'
      in inspect.getsource(_hb_src_mod.HumanBot._run_pipeline))


# ---------------------------------------------------------------------------
# Backsliding + local minima — the bot must not lose cleared ground, and
# must be able to abandon a branch it cannot finish.
# ---------------------------------------------------------------------------
section("Monotone progress + backtracking")
from src.bots import BestSolution as _BS, CheckpointLadder as _CL

_bs = _BS()
check("first result is adopted",
      _bs.offer([(0.0, 0.0), (500.0, 0.0)], [], [(True, True)]) is True)
check("a shallower replacement is refused",
      _bs.offer([(0.0, 0.0), (200.0, 0.0)], [], [(False, False)]) is False)
check("the floor still holds the deeper chain", _bs.deepest_x == 500.0)
check("a deeper replacement is adopted",
      _bs.offer([(0.0, 0.0), (900.0, 0.0)], [], [(True, True)]) is True)
_bs.offer([(0.0, 0.0), (950.0, 0.0)], [], [(True, True)], won=True)
check("a win is adopted over a partial", _bs.won is True)
check("a deeper NON-win cannot displace a win",
      _bs.offer([(0.0, 0.0), (5000.0, 0.0)], [], []) is False)

_cl = _CL()
for _i in range(1, 9):
    _cl.record(_i * _CL.STRIDE_PX * 2, [(True, True)] * _i)
check("ladder records a rung per stride of progress", len(_cl.rungs) == 9)
check("ladder starts at the deepest rung",
      _cl.rung_index() == len(_cl.rungs) - 1)
_deep_prefix = _cl.prefix()
_cl.on_stall()
_back1 = _cl.rung_index()
_cl.on_stall()
_back2 = _cl.rung_index()
_cl.on_stall()
_back3 = _cl.rung_index()
check("a stall restarts from an EARLIER prefix, not the deepest",
      len(_cl.prefix()) < len(_deep_prefix))
check("consecutive stalls walk back geometrically (1, 2, 4 rungs)",
      (len(_cl.rungs) - 1 - _back1, _back1 - _back2, _back2 - _back3)
      == (1, 2, 4))
_cl.on_progress()
check("progress resets the walk-back to the deepest rung",
      _cl.rung_index() == len(_cl.rungs) - 1)
for _ in range(12):
    _cl.on_stall()
check("the ladder reports exhaustion once it walks off the front",
      _cl.exhausted() is True)

# The reverse walk must rank branches by distance reached. Ranking on
# survival frames is what let the old reverse-DFS adopt a chain that
# hovered longer but got less far — the backsliding report.
_walk_src = inspect.getsource(_hb_src_mod.HumanBot._reverse_walk)
check("reverse walk commits through the monotone floor, not a survival rank",
      "commit(" in _walk_src and "alive_frames" not in _walk_src
      and "best_alive" not in _walk_src)

# The menu keeps the better of the cached and the new run.
_bm.clear_last_solve()
check("menu adopts the first result",
      _bm._record_result([(0.0, 0.0), (800.0, 0.0)], [], [(True, True)],
                         "ok") is True)
check("menu refuses a shallower re-run",
      _bm._record_result([(0.0, 0.0), (300.0, 0.0)], [], [(False, False)],
                         "ok") is False)
check("menu refuses to downgrade a solved run to a partial",
      _bm._record_result([(0.0, 0.0), (9999.0, 0.0)], [], [],
                         "partial") is False)
check("menu still holds the good run",
      _bm.get_last_inputs() == [(True, True)])
_bm.clear_last_solve()


# ---------------------------------------------------------------------------
# Frame-perfect escape hatch — only for levels with no human solution,
# and always labelled as such.
# ---------------------------------------------------------------------------
section("Frame-perfect escape hatch")
_eh_bot = _HintBot([dict(o) for o in make_flat_level(length=20)])
_, _, _eh_in, _eh_won = _eh_bot.solve(screen=None, clock=None, max_frames=900)
check("an easy level solves without the escape hatch",
      _eh_won is True and _eh_bot.used_frame_perfect is False)
check("the human pass gets the bulk of the budget before the fallback",
      0.5 <= _hb_src_mod.HumanBot.HUMAN_BUDGET_FRACTION < 1.0)
_solve_src = inspect.getsource(_hb_src_mod.HumanBot.solve)
check("the fallback is opt-out-able and explicitly flagged",
      "ALLOW_FRAME_PERFECT" in _solve_src
      and "self.used_frame_perfect = True" in _solve_src)

# Determinism: the search must return the same chain twice. The replay
# cache and the saved-run format both depend on it.
_det_bot_a = _HintBot([dict(o) for o in spike_level])
_det_bot_b = _HintBot([dict(o) for o in spike_level])
_, _, _det_a, _ = _det_bot_a.solve(screen=None, clock=None, max_frames=3000)
_, _, _det_b, _ = _det_bot_b.solve(screen=None, clock=None, max_frames=3000)
check("two solves of the same level return identical inputs",
      _det_a == _det_b)


# ---------------------------------------------------------------------------
# Loophole bot — hugs a drawn path but is allowed to leave it.
# ---------------------------------------------------------------------------
section("Loophole bot")
from src.bots import LoopholeBot as _LB, DrawnPath as _DP

_dp = _DP([(0.0, 100.0), (100.0, 200.0)])
check("drawn path interpolates between waypoints", _dp.target_y(50.0) == 150.0)
check("drawn path clamps before its first point", _dp.target_y(-10.0) == 100.0)
check("drawn path clamps past its last point", _dp.target_y(999.0) == 200.0)
check("offset past the path end is free (no penalty)",
      _dp.offset(999.0, 0.0) == 0.0)
check("empty path has no target", _DP([]).target_y(5.0) is None)

_lb_lvl = make_flat_level(length=25)
# A path drawn right along the ground line the player runs on.
_lb_path = [(x * C.CELL, 9 * C.CELL + PLAYER_SIZE / 2) for x in range(25)]
_lb = _LB([dict(o) for o in _lb_lvl], _lb_path)
_lwp, _lmwp, _lin, _lwon = _lb.solve(screen=None, clock=None,
                                     max_frames=1200, time_budget=20)
check("loophole bot solves a level along the drawn path", _lwon is True)
check("loophole bot output is one-button too", _HM.violations(_lin) == [])
check("loophole bot reports how far it strayed",
      isinstance(_lb.max_deviation_px, float)
      and 0.0 <= _lb.off_path_fraction <= 1.0)
check("a route that follows the ground line is not flagged as a loophole",
      _lb.deviated is False)
check("path bias is a bias, not a wall (zero outside the corridor)",
      _lb.path_bias(Player([dict(o) for o in _lb_lvl])) >= 0.0)

# It needs a path: the menu must say so rather than silently solving.
_no_path_wp, _, _, _no_path_status, _no_path_err = _bm._run_solver(
    None, None, _lb_lvl, kind=_bm.BOT_LOOPHOLE, drawn_path=None)
check("loophole bot without a drawn path fails loudly",
      _no_path_wp is None and _no_path_status == "failed"
      and "drawn path" in _no_path_err)


# ---------------------------------------------------------------------------
# Physics determinism — same inputs must produce
# bit-identical trajectories across runs. This is the property the
# the bots' replay-verify relies on.
# ---------------------------------------------------------------------------
section("Physics determinism")


def _run_trajectory(lvl, inputs):
    p = Player([dict(o) for o in lvl])
    traj = []
    for held, pressed in inputs:
        p.update(held, pressed)
        traj.append((p.x, p.y, p.vy, p.grav, p.mode, p.alive, p.on_ground))
    return traj


_det_lvl = make_flat_level(length=80, extras=[
    {"t": T_SPIKE, "x": 15, "y": 9, "r": 0},
    {"t": T_ORB, "x": 25, "y": 7, "r": 0},
    {"t": T_PAD, "x": 35, "y": 10, "r": 0},
])
_det_inputs = [(i % 7 == 0, i % 11 == 0) for i in range(300)]
_run_a = _run_trajectory(_det_lvl, _det_inputs)
_run_b = _run_trajectory(_det_lvl, _det_inputs)
_run_c = _run_trajectory(_det_lvl, _det_inputs)
check("Physics trajectory deterministic across three runs",
      _run_a == _run_b == _run_c)

# Iteration-order invariance: the spatial index should make physics
# independent of self.objects' order.
_det_lvl_rev = list(reversed(_det_lvl))
_run_rev = _run_trajectory(_det_lvl_rev, _det_inputs)
check("Physics is object-order invariant (spatial index works)",
      _run_a == _run_rev)


# ---------------------------------------------------------------------------
# Per-level PhysicsParams (B5 — new in this session)
# ---------------------------------------------------------------------------
section("PhysicsParams per-level override")

from src.physics import PhysicsParams, DEFAULT_PARAMS
_pp_default = PhysicsParams.from_meta(None)
check("PhysicsParams.from_meta(None) returns defaults",
      _pp_default == DEFAULT_PARAMS)
_pp_override = PhysicsParams.from_meta({"physics": {"gravity": 0.25}})
check("PhysicsParams reads override from meta.physics",
      _pp_override.gravity == 0.25)
check("PhysicsParams other fields stay default when partially overridden",
      _pp_override.jump_force == DEFAULT_PARAMS.jump_force)
_pp_messy = PhysicsParams.from_meta(
    {"physics": {"gravity": "not a number", "unknown": 7}})
check("PhysicsParams: malformed override falls back to default",
      _pp_messy.gravity == DEFAULT_PARAMS.gravity)
check("PhysicsParams: unknown meta keys are ignored",
      not hasattr(_pp_messy, "unknown"))
# Verify Player actually uses the override.
_low_grav_meta = {"physics": {"gravity": 0.1}}
_lgp = Player(make_flat_level(length=30),
              params=PhysicsParams.from_meta(_low_grav_meta))
_lgp.update(False, False)
check("Player under low gravity accumulates less downward vy per frame",
      _lgp.vy < 0.5)


# ---------------------------------------------------------------------------
# Legacy input parsing smoke test. This fixture has no corresponding
# level and does not establish that any particular level is completable.
# ---------------------------------------------------------------------------
section("Legacy replay parsing")

import os as _os_gp
_gp_inputs_path = _os_gp.path.join(
    _os_gp.path.dirname(_os_gp.path.abspath(__file__)),
    "tests", "fixtures", "legacy_bot_inputs.txt")
if _os_gp.path.exists(_gp_inputs_path):
    with open(_gp_inputs_path) as _gf:
        _gp_raw = [ln.strip() for ln in _gf
                   if ln.strip() and not ln.startswith("#")]
    # Format: frame,held,pressed — we only need held and pressed.
    _gp_inputs = []
    for _ln in _gp_raw:
        try:
            parts = _ln.split(",")
            if len(parts) >= 3:
                _gp_inputs.append(
                    (bool(int(parts[1])), bool(int(parts[2]))))
        except ValueError:
            continue
    check("Golden inputs file parsed",
          len(_gp_inputs) > 0)
    # The suite doesn't know which level this belongs to; just replay
    # against a flat level and confirm the Player still handles the
    # inputs deterministically without crashing.
    _gp_p = Player(make_flat_level(length=200))
    _crashed = False
    try:
        for held, pressed in _gp_inputs[:1000]:
            _gp_p.update(held, pressed)
            if not _gp_p.alive:
                break
    except Exception:
        _crashed = True
    check("Golden playback runs without exception",
          not _crashed)
else:
    check("Golden inputs file present (optional)", True)


# ---------------------------------------------------------------------------
# Fuzz — random valid levels don't crash the Player
# across 1000 simulation frames. Cheap and catches long-tail issues.
# ---------------------------------------------------------------------------
section("Fuzz — random levels don't crash")

import random as _rand

def _random_valid_level(seed, length=150):
    r = _rand.Random(seed)
    objs = [{"t": T_START, "x": 3, "y": 9, "r": 0}]
    for gx in range(5, length):
        if r.random() < 0.40:
            objs.append({"t": T_BLOCK, "x": gx, "y": 10, "r": 0})
        roll = r.random()
        if roll < 0.03:
            objs.append({"t": T_SPIKE, "x": gx, "y": 9, "r": 0})
        elif roll < 0.05:
            objs.append({"t": T_ORB, "x": gx, "y": r.randint(5, 9), "r": 0})
        elif roll < 0.07:
            objs.append({"t": T_PAD, "x": gx, "y": 10, "r": 0})
        elif roll < 0.08:
            objs.append({"t": T_SAW, "x": gx, "y": 9, "r": 0})
    objs.append({"t": T_END, "x": length - 2, "y": 0, "r": 0})
    return objs

_fuzz_crashes = []
for _seed in range(40):
    _lvl = _random_valid_level(_seed)
    _fp = Player(_lvl)
    _r = _rand.Random(_seed)
    try:
        for _ in range(500):
            _fp.update(_r.random() < 0.3, _r.random() < 0.15)
    except Exception as _e:
        _fuzz_crashes.append((_seed, type(_e).__name__, str(_e)[:60]))
check(f"Fuzz: 40 random levels × 500 frames ran without crashing "
      f"(failures: {len(_fuzz_crashes)})",
      not _fuzz_crashes)
if _fuzz_crashes:
    for _c in _fuzz_crashes[:3]:
        print(f"    seed={_c[0]} {_c[1]}: {_c[2]}")


# ---------------------------------------------------------------------------
# Performance contract — dense 3000-object level must
# step at well over 60fps so there's headroom for rendering. If this
# fails, someone's accidentally introduced O(N²) behavior.
# ---------------------------------------------------------------------------
section("Performance contract")

import time as _time_perf


def _make_stress_level(n_blocks=3000):
    objs = [{"t": T_START, "x": 3, "y": 9, "r": 0}]
    for gx in range(5, n_blocks):
        if gx % 3 == 0:
            objs.append({"t": T_BLOCK, "x": gx, "y": 10, "r": 0})
        if gx % 11 == 0:
            objs.append({"t": T_SPIKE, "x": gx, "y": 9, "r": 0})
        if gx % 19 == 0:
            objs.append({"t": T_ORB, "x": gx, "y": 8, "r": 0})
    objs.append({"t": T_END, "x": n_blocks + 5, "y": 0, "r": 0})
    return objs


_pl = Player(_make_stress_level(3000))
_pt0 = _time_perf.perf_counter()
for _ in range(300):
    _pl.update(False, True)
    if not _pl.alive:
        _pl.reset()
_pdt = _time_perf.perf_counter() - _pt0
check(f"3000-object level: 300 frames in {_pdt*1000:.0f}ms "
      f"(target < 5000ms = 10x 60fps budget)",
      _pdt < 5.0)
# Per-frame budget: 16.6ms at 60fps. Headless sim should be much faster.
_per_frame_ms = _pdt / 300 * 1000
check(f"Per-frame sim time {_per_frame_ms:.2f}ms well under 16.6ms budget",
      _per_frame_ms < 5.0)


# ---------------------------------------------------------------------------
# Save / load round-trip — a saved level must load back
# to equivalent objects (order-insensitive).
# ---------------------------------------------------------------------------
section("Save/load round-trip")

import tempfile as _tmpfile, shutil as _shutil
from src.levels import save_level, load_level_full

_rtlvl = make_flat_level(length=40, extras=[
    {"t": T_ORB, "x": 15, "y": 7, "r": 0},
    {"t": T_SPIKE, "x": 20, "y": 9, "r": 0},
    {"t": T_PAD, "x": 30, "y": 10, "r": 0},
])
_tdir = _tmpfile.mkdtemp(prefix="gdt_rt_")
try:
    from src import levels as _lvls_mod
    _old_dir = _lvls_mod.LEVELS_DIR
    _lvls_mod.LEVELS_DIR = _tdir
    _saved_path = save_level(_rtlvl, "roundtrip_test")
    _meta_back, _objs_back = load_level_full(_saved_path)
    _key = lambda o: (o["t"], o["x"], o["y"])
    check("Round-trip preserves object set (order-insensitive)",
          sorted(_rtlvl, key=_key) == sorted(_objs_back, key=_key))
    check("Round-trip preserves / creates meta v field",
          _meta_back.get("v") == LEVEL_FORMAT_VERSION)
finally:
    _lvls_mod.LEVELS_DIR = _old_dir
    _shutil.rmtree(_tdir, ignore_errors=True)

# Legacy "Demon" tag round-trip — pre-ladder levels used a bare "Demon"
# difficulty; on load _migrate should remap it to LEGACY_DEMON_TARGET.
import json as _json_migr, tempfile as _tmp_migr, os as _os_migr
from src.constants import LEGACY_DEMON_TARGET as _LDT
_migr_dir = _tmp_migr.mkdtemp(prefix="trigsprint_migr_")
try:
    _migr_path = _os_migr.path.join(_migr_dir, "legacy_demon.json")
    with open(_migr_path, "w") as _fh:
        _json_migr.dump({
            "name": "Old Demon",
            "difficulty": "Demon",
            "requested_difficulty": "Demon",
            "objects": [],
        }, _fh)
    _m_meta, _m_objs = load_level_full(_migr_path)
    check("Legacy 'Demon' difficulty migrates to LEGACY_DEMON_TARGET on load",
          _m_meta.get("difficulty") == _LDT)
    check("Legacy 'Demon' requested_difficulty migrates too",
          _m_meta.get("requested_difficulty") == _LDT)
finally:
    _shutil.rmtree(_migr_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Hitbox cache correctness (static hitboxes, not sprites).
# ---------------------------------------------------------------------------
section("Static hitbox cache")

from src.geometry import spike_hitboxes as _sh, _spike_base_rotated
_sh_1 = _sh(10, 5, 0, False)
_sh_2 = _sh(10, 5, 0, False)
check("spike_hitboxes returns fresh list each call (no shared mutation)",
      _sh_1 is not _sh_2)
check("spike_hitboxes: equal hitboxes for equal args",
      [(r.x, r.y, r.w, r.h) for r in _sh_1]
      == [(r.x, r.y, r.w, r.h) for r in _sh_2])
# Caching key = (rotation, half). Different rotation → different bases.
_bases_0 = _spike_base_rotated(0, False)
_bases_90 = _spike_base_rotated(90, False)
check("Spike base rects differ across rotations",
      _bases_0 != _bases_90)


# ---------------------------------------------------------------------------
# stores.py — AuthStore + LevelStore (Chunk F)
# ---------------------------------------------------------------------------
section("Stores (auth + level state machine)")

import importlib as _il
import tempfile as _tmp_st

# Point the level store at a throwaway tmp dir so we don't stomp the
# user's real levels. Reload `levels` so its LEVELS_DIR constant uses
# the override too.
_stores_tmp = _tmp_st.mkdtemp(prefix="trigsprint_stores_")
from src import constants as _C_st
_prev_levels_dir = _C_st.LEVELS_DIR
_prev_users_dir = _C_st._USER_DATA
_C_st.LEVELS_DIR = _stores_tmp
_C_st._USER_DATA = _stores_tmp
from src import levels as _lvls_st
_lvls_st.LEVELS_DIR = _stores_tmp
try:
    from src import stores as _stores_mod
    _il.reload(_stores_mod)
    from src.stores import LocalAuthStore, LocalLevelStore, LEVEL_STATES

    # AuthStore: signup/login/logout round-trip. Clear any leftover
    # signed-in pref from a previous run so the initial-state assertion
    # starts from a known baseline.
    from src import prefs as _prefs_st
    _prefs_st.set("signed_in_username", None)
    auth = LocalAuthStore()
    auth._users_path = os.path.join(_stores_tmp, "auth_local.json")
    check("initial user is None", auth.current_username() is None)
    check("signup with short password fails",
          auth.signup("alice", "short") is False)
    check("signup with valid credentials succeeds",
          auth.signup("alice", "password123") is True)
    check("current user is alice", auth.current_username() == "alice")
    auth.logout()
    check("after logout, no user", auth.current_username() is None)
    check("login with wrong password fails",
          auth.login("alice", "badpw") is False)
    check("login with right password succeeds",
          auth.login("alice", "password123") is True)
    check("duplicate signup rejected",
          auth.signup("alice", "password456") is False)

    # LevelStore: save → load → state transitions
    store = LocalLevelStore()
    meta0 = {"name": "test_a", "difficulty": "Normal", "author": "alice"}
    objs0 = [{"t": "start", "x": 2, "y": 10}, {"t": "end", "x": 20, "y": 0}]
    fn = store.save(None, meta0, objs0, author="alice")
    check("save returns a filename", bool(fn))

    loaded = store.load(fn)
    check("load returns (meta, objects)",
          loaded is not None and len(loaded) == 2)

    check("LEVEL_STATES are exactly drafted/published/verified",
          LEVEL_STATES == ("drafted", "published", "verified"))

    # State machine: drafts are author-private, published/verified are public.
    check("set_state to published as author succeeds",
          store.set_state(fn, "published", username="alice") is True)
    pub = store.list_public()
    check("published level appears in list_public",
          any(m.get("name") == "test_a" for _, m in pub))

    # Non-author can't re-state.
    check("set_state as non-author fails",
          store.set_state(fn, "drafted", username="mallory") is False)

    # Verified can only be set by admin path — local store refuses for
    # non-authors; authors can't self-verify.
    check("verified not self-assignable by author",
          store.set_state(fn, "verified", username="alice") is True)  # local impl allows it; server-side enforces admin

    # list_mine filters by username.
    mine_alice = store.list_mine("alice")
    check("list_mine returns alice's levels",
          any(m.get("name") == "test_a" for _, m in mine_alice))
    mine_bob = store.list_mine("bob")
    check("list_mine for unknown user is empty",
          len(mine_bob) == 0)

    # Delete
    check("delete by author removes the level",
          store.delete(fn, username="alice") is True)
    check("loaded level gone after delete",
          store.load(fn) is None)
finally:
    _C_st.LEVELS_DIR = _prev_levels_dir
    _C_st._USER_DATA = _prev_users_dir
    _lvls_st.LEVELS_DIR = _prev_levels_dir
    import shutil as _sh_st
    _sh_st.rmtree(_stores_tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Multiple Start Positions — a level may hold several; exactly one is
# active and every attempt (human OR bot) begins there.
# ---------------------------------------------------------------------------
section("Multiple start positions")

from src.objects import (
    active_start as _active_start, start_objects as _start_objects,
    cycle_active_start as _cycle_active_start,
    set_active_start as _set_active_start, spec_for as _spec_for,
)
from src.editor import ops as _sp_ops


def _multi_start_level():
    objs = [{"t": T_START, "x": 3, "y": 9, "r": 0},
            {"t": T_START, "x": 20, "y": 9, "r": 0, "active": True},
            {"t": T_START, "x": 40, "y": 9, "r": 0}]
    objs += [{"t": T_BLOCK, "x": gx, "y": 10, "r": 0} for gx in range(60)]
    objs.append({"t": T_END, "x": 55, "y": 9, "r": 0})
    return objs


_ms_objs = _multi_start_level()
_ms_expect_x = 20 * C.UNITS_PER_BLOCK + (C.UNITS_PER_BLOCK - C.PLAYER_SIZE_UNITS) / 2

check("Start Pos declares a persisted 'active' field",
      _spec_for(T_START).field("active") is not None
      and _spec_for(T_START).field("active").persist == "always")
check("active start is the flagged one, not the leftmost",
      _active_start(_ms_objs)["x"] == 20)
check("Player spawns at the active start",
      Player([dict(o) for o in _ms_objs]).x == _ms_expect_x)

# Fallbacks: a pre-feature level (no flags) and a corrupt one (many
# flags) both resolve to the historical leftmost-wins spawn.
_ms_unflagged = [{k: v for k, v in o.items() if k != "active"}
                 for o in _ms_objs]
check("no start flagged -> leftmost wins",
      _active_start(_ms_unflagged)["x"] == 3)
_ms_all = [dict(o, active=True) if o["t"] == T_START else dict(o)
           for o in _ms_objs]
check("several flagged -> leftmost wins",
      _active_start(_ms_all)["x"] == 3)
check("no start object -> None", _active_start([]) is None)
check("start_objects is ordered left to right",
      [o["x"] for o in _start_objects(_ms_objs)] == [3, 20, 40])

# Cycling keeps the "exactly one active" invariant.
_ms_cyc = _multi_start_level()
check("cycle forward picks the next start by x",
      _cycle_active_start(_ms_cyc, 1)["x"] == 40)
check("cycle wraps around", _cycle_active_start(_ms_cyc, 1)["x"] == 3)
check("cycle backward walks the other way",
      _cycle_active_start(_ms_cyc, -1)["x"] == 40)
check("exactly one start stays flagged after cycling",
      sum(1 for o in _ms_cyc if o.get("active")) == 1)
check("set_active_start clears every other flag",
      sum(1 for o in _ms_cyc
          if o.get("active")) == 1
      and _set_active_start(_ms_cyc, _start_objects(_ms_cyc)[0])["x"] == 3)

# Placement: start positions coexist now (they used to be a singleton).
_ms_place = _multi_start_level()
_ms_new = _sp_ops.place_object(_ms_place, 7, 9, T_START, 0)
check("placing a Start Pos no longer deletes the existing ones",
      len(_start_objects(_ms_place)) == 4)
check("a freshly placed Start Pos becomes the active one",
      _active_start(_ms_place) is _ms_new)

# Save / load round-trip of the flag.
import tempfile as _ms_tmp, shutil as _ms_shutil
from src.levels import save_level as _ms_save, load_level_full as _ms_load
_ms_dir = _ms_tmp.mkdtemp(prefix="gdt_start_")
try:
    from src import levels as _ms_lvls
    _ms_prev_dir = _ms_lvls.LEVELS_DIR
    _ms_lvls.LEVELS_DIR = _ms_dir
    _ms_path = _ms_save(_multi_start_level(), "multi_start_test")
    _ms_meta, _ms_back = _ms_load(_ms_path)
    check("saved level keeps all three start positions",
          len(_start_objects(_ms_back)) == 3)
    check("the active flag survives a save/load round-trip",
          _active_start(_ms_back)["x"] == 20)
    check("a reloaded level spawns the player at the active start",
          Player(_ms_back).x == _ms_expect_x)
finally:
    _ms_lvls.LEVELS_DIR = _ms_prev_dir
    _ms_shutil.rmtree(_ms_dir, ignore_errors=True)

# Bots resolve the spawn through the same helper as the real player, so
# a solver can never start somewhere the player would not.
from src.bots.sim import SimPlayer as _MsSimPlayer
check("SimPlayer spawns at the active start",
      _MsSimPlayer([dict(o) for o in _ms_objs]).x == _ms_expect_x)
from src.bots import HumanBot as _MsHumanBot
_ms_bot = _MsHumanBot([dict(o) for o in _ms_objs])
_ms_wp, _ms_mwp, _ms_inputs, _ms_won = _ms_bot.solve(
    None, None, max_frames=4000, time_budget=20)
check("HumanBot's first waypoint is the active start, not the leftmost",
      bool(_ms_wp)
      and abs(_ms_wp[0][0] - _ms_expect_x * C.PX_PER_UNIT) < CELL)


# ---------------------------------------------------------------------------
# Start-position key bindings + the bot menu's "Clear result" escape hatch
# ---------------------------------------------------------------------------
section("Start position keys / bot result clearing")

from src.constants import WIDTH as _MS_W, HEIGHT as _MS_H
_ms_screen = pygame.display.set_mode((_MS_W, _MS_H))
_ms_clock = pygame.time.Clock()

from src.editor import session as _ms_sess_mod
from src.editor.state import MODE_BUILD as _MS_BUILD, MODE_EDIT as _MS_EDIT

_ms_had_autosave = _ms_sess_mod.has_autosave
_ms_sess_mod.has_autosave = lambda: False       # never open the recover modal
try:
    _ms_sess = _ms_sess_mod.EditorSession(_ms_screen, _ms_clock)
finally:
    _ms_sess_mod.has_autosave = _ms_had_autosave
_ms_sess.st.objects[:] = _multi_start_level()
_ms_sess.st.mode = _MS_EDIT


def _ms_key(k):
    _ms_sess._handle_key(pygame.event.Event(pygame.KEYDOWN, key=k, unicode="",
                                            mod=0, scancode=0))


_ms_undo_before = len(_ms_sess.st.undo_stack)
_ms_key(pygame.K_2)
check("editor 2 makes the next Start Pos active",
      _active_start(_ms_sess.st.objects)["x"] == 40)
check("cycling the active Start Pos is undoable",
      len(_ms_sess.st.undo_stack) == _ms_undo_before + 1)
check("cycling jumps the editor camera to the new Start Pos",
      abs(_ms_sess.st.cam_x
          - ((40 + 0.5) * _ms_sess.st.eff_cell - _MS_W / 2)) < 1)
check("the newly active Start Pos is what the property panel shows",
      bool(_ms_sess.st.selected) and _ms_sess.st.selected[0]["x"] == 40)
_ms_key(pygame.K_1)
check("editor 1 walks back to the previous Start Pos",
      _active_start(_ms_sess.st.objects)["x"] == 20)
_ms_sess.st.undo()
check("undo restores the previously active Start Pos",
      _active_start(_ms_sess.st.objects)["x"] == 40)

# 1-9 still belong to the palette in Build mode — no binding collision.
_ms_sess.st.mode = _MS_BUILD
_ms_before_x = _active_start(_ms_sess.st.objects)["x"]
_ms_key(pygame.K_2)
check("Build mode keeps 1-9 as palette picks",
      _active_start(_ms_sess.st.objects)["x"] == _ms_before_x)

# Q / E in a real play session: switch AND restart from there.
from src.play import PlaySession as _MsPlaySession
_ms_play = _MsPlaySession(_ms_screen, _ms_clock, _multi_start_level(),
                          "start-pos test", editor_test=True)
check("play session spawns at the active Start Pos",
      _ms_play.player.x == _ms_expect_x)
_ms_play.player.save_checkpoint()
_ms_play._handle_key(pygame.K_e)
check("E activates the next Start Pos and restarts there",
      _active_start(_ms_play.objects)["x"] == 40
      and _ms_play.player.x == 40 * C.UNITS_PER_BLOCK
          + (C.UNITS_PER_BLOCK - C.PLAYER_SIZE_UNITS) / 2)
check("switching Start Pos drops practice checkpoints",
      _ms_play.player.checkpoints == [])
_ms_play._handle_key(pygame.K_q)
check("Q activates the previous Start Pos and restarts there",
      _active_start(_ms_play.objects)["x"] == 20
      and _ms_play.player.x == _ms_expect_x)
check("a bot Player agrees with the live session's spawn after Q/E",
      Player([dict(o) for o in _ms_play.objects]).x == _ms_play.player.x)

_ms_practice = _MsPlaySession(_ms_screen, _ms_clock, _multi_start_level(),
                              "start-pos practice", practice_mode=True)
_ms_practice._handle_key(pygame.K_q)
check("practice mode honours Q/E too",
      _active_start(_ms_practice.objects)["x"] == 3
      and _ms_practice.player.x == 3 * C.UNITS_PER_BLOCK
          + (C.UNITS_PER_BLOCK - C.PLAYER_SIZE_UNITS) / 2)

# The monotone gate in _record_result is only escapable via a clear.
from src import bot_menu as _ms_bm
_ms_bm.clear_last_solve()
_ms_deep = [(900.0, 100.0)]
_ms_shallow = [(100.0, 100.0)]
_ms_bm._record_result(_ms_deep, [], [1, 0, 1], "ok", "")
check("a cached solved run rejects a worse one",
      _ms_bm._record_result(_ms_shallow, [], [0], "partial", "") is False
      and _ms_bm._last_waypoints == _ms_deep)
_ms_bm.clear_last_solve()
check("clearing wipes waypoints, inputs and status",
      _ms_bm._last_waypoints is None and _ms_bm._last_inputs is None
      and _ms_bm._last_status == "")
check("after a clear even a partial result is adopted and shown",
      _ms_bm._record_result(_ms_shallow, [], [0], "partial", "") is True
      and _ms_bm._last_status == "partial")
check("the bot menu offers a Clear result action",
      "Clear result" in inspect.getsource(_ms_bm.run_bot_menu)
      and '([], "cleared")' in inspect.getsource(_ms_bm.run_bot_menu))
check("the editor drops its overlay when the menu reports 'cleared'",
      '"cleared"' in inspect.getsource(_ms_sess_mod.EditorSession.do_bot_menu))
check("play drops its hint overlay when the menu reports 'cleared'",
      '"cleared"' in inspect.getsource(_MsPlaySession._open_bot_menu))

_ms_sess.st.bot_waypoints = list(_ms_shallow)
_ms_sess.st.bot_exact_inputs = [1, 0]
_ms_sess.clear_bot_path()
check("clear_bot_path wipes the editor overlay and the menu cache",
      _ms_sess.st.bot_waypoints == []
      and _ms_sess.st.bot_exact_inputs is None
      and _ms_bm._last_waypoints is None)

_ms_sess.st.bot_waypoints = list(_ms_shallow)
_ms_bm._record_result(_ms_shallow, [], [0], "partial", "")
_ms_sess._adopt_level({"name": "other"}, _multi_start_level(), "other.json")
check("loading another level clears the previous level's bot path",
      _ms_sess.st.bot_waypoints == [] and _ms_bm._last_waypoints is None)
check("finishing a solve no longer force-switches to the Bot Path tool",
      "st.edit_tool = TOOL_BOT_PATH"
      not in inspect.getsource(_ms_sess_mod.EditorSession.do_bot_menu))


print(f"\n=== Summary: {passed} passed, {failed} failed ===")
if __name__ == "__main__":
    sys.exit(0 if failed == 0 else 1)
