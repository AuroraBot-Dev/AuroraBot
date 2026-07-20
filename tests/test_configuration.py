from __future__ import annotations

import hashlib
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from src.contracts.configuration import ConfigurationError, load_configuration
from src.contracts.configuration_preferences import load_preference

_DASHBOARD_PORT = 8000
_REPLY_ROUTE_TTL_SECONDS = 3600.0

_COMMUNICATION_APP = """[[app]]
package = "com.example.discord"
kind = "communication"
enabled = true
transport = "stdio"
working_dir = "."
command = ["python", "server.py"]
timeout_seconds = 30

[[app.tool]]
name = "com.example.discord.publish"
kind = "publication"

[[app.tool]]
name = "com.example.discord.inspect"
kind = "effect"

[[app.publication]]
capability = "com.example.discord.reply"
tool = "com.example.discord.publish"
operation = "reply"

[[app.publication]]
capability = "com.example.discord.relay"
tool = "com.example.discord.publish"
operation = "relay"

[[app.destination]]
alias = "discord.dev"
description = "Discord development channel"
capability = "com.example.discord.relay"
address_ref = "channel:configured-opaque-id"
allowed_source_audiences = ["owner.local", "com.example.qq:*"]
target_audience_ref = "com.example.discord:dev"
"""


def test_loads_deterministic_configuration_snapshot(project_root: Path) -> None:
    configuration = load_configuration(project_root)

    assert configuration.runtime.profile == "test"
    assert configuration.runtime.workspace == project_root / "data" / "kernel"
    assert configuration.communication.reply_route_ttl_seconds == _REPLY_ROUTE_TTL_SECONDS
    assert configuration.communication.relay_hop_limit == 1
    assert configuration.dashboard.port == _DASHBOARD_PORT
    assert configuration.dashboard.database_path == project_root / "data" / "dashboard" / "chat.sqlite3"
    assert configuration.dashboard.owner_username == "alice"
    assert configuration.soul_hash
    apps_source = next(source for source in configuration.sources if source.path.name == "apps.toml")
    assert configuration.apps_configuration_hash == apps_source.sha256
    assert {agent.id for agent in configuration.agents} == {"builtin.gate", "builtin.worker"}
    assert configuration.runtime.agents.root_profile == "builtin.gate"
    assert configuration.runtime.agents.memory_agent_profile is None
    assert configuration.apps == ()
    assert configuration.model_providers["test"].adapter == "litellm"
    source_paths = {source.path for source in configuration.sources}
    assert source_paths == {
        project_root / "config" / "aurora.toml",
        project_root / "config" / "agents.toml",
        project_root / "config" / "apps.toml",
    }
    aurora_source = next(source for source in configuration.sources if source.path.name == "aurora.toml")
    assert aurora_source.sha256 == hashlib.sha256(aurora_source.path.read_bytes()).hexdigest()
    with pytest.raises(TypeError):
        configuration.model_definitions["missing"] = configuration.model_definitions["fast"]  # type: ignore[index]


def test_loads_independent_immutable_preference_snapshot(project_root: Path) -> None:
    preference = load_preference(project_root)

    assert preference.platform.console.enabled is True
    assert preference.platform.console.terminal_logs is False
    assert preference.platform.dashboard.enabled is True
    assert preference.platform.dashboard.open_browser is False
    assert preference.platform.mcp.enabled is True
    assert preference.platform.mcp.terminal_logs is True
    assert preference.source.path == project_root / "config" / "preference.toml"
    assert preference.source.sha256 == hashlib.sha256(preference.source.path.read_bytes()).hexdigest()
    assert not hasattr(preference, "__dict__")
    with pytest.raises(FrozenInstanceError):
        preference.platform.console.enabled = False


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("terminal_logs = true", "terminal_logs = true\nextra = false", "unexpected"),
        ("open_browser = false\n", "", "missing"),
        ("terminal_logs = false", 'terminal_logs = "false"', "must be boolean"),
    ],
)
def test_rejects_invalid_preference_schema(project_root: Path, old: str, new: str, message: str) -> None:
    preference = project_root / "config" / "preference.toml"
    preference.write_text(preference.read_text(encoding="utf-8").replace(old, new, 1), encoding="utf-8")

    with pytest.raises(ConfigurationError, match=message):
        load_preference(project_root)


def test_preference_file_is_required(project_root: Path) -> None:
    (project_root / "config" / "preference.toml").unlink()

    with pytest.raises(ConfigurationError, match="does not exist"):
        load_preference(project_root)


