# aurora.meta.toml 收敛方案与完整示例

日期：2026-11-26。状态：讨论稿，未实施。本文中的清单格式、生成器、方法插头与槽实例 API、`aurora meta` 命令均为拟议能力。示例通过端点对象委托当前 core 的登记与连接接口；第 5.9 节给出最小实现草图，项目尚未提供这些端点类型。

## 1. 目标与原则

`aurora.meta.toml` 描述插件公开什么、各定义有什么用途、向哪里登记、声明连接到哪个插槽。开发者、用户、文档工具和未来的插件目录都能读取这些信息，无需运行插件。

默认信任用户和开发者遵循契约。元信息用来说明、引用、生成和查询，不承担插件审批、权限隔离或通用业务验证。开发检查帮助发现错误，运行期保留让调用语义成立所需的检查。

本方案采用五条约定：

1. 每个事实只有一个可编辑来源，其他文件可以引用或由它生成。
2. 公共 ID、归属和静态关系从清单生成；实现对象和实际行为留在 Python。
3. 继续使用现有 `Plugin`、`RegistryEntry`、`HookConnections` 和 `ExecutionPlug`；端点对象委托既有连接管理器，不维护第二份连接表。
4. 复杂业务规则由插件自己实现；不要求所有插槽都提供 schema 或自定义接受函数。
5. 先支持明确的描述和生成，不设计通用对象构造语言、条件表达式、自动连接或自动启用依赖。

## 2. 相对现状的最小变化

当前 [Plugin](../packages/aurora_core/src/aurora_core/discovery.py) 包含名称、登记项和依赖，[RegistryEntry](../packages/aurora_core/src/aurora_core/registry.py) 已有 ID、kind、provider、register_to、slot 和 interface。清单为这些现有概念提供一个可读的声明来源。

保留 `pyproject.toml` 中的标准 `aurora.plugins` entry points。插件入口的名称和 Python 工厂路径以这里为准，清单使用 `entry_point` 引用它。清单不重复定义 `name` 或 `factory`，也不额外引入生成 entry points 的构建后端。

构建前的开发工具将清单编译成：

- 包内 `_meta.py`：定义对象及其 ID、声明数据、结构契约数据和构造 `Plugin` 的薄辅助函数。
- `aurora.meta.json`：不含 Python 实例的静态目录，用于 CLI、文档和市场索引。

二者都不手工修改。生成模块只使用标准库和 core；拟议端点类型也放在 core，不在每个插件中复制实现。模块不导入插件实现、不启动资源，也不读取 TOML。core 不增加 TOML 加载职责，control 保持仅依赖 core。

首次实现可以提供独立的开发脚本，之后由 CLI 提供命令入口；代码生成工具不成为插件的运行时依赖。构建前显式生成或检查产物，不要求每次启动都核对源码摘要。

## 3. 信息归属与唯一来源

| 信息 | 唯一可编辑来源 | 使用方式 |
| --- | --- | --- |
| 发行包版本、作者、许可证、安装依赖、extra | `pyproject.toml` | 静态查询合并读取标准发行元数据 |
| 插件名称、入口工厂路径 | `pyproject.toml` 的 `aurora.plugins` | 清单引用 entry point；生成代码沿用其名称 |
| 插件简介、用法、文档、启用依赖 | 清单 | 目录展示；生成 `Plugin.requires` |
| 固定公共 ID、kind、provider、登记与插槽关系 | 清单 | 生成定义对象及 `RegistryEntry` 的声明部分 |
| Python 实现对象、绑定方法 | Python | 工厂向生成函数提供实际 target |
| 数据结构契约 | 一个契约文件或一个代码导出函数 | 清单引用，目录和运行消费者读取同一内容 |
| 状态持久化属性、配置关联的状态和模板 | 所属包的清单扩展 | 所属包的构造函数读取声明 |
| 用户配置值、环境凭证、业务快照 | 用户数据与运行环境 | 不进入发布清单 |
| 实例身份、状态地址、连接顺序、生命周期依赖 | 装配代码或既有用户配置 | 引用定义，构造实际运行对象 |
| MCP 实际工具名称、参数和实现 | 远端发现结果 | 形成运行期目录，静态清单只声明动态集合 |

