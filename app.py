"""Macro Recorder GUI. Run this file, or build it into a single exe (see README)."""
import ctypes
import gc
import os
import queue
import sys
import tkinter as tk
import traceback
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, ttk

import engine
from macro import (Action, BUTTONS, BUTTON_TYPES, KEY_NAMES, KEY_TYPES, POINT_TYPES, RECENT_LIMIT, TYPES, edit_cell,
                   format_delay, format_length, key_action, key_info, key_name, load_macro, load_settings,
                   macro_length_ms, move_rows, parse_coord, parse_countdown, parse_delay, parse_loops,
                   parse_percent, parse_speed, row_values, save_macro, save_settings, tidy)

APP_NAME = "Macro Recorder"
APP_VERSION = "2.0.0"
BG, PANEL, FIELD, BORDER = "#15171c", "#1e2128", "#2a2e37", "#454b58"
FG, MUTED, ACCENT, SELECT = "#e8eaee", "#a4abb8", "#3f7fe8", "#2f5da8"
RED, GREEN, AMBER = "#f2666b", "#46c28a", "#e8b54a"
HEADER = "#101216"
RECORD_BG, RECORD_ACTIVE, PLAY_BG, PLAY_ACTIVE = "#c8474d", "#d95a60", "#23925f", "#2aa76e"
# Text colour per action type in the table. Foreground only: a tag background would hide the selection.
TYPE_COLORS = {"key down": "#9cc1ff", "key up": "#9cc1ff", "mouse down": AMBER, "mouse up": AMBER,
               "move": "#c3b5ff", "delay": MUTED}
STATE_STYLES = {"Idle": ("#2a2e37", FG), "Recording": (RECORD_BG, "#ffffff"), "Playing": (PLAY_BG, "#ffffff"),
                "Starting": ("#8a6a1f", "#ffffff")}
VK_ESCAPE = 0x1B
UNDO_LIMIT = 200
GC_INTERVAL_MS = 30000
COLUMNS = (("num", "#", 50, "e"), ("type", "Type", 100, "w"), ("key", "Key/Button", 110, "w"),
           ("x", "X", 70, "e"), ("y", "Y", 70, "e"), ("to_x", "To X", 70, "e"), ("to_y", "To Y", 70, "e"),
           ("duration", "Duration (ms)", 105, "e"), ("delay", "Delay (ms)", 95, "e"))
INSERT_KINDS = ("Key press", "Key down", "Key up", "Mouse click", "Mouse down", "Mouse up", "Mouse move", "Delay")
MENU_COLORS = dict(bg=FIELD, fg=FG, activebackground=SELECT, activeforeground="#ffffff")
HOTKEY_LABELS = (("record", "Record"), ("play", "Play"), ("stop", "Stop"))


def config_path():
    """Next to the script when run from source. For the exe, a config.json beside it means a
    portable copy; otherwise settings go to %APPDATA%, since an installed app can't write to its folder."""
    if not getattr(sys, "frozen", False):
        return Path(__file__).resolve().parent / "config.json"
    portable = Path(sys.executable).parent / "config.json"
    if portable.exists():
        return portable
    # Not just "Macro Recorder": other macro apps already use that folder name.
    folder = Path(os.environ.get("APPDATA") or Path.home()) / "MacroRecorder-fwsoapy"
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        return portable
    return folder / "config.json"


