"""Exhaustive decision-point search — "Bot C" from the design discussion.

Replaces :mod:`.mcts` as ``HumanBot``'s alternative engine. Where A*
trades completeness for speed (a greedy heuristic weight and a frontier
cap that both discard reachable states outright) and MCTS trades it for
sampling, this engine keeps the completeness guarantee: with an
unbounded frontier and a dedup key fine enough not to alias two states
with different futures, it cannot walk past a reachable win. See the
published "One-Button Search Tradeoffs" write-up for the fuller
argument; this is Bot A (brute force + dedup + dead-branch elimination)
plus Bot C's decision-point collapse.

**Why per-frame branching is wasteful.** Under the one-button model, a
frame only has a real decision when the click could possibly do
something: a ground jump (tap modes), an orb/pad in range, or a
continuously-flown mode (ship/wave/ufo/robot) where held state always
matters. Most of a flight corridor's straightaways and the empty air
of a jump arc are the cheap case — holding vs. releasing produces the
*identical* trajectory there, so branching multiplies the search tree
for zero information. An active dash is the *expensive* case, not a
cheap one: releasing ends it immediately (core.py's ``update`` —
"Releasing the button cancels an active dash immediately"), so every
single frame of a dash is a genuine decision (release here, or don't)
and the empirical test below correctly treats it as one. A long dash
with only one or a few surviving release timings is inherently a wide
search — this engine has no shortcut for it, only completeness.

**How a "real decision" is detected — empirically, not by rule.**
Hand-coding "branch only when grounded or near an orb" risks silently
missing some trigger type (a dash-stop block, a mode portal, a mirror
body edge case) and would then just as silently prune a real solution.
Instead this engine *tests* it: mid-scan, whenever a flip is legal
(the dwell rule allows it), it simulates one frame two ways — keep
holding, and flip — from the same snapshot, and compares the resulting
physics states exactly. If they're bit-identical, nothing about the
next frame's world differs based on that click, so scanning continues
without creating a search node. Only a genuine divergence stops the
scan and creates a branch. This is correct by construction for
whatever the physics actually does, not by how well anyone modeled it.

**Configurable dedup granularity.** Two decision points are treated as
the same search state when their (bucketed) position/velocity/mode/etc.
match — see :mod:`.sim`'s ``dedup_key`` for the field list this mirrors.
Finer buckets (``pos_bucket``, ``vel_bucket``) are safer (less risk of
aliasing two states with different survivable futures into one) but
larger and slower; coarser buckets are faster but reintroduce exactly
the risk the "no bugs, can't miss anything" argument depends on not
having. There is no universally correct value — it trades against the
tightest hazard clearance in the specific level being solved.
"""

import multiprocessing as mp
import time

from ..constants import (
    CELL, HEIGHT, MODE_ROBOT, MODE_SHIP, MODE_UFO, MODE_WAVE, ORB_TYPES,
    SPEED_VALUES, T_END, T_SPEED_NORMAL, T_TELEPORT_PORTAL,
)
from .action_space import DWELL_CAP, HUMAN, replay_state
from .sim import SimPlayer, snapshot, restore

# Modes flown continuously — held state matters every frame, so the
# empirical divergence test in _macro_scan would find a divergence on
# literally every frame anyway. Skipping the test there isn't a
# shortcut that risks completeness, it's just not paying to
# rediscover something already structurally true: these modes never
# collapse, only tap modes (cube/ball/spider) do.
_FLIGHT_MODES = (MODE_SHIP, MODE_WAVE, MODE_UFO, MODE_ROBOT)

# ``passed`` entries for these types gate a real future action (a
# not-yet-fired orb/portal can still be clicked; a fired one can't) —
# see the comment in ``_key`` for why this has to be part of the dedup
# key rather than just position/velocity/mode.
_DEDUP_TRACKED_PASSED_TYPES = ORB_TYPES | {T_TELEPORT_PORTAL}

# SnapVals field indices for input_buffer / mirror_input_buffer — see
# the comment on ``_only_buffer_diff`` for why these get special
# handling in the divergence test instead of being compared exactly
# like every other field.
_BUF_IDX = 12
_MIRROR_BUF_IDX = 19
# A fresh press sets input_buffer to exactly this (core.py sets it to
# 6 on press); it counts down to 0 every frame it isn't consumed by a
# landing or an orb touch, so a difference confined to this field
# either gets consumed (a *real* divergence shows up within this many
# frames) or decays away on its own — never longer than this.
_BUFFER_LIFE_FRAMES = 6

