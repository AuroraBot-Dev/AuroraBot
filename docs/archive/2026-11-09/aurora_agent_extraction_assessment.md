# aurora_agent 拆包与 aurora_harness 独立化评估

> 历史归档：2026-11-09。保留当时的设计、计划与验收语境，不作为当前功能承诺或操作指南；当前入口见 [文档索引](../../INDEX.md)。

评估日期：2026-11-01。本文说明 control、agent 与 bot 的职责边界，以及独立 harness 的后续工作；实现与验收记录见 [变更记录](../../CHAGELOG.md)。实施状态：阶段一（独立组件包）与阶段二（运行调度解耦）已完成；阶段三（独立 harness 最小宿主）尚未开始，恢复与裁剪辅助的可复用提取随该阶段处理。

## 1. 结论与目标

`aurora_control` 与 `aurora_agent` 是与 `aurora_bot` 平级的独立包。control 承载执行契约和基础控制组合，agent 承载模型、工具、ReAct 和运行管理。独立 harness 的产品装配与仓库独立化建立在这两个包之上。

当前实现已经具备拆分基础：ReAct、模型调用和工具执行通过 ctx、状态绑定与显式连接协作，主要依赖 `aurora_core` 和 `aurora_adapter.model`。需要重点处理的边界是运行调度、默认装配、资源所有权和恢复语义。

本评估将 `aurora_harness` 理解为能够独立装配、运行、观察和管理 agent 的项目，允许继续依赖 `aurora_core` 与 `aurora_adapter.model`。如果目标还包括脱离 Aurora 微内核，则需要另行评估 ctx、注册表、连接和生命周期接口的替换成本。

拆分完成的核心标准是：在未安装 `aurora_bot` 的环境中，使用 `aurora_agent` 及其声明依赖完成模型与工具往返、运行中引导、取消、状态恢复和资源关闭。

## 2. 实现依据

| 实现位置 | 当前职责与边界 | 对拆分的意义 |
| --- | --- | --- |
| [react.py](../../../packages/aurora_agent/src/aurora_agent/react.py) | 六阶段 ReAct 循环；外部提供状态地址和阶段连接；执行入口等待一次激活收束 | 循环本身适合直接成为 agent 包的组件 |
| [control/](../../../packages/aurora_control/src/aurora_control) | 执行身份、状态绑定、执行连接，以及顺序、分支、循环、并行组件 | 是模型、工具和 ReAct 共用的执行基础 |
| [model.py](../../../packages/aurora_agent/src/aurora_agent/model.py) | 使用注入的 ModelClient 完成一次模型调用，将流式输出和终态写入 ctx | 属于 agent 执行集成，模型协议继续由 adapter 提供 |
| [tools.py](../../../packages/aurora_agent/src/aurora_agent/tools.py) | 工具定义、实例工厂、参数校验、执行钩子、超时和结构化结果 | 可作为独立 agent 的工具执行能力 |
| [react_defaults.py](../../../packages/aurora_agent/src/aurora_agent/react_defaults.py) | 组织上下文、解释模型决定、接纳工具观察和处理未完成轮次 | 是可选的默认 agent 策略，不依赖消息平台 |
| [runtime.py](../../../packages/aurora_agent/src/aurora_agent/runtime.py) | 提交引导、管理运行句柄、串行激活、取消和结束边界复查 | 通过显式执行入口连接宿主，不依赖 DefaultAssembly |
| [assembly.py](../../../packages/aurora_bot/src/aurora_bot/assembly.py) | 配置读取、模型与工具创建、阶段连接、启动关闭、恢复修正和工作状态清理 | 同时承载产品装配和可复用的运行管理语义，需要按职责拆开 |
| [operations.py](../../../packages/aurora_bot/src/aurora_bot/operations.py) | 按实例分发提交、激活和取消操作 | 分发机制可复用，公共操作 ID 与插件登记需要单独处理兼容 |

`ReActAgent` 不创建后台调度任务，也不自动订阅 world。`ReActDefaults` 将模型文本保存为内部上下文，不自动发送用户消息。这些约束适用于聊天、后台任务和命令行等不同宿主，应继续保留。

[ReAct 示例](../../../tests/fixtures/runtime_apps/react_agent/main.py) 使用独立 AgentRuntime 和 agent 组件完成显式装配。[包边界测试](../../../tests/e2e/test_package_boundaries.py) 验证无 bot 环境的插件发现、模型工具往返与恢复；安装层面的独立性由干净 wheel 环境验收。

