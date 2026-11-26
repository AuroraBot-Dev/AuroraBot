"""记忆事务、索引失效与并发取消；检索排序使用可控向量，不调用真实模型。"""

import asyncio
import json

import pytest
from aurora_adapter.model import ModelError
from aurora_agent.tools import ToolExecutionError
from aurora_bot.memory.store import MemoryStore


class Embeddings:
    def __init__(self):
        self.entered = asyncio.Event()
        self.release = None
        self.error = None

    async def embed(self, texts):
        self.entered.set()
        if self.release is not None:
            await self.release.wait()
        if self.error is not None:
            raise self.error
        return [[1.0, 0.0] if "茶" in text or "饮料" in text else [0.0, 1.0] for text in texts]

    async def aclose(self):
        pass


def store(path, client, *, owner="bot", fingerprint="model-v1", chunk_chars=800, overlap_chars=120):
    return MemoryStore(
        path,
        owner,
        client=client,
        fingerprint=fingerprint,
        chunk_chars=chunk_chars,
        overlap_chars=overlap_chars,
    )


def test_compaction_queue_migrates_preserves_sources_and_never_resurrects_deleted_memory(tmp_path):
    async def scenario():
        path, client = tmp_path / "memory.db", Embeddings()
        current = store(path, client)
        original = await current.write("manual", "喜欢茶", "用户", "")
        current.db.execute("DROP TABLE compactions")
        current.db.execute("PRAGMA user_version = 1")
        current.close()
        current, other = store(path, client), store(path, client, owner="other")
        record = {
            "run_id": "task",
            "start": 0,
            "end": 1,
            "digest": "a" * 64,
            "messages": [{"role": "user", "content": "喜欢茶"}],
            "previous_summary": "",
        }
        try:
            assert current.read("manual") == original
            current.archive(record)
            current.queue_summary(record["digest"], "喜欢茶，待确认饮料")
            assert json.loads(current.pending_compactions()[0]["record"]) == record
            assert not other.pending_compactions()
            assert (await current.search("饮料"))["pending_index_count"] == 1
            client.error = ModelError("离线")
            with pytest.raises(ModelError):
                await current.index_compaction(current.pending_compactions()[0])
            current.close()
            current = store(path, client)
            client.error = None
            await current.index_compaction(current.pending_compactions()[0])
            identity = "auto_" + "a" * 59
            indexed = current.read(identity)
            assert "run_id=task" in indexed["source"]
            current.delete(identity, indexed["revision"])
            current.archive(record)
            current.queue_summary(record["digest"], "不得复活")
            assert not current.pending_compactions()
            assert (await current.search("饮料"))["items"][0]["memory_id"] == "manual"
            with pytest.raises(ToolExecutionError, match="没有这条记忆"):
                current.read(identity)
        finally:
            current.close()
            other.close()

    asyncio.run(scenario())


def test_persistent_semantic_search_revision_delete_and_instance_isolation(tmp_path):
    async def scenario():
        path, client = tmp_path / "memory.db", Embeddings()
        first = store(path, client)
        original = await first.write("preference", "喜欢茶", "用户明确告知", "")
        await first.write("unrelated", "周末爬山", "对话", "")
        first.close()
        restored, other = store(path, client), store(path, client, owner="other")
        try:
            found = (await restored.search("饮料", top_k=1))["items"]
            assert len(found) == 1 and found[0]["memory_id"] == "preference"
            assert found[0]["source"] == "用户明确告知" and found[0]["revision"] == original["revision"]
            assert await other.search("饮料") == {"items": []}
            with pytest.raises(ToolExecutionError, match="没有这条记忆"):
                other.read("preference")
            changed = await restored.write("preference", "改喝咖啡", "用户更正", original["revision"])
            assert changed["revision"] != original["revision"] and changed["created_at"] == original["created_at"]
            assert await restored.search("饮料") == {"items": []}
            with pytest.raises(ToolExecutionError, match="版本已变化"):
                restored.delete("preference", original["revision"])
            restored.delete("preference", changed["revision"])
            assert all(item["memory_id"] != "preference" for item in (await restored.search("咖啡"))["items"])
            recreated = await restored.write("preference", "喜欢茶", "用户重建", "")
            with pytest.raises(ToolExecutionError, match="版本已变化"):
                await restored.write("preference", "过期更新", "旧调用", original["revision"])
            assert restored.read("preference") == recreated
        finally:
            restored.close()
            other.close()

    asyncio.run(scenario())


def test_chunk_sources_and_explicit_reindex_preserve_original(tmp_path):
    async def scenario():
        path, client = tmp_path / "memory.db", Embeddings()
        old = store(path, client, chunk_chars=6, overlap_chars=2)
        text = "去爬山去爬山喜欢茶喜欢茶"
        original = await old.write("long", text, "用户", "")
        chunks = (await old.search("饮料", top_k=10, min_score=-1))["items"]
        assert {item["text"] for item in chunks} == {text[0:6], text[4:10], text[8:12]}
        assert all(item["text"] == text[item["start"] : item["end"]] for item in chunks)
        old.close()
        new = store(path, client, fingerprint="model-v2", chunk_chars=12, overlap_chars=0)
        try:
            with pytest.raises(ToolExecutionError, match="显式调用 memory_reindex"):
                await new.search("饮料")
            assert new.read("long") == original
            assert await new.reindex() == {"indexed": 1}
            found = (await new.search("饮料"))["items"]
            assert len(found) == 1 and found[0]["text"] == text and found[0]["revision"] == original["revision"]
        finally:
            new.close()

    asyncio.run(scenario())


def test_failed_cancelled_and_conflicting_embeddings_never_overwrite_committed_memory(tmp_path):
    async def scenario():
        client = Embeddings()
        current = store(tmp_path / "memory.db", client)
        concurrent = store(tmp_path / "memory.db", Embeddings())
        try:
            original = await current.write("pref", "喜欢茶", "用户", "")
            client.error = ModelError("模拟供应商失败")
            with pytest.raises(ModelError):
                await current.write("pref", "不完整写入", "用户", original["revision"])
            assert current.read("pref") == original
            client.error = None
            client.release = asyncio.Event()
            client.entered.clear()
            pending = asyncio.create_task(current.write("pref", "被取消的写入", "用户", original["revision"]))
            await client.entered.wait()
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            assert current.read("pref") == original
            client.entered.clear()
            pending = asyncio.create_task(current.write("pref", "较慢的写入", "用户", original["revision"]))
            await client.entered.wait()
            winner = await concurrent.write("pref", "最新偏好", "用户", original["revision"])
            client.release.set()
            with pytest.raises(ToolExecutionError, match="版本已变化"):
                await pending
            assert current.read("pref") == winner
            client.release = asyncio.Event()
            client.entered.clear()
            rebuild = asyncio.create_task(current.reindex())
            await client.entered.wait()
            concurrent.delete("pref", winner["revision"])
            client.release.set()
            with pytest.raises(ToolExecutionError, match="重建期间"):
                await rebuild
            assert await current.search("饮料") == {"items": []}
        finally:
            current.close()
            concurrent.close()

    asyncio.run(scenario())