def resource_path(name):
    """A bundled file: inside the PyInstaller folder when frozen, else next to this script."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / name


def macros_folder():
    """Where file dialogs start the first time: Documents\\Macro Recorder, made on first use."""
    folder = Path.home() / "Documents" / APP_NAME
    try:
        folder.mkdir(parents=True, exist_ok=True)
        return str(folder)
    except OSError:
        return str(Path.home())


def dark_title_bar(window):
    """Windows 10 2004+ only. Older versions keep a light title bar."""
    try:
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(ctypes.c_int(1)), 4)
    except OSError:
        pass


def apply_theme(root):
    root.configure(bg=BG)
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", background=BG, foreground=FG, fieldbackground=FIELD, bordercolor=BORDER,
                    lightcolor=BORDER, darkcolor=BORDER, troughcolor=PANEL, focuscolor=ACCENT,
                    insertcolor=FG, selectbackground=SELECT, selectforeground=FG, arrowcolor=FG)
    style.map(".", foreground=[("disabled", MUTED)])
    style.configure("TFrame", background=BG)
    style.configure("TLabelframe", background=BG, bordercolor=BORDER)
    style.configure("TLabelframe.Label", background=BG, foreground=MUTED)
    style.configure("Muted.TLabel", foreground=MUTED)
    style.configure("Header.TFrame", background=HEADER)
    style.configure("Header.TLabel", background=HEADER)
    style.configure("Title.TLabel", background=HEADER, font=("Segoe UI Semibold", 12))
    style.configure("File.TLabel", background=HEADER, foreground=MUTED)
    style.configure("Header.TButton", background=HEADER, bordercolor=HEADER, lightcolor=HEADER, darkcolor=HEADER,
                    padding=(10, 4))
    style.map("Header.TButton", background=[("pressed", BORDER), ("active", FIELD)])
    style.configure("Header.TMenubutton", background=HEADER, bordercolor=HEADER, lightcolor=HEADER,
                    darkcolor=HEADER, foreground=FG, padding=(10, 4), arrowcolor=MUTED)
    style.map("Header.TMenubutton", background=[("pressed", BORDER), ("active", FIELD)])
    big = ("Segoe UI Semibold", 11)
    style.configure("Record.TButton", background=RECORD_BG, foreground="#ffffff", font=big, padding=(18, 9))
    style.map("Record.TButton", background=[("pressed", RECORD_BG), ("active", RECORD_ACTIVE)])
    style.configure("Play.TButton", background=PLAY_BG, foreground="#ffffff", font=big, padding=(18, 9))
    style.map("Play.TButton", background=[("disabled", PANEL), ("pressed", PLAY_BG), ("active", PLAY_ACTIVE)])
    style.configure("Big.TButton", font=big, padding=(18, 9))
    style.configure("Side.TLabelframe", background=BG, bordercolor=BORDER, padding=10)
    style.configure("Side.TLabelframe.Label", background=BG, foreground=MUTED, font=("Segoe UI Semibold", 9))
    style.configure("Horizontal.TProgressbar", troughcolor=FIELD, background=PLAY_BG, bordercolor=FIELD,
                    lightcolor=PLAY_BG, darkcolor=PLAY_BG, thickness=6)
    style.configure("Status.TFrame", background=PANEL)
    style.configure("Status.TLabel", background=PANEL)
    style.configure("TButton", background=FIELD, padding=(10, 5))
    style.map("TButton", background=[("disabled", PANEL), ("pressed", BORDER), ("active", BORDER)])
    style.configure("Accent.TButton", background=ACCENT, foreground="#ffffff")
    style.map("Accent.TButton", background=[("pressed", SELECT), ("active", "#5590ee")])
    style.configure("TCheckbutton", background=BG, indicatorbackground=FIELD, indicatorforeground=FG)
    style.map("TCheckbutton", background=[("active", BG)], indicatorbackground=[("selected", ACCENT)])
    style.configure("TRadiobutton", background=BG, indicatorbackground=FIELD, indicatorforeground=FG)
    style.map("TRadiobutton", background=[("active", BG)], indicatorbackground=[("selected", ACCENT)])
    for name in ("TEntry", "TSpinbox", "TCombobox"):
        style.configure(name, fieldbackground=FIELD, foreground=FG, background=FIELD)
        style.map(name, fieldbackground=[("readonly", FIELD)], foreground=[("readonly", FG)],
                  bordercolor=[("focus", ACCENT)], selectbackground=[("readonly", FIELD)])
    style.configure("Vertical.TScrollbar", background=FIELD, arrowcolor=FG)
    style.map("Vertical.TScrollbar", background=[("active", BORDER)])
    linespace = tkfont.nametofont("TkDefaultFont").metrics("linespace")
    style.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=FG, rowheight=linespace + 6)
    style.map("Treeview", background=[("selected", SELECT)], foreground=[("selected", "#ffffff")])
    style.configure("Treeview.Heading", background=FIELD, foreground=FG, relief="flat", padding=4)
    style.map("Treeview.Heading", background=[("active", BORDER)])
    root.option_add("*TCombobox*Listbox.background", FIELD)
    root.option_add("*TCombobox*Listbox.foreground", FG)
    root.option_add("*TCombobox*Listbox.selectBackground", SELECT)


class App:
    def __init__(self, root, settings_path=None):
        self.root = root
        self.settings_path = settings_path or config_path()
        self.settings, warning = load_settings(self.settings_path)
        self.actions = []
        self.undo_stack = []
        self.path = None
        self.dirty = False
        self.note = ""
        self._editor = None
        self._editor_cancelled = False
        self._capture_target = None
        self._shown_count = None
        self._menu = None
        self.events = queue.Queue()  # tkinter is not thread safe, so background threads post here

        self.recorder = engine.Recorder()
        self.player = engine.Player(on_done=lambda error: self.events.put(("done", error)))
        self.router = engine.InputRouter(self.recorder, self._hotkey_from_hook,
                                         lambda vk: self.events.put(("capture", vk)),
                                         lambda text: self.events.put(("hook_error", text)))

        self._countdown_id = None
        self._minimized_for_play = False
        self._current_row = None

        root.title(APP_NAME)
        root.geometry("1140x720")
        root.minsize(940, 580)
        try:
            root.iconbitmap(default=str(resource_path("icon.ico")))
        except tk.TclError:
            pass  # running from source without the icon: Tk's default is fine
        root.report_callback_exception = self._report_exception
        root.protocol("WM_DELETE_WINDOW", self.close)
        apply_theme(root)
        dark_title_bar(root)
        self._build_ui()
        self._apply_hotkeys()
        self._refresh()
        root.attributes("-topmost", self.settings["always_on_top"])
        if warning:
            self._error(warning)
        try:
            self.router.start_keyboard()
        except OSError as e:
            self._error(f"Global hotkeys and keyboard recording are unavailable.\n\n{e}")
        self._poll()
        # Python's automatic GC can run on the hook or player thread, where it would pause input
        # and run tkinter finalizers off the Tk thread. Collect on this thread instead.
        gc.disable()
        self._collect_garbage()

    def _collect_garbage(self):
        gc.collect()
        self._gc_id = self.root.after(GC_INTERVAL_MS, self._collect_garbage)

    # ----- layout -----

    def _build_ui(self):
        s = self.settings
        self.loops_var = tk.StringVar(value=str(s["loops"]))
        self.speed_var = tk.StringVar(value=str(s["speed"]))
        self.random_var = tk.BooleanVar(value=s["random_delay"])
        self.percent_var = tk.StringVar(value=format_delay(s["random_percent"]))
        self.countdown_var = tk.StringVar(value=str(s["countdown"]))
        self.record_mouse_var = tk.BooleanVar(value=s["record_mouse"])
        self.record_keyboard_var = tk.BooleanVar(value=s["record_keyboard"])
        self.admin_var = tk.BooleanVar(value=s["run_as_admin"])
        self.topmost_var = tk.BooleanVar(value=s["always_on_top"])
        self.minimize_var = tk.BooleanVar(value=s["minimize_on_play"])
        self.set_delay_var = tk.StringVar(value="50")

        # Header: name, current file, and file actions.
        header = ttk.Frame(self.root, style="Header.TFrame", padding=(14, 8))
        header.pack(fill="x")
        ttk.Label(header, text="⏺", style="Header.TLabel", foreground=RED,
                  font=("Segoe UI Symbol", 14)).pack(side="left")
        ttk.Label(header, text=APP_NAME, style="Title.TLabel").pack(side="left", padx=(6, 0))
        self.file_label = ttk.Label(header, style="File.TLabel")
        self.file_label.pack(side="left", padx=(14, 0))
        ttk.Button(header, text="Save As", style="Header.TButton", command=self.save_as).pack(side="right")
        ttk.Button(header, text="Save", style="Header.TButton", command=self.save).pack(side="right")
        self.recent_button = ttk.Menubutton(header, text="Recent", style="Header.TMenubutton")
        self.recent_menu = tk.Menu(self.recent_button, tearoff=0, postcommand=self._fill_recent_menu, **MENU_COLORS)
        self.recent_button["menu"] = self.recent_menu
        self.recent_button.pack(side="right")
        ttk.Button(header, text="Open", style="Header.TButton", command=self.open).pack(side="right")
        ttk.Button(header, text="New", style="Header.TButton", command=self.new_macro).pack(side="right")

        # Transport: the three big buttons, then live state and progress.
        transport = ttk.Frame(self.root, padding=(14, 12, 14, 10))
        transport.pack(fill="x")
        self.record_button = ttk.Button(transport, style="Record.TButton", command=self.toggle_record)
        self.record_button.pack(side="left")
        self.play_button = ttk.Button(transport, style="Play.TButton", command=self.play)
        self.play_button.pack(side="left", padx=(8, 0))
        self.stop_button = ttk.Button(transport, style="Big.TButton", command=self.stop)
        self.stop_button.pack(side="left", padx=(8, 0))
        live = ttk.Frame(transport)
        live.pack(side="left", fill="x", expand=True, padx=(18, 0))
        top_line = ttk.Frame(live)
        top_line.pack(fill="x")
        self.state_label = tk.Label(top_line, font=("Segoe UI Semibold", 10), padx=10, pady=2, bd=0)
        self.state_label.pack(side="left")
        self.progress_label = ttk.Label(top_line, style="Muted.TLabel")
        self.progress_label.pack(side="left", padx=(10, 0))
        self.progress = ttk.Progressbar(live, mode="determinate", maximum=1000)
        self.progress.pack(fill="x", pady=(8, 0))

        # Packed before the body so it stays visible when the window shrinks.
        status = ttk.Frame(self.root, style="Status.TFrame", padding=(14, 5))
        status.pack(side="bottom", fill="x")
        self.count_label = ttk.Label(status, style="Status.TLabel")
        self.count_label.pack(side="left")
        self.length_label = ttk.Label(status, style="Status.TLabel", foreground=MUTED)
        self.length_label.pack(side="left", padx=(8, 0))
        self.note_label = ttk.Label(status, style="Status.TLabel", foreground=AMBER)
        self.note_label.pack(side="left", padx=(16, 0))
        ttk.Label(status, style="Status.TLabel", foreground=MUTED,
                  text=f"v{APP_VERSION}  ·  {'Admin' if engine.is_admin() else 'Not admin'}").pack(side="right")

        body = ttk.Frame(self.root, padding=(14, 0, 14, 8))
        body.pack(fill="both", expand=True)
        self._build_side_panel(body)

        main = ttk.Frame(body)
        main.pack(side="left", fill="both", expand=True)
        edit = ttk.Frame(main, padding=(0, 8, 0, 0))
        edit.pack(side="bottom", fill="x")
        for text, command in (("Insert…", self.insert_dialog), ("Delete", self.delete_selected),
                              ("Duplicate", self.duplicate_selected), ("Move up", lambda: self.move_selected(-1)),
                              ("Move down", lambda: self.move_selected(1)), ("Undo", self.undo)):
            ttk.Button(edit, text=text, command=command).pack(side="left", padx=(0, 6))
        ttk.Button(edit, text="Set delays", command=self.set_delay_selected).pack(side="right")
        ttk.Label(edit, text="ms", style="Muted.TLabel").pack(side="right", padx=(4, 6))
        ttk.Entry(edit, width=7, textvariable=self.set_delay_var).pack(side="right")

        table = ttk.Frame(main)
        table.pack(fill="both", expand=True)
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(table, columns=[c[0] for c in COLUMNS], show="headings", selectmode="extended")
        for name, title, width, anchor in COLUMNS:
            self.tree.heading(name, text=title, anchor=anchor)
            self.tree.column(name, width=width, anchor=anchor, stretch=name == "key")
        for action_type, color in TYPE_COLORS.items():
            self.tree.tag_configure(action_type, foreground=color)
        self._bold = tkfont.nametofont("TkDefaultFont").copy()  # kept on self: Tk drops unreferenced fonts
        self._bold.configure(weight="bold")
        self.tree.tag_configure("current", foreground=GREEN, font=self._bold)
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.scrollbar = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=self._on_scroll)
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<Button-1>", lambda e: self._finish_edit(), add=True)
        self.tree.bind("<Button-3>", self._on_right_click)
        self.tree.bind("<Delete>", lambda e: self.delete_selected())
        self.tree.bind("<Control-z>", lambda e: self.undo())
        self.tree.bind("<Control-d>", lambda e: self.duplicate_selected())
        self.tree.bind("<Control-a>", lambda e: self.tree.selection_set(self.tree.get_children()))
        self.root.bind("<Control-s>", lambda e: self.save())
        self.root.bind("<Control-o>", lambda e: self.open())
        self.root.bind("<Control-n>", lambda e: self.new_macro())
        self.empty_label = ttk.Label(self.tree, background=PANEL, foreground=MUTED, justify="center",
                                     font=("Segoe UI", 11))

    def _build_side_panel(self, parent):
        side = ttk.Frame(parent, width=290)
        side.pack(side="right", fill="y", padx=(12, 0))
        side.pack_propagate(False)

        box = ttk.LabelFrame(side, text="PLAYBACK", style="Side.TLabelframe")
        box.pack(fill="x")
        box.columnconfigure(2, weight=1)
        rows = (("Loops", ttk.Spinbox(box, from_=0, to=1000000, width=7, textvariable=self.loops_var), "0 = forever"),
                ("Speed", ttk.Spinbox(box, from_=0.1, to=10.0, increment=0.1, width=7, textvariable=self.speed_var),
                 "×, 0.1 to 10"),
                ("Countdown", ttk.Spinbox(box, from_=0, to=10, width=7, textvariable=self.countdown_var),
                 "s, Play button only"))
        for row, (label, widget, hint) in enumerate(rows):
            pad = (0 if row == 0 else 6, 0)
            ttk.Label(box, text=label).grid(row=row, column=0, sticky="w", pady=pad)
            widget.grid(row=row, column=1, padx=8, pady=pad)
            ttk.Label(box, text=hint, style="Muted.TLabel").grid(row=row, column=2, sticky="w", pady=pad)
        ttk.Checkbutton(box, text="Random delay variation", variable=self.random_var,
                        command=self._save_settings).grid(row=3, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Label(box, text="Up to").grid(row=4, column=0, sticky="w", pady=(4, 0))
        ttk.Entry(box, width=8, textvariable=self.percent_var).grid(row=4, column=1, padx=8, pady=(4, 0))
        ttk.Label(box, text="% either way", style="Muted.TLabel").grid(row=4, column=2, sticky="w", pady=(4, 0))

        box = ttk.LabelFrame(side, text="RECORDING", style="Side.TLabelframe")
        box.pack(fill="x", pady=(10, 0))
        ttk.Checkbutton(box, text="Record mouse movement", variable=self.record_mouse_var,
                        command=self._save_settings).pack(anchor="w")
        ttk.Checkbutton(box, text="Record keyboard", variable=self.record_keyboard_var,
                        command=self._save_settings).pack(anchor="w", pady=(6, 0))

        box = ttk.LabelFrame(side, text="HOTKEYS  ·  CLICK TO CHANGE", style="Side.TLabelframe")
        box.pack(fill="x", pady=(10, 0))
        box.columnconfigure(1, weight=1)
        self.hotkey_buttons = {}
        for row, (action, label) in enumerate(HOTKEY_LABELS):
            ttk.Label(box, text=label).grid(row=row, column=0, sticky="w", pady=(0 if row == 0 else 4, 0))
            button = ttk.Button(box, command=lambda a=action: self._begin_capture(a))
            button.grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=(0 if row == 0 else 4, 0))
            self.hotkey_buttons[action] = button

        box = ttk.LabelFrame(side, text="WINDOW", style="Side.TLabelframe")
        box.pack(fill="x", pady=(10, 0))
        ttk.Checkbutton(box, text="Always on top", variable=self.topmost_var,
                        command=self._topmost_toggled).pack(anchor="w")
        ttk.Checkbutton(box, text="Minimize while playing", variable=self.minimize_var,
                        command=self._save_settings).pack(anchor="w", pady=(6, 0))
        ttk.Checkbutton(box, text="Ask for admin rights on launch", variable=self.admin_var,
                        command=self._admin_toggled).pack(anchor="w", pady=(6, 0))

    def _on_scroll(self, first, last):
        self.scrollbar.set(first, last)
        self._finish_edit()  # the cell editor sits at a fixed position, so it can't follow the scroll

    # ----- state display -----

    def _set_note(self, text):
        self.note = text
        self.note_label.configure(text=text)

    def _update_status(self):
        if self.recorder.active:
            state, count = "Recording", len(self.recorder.actions)
        elif self.player.playing:
            state, count = "Playing", len(self.actions)
        elif self._countdown_id:
            state, count = "Starting", len(self.actions)
        else:
            state, count = "Idle", len(self.actions)
        background, foreground = STATE_STYLES[state]
        self.state_label.configure(text=state, bg=background, fg=foreground)
        self.count_label.configure(text=f"{count} action{'' if count == 1 else 's'}")
        length = macro_length_ms(self.actions)
        self.length_label.configure(text=f"·  {format_length(length)} per loop" if self.actions else "")
        self.record_button.configure(text=f"{'Stop recording' if self.recorder.active else 'Record'} "
                                          f"({self.settings['hotkey_record']})")
        self.play_button.configure(text=f"Play ({self.settings['hotkey_play']})")
        self.stop_button.configure(text=f"Stop ({self.settings['hotkey_stop']})")
        name = Path(self.path).name if self.path else "Untitled"
        self.file_label.configure(text=f"{name}{'  •  unsaved changes' if self.dirty else ''}")
        self.root.title(f"{'*' if self.dirty else ''}{name} - {APP_NAME}")
        if not self.player.playing and not self._countdown_id and not self.recorder.active:
            self.progress_label.configure(text=self._idle_hint())
            self.progress.configure(value=0)

    def _idle_hint(self):
        if not self.actions:
            return f"Press {self.settings['hotkey_record']} anywhere to start recording."
        return (f"Press {self.settings['hotkey_play']} in your game to play, "
                f"{self.settings['hotkey_stop']} to stop.")

    def _show_progress(self):
        """Loop and step while playing, and highlight the row being played."""
        player, total = self.player, len(self.actions)
        loops = self.loops_var.get().strip()
        loop_text = f"Loop {player.loop}" + ("" if loops == "0" else f" of {loops}")
        self.progress_label.configure(text=f"{loop_text}  ·  step {min(player.step + 1, total)} of {total}")
        self.progress.configure(value=1000 * (player.step + 1) / max(total, 1))
        self._mark_current(player.step if player.step < total else None)

    def _mark_current(self, index):
        if index == self._current_row:
            return
        for row, on in ((self._current_row, False), (index, True)):
            if row is not None and row < len(self.actions) and self.tree.exists(str(row)):
                tags = ("current",) if on else (self.actions[row].type,)  # alone, so its colour wins
                self.tree.item(str(row), tags=tags)
        self._current_row = index
        if index is not None and self.tree.exists(str(index)):
            self.tree.see(str(index))

    def _refresh(self, select=()):
        """Rebuild the table from self.actions, keeping the scroll position."""
        position = self.tree.yview()[0]
        self.tree.delete(*self.tree.get_children())
        for i, action in enumerate(self.actions):
            self.tree.insert("", "end", iid=str(i), values=row_values(i, action), tags=(action.type,))
        self.tree.yview_moveto(position)
        if select:
            self.tree.selection_set([str(i) for i in select])
            self.tree.see(str(select[0]))
        self._current_row = None
        if self.actions:
            self.empty_label.place_forget()
        else:
            self.empty_label.configure(
                text=f"No actions yet\n\nPress {self.settings['hotkey_record']} (or the Record button), "
                     f"do what you want repeated,\nthen press {self.settings['hotkey_record']} again.\n\n"
                     "Or right-click here to add steps by hand.")
            self.empty_label.place(relx=0.5, rely=0.5, anchor="center")
        self._update_status()

    def _commit(self, new_actions, select=(), rows=None):
        """Apply an edit with undo. rows lists changed indices when row order and count are unchanged."""
        self.undo_stack.append(self.actions)
        del self.undo_stack[:-UNDO_LIMIT]
        self.actions = new_actions
        self.dirty = True
        if rows is None:
            self._refresh(select)
        else:
            for i in rows:
                self.tree.item(str(i), values=row_values(i, new_actions[i]), tags=(new_actions[i].type,))
            self._current_row = None
            self._update_status()

    def _selected(self):
        return sorted(int(i) for i in self.tree.selection())

    def _selected_or_note(self):
        selected = self._selected()
        if not selected:
            self._set_note("Select one or more rows first.")
        return selected

    # ----- errors -----

    def _error(self, text):
        messagebox.showerror("Macro Recorder", text, parent=self.root)

    def _report_exception(self, exc_type, value, tb):
        traceback.print_exception(exc_type, value, tb)
        self._error(f"Unexpected error: {value}")

    # ----- background events -----

    def _hotkey_from_hook(self, action):
        if action == "stop":
            self.player.stop()  # directly from the hook thread, so a busy GUI can't delay it
        self.events.put(("hotkey", action))

    def _poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "hotkey":
                    {"record": self.toggle_record, "play": lambda: self.play(from_hotkey=True),
                     "stop": self._stop_playback}[value]()
                elif kind == "capture":
                    self._finish_capture(value)
                elif kind == "done":
                    self._mark_current(None)
                    if self._minimized_for_play:
                        self._minimized_for_play = False
                        self.root.deiconify()
                    self._update_status()
                    if value:
                        self._error(f"Playback stopped: {value}")
                elif kind == "hook_error":
                    self._set_note(f"Input hook error: {value}")
        except queue.Empty:
            pass
        if self.recorder.active and len(self.recorder.actions) != self._shown_count:
            self._shown_count = len(self.recorder.actions)
            self._update_status()
            self.progress_label.configure(text=f"{self._shown_count} events captured. "
                                               f"Press {self.settings['hotkey_record']} to finish.")
        elif self.player.playing:
            self._show_progress()
        self._poll_id = self.root.after(20, self._poll)

    # ----- record and play -----

    def toggle_record(self):
        self._finish_edit()
        if self.recorder.active:
            self.router.stop_mouse()
            recorded = self.recorder.stop()
            self._shown_count = None
            if recorded:
                self._commit(tidy(recorded))
                self.path = None  # so Save can't overwrite the old macro's file by accident
                self._set_note("Recording finished. Undo brings back the previous macro.")
            else:
                self._set_note("Nothing recorded. Kept the current macro.")
            self._update_status()
            return
        if self.player.playing:
            self._set_note("Stop playback before recording.")
            return
        self._cancel_capture()
        try:
            self.router.start_mouse()
        except OSError as e:
            self._error(f"Could not start recording.\n\n{e}")
            return
        self.recorder.start(self.record_mouse_var.get(), self.record_keyboard_var.get())
        self._set_note("")
        self._update_status()
        self.progress_label.configure(text=f"Recording. Press {self.settings['hotkey_record']} to finish.")

    def play(self, from_hotkey=False):
        """Start playback. From the window there is a countdown, so you can switch to your game;
        from the hotkey you are already there, so it starts at once."""
        self._finish_edit()
        if self.recorder.active or self.player.playing or self._countdown_id:
            self._set_note("Already recording." if self.recorder.active else "Already playing.")
            return
        if not self.actions:
            self._set_note("Nothing to play.")
            return
        try:
            loops = parse_loops(self.loops_var.get())
            speed = parse_speed(self.speed_var.get())
            percent = parse_percent(self.percent_var.get()) if self.random_var.get() else 0.0
            countdown = 0 if from_hotkey else parse_countdown(self.countdown_var.get())
        except ValueError as e:
            self._error(str(e))
            return
        self._save_settings()
        self._set_note("")
        if countdown:
            self._tick_countdown(countdown, (loops, speed, percent))
        else:
            self._start_playback(loops, speed, percent, minimize=not from_hotkey)

    def _tick_countdown(self, left, options):
        if left <= 0:
            self._countdown_id = None
            self._start_playback(*options, minimize=True)
            return
        self._countdown_id = self.root.after(1000, self._tick_countdown, left - 1, options)
        self._update_status()
        self.state_label.configure(text=f"Starting in {left}")
        self.progress_label.configure(text=f"Switch to your game. {self.settings['hotkey_stop']} cancels.")

    def _start_playback(self, loops, speed, percent, minimize):
        if minimize and self.minimize_var.get():
            self._minimized_for_play = True
            self.root.iconify()
        self.player.play(self.actions, loops, speed, percent)
        self._update_status()
        self._show_progress()

    def _cancel_countdown(self):
        if self._countdown_id:
            self.root.after_cancel(self._countdown_id)
            self._countdown_id = None
            self._set_note("Playback cancelled.")
            self._update_status()

    def _stop_playback(self):
        self._cancel_countdown()
        self.player.stop()

    def stop(self):
        if self.recorder.active:
            self.toggle_record()
        self._stop_playback()

    # ----- hotkeys -----

    def _apply_hotkeys(self):
        self.router.hotkeys = {key_info(self.settings[f"hotkey_{a}"])[1]: a for a, _ in HOTKEY_LABELS}
        for action, button in self.hotkey_buttons.items():
            button.configure(text=self.settings[f"hotkey_{action}"])
        self._update_status()

    def _begin_capture(self, action):
        if self.recorder.active or self.player.playing:
            self._set_note("Stop recording or playback before changing hotkeys.")
            return
        self._capture_target = action
        self.root.focus_set()  # otherwise pressing Space would click the focused button again
        self.hotkey_buttons[action].configure(text="Press a key...")
        self._set_note("Press the new hotkey, or Esc to cancel.")
        self.router.capturing = True

    def _cancel_capture(self):
        self.router.capturing = False
        self._capture_target = None
        self._apply_hotkeys()

    def _finish_capture(self, vk):
        action, self._capture_target = self._capture_target, None
        self._set_note("")
        if action is None or vk == VK_ESCAPE:
            self._apply_hotkeys()
            return
        taken = [a for other_vk, a in self.router.hotkeys.items() if other_vk == vk and a != action]
        if taken:
            self._apply_hotkeys()
            self._error(f"{key_name(vk)} is already the {taken[0]} hotkey.")
            return
        self.settings[f"hotkey_{action}"] = key_name(vk)
        self._apply_hotkeys()
        self._save_settings()
        self._refresh(self._selected())

    # ----- settings -----

    def _save_settings(self):
        s = self.settings
        for name, var, parse in (("loops", self.loops_var, parse_loops), ("speed", self.speed_var, parse_speed),
                                 ("random_percent", self.percent_var, parse_percent),
                                 ("countdown", self.countdown_var, parse_countdown)):
            try:
                s[name] = parse(var.get())
            except ValueError:
                pass  # keep the last good value; play() reports the bad one
        s["random_delay"] = self.random_var.get()
        s["record_mouse"] = self.record_mouse_var.get()
        s["record_keyboard"] = self.record_keyboard_var.get()
        s["run_as_admin"] = self.admin_var.get()
        s["always_on_top"] = self.topmost_var.get()
        s["minimize_on_play"] = self.minimize_var.get()
        try:
            save_settings(self.settings_path, s)
        except OSError as e:
            self._set_note(f"Could not save settings: {e}")

    def _topmost_toggled(self):
        self.root.attributes("-topmost", self.topmost_var.get())
        self._save_settings()

    def _admin_toggled(self):
        self._save_settings()
        if not self.admin_var.get() or engine.is_admin():
            return
        if messagebox.askyesno("Macro Recorder", "Restart now with admin rights?", parent=self.root):
            if self._confirm_discard():
                if engine.relaunch_as_admin():
                    self.shutdown()
                else:
                    self._set_note("Admin rights declined.")

    # ----- table editing -----

    def _on_double_click(self, event):
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        row, column_id = self.tree.identify_row(event.y), self.tree.identify_column(event.x)
        column = COLUMNS[int(column_id[1:]) - 1][0]
        index = int(row)
        action = self.actions[index]
        if column == "type":
            self._choice_menu(index, column, TYPES, event)
        elif column == "key" and action.type in BUTTON_TYPES:
            self._choice_menu(index, column, BUTTONS, event)
        elif column == "key" and action.type not in KEY_TYPES:
            self._set_note(f'A "{action.type}" action has no key or button.')
        elif column in ("x", "y") and action.type not in POINT_TYPES:
            self._set_note("X and Y only apply to mouse actions.")
        elif column in ("to_x", "to_y", "duration") and action.type != "move":
            self._set_note("To X, To Y and Duration only apply to mouse moves.")
        elif column == "delay" and action.type != "delay":
            self._set_note("Only delay rows have a delay. Right-click a row to add one.")
        elif column != "num":
            self._open_editor(row, column_id, index, column)
        return "break"

    def _choice_menu(self, index, column, choices, event):
        menu = tk.Menu(self.root, tearoff=0, **MENU_COLORS)
        for choice in choices:
            menu.add_command(label=choice, command=lambda c=choice: self._apply_cell(index, column, c))
        self._popup(menu, event)

    def _popup(self, menu, event):
        if self._menu:
            self._menu.destroy()  # the previous menu is finished by now; its command may run after tk_popup returns
        self._menu = menu
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _on_right_click(self, event):
        self._finish_edit()
        row = self.tree.identify_row(event.y)
        if row and row not in self.tree.selection():
            self.tree.selection_set(row)
        self.tree.focus_set()
        self._popup(self._context_menu(int(row) if row else None), event)

    def _context_menu(self, row):
        menu = tk.Menu(self.root, tearoff=0, **MENU_COLORS)
        places = (("Add below", row + 1), ("Add above", row)) if row is not None else (("Add", len(self.actions)),)
        for label, at in places:
            submenu = tk.Menu(menu, tearoff=0, **MENU_COLORS)
            for kind in INSERT_KINDS:
                submenu.add_command(label=kind, command=lambda k=kind, a=at: InsertDialog(self, k, a))
            menu.add_cascade(label=label, menu=submenu)
        if row is not None:
            menu.add_separator()
            for label, command in (("Duplicate selected", self.duplicate_selected),
                                   ("Move up", lambda: self.move_selected(-1)),
                                   ("Move down", lambda: self.move_selected(1)),
                                   ("Delete selected", self.delete_selected)):
                menu.add_command(label=label, command=command)
        return menu

    def _open_editor(self, row, column_id, index, column):
        self._finish_edit()
        self.tree.see(row)
        self.tree.update_idletasks()
        bbox = self.tree.bbox(row, column_id)
        if not bbox:
            return
        x, y, width, height = bbox
        current = self.tree.set(row, column)
        entry = ttk.Entry(self.tree, justify="right" if column != "key" else "left")
        entry.insert(0, current)
        entry.select_range(0, "end")
        entry.place(x=x, y=y, width=width, height=height)
        entry.focus_set()
        self._editor = (entry, index, column)
        entry.bind("<Return>", lambda e: self._finish_edit())
        entry.bind("<KP_Enter>", lambda e: self._finish_edit())
        entry.bind("<Escape>", lambda e: self._finish_edit(cancel=True))
        entry.bind("<FocusOut>", lambda e: self._finish_edit())

    def _finish_edit(self, cancel=False):
        if not self._editor:
            return
        entry, index, column = self._editor
        self._editor = None  # first, because destroying the entry fires FocusOut
        text = entry.get()
        entry.destroy()
        self.tree.focus_set()
        if not cancel:
            self._apply_cell(index, column, text)

    def _apply_cell(self, index, column, text):
        if index >= len(self.actions):
            return
        try:
            updated = edit_cell(self.actions[index], column, text)
        except ValueError as e:
            self._error(str(e))
            return
        if updated != self.actions[index]:
            actions = list(self.actions)
            actions[index] = updated
            self._commit(actions, rows=[index])

    def delete_selected(self):
        selected = self._selected_or_note()
        if selected:
            drop = set(selected)
            remaining = [a for i, a in enumerate(self.actions) if i not in drop]
            next_row = min(selected[0], len(remaining) - 1)
            self._commit(remaining, select=[next_row] if next_row >= 0 else ())

    def duplicate_selected(self):
        selected = self._selected_or_note()
        if selected:
            at = selected[-1] + 1
            copies = [self.actions[i] for i in selected]
            self._commit(self.actions[:at] + copies + self.actions[at:], select=range(at, at + len(copies)))

    def move_selected(self, delta):
        selected = self._selected_or_note()
        if selected:
            actions, moved = move_rows(self.actions, selected, delta)
            if moved != selected:
                self._commit(actions, select=moved)

    def set_delay_selected(self):
        if not self._selected_or_note():
            return
        selected = [i for i in self._selected() if self.actions[i].type == "delay"]
        if not selected:
            self._set_note("None of the selected rows are delays. Right-click a row to add one.")
            return
        try:
            delay = parse_delay(self.set_delay_var.get())
        except ValueError as e:
            self._error(str(e))
            return
        actions = list(self.actions)
        for i in selected:
            actions[i] = replace(actions[i], delay_ms=delay)
        self._commit(actions, rows=selected)
        self._set_note(f"Set {len(selected)} delay{'' if len(selected) == 1 else 's'} to {format_delay(delay)} ms.")

    def undo(self):
        self._finish_edit()
        if not self.undo_stack:
            self._set_note("Nothing to undo.")
            return
        self.actions = self.undo_stack.pop()
        self.dirty = True
        self._refresh()

    def _insert_position(self):
        selected = self._selected()
        return selected[-1] + 1 if selected else len(self.actions)

    def insert_actions(self, new_actions, at):
        self._commit(self.actions[:at] + new_actions + self.actions[at:], select=range(at, at + len(new_actions)))

    def insert_dialog(self):
        InsertDialog(self)

    # ----- files -----

    def new_macro(self):
        if self.recorder.active or self.player.playing:
            self._set_note("Stop recording or playback first.")
            return
        if not self._confirm_discard():
            return
        self.undo_stack.clear()
        self.actions, self.path, self.dirty = [], None, False
        self._set_note("")
        self._refresh()

    def _dialog_folder(self):
        recent = self.settings["recent"]
        return str(Path(recent[0]).parent) if recent and Path(recent[0]).parent.exists() else macros_folder()

    def open(self):
        if not self._confirm_discard():
            return
        path = filedialog.askopenfilename(parent=self.root, initialdir=self._dialog_folder(),
                                          filetypes=[("Macro files", "*.json"), ("All files", "*.*")])
        if path:
            self.open_path(path, confirm=False)

    def open_path(self, path, confirm=True):
        if self.recorder.active or self.player.playing:
            self._set_note("Stop recording or playback first.")
            return False
        if confirm and not self._confirm_discard():
            return False
        try:
            actions = load_macro(path)
        except (OSError, ValueError) as e:
            self._error(f"Could not open the macro.\n\n{e}")
            if not Path(path).exists():
                self._forget_recent(path)
            return False
        self.undo_stack.clear()
        self.actions, self.path, self.dirty = actions, str(path), False
        self._remember_recent(path)
        self._set_note("")
        self._refresh()
        return True

    def _remember_recent(self, path):
        path = str(Path(path).resolve())
        recent = [p for p in self.settings["recent"] if os.path.normcase(p) != os.path.normcase(path)]
        self.settings["recent"] = [path] + recent[:RECENT_LIMIT - 1]
        self._save_settings()

    def _forget_recent(self, path):
        self.settings["recent"] = [p for p in self.settings["recent"] if p != path]
        self._save_settings()

    def _fill_recent_menu(self):
        menu = self.recent_menu
        menu.delete(0, "end")
        if not self.settings["recent"]:
            menu.add_command(label="No recent macros", state="disabled")
            return
        for path in self.settings["recent"]:
            item = Path(path)
            menu.add_command(label=f"{item.name}    {item.parent}", command=lambda p=path: self.open_path(p))
        menu.add_separator()
        menu.add_command(label="Clear list", command=self._clear_recent)

    def _clear_recent(self):
        self.settings["recent"] = []
        self._save_settings()

    def save(self):
        return self._write(self.path) if self.path else self.save_as()

    def save_as(self):
        path = filedialog.asksaveasfilename(parent=self.root, defaultextension=".json",
                                            initialdir=self._dialog_folder(),
                                            filetypes=[("Macro files", "*.json"), ("All files", "*.*")])
        return self._write(path) if path else False

    def _write(self, path):
        try:
            save_macro(path, self.actions)
        except OSError as e:
            self._error(f"Could not save the macro.\n\n{e}")
            return False
        self.path, self.dirty = path, False
        self._remember_recent(path)
        self._set_note("Saved.")
        self._update_status()
        return True

    def _confirm_discard(self):
        """True if it's safe to replace the current macro."""
        if not self.dirty:
            return True
        answer = messagebox.askyesnocancel("Macro Recorder", "Save changes to the current macro first?",
                                           parent=self.root)
        return self.save() if answer else answer is False

    def close(self):
        if self.recorder.active:
            self.toggle_record()
        if self._confirm_discard():
            self.shutdown()

    def shutdown(self):
        self._cancel_countdown()
        self.player.stop()
        if self.player.playing:
            self.player.join(1)
        self._save_settings()
        self.router.stop()
        self.root.after_cancel(self._poll_id)
        self.root.after_cancel(self._gc_id)
        self.root.destroy()
        gc.collect()


