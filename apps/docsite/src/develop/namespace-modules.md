---
order: 4
---

# Namespace 与 hook

`aurora_kernel` 提供模块无关的宿主。它只处理名称、调用点、共享上下文和生命周期，不导入 `aurora_cli` 或 `aurora_bot`。CLI 用它承载命令执行，Bot 通过 `aurora_bot.kernel` 把领域模块接入同一个装配机制。

## 注册与调用

命名空间装饰器登记初始化函数；宿主在任何初始化之前创建所有入选模块的 ctx 空间。`requires` 使用其他命名空间的完整名称，决定初始化先后顺序。所有模块可以读写全部 ctx。

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


@namespace("client", requires=("counter",))
def client(ctx: Context) -> None:
    ctx["counter"]["value"] = 10


@client.callpoint("run")
def run(ctx: Context) -> int:
    return ctx.call("counter:increment", 2)


host = Host((client, counter)).build()
assert host.call("client:run") == 12
```

声明可以复用于多个 Host，每个宿主的 ctx 独立。宿主构建时冻结声明，之后添加装饰器不会改变已经创建的宿主。初始化只建立状态；调用点在构造成功后开放，关闭后拒绝调用。

模块可以只声明调用点，再由任意命名空间通过 `@module.hook(target)` 提供实现：

```python
counter.declare("changed", mode="notify")


@client.hook("counter:changed")
def changed(ctx: Context, value: int) -> None:
    ctx["client"]["last_value"] = value
```

这些声明必须在创建 Host 之前完成。注册 hook 不会自动触发调用，调用者显式执行 `ctx.call("counter:changed", value)`。

| 模式             | 行为                                                                 |
| ---------------- | -------------------------------------------------------------------- |
| `single`（默认） | 选取最高 `priority` 的一个实现；缺少实现或最高优先级并列在构建前失败 |
| `collect`        | 按优先级从高到低执行，平级按模块依赖顺序与注册顺序执行，返回结果元组 |
| `notify`         | 使用同样顺序执行全部实现，返回 `None`                                |

`collect` 和 `notify` 可以没有实现。调用是顺序执行，任一实现抛错就停止本次调用，已发生的效果不会自动回滚。`host.call()` / `ctx.call()` 用于同步调用，异步实现通过 `await host.acall()` / `await ctx.acall()` 调用；异步入口也接受同步实现。调用点不要求 Protocol 或输入输出 DTO，公共函数保留必要的参数和返回值注解即可。

## 共享 ctx

- `ctx[namespace][key]` 读写一个字段；赋值、删除和 `update()` 都进入统一变更入口。`ctx.ensure(name)` 显式创建额外共享空间，拼错名称的读取不会隐式建空间。
- 内建 dict、list、tuple、set 等容器在读写时复制，修改读取结果不会偷偷改变 ctx。服务对象按引用共享，其内部状态由服务本身负责。
- 多字段或跨命名空间更新使用 `ctx.transaction()`，在暂存 ctx 上修改，正常退出时一次提交，异常退出时丢弃。
- 事务提交会检查整个 ctx 的版本。期间发生其他写入时抛出 `ContextConflictError`，调用方重新读取并决定是否重试；内核不自动重放效果。`expected_revision` 可保护事务开始前读取的数据。
- 单次读写加锁；`+=`、`pop()` 等包含多次读写的操作需要事务才能保证整体一致。事务不能回滚服务对象内部变化或外部 I/O；暂存 ctx 不能调用 hook。
- `ctx.revision`、`ctx.last_change` 与 `ctx.subscribe(callback)` 提供版本和变更来源。订阅者在提交后同步收到 `Change`，包含版本、来源命名空间与变更字段；订阅返回取消函数。
- 订阅者不能递归修改同一 ctx。通知失败会汇总抛出异常，已经提交的数据保留。通知不是持久事件日志。

命名空间用于寻址与组织，不提供权限隔离。ctx 保存进程内状态；Bot 的持久事实仍通过世界端口提交。

## 生命周期

`Host.build()` 只执行同步构造，适合命令和纯内存功能。有资源的模块使用 `await host.prepare()`，返回的生命周期对象负责激活、后台故障和关闭：

```python
import asyncio
from aurora_kernel import PREPARE, RUN


@client.on(PREPARE)
async def prepare(ctx: Context):
    ctx["client"]["connected"] = True

    async def cleanup() -> None:
        ctx["client"]["connected"] = False

    return cleanup


@client.on(RUN)
async def run_until_stopped(ctx: Context, stop: asyncio.Event) -> None:
    await stop.wait()


async def main() -> None:
    host = Host((counter, client))
    lifecycle = await host.prepare()
    try:
        stop = asyncio.Event()
        await lifecycle.activate(stop)
        await host.acall("client:run")
        stop.set()
    finally:
        await lifecycle.close()
```

默认阶段为 `PREPARE → CONSTRUCT → ACTIVATE → READY → RUN → DRAIN → CLOSE`。`PREPARE` 可返回清理函数；构造失败清理已经成功取得的资源，关闭按依赖逆序执行。后台异常通过 `next_failure()` 交给宿主，未取走的异常在关闭时报告。生命周期回调首参都是 ctx，`RUN` 额外接收停止事件。

## 插件与 Bot 适配

将命名空间声明导出为 `MODULE = client`，即可由 `aurora_kernel.discovery` 的 `DirectorySource`、`PackageSource` 或 `EntryPointSource` 发现。独立安装包使用 `aurora_module` entry point，可指向声明对象或导出 `MODULE` 的 Python 模块。入口依赖的其他模块也必须被宿主发现或显式传入。

Bot 启动发现内置模块、`extensions/plugins/`、`aurorabot_plugin` 和 `aurora_module` 入口。通用 namespace 与 Bot `@module` 可以混合装配，共用依赖解析、ctx 和生命周期。目录支持单文件与含 `module.py` 的包，相对导入按完整文件路径隔离；修改插件需要重启。

发现源的扫描、导入和入口排序统一由 `aurora_kernel.discovery` 完成；Bot 适配层只指定默认来源与声明提取规则。

CLI 的内置命令、内置配置与外部插件也复用这些发现源，通过 `CliPlugin` 声明贡献，并由独立同步 Host 执行命令。CLI 专用入口、配置资源与完整示例见 [CLI 命令与配置插件](./cli-plugins)。

Bot 适配层保留契约类型、资源声明、世界域与清单归档。`context.ctx` / `assembly.ctx` 暴露共享上下文，`get()` 与 `contributions()` 从其中实时读取：

| ctx 空间               | 内容                                                                           |
| ---------------------- | ------------------------------------------------------------------------------ |
| `aurora.bot`           | `settings` 保存装配输入                                                        |
| `kernel.services`      | 契约身份到实例的映射；`aurora_bot.kernel.context.capability_name(type)` 生成键 |
| `kernel.contributions` | 贡献点名称到值元组的映射                                                       |
| 各模块完整名称         | 自动创建的模块自有状态空间                                                     |

通用模块可用 `requires=("aurora:kernel/module/具体模块",)` 等待某个入选 Bot 模块构造，也可以直接读写上述空间。提供方选择与依赖计划在构建时确定；修改 ctx 不会重跑装配，也不会替换其他对象已保存的服务引用。

`Assembly.modules` 是 Bot 领域声明目录，通用声明位于宿主的解析结果中，不自动生成 Bot 资源或模型工具。需要向 Bot 暴露领域能力时，使用[模组开发](./core-development)中的资源、操作与世界端口；hook 本身不等于模型工具授权。
