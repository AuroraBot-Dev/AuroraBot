"""``aurora app search`` 的两组纯函数：查询串构造与参数校验。

这两件事都发生在发请求之前，不需要 transport，所以单独成文件。
"""

from __future__ import annotations

import pytest

from aurora.commands.app.github import (
    MAX_PAGE_SIZE,
    MAX_RESULTS,
    TOPIC_CLAUSE,
    build_search_query,
    check_search_arguments,
)
from aurora.commands.app.models import ConfigError

# --- 查询构造 -----------------------------------------------------------------


@pytest.mark.parametrize("query", [None, "", "   ", "\t\n"])
def test_an_empty_query_leaves_only_the_topic_query(query: str | None) -> None:
    assert build_search_query(query) == TOPIC_CLAUSE


def test_a_query_is_appended_after_the_topic_query() -> None:
    assert build_search_query("clock") == f"{TOPIC_CLAUSE} clock"


def test_surrounding_whitespace_is_trimmed() -> None:
    assert build_search_query("  clock  ") == f"{TOPIC_CLAUSE} clock"


def test_github_qualifiers_are_passed_through_untouched() -> None:
    """不解析高级搜索语法：``language:python`` 是给 GitHub 的，不是给我们解析的。"""
    assert build_search_query("weather language:python") == f"{TOPIC_CLAUSE} weather language:python"


# --- 参数校验 -----------------------------------------------------------------


@pytest.mark.parametrize("page", [0, -1])
def test_a_page_below_one_is_rejected(page: int) -> None:
    with pytest.raises(ConfigError, match="--page"):
        check_search_arguments(page=page, page_size=20, sort=None, order=None)


@pytest.mark.parametrize("page_size", [0, -1, MAX_PAGE_SIZE + 1, 1000])
def test_a_page_size_outside_one_to_a_hundred_is_rejected(page_size: int) -> None:
    with pytest.raises(ConfigError, match="--page-size"):
        check_search_arguments(page=1, page_size=page_size, sort=None, order=None)


@pytest.mark.parametrize(
    ("sort", "order"),
    [("stars", None), ("forks", None), ("updated", "asc"), ("stars", "desc"), (None, None)],
)
def test_legal_sort_combinations_pass(sort: str | None, order: str | None) -> None:
    check_search_arguments(page=1, page_size=20, sort=sort, order=order)


@pytest.mark.parametrize(
    ("sort", "order"),
    [("name", None), ("Stars", None), ("stars", "up"), ("stars", "ascending"), (None, "desc")],
)
def test_illegal_sort_combinations_are_rejected(sort: str | None, order: str | None) -> None:
    with pytest.raises(ConfigError):
        check_search_arguments(page=1, page_size=20, sort=sort, order=order)


def test_order_without_sort_is_rejected() -> None:
    """不传 sort 时 GitHub 用 best match；单给 order 说明用户误以为它管排序。"""
    with pytest.raises(ConfigError, match="--order"):
        check_search_arguments(page=1, page_size=20, sort=None, order="asc")


@pytest.mark.parametrize(("page", "page_size"), [(1, 1), (1, MAX_PAGE_SIZE), (50, 20), (10, MAX_PAGE_SIZE)])
def test_pages_inside_the_search_window_are_accepted(page: int, page_size: int) -> None:
    check_search_arguments(page=page, page_size=page_size, sort=None, order=None)


@pytest.mark.parametrize(("page", "page_size"), [(51, 20), (11, MAX_PAGE_SIZE), (MAX_RESULTS + 1, 1)])
def test_pages_beyond_the_search_window_are_rejected(page: int, page_size: int) -> None:
    """GitHub Search 只暴露前 1000 条；越界请求必然 422，不如就地拒绝。"""
    with pytest.raises(ConfigError, match=str(MAX_RESULTS)):
        check_search_arguments(page=page, page_size=page_size, sort=None, order=None)
