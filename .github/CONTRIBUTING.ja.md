# AuroraBot への貢献

[简体中文](CONTRIBUTING.md) · [English](CONTRIBUTING.en.md)

文書、不具合修正、ツール、画面、ランタイムの改善を歓迎します。公開契約やアーキテクチャを大きく変更する場合は、用途、不変条件、検証方法を Issue または Discussion で先に相談してください。[行動規範](CODE_OF_CONDUCT.md)を守って参加してください。

## 開発環境

Python 3.12 以上、uv、[package.json](../package.json) と [.node-version](../.node-version) に指定された pnpm と Node.js を用意します。

```bash
git clone https://github.com/AuroraBot-Dev/AuroraBot.git
cd AuroraBot
uv sync --locked --all-packages
pnpm install --frozen-lockfile
pnpm exec uv run --locked aurora check
```

Bot の起動は[初回起動ガイド](../examples/START.md)を参照してください。チェックは偽モデルや模擬通信を使用し、モデルの認証情報は不要です。明示的な許可なく実プロバイダーを呼び出さないでください。認証情報は環境変数かローカルの `.env` に置き、TOML、ctx、スナップショット、ログには含めません。

## コードとパッケージ境界

詳細な規約は簡体字中国語の [AGENTS.md](../AGENTS.md) と[開発ガイド](../docs/development.md)にあります。

- コメント、docstring、コミットメッセージは主に中国語で、現在の責務と動作を記述します。
- 実行系の依存方向は `bot → agent → control → core` です。モデルと MCP は `aurora_adapter`、設定は `aurora_config` が担当します。
- core は仕組みを提供し、モデルや業務を制御しません。CLI、API、画面はバックエンドの実行契約を再利用します。
- 公開 ID は `<namespace>:<domain>/<local_path>` 形式で定義元パッケージに属します。インターフェース変更時は設定、利用側、テスト、文書も更新します。
- TOML が永続設定の情報源です。実行時の上書きは自動保存しません。スナップショット復元で実行を自動再開したり、未完了のツール操作を再実行したりしません。
- パッケージ内テストは `packages/<package>/tests/unit` または `tests/contract`、パッケージ間テストはルートの `tests/contract` と `tests/e2e` に置きます。

## 検証と PR

1. 最新の `main` から分岐し、新機能には `feat/<name>` を使用します。
2. 作業前に作業ツリーとステージを確認し、関連する変更だけを小さくコミットします。
3. 対象を絞った検証から始め、契約、ライフサイクル、設定の変更には完全チェックを実行します。
4. 変更内容、検証結果、追加テスト固有の価値を [docs/CHAGELOG.md](../docs/CHAGELOG.md) に記録します。
5. `main` 宛ての PR で動作と検証を説明し、CI とレビューを待ちます。新機能を `main` に直接コミットしません。

```bash
pnpm exec uv run --locked aurora check
pnpm exec uv run --locked aurora check --full
uv build --all-packages --wheel --out-dir build/wheels
pnpm --filter @aurorabot/panel build
```

通常のチェックは整形、lint、型、短時間の境界テストを含みます。`--full` は Python、フロントエンド、ネイティブ端末、統合テストをすべて実行し、`--coverage` も同じ範囲を使います。CI は Python 3.12 / 3.13 で完全チェックを実行し、全 wheel と Panel をビルドします。

実際の不具合を検証できる既存テストを優先し、重複を増やさないでください。失敗を隠すためにアサーションを削除したり、条件を緩めたり、チェックを省略したりしません。テスト範囲を広げた場合は、依存関係を導入済みの同じ環境でコマンド全体の実時間を測定します。目標は通常 15 秒以内、完全チェック 60 秒以内です。文書だけの変更ではリンクと差分を確認します。配布物や依存関係の変更では、クリーン環境への wheel インストールも確認します。

README.md と AGENTS.md の変更はユーザー確認の規則に従います。技術文書の基準は簡体字中国語とし、コミュニティの英語・日本語入口も同期します。

## AI 支援による貢献

AI の利用を歓迎します。投稿者は生成内容を理解し、動作を説明し、正確性に責任を持ってください。PR で支援の範囲を開示し、パッケージ境界とライセンスを守り、実際に行った検証だけを報告します。AI の生成物もチェックの対象です。レビューで修正を求める場合があり、重大または反復する違反はコミュニティの規則に従って扱います。

認証情報、実際の会話、モデル応答全文、アップロード、個人の実行データを提出物に含めないでください。通常の回帰テストでモデルの利用枠を消費しません。
