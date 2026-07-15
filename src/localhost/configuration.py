"""RFC 0002 TOML configuration loading and validation."""

from __future__ import annotations

import copy
import hashlib
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast


class ConfigurationError(ValueError):
    """Raised before startup for invalid structural configuration."""


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except FileNotFoundError as error:
        raise ConfigurationError(f"configuration file does not exist: {path}") from error
    except tomllib.TOMLDecodeError as error:
        raise ConfigurationError(f"invalid TOML in {path}: {error}") from error


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) != isinstance(value, dict):
            raise ConfigurationError(f"profile type mismatch at {key}")
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _require_keys(value: dict[str, Any], keys: set[str], label: str) -> None:
    unexpected = set(value) - keys
    missing = keys - set(value)
    if unexpected or missing:
        raise ConfigurationError(f"{label} has unexpected {sorted(unexpected)} or missing {sorted(missing)} keys")


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ConfigurationError(f"{label} must be a non-empty string")
    return value


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    profile: str
    workspace: Path
    debug_host: str
    debug_port: int
    scheduler: "SchedulerConfig"
    interactive_budget: "EpisodeBudgetConfig"
    autonomous_budget: "EpisodeBudgetConfig"


@dataclass(frozen=True, slots=True)
class SchedulerConfig:
    enabled: bool = True
    scan_seconds: float = 1.0
    idle_initial_seconds: float = 30.0
    idle_max_seconds: float = 1800.0
    idle_multiplier: float = 2.0
    action_cooldown_seconds: float = 300.0
    autonomous_daily_model_calls: int = 24
    autonomous_daily_tokens: int = 100_000


@dataclass(frozen=True, slots=True)
class EpisodeBudgetConfig:
    max_model_calls: int
    max_tool_calls: int
    max_duration_seconds: float


@dataclass(frozen=True, slots=True)
class DashboardBotConfig:
    username: str
    display_name: str
    avatar_url: str | None


@dataclass(frozen=True, slots=True)
class DashboardConfig:
    host: str
    port: int
    database_path: Path
    upload_dir: Path
    max_upload_bytes: int
    session_ttl_seconds: int
    allowed_origins: tuple[str, ...]
    bot: DashboardBotConfig


@dataclass(frozen=True, slots=True)
class NodeConfig:
    id: str
    implementation: str
    inputs: frozenset[str]
    outputs: frozenset[str]
    capabilities: frozenset[str]
    model_roles: frozenset[str]


@dataclass(frozen=True, slots=True)
class AdapterConfig:
    id: str
    implementation: str
    capabilities: tuple["CapabilityConfig", ...]


@dataclass(frozen=True, slots=True)
class CapabilityConfig:
    """A Platform effect capability and its JSON Schema input contract."""

    id: str
    parameters_schema: dict[str, Any]
    description: str = ""
    result_mode: Literal["resume", "terminal"] = "resume"


@dataclass(frozen=True, slots=True)
class AppToolConfig:
    name: str
    result_mode: Literal["resume", "terminal"]


@dataclass(frozen=True, slots=True)
class AppConfig:
    """One explicitly enabled MCP application route."""

    package: str
    transport: str
    working_dir: Path | None
    command: tuple[str, ...]
    url: str | None
    auth_env: str | None
    timeout_seconds: float
    tools: tuple[AppToolConfig, ...]

    @property
    def allowed_tools(self) -> frozenset[str]:
        return frozenset(tool.name for tool in self.tools)


@dataclass(frozen=True, slots=True)
class ModelProviderConfig:
    """A TOML-defined LiteLLM or OpenAI-compatible Provider route."""

    id: str
    adapter: str
    secret_env: str
    base_url: str | None


@dataclass(frozen=True, slots=True)
class ModelRoleConfig:
    """Non-secret configuration for one model role."""

    provider: str
    model: str
    capabilities: frozenset[str]
    endpoint: str = "chat_completions"


@dataclass(frozen=True, slots=True)
class ModelLoggingConfig:
    """Opt-in DEBUG logging controls for the retained gateway implementation."""

    log_queries: bool
    log_responses: bool


@dataclass(frozen=True, slots=True)
class AuroraConfig:
    root: Path
    runtime: RuntimeConfig
    dashboard: DashboardConfig
    soul_path: Path
    soul_hash: str
    logging_level: str
    nodes: tuple[NodeConfig, ...]
    edges: dict[str, tuple[str, ...]]
    advancing_edges: frozenset[tuple[str, str]]
    adapters: tuple[AdapterConfig, ...]
    model_roles: frozenset[str]
    model_definitions: dict[str, ModelRoleConfig]
    model_providers: dict[str, ModelProviderConfig]
    capability_definitions: dict[str, CapabilityConfig]
    model_logging: ModelLoggingConfig
    apps: tuple[AppConfig, ...]


