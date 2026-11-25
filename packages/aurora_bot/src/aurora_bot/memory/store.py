"""实例隔离的文本记忆与可重建向量索引；SQLite 事务提交原文及对应索引。"""

import json
import sqlite3
from pathlib import Path
from time import time
from uuid import uuid4

from aurora_adapter.model import EmbeddingClient, normalize_vectors
from aurora_agent.compaction import CompactionRecord
from aurora_agent.tools import ToolExecutionError
from aurora_core.json_data import encode_json

MAX_MEMORIES = 1000


class MemoryStore:
    """有界语料的精确余弦检索；网络等待期间不持有写事务，提交前复查版本。"""

    def __init__(
        self,
        path: Path,
        owner: str,
        *,
        client: EmbeddingClient | None,
        fingerprint: str,
        chunk_chars: int = 800,
        overlap_chars: int = 120,
    ) -> None:
        if not owner or not 0 <= overlap_chars < chunk_chars:
            raise ValueError("记忆所有者及分块参数无效")
        self.owner, self.client, self.fingerprint = owner, client, fingerprint
        self.chunk_chars, self.overlap_chars = chunk_chars, overlap_chars
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        try:
            version = self.db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2):
                raise ValueError("不支持的记忆数据库版本")
            with self.db:
                self.db.execute(
                    "CREATE TABLE IF NOT EXISTS memories ("
                    "owner TEXT NOT NULL, memory_id TEXT NOT NULL, revision TEXT NOT NULL, "
                    "text TEXT NOT NULL, source TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL, "
                    "fingerprint TEXT NOT NULL, vectors TEXT NOT NULL, PRIMARY KEY(owner, memory_id))"
                )
                self.db.execute(
                    "CREATE TABLE IF NOT EXISTS compactions ("
                    "owner TEXT NOT NULL, digest TEXT NOT NULL, record TEXT NOT NULL, summary TEXT, "
                    "status TEXT NOT NULL, updated_at REAL NOT NULL, PRIMARY KEY(owner, digest))"
                )
                self.db.execute("PRAGMA user_version = 2")
        except BaseException:
            self.db.close()
            raise

    def _rows(self) -> list[dict]:
        return [
            dict(row)
            for row in self.db.execute("SELECT * FROM memories WHERE owner = ? ORDER BY memory_id", (self.owner,))
        ]

    def archive(self, record: CompactionRecord) -> None:
        """先提交原始材料；同一历史前缀重复压缩不重复入库。"""
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO compactions VALUES (?, ?, ?, NULL, 'archived', ?)",
                (self.owner, record["digest"], encode_json(record), time()),
            )

    def queue_summary(self, digest: str, text: str) -> None:
        with self.db:
            self.db.execute(
                "UPDATE compactions SET summary = ?, status = 'pending', updated_at = ? "
                "WHERE owner = ? AND digest = ? AND status = 'archived'",
                (text, time(), self.owner, digest),
            )

    def pending_compactions(self, limit: int = 16) -> list[dict]:
        return [
            dict(row)
            for row in self.db.execute(
                "SELECT * FROM compactions WHERE owner = ? AND status = 'pending' ORDER BY updated_at, digest LIMIT ?",
                (self.owner, limit),
            )
        ]

    def defer_compaction(self, digest: str) -> None:
        """失败记录移到队尾，避免阻塞其他待索引摘要。"""
        with self.db:
            self.db.execute(
                "UPDATE compactions SET updated_at = ? WHERE owner = ? AND digest = ?", (time(), self.owner, digest)
            )

    async def index_compaction(self, job: dict) -> None:
        """索引成功后原子发布记忆并确认队列；已发布记录的删除和编辑不会被重放覆盖。"""
        vectors = await self._index(job["summary"])
        memory_id = "auto_" + job["digest"][:59]
        self.db.execute("BEGIN IMMEDIATE")
        with self.db:
            row = self.db.execute(
                "SELECT status FROM compactions WHERE owner = ? AND digest = ?", (self.owner, job["digest"])
            ).fetchone()
            if row is None or row["status"] != "pending":
                return
            if self._row(memory_id) is not None:
                self.db.execute(
                    "UPDATE compactions SET status = 'conflict' WHERE owner = ? AND digest = ?",
                    (self.owner, job["digest"]),
                )
                return
            self._capacity(None)
            record = json.loads(job["record"])
            now = time()
            source = f"上下文压缩摘要；run_id={record['run_id']}；messages={record['start']}:{record['end']}；digest={job['digest']}"
            self.db.execute(
                "INSERT INTO memories VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (self.owner, memory_id, uuid4().hex, job["summary"], source, now, now, self.fingerprint, vectors),
            )
            self.db.execute(
                "UPDATE compactions SET status = 'indexed', updated_at = ? WHERE owner = ? AND digest = ?",
                (now, self.owner, job["digest"]),
            )

    def _search_result(self, items: list) -> dict:
        pending = self.db.execute(
            "SELECT count(*) FROM compactions WHERE owner = ? AND status = 'pending'", (self.owner,)
        ).fetchone()[0]
        return {"items": items, **({"pending_index_count": pending} if pending else {})}

    def _row(self, memory_id: str) -> dict | None:
        row = self.db.execute(
            "SELECT * FROM memories WHERE owner = ? AND memory_id = ?", (self.owner, memory_id)
        ).fetchone()
        return None if row is None else dict(row)

    @staticmethod
    def _public(row: dict) -> dict:
        return {key: row[key] for key in ("memory_id", "revision", "text", "source", "created_at", "updated_at")}

    def read(self, memory_id: str) -> dict:
        row = self._row(memory_id)
        if row is None:
            raise ToolExecutionError("memory_not_found", "当前实例没有这条记忆")
        return self._public(row)

    def _check_revision(self, memory_id: str, expected_revision: str) -> dict | None:
        row = self._row(memory_id)
        actual = "" if row is None else row["revision"]
        if actual != expected_revision:
            raise ToolExecutionError("memory_conflict", "记忆版本已变化，请重新读取后操作", value={"revision": actual})
        return row

    def _chunks(self, text: str) -> list[tuple[int, int]]:
        result = []
        start = 0
        while start < len(text):
            end = min(start + self.chunk_chars, len(text))
            if text[start:end].strip():
                result.append((start, end))
            if end == len(text):
                break
            start = end - self.overlap_chars
        return result

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        if self.client is None:
            raise RuntimeError("当前记忆工具没有向量客户端")
        vectors = []
        for start in range(0, len(texts), 32):
            batch = texts[start : start + 32]
            vectors.extend(normalize_vectors(await self.client.embed(batch), len(batch)))
        return normalize_vectors(vectors, len(texts))

    async def _index(self, text: str) -> str:
        vectors = await self._embed([text[start:end] for start, end in self._chunks(text)])
        return json.dumps(vectors, allow_nan=False, separators=(",", ":"))

    def _capacity(self, previous: dict | None) -> None:
        count = self.db.execute("SELECT count(*) FROM memories WHERE owner = ?", (self.owner,)).fetchone()[0]
        if previous is None and count >= MAX_MEMORIES:
            raise ToolExecutionError("memory_full", "记忆容量已满，请删除不再需要的记忆")

    async def write(self, memory_id: str, text: str, source: str, expected_revision: str) -> dict:
        if not text.strip():
            raise ValueError("记忆正文不能为空")
        self._capacity(self._check_revision(memory_id, expected_revision))
        vectors = await self._index(text)
        self.db.execute("BEGIN IMMEDIATE")
        with self.db:
            previous = self._check_revision(memory_id, expected_revision)
            self._capacity(previous)
            now = max(time(), previous["updated_at"] if previous else 0)
            row = {
                "memory_id": memory_id,
                "revision": uuid4().hex,
                "text": text,
                "source": source,
                "created_at": now if previous is None else previous["created_at"],
                "updated_at": now,
            }
            self.db.execute(
                "INSERT OR REPLACE INTO memories VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (self.owner, *row.values(), self.fingerprint, vectors),
            )
        return row

    def delete(self, memory_id: str, expected_revision: str) -> dict:
        self.db.execute("BEGIN IMMEDIATE")
        with self.db:
            previous = self._check_revision(memory_id, expected_revision)
            if previous is None:
                raise ToolExecutionError("memory_not_found", "当前实例没有这条记忆")
            self.db.execute("DELETE FROM memories WHERE owner = ? AND memory_id = ?", (self.owner, memory_id))
        return {"memory_id": memory_id, "deleted": True}

    def _check_index(self, rows: list[dict]) -> None:
        if any(row["fingerprint"] != self.fingerprint for row in rows):
            raise ToolExecutionError(
                "memory_index_mismatch", "记忆索引配置已变化，请显式调用 memory_reindex 重建后再搜索"
            )

    async def search(self, query: str, top_k: int = 5, min_score: float = 0.3) -> dict:
        rows = self._rows()
        if not rows:
            return self._search_result([])
        self._check_index(rows)
        vector = (await self._embed([query]))[0]
        rows = self._rows()
        self._check_index(rows)
        matches = []
        for row in rows:
            chunks = self._chunks(row["text"])
            vectors = normalize_vectors(json.loads(row["vectors"]), len(chunks))
            for index, ((start, end), candidate) in enumerate(zip(chunks, vectors, strict=True)):
                if len(candidate) != len(vector):
                    raise ToolExecutionError("memory_index_mismatch", "向量维数已变化，请调用 memory_reindex 重建索引")
                score = max(-1.0, min(1.0, sum(a * b for a, b in zip(vector, candidate, strict=True))))
                if score >= min_score:
                    matches.append(
                        {
                            "memory_id": row["memory_id"],
                            "revision": row["revision"],
                            "source": row["source"],
                            "updated_at": row["updated_at"],
                            "chunk": index,
                            "start": start,
                            "end": end,
                            "text": row["text"][start:end],
                            "score": score,
                        }
                    )
        matches.sort(key=lambda item: (-item["score"], item["memory_id"], item["chunk"]))
        return self._search_result(matches[:top_k])

    async def reindex(self) -> dict:
        """显式重建当前实例全部索引；失败、取消或语料变化时保留原索引。"""
        rows = self._rows()
        indexed = [(await self._index(row["text"]), row["memory_id"]) for row in rows]
        self.db.execute("BEGIN IMMEDIATE")
        with self.db:
            if [(r["memory_id"], r["revision"]) for r in rows] != [
                (r["memory_id"], r["revision"]) for r in self._rows()
            ]:
                raise ToolExecutionError("memory_conflict", "重建期间记忆已变化，请重新发起重建")
            self.db.executemany(
                "UPDATE memories SET vectors = ?, fingerprint = ? WHERE owner = ? AND memory_id = ?",
                [(vectors, self.fingerprint, self.owner, memory_id) for vectors, memory_id in indexed],
            )
        return {"indexed": len(rows)}

    def close(self) -> None:
        self.db.close()