同一个 ID 出现在生成文件和引用处，不代表有两个来源。判断标准是：修改这个定义时，开发者是否只改一处，其余结果是否能确定性重建。

引用不重新定义被引用者。例如 `entry_point = "example_greeting"` 引用标准入口；`register_to` 引用 core 的注册表；都不在本文件重新声明对方的路径、结构或实现。

## 4. 清单格式

每个发行包一份 `aurora.meta.toml`，放在 `pyproject.toml` 旁。一个包可以描述多个插件。插件随发行包版本发布，暂不增加独立插件版本体系。

### 4.1 基础字段

根字段 `schema_version = 1` 表示本格式版本。下面各表的键是文件内符号，不是额外的公共 ID。

| 区域 | 字段 | 含义 |
| --- | --- | --- |
| `plugins.<符号>` | `entry_point` | 必填，引用本发行包的 `aurora.plugins` 入口 |
| 同上 | `summary` | 必填，一句话说明职责 |
| 同上 | `title`、`description`、`usage`、`documentation`、`tags` | 可选，人可读介绍和检索信息 |
| 同上 | `requires` | 默认空，必须同时显式启用的插件名 |
| 同上 | `install_extras` | 默认空，引用本包已定义的 extra，供安装说明使用 |
| 同上 | `provider` | 可选，默认使用 entry point 名；保留当前包级 provider 习惯 |
| `definitions.<符号>` | `plugin`、`id`、`kind`、`summary` | 必填，所有者、公共身份、类别和用途 |
| 同上 | `register_to`、`slot` | 可选，沿用当前登记关系和插槽声明语义 |
| 同上 | `interface` | 可选，显式的数据值或定义引用，映射到 `RegistryEntry.interface` |
| 同上 | `inputs`、`outputs` | 可选，引用 `contracts` 中的契约符号，供描述和查询 |
| 同上 | `description`、`extensions` | 详细说明，以及由所属包解释的扩展数据 |
| `contracts.<符号>` | `format` 与 `file` 或 `export` | 契约格式及唯一来源，`file` 与 `export` 二选一 |
| `dynamic.<符号>` | `plugin`、`kind`、`id_root`、`summary` | 描述运行期才能发现的定义集合 |
| 同上 | `register_to`、`phase`、`discoverer` | 可选，登记目标、发现阶段和发现入口引用 |

`kind` 继续允许第三方扩展。`inputs`、`outputs` 不隐式包装函数或启用运行校验，也不取代 `interface`。某个消费者需要结构验证时，应直接使用这些契约，而不是再手写一份结构规则。

引用采用两种明确形式：

```toml
slot = { local = "GREETING_SLOT" }
register_to = { id = "org.aurora.core:registries/hook_handlers" }
```

`local` 引用本清单的定义；`id` 引用外部完整公共 ID。`interface` 如需表达当前 control 使用的组件身份，写为 `interface = { definition = { local = "COMPONENT" } }`，生成时还原为 `Id`；如需普通 JSON 描述，使用 `interface = { value = { ... } }`，按接收方约定解释。

v1 不为任意 Python 对象建立 TOML 编码规则。确实依赖不可序列化 interface 的程序化插件继续由代码提供，静态目录标明需要代码解释；不声称清单覆盖了这类对象的全部语义。

### 4.2 契约来源

`file` 指向相对清单目录的文件。JSON Schema 使用标准 JSON 文件，保持编辑器和工具支持。生成目录内嵌其内容，安装后的查询不需要访问源码目录。

`export` 指向开发者提供的无参数纯函数，构建时调用一次，返回可序列化的结构。例如现有 [describe_conversation](../packages/aurora_bot/src/aurora_bot/conversation_contract.py) 可以成为 HTTP 契约的唯一来源。运行时消费者和构建导出使用同一函数或同一生成结果，不分别维护路由和字段。

