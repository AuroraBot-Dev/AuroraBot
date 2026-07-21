"""Global Brain Context projection for Aurora's single-tenant persona."""

from __future__ import annotations

from typing import Any

from src.contracts.agent import BrainContextSnapshot, KernelConfiguration
from src.kernel.store import SQLiteRuntimeStore, utc_now


def build_brain_context(
    store: SQLiteRuntimeStore,
    configuration: KernelConfiguration,
) -> BrainContextSnapshot:
    tasks = store.tasks(active_only=True)
    agents = store.agents(active_only=True)
    task_projections: list[dict[str, Any]] = []
    for task in tasks:
        events = store.events_for_task(task.task_id)
        projection: dict[str, Any] = {
            "task_id": task.task_id,
            "status": task.status,
            "model_calls": task.model_calls,
            "tool_calls": task.tool_calls,
            "max_model_calls": task.max_model_calls,
            "max_tool_calls": task.max_tool_calls,
            "work_type": "autonomous" if task.autonomous else "interactive",
            "updated_at": task.updated_at,
            "session_id": task.session_id,
            "summary": task.root_summary,
            "latest_activity": events[-1]["summary"] if events else task.root_summary,
        }
        task_projections.append(projection)
    agent_projections: list[dict[str, Any]] = []
    for agent in agents:
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
    situations = store.situations()
    return BrainContextSnapshot(
        persona={"content": configuration.soul_content, "hash": configuration.soul_hash},
        active_tasks=tuple(task_projections),
        active_agents=tuple(agent_projections),
        ambient_situations=situations,
        generated_at=utc_now(),
    )
