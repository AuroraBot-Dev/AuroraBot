"""Audience-aware Brain Context projection."""

from __future__ import annotations

from typing import Any

from src.contracts.agent import BrainContextSnapshot, KernelConfiguration
from src.kernel.store import SQLiteRuntimeStore, utc_now


def build_brain_context(
    store: SQLiteRuntimeStore,
    configuration: KernelConfiguration,
    *,
    audience_ref: str,
    current_task_id: str | None,
) -> BrainContextSnapshot:
    tasks = store.tasks(active_only=True)
    agents = store.agents(active_only=True)
    task_audiences = {task.task_id: task.audience_ref for task in tasks}
    task_projections: list[dict[str, Any]] = []
    for task in tasks:
        shared = task.task_id == current_task_id or task.audience_ref == audience_ref
        projection: dict[str, Any] = {
            "task_id": task.task_id,
            "status": task.status,
            "model_calls": task.model_calls,
            "tool_calls": task.tool_calls,
            "max_model_calls": task.max_model_calls,
            "max_tool_calls": task.max_tool_calls,
            "work_type": "autonomous" if task.autonomous else "interactive",
            "updated_at": task.updated_at,
        }
        if shared:
            events = store.events_for_task(task.task_id)
            projection.update(
                {
                    "session_id": task.session_id,
                    "audience_ref": task.audience_ref,
                    "summary": task.root_summary,
                    "latest_activity": events[-1]["summary"] if events else task.root_summary,
                }
            )
        task_projections.append(projection)
    agent_projections: list[dict[str, Any]] = []
    for agent in agents:
        if agent.task_id != current_task_id and task_audiences.get(agent.task_id) != audience_ref:
            continue
        projection = {
            "agent_id": agent.agent_id,
            "task_id": agent.task_id,
            "parent_agent_id": agent.parent_agent_id,
            "profile_id": agent.profile_id,
            "status": agent.status,
            "updated_at": agent.updated_at,
        }
        projection.update({"assignment": agent.assignment, "last_summary": agent.last_summary})
        agent_projections.append(projection)
    situations = tuple(
        situation
        for situation in store.situations()
        if situation["audience_ref"] == audience_ref or _system_audience(str(situation["audience_ref"]))
    )
    return BrainContextSnapshot(
        persona={"content": configuration.soul_content, "hash": configuration.soul_hash},
        active_tasks=tuple(task_projections),
        active_agents=tuple(agent_projections),
        ambient_situations=situations,
        generated_at=utc_now(),
    )


def _system_audience(audience_ref: str) -> bool:
    return audience_ref == "system.local" or audience_ref.endswith(":system")
