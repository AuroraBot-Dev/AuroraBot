# 0200：Agent 中心运行时架构

状态：已接受
日期：2026-07-24
来源：取代 RFC 0100、0102、0106、0107 中关于 Kernel、ops、Platform 依赖方向与运行时组合的决定

## 决定

AuroraBot 采用 `ARCHITECTURE.md` 描述的两条正交路径：

- 热路径由 `src.engine` 完整拥有。engine 管理 Task/Agent 状态、邮箱、Activity、因果边界和完整 pump，通过 Port 调用模型、工具与自动记忆服务。
- 检查路径由根级 `ops` 包提供。ops 负责输入规范化、命令路由、状态检查和调试接口，不参与 engine pump。
- `aurora` 是唯一组合根，创建具体实现并注入 Port，管理平台选择、主循环与关闭顺序。

## 包边界

| 包 | 职责 | 可依赖 |
| --- | --- | --- |
| `src/contracts` | 跨层不可变 DTO 与 Port Protocol | 标准库 |
| `src/utils` | 纯通用工具 | 标准库 |
| `src/config` | TOML 加载、校验与配置快照 | contracts |
| `src/prompt` | 提示词目录与装配 | contracts |
| `src.engine` | 完整 Agent 热路径与 SQLite 运行态 | contracts、utils |
| `src.ai` | `ModelProvider` 实现 | contracts、utils |
| `src.memory` | `MemoryStore` 实现 | contracts、utils |
| `src.agents` | 只读上下文并返回决策的 handler | prompt、contracts、utils |
| `src.platform` | 输入与外部效果适配器 | contracts、utils |
| `ops` | 命令、检查、调试与输入分发 | `src.contracts`、`src.utils` |
| `aurora` | 唯一进程组合根 | 所有下层 |

`src.sandbox` 保持孤立，只依赖 utils，当前运行时不启用。

## 强制约束

- Agent handler 只读取 `AgentContext` 并返回 `AgentDecision`，不得直接写运行态、调用 Provider 或平台 Client。
- Platform 不导入 ops 或 engine；交互输入和 AMP 入口通过 contracts Port 注入。
- engine 不导入 ai、memory、agents、prompt、config、platform 或 ops。
- ops 不被 engine、Platform 或其他热路径实现依赖。
- `src` 不导入 `aurora`。
- 所有跨层 DTO 和 Protocol 只定义于 contracts。
- 一个进程只有一个 engine 所有者。

## 运行时所有权

engine 的一次 pump 按顺序处理工具恢复、AMP 摄入、过期与消息领取、Agent turn、决策写入、工具派发、模型派发、自动记忆和终态归档。具体 Provider、ToolExecutor 与 MemoryStore 由 aurora 注入。

ops 仅持有 engine 的公开操作与查询端口，用于 `/status`、`/pump`、`/task`、`/agent`、普通会话输入及调试投影。engine 主循环不调用 ops。

## 配置与迁移

结构配置按 `ARCHITECTURE.md` 的包级 TOML 拆分。迁移必须保持未知键启动前失败、profile 仅覆盖 runtime、密钥仅来自显式命名环境变量，并将运行数据迁移到 `data/engine`。不提供旧工作区的隐式兼容读取。

源代码迁移按以下顺序进行：共享 contracts、engine 热路径、ops sidecar、aurora 组合根、配置与存储路径。每一步均由导入边界和行为测试约束。
