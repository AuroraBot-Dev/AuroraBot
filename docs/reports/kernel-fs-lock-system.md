# AuroraBot 文件归档锁系统设计

> 调研日期：2026-06-14
>
> 问题：认知管线中的文件（inbox/pending/*、pipeline/*/msg_*.json 等）经过 Node 处理后需归档到 `done/` 子目录。当前通过 `move_to_done()` 做文件 rename + 文件名约定避开了部分并发问题，但缺乏真正的锁语义——当文件正在被多个 Reader 读取时执行归档，存在读已删除/已移动文件的风险。

---

## 1. 现状分析

### 1.1 当前的文件消费模式

文件流通过程（以 message_queue 为例）：

```
1. message_preprocessor 写入 pipeline/message_queue/msg_xxx.json
2. FileEventBus.publish() 发布 FileEvent
3. Internalizer 被唤醒，读取 msg_xxx.json
4. Internalizer 调用 move_to_done() 将文件移到 done/ 子目录
5. 第 3 步和第 4 步之间没有锁保护
```

**关键代码路径：**

| 操作 | 文件 | 函数 |
|------|------|------|
| 写入文件 | `src/brain/kernel/event_bus.py:105` | `_write_file()` |
| 文件加锁 | `src/brain/kernel/event_bus.py:99` | `_get_lock()` → `asyncio.Lock()` |
| 归档移动 | `src/brain/kernel/state_store.py:73` | `move_to_done()` → `shutil` |
| 读取文件 | 各 Agent 的 `execute()` | `json.loads(path.read_text())` |

### 1.2 当前锁机制

`FileEventBus._get_lock()` 为每个文件路径提供一把 **互斥锁**（`asyncio.Lock`），不区分读/写，只保护并发写入，不保护读-归档冲突。读操作在锁外执行。

### 1.3 竞态窗口

```
时间线:
  T1: Internalizer 读取 msg_001.json 内容 (无锁)
  T2: MemoryConsolidator 调用 move_to_done() 归档 msg_001.json
  T3: Internalizer 尝试再次读取 msg_001.json → 文件已移动，读失败
```

当前设计中各文件通常只被一个 Node 消费一次，上述竞态在现状下触发概率低。但以下场景会放大风险：

- 启用 `memory_consolidator` 节点（对 pipeline 文件做批量归档）
- 启用 `dead_letter_router` 节点（对过期文件做回收）
- 引入多实例部署（同类型 Node 多实例）

---

## 2. 问题本质：归档需要"终结"语义

### 2.1 优先级的两难

**如果归档锁优先级高（当前模式）**：归档可以先抢到锁执行，但正在读文件的 Node 苏醒后会尝试访问已销毁的文件。

**如果归档锁优先级低**：不影响读服务，但在高并发下归档可能永远等不到所有读操作完成（"归档饥饿"）。

### 2.2 根因

无论优先级如何调整，**单靠"谁先拿到锁"无法实现"终结"语义**。归档操作真正需要表达的是：

> "从这一刻起，不再接纳新的读取请求，待现有读取全部结束后，我执行销毁。"

这是一个**两阶段操作**，不是单纯的锁获取。

---

## 3. 解：两阶段"门闩"模式（Terminable Shared Lock）

### 3.1 设计思路

**阶段 1 — 关门**
- 引入原子状态标志位 `state`
- 归档线程将状态从 `OPEN` 改为 `CLOSING`（CAS 原子操作）
- 一旦 `CLOSING`，所有新到达的读请求直接返回错误，不进入等待队列

**阶段 2 — 等待现有读者 + 执行归档**
- 关门成功后，归档线程等待所有活跃读者释放
- 因为新请求被拒绝，只需等待当前活跃的读锁全部释放
- 全部释放后执行归档，状态改为 `ARCHIVED`

### 3.2 状态机

```
        ┌─── 获取读锁/释放读锁 ───┐
        ▼                          │
     [ OPEN ] ──── archive() ────> [ CLOSING ]
        ▲                              │
        └────── 不支持取消 ───────────┘
                                       │
                           所有读者释放后自动转换
                                       │
                                       ▼
                                  [ ARCHIVED ]
```

