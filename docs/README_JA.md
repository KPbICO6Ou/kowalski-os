## Kowalski OS — コンピューターに話しかけよう

[![CI](https://github.com/KPbICO6Ou/kowalski-os/actions/workflows/ci.yml/badge.svg)](https://github.com/KPbICO6Ou/kowalski-os/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](https://github.com/KPbICO6Ou/kowalski-os/blob/main/LICENSE)
[![Python](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Ubuntu%2024.04%20%C2%B7%20XFCE-orange.svg)](https://ubuntu.com/)

Kowalski OS は、ふつうの Linux デスクトップを、ただ話しかけるだけで使えるものに変えます。ファイルを探す、リマインダーを設定する、メールを要約する、コマンドを実行する、画面に映っているものを見てもらう——こうしたことを、ふだんの言葉で、入力でも音声でも頼めます。アシスタントはあなた自身のマシン上で（[Ollama](https://ollama.com) を通じて）**ローカル**に動くので、あなたのデータがコンピューターの外に出ることはありません。

[English](https://github.com/KPbICO6Ou/kowalski-os/blob/main/README.md) | [Español](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_ES.md) | [Português](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_PT.md) | [Français](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_FR.md) | [Deutsch](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_DE.md) | [Italiano](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_IT.md) | [Русский](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_RU.md) | [中文](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_ZH.md) | **[日本語](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_JA.md)** | [हिन्दी](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_HI.md) | [한국어](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_KR.md)

### 何ができるの？

インストールが終わったら、こんなふうに入力できます。

```bash
kow ask "how much free disk space do I have?"
kow ask "find the budget spreadsheet I edited last week and open it"
kow ask "remind me in 20 minutes to call mom"
kow ask "summarize my latest email from Anna"
kow ask --plan "research topic X, then write a short note about it"
```

- **探す** — 名前で、内容で、あるいは意味で（「旅行についての書類」）。
- **覚える** — メモ、リマインダー、そしてあとで思い出せるあなたに関する事実。
- **メール** — 検索、閲覧、下書き、そして（あなたの承認のうえで）送信。
- **画面を見る** — 「いま画面に何が映っている？」に答える。
- **実行する** — アプリを開く、ウィンドウを操作する、シェルコマンドを実行する、複数の手順からなる作業を自動化する。
- **話す** — ハンズフリーの音声モード（ウェイクワード → 音声認識 → 回答 → 音声合成）。

### 安全なの？

はい、設計からして安全です。

- アシスタントは、あなたが許可したフォルダーにしか触れません。
- 危険を伴うこと——メールの送信、コマンドの実行、ウィンドウへの入力——は **まずあなたに確認を求めます**。そして、あなたは断ることができます。
- シェルコマンドは Linux 上のサンドボックスの中で実行されます。
- すべての操作はローカルのログに記録され、`kow journal tail` で確認できます。
- 言語モデルは Ollama を通じてローカルで動き、クラウドには何も送信されません。

### 必要なもの

- XFCE デスクトップを備えた **Ubuntu 24.04**（開発用には macOS でアシスタントを動かすこともできます）。
- ツール呼び出しに対応したモデルを使う **[Ollama](https://ollama.com)**。たとえば `qwen2.5:14b`（小さめのマシンなら `qwen2.5:7b`）。
- すばやい回答のために **GPU を推奨**しますが、必須ではありません。

### インストール（Ubuntu）

コアのアシスタントをインストールして、バックグラウンドで起動します。

```bash
sudo apt install ./kowalski-core_*.deb        # the assistant + the `kow` command
systemctl --user enable --now kowalski-core   # run it as a background service
```

必要になったら、いつでもオプションのコンポーネントを追加できます。

```bash
sudo apt install ./kowalski-ui_*.deb       # the Omnibox (Super+Space) + desktop theme
sudo apt install ./kowalski-voice_*.deb    # hands-free voice mode
sudo apt install ./kowalski-indexer_*.deb  # semantic file search
```

> まだ `.deb` ファイルがありませんか？ `make deb` でビルドするか（Docker が必要です）、下記の開発者向けセットアップを使ってください。

### 試してみる（開発者向けセットアップ — Linux または macOS）

```bash
git clone https://github.com/KPbICO6Ou/kowalski-os.git
cd kowalski-os
make venv                       # create a virtualenv with the dev tools
.venv/bin/pip install -e core   # install the assistant core
ollama pull qwen2.5:7b          # download a local model
.venv/bin/kow ask "how much free disk space do I have?"
```

### 最初の一歩

```bash
kow ask "..."             # ask once and get an answer
kow ask --plan "..."      # for bigger tasks: it makes a plan and works through it
kow ask --continue "..."  # keep the same conversation going
kow tools list            # see everything the assistant can do
kow journal tail          # see what it has done
kow serve                 # run it as a background service for the desktop apps
```

### どんな構成になっているの？

Kowalski OS には一つの「頭脳」——`kow-core` サービス——があり、すべてのインターフェースがそれと話します。今はコマンドライン、そしてデスクトップ上の Omnibox、音声、チャットウィンドウです。だからアシスタントはどこでも同じようにふるまいます。

| 部分 | それは何か |
|---|---|
| `core/` | アシスタントの頭脳：リクエストの理解、ツール、安全のルール、ログ |
| `ui/` | Omnibox（Super+Space を押す）とデスクトップ部品 |
| `voice/` | ウェイクワード、音声認識、音声合成 |
| `indexer/` | 意味によるファイル検索 |
| `setup/` | 初回起動時のセットアップウィザード |
| `provision/` | システム全体を新しいマシンにインストールするスクリプト |
| `packaging/` | `.deb` パッケージとデスクトップテーマ |

さらに詳しく： [アーキテクチャ](docs/ARCHITECTURE.md) · [マシンへのインストール](docs/PROVISIONING.md) · [パッケージング](docs/PACKAGING.md)。

### プロジェクトの状況

Kowalski OS は **開発初期段階** にあります。アシスタントは今日、コマンドラインを通じて動作します。グラフィカルなデスクトップ部分（Omnibox ウィンドウ、音声、システム全体のインストール）は構築・テスト済みですが、完全に動かすには GPU を備えた実機の Linux マシンが必要です。粗削りなところがあることをご承知おきください。

### ライセンス

[Apache-2.0](LICENSE)。
