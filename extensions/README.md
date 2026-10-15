# 扩展 AuroraBot

扩展 AuroraBot，意味着为她增加一种新的做事方式，或一种新的协作角色。当前提供三条入口：

- **MCP 应用**把时间、文件、服务或设备等外部能力带进来。
- **Agent profile** 定义一个 Agent 使用什么模型、拥有哪些能力，以及可以把工作交给谁。
- **Python 插件**向组合内核追加一个自描述模块，贡献工具、前台或唤起绑定等稳定能力。

前两者只改 TOML，不写 Python；第三条在 `extensions/plugins/` 放置源码即可，无需修改任何随包发布的模块。
`extensions/` 下的应用源码与插件由 Git 忽略，只有本说明和占位文件进入版本库。

## 从一个 MCP 应用开始

MCP 应用最接近 AuroraBot 的“感知器与执行器”：它可以提供工具，也可以在环境发生变化时发回事件。
`extensions/apps/` 下的 `Windows-MCP` 与 `Aurora-QQ` 是可直接启用的示例。

1. 实现一个 stdio 或 HTTPS Streamable HTTP MCP Server。
2. 在 `config/apps.toml` 中只声明 package、transport、连接或启动方式和超时。
3. MCP Server 通过标准 `tools/list` 暴露工具，无需在 AuroraBot 中维护工具 allowlist。
4. 在 `config/agents.toml` 中用精确 Tool ID、`package.*` 或 `*` 设置 Agent profile 的能力策略。
5. 使用 `uv run --env-file .env aurora start --platform mcp` 启动并验证完整闭环。

AuroraBot 会在启动时动态发现 Server 的全部工具，并以配置 package 为 raw tool name 添加前缀，形成
`aur.mcp.<package>.<tool>` 领域 ID。模型只有在 Agent profile 的能力策略允许时才能请求工具；参数仍按 Server
提供的 JSON Schema 校验，执行结果则作为统一工具回执交还原先等待的 Agent。

## 定义一个 Agent profile

Agent profile 在 `config/agents.toml` 中显式配置，包括：

- 唯一 `id`；
- 使用的模型端点与角色提示词（提示词正文在 `config/prompts.toml` 与 `config/prompts/` 中声明）；
- 能力策略：可用 Tool ID、`package.*` 通配或 `!` 排除；
- 是否允许委派，以及允许创建哪些 child profile。

所有 profile 都通过同一种 `AgentTree` 运行：委派只是同一循环内的一次 child 创建，不引入平行的运行模型。

## 写一个 Python 插件

发现源在启动时扫描 `extensions/plugins/`：其中每个 `*.py` 文件，或每个含 `module.py` 的子目录，都是一个插件，
必须导出唯一 `MODULE`。插件用内核的 `@module` 装饰器自描述，与内置能力使用同一装配机制：

```python
from src.contracts import TOOL_CONTRIBUTIONS
from src.kernel import ModuleContext, module


@module(name="my.echo", contributes=(TOOL_CONTRIBUTIONS,))
def build(context: ModuleContext) -> None:
    context.contribute(TOOL_CONTRIBUTIONS, EchoTool())


MODULE = build
```

`provides` 以契约类型登记能力实例，`requires` 声明依赖的能力，`contributes`/`consumes` 使用已声明的稳定贡献键。
工具、前台（`FRONT_BINDINGS`）与唤起绑定（`TREE_LAUNCHER_BINDINGS`）的贡献键已由内置模块声明，插件只需贡献、不再声明。
也可通过 `aurorabot_plugin` entry point 发布模块。

## 扩展边界

- 插件与宿主在同一进程、同一权限下运行，这是有意的信任边界；只加载你信任的源码。
- 插件运行时只依赖 `src.contracts` 与 `src.kernel`；不要运行时 import 其他 `src.<pkg>`，跨包能力经内核注入的契约实例调用。
- 不要直接读写 `data/` 下的 WorldJournal；环境效果必须经已声明的 Tool 执行。
- 依赖缺失、依赖环、同优先级能力冲突、未声明贡献点与重复模块名都在启动前失败，不做静默降级。
- 密钥只通过环境变量注入，结构与启用状态继续由 TOML 决定；当前不做热加载。

若扩展需要新的公共协议、端口类型或运行时边界，请先按 [RFC 流程](../docs/rfc/README.md) 提出设计。
