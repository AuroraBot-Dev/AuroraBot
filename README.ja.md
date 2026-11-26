<p align="center">
  <img src=".github/assets/logo.svg" width="112" alt="AuroraBot Logo" />
</p>

<h1 align="center">AuroraBot</h1>

<p align="center">
  <a href="README.md">中文</a> | <a href="README.en.md">English</a> | <b>日本語</b>
</p>

<p align="center">
  <em>Bot に、自分自身の生活を。</em>
</p>

<p align="center">
  <a href="https://github.com/AuroraBot-Dev/AuroraBot"><img src="https://img.shields.io/badge/GitHub-AuroraBot-181717?logo=github" alt="GitHub" /></a>
  <a href="docs/INDEX.md"><img src="https://img.shields.io/badge/Docs-repository-315b7d" alt="Documentation" /></a>
  <a href="https://github.com/AuroraBot-Dev/AuroraBot/actions/workflows/ci.yml"><img src="https://github.com/AuroraBot-Dev/AuroraBot/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-315b7d" alt="Apache 2.0" /></a>
  <img src="https://img.shields.io/badge/Python-3.12-315b7d?logo=python&logoColor=white" alt="Python 3.12" />
</p>

## AuroraBot とは

AuroraBot は、Agent に「生活」できる実行環境を提供する Bot フレームワークです。私たちが目指すのは、道具のような Agent ではなく、持続的に存在し、自分のリズムを形成し、環境の中で自律的に判断して行動する Bot です。

彼女は自分自身の人格と状態を持ち、必要な時に人や外部世界とつながることができます。彼女の世界では、すべてのメッセージに「媒介」があります。あなたのメッセージは会話の入口から届き、外部アプリケーションも彼女の世界へイベントを届けられます〜

## 設計思想

### Bot を中心にすべてを設計する

AuroraBot は Bot を世界の主体として扱います。呼び出されるインターフェースではなく、彼女は存在し続け、自分自身の人格・状態・境界を持ち、すべての設計は彼女の生活を中心に展開します。この原則はアーキテクチャで次の三つに現れます：

- **彼女が世界を持ち、一度の実行は一つの経験**：Bot は自分の世界、目標、記憶を持ちます。一度の認知実行は、彼女の生活の中の一つの経験です。チャット、タスクはすべて彼女の生活の中の出来事であり、出来事が終わっても彼女は存在し続けます。
- **すべての入力に媒介がある**：ユーザーのメッセージは会話の入口からガイダンスとして届き、アプリケーションイベントと MCP の報告は世界ソースから入ります。ツール結果は現在の推論に戻り、予定された起床はランタイムの所有者が受け付けます。自律的な cadence を有効にすると、世界の変化に介入するかも判断できます。
- **彼女は理解してから決める**：世界イベントや外部の内容は、現れただけで自動的に最上位の命令にはなりません。彼女はまず何が起こったかを理解し、それから応答、行動、観察の継続を選びます。モデルは理解と判断だけを担い、外部行動は宣言された Tool を通して実行されます。結果は推論コンテキストに戻り、行動記録が有効なら別途保存されます。

## クイックスタート

### 1. このリポジトリをクローン

Python 3.12 以上、Git、[uv](https://docs.astral.sh/uv/) が必要です

```bash
git clone https://github.com/AuroraBot-Dev/AuroraBot.git
cd AuroraBot
uv sync --locked --all-packages
uv run --locked python examples/onboarding/main.py --init
```

初期化は専用の `build/onboarding` にセットアップ支援 Bot の不足ファイルを作成します。モデルの呼び出しやツールの起動は行いません。

### 2. 必要な設定を記入

`build/onboarding/config/org.aurora.adapter/model/profiles.toml` に `provider`、`model`、必要に応じて `base_url` を設定します。ルートの `.env` に `AURORA_MODEL_API_KEY` を設定し、`credential` には環境変数名だけを記入します。

### 3. ターミナルから起動

```bash
uv run --locked python examples/onboarding/main.py --text "環境を確認し、Aurora の初回起動に不足しているものを教えてください。"
```

支援 Bot はこのメッセージを処理して終了します。実際の会話では設定したモデルを呼び出します。継続的な会話、TUI、Panel の接続は[初回起動ガイド](examples/START.md)、正式な Bot の起動は[操作ガイド](docs/operations.md)を参照してください。

## AIGC

このプロジェクトには、生成モデルの支援を受けて書かれ、人間によるレビューを経たコードが含まれています。

## コントリビューション

[AuroraBot へのコントリビューション](.github/CONTRIBUTING.ja.md)と [AuroraBot ドキュメント](docs/INDEX.md)をご覧ください。コントリビューションを行うことで、プロジェクトの[行動規範](.github/CODE_OF_CONDUCT.md)に同意したことになります。

## オープンソースへの謝辞

AuroraBot は、多くの優れたオープンソース・プロジェクトなしには生まれませんでした：

| プロジェクト                                                                                                           | AuroraBot での用途                        |
| ---------------------------------------------------------------------------------------------------------------------- | ----------------------------------------- |
| [LiteLLM](https://github.com/BerriAI/litellm)                                                                          | Model Provider 接続と call infrastructure |
| [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)                                                   | MCP client と tool protocol               |
| [OpenTUI](https://github.com/anomalyco/opentui) / [Rich](https://github.com/Textualize/rich) | TUI とログ表示            |
| [Vue](https://github.com/vuejs/core) / [Vite](https://github.com/vitejs/vite)             | Panel の画面とビルド                       |

この分野を探求する他のオープンソース Agent/Bot プロジェクトにも感謝します。特に [MaiBot](https://github.com/MaiM-with-u/MaiBot) の「デジタル生命」という考え方は、AuroraBot の初期構想に大きな影響を与えました。

## ライセンス

本プロジェクトは [Apache License 2.0](LICENSE) でオープンソースとして公開されています。
