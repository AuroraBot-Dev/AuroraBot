"""内容资源的版本、边界、并发发布和完整性行为。"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import TYPE_CHECKING

import pytest

from src.artifacts.files import file_chunks
from src.artifacts.store import FileArtifactStore
from src.contracts.artifact import MAX_ARTIFACT_CHUNK, ArtifactIntegrityError
from src.contracts.resource import ResourceKey, ResourceRef

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_KEY = ResourceKey.parse("lab:memory/dataset/episodes/training")


def test_versions_survive_restart_and_chunk_boundaries_preserve_exact_bytes(tmp_path: Path) -> None:
    """同名新版本不覆盖旧内容，UTF-8 字符也按原始字节分页。"""

    async def scenario() -> None:
        content = "真实的连续经历\n".encode() * 17
        store = FileArtifactStore(tmp_path)
        first = await store.put_stream(_KEY, (content[:7], b"", content[7:]), media_type="text/plain")
        assert first.ref.revision == hashlib.sha256(content).hexdigest()
        second = await store.put(_KEY, b"new")
        assert first.ref != second.ref
        restored = FileArtifactStore(tmp_path)
        assert await restored.stat(first.ref) == first
        offset = 0
        page_size = 5
        chunks = []
        while True:
            chunk = await restored.read(first.ref, offset=offset, limit=page_size)
            chunks.append(chunk.content)
            assert len(chunk.content) <= page_size
            offset = chunk.next_offset
            if not chunk.has_more:
                break
        assert b"".join(chunks) == content
        final = await restored.read(first.ref, offset=first.size)
        assert final.content == b"" and not final.has_more
        assert (await restored.read(second.ref)).content == b"new"

    asyncio.run(scenario())


def test_concurrent_publishers_share_bytes_and_cannot_rebind_metadata(tmp_path: Path) -> None:
    """相同字节可跨命名空间复用，同一版本的元信息由首先发布者确定。"""

    async def scenario() -> None:
        stores = (FileArtifactStore(tmp_path), FileArtifactStore(tmp_path))
        results = await asyncio.gather(*(store.put(_KEY, b"stable") for store in stores))
        assert results[0] == results[1]
        other = await stores[0].put(ResourceKey.parse("other:models/weights/gru"), b"stable")
        assert other.ref.key != results[0].ref.key
        assert other.ref.revision == results[0].ref.revision
        assert len(tuple((tmp_path / "objects").rglob(other.ref.revision or ""))) == 1
        with pytest.raises(ValueError, match="其他资源元信息"):
            await stores[1].put(_KEY, b"stable", media_type="text/plain")
        assert await stores[0].stat(results[0].ref) == results[0]
        assert not tuple((tmp_path / "temporary").iterdir())

    asyncio.run(scenario())


def test_empty_content_and_file_import_have_stable_versions(tmp_path: Path) -> None:
    """空资源可读取，文件导入也遵循同一内容寻址规则。"""

    async def scenario() -> None:
        source = tmp_path / "source.pt"
        source.write_bytes(b"weights\x00\xff")
        store = FileArtifactStore(tmp_path / "store")
        empty = await store.put_stream(_KEY, ())
        assert empty.size == 0
        assert not (await store.read(empty.ref)).has_more
        imported = await store.import_file(_KEY, source)
        assert imported == await store.put(_KEY, source.read_bytes())
        assert (await store.read(imported.ref)).content == source.read_bytes()

    asyncio.run(scenario())


def test_failed_stream_does_not_publish_partial_content(tmp_path: Path) -> None:
    """生产者中断后，不能通过原名称看到半份文件。"""

    def broken() -> Iterator[bytes]:
        """模拟数据导出写出一段后失败。"""
        yield b"partial"
        raise ValueError("导出中断")

    async def scenario() -> None:
        store = FileArtifactStore(tmp_path)
        with pytest.raises(ValueError, match="导出中断"):
            await store.put_stream(_KEY, broken())
        assert not tuple((tmp_path / "temporary").iterdir())
        assert not (tmp_path / "bindings").exists()
        ref = ResourceRef(_KEY, hashlib.sha256(b"partial").hexdigest())
        with pytest.raises(LookupError, match="不存在"):
            await store.stat(ref)

    asyncio.run(scenario())


def test_import_rejects_changes_to_the_open_source(tmp_path: Path) -> None:
    """变动检查针对打开的文件，而非事后随意选取的新路径。"""
    source = tmp_path / "source"
    source.write_bytes(b"before")
    chunks = file_chunks(source)
    assert next(chunks) == b"before"
    source.write_bytes(b"changed")
    with pytest.raises(ValueError, match="发生变化"):
        tuple(chunks)


@pytest.mark.parametrize("offset,limit", [(-1, 1), (0, 0), (0, MAX_ARTIFACT_CHUNK + 1), (True, 1), (0, False)])
def test_read_requires_explicit_bounded_integer_ranges(tmp_path: Path, offset: int, limit: int) -> None:
    """不合法的区间不能触发无界读取。"""

    async def scenario() -> None:
        store = FileArtifactStore(tmp_path)
        info = await store.put(_KEY, b"abc")
        with pytest.raises(ValueError, match="字节上限"):
            await store.read(info.ref, offset=offset, limit=limit)
        with pytest.raises(ValueError, match="超出"):
            await store.read(info.ref, offset=info.size + 1)

    asyncio.run(scenario())


@pytest.mark.parametrize("cached", [False, True])
def test_corruption_outside_requested_range_is_detected(tmp_path: Path, *, cached: bool) -> None:
    """不能只核对所读分块，也不能在文件变更后沿用摘要缓存。"""

    async def scenario() -> None:
        store = FileArtifactStore(tmp_path)
        info = await store.put(_KEY, b"head and tail")
        reader = store if cached else FileArtifactStore(tmp_path)
        object_path = next((tmp_path / "objects").rglob(info.ref.revision or ""))
        object_path.write_bytes(b"head and fail")
        with pytest.raises(ArtifactIntegrityError, match="摘要"):
            await reader.read(info.ref, limit=4)
        with pytest.raises(ArtifactIntegrityError):
            await reader.put(_KEY, b"head and tail")
        object_path.write_bytes(b"short")
        with pytest.raises(ArtifactIntegrityError, match="大小"):
            await reader.stat(info.ref)
        object_path.unlink()
        with pytest.raises(ArtifactIntegrityError, match="缺失"):
            await reader.read(info.ref)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "replacement",
    [{"size": True}, {"size": -1}, {"media_type": None}, {"key": "other"}, {"schema_version": 2}],
)
def test_corrupt_manifests_are_rejected(tmp_path: Path, replacement: dict[str, object]) -> None:
    """绑定不能重新解释内容大小、资源身份或协议版本。"""

    async def scenario() -> None:
        store = FileArtifactStore(tmp_path)
        info = await store.put(_KEY, b"abc")
        manifest = next((tmp_path / "bindings").rglob("*.json"))
        data = json.loads(manifest.read_bytes())
        manifest.write_text(json.dumps(data | replacement), encoding="utf-8")
        with pytest.raises(ArtifactIntegrityError, match="绑定已损坏"):
            await store.stat(info.ref)

    asyncio.run(scenario())


@pytest.mark.parametrize("revision", [None, "../outside", "a" * 63, "A" * 64])
def test_reads_never_interpret_revision_as_a_backend_path(tmp_path: Path, revision: str | None) -> None:
    """名称与版本仅用于逻辑寻址，不直接插入任意文件路径。"""

    async def scenario() -> None:
        store = FileArtifactStore(tmp_path)
        with pytest.raises(ValueError, match="SHA256"):
            await store.stat(ResourceRef(_KEY, revision))

    asyncio.run(scenario())


@pytest.mark.parametrize("long_field", ["key", "media_type"])
def test_oversized_manifest_is_rejected_before_any_resource_is_published(tmp_path: Path, long_field: str) -> None:
    """写入成功必须意味着元信息能按同一读取上限恢复，不能发布不可读版本。"""

    async def scenario() -> None:
        store = FileArtifactStore(tmp_path)
        key = ResourceKey("lab", "memory", "dataset", "x" * 20000) if long_field == "key" else _KEY
        media_type = "x" * 20000 if long_field == "media_type" else "text/plain"
        with pytest.raises(ValueError, match="清单大小上限"):
            await store.put(key, b"stable", media_type=media_type)
        assert not (tmp_path / "objects").exists()
        assert not (tmp_path / "bindings").exists()
        assert not tuple((tmp_path / "temporary").iterdir())

    asyncio.run(scenario())
