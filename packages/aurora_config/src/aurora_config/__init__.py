"""配置声明、通用校验和 config 阶段服务。"""

from ._meta import CONFIGS, CONFIGURATION
from .assembly import configuration_component
from .declarations import ConfigSpec, config_entries
from .files import load_configuration
from .schema import ConfigSchema
from .service import plugin
from .templates import ConfigTemplate, copy_missing, read_toml

__all__ = [
    "CONFIGS",
    "CONFIGURATION",
    "ConfigSchema",
    "ConfigSpec",
    "ConfigTemplate",
    "config_entries",
    "configuration_component",
    "copy_missing",
    "load_configuration",
    "plugin",
    "read_toml",
]
