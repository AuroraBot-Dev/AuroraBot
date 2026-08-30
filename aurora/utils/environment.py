"""加载项目级本地环境变量。"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from dotenv import load_dotenv

if TYPE_CHECKING:
    from pathlib import Path

# 禁止 LiteLLM 在导入时从 GitHub 拉取远程费用表，始终使用随包本地备份
LITELLM_LOCAL_MODEL_COST_MAP = "LITELLM_LOCAL_MODEL_COST_MAP"


def load_project_env(project_root: Path) -> bool:
    """读取项目根目录的 ``.env``，但不覆盖已有进程环境变量。"""
    os.environ[LITELLM_LOCAL_MODEL_COST_MAP] = "True"
    return load_dotenv(project_root / ".env", override=False)
