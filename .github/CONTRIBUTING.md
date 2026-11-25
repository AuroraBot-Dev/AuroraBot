# 参与 AuroraBot

[English](CONTRIBUTING.en.md) · [日本語](CONTRIBUTING.ja.md)

欢迎通过文档、缺陷修复、工具接入、界面和运行时改进参与项目。较大的公共契约或架构调整请先在 Issue 或 Discussion 中说明使用场景、不变量和验证方法。参与者须遵守[行为准则](CODE_OF_CONDUCT.md)。

## 开发环境

安装 Python 3.12+、uv，以及根 [package.json](../package.json) 和 [.node-version](../.node-version) 声明的 pnpm、Node.js：

```bash
git clone https://github.com/AuroraBot-Dev/AuroraBot.git
cd AuroraBot
uv sync --locked --all-packages
pnpm install --frozen-lockfile
pnpm exec uv run --locked aurora check
```

首次运行 Bot 请按[安装助手指南](../examples/START.md)操作。检查与测试不需要模型密钥，使用假模型或模拟传输；不要自行调用真实供应商。凭证只来自环境变量或本地 `.env`，不能进入 TOML、ctx、快照或日志。

## 代码与包边界

完整约束见 [AGENTS.md](../AGENTS.md) 和[开发指南](../docs/development.md)。

- 注释、docstring、提交说明以中文为主，直接描述当前职责、行为和约束。
- 执行依赖方向为 `bot → agent → control → core`，模型与 MCP 由 `aurora_adapter` 接入，配置由 `aurora_config` 声明。
- core 提供机制，不承担模型或业务控制；CLI、API 和界面复用后端执行语义。
- 公共 ID 使用 `<namespace>:<domain>/<local_path>`，按所属包归属；接口调整须同步配置、消费者、测试与文档。
- TOML 是配置持久来源，运行期覆盖不自动写回；恢复快照不代表自动续跑，不重放未完成的工具动作。
- 包内测试放在 `packages/<包>/tests/unit` 或 `tests/contract`，跨包测试放在根目录 `tests/contract` 和 `tests/e2e`。

## 验证与提交

1. 从最新 `main` 建立短生命周期分支，新功能使用 `feat/<功能名>`。
2. 开始前检查工作区和暂存区；小步提交，只包含本任务相关改动。
3. 先做针对性验证；涉及跨包契约、生命周期或配置行为时运行完整检查。
4. 变更说明、验证结果和新增测试的独有价值统一写入 [docs/CHAGELOG.md](../docs/CHAGELOG.md)。
5. 向 `main` 提交 PR，说明行为变化、验证结果和相关 Issue，等待 CI 和评审。不要直接向 `main` 提交功能。

```bash
pnpm exec uv run --locked aurora check
pnpm exec uv run --locked aurora check --full
uv build --all-packages --wheel --out-dir build/wheels
pnpm --filter @aurorabot/panel build
```

日常检查覆盖格式、lint、类型与快速边界测试；`--full` 增加完整 Python、前端、原生终端和集成测试；`--coverage` 同样使用完整测试范围。CI 在 Python 3.12 / 3.13 上执行完整检查，构建全部 wheel 和 Panel。

优先扩展能覆盖真实缺陷的既有用例，不堆叠重复测试，不通过删断言、放宽容错或跳过检查掩盖失败。扩大测试范围后，在依赖已安装的同一环境测量整个命令墙钟时间：日常目标 15 秒以内，完整目标 60 秒以内。纯文档修改检查链接与差异。分发或依赖变化还需在干净环境验证 wheel 安装边界。

README.md、AGENTS.md 的修改遵守项目的用户确认规则。技术文档以简体中文为准，社区入口同步更新英文和日文。

## AI 辅助贡献

欢迎使用 AI 辅助开发。提交者必须理解生成内容、解释其行为并对正确性负责，在 PR 中披露 AI 辅助范围；同样遵守包边界、来源与许可证要求，并如实报告实际运行的验证。不能以生成内容为由绕过检查或虚构测试结果。评审可要求修正不符合约束的贡献，严重或重复违规按社区规则处理。

提交前移除密钥、真实对话、完整模型回复、上传文件和私人运行数据。普通回归不消耗模型额度。
