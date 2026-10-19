"""``install_transaction`` 的提交与回滚：stage → final、注册表条目与残留报告。

文件系统是真的（``tmp_path``），注册表是真的 ``config/apps.toml``，锁是真的目录。
只替换「写注册表」这一个动作来制造提交失败，因为它是链路上唯一一处 Aurora 自己
决定成败、且失败之后必须回滚文件系统的位置。
"""

from __future__ import annotations

import tomllib
from typing import TYPE_CHECKING

import pytest
from app_clone_support import apps_root_entries, project, registry_entry
from app_install_support import (
    DEFAULT_COMMIT,
    WEATHER_PACKAGE,
    WEATHER_PATH,
    plan,
    staging,
    write_origin,
)

from aurora.commands.app.install import PreparedInstall
from aurora.commands.app.models import InstallError, PlanError, RawApp, RegistryWriteError
from aurora.commands.app.store import APPS_RELATIVE_PATH, AppStore
from aurora.commands.app.transaction import install_transaction, plan_removal, read_origin
from aurora.configs.apps import CONFIG_SPEC as APPS_CONFIG
from aurora.configurator import assemble_config

if TYPE_CHECKING:
    from pathlib import Path

_OWNER = "example"
_REPO = "weather-mcp"
_FINAL_PARTS = ("extensions", "apps", _OWNER, _REPO)
_STAGING_NAME = ".aurora-stage-abc123"
_EMPTY_REGISTRY = "app = []\n"
_ORIGIN_URL = "https://github.com/example/weather-mcp.git"


def _store(tmp_path: Path, apps_toml: str | None = _EMPTY_REGISTRY) -> AppStore:
    return AppStore(project(tmp_path, apps_toml))


def _prepared(root: Path, **overrides: object) -> PreparedInstall:
    """一份 staging 里带一个文件的安装上下文。"""
    stage = root / "extensions" / "apps" / _STAGING_NAME
    files = {"pyproject.toml": "[project]\n"}
    return PreparedInstall(plan=plan(**overrides), staging=staging(stage, files))  # type: ignore[arg-type]


def _entries(store: AppStore) -> list[dict[str, object]]:
    document = tomllib.loads((store.project_root / APPS_RELATIVE_PATH).read_text(encoding="utf-8"))
    return document["app"]


def _failing_write(*_args: object, **_kwargs: object) -> None:
    raise RegistryWriteError("无法写入 apps.toml：磁盘满了")


def _cannot_undo(_staging: Path, destination: Path, **_kwargs: object) -> Path:
    """模拟「回滚那一步也失败了」：把残留报成目标目录本身。"""
    return destination


def test_publish_moves_staging_to_the_final_path(tmp_path: Path) -> None:
    store = _store(tmp_path)
    prepared = _prepared(store.project_root)

    install_transaction(store, prepared)

    final = store.project_root.joinpath(*_FINAL_PARTS)
    assert (final / "pyproject.toml").is_file()
    assert not prepared.staging.root.exists(), "提交之后 staging 必须已经不在"


def test_registry_entry_has_exactly_the_eight_whitelist_fields(tmp_path: Path) -> None:
    store = _store(tmp_path)

    install_transaction(store, _prepared(store.project_root))

    entries = _entries(store)
    assert len(entries) == 1
    assert entries[0] == {
        "package": WEATHER_PACKAGE,
        "enabled": False,
        "transport": "stdio",
        "working_dir": WEATHER_PATH,
        "command": ["uv", "run", "weather-mcp"],
        "env": [],
        "timeout_seconds": 60.0,
        "event_mode": "disabled",
    }


def test_the_written_entry_is_readable_by_the_runtime_parser(tmp_path: Path) -> None:
    """比「单独构造一遍 AppConfig」更强的一条：装完真的能被 ``aurora start`` 读出来。

    运行时那份解析器对 stdio 条目做的是白名单校验（恰好八个 key），所以只有走完
    真实的写入再走真实的读取，才回答了「这个 App 装完到底能不能启动」。
    """
    store = _store(tmp_path)
    prepared = _prepared(store.project_root)

    install_transaction(store, prepared)

    apps = assemble_config(store.project_root, (APPS_CONFIG,)).get(APPS_CONFIG).apps
    assert len(apps) == 1
    assert apps[0].package == prepared.plan.package
    assert apps[0].working_dir == prepared.plan.working_dir
    assert apps[0].command == prepared.plan.command


