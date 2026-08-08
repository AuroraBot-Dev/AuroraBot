"""面板后端私有存储（RFC 0218 §6）：bootstrap Token、Bearer 会话与附件索引。

位于 ops 包，数据落 ``data/ops/``（panel.sqlite3 + Token.txt + uploads/）。
存储实现使用 SQLAlchemy 2.0 ORM（RFC 0217），Schema 演进经
``ops/migration`` 版本序列（utils.migration 框架）；ops 仍只依赖
contracts + utils 与通用依赖的边界。
"""

from __future__ import annotations

import hashlib
import secrets
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from rich.console import Console
from rich.panel import Panel
from sqlalchemy import Column, Integer, String, Table, create_engine, delete, select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.pool import NullPool

from src.utils import utc_now
from src.utils.migration import initialize_storage

from . import migration

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

_TOKEN_BYTES = 32
_TOKEN_PRINT_CONSOLE = Console(highlight=False)


class _Base(DeclarativeBase):
    """panel.sqlite3 的声明式基类。"""


SchemaMetaRow = Table(
    "schema_meta",
    _Base.metadata,
    Column("version", Integer, nullable=False),
)


class SessionRow(_Base):
    """sessions：Bearer 会话（token 只存 SHA-256 摘要）。"""

    __tablename__ = "sessions"

    token_hash: Mapped[str] = mapped_column("token_hash", String, primary_key=True)
    created_at: Mapped[str] = mapped_column("created_at", String, nullable=False)
    expires_at: Mapped[str] = mapped_column("expires_at", String, nullable=False)


class AttachmentRow(_Base):
    """attachments：上传附件索引。"""

    __tablename__ = "attachments"

    attachment_id: Mapped[str] = mapped_column("attachment_id", String, primary_key=True)
    name: Mapped[str] = mapped_column("name", String, nullable=False)
    mime: Mapped[str] = mapped_column("mime", String, nullable=False)
    size: Mapped[int] = mapped_column("size", Integer, nullable=False)
    stored_name: Mapped[str] = mapped_column("stored_name", String, nullable=False)
    created_at: Mapped[str] = mapped_column("created_at", String, nullable=False)


def _print_bootstrap_token(token: str, token_path: "Path") -> None:
    """首次生成 bootstrap token 时用 Rich Panel 展示（仅终端，不写入日志）。"""
    content = (
        f"[bold yellow]Token:[/bold yellow] [bold green]{token}[/bold green]\n\n"
        "[dim]请妥善保管 Token。\n"
        f"你也可以在 [bold]{token_path}[/bold] 查看你的 Token。\n"
        "如果不慎泄露，请删除 Token.txt 以重新生成。[/dim]"
    )
    _TOKEN_PRINT_CONSOLE.print(Panel(content, title="Aurora Panel Auth"))


