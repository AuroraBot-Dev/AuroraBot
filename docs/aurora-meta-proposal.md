# plugin.meta.toml：插件导出与集中装配方案

日期：2026-11-27。状态：`aurora_config` 首轮实现，待审查；其他插件尚未迁移。已实现该包的 `plugin.meta.toml`、生成模块与静态目录、`@plug`、组件工厂导出和集中装配文件入口。本轮装配器支持方法插头接入 core 的五个生命周期槽；业务插槽、执行端口和状态绑定仍是后续设计。

## 1. 设计中心

插件描述并导出插头、插槽、状态和配置，实现自己的处理逻辑，维护自己负责的 ctx、订阅和资源。应用通过一份集中装配配置，决定启用哪些插件、创建哪些实例，以及把哪个实例的插头接到哪个实例的插槽。

插件知道自己提供的插槽何时被调用、调用具有什么业务意义；它不需要预先知道最终插入的是哪个插件的哪个实现。插头知道自己实现什么契约，不需要把最终目标插槽写进定义。装饰器只关联定义与实现，集中配置描述运行拓扑。

| 层次 | 决定什么 | 主要来源 |
| --- | --- | --- |
| 插件能力 | 有哪些公共定义、职责、契约、组件入口及宿主依赖 | `plugin.meta.toml` |
| 插件行为 | 方法实现、ctx 读写与订阅、资源创建与收尾、调用插槽的时机 | Python |
| 应用组合 | 实例选择、连接、状态绑定、优先级和生命周期依赖 | 集中装配配置 |
| 基础机制 | 登记、ctx、订阅、连接、调用、生命周期推进与持久化 | core 与宿主 |

默认信任开发者。配置连接不需要经过额外审批；schema、类型说明和用途帮助理解与接入，不建立全局兼容判定器。保留重复 ID、缺失实现、无效连接等让运行语义无法成立的错误，不叠加多层防御检查。

同一插件可以提供多个插头和插槽，也可以实现私有的内部组合。公开的应用接线由集中配置表达；插件发布的默认接线作为独立装配预设提供，不成为插头不可更改的目标约束。

## 2. 现有代码与需要调整的地方

### 2.1 已有机制可以继续使用

- [Plugin](../packages/aurora_core/src/aurora_core/discovery.py) 收集公开定义并声明显式启用依赖。
- [RegistryEntry](../packages/aurora_core/src/aurora_core/registry.py) 区分定义 ID、kind、实现 target 和 provider。
- [HookConnections](../packages/aurora_core/src/aurora_core/hooks.py) 已经按定义和实例分别寻址，支持显式绑定实际方法。
- [Lifecycle](../packages/aurora_core/src/aurora_core/lifecycle.py) 已登记并驱动 `config / prepare / start / stop / clean` 五个真实的 `hook_slot`。
- control 的 [ExecutionPlug / ExecutionSlot](../packages/aurora_control/src/aurora_control/execution.py) 已把组件身份、状态地址和实际执行分开；通用执行插头没有固定的目标槽。

### 2.2 当前的接线仍有代码耦合

[hook_handler](../packages/aurora_core/src/aurora_core/declarations.py) 要求填写目标 slot，core 连接时会检查已声明的 slot 是否匹配。[configuration_component](../packages/aurora_config/src/aurora_config/assembly.py) 现在显式选用包内 assembly.toml 预设，配置服务实现不再自行接线；[ReActDefaults.connect](../packages/aurora_agent/src/aurora_agent/react_defaults.py) 与 [DefaultAssembly](../packages/aurora_bot/src/aurora_bot/assembly.py) 也直接决定了一部分连接。

当前 [host.toml](../packages/aurora_cli/src/aurora_cli/host.toml) 主要选择插件与代码装配入口，并不是完整的集中接线文件。本文提出把应用连接逐步外移，不能仅靠美化 `connect()` 的 Python 写法完成。

迁移到新声明方式的插头不再携带固定目标 slot，生成的 `RegistryEntry.slot` 使用 `None`。装饰器不再要求 slot。实际连接继续由 `HookConnections.connect()` 接收明确的两端。

