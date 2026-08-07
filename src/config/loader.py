"""TOML 配置加载与校验 —— 读取所有 config/ 文件并组装为不可变 AuroraConfig。

按文件拆分为聚焦加载器：runtime/profile、engine、models、storage、platforms、
agents/apps，最后由 ``load_configuration`` 做跨段引用校验与组装。
"""

from __future__ import annotations

import copy
import os
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, cast

from src.config.files import read_toml_snapshot
from src.config.helpers import _require_keys, _string
from src.config.prompts import load_prompts
from src.config.sections import (
    _parse_agent_runtime,
    _parse_agents,
    _parse_apps,
    _parse_autonomy,
    _parse_dashboard,
    _parse_preference,
    _parse_task_budget,
    _parse_triage,
)
from src.contracts.configuration import (
    AuroraConfig,
    ConfigurationError,
    ConfigurationSource,
    ConsoleConfig,
    EngineConfig,
    ModelLoggingConfig,
    ModelProviderConfig,
    ModelRoleConfig,
    RuntimeConfig,
    StorageConfig,
)

if TYPE_CHECKING:
    from src.contracts.agent import AgentProfile
    from src.contracts.configuration import AppConfig, DashboardConfig, PlatformPreference


class _Msg(StrEnum):
    """本文件内所有用户可见或日志输出的字符串常量。"""

    PROFILE_TYPE_MISMATCH = "profile type mismatch at {key}"
    RUNTIME_MUST_BE_TABLE = "runtime must be a table"
    NO_PROFILE_SELECTED = "no profile selected"
    PROFILE_NOT_FOUND = "profile does not exist: {profile}"
    RUNTIME_UNSUPPORTED_KEYS = "runtime has unsupported or missing keys"
    MUST_BE_BOOLEAN = "{label} must be boolean"
    ENGINE_MUST_BE_TABLE = "engine must be a table"
    ENGINE_UNSUPPORTED_KEYS = "engine has unsupported or missing keys"
    PLATFORMS_NO_PLATFORM_TABLE = "platforms.toml must contain a [platform] table"
    DASHBOARD_MUST_BE_TABLE = "platform.dashboard must be a table"
    MODELS_MUST_BE_TABLE = "models must be a table"
    LOGGING_STORAGE_MUST_BE_TABLES = "logging and storage must be tables"
    STORAGE_PLATFORM_MUST_BE_TABLE = "storage.platform must be a table"
    STORAGE_PATH_SANDBOX = "{label} must stay within its parent storage directory"
    STORAGE_ENTRIES_MUST_BE_TABLES = "storage platform entries must be tables"
    PACKAGE_STORAGE_OVERLAP = "package storage directories must not overlap"
    MODEL_SECTIONS_MUST_BE_TABLES = "models.roles, models.providers and models.logging must be tables"
    MODEL_LOGGING_BOOLEAN = "models.logging values must be booleans"
    PROVIDER_MUST_BE_TABLE = "model provider IDs and settings must be tables"
    PROVIDER_ADAPTER_UNSUPPORTED = "models.providers.{provider_id}.adapter is unsupported"
    PROVIDER_BASE_URL_REQUIRED = "models.providers.{provider_id}.base_url is required"
    ROLE_MUST_BE_TABLE = "model role {role} must be a table"
    ROLE_UNSUPPORTED_KEYS = "models.roles.{role} has unsupported or missing keys"
    ROLE_UNKNOWN_PROVIDER = "models.roles.{role} references unknown provider"
    ROLE_CAPABILITIES_STRINGS = "models.roles.{role}.capabilities must contain strings"
    ROLE_ENDPOINT_UNSUPPORTED = "models.roles.{role}.endpoint is unsupported"
    ENGINE_SUB_MUST_BE_TABLES = "engine autonomy, Agents and Task budgets must be tables"
    TRIAGE_UNKNOWN_ROLE = "engine.triage.model_role references unknown role {model_role}"
    DEBUG_PORT_INVALID = "runtime.debug_port must be a valid port"
    PROD_DEBUG_LOOPBACK = "production debug API must bind to loopback"
    ROOT_PROFILE_NOT_CONFIGURED = "engine.agents.root_profile is not configured"
    WORKER_PROFILE_NOT_CONFIGURED = "engine.agents.worker_profile is not configured"
    WORKSPACE_MISMATCH = "engine.workspace must match storage.engine"
    PROFILE_NAME_INVALID = "profile must be a simple name"
    PROFILE_VALUE_MISMATCH = "profile file runtime.profile must match the selected profile"


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """深度合并两个字典，嵌套字典递归合并。"""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) != isinstance(value, dict):
            raise ConfigurationError(_Msg.PROFILE_TYPE_MISMATCH.format(key=key))
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


