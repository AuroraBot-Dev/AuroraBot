# AuroraBot vNext

<p align="center">
  <a href="README.md">中文</a> | <a href="README.en.md">English</a> | <b>日本語</b>
</p>

AuroraBot は、因果イベントを中心にした自律エージェント・フレームワークとして再構築中です。旧実装は `legacy/` に凍結されており、vNext の設計基準ではありません。

## 設計の基準

`docs/rfc/` は vNext の唯一の設計基準です。コード、設定例、貢献ガイド、公開文書は、受理済み RFC に従わなければなりません。

最初の因果閉ループは次のとおりです。

```text
プラットフォーム環境イベント（AMP JSON）
  → Kernel の取込み、周期スナップショット、グラフ調停
  → builtin.decide ノード
  → effect.requested
  → プラットフォーム能力の実行
  → effect.succeeded / effect.failed（次周期）
```

生成されたテキスト自体は効果ではありません。プラットフォームが実行結果を返した時点で初めて因果ループが閉じます。

## 構成

```text
config/       TOML 設定と profile 上書き
docs/rfc/     規範的な vNext 設計文書
legacy/       凍結した旧コードとテスト
src/          vNext 実装
tests/        vNext 契約・統合テスト
extensions/   サードパーティ拡張の推奨配置先
```

Kernel の管理ワークスペースは `data/kernel/{inbox,process,archive}` です。構造設定には TOML、実行時データには JSON、秘密情報には環境変数を使います。

## RFC

- [RFC 0000: RFC process](docs/rfc/0000-rfc-process.md)
- [RFC 0001: Architecture baseline](docs/rfc/0001-architecture.md)
- [RFC 0002: Configuration baseline](docs/rfc/0002-configuration.md)
- [RFC 0003: Event and causality contract](docs/rfc/0003-event-contract.md)
- [RFC 0004: Extension contract](docs/rfc/0004-plugin-contract.md)
- [RFC 0005: Model gateway](docs/rfc/0005-model-gateway.md)

## 再構築の状態

vNext にはまだ実行可能な Bot エントリポイントがありません。ルートの旧エントリポイントや `legacy/` のコードを vNext の起動方法として扱わないでください。

## ライセンス

[Apache License 2.0](LICENSE) で提供されます。
