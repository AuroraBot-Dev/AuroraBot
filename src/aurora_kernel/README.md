# aurora_kernel

通用 Python 模块宿主：通过 **namespace、hook、共享 ctx、依赖解析和生命周期**组合功能。它不依赖 Bot 或 CLI，由宿主决定装配哪些模块、提供哪些调用点，以及何时调用。

## 与 Bot、ReAct 的关系

| 层                  | 负责什么                                                |
| ------------------- | ------------------------------------------------------- |
| `aurora_kernel`     | 通用声明、发现、装配、调用路由、上下文与资源生命周期    |
| `aurora_bot.kernel` | 把 Bot 的命名服务、贡献、资源和世界域声明适配到通用宿主 |
| `aurora_bot.engine` | 为独立 Agent Run 连接记忆、上下文、模型、工具与世界记录 |

**内核提供扩展机制，领域模块定义扩展点和执行语义。** `@module.hook(target)` 只是注册实现；必须有调用方显式执行 `ctx.call(target, ...)` 或 `await ctx.acall(target, ...)`，实现才会运行。

Bot 的认知接线通过共享宿主调用记忆、上下文、模型和工具模块，并提供步骤与工具通知。ReAct 执行由独立的 `aurora_agent` 负责，各领域模块定义自己的调用点，通用内核负责注册与优先级选择。具体接口与边界见 [engine README](../aurora_bot/engine/README.md)。

`PREPARE / RUN / CLOSE` 等是**模块宿主的生命周期阶段**，不会自动成为每轮推理或每次工具执行的前后置回调。hook 也不会自动获得 Bot 工具授权或生成世界事件。

## 先运行 Playground

在仓库根目录执行：

```bash
uv sync --locked --group dev
uv run python -m playground
```

每行输入一个 JSON 对象，查询操作格式、调用真实内核并取得结构化结果：

```json
{"action":"describe","module":"kernel"}
{"module":"kernel","operation":"increment","input":{"amount":3}}
{"module":"kernel","operation":"state"}
{"module":"kernel","operation":"reset","input":{"extension":false}}
{"action":"exit"}
```

状态保留至重置或退出；默认扩展将增量乘以 2。输入与输出 schema、调用示例由 `describe` 返回，完整协议见 [Playground 说明](../../playground/README.md)。

也可以运行预设场景：

```bash
uv run python -m playground.examples.kernel hooks --amount 5
uv run python -m playground.examples.kernel context
uv run python -m playground.examples.kernel lifecycle
uv run python -m playground.examples.kernel lifecycle --fail-run
uv run python -m playground.examples.kernel validation
```

[Playground 源码](../../playground/examples/kernel.py)使用真实内核和内存状态，无需模型或个人配置，打印依赖顺序、调用结果、ctx 变更来源、事务冲突与清理顺序。

## 声明与调用

下面是一个完整的同步示例：`counter` 定义调用点，`extension` 提供更高优先级实现，并接收显式通知。

```python
from aurora_kernel import Context, Host, namespace


@namespace("counter")
def counter(ctx: Context) -> None:
    ctx["counter"]["value"] = 0


@counter.callpoint("increment")
def increment(ctx: Context, amount: int = 1) -> int:
    with ctx.transaction() as staged:
        staged["counter"]["value"] += amount
    return ctx["counter"]["value"]


counter.declare("changed", mode="notify")


@namespace("extension", requires=("counter",))
def extension(ctx: Context) -> None:
    ctx["extension"]["last_value"] = None


@extension.hook("counter:increment", priority=10)
def increment_twice(ctx: Context, amount: int = 1) -> int:
    with ctx.transaction() as staged:
        staged["counter"]["value"] += amount * 2
    return ctx["counter"]["value"]


@extension.hook("counter:changed")
def changed(ctx: Context, value: int) -> None:
    ctx["extension"]["last_value"] = value


host = Host((extension, counter)).build()
assert host.call("counter:increment", 3) == 6
assert host.ctx["extension"]["last_value"] is None
host.call("counter:changed", host.ctx["counter"]["value"])
assert host.ctx["extension"]["last_value"] == 6
```

