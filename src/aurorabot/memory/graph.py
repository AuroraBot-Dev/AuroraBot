"""把世界提交投影成按获知顺序排列的类型化记忆图。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurorabot.contracts.memory_graph import MemoryInteraction, MemoryNode
from aurorabot.memory.records import memory_links, memory_text

if TYPE_CHECKING:
    from aurorabot.contracts.memory_graph import MemoryNodeKind
    from aurorabot.contracts.world import WorldCommit


def graph_interactions(history: tuple[WorldCommit, ...]) -> tuple[MemoryInteraction, ...]:
    """节点特征只在首次获知或更新时出现，不提前引用后来内容。"""
    events: list[MemoryInteraction] = []
    seen: dict[str, str] = {}
    for commit in history:
        if commit.recorded_at is None:
            raise ValueError("记忆图需要世界提交的获知时间")
        node = MemoryNode("memory", commit.commit_id, memory_text(commit))
        seen[commit.commit_id] = node.text
        links = [("experience", node)]
        links.extend(("scope", MemoryNode("scope", scope, scope)) for scope in sorted(commit.scopes))
        node_kinds: tuple[tuple[str, MemoryNodeKind], ...] = (("goal_ids", "goal"), ("entity_ids", "entity"))
        for name, kind in node_kinds:
            links.extend((kind, MemoryNode(kind, identity, identity)) for identity in memory_links(commit, name))
        for relation in ("depends_on", "supersedes"):
            links.extend(
                (relation, MemoryNode("memory", identity, seen.get(identity, "")))
                for identity in memory_links(commit, relation)
            )
        events.extend(
            MemoryInteraction(commit.cursor, commit.recorded_at, node, target, relation) for relation, target in links
        )
        feedback = _feedback(commit)
        if feedback is not None:
            goal_id, memory_id, helpful = feedback
            events.append(
                MemoryInteraction(
                    commit.cursor,
                    commit.recorded_at,
                    MemoryNode("goal", goal_id, goal_id),
                    MemoryNode("memory", memory_id, seen.get(memory_id, "")),
                    "useful" if helpful else "unhelpful",
                )
            )
    return tuple(events)


def _feedback(commit: WorldCommit) -> tuple[str, str, bool] | None:
    """只有显式反馈事件更新采用关系，普通曝光不被当成收益。"""
    if commit.kind != "memory.feedback":
        return None
    goal_id, memory_id, helpful = (commit.data.get(field) for field in ("goal_id", "memory_id", "helpful"))
    if not isinstance(goal_id, str) or not isinstance(memory_id, str) or not isinstance(helpful, bool):
        return None
    if not goal_id.strip() or not memory_id.strip():
        return None
    return goal_id, memory_id, helpful
