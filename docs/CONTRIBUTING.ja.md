# AuroraBot への貢献

[中文](CONTRIBUTING.md) | [English](CONTRIBUTING.en.md)

AuroraBot への貢献ありがとうございます。本プロジェクトは RFC で設計判断を固定し、コード、設定、テスト、公開文書の
整合性を保ちます。

## 開発環境

Python 3.12、Git、[uv](https://docs.astral.sh/uv/) が必要です。

```powershell
git clone https://github.com/AuroraBot-Tech/AuroraBot.git
Set-Location AuroraBot
uv sync --group dev
Copy-Item .env.example .env
```

secret はローカル `.env` またはプロセス環境にだけ保存してください。secret、実際の会話、モデル continuation、
workspace event、runtime log をコミットしてはいけません。

## 設計フロー

- `docs/rfc/` は architecture と公開 contract の唯一の基準です。
- module boundary、AMP/Kernel event、設定、extension protocol、model call contract を変更する前に、RFC を更新または
  追加してください。
- 小規模な不具合修正、テスト追加、意味を変えない refactor は、検証結果とともに直接提出できます。
- 公開動作を説明する文書を変更する場合は、中国語、英語、日本語の入口を同じ commit で更新してください。

## Module boundary

- Kernel は event、state、graph scheduling、cycle、causality を管理し、認知内容の選択や Platform effect の実行は
  行いません。
- Node は Kernel API だけを通じて snapshot を読み、宣言済み能力を要求し、event を生成します。
- Platform は AMP input を正規化して `effect.requested` を実行し、結果を新しい event として Kernel に返します。
- `localhost` はローカル use case を担当し、`dashboard` は route/API adapter に限定されます。
- `utils` は上位 package に依存できません。共通ログは `src.utils.log_utils.get_logger()` を使用します。

## Branch と Pull Request

1. `dev` から短期間の branch を作成します。`feat/`、`fix/`、`refact/` prefix を推奨します。
2. PR はレビュー可能な一つの目的に絞り、対応するテストと文書を含めます。
3. merge target は `dev` とし、動作変更、検証 command、既知の境界、関連 RFC/Issue を記載します。
4. CI とレビュー通過後に merge し、完了した branch を削除します。

## 検証

```powershell
# プロジェクト共通チェック
uv run aurora check

# 必要に応じた個別チェック
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

テストは offline で再現可能にしてください。model、clock、MCP には fake を使用し、実際の利用枠や公開 network service に
依存してはいけません。不具合修正では失敗経路を先にテストし、event/effect のテストでは cycle boundary、idempotency、
causal parentage も確認します。

## 提出前チェック

- Kernel/Platform boundary を迂回せず、Provider 固有 object を workspace に保存していません。
- ログに安定した識別子があり、secret、完全な prompt、continuation、機密 payload は含まれていません。
- 構造設定は TOML、secret は環境変数という原則を維持しています。
- README、module 文書、設定例、RFC が矛盾していません。
- 新しい動作にテストがあり、`uv run aurora check` が成功します。

貢献の提出により、プロジェクトの[行動規範](../CODE_OF_CONDUCT.md)に従うことに同意したものとします。
