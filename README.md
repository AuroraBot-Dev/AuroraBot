<p align="center">
  <img src="assets/logo.svg" width="112" alt="AuroraBot Logo" />
</p>

<h1 align="center">AuroraBot</h1>

<p align="center">
  <b>中文</b> | <a href="README.en.md">English</a> | <a href="README.ja.md">日本語</a>
</p>

<p align="center">
  <em>让 Bot 过上自己的生活。</em>
</p>

<p align="center">
  <a href="https://github.com/AuroraBot-Dev/AuroraBot"><img src="https://img.shields.io/badge/GitHub-AuroraBot-181717?logo=github" alt="GitHub" /></a>
  <a href="https://www.aurorabot.org/"><img src="https://img.shields.io/badge/Docs-aurorabot.org-315b7d" alt="Documentation" /></a>
  <a href="https://github.com/AuroraBot-Dev/AuroraBot/actions/workflows/ci.yml"><img src="https://github.com/AuroraBot-Dev/AuroraBot/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-315b7d" alt="Apache 2.0" /></a>
  <img src="https://img.shields.io/badge/Python-3.12-315b7d?logo=python&logoColor=white" alt="Python 3.12" />
</p>

## AuroraBot 是什么

AuroraBot 是一个为 Agent 提供可以"生活"的运行环境的 Bot 框架。我们想做的不是一个工具一般的 Agent，而是一个能够持续存在、形成自己的节律，并在环境中自主判断和行动的 Bot。

她有自己的人格、状态，可以在需要时与人和外部世界建立联系, 在她的世界里, 所有的消息都有一个"媒介": 你发给她的消息也必须先成为一个应用通知喔~

## 设计哲学

### 以 Bot 为中心设计一切

AuroraBot 把 Bot 当作世界的主体，而不是被调用的接口：她一直存在，拥有自己的人格、状态与边界，一切设计都围绕她的生活展开。这个原则落到架构上有三条：

- **她拥有世界，树只是她的运行**：Bot 持有追加式的世界提交（WorldJournal）与多棵 `AgentTree`。一棵树只是一次运行，不是与她平行的另一个主体；聊天、任务、委派都是她生活中的一次经历，经历结束，她仍然存在。
- **一切输入都有媒介**：任何影响她的变化都必须先成为一条世界事件。你发给她的消息要先作为 `console.input` 提交到她的世界，应用事件、MCP 上报、工具结果、时间的流逝也是如此。她不是在响应接口，而是在经历世界。
- **她理解之后才决定**：来自用户的消息不会因为来源就自动成为最高指令。她先理解发生了什么，再决定回应、行动、委派或保持安静；模型只负责理解与判断，外部行动必须经声明的 Tool 执行，结果再作为新事件回到她的世界。

### 持续状态与自主安排

`config/bot.toml` 指定长期稳定的 Bot 身份。目标、完成条件、恢复检查点和未来活动安排属于这个身份，保存在世界日志中，进程重启后可以恢复。

Bot 可以通过 `bot_state` 读取自己的状态，通过 `goal_set` 建立、修订、暂缓或结束目标，通过 `wake_schedule` 安排一次带时区的未来检查，通过 `wake_cancel` 取消尚未开始的安排。修改需要携带读取到的状态版本，避免覆盖新的选择。

时间服务持续兑现已经登记的安排；这些安排不受事件批量节律开关影响。重启时，已经开始但没有完成记录的认知会被标记为中断，保留待核对的行动依据。恢复过程不会自动重放这些行动。

世界输入、已提交事实和工具参数使用递归不可变的 JSON 值；原调用方改写嵌套容器不会改变历史或缓存。适配器向数据库和外部协议发送内容时，通过 `src.utils.thaw_json` 产生普通 JSON 副本。世界的发生时间与获知时间必须带时区，并统一转换为 UTC；同一事实身份可以用等价的时区表示重试，但不能改写发生时刻。

每次认知都显式获得主体状态。上下文字符预算先为本节点可见工具的名称、说明与完整参数结构预留容量，再保留原始输入、最新完整交互和恢复依据，候选经历按剩余容量进入；必要状态与能力定义超限时明确报错，需要减少可见能力、拆分工作或调整容量。字符预算是领域输入的代理计量，不等同于模型的实际 token 上限。

### 资源与领域操作

