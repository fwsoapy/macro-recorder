"""Logic tests. They send no real input."""
import json
import tempfile
import time
import unittest
from pathlib import Path

import engine
from macro import (Action, DEFAULT_SETTINGS, edit_cell, group_moves, split_delays, tidy, key_action, key_info, key_name, load_macro,
                   load_settings, move_points, move_rows, row_values, parse_loops, parse_percent, parse_speed, save_macro, save_settings, with_type)


class TempDirTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)


class RoundTrip(TempDirTest):
    def test_create_save_load_keeps_delays_and_every_field(self):
        macro = [
            Action("delay", delay_ms=12.5),
            key_action("key down", "W"),
            Action("delay", delay_ms=1000.125),
            Action("key up", "NumEnter", vk=0x0D, scan=0x1C, ext=True),
            Action("delay", delay_ms=0.1),
            Action("mouse down", "right", 1920, -5),
            Action("mouse up", "right", 1920, -5),
            Action("move", "", 10, 20, to_x=40, to_y=50, duration_ms=16.6,
                   path=((10, 20, 0.0), (25, 35, 8.3), (40, 50, 16.6))),
            Action("delay", delay_ms=2500.0),
        ]
        path = self.dir / "macro.json"
        save_macro(path, macro)
        loaded = load_macro(path)
        self.assertEqual([a.delay_ms for a in loaded if a.type == "delay"], [12.5, 1000.125, 0.1, 2500.0])
        self.assertEqual(loaded, macro)

    def test_older_files_get_delay_rows(self):
        path = self.dir / "old.json"
        rows = [{"type": "key down", "key": "A", "delay_ms": 40}, {"type": "delay", "delay_ms": 500},
                {"type": "mouse down", "key": "left", "x": 1, "y": 2, "delay_ms": 0}]
        path.write_text(json.dumps({"version": 1, "actions": rows}), encoding="utf-8")
        self.assertEqual(load_macro(path), [Action("delay", delay_ms=40), key_action("key down", "A"),
                                            Action("delay", delay_ms=500), Action("mouse down", "left", 1, 2)])
    def test_file_is_readable_json_with_one_action_per_line(self):
        path = self.dir / "macro.json"
        save_macro(path, [key_action("key down", "A", 5)])
        text = path.read_text(encoding="utf-8")
        self.assertIn('"key": "A"', text)
        self.assertEqual(json.loads(text)["actions"][0]["delay_ms"], 5)

    def test_empty_macro(self):
        path = self.dir / "macro.json"
        save_macro(path, [])
        self.assertEqual(load_macro(path), [])

    def test_hand_edited_key_name_updates_codes(self):
        path = self.dir / "macro.json"
        save_macro(path, [key_action("key down", "A")])
        path.write_text(path.read_text(encoding="utf-8").replace('"key": "A"', '"key": "F5"'), encoding="utf-8")
        self.assertEqual(load_macro(path)[0], key_action("key down", "F5"))

    def test_bad_files_raise_value_error(self):
        path = self.dir / "bad.json"
        for text in ("not json", "[]", '{"actions": 3}', '{"actions": [{"type": "explode"}]}',
                     '{"actions": [{"type": "delay", "delay_ms": -1}]}',
                     '{"actions": [{"type": "delay", "delay_ms": NaN}]}',
                     '{"actions": [{"type": "delay", "delay_ms": true}]}',
                     '{"actions": [{"type": "key down", "key": "nope"}]}',
                     '{"actions": [{"type": "move", "x": 1}]}',
                     '{"actions": [{"type": "move", "x": 1, "y": 1, "to_x": 2}]}',
                     '{"actions": [{"type": "move", "x": 1, "y": 1, "to_x": 2, "to_y": 2, "path": [[1, 1]]}]}',
                     '{"actions": [{"type": "move", "x": 1, "y": 1, "to_x": 2, "to_y": 2, "path": [[1, 1, 9], [2, 2, 3]]}]}',
                     '{"actions": [{"type": "mouse down", "key": "side", "x": 1, "y": 1}]}'):
            path.write_text(text, encoding="utf-8")
            with self.assertRaises(ValueError, msg=text):
                load_macro(path)

    def test_failed_save_keeps_old_file(self):
        path = self.dir / "macro.json"
        save_macro(path, [Action("delay", delay_ms=1.0)])
        with self.assertRaises(TypeError):
            save_macro(path, [Action("delay", delay_ms=object())])
        self.assertEqual(load_macro(path)[0].delay_ms, 1.0)
        self.assertEqual(list(self.dir.glob("*.tmp")), [])


