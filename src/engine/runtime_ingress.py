"""AMP 入口处理 —— 内存队列与文件系统两条路径。

将外部 AMP Envelope 归一化为 Task 创建或情境（Situation）记录。
支持自动 Tick（autonomous Task）和交互式 Task 两种模式。
"""

from __future__ import annotations

import os
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol

from src.contracts.amp import AmpEnvelope, AmpValidationError
from src.utils.logging import get_logger
from src.utils.serialization import read_json

if TYPE_CHECKING:
    from pathlib import Path

    from src.contracts.agent import AgentLimits, AgentProfile, CapabilityCatalogSnapshot, EngineConfiguration
    from src.engine.store import SQLiteRuntimeStore

logger = get_logger("aurora.engine")


class _Msg(StrEnum):
    """本文件内所有用户可见或日志输出的字符串常量。"""

    RESERVED_TOOL_EVENT = "Tool receipt event types are reserved for internal Runtime use"


class IngressRuntime(Protocol):
    """入口处理所需的 engine 结构协议。

    定义 ingest_ready 所需的最小内核接口，
    避免对 EngineState 的循环导入。
    """

    configuration: EngineConfiguration
    store: SQLiteRuntimeStore
    _inbox: Path
    _archive: Path
    _profiles: dict[str, AgentProfile]
    _amp_queue: list[Any]

    @property
    def limits(self) -> AgentLimits: ...

    @property
    def capability_catalog(self) -> CapabilityCatalogSnapshot: ...


def ingest_ready(kernel: IngressRuntime) -> tuple[str, ...]:
    """领取所有就绪的 AMP 输入。

    先处理内存队列中的 AMP，再扫描 inbox 目录中的 JSON 文件。
    成功摄入后归档到 archive/inbox/accepted，重复或无效的归入 rejected。
    """
    ingested: list[str] = []
    while kernel._amp_queue:
        amp = kernel._amp_queue.pop(0)
        try:
            _ingest_amp(kernel, amp, ingested)
        except (ValueError, TypeError) as error:
            logger.warning("AMP ingress rejected in-memory reason=%s", error)
    for path in sorted(kernel._inbox.glob("*.json")):
        try:
            amp = AmpEnvelope.parse(read_json(path))
        except (OSError, ValueError, TypeError, AmpValidationError) as error:
            logger.warning("AMP ingress rejected file=%s reason=%s", path.name, error)
            _archive_inbox(kernel, path, "rejected")
            continue
        try:
            _ingest_amp_file(kernel, amp, path, ingested)
        except (ValueError, TypeError) as error:
            logger.warning("AMP ingress rejected file=%s reason=%s", path.name, error)
            _archive_inbox(kernel, path, "rejected")
    return tuple(ingested)


def _ingest_amp(kernel: IngressRuntime, amp: AmpEnvelope, ingested: list[str]) -> None:
    """核心 AMP 摄入逻辑：创建 Task 或记录环境情境。无文件系统副作用。

    工具回执事件（tool.*）被保留供内部使用，外部不可直接发送。
    ambient 标记的事件转为 Situation，其余创建为 Task。
    """
    data = amp.payload.data
    if amp.payload.type in {"tool.succeeded", "tool.failed", "tool.unknown"}:
        raise ValueError(_Msg.RESERVED_TOOL_EVENT)
    if data.get("ambient") is True:
        situation_id = kernel.store.add_situation(
            amp.header.source["app"],
            amp.payload.type,
            amp.payload.summary,
            amp.to_dict(),
            10 if amp.payload.type == "system.tick" else 100,
            kernel.limits.ambient_ttl_seconds,
        )
        ingested.append(situation_id)
        return
    autonomous = amp.payload.type == "system.tick"
    budget = kernel.configuration.autonomous_budget if autonomous else kernel.configuration.interactive_budget
    task = kernel.store.create_task(
        external_message_id=amp.header.message_id,
        session_id=amp.payload.session_id,
        summary=amp.payload.summary,
        payload={"amp": amp.to_dict()},
        autonomous=autonomous,
        root_profile=kernel.limits.root_profile,
        budget=budget,
        priority=10 if autonomous else 100,
    )
    if task is not None:
        ingested.append(task.task_id)


def _ingest_amp_file(kernel: IngressRuntime, amp: AmpEnvelope, path: Path, ingested: list[str]) -> None:
    """文件系统路径的 AMP 摄入，含归档逻辑。摄入成功或重复后移动原文件。"""
    before = len(ingested)
    _ingest_amp(kernel, amp, ingested)
    if len(ingested) > before:
        _archive_inbox(kernel, path, "accepted")
    else:
        _archive_inbox(kernel, path, "duplicate")


def _archive_inbox(kernel: IngressRuntime, source: Path, category: str) -> None:
    """将已处理的 inbox 文件移动到对应归档目录。如遇冲突追加随机后缀。"""
    destination_dir = kernel._archive / "inbox" / category
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / source.name
    if destination.exists():
        destination = destination_dir / f"{source.stem}-{os.urandom(4).hex()}{source.suffix}"
    source.replace(destination)
