"""版本化迁移框架：步骤顺序、版本推进与缺失/超前版本拒绝。"""

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

_V2_DDL = """
CREATE TABLE schema_meta (version INTEGER NOT NULL);
CREATE TABLE tasks (
    task_id TEXT PRIMARY KEY, root_agent_id TEXT NOT NULL,
    root_message_id TEXT NOT NULL UNIQUE, session_id TEXT NOT NULL,
    root_summary TEXT NOT NULL, autonomous INTEGER NOT NULL CHECK (autonomous IN (0, 1)),
    status TEXT NOT NULL, model_calls INTEGER NOT NULL, tool_calls INTEGER NOT NULL,
    max_model_calls INTEGER NOT NULL, max_tool_calls INTEGER NOT NULL,
    max_duration_seconds REAL NOT NULL, started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL, termination_reason TEXT
);
CREATE TABLE agents (
    agent_id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(task_id),
    parent_agent_id TEXT REFERENCES agents(agent_id), profile_id TEXT NOT NULL,
    depth INTEGER NOT NULL, assignment TEXT NOT NULL, status TEXT NOT NULL,
    revision INTEGER NOT NULL, state_json TEXT NOT NULL, created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL, last_summary TEXT NOT NULL DEFAULT ''
);
CREATE INDEX idx_agents_task ON agents(task_id, status);
CREATE INDEX idx_agents_parent ON agents(parent_agent_id, status);
CREATE TABLE mailbox (
    message_id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(task_id),
    target_agent_id TEXT NOT NULL REFERENCES agents(agent_id), type TEXT NOT NULL,
    payload_json TEXT NOT NULL, causation_id TEXT, correlation_id TEXT NOT NULL,
    priority INTEGER NOT NULL, status TEXT NOT NULL, available_at TEXT NOT NULL,
    lease_until TEXT, attempts INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE INDEX idx_mailbox_ready ON mailbox(status, priority DESC, available_at, created_at);
CREATE INDEX idx_mailbox_agent ON mailbox(target_agent_id, status, created_at);
CREATE TABLE activities (
    activity_id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(task_id),
    agent_id TEXT NOT NULL REFERENCES agents(agent_id),
    kind TEXT NOT NULL CHECK (kind IN ('model', 'effect')),
    request_json TEXT NOT NULL, status TEXT NOT NULL, priority INTEGER NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE, lease_until TEXT, created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL, result_json TEXT, error TEXT
);
CREATE INDEX idx_activities_ready ON activities(kind, status, priority DESC, created_at);
CREATE UNIQUE INDEX idx_activities_one_active_per_agent
    ON activities(agent_id) WHERE status IN ('PENDING', 'PROCESSING');
CREATE TABLE causal_events (
    event_id TEXT PRIMARY KEY, task_id TEXT, agent_id TEXT, type TEXT NOT NULL,
    summary TEXT NOT NULL, payload_json TEXT NOT NULL, causation_id TEXT,
    correlation_id TEXT NOT NULL, external_message_id TEXT UNIQUE, created_at TEXT NOT NULL
);
CREATE INDEX idx_causal_task ON causal_events(task_id, created_at);
CREATE TABLE situations (
    situation_id TEXT PRIMARY KEY, source TEXT NOT NULL, type TEXT NOT NULL,
    summary TEXT NOT NULL, payload_json TEXT NOT NULL, priority INTEGER NOT NULL,
    status TEXT NOT NULL, claimed_by_agent_id TEXT, expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX idx_situations_open ON situations(status, expires_at, priority DESC);
"""

