<p align="center">
  <img src="assets/logo.svg" width="112" alt="AuroraBot Logo" />
</p>

<h1 align="center">AuroraBot</h1>

<p align="center">
  <a href="README.md">中文</a> | <a href="README.en.md">English</a> | <b>日本語</b>
</p>

<p align="center">
  <em>Agent に、自分自身の生活を。</em>
</p>

<p align="center">イベントの平等 · 同構 Agent の協調 · 能動的なリズム</p>

<p align="center">
  <a href="https://github.com/AuroraBot-Dev/AuroraBot"><img src="https://img.shields.io/badge/GitHub-AuroraBot-181717?logo=github" alt="GitHub" /></a>
  <a href="https://www.aurorabot.org/"><img src="https://img.shields.io/badge/Docs-aurorabot.org-315b7d" alt="Documentation" /></a>
  <a href="https://github.com/AuroraBot-Dev/AuroraBot/actions/workflows/ci.yml"><img src="https://github.com/AuroraBot-Dev/AuroraBot/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-315b7d" alt="Apache 2.0" /></a>
  <img src="https://img.shields.io/badge/Python-3.12-315b7d?logo=python&logoColor=white" alt="Python 3.12" />
</p>

## AuroraBot とは

AuroraBot は、開発者向けのオープンソース自律エージェント・フレームワークです。目指すのは機能を増やした ChatBot ではなく、持続的に存在し、自分のリズムを持ち、環境の中で判断して行動できる Agent です。

一回の実行は一つの `AgentTree` です。root と child は同じ決定論的な loop を使い、事前定義された `AgentDefinition` から作成され、prompt、最初の message、可視 tools、LLM model だけが異なります。

私たちは Agent を「彼女」と呼びます。これは文章上の演出だけではありません。AuroraBot は呼ばれた時だけ存在する便利な道具ではなく、デジタル生命が persona、state、boundary を持ち、必要な時に人や外部世界とつながりながら、自分の仕事を続けられる runtime を提供します。

## 設計思想

### 自分自身の生活を持つ Agent

会話だけが世界ではありません。誰もメッセージを送らない間も時間は進み、application は event を発生させます。能動的なリズム（cadence）により、Agent は明確な予算と境界の中で、今考えるべきか、行動すべきかを判断します。入力欄の後ろに永遠に留まることはありません。

### 環境の変化を平等に扱う

ユーザーのメッセージ、時間の経過、application event、child Agent の結果、effect receipt は、すべて外部世界の変化です。同じ event boundary（worldline）から認知へ入り、ユーザーから届いたという理由だけで、疑問を持てない最上位命令にはなりません。

平等とは、schedule の優先度がないという意味ではありません。対話処理は優先でき、権限と安全規則も常に有効です。大切なのは、Agent が何が起きたかを理解してから、返事、行動、委任、沈黙を選ぶことです。

### 判断と行動を分離する

モデルは理解と判断を担いますが、通常の model text が直接環境を変えることはありません。外部 action は宣言済みの能力、引数検証、実行を通り、outcome は新しい event として Agent に戻ります。自律性と制御可能性は両立します。

## 主な能力

```text
message → model → assistant
                  ├── Tool call → tool result → model
                  └── aur.agent.delegate → child Agent → tool result → parent
```

- **能動的な runtime**：cadence が時間そのものを入力にします。メッセージがなくても、Agent は自分のリズムで呼び出され、行動すべきかを判断します；
- **同構 Agent の協調**：root と child は同じ loop を使い、`aur.agent.delegate` が本当の Tool として child Agent を委任し、複雑な仕事を AgentTree に分解します；
- **イベントの平等**：ユーザーのメッセージ、時間の経過、application event が同じ worldline から認知へ入ります。scope をまたぐ連続 event stream と observation frontier が Agent を外界と同期させます；
- **外部世界との接続**：ローカル Console、Panel backend、MCP SDK 2.x client（stdio / HTTPS Streamable HTTP）がさまざまな source を event に統一します；
- **組み込み記憶**：最近活動した scope の最新 commit が PromptAssembler 経由で system に注入され、過長な context は決定論的に truncate されます；
- **交換可能なモデル**：LiteLLM による統一 model gateway が role と Provider を TOML で設定し、secret は環境変数だけから読み取ります；
- **追跡可能な行動**：入力、model call、tool request、outcome が一つの因果記録（WorldJournal）につながります；
- **設定可能な人格と能力**：SOUL、WORLD、Agent prompt、model role、tool 可視性を個別に設定できます；
- **統一 operation catalog**：engine、world、ai、console、cadence、memory、MCP などの runtime 能力が、method/path とスラッシュ文字列エントリ（ops）を提供します；
- **完全オフラインのテスト**：fake Model/Tool により、テストは決定論的で、オフライン、ネットワーク不要です。

