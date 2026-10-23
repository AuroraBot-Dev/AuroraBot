# 独立工作台扩展

新增一个有状态模块，只需声明配置、装配上下文管理器、操作和快照。工作台统一提供 `create`、`reset`、`export`、`close`；隔离模块还提供 `replay`。无需修改终端、TUI 或 Session，也不需要再写一个模块专属 Session。

下面的文件放入 `playground/modules/counter/__init__.py` 即可被发现：

```python
from contextlib import contextmanager
from collections.abc import Iterator

from playground.protocol import Empty, Model, Module, Operation
from playground.workspace import WorkspaceSpec


class Configuration(Model):
    initial: int = 0


class Value(Model):
    value: int


@contextmanager
def open_instance(configuration: Model, instance_id: str) -> Iterator[list[int]]:
    config = Configuration.model_validate(configuration)
    yield [config.initial]


def snapshot(counter: list[int]) -> Value:
    return Value(value=counter[0])


def increment(counter: list[int]) -> Value:
    counter[0] += 1
    return snapshot(counter)


MODULE = Module(
    "counter",
    "独立计数器",
    workspace=WorkspaceSpec(
        configuration=Configuration,
        open=open_instance,
        snapshot=Operation("state", "读取值", Empty, Value, snapshot, {}, record=False),
        operations=(Operation("increment", "递增", Empty, Value, increment, {}, replayable=True),),
        isolated=True,
    ),
)
```

启动 Playground 后可执行：

```text
/counter.create {"initial":3}
/counter.increment
/counter.state
/counter.inspect
/counter.export
/counter.reset
/counter.reset {"configuration":{"initial":10}}
/counter.close
```

## 声明边界

- 操作函数的第一个参数是装配产物，其余参数来自 `input_type`。函数可以同步或异步，仍使用已有 `Operation` 生成 schema、示例和界面入口。
- 身份参数由工作台添加，默认 `instance_id` 与 `default`；模块可选择自己的身份字段和默认值。配置和操作参数不能占用该字段。
- 快照是无参数、`record=False` 的只读操作。可另声明无参数的 `inspect`，提供模块专属观察视图；未声明时，公共视图展示配置、状态和调用摘要。
- `record=False` 的查询不进入检查点。查询必须无副作用；标记本身不是权限隔离。
- 工厂是标准同步或异步上下文管理器。管理台持有其退出栈，在显式关闭、重置和会话退出时释放。模块内部若使用 Kernel Host，准备与清理仍交给 Host，工作台不再实现一套生命周期钩子。
- `reset` 先装配替代实例，成功后才替换和释放旧实例。新装配失败时保留旧实例；旧资源释放失败时新实例仍可检查。同一实例不能并发调用、重置或关闭。
- 默认必须先 `create`；`implicit=True` 允许在首个有效调用时用空配置按需创建，配置需支持默认值。查询 schema 或输入校验失败不会装配实例。

## 记录与复现

`export` 显式导出配置、初始状态、每个操作的输入/输出/状态/异常类型及最终观察视图，**含正文，不应保存真实凭据或提交真实会话**。摘要和错误响应只记录异常类型，不复制异常正文。

复现需要同时满足：

1. 模块声明 `isolated=True`，保证装配和操作都位于隔离的可重建环境。
2. 序列中的每个操作都声明 `replayable=True`；默认禁止。
3. 记录的模块、声明版本和整个输入序列通过校验。

这些校验在创建任何实例之前完成。真实 CLI、真实 Provider、真实外部写入不能因为记录中写了某个标记就获得重放许可。未声明隔离的模块不提供交互 `replay` 入口。

保存响应的 `result` 字段作为记录对象；调用 `replay` 时传入 `{"instance_id":"replay","archive":记录对象}`。目标身份须未占用。工作台重建依赖、重新执行并比较初始状态、所有检查点和最终观察视图，不续跑原实例，也不在异常后自动重试。

`revision` 标记模块记录格式和语义版本；不兼容改动时更新它。若快照含宿主分配的身份等不参与行为比较的元数据，可通过 `project` 显式投影；投影不能删掉待验证的业务状态，也不要递归替换正文或参数。
