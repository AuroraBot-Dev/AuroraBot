# AuroraBot 平台层原生 MCP 重构 — 迁移进度

> 跟踪每个阶段的执行状态、验证结果和剩余风险。

---

## Phase 0：建基线 ✅

| 项目 | 日期 |
|------|------|
| 完成日期 | 2026-06-19 |
| 当前分支 | `refact/platform` |

### 基线检查结果

| 命令 | 结果 |
|------|------|
| `ruff check src/ tests/` | All checks passed |
| `ruff format --check src/ tests/` | 77 files already formatted |
| `pyright src/` | 0 errors, 0 warnings |
| `pytest --cov=src` | 243 passed, 52% cov |

### 旧接口依赖扫描

扫描命令：

```powershell
rg -n "ApplicationHost|PlatformAPI|ApplicationProtocol|AppEvent|CommandSpec|invoke_command|list_command_specs|drain_events|command_dispatcher|action_queue" src tests apps
```

分类归档见 `reports/phase0-dependency-scan.md`。

### 剩余风险

- 无新增风险，基线已锁定。
- 将保留旧路径至 Phase 7 清理。

---

## Phase 1：新增 MCP 基础设施 ✅

| 项目 | 内容 |
|------|------|
| 完成日期 | 2026-06-19 |
| 开始日期 | 2026-06-19 |
| 改动摘要 | 新增 `mcp_kit` 包（6 文件）、AMP 模型、mcp SDK 依赖 |
| 验证结果 | ruff ✅, pyright ✅ (0 errors), pytest ✅ (270 passed, 55% cov) |

### 新增文件

| 文件 | 职责 |
|------|------|
| `src/platform/mcp_kit/__init__.py` | 包入口 |
| `src/platform/mcp_kit/server_spec.py` | MCPServerSpec dataclass + 约束验证 |
| `src/platform/mcp_kit/amp.py` | AMP envelope：build/parse/convert/legacy 桥接 |
| `src/platform/mcp_kit/tool_schema.py` | MCP Tool → OpenAI schema / prompt text 转换 |
| `src/platform/mcp_kit/manifest.py` | manifest.yaml MCP 扩展读取 |
| `src/platform/mcp_kit/discovery.py` | 扫描 apps/ + config.yml 构建 MCPServerSpec 列表 |
| `tests/test_mcp_amp.py` | 18 个测试：server_spec、AMP、tool_schema |
| `tests/test_mcp_discovery.py` | 9 个测试：manifest、_build_spec、discovery |

### 新增依赖

- `mcp[cli]>=1.27,<2` → 已安装 `mcp==1.28.0`

### 剩余风险

- 旧平台层完全保留（双轨并行）
- MCP Server 进程管理（server_kit.py）和 Client 连接管理（client_manager.py）待 Phase 2

---

## Phase 2：MCP Client/Server 管理 ✅

| 项目 | 内容 |
|------|------|
| 完成日期 | 2026-06-19 |
| 开始日期 | 2026-06-19 |
| 改动摘要 | 实现 MCPServerKit 和 MCPClientManager |
| 验证结果 | ruff ✅, pyright ✅, pytest ✅ (282 passed, 54% cov) |

### 新增文件

| 文件 | 职责 |
|------|------|
| `src/platform/mcp_kit/server_kit.py` | MCP Server 进程管理器：start/stop/restart/health_check |
| `src/platform/mcp_kit/client_manager.py` | MCP Client 连接管理器：connect/call_tool/list_tools/notification_registration |
| `tests/test_mcp_server_kit.py` | 12 个测试：启停、健康检查、工具调用、notification 注册 |

### 关键实现

- `MCPServerKit.start_one()` / `stop_one()` / `restart_one()`：子进程 spawn + SIGTERM 优雅停止 + 超时 SIGKILL
- `MCPServerKit.health_report()`：running/stopped/crashed 状态映射
- `MCPServerKit._health_check_loop()`：后台定期检查进程存活
- `MCPClientManager._run_connection()`：使用 `async with stdio_client()` 正确管理上下文生命周期
- `MCPClientManager.call_tool()`：支持全名路由（`im.polaris.test.echo`），30s 默认超时
- `MCPClientManager.refresh_tools()`：tools/list 缓存刷新
- `MCPClientManager.on_notification()`：Handler 注册/注销（为 Phase 4 预留）

### 注意事项

- Notification 监听尚未实现（MCP SDK v1 无 `incoming_notifications` async generator，需在 Phase 4 改用 message_handler 回调方式）
- legacy 旧平台层完全保留

### 剩余风险

- Notification 的异步接收需要在 Phase 4 使用底层 message_handler 实现
- 没有真正的 MCP Server 的集成测试（需要 mcp_echo_server fixture，将在 Phase 3 创建）

---

## Phase 3：迁移 diary 为 MCP Server 样板 ✅

| 项目 | 内容 |
|------|------|
| 完成日期 | 2026-06-19 |
| 改动摘要 | 抽取 DiaryService、创建 FastMCP 入口、保留旧 runtime 兼容层 |
| 验证结果 | ruff ✅, pyright ✅, pytest ✅ (291 passed, 54% cov) |

### 新增/修改文件

| 文件 | 变更 | 职责 |
|------|------|------|
| `apps/aurora-app-diary/service.py` | **新增** | 纯业务逻辑，无 PlatformAPI 依赖，可独立单测 |
| `apps/aurora-app-diary/mcp_server.py` | **新增** | FastMCP 入口，3 个 tool：write/read/list_dates |
| `apps/aurora-app-diary/runtime.py` | **重写** | 薄兼容层，委托给 DiaryService |
| `apps/aurora-app-diary/manifest.yaml` | **更新** | 添加 `type: mcp-server` 和 `mcp:` 配置段 |
| `pyproject.toml` | **更新** | 忽略 apps 目录的 N999 模块名规则 |
| `tests/test_diary_service.py` | **新增** | 7 个测试 — service 层全覆盖 |
| `tests/test_diary_mcp_server.py` | **新增** | 2 个测试 — 导入 + stdio tools/list 集成测试 |

### 注意事项

- `mcp_server.py` 通过 `sys.path` 添加项目根目录和 App 目录解决横线目录名的导入问题
- 旧 `DiaryApplication` 保留为兼容层，旧测试全部通过（无回归）
- MCP Server 可通过 `uv run python apps/aurora-app-diary/mcp_server.py` 独立启动

---

## Phase 4：

| 项目 | 内容 |
|------|------|
| 状态 | 待开始 |

---

## Phase 5：

| 项目 | 内容 |
|------|------|
| 状态 | 待开始 |

---

## Phase 6：

| 项目 | 内容 |
|------|------|
| 状态 | 待开始 |

---

## Phase 7：

| 项目 | 内容 |
|------|------|
| 状态 | 待开始 |

---

## 备注

- 重构指南文档：`docs/reports/platform-native-mcp-refactor-guide.md`
- 研究报告文档：`docs/reports/app-platform-mcp-migration.md`
- 不可变边界：Brain 核心（FileEventBus、记忆系统、节律环路）保持不变