资源使用 `namespace:domain/kind/path` 寻址，例如 `aurora:bot/query/state`。定义版本、可变别名和 Bot 的运行实例分别记录。存在多个版本时，调用方需要明确选择版本或绑定别名；进行能力替换时可以校验契约身份与版本。

模组声明命令或查询的定义、参数结构、世界域和处理者。统一路由在执行前记录请求与确定版本，结果再次进入世界；重复请求复用持久回执。命令已经开始但结果未确认时，只有声明可安全重试的处理者可以再次执行。

结构化工具和终端指令共用这些定义。终端可使用：

```text
/resources --domain bot --kind command --limit 20
/inspect aurora:bot/command/goal_set@2
/call aurora:bot/query/state {}
/call aurora:bot/query/state {"goal_id":"aurora:goal/check"}
```

扩展通过 `@module(resources=定义.resource)` 静态声明操作说明，通过 `OPERATION_CONTRIBUTIONS` 绑定处理者。处理者可以依赖资源目录，目录不依赖处理者的构造。定义与工具共用同一份参数结构；普通静态资源也可在模组声明中提供，依赖配置或模型状态的资源使用 `RESOURCE_CONTRIBUTIONS`，别名通过 `RESOURCE_ALIASES` 声明。为操作填写 `tool_name` 后，框架会生成模型工具入口；Bot 的可见工具仍由 Agent 定义选择。

模组后台阶段的未处理异常会带着模组、阶段和原始原因交给进程监督，并先作为 `runtime.module.failed` 写入 Bot 世界。运行者随后停止协作者，等待全部前台退出，再逆序释放模组资源。构造、激活、运行和清理同时失败时保留全部错误；CLI 逐项显示原因。普通停止与已请求的取消不记为后台故障。

并发关闭共享同一次资源释放。关闭、构造回滚和协作者退出期间收到取消时，运行者先等待清理完成，再抛出取消；重复取消也不会截断清理。已经接管的后台故障会完成世界记录，原始故障和清理错误保留在异常原因中。

每个 MCP SDK 连接由独立任务建立并保有，关闭请求也交回该任务执行，保证 SDK 的取消作用域在所属任务中退出。启动握手被取消时也会等待已创建的连接资源释放。

MCP 关闭会先停止各连接的事件入口，再逆序释放所有连接。单个连接的停止或释放失败不妨碍其余连接清理；宿主收到带有应用、阶段和原始原因的错误，多个错误一起报告。实际释放失败的连接状态为 `close_failed`，正常释放的为 `closed`；启动失败时也同时保留随后发生的清理错误。

能力提供者由优先级在启动前选定，准备、构造和生命周期都使用同一份登记权；同优先级冲突会失败。能力全部被替换且没有贡献的模块不运行；部分能力被替换时保留其他端口和贡献。模块可用 `context.is_provider(契约类型)` 判断是否需要准备实现；若构造其他能力时需要读取自己提供的可替换端口，应同时把该端口列入 `requires`，让依赖跟随实际选中的提供者。

模组通过 `@module(scopes=ScopeDeclaration(...))` 声明自己拥有的域、分类和含义。装配在业务准备前合并可用模组的声明，形成冻结的 `ScopeCatalog`；记忆、工具和 MCP 通过能力注入读取同一份目录。插件添加域无需修改宿主配置。`scopes.toml` 默认为空，仅填写项目扩展或覆盖：同模式配置优先，不同模式按路径具体度排列。同一模式的模组声明不一致时，启动前失败。

`/resources` 与 Bot 的 `resources_find` 共用 `aurora:resources/query/find`，返回 `items`、`next_cursor` 和 `listing_mode`；`/inspect` 与 `resources_inspect` 共用 `aurora:resources/query/inspect`。默认每页 20 项，用 `--after` 或结构化参数 `after` 继续同一筛选。查询经过统一操作路由并记录调用；检查动态内容需要确定版本并核对完整性，返回描述后仍需按读取入口取得正文。

提示词使用 `namespace:prompt/system/path` 或 `namespace:prompt/agent/path` 身份，版本为实际采用文本的 UTF-8 SHA256。系统片段按配置顺序与节点选定的 Agent 片段共同进入上下文；目录、装配器与实际模型请求引用同一份冻结内容。`ModelRequest.resources` 和 `engine.model.requested` 的 `resources` 保存实际采用的明确版本，未采用的 Agent 片段不计入来源。替换提示词装配器时，资源贡献跟随实际选中的提供者。