# A held→released transition (or vice versa) is, by itself, almost
# always physically inert — nothing reads the raw held bit directly,
# only a *fresh press* (a released→held transition) can activate an
# orb, and a fresh press isn't available again until the button has
# actually been released first. That means "release now" can look
# byte-identical to "keep holding" for the empirical divergence test
# for many consecutive frames — right up until it's followed, several
# frames later, by a *second* flip (the re-press) that lines up with
# the next orb in a chain. A one-frame lookahead can never see that
# far, so without this cap, collapsing keeps auto-continuing "keep
# holding" (or "keep releasing") for the entire stretch and the
# "release, then re-press near the next orb" branch is never even
# queued — not deprioritized, never explored at all. That's a real
# completeness gap for any orb chain reached by release+re-tap with
# open air in between (a common GD pattern), not just a slow search.
# Forcing a decision point at least this often guarantees the search
# keeps re-offering "flip here" as a live, separately-queued option
# throughout a long airborne stretch, not just at the one frame a
# purely local comparison happens to flag.
_MAX_COLLAPSE_RUN = 10


# ---------------------------------------------------------------------------
# Parallel search (opt-in, off by default — see BruteForceSearch's
# ``parallel``/``workers`` params).
#
# A previous attempt at this exact idea was ripped back out of the UI
# (see bot_menu.py's module docstring: "removed when the solver moved
# to single-threaded — they caused the CPU-peg / unresponsive-ESC
# bug"). That failure mode is the whole reason this version is built
# the way it is:
#
#  - The heap/visited/nodes bookkeeping (cheap, and load-bearing for
#    correctness — dedup and priority order) stays entirely in the
#    main process. Only the expensive, side-effect-free part
#    (``_macro_scan_impl``, a pure function of a snapshot) is sent to
#    workers, in small batches (one per currently-frontier node this
#    round), so a single ``pool.map`` call is bounded by how long a
#    handful of macro-scans take (microseconds to low-milliseconds
#    each — a macro-scan is capped at ``_MAX_COLLAPSE_RUN`` frames
#    outside flight mode), not by the level or the whole time budget.
#  - The main loop still checks the deadline / cancel (``progress.
#    pump()``) once per batch, same as it always did once per node —
#    batches just replace "one node" with "one round of nodes," they
#    don't remove the check.
#  - The pool is always torn down in a ``finally`` (win, budget
#    exhaustion, cancel, or an exception from the pool itself) so a
#    failed or interrupted run can never leave worker processes
#    pegging the CPU in the background — that orphaned-process
#    scenario is the likeliest cause of the earlier bug.
#  - Pool creation and every batch's ``pool.map`` are wrapped in
#    try/except: if multiprocessing fails for any reason (sandboxing,
#    pickling, platform quirk), the search silently falls back to the
#    normal single-process loop instead of crashing the whole phase.
# ---------------------------------------------------------------------------


class _Probes:
    """The five scratch :class:`SimPlayer` instances a scan needs —
    same set :class:`BruteForceSearch` keeps on ``self``, packaged so a
    worker process can own one copy per process instead of per search.
    """

    __slots__ = ("probe", "probe_a", "probe_b", "probe_c", "probe_d")

    def __init__(self, objects, params):
        self.probe = SimPlayer([dict(o) for o in objects], params=params)
        self.probe_a = SimPlayer([dict(o) for o in objects], params=params)
        self.probe_b = SimPlayer([dict(o) for o in objects], params=params)
        self.probe_c = SimPlayer([dict(o) for o in objects], params=params)
        self.probe_d = SimPlayer([dict(o) for o in objects], params=params)
        for p in (self.probe, self.probe_a, self.probe_b,
                 self.probe_c, self.probe_d):
            p.trail = []
            p.hitbox_trace = None
            p.mirror_hitbox_trace = None


def _press_matters_impl(probe_c, probe_d, held, flipped, snap_a, snap_b):
    """Free-function twin of ``BruteForceSearch._press_matters`` — see
    that method's docstring. Returns ``(result, frames_used)`` instead
    of mutating ``self.stats`` directly, since a worker process has no
    shared stats dict to mutate."""
    restore(probe_c, snap_a)
    restore(probe_d, snap_b)
    frames_used = 0
    for _ in range(_BUFFER_LIFE_FRAMES):
        probe_c.update(held, False)
        probe_d.update(flipped, False)
        frames_used += 2
        sc, sd = snapshot(probe_c), snapshot(probe_d)
        if sc == sd:
            return False, frames_used
        if not _only_buffer_diff(sc, sd):
            return True, frames_used
    return True, frames_used


