"""Parsers for independently declared Agent, MCP App and Dashboard sections."""

from math import isfinite
from pathlib import Path
from typing import Any, Literal, cast

from src.contracts.configuration import (
    AgentProfileConfig,
    AgentRuntimeConfig,
    AppConfig,
    AppDestinationConfig,
    AppPublicationConfig,
    AppToolConfig,
    CommunicationConfig,
    ConfigurationError,
    DashboardBotConfig,
    DashboardConfig,
    _positive_number,
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


def _parse_communication(raw: dict[str, Any]) -> CommunicationConfig:
    _require_keys(raw, {"reply_route_ttl_seconds", "relay_hop_limit"}, "communication")
    reply_route_ttl_seconds = _positive_number(raw["reply_route_ttl_seconds"], "communication.reply_route_ttl_seconds")
    if not isfinite(reply_route_ttl_seconds):
        raise ConfigurationError("communication.reply_route_ttl_seconds must be positive")
    relay_hop_limit = raw["relay_hop_limit"]
    if not isinstance(relay_hop_limit, int) or isinstance(relay_hop_limit, bool) or relay_hop_limit != 1:
        raise ConfigurationError("communication.relay_hop_limit must be 1")
    return CommunicationConfig(reply_route_ttl_seconds=reply_route_ttl_seconds, relay_hop_limit=1)


def _parse_apps(raw_apps: object, root: Path) -> tuple[AppConfig, ...]:
    if not isinstance(raw_apps, list):
        raise ConfigurationError("app must be an array")
    apps: list[AppConfig] = []
    packages: set[str] = set()
    tool_names: set[str] = set()
    capabilities: set[str] = set()
    aliases: set[str] = set()
    for raw in raw_apps:
        if not isinstance(raw, dict):
            raise ConfigurationError("app must be a table")
        allowed = {
            "package",
            "kind",
            "enabled",
            "transport",
            "working_dir",
            "command",
            "url",
            "auth_env",
            "timeout_seconds",
            "tool",
            "publication",
            "destination",
        }
        if set(raw) - allowed or not {"package", "kind", "enabled", "transport", "timeout_seconds"} <= set(raw):
            raise ConfigurationError("app has unsupported or missing keys")
        enabled = raw["enabled"]
        if not isinstance(enabled, bool):
            raise ConfigurationError("app.enabled must be boolean")
        package = _dotted_name(raw["package"], "app.package")
        if package in packages:
            raise ConfigurationError("app.package must be a unique dotted package name")
        packages.add(package)
        kind = raw["kind"]
        if not isinstance(kind, str) or kind not in {"utility", "communication"}:
            raise ConfigurationError("app.kind must be utility or communication")
        app_kind = cast("Literal['utility', 'communication']", kind)
        transport = _string(raw["transport"], "app.transport")
        if transport not in {"stdio", "streamable_http"}:
            raise ConfigurationError("app.transport must be stdio or streamable_http")
        parsed_tools = _parse_app_tools(raw.get("tool"), package, app_kind, tool_names, capabilities)
        publications = _parse_app_publications(raw.get("publication"), package, app_kind, parsed_tools, capabilities)
        destinations = _parse_app_destinations(raw.get("destination"), package, app_kind, publications, aliases)
        timeout = raw["timeout_seconds"]
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
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
                    kind=app_kind,
                    transport=transport,
                    working_dir=(root / working_dir).resolve() if isinstance(working_dir, str) else None,
                    command=tuple(command) if isinstance(command, list) else (),
                    url=url if isinstance(url, str) else None,
                    auth_env=parsed_auth_env,
                    timeout_seconds=float(timeout),
                    tools=parsed_tools,
                    publications=publications,
                    destinations=destinations,
                )
            )
    return tuple(apps)


def _dotted_name(value: object, label: str) -> str:
    name = _string(value, label)
    parts = name.split(".")
    if len(parts) < 2 or any(not part or any(character.isspace() for character in part) for part in parts):
        raise ConfigurationError(f"{label} must be a dotted name")
    return name


def _parse_app_tools(
    raw_tools: object,
    package: str,
    app_kind: Literal["utility", "communication"],
    global_tool_names: set[str],
    global_capabilities: set[str],
) -> tuple[AppToolConfig, ...]:
    if not isinstance(raw_tools, list) or not raw_tools:
        raise ConfigurationError("app.tool must be a non-empty array of tables")
    tools: list[AppToolConfig] = []
    for tool in raw_tools:
        if not isinstance(tool, dict):
            raise ConfigurationError("app.tool must be a table")
        _require_keys(tool, {"name", "kind"}, "app.tool")
        name = _dotted_name(tool["name"], "app.tool.name")
        if not name.startswith(f"{package}."):
            raise ConfigurationError("app.tool.name must use the app package prefix")
        if name in global_tool_names:
            raise ConfigurationError(f"duplicate app tool {name}")
        tool_kind = tool["kind"]
        if not isinstance(tool_kind, str) or tool_kind not in {"effect", "publication"}:
            raise ConfigurationError("app.tool.kind must be effect or publication")
        if app_kind == "utility" and tool_kind != "effect":
            raise ConfigurationError("utility app tools must have kind effect")
        if tool_kind == "effect":
            if name in global_capabilities:
                raise ConfigurationError(f"duplicate app capability {name}")
            global_capabilities.add(name)
        global_tool_names.add(name)
        tools.append(AppToolConfig(name, cast("Literal['effect', 'publication']", tool_kind)))
    return tuple(tools)


