# Kowalski OS: AI-нативная графическая среда на базе XFCE
## Концепция, архитектура, модули, фазы разработки

---

## 1. Общая концепция

**Название:** Kowalski OS (GitHub-организация `kowalski-os`)

**Идея:** не «десктоп с чат-ботом сбоку», а среда, где LLM — это системный слой, равноправный с ядром и DE. Пользователь логинится через обычный greeter, попадает в XFCE-сессию, но поверх неё работает постоянный AI-демон («мозг»), который:

- видит систему (файлы, окна, процессы, почту, календарь, экран через vision-модель);
- управляет системой через строго типизированный реестр инструментов (tools);
- доступен из любой точки: глобальный хоткей → omnibox (как Spotlight), голос (wake word), чат-окно;
- все «приложения» — это тонкие GTK-окна поверх одного и того же агентного ядра.

**Ключевой архитектурный принцип:** UI ≠ логика. Вся логика живёт в демоне `kow-core` (systemd user service), который общается с Ollama. GUI-приложения — клиенты этого демона через D-Bus. Это позволяет менять/добавлять интерфейсы (голос, CLI, веб, телеграм-бот — у тебя уже есть опыт с openclaw) без переписывания ядра.

**Безопасность как фича, а не запоздалая мысль:** агент с доступом «ко всем ресурсам компьютера» = огромная поверхность атаки. Каждый tool имеет уровень риска (read / write / destructive / network), destructive-действия требуют подтверждения в GUI. Журнал всех действий агента — обязателен с фазы 1.

---

## 2. Архитектура (слои)

```
┌─────────────────────────────────────────────────────┐
│  UI-слой: Omnibox · Chat · Voice HUD · Mail · Notes │  GTK3/PyGObject
├─────────────────────────────────────────────────────┤
│  D-Bus (org.kowalski.Core) + событийная шина             │
├─────────────────────────────────────────────────────┤
│  kow-core (демон): агентный цикл, tool-роутер,      │  Python 3.12,
│  очередь задач, журнал, политики безопасности       │  FastAPI/asyncio
├──────────────┬──────────────┬───────────────────────┤
│ Tools (MCP)  │ Память/RAG   │ Голосовой конвейер    │
│ files/mail/  │ sqlite-vec + │ openWakeWord →        │
│ reminders/   │ nomic-embed  │ faster-whisper →      │
│ system/web   │              │ Piper TTS             │
├──────────────┴──────────────┴───────────────────────┤
│  Ollama (LLM + vision + embeddings) · CUDA          │
├─────────────────────────────────────────────────────┤
│  XFCE 4.18 · Xorg · LightDM                         │
├─────────────────────────────────────────────────────┤
│  Ubuntu Server 24.04 · NVIDIA driver · systemd      │
└─────────────────────────────────────────────────────┘
```

**Почему X11, а не Wayland:** XFCE до 4.20 — X11-нативный, и это плюс: `xdotool`, скриншоты, AT-SPI и глобальные хоткеи на X11 работают без костылей. Автоматизация UI на Wayland до сих пор боль. Закладываем Wayland-совместимость в абстракции (модуль `kow-input`), но не сейчас.

---

## 3. Модули: стек и решение «писать / брать готовое»

### M0 — Provisioning (база)
| Элемент | Решение | Готовое/своё |
|---|---|---|
| Установка ОС | Ubuntu 24.04 Server + **autoinstall (cloud-init)** — yaml-файл, полностью unattended | готовое |
| Конфигурация после установки | **Ansible playbook** (один репозиторий `kowalski-provision`) | своё (playbook), модули готовые |
| NVIDIA драйвер | `ubuntu-drivers install --gpgpu` или `nvidia-driver-5xx-server` + cuda-keyring | готовое |
| CUDA/cuDNN | cuda-toolkit из репо NVIDIA (нужен для faster-whisper/CTranslate2) | готовое |
| Ollama | официальный установщик + systemd unit, `OLLAMA_HOST=127.0.0.1`, модели прогреваются при провижининге | готовое |
| Графический стек | `xubuntu-desktop-minimal` ИЛИ ручной набор: `xfce4 xfce4-goodies lightdm slick-greeter xorg` | готовое |
| Тюнинг | твой опыт с sysctl.d/systemd oneshot отлично переносится: hugepages off для Ollama не нужен, но `vm.overcommit`, лимиты, governor=performance — в playbook | своё |