提示词模块通过 `RESOURCE_CONTENTS` 贡献实际选中目录的冻结正文，`resource_content` 模块在生命周期的 `ready` 阶段统一保存到 `ArtifactStore`，成功后才启动后台任务。正文归档不参与资源目录的构造依赖，其他领域可使用相同贡献入口。源文件改变或进程重启后，仍可通过 `aurora:artifacts/query/read` 按世界日志中的固定版本读取历史正文。写入失败或存储返回不同版本、大小或媒体类型会使启动失败。同步 `assemble_runtime` 只构造实例，不执行生命周期，也不保证提示词正文已持久化；正式启动由 `aurora start` 执行完整生命周期。

Agent 原型使用 `namespace:agent/definition/path` 身份，可由统一资源解析器直接解析。`AgentDefinition.ref` 的 SHA256 版本覆盖身份、说明、提示词引用、模型、已展开的工具集合与可委派原型集合。实际选中目录的规范 JSON 正文通过同一归档入口保存；`/resources --domain agent --kind definition` 可发现已发布版本，正文使用制品读取入口取得。配置变化会产生新版本，已有正文保留；同步装配同样不执行归档。

`AgentNode` 直接持有创建时的不可变 `AgentDefinition`，身份、版本、模型、提示词与可见工具都从这一份快照读取。消息追加、完成和委派不会替换父节点的原型；子节点捕获自己实际采用的原型。运行者在推理前核对目录中的完整版本，同名配置的任何声明变化都不能隐式替换已有节点；委派权限由父节点的原型快照决定。

实际 `ModelRequest.resources` 包含当前节点的原型版本和装配器采用的输入资源，相同引用只记录一次。`engine.tree.started`、`engine.node.spawned` 与 `engine.model.requested` 的 `definition_ref` 都来自节点快照；模型请求事实同时保留完整的 `resources` 列表。重启后可从这些世界事实取出固定引用，再读取当时采用的原型正文。

工具定义使用 `namespace:tool/definition/path`，工具集合标签使用 `namespace:tool/tag/path`，通过 `#namespace:tool/tag/path` 引用。标签先展开为定义身份或模式，再决定 Agent 可见工具；标签不能作为工具执行。MCP 适配器保留服务器原始名称与本地定义身份的冻结映射；Provider 请求中的协议别名也只在适配器边界转换。

`ToolDefinition.ref` 的 SHA256 版本覆盖模型可见的名称、说明和完整参数结构，`content` 是对应的规范 JSON。实际选中目录通过 `RESOURCE_CONTENTS` 归档这些冻结接口；`/resources --domain tool --kind definition` 可发现已发布版本，并通过制品入口读取正文。接口变化产生新版本，原始字典或服务器后续变化不能改写当前目录的接口快照。

`ModelRequest` 自动把实际 `tools` 的接口版本加入 `resources`，只计算本次可见工具；已声明的相同引用只保留一次。`engine.model.requested.tool_refs` 按实际工具顺序单独保存这组接口引用。世界中的工具请求、结果与委派结果通过 `tool_ref` 指向同一冻结接口，未注册或不可见的调用保留原始名称并将引用记为空。可从这些事实取出版本，再用制品读取入口核对当时使用的接口正文。

动态资源通过 `RESOURCE_PROVIDERS` 接入目录，不需要把全部版本登记到内核。每个提供者使用公共排序和游标，每次只返回一页；目录合并去重，静态声明优先，动态来源对同一版本的定义不一致时明确失败。提供者必须遵守页大小、筛选、顺序和续页规则，避免跨来源查询漏项。

大对象通过 `ArtifactStore` 保存。逻辑名称采用同一套资源身份，版本是原始字节的 SHA256；同名新版本保留旧内容，相同字节可以跨名称复用。`artifacts.toml` 指定持久目录，需要与世界日志一起备份。宿主可流式保存内容或导入固定文件；查询只接受确定版本，不自动选择最新内容。

操作结果超过 64 KiB 时，正式装配的路由先保存完整 JSON 回执，再把 `result_ref` 与状态写入世界日志；普通小回执继续内联。宿主的结构化调用仍返回完整结果，并附带 `body_ref` 内容描述。重试从相同版本恢复，不再次执行已完成操作；正文缺失或损坏时拒绝恢复，保留原先的执行状态。

