---
order: 3
---

# 模组开发

模组为 Bot 提供一种可发现的能力。她应能理解能力的输入、结果、影响和读取范围，实际调用仍由外围环境校验、执行并记录。先确定这项能力怎样服务主体，再决定它需要哪些端口和世界事实。

本页演示如何让一个查询出现在终端和 Bot 的可用工具中。通用 Python 模块的学习入口见 [Namespace 与 hook](./namespace-modules)。

## 最小领域操作

本地单文件放在 `extensions/plugins/example.py`，包形式放在 `extensions/plugins/example/module.py`，两种形式都导出唯一 `MODULE`。目录由 Git 忽略；需要发布时使用独立 Python 包和 `aurorabot_plugin` entry point。修改插件后需要重启。

下面的查询只回显参数，不访问外部服务。它用同一个定义生成资源说明、终端调用和结构化工具：

```python
"""提供 Bot 可发现的回显查询。"""

from aurora_bot.contracts import ToolScopes
from aurora_bot.contracts.operation import (
    OPERATION_CONTRIBUTIONS,
    OperationDefinition,
    OperationRequest,
    OperationResult,
)
from aurora_bot.contracts.resource import ResourceKey, ResourceRef
from aurora_bot.kernel import ModuleContext, ModuleManifest, module


class Echo:
    """以单一结构化定义提供查询。"""

    definition = OperationDefinition(
        ResourceRef(ResourceKey.parse("lab:example/query/echo"), "1"),
        "回显给定文本，不产生外部效果。",
        {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
        tool_name="lab:tool/definition/echo",
    )

    def scopes_for(self, request: OperationRequest) -> ToolScopes:
        """此查询不读取或发布业务世界域。"""
        return ToolScopes()

    async def execute(self, request: OperationRequest) -> OperationResult:
        """路由验证参数之后返回可序列化的结构化结果。"""
        return OperationResult({"value": request.arguments["value"]})


@module(
    name="example",
    manifest=ModuleManifest(namespace="lab", version="1.0.0", kernel_api=">=1,<2"),
    resources=Echo.definition.resource,
    contributes=OPERATION_CONTRIBUTIONS,
)
def build(context: ModuleContext) -> None:
    """只贡献自己的实现，目录和工具由宿主统一生成。"""
    context.contribute(OPERATION_CONTRIBUTIONS, Echo())


MODULE = build
```

重启后可以调用：

```text
/resources --namespace lab --domain example --kind query
/inspect lab:example/query/echo@1
/call lab:example/query/echo@1 {"value":"你好"}
```

工具注册不代表模型授权。让某个 Agent 使用该查询时，还需在它的 `tools` 中加入 `lab:tool/definition/echo` 或相应标签。参数、说明或效果语义变化时发布新操作版本，不能在同一个固定引用下换一套定义。

## 扩展的使用边界

插件与主进程具有相同权限，不提供操作系统隔离。发布时需说明依赖、兼容要求、配置方法及可能产生的外部效果。

上述例子只演示无外部效果的查询。接入真实服务时，应准确返回成功、失败或未知结果，并验证重复调用与中断后的行为；含义见[资源与操作](../reference/resources-and-operations)。

需要增加 CLI 命令或个人配置时，参见 [CLI 命令与配置插件](./cli-plugins)。提交前按[验证改动](../architecture/acceptance)运行检查。
