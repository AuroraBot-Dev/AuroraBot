# Agent 独立工作台

目标是验证 `aurora_agent` 接入 Bot 之前的行为，而不是启动完整应用。认知循环、上下文预算、工具校验、输入交付、取消和终态处理全部由真实 `Run` 执行。

有两种使用方式：

- **离线用例**：用 JSON 替换模型响应、工具回执与行动前策略，适合复现边界问题和回归验证；终端、TUI 和独立文件入口共用装配。
- **Python 装配**：直接注入自己的 Model、Tool、ContextAssembler 和 ToolPolicy，适合检查实际准备接入系统的实现，不依赖 JSON 界面。

## 从文件运行与复现

在仓库根目录执行：

```bash
uv sync --locked --group dev
uv run python -m playground.modules.agent playground/modules/agent/cases/tool-loop.json
```

复制该文件后，可以修改任务、指令、模型身份、每轮响应、工具参数 schema、回执、策略与运行上限，无需修改工作台源码。它不是语言模型：脚本按顺序交付配置的响应，不根据任务自动推理。

显式保存一次运行，再离线重跑并逐检查点比对：

```bash
uv run python -m playground.modules.agent playground/modules/agent/cases/tool-loop.json --record /path/to/record.json
uv run python -m playground.modules.agent --replay /path/to/record.json
```

记录路径须由你指定，父目录须已存在，不覆盖已有文件。记录包括版本、配置、控制操作、各操作后的状态、异常类型和端口轨迹；没有自动保存。文件运行在任务完成时退出 `0`，其他任务状态或输入错误退出 `1`。复现时，比对全部匹配才退出 `0`；因此一个效果未知的失败用例也可以复现成功。

`cases/unknown-effect.json` 用于观察效果未知时停止、保留回执状态且不自动重试。这里的写入是本地替身，不产生真实外部效果。

## 终端或 TUI 中逐步检查

```bash
uv run aurora playground --module agent
uv run aurora playground --tui --module agent
```

`create` 的示例参数就是可编辑的离线用例。例如输入：

```text
/create {"case":{"message":"查询后汇总","replies":[{"tool_calls":[{"call_id":"read-1","name":"read","arguments":{}}]},{"content":"已汇总"}],"tools":[{"name":"read","outcomes":[{"content":"事实"}]}]}}
/step
/inspect
/append {"message":"补充条件"}
/step
/snapshot
/run
/inspect
/export
```

- `snapshot` 是模块自己的状态投影，包括消息配对、排队输入、工具回执、统计与终态。
- `inspect` 显式展示最近一次实际发给模型的完整请求及响应，以及上下文装配、模型、策略和工具的调用轨迹。模型请求包含系统消息及工具目录，可用于检查实际装配结果；不是根据输入配置猜测的请求。
- 轨迹只有顺序、边界、阶段、名称、调用身份、策略决定和异常类型，不含 Prompt、消息正文、工具参数或异常正文。
- `reset` 用相同配置重新创建 Run 和所有离线依赖，清空游标、状态、检查点和轨迹，不影响其他 `run_id`。
- `export` 返回记录对象；保存响应的 **`result` 字段**，即可用于独立入口的 `--replay`。
- `replay` 接受 `{"run_id":"replay","archive":记录对象}`，使用一个未占用的新身份，不覆盖原运行。返回 `matched` 和差异位置，例如 `checkpoints[0]`、`trace`；复现后的运行也可继续 `inspect`。

查询 `/describe create` 和 `/describe replay` 可获得完整 schema。未提供 `case` 时，`create` 提供 `loop`、`answer`、`policy`、`unknown` 四种快捷预设；`case` 与非默认预设参数不能混用。

终端和 TUI 顺序执行请求；`run` 返回前不能同时发送追加输入或取消请求。手工控制用 `step`；执行期间的并发控制使用下面的 Python 入口。

## 离线依赖的行为

用例版本是 `aurora.agent.case/v1`；运行记录使用公共格式 `aurora.playground.record/v1`，同时保存模块名称与模块声明版本。不支持的版本直接拒绝，不猜测如何解释。检查点保存操作名称、输入、输出、状态和异常类型；复现只忽略宿主分配的运行身份，不改写正文或工具参数里的同名字段。

- `replies` 按模型调用次数消耗；`error: true` 或响应耗尽产生 `ModelError`。
- 每个工具的 `outcomes` 独立按实际执行次数消耗；参数不合法或被策略拦截时不消耗回执。
- `effect: success` 返回配置的正文及 `is_error`；`error` 表示工具确认失败；`unknown` 表示效果无法确认，运行停止。工具回执耗尽视为确认失败。
- `decisions` 在行动前按顺序消耗，可设 `allow`、`deny`、`reconsider`；拒绝和重新判断必须提供说明，列表耗尽后允许执行。
- 模型可以提出不存在的工具或不符合 schema 的参数，由真实 Run 校验；工作台不提前替模块修正输入。

工具 schema 及用例结构在装配前校验；JSON 不加载任意 Python 路径，不读取个人配置，也不连接网络。用例与人工检查、自动测试使用同一装配入口。

## 注入自己的实现

Python 入口不限制为脚本模型，也不需要声明 JSON 操作。下面的装配函数接受你自己的端口实现：

```python
from collections.abc import Iterable

from aurora_agent import ContextAssembler, Model, RunLimits, RunRequest, Tool, ToolPolicy
from playground.modules.agent.workbench import Workbench


def build(
    provider: Model,
    tools: Iterable[Tool],
    *,
    assembler: ContextAssembler | None = None,
    policy: ToolPolicy | None = None,
) -> Workbench:
    return Workbench(
        RunRequest("需要验证的任务", run_id="local-check"),
        instructions="任务约束",
        model="your-provider/your-model",
        provider=provider,
        tools=tools,
        assembler=assembler,
        policy=policy,
        limits=RunLimits(max_model_calls=8, max_tool_calls=16),
    )
```

在宿主自己的事件循环内执行 `await bench.run.step()` 或 `await bench.run.run()`；通过 `bench.run.snapshot()` 读取只读状态，通过 `bench.probe.request`、`bench.probe.response` 显式检查最近一次模型输入输出，通过 `bench.probe.trace` 观察端口边界。

需要观察执行中的追加输入或取消时，用 `asyncio.create_task(bench.run.run())` 启动驱动，再由宿主在明确的信号边界调用 `bench.run.append_message(...)` 或 `bench.run.cancel()`，最后等待驱动结束。事件流直接使用 `bench.run.events()`。同一个 Run 只能有一个推进者，工作台不另写调度循环。

自定义依赖的连接、文件和后台资源由注入方创建并释放，工作台不猜测其关闭方法。真实工具可能产生外部效果，取消不撤销效果；Python 装配不提供自动导出或自动重放。先用可控替身定位问题，再决定是否执行真实依赖。

## 数据边界

`inspect`、快照和显式导出的记录含有你输入的正文、指令、工具参数与结果，只用于本机检查。提交用例前请替换为最小化的合成数据；不要提交密钥或真实会话。端口轨迹不记录这些正文，也不将异常正文写入日志。

复现不是进程恢复，也不续跑原工具调用。它重新构造离线依赖并重新运行控制序列；不会加载真实 Provider 或自动执行真实工具。修改记录中的配置后，旧检查点可能不再匹配，这正是回归比对要揭示的差异。
