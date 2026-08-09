"""不可变配置 DTO 与基础校验工具。

不含 I/O、TOML 解析或文件读取 —— 这些由 ``src.config`` 提供。
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from src.contracts.agent import AgentLimits, AgentProfile, TaskLimits
    from src.contracts.triage import TriageLimits


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


# ---------------------------------------------------------------------------
# 配置 DTO
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ConsoleConfig:
    """本地 Console 交互前端配置。

    ConsoleConfig object::

        {
            "enabled": true,
            "terminal_logs": false
        }

    """

    enabled: bool
    terminal_logs: bool


@dataclass(frozen=True, slots=True)
class PanelConfig:
    """面板后端配置：唯一 HTTP 端口、认证与前端白名单。

    PanelConfig object::

        {
            "enabled": true,
            "host": "string",
            "port": 0,
            "allowed_origins": ["string", ...],
            "open_browser": false,
            "session_ttl_seconds": 0,
            "max_upload_bytes": 0
        }

    """

    enabled: bool
    host: str
    port: int
    allowed_origins: tuple[str, ...]
    open_browser: bool
    session_ttl_seconds: int
    max_upload_bytes: int


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    """进程运行时配置：profile、面板后端与本地 Console 前端。

    RuntimeConfig object::

        {
            "profile": "string",
            "panel": PanelConfig,
            "console": ConsoleConfig
        }

    """

    profile: str
    panel: "PanelConfig"
    console: "ConsoleConfig"


@dataclass(frozen=True, slots=True)
class EngineConfig:
    """engine 工作区、调度限制、节律与 Task 预算。"""

    workspace: Path
    autonomy: "AutonomyConfig"
    agents: "AgentLimits"
    triage: "TriageLimits"
    interactive_budget: "TaskLimits"
    autonomous_budget: "TaskLimits"


@dataclass(frozen=True, slots=True)
class AutonomyConfig:
    """自主节律配置：扫描间隔、心跳边界和每日额度。

    AutonomyConfig object::

        {
            "scan_seconds": 1.0,
            "heartbeat_initial_seconds": 30.0,
            "heartbeat_min_seconds": 30.0,
            "heartbeat_max_seconds": 1800.0
        }

    """

    scan_seconds: float = 1.0
    heartbeat_initial_seconds: float = 30.0
    heartbeat_min_seconds: float = 30.0
    heartbeat_max_seconds: float = 1800.0


@dataclass(frozen=True, slots=True)
class PromptConfig:
    """启动时加载的不可变提示词内容及来源。"""

    soul: str
    world: str
    agents: Mapping[str, str]
    sources: tuple[ConfigurationSource, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "agents", MappingProxyType(dict(self.agents)))
        object.__setattr__(self, "sources", tuple(self.sources))


@dataclass(frozen=True, slots=True)
class AppConfig:
    """一个显式启用的 MCP 应用路由配置。

    AppConfig object::

        {
            "package": "string",
            "transport": "string",
            "working_dir": "/path/to/dir" | null,
            "command": ["string", ...],
            "env_vars": ["ENV_VAR_NAME", ...],
            "url": "string" | null,
            "auth_env": "string" | null,
            "timeout_seconds": 0.0
        }

    """

    package: str
    transport: str
    working_dir: Path | None
    command: tuple[str, ...]
    env_vars: tuple[str, ...]
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
            "capabilities": ["string", ...]
        }

    """

    provider: str
    model: str
    capabilities: frozenset[str] = frozenset()


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
            "mcp": McpPreference
        }

    """

    mcp: McpPreference


PLATFORM_NAMES: frozenset[str] = frozenset(f.name for f in fields(PlatformPreference))
"""所有已知平台标识符，由 PlatformPreference 的字段名派生。"""


@dataclass(frozen=True, slots=True)
class StorageConfig:
    """各实现包的私有持久化目录；路径层级与包层级一致。

    StorageConfig object::

        {
            "data_root": "/path/to/data",
            "engine": "/path/to/data/engine",
            "ai": "/path/to/data/ai",
            "memory": "/path/to/data/memory",
            "platform": "/path/to/data/platform",
            "ops": "/path/to/data/ops",
            "mcp": "/path/to/data/platform/mcp",
            "apps": "/path/to/data/platform/mcp/apps"
        }

    """

    data_root: Path
    engine: Path
    ai: Path
    memory: Path
    platform: Path
    ops: Path
    mcp: Path
    apps: Path


@dataclass(frozen=True, slots=True)
class AuroraConfig:
    """聚合所有 TOML 配置的根配置对象。

    AuroraConfig object::

        {
            "root": "/path/to/root",
            "sources": [ConfigurationSource, ...],
            "runtime": RuntimeConfig,
            "engine": EngineConfig,
            "preference": PlatformPreference,
            "logging_level": "string",
            "storage": StorageConfig,
            "prompts": PromptConfig,
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
    engine: EngineConfig
    preference: PlatformPreference
    logging_level: str
    logging_dir: Path
    storage: StorageConfig
    prompts: PromptConfig
    agents: "tuple[AgentProfile, ...]"
    model_roles: frozenset[str]
    model_definitions: Mapping[str, ModelRoleConfig] = MappingProxyType({})
    model_providers: Mapping[str, ModelProviderConfig] = MappingProxyType({})
    model_logging: ModelLoggingConfig = ModelLoggingConfig(log_queries=False, log_responses=False)
    apps: tuple[AppConfig, ...] = ()
