# コントリビューションガイド

<a href="./CONTRIBUTING.md">中文</a> | <a href="./CONTRIBUTING.en.md">English</a> | <b>日本語</b>

AuroraBot に関心をお寄せいただきありがとうございます！このガイドでは、プロジェクトを素早く起動する方法と、推奨されるコントリビューションフローについて説明します。

## 前提環境

- **Python** ≥ 3.12, < 3.13
- **uv**（パッケージマネージャー）— [インストールガイド](https://docs.astral.sh/uv/getting-started/installation/)

## プロジェクトの起動

```bash
# 1. リポジトリをクローン
git clone https://github.com/AuroraBot-Dev/AuroraBot.git
cd AuroraBot

# 2. 依存関係をインストール（開発ツール含む）
uv sync --group dev

# 3. 環境変数を設定
cp .env.example .env
# .env を編集し、必要な API キーなどを入力

# 4. 起動
uv run python bot.py
```

## 開発ツール

| コマンド                         | 用途                                   |
| -------------------------------- | -------------------------------------- |
| `uv run pytest --cov=src`        | カバレッジ付きでテスト実行             |
| `uv run ruff check bot.py src/ tests/`  | コードリント                           |
| `uv run ruff format bot.py src/ tests/` | コードフォーマット                     |
| `uv run pyright bot.py src/`            | 型チェック（既定では `tests/` を除外） |

> PR を提出する前に、`uv run pytest --cov=src`、`uv run ruff check bot.py src/ tests/`、`uv run pyright bot.py src/` を実行することを推奨します。CI パイプラインでも、カバレッジ付きの `pytest`、`ruff check`、`ruff format --check`、`pyright bot.py src/` が実行され、コードスタイル・型チェック・基本的な回帰確認がそろうようにしています。

## コントリビューションフロー

私たちは**ブランチ → PR → マージ後に破棄**という軽量なフローを採用しています：

```
dev（最新）
  │
  ├── feat/xxx          ← 新機能ブランチ
  ├── fix/xxx           ← 修正ブランチ
  └── refact/xxx        ← コードリファクタリングまたは最適化ブランチ
```

### 1. 最新の `dev` からブランチを切る

```bash
git checkout dev
git pull origin dev
git checkout -b feat/my-feature    # または fix/xxx, refact/xxx
```

> ブランチプレフィックスの説明：
>
> - **feat/** — 新機能
> - **fix/** — バグ修正
> - **refact/** — コードリファクタリングまたは最適化（外部動作の変更なし）

### 2. ブランチ上で開発

ローカルブランチ上で自由にコミット・修正してください。コミットメッセージは簡潔明瞭に。

### 3. `dev` ブランチに対して PR を作成

開発が完了したら、ブランチをリモートにプッシュし、`dev` ブランチを対象とする Pull Request を作成します。

### 4. PR マージ後、ブランチの使命は終了

PR が `dev` にマージされたら、そのブランチの役割は完了です。**原則として、そのブランチを新機能の開発に再利用しないでください。** 安全に削除できます：

このマージ先が `dev` で、かつ `CI` が成功した場合、リポジトリは `pyproject.toml` のバージョン番号をもとに次の `vX.Y.Z-alpha.N` タグを自動作成し、対応する Pre-release を公開します。日常的な開発では、通常 `alpha` tag を手動で打つ必要はありません。

```bash
git branch -d feat/my-feature
```

### 5. さらなる修正が必要な場合

2 つの方法があります：

- **PR がまだマージされていない** — PR を **Draft** に設定し、同じブランチで修正を続け、完了後に Ready for review に戻します。
- **PR がすでにマージされている** — 上記のフローを繰り返し、最新の `dev` から新しい `feat/`、`fix/`、または `refact/` ブランチを切ります。

> この方針により、各ブランチが単一の責務と明確なライフサイクルを持ち、1 つのブランチに無関係な複数の変更が混在する混乱を防ぐことができます。

---

ご不明な点がありましたら、[Issues](https://github.com/AuroraBot-Dev/AuroraBot/issues) までお気軽にお問い合わせください。
