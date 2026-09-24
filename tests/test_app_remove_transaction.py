"""``remove_transaction`` 的受管推导、归属校验、回收与回滚。

remove 的两件事必须分开验证：删哪些文件（受管推导）与凭什么删（origin 归属）。
``--force`` 只放宽后者 —— 让一个用户参数去打开路径边界，等于把「--force 可以
删到项目外」写进契约。
"""

from __future__ import annotations

import stat
from typing import TYPE_CHECKING

import pytest
from app_clone_support import project

from aurora.commands.app.clone import remove_tree
from aurora.commands.app.models import AppNotFoundError, PathError, RegistryWriteError, RemoveError
from aurora.commands.app.store import AppStore
from aurora.commands.app.transaction import (
    REMOVE_PREFIX,
    Removal,
    classify_managed_app,
    plan_removal,
    remove_transaction,
)

if TYPE_CHECKING:
    from pathlib import Path

    from aurora.commands.app.models import RawApp

_PACKAGE = "github.example.weather-mcp"
_OWNER = "example"
_REPO = "weather-mcp"
_MANAGED_WORKING_DIR = f"extensions/apps/{_OWNER}/{_REPO}"
_MANAGED_PARTS = ("extensions", "apps", _OWNER, _REPO)
_ORIGIN_URL = "https://github.com/example/weather-mcp.git"
_MISMATCHED_ORIGIN = "https://github.com/someone-else/weather-mcp.git"
_REAL_REMOVE_TREE = remove_tree


def _registry(working_dir: str) -> str:
    """一份单条目注册表；working_dir 按 TOML 基本字符串转义。

    直接往模板里塞原始文本是不行的：``extensions\\..\\evil`` 这类用例里的反斜杠
    在 TOML 里是非法转义，会把「路径不安全」测成「文件解析失败」。
    """
    escaped = working_dir.replace("\\", "\\\\")
    return (
        f'[[app]]\npackage = "{_PACKAGE}"\nenabled = false\ntransport = "stdio"\n'
        f'working_dir = "{escaped}"\ncommand = ["uv", "run", "weather-mcp"]\nenv = []\n'
        'timeout_seconds = 60\nevent_mode = "disabled"\n'
    )


def _store(tmp_path: Path, working_dir: str = _MANAGED_WORKING_DIR) -> AppStore:
    return AppStore(project(tmp_path, _registry(working_dir)))


def _raw(store: AppStore) -> RawApp:
    entry = store.raw_app(_PACKAGE)
    assert entry is not None
    return entry


def _installed(store: AppStore, origin: str | None = _ORIGIN_URL) -> Path:
    """造出一个受管安装：目录 + 与目录名匹配的 origin。"""
    root = store.project_root.joinpath(*_MANAGED_PARTS)
    (root / "src").mkdir(parents=True)
    (root / "src" / "main.py").write_text("print('hi')\n", encoding="utf-8")
    if origin is not None:
        git = root / ".git"
        git.mkdir()
        (git / "config").write_text(f'[remote "origin"]\n\turl = {origin}\n', encoding="utf-8")
    return root


def _failing_write(*_args: object, **_kwargs: object) -> None:
    raise RegistryWriteError("无法写入 apps.toml：磁盘满了")


def _refuse_the_quarantine(path: Path) -> str | None:
    """只拒绝删回收目录。

    ``remove_tree`` 不只服务回收目录：锁的释放走的是同一个函数，把它一起换成
    「总是失败」的话，就无法测到回收失败的残留报告。
    """
    if path.name.startswith(REMOVE_PREFIX):
        return "目录被占用"
    return _REAL_REMOVE_TREE(path)


# --- 受管推导 -----------------------------------------------------------------


@pytest.mark.parametrize(
    "working_dir",
    [
        "src/apps/qq-server",
        "extensions/apps/legacy-app",
        "extensions/apps",
        "Extensions/apps/example/weather-mcp",
        ".",
    ],
)
def test_shapes_outside_the_managed_layout_are_not_managed(tmp_path: Path, working_dir: str) -> None:
    store = _store(tmp_path, working_dir)

    assert classify_managed_app(store.project_root, _raw(store)) is None


def test_the_managed_root_is_the_two_level_directory(tmp_path: Path) -> None:
    store = _store(tmp_path)

    assert classify_managed_app(store.project_root, _raw(store)) == store.project_root.joinpath(*_MANAGED_PARTS)


def test_owner_and_repo_casing_is_not_part_of_the_shape_check(tmp_path: Path) -> None:
    """目录名大小写不参与形状判断，它归 origin 校验管。

    GitHub 对大小写不敏感，同一个仓库可能被写成任意大小写组合；把大小写写进形状
    判断会让这类目录一律变成「非受管」，而它们其实是 Aurora 自己装的。
    """
    store = _store(tmp_path, f"extensions/apps/{_OWNER.title()}/{_REPO}")

    assert classify_managed_app(store.project_root, _raw(store)) == store.project_root.joinpath(
        "extensions", "apps", _OWNER.title(), _REPO
    )


