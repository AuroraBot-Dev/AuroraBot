"""版本化迁移框架：步骤顺序、版本推进与缺失/超前版本拒绝（RFC 0217 §5）。"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

from src.utils.migration import migrate_to

if TYPE_CHECKING:
    from pathlib import Path


def _connection(tmp_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(tmp_path / "migration.sqlite3")
    connection.execute("PRAGMA user_version = 0")
    return connection


def _version(connection: sqlite3.Connection) -> int:
    return int(connection.execute("PRAGMA user_version").fetchone()[0])


_TARGET = 2


def test_migrate_to_runs_steps_in_order_and_advances_version(tmp_path: Path) -> None:
    connection = _connection(tmp_path)
    calls: list[int] = []

    def step0(conn: sqlite3.Connection) -> None:
        calls.append(0)
        conn.execute("CREATE TABLE t0 (id INTEGER)")

    def step1(conn: sqlite3.Connection) -> None:
        calls.append(1)
        conn.execute("CREATE TABLE t1 (id INTEGER)")

    migrate_to(
        connection,
        current=0,
        target=2,
        steps={0: step0, 1: step1},
        set_version=lambda c, version: c.execute(f"PRAGMA user_version = {version}"),
    )
    assert calls == [0, 1]
    assert _version(connection) == _TARGET
    assert connection.execute("SELECT name FROM sqlite_master WHERE name = 't1'").fetchone() is not None


def test_migrate_to_skips_when_current_equals_target(tmp_path: Path) -> None:
    connection = _connection(tmp_path)
    connection.execute("PRAGMA user_version = 1")
    migrate_to(
        connection,
        current=1,
        target=1,
        steps={0: lambda _conn: None},
        set_version=lambda c, version: c.execute(f"PRAGMA user_version = {version}"),
    )
    assert _version(connection) == 1


def test_migrate_to_rejects_newer_database(tmp_path: Path) -> None:
    connection = _connection(tmp_path)
    connection.execute("PRAGMA user_version = 5")
    with pytest.raises(RuntimeError, match="newer than supported"):
        migrate_to(
            connection,
            current=5,
            target=1,
            steps={0: lambda _conn: None},
            set_version=lambda c, version: c.execute(f"PRAGMA user_version = {version}"),
        )


def test_migrate_to_rejects_missing_step(tmp_path: Path) -> None:
    connection = _connection(tmp_path)
    with pytest.raises(RuntimeError, match="missing migration step"):
        migrate_to(
            connection,
            current=0,
            target=2,
            steps={0: lambda _conn: None},
            set_version=lambda c, version: c.execute(f"PRAGMA user_version = {version}"),
        )


def test_migrate_to_rolls_back_step_failure(tmp_path: Path) -> None:
    connection = _connection(tmp_path)

    def broken(conn: sqlite3.Connection) -> None:
        conn.execute("INVALID SQL")

    with pytest.raises(sqlite3.Error):
        migrate_to(
            connection,
            current=0,
            target=1,
            steps={0: broken},
            set_version=lambda c, version: c.execute(f"PRAGMA user_version = {version}"),
        )
    assert _version(connection) == 0
