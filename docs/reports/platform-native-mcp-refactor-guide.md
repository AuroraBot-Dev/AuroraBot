# AuroraBot 平台层原生兼容 MCP 重构分步指南

> 用途：本文件作为 DeepSeek 执行平台层重构时的操作准则。
>
> 目标：把 `src/platform/` 与 `apps/` 从进程内自定义 App Host 模型，重构为原生兼容 MCP 的 App Server 体系；Brain 的文件驱动认知内核保持现状。
>
> 基准日期：2026-06-19。

---

## 0. 不可变边界

本次重构只处理 App/Platform 通信层。不要把 Brain 节点、FileEventBus、记忆系统、节律系统改成 MCP Server 或 MCP Tool。

必须保持不变的核心：

- `src/brain/kernel/` 的文件事件总线与 `Circuit` 编排模式。
- `src/brain/nodes/topology.yaml` 中的认知管线语义：外部事件先进入 `inbox/pending/event_*.json`，再由文件流驱动后续节点。
- `src/brain/memory/` 的 L1/L2/L3 联合记忆。
- `heartbeat_generator`、`timer_scheduler` 等自持节律节点。

允许改造的范围：

- `src/platform/`
- `apps/`
- `src/brain/runtime.py`
- `src/brain/nodes/event_bridge.py`
- `src/brain/nodes/agents/externalizer.py`
- `src/brain/nodes/agents/internalizer.py`
- `src/brain/nodes/routers/command_dispatcher.py`
- `src/brain/kernel/node_factory.py`
- `src/brain/nodes/topology.yaml`
- `src/brain/localhost/commands/` 中依赖旧 `ApplicationHost` 的控制台命令
- 相关测试

不允许的做法：

- 不要手写一套“看起来像 MCP”的 JSON-RPC 协议替代官方 SDK。
- 不要让 App 继续依赖 `PlatformAPI` 再包装成 MCP Tool，这会把旧耦合带进新架构。
- 不要一次性删除旧 `ApplicationHost`。必须先提供兼容路径，等 MCP 路径测试通过后再清理。
- 不要让 MCP Server 直接读写 Brain 的 `data/kernel/` 文件。App 只能通过 MCP Tool 和 AMP notification 与平台交互。

---

## 1. 当前项目事实

当前平台层是进程内 App Host：

- `src/platform/application_host.py`
  - 管理 App 注册：`register()` / `replace_apps()` / `stop_all()`
  - 管理命令注册与派发：`register_command()` / `invoke_command()`
  - 管理事件队列：`emit_event()` / `drain_events()`
  - 管理轮询生命周期：`tick()`
- `src/platform/application_api.py`
  - 由 `ApplicationHost.register()` 注入到 App 的 `_bind(api)`。
  - App 用它发事件、注册动态命令、取 app data 目录。
- `src/platform/application_protocol.py`
  - 要求 App 实现 `manifest_path()`、`on_start()`、`on_stop()`、`on_tick()`。
- `src/platform/app_discovery.py`
  - 扫描 `apps/*/manifest.yaml` 与 `__init__.py`，再通过 Python import 实例化应用类。
- `src/platform/app_config.py`
  - 读取 `apps/config.yml`，目前只有 `enabled` 和 `startup`。
- `src/platform/manifest.py`
  - 只解析基础 manifest 字段和 `commands`。

当前 Brain 侧耦合点：

- `src/brain/runtime.py`
  - 启动时注册启用 App。
  - 启动 `run_app_loop()` 调 `host.tick()`。
  - 启动 `run_event_bridge(host, circuit, ...)`。
  - 注册内置控制台命令 `im.polaris.console.send_message`。
- `src/brain/nodes/event_bridge.py`
  - 定时 `host.drain_events()`，把 `AppEvent` 写为 `inbox/pending/event_*.json`。
- `src/brain/nodes/agents/externalizer.py`
  - 用 `_host.list_command_specs()` 拼命令文本。
  - 生成 `pipeline/action_queue/act_*.json`。
- `src/brain/nodes/routers/command_dispatcher.py`
  - 读取 action queue，再调用 `host.invoke_command()`。
