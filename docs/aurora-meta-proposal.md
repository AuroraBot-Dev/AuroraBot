# plugin.meta.toml：元信息、实现与集中装配

核对基线：W08（2026-11-27），schema_version = 2。沿用原方案文件名以维持引用，本文描述当前规范。原迁移决策与工作包见[实施计划](plugin-new-baseline-plan.md)，发行定义见[公共 ID 目录](aurorabot-id-catalog-v0.2.3.md)。

## 设计中心

插件描述并导出插头、插槽、状态和资源，实现处理逻辑，维护自己负责的 ctx 或订阅关注的 ctx。应用用集中装配文件决定创建哪些实例，以及哪个实例的插头插入哪个实例的槽。槽的拥有者决定何时调用；插头的提供者不预先决定最终目标。

默认信任开发者。清单为发现、理解、组合与构建提供数据，不是插件沙箱或全局兼容审批器。保留重复 ID、缺失实现和无法建立连接等必要错误；业务异常正常传播，不提供静默回退、旧入口兼容层或自动修复用户数据。

## 信息只有一个编辑来源

| 信息 | 来源 | 使用方式 |
| --- | --- | --- |
| 发行名称、版本、依赖、extra、entry point 名称与工厂路径 | pyproject.toml | 发布与发现，目录合并标准发行信息 |
| 插件说明、公共 ID、kind、登记关系、组件端口与角色 | 相邻 plugin.meta.toml | 生成运行声明与静态目录 |
| 数据结构、参数与工具契约 | 清单引用的 JSON 或纯导出函数 | 运行校验、目录及客户端生成共用 |
| 插头实现、ctx 读写/订阅、调用自身槽的时机、资源所有权 | Python | 方法装饰生成 ID，工厂导出实际对象 |
| 启用插件、实例、状态地址、资源引用、接线及生命周期依赖 | 选定 assembly.toml | 宿主建立运行图 |
| 业务参数 | 用户配置 TOML | 配置阶段注入非持久 ctx 状态 |
| 凭证与业务快照 | 运行环境与用户数据目录 | 不写入发布清单 |

`_meta.py` 和发行根目录 `plugin.meta.json` 是生成产物，不另设编辑入口。构建只读核对 AST / JSON 是否与清单一致，不在发布时悄悄重写源码。代码引用生成符号，不再次拼接完整公共 ID。元信息不是所有行为的表达语言，控制算法、条件判断和资源实现继续写代码。

`requires` 是显式启用依赖；`register_to` 是定义登记关系；`depends_on` 是实例生命周期依赖；connections 是具体插头到插槽的连接。四者不会互相推导。安装 extra 也不自动启用插件。

## 清单格式

每份版本 2 清单描述一个公开插件，或一个非插件的宿主目录。一个发行包可以有多份清单，符号表分别独立；通过 pyproject.toml 的 `tool.aurora-meta-build.plugins` / `hosts` 显式列出清单和生成模块位置。core 与 CLI 使用 host 目录，没有伪造的 aurora.plugins 入口。

| 区域 / 字段 | 含义 |
| --- | --- |
| `schema_version` | 当前为 2 |
| `plugins.<symbol>` | 本清单唯一插件；symbol 是本地引用名 |
| `entry_point` | 引用 pyproject 的 aurora.plugins 项；工厂从该项读取，Plugin.name 与之相同 |
| `title`、`summary`、`description` | 展示名称、简述和需要补充的行为约束 |
| `requires` | 必须已被显式选择的插件名列表 |
| `provider` | 可选定义提供者；默认使用 entry point 名称 |
| `host` | 与 plugins 二选一，描述 core/CLI 等直接提供的宿主目录 |
| `definitions.<SYMBOL>` | 公开定义，包含 plugin、id、kind 与说明；宿主目录不填 plugin |
| `register_to` | `{ local = "符号" }` 或 `{ id = "完整 ID" }`，表示分类/协议接收目录 |
| `interface` | 公开接口信息；执行端口可用 definition 引用组件定义 |
| `contract` | 引用本清单 contracts 的名称，供静态消费者读取；具体运行消费者绑定该契约 |
| `contracts.<name>` | format 与 file/export；二者恰选一个 |
| `dynamic.<SYMBOL>` | 动态定义的 plugin、id_root、kind 与 register_to；不把运行目录成员写死为静态定义 |