_V7_DDL = """
CREATE TABLE schema_meta (version INTEGER NOT NULL);
CREATE TABLE tasks (
    task_id TEXT PRIMARY KEY, root_agent_id TEXT NOT NULL,
    root_message_id TEXT NOT NULL UNIQUE, session_id TEXT NOT NULL,
    root_summary TEXT NOT NULL, autonomous INTEGER NOT NULL CHECK (autonomous IN (0, 1)),
    status TEXT NOT NULL, model_calls INTEGER NOT NULL, tool_calls INTEGER NOT NULL,
    max_model_calls INTEGER NOT NULL, max_tool_calls INTEGER NOT NULL,
    max_duration_seconds REAL NOT NULL, started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL, termination_reason TEXT
);
CREATE TABLE agents (
    agent_id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(task_id),
    parent_agent_id TEXT REFERENCES agents(agent_id), profile_id TEXT NOT NULL,
    depth INTEGER NOT NULL, assignment TEXT NOT NULL, status TEXT NOT NULL,
    revision INTEGER NOT NULL, state_json TEXT NOT NULL, created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL, last_summary TEXT NOT NULL DEFAULT ''
);
CREATE INDEX idx_agents_task ON agents(task_id, status);
CREATE INDEX idx_agents_parent ON agents(parent_agent_id, status);
CREATE TABLE mailbox (
    message_id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(task_id),
    target_agent_id TEXT NOT NULL REFERENCES agents(agent_id), type TEXT NOT NULL,
    payload_json TEXT NOT NULL, causation_id TEXT, correlation_id TEXT NOT NULL,
    priority INTEGER NOT NULL, status TEXT NOT NULL, available_at TEXT NOT NULL,
    lease_until TEXT, attempts INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE INDEX idx_mailbox_ready ON mailbox(status, priority DESC, available_at, created_at);
CREATE INDEX idx_mailbox_agent ON mailbox(target_agent_id, status, created_at);
CREATE TABLE activities (
    activity_id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(task_id),
    agent_id TEXT NOT NULL REFERENCES agents(agent_id),
    kind TEXT NOT NULL CHECK (kind IN ('model', 'tool')),
    request_json TEXT NOT NULL, status TEXT NOT NULL, priority INTEGER NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE, lease_until TEXT, created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL, result_json TEXT, error TEXT
);
CREATE INDEX idx_activities_ready ON activities(kind, status, priority DESC, created_at);
CREATE UNIQUE INDEX idx_activities_one_active_per_agent
    ON activities(agent_id) WHERE status IN ('PENDING', 'PROCESSING');
CREATE TABLE causal_events (
    event_id TEXT PRIMARY KEY, task_id TEXT, agent_id TEXT, type TEXT NOT NULL,
    summary TEXT NOT NULL, payload_json TEXT NOT NULL, causation_id TEXT,
    correlation_id TEXT NOT NULL, external_message_id TEXT UNIQUE, created_at TEXT NOT NULL
);
CREATE INDEX idx_causal_task ON causal_events(task_id, created_at);
CREATE TABLE inbox_events (
    event_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, type TEXT NOT NULL,
    summary TEXT NOT NULL, source_json TEXT NOT NULL, data_json TEXT NOT NULL,
    priority INTEGER NOT NULL, status TEXT NOT NULL CHECK (status IN ('PENDING', 'TRIAGING', 'DEFERRED')),
    batch_id TEXT, available_at TEXT NOT NULL, created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_inbox_due ON inbox_events(status, available_at, priority DESC, created_at);
CREATE INDEX idx_inbox_session ON inbox_events(session_id, status, created_at);
"""


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


def test_engine_store_fresh_database_is_initialized_to_target_version(tmp_path: Path) -> None:
    from src.engine.store import SQLiteRuntimeStore

    store = SQLiteRuntimeStore(tmp_path / "runtime.sqlite3")
    store.initialize()
    with store.connect() as connection:
        version = connection.execute("SELECT version FROM schema_meta").fetchone()[0]
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert version == 9  # noqa: PLR2004
    assert {"tasks", "agents", "messages", "activities", "causal_events", "inbox_events"} <= tables


def test_engine_store_database_newer_than_target_is_rejected(tmp_path: Path) -> None:
    """库版本比代码支持更新（v10）时拒绝启动，防止静默漏迁移。"""
    import sqlite3 as dbapi

    from src.engine.store import SQLiteRuntimeStore

    path = tmp_path / "runtime.sqlite3"
    with dbapi.connect(path) as connection:
        connection.execute("CREATE TABLE schema_meta (version INTEGER NOT NULL)")
        connection.execute("INSERT INTO schema_meta(version) VALUES (10)")
    store = SQLiteRuntimeStore(path)
    with pytest.raises(RuntimeError, match="newer than supported"):
        store.initialize()