**Вердикт:** ничего не писать, только Ansible-роли. Результат фазы — «вставил флешку → через 20 минут готовая система с логин-экраном».

### M1 — kow-core (агентный демон) — сердце системы
| Элемент | Стек | Готовое/своё |
|---|---|---|
| Демон | Python 3.12, asyncio, systemd user unit (`kow-core.service`) | **своё** |
| LLM-клиент | `ollama` python lib; модель с tool calling: **qwen2.5:14b/32b** или llama3.1 (зависит от VRAM) | готовое |
| Tool-протокол | **MCP (Model Context Protocol)** — каждый модуль инструментов = MCP-сервер. Это даёт совместимость со сторонними MCP-серверами из коробки | готовый протокол, серверы свои |
| IPC с GUI | **D-Bus** (`dasbus`) — нативно для Linux-десктопа, события, активация по запросу | готовое |
| REST (опционально) | FastAPI на 127.0.0.1 — для отладки и внешних клиентов (твой membook-паттерн) | своё |
| Очередь/планировщик | APScheduler + SQLite (журнал задач) | готовое |
| Политики безопасности | свой модуль: уровни риска tools, allowlist путей, confirm-диалоги через D-Bus | **своё, критично** |

**Вердикт:** это главный модуль, который пишется самостоятельно (~3–5 тыс. строк). Всё остальное — обвязка вокруг него.

### M2 — Omnibox + Chat (основной UI)
| Элемент | Стек | Готовое/своё |
|---|---|---|
| Toolkit | **GTK3 + PyGObject** (визуально нативно для XFCE; GTK4 — если хочется отдельный стиль) | готовое |
| Omnibox | своё окно: borderless, по центру, глобальный хоткей (Super+Space) через `libkeybinder` | **своё** (~500 строк) |
| Chat-окно | своё: стриминг токенов, markdown-рендер (`webkit2gtk` или просто Pango) | **своё** |
| Уведомления | `libnotify` / `notify-send` — XFCE уже умеет | готовое |
| Панель-индикатор | XFCE plugin или просто `Gtk.StatusIcon` в трее: статус агента, mute голоса | своё, маленькое |
| Альтернатива для прототипа | форкнуть **Ulauncher** (Python/GTK, расширяемый) и прикрутить к kow-core | готовое как база |

**Вердикт:** Omnibox писать своё (или старт с Ulauncher для скорости), это лицо продукта.

### M3 — Голосовой конвейер (клиент-серверный, на базе wachawo/*)
| Элемент | Стек | Готовое/своё |
|---|---|---|
| Wake word | **openWakeWord** (CPU, локально на десктопе) | готовое |
| VAD | **silero-vad** (локально, режет фразу) | готовое |
| STT | **wachawo/speech-to-text**: Flask/uvicorn HTTP-сервис, openai-whisper, `POST /api/stt`, порт 5099, pool моделей, Bearer-токены (`STT_TOKENS`), Docker GPU/CPU | готовое (своё же) |
| TTS | **wachawo/text-to-speech**: `ttssrv` (порт 5000, `/api/tts`, `/api/engines`), 7 движков; для ru — silerotts, для en — pipertts; клиентская логика из `ttsapi` | готовое (своё же) |
| Аудио | PipeWire + `sounddevice`, запись по образцу `ttsrec` | готовое |
| Оркестрация | свой модуль `kow-voice`: state machine (idle → wake → listen → VAD-cut → POST /api/stt → agent → POST /api/tts → play), barge-in | **своё** |

**Архитектурный выигрыш:** STT/TTS — это HTTP-микросервисы, которые могут жить на localhost (Docker) или на отдельном GPU-сервере. Десктоп тонкий, VRAM-конкуренция с Ollama решается выносом речи на другую машину. Конфиг — родная цепочка `./ttsgen.conf` → `~/.config/ttsgen.conf` → `.env` (`TTS_URL`, `TTS_TOKEN`, `STT_URL`, `STT_TOKEN`).