def test_the_plan_commit_is_not_a_registry_field(tmp_path: Path) -> None:
    """注册表只声明「有哪些 App、怎么启动」；HEAD 属于计划，不属于 schema。"""
    store = _store(tmp_path)

    install_transaction(store, _prepared(store.project_root))

    assert "commit" not in _entries(store)[0]
    assert _prepared(store.project_root).plan.commit == DEFAULT_COMMIT


def test_default_installation_is_disabled(tmp_path: Path) -> None:
    store = _store(tmp_path)

    install_transaction(store, _prepared(store.project_root))

    assert _entries(store)[0]["enabled"] is False


def test_enabled_plan_writes_enabled_true(tmp_path: Path) -> None:
    store = _store(tmp_path)

    install_transaction(store, _prepared(store.project_root, enabled=True))

    assert _entries(store)[0]["enabled"] is True


def test_the_new_entry_is_appended_after_existing_ones(tmp_path: Path) -> None:
    store = _store(tmp_path, registry_entry("com.example.occupied", "src/apps/occupied"))

    install_transaction(store, _prepared(store.project_root))

    packages = [entry["package"] for entry in _entries(store)]
    assert packages == ["com.example.occupied", WEATHER_PACKAGE]


def test_owner_directory_is_created(tmp_path: Path) -> None:
    store = _store(tmp_path)

    install_transaction(store, _prepared(store.project_root))

    assert (store.project_root / "extensions" / "apps" / _OWNER / _REPO).is_dir()


def test_a_pre_existing_owner_directory_is_reused(tmp_path: Path) -> None:
    """第二次装同一个 owner 时不能再建一级目录，也不能把它当成自己建的。"""
    store = _store(tmp_path)
    sibling = store.project_root / "extensions" / "apps" / _OWNER / "other-app"
    sibling.mkdir(parents=True)

    install_transaction(store, _prepared(store.project_root))

    assert sibling.is_dir()


def test_registry_failure_rolls_the_final_directory_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """注册失败后目录回到暂存区，正式目录与注册表保持执行前的状态。"""
    store = _store(tmp_path)
    prepared = _prepared(store.project_root)
    monkeypatch.setattr(AppStore, "add_app", _failing_write)

    with pytest.raises(RegistryWriteError):
        install_transaction(store, prepared)

    assert not store.project_root.joinpath(*_FINAL_PARTS).exists()
    assert _entries(store) == []
    assert prepared.staging.root.joinpath("pyproject.toml").is_file(), "内容必须回到 staging"


