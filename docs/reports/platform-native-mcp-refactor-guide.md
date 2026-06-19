# AuroraBot 平台层原生兼容 MCP 重构分步指南

> 用途：本文件作为 DeepSeek 执行平台层重构时的操作准则。
>
> 阶段判断：AuroraBot 仍处于 alpha 阶段，**不要求保留旧平台层兼容路径**。
>
> 目标：把 `src/platform/` 与 `apps/` 从进程内自定义 App Host 模型，直接重构为原生兼容 MCP 的 Host/Client/App Server 体系；Brain 的文件驱动认知内核保持边界不变。
>
> 基准日期：2026-06-19。

---

## 0. 执行总原则

本指南不是“渐进兼容迁移方案”，而是“alpha 直接替换方案”。

DeepSeek 执行时必须遵守：

1. 不保留旧 `ApplicationHost` / `PlatformAPI` / `ApplicationProtocol` 作为运行路径。
2. 不保留旧 `CommandSpec` / `AppEvent` 作为平台层核心数据结构。
3. 不保留旧 `run_app_loop()` / `on_tick()` / `host.drain_events()` 作为事件或生命周期机制。
4. 不保留 `command_dispatcher` 作为长期节点；工具调用改走 MCP Tool dispatcher。
5. 不把 AMP 设计成 App 侧私有协议；AMP 是 Platform 侧兼容归一化 envelope。
6. 不要求主仓库规定 MCP Server 或 App 的代码位置；主仓库只管理连接信息和外围元信息。
7. 不把 Brain 内部节点 MCP 化；MCP 只用于 App/Platform 外围通信。
8. 不为了保持历史测试而保留错误抽象；旧测试按目标架构重写或删除。

允许短期存在的“临时中间态”只限同一提交内辅助重构，不允许作为阶段交付结果。

---

## 1. 不可变边界

本次重构只处理 App/Platform 通信层，以及 Brain 与 Platform 的连接面。不要把 Brain 核心改成 MCP Server 或 MCP Tool。

必须保持的 Brain 哲学：

- 统一事件认知：Brain 只消费统一事件，不区分“用户事件”和“环境事件”的本体层级。
- 生命体视角：Bot 是持续存在的主体，不是一次请求一次回复的 RPC 服务。
- 文件驱动可追溯：外部变化先进入 `data/kernel/inbox/pending/event_*.json`，再由 FileEventBus / Circuit 驱动认知流。
- 节律自持：heartbeat、timer、memory consolidation 等内部节律不由外部 Tool 调用触发。

本次不重写的核心：

- `src/brain/kernel/` 的文件事件总线和 `Circuit` 编排模式。
- `src/brain/memory/` 的 L1/L2/L3 记忆概念。
- `src/brain/prompts/` 的人格和认知提示词边界。
- Brain 的“统一事件入口 -> 认知加工 -> 行动意图”基本方向。

允许修改的连接面：

- `src/brain/runtime.py`
- `src/brain/nodes/event_bridge.py`
- `src/brain/nodes/routers/command_dispatcher.py`
- `src/brain/nodes/routers/message_preprocessor.py`
- `src/brain/nodes/agents/externalizer.py`
- `src/brain/nodes/agents/internalizer.py`
- `src/brain/kernel/node_factory.py`
- `src/brain/nodes/topology.yaml`
- `src/brain/localhost/commands/`

不允许的做法：

- 不要手写一套“看起来像 MCP”的 JSON-RPC 替代官方 SDK。
- 不要让 MCP Server 直接读写 Brain 的 `data/kernel/` 或 `data/memory/`。
- 不要让 App import `src.platform` 或 `src.brain`。
- 不要让 App 继续依赖 `PlatformAPI`，再包装成 MCP Tool。
- 不要把 notification 当成可靠命令调用；有副作用的动作必须走 `tools/call`。

---

## 2. 目标架构

### 2.1 运行时角色

| 角色 | 目标职责 | 不负责 |
| --- | --- | --- |
| AuroraBot Core | 启动 Brain、Platform、localhost 控制台 | 直接 import App 业务模块 |
| Platform | MCP Host 边界、连接管理、权限、工具目录、AMP 归一化 | 认知决策、人格、记忆 |
| MCPClientManager | 每个 MCP Server 一个 Client session，负责 list/call/notifications | 启停本地进程 |
| MCPServerKit | 本地 stdio Server 生命周期管理 | tool cache、事件转换 |
| AMPCompatibilityBridge | 把 MCP 信号归一化为 Brain 统一事件文件 | 判断是否回复、调用 LLM |
| MCPToolDispatcher | 执行 Brain 产生的工具调用意图 | 自行解析自然语言命令 |
| App MCP Server | 暴露 Tools / Resources / Prompts / Notifications | 跨 App 编排、读写 Brain |

### 2.2 目标模块结构

```text
src/platform/
  __init__.py
  app_config.py              # 读取 apps/config.yml，只保留 MCP/registry 配置
  manifest.py                # 外围元信息读取；不再解析 CommandSpec
  mcp_kit/
    __init__.py
    server_spec.py           # MCPServerSpec / transport config / permissions
    discovery.py             # 从 config/manifest/registry 合成 MCPServerSpec
    server_kit.py            # 本地 stdio server spawn/stop/health
    client_manager.py        # MCP Client session、tools/list、tools/call、notifications
    amp.py                   # Platform 侧 AMP envelope / normalizer / validator
    tool_schema.py           # MCP Tool -> LLM tool schema / prompt text
    permissions.py           # tool/resource 权限和风险等级
    errors.py                # 平台层异常
```

