# aurora_agent

独立的 ReAct 任务执行核心。Agent 持有指令、模型和工具依赖；每次 `create` 创建隔离的 Run。Run 在模型调用与工具执行之间推进，不包含树、节点、父子关系或委派调度。

包随 `aurorabot-ai` 一起安装，运行时只依赖 Python 标准库、`jsonschema` 和 `referencing`，不导入 Bot 或 CLI。宿主提供模型与工具适配器，不需要创建世界、长期记忆或个人配置。

## Playground

手动创建、逐步推进与追加输入可使用统一 JSON 交互入口：

```bash
uv run python -m playground
```

逐行输入：

```json
{"module":"agent","operation":"create"}
{"module":"agent","operation":"step"}
{"module":"agent","operation":"append","input":{"message":"请简短回答。"}}
{"module":"agent","operation":"run"}
```

还支持 `snapshot` 和 `cancel`，用 `{"action":"describe","module":"agent"}` 查询输入输出 schema。会话按 `run_id` 保存独立任务，并复用同一个事件循环；命令顺序执行，需要交互控制时用 `step` 停在步骤边界。详细用法见 [Playground README](../../playground/README.md)。

在仓库根目录运行，无需模型密钥或个人配置：

```bash
uv sync --locked --group dev
uv run python -m playground.examples.agent
```

默认运行全部离线场景，输出模型可见消息顺序、输入队列、调用状态、结果及事件记录。也可单独运行：

```bash
uv run python -m playground.examples.agent loop
uv run python -m playground.examples.agent append --extra "请用两句话总结。"
uv run python -m playground.examples.agent append-model
uv run python -m playground.examples.agent cancel
uv run python -m playground.examples.agent policy
uv run python -m playground.examples.agent unknown
```

`append` 在工具执行中追加输入，观察整批结果配对后交付；`append-model` 在模型生成回答期间追加输入，观察自动进入下一轮。`cancel` 展示当前工具返回后停止，`policy` 展示行动前要求重新判断，`unknown` 展示未知效果停止且不重放。`--message` 可设置初始任务；模型与工具均为确定性的本地替身，不调用真实模型。

## 最小离线示例

```python
import asyncio

from aurora_agent import (
    Agent,
    ChatMessage,
    ModelRequest,
    ModelResponse,
    RunRequest,
    ToolCall,
    ToolContext,
    ToolDefinition,
    ToolOutput,
)


class Echo:
    definition = ToolDefinition(
        "echo",
        "返回输入",
        {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        },
    )

    async def execute(self, call: ToolCall, context: ToolContext) -> ToolOutput:
        return ToolOutput(str(call.arguments["text"]))


class DemoModel:
    async def complete(self, request: ModelRequest) -> ModelResponse:
        if request.messages[-1].role == "tool":
            return ModelResponse(ChatMessage.assistant(request.messages[-1].content))
        call = ToolCall("echo-1", "echo", {"text": "任务完成"})
        return ModelResponse(ChatMessage.assistant(tool_calls=(call,)))


async def main() -> None:
    agent = Agent(
        instructions="使用工具完成任务。",
        model="demo/model",
        provider=DemoModel(),
        tools=(Echo(),),
    )
    run = agent.create(RunRequest("执行一次任务", run_id="example"))
    run.append_message("请用中文回答。")
    result = await run.run()
    print(result.status, result.output)


asyncio.run(main())
```

## 输入与输出

- `Agent` 接收指令、明确的模型身份、模型端口及工具实例；可替换上下文装配器、行动前策略和运行限制。工具目录在构造时固定。
- `RunRequest` 接收任务、可选运行身份和合法历史。历史不能含系统消息或未配对调用；新的任务消息追加在历史末尾。
- 每次 `ModelRequest` 都包含明确模型身份、四角色消息和固定工具声明。Provider adapter 负责把 `message` 映射为供应商协议角色。无需输出或解析 Thought 文本。
- `RunResult` 包含结束状态、最终回答、结束原因和统计。未完成时没有最终回答；模型已报告的用量累加，未报告的用量不估算。
- `snapshot()` 返回不可变的消息、排队输入、调用记录、计数与结果。工具参数和 schema 也做递归冻结。

## 驱动和追加消息