不需要先全局删除 `RegistryEntry.slot` 或现有程序化接口。已迁移插件去除自身的固定目标声明；未迁移插件暂时保持现状。不能同时保留两套会执行的接线，再让用户配置看起来可以覆盖实际上仍被旧代码固定的关系。

## 3. 三份输入与唯一来源

| 信息 | 唯一可编辑来源 | 其他位置的关系 |
| --- | --- | --- |
| 发行包名称、版本、作者、许可证、安装依赖和 extra | `pyproject.toml` | 查询时合并标准发行元数据 |
| 插件 entry point 名称及工厂路径 | `pyproject.toml` | 清单引用入口，不重写 name/factory |
| 公共 ID、kind、provider、登记目录 | 清单 | 生成代码常量和登记项 |
| 插头、插槽及状态的用途与契约 | 清单或它引用的契约来源 | 生成静态能力目录 |
| 方法实现哪个插头 | 代码中的 `@plug(生成的定义引用)` | 工厂显式导出方法，从装饰器读取身份 |
| 组件工厂和自有资源的收尾行为 | 插件代码 | 宿主按导出协议创建、关闭实例 |
| 实例名称、插件选择、组件选择、端点连接 | 集中装配配置 | 装配器建立实际对象与连接 |
| 配置值、状态地址绑定及组件间生命周期依赖 | 对应用户配置与集中装配配置 | 插件读取或接受注入，不重复写死 |
| 数据结构 | 单个 schema 文件或纯代码导出函数 | 目录、运行消费者和客户端生成共用来源 |
| 业务快照、运行期凭证 | 用户数据与运行环境 | 不进入插件发布清单 |

`register_to` 继续表达“定义登记到哪个分类或协议接收目录”，例如处理器登记到 core 的 hook_handlers。它不代表运行时把该处理器连接到某个具体插槽。

`requires` 继续只声明插件启用依赖。安装依赖、插件依赖、实例生命周期依赖、实例连接是四种不同关系，不互相推导，不自动启用依赖插件。

同一个定义可以在多个引用和生成产物中出现，但只在清单定义一次。运行连接只在选定的集中配置中决定一次；发布默认预设时，宿主使用用户选定的预设，不另叠加一份隐藏默认连接。

## 4. 清单的收敛格式

每个发行包一份 `plugin.meta.toml`，与 `pyproject.toml` 同级。一个文件可以描述多个插件。表键是文件内符号，公共身份仍使用现有完整 ID。

插件相关文件采用以下命名方向：

| 用途 | 文件或目录名 | 状态 |
| --- | --- | --- |
| 插件元信息 | `plugin.meta.toml` | 本方案采用的名称 |
| 单文件配置模板 | `plugin.config.toml` | 后续由现有 `config.toml` 迁移 |
| 多文件配置模板 | `plugin.config.tomls/` | 后续由现有 `config.tomls/` 迁移 |

配置模板仍保存在所属 Python 包内，同一包在单文件与目录形式中择一使用。模板命名迁移单独同步 ConfigTemplate、模板资源引用、分发内容和使用文档；用户数据目录中的既有配置文件如何映射需在迁移时明确，不随本次命名讨论自动改名。下文对当前配置链路的核对继续使用现有模板。

| 区域 | 内容 |
| --- | --- |
| `schema_version` | 文件格式版本，v1 为 1；与包版本分开 |
| `plugins.<符号>` | `entry_point`、`summary`，可选 title/description/documentation/tags/requires/provider/install_extras |
| `definitions.<符号>` | 所属 plugin、id、kind、summary，可选 register_to/interface/contract/description/extensions |
| `components.<符号>` | 所属 plugin、summary、需要注入的宿主服务 inject、导出的 plugs/slots |
| `contracts.<符号>` | format，以及 file 或 export 二选一的结构来源 |
| `dynamic.<符号>` | 所属 plugin、kind、id_root、summary，按需描述运行时才能发现的集合 |

约定如下：

