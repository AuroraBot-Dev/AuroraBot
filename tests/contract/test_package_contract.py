"""验证分发依赖、公共命名空间与插件入口的快速跨包契约。"""

from importlib import metadata

from aurora_core.discovery import ENTRY_POINT_GROUP, load_plugins


def test_control_distribution_owns_its_plugin_and_definitions():
    assert metadata.requires("aurora-control") == ["aurora-core>=0.1.0"]
    entries = [point for point in metadata.entry_points(group=ENTRY_POINT_GROUP) if point.name == "aurora_control"]
    assert len(entries) == 1
    assert entries[0].value == "aurora_control:plugin"
    plugin = load_plugins(enabled=["aurora_control"])[0]
    assert all(
        entry.id.namespace == "org.aurora.control" and entry.provider == "aurora_control" for entry in plugin.entries
    )


def test_agent_distribution_owns_its_plugins_and_definitions():
    requirements = metadata.requires("aurora-agent")
    assert requirements is not None
    assert not any(requirement.startswith(("aurora-bot", "aurora-cli", "aurora-api")) for requirement in requirements)
    entries = metadata.entry_points(group=ENTRY_POINT_GROUP)
    names = []
    for module in ("react", "react_defaults", "model", "tools"):
        names.append(f"aurora_agent.{module}")
        matches = [point for point in entries if point.name == names[-1]]
        assert len(matches) == 1
        assert matches[0].value == f"aurora_agent.{module}:plugin"
    plugins = load_plugins(enabled=names)
    assert all(
        entry.id.namespace == "org.aurora.agent" and entry.provider == "aurora_agent"
        for plugin in plugins
        for entry in plugin.entries
    )


def test_workspace_plugins_use_the_aurora_discovery_group():
    for name in ("aurora-agent", "aurora-control", "aurora-bot", "aurora-adapter", "aurora-world"):
        points = metadata.distribution(name).entry_points
        assert points and all(point.group == "aurora.plugins" for point in points)


def test_self_control_definitions_are_bot_owned_and_configuration_is_opt_in():
    from aurora_agent.tools import ToolSpec
    from aurora_bot.assembly import plugin
    from aurora_bot.assembly_config import parse_config
    from aurora_bot.self_control import COMPONENT, SELF_TOOLS
    from aurora_bot.self_control_state import SELF_CONTROL

    entries = {entry.id: entry for entry in plugin().entries}
    expected = {SELF_CONTROL, COMPONENT, *SELF_TOOLS.values()}
    assert expected <= entries.keys()
    assert all(entries[identity].provider == "aurora_bot" for identity in expected)
    names = set()
    for identity in SELF_TOOLS.values():
        spec = entries[identity].target
        assert isinstance(spec, ToolSpec)
        names.add(spec.definition["name"])
    assert names == {
        "bot_status",
        "bot_autonomy",
        "bot_finish",
        "wake_schedule",
        "wake_list",
        "wake_cancel",
    }
    assert parse_config({"instance_id": "main", "model_role": "reasoning"})["self_control"] == {"enabled": False}


def test_adapter_templates_share_one_package_without_path_collisions(tmp_path):
    from aurora_config.files import configuration_files
    from aurora_core.bootstrap import bootstrap
    from aurora_core.discovery import register_plugins

    registry = bootstrap()
    register_plugins(registry, load_plugins(enabled=["aurora_config", "aurora_adapter.model", "aurora_adapter.mcp"]))
    files = configuration_files(registry, tmp_path)
    assert {item.path.relative_to(tmp_path).as_posix() for item in files} == {
        "org.aurora.adapter/model/profiles.toml",
        "org.aurora.adapter/model/bindings.toml",
        "org.aurora.adapter/mcp.toml",
    }
    assert all(item.spec.template.package == "aurora_adapter" for item in files)
    assert all(item.spec.template.source().read_bytes() for item in files)