| 状态 | 含义 | 新读请求 | 已有读锁 | 文件可访问 |
|------|------|---------|---------|-----------|
| `OPEN` | 正常服务 | 允许 | 有效 | 是 |
| `CLOSING` | 归档已发起 | 拒绝 | 仍有效直到释放 | 是 |
| `ARCHIVED` | 归档完成 | 拒绝 | 无 | 否 |

### 3.3 与其他模式的对比

| 模式 | 读并发 | 写互斥 | 终结语义 | 适用场景 |
|------|--------|--------|---------|---------|
| `asyncio.Lock` | 否 | 是 | 否 | 当前 FileEventBus |
| `asyncio.Semaphore(n)` | 是 | 否 | 否 | 简单并发读 |
| `asyncio.Condition` | 是 | 可模拟 | 否 | 需要等待特定条件 |
| **TerminableSharedLock** | 是 | 是(归档) | **是** | 文件生命周期管理 |

---

## 4. Python/asyncio 实现

### 4.1 核心类

```python
# src/brain/kernel/terminable_lock.py
from __future__ import annotations

import asyncio
from enum import Enum, auto
from typing import Any


class LockState(Enum):
    OPEN = auto()
    CLOSING = auto()
    ARCHIVED = auto()


class FileLockedError(Exception):
    """文件已被归档或正在归档中，无法获取读锁。"""

    def __init__(self, path: str, state: LockState) -> None:
        self.path = path
        self.state = state
        super().__init__(f"文件 {path} 处于 {state.name} 状态，无法获取读锁")


class TerminableSharedLock:
    """可终结的共享读锁。

    支持多个并发读者，支持一次归档操作（不可逆）。
    归档通过两阶段门闩实现：先关门拒绝新读者，等待现有读者完成后再执行销毁。

    用法::

        lock = TerminableSharedLock("inbox/pending/event_xxx.json")

        # 读者
        async with lock.reader():
            content = read_file(lock.path)

        # 归档者
        success = await lock.archive(lambda: move_to_done(lock.path))
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self._state = LockState.OPEN
        self._active_readers = 0
        self._readers_done = asyncio.Event()
        self._mutex = asyncio.Lock()  # 保护状态变更

    @property
    def state(self) -> LockState:
        return self._state

    def reader(self) -> "_ReaderContext":
        """返回一个可 ``async with`` 的读锁上下文管理器。

        若文件处于 CLOSING 或 ARCHIVED 状态，进入上下文时抛出 :class:`FileLockedError`。
        """
        return _ReaderContext(self)

    async def _acquire_reader(self) -> None:
        """获取读锁。

        在 OPEN 状态下直接递增计数；
        在 CLOSING/ARCHIVED 状态下抛出异常。
        """
        async with self._mutex:
            if self._state != LockState.OPEN:
                raise FileLockedError(self.path, self._state)
            self._active_readers += 1
            self._readers_done.clear()  # 有新读者，清除"全部完成"信号

    async def _release_reader(self) -> None:
        """释放读锁。

        若读者归零且状态为 CLOSING，通知归档者。
        """
        async with self._mutex:
            self._active_readers -= 1
            if self._active_readers == 0 and self._state == LockState.CLOSING:
                self._readers_done.set()

    async def archive(self, do_archive: Any) -> bool:
        """执行归档操作（两阶段门闩）。

        阶段 1：将状态从 OPEN 改为 CLOSING（关门）。
        阶段 2：等待所有活跃读者完成，然后执行 do_archive。

        Parameters
        ----------
        do_archive : callable or coroutine
            归档操作（同步或异步），在读者全部释放后执行。

        Returns
        -------
        bool
            True 表示归档成功，False 表示已被其他人归档或已在归档中。
        """
        # 阶段 1：关门
        async with self._mutex:
            if self._state != LockState.OPEN:
                return False  # 已经在归档或已归档
            self._state = LockState.CLOSING
            # 如果当前没有活跃读者，直接设置完成信号
            if self._active_readers == 0:
                self._readers_done.set()

        # 阶段 2：等待所有活跃读者完成
        # 此时不可能再有新读者进入（CLOSING 状态拒绝新读者）
        await self._readers_done.wait()

        # 执行归档
        if asyncio.iscoroutinefunction(do_archive) or asyncio.iscoroutine(do_archive):
            await do_archive
        elif callable(do_archive):
            do_archive()

        # 标记为已归档
        async with self._mutex:
            self._state = LockState.ARCHIVED

        return True


class _ReaderContext:
    """TerminableSharedLock 的读锁上下文管理器。"""

    def __init__(self, lock: TerminableSharedLock) -> None:
        self._lock = lock

    async def __aenter__(self) -> "TerminableSharedLock":
        await self._lock._acquire_reader()
        return self._lock

    async def __aexit__(self, *args: object) -> None:
        await self._lock._release_reader()
```

