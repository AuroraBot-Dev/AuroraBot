"""world 自有事件数据库及统一的有界 ctx 呈现。"""

import asyncio
import json
import logging
import math
import sqlite3
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from threading import get_ident
from time import time
from typing import Literal, cast
from uuid import uuid4

from aurora_core import entry_from, hook_handler
from aurora_core.ctx import Context
from aurora_core.hooks import HookConnections
from aurora_core.ids import Id
from aurora_core.json_data import decode_json, encode_json
from aurora_core.lifecycle import CLEAN, PREPARE, START, STOP, LifecycleComponent
from aurora_core.storage import StorageService

RECORDS = Id("org.aurora.world:state/records")
ENVIRONMENT = Id("org.aurora.world:state/environment")
Presentation = Literal["events", "time", "weather"]
logger = logging.getLogger(__name__)


def _identity(value: object) -> None:
    if type(value) is not str or not value.strip():
        raise ValueError("世界记录身份必须为非空字符串")
    encode_json(value)


def _timestamp(value: object) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("世界接收时间必须为有限数")
    return float(value)


@dataclass(frozen=True)
class WorldPosition:
    """数据库、序号与记录身份共同锚定消费位置。"""

    journal_id: str
    sequence: int
    record_id: str | None = None

    def __post_init__(self) -> None:
        _identity(self.journal_id)
        if type(self.sequence) is not int or self.sequence < 0:
            raise ValueError("世界读取位置必须为非负整数")
        if self.sequence:
            _identity(self.record_id)
        elif self.record_id is not None:
            raise ValueError("日志起点不能绑定记录身份")


@dataclass(frozen=True)
class WorldRecord:
    """完整载荷副本；环境观察使用独立身份，不进入事件消费游标。"""

    position: WorldPosition
    record_id: str
    source_id: str
    message_id: str
    payload: object


@dataclass(frozen=True)
class WorldContentPage:
    """事件原始 JSON 的字符片段；拼接全部 text 才构成完整 JSON。"""

    position: WorldPosition
    source_id: str
    message_id: str
    received_at: float
    offset: int
    text: str
    total_chars: int

    @property
    def next_offset(self) -> int | None:
        end = self.offset + len(self.text)
        return end if end < self.total_chars else None


@dataclass(frozen=True)
class WorldReceipt:
    """普通事件已提交数据库，环境观察已更新 ctx；不表示已转交消费者。"""

    record: WorldRecord
    duplicate: bool


class MessageConflictError(ValueError):
    """同一来源消息身份对应不同内容，拒绝覆盖。"""


class CursorError(ValueError):
    """数据库身份、记录锚点或迁移保留范围不匹配。"""


@dataclass(frozen=True)
class WorldView:
    """统一呈现预算；字符数包括文本条目的 JSON 元数据，允许超出一个整条目。"""

    recent_seconds: float = 3600
    max_chars: int = 32000
    max_event_chars: int = 8000
    time_count: int = 1
    weather_count: int = 4
    weather_seconds: float = 3600
    refresh_seconds: float = 30

    def __post_init__(self) -> None:
        for value in (self.recent_seconds, self.weather_seconds, self.refresh_seconds):
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError("呈现时间必须为正有限数")
        for value in (self.max_chars, self.max_event_chars, self.time_count, self.weather_count):
            if type(value) is not int or value < 1:
                raise ValueError("呈现上限必须为正整数")


def _validate_items(items: object, latest: int, *, environment: bool) -> None:
    if not isinstance(items, list):
        raise TypeError("世界呈现条目必须为列表")
    fields = {"sequence", "record_id", "source_id", "message_id", "received_at"}
    fields |= {"payload"} if environment else {"text", "abridged"}
    previous = 0
    identities, record_ids = set(), set()
    for item in items:
        if not isinstance(item, dict) or set(item) != fields:
            raise ValueError("世界呈现条目无效")
        for name in ("record_id", "source_id", "message_id"):
            _identity(item[name])
        identity = (item["source_id"], item["message_id"])
        if identity in identities or item["record_id"] in record_ids:
            raise ValueError("世界呈现身份重复")
        if type(item["sequence"]) is not int or not previous < item["sequence"] <= latest:
            raise ValueError("世界呈现顺序无效")
        identities.add(identity)
        record_ids.add(item["record_id"])
        previous = item["sequence"]
        _timestamp(item["received_at"])
        if not environment and (type(item["text"]) is not str or type(item["abridged"]) is not bool):
            raise ValueError("世界呈现文本无效")