ID 格式为 `<namespace>:<domain>/<local_path>`，归实际能力所在包。定义不允许填写 slot 或 connect_to；装饰器也不携带目标。宿主定义可单独指定 provider，以保持 CLI 各命令的归属。

契约 file 相对清单目录，当前读取 JSON；export 为 `模块:函数`，由构建工具按源码文件调用。导出必须保持纯数据，不导入运行包、供应商 SDK 或创建资源。format 说明用途，如 json-schema、aurora-http、aurora-tools；它不是额外的连接批准策略。

## 组件声明与代码职责

| components 字段 | 含义 |
| --- | --- |
| `plugin`、`summary` | 所属插件与职责 |
| `inject` | 创建时所需宿主参数，例如 ctx、instance_id、states、options、registry、storage |
| `plugs`、`slots` | 本清单定义符号列表，要求导出实际实例端口 |
| `states`、`optional_states` | 必需/可选状态角色；地址由装配提供 |
| `resources` | 本实例导出的资源名称 |
| `inputs`、`optional_inputs` | 必需/可选的借用资源角色 |
| `resource_maps` | 接受一组具名资源引用的角色 |
| `options` | 对应 contracts 中的组件参数契约名称 |

角色名是局部语义，例如模型调用组件的 input/output 状态与 chat 资源，不预设 Bot 的存储地址。配置桥声明公共配置与非持久状态，业务组件按需绑定；资源对象不塞进 ctx。资源提供方负责创建和关闭，消费方只借用。模型资源在 prepare 解析后提供 `ModelIdentity`（adapter、model、provider、base_url）；记忆资源借用 embedding 时使用该身份建立索引指纹，自定义 embedding 资源须同样明确提供身份和 embed 方法。profile 名称与凭证不属于模型身份。

Python 中 `ComponentFactory` 提供 create、export 和需要时的 bind。create 构造实例，export 返回 `InstanceExport` 的端口及资源，bind 接入明确借用的资源；stop_accepting 等导出行为负责本实例的接收边界。`@plug(ID)` 关联方法身份，执行包装可导出对应 ExecutionPlug。装饰器不会登记实例、创建资源或自动接线。

## 真实完整示例：配置服务

配置服务的真实源文件为 [plugin.meta.toml](../packages/aurora_config/src/aurora_config/plugin.meta.toml)、[service.py](../packages/aurora_config/src/aurora_config/service.py) 和[最小装配](../packages/aurora_config/src/aurora_config/assembly.toml)。下面三段对应这些文件，展示清单、实现与装配分别承担什么。

### 清单

```toml
schema_version = 2

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
resources = ["configuration"]
```

配置插件提供 CONFIGS 接收目录、LOAD 插头和配置编辑端点。它不定义自己的 config 生命周期槽，也不声明 LOAD 必须接到哪个槽。

### 实现

