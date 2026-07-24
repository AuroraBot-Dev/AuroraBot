from __future__ import annotations

import shutil
from pathlib import Path

import pytest


@pytest.fixture
def project_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Return an isolated project root using the current split configuration."""
    monkeypatch.delenv("AURORA_PROFILE", raising=False)
    source = Path(__file__).parents[1] / "config"
    shutil.copytree(source, tmp_path / "config")
    return tmp_path
