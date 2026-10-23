---
order: 6
---

# 独立 Agent 任务

`aurora_agent` 适合由自己的 Python 程序驱动一次任务：提供指令、模型适配器和工具，执行模型与工具交替进行的 ReAct 循环，获取最终结果。它随 `aurorabot-ai` 安装，可以独立于 Bot 的世界、目标与长期记忆使用。

## 先运行离线示例

在仓库中执行 `uv sync --locked --group dev`，将以下内容保存为 Python 文件，再用 `uv run python 文件名.py` 运行。示例模型在本地返回固定回答，不需要模型密钥。

```python
import asyncio

from aurora_agent import (
    Agent, ChatMessage, ModelRequest, ModelResponse, RunRequest,
)


class LocalModel:
    async def complete(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(ChatMessage.assistant("收到：" + request.messages[-1].content))


async def main() -> None:
    agent = Agent(
        instructions="使用中文完成任务。",
        model="local/demo",
        provider=LocalModel(),
    )
    run = agent.create(RunRequest("整理任务"))
    run.append_message("请先给出简短回答。")
    result = await run.run()
    print(result.status, result.output)


asyncio.run(main())
```

接入真实模型时，由适配器将请求转换为供应商协议，并返回模型回复。每次请求显式携带模型身份；核心消息使用 `system / message / assistant / tool`，协议角色的映射由适配器完成。

## 工具与宿主控制

工具提供名称、描述、JSON Schema 参数声明和异步执行方法，再通过 Agent 的 `tools` 参数注入。执行前检查工具可见性和参数；同一轮提出的多个工具调用按顺序执行。完整工具示例和适配契约见仓库 `src/aurora_agent/README.md`。

简单程序可以直接等待 `run.run()`。需要控制节奏时，使用 `run.step()` 每次推进一次模型调用或一个工具调用。通过 `run.snapshot()` 查看消息、待执行调用和结束结果；通过 `run.events()` 并发订阅进度，或在结束后读取已有事件。

运行过程中可以调用 `run.append_message(text)` 追加输入。输入先排队，等当前工具调用全部收到结果后再交付给模型。推理期间收到新消息，即使模型本轮已经给出答案，也会再处理新输入。追加输入不会撤销已经提出的工具调用；若需要阻止行动或要求重新判断，可注入行动前策略。

## 使用限制

- 同一个 Run 同时只允许一个执行驱动者，已结束的 Run 不接受追加输入。
- 默认最多调用模型 32 次、实际执行工具 128 次；上下文限制为规范化消息和工具 JSON 的 100,000 字符，不是模型 token 限制。宿主可以调整限制，模型适配器或自定义装配器负责模型 token 预算。
- `run.cancel()` 请求在当前调用返回后停止，不能撤销已经发生的工具效果。强制中断工具调用或工具报告效果未知时，需要宿主核对，核心不会自动重放。
- 快照和事件仅保存在内存中，不提供崩溃恢复。需要持久记录时，由宿主在行动前和结果返回后保存。
- 模型适配器、长期会话、记忆和跨任务调度由宿主提供。
