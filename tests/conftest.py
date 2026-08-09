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
_GUARDED_EVENTS = frozenset(
    {
        "open",
        "os.chmod",
        "os.link",
        "os.mkdir",
        "os.remove",
        "os.rename",
        "os.rmdir",
        "os.symlink",
        "os.truncate",
        "sqlite3.connect",
    }
)


def _audit_path(value: object, dir_fd: object = None) -> Path | None:
    if not isinstance(value, (str, bytes, os.PathLike)):
        return None
    raw = os.fsdecode(value)
    if raw.startswith("file:"):
        raw = raw.removeprefix("file:").partition("?")[0]
    try:
        path = Path(raw)
        if not path.is_absolute() and isinstance(dir_fd, int) and dir_fd >= 0:
            path = Path(f"/proc/self/fd/{dir_fd}").readlink() / path
        return path.resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def _targets_repository_data(values: tuple[tuple[Any, object], ...]) -> bool:
    paths = (_audit_path(value, dir_fd) for value, dir_fd in values)
    return any(path is not None and path.is_relative_to(_REPOSITORY_DATA) for path in paths)


def _event_paths(event: str, arguments: tuple[Any, ...]) -> tuple[tuple[Any, object], ...]:  # noqa: PLR0911
    if event == "sqlite3.connect":
        return ((arguments[0], None),)
    if event == "open":
        path, mode, flags = arguments
        writing = (isinstance(mode, str) and any(marker in mode for marker in "wax+")) or (
            isinstance(flags, int) and bool(flags & _WRITE_FLAGS)
        )
        return ((path, None),) if writing else ()
    dir_fd_index = {"os.remove": 1, "os.rmdir": 1, "os.mkdir": 2, "os.chmod": 2}.get(event)
    if dir_fd_index is not None:
        return ((arguments[0], arguments[dir_fd_index]),)
    if event == "os.truncate":
        return ((arguments[0], None),)
    if event in {"os.link", "os.rename"}:
        return ((arguments[0], arguments[2]), (arguments[1], arguments[3]))
    if event == "os.symlink":
        return ((arguments[1], arguments[2]),)
    return ()


def _deny_repository_data_access(event: str, arguments: tuple[Any, ...]) -> None:
    if event not in _GUARDED_EVENTS:
        return
    paths = _event_paths(event, arguments)
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
