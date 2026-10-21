from __future__ import annotations

import argparse
import shlex
from contextlib import redirect_stderr
from dataclasses import dataclass, replace
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from textwrap import dedent
from typing import TYPE_CHECKING

import tomlkit
from rich.console import Console

from aurora_cli.commander import build_registry, run
from aurora_cli.commands.config import MODULE as CONFIG_COMMAND
from aurora_cli.contracts.config import ConfigSpec, TableShape, text_field
from aurora_cli.plugins import CliPlugin, CommandContribution, ConfigContribution, command_plugin, config_plugin
from aurora_cli.plugins.catalog import load_plugins
from aurora_cli.plugins.discovery import DiscoveredPlugin, plugin_spec
from aurora_cli.utils.process import EXIT_CONFIG_ERROR
from aurora_kernel import Context, ModuleSpec, namespace
from aurora_kernel.discovery import DirectorySource, StaticSource

if TYPE_CHECKING:
    from aurora_cli.contracts.command import CommandRegistry, CommandSpec
    from aurora_cli.plugins.catalog import PluginCatalog

console = Console(highlight=False, markup=False)


@dataclass(frozen=True, slots=True)
class Greeting:
    message: str


GREETING_CONFIG = ConfigSpec(
    "greeting",
    "config/greeting.toml",
    shape=TableShape(("greeting",), (text_field("message"),), Greeting),
)

COMMAND: CommandSpec = {
    "name": "demo",
    "help": "演示参数解析和命令分派",
    "subcommands": {
        "greet": {
            "help": "向指定对象问候",
            "args": {"name": "称呼"},
            "options": {"--uppercase": "将称呼转换为大写"},
        },
        "forward": {"help": "查看透传参数", "passthrough": "传给目标程序的参数"},
    },
}

LOCAL_PLUGIN = dedent("""\
    import argparse
    import sys

    from aurora_cli.plugins import command_plugin


    def execute(arguments: argparse.Namespace) -> int:
        sys.stdout.write(f"本地插件收到称呼：{arguments.name}\\n")
        return 0


    MODULE = command_plugin(
        "playground.local",
        {
            "name": "local",
            "help": "运行临时目录中的插件",
            "args": {"name": "称呼"},
        },
        execute,
    )
""")


def show(label: str, value: object) -> None:
    console.print(f"  {label}：{value}")


def invoke(registry: CommandRegistry, *arguments: str, expected: int = 0) -> None:
    console.print(f"\n$ aurora {shlex.join(arguments)}")
    errors = StringIO()
    with redirect_stderr(errors):
        try:
            code = run(arguments, registry=registry)
        except SystemExit as error:
            code = error.code
    if message := errors.getvalue().strip():
        console.print(message)
    show("退出码", code)
    if code != expected:
        raise AssertionError(f"预期退出码 {expected}，实际为 {code}")


def catalog_for(root: Path, *plugins: CliPlugin) -> PluginCatalog:
    declarations = tuple(DiscoveredPlugin(plugin, f"playground:{index}") for index, plugin in enumerate(plugins))
    return load_plugins(root, sources=(StaticSource(declarations),))


def execute_demo(arguments: argparse.Namespace) -> int:
    if arguments.subcommand == "greet":
        name = arguments.name.upper() if arguments.uppercase else arguments.name
        show("问候", f"你好，{name}！")
    else:
        show("透传参数", arguments.passthrough)
    show("显式目录不会注入插件宿主", not hasattr(arguments, "cli"))
    return 0


def demo_commands(name: str) -> None:
    console.rule("commands · 命令规格、帮助、参数与退出码")
    registry = build_registry(((COMMAND, execute_demo),))
    invoke(registry, "demo")
    invoke(registry, "demo", "greet", name)
    invoke(registry, "demo", "greet", name, "--uppercase")
    invoke(registry, "demo", "greet", name, "--upper", expected=EXIT_CONFIG_ERROR)
    invoke(registry, "demo", "forward", "--", "--root", "elsewhere", "--version")


def greeting_plugin(events: list[str]) -> CliPlugin:
    @namespace("playground.greeting", requires=("aurora.cli",))
    def greeting(ctx: Context) -> None:
        events.append("construct")
        ctx["playground.greeting"]["calls"] = 0

    @greeting.callpoint("execute")
    def execute(ctx: Context, arguments: argparse.Namespace) -> int:
        events.append("execute")
        ctx["playground.greeting"]["calls"] += 1
        show("问候", f"你好，{arguments.name}！")
        show("当前 Host 内调用次数", ctx["playground.greeting"]["calls"])
        show("执行器与 ctx 共用目录", arguments.cli is ctx["aurora.cli"]["catalog"])
        show("执行器与 ctx 共用根目录", arguments.root == ctx["aurora.cli"]["root"])
        assert ctx["playground.greeting"]["calls"] == 1
        assert arguments.cli is ctx["aurora.cli"]["catalog"]
        assert arguments.root == ctx["aurora.cli"]["root"]
        return 0

    spec: CommandSpec = {"name": "greet", "help": "观察插件宿主", "args": {"name": "称呼"}}
    return CliPlugin(greeting, commands=(CommandContribution(spec, "playground.greeting:execute"),))


