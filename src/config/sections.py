"""Agent、MCP App 和 Dashboard 段的解析器。"""

from __future__ import annotations

from enum import StrEnum
from math import isfinite
from pathlib import Path
from typing import Any

from src.config.helpers import _positive_number, _require_keys, _string, _table
from src.contracts.agent import AgentLimits, AgentProfile, TaskLimits
from src.contracts.configuration import (
    PLATFORM_NAMES,
    AppConfig,
    AutonomyConfig,
    ConfigurationError,
    DashboardBotConfig,
    DashboardConfig,
    DashboardPreference,
    McpPreference,
    PlatformPreference,
)
from src.contracts.triage import TriageLimits


class _Msg(StrEnum):
    """本文件内所有用户可见或日志输出的字符串常量。"""

    AGENT_CAN_DELEGATE_BOOLEAN = "Agent {agent_id} can_delegate must be boolean"
    AGENT_CAPABILITIES_STRINGS = "Agent {agent_id} capabilities must contain strings"
    AGENT_CHILD_PROFILES_STRINGS = "Agent {agent_id} child_profiles must contain strings"
    AGENT_DELEGATION_DISABLED = "Agent {agent_id} cannot declare child_profiles when delegation is disabled"
    AGENT_MUST_BE_TABLE = "agent must be a table"
    AGENT_UNKNOWN_CHILDREN = "Agent {agent_id} references unknown child profiles"
    AGENT_UNKNOWN_ROLE = "Agent {agent_id} references unknown model role {model_role}"
    AGENTS_EMPTY_ARRAY = "agents.toml agent must be a non-empty array"
    AGENTS_POSITIVE_INTEGER = "engine.agents.{name} must be a positive integer"
    AGENTS_UNSUPPORTED_KEYS = "engine.agents has unsupported keys"
    APP_ENABLED_BOOLEAN = "app.enabled must be boolean"
    APP_MUST_BE_ARRAY = "app must be an array"
    APP_MUST_BE_TABLE = "app must be a table"
    APP_PACKAGE_UNIQUE = "app.package must be a unique dotted package name"
    APP_TIMEOUT_POSITIVE = "app.timeout_seconds must be positive"
    APP_TRANSPORT_INVALID = "app.transport must be stdio or streamable_http"
    APP_UNSUPPORTED_KEYS = "app has unsupported or missing keys"
    AUTONOMY_UNSUPPORTED_KEYS = "engine.autonomy has unsupported keys"
    CAPABILITY_PATTERN = "{label} must be an exact Tool ID, package.*, or *"
    DASHBOARD_AVATAR_STRING = "dashboard.bot.avatar_url must be a string"
    DASHBOARD_BOT_TABLE = "dashboard.bot must be a table"
    DASHBOARD_DB_UPLOAD_OVERLAP = "dashboard database must not be stored in the upload directory"
    DASHBOARD_LOOPBACK = "dashboard must bind to loopback"
    DASHBOARD_ORIGINS_ARRAY = "dashboard.allowed_origins must be a non-empty string array"
    DASHBOARD_OWNER_TABLE = "dashboard.owner must be a table"
    DASHBOARD_OWNER_WHITESPACE = "dashboard.owner.username must not have leading or trailing whitespace"
    DASHBOARD_PATH_OVERLAP = "dashboard data paths must not overlap the engine workspace"
    DASHBOARD_PATH_SANDBOX = "dashboard data paths must stay within its storage directory"
    DASHBOARD_PORT_INVALID = "dashboard.port must be a valid port"
    DASHBOARD_TTL_POSITIVE = "dashboard.session_ttl_seconds must be a positive integer"
    DASHBOARD_UPLOAD_POSITIVE = "dashboard.max_upload_bytes must be a positive integer"
    DASHBOARD_USERNAME_DIFFER = "dashboard.owner.username must differ from dashboard.bot.username"
    DUPLICATE_AGENT = "duplicate Agent profile {agent_id}"
    ENGINE_LABEL_MODEL_CALLS = "engine.{label}.max_model_calls must be positive"
    ENGINE_LABEL_TOOL_CALLS = "engine.{label}.max_tool_calls must be positive"
    ENGINE_LABEL_UNSUPPORTED_KEYS = "engine.{label} has unsupported keys"
    HEARTBEAT_BOUNDS = "heartbeat_max_seconds must be at least heartbeat_min_seconds"
    HEARTBEAT_INITIAL_BOUNDS = "heartbeat_initial_seconds must be within heartbeat bounds"
    HTTP_NO_COMMAND_DIR = "streamable_http app may not declare command or working_dir"
    HTTP_URL_HTTPS = "streamable_http app.url must use HTTPS"
    MAX_DEPTH_EXCEEDS_MAX_AGENTS = "engine.agents.max_depth cannot exceed max_agents_per_task"
    MUST_BE_BOOLEAN = "{label} must be boolean"
    MUST_BE_DOTTED_NAME = "{label} must be a dotted name"
    STDIO_COMMAND_ARRAY = "stdio app.command must be a non-empty string array"
    STDIO_NO_URL = "stdio app may not declare url"
    STDIO_WORKING_DIR_REQUIRED = "stdio app.working_dir is required"
    TRIAGE_CHARACTERS_MIN = "engine.triage.max_batch_characters must be at least 1000"
    TRIAGE_DEFER_BOUNDS = "engine.triage.defer_seconds must not exceed max_defer_seconds"
    TRIAGE_POSITIVE_INTEGER = "engine.triage.{name} must be a positive integer"
    TRIAGE_QUIET_BOUNDS = "engine.triage.quiet_seconds must not exceed max_wait_seconds"
    TRIAGE_UNSUPPORTED_KEYS = "engine.triage has unexpected {unexpected} or missing {missing}"