# -- 分文件加载器 ---------------------------------------------------------


def _load_runtime_config(config_dir: Path, sources: list[ConfigurationSource], profile: str | None) -> RuntimeConfig:
    """加载 runtime.toml，合并 profile 覆盖并校验运行时配置。"""
    runtime_data, runtime_source = read_toml_snapshot(config_dir / "runtime.toml")
    sources.append(runtime_source)
    _require_keys(runtime_data, {"runtime"}, "runtime.toml")
    runtime_raw = runtime_data.get("runtime", {})
    if not isinstance(runtime_raw, dict):
        raise ConfigurationError(_Msg.RUNTIME_MUST_BE_TABLE)

    selected_profile = profile or os.environ.get("AURORA_PROFILE") or runtime_raw.get("profile")
    if not isinstance(selected_profile, str) or not selected_profile:
        raise ConfigurationError(_Msg.NO_PROFILE_SELECTED)
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", selected_profile) is None:
        raise ConfigurationError(_Msg.PROFILE_NAME_INVALID)

    profile_path = config_dir / "profiles" / f"{selected_profile}.toml"
    if not profile_path.exists():
        raise ConfigurationError(_Msg.PROFILE_NOT_FOUND.format(profile=selected_profile))
    profile_data, profile_source = read_toml_snapshot(profile_path)
    _require_keys(profile_data, {"runtime"}, "profile")
    merged_runtime = _merge(runtime_data, profile_data)
    sources.append(profile_source)

    runtime_raw = merged_runtime.get("runtime", {})
    if not isinstance(runtime_raw, dict):
        raise ConfigurationError(_Msg.RUNTIME_MUST_BE_TABLE)
    runtime_allowed = {"profile", "debug_host", "debug_port", "console"}
    required_runtime = set(runtime_allowed)
    if set(runtime_raw) - runtime_allowed or not required_runtime <= set(runtime_raw):
        raise ConfigurationError(_Msg.RUNTIME_UNSUPPORTED_KEYS)
    if runtime_raw["profile"] != selected_profile:
        raise ConfigurationError(_Msg.PROFILE_VALUE_MISMATCH)

    debug_port = runtime_raw["debug_port"]
    if not isinstance(debug_port, int) or isinstance(debug_port, bool) or not 1 <= debug_port <= 65535:
        raise ConfigurationError(_Msg.DEBUG_PORT_INVALID)
    debug_host = _string(runtime_raw["debug_host"], "runtime.debug_host")
    if selected_profile == "prod" and debug_host not in {"127.0.0.1", "::1", "localhost"}:
        raise ConfigurationError(_Msg.PROD_DEBUG_LOOPBACK)
    console_raw = runtime_raw["console"]
    if not isinstance(console_raw, dict):
        raise ConfigurationError(_Msg.RUNTIME_MUST_BE_TABLE)
    _require_keys(console_raw, {"enabled", "terminal_logs"}, "runtime.console")
    if not isinstance(console_raw["enabled"], bool):
        raise ConfigurationError(_Msg.MUST_BE_BOOLEAN.format(label="runtime.console.enabled"))
    if not isinstance(console_raw["terminal_logs"], bool):
        raise ConfigurationError(_Msg.MUST_BE_BOOLEAN.format(label="runtime.console.terminal_logs"))
    console = ConsoleConfig(
        enabled=console_raw["enabled"],
        terminal_logs=console_raw["terminal_logs"],
    )
    return RuntimeConfig(profile=selected_profile, debug_host=debug_host, debug_port=debug_port, console=console)


