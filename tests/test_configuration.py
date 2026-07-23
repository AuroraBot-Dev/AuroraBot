from __future__ import annotations

import hashlib
from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import pytest

from src.contracts.configuration import AppConfig, ConfigurationError, load_configuration

_DASHBOARD_PORT = 8000
_APP_TIMEOUT_SECONDS = 30.0

_STDIO_APP = """[[app]]
package = "com.example.tools"
enabled = true
transport = "stdio"
working_dir = "."
command = ["python", "server.py"]
timeout_seconds = 30
"""


def test_loads_deterministic_configuration_snapshot(project_root: Path) -> None:
    configuration = load_configuration(project_root)

    assert configuration.runtime.profile == "test"
    assert configuration.runtime.workspace == project_root / "data" / "kernel"
    assert configuration.dashboard.port == _DASHBOARD_PORT
    assert configuration.dashboard.database_path == project_root / "data" / "dashboard" / "chat.sqlite3"
    assert configuration.dashboard.owner_username == "alice"
    assert {agent.id for agent in configuration.agents} == {"builtin.gate", "builtin.worker"}
    assert all(not hasattr(agent, "prompt") for agent in configuration.agents)
    assert configuration.runtime.agents.root_profile == "builtin.gate"
    assert configuration.runtime.agents.memory_agent_profile is None
    assert configuration.apps == ()
    assert not hasattr(configuration, "apps_configuration_hash")
    assert {field.name for field in fields(AppConfig)} == {
        "package",
        "transport",
        "working_dir",
        "command",
        "url",
        "auth_env",
        "timeout_seconds",
    }
    assert configuration.model_providers["test"].adapter == "litellm"
    source_paths = {source.path for source in configuration.sources}
    assert source_paths == {
        project_root / "config" / "runtime.toml",
        project_root / "config" / "platforms.toml",
        project_root / "config" / "models.toml",
        project_root / "config" / "logging.toml",
        project_root / "config" / "agents.toml",
        project_root / "config" / "apps.toml",
    }
    runtime_source = next(source for source in configuration.sources if source.path.name == "runtime.toml")
    assert runtime_source.sha256 == hashlib.sha256(runtime_source.path.read_bytes()).hexdigest()
    with pytest.raises(TypeError):
        configuration.model_definitions["missing"] = configuration.model_definitions["fast"]  # type: ignore[index]


def test_loads_independent_immutable_preference_snapshot(project_root: Path) -> None:
    preference = load_configuration(project_root).preference

    assert preference.console.enabled is True
    assert preference.console.terminal_logs is False
    assert preference.dashboard.enabled is True
    assert preference.dashboard.open_browser is False
    assert preference.mcp.enabled is True
    assert preference.mcp.terminal_logs is True
    assert not hasattr(preference, "__dict__")
    with pytest.raises(FrozenInstanceError):
        preference.console.enabled = False  # type: ignore[misc]


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("enabled = true\n", "", "missing required keys"),
        ("open_browser = false\n", "", "missing"),
        ("terminal_logs = false", 'terminal_logs = "false"', "must be boolean"),
    ],
)
def test_rejects_invalid_preference_schema(project_root: Path, old: str, new: str, message: str) -> None:
    config = project_root / "config" / "platforms.toml"
    config.write_text(config.read_text(encoding="utf-8").replace(old, new, 1), encoding="utf-8")

    with pytest.raises(ConfigurationError, match=message):
        load_configuration(project_root)


def test_preference_platform_table_is_required(project_root: Path) -> None:
    config = project_root / "config" / "platforms.toml"
    config.write_text(
        config.read_text(encoding="utf-8").replace("[platform.console]", "[platform.removed]", 1), encoding="utf-8"
    )

    with pytest.raises(ConfigurationError, match="missing"):
        load_configuration(project_root)


def test_rejects_non_loopback_production_debug_host(project_root: Path) -> None:
    config = project_root / "config" / "profiles" / "prod.toml"
    config.write_text('[runtime]\ndebug_host = "0.0.0.0"\n', encoding="utf-8")

    with pytest.raises(ConfigurationError, match="loopback"):
        load_configuration(project_root, "prod")


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('host = "127.0.0.1"', 'host = "0.0.0.0"', "loopback"),
        ("port = 8000", "port = 70000", "valid port"),
        ("max_upload_bytes = 67108864", "max_upload_bytes = 0", "positive integer"),
        ('database_path = "data/dashboard/chat.sqlite3"', 'database_path = "../chat.sqlite3"', "project root"),
        (
            'database_path = "data/dashboard/chat.sqlite3"',
            'database_path = "data/kernel/process/runtime.sqlite3"',
            "Kernel workspace",
        ),
        ('upload_dir = "data/dashboard/uploads"', 'upload_dir = "data/kernel/inbox"', "Kernel workspace"),
    ],
)
def test_rejects_invalid_dashboard_configuration(project_root: Path, old: str, new: str, message: str) -> None:
    config = project_root / "config" / "platforms.toml"
    config.write_text(config.read_text(encoding="utf-8").replace(old, new, 1), encoding="utf-8")

    with pytest.raises(ConfigurationError, match=message):
        load_configuration(project_root)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('username = "alice"', 'username = ""', "non-empty string"),
        ('username = "alice"', 'username = " alice"', "leading or trailing whitespace"),
        ('username = "alice"', 'username = "alice "', "leading or trailing whitespace"),
        ('username = "alice"', 'username = "aurorabot"', "must differ"),
        ('username = "alice"', 'username = "alice"\nunknown = true', "unexpected"),
    ],
)
def test_rejects_invalid_dashboard_owner_configuration(project_root: Path, old: str, new: str, message: str) -> None:
    config = project_root / "config" / "platforms.toml"
    config.write_text(config.read_text(encoding="utf-8").replace(old, new, 1), encoding="utf-8")

    with pytest.raises(ConfigurationError, match=message):
        load_configuration(project_root)


