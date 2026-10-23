# aurora_bot

持久 Bot 的领域组合层。Bot 拥有世界、目标、记忆和未来安排，每次认知使用独立的任务运行。

## 三个边界

| 包              | 职责                                               |
| --------------- | -------------------------------------------------- |
| `aurora_kernel` | namespace、hook、ctx、发现、依赖解析与模块生命周期 |
| `aurora_agent`  | 独立 ReAct 执行、消息配对、预算、追加输入与取消    |
| `aurora_bot`    | 外部事实、主体状态、记忆、领域操作和认知接线       |

通用宿主和任务执行器彼此独立。Bot 通过命名调用点连接它们，不再维护另一套认知循环或树状调度。

## 模块协作

运行行为通过 `aurora_kernel` 调用点扩展。模块声明自己的调用点和实现，普通 namespace 插件可参与同一宿主的路由。调用点由模块所有者约定参数与结果，缺失实现和优先级冲突在生命周期开始前失败。

需要资源、世界域和操作归档的模块使用 `aurora_bot.kernel` 的薄适配声明。`provides`、`requires` 和服务读取使用明确名称，例如 `"world"`、`"memory"`、`"ai"`；Python Protocol 不再充当服务键或装配依据。

模块自身的服务对象保存在 `ctx["bot.services"]`，多值贡献保存在 `ctx["bot.contributions"]`。这些是进程内装配状态。每次认知的消息、调用结果和观察前沿保存在运行局部对象，持久事实通过世界日志提交。

`contracts` 中保留资源、操作、世界记录等数据格式，以及部分协作者的静态类型提示。它们用于校验和阅读，不构成中央能力注册表；扩展 hook 不需要先新增一个契约类。

## 入口

- `runtime.assemble_runtime()`：同步装配，可注入离线模型或已经准备的服务。
- `runtime.compose_runtime()`：准备资源并返回门面与生命周期。
- `runtime.run_runtime()`：驱动模块生命周期与前台。
- `AuroraRuntime.run()` / `run_from_event()`：先形成世界事实，再调用认知入口。

命令、配置、凭据和进程环境由 `aurora_cli` 负责。认知调用点、持久边界和运行限制见 [engine README](engine/README.md)，通用组合机制见 [kernel README](../aurora_kernel/README.md)。
