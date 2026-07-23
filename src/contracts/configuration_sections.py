"""Parsers for independently declared Agent, MCP App and Dashboard sections."""

from math import isfinite
from pathlib import Path
from typing import Any

from src.contracts.configuration import (
    AgentProfileConfig,
    AgentRuntimeConfig,
    AppConfig,
    AutonomyConfig,
    ConfigurationError,
    ConsolePreference,
    DashboardBotConfig,
    DashboardConfig,
    DashboardPreference,
    McpPreference,
    PlatformPreference,
    TaskBudgetConfig,
    _positive_number,
    _require_keys,
    _require_subset,
    _string,
    _table,
)


def _parse_autonomy(raw: dict[str, Any]) -> AutonomyConfig:
    defaults = AutonomyConfig()
    allowed = {
        "scan_seconds",
        "heartbeat_initial_seconds",
        "heartbeat_min_seconds",
        "heartbeat_max_seconds",
        "autonomous_daily_model_calls",
        "autonomous_daily_tokens",
    }
    if set(raw) - allowed:
        raise ConfigurationError("runtime.autonomy has unsupported keys")
    daily_calls = raw.get("autonomous_daily_model_calls", defaults.autonomous_daily_model_calls)
    daily_tokens = raw.get("autonomous_daily_tokens", defaults.autonomous_daily_tokens)
    if not isinstance(daily_calls, int) or isinstance(daily_calls, bool) or daily_calls <= 0:
        raise ConfigurationError("autonomous_daily_model_calls must be a positive integer")
    if not isinstance(daily_tokens, int) or isinstance(daily_tokens, bool) or daily_tokens <= 0:
        raise ConfigurationError("autonomous_daily_tokens must be a positive integer")
    minimum = _positive_number(
        raw.get("heartbeat_min_seconds", defaults.heartbeat_min_seconds), "heartbeat_min_seconds"
    )
    maximum = _positive_number(
        raw.get("heartbeat_max_seconds", defaults.heartbeat_max_seconds), "heartbeat_max_seconds"
    )
    if maximum < minimum:
        raise ConfigurationError("heartbeat_max_seconds must be at least heartbeat_min_seconds")
    initial = _positive_number(
        raw.get("heartbeat_initial_seconds", defaults.heartbeat_initial_seconds), "heartbeat_initial_seconds"
    )
    if not minimum <= initial <= maximum:
        raise ConfigurationError("heartbeat_initial_seconds must be within heartbeat bounds")
    return AutonomyConfig(
        scan_seconds=_positive_number(raw.get("scan_seconds", defaults.scan_seconds), "scan_seconds"),
        heartbeat_initial_seconds=initial,
        heartbeat_min_seconds=minimum,
        heartbeat_max_seconds=maximum,
        autonomous_daily_model_calls=daily_calls,
        autonomous_daily_tokens=daily_tokens,
    )


def _parse_task_budget(
    raw: dict[str, Any], default_calls: int, default_tools: int, default_duration: float, label: str
) -> TaskBudgetConfig:
    allowed = {"max_model_calls", "max_tool_calls", "max_duration_seconds"}
    if set(raw) - allowed:
        raise ConfigurationError(f"runtime.{label} has unsupported keys")
    calls = raw.get("max_model_calls", default_calls)
    tools = raw.get("max_tool_calls", default_tools)
    if not isinstance(calls, int) or isinstance(calls, bool) or calls <= 0:
        raise ConfigurationError(f"runtime.{label}.max_model_calls must be positive")
    if not isinstance(tools, int) or isinstance(tools, bool) or tools <= 0:
        raise ConfigurationError(f"runtime.{label}.max_tool_calls must be positive")
    return TaskBudgetConfig(calls, tools, _positive_number(raw.get("max_duration_seconds", default_duration), label))


