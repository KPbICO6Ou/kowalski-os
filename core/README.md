# kow-core

Агентное ядро Kowalski OS: демон с LLM-циклом, типизированным реестром
инструментов, политиками безопасности и журналом действий.

## Установка (dev)

```bash
pip install -e core            # + core/requirements-dev.txt для тестов
ollama pull qwen2.5:14b        # или 7b на слабом железе
```

## CLI

```bash
kow ask "найди pdf за последнюю неделю"   # one-shot, без демона
kow ask --yes --json "..."                # автоподтверждение + события JSON
kow serve [--api]                          # демон: socket/D-Bus (+ REST на 127.0.0.1:8377)
kow tools list [--schemas]
kow journal tail [-n 50]
```

## Конфиг `~/.config/kowalski/kowalski.conf` (KEY=VALUE, env переопределяет)

| Ключ | Default | Что |
|---|---|---|
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | адрес Ollama |
| `OLLAMA_MODEL` | `qwen2.5:7b` | модель с tool calling |
| `KOW_LLM` | `ollama` | транспорт: `ollama` или `pydantic-ai` |
| `KOW_PAI_MODEL` | — | модель pydantic-ai с провайдером, напр. `anthropic:claude-sonnet-4-6` |
| `KOW_TEMPERATURE` | `0.2` | низкая темп. = стабильный tool-call у локальных моделей |
| `KOW_TOOLBOX_FS` | `1` | монтировать `fs.*` из pydantic-ai-toolbox |
| `KOW_TOOLBOX_FS_WRITE` | `0` | разрешить write-методы fs.* (всё равно через confirm) |
| `KOW_DB_PATH` | `~/.local/share/kowalski/kowalski.db` | SQLite (журнал, заметки, напоминания) |
| `KOW_ALLOWED_PATHS` | `~` | allowlist путей через `:` |
| `KOW_AUTO_ALLOW_NETWORK` | `0` | network-tools без подтверждения |
| `KOW_MAX_ITERATIONS` | `8` | максимум LLM-итераций на запрос |
| `KOW_TOOL_TIMEOUT` | `30` | сек на выполнение tool |
| `KOW_CONFIRM_TIMEOUT` | `120` | сек ожидания подтверждения (демон) |
| `KOW_SOCKET_PATH` | `$XDG_RUNTIME_DIR/kowalski.sock` | unix-сокет IPC |
| `KOW_IPC` | auto | `socket` / `dbus` |
| `KOW_API_ENABLED` / `KOW_API_PORT` | `0` / `8377` | debug REST API |

## Tools (MVP)

| Tool | Риск | Описание |
|---|---|---|
| `files.search_by_name` | read | поиск файлов: fd → plocate → python-walk |
| `system.info` | read | CPU/RAM/диск/батарея (psutil) |
| `system.diagnostics` | read | обёртка `wtf audit --format json` |
| `apps.open` | write | открыть приложение/файл/URL |
| `notes.create` | write | заметка в SQLite |
| `reminders.create` | write | напоминание (APScheduler + уведомление) |
| `fs.*` (13 шт.) | read/write/destructive | pydantic-ai-toolbox FilesystemToolset: read_file, grep, glob, list_dir, stat (read); write/append/copy/move/mkdir (write); delete_* (destructive) — песочница в первом allowed-пути |

Уровни риска: read → выполняется; write → разрешён внутри allowlist, иначе
подтверждение; destructive → всегда подтверждение; network → подтверждение
(если не `KOW_AUTO_ALLOW_NETWORK=1`). Пути под `/etc`, `/usr`, … — жёсткий DENY.
Каждый вызов — строка в журнале, включая отклонённые.

## Тесты

```bash
pytest core/tests -q                       # юнит, без сети
KOW_TEST_OLLAMA=1 pytest -m integration    # с живым Ollama
docker compose -f docker/ubuntu-dev/docker-compose.yml run --rm test   # Linux/D-Bus
```