- `@namespace` 登记初始化函数，`requires` 是依赖的 namespace 完整名称。上例实际先构造 `counter`，再构造 `extension`。
- `@counter.callpoint(...)` 同时声明调用点和默认实现；`counter.declare(...)` 只声明调用点；`@extension.hook(...)` 登记实现。
- `Host(...)` 取得冻结声明并校验装配，在初始化之前建立所有入选模块的 ctx 空间。后续追加装饰器不会改变已有 Host。
- `.build()` 同步构造，之后才允许调用。初始化函数用于建立状态，不能在构造期间调用 hook。
- 同一组声明可用于多个 Host；每个 Host 默认拥有独立 ctx，且只能构造一次。
- `host.routes` 是只读调用计划：每项 `CallRoute` 包含调用点和已选中的 `(来源模块, Hook)` 元组，创建宿主后不随声明变化。

### 三种调用模式

| 模式             | 返回值与行为                                                                         |
| ---------------- | ------------------------------------------------------------------------------------ |
| `single`（默认） | 只执行最高 `priority` 的实现，返回其结果；没有实现或最高优先级并列时，创建 Host 失败 |
| `collect`        | 按顺序执行全部实现，返回结果元组；没有实现时返回 `()`                                |
| `notify`         | 按顺序执行全部实现，返回 `None`；允许没有实现                                        |

顺序为优先级从高到低，平级按模块依赖顺序和实现注册顺序。`collect` / `notify` 顺序执行，不并发；某个实现抛错会停止本次调用，已经发生的效果不会自动回滚。`collect` 不会把前一个返回值自动传给后一个实现。

调用点参数是普通 Python 参数，实现首参为 `Context`。外部用 `host.call()`，实现内部可用 `ctx.call()` 嵌套调用。异步实现使用 `await host.acall()` 或 `await ctx.acall()`；异步入口也接受同步实现。同步入口会拒绝包含异步实现的路由。

## 共享上下文 ctx

ctx 是宿主内的共享状态，namespace 用于寻址与组织。任何模块都可以读写其他模块的空间，变更来源记录为实际执行的实现所属模块。

| 操作                                          | 语义                                                               |
| --------------------------------------------- | ------------------------------------------------------------------ |
| `ctx["name"]["key"]`                          | 读取或写入字段；读取不存在的 namespace 抛错                        |
| `ctx.ensure("name")`                          | 显式创建额外空间                                                   |
| `ctx.snapshot()`                              | 获取全部空间的容器快照                                             |
| `ctx.transaction()`                           | 暂存多个字段或跨空间修改，正常退出时一次提交，异常时丢弃           |
| `ctx.transaction(expected_revision=revision)` | 同时校验事务开始前读取的版本                                       |
| `ctx.subscribe(callback)`                     | 提交后同步通知 `Change`，返回取消订阅函数                          |
| `ctx.revision` / `ctx.last_change`            | 读取版本和最近一次变更；`Change` 包含 `revision`、`source`、`keys` |

内建 dict、list、tuple、set 等容器在读写时复制；修改读出的 list 不会直接修改 ctx，必须显式写回。服务对象按引用共享，其内部变化不触发 ctx 版本更新。

事务检测**整个 ctx 的版本**：期间任意空间有其他写入，提交会抛出 `ContextConflictError`，调用方重新读取并决定是否重试。内核不自动重放操作。`+=` 等多次读写需要放进事务，单次字段访问的锁不能保证整个复合操作原子化。

事务不能回滚服务内部变化或外部 I/O，暂存 ctx 不能调用 hook。订阅者不能递归修改同一 ctx；通知失败会抛出异常，但数据已经提交。ctx 及其通知都不是持久日志，Bot 的持久事实仍通过世界端口提交。

## 生命周期与资源

默认阶段：

```text
PREPARE → CONSTRUCT → ACTIVATE → READY → RUN → DRAIN → CLOSE
```

`.build()` 只执行同步构造阶段。有资源或后台任务的模块使用 `await host.prepare()`，并由返回的生命周期对象负责激活、故障交付和关闭。下面是可独立运行的示例：

