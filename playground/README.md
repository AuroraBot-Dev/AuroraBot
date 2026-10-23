# 模块独立工作台

用于在模块接入完整系统前独立装配、控制输入并观察真实行为。公共层负责实例管理、资源释放、校验和记录，模块声明自己的配置、装配与操作。Agent 和 Kernel 共用这套机制；CLI 当前提供无实例的命令调用。

从仓库根目录启动终端会话：

```bash
uv sync --locked --group dev
uv run aurora playground
```

命令名后的参数直接透传给 Playground，例如 `aurora playground --help` 查看帮助，也支持 `aurora playground -- --tui`。从其他目录启动时使用 `aurora --root /path/to/AuroraBot playground --tui`。该命令需要源码仓库及对应开发依赖，Playground 不随发行包安装；原有 `uv run python -m playground` 入口仍可使用。

默认响应缩进显示，并在交互终端中提供 JSON 语法高亮；重定向输出时不写入颜色转义码。添加 `--no-pretty` 输出无颜色的单行紧凑 JSON。终端启动时只显示名称，详细用法通过 `/help` 查询；提示写入 stderr，stdout 只包含响应。空行忽略，输入错误返回结构化错误，会话继续。`Ctrl+D` 结束输入，`Ctrl+C` 中断退出。

## Textual 界面

在交互终端中使用 `--tui`，可同时用 `--module` 选择初始模块：

```bash
uv run aurora playground --tui --module kernel
```

顶部的模块和操作按钮打开可搜索的模态选择框，支持方向键、Enter 确认和 Esc 取消；也可按 Ctrl+K 选择模块、Ctrl+O 选择操作，Ctrl+P 打开命令面板。上方查看结果或“接口说明”，下方编辑输入。JSON 默认缩进并高亮，`--no-pretty` 同时关闭两者。

通常输入框只填写操作参数，无需填写 `module`、`operation` 等请求字段。选择 `cli.execute` 后，输入框直接填写真实命令，例如 `aurora config --missing`。

- 点击“执行”，或按 F5 / Ctrl+Enter 提交；部分终端不区分 Ctrl+Enter，此时使用 F5。
- 按 Ctrl+R 恢复当前操作的示例参数。
- 清空输入后输入 `/`，或按 Ctrl+P 打开命令面板；输入关键词筛选，↑/↓ 选择，Tab / Enter 填入命令，再按 Enter 执行。命令参数可按 Tab 继续补全，Esc 关闭面板。
- 参数编辑时 Tab 切换焦点，Ctrl+Q 退出。

选择操作和载入示例不会执行调用。切换模块保留本次会话的状态；执行期间暂时禁用输入与重复提交，错误会显示为 JSON，修改参数后可继续执行。退出时等待已经开始的调用完成并释放会话资源。`--tui` 需要交互终端，管道输入使用默认模式。

## 输入与输出便利功能

响应默认缩进并在终端高亮，用 `--module` 预先选择模块：

```bash
uv run aurora playground --module kernel
```

交互命令以 `/` 开头，也可输入完整 JSON 请求：

```text
/list
/use kernel
/describe
/describe increment
/increment {"amount":3}
/state
/kernel.reset {"configuration":{"modules":["counter"]}}
/aurora --help
/aurora config --missing
/cli.execute {"argv":["--version"]}
/cli.demo {"argv":["demo","greet","Aurora"]}
/help
/exit
```

`/use` 和 `--module` 只为简写调用选择默认模块；完整 JSON 请求仍显式指定 `module`。未选择模块时，用 `/kernel.increment {"amount":3}` 调用，或用 `/describe kernel.increment` 查看单项操作。无参数操作可省略参数 JSON。简写请求仍经过相同的输入校验。

行终端输入 `/` 自动显示带说明的补全列表，继续输入按前缀或名称片段筛选；`/use ` 和 `/describe ` 可补全模块与操作名。↑/↓ 选择候选，Tab 或 Enter 填入候选，随后 Enter 提交；Esc 取消补全。未打开补全列表时，↑/↓ 调取本次会话历史；历史仅保存在内存中。JSON 对象或数组未闭合时，回车继续输入，闭合后回车提交，也可直接粘贴多行 JSON。提示符显示当前选中的模块。

管道输入保持逐行读取，支持 JSON Lines 和每行一条简写命令；终端编辑功能不会接管管道。需要机器逐行处理响应时添加 `--no-pretty`，输出即为 JSON Lines；默认每条响应是多行 JSON。输出格式不改变管道输入的逐行读取方式。

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

