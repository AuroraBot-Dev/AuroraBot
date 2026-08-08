# 0218：面板后端与统一操作体系——RESTful 资源树、命令同构、dashboard 退出平台

状态：已接受
日期：2026-08-08
来源：ops 能力不足（调试/观察/注入碎片化）、dashboard 与 ops 双服务器割裂、命令与 HTTP 不同构
先决条件：RFC 0200（ops 边界与 Port 注入）、0204（Console 本地前端先例）、0206（配置快照）、0210（SQLite 终态与 causal_events）、0211（工具域与 AMP 回执）、0215（费用统计）、0216（记忆引擎）

## 问题

1. **ops 无法承担全流程调试、观察、注入**：命令集只有 11 个单对象查询/注入；无列表查询、无因果事件流查询、无会话导出（RFC 0210 承诺的 causal_events 导出未落地）；命令注册是手工枚举的约定，非结构化契约。
2. **命令与 HTTP 不同构**：命令输出是散乱文本，`/v1/debug/*` 是另一套 JSON 语义，无统一 envelope；同一操作无法在文本与 JSON 之间同构表达。
3. **调试面未覆盖全部子包**：memory（RFC 0216）、ai（RFC 0215）、config（RFC 0206）、prompt、agents 均无可查询的调试接口，只有 engine 运行态。
4. **dashboard 与 ops 两张皮**：两个独立 uvicorn（dashboard 8000 / ops debug 8765）、两套认证（dashboard 完整 token 体系 / ops 裸 loopback）；聊天消息落独立 SQLite，与 engine 终态割裂。
5. **dashboard 平台定位不再成立**：dashboard 的"平台"角色只在承载一个 owner 与 bot 的交流页面；该页面与 console 是同一类本地前端，只是 Web 形态（RFC 0204 先例）。

## 决定

### 1. ops 是唯一面板后端（Panel Backend）

- ops 提供**唯一** FastAPI 根应用 `create_panel_app(ports, configuration)`（`ops/api.py` 重构），单端口单认证，承载系统全部 HTTP/WS 路由。
- 进程组合中不再有独立 debug server；`aurora/runtime.py` 的 `_debug_server` 由 `_panel_server` 取代（同一 `SignalSafeServer` 形态）。
- 面板路由分三类：
  - `/healthz`：无认证健康检查。
  - `/api/auth/*`：面板认证（见 §6）。
  - `/api/ops/*`：RESTful 操作资源树（见 §2/§3），含聊天语义（见 §4）。
- `PLATFORM_NAMES` 收敛为 `{"mcp"}`；dashboard 退出平台。

### 2. 统一操作体系：RESTful 资源树为唯一真源，命令是文本同构形态

RESTful 资源树（方法 + 资源路径）是操作语义的**唯一真源**；斜杠命令是该资源树的文本别名。两者共享同一 `OperationSpec`、同一参数模型、同一 handler、同一 JSON 输出。定义于 `src/contracts/operation.py`：

```python
class OperationScope(StrEnum):
    ALL = "all"                 # console 与面板 API 均可触发
    CONSOLE_ONLY = "console_only"

class ParameterLocation(StrEnum):
    PATH = "path"               # REST 路径段；文本中即路径段（/tasks/123）
    QUERY = "query"             # REST query 参数；文本中 --key value
    BODY = "body"               # REST JSON body 键；文本中 --key value

class ParameterKind(StrEnum):
    POSITIONAL = "positional"   # 仅 BODY/PATH，文本按声明序分配
    NAMED = "named"             # 文本 --key value / --key=value
    FLAG = "flag"               # 文本 --key；REST 中 true

@dataclass(frozen=True, slots=True)
class ParameterSpec:
    name: str
    location: ParameterLocation
    kind: ParameterKind = ParameterKind.NAMED
    type: str = "str"           # "str" | "int" | "float" | "bool" | "json"
    required: bool = False
    default: Any = None
    help: str = ""

@dataclass(frozen=True, slots=True)
class OperationSpec:
    method: str                 # "GET" | "POST"（预留 DELETE）
    path: str                   # 资源路径（唯一真源）："/engine/tasks/{task_id}"
    name: str                   # 内部规范名 "task.get"（日志、错误码）
    aliases: tuple[str, ...]    # 命令别名：("/task",)；缺省时命令文本即 path
    summary: str
    parameters: tuple[ParameterSpec, ...]
    scope: OperationScope = OperationScope.ALL
    handler: OperationHandler

@dataclass(frozen=True, slots=True)
class OperationResult:          # 文本与 REST 双入口的唯一输出
    ok: bool
    code: str                   # "ok" | "PARSE_ERROR" | "NOT_FOUND" | "INVALID_AMP" | ...
    message: str | None = None
    data: dict | None = None

@dataclass(frozen=True, slots=True)
class OperationContext:
    runtime: PanelRuntimePort
    request: RuntimeInput | None    # 文本入口携带；REST 入口为 None
```