- 清单的插头定义没有目标 `slot`，也没有 `connect_to` 或隐含的目标组件。
- `plugs`、`slots` 列出某类组件导出的本地定义符号，不表达它们之间的连接。插件可以只提供其中一类，也可以不提供实例组件。
- `register_to = { id = "完整 ID" }` 引用外部目录；同一文件已有的定义使用 `{ local = "符号" }` 引用。
- control 使用的 `interface = { definition = { local = "组件符号" } }` 表达插头所属组件，不代表目标槽。普通协议也可以使用显式可序列化描述。
- `inject` 只列出工厂需要的已知宿主服务，例如 registry、ctx、storage、hooks。宿主按名称传入对象；不靠遍历构造函数签名猜测依赖。
- 专用状态、配置、工具等描述由所属包解释。core 不因此接管 ConfigSpec、模型或 MCP 语义。
- 说明与业务约束可以保留文字；不要求每个插件都提交完整 schema，不自动把说明变成运行校验。

### 4.1 契约与静态目录

`file` 指向相对清单目录的契约文件。`export` 指向开发者提供的无参数纯导出函数，生成时返回可序列化内容；例如已有的 `describe_configuration()`。生成后的静态目录包含结构内容及来源信息。

开发者负责让导出函数不启动客户端、网络或后台任务。本轮构建工具按 export 定位 src 下的独立 Python 文件，通过 runpy 执行纯导出函数，不导入插件入口；当前 describe_configuration 无其他导入。此阶段不支持依赖包内相对导入的导出文件。生成工具正常报告导出失败，不设计沙箱或全程序副作用检查。查询已发布目录不执行导出函数，也不导入插件实现。

初版不实现通用 Python 类型到 schema 的转换。无法静态描述的 Python 对象、接收逻辑和复杂业务约束保留在代码，目录明确说明其边界。

### 4.2 宿主定义与动态能力

core 的五个生命周期槽由宿主登记，不要求把 core 伪装为一个用户必须启用的插件。它们可用同样的目录格式描述为宿主所有的定义；提供方始终是 core，实例作用域由生命周期组件确定。

MCP 等动态集合只描述来源和公开范围。实际工具 ID、参数与实现来自 prepare 阶段的发现结果。没有发现时显示“尚未发现的动态集合”，不显示为空就当作没有能力。动态元信息不触发发现，也不替代运行目录。

## 5. 主例：现有 aurora_config 插件

选择它作为第一例，是因为它有三个固定公开定义、一个现成的服务类，并直接消费 core 的生命周期插槽，不需要模型、MCP 或网络服务。

### 5.1 当前真实能力

入口在 [aurora_config/pyproject.toml](../packages/aurora_config/pyproject.toml)，实现主要在 [service.py](../packages/aurora_config/src/aurora_config/service.py)、[declarations.py](../packages/aurora_config/src/aurora_config/declarations.py) 和 [editor.py](../packages/aurora_config/src/aurora_config/editor.py)。

| 现有 ID | kind | 职责 |
| --- | --- | --- |
| `org.aurora.config:registries/configs` | registry | 接收各插件的 ConfigSpec 配置声明 |
| `org.aurora.config:handlers/load` | hook_handler | 加载、校验并将配置注入 ctx，准备配置文件编辑服务 |
| `org.aurora.config:endpoints/configuration` | endpoint | 提供已声明配置的编辑端点 |

其中 load 现在由 `ConfigurationService.configure()` 实现。它扫描配置声明、只补缺失模板、进行结构和关联校验，然后调用 `ctx.configure(...)`，不决定哪个具体业务插件必须存在。

这个插件自身没有导出生命周期插槽。它的加载插头应当由应用接到 core 的 config 插槽。配置注册表虽然也有自己的接收协议，但 kind 是 registry，不应为了插头比喻改成 hook_slot。

### 5.2 标准发行入口保持原样

以下是现有 `pyproject.toml` 的入口片段，不是新的入口名称：

```toml
[project.entry-points."aurora.plugins"]
aurora_config = "aurora_config:plugin"
```

配置包的依赖和 extra 继续归标准发行声明。清单不重复维护版本、Python 约束或入口工厂路径。

### 5.3 packages/aurora_config/plugin.meta.toml

已落地的[清单](../packages/aurora_config/plugin.meta.toml)覆盖这个插件的全部三个公开定义，不把其他插件的配置和状态复制进来。`configuration` 组件符号是本方案新增的导出描述，不是新增公共 ID。

