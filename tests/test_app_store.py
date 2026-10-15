"""``config/apps.toml`` 的读取、状态判定与原子写测试。"""

from __future__ import annotations

import os
import stat
from typing import TYPE_CHECKING

import pytest

from aurora.commands.app import store as store_module
from aurora.commands.app.models import AppListItem, AppNotFoundError, ConfigError, PathError, RegistryError
from aurora.commands.app.store import AppStore, app_table, render_entry
from src.mcp.config import AppConfig

if TYPE_CHECKING:
    from pathlib import Path

    from aurora.commands.app.models import AppList

_CONFIG_DIRECTORY = "config"
_GROUP_READABLE = 0o640


def _project(tmp_path: Path, content: str) -> Path:
    """写入一份 config/apps.toml 并返回项目根目录。"""
    (tmp_path / _CONFIG_DIRECTORY).mkdir(parents=True, exist_ok=True)
    (tmp_path / _CONFIG_DIRECTORY / "apps.toml").write_text(content, encoding="utf-8")
    return tmp_path


def _stdio(package: str, working_dir: str | None, *, enabled: bool = False) -> str:
    """生成一个只用于状态判定的 stdio 条目。"""
    lines = [f'[[app]]\npackage = "{package}"\nenabled = {str(enabled).lower()}\ntransport = "stdio"\n']
    if working_dir is not None:
        lines.append(f'working_dir = "{working_dir}"\n')
    lines.append('command = ["uv", "run", "demo"]\nenv = []\ntimeout_seconds = 30\nevent_mode = "disabled"\n')
    return "".join(lines)


def _by_package(result: AppList) -> dict[str, AppListItem]:
    return {item.package: item for item in result.apps}


def _config(package: str, working_dir: str) -> AppConfig:
    """一条运行时配置，字段与 ``[[app]]`` 的八个白名单键一一对应。"""
    return AppConfig(
        package=package,
        enabled=False,
        transport="stdio",
        event_mode="disabled",
        timeout_seconds=60.0,
        working_dir=working_dir,
        command=("uv", "run", "demo"),
        env=(),
    )


def test_list_reports_stdio_ready_missing_and_invalid(tmp_path: Path) -> None:
    root = _project(
        tmp_path,
        _stdio("com.example.ready", "extensions/apps/example/ready")
        + "\n"
        + _stdio("com.example.missing", "extensions/apps/example/missing")
        + "\n"
        + _stdio("com.example.escaping", "../../outside"),
    )
    (root / "extensions" / "apps" / "example" / "ready").mkdir(parents=True)

    items = _by_package(AppStore(root).list_apps())

    assert items["com.example.ready"].state == "ready"
    assert items["com.example.missing"].state == "missing"
    assert items["com.example.escaping"].state == "invalid"


def test_list_does_not_require_two_level_managed_paths(tmp_path: Path) -> None:
    """受管根不是唯一合法位置；层级深度不参与状态判定。"""
    root = _project(
        tmp_path,
        _stdio("com.example.flat", "extensions/apps/only-one-level")
        + "\n"
        + _stdio("com.example.deep", "extensions/apps/a/b/c")
        + "\n"
        + _stdio("com.example.outside_root", "examples/weather")
        + "\n"
        + _stdio("com.example.managed", "extensions/apps/owner/repo"),
    )
    for working_dir in ("extensions/apps/only-one-level", "extensions/apps/a/b/c", "examples/weather"):
        (root / working_dir).mkdir(parents=True, exist_ok=True)
    (root / "extensions" / "apps" / "owner" / "repo").mkdir(parents=True)

    result = AppStore(root).list_apps()

    assert [item.state for item in result.apps] == ["ready"] * 4


@pytest.mark.parametrize(
    "working_dir",
    ["/etc", "C:/Windows", "../outside", "extensions/apps/../../outside", ""],
)
def test_list_marks_unsafe_working_dir_invalid(tmp_path: Path, working_dir: str) -> None:
    root = _project(tmp_path, _stdio("com.example.bad", working_dir))

    item = AppStore(root).list_apps().apps[0]

    assert item.state == "invalid"


