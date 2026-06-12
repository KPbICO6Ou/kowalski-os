# Архитектура

Подробная концепция, модули и фазы — в [../kowalski-os-plan.md](../kowalski-os-plan.md).
Здесь — краткая выжимка принципов, которым следует код.

## Слои

```
UI (GTK3: omnibox, chat, tray)          ← тонкие клиенты
        │ D-Bus org.kowalski.Core / unix socket (dev)
kow-core (демон): агентный цикл, tool-реестр,
журнал, политики безопасности, планировщик
        │
Tools (MCP-совместимые схемы) · Память/RAG · Голос
        │
Ollama (LLM/vision/embeddings) · внешние HTTP-сервисы STT/TTS
        │
XFCE 4.18 · Xorg · LightDM · Ubuntu 24.04 · systemd
```

## Принципы

1. **UI ≠ логика.** Вся логика в `kow-core`; интерфейсы (CLI, GTK, голос) — клиенты.
2. **Безопасность с первого дня.** У каждого tool — уровень риска
   (read/write/destructive/network). Политика решает ALLOW/CONFIRM/DENY,
   allowlist путей, подтверждения через UI. Каждый вызов — в журнале SQLite,
   включая отклонённые.
3. **MCP-совместимость без MCP-транспорта.** Первая итерация — in-process
   реестр; дескрипторы tool'ов поле-в-поле совпадают с MCP `Tool`, поэтому
   вынос в отдельные MCP-серверы — механическая операция.
4. **Кроссплатформенная разработка.** Ядро развивается test-first на macOS;
   Linux-специфика (D-Bus, systemd, GTK, fd/plocate) — за тонкими швами
   (`ipc/`, `platform.py`, backend-цепочки) и проверяется в Docker ubuntu:24.04.
5. **X11, не Wayland** — ради xdotool/AT-SPI/скриншотов; абстракции ввода
   закладываются на будущее.
