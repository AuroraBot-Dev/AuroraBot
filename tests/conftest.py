from __future__ import annotations

import shutil
from pathlib import Path

import pytest


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    source = Path(__file__).parents[1]
    shutil.copytree(source / "config", tmp_path / "config")
    shutil.copy2(source / "SOUL.md", tmp_path / "SOUL.md")
    return tmp_path