`kernel` 使用真实 Host，支持选择模块组合、通用 `call` 和真实路由观察，也保留 `increment`、`describe`、`notify`、`run` 快捷操作。连续调用保留状态；`increment` 只执行增量，`run` 同时发送通知。用下面的请求读取状态、重置为只装配 counter，再递增：

```json
{"module":"kernel","operation":"state"}
{"module":"kernel","operation":"reset","input":{"configuration":{"modules":["counter"]}}}
{"module":"kernel","operation":"increment","input":{"amount":3}}
```

重置后递增返回 `3`；此时 `run` 不可用，因为没有装配 client。传入 `{"configuration":{"modules":["counter","extension","client"]}}` 重置可恢复完整组合。`inspect` 观察实际模块和调用路由，`export` 与 `replay` 使用公共记录机制；通过 Python 可换入自己的 namespace，见 [Kernel 工作台](modules/kernel/README.md)。

`cli.execute` 通过独立进程执行真实 `aurora` 命令，每次调用独立，读取当前项目的个人配置与 CLI 插件。可以直接输入 `aurora ...`，也可以提供 `argv` 数组或 `command` 字符串，两者必须且只能提供一个：

```json
{"module":"cli","operation":"execute","input":{"argv":["--help"]}}
{"module":"cli","operation":"execute","input":{"command":"aurora config --missing"}}
{"module":"cli","operation":"execute","input":{"argv":["--root","/path/to/project","config","--missing"]}}
```

`/aurora` 与直接输入 `aurora ...` 调用相同的真实 CLI。命令按引号分词，不经过 shell，不展开变量、重定向或管道。项目根目录默认是 Playground 的工作目录，也可通过命令内的顶层 `--root` 指定。命令会产生真实效果，例如配置写入和应用安装；Playground 不会回滚或自动重试。

结果包含 `exit_code`、`stdout`、`stderr`、`result` 和 `timed_out`。`stdout` 整体为有效 JSON 时，`result` 是其解析值，否则为 `null`。`ok` 表示 Playground 已完成调用；CLI 命令是否成功由 `exit_code` 表示。参数解析失败返回退出码和 stderr，会话继续。

命令默认等待 60 秒；通过 `timeout_seconds` 设置 1～3600 秒。超时终止命令，返回退出码 `124`、`timed_out: true` 和已收到的输出；已发生的效果可能保留。标准输入默认立即结束，可用 `stdin` 字符串提供预先准备的输入。命令完成后返回输出，不提供交互式终端或实时输出；需要持续交互的命令应在独立终端运行。

`cli.demo` 显式运行内存演示命令，不读取个人配置或本机插件，例如 `/cli.demo {"argv":["demo","greet","Aurora"]}`。Kernel 的计数器和 Agent 的本地模型、工具仍用于离线观察各自的执行机制。

退出会话：

```json
{"action":"exit"}
```

## Agent 独立工作台

`agent` 驱动真实 `aurora_agent.Run`。使用 `case` 编辑模型响应、工具 schema、回执和行动前策略，不局限于固定 echo 场景；同一会话可以用不同 `run_id` 保存多个独立任务。

```json
{"action":"describe","module":"agent"}
{"module":"agent","operation":"create","input":{"case":{"message":"查询后汇总","replies":[{"tool_calls":[{"call_id":"read-1","name":"read","arguments":{}}]},{"content":"已汇总"}],"tools":[{"name":"read","outcomes":[{"content":"事实"}]}]}}}
{"module":"agent","operation":"step"}
{"module":"agent","operation":"append","input":{"message":"请用一句话回答。"}}
{"module":"agent","operation":"step"}
{"module":"agent","operation":"snapshot"}
{"module":"agent","operation":"run"}
{"module":"agent","operation":"inspect"}
{"module":"agent","operation":"export"}
```

省略 `run_id` 时使用 `demo`。`step` 推进一次模型或工具调用；追加输入在工具调用全部配对后交给模型。`inspect` 显式展示最近的实际模型请求、响应及不含正文的端口轨迹。`reset` 重新装配当前离线配置并清空状态；`export` 显式返回配置、控制操作和检查点，`replay` 在新的运行身份下离线重跑并逐项比对，不覆盖原运行。

