# 首次启动：安装配置助手

仓库只提供这一个用户示例：真实模型驱动的 ReAct Bot，配备 7 个 terminal MCP 工具，帮助你检查环境、配置并启动 Aurora。助手使用独立的 `build/onboarding`，不自动启用 QQ、世界输入或决策模型。

## 1. 安装并生成配置

准备 Python 3.12+ 和 uv，在仓库根目录执行：

```powershell
uv sync --locked --all-packages
uv run --locked python examples/onboarding/main.py --init
```

初始化只补齐缺失文件，不调用模型或启动终端。助手启动时由 `uvx` 安装并运行固定版本 `terminal-mcp==0.4.7`，首次需要联网下载。

## 2. 填写模型

编辑 `build/onboarding/config/org.aurora.adapter/model/profiles.toml`，填写你的 `provider`、`model`，需要时添加 `base_url`。模板以 DeepSeek 为例，模型须支持工具调用和流式输出。

在项目根目录 `.env` 中填写 `AURORA_MODEL_API_KEY=你的密钥`；也可设置同名环境变量。`credential` 填环境变量名，不填密钥。

## 3. 开始使用

无需界面即可提交一条消息，完成后退出；再次运行会恢复历史：

```powershell
uv run --locked python examples/onboarding/main.py --text "请检查我的环境，告诉我首次启动 Aurora 还缺什么。"
```

输出为运行回执和模型增量 JSON。需要连续对话时，先启动助手后端：

```powershell
uv run --locked python examples/onboarding/main.py
```

另开终端启动 TUI：

```powershell
pnpm install --frozen-lockfile
pnpm --filter @aurorabot/tui start --connect http://127.0.0.1:10271 --instance onboarding
```

向它说明目标，例如：“帮我配置正式 Bot，先使用终端工具，配置前核对已有文件。”TUI 退出不关闭后端；后端按 Ctrl+C 收尾。终端会话只在本次后端运行期间有效，正式 Bot 的常驻启动应放在另一个终端。

`--data-dir` 可选择另一份助手数据，`--env-file` 可指定环境文件。默认 API 仅供本机非浏览器客户端访问；Panel 连接和访问令牌见[操作指南](../docs/operations.md#连接安装助手)。不要让两个宿主共用同一数据目录。

更多内容：[文档索引](../docs/INDEX.md) · [配置与 MCP](../docs/configuration.md) · [开发与验证](../docs/development.md)
