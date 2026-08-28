# AuroraBot へのコントリビューション

<a href="CONTRIBUTING.md">中文</a> | <a href="CONTRIBUTING.en.md">English</a> | <b>日本語</b>

AuroraBot が目指すのは、道具のような Agent ではありません。持続的に存在し、自分のリズムを持ち、自分の世界の中で判断して行動できる Bot です。私たちが探求したいのは「どうモデルを接続するか」だけではなく、彼女がどう働き続け、確実に行動し、人にその理由を理解してもらえるか、です。
バグ修正、より自然な紹介文、MCP アプリ、runtime の改善など、どのような貢献も歓迎します。

## 自分に合った入口を見つける

- **初めての貢献**：ドキュメントの修正、テストの追加、境界が明確な小さい問題の選択。
- **アプリケーション開発者**：内蔵 Clock アプリから始めて、AuroraBot に新しい MCP 機能を接続する。
- **runtime 開発者**：AgentTree、engine、model gateway、MCP 統合、ローカルの対話体験を改善する。
- **設計への参加**：公共 contract と module 境界の RFC を提案し、実行可能な acceptance criteria で議論を進める。

どこから始めればよいか分からない場合は、まず Discussion や Issue で改善したい体験を説明してください。

## 開発環境の準備

### 1. このリポジトリをクローン