def _parse_agents(data: dict[str, Any], model_roles: frozenset[str]) -> tuple[AgentProfileConfig, ...]:
    _require_keys(data, {"agent"}, "agents.toml")
    raw_agents = data["agent"]
    if not isinstance(raw_agents, list) or not raw_agents:
        raise ConfigurationError("agents.toml agent must be a non-empty array")
    agents: list[AgentProfileConfig] = []
    ids: set[str] = set()
    for raw in raw_agents:
        if not isinstance(raw, dict):
            raise ConfigurationError("agent must be a table")
        _require_keys(
            raw,
            {"id", "implementation", "model_role", "capabilities", "can_delegate", "child_profiles"},
            "agent",
        )
        agent_id = _string(raw["id"], "agent.id")
        if agent_id in ids:
            raise ConfigurationError(f"duplicate Agent profile {agent_id}")
        ids.add(agent_id)
        model_role = _string(raw["model_role"], "agent.model_role")
        if model_role not in model_roles:
            raise ConfigurationError(f"Agent {agent_id} references unknown model role {model_role}")
        capabilities = raw["capabilities"]
        children = raw["child_profiles"]
        if not isinstance(capabilities, list) or not all(isinstance(item, str) for item in capabilities):
            raise ConfigurationError(f"Agent {agent_id} capabilities must contain strings")
        for capability in capabilities:
            _capability_pattern(capability, f"Agent {agent_id} capability")
        if not isinstance(children, list) or not all(isinstance(item, str) for item in children):
            raise ConfigurationError(f"Agent {agent_id} child_profiles must contain strings")
        if not isinstance(raw["can_delegate"], bool):
            raise ConfigurationError(f"Agent {agent_id} can_delegate must be boolean")
        agents.append(
            AgentProfileConfig(
                id=agent_id,
                implementation=_string(raw["implementation"], "agent.implementation"),
                model_role=model_role,
                capabilities=frozenset(capabilities),
                can_delegate=raw["can_delegate"],
                child_profiles=frozenset(children),
            )
        )
    for agent in agents:
        if not agent.child_profiles <= ids:
            raise ConfigurationError(f"Agent {agent.id} references unknown child profiles")
        if not agent.can_delegate and agent.child_profiles:
            raise ConfigurationError(f"Agent {agent.id} cannot declare child_profiles when delegation is disabled")
    return tuple(agents)


def _parse_agent_runtime(raw: dict[str, Any]) -> AgentRuntimeConfig:
    defaults = AgentRuntimeConfig()
    allowed = set(AgentRuntimeConfig.__dataclass_fields__)
    if set(raw) - allowed:
        raise ConfigurationError("runtime.agents has unsupported keys")
    values: dict[str, Any] = {}
    for name in allowed:
        value = raw.get(name, getattr(defaults, name))
        if name == "memory_agent_profile":
            values[name] = None if value is None else _string(value, "runtime.agents.memory_agent_profile")
        elif name in {"root_profile", "worker_profile"}:
            values[name] = _string(value, f"runtime.agents.{name}")
        elif name in {"lease_seconds", "ambient_ttl_seconds"}:
            values[name] = _positive_number(value, f"runtime.agents.{name}")
        elif not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ConfigurationError(f"runtime.agents.{name} must be a positive integer")
        else:
            values[name] = value
    if values["max_depth"] > values["max_agents_per_task"]:
        raise ConfigurationError("runtime.agents.max_depth cannot exceed max_agents_per_task")
    return AgentRuntimeConfig(**values)