class MoveGrouping(TempDirTest):
    SAMPLES = [Action("move", "", 0, 0, 100.0), Action("move", "", 10, 5, 8.0), Action("move", "", 20, 10, 9.0)]

    def test_run_of_samples_becomes_one_move_with_same_total_time(self):
        click = Action("mouse down", "left", 20, 10, 30.0)
        grouped = group_moves(self.SAMPLES + [click])
        self.assertEqual(len(grouped), 2)
        move = grouped[0]
        self.assertEqual((move.x, move.y, move.to_x, move.to_y), (0, 0, 20, 10))
        self.assertEqual((move.delay_ms, move.duration_ms), (100.0, 17.0))
        self.assertEqual(move.path, ((0, 0, 0.0), (10, 5, 8.0), (20, 10, 17.0)))
        self.assertEqual(grouped[1], click)

    def test_other_actions_split_runs_and_finished_moves_stay_separate(self):
        wait = Action("delay", delay_ms=1)
        grouped = group_moves(self.SAMPLES[:2] + [wait] + self.SAMPLES[2:])
        self.assertEqual([a.type for a in grouped], ["move", "delay", "move"])
        once = group_moves(grouped + grouped)
        self.assertEqual(len(once), 6)
        self.assertEqual(group_moves([]), [])

    def test_single_sample_is_an_instant_move(self):
        move = group_moves(self.SAMPLES[:1])[0]
        self.assertEqual((move.to_x, move.to_y, move.duration_ms, move.path), (0, 0, 0.0, ()))
        self.assertEqual(move_points(move), [(0, 0, 0.0)])

    def test_old_files_load_grouped(self):
        path = self.dir / "old.json"
        rows = [{"type": "move", "x": i, "y": i, "delay_ms": 8.0} for i in range(100)]
        path.write_text(json.dumps({"version": 1, "actions": rows}), encoding="utf-8")
        delay, move = load_macro(path)
        self.assertEqual((delay.type, delay.delay_ms), ("delay", 8.0))
        self.assertEqual((move.x, move.to_x, move.duration_ms, move.delay_ms), (0, 99, 792.0, 0))

    def test_split_delays_keeps_total_time_and_order(self):
        recorded = [Action("move", "", 0, 0, 100.0), Action("move", "", 5, 5, 8.0),
                    Action("mouse down", "left", 5, 5, 30.0), Action("mouse up", "left", 5, 5, 0.0)]
        rows = tidy(recorded)
        self.assertEqual([a.type for a in rows], ["delay", "move", "delay", "mouse down", "mouse up"])
        self.assertEqual([a.delay_ms for a in rows], [100.0, 0, 30.0, 0, 0])
        self.assertEqual(rows[1].duration_ms, 8.0)
        self.assertEqual(split_delays(rows), rows)
        self.assertEqual(split_delays([]), [])
    def test_points_replay_recording_unchanged(self):
        move = group_moves(self.SAMPLES)[0]
        self.assertEqual(move_points(move), [(0, 0, 0.0), (10, 5, 8.0), (20, 10, 17.0)])

    def test_edited_endpoints_keep_shape_and_land_exactly(self):
        move = edit_cell(edit_cell(group_moves(self.SAMPLES)[0], "to_x", "120"), "x", "-100")
        points = move_points(move)
        self.assertEqual(points[0][:2], (-100, 0))
        self.assertEqual(points[-1][:2], (120, 10))
        self.assertEqual(len(points), 3)

    def test_edited_duration_rescales_time(self):
        points = move_points(edit_cell(group_moves(self.SAMPLES)[0], "duration", "170"))
        self.assertAlmostEqual(points[-1][2], 170.0)
        self.assertAlmostEqual(points[1][2], 80.0)
        self.assertEqual(move_points(edit_cell(group_moves(self.SAMPLES)[0], "duration", "0")), [(20, 10, 0.0)])

    def test_added_move_is_a_straight_line(self):
        points = move_points(Action("move", "", 0, 0, to_x=100, to_y=-100, duration_ms=100))
        self.assertEqual(len(points), 13)
        self.assertEqual(points[0], (0, 0, 0.0))
        self.assertEqual(points[-1], (100, -100, 100.0))
        self.assertTrue(all(x == -y for x, y, _ in points))

    def test_move_only_columns_rejected_elsewhere(self):
        for column in ("to_x", "to_y", "duration"):
            with self.assertRaises(ValueError):
                edit_cell(Action("delay"), column, "5")
        self.assertEqual(with_type(Action("mouse down", "left", 3, 4), "move").to_x, 3)
        self.assertEqual(with_type(Action("move", "", 3, 4, to_x=9, to_y=9), "mouse up").to_x, None)


