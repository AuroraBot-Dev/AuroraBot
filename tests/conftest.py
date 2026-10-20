"""从发布模板创建隔离配置，并强制 LiteLLM 使用本地费用表以保持离线。"""

from __future__ import annotations

import os
import shutil
from typing import TYPE_CHECKING

import pytest

from tests import PROJECT_ROOT

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"


@pytest.fixture
def configured_project(tmp_path: Path) -> Iterator[Path]:
    shutil.copytree(PROJECT_ROOT / "config.example", tmp_path / "config")
    yield tmp_path