def _parse_apps(raw_apps: object, root: Path) -> tuple[AppConfig, ...]:
    if not isinstance(raw_apps, list):
        raise ConfigurationError("app must be an array")
    apps: list[AppConfig] = []
    packages: set[str] = set()
    for raw in raw_apps:
        if not isinstance(raw, dict):
            raise ConfigurationError("app must be a table")
        allowed = {
            "package",
            "enabled",
            "transport",
            "working_dir",
            "command",
            "url",
            "auth_env",
            "timeout_seconds",
        }
        if set(raw) - allowed or not {"package", "enabled", "transport", "timeout_seconds"} <= set(raw):
            raise ConfigurationError("app has unsupported or missing keys")
        enabled = raw["enabled"]
        if not isinstance(enabled, bool):
            raise ConfigurationError("app.enabled must be boolean")
        package = _dotted_name(raw["package"], "app.package")
        if package in packages:
            raise ConfigurationError("app.package must be a unique dotted package name")
        packages.add(package)
        transport = _string(raw["transport"], "app.transport")
        if transport not in {"stdio", "streamable_http"}:
            raise ConfigurationError("app.transport must be stdio or streamable_http")
        timeout = raw["timeout_seconds"]
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0 or not isfinite(timeout):
            raise ConfigurationError("app.timeout_seconds must be positive")
        command = raw.get("command", [])
        working_dir = raw.get("working_dir")
        url = raw.get("url")
        auth_env = raw.get("auth_env")
        parsed_auth_env = _string(auth_env, "app.auth_env") if auth_env is not None else None
        if transport == "stdio":
            if (
                not isinstance(command, list)
                or not command
                or not all(isinstance(item, str) and item for item in command)
            ):
                raise ConfigurationError("stdio app.command must be a non-empty string array")
            if not isinstance(working_dir, str) or not working_dir:
                raise ConfigurationError("stdio app.working_dir is required")
            if url is not None:
                raise ConfigurationError("stdio app may not declare url")
        else:
            if not isinstance(url, str) or not url.startswith("https://"):
                raise ConfigurationError("streamable_http app.url must use HTTPS")
            if command not in ([], None) or working_dir is not None:
                raise ConfigurationError("streamable_http app may not declare command or working_dir")
        if enabled:
            apps.append(
                AppConfig(
                    package=package,
                    transport=transport,
                    working_dir=(root / working_dir).resolve() if isinstance(working_dir, str) else None,
                    command=tuple(command) if isinstance(command, list) else (),
                    url=url if isinstance(url, str) else None,
                    auth_env=parsed_auth_env,
                    timeout_seconds=float(timeout),
                )
            )
    return tuple(apps)


def _dotted_name(value: object, label: str) -> str:
    name = _string(value, label)
    parts = name.split(".")
    if len(parts) < 2 or any(not part or any(character.isspace() for character in part) for part in parts):
        raise ConfigurationError(f"{label} must be a dotted name")
    return name


def _capability_pattern(value: object, label: str) -> str:
    capability = _string(value, label)
    if capability == "*":
        return capability
    if "*" not in capability:
        return _dotted_name(capability, label)
    if capability.count("*") != 1 or not capability.endswith(".*"):
        raise ConfigurationError(f"{label} must be an exact Tool ID, package.*, or *")
    _dotted_name(capability[:-2], label)
    return capability