def _load_engine_raw(config_dir: Path, sources: list[ConfigurationSource]) -> dict[str, Any]:
    """加载 engine.toml 并校验顶层结构；profile 不得覆盖此文件。"""
    engine_data, engine_source = read_toml_snapshot(config_dir / "engine.toml")
    sources.append(engine_source)
    _require_keys(engine_data, {"engine"}, "engine.toml")
    engine_raw = engine_data.get("engine", {})
    if not isinstance(engine_raw, dict):
        raise ConfigurationError(_Msg.ENGINE_MUST_BE_TABLE)
    engine_allowed = {"workspace", "autonomy", "agents", "triage", "interactive_task", "autonomous_task"}
    if set(engine_raw) != engine_allowed:
        raise ConfigurationError(_Msg.ENGINE_UNSUPPORTED_KEYS)
    return engine_raw


def _load_models(
    config_dir: Path, sources: list[ConfigurationSource]
) -> tuple[dict[str, ModelRoleConfig], dict[str, ModelProviderConfig], ModelLoggingConfig]:
    """加载 models.toml，解析角色、提供商与日志开关。"""
    models_data, models_source = read_toml_snapshot(config_dir / "models.toml")
    sources.append(models_source)
    _require_keys(models_data, {"models"}, "models.toml")
    models_raw = models_data.get("models", {})
    if not isinstance(models_raw, dict):
        raise ConfigurationError(_Msg.MODELS_MUST_BE_TABLE)
    _require_keys(models_raw, {"roles", "providers", "logging"}, "models")

    roles = models_raw["roles"]
    providers = models_raw["providers"]
    model_logging = models_raw["logging"]
    if not isinstance(roles, dict) or not isinstance(providers, dict) or not isinstance(model_logging, dict):
        raise ConfigurationError(_Msg.MODEL_SECTIONS_MUST_BE_TABLES)
    _require_keys(model_logging, {"log_queries", "log_responses"}, "models.logging")
    if not isinstance(model_logging["log_queries"], bool) or not isinstance(model_logging["log_responses"], bool):
        raise ConfigurationError(_Msg.MODEL_LOGGING_BOOLEAN)

    model_providers: dict[str, ModelProviderConfig] = {}
    for provider_id, settings in providers.items():
        if not isinstance(provider_id, str) or not isinstance(settings, dict):
            raise ConfigurationError(_Msg.PROVIDER_MUST_BE_TABLE)
        required_keys = {"adapter", "secret_env", "base_url"} if "base_url" in settings else {"adapter", "secret_env"}
        _require_keys(settings, required_keys, f"models.providers.{provider_id}")
        adapter = _string(settings["adapter"], f"models.providers.{provider_id}.adapter")
        if adapter not in {"litellm", "openai_compatible"}:
            raise ConfigurationError(_Msg.PROVIDER_ADAPTER_UNSUPPORTED.format(provider_id=provider_id))
        base_url = settings.get("base_url")
        if base_url is not None:
            base_url = _string(base_url, f"models.providers.{provider_id}.base_url")
        if adapter == "openai_compatible" and base_url is None:
            raise ConfigurationError(_Msg.PROVIDER_BASE_URL_REQUIRED.format(provider_id=provider_id))
        model_providers[provider_id] = ModelProviderConfig(
            id=provider_id,
            adapter=adapter,
            secret_env=_string(settings["secret_env"], f"models.providers.{provider_id}.secret_env"),
            base_url=base_url,
        )

    model_definitions: dict[str, ModelRoleConfig] = {}
    for role, settings in roles.items():
        if not isinstance(settings, dict):
            raise ConfigurationError(_Msg.ROLE_MUST_BE_TABLE.format(role=role))
        role_allowed = {"provider", "model", "capabilities", "endpoint"}
        if set(settings) - role_allowed or not {"provider", "model"} <= set(settings):
            raise ConfigurationError(_Msg.ROLE_UNSUPPORTED_KEYS.format(role=role))
        provider_id = _string(settings["provider"], f"models.roles.{role}.provider")
        if provider_id not in model_providers:
            raise ConfigurationError(_Msg.ROLE_UNKNOWN_PROVIDER.format(role=role))
        capabilities_raw = settings.get("capabilities")
        if capabilities_raw is not None:
            if not isinstance(capabilities_raw, list) or not all(isinstance(value, str) for value in capabilities_raw):
                raise ConfigurationError(_Msg.ROLE_CAPABILITIES_STRINGS.format(role=role))
            capabilities = frozenset(capabilities_raw)
        else:
            capabilities = frozenset()
        endpoint = settings.get("endpoint", "chat_completions")
        if endpoint not in {"chat_completions", "responses"}:
            raise ConfigurationError(_Msg.ROLE_ENDPOINT_UNSUPPORTED.format(role=role))
        model_definitions[role] = ModelRoleConfig(
            provider=provider_id,
            model=_string(settings["model"], f"models.roles.{role}.model"),
            capabilities=capabilities,
            endpoint=endpoint,
        )

    return (
        model_definitions,
        model_providers,
        ModelLoggingConfig(
            log_queries=model_logging["log_queries"],
            log_responses=model_logging["log_responses"],
        ),
    )


