"""可选 MCP 客户端插件；安装 aurora-adapter[mcp] 后由宿主显式启用。"""

from aurora_config import ConfigSpec, ConfigTemplate, config_entries
from aurora_core import entry_from
from aurora_core.ctx import StateKey
from aurora_core.discovery import Plugin
from aurora_core.json_data import encode_json
from aurora_core.registry import RegistryEntry

from .clients import MCPClients
from .configuration import CLIENT_STATUS, CONFIG_STATE, CONFIGURATION, MCP_CONFIG, PROTOCOL_VERSION
from .errors import MCPClientError

__all__ = [
    "CLIENT_STATUS",
    "CONFIGURATION",
    "CONFIG_STATE",
    "PROTOCOL_VERSION",
    "MCPClientError",
    "MCPClients",
    "plugin",
]


def _validate_status(value: object) -> None:
    encode_json(value)


def plugin() -> Plugin:
    """只登记非持久配置、观察状态和生命周期声明，不解析凭证或访问网络。"""
    return Plugin(
        "aurora_adapter.mcp",
        (
            *config_entries(
                CONFIGURATION,
                ConfigSpec(
                    CONFIG_STATE,
                    ConfigTemplate("aurora_adapter", "config.tomls/mcp.toml"),
                    MCP_CONFIG,
                ),
                provider="aurora_adapter.mcp",
            ),
            RegistryEntry(
                CLIENT_STATUS,
                "state_key",
                StateKey(_validate_status, persistent=False),
                "aurora_adapter.mcp",
            ),
            *(
                entry_from(method, provider="aurora_adapter.mcp")
                for method in (
                    MCPClients.configure,
                    MCPClients.prepare,
                    MCPClients.stop,
                    MCPClients.clean,
                )
            ),
        ),
        requires=("aurora_config",),
    )
