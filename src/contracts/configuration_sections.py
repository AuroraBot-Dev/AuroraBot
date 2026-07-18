"""Parsers for independently declared Agent, Platform and Dashboard sections."""

from pathlib import Path
from typing import Any, Literal, cast

from src.contracts.configuration import (
    AdapterConfig,
    AgentProfileConfig,
    AppConfig,
    AppToolConfig,
    CapabilityConfig,
    ConfigurationError,
    DashboardBotConfig,
    DashboardConfig,
    _require_keys,
    _string,
)


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
            {"id", "implementation", "model_role", "prompt", "capabilities", "can_delegate", "child_profiles"},
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
        if not isinstance(children, list) or not all(isinstance(item, str) for item in children):
            raise ConfigurationError(f"Agent {agent_id} child_profiles must contain strings")
        if not isinstance(raw["can_delegate"], bool):
            raise ConfigurationError(f"Agent {agent_id} can_delegate must be boolean")
        agents.append(
            AgentProfileConfig(
                id=agent_id,
                implementation=_string(raw["implementation"], "agent.implementation"),
                model_role=model_role,
                prompt=_string(raw["prompt"], "agent.prompt"),
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


def _parse_adapters(data: dict[str, Any], root: Path) -> tuple[tuple[AdapterConfig, ...], tuple[AppConfig, ...]]:
    _require_keys(data, {"adapter", "app"}, "apps.toml")
    raw_adapters = data["adapter"]
    if not isinstance(raw_adapters, list):
        raise ConfigurationError("adapter must be an array")
    adapters: list[AdapterConfig] = []
    ids: set[str] = set()
    for raw in raw_adapters:
        if not isinstance(raw, dict):
            raise ConfigurationError("adapter must be a table")
        _require_keys(raw, {"id", "enabled", "implementation", "capability"}, "adapter")
        if not isinstance(raw["enabled"], bool):
            raise ConfigurationError("adapter.enabled must be boolean")
        if not raw["enabled"]:
            continue
        adapter_id = _string(raw["id"], "adapter.id")
        if adapter_id in ids:
            raise ConfigurationError(f"duplicate adapter {adapter_id}")
        ids.add(adapter_id)
        capabilities = raw["capability"]
        if not isinstance(capabilities, list):
            raise ConfigurationError("adapter.capability must be an array")
        parsed_capabilities: list[CapabilityConfig] = []
        capability_ids: set[str] = set()
        for capability in capabilities:
            if not isinstance(capability, dict):
                raise ConfigurationError("adapter.capability must be a table")
            allowed_keys = {"id", "parameters_schema", "description", "result_mode"}
            if set(capability) - allowed_keys or not {"id", "parameters_schema"} <= set(capability):
                raise ConfigurationError("adapter.capability has unsupported or missing keys")
            capability_id = _string(capability["id"], "adapter.capability.id")
            schema = capability["parameters_schema"]
            if capability_id in capability_ids or not isinstance(schema, dict):
                raise ConfigurationError("adapter capability IDs must be unique and schemas must be tables")
            capability_ids.add(capability_id)
            result_mode = capability.get("result_mode", "resume")
            description = capability.get("description", "")
            if result_mode not in {"resume", "terminal"}:
                raise ConfigurationError("adapter.capability.result_mode must be resume or terminal")
            if not isinstance(description, str):
                raise ConfigurationError("adapter.capability.description must be a string")
            parsed_capabilities.append(
                CapabilityConfig(
                    capability_id,
                    schema,
                    description,
                    cast("Literal['resume', 'terminal']", result_mode),
                )
            )
        adapters.append(
            AdapterConfig(
                adapter_id, _string(raw["implementation"], "adapter.implementation"), tuple(parsed_capabilities)
            )
        )
    return tuple(adapters), _parse_apps(data["app"], root)


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
            "tool",
        }
        if set(raw) - allowed or not {"package", "enabled", "transport", "timeout_seconds"} <= set(raw):
            raise ConfigurationError("app has unsupported or missing keys")
        if not isinstance(raw["enabled"], bool) or not raw["enabled"]:
            continue
        package = _string(raw["package"], "app.package")
        if package in packages or "." not in package:
            raise ConfigurationError("app.package must be a unique dotted package name")
        packages.add(package)
        transport = _string(raw["transport"], "app.transport")
        if transport not in {"stdio", "streamable_http"}:
            raise ConfigurationError("app.transport must be stdio or streamable_http")
        parsed_tools = _parse_app_tools(raw.get("tool"), package)
        timeout = raw["timeout_seconds"]
        if not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ConfigurationError("app.timeout_seconds must be positive")
        command = raw.get("command", [])
        working_dir = raw.get("working_dir")
        url = raw.get("url")
        auth_env = raw.get("auth_env")
        if transport == "stdio":
            if not isinstance(command, list) or not command or not all(isinstance(item, str) for item in command):
                raise ConfigurationError("stdio app.command must be a non-empty string array")
            if not isinstance(working_dir, str):
                raise ConfigurationError("stdio app.working_dir is required")
        else:
            if not isinstance(url, str) or not url.startswith("https://"):
                raise ConfigurationError("streamable_http app.url must use HTTPS")
            if command not in ([], None) or working_dir is not None:
                raise ConfigurationError("streamable_http app may not declare command or working_dir")
        apps.append(
            AppConfig(
                package=package,
                transport=transport,
                working_dir=(root / working_dir).resolve() if isinstance(working_dir, str) else None,
                command=tuple(command) if isinstance(command, list) else (),
                url=url if isinstance(url, str) else None,
                auth_env=_string(auth_env, "app.auth_env") if auth_env is not None else None,
                timeout_seconds=float(timeout),
                tools=parsed_tools,
            )
        )
    return tuple(apps)


def _parse_app_tools(raw_tools: object, package: str) -> tuple[AppToolConfig, ...]:
    if not isinstance(raw_tools, list) or not raw_tools:
        raise ConfigurationError("enabled app.tool must be a non-empty array of tables")
    tools: list[AppToolConfig] = []
    for tool in raw_tools:
        if not isinstance(tool, dict) or set(tool) != {"name", "result_mode"}:
            raise ConfigurationError("app.tool must contain name and result_mode")
        name = _string(tool["name"], "app.tool.name")
        result_mode = tool["result_mode"]
        if not name.startswith(f"{package}.") or result_mode not in {"resume", "terminal"}:
            raise ConfigurationError("app.tool must use the package prefix and a valid result_mode")
        tools.append(AppToolConfig(name, cast("Literal['resume', 'terminal']", result_mode)))
    if len({tool.name for tool in tools}) != len(tools):
        raise ConfigurationError("app tool names must be unique")
    return tuple(tools)


def _parse_dashboard(raw: dict[str, Any], root: Path) -> DashboardConfig:
    _require_keys(
        raw,
        {
            "host",
            "port",
            "database_path",
            "upload_dir",
            "max_upload_bytes",
            "session_ttl_seconds",
            "allowed_origins",
            "bot",
        },
        "dashboard",
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
    if not isinstance(bot_raw, dict):
        raise ConfigurationError("dashboard.bot must be a table")
    _require_keys(bot_raw, {"username", "display_name", "avatar_url"}, "dashboard.bot")
    avatar_url = bot_raw["avatar_url"]
    if not isinstance(avatar_url, str):
        raise ConfigurationError("dashboard.bot.avatar_url must be a string")
    database_path = (root / _string(raw["database_path"], "dashboard.database_path")).resolve()
    upload_dir = (root / _string(raw["upload_dir"], "dashboard.upload_dir")).resolve()
    if not database_path.is_relative_to(root) or not upload_dir.is_relative_to(root):
        raise ConfigurationError("dashboard data paths must stay within the project root")
    return DashboardConfig(
        host,
        port,
        database_path,
        upload_dir,
        max_upload_bytes,
        session_ttl_seconds,
        tuple(origins),
        DashboardBotConfig(
            _string(bot_raw["username"], "dashboard.bot.username"),
            _string(bot_raw["display_name"], "dashboard.bot.display_name"),
            avatar_url or None,
        ),
    )
