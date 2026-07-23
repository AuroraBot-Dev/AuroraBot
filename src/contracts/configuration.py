"""叶子级不可变配置 DTO 与 RFC 0002 TOML 校验。"""

from __future__ import annotations

import copy
import hashlib
import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from src.contracts.agent import AgentLimits, AgentProfile, TaskBudget


class ConfigurationError(ValueError):
    """启动前因无效结构性配置抛出。"""


@dataclass(frozen=True, slots=True)
class ConfigurationSource:
    """可审计的配置来源：记录文件路径和 SHA-256 摘要。"""

    path: Path
    sha256: str


def _read_toml_snapshot(path: Path) -> tuple[dict[str, Any], ConfigurationSource]:
    """读取 TOML 文件并返回解析数据和配置来源快照。"""
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
    """深度合并两个字典，嵌套字典递归合并。"""
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
    """检查字典键恰好为指定集合，不允许多余或缺失。"""
    unexpected = set(value) - keys
    missing = keys - set(value)
    if unexpected or missing:
        raise ConfigurationError(f"{label} has unexpected {sorted(unexpected)} or missing {sorted(missing)} keys")


def _require_subset(data: dict[str, Any], required: set[str], label: str) -> None:
    """检查字典至少包含指定的必需键。"""
    missing = required - set(data)
    if missing:
        raise ConfigurationError(f"{label} is missing required keys: {sorted(missing)}")


def _table(value: object, label: str) -> dict[str, Any]:
    """校验值为 TOML 表（dict）类型。"""
    if not isinstance(value, dict):
        raise ConfigurationError(f"{label} must be a table")
    return value


def _string(value: object, label: str) -> str:
    """校验值为非空字符串。"""
    if not isinstance(value, str) or not value:
        raise ConfigurationError(f"{label} must be a non-empty string")
    return value


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    """运行时配置：profile、工作区、调试、自主、Agent 限制和预算。"""

    profile: str
    workspace: Path
    debug_host: str
    debug_port: int
    autonomy: "AutonomyConfig"
    agents: "AgentLimits"
    interactive_budget: "TaskBudget"
    autonomous_budget: "TaskBudget"


@dataclass(frozen=True, slots=True)
class AutonomyConfig:
    """自主节律配置：扫描间隔、心跳边界和每日额度。"""

    scan_seconds: float = 1.0
    heartbeat_initial_seconds: float = 30.0
    heartbeat_min_seconds: float = 30.0
    heartbeat_max_seconds: float = 1800.0
    autonomous_daily_model_calls: int = 24
    autonomous_daily_tokens: int = 100_000


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
class AppConfig:
    """一个显式启用的 MCP 应用路由配置。"""

    package: str
    transport: str
    working_dir: Path | None
    command: tuple[str, ...]
    url: str | None
    auth_env: str | None
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class ModelProviderConfig:
    """TOML 定义的 LiteLLM 或 OpenAI 兼容 Provider 路由。"""

    id: str
    adapter: str
    secret_env: str
    base_url: str | None


@dataclass(frozen=True, slots=True)
class ModelRoleConfig:
    """模型角色的非密钥配置，capabilities 为空时由 models.dev 自动派生。"""

    provider: str
    model: str
    capabilities: frozenset[str] = frozenset()
    endpoint: str = "chat_completions"


@dataclass(frozen=True, slots=True)
class ModelLoggingConfig:
    """模型网关的可选 DEBUG 日志控制。"""

    log_queries: bool
    log_responses: bool


@dataclass(frozen=True, slots=True)
class ConsolePreference:
    enabled: bool
    terminal_logs: bool


@dataclass(frozen=True, slots=True)
class DashboardPreference:
    enabled: bool
    open_browser: bool


@dataclass(frozen=True, slots=True)
class McpPreference:
    enabled: bool
    terminal_logs: bool