def validate_records(value: object) -> None:
    """旧日志可恢复以报告迁移要求，启动不会隐式转换或丢弃旧数据。"""
    if isinstance(value, dict) and value.get("version") in (1, 2):
        from .legacy import validate_records as validate_legacy

        validate_legacy(value)
        return
    encode_json(value)
    if not isinstance(value, dict) or set(value) != {"version", "journal_id", "latest_sequence", "records"}:
        raise ValueError("世界呈现结构无效")
    if type(value["version"]) is not int or value["version"] != 3:
        raise ValueError("不支持的世界呈现版本")
    _identity(value["journal_id"])
    if type(value["latest_sequence"]) is not int or value["latest_sequence"] < 0:
        raise ValueError("世界呈现序号无效")
    _validate_items(value["records"], value["latest_sequence"], environment=False)


def validate_environment(value: object) -> None:
    encode_json(value)
    if not isinstance(value, dict) or set(value) != {"kind", "journal_id", "next_sequence", "records"}:
        raise ValueError("环境观察结构无效")
    if value["kind"] not in ("time", "weather"):
        raise ValueError("环境观察类型无效")
    _identity(value["journal_id"])
    if type(value["next_sequence"]) is not int or value["next_sequence"] < 1:
        raise ValueError("环境观察序号无效")
    _validate_items(value["records"], value["next_sequence"] - 1, environment=True)


def _content(value: object) -> str:
    encode_json(value)
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