```toml
schema_version = 1

[plugins.configuration]
entry_point = "aurora_config"
title = "声明配置服务"
summary = "加载已登记的 TOML 配置，完成校验并注入 ctx"
description = "只补齐缺失模板；运行配置状态不持久化；提供声明配置编辑入口。"
requires = []

[definitions.CONFIGS]
plugin = "configuration"
id = "org.aurora.config:registries/configs"
kind = "registry"
summary = "接收各插件提供的 ConfigSpec"
register_to = { id = "org.aurora.core:registries/registries" }

[definitions.LOAD]
plugin = "configuration"
id = "org.aurora.config:handlers/load"
kind = "hook_handler"
summary = "加载全部声明配置并注入 ctx，准备配置编辑服务"
description = "无参数调用；配置错误正常传播；具体状态由已登记的 ConfigSpec 决定。"
register_to = { id = "org.aurora.core:registries/hook_handlers" }

[definitions.CONFIGURATION]
plugin = "configuration"
id = "org.aurora.config:endpoints/configuration"
kind = "endpoint"
summary = "列出、读取和保存已声明的 TOML 配置"
register_to = { id = "org.aurora.api:registries/endpoints" }
contract = "configuration_http"

[contracts.configuration_http]
format = "aurora-http"
export = "aurora_config.editor_contract:describe_configuration"

[components.configuration]
plugin = "configuration"
summary = "持有当前宿主的配置加载与编辑服务"
inject = ["registry", "ctx", "storage"]
plugs = ["LOAD"]
slots = []
```

这份清单没有 `slot = core/config`，没有 config_loader 实例名，也没有生命周期优先级。LOAD 可以被任何遵循其调用约定的宿主槽调用；正常启动预设将它接到 core/config，是应用组合的选择。

CONFIGURATION 向 API 的端点目录登记是可选接收关系。只运行配置服务不需要启用 aurora_api，更不能因此隐式启动 HTTP 服务。

### 5.4 插件代码怎样变化

以下展示已落地的服务与工厂写法，完整实现见 [service.py](../packages/aurora_config/src/aurora_config/service.py)。`plug`、`ComponentFactory`、生成模块 `_meta` 和绑定入口 `configuration_plugin` 已可用。配置加载与关闭方法保持原业务职责。

```python
from aurora_core import plug
from aurora_core.ctx import Context
from aurora_core.discovery import ComponentFactory, Plugin
from aurora_core.registry import DefinitionRegistry
from aurora_core.storage import StorageService

from ._meta import CONFIGS, CONFIGURATION, LOAD, configuration_plugin
from .declarations import ConfigReceiver
from .editor import ConfigurationEndpoint
from .files import ConfigurationFiles, load_configuration


class ConfigurationService:
    def __init__(
        self,
        registry: DefinitionRegistry,
        ctx: Context,
        storage: StorageService,
    ) -> None:
        self.registry, self.ctx, self.storage = registry, ctx, storage
        self.endpoint = registry.get(CONFIGURATION).target

    @plug(LOAD)
    def configure(self) -> None:
        self.ctx.configure(load_configuration(self.registry, self.storage.configuration_directory()))
        self.endpoint.files = ConfigurationFiles(self.registry, self.storage.configuration_directory())

    def close(self) -> None:
        self.endpoint.files = None


def plugin() -> Plugin:
    return configuration_plugin(
        targets={
            CONFIGS: ConfigReceiver(),
            CONFIGURATION: ConfigurationEndpoint(),
        },
        components={
            "configuration": ComponentFactory(
                create=ConfigurationService,
                plugs=(ConfigurationService.configure,),
                stop_accepting=ConfigurationService.close,
            ),
        },
    )
```

`@plug(LOAD)` 只把生成的定义 ID 关联到函数，保留原函数与绑定方法语义；不指定目标槽，不自行登记、构造实例、订阅 ctx 或建立连接。工厂显式列出导出方法，不扫描模块内所有函数，不推断方法名称。

`ComponentFactory` 的最小职责是保存 create、导出的 plugs，以及可选的本地 stop_accepting 回调。Plugin.components 按组件符号保存 ComponentExport，其中包含工厂和注入服务名；生成的 PluginDeclaration.bind 收集并核对显式导出。宿主用 inject 中的服务创建实例，再把显式导出的未绑定方法绑定到该实例，得到按公共 ID 索引的实际插头。

