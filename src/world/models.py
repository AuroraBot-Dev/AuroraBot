"""WorldJournal 的 SQLAlchemy 声明式 ORM 模型。"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - SQLAlchemy resolves this annotation during model declaration
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """世界数据库全部 ORM 模型的基类。"""


class SchemaMetaRow(Base):
    """单行 schema 版本记录。"""

    __tablename__ = "schema_meta"

    singleton: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    version: Mapped[int] = mapped_column(Integer, nullable=False)


class WorldCommitRow(Base):
    """世界提交的不可变主体。"""

    __tablename__ = "world_commits"

    insertion_sequence: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    commit_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    summary: Mapped[str] = mapped_column(String, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class WorldCommitScopeRow(Base):
    """提交在每个 scope 中的独立序号。"""

    __tablename__ = "world_commit_scopes"
    __table_args__ = (
        UniqueConstraint("scope", "sequence", name="world_commit_scope_sequence_unique"),
        UniqueConstraint("commit_id", "scope", name="world_commit_scope_membership_unique"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    commit_id: Mapped[str] = mapped_column(ForeignKey("world_commits.commit_id"), nullable=False)
    scope: Mapped[str] = mapped_column(String, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)


class WorldCommitBaseRow(Base):
    """提交声明的观察前沿。"""

    __tablename__ = "world_commit_bases"
    __table_args__ = (UniqueConstraint("commit_id", "scope", name="world_commit_base_unique"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    commit_id: Mapped[str] = mapped_column(ForeignKey("world_commits.commit_id"), nullable=False)
    scope: Mapped[str] = mapped_column(String, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
