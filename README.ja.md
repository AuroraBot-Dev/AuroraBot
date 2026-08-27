<p align="center">
  <img src="assets/logo.svg" width="112" alt="AuroraBot Logo" />
</p>

<h1 align="center">AuroraBot</h1>

<p align="center">
  <a href="README.md">中文</a> | <a href="README.en.md">English</a> | <b>日本語</b>
</p>

<p align="center">
  <em>Bot に、自分自身の生活を。</em>
</p>

<p align="center">
  <a href="https://github.com/AuroraBot-Dev/AuroraBot"><img src="https://img.shields.io/badge/GitHub-AuroraBot-181717?logo=github" alt="GitHub" /></a>
  <a href="https://www.aurorabot.org/"><img src="https://img.shields.io/badge/Docs-aurorabot.org-315b7d" alt="Documentation" /></a>
  <a href="https://github.com/AuroraBot-Dev/AuroraBot/actions/workflows/ci.yml"><img src="https://github.com/AuroraBot-Dev/AuroraBot/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-315b7d" alt="Apache 2.0" /></a>
  <img src="https://img.shields.io/badge/Python-3.12-315b7d?logo=python&logoColor=white" alt="Python 3.12" />
</p>

## AuroraBot とは

AuroraBot は、Agent に「生活」できる実行環境を提供する Bot フレームワークです。私たちが目指すのは、道具のような Agent ではなく、持続的に存在し、自分のリズムを形成し、環境の中で自律的に判断して行動する Bot です。

彼女は自分自身の人格と状態を持ち、必要な時に人や外部世界とつながることができます。彼女の世界では、すべてのメッセージに「媒介」があります。あなたが彼女に送るメッセージも、まずアプリケーション通知にならなければなりません〜

## 設計思想

### Bot を中心にすべてを設計する

AuroraBot は Bot を世界の主体として扱います。呼び出されるインターフェースではなく、彼女は存在し続け、自分自身の人格・状態・境界を持ち、すべての設計は彼女の生活を中心に展開します。この原則はアーキテクチャで次の三つに現れます：

- **彼女が世界を持ち、tree は彼女の実行にすぎない**：Bot は追記型の世界ジャーナル（WorldJournal）と複数の `AgentTree` を持ちます。1 本の tree は 1 回の実行にすぎず、彼女と並行する別の主体ではありません。チャット、タスク、委任はすべて彼女の生活の中の出来事であり、出来事が終わっても彼女は存在し続けます。
- **すべての入力に媒介がある**：彼女に影響を与える変化は、必ず最初に世界イベントにならなければなりません。あなたが彼女に送るメッセージも、`console.input` として彼女の世界にコミットされます。アプリケーションイベント、MCP の報告、ツール結果、時間の経過も同様です。彼女はインターフェースに応答しているのではなく、世界を経験しています。
- **彼女は理解してから決める**：ユーザーからのメッセージは、その出所だけで自動的に最上位の命令にはなりません。彼女はまず何が起こったかを理解し、それから応答、行動、委任、沈黙を選びます。モデルは理解と判断だけを担い、外部行動は宣言された Tool を通して実行され、結果は新しいイベントとして彼女の世界に戻ります。

## クイックスタート

### 1. このリポジトリをクローン

Python 3.12、Git、[uv](https://docs.astral.sh/uv/) が必要です

```bash
git clone https://github.com/AuroraBot-Dev/AuroraBot.git
cd AuroraBot
./scripts/linux/setup.sh
# macOS: ./scripts/macos/setup.command;
# Windows: .\scripts\windows\setup.ps1.
```

`setup.sh` は aurora をユーザーのツールディレクトリにインストールし、依存関係、個人設定、docs/panel サブモジュールの初期化を行います。

### 2. 必要な設定を記入

`.env` に既定モデルが必要とするキー（例：`DEEPSEEK_API_KEY`）を記入します

### 3. ターミナルから起動

```bash
aurora start
```

起動後はメッセージを入力して会話できます。`/help` で操作を確認し、`/exit` で終了します。

## AIGC

このプロジェクトには、大規模言語モデルや拡散モデルなどの生成モデルの支援を受けて書かれたコードが含まれており、人間によるレビューを経ています。

## コントリビューション

[AuroraBot へのコントリビューション](CONTRIBUTING.ja.md)と [AuroraBot ドキュメントサイト](https://www.aurorabot.org)をご覧ください。コントリビューションを行うことで、プロジェクトの[行動規範](CODE_OF_CONDUCT.md)に同意したことになります。

## オープンソースへの謝辞

AuroraBot は、多くの優れたオープンソース・プロジェクトなしには生まれませんでした：

| プロジェクト                                                                                                           | AuroraBot での用途                        |
| ---------------------------------------------------------------------------------------------------------------------- | ----------------------------------------- |
| [LiteLLM](https://github.com/BerriAI/litellm)                                                                          | Model Provider 接続と call infrastructure |
| [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)                                                   | MCP client と tool protocol               |
| [FastAPI](https://github.com/fastapi/fastapi) / [Uvicorn](https://github.com/encode/uvicorn)                           | ローカル Panel backend                    |
| [prompt_toolkit](https://github.com/prompt-toolkit/python-prompt-toolkit) / [Rich](https://github.com/Textualize/rich) | Console と terminal experience            |
| [SQLAlchemy](https://github.com/sqlalchemy/sqlalchemy) / [aiosqlite](https://github.com/omnilib/aiosqlite)             | WorldJournal 永続化                       |

この分野を探求する他のオープンソース Agent/Bot プロジェクトにも感謝します。特に [MaiBot](https://github.com/MaiM-with-u/MaiBot) の「デジタル生命」という考え方は、AuroraBot の初期構想に大きな影響を与えました。

## ライセンス

本プロジェクトは [Apache License 2.0](LICENSE) でオープンソースとして公開されています。
