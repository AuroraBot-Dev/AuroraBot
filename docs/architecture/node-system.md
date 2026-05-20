---
title: 节点系统
description: Node / Agent / Router 的设计细节——文件描述符、锁策略、状态机与代码对应。
order: 4
---

# 节点系统

认知层的认知能力由节点承载。节点不是"AI Agent"的简单封装——它是文件驱动认知拓扑中的**原子工作单元**。代码实现见 `src/brain/kernel/base.py`。

## 类的层次

```
Node (ABC)             # 抽象基类：id, type, guards, produces, state
├── Agent(Node)        # LLM 驱动型：think(), system_prompt
└── Router(Node)       # 纯逻辑型：零 LLM，控制结构原语
```

**挼挼如是说**

> Agent 是会"想"的节点——它坐在桌前，翻开输入文件，用 LLM 思考一番，然后写出新文件。Router 是不会"想"的节点——它就是逻辑电路，看到条件 A 就发往节点 B，看到条件 C 就发往节点 D。快、便宜、可预测。

## Node 基类

```python
class Node:
    id: str                          # 唯一标识
    type: "agent" | "router"         # 节点类型
    guards: List[FilePattern]        # 守护的文件模式（glob）
    produces: List[FileDescriptor]   # 产出的文件描述符
    state: NodeState                 # 当前状态
```

### 生命周期

```
IDLE → READY → RUNNING → IDLE
                  ↓
              WAITING → READY
                  ↓
               ERROR（触发修复 Router）
                  ↓
            TERMINATED（子图关闭）
```

### 核心方法

| 方法                                | 职责                                                                                                             |
| ----------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `on_event(event: FileEvent) → bool` | 判断此事件是否应激活本节点。默认遍历 `guards`，命中任意一个即返回 `True`。子类可覆写以实现版本号比对、并发门控等 |
| `execute() → List[FileUpdate]`      | 执行一步认知操作，返回文件变更列表。Agent 调用 LLM，Router 执行纯逻辑                                            |
| `on_complete()`                     | 执行完成钩子。默认重置为 IDLE，子类可保持 READY 等待后续事件                                                     |

## Agent

```python
class Agent(Node):
    host: ApplicationHost             # 应用宿主
    system_prompt: str                # 系统提示词

    async think(messages) → str      # 调用 LLM 网关
```

Agent 的 `execute()` 通常：读取 guards 中的文件 → 调用 `think()` → 将 LLM 输出写入 produces 中的文件。

**设计约束**：

- 不自己调用 LLM API——走 `think()` 方法，内部经过统一 LLM 网关
- 不直接访问 App 的私有文件
- 产出是确定性文件，可版本回滚

## Router

```python
class Router(Node):
    host: ApplicationHost | None     # 部分 Router 需要宿主能力
```

Router 是控制结构原语。当前已实现的 Router 类型（`src/brain/nodes/routers/`）：

| Router             | 功能                                           |
| ------------------ | ---------------------------------------------- |
| `SwitchRouter`     | 检查文件内容条件，激活不同下游                 |
| `WaitRouter`       | 等待多个文件满足条件后触发                     |
| `MergeRouter`      | 将多个输入文件汇总为一个                       |
| `HeartbeatRouter`  | 定时产生脉冲事件，驱动自主意识                 |
| `ReflexRouter`     | 缓存规则匹配，短路径响应（零 LLM）            |
| `FanOutRouter`     | 将事件扇出到多个下游节点                       |
| `TerminalRouter`   | 关闭一个子图                                   |
| `MemoryAgent`      | 将执行结果写入记忆存储                         |

## 文件相关数据结构

### FileDescriptor

```python
@dataclass(slots=True)
class FileDescriptor:
    path: str                            # 文件路径
    schema: str = "json"                 # 格式（json / yaml / text / ...）
    lock: str = LockPolicy.WRITE_OVERWRITE  # 默认锁策略
```

声明一个节点**将产出**的文件。

### FilePattern

```python
@dataclass(slots=True)
class FilePattern:
    pattern: str    # glob 模式，如 "intent.json" 或 "data/kernel/*.json"

    def match(self, file_path: str) -> bool
```

声明一个节点**守护**的文件模式。支持 glob 通配符。

### FileEvent

```python
@dataclass(slots=True)
class FileEvent:
    path: str                # 变更文件路径
    change_type: str         # 变更类型
    timestamp: str           # 时间戳
    version: int = 0         # 当前版本号
    metadata: dict = {}      # 附加元信息
```

文件变更事件，由事件总线广播。节点通过 `on_event()` 判断是否应激活。

### FileUpdate

```python
@dataclass(slots=True)
class FileUpdate:
    descriptor: FileDescriptor   # 目标文件
    content: Any                 # 写入内容
    mode: str = "overwrite"      # 写入模式
```

节点执行完成后产出的文件变更。

## 锁策略

```python
class LockPolicy:
    READ_ONLY = "read_only"           # 只读
    WRITE_OVERWRITE = "write_overwrite"  # 可覆盖
    APPEND_ONLY = "append_only"       # 只可追加

    @staticmethod
    def locked_by(node_id: str) -> str:
        return f"locked_by_{node_id}"  # 动态独占锁
```

每个 `FileDescriptor` 声明其锁策略。运行时，锁机制确保同一时刻只有一个节点以写入模式操作同一文件。

## 下一步阅读

- 想看完整的认知拓扑图：读 [认知架构](./brain-architecture.html)
- 想理解调度机制：读 [内核运行时](./kernel-runtime.html)
