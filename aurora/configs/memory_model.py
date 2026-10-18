"""解析记忆推荐模型的独立配置。"""

from aurora.contracts.config import ConfigSpec, TableShape, optional_text_field, text_field
from src.memory_model.config import MemoryModelConfig

MEMORY_MODEL_CONFIG = ConfigSpec[MemoryModelConfig](
    name="memory_model",
    path="config/memory_model.toml",
    shape=TableShape(
        path=("memory_model",),
        fields=(text_field("policy"), optional_text_field("weights")),
        model=MemoryModelConfig,
    ),
)

CONFIG_SPEC = MEMORY_MODEL_CONFIG
