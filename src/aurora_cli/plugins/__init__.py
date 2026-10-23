"""CLI 插件声明与装配入口；内置与外部插件使用相同协议。"""

from aurora_cli.contracts.plugin import CliPlugin, CommandContribution, ConfigContribution, ConfigFile
from aurora_cli.plugins.declaration import command_plugin, config_plugin

__all__ = ["CliPlugin", "CommandContribution", "ConfigContribution", "ConfigFile", "command_plugin", "config_plugin"]
