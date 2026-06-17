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


# [Other] keys (no short alias) are folded into themed one-line groups for a
# tidy `show`; a trailing catch-all line keeps any new key from disappearing.
OTHER_FAMILIES: tuple[tuple[str, ...], ...] = (
    ("IMAP_",),
    ("SMTP_", "MAIL_FROM"),
    ("KOW_MAIL_BACKEND",),
    ("KOW_API_", "KOW_LOG_LEVEL"),
    ("KOW_SHELL", "KOW_UIAUTO", "KOW_VISION_MODEL"),
    ("KOW_TOOLBOX_",),
    ("KOW_MEMORY", "KOW_CHECKLIST"),
    ("KOW_SUMMARIZE",),
    ("KOW_RECIPES", "KOW_PLUGINS_DIR", "KOW_MCP_SERVERS", "KOW_PAI_MODEL"),
    ("KOW_HEARTBEAT",),
    ("KOW_DB_PATH", "KOW_INDEX"),
    ("KOW_AUTO_ALLOW_NETWORK", "KOW_TOOL_TIMEOUT", "KOW_CONFIRM_TIMEOUT", "KOW_SOCKET_PATH"),
)


def _other_lines(cfg) -> list[str]:
    """Group the non-schema keys into themed ' · '-joined lines."""
    others = [k for k in sorted(cfg.values) if k not in BY_KEY]
    used: set[str] = set()
    lines: list[str] = []

    def render(key: str) -> str:
        value = _mask_value(key, cfg.get(key), None)
        return f"{key}={value}" if value else key

    for family in OTHER_FAMILIES:
        members = [k for k in others
                   if k not in used and any(k == p or k.startswith(p) for p in family)]
        if members:
            used.update(members)
            lines.append(" · ".join(render(k) for k in members))
    leftover = [k for k in others if k not in used]
    if leftover:
        lines.append(" · ".join(render(k) for k in leftover))
    return lines


def cmd_setup_show(args) -> int:
    """Pretty dump of every setting: key · value · env variable, by section."""
    cfg = Config.load()
    width = max(len(s.short) for s in SETTINGS)
    print(f"  {'key':<{width}}  {'value':<30}  env variable")
    last_group = None
    for s in SETTINGS:
        if s.group != last_group:
            print(f"\n[{s.group}]")
            last_group = s.group
        value = cfg.get(s.key, DEFAULTS.get(s.key, ""))
        shown = _mask_value(s.key, value, s.kind) or "—"
        print(f"  {s.short:<{width}}  {shown:<30}  {s.key}")

    other = _other_lines(cfg)
    if other:
        print("\n[Other]  (set by full env KEY)")
        for line in other:
            print(f"  {line}")
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
VALW = 26                       # value column width in the TUI
ENV_COL = VALUE_COL + VALW + 2  # the env-variable (full KEY) column


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


def _ollama_models(host: str) -> list[str]:
    """Names of models installed on the Ollama at `host` (empty if unreachable)."""
    import json
    import urllib.request

    if not host:
        return []
    try:
        with urllib.request.urlopen(host.rstrip("/") + "/api/tags", timeout=3) as resp:
            data = json.load(resp)
        return sorted(m.get("name", "") for m in data.get("models", []) if m.get("name"))
    except Exception:
        return []


def _pick_from_list(stdscr, title: str, options: list[str], current: str) -> str | None:
    """Full-screen single-choice picker; Enter selects, Esc cancels."""
    sel = options.index(current) if current in options else 0
    while True:
        stdscr.erase()
        _put(stdscr, 0, 2, title, curses.A_BOLD)
        _put(stdscr, 1, 2, "↑/↓ move · Enter select · Esc cancel", curses.A_DIM)
        for i, opt in enumerate(options):
            _put(stdscr, 3 + i, 4, opt, curses.A_REVERSE if i == sel else 0)
        stdscr.refresh()
        ch = stdscr.getch()
        if ch == 27:
            return None
        if ch in (curses.KEY_ENTER, 10, 13):
            return options[sel]
        if ch in (curses.KEY_UP, ord("k")):
            sel = (sel - 1) % len(options)
        elif ch in (curses.KEY_DOWN, ord("j")):
            sel = (sel + 1) % len(options)