必须删除或停止作为运行路径使用：

```text
src/platform/application_host.py
src/platform/application_api.py
src/platform/application_protocol.py
src/platform/loop.py
src/platform/contracts.py        # 若仍需要类型，拆到 mcp_kit 内部，不保留旧语义
```

Brain 连接面目标结构：

```text
src/brain/nodes/event_bridge.py
  run_mcp_event_bridge(...)      # 唯一外部事件桥

src/brain/nodes/routers/mcp_tool_dispatcher.py
  dispatch MCP tool calls

src/brain/nodes/routers/command_dispatcher.py
  删除
```

App 目标结构不强制位于主仓库内。主仓库内置样例可采用：

```text
apps/aurora-app-example/
  manifest.yaml                  # 可选外围元信息
  mcp_server.py                  # MCP Server 入口
  service.py                     # 纯业务逻辑
  config.example.yml             # App 私有配置示例
  README.md
```

独立仓库、用户本机任意目录、远程 MCP Server 均可接入。Platform 只依赖连接配置和外围元信息。

### 2.3 目标数据流

外部事件：

```text
World / Third-party MCP Server / Aurora-native App
  -> MCP lifecycle / notifications / resources / tool results
  -> MCPClientManager
  -> AMPCompatibilityBridge
  -> data/kernel/inbox/pending/event_<type>_<id>.json
  -> Brain FileEventBus
```

行动执行：

```text
Brain action intent
  -> MCPToolDispatcher
  -> MCPClientManager.call_tool(full_tool_name, args)
  -> target MCP Server
  -> tool result
  -> audit file + optional AMP tool.completed/tool.failed event
```

能力发现：

```text
apps/config.yml / manifest / registry
  -> MCPServerSpec
  -> ServerKit start local stdio server if needed
  -> ClientManager initialize
  -> tools/list resources/list prompts/list
  -> tool schema exposed to Externalizer / LLM gateway
```

---

## 3. 删除旧平台层

因为 alpha 阶段不考虑过渡兼容，第一批重构就要移除旧抽象的运行入口。

### 3.1 删除对象

删除或清空引用：

- `src/platform/application_host.py`
- `src/platform/application_api.py`
- `src/platform/application_protocol.py`
- `src/platform/loop.py`
- `src/platform/contracts.py`
- `src/brain/nodes/routers/command_dispatcher.py`

删除 App 侧旧入口：

- `apps/*/runtime.py`
- App 类中的 `_bind(api)`
- App 类中的 `on_start()` / `on_stop()` / `on_tick()`
- App 对 `PlatformAPI.emit_event()`、`register_command()`、`data_dir` 的依赖

删除测试或重写测试：

- `tests/test_application_host*.py`
- 只验证 `CommandSpec` 的测试
- 只验证 `AppEvent` 队列的测试
- 只验证 `command_dispatcher` 调用 `host.invoke_command()` 的测试

### 3.2 搜索并清零旧依赖

执行：

```powershell
rg -n "ApplicationHost|PlatformAPI|ApplicationProtocol|AppEvent|CommandSpec|invoke_command|list_command_specs|drain_events|run_app_loop|on_tick|command_dispatcher" src tests apps
```

阶段验收时，上述命中只能出现在：

- 历史文档。
- changelog / report。
- 明确标注为删除原因的注释。

不能出现在运行时代码、测试 fixture、拓扑配置中。

### 3.3 `src/brain/runtime.py` 目标状态

`RuntimeState` 不再保存 `host`。

目标字段：

```python
@dataclass(slots=True)
class RuntimeState:
    circuit: Circuit
    server_kit: MCPServerKit
    client_manager: MCPClientManager
    stop_event: asyncio.Event
    tasks: list[asyncio.Task[None]]
```

启动顺序：

1. `ensure_dirs()`
2. 读取 `apps/config.yml` / manifest / registry。
3. 构造 `MCPServerSpec` 列表。
4. `MCPServerKit.start_all()` 启动本地 stdio Server。
5. `MCPClientManager.connect_all()` 建立 session。
6. `MCPClientManager.refresh_capabilities()` 获取 tools/resources/prompts。
7. 启动 `run_mcp_event_bridge()`。
8. 启动 Brain `Circuit`。
9. 启动 localhost 控制台。

关闭顺序：

1. 停止接收新的外部事件。
2. 取消或等待正在执行的 tool call。
3. flush tool result / AMP event audit。
4. `MCPClientManager.shutdown()`。
5. `MCPServerKit.stop_all()`。
6. 停止 Brain runtime。

---

## 4. MCP 规范落地约束

执行时以官方 MCP 规范为准。

当前文档使用的规范标记：

- 规范入口：<https://modelcontextprotocol.io/specification/latest>
- 本指南编写时使用 `2025-11-25` 规范链接。
- Python SDK：<https://github.com/modelcontextprotocol/python-sdk>

实现约束：

