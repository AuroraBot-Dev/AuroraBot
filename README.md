# AuroraBot

[English](README.en.md) · [日本語](README.ja.md)

AuroraBot 是面向持续运行 Bot 的智能体框架，提供 ReAct 推理、模型与 MCP 工具接入、持久状态、环境观察，以及终端和 Web 交互界面。

执行结构为 `bot → agent → control → core`。配置由 `aurora_config` 声明和加载，模型与 MCP 协议由 `aurora_adapter` 适配；CLI、HTTP / WebSocket API、TUI 和 Panel 共享后端执行语义。

## 开始使用

准备 Python 3.12+、[uv](https://docs.astral.sh/uv/) 和 Git：

```bash
git clone https://github.com/AuroraBot-Dev/AuroraBot.git
cd AuroraBot
uv sync --locked --all-packages
uv run --locked python examples/onboarding/main.py --init
```

随后按[首次启动指南](examples/START.md)填写模型配置与环境变量，再启动安装配置助手。助手使用独立数据目录，真实对话会调用你配置的模型供应商；初始化与普通测试不调用真实模型。

TUI、Panel 和前端开发需要 Node.js 与 pnpm，版本以 [package.json](package.json) 和 [.node-version](.node-version) 为准。

## 文档与开发

- [文档索引](docs/INDEX.md)：配置、操作、上下文和架构。
- [操作指南](docs/operations.md)：正式 Bot、TUI、Panel 与 API 的启动和连接。
- [开发与验证](docs/development.md)：工作区、测试范围与分发验证。
- [贡献指南](.github/CONTRIBUTING.md)与[行为准则](.github/CODE_OF_CONDUCT.md)。
- [变更与验收记录](docs/CHAGELOG.md)。

```bash
pnpm install --frozen-lockfile
pnpm exec uv run --locked aurora check
pnpm exec uv run --locked aurora check --full
```

## 社区

通过 [Issues](https://github.com/AuroraBot-Dev/AuroraBot/issues)反馈缺陷和功能建议，通过 [Discussions](https://github.com/AuroraBot-Dev/AuroraBot/discussions)交流使用与设计，也可[支持项目](https://ifdian.net/a/aurorabot)。提交日志前请移除凭证、真实对话和私人数据。

项目采用 [Apache License 2.0](LICENSE)。