生成函数从清单取得 LOAD 的 id/kind/provider/register_to，并从装饰器取得对应实现。未绑定 configure 方法登记为原始 target，实例连接时再提供绑定方法；这延续当前 core 的方式。没有第二份“LOAD 映射到 configure”的手写字符串表。

`close` 保持当前 `stop_accepting` 行为，不为它杜撰一个现有的公开清理 ID。它是组件自己的停止接收动作，由宿主既有关闭流程调用；不是一条隐藏的跨插件接线，也不是第六个生命周期阶段。

配置服务依赖的 CONFIGS 和 CONFIGURATION 常量要一起改为引用生成模块，包括 declarations.py、editor.py 和公共出口。生成模块本身不导入这些实现模块，避免循环导入。用户配置、公开 ID 与快照身份均不因迁移改变。

本例只创建一个配置服务实例。当前配置编辑端点在同一 registry 中共享，不能因为元信息可以描述多个实例，就宣称已实现多配置服务隔离。

## 6. 集中装配配置怎样写

### 6.1 最小完整示例

文件名为 `assembly.toml`，以下就是已发布在配置包中的[最小预设](../packages/aurora_config/src/aurora_config/assembly.toml)。它通过 CLI 的 `--assembly-file` 或 host.toml 的 `assembly_file` 选择。

```toml
schema_version = 1
plugins = ["aurora_config"]

[instances.aurora_config]
plugin = "aurora_config"
component = "configuration"
depends_on = []

[[connections]]
plug = { instance = "aurora_config", id = "org.aurora.config:handlers/load" }
slot = { instance = "aurora_config", id = "org.aurora.core:lifecycle/config" }
priority = 0
```

| 字段 | 解释 |
| --- | --- |
| plugins | 明确启用并登记哪些插件；不自动启用其 requires |
| instances 的表键 | 本次装配的实例身份，与插件名、定义 ID 分开 |
| instance.plugin / component | 选择已启用插件导出的哪种组件工厂 |
| depends_on | 实例生命周期依赖；沿用启动正序、关闭逆序的规则 |
| connection.plug | 插头的公共定义 ID 与实际提供者实例 |
| connection.slot | 槽的公共定义 ID 与实际槽实例 |
| priority | 同一槽实例中按现有规则排序；同值保留配置中的连接顺序 |

安装包、启用插件与创建实例是不同动作。启用一个只提供定义的插件，不代表必须为它创建一个生命周期组件；没有在实例表选择的工厂不会自行运行。

### 6.2 为什么两端的 instance 都是 aurora_config

插头定义的提供者是 `aurora_config`，槽定义的提供者是 `aurora_core`。两者的公共 ID 已明确区分所属包。

当前 Lifecycle 按组件推进阶段，通过 `hooks.for_slot(阶段 ID, component.instance_id)` 取得连接。因此宿主会为每个生命周期组件使用一组按该组件实例身份寻址的 core 槽。本例的 core/config 槽作用于 aurora_config 组件，所以 slot.instance 与组件实例相同。

这不表示配置插件导出了自己的 config 槽，也不表示插头指向自己的定义。实际关系是：

```text
core 定义的 lifecycle/config，作用于 aurora_config 组件
    → 调用集中配置接入的 aurora_config:handlers/load 实例方法
```

不把所有组件的 config 处理器塞进一个全局广播槽，否则会丢掉现有组件依赖排序和逐组件生命周期语义。

### 6.3 启动和关闭实际发生什么

1. 宿主先读取 assembly.toml，得到插件、实例和连接选择。
2. 登记 core 自举目录、生命周期槽和插件定义，建立 ctx 与存储服务。
3. 用清单声明的 inject 参数创建 ConfigurationService；此时不加载用户配置、不调用 configure。
4. 装配器按 connections，将实际的 service.configure 绑定到该组件的 core/config 槽。
5. 按 instances 创建 LifecycleComponent；使用 depends_on 与组件导出的 stop_accepting。
6. 生命周期先恢复持久状态，再推进 config。core 调用连接，配置插件加载声明文件并写入非持久配置状态。
7. prepare/start 继续按现有规则推进。这个实例没有其他阶段插头，不需要伪造空方法。
8. 关闭时通过既有 stop_accepting 调用 service.close，配置编辑服务停止接收操作；宿主统一完成连接、存储与 ctx 的收尾。

