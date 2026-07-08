<p align="center">
  <img src="assets/logo.svg" width="120" alt="AuroraBot ロゴ" />
</p>

<h1 align="center">AuroraBot</h1>

<p align="center">
  <a href="README.md">中文</a> | <a href="README.en.md">English</a> | <b>日本語</b>
</p>

<p align="center">
  <em>AuroraBot Core + MCP Platform ベースの内発的・自律的意思決定エージェントフレームワーク</em>
</p>

<p align="center">
  ファイル駆動認知エンジン · 三層連合記憶 · プラグ可能な MCP App Server
</p>

<p align="center">
  <a href="https://github.com/AuroraBot-Dev/AuroraBot"><img src="https://img.shields.io/badge/GitHub-リポジトリ-black?logo=github" alt="GitHub" /></a>
  <a href="https://github.com/AuroraBot-Dev/AuroraBot/actions/workflows/ci.yml"><img src="https://github.com/AuroraBot-Dev/AuroraBot/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
  <a href="https://www.aurorabot.org/"><img src="https://img.shields.io/badge/Docs-ドキュメント-blue?logo=vitepress" alt="Docs" /></a>
  <a href="./LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-green" alt="License" /></a>
</p>

---

## 彼女について

AuroraBot は、次世代の**内発的・自律的意思決定エージェントフレームワーク**です。彼女は 2 つのランタイム層と 1 つの認知エンジンで構成されています：

- **アプリケーション層 (Apps)** — プラグ可能な MCP Server センサーとアクチュエーター。各 App は `manifest.yaml` / `apps/config.yml` で能力を宣言
- **プラットフォーム層 (Platform)** — MCP Host Layer がローカル stdio Server のライフサイクル、Client 接続、tools/call、notification イベント橋接を管理
- **認知エンジン (Brain / CortexForge)** — ファイル駆動の認知 OS カーネル。2 つのサブシステムで構成：
  - **kernel**: `Node` / `Agent` / `Router` ノードネットワーク + `FileEventBus` イベントバス + `Circuit` オーケストレーター
  - **memory**: L1 作業記憶 / L2 エピソード記憶 / L3 意味記憶、`UnifiedMemoryManager` で統一アクセス

> 彼女は「指示を待つ」のではなく、「継続的に観察し、自律的に判断し、能動的に行動する」のです。

## アーキテクチャ概要

```mermaid
flowchart LR
    subgraph APPS["アプリケーション層 (Apps)"]
        direction TB
        QQ["QQ アダプター"]
        ALARM["スケジュールリマインダー"]
        DIARY["日記"]
    end

    subgraph PLATFORM["プラットフォーム層 (Platform)"]
        direction TB
        KIT["MCPServerKit"]
        CLIENT["MCPClientManager"]
        AMP["AMP envelope"]
        TOOLS["tools/list + tools/call"]
    end

    subgraph BRAIN["認知エンジン (CortexForge)"]
        subgraph KERNEL["kernel サブシステム"]
            direction LR
            CIRCUIT["Circuit オーケストレーター"]
            BUS["FileEventBus"]
            NODES["Agent / Router ノード"]
        end
        subgraph MEMORY["memory サブシステム"]
            direction LR
            L1["L1 作業記憶"]
            L2["L2 エピソード記憶"]
            L3["L3 意味記憶"]
        end
        GATEWAY["LLM / Embedding ゲートウェイ (litellm)"]
    end

    APPS <-->|"stdio MCP / aurora/event"| PLATFORM
    PLATFORM <-->|"AMP イベントブリッジ / ツール呼び出し"| BRAIN
```

### 高度に分離された App プラグインシステム

各 App は独立した MCP Server です。QQ、タイマー、ファイルシステム、外部 API への接続も 1 つの Server で実現できます。App は `manifest.yaml` と `apps/config.yml` で起動コマンドとツール能力を宣言し、Platform が統一的に接続・発見・呼び出しを行います。

### 宣言的認知トポロジー

認知は単一の「スーパーエージェント」に依存せず、複数の `Agent` / `Router` ノードが `topology.yaml` で宣言的に構成されます。ノード間は `FileEventBus` ファイルイベントバスを通じて状態を受け渡し、ファイル駆動の認知パイプラインを形成します。将来的には、サードパーティによる認知能力拡張のための認知ノードプラグインを開放予定です。

### 三層連合記憶

AuroraBot の記憶は**構造的に成長**します：

| 層                | タイプ            | ストレージ         | 用途                           |
| ----------------- | ----------------- | ------------------ | ------------------------------ |
| L1 作業記憶       | FIFO メモリリスト | 永続化なし         | 現在のセッションコンテキスト   |
| L2 エピソード記憶 | JSON ファイル追記 | 50 件後に LLM 圧縮 | タイムラインベースのアーカイブ |
| L3 意味記憶       | ChromaDB ベクトル | 無制限             | 意味的類似度検索               |