操作请求超过 64 KiB 时也先保存完整正文，世界日志记录 `request_ref` 和已解析的目标版本。请求发布失败时不会进入处理者；重试需要先校验原始正文，再核对参数、来源、关联关系和期限。同一请求身份不能替换参数，即使原正文已经缺失；非幂等命令中断后仍需核对实际状态。

模型工具和终端遇到大结果时只显示固定引用，并提供读取入口；正文包含完整的 `status`、`data`、`message` 和 `evidence_refs`。收到引用本身不会被记为模型已经读取正文中的证据。小结果保持原有输出格式。

`aurora:artifacts/query/find` 与 `artifact_find` 工具按命名空间、领域和类别发现已发布内容，包括训练产生的数据集与权重。每页默认 20 项、最多 100 项，用 `next_cursor` 作为 `after` 继续；结果明确标记 `content_verified=false`，不表示正文已读或可用。分页扫描当前清单，新增且排在游标之前的内容需重新查询；当前实现每页扫描全部小型清单，内存受页大小限制，尚未使用持久检索索引。

`aurora:artifacts/query/stat` 核对版本并返回大小与媒体类型；`aurora:artifacts/query/read` 返回有界字节块，以 `content_base64` 编码，用 `next_offset` 继续读取。root、worker 和记忆专员可使用对应的 `artifact_stat`、`artifact_read` 工具。`aurora:artifacts/command/put` 接受最多 1 MiB 的 base64 内容，无默认模型工具入口；更大的数据集、权重和导出内容使用流式端口。读取会校验内容完整性，损坏文件不能作为有效版本返回。

阅读 JSON 回执或普通文本时，读取参数可指定 `encoding = "utf-8"`，结果通过 `text` 返回完整字符；中文或其他多字节字符跨块时，`next_offset` 会停在完整字符末尾，下一次从该字节位置继续。无效文本或错误的字符起点会明确失败，二进制内容仍用 base64 读取。

### 节律判断与训练

`cadence.toml` 控制世界消费入口、Agent 和检查频率，`rhythm.toml` 选择节律策略。规则基线按事件压力、即时路由和最长安静时间提供推理机会；GRU 模型使用相同的观察特征，并同时预测是否思考与下次检查时长。每次等待或唤醒都会记录策略版本、有效参数、观察、循环隐状态和后续运行结果。重启后恢复消费游标与等待安排，已经开始且结果未知的认知不会自动重放。

