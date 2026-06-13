## Kowalski OS — 컴퓨터와 대화하세요

[![CI](https://github.com/KPbICO6Ou/kowalski-os/actions/workflows/ci.yml/badge.svg)](https://github.com/KPbICO6Ou/kowalski-os/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](https://github.com/KPbICO6Ou/kowalski-os/blob/main/LICENSE)
[![Python](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Ubuntu%2024.04%20%C2%B7%20XFCE-orange.svg)](https://ubuntu.com/)

Kowalski OS는 평범한 리눅스 데스크톱을 그저 말만 걸면 되는 컴퓨터로 바꿔 줍니다. 일상적인 말로 — 타이핑하거나 음성으로 — 파일을 찾고, 알림을 설정하고, 이메일을 요약하고, 명령을 실행하거나, 화면에 무엇이 있는지 물어보세요. 이 어시스턴트는 ([Ollama](https://ollama.com)를 통해) 여러분의 컴퓨터에서 **로컬로** 실행되므로, 데이터가 컴퓨터를 떠나는 일이 없습니다.

[English](https://github.com/KPbICO6Ou/kowalski-os/blob/main/README.md) | [Español](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_ES.md) | [Português](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_PT.md) | [Français](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_FR.md) | [Deutsch](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_DE.md) | [Italiano](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_IT.md) | [Русский](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_RU.md) | [中文](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_ZH.md) | [日本語](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_JA.md) | [हिन्दी](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_HI.md) | **[한국어](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_KR.md)**

### 무엇을 할 수 있나요?

설치한 뒤에는 이런 식으로 입력할 수 있습니다:

```bash
kow ask "how much free disk space do I have?"
kow ask "find the budget spreadsheet I edited last week and open it"
kow ask "remind me in 20 minutes to call mom"
kow ask "summarize my latest email from Anna"
kow ask --plan "research topic X, then write a short note about it"
```

- **물건 찾기** — 이름으로, 내용으로, 또는 의미로 찾습니다 ("여행에 관한 그 문서").
- **기억하기** — 메모, 알림, 그리고 나중에 떠올릴 수 있는 여러분에 대한 사실들.
- **이메일** — 검색하고, 읽고, 초안을 작성하고, (여러분의 승인을 받아) 발송합니다.
- **화면 보기** — "지금 화면에 무엇이 있지?"에 답합니다.
- **작업 수행** — 앱을 열고, 창을 제어하고, 셸 명령을 실행하고, 여러 단계의 작업을 자동화합니다.
- **대화** — 핸즈프리 음성 모드 (웨이크 워드 → 음성-텍스트 변환 → 답변 → 텍스트-음성 변환).

### 안전한가요?

네, 설계부터 그렇습니다:

- 어시스턴트는 여러분이 허용한 폴더에만 접근할 수 있습니다.
- 위험할 수 있는 모든 일 — 이메일 발송, 명령 실행, 창에 입력하기 — 은 **먼저 여러분의 확인을 요청하며**, 거절할 수 있습니다.
- 셸 명령은 리눅스에서 샌드박스 안에서 실행됩니다.
- 모든 동작은 로컬 로그에 기록되며, `kow journal tail` 로 검토할 수 있습니다.
- 언어 모델은 Ollama를 통해 로컬로 실행됩니다 — 클라우드로 전송되는 것은 없습니다.

### 요구 사항

- XFCE 데스크톱이 설치된 **Ubuntu 24.04** (개발 목적이라면 macOS에서도 어시스턴트를 실행할 수 있습니다).
- 도구 호출을 지원하는 모델이 함께 설치된 **[Ollama](https://ollama.com)**, 예: `qwen2.5:14b` (작은 컴퓨터에서는 `qwen2.5:7b`).
- 빠른 응답을 위해 **GPU를 권장**하지만, 필수는 아닙니다.

### 설치 (Ubuntu)

핵심 어시스턴트를 설치하고 백그라운드에서 시작합니다:

```bash
sudo apt install ./kowalski-core_*.deb        # the assistant + the `kow` command
systemctl --user enable --now kowalski-core   # run it as a background service
```

원할 때 선택 구성 요소를 추가하세요:

```bash
sudo apt install ./kowalski-ui_*.deb       # the Omnibox (Super+Space) + desktop theme
sudo apt install ./kowalski-voice_*.deb    # hands-free voice mode
sudo apt install ./kowalski-indexer_*.deb  # semantic file search
```

> 아직 `.deb` 파일이 없으신가요? `make deb` 로 빌드하거나 (Docker 필요), 아래의 개발자 설정을 사용하세요.

### 사용해 보기 (개발자 설정 — Linux 또는 macOS)

```bash
git clone https://github.com/KPbICO6Ou/kowalski-os.git
cd kowalski-os
make venv                       # create a virtualenv with the dev tools
.venv/bin/pip install -e core   # install the assistant core
ollama pull qwen2.5:7b          # download a local model
.venv/bin/kow ask "how much free disk space do I have?"
```

### 첫걸음

```bash
kow ask "..."             # ask once and get an answer
kow ask --plan "..."      # for bigger tasks: it makes a plan and works through it
kow ask --continue "..."  # keep the same conversation going
kow tools list            # see everything the assistant can do
kow journal tail          # see what it has done
kow serve                 # run it as a background service for the desktop apps
```

### 어떻게 구성되어 있나요

Kowalski OS에는 하나의 "두뇌" — `kow-core` 서비스 — 가 있으며, 모든 인터페이스가 이것과 대화합니다: 현재는 명령줄, 그리고 데스크톱의 Omnibox, 음성, 채팅 창입니다. 그래서 어시스턴트는 어디서나 똑같이 동작합니다.

| 부분 | 무엇인지 |
|---|---|
| `core/` | 어시스턴트의 두뇌: 요청 이해, 도구, 안전 규칙, 로그 |
| `ui/` | Omnibox (Super+Space를 누르세요)와 데스크톱 구성 요소 |
| `voice/` | 웨이크 워드, 음성-텍스트 변환, 텍스트-음성 변환 |
| `indexer/` | 의미 기반 파일 검색 |
| `setup/` | 최초 실행 설정 마법사 |
| `provision/` | 전체 시스템을 새 컴퓨터에 설치하는 스크립트 |
| `packaging/` | `.deb` 패키지와 데스크톱 테마 |

더 자세히: [Architecture](docs/ARCHITECTURE.md) · [Installing on a machine](docs/PROVISIONING.md) · [Packaging](docs/PACKAGING.md).

### 프로젝트 상태

Kowalski OS는 **초기 개발** 단계에 있습니다. 어시스턴트는 현재 명령줄을 통해 동작합니다. 그래픽 데스크톱 구성 요소 (Omnibox 창, 음성, 전체 시스템 설치)는 만들어지고 테스트되었지만, 완전히 살아나려면 GPU가 있는 실제 리눅스 컴퓨터가 필요합니다. 다듬어지지 않은 부분이 있을 수 있습니다.

### 라이선스

[Apache-2.0](LICENSE).
