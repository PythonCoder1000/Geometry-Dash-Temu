# Testing

From the repository root:

```sh
.venv/bin/python -m unittest test_physics
.venv/bin/python test_game.py
```

`test_physics.py` checks measured arcs, short taps, mode behavior, collisions,
and agreement between gameplay, simulation, settings and editor previews.
`test_game.py` runs the broader headless game/editor/bot regressions.

`tests/fixtures/legacy_bot_inputs.txt` is a replay parsing fixture, not a
golden level completion. Bot saves loaded through the menu are replayed
against the current level and physics before their result is trusted.

Benchmarks are optional tuning tools, not correctness gates:

```sh
.venv/bin/python scripts/bench_bots.py --out reports/benchmarks/bench_results.json
```

Benchmark reports are local generated files. Level-specific physics metadata
is loaded for each benchmark so it measures the same game the player plays.
