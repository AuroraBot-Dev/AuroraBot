<p align="center">
  <img src="assets/logo.svg" width="112" alt="AuroraBot Logo" />
</p>

<h1 align="center">AuroraBot</h1>

<p align="center">
  <a href="README.md">中文</a> | <a href="README.en.md">English</a> | <b>日本語</b>
</p>

<p align="center"><em>Agent に、自分自身の生活を。</em></p>

<p align="center">イベントの平等 · 同構 Agent の協調 · 能動的なリズム</p>

<p align="center">
  <a href="https://github.com/AuroraBot-Dev/AuroraBot"><img src="https://img.shields.io/badge/GitHub-AuroraBot-181717?logo=github" alt="GitHub" /></a>
  <a href="https://www.aurorabot.org/"><img src="https://img.shields.io/badge/Docs-aurorabot.org-315b7d" alt="Documentation" /></a>
  <a href="https://github.com/AuroraBot-Dev/AuroraBot/actions/workflows/ci.yml"><img src="https://github.com/AuroraBot-Dev/AuroraBot/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-315b7d" alt="Apache 2.0" /></a>
  <img src="https://img.shields.io/badge/Python-3.12-315b7d?logo=python&logoColor=white" alt="Python 3.12" />
  <img src="https://img.shields.io/badge/Nightly-0.5%20alpha-6f5b95" alt="Nightly 0.5 alpha" />
</p>

## AuroraBot とは

AuroraBot は、開発者向けのオープンソース自律エージェント・フレームワークです。目指すのは機能を増やした ChatBot ではなく、持続的に存在し、自分のリズムを持ち、環境の中で判断して行動できる Agent です。

私たちは Agent を「彼女」と呼びます。これは文章上の演出だけではありません。AuroraBot は呼ばれた時だけ存在する便利な道具ではなく、デジタル生命が persona、state、boundary、自分の仕事を持ちながら、人や外部世界と関係を作れる runtime を提供します。

## 設計思想

### 自分自身の生活を持つ Agent

会話だけが世界ではありません。誰もメッセージを送らない間も時間は進み、application は event を発生させ、未完了の仕事は続きます。能動的なリズムにより、Agent は明確な予算と境界の中で、今考えるべきか、行動すべきかを判断します。

### 環境の変化を平等に扱う

ユーザーのメッセージ、時間の経過、application event、child Agent の結果、effect receipt は、すべて外部世界の変化です。同じ event boundary から認知へ入り、ユーザーから届いたという理由だけで、疑問を持てない最上位命令にはなりません。

平等とは、schedule の優先度がないという意味ではありません。対話 Task は優先でき、権限と安全規則も常に有効です。大切なのは、Agent が何が起きたかを理解してから、返事、行動、委任、沈黙を選ぶことです。

### 判断と行動を分離する

モデルは理解と判断を担いますが、通常の model text が直接環境を変えることはありません。外部 action は宣言済みの能力、引数検証、Platform 実行を通り、outcome は新しい event として Agent に戻ります。自律性と制御可能性は両立します。

## 主な能力

- **能動的な runtime**：内蔵 Clock MCP を有効にすると、自律 heartbeat を永続化し、予算内で自律 Task を作り、外部入力時は対話処理へ素早く切り替えます。
- **継続する Task**：model、能力、child Agent を非同期に待ち、結果から再開し、明確な予算と終端を持ちます。
- **Multi-Agent 協調**：同構 Agent が限定された監督ツリーを作り、複雑な仕事を並行して分担できます。
- **進行中の session**：revision、watermark、delta、commit barrier により、新しい event を active session に取り込みつつ、置き換えられた古い generation を隔離します。
- **外部世界との接続**：Console、ローカル Panel backend、MCP Platform が入力を event に統一し、許可済みの能力を提供します。
- **組み込み記憶**：短期 window と summary、global durable facts、mem0/Chroma semantic retrieval が、degrade 可能な長期記憶経路を構成します。
- **交換可能なモデル**：fast、quality、multimodal、embedding role と Provider を TOML で設定します。現在の対話 call は Chat Completions semantics に統一されています。
- **追跡可能な行動**：入力、model call、能力 request、outcome、終了理由が一つの因果記録につながります。
- **設定可能な人格と能力**：SOUL、Agent profile、model role、Platform、MCP application を個別に設定できます。

## クイックスタート

