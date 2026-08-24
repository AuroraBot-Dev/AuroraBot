<p align="center"><img src="assets/logo.svg" width="112" alt="AuroraBot Logo" /></p>

# AuroraBot

AuroraBot 是以树形同构 Agent 为核心的自主智能体框架。一组 Agent 通过消息、工具调用和委派共同完成一次运行。

一次运行就是一棵 `AgentTree`；root 与 child 共用同一种循环，
节点从预定义 `AgentDefinition` 创建，并可因 Agent prompt、初始 message、可见 tools 和使用的 LLM model 不同。

## 当前实现

```text
message → model → assistant
                  ├── Tool call → tool result → model
                  └── aur.agent.delegate → child Agent → tool result → parent
```

- 四个领域 role：`system / message / assistant / tool`；
- 节点级 model 与 Tool 可见性；
- 可复用 Agent 定义目录；同一 prompt 可预定义不同 model、tools 与 child allowlist；
- `aur.*` 统一工具域、不可变工具目录与唯一执行路由；
- `aur.agent.delegate` 作为真实 Tool 产生显式树操作请求；
- 世界线总线：`WorldReader / WorldWriter / WorldJournal` 窄端口、per-scope 单调序号、全局连续事件流、观察前沿与 delta 分页披露；
- Console 输入先作为 `console.input` 进入世界线，终端输出不入世界线；
- `aur.serv.world.read` 世界正文读取、`aur.serv.world.trees` Bot 森林索引与 `aur.builtin.wait`；
- 简化记忆：最近一小时有活动的 scope 各返回最新 50 条提交，经 PromptAssembler 注入 system；
- 节律 cadence：每小时提交一次 `cadence.tick`，每 5 个非 engine 世界提交唤起一棵 triage AgentTree；
- `builtin.triage` 与 `builtin.memory` 两个 Agent 特化预设；
- 确定性的深度优先 AgentTree 循环；
- 完整项目 TOML 与 Markdown Prompt 经显式注册合并为 `AuroraConfig`；
- 每个需实例化的 `src` 子包通过独立 composition 模块接入组合根；
- 同一操作资源目录提供 method/path 与斜杠文本入口；engine、config、agents、tools、prompt、ai、world、console、cadence、memory、MCP 均有 JSON 化 ops 路径；
- MCP Python SDK 2.x 客户端：支持 stdio 与 HTTPS Streamable HTTP、启动期完整发现并冻结 Tool 目录、运行期目录变化提示重启；
- MCP Tool 进入统一 `aur.mcp.<package>.<raw_name>` 域；协商后的 `org.aurorabot/tool-contract` v1 把业务 scope
  模板接入普通 world frontier，并保留 Tool 成功、失败和效果未知契约；
- stdio App 经协商的 `org.aurorabot/world-events` 业务事件只追加 WorldJournal，是否唤起 AgentTree 仍由 cadence 决定；
- LiteLLM 统一模型网关与 OpenAI-compatible role、Tool 名称适配；
- `aurora start` 本地异步终端、`--headless` 和统一停止路径；
- 全离线 fake Model/Tool 测试。

当前范围不包含 Panel backend、sandbox、通用扩展平台，以及 MCP sampling、elicitation、roots、Tasks 和非文本结果注入。

## 开发

需要 Python 3.12 和 uv：

```bash
uv sync
cp -r config.example config
uv run aurora check
uv run aurora start
uv run aurora about
uv run aurora config list
uv run aurora donk show
```

`config.example/` 是随源码发布的模板；复制出的 `config/` 是个人配置并由 Git 忽略。`aurora check` 支持分别运行 lint 或测试，
并可请求 Ruff 修复；`aurora config list/show` 只读查看个人配置；
`aurora donk show/major/minor/patch` 管理项目版本号。

`aurora start` 在加载任何配置和组件前读取项目根目录的 `.env`，且不覆盖进程已有环境变量；随后从 `models.toml`
构造 LiteLLM 模型网关，密钥只读取配置声明的环境变量。嵌入调用与测试仍可通过
`aurora.assemble_runtime(configuration, model, tools)` 显式注入 Model 和 Tool；Provider 选择不会进入核心循环。

架构以 [RFC 0300](docs/rfc/0300-unified-architecture-and-contracts.md) 为准，实施结构见
[架构文档](docs/architecture/index.md)：按包拆分，并以 [新包扩展基线](docs/architecture/packages/package-baseline.md) 作为新增模块的最低成本基线。