@dataclass(frozen=True, slots=True)
class _StorageSnapshot:
    """存储与日志路径校验结果，供跨段引用校验使用。"""

    level: str
    log_dir: Path
    storage: StorageConfig
    engine_dir: Path
    dashboard_dir: Path


def _load_storage(root: Path, config_dir: Path, sources: list[ConfigurationSource]) -> _StorageSnapshot:
    """加载 logging.toml 与 storage.toml，校验所有存储路径沙箱与互不重叠。"""
    logging_data, logging_source = read_toml_snapshot(config_dir / "logging.toml")
    storage_data, storage_source = read_toml_snapshot(config_dir / "storage.toml")
    sources.extend((logging_source, storage_source))
    logging_raw = logging_data.get("logging", {})
    storage_raw = storage_data.get("storage", {})
    _require_keys(logging_data, {"logging"}, "logging.toml")
    _require_keys(storage_data, {"storage"}, "storage.toml")
    if not isinstance(logging_raw, dict) or not isinstance(storage_raw, dict):
        raise ConfigurationError(_Msg.LOGGING_STORAGE_MUST_BE_TABLES)
    _require_keys(logging_raw, {"level", "log_dir"}, "logging")
    _require_keys(storage_raw, {"data_root", "engine", "ai", "memory", "platform"}, "storage")
    storage_platform_raw = storage_raw["platform"]
    if not isinstance(storage_platform_raw, dict):
        raise ConfigurationError(_Msg.STORAGE_PLATFORM_MUST_BE_TABLE)
    _require_keys(storage_platform_raw, {"data_dir", "dashboard", "mcp"}, "storage.platform")

    def storage_path(raw: object, label: str, *, parent: Path) -> Path:
        path = (parent / _string(raw, label)).resolve()
        if not path.is_relative_to(parent.resolve()):
            raise ConfigurationError(_Msg.STORAGE_PATH_SANDBOX.format(label=label))
        return path

    data_root = storage_path(storage_raw["data_root"], "storage.data_root", parent=root)
    engine_dir = storage_path(storage_raw["engine"], "storage.engine", parent=data_root)
    ai_dir = storage_path(storage_raw["ai"], "storage.ai", parent=data_root)
    memory_dir = storage_path(storage_raw["memory"], "storage.memory", parent=data_root)
    platform_dir = storage_path(storage_platform_raw["data_dir"], "storage.platform.data_dir", parent=data_root)
    dashboard_storage = storage_platform_raw["dashboard"]
    mcp_storage = storage_platform_raw["mcp"]
    if not isinstance(dashboard_storage, dict) or not isinstance(mcp_storage, dict):
        raise ConfigurationError(_Msg.STORAGE_ENTRIES_MUST_BE_TABLES)
    _require_keys(dashboard_storage, {"data_dir"}, "storage.platform.dashboard")
    _require_keys(mcp_storage, {"data_dir", "apps_dir"}, "storage.platform.mcp")
    dashboard_dir = storage_path(
        dashboard_storage["data_dir"], "storage.platform.dashboard.data_dir", parent=platform_dir
    )
    mcp_dir = storage_path(mcp_storage["data_dir"], "storage.platform.mcp.data_dir", parent=platform_dir)
    apps_dir = storage_path(mcp_storage["apps_dir"], "storage.platform.mcp.apps_dir", parent=mcp_dir)
    package_directories = {
        "engine": engine_dir,
        "ai": ai_dir,
        "memory": memory_dir,
        "platform": platform_dir,
        "dashboard": dashboard_dir,
        "mcp": mcp_dir,
        "apps": apps_dir,
    }
    _validate_package_directories(package_directories)

    return _StorageSnapshot(
        level=_string(logging_raw["level"], "logging.level"),
        log_dir=storage_path(logging_raw["log_dir"], "logging.log_dir", parent=root),
        storage=StorageConfig(
            data_root=data_root,
            engine=engine_dir,
            ai=ai_dir,
            memory=memory_dir,
            platform=platform_dir,
            dashboard=dashboard_dir,
            mcp=mcp_dir,
            apps=apps_dir,
        ),
        engine_dir=engine_dir,
        dashboard_dir=dashboard_dir,
    )


