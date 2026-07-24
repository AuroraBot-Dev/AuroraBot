# AuroraBot への貢献

[中文](CONTRIBUTING.md) | [English](CONTRIBUTING.en.md)

AuroraBot が探求するのは、単にモデルへ接続する方法だけではありません。Agent が働き続け、確実に行動し、なぜその
行動を選んだのかを人が理解できる仕組みを目指しています。不具合修正、より自然な文書、MCP application、runtime の
改善など、さまざまな貢献を歓迎します。

## 自分に合う入口を見つける

- **初めての貢献**：文書の改善、テスト追加、境界の明確な小さな Issue から始められます。
- **Application 開発者**：組み込み Clock application を参考に、新しい MCP 能力を接続できます。
- **Runtime 開発者**：Agent、Kernel、model gateway、Platform、ローカル体験を改善できます。
- **設計への貢献**：実行可能な受け入れ条件を持つ RFC で、公開 contract や boundary を提案できます。

入口が分からない場合は、改善したい体験を Discussion または Issue に書いてください。

## 開発環境を準備する

Python 3.12、Git、[uv](https://docs.astral.sh/uv/) が必要です。

```powershell
git clone https://github.com/AuroraBot-Dev/AuroraBot.git
Set-Location AuroraBot
uv sync --group dev
Copy-Item .env.example .env

# 実際のモデルを動かす時は .env に key を追加し、明示的に読み込む
uv run --env-file .env aurora --console --mcp
```

テストと静的チェックには実際のモデル key は不要です。secret はローカル `.env` またはプロセス環境だけに置き、
secret、実際の会話、model continuation、workspace event、upload、runtime log を commit しないでください。

## コードを変更する前に

AuroraBot は、長期的にプロジェクトへ影響する判断を RFC に記録します。次の変更では、先に `docs/rfc/` の RFC を
更新または追加してください。

- module の責務や依存方向
- AMP、Task、Agent、Activity、effect event の contract
- TOML 設定、extension protocol、model call contract
- Platform composition、process entry、persistence semantics

小さな不具合修正、テスト、文章の改善、公開動作を変えない refactor は直接提出できます。公開文書を変更する場合は、
中国語、英語、日本語の入口を同期してください。

現在の runtime、package boundary、process composition は
[RFC 0200](rfc/0200-agent-centered-runtime.md) に従います。

## ループを壊さない

AuroraBot の行動を確実にするため、次の boundary を維持してください。

- Agent handler は `AgentContext` を読み、`AgentDecision` を返します。Provider や Platform client を直接呼びません。
- 外部 effect は Platform が実行し、outcome を新しい event として返します。通常のモデル text は effect ではありません。
- Kernel は event、state、mailbox、Activity、因果記録を管理しますが、認知内容は決めません。
- 構造設定は TOML、secret は環境変数だけという原則を維持します。
- 共通ログは `src.utils.logging.get_logger()` を使い、完全な prompt、continuation、機密 payload を記録しません。

maintainer 向けの完全な boundary は、リポジトリ root の `AGENTS.md` を参照してください。

## 改善を提出する

1. `dev` から短期間の branch を作ります。`feat/`、`fix/`、`refact/` prefix を推奨します。
2. Pull Request はレビュー可能な一つの結果に絞り、対応するテストと文書を含めます。
3. merge target は `dev` とし、利用者向けまたは動作上の変更、検証、既知の制限、関連 RFC/Issue を説明します。
4. CI とレビュー通過後に merge し、完了した branch を削除します。

## 検証

提出前に共通チェックを実行します。

```powershell
uv run aurora check
```

範囲を絞る場合は個別に実行できます。

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

テストは offline、deterministic、repeatable にします。実際の利用枠や公開 service ではなく、fake model、clock、MCP を
使用してください。不具合修正は元の失敗経路を覆い、event/effect のテストでは transaction boundary、idempotency、
causal parentage も確認します。

## 提出前の確認

- 文書またはテストから、動作の違いを理解できます。
- 新しい動作が Agent、Kernel、Platform のループを保っています。
- 設定、README、module 文書、テスト、RFC が矛盾していません。
- ログと fixture に実際の secret、会話、個人データがありません。
- `uv run aurora check` が成功しています。実行できない項目は Pull Request に明記しています。

貢献の提出により、プロジェクトの[行動規範](../CODE_OF_CONDUCT.md)に従うことに同意したものとします。
