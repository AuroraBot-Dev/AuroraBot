# AuroraBot へのコントリビューション

<a href="CONTRIBUTING.md">中文</a> | <a href="CONTRIBUTING.en.md">English</a> | <b>日本語</b>

AuroraBot が目指すのは、道具のような Agent ではありません。持続的に存在し、自分のリズムを持ち、自分の世界の中で判断して行動できる Bot です。私たちが探求したいのは「どうモデルを接続するか」だけではなく、彼女がどう働き続け、確実に行動し、人にその理由を理解してもらえるか、です。
バグ修正、より自然な紹介文、MCP アプリ、runtime の改善など、どのような貢献も歓迎します。

## 自分に合った入口を見つける

- **初めての貢献**：ドキュメントの修正、テストの追加、境界が明確な小さい問題の選択。
- **アプリケーション開発者**：MCP サービスやプラグインを通して AuroraBot に機能を提供する。
- **runtime 開発者**：ReAct 実行、モデルアダプター、MCP 統合、ローカルの対話体験を改善する。
- **設計への参加**：Issue や Discussion でユースケース、公開 contract、module 境界を議論する。

どこから始めればよいか分からない場合は、まず Discussion や Issue で改善したい体験を説明してください。

## 開発環境の準備

### 1. このリポジトリをクローン