def _parse_autonomy(raw: dict[str, Any]) -> AutonomyConfig:
    """解析自主节律配置段，校验心跳边界和每日额度。"""
    defaults = AutonomyConfig()
    allowed = {
        "scan_seconds",
        "heartbeat_initial_seconds",
        "heartbeat_min_seconds",
        "heartbeat_max_seconds",
    }
    if set(raw) - allowed:
        raise ConfigurationError(_Msg.AUTONOMY_UNSUPPORTED_KEYS)
    heartbeat_min = _positive_number(
        raw.get("heartbeat_min_seconds", defaults.heartbeat_min_seconds), "heartbeat_min_seconds"
    )
    heartbeat_max = _positive_number(
        raw.get("heartbeat_max_seconds", defaults.heartbeat_max_seconds), "heartbeat_max_seconds"
    )
    if heartbeat_max < heartbeat_min:
        raise ConfigurationError(_Msg.HEARTBEAT_BOUNDS)
    heartbeat_initial = _positive_number(
        raw.get("heartbeat_initial_seconds", defaults.heartbeat_initial_seconds), "heartbeat_initial_seconds"
    )
    if not heartbeat_min <= heartbeat_initial <= heartbeat_max:
        raise ConfigurationError(_Msg.HEARTBEAT_INITIAL_BOUNDS)
    return AutonomyConfig(
        scan_seconds=_positive_number(raw.get("scan_seconds", defaults.scan_seconds), "scan_seconds"),
        heartbeat_initial_seconds=heartbeat_initial,
        heartbeat_min_seconds=heartbeat_min,
        heartbeat_max_seconds=heartbeat_max,
    )


def _parse_task_budget(
    raw: dict[str, Any], default_calls: int, default_tools: int, default_duration: float, label: str
) -> TaskLimits:
    """解析 Task 预算配置，支持交互式和自主式两档默认值。"""
    allowed = {"max_model_calls", "max_tool_calls", "max_duration_seconds"}
    if set(raw) - allowed:
        raise ConfigurationError(_Msg.ENGINE_LABEL_UNSUPPORTED_KEYS.format(label=label))
    calls = raw.get("max_model_calls", default_calls)
    tools = raw.get("max_tool_calls", default_tools)
    if not isinstance(calls, int) or isinstance(calls, bool) or calls <= 0:
        raise ConfigurationError(_Msg.ENGINE_LABEL_MODEL_CALLS.format(label=label))
    if not isinstance(tools, int) or isinstance(tools, bool) or tools <= 0:
        raise ConfigurationError(_Msg.ENGINE_LABEL_TOOL_CALLS.format(label=label))
    return TaskLimits(calls, tools, _positive_number(raw.get("max_duration_seconds", default_duration), label))