class InsertDialog:
    """Modal form that adds actions at a row position (default: after the current selection)."""

    def __init__(self, app, kind="Key press", at=None):
        self.app = app
        self.at = app._insert_position() if at is None else at
        self.top = top = tk.Toplevel(app.root)
        top.title("Add action")
        top.configure(bg=BG)
        top.transient(app.root)
        top.resizable(False, False)
        dark_title_bar(top)

        x, y = 0, 0
        for action in reversed(app.actions[:self.at]):
            if action.type in POINT_TYPES:  # start where the cursor will be at this point in the macro
                x, y = (action.to_x, action.to_y) if action.to_x is not None else (action.x, action.y)
                break
        self.kind = tk.StringVar(value=kind)
        self.key = tk.StringVar(value="Space")
        self.button = tk.StringVar(value="left")
        self.x, self.y = tk.StringVar(value=str(x)), tk.StringVar(value=str(y))
        self.to_x, self.to_y = tk.StringVar(value=str(x)), tk.StringVar(value=str(y))
        self.duration = tk.StringVar(value="200")
        self.delay = tk.StringVar(value="50")
        self.hold = tk.StringVar(value="50")

        form = ttk.Frame(top, padding=14)
        form.pack()
        ttk.Label(form, text="Action").grid(row=0, column=0, sticky="w", pady=(0, 10), padx=(0, 10))
        kinds = ttk.Combobox(form, textvariable=self.kind, values=INSERT_KINDS, width=14, state="readonly")
        kinds.grid(row=0, column=1, sticky="ew", pady=(0, 10))
        kinds.bind("<<ComboboxSelected>>", lambda e: self._show_fields())
        self.rows = {}
        fields = (("key", "Key", ttk.Combobox(form, textvariable=self.key, values=KEY_NAMES, width=14)),
                  ("button", "Button", ttk.Combobox(form, textvariable=self.button, values=BUTTONS, width=14,
                                                    state="readonly")),
                  ("x", "X", ttk.Entry(form, textvariable=self.x, width=16)),
                  ("y", "Y", ttk.Entry(form, textvariable=self.y, width=16)),
                  ("to_x", "To X", ttk.Entry(form, textvariable=self.to_x, width=16)),
                  ("to_y", "To Y", ttk.Entry(form, textvariable=self.to_y, width=16)),
                  ("duration", "Duration (ms)", ttk.Entry(form, textvariable=self.duration, width=16)),
                  ("delay", "Delay (ms)", ttk.Entry(form, textvariable=self.delay, width=16)),
                  ("hold", "Hold for (ms), adds a delay row", ttk.Entry(form, textvariable=self.hold, width=16)))
        for row, (name, text, widget) in enumerate(fields, 1):
            label = ttk.Label(form, text=text)
            label.grid(row=row, column=0, sticky="w", pady=3, padx=(0, 10))
            widget.grid(row=row, column=1, sticky="ew", pady=3)
            self.rows[name] = (label, widget)
        buttons = ttk.Frame(form)
        buttons.grid(row=len(fields) + 1, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="Cancel", command=top.destroy).pack(side="right")
        ttk.Button(buttons, text="Add", style="Accent.TButton", command=self.submit).pack(side="right", padx=6)
        top.bind("<Return>", lambda e: self.submit())
        top.bind("<Escape>", lambda e: top.destroy())
        self._show_fields()
        top.update_idletasks()
        root = app.root
        top.geometry(f"+{root.winfo_rootx() + (root.winfo_width() - top.winfo_width()) // 2}"
                     f"+{root.winfo_rooty() + (root.winfo_height() - top.winfo_height()) // 2}")
        top.grab_set()
        self._focus_first_field()

    def _show_fields(self):
        kind = self.kind.get()
        visible = {"Key press": ("key", "hold"),
                   "Key down": ("key",), "Key up": ("key",),
                   "Mouse click": ("button", "x", "y", "hold"),
                   "Mouse down": ("button", "x", "y"), "Mouse up": ("button", "x", "y"),
                   "Mouse move": ("x", "y", "to_x", "to_y", "duration"),
                   "Delay": ("delay",)}[kind]
        for name, (label, widget) in self.rows.items():
            for item in (label, widget):
                item.grid() if name in visible else item.grid_remove()
        self.rows["x"][0].configure(text="From X" if kind == "Mouse move" else "X")
        self.rows["y"][0].configure(text="From Y" if kind == "Mouse move" else "Y")
        self._first_field = self.rows[visible[0]][1]
        self._first_field.focus_set()

    def _focus_first_field(self):
        # A menu command opens this dialog while the main window has focus, so Enter needs focus_force.
        self._first_field.focus_force()
        self._first_field.select_range(0, "end")

    def build(self):
        """Return the actions the form describes. Raises ValueError on bad input."""
        kind = self.kind.get()
        if kind == "Delay":
            return [Action("delay", delay_ms=parse_delay(self.delay.get()))]
        if kind == "Key press":
            name = self.key.get()
            return self._press(key_action("key down", name), key_action("key up", name))
        if kind in ("Key down", "Key up"):
            return [key_action(kind.lower(), self.key.get())]
        x, y, button = parse_coord(self.x.get()), parse_coord(self.y.get()), self.button.get()
        if kind == "Mouse move":
            return [Action("move", "", x, y, to_x=parse_coord(self.to_x.get()), to_y=parse_coord(self.to_y.get()),
                           duration_ms=parse_delay(self.duration.get()))]
        if kind == "Mouse click":
            return self._press(Action("mouse down", button, x, y), Action("mouse up", button, x, y))
        return [Action(kind.lower(), button, x, y)]

    def _press(self, down, up):
        hold = parse_delay(self.hold.get())
        return [down, Action("delay", delay_ms=hold), up] if hold else [down, up]

    def submit(self):
        try:
            actions = self.build()
        except ValueError as e:
            messagebox.showerror("Macro Recorder", str(e), parent=self.top)
            return
        self.top.destroy()
        self.app.insert_actions(actions, self.at)


def main():
    engine.enable_dpi_awareness()
    settings, _ = load_settings(config_path())
    if settings["run_as_admin"] and not engine.is_admin() and engine.relaunch_as_admin():
        return
    root = tk.Tk()
    app = App(root)
    if len(sys.argv) > 1 and Path(sys.argv[1]).is_file():
        app.open_path(sys.argv[1], confirm=False)
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # a windowed exe has no console, so show startup failures
        ctypes.windll.user32.MessageBoxW(None, f"{APP_NAME} failed to start:\n\n{e}", APP_NAME, 0x10)
        raise