```python
import asyncio
from collections.abc import Awaitable, Callable

from aurora_kernel import PREPARE, RUN, Context, Host, namespace


@namespace("worker")
def worker(ctx: Context) -> None:
    ctx["worker"]["started"] = asyncio.Event()
    ctx["worker"]["finished"] = asyncio.Event()


@worker.on(PREPARE)
async def prepare(ctx: Context) -> Callable[[], Awaitable[None]]:
    ctx["worker"]["connected"] = True

    async def cleanup() -> None:
        ctx["worker"]["connected"] = False

    return cleanup


@worker.on(RUN)
async def run(ctx: Context, stop: asyncio.Event) -> None:
    try:
        ctx["worker"]["started"].set()
        await stop.wait()
    finally:
        ctx["worker"]["finished"].set()


async def main() -> None:
    host = Host((worker,))
    lifecycle = await host.prepare()
    stop = asyncio.Event()
    try:
        await lifecycle.activate(stop)
        await host.ctx["worker"]["started"].wait()
        stop.set()
        await host.ctx["worker"]["finished"].wait()
    finally:
        stop.set()
        await lifecycle.close()
    assert host.ctx["worker"]["connected"] is False


asyncio.run(main())
```

- `PREPARE` 可返回异步清理函数；准备或构造失败时，释放已经取得的资源。
- `CONSTRUCT` 同步建立状态；`ACTIVATE` 和 `READY` 等待各回调完成；`RUN` 启动后台任务，并额外接收停止事件。
- 后台故障通过 `await lifecycle.next_failure()` 交给宿主；尚未取走的故障在关闭时报告。读取 `lifecycle.failures` 历史快照不表示已处理故障。
- `close()` 取消并等待后台任务，执行关闭阶段，再逆序调用准备阶段的清理函数。默认关闭顺序与依赖顺序相反，关闭后拒绝调用。
- 宿主可先设置停止事件，并按领域协议等待后台正常结束；`close()` 本身不会设置传入的停止事件。
- `Phase` 与 `Ordering` 支持额外阶段和顺序约束；它们描述宿主生命周期顺序，业务循环由领域代码组织。

## 发现与装配

模块文件导出 `MODULE = counter`，或导出 `ModuleSpec`，即可交给 `aurora_kernel.discovery` 的发现源读取：

| 发现源             | 来源                                                  |
| ------------------ | ----------------------------------------------------- |
| `StaticSource`     | 显式提供的声明集合                                    |
| `PackageSource`    | Python 包内子目录的 `module.py`；可配置读取直接子模块 |
| `DirectorySource`  | 本地目录中的 `.py` 文件或含 `module.py` 的插件目录    |
| `EntryPointSource` | 已安装包的 entry point，默认分组为 `aurora_module`    |

宿主显式汇总各来源 `.discover()` 的结果并传给 `Host`。依赖模块也必须在发现结果或显式传入的集合中；声明依赖不会自动安装或查找模块。

`ModuleSpec` 还提供字符串能力的 `provides/requires`、贡献点的 `declares/contributes/consumes`、优先级、可选模块与兼容范围，用于领域适配。它的 `depends` 对应 namespace 之间的直接依赖；`@namespace(..., requires=...)` 使用的正是这一字段。Bot 适配层保留资源与世界域元数据，服务依赖同样使用名称。

模块名称、API 兼容范围、缺失依赖、能力冲突、贡献声明和依赖环，以及调用点冲突，都在准备或构造效果之前校验。发现会导入 Python 模块，因此模块顶层应只声明功能，连接与资源获取放入生命周期回调。

## 源码导航

- [`declaration.py`](declaration.py)：namespace、调用点、实现与模块声明。
- [`resolve.py`](resolve.py)：模块选择、依赖校验和阶段计划。
- [`host.py`](host.py) / [`calls.py`](calls.py)：宿主入口与冻结调用路由。
- [`context.py`](context.py)：共享状态、快照、事务和变更来源。
- [`phase.py`](phase.py) / [`lifecycle.py`](lifecycle.py)：阶段定义、后台监督与资源释放。
- [`discovery.py`](discovery.py)：包、目录和安装入口发现。

更多领域接入说明见 [Namespace 与 hook](../../apps/docsite/src/develop/namespace-modules.md)和[模组开发](../../apps/docsite/src/develop/core-development.md)。
