"""WorldJournal 的逐版本迁移目录。"""

from __future__ import annotations

from collections.abc import Callable

TARGET_VERSION = 1
MigrationStep = Callable[..., None]
STEPS: dict[int, MigrationStep] = {}
