# 模块交互 Playground

从仓库根目录启动终端会话：

```bash
uv sync --locked --group dev
uv run aurora playground
```

命令名后的参数直接透传给 Playground，例如 `aurora playground --help` 查看帮助，也支持 `aurora playground -- --tui`。从其他目录启动时使用 `aurora --root /path/to/AuroraBot playground --tui`。该命令需要源码仓库及对应开发依赖，Playground 不随发行包安装；原有 `uv run python -m playground` 入口仍可使用。

默认每个请求返回一行 JSON；终端提示写入 stderr，stdout 只包含响应。空行忽略，输入错误返回结构化错误，会话继续。`Ctrl+D` 结束输入，`Ctrl+C` 中断退出。

## Textual 界面

在交互终端中使用 `--tui`，可同时用 `--module` 选择初始模块：

```bash
uv run aurora playground --tui --module kernel
```

顶部选择模块和操作，左侧编辑参数 JSON，右侧查看结构化结果或切换到“接口说明”查看输入、输出 schema 和示例。输入框只填写操作参数，无需填写 `module`、`operation` 等请求字段；结果始终缩进显示，无需加 `--pretty`。

- 点击“执行”，或按 F5 / Ctrl+Enter 提交；部分终端不区分 Ctrl+Enter，此时使用 F5。
- 点击“载入示例”，或按 Ctrl+R 恢复当前操作的示例参数。
- 按 Tab 切换焦点，按 Ctrl+Q 退出。

选择操作和载入示例不会执行调用。切换模块保留本次会话的状态；执行期间暂时禁用输入与重复提交，错误会显示为 JSON，修改参数后可继续执行。退出时等待已经开始的调用完成并释放会话资源。`--tui` 需要交互终端，管道输入使用默认模式。

## 输入与输出便利功能

用 `--pretty` 将响应缩进为多行，用 `--module` 预先选择模块：

```bash
uv run aurora playground --pretty --module kernel
```

交互时既可以输入完整 JSON 请求，也可以使用简写命令：

```text
list
use kernel
describe
describe increment
increment {"amount":3}
state
kernel.reset {"extension":false}
cli.execute {"argv":["demo","greet","Aurora"]}
help
exit
```

`use` 和 `--module` 只为简写调用选择默认模块；完整 JSON 请求仍显式指定 `module`。未选择模块时，用 `kernel.increment {"amount":3}` 调用，或用 `describe kernel.increment` 查看单项操作。无参数操作可省略参数 JSON。简写请求仍经过相同的输入校验。

真实终端支持 Tab 补全命令、模块和操作名，↑/↓ 调取本次会话历史；历史仅保存在内存中。JSON 对象或数组未闭合时，回车继续输入，闭合后回车提交，也可直接粘贴多行 JSON。提示符显示当前选中的模块。

管道输入保持逐行读取，支持 JSON Lines 和每行一条简写命令；终端编辑功能不会接管管道。需要机器逐行处理响应时不加 `--pretty`，加上后每条响应是多行 JSON，不再是 JSON Lines。`--pretty` 只控制输出格式，不改变管道输入格式。

## 查询和调用

列出可用模块：

```json
{"action":"list"}
```

查看模块操作，或查看单项操作的输入、输出 JSON Schema 和调用示例：

```json
{"action":"describe","module":"kernel"}
{"action":"describe","module":"kernel","operation":"increment"}
```

调用时可省略 `action`（默认 `call`），无参数的操作可省略 `input`：

```json
{"module":"kernel","operation":"increment","input":{"amount":3}}
```

新会话的返回值如下；默认启用双倍增量扩展：

```json
{"ok":true,"module":"kernel","operation":"increment","result":{"value":6}}
```

`kernel` 使用真实内核与内存示例模块，支持 `increment`、`describe`、`notify`、`run`、`state` 和 `reset`。连续调用保留状态；`increment` 只执行增量，`run` 同时发送通知。用下面的请求读取状态、重置为无扩展的计数器，再递增：

```json
{"module":"kernel","operation":"state"}
{"module":"kernel","operation":"reset","input":{"extension":false}}
{"module":"kernel","operation":"increment","input":{"amount":3}}
```

重置后的返回值为 `3`；此时 `run` 不可用，因为没有装配 client。执行 `reset` 并传入 `{"extension":true}` 可重新启用扩展，状态重新从零开始。

`cli` 使用真实参数解析和命令分派，每次调用独立。输入 `argv` 数组，返回 `exit_code`、`stdout`、`stderr` 和结构化业务 `result`：

```json
{"module":"cli","operation":"execute","input":{"argv":["--help"]}}
{"module":"cli","operation":"execute","input":{"argv":["demo","greet","Aurora","--uppercase"]}}
{"module":"cli","operation":"execute","input":{"argv":["demo","forward","--","--version"]}}
```

CLI 只绑定演示命令，不加载个人配置、本机插件或真实 Bot。`ok` 表示 Playground 已完成调用；CLI 命令是否成功由 `exit_code` 表示。参数解析失败也会返回退出码和 stderr，而不会退出交互会话。

退出会话：

```json
{"action":"exit"}
```

## 独立 Agent 交互

`agent` 使用真实 `aurora_agent` 和静默的本地模型、工具替身。无需密钥，先创建 Run，再逐步调用；同一会话可以用不同 `run_id` 保存多个独立任务。

