# 变更记录

## 2026-11-11

### 修复远程图片下载失败阻断模型推理

- 根据用户明确授权重放一次 13:59:42 的失败请求，DeepSeek 返回 HTTP 400，明确指出历史消息中的 QQ 图片无法下载。失败请求只有这一张远程图片；没有证据将本次错误归因于上下文容量或 reasoning_content。诊断不执行工具，不修改历史或凭证，后续回归全部使用模拟传输。
- LiteLLM 适配器识别 HTTP 400 中明确的图片下载失败，仅当失败地址与请求内图片精确匹配时，将该图片投影为“图片未读取、不得推断内容”的文本并补发一次。其他图片、文字、工具往返和原始持久历史保持不变，不改动压缩校验值或长期记忆，不引入通用供应商重试。
- 流式响应只有在首个有效片段前失败才允许补发；已输出部分内容、不匹配地址、其他异常和再次失败均正常上抛。失败响应和替代响应各自关闭，进入上下文前的能力检查及客户端并发约束保留。每个客户端仅缓存最多 128 个失败 URL 的 SHA-256 摘要，后续调用投影替换，重启或淘汰后可重新尝试；不自动续跑失败激活或重放工具动作。
- 适配器错误日志增加供应商异常类型、HTTP 状态和 image_download_failed/provider_error 类别，不输出异常正文、签名 URL 或凭证；SDK 自身调试日志行为未改动。配置、公共 ID、快照和分发边界不变，无需迁移 data；重启 Bot 后使用新代码。
- 新增 4 项协议验收：真实 SDK 配合模拟 HTTP 分别验证流式/非流式图片拒绝后的单次恢复、原历史不变和后续调用去重；部分输出后不重放；第二张图片失败时仍最多补发一次且无匹配图片时不重试。保留既有取消、关闭、能力检查和错误脱敏断言。
- 同一已安装环境实测 `uv run --locked aurora check` 8.77 秒、`uv run --locked aurora check --full` 41.02 秒；1221 项 Python、131 项前端、5 项原生终端测试全部通过，保持 4 worker，现有依赖警告保留。未在修复后追加真实供应商调用，未修改 README.md 或 AGENTS.md。

### 移除默认轮次上限并自动归档压缩记忆

- ReAct 默认不限轮次，Bot 配置和安装助手不再生成 max_iterations；显式正整数仍保留有界任务的 LoopLimitExceeded 语义，control.While 不变。模型结束、bot_finish、取消和关闭仍正常收束；每轮保留调度让出点，新引导能在运行期间接纳。既有 TOML 需删除旧 max_iterations 才能取消上限，不自动覆盖其他用户配置。
- agent 增加由 Bot 消费的 CompactionRecorder 协议。压缩调用前同步归档源消息、旧摘要、run_id、范围与校验值，摘要通过预算检查后同步提交索引队列，再提交上下文摘要；保留原始历史及 actions_read 证据，模型用量统计继续生效。本地落盘失败阻止压缩提交，供应商 embedding 不参与这一同步路径。
- 记忆插件新增显式 auto_compaction 配置，默认关闭，开启要求上下文管理。宿主在 prepare 后持有实例隔离的存储，在 start 启动独立索引任务；embedding 失败或超时保留原文和摘要，队列可重启恢复，stop 取消网络等待、clean 关闭资源。索引完成后事务发布普通 auto_ 记忆并确认队列，检索按需使用现有工具，未发布数量由 pending_index_count 提示。手动删除或编辑已发布记忆不会被重放覆盖；不重试 agent 或有副作用工具动作。
- SQLite v1 增量增加 compactions 表并升级到 v2，保留已有记忆、修订与索引；同一所有者与历史前缀去重。已索引语料仍有 1000 条容量上限，待索引摘要和原始归档不自动裁剪；完整运行历史和磁盘占用仍需管理。没有修改公共 ID、插件入口、快照字段、README.md 或 AGENTS.md。
- 新增 4 项互补验收：超过 25 轮仍接纳引导并可取消；压缩前归档及队列落盘失败不提交摘要；v1 迁移、索引失败恢复、实例隔离及删除不复活；22 轮跨包长任务在 embedding 挂起时多次压缩并完成，关闭后重启补索引可召回，且不重放工具动作。既有显式上限、摘要失败和生命周期测试全部保留。
- 同一已安装环境实测日常 `uv run --locked aurora check` 6.99 秒，完整 `uv run --locked aurora check --full` 38.32 秒：1217 项 Python、131 项前端、5 项原生终端测试通过；保持 4 worker，现有依赖警告保留。全部使用假模型或模拟传输，未调用真实供应商。
- 11 个 wheel 构建成功；使用本次 wheel 的明确文件路径完成干净安装，验证 control 无需 agent/adapter/SDK、agent 无需 Bot/CLI/API/HTTP/SDK 并完成工具往返及恢复；Bot 自动记忆模块、模板与默认配置实际安装可用，未引入 MCP/CLI/API。避免同版本注册表缓存代替本次分发包。
- 按用户授权备份并更新本地 data：移除 16 轮上限、开启 auto_compaction，保持既有输入预算；7 份声明配置关联校验通过，备份位于 data/backups/continuous-memory-20261111-135304。未启动真实宿主或修改凭证，重启后生效；数据库在下次打开时增量升级。

### 减少重复决策材料并记录供应商实际用量

- cadence 按业务材料与忙闲状态指纹跳过 idle_seconds 内的相同判断；观察时间、run_id 与被动时钟变化不触发重复调用，新事件、笔记修订、行动状态及主动时间变化仍可重评，达到静默间隔后保留周期复查。显式忙碌拒绝允许下一轮重试接纳；跳过时不写入假决策、不推进游标，不自动清除既有故障。
- attend_events 引导仅保留选中的事件与环境，review_work 仅保留笔记与行动证据，不把整个业务视图重复写入历史；图片投影、原始归档和消费回执继续使用原有路径。指纹仅存内存，无公共 ID、配置或快照版本变更，旧历史不改写，重启重新判断但不重复转交已消费事件。
- LiteLLM 客户端从原始 JSON/SSE 提取供应商报告的输入、输出、缓存与思考计数；每次调用一条结构化 INFO 日志，区分主推理、摘要、cadence 及向量用途，关联运行或决策身份。缺失用量标为未知，流式累计快照不重复相加，不将 SDK 估算值当实际用量；正文、凭证和图片地址不进入日志，取消、失败与提前结束分开标记。
- 复用现有代表测试，未增加用例数量：图片与工具往返契约补充原始 SSE 分片、重复用量、用途关联、连接关闭和脱敏断言；choice 契约区分供应商零值与缺失值；cadence 用例验证不变材料跳过、新材料即时重评、到期复查、被动时间、忙碌重试、恢复和精简引导，保留主动唤醒与 QQ 图片链路验收。
- 同一已安装环境实测 `uv run --locked aurora check` 13.94 秒、`uv run --locked aurora check --full` 40.27 秒；1213 项 Python、131 项前端及 5 项原生终端测试全部通过。保持现有 4 worker，未跳过检查，保留依赖警告；全部回归使用假模型或模拟传输，未调用真实供应商。
- 11 个 wheel 构建成功；独立安装环境验证 control 无需 agent/adapter/模型 SDK，agent 与用量模块无需 Bot/CLI/API/模型 SDK，新增模块随 wheel 分发。上下文文档同步说明去重范围和用量口径；本轮不改写用户配置或历史，不提供自动费用限额，实际节省比例需结合后续运行日志评估。

### 增加长任务工具观察限制与中途上下文压缩

- 新增显式 `context_management` 配置，要求同时启用输入预算与行动证据，默认关闭。Bot 在完整工具结果归档后生成有界观察：超限内容带明确的截短标记、原状态、错误码与 actions_read 引用；仅对语义完全相同的 MCP 单文本块和 structuredContent 去重，不丢弃附加说明。分页读取工具自身不再次转成预览，其页预算随观察预算收敛，避免递归读取引用。
- agent 增加 HistoryCompactor，按 80% 软阈值先省略旧完整交流，再在完整工具往返边界压缩当前任务，保留最近两组完整消息，尽量降到 60%。摘要串行复用当前聊天客户端，不新增调度所有者、供应商依赖或共享资源；只处理历史材料，不执行工具。固定系统输入、工具定义、最近往返的思考和签名保持完整，无法容纳时明确失败。
- 摘要源剔除旧内部思考与签名，附件显式标注未读取，不将二进制编码作为摘要文本。按实际 JSON 大小分片，每个摘要请求仍受完整输入硬预算限制；总超时与摘要输出长度可配置。失败、取消、超时、异常终止或超长摘要不提交部分结果，不自动重试动作。完整历史保留，新增可选 compaction 字段保存覆盖位置、摘要与历史校验值，重启可复用；旧快照不迁移，历史被外部修改后摘要不匹配会拒绝使用。
- ModelInputBudgetExceeded 增加实际输入分项：system、view、history、tools 与 overhead，连同字符与附件预算写入诊断日志；只输出长度，不输出业务正文。压缩开始、完成和失败日志报告阶段及长度，方便区分摘要耗时与主推理。
- 增加 8 项有独有价值的用例：6 项压缩用例覆盖有界分片、保留多工具往返及签名、恢复复用、历史篡改拒绝、异常/取消/超时/无效输出原子性，以及固定输入和未收齐批次拒绝；1 项观察用例验证精确去重、失败状态及原始证据分页；1 条跨包链路验证长任务在摘要失败后继续且不重放工具、完整证据读取和宿主重启。扩展现有预算用例核对分项总和，不增加重复测试矩阵。
- 同一已安装环境实测 `uv run --locked aurora check` 12.12 秒、`uv run --locked aurora check --full` 39.58 秒；1213 项 Python、131 项前端、5 项原生终端测试全部通过。保持现有 4 worker，未跳过检查；现有依赖警告保留。全部回归使用假模型或模拟传输，未调用真实供应商。
- 11 个 wheel 构建成功；干净安装环境验证 control 无需 agent/adapter/模型 SDK，agent 的压缩、工具往返和恢复无需 Bot/CLI/API/HTTP/模型 SDK。上下文文档补齐配置、成本、失败和快照约束；未修改公共 ID、插件入口、README.md 或 AGENTS.md。

## 2026-11-10

### 合并模型适配层并复用 LiteLLM 原生能力

