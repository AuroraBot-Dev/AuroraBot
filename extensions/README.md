# 扩展 AuroraBot

`extensions/` 保存本机为 Bot 安装的 MCP 应用源码与 Python 插件。Bot 通过这些扩展感知外部环境、执行工具或获得新的能力。

| 目录 | 用途 |
| --- | --- |
| `apps/` | `aurora app install owner/repo` 克隆的源码，存放于 `<owner>/<repo>/` |
| `plugins/` | 启动时自动发现的本地 Python 模组 |

仓库只跟踪本说明和目录占位文件；本机安装的应用与插件由 Git 忽略。没有安装扩展时，这两个目录可以为空。
Agent 定义位于 `config/agents.toml`，不从 `extensions/` 加载。

## 接入 MCP 应用

MCP 应用为 Bot 提供外部工具；符合事件协议并启用相应配置的应用也可向她的世界提交事件。

1. 运行 `aurora setup` 初始化个人配置。
2. 使用 `aurora app install owner/repo` 安装源码应用，或在 `config/apps.toml` 配置已有 Server。
3. 在 `config/agents.toml` 的 `tools` 中为相应 Agent 配置工具可见范围。
4. 使用 `aurora start` 启动；不需要本地终端时使用 `aurora start --headless`。

源码安装需要仓库提供 `aurora-app.toml`，或通过 `--command` 显式指定启动命令。
包管理器安装（`--npx` / `--uvx`）和远程 HTTPS 端点登记不把 Server 源码放入 `apps/`。
完整参数与安装、移除行为见 [应用管理命令](../src/aurora_cli/commands/app/README.md)。

`config.example/apps.toml` 中的 Windows-MCP 与 Aurora-QQ 是默认禁用的配置示例，仓库不附带它们的源码。
手动启用前需要准备对应应用并核对 `working_dir`、启动命令和环境变量；通过安装命令登记的应用使用实际安装路径。

启动时，AuroraBot 发现并冻结 Server 的工具目录，将远端工具映射为 `<package>:tool/definition/<别名>`。
例如 `org.aurora.qq:tool/definition/*` 表示该应用的工具可见范围；也可使用精确工具 ID、`#` 标签引用和 `!` 排除规则。
工具参数按 JSON Schema 校验，外部行动经 Tool 执行，结果作为世界事件回到 Bot。
应用开发与事件接入见 [MCP 应用开发](../apps/docsite/src/develop/app-development.md)。

## 配置 Agent

在 `config/agents.toml` 中声明 Agent 的 `id`、`description`、`model`、`prompt`、`tools` 和 `children`。
模型端点由 `config/endpoints.toml` 定义，提示词由 `config/prompts.toml` 和引用的正文文件定义。
委派需要可见的 `aurora:tool/definition/delegate` 工具，并受 `children` 中列出的目标约束。

Bot 的一次认知运行由一棵 `AgentTree` 表示。root 与 child 使用同一种节点和循环，委派在同一棵树内创建 child。
配置示例见 [Agent 配置模板](../config.example/agents.toml)。

## 编写 Python 插件

启动时会扫描 `extensions/plugins/`：每个 `*.py` 文件，或每个含 `module.py` 的子目录，都是一个插件入口。
入口必须导出唯一的 `MODULE`，其值为 `@module` 生成的 `ModuleSpec`；包形式支持相对导入。

插件与内置能力使用同一套组合机制：`provides` / `requires` 声明能力端口，
`contributes` / `consumes` 声明贡献点，清单声明命名空间、发布版本和内核 API 兼容范围。
完整可运行示例、生命周期和验证要求见 [模组开发](../apps/docsite/src/develop/core-development.md)。

也可将插件安装为独立 Python 包，通过 `aurorabot_plugin` entry point 提供入口。
修改本地插件或配置后需要重启，当前不做热加载。

## 扩展边界

- Python 插件与宿主在同一进程、同一权限下运行，只加载可信源码。
- 插件通过 `aurora_bot.contracts`、`aurora_bot.kernel` 和 `aurora_bot.utils` 使用公共契约、组合机制与底层工具；跨包能力经内核注入，不运行时导入兄弟能力实现。
- 世界读写通过声明的端口完成，不直接访问 WorldJournal 的数据库；外部行动必须经声明的 Tool 执行。
- 依赖缺失、依赖环、同优先级冲突、未声明贡献点和重复模组身份在启动前失败。
- 凭据值通过环境变量提供，配置只记录变量名；结构与启用状态由 TOML 决定。

涉及公共协议或运行时边界的扩展，应先核对 [设计思想](../apps/docsite/src/rfc/0300-design-philosophy.md)
与 [模组协议](../apps/docsite/src/rfc/0302-microkernel-and-module-protocol.md)。