def _parse_dashboard(raw: dict[str, Any], root: Path) -> DashboardConfig:
    _require_keys(
        raw,
        {
            "enabled",
            "open_browser",
            "host",
            "port",
            "database_path",
            "upload_dir",
            "max_upload_bytes",
            "session_ttl_seconds",
            "allowed_origins",
            "owner",
            "bot",
        },
        "platform.dashboard",
    )
    host = _string(raw["host"], "dashboard.host")
    port = raw["port"]
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise ConfigurationError("dashboard must bind to loopback")
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise ConfigurationError("dashboard.port must be a valid port")
    max_upload_bytes = raw["max_upload_bytes"]
    session_ttl_seconds = raw["session_ttl_seconds"]
    if not isinstance(max_upload_bytes, int) or isinstance(max_upload_bytes, bool) or max_upload_bytes <= 0:
        raise ConfigurationError("dashboard.max_upload_bytes must be a positive integer")
    if not isinstance(session_ttl_seconds, int) or isinstance(session_ttl_seconds, bool) or session_ttl_seconds <= 0:
        raise ConfigurationError("dashboard.session_ttl_seconds must be a positive integer")
    origins = raw["allowed_origins"]
    if not isinstance(origins, list) or not origins or not all(isinstance(item, str) and item for item in origins):
        raise ConfigurationError("dashboard.allowed_origins must be a non-empty string array")
    bot_raw = raw["bot"]
    owner_raw = raw["owner"]
    if not isinstance(bot_raw, dict):
        raise ConfigurationError("dashboard.bot must be a table")
    if not isinstance(owner_raw, dict):
        raise ConfigurationError("dashboard.owner must be a table")
    _require_keys(owner_raw, {"username"}, "dashboard.owner")
    _require_keys(bot_raw, {"username", "display_name", "avatar_url"}, "dashboard.bot")
    owner_username = _string(owner_raw["username"], "dashboard.owner.username")
    if owner_username != owner_username.strip():
        raise ConfigurationError("dashboard.owner.username must not have leading or trailing whitespace")
    bot_username = _string(bot_raw["username"], "dashboard.bot.username")
    if owner_username == bot_username:
        raise ConfigurationError("dashboard.owner.username must differ from dashboard.bot.username")
    avatar_url = bot_raw["avatar_url"]
    if not isinstance(avatar_url, str):
        raise ConfigurationError("dashboard.bot.avatar_url must be a string")
    database_path = (root / _string(raw["database_path"], "dashboard.database_path")).resolve()
    upload_dir = (root / _string(raw["upload_dir"], "dashboard.upload_dir")).resolve()
    if not database_path.is_relative_to(root) or not upload_dir.is_relative_to(root):
        raise ConfigurationError("dashboard data paths must stay within the project root")
    kernel_workspace = (root / "data" / "kernel").resolve()
    if database_path.is_relative_to(kernel_workspace) or upload_dir.is_relative_to(kernel_workspace):
        raise ConfigurationError("dashboard data paths must not overlap the Kernel workspace")
    if database_path.is_relative_to(upload_dir):
        raise ConfigurationError("dashboard database must not be stored in the upload directory")
    return DashboardConfig(
        host=host,
        port=port,
        database_path=database_path,
        upload_dir=upload_dir,
        max_upload_bytes=max_upload_bytes,
        session_ttl_seconds=session_ttl_seconds,
        allowed_origins=tuple(origins),
        owner_username=owner_username,
        bot=DashboardBotConfig(
            username=bot_username,
            display_name=_string(bot_raw["display_name"], "dashboard.bot.display_name"),
            avatar_url=avatar_url or None,
        ),
    )


def _parse_preference(platform: dict[str, Any]) -> PlatformPreference:
    _require_keys(platform, {"console", "dashboard", "mcp"}, "platform")
    console = _table(platform["console"], "platform.console")
    dashboard = _table(platform["dashboard"], "platform.dashboard")
    mcp = _table(platform["mcp"], "platform.mcp")
    _require_subset(console, {"enabled", "terminal_logs"}, "platform.console")
    _require_subset(dashboard, {"enabled", "open_browser"}, "platform.dashboard")
    _require_subset(mcp, {"enabled", "terminal_logs"}, "platform.mcp")

    def _bool(value: object, label: str) -> bool:
        if not isinstance(value, bool):
            raise ConfigurationError(f"{label} must be boolean")
        return value

    return PlatformPreference(
        console=ConsolePreference(
            enabled=_bool(console["enabled"], "platform.console.enabled"),
            terminal_logs=_bool(console["terminal_logs"], "platform.console.terminal_logs"),
        ),
        dashboard=DashboardPreference(
            enabled=_bool(dashboard["enabled"], "platform.dashboard.enabled"),
            open_browser=_bool(dashboard["open_browser"], "platform.dashboard.open_browser"),
        ),
        mcp=McpPreference(
            enabled=_bool(mcp["enabled"], "platform.mcp.enabled"),
            terminal_logs=_bool(mcp["terminal_logs"], "platform.mcp.terminal_logs"),
        ),
    )
