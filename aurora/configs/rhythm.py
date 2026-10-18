"""解析节律模型选择与基线参数。"""

from aurora.contracts.config import (
    ConfigSpec,
    TableShape,
    optional_text_field,
    positive_integer_field,
    positive_number_field,
    text_field,
)
from src.rhythm.config import RhythmConfig

RHYTHM_CONFIG = ConfigSpec[RhythmConfig](
    name="rhythm",
    path="config/rhythm.toml",
    shape=TableShape(
        path=("rhythm",),
        fields=(
            text_field("policy"),
            optional_text_field("weights"),
            positive_integer_field("evoke_every"),
            positive_number_field("max_idle_seconds"),
            positive_number_field("min_check_seconds"),
            positive_number_field("probability_threshold"),
        ),
        model=RhythmConfig,
    ),
)

CONFIG_SPEC = RHYTHM_CONFIG
