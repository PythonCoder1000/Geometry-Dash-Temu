#!/usr/bin/env python3
"""Self-contained test suite for Geometry Dash Temu.

Uses pygame in headless mode (SDL_VIDEODRIVER=dummy) so it can run without
a display. Imports from the individual modules that actually exist, not
from a monolithic main.
"""

import os
import sys
import tempfile

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"

import pygame
pygame.init()
pygame.display.set_mode((1, 1))

import constants as C
from constants import (
    CELL, FPS, PLAYER_SIZE, GRAVITY, JUMP_FORCE, SPEED_VALUES,
    T_BLOCK, T_SLAB, T_SPIKE, T_HALF_SPIKE, T_SAW,
    T_ORB, T_DASH_ORB, T_TELEPORT_ORB, T_BLACK_ORB, T_BLUE_ORB, T_GREEN_ORB,
    T_PAD, T_BLUE_PAD, T_GRAV, T_END, T_START, T_COIN, T_CHECKPOINT,
    T_MODE_CUBE, T_MODE_SHIP, T_MODE_BALL, T_MODE_WAVE, T_MODE_UFO, T_MODE_SPIDER,
    T_SPEED_SLOW, T_SPEED_NORMAL, T_SPEED_FAST, T_SPEED_FASTER,
    MODE_CUBE, MODE_SHIP, MODE_BALL, MODE_WAVE, MODE_UFO, MODE_SPIDER,
    SOLID_TYPES, HAZARD_TYPES, ORB_TYPES, PAD_TYPES,
    DIFFICULTIES, LEVEL_FORMAT_VERSION, LEVELS_DIR,
)
from graphics import (
    normalize_rotation, cell_rect, slab_rect, spike_hitboxes, saw_hitbox,
    pad_trigger_rect, clamp, lerp, lerp_col, lighter, darker,
)
from levels import (
    save_level, load_level, load_level_full, update_meta, list_levels,
    list_level_summaries, normalize_object, next_group_id, next_teleport_link,
    next_object_id, next_coin_id, ensure_dirs, _default_meta,
    save_autosave, load_autosave, has_autosave, clear_autosave,
    get_group_id, AUTOSAVE_FILENAME,
)
from player import Player


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
    objs = [{"t": T_START, "x": 3, "y": 9, "r": 0}]
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
check("SPEED_VALUES has 4 entries",
      len(SPEED_VALUES) == 4 and T_SPEED_NORMAL in SPEED_VALUES)
check("DIFFICULTIES list has Demon",
      "Demon" in DIFFICULTIES and "Easy" in DIFFICULTIES)
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
import levels as _levels_mod
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
check("normalize_object rounds r to 90", ob["r"] == 90)
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
check("fresh levels dir is empty by default",
      list_levels() == [])


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
      abs(p.x - (3 * CELL + (CELL - PLAYER_SIZE) / 2)) < 1)

# Step a few frames: player should walk forward
x0 = p.x
for _ in range(10):
    p.update(False, False)
check("Player moves forward on flat ground", p.x > x0)
check("Player stays alive on flat ground", p.alive)

# Jump on cube mode
p2 = Player(make_flat_level())
# Ensure on_ground after a step
for _ in range(3):
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
for _ in range(30):
    p.update(False, False)
check("Coin collected after walking over it", 1 in p.coins_collected)

# Checkpoint request flag
objs = make_flat_level(extras=[{"t": T_CHECKPOINT, "x": 4, "y": 9, "r": 0}])
p = Player(objs)
p.practice_mode = True
for _ in range(30):
    p.update(False, False)
check("Checkpoint flag set after crossing", p._checkpoint_request is True)


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
for _ in range(20):
    p.update(False, False)
check("Player stands on slabs", p.alive and p.on_ground)


# ---------------------------------------------------------------------------
# Green orb / blue pad
# ---------------------------------------------------------------------------
section("Green orb + Blue pad")
objs = make_flat_level(extras=[{"t": T_GREEN_ORB, "x": 6, "y": 8, "r": 0}])
p = Player(objs)
# Walk, then activate with a press while near the orb
for _ in range(22):
    p.update(False, False)