导出只在显式生成时执行，不在插件列表查询时执行。不为导出器设计沙箱或全程序副作用检测；开发者负责让它不启动模型、工具、网络连接或读取用户凭证。导出异常正常报告，不补造空契约。

v1 不实现 Python 类型到通用 schema 的自动推断。无法结构化的行为用说明与代码表达，目录明确保留其边界。

### 4.3 扩展、宿主与动态定义

`extensions."org.aurora.config"` 等命名空间可以描述专用信息，基础生成器保留它们；解释代码由对应包提供。首次实现只支持实际迁移需要的扩展，不预建通用扩展注册框架。

扩展中的信息如果参与运行，消费者直接读取它。例如 `StateKey` 的持久化属性从声明取得，`ConfigSpec` 的 state 和 template 从声明取得；清单引用的结构契约也用于实际配置校验。跨配置关联检查保留在 Python。扩展如果只用于说明，应明确标成说明，不能在 UI 中宣称其已被强制执行。

core 的自举目录、生命周期插槽和 ctx 操作可以使用同格式的定义，由 `host_group` 替代 `plugin` 标记宿主分组。分组没有 entry point，不要求用户启用额外的 core 插件；宿主仍在当前登记时机绑定它们。先有宿主迁移需求再补充分组生成入口。

动态集合示例：

```toml
[dynamic.MCP_TOOLS]
plugin = "mcp_tools"
kind = "tool"
id_root = "org.aurora.adapter:tools/mcp"
register_to = { id = "org.aurora.agent:registries/tools" }
phase = "prepare"
summary = "按用户配置选择并发现 MCP 工具"
```

这是字段示意，`mcp_tools` 必须在实际清单的 plugins 中声明。`id_root` 描述子路径范围，不创建工具、不赋予权限，也不要求增加一套运行时拦截器。尚未发现时，目录显示动态集合，而不是声称插件没有工具。实际 schema 来自现有 MCP 发现结果；目录变化仍遵循当前重建宿主的约定。

## 5. 完整示例：一个处理器定义，两个实例

示例包提供一个问候插槽和一个问候处理器。宿主创建正式、日常两个处理器实例，按顺序连接到同一个插槽实例。两者共享定义身份，实例身份和输出前缀分别由装配指定。

采用普通 core hook，并为它提供与 control 的 `slot.connect(plug)` 一致的用法。生成的槽定义绑定到一个宿主槽实例，处理器定义绑定到一个实际方法后成为方法插头；装配只需把插头交给槽。control 的执行插头对应关系在第 6 节说明。

```text
example-greeting/
├── pyproject.toml
├── aurora.meta.toml
├── contracts/
│   ├── greeting-input.schema.json
│   └── greeting-output.schema.json
├── metadata/
│   └── aurora.meta.json                 # 生成产物
└── src/example_greeting/
    ├── __init__.py                      # 空文件
    ├── _meta.py                         # 生成产物
    ├── implementation.py
    ├── plugin.py
    └── demo.py
```

### 5.1 标准包信息：pyproject.toml

```toml
[project]
name = "example-greeting"
version = "0.1.0"
description = "Aurora 问候插件示例"
requires-python = ">=3.12"
dependencies = ["aurora-core>=0.1.0"]

[project.entry-points."aurora.plugins"]
example_greeting = "example_greeting.plugin:plugin"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/example_greeting"]

[tool.hatch.build.targets.wheel.extra-metadata]
"metadata/aurora.meta.json" = "aurora.meta.json"
"aurora.meta.toml" = "aurora.meta.toml"
"contracts" = "contracts"

[tool.aurora.meta]
source = "aurora.meta.toml"
module = "src/example_greeting/_meta.py"
catalog = "metadata/aurora.meta.json"
```

`tool.aurora.meta` 是拟议的生成器配置，Hatch 不解释这一段。发布前先显式生成产物；Hatch 只负责把产物和资源装进 wheel。上述 `extra-metadata` 将文件放在发行包的 `.dist-info/extra_metadata/` 中。