def test_rejects_unknown_profile_configuration(project_root: Path) -> None:
    config = project_root / "config" / "profiles" / "test.toml"
    config.write_text('[unknown]\nvalue = "not allowed"\n', encoding="utf-8")

    with pytest.raises(ConfigurationError, match="unexpected"):
        load_configuration(project_root)


def test_kernel_workspace_is_fixed(project_root: Path) -> None:
    config = project_root / "config" / "runtime.toml"
    config.write_text(
        config.read_text(encoding="utf-8").replace('workspace = "data/kernel"', 'workspace = "data/other"'),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="must be data/kernel"):
        load_configuration(project_root)


def test_agent_child_profile_must_exist(project_root: Path) -> None:
    agents = project_root / "config" / "agents.toml"
    agents.write_text(
        agents.read_text(encoding="utf-8").replace(
            'child_profiles = ["builtin.worker"]', 'child_profiles = ["missing"]', 1
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="unknown child profiles"):
        load_configuration(project_root)


def test_memory_agent_profile_is_optional_but_must_exist(project_root: Path) -> None:
    config = project_root / "config" / "runtime.toml"
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            'worker_profile = "builtin.worker"',
            'worker_profile = "builtin.worker"\nmemory_agent_profile = "missing"',
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="memory_agent_profile"):
        load_configuration(project_root)


def test_loads_stdio_app_without_tool_allowlist(project_root: Path) -> None:
    apps = project_root / "config" / "apps.toml"
    apps.write_text(_STDIO_APP, encoding="utf-8")

    app = load_configuration(project_root).apps[0]

    assert app.package == "com.example.tools"
    assert app.transport == "stdio"
    assert app.working_dir == project_root
    assert app.command == ("python", "server.py")
    assert app.url is None
    assert app.auth_env is None
    assert app.timeout_seconds == _APP_TIMEOUT_SECONDS


def test_loads_streamable_http_app(project_root: Path) -> None:
    apps = project_root / "config" / "apps.toml"
    apps.write_text(
        """[[app]]
package = "com.example.remote"
enabled = true
transport = "streamable_http"
url = "https://example.com/mcp"
auth_env = "EXAMPLE_MCP_TOKEN"
timeout_seconds = 10
""",
        encoding="utf-8",
    )

    app = load_configuration(project_root).apps[0]

    assert app.url == "https://example.com/mcp"
    assert app.auth_env == "EXAMPLE_MCP_TOKEN"
    assert app.working_dir is None
    assert app.command == ()


@pytest.mark.parametrize("removed_field", ["kind", "tool", "publication", "destination"])
def test_apps_reject_removed_fields(project_root: Path, removed_field: str) -> None:
    apps = project_root / "config" / "apps.toml"
    apps.write_text(
        _STDIO_APP.replace("enabled = true", f'enabled = true\n{removed_field} = "removed"'),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="unsupported"):
        load_configuration(project_root)


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            _STDIO_APP.replace('command = ["python", "server.py"]', "command = []"),
            "non-empty string array",
        ),
        (
            _STDIO_APP.replace('working_dir = "."\n', ""),
            "working_dir is required",
        ),
        (
            _STDIO_APP.replace('transport = "stdio"', 'transport = "streamable_http"'),
            "must use HTTPS",
        ),
    ],
)
def test_rejects_invalid_app_connection_shape(project_root: Path, source: str, message: str) -> None:
    apps = project_root / "config" / "apps.toml"
    apps.write_text(source, encoding="utf-8")

    with pytest.raises(ConfigurationError, match=message):
        load_configuration(project_root)


def test_disabled_app_is_strictly_validated_but_excluded_from_snapshot(project_root: Path) -> None:
    apps = project_root / "config" / "apps.toml"
    disabled = _STDIO_APP.replace("enabled = true", "enabled = false")
    apps.write_text(disabled, encoding="utf-8")

    assert load_configuration(project_root).apps == ()

    apps.write_text(disabled.replace('command = ["python", "server.py"]', "command = []"), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="non-empty string array"):
        load_configuration(project_root)