def _macro_scan_impl(probe, probe_a, probe_b, probe_c, probe_d, model,
                     void_y, dash_release_stride, start_snap, held,
                     pressed0, next_dwell, frames_left):
    """Free-function twin of ``BruteForceSearch._macro_scan`` — see that
    method's docstring for the algorithm. Takes every probe and the
    handful of config values explicitly (instead of reading ``self``)
    so it can run identically in the main process or a worker. Returns
    the same 7-tuple plus a trailing ``frames_used`` count (the frame-
    simulation cost, which the caller adds to whichever stats dict it
    actually has)."""
    restore(probe, start_snap)
    probe.update(held, pressed0)
    frames_used = 1
    seg = [(held, pressed0)]
    frames = 1
    dwell = next_dwell
    if probe.won:
        return snapshot(probe), seg, frames, True, True, held, dwell, frames_used
    if not probe.alive or probe.y > void_y:
        return None, seg, frames, False, False, held, dwell, frames_used
    if probe.mode in _FLIGHT_MODES:
        return (snapshot(probe), seg, frames, False, True, held, dwell,
               frames_used)

    min_dwell = model.min_dwell
    stride = dash_release_stride
    while frames < frames_left:
        if (stride > 1 and probe.dash_timer > 0 and frames % stride != 0):
            probe.update(held, False)
            frames_used += 1
            seg.append((held, False))
            frames += 1
            dwell = dwell + 1 if dwell < DWELL_CAP else DWELL_CAP
            if probe.won:
                return (snapshot(probe), seg, frames, True, True, held,
                       dwell, frames_used)
            if not probe.alive or probe.y > void_y:
                return None, seg, frames, False, False, held, dwell, frames_used
            continue
        if dwell >= min_dwell:
            cur_snap = snapshot(probe)
            restore(probe_a, cur_snap)
            probe_a.update(held, False)
            flipped = not held
            restore(probe_b, cur_snap)
            probe_b.update(flipped, flipped)
            frames_used += 2
            snap_a, snap_b = snapshot(probe_a), snapshot(probe_b)
            diverges = snap_a != snap_b
            if diverges and _only_buffer_diff(snap_a, snap_b):
                diverges, pm_frames = _press_matters_impl(
                    probe_c, probe_d, held, flipped, snap_a, snap_b)
                frames_used += pm_frames
            if not diverges and frames >= _MAX_COLLAPSE_RUN:
                diverges = True
            if diverges:
                return (cur_snap, seg, frames, False, True, held, dwell,
                       frames_used)
            restore(probe, snapshot(probe_a))
        else:
            probe.update(held, False)
            frames_used += 1
        seg.append((held, False))
        frames += 1
        dwell = dwell + 1 if dwell < DWELL_CAP else DWELL_CAP
        if probe.won:
            return (snapshot(probe), seg, frames, True, True, held, dwell,
                   frames_used)
        if not probe.alive or probe.y > void_y:
            return None, seg, frames, False, False, held, dwell, frames_used
        if probe.mode in _FLIGHT_MODES:
            return (snapshot(probe), seg, frames, False, True, held, dwell,
                   frames_used)
    return snapshot(probe), seg, frames, False, True, held, dwell, frames_used


# Per-worker-process globals, set once by ``_pool_init`` (via the
# ``Pool(initializer=..., initargs=...)`` mechanism — this runs once per
# child process, not per task, regardless of start method).
_WORKER = None


def _pool_init(objects, params, model, void_y, dash_release_stride):
    global _WORKER
    _WORKER = (_Probes(objects, params), model, void_y, dash_release_stride)


def _pool_scan(task):
    snap, held, pressed0, next_dwell, frames_left = task
    probes, model, void_y, stride = _WORKER
    return _macro_scan_impl(
        probes.probe, probes.probe_a, probes.probe_b, probes.probe_c,
        probes.probe_d, model, void_y, stride, snap, held, pressed0,
        next_dwell, frames_left)


def _only_buffer_diff(snap_a, snap_b):
    """True when two snapshots differ *only* in pending input-buffer
    bookkeeping (``input_buffer`` / ``mirror_input_buffer``), nothing
    else.

    A press sets the buffer so a jump still fires if it lands slightly
    before the click (standard GD jump-buffering) — real physics,
    correctly part of a full snapshot. But that means merely holding
    the button vs. not, in open air with no landing or orb anywhere
    nearby, changes this ONE bookkeeping field every single frame for
    the ~6 frames the buffer is alive, even though nothing about the
    world differs and neither value will ever be consumed. Comparing
    snapshots exactly (as the divergence test in ``_macro_scan`` did
    before this helper existed) treated that as a genuine decision on
    every such frame — for a level with any real airtime, that turns
    "decision-point collapse" into practically frame-by-frame
    branching, drowning the search's whole time/node budget in
    false decisions before it ever gets deep enough to test a real
    one (an orb it actually needs to time). This only identifies the
    narrow case; ``_press_matters`` (below) still requires it to
    resolve — consumed or decayed — within a bounded window before
    treating it as safe to collapse.
    """
    va, vb = snap_a[0], snap_b[0]
    for i, (a, b) in enumerate(zip(va, vb)):
        if i in (_BUF_IDX, _MIRROR_BUF_IDX):
            continue
        if a != b:
            return False
    return snap_a[1:] == snap_b[1:]


class _Node:
    __slots__ = ("parent", "segment", "depth", "dist")

    def __init__(self, parent, segment, depth, dist):
        self.parent = parent
        self.segment = segment      # [(held, pressed), ...] for this edge
        self.depth = depth          # cumulative frame count at this node
        # Cumulative |dx| along this node's whole path from the root —
        # unlike raw x, this can't go *down* when a branch teleports
        # backward, so it's the honest "how far has this candidate
        # actually traveled" number even through a backward warp.
        self.dist = dist