def _parse_nodes(
    data: dict[str, Any], model_roles: frozenset[str]
) -> tuple[tuple[NodeConfig, ...], dict[str, tuple[str, ...]], frozenset[tuple[str, str]]]:
    _require_keys(data, {"node", "edge"}, "nodes.toml")
    raw_nodes = data["node"]
    raw_edges = data["edge"]
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        raise ConfigurationError("node and edge must be arrays")
    nodes: list[NodeConfig] = []
    ids: set[str] = set()
    for raw in raw_nodes:
        if not isinstance(raw, dict):
            raise ConfigurationError("node must be a table")
        _require_keys(
            raw,
            {"id", "enabled", "implementation", "inputs", "outputs", "capabilities", "model_roles"},
            "node",
        )
        if not isinstance(raw["enabled"], bool):
            raise ConfigurationError("node.enabled must be boolean")
        if not raw["enabled"]:
            continue
        node_id = _string(raw["id"], "node.id")
        if node_id in ids:
            raise ConfigurationError(f"duplicate node {node_id}")
        ids.add(node_id)
        fields = {name: raw[name] for name in ("inputs", "outputs", "capabilities", "model_roles")}
        list_fields_are_invalid = any(
            not isinstance(item, list) or not all(isinstance(item_value, str) for item_value in item)
            for item in fields.values()
        )
        if list_fields_are_invalid:
            raise ConfigurationError(f"node {node_id} list fields must contain strings")
        roles = frozenset(fields["model_roles"])
        if not roles <= model_roles:
            raise ConfigurationError(f"node {node_id} references unknown model roles")
        nodes.append(
            NodeConfig(
                id=node_id,
                implementation=_string(raw["implementation"], "node.implementation"),
                inputs=frozenset(fields["inputs"]),
                outputs=frozenset(fields["outputs"]),
                capabilities=frozenset(fields["capabilities"]),
                model_roles=roles,
            )
        )
    edges: dict[str, list[str]] = {}
    advancing_edges: set[tuple[str, str]] = set()
    for raw in raw_edges:
        if not isinstance(raw, dict):
            raise ConfigurationError("edge must be a table")
        allowed_edge_keys = {"event_type", "target", "advances_round"}
        if set(raw) - allowed_edge_keys or not {"event_type", "target"} <= set(raw):
            raise ConfigurationError("edge has unsupported or missing keys")
        event_type = _string(raw["event_type"], "edge.event_type")
        target = _string(raw["target"], "edge.target")
        advances_round = raw.get("advances_round", False)
        if not isinstance(advances_round, bool):
            raise ConfigurationError("edge.advances_round must be boolean")
        if target == "@continuation" and not advances_round:
            raise ConfigurationError("@continuation edge must advance round")
        if target != "@continuation" and target not in ids:
            raise ConfigurationError(f"edge references disabled or unknown node {target}")
        edges.setdefault(event_type, []).append(target)
        if advances_round:
            advancing_edges.add((event_type, target))
    return tuple(nodes), {key: tuple(value) for key, value in edges.items()}, frozenset(advancing_edges)


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
            allowed_capability_keys = {"id", "parameters_schema", "description", "result_mode"}
            if set(capability) - allowed_capability_keys or not {"id", "parameters_schema"} <= set(capability):
                raise ConfigurationError("adapter.capability has unsupported or missing keys")
            capability_id = _string(capability["id"], "adapter.capability.id")
            schema = capability["parameters_schema"]
            if capability_id in capability_ids or not isinstance(schema, dict):
                raise ConfigurationError("adapter capability IDs must be unique and schemas must be tables")
            capability_ids.add(capability_id)
            result_mode = capability.get("result_mode", "resume")
            if result_mode not in {"resume", "terminal"}:
                raise ConfigurationError("adapter.capability.result_mode must be resume or terminal")
            description = capability.get("description", "")
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
                adapter_id,
                _string(raw["implementation"], "adapter.implementation"),
                tuple(parsed_capabilities),
            )
        )
    raw_apps = data["app"]
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
        required = {"package", "enabled", "transport", "timeout_seconds"}
        if set(raw) - allowed or not required <= set(raw):
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
        parsed_tools: list[AppToolConfig] = []
        tool_tables = raw.get("tool")
        if not isinstance(tool_tables, list) or not tool_tables:
            raise ConfigurationError("enabled app.tool must be a non-empty array of tables")
        for tool in tool_tables:
            if not isinstance(tool, dict) or set(tool) != {"name", "result_mode"}:
                raise ConfigurationError("app.tool must contain name and result_mode")
            name = _string(tool["name"], "app.tool.name")
            result_mode = tool["result_mode"]
            if not name.startswith(f"{package}.") or result_mode not in {"resume", "terminal"}:
                raise ConfigurationError("app.tool must use the package prefix and a valid result_mode")
            parsed_tools.append(AppToolConfig(name, cast("Literal['resume', 'terminal']", result_mode)))
        if len({tool.name for tool in parsed_tools}) != len(parsed_tools):
            raise ConfigurationError("app tool names must be unique")
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
        if auth_env is not None:
            auth_env = _string(auth_env, "app.auth_env")
        apps.append(
            AppConfig(
                package=package,
                transport=transport,
                working_dir=(root / working_dir).resolve() if isinstance(working_dir, str) else None,
                command=tuple(command) if isinstance(command, list) else (),
                url=url if isinstance(url, str) else None,
                auth_env=auth_env,
                timeout_seconds=float(timeout),
                tools=tuple(parsed_tools),
            )
        )
    return tuple(adapters), tuple(apps)


