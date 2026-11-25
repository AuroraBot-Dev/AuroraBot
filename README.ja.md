# AuroraBot

[简体中文](README.md) · [English](README.en.md)

AuroraBot は、継続的に動作する Bot 向けのエージェントフレームワークです。ReAct による推論、モデルと MCP ツールの連携、状態の永続化、環境観察、ターミナルと Web の操作画面を提供します。

実行系の依存方向は `bot → agent → control → core` です。`aurora_config` が設定を管理し、`aurora_adapter` がモデルと MCP のプロトコルを扱います。CLI、HTTP / WebSocket API、TUI、Panel はバックエンドの実行契約を共有します。

## はじめに

Python 3.12 以上、[uv](https://docs.astral.sh/uv/)、Git を用意してください。

```bash
git clone https://github.com/AuroraBot-Dev/AuroraBot.git
cd AuroraBot
uv sync --locked --all-packages
uv run --locked python examples/onboarding/main.py --init
```

[初回起動ガイド](examples/START.md)に従ってモデルと環境変数を設定し、セットアップ支援 Bot を起動します。専用のデータディレクトリを使用します。会話時には設定したモデルプロバイダーを呼び出しますが、初期化と通常のテストでは実モデルを呼び出しません。

TUI、Panel、フロントエンド開発には、[package.json](package.json) と [.node-version](.node-version) で指定した Node.js と pnpm が必要です。

## ドキュメントと開発

- [ドキュメント一覧](docs/INDEX.md)：設定、操作、コンテキスト、アーキテクチャ。
- [操作ガイド](docs/operations.md)：Bot、TUI、Panel、API の起動と接続。
- [開発と検証](docs/development.md)。
- [貢献ガイド](.github/CONTRIBUTING.ja.md)と[行動規範](.github/CODE_OF_CONDUCT.md)。
- [変更と検証の記録](docs/CHAGELOG.md)。

リンク先の技術文書は簡体字中国語で管理しています。

```bash
pnpm install --frozen-lockfile
pnpm exec uv run --locked aurora check
pnpm exec uv run --locked aurora check --full
```

## コミュニティ

不具合や機能提案は [Issues](https://github.com/AuroraBot-Dev/AuroraBot/issues)、利用方法や設計の相談は [Discussions](https://github.com/AuroraBot-Dev/AuroraBot/discussions)へどうぞ。[プロジェクトの支援](https://ifdian.net/a/aurorabot)も受け付けています。ログを共有する前に、認証情報、実際の会話、個人データを削除してください。

[Apache License 2.0](LICENSE) で公開しています。
