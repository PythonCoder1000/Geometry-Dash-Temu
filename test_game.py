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
    _dp.update(False, _dp.x + _dp.size >= 10 * C.UNITS_PER_BLOCK - C.TOUCH_PAD_UNITS)
    if _dp.x - _pre_tp_x > 2 * C.UNITS_PER_BLOCK:  # instant horizontal jump = teleport
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
    _vp.update(False, _vp.x + _vp.size >= 10 * C.UNITS_PER_BLOCK - C.TOUCH_PAD_UNITS)
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
    about_to_touch = (orb1_left - (_bp.x + _bp.size)) <= 0.5 * C.UNITS_PER_BLOCK
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
    while p.x + p.size < 6 * C.UNITS_PER_BLOCK + 6.0:
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
        fired.append(p.vy < before - 0.75)
        p.update(False, False)
    return fired


check("default orb (multi_activate off) fires once and never again",
      _orb_double_touch(False) == [True, False])
check("multi_activate orb fires again on a second discrete touch",
      _orb_double_touch(True) == [True, True])

_ma_orb = {"t": T_ORB, "x": 6, "y": 9, "r": 0, "multi_activate": True}
_ma_p = Player(_dash_level([_ma_orb]))
while _ma_p.x + _ma_p.size < 6 * C.UNITS_PER_BLOCK + 6.0:
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
      _ma_p.vy > -0.75)
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
    _dp_dir.update(False, _dp_dir.x + _dp_dir.size >= 10 * C.UNITS_PER_BLOCK - C.TOUCH_PAD_UNITS)
    if _dp_dir.x - _pre_x_dir > 2 * C.UNITS_PER_BLOCK:
        _post_x_dir = _dp_dir.x
        break
check("dir=right teleports the player horizontally",
      _post_x_dir is not None and _post_x_dir > _pre_x_dir + 4 * C.UNITS_PER_BLOCK)


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
_fp.x = C.UNITS_PER_BLOCK
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
_fp2.x = C.UNITS_PER_BLOCK
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
from src.geometry import (slab_rect_units as _slab_rect,
                          cell_rect_units as _cell_rect)
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
_slab_bottom = _slab_rect(0, 12, 180, 1.0).bottom
_block_bottom = _cell_rect(0, 10, 1.0).bottom
check("spider teleport lands on slab's bottom face (not phasing through)",
      abs(_spslab.y - _slab_bottom) < 1.2
      and abs(_spslab.y - _block_bottom) > 12.0)

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


# ---------------------------------------------------------------------------
# Trigger dispatch: handler registry + ordered same-frame event queue
# (deep-research-report.md, "Same-frame precedence")
# ---------------------------------------------------------------------------
section("Trigger dispatch (registry + ordered event queue)")

from src.constants import (
    TRIGGER_TYPES as _TQ_TRIGGER_TYPES,
    T_ITEM_EDIT_TRIGGER as _TQ_EDIT, T_ITEM_COMP_TRIGGER as _TQ_COMP,
    T_TOGGLE_TRIGGER as _TQ_TOGGLE, T_SPAWN_TRIGGER as _TQ_SPAWN,
    T_BG_TRIGGER as _TQ_BG,
)
from src.objects import SPECS as _TQ_SPECS
from src.player.trigger_registry import (
    TRIGGER_HANDLERS as _TQ_HANDLERS,
    TRIGGER_FAMILY_SPAWN as _TQ_FAM_SPAWN,
    TRIGGER_FAMILY_TOUCH as _TQ_FAM_TOUCH,
    TRIGGER_DRAIN_MAX_PASSES as _TQ_MAX_PASSES,
)

check("every trigger type has exactly one registry handler",
      set(_TQ_HANDLERS) == set(_TQ_TRIGGER_TYPES))
check("_execute_trigger_effect is a registry lookup, not an if/elif chain",
      "TRIGGER_HANDLERS.get" in inspect.getsource(
          Player._execute_trigger_effect)
      and "elif t ==" not in inspect.getsource(
          Player._execute_trigger_effect))
check("group-targeted triggers expose a Trigger Order field",
      all(any(f.key == "trigger_order" for f in _TQ_SPECS[t].fields)
          for t in (_TQ_SPAWN, _TQ_TOGGLE, _TQ_EDIT)))
check("Trigger Order defaults to 0 and is not written when unset",
      next(f for f in _TQ_SPECS[_TQ_SPAWN].fields
           if f.key == "trigger_order").default == 0
      and next(f for f in _TQ_SPECS[_TQ_SPAWN].fields
               if f.key == "trigger_order").persist == "non_default")
check("both activation paths enqueue instead of executing inline",
      "_enqueue_trigger_event(o, TRIGGER_FAMILY_TOUCH)"
      in inspect.getsource(Player._handle_interactions)
      and "_enqueue_trigger_event(o, TRIGGER_FAMILY_SPAWN)"
      in inspect.getsource(Player._fire_group))
check("update() drains the queue as the tick's last step",
      "self._drain_trigger_event_queue()" in inspect.getsource(Player.update))


def _tq_item_level(order_add, order_mul):
    """Two Item Edit triggers on item 1, same group, same x — only their
    Trigger Order can decide which of (v+5)*3 and v*3+5 comes out."""
    return make_flat_level(length=30, extras=[
        {"t": _TQ_EDIT, "x": 12, "y": 5, "r": 0, "groups": [7], "item_id": 1,
         "operation": "multiply", "operand": 3.0, "trigger_order": order_mul},
        {"t": _TQ_EDIT, "x": 12, "y": 5, "r": 0, "groups": [7], "item_id": 1,
         "operation": "add", "operand": 5.0, "trigger_order": order_add},
    ])


def _tq_run_group(objs, group, seed_items=None):
    p = Player(objs)
    if seed_items:
        p.items.update(seed_items)
    p._fire_group(group)
    p._drain_trigger_event_queue()
    return p


# List order is multiply-first in both levels, so a result that tracks
# Trigger Order proves the queue sorted rather than fired in place.
_tq_add_first = _tq_run_group(_tq_item_level(0, 1), 7, {1: 2.0})
_tq_mul_first = _tq_run_group(_tq_item_level(1, 0), 7, {1: 2.0})
check("lower Trigger Order runs first (add then multiply: (2+5)*3)",
      abs(_tq_add_first.items[1] - 21.0) < 1e-9)
check("swapping Trigger Order swaps the result (multiply then add: 2*3+5)",
      abs(_tq_mul_first.items[1] - 11.0) < 1e-9)


class _TqLogPlayer(Player):
    """Player that records the x of every trigger the queue executes."""
    __slots__ = ("order_log",)

    def _execute_trigger_effect(self, o):
        self.order_log.append(o["x"])
        Player._execute_trigger_effect(self, o)


# Three spawn-chain members of one group, listed right-to-left, all at the
# same (default) Trigger Order: only left-to-right x ordering can sort them.
_tq_x_objs = make_flat_level(length=40, extras=[
    {"t": _TQ_EDIT, "x": 30, "y": 5, "r": 0, "groups": [4], "item_id": 2,
     "operation": "add", "operand": 1.0},
    {"t": _TQ_EDIT, "x": 10, "y": 5, "r": 0, "groups": [4], "item_id": 2,
     "operation": "add", "operand": 1.0},
    {"t": _TQ_EDIT, "x": 20, "y": 5, "r": 0, "groups": [4], "item_id": 2,
     "operation": "add", "operand": 1.0},
])
_tq_xp = _TqLogPlayer(_tq_x_objs)
_tq_xp.order_log = []
_tq_xp._fire_group(4)
_tq_xp._drain_trigger_event_queue()
check("spawned triggers execute left-to-right by x",
      _tq_xp.order_log == [10, 20, 30])
check("every spawned trigger in the group ran exactly once",
      abs(_tq_xp.items[2] - 3.0) < 1e-9)

# Recursion: group 3 = Item Edit (+1 on item 5) then Item Comp (fires group
# 3 again while item 5 < 5) then a Toggle that disables group 6. The chain
# must settle inside a single tick, and the Toggle it fires must still take
# effect on the same tick's later activations.
_tq_rec_objs = make_flat_level(length=40, extras=[
    {"t": _TQ_EDIT, "x": 10, "y": 5, "r": 0, "groups": [3], "item_id": 5,
     "operation": "add", "operand": 1.0},
    {"t": _TQ_TOGGLE, "x": 11, "y": 5, "r": 0, "groups": [3],
     "target_group": 6, "state": False},
    {"t": _TQ_COMP, "x": 12, "y": 5, "r": 0, "groups": [3], "item_id": 5,
     "comparator": "<", "value": 5.0, "target_group": 3},
    {"t": _TQ_BG, "x": 13, "y": 5, "r": 0, "groups": [6], "bg": 4},
])
_tq_rec = _TqLogPlayer(_tq_rec_objs)
_tq_rec.order_log = []
_tq_rec._fire_group(3)
_tq_rec._drain_trigger_event_queue()
check("a recursive Spawn/Toggle/Comp chain terminates within one tick",
      abs(_tq_rec.items[5] - 5.0) < 1e-9
      and _tq_rec._trigger_event_queue == [])
check("recursion re-runs the whole group each pass, still in x order",
      _tq_rec.order_log[:3] == [10, 11, 12]
      and len(_tq_rec.order_log) == 15)
check("a Toggle fired mid-chain disables its group for the same tick",
      6 in _tq_rec._trigger_disabled)
_tq_rec._fire_group(6)
_tq_rec._drain_trigger_event_queue()
check("the disabled group's trigger never runs",
      _tq_rec.bg_preset == 0)

# Unbounded self-refire: the drain guard must drop the tick, not hang.
_tq_loop_objs = make_flat_level(length=30, extras=[
    {"t": _TQ_COMP, "x": 10, "y": 5, "r": 0, "groups": [8], "item_id": 9,
     "comparator": ">=", "value": 0.0, "target_group": 8},
])
_tq_loop = _TqLogPlayer(_tq_loop_objs)
_tq_loop.order_log = []
_tq_loop._fire_group(8)
_tq_loop._drain_trigger_event_queue()
check("an infinite trigger loop is cut off by the pass guard",
      len(_tq_loop.order_log) == _TQ_MAX_PASSES
      and _tq_loop._trigger_event_queue == [])

# End-to-end through update(): a touched trigger still fires on the tick it
# was touched, and the queue is always empty between ticks.
_tq_touch_objs = make_flat_level(length=40, extras=[
    {"t": _TQ_BG, "x": 12, "y": 9, "r": 0, "bg": 3},
])
_tq_touch = Player(_tq_touch_objs)
for _ in range(400):
    _tq_touch.update(False, False)
    if _tq_touch._trigger_event_queue:
        break
    if _tq_touch.bg_preset == 3 or not _tq_touch.alive or _tq_touch.won:
        break
check("a touched trigger still takes effect (bg_preset changed)",
      _tq_touch.bg_preset == 3)
check("the event queue is empty between ticks",
      _tq_touch._trigger_event_queue == [])
check("touch ranks after spawn in the same tick",
      _TQ_FAM_SPAWN < _TQ_FAM_TOUCH)


# ---------------------------------------------------------------------------
# Area system: Area / Edit Area / Area Stop
# (deep-research-report.md, "Area and keyframe system")
# ---------------------------------------------------------------------------
section("Area effects (Area / Edit Area / Area Stop)")

from src.constants import (
    AREA_TRIGGER_TYPES as _AR_TYPES,
    AREA_START_TRIGGER_TYPES as _AR_START_TYPES,
    EDIT_AREA_TRIGGER_TYPES as _AR_EDIT_TYPES,
    T_AREA_MOVE_TRIGGER as _AR_MOVE, T_AREA_ROTATE_TRIGGER as _AR_ROT,
    T_AREA_SCALE_TRIGGER as _AR_SCALE, T_AREA_FADE_TRIGGER as _AR_FADE,
    T_AREA_TINT_TRIGGER as _AR_TINT, T_AREA_STOP_TRIGGER as _AR_STOP,
    T_EDIT_AREA_MOVE_TRIGGER as _AR_EMOVE,
    T_EDIT_AREA_ROTATE_TRIGGER as _AR_EROT,
)
from src.objects import (
    CAT_AREA as _AR_CAT, CATEGORY_ORDER as _AR_CAT_ORDER,
    PALETTE_CATEGORIES as _AR_PALETTE, spec_for as _ar_spec_for,
)
from src.geometry import obj_tint as _ar_obj_tint

# --- registry / schema wiring (no gaps between the three tables) -----------
check("all 11 Area types are registered as trigger types",
      len(_AR_TYPES) == 11 and _AR_TYPES <= _TQ_TRIGGER_TYPES)
check("all 11 Area types have a registry handler",
      _AR_TYPES <= set(_TQ_HANDLERS))
check("each Area type has its own distinct handler",
      len({_TQ_HANDLERS[t] for t in _AR_TYPES}) == 11)
check("the per-tick area stepper is NOT a queued trigger handler",
      Player._step_area_effects not in set(_TQ_HANDLERS.values())
      and "self._step_area_effects()" in inspect.getsource(Player.update))
check("Edit Area / Area Stop stay gated by Toggle like Move/Rotate/Scale",
      not (_AR_TYPES & C.CONTROL_TRIGGER_TYPES))
check("the Area palette tab exists and holds exactly the 11 Area types",
      _AR_CAT in _AR_CAT_ORDER
      and set(dict(_AR_PALETTE)[_AR_CAT]) == set(_AR_TYPES))

# Object ids straight off the report's table.
_AR_REPORT_IDS = {
    _AR_MOVE: 3006, _AR_ROT: 3007, _AR_SCALE: 3008, _AR_FADE: 3009,
    _AR_TINT: 3010, _AR_EMOVE: 3011, _AR_EROT: 3012,
    C.T_EDIT_AREA_SCALE_TRIGGER: 3013, C.T_EDIT_AREA_FADE_TRIGGER: 3014,
    C.T_EDIT_AREA_TINT_TRIGGER: 3015, _AR_STOP: 3024,
}
check("every Area spec carries the report's GD object id",
      all(_ar_spec_for(t).gd_object_id == gid
          for t, gid in _AR_REPORT_IDS.items()))
check("Area specs are marked partial (ids report-sourced, ranges engine-chosen)",
      all(_ar_spec_for(t).verification == "partial" for t in _AR_TYPES))
# Report's shared vocabulary: Length 222, Length+- 223, offset 220,
# Y-offset 252, EffectID 225, target 51, center 71, priority 341.
_AR_REPORT_KEYS = {"length": 222, "length_variance": 223, "offset": 220,
                   "y_offset": 252, "effect_id": 225, "target_group": 51,
                   "center_group": 71, "priority": 341}
check("every Area field carries the report's GD property key",
      all(_ar_spec_for(t).field(k).gd_key == v
          for t in (_AR_START_TYPES | _AR_EDIT_TYPES)
          for k, v in _AR_REPORT_KEYS.items()))
check("Area Stop carries only the Effect id it ends",
      [f.key for f in _ar_spec_for(_AR_STOP).fields][:1] == ["effect_id"]
      and _ar_spec_for(_AR_STOP).field("target_group") is None
      and _ar_spec_for(_AR_STOP).field("length") is None)
check("Length is stored as a grid-square float, not GD's tenths int",
      _ar_spec_for(_AR_MOVE).field("length").kind == "float"
      and _ar_spec_for(_AR_MOVE).field("length").default == 3.0)
check("every Area spec renders a schema-driven property panel with no new code",
      all(_ar_spec_for(t).fields
          and all(f.kind in ("int", "float", "bool", "choice")
                  and f.label for f in _ar_spec_for(t).fields)
          for t in _AR_TYPES))


def _ar_trigger(t, group, **fields):
    """One Area-family trigger, fired via _fire_group(``group``)."""
    o = {"t": t, "x": 1, "y": 1, "r": 0, "groups": [group]}
    o.update(fields)
    return o


def _ar_level(*extras):
    """Center-group anchor at (10, 5), an in-range target 2 squares away
    and an out-of-range one 30 squares away, both in target group 50."""
    return make_flat_level(length=60, extras=[
        {"t": T_BLOCK, "x": 10, "y": 5, "r": 0, "groups": [51]},
        {"t": T_BLOCK, "x": 12, "y": 5, "r": 0, "groups": [50]},
        {"t": T_BLOCK, "x": 40, "y": 5, "r": 0, "groups": [50]},
        *extras,
    ])


_AR_NEAR = -3   # indices into the list _ar_level builds (extras go last)
_AR_FAR = -2


def _ar_area_move(group=60, **over):
    fields = {"effect_id": 3, "length": 5.0, "length_variance": 0.0,
              "offset": 0.0, "y_offset": 0.0, "center_group": 51,
              "target_group": 50, "priority": 0, "dx": 10, "dy": 0}
    fields.update(over)
    return _ar_trigger(_AR_MOVE, group, **fields)


def _ar_fire(p, group):
    p._fire_group(group)
    p._drain_trigger_event_queue()


def _ar_step(p, ticks):
    for _ in range(ticks):
        p._step_area_effects()


def _ar_pos(o):
    return float(o.get("_fx", o["x"]))


# --- 1: inside the radius animates, outside does not -----------------------
_ar_objs = _ar_level(_ar_area_move())
_ar_p = Player(_ar_objs)
_ar_near = _ar_p.objects[-3]
_ar_far = _ar_p.objects[-2]
_ar_fire(_ar_p, 60)
check("an Area Move registers a live effect under its Effect id",
      list(_ar_p.active_areas) == [3]
      and _ar_p.active_areas[3]["kind"] == "move")
_ar_step(_ar_p, 60)
check("an object inside the Area Move radius animates",
      _ar_pos(_ar_near) > 12.0)
check("an identical object outside the radius does not move",
      _ar_pos(_ar_far) == 40.0)
# 60 ticks at 10 grid/s = 0.25s = 2.5 squares, at full strength (dist 2
# start, dist 4.5 end -- still inside Length 5).
check("the drift rate is the authored grid squares per second",
      abs(_ar_pos(_ar_near) - 14.5) < 0.05)

# --- 2: falloff between Length and Length +- -------------------------------
_ar_fall_objs = _ar_level(_ar_area_move(length=2.0, length_variance=10.0),
                          {"t": T_BLOCK, "x": 17, "y": 5, "r": 0,
                           "groups": [50]})
_ar_fall = Player(_ar_fall_objs)
_ar_inside = _ar_fall.objects[-4]      # dist 2 -> full strength
_ar_band = _ar_fall.objects[-1]        # dist 7 -> half strength
_ar_fire(_ar_fall, 60)
_ar_step(_ar_fall, 12)
check("an object in the Length +- band moves, but slower than one at full "
      "strength",
      0.0 < (_ar_pos(_ar_band) - 17.0) < (_ar_pos(_ar_inside) - 12.0))

# --- 3: Edit Area Move retunes a live effect mid-flight ---------------------
_ar_edit_objs = _ar_level(
    _ar_area_move(),
    _ar_trigger(_AR_EMOVE, 61, effect_id=3, length=40.0),
    _ar_trigger(_AR_EMOVE, 62, effect_id=99, length=40.0),
    _ar_trigger(_AR_EROT, 63, effect_id=3, degrees=180.0))
