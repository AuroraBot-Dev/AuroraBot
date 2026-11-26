"""将产品快捷启动交给工作区 scripts，CLI 不承担产品装配或前端配置。"""

from functools import partial

from ...declarations import CommandContext, command_plugin
from ...utils.process import run_process


def dispatch(name: str, context: CommandContext, *, passthrough: list[str]) -> int:
    script = context.root / "scripts" / f"{name}.py"
    if not script.is_file() or not (context.root / "pyproject.toml").is_file():
        raise ValueError(f"项目根目录缺少 scripts/{name}.py 或 pyproject.toml，请指定 --root")
    return run_process(
        ["uv", "run", "--locked", "python", str(script), *passthrough], root=context.root, output=context.output
    )


def plugin():
    return command_plugin(
        __name__,
        {
            name: {
                "help": description,
                "executor": partial(dispatch, name),
                "passthrough": f"参数原样交给 scripts/{name}.py；无参数使用项目默认配置",
            }
            for name, description in (
                ("bot", "快速启动完整 Bot 后端，读取项目 .env 与 data"),
                ("panel", "快速启动 Panel 开发服务器，连接已有后端"),
                ("tui", "快速启动 TUI，使用项目 .env 中的访问令牌"),
            )
        },
    )
