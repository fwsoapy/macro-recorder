"""Macro data model, key names, JSON files and settings."""
import ctypes
import json
import math
import os
import tempfile
from dataclasses import asdict, dataclass, replace
from pathlib import Path

KEY_TYPES = ("key down", "key up")
BUTTON_TYPES = ("mouse down", "mouse up")
POINT_TYPES = BUTTON_TYPES + ("move",)
TYPES = KEY_TYPES + POINT_TYPES + ("delay",)
BUTTONS = ("left", "right", "middle")

_user32 = ctypes.WinDLL("user32")
_user32.MapVirtualKeyW.argtypes = (ctypes.c_uint, ctypes.c_uint)
_user32.MapVirtualKeyW.restype = ctypes.c_uint

_NAMES = {
    0x08: "Backspace", 0x09: "Tab", 0x0D: "Enter", 0x13: "Pause", 0x14: "CapsLock", 0x1B: "Esc",
    0x20: "Space", 0x21: "PageUp", 0x22: "PageDown", 0x23: "End", 0x24: "Home",
    0x25: "Left", 0x26: "Up", 0x27: "Right", 0x28: "Down", 0x2C: "PrintScreen",
    0x2D: "Insert", 0x2E: "Delete", 0x5B: "LWin", 0x5C: "RWin", 0x5D: "Apps",
    0x6A: "Num*", 0x6B: "Num+", 0x6D: "Num-", 0x6E: "Num.", 0x6F: "Num/",
    0x90: "NumLock", 0x91: "ScrollLock", 0xA0: "LShift", 0xA1: "RShift",
    0xA2: "LCtrl", 0xA3: "RCtrl", 0xA4: "LAlt", 0xA5: "RAlt",
    0xBA: ";", 0xBB: "=", 0xBC: ",", 0xBD: "-", 0xBE: ".", 0xBF: "/", 0xC0: "`",
    0xDB: "[", 0xDC: "\\", 0xDD: "]", 0xDE: "'",
}
_NAMES.update({vk: chr(vk) for vk in range(0x30, 0x3A)})
_NAMES.update({vk: chr(vk) for vk in range(0x41, 0x5B)})
_NAMES.update({0x60 + n: f"Num{n}" for n in range(10)})
_NAMES.update({0x70 + n: f"F{n + 1}" for n in range(24)})

_VK_BY_NAME = {name.lower(): vk for vk, name in _NAMES.items()}
_VK_BY_NAME.update(shift=0xA0, ctrl=0xA2, alt=0xA4, win=0x5B, ins=0x2D, escape=0x1B, pgup=0x21,
                   pgdn=0x22, **{"return": 0x0D, "del": 0x2E})

# MapVirtualKey does not report the E0 prefix for these keys on every Windows build.
_EXTENDED_VKS = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2C, 0x2D, 0x2E,
                 0x5B, 0x5C, 0x5D, 0x6F, 0xA3, 0xA5}
_SCAN_OVERRIDES = {0x2C: 0x37}  # MapVirtualKey gives Alt+SysRq (0x54) for PrintScreen

KEY_NAMES = sorted(set(_NAMES.values()) | {"NumEnter"}, key=lambda n: (len(n) > 1, n))


def key_name(vk, ext=False):
    """Display name for a virtual key as seen by the hook."""
    if vk == 0x0D and ext:
        return "NumEnter"
    return _NAMES.get(vk, f"VK_{vk:02X}")


def key_info(name):
    """Return (canonical name, vk, scan, ext) for a key name. Raises ValueError if unknown."""
    text = str(name).strip().lower()
    if text == "numenter":
        return "NumEnter", 0x0D, 0x1C, True
    vk = _VK_BY_NAME.get(text)
    if vk is None and text.startswith("vk_"):
        try:
            vk = int(text[3:], 16)
        except ValueError:
            vk = None
        if vk is not None and not 1 <= vk <= 0xFE:
            vk = None
    if vk is None:
        raise ValueError(f'Unknown key "{name}". Examples: A, 5, F1, Space, LShift, Enter, Left, Num0, VK_B3')
    code = _user32.MapVirtualKeyW(vk, 4)  # MAPVK_VK_TO_VSC_EX
    scan = _SCAN_OVERRIDES.get(vk, code & 0xFF)
    return key_name(vk), vk, scan, vk in _EXTENDED_VKS or (code >> 8) in (0xE0, 0xE1)