集中配置只决定连接和组件关系。阶段顺序、失败收束、取消和最终落盘仍由现有生命周期实现负责，不在 TOML 中编写执行算法。

### 6.4 装配器与底层连接的对应

下面仅展示宿主内部映射，不是插件代码需要维护的循环；名称是算法变量，不代表已实现的公共 API。

```python
for connection in assembly.connections:
    plug_instance = instances[connection.plug.instance]
    target = plug_instance.plugs[connection.plug.id]
    hooks.connect(
        connection.slot.id,
        connection.plug.id,
        slot_instance=connection.slot.instance,
        handler_instance=connection.plug.instance,
        target=target,
        priority=connection.priority,
    )
```

所有公开应用连接经过同一份配置和这一类底层调用。插件不必知道对端实例，也不需要给自己的处理器调用 connect。插槽提供方只在相应业务时机调用自身槽内已连接的处理器。

## 7. 必须解决的引导边界

集中装配文件决定配置服务能否启动，因此不能由该配置服务在 config 阶段反过来决定自己的初始连接。

宿主引导层先解析 assembly.toml 的小型结构，只读取插件选择、实例描述和引用，不依赖已经运行的 config 服务。项目已有 [read_host_config](../packages/aurora_cli/src/aurora_cli/configuration.py) 在插件发现前读取宿主选择，可以沿这条路径接入；通用结构处理仍由配置层支持，core 不增加 TOML 解析职责。

其后，业务 TOML 仍通过 ConfigSpec、ConfigSchema、ConfigTemplate 和配置服务加载。运行时覆盖不自动写回文件，不把装配配置或业务配置混入持久业务快照。

CLI 已提供 `--assembly-file PATH`；host.toml 也可以设置 `assembly_file = "assembly.toml"`，相对路径按 host.toml 所在目录解析。命令行文件路径按工作目录解析。旧 `--assembly`、host.toml 的 `assembly` 和命令自带的装配 ID 与文件模式不能同时执行。文件模式的插件列表只来自装配文件，不能另加 `--plugin` 或 host.toml 的非空 plugins；命令行显式选择装配会覆盖宿主默认选择。

文件模式不自动登记配置插件或创建配置组件；程序化传入的插件对象仅作为被文件选中时的实现来源。旧代码装配模式继续显式选用 configuration_component 对应的包内预设；两种模式不会叠加。CLI 的内置命令和配置声明仍由宿主登记，这不等于自动创建配置服务。

## 8. 如何在这个真实插件上验证

### 8.1 先核对能力和最小连接

快速契约检查核对清单、生成物与插件的三个真实定义；端到端用例通过正式 CLI 读取装配文件、发现插件、创建组件、连接和关闭。用例还删除连接并将连接移到 start，验证没有隐藏的 config 接线；空插件列表验证文件模式不会自动启用配置插件。

直接在不登记其他声明的 core 宿主中只启用 aurora_config 时，可见配置数为零；通过 CLI 启动时还会读取 CLI 自身的配置声明。这验证加载插头与 core/config 的衔接，不应描述为已运行完整 Bot。

### 8.2 用现有 world 配置观察真实 ctx 注入

为了观察配置值进入 ctx，可将第 6.1 节插件列表替换为：

```toml
plugins = ["aurora_config", "aurora_world", "aurora_world.configuration"]
```

保留唯一的 aurora_config 实例和原连接。这里启用另外两个插件是为了使用现成的 `org.aurora.world:configs/sources` 声明及 `org.aurora.world:state/config`，不创建 WorldSources、时间或天气来源实例。

在临时数据目录中，config 阶段应复制缺失的 world 配置模板并将解析结果写入非持久状态；配置文件编辑服务应能列出该声明。正常关闭后服务的 files 引用恢复为 None。若后续 config 失败，Lifecycle 也会停止已进入 config 的组件接收入口；未进入 prepare 的组件仍不执行 stop 阶段。全程不调用模型、不发起网络访问、不读取或改写用户实际数据目录。