def test_list_marks_symlinked_working_dir_invalid(tmp_path: Path) -> None:
    root = _project(tmp_path, _stdio("com.example.linked", "extensions/apps/example/linked"))
    link = root / "extensions" / "apps" / "example" / "linked"
    link.parent.mkdir(parents=True)
    try:
        link.symlink_to(root / "elsewhere", target_is_directory=True)
    except OSError as error:  # pragma: no cover - 平台不具备创建符号链接的权限
        pytest.skip(f"当前环境无法创建符号链接：{error}")

    assert AppStore(root).list_apps().apps[0].state == "invalid"


def test_list_marks_junctioned_working_dir_invalid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """不能依赖平台真的存在联接，直接让路径链上的目录报告自己是联接。"""
    root = _project(tmp_path, _stdio("com.example.joined", "extensions/apps/example/joined"))
    (root / "extensions" / "apps" / "example" / "joined").mkdir(parents=True)
    original = type(root).is_junction

    def is_junction(self: Path) -> bool:
        return self.name == "joined" or original(self)

    monkeypatch.setattr(type(root), "is_junction", is_junction)

    assert AppStore(root).list_apps().apps[0].state == "invalid"


def test_validate_registered_working_dir_rejects_links_directly(tmp_path: Path) -> None:
    root = _project(tmp_path, _stdio("com.example.plain", "extensions/apps/example/plain"))
    store = AppStore(root)

    with pytest.raises(PathError):
        store.validate_registered_working_dir("../outside")


def test_list_reports_remote_app_as_configured(tmp_path: Path) -> None:
    """远程条目没有本地文件可查：列表只能说「这一条读得通」。"""
    root = _project(
        tmp_path,
        '[[app]]\npackage = "com.example.remote"\nenabled = true\ntransport = "streamable_http"\n'
        'url = "https://example.com/mcp"\nauth_env = "EXAMPLE_TOKEN"\ntimeout_seconds = 60\n',
    )

    item = AppStore(root).list_apps().apps[0]

    assert (item.state, item.enabled, item.path) == ("configured", True, None)
    assert item.kind == "remote"


@pytest.mark.parametrize(
    "body",
    [
        '[[app]]\npackage = "com.example.remote"\nenabled = false\ntransport = "streamable_http"\n'
        "timeout_seconds = 60\n",
        '[[app]]\npackage = "com.example.remote"\nenabled = false\ntransport = "streamable_http"\n'
        'url = "http://example.com/mcp"\ntimeout_seconds = 60\n',
        '[[app]]\npackage = "com.example.remote"\nenabled = false\ntransport = "streamable_http"\n'
        'url = "https://user:pass@example.com/mcp"\ntimeout_seconds = 60\n',
    ],
)
def test_list_marks_remote_app_with_unusable_url_invalid(tmp_path: Path, body: str) -> None:
    root = _project(tmp_path, body)

    assert AppStore(root).list_apps().apps[0].state == "invalid"


def test_list_marks_unknown_transport_invalid(tmp_path: Path) -> None:
    root = _project(
        tmp_path,
        '[[app]]\npackage = "com.example.weird"\nenabled = false\ntransport = "carrier-pigeon"\ntimeout_seconds = 30\n',
    )

    item = AppStore(root).list_apps().apps[0]

    assert (item.state, item.transport) == ("invalid", "carrier-pigeon")


def test_list_marks_stdio_entry_without_working_dir_invalid(tmp_path: Path) -> None:
    root = _project(tmp_path, _stdio("com.example.incomplete", None))

    item = AppStore(root).list_apps().apps[0]

    assert (item.state, item.path) == ("invalid", "-")