class WorldRecords:
    """宿主持有并显式注入的记录服务；storage=None 表示内存数据库。

    open 在配置就绪后创建资源。普通事件事务提交后更新 ctx；视图失败不会回滚数据库，
    同一消息重试可以修复视图。有界视图随快照保存，启动按数据库重建；环境观察仅存 ctx。
    """

    def __init__(self, ctx: Context, storage: StorageService | None = None, *, now: Callable[[], float] = time) -> None:
        self.ctx, self.storage, self.now = ctx, storage, now
        self.view = WorldView()
        self._owner = get_ident()
        self._db: sqlite3.Connection | None = None
        self._closed = False
        self._connected = False
        self._worker: asyncio.Task[None] | None = None
        self._presentations: dict[str, Presentation] = {}
        self.last_error: str | None = None

    def configure(self, *, view: WorldView) -> None:
        self._check_owner()
        if self._db is not None:
            raise RuntimeError("记录服务已打开，不能重新配置")
        self.view = view

    def select(self, source_id: str, presentation: Presentation) -> None:
        self._check_owner()
        _identity(source_id)
        if presentation not in ("events", "time", "weather"):
            raise ValueError("未知的 world 呈现类型")
        if source_id in self._presentations:
            raise ValueError("来源呈现身份重复")
        self._presentations[source_id] = presentation

    def _check_owner(self) -> None:
        if get_ident() != self._owner:
            raise RuntimeError("记录接口必须在创建它的宿主线程调用")
        if self._closed:
            raise RuntimeError("世界记录服务已关闭")

    def presentation(self, source_id: str) -> Presentation:
        """查询 world 选定的呈现规则；未绑定的程序输入按普通事件处理。"""
        self._check_owner()
        _identity(source_id)
        return self._presentations.get(source_id, "events")

    def open(self) -> None:
        """打开数据库；旧日志与不匹配的快照要求显式迁移或核对。"""
        self._check_owner()
        if self._db is not None:
            return
        previous = self.ctx.get(RECORDS) if self.ctx.list(key=RECORDS, location={}) else None
        if isinstance(previous, dict) and previous["version"] != 3:
            raise ValueError("旧 world 日志需要显式迁移：uv run python -m aurora_world.migrate --root <数据目录>")
        path = (
            ":memory:" if self.storage is None else str(self.storage.directory("org.aurora.world") / "events.sqlite3")
        )
        db = sqlite3.connect(path)
        db.row_factory = sqlite3.Row
        try:
            if db.execute("PRAGMA user_version").fetchone()[0] not in (0, 1):
                raise ValueError("不支持的 world 数据库版本")
            with db:
                db.execute(
                    "CREATE TABLE IF NOT EXISTS journal (id TEXT NOT NULL, next_sequence INTEGER NOT NULL, pruned_through INTEGER NOT NULL, pruned_record_id TEXT)"
                )
                db.execute(
                    "CREATE TABLE IF NOT EXISTS events (sequence INTEGER PRIMARY KEY, record_id TEXT NOT NULL UNIQUE, source_id TEXT NOT NULL, message_id TEXT NOT NULL, received_at REAL NOT NULL, payload TEXT NOT NULL, text TEXT NOT NULL, UNIQUE(source_id, message_id))"
                )
                db.execute("CREATE INDEX IF NOT EXISTS events_received ON events(received_at, sequence)")
                db.execute("CREATE INDEX IF NOT EXISTS events_source ON events(source_id, sequence)")
                if db.execute("SELECT id FROM journal").fetchone() is None:
                    db.execute("INSERT INTO journal VALUES (?, 1, 0, NULL)", (uuid4().hex,))
                db.execute("PRAGMA user_version = 1")
            journal = db.execute("SELECT * FROM journal").fetchone()
            if isinstance(previous, dict) and (
                previous["journal_id"] != journal["id"] or previous["latest_sequence"] >= journal["next_sequence"]
            ):
                raise CursorError("world 数据库与 ctx 快照不匹配；请成套恢复数据目录")
            self._db = db
            self.refresh()
        except BaseException:
            self._db = None
            db.close()
            raise

    def _connection(self) -> sqlite3.Connection:
        self._check_owner()
        if self._db is None:
            raise RuntimeError("世界记录服务尚未 open/prepare")
        return self._db

    def _record(self, row: sqlite3.Row) -> WorldRecord:
        journal = self._connection().execute("SELECT id FROM journal").fetchone()[0]
        return WorldRecord(
            WorldPosition(journal, row["sequence"], row["record_id"]),
            row["record_id"],
            row["source_id"],
            row["message_id"],
            decode_json(row["payload"]),
        )

    def append(self, *, source_id: str, message_id: str, payload: object) -> WorldReceipt:
        _identity(source_id)
        _identity(message_id)
        encoded = _content(payload)
        db = self._connection()
        presentation = self.presentation(source_id)
        if presentation != "events":
            return self._observe(source_id, message_id, payload, presentation)
        row = db.execute("SELECT * FROM events WHERE source_id=? AND message_id=?", (source_id, message_id)).fetchone()
        duplicate = row is not None
        if row is not None:
            if row["payload"] != encoded:
                raise MessageConflictError("该来源消息身份已对应不同内容")
        else:
            received = _timestamp(self.now())
            with db:
                sequence = db.execute("SELECT next_sequence FROM journal").fetchone()[0]
                db.execute(
                    "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        sequence,
                        uuid4().hex,
                        source_id,
                        message_id,
                        received,
                        encoded,
                        payload if isinstance(payload, str) else encoded,
                    ),
                )
                db.execute("UPDATE journal SET next_sequence=next_sequence+1")
            row = db.execute("SELECT * FROM events WHERE sequence=?", (sequence,)).fetchone()
        record = self._record(row)
        self.refresh()
        return WorldReceipt(record, duplicate)

    def get(self, *, source_id: str, message_id: str) -> WorldRecord:
        _identity(source_id)
        _identity(message_id)
        row = (
            self._connection()
            .execute("SELECT * FROM events WHERE source_id=? AND message_id=?", (source_id, message_id))
            .fetchone()
        )
        if row is None:
            raise KeyError((source_id, message_id))
        return self._record(row)

    def get_by_id(self, record_id: str) -> WorldRecord:
        """根据近期视图携带的记录 ID 查询完整事件。"""
        _identity(record_id)
        row = self._connection().execute("SELECT * FROM events WHERE record_id=?", (record_id,)).fetchone()
        if row is None:
            raise KeyError(record_id)
        return self._record(row)

    def read_content(self, *, journal_id: str, record_id: str, offset: int = 0, limit: int = 4000) -> WorldContentPage:
        """核对数据库身份后读取事件 JSON 片段，不反序列化完整载荷或刷新 ctx。

        offset/limit 按 Unicode 字符计数；单页最多 65536 字符。offset 等于全文长度
        返回空末页，超出长度明确失败。环境观察不进入事件数据库，不能通过此接口读取。
        """
        _identity(journal_id)
        _identity(record_id)
        if type(offset) is not int or not 0 <= offset < 2**63 - 1:
            raise ValueError("归档偏移必须为 SQLite 范围内的非负整数")
        if type(limit) is not int or not 1 <= limit <= 65536:
            raise ValueError("归档单页字符数必须在 1 到 65536 之间")
        db = self._connection()
        if db.execute("SELECT id FROM journal").fetchone()[0] != journal_id:
            raise CursorError("归档引用属于其他 world 数据库")
        row = db.execute(
            "SELECT sequence, source_id, message_id, received_at, length(payload) AS total_chars, substr(payload, ?, ?) AS text FROM events WHERE record_id=?",
            (offset + 1, limit, record_id),
        ).fetchone()
        if row is None:
            raise KeyError(record_id)
        if offset > row["total_chars"]:
            raise ValueError("归档偏移超出全文长度")
        return WorldContentPage(
            WorldPosition(journal_id, row["sequence"], record_id),
            row["source_id"],
            row["message_id"],
            row["received_at"],
            offset,
            row["text"],
            row["total_chars"],
        )

    def read(
        self, *, after: WorldPosition | None = None, source_id: str | None = None, limit: int = 100
    ) -> tuple[WorldRecord, ...]:
        """按数据库游标读取完整事件；近期视图裁剪与环境采样不改变消费位置。"""
        if after is not None and not isinstance(after, WorldPosition):
            raise TypeError("after 必须为 WorldPosition")
        if type(limit) is not int or limit < 1:
            raise ValueError("读取上限必须为正整数")
        if source_id is not None:
            _identity(source_id)
        db = self._connection()
        journal = db.execute("SELECT * FROM journal").fetchone()
        if after is not None:
            row = db.execute("SELECT record_id FROM events WHERE sequence=?", (after.sequence,)).fetchone()
            boundary = after.sequence == journal["pruned_through"] and after.record_id == journal["pruned_record_id"]
            if (
                after.journal_id != journal["id"]
                or after.sequence < journal["pruned_through"]
                or (not boundary and (row is None or row[0] != after.record_id))
            ):
                raise CursorError("世界读取位置与数据库不一致，请核对记录或恢复范围")
        sql = "SELECT * FROM events WHERE sequence > ?"
        params: list[object] = [0 if after is None else after.sequence]
        if source_id is not None:
            sql += " AND source_id = ?"
            params.append(source_id)
        return tuple(self._record(row) for row in db.execute(sql + " ORDER BY sequence LIMIT ?", (*params, limit)))

    def refresh(self) -> None:
        """按接收时间及完整条目预算重建文本视图，同时清理过期天气。"""
        db = self._connection()
        now = _timestamp(self.now())
        items, size = [], 0
        rows = db.execute(
            "SELECT sequence, record_id, source_id, message_id, received_at, substr(text,1,?) AS text, length(text) AS chars FROM events WHERE received_at > ? ORDER BY sequence DESC",
            (self.view.max_event_chars, now - self.view.recent_seconds),
        )
        for row in rows:
            abridged = row["chars"] > self.view.max_event_chars
            item = {key: row[key] for key in ("sequence", "record_id", "source_id", "message_id", "received_at")}
            item.update(text=row["text"], abridged=abridged)
            if abridged:
                item["text"] = "[超长事件，凭 record_id 查询完整内容] " + row["text"]
            items.append(item)
            size += len(encode_json(item))
            if size >= self.view.max_chars:
                break
        journal = db.execute("SELECT * FROM journal").fetchone()
        value = {
            "version": 3,
            "journal_id": journal["id"],
            "latest_sequence": journal["next_sequence"] - 1,
            "records": list(reversed(items)),
        }
        exists = bool(self.ctx.list(key=RECORDS, location={}))
        if (exists or value["latest_sequence"]) and (not exists or self.ctx.get(RECORDS) != value):
            self.ctx.set(RECORDS, value)
        for address in self.ctx.list(key=ENVIRONMENT):
            current = cast(dict, self.ctx.get(ENVIRONMENT, location=dict(address.location)))
            retained = self._retain_environment(current, now)
            if retained != current:
                self.ctx.set(ENVIRONMENT, retained, location=dict(address.location))

    def _retain_environment(self, value: dict, now: float) -> dict:
        items = value["records"]
        if value["kind"] == "weather":
            # 最新天气保留原始观测时间；稳定天气没有新消息时仍可查询最后已知状态。
            items = [item for item in items[:-1] if item["received_at"] > now - self.view.weather_seconds] + items[-1:]
        count = self.view.time_count if value["kind"] == "time" else self.view.weather_count
        return {**value, "records": items[-count:]}

    def _observe(self, source_id: str, message_id: str, payload: object, kind: str) -> WorldReceipt:
        location = {"source_id": source_id}
        value = (
            cast(dict, self.ctx.get(ENVIRONMENT, location=location))
            if self.ctx.list(key=ENVIRONMENT, location=location)
            else {"kind": kind, "journal_id": uuid4().hex, "next_sequence": 1, "records": []}
        )
        if value["kind"] != kind:
            raise ValueError("环境来源的呈现类型发生变化，请核对已有状态")
        duplicate = next((item for item in value["records"] if item["message_id"] == message_id), None)
        if duplicate is not None:
            if _content(duplicate["payload"]) != _content(payload):
                raise MessageConflictError("环境消息身份冲突")
            item = duplicate
        else:
            item = {
                "sequence": value["next_sequence"],
                "record_id": uuid4().hex,
                "source_id": source_id,
                "message_id": message_id,
                "received_at": _timestamp(self.now()),
                "payload": deepcopy(payload),
            }
            value = {**value, "next_sequence": value["next_sequence"] + 1, "records": [*value["records"], item]}
            self.ctx.set(ENVIRONMENT, self._retain_environment(value, self.now()), location=location)
        self.refresh()
        record = WorldRecord(
            WorldPosition(value["journal_id"], item["sequence"], item["record_id"]),
            item["record_id"],
            source_id,
            message_id,
            deepcopy(item["payload"]),
        )
        return WorldReceipt(record, duplicate is not None)

    def observations(self, *, source_id: str | None = None) -> tuple[WorldRecord, ...]:
        """读取当前环境观察；环境视图不作为可靠事件队列。"""
        self._check_owner()
        result = []
        for address in self.ctx.list(key=ENVIRONMENT, location=None if source_id is None else {"source_id": source_id}):
            value = cast(dict, self.ctx.get(ENVIRONMENT, location=dict(address.location)))
            for item in value["records"]:
                record = WorldRecord(
                    WorldPosition(value["journal_id"], item["sequence"], item["record_id"]),
                    item["record_id"],
                    item["source_id"],
                    item["message_id"],
                    item["payload"],
                )
                result.append((item["received_at"], record))
        return tuple(record for _, record in sorted(result, key=lambda pair: pair[0]))

    def component(
        self, hooks: HookConnections, *, instance_id: str = "aurora_world/records", depends_on: tuple[str, ...] = ()
    ) -> LifecycleComponent:
        self._check_owner()
        if self._connected:
            raise RuntimeError("世界记录生命周期已经连接")
        links = []
        try:
            for phase, method in ((PREPARE, self.prepare), (START, self.start), (STOP, self.stop), (CLEAN, self.clean)):
                entry = entry_from(method, provider="aurora_world")
                links.append(
                    hooks.connect(
                        phase, entry.id, slot_instance=instance_id, handler_instance=instance_id, target=method
                    )
                )
        except Exception:
            for link in links:
                hooks.disconnect(link)
            raise
        self._connected = True
        return LifecycleComponent(instance_id, depends_on=depends_on)

    @hook_handler("org.aurora.world:handlers/records/prepare", slot=PREPARE)
    def prepare(self) -> None:
        self.open()

    @hook_handler("org.aurora.world:handlers/records/start", slot=START)
    def start(self) -> None:
        self._connection()
        if self._worker is not None:
            raise RuntimeError("世界呈现任务已经启动")
        self._worker = asyncio.create_task(self._refresh_loop(), name="world-presentation")

    async def _refresh_loop(self) -> None:
        while True:
            await asyncio.sleep(self.view.refresh_seconds)
            try:
                self.refresh()
            except Exception:  # noqa: BLE001 - 呈现可从数据库重建，下一周期重试且不重放事件。
                self.last_error = "presentation_failed"
                logger.error("world 呈现刷新失败：presentation_failed")
            else:
                self.last_error = None

    @hook_handler("org.aurora.world:handlers/records/stop", slot=STOP)
    async def stop(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass
            self._worker = None

    @hook_handler("org.aurora.world:handlers/records/clean", slot=CLEAN)
    def clean(self) -> None:
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._check_owner()
        if self._worker is not None:
            raise RuntimeError("必须先停止 world 呈现任务")
        if self._db is not None:
            self._db.close()
            self._db = None
        self._closed = True
