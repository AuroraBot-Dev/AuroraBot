"""SQLite metadata store with CAS semantics."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.kernel.models import CasConflict, FileMeta, FileNotFoundError_, FileState, utcnow


def _to_text(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat()


def _from_text(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)


class SQLiteMetadataStore:
    """Metadata store used by the MVP to validate the CAS protocol."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self._conn = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._create_schema()

    def close(self) -> None:
        self._conn.close()

    def create_file(self, meta: FileMeta) -> FileMeta:
        now = utcnow()
        meta = FileMeta(
            file_id=meta.file_id,
            object_id=meta.object_id,
            version=0,
            state=meta.state,
            owner_id=meta.owner_id,
            write_holder=meta.write_holder,
            read_count=meta.read_count,
            tags=dict(meta.tags),
            parent_file_id=meta.parent_file_id,
            previous_file_id=meta.previous_file_id,
            lease_expire=meta.lease_expire,
            processing_round=meta.processing_round,
            max_rounds=meta.max_rounds,
            termination_policy=meta.termination_policy,
            created_at=now,
            updated_at=now,
            heartbeat_epoch=meta.heartbeat_epoch,
            smooth_load=meta.smooth_load,
            next_cycle_at=meta.next_cycle_at,
            retention_policy=meta.retention_policy,
        )
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO file_meta (
                    file_id, version, state, owner_id, write_holder, read_count,
                    object_id, tags, parent_file_id, previous_file_id, lease_expire,
                    processing_round, max_rounds, termination_policy,
                    created_at, updated_at, heartbeat_epoch, smooth_load,
                    next_cycle_at, retention_policy
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._to_row(meta),
            )
        return meta

    def get(self, file_id: str) -> FileMeta:
        row = self._conn.execute("SELECT * FROM file_meta WHERE file_id = ?", (file_id,)).fetchone()
        if row is None:
            raise FileNotFoundError_(file_id)
        return self._from_row(row)

    def cas_update(
        self,
        file_id: str,
        expected_version: int,
        changes: Mapping[str, Any],
        extra_where: str = "",
        extra_params: tuple[Any, ...] = (),
    ) -> FileMeta:
        if not changes:
            msg = "changes must not be empty"
            raise ValueError(msg)

        allowed = {
            "state",
            "owner_id",
            "write_holder",
            "read_count",
            "object_id",
            "tags",
            "parent_file_id",
            "previous_file_id",
            "lease_expire",
            "processing_round",
            "max_rounds",
            "termination_policy",
            "heartbeat_epoch",
            "smooth_load",
            "next_cycle_at",
            "retention_policy",
        }
        unknown = set(changes) - allowed
        if unknown:
            msg = f"unknown metadata fields: {sorted(unknown)}"
            raise ValueError(msg)

        current = self.get(file_id)
        values = dict(changes)
        values["version"] = expected_version + 1
        values["updated_at"] = utcnow()

        assignments = ", ".join(f"{field} = ?" for field in values)
        params = [self._encode_value(field, value) for field, value in values.items()]
        params.extend([file_id, expected_version])
        params.extend(extra_params)

        sql = f"UPDATE file_meta SET {assignments} WHERE file_id = ? AND version = ?"
        if extra_where:
            sql += f" AND {extra_where}"

        with self._conn:
            cursor = self._conn.execute(sql, tuple(params))
        if cursor.rowcount != 1:
            latest = self.get(file_id)
            if latest.version != current.version:
                raise CasConflict(f"CAS failed for {file_id}: expected version {expected_version}")
            raise CasConflict(f"CAS conditions failed for {file_id}")
        return self.get(file_id)

    def query_claimable(self, *, owner_id: str | None = None, tags: Mapping[str, Any] | None = None) -> list[FileMeta]:
        if owner_id is None:
            owner_clause = "owner_id IS NULL"
            params: tuple[Any, ...] = (FileState.CREATED.value,)
        else:
            owner_clause = "owner_id = ?"
            params = (FileState.CREATED.value, owner_id)
        rows = self._conn.execute(
            f"""
            SELECT * FROM file_meta
            WHERE state = ? AND {owner_clause} AND write_holder IS NULL
            ORDER BY created_at ASC
            """,
            params,
        ).fetchall()
        metas = [self._from_row(row) for row in rows]
        if tags:
            metas = [meta for meta in metas if all(meta.tags.get(key) == value for key, value in tags.items())]
        return metas

    def list_files(self, *, state: FileState | None = None, tags: Mapping[str, Any] | None = None) -> list[FileMeta]:
        if state is None:
            rows = self._conn.execute("SELECT * FROM file_meta ORDER BY created_at ASC").fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM file_meta WHERE state = ? ORDER BY created_at ASC",
                (state.value,),
            ).fetchall()
        metas = [self._from_row(row) for row in rows]
        if tags:
            metas = [meta for meta in metas if all(meta.tags.get(key) == value for key, value in tags.items())]
        return metas

    def expired_leases(self, now: datetime | None = None) -> list[FileMeta]:
        now = now or utcnow()
        rows = self._conn.execute(
            """
            SELECT * FROM file_meta
            WHERE lease_expire IS NOT NULL
              AND lease_expire < ?
              AND state = ?
            ORDER BY lease_expire ASC
            """,
            (_to_text(now), FileState.PROCESSING.value),
        ).fetchall()
        return [self._from_row(row) for row in rows]

    def _create_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS file_meta (
                file_id TEXT PRIMARY KEY,
                version INTEGER NOT NULL,
                state TEXT NOT NULL,
                owner_id TEXT,
                write_holder TEXT,
                read_count INTEGER NOT NULL DEFAULT 0,
                object_id TEXT NOT NULL,
                tags TEXT NOT NULL DEFAULT '{}',
                parent_file_id TEXT,
                previous_file_id TEXT,
                lease_expire TEXT,
                processing_round INTEGER NOT NULL DEFAULT 0,
                max_rounds INTEGER NOT NULL DEFAULT 1,
                termination_policy TEXT NOT NULL DEFAULT 'ARCHIVE',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                heartbeat_epoch INTEGER,
                smooth_load REAL,
                next_cycle_at TEXT,
                retention_policy TEXT
            )
            """
        )
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_file_meta_claim ON file_meta(state, owner_id)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_file_meta_lease ON file_meta(lease_expire)")

    def _to_row(self, meta: FileMeta) -> tuple[Any, ...]:
        return (
            meta.file_id,
            meta.version,
            meta.state.value,
            meta.owner_id,
            meta.write_holder,
            meta.read_count,
            meta.object_id,
            json.dumps(meta.tags, ensure_ascii=False, sort_keys=True),
            meta.parent_file_id,
            meta.previous_file_id,
            _to_text(meta.lease_expire),
            meta.processing_round,
            meta.max_rounds,
            meta.termination_policy,
            _to_text(meta.created_at),
            _to_text(meta.updated_at),
            meta.heartbeat_epoch,
            meta.smooth_load,
            _to_text(meta.next_cycle_at),
            meta.retention_policy,
        )

    def _from_row(self, row: sqlite3.Row) -> FileMeta:
        return FileMeta(
            file_id=row["file_id"],
            version=row["version"],
            state=FileState(row["state"]),
            owner_id=row["owner_id"],
            write_holder=row["write_holder"],
            read_count=row["read_count"],
            object_id=row["object_id"],
            tags=json.loads(row["tags"]),
            parent_file_id=row["parent_file_id"],
            previous_file_id=row["previous_file_id"],
            lease_expire=_from_text(row["lease_expire"]),
            processing_round=row["processing_round"],
            max_rounds=row["max_rounds"],
            termination_policy=row["termination_policy"],
            created_at=_from_text(row["created_at"]) or utcnow(),
            updated_at=_from_text(row["updated_at"]) or utcnow(),
            heartbeat_epoch=row["heartbeat_epoch"],
            smooth_load=row["smooth_load"],
            next_cycle_at=_from_text(row["next_cycle_at"]),
            retention_policy=row["retention_policy"],
        )

    def _encode_value(self, field: str, value: Any) -> Any:
        if field == "state" and isinstance(value, FileState):
            return value.value
        if field == "tags":
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        if isinstance(value, datetime):
            return _to_text(value)
        return value