@pytest.mark.parametrize("working_dir", ["extensions/apps/../evil", "../evil", "C:/Windows", "extensions\\..\\evil"])
def test_escaping_working_dirs_are_not_managed(tmp_path: Path, working_dir: str) -> None:
    """形状判断不能建在一条可能越界的路径上：返回 None 而不是推导出一个项目外的路径。"""
    store = _store(tmp_path, working_dir)

    assert classify_managed_app(store.project_root, _raw(store)) is None


def test_a_subdirectory_working_dir_still_points_at_the_repository_root(tmp_path: Path) -> None:
    """working_dir 多一层时必须删仓库根，不是最后那个子目录。"""
    store = _store(tmp_path, f"{_MANAGED_WORKING_DIR}/apps/server")

    assert classify_managed_app(store.project_root, _raw(store)) == store.project_root.joinpath(*_MANAGED_PARTS)


def test_an_entry_without_working_dir_is_not_managed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    (store.project_root / "config" / "apps.toml").write_text(
        f'[[app]]\npackage = "{_PACKAGE}"\nenabled = false\ntransport = "stdio"\n'
        'command = ["uv", "run", "x"]\nenv = []\ntimeout_seconds = 60\nevent_mode = "disabled"\n',
        encoding="utf-8",
    )

    entry = _raw(store)
    assert entry.working_dir is None
    assert classify_managed_app(store.project_root, entry) is None


# --- 非受管移除 ---------------------------------------------------------------


def test_a_non_managed_app_only_loses_its_entry(tmp_path: Path) -> None:
    store = _store(tmp_path, "src/apps/qq-server")
    local = store.project_root / "src" / "apps" / "qq-server"
    local.mkdir(parents=True)
    (local / "server.py").write_text("", encoding="utf-8")

    removal = Removal(_PACKAGE, None)
    remove_transaction(store, removal)

    assert removal.managed_root is None
    assert store.raw_app(_PACKAGE) is None
    assert (local / "server.py").is_file(), "非受管 App 不触碰任何文件"


def test_a_non_managed_app_leaves_the_install_root_alone(tmp_path: Path) -> None:
    store = _store(tmp_path, "src/apps/qq-server")

    remove_transaction(store, Removal(_PACKAGE, None))

    assert store.raw_app(_PACKAGE) is None


# --- 归属校验 -----------------------------------------------------------------


def test_a_matching_origin_is_accepted(tmp_path: Path) -> None:
    store = _store(tmp_path)
    root = _installed(store)

    assert plan_removal(store, _raw(store), force=False).managed_root == root


def test_a_mismatched_origin_is_rejected_with_a_force_hint(tmp_path: Path) -> None:
    store = _store(tmp_path)
    root = _installed(store, _MISMATCHED_ORIGIN)

    with pytest.raises(RemoveError) as error_info:
        plan_removal(store, _raw(store), force=False)

    message = str(error_info.value)
    assert _MISMATCHED_ORIGIN in message
    assert "--force" in message
    assert root.is_dir(), "拒绝时不能已经动过目录"


def test_a_missing_git_config_is_rejected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _installed(store, origin=None)

    with pytest.raises(RemoveError) as error_info:
        plan_removal(store, _raw(store), force=False)

    assert "读不到 .git/config 里的 origin" in str(error_info.value)


def test_force_skips_the_origin_check(tmp_path: Path) -> None:
    store = _store(tmp_path)
    root = _installed(store, _MISMATCHED_ORIGIN)

    assert plan_removal(store, _raw(store), force=True).managed_root == root


def test_force_still_refuses_a_working_dir_outside_the_project(tmp_path: Path) -> None:
    """``--force`` 只放宽 origin 一条；越界路径归为「非受管」，删不动任何东西。

    项目根本身放在一层子目录里：``tmp_path.parent`` 是 pytest 的共享临时目录，
    在那里造「项目外」的目录会被同一个目录下的其他用例撞上。
    """
    store = _store(tmp_path / "project", "../outside")
    outside = store.project_root.parent / "outside"
    outside.mkdir()

    removal = plan_removal(store, _raw(store), force=True)

    assert removal.managed_root is None
    assert outside.is_dir()


def test_a_symlinked_managed_root_is_a_path_error_even_with_force(tmp_path: Path) -> None:
    store = _store(tmp_path)
    root = store.project_root.joinpath(*_MANAGED_PARTS)
    root.parent.mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    try:
        root.symlink_to(elsewhere, target_is_directory=True)
    except OSError as error:  # pragma: no cover - 平台不具备创建符号链接的权限
        pytest.skip(f"当前环境无法创建符号链接：{error}")

    with pytest.raises(PathError):
        plan_removal(store, _raw(store), force=True)


# --- 提交与回收 ---------------------------------------------------------------