## 3. 建议的包边界

| 能力 | 建议归属 | 边界要求 |
| --- | --- | --- |
| 执行契约与四种控制组合 | `aurora_control` | 仅依赖 core，允许第三方插件单独使用 |
| `react.py` | `aurora_agent` | 保留显式阶段连接和外部状态绑定 |
| `model.py` | `aurora_agent` | 只负责将模型协议接入执行组件，不引入具体供应商 SDK |
| `tools.py` | `aurora_agent` | 保留工具协议与执行机制；具体业务工具由应用或插件提供 |
| `react_defaults.py` | `aurora_agent` 的可选默认实现 | 核心循环允许采用其他阶段实现 |
| runtime 与运行回执类型 | `aurora_agent` | 不引用 DefaultAssembly 或 bot 私有成员 |
| bot 实例运行操作分发 | `aurora_bot` | 通过公共操作使用通用 AgentRuntime |
| 恢复修正与执行数据清理 | agent 装配辅助能力 | 状态地址和保留策略显式传入，不绑定 bot 的固定配置 |
| 产品默认配置、凭证解析、默认装配、CLI 命令 | `aurora_bot`，由 harness 提供自己的装配 | 负责选择组件、资源与产品入口 |
| 世界事件筛选、唤醒条件、消息路由和回复策略 | bot 或外围插件 | 通过引导入口、工具和连接使用 agent |

control 的职责独立于模型与 ReAct。第三方插件可以只依赖 control 组织普通业务执行，避免带入模型适配依赖。微内核继续提供通用登记、状态、连接、调用和生命周期设施；control 不扩展为持久任务调度平台。

建议的直接依赖关系如下：

```text
aurora_bot ────────┐
                  ├──→ aurora_agent ──→ aurora_adapter.model ──→ aurora_core
aurora_harness ───┘            └──→ aurora_control ────────────→ aurora_core

第三方流程插件 ───────────────────→ aurora_control

bot / harness 可直接使用 core 和 adapter.model 的宿主、配置及工厂设施。
```

`aurora_agent` 不得依赖 `aurora_bot`，也不应要求安装 CLI、API 或界面包才能执行。harness 的独立性应由依赖清单和安装验收保证。

## 4. 运行管理与资源所有权

### 4.1 调度器依赖明确的执行入口

AgentRuntime 通过 `get_agent` 获取实例，通过 `execute` 等待一次激活及清理，通过 `is_executing` 查询完整执行期间的占用。DefaultAssembly 直接提供这些入口，独立宿主也可自行装配。接口保留单实例单调度所有者约束，避免显式激活与 runtime 管理并行争用同一 agent。

运行管理需要保留以下语义：

- 同一激活期间提交的引导按现有规则共享运行句柄。
- finish 边界到达的输入由后续激活接纳，成功结束后复查 pending。
- 失败或取消停止自动后续调度，未消费输入等待显式提交或激活。
- 等待者取消不隐式取消 agent；取消运行必须走明确入口。
- 运行句柄是进程内对象，不进入持久化快照，也不直接作为传输层响应序列化。

### 4.2 资源由明确的装配所有者管理

模型和工具资源由装配创建并管理。执行组件使用注入的资源，通用 runtime 管理自己创建的任务。宿主停止时先关闭提交入口、取消并等待运行收尾，再关闭工具和模型，最后由宿主完成状态落盘。

独立 harness 应能复用这一生命周期约定，不需要继承 bot 装配。资源工厂失败、部分装配失败和关闭失败的清理责任也应沿用明确的所有权约束。

### 4.3 恢复与清理需要可复用实现

DefaultAssembly 中的中断运行状态修正、pending 工具结果保留、已消费 inbox 裁剪和临时工作状态清理，包含 agent 的运行语义。建议将这些能力提取为小范围的装配辅助实现，由 bot 和 harness 提供状态地址及具体保留策略。

恢复必须继续区分“数据可恢复”和“执行可续跑”：

- `progress` 表示引导已纳入上下文，不代表业务要求已经完成。
- 快照中的 running 状态不对应重启后的真实任务，应明确标记中断。
- 未完成工具轮次应接纳已有结果，并明确表示缺失结果，不自动重跑可能产生副作用的动作。
- 启动时不自动激活恢复出的输入；是否激活由宿主策略决定。
- 清理不得删除其他实例的数据或后续恢复仍需要的工具结果。

## 5. 命名与迁移边界