生成工具同时读取标准 entry points 表，由此得到插件名称和工厂路径。第三方采用其他构建后端时，只要把同样的静态目录发布到约定位置即可，不要求更换运行框架。

### 5.2 唯一的公共定义来源：aurora.meta.toml

```toml
schema_version = 1

[plugins.greeting]
entry_point = "example_greeting"
title = "问候处理器"
summary = "提供问候插槽和可绑定实例的问候处理器"
description = "调用方提供包含 name 的请求，处理器返回问候文本。"
usage = "将 Greeter.greet 的绑定方法制成插头，再通过槽实例的 connect 接入。"
requires = []
tags = ["example", "greeting"]

[contracts.greeting_input]
format = "json-schema"
file = "contracts/greeting-input.schema.json"

[contracts.greeting_output]
format = "json-schema"
file = "contracts/greeting-output.schema.json"

[definitions.GREETING_SLOT]
plugin = "greeting"
id = "dev.example.greeting:slots/greet"
kind = "hook_slot"
summary = "接收问候请求，由调用方按连接顺序调用处理器"
register_to = { id = "org.aurora.core:registries/hook_slots" }
inputs = "greeting_input"
outputs = "greeting_output"

[definitions.GREETING_HANDLER]
plugin = "greeting"
id = "dev.example.greeting:handlers/greet"
kind = "hook_handler"
summary = "按实例配置的前缀生成问候文本"
register_to = { id = "org.aurora.core:registries/hook_handlers" }
slot = { local = "GREETING_SLOT" }
inputs = "greeting_input"
outputs = "greeting_output"
```

插件名和代码路径没有在清单重新定义。两个公共 ID、两条登记关系和处理器的 slot 意向都在这里定义，后面的 Python 业务文件不再手写这些值。生成器根据 kind 产生 `SlotDefinition` 或 `HandlerDefinition`；端点对象名称及其 ID 均来自同一声明，不增加手写的第二套端口表。

`inputs`、`outputs` 关联的是契约，不是公开登记项。只有某个契约需要被其他插件通过公共 ID 引用时，才额外声明 `kind = "schema"` 的公共定义。

### 5.3 数据契约

`contracts/greeting-input.schema.json`：

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "properties": {
    "name": { "type": "string" }
  },
  "required": ["name"],
  "additionalProperties": false
}
```

`contracts/greeting-output.schema.json`：

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "string"
}
```

这里只描述双方约定，没有给每次进程内调用添加 JSON Schema 验证。未来若通过 HTTP 接收不确定输入，端点可以复用这份契约做边界校验。

### 5.4 行为实现：implementation.py

```python
from collections.abc import Mapping


class Greeter:
    """使用实例前缀，为符合问候契约的请求生成文本。"""

    def __init__(self, prefix: str) -> None:
        self.prefix = prefix

    async def greet(self, request: Mapping[str, str]) -> str:
        return f"{self.prefix}，{request['name']}！"
```

实现没有公共 ID、登记关系、插件依赖和重复的 schema。没有检查请求是否为字典、是否包含 name、name 是否为字符串的多层防御。调用方遵循契约；缺失 name 会产生正常的 Python 错误。

### 5.5 预期生成结果：_meta.py

下面完整展示本例所需的 Python 生成结果，便于审查清单如何落到现有接口。它不属于开发者手写的第二份声明。通用生成器尚未实现。