这证明“一个插件导出配置声明，配置服务消费声明并维护 ctx”的集中装配链路。world 自身的 configure/start 等插头没有被接线，不会因为启用插件而自动运行。

## 9. 如何扩展到其他真实插件

### 9.1 ReAct 与模型调用

下面只是一条拓扑示意，假设 agent 和 model 实例已按各自导出协议创建，不是完整可运行的 Agent 装配：

```toml
[[connections]]
plug = { instance = "model", id = "org.aurora.agent:handlers/model_call/execute" }
slot = { instance = "agent", id = "org.aurora.agent:react/infer" }
priority = 0
```

两端都是现有公共 ID。ReAct 知道何时进入 infer，ModelCall 知道如何从 ctx 读取模型请求并写出结果，集中配置决定把哪个模型实例放入该阶段。

但这条边本身不能完成现有 ReAct 链路。当前默认阶段还包括 build_prompt、interpret_response、record_observation 和工具执行，状态地址及处理顺序也要配套迁移。不能保留 ReActDefaults.connect() 自动连边，再额外读配置重复接线。

执行端口连接应使用现有 `ExecutionSlot.connect(ExecutionPlug)`，保留状态地址握手和实际接收逻辑；装配器按组件导出的端口类别调用它，不把执行插头降级成普通无参数 hook。组件工厂按其需要接收集中配置中的状态绑定，agent 定义不硬编码 bot 的状态地址。

### 9.2 ctx 与订阅

插件描述自己公开的状态、配置与可复用的地址角色；代码负责何时读取、写入和订阅。例如现有 WorldSources 在 start 中订阅 ctx，并在停止接收时解除订阅，这属于其自身行为。

只有插件确实提供可配置的订阅选择时，应用配置才选择具体 key/location。v1 不强迫把每一次 ctx 读写或内部订阅转成装配表，也不把所有 ctx 变化自动当作执行入口。

### 9.3 默认装配预设

正式 Bot 可以发布独立的默认 assembly.toml，集中记录默认组件、状态绑定、生命周期依赖和连接。用户选用或修改它。插件清单可以给出预设资源位置，加载插件本身不应用预设。

插件实现依然可以管理自己的内部对象。需要跨插件替换的公开边应当在预设中出现，避免“预设之外还有一组固定接线”破坏配置作为唯一运行拓扑来源的意义。

## 10. 校验与信任边界

| 情况 | 做法 |
| --- | --- |
| 清单或装配文件无法解析 | 在读取处报告直接错误 |
| 公共 ID 冲突、实际使用的定义或实例缺失 | 沿现有登记、查找或连接路径报告错误 |
| requires 缺失 | 保留显式选择规则，不偷偷安装或启用插件 |
| lifecycle depends_on 缺失或有环 | 沿用已有组件排序检查，不把所有 hook 图都要求成 DAG |
| 可选登记接收方缺席 | 保留 unconnected 诊断，不强制启动对方 |
| 契约不同或没有完整 schema | 允许按双方约定连接，接收方按实际需要解释 |
| 未认识的说明字段和第三方扩展 | 保留并展示，开发工具提示；不一律阻止运行 |
| 外部输入、真实配置、不可逆副作用 | 保留所属消费者必要的校验和行为约束 |
| 生成物过期、资源遗漏或未导出的符号 | 放入开发与发布检查，不在每次调用重复核对 |

不新增插件权限审批、全程序签名扫描、对象来源强制比对、每次调用的重复 schema 验证、源码哈希守卫或自动数据迁移。开发者可以显式选择特殊组合，也承担其业务意义；元信息负责让选择可见、可解释。

静态目录能回答“有哪些插头和槽”；装配文件能回答“计划连接什么”；运行宿主能回答“现在实际连接了什么”。不把其中一个视图当成另一个，也不把静态候选连接标成已经运行成功。

## 11. 生成、包边界与分发

