"""``src.mcp`` 的配置形状。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from src.contracts.identity import PLATFORM_PATH_PREFIX, matches_species
from src.mcp.scopes import owns_scope, validate_mcp_scope
from src.utils.validation import (
    check_environment_name,
    check_https_url,
    check_non_empty_text_array,
    check_package_name,
    check_positive_number,
    check_relative_directory,
    check_unique_items,
)

type McpTransport = Literal["stdio", "streamable_http"]
type McpEventMode = Literal["disabled", "world_events", "legacy_aurora_event"]

_TRANSPORTS = frozenset({"stdio", "streamable_http"})
_EVENT_MODES = frozenset({"disabled", "world_events", "legacy_aurora_event"})
_PLATFORM_IDS = frozenset({"aurora:platform/console", "aurora:platform/mcp"})


@dataclass(frozen=True, slots=True)
class AppConfig:
    """一个 MCP Server 的纯配置定义。"""

    package: str
    enabled: bool
    transport: McpTransport
    event_mode: McpEventMode
    timeout_seconds: float
    working_dir: str | None = None
    command: tuple[str, ...] = ()
    env: tuple[str, ...] = ()
    url: str | None = None
    auth_env: str | None = None
    scopes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        check_package_name(self.package, "app.package")
        if self.transport not in _TRANSPORTS:
            raise ValueError("app.transport 必须是 stdio 或 streamable_http")
        if self.event_mode not in _EVENT_MODES:
            raise ValueError("app.event_mode 不受支持")
        check_positive_number(self.timeout_seconds, "timeout_seconds")
        self._validate_owned_scopes()
        if self.transport == "stdio":
            self._validate_stdio()
        else:
            self._validate_http()

    def _validate_owned_scopes(self) -> None:
        """扩展只能声明自己命名空间下的域：命名空间即所有权。"""
        object.__setattr__(self, "scopes", tuple(self.scopes))
        check_unique_items(self.scopes, "app.scopes")
        for scope in self.scopes:
            validate_mcp_scope(scope)
            if not owns_scope(self.package, scope):
                raise ValueError(f"app.scopes 只能声明自己命名空间下的域：{scope} 不属于 {self.package}")

    def _validate_stdio(self) -> None:
        if self.working_dir is None:
            raise ValueError("stdio app 必须声明 working_dir")
        check_relative_directory(self.working_dir, "app.working_dir")
        check_non_empty_text_array(self.command, "app.command")
        _validate_environment_names(self.env, "app.env")
        if self.url is not None or self.auth_env is not None:
            raise ValueError("stdio app 不得声明 url 或 auth_env")

    def _validate_http(self) -> None:
        if self.working_dir is not None or self.command or self.env:
            raise ValueError("streamable_http app 不得声明 working_dir、command 或 env")
        if self.url is None:
            raise ValueError("streamable_http app 必须声明 HTTPS url")
        check_https_url(self.url, "app.url")
        if self.event_mode == "world_events":
            raise ValueError("streamable_http app 暂不支持 world_events")
        if self.auth_env is not None:
            _validate_environment_names((self.auth_env,), "app.auth_env")


@dataclass(frozen=True, slots=True)
class AppsConfig:
    """``apps.toml`` 的全部 MCP App。"""

    apps: tuple[AppConfig, ...]


@dataclass(frozen=True, slots=True)
class PlatformConfig:
    """一个可拓展的平台声明。"""

    id: str
    enabled: bool
    logging: str | None = None
    config: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not matches_species(self.id, PLATFORM_PATH_PREFIX):
            raise ValueError(f"platform.id 必须是平台命名空间下的 ID：{self.id}")
        if self.id not in _PLATFORM_IDS:
            raise ValueError(f"未知平台 id：{self.id}")
        normalized = self.logging or "INFO"
        if normalized not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL", "NONE"}:
            raise ValueError("platform.logging 必须是日志级别或 NONE")
        object.__setattr__(self, "logging", normalized)

    def settings(self, key: str, default: object = None) -> object:
        return self.config.get(key, default)


@dataclass(frozen=True, slots=True)
class PlatformsConfig:
    """``platforms.toml`` 的全部平台声明。"""

    platforms: tuple[PlatformConfig, ...]


def _validate_environment_names(values: tuple[str, ...], label: str) -> None:
    check_unique_items(values, label)
    for item in values:
        check_environment_name(item, label)