```python
"""由 aurora.meta.toml、契约文件与标准发行声明生成。"""

from collections.abc import Mapping

from aurora_core.discovery import Plugin
from aurora_core.hooks import HandlerDefinition, SlotDefinition
from aurora_core.ids import Id
from aurora_core.registry import RegistryEntry

GREETING_SLOT = SlotDefinition(Id("dev.example.greeting:slots/greet"))
GREETING_HANDLER = HandlerDefinition(Id("dev.example.greeting:handlers/greet"))

CONTRACTS = {
    "greeting_input": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
        "additionalProperties": False,
    },
    "greeting_output": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "string",
    },
}


def greeting_plugin(targets: Mapping[str, object]) -> Plugin:
    """将实际实现对象绑定到已生成的问候插件声明。"""
    return Plugin(
        name="example_greeting",
        entries=(
            RegistryEntry(
                GREETING_SLOT.id,
                "hook_slot",
                targets["GREETING_SLOT"],
                "example_greeting",
                register_to=Id("org.aurora.core:registries/hook_slots"),
            ),
            RegistryEntry(
                GREETING_HANDLER.id,
                "hook_handler",
                targets["GREETING_HANDLER"],
                "example_greeting",
                register_to=Id("org.aurora.core:registries/hook_handlers"),
                slot=GREETING_SLOT.id,
            ),
        ),
        requires=(),
    )
```

`SlotDefinition`、`HandlerDefinition` 是拟议的 core 定义引用类型，不是当前已有的 `HookSlot`。前者让使用者创建端点，`HookSlot` 仍是登记时提供接收规则的 target。定义对象创建时只持有 ID；它不注册插件、不创建宿主、不查找实例。需要底层 ID 的消费者使用 `.id`。

必要 target 缺失时，普通字典访问就能给出缺失符号，未完成的 `Plugin` 不会被登记。没有为了拒绝多余 target 再写一套运行校验；开发检查可以报告未使用绑定。

生成目录 `metadata/aurora.meta.json` 则保存本例全部插件说明、完整 ID、展开后的 register_to/slot、inputs/outputs 和契约内容。每个定义附所属 entry point 与源文件内的符号。它是清单的可序列化展开结果，不包含 target 或实例状态。发行包版本和许可证等由读取方合并标准发行元数据，无需在目录另存一份。

### 5.6 实现绑定：plugin.py

```python
from aurora_core.discovery import Plugin
from aurora_core.hooks import HookSlot

from ._meta import greeting_plugin
from .implementation import Greeter


def plugin() -> Plugin:
    """提供定义对应的实现，不创建问候实例或建立连接。"""
    return greeting_plugin(
        {
            "GREETING_SLOT": HookSlot(),
            "GREETING_HANDLER": Greeter.greet,
        }
    )
```

`HookSlot()` 使用当前最小接收约定，不提供额外 accept 函数。`Greeter.greet` 是未绑定方法，用于登记定义；装配中把实例的绑定方法交给 `GREETING_HANDLER.bind(...)`，形成实际插头。清单不会尝试构造 Greeter 或猜测 prefix 参数。

业务实现绑定关系只在这个函数中编写。清单负责列出需要的定义符号，不再写一套逐定义的 Python 实现路径。

### 5.7 实例装配与调用：demo.py

```python
import asyncio

from aurora_core.bootstrap import bootstrap
from aurora_core.discovery import load_plugins, register_plugins
from aurora_core.hooks import HookConnections

from ._meta import GREETING_HANDLER, GREETING_SLOT
from .implementation import Greeter
from .plugin import plugin


async def main() -> None:
    registry = bootstrap()
    register_plugins(registry, load_plugins(explicit=[plugin()]))
    hooks = HookConnections(registry)
    try:
        greeting = GREETING_SLOT.bind(hooks, instance_id="console")
        formal = GREETING_HANDLER.bind(Greeter("您好").greet, instance_id="formal")
        casual = GREETING_HANDLER.bind(Greeter("你好").greet, instance_id="casual")

        greeting.connect(formal)
        greeting.connect(casual, priority=10)

        for text in await greeting.emit({"name": "小明"}):
            print(text)
    finally:
        hooks.close()


if __name__ == "__main__":
    asyncio.run(main())
```

在端点 API 实现、产物生成并安装示例包之后，运行 `python -m example_greeting.demo` 的预期输出：

```text
您好，小明！
你好，小明！
```

这里 `greeting` 是槽实例，`formal`、`casual` 是持有各自绑定方法的方法插头。Python 的绑定方法保留所属 Greeter 对象，不需要另建对象保活表。实例名称只在 bind 时指定一次，连接只接收一个插头对象。