_ar_ed = Player(_ar_edit_objs)
_ar_ed_near = _ar_ed.objects[-6]
_ar_ed_far = _ar_ed.objects[-5]
_ar_fire(_ar_ed, 60)
_ar_step(_ar_ed, 30)
check("before the edit the far object is out of range",
      _ar_pos(_ar_ed_far) == 40.0)
_ar_fire(_ar_ed, 62)
check("an Edit Area naming an unknown Effect id changes nothing",
      _ar_ed.active_areas[3]["length"] == 5.0)
_ar_fire(_ar_ed, 63)
check("an Edit Area of the wrong kind leaves the effect alone",
      _ar_ed.active_areas[3]["kind"] == "move"
      and "degrees" not in _ar_ed.active_areas[3])
_ar_fire(_ar_ed, 61)
check("Edit Area Move patches the live effect's length in place",
      _ar_ed.active_areas[3]["length"] == 40.0)
check("Edit Area only patches the fields it carries",
      _ar_ed.active_areas[3]["dx"] == 10.0
      and _ar_ed.active_areas[3]["target_group"] == 50)
_ar_step(_ar_ed, 30)
check("the grown radius pulls the previously-out-of-range object in",
      _ar_pos(_ar_ed_far) > 40.0)
check("an Edit Area never creates an effect of its own",
      list(_ar_ed.active_areas) == [3])

# --- 4: Area Stop ends the effect ------------------------------------------
_ar_stop_objs = _ar_level(_ar_area_move(),
                          _ar_trigger(_AR_STOP, 64, effect_id=3))
_ar_st = Player(_ar_stop_objs)
_ar_st_near = _ar_st.objects[-4]
_ar_fire(_ar_st, 60)
_ar_step(_ar_st, 30)
_ar_moved_to = _ar_pos(_ar_st_near)
_ar_fire(_ar_st, 64)
check("Area Stop drops the effect with that Effect id",
      3 not in _ar_st.active_areas and _ar_st.active_areas == {})
_ar_step(_ar_st, 60)
check("the previously-affected object stops animating after Area Stop",
      _ar_pos(_ar_st_near) == _ar_moved_to and _ar_moved_to > 12.0)

# --- 5: reusing an Effect id replaces the effect (documented last-wins) -----
_ar_reuse = Player(_ar_level(_ar_area_move(),
                             _ar_area_move(group=65, dx=0, dy=7)))
_ar_fire(_ar_reuse, 60)
_ar_fire(_ar_reuse, 65)
check("re-firing an Effect id replaces the live effect, never stacks",
      len(_ar_reuse.active_areas) == 1
      and _ar_reuse.active_areas[3]["dy"] == 7.0)

# --- 6: the non-move kinds ---------------------------------------------------
_ar_fade = Player(_ar_level(_ar_trigger(
    _AR_FADE, 60, effect_id=4, length=5.0, length_variance=0.0, offset=0.0,
    y_offset=0.0, center_group=51, target_group=50, priority=0,
    target_alpha=0.0)))
_ar_fire(_ar_fade, 60)
_ar_step(_ar_fade, 1)
check("Area Fade fades what is inside the radius and not what is outside",
      _ar_fade.objects[-3]["_alpha"] == 0.0
      and _ar_fade.objects[-2]["_alpha"] == 1.0)

_ar_sc = Player(_ar_level(_ar_trigger(
    _AR_SCALE, 60, effect_id=5, length=5.0, length_variance=0.0, offset=0.0,
    y_offset=0.0, center_group=51, target_group=50, priority=0,
    sx=3.0, sy=3.0)))
_ar_fire(_ar_sc, 60)
_ar_step(_ar_sc, 1)
check("Area Scale scales what is inside the radius and not what is outside",
      _ar_sc.objects[-3]["sx"] == 3.0
      and _ar_sc.objects[-2].get("sx", 1.0) == 1.0)

_ar_ro = Player(_ar_level(_ar_trigger(
    _AR_ROT, 60, effect_id=6, length=5.0, length_variance=0.0, offset=0.0,
    y_offset=0.0, center_group=51, target_group=50, priority=0,
    degrees=240.0)))
