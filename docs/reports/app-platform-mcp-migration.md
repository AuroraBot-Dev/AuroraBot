# AuroraBot App & Platform 层 MCP 迁移研究报告

> **范围界定**：本次迁移仅涉及 `src/platform/` 和 `apps/` 两层。Brain 核心（FileEventBus、认知管线、记忆系统、节律环路）保持现有架构不变——它们承载着 AuroraBot 的核心设计哲学（文件驱动、异步图计算、可追溯），不应被 MCP 的同步 request/response 模式约束。
>
> 日期：2026-06-14

---

## 目录

1. [背景与动机](#1-背景与动机)
2. [当前架构回顾](#2-当前架构回顾)
3. [目标架构](#3-目标架构)
4. [Platform 层重塑：App 宿主 → MCP Server Kit](#4-platform-层重塑app-宿主--mcp-server-kit)
5. [Aurora 消息协议（AMP）](#5-aurora-消息协议amp)
6. [App 迁移方案](#6-app-迁移方案)
7. [实施路径](#7-实施路径)
8. [风险与缓解](#8-风险与缓解)
9. [总结](#9-总结)

---

## 1. 背景与动机

### 1.1 为什么不做 Brain MCP 化

在早期的 Skill 化和 MCP 化讨论中，都出现过"把认知节点也纳入统一协议"的设想。但这是错误的：

- **FileEventBus 是核心差异点**。文件驱动让每个中间状态可追溯、可回滚、可独立调试。MCP 的同步 RPC 语义完全违背这一设计——把 `internalizer` 改成 MCP Tool 意味着"等待 LLM 返回才能继续"，丢失了异步流图的所有好处。
- **转义者（Internalizer/Externalizer）是认知管线，不是工具**。它们是 B↔A 的语义转换器，不是"被调用的能力"。强行 Tool 化会扭曲它们的角色。
- **节律系统不是服务**。HeartbeatGenerator 的自持振荡回路在 MCP 中没有对应物——它不需要"被调用"，它自己就是时钟。

**因此，本次迁移的明确边界是：App 和 Platform 层。Brain 保持不变。**

### 1.2 Platform 层的问题

当前 `src/platform/` 承担了一个杂糅的角色：

| 职责 | 当前实现 | 问题 |
|------|---------|------|
| App 注册与管理 | `ApplicationHost.register()` | 紧耦合——App 必须在同一进程 |
| 命令注册与派发 | `ApplicationHost.register_command()` / `invoke_command()` | 自定义协议，无标准化 |
| 事件队列 | `ApplicationHost.emit_event()` / `drain_events()` | 单向推送，无类型约束 |
| App 发现 | `app_discovery.py` 扫描 `apps/` 目录 | 强依赖文件系统布局 |
| App 生命周期 | `ApplicationHost.tick()` → `on_tick()` | 轮询驱动，无异步通知 |

核心痛点：**ApplicationHost 既管理 App 生命周期，又管理命令派发，又管理事件路由**——三个正交的职责耦合在一起，且使用完全自定义的协议。

### 1.3 MCP 的契合点

MCP 协议天然解决了其中的两个核心问题：

- **Tools** → 命令注册与派发（已高度对齐，`CommandSpec` ≈ `Tool`）
- **Notifications** → 事件系统（App → Brain 的异步上报）

唯一需要扩展的是：MCP 的通知是结构自由、无类型约束的。我们需要在 MCP notification 基础上定义一套 Aurora 自己的消息 envelope 规范。

---

## 2. 当前架构回顾

### 2.1 Platform 模块全景

```
src/platform/
├── application_host.py     ← 核心：App 注册、命令注册/派发、事件队列、tick 循环
├── application_api.py      ← PlatformAPI：App 反向调用宿主的桥梁
├── application_protocol.py ← ApplicationProtocol：App 必须遵守的接口协议
├── app_config.py           ← 加载 apps/config.yml，启用/禁用/启动参数
├── app_discovery.py        ← 扫描 apps/ 目录，发现 manifest.yaml
├── contracts.py            ← AppEvent, CommandSpec 数据类
├── manifest.py             ← manifest.yaml 解析器 + CommandDecl
└── loop.py                 ← run_app_loop()：定时调用 host.tick()
```

### 2.2 关键数据流

```
┌─────────────────────────────────────────────┐
│                  ApplicationHost             │
│                                              │
│  ┌──────────────┐  ┌──────────────────────┐ │
│  │  _apps dict  │  │   _commands dict     │ │
│  │  {pkg→App}   │  │   {name→CommandSpec} │ │
│  └──────┬───────┘  └──────────┬───────────┘ │
│         │                     │              │
│  ┌──────┴─────────────────────┴───────────┐ │
│  │            _events deque               │ │
│  └────────────────────────────────────────┘ │
└─────────────────────────────────────────────┘
        ▲                    │
        │ register()         ▼ invoke_command()
   ┌────┴─────┐         ┌────────┐
   │  App A   │         │ Brain  │
   │ (QQ)     │         │ Nodes  │
   └──────────┘         └────────┘
        │                    ▲
        └── emit_event() ────┘
            (EventBridge drains events)
```

### 2.3 App 结构（以 weather 为例）

```
apps/aurora-app-weather/
├── __init__.py         ← 空文件，标记为 Python 包
├── manifest.yaml       ← package, commands 声明
├── runtime.py          ← WeatherApplication 类
├── config.example.json ← 启动参数示例
├── assets/             ← 静态资源
├── README.md
└── LICENSE
```

`manifest.yaml` → `runtime.py` 的绑定关系：

```yaml
# manifest.yaml
package: im.polaris.weather
commands:
  - name: get_weather        # 必须对应 WeatherApplication 的 get_weather 方法
```

```python
# runtime.py
class WeatherApplication:
    def _bind(self, api: PlatformAPI) -> None: ...   # 获取 PlatformAPI 引用
    def manifest_path(self) -> Path: ...              # 返回 manifest.yaml 路径
    async def on_start(self) -> None: ...
    async def on_stop(self) -> None: ...
    async def on_tick(self) -> None: ...
    async def get_weather(self, city, days, ...) -> dict: ...  # 命令实现
```

---

## 3. 目标架构

### 3.1 整体拓扑

```
┌──────────────────────────────────────────────────────────┐
│                     Brain Kernel (不变)                   │
│                                                          │
│  FileEventBus → Cognitive Pipeline → Memory System       │
│       ▲                                        │         │
│       │  文件事件                               │ MCP     │
│       │                                        ▼ Client  │
│  ┌────┴──────────────────────────────────────────────┐   │
│  │              MCP Client Manager                    │   │
│  │  - 管理所有 MCP Server 连接                        │   │
│  │  - tools/list → 注入 LLM context                  │   │
│  │  - tools/call → dispatch tool_calls               │   │
│  │  - notifications ← 从 MCP Server 接收事件          │   │
│  └──┬───────┬───────┬───────┬────────────────────────┘   │
└─────┼───────┼───────┼───────┼────────────────────────────┘
      │       │       │       │
      │ stdio │ stdio │ stdio │ stdio  (独立进程)
      ▼       ▼       ▼       ▼
┌─────────┐ ┌───────┐ ┌───────┐ ┌───────┐
│QQ MCP   │ │Weather│ │Clock  │ │Diary  │
│Server   │ │MCP Svr│ │MCP Svr│ │MCP Svr│
└─────────┘ └───────┘ └───────┘ └───────┘
      ▲
      │ OneBot V11 (NoneBot)
══════╪════════════════════════════════════
      │  QQ 协议层 (外部)
```

**核心变化：**
- `ApplicationHost` → 拆分为 `MCPServerKit`（管理 MCP Server 进程生命周期）+ `MCPClientManager`（在 Brain 侧管理连接）
- `PlatformAPI` → 消失。App 不再需要反向引用宿主——它们就是独立的 MCP Server
- `command_dispatcher` Router 节点 → 移除。Brain 直接通过 MCP Client 的 `tools/call` 执行命令
- EventBridge → 保留，但改为接收 MCP notification 并转为文件事件

### 3.2 与两套旧方案的差异

| 维度 | Skill 化方案 | 旧 MCP 方案 | **本方案** |
|------|------------|-----------|----------|
| Brain 改造 | 全部 Skill 化 | 部分 MCP 化 | **不改造** |
| App 改造 | Skill 化 | MCP Server | **MCP Server** |
| Platform | SkillRuntime | 简化 ApplicationHost | **MCPServerKit 包** |
| 消息协议 | 自定义 | MCP 原生 | **AMP（MCP notification 扩展）** |
| 侵入性 | 高（改 ~20 个类） | 中（改 ~10 个类） | **低（改 ~6 个类）** |

---

## 4. Platform 层重塑：App 宿主 → MCP Server Kit

### 4.1 新模块结构

```
src/platform/                         →  src/platform/
├── application_host.py               →  └── mcp_kit/
├── application_api.py       (移除)       ├── server_kit.py    ← MCP Server 生命周期管理
├── application_protocol.py  (移除)       ├── client.py        ← MCP Client Manager (Brain 侧)
├── app_config.py            (改造)       ├── discovery.py     ← 从扫描 runtime.py 改为扫描 MCP 配置
├── app_discovery.py         (改造)       ├── protocol.py      ← AMP 消息协议 (notification 扩展)
├── contracts.py             (改造)       └── manifest.py      ← manifest.yaml 兼容读取 (简化)
├── manifest.py              (保留)
└── loop.py                  (移除)
```

### 4.2 ServerKit：MCP Server 进程管理器

替代原 `ApplicationHost` 的 App 生命周期管理职责。

```python
# src/platform/mcp_kit/server_kit.py
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine


@dataclass(slots=True)
class MCPServerSpec:
    """MCP Server 的完整描述。

    由 manifest.yaml + apps/config.yml 合并得出。"""
    name: str                              # aurora-app-weather
    package: str                           # im.polaris.weather
    transport: str = "stdio"               # stdio (一期), sse (二期)
    command: list[str] = field(default_factory=list)  # ["uv", "run", "python", "mcp_server.py"]
    cwd: str | None = None                 # 工作目录
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True


class MCPServerKit:
    """MCP Server 进程生命周期管理器。

    替代旧的 ApplicationHost 的 register/stop/tick 职责。
    不再负责命令注册和派发——这些由 MCP Client 通过 tools/list 动态发现。

    Usage::

        kit = MCPServerKit()
        await kit.load_specs_from_config()
        await kit.start_all()
        ...
        await kit.stop_all()
    """

    def __init__(self) -> None:
        self._specs: dict[str, MCPServerSpec] = {}     # name → spec
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._health_tasks: dict[str, asyncio.Task[None]] = {}

    async def load_specs_from_config(self) -> list[MCPServerSpec]:
        """从 apps/config.yml + 各 App 的 manifest.yaml 加载所有 Server 配置。"""
        ...

    async def start_all(self) -> None:
        """启动所有 enabled 的 MCP Server 进程。"""
        ...

    async def start_one(self, name: str) -> asyncio.subprocess.Process:
        """启动单个 MCP Server（stdio transport），返回子进程句柄。"""
        ...

    async def stop_all(self) -> None:
        """按逆序停止所有 MCP Server。"""
        ...

    async def stop_one(self, name: str) -> None:
        """优雅停止单个 Server（发送 SIGTERM，超时后 SIGKILL）。"""
        ...

    async def restart_one(self, name: str) -> asyncio.subprocess.Process:
        """重启单个 Server（用于配置热更新后的 reload）。"""
        ...

    def health_report(self) -> dict[str, str]:
        """返回所有 Server 的健康状态。"""
        ...

    # ── 事件通道 ──
    # ServerKit 不直接暴露 AppEvent 队列 ——
    # 事件通过 MCP notification 走 MCPClientManager 的通道
```

### 4.3 MCPClientManager：Brain 侧的连接管理

```python
# src/platform/mcp_kit/client.py
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from mcp.client.stdio import stdio_client
from mcp.types import Tool

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine


@dataclass(slots=True)
class ClientConnection:
    """单个 MCP Server 的客户端连接。"""
    name: str
    tools: list[Tool]
    _session: Any  # mcp.ClientSession


class MCPClientManager:
    """Brain 侧的 MCP 客户端管理器。

    负责：
    - 建立与所有 MCP Server 的连接
    - 维护 tools 列表缓存
    - 执行 tools/call
    - 接收 notifications 并桥接到 EventBridge
    - 连接健康监控

    Usage::

        mgr = MCPClientManager(server_kit)
        await mgr.connect_all()
        await mgr.list_all_tools()
        result = await mgr.call_tool("get_weather", {"city": "北京"})
        await mgr.shutdown()
    """

    def __init__(self, server_kit: "MCPServerKit") -> None:
        self._kit = server_kit
        self._connections: dict[str, ClientConnection] = {}
        self._notification_handlers: dict[str, list[Callable[[str, dict], Coroutine[None, None, None]]]] = {}

    # ── 连接管理 ──

    async def connect_all(self) -> None:
        """为所有已启动的 MCP Server 建立连接。"""
        ...

    async def connect_one(self, name: str, process: asyncio.subprocess.Process) -> None:
        """通过 stdio transport 连接到单个 MCP Server。"""
        async with stdio_client(process.stdin, process.stdout) as (read, write):
            session = await self._init_session(read, write)
            tools = await session.list_tools()
            self._connections[name] = ClientConnection(name=name, tools=tools, _session=session)

    # ── Tool 操作 ──

    async def list_all_tools(self) -> list[Tool]:
        """返回所有已连接 Server 的工具列表。"""
        ...

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """调用指定工具。自动定位到对应的 MCP Server。

        使用 LPM (Longest Prefix Match) 规则：工具名可能带 package 前缀，
        如 ``im.polaris.weather.get_weather``。
        """
        ...

    def tools_as_openai_schema(self) -> list[dict[str, Any]]:
        """将所有工具转换为 OpenAI function calling 格式。

        供 Internalizer/Externalizer 注入 LLM context 使用。
        """
        ...

    # ── 事件接收 ──

    def on_notification(
        self, method: str, handler: Callable[[str, dict], Coroutine[None, None, None]]
    ) -> None:
        """注册 notification 处理器。

        支持的 method：
        - ``aurora/event`` → App 向 Brain 上报事件
        - ``aurora/log``   → App 日志流
        - ``notifications/initialized`` → 连接就绪信号
        """
        ...

    async def _dispatch_notification(self, server_name: str, method: str, params: dict) -> None:
        """将收到的 notification 分发给注册的处理器。"""
        ...

    # ── 生命周期 ──

    async def shutdown(self) -> None:
        """关闭所有连接。"""
        ...
```

### 4.4 可移除的模块

| 原模块 | 处置 |
|--------|------|
| `application_api.py` (PlatformAPI) | **移除**。MCP Server 不需要反向引用宿主——工具调用由 MCP Client 走 stdio |
| `application_protocol.py` | **移除**。App 不再实现 `ApplicationProtocol`，改为 MCP Server 接口 |
| `loop.py` (run_app_loop) | **移除**。不再需要定时 tick 轮询 |
| `command_dispatcher` (Brain Router) | **移除**。Brain 通过 `MCPClientManager.call_tool()` 直接执行 |
| `_build_commands_text()` ×3 | **移除**。改为 `mgr.tools_as_openai_schema()` 统一注入 |

### 4.5 保留并改造的模块

| 原模块 | 改造 |
|--------|------|
| `contracts.py` | AppEvent 数据结构保留，但承载层从 Python dataclass 变更为 AMP notification payload |
| `manifest.py` | 保留 manifest.yaml 读取，但 `commands` 部分变为可选（工具声明由 MCP Server 的 `list_tools` 动态提供） |
| `app_config.py` | 保留配置加载，新增 MCP Server 进程配置字段（transport, command, env, health_timeout） |
| `app_discovery.py` | 从"扫描 runtime.py + 导入类"改为"扫描 mcp_server.py + 读取 manifest.yaml" |

---

## 5. Aurora 消息协议（AMP）

### 5.1 设计目标

MCP 协议的 `notifications` 机制提供了基本的异步推送通道，但方法名和 payload 结构完全由实现方定义，缺乏类型约束和互操作性保证。

AMP（Aurora Message Protocol）是对 MCP notification 的语义扩展——**定义在 MCP notification 通道上承载的消息类型、envelope 结构和路由规则**。它不是新协议，是 MCP notification 的类型化应用层。

### 5.2 Notification 方法命名空间

```
aurora/event          → 应用事件（原 AppEvent，App → Brain）
aurora/event/ack      → 事件确认（Brain → App）
aurora/command/invoke → 命令调用请求（Brain → App，使用 tools/call 替代，推荐）
aurora/log            → 应用日志流（App → Brain）
aurora/health         → 健康检查响应（App → Brain）
aurora/lifecycle      → 生命周期事件（started, stopping, crashed）
```

### 5.3 核心 Envelope 结构

所有 AMP 消息共享统一的 envelope，对齐原 `AppEvent` 的字段：

```json
{
  "header": {
    "protocol": "amp/1.0",
    "method": "aurora/event",
    "message_id": "uuid",
    "timestamp": "2026-06-14T12:00:00+08:00",
    "source": {
      "app": "im.polaris.qq",
      "instance": "qq-server-01"
    }
  },
  "payload": {
    "type": "message.received",
    "session_id": "group_123456",
    "summary": "用户 @小明 问：'今天天气怎么样'",
    "data": {
      "user_id": "987654",
      "group_id": "123456",
      "message_text": "今天天气怎么样",
      "is_group": true
    },
    "expire_at": "2026-06-14T12:05:00+08:00"
  }
}
```

**字段语义：**

| 路径 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `header.protocol` | string | 是 | 固定 `"amp/1.0"` |
| `header.method` | string | 是 | MCP notification method |
| `header.message_id` | string | 是 | UUID7（时间有序），用于去重和回溯 |
| `header.timestamp` | string | 是 | ISO 8601 + 时区 |
| `header.source.app` | string | 是 | 原 `AppEvent.source` |
| `header.source.instance` | string | 否 | 多实例时的实例标识 |
| `payload.type` | string | 是 | 事件类型，点分隔命名，如 `"message.received"` |
| `payload.session_id` | string | 否 | 会话标识 |
| `payload.summary` | string | 否 | 人类可读摘要 |
| `payload.data` | object | 否 | 类型相关的结构化数据 |
| `payload.expire_at` | string | 否 | 过期时间，事件不再有效 |

### 5.4 入站事件类型（App → Brain）

```
message.received      ← 接收到新消息（用户发言）
message.reaction      ← 消息被回应/表情
session.created       ← 新会话建立
session.closed        ← 会话关闭
alarm.triggered       ← 闹钟触发 (aurora-app-clock)
timer.triggered       ← 倒计时触发 (aurora-app-clock)
weather.reported      ← 天气查询完成 (aurora-app-weather) —— 保留但不再常用
diary.written         ← 日记已写入
diary.queried         ← 日记查询完成
lifecycle.started     ← 应用启动完成
lifecycle.stopping    ← 应用即将停止
lifecycle.crashed     ← 应用崩溃
```

### 5.5 EventBridge 适配

原 EventBridge 从 `host.drain_events()` 拉取 `AppEvent` 对象。迁移后改为从 `MCPClientManager` 接收 notification：

```python
# src/brain/nodes/event_bridge.py (改造)
async def run_event_bridge(
    mcp_client: MCPClientManager,
    circuit: Circuit,
    stop_event: asyncio.Event,
) -> None:
    # 注册 notification 处理器
    queue: asyncio.Queue[dict] = asyncio.Queue()

    mcp_client.on_notification("aurora/event", lambda name, params: queue.put(params))

    while not stop_event.is_set():
        try:
            params = await asyncio.wait_for(queue.get(), timeout=1.0)
        except TimeoutError:
            continue

        # 将 AMP notification 转为文件写入（与原逻辑一致）
        envelope = params.get("header", {})
        payload = params.get("payload", {})
        safe_type = str(payload.get("type", "unknown")).replace(".", "_")
        message_id = str(envelope.get("message_id", ""))
        file_path = f"inbox/pending/event_{safe_type}_{message_id}.json"

        update = FileUpdate(
            descriptor=FileDescriptor(path=file_path, schema="json"),
            content=params,  # 完整 AMP envelope 写入文件
        )
        await circuit.apply_update(update, node_id="event_bridge")
```

### 5.6 协议版本与兼容

- 所有消息带 `header.protocol: "amp/1.0"` 版本标记
- 接收方按协议版本选择合适的解析器
- 未知字段忽略（forward-compatible）
- 已知字段缺失时使用默认值

---

## 6. App 迁移方案

### 6.1 App 新结构

```
apps/aurora-app-weather/
├── __init__.py
├── manifest.yaml           ← 元数据声明（保留）
├── mcp_server.py           ← MCP Server 入口（新增）
├── service.py              ← 业务逻辑（从 runtime.py 抽取）
├── config.example.json
├── assets/
├── README.md
└── LICENSE
```

### 6.2 manifest.yaml 升级

```yaml
# apps/aurora-app-weather/manifest.yaml (改造后)
package: im.polaris.weather
name: 天气应用
version: 0.2.0
type: mcp-server                        # 新增：标记为 MCP Server 类型

mcp:
  transport: stdio                      # 新增：传输方式
  entry: mcp_server.py                  # 新增：入口文件
  command: [ "uv", "run", "python" ]    # 新增：启动命令

# commands 字段变为可选——工具声明由 list_tools() 动态提供
# 但保留用于静态文档和人类可读性
commands:
  - name: get_weather
    description: 查询指定城市的实时天气
    parameters:
      city:
        type: string
        description: 城市名称
        required: false
      days:
        type: number
        description: 预报天数（1-7）
        required: false
    returns:
      ok:
        type: boolean
      report:
        type: string
```

### 6.3 mcp_server.py：MCP Server 入口

```python
# apps/aurora-app-weather/mcp_server.py
"""天气 MCP Server —— 通过 stdio 与 Brain 通信。"""
from __future__ import annotations

import asyncio
import json

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from .service import WeatherService

server = Server("aurora-weather")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="get_weather",
            description="查询指定城市的实时天气与今日概览（默认使用启动参数 default_city）。",
            inputSchema={
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "城市名称（可为空，使用默认城市）",
                    },
                    "days": {
                        "type": "integer",
                        "description": "预报天数（1-7）",
                        "minimum": 1,
                        "maximum": 7,
                        "default": 1,
                    },
                },
            },
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name != "get_weather":
        raise ValueError(f"Unknown tool: {name}")

    city = str(arguments.get("city", ""))
    days = int(arguments.get("days", 1))
    result = await WeatherService.get_weather(city=city, days=days)

    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
```

### 6.4 service.py：纯业务逻辑

```python
# apps/aurora-app-weather/service.py
"""天气业务逻辑 —— 无框架依赖，可独立单测。"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class WeatherResult:
    ok: bool
    city: str = ""
    location: str = ""
    report: str = ""
    error: str = ""


class WeatherService:
    @staticmethod
    async def get_weather(city: str = "", days: int = 1) -> dict:
        """纯业务逻辑，不依赖 MCP / PlatformAPI / ApplicationHost。

        返回 dict，由 mcp_server.py 序列化为 JSON。
        """
        ...
        return {"ok": True, "city": city, "report": "..."}
```

### 6.5 兼容层：runtime.py（可选保留）

在迁移过渡期，保留 `runtime.py` 作为兼容入口：

```python
# apps/aurora-app-weather/runtime.py (兼容层)
"""旧 ApplicationProtocol 兼容层 —— 迁移完成后移除。"""
from pathlib import Path
from src.platform.application_api import PlatformAPI
from .service import WeatherService

class WeatherApplication:
    """兼容旧 ApplicationHost 的应用入口。"""

    def _bind(self, api: PlatformAPI) -> None:
        self._api = api

    def manifest_path(self) -> Path:
        return Path(__file__).with_name("manifest.yaml")

    async def get_weather(self, city="", days=1, **kwargs):
        return await WeatherService.get_weather(city=city, days=days)

    async def on_start(self) -> None: ...
    async def on_stop(self) -> None: ...
    async def on_tick(self) -> None: ...
```

两套入口可以并行运行：旧入口走 `ApplicationHost`，新入口走 MCP Server `stdio_client`。迁移完成后移除兼容层。

### 6.6 迁移顺序（按复杂度递增）

| 顺序 | App | 复杂度 | 说明 |
|------|-----|--------|------|
| 1 | `aurora-app-diary` | 低 | 纯文件 I/O，无外部依赖 |
| 2 | `aurora-app-clock` | 低 | 时间逻辑自包含，有定时器回调 |
| 3 | `aurora-app-weather` | 中 | 有 HTTP 外部调用 |
| 4 | `aurora-app-qq` | 高 | 涉及 NoneBot 消息监听、OneBot 协议 |

---

## 7. 实施路径

### Phase 1：基础设施（2 周）

- 引入 `mcp` Python SDK 作为依赖
- 实现 `MCPServerKit`：spawn / health-check / shutdown / restart
- 实现 `MCPClientManager`：连接管理、tools/list 缓存、tools/call
- 实现 AMP envelope 的定义与验证（`src/platform/mcp_kit/protocol.py`）
- 适配 `app_config.py`，支持 `mcp:` 配置段
- 适配 `app_discovery.py`，支持扫描 `mcp_server.py`

### Phase 2：App 逐个迁移（2-3 周）

- 每个 App 新增 `mcp_server.py` + `service.py`
- `manifest.yaml` 升级，添加 `type: mcp-server` + `mcp:` 配置段
- 保留旧 `runtime.py` 兼容层
- 完成一个 App 就上线测试一个

### Phase 3：Brain 侧适配（1-2 周）

- Internalizer / Externalizer 从 `_build_commands_text()` 改为 `mgr.tools_as_openai_schema()`
- Externalizer 从 JSON 文本解析改为接收 `tool_calls` 结构
- EventBridge 从 `host.drain_events()` 改为 MCP notification 回调
- 移除 `command_dispatcher` Router 节点
- 更新 `topology.yaml`：移除 `command_dispatcher` 边

### Phase 4：清理（1 周）

- 移除 `application_api.py`、`application_protocol.py`、`loop.py`
- 移除各 App 的兼容 `runtime.py`
- 移除 `_build_commands_text()` 三处重复
- 移除 `parse_llm_json` 递归 fallback（Externalizer 不再需要解析 LLM 文本为 JSON 动作）
- 更新 `code-review.md` 标记已解决问题
- 更新测试套件

---

## 8. 风险与缓解

### 8.1 高风险项

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| QQ App 的 NoneBot 集成与 MCP stdio 不兼容 | 中 | 高 | QQ App 保留旧兼容层更长时间，或改为 SSE transport |
| MCP Server 进程崩溃后恢复 | 中 | 中 | ServerKit 实现 health-check + 自动重启，Brain 侧 client 实现重连 |
| tools/call 延迟高于 in-process 调用 | 低 | 低 | stdio JSON-RPC 开销 < 1ms，远低于 LLM 调用延迟 |

### 8.2 低风险项

- **MCP SDK 稳定性**：`mcp` Python SDK 由 Anthropic 维护，已在 Cursor / Claude Desktop 中广泛使用
- **进程管理**：Python `asyncio.create_subprocess_exec` 成熟可靠
- **向后兼容**：两套入口并行运行至迁移完成

---

## 9. 总结

| 维度 | 评估 |
|------|------|
| **Brain 影响** | **零侵入**——认知管线、记忆系统、节律环路完全不动 |
| **Platform 变化** | ApplicationHost → MCPServerKit（进程管理）+ MCPClientManager（连接管理） |
| **App 变化** | 新增 mcp_server.py 入口，业务逻辑抽取为 service.py |
| **消息协议** | AMP——在 MCP notification 之上定义类型化 envelope，替代裸 AppEvent 推送 |
| **最大收益** | 消除 JSON 文本解析脆弱性、标准化工具调用、可独立部署 App |
| **迁移周期** | 约 6-8 周（分批、可回滚、兼容层并行） |
| **设计哲学** | 保持 FileEventBus 文件驱动核心不动摇；MCP 仅用于工具/事件的外部通信层 |
