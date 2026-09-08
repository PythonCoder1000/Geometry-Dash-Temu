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
        self.assertAlmostEqual(result["samples"][1][0] - result["samples"][0][0], 0.5)
        self.assertEqual(objects, before)
        self.assertEqual(detect_speed(objects, 3, params), 0.5)
        objects.append({"t": C.T_SPEED_FAST, "x": 2, "y": 9})
        self.assertEqual(detect_speed(objects, 3, params), C.SPEED_VALUES[C.T_SPEED_FAST])

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
        p.mirror = MirrorBody(mode=C.MODE_WAVE, size=C.MINI_PLAYER_SIZE, grav=-1, y=200)
        controller = PathFollowController([(0, 200), (1000, 200)])
        controller._hazard_cells = {(99, 99)}
        state = p.mirror.to_dict()
        with patch.object(controller, "path_crosses_hazard", return_value=False) as estimate:
            controller.mirror_crosses_hazard(p, True, True, 10)
        self.assertAlmostEqual(estimate.call_args.args[3], p.params.wave_velocity(p.move_speed, -1, True, True))
        self.assertEqual(p.mirror.to_dict(), state)

    def test_mirror_sweeps_horizontal_hazards(self):
        from src.player.body import MirrorBody
        p = Player([{"t": C.T_SPIKE, "x": 4, "y": 4}])
        p.x = 300
        p.mirror = MirrorBody(y=200, grav=1, mode=C.MODE_SHIP)
        p._step_mirror(False, False, 200)
        self.assertFalse(p.mirror.alive)
        self.assertEqual(p.x, 300)

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
        self.assertAlmostEqual((p.x - x) / C.CELL, 10.386)
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
        self.assertTrue(2.30 < (y - apex) / C.CELL < 2.40)
        self.assertTrue(0.42 < ticks / 240 < 0.44)
        self.assertTrue(4.35 < (p.x - x) / C.CELL < 4.55)

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
                p._set_size(C.MINI_PLAYER_SIZE)
            y = p.y
            p.update(True, True)
            while p.vy < 0:
                p.update(False, False)
            heights.append(y - p.y)
        self.assertTrue(0.60 < heights[1] / heights[0] < 0.67)

    def test_wave_reversal_and_mini_slope(self):
        for size, slope in ((C.PLAYER_SIZE, 1), (C.MINI_PLAYER_SIZE, 2)):
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
        self.assertTrue(3 < (y - p.y) / C.CELL < 4)
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
        self.assertLess(p.y + p.size, 10 * C.CELL)

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
            p.x, p.grav, p.on_ground = 3 * C.CELL, grav, False
            p.y = 5 * C.CELL - p.size + 0.1 if grav == 1 else 6 * C.CELL - 0.1
            p.vy = grav
            p._resolve_y_collision(p, grav * 0.2)
            self.assertTrue(p.on_ground)
            self.assertEqual(p.y, 5 * C.CELL - p.size if grav == 1 else 6 * C.CELL)

    def test_cube_ceiling_lethal_ship_ceiling_slides(self):
        for mode, alive in ((C.MODE_CUBE, False), (C.MODE_ROBOT, False),
                            (C.MODE_SHIP, True), (C.MODE_BALL, True)):
            p = Player([{"t": C.T_BLOCK, "x": 3, "y": 5}])
            p.x, p.y, p.mode = 3 * C.CELL, 6 * C.CELL - 0.1, mode
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
        self.assertLess(p.vy, -C.MAX_FALL_UFO)

    def test_wave_slope_contact_is_lethal(self):
        p = Player([{"t": C.T_SLOPE, "x": 3, "y": 5, "r": 0}])
        p.x, p.y, p.mode = 3 * C.CELL, 5 * C.CELL, C.MODE_WAVE
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


if __name__ == "__main__":
    unittest.main()