训练依赖通过 `uv sync --extra learning` 安装；开发依赖组也包含训练环境。基础运行可以只安装非开发依赖并选择规则策略。模型使用 [PyTorch GRU](https://docs.pytorch.org/docs/stable/generated/torch.nn.GRU.html)，不要求 CUDA。

```text
/call aurora:rhythm/query/observations {"after":0,"limit":100}
aurora train rhythm train.jsonl validation.jsonl models/rhythm.pt
```

观察查询返回原始决策输入与实际选择，供标注和可回放实验使用，不自动生成“正确”标签。训练数据每行是一段经历，包含 `schema_version = 1`、`episode_id` 和 `examples`；每个样本分别记录 `observation`、`think_value`、`wait_value`、`next_check_seconds`。效用需要由任务结果、独立标注或受控回放提供，监督目标是思考相对等待的增量价值。验证经历必须独立且晚于训练经历，报告同时列出学习模型和规则基线的误差与效用遗憾。

两种训练命令都会先把实际输入 JSONL 固定为数据集资源，再从相同字节解析和训练。报告的 `inputs` 同时包含原始资源版本与解析后样本摘要，模型归档内保存同一份来源信息、训练参数、框架版本和独立验证指标。模型通过 `ArtifactStore` 发布，`artifact` 给出确切模型资源；输出文件是相同字节的导出，不覆盖已有文件。训练使用 `artifacts.toml` 的内容目录；单独训练时该配置不存在则使用 `data/artifacts`。

使用导出的权重时，在 `rhythm.toml` 中指定 `policy = "aurora:rhythm/model/gru"` 和 `weights = "models/rhythm.pt"`。权重按内容生成版本；权重或推理参数变化后，节律会保留消费位置并清空不兼容的循环状态。训练命令不会自动启用新权重。

也可将 `weights_ref` 设置为训练报告中的 `资源名@revision`，例如 `aurora:rhythm/model/gru@完整SHA256`。`weights` 与 `weights_ref` 二选一。常规 `aurora start` 的异步生命周期会把路径权重先导入内容存储，固定引用则直接读取对应版本；目录声明和实际模型使用同一份已校验字节，缺失或损坏不会静默切换模型。程序中使用资源权重时调用 `compose_runtime` 完成异步装配。

### 记忆读取与训练

每次记忆读取先固定全局游标和观察时间，分别检查事件发生时间与 Bot 的获知时间。迟到事件、后续反馈和后来的目标修改不会进入过去的上下文。当前目标的完整检查点与其证据固定保留，其他主体状态通过数量概览和分页查询按需展开；必要内容超过容量时明确结束本次认知。

候选来自近期经历、文本相关性、目标关系和实体关系。世界提交可在 `data.memory` 中显式声明 `goal_ids`、`entity_ids`、`depends_on`、`supersedes` 字符串数组。旧经历可以通过这些关系重新进入上下文；集合组装会补齐依赖、带上已知修订并去重。缺少前提的可选集合整体跳过，检查点缺少的证据引用则明确披露。原始提交仍由世界日志保存，不因退出上下文而删除。

域声明的命名空间支持完整名称或 `*`，路径中的每个 `*` 匹配非空片段并可跨越 `/`，其余字符按字面匹配。操作请求、回执和引擎运行域属于 `run` 台账，默认不进入候选或时序图，避免完整导出和历史回执被反复索引。Bot 在检查点或依赖中明确引用的台账证据仍会恢复；显式读取范围和包含／排除配置继续约束所有来源。审计分别保存实际可见域与候选域，历史重建沿用当时的选择。

`memory.toml` 管理读取范围；`memory_model.toml` 选择独立排序策略。规则基线比较文本、任务关联和时效性；时序图模型使用类型化节点、按获知间隔传递的消息、GRU 节点状态和邻域聚合，结构参考 [Temporal Graph Networks](https://arxiv.org/abs/2006.10637)。动态节点状态与权重分开，按实际可见历史投影并复用确切前缀；模型计算在线程中执行。

```text
aurora train memory train.jsonl validation.jsonl models/memory.pt
```

记忆训练 JSONL 每行包含 `schema_version = 1`、`episode_id`、`bot_id` 和 `examples`。每个样本分别记录 `request`、与候选逐项对应的 `utilities`、`outcome_cursor` 和 `outcome_at`。`request` 中只有当时可见的查询、候选和时序交互；监督结果必须来自推荐之后的世界提交。`src.memory_model.dataset` 提供类型化读取和导出，训练按效用差加权排序，并要求全部训练结果先于独立验证查询获知。报告比较排序准确率、效用遗憾、NDCG 和正收益召回率。受控测试验证历史区分、梯度和重载一致性，真实任务收益需要独立效用数据评估。

使用权重时，在 `memory_model.toml` 中指定 `policy = "aurora:memory/model/tgn"` 和 `weights = "models/memory.pt"`。资源版本由实际权重内容生成，读取结果携带同一版本；输入坐标不兼容时拒绝加载。训练命令不会自动启用权重或在线更新参数。

记忆模型也支持 `weights_ref = "aurora:memory/model/tgn@完整SHA256"`；与路径二选一，读取相同内容存储。原导出文件和训练输入路径移除后，已发布的固定模型版本仍可加载，训练来源也能按归档内引用复核。

TGN 在线评分保存一份图前缀投影；交互历史逐项一致时只处理新增交互。问题、候选、焦点和读取时间每次重新评分，历史查询与不同分支独立构建，不能借用未来状态。并发评分由策略内部串行保护，失败后清空未确认的投影；训练仍从各样本的完整图输入计算梯度。

`memory_model.checkpoint_seconds` 指定动态图状态的周期保存间隔，默认 60 秒，关闭时也会保存。检查点通过 `ArtifactStore` 保存独立张量资源，世界运行台账只记录 Bot 归属、模型版本、历史前缀摘要和固定内容引用；相同历史不重复保存，规则策略不产生检查点。启动时尝试恢复，第一份实际查询仍必须核对完整历史前缀；不兼容、损坏、不同范围或旧历史都会按实际世界重建。检查点台账不进入默认自动召回，也不会增加节律事件压力。

### 主动读取与记忆反馈

Bot 可以主动改变查询问题、指定焦点目标并展开原始来源。默认总代理和执行者提供 `memory_recall`、`memory_source`、`memory_exposures` 和 `memory_feedback` 工具，也可委派给记忆专员。终端使用相同的领域操作：

```text
/call aurora:memory/query/recall {"query":"先前实验的结果","focus_goal_ids":["aurora:goal/check"]}
/call aurora:memory/query/source {"memory_id":"experiment-started"}
/call aurora:memory/query/exposures {}
```

召回返回有来源的摘要和依赖集合；`summary_complete` 明确表示摘要是否完整。来源查询返回完整世界记录与读取边界，以及该时点已经获知的 `superseded_by` 引用。精确知道 ID 也不能读取指定历史边界之后的内容。

模型请求保存完整召回评分、模型版本和参数，并分别记录必要证据、推荐内容、实际载入和消息历史来源。工具结果与世界输入通过显式 `evidence_refs` 传递来源；装配器在裁剪之后报告实际保留的引用，不通过正文关键词猜测曝光。`included_ids` 表示已经进入本次模型请求，不表示模型采用了内容或目标获得收益。曝光查询默认扫描最近一页；传入 `after`、`until_cursor` 和 `limit` 可以在固定世界前缀上分页。

反馈命令 `aurora:memory/command/feedback` 接受 `model_request_id`、`memory_id`、`goal_id`、`helpful`、`reason` 和 `evidence_refs`。目标和记忆必须真实存在，记忆必须进入过指定请求，证据必须在该模型请求之后获知。反馈以 `reported` 自评保存，不会自动变成正确效用标签。判断变化时用 `supersedes` 指向原反馈；原始判断保留，重启重试不会重复写入同一次反馈。

用于标注和训练时，可调用 `aurora:memory/query/training_input` 并传入 `model_request_id`。该查询按照审计保存的时间、游标、实际域和候选特征重建当时的完整排序输入，不调用当前推荐器；原始输入的 SHA256 指纹必须与重建结果一致。返回的 `request` 使用训练数据的输入格式，后续自评和新事实不会进入该历史前缀。效用和结果来源仍需独立提供；缺少原始指纹或重建不一致时明确拒绝导出。

## 快速开始

### 1. 克隆本仓库

需要 Python 3.12、Git 与 [uv](https://docs.astral.sh/uv/)

```bash
git clone https://github.com/AuroraBot-Dev/AuroraBot.git
cd AuroraBot
./scripts/linux/setup.sh
# macOS: ./scripts/macos/setup.command;
# Windows: .\scripts\windows\setup.ps1.
```

`setup.sh` 会检查 git/uv/pnpm，询问是否将 aurora 全局链接到用户工具目录，然后由 `aurora setup` 完成依赖同步、个人配置以及 docs/panel 子模块引导。

### 2. 填写必要配置

在 `.env` 中填入默认模型所需密钥（如 `DEEPSEEK_API_KEY`）

### 3. 从终端启动

```bash
aurora start
```

启动后直接输入消息即可对话；输入 `/help` 查看操作，输入 `/exit` 停止。

## AIGC

本项目存在由大语言模型或扩散模型等生成式模型辅助编写的代码, 并经由人工审核.

## 参与贡献

见[参与 AuroraBot](CONTRIBUTING.md)与[AuroraBot 文档站](https://www.aurorabot.org), 提交贡献即表示你同意遵守项目的[社区行为准则](CODE_OF_CONDUCT.md).

## 开源致谢

AuroraBot 的诞生离不开许多优秀的开源项目：

| 项目                                                                                                                   | 在 AuroraBot 中的用途            |
| ---------------------------------------------------------------------------------------------------------------------- | -------------------------------- |
| [LiteLLM](https://github.com/BerriAI/litellm)                                                                          | 模型 Provider 接入与调用基础设施 |
| [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)                                                   | MCP 客户端与工具协议             |
| [prompt_toolkit](https://github.com/prompt-toolkit/python-prompt-toolkit) / [Rich](https://github.com/Textualize/rich) | Console 与终端体验               |
| [SQLAlchemy](https://github.com/sqlalchemy/sqlalchemy) / [aiosqlite](https://github.com/omnilib/aiosqlite)             | WorldJournal 持久化              |

也感谢其他开源 Agent/Bot 项目对这个领域的探索。特别感谢 [MaiBot](https://github.com/MaiM-with-u/MaiBot)，其"数字生命"理念为 AuroraBot 的早期思考提供了重要启发。

## 许可证

本项目以 [Apache License 2.0](LICENSE) 协议开源。
