## Kowalski OS — sprich mit deinem Computer

[![CI](https://github.com/KPbICO6Ou/kowalski-os/actions/workflows/ci.yml/badge.svg)](https://github.com/KPbICO6Ou/kowalski-os/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](https://github.com/KPbICO6Ou/kowalski-os/blob/main/LICENSE)
[![Python](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Ubuntu%2024.04%20%C2%B7%20XFCE-orange.svg)](https://ubuntu.com/)

Kowalski OS macht aus einem gewöhnlichen Linux-Desktop einen, mit dem du einfach sprechen kannst. Bitte ihn mit ganz normalen Worten — getippt oder per Stimme — eine Datei zu finden, eine Erinnerung einzurichten, eine E-Mail zusammenzufassen, einen Befehl auszuführen oder anzuschauen, was gerade auf deinem Bildschirm zu sehen ist. Der Assistent läuft **lokal** auf deinem eigenen Rechner (über [Ollama](https://ollama.com)), sodass deine Daten deinen Computer niemals verlassen.

[English](https://github.com/KPbICO6Ou/kowalski-os/blob/main/README.md) | [Español](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_ES.md) | [Português](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_PT.md) | [Français](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_FR.md) | **[Deutsch](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_DE.md)** | [Italiano](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_IT.md) | [Русский](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_RU.md) | [中文](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_ZH.md) | [日本語](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_JA.md) | [हिन्दी](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_HI.md) | [한국어](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_KR.md)

### Was kann es?

Nach der Installation kannst du zum Beispiel Folgendes eingeben:

```bash
kow ask "how much free disk space do I have?"
kow ask "find the budget spreadsheet I edited last week and open it"
kow ask "remind me in 20 minutes to call mom"
kow ask "summarize my latest email from Anna"
kow ask --plan "research topic X, then write a short note about it"
```

- **Dinge finden** — nach Name, nach Inhalt oder nach Bedeutung ("das Dokument über die Reise").
- **Sich erinnern** — Notizen, Erinnerungen und Fakten über dich, die er später wieder abrufen kann.
- **E-Mail** — durchsuchen, lesen, entwerfen und (mit deiner Zustimmung) senden.
- **Deinen Bildschirm sehen** — die Frage beantworten "Was ist gerade auf dem Bildschirm zu sehen?".
- **Dinge erledigen** — Apps öffnen, Fenster steuern, Shell-Befehle ausführen, mehrstufige Aufgaben automatisieren.
- **Sprechen** — ein freihändiger Sprachmodus (Aktivierungswort → Sprache-zu-Text → Antwort → Text-zu-Sprache).

### Ist es sicher?

Ja, von Grund auf:

- Der Assistent kann nur auf Ordner zugreifen, die du erlaubst.
- Alles Riskante — eine E-Mail senden, einen Befehl ausführen, in ein Fenster tippen — **fragt zuerst nach deiner Bestätigung**, und du kannst nein sagen.
- Shell-Befehle laufen unter Linux in einer Sandbox.
- Jede Aktion wird in ein lokales Protokoll geschrieben, das du mit `kow journal tail` einsehen kannst.
- Das Sprachmodell läuft lokal über Ollama — nichts wird in die Cloud gesendet.

### Voraussetzungen

- **Ubuntu 24.04** mit dem XFCE-Desktop (du kannst den Assistenten für die Entwicklung auch auf macOS ausführen).
- **[Ollama](https://ollama.com)** mit einem Modell, das Tool-Calling unterstützt, z. B. `qwen2.5:14b` (oder `qwen2.5:7b` auf einem kleineren Rechner).
- Eine **GPU wird empfohlen** für schnelle Antworten, ist aber nicht erforderlich.

### Installation (Ubuntu)

Installiere den Kern-Assistenten und starte ihn im Hintergrund:

```bash
sudo apt install ./kowalski-core_*.deb        # the assistant + the `kow` command
systemctl --user enable --now kowalski-core   # run it as a background service
```

Füge optionale Komponenten hinzu, wann immer du sie haben möchtest:

```bash
sudo apt install ./kowalski-ui_*.deb       # the Omnibox (Super+Space) + desktop theme
sudo apt install ./kowalski-voice_*.deb    # hands-free voice mode
sudo apt install ./kowalski-indexer_*.deb  # semantic file search
```

> Du hast die `.deb`-Dateien noch nicht? Erstelle sie mit `make deb` (erfordert Docker), oder nutze die Entwickler-Einrichtung weiter unten.

### Probier es aus (Entwickler-Einrichtung — Linux oder macOS)

```bash
git clone https://github.com/KPbICO6Ou/kowalski-os.git
cd kowalski-os
make venv                       # create a virtualenv with the dev tools
.venv/bin/pip install -e core   # install the assistant core
ollama pull qwen2.5:7b          # download a local model
.venv/bin/kow ask "how much free disk space do I have?"
```

### Erste Schritte

```bash
kow ask "..."             # ask once and get an answer
kow ask --plan "..."      # for bigger tasks: it makes a plan and works through it
kow ask --continue "..."  # keep the same conversation going
kow tools list            # see everything the assistant can do
kow journal tail          # see what it has done
kow serve                 # run it as a background service for the desktop apps
```

### Wie es aufgebaut ist

Kowalski OS hat ein einziges "Gehirn" — den `kow-core`-Dienst — mit dem jede Schnittstelle spricht: heute die Kommandozeile sowie die Omnibox-, Sprach- und Chat-Fenster auf dem Desktop. So verhält sich der Assistent überall gleich.

| Teil | Was es ist |
|---|---|
| `core/` | das Gehirn des Assistenten: Anfragen verstehen, die Tools, die Sicherheitsregeln, das Protokoll |
| `ui/` | die Omnibox (drücke Super+Space) und die Desktop-Bestandteile |
| `voice/` | Aktivierungswort, Sprache-zu-Text, Text-zu-Sprache |
| `indexer/` | semantische Dateisuche |
| `setup/` | der Einrichtungsassistent für den ersten Start |
| `provision/` | Skripte, die das gesamte System auf einem frischen Rechner installieren |
| `packaging/` | die `.deb`-Pakete und das Desktop-Theme |

Mehr Details: [Architecture](docs/architecture.md) · [Installing on a machine](docs/provisioning.md) · [Packaging](docs/packaging.md).

### Projektstatus

Kowalski OS befindet sich in **früher Entwicklung**. Der Assistent funktioniert heute über die Kommandozeile; die grafischen Desktop-Bestandteile (das Omnibox-Fenster, die Stimme, die vollständige Systeminstallation) sind gebaut und getestet, brauchen aber einen echten Linux-Rechner mit GPU, um voll zur Geltung zu kommen. Rechne mit ein paar Ecken und Kanten.

### Lizenz

[Apache-2.0](LICENSE).