p.update(True, True)
check("Green orb activation flips vy", p.vy < 0)


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
# Walk into spider portal (gx=8 from spawn gx=3, ~5 cells @ 5px/frame)
for _ in range(80):
    p.update(False, False)
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
from levels import _safe_filename as _sf
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
from editor import _clone_objects

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
import snippets as _snip_mod
from snippets import (
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
import thumbnails as _thumbs_mod
from thumbnails import (
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
import prefs as _prefs_mod
import settings as _settings_mod

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
    check("FPS_CAP_OPTIONS contains 60", 60 in _settings_mod.FPS_CAP_OPTIONS)
    check("FPS_CAP_OPTIONS contains 0 (uncapped)",
          0 in _settings_mod.FPS_CAP_OPTIONS)

    # Defaults returned when nothing persisted yet.
    check("get_fps_cap default", _settings_mod.get_fps_cap() == FPS)
    check("get_fullscreen default False",
          _settings_mod.get_fullscreen() is False)

    # set/get round-trip.
    _settings_mod.set_fps_cap(120)
    check("fps_cap persists 120", _settings_mod.get_fps_cap() == 120)
    _settings_mod.set_fps_cap(0)
    check("fps_cap=0 (uncapped) round-trips",
          _settings_mod.get_fps_cap() == 0)

    # Defensive coercion — corrupt prefs fall back to default.
    _prefs_mod.set("fps_cap", "garbage")
    check("garbage fps_cap falls back to default",
          _settings_mod.get_fps_cap() == FPS)
    _prefs_mod.set("fps_cap", -10)
    check("negative fps_cap falls back to default",
          _settings_mod.get_fps_cap() == FPS)
    _prefs_mod.set("fps_cap", 99999)
    check("absurdly large fps_cap clamped to 1000",
          _settings_mod.get_fps_cap() == 1000)
    _prefs_mod.set("fps_cap", 60)  # restore baseline

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

    # cycle_fps_cap walks through the option list.
    _settings_mod.set_fps_cap(60)
    expected = _settings_mod.FPS_CAP_OPTIONS[
        (_settings_mod.FPS_CAP_OPTIONS.index(60) + 1) %
        len(_settings_mod.FPS_CAP_OPTIONS)
    ]
    actual = _settings_mod.cycle_fps_cap()
    check("cycle_fps_cap advances through options", actual == expected)

    # fps_cap_label maps 0 → "Unlimited".
    check("fps_cap_label(0) == 'Unlimited'",
          _settings_mod.fps_cap_label(0) == "Unlimited")
    check("fps_cap_label(60) == '60'",
          _settings_mod.fps_cap_label(60) == "60")

    # reset_to_defaults wipes all keys back to baseline.
    _settings_mod.set_fps_cap(144)
    _settings_mod.set_fullscreen(True)
    _settings_mod.set_music_vol(0.1)
    _settings_mod.reset_to_defaults()
    check("reset returns fps_cap to default",
          _settings_mod.get_fps_cap() == _settings_mod.DEFAULTS["fps_cap"])
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
import gamepad as _gp_mod

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
check("back_pressed returns bool",
      isinstance(_gp_mod.back_pressed(), bool))
check("pause_pressed returns bool",
      isinstance(_gp_mod.pause_pressed(), bool))

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
import settings as _cust_settings
import prefs as _cust_prefs
from constants import PLAYER_COLORS, PLAYER_ICONS
from graphics import draw_cube_icon_glyph as _glyph

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
import menus as _cust_menus
check("run_customize is callable",
      callable(getattr(_cust_menus, "run_customize", None)))
check("_draw_player_swatch helper exists",
      callable(getattr(_cust_menus, "_draw_player_swatch", None)))


# ---------------------------------------------------------------------------
# Hint mode — autobot ghost overlay available from play.py
# ---------------------------------------------------------------------------
section("Hint mode")

import play as _play_mod
# run_play is the entry point that owns the hint toggle. We don't exercise
# the full loop here (it requires a real event pump and would block), but
# the symbol must exist and be callable.
check("play.run_play exists",
      callable(getattr(_play_mod, "run_play", None)))

# The autobot itself must be importable and solve a trivial flat level.
# This is the same path the H key triggers, so a passing test gives us
# reasonable confidence the hint button won't crash on a real level.
from autobot import AutoBot as _HintBot
flat = make_flat_level(length=20)
# Strip any runtime-only keys the test level doesn't have.
_hb = _HintBot([dict(o) for o in flat])
check("AutoBot accepts plain object list", _hb is not None)

# solve() returns (waypoints, mirror_waypoints, inputs, won). Pass a tiny
# max_frames so the test stays quick even if the solver has to explore a bit.
_hwp, _hmwp, _hin, _hwon = _hb.solve(screen=None, clock=None, max_frames=600)
check("AutoBot.solve returns a waypoint list",
      isinstance(_hwp, list))
check("AutoBot.solve returns a mirror waypoint list",
      isinstance(_hmwp, list))
check("AutoBot.solve returns an input list",
      isinstance(_hin, list))
check("AutoBot waypoints have 2-tuples",
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

# AutoBot end-to-end on trivial flat ground: the solver should actually
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
check("AutoBot solves trivial flat level", _twon is True)
check("AutoBot trivial solution has inputs", len(_tin) > 0)
check("AutoBot trivial waypoints reach end x",
      _twp and max(p[0] for p in _twp) >= 30 * C.CELL)

# AutoBot with an obstacle: a single spike in the middle. The solver must
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
check("AutoBot solves single-spike level", _owon is True)
# When the bot solves with a jump, at least one frame must have pressed=True
if _owon:
    check("Spike solution contains a jump press",
          any(pressed for _, pressed in _oin))


# ---------------------------------------------------------------------------
# Dual mode — mirror inherits player state, autobot snapshots it
# ---------------------------------------------------------------------------
section("Dual mode")
from constants import T_MODE_DUAL, HEIGHT as _DH
from autobot import _snap as _ab_snap, _restore as _ab_restore, _build_obj_index, _SimPlayer

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
for _ in range(60):
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
for _ in range(60):
    _sp.update(False, False)
    if _sp.mirror is not None:
        break
check("SimPlayer mirror present after dual portal", _sp.mirror is not None)
if _sp.mirror is not None:
    snap_mirror = _sp.mirror
    expected_y = snap_mirror["y"]
    expected_grav = snap_mirror["grav"]
    snap = _ab_snap(_sp)
    # snap layout: (vals, passed, anims, obj_pos, mirror, mirror_passed)
    check("Snapshot is 6-tuple (mirror + mirror_passed slots present)",
          isinstance(snap, tuple) and len(snap) == 6)
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
from constants import T_MODE_SOLO, T_COIN, T_BG_TRIGGER
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
for _ in range(400):
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
for _ in range(180):
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
from constants import (
    T_MODE_WAVE, T_MODE_BALL, T_MODE_MINI, T_MODE_BIG,
    MODE_CUBE as _MC, MODE_WAVE as _MW, MODE_BALL as _MB,
    MINI_PLAYER_SIZE as _MINI, PLAYER_SIZE as _BIG,
)

# 7a. Wave portal in MIRROR's path — main stays cube, mirror becomes wave.
_mirror_mode_objs = _make_dual_corridor(60, extras=[
    {"t": T_MODE_DUAL, "x": 8, "y": 9, "r": 0},
    {"t": T_MODE_WAVE, "x": 14, "y": 3, "r": 0},
])
_mp = Player(_mirror_mode_objs)
for _ in range(180):
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
for _ in range(180):
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
for _ in range(180):
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
for _ in range(180):
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
from constants import T_ORB
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
for _frame in range(220):
    # Click only when the player is roughly under both orbs (cell x≈18).
    do_click = (not _clicked) and 17 * CELL <= _op.x <= 18.5 * CELL
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


# ---------------------------------------------------------------------------
# Editor test-mode music wiring
# Test mode (editor's "Test" button) should play the level's assigned music
# with the same lifecycle as a real play session: start at 0, restart on
# death/R, stop on exit. Bot/playback runs intentionally stay silent because
# their variable-speed simulation wouldn't sync to audio.
# ---------------------------------------------------------------------------
section("Editor test-mode music wiring")
import inspect
import play as _play_mod
import editor as _editor_mod

_play_src = inspect.getsource(_play_mod.run_play)
# The four music gates inside run_play used to read `level_music and not
# editor_test`, which silenced editor-test runs even when the editor passed
# a track. They should now gate on level_music alone.
check("run_play music gates dropped 'not editor_test'",
      "level_music and not editor_test" not in _play_src)
# A grep-style sanity check that the music start/stop calls still exist —
# we don't want a "fix" that just removes music handling entirely.
check("run_play still starts level music",
      "music.play_file(level_music)" in _play_src)
check("run_play still stops level music on death",
      "music.stop()" in _play_src)
check("run_play still fades music on win",
      "music.fadeout(" in _play_src)

# The editor's Test button should pass level_music through. Bot/playback
# calls below it should NOT pass level_music — they're intentionally silent.
_editor_src = inspect.getsource(_editor_mod.run_editor)
# The Test-button block looks like: `if do_test:\n   run_play(...editor_test=True, level_music=level_music)`
# We do a lenient substring check for the keyword arg in the do_test block.
_test_block_start = _editor_src.find("if do_test:")
_test_block_end = _editor_src.find("if do_bot:", _test_block_start)
check("editor.py has a do_test block",
      _test_block_start >= 0 and _test_block_end > _test_block_start)
if _test_block_start >= 0 and _test_block_end > _test_block_start:
    _test_block = _editor_src[_test_block_start:_test_block_end]
    check("editor's Test button passes level_music to run_play",
          "level_music=level_music" in _test_block)
    check("editor's Test button still flags editor_test=True",
          "editor_test=True" in _test_block)


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
import bot_menu as _bm

# 1. _run_solver signature: returns (wp, mwp, inputs, status, err).
_solver_sig = inspect.signature(_bm._run_solver)
check("_run_solver signature unchanged (screen, clock, objects)",
      list(_solver_sig.parameters) == ["screen", "clock", "objects"])

# 2. Crash surfacing: a deliberately malformed level should NOT vanish into
#    a silent "failed". The exception's class name needs to land in `err`.
_garbage = [{"no_t_field": True}]
_wp, _mwp, _inp, _status, _err = _bm._run_solver(None, None, _garbage)
check("_run_solver returns 5-tuple (wp, mwp, inputs, status, err)",
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
check("Clear cached path button is rendered with disabled flag",
      "clear_disabled" in _bm_src and "disabled=clear_disabled" in _bm_src)

# 4. Disabled clicks should explain WHY they didn't act, not silently drop.
check("Disabled hint-overlay click sets an info_msg",
      "Solve a path first" in _bm_src)
check("Disabled replay click explains the empty-inputs case",
      "Run Find Path first" in _bm_src)
check("Disabled clear click acknowledges the no-op",
      "Nothing to clear" in _bm_src)

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
import player as _player_mod
from constants import MODE_WAVE as _MW, MODE_SHIP as _MSh, MODE_BALL as _MB

_draw_src = inspect.getsource(_player_mod.Player.draw)
check("Player.draw branches on MODE_WAVE/MODE_SHIP for line trail",
      "MODE_WAVE, MODE_SHIP" in _draw_src and "len(self.trail)" in _draw_src)
check("Line trail uses pygame.draw.line with thickness",
      "pygame.draw.line" in _draw_src and "trail_thickness" in _draw_src)
check("Line trail uses a single SRCALPHA surface for alpha blending",
      "SRCALPHA" in _draw_src and "line_surf" in _draw_src)

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
from player import Player as _PB
from constants import T_BLOCK as _TB, T_START as _TS, T_END as _TE
_objs = ([{"t": _TS, "x": 1, "y": 9, "r": 0}]
         + [{"t": _TB, "x": x, "y": 10, "r": 0} for x in range(40)]
         + [{"t": _TE, "x": 38, "y": 9, "r": 0}])
_p = _PB(_objs)
_p.mode = _MW
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


# ---------------------------------------------------------------------------
# Bot replay music wiring
# All three editor "Bot" sub-paths (exact / waypoint / file-playback) and
# the bot-menu Replay callback should pass level_music through, matching
# the Test button's behaviour. Used to be silent on the explicit theory
# that variable-speed runs would desync — but at default speed they're
# fine, and the user wants the audio context.
# ---------------------------------------------------------------------------
section("Bot replay music wiring")
_editor_src2 = inspect.getsource(_editor_mod.run_editor)
_bot_block_start = _editor_src2.find("if do_bot:")
_bot_block_end = _editor_src2.find("if do_bot_menu:", _bot_block_start)
check("editor.py has a do_bot block separate from do_bot_menu",
      _bot_block_start >= 0 and _bot_block_end > _bot_block_start)
if _bot_block_start >= 0 and _bot_block_end > _bot_block_start:
    _bot_block = _editor_src2[_bot_block_start:_bot_block_end]
    # All three sub-paths (Bot Exact, Bot, Playback) should pass level_music.
    _music_kw_count = _bot_block.count("level_music=level_music")
    check("All three do_bot sub-paths pass level_music to run_play",
          _music_kw_count >= 3)

# Bot menu Replay callback should also pass level_music.
_replay_block_start = _editor_src2.find("def _replay_in_editor")
# End-marker: any line that starts with `result = run_bot_menu` (the
# indent level of run_bot_menu's call site varies as the editor grows,
# so don't pin it to a specific number of leading spaces).
_replay_block_end = _editor_src2.find("result = run_bot_menu",
                                       _replay_block_start)
check("editor's _replay_in_editor closure exists",
      _replay_block_start >= 0 and _replay_block_end > _replay_block_start)
if _replay_block_start >= 0 and _replay_block_end > _replay_block_start:
    _replay_block = _editor_src2[_replay_block_start:_replay_block_end]
    check("Bot menu Replay callback passes level_music",
          "level_music=level_music" in _replay_block)


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

_play_src2 = inspect.getsource(_play_mod.run_play)
check("run_play appends per-frame (x, y, size) when out_hitboxes is set",
      "current_hitboxes.append" in _play_src2
      and "player.size" in _play_src2)
check("run_play commits the buffer on _full_reset",
      "out_hitboxes[:] = current_hitboxes" in _play_src2)
check("run_play also commits the buffer on _stop_music_and_return",
      _play_src2.count("out_hitboxes[:] = current_hitboxes") >= 2)

# Editor wiring: state, H toggle, run_play hand-off, draw overlay.
check("editor declares last_run_hitboxes state",
      "last_run_hitboxes = []" in _editor_src2)
check("editor declares show_hitboxes default False",
      "show_hitboxes = False" in _editor_src2)
check("H key toggles show_hitboxes",
      "ev.key == pygame.K_h" in _editor_src2
      and "show_hitboxes = not show_hitboxes" in _editor_src2)
check("editor passes out_hitboxes=last_run_hitboxes to run_play",
      _editor_src2.count("out_hitboxes=last_run_hitboxes") >= 4)
check("editor clears last_run_hitboxes before each run",
      "last_run_hitboxes.clear()" in _editor_src2)
check("editor draws the hitbox overlay layer when toggle is on",
      "show_hitboxes and last_run_hitboxes" in _editor_src2
      and "hb_layer" in _editor_src2)

# Behavioural smoke: simulate a short run with out_hitboxes wired up.
# We don't actually call run_play (it owns the event loop) — instead
# verify the recording shape by inspecting that the buffer contract
# documented in the docstring is consistent with the source markers.
_doc = _play_mod.run_play.__doc__ or ""
check("run_play docstring documents out_hitboxes contract",
      "out_hitboxes" in _doc and "(x, y, size)" in _doc)


print(f"\n=== Summary: {passed} passed, {failed} failed ===")
sys.exit(0 if failed == 0 else 1)