class BruteForceSearch:
    """Exhaustive, dedup'd, decision-point-collapsed search.

    Same ``(inputs, won) = run()`` contract as :class:`~.toggle_search.
    ToggleSearch` / the old MCTS engine, so it drops into
    :class:`~.human.HumanBot` the same way.

    Parameters
    ----------
    pos_bucket, vel_bucket : float
        Dedup granularity in pixels / (pixels-per-frame). Smaller is a
        stronger completeness guarantee, larger is faster. See module
        docstring.
    max_nodes : int or None
        Safety valve on total nodes expanded — without it a pathological
        level's frontier can exhaust memory before exhausting time.
        Hitting this cap means "budget exhausted," not "unsolvable";
        unlike ``FRONTIER_CAP`` in A*, it never discards a reachable
        state early, it just stops accepting new work.
    verbose : bool
        Print periodic stage/progress lines to stdout — for driving
        this from a script rather than the in-game progress bar.
    """

    def __init__(self, objects, params=None, *, model=HUMAN,
                seed_inputs=None, time_budget=None, max_frames=20000,
                pos_bucket=1.0, vel_bucket=0.5, max_nodes=3_000_000,
                heuristic_weight=2.0, progress=None, verbose=False,
                dash_release_stride=1, parallel=False, workers=None):
        self.objects = [dict(o) for o in objects]
        self.params = params
        self.model = model
        self.time_budget = float(time_budget) if time_budget else None
        self.max_frames = int(max_frames)
        self.pos_bucket = float(pos_bucket)
        self.vel_bucket = float(vel_bucket)
        self.max_nodes = max_nodes
        # Releasing ends an active dash immediately (core.py), so every
        # single frame of a dash is a genuine, correctly-detected
        # decision — "release right here" is never bit-identical to
        # "keep holding." For a long dash with only a narrow surviving
        # release window, that's a real per-frame branching factor with
        # no dedup/heuristic shortcut (tuning neither materially helped
        # in practice — every release timing lands at a genuinely
        # different, non-aliasing state). This trades completeness for
        # speed on purpose: only test releasing on every Nth eligible
        # frame during an active dash, at the risk of stepping past the
        # one exact frame a level actually needs. 1 = untouched
        # (test every frame, no completeness given up here).
        self.dash_release_stride = max(1, int(dash_release_stride))
        # Biases which frontier node is explored *first* — it never
        # discards one, so it costs nothing against the completeness
        # guarantee (that only depends on nothing being dropped early,
        # which dedup/pruning-on-death already handle). Without it the
        # search is pure breadth-by-frame-count, which is fine where
        # decisions are sparse (tap modes) but explores continuous
        # flight sections almost undirected, since those never
        # decision-collapse in the first place.
        self.heuristic_weight = float(heuristic_weight)
        self.progress = progress
        self.verbose = verbose
        # Opt-in, off by default — see the "Parallel search" block
        # above this class for why, and its cost/risk tradeoffs. Never
        # part of the completeness guarantee (it changes nothing about
        # which states get explored or discarded, only how many worker
        # processes do the macro-scan work), so leaving it off costs
        # nothing but wall-clock speed.
        self.parallel = bool(parallel)
        self.workers = int(workers) if workers else max(
            1, (mp.cpu_count() or 4) - 1)

        end_xs = [o["x"] * CELL for o in self.objects if o.get("t") == T_END]
        self.end_x = max(end_xs) if end_xs else 0.0
        self._build_speed_segments()

        # The physics has no bottomless-pit death — a branch that falls
        # past every last piece of placed geometry just keeps falling
        # forever, alive, with x still ticking up from forward move
        # speed. Nothing in that branch's future can ever touch level
        # geometry again, but the search has no way to know that from
        # ``alive`` alone, so it looks like *the best result found* —
        # its x only ever grows, it never resolves — and both starves
        # the frontier (the branch never dies, so it never stops being
        # re-expanded) and, worse, becomes the reported "best" result
        # over branches that are actually making real, recoverable
        # progress (e.g. threading a tight teleport-portal gap), whose
        # x dips or grows slower while they do it. Treat "well below
        # the lowest object in the level" as a search-only dead end —
        # this never touches the shared Player physics a real playtest
        # uses, it only stops the *search* from chasing a branch that
        # provably cannot come back.
        max_y = max((o["y"] for o in self.objects), default=0)
        # Generous on purpose: this only has to catch a fall that's
        # unrecoverable, not merely long, and a real drop (into a low
        # platform, through a tight gap) can easily run several screen
        # heights before it's done. Too tight and it kills legitimate
        # branches before they ever reach what they were falling toward
        # (see the fix's history — an early, tighter margin did exactly
        # that, cutting a fall off 300px past the lowest platform,
        # before it had even reached a portal sitting well within that
        # gap). HEIGHT is the play area height in px.
        self._void_y = max_y * CELL + HEIGHT * 4

        self._probe = SimPlayer([dict(o) for o in self.objects], params=params)
        self._probe_a = SimPlayer([dict(o) for o in self.objects], params=params)
        self._probe_b = SimPlayer([dict(o) for o in self.objects], params=params)
        # Scratch probes for _press_matters' bounded lookahead — kept
        # separate from _probe_a/_probe_b so that lookahead can advance
        # several frames without disturbing the one-frame state the
        # caller's own frame/segment bookkeeping expects those two to
        # still be at when it reads them back.
        self._probe_c = SimPlayer([dict(o) for o in self.objects], params=params)
        self._probe_d = SimPlayer([dict(o) for o in self.objects], params=params)
        for p in (self._probe, self._probe_a, self._probe_b,
                 self._probe_c, self._probe_d):
            p.trail = []
            p.hitbox_trace = None
            p.mirror_hitbox_trace = None

        self.seed_inputs = list(seed_inputs) if seed_inputs else []

        self.stats = {
            "frames_simulated": 0,
            "decisions_expanded": 0,
            "macro_edges": 0,
            "dead_branches": 0,
            "dedup_hits": 0,
            "frontier_peak": 0,
            "deepest_x": -1.0,
            "dist_covered": 0.0,
            "stage": "idle",
            "wall_time": 0.0,
        }
        self._last_report = 0.0

    # ---- heuristic (ordering only — never discards a node) -------------
    # Identical construction to HumanBot._build_speed_segments/_h: a
    # piecewise 1/speed integral over the level's speed-portal segments.
    # Ported rather than shared because it's small, stable, and this
    # module deliberately doesn't import from human.py (human.py imports
    # this one).

    def _build_speed_segments(self):
        base_speed = (self.params.base_move_speed if self.params is not None
                      else SPEED_VALUES[T_SPEED_NORMAL])
        events = sorted(
            ((int(o["x"]) * CELL, SPEED_VALUES[o["t"]])
             for o in self.objects if o.get("t") in SPEED_VALUES),
            key=lambda e: e[0])
        seg_starts = [0]
        seg_speeds = [base_speed]
        for ex, esp in events:
            if ex <= seg_starts[-1]:
                seg_speeds[-1] = esp
                continue
            if abs(esp - seg_speeds[-1]) < 1e-9:
                continue
            seg_starts.append(ex)
            seg_speeds.append(esp)
        seg_ends = seg_starts[1:] + [self.end_x]
        cumul = [0.0] * len(seg_starts)
        running = 0.0
        for i in range(len(seg_starts) - 1, -1, -1):
            cumul[i] = running
            seg_len = max(0, seg_ends[i] - seg_starts[i])
            if seg_speeds[i] > 0:
                running += seg_len / seg_speeds[i]

        n_cells = self.end_x // CELL + 2 if self.end_x > 0 else 1
        recips = [0.0] * n_cells
        seg_end_px = [self.end_x] * n_cells
        cumul_after = [0.0] * n_cells
        for cell in range(n_cells):
            x_px = cell * CELL
            i = 0
            for j, ss in enumerate(seg_starts):
                if ss <= x_px:
                    i = j
                else:
                    break
            if seg_speeds[i] > 0:
                recips[cell] = 1.0 / seg_speeds[i]
            seg_end_px[cell] = seg_ends[i]
            cumul_after[cell] = cumul[i]
        self._h_recips = recips
        self._h_seg_end = seg_end_px
        self._h_cumul = cumul_after
        self._h_n_cells = n_cells

    def _h(self, x):
        if self.end_x <= 0 or x >= self.end_x:
            return 0.0
        cell = int(x) // CELL
        if cell >= self._h_n_cells:
            return 0.0
        if cell < 0:
            cell = 0
        recip = self._h_recips[cell]
        if recip <= 0.0:
            return 0.0
        return max(0, self._h_seg_end[cell] - x) * recip + self._h_cumul[cell]

    # ---- dedup key, configurable granularity ---------------------------

    def _key(self, snap, held, dwell):
        vals = snap[0]
        pb = self.pos_bucket
        vb = self.vel_bucket
        min_dwell = self.model.min_dwell
        anims_t = snap[2] if len(snap) > 2 else ()
        obj_pos_t = snap[3] if len(snap) > 3 else ()
        anim_key = (tuple(sorted((a[0], a[5]) for a in anims_t))
                   if anims_t else ())
        obj_pos_key = (tuple(sorted((e[0], round(e[1] / pb),
                                     round(e[2] / pb)) for e in obj_pos_t))
                      if obj_pos_t else ())
        # Which one-shot orbs/portals this branch has already fired —
        # position/velocity/mode alone can't tell two states apart when
        # one of them can still click a teleport orb (or any other
        # single-use orb) and the other can't. This matters most for a
        # *backward* teleport: its destination often lands right back
        # in a position/velocity bucket the search already visited at
        # much shallower depth early on, before the orb was ever used.
        # Without this, that earlier, orb-still-live visit "wins" the
        # dedup (it's shallower) and the entire branch that actually
        # used the orb — and can now reach places the un-teleported
        # branch never could — gets silently discarded as no-better-
        # than-already-seen. Only orb/portal types are tracked (not the
        # full ``passed`` set) so this stays cheap and doesn't reintroduce
        # a key so fine every state looks unique.
        passed = snap[1] if len(snap) > 1 else ()
        passed_orbs = (tuple(sorted(
            k for k in passed if k[0] in _DEDUP_TRACKED_PASSED_TYPES))
            if passed else ())
        base = (
            round(vals.x / pb), round(vals.y / pb), round(vals.vy / vb),
            vals.grav, vals.mode, vals.on_ground,
            1 if vals.input_buffer > 0 else 0,
            1 if vals.dash_timer > 0 else 0,
            1 if vals.teleport_cooldown > 0 else 0,
            int(vals.size), round(vals.move_speed, 4),
            anim_key, obj_pos_key, passed_orbs,
            held, dwell if dwell < min_dwell else min_dwell,
        )
        mirror = snap[4] if len(snap) > 4 else None
        if mirror is None:
            return base + (None,)
        if len(mirror) == 6:
            my, mvy, mgrav, mog, _mang, malive = mirror
            mmode, msize = 0, 0
        elif len(mirror) == 8:
            my, mvy, mgrav, mog, _mang, malive, mmode, msize = mirror
        elif len(mirror) == 9:
            my, mvy, mgrav, mog, _mang, malive, mmode, msize, _mfb = mirror
        else:
            (my, mvy, mgrav, mog, _mang, malive, mmode, msize,
             _mfb, _mtd) = mirror
        return base + (round(my / pb), round(mvy / vb), mgrav,
                       1 if mog else 0, 1 if malive else 0, mmode, msize)

    # ---- bounded resolution of a buffer-only divergence -----------------

    def _press_matters(self, held, flipped, snap_a, snap_b):
        """See ``_press_matters_impl`` — this just supplies this
        instance's own scratch probes and folds the frame cost into
        ``self.stats`` (the free function can't, since a worker
        process calling it has no shared stats dict)."""
        result, frames_used = _press_matters_impl(
            self._probe_c, self._probe_d, held, flipped, snap_a, snap_b)
        self.stats["frames_simulated"] += frames_used
        return result

    # ---- macro-step scan -------------------------------------------------

    def _macro_scan(self, start_snap, held, pressed0, next_dwell, frames_left):
        """See ``_macro_scan_impl`` — this just supplies this instance's
        own probes/config and folds the frame cost into ``self.stats``.

        Returns ``(end_snap, segment, frame_count, won, alive, end_held,
        end_dwell)``. ``end_snap`` is ``None`` when the branch died — the
        caller discards it (dead-branch elimination).
        """
        *result, frames_used = _macro_scan_impl(
            self._probe, self._probe_a, self._probe_b, self._probe_c,
            self._probe_d, self.model, self._void_y, self.dash_release_stride,
            start_snap, held, pressed0, next_dwell, frames_left)
        self.stats["frames_simulated"] += frames_used
        return tuple(result)

    # ---- path reconstruction -------------------------------------------

    def _reconstruct(self, nodes, terminal_id):
        """Walk parent pointers back to the root, prepending each edge's
        segment — root included, since the root's own "segment" is the
        seed prefix it was built from (see ``run()``), not empty."""
        out = []
        idx = terminal_id
        while idx is not None:
            node = nodes[idx]
            out = list(node.segment) + out
            idx = node.parent
        return out

    # ---- reporting -------------------------------------------------------

    def _report(self, force=False):
        now = time.monotonic()
        if not force and now - self._last_report < 0.5:
            return
        self._last_report = now
        s = self.stats
        text = (f"brute-force · {s['stage']} · x={s['deepest_x']:.0f} · "
               f"dist={s['dist_covered']:.0f} · "
               f"decisions={s['decisions_expanded']} · "
               f"frames={s['frames_simulated']} · "
               f"dead={s['dead_branches']} dedup={s['dedup_hits']} · "
               f"frontier={s['frontier_peak']}")
        if self.progress is not None:
            self.progress.paint(text)
        if self.verbose:
            print(text)

    # ---- driver ------------------------------------------------------

    def run(self):
        """Search until a win, budget exhaustion, or the frontier empties.

        Returns ``(inputs, won)``. ``won=False`` with a nonempty
        ``inputs`` means the deepest alive state reached — never a
        state past the frame budget or a dead one.
        """
        import heapq

        started = time.monotonic()
        self.stats["stage"] = "seeding"
        deadline = (started + self.time_budget
                   if self.time_budget else None)

        root_player = SimPlayer([dict(o) for o in self.objects],
                                params=self.params)
        root_player.trail = []
        seed_used = []
        root_dist = 0.0
        if self.seed_inputs:
            prev_seed_x = root_player.x
            for held, pressed in self.model.sanitize(self.seed_inputs):
                if not root_player.alive or root_player.won:
                    break
                root_player.update(held, pressed)
                seed_used.append((held, pressed))
                root_dist += abs(root_player.x - prev_seed_x)
                prev_seed_x = root_player.x
            if root_player.won:
                return seed_used, True
            if not root_player.alive:
                return [], False

        root_snap = snapshot(root_player)
        prev_held, root_dwell = replay_state(seed_used)

        nodes = [_Node(None, seed_used, len(seed_used), root_dist)]
        key0 = self._key(root_snap, prev_held, root_dwell)
        visited = {key0: len(seed_used)}
        counter = 1
        root_depth = len(seed_used)
        root_f = root_depth + self.heuristic_weight * self._h(root_snap[0].x)
        # Heap entries are (f, counter, depth, snap, node_id, held, dwell):
        # `f` orders exploration (heuristic-biased, ties on `counter`),
        # `depth` is the true frame count dedup/max_frames compare
        # against. Splitting them out matters — before this, the pure
        # frame-depth priority meant flight-mode sections (which never
        # decision-collapse) explored almost breadth-first instead of
        # toward the goal, since nothing pulled the frontier forward.
        heap = [(root_f, 0, root_depth, root_snap, 0, prev_held, root_dwell)]

        best_node = 0
        best_x = root_snap[0].x
        stats = self.stats
        stats["stage"] = "searching"
        stats["deepest_x"] = best_x
        stats["dist_covered"] = root_dist
        if self.progress is not None:
            self.progress.note_x(best_x)

        # See the "Parallel search" block above the class for the design
        # and why it's shaped this way. ``pool`` stays ``None`` (pure
        # serial, unchanged from before this feature existed) unless
        # ``self.parallel`` is set AND pool creation actually succeeds;
        # a failure anywhere — creation or a later batch — permanently
        # falls back to serial for the rest of this run instead of
        # losing the search. The ``finally`` below is the one thing
        # that's non-negotiable: whatever ends this run (win, either
        # budget, cancel, or an exception), the pool never outlives it.
        pool = None
        if self.parallel:
            try:
                ctx = mp.get_context("spawn")
                pool = ctx.Pool(
                    processes=self.workers, initializer=_pool_init,
                    initargs=(self.objects, self.params, self.model,
                             self._void_y, self.dash_release_stride))
            except Exception:
                pool = None
                self.parallel = False

        try:
            while heap:
                if (self.max_nodes is not None
                        and stats["decisions_expanded"] >= self.max_nodes):
                    stats["stage"] = "node budget exhausted"
                    break
                if deadline is not None and time.monotonic() > deadline:
                    stats["stage"] = "time budget exhausted"
                    break
                if self.progress is not None and self.progress.pump():
                    stats["stage"] = "cancelled"
                    break

                if pool is not None:
                    # Pop a whole round of frontier nodes at once — one
                    # per worker, roughly — instead of one, so a single
                    # pool.map() call has enough independent work to
                    # actually use every process. The budget/cancel
                    # checks above still run once per round, same
                    # cadence (once per unit of expansion) as the
                    # serial path had once per node.
                    batch = []
                    batch_size = max(1, self.workers)
                    while heap and len(batch) < batch_size:
                        (_f, _c, depth, snap, node_id, prev_h,
                         dwell) = heapq.heappop(heap)
                        key = self._key(snap, prev_h, dwell)
                        if visited.get(key, depth) < depth:
                            continue
                        if depth >= self.max_frames:
                            continue
                        stats["decisions_expanded"] += 1
                        batch.append((depth, snap, node_id, prev_h, dwell))
                    if not batch:
                        continue

                    tasks = []
                    owner = []
                    for bi, (depth, snap, node_id, prev_h,
                            dwell) in enumerate(batch):
                        frames_left = self.max_frames - depth
                        for held, pressed, next_dwell in self.model.actions(
                                prev_h, dwell):
                            tasks.append(
                                (snap, held, pressed, next_dwell, frames_left))
                            owner.append(bi)

                    try:
                        results = pool.map(_pool_scan, tasks)
                    except Exception:
                        # The parallel path itself broke (pickling,
                        # a crashed worker, platform quirk) — tear it
                        # down, fall back to serial for the rest of
                        # this run, and put this batch's nodes back on
                        # the heap so nothing already popped is lost.
                        try:
                            pool.terminate()
                            pool.join()
                        except Exception:
                            pass
                        pool = None
                        self.parallel = False
                        for (depth, snap, node_id, prev_h,
                                dwell) in batch:
                            f = depth + self.heuristic_weight * self._h(
                                snap[0].x)
                            heapq.heappush(
                                heap, (f, counter, depth, snap, node_id,
                                      prev_h, dwell))
                            counter += 1
                            stats["decisions_expanded"] -= 1
                        continue

                    for bi, res in zip(owner, results):
                        depth, snap, node_id, prev_h, dwell = batch[bi]
                        (end_snap, seg, nframes, won, alive, end_held,
                         end_dwell, frames_used) = res
                        stats["frames_simulated"] += frames_used
                        stats["macro_edges"] += 1

                        start_x = snap[0].x
                        end_x = end_snap[0].x if end_snap else None
                        new_dist = nodes[node_id].dist + (
                            abs(end_x - start_x) if end_x is not None else 0.0)

                        if won:
                            nodes.append(_Node(node_id, seg, depth + nframes,
                                               new_dist))
                            stats["dist_covered"] = max(
                                stats["dist_covered"], new_dist)
                            return (self._reconstruct(nodes, len(nodes) - 1),
                                   True)

                        if not alive:
                            stats["dead_branches"] += 1
                            continue

                        new_depth = depth + nframes
                        child_key = self._key(end_snap, end_held, end_dwell)
                        prev_g = visited.get(child_key)
                        if prev_g is not None and prev_g <= new_depth:
                            stats["dedup_hits"] += 1
                            continue
                        visited[child_key] = new_depth

                        nodes.append(_Node(node_id, seg, new_depth, new_dist))
                        nid = len(nodes) - 1
                        if new_dist > stats["dist_covered"]:
                            stats["dist_covered"] = new_dist
                        if end_x > best_x:
                            best_x = end_x
                            best_node = nid
                            stats["deepest_x"] = best_x
                            if self.progress is not None:
                                self.progress.note_x(best_x)

                        f = new_depth + self.heuristic_weight * self._h(end_x)
                        heapq.heappush(
                            heap, (f, counter, new_depth, end_snap, nid,
                                  end_held, end_dwell))
                        counter += 1

                    stats["frontier_peak"] = max(
                        stats["frontier_peak"], len(heap))
                    self._report()
                    continue

                (_f, _c, depth, snap, node_id, prev_h,
                 dwell) = heapq.heappop(heap)
                key = self._key(snap, prev_h, dwell)
                if visited.get(key, depth) < depth:
                    continue
                if depth >= self.max_frames:
                    continue

                stats["decisions_expanded"] += 1
                frames_left = self.max_frames - depth

                for held, pressed, next_dwell in self.model.actions(prev_h, dwell):
                    (end_snap, seg, nframes, won, alive, end_held,
                     end_dwell) = self._macro_scan(
                        snap, held, pressed, next_dwell, frames_left)
                    stats["macro_edges"] += 1

                    start_x = snap[0].x
                    end_x = end_snap[0].x if end_snap else None
                    new_dist = nodes[node_id].dist + (
                        abs(end_x - start_x) if end_x is not None else 0.0)

                    if won:
                        nodes.append(_Node(node_id, seg, depth + nframes,
                                           new_dist))
                        stats["dist_covered"] = max(stats["dist_covered"], new_dist)
                        return self._reconstruct(nodes, len(nodes) - 1), True

                    if not alive:
                        stats["dead_branches"] += 1
                        continue

                    new_depth = depth + nframes
                    child_key = self._key(end_snap, end_held, end_dwell)
                    prev_g = visited.get(child_key)
                    if prev_g is not None and prev_g <= new_depth:
                        stats["dedup_hits"] += 1
                        continue
                    visited[child_key] = new_depth

                    nodes.append(_Node(node_id, seg, new_depth, new_dist))
                    nid = len(nodes) - 1
                    # Tracked independently of best_x/best_node: a backward
                    # teleport makes x itself an unreliable "how far along
                    # is it" signal (a branch can legitimately need to go
                    # backward before it can go further forward than
                    # anything tried yet), but total distance travelled
                    # never goes down, so it keeps climbing through exactly
                    # the case that makes x look like it regressed.
                    if new_dist > stats["dist_covered"]:
                        stats["dist_covered"] = new_dist
                    if end_x > best_x:
                        best_x = end_x
                        best_node = nid
                        stats["deepest_x"] = best_x
                        if self.progress is not None:
                            self.progress.note_x(best_x)

                    f = new_depth + self.heuristic_weight * self._h(end_x)
                    heapq.heappush(
                        heap, (f, counter, new_depth, end_snap, nid,
                              end_held, end_dwell))
                    counter += 1

                stats["frontier_peak"] = max(stats["frontier_peak"], len(heap))
                self._report()

            stats["wall_time"] = time.monotonic() - started
            if stats["stage"] == "searching":
                stats["stage"] = "frontier exhausted"
            self._report(force=True)
            return self._reconstruct(nodes, best_node), False
        finally:
            if pool is not None:
                try:
                    pool.terminate()
                    pool.join()
                except Exception:
                    pass
