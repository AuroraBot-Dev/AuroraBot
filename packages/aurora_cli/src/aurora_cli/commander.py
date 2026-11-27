"""发现命令、选择入口，并分派至项目工具或运行期宿主。"""

import logging
import sys
from collections.abc import Iterable
from importlib.metadata import version
from typing import TextIO

from aurora_core.admission import AdmissionStatus, inspect_admissions
from aurora_core.bootstrap import bootstrap
from aurora_core.discovery import Plugin, load_plugins, register_plugins
from aurora_core.lifecycle import install_lifecycle_slots
from aurora_host import AssemblyPlan, Host, read_assembly
from aurora_host.configuration import select_assembly
from aurora_logging import configure_logging

from . import host
from .commands import discover_commands, install_commands
from .declarations import COMMANDS, CommandContext, read_command
from .execution import execute_command
from .parsing import parse_command, root_parser
from .presentation import show_commands


async def run_cli(
    argv: list[str] | None = None,
    *,
    plugins: Iterable[Plugin] = (),
    output: TextIO | None = None,
    runtime: Host | None = None,
) -> int:
    output = sys.stdout if output is None else output
    if output is None:
        raise RuntimeError("标准输出不可用，请显式提供 output 文本流")
    parser = root_parser()
    options = parser.parse_args(argv)
    if options.command[:1] == ["--"]:
        options.command = options.command[1:]
    if options.version:
        print(f"aurora {version('aurora-cli')}", file=output)
        return 0
    console_level = logging.getLevelNamesMapping()[options.level]
    console_tracebacks = console_level == logging.DEBUG
    configure_logging(console_level=console_level, console_tracebacks=console_tracebacks)
    if options.connect_token_env is not None and options.connect is None:
        parser.error("--connect-token-env 必须与 --connect 同时使用")
    if options.connect is not None and (
        options.data_dir is not None or options.assembly_file is not None or options.config is not None
    ):
        parser.error("--connect 不能与 --data-dir、--assembly-file 或 --config 同时使用")
    if runtime is not None and (options.assembly_file is not None or options.connect is not None):
        parser.error("已提供程序化宿主，不能同时选择 --assembly-file 或 --connect")
    registry = bootstrap() if runtime is None else runtime.registry
    if (
        options.connect is None
        and options.assembly_file is None
        and options.data_dir is not None
        and runtime is None
        and (options.data_dir / "config/host.toml").exists()
    ):
        options.assembly_file = select_assembly(options.data_dir)
    plan = (
        read_assembly(options.assembly_file)
        if options.assembly_file is not None
        else AssemblyPlan.parse({"schema_version": 2, "plugins": [], "instances": {}})
    )
    install_commands(registry)
    if runtime is None:
        install_lifecycle_slots(registry)
    if options.assembly_file is not None:
        plugins = tuple(item for item in plugins if item.name in plan.plugins)
    loaded = load_plugins(explicit=(*discover_commands(), *plugins), enabled=plan.plugins)
    register_plugins(registry, loaded)
    accepted = {
        admission.source
        for admission in inspect_admissions(registry)
        if admission.target == COMMANDS and admission.status == AdmissionStatus.ACCEPTED
    }
    commands = {entry.id: read_command(entry) for entry in registry.view(register_to=COMMANDS) if entry.id in accepted}
    if options.show_help or not options.command:
        if options.show_help:
            print(parser.format_help(), file=output)
        show_commands(commands.values(), output)
        return 0
    name, arguments = options.command[0], options.command[1:]
    while ":" not in name:
        group = [
            item
            for item in commands.values()
            if item.id.namespace == options.namespace and item.id.local_path.startswith(f"{name}/")
        ]
        if not group:
            break
        if not arguments or arguments[0] in ("--help", "-h"):
            show_commands(group, output)
            return 0
        name, arguments = f"{name}/{arguments[0]}", arguments[1:]
    try:
        entry = registry.resolve(name, namespace=options.namespace, domain="commands")
        command = commands[entry.id]
    except (ValueError, KeyError) as error:
        parser.error(f"命令不可用：{name}（{error}）")
    values = parse_command(command, arguments)
    if options.connect is not None:
        from . import remote

        if command.id not in remote.COMMANDS:
            parser.error("--connect 仅支持内置 ctx get/list/set/delete/watch 命令")
        return await remote.execute(options.connect, command.id, values, output, token_env=options.connect_token_env)
    context = CommandContext(options.root.resolve(), output, registry, tuple(commands.values()))
    if not command.runtime:
        if options.config is not None:
            parser.error("--config 仅适用于运行期宿主命令")
        return await execute_command(command, context, values)
    if options.data_dir is None:
        parser.error("执行宿主命令必须指定 --data-dir")
    configure_logging(
        log_dir=options.data_dir.resolve() / "logs",
        console_level=console_level,
        console_tracebacks=console_tracebacks,
    )
    return await host.execute(
        context,
        command,
        values,
        data_dir=options.data_dir,
        runtime=runtime,
        config=options.config,
        plan=plan,
        plugins=loaded,
    )
