# AuroraBot

以 Bot 为中心设计：Bot 是持久主体，拥有世界、目标与记忆；认知执行有明确的输入和结果，不要求树状拓扑。

## 设计边界

- 外部输入先成为世界事件；Bot 理解后决定回应或行动，外部效果经声明的 Tool 执行，结果回到世界。
- 认知入口只传递请求与结果；默认执行器用树组织委派，独立上下文、结果归属和运行上界由执行器保障，不另建调度框架。
- `ChatMessage` 只有 system/message/assistant/tool；仅 Provider adapter 映射协议角色，模型身份显式进入每次请求。
- `PromptAssembler` 只装配上下文，记忆快照显式注入；必要状态与约束超限时在模型调用或行动前失败。
- 世界只校验、编号和追加，提交方决定 scope；通过 contracts 端口访问，禁止跨包导入 world 实现。
- Bot 状态与时钟可独立替换；记忆、检查点、模型投影分开保存，后续反馈不得泄漏到过去查询。
- 操作定义统一生成工具与终端入口，持久保存版本、请求、回执和因果；效果未知的非幂等操作不自动重放。

## 包与组合

- `src/aurora_kernel/` 是唯一通用组合机制：namespace、hook、ctx、发现、依赖解析和生命周期；不依赖 CLI 或 Bot。
- 装饰器注册命名空间和调用点；宿主自动创建 ctx，模块可读写全部空间，事务检测冲突并记录来源。
- namespace 不隔离权限；容器读写使用快照，服务对象按引用共享，ctx 不替代世界日志。
- `src/aurora_bot/kernel/` 适配领域声明与契约，不重复实现内核；接线和生命周期跟随选中能力，失选实现不产生准备效果。
- `src/aurora_bot/runtime/` 负责 Bot 装配与门面；功能包运行时只依赖自身、contracts、utils，兄弟能力通过注入调用。
- 功能包的 `module.py` 可引用 Bot kernel 并导出唯一 `MODULE`；兄弟实现的类型引用限于 `TYPE_CHECKING`。
- `src/aurora_cli/` 负责命令、配置和进程环境；命令入口保持 `aurora`。三个导入包同属一个发行包，Bot 不导入 CLI。
- 命令与配置按目录发现；插件来自内置包、`extensions/plugins/` 和 entry point。兼容性、冲突与依赖环在准备效果前校验。
- `config.example/` 保存模板；个人 `config/`、本机扩展由 Git 忽略。前端位于 `apps/`，工程配置位于 `tooling/`。

## 文档与范围

- README 以当前版本为基准，保留介绍、设计哲学、快速开始和致谢；不追加实现细节或接口清单。
- 现行结构见 [系统总览](apps/docsite/src/architecture/system-overview.md)，通用接口见 [Namespace 与 hook](apps/docsite/src/develop/namespace-modules.md)。
- 领域扩展见 [模组开发](apps/docsite/src/develop/core-development.md)，精确协议见 `apps/docsite/src/reference/`；实现与相关文档一起更新。
- 当前不推进 RFC；源码注释直接说明局部不变量，不引用 RFC 编号。
- 新增并发、抢占、自动摘要、在线训练、sandbox 等能力前，先明确 Bot 用例、不变量与独立测试。
- 面向人的文本以简体中文为准，描述当前能力和限制，不使用实验、旧版、迁移等历史阶段叙事。

## 开发与验证

- 当处于wsl环境时运行命令, 不要带有wsl前缀.
- Python 3.12 使用 uv；前端使用 Node.js 24、pnpm 12。测试前执行 `uv sync --locked --group dev` 安装项目。
- Ruff 行宽 120、LF、双引号；单个源码文件不超过 600 行，纯字段模型可例外。
- 公开 API 保留必要注解，值对象优先 frozen + slots dataclass；hook 与 ctx 允许 Any，不堆叠类型包装，不以 lint ignore 掩盖复杂度。
- 测试必须离线、确定，无网络或环境变量依赖；Model/Tool 使用 fake，数据库仅用于 WorldJournal 临时 SQLite 集成测试。
- pytest 使用 importlib 模式，测试按能力分目录；专用辅助代码就近放置，跨能力替身放 `tests/support/`，经 `tests.*` 导入。
- 优先验证认知循环、持久化、幂等、未知效果恢复、权限与路径、脱敏和记忆时间边界；不为简单转发或覆盖率补重复测试。
- 日常不采集覆盖率；按需使用 `uv run aurora check --test --coverage`，CI 下限 20%，不作为删减目标。
- 不提交密钥或真实会话；日志不记录 Prompt、消息正文、工具参数或凭据。
- 提交前运行 `uv run aurora check --fix`。
