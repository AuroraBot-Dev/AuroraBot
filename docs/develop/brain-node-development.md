---
title: 认知节点开发
description: 基于 base.py + node_factory + topology.yaml 的认知节点开发方式。
order: 1
---

# 认知节点开发

认知节点（Brain Node）是 AuroraBot 认知系统中的插件化工作单元。目前节点体系已运行在生产电路中，开放给开发者扩展。

## 节点分类

| 类型     | 基类        | LLM 调用 | 执行时间  | 用途                     |
| -------- | ----------- | -------- | --------- | ------------------------ |
| `Agent`  | `Agent(Node)` | ✅       | 不确定    | 意图识别、规划、展开等   |
| `Router` | `Router(Node)` | ❌       | 可预测 | 条件分支、汇合、扇出、缓存匹配 |

Agent 执行时调用 `think()` 自动经过统一 LLM 网关注入系统提示词；Router 执行纯逻辑，零 LLM 开销。

## 三步添加一个新节点

### ① 编写节点类

继承 `Agent` 或 `Router`，实现 `guards` / `produces` / `execute()`：

```python
# src/brain/nodes/agents/my_agent.py
from src.brain.kernel.base import Agent, FileDescriptor, FilePattern, FileUpdate

class MyAgent(Agent):
    def __init__(self, node_id: str) -> None:
        super().__init__(node_id)
        self.guards = [FilePattern("inbox/event_*.json")]
        self.produces = [FileDescriptor("plans/my_plan.json")]

    async def execute(self) -> list[FileUpdate]:
        # 读 guards 中的文件 → think() → 写 produces 中的文件
        ...
```

Router 只需做纯逻辑运算，无 `think()`。

### ② 注册到节点工厂

在 `src/brain/kernel/node_factory.py` 的 `NODE_REGISTRY` 中注册：

```python
NODE_REGISTRY: dict[str, type[Node]] = {
    ...
    "my_agent": MyAgent,
}
```

如果节点需要 `host` 引用或接收额外 `config`，需要在 `NODE_NEEDS_HOST` / `NODE_ACCEPTS_CONFIG` 中声明。

### ③ 在拓扑配置中启用

在 `src/brain/nodes/topology.yaml` 添加节点：

```yaml
nodes:
  - id: my-agent
    type: my_agent
    enabled: true
    watch:
      - "inbox/event_*.json"
    config:
      some_param: value
```

`watch` 和 `emit`（可选）可覆盖节点类中的默认 `guards` / `produces`。多个节点通过文件模式隐式连边，无需声明上下游关系。

## 内置节点参考

`src/brain/nodes/agents/` 下已实现的 Agent：

| 文件                      | 节点类型（注册名） | 职责                     |
| ------------------------- | ----------------- | ------------------------ |
| `plan_agent.py`           | `planner`         | 用 LLM 将事件转为计划    |
| `expand_agent.py`         | `expander`        | 用 LLM 展开计划为动作    |
| `execute_agent.py`        | `executor`        | 调用 App 命令并判断结果  |
| `goal_generator_agent.py` | `goal_generator`  | 沉默时主动生成意图       |
| `reflex_learner_agent.py` | `reflex_learner`  | 从成功动作中学习反射规则 |
| `example_agent.py`        | `example`         | 示例节点（默认禁用）     |

`src/brain/nodes/routers/` 下已实现的 Router：

| 文件                 | 节点类型（注册名） | 职责                    |
| -------------------- | ----------------- | ----------------------- |
| `switch_router.py`   | `switch`          | 条件分支                |
| `wait_router.py`     | `wait`            | 等待条件满足            |
| `merge_router.py`    | `merge`           | 归并多个文件            |
| `heartbeat_router.py` | `heartbeat`       | 定时脉冲                |
| `reflex_router.py`   | `reflex`          | 反射规则匹配（短路径）  |
| `fanout_router.py`   | `fanout`          | 扇出到多个下游          |
| `terminal_router.py` | `terminal`        | 关闭子图                |
| `memory_agent.py`    | `memory`          | 写入记忆存储            |

## 设计约束

- Agent 不直接调用 LLM API——走 `think()` 经统一 LLM 网关
- Agent 不直接访问 App 的私有文件
- 节点本身无内部状态，每次 `execute()` 后理论上可回收
- 文件锁策略通过 `FileDescriptor.lock` 声明，总线自动执行

## 继续阅读

- 想理解认知架构：读 [认知架构](../architecture/brain-architecture.html)
- 想理解节点设计哲学与数据结构：读 [节点系统](../architecture/node-system.html)
- 想开发 App 插件：读 [App 开发指南](./app-development.html)
