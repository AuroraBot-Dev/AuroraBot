"""真实进程装配不能在后台故障后静默等待，前台必须先于资源关闭。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from aurora import load_config
from aurorabot.contracts import FRONT_BINDINGS, Front
from aurorabot.contracts.pkgs.world import WorldJournal
from aurorabot.kernel import ModuleLifecycleError
from aurorabot.runtime import run_runtime
from aurorabot.runtime.events import RUNTIME_MODULE_FAILED
from aurorabot.world import SqlAlchemyWorldJournal
from tests.support.model import TemplateModel as FakeModel

if TYPE_CHECKING:
    from pathlib import Path

    from aurorabot.contracts import WorldCommit, WorldCommitInput


_PLUGIN = '''"""失败的后台模组。"""

from aurorabot.kernel import module


async def run(context, stop):
    """实际后台错误不应让宿主永远等待。"""
    raise ValueError("后台连接丢失")


@module(name="broken_sensor", provides=str, run=run)
def build(context):
    """纯服务构造仍正常。"""
    return "ready"


MODULE = build
'''


class _World(SqlAlchemyWorldJournal):
    """保留真实 SQLite 行为，同时记录实际关闭时刻。"""

    def __init__(self, path: Path, trace: list[str]) -> None:
        """关闭序列与测试协作者共享同一记录。"""
        super().__init__(path)
        self.trace = trace

    async def close(self) -> None:
        """记录关闭发生在前台退出之后。"""
        self.trace.append("world.closed")
        await super().close()


def _plugin(project: Path) -> None:
    """由正常目录发现路径装载故障模组。"""
    directory = project / "extensions" / "plugins"
    directory.mkdir(parents=True)
    (directory / "broken_sensor.py").write_text(_PLUGIN, encoding="utf-8")


def test_headless_background_failure_is_persisted_and_ends_the_process(configured_project: Path) -> None:
    """没有外部输入或前台时，也能感知后台死亡并保留世界事实。"""
    _plugin(configured_project)
    trace: list[str] = []
    path = configured_project / "failure.sqlite3"
    world = _World(path, trace)

    async def scenario() -> None:
        """停止不依赖定时轮询，重新打开日志可以看到模组故障。"""
        stop = asyncio.Event()
        async with asyncio.timeout(3):
            with pytest.raises(ModuleLifecycleError, match="broken_sensor"):
                await run_runtime(
                    load_config(configured_project),
                    FakeModel(),
                    headless=True,
                    stop_event=stop,
                    instances=((WorldJournal, world),),
                    output=lambda _: None,
                )
        assert stop.is_set()
        assert trace == ["world.closed"]
        reopened = SqlAlchemyWorldJournal(path)
        try:
            await reopened.initialize()
            page = await reopened.stream(0, 100)
            failures = [commit for commit in page.commits if commit.kind == RUNTIME_MODULE_FAILED]
            assert len(failures) == 1
            assert failures[0].data == {
                "module": "aurora:kernel/module/broken_sensor",
                "phase": "run",
                "error_type": "ValueError",
                "message": "后台连接丢失",
            }
        finally:
            await reopened.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("fail_front", [False, True])
def test_fronts_are_cancelled_and_joined_before_resources_close(configured_project: Path, fail_front: bool) -> None:
    """无论正常停止还是前台出错，都不能留下仍在使用资源的前台。"""
    trace: list[str] = []
    world = _World(configured_project / "fronts.sqlite3", trace)

    async def scenario() -> None:
        """一个前台故意不响应停止事件，必须由宿主显式取消回收。"""
        started = asyncio.Event()

        async def peer(stop: asyncio.Event) -> None:
            """清理包含一次真实异步让出，不能只发取消信号就关闭世界。"""
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                trace.append("front.closed")

        async def trigger(stop: asyncio.Event) -> None:
            """等协作者启动后触发停止或故障。"""
            await started.wait()
            if fail_front:
                raise ValueError("前台读取失败")
            stop.set()

        bindings = (
            (FRONT_BINDINGS, lambda _: Front(peer)),
            (FRONT_BINDINGS, lambda _: Front(trigger)),
        )
        async with asyncio.timeout(3):
            if fail_front:
                with pytest.raises(ExceptionGroup):
                    await run_runtime(
                        load_config(configured_project),
                        FakeModel(),
                        headless=True,
                        instances=((WorldJournal, world),),
                        contributions=bindings,
                        output=lambda _: None,
                    )
            else:
                await run_runtime(
                    load_config(configured_project),
                    FakeModel(),
                    headless=True,
                    instances=((WorldJournal, world),),
                    contributions=bindings,
                    output=lambda _: None,
                )
        assert trace == ["front.closed", "world.closed"]

    asyncio.run(scenario())


def test_external_runtime_cancellation_still_joins_fronts_and_closes_resources(configured_project: Path) -> None:
    """宿主取消保持 CancelledError 语义，同时完成前台与模组释放。"""
    trace: list[str] = []
    world = _World(configured_project / "cancelled.sqlite3", trace)

    async def scenario() -> None:
        """用启动事件精确控制取消点。"""
        started = asyncio.Event()

        async def front(stop: asyncio.Event) -> None:
            """前台终止时先释放自己的局部状态。"""
            started.set()
            try:
                await stop.wait()
            finally:
                trace.append("front.closed")

        task = asyncio.create_task(
            run_runtime(
                load_config(configured_project),
                FakeModel(),
                headless=True,
                instances=((WorldJournal, world),),
                contributions=((FRONT_BINDINGS, lambda _: Front(front)),),
                output=lambda _: None,
            )
        )
        async with asyncio.timeout(3):
            await started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert task.cancelled()
        assert trace == ["front.closed", "world.closed"]

    asyncio.run(scenario())


def test_unexpected_front_cancellation_is_a_runtime_failure(configured_project: Path) -> None:
    """自行取消的前台不能被 TaskGroup 当作正常完成而忽略。"""

    async def front(stop: asyncio.Event) -> None:
        """模拟适配器意外取消自身。"""
        raise asyncio.CancelledError("意外取消")

    async def scenario() -> None:
        """前台故障经过正常关闭路径报告。"""
        with pytest.raises(ExceptionGroup) as captured:
            await run_runtime(
                load_config(configured_project),
                FakeModel(),
                headless=True,
                contributions=((FRONT_BINDINGS, lambda _: Front(front)),),
                output=lambda _: None,
            )
        assert any("意外取消" in str(error) for error in captured.value.exceptions)

    asyncio.run(scenario())


def test_world_recording_failure_preserves_the_original_module_error(configured_project: Path) -> None:
    """故障记录也失败时，两项错误都必须到达宿主。"""
    _plugin(configured_project)
    trace: list[str] = []

    class FailingWorld(_World):
        """只让故障事实提交失败，初始化仍使用真实世界日志。"""

        async def append_commits(self, inputs: tuple[WorldCommitInput, ...]) -> tuple[WorldCommit, ...]:
            """模拟磁盘写入故障。"""
            if any(item.kind == RUNTIME_MODULE_FAILED for item in inputs):
                raise OSError("故障日志无法写入")
            return await super().append_commits(inputs)

    async def scenario() -> None:
        """底层世界即使拒绝记录，也仍被关闭。"""
        world = FailingWorld(configured_project / "unwritable.sqlite3", trace)
        with pytest.raises(ExceptionGroup) as captured:
            await run_runtime(
                load_config(configured_project),
                FakeModel(),
                headless=True,
                instances=((WorldJournal, world),),
                output=lambda _: None,
            )
        assert any(isinstance(error, ModuleLifecycleError) for error in captured.value.exceptions)
        assert any(isinstance(error, OSError) for error in captured.value.exceptions)
        assert trace == ["world.closed"]

    asyncio.run(scenario())


@pytest.mark.parametrize("cancel_while_recording", [False, True])
def test_stop_waits_for_an_already_claimed_module_failure_to_be_recorded(
    configured_project: Path, cancel_while_recording: bool
) -> None:
    """停止到达故障写入中途时，不能取消已取走的故障并把进程当成成功。"""
    _plugin(configured_project)

    async def scenario() -> None:
        """前台清理确认监督者进入回收阶段，再允许故障记录完成。"""
        recording = asyncio.Event()
        release = asyncio.Event()
        front_closed = asyncio.Event()
        stop = asyncio.Event()
        trace: list[str] = []

        class DelayedWorld(_World):
            """精确控制故障提交的完成时机。"""

            async def append_commits(self, inputs: tuple[WorldCommitInput, ...]) -> tuple[WorldCommit, ...]:
                """只延迟故障事实，其他提交不受影响。"""
                if any(item.kind == RUNTIME_MODULE_FAILED for item in inputs):
                    recording.set()
                    await release.wait()
                return await super().append_commits(inputs)

        async def front(stop: asyncio.Event) -> None:
            """前台必须由监督者取消，释放完成后通知测试。"""
            try:
                await asyncio.Event().wait()
            finally:
                front_closed.set()

        path = configured_project / "stopping.sqlite3"
        world = DelayedWorld(path, trace)
        task = asyncio.create_task(
            run_runtime(
                load_config(configured_project),
                FakeModel(),
                headless=True,
                stop_event=stop,
                instances=((WorldJournal, world),),
                contributions=((FRONT_BINDINGS, lambda _: Front(front)),),
                output=lambda _: None,
            )
        )
        async with asyncio.timeout(3):
            await recording.wait()
            stop.set()
            await front_closed.wait()
            assert trace == []
            if cancel_while_recording:
                task.cancel()
            release.set()
            if cancel_while_recording:
                with pytest.raises(asyncio.CancelledError) as captured:
                    await task
                cause = captured.value.__cause__
                assert isinstance(cause, ExceptionGroup)
                assert any(isinstance(error, ModuleLifecycleError) for error in cause.exceptions)
            else:
                with pytest.raises(ModuleLifecycleError):
                    await task
        assert trace == ["world.closed"]
        reopened = SqlAlchemyWorldJournal(path)
        try:
            await reopened.initialize()
            page = await reopened.stream(0, 100)
            assert any(commit.kind == RUNTIME_MODULE_FAILED for commit in page.commits)
        finally:
            await reopened.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("stop_first", [False, True])
def test_cancellation_while_joining_fronts_waits_for_their_cleanup(configured_project: Path, stop_first: bool) -> None:
    """退出期间再次取消宿主，也必须先完成前台清理再关闭世界。"""
    trace: list[str] = []
    world = _World(configured_project / "repeated-cancellation.sqlite3", trace)

    async def scenario() -> None:
        """用两个事件分别控制前台启动和清理中的取消点。"""
        started = asyncio.Event()
        cleaning = asyncio.Event()
        release = asyncio.Event()
        stop = asyncio.Event()

        async def front(stop: asyncio.Event) -> None:
            """清理尚未完成时仍持有世界资源。"""
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaning.set()
                await release.wait()
                trace.append("front.closed")

        task = asyncio.create_task(
            run_runtime(
                load_config(configured_project),
                FakeModel(),
                headless=True,
                stop_event=stop,
                instances=((WorldJournal, world),),
                contributions=((FRONT_BINDINGS, lambda _: Front(front)),),
                output=lambda _: None,
            )
        )
        async with asyncio.timeout(3):
            await started.wait()
            if stop_first:
                stop.set()
            else:
                task.cancel()
            await cleaning.wait()
            task.cancel()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert task.cancelled()
        assert trace == ["front.closed", "world.closed"]

    asyncio.run(scenario())
