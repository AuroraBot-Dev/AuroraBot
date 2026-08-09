from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

_REPOSITORY_ROOT = Path(__file__).parents[1].resolve()
_REPOSITORY_DATA = (_REPOSITORY_ROOT / "data").resolve()
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
_PATH_MUTATION_EVENTS = frozenset(
    {
        "os.chmod",
        "os.link",
        "os.mkdir",
        "os.remove",
        "os.rename",
        "os.rmdir",
        "os.symlink",
        "os.truncate",
    }
)


def _audit_path(value: object) -> Path | None:
    if not isinstance(value, (str, bytes, os.PathLike)):
        return None
    raw = os.fsdecode(value)
    if raw.startswith("file:"):
        raw = raw.removeprefix("file:").partition("?")[0]
    try:
        return Path(raw).resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def _targets_repository_data(values: tuple[Any, ...]) -> bool:
    return any(path is not None and path.is_relative_to(_REPOSITORY_DATA) for path in map(_audit_path, values))


def _deny_repository_data_access(event: str, arguments: tuple[Any, ...]) -> None:
    paths: tuple[Any, ...] = ()
    if event == "sqlite3.connect":
        paths = arguments[:1]
    elif event == "open":
        path, mode, flags = arguments
        writing = (isinstance(mode, str) and any(marker in mode for marker in "wax+")) or (
            isinstance(flags, int) and bool(flags & _WRITE_FLAGS)
        )
        if writing:
            paths = (path,)
    elif event in _PATH_MUTATION_EVENTS:
        paths = arguments[:2] if event in {"os.link", "os.rename", "os.symlink"} else arguments[:1]
    if paths and _targets_repository_data(paths):
        raise RuntimeError(f"tests must not access repository runtime data: {_REPOSITORY_DATA}")


sys.addaudithook(_deny_repository_data_access)


def _copy_configuration(root: Path) -> None:
    destination = root / "config"
    if not destination.exists():
        shutil.copytree(_REPOSITORY_ROOT / "config", destination)


@pytest.fixture(autouse=True)
def isolated_test_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Run every test from a disposable project root with its own data paths."""
    monkeypatch.delenv("AURORA_PROFILE", raising=False)
    _copy_configuration(tmp_path)
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def project_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Return an isolated project root using the current split configuration."""
    monkeypatch.delenv("AURORA_PROFILE", raising=False)
    _copy_configuration(tmp_path)
    return tmp_path
