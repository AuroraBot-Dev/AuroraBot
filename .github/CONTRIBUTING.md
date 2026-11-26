# 参与 AuroraBot

<b>中文</b> | <a href="CONTRIBUTING.en.md">English</a> | <a href="CONTRIBUTING.ja.md">日本語</a>

AuroraBot 想做的不是一个工具一般的 Agent，而是一个能够持续存在、形成自己的节律、在自己世界里自主判断和行动的 Bot。
我们探索的不只是"如何接入一个模型"，而是她如何持续工作、可靠行动，并让人理解她为什么这样做。
无论你带来一个缺陷修复、一段更自然的介绍、一个 MCP 应用，还是一项运行时改进，都欢迎参与。

## 找到适合你的入口

- **第一次贡献**：修正文档、补充测试，或选择边界清晰的小问题。
- **应用开发者**：通过 MCP 服务或插件为 Bot 提供能力。
- **运行时开发者**：改进 ReAct 执行、模型适配、MCP 接入或本地交互体验。
- **设计参与者**：通过 Issue 或 Discussion 讨论用例、公共契约与模块边界。

如果还不确定从哪里开始，可以先在 Discussion 或 Issue 中描述你希望改善的使用体验。

## 准备开发环境

### 1. 克隆本仓库

需要 Python 3.12+、Git 和 [uv](https://docs.astral.sh/uv/)，CI 验证 Python 3.12 / 3.13。
TUI、Panel 和工程脚本需要 [Node.js](https://nodejs.org/) 与 [pnpm](https://pnpm.io/)，版本以根 [package.json](../package.json) 和 [.node-version](../.node-version) 为准。开发检查前运行 `pnpm install --frozen-lockfile`。

```bash
git clone https://github.com/AuroraBot-Dev/AuroraBot.git
cd AuroraBot
uv sync --locked --all-packages
uv run --locked python examples/onboarding/main.py --init
```

初始化会在独立的 `build/onboarding` 中补齐安装配置助手所需文件，不调用模型或启动工具。

### 2. 填写必要配置

在 `build/onboarding/config/org.aurora.adapter/model/profiles.toml` 中填写模型的 `provider`、`model` 和必要的 `base_url`；在根目录 `.env` 中设置 `AURORA_MODEL_API_KEY`，`credential` 只填环境变量名。

### 3. 从终端启动

```bash
uv run --locked python examples/onboarding/main.py --text "请检查我的环境，告诉我首次启动 Aurora 还缺什么。"
```

助手处理这条消息后退出，真实对话会调用你配置的模型。连续对话、TUI 和 Panel 的连接方法见[首次启动指南](../examples/START.md)，正式 Bot 的启动见[操作指南](../docs/operations.md)。

仅运行测试和静态检查不需要真实模型密钥。密钥只写入本地 `.env` 或进程环境；不要提交密钥、真实对话、完整模型回复、工作区事件、上传文件或运行日志。

## 在改动之前

涉及公共契约、持久化或模块边界时，先明确 Bot 用例、不变量和验证方法。开发约束见 [AGENTS.md](../AGENTS.md)，组件职责见[系统总览](../docs/aurorabot-design-v0.2.3.md)。较大设计通过 Issue 或 Discussion 讨论。

文档直接说明当前用法、能力和限制，变更经过写入 [docs/CHAGELOG.md](../docs/CHAGELOG.md)。公开说明以简体中文为准，并同步更新对应翻译。

## 保持闭环完整

贡献代码时，请守住几条能让 AuroraBot 可靠工作的边界：

- 模型决定、运行时执行：assistant 只能回复或请求工具，真实外部效果只由 Tool 契约执行，普通模型文本不是效果；
- 每个 agent 实例由一个 AgentRuntime 调度，用户交流、cadence 与计划唤醒向同一所有者提交引导；
- 执行依赖方向为 `bot → agent → control → core`，模型与 MCP 由 `aurora_adapter` 接入，配置由 `aurora_config` 声明；CLI、API 和界面复用后端执行语义；
- 结构配置使用 TOML，密钥只来自环境变量；
- 日志由 `aurora_logging` 统一配置，通过 `logging.getLogger(__name__)` 获取，不记录完整提示词、模型回复或敏感载荷。

更完整的维护者边界见仓库根目录 `AGENTS.md`。

## AIGC

AuroraBot 欢迎使用 AI 辅助开发，但生成的内容同样受项目边界约束，不能因为是"AI 写的"而获得豁免：

- **必须可验证**：AI 生成或大幅修改的代码必须通过 `aurora check --full` 全部检查，并配套离线、确定、可重复的测试；
- **必须理解并负责**：提交者必须逐行理解生成代码，能解释其行为，并对其正确性与安全性负责；
- **必须守边界**：生成代码保持既有依赖方向与契约，不引入平行运行模型或绕过闭环的旁路；
- **不得掩盖质量**：不用 lint ignore 掩盖生成代码的复杂度；单文件原则上不允许超过 600 行；
- **文本以中文为准**：生成的面向用户文案以简体中文为权威版本，不写"实验、重构、旧版、迁移"等历史阶段叙事，不虚构能力、API 或示例数据；
- **来源与安全**：不引入来源不明或许可证不兼容的代码，不生成并提交密钥、真实会话或私人数据；
- **如实披露**：在 Pull Request 描述中说明哪些内容由 AI 生成或辅助，便于评审聚焦。

违反后果：

- 评审发现违反以上约束的 PR 会被打回，要求修改或重写相关部分；
- 未运行 `aurora check` 且未说明原因的 PR 不予合入；
- 重复或严重违反（如泄漏密钥、伪造测试结果、绕过安全或架构边界）的 PR 将被关闭，维护者会保留记录，并可能限制后续贡献。

## 提交你的改进

1. 从 `main` 创建短生命周期分支，新功能使用 `feat/<功能名>`，修复或重构可使用 `fix/` 或 `refact/` 前缀。
2. 让每个 Pull Request 聚焦一个可审查目标，并补充对应测试和文档。
3. 合并目标设为 `main`，说明行为变化、验证结果和相关 Issue。
4. 等待 CI 与评审通过后合并，并删除已经完成的分支。

## 验证

提交前运行统一检查：

```powershell
pnpm exec uv run --locked aurora check
```

根据验证范围，也可以分别运行：

```powershell
pnpm exec uv run --locked pytest packages/aurora_agent/tests/unit/test_agent_runtime.py -q
pnpm exec uv run --locked aurora check --full
pnpm exec uv run --locked aurora check --test --coverage
uv run --locked ruff check .
uv run --locked ruff format --check .
pnpm typecheck
```

先运行 `uv sync --locked --all-packages` 和 `pnpm install --frozen-lockfile` 安装开发依赖。
包级测试位于 `packages/<包>/tests/unit` 和 `tests/contract`，跨包契约位于根 `tests/contract`，进程与集成测试位于 `tests/e2e`；共享夹具位于 `tests/fixtures` 和根 `conftest.py`。
日常检查运行快速边界测试，`--full` 与 `--coverage` 使用完整测试范围；CI 运行 `--full`，显式覆盖率检查使用 20% 总体下限。门槛不作为删减目标，也不要求为简单代码补测试。
优先验证认知循环、持久化一致性、幂等与失败恢复、权限和路径边界、凭据脱敏、记忆时间正确性。
避免重复用例、对测试辅助函数自身的测试，以及只为覆盖行数添加的断言。

测试必须离线、确定且可重复。模型、时钟和 MCP 使用 fake，不消耗真实额度或依赖公网服务。缺陷修复应覆盖原始失败路径；
事件与效果测试还应验证事务边界、幂等性和执行身份关联。

## 提交前自查

- 使用者能从文档或测试看懂改动带来的行为差异。
- 新行为没有绕过模型决定、Tool 执行与结果回填的闭环。
- 配置、文档与测试保持一致。
- 日志和测试夹具不包含真实密钥、会话或私人数据。
- `aurora check` 已通过，或 Pull Request 清楚解释了未运行的部分。

提交贡献即表示你同意遵守项目的[社区行为准则](CODE_OF_CONDUCT.md)。

## Vue 应用与工程脚本

根目录的 `pyproject.toml` 与 `package.json` 分别管理 Python 与 Node.js 工程；前端只使用根目录的 `pnpm-workspace.yaml` 和 `pnpm-lock.yaml`。

```bash
pnpm install --frozen-lockfile
pnpm panel                      # Panel 开发服务器
pnpm tui                        # TUI，需先启动 Bot 后端
pnpm typecheck                  # Python、工程脚本和应用的类型检查
pnpm test                       # 前端单元测试
pnpm --filter @aurorabot/panel build  # 构建 Panel
pnpm exec uv run --locked aurora check --full  # 完整质量检查
```

运行命令与连接选项见[操作指南](../docs/operations.md)，检查范围见[开发与验证](../docs/development.md)。

新增 TypeScript 工程脚本放在 `scripts/*.ts`，通过 `pnpm exec node scripts/<name>.ts` 或根 `package.json` 的脚本运行。

`pnpm install --frozen-lockfile` 在根目录统一安装应用工作区依赖。

## TypeScript 配置与应用结构

应用源码位于 `src/`，构建产物位于 `dist/`；需要原样复制的静态文件放在 `public/`，没有这类文件时无需保留空目录。Panel 与 TUI 分别位于 `apps/aurora_panel` 和 `apps/aurora_tui`，共享客户端位于 `packages/aurora_client`。构建、TypeScript 与检查配置包位于根 `tooling/`。当前文档位于 `docs/`；`apps/docsite` 和 `apps/landing` 仅保留包声明，没有构建或部署入口。

- 根 `tsconfig.json` 检查工程脚本及公共工具配置。
- 应用 `tsconfig.json` 检查各自源码和工程配置。
- `tooling/tsconfig/` 提供公共基线、浏览器与 Node.js 配置；`pnpm typecheck` 从根目录运行完整应用检查。

应用目录由主仓直接管理，克隆仓库后运行 `pnpm install --frozen-lockfile` 即可。`pnpm lint` 和 `pnpm format` 使用根目录的检查与格式配置，`pnpm test` 收集客户端、应用和工程脚本中的前端测试；原生 TUI 验收由 `aurora check --full` 单独执行。
