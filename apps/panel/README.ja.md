# AuroraBot Panel

<a href="README.md">中文</a> | <a href="README.en.md">English</a> | <b>日本語</b>

AuroraBot の読み取り専用 Web 観察パネルです。Vue、Vite、Naive UI、Vben Admin をベースとし、AuroraBot の ops バックエンドに接続して、構成済み機能、設定、世界タイムライン、実行状態を確認します。

## 環境要件

- [Node.js](https://nodejs.org/) 22.18+ または 24.12+
- [pnpm](https://pnpm.io/) 11+
- `/serve` を実行済みの AuroraBot Console

```bash
npm install -g pnpm   # 未インストールの場合
```

## ローカル開発

先に AuroraBot メインリポジトリで Console を起動し（aurora はメインリポジトリの setup スクリプトでリンク済み。未リンクの場合は `uv run aurora start`）、Console で `/serve` を実行します：

```bash
aurora start
# 起動した Console で /serve を入力
```

`/serve` で起動したバックエンドはデフォルトで `http://127.0.0.1:8765` をリッスンします。続いて別のターミナルで、メインリポジトリのルートから `aurora panel` でパネルを操作します（`aurora setup` が workspace の依存関係をインストールします）：

```bash
aurora panel dev      # 開発サーバーの起動
aurora panel build    # 本番ビルド
```

開発サーバーは Vite 経由で `/api` と `/healthz` をバックエンドにプロキシします。ログインには、バックエンドが `data/ops/Token.txt` に生成する bootstrap token を使用します。クロスオリジンでのデプロイ時は、`VITE_GLOB_API_URL` で API アドレスを設定できます。

このリポジトリで直接実行することもできます：

```bash
pnpm install --frozen-lockfile
pnpm dev
```

## リリースとデプロイ

パネルは純粋な静的 SPA で、`dist` が成果物の全体です。API アドレスはランタイム設定として、再ビルドなしでデプロイ時に変更できます。バックエンドは loopback のみをリッスンするため、パネルは同じマシンにデプロイする必要があります：

1. **nginx リバースプロキシ**：`scripts/deploy/nginx.conf`（静的ファイルの配信と `/api`・`/healthz` のプロキシ）を使用し、アクセス元をバックエンドの `config/runtime.toml` の `runtime.panel.allowed_origins` に追加します。
2. **コンテナ**：`scripts/deploy/build-local-docker-image.sh` でイメージをビルドし、`--network host` で実行します。

純粋なローカル利用では `pnpm dev`（Vite プロキシ）または `pnpm build && pnpm preview` でも構いません。リモートアクセスはメインリポジトリのドキュメントに従い、バックエンドをローカルのまま信頼できるトンネルを構築してください。
