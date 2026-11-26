"""离线示例的配置模板，复用各插件的结构声明与状态地址。"""

from dataclasses import replace

from aurora_config import ConfigSpec, ConfigTemplate

_RESOURCES = {
    "org.aurora.bot:state/config": "bot.toml",
    "org.aurora.adapter:state/model/config": "model/profiles.toml",
    "org.aurora.adapter:state/model/bindings": "model/bindings.toml",
}


def configured_plugins(plugins):
    for plugin in plugins:
        entries = []
        for entry in plugin.entries:
            if isinstance(entry.target, ConfigSpec) and str(entry.target.state) in _RESOURCES:
                template = ConfigTemplate(__name__, "config.tomls/" + _RESOURCES[str(entry.target.state)])
                entry = replace(entry, target=replace(entry.target, template=template))
            entries.append(entry)
        yield replace(plugin, entries=tuple(entries))