**三重视角同构**：

1. **路径同构**：REST 路径 = 命令路径。`GET /api/ops/engine/tasks/123` 与 `/engine/tasks/123` 是同一操作；路径参数在文本中就是路径段。
2. **参数同构**：`ParameterSpec.location` 统一声明 PATH/QUERY/BODY；REST 入口按 location 从路径模板/query/body 取值，文本入口按 positional（PATH/BODY 声明序）+ `--key value`（NAMED/FLAG）取值，**两入口产出同一个规范化 `params: dict[str, Any]`**。
3. **输出同构**：两入口都返回 `OperationResult` 并序列化为固定 envelope：

   ```json
   {"ok": true, "code": "ok", "message": null, "data": { ... }}
   ```

   业务失败（参数错误、未找到、注入校验失败）返回 HTTP 200 + `{"ok": false, ...}`；HTTP 状态只表达传输与认证语义（401、404 未知资源、405 方法不支持）。Console 渲染器把 JSON 渲染为可读文本；`CommandControl` 保留给 console 的 clear/shutdown 进程控制。

- **注册**：`@operation(...)` 装饰器收集到 `ops/operations/` 包内模块级注册表（`ops/registry.py` 重写为自动收集 + 冲突校验：path+method、alias 全局唯一）。
- **路由**：`OperationRouter` 提供 `route_text(request) -> OperationResult`（文本入口）与 `dispatch(method, path, params) -> OperationResult`（REST 入口）。文本命令名匹配 = path 完整匹配或 alias 匹配；未命中且以 `/` 开头 → `NOT_FOUND`；非 `/` 开头 → 对话通道（`message.send` 便捷形式）。
- **参数错误**：`PARSE_ERROR`，message 含用法串（由 ParameterSpec 渲染）。

### 3. 操作目录：RESTful 资源树镜像 src 包层级（全子包调试面）

资源树按域组织，**镜像 `src/` 包结构**（engine/memory/ai/agents/config/prompt——与"持久化路径镜像包层级"同一哲学）：

**engine 域**（运行态观察与注入）：

| 操作 | 命令别名 | 职责 |
|---|---|---|
| `GET /engine/status` | `/engine/status` | 运行态快照 |
| `GET /engine/tasks` | `/tasks` | Task 列表（status 筛选、分页） |
| `GET /engine/tasks/{task_id}` | `/task` | Task 详情（预算、监督树、`waiting_on`、因果摘要） |
| `GET /engine/agents` | `/agents` | Agent 列表 |
| `GET /engine/agents/{agent_id}` | `/agent` | Agent 详情 |
| `GET /engine/events` | `/events` | causal_events 流查询（session/task/type 筛选、分页） |
| `POST /engine/events` | `/event` `/e` | AMP 注入（同一资源、写方法，RESTful 语义） |
| `GET /engine/sessions/{session_id}/export` | `/export` | 会话导出：RFC 0210 的 causal_events 投影 |
| `POST /engine/pump` | `/pump` `/p` | 显式推进（1–100 边界） |
| `POST /engine/shutdown` | `/quit` | 请求进程关闭 |

**memory 域**（RFC 0216 记忆引擎）：

| 操作 | 命令别名 | 职责 |
|---|---|---|
| `GET /memory/history` | `/memory/history` | 记忆历史（scope 筛选、分页） |
| `GET /memory/search` | `/memory/search` | 记忆检索（query、scope、limit） |
| `GET /memory/status` | `/memory/status` | 记忆存储统计（窗口/概要/长期计数） |

**ai 域**（RFC 0215 外部接口）：

| 操作 | 命令别名 | 职责 |
|---|---|---|
| `GET /ai/cost` | `/ai` | 费用统计（total/by_role/by_model/by_status） |
| `GET /ai/models` | `/models` | 角色-模型绑定与模态查询 |
| `GET /ai/roles` | `/roles` | 角色目录（自描述） |

**agents / config / prompt 域**：