- `src/brain/nodes/agents/internalizer.py`、`action_planner.py`、`polaris_agent.py`
  - 也有 `_build_commands_text()` 或旧命令调用逻辑，需要后续清理。
- `src/brain/localhost/commands/invoke.py`、`core.py`、`emit.py`、`say.py`
  - 依赖 `runtime.host` 的命令列表、命令调用、事件推送。

当前 App：

- `apps/aurora-app-diary`：低复杂度，适合作为第一个 MCP 化样板。
- `apps/aurora-app-clock`：有定时器和事件上报，适合作为第二个样板。
- `apps/aurora-app-weather`：有外部 HTTP 请求和可选事件上报，第三个迁移。
- `apps/aurora-app-qq`：绑定 NoneBot/OneBot 监听，最高风险，最后迁移。

---

## 2. 官方 MCP 约束

执行时以官方 MCP 规范为准：

- 最新规范入口：<https://modelcontextprotocol.io/specification/latest>
- 2026-06-19 核对时，`latest` 指向 `2025-11-25`。
- 架构：<https://modelcontextprotocol.io/specification/2025-11-25/architecture>
- 生命周期：<https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle>
- 传输：<https://modelcontextprotocol.io/specification/2025-11-25/basic/transports>
- Tools：<https://modelcontextprotocol.io/specification/2025-11-25/server/tools>
- Resources：<https://modelcontextprotocol.io/specification/2025-11-25/server/resources>
- Prompts：<https://modelcontextprotocol.io/specification/2025-11-25/server/prompts>
- Python SDK：<https://github.com/modelcontextprotocol/python-sdk>

本项目对 MCP 的落地解释：

- AuroraBot 主进程是 MCP Host。
- `src/platform/mcp_kit/client.py` 内的每个连接是一个 MCP Client。
- 每个 App 是独立 MCP Server。
- App 命令映射为 MCP Tools。
- App 事件映射为 MCP notifications，并使用 AMP envelope 约束 payload。
- 日记、配置、运行状态等只读上下文可以逐步映射为 MCP Resources。
- Prompt Templates 不是第一阶段目标，除非 App 本身确实提供可复用提示模板。

Python SDK 依赖策略：

- 先使用 SDK v1 稳定线：`mcp[cli]>=1.27,<2`。
- 不要在本次重构中追 v2 alpha，除非项目明确升级 SDK 策略。
- 使用 `uv add "mcp[cli]>=1.27,<2"` 更新 `pyproject.toml` 和 `uv.lock`。

---

## 3. 目标架构

目标模块结构：

```text
src/platform/
  mcp_kit/
    __init__.py
    server_spec.py        # MCPServerSpec 等配置模型
    manifest.py           # manifest 的 MCP 扩展读取
    discovery.py          # 扫描 App MCP Server
    server_kit.py         # 启停/重启/健康状态，不做 tools 派发
    client_manager.py     # MCP Client session 管理、tools/list、tools/call
    amp.py                # Aurora Message Protocol envelope
    tool_schema.py        # MCP Tool 到 LLM tool schema 的转换
  manifest.py             # 保留旧读取器，或薄封装新读取器
  app_config.py           # 扩展 mcp 配置
  app_discovery.py        # 迁移期兼容旧 App 扫描
  application_host.py     # 迁移期保留，最终删除或降级为 legacy
  application_api.py      # 迁移期保留，最终删除
  application_protocol.py # 迁移期保留，最终删除
  contracts.py            # 保留 AppEvent/CommandSpec 的兼容转换，最终瘦身
```

目标数据流：

```text
App MCP Server
  tools/list
  tools/call
  notifications/aurora/event
        |
        v
MCPClientManager
  - 缓存 tools
  - 调用 tools
  - 接收 notification
        |
        v
EventBridge
  AMP envelope -> FileUpdate
        |
        v
data/kernel/inbox/pending/event_*.json
        |
        v
Brain FileEventBus pipeline
```

迁移期双轨：

