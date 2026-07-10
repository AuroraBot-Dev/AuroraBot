"""Immutable heartbeat snapshots and adaptive rhythm.

Uses EMA smoothing and a quadratic curve to self-regulate cycle
intervals based on cluster load, mimicking biological rhythms.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta

from src.kernel.metadata import SQLiteMetadataStore
from src.kernel.models import FileMeta, FileNotFoundError_, utcnow
from src.kernel.objectstore import FileObjectStore, MemoryObjectStore


@dataclass(frozen=True, slots=True)
class LoadSample:
    agent_id: str
    role: str
    queue_depth: int
    input_type: str | None = None

    @property
    def normalized(self) -> float:
        return min(1.0, self.queue_depth / 3.0)


@dataclass(frozen=True, slots=True)
class HeartbeatSnapshot:
    epoch: int
    instant_load: float
    smooth_load: float
    next_interval: float
    object_id: str


class HeartbeatRuntime:
    """Adaptive heartbeat with load-aware interval regulation.

    Publishes load samples as immutable heartbeat snapshots.
    Uses EMA smoothing and emergency wake-up on load spikes.
    """

    def __init__(
        self,
        store: SQLiteMetadataStore,
        objects: MemoryObjectStore | FileObjectStore,
        *,
        heartbeat_id: str = "heartbeat",
        min_interval: float = 0.2,
        max_interval: float = 1.2,
        alpha: float = 0.35,
        half_saturation: float = 0.25,
    ) -> None:
        self.store = store
        self.objects = objects
        self.heartbeat_id = heartbeat_id
        self.min_interval = min_interval
        self.max_interval = max_interval
        self.alpha = alpha
        self.half_saturation = half_saturation
        self._ensure_file()

    def publish(self, samples: list[LoadSample]) -> HeartbeatSnapshot:
        current = self.store.get(self.heartbeat_id)
        instant = sum(sample.normalized for sample in samples) / len(samples) if samples else 0.0
        previous = current.smooth_load or 0.0
        smooth = self.alpha * instant + (1.0 - self.alpha) * previous
        interval = self._interval_for(smooth)
        if instant > previous + 0.35:
            interval = self.min_interval
            smooth = instant

        epoch = (current.heartbeat_epoch or 0) + 1
        payload = {
            "epoch": epoch,
            "instant_load": round(instant, 4),
            "smooth_load": round(smooth, 4),
            "next_interval": round(interval, 4),
            "previous_object_id": current.object_id,
            "samples": [
                {
                    "agent_id": sample.agent_id,
                    "role": sample.role,
                    "queue_depth": sample.queue_depth,
                }
                for sample in samples
            ],
        }
        object_id = self.objects.put(json.dumps(payload, sort_keys=True).encode("utf-8"))
        updated = self.store.cas_update(
            self.heartbeat_id,
            current.version,
            {
                "object_id": object_id,
                "heartbeat_epoch": epoch,
                "smooth_load": smooth,
                "next_cycle_at": utcnow() + timedelta(seconds=interval),
            },
        )
        return HeartbeatSnapshot(
            epoch=epoch,
            instant_load=instant,
            smooth_load=updated.smooth_load or 0.0,
            next_interval=interval,
            object_id=object_id,
        )

    def _ensure_file(self) -> None:
        try:
            self.store.get(self.heartbeat_id)
        except FileNotFoundError_:
            payload = {
                "epoch": 0,
                "instant_load": 0.0,
                "smooth_load": 0.0,
                "next_interval": self.max_interval,
                "samples": [],
            }
            object_id = self.objects.put(json.dumps(payload, sort_keys=True).encode("utf-8"))
            self.store.create_file(
                FileMeta(
                    file_id=self.heartbeat_id,
                    object_id=object_id,
                    owner_id="heartbeat",
                    tags={"type": "heartbeat"},
                    heartbeat_epoch=0,
                    smooth_load=0.0,
                    next_cycle_at=utcnow() + timedelta(seconds=self.max_interval),
                    retention_policy="latest-plus-window",
                )
            )

    def _interval_for(self, smooth_load: float) -> float:
        curved = smooth_load * smooth_load
        pressure = curved / (self.half_saturation + curved) if curved else 0.0
        return self.max_interval - (self.max_interval - self.min_interval) * pressure