@pytest.mark.parametrize(
    ("table", "body", "message"),
    [
        ("runtime.autonomy", "autonomous_daily_model_calls = 0", "positive integer"),
        ("runtime.autonomy", "autonomous_daily_tokens = false", "positive integer"),
        ("runtime.autonomy", "heartbeat_min_seconds = 60\nheartbeat_max_seconds = 30", "at least"),
        ("runtime.autonomy", "heartbeat_initial_seconds = 5\nheartbeat_min_seconds = 30", "within heartbeat bounds"),
        ("runtime.interactive_task", "max_model_calls = 0", "max_model_calls must be positive"),
        ("runtime.interactive_task", "max_tool_calls = false", "max_tool_calls must be positive"),
        ("runtime.autonomous_task", "max_duration_seconds = 0", "must be positive"),
    ],
)
def test_rejects_invalid_autonomy_and_task_budgets(project_root: Path, table: str, body: str, message: str) -> None:
    config = project_root / "config" / "runtime.toml"
    config.write_text(config.read_text(encoding="utf-8") + f"\n[{table}]\n{body}\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match=message):
        load_configuration(project_root)


@pytest.mark.parametrize(
    ("old", "new", "message", "config_file"),
    [
        ("debug_port = 8765", "debug_port = 70000", "valid port", "runtime.toml"),
        ("log_queries = false", 'log_queries = "false"', "must be booleans", "models.toml"),
        ('adapter = "litellm"', 'adapter = "unknown"', "unsupported", "models.toml"),
        ('provider = "test"', 'provider = "missing"', "unknown provider", "models.toml"),
        (
            'capabilities = ["chat", "stream", "structured_output", "json_text_fallback", "tools"]',
            'capabilities = "chat"',
            "contain strings",
            "models.toml",
        ),
    ],
)
def test_rejects_invalid_runtime_and_model_configuration(
    project_root: Path, old: str, new: str, message: str, config_file: str
) -> None:
    config = project_root / "config" / config_file
    config.write_text(config.read_text(encoding="utf-8").replace(old, new, 1), encoding="utf-8")

    with pytest.raises(ConfigurationError, match=message):
        load_configuration(project_root)


def test_responses_role_accepts_models_dev_capabilities(project_root: Path) -> None:
    """配置中不再强制声明 native_responses —— 由 models.dev 自动补充。"""
    config = project_root / "config" / "models.toml"
    old_caps = (
        'capabilities = ["chat", "stream", "structured_output", "json_text_fallback",'
        ' "tools", "native_responses", "reasoning"]'
    )
    modified = config.read_text(encoding="utf-8").replace(old_caps, 'capabilities = ["chat"]', 1)
    config.write_text(modified, encoding="utf-8")
    load_configuration(project_root)


def test_agent_capabilities_are_authorization_limits_not_startup_availability(project_root: Path) -> None:
    agents = project_root / "config" / "agents.toml"
    agents.write_text(
        agents.read_text(encoding="utf-8").replace(
            'capabilities = ["*"]',
            'capabilities = ["org.aurora.missing"]',
            1,
        ),
        encoding="utf-8",
    )

    configuration = load_configuration(project_root)

    assert "org.aurora.missing" in configuration.agents[0].capabilities


@pytest.mark.parametrize("capability", ["org.aurora.clock.get_time", "org.aurora.clock.*", "*"])
def test_agent_capability_patterns_are_supported(project_root: Path, capability: str) -> None:
    agents = project_root / "config" / "agents.toml"
    agents.write_text(
        agents.read_text(encoding="utf-8").replace('capabilities = ["*"]', f'capabilities = ["{capability}"]', 1),
        encoding="utf-8",
    )

    assert capability in load_configuration(project_root).agents[0].capabilities


@pytest.mark.parametrize("capability", ["org.*.clock", "org.aurora.clock*", "org aurora.clock", "single"])
def test_agent_capability_patterns_reject_invalid_shapes(project_root: Path, capability: str) -> None:
    agents = project_root / "config" / "agents.toml"
    agents.write_text(
        agents.read_text(encoding="utf-8").replace('capabilities = ["*"]', f'capabilities = ["{capability}"]', 1),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="capability"):
        load_configuration(project_root)


def test_apps_rejects_removed_adapter_section(project_root: Path) -> None:
    apps = project_root / "config" / "apps.toml"
    apps.write_text("app = []\nadapter = []\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match=r"unexpected.*adapter"):
        load_configuration(project_root)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("enabled", '"false"', "must be boolean"),
        ("timeout_seconds", "true", "must be positive"),
        ("timeout_seconds", "nan", "must be positive"),
        ("timeout_seconds", "inf", "must be positive"),
    ),
)
def test_apps_rejects_invalid_scalar_types(project_root: Path, field: str, value: str, message: str) -> None:
    apps = project_root / "config" / "apps.toml"
    apps.write_text(
        f"""[[app]]
package = "org.example.test"
enabled = {value if field == "enabled" else "true"}
transport = "stdio"
working_dir = "."
command = ["python", "server.py"]
timeout_seconds = {value if field == "timeout_seconds" else "30"}
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match=message):
        load_configuration(project_root)