def parse_delay(value):
    """Delay in ms: finite and not negative."""
    if isinstance(value, bool):
        raise ValueError("Delay must be a number.")
    try:
        delay = float(value)
    except (TypeError, ValueError):
        raise ValueError(f'Delay must be a number, got "{value}".') from None
    if not math.isfinite(delay) or delay < 0:
        raise ValueError("Delay must be 0 or more.")
    return delay


def parse_coord(value):
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError("X and Y must be whole numbers.")
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f'X and Y must be whole numbers, got "{value}".') from None


def parse_speed(value):
    try:
        speed = float(value)
    except (TypeError, ValueError):
        speed = math.nan
    if not 0.1 <= speed <= 10.0:  # also rejects NaN
        raise ValueError("Speed must be a number from 0.1 to 10.0.")
    return speed


def parse_loops(value):
    try:
        loops = int(value)
    except (TypeError, ValueError):
        loops = -1
    if loops < 0:
        raise ValueError("Loop count must be a whole number, 0 or more (0 means infinite).")
    return loops


def parse_percent(value):
    try:
        percent = float(value)
    except (TypeError, ValueError):
        percent = math.nan
    if not 0 <= percent <= 100:
        raise ValueError("Variation must be a number from 0 to 100 percent.")
    return percent


def parse_countdown(value):
    """Whole seconds to wait before playback starts from the window, 0 to 10."""
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        seconds = math.nan
    if not (0 <= seconds <= 10 and seconds == int(seconds)):
        raise ValueError("Countdown must be a whole number of seconds from 0 to 10.")
    return int(seconds)


@dataclass(frozen=True, slots=True)
class Action:
    """One macro step. Frozen, so undo snapshots can share objects."""
    type: str
    key: str = ""  # key name, or button name for mouse down/up
    x: int | None = None
    y: int | None = None
    delay_ms: float = 0.0
    vk: int = 0
    scan: int = 0
    ext: bool = False
    # Mouse moves go from (x, y) to (to_x, to_y). path holds the recorded (x, y, ms) samples.
    to_x: int | None = None
    to_y: int | None = None
    duration_ms: float = 0.0
    path: tuple = ()


def key_action(action_type, name, delay_ms=0.0):
    canonical, vk, scan, ext = key_info(name)
    return Action(action_type, canonical, delay_ms=delay_ms, vk=vk, scan=scan, ext=ext)


def with_type(action, new_type):
    """Change an action's type, filling the fields the new type needs."""
    if new_type == action.type:
        return action
    if new_type in KEY_TYPES:
        if action.type in KEY_TYPES:
            return replace(action, type=new_type)
        return key_action(new_type, "Space")
    x, y = action.x or 0, action.y or 0
    if new_type in BUTTON_TYPES:
        return Action(new_type, action.key if action.key in BUTTONS else "left", x, y)
    if new_type == "move":
        return Action("move", "", x, y, to_x=x, to_y=y)
    if new_type == "delay":
        return Action("delay")
    raise ValueError(f'Unknown action type "{new_type}".')


def edit_cell(action, column, text):
    """Return a new action with one table cell changed. Raises ValueError on bad input."""
    if column == "delay":
        if action.type != "delay":
            raise ValueError("Only delay rows have a delay. Right-click a row to add one.")
        return replace(action, delay_ms=parse_delay(text))
    if column == "type":
        return with_type(action, text)
    if column in ("x", "y"):
        if action.type not in POINT_TYPES:
            raise ValueError("X and Y only apply to mouse actions.")
        return replace(action, **{column: parse_coord(text)})
    if column in ("to_x", "to_y", "duration"):
        if action.type != "move":
            raise ValueError("To X, To Y and Duration only apply to mouse moves.")
        if column == "duration":
            return replace(action, duration_ms=parse_delay(text))
        return replace(action, **{column: parse_coord(text)})
    if column == "key":
        if action.type in KEY_TYPES:
            return key_action(action.type, text, action.delay_ms)
        if action.type in BUTTON_TYPES:
            if text not in BUTTONS:
                raise ValueError("Button must be left, right or middle.")
            return replace(action, key=text)
        raise ValueError(f'A "{action.type}" action has no key or button.')
    raise ValueError(f'Column "{column}" cannot be edited.')


def format_delay(delay_ms):
    return f"{delay_ms:.3f}".rstrip("0").rstrip(".")


def macro_length_ms(actions):
    """How long one loop takes at speed 1: every delay plus every move's own duration."""
    return sum(a.delay_ms + (a.duration_ms if a.type == "move" else 0) for a in actions)