def test_registry_failure_removes_the_owner_directory_it_created(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    monkeypatch.setattr(AppStore, "add_app", _failing_write)

    with pytest.raises(RegistryWriteError):
        install_transaction(store, _prepared(store.project_root))

    assert not (store.project_root / "extensions" / "apps" / _OWNER).exists()


def test_registry_failure_keeps_a_pre_existing_owner_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """回滚只删「这次新建的那一级」：删掉别人的目录是不可接受的。"""
    store = _store(tmp_path)
    sibling = store.project_root / "extensions" / "apps" / _OWNER / "other-app"
    sibling.mkdir(parents=True)
    monkeypatch.setattr(AppStore, "add_app", _failing_write)

    with pytest.raises(RegistryWriteError):
        install_transaction(store, _prepared(store.project_root))

    assert sibling.is_dir()


def test_rollback_failure_reports_the_exact_residue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """回滚也失败是严重状态：必须报出确切的残留路径，而不是一句「安装失败」。"""
    store = _store(tmp_path)
    monkeypatch.setattr(AppStore, "add_app", _failing_write)
    monkeypatch.setattr("aurora.commands.app.transaction._undo_install", _cannot_undo)

    with pytest.raises(InstallError) as error_info:
        install_transaction(store, _prepared(store.project_root))

    message = str(error_info.value)
    assert "自动回滚未能完成" in message
    assert WEATHER_PATH in message, "残留路径必须是项目内相对形式，用户才能照着删"
    assert "注册表未修改" in message


def test_a_successful_commit_leaves_no_staging_behind(tmp_path: Path) -> None:
    """事务将暂存目录发布为正式目录；scratch 由外层暂存上下文管理。"""
    store = _store(tmp_path)
    prepared = _prepared(store.project_root)

    install_transaction(store, prepared)

    entries = apps_root_entries(store.project_root)
    assert _STAGING_NAME not in entries
    assert _OWNER in entries
    assert not prepared.staging.root.exists()


def test_revalidation_rejects_a_package_that_appeared_during_the_wait(tmp_path: Path) -> None:
    """从生成计划到提交之间隔着一次确认，这中间什么都可能出现。"""
    store = _store(tmp_path, registry_entry(WEATHER_PACKAGE, "src/apps/other"))
    prepared = _prepared(store.project_root)

    with pytest.raises(PlanError) as error_info:
        install_transaction(store, prepared)

    assert WEATHER_PACKAGE in str(error_info.value)
    assert not store.project_root.joinpath(*_FINAL_PARTS).exists()
    assert prepared.staging.root.is_dir(), "拒绝之后 staging 必须原样留着，什么都没提交"


def test_revalidation_rejects_a_final_path_that_appeared_during_the_wait(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.project_root.joinpath(*_FINAL_PARTS).mkdir(parents=True)
    prepared = _prepared(store.project_root)

    with pytest.raises(PlanError) as error_info:
        install_transaction(store, prepared)

    assert "安装目录已存在" in str(error_info.value)
    assert prepared.staging.root.is_dir()


def test_revalidation_does_not_append_a_second_entry(tmp_path: Path) -> None:
    store = _store(tmp_path, registry_entry(WEATHER_PACKAGE, "src/apps/other"))

    with pytest.raises(PlanError):
        install_transaction(store, _prepared(store.project_root))

    assert len(_entries(store)) == 1


def test_install_writes_a_working_dir_that_lists_as_ready(tmp_path: Path) -> None:
    """事务写出来的那条记录必须能被 ``aurora app list`` 认成 ready。

    两条链各自看都对、合起来不对是最容易漏的一类回归：这里让注册表读取去验证
    事务写出来的东西。
    """
    store = _store(tmp_path)

    install_transaction(store, _prepared(store.project_root))

    item = store.list_apps().apps[0]
    assert (item.package, item.state, item.enabled) == (WEATHER_PACKAGE, "ready", False)


def test_installing_the_same_package_twice_is_rejected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    install_transaction(store, _prepared(store.project_root))

    with pytest.raises(PlanError):
        install_transaction(store, _prepared(store.project_root))


def test_a_subdirectory_working_dir_still_publishes_the_repository_root(tmp_path: Path) -> None:
    """repository_subdir 不为 ``.`` 时落地的是仓库根，working_dir 指向其中一层。"""
    store = _store(tmp_path)
    prepared = _prepared(
        store.project_root,
        repository_subdir="apps/server",
        working_dir=f"{WEATHER_PATH}/apps/server",
    )

    install_transaction(store, prepared)

    assert store.project_root.joinpath(*_FINAL_PARTS, "pyproject.toml").is_file()
    assert _entries(store)[0]["working_dir"] == f"{WEATHER_PATH}/apps/server"


def test_remove_would_recognise_what_install_produced(tmp_path: Path) -> None:
    """事务装出来的目录必须带得走 remove 的 ownership 校验，否则 remove 永远要 --force。"""
    store = _store(tmp_path)
    install_transaction(store, _prepared(store.project_root))
    root = store.project_root.joinpath(*_FINAL_PARTS)
    write_origin(root, _ORIGIN_URL)

    assert read_origin(root) == _ORIGIN_URL
    removal = plan_removal(store, RawApp(WEATHER_PACKAGE, WEATHER_PATH, None), force=False)
    assert removal.managed_root == root