Python 3.12（推奨。それ以上のバージョンは十分に検証されていません）、Git、[uv](https://docs.astral.sh/uv/) が必要です。現在はソースからの実行を推奨します。

```powershell
git clone --branch nightly --single-branch https://github.com/AuroraBot-Dev/AuroraBot.git
Set-Location AuroraBot
uv sync --no-dev
Copy-Item .env.example .env
```

既定の model 設定に必要な `DEEPSEEK_API_KEY` を `.env` に追加してください。現在の `config/apps.toml` は、
リポジトリ外の `org.aurora.qq` application を既定で有効にしています。`extensions/apps/Aurora-QQ` をインストール
していない場合は、その `[[app]]` block の `enabled = false` を先に設定してください。strict configuration のため、
未導入のままでは起動が停止します。

```powershell
uv run --no-dev --env-file .env aurora start
```

起動後はメッセージを入力できます。`/help` で command、`/engine/status` で runtime state を確認できます。

```powershell
# config/platforms.toml の既定 Platform 構成を使用
uv run --no-dev --env-file .env aurora start

# ヘッドレス：ローカル Console を無効化、Platform 構成は変更なし
uv run --no-dev --env-file .env aurora start --headless
```

ローカル Console は `--platform` の選択では起動・停止しません。ヘッドレスでなく `[runtime.console].enabled = true`
であれば常に動作します。`--platform` を指定すると、それらが正確な Platform 集合になり、既定値には追加されません。
完全な browser UI は別の [AuroraBot Panel](https://github.com/AuroraBot-Dev/AuroraBot-panel) プロジェクトにあり、
本リポジトリには loopback、single-owner の backend と chat bridge だけが含まれます。

## カスタマイズと拡張

| 変更したいもの                         | 最初に見る場所           |
| -------------------------------------- | ------------------------ |
| SOUL、世界、Agent prompt fragment       | `config/prompts.toml`    |
| model role と Provider                 | `config/models.toml`     |
| engine 制限と Task budget              | `config/engine.toml`     |
| 永続化 storage path                    | `config/storage.toml`    |
| 既定で起動する Platform                | `config/platforms.toml` |
| Agent の model、能力、委任範囲         | `config/agents.toml`     |
| ローカルまたはリモート MCP application | `config/apps.toml`       |

構造設定には TOML を使い、secret は環境変数だけから読み取ります。[拡張ガイド](extensions/README.md)と組み込みの
[Clock application source](src/apps/aurora-app-clock/mcp_server.py)から始められます。

## 現在の段階

`nightly` の AuroraBot `0.5 alpha` は、ローカル体験、runtime 研究、拡張開発向けです。添付ファイルは保存と参照渡しまでで、
完全な multimodal understanding chain はまだありません。sandbox と speech は authorized runtime に未接続です。
安定した MCP reconnect、終端データの TTL、一貫した backup、公開 multi-tenant deployment も現在の保証には含まれません。
公開動作は [RFC 0300](docs/rfc/0300-unified-architecture-and-contracts.md)、contract、テストを基準とします。

## ドキュメント

- [クイックスタート](https://www.aurorabot.org/start/getting-started)
- [Nightly の現在状態と境界](https://www.aurorabot.org/reference/nightly-status)
- [Architecture](ARCHITECTURE.md) と [technical reference](TECHNICAL.md)
- [コントリビューションガイド](docs/CONTRIBUTING.ja.md)
- [AuroraBot の拡張](extensions/README.md)
- [RFC 読み方ガイド](docs/rfc/README.md)
- [進化 roadmap](ROADMAP.md)
- [ログ規約](LOGGING.md)
- [行動規範](CODE_OF_CONDUCT.md)

## オープンソースへの謝辞

AuroraBot は、多くの優れたオープンソース・プロジェクトを利用しています。

| プロジェクト                                                                                                           | AuroraBot での用途                        |
| ---------------------------------------------------------------------------------------------------------------------- | ----------------------------------------- |
| [LiteLLM](https://github.com/BerriAI/litellm)                                                                          | Model Provider 接続と call infrastructure |
| [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)                                                   | MCP application と tool protocol          |
| [FastAPI](https://github.com/fastapi/fastapi) / [Uvicorn](https://github.com/encode/uvicorn)                           | ローカル Panel backend                    |
| [prompt_toolkit](https://github.com/prompt-toolkit/python-prompt-toolkit) / [Rich](https://github.com/Textualize/rich) | Console と terminal experience            |
| [jsonschema](https://github.com/python-jsonschema/jsonschema)                                                          | 能力の引数検証                            |

この分野を探求する他のオープンソース Agent/Bot プロジェクトにも感謝します。特に [MaiBot](https://github.com/MaiM-with-u/MaiBot) の「デジタル生命」という考え方は、AuroraBot の初期構想に大きな影響を与えました。

## ライセンス

本プロジェクトは [Apache License 2.0](LICENSE) でオープンソースとして公開されています。