def format_length(ms):
    """A readable length: 850 ms, 4.2 s, 3 min 05 s."""
    if ms < 1000:
        return f"{ms:.0f} ms"
    seconds = ms / 1000
    if seconds < 60:
        return f"{seconds:.1f} s"
    minutes, seconds = divmod(round(seconds), 60)
    return f"{minutes} min {seconds:02d} s"


def row_values(index, action):
    blank = lambda v: "" if v is None else v
    duration = format_delay(action.duration_ms) if action.type == "move" else ""
    return (index + 1, action.type, action.key, blank(action.x), blank(action.y), blank(action.to_x),
            blank(action.to_y), duration, format_delay(action.delay_ms) if action.type == "delay" else "")


def group_moves(actions):
    """Merge each run of single-position move samples into one move action. Total timing is unchanged."""
    grouped = []
    run = []

    def flush():
        if not run:
            return
        first, last = run[0], run[-1]
        points, elapsed = [], 0.0
        for sample in run:
            if sample is not first:
                elapsed = round(elapsed + sample.delay_ms, 3)
            points.append((sample.x, sample.y, elapsed))
        grouped.append(Action("move", "", first.x, first.y, first.delay_ms, to_x=last.x, to_y=last.y,
                              duration_ms=elapsed, path=tuple(points) if len(points) > 1 else ()))
        run.clear()

    for action in actions:
        if action.type == "move" and action.to_x is None:
            run.append(action)
        else:
            flush()
            grouped.append(action)
    flush()
    return grouped


def split_delays(actions):
    """Turn each gap stored on an action into its own delay row in front of that action."""
    result = []
    for action in actions:
        if action.type != "delay" and action.delay_ms > 0:
            result.append(Action("delay", delay_ms=action.delay_ms))
            action = replace(action, delay_ms=0.0)
        result.append(action)
    return result


def tidy(actions):
    """The form the editor shows: one row per mouse movement, and delays as their own rows."""
    return split_delays(group_moves(actions))


def move_points(action):
    """The (x, y, ms) positions to send for a move, fitted to its current endpoints and duration."""
    if action.to_x is None:
        return [(action.x, action.y, 0.0)]
    duration = action.duration_ms
    if duration <= 0:
        return [(action.to_x, action.to_y, 0.0)]
    if action.path:
        (x0, y0, t0), (x1, y1, t1) = action.path[0], action.path[-1]
        span = t1 - t0
        points = []
        for i, (x, y, t) in enumerate(action.path):
            part = (t - t0) / span if span else i / (len(action.path) - 1)
            # Keeps the recorded shape, bent gradually to reach edited endpoints.
            points.append((x + round((action.x - x0) * (1 - part) + (action.to_x - x1) * part),
                           y + round((action.y - y0) * (1 - part) + (action.to_y - y1) * part), part * duration))
        return points
    steps = max(1, int(duration * 120 / 1000))
    return [(round(action.x + (action.to_x - action.x) * i / steps),
             round(action.y + (action.to_y - action.y) * i / steps), duration * i / steps) for i in range(steps + 1)]


def move_rows(actions, indices, delta):
    """Move selected rows one step (delta is -1 or 1). Returns (new list, new selected indices)."""
    result = list(actions)
    selected = set(indices)
    for i in sorted(selected, reverse=delta > 0):
        j = i + delta
        if 0 <= j < len(result) and j not in selected:
            result[i], result[j] = result[j], result[i]
            selected.remove(i)
            selected.add(j)
    return result, sorted(selected)


def _to_dict(action):
    data = asdict(action)
    if action.type not in POINT_TYPES:
        del data["x"], data["y"]
    if action.type not in KEY_TYPES:
        del data["vk"], data["scan"], data["ext"]
    if action.type != "move":
        del data["to_x"], data["to_y"], data["duration_ms"]
    if not action.path:
        del data["path"]
    if action.type != "delay" and not action.delay_ms:
        del data["delay_ms"]
    if not data["key"]:
        del data["key"]
    return data


def _parse_path(data):
    if not isinstance(data, list):
        raise ValueError("path must be a list")
    points, previous = [], 0.0
    for point in data:
        if not isinstance(point, list) or len(point) != 3:
            raise ValueError("each path point must be [x, y, ms]")
        x, y, t = parse_coord(point[0]), parse_coord(point[1]), parse_delay(point[2])
        if t < previous:
            raise ValueError("path times must not go backwards")
        previous = t
        points.append((x, y, t))
    return tuple(points)