- 先使用 SDK v1 稳定线：`mcp[cli]>=1.27,<2`。
- 第一阶段 transport 只实现 `stdio`。
- Streamable HTTP 作为第二阶段能力设计接口，但不阻塞本轮重构。
- 不启用 Roots / Sampling / Elicitation，除非后续安全策略明确授权。
- stdio Server 的 stdout 只能输出 MCP JSON-RPC；日志走 stderr 或文件。

依赖修改：

```powershell
uv add "mcp[cli]>=1.27,<2"
uv sync --group dev
```

如果依赖安装失败，记录具体错误，不要写 SDK stub。

---

## 5. App 发现与位置无关原则

### 5.1 核心原则

主仓库不规定 App/MCP Server 的代码位置。

Platform 只需要：

- `key`：本地唯一连接名。
- `package`：全局包名或能力命名空间。
- `name` / `version` / `description`：外围元信息。
- `transport`：第一阶段只支持 `stdio`。
- `command` / `args` / `env` / `cwd`：本地进程启动信息。
- `endpoint` / `headers`：预留给 Streamable HTTP。
- `permissions`：工具、资源、通知风险策略。

App 可以位于：

- 主仓库 `apps/` 内。
- 独立 Git 仓库。
- 用户本机任意目录。
- 远程 MCP 服务。
- in-process adapter，仅限受框架限制时的特例；对 Platform 暴露仍必须是 MCP 语义。

### 5.2 `apps/config.yml` 目标格式

```yaml
apps:
  weather:
    enabled: true
    package: im.polaris.weather
    name: Weather
    version: "1.0.0"
    transport: stdio
    command:
      - uv
      - run
      - --project
      - D:/aurora-app-weather
      - python
      - -m
      - aurora_weather.mcp_server
    env:
      AURORA_APP_DATA_DIR: data/app_data/weather
    startup:
      default_city: 北京
      language: zh
    permissions:
      tools:
        im.polaris.weather.get_weather:
          risk: low
          enabled: true
```

主仓库内置样例也使用同一配置：

```yaml
apps:
  diary:
    enabled: true
    package: im.polaris.diary
    transport: stdio
    command:
      - uv
      - run
      - python
      - -m
      - apps.aurora-app-diary.mcp_server
```

### 5.3 `MCPServerSpec`

文件：`src/platform/mcp_kit/server_spec.py`

必备字段：

```python
@dataclass(slots=True)
class MCPServerSpec:
    key: str
    package: str
    name: str
    version: str = "0.0.0"
    description: str = ""
    transport: Literal["stdio"] = "stdio"
    command: list[str] = field(default_factory=list)
    args: list[str] = field(default_factory=list)
    cwd: Path | None = None
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    startup: dict[str, object] = field(default_factory=dict)
    health_timeout_seconds: float = 10.0
    tool_timeout_seconds: float = 30.0
    permissions: AppPermissionSpec = field(default_factory=AppPermissionSpec)
```

校验规则：

- `key` 非空，只能包含字母、数字、`-`、`_`。
- `package` 必须全局唯一。
- `enabled=true` 时，stdio `command` 不能为空。
- `cwd` 如果配置，必须存在。
- `transport` 遇到非 `stdio` 直接报错，并提示本阶段未实现。
- `env` 只允许字符串值。

### 5.4 Discovery

文件：`src/platform/mcp_kit/discovery.py`

职责：

- 读取 `apps/config.yml`。
- 可选读取本地 `apps/*/manifest.yaml`，补充 name/version/description。
- 将 registry 或远程元信息预留为接口，不要求第一阶段实现。
- 产出 `list[MCPServerSpec]`。

不再做：

- 不 import `apps/*/__init__.py`。
- 不实例化 App class。
- 不扫描 `runtime.py`。
- 不读取旧 `commands` 作为运行时命令源。

验收：

- 仅靠 `apps/config.yml` 可以启动一个主仓库外的 fake MCP Server。
- 主仓库内 `apps/` 为空时，Platform 仍能通过 config 接入外部 MCP Server。

---

## 6. AMP 兼容归一化层

### 6.1 定位

AMP 是 AuroraBot Platform 内部的统一事件 envelope。

它不是：

- MCP 传输协议。
- MCP Server 必须实现的私有规范。
- App 开发者必须导入的 SDK。
- `aurora/event` notification 的同义词。

它是：

- Brain 的统一事件入口格式。
- Platform 吸收全 MCP 生态的兼容层。
- 旧 `AppEvent` 语义的目标替代物。
- lifecycle、capability、tool result、resource observation、notification、error 的统一审计格式。

### 6.2 Envelope

文件：`src/platform/mcp_kit/amp.py`

必备 dataclass：

```python
@dataclass(slots=True)
class AMPSource:
    app: str
    instance: str = "default"
    transport: str = "stdio"


@dataclass(slots=True)
class AMPHeader:
    protocol: str
    method: str
    message_id: str
    timestamp: str
    source: AMPSource
    trace_id: str = ""


@dataclass(slots=True)
class AMPPayload:
    type: str
    session_id: str = ""
    summary: str = ""
    data: dict[str, object] = field(default_factory=dict)
    expire_at: str | None = None


@dataclass(slots=True)
class AMPEnvelope:
    header: AMPHeader
    payload: AMPPayload
```

