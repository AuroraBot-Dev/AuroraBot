"""受管 App 安装事务、列表诊断与安全移除测试。"""

from __future__ import annotations

import os
import subprocess
import tomllib
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from aurora.apps.github import GitHubClient, JsonResponse
from aurora.apps.models import AppManagerConfigError, AppManagerError
from aurora.apps.service import AppManager
from aurora.apps.store import LOCK_NAME, MARKER_NAME, AppStore

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

_COMMIT = "0123456789abcdef0123456789abcdef01234567"
_NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


def _repository_payload(*, topic: bool = True, archived: bool = False, disabled: bool = False) -> dict[str, object]:
    return {
        "full_name": "example/weather-mcp",
        "description": "天气 App",
        "stargazers_count": 42,
        "default_branch": "main",
        "html_url": "https://github.com/example/weather-mcp",
        "clone_url": "https://github.com/example/weather-mcp.git",
        "topics": ["aurorabot-app"] if topic else [],
        "archived": archived,
        "disabled": disabled,
        "updated_at": "2026-09-01T00:00:00Z",
    }


def _github(**repository_options: bool) -> GitHubClient:
    return GitHubClient(transport=lambda _url, _headers: JsonResponse(_repository_payload(**repository_options), {}))


def _project(tmp_path: Path) -> Path:
    config = tmp_path / "config"
    config.mkdir(parents=True)
    (config / "apps.toml").write_text(
        "# 保留这条注释\n\n"
        "[[app]]\n"
        'package = "org.example.existing"\n'
        "enabled = false\n"
        'transport = "streamable_http"\n'
        'url = "https://example.com/mcp"\n'
        "timeout_seconds = 30\n"
        'event_mode = "disabled"\n',
        encoding="utf-8",
    )
    return tmp_path


def _clone(_url: str, destination: Path, ref: str | None) -> str:
    assert ref in {None, "v1.2.0"}
    destination.mkdir(parents=True)
    (destination / "payload.txt").write_text("payload", encoding="utf-8")
    (destination / "aurora-app.toml").write_text(
        "manifest_version = 1\n\n"
        "[package]\n"
        'id = "org.example.weather"\n'
        'name = "Weather MCP"\n'
        'version = "1.2.0"\n'
        'description = "天气工具"\n\n'
        "[app]\n"
        'command = ["uv", "run", "--frozen", "weather-mcp"]\n'
        'env = ["WEATHER_API_KEY"]\n'
        "timeout_seconds = 30\n"
        'event_mode = "disabled"\n',
        encoding="utf-8",
    )
    return _COMMIT


def _manager(root: Path, **repository_options: bool) -> AppManager:
    return AppManager(root, github=_github(**repository_options), clone=_clone, clock=lambda: _NOW)


def _create_directory_link(target: Path, link: Path) -> bool:
    """创建指向目录的 junction(Windows)/symlink(其他)；无特权时返回 False。"""
    if os.name == "nt":
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            check=False,
        )
        return result.returncode == 0
    try:
        link.symlink_to(target, target_is_directory=True)
        return True
    except OSError:
        return False


def _clone_second(url: str, destination: Path, ref: str | None) -> str:
    """把 calendar 仓库克隆改写为第二份受管安装的清单。"""
    _clone(url, destination, ref)
    if "calendar" not in url:
        return _COMMIT
    manifest = destination / "aurora-app.toml"
    content = manifest.read_text(encoding="utf-8")
    manifest.write_text(
        content.replace('id = "org.example.weather"', 'id = "org.example.calendar"')
        .replace('name = "Weather MCP"', 'name = "Calendar MCP"')
        .replace('version = "1.2.0"', 'version = "0.8.1"'),
        encoding="utf-8",
    )
    return _COMMIT


def _second_transport(url: str, headers: Mapping[str, str]) -> JsonResponse:
    payload = _repository_payload()
    if "calendar" in url:
        payload.update(
            {
                "full_name": "another/calendar-mcp",
                "html_url": "https://github.com/another/calendar-mcp",
                "clone_url": "https://github.com/another/calendar-mcp.git",
            }
        )
    return JsonResponse(payload, {})


