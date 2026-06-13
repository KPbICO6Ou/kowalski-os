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
kow ask --continue "and the largest one?"  # follow-up in the most recent conversation
kow ask -c <ID> "..."                      # follow-up in a specific conversation
kow serve [--api]                          # daemon: socket/D-Bus (+ REST on 127.0.0.1:8377)
kow tools list [--schemas]
kow journal tail [-n 50]
```

Conversations persist final user/assistant turns in SQLite; follow-ups (same
`conversation_id` over IPC, or `-c`/`--continue` in the CLI) see prior turns.
The socket op `{"op": "conversations"}` returns the recent conversation list.

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
| `KOW_TOOLBOX_SYSTEM` | `1` | mount read-only `system.*` host-info tools from pydantic-ai-toolbox |
| `KOW_DB_PATH` | `~/.local/share/kowalski/kowalski.db` | SQLite (journal, notes, reminders) |
| `KOW_INDEX_DB` | `~/.local/share/kowalski/index.db` | semantic index built by `kow-index` |
| `KOW_INDEX_PATHS` | — | `:`-separated indexer roots; empty = `KOW_ALLOWED_PATHS` |
| `KOW_EMBED_MODEL` | `nomic-embed-text` | Ollama embedding model for the semantic index |
| `KOW_ALLOWED_PATHS` | `~` | path allowlist, `:`-separated |
| `KOW_AUTO_ALLOW_NETWORK` | `0` | run network tools without confirmation |
| `KOW_MAX_ITERATIONS` | `8` | max LLM iterations per request |
| `KOW_TOOL_TIMEOUT` | `30` | seconds per tool execution |
| `KOW_CONFIRM_TIMEOUT` | `120` | seconds to wait for confirmation (daemon) |
| `KOW_SOCKET_PATH` | `$XDG_RUNTIME_DIR/kowalski.sock` | unix-socket IPC |
| `KOW_IPC` | auto | `socket` / `dbus` |
| `KOW_API_ENABLED` / `KOW_API_PORT` | `0` / `8377` | debug REST API |
| `KOW_MAIL_BACKEND` | `mock` | `mock` (in-memory, no creds) or `imap` (real IMAP/SMTP, needs the `mail` extra) |
| `IMAP_HOST` / `IMAP_PORT` / `IMAP_SSL` | — / `993` / `1` | incoming IMAP server |
| `IMAP_USER` / `IMAP_PASSWORD` | — | IMAP login — keep secrets in the 0600 conf; use an app-password |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_TLS` | — / `587` / `1` | outgoing SMTP server |
| `SMTP_USER` / `SMTP_PASSWORD` | — | SMTP login — keep secrets in the 0600 conf; use an app-password |
| `MAIL_FROM` | — | From address for sent mail; empty falls back to `SMTP_USER` |
| `KOW_VISION` / `KOW_VISION_MODEL` | `1` / `qwen2.5vl` | screen capture + vision-LLM tools |
| `KOW_UIAUTO` / `UIAUTO_TREE_MAX_DEPTH` | `1` / `6` | window/accessibility/input tools (X11) |
| `KOW_SHELL` / `KOW_SHELL_TIMEOUT` | `1` / `30` | sandboxed shell `system.run` |
| `KOW_RECIPES` / `KOW_RECIPES_DIR` | `1` / `~/.config/kowalski/recipes` | YAML automation recipes |

## Tools (MVP)

| Tool | Risk | Description |
|---|---|---|
| `files.search_by_name` | read | file search: fd → plocate → python walk |
| `files.search_semantic` | read | natural-language content search over the `kow-index` embedding index (registered only when the `indexer/` package is installed) |
| `system.*` (9 tools) | read | pydantic-ai-toolbox SystemToolset: cpu_info, memory_info, disk_usage, disk_partitions, uptime, load_avg, top_processes, network_io, battery — read-only host info (psutil) |
| `system.diagnostics` | read | `wtf audit --format json` wrapper |
| `apps.open` | write | open an application/file/URL |
| `notes.create` | write | note in SQLite |
| `reminders.create` | write | reminder (APScheduler + notification) |
| `reminders.list` | read | pending reminders ordered by due time; `include_done` adds delivered/missed |
| `reminders.cancel` | write | cancel a pending reminder: removes the scheduled job and the row |
| `fs.*` (13 tools) | read/write/destructive | pydantic-ai-toolbox FilesystemToolset: read_file, grep, glob, list_dir, stat (read); write/append/copy/move/mkdir (write); delete_* (destructive) — sandboxed at the first allowed path |
| `mail.search` | read | search the mailbox by substring over subject/sender/snippet |
| `mail.read` | read | read one message by id (headers + body text) |
| `mail.draft` | write | compose and save a local email draft (the AI writes the body); returns a draft id |
| `mail.send` | destructive | send a draft (`draft_id`) or inline (`to`/`subject`/`body`) — irreversible, so **always confirmed** and never auto-allowed |
| `screen.capture` / `screen.describe` | read | screenshot the primary screen; describe it via a vision model (qwen2.5-vl/llava over Ollama) |
| `windows.list` / `windows.activate` | read / write | list open windows; focus one (wmctrl/xdotool, X11) |
| `ui.tree` | read | read a window's accessibility tree (AT-SPI), depth-capped |
| `input.type` / `input.key` / `input.click` | destructive | drive keyboard/mouse — typed input lands in whatever window is focused, so **always confirmed** |
| `system.run` | destructive | run a shell command — sandboxed via bubblewrap/firejail on Linux, unsandboxed fallback on macOS/CI; `cwd` must be inside the allowlist; **always confirmed** |
| `recipes.list` / `recipes.add` / `recipes.run` / `recipes.remove` | read / write | YAML automation recipes: a trigger (manual/time/interval/inotify) drives a chain of tool calls; each step passes through the policy/confirmation/journal like any direct call |

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