### 4.2 集成到 FileEventBus

```python
# src/brain/kernel/event_bus.py 中的修改

from src.brain.kernel.terminable_lock import TerminableSharedLock

class FileEventBus:
    def __init__(self, nodes, data_dir=None):
        # ... 现有初始化 ...
        self._file_locks: dict[str, TerminableSharedLock] = {}  # 从 asyncio.Lock 升级

    def _get_lock(self, path_key: str) -> TerminableSharedLock:
        if path_key not in self._file_locks:
            self._file_locks[path_key] = TerminableSharedLock(path_key)
        return self._file_locks[path_key]

    async def archive_file(self, file_path: str, do_archive) -> bool:
        """对文件执行安全归档。"""
        lock = self._get_lock(file_path)
        return await lock.archive(do_archive)
```

### 4.3 Node 中的读取保护

```python
# 在 Agent.execute() 中，读取 pipeline 文件时使用读锁：

async def execute(self) -> list[FileUpdate]:
    bus = self._bus  # type: FileEventBus
    lock = bus._get_lock("pipeline/message_queue/msg_001.json")

    try:
        async with lock.reader():
            data = json.loads(path.read_text(encoding="utf-8"))
    except FileLockedError:
        logger.debug("文件已被归档，跳过: %s", path)
        return []
    # ... 正常处理 ...
```

---

## 5. 何时需要此机制

### 5.1 当前不需要的场景

当前系统中大部分 pipeline 文件只被**一个 Node 消费一次**，消费后立即 `move_to_done`。在这种单生产者-单消费者模式下，竞态窗口极小（纳秒级），不需要门闩锁。

### 5.2 未来需要的场景

| 场景 | 触发条件 | 风险 |
|------|---------|------|
| `memory_consolidator` 启用 | 批量归档 evening/midnight 的 pipeline 文件 | 同时有其他 Node 在读 |
| `dead_letter_router` 启用 | 按 TTL 回收过期文件 | 文件可能仍被引用 |
| 多实例 Node | 同类型 Node 多实例并发处理同一批文件 | 一个实例归档后另一个读失败 |
| 跨文件系统部署 | `move_to_done()` rename 不保证原子性 | rename 中间态 |

### 5.3 最低侵入方案

如果暂时不需要完整的门闩锁，可以先做**防御性 rename**：`move_to_done` 改为 copy + unlink（异步删除），写入新文件后旧文件延迟删除，读失败时检查 done/ 目录。当前代码已经用 `shutil.copy2` + `unlink(missing_ok=True)` 做了这个兜底（见 `state_store.py:83-85`）。

但这只是降低概率，无法消除 root cause。

---

## 6. 参考

- 该模式在数据库论文中被称为 "lightweight shutdown" 或 "two-phase latch"
- 类似设计出现在 PostgreSQL 的 `LockAcquire` 中——归档等价于 `AccessExclusiveLock` + 等待所有 `AccessShareLock` 释放
- 在文件系统领域，Windows 的 `FILE_SHARE_DELETE` 语义与本设计有相似之处

---

## 7. 总结

| 维度 | 说明 |
|------|------|
| 当前状态 | `asyncio.Lock` 仅保护并发写，不保护读-归档冲突 |
| 改造成本 | 低——新增 `terminable_lock.py`（~100 行），FileEventBus 换掉 `_file_locks` 类型 |
| 性能影响 | 对于单消费者场景无影响；对多读者场景增加一次状态检查（纳秒级） |
| 紧迫度 | 低——当前单消费者模式下竞态窗口极小，但不妨碍提前设计 |
| 推荐做法 | 先保留本文档作为设计参考，等 `memory_consolidator` 或 `dead_letter_router` 启用时再实施 |
