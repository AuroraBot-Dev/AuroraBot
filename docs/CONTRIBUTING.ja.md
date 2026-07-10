# コントリビューションガイド

<a href="./CONTRIBUTING.md">中文</a> | <a href="./CONTRIBUTING.en.md">English</a> | <b>日本語</b>

AuroraBot は vNext の再構築段階にあります。直近の目標は、`legacy/` の全機能を復元することではなく、契約に基づく最小因果ループを確立することです。

## 始める前に

- Python 3.12 と `uv` を使用してください。
- `docs/rfc/README.md` と、変更が影響する受理済み RFC を読んでください。
- `legacy/` は履歴参照であり、アーキテクチャのテンプレートではありません。

## ルール

1. アーキテクチャ、イベント、設定、拡張、モデルゲートウェイの契約を変更する前に RFC を更新または追加します。
2. 受理済み契約ごとに自動実行可能なテストを追加します。
3. Kernel のイベント記録を迂回してワークスペースを操作してはいけません。Dashboard は Kernel や Platform を直接呼び出してはいけません。
4. TOML に秘密情報を書かず、JSON を構造設定に使わないでください。
5. vNext のエントリポイントができるまで、`bot.py` を vNext の起動方法として説明しないでください。

## チェック

```bash
uv sync --group dev
uv run ruff check bot.py src/ tests/
uv run ruff format --check bot.py src/ tests/
uv run pyright bot.py src/
uv run pytest --cov=src
```

コマンドは vNext 実装に合わせて更新されます。CI と受理済み RFC が基準です。