def test_list_rejects_missing_or_illegal_package(tmp_path: Path) -> None:
    missing = _project(tmp_path / "missing", '[[app]]\nenabled = false\ntransport = "stdio"\n')
    illegal = _project(tmp_path / "illegal", _stdio("Com.Example.Weather", "extensions/apps/a/b"))

    with pytest.raises(RegistryError):
        AppStore(missing).list_apps()
    with pytest.raises(RegistryError):
        AppStore(illegal).list_apps()


def test_list_rejects_duplicate_package(tmp_path: Path) -> None:
    root = _project(
        tmp_path,
        _stdio("com.example.weather", "extensions/apps/a/b")
        + "\n"
        + _stdio("com.example.weather", "extensions/apps/a/c"),
    )

    with pytest.raises(RegistryError, match="重复"):
        AppStore(root).list_apps()


def test_list_requires_a_readable_registry(tmp_path: Path) -> None:
    (tmp_path / _CONFIG_DIRECTORY).mkdir()
    with pytest.raises(ConfigError, match="未找到"):
        AppStore(tmp_path).list_apps()

    broken = _project(tmp_path / "broken", "[[app]\npackage = ")
    with pytest.raises(ConfigError, match="无法解析"):
        AppStore(broken).list_apps()

    shapeless = _project(tmp_path / "shapeless", "app = 1\n")
    with pytest.raises(RegistryError):
        AppStore(shapeless).list_apps()


def test_list_accepts_an_empty_registry(tmp_path: Path) -> None:
    root = _project(tmp_path, "app = []\n")

    result = AppStore(root).list_apps()

    assert result.apps == ()


def test_list_only_reads_registered_entries(tmp_path: Path) -> None:
    """磁盘上存在但未注册的目录不出现在结果里。"""
    root = _project(tmp_path, _stdio("com.example.known", "extensions/apps/owner/known"))
    (root / "extensions" / "apps" / "owner" / "known").mkdir(parents=True)
    (root / "extensions" / "apps" / "ghost" / "unregistered").mkdir(parents=True)

    assert [item.package for item in AppStore(root).list_apps().apps] == ["com.example.known"]


# --- 条目的渲染 ------------------------------------------------------------------
#
# 安装确认时展示的那段 TOML 与最终写进文件的那一段出自同一个 app_table，所以这两组
# 断言同时约束着两件事：键集必须是运行时白名单允许的那几个，且渲染出来的文本本身
# 就是一份能被读回来的合法注册表。


def _remote_config(package: str, *, auth_env: str | None = None) -> AppConfig:
    return AppConfig(
        package=package,
        enabled=False,
        transport="streamable_http",
        event_mode="disabled",
        timeout_seconds=60.0,
        url="https://mcp.example.com/rpc",
        auth_env=auth_env,
    )


def test_a_stdio_entry_carries_no_url_or_auth_env() -> None:
    rendered = app_table(_config("com.example.local", "extensions/apps/x/y"))

    assert set(rendered.keys()) == {
        "package",
        "enabled",
        "transport",
        "working_dir",
        "command",
        "env",
        "timeout_seconds",
        "event_mode",
    }


def test_a_remote_entry_carries_no_working_dir_or_command() -> None:
    rendered = app_table(_remote_config("com.example.remote"))

    assert set(rendered.keys()) == {
        "package",
        "enabled",
        "transport",
        "url",
        "timeout_seconds",
        "event_mode",
    }


def test_auth_env_is_written_only_when_there_is_one() -> None:
    """没有凭据就是「这个端点不需要凭据」；写一个空值反而会被解析器判为非法。"""
    assert "auth_env" not in app_table(_remote_config("com.example.remote"))
    assert app_table(_remote_config("com.example.remote", auth_env="MCP_TOKEN"))["auth_env"] == "MCP_TOKEN"


def test_a_rendered_stdio_entry_reads_back_as_usable(tmp_path: Path) -> None:
    root = _project(tmp_path, render_entry(_config("com.example.local", "extensions/apps/x/y")))
    (root / "extensions" / "apps" / "x" / "y").mkdir(parents=True)

    item = AppStore(root).list_apps().apps[0]

    assert (item.package, item.kind, item.state) == ("com.example.local", "local", "ready")


