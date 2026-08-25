"""共享测试配置；配置测试从发布模板创建隔离的个人目录。"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

# 测试必须离线：禁止 LiteLLM 在导入时拉取远程费用表
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"

_ROOT = Path(__file__).parents[1]


@pytest.fixture
def configured_project(tmp_path: Path) -> Iterator[Path]:
    shutil.copytree(_ROOT / "config.example", tmp_path / "config")
    yield tmp_path