```python
"""在 config 阶段收集声明、校验全部配置并原子注入 ctx。"""

from aurora_core import plug
from aurora_core.components import InstanceExport
from aurora_core.ctx import Context
from aurora_core.discovery import ComponentFactory, Plugin
from aurora_core.registry import DefinitionRegistry
from aurora_core.storage import StorageService

from ._meta import CONFIGS, CONFIGURATION, LOAD, configuration_plugin
from .declarations import ConfigReceiver
from .editor import ConfigurationEndpoint
from .files import ConfigurationFiles, load_configuration


class ConfigurationService:
    def __init__(self, registry: DefinitionRegistry, ctx: Context, storage: StorageService) -> None:
        self.registry, self.ctx, self.storage = registry, ctx, storage
        endpoint = registry.get(CONFIGURATION).target
        assert isinstance(endpoint, ConfigurationEndpoint)
        self.endpoint = endpoint

    @plug(LOAD)
    def configure(self) -> None:
        self.ctx.configure(load_configuration(self.registry, self.storage.configuration_directory()))
        self.endpoint.files = ConfigurationFiles(self.registry, self.storage.configuration_directory())

    def close(self) -> None:
        self.endpoint.files = None


def plugin() -> Plugin:
    return configuration_plugin(
        targets={CONFIGS: ConfigReceiver(), CONFIGURATION: ConfigurationEndpoint()},
        components={
            "configuration": ComponentFactory(
                create=ConfigurationService,
                export=lambda service: InstanceExport(
                    plugs={LOAD: service.configure}, resources={"configuration": service}, stop_accepting=service.close
                ),
                plugs=(ConfigurationService.configure,),
            ),
        },
    )
```

`configuration_plugin` 与 LOAD 等符号来自生成模块。工厂只绑定实际实现，不再次定义插件 ID、端口目录或生命周期目标。`@plug(LOAD)` 保持方法可读，导出表明确哪些对象属于本实例。

### 集中装配

```toml
schema_version = 2
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

这里的槽 ID 由 core 导出。slot.instance 的 `aurora_config` 标识配置服务参加生命周期的实例位置，不表示配置插件拥有一个同名槽。宿主推进这个实例的 config 阶段时，调用连接的 LOAD 方法。换成业务执行槽时，slot.instance 则指向真正导出该槽的组件实例。

## 业务插头如何插入另一个插件的槽

以下是 [default 预设](../packages/aurora_bot/src/aurora_bot/presets/default.toml)中的局部连接，必须与该文件里的模型调用及 ReAct 实例一起使用：

```toml
[[connections]]
plug = { instance = "model_call", id = "org.aurora.agent:handlers/model_call/execute" }
slot = { instance = "main", id = "org.aurora.agent:react/infer" }
priority = 0
```

```mermaid
flowchart LR
  chat[模型资源：chat] -. 借用资源 .-> call[model_call 实例]
  call -->|execute 插头插入 infer 槽| main[main：ReAct 实例]
```

ReAct 调用 infer 槽时才执行模型调用。两者通过状态绑定共享请求与返回地址，模型调用的 chat 资源另由装配引用。连接本身不选择模型、不复制状态，也不推导生命周期顺序。

## 装配文件的公开边界

| 字段 | 含义 |
| --- | --- |
| `schema_version`、`plugins` | 版本 2、显式启用的插件列表 |
| `instances.<name>.plugin/component` | 组件类型与实例身份 |
| `options` | 该实例的静态参数，由组件契约解释 |
| `states.<role>` | key、scope（instance/run）、可选 location；run 作用域由执行身份定位 |
| `resources.<role>` | `{ instance, export }` 引用；resource_maps 角色可映射多个具名引用 |
| `depends_on` | 生命周期前置实例；启动按依赖推进，关闭先处理依赖者 |
| `connections` | 具体 plug / slot 的 instance 和 id，以及 priority |
| `collection_connections` | 将工具 collection 展开的执行成员接到指定 slot |

装配器读取这些数据，代码负责实际连接接收判断和调用。动态目录在 prepare 后才有成员，静态计划不能冒充实际运行图。工具集合的筛选规则与成员身份属于集合 options，工具实际行为仍由工厂提供。

当前查询可用 `aurora-meta catalog <发行名>`、`aurora ... id list` 和 Python `Host.graph`；独立 CLI 目录/计划/实际图入口尚未实现。完整预设及配置路径见[配置与装配](configuration.md)，生成与发布核对见[开发指南](development.md#清单生成与静态目录)。