`header.method` 记录原始信号类别：

- `mcp.lifecycle`
- `mcp.notification`
- `mcp.tool_result`
- `mcp.resource`
- `mcp.error`
- `aurora/event`

不要限制为 `aurora/*`。

### 6.3 标准映射

| 输入信号 | AMP `header.method` | AMP `payload.type` |
| --- | --- | --- |
| initialize 成功 | `mcp.lifecycle` | `lifecycle.started` |
| session 断开 | `mcp.lifecycle` | `lifecycle.stopped` |
| server 进程异常退出 | `mcp.lifecycle` | `lifecycle.crashed` |
| `notifications/tools/list_changed` | `mcp.notification` | `capability.changed` |
| `notifications/resources/list_changed` | `mcp.notification` | `capability.changed` |
| `notifications/prompts/list_changed` | `mcp.notification` | `capability.changed` |
| 任意第三方 notification | `mcp.notification` | `mcp.notification.<method>` |
| `tools/call` 成功 | `mcp.tool_result` | `tool.completed` |
| `tools/call` 失败 | `mcp.tool_result` | `tool.failed` |
| `resources/read` 被纳入观察 | `mcp.resource` | `resource.observed` |
| 协议解析/超时/权限失败 | `mcp.error` | `mcp.error` |
| Aurora 原生 `aurora/event` | `aurora/event` | params 中声明的业务类型 |

### 6.4 必备函数

```python
def build_event_envelope(...) -> AMPEnvelope: ...

def build_from_mcp_signal(
    *,
    server: MCPServerSpec,
    method: str,
    signal_type: str,
    params: Mapping[str, object],
    summary: str = "",
) -> AMPEnvelope: ...

def parse_amp_envelope(raw: object) -> AMPEnvelope: ...

def amp_to_file_event(envelope: AMPEnvelope) -> dict[str, object]: ...

def normalize_aurora_event_params(
    *,
    server: MCPServerSpec,
    params: Mapping[str, object],
) -> AMPEnvelope: ...
```

不要实现 `legacy_app_event_to_amp()`。alpha 阶段直接删除旧 `AppEvent`。

### 6.5 Aurora 原生事件快捷入口

Aurora 原生 App 可以发送：

```json
{
  "method": "aurora/event",
  "params": {
    "type": "message.received",
    "session_id": "group_123456",
    "summary": "收到一条群消息",
    "data": {
      "text": "你好"
    }
  }
}
```

Platform 收到后：

1. 不信任 App 提供的 `source`。
2. 用当前 MCP session 的 `MCPServerSpec.package` 填充 `header.source.app`。
3. 生成 `message_id` 和带时区 `timestamp`。
4. 校验 `payload.type` 非空。
5. 写入 Brain inbox。

第三方 MCP Server 没有 `aurora/event` 时，不视为能力缺失。

---

## 7. MCP ServerKit

文件：`src/platform/mcp_kit/server_kit.py`

### 7.1 职责

`MCPServerKit` 只管理本地 Server 进程：

- `start_all(specs)`
- `start_one(spec)`
- `stop_all()`
- `stop_one(key)`
- `restart_one(key)`
- `health_report()`
- `processes`

不做：

- 不调用 tools。
- 不缓存 tools。
- 不解析 notification。
- 不写 Brain inbox。
- 不做权限判断。

### 7.2 stdio 启动

实现要求：

- 使用 `asyncio.create_subprocess_exec()`，不要通过 shell 拼字符串。
- `stdin` / `stdout` 保留给 MCP transport。
- `stderr` 异步读取并写 DEBUG/WARNING 日志。
- `cwd` 使用 `MCPServerSpec.cwd`。
- `env` 合并当前环境和 spec.env。
- 进程启动失败时抛出 `MCPServerStartError`。

### 7.3 健康状态

状态枚举：

- `configured`
- `starting`
- `running`
- `stopped`
- `crashed`
- `failed_to_start`

`health_report()` 返回结构：

```python
{
    "weather": {
        "status": "running",
        "package": "im.polaris.weather",
        "pid": 12345,
        "last_error": "",
        "started_at": "2026-06-19T12:00:00+08:00",
    }
}
```

进程异常退出时：

- 更新 health。
- 生成 `lifecycle.crashed` AMP 信号，交给 Platform event queue。
- 不在 ServerKit 内自动无限重启；重启策略以后单独设计。

---

## 8. MCP ClientManager

文件：`src/platform/mcp_kit/client_manager.py`

### 8.1 职责

`MCPClientManager` 是 AuroraBot Host 中的 MCP Client 管理器：

- 每个 Server 一个 session。
- 执行 initialize。
- 发送 `notifications/initialized`。
- 获取 `tools/list`、`resources/list`、`prompts/list`。
- 维护 tool/resource/prompt cache。
- 执行 `tools/call`。
- 接收 notifications。
- 将可观测信号送入 AMP queue。

### 8.2 接口