def _from_dict(data):
    if not isinstance(data, dict):
        raise ValueError("expected an object")
    action_type = data.get("type")
    if action_type == "wait":  # the name older files use
        action_type = "delay"
    if action_type not in TYPES:
        raise ValueError(f'unknown type "{action_type}"')
    delay = parse_delay(data.get("delay_ms", 0))
    if action_type in KEY_TYPES:
        action = key_action(action_type, data.get("key", ""), delay)
        scan, ext = data.get("scan"), data.get("ext")
        # Keep recorded scan codes unless someone hand-edited the key name.
        if data.get("vk") == action.vk and type(scan) is int and 0 < scan <= 0xFF and type(ext) is bool:
            action = replace(action, scan=scan, ext=ext)
        return action
    if action_type in POINT_TYPES:
        x, y = parse_coord(data.get("x")), parse_coord(data.get("y"))
        if action_type == "move":
            if "to_x" not in data and "to_y" not in data:  # older files: one sample per action
                return Action("move", "", x, y, delay)
            return Action("move", "", x, y, delay, to_x=parse_coord(data.get("to_x")),
                          to_y=parse_coord(data.get("to_y")), duration_ms=parse_delay(data.get("duration_ms", 0)),
                          path=_parse_path(data.get("path", [])))
        if data.get("key") not in BUTTONS:
            raise ValueError(f'unknown button "{data.get("key")}"')
        return Action(action_type, data["key"], x, y, delay)
    return Action("delay", delay_ms=delay)


def _write_atomic(path, text):
    """Write through a temp file so a failed save can't destroy the existing file."""
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def save_macro(path, actions):
    rows = ",\n".join("    " + json.dumps(_to_dict(a)) for a in actions)
    body = f"\n{rows}\n  " if rows else ""
    _write_atomic(path, f'{{\n  "version": 1,\n  "actions": [{body}]\n}}\n')


def load_macro(path):
    """Read a macro file. Raises ValueError with a readable message if it is invalid."""
    with open(path, encoding="utf-8") as f:
        try:
            data = json.load(f)
        except ValueError as e:
            raise ValueError(f"Not a valid JSON file: {e}") from None
    if not isinstance(data, dict) or not isinstance(data.get("actions"), list):
        raise ValueError('Not a macro file: missing the "actions" list.')
    actions = []
    for i, row in enumerate(data["actions"], 1):
        try:
            actions.append(_from_dict(row))
        except ValueError as e:
            raise ValueError(f"Action {i}: {e}") from None
    return tidy(actions)


DEFAULT_SETTINGS = {
    "hotkey_record": "F8", "hotkey_play": "F9", "hotkey_stop": "F10",
    "speed": 1.0, "loops": 1,
    "random_delay": False, "random_percent": 10.0,
    "record_mouse": True, "record_keyboard": True,
    "run_as_admin": False,
    "countdown": 3, "always_on_top": False, "minimize_on_play": False,
    "recent": [],
}
RECENT_LIMIT = 8


def _valid_hotkeys(settings):
    try:
        vks = {key_info(settings[k])[1] for k in ("hotkey_record", "hotkey_play", "hotkey_stop")}
    except ValueError:
        return False
    return len(vks) == 3


def load_settings(path):
    """Return (settings, warning). Bad or missing values fall back to defaults."""
    settings = dict(DEFAULT_SETTINGS)
    try:
        with open(path, encoding="utf-8") as f:
            saved = json.load(f)
        if not isinstance(saved, dict):
            raise ValueError("expected an object")
    except FileNotFoundError:
        return settings, None
    except (OSError, ValueError) as e:
        return settings, f"Could not read {Path(path).name}, using defaults: {e}"
    for name, parse in (("speed", parse_speed), ("loops", parse_loops), ("random_percent", parse_percent)):
        try:
            settings[name] = parse(saved[name])
        except (KeyError, ValueError):
            pass
    try:
        settings["countdown"] = parse_countdown(saved["countdown"])
    except (KeyError, ValueError):
        pass
    recent = saved.get("recent")
    if isinstance(recent, list):
        settings["recent"] = [p for p in recent if isinstance(p, str) and p][:RECENT_LIMIT]
    for name in ("random_delay", "record_mouse", "record_keyboard", "run_as_admin", "always_on_top",
                 "minimize_on_play"):
        if isinstance(saved.get(name), bool):
            settings[name] = saved[name]
    hotkeys = {k: saved.get(k) for k in ("hotkey_record", "hotkey_play", "hotkey_stop")}
    if _valid_hotkeys(hotkeys):
        settings.update(hotkeys)
    return settings, None


def save_settings(path, settings):
    _write_atomic(path, json.dumps(settings, indent=2) + "\n")
