"""Memory SQLite 的纯 SQLAlchemy 数据模型。"""

from __future__ import annotations

from sqlalchemy import Column, Index, Integer, String, Table, UniqueConstraint, desc
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """memory.sqlite3 全部表的声明式基类。"""


SchemaMetaRow = Table(
    "schema_meta",
    Base.metadata,
    Column("version", Integer, nullable=False),
)


class MemoryReceiptRow(Base):
    """memory_receipts：终态投影幂等回执。"""

    __tablename__ = "memory_receipts"

    task_id: Mapped[str] = mapped_column("task_id", String, primary_key=True)
    scope: Mapped[str] = mapped_column("scope", String, nullable=False)
    created_at: Mapped[str] = mapped_column("created_at", String, nullable=False)


class SessionMemoryRow(Base):
    """session_memory：窗口外压缩概要（每 scope 一条）。"""

    __tablename__ = "session_memory"

    scope: Mapped[str] = mapped_column("scope", String, primary_key=True)
    summary: Mapped[str] = mapped_column("summary", String, nullable=False)
    updated_at: Mapped[str] = mapped_column("updated_at", String, nullable=False)


class DurableFactRow(Base):
    """durable_facts：长期事实（UNIQUE(scope, content) 保证去重）。"""

    __tablename__ = "durable_facts"
    __table_args__ = (
        UniqueConstraint("scope", "content"),
        Index("idx_durable_facts_scope_created", "scope", desc("created_at")),
    )

    fact_id: Mapped[int] = mapped_column("fact_id", Integer, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column("scope", String, nullable=False)
    content: Mapped[str] = mapped_column("content", String, nullable=False)
    source_task_id: Mapped[str] = mapped_column("source_task_id", String, nullable=False)
    created_at: Mapped[str] = mapped_column("created_at", String, nullable=False)


class MemoryMessageRow(Base):
    """memory_messages：最近 N 条原始消息（窗口）。"""

    __tablename__ = "memory_messages"
    __table_args__ = (
        Index("idx_memory_messages_scope", "scope", "seq"),
        {"sqlite_autoincrement": True},
    )

    seq: Mapped[int] = mapped_column("seq", Integer, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column("scope", String, nullable=False)
    role: Mapped[str] = mapped_column("role", String, nullable=False)
    content: Mapped[str] = mapped_column("content", String, nullable=False)
    at: Mapped[str] = mapped_column("at", String, nullable=False)
