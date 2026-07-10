"""Executable graph runner for the AuroraBot kernel."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.kernel.graph import FlowWorker, GraphRuntime, WorkerEvent
from src.kernel.heartbeat import HeartbeatRuntime, LoadSample
from src.kernel.models import FileState

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(frozen=True, slots=True)
class RunnerEvent:
    kind: str
    message: str


@dataclass(frozen=True, slots=True)
class RunnerCycle:
    epoch: int
    next_interval: float
    moved: bool
    done: bool
    events: list[RunnerEvent]


class GraphRunner:
    """Drives file processing through the graph.

    Each cycle:
    1. Assigns free work to available workers (load-balanced)
    2. Publishes heartbeat with current load samples
    3. Steps each worker to process one file
    """

    def __init__(self, graph: GraphRuntime, heartbeat: HeartbeatRuntime, workers: list[FlowWorker]) -> None:
        self.graph = graph
        self.heartbeat = heartbeat
        self.workers = workers

    def cycle(self) -> RunnerCycle:
        events: list[RunnerEvent] = []
        assignments = self.graph.assign_free_work([worker.load() for worker in self.workers])
        for file_id, file_type, owner_id in assignments:
            events.append(RunnerEvent("ASSIGN", f"{file_id} type={file_type} -> {owner_id}"))

        loads = [worker.load() for worker in self.workers]
        snapshot = self.heartbeat.publish(
            [LoadSample(agent_id=load.node_id, role=load.role, queue_depth=int(load.load)) for load in loads]
        )
        load_text = " ".join(f"{load.node_id}:{int(load.load)}" for load in loads)
        events.append(
            RunnerEvent(
                "BEAT",
                (
                    f"{snapshot.epoch:02d} load={snapshot.instant_load:.2f} "
                    f"smooth={snapshot.smooth_load:.2f} next={snapshot.next_interval:.2f}s | {load_text}"
                ),
            )
        )

        moved = False
        for worker in self.workers:
            result = worker.step()
            if result is None:
                continue
            if isinstance(result, WorkerEvent):
                moved = moved or result.moved
                events.append(RunnerEvent(result.kind, result.message))
                continue
            moved = True
            source_id, source_type, target_id = result
            events.append(RunnerEvent("FLOW", f"{worker.node_id} consumed {source_id}({source_type}) -> {target_id}"))

        done = self.is_done()
        return RunnerCycle(
            epoch=snapshot.epoch,
            next_interval=snapshot.next_interval,
            moved=moved,
            done=done,
            events=events,
        )

    def run_until_done(self, *, max_cycles: int = 100) -> list[RunnerCycle]:
        cycles: list[RunnerCycle] = []
        for _ in range(max_cycles):
            cycle = self.cycle()
            cycles.append(cycle)
            if cycle.done:
                break
        return cycles

    async def run_live(
        self,
        *,
        max_cycles: int = 100,
        sleep_scale: float = 1.0,
        on_cycle: Callable[[RunnerCycle], None] | None = None,
    ) -> list[RunnerCycle]:
        cycles: list[RunnerCycle] = []
        for _ in range(max_cycles):
            cycle = self.cycle()
            cycles.append(cycle)
            if on_cycle is not None:
                on_cycle(cycle)
            if cycle.done:
                break
            await asyncio.sleep(max(0.0, cycle.next_interval * sleep_scale))
        return cycles

    def is_done(self) -> bool:
        free_work = self.graph.store.query_claimable(owner_id=None)
        if free_work:
            return False
        active = [
            meta
            for meta in self.graph.store.list_files()
            if meta.tags.get("type") != "heartbeat" and meta.state != FileState.ARCHIVED
        ]
        return not active

    def close(self) -> None:
        self.graph.store.close()
