"""落盘的第三方 CLI 插件；通过公开声明同时贡献命令与自定义路径配置。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


_MODULE = """from pathlib import Path
from aurora_cli.contracts.config import ConfigSpec, TableShape, text_field
from aurora_cli.plugins import CliPlugin, CommandContribution, ConfigContribution, ConfigFile
from aurora_kernel import namespace
from .values import ExtraSettings

SPEC = ConfigSpec("extra", "settings/custom.toml", shape=TableShape(
    ("extra",), (text_field("message"),), ExtraSettings,
))

@namespace("test.extra", requires=("aurora.cli",))
def extra(ctx):
    ctx["test.extra"]["calls"] = 0

@extra.callpoint("execute")
def execute(ctx, args):
    catalog = ctx["aurora.cli"]["catalog"]
    assert catalog is args.cli
    assert ctx["aurora.cli"]["root"] == args.root
    value = catalog.configs.spec("extra").load(args.root)
    ctx["test.extra"]["calls"] += 1
    print(value.message, ctx["test.extra"]["calls"])
    return 0

MODULE = CliPlugin(
    extra,
    commands=(CommandContribution({"name": "greet", "help": "插件问候"}, "test.extra:execute"),),
    configs=(ConfigContribution(SPEC, (
        ConfigFile(Path(__file__).with_name("extra.toml"), SPEC.path),
        ConfigFile(Path(__file__).with_name("note.md"), "settings/extra/note.md"),
    )),),
)
"""


def write_plugin(root: Path, message: str = "来自插件") -> Path:
    directory = root / "extensions/cli/example"
    directory.mkdir(parents=True)
    (directory / "module.py").write_text(_MODULE, encoding="utf-8")
    (directory / "values.py").write_text(
        "from dataclasses import dataclass\n@dataclass(frozen=True, slots=True)\n"
        "class ExtraSettings:\n    message: str\n",
        encoding="utf-8",
    )
    (directory / "extra.toml").write_text(f'[extra]\nmessage = "{message}"\n', encoding="utf-8")
    (directory / "note.md").write_text("配套资源\n", encoding="utf-8")
    return directory
