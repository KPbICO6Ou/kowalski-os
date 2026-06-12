# kow-core

The agent core of Kowalski OS: a daemon with an LLM loop, a typed tool
registry, security policies, and an action journal.

## Install (dev)

```bash
pip install -e core            # + core/requirements-dev.txt for tests
ollama pull qwen2.5:14b        # or 7b on smaller hardware
```

## CLI

```bash
kow ask "find PDFs from the last week"     # one-shot, no daemon
kow ask --yes --json "..."                 # auto-confirm + JSON event stream
kow serve [--api]                          # daemon: socket/D-Bus (+ REST on 127.0.0.1:8377)
kow tools list [--schemas]
kow journal tail [-n 50]
```

## Config `~/.config/kowalski/kowalski.conf` (KEY=VALUE, env overrides file)

| Key | Default | Meaning |
|---|---|---|
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | Ollama address |
| `OLLAMA_MODEL` | `qwen2.5:7b` | model with tool calling |
| `KOW_LLM` | `ollama` | transport: `ollama` or `pydantic-ai` |
| `KOW_PAI_MODEL` | — | provider-prefixed pydantic-ai model, e.g. `anthropic:claude-sonnet-4-6` |
| `KOW_TEMPERATURE` | `0.2` | low temp keeps local models' tool-call markup well-formed |
| `KOW_TOOLBOX_FS` | `1` | mount `fs.*` from pydantic-ai-toolbox |
| `KOW_TOOLBOX_FS_WRITE` | `0` | unlock fs.* write methods (still confirmed) |
| `KOW_DB_PATH` | `~/.local/share/kowalski/kowalski.db` | SQLite (journal, notes, reminders) |
| `KOW_ALLOWED_PATHS` | `~` | path allowlist, `:`-separated |
| `KOW_AUTO_ALLOW_NETWORK` | `0` | run network tools without confirmation |
| `KOW_MAX_ITERATIONS` | `8` | max LLM iterations per request |
| `KOW_TOOL_TIMEOUT` | `30` | seconds per tool execution |
| `KOW_CONFIRM_TIMEOUT` | `120` | seconds to wait for confirmation (daemon) |
| `KOW_SOCKET_PATH` | `$XDG_RUNTIME_DIR/kowalski.sock` | unix-socket IPC |
| `KOW_IPC` | auto | `socket` / `dbus` |
| `KOW_API_ENABLED` / `KOW_API_PORT` | `0` / `8377` | debug REST API |

## Tools (MVP)

| Tool | Risk | Description |
|---|---|---|
| `files.search_by_name` | read | file search: fd → plocate → python walk |
| `system.info` | read | CPU/RAM/disk/battery (psutil) |
| `system.diagnostics` | read | `wtf audit --format json` wrapper |
| `apps.open` | write | open an application/file/URL |
| `notes.create` | write | note in SQLite |
| `reminders.create` | write | reminder (APScheduler + notification) |
| `fs.*` (13 tools) | read/write/destructive | pydantic-ai-toolbox FilesystemToolset: read_file, grep, glob, list_dir, stat (read); write/append/copy/move/mkdir (write); delete_* (destructive) — sandboxed at the first allowed path |

Risk levels: read → executes; write → allowed inside the allowlist, otherwise
confirmation; destructive → always confirmation; network → confirmation
(unless `KOW_AUTO_ALLOW_NETWORK=1`). Paths under `/etc`, `/usr`, … are a hard
DENY. Every invocation is a journal row, including denied ones.

## Tests

```bash
pytest core/tests -q                       # unit, no network
KOW_TEST_OLLAMA=1 pytest -m integration    # against a live Ollama
docker compose -f docker/ubuntu-dev/docker-compose.yml run --rm test   # Linux/D-Bus
```
