# 参与 AuroraBot

<b>中文</b> | <a href="CONTRIBUTING.en.md">English</a> | <a href="CONTRIBUTING.ja.md">日本語</a>

AuroraBot 想做的不是一个工具一般的 Agent，而是一个能够持续存在、形成自己的节律、在自己世界里自主判断和行动的 Bot。
我们探索的不只是"如何接入一个模型"，而是她如何持续工作、可靠行动，并让人理解她为什么这样做。
无论你带来一个缺陷修复、一段更自然的介绍、一个 MCP 应用，还是一项运行时改进，都欢迎参与。

## 找到适合你的入口

- **第一次贡献**：修正文档、补充测试，或选择边界清晰的小问题。
- **应用开发者**：从内建 Clock 应用出发，为 AuroraBot 接入新的 MCP 能力。
- **运行时开发者**：改进 AgentTree、engine、模型网关、MCP 适配或本地交互体验。
- **设计参与者**：对公共契约和模块边界提出 RFC，并通过可执行验收标准推动讨论。

如果还不确定从哪里开始，可以先在 Discussion 或 Issue 中描述你希望改善的使用体验。

## 准备开发环境

### 1. 克隆本仓库

需要 Python 3.12（推荐，以上版本未经充分验证）、Git 和 [uv](https://docs.astral.sh/uv/)。
文档站、落地页和工程脚本需要 [Node.js](https://nodejs.org/) 24 与 [pnpm](https://pnpm.io/) 12。

```bash
git clone https://github.com/AuroraBot-Dev/AuroraBot.git
cd AuroraBot
./scripts/linux/setup.sh
# macOS: ./scripts/macos/setup.command;
# Windows: .\scripts\windows\setup.ps1.
```

`setup.sh` 会检查 git/uv/pnpm，询问是否将 aurora 全局链接到用户工具目录，然后由 `aurora setup` 完成依赖同步、个人配置以及 应用工作区依赖安装。

### 2. 填写必要配置

在 `.env` 中填入默认模型所需密钥（如 `DEEPSEEK_API_KEY`）

### 3. 从终端启动

```bash
aurora start
```

启动后直接输入消息即可对话；输入 `/help` 查看操作，输入 `/exit` 停止。

仅运行测试和静态检查不需要真实模型密钥。密钥只写入本地 `.env` 或进程环境；不要提交密钥、真实对话、完整模型回复、工作区事件、上传文件或运行日志。

## 在改动之前

AuroraBot 用 RFC 记录会长期影响项目的设计决策。以下改动应先更新或新增 `apps/docsite/src/rfc/` 中的 RFC：

- 模块职责或依赖方向；
- AgentTree、委派与工具回执契约；
- TOML 配置、扩展协议或模型调用契约；
- 会改变平台组合、进程入口或持久化语义的行为。

小型缺陷修复、测试补充、文案改进和不改变公共语义的重构可以直接提交。公开说明发生变化时，请同步更新中文、英文和日文入口。

当前运行时、包边界和进程组合以设计思想 [RFC 0300](../apps/docsite/src/rfc/0300-design-philosophy.md) 为最高约束，现行实现结构见 [架构说明](../apps/docsite/src/architecture/)。

## 保持闭环完整

贡献代码时，请守住几条能让 AuroraBot 可靠工作的边界：

- 模型决定、运行时执行：assistant 只能回复或请求工具，真实外部效果只由 Tool 契约执行，普通模型文本不是效果；
- 委派就是树操作：`aurora:tool/delegate` 是普通可见 Tool，由 engine 解释并创建 child，child 完成后以 tool
  结果恢复 parent；
- engine 管理完整热路径，具体模型、工具与记忆实现通过 contracts Port 注入，节点不直接调用模型网关或平台客户端；
- 结构配置继续使用 TOML，密钥继续只来自环境变量；
- 共享日志通过 `aurora_bot.utils.logging.get_logger()` 获取，不记录完整提示词、模型回复或敏感载荷。

更完整的维护者边界见仓库根目录 `AGENTS.md`。

## AIGC

AuroraBot 欢迎使用 AI 辅助开发，但生成的内容同样受项目边界约束，不能因为是"AI 写的"而获得豁免：

- **必须可验证**：AI 生成或大幅修改的代码必须通过 `aurora check` 全部检查，并配套离线、确定、可重复的测试；
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

1. 从 `dev` 创建短生命周期分支，推荐 `feat/`、`fix/` 或 `refact/` 前缀。
2. 让每个 Pull Request 聚焦一个可审查目标，并补充对应测试和文档。
3. 合并目标设为 `dev`，说明使用体验或行为变化、验证命令、已知边界和相关 RFC/Issue。
4. 等待 CI 与评审通过后合并，并删除已经完成的分支。

## 验证

提交前运行统一检查：

```powershell
aurora check
```

需要缩小范围时，可以分别运行：

```powershell
uv run pytest
uv run pytest tests/runtime/test_bot_lifecycle.py -q
uv run aurora check --test --coverage
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

先运行 `uv sync --locked --group dev` 安装开发依赖。pytest 使用 importlib 模式，
测试按能力分目录，工具通过 `tests.*` 显式导入；专用辅助代码放在对应目录，跨能力 fake 放在 `tests/support/`。
日常检查不采集覆盖率；CI 使用 20% 总体下限。门槛不作为删减目标，也不要求为简单代码补测试。
优先验证认知循环、持久化一致性、幂等与失败恢复、权限和路径边界、凭据脱敏、记忆时间正确性。
避免重复用例、对测试辅助函数自身的测试，以及只为覆盖行数添加的断言。

测试必须离线、确定且可重复。模型、时钟和 MCP 使用 fake，不消耗真实额度或依赖公网服务。缺陷修复应覆盖原始失败路径；
事件与效果测试还应验证事务边界、幂等性和因果父子关系。

## 提交前自查

- 使用者能从文档或测试看懂改动带来的行为差异。
- 新行为没有绕过模型决定、Tool 执行与世界提交的闭环。
- 配置、README、模块文档、测试和 RFC 没有互相矛盾。
- 日志和测试夹具不包含真实密钥、会话或私人数据。
- `aurora check` 已通过，或 Pull Request 清楚解释了未运行的部分。

提交贡献即表示你同意遵守项目的[社区行为准则](CODE_OF_CONDUCT.md)。

## Vue 应用与工程脚本

根目录的 `pyproject.toml` 与 `package.json` 分别管理 Python 与 Node.js 工程；前端只使用根目录的 `pnpm-workspace.yaml` 和 `pnpm-lock.yaml`。

```bash
pnpm install --frozen-lockfile
pnpm dev docsite                 # VitePress 文档站
pnpm dev landing                 # Vue 落地页
pnpm typecheck all               # 工程脚本和应用的类型检查
pnpm test all                    # 前端单元测试
pnpm build all                   # 构建两个应用
pnpm check python                # Python 完整质量检查
pnpm clean artifacts             # 清理应用构建产物
pnpm clean deps                  # 同时清理 Node.js 依赖
```

根目录 `pnpm task` 提供交互式任务菜单；也可省略具体任务的目标，例如 `pnpm dev`，通过方向键选择。自动化使用明确目标，命令与选项见[开发应用](../apps/docsite/src/develop/app-development.md)。

新增 TypeScript 工程脚本放在 `scripts/*.ts`，通过 `pnpm exec tsx scripts/<name>.ts` 或根 `package.json` 的脚本运行。三平台安装脚本仍在各自平台目录。

`aurora setup --docs` 在根目录统一安装应用工作区依赖。

## TypeScript 配置与应用结构

应用源码位于 `src/`，构建产物位于 `dist/`；需要原样复制的静态文件放在 `public/`，没有这类文件时无需保留空目录。落地页的图标与字体位于 `src/assets/`，样式和文案分别位于 `src/styles/`、`src/locales/`。构建、TypeScript 与检查配置包位于根 `tooling/`。文档站正文位于 `apps/docsite/src/`，VitePress 配置与主题位于 `.vitepress/`。

- 根 `tsconfig.json` 检查工程脚本及公共工具配置。
- 应用 `tsconfig.json` 检查浏览器源码或文档主题。
- 应用 `tsconfig.node.json` 检查 Vite / VitePress 配置。
- `tooling/tsconfig/` 提供公共基线、浏览器与 Node.js 配置；`pnpm typecheck all` 从根目录运行完整应用检查。

应用目录由主仓直接管理，克隆仓库后运行 `pnpm install --frozen-lockfile` 即可。`pnpm lint all` 和 `pnpm format all` 使用根目录的检查与格式配置，`pnpm test all` 只发现应用和工程工具中的测试。
