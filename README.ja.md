<p align="center">
  <img src="assets/logo.svg" width="112" alt="AuroraBot Logo" />
</p>

<h1 align="center">AuroraBot</h1>

<p align="center">
  <a href="README.md">中文</a> | <a href="README.en.md">English</a> | <b>日本語</b>
</p>

<p align="center">
  <em>能動的なリズムで動き続け、すべての行動の経緯をたどれる自律エージェント・フレームワーク。</em>
</p>

<p align="center">因果イベント · 同構 Agent · 能動的なリズム</p>

<p align="center">
  <a href="https://github.com/AuroraBot-Dev/AuroraBot"><img src="https://img.shields.io/badge/GitHub-AuroraBot-181717?logo=github" alt="GitHub" /></a>
  <a href="https://github.com/AuroraBot-Dev/AuroraBot/actions/workflows/ci.yml"><img src="https://github.com/AuroraBot-Dev/AuroraBot/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-315b7d" alt="Apache 2.0" /></a>
  <img src="https://img.shields.io/badge/Python-3.12-315b7d?logo=python&logoColor=white" alt="Python 3.12" />
</p>

## AuroraBot とは

AuroraBot は、開発者向けのオープンソース自律エージェント・フレームワークです。エージェントを独立した問答の
繰り返しとして扱うのではなく、環境の変化、モデルの判断、能力の呼び出し、行動の結果を、停止・再開・振り返りが
できる一続きの経験として扱います。

誰も話しかけていない時でも、AuroraBot は自分のリズムで目を覚まし、今行動すべきかを判断できます。仕事が複雑に
なれば、同構 Agent が範囲を限定して協力します。外部世界へ作用する時は、宣言され、許可された能力だけが実際の
効果を生みます。

> 彼女は指示を待つのではなく、観察し、判断し、行動し続けます。

## 何を作れるのか

- **自ら目を覚ます Agent**：永続 scheduler が予算内で自律的な時刻を作り、外部メッセージが来れば対話 Task を
  すぐに優先します。
- **複雑な仕事の自然な分担**：Agent は簡単な依頼を直接処理し、必要なら限定された子 Task に委任して、結果が
  戻ったところから再開します。
- **現実世界につながる能力**：MCP application で時刻、リマインダー、その他の tool を追加し、利用前に権限と
  引数を検証します。
- **複数の出会い方**：ローカル Console、独立した Dashboard UI、または headless runtime から利用できます。
- **理解できる行動履歴**：入力、モデル呼び出し、tool request、receipt、終了理由が一つの因果記録につながります。

このリポジトリには、時刻、アラーム、タイマーを扱う Clock MCP application が含まれます。すぐ使える能力であると
同時に、新しい application を追加するための最小例でもあります。

## 一つの体験から見る仕組み

「午後7時に会議を知らせて」と話した時、AuroraBot はモデルの文章を実行済みの行動として扱いません。

1. メッセージが環境イベントになり、独立した Task を起動します。
2. root Agent が依頼を理解し、許可済みの Clock 能力を選びます。
3. Clock が構造化された receipt を返し、リマインダーが実際に設定されたことを確認します。
4. 時刻になると Clock が新しい環境イベントを作り、AuroraBot を再び起動します。
5. AuroraBot が現在の Platform を通してリマインダーを届けます。

このループが、AuroraBot と単純な「入力からテキストを返す」ラッパーとの違いです。モデルが判断し、runtime が
行動を確実に発生させます。

## クイックスタート

Python 3.12、Git、[uv](https://docs.astral.sh/uv/) が必要です。現在はソースからの実行をサポートしています。

```powershell
git clone https://github.com/AuroraBot-Dev/AuroraBot.git
Set-Location AuroraBot
uv sync --no-dev
Copy-Item .env.example .env

# 既定設定に必要な DEEPSEEK_API_KEY を .env に追加
uv run --no-dev --env-file .env aurora --console --mcp
```

起動後はそのままメッセージを入力できます。`/help` で command を確認し、`/status` で状態を表示できます。

### 実行方法を選ぶ

```powershell
# config/preference.toml を使用：既定では Console、Dashboard backend、MCP
uv run --no-dev --env-file .env aurora

# ローカル Console のみ起動
uv run --no-dev --env-file .env aurora --console

# 外部 Platform なしで Kernel と能動的なリズムを実行
uv run --no-dev --env-file .env aurora --headless
```

`--console`、`--dashboard`、`--mcp` のいずれかを指定すると、それらが正確な Platform 集合になり、既定値には
追加されません。Dashboard UI は別プロジェクトです。このリポジトリにはローカル backend と chat bridge があり、
browser UI は含まれません。

## 自分の Agent にする

よく使うカスタマイズ項目は、役割ごとに分かれた設定ファイルにあります。

| 変更したいもの | 最初に見る場所 |
| --- | --- |
| persona、話し方、会話の境界 | `config/prompts/SOUL.md` |
| model role と Provider | `config/aurora.toml` |
| 既定で起動する Platform | `config/preference.toml` |
| Agent の model、能力、委任範囲 | `config/agents.toml` |
| ローカルまたはリモート MCP application | `config/apps.toml` |

構造設定には TOML を使い、secret は環境変数からのみ読み取ります。拡張 application が Kernel に直接触れる必要は
ありません。[拡張ガイド](extensions/README.md)と組み込みの
[Clock application](src/apps/aurora-app-clock/README.md)から始められます。

## 現在の段階

AuroraBot `0.4` は、ローカルでの体験、runtime の研究、拡張開発を目的とした developer preview です。組み込みの
長期記憶、添付ファイル理解、Agent sandbox tool、本番向け multi-tenant 保証はまだ提供していません。Dashboard の
debug endpoint もローカルマシンの境界内だけで利用してください。

未完成の roadmap を現在の能力として見せることはしません。現在の公開動作は、accepted RFC とテストが定義します。

## さらに読む

- [コントリビューションガイド](docs/CONTRIBUTING.ja.md)：開発環境を準備して改善を提出する
- [AuroraBot の拡張](extensions/README.md)：MCP application と Agent profile を接続する
- [モデル gateway](src/ai/README.md)：model role、能力、endpoint を理解する
- [RFC 読み方ガイド](docs/rfc/README.md)：現在有効な設計判断を確認する
- [ログ規約](LOGGING.md)：diagnostics、privacy、audit の境界
- [行動規範](CODE_OF_CONDUCT.md)：歓迎されるオープンソース・コミュニティを維持する

## オープンソース

AuroraBot は [Apache License 2.0](LICENSE) で公開されています。優れた Agent framework は、すべての人のためにあると
私たちは考えています。
