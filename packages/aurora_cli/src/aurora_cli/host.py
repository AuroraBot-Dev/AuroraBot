"""将 CLI 命令交给应用宿主执行；组件与生命周期由 aurora_host 管理。"""

from pathlib import Path
from typing import cast

from aurora_core.discovery import Plugin
from aurora_host import AssemblyPlan, Host

from .declarations import CONFIG, Command, CommandContext
from .execution import execute_command


async def execute(
    context: CommandContext,
    command: Command,
    values: dict[str, object],
    *,
    data_dir: Path,
    config: object,
    plan: AssemblyPlan,
    plugins: tuple[Plugin, ...],
    runtime: Host | None = None,
) -> int:
    host = runtime or Host(context.registry, data_dir, workspace_root=context.root)
    try:
        if runtime is None:
            host.assemble(plan, plugins)

        def configure() -> None:
            if config is not None:
                host.ctx.set(CONFIG, config)

        await host.start(configure=configure)
        return cast(int, await host.run(execute_command, command, context, values))
    finally:
        await host.stop()
