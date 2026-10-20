"""即时路由策略以数据形式加载，而不是硬编码在 Python 里。"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from aurora.configs.reactions import CONFIG_SPEC as REACTIONS_CONFIG
from aurora.configurator import assemble_config
from aurorabot.cadence import ReactiveRule
from aurorabot.cadence.config import ReactionConfig, ReactionsConfig
from aurorabot.contracts import MCP_EVENT_RECEIVED, WorldCommit, WorldFrontier
from tests import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

_TEMPLATE = (
    ReactionConfig("mcp:org.aurora.qq", "qq.message.private", "aurora:agent/definition/chat", ()),
    ReactionConfig("mcp:org.aurora.qq", "qq.message.group", "aurora:agent/definition/chat", ("小光", "夜曦光")),
)


def _commit(source: str, event_kind: str, summary: str) -> WorldCommit:
    return WorldCommit(
        "commit",
        MCP_EVENT_RECEIVED,
        source,
        summary,
        datetime(2026, 1, 1, tzinfo=UTC),
        {"org.aurora.qq:world": 1},
        WorldFrontier(),
        {"event_kind": event_kind},
    )


def _rules(reactions: tuple[ReactionConfig, ...]) -> tuple[ReactiveRule, ...]:
    return tuple(
        ReactiveRule(item.source, item.event_kind, item.agent, item.contains_any)
        for item in ReactionsConfig(reactions).reactions
    )


def test_template_declares_reaction_rules_as_data(tmp_path: Path) -> None:
    shutil.copytree(PROJECT_ROOT / "config.example", tmp_path / "config")

    reactions = assemble_config(tmp_path, (REACTIONS_CONFIG,)).get(REACTIONS_CONFIG).reactions

    assert reactions == _TEMPLATE


def test_declared_rules_route_private_and_mentioning_group_messages() -> None:
    rules = _rules(_TEMPLATE)

    private = _commit("mcp:org.aurora.qq", "qq.message.private", "你好")
    mentioning = _commit("mcp:org.aurora.qq", "qq.message.group", "小光在吗")
    quiet = _commit("mcp:org.aurora.qq", "qq.message.group", "路人闲聊")

    assert [rule.agent for rule in rules if rule.matches(private)] == ["aurora:agent/definition/chat"]
    assert [rule.agent for rule in rules if rule.matches(mentioning)] == ["aurora:agent/definition/chat"]
    assert [rule.agent for rule in rules if rule.matches(quiet)] == []


@pytest.mark.parametrize(
    "content",
    [
        "",
        '[[reaction]]\nsource = "mcp:a"\n',
        '[[reaction]]\nsource = ""\nevent_kind = "x"\nagent = "aurora:agent/definition/chat"\ncontains_any = []\n',
        '[[reaction]]\nsource = "mcp:a"\nevent_kind = "x"\nagent = "aurora:agent/definition/chat"\nunknown = 1\n',
    ],
)
def test_reaction_template_rejects_incomplete_or_unknown_fields(tmp_path: Path, content: str) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "reactions.toml").write_text(content, encoding="utf-8")

    with pytest.raises((ValueError, KeyError, TypeError)):
        assemble_config(tmp_path, (REACTIONS_CONFIG,))
