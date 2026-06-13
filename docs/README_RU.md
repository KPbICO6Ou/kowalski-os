## Kowalski OS — разговаривайте со своим компьютером

[![CI](https://github.com/KPbICO6Ou/kowalski-os/actions/workflows/ci.yml/badge.svg)](https://github.com/KPbICO6Ou/kowalski-os/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](https://github.com/KPbICO6Ou/kowalski-os/blob/main/LICENSE)
[![Python](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Ubuntu%2024.04%20%C2%B7%20XFCE-orange.svg)](https://ubuntu.com/)

Kowalski OS превращает обычный рабочий стол Linux в такой, с которым можно просто разговаривать. Попросите его обычными словами — набрав текст или голосом — найти файл, поставить напоминание, кратко изложить письмо, выполнить команду или посмотреть, что у вас на экране. Ассистент работает **локально** на вашей собственной машине (через [Ollama](https://ollama.com)), поэтому ваши данные никогда не покидают ваш компьютер.

[English](https://github.com/KPbICO6Ou/kowalski-os/blob/main/README.md) | [Español](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_ES.md) | [Português](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_PT.md) | [Français](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_FR.md) | [Deutsch](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_DE.md) | [Italiano](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_IT.md) | **[Русский](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_RU.md)** | [中文](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_ZH.md) | [日本語](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_JA.md) | [हिन्दी](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_HI.md) | [한국어](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_KR.md)

### Что он умеет?

После установки вы можете писать что-то вроде:

```bash
kow ask "how much free disk space do I have?"
kow ask "find the budget spreadsheet I edited last week and open it"
kow ask "remind me in 20 minutes to call mom"
kow ask "summarize my latest email from Anna"
kow ask --plan "research topic X, then write a short note about it"
```

- **Находить вещи** — по имени, по содержимому или по смыслу («документ про поездку»).
- **Запоминать** — заметки, напоминания и факты о вас, которые он сможет вспомнить позже.
- **Электронная почта** — искать, читать, составлять черновики и (с вашего одобрения) отправлять.
- **Видеть ваш экран** — отвечать на вопрос «что сейчас на экране?».
- **Делать дела** — открывать приложения, управлять окнами, выполнять команды оболочки, автоматизировать многошаговые задачи.
- **Говорить** — голосовой режим без рук (ключевое слово → распознавание речи → ответ → синтез речи).

### Это безопасно?

Да, так задумано:

- Ассистент может обращаться только к тем папкам, которые вы разрешили.
- Всё рискованное — отправка письма, выполнение команды, ввод текста в окно — **сначала запрашивает ваше подтверждение**, и вы можете отказаться.
- Команды оболочки выполняются в песочнице на Linux.
- Каждое действие записывается в локальный журнал, который вы можете просмотреть командой `kow journal tail`.
- Языковая модель работает локально через Ollama — ничего не отправляется в облако.

### Требования

- **Ubuntu 24.04** с рабочим столом XFCE (для разработки ассистента можно также запускать на macOS).
- **[Ollama](https://ollama.com)** с моделью, поддерживающей вызов инструментов, например `qwen2.5:14b` (или `qwen2.5:7b` на менее мощной машине).
- **GPU рекомендуется** для быстрых ответов, но он не обязателен.

### Установка (Ubuntu)

Установите основной ассистент и запустите его в фоновом режиме:

```bash
sudo apt install ./kowalski-core_*.deb        # the assistant + the `kow` command
systemctl --user enable --now kowalski-core   # run it as a background service
```

Добавляйте дополнительные компоненты, когда они вам понадобятся:

```bash
sudo apt install ./kowalski-ui_*.deb       # the Omnibox (Super+Space) + desktop theme
sudo apt install ./kowalski-voice_*.deb    # hands-free voice mode
sudo apt install ./kowalski-indexer_*.deb  # semantic file search
```

> Ещё нет файлов `.deb`? Соберите их командой `make deb` (требуется Docker) или воспользуйтесь настройкой для разработчиков ниже.

### Попробовать (настройка для разработчиков — Linux или macOS)

```bash
git clone https://github.com/KPbICO6Ou/kowalski-os.git
cd kowalski-os
make venv                       # create a virtualenv with the dev tools
.venv/bin/pip install -e core   # install the assistant core
ollama pull qwen2.5:7b          # download a local model
.venv/bin/kow ask "how much free disk space do I have?"
```

### Первые шаги

```bash
kow ask "..."             # ask once and get an answer
kow ask --plan "..."      # for bigger tasks: it makes a plan and works through it
kow ask --continue "..."  # keep the same conversation going
kow tools list            # see everything the assistant can do
kow journal tail          # see what it has done
kow serve                 # run it as a background service for the desktop apps
```

### Как это устроено

У Kowalski OS есть один «мозг» — служба `kow-core`, с которой общается каждый интерфейс: сегодня это командная строка, а на рабочем столе — Omnibox, голос и окна чата. Поэтому ассистент ведёт себя одинаково повсюду.

| Часть | Что это |
|---|---|
| `core/` | мозг ассистента: понимание запросов, инструменты, правила безопасности, журнал |
| `ui/` | Omnibox (нажмите Super+Space) и компоненты рабочего стола |
| `voice/` | ключевое слово, распознавание речи, синтез речи |
| `indexer/` | семантический поиск по файлам |
| `setup/` | мастер первоначальной настройки |
| `provision/` | скрипты, устанавливающие всю систему на чистую машину |
| `packaging/` | пакеты `.deb` и тема оформления рабочего стола |

Подробнее: [Архитектура](docs/ARCHITECTURE.md) · [Установка на машину](docs/PROVISIONING.md) · [Упаковка](docs/PACKAGING.md).

### Статус проекта

Kowalski OS находится в **ранней стадии разработки**. Ассистент уже работает через командную строку; графические компоненты рабочего стола (окно Omnibox, голос, полная установка системы) собраны и протестированы, но для полноценной работы им нужна настоящая машина с Linux и GPU. Ожидайте шероховатостей.

### Лицензия

[Apache-2.0](LICENSE).
