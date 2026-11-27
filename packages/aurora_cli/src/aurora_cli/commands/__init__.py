"""发现命令子包并安装 CLI 接收方，不维护具体命令列表。"""

from importlib import import_module
from pkgutil import iter_modules

from aurora_config import ConfigSchema, ConfigSpec, ConfigTemplate
from aurora_core.ctx import StateKey
from aurora_core.discovery import Plugin
from aurora_core.registry import DefinitionRegistry

from .._meta import COMMAND_SCHEMA, CONFIGURATION, HOST_DEFINITIONS
from ..declarations import COMMANDS, CONFIG, CommandReceiver


def install_commands(registry: DefinitionRegistry) -> None:
    """登记命令接收方、描述格式与配置状态。"""
    entries = [
        HOST_DEFINITIONS[COMMANDS].bind(CommandReceiver()),
        HOST_DEFINITIONS[COMMAND_SCHEMA].bind(
            {
                "help": "string",
                "operation": "完整操作 ID，与 executor 二选一",
                "executor": "接收 CommandContext 与命名参数的同步或异步 callable",
                "runtime": "是否需要运行期宿主；operation 固定为 true，executor 默认为 false",
                "arguments": "name/type/option/required 参数列表",
                "passthrough": "可选的非空透传帮助文本；执行器或 operation 接收原样字符串列表 passthrough",
            },
        ),
        HOST_DEFINITIONS[CONFIGURATION].bind(ConfigSpec(CONFIG, ConfigTemplate("aurora_cli"), ConfigSchema({}))),
        HOST_DEFINITIONS[CONFIG].bind(StateKey(ConfigSchema({}).validate, persistent=False)),
    ]
    registry.register_many(entries)


def discover_commands() -> tuple[Plugin, ...]:
    """仅扫描内置命令包的直接子包；每个包导出无参数 plugin 工厂。"""
    plugins = []
    for item in sorted(iter_modules(__path__), key=lambda item: item.name):
        if not item.ispkg or item.name.startswith("_"):
            continue
        module = import_module(f"{__name__}.{item.name}")
        factory = getattr(module, "plugin", None)
        if not callable(factory):
            raise TypeError(f"命令包 {module.__name__} 必须导出 plugin 工厂")
        plugin = factory()
        if not isinstance(plugin, Plugin):
            raise TypeError(f"命令包 {module.__name__} 的工厂必须返回 Plugin")
        plugins.append(plugin)
    return tuple(plugins)
