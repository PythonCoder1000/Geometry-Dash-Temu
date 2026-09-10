"""Behavioral physics contracts. Run: .venv/bin/python -m unittest test_physics."""
import os
import unittest
from unittest.mock import patch
from copy import deepcopy

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from src import constants as C
from src.player import Player
from src.physics import PhysicsParams


def flat():
    p = Player([{"t": C.T_START, "x": 3, "y": 9}]
               + [{"t": C.T_BLOCK, "x": x, "y": 10} for x in range(150)])
    for _ in range(20):
        p.update(False, False)
    return p


class PhysicsContracts(unittest.TestCase):
    def test_tick_rate_and_predictor_horizon_agree(self):
        from src import settings, play, jump_predictor
        self.assertEqual(settings.get_tps(), C.PHYSICS_TPS)
        self.assertEqual(play.PHYSICS_RATE, C.PHYSICS_TPS)
        self.assertEqual(jump_predictor._probe_max_frames(), 3 * C.PHYSICS_TPS)

    def test_render_rate_does_not_change_simulation(self):
        from src.play import PlaySession
        poses = []
        for fps in (60, 120, 144, 240):
            p = flat()
            session = PlaySession.__new__(PlaySession)
            session.sim_accum = 0
            session.last_dt_sec = 1 / fps
            session._step_scale = lambda: 1
            session._tick = lambda: p.update(True, False)
            for _ in range(fps):
                session._advance_physics()
            poses.append((p.frame, p.x, p.y, p.vy))
        self.assertTrue(all(pose == poses[0] for pose in poses))

    def test_predictor_uses_overrides_and_preserves_editor_world(self):
        from src.jump_predictor import predict, detect_speed
        objects = [{"t": C.T_BLOCK, "x": x, "y": 10} for x in range(30)]
        probe = {"t": C.T_JUMP_PREDICTOR, "x": 3, "y": 9}
        objects.append(probe)
        before = deepcopy(objects)
        params = PhysicsParams(base_move_speed=0.5)
        result = predict(objects, probe, params)
        # samples are px; base_move_speed is units/tick.
        self.assertAlmostEqual(result["samples"][1][0] - result["samples"][0][0],
                               0.5 * C.PX_PER_UNIT)
        self.assertEqual(objects, before)
        # Both detect_speed branches must answer in the SAME unit system
        # (units/tick) — they used to disagree by PX_PER_UNIT, so a probe
        # with no speed portal ahead of it previewed at 0.6x run speed.
        self.assertEqual(detect_speed(objects, 3, params), 0.5)
        objects.append({"t": C.T_SPEED_FAST, "x": 2, "y": 9})
        self.assertEqual(detect_speed(objects, 3, params),
                         C.SPEED_VALUES_UT[C.T_SPEED_FAST])
        no_portal = [o for o in objects if o.get("t") != C.T_SPEED_FAST]
        self.assertAlmostEqual(detect_speed(no_portal, 3),
                               C.SPEED_VALUES_UT[C.T_SPEED_NORMAL])

    def test_predictor_nudge_does_not_invent_ground_contact(self):
        from src.jump_predictor import predict
        p = flat()
        result = predict(p.objects, {"t": C.T_JUMP_PREDICTOR, "x": 3, "y": 9, "dy": -5})
        self.assertGreater(result["samples"][1][1], result["samples"][0][1])

    def test_music_mapping_respects_slow_custom_speed(self):
        from src.play import real_time_to_x, x_at_time
        objects = [{"t": C.T_SPEED_FAST, "x": 3, "y": 9},
                   {"t": C.T_TIME_WARP, "x": 6, "y": 9, "factor": 0.5}]
        for target in (50, 200, 400):
            elapsed = real_time_to_x(objects, target, 0.25)
            self.assertAlmostEqual(x_at_time(objects, elapsed, 0.25), target)
        self.assertAlmostEqual(real_time_to_x([], 60, 0.25), 1)

    def test_malformed_physics_falls_back_without_poisoning_simulation(self):
        for raw in (None, [], "invalid", 5):
            self.assertEqual(PhysicsParams.from_meta(raw), PhysicsParams())
            self.assertEqual(PhysicsParams.from_dict(raw), PhysicsParams())
        for key, value in (("gravity", float("nan")), ("gravity", -1),
                           ("dash_time", float("inf")), ("base_move_speed", 0),
                           ("jump_force", 5), ("wave_angle", 90)):
            self.assertEqual(PhysicsParams.from_dict({key: value}), PhysicsParams())
        self.assertEqual(PhysicsParams.from_dict({"gravity": 0}).gravity, 0)

    def test_bot_flight_estimates_use_actual_mini_physics(self):
        from src.bots.loophole import PathFollowController
        from src.player.body import MirrorBody
        p = flat()
        p.params = PhysicsParams(wave_angle=30)
        # Mini wave is 6 units, not 18 — §3.2 sizes the body per (mode, mini).
        p.mirror = MirrorBody(mode=C.MODE_WAVE,
                              size=C.body_size_units(C.MODE_WAVE, True),
                              grav=-1, y=200)
        controller = PathFollowController([(0, 200), (1000, 200)])
        controller._hazard_cells = {(99, 99)}
        state = p.mirror.to_dict()
        with patch.object(controller, "path_crosses_hazard", return_value=False) as estimate:
            controller.mirror_crosses_hazard(p, True, True, 10)
        self.assertAlmostEqual(
            estimate.call_args.args[3],
            p.params.wave_velocity(p.move_speed, -1, True, True) * C.PX_PER_UNIT)
        self.assertEqual(p.mirror.to_dict(), state)

    def test_mirror_sweeps_horizontal_hazards(self):
        from src.player.body import MirrorBody
        p = Player([{"t": C.T_SPIKE, "x": 4, "y": 4}])
        # Sweep the mirror 4 blocks left, from 6 blocks in, across the
        # spike sitting in cell (4, 4).
        p.x = 6 * C.UNITS_PER_BLOCK
        p.mirror = MirrorBody(y=4 * C.UNITS_PER_BLOCK, grav=1, mode=C.MODE_SHIP)
        p._step_mirror(False, False, 4 * C.UNITS_PER_BLOCK)
        self.assertFalse(p.mirror.alive)
        self.assertEqual(p.x, 6 * C.UNITS_PER_BLOCK)

    def test_cached_win_invalidated_by_physics_or_geometry(self):
        from src import bot_menu
        objects = [{"t": C.T_BLOCK, "x": 1, "y": 10}]
        bot_menu.clear_last_solve()
        try:
            bot_menu._sync_solve_context(objects, PhysicsParams())
            bot_menu._record_result([(0, 0), (100, 0)], [], [(False, False)], "ok")
            self.assertFalse(bot_menu._sync_solve_context(objects, PhysicsParams()))
            self.assertTrue(bot_menu.get_last_inputs())
            self.assertTrue(bot_menu._sync_solve_context(objects, PhysicsParams(gravity=0.1)))
            self.assertFalse(bot_menu.get_last_inputs())
            objects[0]["y"] = 9
            self.assertTrue(bot_menu._sync_solve_context(objects, PhysicsParams(gravity=0.1)))
        finally:
            bot_menu.clear_last_solve()

    def test_malformed_saved_runs_do_not_crash_menu(self):
        from src import bot_saves
        from unittest.mock import mock_open
        for content in ('[]', '{"inputs":[[1]]}', '{"waypoints":[["bad",0]]}',
                        '{"start_key":[1]}', '{"inputs":null}'):
            with patch.object(bot_saves, "_ensure_dir"), patch("builtins.open", mock_open(read_data=content)):
                self.assertIsNone(bot_saves.load_run("fixture", "broken"))

    def test_run_speed_in_blocks_per_second(self):
        p = flat()
        x = p.x
        for _ in range(240):
            p.update(False, False)
        self.assertAlmostEqual((p.x - x) / C.UNITS_PER_BLOCK, 10.386)
        self.assertTrue(p.alive and p.on_ground)

    def test_cube_arc_height_duration_and_distance(self):
        p = flat()
        x, y = p.x, p.y
        p.update(True, True)
        apex = p.y
        ticks = 1
        while not p.on_ground and ticks < 240:
            p.update(False, False)
            apex = min(apex, p.y)
            ticks += 1
        self.assertTrue(p.alive and p.on_ground)
        self.assertTrue(2.30 < (y - apex) / C.UNITS_PER_BLOCK < 2.40)
        self.assertTrue(0.42 < ticks / 240 < 0.44)
        self.assertTrue(4.35 < (p.x - x) / C.UNITS_PER_BLOCK < 4.55)

    def test_short_tap_is_not_lost(self):
        p = flat()
        y = p.y
        p.update(False, True)
        self.assertLess(p.y, y)
        self.assertFalse(p.on_ground)

    def test_held_cube_relaunches(self):
        p = flat()
        launches = 0
        for tick in range(330):
            was_ground = p.on_ground
            p.update(True, tick == 0)
            launches += was_ground and not p.on_ground
        self.assertGreaterEqual(launches, 3)
        self.assertTrue(p.alive)

    def test_mini_cube_has_lower_arc(self):
        heights = []
        for mini in (False, True):
            p = flat()
            if mini:
                p._set_size(C.MINI_PLAYER_SIZE_UNITS)
            y = p.y
            p.update(True, True)
            while p.vy < 0:
                p.update(False, False)
            heights.append(y - p.y)
        self.assertTrue(0.60 < heights[1] / heights[0] < 0.67)

    def test_wave_reversal_and_mini_slope(self):
        # §3.2 sizes the wave body at 10 units normal / 6 mini, so "mini"
        # is that row's mini value, not the box modes' 18.
        for size, slope in ((C.body_size_units(C.MODE_WAVE, False), 1),
                            (C.body_size_units(C.MODE_WAVE, True), 2)):
            for speed in C.SPEED_VALUES.values():
                for grav in (1, -1):
                    p = flat()
                    p.mode, p.size, p.grav = C.MODE_WAVE, size, grav
                    p.y, p.move_speed = 250, speed
                    for held in (True, False, True, False):
                        x, y = p.x, p.y
                        p.update(held, held)
                        self.assertAlmostEqual((p.y - y) / (p.x - x),
                                               slope * grav * (-1 if held else 1))
                        self.assertTrue(p.alive)

    def test_custom_wave_angle_affects_path(self):
        p = Player([], params=PhysicsParams(wave_angle=30))
        p.mode = C.MODE_WAVE
        p.update(True, True)
        self.assertAlmostEqual(-p.vy / p.move_speed, 3 ** -0.5)

    def test_robot_hold_is_bounded_and_release_cannot_reignite(self):
        p = flat()
        p.set_mode(C.MODE_ROBOT)
        y = p.y
        for tick in range(80):
            p.update(True, tick == 0)
        self.assertEqual(p.flight_budget, 0)
        self.assertTrue(3 < (y - p.y) / C.UNITS_PER_BLOCK < 4)
        p = flat()
        p.set_mode(C.MODE_ROBOT)
        p.update(True, True)
        p.update(False, False)
        vy = p.vy
        p.update(True, True)
        self.assertGreater(p.vy, vy)

    def test_no_magnetic_landing(self):
        p = flat()
        p.y -= 5
        p.on_ground = False
        p.vy = 0
        p._check_ground_adjacency(p)
        self.assertFalse(p.on_ground)
        p.update(False, False)
        self.assertFalse(p.on_ground)
        self.assertLess(p.y + p.size, 10 * C.UNITS_PER_BLOCK)

    def test_ball_press_held_before_landing_flips_once(self):
        p = flat()
        p.mode = C.MODE_BALL
        p.y -= 10
        p.on_ground = False
        for tick in range(60):
            p.update(True, tick == 0)
            if p.grav == -1:
                break
        self.assertEqual(p.grav, -1)
        self.assertEqual(p.input_buffer, 0)

    def test_ship_and_swing_are_symmetric_under_gravity(self):
        for mode in (C.MODE_SHIP, C.MODE_SWING):
            normal, inverted = flat(), flat()
            for p, grav in ((normal, 1), (inverted, -1)):
                p.mode, p.grav, p.y, p.on_ground = mode, grav, 250, False
            for tick in range(30):
                held = tick < 15
                normal.update(held, tick == 0)
                inverted.update(held, tick == 0)
                self.assertAlmostEqual(normal.vy, -inverted.vy)
                self.assertAlmostEqual(normal.y - 250, 250 - inverted.y)

    def test_landing_at_outer_feet_in_both_gravities(self):
        for grav in (1, -1):
            p = Player([{"t": C.T_BLOCK, "x": 3, "y": 5}])
            p.x, p.grav, p.on_ground = 3 * C.UNITS_PER_BLOCK, grav, False
            p.y = (5 * C.UNITS_PER_BLOCK - p.size + 0.1 if grav == 1
                   else 6 * C.UNITS_PER_BLOCK - 0.1)
            p.vy = grav
            p._resolve_y_collision(p, grav * 0.2)
            self.assertTrue(p.on_ground)
            self.assertEqual(p.y, 5 * C.UNITS_PER_BLOCK - p.size if grav == 1
                              else 6 * C.UNITS_PER_BLOCK)

    def test_cube_ceiling_lethal_ship_ceiling_slides(self):
        for mode, alive in ((C.MODE_CUBE, False), (C.MODE_ROBOT, False),
                            (C.MODE_SHIP, True), (C.MODE_BALL, True)):
            p = Player([{"t": C.T_BLOCK, "x": 3, "y": 5}])
            p.x, p.y, p.mode = 3 * C.UNITS_PER_BLOCK, 6 * C.UNITS_PER_BLOCK - 0.1, mode
            p._resolve_y_collision(p, -0.2)
            self.assertEqual(p.alive, alive)

    def test_wave_floor_lethal_unless_d_block(self):
        for exempt in (False, True):
            p = flat()
            p.mode = C.MODE_WAVE
            if exempt:
                p.objects.append({"t": C.T_WAVE_BLOCK, "x": 4, "y": 9})
                p._rebuild_spatial_index()
            p.update(False, False)
            self.assertEqual(p.alive, exempt)

    def test_ufo_hold_does_not_repeat_flaps_after_landing(self):
        p = flat()
        p.mode = C.MODE_UFO
        p.update(True, True)
        for _ in range(300):
            p.update(True, False)
        self.assertTrue(p.alive and p.on_ground)
        self.assertEqual(p.vy, 0)
        p.update(False, False)
        p.update(True, True)
        self.assertFalse(p.on_ground)
        self.assertLess(p.vy, 0)

    def test_ufo_flap_is_not_cut_to_fall_speed_next_tick(self):
        p = flat()
        p.mode = C.MODE_UFO
        p.update(True, True)
        p.update(False, False)
        self.assertLess(p.vy, -C.MAX_FALL_UFO_UT)

    def test_wave_slope_contact_is_lethal(self):
        p = Player([{"t": C.T_SLOPE, "x": 3, "y": 5, "r": 0}])
        p.x, p.y, p.mode = 3 * C.UNITS_PER_BLOCK, 5 * C.UNITS_PER_BLOCK, C.MODE_WAVE
        p._resolve_slopes(p)
        self.assertFalse(p.alive)

    def test_identical_inputs_produce_identical_replay(self):
        from src.bots.sim import SimPlayer
        p = flat()
        sim = SimPlayer([dict(o) for o in p.objects])
        p.reset()
        for tick in range(500):
            held = tick % 140 < 40
            pressed = tick % 140 == 0
            p.update(held, pressed)
            sim.update(held, pressed)
            self.assertEqual((p.x, p.y, p.vy, p.alive),
                             (sim.x, sim.y, sim.vy, sim.alive))

    def test_player_body_is_one_block_and_yields_the_bible_solid_box(self):
        """Physics bible §3.2: the box gamemodes' main ("red") hitbox is
        30 units — one full block — and 18 in mini. HITBOX_SOLID_FRACTION's
        entries are literally bible_blue/bible_red (9/30, 10/18, ...), so
        they only produce the bible's blue box when the body size IS the
        bible's red box. Both halves are asserted together because that is
        the coupling that silently broke: a 44 px / 26.4 unit body made the
        solid box 7.92 instead of 9, and made every jump read 12% high and
        the world scroll 14% fast *relative to the player*."""
        from src.player.collision import solid_hitbox_fraction
        self.assertEqual(C.PLAYER_SIZE_UNITS, C.UNITS_PER_BLOCK)
        self.assertEqual(C.MINI_PLAYER_SIZE_UNITS, C.UNITS_PER_BLOCK * 0.6)
        # (mode, bible blue normal, bible blue mini)
        for mode, blue, blue_mini in ((C.MODE_CUBE, 9, 10), (C.MODE_SHIP, 9, 10),
                                      (C.MODE_BALL, 9, 10), (C.MODE_UFO, 9, 10),
                                      (C.MODE_ROBOT, 9, 10), (C.MODE_SWING, 9, 10)):
            size = C.PLAYER_SIZE_UNITS
            self.assertAlmostEqual(size * solid_hitbox_fraction(mode, size), blue)
            mini = C.MINI_PLAYER_SIZE_UNITS
            self.assertAlmostEqual(mini * solid_hitbox_fraction(mode, mini), blue_mini)
        p = flat()
        self.assertAlmostEqual(p.solid_hitbox().width, 9.0)

    def test_every_gamemode_reproduces_the_bible_3_2_hitbox_table(self):
        """§3.2 in full: the red (body) box AND the blue (solid) box it
        yields, for all eight modes, normal and mini. Wave's 10/3 and
        Spider's 27.5/9 are the rows a single PLAYER_SIZE_UNITS got wrong
        — HITBOX_SOLID_FRACTION's entries are bible_blue/bible_red, so
        they only produce the bible's blue box when the body size is that
        row's red box."""
        from src.player.collision import solid_hitbox_fraction
        # mode: (red, blue, mini_red, mini_blue)
        table = {
            C.MODE_CUBE:   (30, 9, 18, 10), C.MODE_SHIP:  (30, 9, 18, 10),
            C.MODE_BALL:   (30, 9, 18, 10), C.MODE_UFO:   (30, 9, 18, 10),
            C.MODE_ROBOT:  (30, 9, 18, 10), C.MODE_SWING: (30, 9, 18, 10),
            C.MODE_WAVE:   (10, 3, 6, 3),
            C.MODE_SPIDER: (27.5, 9, 16.5, 10),
        }
        self.assertEqual(set(table), set(C.ALL_MODES))
        for mode, (red, blue, mini_red, mini_blue) in table.items():
            for size, want_red, want_blue in ((False, red, blue),
                                              (True, mini_red, mini_blue)):
                got = C.body_size_units(mode, size)
                self.assertAlmostEqual(got, want_red, msg=f"{mode} red")
                self.assertAlmostEqual(got * solid_hitbox_fraction(mode, got),
                                       want_blue, msg=f"{mode} blue")
                self.assertIs(C.is_mini_size(mode, got), size, msg=f"{mode} mini")

    def test_hazard_box_is_the_whole_body_with_no_extra_inset(self):
        """§3.4 debunks player-side forgiveness: GD's forgiveness lives in
        the hazard shapes (this engine's spike danger box is 9 x 19.2 in a
        30-unit cell), not in a shrunken player box. The player box used
        against hazards used to be inset 3.6 units per side, which also
        made an axis-aligned spike more forgiving than the same spike
        rotated one degree (the rotated path never had the inset)."""
        from src.geometry import spike_hitboxes_units
        (_sx, _sy, sw, _sh), = spike_hitboxes_units(10, 10, {"t": C.T_SPIKE,
                                                             "x": 10, "y": 10})
        cell = 10 * C.UNITS_PER_BLOCK
        body = C.PLAYER_SIZE_UNITS
        # Overlap of a full-width body with the spike's danger box.
        expected = sw + body
        lo = hi = None
        objs = [{"t": C.T_BLOCK, "x": x, "y": 11} for x in range(40)]
        objs.append({"t": C.T_SPIKE, "x": 10, "y": 10})
        x = cell - body - 5.0
        while x < cell + sw + body + 5.0:
            p = Player([dict(o) for o in objs])
            p.x, p.y, p.vy, p.move_speed = x, cell, 0.0, 0.0
            p.update(False, False)
            if not p.alive:
                lo = x if lo is None else lo
                hi = x
            x += 0.05
        self.assertAlmostEqual(hi - lo, expected, delta=0.15)

    def test_cube_jump_matches_the_bible_velocity_table(self):
        """§1.3/§1.4: 11.18G at 1x, and the tick-ordering quirk — a fresh
        click eats one gravity tick (11.18 - 0.216) while a held/buffered
        one gets the full force."""
        vel = C.PHYSICS_TPS / 60.0          # units/tick -> bible "Vels"
        for speed_type, expected in ((C.T_SPEED_SLOW, 10.62),
                                     (C.T_SPEED_NORMAL, 11.18),
                                     (C.T_SPEED_FAST, 11.42),
                                     (C.T_SPEED_FASTER, 11.23),
                                     (C.T_SPEED_FASTEST, 11.23)):
            held = flat()
            held.set_speed(speed_type)
            held.update(True, False)
            self.assertAlmostEqual(-held.vy * vel, expected, places=3)
            fresh = flat()
            fresh.set_speed(speed_type)
            fresh.update(True, True)
            self.assertAlmostEqual(-fresh.vy * vel, expected - 0.216, places=3)


if __name__ == "__main__":
    unittest.main()