本轮生成工具为 [build_meta.py](../packages/aurora_config/build_meta.py)，读取 pyproject.toml、plugin.meta.toml 及契约来源，生成包内 `_meta.py` 和 `plugin.meta.json`。工具暂为 aurora_config 定址，不作为所有发行包的通用生成器。公共 ID 常量、Plugin 的声明部分以及组件导出描述由这些输入确定；生成代码不手工维护，不导入业务实现来猜测连接。

插件实现只把实际对象、装饰过的导出方法和组件工厂交给生成入口。装饰器对方法的关联是实现来源，清单是公共身份来源；这不是重复声明目标槽或实例连接。

静态目录随 wheel 放在约定的 `.dist-info/extra_metadata/plugin.meta.json` 中，查询方从发行元数据读取；不通过导入插件包来定位，不需要安装模型或 MCP 的可选 SDK。本包同时分发清单和纯契约导出文件。生成物随源码提交，快速契约测试与 Hatch 构建钩子均执行只读一致性检查。Python 生成物按 AST 比较、JSON 按数据比较，允许格式器调整排版；不在调用期间检查文件或哈希。

core 只处理已经解析的声明、工厂导出、对象和连接；TOML 读取、静态生成与装配文件解释属于开发工具和宿主配置层。control 保持仅依赖 core，agent 不因此依赖 CLI、API 或 bot。实例工厂协议是集中装配这个实际消费者需要的能力，不在此基础上提前引入新的通用 harness 或任意 Python 对象配置语言。

## 12. 运行、生成与审查入口

在工作区完成依赖安装后，可以使用真实配置服务预设运行一次宿主命令：

```bash
uv run --locked aurora --data-dir /tmp/aurora-config-review \
  --assembly-file packages/aurora_config/src/aurora_config/assembly.toml ctx list
```

应能看到 CLI 的配置状态；命令结束后生命周期完成关闭。选择独立数据目录，避免混入既有业务快照。若需要验证 world 配置，复制该 assembly.toml，并把 plugins 改为第 8.2 节的三个入口，然后通过 `ctx get org.aurora.world:state/config` 查看结果。这个操作不创建 world 来源或 Agent。

也可以在数据目录的 config/host.toml 写入以下选择，后续省略 `--assembly-file`：

```toml
assembly_file = "assembly.toml"
```

清单修改后，使用已安装开发环境生成并格式化产物。首次生成使用 `--no-sync`，避免 uv 在产物更新前触发构建一致性检查：

```bash
uv run --locked --no-sync python packages/aurora_config/build_meta.py
uv run --locked ruff format packages/aurora_config/src/aurora_config/_meta.py
pnpm exec prettier --write packages/aurora_config/plugin.meta.json
uv run --locked python packages/aurora_config/build_meta.py --check
```

安装 wheel 后，无需导入插件即可读取目录：

```python
import json
from importlib.metadata import distribution

catalog = json.loads(distribution("aurora-config").read_text("extra_metadata/plugin.meta.json"))
print(catalog["definitions"]["LOAD"])
```

静态目录描述能力；assembly.toml 描述计划连接；实际连接仍可通过 HookConnections.for_slot 查询。没有新增插件审批或全局契约兼容检查。

## 13. 本轮范围与后续审查

本轮只迁移 aurora_config 的三个既有定义与配置服务组件，补齐必要的 core 声明机制、配置层装配读取和 CLI 引导。公开 ID、entry point、依赖关系、用户配置及快照身份保持不变，不迁移或改名既有用户文件。`plugin.config.toml(s)` 模板命名仍是后续事项。

集中装配目前支持配置服务所需的显式实例、注入服务、方法插头、生命周期槽、连接优先级与组件 depends_on。业务槽与 ExecutionSlot、状态地址绑定、动态定义和更多插件的生成支持尚未落地；不把不支持的端口静默当成普通 hook。组件构造保持同步且不启动运行资源，资源在生命周期中创建与关闭。同一 registry 中只应配置一个配置服务实例，端点尚不提供多实例隔离。

后续先审查这一条链路，再选择真实业务组件迁移公开接线；需要同时处理其状态绑定和旧自动连接路径。其他插件代码、默认 Bot 装配和配置模板本轮不迁移。测试和发行验收结果记录在[变更记录](CHAGELOG.md)。
