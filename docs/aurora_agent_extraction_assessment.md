# 执行包边界与独立性

核对基线：W08（2026-11-27）。本页保留安装与能力复用的判断标准；最初的拆包评估见[历史归档](archive/2026-11-09/aurora_agent_extraction_assessment.md)。完整职责见[架构](aurorabot-design-v0.2.3.md)。

## 安装边界

| 能力 | 独立使用时不需要 | 组合方式 |
| --- | --- | --- |
| core | TOML、模型、工具、Bot 或界面 | 宿主直接提供登记、ctx、连接与生命周期 |
| control | agent、模型、Bot、CLI/API | 选择四种控制组件，绑定状态、条件资源与执行连接 |
| tools | agent、模型、Bot、world | 显式工具定义、执行器与静态/动态集合 |
| model 基础包 | 配置包、供应商 SDK、MCP、agent/Bot | 协议与资源；config/litellm 按 extra 安装 |
| MCP 客户端 | tools、world、model、agent/Bot | tools/world 桥分别安装和启用 |
| agent 基础包 | config、Bot、CLI/API、供应商 SDK | 使用 core/control/tools/model；配置桥另选 |
| world 基础包 | config、MCP、agent/Bot | records 和 sources 分开启用；配置/环境来源可选 |
| memory 基础包 | agent/Bot、CLI/API、具体模型 SDK | 借用 embedding，显式分配 owner 与状态地址；compaction extra 另依赖 agent |
| host | model、tools、agent/Bot、CLI/API | 依据文件创建与连接任意已选组件 |
| Bot 基础包 | world、memory、MCP、供应商 SDK、CLI/API | 产品能力各自启用；预设依赖按 extra 安装 |

安装依赖、插件 requires、资源引用、生命周期依赖和执行连接是不同关系。一个发行包内有多个插件不表示拆包失败：拆 package 的依据是独立依赖和分发价值，拆插件的依据是能力可选性与公开定义归属。

## 状态和资源归属

control/agent/tools 定义属于各自命名空间；产品分配的消息、引导、运行和工作状态仍归 Bot，由实例绑定注入。工具不能根据某个 Bot WORK 地址反查 owner 或产品配置。

模型、数据库、MCP 连接由提供者持有。工具集合持有成员并负责关闭；成员借用的模型或服务仍由原提供者关闭。运行所有者只管理一次 agent 执行的接纳、等待和收尾，不复制 ReAct 算法。

memory 的索引策略、world 的视图保留和 Bot 的工作状态裁剪各归对应能力，不下沉到 core。新的公共能力应先说明实际消费者、状态所有者和资源生命周期，再决定是否需要新 package。

## 验证证据

- [安装边界回归](../tests/e2e/test_package_boundaries.py)禁止导入上层包，验证独立执行、工具往返和恢复。
- [元信息契约](../tests/contract/test_plugin_metadata.py)核对清单、真实导出、全部入口和历史定义去向。
- [分发验收](../tests/e2e/test_metadata_distribution.py)从 sdist 隔离构建，禁止运行包导入后读取静态目录。
- [完整预设回归](../tests/e2e/test_product_presets.py)验证资源就绪、来源触发、记忆与工具、恢复和关闭顺序。

依赖或分发变更还需在工作区外从 wheel 安装；不能用工作区可导入替代安装验收。执行命令见[开发指南](development.md)，已完成的验收记录见[变更记录](CHAGELOG.md)。

## 后续边界

独立 `aurora_harness` 尚未引入。安装助手是使用现有 Bot/Host/MCP 能力的产品预设，不等同于一个新的通用框架。应有实际消费者和清晰的资源、配置、交互责任后再设计该包。
