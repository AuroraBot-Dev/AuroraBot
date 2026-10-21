"""``aurora app remove`` 的装配、输出文案、失败标签与退出码。

走真实的 ``execute`` 与真实的文件系统；只有注册表与受管目录是本文件自己铺的
夹具。这里验证的是**用户看到什么**：命令装配、三段文案、以及四条失败归属
（不存在 / 归属不符 / 路径不安全 / 锁被占用）各自的退出码。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from aurora_cli.commander import run
from aurora_cli.commands import DEFAULT_REGISTRY
from aurora_cli.commands.app.models import RegistryWriteError
from aurora_cli.commands.app.store import AppStore
from aurora_cli.commands.app.transaction import REMOVE_PREFIX
from aurora_cli.utils.process import EXIT_CONFIG_ERROR, EXIT_FAILURE
from tests.cli.app.clone_support import apps_root_entries, project, registry_entry

if TYPE_CHECKING:
    from pathlib import Path

_EMPTY_REGISTRY = "app = []\n"
_PACKAGE = "github.example.weather-mcp"
_OTHER_PACKAGE = "github.example.somewhere-else"
_MANAGED = "extensions/apps/example/weather-mcp"
_MANAGED_PARTS = ("extensions", "apps", "example", "weather-mcp")
_LOCAL = "src/apps/local-server"
_ORIGIN = "https://github.com/example/weather-mcp.git"
_FOREIGN_ORIGIN = "https://github.com/someone-else/weather-mcp.git"
_CONFIG = "config/apps.toml"


def _project(tmp_path: Path, apps_toml: str) -> Path:
    return project(tmp_path, apps_toml)


def _installed(root: Path, *, origin: str | None = _ORIGIN) -> Path:
    """在项目里造出一个受管安装：目录 + 一份可读的 origin。"""
    managed = root.joinpath(*_MANAGED_PARTS)
    (managed / "src").mkdir(parents=True)
    (managed / "src" / "main.py").write_text("print('hi')\n", encoding="utf-8")
    if origin is not None:
        git = managed / ".git"
        git.mkdir()
        (git / "config").write_text(f'[remote "origin"]\n\turl = {origin}\n', encoding="utf-8")
    return managed


def _quarantines(root: Path) -> list[str]:
    """``extensions/apps/`` 下的回收目录；成功的 remove 一个都不该留下。

    owner 级目录（``example/``）不在其列：它可能还有别的 App，也可能有用户
    自己放的东西，remove 不该替用户决定它该不该存在。
    """
    return [name for name in apps_root_entries(root) if name.startswith(REMOVE_PREFIX)]


def _cli(root: Path, *arguments: str) -> int:
    return run(["--root", str(root), "app", *arguments], registry=DEFAULT_REGISTRY)


def _capture(capsys: pytest.CaptureFixture[str], root: Path, *arguments: str) -> tuple[int, str, str]:
    code = _cli(root, *arguments)
    streams = capsys.readouterr()
    return code, streams.out, streams.err


def _failing_write(*_args: object, **_kwargs: object) -> None:
    raise RegistryWriteError("无法写入 apps.toml：磁盘满了")


def test_remove_help_lists_force(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        run(["app", "remove", "--help"], registry=DEFAULT_REGISTRY)

    assert exit_info.value.code == 0
    usage = " ".join(capsys.readouterr().out.split())
    assert "--force" in usage
    assert "package" in usage


def test_remove_requires_a_package_argument() -> None:
    with pytest.raises(SystemExit):
        run(["app", "remove"], registry=DEFAULT_REGISTRY)


def test_a_managed_remove_reports_the_deleted_directory(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _project(tmp_path, registry_entry(_PACKAGE, _MANAGED))
    _installed(root)

    code, out, _ = _capture(capsys, root, "remove", _PACKAGE)

    assert code == 0
    assert f"已移除 {_PACKAGE}。" in out
    assert f"已删除安装目录 {_MANAGED}。" in out
    assert "未删除任何文件" not in out


def test_a_managed_remove_actually_deletes_the_directory(tmp_path: Path) -> None:
    root = _project(tmp_path, registry_entry(_PACKAGE, _MANAGED))
    managed = _installed(root)

    _cli(root, "remove", _PACKAGE)

    assert not managed.exists()


def test_a_managed_remove_leaves_no_quarantine_behind(tmp_path: Path) -> None:
    """回收目录是中间态，成功路径上不该让用户看到任何 ``.aurora-remove-``。"""
    root = _project(tmp_path, registry_entry(_PACKAGE, _MANAGED))
    _installed(root)

    _cli(root, "remove", _PACKAGE)

    assert _quarantines(root) == []


def test_the_last_removal_keeps_the_registry_readable(tmp_path: Path) -> None:
    """删掉最后一条之后 ``app`` 键必须还在，否则下一个命令读不了这份文件。"""
    root = _project(tmp_path, registry_entry(_PACKAGE, _MANAGED))
    _installed(root)

    _cli(root, "remove", _PACKAGE)

    assert (root / _CONFIG).read_text(encoding="utf-8") == _EMPTY_REGISTRY


def test_a_non_managed_remove_only_unregisters(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """本地 Server 不在受管路径下：删条目，但绝不碰它的文件。"""
    root = _project(tmp_path, registry_entry(_PACKAGE, _LOCAL))
    local = root.joinpath(*_LOCAL.split("/"))
    local.mkdir(parents=True)
    (local / "server.py").write_text("print('hi')\n", encoding="utf-8")

    code, out, _ = _capture(capsys, root, "remove", _PACKAGE)

    assert code == 0
    assert f"已移除 {_PACKAGE}。" in out
    assert "只解除 Aurora 注册；未删除 Server 文件、npm 缓存或用户目录。" in out
    assert "已删除安装目录" not in out
    assert (local / "server.py").is_file()


def test_a_missing_package_is_a_config_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _project(tmp_path, registry_entry(_OTHER_PACKAGE, _LOCAL))

    code, _, err = _capture(capsys, root, "remove", _PACKAGE)

    assert code == EXIT_CONFIG_ERROR
    assert "App 配置错误" in err
    assert "注册表中不存在 package" in err


def test_a_missing_registry_points_at_aurora_setup(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = _capture(capsys, tmp_path, "remove", _PACKAGE)

    assert code == EXIT_CONFIG_ERROR
    assert "aurora config apps --init" in err


def test_a_duplicate_package_in_the_registry_is_a_config_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """同一 package 出现两次时，无法确定该操作哪一个条目。"""
    root = _project(tmp_path, registry_entry(_PACKAGE, _MANAGED) * 2)

    code, _, err = _capture(capsys, root, "remove", _PACKAGE)

    assert code == EXIT_CONFIG_ERROR
    assert "package 重复" in err


def test_an_invalid_package_id_is_a_config_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _project(tmp_path, registry_entry(_PACKAGE, _MANAGED))

    code, _, err = _capture(capsys, root, "remove", "Not.A.Package")

    assert code == EXIT_CONFIG_ERROR
    assert "package ID" in err


@pytest.mark.parametrize("origin", [_FOREIGN_ORIGIN, None], ids=["mismatched", "unreadable"])
def test_a_directory_that_cannot_be_claimed_is_an_operation_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], origin: str | None
) -> None:
    """目录形状对不等于 Aurora 装的：期望值来自目录名，凭据来自 ``.git/config``。"""
    root = _project(tmp_path, registry_entry(_PACKAGE, _MANAGED))
    managed = _installed(root, origin=origin)

    code, out, err = _capture(capsys, root, "remove", _PACKAGE)

    assert code == EXIT_FAILURE
    assert "App 移除失败" in err
    assert "--force" in err, "拒绝之后必须告诉用户下一步能做什么"
    assert "已移除" not in out
    assert managed.is_dir(), "拒绝时一个字节都不能删"
    assert _PACKAGE in (root / _CONFIG).read_text(encoding="utf-8")


def test_force_removes_a_directory_with_a_mismatched_origin(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _project(tmp_path, registry_entry(_PACKAGE, _MANAGED))
    managed = _installed(root, origin=_FOREIGN_ORIGIN)

    code, out, _ = _capture(capsys, root, "remove", _PACKAGE, "--force")

    assert code == 0
    assert "已删除安装目录" in out
    assert not managed.exists()


def test_force_never_deletes_outside_the_project(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """路径边界不由用户参数开启：越界的 working_dir 归为「非受管」，不报错也不删。

    项目根放在一层子目录里，``../outside`` 才是这个用例独占的目录 —— 直接往
    ``tmp_path.parent`` 里放东西会污染 pytest 的共享临时目录。
    """
    root = _project(tmp_path / "project", registry_entry(_PACKAGE, "../outside"))
    outside = tmp_path / "outside"
    outside.mkdir(parents=True)
    (outside / "important.txt").write_text("keep me\n", encoding="utf-8")

    code, out, _ = _capture(capsys, root, "remove", _PACKAGE, "--force")

    assert code == 0
    assert "未删除 Server 文件、npm 缓存或用户目录" in out
    assert (outside / "important.txt").is_file()


def test_a_symlinked_managed_root_is_a_path_error_even_with_force(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """形状对、origin 也对，但中间一层是符号链接：删它等于删项目外的东西。"""
    root = _project(tmp_path, registry_entry(_PACKAGE, _MANAGED))
    managed = root.joinpath(*_MANAGED_PARTS)
    managed.parent.mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "important.txt").write_text("keep me\n", encoding="utf-8")
    try:
        managed.symlink_to(elsewhere, target_is_directory=True)
    except OSError as error:  # pragma: no cover - 平台不具备创建符号链接的权限
        pytest.skip(f"当前环境无法创建符号链接：{error}")

    code, _, err = _capture(capsys, root, "remove", _PACKAGE, "--force")

    assert code == EXIT_CONFIG_ERROR
    assert "符号链接或联接" in err
    assert (elsewhere / "important.txt").is_file()


def test_a_registry_write_failure_puts_the_directory_back(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """先 quarantine 后写注册表：写失败时目录要回到原位，用户看到与执行前一样。"""
    root = _project(tmp_path, registry_entry(_PACKAGE, _MANAGED))
    managed = _installed(root)
    monkeypatch.setattr(AppStore, "remove_app", _failing_write)

    code, _, err = _capture(capsys, root, "remove", _PACKAGE)

    assert code == EXIT_FAILURE
    assert "App 操作失败" in err
    assert managed.is_dir(), "回滚之后正式目录必须原地不动"
    assert _quarantines(root) == [], "回收目录不该留下来"
    assert _PACKAGE in (root / _CONFIG).read_text(encoding="utf-8")


def test_a_managed_entry_without_its_directory_fails_loudly(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """目录已经被用户自己删掉时固定住当前行为：报错，而不是悄悄删掉条目。

    报出来比默默成功好，因为用户仍可以在 ``config/apps.toml`` 里手工改掉这条
    指向不存在目录的条目。失败信息里带着那个路径，用户看得出发生了什么。
    """
    root = _project(tmp_path, registry_entry(_PACKAGE, _MANAGED))

    code, _, err = _capture(capsys, root, "remove", _PACKAGE)

    assert code == EXIT_FAILURE
    assert "App 移除失败" in err
    assert _MANAGED in err
    assert _PACKAGE in (root / _CONFIG).read_text(encoding="utf-8")
