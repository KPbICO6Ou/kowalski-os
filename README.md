# Kowalski OS

An AI-native desktop environment built on Ubuntu 24.04 + XFCE: a persistent LLM
daemon (`kow-core`) acts as a system layer, and GUI applications are thin
clients talking to it over D-Bus. The full concept and phase plan live in
[kowalski-os-plan.md](kowalski-os-plan.md) (Russian, working document).

## Monorepo layout

| Directory | What it is | Phase |
|---|---|---|
| `provision/` | autoinstall (cloud-init) + Ansible roles: OS → drivers → CUDA → Docker → Ollama → XFCE | 0 |
| `core/` | `kow-core`: agent daemon, tool registry, security policies, action journal; `kow` CLI | 1 |
| `setup/` | `kow-setup`: first-run wizard (CLI), Ollama/STT/TTS endpoint checks | 0 |
| `ui/` | Omnibox, chat, tray (GTK3) | 1–2 |
| `voice/` | wake word + VAD + STT/TTS clients | 3 |
| `indexer/` | semantic file index (sqlite-vec) | 2 |
| `packaging/` | systemd units, .deb, ISO | 6 |

## Quick start (development)

```bash
make venv            # python3 -m venv + dev dependencies
make lint            # yamllint + ansible-lint + ruff
make syntax          # ansible-playbook --syntax-check
make test            # pytest across core/ setup/ ui/ indexer/ voice/
make test-provision  # Ansible role smoke test in Docker (ubuntu:24.04)
make deb             # build dist/kowalski_<ver>_<arch>.deb in Docker
make test-deb        # build the .deb, install it in a clean container, smoke-test the CLIs
```

Run the core locally (requires [Ollama](https://ollama.com)):

```bash
.venv/bin/pip install -e core
ollama pull qwen2.5:7b
.venv/bin/kow ask "how much free disk space do I have?"
```

## Documentation

- [docs/architecture.md](docs/architecture.md) — layers and principles
- [docs/provisioning.md](docs/provisioning.md) — bare-metal install, USB, ansible-pull
- [docs/packaging.md](docs/packaging.md) — .deb build, XFCE theme/onboarding, ISO

## License

Apache-2.0, see [LICENSE](LICENSE).
