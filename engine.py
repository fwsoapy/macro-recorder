"""Win32 input: SendInput playback, low-level hooks, recorder and player. ctypes only."""
import ctypes
import os
import random
import subprocess
import sys
import threading
import time
from ctypes import wintypes

from macro import Action, BUTTON_TYPES, KEY_TYPES, key_name, move_points

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
winmm = ctypes.WinDLL("winmm")
shell32 = ctypes.WinDLL("shell32")

ULONG_PTR = ctypes.c_size_t
LRESULT = ctypes.c_ssize_t

WH_KEYBOARD_LL, WH_MOUSE_LL = 13, 14
WM_QUIT = 0x0012
WM_MOUSEMOVE = 0x0200
MOUSE_MESSAGES = {0x0201: ("left", True), 0x0202: ("left", False), 0x0204: ("right", True),
                  0x0205: ("right", False), 0x0207: ("middle", True), 0x0208: ("middle", False)}
LLKHF_EXTENDED, LLKHF_INJECTED, LLKHF_UP = 0x01, 0x10, 0x80
LLMHF_INJECTED = 0x01

INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_SCANCODE = 0x1, 0x2, 0x8
MOUSEEVENTF_MOVE, MOUSEEVENTF_ABSOLUTE, MOUSEEVENTF_VIRTUALDESK = 0x0001, 0x8000, 0x4000
MOUSE_FLAGS = {("left", True): 0x0002, ("left", False): 0x0004, ("right", True): 0x0008,
               ("right", False): 0x0010, ("middle", True): 0x0020, ("middle", False): 0x0040}
SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 76, 77, 78, 79
VK_PAUSE = 0x13


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", wintypes.POINT), ("mouseData", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wintypes.UINT
user32.SetWindowsHookExW.argtypes = (ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD)
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.CallNextHookEx.argtypes = (wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
user32.CallNextHookEx.restype = LRESULT
user32.UnhookWindowsHookEx.argtypes = (wintypes.HHOOK,)
user32.GetMessageW.argtypes = (ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT)
user32.GetMessageW.restype = ctypes.c_int
user32.PeekMessageW.argtypes = (ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT,
                                wintypes.UINT)
user32.PostThreadMessageW.argtypes = (wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
user32.WindowFromPoint.argtypes = (wintypes.POINT,)
user32.WindowFromPoint.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
user32.GetSystemMetrics.argtypes = (ctypes.c_int,)
kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
shell32.ShellExecuteW.argtypes = (wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                  wintypes.LPCWSTR, ctypes.c_int)
shell32.ShellExecuteW.restype = ctypes.c_ssize_t


def enable_dpi_awareness():
    """Keep recorded and sent coordinates in physical pixels on scaled displays."""
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # per monitor v2
    except (AttributeError, OSError):
        user32.SetProcessDPIAware()


def is_admin():
    try:
        return bool(shell32.IsUserAnAdmin())
    except OSError:
        return False


def relaunch_as_admin():
    """Start this program elevated. Returns False if the user declined the UAC prompt."""
    args = sys.argv[1:] if getattr(sys, "frozen", False) else [os.path.abspath(sys.argv[0])] + sys.argv[1:]
    return shell32.ShellExecuteW(None, "runas", sys.executable, subprocess.list2cmdline(args), None, 1) > 32


def _send(inp):
    if user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT)) != 1:
        raise OSError(f"SendInput failed (Windows error {ctypes.get_last_error()}).")


def send_key(vk, scan, ext, down):
    inp = INPUT(type=INPUT_KEYBOARD)
    flags = 0 if down else KEYEVENTF_KEYUP
    if scan and vk != VK_PAUSE:  # Pause has no single-byte scan code, so it only works by virtual key
        inp.u.ki.wScan = scan
        flags |= KEYEVENTF_SCANCODE | (KEYEVENTF_EXTENDEDKEY if ext else 0)
    else:
        inp.u.ki.wVk = vk
    inp.u.ki.dwFlags = flags
    _send(inp)


