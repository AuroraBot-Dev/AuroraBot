# Kernel 独立工作台

使用真实 `Host` 装配模块，不启动 Bot。配置决定模块组合；实例、重置、释放、检查点和复现统一由公共工作台管理，不要求模块提供 Agent 的单步、消息或取消操作。

```text
/kernel.create {"modules":["counter"]}
/kernel.call {"target":"counter:increment","args":[3]}
/kernel.inspect
/kernel.export
/kernel.reset {"configuration":{"modules":["counter","extension","client"]}}
/kernel.call {"target":"counter:increment","kwargs":{"amount":3}}
/kernel.close
```

`modules` 选择已声明的模块；省略时选择全部，不自动补齐依赖。重复选择、未声明模块以及依赖不完整的组合会失败。`inspect` 显示真实构造的模块、路由模式、选中的实现归属、同步/异步属性和 ctx 快照，可直接观察扩展是否真正接管调用点。

`call` 通过 `Host.acall` 支持同步和异步调用点，传递 `target`、位置参数 `args` 和关键字参数 `kwargs`。调用结果必须能投影为 JSON；上下文中的服务对象需要模块自行提供可序列化的观察视图，不应直接导出连接或凭据。

内置声明是本地内存模块，保留 `increment`、`describe`、`notify`、`run` 快捷操作；未创建实例时，首个有效调用按默认配置创建。可以通过 `instance_id` 保存多个互不共享 ctx 的实例，默认身份是 `default`。

## 换入自己的 namespace

在自己的 Playground 模块中注入声明，不用修改公共 Session：

```python
from aurora_kernel import Context, namespace
from playground.modules.kernel.environment import specification
from playground.protocol import Module


@namespace("my_module")
def my_module(ctx: Context) -> None:
    ctx["my_module"]["value"] = 0


@my_module.callpoint("increment")
def increment(ctx: Context, amount: int = 1) -> int:
    ctx["my_module"]["value"] += amount
    return ctx["my_module"]["value"]


MODULE = Module("my_kernel", "我的模块工作台", workspace=specification((my_module,)))
```

启动后调用 `/my_kernel.call {"target":"my_module:increment","args":[3]}`，通过 `/my_kernel.inspect` 观察。默认不允许复现自定义声明，因为其准备钩子和调用点可能产生真实效果。只有确认整个装配与操作都在隔离环境中时才声明 `isolated=True`；记录文件不能覆盖该限制。

工作台通过 `Host.prepare()` 管理准备、构造和清理，不启动激活钩子或后台任务。需要完整启动阶段的用例应自行提供装配上下文并使用 Host 的生命周期入口，工作台不另写生命周期调度。`reset` 会先准备新 Host，成功后关闭旧 Host；依赖或准备失败不会替换仍可观察的旧实例。

记录使用公共格式 `aurora.playground.record/v1`，可通过 `/kernel.replay {"instance_id":"replay","archive":记录对象}` 离线重跑。详情见 [公共工作台扩展](../../workspace/README.md)。
