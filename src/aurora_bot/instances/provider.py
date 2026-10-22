"""按公共分页发现实例，并从世界域读取指定的历史版本。"""

from __future__ import annotations

import asyncio
import heapq
from typing import TYPE_CHECKING

from aurora_bot.contracts.resource import ResourceDescriptor, ResourceKey, resource_instance_identity
from aurora_bot.contracts.resource_paging import resource_cursor, resource_order, resource_position
from aurora_bot.contracts.resource_query import ResourcePage
from aurora_bot.contracts.run_lifecycle import run_scope
from aurora_bot.instances.history import InstanceView, instance_start

if TYPE_CHECKING:
    from aurora_bot.contracts.pkgs.world import WorldReader
    from aurora_bot.contracts.resource import ResourceRef
    from aurora_bot.contracts.resource_query import ResourceQuery
    from aurora_bot.contracts.world import WorldCommit

_WORLD_PAGE_SIZE = 256


class InstanceProvider:
    """缓存每实例一个摘要，历史版本始终按所属世界事实重建。"""

    def __init__(self, world: WorldReader, bot_id: str) -> None:
        """不依赖认知运行器或资源目录，避免能力装配形成循环。"""
        self._world = world
        self._bot_id = bot_id
        self._views: dict[str, InstanceView] = {}
        self._cursor = 0
        self._lock = asyncio.Lock()

    @property
    def key(self) -> ResourceKey:
        """来源身份与它提供的实例身份分别管理。"""
        return ResourceKey("aurora", "engine", "provider", "instances")

    async def find(self, query: ResourceQuery) -> ResourcePage:
        """从有界世界页更新摘要，按公共位置填满每个非末页。"""
        after = resource_position(query)
        if query.domain not in (None, "engine") or query.kind not in (None, "instance"):
            return ResourcePage(())
        async with self._lock:
            await self._refresh()
            views = tuple(self._views.values())
        eligible = (
            view
            for view in views
            if query.matches(view.ref.key) and (after is None or resource_order(view.ref) > after)
        )
        first = heapq.nsmallest(query.limit + 1, eligible, key=lambda view: resource_order(view.ref))
        selected = tuple(view.descriptor() for view in first[: query.limit])
        return ResourcePage(selected, resource_cursor(query, selected[-1].ref) if len(first) > query.limit else None)

    async def resolve(self, ref: ResourceRef) -> ResourceDescriptor | None:
        """固定版本只包含该实例在指定游标前已提交的事实。"""
        if ref.key.domain != "engine" or ref.key.kind != "instance":
            return None
        try:
            bot_id, run_id = resource_instance_identity(ref.key)
        except ValueError:
            return None
        cursor = _revision_cursor(ref.revision)
        if bot_id != self._bot_id or cursor is None:
            return None
        started = await self._world.commit(f"{run_id}:run:started")
        if started is None:
            return None
        view = instance_start(started, bot_id)
        if view is None or view.instance.key != ref.key or view.start_cursor > cursor:
            return None
        return await self._at(view, started.scopes[run_scope(run_id)], cursor)

    async def _at(self, view: InstanceView, after: int, cursor: int) -> ResourceDescriptor | None:
        """只重放实例开始之后的所属域，目标游标必须确实属于该实例。"""
        scope = run_scope(view.instance.instance_id)
        while view.last_cursor < cursor:
            page = await self._world.commits(scope, after, _WORLD_PAGE_SIZE)
            if not page:
                return None
            for commit in page:
                if commit.cursor > cursor:
                    return None
                view = view.advance(commit)
                if view.last_cursor == cursor:
                    return view.descriptor()
            after = page[-1].scopes[scope]
        return view.descriptor()

    async def _refresh(self) -> None:
        """读取固定高水位，逐条推进投影位置，异常后重试不会重复计数。"""
        high_water = await self._world.cursor()
        while self._cursor < high_water:
            page = await self._world.stream(self._cursor, _WORLD_PAGE_SIZE)
            previous = self._cursor
            for commit in page.commits:
                if commit.cursor > high_water:
                    break
                self._apply(commit)
                self._cursor = commit.cursor
            if self._cursor == previous:
                raise ValueError("实例发现无法读取已存在的世界前缀")

    def _apply(self, commit: WorldCommit) -> None:
        started = instance_start(commit, self._bot_id)
        if started is not None:
            self._views[run_scope(started.instance.instance_id)] = started
            return
        for scope in commit.scopes:
            view = self._views.get(scope)
            if view is not None:
                self._views[scope] = view.advance(commit)


def _revision_cursor(revision: str | None) -> int | None:
    """只接受正整数世界游标的规范文本，不将其他资源版本当作实例状态。"""
    if revision is None:
        return None
    try:
        cursor = int(revision.removeprefix("world_"))
    except ValueError:
        return None
    return cursor if cursor > 0 and revision == f"world_{cursor}" else None
