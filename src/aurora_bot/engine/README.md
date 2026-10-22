# Bot 认知接线

Bot 使用 `aurora_agent.Agent` 创建独立 Run。模型调用、消息配对、运行预算、追加输入和取消由 `aurora_agent` 负责；Bot 为一次运行连接世界、记忆、工具和 kernel hook。

没有树、节点、父子 Agent 或内建委派调度。不同运行通过明确的运行身份和世界因果关联连接。

## 模块边界

- `runtime.py`：创建并驱动 Run，管理活动运行，等待最终记录完成。
- `session.py`：适配模型、上下文和行动前策略；保存本次运行的证据归属。
- `ledger.py`：声明并追加世界事实，推进观察前沿，封口工具请求并保存结果。
- `hooks.py`：认知入口及步骤、工具通知。
- `module.py`：将选中的服务接入共享宿主，发布实际使用的过程定义。

`RunSession` 是单次运行的局部对象。消息、输出、观察前沿和工具状态不放进全局 ctx；模块共享配置和服务由宿主 ctx 保存。并发 Run 共享注入服务，服务自身负责并发访问。

## 调用与扩展

调用点的完整前缀是 `aurora:kernel/module/`，实现首参是通用 `Context`。

| 调用点                                     | 模式   | 参数与结果                                                   |
| ------------------------------------------ | ------ | ------------------------------------------------------------ |
| `engine:execute`                           | single | `(request, *, observer=None)` → `aurora_agent.RunResult`     |
| `agents:get`                               | single | `(definition_id)` → 本次选用的 Agent 原型                    |
| `memory:recall`                            | single | `(request)` → 记忆快照或 `None`                              |
| `prompt:assemble`                          | single | `(prompt_id, messages, *, memory, tools)` → 上下文及实际来源 |
| `ai:resolve_endpoint`                      | single | `(model_id)` → 固定版本的模型端点                            |
| `ai:complete`                              | single | `(request)` → assistant 消息                                 |
| `tools:definitions_for`                    | single | `(visible_names)` → 可见工具定义                             |
| `tools:scopes_for`                         | single | `(call)` → 观察与发布范围                                    |
| `tools:execute`                            | single | `(call)` → 工具结果                                          |
| `engine:before_step` / `engine:after_step` | notify | `(snapshot)`                                                 |
| `engine:before_tool`                       | notify | `(run_id, call)`                                             |
| `engine:after_tool`                        | notify | `(run_id, call, output)`                                     |

默认实现优先级为 0。普通 namespace 可以通过更高优先级实现替换调用点，无需登记 Python 契约类型：

```python
from aurora_bot.contracts import ChatMessage
from aurora_kernel import namespace


@namespace("example.reasoning", requires=("aurora:kernel/module/ai",))
def plugin(ctx):
    ctx["example.reasoning"]["requests"] = 0


@plugin.hook("aurora:kernel/module/ai:complete", priority=10)
async def complete(ctx, request):
    with ctx.transaction() as staged:
        staged["example.reasoning"]["requests"] += 1
    return ChatMessage.assistant("已通过自定义推理入口处理。")


MODULE = plugin
```

将文件放在 `extensions/plugins/` 后重启。回调中再次调用同一个调用点会递归进入自己；需要包装原模型时，在初始化时保存选中模型的调用函数，或直接使用 `ctx["bot.services"]["ai"].complete(request)`。

Bot 的终端、节律和时钟都通过 `engine:execute` 进入认知。外部输入应先提交世界，再传递对应的因果身份；`AuroraRuntime.run()` 与 `run_from_event()` 已完成这一过程。单独使用 ReAct 时直接使用 `aurora_agent`，无需创建 Bot 世界或这些调用点。

## 持久行为

- 运行开始写入 `{run_id}:run:started`，包含主体、原型、过程版本、触发事实及本次执行标识。相同运行 ID 不能再次执行；并发争用也不能变成两次模型调用。
- 模型请求先保存实际端点、工具版本和记忆曝光，再调用模型。证据按消息位置或工具调用 ID 关联，不从正文中猜测来源。
- 行动前读取相关世界增量。需要重新理解时，通过 Agent 的 `RECONSIDER` 决定配对尚未执行的工具调用，再进入下一次推理。
- 工具批次的请求记录先于效果。每一步返回之后等待结果记录完成，之后才通知观察者或推进下一步。
- 成功、明确失败与未知效果分别记录。未知效果结束当前 Run，不自动重试。重复取消会等待已确认结果和结束记录落盘。
- 最终输出和 `{run_id}:run:finished` 在终态观察者之前提交；后置 hook 失败不能撤销已经提交的结果。

世界、模型端点、工具定义与领域操作仍使用必要的数据校验和版本记录。这些数据格式不参与按 Python 类型选择模块。

## 配置

`config/engine.toml`：

```toml
[engine.run]
max_model_calls = 32
max_tool_calls = 128
max_context_chars = 100000
```

模型与工具调用分别计数。字符预算覆盖实际模型消息和工具 schema，不等同于 token 限制。上下文装配器仍负责保留必要身份、任务和恢复依据。

Agent 配置只声明身份、说明、提示词、模型和可见工具。内置工具 `world_runs` 查询独立运行的活动摘要；当前没有内置 Agent 委派工具。
