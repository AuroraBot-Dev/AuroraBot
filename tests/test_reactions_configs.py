"""即时路由策略以数据形式加载，而不是硬编码在 Python 里。"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aurora.configs.reactions import REACTIONS_CONFIG
from aurora.configurator import assemble_config
from src.cadence import ReactiveRule
from src.cadence.config import ReactionConfig, ReactionsConfig
from src.contracts import MCP_EVENT_RECEIVED, WorldCommit, WorldFrontier

_TEMPLATE = (
    ReactionConfig("mcp:org.aurora.qq", "qq.message.private", "builtin.chat", ()),
    ReactionConfig("mcp:org.aurora.qq", "qq.message.group", "builtin.chat", ("小光", "夜曦光")),
)


def _commit(source: str, event_kind: str, summary: str) -> WorldCommit:
    return WorldCommit(
        "commit",
        MCP_EVENT_RECEIVED,
        source,
        summary,
        datetime(2026, 1, 1, tzinfo=UTC),
        {"aurora:mcp:org.aurora.qq": 1},
        WorldFrontier(),
        {"event_kind": event_kind},
    )


def _rules(reactions: tuple[ReactionConfig, ...]) -> tuple[ReactiveRule, ...]:
    return tuple(
        ReactiveRule(item.source, item.event_kind, item.agent, item.contains_any)
        for item in ReactionsConfig(reactions).reactions
    )


def test_template_declares_reaction_rules_as_data(tmp_path: Path) -> None:
    shutil.copytree(Path(__file__).parents[1] / "config.example", tmp_path / "config")

    reactions = assemble_config(tmp_path, (REACTIONS_CONFIG,)).get(REACTIONS_CONFIG).reactions

    assert reactions == _TEMPLATE


def test_declared_rules_route_private_and_mentioning_group_messages() -> None:
    rules = _rules(_TEMPLATE)

    private = _commit("mcp:org.aurora.qq", "qq.message.private", "你好")
    mentioning = _commit("mcp:org.aurora.qq", "qq.message.group", "小光在吗")
    quiet = _commit("mcp:org.aurora.qq", "qq.message.group", "路人闲聊")

    assert [rule.agent for rule in rules if rule.matches(private)] == ["builtin.chat"]
    assert [rule.agent for rule in rules if rule.matches(mentioning)] == ["builtin.chat"]
    assert [rule.agent for rule in rules if rule.matches(quiet)] == []


@pytest.mark.parametrize(
    "content",
    [
        "",
        '[[reaction]]\nsource = "mcp:a"\n',
        '[[reaction]]\nsource = ""\nevent_kind = "x"\nagent = "builtin.chat"\ncontains_any = []\n',
        '[[reaction]]\nsource = "mcp:a"\nevent_kind = "x"\nagent = "builtin.chat"\nunknown = 1\n',
    ],
)
def test_reaction_template_rejects_incomplete_or_unknown_fields(tmp_path: Path, content: str) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "reactions.toml").write_text(content, encoding="utf-8")

    with pytest.raises((ValueError, KeyError, TypeError)):
        assemble_config(tmp_path, (REACTIONS_CONFIG,))
