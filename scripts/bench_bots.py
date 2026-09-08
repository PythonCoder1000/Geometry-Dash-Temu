#!/usr/bin/env python3
"""Benchmark HumanBot's search engines (A*+toggle vs brute force) across
levels and time budgets.

Not a correctness test (see test_game.py for that) — a tuning tool. Run
it before/after changing the brute-force engine's dedup bucket size,
or A*'s knobs, to see whether the change actually helped, on real
content rather than the tiny synthetic levels test_game.py uses.

Usage:
    python scripts/bench_bots.py
    python scripts/bench_bots.py --levels levels/nine_circles.json
    python scripts/bench_bots.py --budgets 10 20 --engines brute_force
    python scripts/bench_bots.py --engines brute_force --pos-bucket 0.5 --vel-bucket 0.25
    python scripts/bench_bots.py --out reports/benchmarks/bench_results.json

For each (level, budget, engine) combination it runs HumanBot.solve()
once with that time_budget and reports:
  - whether it won, and how many wall-clock seconds that took
  - the deepest x reached (win or not)
  - one-button violations in the returned inputs (should always be 0 —
    a nonzero count here is a solver bug, not a tuning signal)
  - for brute_force: whether the frontier was exhausted (a completeness
    proof — "no reachable win past this x", not just "didn't find one")
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.levels import load_level_full
from src.physics import PhysicsParams
from src.constants import px_to_units
from src.bots import HumanBot
from src.bots.action_space import HUMAN

DEFAULT_LEVELS = [
    "levels/levels_of_hell.json",
    "levels/nine_circles.json",
    "levels/death_corridor_2.0.json",
]

ENGINES = ("astar", "brute_force")


def run_one(objects, engine, time_budget, max_frames, pos_bucket, vel_bucket, params=None):
    bot = HumanBot([dict(o) for o in objects], params=params)
    bot.USE_BRUTE_FORCE = (engine == "brute_force")
    bot.BRUTE_FORCE_POS_BUCKET = px_to_units(pos_bucket)
    bot.BRUTE_FORCE_VEL_BUCKET = px_to_units(vel_bucket)
    t0 = time.monotonic()
    wp, _mwp, inputs, won = bot.solve(
        screen=None, clock=None, max_frames=max_frames, time_budget=time_budget)
    elapsed = time.monotonic() - t0
    deepest_x = max((p[0] for p in wp), default=-1.0) if wp else -1.0
    violations = len(HUMAN.violations(inputs)) if inputs else 0
    return {
        "won": bool(won),
        "elapsed": round(elapsed, 2),
        "deepest_x": round(deepest_x, 1),
        "frames": len(inputs) if inputs else 0,
        "violations": violations,
        "frame_perfect": bool(bot.used_frame_perfect),
    }


def _cell(r):
    status = ("WIN@%.1fs" % r["elapsed"]) if r["won"] else "--"
    flag = " FP" if r["frame_perfect"] else ""
    bad = " BAD-INPUT" if r["violations"] else ""
    return f"{status:>9} x={r['deepest_x']:>7.0f}{flag}{bad}"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--levels", nargs="*", default=DEFAULT_LEVELS,
                     help="level JSON paths to benchmark against")
    ap.add_argument("--budgets", nargs="*", type=float, default=[10, 20, 30, 40],
                     help="time_budget values in seconds")
    ap.add_argument("--max-frames", type=int, default=20000)
    ap.add_argument("--engines", nargs="*", default=list(ENGINES),
                     choices=list(ENGINES))
    ap.add_argument("--pos-bucket", type=float, default=1.0,
                     help="brute_force dedup position bucket, px")
    ap.add_argument("--vel-bucket", type=float, default=0.5,
                     help="brute_force dedup velocity bucket, px/frame")
    ap.add_argument("--out", default=None,
                     help="write raw per-run results as JSON to this path")
    args = ap.parse_args()

    results = []
    for level_path in args.levels:
        if not os.path.exists(level_path):
            print(f"skip (missing): {level_path}")
            continue
        meta, objects = load_level_full(level_path)
        params = PhysicsParams.from_meta(meta)
        print(f"\n=== {os.path.basename(level_path)} "
              f"({len(objects)} objects) ===")
        header = f"{'budget':>7} | " + " | ".join(
            f"{e:>28}" for e in args.engines)
        print(header)
        print("-" * len(header))
        for budget in args.budgets:
            row = [f"{budget:>7g}"]
            for engine in args.engines:
                r = run_one(objects, engine, budget, args.max_frames,
                           args.pos_bucket, args.vel_bucket, params=params)
                results.append({"level": level_path, "engine": engine,
                                "budget": budget, **r})
                row.append(f"{_cell(r):>28}")
            print(" | ".join(row))

    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