class Keys(unittest.TestCase):
    def test_scan_codes_for_game_keys(self):
        self.assertEqual(key_info("w")[1:], (0x57, 0x11, False))
        self.assertEqual(key_info("Space")[1:], (0x20, 0x39, False))
        self.assertEqual(key_info("Left")[1:], (0x25, 0x4B, True))
        self.assertEqual(key_info("RCtrl")[1:], (0xA3, 0x1D, True))
        self.assertEqual(key_info("LShift")[1:], (0xA0, 0x2A, False))
        self.assertEqual(key_info("NumEnter")[1:], (0x0D, 0x1C, True))
        self.assertEqual(key_info("PrintScreen")[1:], (0x2C, 0x37, True))

    def test_names_round_trip(self):
        for vk in list(range(0x30, 0x3A)) + list(range(0x41, 0x5B)) + list(range(0x70, 0x88)):
            self.assertEqual(key_info(key_name(vk))[1], vk)
        self.assertEqual(key_name(0xB3), "VK_B3")
        self.assertEqual(key_info("VK_B3")[1], 0xB3)

    def test_unknown_names_rejected(self):
        for name in ("", "nope", "vk_zz", "vk_0", "vk_1ff"):
            with self.assertRaises(ValueError, msg=name):
                key_info(name)


class Editing(unittest.TestCase):
    def test_edit_delay(self):
        self.assertEqual(edit_cell(Action("delay"), "delay", "50").delay_ms, 50.0)
        for bad in ("", "abc", "-1", "nan", "inf"):
            with self.assertRaises(ValueError, msg=bad):
                edit_cell(Action("delay"), "delay", bad)

    def test_only_delay_rows_have_a_delay(self):
        for action in (key_action("key down", "A"), Action("move", "", 0, 0, to_x=1, to_y=1), Action("mouse up", "left", 0, 0)):
            with self.assertRaises(ValueError):
                edit_cell(action, "delay", "50")
        self.assertEqual(row_values(0, key_action("key down", "A"))[-1], "")
        self.assertEqual(row_values(0, Action("delay", delay_ms=50))[-1], "50")
    def test_edit_coordinates_only_on_mouse_actions(self):
        self.assertEqual(edit_cell(Action("move", x=1, y=2), "x", "-30").x, -30)
        for action, text in ((key_action("key down", "A"), "5"), (Action("delay"), "5"), (Action("move", x=1, y=2), "1.5")):
            with self.assertRaises(ValueError):
                edit_cell(action, "x", text)

    def test_edit_key_updates_scan_code(self):
        edited = edit_cell(key_action("key down", "A", 7), "key", "d")
        self.assertEqual((edited.key, edited.vk, edited.scan, edited.delay_ms), ("D", 0x44, 0x20, 7))

    def test_edit_key_column_by_type(self):
        self.assertEqual(edit_cell(Action("mouse down", "left", 0, 0), "key", "middle").key, "middle")
        for action, text in ((Action("mouse down", "left", 0, 0), "A"), (Action("move", x=0, y=0), "A"), (Action("delay"), "A")):
            with self.assertRaises(ValueError):
                edit_cell(action, "key", text)

    def test_type_change_fills_fields(self):
        key = key_action("key down", "A")
        self.assertEqual(with_type(key, "key up").key, "A")
        mouse = with_type(key, "mouse down")
        self.assertEqual((mouse.key, mouse.x, mouse.y, mouse.vk), ("left", 0, 0, 0))
        self.assertEqual(with_type(mouse, "move").key, "")
        self.assertEqual(with_type(mouse, "delay"), Action("delay"))
        self.assertEqual(with_type(Action("delay", delay_ms=3), "key up"), key_action("key up", "Space"))
        with self.assertRaises(ValueError):
            with_type(key, "explode")
    def test_move_rows(self):
        rows = list("abcde")
        self.assertEqual(move_rows(rows, [2], -1), (list("acbde"), [1]))
        self.assertEqual(move_rows(rows, [1, 3], 1), (list("acbed"), [2, 4]))
        self.assertEqual(move_rows(rows, [0, 1], -1), (rows, [0, 1]))  # block at the top stays put
        self.assertEqual(move_rows(rows, [3, 4], 1), (rows, [3, 4]))
        self.assertEqual(move_rows(rows, [1, 2], 1), (list("adbce"), [2, 3]))


