# Architecture

The detailed concept, modules and phases are in
[../kowalski-os-plan.md](../kowalski-os-plan.md) (working document).
This page is a short summary of the principles the code follows.

## Layers

```
UI (GTK3: omnibox, chat, tray)          ← thin clients
        │ D-Bus org.kowalski.Core / unix socket (dev)
kow-core (daemon): agent loop, tool registry,
action journal, security policies, scheduler
        │
Tools (MCP-shaped schemas) · Memory/RAG · Voice
        │
Ollama (LLM/vision/embeddings) · external HTTP STT/TTS services
        │
XFCE 4.18 · Xorg · LightDM · Ubuntu 24.04 · systemd
```

## Principles

1. **UI ≠ logic.** All logic lives in `kow-core`; interfaces (CLI, GTK, voice)
   are clients.
2. **Security from day one.** Every tool carries a risk level
   (read/write/destructive/network). The policy decides ALLOW/CONFIRM/DENY,
   with a path allowlist and UI confirmations. Every invocation lands in the
   SQLite journal — including denied ones.
3. **MCP compatibility without MCP transport.** The first iteration uses an
   in-process registry; tool descriptors match the MCP `Tool` shape
   field-for-field, so extracting real MCP servers later is mechanical.
4. **Cross-platform development.** The core is developed test-first on macOS;
   Linux specifics (D-Bus, systemd, GTK, fd/plocate) sit behind thin seams
   (`ipc/`, `platform.py`, backend chains) and are exercised in a Docker
   ubuntu:24.04 container.
5. **X11, not Wayland** — for xdotool/AT-SPI/screenshots; input abstractions
   are designed with a future Wayland port in mind.
