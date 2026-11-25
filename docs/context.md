# 上下文与运行

核对日期：2026-11-11。本页描述当前代码，预算单位是字符或字节，不代表供应商 token。安装助手仅启用普通 ReAct 和终端工具，未启用本页的主动行为。

## 主推理模型的每次输入

按顺序发送：system_prompt、临时 business_context（启用时）、保留的 user / assistant / tool 历史；另附当前已连接工具的全部定义。工具往返中的 assistant 调用、返回及必要的 reasoning_content / thinking_blocks 保留。

临时业务视图不写入消息历史。cadence 引导仅保存本次关注的材料：attend_events 包含未投递事件与环境变化，review_work 包含笔记与行动证据，不复制整个 business 快照。选中材料仍可能与最新视图重叠，以保留投递时的事实。工具结果也会随保留历史重复发送。默认保留完整结果；显式启用下面的上下文管理后，对已归档结果生成有界观察，并消除 MCP 中完全相同的文本与 structuredContent 副本。

业务视图包含近期事件、保留的环境观察、未归档笔记和最近行动证据，按启用类别分配字符预算，优先最新材料。abridged 表示正文截短，omitted 只计当前候选中因预算省略的条目；不是完整归档，也不表示事项已完成。

实现：[ReActDefaults](../packages/aurora_agent/src/aurora_agent/react_defaults.py)、[业务视图](../packages/aurora_bot/src/aurora_bot/context_view.py)。

远程图片链接由供应商读取，QQ 等来源的签名链接可能失效或无法被供应商访问。LiteLLM 适配器仅在 HTTP 400 明确报告 `Failed to download image from`，且地址与当前请求的图片匹配时，将该图片替换为“图片未读取”的文本说明，最多补发一次。有效图片、文字和原始持久历史保持不变，不伪造图片内容，也不改写压缩校验值。

流式调用只有尚未输出有效片段时才允许这一补发；其他错误、部分输出后的失败及第二次失败仍明确返回。每个客户端最多记住 128 个失败地址摘要，后续请求不反复发送它们；缓存只在本进程内有效，重启或淘汰后可重新尝试，重新上传的新地址不受影响。这不恢复已失败的 agent 激活，也不重放工具动作。适配器错误日志仅记录 HTTP 状态与错误类别，不记录图片签名 URL 或供应商正文。

## 输入预算与历史

Bot 的 input_budget 开启后对完整应用层模型请求限制 JSON 文本字符，并限制内嵌文件合计 10 MiB。system、临时视图、工具定义保留；超过预算时从请求中省略较早的完整交流段，至少保留最新交流。当前交流加固定输入仍超限时抛错，不拆断工具调用关系。

单独启用 input_budget 不生成摘要、不压缩工具正文、不删除持久历史。默认不限制一次激活的轮次；有界任务可显式设置正整数 max_iterations，达到该上限仍会报 LoopLimitExceeded。删除既有 TOML 中的该字段才会移除旧上限。模型结束、bot_finish、取消和宿主关闭仍能收束运行；正常结束后由调度所有者等待和接纳下一次输入，不会自动空转推理。供应商传输还可能增加协议包装，字符预算不能替代真实 token 统计。超限日志列出实际所需字符、附件字节、system / view / history / tools / overhead 分项，不打印输入正文。

| 配置 | 包模板默认值 | 安装助手 |
| --- | --- | --- |
| context_view.enabled | true | false |
| context_view.max_chars | 12000 | 未使用 |
| input_budget.enabled | false | true |
| input_budget.max_chars | 128000 | 48000 |
| max_iterations | 省略，不限轮次 | 省略，不限轮次 |

既有用户 TOML 不因模板变化而更新。实现：[ModelInputBudget](../packages/aurora_agent/src/aurora_agent/input_budget.py)。

## 长任务上下文管理

Bot 配置的 `context_management` 默认关闭，开启时必须同时启用 `input_budget` 和 `actions`。摘要串行复用当前聊天模型，会增加模型调用；额外启用记忆插件的 `auto_compaction` 可将压缩材料和摘要保存到长期记忆存储，配置见下文。

```toml
[input_budget]
enabled = true
max_chars = 128000

[actions]
enabled = true
max_chars = 8000

[context_management]
enabled = true
tool_result_chars = 6000
summary_chars = 6000
timeout_seconds = 60.0
```

工具执行先把完整结果写入行动证据，再生成进入上下文的观察。超长结果提供明确的截短预览、原状态、错误码和 `actions_read` 的 run_id/call_id 引用；分页读取原结果，不重跑动作。MCP 文本只有在它是唯一文本块且解码后与 structuredContent 完全相等时才去重，附加说明和非文本内容保留。actions_read 本身直接交付分页，页预算自动不超过 tool_result_chars 减 512，避免把读取工具的结果再次变成读取引用。已有历史中的大结果不会被就地改写。

