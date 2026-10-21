---
order: 5
---

# CLI 命令与配置插件

内置命令、内置配置与外部 CLI 插件都导出 `MODULE: CliPlugin`，使用同一份发现、校验和装配流程。CLI 的声明协议位于 `aurora_cli.plugins`，依赖解析、namespace、ctx 和调用点由 `aurora_kernel` 提供。

## 发现与执行

CLI 先读取顶层 `--root`（默认当前目录），再发现以下来源：

| 来源 | 声明位置 |
| --- | --- |
| 内置命令 | `aurora_cli.commands.<name>` 命令包的 `__init__.py` 导出的 `MODULE` |
| 内置配置 | `aurora_cli.configs` 的直接子包导出的 `MODULE` |
| 工作目录插件 | `extensions/cli/*.py` 或 `extensions/cli/<name>/module.py` |
| 已安装插件 | `aurora_cli_plugin` entry point 指向的声明对象或导出 `MODULE` 的模块 |

本地插件包可使用相对导入。每次 CLI 调用重新建立目录；不同工作目录不共用配置缓存。CLI 插件使用独立的发现入口，Bot 领域插件的入口见[模组开发](./core-development)。

内置命令统一放在 `src/aurora_cli/commands/<name>/` 包内。简单命令直接在 `__init__.py` 声明规格、执行器与 `MODULE`；复杂命令可在同包拆分辅助模块，加载器只读取包入口。

加载器在执行前检查内核 API 兼容性、模块依赖与环、hook 冲突、命令重名、配置重名、配置与资源目标路径冲突。重复贡献报出双方来源，不按导入顺序覆盖。内核未选中的模块不贡献命令或配置。

`--help` 只装配参数描述，不执行 namespace 构造、不读取个人配置、不创建文件。独立使用 `--version` 不加载插件。插件导入只应声明元数据。

命令执行时创建独立的同步 Host 与 ctx；namespace 构造仅建立内存状态。CLI 插件只支持 `CONSTRUCT` 阶段及同步命令调用点，文件、连接和异步任务由命令执行器管理和释放。需要 Bot 生命周期的能力通过 Bot 模组接入。

## 单命令插件

将下面内容保存到 `extensions/cli/hello.py`：

```python
import argparse

from aurora_cli.plugins import command_plugin


def execute(arguments: argparse.Namespace) -> int:
    print(f"你好，{arguments.name}！工作目录：{arguments.root}")
    return 0


MODULE = command_plugin(
    "example.cli.hello",
    {
        "name": "hello",
        "help": "显示问候",
        "args": {"name": "称呼"},
    },
    execute,
)
```

运行 `aurora hello Aurora`。`CommandSpec` 支持参数、选项和子命令；`command_plugin` 将执行器绑定到 namespace 的 `execute` 调用点。

## 同时贡献命令与配置

一个插件可通过 `CliPlugin` 声明多项贡献。下面的 `module.py` 与 `greeting.toml` 放在同一个插件目录：

```python
import argparse
from dataclasses import dataclass
from pathlib import Path

from aurora_cli.contracts.config import ConfigSpec, TableShape, text_field
from aurora_cli.plugins import CliPlugin, CommandContribution, ConfigContribution, ConfigFile
from aurora_kernel import Context, namespace


@dataclass(frozen=True, slots=True)
class Greeting:
    message: str


CONFIG_SPEC = ConfigSpec(
    name="greeting",
    path="config/greeting.toml",
    shape=TableShape(("greeting",), (text_field("message"),), Greeting),
)


@namespace("example.cli.greeting", requires=("aurora.cli",))
def greeting(ctx: Context) -> None:
    ctx["example.cli.greeting"]["calls"] = 0


@greeting.callpoint("show")
def show(ctx: Context, arguments: argparse.Namespace) -> int:
    catalog = ctx["aurora.cli"]["catalog"]
    catalog.configs.path(arguments.root, "greeting")
    value = catalog.configs.spec("greeting").load(arguments.root)
    print(value.message)
    return 0


MODULE = CliPlugin(
    greeting,
    commands=(CommandContribution({"name": "greet", "help": "读取问候配置"}, "example.cli.greeting:show"),),
    configs=(ConfigContribution(CONFIG_SPEC, (
        ConfigFile(Path(__file__).with_name("greeting.toml"), CONFIG_SPEC.path),
    )),),
)
```

`greeting.toml`：

```toml
[greeting]
message = "你好，Aurora！"
```

执行 `aurora config greeting --init` 创建个人配置，然后运行 `aurora greet`。它也自动出现在配置总览中，支持 `--check`、`--raw`、`--edit` 和 `--set`。`aurora start` 会补齐并加载所有入选配置，Bot 通过注入的 `Settings.resolve(Greeting)` 读取值；运行能力仍需声明自身的 Bot 模组。

配置路径以工作目录为基准，必须是相对文件路径；CLI 的配置读写拒绝越出工作目录的符号链接。模板及附属资源使用 `ConfigFile` 显式声明源文件与目标路径，初始化只补缺失文件。简单配置插件可使用 `config_plugin(namespace, CONFIG_SPEC, directory)`：读取目录内同名 TOML，并把 `resources/` 复制到配置文件去掉扩展名后的目录。

执行器参数中的 `root` 与 `cli` 由宿主提供，不应用作插件自定义参数的目标字段。`arguments.cli` 与 `ctx["aurora.cli"]["catalog"]` 是同一份 `PluginCatalog`，`ctx["aurora.cli"]["root"]` 为本次工作目录。需要读取多个配置时使用 `catalog.configs.load(root)`，返回只读 `AuroraConfig`。

## 发布安装入口

```toml
[project.entry-points.aurora_cli_plugin]
greeting = "my_package.module:MODULE"
```

发布包时一并包含模板与配套资源。内置插件与已安装插件使用相同的声明契约，安装包名不决定 namespace 或命令名；跨插件依赖使用明确的 namespace 名称。
