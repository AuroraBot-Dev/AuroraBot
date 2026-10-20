"""注册并解析 ``config/tags.toml`` 的命名标签集合。"""

from __future__ import annotations

from aurora.contracts.config import ConfigSpec, TableArrayShape, strings_field, text_field
from aurorabot.contracts.identity import TagDefinition, TagsConfig

CONFIG_SPEC = ConfigSpec[TagsConfig](
    name="tags",
    path="config/tags.toml",
    shape=TableArrayShape(
        path=("tag",),
        fields=(
            text_field("name"),
            strings_field("values"),
        ),
        model=TagDefinition,
        container=TagsConfig,
    ),
)