每次推理前先按 80% 预算尝试省略已结束的旧交流；当前任务仍过长时，在收齐工具批次结果的边界生成续接摘要。至少保留最近两组完整消息（assistant 工具调用及全部返回视为一组），尽量把请求降到 60%；固定系统提示、业务视图、工具定义与最近往返保持完整。摘要保留目标、约束、关键事实、执行结果、未知状态和待办，作为低优先级历史材料注入；它可能遗漏细节，不是执行证据。

摘要源不包含旧的内部思考与签名，附件只提供“未读取附件”的标记；原始消息仍保留，最近往返的思考和签名原样交付。过长源材料按实际 JSON 大小分片，每次摘要请求都受同一硬预算约束，总耗时受 timeout_seconds 限制。返回必须正常结束、无工具调用且符合 summary_chars（JSON 编码长度）限制；失败、超时或取消不提交部分摘要，也不自动重试。

摘要保存于原有 ReActContext 的可选 compaction 字段，记录覆盖位置与历史摘要校验值。旧快照无需迁移，重启可以复用已提交摘要，不自动继续执行或重新调用摘要模型。原消息及交流结束位置不删除；宿主若另行修改已覆盖的历史，必须同步处理 compaction，校验不符会明确拒绝。关闭功能后按原始历史执行原有预算逻辑。

固定输入或最近两组消息本身已超过硬预算时仍会报错，不能保证所有输入都能压缩成功。应减少开放工具、缩小业务视图或分页读取大内容；不要把增加字符预算当作模型 token 上限的保证。实现：[HistoryCompactor](../packages/aurora_agent/src/aurora_agent/compaction.py)、[行动证据与预览](../packages/aurora_bot/src/aurora_bot/action_evidence.py)。

## 压缩时自动保存长期记忆

显式启用 `aurora_bot.memory`、配置 embedding 角色，并在 `config/org.aurora.bot/memory.toml` 中添加：

```toml
[auto_compaction]
enabled = true
index_timeout_seconds = 15.0
retry_seconds = 60.0
```

该功能要求同时启用 context_management。压缩前，同步把本次被压缩的消息、旧摘要、run_id、覆盖范围及历史校验值提交到记忆数据库的 compactions 表；摘要通过预算检查后，先提交待索引摘要，再替换上下文。原始消息不删除，超长工具原文仍通过 actions_read 读取。未触发压缩的对话及仅被省略的已完成交流不会自动写入此队列；需要主动保存的事实仍可使用 memory_write。

宿主持有独立后台索引任务，成功后将摘要发布为 `auto_` 开头的普通记忆，memory_search/read 可检索和读取。供应商失败、超时或取消保留队列，按 retry_seconds 重试；启动会补处理待索引记录，关闭会取消等待并关闭客户端，不续跑旧 agent 或重放工具动作。检索结果中的 pending_index_count 表示尚未发布的摘要数量。本地归档或队列提交失败会阻止提交压缩状态，避免声称已保存却丢失材料。

自动摘要保留来源但不是事实证明，检索不会自动注入每轮输入；Bot 仍按需调用 memory_search。同一历史前缀重复压缩按所有者与校验值去重，已发布后手动编辑或删除不会被后台重新覆盖。删除记忆不清理原始归档或会话副本。记忆数据库从 v1 增量升级到 v2，保留已有记忆、索引与版本；不改公共 ID 和快照。

已索引记忆仍有每实例 1000 条容量上限；满容量时待索引摘要保留，释放容量后继续处理。原始归档与待索引队列不会自动裁剪，长期运行需关注磁盘占用。摘要调用、embedding 与远程故障仍有各自的成本和失败边界，移除轮次上限不等于无限上下文或永不失败。

## cadence 决策

启用 aurora_bot.cadence 后，省略 decision 表时按原样转交世界记录；显式配置 decision 后使用 choice 模型判断。

决策输入包含观察时间、Bot 是否忙碌与 run_id、上次引导时间、业务视图、判断指令和 observe / attend_events / review_work 三个选项。不携带主模型整段对话或工具定义。决策视图预算为 max_chars 减 2048，应用层完整 ChoiceRequest 再检查 max_chars。

```toml
[decision]
model_role = "cadence"
active_seconds = 5.0
idle_seconds = 180.0
half_life_seconds = 60.0
jitter_ratio = 0.2
timeout_seconds = 15.0
max_chars = 12000
```

model_role 必须绑定 choice 适配器；聊天模型适配器不能直接替代。节律受 ctx 活动刺激并随静默衰减，在窗口内随机判断，静默时仍会检查。内部反馈和被动时间刺激逐次衰减，世界事件和环境变化可重新激活。

observe 只更新观察位置，不推进事件投递位置。cadence 比较业务材料与 Bot 忙闲状态的指纹；同一材料在上次成功判断后的 idle_seconds 内不再调用模型，也不写入伪造的决策或推进游标。观察时间、run_id 和被动时钟刷新不使指纹变化；新事件、笔记修订、行动状态、主动时间观察及忙闲变化仍触发重评。达到 idle_seconds 后的下一次节律检查重新判断，保留随时间变化的事项检查能力；它不是准点唤醒，明确的计划继续使用自身控制工具。