```python
class MCPClientManager:
    async def connect_all(self, specs: Sequence[MCPServerSpec]) -> None: ...
    async def connect_one(self, spec: MCPServerSpec) -> None: ...
    async def refresh_capabilities(self, key: str | None = None) -> None: ...
    async def list_tools(self) -> list[MCPToolEntry]: ...
    async def call_tool(self, full_tool_name: str, arguments: dict[str, object]) -> MCPToolResult: ...
    async def read_resource(self, uri: str) -> MCPResourceResult: ...
    def tools_as_openai_schema(self) -> list[dict[str, object]]: ...
    def tools_as_prompt_text(self) -> str: ...
    @property
    def amp_queue(self) -> asyncio.Queue[AMPEnvelope]: ...
    async def shutdown(self) -> None: ...
```

### 8.3 Tool 命名

对 Brain/LLM 暴露的工具名必须全局唯一。

规则：

1. 如果 MCP Server tool 名已经以 package 开头，直接使用。
2. 否则使用 `{package}.{tool_name}`。
3. 冲突时启动失败，不静默覆盖。
4. tool name 与 server key 的映射必须可反查。

示例：

```text
get_weather -> im.polaris.weather.get_weather
send_message -> im.polaris.qq.send_message
im.polaris.diary.write_diary -> im.polaris.diary.write_diary
```

### 8.4 Capability refresh

收到以下 notification 时刷新对应 cache：

- `notifications/tools/list_changed`
- `notifications/resources/list_changed`
- `notifications/prompts/list_changed`

同时生成 AMP：

```text
header.method = mcp.notification
payload.type = capability.changed
payload.data = {
  "method": "notifications/tools/list_changed",
  "server": "weather",
  "package": "im.polaris.weather"
}
```

### 8.5 Tool result 事件

每次 `call_tool()` 后生成审计事件：

- 成功：`payload.type = tool.completed`
- 失败：`payload.type = tool.failed`
- 超时：`payload.type = tool.failed`，`data.reason = "timeout"`
- 权限拒绝：`payload.type = tool.failed`，`data.reason = "permission_denied"`

Tool result 的内容不能作为指令直接注入模型；它是数据。

---

## 9. 权限与安全

文件：`src/platform/mcp_kit/permissions.py`

### 9.1 风险等级

工具风险等级：

- `low`：只读查询或无外部副作用。
- `medium`：写入 App 私有状态或轻量外部副作用。
- `high`：发送消息、操作账户、删除数据、执行支付等外部副作用。
- `critical`：执行任意命令、读写任意文件、访问 secrets。默认禁止。

第一阶段策略：

- `low` / `medium` 默认允许。
- `high` 需要显式配置 `enabled: true`。
- `critical` 即使配置也先拒绝，除非专门实现确认机制。

### 9.2 Tool call 前检查

`MCPToolDispatcher` 调用前检查：

- tool 是否存在。
- server 是否 connected。
- tool 是否 enabled。
- risk 是否允许。
- 参数是否符合 MCP schema。
- 是否超出 timeout。

拒绝时返回结构化失败，并写 `tool.failed` AMP 事件。

### 9.3 禁止默认能力

默认禁用：

- MCP Roots
- MCP Sampling
- MCP Elicitation
- 任意文件系统 roots
- 任意 shell / command executor tool

除非后续单独做安全设计，否则不要接入。

---

## 10. Brain 事件桥

文件：`src/brain/nodes/event_bridge.py`

### 10.1 删除旧桥

删除：

- `run_event_bridge(host, circuit, ...)`
- `host.drain_events()`
- 旧 `AppEvent.to_dict()` 处理逻辑

保留唯一入口：

```python
async def run_mcp_event_bridge(
    client_manager: MCPClientManager,
    circuit: Circuit,
    stop_event: asyncio.Event,
) -> None:
    ...
```

### 10.2 行为

`run_mcp_event_bridge()`：

1. 从 `client_manager.amp_queue` 消费 `AMPEnvelope`。
2. 构造文件名：

```text
inbox/pending/event_<payload.type with . and / replaced by _>_<header.message_id>.json
```

3. 写入完整 envelope。
4. 不调用 LLM。
5. 不判断是否回复。
6. 不修改 App 私有状态。

### 10.3 `message_preprocessor`

文件：`src/brain/nodes/routers/message_preprocessor.py`

目标只支持 AMP envelope，不再支持旧扁平 `AppEvent`。

读取字段：

- `payload.type`
- `payload.session_id`
- `payload.summary`
- `payload.data`
- `header.source.app`
- `header.message_id`
- `header.timestamp`
- `header.method`

输出到后续 message queue 时保留 trace：

```json
{
  "type": "message.received",
  "session_id": "group_123",
  "source": "im.polaris.qq",
  "text": "...",
  "trace": {
    "message_id": "...",
    "method": "aurora/event",
    "timestamp": "..."
  }
}
```

验收：

- `capability.changed` 能进入 inbox，但可以被 preprocessor 标记为系统事件。
- `message.received` 能被格式化为第一人称可理解文本。
- `tool.completed` / `tool.failed` 能作为行动反馈事件进入 Brain。

---

## 11. Brain 工具调用链

### 11.1 删除 `command_dispatcher`

删除：

- `src/brain/nodes/routers/command_dispatcher.py`
- `topology.yaml` 中的 `command_dispatcher` 节点。
- `NodeFactory` 对 `command_dispatcher` 的注册。
- Externalizer 生成旧 `{"command": "...", "params": {...}}` 后再由 command_dispatcher 解析的路径。

