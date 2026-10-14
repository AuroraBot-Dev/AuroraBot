"""横向身份层：命名空间 ID 与标签集合。"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from aurora.configs.tags import TAGS_CONFIG
from aurora.configurator import assemble_config
from src.contracts.identity import (
    DEFAULT_NAMESPACE,
    Identifier,
    IdentityError,
    TagDefinition,
    TagsConfig,
    TagTable,
    is_namespace,
    is_path,
)
from src.utils import resolve_names


def _table(*tags: TagDefinition) -> TagTable:
    return TagsConfig(tags).table


def test_identifier_round_trips_namespace_and_path() -> None:
    identifier = Identifier.parse("org.aurora.qq:tool/qq_send_message")

    assert str(identifier) == "org.aurora.qq:tool/qq_send_message"
    assert identifier.namespace == "org.aurora.qq"
    assert identifier.path == "tool/qq_send_message"


def test_identifier_falls_back_to_the_default_namespace() -> None:
    assert str(Identifier.parse("tool/delegate", default_namespace="aurora")) == "aurora:tool/delegate"
    with pytest.raises(IdentityError, match="缺少命名空间"):
        Identifier.parse("agent/delegate")
    assert str(Identifier.parse("agent/delegate", default_namespace=DEFAULT_NAMESPACE)) == "aurora:agent/delegate"


@pytest.mark.parametrize(
    "text",
    ["", "   ", ":path", "aurora:", "Aurora:path", "aurora:tool//x", "aurora:tool/", "#aurora:tool/x"],
)
def test_identifier_rejects_malformed_text(text: str) -> None:
    with pytest.raises(IdentityError):
        Identifier.parse(text)


def test_upper_case_is_allowed_only_in_the_path() -> None:
    assert str(Identifier.parse("org.aurora.qq:qq_sendMessage")) == "org.aurora.qq:qq_sendMessage"
    assert Identifier.optional("AURORA:tool/x") is None
    assert Identifier.optional("aurora:tool/x") is not None


def test_namespace_and_path_predicates() -> None:
    assert is_namespace("aurora")
    assert is_namespace("org.aurora.qq")
    assert not is_namespace("Aurora")
    assert is_path("tool/qq_send_message")
    assert not is_path("/tool")


def test_tags_pass_through_entries_that_are_not_references() -> None:
    table = _table(TagDefinition("aurora:tool/qq", ("aur.mcp.org.aurora.qq.*",)))

    assert table.expand(("aur.agent.delegate", "#aurora:tool/qq")) == (
        "aur.agent.delegate",
        "aur.mcp.org.aurora.qq.*",
    )


def test_tags_expand_nested_definitions_in_writing_order() -> None:
    table = _table(
        TagDefinition("aurora:tool/send", ("aur.mcp.org.aurora.qq.qq_send_*message", "!aur.mcp.org.aurora.qq.skip")),
        TagDefinition("aurora:tool/qq", ("#aurora:tool/send", "aur.mcp.org.aurora.qq.qq_get_*")),
    )

    assert table.expand(("#aurora:tool/qq",)) == (
        "aur.mcp.org.aurora.qq.qq_send_*message",
        "!aur.mcp.org.aurora.qq.skip",
        "aur.mcp.org.aurora.qq.qq_get_*",
    )


def test_tag_expansion_keeps_last_match_wins_semantics() -> None:
    available = frozenset({"aur.mcp.org.aurora.qq.qq_send_message", "aur.mcp.org.aurora.qq.qq_send_forward_message"})
    table = _table(
        TagDefinition(
            "aurora:tool/qq-send",
            ("aur.mcp.org.aurora.qq.qq_send_*message", "!aur.mcp.org.aurora.qq.qq_send_forward_message"),
        )
    )

    resolved = resolve_names(available, table.expand(("#aurora:tool/qq-send",), label="builtin.chat"))

    assert resolved == frozenset({"aur.mcp.org.aurora.qq.qq_send_message"})


def test_tag_expansion_equals_writing_the_patterns_inline() -> None:
    patterns = (
        "aur.mcp.org.aurora.qq.qq_send_*message",
        "!aur.mcp.org.aurora.qq.qq_send_forward_message",
        "aur.mcp.org.aurora.qq.qq_get_*",
    )
    table = _table(TagDefinition("aurora:tool/qq-send", patterns))
    available = frozenset(
        {
            "aur.mcp.org.aurora.qq.qq_send_message",
            "aur.mcp.org.aurora.qq.qq_send_forward_message",
            "aur.mcp.org.aurora.qq.qq_get_profile",
            "aur.mcp.com.github.windows_mcp.click",
        }
    )

    assert resolve_names(available, table.expand(("#aurora:tool/qq-send",))) == resolve_names(available, patterns)


def test_undeclared_tag_is_rejected() -> None:
    table = _table(TagDefinition("aurora:tool/qq", ("aur.mcp.org.aurora.qq.*",)))

    with pytest.raises(IdentityError, match="未声明的标签"):
        table.expand(("#aurora:tool/missing",), label="builtin.chat")


def test_tag_cycles_are_rejected() -> None:
    table = _table(
        TagDefinition("aurora:a", ("#aurora:b",)),
        TagDefinition("aurora:b", ("#aurora:a",)),
    )

    with pytest.raises(IdentityError, match="循环引用"):
        table.expand(("#aurora:a",))


def test_tag_nesting_is_bounded() -> None:
    tags = tuple(TagDefinition(f"aurora:level{index}", (f"#aurora:level{index + 1}",)) for index in range(20))
    table = _table(*tags, TagDefinition("aurora:level20", ("aur.x.y",)))

    with pytest.raises(IdentityError, match="嵌套超过"):
        table.expand(("#aurora:level0",))


def test_tag_definition_requires_a_valid_name_and_non_empty_values() -> None:
    with pytest.raises(IdentityError):
        TagDefinition("Aurora:tool/x", ("aur.x.y",))
    with pytest.raises(IdentityError):
        TagDefinition("aurora:tool/x", ())
    with pytest.raises(IdentityError):
        TagDefinition("aurora:tool/x", ("",))


def test_duplicate_tag_declarations_are_rejected() -> None:
    with pytest.raises(IdentityError, match="标签重复声明"):
        TagsConfig(
            (
                TagDefinition("aurora:tool/x", ("aur.x.y",)),
                TagDefinition("aurora:tool/x", ("aur.x.z",)),
            )
        )


def test_template_declares_a_nested_tag_collection(tmp_path: Path) -> None:
    shutil.copytree(Path(__file__).parents[1] / "config.example", tmp_path / "config")
    config = assemble_config(tmp_path, (TAGS_CONFIG,))
    table = config.get(TAGS_CONFIG).table

    assert table.names == {"aurora:tool/qq-send", "aurora:tool/qq-read", "aurora:tool/qq"}
    assert table.expand(("#aurora:tool/qq",)) == (
        "aur.mcp.org.aurora.qq.qq_send_*message",
        "!aur.mcp.org.aurora.qq.qq_send_forward_message",
        "aur.mcp.org.aurora.qq.qq_get_*",
        "aur.mcp.org.aurora.qq.qq_mark_*",
    )