class Settings(TempDirTest):
    def test_ranges(self):
        self.assertEqual((parse_speed("0.1"), parse_speed("10")), (0.1, 10.0))
        self.assertEqual((parse_loops("0"), parse_percent("100")), (0, 100.0))
        for parse, bad in ((parse_speed, "0.05"), (parse_speed, "10.1"), (parse_speed, "nan"), (parse_speed, "x"),
                           (parse_loops, "-1"), (parse_loops, "1.5"), (parse_percent, "101"), (parse_percent, "-1")):
            with self.assertRaises(ValueError, msg=(parse.__name__, bad)):
                parse(bad)

    def test_round_trip(self):
        path = self.dir / "config.json"
        settings = dict(DEFAULT_SETTINGS, hotkey_play="F6", speed=2.5, loops=0)
        save_settings(path, settings)
        self.assertEqual(load_settings(path), (settings, None))

    def test_missing_file_gives_defaults_silently(self):
        self.assertEqual(load_settings(self.dir / "none.json"), (DEFAULT_SETTINGS, None))

    def test_corrupt_file_gives_defaults_and_warning(self):
        path = self.dir / "config.json"
        path.write_text("{oops", encoding="utf-8")
        settings, warning = load_settings(path)
        self.assertEqual(settings, DEFAULT_SETTINGS)
        self.assertIn("config.json", warning)

    def test_bad_values_fall_back_one_by_one(self):
        path = self.dir / "config.json"
        path.write_text(json.dumps({"speed": 99, "loops": 5, "record_mouse": "yes", "hotkey_play": "F8"}), encoding="utf-8")
        settings, _ = load_settings(path)
        self.assertEqual((settings["speed"], settings["loops"], settings["record_mouse"]), (1.0, 5, True))
        self.assertEqual(settings["hotkey_play"], "F9")  # F8 would clash with record