class PanelStore:
    """面板会话与附件存储：Token 文件原子创建、会话生命周期与附件索引。"""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        data_dir.mkdir(parents=True, exist_ok=True)
        self._database_path = data_dir / "panel.sqlite3"
        self._token_path = data_dir / "Token.txt"
        self._upload_dir = data_dir / "uploads"
        self._upload_dir.mkdir(parents=True, exist_ok=True)
        self._engine = create_engine(
            f"sqlite:///{self._database_path}",
            poolclass=NullPool,
            connect_args={"timeout": 30},
        )
        with self._engine.begin() as connection:
            connection.execute(text("PRAGMA journal_mode=WAL"))
            connection.execute(text("PRAGMA busy_timeout=30000"))
        self._migrate()
        self._bootstrap_token = self._load_or_create_token()

    @property
    def bootstrap_token(self) -> str:
        """本次启动的 bootstrap token（首次启动生成并落盘）。"""
        return self._bootstrap_token

    @property
    def upload_dir(self) -> Path:
        return self._upload_dir

    def _load_or_create_token(self) -> str:
        """读取或原子创建 Token.txt（0600）；首次生成时在控制台用 Rich Panel 展示。"""
        if self._token_path.exists():
            raw = self._token_path.read_text(encoding="utf-8").strip()
            if raw:
                return raw
        token = secrets.token_urlsafe(_TOKEN_BYTES)
        temporary = self._token_path.with_suffix(".tmp")
        temporary.write_text(token + "\n", encoding="utf-8")
        temporary.chmod(0o600)
        temporary.replace(self._token_path)
        _print_bootstrap_token(token, self._token_path)
        return token

    def _migrate(self) -> None:
        """统一初始化（initialize_storage：全新建表/旧库按版本序列迁移）。"""
        with self._engine.begin() as connection:
            initialize_storage(
                connection,
                metadata=_Base.metadata,
                steps=migration.STEPS,
                target=migration.TARGET_VERSION,
            )

    @contextmanager
    def _session(self) -> Generator[Session, None, None]:
        """事务上下文：成功提交，异常回滚。"""
        with Session(self._engine, expire_on_commit=False) as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    # -- 认证 ------------------------------------------------------------

    def create_session(self, token: str, ttl_seconds: int) -> dict[str, str]:
        """为登录 token 创建 Bearer 会话，返回会话元数据。"""
        now = datetime.now(UTC)
        expires = now + timedelta(seconds=ttl_seconds)
        with self._session() as session:
            session.execute(
                sqlite_insert(SessionRow)
                .values(
                    token_hash=_digest(token),
                    created_at=now.isoformat(),
                    expires_at=expires.isoformat(),
                )
                .on_conflict_do_update(
                    index_elements=["token_hash"],
                    set_={
                        "created_at": now.isoformat(),
                        "expires_at": expires.isoformat(),
                    },
                )
            )
        return {"created_at": now.isoformat(), "expires_at": expires.isoformat()}

    def verify_session(self, token: str) -> bool:
        """校验 Bearer token：存在且未过期。"""
        now = utc_now()
        with self._session() as session:
            row = session.scalar(select(SessionRow.expires_at).where(SessionRow.token_hash == _digest(token)))
        return row is not None and str(row) > now

    def delete_session(self, token: str) -> None:
        """销毁会话。"""
        with self._session() as session:
            session.execute(delete(SessionRow).where(SessionRow.token_hash == _digest(token)))

    # -- 附件 ------------------------------------------------------------

    def add_attachment(self, *, name: str, mime: str, size: int, stored_name: str) -> dict[str, Any]:
        """登记附件并返回索引记录。"""
        attachment_id = str(uuid4().hex)
        created_at = utc_now()
        with self._session() as session:
            session.add(
                AttachmentRow(
                    attachment_id=attachment_id,
                    name=name,
                    mime=mime,
                    size=size,
                    stored_name=stored_name,
                    created_at=created_at,
                )
            )
        return self._attachment_row(attachment_id, name, mime, size, stored_name, created_at)

    def get_attachment(self, attachment_id: str) -> dict[str, Any] | None:
        """按 ID 查询附件索引。"""
        with self._session() as session:
            row = session.scalar(select(AttachmentRow).where(AttachmentRow.attachment_id == attachment_id))
        return (
            self._attachment_row(row.attachment_id, row.name, row.mime, row.size, row.stored_name, row.created_at)
            if row is not None
            else None
        )

    @staticmethod
    def _attachment_row(
        attachment_id: str, name: str, mime: str, size: int, stored_name: str, created_at: str
    ) -> dict[str, Any]:
        return {
            "attachment_id": attachment_id,
            "name": name,
            "mime": mime,
            "size": size,
            "stored_name": stored_name,
            "created_at": created_at,
        }

    def close(self) -> None:
        """关闭数据库引擎与连接池。"""
        self._engine.dispose()


def _digest(token: str) -> str:
    """会话 token 的 SHA-256 摘要（库中不存明文）。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