| 操作 | 命令别名 | 职责 |
|---|---|---|
| `GET /agents/profiles` | `/profiles` | Agent profile 目录（id、实现、能力） |
| `GET /config/snapshot` | `/config` | 启动配置快照（RFC 0206，脱敏） |
| `GET /prompts/{role}` | `/prompt` | 角色提示词查看 |

**会话与输出（面板聊天语义，见 §4）**：

| 操作 | 命令别名 | 职责 |
|---|---|---|
| `GET /messages` | `/messages` | 会话消息投影（按 session 筛选，聊天历史） |
| `POST /messages` | `/say` `/s` | 发送消息（对话通道同实现） |
| `GET /activities` | `/activities` | output_stream 游标查询（与 console 渲染同源） |

console 专属（scope=CONSOLE_ONLY）：`console.clear`（`/clear`）、`console.log`（`/log` 终端日志开关）。

- 注入-推进-观察闭环：`POST /messages` / `POST /engine/events` → `POST /engine/pump` → `GET /engine/tasks/{id}` / `GET /engine/events` / `GET /activities`。
- 原有 11 个命令全部迁入该体系；`/v1/debug/*` 端点删除（语义由资源树取代）。
- 域路径即包名，新子包出现即新增域；`/api/ops` 前缀下的资源树可经 `GET /api/ops`（或 `system.info` 操作）自描述——由 OperationSpec 目录渲染。

### 4. dashboard 退出平台，能力并入 ops

- **删除 `src/platform/dashboard/` 整目录**（api/service/communication/routing/store/adapter/`__init__.py`），及其 `aur.dashboard.send` 工具、聊天 SQLite（chat.sqlite3）、附件目录、Token 机制中的全部代码。
- **聊天语义并入面板**（前端是 console 的 Web 分身，不再有"消息应用"）：
  - **输入**：聊天输入 = `POST /messages`（`/say` 或直接对话文本），进入 engine AMP 热路径。
  - **输出**：bot 输出不再投递为消息；Web 前端与 console 渲染**同一个源**——`output_stream`（activities 投影），原样保留 bot 输出。WS 端点 `WS /api/ops/stream`（Bearer 认证 + Origin 校验）推送 output_stream 增量（服务端维护游标），前端聊天输出区即 console 的 Web 形态。
  - **历史**：聊天历史 = `GET /messages` 投影（message.received 与 model 输出按 session 筛选）；不再有独立消息库与用户库，面板只有一个 owner 身份。
  - **附件**：保留上传/下载端点（`POST/GET /api/ops/attachments`，登录保护，存储 `data/ops/uploads/`，索引入 ops 自有 SQLite），`POST /messages` 支持 `attachments`（BODY 参数，可重复）。
- `InputOrigin.DASHBOARD` 更名 `InputOrigin.PANEL`。

### 5. 输出同源与查询面扩展（contracts 窄端口）

- console 与面板的 bot 输出统一来自 `output_stream`/`GET /messages`，不再存在"应用"级消息回发；RFC 0204 的 console 渲染语义原样适用于面板。
- `src/contracts/ports.py` 按域拆分窄查询端口，组合根将实现注入 `create_panel_app`（ops 仍只依赖 contracts + utils，不 import 具体包）：
  - `EngineQueryPort`（演化自 RuntimeCommandPort）：`submit_amp`/`submit_conversation`/`pump`/`status`/`task_detail`/`agent_detail`/`output_stream` + 新增 `list_tasks(status=.., limit=..)`、`list_agents()`、`query_events(session_id=.., task_id=.., event_type=.., after_id=0, limit=..)`、`session_export(session_id)`。
  - `MemoryQueryPort`（新增）：`history(scope=.., limit=..)`、`search(query, scope=.., limit=..)`、`status()`——由 MemoryService 新增只读方法实现（读终态行，不触碰热路径）。
  - `AiQueryPort`（新增）：`cost()`（透传 cost_tracker 分类统计）、`models()`（角色-模型绑定与模态）、`roles()`（角色目录）。
  - `ConfigQueryPort`（新增）：`snapshot()`（配置快照脱敏投影）、`prompt_for(role)`（PromptCatalog 只读查询）。
- `DashboardControlPort`/`DashboardDebugPort` 删除；`InteractiveInputPort` 保留；`InputOrigin` 改名。

### 6. 认证：面板级 token 体系（上移并统一）