class Recording(unittest.TestCase):
    def setUp(self):
        self.recorder = engine.Recorder()
        self.hotkeys = []
        self.router = engine.InputRouter(self.recorder, self.hotkeys.append)
        self.router.hotkeys = {0x77: "record", 0x78: "play", 0x79: "stop"}

    def test_delays_measure_the_gap_before_each_action(self):
        self.recorder.start(now=100.0)
        self.recorder.key(0x41, 0x1E, False, True, now=100.25)
        self.recorder.button("left", True, 5, 6, now=100.5)
        self.recorder.key(0x41, 0x1E, False, False, now=101.5)
        self.assertEqual([a.delay_ms for a in self.recorder.stop()], [250.0, 250.0, 1000.0])

    def test_move_throttle_caps_at_120_per_second(self):
        self.recorder.start(now=0.0)
        for ms in range(1000):  # a 1000 Hz mouse
            self.recorder.move(ms, 0, now=1 + ms / 1000)
        count = len(self.recorder.stop())
        self.assertLessEqual(count, 120)
        self.assertGreaterEqual(count, 100)

    def test_throttled_moves_stay_in_the_next_gap(self):
        self.recorder.start(now=0.0)
        self.recorder.move(1, 1, now=1.0)
        self.recorder.move(2, 2, now=1.001)  # dropped
        self.recorder.button("left", True, 2, 2, now=1.5)
        actions = self.recorder.stop()
        self.assertEqual([a.type for a in actions], ["move", "mouse down"])
        self.assertEqual(actions[1].delay_ms, 500.0)

    def test_options_turn_off_moves_and_keyboard_but_not_clicks(self):
        self.recorder.start(moves=False, keyboard=False, now=0.0)
        self.recorder.move(1, 1, now=1.0)
        self.recorder.key(0x41, 0x1E, False, True, now=2.0)
        self.recorder.button("right", True, 1, 1, now=3.0)
        actions = self.recorder.stop()
        self.assertEqual([a.type for a in actions], ["mouse down"])
        self.assertEqual(actions[0].delay_ms, 3000.0)

    def test_auto_repeat_records_one_key_down(self):
        self.recorder.start(now=0.0)
        for t in (1.0, 1.5, 1.53, 1.56):
            self.recorder.key(0x41, 0x1E, False, True, now=t)
        self.recorder.key(0x41, 0x1E, False, False, now=2.0)
        self.recorder.key(0x41, 0x1E, False, True, now=3.0)
        self.assertEqual([a.type for a in self.recorder.stop()], ["key down", "key up", "key down"])

    def test_nothing_recorded_when_inactive(self):
        self.recorder.key(0x41, 0x1E, False, True)
        self.recorder.button("left", True, 0, 0)
        self.recorder.move(0, 0)
        self.assertEqual(self.recorder.actions, [])

    def test_hotkeys_fire_once_and_never_get_recorded(self):
        self.recorder.start()
        self.router.handle_key(0x78, 0x43, 0)  # F9 down
        self.router.handle_key(0x78, 0x43, 0)  # auto-repeat
        self.router.handle_key(0x78, 0x43, engine.LLKHF_UP)
        self.router.handle_key(0x77, 0x42, engine.LLKHF_UP)  # F8 release left over from starting
        self.router.handle_key(0x41, 0x1E, 0)
        self.assertEqual(self.hotkeys, ["play"])
        self.assertEqual([a.key for a in self.recorder.stop()], ["A"])

    def test_injected_input_ignored(self):
        self.recorder.start()
        self.router.handle_key(0x79, 0x44, engine.LLKHF_INJECTED)
        self.router.handle_key(0x41, 0x1E, engine.LLKHF_INJECTED)
        self.router.handle_mouse(engine.WM_MOUSEMOVE, 1, 1, engine.LLMHF_INJECTED)
        self.assertEqual(self.hotkeys, [])
        self.assertEqual(self.recorder.stop(), [])

    def test_capture_takes_the_next_key_instead_of_recording_it(self):
        captured = []
        self.router.on_capture = captured.append
        self.router.capturing = True
        self.recorder.start()
        self.router.handle_key(0x78, 0x43, 0)
        self.assertEqual((captured, self.hotkeys, self.router.capturing), ([0x78], [], False))
        self.assertEqual(self.recorder.stop(), [])

    def test_extended_flag_kept(self):
        self.recorder.start()
        self.router.handle_key(0x0D, 0x1C, engine.LLKHF_EXTENDED)
        action = self.recorder.stop()[0]
        self.assertEqual((action.key, action.scan, action.ext), ("NumEnter", 0x1C, True))


