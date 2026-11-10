"""Drives the real GUI: real widgets and real cell editing. Dialogs are patched out."""
import json
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

import engine
import app as app_module
from app import App, InsertDialog
from macro import Action, key_action, load_macro

engine.enable_dpi_awareness()


class AppTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)
        patcher = mock.patch.object(app_module.messagebox, "showerror")
        self.showerror = patcher.start()
        self.addCleanup(patcher.stop)
        self.root = tk.Tk()
        self.app = App(self.root, self.dir / "config.json")
        self.root.update()
        self.addCleanup(self._close)

    def _close(self):
        self.app.dirty = False
        self.app.close()

    def load(self, count=5):
        self.app.actions = [Action("delay", delay_ms=float(i)) for i in range(count)]
        self.app._refresh()
        self.root.update()

    def delays(self):
        return [a.delay_ms for a in self.app.actions]

    def double_click(self, row, column):
        self.app.tree.see(str(row))
        self.root.update()
        x, y, w, h = self.app.tree.bbox(str(row), column)
        for _ in range(2):  # Tk can't generate <Double-1> directly, but two quick clicks trigger it
            self.app.tree.event_generate("<ButtonPress-1>", x=x + w // 2, y=y + h // 2)
            self.app.tree.event_generate("<ButtonRelease-1>", x=x + w // 2, y=y + h // 2)
        self.root.update()

    def type_in_editor(self, text, key="<Return>"):
        entry = self.app._editor[0]
        entry.delete(0, "end")
        entry.insert(0, text)
        entry.focus_force()  # Tk sends generated key events to the focused widget
        self.root.update()
        entry.event_generate(key)
        self.root.update()

    def test_table_shows_each_column(self):
        self.app.actions = [Action("mouse down", "left", 10, 20), Action("delay", delay_ms=12.5),
                            Action("move", "", 1, 2, to_x=3, to_y=4, duration_ms=100)]
        self.app._refresh()
        self.assertEqual(self.app.tree.item("0", "values"), ("1", "mouse down", "left", "10", "20", "", "", "", ""))
        self.assertEqual(self.app.tree.item("1", "values"), ("2", "delay", "", "", "", "", "", "", "12.5"))
        self.assertEqual(self.app.tree.item("2", "values"), ("3", "move", "", "1", "2", "3", "4", "100", ""))
    def test_edit_move_end_and_duration_cells(self):
        self.app.actions = [Action("move", "", 1, 2, to_x=3, to_y=4, duration_ms=100)]
        self.app._refresh()
        self.root.update()
        self.double_click(0, "to_x")
        self.type_in_editor("300")
        self.double_click(0, "duration")
        self.type_in_editor("250")
        self.assertEqual((self.app.actions[0].to_x, self.app.actions[0].duration_ms), (300, 250))
    def test_recording_groups_mouse_moves_into_one_row(self):
        self.app.toggle_record()
        for i in range(100):
            self.app.recorder.move(i, i, now=self.app.recorder._last + 0.01)
        self.app.recorder.button("left", True, 99, 99, now=self.app.recorder._last + 0.05)
        self.app.toggle_record()
        self.assertEqual([a.type for a in self.app.actions], ["delay", "move", "delay", "mouse down"])
        self.assertEqual((self.app.actions[1].x, self.app.actions[1].to_x), (0, 99))

    def test_context_menu_adds_above_and_below_clicked_row(self):
        self.load(3)
        menu = self.app._context_menu(1)
        self.assertEqual([menu.entrycget(i, "label") for i in (0, 1)], ["Add below", "Add above"])
        for index, expected in ((0, 2), (1, 1)):
            submenu = menu.nametowidget(menu.entrycget(index, "menu"))
            labels = [submenu.entrycget(i, "label") for i in range(submenu.index("end") + 1)]
            self.assertEqual(labels, list(app_module.INSERT_KINDS))
            with mock.patch.object(app_module, "InsertDialog") as dialog:
                submenu.invoke(labels.index("Delay"))
            dialog.assert_called_once_with(self.app, "Delay", expected)

    def test_context_menu_on_empty_table_adds_at_end(self):
        self.load(2)
        menu = self.app._context_menu(None)
        self.assertEqual(menu.index("end"), 0)
        submenu = menu.nametowidget(menu.entrycget(0, "menu"))
        with mock.patch.object(app_module, "InsertDialog") as dialog:
            submenu.invoke(0)
        dialog.assert_called_once_with(self.app, "Key press", 2)

    def test_add_at_position_from_context_menu(self):
        self.load(3)
        dialog = InsertDialog(self.app, "Delay", 0)
        dialog.delay.set("500")
        dialog.submit()
        self.assertEqual(self.delays(), [500, 0, 1, 2])
        self.assertEqual(self.app.actions[0].type, "delay")
        self.assertEqual(self.app._selected(), [0])

    def test_add_dialog_focuses_a_visible_field_so_enter_submits(self):
        self.load(1)
        dialog = InsertDialog(self.app, "Delay", 1)
        self.root.update()
        field = dialog.rows["delay"][1]
        self.assertEqual(self.root.focus_get(), field)
        field.event_generate("<Return>")
        self.root.update()
        self.assertFalse(dialog.top.winfo_exists())
        self.assertEqual(self.app.actions[1].type, "delay")

    def test_add_every_other_kind(self):
        self.load(1)
        expected = {"Key down": ("key down", "Space"), "Key up": ("key up", "Space"),
                    "Mouse down": ("mouse down", "left"), "Mouse up": ("mouse up", "left")}
        for kind, (action_type, key) in expected.items():
            dialog = InsertDialog(self.app, kind, 0)
            dialog.submit()
            self.assertEqual((self.app.actions[0].type, self.app.actions[0].key), (action_type, key))
        dialog = InsertDialog(self.app, "Mouse move", 0)
        dialog.x.set("1")
        dialog.y.set("2")
        dialog.to_x.set("300")
        dialog.to_y.set("400")
        dialog.duration.set("250")
        dialog.submit()
        self.assertEqual(self.app.actions[0], Action("move", "", 1, 2, to_x=300, to_y=400, duration_ms=250))

    def test_new_click_starts_where_the_previous_move_ended(self):
        self.app.actions = [Action("move", "", 1, 2, to_x=30, to_y=40)]
        self.app._refresh()
        dialog = InsertDialog(self.app, "Mouse click", 1)
        self.assertEqual((dialog.x.get(), dialog.y.get()), ("30", "40"))
        dialog.top.destroy()

    def test_double_click_delay_edits_only_that_cell(self):
        self.load()
        self.double_click(2, "delay")
        self.assertEqual(self.app._editor[0].get(), "2")
        self.type_in_editor("75")
        self.assertEqual(self.delays(), [0, 1, 75, 3, 4])
        self.assertEqual(self.app.tree.set("2", "delay"), "75")
        self.assertTrue(self.app.dirty)

    def test_bad_delay_shows_error_and_changes_nothing(self):
        self.load()
        self.double_click(1, "delay")
        self.type_in_editor("abc")
        self.showerror.assert_called_once()
        self.assertEqual(self.delays(), [0, 1, 2, 3, 4])

    def test_escape_cancels_edit(self):
        self.load()
        self.double_click(1, "delay")
        self.type_in_editor("999", "<Escape>")
        self.assertEqual(self.delays()[1], 1)

    def test_scrolling_commits_the_open_editor(self):
        self.load(200)
        self.double_click(0, "delay")
        entry = self.app._editor[0]
        entry.delete(0, "end")
        entry.insert(0, "42")
        self.app.tree.yview_moveto(0.5)
        self.root.update()
        self.assertIsNone(self.app._editor)
        self.assertEqual(self.delays()[0], 42)

    def test_double_click_ignored_on_number_column_and_blank_cells(self):
        self.load()
        self.double_click(0, "num")
        self.assertIsNone(self.app._editor)
        self.double_click(0, "x")
        self.assertIsNone(self.app._editor)

    def test_delete_duplicate_move_undo(self):
        self.load()
        self.app.tree.selection_set(["1", "3"])
        self.app.delete_selected()
        self.assertEqual(self.delays(), [0, 2, 4])
        self.assertEqual(self.app._selected(), [1])

        self.app.tree.selection_set(["0", "1"])
        self.app.duplicate_selected()
        self.assertEqual(self.delays(), [0, 2, 0, 2, 4])
        self.assertEqual(self.app._selected(), [2, 3])

        self.app.tree.selection_set(["4"])
        self.app.move_selected(-1)
        self.assertEqual(self.delays(), [0, 2, 0, 4, 2])
        self.assertEqual(self.app._selected(), [3])
        self.app.move_selected(1)
        self.assertEqual(self.delays(), [0, 2, 0, 2, 4])

        for expected in ([0, 2, 0, 4, 2], [0, 2, 0, 2, 4], [0, 2, 4], [0, 1, 2, 3, 4]):
            self.app.undo()
            self.assertEqual(self.delays(), expected)
        self.app.undo()  # nothing left: must not raise
        self.assertEqual(self.delays(), [0, 1, 2, 3, 4])

    def test_delete_everything_leaves_empty_state(self):
        self.load(2)
        self.app.tree.selection_set(["0", "1"])
        self.app.delete_selected()
        self.assertEqual(self.app.actions, [])
        self.root.update()
        self.assertTrue(self.app.empty_label.winfo_ismapped())

    def test_set_delay_for_selected(self):
        self.load()
        self.app.tree.selection_set(["0", "2", "4"])
        self.app.set_delay_var.set("50")
        self.app.set_delay_selected()
        self.assertEqual(self.delays(), [50, 1, 50, 3, 50])
        self.assertEqual(self.app.tree.set("4", "delay"), "50")
        self.app.undo()
        self.assertEqual(self.delays(), [0, 1, 2, 3, 4])

    def test_set_delay_skips_rows_that_are_not_delays(self):
        key = key_action("key down", "A")
        self.app.actions = [key, Action("delay", delay_ms=1.0), key]
        self.app._refresh()
        self.app.tree.selection_set(["0", "1", "2"])
        self.app.set_delay_selected()
        self.assertEqual(self.app.actions, [key, Action("delay", delay_ms=50.0), key])
        self.app.tree.selection_set(["0"])
        self.app.set_delay_var.set("9")
        self.app.set_delay_selected()
        self.assertEqual(self.app.actions, [key, Action("delay", delay_ms=50.0), key])
        self.assertIn("None of the selected", self.app.note)

    def test_double_click_delay_on_other_rows_only_notes(self):
        self.app.actions = [key_action("key down", "A")]
        self.app._refresh()
        self.root.update()
        self.double_click(0, "delay")
        self.assertIsNone(self.app._editor)
        self.assertIn("Right-click", self.app.note)
    def test_buttons_without_selection_only_note_it(self):
        self.load()
        for action in (self.app.delete_selected, self.app.duplicate_selected, self.app.set_delay_selected,
                       lambda: self.app.move_selected(1)):
            action()
        self.assertEqual(self.delays(), [0, 1, 2, 3, 4])
        self.showerror.assert_not_called()

    def test_insert_dialog_presses_clicks_and_delays(self):
        self.load(1)
        self.app.tree.selection_set(["0"])
        dialog = InsertDialog(self.app)
        dialog.key.set("f5")
        dialog.hold.set("20")
        dialog.submit()
        self.assertEqual([(a.type, a.key, a.delay_ms) for a in self.app.actions[1:]],
                         [("key down", "F5", 0), ("delay", "", 20), ("key up", "F5", 0)])
        self.assertEqual(self.app._selected(), [1, 2, 3])

        dialog = InsertDialog(self.app)
        dialog.kind.set("Mouse click")
        dialog._show_fields()
        dialog.button.set("right")
        dialog.x.set("100")
        dialog.y.set("-200")
        dialog.hold.set("0")
        dialog.submit()
        self.assertEqual(self.app.actions[4:6], [Action("mouse down", "right", 100, -200),
                                                 Action("mouse up", "right", 100, -200)])

        dialog = InsertDialog(self.app)
        dialog.kind.set("Delay")
        dialog._show_fields()
        dialog.delay.set("1000")
        dialog.submit()
        self.assertEqual(self.app.actions[6], Action("delay", delay_ms=1000))
    def test_insert_dialog_rejects_bad_input_and_stays_open(self):
        self.load(1)
        dialog = InsertDialog(self.app)
        dialog.key.set("nonsense")
        dialog.submit()
        self.showerror.assert_called_once()
        self.assertTrue(dialog.top.winfo_exists())
        self.assertEqual(len(self.app.actions), 1)
        dialog.top.destroy()

    def test_save_open_keeps_edits(self):
        self.load(3)
        path = self.dir / "m.json"
        with mock.patch.object(app_module.filedialog, "asksaveasfilename", return_value=str(path)):
            self.assertTrue(self.app.save_as())
        self.assertFalse(self.app.dirty)
        self.assertEqual(self.app.save(), True)  # second save goes straight to the same file
        self.app.actions = []
        with mock.patch.object(app_module.filedialog, "askopenfilename", return_value=str(path)):
            self.app.open()
        self.assertEqual(self.delays(), [0, 1, 2])
        self.assertEqual(self.app.tree.set("2", "delay"), "2")
        self.assertEqual(load_macro(path), self.app.actions)

    def test_open_bad_file_shows_error_and_keeps_macro(self):
        self.load(2)
        path = self.dir / "bad.json"
        path.write_text("nope", encoding="utf-8")
        with mock.patch.object(app_module.filedialog, "askopenfilename", return_value=str(path)):
            self.app.open()
        self.showerror.assert_called_once()
        self.assertEqual(len(self.app.actions), 2)

    def test_unsaved_changes_prompt(self):
        self.load(1)
        self.app.dirty = True
        with mock.patch.object(app_module.messagebox, "askyesnocancel", return_value=None):
            self.assertFalse(self.app._confirm_discard())
        with mock.patch.object(app_module.messagebox, "askyesnocancel", return_value=False):
            self.assertTrue(self.app._confirm_discard())

    def test_settings_saved_and_restored(self):
        self.app.speed_var.set("2.5")
        self.app.loops_var.set("0")
        self.app.record_keyboard_var.set(False)
        self.app._save_settings()
        saved = json.loads((self.dir / "config.json").read_text(encoding="utf-8"))
        self.assertEqual((saved["speed"], saved["loops"], saved["record_keyboard"]), (2.5, 0, False))

    def test_play_validates_inputs(self):
        self.load(1)
        for var, bad in ((self.app.speed_var, "11"), (self.app.loops_var, "-1")):
            good = var.get()
            var.set(bad)
            self.app.play()
            self.assertFalse(self.app.player.playing)
            var.set(good)
        self.assertEqual(self.showerror.call_count, 2)

    def test_play_empty_macro_is_a_status_note(self):
        self.app.play()
        self.assertFalse(self.app.player.playing)
        self.showerror.assert_not_called()
        self.assertEqual(self.app.note, "Nothing to play.")

    def test_status_bar_tracks_play_and_stop(self):
        self.app.actions = [Action("delay", delay_ms=60000)]
        self.app._refresh()
        self.app.countdown_var.set("0")
        self.assertEqual(self.app.state_label.cget("text"), "Idle")
        self.assertEqual(self.app.count_label.cget("text"), "1 action")
        self.app.play()
        self.root.update()
        self.assertEqual(self.app.state_label.cget("text"), "Playing")
        self.app.play()  # second press is ignored
        self.app._hotkey_from_hook("stop")
        self.app.player.join(2)
        for _ in range(10):
            self.root.update()
            self.root.after(25)
        self.assertEqual(self.app.state_label.cget("text"), "Idle")

    def test_record_replaces_macro_and_undo_restores_it(self):
        self.load(2)
        self.app.path = str(self.dir / "old.json")
        self.app.toggle_record()
        self.assertEqual(self.app.state_label.cget("text"), "Recording")
        self.app.recorder.key(0x41, 0x1E, False, True, now=self.app.recorder._last + 0.05)
        self.app.recorder.key(0x41, 0x1E, False, False, now=self.app.recorder._last + 0.05)
        self.app.toggle_record()
        self.assertEqual([a.type for a in self.app.actions], ["delay", "key down", "delay", "key up"])
        self.assertIsNone(self.app.path)  # Save must not overwrite old.json
        self.app.undo()
        self.assertEqual(self.delays(), [0, 1])

    def test_empty_recording_keeps_macro(self):
        self.load(2)
        self.app.toggle_record()
        self.app.toggle_record()
        self.assertEqual(len(self.app.actions), 2)
        self.assertFalse(self.app.undo_stack)

    def test_hotkey_capture_changes_key_and_rejects_clashes(self):
        self.app._begin_capture("play")
        self.assertTrue(self.app.router.capturing)
        self.app.router.handle_key(0x75, 0x3F, 0)  # F6
        self.app._poll()
        self.assertEqual(self.app.settings["hotkey_play"], "F6")
        self.assertEqual(self.app.router.hotkeys[0x75], "play")
        self.assertNotIn(0x78, self.app.router.hotkeys)
        self.assertEqual(self.app.play_button.cget("text"), "Play (F6)")
        saved = json.loads((self.dir / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["hotkey_play"], "F6")

        self.app._begin_capture("stop")
        self.app.router.handle_key(0x75, 0x3F, 0)  # F6 is taken
        self.app._poll()
        self.showerror.assert_called_once()
        self.assertEqual(self.app.settings["hotkey_stop"], "F10")

        self.app._begin_capture("stop")
        self.app.router.handle_key(0x1B, 0x01, 0)  # Esc cancels
        self.app._poll()
        self.assertEqual(self.app.settings["hotkey_stop"], "F10")
        self.assertEqual(self.app.hotkey_buttons["stop"].cget("text"), "F10")

    def test_play_button_counts_down_and_stop_cancels(self):
        self.app.actions = [Action("delay", delay_ms=60000)]
        self.app._refresh()
        self.app.countdown_var.set("2")
        self.app.play()
        self.assertEqual(self.app.state_label.cget("text"), "Starting in 2")
        self.assertFalse(self.app.player.playing)
        self.app.play()  # a second press while counting down is ignored
        self.app._hotkey_from_hook("stop")
        self.app._poll()
        self.assertIsNone(self.app._countdown_id)
        self.assertEqual(self.app.state_label.cget("text"), "Idle")
        self.assertFalse(self.app.player.playing)

    def test_countdown_finishes_into_playback(self):
        self.app.actions = [Action("delay", delay_ms=60000)]
        self.app._refresh()
        self.app.countdown_var.set("1")
        self.app.play()
        self.app._tick_countdown(0, (1, 1.0, 0.0))  # what the timer calls when it reaches zero
        self.root.update()
        self.assertTrue(self.app.player.playing)
        self.assertEqual(self.app.state_label.cget("text"), "Playing")
        self.app.stop()
        self.app.player.join(2)

    def test_hotkey_play_skips_the_countdown(self):
        self.app.actions = [Action("delay", delay_ms=60000)]
        self.app._refresh()
        self.app.countdown_var.set("5")
        self.app._hotkey_from_hook("play")
        self.app._poll()
        self.assertTrue(self.app.player.playing)
        self.app.stop()
        self.app.player.join(2)

    def test_bad_countdown_is_reported(self):
        self.load(1)
        self.app.countdown_var.set("11")
        self.app.play()
        self.assertFalse(self.app.player.playing)
        self.showerror.assert_called_once()

    def test_progress_highlights_the_playing_row(self):
        self.load(3)
        self.app.player.loop, self.app.player.step = 2, 1
        self.app._show_progress()
        self.assertIn("current", self.app.tree.item("1", "tags"))
        self.assertIn("step 2 of 3", self.app.progress_label.cget("text"))
        self.app._mark_current(None)
        self.assertEqual(list(self.app.tree.item("1", "tags")), ["delay"])

    def test_open_and_save_fill_recent_list(self):
        first, second = self.dir / "a.json", self.dir / "b.json"
        self.load(2)
        with mock.patch.object(app_module.filedialog, "asksaveasfilename", return_value=str(first)):
            self.app.save_as()
        with mock.patch.object(app_module.filedialog, "asksaveasfilename", return_value=str(second)):
            self.app.save_as()
        recent = self.app.settings["recent"]
        self.assertEqual([Path(p).name for p in recent], ["b.json", "a.json"])
        self.assertTrue(self.app.open_path(recent[1]))
        self.assertEqual(Path(self.app.settings["recent"][0]).name, "a.json")
        saved = json.loads((self.dir / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(len(saved["recent"]), 2)

    def test_missing_recent_file_is_dropped(self):
        gone = str(self.dir / "gone.json")
        self.app.settings["recent"] = [gone]
        self.assertFalse(self.app.open_path(gone, confirm=False))
        self.assertEqual(self.app.settings["recent"], [])
        self.showerror.assert_called_once()

    def test_new_macro_clears_after_confirm(self):
        self.load(3)
        self.app.dirty = False
        self.app.new_macro()
        self.assertEqual(self.app.actions, [])
        self.root.update()
        self.assertTrue(self.app.empty_label.winfo_ismapped())
        self.assertIsNone(self.app.path)

    def test_window_options_saved(self):
        self.app.topmost_var.set(True)
        self.app._topmost_toggled()
        self.assertTrue(self.root.attributes("-topmost"))
        self.app.minimize_var.set(True)
        self.app.countdown_var.set("4")
        self.app._save_settings()
        saved = json.loads((self.dir / "config.json").read_text(encoding="utf-8"))
        self.assertEqual((saved["always_on_top"], saved["minimize_on_play"], saved["countdown"]), (True, True, 4))
        self.app.topmost_var.set(False)
        self.app._topmost_toggled()


if __name__ == "__main__":
    unittest.main()
