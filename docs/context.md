# 上下文与运行

核对基线：W08（2026-11-27）。本页说明模型输入、长期任务和主动行为的可观察语义。预算单位是字符或字节，不代表供应商 token；实际启用哪些能力由[完整装配](configuration.md#选择完整预设)决定。

## 主推理模型的每次输入

模型依次收到 system_prompt、已绑定的临时业务视图、保留的 user / assistant / tool 历史，另附当前已连接工具的定义。工具往返中的调用、返回及必要的 reasoning_content / thinking_blocks 保留。

临时业务视图不写入消息历史。世界视图可包含近期事件、环境观察、未归档笔记和行动证据，按配置限制字符。abridged 表示正文截短，omitted 表示当前候选中因预算省略的条目；二者不表示工作完成或完整归档。cadence 引导保存本次关注的材料，可能与最新视图重叠，保留投递时的事实。

工具返回会随保留历史再次发送。使用动作证据和观察转换资源后，可保留完整原文并向模型提供有界预览；没有连接这些资源时，不会仅凭配置字段自动增加该行为。

远程图片由供应商读取，链接可能失效。LiteLLM 适配器仅在明确的图片下载失败、能匹配当前图片且尚无有效流式输出时，将失败图片替换为未读取说明并补发一次；其他失败正常返回。原始历史不改写，不伪造图片内容，也不重放工具动作。

## 输入预算与历史

输入预算由 agent 的 `input_budget` 资源组件提供，绑定到默认阶段；业务参数位于 `config/org.aurora.agent/input_budget.toml`：

```toml
max_chars = 128000
```

安装助手使用 48000，memory/full 预设显式绑定预算；default/MCP/bot 预设不因配置文件存在而自动启用它。完整请求包含 system、业务视图、工具定义和历史；内嵌文件另有合计 10 MiB 限额。超过预算时省略较早的完整交流段，至少保留最新交流，不拆断工具调用关系。

仅有预算不会生成摘要、压缩工具正文或删除持久历史。最新交流与固定输入仍超限时明确失败；供应商协议包装还可能增加开销。超限日志报告字符与字节分项，不打印正文。

ReAct 的 `config/org.aurora.agent/react.toml` 可设置正整数 `max_iterations`；省略表示不限轮次，达到上限仍会报 LoopLimitExceeded。正常结束、bot_finish、取消和关闭可以收束运行；所有者等待下一次输入，不会自动空转推理。初始化不覆盖用户已有字段。

## 长任务上下文管理

历史压缩由 agent 的 `compaction` 资源组件提供，明确绑定聊天模型与输入预算，再由默认阶段借用。memory/full 预设包含该组合；动作证据与长期记忆归档都是独立资源，不是启用压缩的隐式前提。压缩会增加模型调用。

`config/org.aurora.agent/compaction.toml` 的业务参数：

```toml
tool_result_chars = 6000
summary_chars = 6000
timeout_seconds = 60.0
```

当前任务过长时，在完整工具批次边界生成续接摘要，保留最近的完整往返。固定系统提示、业务视图与工具定义不靠摘要缩减。摘要保留目标、约束、事实、未知状态和待办，作为历史材料使用；它可能遗漏细节，不能替代执行证据。摘要源不包含旧思考与签名，附件只标记为未读取；最近往返仍保留原有思考与签名。

摘要请求受同一字符预算及总超时约束。失败、超时或取消不提交部分摘要，也不自动重试模型调用。已提交摘要随 ReAct 状态保存，恢复时可复用，但不会自动续跑。原消息不删除；若宿主修改已覆盖的历史，须同步处理摘要记录，校验不符会拒绝复用。这里描述的是新基线自身恢复，不承诺旧基线快照兼容。

full 同时启用 `aurora_bot.actions`：执行器先保存完整工具结果，默认阶段借用观察服务生成预览。超长结果包含状态和 `actions_read` 的 run_id/call_id 引用；分页读原文，不重新执行动作。读取工具的结果不再包装成读取引用。MCP 完全相同的单一文本与 structuredContent 可去重，附加说明和非文本内容保留；已有历史不被就地改写。

固定输入或最近往返本身超限仍会失败。应减少开放工具、缩小业务视图或分页读取大内容；增加字符预算不等于提高模型 token 上限。

## 压缩时自动保存长期记忆

`aurora_memory.compaction` 提供 recorder，借用 `aurora_memory` 存储并交给 agent 压缩组件；memory/full 已显式连接。没有 `auto_compaction.enabled` 或 Bot 聚合配置开关。后台索引参数属于装配实例 options，例如以下 **memory/full 中已有实例的局部配置**：

```toml
[instances.memory_recorder.options]
index_timeout_seconds = 15.0
retry_seconds = 60.0
```

压缩先归档覆盖的消息、旧摘要、run_id、范围与校验值；摘要通过检查后提交待索引记录，再替换上下文。原始消息不删除。没有触发压缩的对话及仅被预算省略的交流不会自动写入该队列，显式事实仍可调用 memory_write 保存。

记录器拥有后台索引任务，成功后将摘要发布为普通记忆，memory_search/read 可查询。索引失败保留队列，按 retry_seconds 重试；启动可补处理待索引记录。pending_index_count 表示未发布的摘要数量。本地归档或队列提交失败会阻止提交压缩状态；关闭结束自有任务，不关闭借用的存储或模型，不重放旧 agent 动作。

摘要保留来源但不是事实证明，搜索结果不自动注入每轮输入。同一历史前缀按 owner 与校验值去重，已发布记忆手动修改或删除后不会被后台重新覆盖；删除记忆不清理原始归档或会话副本。

每个 owner 最多 1000 条已索引记忆；满容量时待索引摘要保留，释放容量后继续处理。原始归档与队列不自动裁剪，长期运行需管理磁盘与调用成本。模型身份变更与显式索引重建见[记忆配置](configuration.md#显式文本记忆朴素-rag)。

## cadence 决策

cadence 借用世界记录和唯一运行所有者。省略 `config/org.aurora.bot/cadence.toml` 的 decision 表时，按原样转交世界记录；需要模型判断时，还须在装配中绑定 choice 资源与业务视图。full 已提供这些资源，普通 bot 预设没有 choice 实例。

```toml
[decision]
active_seconds = 5.0
idle_seconds = 180.0
half_life_seconds = 60.0
jitter_ratio = 0.2
timeout_seconds = 15.0
max_chars = 12000
```

不存在 model_role 参数，实际模型来自资源引用。决策输入包含观察时间、忙闲状态、run_id、上次引导时间、业务视图与 observe / attend_events / review_work 选项，不携带主模型全部历史或工具定义。max_chars 限制完整 ChoiceRequest；业务视图有独立 max_chars，须为其他请求字段留出空间，不会自动从视图预算扣除固定值。

节律受 ctx 活动刺激并随静默衰减，在窗口内随机判断。材料与忙闲状态没有变化时，在 idle_seconds 内不重复调用模型；到期后的检查可重新判断，不是准点唤醒。明确计划使用自身控制工具。

observe 只更新观察位置，不推进投递位置。接纳回执也不表示运行或业务已经完成。Bot 忙碌时可接纳补充引导；拒绝接纳不缓存为投递成功。重启可重新评估，但不把未完成外部动作当作可自动重试的工作。改变 cadence 模式应使用独立数据目录，不自动转换旧 checkpoint。

## 实际模型用量

LiteLLM 客户端每次调用输出一条 `模型用量` INFO 日志，正文为 JSON。purpose 区分 inference（主推理）、summary（任务压缩）、cadence（节律决策）与未标注用途的 chat / choice / embedding；主推理与摘要带 run_id、execution_id，节律决策带独立 decision_id，可据此汇总各类调用。用量不写入业务历史，不随下一次请求重复发送。

tokens 只包含原始 HTTP JSON 或 SSE 中供应商明确报告的非负整数：input_tokens、output_tokens、total_tokens，以及可用的 cached_input_tokens、cache_write_tokens、reasoning_tokens。缺失字段不补零，也不采用 SDK 推算值；完全未报告时 usage_reported=false。流式用量按累计快照更新，不累加重复片段。缓存、思考字段与总量可能重叠，不应再次相加；供应商间 input_tokens 对缓存的包含方式可能不同，应结合各自计费口径解释。

status 区分 completed、failed、cancelled 和 incomplete（响应流提前结束）；失败、取消或不完整响应中的已报告用量仅代表已观测值，不能据缺失记录断言未计费。elapsed_seconds 包含调用耗时。日志不包含消息正文、文件地址、端点或凭证；目前用于观测，不自动按价格换算费用或停止运行。

实现：[用量记录](../packages/aurora_model/src/aurora_model/usage.py)、[原始传输采集](../packages/aurora_model/src/aurora_model/litellm.py)。

## 世界、笔记与证据

world records 持久归档事件原文，ctx 只保留近期窗口；sources 管理来源，环境观察有界。`aurora_bot.world_view` 借用记录与可选笔记/证据生成业务视图，提供 world_read_event 分页读原文。读取不表示消费或处理，图片仍由主模型处理，不另开视觉模型。

`aurora_bot.notes` 的服务和工具提供 notes_write/read/list，笔记按绑定的 owner 隔离并随快照保存；未归档笔记可进入已绑定的业务视图。

`aurora_bot.actions` 提供动作证据与 actions_read。completed / failed 表示工具返回结果，unknown 需要核实，不能视作未执行或自动重试的依据；证据缺失也不能证明动作未发生。启用插件后还须在装配中选择组件、状态、资源与工具，旧 notes.enabled/actions.enabled 开关不再存在。

## 长期文本记忆

独立插件 `aurora_memory` 提供 memory_write/search/read/delete/reindex 五个工具。原文按字符分块，以 embedding 做余弦 top-k 检索；当前使用有界 SQLite 存储，无额外向量数据库或重排器。完整配置与索引重建见[配置指南](configuration.md#显式文本记忆朴素-rag)。

工作笔记表示当前工作状态，长期记忆接收显式写入或已连接压缩记录器发布的摘要，不自动复制笔记。记忆不加入每轮业务视图，由模型按需搜索；结果含来源、版本和字符偏移。相似度不代表事实可信度，检索内容不具有指令优先级。

写入先生成向量，再按版本提交正文和索引；并发修改、失败或取消不覆盖已提交版本。删除后不再召回，但已进入会话的工具结果仍按历史规则保存。owner 用于数据归属，不构成同进程权限隔离。

## 计划唤醒与自身控制

`aurora_bot.self_control` 绑定既有运行所有者，提供 wake_schedule/list/cancel、bot_status、bot_autonomy 和 bot_finish。full 显式连接这些工具；计划到期只提交引导，不创建第二个调度所有者，也不代表动作完成。

bot_finish 正常结束当前运行，不暂停 cadence；bot_autonomy(paused=true) 暂停自动引导，包括计划唤醒，直接交流仍可用。恢复后按当前事实判断，不自动重放未完成动作。

模型调用、工具执行、摘要和后台索引分别有自己的失败与成本边界。当前没有供应商 token 总预算或累计费用熔断。