def _parse_app_publications(
    raw_publications: object,
    package: str,
    app_kind: Literal["utility", "communication"],
    tools: tuple[AppToolConfig, ...],
    global_capabilities: set[str],
) -> tuple[AppPublicationConfig, ...]:
    if app_kind == "utility":
        if raw_publications is not None:
            raise ConfigurationError("utility app may not declare publication")
        return ()
    if not isinstance(raw_publications, list) or not raw_publications:
        raise ConfigurationError("communication app.publication must be a non-empty array of tables")
    publication_tools = {tool.name for tool in tools if tool.kind == "publication"}
    publications: list[AppPublicationConfig] = []
    for raw in raw_publications:
        if not isinstance(raw, dict):
            raise ConfigurationError("app.publication must be a table")
        _require_keys(raw, {"capability", "tool", "operation"}, "app.publication")
        capability = _dotted_name(raw["capability"], "app.publication.capability")
        if capability in global_capabilities:
            raise ConfigurationError(f"duplicate app capability {capability}")
        tool = _dotted_name(raw["tool"], "app.publication.tool")
        if not tool.startswith(f"{package}.") or tool not in publication_tools:
            raise ConfigurationError("app.publication.tool must bind a publication tool from the same app")
        operation = raw["operation"]
        if not isinstance(operation, str) or operation not in {"reply", "relay", "proactive_send"}:
            raise ConfigurationError("app.publication.operation must be reply, relay or proactive_send")
        global_capabilities.add(capability)
        publications.append(
            AppPublicationConfig(
                capability,
                tool,
                cast("Literal['reply', 'relay', 'proactive_send']", operation),
            )
        )
    if sum(publication.operation == "reply" for publication in publications) != 1:
        raise ConfigurationError("communication app must declare exactly one reply capability")
    return tuple(publications)


def _parse_app_destinations(
    raw_destinations: object,
    package: str,
    app_kind: Literal["utility", "communication"],
    publications: tuple[AppPublicationConfig, ...],
    global_aliases: set[str],
) -> tuple[AppDestinationConfig, ...]:
    if app_kind == "utility":
        if raw_destinations is not None:
            raise ConfigurationError("utility app may not declare destination")
        return ()
    if raw_destinations is None:
        return ()
    if not isinstance(raw_destinations, list):
        raise ConfigurationError("app.destination must be an array of tables")
    destination_capabilities = {
        publication.capability for publication in publications if publication.operation in {"relay", "proactive_send"}
    }
    endpoint_short_name = package.rsplit(".", 1)[-1]
    destinations: list[AppDestinationConfig] = []
    for raw in raw_destinations:
        if not isinstance(raw, dict):
            raise ConfigurationError("app.destination must be a table")
        _require_keys(
            raw,
            {
                "alias",
                "description",
                "capability",
                "address_ref",
                "allowed_source_audiences",
                "target_audience_ref",
            },
            "app.destination",
        )
        alias = _dotted_name(raw["alias"], "app.destination.alias")
        if alias.split(".", 1)[0] != endpoint_short_name:
            raise ConfigurationError("app.destination.alias must start with the package's final segment")
        if alias in global_aliases:
            raise ConfigurationError(f"duplicate app destination alias {alias}")
        capability = _dotted_name(raw["capability"], "app.destination.capability")
        if capability not in destination_capabilities:
            raise ConfigurationError(
                "app.destination.capability must bind this app's relay or proactive_send capability"
            )
        audiences = raw["allowed_source_audiences"]
        if not isinstance(audiences, list) or not audiences:
            raise ConfigurationError("app.destination.allowed_source_audiences must be a non-empty string array")
        parsed_audiences = tuple(
            _source_audience_pattern(audience, "app.destination.allowed_source_audiences") for audience in audiences
        )
        if len(set(parsed_audiences)) != len(parsed_audiences):
            raise ConfigurationError("app.destination.allowed_source_audiences must be unique")
        target_audience = _exact_audience(raw["target_audience_ref"], "app.destination.target_audience_ref")
        global_aliases.add(alias)
        destinations.append(
            AppDestinationConfig(
                alias=alias,
                description=_string(raw["description"], "app.destination.description"),
                capability=capability,
                address_ref=_string(raw["address_ref"], "app.destination.address_ref"),
                allowed_source_audiences=parsed_audiences,
                target_audience_ref=target_audience,
            )
        )
    return tuple(destinations)


def _source_audience_pattern(value: object, label: str) -> str:
    audience = _string(value, label)
    if any(character.isspace() for character in audience):
        raise ConfigurationError(f"{label} contains an invalid audience pattern")
    if audience == "*":
        raise ConfigurationError(f"{label} must be exact or use a final :* wildcard")
    if "*" not in audience:
        return audience
    if audience.count("*") != 1 or not audience.endswith(":*"):
        raise ConfigurationError(f"{label} wildcard is only allowed as a final :*")
    _dotted_name(audience[:-2], label)
    return audience


def _exact_audience(value: object, label: str) -> str:
    audience = _string(value, label)
    if "*" in audience or any(character.isspace() for character in audience):
        raise ConfigurationError(f"{label} must be an exact audience")
    return audience


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
            "owner",
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