スコープには、Panel の添付ファイルと WebSocket、sandbox、汎用 extension platform、MCP の sampling・elicitation・roots・Tasks・非テキスト結果注入は含まれません。

## クイックスタート

Python 3.12、Git、[uv](https://docs.astral.sh/uv/) が必要です：

```bash
git clone https://github.com/AuroraBot-Dev/AuroraBot.git
cd AuroraBot
uv sync
cp -r config.example config
cp .env.example .env
uv run aurora start
```

`aurora start` はプロジェクトルートの `.env` を読み込み（`.env` に既定モデルが必要とする `DEEPSEEK_API_KEY` などを設定）、`models.toml` から model gateway を作成します。起動後はメッセージを入力して会話できます。`/help` で操作を確認し、`/exit` で終了します。ローカル Console を起動しない場合は `--headless` を付けます：

```bash
uv run aurora start --headless
```

## カスタマイズと拡張

| 変更したいもの                             | 最初に見る場所                              |
| ------------------------------------------ | ------------------------------------------- |
| SOUL、世界、Agent prompt                   | `config/prompts.toml`、`config/prompts/`    |
| model role と Provider                     | `config/models.toml`                        |
| Agent 定義と委任範囲                       | `config/agents.toml`                        |
| engine 制限と tree 構造                    | `config/engine.toml`、`config/runtime.toml` |
| リズムと記憶                               | `config/cadence.toml`、`config/memory.toml` |
| ローカルまたはリモート MCP application     | `config/apps.toml`                          |
| ログと永続化 path                          | `config/logging.toml`、`config/storage.toml` |

構造設定には TOML を使い、secret は環境変数だけから読み取ります。

## 開発

`config.example/` は source とともに配布され、コピーした `config/` は個人設定で Git の管理外です。よく使うコマンド：

```bash
uv run aurora check        # lint、型、テスト
uv run aurora about        # AuroraBot について
uv run aurora config list  # 登録済み設定の一覧
uv run aurora setup        # 完全ブートストラップ：依存関係、submodule、panel
```

設計の基準は [RFC 0300](docs/rfc/0300-unified-architecture-and-contracts.md) です。実装構造は
[アーキテクチャドキュメント](docs/architecture/index.md)（パッケージ別）を参照してください。

## ドキュメント

- [クイックスタート](docs/start/getting-started.md)
- [設定](docs/start/configuration.md)
- [アーキテクチャ概要](docs/architecture/index.md)
- [現在の実装状態](docs/reference/nightly-status.md)
- [コントリビューションガイド](CONTRIBUTING.ja.md)
- [行動規範](CODE_OF_CONDUCT.md)

## オープンソースへの謝辞

AuroraBot は、多くの優れたオープンソース・プロジェクトを利用しています。

| プロジェクト                                                                                                           | AuroraBot での用途                        |
| ---------------------------------------------------------------------------------------------------------------------- | ----------------------------------------- |
| [LiteLLM](https://github.com/BerriAI/litellm)                                                                          | Model Provider 接続と call infrastructure |
| [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)                                                   | MCP client と tool protocol               |
| [FastAPI](https://github.com/fastapi/fastapi) / [Uvicorn](https://github.com/encode/uvicorn)                           | ローカル Panel backend                    |
| [prompt_toolkit](https://github.com/prompt-toolkit/python-prompt-toolkit) / [Rich](https://github.com/Textualize/rich) | Console と terminal experience            |
| [SQLAlchemy](https://github.com/sqlalchemy/sqlalchemy) / [aiosqlite](https://github.com/omnilib/aiosqlite)             | WorldJournal 永続化                       |

この分野を探求する他のオープンソース Agent/Bot プロジェクトにも感謝します。特に
[MaiBot](https://github.com/MaiM-with-u/MaiBot) の「デジタル生命」という考え方は、AuroraBot の初期構想に大きな影響を与えました。

## ライセンス

本プロジェクトは [Apache License 2.0](LICENSE) でオープンソースとして公開されています。
