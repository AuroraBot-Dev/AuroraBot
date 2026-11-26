"""命令声明接收与 argv 转换；业务执行目标由公共操作 ID 引用。"""

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from aurora_core.discovery import Plugin
from aurora_core.ids import Id
from aurora_core.registry import DefinitionRegistry, RegistryEntry

COMMANDS = Id("org.aurora.cli:registries/commands")
CONFIG = Id("org.aurora.cli:state/config")


ARGUMENT_TYPES = frozenset({"string", "integer", "json", "id", "location", "flag"})
ALLOWED_SPEC_FIELDS = frozenset(
    {"help", "operation", "arguments", "executor", "runtime", "assembly_argument", "passthrough"}
)
ALLOWED_ARGUMENT_FIELDS = frozenset({"name", "type", "option", "required"})


@dataclass(frozen=True)
class Command:
    """CLI 接收方校验后的描述，不要求声明方导入此类型。"""

    id: Id
    help: str
    operation: Id | None
    arguments: tuple[dict[str, Any], ...]
    executor: Callable[..., object] | None = None
    runtime: bool = True
    assembly_argument: str | None = None
    passthrough: str | None = None


@dataclass(frozen=True)
class CommandContext:
    """命令执行依赖；registry 在运行期已绑定 core 状态操作。"""

    root: Path
    output: TextIO
    registry: DefinitionRegistry
    commands: tuple[Command, ...]


def command_plugin(
    provider: str, definitions: Mapping[str, Mapping[str, object]], *, namespace: str = "org.aurora.cli"
) -> Plugin:
    """为自包含命令包生成 core 插件清单，路径相对于 commands 域。"""
    return Plugin(
        provider,
        tuple(
            RegistryEntry(
                Id(f"{namespace}:commands/{name}"),
                "command",
                dict(spec),
                provider,
                register_to=COMMANDS,
            )
            for name, spec in definitions.items()
        ),
    )


def read_command(entry: RegistryEntry) -> Command:
    if entry.kind != "command" or not isinstance(entry.target, Mapping):
        raise TypeError("命令必须使用 command kind 和映射描述")
    spec = entry.target
    if set(spec) - ALLOWED_SPEC_FIELDS or not isinstance(spec.get("help"), str):
        raise ValueError("命令描述缺少 help 或包含不支持的字段")
    operation = Id(spec["operation"]) if "operation" in spec else None
    executor = spec.get("executor")
    if executor is not None and not callable(executor):
        raise TypeError("executor 必须为可调用对象")
    if (operation is None) == (executor is None):
        raise ValueError("命令必须且只能声明 operation 或 executor")
    runtime = spec.get("runtime", operation is not None)
    if type(runtime) is not bool:
        raise TypeError("runtime 必须为布尔值")
    if operation is not None and not runtime:
        raise ValueError("operation 命令需要运行期宿主")
    arguments = spec.get("arguments", [])
    if not isinstance(arguments, (list, tuple)):
        raise TypeError("命令 arguments 必须为列表或元组")
    names = set()
    for argument in arguments:
        if not isinstance(argument, dict) or set(argument) - ALLOWED_ARGUMENT_FIELDS:
            raise ValueError("参数仅支持 name、type、option、required")
        name = argument.get("name")
        if (
            not isinstance(name, str)
            or not name.isidentifier()
            or not name.isascii()
            or name in names
            or name == "help"
        ):
            raise ValueError("参数名称须为不重复的 ASCII 标识符，且不能为 help")
        names.add(name)
        if argument.get("type", "string") not in ARGUMENT_TYPES:
            raise ValueError(f"不支持的参数类型：{argument.get('type')}")
        if any(key in argument and type(argument[key]) is not bool for key in ("option", "required")):
            raise TypeError("option 和 required 必须为布尔值")
        if not argument.get("option", False) and argument.get("required", True) is False:
            raise ValueError("可选参数须使用 option=true")
        if argument.get("type") == "flag" and not argument.get("option", False):
            raise ValueError("flag 类型仅支持命名选项")
    passthrough = spec.get("passthrough")
    if "passthrough" in spec:
        if not isinstance(passthrough, str) or not passthrough.strip():
            raise ValueError("passthrough 必须为非空帮助文本")
        if "passthrough" in names:
            raise ValueError("透传命令不能同时声明名为 passthrough 的参数")
    assembly_argument = spec.get("assembly_argument")
    if assembly_argument is not None and (
        not runtime
        or not isinstance(assembly_argument, str)
        or not any(item["name"] == assembly_argument and item.get("type") == "id" for item in arguments)
    ):
        raise ValueError("assembly_argument 须引用运行期命令的 id 类型参数")
    return Command(
        entry.id,
        spec["help"],
        operation,
        tuple(deepcopy(arguments)),
        executor,
        runtime,
        assembly_argument,
        passthrough,
    )


class CommandReceiver:
    def rejection_reason(self, entry: RegistryEntry) -> str | None:
        try:
            read_command(entry)
        except (TypeError, ValueError) as error:
            return str(error)
        return None
