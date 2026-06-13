## Kowalski OS — converse com o seu computador

[![CI](https://github.com/KPbICO6Ou/kowalski-os/actions/workflows/ci.yml/badge.svg)](https://github.com/KPbICO6Ou/kowalski-os/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](https://github.com/KPbICO6Ou/kowalski-os/blob/main/LICENSE)
[![Python](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Ubuntu%2024.04%20%C2%B7%20XFCE-orange.svg)](https://ubuntu.com/)

O Kowalski OS transforma um computador Linux comum em um com o qual você pode simplesmente conversar. Peça em palavras simples — digitando ou por voz — para encontrar um arquivo, definir um lembrete, resumir um e-mail, executar um comando ou olhar o que está na sua tela. O assistente roda **localmente** na sua própria máquina (através do [Ollama](https://ollama.com)), então os seus dados nunca saem do seu computador.

[English](https://github.com/KPbICO6Ou/kowalski-os/blob/main/README.md) | [Español](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_ES.md) | **[Português](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_PT.md)** | [Français](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_FR.md) | [Deutsch](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_DE.md) | [Italiano](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_IT.md) | [Русский](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_RU.md) | [中文](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_ZH.md) | [日本語](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_JA.md) | [हिन्दी](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_HI.md) | [한국어](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_KR.md)

### O que ele consegue fazer?

Depois de instalar, você pode digitar coisas como:

```bash
kow ask "how much free disk space do I have?"
kow ask "find the budget spreadsheet I edited last week and open it"
kow ask "remind me in 20 minutes to call mom"
kow ask "summarize my latest email from Anna"
kow ask --plan "research topic X, then write a short note about it"
```

- **Encontrar coisas** — por nome, por conteúdo ou por significado ("o documento sobre a viagem").
- **Lembrar** — anotações, lembretes e fatos sobre você que ele pode recuperar depois.
- **E-mail** — pesquisar, ler, redigir e (com a sua aprovação) enviar.
- **Ver a sua tela** — responder "o que está na tela agora?".
- **Fazer coisas** — abrir aplicativos, controlar janelas, executar comandos do shell, automatizar tarefas de várias etapas.
- **Conversar** — um modo de voz com as mãos livres (palavra de ativação → fala para texto → resposta → texto para fala).

### É seguro?

Sim, por concepção:

- O assistente só pode acessar as pastas que você permitir.
- Qualquer coisa arriscada — enviar e-mail, executar um comando, digitar em uma janela — **pede a sua confirmação primeiro**, e você pode dizer não.
- Os comandos do shell rodam dentro de um sandbox no Linux.
- Toda ação é registrada em um log local que você pode revisar com `kow journal tail`.
- O modelo de linguagem roda localmente através do Ollama — nada é enviado para a nuvem.

### Requisitos

- **Ubuntu 24.04** com o desktop XFCE (você também pode rodar o assistente no macOS para desenvolvimento).
- **[Ollama](https://ollama.com)** com um modelo que suporte chamada de ferramentas (tool-calling), por exemplo `qwen2.5:14b` (ou `qwen2.5:7b` em uma máquina menor).
- Uma **GPU é recomendada** para respostas rápidas, mas não é obrigatória.

### Instalação (Ubuntu)

Instale o núcleo do assistente e inicie-o em segundo plano:

```bash
sudo apt install ./kowalski-core_*.deb        # the assistant + the `kow` command
systemctl --user enable --now kowalski-core   # run it as a background service
```

Adicione componentes opcionais sempre que quiser:

```bash
sudo apt install ./kowalski-ui_*.deb       # the Omnibox (Super+Space) + desktop theme
sudo apt install ./kowalski-voice_*.deb    # hands-free voice mode
sudo apt install ./kowalski-indexer_*.deb  # semantic file search
```

> Ainda não tem os arquivos `.deb`? Construa-os com `make deb` (requer Docker), ou use a configuração para desenvolvedores abaixo.

### Experimente (configuração para desenvolvedores — Linux ou macOS)

```bash
git clone https://github.com/KPbICO6Ou/kowalski-os.git
cd kowalski-os
make venv                       # create a virtualenv with the dev tools
.venv/bin/pip install -e core   # install the assistant core
ollama pull qwen2.5:7b          # download a local model
.venv/bin/kow ask "how much free disk space do I have?"
```

### Primeiros passos

```bash
kow ask "..."             # ask once and get an answer
kow ask --plan "..."      # for bigger tasks: it makes a plan and works through it
kow ask --continue "..."  # keep the same conversation going
kow tools list            # see everything the assistant can do
kow journal tail          # see what it has done
kow serve                 # run it as a background service for the desktop apps
```

### Como ele é organizado

O Kowalski OS tem um único "cérebro" — o serviço `kow-core` — com o qual cada interface conversa: a linha de comando hoje, e a Omnibox, a voz e as janelas de chat no desktop. Assim, o assistente se comporta da mesma forma em todos os lugares.

| Parte | O que é |
|---|---|
| `core/` | o cérebro do assistente: compreender pedidos, as ferramentas, as regras de segurança, o log |
| `ui/` | a Omnibox (pressione Super+Space) e os elementos do desktop |
| `voice/` | palavra de ativação, fala para texto, texto para fala |
| `indexer/` | pesquisa semântica de arquivos |
| `setup/` | o assistente de configuração de primeira execução |
| `provision/` | scripts que instalam o sistema inteiro em uma máquina nova |
| `packaging/` | os pacotes `.deb` e o tema do desktop |

Mais detalhes: [Arquitetura](docs/architecture.md) · [Instalando em uma máquina](docs/provisioning.md) · [Empacotamento](docs/packaging.md).

### Estado do projeto

O Kowalski OS está em **desenvolvimento inicial**. O assistente já funciona hoje pela linha de comando; os elementos gráficos do desktop (a janela da Omnibox, a voz, a instalação completa do sistema) estão construídos e testados, mas precisam de uma máquina Linux real com uma GPU para ganhar vida plenamente. Espere algumas arestas a aparar.

### Licença

[Apache-2.0](LICENSE).
