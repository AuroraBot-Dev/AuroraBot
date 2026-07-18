# RFC 0001：架构基准与因果闭环

状态：已接受
日期：2026-07-11
修订：2026-07-15

## 背景

自主智能体必须可靠区分“模型产生内容”“请求环境能力”和“环境效果已经完成”。AuroraBot 因此以可审计的
因果记录连接认知、模型、平台与运行时，并让每一层承担单一职责。

RFC 0012 取代本文最初定义的 Node/Graph、手动周期和 JSON 运行态条款；本文继续定义稳定的模块、效果和工作区边界。

## 决策

### 核心原则

Kernel 负责事件、Task/Agent 状态、邮箱、Activity 调度与因果边界；Agent handler 负责认知；Platform 负责环境感知与
效果执行。
任何一层不得替代另一层的职责。

### 模块边界

| 位置 | 责任 |
| --- | --- |
| `src/kernel` | AMP 接管、Kernel record、工作区、图、周期、Episode、状态和因果限制。 |
| `src/ai` | 宽泛模型网关：模型角色、能力协商、调用、计费、节流与中断。 |
| `src/localhost` | CLI 与 Dashboard 共用的业务用例、scheduler 和开发者调试能力；不提供 Dashboard 路由。 |
| `src/dashboard` | Dashboard 的后端路由/API 适配；只依赖 `localhost`。前端不由本仓库管理。 |
| `src/platform` | 平台生态适配、AMP 归一化、能力目录和效果执行。 |
| `src/apps` | 内建原生 AMP-MCP 应用，经 Platform 接入。 |
| `src/nodes` | 自包含的内建认知节点。 |
| `src/sandbox` | 独立沙箱组件；未经图与能力声明不进入认知闭环。 |
| `src/utils` | 无上层依赖的纯通用工具。 |

长期记忆、沙箱和提示词编排不是 Kernel 的预设顶层子系统。需要时，它们以职责单一的节点或节点能力进入图，
并遵守相同的事件、预算和因果约束。

### 运行图

当前首轮图由 RFC 0008 定义：外部 AMP 或 `system.tick` 创建独立 Episode，`builtin.fast_gate` 处理简单任务或
升级 `builtin.native_agent`，模型与效果均通过异步事件在后续周期恢复。Kernel 在调用节点前提供只读认知快照，
包括根 AMP、Episode 内事实、SOUL 内容及哈希、能力目录、预算和调度状态。

Node 只能发布声明过的事件；不得直接调用 Platform client、修改共享工作区或自行执行外部效果。

### 效果闭环

`effect.requested` 是决策，不是执行成功。Platform 是唯一可以执行效果的一层，并且必须以新的 AMP
`effect.succeeded` 或 `effect.failed` 事件回写结果。效果回执最早在下一周期进入图。

### 周期与自环

一个周期只消费该周期开始时已经就绪的记录集合。本周期产生的记录最早在下一周期调度。所有记录必须具有
因果父级；所有 Episode 受轮次、模型调用数、工具调用数和持续时间限制。任何可能成环的路径必须显式标记推进边。

`system.tick`、反思、探索和效果反馈都是普通事件。自发性不得绕过能力授权、预算、冷却、优先级或终止条件。

### 工作区

Kernel 工作区只有三个顶级业务目录：

```text
data/kernel/inbox/     # 平台投递的 AMP JSON
data/kernel/process/   # 已接管记录、Episode、租约、中间产物和效果请求
data/kernel/archive/   # 已完成、失败或过期的记录与 Episode
```

这是共享可见工作区，不是任意共享可写目录。节点通过 Kernel API 创建事件或更新被授予的状态键；节点间协作
优先采用追加事件而非覆盖文件。所有生产者必须先写临时文件，再原子改名。

## 当前边界

- 首轮闭环不提供长期记忆、跨 Episode session 历史或认知图内沙箱。
- Kernel 不理解 MCP、QQ、Discord、OneBot 或任意平台私有对象。
- Dashboard 不成为第二个运行时。

## 验收标准

1. 一个 AMP 输入或自主 tick 创建一个有界、可审计的 Episode。
2. 模型完成和 Platform 回执均以新记录在后续周期恢复认知图。
3. 每条记录可追溯到根输入、产生它的节点和单一因果父级。
4. 未授权节点不能直接执行效果或写入其他节点状态。
