---
order: 1
---

# 系统总览

AuroraBot 为一个长期存在的 Bot 提供世界、目标、记忆和行动环境。Bot 拥有世界日志、目标与记忆；一次认知执行通过请求与结果连接到她的持续生活，内部拓扑由执行器决定。进程退出不会结束她已经接受的目标或取消尚未到期的活动。

## 持续闭环

外部观察先进入 `WorldJournal`。节律根据轻量观察和显式循环状态分配推理机会，时间服务兑现 Bot 已经登记的活动。认知运行读取主体检查点与记忆快照，组装上下文后请求 LLM；目标修订、工具行动与结果再成为世界事实。

外围环境提供可发现的能力、明确的执行结果和恢复入口。Bot 可以建立或修订目标、暂缓或放弃目标、安排检查、展开证据，也可以结束当前认知并等待。节律策略只决定推理机会，记忆策略只分配可选经历的位置；二者不代替主体作出行动选择。

## 同级能力包

| 包                                                            | 职责                                                          |
| ------------------------------------------------------------- | ------------------------------------------------------------- |
| `src/aurora_bot/contracts`、`src/aurora_bot/utils`            | 公共值对象、能力端口、贡献契约与无上层依赖的工具              |
| `src/aurora_kernel`                                           | 模块无关的 namespace、hook、ctx、发现、依赖解析与生命周期监督 |
| `src/aurora_bot/kernel`                                       | Bot 契约、贡献、资源和世界域的装配适配                        |
| `src/aurora_bot/runtime`                                      | 从冻结装配创建 Bot 门面，绑定认知入口并驱动前台               |
| `src/aurora_bot/bot`                                          | 从世界提交投影主体目标、检查点和唤醒安排                      |
| `src/aurora_bot/clock`                                        | 独立兑现主体保存的未来安排                                    |
| `src/aurora_bot/world`                                        | 追加式世界日志、全局游标、域序号与 SQLite migration           |
| `src/aurora_bot/cadence`、`src/aurora_bot/rhythm`             | 世界与时间驱动的调度、可替换的规则或 GRU 策略及训练           |
| `src/aurora_bot/memory`、`src/aurora_bot/memory_model`        | 时间正确的经历读取、连续性与集合组装、规则或 TGN 排序及训练   |
| `src/aurora_bot/agents`、`src/aurora_bot/prompt`              | 不可变 Agent 定义、提示词目录与无 I/O 的四角色上下文装配      |
| `src/aurora_bot/engine`、`src/aurora_bot/tools`               | 单循环认知、工具目录、普通效果与委派                          |
| `src/aurora_bot/ai`、`src/aurora_bot/mcp`                     | LLM Provider 协议适配、MCP 连接与冻结工具目录                 |
| `src/aurora_bot/resources`、`src/aurora_bot/scopes`           | 资源寻址、版本与别名解析、领域声明与范围校验                  |
| `src/aurora_bot/operations`                                   | 统一命令与查询路由、回执、幂等及不确定效果处理                |
| `src/aurora_bot/artifacts`、`src/aurora_bot/resource_content` | 大对象内容存储、固定版本校验与实际定义正文归档                |
| `src/aurora_bot/instances`                                    | 从世界事实发现运行实例与确定历史版本                          |
| `src/aurora_bot/console`                                      | 本地异步终端、输入先入世界、领域指令入口                      |

功能包在运行期只引用自身、`contracts` 和 `utils`；模块声明可以引用 `kernel`，`runtime` 依赖 `kernel`。兄弟包的类型引用可放在 `TYPE_CHECKING` 中，实际能力经契约注入。外部库由使用它的包封装，数据库、SDK 与计算张量不泄漏到主体和消息契约。边界由 `tests/foundation/test_dependency_boundaries.py` 校验。

每个可装配包在 `module.py` 导出唯一 `MODULE`。替换能力时，公开操作、前台、认知唤起绑定和生命周期均使用实际选中的实例；失选默认实现不应读取自己的无关配置或产生连接效果。主体状态与时间服务分别装配，默认工具和时钟共享同一个 `BotStateStore`。

## 组合与发现

发现源包括安装内的 `aurora_bot` 包、项目本地 `extensions/plugins/` 与 `aurorabot_plugin` / `aurora_module` entry point。本地插件支持单文件或带 `module.py` 的包；包内相对导入与重新发现使用独立模块空间。

Bot 领域模组以 `namespace:kernel/module/path` 标识，声明发布版本与内核 API 兼容范围，并按契约类型表达 `provides/requires`、按贡献点表达 `contributes/consumes/declares`。同优先级能力冲突、缺失依赖、未声明贡献和依赖环在启动效果前失败。完整模组声明冻结为规范 JSON，并在生命周期中归档；声明摘要描述发布清单，不等同于代码或整个 Python 环境的快照。

生命周期默认经过 `prepare → construct → activate → ready → run → drain → close`，也支持声明额外阶段与顺序约束。构造阶段结束后固定 `Assembly` 的声明索引，能力值从共享 ctx 读取；门面创建并完成所有 `CognitionLauncher` 接线之后，才启动运行阶段。准备资源有逆序清理，后台失败交给宿主，关闭等待已启动的清理完成。第三方代码模组与进程同权限运行，当前没有操作系统隔离。

通用模块通过 `@namespace` 注册初始化函数，通过装饰器声明调用点和 hook。宿主自动建立模块的 ctx 空间，所有模块都能读写全部空间；容器读写采用快照，多字段更新使用带版本冲突检测的事务，修改保留来源。服务对象按引用共享，ctx 不替代持久世界事实。Bot 适配层将领域契约转换为宿主名称，通用内核不导入 Bot 或 CLI。具体接口见 [Namespace 与 hook](../develop/namespace-modules)。

## 项目入口

Python 使用 src layout：`src/aurora_cli/` 提供项目入口，`src/aurora_kernel/` 提供通用宿主，`src/aurora_bot/` 提供领域框架，
由同一份 `pyproject.toml` 发布为 AuroraBot。终端命令 `aurora` 由 `aurora_cli.main:main` 提供入口。
开发时先执行 `uv sync --locked --group dev`，测试与运行均使用安装后的包。

前端应用位于 `apps/`，工程配置位于 `tooling/`，
由根目录 pnpm workspace 管理。uv 与 pnpm 各自维护依赖锁、测试和构建；
根目录 `pnpm check all` 汇总两侧检查，Python 开发也可以独立使用 `uv run aurora check`。

`aurora_cli` 负责 CLI、`.env`、只读配置解析、进程日志和信号处理，再调用 `aurora_bot.runtime` 的装配入口。命令执行通过 namespace 调用点进入独立宿主；Bot 装配使用自己的宿主与 ctx。`aurora_bot` 不导入 `aurora_cli`。命令和配置按目录约定发现，新增能力不需要修改中心分派表。

`aurora start` 和 `--headless` 共用生命周期；无界面模式只排除交互式前台。Console 普通输入先提交世界；本地帮助、清屏和退出不作为外部观察。领域命令由同一个操作定义解析和校验。

运行日志只记录状态、身份、数量和错误类型等元数据，不记录 Prompt、消息正文、工具参数或密钥。世界日志保存需要恢复的业务事实，制品存储保存按固定引用展开的大对象，三者职责独立。

相关机制见[认知与恢复](./runtime-core)、[配置与存储](./configs)和[质量与验收](./acceptance)。