| 风险 | 建议处理方式 |
| --- | --- |
| Python 导入路径 | 执行契约使用 aurora_control，agent 能力使用 aurora_agent；不提供 bot 兼容导出 |
| 公共 ID 与持久化地址 | control 和 agent 定义分别归属 org.aurora.control、org.aurora.agent；bot 装配分配的业务状态仍归属 bot |
| 插件发现与依赖声明失配 | 同步核对 entry point、Plugin.name、requires 和显式启用列表 |
| 重复插件入口 | 每个插件只提供规范名称，不提供旧名别名或重复定义 |
| runtime 与装配职责交叉 | 用单一调度所有者和明确资源所有权约束接口，验证取消及关闭边界 |
| 恢复逻辑在两个项目重复实现 | 提取共享辅助能力，宿主只提供地址、配置和策略 |
| 工作区掩盖缺失依赖 | 构建并在无 bot 的干净环境中安装验证，不能只依赖 workspace 内测试 |

插件发现分组为 `aurora.plugins`，入口为 `aurora_control`、`aurora_agent.model`、`aurora_agent.react`、`aurora_agent.tools` 和 `aurora_agent.react_defaults`。运行时不映射旧 ID 或旧入口；带有旧控制状态地址的快照须离线转换或使用新的数据目录，不自动改写用户数据。

当前插件发现只加载显式启用的入口，`requires` 用于验证依赖已启用，不会自动启用依赖。安装 `aurora-agent` 不能替代宿主对插件清单的选择。

工具执行使用的 `jsonschema`、`referencing` 等依赖应随实现归属进入 agent 的包声明。工作区成员、包源、类型检查路径、覆盖率范围、示例和验收脚本也需要同步核对。

## 6. 分阶段实施与验收

### 阶段一：建立独立组件包

分别建立 `packages/aurora_control` 和 `packages/aurora_agent`，将执行契约、四种控制组合与 agent 能力按职责归属，使用各自的命名空间和插件名称，更新 bot 装配的导入及包依赖。

验收要求：

- agent 的代码和包依赖均不反向引用 bot。
- 对应组件测试及模型、工具往返集成测试通过。
- bot 默认装配仍能使用迁出的组件。
- 插件定义能完整登记，无重复身份和缺失依赖。

### 阶段二：解耦运行管理和通用装配能力

将 runtime 对 DefaultAssembly 的私有依赖改为明确接口，提取运行回执和必要的恢复、清理辅助能力。bot 保留自己的配置、公共入口与默认产品装配。

验收要求：

- 提交、等待、取消和显式激活的所有权规则明确且有行为验证。
- 覆盖运行中引导、finish 边界提交、失败和取消后的 pending 处理。
- 覆盖恢复时的中断状态、未完成工具轮次和跨实例清理隔离。
- 关闭流程等待运行收尾，工具与模型按资源所有权释放。

### 阶段三：验证独立 harness 的最小宿主

提供一个仅使用 agent 及其声明依赖的最小宿主，显式创建 core 设施、模型和工具，完成启动、提交、观察、取消、关闭与再次启动。

验收要求：

- 在没有安装 `aurora_bot` 的干净环境中安装并运行。
- 使用离线模型完成至少一次模型—工具—模型闭环。
- 验证运行中引导、取消、持久化恢复及资源关闭。
- 默认路径不依赖 bot 配置文件、bot 装配或 bot CLI 命令。
- 插件和定义使用自身命名空间，不依靠 bot 插件补齐或通过别名转发。

完成以上验收后，再确定 `aurora_harness` 的产品配置、交互入口、发布方式和仓库拆分。第一阶段无需同时引入多 agent 调度、通用 workflow 平台或新的恢复协议。

## 7. 收益、成本与决策建议

收益主要体现在三个方面：bot 与 harness 共享执行语义；第三方流程插件与 agent 扩展获得明确的依赖入口；未来独立发布可以沿已有包边界推进。宿主级恢复和裁剪策略的共享仍需在 harness 装配中明确。

组件迁移的改造范围相对明确，主要是导入、插件清单和包声明。运行管理与装配解耦的复杂度更高，集中在并发边界、关闭顺序、恢复数据保留和公共入口兼容。执行包的测试及安装验收见变更记录；独立 harness 的产品装配不据此承诺工期。

后续工作集中在 harness 的产品装配、资源与恢复策略、交互入口和发布边界。执行包的独立使用验收是基础，不代表 harness 产品已经完成。
