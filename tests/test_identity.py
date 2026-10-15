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
    alias_path,
    is_namespace,
    is_path,
)
from src.utils import resolve_names

# 第三方 MCP Server 真的会给出这些名字；MCP SDK 对 Tool.name 不做任何格式约束。
_FOREIGN_NAMES = (
    "send_message",
    "read-file",
    "SendMessage",
    "send.message",
    "tool/read",
    "2fa_verify",
    "_private",
    "send:message",
    "send message",
    "消息发送",
    "-leading-dash",
    ".leading-dot",
    "",
    "   ",
    "a" * 200,
)


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


@pytest.mark.parametrize("raw", _FOREIGN_NAMES)
def test_alias_path_is_total_over_foreign_names(raw: str) -> None:
    """任何第三方名字都必须能落进命名空间，否则一个古怪名字会让进程起不来。"""
    aliased = alias_path(raw)

    assert is_path(aliased)
    assert aliased == alias_path(raw)


def test_alias_path_keeps_legal_names_verbatim() -> None:
    """合法即零映射：模型看到的就是服务器给的名字。"""
    for raw in ("send_message", "read-file", "SendMessage", "send.message", "tool/read", "2fa_verify", "_private"):
        assert alias_path(raw) == raw


def test_alias_path_is_a_pure_function_of_the_raw_name() -> None:
    """别名不能依赖服务器的工具集合，否则增删工具会让已有工具的 ID 漂移。"""
    assert alias_path("send:message") == alias_path("send:message")
    assert alias_path("send:message") != alias_path("send/ message")
    assert alias_path("消息发送") == alias_path("消息发送")


_ALIAS_LENGTH_LIMIT = 64
_ALIAS_DIGEST_TAIL = 9


@pytest.mark.parametrize("raw", ["send:message", "send message", "消息发送", "-leading-dash", ""])
def test_alias_path_output_is_readable_and_marked(raw: str) -> None:
    aliased = alias_path(raw)

    assert len(aliased) <= _ALIAS_LENGTH_LIMIT
    assert aliased.isascii()
    assert aliased[-_ALIAS_DIGEST_TAIL] == "-"
    assert all(char.isalnum() or char == "-" for char in aliased)


def test_alias_path_separates_names_that_would_otherwise_merge() -> None:
    """净化会把不同名字压成同一个 slug，哈希必须把它们分开。"""
    assert alias_path("send:message") != alias_path("send.message-x")
    assert alias_path("a b") != alias_path("a-b")


def test_tags_pass_through_entries_that_are_not_references() -> None:
    table = _table(TagDefinition("aurora:tool/qq", ("org.aurora.qq:tool/*",)))

    assert table.expand(("aurora:tool/delegate", "#aurora:tool/qq")) == (
        "aurora:tool/delegate",
        "org.aurora.qq:tool/*",
    )


def test_tags_expand_nested_definitions_in_writing_order() -> None:
    table = _table(
        TagDefinition("aurora:tool/send", ("org.aurora.qq:tool/qq_send_*message", "!org.aurora.qq:tool/skip")),
        TagDefinition("aurora:tool/qq", ("#aurora:tool/send", "org.aurora.qq:tool/qq_get_*")),
    )

    assert table.expand(("#aurora:tool/qq",)) == (
        "org.aurora.qq:tool/qq_send_*message",
        "!org.aurora.qq:tool/skip",
        "org.aurora.qq:tool/qq_get_*",
    )


def test_tag_expansion_keeps_last_match_wins_semantics() -> None:
    available = frozenset({"org.aurora.qq:tool/qq_send_message", "org.aurora.qq:tool/qq_send_forward_message"})
    table = _table(
        TagDefinition(
            "aurora:tool/qq-send",
            ("org.aurora.qq:tool/qq_send_*message", "!org.aurora.qq:tool/qq_send_forward_message"),
        )
    )

    resolved = resolve_names(available, table.expand(("#aurora:tool/qq-send",), label="builtin.chat"))

    assert resolved == frozenset({"org.aurora.qq:tool/qq_send_message"})


def test_tag_expansion_equals_writing_the_patterns_inline() -> None:
    patterns = (
        "org.aurora.qq:tool/qq_send_*message",
        "!org.aurora.qq:tool/qq_send_forward_message",
        "org.aurora.qq:tool/qq_get_*",
    )
    table = _table(TagDefinition("aurora:tool/qq-send", patterns))
    available = frozenset(
        {
            "org.aurora.qq:tool/qq_send_message",
            "org.aurora.qq:tool/qq_send_forward_message",
            "org.aurora.qq:tool/qq_get_profile",
            "com.github.windows_mcp:tool/click",
        }
    )

    assert resolve_names(available, table.expand(("#aurora:tool/qq-send",))) == resolve_names(available, patterns)


def test_undeclared_tag_is_rejected() -> None:
    table = _table(TagDefinition("aurora:tool/qq", ("org.aurora.qq:tool/*",)))

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
        "org.aurora.qq:tool/qq_send_*message",
        "!org.aurora.qq:tool/qq_send_forward_message",
        "org.aurora.qq:tool/qq_get_*",
        "org.aurora.qq:tool/qq_mark_*",
    )
