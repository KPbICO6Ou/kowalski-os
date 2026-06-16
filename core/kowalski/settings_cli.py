"""`kow settings` (TUI window) and `kow setup show|get|set` — view and edit the
settings in ~/.config/kowalski/kowalski.conf through the shared schema."""

from __future__ import annotations

import sys

from .config import DEFAULT_CONFIG_PATH, DEFAULTS, Config, parse_conf, write_conf
from .settings_schema import BY_KEY, SETTINGS, is_true, normalize, resolve

try:
    import curses
except ImportError:  # pragma: no cover - curses is stdlib on Linux/macOS
    curses = None


def _mask_value(key: str, value: str, kind: str | None) -> str:
    """Hide secrets in read-only output (tokens, passwords)."""
    secret = kind == "secret" or any(t in key.upper() for t in ("PASSWORD", "TOKEN", "SECRET"))
    return "••••••••" if (secret and value) else value


def cmd_setup_show(args) -> int:
    """Print every setting: the curated short-key groups, then any other keys."""
    cfg = Config.load()
    width = max(len(s.short) for s in SETTINGS)
    last_group = None
    for s in SETTINGS:
        if s.group != last_group:
            print(f"\n[{s.group}]")
            last_group = s.group
        value = cfg.get(s.key, DEFAULTS.get(s.key, ""))
        shown = _mask_value(s.key, value, s.kind) or "—"
        print(f"  {s.short:<{width}}  {shown:<30}  {s.key}")

    others = sorted(k for k in cfg.values if k not in BY_KEY)
    if others:
        print("\n[Other]")
        for key in others:
            print(f"  {key} = {_mask_value(key, cfg.get(key), None)}")
    return 0


def cmd_setup_get(args) -> int:
    """Print one value (raw, unmasked — meant for scripting) by short or full key."""
    cfg = Config.load()
    setting = resolve(args.name)
    key = setting.key if setting else args.name.upper()
    if key not in cfg.values and key not in DEFAULTS:
        print(f"unknown setting: {args.name}", file=sys.stderr)
        return 2
    print(cfg.get(key, DEFAULTS.get(key, "")))
    return 0


def cmd_setup_set(args) -> int:
    """Validate and persist one setting by short key (schema) or full KEY (raw)."""
    setting = resolve(args.name)
    if setting:
        try:
            value = normalize(setting, args.value)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        key = setting.key
    else:
        key = args.name.upper()
        if not key or not all(c.isalnum() or c == "_" for c in key):
            print(f"unknown setting: {args.name}\n"
                  "use a key from `kow setup show` (any case) or a full env KEY",
                  file=sys.stderr)
            return 2
        value = args.value
    path = write_conf({key: value})
    print(f"set {key}={value}\nsaved: {path}")
    return 0


def _display(setting, value: str) -> str:
    if setting.kind == "bool":
        return "on" if is_true(value) else "off"
    if setting.kind == "secret":
        return "••••••••" if value else "—"
    return value if value else "—"


def _cycle(choices: tuple[str, ...], current: str, step: int) -> str:
    try:
        i = choices.index(current)
    except ValueError:
        i = 0
        return choices[0]
    return choices[(i + step) % len(choices)]


def _put(stdscr, y: int, x: int, text: str, attr: int = 0) -> None:
    """addstr that ignores out-of-bounds writes on a small terminal."""
    try:
        stdscr.addstr(y, x, text, attr)
    except curses.error:
        pass


SHORT_W = max(len(s.short) for s in SETTINGS)
VALUE_COL = 4 + SHORT_W + 2


def _edit_text(stdscr, y: int, initial: str, masked: bool) -> str | None:
    """Minimal inline line editor; Enter commits, Esc cancels, returns the text."""
    curses.curs_set(1)
    buf = list(initial)
    while True:
        shown = ("*" * len(buf)) if masked else "".join(buf)
        _put(stdscr, y, VALUE_COL, shown + "  ")
        try:
            stdscr.move(y, VALUE_COL + len(buf))
        except curses.error:
            pass
        stdscr.refresh()
        ch = stdscr.getch()
        if ch in (curses.KEY_ENTER, 10, 13):
            curses.curs_set(0)
            return "".join(buf)
        if ch == 27:  # Esc
            curses.curs_set(0)
            return None
        if ch in (curses.KEY_BACKSPACE, 127, 8):
            if buf:
                buf.pop()
        elif 32 <= ch < 127:
            buf.append(chr(ch))


