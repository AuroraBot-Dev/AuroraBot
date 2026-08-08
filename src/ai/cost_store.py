"""模型调用费用持久化：``data/ai/cost.sqlite3``（RFC 0215 §4，存储镜像 src/ai → data/ai/）。

与 engine/memory/ops 同一持久化体系（RFC 0217 §5）：SQLAlchemy ORM 声明
Schema、``schema_meta`` 版本号、``utils.migration.initialize_storage`` 统一
初始化入口。费用记录是只追加的审计日志，无更新/删除路径。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import Column, Float, Integer, String, Table, create_engine, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.pool import NullPool

from src.utils import utc_now
from src.utils.migration import initialize_storage

if TYPE_CHECKING:
    from pathlib import Path


class _Base(DeclarativeBase):
    """cost.sqlite3 的声明式基类。"""


SchemaMetaRow = Table(
    "schema_meta",
    _Base.metadata,
    Column("version", Integer, nullable=False),
)


class CostRecordRow(_Base):
    """cost_records：模型调用费用（只追加审计日志）。"""

    __tablename__ = "cost_records"
    __table_args__ = ({"sqlite_autoincrement": True},)

    id: Mapped[int] = mapped_column("id", Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str | None] = mapped_column("task_id", String, nullable=True)
    role: Mapped[str] = mapped_column("role", String, nullable=False)
    model: Mapped[str] = mapped_column("model", String, nullable=False)
    type: Mapped[str] = mapped_column("type", String, nullable=False)
    status: Mapped[str] = mapped_column("status", String, nullable=False)
    prompt_tokens: Mapped[int] = mapped_column("prompt_tokens", Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column("completion_tokens", Integer, nullable=False, default=0)
    cost: Mapped[float] = mapped_column("cost", Float, nullable=False, default=0.0)
    created_at: Mapped[str] = mapped_column("created_at", String, nullable=False)


def _build_engine(database_path: Path) -> Any:
    """构建同步 SQLite 引擎：NullPool + 连接超时（与面板/记忆存储同约定）。"""
    return create_engine(
        f"sqlite:///{database_path}",
        poolclass=NullPool,
        connect_args={"timeout": 30},
    )


def _row_dict(row: CostRecordRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "task_id": row.task_id,
        "role": row.role,
        "model": row.model,
        "type": row.type,
        "status": row.status,
        "prompt_tokens": row.prompt_tokens,
        "completion_tokens": row.completion_tokens,
        "cost": row.cost,
        "created_at": row.created_at,
    }


class CostStore:
    """费用记录 SQLite 存储（WAL；只追加，无更新路径）。"""

    def __init__(self, data_dir: Path) -> None:
        data_dir.mkdir(parents=True, exist_ok=True)
        self._path = data_dir / "cost.sqlite3"
        self._engine = _build_engine(self._path)
        self._init_database()

    @property
    def path(self) -> Path:
        return self._path

    def _init_database(self) -> None:
        """WAL 配置 + 统一初始化（initialize_storage：全新建表/旧库按版本序列迁移）。"""
        from src.ai import migration

        with self._engine.begin() as connection:
            connection.execute(text("PRAGMA journal_mode=WAL"))
            connection.execute(text("PRAGMA busy_timeout=30000"))
            initialize_storage(
                connection,
                metadata=_Base.metadata,
                steps=migration.STEPS,
                target=migration.TARGET_VERSION,
            )

    def load_records(self) -> list[dict[str, Any]]:
        """按写入顺序返回全部费用记录（启动时恢复历史）。"""
        with Session(self._engine, expire_on_commit=False) as session:
            rows = session.execute(select(CostRecordRow).order_by(CostRecordRow.id)).scalars().all()
        return [_row_dict(row) for row in rows]

    def append(self, record: dict[str, Any]) -> None:
        """追加一条费用记录（只追加，不更新）。"""
        with Session(self._engine, expire_on_commit=False) as session:
            session.add(
                CostRecordRow(
                    task_id=record.get("task_id"),
                    role=record["role"],
                    model=record["model"],
                    type=record["type"],
                    status=record["status"],
                    prompt_tokens=int(record.get("prompt_tokens", 0)),
                    completion_tokens=int(record.get("completion_tokens", 0)),
                    cost=float(record.get("cost", 0.0)),
                    created_at=utc_now(),
                )
            )
            session.commit()

    def close(self) -> None:
        self._engine.dispose()
