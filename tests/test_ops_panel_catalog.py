"""Panel 前端与本后端共享的目录快照，防止两侧漂移。"""

from __future__ import annotations

from ops.contracts import OperationScope
from ops.registry import iter_operations

_EXPECTED_HTTP = frozenset(
    {
        "GET /",
        "POST /process/shutdown",
        "GET /config",
        "GET /config/{name}",
        "POST /config/reload",
        "POST /apps/{package}/enabled",
        "POST /extensions/{extension_id}/enabled",
        "GET /engine/status",
        "GET /trees",
        "GET /trees/{tree_id}",
        "GET /trees/{tree_id}/nodes/{node_id}",
        "POST /trees",
        "POST /events",
        "GET /world/{scope}",
        "GET /forest",
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
        "POST /cadence/trigger",
        "GET /memory",
        "GET /mcp",
        "GET /mcp/{package}",
    }
)

_TEXT_ONLY = frozenset({"POST /console/clear"})
_EXPECTED_TOTAL = len(_EXPECTED_HTTP) + len(_TEXT_ONLY)


def test_panel_catalog_is_exactly_34_http_plus_1_text_only() -> None:
    entries = {f"{spec.method} {spec.path}" for spec in iter_operations()}
    text_only = {f"{spec.method} {spec.path}" for spec in iter_operations() if spec.scope is OperationScope.TEXT_ONLY}

    assert entries == _EXPECTED_HTTP | _TEXT_ONLY
    assert text_only == _TEXT_ONLY
    assert len(entries) == _EXPECTED_TOTAL
