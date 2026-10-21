"""已发布内容版本的发现有界、可恢复，元信息不冒充正文完整性证明。"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from aurora_bot.artifacts.store import FileArtifactStore
from aurora_bot.contracts.artifact import ArtifactIntegrityError
from aurora_bot.contracts.resource import ResourceKey
from aurora_bot.contracts.resource_query import MAX_RESOURCE_PAGE, ResourceQuery

if TYPE_CHECKING:
    from pathlib import Path


_MAX_EXPECTED_CURSOR = 512
_KEY = ResourceKey.parse("lab:memory/dataset/episodes")


def test_discovery_pages_all_versions_and_shared_content_after_restart(tmp_path: Path) -> None:
    """共享字节不合并不同逻辑名称，同名版本不隐式选取最新值。"""

    async def scenario() -> None:
        """每页只容纳一项，多次继续应完整且不重复。"""
        store = FileArtifactStore(tmp_path)
        expected = (
            await store.put(_KEY, b"one"),
            await store.put(_KEY, b"two"),
            await store.put(ResourceKey.parse("other:rhythm/model/gru"), b"one"),
            await store.put(ResourceKey.parse("lab:memory/model/tgn"), b"weights"),
        )
        reader = FileArtifactStore(tmp_path)
        found = []
        query = ResourceQuery(limit=1)
        while True:
            page = await reader.find(query)
            assert len(page.items) == 1
            found.extend(page.items)
            if page.next_cursor is None:
                break
            query = replace(query, after=page.next_cursor)
        assert len(found) == len(set(found)) == len(expected)
        assert set(found) == set(expected)
        selected = await reader.find(ResourceQuery(namespace="lab", domain="memory", kind="dataset"))
        assert set(selected.items) == set(expected[:2])
        assert selected.next_cursor is None
        assert (await reader.find(ResourceQuery(namespace="missing"))).items == ()

    asyncio.run(scenario())


def test_listing_reads_no_content_and_does_not_certify_missing_bytes(tmp_path: Path) -> None:
    """缺失正文不抹掉已发布身份，调用者仍须通过 stat 或 read 验证内容。"""

    async def scenario() -> None:
        """完整性验证失败不能把元信息发现误记为已经读过正文。"""
        store = FileArtifactStore(tmp_path)
        info = await store.put(_KEY, b"source")
        for path in (tmp_path / "objects").rglob(info.ref.revision or ""):
            path.unlink()
        page = await store.find(ResourceQuery())
        assert page.items == (info,)
        with pytest.raises(ArtifactIntegrityError, match="缺失"):
            await store.stat(info.ref)

    asyncio.run(scenario())


def test_cursor_is_bounded_for_long_resource_names_and_rejects_other_filters(tmp_path: Path) -> None:
    """固定长度游标不会复制很长的资源路径，也不接受跨查询继续。"""

    async def scenario() -> None:
        """同名多版本保证出现续页，重新打开存储仍可使用游标。"""
        store = FileArtifactStore(tmp_path)
        key = replace(_KEY, path="x" * 10000)
        await store.put(key, b"one")
        await store.put(key, b"two")
        page = await store.find(ResourceQuery(limit=1))
        assert page.next_cursor is not None
        assert len(page.next_cursor) < _MAX_EXPECTED_CURSOR
        continued = await FileArtifactStore(tmp_path).find(ResourceQuery(limit=2, after=page.next_cursor))
        assert len(continued.items) == 1
        assert continued.items[0] != page.items[0]
        with pytest.raises(ValueError, match="当前筛选"):
            await store.find(ResourceQuery(namespace="lab", after=page.next_cursor))

    asyncio.run(scenario())


@pytest.mark.parametrize("token", ["?", "中文", "e30=", "W10=", "bnVsbA=="])
def test_malformed_cursors_fail_without_reading_storage(tmp_path: Path, token: str) -> None:
    """游标结构或编码错误不能变成空列表或重新开始。"""
    with pytest.raises(ValueError, match="游标无效"):
        asyncio.run(FileArtifactStore(tmp_path).find(ResourceQuery(after=token)))


@pytest.mark.parametrize("replacement", [{"key": "bad"}, {"schema_version": True}, {"size": -1}])
def test_listing_rejects_corrupt_metadata_even_without_content_reads(
    tmp_path: Path, replacement: dict[str, object]
) -> None:
    """发现仍校验清单结构，不把损坏元信息呈现为有效身份。"""

    async def scenario() -> None:
        """直接损坏清单后，发现和读取遵循同一结构约束。"""
        store = FileArtifactStore(tmp_path)
        await store.put(_KEY, b"source")
        manifest = next((tmp_path / "bindings").rglob("*.json"))
        manifest.write_text(json.dumps(json.loads(manifest.read_bytes()) | replacement), encoding="utf-8")
        with pytest.raises(ArtifactIntegrityError, match="绑定已损坏"):
            await store.find(ResourceQuery())

    asyncio.run(scenario())


def test_listing_rejects_binding_moved_to_another_resource_identity(tmp_path: Path) -> None:
    """清单自身合法仍不能伪装成其他逻辑身份的绑定。"""

    async def scenario() -> None:
        """目录名与摘要不一致必须显式报错。"""
        store = FileArtifactStore(tmp_path)
        await store.put(_KEY, b"source")
        manifest = next((tmp_path / "bindings").rglob("*.json"))
        manifest.rename(manifest.with_name("0" * 64 + ".json"))
        with pytest.raises(ArtifactIntegrityError, match="位置"):
            await store.find(ResourceQuery())

    asyncio.run(scenario())


def test_live_listing_can_see_new_entries_after_the_cursor(tmp_path: Path) -> None:
    """分页扫描当前目录，不宣称固定时间快照；新增靠前内容需重新发现。"""

    async def scenario() -> None:
        """新名称按摘要排序，继续读取可看到位于游标之后的发布。"""
        store = FileArtifactStore(tmp_path)
        first = await store.put(_KEY, b"one")
        await store.put(_KEY, b"two")
        page = await store.find(ResourceQuery(limit=1))
        after = hashlib.sha256(str(first.ref.key).encode()).hexdigest()
        key = next(
            ResourceKey("lab", "memory", "dataset", f"added-{index}")
            for index in range(1000)
            if hashlib.sha256(f"lab:memory/dataset/added-{index}".encode()).hexdigest() > after
        )
        added = await store.put(key, b"new")
        continued = await store.find(ResourceQuery(after=page.next_cursor))
        assert added in continued.items

    asyncio.run(scenario())


def test_empty_listing_has_no_filesystem_side_effects(tmp_path: Path) -> None:
    """发现尚未使用的存储不会创建目录。"""
    directory = tmp_path / "unused"
    page = asyncio.run(FileArtifactStore(directory).find(ResourceQuery()))
    assert page.items == ()
    assert page.next_cursor is None
    assert not directory.exists()


@pytest.mark.parametrize("limit", [0, -1, MAX_RESOURCE_PAGE + 1, True])
def test_resource_discovery_requires_a_bounded_page(limit: int) -> None:
    """无界或布尔型数量不被视为有效分页参数。"""
    with pytest.raises(ValueError, match="分页上限"):
        ResourceQuery(limit=limit)