# 允许的包含关系（含传递闭包）：目录可嵌套在声明过的祖先包之下
_PACKAGE_STORAGE_CONTAINS: dict[str, frozenset[str]] = {
    "platform": frozenset({"dashboard", "mcp", "apps"}),
    "mcp": frozenset({"apps"}),
    "dashboard": frozenset(),
    "engine": frozenset(),
    "ai": frozenset(),
    "memory": frozenset(),
    "apps": frozenset(),
}


def _validate_package_directories(package_directories: dict[str, Path]) -> None:
    """校验各包数据目录互不重叠，仅允许声明过的祖先包含关系。"""
    paths = list(package_directories.items())
    for index, (label, directory) in enumerate(paths):
        for other_label, other in paths[index + 1 :]:
            if directory == other:
                raise ConfigurationError(_Msg.PACKAGE_STORAGE_OVERLAP)
            if not (directory.is_relative_to(other) or other.is_relative_to(directory)):
                continue
            if label in _PACKAGE_STORAGE_CONTAINS[other_label] or other_label in _PACKAGE_STORAGE_CONTAINS[label]:
                continue
            raise ConfigurationError(_Msg.PACKAGE_STORAGE_OVERLAP)


def _load_platforms(
    config_dir: Path,
    sources: list[ConfigurationSource],
    *,
    dashboard_dir: Path,
    engine_dir: Path,
) -> tuple[PlatformPreference, DashboardConfig]:
    """加载 platforms.toml，解析平台偏好与 Dashboard 配置。"""
    platforms_data, platforms_source = read_toml_snapshot(config_dir / "platforms.toml")
    sources.append(platforms_source)
    _require_keys(platforms_data, {"platform"}, "platforms.toml")
    platform_raw = platforms_data.get("platform")
    if not isinstance(platform_raw, dict):
        raise ConfigurationError(_Msg.PLATFORMS_NO_PLATFORM_TABLE)
    dashboard_raw = platform_raw.get("dashboard")
    if not isinstance(dashboard_raw, dict):
        raise ConfigurationError(_Msg.DASHBOARD_MUST_BE_TABLE)
    preference = _parse_preference(platform_raw)
    dashboard = _parse_dashboard(cast("dict[str, Any]", dashboard_raw), dashboard_dir, engine_dir)
    return preference, dashboard


