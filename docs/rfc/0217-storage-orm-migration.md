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
- 版本检查语义保留：`current > target`（库比代码新）拒绝启动；旧库
  （v1–v8）按版本序列迁移（仍只接受迁移后 v9 形状）。
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

### 4. ops/store.py 重写为 ORM

- `panel.sqlite3` 两表（`sessions/attachments`）改为 ORM 模型；
  `PRAGMA user_version` 迁移语义（Schema v1、拒绝不支持版本）不变，
  Token.txt 原子创建逻辑不变。
- 共享连接改为每事务独立 Session（FastAPI 线程池下更安全）；
  `create_session/verify_session/delete_session/add_attachment/
  get_attachment/close` 公共方法签名不变。

### 5. 版本化迁移框架（utils/migration + 各存储 migration 包）

- 新增 `src/utils/migration.py`：`migrate_to(connection, *, current, target,
  steps, set_version)` —— 从当前版本按序执行版本迁移步骤直到目标版本，
  每步后推进版本号；`current > target`（库比代码新）与缺失步骤均拒绝，
  防止静默漏迁移。
- 每个版本间隔一个独立步骤文件（`v0_v1.py`、`v1_v2.py`…），在各存储的
  `migration/` 子包中以 `STEPS: dict[int, MigrationStep]` +
  `TARGET_VERSION` 汇总，全部存储统一实装：
  - `ops/migration/`：面板存储，`user_version` 版本号，v0→v1 建表（v1 现状）；
  - `src/memory/migration/`：记忆存储，`user_version` 版本号，v0→v1 建表
    并清理遗留表（v1 现状）；
  - `src/engine/store/migration/`：运行态存储，`schema_meta` 版本号（RFC 0210
    契约），v0 全新库直接建表并写入当前目标版本 9；v1–v8 迁移步骤按历史演化
    档案重建并全部注册（RFC 0210 §3 撤销"不迁移旧库"政策，自即日起数据库必须
    考虑迁移），旧库启动时在单事务中按序升级到 v9，任一版本步骤失败整体回滚；
    代码路径只访问 v9 形状，不兼容旧版本列。
- 未来 Schema 演进：实现对应 `vN_vN+1.py`、注册并提升 `TARGET_VERSION`，
  启动时从当前版本一路迁移到目标版本。

### 6. 行为与性能

- 语义零变化：幂等、防抖、原子决策、claim 降级为原子 UPDATE、崩溃恢复全部不变。
- 单次操作增加 µs 级 ORM 开销，相对秒级模型/工具调用可忽略（RFC 0210 结论不变）。

## 结果

- engine/store、memory 与 ops/store 不再出现手写 SQL；模型即 schema 声明，
  类型检查（pyright）覆盖全部列名与查询。
- Schema v9 物理结构与迁移后数据库完全兼容；v1–v8 旧库经版本序列升级，
  无需重建工作区（历史演化档案 v2→v4→v7→v9 由迁移步骤承接）。

## 兼容性

- 行为契约不变：`SQLiteRuntimeStore`、`MemoryService` 与 `PanelStore` 公共方法
  签名、幂等与事务边界、`data/engine`、`data/memory` 与 `data/ops` 目录布局均不变。
- 仅返回值访问方式变化（`row["x"]` → `row.x`），由 pyright 强制对齐。
- 依赖：`sqlalchemy` 升级为直接依赖（已在 lock 内）。
