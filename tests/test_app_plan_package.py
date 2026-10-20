"""package ID 的规范化、校验与查重。

默认 package 是 ``github.<owner>.<repo>``；两段各自走同一套六步规则，不是对整
个字符串走一遍——``acme/2fast`` 的 repo 段要加前缀、owner 段不加，否则
``github.acme.2fast`` 通不过点分包名规则。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from aurora.commands.app.install import (
    check_package_collision,
    check_user_package,
    derive_package,
    normalize_segment,
)
from aurora.commands.app.models import PlanError
from aurora.commands.app.store import AppStore
from tests.app_clone_support import APP_PACKAGE, CONFLICTING_PACKAGE, project, registry_entry

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("weather-mcp", "weather-mcp"),
        ("Aurora-QQ", "aurora-qq"),
        ("My.Repo", "my-repo"),
        ("a b", "a-b"),
        ("a--b", "a-b"),
        ("a..b", "a-b"),
        ("-leading-", "leading"),
        ("_kernel", "app-_kernel"),
        ("2fast", "app-2fast"),
        ("_", "app-_"),
        ("", "app"),
        ("...", "app"),
    ],
)
def test_normalize_segment_follows_the_six_rules(value: str, expected: str) -> None:
    assert normalize_segment(value) == expected


def test_prefix_is_decided_per_segment_not_for_the_whole_string() -> None:
    """acme 段没加前缀、2fast 段加了，两段各自判断。"""
    assert derive_package("acme/2fast") == "github.acme.app-2fast"


@pytest.mark.parametrize(
    ("full_name", "expected"),
    [
        ("example/weather-mcp", "github.example.weather-mcp"),
        ("Owner/My.Repo", "github.owner.my-repo"),
        ("acme/2fast", "github.acme.app-2fast"),
        ("Churk-Ben/Aurora-QQ", "github.churk-ben.aurora-qq"),
    ],
)
def test_derived_package_is_github_owner_repo(full_name: str, expected: str) -> None:
    assert derive_package(full_name) == expected


@pytest.mark.parametrize(
    "full_name",
    ["example/weather-mcp", "Owner/My.Repo", "acme/2fast", "a/_", "0/0"],
)
def test_every_derived_package_passes_the_shared_package_rule(full_name: str) -> None:
    """推导出来的一定能过校验，否则失败会晚一步出现在 AppConfig 里。"""
    assert check_user_package(derive_package(full_name)) == derive_package(full_name)


@pytest.mark.parametrize("value", ["github.example.weather-mcp", "com.example.a1", "org.aurora.qq"])
def test_valid_explicit_packages_are_accepted(value: str) -> None:
    assert check_user_package(value) == value


@pytest.mark.parametrize(
    "value",
    ["weather-mcp", "Github.Example.Weather", "github..weather", "github.example.-q", "github.example.weather mcp"],
)
def test_invalid_explicit_packages_are_plan_errors(value: str) -> None:
    with pytest.raises(PlanError) as failure:
        check_user_package(value)

    assert "--package" in str(failure.value)


def test_missing_registry_is_not_a_conflict(tmp_path: Path) -> None:
    """config/ 是 git 忽略的个人配置，没有它就没有冲突可谈。"""
    check_package_collision(AppStore(project(tmp_path)), APP_PACKAGE)


def test_distinct_package_is_not_a_conflict(tmp_path: Path) -> None:
    store = AppStore(project(tmp_path, registry_entry()))

    check_package_collision(store, APP_PACKAGE)


def test_existing_package_is_rejected_without_renaming(tmp_path: Path) -> None:
    """package 是长期 identity，自动加 -2、-3 会让「我装的是哪个」无法回答。"""
    store = AppStore(project(tmp_path, registry_entry(CONFLICTING_PACKAGE)))

    with pytest.raises(PlanError) as failure:
        check_package_collision(store, CONFLICTING_PACKAGE)

    message = str(failure.value)
    assert CONFLICTING_PACKAGE in message
    assert "--package" in message
    assert "-2" not in message