def _load_agents_apps(
    config_dir: Path,
    sources: list[ConfigurationSource],
    *,
    root: Path,
    roles: frozenset[str],
) -> tuple[tuple[AgentProfile, ...], tuple[AppConfig, ...]]:
    """加载 agents.toml 与 apps.toml，解析 Agent 档案与应用路由。"""
    agents_data, agents_source = read_toml_snapshot(config_dir / "agents.toml")
    apps_data, apps_source = read_toml_snapshot(config_dir / "apps.toml")
    sources.extend((agents_source, apps_source))
    agents = _parse_agents(agents_data, roles)
    _require_keys(apps_data, {"app"}, "apps.toml")
    apps = _parse_apps(apps_data["app"], root)
    return agents, apps


# -- 组装入口 -----------------------------------------------------------


def load_configuration(root: Path, profile: str | None = None) -> AuroraConfig:
    """加载选定的 RFC 0002 配置快照：读取 TOML → 合并 profile → 校验并组装。"""
    root = root.resolve()
    config_dir = root / "config"
    sources: list[ConfigurationSource] = []

    runtime = _load_runtime_config(config_dir, sources, profile)
    engine_raw = _load_engine_raw(config_dir, sources)
    model_definitions, model_providers, model_logging = _load_models(config_dir, sources)
    roles = frozenset(model_definitions)
    storage_snapshot = _load_storage(root, config_dir, sources)
    preference, dashboard = _load_platforms(
        config_dir,
        sources,
        dashboard_dir=storage_snapshot.dashboard_dir,
        engine_dir=storage_snapshot.engine_dir,
    )
    agents, apps = _load_agents_apps(config_dir, sources, root=root, roles=roles)
    prompts = load_prompts(config_dir, sources, frozenset(agent.id for agent in agents))

    # 解析运行时子配置
    autonomy_raw = engine_raw.get("autonomy", {})
    agents_raw = engine_raw.get("agents", {})
    triage_raw = engine_raw.get("triage", {})
    interactive_raw = engine_raw.get("interactive_task", {})
    autonomous_raw = engine_raw.get("autonomous_task", {})
    if not all(
        isinstance(item, dict) for item in (autonomy_raw, agents_raw, triage_raw, interactive_raw, autonomous_raw)
    ):
        raise ConfigurationError(_Msg.ENGINE_SUB_MUST_BE_TABLES)

    # 解析子配置
    autonomy = _parse_autonomy(autonomy_raw)
    agent_runtime = _parse_agent_runtime(agents_raw)
    triage = _parse_triage(triage_raw)
    if triage.model_role not in roles:
        raise ConfigurationError(_Msg.TRIAGE_UNKNOWN_ROLE.format(model_role=triage.model_role))
    if agent_runtime.root_profile not in {agent.id for agent in agents}:
        raise ConfigurationError(_Msg.ROOT_PROFILE_NOT_CONFIGURED)
    if agent_runtime.worker_profile not in {agent.id for agent in agents}:
        raise ConfigurationError(_Msg.WORKER_PROFILE_NOT_CONFIGURED)
    interactive_budget = _parse_task_budget(interactive_raw, 8, 6, 300.0, "interactive_task")
    autonomous_budget = _parse_task_budget(autonomous_raw, 3, 2, 120.0, "autonomous_task")

    # 验证工作区
    workspace = (root / _string(engine_raw["workspace"], "engine.workspace")).resolve()
    if workspace != storage_snapshot.engine_dir:
        raise ConfigurationError(_Msg.WORKSPACE_MISMATCH)

    return AuroraConfig(
        root=root,
        sources=tuple(sources),
        runtime=runtime,
        engine=EngineConfig(
            workspace=workspace,
            autonomy=autonomy,
            agents=agent_runtime,
            triage=triage,
            interactive_budget=interactive_budget,
            autonomous_budget=autonomous_budget,
        ),
        dashboard=dashboard,
        preference=preference,
        logging_level=storage_snapshot.level,
        logging_dir=storage_snapshot.log_dir,
        storage=storage_snapshot.storage,
        prompts=prompts,
        agents=agents,
        model_roles=roles,
        model_definitions=MappingProxyType(model_definitions),
        model_providers=MappingProxyType(model_providers),
        model_logging=model_logging,
        apps=apps,
    )