def test_engine_store_v2_database_migrates_to_v9(tmp_path: Path) -> None:
    """v2 样本库（演化档案最早文档版本）经完整版本序列迁移到 v9。

    验证 kind 归一（effect → tool + legacy_kind）、audience 阶段建/撤、
    mailbox → messages、冗余列删除与索引重建。
    """
    import sqlite3 as dbapi

    from src.engine.store import SQLiteRuntimeStore

    path = tmp_path / "runtime.sqlite3"
    with dbapi.connect(path) as connection:
        connection.executescript(_V2_DDL)
        connection.execute("INSERT INTO schema_meta(version) VALUES (2)")
        connection.execute(
            "INSERT INTO tasks VALUES ('t1','ra1','rm1','s1','root',1,'ACTIVE',"
            "0,0,100,100,3600.0,'2026-01-01T00:00:00Z','2026-01-01T00:00:00Z',NULL)"
        )
        connection.execute(
            "INSERT INTO agents VALUES ('a1','t1',NULL,'default',0,'root','READY',"
            "1,'{}','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z','')"
        )
        connection.execute(
            "INSERT INTO mailbox VALUES ('m1','t1','a1','user.text','{}',NULL,'c1',"
            "5,'PENDING','2026-01-01T00:00:00Z',NULL,0,'2026-01-01T00:00:00Z',NULL)"
        )
        connection.execute(
            "INSERT INTO activities VALUES ('act1','t1','a1','model','{\"x\":1}',"
            "'COMPLETED',5,'k1',NULL,'2026-01-01T00:00:00Z','2026-01-01T00:00:00Z','{\"ok\":true}',NULL)"
        )
        connection.execute(
            "INSERT INTO activities VALUES ('act2','t1','a1','effect','{\"y\":2}',"
            "'COMPLETED',5,'k2',NULL,'2026-01-01T00:00:00Z','2026-01-01T00:00:00Z','{\"ok\":true}',NULL)"
        )
        connection.execute(
            "INSERT INTO causal_events VALUES ('ev1','t1','a1','task.started','s',"
            "'{\"a\":1}',NULL,'c1','ext1','2026-01-01T00:00:00Z')"
        )
        connection.execute(
            "INSERT INTO situations VALUES ('s1','console','info','hi','{}',1,"
            "'OPEN',NULL,'2026-01-01T00:00:00Z','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z')"
        )

    store = SQLiteRuntimeStore(path)
    store.initialize()

    with store.connect() as connection:
        version = connection.execute("SELECT version FROM schema_meta").fetchone()[0]
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        indexes = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
        columns = {
            table: {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
            for table in ("tasks", "agents", "activities", "causal_events", "messages")
        }
        message = connection.execute("SELECT * FROM messages WHERE message_id = 'm1'").fetchone()
        act2 = connection.execute("SELECT kind, request_json FROM activities WHERE activity_id = 'act2'").fetchone()
        act1 = connection.execute("SELECT kind, request_json FROM activities WHERE activity_id = 'act1'").fetchone()
        event = connection.execute("SELECT * FROM causal_events WHERE event_id = 'ev1'").fetchone()
        agent = connection.execute("SELECT * FROM agents WHERE agent_id = 'a1'").fetchone()

    assert version == 9  # noqa: PLR2004
    assert {"tasks", "agents", "messages", "activities", "causal_events", "inbox_events"} <= tables
    assert {"mailbox", "situations", "reply_grants"} & tables == set()
    assert "audience_ref" not in columns["tasks"]
    assert "revision" not in columns["agents"]
    assert "lease_until" not in columns["activities"]
    assert "external_message_id" not in columns["causal_events"]
    assert {"available_at", "lease_until", "attempts"} & columns["messages"] == set()
    required_indexes = {
        "idx_messages_ready",
        "idx_messages_agent",
        "idx_inbox_due",
        "idx_activities_one_active_per_agent",
    }
    assert required_indexes <= indexes
    assert message is not None and message["correlation_id"] == "c1" and message["priority"] == 5  # noqa: PLR2004
    assert act1 is not None and act1["kind"] == "model"
    assert act2 is not None and act2["kind"] == "tool" and "legacy_kind" in act2["request_json"]
    assert event is not None and event["correlation_id"] == "c1"
    assert agent is not None and agent["agent_id"] == "a1"


def test_engine_store_v7_database_migrates_to_v9(tmp_path: Path) -> None:
    """v7 样本库（inbox 已存在、mailbox 租约列未删）迁移到 v9。"""
    import sqlite3 as dbapi

    from src.engine.store import SQLiteRuntimeStore

    path = tmp_path / "runtime.sqlite3"
    with dbapi.connect(path) as connection:
        connection.executescript(_V7_DDL)
        connection.execute("INSERT INTO schema_meta(version) VALUES (7)")
        connection.execute(
            "INSERT INTO tasks VALUES ('t1','ra1','rm1','s1','root',1,'ACTIVE',"
            "0,0,100,100,3600.0,'2026-01-01T00:00:00Z','2026-01-01T00:00:00Z',NULL)"
        )
        connection.execute(
            "INSERT INTO agents VALUES ('a1','t1',NULL,'default',0,'root','READY',"
            "1,'{}','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z','')"
        )
        connection.execute(
            "INSERT INTO mailbox VALUES ('m1','t1','a1','user.text','{}',NULL,'c1',"
            "5,'PENDING','2026-01-01T00:00:00Z','2026-01-02T00:00:00Z',3,"
            "'2026-01-01T00:00:00Z',NULL)"
        )
        connection.execute(
            "INSERT INTO inbox_events VALUES ('in1','s1','amp.ingress','hi','{}','{}',"
            "1,'PENDING',NULL,'2026-01-01T00:00:00Z','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z')"
        )
        connection.execute(
            "INSERT INTO activities VALUES ('act1','t1','a1','tool','{\"x\":1}',"
            "'COMPLETED',5,'k1','2026-01-02T00:00:00Z','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z','{\"ok\":true}',NULL)"
        )

    store = SQLiteRuntimeStore(path)
    store.initialize()

    with store.connect() as connection:
        version = connection.execute("SELECT version FROM schema_meta").fetchone()[0]
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        message = connection.execute("SELECT * FROM messages WHERE message_id = 'm1'").fetchone()
        inbox = connection.execute("SELECT * FROM inbox_events WHERE event_id = 'in1'").fetchone()
        activity = connection.execute("SELECT * FROM activities WHERE activity_id = 'act1'").fetchone()

    assert version == 9  # noqa: PLR2004
    assert "mailbox" not in tables
    assert "messages" in tables
    assert message is not None and message["correlation_id"] == "c1" and message["completed_at"] is None
    assert inbox is not None and inbox["status"] == "PENDING"
    assert activity is not None and activity["kind"] == "tool"


def test_memory_store_fresh_database_is_initialized_to_target_version(tmp_path: Path) -> None:
    import sqlite3 as dbapi

    from src.memory.service import MemoryService

    directory = tmp_path / "memory"
    MemoryService(directory)
    with dbapi.connect(directory / "memory.sqlite3") as connection:
        version = connection.execute("SELECT version FROM schema_meta").fetchone()[0]
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert version == 2  # noqa: PLR2004
    assert {"memory_receipts", "session_memory", "durable_facts", "memory_messages", "schema_meta"} <= tables
    MemoryService(directory)


def test_memory_v1_facts_are_rescoped_to_global(tmp_path: Path) -> None:
    """v1 存量按会话隔离的 facts 在迁移到 v2 后统一为 global，重复内容保留最早来源。"""
    import sqlite3 as dbapi

    from src.memory.service import MemoryService

    directory = tmp_path / "memory"
    directory.mkdir(parents=True)
    with dbapi.connect(directory / "memory.sqlite3") as connection:
        connection.executescript(
            """
            CREATE TABLE schema_meta (version INTEGER NOT NULL);
            INSERT INTO schema_meta(version) VALUES (1);
            CREATE TABLE memory_receipts (
                task_id TEXT PRIMARY KEY, scope TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE session_memory (
                scope TEXT PRIMARY KEY, summary TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE durable_facts (
                fact_id INTEGER PRIMARY KEY AUTOINCREMENT, scope TEXT NOT NULL,
                content TEXT NOT NULL, source_task_id TEXT NOT NULL, created_at TEXT NOT NULL,
                UNIQUE(scope, content)
            );
            CREATE TABLE memory_messages (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, scope TEXT NOT NULL,
                role TEXT NOT NULL, content TEXT NOT NULL, at TEXT NOT NULL
            );
            INSERT INTO durable_facts(scope, content, source_task_id, created_at)
                VALUES ('qq:group:1', 'f1', 't1', '2026-01-01'), ('qq:private:2', 'f2', 't2', '2026-01-02');
            """
        )
    MemoryService(directory)
    with dbapi.connect(directory / "memory.sqlite3") as connection:
        version = connection.execute("SELECT version FROM schema_meta").fetchone()[0]
        facts = connection.execute("SELECT scope, content FROM durable_facts ORDER BY created_at").fetchall()
    assert version == 2  # noqa: PLR2004
    assert facts == [("global", "f1"), ("global", "f2")]


def test_panel_store_fresh_database_is_initialized_to_target_version(tmp_path: Path) -> None:
    import sqlite3 as dbapi

    from ops.store import PanelStore

    directory = tmp_path / "panel"
    PanelStore(directory)
    with dbapi.connect(directory / "panel.sqlite3") as connection:
        version = connection.execute("SELECT version FROM schema_meta").fetchone()[0]
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert version == 1
    assert {"sessions", "attachments", "schema_meta"} <= tables
