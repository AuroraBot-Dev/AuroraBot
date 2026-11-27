# 开发与验证

核对基线：W08（2026-11-27）。首次使用走[安装助手](../examples/START.md)，本页供维护者使用。

## 环境与检查

Python 使用 uv workspace，版本以各包 pyproject.toml 为准。Node / pnpm 以根 package.json 为准；pnpm 会按声明准备项目 Node 运行时，通过 pnpm exec 使用，系统全局 Node 不随之修改。

```powershell
uv sync --locked --all-packages
pnpm install --frozen-lockfile
uv run --locked aurora check
uv run --locked aurora check --full
```

默认检查包含格式、lint、Python / TypeScript 类型与快速边界测试；--test 跳过静态检查，--full 运行全部保留的包内单测、契约、前端、原生终端和集成测试；--coverage 也使用完整测试范围。

在依赖已安装的开发环境中，日常检查目标不超过 15 秒，完整检查目标不超过 60 秒，按整个 `uv run --locked aurora check` 命令的墙钟时间验收。只读检查并行执行，按任务集中输出日志；--fix 顺序执行，避免格式修复与其他检查竞争文件。完整档与覆盖率档的 Python 测试使用 pytest-xdist 的 4 个 worker 和 worksteal 调度，快速档及直接调用 pytest 仍为单进程。

按影响范围先验证。涉及生命周期、跨包契约或配置行为时再完成完整检查。纯文档只需检查链接、内容与差异。普通回归使用假模型或本机模拟传输，不调用真实供应商。

```powershell
pnpm exec uv run --locked pytest tests/e2e/test_onboarding.py tests/e2e/test_package_boundaries.py -q
uv build tooling/aurora_meta_build --wheel --out-dir build/meta
uv build --all-packages --wheel --find-links build/meta --out-dir build/wheels
```

依赖或分发内容变化时，在干净环境安装 wheel，确认 control 无需 agent / 模型，agent 无需 bot / CLI / API；工作区导入不能替代验收。

## 测试与夹具

包内 unit / contract 位于 packages 下；跨包契约在 tests/contract，真实进程及跨包集成在 tests/e2e。tests/fixtures/runtime_apps 保留五组离线回归应用，供持久化、取消、包边界与常驻宿主测试使用，不再承担用户教学入口。

用户示例仅为 examples/onboarding。它提供完整装配文件，复用通用宿主、模型工具执行和现有界面，不复制 ReAct 调度。初始化不启动模型或 MCP；普通验收通过假模型与本机 stdio 覆盖配置、工具回填和历史恢复。固定版本 terminal MCP 可单独检查目录与工具调用，不需真实模型。

测试优先验证可观察结果、数据隔离、资源释放和故障恢复；跨层验收选择能覆盖不同路径的代表组合，协议与校验细节集中在所属包，避免在每个宿主重复参数笛卡尔积。不要通过删除有效断言或放宽容错掩盖失败；运行夹具需要的配置资源随夹具一起保留。涉及原生终端的针对性 pytest 命令也通过 pnpm exec 使用工作区 Node。

## 清单生成与静态目录

每个插件的公开身份和组件角色以 `plugin.meta.toml` 为源，发行信息与入口工厂以 pyproject.toml 为源。修改后生成并检查一致性：

```powershell
uv run --locked aurora-meta generate
uv run --locked aurora-meta generate --check
uv run --locked aurora-meta catalog aurora-agent
```

生成器更新清单相邻的 `_meta.py` 和发行根目录 `plugin.meta.json`，不要手改生成物。契约使用纯导出或包内文件；构建工具不安装业务运行依赖。按项目格式工具处理生成物后，再执行检查。

catalog 读取已安装发行包的静态目录，不导入插件或创建资源；无需模型供应商 SDK。源码目录汇总在[公共 ID 目录](aurorabot-id-catalog-v0.2.3.md)，组件角色、端口及契约的权威来源仍是清单和契约文件。

## 查询运行定义

当前 CLI 的 `id list` 登记所选插件并列出定义，不执行 prepare/start，不启动客户端或后台任务：

```powershell
uv run --locked aurora --data-dir build/onboarding id list
```

上面的目录应已由助手 --init 初始化。这条命令需要所选插件的运行依赖；它与只读发行数据的 catalog 不同。MCP 动态工具只会在准备连接和读取目录后出现。独立的 CLI 插件目录、装配计划与实际图命令仍属 W09 待办，当前不要使用规划中的命令名。公开接口以契约文件和测试为准，不照搬历史设计中的拟议 schema。

## 文档与提交

当前入口集中在 [INDEX.md](INDEX.md)，START.md 保持为首次启动短指南。文档描述职责、公共约定和使用行为；实现步骤、私有方法与算法细节留在代码及测试。公开接口、配置或行为变化时同步主题文档，内部重构不要求重写使用指南。配置、操作、上下文与架构分别维护，旧计划和讨论保留归档标记；变更与验收统一写入 CHAGELOG.md。

按项目 AGENTS.md 使用中文注释、docstring 与提交说明，小步提交，在功能分支验证后通过 PR 合并。README.md 和 AGENTS.md 的修改遵守用户确认规则；不改写用户数据来适配示例或测试。

## CI 与发布

GitHub 的 `CI` 工作流对 `main` 的 push 和 PR 执行 Python 3.12 / 3.13 完整检查，使用 `.node-version`、`packageManager` 与锁文件安装环境。Python 3.12 作业额外构建全部 wheel 和 Panel，并保存 Actions 产物。原生 TUI 验收包含在 `aurora check --full` 中。`apps/docsite` 与 `apps/landing` 目前仅有工作区包声明，不提供构建或部署入口；当前文档以仓库 `docs` 为准。

维护者发布时先在单独的版本 PR 中同步工作区包版本，然后为已合入 `main` 的提交创建尚未使用的 `vX.Y.Z` 或 `vX.Y.Z-alpha/beta/rc.N` 标签。在 Actions 中从 `main` 手动运行 `Release` 并填写该标签。流程验证标签存在、主线归属及全部 Python 包版本，复用 CI 验证标签指向的确定提交，通过后创建附带 wheel 的 GitHub Release；不上传 PyPI，不自动创建或移动标签，不覆盖现有 Release。

历史标签和 Release 保持原样。当前包版本为 `0.1.0`，不表示要覆盖旧版本的同名标签；后续正式版本号由维护者单独决定。`archive/pre-next` 保存历史接入前的旧主线，`archive/next/*` 原样保存 AuroraBot-next 的各分支引用，未合并分支的保留不表示其功能被并入 `main`。历史接入 PR 必须选择 merge commit，不能 squash 或 rebase。