| 操作 | 语义 |
| --- | --- |
| `agent.create(request)` | 创建 Run，不调用模型、装配器或工具 |
| `await run.step()` | 推进一次模型调用，或处理一个待执行工具调用，返回快照 |
| `await run.run()` | 连续推进至结束，返回结果 |
| `run.append_message(text)` | 排队普通输入；不允许注入 system、assistant 或 tool 消息 |
| `run.cancel()` | 请求协作式取消，阻止后续调用 |
| `run.snapshot()` | 检查当前状态，包括尚未交付的输入 |
| `run.events(after=0)` | 异步订阅进度，游标独立，支持已有事件重放 |

一个 Run 同时只允许一个驱动者。Run 在单个事件循环中使用；宿主可以在模型、装配器、策略或工具等待期间追加消息、读取快照或请求取消。多个 Run 状态独立，注入的模型、工具和装配器对象共享，其并发安全由宿主负责。

追加消息按提交顺序在下一次上下文装配前交付。若有未配对工具调用，必须等整批调用完成，不能插入调用与结果之间，也不会撤销已经提出的工具调用。策略需要重新判断时可以主动结束待执行提案。

推理期间收到新消息时，本轮无工具调用的回答仍保留在历史中，但不会直接结束 Run；下一轮处理新输入。若运行取消、失败或达到上限，尚未交付的消息保留在快照队列中。已结束的 Run 拒绝追加消息。

通过 `step()` 停在步骤边界，再调用 `step()` 或 `run()` 继续，即可由宿主控制推进节奏。终态不可恢复；对终态再次推进只返回已有结果，不重放效果。

## 行动、错误与取消

工具执行前检查目录可见性及 JSON Schema。schema 使用 Draft 2020-12，允许本地引用，不提供外部资源下载；schema 解析失败在工具执行前终止。

`ToolPolicy.before_tool(snapshot, call)` 是可等待的执行决定，不是通知：

- `ALLOW`：允许本次调用。
- `DENY`：写入本次调用的错误结果，继续处理其他待执行调用。
- `RECONSIDER`：将说明作为尚未执行调用的错误结果，全部配对后再次调用模型。

Bot 或其他宿主可以在此接入环境新鲜度、权限和行动记录；需要在效果前完成的持久写入，应由策略或工具适配器等待完成。事件订阅不充当事务提交或阻塞式行动检查。

工具返回 `ToolOutput(is_error=True)` 或抛出 `ToolExecutionError` 表示明确失败，作为结果交给模型。需要向模型解释的具体诊断放入 `ToolOutput`；异常正文不自动写入结果或事件。

`ToolEffectUnknownError` 会保留未知调用并结束 Run。执行中的工具发生未预期异常或驱动任务被强制取消，同样保留未知状态；不自动重放。`cancel()` 是协作式请求，会等待当前调用返回，保留确定结果后停止，不能撤销已发生的效果。需要超时的宿主可使用 asyncio 超时控制，但必须核对被中断的工具效果。

模型适配器的 `ModelError` 和上下文预算错误转为失败结果；未预期异常在保存失败状态后继续向调用者抛出。

## 限制与观察

- 默认最多调用模型 32 次、实际执行工具 128 次。整批工具按顺序执行；达到限制时保留尚未执行的调用。
- 默认上下文限制为规范化消息与工具 JSON 的 100,000 字符，不等同于 token 限制。默认装配器保留完整历史，超限在模型调用前失败。模型 token 限制由 Provider adapter 或自定义装配器检查。
- 自定义 `ContextAssembler` 负责保留必要指令、任务和事实；核心仍验证消息配对与字符预算。装配器不能改变请求的模型身份或可见工具目录。
- 事件只包含进度元数据，不携带正文、工具参数或凭据。宿主如需正文，显式读取快照。事件订阅需要与驱动任务并发运行，或在执行结束后重放；结束时排空已有事件并退出。
- 快照与事件保存在内存中，没有自动持久化、序列化恢复、崩溃恢复或未知效果核对接口。
- 不内置 Provider SDK、长期会话、子 Agent 调度或工具并行执行。宿主可将另一个 Run 包装为工具，并自行承担跨 Run 的预算与取消传播。