### 11.2 新增 `mcp_tool_dispatcher`

新增：

```text
src/brain/nodes/routers/mcp_tool_dispatcher.py
```

职责：

- 读取 Brain 产生的 tool intent 文件。
- 校验 tool 名和参数。
- 调用 `MCPClientManager.call_tool()`。
- 写入 tool result audit。
- 生成 `tool.completed` / `tool.failed` AMP 事件。

建议输入文件：

```text
data/kernel/pipeline/tool_intents/intent_<id>.json
```

格式：

```json
{
  "intent_id": "uuid",
  "tool": "im.polaris.weather.get_weather",
  "arguments": {
    "city": "北京"
  },
  "reason": "需要了解当前天气",
  "trace": {
    "source_message_id": "..."
  }
}
```

结果文件：

```text
data/kernel/pipeline/tool_results/result_<intent_id>.json
```

格式：

```json
{
  "intent_id": "uuid",
  "tool": "im.polaris.weather.get_weather",
  "ok": true,
  "result": {},
  "error": null,
  "timestamp": "2026-06-19T12:00:00+08:00"
}
```

### 11.3 Externalizer

文件：`src/brain/nodes/agents/externalizer.py`

目标：

- 不再读取 `_host.list_command_specs()`。
- 工具上下文来自 `MCPClientManager.tools_as_openai_schema()` 或 `tools_as_prompt_text()`。
- 如果当前 `LLMGateway` 尚未支持原生 tool calls，Externalizer 仍可输出 tool intent JSON 文件，但字段必须是 `tool` / `arguments`，不是旧 `command` / `params`。
- 后续 `LLMGateway` 支持 tool calls 后，直接落到同一 tool intent 格式。

### 11.4 localhost 控制台

重写 `src/brain/localhost/commands/`：

- `invoke`：调用 MCP tool。
- `say`：调用 QQ/IM connector 的 send tool，或写入本地测试事件。
- `emit`：写 AMP envelope 到 inbox，用于调试 Brain，不再构造 `AppEvent`。
- `apps`：列出 MCP Server health 和 capabilities。
- `tools`：列出当前 tool cache。

禁止控制台继续访问 `runtime.host`。

---

## 12. App 重构规范

### 12.1 通用结构

每个内置 App 采用：

```text
apps/aurora-app-name/
  manifest.yaml
  mcp_server.py
  service.py
  config.example.yml
  README.md
```

`service.py`：

- 只包含业务逻辑。
- 不 import MCP SDK。
- 不 import `src.platform`。
- 不 import `src.brain`。
- 可单独单测。

`mcp_server.py`：

- 使用官方 SDK / FastMCP。
- 注册 tools/resources/prompts。
- 负责把 service 接到 MCP。
- stdout 不输出日志。

### 12.2 diary

删除：

- `runtime.py`
- `DiaryApplication`
- `PlatformAPI` data dir 依赖

新增 tools：

- `im.polaris.diary.write_diary`
- `im.polaris.diary.read_diary`
- `im.polaris.diary.list_dates`
- `im.polaris.diary.search_diary`（可选）

新增 resources：

- `diary://dates`
- `diary://entry/{date}`

验收：

- 可以在主仓库外通过 stdio 启动。
- tools/list 能看到 diary tools。
- write/read/list 都可通过 `MCPClientManager.call_tool()` 调用。

### 12.3 clock

删除：

- `on_tick()` 轮询模型。
- 旧 Host 事件队列。

新增 tools：

- `im.polaris.clock.get_current_time`
- `im.polaris.clock.set_alarm`
- `im.polaris.clock.set_timer`
- `im.polaris.clock.list_alarms`
- `im.polaris.clock.cancel_alarm`

事件：

- 到时后可发送 Aurora 原生 `aurora/event`，`type=alarm.triggered` 或 `timer.triggered`。
- 也可以由 Platform adapter 把标准 notification 映射为上述类型。

验收：

- `set_timer(seconds=1)` 后 inbox 出现 `timer.triggered`。
- Server shutdown 时取消后台 task 并保存状态。

### 12.4 weather

新增 tools：

- `im.polaris.weather.get_weather`
- `im.polaris.weather.get_forecast`
- `im.polaris.weather.set_default_city`

新增 resources：

- `weather://config`
- `weather://last-report`

规则：

- HTTP timeout 可配置。
- HTTP 失败返回结构化错误，不退出进程。
- 不默认主动上报事件；除非配置 polling 或 tool 参数要求。

验收：

- 默认城市北京可查询。
- 网络失败生成 `tool.failed`。
- tool result 不污染 stdout。

### 12.5 QQ / OneBot / NoneBot connector

目标不是立即“消灭 NoneBot”，而是把 NoneBot 降级为可选边缘 connector。

新增 App：

```text
apps/aurora-app-qq-nonebot/
  mcp_server.py
  service.py
  nonebot_adapter.py
```

或独立仓库：

```text
aurora-app-qq-nonebot/
```

目标 tools：

- `im.polaris.qq.send_message`
- `im.polaris.qq.send_private_message`
- `im.polaris.qq.send_group_message`
- `im.polaris.qq.recall_message`
- `im.polaris.qq.get_group_member_info`

目标事件：

