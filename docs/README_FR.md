## Kowalski OS — parlez à votre ordinateur

[![CI](https://github.com/KPbICO6Ou/kowalski-os/actions/workflows/ci.yml/badge.svg)](https://github.com/KPbICO6Ou/kowalski-os/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](https://github.com/KPbICO6Ou/kowalski-os/blob/main/LICENSE)
[![Python](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Ubuntu%2024.04%20%C2%B7%20XFCE-orange.svg)](https://ubuntu.com/)

Kowalski OS transforme un bureau Linux ordinaire en un bureau auquel vous pouvez tout simplement parler. Demandez-lui en langage courant — en tapant ou à la voix — de trouver un fichier, de programmer un rappel, de résumer un e-mail, d'exécuter une commande ou de regarder ce qui s'affiche à l'écran. L'assistant s'exécute **localement** sur votre propre machine (grâce à [Ollama](https://ollama.com)), de sorte que vos données ne quittent jamais votre ordinateur.

[English](https://github.com/KPbICO6Ou/kowalski-os/blob/main/README.md) | [Español](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_ES.md) | [Português](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_PT.md) | **[Français](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_FR.md)** | [Deutsch](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_DE.md) | [Italiano](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_IT.md) | [Русский](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_RU.md) | [中文](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_ZH.md) | [日本語](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_JA.md) | [हिन्दी](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_HI.md) | [한국어](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_KR.md)

### Que peut-il faire ?

Une fois installé, vous pouvez taper des choses comme :

```bash
kow ask "how much free disk space do I have?"
kow ask "find the budget spreadsheet I edited last week and open it"
kow ask "remind me in 20 minutes to call mom"
kow ask "summarize my latest email from Anna"
kow ask --plan "research topic X, then write a short note about it"
```

- **Trouver des choses** — par nom, par contenu ou par sens (« le document à propos du voyage »).
- **Se souvenir** — des notes, des rappels et des informations vous concernant qu'il pourra rappeler plus tard.
- **E-mail** — chercher, lire, rédiger et (avec votre accord) envoyer.
- **Voir votre écran** — répondre à « qu'est-ce qui s'affiche à l'écran en ce moment ? ».
- **Agir** — ouvrir des applications, contrôler les fenêtres, exécuter des commandes shell, automatiser des tâches en plusieurs étapes.
- **Parler** — un mode vocal mains libres (mot d'activation → reconnaissance vocale → réponse → synthèse vocale).

### Est-ce sûr ?

Oui, par conception :

- L'assistant ne peut accéder qu'aux dossiers que vous autorisez.
- Toute action risquée — envoyer un e-mail, exécuter une commande, taper dans une fenêtre — **vous demande d'abord confirmation**, et vous pouvez refuser.
- Les commandes shell s'exécutent dans un bac à sable sous Linux.
- Chaque action est consignée dans un journal local que vous pouvez consulter avec `kow journal tail`.
- Le modèle de langage s'exécute localement grâce à Ollama — rien n'est envoyé vers le cloud.

### Prérequis

- **Ubuntu 24.04** avec le bureau XFCE (vous pouvez aussi exécuter l'assistant sur macOS pour le développement).
- **[Ollama](https://ollama.com)** avec un modèle prenant en charge l'appel d'outils, par exemple `qwen2.5:14b` (ou `qwen2.5:7b` sur une machine plus modeste).
- Un **GPU est recommandé** pour des réponses rapides, mais il n'est pas obligatoire.

### Installation (Ubuntu)

Installez l'assistant principal et lancez-le en arrière-plan :

```bash
sudo apt install ./kowalski-core_*.deb        # the assistant + the `kow` command
systemctl --user enable --now kowalski-core   # run it as a background service
```

Ajoutez les composants optionnels quand vous le souhaitez :

```bash
sudo apt install ./kowalski-ui_*.deb       # the Omnibox (Super+Space) + desktop theme
sudo apt install ./kowalski-voice_*.deb    # hands-free voice mode
sudo apt install ./kowalski-indexer_*.deb  # semantic file search
```

> Vous n'avez pas encore les fichiers `.deb` ? Construisez-les avec `make deb` (nécessite Docker), ou utilisez la configuration développeur ci-dessous.

### Essayez-le (configuration développeur — Linux ou macOS)

```bash
git clone https://github.com/KPbICO6Ou/kowalski-os.git
cd kowalski-os
make venv                       # create a virtualenv with the dev tools
.venv/bin/pip install -e core   # install the assistant core
ollama pull qwen2.5:7b          # download a local model
.venv/bin/kow ask "how much free disk space do I have?"
```

### Premiers pas

```bash
kow ask "..."             # ask once and get an answer
kow ask --plan "..."      # for bigger tasks: it makes a plan and works through it
kow ask --continue "..."  # keep the same conversation going
kow tools list            # see everything the assistant can do
kow journal tail          # see what it has done
kow serve                 # run it as a background service for the desktop apps
```

### Comment c'est organisé

Kowalski OS possède un seul « cerveau » — le service `kow-core` — auquel chaque interface s'adresse : la ligne de commande aujourd'hui, et l'Omnibox, la voix et les fenêtres de discussion sur le bureau. Ainsi, l'assistant se comporte de la même manière partout.

| Composant | Ce que c'est |
|---|---|
| `core/` | le cerveau de l'assistant : la compréhension des demandes, les outils, les règles de sécurité, le journal |
| `ui/` | l'Omnibox (appuyez sur Super+Space) et les éléments de bureau |
| `voice/` | mot d'activation, reconnaissance vocale, synthèse vocale |
| `indexer/` | recherche sémantique de fichiers |
| `setup/` | l'assistant de configuration au premier lancement |
| `provision/` | les scripts qui installent l'ensemble du système sur une machine neuve |
| `packaging/` | les paquets `.deb` et le thème de bureau |

Plus de détails : [Architecture](docs/architecture.md) · [Installation sur une machine](docs/provisioning.md) · [Packaging](docs/packaging.md).

### État du projet

Kowalski OS est en **développement précoce**. L'assistant fonctionne aujourd'hui via la ligne de commande ; les éléments du bureau graphique (la fenêtre Omnibox, la voix, l'installation complète du système) sont développés et testés, mais nécessitent une véritable machine Linux dotée d'un GPU pour prendre pleinement vie. Attendez-vous à quelques aspérités.

### Licence

[Apache-2.0](LICENSE).
