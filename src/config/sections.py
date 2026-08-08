"""Agent、MCP App 与面板配置段的解析器。"""

from __future__ import annotations

from enum import StrEnum
from math import isfinite
from pathlib import Path
from typing import Any

from src.config.helpers import _positive_number, _require_keys, _string, _table
from src.contracts import (
    PLATFORM_NAMES,
    AgentLimits,
    AgentProfile,
    AppConfig,
    AutonomyConfig,
    ConfigurationError,
    McpPreference,
    PanelConfig,
    PlatformPreference,
    TaskLimits,
    TriageLimits,
)


class _Msg(StrEnum):
    """本文件内所有用户可见或日志输出的字符串常量。"""

    AGENT_CAN_DELEGATE_BOOLEAN = "Agent {agent_id} can_delegate must be boolean"
    AGENT_TRIAGE_CONTROL_BOOLEAN = "Agent {agent_id} triage_control must be boolean"
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
    PANEL_LOOPBACK = "panel must bind to loopback"
    PANEL_ORIGINS_ARRAY = "panel.allowed_origins must be a non-empty string array"
    PANEL_PORT_INVALID = "panel.port must be a valid port"
    PANEL_TTL_POSITIVE = "panel.session_ttl_seconds must be a positive integer"
    PANEL_UPLOAD_NONNEGATIVE = "panel.max_upload_bytes must be a non-negative integer"
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
        raw_triage_control = raw.pop("triage_control", None)
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
        triage_control = raw_triage_control
        if triage_control is not None and not isinstance(triage_control, bool):
            raise ConfigurationError(_Msg.AGENT_TRIAGE_CONTROL_BOOLEAN.format(agent_id=agent_id))
        agents.append(
            AgentProfile(
                id=agent_id,
                implementation=_string(raw["implementation"], "agent.implementation"),
                model_role=model_role,
                capabilities=frozenset(capabilities),
                can_delegate=raw["can_delegate"],
                child_profiles=frozenset(children),
                triage_control=bool(triage_control),
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
    """校验能力模式：`!` 排除前缀、精确工具 ID、package.* 或 *（RFC 0207）。"""
    raw = _string(value, label)
    if raw.startswith("!"):
        if len(raw) == 1:
            raise ConfigurationError(_Msg.CAPABILITY_PATTERN.format(label=label))
        return "!" + _capability_pattern(raw[1:], label)
    if raw == "*":
        return raw
    if "*" not in raw:
        return _dotted_name(raw, label)
    if raw.count("*") != 1 or not raw.endswith(".*"):
        raise ConfigurationError(_Msg.CAPABILITY_PATTERN.format(label=label))
    _dotted_name(raw[:-2], label)
    return raw


def _parse_panel(raw: dict[str, Any]) -> PanelConfig:
    """解析面板后端配置段（RFC 0218 §7），校验 loopback、端口与前端白名单。"""
    _require_keys(
        raw,
        {"enabled", "host", "port", "allowed_origins", "open_browser", "session_ttl_seconds", "max_upload_bytes"},
        "runtime.panel",
    )
    host = _string(raw["host"], "panel.host")
    port = raw["port"]
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise ConfigurationError(_Msg.PANEL_LOOPBACK)
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise ConfigurationError(_Msg.PANEL_PORT_INVALID)
    max_upload_bytes = raw["max_upload_bytes"]
    session_ttl_seconds = raw["session_ttl_seconds"]
    if not isinstance(max_upload_bytes, int) or isinstance(max_upload_bytes, bool) or max_upload_bytes < 0:
        raise ConfigurationError(_Msg.PANEL_UPLOAD_NONNEGATIVE)
    if (
        not isinstance(session_ttl_seconds, int)
        or isinstance(session_ttl_seconds, bool)
        or session_ttl_seconds <= 0
    ):
        raise ConfigurationError(_Msg.PANEL_TTL_POSITIVE)
    origins = raw["allowed_origins"]
    if not isinstance(origins, list) or not origins or not all(isinstance(item, str) and item for item in origins):
        raise ConfigurationError(_Msg.PANEL_ORIGINS_ARRAY)
    if not isinstance(raw["enabled"], bool) or not isinstance(raw["open_browser"], bool):
        raise ConfigurationError(_Msg.MUST_BE_BOOLEAN.format(label="panel"))
    return PanelConfig(
        enabled=raw["enabled"],
        host=host,
        port=port,
        allowed_origins=tuple(origins),
        open_browser=raw["open_browser"],
        session_ttl_seconds=session_ttl_seconds,
        max_upload_bytes=max_upload_bytes,
    )


def _parse_preference(platform: dict[str, Any]) -> PlatformPreference:
    """解析平台偏好配置段（mcp 的启用和选项）。"""
    _require_keys(platform, set(PLATFORM_NAMES), "platform")
    mcp = _table(platform["mcp"], "platform.mcp")
    _require_keys(mcp, {"enabled", "terminal_logs"}, "platform.mcp")

    def _bool(value: object, label: str) -> bool:
        if not isinstance(value, bool):
            raise ConfigurationError(_Msg.MUST_BE_BOOLEAN.format(label=label))
        return value

    return PlatformPreference(
        mcp=McpPreference(
            enabled=_bool(mcp["enabled"], "platform.mcp.enabled"),
            terminal_logs=_bool(mcp["terminal_logs"], "platform.mcp.terminal_logs"),
        ),
    )