- `message.received`
- `message.reaction`
- `session.created`
- `session.closed`
- `lifecycle.started`
- `lifecycle.crashed`

实现路线：

1. Core 不再由 NoneBot 启动。
2. NoneBot 只存在于 QQ connector 内。
3. QQ connector 对 Core 暴露 MCP tools 和事件。
4. 如果 NoneBot 生命周期无法独立进程化，允许 in-process adapter，但必须隔离在 Platform/App 边界，不允许 Brain import NoneBot。

验收：

- `src/main.py` / Core runtime 不 import `nonebot`。
- 群消息进入 `inbox/pending/event_message_received_*.json`。
- 发送消息通过 MCP tool。
- OneBot API 失败返回结构化错误。

---

## 13. Runtime 与入口去 NoneBot 化

本节对应“脱离 NoneBot 框架”的合理边界。

### 13.1 新增 Core 入口

新增：

```text
src/aurora/main.py
```

职责：

- 初始化配置。
- 启动 Platform。
- 启动 Brain。
- 启动 localhost 控制台。
- 处理 shutdown。

新增 CLI 或脚本入口：

```text
aurora-core
```

或先使用：

```powershell
uv run python -m src.aurora.main
```

### 13.2 NoneBot 入口降级

`bot.py` 不再是 Core 唯一入口。

目标：

- `bot.py` 只作为可选 NoneBot 启动器或 QQ connector 的实现细节，不再是 Core 主入口。
- Core 可以不依赖 NoneBot 独立启动。
- `nonebot2` 依赖后续移动到 optional dependency，例如 `qq-nonebot` extra。

### 13.3 验收

- 不启动 NoneBot 也能运行 Brain + Platform + localhost。
- 没有 QQ connector 时，Core 正常运行，只是缺少 QQ tools/events。
- 启动 QQ connector 后，QQ 能力通过 MCP 出现在 tools/list。

---

## 14. 阶段实施

### Phase 0：切断旧平台层

目标：让仓库不再能通过旧 Host 路径运行。

操作：

1. 删除旧 platform 文件。
2. 删除旧 App `runtime.py`。
3. 删除 `command_dispatcher`。
4. 删除旧测试。
5. 更新 imports。
6. 运行 `rg` 确认旧符号清零。

验收：

```powershell
rg -n "ApplicationHost|PlatformAPI|ApplicationProtocol|AppEvent|CommandSpec|run_app_loop|drain_events|command_dispatcher" src tests apps
```

无运行时代码命中。

### Phase 1：建立 MCP 基础设施

目标：Platform 能发现、启动、连接一个 fake MCP Server。

操作：

1. 添加 `mcp[cli]` 依赖。
2. 新建 `mcp_kit` 包。
3. 实现 `MCPServerSpec`。
4. 实现 discovery。
5. 实现 ServerKit。
6. 实现 ClientManager initialize / tools/list。
7. 实现 tool schema adapter。

验收：

- fake server 可启动。
- `tools/list` 成功。
- 工具名加 package 前缀。
- `ruff` / `pyright` / MCP 单测通过。

### Phase 2：AMP Bridge

目标：标准 MCP 信号进入 Brain inbox。

操作：

1. 实现 `amp.py`。
2. `ClientManager` 暴露 `amp_queue`。
3. notification/lifecycle/tool result/resource/error 统一生成 AMP。
4. 实现 `run_mcp_event_bridge()`。
5. `message_preprocessor` 改为只识别 AMP envelope。

验收：

- `notifications/tools/list_changed` -> `capability.changed` 文件。
- `tools/call` 成功 -> `tool.completed` 文件。
- `tools/call` 失败 -> `tool.failed` 文件。
- 第三方 fake MCP Server 不实现 AMP 也能产生事件。
- Aurora 原生 `aurora/event` 能补齐 header。

### Phase 3：Tool 调用链

目标：Brain 不再通过 `command_dispatcher` 调用 App。

操作：

1. 新增 `mcp_tool_dispatcher`。
2. 定义 `tool_intents` 和 `tool_results` 文件格式。
3. Externalizer 改用 MCP tool schema。
4. localhost `invoke/tools/apps` 改用 ClientManager。
5. topology 移除旧 action queue 到 command dispatcher 的边。

验收：

- Externalizer 能产生 `tool_intent`。
- Dispatcher 能调用 fake `echo` tool。
- tool result 写入文件。
- tool result 生成 AMP 反馈事件。

### Phase 4：迁移内置 App

顺序：

1. diary
2. clock
3. weather
4. qq-nonebot connector

每个 App 必须：

- 删除 `runtime.py`。
- 新增 `service.py`。
- 新增 `mcp_server.py`。
- 更新 `apps/config.yml`。
- 增加 MCP integration test。

验收：

- 所有启用 App 都通过 MCP 启动或连接。
- `apps/` 内没有旧 App class。
- App 不 import `src.platform` / `src.brain`。

### Phase 5：Core 去 NoneBot 化

目标：AuroraBot Core 独立于 NoneBot 启动。

操作：

1. 新增 `src/aurora/main.py`。
2. 把 `src/main.py` 中 startup/shutdown 抽成 Core runtime 可调用函数。
3. 调整 `bot.py` 为可选 launcher。
4. QQ 接入移动到 connector。
5. 规划 `nonebot2` optional dependency。