def demo_plugins(root: Path, name: str) -> None:
    console.rule("plugins · 目录发现、声明校验与独立宿主")
    directory = root / "extensions/cli"
    directory.mkdir(parents=True)
    (directory / "hello.py").write_text(LOCAL_PLUGIN, encoding="utf-8")
    events: list[str] = []
    catalog = load_plugins(
        root,
        sources=(
            StaticSource((DiscoveredPlugin(greeting_plugin(events), "playground:memory"),)),
            DirectorySource(directory, extract=plugin_spec),
        ),
    )
    show("发现的命令", tuple(command.spec["name"] for command in catalog.commands))
    show("发现后的构造与执行记录", events)
    assert not events
    registry = catalog.registry()
    invoke(registry, "--help")
    show("帮助输出后的构造与执行记录", events)
    assert not events
    invoke(registry, "greet", name)
    invoke(registry, "greet", name)
    show("每次调用独立构造 Host", events)
    assert events == ["construct", "execute", "construct", "execute"]
    invoke(registry, "local", name)


def demo_config(root: Path, message: str) -> None:
    console.rule("config · 模板、个人配置、类型化读取与资源补齐")
    templates = root / "templates"
    resources = templates / "resources"
    resources.mkdir(parents=True)
    (templates / "greeting.toml").write_text('[greeting]\nmessage = "你好"\n', encoding="utf-8")
    (resources / "greeting.txt").write_text("问候资源\n", encoding="utf-8")
    plugin = config_plugin("playground.settings", GREETING_CONFIG, templates)
    catalog = catalog_for(root, CONFIG_COMMAND, plugin)
    registry = catalog.registry()

    invoke(registry, "config", "greeting", "--missing")
    assert not (root / "config").exists()
    invoke(registry, "config", "greeting", "--init")
    invoke(registry, "config", "greeting", "--raw")
    invoke(registry, "config", "greeting", "--set", f"greeting.message={tomlkit.string(message).as_string()}")
    invoke(registry, "config", "greeting")

    config = catalog.configs.load(root)
    show("按规格读取", config.get(GREETING_CONFIG))
    show("按 DTO 类型读取", config.resolve(Greeting))
    override = config.with_value(GREETING_CONFIG, Greeting("仅替换内存值"))
    show("替换后的集合", override.get(GREETING_CONFIG))
    show("原集合保留原值", config.get(GREETING_CONFIG))
    assert config.get(GREETING_CONFIG).message == message

    personal = catalog.configs.path(root, "greeting")
    content = personal.read_bytes()
    resource = root / "config/greeting/greeting.txt"
    resource.unlink()
    invoke(registry, "config", "greeting", "--missing")
    invoke(registry, "config", "greeting", "--init")
    show("补齐资源后个人配置保持原样", personal.read_bytes() == content)
    show("再次初始化创建的文件", catalog.configs.initialize(root))
    assert personal.read_bytes() == content
    assert resource.read_text(encoding="utf-8") == "问候资源\n"
    assert catalog.configs.missing(root) == {}


def demo_validation(root: Path) -> None:
    console.rule("validation · 在构造和文件写入前拒绝无效声明")
    events: list[str] = []
    guard = greeting_plugin(events)
    duplicate = command_plugin("playground.duplicate", {"name": "greet"}, lambda _args: 0)
    missing = CliPlugin(ModuleSpec("playground.missing", depends=("absent",)))
    target = CliPlugin(
        ModuleSpec("playground.target"),
        commands=(CommandContribution({"name": "broken"}, "playground.target:absent"),),
    )
    unsafe = CliPlugin(
        ModuleSpec("playground.unsafe"),
        configs=(ConfigContribution(replace(GREETING_CONFIG, path="../outside.toml")),),
    )
    duplicate_config = CliPlugin(
        ModuleSpec("playground.configs"),
        configs=(
            ConfigContribution(GREETING_CONFIG),
            ConfigContribution(replace(GREETING_CONFIG, name="another")),
        ),
    )
    cases = {
        "命令重名": duplicate,
        "缺失依赖": missing,
        "调用点不存在": target,
        "配置路径越界": unsafe,
        "配置目标冲突": duplicate_config,
    }
    for label, invalid in cases.items():
        try:
            catalog_for(root, guard, invalid)
        except ValueError as error:
            show(label, error)
        else:
            raise AssertionError(f"应拒绝无效声明：{label}")
    show("实际构造与执行记录", events)
    show("项目目录是否被创建", root.exists())
    assert not events
    assert not root.exists()


def nonempty_text(value: str) -> str:
    if not value.strip():
        raise argparse.ArgumentTypeError("请输入非空文本")
    return value.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Aurora CLI Playground · 真实命令宿主与临时配置")
    parser.add_argument(
        "scene", nargs="?", default="all", choices=("all", "commands", "plugins", "config", "validation")
    )
    parser.add_argument("--name", default="Aurora", help="命令与插件场景使用的称呼")
    parser.add_argument(
        "--message", type=nonempty_text, default="来自个人配置的问候", help="config 场景写入的非空问候文本"
    )
    arguments = parser.parse_args()
    console.print("Aurora CLI Playground · 离线运行 / 临时目录 / 无需个人配置")
    with TemporaryDirectory(prefix="aurora-cli-playground-") as directory:
        root = Path(directory)
        if arguments.scene in ("all", "commands"):
            demo_commands(arguments.name)
        if arguments.scene in ("all", "plugins"):
            demo_plugins(root / "plugins", arguments.name)
        if arguments.scene in ("all", "config"):
            demo_config(root / "config", arguments.message)
        if arguments.scene in ("all", "validation"):
            demo_validation(root / "validation")
    console.print("\n演示完成，临时插件、配置和资源已清理。")


if __name__ == "__main__":
    main()