各操作返回统一的结构化快照，包括消息、排队输入、工具调用状态、统计与最终结果。`ok` 表示交互操作成功；任务是否完成应查看 `result.status`，最终回答在 `result.result.output`。同一身份不能重复创建，终态不能追加输入，再次执行终态不会重放工具效果。

在步骤边界取消任务：

```json
{"module":"agent","operation":"create","input":{"run_id":"stop"}}
{"module":"agent","operation":"step","input":{"run_id":"stop"}}
{"module":"agent","operation":"cancel","input":{"run_id":"stop"}}
```

不提供 `case` 时，`create` 支持四种快捷预设：`loop`、`answer`、`policy`、`unknown`。完整输入和输出 schema 通过 `describe` 查询。

交互会话顺序处理每行请求：`run` 返回前不接收另一条 JSON 命令。需要手动追加或取消时使用 `step` 停在边界；模型或工具正在等待时的并发控制见下面的预设场景。所有异步操作复用会话自己的事件循环，`exit`、EOF 或中断时关闭。程序中直接使用 `Session` 时应使用 `with Session() as session`，或显式调用 `close()`；同步会话不能嵌套在运行中的事件循环内。

也可以完全不启动交互界面，从文件运行和复现：

```bash
uv run python -m playground.modules.agent playground/modules/agent/cases/tool-loop.json
uv run python -m playground.modules.agent playground/modules/agent/cases/tool-loop.json --record /path/to/record.json
uv run python -m playground.modules.agent --replay /path/to/record.json
```

Python `Workbench` 支持直接注入自己的 Model、Tool、上下文装配器和策略，无需接入 Bot。运行记录含正文，只能显式导出；真实依赖不自动重放。配置、比对结果、资源归属与注入示例见 [Agent 工作台](modules/agent/README.md)。

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
├── workspace/           # 公共实例管理、资源释放、记录和复现
├── commands.py          # 简写转换与当前模块选择
├── terminal.py          # 行编辑、输入输出与格式
├── tui/                 # Textual 界面及会话工作线程
├── modules/
│   ├── agent/
│   │   ├── __init__.py  # Agent 装配、操作和观察声明
│   │   ├── __main__.py  # 独立文件运行与记录比对
│   │   ├── workbench.py # Python 端口注入与元数据观察
│   │   ├── case.py      # 可编辑离线依赖
│   │   ├── records.py   # Agent 专属检查视图
│   │   ├── cases/       # 可复现的离线用例
│   │   ├── models.py    # JSON 输入与快照输出模型
│   │   └── fixtures.py  # 共用的离线模型、工具和策略
│   ├── cli/
│   │   ├── __init__.py  # 操作声明与 MODULE
│   │   └── fixtures.py  # 共用的演示命令声明
│   └── kernel/
│       ├── __init__.py  # 本地快捷操作与 MODULE
│       ├── environment.py # Host 装配、模块选择与路由观察
│       └── fixtures.py  # 共用的内存模块声明
└── examples/            # 可独立运行的预设场景
```

有独立实例的模块通过 `MODULE.workspace` 声明配置、装配上下文管理器、操作与快照；公共工作台负责实例管理、输入校验、重置、资源释放和记录复现。只有在隔离装配中明确允许复现的操作才能重跑，记录不能提升权限。接入说明见 [工作台扩展](workspace/README.md)。

无实例操作仍可通过 `MODULE.create()` 绑定。查询操作说明只读取声明，不获取运行资源；资源和宿主在有效调用时按需创建。Kernel 的 `list`、`describe` 和无效输入均不会构造 Host，各会话也不会共享计数状态。模块导入只做声明，不执行示例。

操作处理函数可同步返回输出模型，也可异步返回；会话仅在有效异步操作首次执行时创建 Runner。查询模块和操作说明、输入校验失败都不会分配事件循环。异步模型、工具的输出默认静默，stdout 只交付 JSON 响应。

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

重启 Playground 后，`/list` 会包含 `echo`，可用 `/describe` 查询示例并调用。输入与输出模型同时用于校验和生成说明；适配函数调用真实公开入口，不解析打印文本来构造业务结果。共享示例声明放在所属模块的 `fixtures.py`，交互模块不导入 `examples/`。通用内核和 Bot 契约不依赖此交互协议。

预设场景脚本仍可单独运行：`uv run python -m playground.examples.kernel` 和 `uv run python -m playground.examples.cli`，用于观察生命周期、事务冲突及临时配置等完整场景。