此处“实例装配”就是创建对象、绑定实例身份并显式插接。清单中的 slot 意向不会自动连上实例，实际顺序也不由清单表的排列顺序决定。`GREETING_HANDLER.bind(...)` 表示让这个实例方法实现已经声明的处理器；开发者可以显式提供其他符合约定的 callable，不通过反射强制它必须等于原始工厂中的函数。

安装后的 entry point 发现可由现有 `load_plugins(enabled=["example_greeting"])` 完成。demo 使用显式插件只是为了把从登记到调用的链路完整写在一个文件中。

### 5.8 端点 API 的行为

| 写法 | 作用 |
| --- | --- |
| `GREETING_SLOT.bind(hooks, instance_id="console")` | 把槽定义绑定到某个宿主中的槽实例，不建立连接 |
| `GREETING_HANDLER.bind(method, instance_id="formal")` | 把处理器定义、实例身份和实际方法合成插头，不调用方法 |
| `connection = greeting.connect(formal)` | 把一个方法插头接入槽，返回现有 `HookConnection` |
| `greeting.disconnect(connection)` | 拔掉这条连接，委托既有连接管理器 |
| `await greeting.emit(request)` | 按当前连接快照依次调用，返回结果元组 |
| `greeting.connections()` | 取得由既有连接管理器排序的连接快照 |
| `await greeting.invoke(connection, request)` | 调用某条连接，供业务代码自行决定流程 |

`emit` 是普通 hook 的串行广播便利方法：priority 小者先执行，同级按 connect 顺序；没有连接时返回空元组；结果按调用顺序排列。异常直接传播，之后的连接不继续调用，取消沿当前 await 链传播；不额外重试、并发执行、吞掉错误或自动归并结果。

调用期间的连接变化沿用 `HookConnections` 的语义。新增连接不进入已取得的快照；某条尚未调用的连接被断开后，调用它会沿现有 invoke 路径报告连接失效，不额外静默跳过。断开连接不取消已开始的调用，也不关闭处理器自有资源。

如果业务需要分支、并行或选择性调用，使用 connections/invoke 或现有控制组件。`emit` 不改变控制组件的执行策略。宿主仍持有和关闭 `hooks`；单个槽没有关闭整个宿主连接管理器的权力。

普通方法继续是普通方法。为了把它接入系统，显式通过生成定义的 bind 产生插头即可。无需要求所有业务类继承框架基类、增加隐藏实例 ID、扫描方法名或维护对象与公共 ID 的自动匹配表。`slot.connect(plug)` 与现有 control 用法一致，本轮不增加方向难以辨认的运算符重载。

### 5.9 端点到现有 core 的最小映射

下面是拟议 core API 的完整最小草图，供评审行为和验证示例；不是要求每个插件携带的辅助文件，也不是本次对运行代码的修改。四个小对象只保存定义引用、实际方法及实例身份，连接仍全部由同一个 `HookConnections` 管理。

```python
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from aurora_core.hooks import HookConnection, HookConnections
from aurora_core.ids import Id


@dataclass(frozen=True)
class MethodPlug:
    definition: Id
    target: Callable[..., object]
    instance_id: str


@dataclass(frozen=True)
class HandlerDefinition:
    id: Id

    def bind(self, target: Callable[..., object], *, instance_id: str) -> MethodPlug:
        return MethodPlug(self.id, target, instance_id)


@dataclass(frozen=True)
class SlotDefinition:
    id: Id

    def bind(self, hooks: HookConnections, *, instance_id: str) -> BoundSlot:
        return BoundSlot(self.id, hooks, instance_id)


@dataclass(frozen=True)
class BoundSlot:
    definition: Id
    hooks: HookConnections
    instance_id: str

    def connect(self, plug: MethodPlug, *, priority: int = 0) -> HookConnection:
        return self.hooks.connect(
            self.definition,
            plug.definition,
            slot_instance=self.instance_id,
            handler_instance=plug.instance_id,
            target=plug.target,
            priority=priority,
        )

    def disconnect(self, connection: HookConnection) -> bool:
        return self.hooks.disconnect(connection)

    def connections(self) -> tuple[HookConnection, ...]:
        return self.hooks.for_slot(self.definition, self.instance_id)

    async def invoke(self, connection: HookConnection, *args: object, **kwargs: object) -> object:
        return await self.hooks.invoke(connection, *args, **kwargs)

    async def emit(self, *args: object, **kwargs: object) -> tuple[object, ...]:
        results = []
        for connection in self.connections():
            results.append(await self.invoke(connection, *args, **kwargs))
        return tuple(results)
```