```text
旧轨：ApplicationHost -> CommandSpec/AppEvent -> command_dispatcher/event_bridge
新轨：MCPServerKit + MCPClientManager -> MCP Tool/AMP notification -> tool dispatcher/event_bridge
```

只有当新轨覆盖所有启用 App 且测试稳定后，才能删除旧轨。

---

## 4. 分阶段实施总览

推荐按 8 个阶段执行，每个阶段必须能独立提交和回滚。

| 阶段 | 目标 | 主要结果 |
| --- | --- | --- |
| Phase 0 | 建基线 | 测试基线、依赖策略、风险列表 |
| Phase 1 | 引入 MCP 基础设施 | `mcp_kit` 包、AMP 模型、配置模型 |
| Phase 2 | 实现 MCP Client/Server 管理 | 能启动样板 MCP Server、list/call tool |
| Phase 3 | 迁移 diary 样板 | 第一个 App 双入口运行 |
| Phase 4 | 接入 Brain 事件桥 | MCP notification 能进入文件总线 |
| Phase 5 | 接入 Tool 调用链 | Externalizer/控制台可调用 MCP Tool |
| Phase 6 | 逐个迁移 clock/weather/qq | 所有 App 都有 MCP Server 入口 |
| Phase 7 | 清理旧平台层 | 移除旧 Host/API/Protocol/command_dispatcher |

---

## 5. Phase 0：建基线

### 5.1 先运行基线检查

执行：

```powershell
uv run ruff check src/ tests/
uv run pyright src/
uv run pytest --cov=src
```

如果当前仓库已有失败项：

- 记录失败命令、失败测试名和关键错误。
- 不要在 MCP 重构提交中顺手修无关问题。
- 后续验收时必须区分“原有失败”和“本阶段新增失败”。

### 5.2 建立迁移日志

新建或更新：

```text
docs/reports/platform-native-mcp-progress.md
```

每阶段写入：

- 日期
- 改动摘要
- 运行过的验证命令
- 剩余风险
- 是否可回滚

### 5.3 搜索旧接口依赖

每次开始阶段前运行：

```powershell
rg -n "ApplicationHost|PlatformAPI|ApplicationProtocol|AppEvent|CommandSpec|invoke_command|list_command_specs|drain_events|command_dispatcher|action_queue" src tests apps
```

把结果按四类归档：

- 需要立即改
- 迁移期兼容保留
- 测试需要更新
- 旧代码最终删除

---

## 6. Phase 1：新增 MCP 基础设施

### 6.1 添加依赖

修改 `pyproject.toml`：

```toml
dependencies = [
    ...
    "mcp[cli]>=1.27,<2",
]
```

然后运行：

```powershell
uv sync --group dev
```

注意：如果下载失败，先确认是否是网络或镜像问题，不要手写 SDK stub。

### 6.2 新建 `src/platform/mcp_kit/`

新增文件：

```text
src/platform/mcp_kit/__init__.py
src/platform/mcp_kit/server_spec.py
src/platform/mcp_kit/amp.py
src/platform/mcp_kit/tool_schema.py
src/platform/mcp_kit/manifest.py
src/platform/mcp_kit/discovery.py
```

### 6.3 定义 `MCPServerSpec`

文件：`src/platform/mcp_kit/server_spec.py`

要求：

- 使用 `@dataclass(slots=True)`。
- 不使用裸 `Any` 作为公共 API 的核心类型；必要时局部兼容即可。
- 所有时间字段使用带时区的 ISO 8601 字符串。

建议字段：

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class MCPServerSpec:
    key: str
    package: str
    name: str
    version: str
    directory: Path
    transport: str = "stdio"
    command: list[str] = field(default_factory=list)
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    startup: dict[str, object] = field(default_factory=dict)
    health_timeout_seconds: float = 10.0
