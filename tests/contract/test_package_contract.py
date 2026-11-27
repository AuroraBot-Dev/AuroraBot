"""验证分发依赖、公共命名空间与插件入口的快速跨包契约。"""

from importlib import metadata

from aurora_core.discovery import ENTRY_POINT_GROUP, load_plugins


def test_host_dependencies_and_control_distribution_boundary():
    assert set(metadata.requires("aurora-host") or ()) == {
        "aurora-core>=0.1.0",
        "aurora-config>=0.1.0",
        "aurora-control>=0.1.0",
    }
    assert metadata.requires("aurora-control") == ["aurora-core>=0.1.0"]
    entries = [point for point in metadata.entry_points(group=ENTRY_POINT_GROUP) if point.name == "aurora_control"]
    assert len(entries) == 1
    assert entries[0].value == "aurora_control:plugin"
    plugin = load_plugins(enabled=["aurora_control"])[0]
    assert all(
        entry.id.namespace == "org.aurora.control" and entry.provider == "aurora_control" for entry in plugin.entries
    )


def test_agent_and_tools_distributions_own_their_plugins_and_definitions():
    requirements = metadata.requires("aurora-agent")
    assert requirements is not None
    assert not any(requirement.startswith(("aurora-bot", "aurora-cli", "aurora-api")) for requirement in requirements)
    entries = metadata.entry_points(group=ENTRY_POINT_GROUP)
    names = []
    for module in ("react", "react_defaults", "model"):
        names.append(f"aurora_agent.{module}")
        matches = [point for point in entries if point.name == names[-1]]
        assert len(matches) == 1
        path = "aurora_agent.plugins.model" if module == "model" else f"aurora_agent.{module}"
        assert matches[0].value == f"{path}:plugin"
    tools = load_plugins(enabled=["aurora_tools"])[0]
    assert all(entry.id.namespace == "org.aurora.tools" and entry.provider == "aurora_tools" for entry in tools.entries)
    assert {point.name for point in metadata.distribution("aurora-tools").entry_points} == {"aurora_tools"}
    assert not any(point.name == "aurora_agent.tools" for point in entries)
    tools_requirements = metadata.requires("aurora-tools")
    assert tools_requirements is not None
    assert not any(
        requirement.startswith(("aurora-model", "aurora-mcp", "aurora-agent", "aurora-bot", "aurora-cli", "aurora-api"))
        for requirement in tools_requirements
    )
    plugins = load_plugins(enabled=[*names, "aurora_tools"])
    assert all(
        entry.id.namespace == "org.aurora.agent" and entry.provider == "aurora_agent"
        for plugin in plugins
        if plugin.name != "aurora_tools"
        for entry in plugin.entries
    )


def test_workspace_plugins_use_the_aurora_discovery_group():
    for name in (
        "aurora-agent",
        "aurora-tools",
        "aurora-control",
        "aurora-bot",
        "aurora-model",
        "aurora-mcp",
        "aurora-world",
    ):
        points = metadata.distribution(name).entry_points
        assert points and all(point.group == "aurora.plugins" for point in points)


def test_self_control_definitions_are_bot_owned_and_configuration_is_opt_in():
    from aurora_bot.assembly import plugin
    from aurora_bot.assembly_config import parse_config
    from aurora_bot.self_control import COMPONENT, SELF_TOOLS
    from aurora_bot.self_control_state import SELF_CONTROL
    from aurora_tools.execution import ToolSpec

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


def test_model_and_mcp_templates_belong_to_independent_distributions(tmp_path):
    from aurora_config.files import configuration_files
    from aurora_core.bootstrap import bootstrap
    from aurora_core.discovery import register_plugins

    registry = bootstrap()
    register_plugins(
        registry,
        load_plugins(
            enabled=[
                "aurora_config",
                "aurora_model",
                "aurora_model.configuration",
                "aurora_model.litellm",
                "aurora_mcp",
            ]
        ),
    )
    files = configuration_files(registry, tmp_path)
    assert {item.path.relative_to(tmp_path).as_posix() for item in files} == {
        "org.aurora.model/profiles.toml",
        "org.aurora.model/bindings.toml",
        "org.aurora.mcp/plugin.config.toml",
    }
    assert {item.spec.template.package for item in files} == {"aurora_model", "aurora_mcp"}
    assert all(item.spec.template.source().read_bytes() for item in files)
