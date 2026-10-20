"""解析资源内容存储配置。"""

from __future__ import annotations

from aurora.contracts.config import ConfigSpec, TableShape, text_field
from aurorabot.artifacts.config import ArtifactsConfig

CONFIG_SPEC = ConfigSpec[ArtifactsConfig](
    name="artifacts",
    path="config/artifacts.toml",
    shape=TableShape(path=("artifacts",), fields=(text_field("directory"),), model=ArtifactsConfig),
)