**Доработки в speech-to-text и text-to-speech** — см. раздел «Доработки в существующих репозиториях wachawo/*» ниже.

### M4 — Файлы и поиск («найди файл»)
| Элемент | Стек | Готовое/своё |
|---|---|---|
| Поиск по имени | `fd` / `plocate` как backend tools | готовое |
| Поиск по содержимому | `ripgrep` + extractors (pdftotext, и т.п.) | готовое |
| Семантический поиск | свой индексер: watchdog (inotify) → чанкинг → **nomic-embed-text** через Ollama → **sqlite-vec** | **своё** (~800 строк), у тебя уже есть RAG-опыт из membook — переиспользуй |
| Файловые операции | tools: move/copy/trash (`gio trash`, не rm!), open with xdg-open | своё, тонкое |

### M5 — Почта
| Элемент | Стек | Готовое/своё |
|---|---|---|
| IMAP | **imap-tools** (sync, простой) или aioimaplib | готовое |
| SMTP | **aiosmtplib** | готовое |
| Хранилище/индекс | вариант «по-взрослому»: **notmuch** + mbsync (offline-почта с мощным поиском, есть python-биндинги) | готовое ядро |
| GUI | своё GTK-окно: список → тред → AI-панель (summarize, draft, «ответь вежливо») | **своё** |
| Tools для агента | `mail.search`, `mail.read`, `mail.draft`, `mail.send` (send — уровень риска high → подтверждение) | своё |

**Вердикт:** транспорт готовый, GUI и AI-обвязка свои. Полноценный клиент уровня Thunderbird не писать — достаточно «AI-first» минимализма.

### M6 — Напоминалки / календарь / задачи
| Элемент | Стек | Готовое/своё |
|---|---|---|
| Хранилище | SQLite + (опционально) CalDAV через `caldav` lib для синка | готовое |
| Срабатывание | APScheduler внутри kow-core + libnotify + TTS-озвучка | своё, тривиально |
| NLU дат («через 20 минут», «в пятницу») | `dateparser` (русский поддерживает) + LLM как fallback | готовое |

### M7 — Системные tools и автоматизация
| Элемент | Стек | Готовое/своё |
|---|---|---|
| Процессы/ресурсы | `psutil`, nvidia-smi/NVML (`pynvml`) | готовое |
| Управление окнами | `wmctrl`/`xdotool`, python-xlib | готовое |
| Клавиатура/мышь (агент «водит» UI) | `xdotool` + **AT-SPI** (accessibility tree — структурное чтение UI, надёжнее координат) | готовое |
| Скриншот + vision | `maim`/xfce4-screenshooter → **qwen2.5-vl / llava** через Ollama: «что на экране?» | готовое + своё |
| Shell-выполнение | tool `system.run` — sandboxed (bwrap/firejail), уровень риска max, всегда confirm | **своё, критично** |
| Сценарии автоматизации | YAML-«рецепты»: триггер (время/событие/inotify) → цепочка tools; LLM генерирует рецепты сам | **своё** |

### M8 — Память и персонализация
- Долговременная память агента: тот же sqlite-vec, паттерн из membook.
- Профиль пользователя, факты, предпочтения — отдельная таблица, инжект в системный промпт.
- Журнал диалогов с поиском.

**Вердикт:** переиспользовать твою наработку membook почти as-is.

### M9 — kow-setup: первый запуск, валидация, тест латентности

Один backend-модуль `kow_setup/core.py` + два фронтенда: **CLI/TUI** (для headless-провижининга, вызывается из Ansible с `--non-interactive` и ответами из yaml) и **GTK-мастер** (autostart при первом логине, флаг `~/.config/kowalski/.setup-done`).

**Шаги мастера — для каждого из трёх сервисов (Ollama, STT, TTS) одинаковая развилка:**

```
┌ Сервис X ────────────────────────────────┐
│ ( ) Установить локально (localhost)      │
│      → pkexec: установка + docker compose│
│      → прогресс пула моделей             │
│ ( ) Указать адрес сервера                │
│      URL: [http://10.0.0.5:5099 ]        │
│      Token (опционально): [_______]      │
│              [ Проверить соединение ]    │
└──────────────────────────────────────────┘
```

- **Ollama:** локально — официальный установщик + `ollama pull` выбранных моделей; удалённо — `OLLAMA_HOST`.
- **STT:** локально — `docker compose up -d` из speech-to-text (GPU-вариант, если есть nvidia-container-toolkit, иначе CPU); выбор `WHISPER_MODEL` (turbo/medium/small) и **языка whisper** (ru/en/auto → `WHISPER_LANGUAGE` в env compose, для удалённого — поле `language` в запросе после PR №1).
- **TTS:** локально — `ttssrv` в Docker, выбор движка (ru → silerotts, en → pipertts); удалённо — `TTS_URL`/`TTS_TOKEN`.

**Валидация (кнопка «Проверить» и финальный экран) — три уровня на сервис:**

| Уровень | Ollama | STT | TTS |
|---|---|---|---|
| 1. Связность | TCP connect + `GET /api/tags` | `GET /api/health` (`available` > 0) | `GET /api/health` (engine загружен) |
| 2. Функция | `POST /api/generate`, prompt «ping», 1 токен | `POST /api/stt` с эталонным WAV (2 сек, вшит в пакет) → текст совпал | `POST /api/tts` «проверка связи» → валидные аудио-байты |
| 3. Латентность | TTFT + tokens/s (из `eval_duration`) | RTT целиком + `elapsed` из ответа (отделяем сеть от инференса) | время до полного аудио + длительность/время = RTF |

**Пороговые оценки в UI:** 🟢 / 🟡 / 🔴 — например, STT < 1.5 c на 2-сек фразу — зелёный; TTFT Ollama < 1 c — зелёный; иначе предупреждение «голосовой режим будет ощущаться медленным» с возможностью продолжить осознанно. Конфиг записывается **только после прохождения проверок** (или явного «принять с предупреждениями»).

**Куда пишется конфиг:** TTS-параметры — в родной `~/.config/ttsgen.conf` (код ttsapi уже его читает), остальное — `~/.config/kowalski/kowalski.conf` в том же формате KEY=VALUE: `OLLAMA_HOST`, `OLLAMA_MODEL`, `STT_URL`, `STT_TOKEN`, `STT_LANGUAGE`.

**Диагностика — wtftools вместо отдельной утилиты.** `wtf` уже умеет всё нужное как платформа: audit с [OK]/[WARN]/[FAIL], `--format json` для пайплайнов, `--check NAME` для выборочного запуска, пороги в INI-конфиге, снапшоты/diff, exit codes и даже `explain --llm ollama`. Не дублируем — расширяем (см. раздел «Доработки в репозиториях»). В итоге:

```bash
wtf ai                          # таблица: сервис | URL | статус | latency | server | network
wtf ai --bench -n 5             # p50/p95 по 5 прогонам
wtf audit --check ollama --check stt --check tts --format json   # для kow-setup
wtf audit                       # общий аудит хоста: диски, OOM, GPU, failed units
```

- Кнопка «Проверить» в мастере и финальный экран = вызов `wtf audit --check ... --format json` и разбор результата.
- Tool агента `system.diagnostics` = обёртка над `wtf ... --format json`; пользователь спрашивает «почему тормозишь?» → агент запускает wtf и отвечает по цифрам: «STT отвечает за 4 с, из них 3.5 с — сеть до 10.0.0.5».
- Бонус: `wtf explain --prompt` отдаёт готовый текст для LLM — kow-core скармливает его своей же Ollama-сессии вместо отдельного вызова.

Эскиз разделения сети и инференса внутри check'а:

```python
t0 = time.perf_counter()
resp = post(f"{url}/api/stt", files={"file": SAMPLE_WAV})
rtt = time.perf_counter() - t0
server = resp.json().get("elapsed")      # сервер сам меряет инференс
network = rtt - server if server else None
```

---

## 4. Фазы разработки

### Фаза 0 — Provisioning + kow-setup CLI (2–3 недели)
Autoinstall yaml + Ansible: ОС → драйверы → CUDA → Docker + nvidia-container-toolkit → XFCE + LightDM. **kow-setup в CLI-режиме**: развилка «локально/сервер» для Ollama/STT/TTS, установка локальных вариантов, валидация и латентность-тест через wtf ai, запись конфига.
**DoD:** чистое железо → логин-экран → `wtf ai` показывает 🟢 по всем трём сервисам.

### Фаза 1 — Ядро + Omnibox (3–4 недели) ← MVP
kow-core демон, D-Bus API, 5–7 базовых tools (поиск файлов по имени, открыть приложение, заметка, напоминание, system info, system.diagnostics как обёртка над wtf --format json), Omnibox с хоткеем, стриминг ответа, журнал действий, политика подтверждений.
**DoD:** Super+Space → «найди презентацию за прошлую неделю и открой» → работает.

### Фаза 2 — Семантика файлов + Напоминалки (2–3 недели)
Индексер с inotify, sqlite-vec, гибридный поиск (имя+содержимое+смысл), полноценные напоминания с озвучкой.

### Фаза 3 — Голос + GTK-мастер первого запуска (2–3 недели)
kow-voice: openWakeWord + silero-vad локально → wachawo/speech-to-text по HTTP → агент → ttssrv по HTTP. HUD-индикатор. Barge-in. GTK-версия kow-setup (та же логика, что CLI из фазы 0). PR в speech-to-text: поле `language` в `/api/stt`.
**DoD:** «Компьютер, напомни через час позвонить маме» — без рук; первый логин нового пользователя открывает мастер.

### Фаза 4 — Почта (3 недели)
mbsync/notmuch backend, GTK-клиент, mail-tools, AI-драфты.
**DoD:** «отправь Ивану письмо, что встреча переносится» → драфт → подтверждение → отправка.

### Фаза 5 — Автоматизация и vision (3–4 недели)
Скриншот+VLM, AT-SPI/xdotool управление, YAML-рецепты, sandboxed shell. Многошаговые агентные задачи с планированием.

### Фаза 6 — Продукт (2–3 недели)
Упаковка в .deb (`kowalski-core`, `kowalski-ui`, `kowalski-voice`), свой ISO `kowalski-os-1.0-amd64.iso` (Cubic / autoinstall-образ), тема XFCE, onboarding-мастер при первом входе, документация.

Итого: ~4–5 месяцев соло в спокойном темпе; MVP (фазы 0–1) — за месяц.

---

## 5. Железо и VRAM-бюджет (важно)

Всё крутится на одной карте, считаем заранее. Пример для 24 GB (3090/4090):
- qwen2.5:14b Q4 ≈ 10–11 GB (или 32b Q4 ≈ 20 GB — тогда тесно)
- qwen2.5-vl:7b ≈ 6–7 GB (грузится по требованию, `keep_alive` короткий)
- nomic-embed ≈ 0.5 GB
- faster-whisper medium int8 ≈ 1.5 GB
- запас под KV-cache и X11

На 12–16 GB карте: LLM 7–8b, whisper small, vision по требованию с выгрузкой. Ollama сам выгружает модели по `keep_alive` — это спасает.

---

## 6. Структура репозитория

```
kowalski/                  # монорепо в org kowalski-os
├── provision/          # autoinstall.yaml + ansible roles
├── core/               # демон, агентный цикл, политики
│   └── tools/          # MCP-серверы: files, mail, reminders, system, vision
├── ui/                 # omnibox, chat, mail-gui, tray
├── voice/              # wake word + VAD + клиенты к STT/TTS серверам
├── setup/              # kow-setup (CLI+GTK); диагностика — wtftools
├── indexer/            # файловый семантический индекс
├── packaging/          # debian/, ISO build
└── docs/
```

**Нейминг и организация:**
- GitHub-организация **`kowalski-os`**; репозитории: `kowalski` (монорепо выше), `provision` можно выделить отдельно позже, `iso` — сборка образа.
- Upstream-зависимости остаются в личном аккаунте wachawo: `wtftools`, `speech-to-text`, `text-to-speech`.
- CLI-команда: **`kow`** (`kow ask "..."`, `kow setup --reconfigure`); демон — `kowalski-core.service` (systemd user unit).
- D-Bus: `org.kowalski.Core`. Конфиг: `~/.config/kowalski/kowalski.conf`.
- Python-пакет: `kowalski` (если имя на PyPI занято — `kowalski-os`).

---

## 7. Доработки в существующих репозиториях wachawo/*

### wtftools (становится диагностическим слоем Kowalski OS)

1. **AI-checks — встроенные, но опциональные.** Группа `ai` живёт прямо в wtftools, выключена по умолчанию: активируется секцией `[ai]` в config.ini, тяжёлые зависимости (requests/pynvml) — через extra `pip install wtftools[ai]` по образцу существующего `[full]`. Без секции и без extra поведение wtftools не меняется ни на байт — тулза остаётся универсальной для любых серверов.
2. **Новые checks (группа `ai`):**
   - `ollama` — `GET /api/tags` (связность, наличие требуемых моделей из конфига) + `POST /api/generate` на 1 токен → TTFT и tokens/s из `eval_duration`;
   - `stt` — `GET /api/health` (`available > 0`) + `POST /api/stt` с эталонным 2-сек WAV (вшит в пакет) → RTT, server `elapsed`, network = RTT − elapsed, сверка текста;
   - `tts` — `GET /api/health` + `POST /api/tts` пробной фразы → время до полного аудио, RTF;
   - `gpu` — pynvml: занятая/общая VRAM, температура, throttling, ECC (дополняет существующий hw-temperature check).
3. **Секция `[ai]` в config.ini** — `ollama_url`, `ollama_models`, `stt_url`, `stt_token`, `tts_url`, `tts_token` + пороги в `[thresholds]`: `ollama_ttft_warn/fail`, `stt_latency_warn/fail`, `tts_rtf_warn/fail`. Fallback: уметь читать `~/.config/kowalski/kowalski.conf` и `~/.config/ttsgen.conf`, чтобы не дублировать адреса.
4. **Подкоманда `wtf ai`** — шорткат для `audit --check ollama --check stt --check tts` с табличным выводом latency/server/network и режимом `--bench -n N` (повторные прогоны, p50/p95). Разовая проверка против бенчмарка — разные сценарии мастера.
5. **Стабильный JSON-контракт** — зафиксировать схему `--format json` (версионное поле `schema`), потому что на неё завязываются kow-setup и tool агента. Сейчас формат есть, но без гарантий.
6. **Опционально:** `wtf explain --prompt --format json`, чтобы kow-core забирал текст для LLM структурно, а не парсил stdout.

### speech-to-text

1. Опциональное поле `language` в `POST /api/stt` с fallback на серверный `WHISPER_LANGUAGE` — иначе язык, выбранный в мастере, не работает с общим удалённым сервером.
2. `GET /api/info`: имя модели, device (cuda/cpu), версия — для check'а `stt` и экрана диагностики.
3. Поле `elapsed` в ответе уже есть — не трогаем, на него опирается расчёт network vs inference.

### text-to-speech

1. Добавить `elapsed` (время инференса) в ответ `POST /api/tts` — телом нельзя (там аудио-байты), значит заголовком `X-Elapsed`. Без него check `tts` не отделит сеть от синтеза.
2. `GET /api/health` уже отдаёт engine/pool — достаточно; опционально добавить `device`.
3. Опционально: параметр `format=wav|mp3` в API, чтобы kow-voice не перекодировал на клиенте.

### Принцип

Все доработки — обратносовместимые и полезные репозиториям сами по себе (plugin API и `wtf ai` усиливают wtftools как продукт, `language` и `X-Elapsed` нужны любому клиенту). Kowalski OS не форкает, а использует их как upstream-зависимости: `pip install wtftools[ai]`.

## 8. Главные риски

1. **Безопасность агента** — shell/файловые операции без подтверждений превратят систему в оружие против владельца. Политики с фазы 1, не «потом».
2. **VRAM-конкуренция** — LLM+STT+vision одновременно. Решение: keep_alive, очередь инференса в kow-core.
3. **Латентность голоса** — цель < 1.5 с от конца фразы до начала ответа. Стриминг везде: whisper по чанкам, TTS по предложениям.
4. **Качество tool calling у локальных моделей** — qwen2.5 хорош, но нужен валидатор аргументов + retry-петля в ядре.
5. **Соблазн написать всё** — почтовый транспорт, поиск, TTS, wake word уже написаны лучше, чем успеешь сам. Своё — только ядро, политики, UI и склейка.