- 复用并扩展原 dashboard 模式：bootstrap token 文件 `data/ops/Token.txt`（0600，首次启动生成并以 Rich Panel 打印）+ Bearer session。
- session 存储改为 ops 自有 SQLite（`data/ops/panel.sqlite3`，Schema v1：sessions/attachments 表），不再有 users 表（面板单一 owner 身份）。
- `POST /api/auth/login`（bootstrap token 恒定时间比较）签发 Bearer；`POST /api/auth/logout` 销毁。
- **除 `/healthz` 外全部面板端点（含操作、附件、WS）要求 Bearer**；WS 走 query token + Origin 校验；CORS 白名单收敛到面板配置。
- ops 裸 loopback debug API 时代结束；`debug_host`/`debug_port` 随之删除。

### 7. 配置与存储

```toml
[runtime.panel]                       # 取代 debug_host/debug_port 与 [platform.dashboard]
enabled = true
host = "127.0.0.1"                    # 校验强制 loopback（沿用 dashboard 校验）
port = 8765
allowed_origins = ["http://localhost:5173", "http://127.0.0.1:5173"]
open_browser = false
session_ttl_seconds = 604800
max_upload_bytes = 10485760           # 附件上限，0 表示禁用附件
```

- `config/platforms.toml` 删除 `[platform.dashboard]`；`config/runtime.toml` 增加 `[runtime.panel]`，删除 `debug_host`/`debug_port`；`config/storage.toml` 的 `[storage.platform.dashboard]` 由 `[storage.ops]`（→ `data/ops/`）取代；platform preference 中 dashboard 由 `[runtime.panel].open_browser` 取代。
- `src/contracts/configuration.py`：删 `DashboardConfig`，新增 `PanelConfig`；`PlatformPreference.dashboard` 字段移除。
- 面板存储路径镜像包层级：ops 是根级包 → `data/ops/`。

### 8. 组合根

- `aurora/runtime.py`：平台工厂注册表只剩 mcp；`_debug_server` → `_panel_server`（构建各查询 Port → `create_panel_app` + `SignalSafeServer`）；console 启动不变；`open_browser` 后台任务并入面板 server 生命周期。
- `AuroraRuntime`（`ops/runtime.py`）继续实现 `EngineQueryPort`/`InteractiveInputPort`，并持有 memory/gateway/configuration 的查询面（组合根构造时注入），不再兼任认证与聊天存储（上收 ops 面板自有组件）。
- 依赖方向不变：ops 只依赖 contracts + utils（面板 SQLite 用 stdlib sqlite3）；engine/memory/ai 不依赖 ops。

## 结果

- ops 成为系统唯一后端路由：单端口、单认证、单 envelope；RESTful 资源树与文本命令同构（同一路径、同一参数模型、同一 JSON 输出）。
- 调试面覆盖全部子包：engine（运行态/事件/会话导出）、memory（历史/检索/统计）、ai（费用/模型/角色）、agents（profile）、config（快照）、prompt（提示词）。
- 注入-推进-观察全流程闭环：消息/AMP 注入 → pump → 任务/事件/输出流观察。
- dashboard 平台删除；console 与 Web 面板是同一 bot 输出源的两个渲染形态；聊天历史回归 engine 终态（causal_events），无独立聊天库。
- 认证统一：裸 loopback debug API 消失，全部面板能力受 token 保护。

## 兼容性与迁移

- **删除**：`src/platform/dashboard/`、`DashboardConfig`、`DashboardControlPort`/`DashboardDebugPort`、`PLATFORM_NAMES` 中 dashboard、`[platform.dashboard]`、`[storage.platform.dashboard]`、`debug_host`/`debug_port`、`/v1/debug/*`、`aur.dashboard.send` 能力、`ops/commands/` 旧命令文件（迁入 `ops/operations/`）。
- **测试**：删除 `tests/test_dashboard.py` 与平台相关断言；新增：操作体系（REST/文本同构、路径与参数解析、envelope、错误码）、各域查询（memory/ai/config/prompt）、会话导出、面板认证（登录/未授权/附件/WS）、组合根单服务器启动；`test_dependency_boundaries.py` 的 ops 边界断言保留并扩展（ops 不 import platform）。
- **前端**（仓库外）：聊天页改为 `POST /messages` + `WS /api/ops/stream` + `GET /messages`；登录指向 `/api/auth/login`；附件指向面板端点。
- 既有聊天历史不回迁（面板为全新后端，历史数据不回填；RFC 0217 的版本迁移只作用于 schema，不涉及面板数据回迁）；`data/platform/dashboard/` 遗留数据不再读取。
