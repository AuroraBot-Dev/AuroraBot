# 0217：存储实现迁移——SQLAlchemy 2.0 ORM（Schema v9 契约不变）

状态：已接受
日期：2026-08-08
来源：用户决策——放弃裸 sqlite3 手写 SQL，改用 ORM 模型 + pythonic 数据库操作
先决条件：RFC 0210（单一 SQLite 即运行态与归档）、RFC 0216（记忆引擎）

## 问题

`src/engine/store/`（1652 行）与 `src/memory/service.py`（242 行）全部使用裸
`sqlite3` + 手写 SQL：重复的 INSERT/SELECT 绑定、`sqlite3.Row → 领域模型`手写转换、
`_SCHEMA` DDL 字符串与 `_quoted/_set` 状态字面量生成。类型安全差、样板多、难以演进。

用户决策：存储实现迁移到 **SQLAlchemy 2.0（同步 ORM）**，行为契约不变。

## 决定

### 1. 依赖与引擎

- `sqlalchemy>=2.0` 加入直接依赖（当前已随 mem0ai 传递进入 lock，无额外重量）。
- 同步引擎，单进程 asyncio 独占不变：`NullPool` + `isolation_level="IMMEDIATE"`
  （等价现有 `BEGIN IMMEDIATE`）+ `timeout=30`；`foreign_keys=ON` 与
  `busy_timeout=30000` 通过 connect 事件注入。

### 2. engine/store 重写为 ORM

- 新增 `models.py`：`TaskRow/AgentRow/MessageRow/ActivityRow/CausalEventRow/InboxEventRow`
  六张表 + `SchemaMetaRow`，`Mapped/mapped_column` 声明式模型，**物理 Schema v9 不变**：
  - 部分唯一索引 `idx_activities_one_active_per_agent`（`sqlite_where`）；
  - `idx_messages_ready` 等复合索引的列序与 `DESC` 方向逐一保留；
  - CHECK（autonomous、kind、inbox status）、FK、UNIQUE、TEXT/INTEGER/REAL 类型一致。
- `schema.py` 的 DDL 字符串删除，`Base.metadata.create_all(checkfirst=True)` 生成；
  版本检查与"旧库拒绝启动"语义保留（仍只接受全新 v9）。
- 行转换：`_task/_agent/_message/_activity` 从"sqlite3.Row → 领域模型"改为
  "ORM 实体 → 领域模型"；所有内部写操作走 `Session` 事务（提交后属性不过期，
  `expire_on_commit=False`，外部可安全读取返回的实体）。
- **公共方法签名不变**；仅 `claim_activities/claim_tool_activities/
  tool_recovery_activities` 的返回元素从 sqlite3.Row 变为 ORM 实体
  （`row["x"]` → `row.x`），调用方 `engine/runtime.py:_activity`、
  `tool_registry.py:_execution_request` 同步更新。
- JSON 列保留紧凑序列化（`sort_keys=True`、紧凑分隔符）不变，由 TypeDecorator 承担。
- `store.connect()/store.transaction()` 保留为原始 sqlite3 逃生口
  （测试与调试直查 DB 用），热路径不再使用。

### 3. memory/service.py 重写为 ORM

- `memory.sqlite3` 四表（`memory_receipts/session_memory/durable_facts/
  memory_messages`）改为 ORM 模型；`INSERT OR IGNORE` → SQLite 方言
  `on_conflict_do_nothing`，幂等语义与 rowcount 判断不变。
- `memory_dir=None` 时的内存降级路径不变。

### 4. 行为与性能

- 语义零变化：幂等、防抖、原子决策、claim 降级为原子 UPDATE、崩溃恢复全部不变。
- 单次操作增加 µs 级 ORM 开销，相对秒级模型/工具调用可忽略（RFC 0210 结论不变）。

## 结果

- engine/store 与 memory 不再出现手写 SQL；模型即 schema 声明，类型检查（pyright）
  覆盖全部列名与查询。
- Schema v9 物理结构与既有数据库完全兼容；不迁移、不重建工作区。

## 兼容性

- 行为契约不变：`SQLiteRuntimeStore` 与 `MemoryService` 公共方法签名、幂等与
  事务边界、`data/engine` 与 `data/memory` 目录布局均不变。
- 仅返回值访问方式变化（`row["x"]` → `row.x`），由 pyright 强制对齐。
- 依赖：`sqlalchemy` 升级为直接依赖（已在 lock 内）。