def test_rejects_non_loopback_production_debug_host(project_root: Path) -> None:
    config = project_root / "config" / "profiles" / "prod.toml"
    config.write_text('[runtime]\ndebug_host = "0.0.0.0"\n\n[logging]\nlevel = "INFO"\n', encoding="utf-8")

    with pytest.raises(ConfigurationError, match="loopback"):
        load_configuration(project_root, "prod")


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('[dashboard]\nhost = "127.0.0.1"', '[dashboard]\nhost = "0.0.0.0"', "loopback"),
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
    config = project_root / "config" / "aurora.toml"
    config.write_text(config.read_text(encoding="utf-8").replace(old, new, 1), encoding="utf-8")

    with pytest.raises(ConfigurationError, match=message):
        load_configuration(project_root)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("reply_route_ttl_seconds = 3600.0", "reply_route_ttl_seconds = 0", "must be positive"),
        ("reply_route_ttl_seconds = 3600.0", "reply_route_ttl_seconds = true", "must be positive"),
        ("reply_route_ttl_seconds = 3600.0", "reply_route_ttl_seconds = nan", "must be positive"),
        ("reply_route_ttl_seconds = 3600.0", "reply_route_ttl_seconds = inf", "must be positive"),
        ("relay_hop_limit = 1", "relay_hop_limit = 2", "must be 1"),
        ("relay_hop_limit = 1", "relay_hop_limit = true", "must be 1"),
        ("relay_hop_limit = 1", "relay_hop_limit = 1\nunknown = true", "unexpected"),
    ],
)
def test_rejects_invalid_communication_configuration(project_root: Path, old: str, new: str, message: str) -> None:
    config = project_root / "config" / "aurora.toml"
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
    config = project_root / "config" / "aurora.toml"
    config.write_text(config.read_text(encoding="utf-8").replace(old, new, 1), encoding="utf-8")

    with pytest.raises(ConfigurationError, match=message):
        load_configuration(project_root)


def test_rejects_unknown_profile_configuration(project_root: Path) -> None:
    config = project_root / "config" / "profiles" / "test.toml"
    config.write_text('[unknown]\nvalue = "not allowed"\n', encoding="utf-8")

    with pytest.raises(ConfigurationError, match="unexpected"):
        load_configuration(project_root)


def test_kernel_workspace_is_fixed(project_root: Path) -> None:
    config = project_root / "config" / "aurora.toml"
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
    config = project_root / "config" / "aurora.toml"
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            'worker_profile = "builtin.worker"',
            'worker_profile = "builtin.worker"\nmemory_agent_profile = "missing"',
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="memory_agent_profile"):
        load_configuration(project_root)


