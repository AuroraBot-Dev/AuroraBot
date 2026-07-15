from __future__ import annotations

from pathlib import Path

import pytest

from src.localhost.configuration import ConfigurationError, load_configuration


def test_loads_deterministic_configuration_snapshot(project_root: Path) -> None:
    configuration = load_configuration(project_root)

    assert configuration.runtime.profile == "test"
    assert configuration.runtime.workspace == project_root / "data" / "kernel"
    assert configuration.soul_hash
    assert configuration.edges == {"message.received": ("builtin.decide",)}
    assert configuration.adapters[0].capabilities[0].id == "org.aurora.console.send_message"
    assert configuration.capability_definitions["org.aurora.console.send_message"].parameters_schema["type"] == "object"
    assert configuration.model_providers["test"].adapter == "litellm"


def test_rejects_non_loopback_production_debug_host(project_root: Path) -> None:
    config = project_root / "config" / "profiles" / "prod.toml"
    config.write_text('[runtime]\ndebug_host = "0.0.0.0"\n\n[logging]\nlevel = "INFO"\n', encoding="utf-8")

    with pytest.raises(ConfigurationError, match="loopback"):
        load_configuration(project_root, "prod")


def test_rejects_unknown_profile_configuration(project_root: Path) -> None:
    config = project_root / "config" / "profiles" / "test.toml"
    config.write_text('[unknown]\nvalue = "not allowed"\n', encoding="utf-8")

    with pytest.raises(ConfigurationError, match="unexpected"):
        load_configuration(project_root)


def test_continuation_edge_must_advance_episode_round(project_root: Path) -> None:
    nodes = project_root / "config" / "nodes.toml"
    nodes.write_text(
        nodes.read_text(encoding="utf-8") + '\n[[edge]]\nevent_type = "model.completed"\ntarget = "@continuation"\n',
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="advance round"):
        load_configuration(project_root)


def test_rejects_invalid_capability_result_mode(project_root: Path) -> None:
    apps = project_root / "config" / "apps.toml"
    apps.write_text(
        apps.read_text(encoding="utf-8").replace(
            'parameters_schema = { type = "object",',
            'result_mode = "sometimes"\nparameters_schema = { type = "object",',
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="result_mode"):
        load_configuration(project_root)


@pytest.mark.parametrize(
    ("table", "body", "message"),
    [
        ("runtime.scheduler", 'enabled = "yes"', "enabled must be boolean"),
        ("runtime.scheduler", "autonomous_daily_model_calls = 0", "positive integer"),
        ("runtime.scheduler", "autonomous_daily_tokens = false", "positive integer"),
        ("runtime.scheduler", "idle_initial_seconds = 60\nidle_max_seconds = 30", "at least"),
        ("runtime.scheduler", "idle_multiplier = 1", "greater than one"),
        ("runtime.interactive_episode", "max_model_calls = 0", "max_model_calls must be positive"),
        ("runtime.interactive_episode", "max_tool_calls = false", "max_tool_calls must be positive"),
        ("runtime.autonomous_episode", "max_duration_seconds = 0", "must be positive"),
    ],
)
def test_rejects_invalid_scheduler_and_episode_budgets(project_root: Path, table: str, body: str, message: str) -> None:
    config = project_root / "config" / "aurora.toml"
    config.write_text(config.read_text(encoding="utf-8") + f"\n[{table}]\n{body}\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match=message):
        load_configuration(project_root)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("debug_port = 8765", "debug_port = 70000", "valid port"),
        ("log_queries = false", 'log_queries = "false"', "must be booleans"),
        ('adapter = "litellm"', 'adapter = "unknown"', "unsupported"),
        ('provider = "test"', 'provider = "missing"', "unknown provider"),
        (
            'capabilities = ["chat", "stream", "structured_output", "json_text_fallback"]',
            'capabilities = "chat"',
            "contain strings",
        ),
    ],
)
def test_rejects_invalid_runtime_and_model_configuration(project_root: Path, old: str, new: str, message: str) -> None:
    config = project_root / "config" / "aurora.toml"
    config.write_text(config.read_text(encoding="utf-8").replace(old, new, 1), encoding="utf-8")

    with pytest.raises(ConfigurationError, match=message):
        load_configuration(project_root)


def test_responses_role_requires_native_responses_capability(project_root: Path) -> None:
    config = project_root / "config" / "aurora.toml"
    config.write_text(
        config.read_text(encoding="utf-8") + '\n[models.roles.agent]\nprovider = "test"\nmodel = "agent"\n'
        'endpoint = "responses"\ncapabilities = ["chat"]\n',
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="requires native_responses"):
        load_configuration(project_root)


def test_node_cannot_request_unavailable_capability(project_root: Path) -> None:
    nodes = project_root / "config" / "nodes.toml"
    nodes.write_text(
        nodes.read_text(encoding="utf-8").replace(
            'capabilities = ["org.aurora.console.send_message"]',
            'capabilities = ["org.aurora.missing"]',
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="unavailable capabilities"):
        load_configuration(project_root)
