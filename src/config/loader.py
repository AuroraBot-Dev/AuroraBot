"""TOML 配置加载与校验 —— 读取所有 config/ 文件并组装为不可变 AuroraConfig。"""

from __future__ import annotations

import copy
import hashlib
import os
import tomllib
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

from src.config.sections import (
    _parse_agent_runtime,
    _parse_agents,
    _parse_apps,
    _parse_autonomy,
    _parse_dashboard,
    _parse_preference,
    _parse_task_budget,
)
from src.contracts.configuration import (
    AuroraConfig,
    ConfigurationError,
    ConfigurationSource,
    EngineConfig,
    ModelLoggingConfig,
    ModelProviderConfig,
    ModelRoleConfig,
    RuntimeConfig,
    StorageConfig,
    _require_keys,
    _string,
)


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


def load_configuration(root: Path, profile: str | None = None) -> AuroraConfig:
    """加载选定的 RFC 0002 配置快照：读取 TOML → 合并 profile → 校验并组装。"""
    root = root.resolve()
    config_dir = root / "config"
    sources: list[ConfigurationSource] = []

    # 加载运行时配置
    runtime_data, runtime_source = _read_toml_snapshot(config_dir / "runtime.toml")
    sources.append(runtime_source)
    _require_keys(runtime_data, {"runtime"}, "runtime.toml")
    runtime_raw = runtime_data.get("runtime", {})
    if not isinstance(runtime_raw, dict):
        raise ConfigurationError("runtime must be a table")

    # 确定profile
    selected_profile = profile or os.environ.get("AURORA_PROFILE") or runtime_raw.get("profile")
    if not isinstance(selected_profile, str) or not selected_profile:
        raise ConfigurationError("no profile selected")

    # 合并profile覆盖
    profile_path = config_dir / "profiles" / f"{selected_profile}.toml"
    if not profile_path.exists():
        raise ConfigurationError(f"profile does not exist: {selected_profile}")
    profile_data, profile_source = _read_toml_snapshot(profile_path)
    _require_keys(profile_data, {"runtime"}, "profile")
    merged_runtime = _merge(runtime_data, profile_data)
    sources.append(profile_source)

    runtime_raw = merged_runtime.get("runtime", {})
    if not isinstance(runtime_raw, dict):
        raise ConfigurationError("runtime must be a table")

    # 验证运行时配置
    runtime_allowed = {"profile", "debug_host", "debug_port"}
    required_runtime = set(runtime_allowed)
    if set(runtime_raw) - runtime_allowed or not required_runtime <= set(runtime_raw):
        raise ConfigurationError("runtime has unsupported or missing keys")

    # 加载 engine 配置，profile 不得覆盖此文件
    engine_data, engine_source = _read_toml_snapshot(config_dir / "engine.toml")
    sources.append(engine_source)
    _require_keys(engine_data, {"engine"}, "engine.toml")
    engine_raw = engine_data.get("engine", {})
    if not isinstance(engine_raw, dict):
        raise ConfigurationError("engine must be a table")
    engine_allowed = {"workspace", "autonomy", "agents", "interactive_task", "autonomous_task"}
    if set(engine_raw) != engine_allowed:
        raise ConfigurationError("engine has unsupported or missing keys")

    # 加载平台配置
    platforms_data, platforms_source = _read_toml_snapshot(config_dir / "platforms.toml")
    sources.append(platforms_source)
    _require_keys(platforms_data, {"platform"}, "platforms.toml")
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
    _require_keys(models_data, {"models"}, "models.toml")
    models_raw = models_data.get("models", {})
    if not isinstance(models_raw, dict):
        raise ConfigurationError("models must be a table")
    _require_keys(models_raw, {"roles", "providers", "logging"}, "models")

    # 加载日志与存储配置
    logging_data, logging_source = _read_toml_snapshot(config_dir / "logging.toml")
    storage_data, storage_source = _read_toml_snapshot(config_dir / "storage.toml")
    sources.extend((logging_source, storage_source))
    logging_raw = logging_data.get("logging", {})
    storage_raw = storage_data.get("storage", {})
    _require_keys(logging_data, {"logging"}, "logging.toml")
    _require_keys(storage_data, {"storage"}, "storage.toml")
    if not isinstance(logging_raw, dict) or not isinstance(storage_raw, dict):
        raise ConfigurationError("logging and storage must be tables")
    _require_keys(logging_raw, {"level", "log_dir"}, "logging")
    _require_keys(storage_raw, {"data_root", "engine", "ai", "memory", "apps", "platform"}, "storage")
    storage_platform_raw = storage_raw["platform"]
    if not isinstance(storage_platform_raw, dict):
        raise ConfigurationError("storage.platform must be a table")
    _require_keys(storage_platform_raw, {"console", "dashboard"}, "storage.platform")

    def storage_path(raw: object, label: str, *, parent: Path) -> Path:
        path = (parent / _string(raw, label)).resolve()
        if not path.is_relative_to(parent.resolve()):
            raise ConfigurationError(f"{label} must stay within its parent storage directory")
        return path

    data_root = storage_path(storage_raw["data_root"], "storage.data_root", parent=root)
    engine_dir = storage_path(storage_raw["engine"], "storage.engine", parent=data_root)
    ai_dir = storage_path(storage_raw["ai"], "storage.ai", parent=data_root)
    memory_dir = storage_path(storage_raw["memory"], "storage.memory", parent=data_root)
    apps_dir = storage_path(storage_raw["apps"], "storage.apps", parent=data_root)
    console_storage = storage_platform_raw["console"]
    dashboard_storage = storage_platform_raw["dashboard"]
    if not isinstance(console_storage, dict) or not isinstance(dashboard_storage, dict):
        raise ConfigurationError("storage platform entries must be tables")
    _require_keys(console_storage, {"data_dir"}, "storage.platform.console")
    _require_keys(dashboard_storage, {"data_dir"}, "storage.platform.dashboard")
    console_dir = storage_path(console_storage["data_dir"], "storage.platform.console.data_dir", parent=data_root)
    dashboard_dir = storage_path(dashboard_storage["data_dir"], "storage.platform.dashboard.data_dir", parent=data_root)
    package_directories = (engine_dir, ai_dir, memory_dir, apps_dir, console_dir, dashboard_dir)
    for index, directory in enumerate(package_directories):
        if any(
            directory == other or directory.is_relative_to(other) or other.is_relative_to(directory)
            for other in package_directories[index + 1 :]
        ):
            raise ConfigurationError("package storage directories must not overlap")

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
    autonomy_raw = engine_raw.get("autonomy", {})
    agents_raw = engine_raw.get("agents", {})
    interactive_raw = engine_raw.get("interactive_task", {})
    autonomous_raw = engine_raw.get("autonomous_task", {})
    if not all(isinstance(item, dict) for item in (autonomy_raw, agents_raw, interactive_raw, autonomous_raw)):
        raise ConfigurationError("engine autonomy, Agents and Task budgets must be tables")

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
        raise ConfigurationError("engine.agents.root_profile is not configured")
    if agent_runtime.worker_profile not in {agent.id for agent in agents}:
        raise ConfigurationError("engine.agents.worker_profile is not configured")
    interactive_budget = _parse_task_budget(interactive_raw, 8, 6, 300.0, "interactive_task")
    autonomous_budget = _parse_task_budget(autonomous_raw, 3, 2, 120.0, "autonomous_task")

    # 验证工作区
    workspace = (root / _string(engine_raw["workspace"], "engine.workspace")).resolve()
    expected_workspace = engine_dir
    if workspace != expected_workspace:
        raise ConfigurationError("engine.workspace must match storage.engine")

    return AuroraConfig(
        root=root,
        sources=tuple(sources),
        runtime=RuntimeConfig(
            profile=selected_profile,
            debug_host=debug_host,
            debug_port=debug_port,
        ),
        engine=EngineConfig(
            workspace=workspace,
            autonomy=autonomy,
            agents=agent_runtime,
            interactive_budget=interactive_budget,
            autonomous_budget=autonomous_budget,
        ),
        dashboard=_parse_dashboard(cast("dict[str, Any]", dashboard_raw), dashboard_dir, engine_dir),
        preference=preference,
        logging_level=_string(logging_raw["level"], "logging.level"),
        logging_dir=storage_path(logging_raw["log_dir"], "logging.log_dir", parent=root),
        storage=StorageConfig(
            data_root=data_root,
            engine=engine_dir,
            ai=ai_dir,
            memory=memory_dir,
            apps=apps_dir,
            console=console_dir,
            dashboard=dashboard_dir,
        ),
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
