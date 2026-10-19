"""实例发现和固定版本检查必须以真实世界事实为依据。"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from src.artifacts.provider import ArtifactProvider
from src.artifacts.store import FileArtifactStore
from src.contracts.process import DEFAULT_TREE_PROCESS
from src.contracts.resource import ResourceInstance, ResourceKey, ResourceRef
from src.contracts.resource_codec import resource_instance_data, resource_ref_data
from src.contracts.resource_query import ResourceQuery
from src.contracts.tree_lifecycle import TREE_COMPLETED, TREE_FAILED, TREE_STARTED, tree_scope
from src.contracts.world import WorldCommitInput, WorldFrontier
from src.instances.provider import InstanceProvider
from src.resources.catalog import ResourceCatalog
from src.world import SqlAlchemyWorldJournal

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from src.contracts.world import WorldStreamPage

_BOT = "aurora:bot/default"


@asynccontextmanager
async def _journal(tmp_path: Path) -> AsyncIterator[SqlAlchemyWorldJournal]:
    """每个场景使用真实临时世界库，并在同一事件循环关闭。"""
    world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
    try:
        await world.initialize()
        yield world
    finally:
        await world.close()


def _start(tree_id: str, bot_id: str = _BOT) -> WorldCommitInput:
    """使用生产开始事实的完整身份和过程版本。"""
    instance = ResourceInstance(tree_id, bot_id, DEFAULT_TREE_PROCESS.ref)
    return WorldCommitInput(
        f"{tree_id}:tree:started",
        TREE_STARTED,
        "engine",
        "开始认知",
        frozenset({tree_scope(tree_id)}),
        WorldFrontier(),
        {
            "tree_id": tree_id,
            "bot_id": bot_id,
            "instance": resource_instance_data(instance),
            "process_ref": resource_ref_data(instance.definition),
        },
    )


def _fact(tree_id: str, suffix: str, *, kind: str = "test.observed", source: str = "test") -> WorldCommitInput:
    """追加归属明确的事实，提交后由世界分配真实游标。"""
    return WorldCommitInput(
        f"{tree_id}:{suffix}",
        kind,
        source,
        "实例经历",
        frozenset({tree_scope(tree_id)}),
        WorldFrontier(),
        {"tree_id": tree_id},
    )


def test_instance_discovery_pages_all_owned_starts_and_ignores_decorative_tree_ids(tmp_path: Path) -> None:
    """跨过世界页和旧摘要的数量上限，普通 payload 不能冒充实例。"""

    async def scenario() -> None:
        """统一目录合并来源后，续页仍不遗漏或重复任何真实实例。"""
        async with _journal(tmp_path) as world:
            count = 107
            inputs = (
                *(_start(f"tree:{index}") for index in range(count)),
                *(_fact(f"noise-{index}", "observed") for index in range(160)),
                _start("foreign", "aurora:bot/other"),
                replace(_start("forged"), source="application"),
                replace(_start("wrong-scope"), scopes=frozenset({"aurora:world/test"})),
                replace(_start("wrong-id"), commit_id="decorative-start"),
                replace(_start("legacy"), data={"tree_id": "legacy", "bot_id": _BOT}),
            )
            await world.append_commits(inputs)
            catalog = ResourceCatalog(providers=(InstanceProvider(world, _BOT),))
            found = []
            after = None
            limit = 17
            while True:
                page = await catalog.browse(ResourceQuery(domain="engine", kind="instance", limit=limit, after=after))
                found.extend(page.items)
                if page.next_cursor is None:
                    break
                assert len(page.items) == limit
                after = page.next_cursor
            assert len(found) == count
            assert {item.metadata["instance"]["instance_id"] for item in found} == {f"tree:{i}" for i in range(count)}
            for item in found:
                assert await catalog.inspect(item.ref) == item
            assert (await catalog.browse(ResourceQuery(namespace="missing", kind="instance"))).items == ()
            assert (await catalog.browse(ResourceQuery(domain="memory"))).items == ()

    asyncio.run(scenario())


@pytest.mark.parametrize("terminal", ["completed", "failed"])
def test_historical_instance_views_remain_exact_across_long_scopes(tmp_path: Path, terminal: str) -> None:
    """历史检查跨世界正文页恢复，不使用当前摘要替换旧版本。"""

    async def scenario() -> None:
        """事实时间无关，只有实例所属提交的精确游标能形成状态版本。"""
        async with _journal(tmp_path) as world:
            tree_id = "森林/树:一"
            before = (await world.append_commits((_fact(tree_id, "before-start"),)))[0]
            started = (await world.append_commits((_start(tree_id),)))[0]
            provider = InstanceProvider(world, _BOT)
            catalog = ResourceCatalog(providers=(provider,))
            first = (await catalog.browse(ResourceQuery(kind="instance"))).items[0]
            assert first.metadata["commit_count"] == 1
            events = await world.append_commits(tuple(_fact(tree_id, f"step-{i}") for i in range(270)))
            unrelated = (await world.append_commits((_fact("other", "unrelated"),)))[0]
            kind = TREE_COMPLETED if terminal == "completed" else TREE_FAILED
            opposite = "failed" if terminal == "completed" else "completed"
            opposite_kind = TREE_FAILED if terminal == "completed" else TREE_COMPLETED
            await world.append_commits((_fact(tree_id, f"tree:{opposite}", kind=opposite_kind, source="application"),))
            assert (await catalog.browse(ResourceQuery(kind="instance"))).items[0].metadata["state"] == "started"
            ending = _fact(tree_id, "wrong-end-id", kind=kind, source="engine")
            await world.append_commits((ending,))
            assert (await catalog.browse(ResourceQuery(kind="instance"))).items[0].metadata["state"] == "started"
            last = (await world.append_commits((_fact(tree_id, f"tree:{terminal}", kind=kind, source="engine"),)))[0]
            latest = (await catalog.browse(ResourceQuery(kind="instance"))).items[0]
            assert latest.metadata["state"] == terminal
            assert latest.metadata["as_of_cursor"] == last.cursor
            old = await InstanceProvider(world, _BOT).resolve(first.ref)
            assert old == first
            middle = await catalog.inspect(ResourceRef(first.ref.key, f"world_{events[-1].cursor}"))
            assert middle.metadata["state"] == "started"
            assert middle.metadata["commit_count"] == len(events) + 1
            for cursor in (before.cursor, unrelated.cursor, last.cursor + 1):
                with pytest.raises(LookupError):
                    await catalog.inspect(ResourceRef(first.ref.key, f"world_{cursor}"))
            assert first.ref.revision == f"world_{started.cursor}"

    asyncio.run(scenario())


@pytest.mark.parametrize("revision", [None, "latest", "world_0", "world_-1", "world_01", "1", "world_x"])
def test_instance_inspection_requires_owned_address_and_canonical_version(tmp_path: Path, revision: str | None) -> None:
    """另一个 Bot 或另一命名空间不能借同一原始树 ID 读取该实例。"""

    async def scenario() -> None:
        """不属于来源的引用返回缺失，目录据此给出统一错误。"""
        async with _journal(tmp_path) as world:
            await world.append_commits((_start("tree"),))
            provider = InstanceProvider(world, _BOT)
            found = (await provider.find(ResourceQuery(kind="instance"))).items[0]
            assert await provider.resolve(ResourceRef(found.ref.key, revision)) is None
            assert await InstanceProvider(world, "aurora:bot/other").resolve(found.ref) is None
            assert (
                await provider.resolve(ResourceRef(replace(found.ref.key, namespace="missing"), found.ref.revision))
                is None
            )
            assert await provider.resolve(ResourceRef(DEFAULT_TREE_PROCESS.key, "1")) is None
            assert await provider.resolve(ResourceRef(replace(found.ref.key, domain="memory"), "1")) is None

    asyncio.run(scenario())


@pytest.mark.parametrize("change", ["missing-process", "missing-instance", "wrong-process", "wrong-owner", "wrong-id"])
def test_declared_but_inconsistent_instance_metadata_is_an_explicit_error(tmp_path: Path, change: str) -> None:
    """损坏的明确声明不能被伪装成完整的空列表。"""

    async def scenario() -> None:
        """解析与版本核对使用事实本身，不使用当前运行器配置。"""
        async with _journal(tmp_path) as world:
            start = _start("tree")
            instance = ResourceInstance("tree", _BOT, DEFAULT_TREE_PROCESS.ref)
            data = dict(start.data)
            match change:
                case "missing-process":
                    del data["process_ref"]
                case "missing-instance":
                    del data["instance"]
                case "wrong-process":
                    data["process_ref"] = resource_ref_data(ResourceRef(DEFAULT_TREE_PROCESS.key, "different"))
                case "wrong-owner":
                    data["instance"] = resource_instance_data(replace(instance, bot_id="aurora:bot/other"))
                case "wrong-id":
                    data["instance"] = resource_instance_data(replace(instance, instance_id="other"))
            await world.append_commits((replace(start, data=data),))
            provider = InstanceProvider(world, _BOT)
            with pytest.raises(ValueError):
                await provider.find(ResourceQuery(kind="instance"))
            with pytest.raises(ValueError):
                await provider.resolve(ResourceRef(instance.key, "world_1"))

    asyncio.run(scenario())


def test_instance_provider_does_not_claim_other_sources_addresses(tmp_path: Path) -> None:
    """同领域同类别的扩展资源仍能由自己的来源解析。"""

    async def scenario() -> None:
        """用真实制品来源验证实例提供者不会阻断其他提供者的结果。"""
        async with _journal(tmp_path) as world:
            store = FileArtifactStore(tmp_path / "artifacts")
            info = await store.put(ResourceKey("lab", "engine", "instance", "external-format"), b"external instance")
            catalog = ResourceCatalog(providers=(InstanceProvider(world, _BOT), ArtifactProvider(store)))
            inspected = await catalog.inspect(info.ref)
            assert inspected.ref == info.ref
            assert inspected.metadata["content"]["size"] == info.size

    asyncio.run(scenario())


def test_discovery_uses_a_finite_world_prefix_when_new_starts_arrive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """读第一页期间的新事实留给下一次发现，扫描不会追逐无限增长的日志。"""

    async def scenario() -> None:
        """真实追加发生在高水位确定之后、世界页读取之前。"""
        async with _journal(tmp_path) as world:
            await world.append_commits((_start("first"),))
            original = world.stream
            added = False

            async def stream(after: int, limit: int) -> WorldStreamPage:
                """仅第一次读取时追加一个开始事实。"""
                nonlocal added
                if not added:
                    added = True
                    await world.append_commits((_start("second"),))
                return await original(after, limit)

            monkeypatch.setattr(world, "stream", stream)
            provider = InstanceProvider(world, _BOT)
            query = ResourceQuery(kind="instance")
            assert len((await provider.find(query)).items) == 1
            assert {item.metadata["instance"]["instance_id"] for item in (await provider.find(query)).items} == {
                "first",
                "second",
            }

    asyncio.run(scenario())
