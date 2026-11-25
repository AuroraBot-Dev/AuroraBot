"""bot 的可选 CLI 声明；通过公共操作提交引导、观察内部运行并取消。"""

import asyncio
from dataclasses import asdict
from typing import Protocol, TextIO, cast

from aurora_agent.runtime import RunHandle, Submission
from aurora_core.ctx import StateChange
from aurora_core.ids import Id
from aurora_core.invocation import invoke_operation
from aurora_core.json_data import encode_json
from aurora_core.registry import DefinitionRegistry, RegistryEntry

from .assembly_config import RUN, WORK
from .operations import RUN_ACTIVATE, RUN_CANCEL, RUN_SUBMIT


class CommandContext(Protocol):
    """由 CLI 宿主提供的结构接口，bot 无需导入 CLI 实现。"""

    @property
    def registry(self) -> DefinitionRegistry: ...

    @property
    def output(self) -> TextIO: ...


def _write(context: CommandContext, value: object) -> None:
    print(encode_json(value), file=context.output, flush=True)


def _render(context: CommandContext, change: StateChange, handle: RunHandle, instance_id: str) -> None:
    value = change.value
    assert isinstance(value, dict)
    location = dict(change.address.location)
    identity = value.get("run_id") if change.address.key == RUN else location.get("run_id")
    if identity != handle.run_id:
        return
    common = {"instance_id": instance_id, "run_id": handle.run_id}
    if change.address.key == RUN:
        _write(context, {**common, "event": "run", "state": value})
    else:
        previous = change.previous
        prefix = (
            previous["text"]
            if isinstance(previous, dict) and previous.get("execution_id") == value["execution_id"]
            else ""
        )
        _write(
            context,
            {
                **common,
                "event": "model",
                "execution_id": value["execution_id"],
                "status": value["status"],
                "delta": value["text"][len(prefix) :],
                "tool_calls": value["tool_calls"],
                "finish_reason": value["finish_reason"],
            },
        )


async def _follow(context: CommandContext, operation: Id, instance_id: str, **values: object) -> int:
    changes: asyncio.Queue[StateChange | None] = asyncio.Queue()

    def observe(change: StateChange) -> None:
        location = dict(change.address.location)
        if (
            change.action == "set"
            and location.get("instance_id") == instance_id
            and (change.address.key == RUN or (change.address.key == WORK and location.get("part") == "model_output"))
        ):
            changes.put_nowait(change)

    subscription = await invoke_operation(context.registry, Id("org.aurora.core:operations/ctx/subscribe"), observe)
    handle: RunHandle | None = None
    waiter = None
    try:
        receipt = await invoke_operation(context.registry, operation, instance_id=instance_id, **values)
        handle = receipt.run if isinstance(receipt, Submission) else cast(RunHandle, receipt)
        accepted: dict[str, object] = {"event": "accepted", "instance_id": instance_id, "run_id": handle.run_id}
        if isinstance(receipt, Submission):
            accepted.update(sequence=receipt.sequence, guidance_id=receipt.guidance_id)
        _write(context, accepted)
        waiter = asyncio.create_task(handle.wait())
        waiter.add_done_callback(lambda _: changes.put_nowait(None))
        while (change := await changes.get()) is not None:
            _render(context, change, handle, instance_id)
        result = waiter.result()
        _write(context, {"event": "result", "instance_id": instance_id, **asdict(result)})
        return {"completed": 0, "failed": 1, "cancelled": 130}[result.status]
    except asyncio.CancelledError:
        if handle is not None:
            await invoke_operation(context.registry, RUN_CANCEL, handle.run_id, instance_id=instance_id)
            while not changes.empty():
                change = changes.get_nowait()
                if change is not None:
                    _render(context, change, handle, instance_id)
            result = await handle.wait()
            _write(context, {"event": "result", "instance_id": instance_id, **asdict(result)})
        raise
    finally:
        await invoke_operation(context.registry, Id("org.aurora.core:operations/ctx/unsubscribe"), subscription)
        if handle is not None and not handle.done:
            await invoke_operation(context.registry, RUN_CANCEL, handle.run_id, instance_id=instance_id)
        if waiter is not None:
            waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)


async def submit(context: CommandContext, payload: str, *, instance_id: str, sequence: int | None = None) -> int:
    """提交文本引导，逐行输出 JSON；model 记录表示内部推理。"""
    return await _follow(context, RUN_SUBMIT, instance_id, payload=payload, sequence=sequence)


async def activate(context: CommandContext, *, instance_id: str) -> int:
    """显式激活已有输入，等待运行清理后返回终态。"""
    return await _follow(context, RUN_ACTIVATE, instance_id)


async def cancel(context: CommandContext, run_id: str, *, instance_id: str) -> None:
    """仅取消当前宿主中的匹配运行，不跨进程寻址。"""
    cancelled = await invoke_operation(context.registry, RUN_CANCEL, run_id, instance_id=instance_id)
    _write(context, {"event": "cancel", "instance_id": instance_id, "run_id": run_id, "cancelled": cancelled})


def command_entries() -> tuple[RegistryEntry, ...]:
    """CLI 缺席时声明保留为未连接，不影响装配和进程内操作。"""
    instance = {"name": "instance_id", "option": True, "required": True}
    return tuple(
        RegistryEntry(
            Id(f"org.aurora.bot:commands/run/{name}"),
            "command",
            {"help": help_text, "executor": executor, "runtime": True, "arguments": [*arguments, instance]},
            "aurora_bot",
            register_to=Id("org.aurora.cli:registries/commands"),
        )
        for name, help_text, executor, arguments in (
            (
                "submit",
                "提交文本引导并观察内部运行；Ctrl+C 取消本次运行",
                submit,
                [{"name": "payload"}, {"name": "sequence", "type": "integer", "option": True}],
            ),
            ("activate", "显式激活已有输入并观察内部运行", activate, []),
            ("cancel", "按 run_id 取消当前宿主中的运行", cancel, [{"name": "run_id"}]),
        )
    )
