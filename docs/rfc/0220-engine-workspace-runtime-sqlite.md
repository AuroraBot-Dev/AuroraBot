# 0220：engine 运行库路径上提——`data/engine/runtime.sqlite3`

状态：已接受
日期：2026-08-08
来源：RFC 0219 收敛工作区后 `process/` 仅剩单一文件，子目录失去载体意义
先决条件：RFC 0210（SQLite 终态）、0219（移除 inbox/archive，工作区收敛）

## 问题

RFC 0219 移除 inbox/archive 后，`data/engine/process/` 只承载 `runtime.sqlite3` 一个文件，
目录层级与实际内容不再匹配（"镜像包层级"哲学的过度嵌套）。

## 决定

1. **运行库路径上提**：`data/engine/process/runtime.sqlite3` → `data/engine/runtime.sqlite3`
   （`AgentEngine` 直接 `workspace / "runtime.sqlite3"`，不再创建 `process/`）。
2. 既有 `data/engine/process/runtime.sqlite3` 由运维一次迁移至新路径（move，WAL 一并移动）；
   旧路径不再读取（不迁移、不清理，与 0219 遗留处理一致）。
3. `reject_active_legacy_workspace` 的参数语义从"process 目录"校正为"engine 工作区"。

## 结果

- engine 工作区 = `data/engine/runtime.sqlite3`（单一文件即唯一运行态与终态）。
- 持久化路径镜像包层级：`src/engine → data/engine`。

## 兼容性

- Schema v9 与数据库内容不变，仅文件位置变化；一次 `mv` 即完成迁移。
- 测试与文档中的路径引用同步更新。