验收：

- `uv run python -m src.aurora.main` 可启动 Core。
- Core import tree 不依赖 NoneBot。
- QQ connector 独立提供 MCP tools/events。

### Phase 6：清理与固化

目标：文档、测试、CI 都只承认 MCP 目标架构。

操作：

1. 更新 README / docs。
2. 删除旧报告中会误导执行的兼容话术，或标注历史。
3. 更新 CI 测试集。
4. 全量运行质量检查。

验收：

```powershell
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run pyright src/
uv run pytest --cov=src
```

---

## 15. 测试要求

### 15.1 单元测试

新增或保留：

```text
tests/test_mcp_server_spec.py
tests/test_mcp_discovery.py
tests/test_mcp_server_kit.py
tests/test_mcp_client_manager.py
tests/test_mcp_amp.py
tests/test_mcp_event_bridge.py
tests/test_mcp_tool_dispatcher.py
tests/test_mcp_permissions.py
```

覆盖点：

- config -> spec。
- package 前缀和工具冲突。
- stdio server 启停。
- initialize / tools/list / tools/call。
- capability_changed notification。
- AMP normalizer。
- `aurora/event` params 补齐 header。
- tool.completed / tool.failed。
- 权限拒绝。

### 15.2 fixture

新增：

```text
tests/fixtures/mcp_echo_server.py
tests/fixtures/mcp_event_server.py
tests/fixtures/mcp_broken_server.py
```

fixture 能力：

- echo tool。
- fail tool。
- slow tool。
- list_changed notification。
- optional `aurora/event`。
- 非法 JSON / 进程退出模拟。

### 15.3 删除旧测试

删除或重写：

- `ApplicationHost` 行为测试。
- `PlatformAPI` 行为测试。
- `CommandSpec` 文本拼接测试。
- `AppEvent` drain 测试。
- `command_dispatcher` 调用旧 host 测试。

---

## 16. 代码风格约束

遵守仓库现有规则：

- 所有 Python 文件加 `from __future__ import annotations`。
- 公共函数必须写类型标注。
- dataclass 使用 `slots=True`。
- 日志使用 `get_logger()`，不要 `print()`。
- INFO 只记录生命周期和用户可见结果。
- DEBUG 记录协议细节、tools/list、tools/call 参数摘要、notification 路由。
- WARNING 记录配置回退、App 缺失、工具冲突、notification 解析失败。
- ERROR/exception 记录功能中断。
- 不要使用无时区 `datetime.now()`。
- 文件路径使用 `pathlib.Path`。
- 行宽 120。

---

## 17. DeepSeek 执行守则

每次执行任务时按这个顺序：

1. 先读本文件。
2. 运行旧符号 `rg`，确认要删除的依赖位置。
3. 一次只做一个 Phase。
4. alpha 阶段不保留旧运行路径。
5. 删除旧代码后立即更新测试，不为旧测试保留适配层。
6. 不引入新全局单例；Platform runtime context 显式注入。
7. 不在 App MCP Server 中读取 Brain 内部文件。
8. 不把 AMP 当成第三方 MCP Server 必须实现的协议。
9. 不把 notification 当作命令调用。
10. QQ/NoneBot 只作为 connector，不作为 Core 框架依赖。
11. 每阶段结束更新 `docs/reports/platform-native-mcp-progress.md`。
12. 每阶段结束写清楚运行过的验证命令和剩余风险。

---

## 18. 阶段验收总表

| 阶段 | 必须证明 |
| --- | --- |
| Phase 0 | 旧 Host/API/Protocol/AppEvent/CommandSpec/command_dispatcher 运行路径已删除 |
| Phase 1 | fake MCP Server 可启动、连接、list tools |
| Phase 2 | 标准 MCP 信号和可选 `aurora/event` 均能写入 Brain inbox |
| Phase 3 | Brain tool intent 可调用 MCP Tool，并写入 tool result |
| Phase 4 | diary/clock/weather/qq 均以 MCP Server 或 connector 方式接入 |
| Phase 5 | Core 可不依赖 NoneBot 独立启动 |
| Phase 6 | 文档、测试、CI 均只承认 MCP 目标架构 |

---

## 19. 最终完成定义

重构完成时，项目满足：

- `src/platform/mcp_kit/` 是平台层主入口。
- `apps/config.yml` 可以声明主仓库内、主仓库外、本机任意路径的 MCP Server。
- 主仓库不 import App 业务模块。
- App 不 import `src.platform` 或 `src.brain`。
- App 能力通过 MCP `tools/list` / `resources/list` / `prompts/list` 暴露。
- App 动作通过 MCP `tools/call` 执行。
- 外部变化通过 Platform 归一化为 AMP envelope 后写入 Brain inbox。
- 第三方 MCP Server 不需要实现 AMP。
- Aurora 原生 `aurora/event` 只是可选快捷入口。
- Brain 仍只通过文件总线消费统一事件。
- `ApplicationHost`、`PlatformAPI`、`ApplicationProtocol`、`CommandSpec`、`AppEvent`、`command_dispatcher` 不再是运行时代码。
- Core 可以脱离 NoneBot 启动。
- QQ/OneBot 通过可选 connector 接入。
- 全量质量检查通过。
