"""AuroraBot 项目层的公共值对象与契约。

配置契约位于 ``aurora_cli.contracts.config``，命令契约位于 ``aurora_cli.contracts.command``；
消费方可直接从对应子模块导入，无需经本入口中转。
"""

from __future__ import annotations

from aurora_cli.contracts.command import CommandBinding, CommandRegistry, CommandSpec, SubcommandSpec
from aurora_cli.contracts.config import (
    AuroraConfig,
    ConfigSource,
    ConfigSpec,
    Field,
    FieldKind,
    TableArrayShape,
    TableShape,
    boolean_field,
    optional_table_field,
    optional_text_field,
    positive_integer_field,
    positive_number_field,
    strings_field,
    text_field,
)

__all__ = [
    "AuroraConfig",
    "CommandBinding",
    "CommandRegistry",
    "CommandSpec",
    "ConfigSource",
    "ConfigSpec",
    "Field",
    "FieldKind",
    "SubcommandSpec",
    "TableArrayShape",
    "TableShape",
    "boolean_field",
    "optional_table_field",
    "optional_text_field",
    "positive_integer_field",
    "positive_number_field",
    "strings_field",
    "text_field",
]