这里没有新的接收规则、连接缓存或隐式生命周期。端点对象只是更适合装配代码阅读的调用入口。只有 bind 保存描述，connect 才访问注册表并建立实际连接，emit/invoke 才执行方法；缺失定义、重复连接和接收方拒绝仍由现有路径报告。

## 6. 对应项目现有能力

### 6.1 control 与 agent 的执行插头

当前 [component_entries](../packages/aurora_control/src/aurora_control/execution.py) 生成 component、`/execute`，以及可选的 `/children`。迁移时把这些固定定义写入清单或生成展开目录，业务代码引用生成常量；不同时保留两套手写的固定登记声明。

执行插头仍是登记层的 `hook_handler` 与实例层的 `ExecutionPlug`。`interface` 继续引用其组件定义，不新增一个 plug 登记种类。v1 沿用现有 `/execute` 端口命名约定，清单不能凭空承诺任意端口命名都能被当前 ExecutionPlug 使用。

`ExecutionRequest`、`StateBinding`、`InstanceStateBinding` 及实际状态地址留在代码。元信息可描述 input/output 等角色和用途，但不把 bot 的地址写进 agent 定义。`ExecutionSlot.accept` 保持可选；没有业务需要就不写。不增加全局 schema 相等校验，不把静态“候选连接”显示为已确认兼容。

control 已有 `slot.connect(component.plug)`，普通方法插头沿用相同的装配表达。`MethodPlug` 不冒充携带执行身份和状态地址的 `ExecutionPlug`，也不把控制组件的 invoke 换成普通 hook 的 emit。二者复用底层连接机制，各自保留实际调用协议。

### 6.2 配置、状态、工具和端点

[config_entries](../packages/aurora_config/src/aurora_config/declarations.py) 同时产生配置与非持久状态。迁移这些定义时要同步把状态纳入目录，避免清单展示一个定义、运行时又隐含出现另一个固定 ID。

具体实现可以使用配置包的薄构造函数读取声明中的状态、模板和契约；不要求 core 理解 ConfigSpec。业务关联校验仍留在代码。工具参数、HTTP 路由、CLI 参数等可以沿用现有纯数据描述或纯导出函数，目录从同一来源取得内容，不要求第一轮全部改写成 TOML。

持久化属性如果进入清单，就必须由实际 StateKey 构造读取；在完成这种消费关系之前，不添加一个仅供展示、可能与运行行为不一致的 persistent 字段。

### 6.3 装饰器和显式替换

对于已迁移到清单的 operation/hook_handler，代码不再使用带完整 ID 和 slot 的重复声明。可以直接像示例那样绑定对象；若保留装饰器，装饰器只引用生成的声明符号。

现有 `registry.replace()` 和运行期显式 target 绑定继续可用。用户可以编写程序化插件、替换实现或直接组合组件。静态目录描述发行包声明的默认能力，运行期查询显示实际登记与连接；替换后的对象不应被静态目录误报为原始实现。

程序化插件可以没有清单，查询时显示“仅运行期提供”。不为了强迫全部插件进入清单而添加加载禁令，也不为此引入兼容转发层。

## 7. 校验收敛到哪里