Python 3.12 以上、Git、[uv](https://docs.astral.sh/uv/) が必要です。CI は Python 3.12 / 3.13 を検証します。
TUI、Panel、工程スクリプトには [package.json](../package.json) と [.node-version](../.node-version) で指定した [Node.js](https://nodejs.org/) と [pnpm](https://pnpm.io/) が必要です。開発チェックの前に `pnpm install --frozen-lockfile` を実行してください。

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

支援 Bot はこのメッセージを処理して終了します。実際の会話では設定したモデルを呼び出します。継続的な会話、TUI、Panel の接続は[初回起動ガイド](../examples/START.md)、正式な Bot の起動は[操作ガイド](../docs/operations.md)を参照してください。

テストと静的解析を実行するだけなら、実際のモデルキーは不要です。キーはローカルの `.env` かプロセスの環境にのみ書き込みます。キー、実際の会話、モデルの完全な応答、workspace event、アップロードしたファイル、実行ログをコミットしないでください。

## 変更の前に

公開 contract、永続化、module 境界を変更する場合は、Bot のユースケース、不変条件、検証方法を明確にしてください。開発上の制約は [AGENTS.md](../AGENTS.md)、各コンポーネントの責務は[システム概要](../docs/aurorabot-design-v0.2.3.md)を参照してください。大きな設計は Issue や Discussion で議論します。

ドキュメントには現在の使い方、機能、制限を記載し、変更経緯は [docs/CHAGELOG.md](../docs/CHAGELOG.md) に記録します。簡体中文を基準とし、対応する翻訳も更新してください。

## 閉じたループを保つ

コードに貢献するときは、AuroraBot を確実に動かすための境界を守ってください：

- モデルが判断し、runtime が実行します。assistant は応答するか tool を要求するだけです。実際の外部 effect は Tool contract を通してのみ実行され、通常の model text は effect ではありません。
- 各 agent インスタンスは一つの AgentRuntime が管理し、会話、cadence、予定された起床は同じ所有者へガイダンスを送ります。
- 実行系の依存方向は `bot → agent → control → core` です。`aurora_adapter` がモデルと MCP を接続し、`aurora_config` が設定を宣言します。CLI、API、画面はバックエンドの実行契約を再利用します。
- 構造設定は引き続き TOML を使い、キーは環境変数だけから読み取ります。
- 共有ログは `aurora_logging` で設定し、`logging.getLogger(__name__)` 経由で取得します。完全な prompt、モデル応答、機密 payload は記録しません。

より完全なメンテナー境界は、リポジトリルートの `AGENTS.md` を参照してください。

## AIGC

AuroraBot は AI を活用した開発を歓迎しますが、生成された内容も同じプロジェクトの境界に従う必要があり、「AI が書いた」という理由での免除はありません：

- **検証可能であること**：AI が生成または大幅に変更したコードは、`aurora check --full` のすべてのチェックを通過し、オフラインで決定論的で再現可能なテストを伴うこと；
- **理解して責任を持つこと**：生成されたコードを 1 行ずつ読み、その挙動を説明でき、正しさと安全性の責任を負うこと；
- **境界を守ること**：既存の依存方向と contract を維持し、平行な実行モデルや閉じたループを迂回する旁路を導入しないこと；
- **品質をごまかさないこと**：lint ignore で生成コードの複雑さを隠さないこと。原則として単一ファイルは 600 行を超えないこと；
- **テキストの権威は中国語**：ユーザー向けテキストは簡体中文が権威版で、「実験、refactor、旧版、migration」などの歴史的な物語や、能力・API・サンプルデータの捏造を書かないこと；
- **出所と安全**：出所不明やライセンス非互換のコードを導入せず、キー、実際のセッション、プライベートデータを生成・コミットしないこと；
- **正直に開示すること**：Pull Request の説明に、AI が生成または支援した部分を明記し、レビューをしやすくすること。

違反の結果：

- 上記に違反した PR は差し戻され、該当部分の修正または書き直しが求められます；
- `aurora check` を実行せず理由も説明されていない PR はマージされません；
- 繰り返しまたは重大な違反（キーの漏洩、テスト結果の偽造、セキュリティやアーキテクチャ境界の迂回など）は、PR のクローズ、メンテナーによる記録、その後の貢献制限につながります。

## 変更の提出

1. `main` から短命のブランチを作成します。新機能には `feat/<name>`、修正やリファクタリングには `fix/` または `refact/` を使用します。
2. 各 Pull Request を、レビュー可能な 1 つの目標に集中させ、対応するテストとドキュメントを添えます。
3. マージ先を `main` に設定し、挙動の変化、検証結果、関連 Issue を説明します。
4. CI とレビューが通るまで待ち、完了したブランチを削除します。

## 検証

提出前に統一チェックを実行します：

```powershell
pnpm exec uv run --locked aurora check
```

検証範囲に応じて、個別に実行できます：

```powershell
pnpm exec uv run --locked pytest packages/aurora_agent/tests/unit/test_agent_runtime.py -q
pnpm exec uv run --locked aurora check --full
pnpm exec uv run --locked aurora check --test --coverage
uv run --locked ruff check .
uv run --locked ruff format --check .
pnpm typecheck
```

`uv sync --locked --all-packages` と `pnpm install --frozen-lockfile` で開発依存関係をインストールします。
パッケージ内テストは `packages/<package>/tests/unit` と `tests/contract`、パッケージ間契約はルートの `tests/contract`、プロセス・統合テストは `tests/e2e` に配置します。共有フィクスチャは `tests/fixtures` とルートの `conftest.py` に置きます。
通常のチェックは短時間の境界テストを実行し、`--full` と `--coverage` は完全な範囲を使います。CI は `--full` を実行し、明示的なカバレッジチェックの下限は 20% です。この値は最低基準であり、削減目標ではありません。重複ケースや補助関数自身のテスト、
行数を埋めるだけの断言よりも、挙動・境界・障害回復を検証します。

テストはオフラインで、決定論的で、再現可能でなければなりません。モデル、時計、MCP は fake を使い、実際の使用量を消費せず、公衆ネットワークに依存しません。バグ修正は元の失敗パスをカバーし、event と effect のテストはトランザクション境界、冪等性、実行 ID の関連付けも検証してください。

## 提出前のセルフチェック

- 利用者がドキュメントやテストから変更による挙動の違いを理解できる。
- 新しい挙動がモデルの判断、Tool 実行、結果の反映という閉じたループを迂回していない。
- 設定、ドキュメント、テストが互いに矛盾していない。
- ログとテストフィクスチャに実際のキー、セッション、プライベートデータが含まれていない。
- `aurora check` が通っているか、Pull Request で実行できなかった部分が明確に説明されている。

コントリビューションを行うことで、プロジェクトの[行動規範](CODE_OF_CONDUCT.md)に同意したことになります。