`UnifiedMemoryManager` が三層を統一インターフェースでカプセル化し、ノードは基盤のデータフローを意識する必要がありません。すべての対話が三層に一括書き込みされ、検索時には全層から結果をマージします。

## MCP App Server 体系

AuroraBot の App 体系は **MCP (Model Context Protocol)** を主経路として採用し、任意の MCP Server を App として接続できます。

これは次のことを意味します：

- MCP プロトコルに準拠するあらゆるツールが AuroraBot の能力拡張になり得る
- MCP ツールは Brain から見えるツール記述へ変換される
- Brain は MCP Client 経由でツールを呼び出し、イベントは AMP envelope としてファイル駆動パイプラインへ入る

> MCP エコシステムをあなたの能力拡張に。

## クイックナビゲーション

完全なアーキテクチャ設計、利用ガイド、開発ドキュメントについては、**[AuroraBot ドキュメントサイト 📖](https://www.aurorabot.org/)** をご覧ください：

| ドキュメント                                                                          | 説明                                                             |
| ------------------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| [概要](https://www.aurorabot.org/start/overview.html)                                 | AuroraBot のビジョンとアーキテクチャを素早く理解                 |
| [クイックスタート](https://www.aurorabot.org/start/getting-started.html)              | ゼロからプロジェクトを起動                                       |
| [設定](https://www.aurorabot.org/start/configuration.html)                            | 環境変数、プラットフォーム設定、アプリ設定、ペルソナドキュメント |
| [システムアーキテクチャ](https://www.aurorabot.org/architecture/system-overview.html) | Apps / Platform / Kernel / Brain の 4 層を理解                   |
| [認知アーキテクチャ](https://www.aurorabot.org/architecture/brain-architecture.html)  | ファイル駆動の認知パイプラインと現在有効なトポロジー             |
| [ノードシステム](https://www.aurorabot.org/architecture/node-system.html)             | Node / Agent / Router のデータ構造とイベントバス                 |
| [記憶システム](https://www.aurorabot.org/architecture/memory-system.html)             | L1 / L2 / L3 三層連合記憶の保存と検索                            |
| [App 開発ガイド](https://www.aurorabot.org/develop/app-development.html)              | 構造からライフサイクルまで自作 App を開発                        |
| [認知ノード開発](https://www.aurorabot.org/develop/brain-node-development.html)       | Agent / Router ノードを作成する                                  |
| [AUR CLI](https://www.aurorabot.org/develop/aur-cli.html)                             | アプリ開発ツールチェーンロードマップ                             |

## オープンソースへの謝辞

AuroraBot は多くの優れたオープンソースプロジェクトの上に構築されています：

| プロジェクト                                      | 説明                                               | ライセンス                                                                          |
| ------------------------------------------------- | -------------------------------------------------- | :---------------------------------------------------------------------------------- |
| [LiteLLM](https://github.com/BerriAI/litellm)     | 統合 LLM API コール層                              | [LICENSE](https://github.com/BerriAI/litellm/blob/litellm_internal_staging/LICENSE) |
| [mem0](https://github.com/mem0ai/mem0)            | エージェント記憶基盤                               | [Apache License 2.0](https://github.com/mem0ai/mem0/blob/main/LICENSE)              |
| [ChromaDB](https://github.com/chroma-core/chroma) | オープンソースベクトルデータベース                 | [Apache License 2.0](https://github.com/chroma-core/chroma/blob/main/LICENSE)       |
| [VitePress](https://github.com/vuejs/vitepress)   | ドキュメントサイトジェネレーター                   | [MIT License](https://github.com/vuejs/vitepress/blob/main/LICENSE)                 |

**[MaiBot](https://github.com/MaiM-with-u/MaiBot)** には、アーキテクチャのインスピレーションと設計参考を提供していただき、特別に感謝いたします。

## ライセンス

本プロジェクトは [Apache License 2.0](./LICENSE) の下でオープンソース公開されています。

---

## Star History

<a href="https://www.star-history.com/?repos=AuroraBot-Dev%2FAuroraBot&type=date&logscale=&legend=bottom-right">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=AuroraBot-Dev/AuroraBot&type=date&theme=dark&logscale&legend=bottom-right" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=AuroraBot-Dev/AuroraBot&type=date&logscale&legend=bottom-right" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=AuroraBot-Dev/AuroraBot&type=date&logscale&legend=bottom-right" />
 </picture>
</a>

---

<p align="center">
  <sub>Built with ❤️ by <a href="https://github.com/JuFireX">JuFireX</a> | <a href="https://github.com/AuroraBot-Dev">AuroraBot-Dev</a></sub>
</p>
