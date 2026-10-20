---
order: 3
---

# 模组开发

模组为 Bot 提供一种可发现的能力。她应能理解能力的输入、结果、影响和读取范围，实际调用仍由外围环境校验、执行并记录。先确定这项能力怎样服务主体，再决定它需要哪些端口和世界事实。

## 最小领域操作

本地单文件放在 `extensions/plugins/example.py`，包形式放在 `extensions/plugins/example/module.py`，两种形式都导出唯一 `MODULE`。目录由 Git 忽略；需要发布时使用独立 Python 包和 `aurorabot_plugin` entry point。包内可以相对导入，重新发现会重新加载该本地包及其子模块。

下面的查询只回显参数，不访问外部服务。它用同一个定义生成资源说明、终端调用和结构化工具：

```python
"""提供 Bot 可发现的回显查询。"""

from aurorabot.contracts import ToolScopes
from aurorabot.contracts.operation import (
    OPERATION_CONTRIBUTIONS,
    OperationDefinition,
    OperationRequest,
    OperationResult,
)
from aurorabot.contracts.resource import ResourceKey, ResourceRef
from aurorabot.kernel import ModuleContext, ModuleManifest, module


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

## 端口与依赖

`provides` 与 `requires` 使用公开契约类型，运行时通过 `context.get` 获取实际实现。功能包不运行时导入兄弟实现，也不直接访问其数据库表。内建端口位于 `aurorabot.contracts.pkgs`；独立扩展共享的领域契约应稳定发布，消费者与提供者使用同一个类型身份。

用组合和结构化 `Protocol` 表达能力，不要求所有实现继承同一个基类。单值能力由优先级选取，平级冲突启动即失败；多值扩展使用已声明的贡献点。消费方使用 `consumes` 声明对完整贡献集合的依赖，不手动枚举插件或维护 import 列表。

模组部分能力被替换后仍可能因为贡献、其他端口或生命周期参与装配。构造私有默认对象前，应先取得已选端口；`prepare` 中的网络连接、模型载入等效果需要确认 `context.is_provider` 和端口是否已经存在。接线、公开操作和关闭必须使用实际选中的实例。自依赖声明允许默认适配层等待替代提供者，内核不会把默认自身依赖当成循环；真实跨模组依赖环仍会失败。

## 实现组织

`module.py` 依次放置导入与常量、按生命周期排序的钩子、带声明的 `build`、辅助函数和末尾的 `MODULE = build`。单端口 `build` 依次读取已选实例、在缺省分支构造默认实现、登记贡献并返回实例；只有准备和构造阶段共用的默认构造才提取为 `_create_default`，该函数不再承担端口选择或登记。

固定操作和工具直接在类上声明不可变的 `definition`，静态资源声明与实例执行共用这个入口。依赖具体实例才能生成的定义保留实例属性。结构化操作输入放在所属能力的 `inputs.py`；被多个能力共同使用的输入继续放在 contracts。

并列配置解析模块导出唯一 `CONFIG_SPEC`。普通表和表数组使用声明式形状；涉及传输分支或整组约束的文件保留显式解析。组织方式保持一致，异步准备、多端口登记和按实例生成定义等差异由实际语义决定。

## 生命周期与资源

准备阶段可以初始化外部资源并返回异步清理函数，构造阶段完成端口与贡献绑定。若消费者需要在 `prepare` 读取端口，提供者也必须在该阶段发布它，或由宿主预先注入；不能假设稍后构造的端口已经存在。

`activate` 完成恢复和事件入口激活，`ready` 可归档已冻结的实际定义，`run` 接收停止事件并持续运行。`drain/close` 和准备清理按计划关闭，后台失败必须交还监督机制。创建认知入口的能力贡献 `TREE_LAUNCHER_BINDINGS`，不直接导入 runtime 或 engine。

静态定义用 `resources`；由实际配置或所选实例决定的定义用 `RESOURCE_CONTRIBUTIONS`。需要跨重启读取正文时贡献 `RESOURCE_CONTENTS`，由统一生命周期归档；大量实例和内容用动态提供者分页发现，避免把每条数据塞进内核注册表。定义、别名和运行实例的精确语义见[资源与操作协议](../reference/resources-and-operations)。

## 验证与发布

至少验证该能力的成功、参数拒绝、失败及未知效果路径；有外部副作用时验证幂等身份和恢复边界。替换既有端口时，用真实装配检查调用落在被选中的实例上。网络服务用 fake，世界恢复使用临时 SQLite，模型机制使用确定的离线输入。

运行 `uv run aurora check --fix`；示例对应的插件集成行为见 `tests/test_operation_plugin.py`。清单发布版本与内核 API 范围分别表达，宿主在任何准备效果前校验兼容性。清单归档能核对声明，不能恢复未安装的代码和依赖环境。
