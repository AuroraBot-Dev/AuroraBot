"""``aurora app`` 的用例编排层；只调用协作者，不直接触碰文件、TOML 与网络。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora.commands.app.github import DEFAULT_PAGE, DEFAULT_PAGE_SIZE
from aurora.commands.app.models import validate_package

if TYPE_CHECKING:
    from aurora.commands.app.github import GitHubSource
    from aurora.commands.app.models import AppList, RepositoryPage
    from aurora.commands.app.store import AppStore


class AppManager:
    """把 CLI 意图翻译成注册表读写与仓库发现用例。"""

    def __init__(self, store: AppStore, source: GitHubSource) -> None:
        self.store = store
        self.source = source

    def list_apps(self) -> AppList:
        """列出注册表条目及其就绪状态。"""
        return self.store.list_apps()

    def enable(self, package: str) -> bool:
        """允许 App 在下次 aurora start 时启动；返回是否实际改动了注册表。"""
        return self.store.set_enabled(validate_package(package), True)

    def disable(self, package: str) -> bool:
        """禁止 App 在下次 aurora start 时启动；返回是否实际改动了注册表。"""
        return self.store.set_enabled(validate_package(package), False)

    def search_apps(
        self,
        query: str | None = None,
        *,
        page: int = DEFAULT_PAGE,
        page_size: int = DEFAULT_PAGE_SIZE,
        sort: str | None = None,
        order: str | None = None,
    ) -> RepositoryPage:
        """搜索候选仓库。

        不读也不写注册表 —— search 与 ``config/apps.toml`` 无关。
        """
        return self.source.search(query, page=page, page_size=page_size, sort=sort, order=order)


__all__ = ["AppManager"]
