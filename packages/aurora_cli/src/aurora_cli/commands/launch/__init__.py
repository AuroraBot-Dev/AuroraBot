"""将产品快捷启动交给工作区 scripts，CLI 不承担产品装配或前端配置。"""

from functools import partial

from ...declarations import CommandContext, builtin_commands
from ...utils.process import run_process


def dispatch(name: str, context: CommandContext, *, passthrough: list[str]) -> int:
    script = context.root / "scripts" / f"{name}.py"
    if not script.is_file() or not (context.root / "pyproject.toml").is_file():
        raise ValueError(f"项目根目录缺少 scripts/{name}.py 或 pyproject.toml，请指定 --root")
    return run_process(
        ["uv", "run", "--locked", "python", str(script), *passthrough], root=context.root, output=context.output
    )


def plugin():
    return builtin_commands(
        __name__,
        {"bot": partial(dispatch, "bot"), "panel": partial(dispatch, "panel"), "tui": partial(dispatch, "tui")},
    )
