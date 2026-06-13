## Kowalski OS — parla con il tuo computer

[![CI](https://github.com/KPbICO6Ou/kowalski-os/actions/workflows/ci.yml/badge.svg)](https://github.com/KPbICO6Ou/kowalski-os/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](https://github.com/KPbICO6Ou/kowalski-os/blob/main/LICENSE)
[![Python](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Ubuntu%2024.04%20%C2%B7%20XFCE-orange.svg)](https://ubuntu.com/)

Kowalski OS trasforma un comune desktop Linux in uno con cui puoi semplicemente parlare. Chiedigli con parole semplici — scrivendo o con la voce — di trovare un file, impostare un promemoria, riassumere un'email, eseguire un comando o guardare cosa c'è sul tuo schermo. L'assistente funziona **localmente** sul tuo computer (tramite [Ollama](https://ollama.com)), quindi i tuoi dati non lasciano mai il tuo computer.

[English](https://github.com/KPbICO6Ou/kowalski-os/blob/main/README.md) | [Español](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_ES.md) | [Português](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_PT.md) | [Français](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_FR.md) | [Deutsch](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_DE.md) | **[Italiano](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_IT.md)** | [Русский](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_RU.md) | [中文](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_ZH.md) | [日本語](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_JA.md) | [हिन्दी](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_HI.md) | [한국어](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_KR.md)

### Cosa può fare?

Dopo l'installazione, puoi scrivere cose come:

```bash
kow ask "how much free disk space do I have?"
kow ask "find the budget spreadsheet I edited last week and open it"
kow ask "remind me in 20 minutes to call mom"
kow ask "summarize my latest email from Anna"
kow ask --plan "research topic X, then write a short note about it"
```

- **Trovare cose** — per nome, per contenuto o per significato ("il documento sul viaggio").
- **Ricordare** — note, promemoria e fatti su di te che può richiamare in seguito.
- **Email** — cercare, leggere, comporre e (con la tua approvazione) inviare.
- **Vedere il tuo schermo** — rispondere a "cosa c'è sullo schermo in questo momento?".
- **Fare cose** — aprire app, gestire le finestre, eseguire comandi shell, automatizzare attività in più passaggi.
- **Parlare** — una modalità vocale a mani libere (parola di attivazione → trascrizione vocale → risposta → sintesi vocale).

### È sicuro?

Sì, fin dalla progettazione:

- L'assistente può accedere solo alle cartelle che gli consenti.
- Qualsiasi azione rischiosa — inviare un'email, eseguire un comando, scrivere in una finestra — **chiede prima la tua conferma**, e puoi rifiutare.
- I comandi shell vengono eseguiti in un sandbox su Linux.
- Ogni azione viene registrata in un log locale che puoi consultare con `kow journal tail`.
- Il modello linguistico funziona localmente tramite Ollama — nulla viene inviato al cloud.

### Requisiti

- **Ubuntu 24.04** con il desktop XFCE (puoi anche eseguire l'assistente su macOS per lo sviluppo).
- **[Ollama](https://ollama.com)** con un modello che supporta il tool-calling, ad esempio `qwen2.5:14b` (oppure `qwen2.5:7b` su una macchina più piccola).
- Una **GPU è consigliata** per risposte rapide, ma non è obbligatoria.

### Installazione (Ubuntu)

Installa il nucleo dell'assistente e avvialo in background:

```bash
sudo apt install ./kowalski-core_*.deb        # the assistant + the `kow` command
systemctl --user enable --now kowalski-core   # run it as a background service
```

Aggiungi i componenti opzionali quando li desideri:

```bash
sudo apt install ./kowalski-ui_*.deb       # the Omnibox (Super+Space) + desktop theme
sudo apt install ./kowalski-voice_*.deb    # hands-free voice mode
sudo apt install ./kowalski-indexer_*.deb  # semantic file search
```

> Non hai ancora i file `.deb`? Compilali con `make deb` (richiede Docker), oppure usa la configurazione per sviluppatori qui sotto.

### Provalo (configurazione per sviluppatori — Linux o macOS)

```bash
git clone https://github.com/KPbICO6Ou/kowalski-os.git
cd kowalski-os
make venv                       # create a virtualenv with the dev tools
.venv/bin/pip install -e core   # install the assistant core
ollama pull qwen2.5:7b          # download a local model
.venv/bin/kow ask "how much free disk space do I have?"
```

### Primi passi

```bash
kow ask "..."             # ask once and get an answer
kow ask --plan "..."      # for bigger tasks: it makes a plan and works through it
kow ask --continue "..."  # keep the same conversation going
kow tools list            # see everything the assistant can do
kow journal tail          # see what it has done
kow serve                 # run it as a background service for the desktop apps
```

### Come è organizzato

Kowalski OS ha un unico "cervello" — il servizio `kow-core` — con cui ogni interfaccia comunica: oggi la riga di comando, e l'Omnibox, la voce e le finestre di chat sul desktop. Così l'assistente si comporta allo stesso modo ovunque.

| Parte | Cos'è |
|---|---|
| `core/` | il cervello dell'assistente: comprensione delle richieste, gli strumenti, le regole di sicurezza, il log |
| `ui/` | l'Omnibox (premi Super+Space) e i componenti del desktop |
| `voice/` | parola di attivazione, trascrizione vocale, sintesi vocale |
| `indexer/` | ricerca semantica dei file |
| `setup/` | la procedura guidata di configurazione al primo avvio |
| `provision/` | script che installano l'intero sistema su una macchina nuova |
| `packaging/` | i pacchetti `.deb` e il tema del desktop |

Maggiori dettagli: [Architecture](docs/architecture.md) · [Installing on a machine](docs/provisioning.md) · [Packaging](docs/packaging.md).

### Stato del progetto

Kowalski OS è in **fase iniziale di sviluppo**. L'assistente funziona già oggi tramite la riga di comando; i componenti grafici del desktop (la finestra Omnibox, la voce, l'installazione completa del sistema) sono realizzati e testati ma hanno bisogno di una vera macchina Linux con una GPU per prendere pienamente vita. Aspettati qualche imperfezione.

### Licenza

[Apache-2.0](LICENSE).