Python 3.12（推奨。それ以上のバージョンは十分に検証されていません）、Git、[uv](https://docs.astral.sh/uv/) が必要です。
ドキュメントや panel の開発にはさらに [Node.js](https://nodejs.org/) と [pnpm](https://pnpm.io/) が必要です。

```bash
git clone https://github.com/AuroraBot-Dev/AuroraBot.git
cd AuroraBot
./scripts/linux/setup.sh
# macOS: ./scripts/macos/setup.command;
# Windows: .\scripts\windows\setup.ps1.
```

`setup.sh` は git/uv/pnpm を確認し、aurora をユーザーのツールディレクトリにグローバルリンクするか確認した後、`aurora setup` が依存関係、個人設定、docs/panel サブモジュールの初期化を行います。

### 2. 必要な設定を記入

`.env` に既定モデルが必要とするキー（例：`DEEPSEEK_API_KEY`）を記入します

### 3. ターミナルから起動

```bash
aurora start
```

起動後はメッセージを入力して会話できます。`/help` で操作を確認し、`/exit` で終了します。

テストと静的解析を実行するだけなら、実際のモデルキーは不要です。キーはローカルの `.env` かプロセスの環境にのみ書き込みます。キー、実際の会話、モデルの完全な応答、workspace event、アップロードしたファイル、実行ログをコミットしないでください。

## 変更の前に

AuroraBot は、長期的に影響を与える設計上の決定を RFC に記録します。次の変更は、`docs/rfc/` の RFC を先に更新または新規作成してください：

- module の責務または依存方向；
- AgentTree、委任、tool 受領 contract；
- TOML 設定、extension protocol、または model call contract；
- platform の構成、プロセス入口、永続化の意味を変える挙動。

小さなバグ修正、テストの追加、文言の改善、公共の意味を変えない refactor は直接提出できます。公開ドキュメントを変更した場合は、中国語・英語・日本語の入口をまとめて更新してください。

現在の runtime、パッケージ境界、プロセス構成は、唯一の設計基準 [RFC 0300](docs/rfc/0300-unified-architecture-and-contracts.md) に従います。

## 閉じたループを保つ

コードに貢献するときは、AuroraBot を確実に動かすための境界を守ってください：

- モデルが判断し、runtime が実行します。assistant は応答するか tool を要求するだけです。実際の外部 effect は Tool contract を通してのみ実行され、通常の model text は effect ではありません。
- 委任は tree 操作です。`aur.agent.delegate` は普通に見える Tool で、engine が解釈して child を生成し、child の完了後は tool 結果で parent を再開します。
- engine が完全な hot path を管理し、具体的な model・tool・memory の実装は contracts Port から注入されます。node が model gateway や platform client を直接呼び出してはいけません。
- 構造設定は引き続き TOML を使い、キーは環境変数だけから読み取ります。
- 共有ログは `src.utils.logging.get_logger()` 経由で取得し、完全な prompt、モデル応答、機密 payload は記録しません。

より完全なメンテナー境界は、リポジトリルートの `AGENTS.md` を参照してください。

## AIGC

AuroraBot は AI を活用した開発を歓迎しますが、生成された内容も同じプロジェクトの境界に従う必要があり、「AI が書いた」という理由での免除はありません：

- **検証可能であること**：AI が生成または大幅に変更したコードは、`aurora check` のすべてのチェックを通過し、オフラインで決定論的で再現可能なテストを伴うこと；
- **理解して責任を持つこと**：生成されたコードを 1 行ずつ読み、その挙動を説明でき、正しさと安全性の責任を負うこと；
- **境界を守ること**：既存の依存方向と contract を維持し、平行な実行モデルや閉じたループを迂回する旁路を導入しないこと；
- **品質をごまかさないこと**：lint ignore で生成コードの複雑さを隠さないこと。原則として単一ファイルは 600 行を超えないこと；
- **基盤を置き換えないこと**：panel サブモジュールの `packages/@core` などの基盤コードは、AI による一括置換を受け付けません；
- **テキストの権威は中国語**：ユーザー向けテキストは簡体中文が権威版で、「実験、refactor、旧版、migration」などの歴史的な物語や、能力・API・サンプルデータの捏造を書かないこと；
- **出所と安全**：出所不明やライセンス非互換のコードを導入せず、キー、実際のセッション、プライベートデータを生成・コミットしないこと；
- **正直に開示すること**：Pull Request の説明に、AI が生成または支援した部分を明記し、レビューをしやすくすること。

違反の結果：

- 上記に違反した PR は差し戻され、該当部分の修正または書き直しが求められます；
- `aurora check` を実行せず理由も説明されていない PR はマージされません；
- 繰り返しまたは重大な違反（キーの漏洩、テスト結果の偽造、セキュリティやアーキテクチャ境界の迂回など）は、PR のクローズ、メンテナーによる記録、その後の貢献制限につながります。

## 変更の提出

1. `dev` から短命のブランチを作成します。`feat/`、`fix/`、`refact/` のプレフィックスを推奨します。
2. 各 Pull Request を、レビュー可能な 1 つの目標に集中させ、対応するテストとドキュメントを添えます。
3. マージ先を `dev` に設定し、ユーザーに見える変化や挙動の変化、検証コマンド、既知の境界、関連 RFC/Issue を説明します。
4. CI とレビューが通るまで待ち、完了したブランチを削除します。

## 検証

提出前に統一チェックを実行します：

```powershell
aurora check
```

範囲を絞りたい場合は、個別に実行できます：

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

テストはオフラインで、決定論的で、再現可能でなければなりません。モデル、時計、MCP は fake を使い、実際の使用量を消費せず、公衆ネットワークに依存しません。バグ修正は元の失敗パスをカバーし、event と effect のテストはトランザクション境界、冪等性、因果関係の親子関係も検証してください。

## 提出前のセルフチェック

- 利用者がドキュメントやテストから変更による挙動の違いを理解できる。
- 新しい挙動がモデルの判断、Tool 実行、world commit の閉じたループを迂回していない。
- 設定、README、module ドキュメント、テスト、RFC が互いに矛盾していない。
- ログとテストフィクスチャに実際のキー、セッション、プライベートデータが含まれていない。
- `aurora check` が通っているか、Pull Request で実行できなかった部分が明確に説明されている。

コントリビューションを行うことで、プロジェクトの[行動規範](CODE_OF_CONDUCT.md)に同意したことになります。
