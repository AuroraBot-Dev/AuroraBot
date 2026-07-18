# AuroraBot

<p align="center">
  <a href="README.md">中文</a> | <a href="README.en.md">English</a> | <b>日本語</b>
</p>

AuroraBot は、因果イベント、同構 Agent、能動的なリズムを中心とする自律エージェント・フレームワークです。
環境入力、モデル呼び出し、能力の実行、実行結果を監査可能な記録として残すため、Task を非同期に停止し、
確実に再開し、明示的に終了できます。

## 認知ループ

```text
外部 AMP イベント / system.tick
  → Kernel が Task と root Gate Agent を作成
  → Agent が model Activity を要求、または有界な並列 child Agent に委任
  → 各 child Agent が親へ完了報告し、親 Agent が直ちに再開
  → 通常 effect は許可済み Agent、terminal effect は root Agent のみが要求
  → Platform receipt が要求元 Agent の mailbox message として戻る
```

モデルが生成したテキスト自体は外部効果ではありません。宣言済みの Platform 能力だけが効果を発生させ、モデル呼び出し、
ツール呼び出し、実行結果、予算変更、終了理由は一つの因果連鎖に記録されます。外部入力または自律 tick ごとに独立した
Task を作成します。監督ツリー全体で model、tool、時間の budget を共有し、Runtime は全 Agent に読み取り専用の
global Brain Context を投影します。長期記憶は現在、任意の Memory Agent contract のみを公開します。

外部入力がない場合、永続 scheduler が予算内で `system.tick` を生成します。沈黙が続くと間隔は 30 秒から 30 分まで
段階的に延びます。外部入力は runtime を即時に起動し、対話 Task は自律 Task より優先されます。

## 主な機能

- AMP JSON boundary、SQLite WAL runtime state、atomic archive
- 永続 mailbox、同構 Agent、監督ツリー、共有 budget、cancel propagation
- Chat Completions tools と Responses agent に対応するモデル gateway
- 不変 capability catalog、JSON Schema 引数検証、MCP application
- scheduler、Kernel、model dispatcher、Platform receipt を一つにまとめる `AuroraRuntime`
- 因果監査記録と分離された、文脈情報を持つ構造化ログ

## クイックスタート

Python 3.12 と [uv](https://docs.astral.sh/uv/) が必要です。

```powershell
uv sync --group dev
Copy-Item .env.example .env
# 設定した Provider に必要な API キーを .env に追加
uv run python bot.py
```

認知ループと `http://127.0.0.1:8000` の Dashboard backend が同時に起動します。独立 frontend は次のように起動します。

```powershell
Set-Location ..\AuroraChat
pnpm install
pnpm run dev
```

`http://localhost:5173` を開き、登録後に通常ユーザーまたは組み込み AuroraBot と会話できます。

主なエントリポイント：

```powershell
# Dashboard なしで認知ループのみ実行
uv run python bot.py --headless --profile prod

# デバッグ API とローカル console を同時に起動
uv run aurora

# デバッグ API または console を個別に起動
uv run aurora serve
uv run aurora console

# プロジェクト品質チェック
uv run aurora check
```

console では `/say こんにちは` でメッセージを投入し、`/pump` で ready turn を進め、
`/task <task_id>`、`/agent <agent_id>` または `/status` で監督ツリーと scheduler 状態を確認できます。

## ディレクトリ

```text
config/         TOML 設定と profile override
docs/rfc/       規範的な architecture と公開 contract
src/contracts/  設定、AMP、Agent、model、memory contract
src/kernel/     Task、Agent、mailbox、Activity、因果、SQLite runtime state
src/agents/     同構 Agent handler と組み込み委任能力
src/ai/         モデル role、routing、native tools/Responses、usage 記録
src/localhost/  chat、scheduler、console の application use case
src/dashboard/  Dashboard HTTP/WebSocket と debug route adapter
src/platform/   Console、Dashboard、MCP adapter、capability catalog、AMP 正規化
src/apps/       組み込み native AMP-MCP application
src/sandbox/    独立 sandbox component。現在の Agent runtime では無効
src/utils/      上位 layer に依存しない共通 utility
tests/          contract、integration、regression test
```

Kernel workspace は `data/kernel/{inbox,process,archive}` に固定されています。外部 boundary と archive は JSON、
runtime state は SQLite WAL、構造設定は TOML、secret は環境変数からのみ供給します。

## ドキュメント

- [RFC 一覧](docs/rfc/README.md)
- [RFC 0001：architecture baseline](docs/rfc/0001-architecture.md)
- [RFC 0012：同構 multi-Agent durable runtime](docs/rfc/0012-homogeneous-agent-runtime.md)
- [RFC 0010：Dashboard chat adapter](docs/rfc/0010-dashboard-chat.md)
- [RFC 0011：current project baseline](docs/rfc/0011-current-project-baseline.md)
- [コントリビューションガイド](docs/CONTRIBUTING.ja.md)
- [ログ規約](LOGGING.md)
- [行動規範](CODE_OF_CONDUCT.md)

## ライセンス

[Apache License 2.0](LICENSE) のもとで公開されています。
