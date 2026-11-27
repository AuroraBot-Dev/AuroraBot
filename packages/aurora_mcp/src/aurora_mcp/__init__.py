"""可选 MCP 客户端插件；安装 aurora-mcp 后由宿主显式启用。"""

from aurora_config import ConfigSpec, ConfigTemplate
from aurora_core.ctx import StateKey
from aurora_core.discovery import Plugin
from aurora_core.json_data import encode_json

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


def _create(*, ctx, hooks, instance_id, workspace_root, resolve_credential):
    return MCPClients(
        ctx, hooks, instance_id=instance_id, workspace_root=workspace_root, resolve_env=resolve_credential
    )


def plugin() -> Plugin:
    from aurora_core.components import ComponentFactory, InstanceExport

    from .plugins.clients._meta import CLEAN, CONFIGURE, PREPARE, STOP, clients_plugin

    return clients_plugin(
        targets={
            CONFIGURATION: ConfigSpec(CONFIG_STATE, ConfigTemplate("aurora_mcp"), MCP_CONFIG),
            CONFIG_STATE: StateKey(MCP_CONFIG.validate, persistent=False),
            CLIENT_STATUS: StateKey(_validate_status, persistent=False),
        },
        components={
            "clients": ComponentFactory(
                _create,
                lambda instance: InstanceExport(
                    plugs={
                        CONFIGURE: instance.configure,
                        PREPARE: instance.prepare,
                        STOP: instance.stop,
                        CLEAN: instance.clean,
                    },
                    resources={"clients": instance},
                    stop_accepting=instance.stop_accepting,
                ),
                plugs=(MCPClients.configure, MCPClients.prepare, MCPClients.stop, MCPClients.clean),
            )
        },
    )
