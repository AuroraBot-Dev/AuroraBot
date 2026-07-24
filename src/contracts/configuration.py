"""不可变配置 DTO 与基础校验工具。

不含 I/O、TOML 解析或文件读取 —— 这些由 ``src.config`` 提供。
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

    from src.contracts.agent import AgentLimits, AgentProfile, TaskBudget


class ConfigurationError(ValueError):
    """启动前因无效结构性配置抛出。"""


@dataclass(frozen=True, slots=True)
class ConfigurationSource:
    """可审计的配置来源：记录文件路径和 SHA-256 摘要。

    ConfigurationSource object::

        {
            "path": "/path/to/file",
            "sha256": "hex-digest"
        }

    """

    path: Path
    sha256: str


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


def _positive_number(value: object, label: str) -> float:
    """校验值为正数（int 或 float），返回 float。"""
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        raise ConfigurationError(f"{label} must be positive")
    return float(value)


# ---------------------------------------------------------------------------
# 配置 DTO
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    """运行时配置：profile、工作区、调试、自主、Agent 限制和预算。

    RuntimeConfig object::

        {
            "profile": "string",
            "workspace": "/path/to/workspace",
            "debug_host": "string",
            "debug_port": 0,
            "autonomy": AutonomyConfig,
            "agents": AgentLimits,
            "interactive_budget": TaskBudget,
            "autonomous_budget": TaskBudget
        }

    """

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
    """自主节律配置：扫描间隔、心跳边界和每日额度。

    AutonomyConfig object::

        {
            "scan_seconds": 1.0,
            "heartbeat_initial_seconds": 30.0,
            "heartbeat_min_seconds": 30.0,
            "heartbeat_max_seconds": 1800.0,
            "autonomous_daily_model_calls": 24,
            "autonomous_daily_tokens": 100000
        }

    """

    scan_seconds: float = 1.0
    heartbeat_initial_seconds: float = 30.0
    heartbeat_min_seconds: float = 30.0
    heartbeat_max_seconds: float = 1800.0
    autonomous_daily_model_calls: int = 24
    autonomous_daily_tokens: int = 100_000


@dataclass(frozen=True, slots=True)
class DashboardBotConfig:
    """Dashboard Bot 身份配置。

    DashboardBotConfig object::

        {
            "username": "string",
            "display_name": "string",
            "avatar_url": "string" | null
        }

    """

    username: str
    display_name: str
    avatar_url: str | None


@dataclass(frozen=True, slots=True)
class DashboardConfig:
    """Dashboard 服务配置。

    DashboardConfig object::

        {
            "host": "string",
            "port": 0,
            "database_path": "/path/to/db",
            "upload_dir": "/path/to/uploads",
            "max_upload_bytes": 0,
            "session_ttl_seconds": 0,
            "allowed_origins": ["string", ...],
            "owner_username": "string",
            "bot": DashboardBotConfig
        }

    """

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
    """一个显式启用的 MCP 应用路由配置。

    AppConfig object::

        {
            "package": "string",
            "transport": "string",
            "working_dir": "/path/to/dir" | null,
            "command": ["string", ...],
            "url": "string" | null,
            "auth_env": "string" | null,
            "timeout_seconds": 0.0
        }

    """

    package: str
    transport: str
    working_dir: Path | None
    command: tuple[str, ...]
    url: str | None
    auth_env: str | None
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class ModelProviderConfig:
    """TOML 定义的 LiteLLM 或 OpenAI 兼容 Provider 路由。

    ModelProviderConfig object::

        {
            "id": "string",
            "adapter": "string",
            "secret_env": "ENV_VAR_NAME",
            "base_url": "string" | null
        }

    """

    id: str
    adapter: str
    secret_env: str
    base_url: str | None


@dataclass(frozen=True, slots=True)
class ModelRoleConfig:
    """模型角色的非密钥配置，capabilities 为空时由 models.dev 自动派生。

    ModelRoleConfig object::

        {
            "provider": "string",
            "model": "string",
            "capabilities": ["string", ...],
            "endpoint": "chat_completions"
        }

    """

    provider: str
    model: str
    capabilities: frozenset[str] = frozenset()
    endpoint: str = "chat_completions"


@dataclass(frozen=True, slots=True)
class ModelLoggingConfig:
    """模型网关的可选 DEBUG 日志控制。

    ModelLoggingConfig object::

        {
            "log_queries": false,
            "log_responses": false
        }

    """

    log_queries: bool
    log_responses: bool


@dataclass(frozen=True, slots=True)
class ConsolePreference:
    """Console 平台偏好。

    ConsolePreference object::

        {
            "enabled": false,
            "terminal_logs": false
        }

    """

    enabled: bool
    terminal_logs: bool


@dataclass(frozen=True, slots=True)
class DashboardPreference:
    """Dashboard 平台偏好。

    DashboardPreference object::

        {
            "enabled": false,
            "open_browser": false
        }

    """

    enabled: bool
    open_browser: bool


@dataclass(frozen=True, slots=True)
class McpPreference:
    """MCP 平台偏好。

    McpPreference object::

        {
            "enabled": false,
            "terminal_logs": false
        }

    """

    enabled: bool
    terminal_logs: bool


@dataclass(frozen=True, slots=True)
class PlatformPreference:
    """平台组合偏好。

    PlatformPreference object::

        {
            "console": ConsolePreference,
            "dashboard": DashboardPreference,
            "mcp": McpPreference
        }

    """

    console: ConsolePreference
    dashboard: DashboardPreference
    mcp: McpPreference


PLATFORM_NAMES: frozenset[str] = frozenset(f.name for f in fields(PlatformPreference))
"""所有已知平台标识符，由 PlatformPreference 的字段名派生。"""


@dataclass(frozen=True, slots=True)
class AuroraConfig:
    """聚合所有 TOML 配置的根配置对象。

    AuroraConfig object::

        {
            "root": "/path/to/root",
            "sources": [ConfigurationSource, ...],
            "runtime": RuntimeConfig,
            "dashboard": DashboardConfig,
            "preference": PlatformPreference,
            "logging_level": "string",
            "storage_data_dir": "/path/to/data",
            "agents": [AgentProfile, ...],
            "model_roles": ["string", ...],
            "model_definitions": {"role": ModelRoleConfig, ...},
            "model_providers": {"provider": ModelProviderConfig, ...},
            "model_logging": ModelLoggingConfig,
            "apps": [AppConfig, ...]
        }

    """

    root: Path
    sources: tuple[ConfigurationSource, ...]
    runtime: RuntimeConfig
    dashboard: DashboardConfig
    preference: PlatformPreference
    logging_level: str
    storage_data_dir: Path
    agents: "tuple[AgentProfile, ...]"
    model_roles: frozenset[str]
    model_definitions: Mapping[str, ModelRoleConfig] = MappingProxyType({})
    model_providers: Mapping[str, ModelProviderConfig] = MappingProxyType({})
    model_logging: ModelLoggingConfig = ModelLoggingConfig(log_queries=False, log_responses=False)
    apps: tuple[AppConfig, ...] = ()
