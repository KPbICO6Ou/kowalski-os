## Kowalski OS — talk to your computer

[![CI](https://github.com/KPbICO6Ou/kowalski-os/actions/workflows/ci.yml/badge.svg)](https://github.com/KPbICO6Ou/kowalski-os/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](https://github.com/KPbICO6Ou/kowalski-os/blob/main/LICENSE)
[![Python](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Ubuntu%2024.04%20%C2%B7%20XFCE-orange.svg)](https://ubuntu.com/)

Kowalski OS turns an ordinary Linux desktop into one you can simply talk to. Ask it in plain words — by typing or by voice — to find a file, set a reminder, summarize an email, run a command, or look at what's on your screen. The assistant runs **locally** on your own machine (through [Ollama](https://ollama.com)), so your data never leaves your computer.

**[English](https://github.com/KPbICO6Ou/kowalski-os/blob/main/README.md)** | [Español](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_ES.md) | [Português](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_PT.md) | [Français](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_FR.md) | [Deutsch](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_DE.md) | [Italiano](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_IT.md) | [Русский](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_RU.md) | [中文](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_ZH.md) | [日本語](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_JA.md) | [हिन्दी](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_HI.md) | [한국어](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_KR.md)

### What can it do?

After installing, you can type things like:

```bash
kow ask "how much free disk space do I have?"
kow ask "find the budget spreadsheet I edited last week and open it"
kow ask "remind me in 20 minutes to call mom"
kow ask "summarize my latest email from Anna"
kow ask --plan "research topic X, then write a short note about it"
```

- **Find things** — by name, by content, or by meaning ("the document about the trip").
- **Remember** — notes, reminders, and facts about you it can recall later.
- **Email** — search, read, draft, and (with your approval) send.
- **See your screen** — answer "what's on screen right now?".
- **Do things** — open apps, control windows, run shell commands, automate multi-step tasks.
- **Talk** — a hands-free voice mode (wake word → speech-to-text → answer → text-to-speech).

### Is it safe?

Yes, by design:

- The assistant can only touch folders you allow.
- Anything risky — sending email, running a command, typing into a window — **asks for your confirmation first**, and you can say no.
- Shell commands run inside a sandbox on Linux.
- Every action is written to a local log you can review with `kow journal tail`.
- The language model runs locally through Ollama — nothing is sent to the cloud.

### Requirements

- **Ubuntu 24.04** with the XFCE desktop (you can also run the assistant on macOS for development).
- **[Ollama](https://ollama.com)** with a model that supports tool-calling, e.g. `qwen2.5:14b` (or `qwen2.5:7b` on a smaller machine).
- A **GPU is recommended** for fast answers, but it is not required.

### Install (Ubuntu)

Install the core assistant and start it in the background:

```bash
sudo apt install ./kowalski-core_*.deb        # the assistant + the `kow` command
systemctl --user enable --now kowalski-core   # run it as a background service
```

Add optional components whenever you want them:

```bash
sudo apt install ./kowalski-ui_*.deb       # the Omnibox (Super+Space) + desktop theme
sudo apt install ./kowalski-voice_*.deb    # hands-free voice mode
sudo apt install ./kowalski-indexer_*.deb  # semantic file search
```

> Don't have the `.deb` files yet? Build them with `make deb` (requires Docker), or use the developer setup below.

### Try it (developer setup — Linux or macOS)

```bash
git clone https://github.com/KPbICO6Ou/kowalski-os.git
cd kowalski-os
make venv                       # create a virtualenv with the dev tools
.venv/bin/pip install -e core   # install the assistant core
ollama pull qwen2.5:7b          # download a local model
.venv/bin/kow ask "how much free disk space do I have?"
```

### First steps

```bash
kow ask "..."             # ask once and get an answer
kow ask --plan "..."      # for bigger tasks: it makes a plan and works through it
kow ask --continue "..."  # keep the same conversation going
kow tools list            # see everything the assistant can do
kow journal tail          # see what it has done
kow serve                 # run it as a background service for the desktop apps
```

### How it is organized

Kowalski OS has one "brain" — the `kow-core` service — that every interface talks to: the command line today, and the Omnibox, voice, and chat windows on the desktop. So the assistant behaves the same everywhere.

| Part | What it is |
|---|---|
| `core/` | the assistant's brain: understanding requests, the tools, the safety rules, the log |
| `ui/` | the Omnibox (press Super+Space) and desktop pieces |
| `voice/` | wake word, speech-to-text, text-to-speech |
| `indexer/` | semantic file search |
| `setup/` | the first-run setup wizard |
| `provision/` | scripts that install the whole system onto a fresh machine |
| `packaging/` | the `.deb` packages and the desktop theme |

More detail: [Architecture](docs/architecture.md) · [Installing on a machine](docs/provisioning.md) · [Packaging](docs/packaging.md).

### Project status

Kowalski OS is in **early development**. The assistant works today through the command line; the graphical desktop pieces (the Omnibox window, voice, full system installation) are built and tested but need a real Linux machine with a GPU to come fully to life. Expect rough edges.

### License

[Apache-2.0](LICENSE).