- `aurora_adapter.model` 从 13 个文件、1450 行合并为 9 个文件、1349 行，按 contract、config、content、response、litellm、内部 codec、testing 和 plugin 职责平铺。聊天类型统一命名为 ChatClient / ChatRequest / ChatResponse / ChatChunk / ChatCapabilities；去除旧模块、兼容别名和三套重复工厂解析。
- 聊天、choice、embedding 共用类型化 ModelAdapter、泛型 ModelFactory / ResolvedModel 与 resolve_model(kind=...)，统一登记到 model/adapters。LiteLLMClient 统一管理实例连接、用途、在途调用、错误脱敏和关闭；向量请求改用原生 aembedding，流式工具与思考碎片改用 SDK ChunkProcessor，保留完整性与签名校验。移除独立 OpenAI embedding HTTP 实现和 embedding extra，Bot 统一依赖 litellm extra；该 extra 不再额外安装 MCP。
- 保留 SDK 版本约束 `>=1.106.6,<1.107`。当前高层 decisions 不透传实例 client，继续使用 SDK 请求转换和底层 handler；OpenAI embedding 会覆盖零重试值，自有客户端固定零重试；DeepSeek 使用兼容路由保留文件和思考。没有引入共享 Router 或修改 SDK 全局配置，模型能力范围以已接入实例传输的供应商为准。
- adapter ID 改为 model/litellm/chat、choice、embedding；聊天服务改为 model/chat_client，聊天 schema 移入 model/chat/，移除独立 choice/embedding 注册表。同步迁移消费者、测试夹具、包模板和安装助手；插件入口、配置及持久业务状态 ID 不变。旧用户 TOML 不自动覆盖，旧向量 profile 须补 provider=openai；记忆索引指纹包含 adapter ID，升级后须显式重建，原文保留。完整手动迁移说明见[配置指南](configuration.md#从旧模型配置升级)与[模型边界](aurorabot-design-v0.2.3.md#模型边界)。
- 复用既有协议、装配、资源生命周期与记忆往返测试；只增加一个 Voyage 参数用例，独有价值是验证原生非 OpenAI 向量传输，同一用例同时覆盖顺序、无重试、重定向拒绝、错误脱敏和关闭。更新既有冷发现断言验证统一工厂用途与无 SDK 导入，保留全部业务及关闭断言。
- 同一已安装开发环境实测：`uv run --locked aurora check` 12.73 秒，`uv run --locked aurora check --full` 39.33 秒；1205 项 Python、131 项前端、5 项原生终端测试全部通过。保持现有 4 worker，未跳过检查；Pydantic、aiohttp 依赖警告仍存在。验证全部使用假模型或模拟传输，未调用真实供应商。
- 11 个 wheel 构建成功；干净环境验证 control 无需 agent/adapter/模型 SDK，agent 无需 Bot/CLI/API/HTTP/模型 SDK，并实际完成控制流与 agent 工具往返及恢复。安装 Bot 后确认无 MCP/CLI/API 依赖，模型插件发现不加载 LiteLLM，模板资源齐全，原生聊天、choice、OpenAI/Voyage embedding 模拟往返与关闭通过。
- 当前文档 31 个本地链接、5 段 TOML 和全部 15 个模型定义核对通过；未修改 README.md 或 AGENTS.md。

### 增加显式文本记忆插件与向量协议

- 新增独立 `aurora_bot.memory` 插件，通过现有工具工厂提供 `memory_write / memory_search / memory_read / memory_delete / memory_reindex`。按 Bot 实例隔离，正文分块后做 embedding 与精确余弦 top-k 检索；显式保存，不自动提炼聊天、复制工作笔记或注入每轮业务视图。
- 原文、来源、修订与索引保存到 `namespaces/ns-org.aurora.bot/memory.sqlite3`，不进入 ctx 快照；每实例最多 1000 条，每条最多 16000 字符。更新和删除检查不透明版本，embedding 等待后再次核对版本；原文与索引事务提交，失败或取消保留已提交数据。删除不清理已有会话历史副本。
- adapter 增加 SDK 无关的 `EmbeddingClient`、独立 embedding 注册表和角色解析，以及 OpenAI 兼容 HTTP 适配器。请求不重试、不跟随重定向，校验响应数量、索引顺序、维数和有限非零向量；凭证只在运行期解析，传输错误不返回正文。HTTP 依赖通过 `embedding` extra 安装，Bot 显式依赖它，adapter 基础包与独立 agent 依赖不变。
- 插件配置通过 aurora_config 的包模板和非持久状态接入。模型、端点、分块或 index_version 变化使旧索引不可搜索，须显式重建；原文仍可读取和删除。没有改名或删除既有公共 ID，也不迁移既有笔记、快照或用户 TOML；安装助手仍仅启用原有 ReAct 与 terminal MCP。
- 新增 6 项用例的独有价值：存储层覆盖重启召回、旧版本冲突、删除后重建身份、实例隔离、分块来源、索引失效，以及等待中的取消、并发更新和重建冲突；适配器验证 HTTP 参数、乱序向量、无重试脱敏和协议类型边界；仅保留一条真实配置与 ReAct 的跨包往返，验证写入后重启召回、浮点整数参数、资源关闭和凭证不落盘。扩展已有独立发现测试，确认 HTTP 依赖不在发现时导入。
- 同一开发环境实测：`uv run --locked aurora check` 12.19 秒；`uv run --locked aurora check --full` 38.73 秒。1204 项 Python、131 项前端及 5 项原生终端测试全部通过，未增加 worker 或跳过检查；现有 Pydantic、aiohttp 依赖警告保留。验证全程使用假模型或模拟 HTTP，未调用真实供应商。
- 11 个 wheel 构建成功；干净安装环境确认 control 无需 agent/adapter/模型 SDK、agent 无需 bot/CLI/API/HTTP/模型 SDK，并运行控制流及 agent 工具往返和恢复。随后从 wheel 安装 Bot，验证记忆插件发现、模板资源、模拟 HTTP 和数据库重开检索，无 CLI/API 依赖。
- 配置指南补齐插件启用、独立向量 profile、角色绑定、五个工具选择、索引重建与备份位置；上下文和架构文档区分工作笔记与长期记忆，公共目录补齐 12 个实际新增定义及插件入口。文档格式、60 个本地链接、8 段 TOML 与模型/记忆定义清单校验通过，未修改 README.md 或 AGENTS.md。

## 2026-11-09

### 约束开发过程中新增测试

- 按用户要求在 AGENTS.md 新增一条规则：新增测试须说明独有价值，优先复用或替换现有用例，限制跨层重复、同类边界枚举、参数组合膨胀及过程性断言。
- 扩大测试范围后须实测 15 秒／60 秒的完整命令耗时预算，超预算不能靠跳过检查、削弱有效断言或增加 worker 数规避。此项为开发约定，未新增自动门禁。
- 验证两份文档的格式、本地链接及差异；纯文档修改，不运行业务测试。

### 收敛日常与完整检查耗时

- `aurora check` 并行执行互不依赖的只读检查，按任务汇总 UTF-8 输出，任一任务失败仍返回非零；`--fix` 保持顺序执行。完整档及覆盖率档通过开发依赖 pytest-xdist 使用 4 个 worker、worksteal 调度，默认快速档与直接 pytest 保持单进程；不隐藏测试或跳过静态检查。
- 本机端到端计时（Windows、Python 3.12.10、项目 Node 26.13.0、pnpm 12.15.0，依赖已安装）：`uv run --locked aurora check` 从 14.92 秒降至 7.33 秒，另一次复测为 8.55 秒；`uv run --locked aurora check --full` 从 251.51 秒降至 39.65 秒。两档均全部通过，满足 15 秒／60 秒目标。
- `--coverage` 的 4 worker 结果合并成功，1198 项 Python 测试全部通过，总覆盖率 92.87%；前端与原生终端同时通过。11 个 wheel 构建成功，模板资源齐全，干净环境验证 control 无需 agent／模型包、agent 无需 bot／CLI／API 或供应商 SDK。
- 开发文档补充测试取舍、并行规则和计时口径；原生终端的针对性 pytest 通过 pnpm exec 选择工作区 Node，避免系统旧 Node 不支持 FFI。

### 精简测试矩阵与重复验收

- Python 用例从 1408 项减少为 1198 项，前端从 140 项减少为 131 项，保留 5 项原生终端测试。删除只验证包可导入、旧名称不存在、旧示例重复往返及第三方样式检查器行为的测试；旧示例仍保留独立包、SIGINT、恢复和常驻宿主的代表验收。
- MCP 工具桥从 24 组笛卡尔积收敛为 2 个跨层代表组合；共享资源关闭和部分启动失败从 30 组收敛为 10 组，保留各故障路径和混合连接隔离。供应商协议细节由适配层契约验证，默认装配保留流式及非流式往返。
- 精简同类配置错误、CLI 帮助与日志级别矩阵；移除固定插件数量、重复检查同一函数元数据、Promise 对象身份等内部步骤断言。时间间隔改为 5 个确定的正态分位点，替代 2000 次随机采样及近似统计断言。
- 快速契约测试从 31 项减少为 15 项；生成产物保留一次真实 `--check`，不再反复启动生成器验证相同产物。状态隔离、配置原子性、取消收尾、凭证不落盘、恢复不重放和真实 HTTP/WS/stdio 回归继续覆盖。
- 验收：1198 项 Python、131 项前端、5 项原生终端全部通过；完整覆盖率 92.87%，未降低覆盖率门槛或增加跳过标记，未调用真实模型供应商。依赖警告来自 Pydantic 与 aiohttp。

### 同步安装助手与文档约定

- 按用户明确要求直接在 main 更新 AGENTS.md：示例仅保留 onboarding，旧离线应用归入测试夹具；START.md 维持首次启动短指南，详细说明进入 docs，并增加当前文档索引入口。
- 将 world 的包职责与目录说明对齐已实现的世界来源、事件归档和环境观察，主动调度仍由 bot 的 cadence 提供。
- 验证 AGENTS.md 的本地链接与 git diff 空白检查；纯文档变更，不运行无关业务测试。

### 精简启动指南并归档、对齐文档

- examples/START.md 从 843 行收敛为 47 行，只保留安装配置助手的初始化、模型配置、单次使用及连续对话路径；详细内容按配置、操作、上下文、架构和开发验证组织，由 docs/INDEX.md 统一导航。
- 旧启动大全、架构、公共 ID、拆包评估及八份历史计划、交接、讨论和审查资料保存到 docs/archive/2026-11-09；增加历史状态说明，修正相对链接，保留当时的设计与验收语境。CHAGELOG 历史记录保留，仅更新迁移后的引用。
- 当前架构和执行包边界保留既有文件名并重写为代码现状，明确 world、MCP 产品装配与主动行为已实现，独立 harness 未实现；公共 ID 目录与 17 个插件及宿主基础定义实际枚举结果核对，共 179 项，不混入规划身份或未发现的动态工具。
- 文档验收：22 份 Markdown 的 269 个本地链接与章节锚点检查通过，代码围栏平衡，3 段当前 TOML 示例可解析，git diff 空白检查通过。
- 完整验收：pnpm exec uv run --locked aurora check --full 通过，包括格式、lint、Python/TypeScript 类型、140 项前端测试、5 项原生终端测试和 1408 项 Python 测试。Python 报告 3 条依赖警告，无测试失败；未调用真实模型供应商。

### 收敛用户示例为安装配置助手

- examples 仅提供 onboarding：真实模型驱动的朴素 ReAct Bot，复用现有 CLI 宿主与 MCP 产品装配；支持只补缺模板的 --init、单次 --text 和供 TUI / Panel 连接的持续后端。
- 助手独立使用 build/onboarding、onboarding 实例和 10271 端口，默认仅选择 terminal-mcp==0.4.7 的 7 个终端工具；关闭世界视图、cadence、笔记、行动证据和自身控制，开启 48000 字符输入预算。凭证仍通过环境变量解析，不复制或改写既有 data。
- 原五组离线应用及其配置移入 tests/fixtures/runtime_apps，相关测试只调整入口和格式，保留原有断言；独立包、恢复、取消和持续宿主的验收覆盖不删除。
- 针对性验证：新助手与原示例迁移相关 26 项测试通过，使用假模型与真实本机 stdio；初始化保留已有配置，工具结果可回填，重启恢复消息历史，未初始化或无效访问策略在创建宿主前失败。
- 本机安装验收：按模板通过 uvx 启动固定版本 terminal MCP，发现全部 7 个所需工具；完成 session_list、PowerShell 会话创建、无副作用输出读取和关闭。未调用真实模型供应商。
- 不变更现有包依赖、公共 ID、配置或快照格式；助手仅生成自己的模板，现有产品入口与数据不迁移。

## 2026-11-08

### 将 QQ 世界图片转为结构化模型输入

- cadence 原样转发与 `attend_events` 决策转交均识别 QQ 私聊、群聊事件中的 OneBot `image` 段，将有效 HTTPS URL 或图片 data URI 作为 `image_url` 交给既有模型通路；继续使用当前主模型，不增加 OCR、视觉模型或下载服务。
- 决策转交按所选记录 ID 读取完整事件，避免摘要截断导致图片来源丢失；保留原始引导文本，并为每张图片关联来源、记录、会话、消息 ID 和段序号。原始归档、消费游标和投递回执语义不变，普通 JSON、`observe` 和 `review_work` 不额外提取图片。
- 无效图片来源明确标记未进入视觉输入；每条引导最多 15 张图片，内嵌文件合计最多 10 MiB，超过预算的图片附带提示且不阻断后续消息。不读取本地路径，不自动下载或提升 HTTP 为 HTTPS。
- 无公共 ID、插件名、配置和快照版本变更；旧纯文本历史保持原样，已消费事件不自动补发。宿主重启加载新代码后，新 QQ 图片消息走结构化输入；既有 HTTPS 引用的可访问性和有效期由图片服务决定。
- 针对性验证：50 项测试通过，覆盖 URL/data URI、多图顺序与来源关联、无效来源及预算提示、两种 cadence 模式、截短事件原文读取、快照恢复及不重复投递；均使用假模型，未调用真实供应商。

### 按 ctx 活动形成衰减节律并随机感知时间

- 决策 cadence 订阅 ctx 的有效变化，以活动度动态缩短随机判断间隔；默认活跃下限 5 秒、静默中心 180 秒、半衰期 60 秒、随机浮动 20%。新刺激打断长等待，连续输入只提前期限，推理期间的变化保留到下一轮；判断继续串行，使用单调时钟，不增加 AgentRuntime 所有者。
- 允许时间刷新、cadence 记账和 Bot 运行状态参与反馈，每次反馈强度减半，低于 0.01 后停止加速；外部变化重新补充刺激。运行中的其他 ctx 变化按反馈处理，世界事件与主动环境变化仍作为新刺激。同值写入不刺激，活动度低于阈值归零，安静后恢复低频判断；自动活动暂停时不持续创建计时器。
- 时间启动时发布当前观察，随后以均值 1800 秒、标准差 300 秒的截断正态间隔主动更新，取值限定在均值 ± 三倍标准差内；ctx 变化时另行刷新，同秒合并，不重置主动更新时间。payload.trigger 区分 startup/context/rhythm，重启及墙钟跳变不补发历史周期。决策可评估所有时间观察，原样转发仅投递主动时间观察，避免派生时间随每轮执行重复转交。
- SourceInstance 增加可选同步 on_context_change，WorldSources 负责通知、退订及失败收束；工厂仍不获得原始 ctx。回调故障只封闭对应来源，保留 context_update_failed 诊断，取消并等待自有任务后释放资源。
- 旧 cadence 的 min_seconds/max_seconds/cooldown_seconds 替换为上述四项节律参数，取消固定引导冷却；时间的 interval_seconds 替换为 mean_seconds/deviation_seconds。公共 ID 和消费快照版本不变，last_guided_at、游标、pending 与历史回执保留，节律仅存于本进程。模板、示例及架构/公共目录同步更新。
- 已备份并更新本地 data 配置：原文件分别保存到 build/cadence-before-ctx-rhythm-20261108.toml、build/world-before-ctx-rhythm-20261108.toml；天气保持启用，仍每 900 秒查询、显著温差或天气类型/状态变化时发布。没有手工改写业务快照或调用真实模型，重启宿主后加载新配置。
- 针对性回归覆盖刺激加速、反馈耗尽、静默恢复、新输入打断等待、推理中刺激保留、暂停恢复、截断正态分布、ctx 时间刷新与同秒合并、来源回调失败清理和消费状态恢复；使用可控时钟、假模型和模拟传输。
- 全量测试通过：Python 1390 项、前端及共享客户端 140 项、原生终端 5 项；随后补充普通文本事件的加速断言，相关 43 项回归通过。全量命令发现的文档换行格式已修正，独立 `aurora check --lint` 通过；11 个 wheel 构建及新增节律模块、回调和模板的分发内容核验通过。

### 支持模型文件输入、思考及 Panel 附件

- Message.content 支持文本、图片及文件块；默认将 primary 聊天模型视为多模态，file_input 可显式关闭。新增 thinking/reasoning_effort profile 配置，取消 DeepSeek 强制关闭思考；使用其 OpenAI 兼容传输保留文件及思考，避免 SDK 按模型目录压平内容。
- 完整及流式响应分别保存回答、思考文本、签名和隐藏思考块，Agent 状态、工具往返、历史及恢复保留原始字段；旧纯文本快照继续可读，不改写旧消息或补造思考。公共 ID 与插件身份不变。
- Panel 提供附件选择、移除、仅附件发送和折叠思考展示。每条最多 8 个附件、合计 10 MiB，支持图片、PDF 与 UTF-8 文本；附件草稿按 API 地址及实例隔离，原请求重试保留相同字节。直接交流契约与生成的 TS 类型同步，submit 独立允许 15 MiB HTTP 请求，其他端点限制保持原值。
- 输入预算区分文本 JSON 与内嵌二进制，附件上限为 10 MiB，任一超限均按完整交流段裁剪；附件进入后端上下文和快照，宿主不读取调用方指定的本地路径。已配置本地 primary 启用思考与文件输入，原 profile 备份在 build/model-profiles-before-thinking-20261108.toml；本次验收未调用真实模型或手工改写业务快照。
- 针对性回归覆盖真实 SDK 的 OpenAI/DeepSeek 文件及思考工具往返、Anthropic 签名与隐藏思考块、模型部分输出保留、附件校验和去重、文件预算及超过默认 HTTP 大小的附件；全部使用假模型或模拟 HTTP。
- 最终全量测试通过：Python 1370 项、前端及共享客户端 140 项、原生终端 5 项；修正恢复测试的类型断言后，独立 `aurora check --lint` 全部通过。Panel 生产构建、11 个 wheel 构建及资源核验通过；干净环境安装本次 wheel，确认 Agent 的文件与思考接口无需 Bot、API 或模型 SDK。

### 取消 cadence 来源白名单并按天气变化发布观察

- 移除 source_ids 配置和来源选择暂停，原样转发与决策模式均接纳所有世界事件和环境变化。归档事件保留全局游标，环境来源各自保存锚点，环境观察不伪装成归档事件；决策材料引用保留环境来源及记录身份。
- 消费状态升级为 version=3/4；旧 version=1/2 在同一模式下保留事件进度、pending、回执和故障，只移除来源绑定及 SelectionChanged 暂停。未知投递、坏游标和模式变化仍拒绝自动重放。旧 TOML 须删除 source_ids，新模板、示例及文档同步调整，公共 ID 不变。
- 天气继续周期查询，首次、相对上次已发布气温的变化超过 temperature_change_c（默认 3°C）、天气类型或可用状态变化时发布。恰好阈值、只变时间戳/风速以及重复相同故障不发布；恢复会发布新观察。最新天气保留原始观测时间，额外历史仍受一小时与条数限制。
- 94 项针对性回归通过，覆盖所有来源参与、环境独立去重与恢复、旧消费状态升级及坏数据拒绝、天气累积温差、状态变化和稳定天气保留。全部使用假模型与模拟天气传输，未调用真实供应商。
- 全量回归通过：Python 1341 项、前端与共享客户端 136 项、原生终端 5 项。修正换行格式后独立执行 `aurora check --lint` 全部通过；11 个工作区 wheel 构建成功，核验分发中的 cadence 与天气模板包含新配置契约。

### 将本地 QQ MCP 迁入 Bot 工具目录

- 将 `../Aurora-QQ` 整体迁到 `data/tools/Aurora-QQ`，保留独立 Git 仓库、源码、锁文件和原 config.toml；98 个文件逐一校验 SHA-256 一致。旧 `.venv` 保存在 `build/aurora-qq-venv-before-move-20261108/`，新环境按原 uv.lock 的固定依赖重建，安装后的 `uv sync --frozen --dry-run` 无差异。
- 本地 MCP 的 cwd 更新为 `data/tools/Aurora-QQ`，直接启动新环境的 aurora-qq-mcp.exe，宿主启动不安装依赖。QQ 工具选择、协议要求、事件资源和运行期凭证引用保持原配置；主仓库继续忽略 data，本次迁移不修改 QQ 仓库源码。
- QQ 仓库 41 项测试通过，1 项依赖旧适配包名的跨项目测试按原条件跳过；另通过当前项目的 MCPClients/MCPTools 实测新路径握手、29 个工具登记和 qq://events/inbox 目录发现。未发送 QQ 消息或启动真实模型，验证连接清理完成。
- 本地 cadence 已删除 source_ids；天气来源继续启用，temperature_change_c 显式设置为 3。旧 cadence 快照离线升级校验通过，保留原始文件并备份至 `build/cadence-before-all-sources-20261108.json`，实际升级随下次宿主启动完成。

### 为 Panel 增加本地环境自动连接

- `aurora panel` / `pnpm panel` 启动的开发服务器从仓库根目录加载 `.env` 及 Vite 模式覆盖，页面打开后使用 `AURORA_API_TOKEN` 自动连接后端；默认地址为 `http://127.0.0.1:10270`，可用 `AURORA_API_URL` 覆盖，已有进程环境变量优先。修改环境文件后重启 Panel 开发服务器。
- 连接信息只通过本机同源 POST 接口运行时提供，检查回环地址、Host、Origin 和专用请求头，禁用响应缓存及跨来源读取；只返回地址与令牌，不暴露其余环境变量。生产构建和 preview 不提供此接口，令牌不进入静态文件、Pinia 状态、动作参数或浏览器存储。
- 每个页面连接所有者只尝试一次默认连接；配置请求限时五秒，手动连接、断开和页面关闭取消旧请求。配置缺失保留手动入口，读取或连接失败显示提示；迟到响应不覆盖新连接，不提交 Bot 消息或启动产品宿主。连接表单同步当前后端地址。
- Panel 的 35 项测试、类型检查、ESLint 和 Oxlint 通过，覆盖真实开发服务器环境读取及跨来源拒绝、页面自动连接、凭证不持久化、错误兜底和连接竞争。生产构建成功；使用实际根目录 `.env` 验证开发接口，并检查静态产物无令牌及 preview 无凭证接口。同步更新示例启动指南。
- 全量回归通过：Python 1331 项、前端与共享客户端 136 项、原生终端 5 项。未调用真实模型或重启现有 Bot。

### 为本地 Bot 配置持久终端 MCP

- 在 Git 忽略的 `data/tools/terminal-mcp/.venv/` 独立安装 [terminal-mcp](https://github.com/mkpvishnu/terminal-mcp) `0.4.7`，依赖版本保存到同目录的 `requirements.lock`；宿主直接启动本地入口，不在启动时下载依赖，不修改工作区 Python 依赖。
- `data/config/org.aurora.adapter/mcp.toml` 新增 `terminal` stdio 服务，使用 legacy 协商，向现有 Bot 装配开放 `terminal_create`、`terminal_send`、`terminal_interact`、`terminal_read`、`terminal_list`、`terminal_close`、`terminal_wait_for`。保留原 QQ 服务及其工具选择，连接执行超时为 45 秒，小于 Bot 的 60 秒工具预算。
- 为本地 Bot 提示补充 Windows PowerShell 会话创建、复用 session_id、分次读取长任务输出、超时不重发及关闭会话的说明。会话跨工具调用保留，默认空闲一天回收；宿主或 MCP 服务重启后不恢复进程，不改写业务快照。
- 使用项目实际 `MCPClients` 和 `MCPTools` 完成连接及七个工具登记；协议协商为 `2025-11-25`。跨调用变量及工作目录保留、会话枚举、异步命令输出读取与匹配等待、会话关闭和连接清理均通过，未调用真实模型。当前运行的产品宿主尚未重启，新增工具在重启后加载。

### 配置本地完整能力 Bot 并归档旧数据

- 正常停止原 Bot 后，将原 `data/` 整体移至 `build/data-archive-20261108-205846/`；13 个文件逐一校验 SHA-256，配置、快照、数据库和日志均保留。新 `data/` 只包含配置，不恢复旧业务状态。
- 沿用现有 DeepSeek 推理模型、QQ MCP、时间及南京天气来源，显式启用 17 个产品插件；Jev 决策 profile 使用项目示例地址及现有运行期凭证引用，cadence 选择 QQ 事件，环境来源保留为观察。启用上下文视图、工作笔记、事件归档、行动证据、完整请求字符预算与自身控制，并补充工具使用说明。
- 8 份 TOML、7 份声明配置通过离线结构与关联校验，来源 schema、MCP 连接引用、模型角色、4 个凭证引用及带配置编辑的启动参数检查通过；新 TOML 不含凭证值。配置和归档位于 Git 忽略目录，根目录凭证文件保持原样。未启动新宿主或调用真实供应商，启动使用 `uv run --locked python scripts/bot.py --edit-config`。

### 提供 Bot 计划唤醒与自身运行控制

- Agent 提供按 run_id 请求正常结束的能力，在当前轮工具与观察完成后执行 finish；保留后来输入交给同一调度所有者，结束请求不跨运行恢复。默认阶段保留完整工具往返并记录交流结束边界。
- Agent 的 ReAct、默认阶段及运行时 34 项针对性回归通过，覆盖本轮观察完成、新引导保留、身份拒绝和正常结束。
- 默认关闭的 `[self_control] enabled=true` 装配 bot_status、bot_autonomy、bot_finish 和 wake_schedule/wake_list/wake_cancel；所有工具绑定本实例，不新增插件或宿主进程控制。计划独立于 world/choice，到期经同一 AgentRuntime 提交，不受普通 cadence 冷却限制。
- 一次性计划支持相对时间或带时区的绝对时间、版本更新与取消，最大提前 30 天、迟到有效期默认一小时；重启只提交有效期内的到期计划，过期保留 expired。新增 state/self_control 保存开关与最多 128 条计划，pending 恢复为 uncertain；未知提交不重放。状态沿宿主异步快照保存，不承诺崩溃下恰好一次。
- 暂停同时阻止原样转发、决策投递和计划唤醒，直接交流仍可用；恢复不会清除故障。关闭等待所有自有计划任务收尾。默认产品入口只读开放新状态，旧 TOML 不被改写，新状态需有对应定义才能恢复。
- 新增 32 项离线回归通过，覆盖正式模型工具往返后的结束与唤醒、暂停重启与直接交流、过期、未知投递和回执写入失败、pending 恢复、提前更新、时间回拨、版本与实例隔离，以及在途运行共享和部分启动失败清理；原 cadence/笔记的 42 项回归及 Python 类型检查通过。未调用真实供应商。
- 11 个 wheel 构建成功，明确指定本次本地 wheel 安装后的 63 项自身控制与 Agent 回归通过，模块来自 site-packages，配置模板及六个工具定义齐全。control 环境不含 agent/adapter/模型，agent 环境不含 bot/CLI/API/模型 SDK；96 处本地文档链接及 Git 差异检查通过。
- 完整 `uv run --locked aurora check --full` 通过：1331 项 Python、115 项 TypeScript、5 项原生终端测试及全部静态检查；Python 测试耗时 250.85 秒，保留已有两项 Pydantic ReadOnly 提示。首轮新增定义契约测试缺少 ToolSpec 类型收窄，修正后完成全量复验。

### 增加受控随机时钟驱动的决策 cadence

- 显式添加 cadence 的 `[decision]` 后，随机间隔串行唤起 choice 模型，选择 observe、attend_events 或 review_work；固定模板形成引导，复用原 AgentRuntime。无该配置时保留原样转发，已有用户 TOML 不被改写。默认 60–180 秒判断、600 秒引导冷却、15 秒判断超时和 12000 字符完整 ChoiceRequest 预算。
- 决策读取有界业务视图，事件按 source_ids 过滤，笔记及行动证据按实例隔离。无事件时可检查笔记；观察不等于处理，事件去重位置和笔记冷却分别保存。当前窗口不保证旧事件逐条补发，冷却后允许再次检查未归档笔记；运行忙碌时可以补充引导，取消收尾期间明确拒绝的投递留待下次判断。
- cadence 状态 version=2 分离观察、最近判断、事件引导位置、最后投递时间、pending 与最近 64 条含材料引用的回执；不新增持久状态 ID。两模式快照不自动转换，跨模式启动拒绝并提示使用独立数据目录；未知投递、回执写入失败和恢复 pending 均暂停，模型错误不降级成行动。关闭等待在途判断取消后释放独立决策连接。
- 78 项针对性回归与 Python 类型检查通过，覆盖真实 LiteLLM 的 Jev/OpenAI 格式转换、独立连接池、观察后再次判断、随机间隔边界、无事件笔记检查、冷却恢复、忙碌运行、来源及实例隔离、预算、取消收尾、未知投递恢复、回执裁剪后去重和损坏配置/状态。未调用真实供应商或 QQ 服务，未修改 README.md、AGENTS.md 或用户数据。
- 完整 `uv run --locked aurora check --full` 通过：1297 项 Python、115 项 TypeScript、5 项原生终端测试及全部静态检查；Python 测试耗时 237.08 秒，保留已有的两项 Pydantic ReadOnly 提示。首轮发现两处插件定义总数仍为 11 的断言，按新增的三个公共定义更新为 14，并增加新增 ID 集合检查，随后完整复验通过。
- 11 个 wheel 构建成功。干净 control 环境不含 agent/adapter/模型，干净 agent 环境不含 bot/CLI/API/模型 SDK；产品 wheel 的 61 项决策协议、状态和集成测试通过，确认模块来自 site-packages、配置模板和插件定义齐全。工作区使用锁定 LiteLLM 1.106.6，干净产品环境按发布约束解析的 1.106.7 也通过相同协议测试。105 处本地文档链接及 Git 差异检查通过。

### 提供类型化选择模型与 LiteLLM 决策适配

- 在 adapter.model 增加 ChoiceClient/ChoiceFactory 单题选择契约和独立 choice_adapters 注册表，复用现有 profile、角色绑定与运行期凭证；聊天工厂和选择工厂不能混用。litellm_choice 工厂仅实例化时导入 SDK，插件发现不创建客户端。
- 复用锁定版本 LiteLLM 1.106.6 的决策转换和 HTTP handler，显式注入自有客户端，不使用全局连接池或修改 SDK 全局配置；沿用既有 litellm extra，没有新增依赖。通过 typesafe/jev-latest 选择 Jev，base_url 可指向 SystemOne 兼容服务。响应只能选择已声明项；不把概率当作随机投递概率，不自动重试或跟随重定向，错误不暴露响应正文和凭证。
- 模拟传输验证覆盖 Jev 请求契约、HTTP 错误、畸形回答、取消清理和工厂边界；未调用真实供应商。新增公共定义无独立插件、配置文件或持久状态，已有 TOML 与快照不变。底层 SDK 入口的升级须重新验证客户端注入和供应商转换。

### 默认快速边界检查与显式完整测试

- `uv run --locked aurora check` 保留全部格式、lint、Python/TypeScript 类型和客户端入口检查，默认测试限定为 `tests/contract`、共享 TypeScript 客户端和检查计划契约；不收集 Python 插件包内测试，不启动完整前端、原生终端或长耗时集成测试。
- `aurora check --test` 只运行快速边界测试；`aurora check --full` 运行静态检查与全部测试；`aurora check --test --full` 只运行全部测试。`--coverage` 使用完整测试范围，直接运行 pytest 的默认发现范围保持不变。CLI 帮助及检查输出说明当前范围。
- 将包依赖、公共命名空间、插件入口和模板归属断言移入跨包契约目录，独立进程安装边界用例仍保留在 e2e；不删除原有测试或断言。
- MCP 超时测试在模拟握手就绪后驱动真实超时取消，并确认协议回退共用同一个预算，替代固定等待和 20 毫秒启动窗口。Panel 完成断言同时等待 HTTP 完成回执与 WebSocket 活动到达，保持原有超时上限与内容断言。
- 将检查计划与执行入口合并到 `scripts/check.ts`，导入时只提供计划函数，通过 `import.meta.main` 限制命令执行；生成脚本统一为 `scripts/generate.py`，同步测试、生成产物来源和文档引用，不保留旧入口。
- 基线：1246 项 Python 测试耗时 239.29 秒，其中 3 项 TUI 用例因系统 Node 不支持 FFI 失败；使用 pnpm 提供的仓库指定 Node 后，包含这些用例的 85 项定向回归全部通过，耗时 7.58 秒。
- 验收：默认检查包含 30 项 Python 边界测试、60 项 TypeScript 契约及全部静态检查，总耗时 16.04 秒；仅快速测试耗时 4.52 秒。显式完整测试的 1250 项 Python、115 项 TypeScript 和 5 项终端测试全部通过，总耗时 238.44 秒，保留已有 Pydantic ReadOnly 提示；MCP 的 5 项超时/取消场景与 Panel 场景各重复 20 轮通过。合并检查脚本与生成入口改名后，默认检查及生成一致性复验通过。迁移前后包边界测试函数的 AST 完全相同，未修改模型、公共 ID、配置或快照格式，未调用真实供应商。

### 统一 Bot、Panel 与 TUI 快捷启动

- 增加 `aurora bot/panel/tui` 与根目录 `pnpm bot/panel/tui` 两组等价快捷命令，全部委托 `scripts/bot.py`、`scripts/panel.py`、`scripts/tui.py`；无参数即可使用项目默认配置，附加参数原样透传。CLI 只登记非宿主工具命令，不导入产品装配，也不隐式启动后端。
- 将完整产品入口从根目录 `bot.py` 移入 `scripts/bot.py`，根目录 `.env`、`data` 及环境变量优先级不变，不保留旧入口转发。TUI 的环境加载、令牌变量与启动参数从 package.json 移入脚本；Panel 复用现有 Vite 开发入口，不向浏览器注入令牌。
- 子进程收到首次终端中断后等待清理和落盘，再次中断才强制结束；新增公共命令 ID，不迁移配置或快照。同步启动指南、公共 ID 目录、架构文档、历史文档当前入口链接和入口测试。
- 验收：新增 22 项快捷命令验证，覆盖无参数分派、原样透传、退出码、非工作区错误、两组入口跨目录调用、中文及空格参数、临时偏好保存和中断收尾。Panel 在临时端口返回 HTTP 200，验收进程已关闭；未调用真实模型或用户外部服务。
- 完整 `uv run --locked aurora check` 通过：1246 项 Python、114 项 TypeScript、5 项终端测试及格式、lint、类型检查。首轮 Panel 集成断言未观察到预期活动文本，保留原断言，单项及完整复跑通过。11 个 wheel 构建成功；干净环境验证安装后的 CLI 可独立发现快捷命令、control 无需 agent/模型、agent 无需 bot/CLI/API。103 处本地文档链接和 Git 差异检查通过。

### 简化 TUI 启动命令

- 增加根目录 `pnpm tui`，自动加载可选的根目录 `.env`，默认从 `AURORA_API_TOKEN` 读取连接令牌；已有进程环境变量优先，连接地址和实例继续使用现有参数与偏好规则。令牌不进入命令行、偏好文件或业务状态。
- 复用现有 TUI 入口与 Node 原生环境文件加载，不新增依赖或后端进程；保留无认证示例入口，并同步产品启动指南。
- 验收：`pnpm tui --help`、自定义连接/实例/令牌变量参数传递、独立临时偏好保存、三份文件格式和 Git 差异检查通过；未连接后端或调用模型服务。

### 提供根目录完整产品启动入口

- 使用根目录 `bot.py` 替代 `scripts/serve_bot.py`，显式选择 MCP 产品装配，启用模型、ReAct、工具、控制、MCP 工具/世界桥、环境来源、cadence 与 API。合并 `host.toml` 的额外插件，产品装配选择优先于文件中的 assembly，不修改已有宿主配置、凭证、快照或数据库。
- 默认读取项目根目录 `.env` 与 `data/`，现有进程环境变量优先；API 默认使用 `AURORA_API_TOKEN`、端口 10270 与本机 5173 浏览器来源。访问策略在外部资源创建前校验，Bot、world、cadence 与 MCP 诊断状态只读开放，TOML 编辑保留 `--edit-config` 开关。
- MCP 完整产品 extra 和 dotenv 改为统一安装包的直接运行依赖，不依赖开发依赖碰巧安装。同步锁文件、启动指南、架构说明和历史审查文档链接，移除旧脚本及空目录占位文件，不保留转发入口。
- 新增 8 项根入口验收，覆盖工作目录独立性、环境变量优先级、启动前认证校验、缺失环境文件、帮助无副作用、不完整宿主清单下的真实 API/MCP 工具往返、环境采样、cadence 自动转交、配置编辑权限及关闭落盘；使用假模型、本地 MCP 服务和隔离数据目录。
- 完整 `uv run --locked aurora check` 通过：1224 项 Python、114 项 TypeScript、5 项终端测试及全部格式、lint、类型检查。11 个工作区 wheel 构建通过；将本次工作区 wheel 显式安装到无开发依赖的干净环境，验证 17 个插件、11 项观察状态与 6 份模板；独立环境验证 control 无需 agent/模型，agent 无需 bot/CLI/API/供应商 SDK。90 处本地文档链接与 Git 差异检查通过。

### 精简 Panel 界面文案

- 移除侧栏标语、技术栈署名、重复的工作空间标签、欢迎页口号与通用示例卡片；空白交流页保留“开始对话”和连接入口，继续使用原有蓝金配色与图形装饰。
- 删除历史上下文、状态页和输入框底部的常驻解释，缩短输入提示与连接文案；来源配置改为按需展开。保留快捷键、运行状态、错误、只读标记、停止与重试入口，并清理对应的闲置样式和图标。
- 验收：14 项 Panel 测试、TypeScript/模板类型检查、生产构建、ESLint、Stylelint、格式与差异检查通过；Chrome 使用假模型和本地工具验证连接、发送、状态筛选、草稿、重连、刷新和取消，桌面与 390px 窄屏布局通过。

### 统一 Panel 为 KunUI 并清理双版本实现

- 将 KunUI 设为唯一 Panel，正式入口为 `/`。界面移入现有 `layouts/views/components`，应用根组件保留连接生命周期，路由仍为交流与公开状态；移除 `kun.html`、对照导航、重复组件和不再使用的窄屏 composable，不保留旧入口转发。
- 删除 Naive UI、Font Awesome 的四项直接依赖与 catalog 项，刷新锁文件，安装依赖减少 23 个包。保留 KunUI、Lucide、Pinia、Vue Router 与 Tailwind；移除旧供应商分块，品牌 token 集中到 `src/theme/index.css`，继续沿用 TUI 蓝金配色。
- 按用户确认移除两个离线演示启动脚本及其公共启动器，启动指南以根目录 `.env`、现有完整宿主和 `pnpm --filter @aurorabot/panel dev` 为入口，同时保留默认 Bot 示例的独立离线验证命令。同步架构说明，不改动用户配置、凭证、业务快照或数据库。
- 真实组件验收合并为唯一 Panel 的 14 项服务/页面测试，保留全部场景与断言，删除的仅是旧界面的重复执行参数。类型检查、生产构建、固定锁文件安装通过；Chrome 验证根入口的连接、发送、工具活动、状态筛选、草稿、重连、刷新不重放且不取消、明确停止运行及 1440px/390px 布局，使用假模型与本地工具。
- 工作区验收：1216 项 Python、114 项 TypeScript、5 项终端测试通过；首次完整检查发现的两处导入排序和文档换行格式问题已修正，随后 `pnpm check --lint` 全部通过。三份更新文档的 64 处本地链接与 Git 差异检查通过。

### 迁移本机旧适配包配置

- 经用户确认，备份本机 `data/config` 后，将旧 `aurora_model_adapter`、`aurora_adapters.mcp*` 插件名更新为当前入口，迁移模型与 MCP 配置路径，并同步装配、模型适配器、世界来源及配置路径引用。用户配置与备份均保持在 Git 忽略目录中。
- 先在配置副本验证，再应用到原目录；15 个宿主插件、6 项声明配置、模型角色绑定、装配与世界来源引用校验通过，`aurora --data-dir data --help` 插件发现通过。核对业务快照与数据库字节内容未变化，未创建模型、工具或外部连接。

### 提供两版 Panel 的一键体验入口

- 增加根目录 `start-panel-naive.cmd` 与 `start-panel-kun.cmd`，共用 `scripts/panel_demo.py`，自动启动前端与默认 Bot 离线示例并打开对应页面。分别分配前端 5173/5174、API 10271/10272 和独立演示数据目录，可同时比较。
- 运行期生成临时令牌并在启动窗口提供连接信息，不写入配置、前端日志或浏览器存储，不传给前端进程。Ctrl+C 等待宿主清理与落盘，再关闭自有前端进程树；端口冲突明确退出，不操作已有服务。启动说明同步至 `examples/START.md`。
- 两个启动器同时运行的实测通过：页面返回正确入口、各自 API 认证成功、取消后生成业务快照、临时环境变量恢复、四个端口释放。脚本 Ruff 格式/lint、Pyright、文档格式与差异检查通过。

### 增加 KunUI 与 Lucide 的 Panel 对照版本

- 在 `feat/panel-kun-ui` 增加独立 `/kun.html` 入口，原版 Panel 保留在 `/`。采用 KunUI 的按钮、输入、文本域、选择器、抽屉和状态标签，Lucide 使用当前官方 Vue 包 `@lucide/vue`。两版共用连接、回执、取消、草稿与交流投影逻辑，不新增后端契约或公共 ID。
- 新版以聊天为中心，固定输入区，工具活动与后端历史按需展开，公开状态独立路由；浅色背景、圆润控件和小型星光装饰提供轻量 ACG 风格。强调色 `#4B79EC`、对比色 `#ECBE4B` 与 TUI 保持一致。桌面侧栏在窄屏收为图标导航。
- Vite 同时构建两个 HTML 入口；KunUI 的 Tailwind 和 token 样式仅由新版引入，保留原版样式。依赖通过 catalog 和锁文件固定，仅允许 KunUI 间接依赖 vue-demi 的安装脚本；既有 TUI TypeScript peer 提示仍存在。
- 将真实组件 DOM 验收参数化为两版共用：21 项 Panel 服务与页面测试通过，覆盖中文组字、草稿隔离、路由前进后退、令牌清空、非法地址、连接中断与卸载清理。保留同轮输入后立即提交和切换实例的断言，提交在输入更新后清空，文本域按后端与实例隔离。
- Chrome 加载生产产物，验证连接、提交、工具观察、状态筛选、草稿保持、后端重启、刷新不重发且不取消、重新连接后明确停止运行；1440px 与 390px 布局通过。确认品牌蓝及用户头像暖金的计算样式。使用离线模型与本地工具，未调用真实供应商。启动和对照入口同步至 `examples/START.md`。
- 完整检查的 1216 项 Python、121 项 TypeScript、5 项终端测试通过；首轮发现 Vite 新导入位置与相对 URL 写法不合规范，修正后完整 `pnpm check --lint` 通过。快速提交修复后重新通过 21 项 Panel 测试、类型检查、构建、局部 lint 和 Chrome 流程；原版生产页面也完成相同浏览器回归。固定锁文件安装、43 处本地文档链接及差异检查通过，保留既有 Pydantic ReadOnly 提示。

## 2026-11-07

### 对齐 Panel 与 TUI 的品牌配色

- 以 `apps/aurora_tui/assets/palette.svg` 为依据，将 Panel 强调色统一为主题蓝 `#4B79EC`，对比色统一为暖金 `#ECBE4B`，hover/pressed 使用浅蓝 `#81A1F2` 与深蓝 `#3555A5`。品牌色集中在 `src/theme`，导航、主按钮、品牌标识和 Bot 头像使用蓝色，用户头像使用暖金配深色文字。
- Panel 的 14 项既有测试、类型检查、生产构建、格式/lint 检查通过；Chrome 复验桌面与窄屏流程，并核对蓝色品牌标识与暖金头像的实际计算样式。未更改后端行为、公共 ID 或数据格式。

### 按职责重构 Panel 并接入成熟组件库

- 将根组件中的连接、导航、交流、工具和状态展示拆为 layouts/views/components；services 保存无界面的连接与回执控制，stores 使用 Pinia 统一持有跨页状态和内存草稿，composables 管理视图投影及监听，types/constants/utils/theme/styles 分别维护契约、常量、辅助函数、主题和基础样式。移除手写 SVG 图标和原集中样式文件，无兼容转发层。
- 使用 Naive UI 的表单校验、输入、选择、导航、抽屉、提示、折叠及数据表格；产品图标按用户要求统一使用 Font Awesome，未保留 Ionicons 依赖。主题集中配置，布局样式按组件 scoped。Vue Router 提供 Hash 路由与页面延迟加载，浏览器前进/后退保留草稿与筛选；切页复用同一个订阅所有者。
- 保留接纳/完成区分、未知请求核对与显式重试、会话失效、明确取消及关闭不取消的语义。令牌从表单临时解析，不进入 Pinia 状态或 action 的值参数；连接表单明确当前页面 Origin，校验完整 API 地址。开启严格 Vue 模板检查，按真实组件契约处理属性和响应式侧栏。
- 14 项 Panel 服务/真实组件 DOM 测试通过，新增路由前进/后退、连接复用、跨实例/后端草稿隔离、非法 URL 校验及令牌不进入 Pinia 检查。Chrome 加载生产构建验证连接、发送、工具观察、状态筛选、断线恢复、刷新不重发且不取消、重新连接后停止运行；桌面与 390px 窄屏检查通过。回归使用假模型和本地工具，未额外调用真实供应商。
- 完整检查中的 1216 项 Python、114 项 TS、5 项终端测试通过；首轮 lint 检出模板插槽换行问题，修正后完整 `pnpm check --lint` 通过，保留既有 Pydantic ReadOnly 提示。固定锁文件安装、严格模板类型检查、生产构建及 64 处本地文档链接检查通过。构建分块的浏览器复验发现初始化顺序错误，启用 strictExecutionOrder 后最终产物的完整浏览器流程通过。
- 本机开发页面已确认能连接现有真实模型宿主，原后端进程未重启；本次只观察连接，不额外提交真实模型请求。应用根组件缩为 26 行、全局基础样式缩为 55 行；启动与工程分工同步写入示例指南和架构设计，README.md/AGENTS.md 未修改。

### 提供浏览器连接、交流与只读状态工作台

- Panel 从包声明补齐 Vue/Vite 应用、生产构建、预览和 vue-tsc 类型检查；使用工作区 Vue/Vite 版本，新增 vue-tsc 固定依赖与锁文件，不引入额外 UI 框架。
- 页面提供显式令牌连接、Bot 实例选择、按运行展示的交流/模型过程/工具结果、指定运行取消及只读状态筛选。中文组字和换行不提交，切页保留草稿，地址与实例间草稿分开；后端数据作为文本呈现。令牌在提交连接后从表单清空，不保存连接、凭证或草稿到浏览器存储。
- 共享 client 管理认证和重连，Panel 只维护观察与请求回执。接纳不等于完成，终态通过 query 核对；断线与刷新不重放或取消，未知接纳可核对及显式重试原请求；重启后旧身份失效，慢旧响应和旧连接通知不能覆盖新会话。关闭页面释放订阅与计时器，连接等待中仍可主动断开。
- 默认 Bot 离线示例同步 token-env 与 allowed-origin，启动指南提供无需模型密钥的 Panel 体验路径。无新增公共 ID、插件或业务快照格式，配置/ctx 编辑、持久偏好和生产 TLS 代理部署不在本切片范围。
- 11 项 Panel 状态/DOM 测试与默认装配的真实 Node 工具往返通过。Chrome 加载生产构建验证连接、提交、观察、状态筛选、草稿、API 重启、刷新不重发且不取消、重新连接后停止运行；桌面 1440px 与窄屏 390px 截图检查通过，无横向溢出。仅使用假模型和本地工具。
- 完整检查中的 1216 项 Python、111 项 TS、5 项终端测试通过，保留既有 Pydantic ReadOnly 提示；首轮 stylelint 检出窄屏样式规则间缺少空行，修正后完整 `pnpm check --lint` 复验通过。固定锁文件安装、Panel 生产构建和 11 个 Python wheel 构建通过，文档链接与差异检查通过。

### 开放显式认证的浏览器 HTTP/WS 访问

- API 新增 AccessPolicy，默认保留仅本机非浏览器访问；来源或额外 Host 必须绑定运行期令牌。HTTP 使用 Bearer，WS 首帧认证成功后才订阅；预检仅接受显式开放的路由、方法与请求头。来源/Host 拒绝返回 403，令牌拒绝返回 unauthorized，不回显凭证。
- 服务仍监听回环地址，生产 HTTPS/WSS 由代理终止；不信任 Forwarded/X-Forwarded-*。认证不扩大状态键、只读状态或端点范围，令牌不进入 TOML、ctx、快照或界面偏好。无新公共 ID、插件或业务快照格式；生成契约新增 WatchHandshake，原过滤类型与默认本机请求保持兼容。
- TS/Python client、CLI serve/connect、serve_bot 与 TUI 同步运行期令牌入口。WS 断线重新认证并刷新，认证拒绝停止自动重连，HTTP 动作不重放；同步使用指南、架构与接续队列，token 预算及输出预留按用户要求暂缓。
- Chrome headless 以真实跨端口页面加载共享 client 的 Vite 构建产物：CORS 请求、WS 状态推送、默认 bot 提交与取消、错误令牌、API 重启重连均通过；未开放来源被浏览器阻止。使用假模型和本地工具，未调用供应商；生产 TLS 代理与 Panel 页面尚未验收。

- 完整检查中的 1214 项 Python、100 项 TS、5 项终端测试通过，保留既有 Pydantic ReadOnly 提示；首轮 lint 检出新增 TS 测试写法与接口排序问题，修正后完整 `pnpm check --lint` 与 55 项共享 client 测试复验通过。测试使用仓库固定的 Node 26.13；系统 Node 24 不支持终端 FFI 参数。
- 11 个 wheel 构建成功；干净 API wheel 环境不含 bot/agent/CLI，确认模块来自 site-packages，28 项 API 协议与认证测试通过。76 处本地文档链接、文档格式及差异检查通过。

## 2026-11-06

### 修复巡检示例将输入预算提示识别为任务

- 复现 PR #5 的 P2：默认装配启用输入预算并省略历史时，live_workshop 将 input_budget 提示识别为缺少 text 的巡检任务，导致运行失败。离线模型现在同时跳过 business_context 和 input_budget，只对实际引导生成工具调用；同步示例启动指南。
- 新增 4 项跨进程回归，覆盖流式/非流式与启用世界输入/direct-only 的组合：恢复超限历史后实际触发省略，核对每轮请求的预算和提示、唯一巡检及报告、完整工具关联与成功结果。修复前失败，修复后全部通过。

- 61 项定向回归及完整 `uv run --locked aurora check` 通过：1196 项 Python、97 项 TS、5 项终端测试，以及格式、lint、Python/TS 类型检查通过，保留既有 Pydantic ReadOnly 提示。未变更依赖、公共 ID 或存储格式，未调用真实模型或 QQ 服务。

### 修复空回复结束的交流无法参与预算裁剪

- 复现 PR #5 的 P2：1024 字符预算下每次约 350 字符，前两次静默正常结束，第三次触发 ModelInputBudgetExceeded；流式、非流式及重启场景均复现。
- ReActContext 新增可选 exchange_ends，正常 stop 无论正文是否为空均保存当前历史结束位置，预算关闭时同样记录；不追加空白 assistant 消息，不把元数据发送给模型。无新增消息的重复静默结束不产生重复边界，模型失败、取消和未完整结束的响应不记为完成。
- 预算按显式边界裁剪完整交流；边界类型、顺序、范围及工具关系严格校验。旧快照缺少字段时仅重建已有 assistant 回复可证明的结束位置，不能推断历史静默结束；不迁移或删除用户数据。live_workshop 裁剪历史时同步过滤和平移位置，文档补充快照和消费者影响。
- 51 项预算、默认阶段与默认装配回归通过，包含连续静默、流式/非流式、先关闭预算再启用、正常重启、边界损坏、完整工具关系及原有超限重试；持续示例的 6 项回归通过。未修改 README.md、AGENTS.md，未调用真实供应商或 QQ 服务。

- 完整 `uv run --locked aurora check` 通过：1192 项 Python、97 项 TS、5 项终端测试及格式、lint、Python/TS 类型检查通过，保留既有 Pydantic ReadOnly 提示。11 个 wheel 构建成功，独立 agent wheel 的 33 项预算/默认阶段测试和产品环境的 18 项预算集成测试通过；84 处本地文档链接、文档格式及 `git diff --check` 通过。

### 提供完整模型请求字符预算

- agent 新增 ModelInputBudget 和明确的 ModelInputBudgetExceeded。ReActDefaults 在每轮 prepare 生成统一请求后约束完整 JSON 字符数，覆盖 system、当前视图、历史及工具定义；不是供应商 token 或 HTTP 字节上限。
- 超限时按完整交流段从旧到新选择最少省略范围，保留最新交流及其全部引导、工具请求和结果，临时省略提示同样计入预算。必要内容仍放不下时清除旧 model_input 并阻止模型调用；持久历史及已完成工具结果不删除，显式重试不重复接纳或执行。
- bot 新增可选 `[input_budget] enabled=false`，max_chars 默认 128000、最小 1024；由默认装配注入策略，不新增公共 ID、插件、依赖或快照字段，已有配置默认保持行为，模板不覆盖用户文件。
- 23 项新增单元与默认装配回归通过，覆盖完整 JSON/Unicode 计数、固定材料超限、最少完整交流省略、流式/非流式工具关系、重启历史保留和超限后显式重试。同步启动指南、架构及接续计划，未修改 README.md、AGENTS.md 或用户数据，未调用真实模型或 QQ 服务。

- 完整 `uv run --locked aurora check` 通过：1176 项 Python、97 项 TS、5 项终端测试，以及格式、lint、Python/TS 类型检查通过，保留既有 Pydantic ReadOnly 提示。补充的最少省略断言在工作区及独立 agent wheel 中复验通过。
- 11 个 wheel 构建成功；从明确 wheel 路径安装的干净 agent 环境无 bot/CLI/API/模型 SDK，25 项预算及默认阶段测试通过；产品 wheel 的 10 项预算集成测试通过，模块来自 site-packages，包内 input_budget 模板可读。85 处本地文档链接、Prettier/Ruff 文档格式与 `git diff --check` 通过。

### 提供可持久查询的工具执行证据

- agent 的 ToolExecutor 接受可选 ToolRecorder，覆盖批次接纳、实际调用前和结果接纳前边界；记录失败阻止继续执行，取消后未调用项保留未执行。agent 不依赖 bot、world 或数据库，原 before_call/after_call 和结果接纳契约保留。
- bot 新增 `[actions] enabled=false`、actions_read 及组件/工具公开定义；启用后在 bot 命名空间 actions.sqlite3 按实例和 run_id/call_id 独立事务保存证据。工具返回、未执行和结果待核实分别呈现，未知结果不重试，重复引用拒绝整个新批次，笔记不能覆盖执行事实。
- 记录器 start 抛出超时或拒绝异常时保留原因为装配故障，阻止工具和后续调用，不将其伪装成可继续处理的工具观察；补充两项执行边界回归。
- 查询固定当前实例，按 Unicode 字符位置分页，max_chars 默认 8000、范围 1024–32000，约束每页 value 的完整 JSON。SQL 分段读取结果；每轮业务视图按总预算提供最近 16 次调用摘要，可单独隐藏。记录永久保留，关闭功能不删数据，不新增插件、依赖或 ctx 持久状态，旧快照无需迁移；完整备份须包含新增数据库。
- 69 项定向回归通过，覆盖流式/非流式往返、笔记引用、重启分页、取消、未执行、结果写入失败、实例隔离、重复引用、严格预算和工具参数拒绝。同步启动指南、公共 ID、架构与接续计划；未修改 README.md、AGENTS.md 或用户数据，未调用真实模型或 QQ 服务。

- 最终完整 `uv run --locked aurora check` 通过：1153 项 Python、97 项 TS、5 项终端测试及格式、lint、Python/TS 类型检查通过，保留既有 Pydantic ReadOnly 提示。首次全量中的 MCP 20 毫秒启动预算用例在进入模拟传输前超时，单文件 35 项及后续完整检查均通过，未改断言；新增文档换行格式已修正并复验。
- 11 个 wheel 构建成功。通过明确 wheel 路径安装验证，干净 control 环境不含 agent/adapter/模型，干净 agent 环境不含 bot/CLI/API/模型 SDK 且 22 项工具测试通过；产品 wheel 的 27 项证据单元与集成测试通过，模块确来自 site-packages，包内 actions 模板可读。96 处本地文档链接及 `git diff --check` 通过。

### 对齐归档工具的 JSON Schema 整数偏移

- 同步 PR #2 的笔记整数参数修复，并修复 PR #3 中 offset=0.0 通过公开 schema 后被内部 ConfigSchema 拒绝的同类问题。归档工具边界将整数值浮点偏移复制为 int，WorldRecords 的严格整数接口及配置校验保持不变。
- 通过实际 ToolExecutor 复现并补充完整分页、过期引用及重启后的浮点偏移回归；布尔值、小数、字符串、负值及超出 SQLite 范围的偏移继续返回 invalid_arguments，不读取或修改事件。
- 45 项定向回归通过；完整检查中的 1118 项 Python、97 项 TS、5 项终端测试、格式与 lint 通过，1 项平台用例跳过。新增测试辅助函数的 offset 类型标注修正后，单独重跑 `pnpm run typecheck`，Python/TS 类型检查均通过；`git diff --check` 通过。未变更公开 schema、依赖或存储格式，未调用真实模型服务。

### 对齐笔记工具的 JSON Schema 整数参数

- 修复 PR #2 中公开 schema 接受 expected_revision=0.0、limit=1.0，但笔记内部严格整数校验导致 tool_failed 的问题。工具执行边界对这两个字段中的整数值浮点数生成 int 副本，保持原始调用参数、配置校验与持久状态约束不变。
- 使用默认装配的实际 ToolExecutor 复现并回归：创建、更新、过期版本冲突及分页接受整数值浮点数，状态中的 revision 保持 int；布尔值、非整数小数、字符串及越界值继续返回 invalid_arguments，原笔记不变。
- 34 项定向回归通过；完整 `uv run --locked aurora check` 通过，包括 1087 项 Python、1 项平台用例跳过、97 项 TS、5 项终端测试及格式、lint、类型检查，保留既有 Pydantic ReadOnly 提示。无依赖、公共 ID 或快照格式变更，未调用真实模型服务。

### 将按引用读取事件归档接入默认 bot

- 新增 components/world/read_event、其 execute 入口及 tools/world/read_event，模型名称 world_read_event。bot 的 `[archive]` 默认关闭，启用后绑定宿主持有的 WorldRecords；缺少 world 或手工覆盖数据库配置明确拒绝，不新增插件、资源所有者、依赖或持久状态。
- 按 journal_id/record_id/offset 读取原始事件 JSON，保留身份、来源、时间及 next_offset。max_chars 默认 8000、范围 1024–32000，约束整个 value 的 JSON 长度，包含转义及元数据、不含 ToolResult 外层信封；长内容分页，不能容纳身份或正文时明确失败。错库、缺失、越界和服务不可用分别反馈，不自动换库或重试。
- 读取不修改笔记、不消费或重放事件；只支持已知事件引用，不提供环境观察、工具调用查询或归档搜索。启用后每轮业务视图提示读取方法，工具与视图开关独立；现有数据库及快照无需迁移。
- 54 项工具、配置和分页单元测试及 5 项默认装配集成测试通过：覆盖 Unicode/转义预算、退出近期窗口后按笔记引用还原、错误反馈、完整工具关联、正常重启及显式再次读取；禁用时不宣告工具，无 world 时不创建数据库。同步模板、启动指南、公共 ID、架构与接续计划。
- 完整 `uv run --locked aurora check` 通过：1115 项 Python 通过、1 项 Windows 平台用例跳过，97 项 TS、5 项终端测试及格式、lint、Python/TS 类型检查通过，保留既有 Pydantic ReadOnly 提示。11 个 wheel 构建成功；干净 world 环境的 47 项测试及产品环境的 18 项归档/笔记恢复测试通过，确认 world 无 bot/agent/adapter/config 依赖、模块来自 wheel，包内模板、工具定义和最小视图预算可用。
- 93 处本地文档链接及 `git diff --check` 通过；基于待审查的 PR #2 建立 feat/event-archive 分支。未修改 README.md、AGENTS.md 或用户数据，未调用真实供应商或 QQ 服务。

### 提供核对数据库身份的事件原文分页接口

- world 新增 `WorldRecords.read_content` 和不可变 `WorldContentPage`，按 journal_id/record_id 读取数据库中原始 JSON 的字符片段，保留来源、消息、接收时间及位置。分页直接查询 SQLite，不先反序列化完整载荷，不刷新 ctx、消费或重放事件。
- 错库、缺失记录和越界位置明确失败；环境观察不属于事件归档。每页最多 65536 字符，拼接全部 text 后才是完整 JSON，next_offset 为 null 表示结束。现有数据库、快照、公共 ID 和依赖不变。
- 47 项 world 读取与记录测试通过，覆盖 Unicode、转义、空值、多页重组、只读和分页参数边界。

### 将工作笔记接入默认装配和每轮业务视图

- bot 配置新增可选 `[notes] enabled=false`；显式启用后自动装配 notes_read/write/list，模型所有者由 bot 工作状态绑定固定，不允许模型参数或工具配置覆盖。已有插件入口不变，发现只登记定义，不创建笔记或后台资源。
- context_view 新增 notes 选择，未归档笔记与事件、环境按非空材料类别平分完整视图预算。无需 world 也能写笔记和刷新视图，工具写入后下一轮可见；笔记超长时保留完整身份并标注截短，可通过工具读取全文，归档数据仍可查询。关闭功能保留已有状态，视图开关与工具启用分别控制。
- serve_bot 将 notes 状态作为只读观察键开放。同步包内模板、启动指南、公共 ID、架构和接续计划；笔记与引用只表示工作材料，未知外部动作不因笔记内容变成成功，事件归档读取工具仍为下一切片。
- 定向回归覆盖工具往返、版本冲突反馈、实例隔离、有/无 world、功能关闭后的数据保留和正常重启；另验证写入已完成但工具观察未接纳时取消，恢复后接纳原结果且不重复写入。11 个 wheel 构建完成，干净产品环境的 28 项笔记与视图测试、包内模板及工具定义检查通过。未修改 README.md、AGENTS.md 或用户数据，未调用真实供应商或 QQ 服务。
- 完整 `uv run --locked aurora check` 通过：1085 项 Python 通过、1 项 Windows 平台用例跳过，97 项 TS、5 项终端测试及格式、lint、Python/TS 类型检查通过，保留既有 Pydantic ReadOnly 提示。92 处本地文档链接及 `git diff --check` 通过；基于已合并 PR #1 的 main 开发。

### 提供实例隔离的持久工作笔记及工具定义

- 新增 org.aurora.bot:state/notes、components/notes 及其 execute 入口、tools/notes/read、write、list。笔记按 bot instance_id 隔离，使用自由文本、active/archived 状态和结构化引用，框架维护版本、时间及最近写入的 run/execution/call 身份；笔记与引用不证明外部动作成功。
- notes_write 使用 expected_revision=0 创建，更新须匹配当前版本；冲突不覆盖。notes_list 提供分页摘要，notes_read 提供完整正文及归档内容。每实例最多 128 条、正文最多 16000 字符、引用最多 16 项，容量不足明确拒绝创建，不自动淘汰。归档隐藏当前视图但保留数据和容量占用。
- 状态通过宿主快照保存，工具成功只表示 ctx 更新完成，不承诺逐次落盘。没有新插件、包或依赖；旧快照无需迁移，新笔记状态须由登记其定义的版本恢复，不静默忽略未知状态。定向回归覆盖版本冲突、实例隔离、引用保留、查询分页、状态损坏、容量与读取副本隔离。

### 将近期事件与环境观察接入默认 bot 的每轮视图

- 默认装配在启用 world 时提供 BusinessContextView，每次 prepare 刷新近期窗口，再以临时 user 消息呈现事件及环境观察。条目保留来源、消息、记录、数据库身份和接收时间；读取范围限定为 world 两类业务状态，不遍历配置、凭证或模型工作区。
- bot 配置新增可选 `[context_view]`，enabled/events/environment 默认 true，max_chars 默认 12000、最小 1024。预算包括完整视图 JSON；两类非空材料平分预算，优先保留最新记录。截短正文标记 abridged，完整身份仍保留；放不下的整条记录以 omitted 计数。该预算不限制完整模型请求，也不删除归档或改变世界去重。
- 直接交流与 cadence 原始 payload 转交保持既有契约，观察视图不充当待办或完成回执。未启用 world 或关闭视图时直接交流保持原有输入。live_workshop 的离线模型识别观察块，仅对引导生成巡检动作；同步配置用法、设计、公共扩展契约与接续计划。按用户决定暂缓社区工程化。
- 无公共 ID、插件或快照结构变更；旧 bot 配置缺少该段时采用默认值，已有配置文件不被模板覆盖，修改后重启生效。临时视图不进入持久对话，正常收尾清理 model_input；恢复后的 prepare 重新构建观察，保留完整工具请求及结果关联。
- 定向验证通过：来源与内容隔离、严格字符预算和转义文本、过期刷新、归档与去重保留、无 world/显式关闭视图、streaming/非 streaming 工具更新与下一轮刷新、直接交流及关闭恢复。11 个 wheel 构建完成；干净环境确认 control 无 agent/模型包、agent 无 bot/CLI/API/world/模型 SDK，agent 12 项默认阶段测试及产品 wheel 的 11 项视图测试通过，包内配置模板可读取。未调用真实供应商或 QQ 服务。
- 完整 `uv run --locked aurora check` 通过：1065 项 Python 通过、1 项 Windows 平台用例跳过，97 项 TS、5 项终端测试及格式、lint、Python/TS 类型检查全部通过，仅保留既有 Pydantic ReadOnly 提示。91 处本地文档链接与 `git diff --check` 通过；README.md、AGENTS.md 及用户数据未修改。

### 为每轮推理接入临时上下文视图

- ReActDefaults 接受装配提供的同步 context_view 回调，每次 prepare 生成临时 user 观察；system 保持原配置，历史消息和 assistant/tool 关联沿用既有接纳机制。视图不写入持久 ReActContext，回调失败阻止本轮推理，后续显式重试不重复接纳引导。
- agent 定向回归通过，覆盖推理期间观察变化、跨轮与跨运行刷新、历史隔离、工具关联，以及视图失败后重试。agent 不新增 world/bot 依赖，不新增公共 ID、插件或快照字段。

### 明确新功能分支与 PR 合并规范

- 经用户确认，在 AGENTS.md 中规定新功能使用 `feat/<功能名>` 分支开发，完成验证后通过 PR 合并到 `main`。
- 仅调整开发规范与变更记录；文档格式、本地链接及 `git diff --check` 检查通过。

### 合并远端更新并衔接适配器迁移

- 合并远端的 API 只读状态、执行清理异常和 live_workshop 双路径更新，保留本地单数 aurora_adapter 包、公共 ID 与包级测试布局。
- 解决持续示例的模型导入和模板路径冲突：使用 aurora_adapter.model 与 model/profiles.toml、model/bindings.toml，同时保留 world/cadence 配置。启动指南使用包级 cadence 测试路径并注明双路径验收已完成；保留双方已有变更记录。
- 104 项持续宿主、默认装配、API 与 cadence 针对性回归通过；完整 `uv run --locked aurora check` 通过，包括 1049 项 Python、97 项 TypeScript、5 项终端测试及格式、lint、类型检查，保留既有 Pydantic ReadOnly 提示。
- 11 个 wheel 构建成功，适配器与示例配置模板、本地文档链接及 `git diff --check` 通过。验证使用离线模型与本机传输，未调用真实供应商。

### M4.W4：统一持续示例的双路径并完成安装验收

- live_workshop 的模拟来源改为正式 SourceInstance，由 world 配置服务托管并通过绑定 emit 归档；cadence 向同一个 AgentRuntime 转交。移除示例自有 inbox 写入、激活循环和后台调度任务，直接交流通过 conversation 的提交、查询及指定运行取消。来源暂停只停止产生新巡检事件，已归档事件仍可被接纳。
- 保留四类控制组件、SQLite 报告台账及运行观察。历史裁剪接入 ReAct finish，保留最近引导及完整 assistant/tool 关联，跨裁剪边界的工具往返回退至完整输入组；取消的工具观察继续由默认恢复策略接纳，不重试副作用。
- 增加 world/cadence 示例配置和 --direct-only 模式；后者不启用 world/cadence，不创建世界数据库。API 只开放 settings、bindings 的写操作，运行、报告、世界和消费状态仅可观察。启动指南同步提供 conversation 调用和两种模式的独立数据目录。
- 移除旧示例 state/request 和自有调度处理器，新增 dev.example.workshop:sources/workshop 与 finish/observer 处理器。含旧定义的快照须保留原目录并使用新目录，不增加兼容别名或自动改写数据；含 world/cadence 状态的目录不能切换成未启用对应插件的模式。README.md、AGENTS.md 与用户 data 未修改。
- 58 项相关回归通过；新增双路径共用 run_id、运行中直接交流、只读写入拒绝、取消收尾、关闭恢复、重复转交抑制及未启用 world/cadence 的验收，原有控制流程、工具故障、报告恢复与上下文保留断言继续通过。
- 完整 `uv run --locked aurora check` 通过：1042 项 Python、97 项 TS、5 项终端测试；Linux 跳过 1 项 Windows CMD/PATHEXT 用例。格式、lint、Python/TS 类型和生成契约检查通过，保留既有 Pydantic ReadOnly 提示。
- 12 个 wheel 构建成功。临时干净环境显式安装本次本地 wheel，验证 control 无 agent/模型依赖、agent 无 bot/CLI/API/world 的工具往返与引导/重启、world 基础包及配置组合的去重恢复。产品 wheel 环境的 20 项 live_workshop/API 回归通过，核验导入路径、版本和配置资源，未借助工作区 editable 安装。普通回归未调用真实模型、NapCat 或 QQ 业务服务。
- W4 已交付；下一步按主动上下文讨论稿推进业务视图、工作笔记和归档读取，QQ 真实行为验收另行安排。

### 保护 API 观察状态并保留执行清理异常

- API 和 CLI serve 增加 read_only_keys / --read-only-keys，与现有读写 keys 分开声明；重叠配置明确拒绝。只读键允许 get/list/watch，所有 location 的 set/delete 均返回 forbidden。serve_bot 的 bot、world 和 cadence 观察状态统一只读，交流和配置仍通过对应产品端点完成。公共 ID、快照和现有 keys 的读写语义不变。
- 默认装配清理失败时保留原执行异常及清理异常链，取消仍保持取消语义；单独清理失败明确抛出，所有路径释放执行占用。
- 82 项 API 契约、默认装配与 CLI 回归通过，覆盖只读订阅、写入拒绝、完成/失败/取消后的清理故障。测试使用本机回环服务和模拟模型传输；沙箱禁止绑定端口，已在允许本机端口的环境完成验收。

## 2026-11-04

### 按包归置模块测试并清理里程碑验收入口

- 将根目录 39 个单元测试文件及 4 个包级契约测试文件迁到对应的 `packages/<包>/tests/unit`、`tests/contract`，覆盖 core、config、control、agent、adapter、bot、CLI、API、logging 和 world。按实际职责将原 `test_bot_control.py`、`test_bot_tools.py` 分别归入 control 和 agent，并改为 `test_control.py`、`test_tools.py`。
- 工作区安装测试移至根目录 `tests/e2e/test_workspace.py`；跨包契约、生成产物一致性、示例和真实进程集成继续保留在根目录 `tests`。根目录 `conftest.py` 提供按需加载 agent 的共享装配 fixture，消除 bot 测试对 agent 测试文件的直接导入，保留原有测试断言。
- pytest 默认发现同时覆盖 `packages/*/tests` 和根目录 `tests`；Pyright 纳入包内测试及共享 fixture。同步设计文档、测试命令和示例启动指南中的路径，经用户确认同步 AGENTS.md 的目录、测试规范和示例命令；适配器测试按当前工作区合并后的 `aurora_adapter` 归置，不改动公共 ID、配置或快照。
- 删除独立的 `test_m2_acceptance.py`、`test_m1_shutdown.py`、`test_m1_cli_process.py` 入口，将仍有效的 bot 无宿主依赖、并发写入与最终落盘、真实 CLI 中断及故障恢复测试分别并入 `test_package_boundaries.py`、`test_lifecycle_persistence.py`、`test_cli.py`。CLI 夹具改为 `cli_shutdown_plugin.py`，同步临时插件名、测试命名空间和故障注入环境变量；保留全部断言和 5 项参数化用例。
- 删除没有自动化消费者的 `tests/fixtures/environment_roundtrip.py` 手工验收脚本，文档改为引用现有环境来源单元测试与默认装配环境集成测试，覆盖周期采样、观察、持久化和恢复。其余进程夹具均仍被当前回归使用，检查、契约生成和产品启动脚本继续保留。
- 经用户确认删除 `scripts/accept_m2.py`，移除里程碑专用的真实模型双模式验收编排和报告入口；现有默认装配回归继续验证工具往返、终态、收尾和恢复。同步 AGENTS.md 与示例启动指南，真实模型验收改用当前 CLI、独立数据目录及显式配置。本次未调用真实模型或天气服务。
- 验收：迁移前后收集到相同的 1042 项用例；719 项包级测试、合并后的 42 项 CLI/生命周期/包边界回归全部通过。在 `packages/aurora_bot` 下单独运行会话测试，4 项通过，共享 fixture 不依赖其他包测试的收集顺序。最终 `uv run --locked aurora check` 全部通过：1042 项 Python、97 项 TS、5 项终端测试，以及格式、lint、Python/TS 类型检查；仅有既有 Pydantic ReadOnly 提示。迁移后的 20 处测试路径引用及文档格式检查通过。

### 合并模型与外部协议适配到单数 aurora_adapter

- 将 `aurora_model_adapter` 并入 `aurora_adapter.model`，将 `aurora_adapters` 改为 `aurora_adapter`，仅发布 `aurora-adapter`。统一维护模型协议、FakeModel、供应商工厂及 MCP 客户端与桥；移除旧分发包、导入路径和插件入口，不提供兼容转发。
- 基础包仅依赖 core；`[model]` 安装配置服务，`[litellm]` 加入原 LiteLLM SDK 依赖，`[mcp]`、`[mcp-world]`、`[mcp-tools]`、`[mcp-bot]` 按原职责安装。agent 仅依赖基础包，bot 选择 `[litellm]`。插件仍须显式启用，发现模型插件不加载 SDK，MCP 客户端和世界桥不导入模型模块。
- 模型插件改为 `aurora_adapter.model`，MCP 插件前缀改为 `aurora_adapter.mcp`；定义统一归属 `org.aurora.adapter`。MCP ID 只更换命名空间；模型 ID 按下表更换，provider 与插件名同步。公共 ID 的 registries/tools 等集合 domain 及配置字段保留既有契约，本次单数命名针对适配包。

| 旧模型 ID（前缀 org.aurora.model_adapter:） | 新 ID（前缀 org.aurora.adapter:） |
| --- | --- |
| `registries/adapters` | `registries/model/adapters` |
| `services/model_client` | `services/model/client` |
| `schemas/model_request`、`model_response`、`model_chunk`、`model_capabilities` | `schemas/model/request`、`response`、`chunk`、`capabilities` |
| `adapters/litellm` | `adapters/model/litellm` |
| `configs/profiles`、`configs/bindings` | `configs/model/profiles`、`configs/model/bindings` |
| `state/config`、`state/bindings` | `state/model/config`、`state/model/bindings` |

- 包内模板统一位于 `aurora_adapter/config.tomls/`。用户配置根目录下的 `org.aurora.model_adapter/profiles.toml`、`bindings.toml` 分别迁至 `org.aurora.adapter/model/profiles.toml`、`model/bindings.toml`，`org.aurora.adapters/config.toml` 迁至 `org.aurora.adapter/mcp.toml`。模板仍只复制缺失文件；升级前须显式备份并迁移原配置，更新 host 插件/assembly、profile.adapter、bot 显式工具 ID、world source ID 等引用，否则旧选择会被拒绝或新模板为空。既有 MCP v1→v2 migrate 命令只转换配置结构，不承担本次包名或快照迁移。
- 模型配置、MCP 配置与观察状态均非持久，无这些状态项的正常快照可原样恢复；业务值中的旧工具或来源 ID，以及 world 数据库已有来源身份仍需宿主核对并显式迁移，避免历史引用失效或去重身份变化。未知状态继续报错，不自动忽略；本任务未修改用户 data、凭证、业务快照或数据库。
- 同步 workspace/锁文件、消费者、示例、公共 ID 目录与架构说明。用户允许同步 AGENTS.md 的适配包职责与命名；README.md 当前为空，无相关内容需要修改。历史变更条目保留当时名称。
- 分发验收：11 个 wheel 构建通过，模型 profiles/bindings 与 MCP 三份模板均包含在统一包内。所有 Aurora 依赖约束到本次 wheel，在 7 个干净环境中分别验证 control 独立运行、无 config/SDK/产品包的 agent 工具往返与恢复、无 SDK 的模型插件发现，以及 MCP 客户端、世界桥、工具桥和假模型默认 bot 的本机往返；产品 extra 不要求 CLI/API。未调用真实模型或外部 MCP 服务。
- 最终 `uv run --locked aurora check` 全部通过：1042 项 Python、97 项 TypeScript、5 项终端测试，格式、lint、Python/TypeScript 类型检查通过，仅保留既有 Pydantic ReadOnly 提示。默认 bot 与 live_workshop 的自定义模型模板同步迁到 model 子目录，模型切换与重启恢复通过；变更文档的本地链接和 `git diff --check` 通过。验证基于包含并发测试归置工作的当前工作区，未混合提交其他任务改动。

## 2026-11-03

### 将 Aurora-QQ 通知适配为 bot 的 MCP 世界事件

- 在相邻 `Aurora-QQ` 项目以 MCP `2026-07-28` 的 `subscriptions/listen` 和 `notifications/resources/updated` 替换旧 `org.aurorabot/world-events` 通知扩展。公开事件资源为 `qq://events/inbox`，读取返回严格的 `message_id/payload` 信封；保留原事件摘要身份、发生时间、会话范围和完整 OneBot 数据，直接匹配 bot 现有 `mode = "event"` 契约。旧扩展不保留兼容转发，旧宿主须改用资源订阅；30 个远端工具名及 tool-contract 元数据保持不变。
- 每个 stdio 服务进程仅接纳一个事件消费者，拒绝未知资源和重复订阅。订阅注册后才启动 NapCat 监听，确认响应不等待联网；工具发现不启动来源。上一条被读取后才通知下一条，避免 SDK 合并同 URI 通知导致连续事件被覆盖；最多保留一条待取 JSON，单条上限 512 KiB。手动停止后恢复保留已通知未读取事件，订阅取消、连接关闭及准备失败均收束事件任务。
- 读取确认仅代表客户端取走，不代表 world 提交或模型处理；断线、取消订阅和进程重启不自动重放，world 对实际收到的稳定消息身份持久去重。继续保留自身消息和无意义事件过滤。QQ 使用 SDK 2.3 的预期工具/资源错误类型，明确呈现未订阅、需要确认、禁用原始动作和 NapCat 拒绝等诊断，不通过放宽原有断言掩盖失败。
- 更新本地 data：显式启用 `aurora_adapters.mcp.world`，QQ 连接固定新版并要求 tools/resources 能力，新增 `qq/events` 世界来源；恢复 `qq_start_events`、`qq_stop_events`，目前开放 29 个工具，raw action 仍关闭。保留模型、时间、南京天气及 Token 环境引用，更新系统提示；cadence 自动唤醒仍关闭。四份原配置分别备份为 `.before-mcp-events`，本任务未改写业务快照，data 与备份仍不进入 Git。
- 用户确认后同步 QQ README 和配置模板，提供当前 host/MCP/world 接入示例、迁移边界、可选 cadence 配置和跨项目验收命令。源码及测试移除旧事件扩展引用。QQ 的 41 项测试、Ruff 格式/lint 与 Pyright 通过；其独立环境明确跳过需要 bot 包的集成测试，该项随后在 bot 环境单独通过。
- 跨项目验收使用真实 QQ stdio 服务和模拟 OneBot：12 条连续消息有序归档、重复消息去重，两次宿主启动后记录身份稳定，共享连接仍能调用工具，关闭后无自有任务残留。QQ wheel 构建及干净环境安装后的工具目录、事件资源和本地状态调用通过；实际 data 的 6 份声明配置、来源配置及原快照内存恢复校验通过。未连接真实 NapCat、调用真实模型或执行 QQ 发送/管理动作。
- bot 完整 `uv run --locked aurora check` 通过：1036 项 Python、97 项 TS、5 项终端测试，格式、lint、Python/TS 类型检查通过，仅有既有 Pydantic ReadOnly 提示。QQ README 的 4 段 TOML、2 段 JSON 和格式校验通过；QQ 收尾提交为 `27a9468`。

### 核对本地工具可见性并清空试用对话

- 针对模型回复“没有工具”，使用实际 data 配置和运行期环境连接 QQ MCP；确认 27 个工具完成发现、接入 main 工具插槽，并进入模型请求及 LiteLLM 的供应商请求结构。当前模型适配器声明支持工具；未发现本地工具装配缺失，尚未确定此前模型回复的具体原因，未调用真实模型或 QQ 业务工具。
- 按用户要求，在确认本机 API 未监听后备份原快照为 `data/framework/ctx.before-context-reset-20261103-230829.json`，清除 main 的 30 条历史消息及 inbox/progress、run、react_work，共移除 5 个状态项。保留 3 个 world 状态项，配置文件和 world 数据库哈希保持一致。
- 使用清空后的实际快照完成内存恢复和请求构造验收：仅有系统提示，无历史对话，27 个工具仍完整传入请求；假模型可接收请求，诊断不写回快照，模型与 MCP 资源正常关闭。配置与备份由 git 忽略，不进入提交；从仓库根目录重启 `uv run --locked --env-file .env python scripts/serve_bot.py --world --edit-config` 后可继续试用。

### 完善本地 data 的 MCP 工具配置

- 保留已有插件、模型绑定、运行期凭证、时间与南京天气配置，新增 MCP 客户端、工具桥和产品装配插件，将 host 切换为 `org.aurora.adapters:assemblies/mcp/default_bot`。MCP 目录在准备阶段自动接入 `main` 的工具插槽；bot 的 `tools = []` 仅表示没有额外显式工具，不关闭自动接入。
- 新增本地 `org.aurora.adapters/config.toml`，通过 stdio 挂接 `../Aurora-QQ`；相对 cwd 基于 AuroraBot-next 工作区，执行 `uv run --frozen --no-sync aurora-qq-mcp --config config.toml`，复用 QQ 已安装的独立环境。使用 auto 协商与 tools 能力检查，startup/catalog/execution/shutdown 分别为 30/30/45/10 秒；bot 外层工具预算为 60 秒，最多 16 轮，保留流式输出。
- 按现有 QQ 配置开放 27 个工具，排除不兼容的 `qq_start_events`、`qq_stop_events` 和服务端已禁用的 `qq_call_action`；其他工具沿用 v2 自动名称和服务端确认参数。补充中文系统提示，要求按实际工具回执报告结果，超时或结果未知时不自动重试有副作用的动作。
- QQ 使用 `org.aurorabot/world-events` 自定义通知，当前 world 桥使用 MCP 资源订阅，两者不能仅靠配置接通。因此未配置虚假的 QQ 世界来源或启用 cadence 自动唤醒；现有时间、天气观察继续保留。接入消息监听和自动回复需要后续协议适配。
- 用户确认 NapCat 已启用 Token，并将在启动环境提供 `AURORA_QQ_TOKEN`；MCP environment 仅保存 `{env:AURORA_QQ_TOKEN}` 引用。宿主启动前须提供该变量，缺失时明确拒绝准备连接。保留 `.env` 原内容，从项目根目录运行 `uv run --locked --env-file .env python scripts/serve_bot.py --world --edit-config`，正常重启后配置生效。
- 验收通过：6 份已声明配置的结构和关联校验、现有 8 条快照状态的内存恢复；正式 CLI 在隔离目录中使用假模型和真实 QQ stdio 服务，发现并向模型提供 27 个工具，通过 agent 插槽执行 `qq_get_status(probe=false)`，确认本地状态返回、模型与 MCP 任务收尾。92 项相关 MCP 配置、预设、装配及 CLI/API 回归通过。Token 引用以仅存在于验收进程的占位值验证，未验证真实 NapCat 鉴权，未调用真实模型、天气、QQ 发送或管理动作。
- 原 host 和 bot 配置分别备份为同目录的 `.before-mcp-tools` 文件；原模型、world 配置和业务快照保持原样。实际 data 配置与备份仍由 git 忽略，不进入提交；README.md、AGENTS.md 和 Aurora-QQ 项目未修改。

### 归档 build 历史产物

- 将 build 下的 166 项旧产物及清点文件移动到仓库外 `E:/Aurora/AuroraBot-next-archives/build-20261103-225238`，保留原目录名，附带 `archive-inventory.json` 与 `move-manifest.csv` 便于查找和后续删除。内容包括历史 wheel、隔离安装环境、验收数据、临时脚本和日志；没有删除文件。
- build 仅保留 wheels 目录中的 12 个最新分发包及其忽略文件。移动前确认源/目标绝对路径边界及没有进程引用 build，移动后核对 348725 个归档文件的数量和逻辑大小（约 7.04 GiB），保留文件的 SHA-256 一致。data、开发用 .venv 和源码不受影响；本次只做文件整理，不运行无关测试。

### 配置本地 data 的 world 试用环境

- 保留现有 host 插件、模型绑定和运行期凭证，将 world 的旧来源保留参数移至统一 `[view]`：近期 3600 秒、32000 字符预算、8000 字符单条预览、30 秒刷新；时间保留 1 条，南京天气保留一小时内最多 4 条。原配置备份为 `data/config/org.aurora.world/config.toml.before-world-view`。
- 经用户明确确认，对 `data` 执行旧日志迁移；2 条记录的原文、记录身份和序号保留，其他 ctx 状态原样，原快照备份为 `data/framework/ctx.before-world-database.json`。迁移前在副本验证，迁移后完成实际数据库及快照核对。
- 全部已启用插件的配置加载、关联校验和凭证可解析性检查通过；未启动真实模型或天气请求。继续使用每 60 秒的时间采样与每 900 秒的南京天气采样，未启用 cadence 自动转发。实际本地配置和数据由 git 忽略，不进入提交。

### 整理以 ctx 为中心的主动 bot 上下文设计

- 新增独立讨论稿 [以 ctx 为中心的主动 bot 上下文设计](archive/2026-11-09/aurora_bot_ctx_prompt_design.md)：稳定的世界规则和人格进入 system，本次唤起原因与业务 ctx 视图通过 user 提供，运行中保留 assistant/tool 关系；关注与行动选择交给 bot，框架维护来源、身份和执行事实。
- 区分完整业务记录、有限模型视图、持久工作笔记与实际行动证据；明确引导接纳不等于事项完成，模型笔记不替代工具回执，当前快照不逐轮追加到永久历史。
- 以现有 world 事件数据库、近期视图和独立环境状态为基线，列出插件分工、已有能力、最小验证场景和待讨论问题。仅整理设计，不新增运行实现、公共 ID、插件、配置或快照格式，不改变 M4.W3 契约或将 W4 标记完成。
- 验证通过：两份文档的 Prettier/Ruff 格式检查、新文档及本条记录的 11 个本地链接、代码围栏闭合与 git diff 空白检查。纯文档变更未运行业务测试；README.md、AGENTS.md 和用户数据未修改。

### 统一 world 事件归档与 ctx 有界呈现

- 来源插件只通过绑定身份的 emit 提交消息；移除 SourceInstance.retention、RecordRetention 及来源内裁剪。WorldRecords 由宿主持有并显式注入来源、MCP 桥和 cadence，构造不打开资源，配置完成后由记录组件创建数据库和呈现刷新任务。
- 普通事件逐条事务保存于 `namespaces/ns-org.aurora.world/events.sqlite3`，去重覆盖归档历史；get/get_by_id/read 返回完整原文，消费游标不受 ctx 窗口裁剪影响。数据库提交后才更新呈现，写库失败不消费身份或序号，呈现失败可用同一消息重试；周期刷新失败记录固定诊断并在下一周期重建，不重放事件。
- `state/records` 更新为 v3 近期文本视图：默认最近 3600 秒、32000 字符预算，按完整条目边界浮动；单条超过 8000 字符时保留标记、预览和记录 ID。预算包括条目元数据，按宿主接收时间裁剪，默认每 30 秒和每次接纳时刷新，空闲也会过期。有限视图随快照保存，启动以数据库重建。
- 新增 `org.aurora.world:state/environment`，按 source_id 保存时间最新 1 条、天气一小时内最多 4 条；不进入普通事件数据库或消费序列。来源只保留采样参数，呈现统一配置于 world TOML 的 `[view]`。需要归档和转交的环境来源可显式选择 `presentation = "events"`；cadence 选择普通环境观察时明确拒绝启动。新增记录服务 prepare/start/stop/clean 四个公共 handler ID，插件入口和包依赖保持不变。
- 衔接已提交的 M4.W3：默认装配按 bot → world 记录服务 → cadence → world 来源启动，cadence 读取同一数据库服务，保留原样转交、未知投递暂停和直接交流并存语义。覆盖视图已清空仍转交全部积压、视图裁剪后来源去重、环境归档显式选择及重复启动保护。
- v1/v2 ctx 日志启动时要求显式迁移，不覆盖用户配置或自动丢弃状态。停机后执行 `uv run --locked python -m aurora_world.migrate --root <数据目录>`，备份原快照到 `framework/ctx.before-world-database.json`，保留已有日志、记录、序号和裁剪锚点。迁移失败可重试；旧记录接收时间采用导入时刻，原有环境历史原样归档。旧 retain_count/retain_seconds 须手动移至 `[view]` 的 time_count/weather_count/weather_seconds；后续备份与恢复同时包含数据库和 ctx 快照。
- 同步架构、公共 ID、计划、五条示例体系中的启动指南及进程夹具；serve_bot 的 world 状态列表加入环境地址。未修改 README.md、AGENTS.md、用户审查报告或实际用户数据；未调用真实模型或外部业务服务。
- 12 个最终 wheel 构建成功；使用显式本地 wheel 约束完成隔离安装，验证 world/core 独立接收与重启去重、control 无 agent/模型、agent 无 bot/CLI/API，以及 bot 无 CLI/API 的假模型 cadence 转交和恢复。最终 wheel 环境的 105 项 world 回归通过，包含配置资源、环境采样、归档与裁剪、错误重试、迁移和生命周期；50 个本地文档链接、13 个锚点和 9 段 TOML 示例通过。
- 最终 `uv run --locked aurora check` 全部通过：1036 项 Python、97 项 TS、5 项原生终端测试，格式、lint 及 Python/TS 类型检查通过；仅有已有的 Pydantic ReadOnly 提示。

### M4.W3：接入最小原样转发 cadence

- 新增 bot 包内可选 `aurora_bot.cadence` 插件，显式依赖默认装配、world 与 config。TOML 的 source_ids 精确选择来源，默认空列表不转发；仅补齐缺失的 `org.aurora.bot/cadence.toml`，配置非持久化。新增配置、消费状态与 prepare/start/stop 共 6 个公共 ID，不替换旧定义或插件，不改写已有用户配置和快照。
- DefaultAssembly 装配单一转发所有者，启动依赖为 bot → cadence → world，先订阅再开放来源；后台只按位置扫描并逐条原样提交到既有 AgentRuntime，不另建激活调度。运行中可继续接纳，取消期间的明确写入前拒绝等待原运行收尾；停止时取消订阅并收束转发，bot 运行、工具与模型由原所有者关闭，最后宿主落盘。部分启动失败与组件连接失败均清理所属资源。
- 按 bot instance_id 保存来源选择绑定、完整消费位置、pending 原消息及 receipts，引导关联包括 guidance_id、sequence、run_id。先记录转交意图，同步提交后将回执与位置一次保存。提交或回执保存结果不确定、恢复出 pending、日志身份/裁剪缺口及来源选择变化均明确暂停；重启不清除诊断、不重放未知投递，暂停不阻断直接交流。首次消费读取当前保留窗口，未选来源仅推进扫描位置。
- 消费状态随宿主异步快照保存，不承诺崩溃下的恰好一次执行；world 去重仍限保留窗口，裁剪后的同身份重投作为新记录。完整转交关联暂不自动裁剪，首版不提供自动核对或重置命令。含新消费状态的快照恢复须显式启用 cadence，缺失定义不会被静默忽略。
- 新增 28 项状态及默认装配验收，覆盖原始 JSON、同一运行接纳、去重、恢复不重放、转交前后与回执写入故障、pending 恢复、日志换代/裁剪缺口、来源变更、取消收尾、空选择、立即关闭、来源启动失败和连接回收。相关运行、环境及包边界共 43 项回归通过。12 个 wheel 构建成功；干净环境分别验证 control 无 agent/模型、agent 无 bot/CLI/API，以及 bot 无 CLI/API 时的插件发现、模板、假模型转发、恢复与关闭。
- `scripts/serve_bot.py --cadence` 显式开放消费状态及暂停诊断；同步架构、公共 ID、推进计划和启动指南。W3 已交付，W4 的 live_workshop 正式替换、完整双路径矩阵与安装组合继续作为下一阶段；保留五条示例路径。本轮未调用真实模型或外部业务服务。
- 最终 `uv run --locked aurora check` 全部通过：1027 项 Python、97 项 TS、5 项原生终端测试，格式、lint 和 Python/TS 类型检查通过；仅有已有的 Pydantic ReadOnly 提示。51 个本地文档链接/锚点、8 段 TOML 示例及差异空白检查通过。README.md、AGENTS.md、用户审查报告和已有用户数据未修改。

### M4.B3：完成共享客户端与跨传输生命周期验收

- 新增正式 MCP 产品装配的 30 项本机集成验收，覆盖 HTTP、stdio、混合连接三种布局。工具与 MCP 世界来源共享同一客户端，普通时间来源同时由唯一 world 所有者管理；验证来源停止不打断在途工具、工具超时、运行取消、宿主退出、进程断线，以及关闭等待被取消或超时后再次等待。
- 明确断言来源、工具、模型、客户端和最终快照的收尾顺序；所有自有任务结束，stdio 进程被回收，外部 HTTP 服务不由客户端结束。混合布局中本地服务退出后，另一远程来源与连接仍接纳；发送后的断线保留 mcp_result_unknown，超时为 mcp_timeout，远端调用日志均只有一次，不自动重发。
- 目录选择失败、模型工厂失败和旧协议来源启动失败均回收已准备的共享资源并完成最终落盘。取消或正常关闭后重建宿主可恢复世界记录，但不启动模型、不重放工具动作；配置文件原样保留，客户端/配置状态不进入业务快照。测试服务与进程闸门集中在 tests/fixtures/mcp_shared_server.py，未新增产品示例或第二套执行机制。
- 最终完整 `pnpm exec uv run --locked aurora check` 通过：999 项 Python、97 项 TS、5 项原生终端测试，格式、lint、Python/TS 类型检查通过。Windows 工作区和最终 wheel 的独立产品环境分别通过 30 项共享回归；混合布局强化为本地故障后，相关 10 项工作区回归及安装环境故障验证通过。代码与 B5.4 的 12 个最终 wheel 一致，本批只新增测试并同步文档。
- Fedora Linux/Python 3.12.14 的干净 wheel 环境通过 30 项共享回归及 6 项正式 CLI/API 验收；补验本地服务优先的混合来源停止和故障隔离，两项通过。各环境使用最终本地 wheel 的显式约束，未以工作区导入替代安装验收。107 个文档本地链接/锚点、11 段 TOML 示例和差异检查通过。
- B5 通用 MCP 接入与 B3 共享关闭闭环完成；下一阶段为 W3/W4 cadence 与 live_workshop 正式集成。业务事件可靠投递、外部真实 MCP 兼容性及真实模型验收仍单独安排，本轮未调用外部服务。README.md、AGENTS.md、用户审查报告及用户数据保持原状。

### M4.B5.4：接入默认 bot 产品装配与初始化预设

- 新增可选 `aurora_adapters.mcp.bot` 插件、`aurora-adapters[mcp-bot]` extra 和 `org.aurora.adapters:assemblies/mcp/default_bot`。共享一个 MCPClients，目录发现先于模型和工具准备；DefaultAssembly 通过 additional_tools 增量合并工具，保留已显式选择的 MCP 实例身份，新增实例使用工具 ID 的 local_path，不改写 TOML、ctx 配置或历史快照。
- `python -m aurora_adapters.mcp.preset <data-dir> [--world] [--api]` 生成显式插件选择和缺失模板。已有 host.toml 选择不同时保留原文件，输出规范化差异与 host.mcp.toml 候选并返回 2；候选冲突报错，不创建模型、连接或子进程。宿主 schema 移入 aurora_config.host，CLI 与预设复用同一解析契约，adapters 不依赖 CLI/API。
- 正式 CLI/API 宿主工厂增加必需 workspace_root 关键字，来自 --root，独立于数据目录；同步默认装配、live_workshop、测试消费者与指南，无签名猜测或兼容转发。第三方装配工厂须同步接收该参数。公开 ID/插件为新增，无旧 ID 替换；自动实例身份只作用于未显式选择的工具。
- DefaultAssembly 提供单一 world_component_factory 入口；world 按实例注入 source_factories，MCP 来源复用共享连接，普通来源沿用原工厂，不再向公共 SourceSpec 写入宿主 ctx/clients。两个 ctx 复用同一来源定义的独立接纳和关闭验证通过。
- 新增 14 项验收：正式 CLI 的 HTTP/stdio 与显式选择保留、正式 API 双传输往返、四种预设、原文件/候选保护、非法宿主及依赖显式启用、来源定义复用。完整检查中 969 项 Python、97 项 TS、5 项终端测试通过；新增测试的类型标注修正后单独重跑 pyright 为零错误，格式/lint 与 TS 类型检查通过。12 个 wheel 构建完成，隔离安装验证基础、客户端、世界、工具、agent 与产品 extra；产品 extra 无 CLI/API 时可生成预设，另装正式宿主后验收双传输 CLI/API。82 个本地链接/锚点与 9 段 TOML 示例通过。仅使用假模型和本机测试服务。
- B5.4 产品入口已完成，扩展 B3 共享关闭矩阵继续推进；未修改 README.md、AGENTS.md、用户审查报告或已有用户数据。

### M4.B5.4：完成工具自动选择与内部目录整合

- MCPTools 默认发现 tools 能力服务的完整目录，支持精确 include/exclude、显式别名及 v2 稳定自动名称；原始服务名和远端工具名参与 SHA-256 摘要，ASCII slug 仅用于阅读。Unicode、截断和同名服务工具不依赖返回顺序；自动名称、显式别名、本地工具模型名称和公共 ID 统一检查冲突，不添加临时编号或登记部分目录。
- 无 tools 能力的服务在默认通配下保留供其他消费者使用，显式选择要求能力；缺失的 include/exclude/alias 目标明确失败。显式 include=[] 仍不发现、不暴露工具，迁移后的旧别名和公共 ID 保持。工具目录使用连接所有者在 config 阶段保存的声明副本，不重复读取运行期 ctx；新增 MCPTools.tool_ids 供后续产品装配获取已登记身份。
- 按职责拆分 catalog.py（分页、选择、名称）、tool_execution.py（单次执行和结果）、tools.py（工厂与原子登记），移除重复实现；执行仍使用同一个 SDK session、agent 插槽和结果契约。新增名称向量、多服务/目录顺序、显式过滤、冲突与配置快照测试，HTTP/stdio 夹具增加 --automatic，验证自动名称与旧别名两条路径。
- 完整检查通过 955 项 Python、97 项 TS、5 项原生终端测试，格式、lint 与 Python/TS 类型检查通过；24 条真实本机工具/假模型 bot 路径通过。adapters wheel 构建后在无 world/bot/CLI/API 的工具 extra 环境完成自动命名 HTTP 与 stdio 往返；57 个本地链接/锚点、9 段 TOML 示例和差异检查通过。没有调用外部 MCP 或真实模型。
- 此批完成 B5.4 的工具目录部分；CLI/API 可选组合装配、初始化预设及扩展 B3 共享关闭仍待完成。同步模板、设计、公共 ID、计划和启动指南；未修改 README.md、AGENTS.md、用户配置或业务快照。

### M4.B5.3：接入有界 stdio 传输与自有进程回收

- local 与 remote 通过 transports 共用同一个 SDK Client、协议协商、连接所有者、工具桥和执行契约；支持 legacy、auto、固定新版及旧服务回退。MCPClients 新增显式 workspace_root，prepare 才解析 cwd 和 environment；相对目录基于工作区根，缺失目录或凭证在启动前拒绝。命令按参数数组执行，不拼接 shell；仅继承 SDK 基础环境，原始 stderr 丢弃，不修改宿主环境。
- 新增 stdio.py，集中路径解析、有界管道与进程回收，复用 SDK 的参数模型、消息校验器、基础环境和公开平台进程工具。SDK 自带 stdio_client 缺少未结束消息限额且 POSIX 正常退出不回收后代，因此适配层补充 4 MiB 单帧上限、零容量接收背压、EOF/进程退出观察及固定诊断；未复制协议会话、工具机制或引入传输注册框架。anyio 作为 mcp extra 的直接依赖，基础 adapters 仍只依赖 core。
- 关闭先结束 stdin、限时等待，再回收所属 Windows Job/POSIX 进程组及管道，包含根进程已退出但后代持有管道的情形。生成进程与回收任务受独立取消保护，修复启动预算到期再次打断 finally 的竞态；关闭等待取消/超时后可以再次等待，不重复取消回收，不根据持久 PID 或进程名终止其他资源。进程或管道故障不自动重启、重协商或重发工具请求。
- 真实进程测试在最终 wheel 的 Windows 环境通过 24 项，WSL Fedora Linux 通过 23 项并跳过 Windows 专属 CMD/PATHEXT 用例。覆盖三种策略、工作区、参数、凭证隔离、stdout 污染/超限/残帧、stderr 洪泛、启动取消、父子退出、关闭重试、清理失败优先报告及发送后退出零重放；Windows 另验证扩展名发现和含空格脚本路径。工具桥夹具增加 --transport local，HTTP/stdio × 三种策略 × 独立工具宿主/假模型默认 bot 的 12 条路径通过；真实供应商与外部业务 MCP 均未调用。
- 完整检查通过 928 项 Python、97 项 TS、5 项原生终端测试；随后补充的 1 项 Windows 命令发现测试及相关类型、格式检查通过。12 个 wheel 构建完成，五个干净 Windows 环境验证基础包、客户端、通知桥、工具桥和 agent 依赖边界；独立 Linux 客户端环境不含 agent/bot/world。安装后的模板、迁移、HTTP/stdio 工具往返、world 恢复及假模型示例通过。57 个文档本地链接/锚点、9 段 TOML 示例和差异检查通过。
- 同步设计、架构、公共 ID、模板、计划及启动指南；公共 ID、已有工具身份和业务快照不变，用户配置不覆盖。自动工具名称、可选产品装配及扩展共享关闭矩阵仍待 B5.4/B3，未将注册插件等同于启动服务；README.md、AGENTS.md 与用户审查报告未修改。

### 复核设计一致性审查报告

- 更新[审查报告](archive/2026-11-09/review-report_2026-11-03.md)，保留 F1–F16 编号，区分已确认缺陷、条件性风险、维护建议和规划能力；修正双调度、MCP 原子登记与作用域、实例切换、持久化频率、配置启用和 Node 运行入口等判断，重排整改优先级。
- 分开保留原基线验证与同日复核记录：192 项 Python 定向测试、58 项前端测试、2 项 TUI e2e 及生成契约检查通过；最小场景确认世界记录可删除、配置失败后编辑入口仍绑定、405 非 JSON 和空来源异常覆盖。上述验证不构成对并行 MCP 未提交改动的完整验收。
- 本次仅修改报告与本条记录，未修改实现或用户配置；文档本地链接、锚点和差异检查通过，保留其他任务已有改动。

### M4.B5.2：接入 HTTP 协议协商并拆分 MCP 内部职责

- remote 连接支持 legacy、auto 和固定 2026-07-28。legacy/auto 复用 SDK 2.3.0 公共 Client 入口，固定新版继续显式 discover、确认能力和 adopt；只接纳已验收的 2025-11-25/2026-07-28。RPC 错误不作为版本证据，auto 的回退和版本纠正重探测共用一个 startup 预算，不额外调用私有探测函数或叠加重试循环。
- HTTP 401/403、5xx、重定向、损坏 JSON 与非法握手响应明确失败，保留固定错误码，不把鉴权失败转换为成功回退。合法 RPC 错误和 HTTP 404 沿 SDK 策略尝试旧握手；工具调用仍只经过单次 session 请求，不因协议错误重协商或重发。HTTP 边界阻止 Last-Event-ID 恢复 GET 及第二次后台 GET，SDK 内部有限退避不会发出重连网络请求，关闭仍等待自有任务收束。
- 内部分为 configuration（声明）、credentials（引用校验/展开）、transports（资源创建及 HTTP 边界）、negotiation（协商校验/安全摘要）、errors（固定错误码）、clients（连接所有权/生命周期），工具与世界来源继续复用同一个客户端所有者。迁移器复用 URL 和名称约束，移除重复校验；不引入通用传输注册中心、第二套调度器或兼容转发模块。
- CLIENT_STATUS 新增 type、configured_protocol、negotiated_protocol、negotiation_attempts，保留 phase 作为阶段字段；negotiated_protocol 替代旧 protocol_version，无同义别名。摘要最多四项，只存方法、HTTP 状态和数值 RPC 错误码，不记录报文、凭证或异常原文。能力拒绝时仍可观察已确认版本，accepting 为 false。该状态非持久，无业务快照迁移。旧版资源能力不冒充新版订阅能力，world 来源在借用内明确报 unsupported_subscription_protocol，客户端仍可供工具使用。
- 新增真实 SDK 协商矩阵，覆盖三种策略、-32601/-32603/-32022、版本纠正、畸形响应、鉴权及 HTTP 错误、短执行预算与握手隔离、同一总预算、外部取消、零工具重发和禁止网络重连。工具进程夹具扩展 --protocol，三种策略均通过无 bot 宿主及假模型 DefaultAssembly 的真实本机 HTTP 往返；既有来源恢复与独立安装边界继续验证。未调用真实模型或外部业务 MCP 服务。
- 完整检查通过 899 项 Python、97 项 TS、5 项原生终端测试，格式、lint、Python/TS 类型检查通过。12 个 wheel 构建完成，最终 adapters wheel 在五个干净环境验证基础包、客户端、通知桥、工具桥和 agent 的依赖边界；安装后的三种协议工具往返、客户端往返、world 恢复、模板和迁移入口通过。57 个文档本地链接/锚点、8 段 TOML 示例及差异检查通过。
- stdio、自动工具命名、可选产品装配及扩展共享关闭矩阵仍待 B5.3/B5.4/B3。同步架构、公共 ID、计划、模板和启动指南；下一步接入 stdio，并在后续产品装配中处理审查报告指出的定义/宿主资源绑定边界。用户的审查报告、配置与数据保持原状。

### M4.B5.1：声明 MCP v2 服务配置并提供显式迁移

- MCP 配置改为 `schema_version = 2` 和按服务名组织的 `servers`；服务名保持 connection_id 身份。声明 local/remote、enabled、独立 protocol、headers/environment 引用、服务内工具选择及根级/服务级四类超时；配置校验不创建资源、不解析环境或检查本地目录。模板默认空 servers，只复制缺失文件。旧 connections/tools 及混合布局明确提示迁移，不提供运行期双解析或兼容别名。
- 新增 `python -m aurora_adapters.mcp.migrate <旧文件> --output <新候选>`，只创建不存在的候选并打印忽略注释和排版的规范化差异。保留连接身份、固定新版策略、原工具别名/公共 ID、所需能力与请求超时；旧连接没有工具时迁移为 include=[]，不扩大暴露范围。同一远端工具的多别名无法无损表达时明确停止，不静默丢弃。保留 bot 显式工具选择、各实例身份和 world 引用，不合并消费者或改写快照；提示核对 agent 外层 tool_timeout 和新增的 shutdown=10 秒预算。
- 客户端与工具桥同步消费 v2。禁用服务不创建资源、解析凭证或登记工具；headers 在 prepare 创建连接时展开环境引用，拒绝缺失/空凭证、控制字符、重复及协议控制头，Authorization 等明确凭证字段拒绝纯字面量。解析失败只暴露固定错误码、服务名和字段位置；MCPClients 注入参数改为 resolve_env，非持久状态增加 error_location。local 环境声明支持引用与非敏感字面量，工作区路径解析及子进程创建随 B5.3 实现。
- startup/catalog/execution 分别约束握手、完整分页发现与单次工具调用，服务字段覆盖根默认；SDK 请求与 HTTP 空闲读取上限取三者最大值，避免短执行超时截断握手或目录。shutdown 限制每服务每次 stop/clean 等待，超时后仍保留清理任务供再次等待，不重复取消 finally。工具沿用参数校验、执行钩子、失败观察和零自动重发；include/exclude 使用精确名称，aliases 保留稳定模型名称。
- B5.1 的可运行路径仍为 remote + 显式 protocol=2026-07-28、显式工具 include 与 aliases。新声明默认 legacy，启用尚未实现的 legacy/auto/local 时在创建任何连接前报 unsupported_protocol/unsupported_transport；默认通配或缺少别名的自动工具选择报 unsupported_tool_selection。自动命名与产品装配不冒充已交付；后续顺序为 B5.2 HTTP 协商、B5.3 stdio、B5.4 产品接线、扩展后的 B3。
- 新增 70 项验证，覆盖声明分支与控制字符、惰性凭证、未实现模式预检、禁用项、迁移保留/冲突/不覆盖、独立操作预算与关闭等待重试；原工具、假模型默认装配和世界通知恢复仍通过。完整检查最终通过 861 项 Python、97 项 TS、5 项原生终端测试，格式、lint、Python/TS 类型检查通过；普通回归仅使用假模型、模拟 HTTP 与本机测试进程，没有调用外部 MCP 服务或真实模型。
- 12 个 wheel 构建完成，最终 adapters wheel 在 `build/b5-1-{base,client,world,tools,agent}` 的五个干净环境验证基础 adapters/control 无 agent/模型、客户端无 world/agent/bot、通知桥无 agent/bot、工具桥无 world/bot、agent 无 adapters/world/bot/CLI/API。安装后的迁移命令、包内模板、本机客户端/工具往返和 world 跨进程恢复均通过。MCP extra 新增 tomli-w 以发布迁移命令，基础包依赖不变。
- 同步[设计与实现边界](archive/2026-11-09/mcp_unified_access_design.md)、架构、公共 ID、计划和[启动指南](archive/2026-11-09/START.md)；57 个现行文档本地链接/锚点、8 段 TOML 示例和差异检查通过。无旧公共 ID/插件替换，无业务快照迁移；用户配置与数据未修改，README.md、AGENTS.md 保持原状。

### 编写 MCP 通用接入需求与设计草案

- 新增 [MCP 通用接入需求与设计草案](archive/2026-11-09/mcp_unified_access_design.md)，明确由 Aurora 自身支持 HTTP/stdio，复用一套连接所有权和工具执行契约，不要求第三方服务改传输。区分已交付 B1/B2/B4、样本观察和未实现设计。
- 提出按服务名组织的 v2 TOML、local/remote、独立 protocol、运行期 headers/environment 引用、自动工具命名与过滤、可选产品装配及显式迁移。新配置默认 legacy，旧配置迁移显式保留固定新版；auto 的回退边界按锁定 SDK 行为说明，不把 RPC 错误当作版本证据，不重放工具动作。
- 明确 Windows/跨平台子进程回收、共享关闭、错误诊断、包依赖及 CLI/API 产品验收；业务事件扩展和带游标事件日志独立于传输与工具兼容。增加计划 B5 切片，B3 扩展到两种传输；同步主架构与计划入口，拟议公共 ID/插件尚不登记为已实现。
- 本轮仅修改文档，不修改实现、宿主配置、README.md 或 AGENTS.md；用户的 OpenCode 配置及参考文件不纳入本次提交。2 段 TOML 示例及合并结果解析通过，57 个本地链接/锚点、代码块格式与差异检查通过；修正主架构中公共 ID 第 6 节的既有失效锚点。不运行无关业务测试或真实 MCP/模型调用。

### M4.B2：将 MCP 工具接入 agent 执行契约

- 新增 `aurora_adapters.mcp.tools` 插件与 `aurora-adapters[mcp-tools]` extra，显式依赖 MCP 客户端和 agent 工具插件；仅工具桥引入 agent，不引入 world/bot/CLI/API，既有客户端与通知路径保持可独立安装。工作区开发依赖同时安装工具与通知 extra，产品入口仍不自动启用 MCP。
- MCP 配置增加默认空 tools 列表，显式映射 connection_id、remote_name 和本地 name。稳定模型名称直接对应 `org.aurora.adapters:tools/mcp/<name>`；连接不存在、重复本地名称、缺失远程工具、重复远端目录、无效参数 schema 或公共 ID 冲突均阻止启动。prepare 完整分页发现后原子登记，游标循环、分页上限和整体发现超时有界；配置或目录变化须重建宿主。
- 登记 `org.aurora.adapters:components/mcp/tool`、其 execute 端口和 `handlers/mcp/tools/prepare`。MCPTools 显式依赖 MCPClients；DefaultAssembly.components 增加 depends_on，使发现早于模型及工具检查。ToolSpec 工厂创建使用注入状态绑定的 ExecutionPlug；实例关闭封闭自身入口，共享客户端仍由独立所有者释放。
- agent 新增协议无关 ToolExecutionError，将安全错误码、消息和可选 JSON 内容转为失败观察。MCP 业务错误保留完整内容块和 structuredContent，协议错误仅保留数值码；请求超时、结果未知、无效结果、未提交和额外交互分别反馈。执行沿用参数校验与 before_call/after_call；外层超时/取消沿用 agent 契约。SDK session 单次调用绕过便捷接口的 HEADER_MISMATCH 重发与多轮输入续发，不自动重试工具动作，不在异常日志或诊断中写出原始远端错误文本。
- 新增假传输单元验证和本机真实 Streamable HTTP 进程夹具，覆盖分页/原子登记、内容块/结构化结果、业务与协议错误、参数/钩子拒绝、超时/取消及单次调用。无 world 的工具宿主和假模型 DefaultAssembly 路径均通过；针对 MCP、agent 工具、默认装配和包边界的 184 项回归通过。外部真实 MCP 服务兼容性按用户要求留待后续，未调用真实模型。
- 完整检查中 791 项 Python、97 项 TS、5 项原生终端测试通过；文档代码块的换行格式修正后复核格式、lint 和类型检查。12 个 wheel 构建完成，干净环境确认工具桥无 world/bot/CLI/API、通知桥无 agent/bot、客户端无 world/agent、基础 adapters/control 无 agent/模型、agent 无 bot/CLI/API/world/adapters。安装后的工具桥、通知桥与客户端均完成本机 HTTP 验收，包内模板可读取；文档 67 个本地链接与差异检查通过。
- 同步架构、公共 ID、推进计划和启动指南；无旧 ID/插件替换，无快照迁移，不改写已有配置文件。B2 已交付，下一步为 B3 工具与世界通知共同使用的关闭、取消和故障验收，再推进 cadence 与 live_workshop 集成。保留原五条产品示例路径，新验收入口为 tests/fixtures/mcp_tools_roundtrip.py。

## 2026-11-02

### M4.B4：将 MCP 资源通知接入独立世界来源

- 新增 `aurora_adapters.mcp.world` 插件与 `aurora-adapters[mcp-world]` extra，登记 `org.aurora.adapters:sources/mcp/resources` 和非持久 `org.aurora.adapters:state/mcp/world`。来源配置复用 world 的 sources.config，mcp_world_component 注入共享 MCPClients 并声明生命周期依赖，替代通用来源装配而不创建第二个 world 所有者。仅客户端的 mcp extra 仍不安装或导入 world，通知侧不引入 agent/bot/CLI/API。
- 通过 SDK 2.3.0 的 subscriptions/listen 订阅精确选择的 URI，start 等待全部选择得到确认；按实际消费要求检查 resources/tools 能力。notification 只存变化提示，resource 读取当前内容，两者使用本地观察身份；event 读取单个文本资源的严格 JSON `{message_id, payload}`，以连接、URI、上游消息身份组合去重，不把采样时间混入稳定事件。同身份同文返回原 world 记录，异文或身份缺失明确失败。来源固定 source_id，经既有 emit 接纳普通 JSON，SDK 类型不进入 world。
- 默认桥接缓冲为 64 项，溢出、未选 URI、超限内容、读取失败、订阅结束或断线均停止该来源并记录固定错误码，无自动重订阅、重连或历史补发。SDK 可能合并尚未消费的同 URI 通知，另有 1024 项不同事件积压上限；SDK 丢流统一报 subscription_lost。因此资源读取及 event 模式都不承诺还原全部中间变化。工具目录变化只标记 tools_dirty，不进入世界记录或热改工具集合。
- 订阅及借用由来源自有任务进入和退出，接收与读取任务一同收束；关闭等待取消或超时可再次等待，不重复取消 finally。来源失败或关闭不关闭共享客户端；真正的订阅清理失败单独报告，故障与宿主停止同时发生不误报清理失败。正常停止时尚未接纳的缓冲与在途观察以 discarded、固定诊断和日志报告，不伪报已保存，不在重启后重放。只有 emit 成功的记录交由宿主最终落盘。
- 新增 34 项验收：资源模式、身份与冲突、过滤确认、能力拒绝、断流/读取错误、缓冲溢出、启动取消、关闭等待重试和收尾竞态。真实本机 HTTP 服务通过两个独立进程验证记录恢复，记录数依次为 `[2, 3]`、`[4, 5]`，稳定事件保留原 record_id；来源失败后另一个来源和共享工具调用仍可用，断线不自动重新订阅。未调用真实模型或外部业务服务。
- 完整 `pnpm exec uv run --locked aurora check` 通过：758 项 Python、97 项 TS、5 项原生终端测试，格式、lint、类型检查通过。12 个 wheel 构建完成；最终 adapters wheel 在 `build/mcp-b4-isolated` 的无 bot/agent 环境完成来源、模板和本机通知验收，在 `build/mcp-b4-client` 验证仅客户端无需 world。另以干净环境确认基础 adapters/control 仅需 core、agent 无 bot/CLI/API/world/adapters。文档本地链接和差异检查通过。
- 同步架构、公共 ID、启动指南与推进顺序；无旧公共 ID/插件替换，无快照迁移，不修改现有用户配置或默认 bot 装配。B4 已交付，下一步 B2 工具桥及 B3 共享关闭验收，再接 cadence 与 live_workshop 集成。保留原五条产品示例路径，独立验收入口位于 tests/fixtures/mcp_world_roundtrip.py。

### M4.B1：MCP 声明配置与独立客户端所有权

- 新增可选 `aurora_adapters` 包及 `aurora_adapters.mcp` 插件，基础包仅依赖 core，`aurora-adapters[mcp]` extra 提供 config、官方 MCP SDK 2.3.0 和 httpx2。工作区开发依赖包含该 extra，统一产品安装和默认 bot 不自动启用 MCP；不引入 world/agent/bot 反向依赖。协议限定 2026-07-28，通过指定版本的 server/discover 检查能力，不回退旧握手，不自动续发多轮输入请求。
- 连接配置复用 ConfigSpec/ConfigSchema/ConfigTemplate，默认 connections 为空，模板只复制缺失文件；config 选择连接，prepare 才创建客户端。支持 HTTP(S) Streamable HTTP，本轮验收本机 HTTP。每项声明独立身份、URL、必需能力及连接/请求超时；凭证只通过 token_env 在运行期解析，URL 拒绝 userinfo、查询串和片段。未知必需能力在配置阶段拒绝，服务端额外能力不冒充本地支持，不将任意元数据写入状态。
- MCPClients 通过既有生命周期组件表达依赖，每个 SDK 上下文始终由同一后台任务进入、退出；消费者在适配层通过 connection 异步上下文借用。停止接纳后取消并等待剩余借用，依赖者清理完成后才释放客户端，最终由宿主落盘。关闭等待超时或取消可再次等待，不重复取消正在执行的 finally；真正的关闭异常明确失败，保留诊断而不伪报成功。SDK 在退出时上抛的既有请求传输故障与真正关闭异常分别处理，不自动重连或重放请求。
- 新增 `org.aurora.adapters:configs/mcp`、`state/mcp/config`、`state/mcp/clients` 和四个生命周期处理器。配置和观察状态均非持久；观察以 owner/connection_id 定位，只含阶段、固定错误码、接纳开关、协议和已知能力。ready 表示准备成功，不提供持续健康探测，断线在实际请求中诊断。无旧公共 ID 或插件替换，无快照迁移，不改写现有用户配置。
- 新增 41 项验收，覆盖配置拒绝、发现不联网、运行期凭证与错误脱敏、协议/能力拒绝、部分启动失败及取消、嵌套借用收束、关闭等待重试、关闭异常、模板保留和最终落盘顺序。真实进程夹具在禁用执行包、world、bot、CLI/API 导入的环境中完成本机 HTTP 能力发现、工具往返、资源读取和断线诊断；不调用真实模型或供应商服务。
- 最终完整 `pnpm exec uv run --locked aurora check` 通过：724 项 Python、97 项 TS、5 项原生终端测试，格式、lint、类型检查通过。12 个 wheel 构建完成；最终 adapters wheel 在 `build/mcp-b1-isolated` 验证安装包内模板、无 bot/agent/world 环境和本机往返。另以干净环境验证基础 adapters 仅需 core、control 无 agent/模型、agent 无 bot/CLI/API；agent 既有 LiteLLM 间接依赖包含 MCP，本轮未改变该依赖关系。文档本地链接与差异检查通过。
- 同步架构、公共 ID、推进计划和启动指南。B1 已交付，下一步为 B4 世界通知桥；通知流、world 转换、agent 工具桥和 stdio 尚未交付。保留原五条产品示例路径，独立安装验收复用 tests/fixtures/mcp_roundtrip.py。

### 限定环境记录保留窗口

- 按用户要求，时间默认只保留最新 1 条；天气按 observed_at 采样时间保留最近一小时内最多 4 条，满一小时即过期，包括不可用观察。时间和天气分别提供 retain_count，天气另提供 retain_seconds，默认 1、4、3600；与采样间隔独立配置。包内模板、启动指南及本机南京来源配置已同步，修改后重启生效。
- SourceInstance 可声明 RecordRetention，WorldSources 在全部来源 prepare 完成及每次接纳时统一应用已创建来源的保留规则，时间写入也会清理过期天气；无输入时不另设清理任务。策略仅作用于绑定来源，其他来源默认保留全部记录。追加与裁剪一次提交，失败不消耗序号、不改变旧窗口；实际数据与快照均裁剪，不只是界面隐藏。
- world 日志升级为 v2，增加 next_sequence、pruned_through 和 pruned_record_id，保留稀疏但单调递增的原序号和存活记录身份。v1 日志仍严格校验和读取，读取及无变化裁剪不改写，下次实际变更升级；旧程序不能读取 v2。仅保留窗口内的身份参与去重，已裁剪消息重投视为新输入，不另存无限增长的历史墓碑。没有更改公共 ID 或插件名。
- 读取位置早于最高裁剪序号时明确报 CursorError，即使指定来源过滤也不隐瞒全局历史缺口；恰好处于边界时凭保存的记录身份继续读取，允许已消费的上一条时间记录被替换后正常追读。省略 after 读取当前窗口，缺口由消费者明确处理；旧快照回退造成同序号不同身份时仍拒绝读取。
- 新增 17 项验收并同步原有环境恢复断言，覆盖来源隔离、原子通知、数量与小时边界、时间写入清理天气、空窗口序号、有限去重、裁剪位置、无效边界、失败回滚及 v1/v2 恢复。完整 `pnpm exec uv run --locked aurora check` 通过：683 项 Python、97 项 TS、5 项原生终端测试，格式、lint 和类型检查通过；未调用真实天气或模型。
- 11 个 wheel 构建完成，在 `build/world-retention-isolated` 干净环境验证环境来源、保留规则与跨进程恢复，环境无 bot/agent/control/模型/CLI/API/MCP。另将本机旧版世界状态复制到 `build/world-retention-existing-copy`，验证安装包能启动裁剪并保留原序号继续采样。当前本机后端仍在运行，在线快照由其继续持有，新规则在正常重启时应用。
- 同步架构、公共 ID 目录和 D11 保留边界；主线仍接续 MCP 客户端与世界通知桥，cadence 后续须按裁剪缺口规则处理消费位置。

### W2.3：将可配置的时间与天气周期接入默认装配

- 按用户要求将最小周期来源落实为时间和天气，新增 `aurora_world.environment` 插件及 `org.aurora.world:sources/environment/time`、`org.aurora.world:sources/environment/weather` 两个 SourceSpec，复用 W2.2 的身份绑定、配置和任务托管。基础 world 仍仅依赖 core，environment extra 引入 config/httpx；统一安装包包含该 extra，bot 增加 world/config 依赖，无 agent → world 的反向依赖。
- 时间使用宿主本地时区，默认每 60 秒采样；天气按配置的地点标签、经纬度、间隔与总请求超时读取 [Open-Meteo 当前天气](https://open-meteo.com/en/docs)，默认间隔 900 秒。两者可分别选择、调整或移除，重启生效；模板保留空列表默认值及真实配置示例，不覆盖用户文件。每次启动立即采样，以会话身份和计数区分观察，不补发离线周期，不把轮询采样冒充外部事件修订。
- 天气观察保留提供方、采样时间、有效时间、摄氏温度、WMO 天气代码与描述、km/h 风速。超时、HTTP/网络错误和无效响应形成不可用观察，不写异常原文、不伪造天气，不阻塞时间来源；当前请求不自动重试，下个周期重新采样。关闭先取消并等待在途请求，再释放 HTTP 客户端和落盘。
- DefaultAssembly 在 world 配置定义已显式登记时装配一个来源所有者，生命周期依赖 bot 组件；bot 就绪后开放来源，关闭时先收束来源，再关闭 bot/模型。没有启用 world 配置插件时保持原装配行为。`scripts/serve_bot.py --world` 显式开放世界记录及来源状态，复用 TUI 状态页与 F7 配置编辑。周期只进入 world，尚未接入 cadence，不自动调用模型。
- 根据用户选择，在本机 `data/config/host.toml` 加入 world、配置及环境插件，并创建 `data/config/org.aurora.world/config.toml`，初始地点为南京（32.0617, 118.7778），时间 60 秒、天气 900 秒、超时 10 秒；修改前的宿主配置备份位于 `build/w2-3-local-config-before/host.toml`。本机数据不进入提交。使用现有配置完成正式 DefaultAssembly 启动、本机 API 读取和正常关闭落盘；南京天气返回可用，未提交或激活模型运行。
- 新增 21 项自动验收，使用可控时钟、模拟传输及假模型，覆盖参数校验、时钟前后跳变不补发、天气错误与下一周期恢复、取消在途请求、默认装配的 HTTP/WS 观察、显式交流仍可执行、重启应用间隔变更与记录恢复。完整 `pnpm exec uv run --locked aurora check` 通过：666 项 Python、97 项 TS、5 项原生终端测试，格式、lint 和类型检查均通过。普通回归不访问真实天气或模型；真实天气采样另通过显式验收完成。
- 11 个 wheel 构建完成；环境来源在 `build/w2-3-isolated` 的干净环境安装，确认无 bot/agent/control/模型/CLI/API/MCP，模板和环境代码来自安装包，独立进程恢复后仅增加两条当前观察。另验证基础 core/world 安装、control 无 agent/模型、agent 无 bot/CLI/API/world，以及 bot wheel 的新增 world 依赖和插件发现。执行包验收使用本次构建 wheel 的精确路径，避免解析到缓存中的外部同名 aurora-agent 包。
- 同步架构、公共 ID、计划与启动指南。新增两个来源定义，不改变既有快照格式，不自动迁移用户配置；W2.3 已交付，下一步为 M4.B1/B4 的 MCP 客户端与世界通知桥。live_workshop 的示例调度仍待 W4 替换，TUI 全面优化仍在独立待办。

### W2.2：声明来源配置与后台任务托管

- 新增可选 `aurora_world.configuration` 插件和 `aurora-world[config]` 安装 extra；基础 world 仍仅依赖 core。配置复用 ConfigSpec/ConfigSchema/ConfigTemplate，宿主显式装配配置服务及 configured_sources_component。包内 config.toml 默认空来源列表，只生成缺失文件；config 阶段校验列表、唯一 source_id 和来源引用，prepare 才创建资源。未选择的来源不启动，来源专用参数由工厂校验，运行期配置覆盖不写回 TOML，也不热装配实例。
- SourceInstance 增加可选 run 主循环，由 WorldSources 创建、观察和收束；正常退出、异常及意外取消均封闭对应入口，其他来源继续接纳，不自动重启。后台异常使用固定错误代码，不将异常文本或配置写入观察状态和来源日志。自行创建的其他任务仍由实例 stop 负责，失败来源的剩余资源在宿主关闭时释放。
- 新增非持久的 `org.aurora.world:state/sources`，按 source_id 观察定义、阶段、接纳开关及错误；配置插件另登记 configs/sources、state/config 和 handlers/sources/configure。来源配置及运行状态不进入业务快照；原记录格式和插件名不变，无旧数据迁移，不自动改写用户配置。
- 关闭先封闭入口，调用实例 stop，再取消并等待托管主循环，之后释放资源和最终落盘。关闭失败或超时保留任务及资源供重试；不重复已经成功的 stop，不再次取消正在执行 finally 的主循环，部分启动失败和取消同样等待已启动任务收尾。
- 新增 19 项验收，覆盖结构与重复身份、显式插件依赖、TOML 选择与无效引用、配置文件保留、后台退出/失败隔离、异常消费、部分启动失败、关闭超时与失败重试。完整 `pnpm exec uv run --locked aurora check` 通过：645 项 Python、97 项 TS、5 项原生终端测试，格式、lint 和类型检查均通过；未调用真实模型或 MCP 服务。
- 11 个 wheel 构建完成；分别在 `build/w2-2-core-world` 和 `build/w2-2-config-world` 干净环境安装验证。前者只有 core/world，后者另含 config 及其 JSON Schema 依赖，均无 agent、bot、control、模型、CLI、API 或 MCP；确认模板来自安装包。既有 world_roundtrip 夹具增加 `--configured`，两条路径均经独立进程恢复原记录身份，序号从 `[1, 2]` 继续到 `[1, 2, 3]`，快照仅保留业务记录。
- 同步架构、公共 ID、计划及启动指南；W2.2 已交付，下一步 W2.3 模拟与最小周期来源，再接入 MCP 双路径。TUI 全面优化保留在独立待办，README.md 和 AGENTS.md 未修改。

### W2.1：来源登记与固定身份接纳

- 新增 `org.aurora.world:registries/sources`，接收 `kind=source` 的 SourceSpec 工厂定义。WorldSources 在 prepare 前选择来源、复制 JSON 参数并绑定唯一 source_id，尊重实际接收方的拒绝规则；SourceFactory 只获得固定身份的 emit 回调及配置，不接收原始 ctx。定义替换不暗中改变已选择的工厂，定义发现与生命周期连接不创建来源或后台任务。
- SourceInstance 提供异步 start/stop/aclose；四个 `org.aurora.world:handlers/sources/*` 声明连接到 core 的 prepare/start/stop/clean。进入对应来源 start 时开放回调，prepare 期间、停止接纳后及清理后均拒绝投递；不能通过回调更换来源身份，来源只能在宿主线程提交。重复与冲突沿用 W1，不重复写入记录。
- 启动失败、取消或启动期间停止接纳会永久封闭入口；已接纳的记录保留，宿主收尾落盘。工厂返回前负责自身部分资源，返回后由所有者托管；停止和清理按逆序执行，失败保留资源供重试，成功动作不重复。来源后台任务仍由实例 stop 负责收束，统一后台失败观察及 TOML 装配留至 W2.2。
- 新增 28 项验收，覆盖声明诊断、两个来源身份隔离、配置副本、跨线程拒绝、旧回调失效、接收方拒绝、连接回滚、工厂替换、启动失败与取消、停止/清理失败后的重试。完整 `pnpm exec uv run --locked aurora check` 通过：626 项 Python、97 项 TS、5 项原生终端测试；未调用真实模型或 MCP 服务。
- 11 个 wheel 构建完成，最终 world wheel 在 `build/w2-1-isolated` 的干净环境安装验证；环境只有 core/world，无 agent、bot、control、model_adapter、CLI、API、config 或 MCP。更新既有 world_roundtrip 夹具，经来源工厂与生命周期完成接纳、停止拒绝及跨进程恢复，序号由 `[1, 2]` 继续到 `[1, 2, 3]`，不新增示例路径。
- 同步公共 ID、架构、计划与启动指南。新增五项非持久公共定义，原记录状态、插件名、依赖及快照格式不变，无配置或数据迁移；W2.1 已完成，下一步 W2.2 声明配置与来源服务，W2.3 周期来源及 MCP 双路径尚未交付。

### 明确 world 来源与 MCP 双路径的推进计划

- 根据已确认的设计方向，将 M4.W2 划分为来源契约、配置/生命周期、模拟及周期来源验收三个切片；来源通过绑定 source_id 的接纳入口投递，生命周期复用 core，不承担 bot 调度。完整自研环境周期的业务行为尚未定义，本次只安排最小周期来源验证扩展点。
- MCP 客户端计划从 bot 内部实现调整至待新增的 `aurora_adapters.mcp`，由独立组件持有资源，world 来源桥与 agent 工具桥分别显式启用。记录官方 SDK 2.x 与 MCP `2026-07-28` 的版本区别，首版采用本机 Streamable HTTP 测试服务；旧协议回退、stdio 及未验收功能不预先列为已支持。
- 保留 M4.B1/B2/B3 编号，新增 M4.B4 世界通知桥；推进顺序为 W2 → B1/B4 → B2/B3 → W3/W4。补齐工具发现先于 bot prepare、通知语义分流、无稳定事件身份的限制、工具集合重装配、共享客户端关闭及未知结果不自动重试等验收约束。
- 同步架构与公共 ID 目录，移除从未登记的 bot mcp_servers 规划项；没有新增实际公共 ID、插件、配置或运行代码，无数据迁移。仅检查文档格式、相对链接、锚点和差异，不运行无关测试；README.md、AGENTS.md 保持原样。

### M4.W1：独立世界记录与来源身份

- `aurora_world` 提供 `WorldRecords.append/get/read`、`WorldRecord`、`WorldReceipt` 和 `WorldPosition`，只依赖 core。插件登记全局持久状态 `org.aurora.world:state/records`，发现与构造不写入状态、不创建资源；接收消息无需 bot、agent、模型、目标实例或 run。变化观察复用 `ctx.subscribe`，不新增重复的操作、事件总线或投递队列。
- `(source_id, message_id)` 是来源消息身份；同身份同 JSON 内容返回原记录且不再通知，内容冲突拒绝覆盖。记录拥有独立 record_id 和连续序号；按来源及位置读取返回独立副本。位置同时绑定日志、序号与记录身份，拒绝日志丢失、替换、位置超前，以及旧快照恢复后序号被新记录复用的情况。
- D11 的记录保存策略确定为版本化完整 ctx 日志，保留全部记录与去重身份，不自动裁剪。一次同步写入提交记录及身份；宿主负责异步保存和最终 flush，接纳回执不承诺已落盘或已经转交。非法 JSON、损坏结构、重复身份、不连续序号及未知版本在写入/恢复时明确拒绝；每次操作复制完整日志，首版面向有限规模输入。
- 验收新增 39 项用例，覆盖重复/冲突、数据副本、分页与来源过滤、读取位置回退、重入订阅、失败提交、非法数据、跨线程拒绝、坏快照、落盘失败后重试与跨进程恢复。完整 `pnpm exec uv run --locked aurora check` 验证 598 项 Python、97 项 TS、5 项原生终端测试；未调用真实模型。
- 11 个 wheel 构建完成；最终 world wheel 在 `build/m4-w1-isolated` 的干净环境中验证，环境仅安装 core/world，缺少 bot、agent、control、model_adapter、CLI、API、config。独立进程两次运行 `tests/fixtures/world_roundtrip.py`，恢复原身份、识别重复输入并将序号从 `[1, 2]` 继续到 `[1, 2, 3]`。
- 同步设计、公共 ID、计划与示例指南。无旧 ID、插件名或配置变更，旧数据无需迁移；含新世界状态的快照恢复时须显式启用 aurora_world，不静默忽略缺失定义。M4.W1 已交付，下一步 M4.W2 来源与生命周期；live_workshop 的示例调度留至 M4.W4 统一替换，cadence 尚未实现。

### M3.9：本机双工作台、断线与重启联调

- 新增 `tests/e2e/test_tui_recovery.py` 与 `apps/aurora_tui/tests/recovery-process.ts`：真实 Python bot/API 与 Node 共享客户端连接两个 OpenTUI 原生测试工作台，双向编辑并观察 ctx，区分 null 与缺失地址；两端读取同版 TOML 后保存产生修订冲突，拒绝覆盖并保留未保存草稿。页面和工具展开偏好保持各自独立。
- 测试链路在首次提交已被后端接纳后丢弃 HTTP 回执并断开该端 WS，另一端继续观察和追加引导。重连通过查询核对原请求与原 run，代理确认提交只发送一次、工具只执行一次；全量快照包含断线期间的新增与更新，移除已删除地址，保留未发送文本与配置草稿，不自动重放动作。
- 在两端在线且工具等待时停止宿主：两端退出就绪状态，待确认配置写入作废；后端结束工具、关闭工具及模型，再保存最后写入。同端口从原存储重启后，两端识别新会话、旧请求失效，恢复持久状态并移除非持久状态；启动及旧请求重试不触发模型，只有显式新提交才执行。单端退出不影响另一端继续编辑，最后退出释放全部 API 订阅。
- 验收：完整 `pnpm exec uv run --locked aurora check` 通过，559 项 Python、97 项 TS 和 5 项原生终端测试通过；既有跨语言共用 ctx 用例、单工作台编辑/引导/退出/取消与新增恢复场景一并回归。使用本机服务、假模型和模拟终端，不调用真实供应商；M3.9 结论限于本机路径，浏览器/远程访问及人工终端体验另行验收。
- 本次无需修改运行实现，无公共 ID、配置、快照、依赖或分发内容变化；主线接续 M4.W1，M3 尚未整体完成。TUI 全面优化继续保留在独立待办中。

### 单列 TUI 全面优化待办

- 按用户要求新增 [TUI 全面优化待办](archive/2026-11-09/tui_optimization_todo.md)，记录操作与反馈、编辑体验、布局与文本、性能、偏好及终端兼容的分级任务和验收要求；条目保持未完成，不将评估方向写成已确认缺陷。
- 计划明确该队列独立于主线，当前继续 M3.9 多客户端、断线与重启联调；影响正确性的问题仍随主线修复。仅修改文档，检查格式、相对链接与差异，不改 README.md 或 AGENTS.md。

### M3.7：TUI ctx 操作与 TOML 编辑

- 状态页按 ↑/↓ 选择精确地址，F6 编辑，Ctrl+N 填写新地址。JSON 编辑包含完整 ID、location 和未截断的值；F5 重新读取，F8 准备整项替换，Ctrl+D 准备删除，F9 明确确认。JSON null、缺失地址和删除不存在地址分别反馈；保留宿主状态键白名单，普通 ctx 写入不是事务，也不会自动保存 TOML 或重建运行资源。
- F7 打开声明 TOML 文件列表，选择后 F5 读取，Tab 进入文本编辑，F8/F9 保存。使用共享配置客户端与后端校验，展示重启生效说明；端点未开放时提示使用宿主 `--edit-config`。配置冲突、拒绝和未知结果保留草稿，冲突或结果不确定后须重新读取，断线和重连不重发写入。
- 编辑器为模态：确认与在途请求锁住草稿，拦截底层交流/取消动作与粘贴；Esc 先取消确认，再关闭编辑器并丢弃草稿，F12 帮助恢复原编辑焦点。订阅刷新不覆盖正在编辑的文本；程序加载新文档与用户草稿分别更新，避免原生内容事件时序导致保存旧值。编辑草稿不进入本地偏好或后端快照。
- 验收：完整 `pnpm exec uv run --locked aurora check` 通过，558 项 Python、97 项 TS 和 5 项原生终端测试通过。新增编辑控制器与原生交互回归，覆盖完整地址和值、确认去重、非法 JSON、拒绝/响应丢失、断线作废、配置修订、帮助模态和 48×18 窄终端；真实 Python API + Node TUI 联调验证 ctx 创建/读取/删除、未开放键拒绝、TOML 注释保存，随后完成既有交流/引导/退出观察/取消场景。界面使用 OpenTUI 原生测试渲染器与模拟按键验收，未调用真实模型。
- 同步启动指南、架构与计划；M3.7/M3.8 基本操作已交付，M3.9 完整多客户端/断线联调仍待推进，M3 不标记整体完成。新增配置端点及 wheel 安装验收见下节；已有业务配置、运行身份和快照无需迁移。

### 提供声明 TOML 的显式编辑端点

- `aurora_config` 登记 `org.aurora.config:endpoints/configuration`，提供 POST `/configuration/list`、`/configuration/get`、`/configuration/save`。配置服务在 config 成功后绑定文件访问，停止接收时关闭；API 按宿主显式选择开放，两个包不互相导入。`scripts/serve_bot.py` 和 `default_bot --serve` 增加 `--edit-config`，默认不开放配置编辑。未开放路由统一返回固定 JSON 404。
- 提取启动与编辑共用的文件定位、结构及关联校验，保留现有缺失模板复制与配置原子注入语义。编辑只接受已登记配置 ID，排除任意路径、host.toml 与凭证文件；单文件上限 256 KiB。读取修订覆盖全部声明文件，冲突返回 409；同一宿主保存串行，校验通过后完整写临时文件并替换，原始注释与文本保留。与外部编辑器仍存在检查/替换竞态，不承诺跨进程比较交换或跨文件事务。
- 保存只更新 TOML，返回 `restart_required=true`，不改 ctx、不创建资源或重建模型/工具。下一次启动再次加载与创建资源。共享 `CtxClient.configuration` 提供 list/get/save，复用 HTTP 关闭、超时与不重试规则，校验响应身份和修订；生成契约同步合并 config 描述，API 独立导出仍不依赖 config 或 bot。
- 验证配置服务的未就绪/关闭、未开放路由、来源拒绝、注释保留、结构与关联校验、重复保存冲突、跨文件修订、写入失败保留原文件及重启生效。既有模型协议测试明确断言新增端点是唯一可选未连接项，其余登记继续全部接纳。11 个 wheel 构建通过；三个干净环境验证 config/API 无 agent/模型/bot/CLI、control 无 agent/模型、agent 无 bot/CLI/API，并检查安装包中的端点与契约可导入。未调用真实模型。
- 新增端点 ID，不改变已有插件名、配置状态 ID 或快照格式，无用户数据迁移；公共 ID 目录已同步。API 缺席时按现有规则报告可选接收方未连接。

### M3.7：TUI 连接设置与本地偏好

- 启动按命令行参数、本地偏好、内置默认值依次选择连接和实例。新增 `--save-preferences` 保存连接选择后退出，不连接后端；普通启动参数仅本次生效。切换到不同后端而未指定实例时恢复自动选择，避免沿用旧后端的目标。`--preferences PATH` 可隔离不同界面的设置，默认文件位于用户配置目录，详见[启动指南](archive/2026-11-09/START.md)。
- 正常退出自动保存改变的页面及 Ctrl+T 全局工具展开偏好，重新启动恢复页面、焦点和工具详情展示。按运行展开状态、筛选词、草稿、消息、回执及凭证不持久化；偏好不进入后端 TOML、ctx 或业务快照。保存前重新读取文件并合并改动；并发写同一文件时最后一次完整写入生效。
- 版本化 JSON 校验拒绝未知字段、无效类型和版本；HTTP(S) 地址拒绝 URL 凭证、查询参数及片段。无效文件保留原内容并报告错误，帮助入口无需读取文件。完整临时文件通过重命名替换旧文件；退出保存位于连接清理和终端恢复之后，保存失败不妨碍后端运行。
- 验收：完整 `pnpm exec uv run --locked aurora check` 通过，556 项 Python、87 项 TS 和 4 项原生终端测试通过。新增 22 项偏好及命令入口测试，覆盖加载/保存、覆盖优先级、临时连接隔离、后端切换、坏文件保护与无终端保存；新增原生界面重开测试，检查状态页焦点、工具展开及不恢复请求/草稿。执行环境拒绝交互式 PTY，界面通过 OpenTUI 原生测试渲染器与模拟按键验收；未调用真实模型，保留既有 FFI 实验性与 Pydantic ReadOnly 提示。
- 同步计划与启动指南。M3.7 的后端配置编辑、ctx 写操作及 M3.9 完整联调仍待交付；无公共 ID、插件、依赖或分发内容变化，不涉及业务数据迁移。

### TUI 退出时展示 AuroraBot 字符标志

- TUI 正常退出并等待 renderer 关闭、终端恢复后，在主屏幕打印 `about` 同款字符画，仅输出一次。图案保存于 TUI 的 `assets/logo.txt`，不为展示标志启动 Python 进程或依赖 CLI 运行环境。
- 沿用品牌蓝 `#4B79EC`，遵循终端颜色能力与 `NO_COLOR`；宽度不足时显示紧凑文字标志。帮助命令和启动失败不打印退出标志，退出界面仍不取消后端运行。
- 验收：字符画逐字比对 `about.LOGO` 一致，检查宽屏、窄屏及无色输出；格式、ESLint/Oxlint、TUI 类型检查和 3 项原生终端回归通过。输出位于 `renderer.closed` 与连接清理完成之后。

### 启用 OpenTUI 内置 Markdown 渲染

- 交流页使用 OpenTUI 0.8.1 的 `MarkdownRenderable` 显示模型输出和历史模型消息，支持标题、强调、列表、行内代码、代码块及表格；用户输入与工具数据保持原文展示。无需增加 Markdown 解析依赖或修改后端数据。
- 每轮输出使用独立组件，按 execution_id 增量更新，后续轮次或运行终态到来时完成流式解析，避免未闭合语法跨消息影响展示。保留控制字符过滤、滚动位置和新内容提示。Markdown 样式位于 `theme/markdown.ts`，沿用深灰背景、灰白正文及浅蓝链接/关键字；共享原生样式在页面退出时释放。
- 格式、ESLint/Oxlint 和类型检查通过；65 项 TS 测试、3 项原生终端测试及真实后端联调通过。新增历史消息、用户原文、流式代码围栏、连续两轮输出、表格与窄终端回归，等待异步富文本渲染后核对实际内容帧。未调用真实模型；重启 TUI 即可生效。

### 避免 PowerShell 启动 bot 后端时丢失 JSON 引号

- 新增 `scripts/serve_bot.py`，默认使用 `data` 和端口 `10270`，从既有 bot 公共 ID 构造状态白名单与直接交流端点参数，直接通过 Python 启动正式 CLI。配置、凭证解析、生命周期及落盘仍由已有宿主负责，不修改 JSON 校验规则。
- 示例指南改用 `uv run --locked --env-file .env python scripts/serve_bot.py`，无需在 PowerShell 命令中传递嵌套 JSON 引号；支持 `--data-dir`、`--port` 和 `--help`。
- 验收：Windows PowerShell 的脚本入口和正式 CLI JSON 参数解析通过；在宿主执行边界检查四项状态、交流端点、端口与已有装配选择，未调用真实模型。Ruff 格式/lint、Pyright 和 23 项 CLI/远程 CLI 回归通过。脚本在同一进程调用 CLI 入口，保留既有退出码和 Ctrl+C 生命周期收尾。

## 2026-11-01

### 使用现有 data 配置启动 TUI 的真实模型后端

- 检查本地 `data` 的默认装配、`reasoning → primary` 绑定、DeepSeek `deepseek-flash` 配置与流式开关，并确认 `.env` 可提供 profile 引用的环境凭证，未输出密钥内容。仅在本地宿主插件列表补充 `aurora_api`，保留模型、工具和业务数据配置。
- 使用现有 `aurora --data-dir data serve` 开放本机 `10270`、直接交流端点和四项 bot 状态；`/conversation/info` 确认 `main` 实例和宿主会话就绪。未发送模型测试消息，未执行真实模型验收。可复用的启动及关闭方式写入[示例指南](archive/2026-11-09/START.md#使用已有配置启动真实模型后端)。无产品代码或契约变化。

### 整理 TUI 目录并加入分组快捷键帮助

- 底栏改用独立布局容器承担左右 3 列、上下 1 行留白，修复文字组件 padding 未体现的问题；常态仅显示 `? 帮助` 和按需出现的新内容提示。通知行也由容器控制边距。
- 参照用户提供的 Codex 截图，在输入区上方展开“输入 / 工作台 / 运行”帮助面板，保留深灰背景与灰白说明，按键使用浅蓝从色。宽终端三栏、窄终端纵向滚动；较矮终端在帮助期间缩小输入区高度。帮助和命令行 `--help` 共用键位说明。
- 空输入时 `?` / Shift+/ 打开，已有文字时保留问号输入，F12 随时打开；`?`、Esc、F12 或底栏点击关闭。模态期间拦截提交、粘贴、切页与取消等底层动作，保留 Ctrl+C 退出；关闭恢复原页面、输入焦点、草稿和滚动位置。
- TUI 源码按 `state/`、`theme/`、`ui/pages/`、`ui/components/` 划分；交流流与只读状态从主视图拆出，主视图负责布局、导航、焦点与键盘路由。色卡移至 `assets/palette.svg`；同步入口、测试和文档引用，删除旧路径，不保留转发文件。
- 验收：完整 `pnpm exec uv run --locked aurora check` 通过，556 项 Python、65 项 TS 和 2 项原生终端测试通过。新增帮助开启/关闭、Shift+/、模态动作与粘贴拦截、问号正常输入、焦点与滚动恢复、窄终端完整滚动验证；读取检查 120 列分栏和 48 列纵排的原生内容帧，命令行帮助入口通过。用户提供的 `tmp/image.png` 仅作参考，不纳入提交。

### 精简终端提示并统一品牌调色板

- TUI 背景、输入区、边框和滚动条改为无色相的深灰层级，正文和辅助文字使用灰白。主题色集中在 `apps/aurora_tui/src/theme/colors.ts`，原生 renderer 与界面共享背景；`#4B79EC` 用于输入焦点边线和光标。
- 对比色按 HSL 色相旋转 180° 得到 `#ECBE4B`；两个从色按 sRGB 通道分别混入 30% 白/黑并四舍五入，得到 `#81A1F2` / `#3555A5`。三色先保留于调色板，不额外增加界面彩色元素。[调色板色卡](../apps/aurora_tui/assets/palette.svg) 展示全部色值、用途及对背景的对比度。
- 移除连接成功、引导接纳、空白页引导和输入框内的重复说明，正常状态不占提示行；页脚精简为切页、退出与按需出现的新内容提示。运行标识、模型输出标签、断线/异常、旧会话、请求未确认及取消反馈继续保留，既有快捷键不变。状态页去掉重复的目标与连接信息。
- 验收：TUI 格式、ESLint/Oxlint 和类型检查通过，6 项控制器回归、1 项原生交互测试、1 项真实后端联调通过；检查 90×24 原生终端内容帧，SVG XML 与主题色值一致。未修改后端契约、配置或快照。

### M3.7 / M3.8 首版终端工作台

- `apps/aurora_tui` 提供 OpenTUI 入口，通过共享 `CtxClient` 连接已有 bot；Node 26 启动脚本仅在原生入口启用 `--experimental-ffi`。顶部交流/状态页签、底部多行输入、按运行分组的消息和模型输出、可展开工具及明确取消可用。状态页按 ID/location 筛选后端开放的只读 ctx，不承担插件装配或业务执行。
- 切页保留草稿、工具展开和滚动位置；仅在底部跟随新输出，上翻显示新内容提示。支持中文、多行粘贴、窄终端、键盘和页签点击。输出过滤终端控制字符；较长输出及状态值显示有长度限制，界面仅保留最近 100 个可裁剪运行，不充当完整审计存储。
- 接纳与调用完成分开，结束状态由回执查询确认；观察到的 ctx 终态单独标注。断线禁用新提交但保留草稿，恢复后刷新状态并核对回执，不自动重发；F4 明确重试原身份，后端会话改变后旧请求失效。Ctrl+X/运行内停止按钮等待取消收尾；Ctrl+C 只关闭观察连接、释放原生资源和恢复终端，不取消 bot。
- 原生渲染验收纳入 `aurora check`。新增控制器回归、真实 OpenTUI 布局/输入/切页/滚动验收及 Python API + Node 原生 TUI 联调，覆盖提交、同 run 追加引导、退出观察后继续运行、重新连接后取消、工具与模型关闭顺序；全部使用假模型。实际读取并检查 100×30 终端帧，另覆盖 48×18 窄终端。
- `pnpm install --frozen-lockfile`、完整 `pnpm exec uv run --locked aurora check` 和全工作区 wheel 构建通过：556 项 Python 测试、65 项 TS 测试、1 项原生终端测试，格式/lint/类型及生成契约检查通过。测试执行环境拒绝分配交互式 PTY，原生界面通过测试渲染器与按键输入模拟验收，尚未在该环境完成真实终端人工操作；启动帮助入口通过。保留 Node FFI 实验性接口和既有供应商 SDK Pydantic 提示。
- 启动方式见[示例指南](archive/2026-11-09/START.md)。本次交付交流页与只读状态页；M3.7 的配置编辑、ctx 写操作及本地偏好持久化仍待实现，M3.9 尚需完整多客户端/断线联调，M3 不标记整体完成。无公共 ID、后端配置、快照格式或插件入口变更。

### 升级 Node 26 并验证 OpenTUI 原生运行路径

- 工作区 Node 要求统一为 `>=26.4.0 <27`，`.node-version` 和 `devEngines.runtime` 固定 `26.13.0`；pnpm 在需要时下载项目运行时，所有 pnpm 脚本及 `pnpm exec` 使用该版本，不替换系统全局 Node。pnpm 保持 `12.15.0`，不引入 Bun 运行时。
- 同步 `@types/node` 到 `26.6.6`、ESLint 的 Node 语法目标及锁文件。TUI 保留已安装的 `@opentui/core@0.8.1`，按工作区约定纳入 catalog；界面代码尚未实现。
- OpenTUI 的 Node 路径使用 ESM 和 `--experimental-ffi`，仅原生渲染入口需要该标志，不加入全局 NODE_OPTIONS。Windows x64 上已用 Node 26.13.0 完成真实原生测试渲染、帧读取和资源释放；具体运行要求见 [OpenTUI 文档](https://opentui.com/docs/getting-started/runtime-support/)。FFI 仍是 Node 实验性接口。
- `pnpm install --frozen-lockfile` 通过。OpenTUI 的间接依赖 `bun-ffi-structs@0.3.1` 仍声明 TypeScript `^5` peer，工作区为 TypeScript 6.0.3；保留这一上游提示，不扩大版本容忍范围或降低工作区编译器。Node 26 下 `pnpm exec uv run --locked aurora check` 全部通过：555 项 Python 测试、59 项 TS/工具链测试、格式、lint、类型及生成契约检查；Python 供应商 SDK 保留既有 Pydantic ReadOnly 提示。本次不修改 Python 包、配置、快照或公共 ID。

### M3.6：直接交流端点、运行回执与客户端联通

- bot 的 `aurora_bot.assembly` 登记 `org.aurora.bot:endpoints/conversation`，复用同一 RunOperations 和 AgentRuntime。API 新增 `aurora_api` 插件及 `org.aurora.api:registries/endpoints` 接收方，结构协议不引入 bot/API 双向导入；只在 `serve(..., endpoints=[...])` 或 CLI `serve --endpoints` 显式选择后开放。沿用本机回环、Origin/Host 检查与独立 ctx 白名单，不提供任意 operation 转发。
- 提供 POST `/conversation/info`、`/conversation/submit`、`/conversation/query`、`/conversation/cancel`。客户端先取得 session_id 和 instance_ids；提交携带 session_id、instance_id、request_id、text，回执关联 guidance_id、sequence、run_id 和 accepted=true。空闲提交启动运行，运行中提交追加引导，finish/清理边界提交关联下一次运行；接纳不等于完成。
- 请求去重作用域为 session_id/instance_id/request_id。同身份同文本返回原回执，异文返回 409 request_conflict；不同身份的同文属于新引导。回执最多保留 4096 条，满额返回 429 receipt_limit，不通过淘汰身份允许旧请求重新执行。回执仅存内存，重启后旧会话统一返回 409 session_expired；客户端不自动重放 HTTP 动作，不承诺跨重启去重。
- query 返回关联句柄的 pending/completed/cancelled/failed 与异常类型，pending 覆盖排队、执行及清理，不根据残留 ctx 推断结束。取消限定 instance_id/run_id，等待收尾；未知或已结束返回 cancelled=false，取消期间新引导返回 409 busy。API 关闭、客户端关闭与 HTTP 等待取消不隐式停止 bot。失败的原回执仍可核对，重复提交不会重试业务。
- `CtxClient.conversation` 提供 info、submit、query、cancel，共用 HTTP 超时、主动关闭和错误处理；响应校验拒绝会话、实例、请求和运行身份错配。契约生成显式合并 API ctx 描述与 bot 直接交流描述，保留 API 独立导出；info/query 不伪造 operation ID。生成 JSON 与 TS 类型/绑定同步更新。
- `examples/default_bot/main.py --serve` 提供无需世界插件、网络模型或凭证的常驻演示；启动及客户端代码见[示例指南](archive/2026-11-09/START.md)。更新[计划](archive/2026-11-09/plan.md)、[架构](archive/2026-11-09/aurorabot-design-v0.2.3.md)和[公共 ID](archive/2026-11-09/aurorabot-id-catalog-v0.2.3.md)，接续 M3.7 OpenTUI。新增接收方与端点 ID，无旧 ID 重命名、配置或快照迁移；README.md 和 AGENTS.md 保持不变。
- 新增 6 项 Python 场景及 11 项 TS 测试，覆盖重复/冲突、实例隔离、运行中引导、结束边界、清理期间查询与取消、失败/关闭、API 断开、宿主重启和真实 Node/Python bot 联通。完整 `uv run --locked aurora check` 通过：555 项 Python、59 项 TS/工具链测试，以及格式、lint 和 Python/TS 类型检查；供应商 SDK 保留既有 1 项 Pydantic ReadOnly 提示，未调用真实模型。
- 全部 11 个 wheel 构建通过，产物位于 `build/m3.6-wheels`。四个隔离环境使用实际 wheel 验证 API 无 bot/agent/模型/CLI、control 无 agent/模型、agent 无 bot/CLI/API、bot 无 CLI/API；插件发现、直接交流声明及 bot 模板资源通过。文档 50 条相对链接和 git diff 空白检查通过。

### 确定直接交流路径并纳入 M4-W 世界输入规划

- D10 确定面对面交流由 bot 产品入口向目标实例的既有 AgentRuntime 提交引导；首版默认 Panel/TUI/CLI 使用此路径，外部消息与环境变化经 world/cadence 接入。路由按交流性质配置，不把平台永久绑定到某条路径；直接交流不要求先进入 world。两条路径共用一个调度所有者，运行中保留当前 loop，接纳不等于完成，关闭界面不取消后端运行。
- 首版界面确定为 bot 工作台，展示直接交流、运行与工具活动，不提前实现多会话上下文隔离。M3.6 接续专用提交/取消入口、回执、重复请求与运行关联；复用 run 操作，不新增 conversation/send、conversation/cancel 同义实现。具体信封和 URL 待实现时同步契约与测试。
- [设计文档](archive/2026-11-09/aurorabot-design-v0.2.3.md)补充两条路径与包边界：world 负责独立的世界记录与来源，cadence 先作为 bot 包内可选插件逐条原样转发，不做语义聚类、合并或延迟调度。agent 不依赖 world，cadence 不另建激活调度循环；直接对话与世界记录分别保留来源身份。
- [计划](archive/2026-11-09/plan.md)新增 D11 与 M4.W1–M4.W4：世界记录及接口、模拟来源与生命周期、原样转发 cadence、双路径与隔离安装验收。M4-W 排在 M3 工作台之后，不阻塞 M3.6；明确重复来源、消费位置、转交结果不确定及关闭恢复边界，后续将 live_workshop 改为正式能力消费者。移除 bot 编码落点中重复的 world 职责。
- [公共 ID 目录](archive/2026-11-09/aurorabot-id-catalog-v0.2.3.md)补充 world/cadence 的命名空间归属，明确 world 当前为空插件、cadence 尚未实现；保留的 conversation 端点规划改为复用已有 run 操作，未预占新的世界业务 ID。同步[主动 bot 设计摘要](archive/2026-11-09/aurora_bot_react_design.md)，原始讨论记录保留为历史草案。
- 本次仅更新文档，不改 README.md、AGENTS.md、运行代码、已登记 ID、插件清单、配置或快照，无需数据迁移。M3.6 和 M4-W 未标记为已交付。
- 验证通过：5 份文档的 Prettier 与 Ruff 格式检查、39 条相对链接、4 项 M4-W 任务编号唯一性及 git diff 空白检查。现行设计已移除过期的 M3/D10 状态和 cadence 自建调度要求；历史聊天和旧变更记录保留原文。纯文档修改未运行业务测试或真实模型验收。

### M3.5：共享 TS ctx 客户端与断线恢复

- `@aurorabot/client` 导出 `CtxClient`、订阅句柄、更新类型及 `RemoteError`/`ProtocolError`，复用生成的 HTTP/WS 绑定和 core ctx ID。提供 get、set、delete、list、subscribe、unsubscribe；HTTP 方法接收对应的请求对象，可另传 AbortSignal。get 保留 JSON null 与缺失错误的区别，set 返回 null，delete 返回是否删除，list 保留精确 location 语义。没有任意 operation 转发入口。
- 每个订阅独立维护 connecting、refreshing、connected、reconnecting、failed、closed 状态。subscribe 立即返回句柄，ready 等待首次握手、读取匹配状态及缓冲事件交付完成；观察者接收 status、snapshot、change 更新。观察者按顺序同步调用，异步处理须自行保持顺序；观察者抛错或 Promise 拒绝仅终止自己的订阅。
- 每次连接先收到 WS ready，再通过 list/get 读取匹配状态，随后交付刷新期间的变化。snapshot 是多次读取的结果，不是原子快照；读取与事件可能短暂重复或交错，界面按完整地址替换/删除状态，不据此触发业务副作用。刷新时已删除的地址允许返回 not_found。事件修订号只在当前连接内检查递增，允许过滤形成的间隔；重连重新建立基线，兼容宿主重启后的修订号归零。
- 网络故障、握手超时和慢消费者错误按 250ms 起、最多 5s 的指数退避重连，并重新订阅与读取。刷新事件缓冲默认 256，溢出显式通知重连；旧连接迟到的结果不会进入新状态。访问拒绝、协议错误和无法编码的状态终止订阅，避免无效重试；`reconnect: false` 可关闭自动重连。HTTP 请求默认超时 10s，不自动重试任何动作，写入中断也不会因重连重复提交。
- unsubscribe 只接受所属客户端仍持有的句柄，重复或跨客户端取消返回 false；取消会中止刷新、停止退避并等待连接关闭，握手等待上限 2s。close 幂等，停止新工作、中止并等待在途 HTTP 与订阅清理，也等待正在取消的连接；取消通知中重入 close 不提前返回。关闭观察与关闭客户端都不取消后端 agent 运行。
- 请求编码拒绝非有限数值、孤立代理字符、undefined 状态值、循环引用及非 JSON 对象，避免 JSON.stringify 静默改值；响应形状和事件身份经过校验。沿用既有 JSON number 精度范围，无新增凭证、配置、持久状态或公共 ID，不涉及用户数据迁移。
- 新增 39 项 TS 测试及真实 Node/Python 集成场景。两个客户端共享 11 组 ctx 用例，覆盖空值、精确地址、删除、错误与中文 JSON；真实 HTTP/WS 验证双订阅独立取消、后端重启后的重新读取、修订号重建及资源释放。当前验收范围为 Node 本机 API；浏览器来源、远程认证、D10 界面运行协议和 OpenTUI 仍待后续任务，未调用真实模型服务。
- 完整 `uv run --locked aurora check` 通过：549 项 Python 测试、48 项 TS/工具链测试，以及格式、lint、Python/TypeScript 类型和工作区导入检查。供应商 SDK 保留 1 项 Pydantic ReadOnly 提示。未增加运行依赖，现有生成契约保持一致。

本机 API 启动后，可在工作区 Node 客户端中使用（开放状态由宿主的 keys 决定）：

```ts
import { CtxClient } from '@aurorabot/client';

const client = new CtxClient('http://127.0.0.1:10270');
try {
  const subscription = client.subscribe({}, (update) => {
    console.log(update);
  });
  await subscription.ready;
  const addresses = await client.list();
  for (const address of addresses) {
    console.log(await client.get({ key: address.id, location: address.location }));
  }
  await client.unsubscribe(subscription);
} finally {
  await client.close();
}
```

### M3.4：本机 ctx 传输契约按需生成

- `aurora_api.contract.describe_contract()` 描述现有四个 HTTP ctx 请求及响应、错误、WS 握手与事件信封，显式绑定 URL、方法、既有 core 操作及事件 ID。JSON Schema Draft 2020-12 保留必填、可选、空值与 location 结构；业务状态值仅描述为 JSON，不读取配置、登记表或运行期资源，不引入新公共 ID。
- `uv run --locked python scripts/generate.py` 生成 `packages/aurora_client/src/generated/ctx-contract.json` 和 `ctx-contract.ts`，TS 类型与绑定常量由 `@aurorabot/client` 导出。需要已安装 Python 工作区及 Node/pnpm 开发依赖，格式化复用工作区 Prettier。`--check` 不写文件，产物缺失或过期时返回非零；`--output <目录>` 可指定输出位置。生成一致性已纳入 pytest 回归。
- 描述中的 `aurora-id` 格式使用 core 的 Id 语法；JSON Schema 的格式、字符串和数值约束不全部体现在 TS 类型中，服务端继续负责校验。TS 使用 JavaScript number，不提供任意精度整数转换。合法 UTF-8、有限数值、重复对象键等编码约束继续由共用 JSON 编解码实施。
- WS 保持每连接一个订阅，关闭即取消，revision 作用域为当前宿主 ctx；断线后需重新订阅并读取状态，无历史补发。当前接口仍仅开放本机回环及显式状态键，拒绝浏览器 Origin 与非本机 Host。M3.4 完成当前传输范围，M3.5 的共享访问与重连、远程及浏览器访问、D10 界面运行关联仍待实现。计划和公共文档据代码修正为 M3 进行中。
- 新增 17 项契约测试，覆盖真实 HTTP/WS 载荷、必填与空值边界、访问拒绝、慢消费者错误、重复生成及只读过期检查；与已有 API 测试合计 30 项通过。配置、快照和已有 ID 未变化，无需数据迁移，未调用真实模型服务。
- 完整检查中的 548 项 Python 测试、9 项工具链测试通过；修正新增 TS 配置字段排序及本文档、设计文档两处已有代码块格式后，`uv run --locked aurora check --lint` 全部通过，包括格式、lint、Python/TypeScript 类型和客户端导入。供应商 SDK 保留 1 项 Pydantic ReadOnly 提示。API/core wheel 构建通过，隔离安装验证 4 条 HTTP 绑定及 20 个数据定义可导出，环境中未安装 bot、agent、配置、模型或 CLI 包，导出不加载 aiohttp。验收 wheel 位于 `build/m3-contract-wheels`。

### JSON 提交前拒绝无法编码为 UTF-8 的字符串

- 共用 JSON 编解码校验字符串值和对象键的 UTF-8 可编码性，拒绝孤立代理字符。HTTP `/ctx/set` 在提交状态前返回 400，保留原值、修订和订阅状态，避免单项非法数据阻断完整快照保存。合法中文、补充平面字符及 JSON 转义中的合法代理对继续往返。
- 新增高低代理字符、嵌套值、对象键和 location 的回归，验证非法 API 请求不修改状态，正常状态仍可保存并恢复。三项审查修复共新增 23 项测试；完整检查中的 531 项 Python 测试、9 项工具链测试通过，修正新测试的类型与 lint 问题后相关 98 项测试复验通过，Python/TypeScript 类型检查通过。
- `uv run --locked aurora check --lint` 复验仅剩本文档原有 ConfigSchema 示例与 `aurorabot-design-v0.2.3.md` 原有代码块的 Ruff 格式问题；其余格式、lint 与类型检查通过。本次未修改这两处历史内容，供应商 SDK 仍有 1 项 Pydantic ReadOnly 提示。

### 批量配置通知保持提交顺序

- EventBus 提供同类型事件的整批入队与派发；Context.configure 在全部配置提交后一次入队全部变更，监听器重入 set、configure 或 delete 时，新通知排在本批之后，修订序号与提交顺序一致。
- 回归覆盖订阅镜像与最终状态一致、批内监听器新增的生效边界，以及批量载荷复制失败不派发、不消耗事件序号；配置、事件和 ctx 相关测试通过。

### 默认装配按实际连接清理执行资源

- 默认装配保存工具与 ReAct 阶段的实际连接，clean 时仅断开持有的连接；执行实例与生命周期所有者同名时，不再移除尚未调用的模型清理处理器。实例名、公共 ID、配置和快照地址保持不变，无需迁移数据。
- 新增 `default`、`default/model`、`default/bot` 配置实例名回归，覆盖正常关闭及模型关闭失败后的重试，验证工具仅关闭一次、模型关闭完成后才保存最终快照并关闭 ctx。默认装配相关测试通过，使用 FakeModel 或模拟传输。

### AgentRuntime 执行回调类型修复

- 创建激活任务时通过协程等待 execute 回调，保留 `Awaitable[None]` 接口，支持返回 Future 的宿主回调并消除 `asyncio.create_task` 参数类型错误。
- 新增 Future 回调回归，验证运行句柄等待完成并保留 run_id；AgentRuntime 与默认装配相关 45 项测试通过，Python 类型检查无错误和警告。
- 完整 `uv run --locked aurora check` 中 508 项 Python 测试、9 项工具链测试及 Python/TypeScript 类型和 lint 检查通过；Ruff 格式检查因本文档原有 ConfigSchema 示例及 `aurorabot-design-v0.2.3.md` 原有代码块格式未通过，未改动这两处内容。供应商 SDK 保留 1 项 Pydantic ReadOnly 提示。

### 五阶段生命周期与独立配置服务

- core 提供 config、prepare、start、stop、clean 五个生命周期插槽。各启动阶段整体推进，依赖先执行；全部 stop 完成后按反向依赖 clean，最后由宿主保存业务状态并关闭存储和 ctx。配置或准备部分失败也进入清理，成功的 stop/clean 处理器不在重试时重复执行。
- `aurora_config` 提供 ConfigSchema、ConfigSpec、ConfigTemplate、config_entries 和 configuration_component。配置以 config 类型登记到 `org.aurora.config:registries/configs`，`org.aurora.config:handlers/load` 在 config 阶段完成模板收集、全部文件校验、关联校验和原子注入。core 不依赖配置包、JSON Schema 库或 TOML 加载实现。
- ConfigSchema 使用 JSON Schema Draft 2020-12 描述类型、必填、未知字段、枚举及范围，并支持 aurora-id 格式；整数严格拒绝布尔值和浮点数，不自动转换字符串类型。properties、additionalProperties 和 items 中的 default 统一补齐，错误报告文件与字段位置，不输出字段值，不获取外部 schema。声明的 check 只承担业务约束。
- ConfigSpec.check 在全部配置结构通过后接收配置状态映射，用于跨文件关系校验。config_entries 同时登记配置与非持久状态；运行期 ctx/set 复用结构和单项业务校验，关联关系在 config 阶段验证。TOML 保持持久来源，运行期覆盖不写回文件。
- 模型 profiles、bindings、默认 Bot 和 CLI 使用统一配置声明。模型适配与默认 Bot 插件声明依赖 aurora_config；CLI 内置启用配置插件并装配服务，host.toml 在插件发现前复用同一读取和校验方法。程序化宿主显式启用配置插件，并将 configuration_component(registry, ctx, hooks, storage) 加入生命周期组件；需要在 config 处理器读取配置的组件依赖 aurora_config 实例。
- Bot 的 stop 收束 AgentRuntime，clean 关闭工具、模型并解除实例绑定。默认 Bot 与巡检示例复用插件结构声明、提供各自的 config.tomls 模板；core 计数器在 clean 解除订阅，独立 agent 在 clean 关闭模型。默认 Bot 示例配置位于 org.aurora.bot/bot.toml，内置 Bot 模板仍为 org.aurora.bot/config.toml；框架不迁移或删除用户文件。
- 完整 `uv run --locked aurora check` 通过：507 项 Python 测试、9 项工具链测试，格式、lint 和 Python/TypeScript 类型检查通过；供应商 SDK 保留 1 项 Pydantic ReadOnly 提示。验证包含五阶段顺序、失败清理与重试、clean 后最终落盘、默认值隔离、严格类型、跨配置原子拒绝及 core 无配置包时独立运行。
- 工作区 wheel 构建通过。干净 control 环境仅安装 core/control 并完成组合执行；干净 agent 环境未安装 bot/CLI/API，完成模型工具往返和重启恢复。实际安装的配置包完成生命周期注入，模型适配 wheel 提供 TOML 模板，配置状态未进入快照。构建和安装验收目录为 `build/config-lifecycle-*`，未调用真实模型服务。

### 文档基线 v0.2.3

- 设计文档与公共 ID 目录升版为 v0.2.3，同步 control、agent、bot 的包职责、命名空间、依赖方向、模型适配器状态与 M2 完成情况；补充 `aurora_config` 的配置声明、校验、模板与 config 阶段边界；旧版本号只保留在修订记录中。
- [计划](archive/2026-11-09/plan.md) 更新实现基线、M2 完成状态、D03/D05/D06/D07 结论、模块落点与 M3 接续队列；[M2 交接](archive/2026-11-09/m2-handoff.md) 标注为已完成的交接语境，并修正模型、CLI 与依赖方向；[主动 bot 设计](archive/2026-11-09/aurora_bot_react_design.md) 与[拆包评估](archive/2026-11-09/aurora_agent_extraction_assessment.md) 补充实施位置与阶段状态。
- `AGENTS.md` 的项目结构补齐 `aurora_config`、`aurora_control`、`aurora_agent`、`aurora_logging`、`aurora_world`；[示例指南](archive/2026-11-09/START.md) 的公共 ID 链接指向 v0.2.3。
- 本次仅改动文档，不改变运行行为。文档更新前的基线 `7b84b6b` 完整检查通过（488 项测试）；当前工作区另有进行中的 `aurora_config` 迁移，未重新取得全绿检查，该差异不归因于文档更新。`docs/`、`examples/START.md` 与 `AGENTS.md` 的 71 条相对链接全部有效。

### 示例入口与独立运行管理

- 示例提供 core 计数器、control 控制流、独立 agent、默认 bot 和持续巡检宿主五条路径，完整启动方式见 [示例指南](archive/2026-11-09/START.md)。真实模型验收统一使用 `scripts/accept_m2.py` 的 TOML profile 与 CLI 流程。
- 独立 agent 示例使用 AgentRuntime 提交输入、接纳流式期间引导并等待结果；宿主关闭时停止提交、等待 runtime 收尾，再关闭模型并保存状态。模型失败、部分输出和取消语义由模型组件测试覆盖。
- 公共 ID 目录第 6 节按实际插件清单列出 control、agent 和 bot 定义，源码链接与示例命令使用当前包路径。
- 完整 `uv run --locked aurora check` 通过：488 项 Python 测试、9 项工具链测试，以及格式、lint、Python/TypeScript 类型检查。干净 wheel 环境验证新插件入口、独立控制流、agent 调度、模型工具往返和恢复；bot wheel 不包含执行组件兼容模块。变更文档中的 54 项相对链接检查通过。

### 执行包命名空间与插件发现

- 控制组件、端口与控制状态归属 `org.aurora.control`，agent 组件、ReAct 阶段、工具注册表及工具钩子归属 `org.aurora.agent`。bot 默认配置、装配、运行操作、命令和装配分配的状态地址归属 `org.aurora.bot`。
- 通用插件发现分组为 `aurora.plugins`。控制入口为 `aurora_control`，agent 入口为 `aurora_agent.model`、`aurora_agent.react`、`aurora_agent.tools`、`aurora_agent.react_defaults`；插件配置须使用完整的新入口名称。
- 执行组件仅由各自包导出，默认 bot 直接装配 AgentRuntime。运行时不提供旧导入路径、插件名或公共 ID 的别名；带有旧控制状态 ID 的快照需要离线转换或使用新的数据目录，程序不自动删除或改写用户数据。

### 独立 Agent 执行包

- `aurora_agent` 提供 ReActAgent、ModelCall、ToolExecutor、ReActDefaults 及 AgentRuntime，依赖 `aurora_control`、`aurora_core` 和 `aurora_model_adapter`；工具参数校验依赖由 agent 包声明。默认 bot 使用这些组件完成产品装配。
- AgentRuntime 通过 `get_agent`、`execute`、`is_executing` 三个显式入口连接宿主；execute 须等待激活和清理完成，占用查询覆盖整个执行期间。默认装配直接创建 AgentRuntime，RunHandle、RunResult、Submission 由 agent 包提供。
- agent 插件入口由 agent 分发包直接提供，独立 agent 环境无需安装 bot。公共定义归属 agent 命名空间，具体业务状态地址由宿主显式绑定。
- 默认配置、凭证解析、实例资源装配、状态恢复与裁剪策略、bot 运行操作和 CLI 命令由 bot 提供。独立宿主可显式装配 agent 组件，并负责自己的资源关闭与状态保留策略。
- `uv run --locked aurora check` 全部通过：483 项 Python 测试、9 项工具链测试，以及格式、lint、Python/TypeScript 类型检查；供应商 SDK 保留 1 项 Pydantic ReadOnly 提示。新增独立包边界、兼容类型身份、运行中引导、finish 边界、等待者取消及宿主清理等待验证。
- 工作区 wheel 构建通过。干净 control 环境仅安装 core 和 control 即可执行四种控制组合；干净 agent 环境未安装 bot、CLI、API，完成运行调度、模型工具往返、引导接纳、取消收尾和重启恢复。验收使用 wheel 安装及隔离 Python 进程。

### 独立控制组件包

- `aurora_control` 提供执行身份、状态绑定、执行连接及 Serial、Branch、While、Parallel 四种组合，仅依赖 `aurora_core`。使用执行契约不要求启用控制组件插件。
- 控制插件由 `aurora-control` 分发包提供，发现入口为 `aurora_control`，公共定义和控制状态归属 `org.aurora.control`。
- 仓库组件、示例与测试使用 `aurora_control` 导入。控制流、实例身份、宿主关闭及包边界相关 41 项测试通过，覆盖禁止导入 bot、agent、模型适配和可选宿主时的控制流执行。

### 插件 TOML 配置与启动注入

- TOML 是配置的持久来源。带 StorageService 的宿主在发现后收集配置、恢复运行状态，再原子校验并注入全部配置，随后执行各组件的 prepare/start。装配工厂只构造组件，prepare 可读取完整配置并创建资源。
- 插件使用包内 `config.toml` 或 `config.tomls/`，同一包不能同时提供两种形式。普通 `config/` 代码包不参与收集。每个配置状态显式声明包资源；单文件对应整个状态对象，多文件分别声明目标状态，不隐式合并表。
- 用户文件位于 `<data-dir>/config/<拥有者命名空间>/`。单文件保留 `config.toml` 名称，多文件保留 `config.tomls/` 内相对路径。拥有者默认取状态 ID 的命名空间，也可通过 owner 显式指定。框架只复制缺失文件，保留模板注释，不覆盖用户文件；删除文件后下次启动会重新生成该文件。
- 配置状态显式设置 `persistent=False`，其全部业务地址均不保存、不从快照恢复；运行期 ctx 修改不会写回 TOML。重启直接以文件内容重建，删去的字段不会由快照补回。普通业务状态继续持久化，不根据状态名称猜测用途。配置文件修改在下次启动生效，不提供通用热加载。
- `config/host.toml` 在插件发现前读取 plugins 与可选 assembly。显式 `--plugin` 列表替代文件列表，显式装配参数优先于文件默认值；`--config` 仅临时覆盖当前宿主的 CLI 配置。程序化启动的 configure 回调也只修改本次 ctx。help/id 等查询不启动组件、不生成插件模板，远程连接不读取本地宿主配置。
- 模型 profiles、角色 bindings、默认 bot 和 CLI 均提供包内模板；profile 的协议、地址、凭证引用与能力继续独立。默认 bot 示例、持续巡检示例及 M2 验收脚本使用 TOML 文件准备配置。
- 完整 `uv run --locked aurora check` 通过：475 项 Python 测试、9 项工具链测试，格式、lint、Python/TypeScript 类型检查通过；SDK 保留 1 项 Pydantic ReadOnly 提示。覆盖普通包与压缩包资源、模板冲突、已有文件保留、无效配置原子拒绝、prepare 顺序、配置不落盘、业务状态恢复及宿主选项优先级。工作区 wheel 构建成功，bot、CLI、模型适配包中的模板资源已核对。

插件通过配置接收方声明配置来源，例如包内 `config.tomls/options.toml`：

```python
from aurora_config import ConfigSchema, ConfigSpec, ConfigTemplate, config_entries
from aurora_core import Id

entries = config_entries(
    Id("dev.example:configs/options"),
    ConfigSpec(
        state=Id("dev.example:state/options"),
        template=ConfigTemplate("my_plugin", "config.tomls/options.toml"),
        schema=ConfigSchema(
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {"enabled": {"type": "boolean", "default": True}},
            }
        ),
    ),
    provider="my_plugin",
)
```

将 entries 放入插件清单并声明 `requires=("aurora_config",)` 后，文件路径为 `data/config/dev.example/options.toml`；prepare 中通过 `ctx.get(Id("dev.example:state/options"))` 读取。单文件使用 `ConfigTemplate("my_plugin")`。发布插件时须将 TOML 文件包含在包资源中；未声明的文件不参与加载。

本地初始化可执行 `uv run --locked aurora --data-dir data ctx list`，生成宿主与 CLI 配置。将 `data/config/host.toml` 的 plugins 设置为：

```toml
plugins = [
  "aurora_config",
  "aurora_model_adapter",
  "aurora_agent.model",
  "aurora_agent.react",
  "aurora_agent.tools",
  "aurora_agent.react_defaults",
  "aurora_bot.assembly",
]
# 完成模型配置后，可设置默认装配。
# assembly = "org.aurora.bot:assemblies/default"
```

再次执行 ctx list，生成以下文件；此时不创建模型客户端：

```text
data/config/
├── host.toml
├── org.aurora.cli/config.toml
├── org.aurora.bot/config.toml
└── org.aurora.model_adapter/
    ├── profiles.toml
    └── bindings.toml
```

在 profiles.toml 中填写独立 profile，例如 DeepSeek：

```toml
[primary]
adapter = "org.aurora.model_adapter:adapters/litellm"
provider = "deepseek"
model = "deepseek-flash"
credential = "DEEPSEEK_API_KEY"

[primary.capabilities]
streaming = true
tool_calls = true
```

bindings.toml 填写 `reasoning = "primary"`。兼容服务可在自己的 profile 中设置 `provider = "openai"`、base_url、model 和 credential。凭证字段仅填写环境变量名称，实际密钥由启动环境提供。

使用默认 bot 配置发起一次运行：

```powershell
uv run --locked --env-file .env aurora --data-dir data --assembly org.aurora.bot:assemblies/default --namespace org.aurora.bot run submit '只输出：配置验收成功' --instance-id main
```

## 2026-10-31

### profile 独立连接与 LiteLLM 模型选择

- 每个模型 profile 独立保存 adapter、model、base_url 和 credential，并可声明 provider 与 capabilities；角色绑定继续引用 profile 名称。凭证仍为环境变量引用，客户端及运行期密钥不写入 ctx。供应商协议和地址直接在 profile 中配置，不增加共享 provider 配置表。
- provider 可显式选择 SDK 路由，如 `openai`、`anthropic`、`deepseek`、`xiaomi_mimo`；省略时按 SDK 模型命名规则推断，既有带前缀的配置可继续使用。显式指定 provider 后可填写平台模型名，如 `Qwen/private-deployment`，模型名称中的组织路径保留。OpenAI 兼容服务使用 `provider: "openai"` 与自己的 base_url；siliconflow 可作为 profile 名称，无需登记同名 SDK provider。
- capabilities 可显式设置 `{"streaming": true, "tool_calls": true}`，必须同时提供两个布尔值。显式声明优先，省略时查询 SDK 模型目录，未知能力不会自动开启。能力值须按实际模型填写；启用工具能力时，工具参数按请求通过 SDK 参数检查，不全局注册模型、不静默丢弃工具。
- LiteLLM 工厂支持 OpenAI 兼容路由、Anthropic、DeepSeek，以及锁定 SDK 自带 JSON 定义的兼容供应商（包含 MiMo）。客户端、连接池、地址、密钥和能力按实例隔离；不修改 SDK 全局 provider/model 映射。其他专用 SDK 路由未统一接入实例传输时明确拒绝，兼容 Chat Completions 的服务可选择 openai 路由。
- 完整 `uv run --locked aurora check` 通过：449 项 Python 测试、9 项工具链测试，以及格式、lint、Python/TypeScript 类型与工作区检查；改动代码及测试的 basedpyright 为 0 错误、0 警告。新增验证覆盖配置原子拒绝、带组织路径的模型名、手动能力、MiMo、自有连接池、两个 profile 的地址/密钥/关闭隔离，以及默认装配的工具循环和配置恢复。新增兼容服务和 MiMo 路由通过真实 SDK 与模拟 HTTP 验收，未调用这些供应商的真实接口。
- DeepSeek 流式与非流式真实回归均完成一次本地工具调用、两轮推理和重启恢复；报告位于 `build/profile-provider-regression-20261031/report.json`，快照、日志及事件记录均检查不含运行期密钥。SDK 保留 1 项 Pydantic ReadOnly 提示。

硅基流动的 profile 示例，写入 `org.aurora.model_adapter:state/config`。地址参见[官方 OpenAI 兼容接入说明](https://docs.siliconflow.cn/docs/userguide/quickstart)；将 model 占位符替换为平台上的完整模型 ID，并按该模型能力填写两个布尔值：

```json
{
  "siliconflow": {
    "adapter": "org.aurora.model_adapter:adapters/litellm",
    "provider": "openai",
    "model": "<平台上的完整模型 ID>",
    "base_url": "https://api.siliconflow.cn/v1",
    "credential": "SILICONFLOW_API_KEY",
    "capabilities": {
      "streaming": true,
      "tool_calls": true
    }
  }
}
```

在 `org.aurora.model_adapter:state/bindings` 中以 `{"reasoning":"siliconflow"}` 绑定角色；默认装配在下次启动读取配置。ctx/set 替换整个配置映射，已有其他 profile 时须一起保留。

### M2.8：最小 bot 整体验收通过

验收范围为默认装配、模型协议与适配、ReAct 工具循环、公共运行操作、CLI 观察及关闭恢复。此范围的 M2.8 完成；运行身份沿用 instance_id/run_id，界面消息关联、完整 world/cadence 插件和 TUI/Panel 属于后续范围。

| 验收项 | 证据 | 结果 |
| --- | --- | --- |
| 模型协议与适配 | `tests/contract/test_model_protocol.py`、`test_litellm_adapter.py` | 流式/非流式、完整工具参数、能力拒绝、供应商异常、超时和流关闭通过 |
| 默认装配与运行身份 | `tests/e2e/test_default_assembly.py` | 配置恢复、实例路由、序号拒绝、终态、取消竞态、停止顺序及遗留 running 标记处理通过 |
| ReAct 与工具边界 | `tests/unit/test_react_agent.py`、`test_react_defaults.py`、`test_bot_tools.py` | 六阶段循环、迭代限制、参数拒绝、工具钩子、失败回填及取消后接纳通过 |
| CLI 完整链路 | `tests/e2e/test_default_assembly.py` | 提交→工具→观察→再次推理→唯一终态通过；工具失败/超时作为观察保存，bot 可完成；重启保留观察且不重做动作 |
| 中断与持久化 | CLI SIGINT 子进程、工具取消及重启用例 | Windows 退出码 130、流和工具清理、取消终态落盘通过；显式重启激活接纳取消观察且工具累计执行仅 1 次 |
| 可选宿主缺席 | `tests/e2e/test_m2_acceptance.py` | 独立进程禁止导入 CLI/API，默认 bot 仍完成离线工具往返与快照保存 |
| 真实 DeepSeek 工具往返 | `scripts/accept_m2.py`，`build/m2-acceptance-20261031/report.json` | 流式和非流式各完成 1 次本地工具调用及 2 轮推理，均为 completed；事件、回执和快照终态一致 |

- 完整 `uv run --locked aurora check` 通过：433 项 Python 测试、9 项工具链测试，以及格式、lint、Python/TypeScript 类型与工作区入口检查。验收脚本及改动测试的 basedpyright 为 0 错误、0 警告；SDK 保留 1 项 Pydantic ReadOnly 提示，无失败。本次改动仅涉及验收脚本、测试与记录。
- 离线新增工具失败、工具超时和可选宿主缺席用例，并加强 CLI 工具取消后的重启验证。工具失败不等同于 bot 失败：工具错误作为结构化观察交给下一轮推理，运行可以 completed；模型失败仍以 failed 和退出码 1 收束。
- 真实模型为 `deepseek/deepseek-flash`。流式 run_id 为 `aa82a4a3315d41c4a2c2b06cc4588082`，收到 20 个非空文本增量；非流式 run_id 为 `5414c66da5774761be0360a4e7f929c6`，收到 1 个非空文本增量。工具使用随机标记核对实际执行及结果回填；重启后的消息、bot 配置和模型角色绑定一致。每种模式的 `events.jsonl`、快照和日志位于报告目录下的 `stream`/`complete` 子目录，均检查不含运行期密钥。
- 真实请求仅覆盖正常工具往返；供应商异常、超时、取消和故障恢复由确定性离线测试覆盖，不以真实正常请求代替故障验收。报告与快照保存在 Git 忽略的 build 目录，验收脚本纳入版本管理。

重复真实验收需选择尚不存在的数据目录；此命令会调用所选供应商，凭证由 uv 从根目录 `.env` 加载：

```powershell
uv run --locked --env-file .env python scripts/accept_m2.py --data-dir build/m2-acceptance-rerun
```

脚本默认验证 DeepSeek 的流式与非流式完整链路，可显式指定 `--model`、`--credential-env`、`--base-url` 和每种模式的 `--timeout`；目录已存在时拒绝执行，避免覆盖验收数据。

### M2.7：CLI 引导提交、流式观察与同宿主取消

- `aurora_bot.assembly` 声明 `org.aurora.bot:commands/run/submit`、`run/activate`、`run/cancel` 三个命令，由 CLI 接收。命令经既有公共 operation 调用运行管理器，要求显式 `--instance-id`；bot 仅使用 core 与结构接口，不导入 CLI 实现。CLI 缺席时命令声明保持未连接，进程内运行照常可用。
- submit 接收文本引导和可选 `--sequence`，activate 接纳已有输入。两者逐行输出 JSON：accepted 包含 run_id 和提交回执；run 展示阶段；model 展示内部推理的文本增量、模型执行身份及工具请求；result 在运行清理完成后报告终态。模型增量按 execution_id 区分一次激活内的多次推理，内部推理内容不作为对外消息投递。
- 正常完成、失败、取消的退出码分别为 0、1、130。Ctrl+C 按本次 run_id 发起取消，等待流或工具清理，输出终态并交给宿主关闭资源、保存状态。输出失败也会释放订阅并取消未完成运行。cancel 命令仅操作当前宿主中的匹配运行，返回 cancelled 布尔值；独立新进程不能取消另一宿主的运行，`--connect` 仍只支持 ctx 命令。
- 完整 `uv run --locked aurora check` 通过：430 项 Python 测试、9 项工具链测试，以及格式、lint、Python/TypeScript 类型与工作区入口检查。命令模块、装配和相关测试的 basedpyright 为 0 错误、0 警告。覆盖工具往返、增量提前交付、模型失败、按 ID 取消、工具中断、输出失败清理和配置恢复；独立 Windows 进程验证 SIGINT、退出码 130 与取消终态落盘。SDK 保留 1 项 Pydantic ReadOnly 提示。
- 通过真实 CLI 参数解析、宿主和默认装配调用 `deepseek/deepseek-flash`，收到 4 个非空文本增量，合并为“CLI验收成功”，终态 completed。验收数据位于 `build/cli-smoke-de69eede`；快照与日志均确认不包含运行期密钥。本次真实请求仅验收文本流，工具与取消路径由离线测试覆盖。M2.8 的整体验收继续推进。

PowerShell 下可使用独立数据目录准备最小 DeepSeek 配置；已有配置可直接执行最后一条命令：

```powershell
$botPlugins = @(
  '--plugin', 'aurora_model_adapter',
  '--plugin', 'aurora_agent.model',
  '--plugin', 'aurora_agent.react',
  '--plugin', 'aurora_agent.tools',
  '--plugin', 'aurora_agent.react_defaults',
  '--plugin', 'aurora_bot.assembly'
)
$botData = @('--data-dir', 'build/cli-bot')
uv run --locked aurora @botPlugins @botData ctx set org.aurora.bot:state/config '{"instance_id":"main","model_role":"reasoning","tools":[]}'
uv run --locked aurora @botPlugins @botData ctx set org.aurora.model_adapter:state/config '{"primary":{"adapter":"org.aurora.model_adapter:adapters/litellm","model":"deepseek/deepseek-flash","credential":"DEEPSEEK_API_KEY"}}'
uv run --locked aurora @botPlugins @botData ctx set org.aurora.model_adapter:state/bindings '{"reasoning":"primary"}'
uv run --locked --env-file .env aurora @botPlugins @botData --assembly org.aurora.bot:assemblies/default --namespace org.aurora.bot run submit '只输出：CLI验收成功' --instance-id main
```

将最后一条命令的 `run submit '只输出：CLI验收成功'` 替换为 `run activate`，可显式激活已有输入。`--env-file .env` 仅由 uv 在本次启动时加载环境凭证，ctx 配置只保存变量名。

### bot 公共运行操作 ID

- `aurora_bot.assembly` 在插件发现阶段登记三个 operation：`org.aurora.bot:operations/run/submit`、`org.aurora.bot:operations/run/activate`、`org.aurora.bot:operations/run/cancel`，统一接入 core 的 operations 注册表。CLI `id list` 可在启动装配前枚举这些定义。
- 每次插件构建持有独立的 `org.aurora.bot:services/run_control` 运行分发服务。DefaultAssembly 启动时按 bot 配置的 instance_id 绑定 runtime，停止并完成工具清理后解除自身绑定。相同实例身份禁止覆盖；尚未启动、已解除绑定或未知实例明确报错，不隐式选择默认 bot。服务及 runtime 引用不进入 ctx。
- 所有操作要求显式关键字 `instance_id`。submit 接收 payload 和可选 sequence，返回既有 Submission；activate 返回 RunHandle；cancel 接收 run_id，等待匹配运行的清理并返回布尔值。运行句柄是进程内对象，CLI/API 传输回执时须显式转换，登记 operation 不自动开放远程分发。
- 调用示例：`await invoke_operation(registry, Id("org.aurora.bot:operations/run/cancel"), run_id, instance_id="main")`。提交和激活分别以对应 ID 调用；运行、等待与取消语义由 AgentRuntime 提供。此命名表达 bot 激活，不绑定到尚未确定的 conversation 端点。
- 完整 `uv run --locked aurora check` 通过：423 项 Python 测试、9 项工具链测试，以及格式、lint、Python/TypeScript 类型与工作区入口检查；操作模块、装配和相关测试的 basedpyright 检查为 0 错误、0 警告。新增用例覆盖发现阶段枚举、按 ID 调用、实例选择、重复绑定失败清理、停止拒绝与解绑；SDK 保留 1 项 Pydantic ReadOnly 提示。

### M2.4：单 bot 的激活、引导提交与取消入口

- DefaultAssembly.runtime 提供单一调度所有者 AgentRuntime。宿主启动后可调用 `submit(payload, sequence=...)` 提交 JSON 引导，返回 Submission（sequence、guidance_id、run）；`activate()` 显式激活已有输入或空输入。两者同步返回，不等待推理。普通 ctx 写入和宿主启动不自动触发运行，恢复输入须显式接纳。
- `await receipt.run.wait()` 返回 RunResult（run_id、completed/cancelled/failed、可选错误类型）。取消等待者不取消 bot。活动阶段的提交和重复 activate 共用当前句柄及 run_id；finish 阶段和终态通知期间的输入取得后续激活句柄，等待当前激活完成清理。每次成功激活结束后复查 pending，覆盖结束边界上的输入。
- 引导 ID 自动生成，sequence 缺省取 progress 与 pending 最大序号加一。调用方可显式提供严格递增序号以拒绝重放；重复或过期序号在写入前报错，相同文本使用新序号表示新引导。序号约束沿用恢复的 inbox/progress，运行句柄不持久化。inbox 写入通知期间的同步重入提交明确拒绝，订阅方可调度到下一事件循环轮次。
- `await assembly.runtime.cancel(run_id)` 仅处理匹配的当前或待执行句柄，并等待清理；未知或已完成的身份返回 False。重复取消只发出一次任务取消请求，取消方自身退出不打断 bot 清理。取消待执行激活不取消其前驱。失败或取消停止自动后续激活，尚未消费的输入保留；关联的待执行句柄以 cancelled 或 failed/PreviousRunFailed 收束，下一次显式 activate/submit 可接纳保留输入。
- ReAct 已开始的激活沿用 state/run 的运行身份与唯一终态；尚未执行就取消的句柄仅返回 cancelled，不伪造一次 ReAct 执行。运行期间不能混用 runtime 管理与 `Lifecycle.run(assembly.activate, request)` 显式调度；显式装配与巡检示例仍可自行管理调度所有权。
- 宿主停止时关闭提交入口、请求取消自有激活、等待模型流或工具清理，再关闭工具、模型和最终落盘。取消 close 等待者不取消后台收尾；资源清理未完成时宿主保留资源供重试。失败和取消均不自动重做工具动作，后续激活接纳既有恢复记录。
- `examples/default_bot/main.py` 使用 runtime 提交和等待，`--text` 写入引导，`--activate` 接纳已有输入；启动不带两者时保持空闲。示例仍使用离线 FakeModel，不需要凭证。入口示例：`receipt = assembly.runtime.submit("开始检查")`，随后 `result = await receipt.run.wait()`；运行中通过 `await assembly.runtime.cancel(receipt.run.run_id)` 显式取消。
- 本切片提供进程内运行入口；world/cadence 的完整插件、界面提交关联以及 CLI 交互命令由后续切片接入，不新增未确定的 conversation 端点或公共 operation ID。
- 完整 `uv run --locked aurora check` 通过：419 项 Python 测试、9 项工具链测试，以及格式、lint、Python/TypeScript 类型与工作区入口检查。新增运行管理、装配及相关测试、示例经 basedpyright 检查为 0 错误、0 警告；14 项新增集成用例覆盖提交、序号拒绝、收尾复查、取消与关闭竞态、失败保留、调度所有权和重启恢复。SDK 仍有 1 项 Pydantic ReadOnly 提示。

### DeepSeek 真实模型验收

- LiteLLM 工厂支持 `deepseek/` 模型，通过实例自有 AsyncHTTPHandler 管理连接，默认端点为 `https://api.deepseek.com`，允许显式配置 base_url。请求指定 `thinking={"type":"disabled"}`；当前公共消息协议不保存 reasoning_content，DeepSeek 工具往返使用[官方非思考模式](https://api-docs.deepseek.com/guides/tool_calls/)。
- 真实模型验收入口为 `scripts/accept_m2.py`，通过 TOML profile、默认装配和 CLI 验证流式与完整响应的工具往返；使用独立的新数据目录，凭证从指定环境变量读取。运行方式见 [示例指南](archive/2026-11-09/START.md#真实模型验收)。
- DeepSeek 官方模型列表接口鉴权成功。真实 `deepseek-flash` 流式请求输出“Aurora 连接成功。”；正式 DefaultAssembly 的流式、非流式激活分别完成一次本地 echo 工具调用、观察回填及后续推理，均以 completed 收束并输出“验收成功”。两种装配关闭后重新启动，消息与引导消费位置恢复一致，快照不含运行期密钥。
- 真实验收快照位于忽略目录 `build/deepseek-smoke-5ff05490/{stream,complete}/framework/ctx.json`。本次共执行一次简短文本请求和两次工具往返；真实模型取消与超时未重复调用，相关路径由既有离线测试覆盖。M2.3 的真实模型连接与工具往返已有验收证据，M2 的后续运行入口与 CLI 整体验收继续推进。
- 完整 `uv run --locked aurora check` 通过：405 项 Python 测试、9 项工具链测试，以及格式、lint、Python/TypeScript 类型与工作区入口检查。SDK 的 Pydantic 类型加载产生 1 项 ReadOnly 限定符提示，测试无失败。

### M2.3：LiteLLM 适配与离线验收

- 模型插件登记 `org.aurora.model_adapter:adapters/litellm` 异步工厂，默认装配通过既有模型配置、角色绑定与运行期凭证解析器创建独立实例。插件发现不加载 SDK；供应商 SDK 类型保留在适配模块内。依赖固定在 LiteLLM 1.106 系列，锁文件选择 1.106.6；启用官方 mcp 依赖组以满足该版本工具请求转换的导入依赖，不登记或运行 MCP 插件。
- 本切片支持 `openai/` 模型与 OpenAI 兼容网关、`anthropic/` 模型。实例拥有各自的异步连接池，关闭不影响其他实例；同一实例串行调用，关闭前须收束在途调用。其他供应商明确拒绝。streaming/tool_calls 以 SDK 模型目录为准，未知或未声明的能力不隐式降级；自定义网关的模型名称也须能由该目录解析。
- 文本逐段交付，工具按 index 汇集名称与参数，完整严格 JSON 对象通过验证后才输出 ToolCall。重复工具 ID、非法参数、缺失或无效结束片段明确失败；usage 与 SDK 尾部空片段不作为业务内容。请求中的工具描述、assistant 工具请求和 tool 结果转换为 SDK 格式，不修改调用方输入。
- SDK 请求、读取和关闭错误转换为 ModelError，供应商超时转换为标准 TimeoutError，取消保持 CancelledError。错误摘要只包含异常类型，不复制供应商请求或凭证。响应流在正常结束、提前退出、消费方异常、取消与超时时关闭；宿主最终关闭客户端。SDK 重试与响应缓存显式禁用。
- 离线验收使用真实 LiteLLM/OpenAI SDK 与模拟 HTTP/SSE，覆盖 OpenAI 与 Anthropic 流式响应、工具往返、能力拒绝、参数错误、取消及资源释放；正式 DefaultAssembly 分别验证流式与非流式工具循环、终态、凭证不落盘和重启恢复。
- 真实模型验收入口为 `scripts/accept_m2.py`，通过 TOML profile、默认装配和 CLI 验证流式与完整响应的工具往返；使用独立的新数据目录，凭证从指定环境变量读取。运行方式见 [示例指南](archive/2026-11-09/START.md#真实模型验收)。
- 真实供应商连接尚未执行；本条仅验收适配器与默认装配的离线路径，M2 整体验收仍待真实模型连接及后续运行入口切片。
- 完整 `uv run --locked aurora check` 通过：401 项 Python 测试、9 项工具链测试，以及格式、lint、Python/TypeScript 类型与工作区入口检查。SDK 的 Pydantic 类型加载产生 1 项 ReadOnly 限定符提示，测试无失败；真实连接示例的帮助入口验证通过。

## 2026-10-30

### 持续巡检工作台示例

`examples/live_workshop/main.py` 通过真实 CLI 宿主常驻运行，默认监听 `127.0.0.1:10270`。模拟世界每 8 秒更新一次；示例内 cadence 订阅世界 ctx，空闲时触发 DefaultAssembly 的 ReActAgent。离线 FakeModel 通过 ModelCall 发起巡检工具，再调用报告工具，最后结束本次激活并等待后续任务。无需模型凭证或外部服务。

- 巡检工具连接 Serial、While、Branch、Parallel：初始化计数、逐步递增并判断奇偶、并行计算双倍与平方。临时状态可通过 ctx/watch 观察，执行完成或取消后清理。
- 运行中写入 request 会追加引导，由当前 bot 循环继续接纳；调度所有者串行管理激活。自动巡检在忙碌时跳过，暂停自动巡检仍保持世界更新与远程 CLI 可用。
- 报告以 SQLite 台账持久化，通过 ctx 镜像展示累计数量与最近 10 条结果；成功激活后裁剪旧消息，FakeModel 仅保留最近请求样本。日志写入 `build/live-workshop/logs/aurora.log` 并轮转。
- Ctrl+C 停止服务与订阅，取消并等待调度、世界任务，再关闭工具和模型并保存 ctx。重启保留设置、模型角色绑定、报告和 bot 上下文；已消费的 request 不自动重放，中断的工具结果在下一次激活接纳，不自动重做动作。
- world 来源及 cadence 调度实现在示例目录内；`aurora_world` 插件参与发现。TUI、Panel 与 TS client 尚无完整运行入口，本示例使用已有 Python CLI 和 HTTP/WS 能力。

在仓库根目录打开三个终端。终端一启动宿主，直到 Ctrl+C 才退出；`-l DEBUG` 可观察完整日志，`-d` 可选择独立数据目录：

```powershell
uv run python examples/live_workshop/main.py
# 显式启动及参数示例
uv run python examples/live_workshop/main.py -l DEBUG -d build/workshop-two serve --port 10271
```

终端二持续看报告；watch 仅推送订阅后的变化，已有报告用 get 读取。将 key 换成 `org.aurora.bot:state/run` 可观察 bot 阶段，换成 `org.aurora.control:state/control` 可观察控制组件：

```powershell
uv run aurora --connect http://127.0.0.1:10270 ctx watch --key dev.example.workshop:state/reports
```

终端三读写正在运行的宿主。下面命令按需单独执行，ctx/set 是整项替换；settings 中省略的字段按默认值解释：

```powershell
# 查看状态地址、调度状态及累计报告
uv run aurora --connect http://127.0.0.1:10270 ctx list
uv run aurora --connect http://127.0.0.1:10270 ctx get dev.example.workshop:state/status
uv run aurora --connect http://127.0.0.1:10270 ctx get dev.example.workshop:state/reports

# 暂停自动任务，放慢步骤，便于观察运行中追加引导
uv run aurora --connect http://127.0.0.1:10270 ctx set dev.example.workshop:state/settings '{"automatic":false,"interval":8,"steps":3,"delay":1}'
uv run aurora --connect http://127.0.0.1:10270 ctx set dev.example.workshop:state/request '{"text":"手动巡检","steps":10}'
uv run aurora --connect http://127.0.0.1:10270 ctx set dev.example.workshop:state/request '{"text":"运行中追加检查","steps":2}'

# 让工具失败一次；bot 将失败结果写入报告，宿主继续接受后续任务
uv run aurora --connect http://127.0.0.1:10270 ctx set dev.example.workshop:state/request '{"text":"故障演示","fail":true}'
uv run aurora --connect http://127.0.0.1:10270 ctx set dev.example.workshop:state/request '{"text":"故障后的正常任务","steps":4}'

# 查看模型消息与工具往返；运行状态使用相同 location
uv run aurora --connect http://127.0.0.1:10270 ctx get org.aurora.bot:state/messages --location '{"instance_id":"workshop"}'

# 清除最后一次请求的展示值，不取消已接纳任务
uv run aurora --connect http://127.0.0.1:10270 ctx delete dev.example.workshop:state/request

# 恢复默认自动巡检
uv run aurora --connect http://127.0.0.1:10270 ctx set dev.example.workshop:state/settings '{"automatic":true}'

# 改用更快的离线模型；Ctrl+C 并重新启动宿主后生效
uv run aurora --connect http://127.0.0.1:10270 ctx set org.aurora.model_adapter:state/bindings '{"reasoning":"fast"}'

# 通过示例入口枚举插件定义，不启动常驻服务
uv run python examples/live_workshop/main.py id list
```

`--config '{"automatic":false}'` 可在首次启动时初始化 settings，已保存的 settings 优先；interval 范围为 0.5–3600 秒，delay 为 0–2 秒，steps 为 1–20。默认只开放示例与 bot 的指定状态 key；内部运行状态用于观察，调度输入使用 settings/request，模型选择使用 bindings。

跨进程测试覆盖自动循环与 WS 观察、四类控制组件、真实 CLI 写入、运行中追加引导、失败后继续执行、设置与报告持久化、模型绑定重启生效，以及执行中 SIGINT 后清理与恢复。

完整 `uv run --locked aurora check` 通过：367 项 Python 测试、9 项工具链测试，以及格式、lint、Python/TypeScript 类型与工作区入口检查；示例与新增测试的 basedpyright 检查为 0 错误、0 警告。

### 主动 bot、ReActAgent 与外围环境的设计决策

- 设计以 bot 为中心：外围环境提供感知、执行、持久化与调度条件，尊重 bot 对关注对象、目标推进和行动的选择。没有新用户消息时，bot 仍可推进目标或主动行动；回复消息是可选择的行动，一次激活允许不采取行动就正常结束。
- bot 实例长期存在；一次激活包含可能多次推理与工具执行的 ReAct loop；一次模型或工具调用属于激活内部。激活结束不销毁 bot 的身份、目标及需要保留的状态。安排下一次唤醒、子代理等能力通过工具提供，具体工具随相应切片实现。
- 再次触发表达可能需要重新规划的引导。空闲时启动一次激活；运行中接纳新信息并在后续观察、推理节点调整计划，保留当前运行及已有执行结果。引导不隐含强制取消、重启或创建并发 loop；同一次激活保留 run_id，子调用各自拥有 execution_id。
- world 是独立接入根生命周期的插件，与 bot 执行体系并行工作。world 的插槽接入客观世界的信息来源，例如外部消息、MCP 推送或模拟环境；world 维护相关 ctx 空间，不直接提供供 cadence 接入的执行插槽。
- cadence 订阅选定的 world ctx 地址，按自身策略筛选变化、准备引导并触发连接的 ReActAgent。不同 cadence 可以关注同一世界的不同范围；world 的信息维护不依赖某个 bot 是否关注。world 与 cadence 的联系通过 ctx 数据和订阅表达。
- cadence 提供执行插槽，ReActAgent 提供执行插头；连接握手交换 ctx 地址与可选 schema，执行只传递运行和调用身份。每个 agent 实例由一个调度所有者串行管理激活；运行中通过持续输入接纳引导。ReActAgent 的执行入口等待本次激活收束，调用完成由等待确定。
- 持续输入采用 inbox、progress、runtime 三类地址角色：cadence 写入带标识与顺序的引导；ReActAgent 记录已纳入上下文的位置及当前运行状态。progress 表达已接纳，不代表已完成对应要求。inbox 与消费位置按 agent 实例定位，跨激活保留；单次推理、动作等数据可沿用按 run_id 定位的绑定。保留与裁剪策略由装配明确，不由 core 自动推断。
- ReActAgent 在推理前接纳引导，在结束前检查待处理输入；调度所有者在执行返回后复查输入，覆盖结束边界上的变化。ctx 订阅仅通知后续变更，没有历史回放承诺；需要逐条处理的世界消息应保存可读取的记录，消费方维护位置，不能仅依赖不断覆盖的最新值或瞬时事件。
- 接口草案：org.aurora.agent:handlers/react_agent 为 component，其 /execute 为 hook_handler；沿用 org.aurora.agent:react/{prepare,infer,act,observe,finish,error} 六个 hook_slot。prepare 在每次推理前准备上下文与引导，infer 形成行动或结束决定，act 执行工具，observe 接纳结果，finish 收束本次激活且允许无输出，error 处理失败。阶段连接属于具体 agent 实例，执行顺序由 bot 组件负责。
- 实施顺序：先交付可再次激活、运行中接纳引导的 ReActAgent 最小组件与离线行为验收，再接入基本工具往返、默认装配与恢复、真实模型和 CLI 整体验收。world、cadence 的完整插件、唤醒工具与子代理属于后续切片；阶段入口和持续输入先以显式进程内装配验证。达到本切片验收不代表整个 M2 完成。

### 实现与验证记录

- aurora-world 初始化为 Python 3.12+、Hatchling 构建的独立工作区包，源码位于 packages/aurora_world/src/aurora_world，仅依赖 aurora-core；统一安装包包含 aurora-world，uv workspace/source、覆盖率和 Pyright 路径均接入。aurora.plugins 的 aurora_world entry point 返回同名插件清单，当前不登记世界状态、来源插槽或生命周期处理器，具体行为由后续功能提供。
- 初始化验收通过 uv sync --all-packages、8 项工作区导入/安装依赖测试、Ruff 检查与格式检查、Python 类型检查及插件发现；uv build --package aurora-world 成功构建源码包与 wheel。本次未重跑完整业务测试。

- examples/default_bot/main.py 通过正式 DefaultAssembly 和本地模型/工具工厂演示配置恢复。`uv run python examples/default_bot/main.py --data-dir build/default-demo` 只启动和关闭；增加 `--text "你好"` 明确写入引导并激活一次，`--activate` 使用已有输入激活，`--profile secondary` 在启动前更新并保存模型角色绑定。首次缺失的配置由示例 configure 填入，后续沿用恢复值；工厂、实例和连接每次重新创建。
- M2.2 默认单 bot 装配与实例绑定完成本切片验收。完整 uv run aurora check 通过：363 项 Python 测试、9 项工具链测试及格式、lint、Python/TypeScript 类型和工作区入口检查；真实示例进程覆盖空闲启动、工具往返、切换模型绑定、跨进程上下文恢复及中间值清理。真实供应商连接、会话运行入口、cadence/world 与 CLI 对话不属于本切片，M2 尚未整体完成。

- aurora_bot.assembly 提供 org.aurora.bot:assemblies/default 同步宿主入口及 DefaultAssembly。装配入口只建立生命周期连接；宿主恢复 ctx 并预配置后，prepare 创建独立模型客户端、工具实例及默认 ReAct 连接。start 只开放显式 activate，调用方通过 Lifecycle.run 跟踪根调用，不由启动或普通 ctx 写入隐式触发推理。
- 默认单 bot 配置位于 org.aurora.bot:state/config，必填 instance_id/model_role；tools 选择公开工具 ID、实例身份及 config，max_iterations/tool_timeout/streaming/system_prompt 默认分别为 8/30/true/空串。模型角色引用 aurora_model_adapter 的配置与绑定状态；配置变更在下次宿主启动生效，CLI 的 --config 仍只写 CLI 自身状态，不隐式转写 bot 配置。凭证解析器默认读取指定环境变量，也可由进程内装配注入，解析出的密钥不进入 ctx。
- bot 实例状态分别使用 state/agents（inbox/progress）、state/messages（ReActContext）、state/run（最近运行）与 state/react_work（按 run_id 定位的中间值）；全部在恢复前登记，按稳定 instance_id 分开。恢复出的 running 状态标为 failed/InterruptedRun，不自动创建任务；未完成工具轮次保留到后续显式激活接纳。默认装配清理已消费 inbox 和中间值，保留上下文、消费位置、最近模型输出及 pending 所需工具批次，不裁剪其他实例的数据。
- 关闭按停止接收激活、宿主收束在途调用、逆序关闭工具、关闭模型、最终落盘执行。部分工具创建失败会关闭已创建工具及模型；关闭失败保留资源供宿主重试，已关闭工具不重复关闭。16 项配置测试和 7 项宿主集成测试验证配置拒绝、角色解析、运行期凭证、独立客户端、启动顺序、无自动激活、工具往返、恢复、取消、部分失败、关闭重试与 CLI 宿主入口。

- 模型适配插件登记 state/config 与 state/bindings：前者按名称保存 adapter/model 和可选 base_url/credential，后者将逻辑角色映射到配置名称。credential 只保存运行期凭证引用；api_key 与未知字段拒绝写入。resolve_model 只解析 adapters 注册表中的工厂，不从配置导入模块、不缓存客户端；同一定义可以创建独立实例。
- ToolSpec 可显式提供异步 ToolFactory。工厂接收 ctx、宿主 storage、分配的 instance_id、input/output 地址及工具 JSON 配置，返回 ToolInstance(plug, aclose)。工厂返回前的失败或取消由工厂释放部分资源；成功返回后的资源由装配负责关闭。工具沿用装配分配的身份和工作地址，共享 storage 仍由宿主关闭。

- examples/react_agent/main.py 使用正式 ReActAgent、ReActDefaults、ModelCall 和 ToolExecutor，显式装配本地加法工具与 FakeModel。运行 `uv run python examples/react_agent/main.py --data-dir build/react-demo --guide "保留当前计算进度"` 可观察工具往返和流式期间引导；`--tool-error` 演示失败观察，`--tool-delay 0.2 --timeout 0.01` 演示超时，`--text "无需行动"` 演示无行动结束。同一数据目录重复运行保留上下文与消费位置，Ctrl+C 保存取消状态和待接纳工具结果；示例清理已消费 inbox 与中间值，只保留最近模型输出和恢复所需工具批次。
- 本切片完整 uv run aurora check 通过：339 项 Python 测试、9 项工具链测试及格式、lint、Python/TypeScript 类型和工作区入口检查；4 项新增真实进程测试验证正常/失败/超时工具往返、引导、重启恢复与 SIGINT 后结果接纳。CLI 显式启用 aurora_agent.react、aurora_agent.model、aurora_agent.tools、aurora_agent.react_defaults 可枚举新增组件与端口。真实模型连接未验证；正式默认装配资源、模型工厂与绑定恢复、cadence/world 以及 CLI 对话仍待后续切片，M2 尚未整体完成。

- aurora_agent.react_defaults 提供 ReActDefaults，将 build_prompt、ModelCall、interpret_response、ToolExecutor 与 record_observation 显式连接到 ReActAgent 的 prepare/infer/act/observe 阶段。三个默认处理器以 component 及 /execute 插头登记；模型和工具继续使用各自的组件定义。默认连接要求工作阶段为空，连接失败撤销本次新增连接；客户端仍由宿主持有并关闭。
- 默认上下文以实例级 ReActContext 保存 messages、guidance_sequence 和 pending，消息与引导位置整项提交。prepare 按序接纳输入并准备模型可见工具清单；工具失败观察仍进入下一轮推理。模型文本仅保留为内部上下文，不自动发送给用户；无工具且 stop 可正常结束，length/content_filter 或不一致的结束原因明确失败。
- 工具请求与其全部结果成组回填。中断后的 pending 在下一次激活时接纳已保存结果，其余结果标为 interrupted；不复用其他 turn_id 的输出，不自动重跑动作，也不假定中断时没有副作用。完成的工具结果在 after_call 扩展失败时仍保留，后续工具不继续执行。上下文、inbox 和恢复所需工具记录的裁剪由装配明确。
- 10 项默认阶段测试覆盖成功/失败工具观察、流式期间引导、无行动结束、prepare 去重、取消后的结果接纳、旧批次隔离与不完整模型响应；工具测试共 15 项。完整检查结果与离线示例见下条。

- 工具失败策略：未知工具、参数错误、工具执行异常和超时均作为结构化观察交回 bot，由模型决定后续行动；取消继续传播并等待清理。基础执行器不自动重试动作，扩展处理器故障和装配错误仍明确失败。
- aurora_agent.tools 提供 tools 注册表、ToolSpec 和 ToolExecutor。ToolSpec 将模型可见的名称、描述及参数 schema 关联到组件定义，装配显式连接工具实例；模型只看到已连接工具，同一执行器拒绝重复模型名称。工具以 ExecutionPlug 接入，通过 input 读取完整 ToolCall，在 output 写入 JSON 结果；临时工作地址由执行器清理，持久业务数据另存。
- 工具参数使用 jsonschema 的 Draft 2020-12 校验与本地 referencing Registry，不获取外部 schema；format 仅为注释。批次按 turn_id 关联推理，调用 id 在批次内唯一；按顺序执行并逐个保存结果，before_call 可通过 ToolRejected 拒绝动作，after_call 观察已保存结果。超时覆盖前置处理和工具执行，以及后置处理；同步阻塞和忽略取消的插件不承诺强制抢占。
- 工具批次保留 completed/failed/cancelled 状态与逐项结果；批次 completed 表示处理结束，各项仍可为失败。取消保留已完成结果、标记当前取消及后续未执行项，不消费旧输出。14 项工具测试覆盖连接、参数、结果隔离、拒绝、失败、超时、取消、临时值清理和本地 schema 引用；Ruff 与 Python 类型检查通过。

- aurora_agent.react 插件提供 ReActAgent component、/execute 插头与六个 react 阶段插槽。调用通过显式连接执行，保持同一激活的 run_id，各阶段子调用生成独立 execution_id。prepare/infer 必须连接；infer 经 decision 地址明确选择 act、continue 或 finish；act 要求 act/observe 连接，finish 可无处理器、无对外输出。组件不持有后台任务，不订阅 world；宿主通过 Lifecycle.run 管理根调用。
- inbox、progress、runtime 使用实例级地址；引导包含跨激活严格递增的 sequence、唯一 id 和 payload。prepare 读取 batch 快照并将其纳入可保留的上下文，成功后推进消费位置；失败不确认该批输入，处理器按引导 id 避免重试重复。新输入在下一次 prepare 接纳，finish 开始后的输入保留为 pending，由调度所有者在返回后复查。batch/decision 按运行定位并在收尾时删除，runtime 保留最近激活的 completed/cancelled/failed 状态；其他上下文、模型输出和输入裁剪由装配负责。
- 同一 ReActAgent 实例的重入执行明确拒绝，不改动在途运行；取消传播并等待当前处理器收尾。循环上限、缺少阶段、无效决策与异常输入明确失败；error 处理器失败时同时保留执行和错误处理异常。既有 ModelCall 可直接连接 infer 插槽，由后续阶段处理器将模型结果解释为控制决定。
- 本切片新增 18 项组件行为测试与 3 项离线集成测试。真实宿主、FakeModel、ModelCall 和测试内本地加法工具完成工具往返、流式期间引导、无行动结束、上下文与消费进度恢复、模型/工具失败及资源关闭验证；本地工具仅为测试装配，通用工具组件、默认 ReAct 处理器、正式装配、cadence/world 与真实供应商适配仍待后续实现，不承诺重启透明续跑。
- 完整 uv run aurora check 通过：310 项 Python 测试、9 项工具链测试及格式、lint、Python/TypeScript 类型和工作区入口检查。uv run aurora --plugin aurora_agent.react id list 可列出组件与六个阶段插槽；本切片未连接真实模型。

- bot 的 InstanceStateBinding 使用装配显式指定的固定地址，跨 run_id 共享实例状态；StateBinding 继续按 run_id 定位单次运行数据。ExecutionSlot 可通过 slot_id 指定具名阶段端口，execution_slot_entry 声明接收 ExecutionPlug 的插槽；握手、组件身份校验和调用语义沿用现有执行接口。

- 项目服务端口使用 10270–10279 段；本机 ctx API 默认监听 127.0.0.1:10270，serve 的 --port 可显式覆盖。`uv run aurora -d build/ctx-demo serve` 启动常驻宿主，Ctrl+C 关闭连接、取消订阅并完成状态落盘；可在 serve 前通过 --plugin、--assembly 和 --config 选择业务装配及初始配置。
- CLI 通过 `--connect http://127.0.0.1:10270` 执行 ctx get/list/set/delete/watch，连接模式不构造本地 ctx 或存储，不接受 --data-dir、--plugin、--assembly、--config。默认开放 org.aurora.cli:state/config 的全部业务地址；serve 的 --keys 接收完整状态 ID 的 JSON 数组，显式替换开放列表。该切片服务本机 CLI，拒绝浏览器 Origin 与非本机 Host；浏览器接入、远程部署认证及 TS client 尚待实现。
- HTTP 使用 POST /ctx/get、/ctx/list、/ctx/set、/ctx/delete，参数为 key、location 与 set 的 value，成功响应为 result 信封；错误使用稳定 code/message，不回传校验器内部信息。WS /ctx/watch 接收 key/location 筛选对象，ready 确认订阅后发送保留 org.aurora.core:events/ctx/changed 身份的事件；revision 属于当前宿主 ctx，不承诺连续编号或历史补发。关闭连接即取消订阅，断线显式失败；每连接队列上限 256，溢出报告 slow_consumer 并关闭，重连后需重新读取状态。
- 多终端体验：先启动 serve；第二个终端执行 `uv run aurora --connect http://127.0.0.1:10270 ctx watch`；第三个终端执行 `uv run aurora --connect http://127.0.0.1:10270 ctx set org.aurora.cli:state/config '{"count":1}'`。watch 输出 JSON 变更；ctx get/list 可通过同一连接参数读取运行中宿主的状态。
- HTTP/WS 契约与真实 CLI 进程覆盖读写、精确地址过滤、并行订阅、断线释放、队列溢出、访问拒绝、错误脱敏及 Ctrl+C 后恢复；全量 289 项 Python 测试、Ruff 检查与格式检查、Pyright 类型检查通过。

- aurora_logging 提供显式 configure_logging 入口：root logger 统一接收业务包的标准库日志，RichHandler 输出至 stderr，UTF-8 文件按大小轮转。默认文件级别为 DEBUG、终端级别为 INFO，每个文件 10 MiB，保留 5 份备份；重复配置关闭并替换本包处理器，保留外部处理器，导入包不创建文件或配置日志。日志目录由单进程独占。
- CLI 在插件发现前配置终端日志，在宿主命令参数验证通过后写入 data_dir/logs/aurora.log，覆盖装配工厂和 prepare/start/stop。--level/-l 设置终端日志等级，支持 DEBUG、INFO、WARNING、ERROR、CRITICAL，忽略大小写，默认 INFO；DEBUG 显示完整异常栈，文件始终以独立的 DEBUG 级别保留完整异常栈。帮助、版本及参数错误不创建数据目录，插件发现期间仅输出终端日志。core、bot 与模型适配包直接使用标准库 logging，无需依赖 aurora_logging。
- 日志传播、独立级别、中文与异常落盘、轮转保留、重复配置、配置失败、CLI 输出及生命周期日志验证通过；全量 269 项 Python 测试、Ruff 检查与格式检查、Pyright 类型检查通过。

- 计划、M2 交接、设计文档、公共 ID 目录与示例指南以 4eb4d6e 为实现基线：M0/M1/M2.1 完成，控制与模型组件可用，默认装配、真实适配、对话运行和 ReAct 工具循环仍待实现。文档列出组件定义、实例与调用身份、ctx 数据握手、临时状态清理、模型流与客户端关闭责任，以及当前插件入口和启动命令；公共 ID 目录逐段区分已实现定义与规划入口。
- 文档核对通过 34 个本地链接与 24 项模型/bot 已实现 ID、kind 对照，所列插件目录命令可执行；模型协议、组件身份、控制、ModelCall 和两个相关示例共 45 项测试通过。本轮仅修改文档，未重新运行完整 aurora check。

- 控制组件采用统一层级定义：org.aurora.control:handlers/control 及其 serial、branch、while、parallel 子路径登记为 component，各定义的 /execute 为执行插头，/children 为子组件插槽。component 登记项指向组件类或局部执行函数，提供者由装配显式声明；component_entries 负责生成本插件约定的端口声明，core 仍按完整 ID 与显式 kind 寻址。
- ExecutionPlug 与 ExecutionSlot 显式携带 definition_id，连接使用双方实际端口 ID，并校验执行插头的定义归属；控制器须匹配自身的插槽定义。同一插槽内的子实例标识唯一，避免分支选择歧义。组件定义、执行入口和插槽共用路径层级，不从路径推导运行时父子关系。
- 实例标识默认使用 UUID，可显式指定非空字符串；展示引用采用 definition_id.instance_id，内部保留独立字段，不将复合展示字符串交给 Id 解析。组件多次取得插头保留同一个实例身份，每次子调用继续使用独立 execution_id。控制状态按定义、实例、运行和调用定位，终态后清理；运行期实例不会因恢复快照而自动重建。
- ModelCall 的组件身份为 org.aurora.agent:handlers/model_call，执行入口为其 /execute；aurora_agent.model 插件可通过显式清单或同名 entry point 启用。示例显式登记局部业务组件与提供者，通过 ctx 地址握手交换数据，并使用各组件自己的执行入口。
- 装配使用 ExecutionSlot(Serial.definition_id, hooks, instance_id="root") 与 ExecutionPlug(definition_id, execute, instance_id="worker")，省略 instance_id 时自动分配身份；ModelCall(ctx, client, ...) 采用相同规则。本轮完整 aurora check 通过 256 项 Python 测试、9 项工具链测试及格式/lint/类型检查；安装后的 CLI 能通过两个 bot entry point 展示组件与端口目录。

- bot 的 ModelCall 组件通过连接约定的 ctx 地址读取 ModelRequest，在单一输出位置更新文本、完整工具请求、结束原因和调用状态。取消或失败保留已收到的文本并标记 cancelled/failed，错误继续传播；只关闭单次响应流，ModelClient 由创建它的宿主关闭。同一输出地址须串行调用，业务数据保留策略由装配负责。
- `examples/react_agent/main.py` 演示模型调用、工具观察和运行管理；单次 ModelCall 的流式/完整响应、部分输出和取消语义由 `tests/unit/test_model_call.py` 验证。模型数据使用 TypedDict 表达普通 JSON，运行期资源由宿主管理。

- model_adapter 提供普通 JSON 数据形式的消息、工具定义、完整工具请求、模型请求/响应与流式片段，以及 ModelClient/ModelFactory 协议。complete 返回完整响应；stream 通过 async with 消费文本增量、完整工具请求及唯一结束片段，缺失结束片段明确失败。结束原因区分 stop、tool_calls、length 和 content_filter，不将响应结束等同于业务完成。
- 调用方拥有单次响应流，提前结束、失败、超时或取消均通过上下文收尾；宿主在全部调用结束后关闭 ModelClient。能力不足明确拒绝，不自动降级；配置描述与运行期 api_key 分开，公共数据不包含 SDK 类型。FakeModel 以可配置响应脚本离线验证上述边界，工厂可创建相互独立的实例。
- aurora_model_adapter 插件沿用目录中的 adapters 注册表、model_client 服务及四个模型 schema 身份，可由显式清单或同名 entry point 启用；此切片不包含真实供应商适配、默认绑定恢复或对话提交机制。

- Controller 的 ctx 状态仅覆盖在途调用；完成、失败或取消时通知唯一终态，随后删除本次地址，不累计子调用历史。清理按实例、运行和执行身份精确定位，其他在途调用不受影响；需要历史的订阅者自行收集。业务数据的保留策略由应用负责，core 仍保存完整 ctx 快照。
- control_flow 示例恢复时清理没有在途任务对应的控制状态，收尾时清理中间值和历史结果，仅保存最近一次运行的 completed/result、cancelled 或 failed 记录。循环 100 次的单元用例验证在途控制状态数量有界，连续启动与真实 SIGINT 用例验证最终快照只有一条运行结果。

- 示例按应用放在 examples/core_counter/ 与 examples/control_flow/，入口均为 main.py；examples/START.md 提供安装、启动、参数、预期输出、取消和数据目录说明。控制示例通过循环计数、奇偶分支、并行计算与结果汇总展示四类控制组件，打印真实 ctx 通知；每次启动创建独立运行，结束或取消后由宿主保存快照。

- aurora_control 提供内置控制插件，可通过显式 Plugin 清单或同名 aurora.plugins 入口启用。Serial、Branch、While、Parallel 组件复用 core 的实例连接和单次调用，可相互嵌套；core 不承担业务流程控制。
- 控制连接在握手时交换双方的 ctx 地址描述和可选 schema，由插槽实例的 accept 判断兼容性；描述不同但被接收时记录 warning，无 schema 时允许使用代码约定。执行请求仅携带 run_id、execution_id 和父调用标识，业务输入输出由各组件自行读取和更新 ctx，不通过执行参数或返回值传递。
- StateBinding 将实例业务位置按 run_id 定位；同一运行的重复调用可更新同一位置，需要调用历史的组件自行增加 execution_id 定位。地址不构成写权限边界，也不保证共享业务状态的并发安全。每次子调用生成独立 execution_id，控制完成由等待调用确定，ctx 变化订阅用于观察状态。
- Serial 按 priority 和连接顺序依次等待，失败或取消终止后续调用；Branch 从 ctx 读取条件并选择一个子实例，None 跳过，未知实例报错；While 先判断条件，执行唯一循环体，达到显式上限且仍需继续时失败；Parallel 按显式并发上限运行，失败或取消时取消其他任务并等待清理，再传播异常。
- 当前控制插件登记 org.aurora.control:handlers/control/children（hook_slot）、org.aurora.control:handlers/control/execute（hook_handler）和 org.aurora.control:state/control（state_key）。在途控制状态按实例、运行和调用定位，提供父调用标识及选择或迭代信息；终态通知后删除，不保留调用历史。每次根调用使用新的 ExecutionRequest，不提供重复请求去重或崩溃续跑。
- 根执行可交给 Lifecycle.run 管理；控制组件没有脱离根调用的后台任务，正常关闭完成任务清理与最终状态写入后由宿主持久化。离线用例覆盖地址握手、兼容与拒绝、四类控制行为、嵌套、并发限制、父/子取消、组合结果恢复以及宿主关闭后的清理写入恢复。此切片不包含 ModelClient、ReAct 默认装配或 CLI 对话入口。

- id/list（亦可写作 id list）按完整 ID 排序展示当前定义总表的 ID、kind 与 provider，包含 core 自举、CLI 内置定义及已启用插件声明。命令身份为 org.aurora.cli:commands/id/list，通过命令包自动发现；无需数据目录，不构造 ctx 或启动装配，因此不包含 prepare/start 阶段动态登记的定义。

- 命令可通过 passthrough 的非空帮助文本显式启用参数透传。无自身参数的命令原样接收全部参数，包括 --help；有自身参数的命令只将首个 -- 及后续内容交给执行器，其前参数继续严格解析。执行器或 operation 接收名为 passthrough 的 list[str]，保留顺序、空字符串、含空格参数及分隔符，由命令决定下游转发方式，不拼接 shell 字符串。
- 未声明透传的命令仍拒绝未知参数；透传命令禁止再声明同名 passthrough 参数。check 仅提供既有初筛选项，不启用透传；定位失败项时使用对应工具的精准命令。
- 顶层命令和参数作为整体保留原始 argv，避免消耗叶子命令的 --。core 单次调用包装器的路由参数使用仅限位置参数，允许业务参数使用 target、registry、identity 等名称。

- M1.8 微内核集成验收完成，M1「微内核可用」达到出口条件；下一里程碑为 M2「最小 bot」。验收使用真实组件、JSON 快照、SQLite 存储和 CLI 进程，故障注入仅位于测试夹具。
- tests/e2e/test_m1_shutdown.py 在磁盘 I/O 阻塞时接收 20 个并发调用，并启动关闭：拒绝新工作、等待全部在途写入、执行组件最后写入、保存最新完整快照、关闭存储、关闭 ctx。测试记录实际顺序，检查连续 22 次状态通知，重开后验证全部业务地址与结构化数据。
- tests/e2e/test_m1_cli_process.py 通过已安装入口元数据发现测试插件，在真实 CLI 进程中运行 ctx/watch 并触发 SIGINT；变化按序输出，停止阶段最后写入，进程返回 130，下一进程读取到最终值。组件停止失败和最终落盘失败均返回 1；落盘故障保留上一份正式快照。
- M1 关闭异常覆盖同时包含部分启动清理、禁用可选停止处理器、在途取消、落盘失败保留内存与重试、损坏快照保护；既有生命周期与持久化测试和本轮整体场景共同验证这些边界。
- 本次 aurora-core wheel 在仅安装该包的独立虚拟环境中执行计数器两次，输出 2 和 5；确认 CLI、bot、模型适配和 API 均不可导入，验证 core 外应用无需业务包即可恢复状态。
- M1.8 验收包含 196 项 Python 测试、9 项工具链测试、Pyright basic 及格式/lint/TypeScript/工作区入口检查。ctx 并发语义仍为同一宿主线程内的显式操作；数据目录由单宿主独占，CLI watch 观察当前进程，快照不承诺异常断电时零数据丢失。

- aurora -v/--version 输出已安装 aurora-cli 发行包的版本并立即退出，不发现插件、不创建运行期宿主或存储；版本来源为发行包元数据。

- commands/ 的直接子包通过无参数 plugin() 工厂返回 core Plugin，CLI 按包名排序自动发现并统一登记；下划线开头的内部包不参与发现。包入口仅声明元数据和函数引用，文件、连接及任务在执行或生命周期阶段创建。发现范围为内置命令包，外部 entry point 仍需 --plugin 显式启用。
- 命令必须且只能绑定 operation 完整 ID 或 executor callable。operation 默认要求运行期宿主，返回值以 JSON 输出；executor 默认不启动宿主，接收 CommandContext 与解析后的命名参数，可同步或异步执行，自行输出并返回 None 或 0–255 的整数退出码。CommandContext 提供 root、output、registry 与已接收命令目录。
- executor 通过 runtime=true 声明需要 core 状态操作和生命周期，通过 assembly_argument 指定由宿主消费的 id 类型装配参数。所有执行绑定复用最小调用机制；重复 ID 在执行前拒绝，不完整或不兼容声明不进入可执行命令目录。
- about、check、donk、help、ctx 与 run 各自在包内提供执行绑定和运行需求；commander 按声明选择运行环境，host 只负责装配与生命周期，执行层无需具体命令 ID 白名单。空命令与分组帮助由 CLI 展示基础设施提供，即使 help 命令包缺席仍可查看目录。
- 自包含命令示例：在 packages/aurora_cli/src/aurora_cli/commands/hello/__init__.py 中定义以下内容，即可通过 uv run aurora hello Aurora 执行，无需修改中央分派或登记列表：

```python
from aurora_cli.declarations import CommandContext, command_plugin


def execute(context: CommandContext, name: str) -> int:
    print(f"你好，{name}", file=context.output)
    return 0


def plugin():
    return command_plugin(
        __name__,
        {
            "hello": {
                "help": "打招呼",
                "arguments": [{"name": "name"}],
                "executor": execute,
            }
        },
    )
```

- 验收通过完整 aurora check：190 项 Python 测试、9 项工具链测试，Pyright basic 无错误。覆盖命令包独立新增与移除、外部入口显式启用、同步/异步执行器、自定义退出码、运行期状态恢复、重复 ID 和无效绑定拒绝；安装后的 CLI wheel 在独立环境中完成命令发现与 ctx 调用。

- CLI 分派在选择输出流后显式检查 None；无标准输出的环境须提供 output 文本流，各命令接收非空 TextIO。

- about 与 help 的表格使用 Rich 内置 box.SIMPLE，隐藏外框、保留表头分隔线，不设置隔行变暗。

- about 与 help 直接使用 Rich Table、Text 和 Console，表格展示无需项目级封装；插件帮助内容按字面量渲染。

- CLI 表格采用 Rich Table 原生默认边框、表头和行间样式；banner 使用原生标题，单元格保持字面量文本，重定向输出与文本渲染沿用 Rich 的终端处理。

- CLI 按职责组织为 main（进程入口）、commander（发现和分派）、parsing（参数转换）、declarations（声明接收）、host（运行期装配）与 commands/<name>（命令行为）。内置命令显式汇总，业务操作继续引用 core 公共 ID；旧项目仅提供目录组织和用户可见效果参考。
- help、ctx 和 donk 命令组在未选叶子命令时展示本级帮助；顶层 --help 包含已接收的扩展命令。帮助与项目工具命令不创建 ctx 或存储，长选项要求完整名称。常见错误输出简洁提示，--level DEBUG 显示完整异常。
- about 展示项目标志、介绍、系统与 Python 信息、项目/安装版本、可获得的 Git 提交及链接。--root 指定项目根目录，默认为当前目录；about、donk 和 check 不要求 --data-dir。
- utils.table 使用 Rich 提供中文、多行单元格、边框和终端宽度处理；单元格内容按字面量显示。print_table 面向终端，render_table 返回无 ANSI 控制码的文本，banner 位于表头之上。ctx 的结果及 watch 事件继续输出 JSON。
- donk show 列出根包与全部 Python 工作区成员版本；major/minor/patch 暂按统一版本策略更新这些包的 project.version、内部 >=/== 版本约束，并执行 uv lock。版本不一致、非正式三段版本及不支持的内部约束拒绝升级；文件编辑保留 TOML 注释，写入或锁文件更新失败恢复原始项目文件与 uv.lock。该策略封装于 donk 命令，后续拆分子仓库时可独立调整。
- check 复用 scripts/check.ts；无选项运行完整前后端检查，--lint 选择格式/lint/类型与入口检查，--test 选择 Vitest/Pytest，--coverage 为 Python 测试生成覆盖率并使用 pyproject.toml 的最低阈值。覆盖率阈值采用 20%，可在 tool.coverage.report 中调整。
- --fix 显式启用 Ruff 修复与格式写入，前端格式交给 pnpm format；--unsafe-fixes 需同时指定 --fix，--check 在修复时保持格式预览。测试专用模式拒绝修复选项，检查过程汇总各项失败并返回非零状态。Python 子进程包装在中断时等待工具结束，再将控制权交还文件回滚流程。
- 新增 org.aurora.cli:commands/about、commands/check 与 commands/donk/{show,major,minor,patch} 命令身份；命令参数描述支持仅用于命名选项的 flag 类型。Rich 与 TOML Kit 为 CLI 依赖，pytest-cov 为开发依赖，uv.lock 固定安装版本。
- 使用示例：uv run aurora about；uv run aurora donk show；uv run aurora check --test --coverage。版本变更可通过 uv run aurora --root <项目根目录> donk patch 执行。版本升级验证仅操作临时工作区，当前仓库版本保持 0.1.0。
- 本轮验收包含 182 项 Python 测试、9 项工具链测试、Pyright basic 与完整 aurora check；覆盖率命令、真实 uv.lock 版本更新、锁文件失败回滚、中文表格、项目命令无宿主副作用及原有 CLI 场景均通过。

- M1.7 提供 `aurora` 与 `python -m aurora_cli` 入口。`help`、`ctx` 和 `--help` 展示帮助；状态命令支持 `ctx get/set/delete/list/watch` 或 `ctx/get` 等路径，跨命名空间命令使用完整 ID，短名上下文由 `--namespace` 指定，歧义明确报错。全局选项放在命令之前，运行期命令须显式提供 `--data-dir`。
- CLI 命令表接收普通映射声明：`help` 描述用途，`operation` 引用完整操作 ID，`arguments` 描述参数。参数支持 `name`、`type`、`option`、`required`，类型包括 string、integer、json、id、location；位置参数必填，可选命名参数省略时保留目标函数默认值。接收方拒绝不支持的声明并告警，业务插件无需导入 CLI 类型。
- get/set/delete/list 通过既有 core operation 执行，结果输出 JSON；set 值使用严格 JSON，拒绝重复字段及非有限数。`--location` 使用字符串键值对 JSON，list/watch 省略时不筛选位置，空对象表示全局地址。watch 输出后续变更的逐行 JSON，取消或输出失败时释放订阅。
- `--plugin NAME` 显式启用已安装的 `aurora.plugins` 入口，可重复指定。`run ASSEMBLY_ID` 启动选定装配；其他命令通过 `--assembly ASSEMBLY_ID` 在同一宿主中启动组件。首版装配目标是同步工厂，以关键字接收 registry、ctx、hooks、storage，返回 LifecycleComponent 可迭代对象；工厂负责连接，资源初始化与任务启动放在 prepare/start。
- `Lifecycle.start(configure=...)` 在完整快照恢复后、所有组件 prepare 前应用宿主配置。CLI 的 `--config JSON` 将对象整项写入 `org.aurora.cli:state/config`；省略时保留恢复值。配置失败进入启动清理路径，组件不会开始 prepare。
- run/watch 等待至取消，Ctrl+C 通过生命周期停止组件并完成最终落盘；正常退出码为 0，参数解析错误为 2，运行或收尾失败为 1，正常处理中断为 130。CLI 操作当前进程的宿主，数据目录由该宿主独占；watch 不监听其他进程的快照文件。
- 示例：`uv run aurora --data-dir build/cli-demo ctx set org.aurora.cli:state/config '{"name":"demo"}'`，随后执行 `uv run aurora --data-dir build/cli-demo ctx get org.aurora.cli:state/config` 可读取恢复值；`uv run aurora help` 查看命令目录。
- M1.7 验收通过 172 项 Python 测试、5 项工具链测试及完整 `pnpm check`，Pyright basic 无错误。覆盖跨进程状态恢复、地址过滤、参数拒绝、扩展命令调用、watch 取消和输出故障、启动预配置及 stop 最后写入。本次 wheel 在仅安装 aurora-core 与 aurora-cli 的独立环境中完成控制台入口写入与恢复；下一步为 M1.8 微内核集成验收。

## 2026-10-29

- `aurorabot-ai` 为统一安装发行包，依赖独立的 bot、CLI 和 API 包，间接安装 core 与模型适配层；Python 导入名与公共 ID 保持各包归属。
- `uv sync --all-packages` 与 `pnpm install --frozen-lockfile` 安装工作区依赖，`pnpm check` 经 `scripts/check.ts` 汇总格式、lint、类型检查、Vitest、Python 检查与 TS 工作区入口加载检查。
- `scripts/` 首选 Node/TypeScript 脚本；运行环境为 Node `>=24.15.0 <25`，`.node-version` 指定 24.22.0；检查入口兼容 pnpm 的 JS 启动器和原生可执行文件。
- 统一安装包仅提供依赖装配；命令行与服务入口随对应功能实现。
- core 提供不可变 `Id`、公开定义登记项与唯一总表；批量登记检查通过后统一写入，显式替换要求目标存在。短名仅在明确的命名空间与域中解析，歧义时报错。
- 宿主直接建立注册表目录与九个 core 分类注册表；resources 接收 resource、assembly、contract，并保留原 kind。
- 插件发现使用 `aurora.plugins` entry point group。入口指向无参数工厂，返回同名 `Plugin`；宿主只发现显式启用的入口，同名显式清单优先。必需插件须同时选中，缺失、入口歧义和导入失败明确报错。
- `register_plugins` 收集全部定义后原子登记；定义覆盖仅通过 `DefinitionRegistry.replace` 显式完成，不依赖发现顺序。
- 接收方通过 `rejection_reason` 评估声明，自行决定接口兼容性；登记与插槽关系分别产生 accepted/unconnected/rejected 诊断。缺席 CLI/API 时保留声明并 warning，其他资源仍可寻址；accepted 仅表示声明被接收，不表示实例已连接或执行。
- M0 验收覆盖 ID、原子登记、自举、插件发现、可选宿主诊断和工作区入口；后续 M1 实现 ctx、实例连接及生命周期。
- `tooling/*` 纳入 pnpm workspace，共享配置保留 Vben MIT 授权信息；工具版本通过 catalog 与锁文件管理。TypeScript 采用 6.0 系列以符合 ESLint 解析器的支持范围。
- `pnpm format` 写入 Prettier 格式，`pnpm format:check` 只检查；Markdown 单独维护，Python 虚拟环境、构建产物与缓存不参与前端检查。
- `pnpm lint` 依次执行 Oxlint、ESLint、Stylelint；`pnpm typecheck` 检查根配置、TS 脚本、共享 client 和工具配置包。应用具备源码后应添加自身 tsconfig 和 typecheck 脚本。
- `pnpm test` 执行 Vitest；Web 应用采用 happy-dom，client、TUI、脚本和工具配置采用 Node 测试环境。样式入口覆盖 CSS、SCSS、Vue 的有效输入及未知属性拒绝行为；当前无应用样式文件时允许空匹配。
- 工具链验收通过 5 项 Vitest 测试、37 项 Python 测试、格式/lint/类型检查及冻结锁文件安装。
- 进程内 `EventBus` 提供同步订阅、按类型过滤、取消和关闭；监听器接收独立载荷副本。重入发布按 FIFO 派发，监听器异常记录后继续通知；不保存历史或隐式创建异步任务。
- ctx 采用整项替换，读写与校验均使用独立深拷贝；状态定义通过 `StateKey` 提供可选同步校验器。状态数据须支持独立深拷贝，运行时服务由装配持有引用。
- 状态地址由公共状态 ID 与排序后的业务定位字段组成，精确匹配且无隐式回退；get 缺失抛出 KeyError，delete 缺失返回 False，list 返回已赋值地址并按 ID 与定位排序。list/subscribe 的 location=None 不过滤，空字典选择全局地址。
- 每次成功 set（含同值写入）与实际 delete 产生一个递增修订和变化通知；校验失败不提交，监听器失败不撤销提交。ctx 原语限宿主线程同步执行，跨线程访问明确拒绝，读改写组合不构成事务。
- `install_context` 显式绑定现有六个 ctx 操作 ID 与变化事件；订阅取消和关闭幂等。持久化及运行时资源关闭顺序由后续宿主生命周期接入。
- `aurora_core` 导出 `Id`、`operation`、`hook_handler` 与 `entry_from`；装饰器只附加声明，保留原函数、签名、协程及绑定方法语义。`entry_from` 显式转换登记项，提供者由装配指定；同一函数仅允许一个公共声明，ID 格式复用 `Id` 校验。
- 六个 ctx 操作通过 `@operation` 声明身份；hook handler 通过显式 slot 引用接收方，装饰器不注册、不执行、不判断接口兼容。
- M1.1–M1.2 与函数声明装饰器验收通过 67 项 Python 测试、5 项工具链测试及完整 `pnpm check`。
- Python 使用 Pyright `basic` 模式；配置统一位于 `pyproject.toml` 的 `[tool.pyright]`，覆盖五个包的源码与 `tests/`，按 Python 3.12 和工作区 `.venv` 解析类型及依赖。
- `pnpm typecheck:python` 单独执行 Python 类型检查；`pnpm typecheck` 汇总 Python 与 TypeScript，`pnpm check` 包含两者。Pyright 通过 pnpm catalog 与锁文件固定版本，测试中的非法输入仅使用注明原因的局部诊断忽略。
- ctx 默认将全部状态数据纳入快照，包含完整状态 ID、业务定位与值；函数、注册表和订阅回调不属于状态快照。JSON 数据支持 null、布尔、整数、有限浮点数、字符串、列表及字符串键字典，不可表示的数据明确报错，不静默省略。
- `Context.snapshot()` 在宿主线程复制全部状态；`restore()` 仅在首次写入前执行一次，按当前状态定义完整校验后原子提交，不重放历史事件。缺失定义、重复地址、损坏文件或不支持的格式版本会拒绝恢复并保留源文件。
- `JsonSnapshotStore` 使用版本 1 的 JSON 格式；同目录临时文件写入并 fsync 后，经文件替换提交正式快照。写入失败保留上一份正式快照并清理临时文件；文件由单宿主独占，不承诺进程崩溃或断电时零数据丢失。
- `ContextPersistence.start()` 先恢复再订阅变更，默认以 0.5 秒间隔合并自动落盘，I/O 在后台线程执行。`flush()` 串行保存并继续处理写入期间的新修订；取消调用仍等待在途 I/O 结束，防止旧快照覆盖后续写入。
- 自动落盘失败通过日志与 `last_error` 报告并重试；显式 flush/close 失败向调用方抛出。宿主停止写入来源后调用持久化 close，成功落盘后才释放订阅，最后关闭 ctx；最终落盘失败保留内存及再次 close 的重试能力。
- M1.3 验收通过 97 项 Python 测试、5 项工具链测试及完整 `pnpm check`；命名空间存储目录和宿主生命周期接入继续按后续任务实现。
- M1.4 的数据目录和结构化存储由 core 提供，根目录由宿主显式传入。`DataDirectories` 分配 `namespaces/ns-<namespace>`，保留点分名称并避开 Windows 保留文件名；命名空间与公共 ID 共用语法，分配时拒绝路径重定向或根目录外路径。
- 宿主级文件使用 `framework/ctx.json` 与 `framework/structured.sqlite3`。`StorageService.snapshot_store()` 接入完整 ctx 快照，`directory(namespace)` 提供插件自有文件和数据库目录；不增加存储服务公共 ID，也不从状态 ID 推导文件名。
- `StorageService` 提供按命名空间和字符串键组织的 get/set/delete/keys，值采用严格 JSON 编解码；单次写入或删除以 SQLite 事务提交，失败回滚，缺失读取抛出 KeyError，键按字典序枚举。接口限创建线程同步调用，跨命名空间访问不构成授权检查。
- 存储服务实例由宿主持有，close 幂等释放框架数据库连接；插件自行负责其数据库结构、事务、迁移和连接关闭。结构化数据与插件数据库不强制镜像到 ctx，完整 JSON 快照仅包含 ctx 状态数据。
- M1.4 验收通过 124 项 Python 测试、5 项工具链测试及完整 `pnpm check`，包含路径约束、Windows 保留名称、SQL 回滚、关闭后重开和三类存储组合恢复。
- M1.5 提供 `HookSlot` 与 `HookConnections`。连接显式指定插槽/处理器公共 ID 和各自实例标识，由插槽接收方判断兼容；缺失、重复、声明插槽不符或被拒绝时不建立连接。运行时方法通过 target 显式绑定，公共定义身份不随实例变化。
- `for_slot` 按 priority 从小到大返回连接，同级保持显式 connect 顺序。定义替换不改变既有连接；断开后拒绝新调用，在途工作由拥有它的组件等待或取消。顺序、并行和循环控制由调用方实现，首版不提供 before/after 排序字段。
- `invoke_operation` 仅接受已登记且可调用的 operation；`HookConnections.invoke` 调用一条有效连接。同步函数在宿主线程运行，异步结果直接等待，错误保留原异常类型并补充 hook 实例信息；协程取消向处理器传播，调用方可使用 asyncio.timeout，不能抢占同步阻塞代码。
- `examples/core_counter/main.py` 是仅依赖 core 的独立计数器应用，包含显式插件装配、装饰器声明、实例连接、操作调用、ctx 订阅、JSON 快照与重启恢复。运行方式：`uv run python examples/core_counter/main.py --data-dir build/counter-demo --name visits --amount 1`；同一目录和名称重复执行会继续累计，业务状态按名称区分。
- M1.5 验收通过 141 项 Python 测试、5 项工具链测试及完整 `pnpm check`。本次 core wheel 在仅安装 aurora-core 的独立环境中完成两次运行与状态恢复；示例自行管理启动和收尾，通用生命周期按 M1.6 实现。
- M1.6 提供 `Lifecycle`、`LifecycleComponent` 与 `install_lifecycle_slots`，沿用 prepare/start/stop 三个公共插槽。组件以宿主内唯一的实例标识显式声明依赖，缺失依赖、重复标识和依赖环在启动前拒绝；依赖先 prepare/start，依赖者先 stop，同级遵循显式装配顺序。
- 生命周期先恢复完整 ctx，再执行全部 prepare 和全部 start。启动失败或取消时清理已经尝试 prepare 的组件，包含部分初始化的当前组件；同时发生的启动与收尾错误通过异常组保留。恢复失败不执行最终写入，源快照保持原样。
- `Lifecycle.run` 跟踪宿主接收的调用；停止时拒绝新调用，执行组件的 `stop_accepting`，等待在途调用，超时后请求取消并等待清理。组件自行创建的任务由其 stop 处理器收束。默认超时为 10 秒，分别用于各个异步处理器及在途工作的等待、取消阶段；同步阻塞代码不被抢占。
- 组件 stop 成功后断开涉及该实例的连接；停止或取消收束失败保留尚未停止的依赖、ctx 和存储供重试，成功的 stop 处理器不重复执行。取消 stop 的等待者不会取消宿主收尾，可再次调用 stop 等待结果；收尾失败明确抛出并记录日志。
- 宿主在组件停止后独立执行持久化 close，确保最后的 ctx 写入落盘，再释放连接、存储与 ctx。禁用可选 stop 处理器不取消最终落盘；落盘失败时保留内存和存储，重试成功后才完成关闭。
- `examples/core_counter/main.py` 通过生命周期恢复状态、prepare 装配调用与订阅、run 执行业务、stop 取消订阅及最终落盘。运行命令和按名称累计语义保持稳定。
- M1.6 验收通过 158 项 Python 测试、5 项工具链测试及完整 `pnpm check`，Pyright basic 无错误。覆盖依赖顺序、部分启动失败、取消与超时、停止失败重试、最终写入恢复、可选处理器禁用、落盘失败重试和损坏快照保护；后续进入 M1.7 CLI 基础入口，再执行 M1.8 微内核集成验收。