```

验收：

- `MCPServerSpec` 可以表达当前 `apps/config.yml` 的所有启动参数。
- `transport` 第一期只允许 `stdio`；遇到其他值要报清晰错误。

### 6.4 定义 AMP envelope

文件：`src/platform/mcp_kit/amp.py`

AMP 是 MCP notification 的 payload 规范，不是新传输协议。

必备 dataclass：

- `AMPSource`
- `AMPHeader`
- `AMPPayload`
- `AMPEnvelope`

必备函数：

- `build_event_envelope(...) -> AMPEnvelope`
- `parse_amp_envelope(raw: object) -> AMPEnvelope`
- `amp_to_file_event(envelope: AMPEnvelope) -> dict[str, object]`
- `legacy_app_event_to_amp(event: AppEvent) -> AMPEnvelope`

标准 envelope：

```json
{
  "header": {
    "protocol": "amp/1.0",
    "method": "aurora/event",
    "message_id": "uuid",
    "timestamp": "2026-06-19T12:00:00+08:00",
    "source": {
      "app": "im.polaris.qq",
      "instance": "default"
    }
  },
  "payload": {
    "type": "message.received",
    "session_id": "group_123456",
    "summary": "用户发来新消息",
    "data": {},
    "expire_at": null
  }
}
```

约束：

- `header.protocol` 固定为 `amp/1.0`。
- `header.method` 第一期只允许 `aurora/event`、`aurora/log`、`aurora/health`、`aurora/lifecycle`。
- `message_id` 用 `uuid.uuid4()` 即可；不要引入额外 UUID7 依赖。
- `timestamp` 使用项目已有 `src.utils.time_utils`，若该工具不带时区则先修工具或在 AMP 内部使用 `datetime.now(UTC).astimezone()`。
- 未知字段保留但不参与路由。
- 解析失败抛 `ValueError`，由接收层记录 WARNING。

### 6.5 Tool schema 转换

文件：`src/platform/mcp_kit/tool_schema.py`

必备函数：

- `mcp_tool_to_openai_tool(tool: object, *, server_name: str) -> dict[str, object]`
- `mcp_tools_to_prompt_text(tools: Sequence[object]) -> str`
- `normalize_tool_name(server_name: str, tool_name: str) -> str`

命名规则：

- 对外暴露给 LLM 的工具名必须全局唯一。
- 优先使用 manifest package 前缀：`im.polaris.weather.get_weather`。
- 如果 MCP Server 返回的 tool 已经带 package 前缀，不重复添加。
- 如果出现同名冲突，启动阶段直接失败，不允许静默覆盖。

验收：

- 能把旧 `CommandSpec` 的命令文本表达能力完整映射到 MCP Tool schema。
- Externalizer 迁移前可以继续使用 prompt text；后续再切到结构化 tool calling。

---

## 7. Phase 2：MCP ServerKit 与 ClientManager

### 7.1 实现发现逻辑

文件：`src/platform/mcp_kit/discovery.py`

职责：

- 扫描 `apps/*/manifest.yaml`。
- 支持旧 App：没有 `type: mcp-server` 时仍返回 legacy 信息，但不强制启动 MCP。
- 支持新 App：有 `type: mcp-server` 或 `mcp:` 段时构造 `MCPServerSpec`。
- 合并 `apps/config.yml` 的 `enabled`、`startup`、`mcp` 覆盖项。

建议 `apps/config.yml` 新格式：

```yaml
apps:
  aurora-app-diary:
    enabled: true
    startup: {}
    mcp:
      enabled: true
      transport: stdio
      command: ["uv", "run", "python", "-m", "apps.aurora-app-diary.mcp_server"]
      env: {}
      health_timeout_seconds: 10.0
```

兼容规则：

- 未配置 `mcp` 的 App 继续走旧 Host。
- 配置了 `mcp.enabled: true` 但缺少 `mcp_server.py`，启动时报错。
- 配置了 `mcp.enabled: false` 时，即使 manifest 有 `mcp:` 也不启动新轨。

### 7.2 实现 `MCPServerKit`

文件：`src/platform/mcp_kit/server_kit.py`

职责只限进程生命周期：

- `load_specs()`
- `start_all()`
- `start_one(key)`
- `stop_all()`
- `stop_one(key)`
- `restart_one(key)`
- `health_report()`

不要做：

- 不要在 `ServerKit` 里保存 tools。
- 不要在 `ServerKit` 里实现 `call_tool()`。
- 不要在 `ServerKit` 里转换 notification。

实现要求：

- 使用 `asyncio.create_subprocess_exec(*command, cwd=..., env=...)`。
- stdout/stdin 必须留给 MCP transport 使用。
- stderr 可以采集到日志，注意不要误判 stderr 为启动失败。
- stop 顺序：关闭 stdin 或终止进程，等待超时，最后 kill。
- 不要每 tick 重启；只在进程退出或显式 restart 时处理。

### 7.3 实现 `MCPClientManager`

文件：`src/platform/mcp_kit/client_manager.py`

职责：

- 连接每个 MCP Server。
- 执行 MCP lifecycle：`initialize` -> `notifications/initialized`。
- 缓存 `tools/list`。
- 提供 `call_tool(full_tool_name, arguments)`。
- 接收 MCP notifications，转发给注册的 handler。
- 暴露 `tools_as_openai_schema()` 和 `tools_as_prompt_text()`。

关键接口：

```python
class MCPClientManager:
    async def connect_all(self) -> None: ...
    async def connect_one(self, spec: MCPServerSpec) -> None: ...
    async def refresh_tools(self) -> None: ...
    async def list_tools(self) -> list[object]: ...
    async def call_tool(self, full_tool_name: str, arguments: dict[str, object]) -> object: ...
    def add_notification_handler(self, method: str, handler: NotificationHandler) -> None: ...
    async def shutdown(self) -> None: ...
```

设计要求：

- 每个 MCP Server 一个独立 session。
- session 之间隔离，不共享 conversation。
- tool cache 必须带 server key/package。
- `tools/list_changed` notification 到达时刷新对应 server 的 tools。
- 调用超时必须可配置，默认 30 秒。
- MCP 错误要转换为项目内清晰异常，例如 `MCPToolCallError`。

测试样板：

- 用一个测试 MCP Server 暴露 `echo` tool。
- `connect_all()` 后能 list 到 `im.polaris.test.echo`。
- `call_tool()` 能返回 echo 结果。
- Server 退出后 `health_report()` 能发现异常。

---

## 8. Phase 3：迁移 diary 为样板 App

先迁移 `apps/aurora-app-diary`，因为它依赖少、风险低。

### 8.1 拆业务逻辑

新增：

```text
apps/aurora-app-diary/service.py
```

把 `runtime.py` 中读写日记文件的逻辑迁到 `DiaryService`。

要求：

- `service.py` 不 import `PlatformAPI`。
- `service.py` 不 import MCP SDK。
- `service.py` 可单独单测。
- 保留当前 app data 目录行为；如果旧目录来自 `PlatformAPI.data_dir`，新 service 需要从启动参数或环境变量获得 data dir。

### 8.2 新增 MCP Server 入口

新增：

```text
apps/aurora-app-diary/mcp_server.py
```

推荐使用 FastMCP v1 风格：

```python
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .service import DiaryService

mcp = FastMCP("aurora-diary", json_response=True)
service = DiaryService.from_env()


@mcp.tool(name="write_diary")
async def write_diary(date: str, content: str) -> dict[str, object]:
    return await service.write_diary(date=date, content=content)


@mcp.tool(name="read_diary")
async def read_diary(date: str) -> dict[str, object]:
    return await service.read_diary(date=date)


@mcp.tool(name="list_dates")
async def list_dates() -> dict[str, object]:
    return await service.list_dates()


if __name__ == "__main__":
    mcp.run(transport="stdio")
```

注意：

- `stdout` 只能输出 MCP JSON-RPC 消息。
- 普通日志必须走 stderr 或项目日志文件。
- 工具返回值必须 JSON 可序列化。

### 8.3 保留旧 `runtime.py`

迁移期不要删除 `runtime.py`。

把旧 `DiaryApplication` 改成薄兼容层：

- `_bind(api)` 继续保存旧 API。
- command 方法调用 `DiaryService`。
- 事件上报仍可通过旧 `PlatformAPI.emit_event()`。

验收：

- 旧测试 `test_application_host*` 仍通过。
- 新 MCP 测试通过。
- 手动运行 diary MCP Server，不向 stdout 打非 MCP 文本。

---

## 9. Phase 4：MCP notification 接入 EventBridge

### 9.1 修改 `event_bridge`

目标：支持旧 Host 和新 MCP notification 双来源。

不要立即删除旧签名。先新增并行函数：

```python
async def run_mcp_event_bridge(
    client_manager: MCPClientManager,
    circuit: Circuit,
    stop_event: asyncio.Event,
) -> None:
    ...
```

行为：

- 注册 `aurora/event` handler。
- handler 把 AMP envelope 放进 `asyncio.Queue`。
- bridge 循环从 queue 取消息，写入 `inbox/pending/event_<type>_<message_id>.json`。
- 文件内容保存完整 AMP envelope。

文件名规则：

```text
inbox/pending/event_<payload.type with . and / replaced by _>_<header.message_id>.json
```

兼容转换：

- 旧 `AppEvent.to_dict()` 是扁平结构。
- 新 AMP 是 `header` + `payload`。
- `message_preprocessor` 如果只支持旧扁平结构，需要先扩展它同时识别两种格式。

### 9.2 扩展 `message_preprocessor`

文件：`src/brain/nodes/routers/message_preprocessor.py`

要求：

- 读取旧事件时保持当前行为。
- 读取 AMP envelope 时从：
  - `payload.type`
  - `payload.session_id`
  - `payload.summary`
  - `payload.data`
  - `header.source.app`
  提取等价字段。
- 不要把 AMP header 丢掉；写入后续 message queue 时保留 trace 字段。

验收：

- 构造一个 `aurora/event` notification，最终能生成 `pipeline/message_queue/*.json`。
- 旧 `host.emit_event(AppEvent(...))` 仍能进入同一管线。

---

## 10. Phase 5：MCP Tool 调用链

这个阶段要谨慎：先让旧 action_queue 继续存在，再逐步减少文本 JSON 动作依赖。

### 10.1 新增 Tool Dispatcher 适配层

新增：

```text
src/brain/nodes/routers/mcp_tool_dispatcher.py
```

第一步可以让它替代旧 `command_dispatcher` 的执行部分，但仍读取 `pipeline/action_queue/*.json`：

- 解析 `actions[].command`。
- 如果 command 对应 MCP tool，调用 `MCPClientManager.call_tool()`。
- 如果 command 只存在旧 Host，调用旧 `host.invoke_command()`。
- 记录执行结果到 `pipeline/action_queue/done/` 或 `pipeline/tool_results/`。

这样可以先保留 Externalizer 的 JSON 输出格式，降低一次性切换风险。

### 10.2 修改 Externalizer 的命令上下文来源

文件：`src/brain/nodes/agents/externalizer.py`

迁移期策略：

- 如果注入了 `MCPClientManager`，优先使用 `client_manager.tools_as_prompt_text()`。
- 否则回退到旧 `_host.list_command_specs()`。

不要在这一步强制改成模型原生 tool_calls，因为当前 `gateway` 可能仍只包装文本补全。先把工具来源标准化，后续再改 LLM gateway。

### 10.3 后续切换为原生 tool_calls

当 `src/brain/ai/gateway.py` 支持结构化 tools 后，再做：

- Externalizer 调用 LLM 时传入 MCP tools schema。
- LLM 返回 tool_calls。
- `mcp_tool_dispatcher` 或 Externalizer 直接执行 tool_calls。
- action_queue 文件可以改为审计记录，而不是派发必经队列。

验收：

- `im.polaris.diary.write_diary` 可以经 Externalizer 生成动作并由 MCP 调用成功。
- `im.polaris.console.send_message` 旧内置命令仍可用，直到它也被迁到 MCP 或专门的 internal tool registry。

---

## 11. Phase 6：迁移其余 App

### 11.1 clock

目标：

- `service.py` 管理闹钟/计时器状态。
- `mcp_server.py` 暴露：
  - `get_current_time`
  - `set_alarm`
  - `set_timer`
  - `list_alarms`
- 到时提醒通过 `aurora/event` notification 发出 `alarm.triggered` 或 `timer.triggered`。

注意：

- 旧 `on_tick()` 轮询要改为 server 内部后台 task。
- FastMCP lifespan 或 server 启动逻辑里创建后台任务。
- shutdown 时取消任务并保存状态。

验收：

- `set_timer("1")` 后 1 秒左右收到 `timer.triggered` AMP notification。
- notification 能进入 `inbox/pending`。

### 11.2 weather

目标：

- `service.py` 管理城市别名、HTTP 请求、格式化。
- `mcp_server.py` 暴露 `get_weather`。
- `emit_event` 仍作为 tool 参数兼容，但默认行为由启动配置控制。

注意：

- 外部 HTTP timeout 保持当前 `request_timeout_seconds`。
- 不要在 MCP tool 里直接吞异常；返回 `{ok: false, error: "..."}`，同时 DEBUG 记录异常细节。

验收：

- 默认城市北京可查询。
- 参数 `emit_event=true` 时发送 `weather.reported`。
- HTTP 失败时不会导致 MCP Server 进程退出。

### 11.3 qq

这是最高风险项，最后做。

目标：

- 发送能力暴露为 tools：
  - `send_qq_message`
  - `send_qq_private_message`
  - `at_user_in_group`
- 接收消息转为 `aurora/event` notification：
  - `message.received`

建议策略：

- 第一步保留 NoneBot plugin 在主进程内，只把发送命令 MCP 化。
- 第二步再评估 QQ App 是否需要独立进程。如果 NoneBot driver 强绑定主进程，则允许 QQ App 作为“in-process MCP server adapter”存在，但接口仍必须是 MCP Tool/notification。
- 不要为了追求独立进程破坏 NoneBot 的生命周期。

验收：

- 群消息接收仍能进入 `inbox/pending`。
- 私聊和群聊发送工具能正确调用 OneBot API。
- 发送失败有结构化错误，不让 Externalizer 误以为已发送。

---

## 12. Phase 7：清理旧平台层

只有满足以下条件后才能进入清理：

- 所有启用 App 都有 MCP Server 或明确的 in-process MCP adapter。
- `MCPClientManager.list_tools()` 覆盖旧 `host.list_command_specs()` 的全部命令。
- `run_mcp_event_bridge()` 覆盖旧 `run_event_bridge(host, ...)` 的事件输入。
- 控制台命令不再强依赖 `runtime.host.invoke_command()`。
- 测试覆盖新路径。

清理顺序：

1. `src/brain/runtime.py`
   - `RuntimeState` 从 `host` 改为 `server_kit` + `client_manager`。
   - 删除 `run_app_loop()` 启动。
   - 删除旧 `register_enabled_apps()` 路径。
2. `src/brain/nodes/topology.yaml`
   - 移除 `command_dispatcher`。
   - 如果 `mcp_tool_dispatcher` 已不需要 action_queue，也一起移除对应边。
3. `src/brain/kernel/node_factory.py`
   - 移除 `command_dispatcher` registry。
   - 去掉对 `ApplicationHost` 的必需注入；保留可选 context 对象。
4. `src/platform/application_api.py`
   - 删除。
5. `src/platform/application_protocol.py`
   - 删除。
6. `src/platform/loop.py`
   - 删除。
7. `src/platform/application_host.py`
   - 删除，或移动到 `src/platform/legacy/application_host.py` 只供旧测试参考。
8. `src/platform/contracts.py`
   - 删除 `CommandSpec`。
   - `AppEvent` 若仍用于测试 fixture，移动到 AMP 兼容模块。
9. `apps/*/runtime.py`
   - 删除或改为导入 `mcp_server.py` 的兼容 shim。
10. tests
   - 删除旧 Host 行为测试。
   - 新增 MCP lifecycle、tools、notification、Brain bridge 集成测试。

---

## 13. 测试要求

### 13.1 单元测试

新增测试文件建议：

```text
tests/test_mcp_amp.py
tests/test_mcp_discovery.py
tests/test_mcp_server_kit.py
tests/test_mcp_client_manager.py
tests/test_mcp_event_bridge.py
tests/test_mcp_tool_dispatcher.py
```

覆盖点：

- AMP envelope 序列化/解析。
- 旧 `AppEvent` 到 AMP 的转换。
- manifest + config 合并。
- tool name 前缀和冲突检测。
- MCP Server 启停和健康状态。
- tools/list 缓存刷新。
- tools/call 成功与失败。
- notification 写入 FileEventBus。

### 13.2 集成测试

新增一个测试 MCP App fixture：

```text
tests/fixtures/mcp_echo_server.py
```

它必须：

- 暴露 `echo` tool。
- 支持发送 `aurora/event` notification。
- 能模拟延迟、错误和进程退出。

集成场景：

- Runtime 启动后连接 echo server。
- Externalizer 或 dispatcher 能调用 echo tool。
- echo server 发 notification 后，`inbox/pending/event_*.json` 被写入。

### 13.3 验证命令

每阶段至少运行：

```powershell
uv run ruff check src/ tests/
uv run pyright src/
uv run pytest tests/test_mcp_amp.py tests/test_mcp_discovery.py
```

涉及 runtime 或 Brain 管线时运行：

```powershell
uv run pytest tests/test_runtime.py tests/test_gamma_integration.py tests/test_mcp_event_bridge.py
```

完成阶段后运行全量：

```powershell
uv run pytest --cov=src
```

---

## 14. 代码风格约束

必须遵守仓库现有规则：

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

## 15. DeepSeek 执行守则

每次执行任务时按这个顺序：

1. 先读本文件和 `docs/reports/app-platform-mcp-migration.md`。
2. 运行 `rg` 确认当前旧接口依赖，不要只凭文档假设。
3. 一次只做一个 Phase 或一个 App。
4. 新增新路径时保留旧路径。
5. 新路径测试通过后再迁移调用方。
6. 所有删除动作必须发生在 Phase 7。
7. 每个提交都要有测试或至少有明确的未运行原因。
8. 不要引入新全局单例，除非与现有 `get_app_host()` 风格兼容并有懒加载理由。
9. 不要在 App 的 MCP Server 中读取 Brain 内部文件。
10. 不要把 notification 当作可靠命令调用；有副作用的动作必须走 tools/call。
11. 对 QQ App 保守处理，优先 in-process adapter，确认 NoneBot 生命周期后再独立进程化。
12. 每阶段结束更新 `docs/reports/platform-native-mcp-progress.md`。

---

## 16. 阶段验收总表

| 阶段 | 必须证明 |
| --- | --- |
| Phase 0 | 已记录基线测试结果和旧接口依赖 |
| Phase 1 | `mcp_kit` 基础模型有单测，ruff/pyright 通过 |
| Phase 2 | 测试 MCP Server 可启动、连接、list tools、call tool |
| Phase 3 | diary 旧入口和 MCP 入口都可用 |
| Phase 4 | MCP notification 能写入 `inbox/pending/event_*.json` |
| Phase 5 | Externalizer/dispatcher 能调用至少一个 MCP Tool |
| Phase 6 | clock/weather/qq 的 MCP 入口覆盖旧命令能力 |
| Phase 7 | 旧 `ApplicationHost`/`PlatformAPI`/`command_dispatcher` 被删除或 legacy 化，全量测试通过 |

---

## 17. 最终完成定义

本重构完成时，项目应满足：

- `apps/config.yml` 能声明 MCP Server 启动方式。
- `src/platform/mcp_kit/` 是平台层主入口。
- App 命令不再通过 `CommandSpec` 注册，而是通过 MCP `tools/list` 暴露。
- App 命令执行不再通过 `ApplicationHost.invoke_command()`，而是通过 MCP `tools/call`。
- App 事件不再通过 `ApplicationHost.emit_event()` 队列，而是通过 `aurora/event` notification + AMP envelope。
- Brain 仍然只通过文件总线消费外部事件。
- `command_dispatcher` 不再是必要节点。
- QQ、weather、clock、diary 都能以 MCP 方式运行。
- CI 命令通过：

```powershell
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run pyright src/
uv run pytest --cov=src
```