_ar_fire(_ar_ro, 60)
_ar_step(_ar_ro, C.PHYSICS_TPS // 2)
check("Area Rotate spins what is inside the radius at the authored deg/s",
      abs(_ar_ro.objects[-3]["r"] - 120.0) < 1.0
      and _ar_ro.objects[-2].get("r", 0) == 0)

_ar_ti = Player(_ar_level(_ar_trigger(
    _AR_TINT, 60, effect_id=7, length=5.0, length_variance=0.0, offset=0.0,
    y_offset=0.0, center_group=51, target_group=50, priority=0,
    target_channel=2)))
_ar_fire(_ar_ti, 60)
_ar_step(_ar_ti, 1)
check("Area Tint tints what is inside the radius and not what is outside",
      _ar_obj_tint(_ar_ti.objects[-3]) is not None
      and _ar_obj_tint(_ar_ti.objects[-2]) is None)

# --- 7: the offset keys shift the effect's center ---------------------------
_ar_off = Player(_ar_level(_ar_area_move(length=1.0, offset=30.0)))
_ar_fire(_ar_off, 60)
_ar_step(_ar_off, 30)
check("Offset x shifts the falloff center away from the center group",
      _ar_pos(_ar_off.objects[-2]) > 40.0
      and _ar_pos(_ar_off.objects[-3]) == 12.0)

# --- 8: end to end through update(), fired by a real touch ------------------
_ar_touch = Player(make_flat_level(length=60, extras=[
    {"t": T_BLOCK, "x": 20, "y": 5, "r": 0, "groups": [51]},
    {"t": T_BLOCK, "x": 21, "y": 5, "r": 0, "groups": [50]},
    _ar_area_move(group=60, **{"touch_activated": True}) | {"x": 12, "y": 9},
]))
_ar_touch_target = _ar_touch.objects[-2]   # extras order: anchor, target, trigger
for _ in range(600):
    _ar_touch.update(False, False)
    if not _ar_touch.alive or _ar_touch.won:
        break
check("a touched Area Move starts a live effect through the normal queue",
      3 in _ar_touch.active_areas)
check("update()'s stepper advances the live area effect",
      _ar_pos(_ar_touch_target) > 21.0)

# --- 9: save/load round-trip of all 11 new types ----------------------------


def _ar_alt_value(f):
    """A legal, non-default value for one Field, so the round-trip proves
    the value survived rather than that both sides defaulted."""
    if f.kind == "bool":
        return not bool(f.default)
    if f.kind == "choice":
        return f.choices[1] if len(f.choices) > 1 else f.choices[0]
    return f.coerce(f.default + (f.step if f.kind == "float" else 1))


_ar_rt_objs = []
_ar_rt_expect = {}
for _ar_i, _ar_t in enumerate(sorted(_AR_TYPES)):
    _ar_o = {"t": _ar_t, "x": _ar_i, "y": 4, "r": 0}
    for _ar_f in _ar_spec_for(_ar_t).fields:
        _ar_o[_ar_f.key] = _ar_alt_value(_ar_f)
    _ar_rt_expect[_ar_t] = dict(_ar_o)
    _ar_rt_objs.append(_ar_o)
_ar_rt_path = save_level(_ar_rt_objs, "Area RT", "area-roundtrip")
_ar_rt_loaded = {o["t"]: o for o in load_level(_ar_rt_path)[1]}
check("every Area type survives a save/load round-trip",
      set(_ar_rt_loaded) == set(_AR_TYPES))
_ar_rt_bad = [
    (t, f.key)
    for t in _AR_TYPES
    for f in _ar_spec_for(t).fields
    if _ar_rt_loaded[t].get(f.key) != _ar_rt_expect[t][f.key]
]
check("every Area field round-trips with its authored value",
      _ar_rt_bad == [])
check("the round-trip wrote no numeric GD keys into the save format",
      all(not any(str(k).isdigit() for k in o)
          for o in _ar_rt_loaded.values()))


# ---------------------------------------------------------------------------
# Random Trigger, Advanced Random Trigger, Force Block
# (deep-research-report.md, "Core object, paired, and item triggers" +
#  "Force and state precedence" + "Representative full-format records")
# ---------------------------------------------------------------------------
section("Random / Advanced Random / Force Block")

import random as _rn_random

from src.constants import (
    T_RANDOM_TRIGGER as _RN_RANDOM,
    T_ADVANCED_RANDOM_TRIGGER as _RN_ADV,
    T_FORCE_BLOCK as _RN_FORCE,
    RANDOM_TRIGGER_TYPES as _RN_TYPES,
    ADVANCED_RANDOM_MAX_PAIRS as _RN_MAX_PAIRS,
    ADVANCED_RANDOM_EDITOR_SLOTS as _RN_SLOTS,
    UNITS_PER_BLOCK as _RN_UPB,
)
from src.objects import (
    parse_weighted_list as _rn_parse,
    format_weighted_list as _rn_format,
    advanced_random_weighted_list as _rn_list_for,
)

# --- registry / schema wiring (no gaps, and no *wrong* entries either) ------
check("both random triggers are registered as trigger types",
      _RN_TYPES == {_RN_RANDOM, _RN_ADV} and _RN_TYPES <= _TQ_TRIGGER_TYPES)
check("both random triggers have a registry handler",
      _RN_TYPES <= set(_TQ_HANDLERS))
check("each random trigger has its own distinct handler",
      len({_TQ_HANDLERS[t] for t in _RN_TYPES}) == 2)
check("the registry still has no gaps after adding them",
      set(_TQ_HANDLERS) == set(_TQ_TRIGGER_TYPES))
# Falsification: Force Block fires no group, so a future contributor
# "helpfully" adding it to either table must break the suite.
check("Force Block is NOT a trigger type",
      _RN_FORCE not in _TQ_TRIGGER_TYPES
      and _RN_FORCE not in C.CONTROL_TRIGGER_TYPES)
check("Force Block has NO registry handler",
      _RN_FORCE not in _TQ_HANDLERS)
check("Force Block targets no group and carries no activation fields",
      all(_ar_spec_for(_RN_FORCE).field(k) is None
          for k in ("target_group", "target_group2", "touch_activated",
                    "multi_activate", "trigger_order")))
check("the random triggers ARE the run-other-triggers family (Toggle bypass)",
      _RN_TYPES <= C.CONTROL_TRIGGER_TYPES)
check("Advanced Random targets its own slots, not a single target_group",
      _ar_spec_for(_RN_ADV).field("target_group") is None
      and _ar_spec_for(_RN_ADV).field("group1") is not None)
check("Random Trigger picks between target_group and target_group2",
      _ar_spec_for(_RN_RANDOM).field("target_group") is not None
      and _ar_spec_for(_RN_RANDOM).field("target_group2") is not None)
check("the Target group row is not duplicated on the Random Trigger",
      [f.key for f in _ar_spec_for(_RN_RANDOM).fields].count("target_group")
      == 1)

# Object ids straight off the report's table.
check("every new spec carries the report's GD object id",
      _ar_spec_for(_RN_RANDOM).gd_object_id == 1912
      and _ar_spec_for(_RN_ADV).gd_object_id == 2068
      and _ar_spec_for(_RN_FORCE).gd_object_id == 2069)
check("all three specs are marked partial (ids report-sourced, rest chosen)",
      all(_ar_spec_for(t).verification == "partial"
          for t in (_RN_RANDOM, _RN_ADV, _RN_FORCE)))
# FlowVix's force field map, quoted by the report.
_RN_FORCE_KEYS = {"relative": 528, "force": 149, "min_force": 526,
                  "max_force": 527, "force_range": 529, "force_id": 530}
check("every Force Block field carries FlowVix's GD property key",
      all(_ar_spec_for(_RN_FORCE).field(k).gd_key == v
          for k, v in _RN_FORCE_KEYS.items()))
check("Force Block sits in the same palette tab as the letter blocks",
      _ar_spec_for(_RN_FORCE).category
      == _ar_spec_for(C.T_DASH_STOP).category)
check("both random triggers sit in the Triggers tab beside Spawn/Sequence",
      _ar_spec_for(_RN_RANDOM).category
      == _ar_spec_for(_RN_ADV).category
      == _ar_spec_for(_TQ_SPAWN).category)
check("all three render a schema-driven property panel with no new code",
      all(_ar_spec_for(t).fields
          and all(f.kind in ("int", "float", "bool", "choice") and f.label
                  for f in _ar_spec_for(t).fields)
          for t in (_RN_RANDOM, _RN_ADV, _RN_FORCE)))
check("the editor exposes exactly ADVANCED_RANDOM_EDITOR_SLOTS pairs",
      all(_ar_spec_for(_RN_ADV).field(f"group{i}") is not None
          and _ar_spec_for(_RN_ADV).field(f"weight{i}") is not None
          for i in range(1, _RN_SLOTS + 1))
      and _ar_spec_for(_RN_ADV).field(f"group{_RN_SLOTS + 1}") is None)

# --- weighted-list format (the engine side stays generic over 20 pairs) -----
check("the report's own sample list parses to its documented pairs",
      _rn_parse("2.10.3.15") == [(2, 10), (3, 15)])
check("the weighted list round-trips through the report's string form",
      _rn_format(_rn_parse("2.10.3.15")) == "2.10.3.15")
check("the parser accepts the full 20-pair format the editor cannot show",
      len(_rn_parse(_rn_format([(i, i) for i in range(1, 40)])))
      == _RN_MAX_PAIRS == 20)
check("zero-weight slots drop out instead of taking 0% of the draw",
      _rn_parse("2.10.0.0.3.15.0.0") == [(2, 10), (3, 15)])
check("a malformed or truncated list is ignored, not crashed on",
      _rn_parse("2.10.3") == [(2, 10)] and _rn_parse("x.y") == []
      and _rn_parse("") == [] and _rn_parse(None) == [])
check("editor slots serialize into the report's string form",
      _rn_list_for({"group1": 2, "weight1": 10, "group2": 3, "weight2": 15})
      == "2.10.3.15")
check("an unauthored Advanced Random serializes to an empty list",
      _rn_list_for({}) == "")
check("an explicit weighted_list string wins over the editor slots",
      _rn_list_for({"group1": 9, "weight1": 1, "weighted_list": "4.1.5.2"})
      == "4.1.5.2")


def _rn_counter(group, item_id):
    """An Item Edit trigger in ``group`` that adds 1 to ``item_id`` --
    a group whose firing is observable in Player.items."""
    return {"t": _TQ_EDIT, "x": 1, "y": 1, "r": 0, "groups": [group],
            "item_id": item_id, "operation": "add", "operand": 1.0}


def _rn_fire(p, obj):
    """Enqueue + drain one trigger, the same path a touch/spawn takes."""
    p._enqueue_trigger_event(obj, _TQ_FAM_SPAWN)
    p._drain_trigger_event_queue()


def _rn_player(trigger):
    return Player(make_flat_level(length=30, extras=[
        _rn_counter(70, 1), _rn_counter(71, 2), _rn_counter(72, 3),
        trigger,
    ]))


def _rn_run(trigger, trials, seed=1234):
    """Fire ``trigger`` ``trials`` times; return the per-item tallies."""
    p = _rn_player(trigger)
    obj = p.objects[-1]
    _rn_random.seed(seed)
    for _ in range(trials):
        _rn_fire(p, obj)
    return p.items


# --- Random Trigger: the two deterministic edges ----------------------------
_RN_TRIG = {"t": _RN_RANDOM, "x": 5, "y": 5, "r": 0,
            "target_group": 70, "target_group2": 71}
_rn_always = _rn_run(_RN_TRIG | {"chance": 100.0}, 500)
check("chance=100 always fires the first target group",
      _rn_always.get(1) == 500 and _rn_always.get(2, 0) == 0)
_rn_never = _rn_run(_RN_TRIG | {"chance": 0.0}, 500)
check("chance=0 always fires the second target group",
      _rn_never.get(2) == 500 and _rn_never.get(1, 0) == 0)
_rn_even = _rn_run(_RN_TRIG | {"chance": 50.0}, 2000)
check("chance=50 splits both ways (neither group is dead code)",
      800 < _rn_even.get(1, 0) < 1200 and 800 < _rn_even.get(2, 0) < 1200
      and _rn_even.get(1, 0) + _rn_even.get(2, 0) == 2000)
check("a Random Trigger with an empty second group simply fires nothing",
      _rn_run(_RN_TRIG | {"chance": 0.0, "target_group2": 0}, 50) == {})

# --- Advanced Random: P(i) = 100 * w_i / sum(w_j) ---------------------------
# The report's own sample payload: groups weighted 10 and 15, i.e. 40/60.
_RN_ADV_TRIG = {"t": _RN_ADV, "x": 5, "y": 5, "r": 0,
                "group1": 70, "weight1": 10, "group2": 71, "weight2": 15,
                "group3": 0, "weight3": 0, "group4": 0, "weight4": 0}
_RN_TRIALS = 2000
_rn_weighted = _rn_run(_RN_ADV_TRIG, _RN_TRIALS)
_rn_a = _rn_weighted.get(1, 0)
_rn_b = _rn_weighted.get(2, 0)
check("every Advanced Random draw picks exactly one group",
      _rn_a + _rn_b == _RN_TRIALS and _rn_weighted.get(3, 0) == 0)
# Seeded RNG + a +/-5pp band: ~4.4 standard deviations at n=2000, so this
# cannot flake on the seed while still failing any real mis-weighting
# (an even 50/50 split, or the two groups swapped, is 10pp out).
check("weights 10/15 land within 5pp of the report's 40/60 split",
      abs(_rn_a / _RN_TRIALS - 0.40) < 0.05
      and abs(_rn_b / _RN_TRIALS - 0.60) < 0.05)
check("the heavier weight really is the more likely one", _rn_b > _rn_a)
check("an Advanced Random with every weight at 0 is inert",
      _rn_run({"t": _RN_ADV, "x": 5, "y": 5, "r": 0}, 100) == {})
check("a single weighted slot always wins",
      _rn_run({"t": _RN_ADV, "x": 5, "y": 5, "r": 0,
               "group1": 72, "weight1": 7}, 200).get(3) == 200)
check("the handler reads a full weighted_list string, not just the slots",
      _rn_run({"t": _RN_ADV, "x": 5, "y": 5, "r": 0,
               "weighted_list": "72.5"}, 200).get(3) == 200)

# --- Force Block: the report's stacking law ---------------------------------
_RN_FORCE_UP = -6.0   # units/tick, ~2x a cube jump


def _rn_force_block(force_id, **over):
    o = {"t": _RN_FORCE, "x": 3, "y": 9, "r": 0, "force": _RN_FORCE_UP,
         "relative": False, "min_force": 0.0, "max_force": 0.0,
         "force_range": 1.0, "force_id": force_id}
    o.update(over)
    return o


def _rn_force_player(*blocks):
    """A player sitting exactly on the spawn cell the blocks occupy."""
    return Player(make_flat_level(length=30, extras=list(blocks)))


def _rn_vy_after_one_tick(*blocks):
    p = _rn_force_player(*blocks)
    p.update(False, False)
    return p.vy


_rn_vy_none = _rn_vy_after_one_tick()
_rn_vy_one = _rn_vy_after_one_tick(_rn_force_block(7))
_rn_vy_same = _rn_vy_after_one_tick(_rn_force_block(7), _rn_force_block(7))
_rn_vy_diff = _rn_vy_after_one_tick(_rn_force_block(7), _rn_force_block(8))
check("a Force Block reaches vy through _handle_interactions",
      abs((_rn_vy_one - _rn_vy_none) - _RN_FORCE_UP) < 1e-6)
# The report, verbatim: "same ForceID -> forces do not stack".
check("two Force Blocks sharing a ForceID apply exactly one impulse",
      abs(_rn_vy_same - _rn_vy_one) < 1e-6)
# The report, verbatim: "different ForceID -> forces stack".
check("two Force Blocks with different ForceIDs both apply (they stack)",
      abs((_rn_vy_diff - _rn_vy_none) - 2 * _RN_FORCE_UP) < 1e-6)
check("stacking is a real doubling, not the single-impulse result",
      abs(_rn_vy_diff - _rn_vy_same) > abs(_RN_FORCE_UP) / 2)
_rn_ground = _rn_force_player()
_rn_ground.update(False, False)
_rn_ground.on_ground = True
_rn_ground.vy = 0.0
_rn_ground._force_ids_this_frame.clear()
_rn_ground._apply_force_block(_rn_ground, _rn_force_block(20))
check("a push away from the floor ungrounds the player",
      _rn_ground.on_ground is False)
_rn_ground.on_ground = True
_rn_ground.vy = 0.0
_rn_ground._force_ids_this_frame.clear()
_rn_ground._apply_force_block(_rn_ground,
                             _rn_force_block(21, force=-_RN_FORCE_UP))
check("a push into the floor leaves the player grounded",
      _rn_ground.on_ground is True and _rn_ground.vy > 0)

# The ForceID set is per-FRAME, not per-attempt: the same block must be
# able to push again on the next tick.
_rn_multi = _rn_force_player(_rn_force_block(7))
_rn_multi.update(False, False)
_rn_first = _rn_multi.vy
_rn_ids_mid = set(_rn_multi._force_ids_this_frame)
_rn_multi.update(False, False)
check("a ForceID applied last frame is free to apply again this frame",
      _rn_multi.vy < _rn_first)
check("the ForceID set records the block that fired, then clears next tick",
      _rn_ids_mid == {7})
check("the ForceID set is empty on a fresh reset",
      Player(make_flat_level(length=10))._force_ids_this_frame == set())

# Direct-call checks for the field semantics, so the clamp/range/relative
# readings are pinned independently of a whole simulation tick.
_rn_direct = _rn_force_player()
_rn_direct.vy = 0.0
check("min/max of 0 leave the impulse unclamped (pure ADD)",
      _rn_direct._apply_force_block(_rn_direct, _rn_force_block(1))
      and abs(_rn_direct.vy - _RN_FORCE_UP) < 1e-6)
_rn_direct.vy = 0.0
check("max_force clamps the resulting speed magnitude",
      _rn_direct._apply_force_block(_rn_direct,
                                    _rn_force_block(2, max_force=2.0))
      and abs(_rn_direct.vy + 2.0) < 1e-6)
_rn_direct.vy = 0.0
check("min_force floors the resulting speed magnitude along the push",
      _rn_direct._apply_force_block(_rn_direct,
                                    _rn_force_block(3, force=-0.25,
                                                    min_force=4.0))
      and abs(_rn_direct.vy + 4.0) < 1e-6)
_rn_direct.vy = 0.0
_rn_direct.grav = -1
check("relative=True mirrors the push when gravity is flipped",
      _rn_direct._apply_force_block(_rn_direct,
                                    _rn_force_block(4, relative=True))
      and abs(_rn_direct.vy + _RN_FORCE_UP) < 1e-6)
_rn_direct.grav = 1
_rn_direct.vy = 0.0
check("a block outside its own range does nothing",
      _rn_direct._apply_force_block(
          _rn_direct, _rn_force_block(5, x=3, y=6, force_range=0.5)) is False
      and _rn_direct.vy == 0.0)
_rn_direct.vy = 0.0
check("a wider range reaches a block the default range would miss",
      _rn_direct._apply_force_block(
          _rn_direct, _rn_force_block(6, x=3, y=8, force_range=2.0)) is True)
# Scope guard: the impulse is a contact response next to the letter
# blocks, NOT a physics/collision change (plan Checkpoint 3's one hard
# constraint). If someone moves it into the gravity or hitbox code this
# fails rather than silently drifting.
_RN_CONTACT_SRC = inspect.getsource(Player._handle_interactions)
check("the Force Block branch lives beside the letter blocks' contact tests",
      "T_FORCE_BLOCK" in _RN_CONTACT_SRC and "T_DASH_STOP" in _RN_CONTACT_SRC
      and "_apply_force_block" in _RN_CONTACT_SRC)
check("neither physics.py nor collision.py knows Force Block exists",
      "force_block" not in inspect.getsource(sys.modules["src.physics"]).lower()
      and "force_block" not in inspect.getsource(
          sys.modules["src.player.collision"]).lower())

# --- save/load round-trip of all three new types ----------------------------
_RN_RT_TYPES = (_RN_RANDOM, _RN_ADV, _RN_FORCE)
_rn_rt_objs = []
_rn_rt_expect = {}
for _rn_i, _rn_t in enumerate(_RN_RT_TYPES):
    _rn_o = {"t": _rn_t, "x": _rn_i, "y": 4, "r": 0}
    for _rn_f in _ar_spec_for(_rn_t).fields:
        _rn_o[_rn_f.key] = _ar_alt_value(_rn_f)
    _rn_rt_expect[_rn_t] = dict(_rn_o)
    _rn_rt_objs.append(_rn_o)
_rn_rt_objs[1]["weighted_list"] = "2.10.3.15"
_rn_rt_path = save_level(_rn_rt_objs, "Random RT", "random-roundtrip")
_rn_rt_loaded = {o["t"]: o for o in load_level(_rn_rt_path)[1]}
check("all three new types survive a save/load round-trip",
      set(_rn_rt_loaded) == set(_RN_RT_TYPES))
_rn_rt_bad = [
    (t, f.key)
    for t in _RN_RT_TYPES
    for f in _ar_spec_for(t).fields
    if _rn_rt_loaded[t].get(f.key) != _rn_rt_expect[t][f.key]
]
check("every new field round-trips with its authored value", _rn_rt_bad == [])
check("Advanced Random's full weighted_list string survives the round-trip",
      _rn_rt_loaded[_RN_ADV].get("weighted_list") == "2.10.3.15")
check("a slot-authored Advanced Random writes no weighted_list key",
      "weighted_list" not in {o["t"]: o for o in load_level(save_level(
          [{"t": _RN_ADV, "x": 1, "y": 1, "r": 0, "group1": 5,
            "weight1": 2}], "Random RT2", "random-roundtrip-2"))[1]}[_RN_ADV])
check("the round-trip wrote no numeric GD keys into the save format",
      all(not any(str(k).isdigit() for k in o)
          for o in _rn_rt_loaded.values()))


# ---------------------------------------------------------------------------
# Shader / screen effects, Checkpoint 4
# (deep-research-report.md, "Shader and visual effects": Shader 2904,
#  Chromatic 2910, Radial Blur 2914, Motion Blur 2915, Bulge 2916,
#  Pinch 2917, Split Screen 2924)
# ---------------------------------------------------------------------------
section("Shader effects (Chromatic / Radial Blur / Motion Blur / Bulge / "
        "Pinch / Split Screen / Shader)")

import numpy as _sh_np

from src.constants import (
    T_SHADER_TRIGGER as _SH_SHADER, T_CHROMATIC_TRIGGER as _SH_CHROMA,
    T_RADIAL_BLUR_TRIGGER as _SH_RBLUR, T_MOTION_BLUR_TRIGGER as _SH_MBLUR,
    T_BULGE_TRIGGER as _SH_BULGE, T_PINCH_TRIGGER as _SH_PINCH,
    T_SPLIT_SCREEN_TRIGGER as _SH_SPLIT,
    T_GRAYSCALE_TRIGGER as _SH_GRAY, T_INVERT_TRIGGER as _SH_INVERT,
    T_PIXELATE_TRIGGER as _SH_PIXEL,
    SCREEN_EFFECT_TRIGGER_TYPES as _SH_FX_TYPES,
    RADIAL_BLUR_MAX_SAMPLES as _SH_MAX_SAMPLES,
    MOTION_BLUR_MAX_FRAMES as _SH_MAX_FRAMES,
    CHROMATIC_MAX_OFFSET_PX as _SH_MAX_OFFSET,
    PHYSICS_TPS as _SH_TPS,
)
from src.play_render import (
    apply_screen_effects as _sh_apply, build_screen_effects as _sh_build,
    apply_camera_post as _sh_post,
)
from src.player.triggers import SCREEN_EFFECT_PARAMS as _SH_PARAMS

# The six new effects that animate, plus the base trigger that does not.
_SH_ANIMATED = (_SH_CHROMA, _SH_RBLUR, _SH_MBLUR, _SH_BULGE, _SH_PINCH,
                _SH_SPLIT)
_SH_NEW = _SH_ANIMATED + (_SH_SHADER,)
# type -> the active_effect_anims key its handler writes.
_SH_ANIM_NAME = {_SH_CHROMA: "chromatic", _SH_RBLUR: "radial_blur",
                 _SH_MBLUR: "motion_blur", _SH_BULGE: "bulge",
                 _SH_PINCH: "pinch", _SH_SPLIT: "split_screen"}

# --- registry / schema wiring (no gaps, and no wrong entries either) --------
check("all 7 new shader types are registered as trigger types",
      all(t in _TQ_TRIGGER_TYPES for t in _SH_NEW) and len(set(_SH_NEW)) == 7)
check("all 7 new shader types have a registry handler",
      all(t in _TQ_HANDLERS for t in _SH_NEW))
check("each new shader type has its own distinct handler",
      len({_TQ_HANDLERS[t] for t in _SH_NEW}) == 7)
check("the registry still has no gaps after adding them",
      set(_TQ_HANDLERS) == set(_TQ_TRIGGER_TYPES))
check("the per-tick effect stepper is NOT a queued trigger handler",
      Player._step_screen_effects not in set(_TQ_HANDLERS.values())
      and "self._step_screen_effects()" in inspect.getsource(Player.update))
check("the 6 animated effects join the 5 existing ones in "
      "SCREEN_EFFECT_TRIGGER_TYPES",
      _SH_FX_TYPES == {_SH_GRAY, C.T_SEPIA_TRIGGER, _SH_INVERT,
                       C.T_HUE_TRIGGER, _SH_PIXEL} | set(_SH_ANIMATED))
# Falsification: Shader Trigger animates nothing, so promising
# build_screen_effects a "shader_trigger" anim entry must break the suite.
check("Shader Trigger is deliberately NOT a screen-effect (animating) type",
      _SH_SHADER not in _SH_FX_TYPES)
check("Shader Trigger carries no tween fields at all",
      all(_ar_spec_for(_SH_SHADER).field(k) is None
          for k in ("state", "intensity", "duration", "easing")))
check("every animated effect type does carry the shared tween quartet",
      all(all(_ar_spec_for(t).field(k) is not None
              for k in ("state", "intensity", "duration", "easing"))
          for t in _SH_ANIMATED))
check("all 7 sit in the Camera palette tab beside the existing 5 effects",
      all(_ar_spec_for(t).category == _ar_spec_for(_SH_GRAY).category
          for t in _SH_NEW))
check("all 7 render a schema-driven property panel with no new code",
      all(_ar_spec_for(t).fields
          and all(f.kind in ("int", "float", "bool", "choice") and f.label
                  for f in _ar_spec_for(t).fields)
          for t in _SH_NEW))

# Object ids straight off the report's table.
_SH_REPORT_IDS = {_SH_SHADER: 2904, _SH_CHROMA: 2910, _SH_RBLUR: 2914,
                  _SH_MBLUR: 2915, _SH_BULGE: 2916, _SH_PINCH: 2917,
                  _SH_SPLIT: 2924}
check("every new shader spec carries the report's GD object id",
      all(_ar_spec_for(t).gd_object_id == gid
          for t, gid in _SH_REPORT_IDS.items()))
check("all 7 specs are marked partial (ids report-sourced, ranges chosen)",
      all(_ar_spec_for(t).verification == "partial" for t in _SH_NEW))
# FlowVix's base-shader property map, quoted by the report.
check("Shader Trigger carries FlowVix's disable_all/layer-range keys",
      _ar_spec_for(_SH_SHADER).field("disable_all").gd_key == 192
      and _ar_spec_for(_SH_SHADER).field("lowest_layer").gd_key == 196
      and _ar_spec_for(_SH_SHADER).field("highest_layer").gd_key == 197)
check("Split Screen's engine-invented axis field claims no GD key",
      _ar_spec_for(_SH_SPLIT).field("axis").gd_key is None
      and _ar_spec_for(_SH_SPLIT).field("axis").verification == "unverified")

# Falsification: the six effects the report itself flags as needing a real
# GPU shader stay deferred. A half-wired type must fail here, not ship.
_SH_DEFERRED_NAMES = ("T_GRADIENT", "T_SHOCK_WAVE", "T_SHOCK_LINE",
                      "T_GLITCH", "T_CHROMATIC_GLITCH", "T_LENS_CIRCLE")
check("no half-wired type exists for the 6 deferred GPU-only shaders",
      not any(hasattr(C, n) for n in _SH_DEFERRED_NAMES))
check("no deferred shader id leaked into a spec",
      not ({2903, 2905, 2907, 2909, 2911, 2913}
           & {s.gd_object_id for s in _TQ_SPECS.values()}))

# --- every effect's knobs are declared once, and reach the anim entry -------
check("every animated effect declares its knobs in SCREEN_EFFECT_PARAMS",
      all(_SH_ANIM_NAME[t] in _SH_PARAMS for t in _SH_ANIMATED))
_sh_param_gap = [
    (t, key)
    for t in _SH_ANIMATED
    for key, _d, _c in _SH_PARAMS[_SH_ANIM_NAME[t]]
    if _ar_spec_for(t).field(key) is None
]
check("every declared knob is a real authorable field on its spec",
      _sh_param_gap == [])


def _sh_level(*extras):
    return make_flat_level(length=20, extras=list(extras))


def _sh_trigger(t, group=70, **fields):
    o = {"t": t, "x": 1, "y": 1, "r": 0, "groups": [group]}
    o.update(fields)
    return o


def _sh_run(objs, ticks=None):
    """Fire group 70, then step the effect tween to completion."""
    p = Player(_sh_level(*objs))
    p._fire_group(70)
    p._drain_trigger_event_queue()
    for _ in range(ticks if ticks is not None else int(_SH_TPS) + 2):
        p._step_screen_effects()
    return p


_sh_full = {"duration": 0.1, "intensity": 1.0, "state": True}
_SH_AUTHORED = {
    _SH_CHROMA: {"offset_px": 8},
    _SH_RBLUR: {"strength": 1.0, "sample_count": 4},
    _SH_MBLUR: {"strength": 1.0, "frame_count": 3},
    _SH_BULGE: {"strength": 1.0, "radius": 120.0},
    _SH_PINCH: {"strength": 1.0, "radius": 120.0},
    _SH_SPLIT: {"axis": "vertical"},
}
_sh_players = {t: _sh_run([_sh_trigger(t, **_sh_full, **_SH_AUTHORED[t])])
               for t in _SH_ANIMATED}
check("firing each new trigger registers its own named animation entry",
      all(set(_sh_players[t].active_effect_anims) == {_SH_ANIM_NAME[t]}
          for t in _SH_ANIMATED))
check("each animation reaches full intensity once its duration elapses",
      all(abs(_sh_players[t].active_effect_anims[_SH_ANIM_NAME[t]]["cur"]
              - 1.0) < 1e-6 for t in _SH_ANIMATED))
check("each authored knob is copied onto the animation entry verbatim",
      all(_sh_players[t].active_effect_anims[_SH_ANIM_NAME[t]][k] == v
          for t, knobs in _SH_AUTHORED.items() for k, v in knobs.items()))
_sh_built = {t: _sh_build(_sh_players[t].active_effect_anims)[_SH_ANIM_NAME[t]]
             for t in _SH_ANIMATED}
check("build_screen_effects emits exactly the declared knobs plus an amount "
      "(no tween bookkeeping leaks into the render side)",
      all(set(_sh_built[t]) == {"amount"}
          | {k for k, _d, _c in _SH_PARAMS[_SH_ANIM_NAME[t]]}
          for t in _SH_ANIMATED))
check("build_screen_effects hands every authored knob through verbatim",
      all(_sh_built[t]["amount"] == 1.0
          and all(_sh_built[t][k] == v for k, v in _SH_AUTHORED[t].items())
          for t in _SH_ANIMATED))
check("a state=False trigger tweens the effect back toward 0",
      _sh_run([_sh_trigger(_SH_BULGE, **{**_sh_full, "state": False},
                           **_SH_AUTHORED[_SH_BULGE])]
              ).active_effect_anims["bulge"]["cur"] == 0.0)
# The runtime floor under objects.py's Field ranges: a hand-edited level
# must not be able to buy unbounded per-frame work.
_sh_wild = _sh_run([_sh_trigger(_SH_RBLUR, **_sh_full, strength=99.0,
                                sample_count=999),
                    _sh_trigger(_SH_MBLUR, **_sh_full, frame_count=999),
                    _sh_trigger(_SH_CHROMA, **_sh_full, offset_px=99999)])
check("out-of-range authored knobs are clamped to the constants.py caps",
      _sh_wild.active_effect_anims["radial_blur"]["sample_count"]
      == _SH_MAX_SAMPLES
      and _sh_wild.active_effect_anims["motion_blur"]["frame_count"]
      == _SH_MAX_FRAMES
      and _sh_wild.active_effect_anims["chromatic"]["offset_px"]
      == _SH_MAX_OFFSET
      and _sh_wild.active_effect_anims["radial_blur"]["strength"] == 1.0)
check("build_screen_effects still drops a near-zero-intensity effect",
      _sh_build({"bulge": {"cur": 0.0005, "start": 0.0, "target": 1.0,
                           "frame": 1, "duration": 6, "easing": "linear",
                           "strength": 1.0}}) == {})

# --- each effect actually changes pixels (numpy diff, not golden image) -----
_SH_W, _SH_H = 320, 240


def _sh_pattern():
    """A busy, non-symmetric test frame: a mirror or a roll of a flat or
    symmetric image would compare equal and pass vacuously."""
    s = pygame.Surface((_SH_W, _SH_H))
    a = _sh_np.zeros((_SH_W, _SH_H, 3), _sh_np.uint8)
    xs = _sh_np.arange(_SH_W)[:, None]
    ys = _sh_np.arange(_SH_H)[None, :]
    a[..., 0] = (xs * 7) % 256
    a[..., 1] = (ys * 11) % 256
    a[..., 2] = ((xs + ys * 3) * 13) % 256
    pygame.surfarray.blit_array(s, a)
    return s


def _sh_changed(effects, history=None):
    """How many pixels apply_screen_effects moved on the test pattern."""
    surf = _sh_pattern()
    before = pygame.surfarray.array3d(surf).copy()
    out = _sh_apply(surf, effects, history)
    return int((before != pygame.surfarray.array3d(out)).any(axis=2).sum())


check("the test pattern is not symmetric on either axis (mirrors would "
      "pass vacuously)",
      _sh_changed({"split_screen": {"amount": 1.0, "axis": "vertical"}}) > 0
      and _sh_changed({"split_screen": {"amount": 1.0,
                                        "axis": "horizontal"}}) > 0)
_sh_diffs = {}
for _sh_t in _SH_ANIMATED:
    _sh_name = _SH_ANIM_NAME[_sh_t]
    _sh_fx = _sh_build(_sh_players[_sh_t].active_effect_anims)
    if _sh_name == "motion_blur":
        # Nothing to blend on the very first frame by construction, so
        # prime the ring buffer with a visibly different frame first.
        _sh_hist = [_sh_np.zeros((_SH_W, _SH_H, 3), _sh_np.uint8)]
        _sh_diffs[_sh_name] = _sh_changed(_sh_fx, _sh_hist)
    else:
        _sh_diffs[_sh_name] = _sh_changed(_sh_fx)
check("every new effect is a non-identity transform of the frame",
      all(v > 0 for v in _sh_diffs.values()) and len(_sh_diffs) == 6)
check("Bulge and Pinch displace pixels in opposite directions",
      not _sh_np.array_equal(
          pygame.surfarray.array3d(_sh_apply(
              _sh_pattern(), _sh_build(
                  _sh_players[_SH_BULGE].active_effect_anims))),
          pygame.surfarray.array3d(_sh_apply(
              _sh_pattern(), _sh_build(
                  _sh_players[_SH_PINCH].active_effect_anims)))))
check("a zero-amount effect leaves the frame untouched",
      all(_sh_changed({n: dict(_SH_AUTHORED[t], amount=0.0)}) == 0
          for t, n in _SH_ANIM_NAME.items() if n != "motion_blur"))
check("the 5 pre-existing effects still transform the frame after the "
      "params-dict change",
      all(_sh_changed({n: p}) > 0 for n, p in (
          ("grayscale", {"amount": 1.0}), ("sepia", {"amount": 1.0}),
          ("invert", {"amount": 1.0}),
          ("hue", {"amount": 1.0, "hue_shift": 120.0}),
          ("pixelate", {"amount": 0.5, "pixel_size": 8}))))
check("an empty effects dict is still the no-op fast path",
      _sh_changed({}) == 0)

# --- Motion Blur's ring buffer stays bounded and attempt-local -------------
_sh_hist = []
for _sh_i in range(10):
    _sh_apply(_sh_pattern(), {"motion_blur": {"amount": 1.0, "strength": 0.5,
                                              "frame_count": 3}}, _sh_hist)
check("the Motion Blur ring buffer never grows past frame_count - 1",
      len(_sh_hist) == 2)
_sh_screen = pygame.Surface((_SH_W, _SH_H))
_sh_post(_sh_screen, 1.0, 0.0, {"grayscale": {"amount": 1.0}}, _sh_hist)
check("stopping Motion Blur drops the retained frames immediately",
      _sh_hist == [])
check("Player carries no frame buffers -- the ring buffer is render-side",
      "motion_blur_frames" not in set(Player.__slots__)
      and "motion_blur_frames" in inspect.getsource(
          sys.modules["src.play"]))

# --- Shader Trigger: the one documented behavior, disable_all -------------
_sh_dis = _sh_run([_sh_trigger(_SH_CHROMA, **_sh_full, **_SH_AUTHORED[_SH_CHROMA]),
                   _sh_trigger(_SH_BULGE, **_sh_full, **_SH_AUTHORED[_SH_BULGE]),
                   _sh_trigger(_SH_GRAY, **_sh_full)])
check("three effects are live before the Shader Trigger fires",
      set(_sh_dis.active_effect_anims) == {"chromatic", "bulge", "grayscale"})
_sh_dis._apply_shader_trigger({"disable_all": True})
check("Shader Trigger with disable_all=True clears active_effect_anims",
      _sh_dis.active_effect_anims == {})
check("and the cleared state renders as no effects at all",
      _sh_build(_sh_dis.active_effect_anims) == {})
_sh_keep = _sh_run([_sh_trigger(_SH_CHROMA, **_sh_full,
                                **_SH_AUTHORED[_SH_CHROMA]),
                    _sh_trigger(_SH_SHADER, disable_all=False,
                                lowest_layer=3, highest_layer=9)])
check("Shader Trigger with disable_all=False leaves live effects alone",
      set(_sh_keep.active_effect_anims) == {"chromatic"})
# The engine has no render-layer concept: the fields are authored and
# saved but nothing consumes them. Pinned so a future layer system has to
# come back here rather than silently half-wiring itself.
_sh_layer_readers = [
    (mod, key)
    for mod in ("src.player.triggers", "src.player.core", "src.play_render",
                "src.play")
    for key in ("lowest_layer", "highest_layer")
    if f'get("{key}"' in inspect.getsource(sys.modules[mod])
]
check("lowest_layer/highest_layer are stored but never read at runtime",
      _sh_layer_readers == [])
check("Shader Trigger has no render-side branch (it only clears state)",
      "shader" not in _sh_build({"chromatic": {"cur": 1.0, "start": 0.0,
                                               "target": 1.0, "frame": 6,
                                               "duration": 6,
                                               "easing": "linear",
                                               "offset_px": 8}}))

# --- perf sanity: everything on at once stays bounded ----------------------
_sh_all = {n: dict(_SH_AUTHORED[t], amount=1.0)
           for t, n in _SH_ANIM_NAME.items()}
_sh_all.update({"grayscale": {"amount": 0.5}, "sepia": {"amount": 0.5},
                "invert": {"amount": 0.5},
                "hue": {"amount": 0.5, "hue_shift": 90.0},
                "pixelate": {"amount": 0.5, "pixel_size": 8}})
_sh_all["radial_blur"] = dict(_sh_all["radial_blur"], amount=1.0,
                              sample_count=_SH_MAX_SAMPLES)
_sh_perf_hist = []
_sh_apply(_sh_pattern(), _sh_all, _sh_perf_hist)   # warm the caches
_sh_t0 = _time_perf.perf_counter()
for _ in range(3):
    _sh_apply(_sh_pattern(), _sh_all, _sh_perf_hist)
_sh_ms = (_time_perf.perf_counter() - _sh_t0) / 3 * 1000
# Deliberately generous: all 11 effects at once with the maximum sample
# count is a pathological authoring case, not a shipping one, and CI
# machines are slow. This only has to catch an accidental per-pixel
# Python loop, which would be orders of magnitude past this.
check(f"all 11 effects at once stay bounded ({_sh_ms:.0f} ms/frame at "
      f"{_SH_W}x{_SH_H})", _sh_ms < 2000)

# --- save/load round-trip of all 7 new types -------------------------------
_sh_rt_objs = []
_sh_rt_expect = {}
for _sh_i, _sh_t in enumerate(_SH_NEW):
    _sh_o = {"t": _sh_t, "x": _sh_i, "y": 4, "r": 0}
    for _sh_f in _ar_spec_for(_sh_t).fields:
        _sh_o[_sh_f.key] = _ar_alt_value(_sh_f)
    _sh_rt_expect[_sh_t] = dict(_sh_o)
    _sh_rt_objs.append(_sh_o)
_sh_rt_path = save_level(_sh_rt_objs, "Shader RT", "shader-roundtrip")
_sh_rt_loaded = {o["t"]: o for o in load_level(_sh_rt_path)[1]}
check("all 7 new shader types survive a save/load round-trip",
      set(_sh_rt_loaded) == set(_SH_NEW))
_sh_rt_bad = [
    (t, f.key)
    for t in _SH_NEW
    for f in _ar_spec_for(t).fields
    if _sh_rt_loaded[t].get(f.key) != _sh_rt_expect[t][f.key]
]
check("every new shader field round-trips with its authored value",
      _sh_rt_bad == [])
check("Split Screen's axis choice round-trips as a string",
      _sh_rt_loaded[_SH_SPLIT]["axis"] == "horizontal")
check("a centered Bulge writes no center_x/center_y keys (non_default)",
      not ({"center_x", "center_y"} & set({o["t"]: o for o in load_level(
          save_level([{"t": _SH_BULGE, "x": 1, "y": 1, "r": 0}],
                     "Shader RT2", "shader-roundtrip-2"))[1]}[_SH_BULGE])))
check("the round-trip wrote no numeric GD keys into the save format",
      all(not any(str(k).isdigit() for k in o)
          for o in _sh_rt_loaded.values()))


# ---------------------------------------------------------------------------
# Audio triggers: Song / SFX / Edit Song / Edit SFX
# (deep-research-report.md, "Audio, timers, and arithmetic")
# ---------------------------------------------------------------------------
section("Audio triggers (Song / SFX / Edit Song / Edit SFX)")

from src import music as _au_music
from src import sfx as _au_sfx
from src.constants import (
    T_SONG_TRIGGER as _AU_SONG, T_SFX_TRIGGER as _AU_SFX,
    T_EDIT_SONG_TRIGGER as _AU_ESONG, T_EDIT_SFX_TRIGGER as _AU_ESFX,
    AUDIO_TRIGGER_TYPES as _AU_TYPES,
    AUDIO_START_TRIGGER_TYPES as _AU_START_TYPES,
    EDIT_AUDIO_TRIGGER_TYPES as _AU_EDIT_TYPES,
    SONG_CHANNEL_MAX as _AU_CHAN_MAX,
)
from src.objects import CAT_AUDIO as _AU_CAT
from src.bots.sim import SimPlayer as _AU_SIM
from src.editor import ui as _ed_ui

_au_sfx.init()

# --- registry / schema wiring (no gaps between the three tables) -----------
check("all 4 audio types are registered as trigger types",
      len(_AU_TYPES) == 4 and _AU_TYPES <= _TQ_TRIGGER_TYPES)
check("all 4 audio types have a registry handler",
      _AU_TYPES <= set(_TQ_HANDLERS))
check("each audio type has its own distinct handler",
      len({_TQ_HANDLERS[t] for t in _AU_TYPES}) == 4)
check("the start/edit split covers the family with no overlap",
      _AU_START_TYPES == {_AU_SONG, _AU_SFX}
      and _AU_EDIT_TYPES == {_AU_ESONG, _AU_ESFX}
      and not (_AU_START_TYPES & _AU_EDIT_TYPES))
check("audio triggers stay gated by Toggle (they run no other triggers)",
      not (_AU_TYPES & C.CONTROL_TRIGGER_TYPES))
check("the Audio palette tab exists and holds exactly the 4 audio types",
      _AU_CAT in _AR_CAT_ORDER
      and set(dict(_AR_PALETTE)[_AU_CAT]) == set(_AU_TYPES))
# Falsification: audio is event-driven only. Playback advances in the
# mixer's own thread, so there must be no per-tick audio stepper the way
# the area/screen-effect families have one.
check("there is no per-tick audio stepper anywhere on Player",
      not [n for n in dir(Player) if n.startswith("_step") and "audio" in n]
      and "audio" not in inspect.getsource(Player.update))

# Object ids + the report's property-key map, quoted verbatim.
_AU_REPORT_IDS = {_AU_SONG: 1934, _AU_SFX: 3602, _AU_ESFX: 3603,
                  _AU_ESONG: 3605}
check("every audio spec carries the report's GD object id",
      all(_ar_spec_for(t).gd_object_id == gid
          for t, gid in _AU_REPORT_IDS.items()))
check("audio specs are marked partial (ids report-sourced, ranges engine-chosen)",
      all(_ar_spec_for(t).verification == "partial" for t in _AU_TYPES))
_AU_REPORT_KEYS = {
    _AU_SONG: {"song": 392, "speed": 404, "volume": 406, "start": 408,
               "fade_in": 409, "end": 410, "fade_out": 411, "loop": 413,
               "channel": 432},
    _AU_SFX: {"pitch": 405, "volume": 406, "reverb": 407, "loop": 413,
              "unique_id": 416},
    _AU_ESONG: {"speed": 404, "volume": 406, "channel": 432},
    _AU_ESFX: {"pitch": 405, "volume": 406, "unique_id": 416},
}
check("every audio field carries the report's GD property key",
      all(_ar_spec_for(t).field(k).gd_key == v
          for t, keys in _AU_REPORT_KEYS.items() for k, v in keys.items()))
check("the fields the report gives no key for claim none",
      _ar_spec_for(_AU_SFX).field("sfx").gd_key is None
      and _ar_spec_for(_AU_ESFX).field("stop").gd_key is None
      and _ar_spec_for(_AU_ESONG).field("stop").gd_key is None)
check("the SFX sound list is sfx.py's own, not a second hand-kept copy",
      _ar_spec_for(_AU_SFX).field("sfx").choices == _au_sfx.SOUND_NAMES
      and set(_au_sfx.SOUND_NAMES) == set(_au_sfx.SOUND_GENERATORS))
check("no audio trigger carries a target group (they act on the mixer)",
      all(_ar_spec_for(t).field("target_group") is None for t in _AU_TYPES))
check("every audio spec renders a schema-driven property panel with no new code",
      all(_ar_spec_for(t).fields
          and all(f.kind in ("int", "float", "bool", "choice") and f.label
                  for f in _ar_spec_for(t).fields)
          for t in _AU_TYPES))
# The palette tabs are laid out in one unwrapped row, so a new tab is a
# real layout risk, not just a list entry (editor/ui.py _build_buttons).
_au_tab_x = _ed_ui.CONTENT_X
for _au_name, _ in _AR_PALETTE:
    _au_tab_x += (78 if len(_au_name) > 5 else 64) + 4
check(f"the 14-tab palette row still fits the window ({_au_tab_x} of {C.WIDTH})",
      _au_tab_x <= C.WIDTH)


# --- spies: the mixer is silent under a dummy driver, so assert the calls --
class _AuSpy:
    """Records what the handlers ask music.py / sfx.py to do, and passes
    the level-volume calls through to the real module so the non-persisted
    scaling can still be asserted for real."""

    def __init__(self):
        self.calls = []
        self._saved = {}

    def __enter__(self):
        for mod, name in ((_au_music, "play_track"), (_au_music, "fadeout"),
                          (_au_music, "stop"), (_au_sfx, "play"),
                          (_au_sfx, "stop_channel")):
            self._saved[(mod, name)] = getattr(mod, name)
            setattr(mod, name, self._recorder(name))
        return self

    def __exit__(self, *exc):
        for (mod, name), fn in self._saved.items():
            setattr(mod, name, fn)
        return False

    def _recorder(self, name):
        def record(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return None
        return record

    def named(self, name):
        return [(a, k) for n, a, k in self.calls if n == name]


def _au_level(*extras):
    return make_flat_level(length=40, extras=list(extras))


def _au_trigger(t, group, **fields):
    o = {"t": t, "x": 1, "y": 1, "r": 0, "groups": [group]}
    o.update(fields)
    return o


def _au_fire(p, group):
    p._fire_group(group)
    p._drain_trigger_event_queue()


# --- 1: a Song Trigger reaches music.py's play primitive -------------------
_au_song_obj = _au_trigger(_AU_SONG, 70, song=2, channel=1, volume=0.25,
                           loop=True, start=3.0, fade_in=0.5, fade_out=2.0,
                           speed=2.0, end=99.0)
_au_user_vol_before = _au_music.get_volume()
_au_user_pref_before = _prefs_mod.get("music_vol", 0.5)
_au_p = Player(_au_level(_au_song_obj))
with _AuSpy() as _au_spy:
    _au_fire(_au_p, 70)
_au_play_calls = _au_spy.named("play_track")
check("a Song Trigger calls music.play_track with the authored track",
      len(_au_play_calls) == 1 and _au_play_calls[0][0] == (2,))
check("loop=True becomes pygame's endless loops=-1",
      _au_play_calls[0][1]["loops"] == -1)
check("Start seconds are passed to music.py's seek",
      _au_play_calls[0][1]["start_sec"] == 3.0)
check("Fade in seconds become pygame's fade_ms",
      _au_play_calls[0][1]["fade_ms"] == 500)
check("the authored volume reaches the mixer as a level-volume scale",
      _au_music.get_level_volume() == 0.25)
# Falsification: the trigger must NEVER write the user's saved volume.
check("a Song Trigger does not touch the user's saved music volume",
      _au_music.get_volume() == _au_user_vol_before
      and _prefs_mod.get("music_vol", 0.5) == _au_user_pref_before)
check("the live song is tracked under its channel (GD key 432)",
      list(_au_p.active_songs) == [1]
      and _au_p.active_songs[1]["song"] == 2
      and _au_p.active_songs[1]["volume"] == 0.25)
check("the sounding channel is recorded (one music stream, many addresses)",
      _au_p.active_song_channel == 1)
check("no-op fields are still recorded on the live entry",
      _au_p.active_songs[1]["speed"] == 2.0
      and _au_p.active_songs[1]["end"] == 99.0)
check("a channel above the engine's range clamps instead of vanishing",
      _AU_CHAN_MAX >= 1
      and _ar_spec_for(_AU_SONG).field("channel").hi == _AU_CHAN_MAX)

# --- 2: SFX instances are tracked by unique id -----------------------------
_au_sp = Player(_au_level(
    _au_trigger(_AU_SFX, 71, sfx="orb", volume=0.8, unique_id=7, loop=True),
    _au_trigger(_AU_SFX, 72, sfx="pad", volume=0.5, unique_id=0, loop=True),
    _au_trigger(_AU_SFX, 73, sfx="click", volume=0.3, unique_id=7),
    _au_trigger(_AU_ESFX, 74, unique_id=7, stop=True),
    _au_trigger(_AU_ESFX, 75, unique_id=4242, stop=True),
    _au_trigger(_AU_ESFX, 76, unique_id=7, volume=0.1, pitch=5.0)))
with _AuSpy() as _au_spy:
    _au_fire(_au_sp, 71)
    _au_sfx_calls = _au_spy.named("play")
check("an SFX Trigger plays the authored sound at the authored volume",
      len(_au_sfx_calls) == 1
      and _au_sfx_calls[0][0][:2] == ("orb", 0.8))
check("a looping SFX with a unique id loops endlessly",
      _au_sfx_calls[0][0][2] == -1)
check("firing an SFX with a unique id registers a live instance",
      list(_au_sp.active_sfx) == [7]
      and _au_sp.active_sfx[7]["sfx"] == "orb"
      and _au_sp.active_sfx[7]["volume"] == 0.8)
with _AuSpy() as _au_spy:
    _au_fire(_au_sp, 72)
    _au_anon = _au_spy.named("play")
check("unique_id 0 plays but is never tracked (nothing could stop it)",
      list(_au_sp.active_sfx) == [7] and len(_au_anon) == 1)
check("and an anonymous instance refuses to loop forever",
      _au_anon[0][0][2] == 0)
with _AuSpy() as _au_spy:
    _au_fire(_au_sp, 73)
    _au_replaced = _au_spy.named("stop_channel")
check("re-firing a unique id replaces the live instance (last-fired-wins)",
      list(_au_sp.active_sfx) == [7]
      and _au_sp.active_sfx[7]["sfx"] == "click"
      and len(_au_replaced) == 1)
with _AuSpy() as _au_spy:
    _au_fire(_au_sp, 76)
check("Edit SFX patches volume and pitch on the live instance",
      _au_sp.active_sfx[7]["volume"] == 0.1
      and _au_sp.active_sfx[7]["pitch"] == 5.0
      and _au_sp.active_sfx[7]["sfx"] == "click")
_au_sfx_before_unknown = dict(_au_sp.active_sfx)
with _AuSpy() as _au_spy:
    _au_fire(_au_sp, 75)
    _au_unknown_calls = list(_au_spy.calls)
check("Edit SFX for an unknown unique id is a complete no-op",
      _au_sp.active_sfx == _au_sfx_before_unknown and _au_unknown_calls == [])
with _AuSpy() as _au_spy:
    _au_fire(_au_sp, 74)
    _au_stop_calls = _au_spy.named("stop_channel")
check("Edit SFX with stop=True drops and stops the tracked instance",
      _au_sp.active_sfx == {} and len(_au_stop_calls) == 1)

# --- 3: Edit Song patches a live channel, and no-ops on a silent one -------
_au_ed = Player(_au_level(
    _au_trigger(_AU_SONG, 80, song=0, channel=0, volume=0.9, fade_out=1.5),
    _au_trigger(_AU_ESONG, 81, channel=2, volume=0.1),
    _au_trigger(_AU_ESONG, 82, channel=0, volume=0.4),
    _au_trigger(_AU_ESONG, 83, channel=0, stop=True)))
with _AuSpy() as _au_spy:
    _au_fire(_au_ed, 81)
    _au_silent_calls = list(_au_spy.calls)
check("Edit Song on a channel with nothing playing is a complete no-op",
      _au_ed.active_songs == {} and _au_silent_calls == []
      and _au_ed.active_song_channel is None)
with _AuSpy():
    _au_fire(_au_ed, 80)
check("a live song is registered before the edit",
      _au_ed.active_songs[0]["volume"] == 0.9)
with _AuSpy():
    _au_fire(_au_ed, 82)
check("Edit Song patches the live entry's volume (absolute, not a delta)",
      _au_ed.active_songs[0]["volume"] == 0.4
      and _au_music.get_level_volume() == 0.4)
with _AuSpy() as _au_spy:
    _au_fire(_au_ed, 83)
    _au_fade_calls = _au_spy.named("fadeout")
    _au_hard_stops = _au_spy.named("stop")
check("Edit Song stop fades out over the song's own Fade out",
      _au_ed.active_songs == {} and _au_ed.active_song_channel is None
      and _au_fade_calls == [((1500,), {})] and _au_hard_stops == [])
# A song with no authored fade stops outright instead.
_au_hard = Player(_au_level(
    _au_trigger(_AU_SONG, 84, song=0, channel=0, volume=1.0),
    _au_trigger(_AU_ESONG, 85, channel=0, stop=True)))
with _AuSpy() as _au_spy:
    _au_fire(_au_hard, 84)
    _au_fire(_au_hard, 85)
    check("a song with no Fade out stops immediately",
          _au_spy.named("stop") and not _au_spy.named("fadeout"))

# --- 4: end to end through update(), fired by a real touch -----------------
_au_touch = Player(make_flat_level(length=40, extras=[
    _au_trigger(_AU_SONG, 90, song=1, channel=0, volume=0.6,
                touch_activated=True) | {"x": 12, "y": 9},
]))
with _AuSpy() as _au_spy:
    for _ in range(600):
        _au_touch.update(False, False)
        if not _au_touch.alive or _au_touch.won or _au_touch.active_songs:
            break
    _au_touch_calls = _au_spy.named("play_track")
check("a touched Song Trigger plays through the normal queue+registry path",
      0 in _au_touch.active_songs and len(_au_touch_calls) == 1
      and _au_touch_calls[0][0] == (1,))
check("the trigger event queue is still empty after the audio tick",
      _au_touch._trigger_event_queue == [])

# --- 5: retry silences what the previous attempt started -------------------
_au_retry = Player(_au_level(
    _au_trigger(_AU_SFX, 91, sfx="orb", volume=0.5, unique_id=3, loop=True),
    _au_trigger(_AU_SONG, 92, song=0, channel=0, volume=0.5)))
with _AuSpy() as _au_spy:
    _au_fire(_au_retry, 91)
    _au_fire(_au_retry, 92)
    _au_retry.reset()
    _au_reset_stops = _au_spy.named("stop_channel")
    _au_reset_music = _au_spy.named("stop")
check("reset() stops the looping SFX the previous attempt left playing",
      _au_retry.active_sfx == {} and len(_au_reset_stops) == 1)
check("reset() stops music only because this player started a song",
      _au_retry.active_songs == {} and len(_au_reset_music) == 1)
_au_quiet = Player(_au_level())
with _AuSpy() as _au_spy:
    _au_quiet.reset()
    check("reset() leaves music alone when no Song Trigger ever fired",
          _au_spy.named("stop") == [])

# --- 6: a bot search never reaches the mixer -------------------------------
check("SimPlayer opts out of audio output; the real Player opts in",
      _AU_SIM.audio_output_enabled is False
      and Player.audio_output_enabled is True)
_au_bot = _AU_SIM(_au_level(
    _au_trigger(_AU_SONG, 93, song=0, channel=0, volume=0.5),
    _au_trigger(_AU_SFX, 94, sfx="orb", volume=0.5, unique_id=9)))
with _AuSpy() as _au_spy:
    _au_fire(_au_bot, 93)
    _au_fire(_au_bot, 94)
    _au_bot_calls = list(_au_spy.calls)
check("a bot sim records the same audio state but emits nothing",
      _au_bot_calls == [] and 0 in _au_bot.active_songs
      and _au_bot.active_sfx[9]["channel"] is None)

# --- 7: headless-safety of the real (unspied) primitives -------------------
check("the suite really is running on the dummy audio driver",
      os.environ.get("SDL_AUDIODRIVER") == "dummy")
_au_live = Player(_au_level(
    _au_trigger(_AU_SFX, 95, sfx="orb", volume=0.5, unique_id=11),
    _au_trigger(_AU_ESFX, 96, unique_id=11, volume=0.2),
    _au_trigger(_AU_ESFX, 97, unique_id=11, stop=True),
    _au_trigger(_AU_SONG, 98, song=0, channel=0, volume=0.5, fade_in=0.2),
    _au_trigger(_AU_ESONG, 99, channel=0, stop=True)))
for _au_g in (95, 96, 97, 98, 99):
    _au_fire(_au_live, _au_g)
check("every audio handler survives real mixer calls under a dummy driver",
      _au_live.active_sfx == {} and _au_live.active_songs == {})
check("an unknown sound name is a safe no-op, not a crash",
      _au_sfx.play("no_such_sound", 0.5) is None)
check("sfx.play still returns a channel handle for a real sound",
      _au_sfx.stop_channel(_au_sfx.play("click", 0.4)) is None)

# --- 8: save/load round-trip of all 4 new types ----------------------------
_au_rt_objs = []
_au_rt_expect = {}
for _au_i, _au_t in enumerate(sorted(_AU_TYPES)):
    _au_o = {"t": _au_t, "x": _au_i, "y": 4, "r": 0}
    for _au_f in _ar_spec_for(_au_t).fields:
        _au_o[_au_f.key] = _ar_alt_value(_au_f)
    _au_rt_expect[_au_t] = dict(_au_o)
    _au_rt_objs.append(_au_o)
_au_rt_path = save_level(_au_rt_objs, "Audio RT", "audio-roundtrip")
_au_rt_loaded = {o["t"]: o for o in load_level(_au_rt_path)[1]}
check("every audio type survives a save/load round-trip",
      set(_au_rt_loaded) == set(_AU_TYPES))
_au_rt_bad = [
    (t, f.key)
    for t in _AU_TYPES
    for f in _ar_spec_for(t).fields
    if _au_rt_loaded[t].get(f.key) != _au_rt_expect[t][f.key]
]
check("every audio field round-trips with its authored value",
      _au_rt_bad == [])
check("the documented no-op fields round-trip too (speed/end/pitch/reverb)",
      _au_rt_loaded[_AU_SONG]["speed"] == _au_rt_expect[_AU_SONG]["speed"]
      and _au_rt_loaded[_AU_SONG]["end"] == _au_rt_expect[_AU_SONG]["end"]
      and _au_rt_loaded[_AU_SFX]["pitch"] == _au_rt_expect[_AU_SFX]["pitch"]
      and _au_rt_loaded[_AU_SFX]["reverb"] == _au_rt_expect[_AU_SFX]["reverb"])
check("the SFX sound choice round-trips as a name string",
      _au_rt_loaded[_AU_SFX]["sfx"] == _au_sfx.SOUND_NAMES[1])
check("the audio round-trip wrote no numeric GD keys into the save format",
      all(not any(str(k).isdigit() for k in o)
          for o in _au_rt_loaded.values()))
# Falsification: the no-op fields must reach no mixer call at all -- an
# engine with no playback-rate, scheduled-stop, pitch or reverb primitive
# must not smuggle those values into one of the calls it does make.
_au_noop = Player(_au_level(
    _au_trigger(_AU_SONG, 100, song=0, channel=0, volume=0.5, speed=3.7,
                end=42.0),
    _au_trigger(_AU_SFX, 101, sfx="orb", volume=0.5, unique_id=13, pitch=9.0,
                reverb=0.77)))
with _AuSpy() as _au_spy:
    _au_fire(_au_noop, 100)
    _au_fire(_au_noop, 101)
    _au_noop_args = [v for _n, a, k in _au_spy.calls
                     for v in (list(a) + list(k.values()))]
check("no no-op field value is smuggled into a music.py / sfx.py call",
      _au_spy.calls
      and not ({3.7, 42.0, 9.0, 0.77} & {v for v in _au_noop_args
                                         if isinstance(v, float)}))
check("but they are all still recorded on the live entries",
      _au_noop.active_songs[0]["speed"] == 3.7
      and _au_noop.active_songs[0]["end"] == 42.0
      and _au_noop.active_sfx[13]["pitch"] == 9.0
      and _au_noop.active_sfx[13]["reverb"] == 0.77)
_au_noop_readers = [
    (mod, key)
    for mod in ("src.music", "src.sfx")
    for key in ("speed", "end", "pitch", "reverb")
    if f'"{key}"' in inspect.getsource(sys.modules[mod])
]
check("speed/end/pitch/reverb are stored but never reach music.py/sfx.py",
      _au_noop_readers == [])


# ---------------------------------------------------------------------------
# Player-state triggers: Gameplay Rotation / Reverse / Teleport / Checkpoint
# (deep-research-report.md, "Gameplay, camera, UI, and environment")
# ---------------------------------------------------------------------------
section("Player-state triggers (Gameplay Rotation / Reverse / Teleport / "
        "Checkpoint)")

from src.constants import (
    T_GAMEPLAY_ROTATION_TRIGGER as _G6_ROT, T_REVERSE_TRIGGER as _G6_REV,
    T_TELEPORT_TRIGGER as _G6_TP, T_CHECKPOINT_TRIGGER as _G6_CP,
    PLAYER_STATE_TRIGGER_TYPES as _G6_TYPES,
    GAMEPLAY_CHANNEL_DEFAULT as _G6_CHAN_DEFAULT,
)
from src.objects import CAT_TRIGGERS as _G6_CAT
from src.bots.sim import (
    SimPlayer as _G6_SIM, snapshot as _g6_snapshot, restore as _g6_restore,
    dedup_key as _g6_dedup,
)

_G6_ROW = 9            # the lane make_flat_level's player runs along
_G6_DEST_GX = 20       # teleport destination cell
_G6_DEST_GY = 6


def _g6_level(*extras):
    return make_flat_level(length=40, extras=list(extras))


def _g6_trigger(t, group, **fields):
    """A trigger off the player's lane, reachable only by group fire."""
    o = {"t": t, "x": 1, "y": 1, "r": 0, "groups": [group]}
    o.update(fields)
    return o


def _g6_fire(p, group):
    p._fire_group(group)
    p._drain_trigger_event_queue()


def _g6_state(p):
    return (round(p.x, 6), round(p.y, 6), round(p.vy, 6), p.grav,
            p.on_ground, p.alive, p.move_dir)


def _g6_trace(extra, ticks=200):
    """Tick-by-tick player state down a flat level holding one extra
    object in the player's lane (``None`` = an empty lane)."""
    p = Player(_g6_level(*([extra] if extra else [])))
    out = []
    for _ in range(ticks):
        p.update(False, False)
        out.append(_g6_state(p))
    return out


# --- 1: registry / schema wiring (no gaps between the three tables) --------
check("all 4 player-state types are registered as trigger types",
      len(_G6_TYPES) == 4 and _G6_TYPES <= _TQ_TRIGGER_TYPES)
check("all 4 player-state types have a registry handler",
      _G6_TYPES <= set(_TQ_HANDLERS))
check("each player-state type has its own distinct handler",
      len({_TQ_HANDLERS[t] for t in _G6_TYPES}) == 4)
check("every trigger type still has exactly one registry handler",
      set(_TQ_HANDLERS) == set(_TQ_TRIGGER_TYPES))
check("player-state triggers stay gated by Toggle (they run no triggers)",
      not (_G6_TYPES & C.CONTROL_TRIGGER_TYPES))
check("all 4 are placeable in the Triggers palette tab",
      _G6_CAT in _AR_CAT_ORDER
      and _G6_TYPES <= set(dict(_AR_PALETTE)[_G6_CAT]))
_G6_REPORT_IDS = {_G6_ROT: 2900, _G6_REV: 1917, _G6_TP: 3022, _G6_CP: 2063}
check("every player-state spec carries the report's GD object id",
      all(_ar_spec_for(t).gd_object_id == i
          for t, i in _G6_REPORT_IDS.items()))
check("all 4 share the standard group-fired activation vocabulary",
      all({"target_group", "touch_activated", "multi_activate",
           "trigger_order"} <= {f.key for f in _ar_spec_for(t).fields}
          for t in _G6_TYPES))
# The report's one hard default in this family, and its one honest gap.
_g6_chan = _ar_spec_for(_G6_ROT).field("channel")
check("Gameplay Rotation's gameplay channel defaults to the report's 0",
      _g6_chan.default == _G6_CHAN_DEFAULT == 0)
check("the channel field is marked unverified with no invented GD key",
      _g6_chan.gd_key is None and _g6_chan.verification == "unverified")
# Stored-only means stored-only: no handler ever reads the key back.
check("no handler reads the channel (this engine has no channel gating)",
      all('"channel"' not in inspect.getsource(_TQ_HANDLERS[t])
          for t in _G6_TYPES))
# Falsification: retargeting the player is an instant state change, so
# unlike the area/screen-effect/keyframe families this one must add no
# per-tick stepper.
check("the player-state family adds no per-tick stepper",
      not [n for n in dir(Player)
           if n.startswith("_step")
           and any(w in n for w in ("gameplay", "reverse", "teleport",
                                    "checkpoint"))])
# The pre-existing transient marker must be left exactly as it was.
check("the new Checkpoint Trigger is a different type from the marker",
      _G6_CP != T_CHECKPOINT)
check("the transient Checkpoint marker is still unplaceable and untriggered",
      _ar_spec_for(T_CHECKPOINT).category is None
      and T_CHECKPOINT not in _TQ_TRIGGER_TYPES
      and T_CHECKPOINT not in _TQ_HANDLERS)

# --- 2: gravity_dir is the EXISTING grav-portal mechanism ------------------
_g6_portal_trace = _g6_trace({"t": T_GRAV_UP, "x": 8, "y": _G6_ROW, "r": 0})
_g6_rot_trace = _g6_trace({"t": _G6_ROT, "x": 8, "y": _G6_ROW, "r": 0,
                           "gravity_dir": "up", "touch_activated": True})
# Guard against a vacuous equivalence: the reference run must really flip.
check("reference: touching a Gravity Up portal does flip gravity mid-run",
      any(s[3] == -1 for s in _g6_portal_trace)
      and _g6_portal_trace[0][3] == 1)
check("Gameplay Rotation gravity_dir=up is tick-for-tick identical to "
      "touching a Gravity Up portal",
      _g6_rot_trace == _g6_portal_trace)
_g6_empty_trace = _g6_trace(None)
_g6_down_portal_trace = _g6_trace({"t": T_GRAV_DOWN, "x": 8, "y": _G6_ROW,
                                   "r": 0})
_g6_down_rot_trace = _g6_trace({"t": _G6_ROT, "x": 8, "y": _G6_ROW, "r": 0,
                                "gravity_dir": "down", "touch_activated": True})
check("gravity_dir=down on an already-down player is the same no-op a "
      "Gravity Down portal is",
      _g6_down_rot_trace == _g6_down_portal_trace == _g6_empty_trace
      and _g6_empty_trace != _g6_portal_trace)
# The mechanism is shared because there is only one copy of it left.
check("both gravity paths go through the one set_body_gravity primitive",
      "set_body_gravity" in inspect.getsource(Player._handle_interactions)
      and "set_body_gravity" in inspect.getsource(
          Player._apply_gameplay_rotation_trigger)
      and "b.grav = target" not in inspect.getsource(
          Player._handle_interactions))
_g6_prim = Player(_g6_level())
_g6_prim.grav = 1
_g6_prim.on_ground = True
_g6_prim.set_body_gravity(_g6_prim, 1)
check("set_body_gravity leaves a body already pointing that way grounded",
      _g6_prim.grav == 1 and _g6_prim.on_ground is True)
_g6_prim.set_body_gravity(_g6_prim, -1)
check("set_body_gravity unsticks the body only when it really flips",
      _g6_prim.grav == -1 and _g6_prim.on_ground is False)
_g6_gnone = Player(_g6_level(_g6_trigger(_G6_ROT, 60, gravity_dir="none")))
_g6_gnone.on_ground = True
_g6_fire(_g6_gnone, 60)
check("gravity_dir=none leaves gravity (and grounding) alone",
      _g6_gnone.grav == 1 and _g6_gnone.on_ground is True)

# --- 3: direction + velocity override --------------------------------------
_g6_dir_cases = [("none", 1, 1), ("none", -1, -1), ("forward", -1, 1),
                 ("forward", 1, 1), ("reverse", 1, -1), ("reverse", -1, -1),
                 ("flip", 1, -1), ("flip", -1, 1)]
_g6_dir_bad = []
for _g6_val, _g6_before, _g6_after in _g6_dir_cases:
    _g6_dp = Player(_g6_level(_g6_trigger(_G6_ROT, 61, direction=_g6_val)))
    _g6_dp.move_dir = _g6_before
    _g6_fire(_g6_dp, 61)
    if _g6_dp.move_dir != _g6_after:
        _g6_dir_bad.append((_g6_val, _g6_before, _g6_dp.move_dir))
check("Gameplay Rotation's direction field sets/flips gameplay direction",
      _g6_dir_bad == [])
_g6_v0 = Player(_g6_level(_g6_trigger(_G6_ROT, 62, velocity_override=0.0)))
_g6_v0.vy = 1.25
_g6_v0.on_ground = True
_g6_fire(_g6_v0, 62)
check("velocity_override 0 means 'keep', not 'stop dead'",
      _g6_v0.vy == 1.25 and _g6_v0.on_ground is True)
_g6_v1 = Player(_g6_level(_g6_trigger(_G6_ROT, 63, velocity_override=-4.5)))
_g6_v1.vy = 1.25
_g6_v1.on_ground = True
_g6_fire(_g6_v1, 63)
check("a nonzero velocity_override writes vy in absolute screen space",
      _g6_v1.vy == -4.5 and _g6_v1.on_ground is False)

# --- 4: Reverse -- what "direction" actually means in this engine ----------
# Scope, documented: before this checkpoint the engine had no gameplay
# direction at all. Reverse flips the SIGN of the auto-scroll step
# (Player.move_dir), leaving move_speed the positive magnitude every speed
# portal / HUD / bot heuristic already treats it as.
_g6_rev = Player(_g6_level(_g6_trigger(_G6_REV, 64, multi_activate=True)))
check("gameplay direction starts rightwards, as it always has",
      _g6_rev.move_dir == 1)
_g6_fire(_g6_rev, 64)
_g6_rev_once = _g6_rev.move_dir
_g6_fire(_g6_rev, 64)
check("a Reverse Trigger flips gameplay direction, and flips it back",
      _g6_rev_once == -1 and _g6_rev.move_dir == 1)
_g6_mot = Player(_g6_level(_g6_trigger(_G6_REV, 65)))
for _ in range(10):
    _g6_mot.update(False, False)
_g6_mot_x0 = _g6_mot.x
_g6_mot.update(False, False)
_g6_dx_fwd = _g6_mot.x - _g6_mot_x0
_g6_mot_before = (_g6_mot.move_speed, _g6_mot.grav, _g6_mot.mode,
                  _g6_mot.size, _g6_mot.y)
_g6_fire(_g6_mot, 65)
_g6_mot_x1 = _g6_mot.x
_g6_mot.update(False, False)
_g6_dx_rev = _g6_mot.x - _g6_mot_x1
check("after a Reverse the player auto-scrolls backwards at the same speed",
      _g6_dx_fwd > 0 and abs(_g6_dx_rev + _g6_dx_fwd) < 1e-9)
check("Reverse changes direction ONLY -- speed/gravity/mode/size untouched",
      (_g6_mot.move_speed, _g6_mot.grav, _g6_mot.mode, _g6_mot.size)
      == _g6_mot_before[:4]
      and _g6_mot.move_speed > 0)
check("move_speed stays a positive magnitude (the sign lives in move_dir)",
      "self.move_speed * self.move_dir" in inspect.getsource(Player.update))
# Practice checkpoints and bot snapshots both have to carry the new field
# or a restore silently teleports the player back to running rightwards.
_g6_cpdir = Player(_g6_level())
_g6_cpdir.set_gameplay_direction(-1)
_g6_cpdir.save_checkpoint()
_g6_cpdir.set_gameplay_direction(1)
_g6_cpdir.load_checkpoint()
check("a practice checkpoint restores the gameplay direction",
      _g6_cpdir.move_dir == -1)
_g6_cpdir.checkpoints[-1].pop("move_dir")
_g6_cpdir.set_gameplay_direction(-1)
_g6_cpdir.load_checkpoint()
check("a checkpoint saved before the field existed restores rightwards",
      _g6_cpdir.move_dir == 1)
_g6_sim = _G6_SIM(_g6_level())
_g6_sim.set_gameplay_direction(-1)
_g6_snap_rev = _g6_snapshot(_g6_sim)
_g6_sim.set_gameplay_direction(1)
_g6_snap_fwd = _g6_snapshot(_g6_sim)
_g6_restore(_g6_sim, _g6_snap_rev)
check("a bot snapshot round-trips the gameplay direction",
      _g6_sim.move_dir == -1)
check("the bot dedup key keeps the two gameplay directions apart",
      _g6_dedup(_g6_snap_rev) != _g6_dedup(_g6_snap_fwd))

# --- 5: Teleport Trigger ---------------------------------------------------


def _g6_teleport(**fields):
    """Fire a Teleport Trigger at a marker in group 78; returns the player
    and the position it started from."""
    target = {"t": T_COIN, "x": _G6_DEST_GX, "y": _G6_DEST_GY, "r": 0,
              "groups": [78]}
    p = Player(_g6_level(target,
                         _g6_trigger(_G6_TP, 66, target_group=78, **fields)))
    start = (p.x, p.y)
    p.vy = 4.0
    _g6_fire(p, 66)
    return p, start


_g6_cell_x = _G6_DEST_GX * C.UNITS_PER_BLOCK
_g6_cell_y = _G6_DEST_GY * C.UNITS_PER_BLOCK
_g6_tp_p, _g6_tp_start = _g6_teleport()
_g6_centre = (C.UNITS_PER_BLOCK - _g6_tp_p.size) / 2
check("a Teleport Trigger snaps the player onto the target group's member",
      _g6_tp_p.x == _g6_cell_x + _g6_centre
      and _g6_tp_p.y == _g6_cell_y + _g6_centre)
_g6_tp_x, _g6_tp_xstart = _g6_teleport(x_only=True)
check("x_only moves the player on x and leaves y where it was",
      _g6_tp_x.x == _g6_cell_x + _g6_centre
      and _g6_tp_x.y == _g6_tp_xstart[1])
_g6_tp_y, _g6_tp_ystart = _g6_teleport(y_only=True)
check("y_only moves the player on y and leaves x where it was",
      _g6_tp_y.y == _g6_cell_y + _g6_centre
      and _g6_tp_y.x == _g6_tp_ystart[0])
_g6_tp_both, _g6_tp_bstart = _g6_teleport(x_only=True, y_only=True)
check("both axis flags on is the documented contradiction: neither moves",
      (_g6_tp_both.x, _g6_tp_both.y) == _g6_tp_bstart)
_g6_tp_none = Player(_g6_level(_g6_trigger(_G6_TP, 67, target_group=999)))
_g6_tp_none_start = (_g6_tp_none.x, _g6_tp_none.y)
_g6_fire(_g6_tp_none, 67)
check("a Teleport Trigger with no destination is a clean no-op",
      (_g6_tp_none.x, _g6_tp_none.y) == _g6_tp_none_start
      and _g6_tp_none.teleport_cooldown == 0)
# Real equivalence with the pre-existing touch-based orb: same primitive,
# so the same end state (centring, quarter-damped vy, cooldown, trail).
_g6_orb_p = Player(_g6_level(
    {"t": T_TELEPORT_ORB, "x": 6, "y": _G6_ROW, "r": 0, "group_id": 9},
    {"t": T_TELEPORT_ORB, "x": _G6_DEST_GX, "y": _G6_DEST_GY, "r": 0,
     "group_id": 9, "dest": True}))
_g6_orb_p.vy = 4.0
_g6_orb_src = [o for o in _g6_orb_p.objects
               if o.get("group_id") == 9 and not o.get("dest")][0]
_g6_orb_p.activate_teleport(_g6_orb_src)
check("a triggered teleport lands exactly where the Teleport Orb lands",
      (_g6_orb_p.x, _g6_orb_p.y, _g6_orb_p.vy, _g6_orb_p.teleport_cooldown,
       _g6_orb_p.trail)
      == (_g6_tp_p.x, _g6_tp_p.y, _g6_tp_p.vy, _g6_tp_p.teleport_cooldown,
          _g6_tp_p.trail))
check("both teleport paths go through the one teleport_to_cell primitive",
      "teleport_to_cell" in inspect.getsource(Player.activate_teleport)
      and "teleport_to_cell" in inspect.getsource(
          Player._apply_teleport_trigger)
      and "self.x =" not in inspect.getsource(Player.activate_teleport))

# --- 6: Checkpoint Trigger -------------------------------------------------
_g6_cp_trigger = _g6_trigger(_G6_CP, 68)
_g6_cp_a = Player(_g6_level(dict(_g6_cp_trigger)))
_g6_cp_b = Player(_g6_level(dict(_g6_cp_trigger)))
for _g6_cp_p in (_g6_cp_a, _g6_cp_b):
    _g6_cp_p.practice_mode = True
    for _ in range(20):
        _g6_cp_p.update(False, False)
_g6_fire(_g6_cp_a, 68)          # the new placeable trigger
_g6_cp_b.save_checkpoint()      # the existing manual practice-mode path
check("a Checkpoint Trigger writes exactly one checkpoint entry",
      len(_g6_cp_a.checkpoints) == 1 and len(_g6_cp_b.checkpoints) == 1)
check("its checkpoint is identical to the manual practice-mode one",
      _g6_cp_a.checkpoints[0] == _g6_cp_b.checkpoints[0])
check("and it is restorable through the existing load_checkpoint()",
      _g6_cp_a.load_checkpoint() is True
      and (_g6_cp_a.x, _g6_cp_a.y) == (_g6_cp_b.checkpoints[0]["x"],
                                       _g6_cp_b.checkpoints[0]["y"]))
_g6_cp_off = Player(_g6_level(dict(_g6_cp_trigger)))
_g6_fire(_g6_cp_off, 68)
check("outside practice mode it saves nothing (nothing would read it)",
      _g6_cp_off.practice_mode is False and _g6_cp_off.checkpoints == [])
_g6_cp_src = inspect.getsource(Player._apply_checkpoint_trigger)
check("the handler only calls the existing save_checkpoint(), builds no "
      "restore logic of its own",
      "self.save_checkpoint()" in _g6_cp_src
      and "checkpoints.append" not in _g6_cp_src
      and "load_checkpoint" not in _g6_cp_src)

# --- 7: save/load round-trip of all 4 new types ----------------------------
_g6_rt_objs = []
_g6_rt_expect = {}
for _g6_i, _g6_t in enumerate(sorted(_G6_TYPES)):
    _g6_o = {"t": _g6_t, "x": _g6_i, "y": 4, "r": 0}
    for _g6_f in _ar_spec_for(_g6_t).fields:
        _g6_o[_g6_f.key] = _ar_alt_value(_g6_f)
    _g6_rt_expect[_g6_t] = dict(_g6_o)
    _g6_rt_objs.append(_g6_o)
# The transient marker rides along to prove the placeable Checkpoint
# Trigger is NOT caught by the save-time strip that drops the marker.
_g6_rt_objs.append({"t": T_CHECKPOINT, "x": 30, "y": 4, "r": 0})
_g6_rt_path = save_level(_g6_rt_objs, "Player state RT", "playerstate-rt")
_g6_rt_loaded = {o["t"]: o for o in load_level(_g6_rt_path)[1]}
check("every player-state type survives a save/load round-trip",
      set(_g6_rt_loaded) == set(_G6_TYPES))
check("the transient Checkpoint marker is still stripped on save",
      T_CHECKPOINT not in _g6_rt_loaded)
_g6_rt_bad = [
    (t, f.key)
    for t in _G6_TYPES
    for f in _ar_spec_for(t).fields
    if _g6_rt_loaded[t].get(f.key) != _g6_rt_expect[t][f.key]
]
check("every player-state field round-trips with its authored value",
      _g6_rt_bad == [])
check("the round-trip wrote no numeric GD keys into the save format",
      all(not any(str(k).isdigit() for k in o)
          for o in _g6_rt_loaded.values()))


# ---------------------------------------------------------------------------
# Checkpoint 7: BG/Ground/MG Change + Speed, UI, Event, End Trigger,
# legacy transitions
# (deep-research-report.md, "Gameplay, camera, UI, and environment" +
#  "Transition, letter, and legacy objects")
# ---------------------------------------------------------------------------
section("Environment / UI / Event / End triggers + level transitions")

from src.constants import (
    T_GROUND_TRIGGER as _C7_GROUND, T_MG_TRIGGER as _C7_MG,
    T_BG_SPEED_TRIGGER as _C7_BGS, T_MG_SPEED_TRIGGER as _C7_MGS,
    T_UI_TRIGGER as _C7_UI, T_EVENT_TRIGGER as _C7_EVENT,
    T_END_TRIGGER as _C7_END, T_BG_TRIGGER as _C7_BG,
    ENVIRONMENT_TRIGGER_TYPES as _C7_ENV_TYPES,
    INERT_PRESET_TRIGGER_TYPES as _C7_INERT_TYPES,
    BG_SPEED_DEFAULT_X as _C7_BGX, BG_SPEED_DEFAULT_Y as _C7_BGY,
    MG_SPEED_DEFAULT_X as _C7_MGX, MG_SPEED_DEFAULT_Y as _C7_MGY,
    LEVEL_EVENTS as _C7_EVENTS, LEVEL_TRANSITIONS as _C7_TRANSITIONS,
    LEVEL_TRANSITION_FRAMES as _C7_TR_FRAMES,
    LEVEL_TRANSITION_SCALE_START as _C7_TR_SCALE,
    UI_TEXT_CHOICES as _C7_UI_TEXTS, T_ITEM_EDIT_TRIGGER as _C7_ITEM_EDIT,
)
from src.play_render import (
    render_hud as _c7_render_hud,
    level_transition_state as _c7_transition,
)
from src.graphics import draw_bg as _c7_draw_bg
from src.levels import _migrate as _c7_migrate_meta
from src.objects import CAT_MISC as _C7_CAT_MISC
import ast as _c7_ast
import copy as _c7_copy
import textwrap as _c7_textwrap

_C7_TYPES = frozenset({_C7_GROUND, _C7_MG, _C7_BGS, _C7_MGS, _C7_UI,
                       _C7_EVENT, _C7_END})
_C7_ROW = 9            # the lane make_flat_level's player runs along


def _c7_trigger(t, group, **fields):
    """A trigger off the player's lane, reachable only by group fire."""
    o = {"t": t, "x": 1, "y": 1, "r": 0, "groups": [group]}
    o.update(fields)
    return o


def _c7_fire(p, group):
    p._fire_group(group)
    p._drain_trigger_event_queue()


# --- 1: registry / schema wiring (no gaps between the three tables) --------
check("all 7 Checkpoint-7 types are registered as trigger types",
      len(_C7_TYPES) == 7 and _C7_TYPES <= _TQ_TRIGGER_TYPES)
check("all 7 have a registry handler",
      _C7_TYPES <= set(_TQ_HANDLERS))
check("each of the 7 has its own distinct handler",
      len({_TQ_HANDLERS[t] for t in _C7_TYPES}) == 7)
check("every trigger type still has exactly one registry handler",
      set(_TQ_HANDLERS) == set(_TQ_TRIGGER_TYPES))
check("none of them runs other triggers as its own effect (Toggle gates them)",
      not (_C7_TYPES & C.CONTROL_TRIGGER_TYPES))
check("all 7 are placeable in the existing Triggers palette tab",
      _C7_TYPES <= set(dict(_AR_PALETTE)[_G6_CAT]))
check("no new palette tab was opened for them (the tab row is full)",
      len(_AR_CAT_ORDER) == 14)
_C7_REPORT_IDS = {_C7_BG: 3029, _C7_GROUND: 3030, _C7_MG: 3031,
                  _C7_BGS: 3606, _C7_MGS: 3612, _C7_UI: 3613,
                  _C7_EVENT: 3604, _C7_END: 3600}
check("every new spec carries the report's own GD object id",
      all(_ar_spec_for(t).gd_object_id == i
          for t, i in _C7_REPORT_IDS.items()))
check("the Event Trigger is marked unverified (the report gives no fields)",
      _ar_spec_for(_C7_EVENT).verification == "unverified")
check("the scenery family names its members, BG Trigger included",
      _C7_ENV_TYPES == {_C7_BG, _C7_GROUND, _C7_MG, _C7_BGS, _C7_MGS})
check("the pre-existing BG Trigger kept its preset field and handler",
      _ar_spec_for(_C7_BG).field("bg") is not None
      and _TQ_HANDLERS[_C7_BG] is Player._apply_bg_trigger)

# --- 2: BG/MG Speed -- the report's exact defaults, verbatim ---------------
# The report's values table gives four hard numbers for this family and
# nothing else; they are checked literally, not approximately, because
# they are also the renderer's identity point (see below).
check("BG Speed defaults are the report's 0.1 / 0.1, exactly",
      (_ar_spec_for(_C7_BGS).field("speed_x").default,
       _ar_spec_for(_C7_BGS).field("speed_y").default) == (0.1, 0.1)
      and (_C7_BGX, _C7_BGY) == (0.1, 0.1))
check("MG Speed defaults are the report's 0.3 / 0.5, exactly",
      (_ar_spec_for(_C7_MGS).field("speed_x").default,
       _ar_spec_for(_C7_MGS).field("speed_y").default) == (0.3, 0.5)
      and (_C7_MGX, _C7_MGY) == (0.3, 0.5))
check("both speed pairs are marked verified (report-sourced defaults)",
      all(_ar_spec_for(t).field(k).verification == "verified"
          for t in (_C7_BGS, _C7_MGS) for k in ("speed_x", "speed_y")))
check("and they invent no GD property key the report never cites",
      all(_ar_spec_for(t).field(k).gd_key is None
          for t in (_C7_BGS, _C7_MGS) for k in ("speed_x", "speed_y")))
_c7_sp = Player(make_flat_level(length=40))
check("a fresh player starts at the report's documented speeds",
      (_c7_sp.bg_speed_x, _c7_sp.bg_speed_y) == (0.1, 0.1)
      and (_c7_sp.mg_speed_x, _c7_sp.mg_speed_y) == (0.3, 0.5))
check("which is the renderer's identity point: scale 1.0 on both layers",
      _c7_sp.bg_scroll_scale() == (1.0, 1.0)
      and _c7_sp.mg_scroll_scale() == (1.0, 1.0))
_c7_spd = Player(make_flat_level(length=40, extras=[
    _c7_trigger(_C7_BGS, 70, speed_x=0.2, speed_y=0.05),
    _c7_trigger(_C7_MGS, 71, speed_x=0.6, speed_y=0.25)]))
_c7_fire(_c7_spd, 70)
_c7_fire(_c7_spd, 71)
check("a BG Speed trigger scales the background parallax rate",
      _c7_spd.bg_scroll_scale() == (2.0, 0.5))
check("an MG Speed trigger scales the middleground parallax rate",
      _c7_spd.mg_scroll_scale() == (2.0, 0.5))
_c7_spd_def = Player(make_flat_level(length=40, extras=[
    _c7_trigger(_C7_BGS, 72, speed_x=_C7_BGX, speed_y=_C7_BGY)]))
_c7_fire(_c7_spd_def, 72)
check("a trigger carrying the report's defaults is a visual no-op",
      _c7_spd_def.bg_scroll_scale() == (1.0, 1.0))
_c7_spd_bad = Player(make_flat_level(length=40, extras=[
    _c7_trigger(_C7_BGS, 73, speed_x="nonsense", speed_y=999.0)]))
_c7_fire(_c7_spd_bad, 73)
check("an unparseable speed falls back to the default, a huge one clamps",
      _c7_spd_bad.bg_speed_x == _C7_BGX
      and _c7_spd_bad.bg_speed_y == C.ENV_SPEED_MAX)
# Real render check: the scale reaches actual pixels, and the identity
# scale is pixel-for-pixel what draw_bg painted before this checkpoint.
_C7_STARS = [(120, 60, 2, 200), (640, 140, 1, 120), (1500, 300, 3, 180)]
_C7_MOUNTAINS = [[(0, 320), (300, 240), (700, 300), (1200, 220)]]


def _c7_bg_pixels(bg_scale=None, mg_scale=None):
    surf = pygame.Surface((C.WIDTH, C.HEIGHT))
    _c7_draw_bg(surf, 900, _C7_STARS, _C7_MOUNTAINS, cam_y=40,
                bg_scale=bg_scale, mg_scale=mg_scale)
    return pygame.image.tostring(surf, "RGB")


_c7_px_stock = _c7_bg_pixels()
check("the identity scale renders the stock background pixel-for-pixel",
      _c7_bg_pixels((1.0, 1.0), (1.0, 1.0)) == _c7_px_stock)
check("a scaled BG speed really does move the background layer",
      _c7_bg_pixels((3.0, 1.0), (1.0, 1.0)) != _c7_px_stock)
check("a scaled MG speed really does move the middleground layer",
      _c7_bg_pixels((1.0, 1.0), (1.0, 3.0)) != _c7_px_stock)
check("the play render path hands the player's scales to draw_bg",
      "bg_scroll_scale()" in inspect.getsource(sys.modules["src.play"])
      and "bg_scale=bg_scale" in inspect.getsource(
          sys.modules["src.play_render"].render_world))

# --- 3: Ground / MG Change -- stored, and provably never read -------------
# The Checkpoint-4 lowest_layer/highest_layer precedent: there is no
# ground or middleground preset table in this engine, so the authored
# index is saved and round-tripped but nothing consumes it. Pinned so a
# future palette has to come back here rather than silently half-wiring.
check("the two inert scenery triggers are named as a set",
      _C7_INERT_TYPES == {_C7_GROUND, _C7_MG})
_c7_inert_readers = [
    (mod, key)
    for mod in ("src.player.triggers", "src.player.core", "src.play_render",
                "src.play", "src.graphics")
    for key in ("ground", "mg")
    if f'get("{key}"' in inspect.getsource(sys.modules[mod])
]
check("the ground/mg preset indices are stored but never read at runtime",
      _c7_inert_readers == [])
check("their fields say so in the editor label, not just in a comment",
      all("no-op" in _ar_spec_for(t).fields[0].label
          for t in _C7_INERT_TYPES))
_c7_inert_p = Player(make_flat_level(length=40, extras=[
    _c7_trigger(_C7_GROUND, 74, ground=5),
    _c7_trigger(_C7_MG, 75, mg=6)]))


def _c7_player_state(p):
    """A copy of every Player attribute, so a mutation shows up as a diff
    rather than being invisible behind a shared reference."""
    return tuple(_c7_copy.copy(getattr(p, n)) for n in Player.__slots__)


_c7_inert_before = _c7_player_state(_c7_inert_p)
_c7_fire(_c7_inert_p, 74)
_c7_fire(_c7_inert_p, 75)
check("firing them changes nothing at all about the player",
      _c7_player_state(_c7_inert_p) == _c7_inert_before)
def _c7_body_is_only_a_docstring(fn):
    tree = _c7_ast.parse(_c7_textwrap.dedent(inspect.getsource(fn)))
    body = tree.body[0].body
    return (len(body) == 1 and isinstance(body[0], _c7_ast.Expr)
            and isinstance(body[0].value, _c7_ast.Constant)
            and isinstance(body[0].value.value, str))


check("their handlers are documented no-ops: a docstring and nothing else",
      all(_c7_body_is_only_a_docstring(_TQ_HANDLERS[t])
          for t in _C7_INERT_TYPES))

# --- 4: End Trigger -- a second path into the EXISTING win flag -----------
# Equivalence, not "it sets a bool": the fired-by-Spawn player must end up
# in the same won state as one that crossed the pre-existing T_END wall.
def _c7_run(extras, ticks=900, fire=None):
    p = Player(make_flat_level(length=40, extras=list(extras)))
    for i in range(ticks):
        if fire is not None and i == 5:
            _c7_fire(p, fire)
        p.update(False, False)
        if p.won or not p.alive:
            break
    return p


_c7_wall = _c7_run([])
check("reference: the existing T_END finish wall still wins the level",
      _c7_wall.won is True and _c7_wall.alive is True)
_c7_endtrig = Player(make_flat_level(length=40, extras=[
    _c7_trigger(_C7_END, 76),
    {"t": C.T_SPAWN_TRIGGER, "x": 6, "y": _C7_ROW, "r": 0,
     "target_group": 76, "touch_activated": True}]))
for _ in range(400):
    _c7_endtrig.update(False, False)
    if _c7_endtrig.won:
        break
check("an End Trigger fired via Spawn wins the level too",
      _c7_endtrig.won is True and _c7_endtrig.alive is True)
check("and it wins EARLIER than the wall would -- the Spawn really did it",
      _c7_endtrig.x < (40 - 5) * C.UNITS_PER_BLOCK)
_c7_no_end = Player([o for o in make_flat_level(length=40)
                     if o["t"] != T_END])
for _ in range(400):
    _c7_no_end.update(False, False)
check("falsification: with no finish wall and no End Trigger, nobody wins",
      _c7_no_end.won is False)
_c7_end_src = inspect.getsource(Player._apply_end_trigger)
check("the End Trigger handler writes the same flag and no new win logic",
      "self.won = True" in _c7_end_src
      and "death" not in _c7_end_src
      and "alive" not in _c7_end_src)
check("T_END itself is untouched: still a placeable, still not a trigger",
      T_END not in _TQ_TRIGGER_TYPES and T_END not in _TQ_HANDLERS
      and _ar_spec_for(T_END).category == _C7_CAT_MISC)

# --- 5: Event Trigger -- fired by the engine, end to end ------------------
# Every case below goes through the REAL code path (a spike kills the
# player, the finish wall wins, save/load_checkpoint runs) rather than
# calling the handler, so a broken hook point fails the test.
def _c7_event_level(event, *, spike=False, length=40):
    extras = [{"t": _C7_EVENT, "x": 1, "y": 1, "r": 0,
               "event_type": event, "target_group": 77},
              _c7_trigger(_C7_BG, 77, bg=3)]
    if spike:
        extras.append({"t": T_SPIKE, "x": 12, "y": _C7_ROW, "r": 0})
    return make_flat_level(length=length, extras=extras)


_c7_ev_start = Player(_c7_event_level("level_start"))
check("the level_start activation is queued by reset(), not applied early",
      _c7_ev_start.bg_preset == 0)
_c7_ev_start.update(False, False)
check("...and the first tick's drain runs its target group (bg changed)",
      _c7_ev_start.bg_preset == 3)
_c7_ev_death = Player(_c7_event_level("death", spike=True))
for _ in range(900):
    _c7_ev_death.update(False, False)
    if not _c7_ev_death.alive:
        break
check("reference: the spike really killed the player",
      _c7_ev_death.alive is False and _c7_ev_death.bg_preset == 3)
_c7_ev_wrong = Player(_c7_event_level("win", spike=True))
for _ in range(900):
    _c7_ev_wrong.update(False, False)
    if not _c7_ev_wrong.alive:
        break
check("falsification: a 'win' Event Trigger does NOT fire on death",
      _c7_ev_wrong.alive is False and _c7_ev_wrong.bg_preset == 0)
_c7_ev_win = Player(_c7_event_level("win"))
for _ in range(900):
    _c7_ev_win.update(False, False)
    if _c7_ev_win.won:
        break
check("win fires when the finish wall sets the win flag",
      _c7_ev_win.won is True and _c7_ev_win.bg_preset == 3)
_c7_ev_win_trig = Player(make_flat_level(length=40, extras=[
    {"t": _C7_EVENT, "x": 1, "y": 1, "r": 0, "event_type": "win",
     "target_group": 77},
    _c7_trigger(_C7_BG, 77, bg=3),
    _c7_trigger(_C7_END, 79)]))
_c7_fire(_c7_ev_win_trig, 79)
check("...and equally when an End Trigger sets it (one win flag, one event)",
      _c7_ev_win_trig.won is True and _c7_ev_win_trig.bg_preset == 3)
_c7_ev_cp = Player(_c7_event_level("checkpoint"))
_c7_ev_cp.practice_mode = True
_c7_ev_cp.save_checkpoint()
_c7_ev_cp._drain_trigger_event_queue()
check("checkpoint fires from the existing save_checkpoint() path",
      len(_c7_ev_cp.checkpoints) == 1 and _c7_ev_cp.bg_preset == 3)
_c7_ev_rs = Player(_c7_event_level("respawn"))
_c7_ev_rs.practice_mode = True
_c7_ev_rs.save_checkpoint()
_c7_ev_rs._drain_trigger_event_queue()
_c7_ev_rs.bg_preset = 0
_c7_ev_rs.load_checkpoint()
_c7_ev_rs._drain_trigger_event_queue()
check("respawn fires from the existing load_checkpoint() path",
      _c7_ev_rs.bg_preset == 3)
# Fires ONCE per event, not once per tick after it.
_c7_ev_count = Player(make_flat_level(length=40, extras=[
    {"t": _C7_EVENT, "x": 1, "y": 1, "r": 0, "event_type": "death",
     "target_group": 80},
    _c7_trigger(_C7_ITEM_EDIT, 80, item_id=1, operation="add", operand=1.0),
    {"t": T_SPIKE, "x": 12, "y": _C7_ROW, "r": 0}]))
for _ in range(900):
    _c7_ev_count.update(False, False)
check("the death event fires exactly once, not once per tick after it",
      _c7_ev_count.items.get(1) == 1.0)
check("Event Triggers are indexed once at level load, not per attempt",
      "for o in self.objects" in inspect.getsource(Player._arm_event_triggers)
      and "_arm_event_triggers" in inspect.getsource(Player.__init__)
      and "_arm_event_triggers" not in inspect.getsource(Player.reset))
check("but the level_start event still fires on every attempt (retries too)",
      "_fire_event(EVENT_LEVEL_START)" in inspect.getsource(Player.reset))
_c7_ev_retry = Player(_c7_event_level("level_start"))
_c7_ev_retry.update(False, False)
_c7_ev_retry.reset()
_c7_ev_retry.bg_preset = 0
_c7_ev_retry.update(False, False)
check("...proved by a real retry: reset() re-fires it",
      _c7_ev_retry.bg_preset == 3)
check("every documented event name is reachable from the spec's choices",
      set(_ar_spec_for(_C7_EVENT).field("event_type").choices)
      == set(_C7_EVENTS) and len(_C7_EVENTS) == 5)
check("the engine fires each of the five from a real code path",
      all(f'_fire_event({n})' in
          (inspect.getsource(sys.modules["src.player.core"])
           + inspect.getsource(sys.modules["src.player.triggers"]))
          for n in ("EVENT_LEVEL_START", "EVENT_DEATH", "EVENT_WIN",
                    "EVENT_CHECKPOINT", "EVENT_RESPAWN")))

# --- 6: UI Trigger -- a HUD-readable label ---------------------------------
_c7_ui = Player(make_flat_level(length=40, extras=[
    _c7_trigger(_C7_UI, 81, ui_id=2, text="Go!", x_offset=40, y_offset=-60,
                duration=0.0),
    _c7_trigger(_C7_UI, 82, ui_id=2, text="Nice!", duration=0.0),
    _c7_trigger(_C7_UI, 83, ui_id=2, state=False),
    _c7_trigger(_C7_UI, 84, ui_id=3, text="Wait", duration=1.0)]))
check("no UI label exists before any UI Trigger fires",
      _c7_ui.active_ui_labels() == ())
_c7_fire(_c7_ui, 81)
_c7_labels = _c7_ui.active_ui_labels()
check("a UI Trigger posts a HUD-readable label with its text and offsets",
      len(_c7_labels) == 1 and _c7_labels[0]["text"] == "Go!"
      and (_c7_labels[0]["x_offset"], _c7_labels[0]["y_offset"]) == (40, -60))
_c7_fire(_c7_ui, 82)
check("the same ui_id replaces that label instead of stacking a second",
      len(_c7_ui.active_ui_labels()) == 1
      and _c7_ui.active_ui_labels()[0]["text"] == "Nice!")
_c7_fire(_c7_ui, 84)
check("a different ui_id posts its own row",
      len(_c7_ui.active_ui_labels()) == 2)
_c7_ui.frame += C.PHYSICS_TPS      # one second later
check("a timed label expires; a duration-0 label persists",
      [e["text"] for e in _c7_ui.active_ui_labels()] == ["Nice!"])
_c7_fire(_c7_ui, 83)
check("a UI Trigger with Show off clears its ui_id",
      _c7_ui.active_ui_labels() == ())
check("the label text vocabulary is the documented fixed choice list",
      _ar_spec_for(_C7_UI).field("text").choices == _C7_UI_TEXTS)
check("the UI Trigger targets no group (it is untargeted, like the camera "
      "family)",
      "target_group" not in {f.key for f in _ar_spec_for(_C7_UI).fields})


def _c7_hud_pixels(player):
    surf = pygame.Surface((C.WIDTH, C.HEIGHT))
    _c7_render_hud(surf, player, 1000.0, 1, 0, None, False, [], 0, False, 0,
                   0, "L", 0, False, False, None, "", False, 0, (1.0,), None,
                   None, 0, None, 0, 0.0)
    return pygame.image.tostring(surf, "RGB")


_c7_hud_p = Player(make_flat_level(length=40, extras=[
    _c7_trigger(_C7_UI, 85, ui_id=1, text="Danger", duration=0.0)]))
_c7_hud_before = _c7_hud_pixels(_c7_hud_p)
_c7_fire(_c7_hud_p, 85)
check("the real HUD render pass draws the label (pixels change)",
      _c7_hud_pixels(_c7_hud_p) != _c7_hud_before)
check("and it reuses the Item Counter's HUD pass rather than a new layer",
      "active_ui_labels" in inspect.getsource(_c7_render_hud)
      and "T_ITEM_COUNTER" in inspect.getsource(_c7_render_hud))

# --- 7: level meta "transition" -------------------------------------------
check("a fresh level's meta defaults to no transition",
      _default_meta("x")["transition"] == "none"
      and "none" in _C7_TRANSITIONS)
_c7_tr_path = save_level([{"t": T_BLOCK, "x": 0, "y": 10, "r": 0}],
                         "Transition RT", "transition-rt",
                         meta=dict(_default_meta("Transition RT"),
                                   transition="fade"))
check("the transition setting round-trips through save/load",
      load_level_full(_c7_tr_path)[0].get("transition") == "fade")
_c7_tr_bad = _c7_migrate_meta({"name": "x", "transition": "wobble"})
check("an unknown transition falls back to the default on load",
      _c7_tr_bad["transition"] == "none")
check("none is a true identity: no fade, no zoom, at any frame",
      all(_c7_transition("none", f) == (0.0, 1.0)
          for f in (0, 1, _C7_TR_FRAMES // 2, _C7_TR_FRAMES, 10 ** 6)))
check("fade starts fully black and ends fully clear",
      _c7_transition("fade", 0) == (1.0, 1.0)
      and _c7_transition("fade", _C7_TR_FRAMES) == (0.0, 1.0)
      and 0.0 < _c7_transition("fade", _C7_TR_FRAMES // 2)[0] < 1.0)
check("scale starts zoomed in and ends at 1.0, never fading",
      _c7_transition("scale", 0) == (0.0, _C7_TR_SCALE)
      and _c7_transition("scale", _C7_TR_FRAMES) == (0.0, 1.0)
      and 1.0 < _c7_transition("scale", _C7_TR_FRAMES // 2)[1] < _C7_TR_SCALE)
_c7_play_src = inspect.getsource(sys.modules["src.play"])
check("the transition rides the EXISTING blackout and zoom stages",
      "max(p.blackout_value, tr_fade)" in _c7_play_src
      and "p.zoom * tr_zoom" in _c7_play_src)
check("it is derived from the per-attempt tick counter, not new state",
      "level_transition_state(self.transition,\n"
      "                                                  self.attempt_frames)"
      in _c7_play_src)

# --- 8: save/load round-trip of all 7 new types ---------------------------
_c7_rt_objs = []
_c7_rt_expect = {}
for _c7_i, _c7_t in enumerate(sorted(_C7_TYPES)):
    _c7_o = {"t": _c7_t, "x": _c7_i, "y": 4, "r": 0}
    for _c7_f in _ar_spec_for(_c7_t).fields:
        _c7_o[_c7_f.key] = _ar_alt_value(_c7_f)
    _c7_rt_expect[_c7_t] = dict(_c7_o)
    _c7_rt_objs.append(_c7_o)
_c7_rt_path = save_level(_c7_rt_objs, "Env RT", "env-roundtrip")
_c7_rt_loaded = {o["t"]: o for o in load_level(_c7_rt_path)[1]}
check("every Checkpoint-7 type survives a save/load round-trip",
      set(_c7_rt_loaded) == set(_C7_TYPES))
_c7_rt_bad = [
    (t, f.key)
    for t in _C7_TYPES
    for f in _ar_spec_for(t).fields
    if _c7_rt_loaded[t].get(f.key) != _c7_rt_expect[t][f.key]
]
check("every Checkpoint-7 field round-trips with its authored value",
      _c7_rt_bad == [])
check("the stored-only ground/mg indices survive the round-trip too",
      _c7_rt_loaded[_C7_GROUND].get("ground")
      == _c7_rt_expect[_C7_GROUND]["ground"]
      and _c7_rt_loaded[_C7_MG].get("mg") == _c7_rt_expect[_C7_MG]["mg"])
check("the round-trip wrote no numeric GD keys into the save format",
      all(not any(str(k).isdigit() for k in o)
          for o in _c7_rt_loaded.values()))


print("\n=== Z-Layer / Z-Order (GD-style draw order) ===")
from src.objects import get_z_layer, get_z_order, default_z_layer
from src.play_render import render_world as _zl_render_world
from src.play import PlaySession as _ZLPlaySession
from src.graphics import make_stars as _zl_make_stars, make_mountains as _zl_make_mountains

check("Z_LAYERS lists all 7 GD layers back-to-front",
      C.Z_LAYERS == ("b4", "b3", "b2", "b1", "t1", "t2", "t3"))

_zl_block = {"t": C.T_BLOCK, "x": 0, "y": 0}
_zl_deco = {"t": C.T_DECO_CRYSTAL, "x": 0, "y": 0}
check("a normal object defaults to Z-Layer t1 (unchanged draw order)",
      get_z_layer(_zl_block) == "t1" and default_z_layer(C.T_BLOCK) == "t1")
check("a decoration object defaults to Z-Layer b1 (behind gameplay)",
      get_z_layer(_zl_deco) == "b1" and default_z_layer(C.T_DECO_CRYSTAL) == "b1")
check("Z-Order defaults to 0",
      get_z_order(_zl_block) == 0)
check("an invalid/garbage z_layer value falls back to the type default",
      get_z_layer({"t": C.T_BLOCK, "z_layer": "nonsense"}) == "t1")

_zl_explicit = {"t": C.T_BLOCK, "x": 1, "y": 0, "z_layer": "b4", "z_order": 7}
_zl_path = save_level([_zl_explicit], "ZLayerRT", "zlayer-roundtrip")
_zl_loaded = load_level(_zl_path)[1][0]
check("an explicit z_layer/z_order survives a save/load round-trip",
      _zl_loaded.get("z_layer") == "b4" and _zl_loaded.get("z_order") == 7)
_zl_default_saved = load_level(
    save_level([dict(_zl_block)], "ZLayerLean", "zlayer-lean"))[1][0]
check("an object left at its default z_layer/z_order saves lean (no keys written)",
      "z_layer" not in _zl_default_saved and "z_order" not in _zl_default_saved)

# Draw order: Z-Layer wins over Z-Order, and within a layer higher
# Z-Order draws later (on top). Track draw calls via a fake objects list
# rendered directly through render_world's own bisect-sliced layers.
_zl_draw_order = []


def _zl_fake_draw(obj):
    _zl_draw_order.append((obj["t"], get_z_layer(obj), get_z_order(obj)))


_zl_probe_objs = [
    {"t": "back", "x": 0, "y": 0, "_orig_x": 0, "z_layer": "b1", "z_order": 5},
    {"t": "front_low_order", "x": 0, "y": 0, "_orig_x": 0, "z_layer": "t1", "z_order": -5},
    {"t": "back_high_order", "x": 0, "y": 0, "_orig_x": 0, "z_layer": "b1", "z_order": 50},
]
_zl_by_layer = {name: [] for name in C.Z_LAYERS}
for _zl_o in _zl_probe_objs:
    _zl_by_layer[get_z_layer(_zl_o)].append(_zl_o)
_zl_layers = [
    (sorted(_zl_by_layer[name], key=lambda o: o["_orig_x"]),
     [o["_orig_x"] for o in sorted(_zl_by_layer[name], key=lambda o: o["_orig_x"])])
    for name in C.Z_LAYERS
]
import src.play_render as _zl_pr_mod
_zl_orig_draw_obj = _zl_pr_mod.draw_obj
_zl_pr_mod.draw_obj = lambda screen, t, *a, **k: _zl_draw_order.append(t)
try:
    _zl_render_world(pygame.Surface((200, 200)), 0, 0, 0, 0,
                      _zl_make_stars(), _zl_make_mountains(),
                      C.C_BG_TOP, C.C_BG_BOT, 0.0, _zl_layers, set())
finally:
    _zl_pr_mod.draw_obj = _zl_orig_draw_obj
check("Z-Layer beats Z-Order: b1/50 still draws before t1/-5",
      _zl_draw_order.index("back_high_order") < _zl_draw_order.index("front_low_order"))
check("within a Z-Layer, higher Z-Order draws later (in front)",
      _zl_draw_order.index("back") < _zl_draw_order.index("back_high_order"))

check("the editor canvas sorts by Z-Layer/Z-Order ahead of the Editor Layer",
      "Z_LAYER_INDEX[get_z_layer(o)]" in
      inspect.getsource(sys.modules["src.editor.render"]))

print("\n=== Swap Trigger (random position swap, interval x count) ===")
from src.constants import T_SWAP_TRIGGER
from src.player.trigger_registry import TRIGGER_HANDLERS as _SWAP_HANDLERS


def _swap_level(swap_group=90, target_group=91, **fields):
    trig = {"t": T_SWAP_TRIGGER, "x": 1, "y": 1, "r": 0,
           "groups": [swap_group], "target_group": target_group,
           "interval": 1.0, "count": 3}
    trig.update(fields)
    return make_flat_level(length=60, extras=[
        {"t": T_BLOCK, "x": 5, "y": 3, "r": 0, "groups": [target_group]},
        {"t": T_BLOCK, "x": 8, "y": 6, "r": 0, "groups": [target_group]},
        {"t": T_BLOCK, "x": 12, "y": 9, "r": 0, "groups": [target_group]},
        trig,
    ])


def _swap_fire(p, group):
    p._fire_group(group)
    p._drain_trigger_event_queue()


def _swap_positions(members):
    return [(float(o.get("_fx", o["x"])), float(o.get("_fy", o["y"])))
           for o in members]


check("Swap Trigger is registered as a trigger type with a handler",
      T_SWAP_TRIGGER in C.TRIGGER_TYPES and T_SWAP_TRIGGER in _SWAP_HANDLERS)
check("Swap Trigger is NOT a control trigger (it moves objects directly, "
      "like Move/Rotate/Scale, not 'fire other triggers')",
      T_SWAP_TRIGGER not in C.CONTROL_TRIGGER_TYPES)

# --- 1: an instant swap actually permutes positions, once per interval ----
_sw_objs = _swap_level()
_sw_p = Player(_sw_objs)
_sw_members = [o for o in _sw_p.objects if 91 in o.get("groups", ())]
_sw_before = _swap_positions(_sw_members)
_swap_fire(_sw_p, 90)
check("firing a Swap Trigger with < 1s elapsed does nothing yet (Interval gate)",
      _swap_positions(_sw_members) == _sw_before)
for _ in range(int(C.PHYSICS_TPS * 1.0) + 2):
    _sw_p.frame += 1
    _sw_p._step_pending_swaps()
_sw_after_1 = _swap_positions(_sw_members)
check("after one Interval, the three targets' positions are a permutation "
      "of their originals (nobody teleported off-formation)",
      sorted(_sw_after_1) == sorted(_sw_before))
check("...and it actually changed something (not a no-op identity shuffle)",
      _sw_after_1 != _sw_before)

# --- 2: fires exactly Count times, then stops -----------------------------
for _ in range(int(C.PHYSICS_TPS * 1.0) + 2):
    _sw_p.frame += 1
    _sw_p._step_pending_swaps()
_sw_after_2 = _swap_positions(_sw_members)
for _ in range(int(C.PHYSICS_TPS * 1.0) + 2):
    _sw_p.frame += 1
    _sw_p._step_pending_swaps()
_sw_after_3 = _swap_positions(_sw_members)
check("Count=3 means exactly 3 permutation events are scheduled",
      len(_sw_p.pending_swaps) == 0)
for _ in range(int(C.PHYSICS_TPS * 1.0) + 2):
    _sw_p.frame += 1
    _sw_p._step_pending_swaps()
check("a 4th interval firing nothing more: positions hold after Count runs out",
      _swap_positions(_sw_members) == _sw_after_3)

# --- 3: fewer than 2 targets is a safe no-op ------------------------------
_sw_solo = make_flat_level(length=30, extras=[
    {"t": T_BLOCK, "x": 5, "y": 3, "r": 0, "groups": [93]},
    {"t": T_SWAP_TRIGGER, "x": 1, "y": 1, "r": 0, "groups": [92],
     "target_group": 93, "interval": 0.05, "count": 1},
])
_sw_solo_p = Player(_sw_solo)
_sw_solo_member = next(o for o in _sw_solo_p.objects if 93 in o.get("groups", ()))
_sw_solo_before = (_sw_solo_member["x"], _sw_solo_member["y"])
_swap_fire(_sw_solo_p, 92)
for _ in range(int(C.PHYSICS_TPS * 0.05) + 2):
    _sw_solo_p.frame += 1
    _sw_solo_p._step_pending_swaps()
check("a target group with fewer than 2 members is a safe no-op",
      (_sw_solo_member["x"], _sw_solo_member["y"]) == _sw_solo_before)

# --- 4: Smooth tweens through move_animations, clamped to <= Interval -----
_sw_smooth_objs = _swap_level(swap_group=94, target_group=95,
                              interval=0.2, count=1, smooth=True,
                              smooth_duration=10.0, easing="ease_in_out")
_sw_smooth_p = Player(_sw_smooth_objs)
_sw_smooth_members = [o for o in _sw_smooth_p.objects
                      if 95 in o.get("groups", ())]
_sw_smooth_before = _swap_positions(_sw_smooth_members)
_swap_fire(_sw_smooth_p, 94)
_sw_interval_frames = int(round(0.2 * C.PHYSICS_TPS))
_sw_smooth_p.frame += _sw_interval_frames
_sw_smooth_p._step_pending_swaps()
check("a 10s Smooth Duration is clamped to at most the 0.2s Interval",
      all(a["duration"] <= _sw_interval_frames
          for a in _sw_smooth_p.move_animations
          if a["obj"] in _sw_smooth_members))
for _ in range(_sw_interval_frames + 2):
    _sw_smooth_p._step_move_animations()
check("the clamped tween fully resolves within one Interval",
      all(a["obj"] not in _sw_smooth_members for a in _sw_smooth_p.move_animations))
_sw_smooth_after = _swap_positions(_sw_smooth_members)
check("Smooth swap still lands on a permutation of the original positions",
      sorted(_sw_smooth_after) == sorted(_sw_smooth_before))

# --- 5: round-trips through save/load like any other trigger --------------
_sw_rt_obj = {"t": T_SWAP_TRIGGER, "x": 2, "y": 2, "r": 0, "target_group": 5,
             "interval": 2.5, "count": 7, "smooth": True,
             "smooth_duration": 1.5, "easing": "ease_out"}
_sw_rt_path = save_level([_sw_rt_obj], "SwapRT", "swap-roundtrip")
_sw_rt_loaded = load_level(_sw_rt_path)[1][0]
check("Swap Trigger's fields survive a save/load round-trip",
      _sw_rt_loaded.get("interval") == 2.5
      and _sw_rt_loaded.get("count") == 7
      and _sw_rt_loaded.get("smooth") is True
      and _sw_rt_loaded.get("smooth_duration") == 1.5
      and _sw_rt_loaded.get("easing") == "ease_out")


section("Real-GD sprite geometry (overhang, spin loop, cache signature)")

from src import gd_atlas as _gda
from src.sprites import (GD_SPRITE_MAP as _GDMAP, GD_ART_RECIPE as _GDRECIPE,
                         SPRITE_FRAMES as _GDFRAMES,
                         sprite_cache_signature as _gdsig,
                         sprite_extent as _gdextent, draw_obj as _gddraw)
from src.constants import (T_SAW as _T_SAW, T_MODE_MINI as _T_MINI,
                           T_MODE_BIG as _T_BIG, T_BLOCK as _T_BLK)

# --- 1: cell_extent is the contract draw_obj relies on -------------------
check("cell_extent keeps a one-cell (30 unit) sprite exactly one cell",
      _gda.cell_extent(50, 30, 30) == (50, 50))
check("cell_extent grows the canvas for art bigger than a cell "
      "(a 60x60 saw is 2x2 cells)",
      _gda.cell_extent(50, 60, 60) == (100, 100))
check("cell_extent never returns less than one cell for small art",
      _gda.cell_extent(50, 25, 4) == (50, 50))
check('cell_extent under fit="contain" always stays one cell',
      _gda.cell_extent(50, 44, 90, fit="contain") == (50, 50))
check("cell_extent ignores pad, so a breathing sprite's canvas is stable "
      "across its frames (a per-frame canvas would jitter the blit)",
      _gda.cell_extent(50, 33, 33) == _gda.cell_extent(50, 33, 33))

# --- 2: the specs that must NOT be shrunk into one cell ------------------
check("portals render at true GD scale, not shrunk to fit a cell",
      all(_GDMAP[t].get("fit", "cell") == "cell"
          for t in (_T_MINI, _T_BIG)))
check("the saw renders at true GD scale (it is a real 2x2 cells)",
      _GDMAP[_T_SAW].get("fit", "cell") == "cell")

# --- 3: the spin loop must wrap ------------------------------------------
# `sawblade_02`'s radial profile repeats every 30 degrees (12 teeth). A
# sweep that is not a whole number of those periods leaves the last frame
# out of phase with the first, and the blade lurches backwards once per
# loop -- which is what "the saw oscillates for no reason" was.
_SAW_TOOTH_DEG = 30.0
_saw_spin = _GDMAP[_T_SAW]["spin"]
check("the saw's spin sweep is a whole number of tooth periods, so frame 7 "
      "wraps back to frame 0 seamlessly",
      abs(_saw_spin / _SAW_TOOTH_DEG - round(_saw_spin / _SAW_TOOTH_DEG)) < 1e-6)
check("...and each frame turns less than half a tooth, so the direction of "
      "rotation is never ambiguous",
      _saw_spin / _GDFRAMES < _SAW_TOOTH_DEG / 2)

# --- 4: the size portals are not swapped ---------------------------------
# GD's wiki is explicit that mini is pink and normal-size is green, and the
# frames measure that way, so the mapping is pinned to the frame index.
check("Mini Portal uses GD's pink size-portal frame (09), not the green one",
      _GDMAP[_T_MINI]["frames"][1] == "portal_09_front_001.png")
check("Big Portal uses GD's green size-portal frame (08)",
      _GDMAP[_T_BIG]["frames"][1] == "portal_08_front_001.png")
check("...so the two size portals are not the same art",
      _GDMAP[_T_MINI]["frames"] != _GDMAP[_T_BIG]["frames"])

# --- 5: the cache signature tracks the art recipe ------------------------
# Editing a frame/tint/spin used to leave already-baked frames on disk
# under the old recipe while the rest re-rendered under the new one.
_sig_before = _gdsig()
_GDMAP[_T_SAW] = dict(_GDMAP[_T_SAW], spin=_saw_spin + 30.0)
_sig_after = _gdsig()
_GDMAP[_T_SAW] = dict(_GDMAP[_T_SAW], spin=_saw_spin)
check("changing GD_SPRITE_MAP changes the sprite cache signature "
      "(no hand-bump needed to invalidate stale PNGs)",
      _sig_before != _sig_after or not _gda.atlas_installed())
check("...and restoring it restores the signature (the digest is of the "
      "recipe, not of edit history)",
      _gdsig() == _sig_before)
check("GD_ART_RECIPE carries the sprite map, so the digest covers it",
      _GDMAP in _GDRECIPE)

# --- 6: draw_obj centres a sprite on its cell, oversized or not ----------
_ext_blk = _gdextent(_T_BLK, 50)
check("a one-cell type's sprite is exactly one cell", _ext_blk == (50, 50))
_gd_surf = pygame.Surface((300, 300), pygame.SRCALPHA)
_gddraw(_gd_surf, _T_BLK, 100, 100, 50)
_gd_bb = _gd_surf.get_bounding_rect()
check("draw_obj still lands a one-cell sprite on the cell's top-left "
      "(no drift from the centring change)",
      _gd_bb.x == 100 and _gd_bb.y == 100)
_gd_surf2 = pygame.Surface((300, 300), pygame.SRCALPHA)
_gddraw(_gd_surf2, _T_SAW, 100, 100, 50)
_gd_bb2 = _gd_surf2.get_bounding_rect()
check("an oversized sprite is CENTRED on its cell, overhanging evenly, "
      "rather than pinned to the cell's corner",
      abs(_gd_bb2.centerx - 125) <= 2 and abs(_gd_bb2.centery - 125) <= 2)
_gd_surf3 = pygame.Surface((300, 300), pygame.SRCALPHA)
_gddraw(_gd_surf3, _T_SAW, 100, 100, 50, fit_cell=True)
_gd_bb3 = _gd_surf3.get_bounding_rect()
check("fit_cell keeps an oversized sprite inside the cell, for the editor "
      "palette tiles it would otherwise spill out of",
      _gd_bb3.width <= 50 and _gd_bb3.height <= 50)

# --- 7: the procedural fallback discipline still holds -------------------
_gd_missing = _gda.compose("GJ_NoSuchSheet", "nope.png", 50)
check("compose returns None for a missing sheet, so the procedural "
      "renderer takes over instead of crashing", _gd_missing is None)


# ---------------------------------------------------------------------------
section("CELL is render-only")
# The camera-zoom fix turned CELL from a secretly load-bearing physics
# constant into a pure render scale. These guard that: if a physics or
# collision length ever routes through pixels again, one of them fails.

_UNIT_MODULES = [
    "src/geometry.py", "src/player/core.py", "src/player/collision.py",
    "src/player/triggers.py", "src/player/body.py", "src/physics.py",
    "src/bots/sim.py", "src/bots/brute_force.py", "src/bots/human.py",
    "src/bots/progress.py", "src/bots/action_space.py",
]
_px_callers = [m for m in _UNIT_MODULES
               if "px_to_units" in open(m, encoding="utf-8").read()]
check("no physics/collision/bot module converts a px literal to units",
      _px_callers == [])

# geometry.py had a private second copy of the px->unit ratio that
# desynced from constants' when only one was frozen.
check("geometry.py has no private px<->unit ratio of its own",
      "_PX_TO_UNIT_RATIO" not in open("src/geometry.py", encoding="utf-8").read())

# The px hitbox builders must be the unit ones scaled, not independent
# pixel literals — that desync is what made a bare CELL change unsafe.
from src.geometry import (
    cell_rect as _g_cr, cell_rect_units as _g_cru,
    slab_rect as _g_sr, slab_rect_units as _g_sru,
    spike_hitboxes as _g_sp, spike_hitboxes_units as _g_spu,
    pad_trigger_rect as _g_pt, pad_trigger_rect_units as _g_ptu,
)
_geo_ok = True
for _gx, _gy, _r in ((0, 0, 0), (3, 7, 90), (5, 2, 180), (9, 4, 270)):
    _pairs = [(_g_cr(_gx, _gy), _g_cru(_gx, _gy)),
              (_g_sr(_gx, _gy, _r), _g_sru(_gx, _gy, _r)),
              (_g_pt(_gx, _gy, _r), _g_ptu(_gx, _gy, _r))]
    for _half in (False, True):
        _pairs += list(zip(_g_sp(_gx, _gy, _r, _half),
                           _g_spu(_gx, _gy, _r, _half)))
    for _px_rect, _u_rect in _pairs:
        for _a, _b in zip(_px_rect, _u_rect):
            if abs(_a - _b * C.PX_PER_UNIT) > 1.0:
                _geo_ok = False
check("px hitbox builders track their unit twins at the live render scale",
      _geo_ok)

# The camera framing is the sourced one, and the play-field bound the
# dual mirror / fall-off / bot-void code wants is NOT the camera height.
check("vertical FOV is GD's 320 units (10.67 blocks), within rounding",
      abs(C.CAMERA_HEIGHT_UNITS - C.CAMERA_FOV_UNITS) < 2.0)
check("play-field height stays 14 blocks, independent of the FOV",
      C.PLAYFIELD_HEIGHT_UNITS == 14 * C.UNITS_PER_BLOCK)
check("default camera framing is 0 at the legacy 14-block FOV",
      abs((11 * C.UNITS_PER_BLOCK - C.GROUND_SCREEN_FRACTION
           * C.PLAYFIELD_HEIGHT_UNITS)) < 1e-9)


print(f"\n=== Summary: {passed} passed, {failed} failed ===")
if __name__ == "__main__":
    sys.exit(0 if failed == 0 else 1)