```json
{"action":"describe","module":"agent"}
{"module":"agent","operation":"create","input":{"run_id":"demo","message":"收集事实并汇总。"}}
{"module":"agent","operation":"step"}
{"module":"agent","operation":"append","input":{"message":"请用一句话回答。"}}
{"module":"agent","operation":"step"}
{"module":"agent","operation":"snapshot"}
{"module":"agent","operation":"run"}
```

省略 `run_id` 时使用 `demo`。首次 `step` 由模型提出两个工具调用；第二次 `step` 只执行第一个工具，快照中的 `queued_messages` 仍保留追加输入。`run` 处理剩余调用，再将追加输入交给模型。

各操作返回统一的结构化快照，包括消息、排队输入、工具调用状态、统计与最终结果。`ok` 表示交互操作成功；任务是否完成应查看 `result.status`，最终回答在 `result.result.output`。同一身份不能重复创建，终态不能追加输入，再次执行终态不会重放工具效果。

在步骤边界取消任务：

```json
{"module":"agent","operation":"create","input":{"run_id":"stop"}}
{"module":"agent","operation":"step","input":{"run_id":"stop"}}
{"module":"agent","operation":"cancel","input":{"run_id":"stop"}}
```

`create` 支持 `scenario`：`loop` 为默认工具循环，`answer` 直接回答，`policy` 在行动前要求重新判断，`unknown` 模拟工具效果未知；可通过 `max_model_calls` 和 `max_tool_calls` 调整执行上限。完整字段与输出 schema 通过 `describe` 查询。

交互会话顺序处理每行请求：`run` 返回前不接收另一条 JSON 命令。需要手动追加或取消时使用 `step` 停在边界；模型或工具正在等待时的并发控制见下面的预设场景。所有异步操作复用会话自己的事件循环，`exit`、EOF 或中断时关闭。程序中直接使用 `Session` 时应使用 `with Session() as session`，或显式调用 `close()`；同步会话不能嵌套在运行中的事件循环内。

## 独立 Agent 场景

独立 Agent 的离线场景可运行 `uv run python -m playground.examples.agent`，默认展示完整 ReAct 循环、工具与模型执行期间追加输入、取消、行动前策略和未知效果。可追加 `loop`、`append`、`append-model`、`cancel`、`policy` 或 `unknown` 选择单个场景；`--message` 设置任务，`--extra` 设置追加输入。每个场景输出状态快照与事件记录，详细说明见 `src/aurora_agent/README.md`。

## 边界与扩展

输入按 schema 严格校验，不将字符串或布尔值自动转换为整数，未知字段也会被拒绝。错误响应包含 `error.code`、`message` 和 `details`；校验失败不调用模块。执行异常返回 `execution_error`，已发生的效果不自动回滚或重试。

交互模块按 `modules/<名称>/` 组织，子包的 `__init__.py` 导出唯一 `MODULE: Module`。入口复用内核的 `PackageSource` 自动发现这些声明，新增模块无需修改 `Session`。发现时校验声明类型和模块重名，不调用操作工厂。

```text
playground/
├── __main__.py          # 终端入口
├── protocol.py          # JSON 请求、操作与模块声明
├── discovery.py         # 包发现与声明校验
├── session.py           # 会话状态、协议校验与模块分派
├── commands.py          # 简写转换与当前模块选择
├── terminal.py          # 行编辑、输入输出与格式
├── tui/                 # Textual 界面及会话工作线程
├── modules/
│   ├── agent/
│   │   ├── __init__.py  # Run 操作适配与 MODULE
│   │   ├── models.py    # JSON 输入与快照输出模型
│   │   └── fixtures.py  # 共用的离线模型、工具和策略
│   ├── cli/
│   │   ├── __init__.py  # 操作适配与 MODULE
│   │   └── fixtures.py  # 共用的演示命令声明
│   └── kernel/
│       ├── __init__.py  # 操作适配与 MODULE
│       └── fixtures.py  # 共用的内存模块声明
└── examples/            # 可独立运行的预设场景
```

每个会话在首次查询某模块操作或调用该模块时，调用一次 `MODULE.create()`，绑定独立操作并检查操作重名。工厂只创建适配对象和操作声明，不获取运行资源；资源和宿主在有效调用时按需创建。Kernel 的 `list`、`describe` 和无效输入均不会构造 Host，各会话也不会共享计数状态。模块导入只做声明，不执行示例。

操作处理函数可同步返回输出模型，也可异步返回；会话仅在有效异步操作首次执行时创建 Runner。查询模块和操作说明、输入校验失败都不会分配事件循环。异步模型、工具的输出默认静默，stdout 保持逐行 JSON 协议。

例如新增 `playground/modules/echo/__init__.py`：

```python
from playground.protocol import Model, Module, Operation


class Text(Model):
    text: str


def echo(*, text: str) -> Text:
    return Text(text=text)


def create() -> tuple[Operation, ...]:
    return (Operation("echo", "返回输入文本", Text, Text, echo, {"text": "你好"}),)


MODULE = Module("echo", "文本回显", create)
```

重启 Playground 后，`list` 会包含 `echo`，可用 `describe` 查询示例并调用。输入与输出模型同时用于校验和生成说明；适配函数调用真实公开入口，不解析打印文本来构造业务结果。共享示例声明放在所属模块的 `fixtures.py`，交互模块不导入 `examples/`。通用内核和 Bot 契约不依赖此交互协议。

预设场景脚本仍可单独运行：`uv run python -m playground.examples.kernel` 和 `uv run python -m playground.examples.cli`，用于观察生命周期、事务冲突及临时配置等完整场景。