| 情况 | 处理方式 |
| --- | --- |
| 无法解析清单、格式版本无法解释 | 生成时报告明确错误，不猜测含义 |
| 固定公共 ID 重复 | 保留现有登记冲突错误 |
| 必需实现未提供、实际调用的定义不存在 | 使用直接的绑定或查询错误，不静默生成占位对象 |
| 显式 requires 未满足 | 保留现有插件选择校验，不自动安装或启用 |
| 可选接收方缺席 | 保留现有 unconnected 诊断，不升级为通用加载禁令 |
| 非调用对象被当作处理器、实例连接重复 | 保留现有连接语义所需检查，不叠加另一套 |
| 不认识的说明字段、第三方 kind 或扩展 | 保留供查询；开发检查提示拼写或解释边界，不一律拒绝运行 |
| 生成物过期、模板缺失、契约链接失效 | 放在生成检查和发布验收中，不在每次调用重查 |
| 两个契约不同或没有契约 | 接收方自行决定；框架不建立全局兼容判定器 |
| 外部输入、用户配置、实际副作用边界 | 保留对应消费者已有的必要校验，不因信任开发者删除有效检查 |

基础生成器保留未知说明/扩展数据，但不尝试执行其中未知的行为。某个消费者必须理解一项配置才能工作时，由该消费者给出局部错误；“忽略未知字段”不等于执行自己无法解释的指令。

不新增递归对象验证、方法签名全覆盖扫描、运行期源码哈希检查、权限审批、自动修复或静默数据迁移。已有检查是否需要精简，应针对真实成本或问题单独讨论，不借元信息迁移批量删除。

拟议 `aurora meta check` 检查的是开发产物：引用可解析、入口对应、目录完整、生成结果一致、契约资源存在。它不自动导入全部已安装插件或启动宿主；需要调用 export 时，应针对开发者明确选择的项目。未使用绑定等提示不必默认成为启动阻断条件。

## 8. 构建、查询与实施范围

生成工具读取 `pyproject.toml`、清单及契约来源，确定性输出 Python 声明和 JSON 目录。构建消费已经生成的文件。生成物可以随源码提交，方便可编辑安装和源码阅读；修改声明后重新生成，CI 用只读检查发现遗漏。

Hatch 示例将静态目录发布到 `.dist-info/extra_metadata/aurora.meta.json`。读取方通过发行包元数据读取它，不通过 `importlib.resources` 导入插件包来定位。目录内嵌契约并保留来源符号；查阅不依赖模型 SDK、MCP、用户配置或运行凭证。

拟议查询入口：

```text
aurora plugin list
aurora plugin show example_greeting
aurora id show dev.example.greeting:slots/greet
aurora id references dev.example.greeting:slots/greet
aurora meta generate <项目目录>
aurora meta check <项目目录>
```

这些入口属于后续实现。静态查询应展示“插件提供一个插槽和一个处理器，处理器声明指向这个插槽”；只有连接到运行宿主，才能展示“console 当前连接 formal 和 casual 两个实例”。

第一轮实现集中在标准入口关联、固定定义生成、方法插头与槽实例的薄 API、静态目录、必要的契约资源引用，以及代表插件的迁移。配置等专用扩展按实际消费者逐步接入。后续市场可以按 ID、kind、插槽关系和说明检索；安装更新、自动装配、权限系统及通用 schema 兼容引擎不纳入本轮。

迁移某个定义时应同时切换 ID 常量、声明装饰器、登记工厂、消费者和文档来源，保留原公共 ID、插件名和生命周期行为。已有配置与快照不因加入清单被改写。构建工具不能为了元信息读取破坏 control/agent 的独立安装边界。

## 9. 本文验收范围

本文作为独立方案保存，未修改项目实现、依赖、入口、配置、README.md 或 AGENTS.md。文档验收包括本地链接、TOML/JSON 片段解析、完整示例 Python 语法，以及在临时验证环境中把第 5.9 节草图接到现有 core 后运行示例，核对绑定、插接、输出与拔除行为。该验证不能证明拟议端点 API 已进入项目，也不能证明尚未实现的生成器或 wheel 打包流程已完成。
