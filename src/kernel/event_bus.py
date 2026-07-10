"""File-based event bus — enhanced with hooks and backed by CAS metadata store.

Replaces the previous direct-filesystem event bus.  File writes go through
the immutable object store and CAS metadata store.  The async dispatch
mechanism is preserved and extended with pre/post/error hooks.

For backward compatibility, ``apply_update`` also writes to the expected
filesystem path so that existing node implementations can continue to
read from the filesystem during migration.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import TYPE_CHECKING

from src.config import Config
from src.kernel.base import FileEvent, FileUpdate
from src.kernel.hooks import hook_registry
from src.kernel.metadata import SQLiteMetadataStore
from src.kernel.models import FileMeta
from src.kernel.objectstore import FileObjectStore, MemoryObjectStore
from src.utils.log_utils import get_logger

if TYPE_CHECKING:
    from pathlib import Path

    from src.kernel.base import Node

logger = get_logger("FileEventBus")


class FileEventBus:
    """Enhanced event bus backed by CAS metadata store and immutable object store.

    Responsibilities:
    - Accept :class:`FileEvent` and dispatch to matching :class:`Node` instances
    - Write :class:`FileUpdate` through the immutable object store (+ filesystem compat)
    - Integrate pre/post/error hooks for plugin extensibility
    - Generate downstream events after file writes
    """

    def __init__(
        self,
        nodes: list[Node],
        store: SQLiteMetadataStore | None = None,
        objects: MemoryObjectStore | FileObjectStore | None = None,
        data_dir: Path | None = None,
    ) -> None:
        self._nodes = nodes
        self._store = store or SQLiteMetadataStore(":memory:")
        self._objects = objects or MemoryObjectStore()
        self._data_dir = data_dir or Config.KERNEL_DATA_DIR
        self._queue: asyncio.Queue[FileEvent] = asyncio.Queue()
        self._dispatch_task: asyncio.Task[None] | None = None

    def publish(self, event: FileEvent) -> None:
        """Publish a file event to the bus for dispatch."""
        self._queue.put_nowait(event)

    async def apply_update(self, update: FileUpdate, node_id: str) -> None:
        """Write a file update and publish a downstream event.

        This is the primary write path.  Content is:
        1. Stored in the immutable object store (SHA-256)
        2. Recorded in the CAS metadata store (SQLite)
        3. Written to the expected filesystem path (backward compat)

        A FileEvent is published to wake downstream nodes.
        """
        # 1. Serialize content
        content_bytes = self._serialize_content(update)

        # 2. Store in immutable object store
        object_id = self._objects.put(content_bytes)

        # 3. Create metadata entry
        file_path = update.descriptor.path
        file_id = file_path.replace("/", "-").replace("\\", "-")
        meta = self._store.create_file(
            FileMeta(
                file_id=file_id,
                object_id=object_id,
                owner_id=None,
                tags={
                    "type": update.descriptor.schema or "raw",
                    "path": file_path,
                    "producer": node_id,
                },
                max_rounds=1,
            )
        )

        # 4. Write to filesystem (backward compat for nodes reading from disk)
        self._write_to_filesystem(update)

        logger.debug(
            "File written: %s (object=%s, version=%d)",
            file_path,
            object_id,
            meta.version,
        )

        # 5. Publish downstream event
        event = FileEvent(
            path=file_path,
            change_type="write",
            metadata={
                "source_node": node_id,
                "object_id": object_id,
                "file_id": file_id,
                "version": meta.version,
            },
        )
        self.publish(event)

    async def dispatch_forever(self) -> None:
        """Main event dispatch loop.

        Continuously pulls events from the queue and dispatches to
        matching nodes, running through pre/post hooks.
        """
        while True:
            try:
                event = await self._queue.get()
            except asyncio.CancelledError:
                return

            try:
                await self._dispatch_to_nodes(event)
            except Exception:
                logger.exception("Event dispatch failed: path=%s", event.path)

    def start_dispatch(self) -> None:
        """Start the dispatch loop as an asyncio task."""
        self._dispatch_task = asyncio.create_task(self.dispatch_forever())

    async def shutdown(self) -> None:
        """Stop the dispatch loop."""
        if self._dispatch_task is not None and not self._dispatch_task.done():
            self._dispatch_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._dispatch_task
            self._dispatch_task = None

    # ── Internal helpers ──────────────────────────────────

    async def _dispatch_to_nodes(self, event: FileEvent) -> None:
        """Dispatch a single event to all matching nodes via hooks."""
        # Pre-dispatch hooks — can suppress the event
        results = await hook_registry.trigger("pre_dispatch", event, self._nodes)
        if any(r is None for r in results):
            logger.debug("Event suppressed by pre_dispatch hook: path=%s", event.path)
            return

        matched_nodes: list[Node] = []
        for node in self._nodes:
            try:
                if node.on_event(event):
                    node.wake()
                    matched_nodes.append(node)
            except Exception:
                logger.exception("Node %s on_event error: path=%s", node.id, event.path)
                await hook_registry.trigger("on_error", event, node, None)

        # Post-dispatch hooks
        await hook_registry.trigger("post_dispatch", event, matched_nodes)

    def _serialize_content(self, update: FileUpdate) -> bytes:
        """Serialize FileUpdate content to bytes for the object store."""
        if update.descriptor.schema == "json":
            return json.dumps(update.content, indent=2, ensure_ascii=False).encode("utf-8")
        return str(update.content).encode("utf-8")

    def _write_to_filesystem(self, update: FileUpdate) -> None:
        """Write the file to the expected filesystem path (backward compat)."""
        file_path = self._data_dir / update.descriptor.path
        file_path.parent.mkdir(parents=True, exist_ok=True)

        content = update.content
        if update.descriptor.schema == "json":
            file_path.write_text(
                json.dumps(content, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        else:
            file_path.write_text(str(content), encoding="utf-8")
