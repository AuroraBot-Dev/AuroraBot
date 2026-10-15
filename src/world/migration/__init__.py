"""WorldJournal 的逐版本迁移目录：`STEPS[current]` 把版本 `current` 推进到 `current + 1`。"""

from __future__ import annotations

from collections.abc import Callable

from src.world.migration.v1 import apply as apply_v1

TARGET_VERSION = 2
MigrationStep = Callable[..., None]
STEPS: dict[int, MigrationStep] = {1: apply_v1}
