---
order: 5
---

# CLI 命令与配置插件

CLI 插件可以增加 `aurora` 子命令，以及通过 `aurora config` 管理的个人配置。

## 放置插件

本地插件相对于工作目录放置，可通过顶层 `--root` 指定其他工作目录：

| 来源         | 声明位置                                                             |
| ------------ | -------------------------------------------------------------------- |
| 工作目录插件 | `extensions/cli/*.py` 或 `extensions/cli/<name>/module.py`           |
| 已安装插件   | `aurora_cli_plugin` entry point 指向的声明对象或导出 `MODULE` 的模块 |

本地插件包可以使用相对导入。命令或配置重名会报错，不会覆盖已有贡献。CLI 插件与 Bot 插件使用不同入口；需要向 Bot 增加工具时，参见[模组开发](./core-development)。

插件导入只应声明功能，文件访问与连接等工作放在命令执行器中。CLI 命令使用同步执行器，资源由执行器负责释放。

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

在工作目录运行 `aurora hello Aurora` 即可看到问候。命令声明支持参数、选项和子命令。

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

执行 `aurora config greeting --init` 创建个人配置，然后运行 `aurora greet`。配置会出现在总览中，支持 `--check`、`--raw`、`--edit` 和 `--set`；`aurora start` 会补齐缺失的插件配置。

配置路径以工作目录为基准，必须是相对文件路径；CLI 的配置读写拒绝越出工作目录的符号链接。模板及附属资源使用 `ConfigFile` 显式声明源文件与目标路径，初始化只补缺失文件。简单配置插件可使用 `config_plugin(namespace, CONFIG_SPEC, directory)`：读取目录内同名 TOML，并把 `resources/` 复制到配置文件去掉扩展名后的目录。

执行器参数中的 `root` 与 `cli` 由宿主提供，不应用作插件自定义参数的目标字段。

## 发布安装入口

```toml
[project.entry-points.aurora_cli_plugin]
greeting = "my_package.module:MODULE"
```

发布包时一并包含模板与配套资源。内置插件与已安装插件使用相同的声明契约，安装包名不决定 namespace 或命令名；跨插件依赖使用明确的 namespace 名称。
