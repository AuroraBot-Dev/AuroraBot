"""从认知树世界事实推导固定版本摘要，不保存另一套执行状态。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from aurorabot.contracts.resource import ResourceDescriptor, ResourceInstance, ResourceRef
from aurorabot.contracts.resource_codec import parse_resource_instance, parse_resource_ref, resource_instance_data
from aurorabot.contracts.tree_lifecycle import (
    TREE_COMPLETED,
    TREE_FAILED,
    TREE_INSTANCE_CONTRACT,
    TREE_STARTED,
    tree_scope,
)

if TYPE_CHECKING:
    from aurorabot.contracts.world import WorldCommit


@dataclass(frozen=True, slots=True)
class InstanceView:
    """某个世界前缀内的实例摘要，状态只描述已经提交的事实。"""

    instance: ResourceInstance
    start_commit_id: str
    start_cursor: int
    last_commit_id: str
    last_cursor: int
    commit_count: int = 1
    state: str = "started"

    @property
    def ref(self) -> ResourceRef:
        """实例版本由最后一个所属世界提交确定，后续提交产生新版本。"""
        return ResourceRef(self.instance.key, f"world_{self.last_cursor}")

    def advance(self, commit: WorldCommit) -> InstanceView:
        """归属域的每个新事实推进版本，只有规范终态事实能结束实例。"""
        state = self.state
        tree_id = self.instance.instance_id
        terminal = {TREE_COMPLETED: "completed", TREE_FAILED: "failed"}.get(commit.kind)
        if (
            terminal is not None
            and commit.source == "engine"
            and commit.data.get("tree_id") == tree_id
            and commit.commit_id == f"{tree_id}:tree:{terminal}"
        ):
            state = terminal
        return replace(
            self,
            last_commit_id=commit.commit_id,
            last_cursor=commit.cursor,
            commit_count=self.commit_count + 1,
            state=state,
        )

    def descriptor(self) -> ResourceDescriptor:
        """公开可追溯的固定摘要；开始事实不证明进程此刻仍在执行。"""
        return ResourceDescriptor(
            self.ref,
            "Bot 认知实例的世界记录摘要；started 表示已有开始事实，不能据此判断当前是否正在运行。",
            TREE_INSTANCE_CONTRACT,
            {
                "instance": resource_instance_data(self.instance),
                "state": self.state,
                "scope": tree_scope(self.instance.instance_id),
                "start_commit_id": self.start_commit_id,
                "start_cursor": self.start_cursor,
                "last_commit_id": self.last_commit_id,
                "as_of_cursor": self.last_cursor,
                "commit_count": self.commit_count,
            },
        )


def instance_start(commit: WorldCommit, bot_id: str) -> InstanceView | None:
    """只读取属于 Bot 的规范开始事实，缺少实例版本的记录不能靠现配置补齐。"""
    if commit.kind != TREE_STARTED or commit.source != "engine" or commit.data.get("bot_id") != bot_id:
        return None
    tree_id = commit.data.get("tree_id")
    if not isinstance(tree_id, str) or not tree_id.strip():
        return None
    if commit.commit_id != f"{tree_id}:tree:started" or tree_scope(tree_id) not in commit.scopes:
        return None
    if "instance" not in commit.data and "process_ref" not in commit.data:
        return None
    instance = parse_resource_instance(commit.data.get("instance"))
    process = parse_resource_ref(commit.data.get("process_ref"))
    if (
        instance.instance_id != tree_id
        or instance.bot_id != bot_id
        or instance.definition != process
        or process.key.domain != "engine"
        or process.key.kind != "process"
    ):
        raise ValueError(f"认知实例与开始事实的执行依据不一致：{commit.commit_id}")
    return InstanceView(instance, commit.commit_id, commit.cursor, commit.commit_id, commit.cursor)