def _tui_loop(stdscr, work: dict, original: dict, path) -> None:
    curses.curs_set(0)
    stdscr.keypad(True)
    sel = 0
    saved = False
    while True:
        stdscr.erase()
        _put(stdscr, 0, 2, "Kowalski settings", curses.A_BOLD)
        _put(stdscr, 1, 2, str(path), curses.A_DIM)
        row = 3
        rows: dict[int, int] = {}
        last_group = None
        for i, s in enumerate(SETTINGS):
            if s.group != last_group:
                _put(stdscr, row, 2, f"[{s.group}]", curses.A_BOLD)
                row += 1
                last_group = s.group
            attr = curses.A_REVERSE if i == sel else 0
            _put(stdscr, row, 4, f"{s.short:<{SHORT_W}}", attr)
            _put(stdscr, row, VALUE_COL, _display(s, work[s.key]), attr)
            rows[i] = row
            row += 1

        changed = any(work[s.key] != original[s.key] for s in SETTINGS)
        cur = SETTINGS[sel]
        hint = f"{cur.key}: {cur.help}"
        if cur.kind == "enum":
            hint += f"  [{' / '.join(cur.choices)}]"
        _put(stdscr, row + 1, 2, hint, curses.A_DIM)
        flag = "  *unsaved*" if changed else ("  saved" if saved else "")
        _put(stdscr, row + 2, 2,
             "↑/↓ move · Space/Enter edit · ←/→ enum · s save · q quit" + flag, curses.A_DIM)
        stdscr.refresh()

        ch = stdscr.getch()
        if ch in (ord("q"), ord("Q")):
            return
        if ch in (curses.KEY_UP, ord("k")):
            sel = (sel - 1) % len(SETTINGS)
        elif ch in (curses.KEY_DOWN, ord("j")):
            sel = (sel + 1) % len(SETTINGS)
        elif ch == ord("s"):
            diff = {s.key: work[s.key] for s in SETTINGS if work[s.key] != original[s.key]}
            if diff:
                write_conf(diff, path)
                original.update(work)
            saved = True
        elif cur.kind == "bool" and ch in (ord(" "), curses.KEY_ENTER, 10, 13):
            work[cur.key] = "0" if is_true(work[cur.key]) else "1"
            saved = False
        elif cur.kind == "enum" and ch in (ord(" "), curses.KEY_RIGHT, curses.KEY_ENTER, 10, 13):
            work[cur.key] = _cycle(cur.choices, work[cur.key], +1)
            saved = False
        elif cur.kind == "enum" and ch == curses.KEY_LEFT:
            work[cur.key] = _cycle(cur.choices, work[cur.key], -1)
            saved = False
        elif cur.kind in ("text", "secret") and ch in (ord(" "), curses.KEY_ENTER, 10, 13):
            new = _edit_text(stdscr, rows[sel], work[cur.key], masked=cur.kind == "secret")
            if new is not None:
                work[cur.key] = new
                saved = False


def cmd_settings_tui(args) -> int:
    """Full-screen settings editor over the schema (toggles + inline inputs)."""
    if curses is None:
        print("the settings TUI needs the curses module; use `kow setup show/set`.",
              file=sys.stderr)
        return 1
    path = DEFAULT_CONFIG_PATH
    file_values = parse_conf(path.read_text()) if path.exists() else {}
    work = {s.key: file_values.get(s.key, DEFAULTS.get(s.key, "")) for s in SETTINGS}
    original = dict(work)
    try:
        curses.wrapper(_tui_loop, work, original, path)
    except Exception as exc:  # keep a broken terminal from dumping a traceback
        print(f"settings TUI unavailable ({exc}). Try `kow setup show`.", file=sys.stderr)
        return 1
    return 0
