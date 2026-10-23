from pathlib import Path

from aurora_cli.plugins import config_plugin

from .engine import CONFIG_SPEC

MODULE = config_plugin("aurora.cli.configs.engine", CONFIG_SPEC, Path(__file__).parent)

__all__ = ["CONFIG_SPEC", "MODULE"]