def test_install_writes_marker_and_preserves_personal_config(tmp_path: Path) -> None:
    root = _project(tmp_path)
    manager = _manager(root)

    installed = manager.install("https://github.com/example/weather-mcp.git", ref="v1.2.0", enabled=False)

    assert installed.state == "ready"
    assert installed.enabled is False
    assert installed.marker is not None
    assert installed.marker.resolved_commit == _COMMIT
    assert installed.marker.installed_at == _NOW
    assert (installed.path / "payload.txt").read_text(encoding="utf-8") == "payload"
    assert (installed.path / MARKER_NAME).is_file()
    text = (root / "config" / "apps.toml").read_text(encoding="utf-8")
    assert text.startswith("# 保留这条注释")
    with (root / "config" / "apps.toml").open("rb") as stream:
        apps = tomllib.load(stream)["app"]
    assert [item["package"] for item in apps] == ["org.example.existing", "org.example.weather"]
    assert apps[1]["working_dir"] == "extensions/apps/example/weather-mcp"
    assert apps[1]["enabled"] is False
    assert not (root / "extensions" / "apps" / LOCK_NAME).exists()


def test_install_accepts_valid_empty_app_array_and_preserves_comment(tmp_path: Path) -> None:
    root = tmp_path
    config = root / "config"
    config.mkdir()
    path = config / "apps.toml"
    path.write_text("# 空配置\napp = [] # 暂无 App\n", encoding="utf-8")

    installed = _manager(root).install("example/weather-mcp")

    assert installed.state == "ready"
    text = path.read_text(encoding="utf-8")
    assert "# 空配置" in text
    assert "# 暂无 App" in text
    with path.open("rb") as stream:
        assert tomllib.load(stream)["app"][0]["package"] == "org.example.weather"


def test_list_reports_ready_config_missing_and_invalid_marker(tmp_path: Path) -> None:
    root = _project(tmp_path)
    manager = _manager(root)
    installed = manager.install("example/weather-mcp")

    ready = manager.list()
    assert [(item.package, item.state, item.enabled) for item in ready.apps] == [("org.example.weather", "ready", True)]

    path = root / "config" / "apps.toml"
    content = path.read_text(encoding="utf-8")
    start = content.index('[[app]]\npackage = "org.example.weather"')
    path.write_text(content[:start].rstrip() + "\n", encoding="utf-8")
    missing = manager.list()
    assert missing.apps[0].state == "config_missing"

    (installed.path / MARKER_NAME).write_text("marker_version = 99\n", encoding="utf-8")
    invalid = manager.list()
    assert invalid.apps[0].state == "invalid_marker"
    assert invalid.apps[0].detail is not None


def test_list_ignores_manual_directory_and_reports_lock(tmp_path: Path) -> None:
    root = _project(tmp_path)
    manual = root / "extensions" / "apps" / "owner" / "manual"
    manual.mkdir(parents=True)
    (manual / "keep.txt").write_text("keep", encoding="utf-8")
    lock = root / "extensions" / "apps" / LOCK_NAME
    lock.mkdir()

    result = _manager(root).list()

    assert result.apps == ()
    assert result.changing is True


@pytest.mark.parametrize(
    ("options", "message"),
    (
        ({"topic": False}, "没有 aurorabot-app topic"),
        ({"archived": True}, "已归档"),
        ({"disabled": True}, "已被 GitHub 禁用"),
    ),
)
def test_install_rejects_unavailable_repository(
    tmp_path: Path,
    options: dict[str, bool],
    message: str,
) -> None:
    with pytest.raises(AppManagerError, match=message):
        _manager(_project(tmp_path), **options).install("example/weather-mcp")


