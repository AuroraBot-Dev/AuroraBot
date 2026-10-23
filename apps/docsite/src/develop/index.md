---
order: 3
---

# 开发

欢迎参与 AuroraBot 的代码、应用与文档开发。

## 找到适合你的入口

- **文档贡献者**：按[文档规范](./docs-contribution)修正说明与示例。
- **前端开发者**：开发落地页、文档主题或工程脚本，见[开发应用](./app-development)。
- **应用开发者**：接入 MCP 能力，或按[模组开发](./core-development)贡献领域操作。
- **通用模块开发者**：通过 [Namespace 与 hook](./namespace-modules) 注册调用点并使用共享 ctx。
- **CLI 扩展开发者**：通过 [CLI 命令与配置插件](./cli-plugins) 贡献命令、配置解析与默认资源。
- **运行时开发者**：改进 Bot 的运行行为与交互体验，开发约束见仓库根目录 `AGENTS.md`。
- **任务执行宿主开发者**：通过[独立 Agent 任务](./agent-runtime)接入模型与工具，控制执行和追加输入。
- **设计参与者**：通过 Issue 或 Discussion 讨论用例、公共契约与模块边界。

如果还不确定从哪里开始，可以先在 Discussion 或 Issue 中描述你希望改善的使用体验。

## 准备开发环境

### 1. 克隆仓库

需要 Python 3.12、Git、[uv](https://docs.astral.sh/uv/)、[Node.js](https://nodejs.org/) 24 与 [pnpm](https://pnpm.io/) 12。

```bash
git clone https://github.com/AuroraBot-Dev/AuroraBot.git
cd AuroraBot
node scripts/setup.ts
```

安装脚本准备依赖、个人配置和应用工作区。

### 2. 填写必要配置

在 `.env` 中填入默认模型所需密钥（如 `DEEPSEEK_API_KEY`）。

### 3. 从终端启动

```bash
aurora start
```

启动后直接输入消息即可对话；输入 `/help` 查看操作，输入 `/exit` 停止。

仅运行测试和静态检查不需要真实模型密钥。密钥只写入本地 `.env` 或进程环境；不要提交密钥、真实对话、完整模型回复、工作区事件、上传文件或运行日志。

## 贡献范围

产品概念见[系统总览](../architecture/system-overview)，重启与行动结果见[认知与恢复](../architecture/runtime-core)。代码组织与实现约束在仓库中维护。

先明确希望改善的使用体验和验证方法。影响安装、配置、交互或公开扩展用法时，同步更新相关文档；内部重构不要求同步改写文档站。较大设计通过 Issue 或 Discussion 讨论。

## AIGC

AI 辅助生成的内容遵循相同的代码、文档和验证要求。提交者应理解其行为、核对来源与许可证、对结果负责，并在 Pull Request 中说明 AI 参与的范围。不得虚构能力、接口或验证结果。

## 提交你的改进

1. 从 `dev` 创建短生命周期分支，推荐 `feat/`、`fix/` 或 `refact/` 前缀。
2. 让每个 Pull Request 聚焦一个可审查目标，按影响范围补充验证，并更新受影响的使用说明。
3. 合并目标设为 `dev`，说明行为变化、验证结果和相关 Issue；变更记录写入 `docs/CHANGELOG.md`。
4. 等待 CI 与评审通过后合并，并删除已经完成的分支。

## 验证

Python 开发依赖与检查：

```bash
uv sync --locked --group dev
uv run aurora check --fix
```

前端使用 `pnpm check apps`，文档使用 `pnpm build docsite`。

测试必须离线、确定且可重复；外部模型与服务使用替身。检查说明见[验证改动](../architecture/acceptance)。

提交贡献即表示你同意遵守项目的[社区行为准则](/reference/CODE_OF_CONDUCT)。