def send_mouse(x, y, button_flag=0):
    """Move to absolute (x, y) when given, and press or release a button in the same event."""
    inp = INPUT(type=INPUT_MOUSE)
    flags = button_flag
    if x is not None and y is not None:
        left, top = user32.GetSystemMetrics(SM_XVIRTUALSCREEN), user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        width, height = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN), user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
        # Round up: Windows maps back with floor(n * size / 65536), so this lands on the exact pixel.
        inp.u.mi.dx = min(65535, max(0, ((x - left) * 65536 + width - 1) // width))
        inp.u.mi.dy = min(65535, max(0, ((y - top) * 65536 + height - 1) // height))
        flags |= MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
    inp.u.mi.dwFlags = flags
    _send(inp)


def send_action(action):
    if action.type in KEY_TYPES:
        send_key(action.vk, action.scan, action.ext, action.type == "key down")
    elif action.type in BUTTON_TYPES:
        send_mouse(action.x, action.y, MOUSE_FLAGS[action.key, action.type == "mouse down"])
    elif action.type == "move":
        send_mouse(action.x, action.y)


def own_window_at(x, y):
    """True if the window under this point belongs to this process."""
    hwnd = user32.WindowFromPoint(wintypes.POINT(x, y))
    if not hwnd:
        return False
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value == os.getpid()


class HookThread(threading.Thread):
    """Runs one low-level hook on its own message loop. handler(wparam, lparam) returning True eats the event."""

    def __init__(self, hook_id, handler, on_error=None):
        super().__init__(daemon=True)
        self._hook_id, self._handler, self._on_error = hook_id, handler, on_error
        self._ready = threading.Event()
        self._failure = None
        self._thread_id = None
        self._proc = HOOKPROC(self._callback)  # must stay referenced while the hook is installed

    def _callback(self, code, wparam, lparam):
        if code == 0:
            try:
                if self._handler(wparam, lparam):
                    return 1
            except Exception as e:  # an exception must not break input for the whole desktop
                if self._on_error:
                    self._on_error(str(e))
        return user32.CallNextHookEx(None, code, wparam, lparam)

    def run(self):
        self._thread_id = kernel32.GetCurrentThreadId()
        msg = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)  # creates the queue PostThreadMessage needs
        hook = user32.SetWindowsHookExW(self._hook_id, self._proc, kernel32.GetModuleHandleW(None), 0)
        if not hook:
            self._failure = OSError(f"Could not install input hook (Windows error {ctypes.get_last_error()}).")
            self._ready.set()
            return
        self._ready.set()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                pass
        finally:
            user32.UnhookWindowsHookEx(hook)

    def start_and_wait(self):
        self.start()
        self._ready.wait()
        if self._failure:
            raise self._failure

    def stop(self):
        if self.is_alive():
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            self.join(1)


class Recorder:
    """Collects actions and the time gap before each. Called from hook threads."""
    MOVE_INTERVAL = 1 / 120

    def __init__(self):
        self.active = False
        self.actions = []
        self._lock = threading.Lock()
        self._last = self._last_move = 0.0
        self._held = set()
        self._moves = self._keyboard = True

    def start(self, moves=True, keyboard=True, now=None):
        with self._lock:
            self.actions = []
            self._held = set()
            self._moves, self._keyboard = moves, keyboard
            self._last = time.perf_counter() if now is None else now
            self._last_move = 0.0
            self.active = True

    def stop(self):
        with self._lock:
            self.active = False
            return self.actions

    def _add(self, action_type, key="", x=None, y=None, vk=0, scan=0, ext=False, now=None):
        now = time.perf_counter() if now is None else now
        self.actions.append(Action(action_type, key, x, y, round((now - self._last) * 1000, 1), vk, scan, ext))
        self._last = now

    def key(self, vk, scan, ext, down, now=None):
        with self._lock:
            if not self.active or not self._keyboard:
                return
            held = (vk, ext)
            if down and held in self._held:  # Windows auto-repeat; a held key stays held on playback
                return
            (self._held.add if down else self._held.discard)(held)
            self._add("key down" if down else "key up", key_name(vk, ext), vk=vk, scan=scan, ext=ext, now=now)

    def move(self, x, y, now=None):
        now = time.perf_counter() if now is None else now
        with self._lock:
            if not self.active or not self._moves or now - self._last_move < self.MOVE_INTERVAL:
                return
            self._last_move = now
            self._add("move", x=x, y=y, now=now)

    def button(self, button, down, x, y, now=None):
        with self._lock:
            if self.active:
                self._add("mouse down" if down else "mouse up", button, x, y, now=now)


class InputRouter:
    """Decides where each input event goes: hotkey, hotkey capture, or the recorder."""

    def __init__(self, recorder, on_hotkey, on_capture=None, on_error=None):
        self.recorder = recorder
        self.on_hotkey, self.on_capture, self.on_error = on_hotkey, on_capture, on_error
        self.hotkeys = {}  # vk -> action name
        self.capturing = False
        self.ignore_injected = True  # playback must not trigger hotkeys or get recorded
        self._held_hotkeys = set()
        self._keyboard_hook = None
        self._mouse_hook = None

    def handle_key(self, vk, scan, flags):
        if flags & LLKHF_INJECTED and self.ignore_injected:
            return
        down = not flags & LLKHF_UP
        ext = bool(flags & LLKHF_EXTENDED)
        if self.capturing and down:
            self.capturing = False
            self.on_capture(vk)
            return
        action = self.hotkeys.get(vk)
        if action:  # both edges are dropped here, so hotkeys never reach the recorder
            if down and vk not in self._held_hotkeys:
                self._held_hotkeys.add(vk)
                self.on_hotkey(action)
            elif not down:
                self._held_hotkeys.discard(vk)
            return
        self.recorder.key(vk, scan, ext, down)

    def handle_mouse(self, message, x, y, flags):
        if flags & LLMHF_INJECTED and self.ignore_injected:
            return
        if own_window_at(x, y):  # reaching for the app's Stop button isn't a macro step
            return
        if message == WM_MOUSEMOVE:
            self.recorder.move(x, y)
        elif message in MOUSE_MESSAGES:
            button, down = MOUSE_MESSAGES[message]
            self.recorder.button(button, down, x, y)

    def _keyboard_event(self, wparam, lparam):
        event = KBDLLHOOKSTRUCT.from_address(lparam)
        self.handle_key(event.vkCode, event.scanCode, event.flags)

    def _mouse_event(self, wparam, lparam):
        event = MSLLHOOKSTRUCT.from_address(lparam)
        self.handle_mouse(wparam, event.pt.x, event.pt.y, event.flags)

    def start_keyboard(self):
        self._keyboard_hook = HookThread(WH_KEYBOARD_LL, self._keyboard_event, self.on_error)
        self._keyboard_hook.start_and_wait()

    def start_mouse(self):
        """The mouse hook runs only while recording, so it can't add latency during games."""
        self._mouse_hook = HookThread(WH_MOUSE_LL, self._mouse_event, self.on_error)
        self._mouse_hook.start_and_wait()

    def stop_mouse(self):
        if self._mouse_hook:
            self._mouse_hook.stop()
            self._mouse_hook = None

    def stop(self):
        self.stop_mouse()
        if self._keyboard_hook:
            self._keyboard_hook.stop()
            self._keyboard_hook = None


class Player:
    """Plays actions on a background thread. stop() takes effect before the next input is sent."""

    def __init__(self, send=send_action, on_done=None):
        self._send = send
        self._on_done = on_done
        self._stop = threading.Event()
        self.playing = False
        # Progress, read by the GUI while playing. Plain ints, so reading them off-thread is safe.
        self.loop = 0
        self.step = 0

    def play(self, actions, loops=1, speed=1.0, jitter_percent=0.0):
        if self.playing:
            raise RuntimeError("Already playing.")
        self.playing = True
        self.loop, self.step = 1, 0
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        args=(list(actions), loops, speed, jitter_percent))
        self._thread.start()

    def stop(self):
        self._stop.set()

    def join(self, timeout=None):
        self._thread.join(timeout)

    def _sleep_until(self, deadline):
        """Wait on the stop event, then spin the last 2 ms for accuracy. False means stopped."""
        while not self._stop.is_set():
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                return True
            if remaining > 0.002:
                self._stop.wait(min(remaining - 0.002, 0.5))
            else:
                time.sleep(0)
        return False

    def _run(self, actions, loops, speed, jitter_percent):
        winmm.timeBeginPeriod(1)
        held = {}
        error = None
        jitter = jitter_percent / 100
        try:
            # Absolute deadlines: time spent sending never accumulates into drift.
            deadline = time.perf_counter()
            count = 0
            while not self._stop.is_set() and (loops == 0 or count < loops):
                self.loop = count + 1
                for index, action in enumerate(actions):
                    self.step = index
                    delay = action.delay_ms / speed
                    if jitter:
                        delay *= 1 + random.uniform(-jitter, jitter)
                    deadline += delay / 1000
                    if not self._sleep_until(deadline):
                        return
                    if action.type == "move":
                        start = deadline
                        for x, y, ms in move_points(action):
                            if not self._sleep_until(start + ms / speed / 1000):
                                return
                            self._send(Action("move", "", x, y))
                        deadline = start + action.duration_ms / speed / 1000
                    else:
                        self._send(action)
                        self._track(held, action)
                count += 1
        except Exception as e:
            error = str(e)
        finally:
            for action in held.values():  # never leave a key or button stuck down
                try:
                    self._send(action)
                except Exception as e:
                    error = error or str(e)
            winmm.timeEndPeriod(1)
            self.playing = False
            if self._on_done:
                self._on_done(error)

    @staticmethod
    def _track(held, action):
        if action.type in KEY_TYPES:
            ident = ("key", action.vk, action.scan, action.ext)
            if action.type == "key down":
                held[ident] = Action("key up", action.key, vk=action.vk, scan=action.scan, ext=action.ext)
            else:
                held.pop(ident, None)
        elif action.type in BUTTON_TYPES:
            ident = ("button", action.key)
            if action.type == "mouse down":
                held[ident] = Action("mouse up", action.key)  # no x/y: release where the cursor is
            else:
                held.pop(ident, None)