def _keyname(ch: int) -> str:
    """Render a captured keypress as a readable combo string."""
    named = {0: "ctrl+space", 9: "tab", 10: "enter", 13: "enter", 8: "backspace",
             127: "backspace", 32: "space", curses.KEY_UP: "up", curses.KEY_DOWN: "down",
             curses.KEY_LEFT: "left", curses.KEY_RIGHT: "right"}
    if ch in named:
        return named[ch]
    if 1 <= ch <= 26:
        return f"ctrl+{chr(ch + 96)}"
    if 32 < ch < 127:
        return chr(ch)
    for n in range(1, 13):
        if ch == curses.KEY_F(n):
            return f"f{n}"
    return f"key{ch}"


def _capture_hotkey(stdscr, y: int) -> str | None:
    """Capture one chord at row `y`. Esc cancels. Ctrl/Alt are terminal-readable
    (Ctrl = control codes, Alt = an Esc prefix); Shift/Super on printable keys are
    NOT — set those as text, e.g. `kow setup set kow_voice_hotkey 'super+space'`."""
    _put(stdscr, y, VALUE_COL, "Press a key (or Esc)" + " " * 12)
    stdscr.refresh()
    ch = stdscr.getch()
    if ch == 27:  # lone Esc cancels; Esc immediately followed by a key is Alt+key
        stdscr.nodelay(True)
        nxt = stdscr.getch()
        stdscr.nodelay(False)
        return None if nxt == -1 else "alt+" + _keyname(nxt)
    return _keyname(ch)


def _tui_loop(stdscr, work: dict, original: dict, path) -> None:
    curses.curs_set(0)
    stdscr.keypad(True)
    sel = 0
    saved = False
    while True:
        stdscr.erase()
        _put(stdscr, 0, 2, "kow setup — settings", curses.A_BOLD)
        _put(stdscr, 1, 2, str(path), curses.A_DIM)
        _put(stdscr, 2, 4, f"{'key':<{SHORT_W}}  {'value':<{VALW}}  env variable", curses.A_DIM)
        row = 3
        rows: dict[int, int] = {}
        last_group = None
        for i, s in enumerate(SETTINGS):
            if s.group != last_group:
                _put(stdscr, row, 2, f"[{s.group}]", curses.A_BOLD)
                row += 1
                last_group = s.group
            attr = curses.A_REVERSE if i == sel else 0
            val = _display(s, work[s.key])
            if len(val) > VALW:
                val = val[: VALW - 1] + "…"
            _put(stdscr, row, 4, f"{s.short:<{SHORT_W}}", attr)
            _put(stdscr, row, VALUE_COL, f"{val:<{VALW}}", attr)
            _put(stdscr, row, ENV_COL, s.key, curses.A_DIM)
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
        elif cur.kind == "model" and ch in (ord(" "), curses.KEY_ENTER, 10, 13):
            models = _ollama_models(work["OLLAMA_HOST"])
            if models:
                picked = _pick_from_list(
                    stdscr, f"{cur.short} — Ollama @ {work['OLLAMA_HOST']}", models, work[cur.key])
                if picked is not None:
                    work[cur.key] = picked
                    saved = False
            else:  # Ollama unreachable — fall back to typing it
                typed = _edit_text(stdscr, rows[sel], work[cur.key], masked=False)
                if typed is not None:
                    work[cur.key] = typed
                    saved = False
        elif cur.kind == "hotkey" and ch in (ord(" "), curses.KEY_ENTER, 10, 13):
            combo = _capture_hotkey(stdscr, rows[sel])
            if combo is not None:
                work[cur.key] = combo
                saved = False
        elif cur.kind == "mic" and ch in (ord(" "), curses.KEY_ENTER, 10, 13):
            try:
                from kowvoice import mic_select
            except Exception:
                mic_select = None
            if mic_select is not None:
                mic_select.run(stdscr)  # writes KOW_VOICE_INPUT_DEVICE itself
                stdscr.timeout(-1)
                curses.curs_set(0)
                fresh = parse_conf(path.read_text()) if path.exists() else {}
                work[cur.key] = fresh.get(cur.key, work[cur.key])
                original[cur.key] = work[cur.key]
            else:  # voice/sounddevice absent — let them type the device name
                typed = _edit_text(stdscr, rows[sel], work[cur.key], masked=False)
                if typed is not None:
                    work[cur.key] = typed
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