Bot 忙碌时仍可接受补充引导；显式忙碌拒绝不缓存此次判断，后续可再次投递。指纹只在当前进程保存，重启会重新评估材料，已有消费游标仍防止事件重复转交。累计消耗仍取决于输入大小、实际材料变化和调用次数。

观察、投递、接纳、运行完成和业务完成是不同状态。改变 cadence 模式应使用独立数据目录，不自动转换既有 checkpoint；错误会暂停自动转交，不靠重启或清空状态掩盖不确定副作用。

实现：[cadence](../packages/aurora_bot/src/aurora_bot/cadence/forwarder.py)、[节律](../packages/aurora_bot/src/aurora_bot/cadence/rhythm.py)。

## 实际模型用量

LiteLLM 客户端每次调用输出一条 `模型用量` INFO 日志，正文为 JSON。purpose 区分 inference（主推理）、summary（任务压缩）、cadence（节律决策）与未标注用途的 chat / choice / embedding；主推理与摘要带 run_id、execution_id，节律决策带独立 decision_id，可据此汇总各类调用。用量不写入业务历史，不随下一次请求重复发送。

tokens 只包含原始 HTTP JSON 或 SSE 中供应商明确报告的非负整数：input_tokens、output_tokens、total_tokens，以及可用的 cached_input_tokens、cache_write_tokens、reasoning_tokens。缺失字段不补零，也不采用 SDK 推算值；完全未报告时 usage_reported=false。流式用量按累计快照更新，不累加重复片段。缓存、思考字段与总量可能重叠，不应再次相加；供应商间 input_tokens 对缓存的包含方式可能不同，应结合各自计费口径解释。

status 区分 completed、failed、cancelled 和 incomplete（响应流提前结束）；失败、取消或不完整响应中的已报告用量仅代表已观测值，不能据缺失记录断言未计费。elapsed_seconds 包含调用耗时。日志不包含消息正文、文件地址、端点或凭证；目前用于观测，不自动按价格换算费用或停止运行。

实现：[用量记录](../packages/aurora_adapter/src/aurora_adapter/model/usage.py)、[原始传输采集](../packages/aurora_adapter/src/aurora_adapter/model/litellm.py)。

## 世界、笔记与证据

世界事件原文持久归档，ctx 只保留近期窗口；环境按来源保留有界观察。world_read_event 按 record_id 分页读取原文，读取不表示消费或处理。QQ 图片事件中的有效图片引用可由 cadence 转为模型图片输入，仍由主模型处理，不自动下载或另开视觉模型。

notes.enabled 提供 notes_write / notes_read / notes_list，笔记按实例隔离并随快照保存。未归档笔记可进入业务视图，记录和引用不证明外部动作成功。

actions.enabled 提供工具调用证据和 actions_read 分页查询。completed / failed 表示工具返回结果，unknown 需要核实，不能视作未执行或要求重试。证据缺失也不能证明动作未发生。

## 长期文本记忆

显式启用 `aurora_bot.memory` 并连接工具后，ReAct 可通过 `memory_write / memory_search / memory_read / memory_delete` 保存和查询长期记忆。原文按字符分块，以 embedding 向量做精确余弦 top-k 检索；本版使用有界 SQLite 语料，不需要额外向量数据库，也不提供重排或自动摘要。配置和重建方法见[显式文本记忆](configuration.md#显式文本记忆朴素-rag)。

记忆与工作笔记独立：工作笔记继续表示当前工作状态，长期记忆只接收显式写入，不自动复制笔记正文。记忆不加入每轮 business_context，由模型按需调用搜索工具；结果含来源、版本和分块字符偏移，需要全文时再读取。相似度不代表事实可信度，检索内容也不具有指令优先级。

写入先生成向量，再在事务内检查版本并提交正文与索引；并发修改、供应商失败或取消不会覆盖已提交版本。删除后不再从记忆库召回，但已进入会话历史的工具结果仍按现有历史保留规则保存。实例隔离用于数据归属，不构成同进程插件权限边界。

## 计划唤醒与自身控制

self_control.enabled 提供 wake_schedule / wake_list / wake_cancel、bot_status、bot_autonomy 与 bot_finish。唤醒只向既有运行所有者提交引导，不创建第二个调度所有者；计划到期不等于业务动作完成。

bot_finish 正常结束当前运行，不暂停 cadence。bot_autonomy(paused=true) 暂停自动引导，包括计划唤醒，直接交流仍可用。恢复后按当前事实判断，不自动重放未完成的外部动作。

工具结果限制、任务摘要和模型用量记录按上述机制工作；完整请求仍按字符约束，尚未提供供应商 token 预算或累计费用熔断。
