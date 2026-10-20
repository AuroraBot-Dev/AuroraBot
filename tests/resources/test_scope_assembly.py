"""有效域目录在业务准备前完成校验，并向所有消费者暴露同一实例。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from aurorabot.contracts.scope import ScopeCatalog, ScopeDeclaration, ScopeKind
from aurorabot.kernel import compose, compose_managed, module
from aurorabot.scopes.module import MODULE

if TYPE_CHECKING:
    from aurorabot.kernel import ModuleContext


@dataclass(frozen=True, slots=True)
class _Settings:
    """只提供项目级域覆盖的设置。"""

    catalog: ScopeCatalog = field(default_factory=lambda: ScopeCatalog(()))
    project_root: Path = Path()

    def resolve[T](self, config_type: type[T]) -> T:
        """域目录之外的配置不应参与声明汇总。"""
        assert config_type is ScopeCatalog
        return cast("T", self.catalog)


def test_scope_provider_reads_consumer_metadata_without_a_dependency_cycle() -> None:
    """业务模块依赖目录，也可在准备前声明自己的运行台账。"""
    declaration = ScopeDeclaration("lab:world/jobs/*", ScopeKind.RUN, "异步过程台账")
    seen: list[ScopeCatalog] = []

    async def prepare(context: ModuleContext) -> None:
        """业务准备前已经能读取自己声明的分类。"""
        seen.append(context.get(ScopeCatalog))
        assert seen[-1].classify("lab:world/jobs/one") is ScopeKind.RUN

    @module(name="jobs", provides=str, requires=ScopeCatalog, scopes=declaration, prepare=prepare)
    def jobs(context: ModuleContext) -> str:
        """构造阶段读取同一个冻结目录。"""
        seen.append(context.get(ScopeCatalog))
        return "ready"

    async def scenario() -> None:
        handle = await compose_managed(_Settings(), (jobs, MODULE))
        try:
            assert seen == [handle.assembly.get(ScopeCatalog)] * 2
        finally:
            await handle.close()

    asyncio.run(scenario())
    assert compose(_Settings(), (jobs, MODULE)).get(ScopeCatalog).declarations == (declaration,)


@pytest.mark.parametrize("managed", [False, True])
def test_inconsistent_scope_declarations_fail_before_business_resources_open(managed: bool) -> None:
    """冲突只依赖静态声明，不能在其他模块的准备副作用之后才暴露。"""
    trace: list[str] = []
    pattern = "lab:world/jobs/*"

    async def prepare(context: ModuleContext) -> None:
        """模拟文件或连接的创建。"""
        trace.append("opened")

    @module(
        name="a",
        provides=str,
        requires=ScopeCatalog,
        scopes=ScopeDeclaration(pattern, ScopeKind.RUN, "过程台账"),
        prepare=prepare,
    )
    def first(context: ModuleContext) -> str:
        """同步构造也应等待域声明校验。"""
        trace.append("constructed")
        return "first"

    @module(
        name="b", provides=int, requires=ScopeCatalog, scopes=ScopeDeclaration(pattern, ScopeKind.RESOURCE, "业务事实")
    )
    def second(context: ModuleContext) -> int:
        """同一模式的另一项不一致声明。"""
        return 1

    async def scenario() -> None:
        """异步准备遇到冲突应直接失败。"""
        await compose_managed(_Settings(), (first, second, MODULE))

    with pytest.raises(ValueError, match="域模式定义不一致"):
        if managed:
            asyncio.run(scenario())
        else:
            compose(_Settings(), (MODULE, first, second))
    assert trace == []
