"""Kernel 交互和演示共用的内存模块声明。"""

from aurora_kernel import Context, namespace


@namespace("counter")
def counter(ctx: Context) -> None:
    ctx["counter"].update(value=0, history=[])


@counter.callpoint("increment")
def increment(ctx: Context, amount: int = 1) -> int:
    with ctx.transaction() as staged:
        staged["counter"]["value"] += amount
    return ctx["counter"]["value"]


counter.declare("describe", mode="collect")
counter.declare("changed", mode="notify")


@namespace("extension", requires=("counter",))
def extension(ctx: Context) -> None:
    ctx["extension"]["notifications"] = 0


@extension.hook("counter:increment", priority=10)
def increment_twice(ctx: Context, amount: int = 1) -> int:
    # 跨命名空间写入仍标记为 extension；namespace 不隔离权限。
    with ctx.transaction() as staged:
        staged["counter"]["value"] += amount * 2
    return ctx["counter"]["value"]


@counter.hook("counter:describe")
def describe_counter(ctx: Context) -> str:
    return f"counter.value={ctx['counter']['value']}"


@extension.hook("counter:describe", priority=10)
def describe_extension(ctx: Context) -> str:
    return f"extension.notifications={ctx['extension']['notifications']}"


@counter.hook("counter:changed")
def remember_change(ctx: Context, value: int) -> None:
    with ctx.transaction() as staged:
        staged["counter"]["history"] = [*staged["counter"]["history"], value]


@extension.hook("counter:changed")
def count_notification(ctx: Context, value: int) -> None:
    with ctx.transaction() as staged:
        staged["extension"]["notifications"] += 1
        staged["extension"]["last_value"] = value


@namespace("client", requires=("extension",))
def client(ctx: Context) -> None:
    ctx["client"]["calls"] = 0


@client.callpoint("run")
def run_client(ctx: Context, amount: int) -> int:
    value = ctx.call("counter:increment", amount)
    ctx.call("counter:changed", value)
    with ctx.transaction() as staged:
        staged["client"]["calls"] += 1
    return value