def test_a_rendered_remote_entry_reads_back_as_usable(tmp_path: Path) -> None:
    root = _project(tmp_path, render_entry(_remote_config("com.example.remote", auth_env="MCP_TOKEN")))

    item = AppStore(root).list_apps().apps[0]

    assert (item.package, item.kind, item.state) == ("com.example.remote", "remote", "configured")


def test_set_enabled_preserves_comments_order_and_other_entries(tmp_path: Path) -> None:
    root = _project(
        tmp_path,
        "# comment A\n"
        "\n"
        "[[app]]\n"
        'package = "com.example.weather" # app\n'
        "enabled = false\n"
        'transport = "stdio"\n'
        'working_dir = "extensions/apps/example/weather"\n'
        'command = ["uv", "run", "weather-mcp"]\n'
        "env = []\n"
        "timeout_seconds = 60\n"
        'event_mode = "disabled"\n'
        "\n"
        "# keep me\n"
        "[[app]]\n"
        'package = "com.example.other"\n'
        "enabled = true\n"
        'transport = "stdio"\n'
        'working_dir = "extensions/apps/example/other"\n'
        'command = ["uv", "run", "other"]\n'
        "env = []\n"
        "timeout_seconds = 20\n"
        'event_mode = "disabled"\n',
    )

    assert AppStore(root).set_enabled("com.example.weather", True) is True
    written = (root / _CONFIG_DIRECTORY / "apps.toml").read_text(encoding="utf-8")

    assert "# comment A" in written
    assert 'package = "com.example.weather" # app' in written
    assert "# keep me" in written
    assert "enabled = true\n" in written
    assert "timeout_seconds = 60" in written
    assert written.index("com.example.weather") < written.index("com.example.other")


def test_set_enabled_is_idempotent_and_leaves_the_file_untouched(tmp_path: Path) -> None:
    root = _project(tmp_path, _stdio("com.example.weather", "extensions/apps/a/b", enabled=True))
    path = root / _CONFIG_DIRECTORY / "apps.toml"
    before = path.read_text(encoding="utf-8")

    assert AppStore(root).set_enabled("com.example.weather", True) is False
    assert path.read_text(encoding="utf-8") == before


def test_set_enabled_reports_unknown_package(tmp_path: Path) -> None:
    root = _project(tmp_path, _stdio("com.example.weather", "extensions/apps/a/b"))

    with pytest.raises(AppNotFoundError):
        AppStore(root).set_enabled("com.example.ghost", True)


def test_set_enabled_keeps_the_original_when_replacement_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _project(tmp_path, _stdio("com.example.weather", "extensions/apps/a/b"))
    path = root / _CONFIG_DIRECTORY / "apps.toml"
    before = path.read_text(encoding="utf-8")

    def fail(source: Path, target: Path) -> None:
        raise OSError("disk on fire")

    monkeypatch.setattr(store_module, "_replace", fail)

    with pytest.raises(RegistryError, match="无法写入"):
        AppStore(root).set_enabled("com.example.weather", True)

    assert path.read_text(encoding="utf-8") == before
    assert list((root / _CONFIG_DIRECTORY).iterdir()) == [path]


def test_set_enabled_keeps_the_original_when_the_temporary_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path, _stdio("com.example.weather", "extensions/apps/a/b"))
    path = root / _CONFIG_DIRECTORY / "apps.toml"
    before = path.read_text(encoding="utf-8")

    def fail(descriptor: int) -> None:
        raise OSError("fsync unsupported")

    monkeypatch.setattr(store_module.os, "fsync", fail)

    with pytest.raises(RegistryError, match="无法写入"):
        AppStore(root).set_enabled("com.example.weather", True)

    assert path.read_text(encoding="utf-8") == before
    assert list((root / _CONFIG_DIRECTORY).iterdir()) == [path]


