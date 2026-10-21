from pathlib import Path

from aurora_cli.plugins import config_plugin

from .platforms import CONFIG_SPEC

MODULE = config_plugin("aurora.cli.configs.platforms", CONFIG_SPEC, Path(__file__).parent)

__all__ = ["CONFIG_SPEC", "MODULE"]
