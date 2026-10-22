from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aurora_bot.contracts.agent import AgentDefinition

AGENT_MEDIA_TYPE = "application/vnd.aurora.agent+json;version=1"


def agent_content(definition: AgentDefinition) -> bytes:
    """集合按名称排序，输入顺序不影响内容；任何声明变化都会产生不同正文。"""
    return json.dumps(
        {
            "schema_version": 1,
            "definition_id": definition.definition_id,
            "description": definition.description,
            "prompt_id": definition.prompt_id,
            "model": definition.model,
            "tools": sorted(definition.tools),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
