"""``aurora app search`` 的两组纯函数：查询串构造与参数校验。

这两件事都发生在发请求之前，不需要 transport，所以单独成文件。
"""

from __future__ import annotations

import pytest

from aurora.commands.app.github import (
    MAX_PAGE_SIZE,
    MAX_RESULTS,
    check_search_arguments,
)
from aurora.commands.app.models import ConfigError


@pytest.mark.parametrize("page_size", [0, -1, MAX_PAGE_SIZE + 1, 1000])
def test_a_page_size_outside_one_to_a_hundred_is_rejected(page_size: int) -> None:
    with pytest.raises(ConfigError, match="--page-size"):
        check_search_arguments(page=1, page_size=page_size, sort=None, order=None)


@pytest.mark.parametrize(("page", "page_size"), [(1, 1), (1, MAX_PAGE_SIZE), (50, 20), (10, MAX_PAGE_SIZE)])
def test_pages_inside_the_search_window_are_accepted(page: int, page_size: int) -> None:
    check_search_arguments(page=page, page_size=page_size, sort=None, order=None)


@pytest.mark.parametrize(("page", "page_size"), [(51, 20), (11, MAX_PAGE_SIZE), (MAX_RESULTS + 1, 1)])
def test_pages_beyond_the_search_window_are_rejected(page: int, page_size: int) -> None:
    """GitHub Search 只暴露前 1000 条；越界请求必然 422，不如就地拒绝。"""
    with pytest.raises(ConfigError, match=str(MAX_RESULTS)):
        check_search_arguments(page=page, page_size=page_size, sort=None, order=None)
