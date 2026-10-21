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
- **运行时开发者**：改进认知执行、委派、engine、模型网关、MCP 适配或本地交互体验。
- **设计参与者**：通过 Issue 或 Discussion 讨论用例、公共契约与模块边界。

如果还不确定从哪里开始，可以先在 Discussion 或 Issue 中描述你希望改善的使用体验。

## 准备开发环境

### 1. 克隆仓库

需要 Python 3.12、Git、[uv](https://docs.astral.sh/uv/)、[Node.js](https://nodejs.org/) 24 与 [pnpm](https://pnpm.io/) 12。

```bash
git clone https://github.com/AuroraBot-Dev/AuroraBot.git
cd AuroraBot
./scripts/linux/setup.sh
# macOS: ./scripts/macos/setup.command;
# Windows: .\scripts\windows\setup.ps1.
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

## 设计与实现

包职责和依赖方向见[系统总览](../architecture/system-overview)，认知与行动边界见[认知与恢复](../architecture/runtime-core)，开发约束见仓库根目录 `AGENTS.md`。

涉及公共契约、持久化或模块边界时，先明确 Bot 用例、不变量和验证方法，并同步更新对应文档。较大设计通过 Issue 或 Discussion 讨论。

## AIGC

AI 辅助生成的内容遵循相同的代码、文档和验证要求。提交者应理解其行为、核对来源与许可证、对结果负责，并在 Pull Request 中说明 AI 参与的范围。不得虚构能力、接口或验证结果。

## 提交你的改进

1. 从 `dev` 创建短生命周期分支，推荐 `feat/`、`fix/` 或 `refact/` 前缀。
2. 让每个 Pull Request 聚焦一个可审查目标，并补充对应测试和文档。
3. 合并目标设为 `dev`，说明行为变化、验证结果和相关 Issue；变更记录写入 `docs/CHANGELOG.md`。
4. 等待 CI 与评审通过后合并，并删除已经完成的分支。

## 验证

Python 开发依赖与检查：

```bash
uv sync --locked --group dev
uv run aurora check --fix
```

按改动范围验证时，可运行具体测试，例如 `uv run pytest tests/runtime/test_bot_lifecycle.py -q`。前端使用 `pnpm check apps`，文档使用 `pnpm build docsite`。

测试必须离线、确定且可重复；外部 LLM、工具和 MCP 使用 fake。测试组织与验收重点见[质量与验收](../architecture/acceptance)。

提交贡献即表示你同意遵守项目的[社区行为准则](/reference/CODE_OF_CONDUCT)。
