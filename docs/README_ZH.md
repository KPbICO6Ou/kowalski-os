## Kowalski OS — 和你的电脑对话

[![CI](https://github.com/KPbICO6Ou/kowalski-os/actions/workflows/ci.yml/badge.svg)](https://github.com/KPbICO6Ou/kowalski-os/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](https://github.com/KPbICO6Ou/kowalski-os/blob/main/LICENSE)
[![Python](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Ubuntu%2024.04%20%C2%B7%20XFCE-orange.svg)](https://ubuntu.com/)

Kowalski OS 让一台普通的 Linux 桌面电脑变成你可以直接对话的电脑。用日常的话告诉它——可以打字，也可以语音——去查找文件、设置提醒、总结一封邮件、运行某个命令，或者看看屏幕上有什么。这个助手在你自己的电脑上**本地**运行（借助 [Ollama](https://ollama.com)），所以你的数据永远不会离开你的电脑。

[English](https://github.com/KPbICO6Ou/kowalski-os/blob/main/README.md) | [Español](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_ES.md) | [Português](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_PT.md) | [Français](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_FR.md) | [Deutsch](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_DE.md) | [Italiano](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_IT.md) | [Русский](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_RU.md) | **[中文](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_ZH.md)** | [日本語](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_JA.md) | [हिन्दी](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_HI.md) | [한국어](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_KR.md)

### 它能做什么？

安装之后，你可以输入这样的话：

```bash
kow ask "how much free disk space do I have?"
kow ask "find the budget spreadsheet I edited last week and open it"
kow ask "remind me in 20 minutes to call mom"
kow ask "summarize my latest email from Anna"
kow ask --plan "research topic X, then write a short note about it"
```

- **查找东西**——按名称、按内容，或者按含义（“关于那次旅行的文档”）。
- **记住**——它可以记下笔记、提醒，以及关于你的信息，以后再为你回忆起来。
- **邮件**——搜索、阅读、起草，并（在你同意后）发送邮件。
- **看你的屏幕**——回答“现在屏幕上有什么？”。
- **做事情**——打开应用、控制窗口、运行 shell 命令、自动完成多步骤任务。
- **说话**——一种免手动的语音模式（唤醒词 → 语音转文字 → 回答 → 文字转语音）。

### 它安全吗？

是的，从设计上就是安全的：

- 助手只能访问你允许它访问的文件夹。
- 任何有风险的操作——发送邮件、运行命令、向窗口里输入内容——都会**先征求你的确认**，你可以拒绝。
- shell 命令在 Linux 上的沙箱内运行。
- 每一个操作都会写入一份本地日志，你可以用 `kow journal tail` 来查看。
- 语言模型通过 Ollama 在本地运行——没有任何内容会被发送到云端。

### 系统要求

- **Ubuntu 24.04**，并安装 XFCE 桌面（你也可以在 macOS 上运行助手以用于开发）。
- **[Ollama](https://ollama.com)**，并使用一个支持工具调用的模型，例如 `qwen2.5:14b`（在配置较低的电脑上可以用 `qwen2.5:7b`）。
- **建议使用 GPU** 以获得更快的回答，但这不是必需的。

### 安装（Ubuntu）

安装核心助手并在后台启动它：

```bash
sudo apt install ./kowalski-core_*.deb        # the assistant + the `kow` command
systemctl --user enable --now kowalski-core   # run it as a background service
```

需要的时候随时添加可选组件：

```bash
sudo apt install ./kowalski-ui_*.deb       # the Omnibox (Super+Space) + desktop theme
sudo apt install ./kowalski-voice_*.deb    # hands-free voice mode
sudo apt install ./kowalski-indexer_*.deb  # semantic file search
```

> 还没有 `.deb` 文件？用 `make deb` 来构建它们（需要 Docker），或者使用下面的开发者安装方式。

### 试一试（开发者安装——Linux 或 macOS）

```bash
git clone https://github.com/KPbICO6Ou/kowalski-os.git
cd kowalski-os
make venv                       # create a virtualenv with the dev tools
.venv/bin/pip install -e core   # install the assistant core
ollama pull qwen2.5:7b          # download a local model
.venv/bin/kow ask "how much free disk space do I have?"
```

### 第一步

```bash
kow ask "..."             # ask once and get an answer
kow ask --plan "..."      # for bigger tasks: it makes a plan and works through it
kow ask --continue "..."  # keep the same conversation going
kow tools list            # see everything the assistant can do
kow journal tail          # see what it has done
kow serve                 # run it as a background service for the desktop apps
```

### 它是如何组织的

Kowalski OS 有一个“大脑”——`kow-core` 服务——每一个界面都与它对话：今天是命令行，以及桌面上的 Omnibox、语音和聊天窗口。因此助手在任何地方的表现都是一致的。

| 组成部分 | 它是什么 |
|---|---|
| `core/` | 助手的大脑：理解请求、各种工具、安全规则、日志 |
| `ui/` | Omnibox（按 Super+Space）和桌面相关部分 |
| `voice/` | 唤醒词、语音转文字、文字转语音 |
| `indexer/` | 语义文件搜索 |
| `setup/` | 首次运行的安装向导 |
| `provision/` | 把整个系统安装到一台全新机器上的脚本 |
| `packaging/` | `.deb` 软件包和桌面主题 |

更多细节：[Architecture](docs/architecture.md) · [Installing on a machine](docs/provisioning.md) · [Packaging](docs/packaging.md)。

### 项目状态

Kowalski OS 正处于**早期开发阶段**。助手目前已经可以通过命令行使用；图形化的桌面部分（Omnibox 窗口、语音、完整的系统安装）已经构建并经过测试，但需要一台带 GPU 的真实 Linux 机器才能完全运转起来。请预期会有一些不完善之处。

### 许可证

[Apache-2.0](LICENSE)。