def test_rejects_removed_app_tool_result_mode(project_root: Path) -> None:
    apps = project_root / "config" / "apps.toml"
    apps.write_text(
        """[[app]]
package = "org.example.test"
kind = "utility"
enabled = true
transport = "stdio"
working_dir = "."
command = ["python", "server.py"]
timeout_seconds = 30

[[app.tool]]
name = "org.example.test.run"
kind = "effect"
result_mode = "sometimes"
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="result_mode"):
        load_configuration(project_root)


def test_loads_strict_communication_app_configuration(project_root: Path) -> None:
    apps = project_root / "config" / "apps.toml"
    apps.write_text(_COMMUNICATION_APP, encoding="utf-8")

    configuration = load_configuration(project_root)

    assert len(configuration.apps) == 1
    app = configuration.apps[0]
    assert app.kind == "communication"
    assert [(tool.name, tool.kind) for tool in app.tools] == [
        ("com.example.discord.publish", "publication"),
        ("com.example.discord.inspect", "effect"),
    ]
    assert [(publication.capability, publication.tool, publication.operation) for publication in app.publications] == [
        ("com.example.discord.reply", "com.example.discord.publish", "reply"),
        ("com.example.discord.relay", "com.example.discord.publish", "relay"),
    ]
    assert app.destinations[0].alias == "discord.dev"
    assert app.destinations[0].allowed_source_audiences == ("owner.local", "com.example.qq:*")


def test_communication_destination_accepts_global_source_audience_wildcard(project_root: Path) -> None:
    apps = project_root / "config" / "apps.toml"
    apps.write_text(
        _COMMUNICATION_APP.replace('["owner.local", "com.example.qq:*"]', '["*"]'),
        encoding="utf-8",
    )

    destination = load_configuration(project_root).apps[0].destinations[0]

    assert destination.allowed_source_audiences == ("*",)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('kind = "communication"', 'kind = "service"', "app.kind"),
        ('kind = "publication"', 'kind = "other"', "tool.kind"),
        ('operation = "relay"', 'operation = "reply"', "exactly one reply"),
        ('operation = "relay"', 'operation = "broadcast"', "operation"),
        (
            'tool = "com.example.discord.publish"\noperation = "relay"',
            'tool = "com.example.discord.inspect"\noperation = "relay"',
            "publication tool",
        ),
        (
            'capability = "com.example.discord.relay"\naddress_ref',
            'capability = "com.example.discord.reply"\naddress_ref',
            "relay or proactive_send",
        ),
        ('alias = "discord.dev"', 'alias = "chat.dev"', "final segment"),
        ('"com.example.qq:*"', '"com.example.*:conversation"', "wildcard"),
        (
            'target_audience_ref = "com.example.discord:dev"',
            'target_audience_ref = "com.example.discord:*"',
            "exact audience",
        ),
    ],
)
def test_rejects_invalid_communication_app_configuration(project_root: Path, old: str, new: str, message: str) -> None:
    apps = project_root / "config" / "apps.toml"
    apps.write_text(_COMMUNICATION_APP.replace(old, new, 1), encoding="utf-8")

    with pytest.raises(ConfigurationError, match=message):
        load_configuration(project_root)


def test_rejects_duplicate_publication_capability(project_root: Path) -> None:
    apps = project_root / "config" / "apps.toml"
    apps.write_text(
        _COMMUNICATION_APP.replace(
            'capability = "com.example.discord.relay"\ntool =',
            'capability = "com.example.discord.reply"\ntool =',
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="duplicate app capability"):
        load_configuration(project_root)


def test_disabled_app_is_strictly_validated_but_excluded_from_snapshot(project_root: Path) -> None:
    apps = project_root / "config" / "apps.toml"
    disabled = """[[app]]
package = "org.example.disabled"
kind = "utility"
enabled = false
transport = "stdio"
working_dir = "."
command = ["python", "server.py"]
timeout_seconds = 30

[[app.tool]]
name = "org.example.disabled.run"
kind = "effect"
"""
    apps.write_text(disabled, encoding="utf-8")

    assert load_configuration(project_root).apps == ()

    apps.write_text(disabled.replace('kind = "effect"', 'kind = "publication"'), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="utility app tools"):
        load_configuration(project_root)


@pytest.mark.parametrize(
    ("table", "body", "message"),
    [
        ("runtime.scheduler", 'enabled = "yes"', "enabled must be boolean"),
        ("runtime.scheduler", "autonomous_daily_model_calls = 0", "positive integer"),
        ("runtime.scheduler", "autonomous_daily_tokens = false", "positive integer"),
        ("runtime.scheduler", "idle_initial_seconds = 60\nidle_max_seconds = 30", "at least"),
        ("runtime.scheduler", "idle_multiplier = 1", "greater than one"),
        ("runtime.interactive_task", "max_model_calls = 0", "max_model_calls must be positive"),
        ("runtime.interactive_task", "max_tool_calls = false", "max_tool_calls must be positive"),
        ("runtime.autonomous_task", "max_duration_seconds = 0", "must be positive"),
    ],
)
def test_rejects_invalid_scheduler_and_task_budgets(project_root: Path, table: str, body: str, message: str) -> None:
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
        config.read_text(encoding="utf-8").replace(
            'capabilities = ["chat", "stream", "structured_output", "json_text_fallback", "tools", "native_responses"]',
            'capabilities = ["chat"]',
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="requires native_responses"):
        load_configuration(project_root)


def test_agent_capabilities_are_authorization_limits_not_startup_availability(project_root: Path) -> None:
    agents = project_root / "config" / "agents.toml"
    agents.write_text(
        agents.read_text(encoding="utf-8").replace(
            'capabilities = ["org.aurora.console.send_message"]',
            'capabilities = ["org.aurora.missing"]',
            1,
        ),
        encoding="utf-8",
    )

    configuration = load_configuration(project_root)

    assert "org.aurora.missing" in configuration.agents[0].capabilities


def test_apps_rejects_removed_adapter_section(project_root: Path) -> None:
    apps = project_root / "config" / "apps.toml"
    apps.write_text("app = []\nadapter = []\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match=r"unexpected.*adapter"):
        load_configuration(project_root)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (("enabled", '"false"', "must be boolean"), ("timeout_seconds", "true", "must be positive")),
)
def test_apps_rejects_invalid_scalar_types(project_root: Path, field: str, value: str, message: str) -> None:
    apps = project_root / "config" / "apps.toml"
    apps.write_text(
        f"""[[app]]
package = "org.example.test"
kind = "utility"
enabled = {value if field == "enabled" else "true"}
transport = "stdio"
working_dir = "."
command = ["python", "server.py"]
timeout_seconds = {value if field == "timeout_seconds" else "30"}

[[app.tool]]
name = "org.example.test.run"
kind = "effect"
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match=message):
        load_configuration(project_root)
