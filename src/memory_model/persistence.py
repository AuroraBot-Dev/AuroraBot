"""将 Bot 的动态图投影保存为资源，世界中只记录固定版本引用。"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Mapping
from typing import TYPE_CHECKING

from src.contracts import WorldFrontier
from src.contracts.artifact_codec import artifact_data, read_artifact
from src.contracts.artifact_io import artifact_content
from src.contracts.identity import Identifier
from src.contracts.memory_checkpoint import MEMORY_CHECKPOINT_MEDIA_TYPE, MemoryPolicyCheckpoint
from src.contracts.memory_checkpoint_codec import prefix_data, read_prefix
from src.contracts.resource import ResourceKey, ResourceRef
from src.utils import get_logger
from src.utils.validation import check_positive_number

if TYPE_CHECKING:
    from src.contracts.artifact import ArtifactInfo
    from src.contracts.pkgs.artifacts import ArtifactStore
    from src.contracts.pkgs.memory import MemoryPolicyState
    from src.contracts.pkgs.world import WorldJournal
    from src.contracts.world import WorldCommit

_logger = get_logger(__name__)
_CHECKPOINT_KIND = "memory.model.checkpoint"
_SCHEMA_VERSION = 1


class MemoryModelCheckpoints:
    """检查点是可丢弃的加速状态，损坏时回到世界历史重建。"""

    def __init__(
        self,
        bot_id: str,
        policy: MemoryPolicyState | None,
        artifacts: ArtifactStore,
        world: WorldJournal,
        *,
        interval_seconds: float = 60.0,
    ) -> None:
        """每个 Bot 使用独立台账和资源身份，规则策略没有动态投影。"""
        identifier = Identifier.parse(bot_id)
        if not identifier.path.startswith("bot/"):
            raise ValueError("记忆检查点必须属于 Bot 身份")
        check_positive_number(interval_seconds, "memory_model.checkpoint_seconds")
        self.scope = f"aurora:run/memory-model/{identifier.namespace}/{identifier.path}"
        self._bot_id = bot_id
        self._policy = policy
        self._artifacts = artifacts
        self._world = world
        self._interval = interval_seconds
        self._key = ResourceKey(identifier.namespace, "memory", "checkpoint", identifier.path)
        self._saved_digest: str | None = None
        self._initialized = False
        self._restored = False
        self._lock = asyncio.Lock()

    async def initialize(self) -> bool:
        """尝试最新自有检查点；失配和损坏不阻止 Bot 从原始事实继续。"""
        async with self._lock:
            if self._initialized:
                return self._restored
            if self._policy is not None:
                await self._world.initialize()
                head = await self._world.head(frozenset({self.scope}))
                sequence = head.sequence(self.scope)
                latest = await self._world.commits(self.scope, max(0, sequence - 1), 1)
                if latest:
                    self._restored = await self._restore(latest[-1])
            self._initialized = True
            return self._restored

    async def save(self) -> ArtifactInfo | None:
        """完整状态发布后才提交世界引用，只有历史改变才重新保存。"""
        async with self._lock:
            if self._policy is None:
                return None
            checkpoint = await asyncio.to_thread(self._policy.checkpoint, after=self._saved_digest)
            if checkpoint is None:
                return None
            await self._world.initialize()
            source = await self._world.stream(checkpoint.prefix.cursor - 1, 1)
            if (
                not source.commits
                or source.commits[0].cursor != checkpoint.prefix.cursor
                or source.commits[0].recorded_at != checkpoint.prefix.recorded_at
            ):
                raise ValueError("记忆检查点的历史边界不属于当前已知世界")
            info = await self._artifacts.put(self._key, checkpoint.content, media_type=MEMORY_CHECKPOINT_MEDIA_TYPE)
            owner = hashlib.sha256(self._bot_id.encode()).hexdigest()
            await self._world.append_commit(
                commit_id=f"memory-checkpoint:{owner}:{info.ref.revision}",
                kind=_CHECKPOINT_KIND,
                source="memory_model",
                summary="已保存记忆模型的动态节点检查点",
                scopes=frozenset({self.scope}),
                based_on=WorldFrontier(),
                data={
                    "schema_version": _SCHEMA_VERSION,
                    "bot_id": self._bot_id,
                    "model": {"key": str(checkpoint.model.key), "revision": checkpoint.model.revision},
                    "prefix": prefix_data(checkpoint.prefix),
                    "artifact": artifact_data(info),
                },
            )
            self._saved_digest = checkpoint.prefix.digest
            return info

    async def run(self, stop: asyncio.Event) -> None:
        """周期保存失败只影响加速状态，下个周期仍可重新尝试。"""
        if self._policy is None:
            await stop.wait()
            return
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._interval)
            except TimeoutError:
                try:
                    await self.save()
                except (ValueError, LookupError, OSError) as error:
                    _logger.warning("记忆检查点保存失败，下次继续尝试：{}", error)

    async def _restore(self, commit: WorldCommit) -> bool:
        """归属、内容版本和模型身份核对后，才把正文交给策略。"""
        if self._policy is None or commit.kind != _CHECKPOINT_KIND or commit.data.get("bot_id") != self._bot_id:
            return False
        try:
            data = commit.data
            if data["schema_version"] != _SCHEMA_VERSION:
                return False
            raw_model = data["model"]
            if not isinstance(raw_model, Mapping) or any(
                not isinstance(raw_model.get(key), str) for key in ("key", "revision")
            ):
                raise ValueError("记忆检查点的模型描述无效")
            model = ResourceRef(ResourceKey.parse(raw_model["key"]), raw_model["revision"])
            if model != self._policy.ref:
                return False
            prefix = read_prefix(data["prefix"])
            if prefix.cursor >= commit.cursor or commit.recorded_at is None or prefix.recorded_at > commit.recorded_at:
                raise ValueError("记忆检查点不能引用后来才获知的历史")
            info = read_artifact(data["artifact"])
            if info.ref.key != self._key or info.media_type != MEMORY_CHECKPOINT_MEDIA_TYPE:
                raise ValueError("记忆检查点资源身份或媒体类型不匹配")
            content = await artifact_content(self._artifacts, info)
            restored = await asyncio.to_thread(self._policy.restore, MemoryPolicyCheckpoint(model, prefix, content))
            if restored:
                self._saved_digest = prefix.digest
            return restored
        except (ValueError, TypeError, LookupError, OSError) as error:
            _logger.warning("记忆检查点不可恢复，将按实际世界历史重建：{}", error)
            return False
