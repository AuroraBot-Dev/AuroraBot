"""Leaf-level immutable configuration DTOs and RFC 0002 TOML validation."""

from __future__ import annotations

import copy
import hashlib
import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast


class ConfigurationError(ValueError):
    """Raised before startup for invalid structural configuration."""


@dataclass(frozen=True, slots=True)
class ConfigurationSource:
    """Auditable identity of one file used to build a configuration snapshot."""

    path: Path
    sha256: str


def _read_toml_snapshot(path: Path) -> tuple[dict[str, Any], ConfigurationSource]:
    path = path.resolve()
    try:
        content = path.read_bytes()
        data = tomllib.loads(content.decode("utf-8"))
    except FileNotFoundError as error:
        raise ConfigurationError(f"configuration file does not exist: {path}") from error
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise ConfigurationError(f"invalid TOML in {path}: {error}") from error
    return data, ConfigurationSource(path=path, sha256=hashlib.sha256(content).hexdigest())


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
    agents: "AgentRuntimeConfig"
    interactive_budget: "TaskBudgetConfig"
    autonomous_budget: "TaskBudgetConfig"


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
class TaskBudgetConfig:
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
    owner_username: str
    bot: DashboardBotConfig


@dataclass(frozen=True, slots=True)
class AgentRuntimeConfig:
    root_profile: str = "builtin.gate"
    worker_profile: str = "builtin.worker"
    memory_agent_profile: str | None = None
    max_active_agents: int = 16
    max_agents_per_task: int = 8
    max_depth: int = 3
    max_children_per_agent: int = 4
    turn_concurrency: int = 8
    model_concurrency: int = 4
    tool_concurrency: int = 8
    blocking_workers: int = 4
    lease_seconds: float = 30.0
    ambient_ttl_seconds: float = 1800.0


@dataclass(frozen=True, slots=True)
class AgentProfileConfig:
    id: str
    implementation: str
    model_role: str
    capabilities: frozenset[str]
    can_delegate: bool
    child_profiles: frozenset[str]


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
    sources: tuple[ConfigurationSource, ...]
    runtime: RuntimeConfig
    dashboard: DashboardConfig
    logging_level: str
    agents: tuple[AgentProfileConfig, ...]
    model_roles: frozenset[str]
    model_definitions: Mapping[str, ModelRoleConfig]
    model_providers: Mapping[str, ModelProviderConfig]
    model_logging: ModelLoggingConfig
    apps: tuple[AppConfig, ...]


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


def load_configuration(root: Path, profile: str | None = None) -> AuroraConfig:
    """Load the selected RFC 0002 configuration snapshot."""
    from src.contracts.configuration_sections import (
        _parse_agent_runtime,
        _parse_agents,
        _parse_apps,
        _parse_dashboard,
    )

    root = root.resolve()
    base, base_source = _read_toml_snapshot(root / "config" / "aurora.toml")
    sources = [base_source]
    _require_keys(
        base,
        {"runtime", "dashboard", "logging", "storage", "models"},
        "aurora.toml",
    )
    runtime_raw = base["runtime"]
    if not isinstance(runtime_raw, dict):
        raise ConfigurationError("runtime must be a table")
    selected_profile = profile or os.environ.get("AURORA_PROFILE") or runtime_raw.get("profile")
    if not isinstance(selected_profile, str) or not selected_profile:
        raise ConfigurationError("no profile selected")
    merged = base
    profile_path = root / "config" / "profiles" / f"{selected_profile}.toml"
    if profile_path.exists():
        profile_data, profile_source = _read_toml_snapshot(profile_path)
        merged = _merge(base, profile_data)
        sources.append(profile_source)
    _require_keys(
        merged,
        {"runtime", "dashboard", "logging", "storage", "models"},
        "merged aurora config",
    )
    runtime_raw = merged["runtime"]
    dashboard_raw = merged["dashboard"]
    logging_raw = merged["logging"]
    storage_raw = merged["storage"]
    models_raw = merged["models"]
    if not all(isinstance(value, dict) for value in (runtime_raw, dashboard_raw, logging_raw, storage_raw, models_raw)):
        raise ConfigurationError("aurora top-level sections must be tables")
    runtime_allowed = {
        "profile",
        "workspace",
        "debug_host",
        "debug_port",
        "scheduler",
        "agents",
        "interactive_task",
        "autonomous_task",
    }
    required_runtime = {"profile", "workspace", "debug_host", "debug_port"}
    if set(runtime_raw) - runtime_allowed or not required_runtime <= set(runtime_raw):
        raise ConfigurationError("runtime has unsupported or missing keys")
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
    agents_data, agents_source = _read_toml_snapshot(root / "config" / "agents.toml")
    apps_data, apps_source = _read_toml_snapshot(root / "config" / "apps.toml")
    sources.extend((agents_source, apps_source))
    agents = _parse_agents(agents_data, frozenset(roles))
    _require_keys(apps_data, {"app"}, "apps.toml")
    apps = _parse_apps(apps_data["app"], root)
    scheduler_raw = runtime_raw.get("scheduler", {})
    agents_raw = runtime_raw.get("agents", {})
    interactive_raw = runtime_raw.get("interactive_task", {})
    autonomous_raw = runtime_raw.get("autonomous_task", {})
    if not all(isinstance(item, dict) for item in (scheduler_raw, agents_raw, interactive_raw, autonomous_raw)):
        raise ConfigurationError("runtime scheduler, Agents and Task budgets must be tables")
    scheduler = _parse_scheduler(scheduler_raw)
    agent_runtime = _parse_agent_runtime(agents_raw)
    if agent_runtime.root_profile not in {agent.id for agent in agents}:
        raise ConfigurationError("runtime.agents.root_profile is not configured")
    if agent_runtime.worker_profile not in {agent.id for agent in agents}:
        raise ConfigurationError("runtime.agents.worker_profile is not configured")
    if agent_runtime.memory_agent_profile is not None and agent_runtime.memory_agent_profile not in {
        agent.id for agent in agents
    }:
        raise ConfigurationError("runtime.agents.memory_agent_profile is not configured")
    interactive_budget = _parse_task_budget(interactive_raw, 8, 6, 300.0, "interactive_task")
    autonomous_budget = _parse_task_budget(autonomous_raw, 3, 2, 120.0, "autonomous_task")
    workspace = (root / _string(runtime_raw["workspace"], "runtime.workspace")).resolve()
    expected_workspace = (root / "data" / "kernel").resolve()
    if workspace != expected_workspace:
        raise ConfigurationError("runtime.workspace must be data/kernel")
    return AuroraConfig(
        root=root,
        sources=tuple(sources),
        runtime=RuntimeConfig(
            profile=selected_profile,
            workspace=workspace,
            debug_host=debug_host,
            debug_port=debug_port,
            scheduler=scheduler,
            agents=agent_runtime,
            interactive_budget=interactive_budget,
            autonomous_budget=autonomous_budget,
        ),
        dashboard=_parse_dashboard(cast("dict[str, Any]", dashboard_raw), root),
        logging_level=_string(logging_raw["level"], "logging.level"),
        agents=agents,
        model_roles=frozenset(roles),
        model_definitions=MappingProxyType(model_definitions),
        model_providers=MappingProxyType(model_providers),
        model_logging=ModelLoggingConfig(
            log_queries=model_logging["log_queries"],
            log_responses=model_logging["log_responses"],
        ),
        apps=apps,
    )