def test_a_managed_remove_deletes_the_directory(tmp_path: Path) -> None:
    store = _store(tmp_path)
    root = _installed(store)

    remove_transaction(store, Removal(_PACKAGE, root))

    assert not root.exists()
    assert store.raw_app(_PACKAGE) is None


def test_no_quarantine_directory_survives_a_successful_remove(tmp_path: Path) -> None:
    store = _store(tmp_path)
    root = _installed(store)

    remove_transaction(store, Removal(_PACKAGE, root))

    leftovers = [path.name for path in root.parent.iterdir() if path.name.startswith(REMOVE_PREFIX)]
    assert leftovers == []


def test_a_read_only_file_does_not_block_the_cleanup(tmp_path: Path) -> None:
    """真正会挡路的不是「目录被占用」，是 git 留下的只读包文件。

    Windows 上 .git/objects/pack/*.pack 带只读属性，直接 rmtree 会 WinError 5。
    修之前这条路径每次都会以「注册表已更新但残留目录未能删除」结束（退出码 1），
    而那被设计当成罕见情形。
    """
    store = _store(tmp_path)
    root = _installed(store)
    pack = root / ".git" / "objects" / "pack"
    pack.mkdir(parents=True)
    blob = pack / "pack-abcdef.pack"
    blob.write_bytes(b"x")
    blob.chmod(stat.S_IREAD)

    remove_transaction(store, Removal(_PACKAGE, root))

    assert not root.exists()
    assert store.raw_app(_PACKAGE) is None


def test_registry_failure_renames_the_quarantine_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = _store(tmp_path)
    root = _installed(store)
    monkeypatch.setattr(AppStore, "remove_app", _failing_write)

    with pytest.raises(RegistryWriteError):
        remove_transaction(store, Removal(_PACKAGE, root))

    # 用户在文件系统上看到的东西必须与执行 remove 之前完全一样。
    assert (root / "src" / "main.py").is_file()
    assert store.raw_app(_PACKAGE) is not None


def test_cleanup_failure_reports_the_residue_but_keeps_the_entry_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """注册表删成功、目录删不掉：remove 逻辑上已经完成，不为了清理失败把条目写回来。"""
    store = _store(tmp_path)
    root = _installed(store)
    monkeypatch.setattr("aurora.commands.app.transaction.remove_tree", _refuse_the_quarantine)

    with pytest.raises(RemoveError) as error_info:
        remove_transaction(store, Removal(_PACKAGE, root))

    message = str(error_info.value)
    assert "注册表已更新" in message
    assert REMOVE_PREFIX in message
    assert _MANAGED_WORKING_DIR in message, "残留的 UUID 目录必须说清它原来是哪一个"
    assert store.raw_app(_PACKAGE) is None, "条目必须保持已删除，不能写回来"


def test_rollback_failure_reports_the_residue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = _store(tmp_path)
    root = _installed(store)
    monkeypatch.setattr(AppStore, "remove_app", _failing_write)
    monkeypatch.setattr("aurora.commands.app.transaction._undo_remove", _cannot_undo)

    with pytest.raises(RemoveError) as error_info:
        remove_transaction(store, Removal(_PACKAGE, root))

    message = str(error_info.value)
    assert "自动回滚未能完成" in message
    assert REMOVE_PREFIX in message
    assert _PACKAGE in message
    assert "请手动把残留目录改回原路径" in message


# --- 提交前重验证 -------------------------------------------------------------


def test_a_package_that_vanished_before_commit_is_reported(tmp_path: Path) -> None:
    store = _store(tmp_path)
    root = _installed(store)
    (store.project_root / "config" / "apps.toml").write_text("app = []\n", encoding="utf-8")

    with pytest.raises(AppNotFoundError):
        remove_transaction(store, Removal(_PACKAGE, root))

    assert root.is_dir(), "什么都没提交，目录必须原样"


def test_a_managed_root_that_changed_before_commit_is_reported(tmp_path: Path) -> None:
    """计划到提交之间，用户可能在文件管理器里改过目录。"""
    store = _store(tmp_path, "src/apps/moved")
    root = _installed(store)

    with pytest.raises(RemoveError) as error_info:
        remove_transaction(store, Removal(_PACKAGE, root))

    assert "判定之后发生了变化" in str(error_info.value)
    assert root.is_dir()


def test_a_non_managed_removal_ignores_a_working_dir_that_changed(tmp_path: Path) -> None:
    """非受管不删文件，working_dir 怎么变都不影响「只解除注册」这个结果。"""
    store = _store(tmp_path, "src/apps/qq-server")

    remove_transaction(store, Removal(_PACKAGE, None))

    assert store.raw_app(_PACKAGE) is None


def _cannot_undo(_removal: Removal, quarantine: Path | None) -> Path:
    """模拟「回收目录搬不回去」：把残留报成那个 UUID 目录本身。"""
    assert quarantine is not None
    return quarantine