def _positive_number(value: object, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        raise ConfigurationError(f"{label} must be positive")
    return float(value)


def _parse_scheduler(raw: dict[str, Any]) -> SchedulerConfig:
    defaults = SchedulerConfig()
    allowed = {
        "enabled",
        "scan_seconds",
        "idle_initial_seconds",
        "idle_max_seconds",
        "idle_multiplier",
        "action_cooldown_seconds",
        "autonomous_daily_model_calls",
        "autonomous_daily_tokens",
    }
    if set(raw) - allowed:
        raise ConfigurationError("runtime.scheduler has unsupported keys")
    enabled = raw.get("enabled", defaults.enabled)
    if not isinstance(enabled, bool):
        raise ConfigurationError("runtime.scheduler.enabled must be boolean")
    daily_calls = raw.get("autonomous_daily_model_calls", defaults.autonomous_daily_model_calls)
    daily_tokens = raw.get("autonomous_daily_tokens", defaults.autonomous_daily_tokens)
    if not isinstance(daily_calls, int) or isinstance(daily_calls, bool) or daily_calls <= 0:
        raise ConfigurationError("autonomous_daily_model_calls must be a positive integer")
    if not isinstance(daily_tokens, int) or isinstance(daily_tokens, bool) or daily_tokens <= 0:
        raise ConfigurationError("autonomous_daily_tokens must be a positive integer")
    initial = _positive_number(raw.get("idle_initial_seconds", defaults.idle_initial_seconds), "idle_initial_seconds")
    maximum = _positive_number(raw.get("idle_max_seconds", defaults.idle_max_seconds), "idle_max_seconds")
    if maximum < initial:
        raise ConfigurationError("idle_max_seconds must be at least idle_initial_seconds")
    multiplier = _positive_number(raw.get("idle_multiplier", defaults.idle_multiplier), "idle_multiplier")
    if multiplier <= 1:
        raise ConfigurationError("idle_multiplier must be greater than one")
    return SchedulerConfig(
        enabled=enabled,
        scan_seconds=_positive_number(raw.get("scan_seconds", defaults.scan_seconds), "scan_seconds"),
        idle_initial_seconds=initial,
        idle_max_seconds=maximum,
        idle_multiplier=multiplier,
        action_cooldown_seconds=_positive_number(
            raw.get("action_cooldown_seconds", defaults.action_cooldown_seconds), "action_cooldown_seconds"
        ),
        autonomous_daily_model_calls=daily_calls,
        autonomous_daily_tokens=daily_tokens,
    )


def _parse_episode_budget(
    raw: dict[str, Any], default_calls: int, default_tools: int, default_duration: float, label: str
) -> EpisodeBudgetConfig:
    allowed = {"max_model_calls", "max_tool_calls", "max_duration_seconds"}
    if set(raw) - allowed:
        raise ConfigurationError(f"runtime.{label} has unsupported keys")
    calls = raw.get("max_model_calls", default_calls)
    tools = raw.get("max_tool_calls", default_tools)
    if not isinstance(calls, int) or isinstance(calls, bool) or calls <= 0:
        raise ConfigurationError(f"runtime.{label}.max_model_calls must be positive")
    if not isinstance(tools, int) or isinstance(tools, bool) or tools <= 0:
        raise ConfigurationError(f"runtime.{label}.max_tool_calls must be positive")
    return EpisodeBudgetConfig(calls, tools, _positive_number(raw.get("max_duration_seconds", default_duration), label))


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
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise ConfigurationError("dashboard must bind to loopback")
    port = raw["port"]
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
        host=host,
        port=port,
        database_path=database_path,
        upload_dir=upload_dir,
        max_upload_bytes=max_upload_bytes,
        session_ttl_seconds=session_ttl_seconds,
        allowed_origins=tuple(origins),
        bot=DashboardBotConfig(
            username=_string(bot_raw["username"], "dashboard.bot.username"),
            display_name=_string(bot_raw["display_name"], "dashboard.bot.display_name"),
            avatar_url=avatar_url or None,
        ),
    )


