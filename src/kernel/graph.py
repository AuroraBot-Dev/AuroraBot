"""Graph-based file flow routing engine.

Defines the Route table and the GraphRuntime which manages file
transitions through a directed (possibly cyclic) graph of processing steps.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from uuid import uuid4

from src.kernel.locks import LockClient
from src.kernel.metadata import SQLiteMetadataStore
from src.kernel.models import CasConflict, FileMeta, FileState, LockDenied
from src.kernel.objectstore import FileObjectStore, MemoryObjectStore


@dataclass(frozen=True, slots=True)
class AgentLoad:
    node_id: str
    role: str
    load: float
    input_type: str | None = None


@dataclass(frozen=True, slots=True)
class Route:
    """A single edge in the processing graph.

    Files with ``input_type`` are routed to workers with ``worker_role``,
    producing output of ``output_type``.
    """

    input_type: str
    output_type: str | None
    worker_role: str
    next_role: str | None = None
    terminal: bool = False
    match_tags: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class WorkerEvent:
    kind: str
    message: str
    moved: bool = False


class LeastLoadBalancer:
    """Assign work to the agent with the lowest current load."""

    @staticmethod
    def choose(candidates: list[AgentLoad]) -> AgentLoad:
        if not candidates:
            msg = "no load candidates"
            raise ValueError(msg)
        return sorted(candidates, key=lambda item: (item.load, item.node_id))[0]


class GraphRuntime:
    """Core graph engine that routes files through processing steps.

    Responsibilities:
    - Maintain route table (input_type → output_type mapping)
    - Assign unowned files to capable workers via CAS
    - Produce successor files (new immutable versions)
    - Complete/archive processed files
    """

    def __init__(
        self,
        store: SQLiteMetadataStore,
        objects: MemoryObjectStore | FileObjectStore,
        routes: list[Route],
    ) -> None:
        self.store = store
        self.objects = objects
        self.routes = routes
        self.balancer = LeastLoadBalancer()

    def route_for_type(self, file_type: str) -> Route | None:
        for route in self.routes:
            if route.input_type == file_type:
                return route
        return None

    def route_for_meta(self, meta: FileMeta) -> Route | None:
        file_type = str(meta.tags.get("type", ""))
        for route in self.routes:
            if route.input_type != file_type:
                continue
            if route.match_tags and any(meta.tags.get(key) != value for key, value in route.match_tags.items()):
                continue
            return route
        return None

    def assign_free_work(self, loads: list[AgentLoad]) -> list[tuple[str, str, str]]:
        """Assign unowned files to the best-suited worker via CAS.

        Returns list of (file_id, file_type, node_id) assignments.
        """
        assignments: list[tuple[str, str, str]] = []
        virtual_loads = list(loads)
        for meta in self.store.query_claimable(owner_id=None):
            file_type = str(meta.tags.get("type", ""))
            route = self.route_for_meta(meta)
            if route is None:
                self._mark_error(meta, "no_route")
                continue
            candidates = [
                load
                for load in virtual_loads
                if load.role == route.worker_role and (load.input_type is None or load.input_type == file_type)
            ]
            target_node = meta.tags.get("target_node")
            if isinstance(target_node, str):
                candidates = [load for load in candidates if load.node_id == target_node]
            if not candidates:
                continue
            chosen = self.balancer.choose(candidates)
            try:
                updated = self.store.cas_update(
                    meta.file_id,
                    meta.version,
                    {"owner_id": chosen.node_id},
                    "owner_id IS NULL AND write_holder IS NULL AND state = ?",
                    (FileState.CREATED.value,),
                )
            except CasConflict:
                continue
            assignments.append((updated.file_id, file_type, chosen.node_id))
            virtual_loads = [
                replace(load, load=load.load + 1.0) if load.node_id == chosen.node_id else load
                for load in virtual_loads
            ]
        return assignments

    def produce_successor(
        self,
        *,
        source: FileMeta,
        producer_id: str,
        output_type: str,
        content: bytes,
        tags: dict[str, object] | None = None,
    ) -> FileMeta:
        object_id = self.objects.put(content)
        next_tags = dict(tags or {})
        next_tags["type"] = output_type
        return self.store.create_file(
            FileMeta(
                file_id=f"{output_type}-{uuid4().hex[:8]}",
                object_id=object_id,
                owner_id=None,
                tags=next_tags,
                parent_file_id=source.file_id,
                previous_file_id=source.file_id,
                processing_round=source.processing_round,
                max_rounds=source.max_rounds,
                termination_policy=source.termination_policy,
            )
        )

    def complete_input(self, source: FileMeta, producer_id: str) -> FileMeta:
        lock = LockClient(self.store, producer_id)
        current = self.store.get(source.file_id)
        if current.write_holder == producer_id:
            current = lock.release_write(source.file_id)
        return lock.archive(current.file_id)

    def _mark_error(self, meta: FileMeta, reason: str) -> None:
        try:
            self.store.cas_update(
                meta.file_id,
                meta.version,
                {"state": FileState.ERROR, "tags": {**meta.tags, "error": reason}},
                "state != ?",
                (FileState.ARCHIVED.value,),
            )
        except CasConflict:
            pass


class FlowWorker:
    """A processing worker in the graph.

    Reads files of a given input_type, processes them, and produces
    output files of output_type.  The actual processing logic is
    provided by subclasses or callables.
    """

    def __init__(
        self,
        *,
        node_id: str,
        role: str,
        input_type: str,
        output_type: str | None,
        graph: GraphRuntime,
    ) -> None:
        self.node_id = node_id
        self.role = role
        self.input_type = input_type
        self.output_type = output_type
        self.graph = graph
        self.processed = 0

    def queue_depth(self) -> int:
        return len(self.graph.store.query_claimable(owner_id=self.node_id, tags={"type": self.input_type}))

    def load(self) -> AgentLoad:
        return AgentLoad(self.node_id, self.role, float(self.queue_depth()), self.input_type)

    def step(self) -> tuple[str, str, str] | None:
        """Process one file from this worker's queue.

        Returns (source_id, input_type, target_id) or None if no work.
        """
        queue = self.graph.store.query_claimable(owner_id=self.node_id, tags={"type": self.input_type})
        if not queue:
            return None
        source = queue[0]
        lock = LockClient(self.graph.store, self.node_id)
        try:
            locked = lock.acquire_write(source.file_id)
        except (CasConflict, LockDenied):
            return None

        input_text = self.graph.objects.get(locked.object_id).decode("utf-8")
        if self.output_type is None:
            self.graph.complete_input(locked, self.node_id)
            self.processed += 1
            return (locked.file_id, self.input_type, "ARCHIVED")

        output_text = f"{self.output_type}({input_text}) by {self.node_id}"
        successor = self.graph.produce_successor(
            source=locked,
            producer_id=self.node_id,
            output_type=self.output_type,
            content=output_text.encode("utf-8"),
            tags={"producer": self.node_id},
        )
        self.graph.complete_input(locked, self.node_id)
        self.processed += 1
        return (locked.file_id, self.input_type, successor.file_id)
