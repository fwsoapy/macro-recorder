"""Real SendInput through real hooks.

A second hook eats the injected events after the app's hook has seen them, so these keys and
clicks never reach whatever window you have open. The cursor really moves, and the tests put it back.
"""
import ctypes
import time
import unittest
from ctypes import wintypes

import engine
from macro import Action, key_action

engine.enable_dpi_awareness()


def eat_injected_keys(wparam, lparam):
    return bool(engine.KBDLLHOOKSTRUCT.from_address(lparam).flags & engine.LLKHF_INJECTED)


def eat_injected_clicks(wparam, lparam):
    """Moves pass through because Windows reports a click at the cursor's real position."""
    event = engine.MSLLHOOKSTRUCT.from_address(lparam)
    return wparam != engine.WM_MOUSEMOVE and bool(event.flags & engine.LLMHF_INJECTED)


class Loopback(unittest.TestCase):
    def setUp(self):
        self.seen = []
        self.recorder = engine.Recorder()
        self.router = engine.InputRouter(self.recorder, self.seen.append)
        self.router.ignore_injected = False
        # Hooks run newest first: the app's router sees events, then the eater drops them.
        self.eaters = [engine.HookThread(engine.WH_KEYBOARD_LL, eat_injected_keys),
                       engine.HookThread(engine.WH_MOUSE_LL, eat_injected_clicks)]
        for eater in self.eaters:
            eater.start_and_wait()
        self.router.start_keyboard()
        self.router.start_mouse()
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        self.router.stop()
        for eater in self.eaters:
            eater.stop()

    def test_input_struct_matches_win32(self):
        self.assertEqual(ctypes.sizeof(engine.INPUT), 40)

    def test_scan_codes_arrive_as_the_same_key(self):
        self.recorder.start()
        names = ["A", "W", "Space", "F13", "LShift", "RShift", "LCtrl", "RCtrl", "LAlt", "RAlt", "Left", "Up", "Right",
                 "Down", "Home", "End", "PageUp", "PageDown", "Insert", "Delete", "Enter", "NumEnter", "Num/",
                 "PrintScreen", "NumLock", "CapsLock", "LWin", "Apps"]
        for name in names:
            action = key_action("key down", name)
            engine.send_action(action)
            engine.send_action(key_action("key up", name))
        time.sleep(0.2)
        recorded = [a for a in self.recorder.stop() if a.type == "key down" and a.key in names]
        self.assertEqual([a.key for a in recorded], names)

    def test_pause_key_sends_by_virtual_key(self):
        self.recorder.start()
        engine.send_action(key_action("key down", "Pause"))
        engine.send_action(key_action("key up", "Pause"))
        time.sleep(0.1)
        self.assertIn("Pause", [a.key for a in self.recorder.stop()])

    def test_rerecording_a_recorded_key_gives_the_same_codes(self):
        self.recorder.start()
        engine.send_action(key_action("key down", "RCtrl"))
        engine.send_action(key_action("key up", "RCtrl"))
        time.sleep(0.1)
        first = [a for a in self.recorder.stop() if a.key == "RCtrl"][0]
        self.assertEqual((first.vk, first.scan, first.ext), (0xA3, 0x1D, True))

    def test_hotkey_is_not_recorded_through_real_hooks(self):
        self.router.hotkeys = {0x7D: "play"}  # F14
        self.recorder.start()
        engine.send_action(key_action("key down", "F14"))
        engine.send_action(key_action("key up", "F14"))
        engine.send_action(key_action("key down", "F15"))
        engine.send_action(key_action("key up", "F15"))
        time.sleep(0.1)
        keys = {a.key for a in self.recorder.stop() if a.type.startswith("key")}
        self.assertEqual(self.seen, ["play"])
        self.assertIn("F15", keys)
        self.assertNotIn("F14", keys)

    def test_mouse_buttons_arrive_with_coordinates(self):
        start = wintypes.POINT()
        engine.user32.GetCursorPos(ctypes.byref(start))
        self.addCleanup(engine.send_mouse, start.x, start.y)
        self.recorder.start()
        for button in ("left", "right", "middle"):
            engine.send_action(Action("mouse down", button, 321, 123))
            engine.send_action(Action("mouse up", button, 321, 123))
        time.sleep(0.2)
        clicks = [a for a in self.recorder.stop() if a.type.startswith("mouse")]
        self.assertEqual([(a.type, a.key) for a in clicks],
                         [("mouse down", "left"), ("mouse up", "left"), ("mouse down", "right"),
                          ("mouse up", "right"), ("mouse down", "middle"), ("mouse up", "middle")])
        self.assertTrue(all((a.x, a.y) == (321, 123) for a in clicks))


class Cursor(unittest.TestCase):
    def test_absolute_move_lands_on_the_exact_pixel(self):
        metrics = engine.user32.GetSystemMetrics
        left, top = metrics(engine.SM_XVIRTUALSCREEN), metrics(engine.SM_YVIRTUALSCREEN)
        width, height = metrics(engine.SM_CXVIRTUALSCREEN), metrics(engine.SM_CYVIRTUALSCREEN)
        start = wintypes.POINT()
        engine.user32.GetCursorPos(ctypes.byref(start))
        points = [(left + width // 2 + dx, top + height // 2 + dy) for dx, dy in ((0, 0), (1, 1), (7, -3), (-101, 37))]
        points += [(start.x, start.y), (start.x + 1, start.y)]
        try:
            for x, y in points:
                engine.send_action(Action("move", "", x, y))
                time.sleep(0.03)
                now = wintypes.POINT()
                engine.user32.GetCursorPos(ctypes.byref(now))
                self.assertEqual((now.x, now.y), (x, y))
        finally:
            engine.send_mouse(start.x, start.y)


class RealPlayback(unittest.TestCase):
    def test_grouped_move_ends_on_the_exact_pixel(self):
        start = wintypes.POINT()
        engine.user32.GetCursorPos(ctypes.byref(start))
        self.addCleanup(engine.send_mouse, start.x, start.y)
        move = Action("move", "", start.x, start.y, to_x=start.x + 37, to_y=start.y + 11, duration_ms=60)
        player = engine.Player()
        player.play([move])
        player.join(5)
        time.sleep(0.03)
        now = wintypes.POINT()
        engine.user32.GetCursorPos(ctypes.byref(now))
        self.assertEqual((now.x, now.y), (start.x + 37, start.y + 11))

    def test_player_key_reaches_the_hook_and_stop_releases_it(self):
        recorder = engine.Recorder()
        router = engine.InputRouter(recorder, lambda action: None)
        router.ignore_injected = False
        eater = engine.HookThread(engine.WH_KEYBOARD_LL, eat_injected_keys)
        eater.start_and_wait()
        router.start_keyboard()
        try:
            recorder.start(moves=False)
            player = engine.Player()
            player.play([key_action("key down", "F16"), Action("delay", delay_ms=60000)])
            time.sleep(0.1)
            player.stop()
            player.join(5)
            time.sleep(0.1)
            events = [a.type for a in recorder.stop() if a.key == "F16"]
            self.assertEqual(events, ["key down", "key up"])
        finally:
            router.stop()
            eater.stop()


if __name__ == "__main__":
    unittest.main()
