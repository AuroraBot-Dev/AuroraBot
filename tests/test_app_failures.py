"""App 命令的子进程、权限和事务失败路径。"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from aurora.commander import run
from aurora.commands import DEFAULT_REGISTRY
from aurora.commands import app as command
from aurora.commands.app import service
from aurora.commands.app.github import GitHubClient, JsonResponse
from aurora.commands.app.models import AppManagerError
from aurora.configuration.apps import AppConfig
from aurora.utils.process import EXIT_CONFIG_ERROR

_COMMIT = "a" * 40


@pytest.fixture
def manager(tmp_path: Path) -> service.AppManager:
    (tmp_path / "config").mkdir()
    (tmp_path / "config/apps.toml").write_text("app = []\n", encoding="utf-8")
    payload = {
        "full_name": "example/app",
        "description": "应用",
        "stargazers_count": 0,
        "default_branch": "main",
        "html_url": "https://github.com/example/app",
        "clone_url": "https://github.com/example/app.git",
        "topics": [],
        "archived": False,
        "disabled": False,
        "updated_at": "2026-09-01T00:00:00Z",
    }
    return service.AppManager(tmp_path, github=GitHubClient(transport=lambda *_args: JsonResponse(payload, {})))


def _git_success(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
    if "clone" in args:
        checkout = Path(args[-1])
        checkout.mkdir()
        (checkout / "aurora-app.toml").write_text(
            'manifest_version = 1\n[package]\nid = "org.example.app"\nname = "App"\n'
            'version = "1"\ndescription = "测试"\n[app]\ncommand = ["server"]\n'
            'env = []\ntimeout_seconds = 60\nevent_mode = "disabled"\n',
            encoding="utf-8",
        )
    return subprocess.CompletedProcess(args, 0, stdout=_COMMIT + "\n", stderr="")


@pytest.mark.parametrize(
    "failure",
    (
        FileNotFoundError("git"),
        PermissionError("blocked"),
        subprocess.TimeoutExpired("git", 300),
    ),
)
def test_git_launch_failures_map_to_cli_error_and_release_lock(
    manager: service.AppManager,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure: Exception,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise failure

    monkeypatch.setattr(service.subprocess, "run", fail)
    monkeypatch.setattr(command, "AppManager", lambda *_args, **_kwargs: manager)
    assert run(["app", "install", "example/app"], registry=DEFAULT_REGISTRY) == 1
    assert "App 操作失败" in capsys.readouterr().err
    assert manager.store.apps_config() == ()
    assert tuple(manager.store.install_root.iterdir()) == ()


def test_git_nonzero_exit_releases_lock(manager: service.AppManager, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service.subprocess, "run", lambda args, **kwargs: subprocess.CompletedProcess(args, 128))
    with pytest.raises(AppManagerError, match="退出码 128"):
        manager.install("example/app")
    assert manager.store.apps_config() == ()
    assert tuple(manager.store.install_root.iterdir()) == ()


def test_real_clone_command_construction_and_empty_config_lifecycle(
    manager: service.AppManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def git(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return _git_success(args, **kwargs)

    monkeypatch.setattr(service.subprocess, "run", git)
    installed = manager.install("example/app", ref="v1", enabled=False)
    assert "--single-branch" in calls[0]
    assert calls[0][calls[0].index("--branch") + 1] == "v1"
    assert calls[1][-2:] == ["rev-parse", "HEAD"]
    assert installed.marker is not None and installed.marker.requested_ref == "v1"
    manager.remove(installed.package)
    assert manager.list().apps == ()


def test_staging_permission_failure_is_domain_error(
    manager: service.AppManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(**_kwargs: object) -> str:
        raise PermissionError("staging blocked")

    monkeypatch.setattr(service.tempfile, "mkdtemp", fail)
    with pytest.raises(AppManagerError, match="无法创建安装临时目录"):
        manager.install("example/app")
    assert not manager.store.lock_exists()
    assert manager.store.apps_config() == ()


def test_remove_cleanup_failure_keeps_valid_config_and_reports_residual(
    manager: service.AppManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(service.subprocess, "run", _git_success)
    installed = manager.install("example/app")

    def fail(_path: Path, **_kwargs: object) -> None:
        raise PermissionError("cleanup blocked")

    monkeypatch.setattr(service.shutil, "rmtree", fail)
    with pytest.raises(AppManagerError, match="配置已移除，但隔离目录清理失败"):
        manager.remove(installed.package)
    assert manager.store.apps_config() == ()
    assert not manager.store.lock_exists()
    assert len(tuple(manager.store.install_root.glob(".aurora-remove-*"))) == 1


def test_readonly_retry_does_not_hide_real_permission_error(tmp_path: Path) -> None:
    path = tmp_path / "writable.txt"
    path.write_text("data")
    error = PermissionError("ACL blocked")
    with pytest.raises(PermissionError, match="ACL blocked"):
        service._remove_readonly(lambda _path: pytest.fail("不得重试可写文件"), str(path), error)
    assert path.read_text() == "data"


@pytest.mark.parametrize("contents", ("bad = [", "", "app = 1"))
def test_broken_configuration_maps_to_exit_two(
    manager: service.AppManager,
    monkeypatch: pytest.MonkeyPatch,
    contents: str,
) -> None:
    manager.store.apps_path.write_text(contents)
    monkeypatch.setattr(command, "AppManager", lambda *_args, **_kwargs: manager)
    assert run(["app", "list"], registry=DEFAULT_REGISTRY) == EXIT_CONFIG_ERROR


@pytest.mark.parametrize(
    ("previous_enabled", "requested_enabled"), ((False, False), (False, True), (True, False), (True, True))
)
def test_reuse_preserves_enabled_state_unless_disabled_is_requested(
    manager: service.AppManager,
    monkeypatch: pytest.MonkeyPatch,
    previous_enabled: bool,
    requested_enabled: bool,
) -> None:
    previous = AppConfig(
        "org.example.app",
        previous_enabled,
        "stdio",
        "world_events",
        45,
        working_dir="extensions/apps/preset",
        command=("custom-server",),
        env=("TOKEN",),
    )
    manager.store.add_app(previous)
    monkeypatch.setattr(service.subprocess, "run", _git_success)
    installed = manager.install("example/app", reuse_config=True, enabled=requested_enabled)
    current = manager.store.apps_config()[0]
    assert installed.enabled == current.enabled == (previous_enabled and requested_enabled)
    assert (current.command, current.env, current.event_mode, current.timeout_seconds) == (
        previous.command,
        previous.env,
        previous.event_mode,
        previous.timeout_seconds,
    )


def test_cli_reuse_flag_reaches_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    received: dict[str, object] = {}

    class Manager:
        def install(self, source: str, **options: object) -> None:
            received.update(options)
            raise AppManagerError("stop before download")

    monkeypatch.setattr(command, "AppManager", lambda *_args, **_kwargs: Manager())
    assert run(["app", "install", "example/app", "--reuse-config", "--disabled"], registry=DEFAULT_REGISTRY) == 1
    assert received == {"ref": None, "enabled": False, "reuse_config": True}
