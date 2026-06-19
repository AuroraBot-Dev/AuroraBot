# Phase 0 — 旧接口依赖扫描分类

> 日期：2026-06-19
> 命令：`grep -rn "ApplicationHost|PlatformAPI|ApplicationProtocol|AppEvent|CommandSpec|invoke_command|list_command_specs|drain_events|command_dispatcher|action_queue" src/ tests/ apps/`

---

## 一、需要立即改（Phase 1-2 新路径）

| 文件 | 原因 |
|------|------|
| `src/platform/` 全模块 | 新架构入口，新增 `mcp_kit/` 包，旧文件保留为 legacy |
| `src/platform/mcp_kit/__init__.py` | 新建 |
| `src/platform/mcp_kit/server_spec.py` | 新建 — MCPServerSpec |
| `src/platform/mcp_kit/amp.py` | 新建 — AMP envelope |
| `src/platform/mcp_kit/tool_schema.py` | 新建 — Tool schema 转换 |
| `src/platform/mcp_kit/manifest.py` | 新建 — MCP manifest 扩展 |
| `src/platform/mcp_kit/discovery.py` | 新建 — MCP server 发现 |
| `src/platform/mcp_kit/server_kit.py` | 新建 — Server 生命周期管理 |
| `src/platform/mcp_kit/client_manager.py` | 新建 — Client 连接管理 |

## 二、迁移期兼容保留（双轨并存）

所有 Brain 节点在 Phase 5 前继续使用旧 `host` 引用，通过字段注入：

| 文件 | 旧依赖 | 迁移策略 |
|------|--------|---------|
| `src/brain/kernel/base.py:283` | `host: ApplicationHost` | 保持字段，Phase 5 注入 `client_manager` 作为备选 |
| `src/brain/kernel/node_factory.py:35` | `from ... import ApplicationHost` | Phase 7 移除 |
| `src/brain/kernel/node_factory.py:45` | `"command_dispatcher": CommandDispatcher` | Phase 7 移除 |
| `src/brain/nodes/routers/command_dispatcher.py` | `host.invoke_command()` | Phase 5 新增 `mcp_tool_dispatcher` 并行 |
| `src/brain/nodes/agents/externalizer.py:189` | `host.list_command_specs()` | Phase 5 优先使用 `client_manager` |
| `src/brain/nodes/agents/internalizer.py:169` | `host.list_command_specs()` | Phase 5 优先使用 `client_manager` |
| `src/brain/nodes/agents/action_planner.py:239` | `host.list_command_specs()` | Phase 5 优先使用 `client_manager` |
| `src/brain/nodes/agents/polaris_agent.py:583` | `host.list_command_specs()` | Phase 5 + 6 |
| `src/brain/nodes/agents/polaris_agent.py:732` | `host.invoke_command()` | Phase 5 + 6 |
| `src/brain/nodes/event_bridge.py:49` | `host.drain_events()` | Phase 4 新增 `run_mcp_event_bridge()` |
| `src/brain/runtime.py:31` | `_register_builtin_commands(host)` | Phase 7 改为注册到 MCP |
| `src/brain/runtime.py:70` | `register_enabled_apps(host)` | Phase 7 改为 `server_kit.load_specs_from_config()` |
| `src/brain/runtime.py:85` | `start_runtime(host)` | Phase 7 改为 `server_kit.start_all()` |
| `src/brain/localhost/commands/core.py:64` | `host.drain_events()` | Phase 5 + 6 |
| `src/brain/localhost/commands/emit.py` | `AppEvent()` | Phase 5 + 6 |
| `src/brain/localhost/commands/invoke.py` | `host.invoke_command()` | Phase 5 + 6 |
| `src/brain/localhost/commands/say.py` | `AppEvent()` | Phase 5 + 6 |

## 三、测试需要更新

| 测试文件 | 说明 | 迁移时机 |
|---------|------|---------|
| `tests/test_application_host.py` | 旧 Host 行为测试 | Phase 7 删除或改为 legacy 测试 |
| `tests/test_application_host_extra.py` | 旧 Host 额外行为测试 | Phase 7 删除或改为 legacy 测试 |
| `tests/test_gamma_integration.py` | 引用 ApplicationHost + command_dispatcher | Phase 5 + 7 |
| `tests/test_localhost_terminal.py` | 引用 ApplicationHost | Phase 5 + 7 |
| `tests/test_node_factory.py` | 引用 ApplicationHost | Phase 7 |
| `tests/test_runtime.py` | 引用 ApplicationHost | Phase 7 |

## 四、旧代码最终删除（Phase 7）

| 文件 | 删除/保留 |
|------|-----------|
| `src/platform/application_api.py` | 删除 |
| `src/platform/application_protocol.py` | 删除 |
| `src/platform/loop.py` | 删除或降级 |
| `src/platform/application_host.py` | 删除或移动到 `legacy/` |
| `src/platform/contracts.py` | `CommandSpec` 删除；`AppEvent` 保留为 AMP 兼容 |
| `src/brain/nodes/routers/command_dispatcher.py` | 删除 |
| `apps/*/runtime.py` | 删除或 shim |
| `src/brain/nodes/topology.yaml` 中 `command_dispatcher` | 移除 |