def test_set_enabled_requires_an_existing_registry(tmp_path: Path) -> None:
    (tmp_path / _CONFIG_DIRECTORY).mkdir()

    with pytest.raises(ConfigError, match="未找到"):
        AppStore(tmp_path).set_enabled("com.example.weather", True)

    assert list((tmp_path / _CONFIG_DIRECTORY).iterdir()) == []


def test_remove_app_keeps_the_registry_readable_after_the_last_entry(tmp_path: Path) -> None:
    """删掉最后一条之后必须留下 ``app = []``，否则注册表会变成一份读不了的文件。

    tomlkit 会把空掉的表数组整个渲染掉，文件里只剩下一个空文档；而读取端要求
    ``app`` 存在。少了这一步，「移除最后一个 App」会让 aurora app list 直接报
    「配置字段 app 必须是表数组」。
    """
    root = _project(tmp_path, _stdio("com.example.weather", "extensions/apps/example/weather"))
    store = AppStore(root)

    store.remove_app("com.example.weather")

    assert store.list_apps().apps == ()
    assert (root / _CONFIG_DIRECTORY / "apps.toml").read_text(encoding="utf-8").strip() == "app = []"


def test_remove_app_leaves_the_remaining_entries_alone(tmp_path: Path) -> None:
    content = _stdio("com.example.weather", "extensions/apps/example/weather")
    content += _stdio("com.example.clock", "extensions/apps/example/clock")
    store = AppStore(_project(tmp_path, content))

    store.remove_app("com.example.weather")

    assert [item.package for item in store.list_apps().apps] == ["com.example.clock"]


def test_remove_app_reports_an_unknown_package(tmp_path: Path) -> None:
    store = AppStore(_project(tmp_path, _stdio("com.example.weather", "extensions/apps/example/weather")))

    with pytest.raises(AppNotFoundError, match="不存在"):
        store.remove_app("com.example.missing")


def test_remove_app_requires_an_existing_registry(tmp_path: Path) -> None:
    (tmp_path / _CONFIG_DIRECTORY).mkdir()

    with pytest.raises(ConfigError, match="未找到"):
        AppStore(tmp_path).remove_app("com.example.weather")


def test_add_app_creates_the_key_when_the_registry_has_none(tmp_path: Path) -> None:
    """注释-only 的文件没有 ``app`` 键，加第一条时必须自己把表数组建出来。"""
    store = AppStore(_project(tmp_path, "# 只有一行注释\n"))

    store.add_app(_config("com.example.weather", "extensions/apps/example/weather"))

    assert [item.package for item in store.list_apps().apps] == ["com.example.weather"]
    written = (store.project_root / _CONFIG_DIRECTORY / "apps.toml").read_text(encoding="utf-8")
    assert written.startswith("# 只有一行注释"), "用户写的注释不能被吃掉"


def test_add_app_appends_to_an_empty_array(tmp_path: Path) -> None:
    store = AppStore(_project(tmp_path, "app = []\n"))

    store.add_app(_config("com.example.weather", "extensions/apps/example/weather"))

    assert [item.package for item in store.list_apps().apps] == ["com.example.weather"]


def test_atomic_write_replaces_content_without_leaving_temporaries(tmp_path: Path) -> None:
    directory = tmp_path / _CONFIG_DIRECTORY
    directory.mkdir()
    path = directory / "apps.toml"
    path.write_text("before\n", encoding="utf-8")

    store_module._atomic_write(path, "after\n")

    assert path.read_text(encoding="utf-8") == "after\n"
    assert list(directory.iterdir()) == [path]


@pytest.mark.skipif(os.name != "posix", reason="Windows 不使用 POSIX 权限位")
def test_atomic_write_keeps_file_permissions(tmp_path: Path) -> None:
    directory = tmp_path / _CONFIG_DIRECTORY
    directory.mkdir()
    path = directory / "apps.toml"
    path.write_text("before\n", encoding="utf-8")
    path.chmod(_GROUP_READABLE)

    store_module._atomic_write(path, "after\n")

    assert stat.S_IMODE(path.stat().st_mode) == _GROUP_READABLE