def _parse_agents(data: dict[str, Any], model_roles: frozenset[str]) -> tuple[AgentProfile, ...]:
    """解析 agents.toml 中的 Agent 档案数组，校验引用完整性。"""
    _require_keys(data, {"agent"}, "agents.toml")
    raw_agents = data["agent"]
    if not isinstance(raw_agents, list) or not raw_agents:
        raise ConfigurationError(_Msg.AGENTS_EMPTY_ARRAY)
    agents: list[AgentProfile] = []
    ids: set[str] = set()
    for raw in raw_agents:
        if not isinstance(raw, dict):
            raise ConfigurationError(_Msg.AGENT_MUST_BE_TABLE)
        _require_keys(
            raw,
            {"id", "implementation", "model_role", "capabilities", "can_delegate", "child_profiles"},
            "agent",
        )
        agent_id = _string(raw["id"], "agent.id")
        if agent_id in ids:
            raise ConfigurationError(_Msg.DUPLICATE_AGENT.format(agent_id=agent_id))
        ids.add(agent_id)
        model_role = _string(raw["model_role"], "agent.model_role")
        if model_role not in model_roles:
            raise ConfigurationError(_Msg.AGENT_UNKNOWN_ROLE.format(agent_id=agent_id, model_role=model_role))
        capabilities = raw["capabilities"]
        children = raw["child_profiles"]
        if not isinstance(capabilities, list) or not all(isinstance(item, str) for item in capabilities):
            raise ConfigurationError(_Msg.AGENT_CAPABILITIES_STRINGS.format(agent_id=agent_id))
        for capability in capabilities:
            _capability_pattern(capability, f"Agent {agent_id} capability")
        if not isinstance(children, list) or not all(isinstance(item, str) for item in children):
            raise ConfigurationError(_Msg.AGENT_CHILD_PROFILES_STRINGS.format(agent_id=agent_id))
        if not isinstance(raw["can_delegate"], bool):
            raise ConfigurationError(_Msg.AGENT_CAN_DELEGATE_BOOLEAN.format(agent_id=agent_id))
        agents.append(
            AgentProfile(
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
            raise ConfigurationError(_Msg.AGENT_UNKNOWN_CHILDREN.format(agent_id=agent.id))
        if not agent.can_delegate and agent.child_profiles:
            raise ConfigurationError(_Msg.AGENT_DELEGATION_DISABLED.format(agent_id=agent.id))
    return tuple(agents)


def _parse_agent_runtime(raw: dict[str, Any]) -> AgentLimits:
    """解析运行时 Agent 限制配置，校验 max_depth 与 max_agents_per_task 的关系。"""
    defaults = AgentLimits()
    allowed = set(AgentLimits.__dataclass_fields__)
    if set(raw) - allowed:
        raise ConfigurationError(_Msg.AGENTS_UNSUPPORTED_KEYS)
    values: dict[str, Any] = {}
    for name in allowed:
        value = raw.get(name, getattr(defaults, name))
        if name in {"root_profile", "worker_profile"}:
            values[name] = _string(value, f"engine.agents.{name}")
        elif name == "lease_seconds":
            values[name] = _positive_number(value, f"engine.agents.{name}")
        elif not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ConfigurationError(_Msg.AGENTS_POSITIVE_INTEGER.format(name=name))
        else:
            values[name] = value
    if values["max_depth"] > values["max_agents_per_task"]:
        raise ConfigurationError(_Msg.MAX_DEPTH_EXCEEDS_MAX_AGENTS)
    return AgentLimits(**values)


def _parse_triage(raw: dict[str, Any]) -> TriageLimits:
    """解析防抖与 Triage 的严格结构配置。"""
    allowed = set(TriageLimits.__dataclass_fields__)
    if set(raw) != allowed:
        raise ConfigurationError(
            _Msg.TRIAGE_UNSUPPORTED_KEYS.format(
                unexpected=sorted(set(raw) - allowed),
                missing=sorted(allowed - set(raw)),
            )
        )
    values: dict[str, Any] = {}
    for name in allowed:
        value = raw[name]
        if name == "model_role":
            values[name] = _string(value, f"engine.triage.{name}")
        elif name in {"max_batch_events", "max_batch_characters"}:
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ConfigurationError(_Msg.TRIAGE_POSITIVE_INTEGER.format(name=name))
            values[name] = value
        else:
            values[name] = _positive_number(value, f"engine.triage.{name}")
    if values["quiet_seconds"] > values["max_wait_seconds"]:
        raise ConfigurationError(_Msg.TRIAGE_QUIET_BOUNDS)
    if values["defer_seconds"] > values["max_defer_seconds"]:
        raise ConfigurationError(_Msg.TRIAGE_DEFER_BOUNDS)
    if values["max_batch_characters"] < 1000:
        raise ConfigurationError(_Msg.TRIAGE_CHARACTERS_MIN)
    return TriageLimits(**values)


def _parse_apps(raw_apps: object, root: Path) -> tuple[AppConfig, ...]:
    """解析 apps.toml 中的应用路由数组，校验 stdio/streamable_http 约束。"""
    if not isinstance(raw_apps, list):
        raise ConfigurationError(_Msg.APP_MUST_BE_ARRAY)
    apps: list[AppConfig] = []
    packages: set[str] = set()
    for raw in raw_apps:
        if not isinstance(raw, dict):
            raise ConfigurationError(_Msg.APP_MUST_BE_TABLE)
        allowed = {
            "package",
            "enabled",
            "transport",
            "working_dir",
            "command",
            "env",
            "url",
            "auth_env",
            "timeout_seconds",
        }
        if set(raw) - allowed or not {"package", "enabled", "transport", "timeout_seconds"} <= set(raw):
            raise ConfigurationError(_Msg.APP_UNSUPPORTED_KEYS)
        enabled = raw["enabled"]
        if not isinstance(enabled, bool):
            raise ConfigurationError(_Msg.APP_ENABLED_BOOLEAN)
        package = _dotted_name(raw["package"], "app.package")
        if package in packages:
            raise ConfigurationError(_Msg.APP_PACKAGE_UNIQUE)
        packages.add(package)
        transport = _string(raw["transport"], "app.transport")
        if transport not in {"stdio", "streamable_http"}:
            raise ConfigurationError(_Msg.APP_TRANSPORT_INVALID)
        timeout = raw["timeout_seconds"]
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0 or not isfinite(timeout):
            raise ConfigurationError(_Msg.APP_TIMEOUT_POSITIVE)
        command = raw.get("command", [])
        env_vars = raw.get("env", [])
        working_dir = raw.get("working_dir")
        url = raw.get("url")
        auth_env = raw.get("auth_env")
        parsed_auth_env = _string(auth_env, "app.auth_env") if auth_env is not None else None
        if not isinstance(env_vars, list) or not all(isinstance(item, str) for item in env_vars):
            raise ConfigurationError("app.env must contain unique environment variable names")
        if len(env_vars) != len(set(env_vars)) or not all(item.isidentifier() for item in env_vars):
            raise ConfigurationError("app.env must contain unique environment variable names")
        if transport == "stdio":
            if (
                not isinstance(command, list)
                or not command
                or not all(isinstance(item, str) and item for item in command)
            ):
                raise ConfigurationError(_Msg.STDIO_COMMAND_ARRAY)
            if not isinstance(working_dir, str) or not working_dir:
                raise ConfigurationError(_Msg.STDIO_WORKING_DIR_REQUIRED)
            if url is not None:
                raise ConfigurationError(_Msg.STDIO_NO_URL)
        else:
            if not isinstance(url, str) or not url.startswith("https://"):
                raise ConfigurationError(_Msg.HTTP_URL_HTTPS)
            if command not in ([], None) or working_dir is not None:
                raise ConfigurationError(_Msg.HTTP_NO_COMMAND_DIR)
        if enabled:
            apps.append(
                AppConfig(
                    package=package,
                    transport=transport,
                    working_dir=(root / working_dir).resolve() if isinstance(working_dir, str) else None,
                    command=tuple(command) if isinstance(command, list) else (),
                    env_vars=tuple(env_vars),
                    url=url if isinstance(url, str) else None,
                    auth_env=parsed_auth_env,
                    timeout_seconds=float(timeout),
                )
            )
    return tuple(apps)


def _dotted_name(value: object, label: str) -> str:
    """校验值为合法的点分名称（如 com.example.app）。"""
    name = _string(value, label)
    parts = name.split(".")
    if len(parts) < 2 or any(not part or any(character.isspace() for character in part) for part in parts):
        raise ConfigurationError(_Msg.MUST_BE_DOTTED_NAME.format(label=label))
    return name


def _capability_pattern(value: object, label: str) -> str:
    """校验能力模式：精确工具 ID、package.* 或 *。"""
    capability = _string(value, label)
    if capability == "*":
        return capability
    if "*" not in capability:
        return _dotted_name(capability, label)
    if capability.count("*") != 1 or not capability.endswith(".*"):
        raise ConfigurationError(_Msg.CAPABILITY_PATTERN.format(label=label))
    _dotted_name(capability[:-2], label)
    return capability


def _parse_dashboard(raw: dict[str, Any], root: Path, engine_workspace: Path) -> DashboardConfig:
    """解析 Dashboard 配置段，校验端口、路径安全和 owner/bot 分离。"""
    _require_keys(
        raw,
        {
            "enabled",
            "open_browser",
            "host",
            "port",
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
        raise ConfigurationError(_Msg.DASHBOARD_LOOPBACK)
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise ConfigurationError(_Msg.DASHBOARD_PORT_INVALID)
    max_upload_bytes = raw["max_upload_bytes"]
    session_ttl_seconds = raw["session_ttl_seconds"]
    if not isinstance(max_upload_bytes, int) or isinstance(max_upload_bytes, bool) or max_upload_bytes <= 0:
        raise ConfigurationError(_Msg.DASHBOARD_UPLOAD_POSITIVE)
    if not isinstance(session_ttl_seconds, int) or isinstance(session_ttl_seconds, bool) or session_ttl_seconds <= 0:
        raise ConfigurationError(_Msg.DASHBOARD_TTL_POSITIVE)
    origins = raw["allowed_origins"]
    if not isinstance(origins, list) or not origins or not all(isinstance(item, str) and item for item in origins):
        raise ConfigurationError(_Msg.DASHBOARD_ORIGINS_ARRAY)
    bot_raw = raw["bot"]
    owner_raw = raw["owner"]
    if not isinstance(bot_raw, dict):
        raise ConfigurationError(_Msg.DASHBOARD_BOT_TABLE)
    if not isinstance(owner_raw, dict):
        raise ConfigurationError(_Msg.DASHBOARD_OWNER_TABLE)
    _require_keys(owner_raw, {"username"}, "dashboard.owner")
    _require_keys(bot_raw, {"username", "display_name", "avatar_url"}, "dashboard.bot")
    owner_username = _string(owner_raw["username"], "dashboard.owner.username")
    if owner_username != owner_username.strip():
        raise ConfigurationError(_Msg.DASHBOARD_OWNER_WHITESPACE)
    bot_username = _string(bot_raw["username"], "dashboard.bot.username")
    if owner_username == bot_username:
        raise ConfigurationError(_Msg.DASHBOARD_USERNAME_DIFFER)
    avatar_url = bot_raw["avatar_url"]
    if not isinstance(avatar_url, str):
        raise ConfigurationError(_Msg.DASHBOARD_AVATAR_STRING)
    database_path = (root / "chat.sqlite3").resolve()
    upload_dir = (root / "uploads").resolve()
    if not database_path.is_relative_to(root) or not upload_dir.is_relative_to(root):
        raise ConfigurationError(_Msg.DASHBOARD_PATH_SANDBOX)
    if database_path.is_relative_to(engine_workspace) or upload_dir.is_relative_to(engine_workspace):
        raise ConfigurationError(_Msg.DASHBOARD_PATH_OVERLAP)
    if database_path.is_relative_to(upload_dir):
        raise ConfigurationError(_Msg.DASHBOARD_DB_UPLOAD_OVERLAP)
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
    """解析平台偏好配置段（dashboard / mcp 的启用和选项）。"""
    _require_keys(platform, set(PLATFORM_NAMES), "platform")
    dashboard = _table(platform["dashboard"], "platform.dashboard")
    mcp = _table(platform["mcp"], "platform.mcp")
    _require_keys(
        dashboard,
        {
            "enabled",
            "open_browser",
            "host",
            "port",
            "max_upload_bytes",
            "session_ttl_seconds",
            "allowed_origins",
            "owner",
            "bot",
        },
        "platform.dashboard",
    )
    _require_keys(mcp, {"enabled", "terminal_logs"}, "platform.mcp")

    def _bool(value: object, label: str) -> bool:
        if not isinstance(value, bool):
            raise ConfigurationError(_Msg.MUST_BE_BOOLEAN.format(label=label))
        return value

    return PlatformPreference(
        dashboard=DashboardPreference(
            enabled=_bool(dashboard["enabled"], "platform.dashboard.enabled"),
            open_browser=_bool(dashboard["open_browser"], "platform.dashboard.open_browser"),
        ),
        mcp=McpPreference(
            enabled=_bool(mcp["enabled"], "platform.mcp.enabled"),
            terminal_logs=_bool(mcp["terminal_logs"], "platform.mcp.terminal_logs"),
        ),
    )