@dataclass(frozen=True, slots=True)
class PlatformPreference:
    console: ConsolePreference
    dashboard: DashboardPreference
    mcp: McpPreference


@dataclass(frozen=True, slots=True)
class AuroraConfig:
    """聚合所有 TOML 配置的根配置对象。"""

    root: Path
    sources: tuple[ConfigurationSource, ...]
    runtime: RuntimeConfig
    dashboard: DashboardConfig
    preference: PlatformPreference
    logging_level: str
    storage_data_dir: Path
    agents: "tuple[AgentProfile, ...]"
    model_roles: frozenset[str]
    model_definitions: Mapping[str, ModelRoleConfig]
    model_providers: Mapping[str, ModelProviderConfig]
    model_logging: ModelLoggingConfig
    apps: tuple[AppConfig, ...]


def _positive_number(value: object, label: str) -> float:
    """校验值为正数（int 或 float），返回 float。"""
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        raise ConfigurationError(f"{label} must be positive")
    return float(value)


def load_configuration(root: Path, profile: str | None = None) -> AuroraConfig:
    """加载选定的 RFC 0002 配置快照：读取 TOML → 合并 profile → 校验并组装。"""
    from src.contracts.configuration_sections import (
        _parse_agent_runtime,
        _parse_agents,
        _parse_apps,
        _parse_autonomy,
        _parse_dashboard,
        _parse_preference,
        _parse_task_budget,
    )

    root = root.resolve()
    config_dir = root / "config"
    sources: list[ConfigurationSource] = []

    # 加载运行时配置
    runtime_data, runtime_source = _read_toml_snapshot(config_dir / "runtime.toml")
    sources.append(runtime_source)
    runtime_raw = runtime_data.get("runtime", {})
    if not isinstance(runtime_raw, dict):
        raise ConfigurationError("runtime must be a table")

    # 确定profile
    selected_profile = profile or os.environ.get("AURORA_PROFILE") or runtime_raw.get("profile")
    if not isinstance(selected_profile, str) or not selected_profile:
        raise ConfigurationError("no profile selected")

    # 合并profile覆盖
    merged_runtime = runtime_data
    profile_path = config_dir / "profiles" / f"{selected_profile}.toml"
    if profile_path.exists():
        profile_data, profile_source = _read_toml_snapshot(profile_path)
        # 验证profile只包含runtime.toml中允许的配置项
        allowed_profile_keys = {"runtime"}
        unexpected_keys = set(profile_data) - allowed_profile_keys
        if unexpected_keys:
            raise ConfigurationError(f"profile has unexpected keys: {sorted(unexpected_keys)}")
        merged_runtime = _merge(runtime_data, profile_data)
        sources.append(profile_source)

    runtime_raw = merged_runtime.get("runtime", {})
    if not isinstance(runtime_raw, dict):
        raise ConfigurationError("runtime must be a table")

    # 验证运行时配置
    runtime_allowed = {
        "profile",
        "workspace",
        "debug_host",
        "debug_port",
        "autonomy",
        "agents",
        "interactive_task",
        "autonomous_task",
    }
    required_runtime = {"profile", "workspace", "debug_host", "debug_port"}
    if set(runtime_raw) - runtime_allowed or not required_runtime <= set(runtime_raw):
        raise ConfigurationError("runtime has unsupported or missing keys")

    # 加载平台配置
    platforms_data, platforms_source = _read_toml_snapshot(config_dir / "platforms.toml")
    sources.append(platforms_source)
    platform_raw = platforms_data.get("platform")
    if not isinstance(platform_raw, dict):
        raise ConfigurationError("platforms.toml must contain a [platform] table")
    dashboard_raw = platform_raw.get("dashboard")
    if not isinstance(dashboard_raw, dict):
        raise ConfigurationError("platform.dashboard must be a table")
    preference = _parse_preference(platform_raw)

    # 加载模型配置
    models_data, models_source = _read_toml_snapshot(config_dir / "models.toml")
    sources.append(models_source)
    models_raw = models_data.get("models", {})
    if not isinstance(models_raw, dict):
        raise ConfigurationError("models must be a table")
    _require_keys(models_raw, {"roles", "providers", "logging"}, "models")

    # 加载日志和存储配置
    logging_data, logging_source = _read_toml_snapshot(config_dir / "logging.toml")
    sources.append(logging_source)
    logging_raw = logging_data.get("logging", {})
    storage_raw = logging_data.get("storage", {})
    if not isinstance(logging_raw, dict) or not isinstance(storage_raw, dict):
        raise ConfigurationError("logging and storage must be tables")
    _require_keys(logging_raw, {"level"}, "logging")
    _require_keys(storage_raw, {"data_dir"}, "storage")

    # 解析模型配置
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
        if set(settings) - role_allowed or not {"provider", "model"} <= set(settings):
            raise ConfigurationError(f"models.roles.{role} has unsupported or missing keys")
        provider_id = _string(settings["provider"], f"models.roles.{role}.provider")
        if provider_id not in model_providers:
            raise ConfigurationError(f"models.roles.{role} references unknown provider")
        capabilities_raw = settings.get("capabilities")
        if capabilities_raw is not None:
            if not isinstance(capabilities_raw, list) or not all(isinstance(value, str) for value in capabilities_raw):
                raise ConfigurationError(f"models.roles.{role}.capabilities must contain strings")
            capabilities = frozenset(capabilities_raw)
        else:
            capabilities = frozenset()
        endpoint = settings.get("endpoint", "chat_completions")
        if endpoint not in {"chat_completions", "responses"}:
            raise ConfigurationError(f"models.roles.{role}.endpoint is unsupported")
        model_definitions[role] = ModelRoleConfig(
            provider=provider_id,
            model=_string(settings["model"], f"models.roles.{role}.model"),
            capabilities=capabilities,
            endpoint=endpoint,
        )

    # 加载代理和应用配置
    agents_data, agents_source = _read_toml_snapshot(config_dir / "agents.toml")
    apps_data, apps_source = _read_toml_snapshot(config_dir / "apps.toml")
    sources.extend((agents_source, apps_source))
    agents = _parse_agents(agents_data, frozenset(roles))
    _require_keys(apps_data, {"app"}, "apps.toml")
    apps = _parse_apps(apps_data["app"], root)

    # 解析运行时子配置
    autonomy_raw = runtime_raw.get("autonomy", {})
    agents_raw = runtime_raw.get("agents", {})
    interactive_raw = runtime_raw.get("interactive_task", {})
    autonomous_raw = runtime_raw.get("autonomous_task", {})
    if not all(isinstance(item, dict) for item in (autonomy_raw, agents_raw, interactive_raw, autonomous_raw)):
        raise ConfigurationError("runtime autonomy, Agents and Task budgets must be tables")

    # 验证调试端口和主机
    debug_port = runtime_raw["debug_port"]
    if not isinstance(debug_port, int) or not 1 <= debug_port <= 65535:
        raise ConfigurationError("runtime.debug_port must be a valid port")
    debug_host = _string(runtime_raw["debug_host"], "runtime.debug_host")
    if selected_profile == "prod" and debug_host not in {"127.0.0.1", "::1", "localhost"}:
        raise ConfigurationError("production debug API must bind to loopback")

    # 解析子配置
    autonomy = _parse_autonomy(autonomy_raw)
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

    # 验证工作区
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
            autonomy=autonomy,
            agents=agent_runtime,
            interactive_budget=interactive_budget,
            autonomous_budget=autonomous_budget,
        ),
        dashboard=_parse_dashboard(cast("dict[str, Any]", dashboard_raw), root),
        preference=preference,
        logging_level=_string(logging_raw["level"], "logging.level"),
        storage_data_dir=(root / _string(storage_raw["data_dir"], "storage.data_dir")).resolve(),
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
