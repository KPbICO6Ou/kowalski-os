# Kowalski OS

AI-нативная графическая среда на базе Ubuntu 24.04 + XFCE: постоянный LLM-демон
(`kow-core`) — системный слой, GUI-приложения — тонкие клиенты через D-Bus.
Полная концепция и фазы — в [kowalski-os-plan.md](kowalski-os-plan.md).

## Состав монорепо

| Каталог | Что это | Фаза |
|---|---|---|
| `provision/` | autoinstall (cloud-init) + Ansible-роли: ОС → драйверы → CUDA → Docker → Ollama → XFCE | 0 |
| `core/` | `kow-core`: агентный демон, tool-реестр, политики безопасности, журнал; CLI `kow` | 1 |
| `setup/` | `kow-setup`: мастер первого запуска (CLI), проверки Ollama/STT/TTS | 0 |
| `ui/` | Omnibox, чат, трей (GTK3) | 1–2 |
| `voice/` | wake word + VAD + клиенты STT/TTS | 3 |
| `indexer/` | семантический файловый индекс (sqlite-vec) | 2 |
| `packaging/` | systemd units, .deb, ISO | 6 |

## Быстрый старт (разработка)

```bash
make venv          # python3 -m venv + dev-зависимости
make lint          # yamllint + ansible-lint + ruff
make syntax        # ansible-playbook --syntax-check
make test          # pytest для core/ и setup/
make test-provision  # smoke-тест Ansible-ролей в Docker (ubuntu:24.04)
```

Ядро для локальной разработки (нужен установленный [Ollama](https://ollama.com)):

```bash
.venv/bin/pip install -e core
ollama pull qwen2.5:7b
.venv/bin/kow ask "сколько свободного места на диске?"
```

## Документация

- [docs/architecture.md](docs/architecture.md) — слои и принципы
- [docs/provisioning.md](docs/provisioning.md) — установка на железо, USB, ansible-pull

## Лицензия

Apache-2.0, см. [LICENSE](LICENSE).
