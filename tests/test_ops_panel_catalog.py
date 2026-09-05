"""Panel 前端与本后端共享的只读目录快照，防止两侧漂移。"""

from __future__ import annotations

from ops.registry import iter_operations

_EXPECTED = frozenset(
    {
        "GET /",
        "GET /config",
        "GET /config/{name}",
        "GET /engine/status",
        "GET /agents",
        "GET /agents/{agent_id}",
        "GET /agents/{agent_id}/tools",
        "GET /tools",
        "GET /tools/{tool_id}",
        "GET /prompts",
        "GET /prompts/{prompt_id}",
        "GET /models",
        "GET /models/{endpoint_id}",
        "GET /world/stream",
        "GET /world/commits/{commit_id}",
        "GET /console",
        "GET /utils",
        "GET /contracts",
        "GET /cadence",
        "GET /memory",
        "GET /mcp",
        "GET /mcp/{package}",
    }
)


def test_panel_catalog_contains_only_expected_get_observations() -> None:
    entries = {f"{spec.method} {spec.path}" for spec in iter_operations()}

    assert entries == _EXPECTED
    assert all(spec.method == "GET" for spec in iter_operations())