def load_configuration(root: Path, profile: str | None = None) -> AuroraConfig:
    """Load the selected RFC 0002 configuration snapshot."""
    root = root.resolve()
    base = _read_toml(root / "config" / "aurora.toml")
    _require_keys(base, {"runtime", "dashboard", "soul", "logging", "storage", "models"}, "aurora.toml")
    runtime_raw = base["runtime"]
    if not isinstance(runtime_raw, dict):
        raise ConfigurationError("runtime must be a table")
    selected_profile = profile or os.environ.get("AURORA_PROFILE") or runtime_raw.get("profile")
    if not isinstance(selected_profile, str) or not selected_profile:
        raise ConfigurationError("no profile selected")
    merged = base
    profile_path = root / "config" / "profiles" / f"{selected_profile}.toml"
    if profile_path.exists():
        merged = _merge(base, _read_toml(profile_path))
    _require_keys(
        merged,
        {"runtime", "dashboard", "soul", "logging", "storage", "models"},
        "merged aurora config",
    )
    runtime_raw = merged["runtime"]
    dashboard_raw = merged["dashboard"]
    soul_raw = merged["soul"]
    logging_raw = merged["logging"]
    storage_raw = merged["storage"]
    models_raw = merged["models"]
    if not all(
        isinstance(value, dict)
        for value in (runtime_raw, dashboard_raw, soul_raw, logging_raw, storage_raw, models_raw)
    ):
        raise ConfigurationError("aurora top-level sections must be tables")
    runtime_allowed = {
        "profile",
        "workspace",
        "debug_host",
        "debug_port",
        "scheduler",
        "interactive_episode",
        "autonomous_episode",
    }
    required_runtime = {"profile", "workspace", "debug_host", "debug_port"}
    if set(runtime_raw) - runtime_allowed or not required_runtime <= set(runtime_raw):
        raise ConfigurationError("runtime has unsupported or missing keys")
    _require_keys(soul_raw, {"path"}, "soul")
    _require_keys(logging_raw, {"level"}, "logging")
    _require_keys(storage_raw, {"data_dir"}, "storage")
    _require_keys(models_raw, {"roles", "providers", "logging"}, "models")
    debug_port = runtime_raw["debug_port"]
    if not isinstance(debug_port, int) or not 1 <= debug_port <= 65535:
        raise ConfigurationError("runtime.debug_port must be a valid port")
    debug_host = _string(runtime_raw["debug_host"], "runtime.debug_host")
    if selected_profile == "prod" and debug_host not in {"127.0.0.1", "::1", "localhost"}:
        raise ConfigurationError("production debug API must bind to loopback")
    roles = models_raw["roles"]
    providers = models_raw["providers"]
    model_logging = models_raw["logging"]
    if not isinstance(roles, dict) or not isinstance(providers, dict) or not isinstance(model_logging, dict):
        raise ConfigurationError("models.roles, models.providers and models.logging must be tables")
    _require_keys(model_logging, {"log_queries", "log_responses"}, "models.logging")
    if not isinstance(model_logging["log_queries"], bool) or not isinstance(model_logging["log_responses"], bool):
        raise ConfigurationError("models.logging values must be booleans")
    model_providers: dict[str, ModelProviderConfig] = {}
    for provider_id, settings in providers.items():
        if not isinstance(provider_id, str) or not isinstance(settings, dict):
            raise ConfigurationError("model provider IDs and settings must be tables")
        required_keys = {"adapter", "secret_env", "base_url"} if "base_url" in settings else {"adapter", "secret_env"}
        _require_keys(settings, required_keys, f"models.providers.{provider_id}")
        adapter = _string(settings["adapter"], f"models.providers.{provider_id}.adapter")
        if adapter not in {"litellm", "openai_compatible"}:
            raise ConfigurationError(f"models.providers.{provider_id}.adapter is unsupported")
        base_url = settings.get("base_url")
        if base_url is not None:
            base_url = _string(base_url, f"models.providers.{provider_id}.base_url")
        if adapter == "openai_compatible" and base_url is None:
            raise ConfigurationError(f"models.providers.{provider_id}.base_url is required")
        model_providers[provider_id] = ModelProviderConfig(
            id=provider_id,
            adapter=adapter,
            secret_env=_string(settings["secret_env"], f"models.providers.{provider_id}.secret_env"),
            base_url=base_url,
        )
    model_definitions: dict[str, ModelRoleConfig] = {}
    for role, settings in roles.items():
        if not isinstance(settings, dict):
            raise ConfigurationError(f"model role {role} must be a table")
        role_allowed = {"provider", "model", "capabilities", "endpoint"}
        if set(settings) - role_allowed or not {"provider", "model", "capabilities"} <= set(settings):
            raise ConfigurationError(f"models.roles.{role} has unsupported or missing keys")
        provider_id = _string(settings["provider"], f"models.roles.{role}.provider")
        if provider_id not in model_providers:
            raise ConfigurationError(f"models.roles.{role} references unknown provider")
        capabilities = settings["capabilities"]
        if not isinstance(capabilities, list) or not all(isinstance(value, str) for value in capabilities):
            raise ConfigurationError(f"models.roles.{role}.capabilities must contain strings")
        endpoint = settings.get("endpoint", "chat_completions")
        if endpoint not in {"chat_completions", "responses"}:
            raise ConfigurationError(f"models.roles.{role}.endpoint is unsupported")
        if endpoint == "responses" and "native_responses" not in capabilities:
            raise ConfigurationError(f"models.roles.{role} responses endpoint requires native_responses")
        model_definitions[role] = ModelRoleConfig(
            provider=provider_id,
            model=_string(settings["model"], f"models.roles.{role}.model"),
            capabilities=frozenset(capabilities),
            endpoint=endpoint,
        )
    soul_path = (root / _string(soul_raw["path"], "soul.path")).resolve()
    try:
        soul_hash = hashlib.sha256(soul_path.read_bytes()).hexdigest()
    except FileNotFoundError as error:
        raise ConfigurationError(f"SOUL file does not exist: {soul_path}") from error
    nodes, edges, advancing_edges = _parse_nodes(_read_toml(root / "config" / "nodes.toml"), frozenset(roles))
    adapters, apps = _parse_adapters(_read_toml(root / "config" / "apps.toml"), root)
    capability_definitions: dict[str, CapabilityConfig] = {}
    for adapter in adapters:
        for capability in adapter.capabilities:
            if capability.id in capability_definitions:
                raise ConfigurationError(f"duplicate capability {capability.id}")
            capability_definitions[capability.id] = capability
    app_tools = frozenset().union(*(app.allowed_tools for app in apps)) if apps else frozenset()
    for node in nodes:
        if not node.capabilities <= capability_definitions.keys() | app_tools:
            raise ConfigurationError(f"node {node.id} requests unavailable capabilities")
    scheduler_raw = runtime_raw.get("scheduler", {})
    interactive_raw = runtime_raw.get("interactive_episode", {})
    autonomous_raw = runtime_raw.get("autonomous_episode", {})
    if not all(isinstance(item, dict) for item in (scheduler_raw, interactive_raw, autonomous_raw)):
        raise ConfigurationError("runtime scheduler and episode budgets must be tables")
    scheduler = _parse_scheduler(scheduler_raw)
    interactive_budget = _parse_episode_budget(interactive_raw, 8, 6, 300.0, "interactive_episode")
    autonomous_budget = _parse_episode_budget(autonomous_raw, 3, 2, 120.0, "autonomous_episode")
    return AuroraConfig(
        root=root,
        runtime=RuntimeConfig(
            profile=selected_profile,
            workspace=(root / _string(runtime_raw["workspace"], "runtime.workspace")).resolve(),
            debug_host=debug_host,
            debug_port=debug_port,
            scheduler=scheduler,
            interactive_budget=interactive_budget,
            autonomous_budget=autonomous_budget,
        ),
        dashboard=_parse_dashboard(cast("dict[str, Any]", dashboard_raw), root),
        soul_path=soul_path,
        soul_hash=soul_hash,
        logging_level=_string(logging_raw["level"], "logging.level"),
        nodes=nodes,
        edges=edges,
        advancing_edges=advancing_edges,
        adapters=adapters,
        model_roles=frozenset(roles),
        model_definitions=model_definitions,
        model_providers=model_providers,
        capability_definitions=capability_definitions,
        model_logging=ModelLoggingConfig(
            log_queries=model_logging["log_queries"],
            log_responses=model_logging["log_responses"],
        ),
        apps=apps,
    )