def test_install_rejects_missing_config_and_invalid_ref(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    with pytest.raises(AppManagerConfigError, match="aurora setup"):
        manager.install("example/weather-mcp")

    root = _project(tmp_path / "configured")
    with pytest.raises(AppManagerError, match="ref"):
        _manager(root).install("example/weather-mcp", ref="--main")


def test_duplicate_install_is_rejected_before_second_clone(tmp_path: Path) -> None:
    root = _project(tmp_path)
    calls = 0

    def clone(url: str, destination: Path, ref: str | None) -> str:
        nonlocal calls
        calls += 1
        return _clone(url, destination, ref)

    manager = AppManager(root, github=_github(), clone=clone, clock=lambda: _NOW)
    manager.install("example/weather-mcp")

    with pytest.raises(AppManagerError, match="安装目录已存在"):
        manager.install("example/weather-mcp")
    assert calls == 1


def test_install_rejects_package_owned_by_different_managed_repository(tmp_path: Path) -> None:
    root = _project(tmp_path)
    first = _manager(root)
    first.install("example/weather-mcp")
    path = root / "config" / "apps.toml"
    content = path.read_text(encoding="utf-8")
    start = content.index('[[app]]\npackage = "org.example.weather"')
    path.write_text(content[:start].rstrip() + "\n", encoding="utf-8")
    payload = _repository_payload()
    payload.update(
        {
            "full_name": "another/weather-mcp",
            "html_url": "https://github.com/another/weather-mcp",
            "clone_url": "https://github.com/another/weather-mcp.git",
        }
    )
    github = GitHubClient(transport=lambda _url, _headers: JsonResponse(payload, {}))
    second = AppManager(root, github=github, clone=_clone, clock=lambda: _NOW)

    with pytest.raises(AppManagerError, match="受管安装已存在 package"):
        second.install("another/weather-mcp")
    assert not (root / "extensions" / "apps" / "another" / "weather-mcp").exists()


def test_install_rejects_invalid_commit_from_clone_boundary(tmp_path: Path) -> None:
    root = _project(tmp_path)

    def clone(url: str, destination: Path, ref: str | None) -> str:
        _clone(url, destination, ref)
        return "not-a-commit"

    manager = AppManager(root, github=_github(), clone=clone, clock=lambda: _NOW)

    with pytest.raises(AppManagerError, match="无效 commit"):
        manager.install("example/weather-mcp")
    assert not (root / "extensions" / "apps" / "example" / "weather-mcp").exists()


def test_install_rolls_back_directory_when_config_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _project(tmp_path)
    manager = _manager(root)
    original = (root / "config" / "apps.toml").read_text(encoding="utf-8")

    def fail_add(_app: object) -> None:
        raise AppManagerError("write failed")

    monkeypatch.setattr(manager.store, "add_app", fail_add)

    with pytest.raises(AppManagerError, match="write failed"):
        manager.install("example/weather-mcp")
    assert not (root / "extensions" / "apps" / "example" / "weather-mcp").exists()
    assert (root / "config" / "apps.toml").read_text(encoding="utf-8") == original
    assert not tuple((root / "extensions" / "apps").glob(".aurora-stage-*"))


def test_remove_deletes_only_managed_directory_and_config(tmp_path: Path) -> None:
    root = _project(tmp_path)
    manager = _manager(root)
    installed = manager.install("example/weather-mcp")
    manual = root / "extensions" / "apps" / "someone" / "manual"
    manual.mkdir(parents=True)
    (manual / "keep.txt").write_text("keep", encoding="utf-8")

    removed = manager.remove("org.example.weather")

    assert removed.path == installed.path
    assert not installed.path.exists()
    assert (manual / "keep.txt").is_file()
    with (root / "config" / "apps.toml").open("rb") as stream:
        apps = tomllib.load(stream)["app"]
    assert [item["package"] for item in apps] == ["org.example.existing"]


def test_remove_restores_directory_when_config_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _project(tmp_path)
    manager = _manager(root)
    installed = manager.install("example/weather-mcp")

    def fail_remove(_package: str, _directory: Path) -> None:
        raise AppManagerError("write failed")

    monkeypatch.setattr(manager.store, "remove_app", fail_remove)

    with pytest.raises(AppManagerError, match="write failed"):
        manager.remove("org.example.weather")
    assert installed.path.is_dir()
    assert (installed.path / MARKER_NAME).is_file()


def test_remove_rejects_unknown_and_non_ready_install(tmp_path: Path) -> None:
    root = _project(tmp_path)
    manager = _manager(root)
    installed = manager.install("example/weather-mcp")
    with pytest.raises(AppManagerError, match="未找到"):
        manager.remove("org.example.unknown")

    path = root / "config" / "apps.toml"
    content = path.read_text(encoding="utf-8")
    start = content.index('[[app]]\npackage = "org.example.weather"')
    path.write_text(content[:start].rstrip() + "\n", encoding="utf-8")
    with pytest.raises(AppManagerError, match="config_missing"):
        manager.remove("org.example.weather")
    assert installed.path.is_dir()


def test_list_reports_package_mismatch_for_same_working_directory(tmp_path: Path) -> None:
    root = _project(tmp_path)
    manager = _manager(root)
    manager.install("example/weather-mcp")
    path = root / "config" / "apps.toml"
    content = path.read_text(encoding="utf-8")
    path.write_text(
        content.replace('package = "org.example.weather"', 'package = "org.example.other"'), encoding="utf-8"
    )

    installed = manager.list().apps[0]

    assert installed.state == "config_mismatch"
    assert installed.detail == "package 不一致"


def test_list_and_remove_reject_marker_repository_path_mismatch(tmp_path: Path) -> None:
    root = _project(tmp_path)
    manager = _manager(root)
    installed = manager.install("example/weather-mcp")
    marker = installed.path / MARKER_NAME
    marker.write_text(
        marker.read_text(encoding="utf-8").replace(
            'repository = "example/weather-mcp"',
            'repository = "another/weather-mcp"',
        ),
        encoding="utf-8",
    )

    listed = manager.list().apps[0]

    assert listed.state == "config_mismatch"
    assert listed.detail == "repository 与安装目录不一致"
    with pytest.raises(AppManagerError, match="config_mismatch"):
        manager.remove("org.example.weather")
    assert installed.path.is_dir()


def test_remove_restores_directory_when_interrupted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _project(tmp_path)
    manager = _manager(root)
    installed = manager.install("example/weather-mcp")

    def interrupt(_package: str, _directory: Path) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(manager.store, "remove_app", interrupt)

    with pytest.raises(KeyboardInterrupt):
        manager.remove("org.example.weather")
    assert installed.path.is_dir()
    assert (installed.path / MARKER_NAME).is_file()


def test_write_lock_rejects_concurrent_operation(tmp_path: Path) -> None:
    root = _project(tmp_path)
    manager = _manager(root)
    manager.store.install_root.mkdir(parents=True)

    with (
        manager.store.lock("first"),
        pytest.raises(AppManagerError, match="另一个 App 写操作"),
        manager.store.lock("second"),
    ):
        pytest.fail("不应取得第二把锁")


@pytest.mark.parametrize("version", ("true", "1.0"))
def test_list_rejects_non_integer_marker_version(tmp_path: Path, version: str) -> None:
    root = _project(tmp_path)
    manager = _manager(root)
    installed = manager.install("example/weather-mcp")
    marker = installed.path / MARKER_NAME
    marker.write_text(
        marker.read_text(encoding="utf-8").replace("marker_version = 1", f"marker_version = {version}"),
        encoding="utf-8",
    )

    listed = manager.list().apps

    assert listed[0].state == "invalid_marker"
    assert listed[0].detail is not None


def test_install_cleans_staging_when_interrupted(tmp_path: Path) -> None:
    root = _project(tmp_path)

    def interrupt(url: str, destination: Path, ref: str | None) -> str:
        raise KeyboardInterrupt

    manager = AppManager(root, github=_github(), clone=interrupt, clock=lambda: _NOW)

    with pytest.raises(KeyboardInterrupt):
        manager.install("example/weather-mcp")
    assert not (root / "extensions" / "apps" / "example" / "weather-mcp").exists()
    assert not tuple((root / "extensions" / "apps").glob(".aurora-stage-*"))
    assert not (root / "extensions" / "apps" / LOCK_NAME).exists()


def test_one_damaged_install_does_not_hide_others(tmp_path: Path) -> None:
    root = _project(tmp_path)
    manager = _manager(root)
    manager.install("example/weather-mcp")
    second = AppManager(
        root,
        github=GitHubClient(transport=_second_transport),
        clone=_clone_second,
        clock=lambda: _NOW,
    )
    second.install("another/calendar-mcp")
    damaged = root / "extensions" / "apps" / "example" / "weather-mcp"
    (damaged / MARKER_NAME).write_text("marker_version = 99\n", encoding="utf-8")

    listed = manager.list().apps

    assert sorted((item.package, item.state) for item in listed) == [
        ("-", "invalid_marker"),
        ("org.example.calendar", "ready"),
    ]
    second.remove("org.example.calendar")
    assert not (root / "extensions" / "apps" / "another" / "calendar-mcp").exists()
    with pytest.raises(AppManagerError, match="未找到"):
        manager.remove("org.example.weather")


def test_list_and_remove_reject_linked_managed_directory(tmp_path: Path) -> None:
    root = _project(tmp_path)
    manager = _manager(root)
    installed = manager.install("example/weather-mcp")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    installed.path.replace(root / "extensions" / "apps" / ".backup")
    if not _create_directory_link(outside, installed.path):
        pytest.skip("当前环境没有目录链接权限")

    listed = manager.list().apps

    assert listed[0].state == "invalid_marker"
    assert "越界" in (listed[0].detail or "")
    with pytest.raises(AppManagerError, match="未找到"):
        manager.remove("org.example.weather")
    assert (outside / "secret.txt").read_text(encoding="utf-8") == "secret"


def test_list_rejects_linked_marker_without_reading_target(tmp_path: Path) -> None:
    root = _project(tmp_path)
    manager = _manager(root)
    installed = manager.install("example/weather-mcp")
    outside = tmp_path / "outside-marker"
    outside.mkdir()
    (outside / "payload.toml").write_text('package = "org.example.attacker"\n', encoding="utf-8")
    marker = installed.path / MARKER_NAME
    marker.replace(tmp_path / "real-marker.toml")
    if not _create_directory_link(outside, marker):
        pytest.skip("当前环境没有目录链接权限")

    listed = manager.list().apps

    assert listed[0].state == "invalid_marker"
    assert (outside / "payload.toml").read_text(encoding="utf-8") == 'package = "org.example.attacker"\n'


def test_store_rejects_dotdot_and_link_components(tmp_path: Path) -> None:
    root = _project(tmp_path)
    store = AppStore(root)
    for source in ("example/..", "example/."):
        with pytest.raises(AppManagerError, match="受管安装目录"):
            store.destination(source)
    outside = tmp_path / "outside"
    outside.mkdir()
    owner = store.install_root / "example"
    owner.mkdir(parents=True)
    link = owner / "linked"
    if not _create_directory_link(outside, link):
        pytest.skip("当前环境没有目录链接权限")

    with pytest.raises(AppManagerError, match="符号链接或联接"):
        store.destination("example/linked")


def test_store_rejects_linked_install_root_before_access(tmp_path: Path) -> None:
    root = _project(tmp_path / "project")
    outside = tmp_path / "outside"
    outside.mkdir()
    install_root = root / "extensions" / "apps"
    install_root.parent.mkdir()
    if not _create_directory_link(outside, install_root):
        pytest.skip("当前环境没有目录链接权限")
    manager = _manager(root)

    with pytest.raises(AppManagerError, match="符号链接或联接"):
        manager.list()
    with pytest.raises(AppManagerError, match="符号链接或联接"):
        manager.install("example/weather-mcp")
    assert not (outside / LOCK_NAME).exists()
    assert tuple(outside.iterdir()) == ()