class Playback(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.finished = []
        self.player = engine.Player(send=self._send, on_done=self.finished.append)

    def _send(self, action):
        self.sent.append((action, time.perf_counter()))

    def _play(self, actions, **kwargs):
        self.player.play(actions, **kwargs)
        self.player.join(10)
        self.assertFalse(self.player.playing)

    def test_loop_count(self):
        self._play([Action("delay")], loops=3)
        self.assertEqual(len(self.sent), 3)
        self.assertEqual(self.finished, [None])

    def test_timing_and_speed_multiplier(self):
        macro = [Action("delay", delay_ms=0), Action("delay", delay_ms=100), Action("delay", delay_ms=100)]
        self._play(macro, speed=2.0)
        elapsed = self.sent[-1][1] - self.sent[0][1]
        self.assertAlmostEqual(elapsed, 0.1, delta=0.02)
        self.assertEqual(macro[1].delay_ms, 100)

    def test_no_drift_over_many_short_delays(self):
        self._play([Action("delay", delay_ms=2)] * 100)
        self.assertAlmostEqual(self.sent[-1][1] - self.sent[0][1], 0.198, delta=0.02)

    def test_jitter_stays_inside_percent(self):
        self._play([Action("delay", delay_ms=10)] * 50, jitter_percent=50)
        gaps = [b[1] - a[1] for a, b in zip(self.sent, self.sent[1:])]
        self.assertGreater(max(gaps) - min(gaps), 0.001)
        self.assertLess(sum(gaps), 49 * 0.015 + 0.02)

    def test_move_plays_every_point_over_its_duration(self):
        move = Action("move", "", 0, 0, to_x=30, to_y=0, duration_ms=100,
                      path=((0, 0, 0.0), (10, 0, 50.0), (30, 0, 100.0)))
        self._play([move, Action("delay", delay_ms=0)], speed=2.0)
        self.assertEqual([(a.x, a.y) for a, _ in self.sent[:3]], [(0, 0), (10, 0), (30, 0)])
        self.assertAlmostEqual(self.sent[2][1] - self.sent[0][1], 0.05, delta=0.015)

    def test_stop_interrupts_a_long_move(self):
        self.player.play([Action("move", "", 0, 0, to_x=500, to_y=0, duration_ms=60000)])
        time.sleep(0.1)
        self.player.stop()
        self.player.join(1)
        self.assertFalse(self.player.playing)
        self.assertLess(len(self.sent), 50)

    def test_stop_interrupts_a_long_delay_at_once(self):
        self.player.play([Action("delay", delay_ms=60000)])
        time.sleep(0.05)
        start = time.perf_counter()
        self.player.stop()
        self.player.join(5)
        self.assertLess(time.perf_counter() - start, 0.05)
        self.assertEqual(self.sent, [])

    def test_stop_ends_an_infinite_loop(self):
        self.player.play([Action("delay")], loops=0)
        time.sleep(0.05)
        self.player.stop()
        self.player.join(5)
        self.assertFalse(self.player.playing)

    def test_held_keys_and_buttons_released_on_stop(self):
        macro = [key_action("key down", "W"), Action("mouse down", "left", 5, 5), key_action("key down", "A"),
                 key_action("key up", "A"), Action("delay", delay_ms=60000)]
        self.player.play(macro)
        while len(self.sent) < 4:
            time.sleep(0.001)
        self.player.stop()
        self.player.join(5)
        released = [(a.type, a.key) for a, _ in self.sent[4:]]
        self.assertCountEqual(released, [("key up", "W"), ("mouse up", "left")])

    def test_send_failure_reports_error_and_still_finishes(self):
        def fail(action):
            raise OSError("blocked")
        player = engine.Player(send=fail, on_done=self.finished.append)
        player.play([Action("delay")], loops=0)
        player.join(5)
        self.assertEqual(self.finished, ["blocked"])
        self.assertFalse(player.playing)

    def test_cannot_play_twice_at_once(self):
        self.player.play([Action("delay", delay_ms=60000)])
        with self.assertRaises(RuntimeError):
            self.player.play([Action("delay")])
        self.player.stop()
        self.player.join(5)



class NewHelpersTest(unittest.TestCase):
    def test_parse_countdown(self):
        from macro import parse_countdown
        self.assertEqual(parse_countdown("3"), 3)
        self.assertEqual(parse_countdown(0), 0)
        for bad in ("-1", "11", "2.5", "x", None):
            with self.assertRaises(ValueError):
                parse_countdown(bad)

    def test_macro_length_counts_delays_and_moves(self):
        from macro import Action, macro_length_ms, format_length
        actions = [Action("delay", delay_ms=500), Action("move", "", 0, 0, to_x=1, to_y=1, duration_ms=250),
                   Action("key down", "A")]
        self.assertEqual(macro_length_ms(actions), 750)
        self.assertEqual(format_length(750), "750 ms")
        self.assertEqual(format_length(4200), "4.2 s")
        self.assertEqual(format_length(185000), "3 min 05 s")

    def test_settings_load_new_fields_and_reject_bad_ones(self):
        import json, tempfile
        from pathlib import Path
        from macro import load_settings
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "config.json"
            path.write_text(json.dumps({"countdown": 5, "always_on_top": True, "recent": ["a.json", 3, "", "b.json"]}))
            settings, warning = load_settings(path)
            self.assertIsNone(warning)
            self.assertEqual((settings["countdown"], settings["always_on_top"]), (5, True))
            self.assertEqual(settings["recent"], ["a.json", "b.json"])
            path.write_text(json.dumps({"countdown": 99, "always_on_top": "yes", "recent": "nope"}))
            settings, _ = load_settings(path)
            self.assertEqual((settings["countdown"], settings["always_on_top"], settings["recent"]), (3, False, []))

if __name__ == "__main__":
    unittest.main()
