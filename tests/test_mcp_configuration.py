from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from aurora import load_config
from aurora.config import collect_config
from aurora.configuration import apps, platforms
from aurora.configuration.apps import APPS_CONFIG, AppConfig, AppsConfig
from aurora.configuration.platforms import PLATFORMS_CONFIG, McpPlatformConfig, PlatformsConfig
from src.mcp import McpAppSpec, McpEventMode, McpTransport

if TYPE_CHECKING:
    from pathlib import Path

_STDIO = """\
[[app]]
package = "org.example.clock"
enabled = true
transport = "stdio"
working_dir = "extensions/clock"
command = ["uv", "run", "clock"]
env = ["CLOCK_TOKEN"]
timeout_seconds = 30
event_mode = "disabled"
"""

_HTTP = """\
[[app]]
package = "org.example.remote"
enabled = true
transport = "streamable_http"
url = "https://mcp.example.org/rpc"
auth_env = "MCP_BEARER_TOKEN"
timeout_seconds = 15.5
event_mode = "disabled"
"""

_EXPECTED_TEMPLATE_APPS = 3
_EXPECTED_TIMEOUT_SECONDS = 30.0


def _load_apps(tmp_path: Path, content: str) -> AppsConfig:
    config_directory = tmp_path / "config"
    config_directory.mkdir(exist_ok=True)
    (config_directory / "apps.toml").write_text(content, encoding="utf-8")
    return collect_config(tmp_path, (apps.register,)).get(APPS_CONFIG)


def _load_platforms(tmp_path: Path, content: str) -> PlatformsConfig:
    config_directory = tmp_path / "config"
    config_directory.mkdir(exist_ok=True)
    (config_directory / "platforms.toml").write_text(content, encoding="utf-8")
    return collect_config(tmp_path, (platforms.register,)).get(PLATFORMS_CONFIG)


def test_template_exports_typed_frozen_mcp_configuration(configured_project: Path) -> None:
    configuration = load_config(configured_project)
    app_configuration = configuration.get(APPS_CONFIG)
    platform_configuration = configuration.get(PLATFORMS_CONFIG)

    assert isinstance(app_configuration, AppsConfig)
    assert len(app_configuration.apps) == _EXPECTED_TEMPLATE_APPS
    assert all(isinstance(app, AppConfig) for app in app_configuration.apps)
    assert all(app.enabled is False for app in app_configuration.apps)
    assert app_configuration.apps[0].event_mode == "disabled"
    assert app_configuration.apps[1].event_mode == "disabled"
    assert app_configuration.apps[2].event_mode == "world_events"
    assert app_configuration.apps[2].env == ("AURORA_QQ_TOKEN", "AURORA_QQ_CONFIG")
    assert platform_configuration == PlatformsConfig(McpPlatformConfig(enabled=True, terminal_logs=True))


@pytest.mark.parametrize("event_mode", ("disabled", "world_events", "legacy_aurora_event"))
def test_stdio_accepts_each_event_mode_and_project_relative_directory(tmp_path: Path, event_mode: str) -> None:
    configuration = _load_apps(tmp_path, _STDIO.replace('event_mode = "disabled"', f'event_mode = "{event_mode}"'))
    app = configuration.apps[0]

    assert app.package == "org.example.clock"
    assert app.working_dir == "extensions/clock"
    assert app.command == ("uv", "run", "clock")
    assert app.env == ("CLOCK_TOKEN",)
    assert app.timeout_seconds == _EXPECTED_TIMEOUT_SECONDS


def test_streamable_http_uses_https_and_optional_auth_environment(tmp_path: Path) -> None:
    with_auth = _load_apps(tmp_path, _HTTP).apps[0]
    without_auth = _load_apps(tmp_path, _HTTP.replace('auth_env = "MCP_BEARER_TOKEN"\n', "")).apps[0]

    assert with_auth.url == "https://mcp.example.org/rpc"
    assert with_auth.auth_env == "MCP_BEARER_TOKEN"
    assert with_auth.command == with_auth.env == ()
    assert without_auth.auth_env is None


def test_streamable_http_rejects_world_events_in_config_dto_and_runtime_spec(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="暂不支持 world_events"):
        _load_apps(tmp_path, _HTTP.replace('event_mode = "disabled"', 'event_mode = "world_events"'))

    with pytest.raises(ValueError, match="暂不支持 world_events"):
        McpAppSpec(
            package="org.example.remote",
            enabled=True,
            transport=McpTransport.STREAMABLE_HTTP,
            timeout_seconds=5,
            terminal_logs=False,
            event_mode=McpEventMode.WORLD_EVENTS,
            url="https://mcp.example.org/rpc",
        )


def test_empty_app_directory_is_valid(tmp_path: Path) -> None:
    assert _load_apps(tmp_path, "app = []\n") == AppsConfig(())


@pytest.mark.parametrize(
    "content",
    (
        "",
        "app = []\nunknown = true\n",
        "app = {}\n",
        _STDIO + "unknown = true\n",
    ),
)
def test_apps_rejects_unknown_missing_and_invalid_topology(tmp_path: Path, content: str) -> None:
    with pytest.raises(ValueError, match=r"字段不匹配|表数组"):
        _load_apps(tmp_path, content)


def test_missing_event_mode_defaults_to_disabled_for_existing_personal_config(tmp_path: Path) -> None:
    app = _load_apps(tmp_path, _STDIO.replace('event_mode = "disabled"\n', "")).apps[0]

    assert app.event_mode == "disabled"


@pytest.mark.parametrize("package", ("clock", "Org.example.clock", "org..clock", "org.example.clock!"))
def test_apps_rejects_invalid_package_names(tmp_path: Path, package: str) -> None:
    with pytest.raises(ValueError, match="小写点分包名"):
        _load_apps(tmp_path, _STDIO.replace("org.example.clock", package))


def test_apps_rejects_duplicate_packages_even_when_disabled(tmp_path: Path) -> None:
    duplicate = _STDIO + _STDIO.replace("enabled = true", "enabled = false")

    with pytest.raises(ValueError, match="不得重复"):
        _load_apps(tmp_path, duplicate)


@pytest.mark.parametrize("timeout", ("0", "-1", "true", "nan", "inf"))
def test_apps_rejects_non_positive_boolean_and_non_finite_timeout(tmp_path: Path, timeout: str) -> None:
    with pytest.raises(ValueError, match="有限正数"):
        _load_apps(tmp_path, _STDIO.replace("timeout_seconds = 30", f"timeout_seconds = {timeout}"))


@pytest.mark.parametrize("working_dir", ("/outside", "../outside", "C:/outside"))
def test_stdio_working_directory_must_stay_relative_to_project(tmp_path: Path, working_dir: str) -> None:
    with pytest.raises(ValueError, match="项目内相对目录"):
        _load_apps(tmp_path, _STDIO.replace("extensions/clock", working_dir))


@pytest.mark.parametrize("env", ('["BAD-NAME"]', '["TOKEN", "TOKEN"]', '["变量"]', "[1]"))
def test_stdio_environment_is_an_ascii_unique_name_allowlist(tmp_path: Path, env: str) -> None:
    with pytest.raises(ValueError, match=r"环境变量名|文本数组|不得重复"):
        _load_apps(tmp_path, _STDIO.replace('["CLOCK_TOKEN"]', env))


@pytest.mark.parametrize("command", ("[]", '[""]', "[1]"))
def test_stdio_command_must_be_a_non_empty_text_array(tmp_path: Path, command: str) -> None:
    with pytest.raises(ValueError, match=r"command.*文本数组|字段 command 必须是文本数组"):
        _load_apps(tmp_path, _STDIO.replace('["uv", "run", "clock"]', command))


@pytest.mark.parametrize(
    "content",
    (
        _STDIO + 'url = "https://mcp.example.org"\n',
        _STDIO + 'auth_env = "TOKEN"\n',
        _HTTP + "env = []\n",
        _HTTP + 'working_dir = "extensions/remote"\n',
        _HTTP + 'command = ["serve"]\n',
    ),
)
def test_transports_reject_each_others_fields(tmp_path: Path, content: str) -> None:
    with pytest.raises(ValueError, match="字段不匹配"):
        _load_apps(tmp_path, content)


@pytest.mark.parametrize(
    "url",
    (
        "http://mcp.example.org/rpc",
        "https:///missing-host",
        "https://user:secret@mcp.example.org/rpc",
        "https://mcp.example.org/rpc#fragment",
    ),
)
def test_streamable_http_requires_safe_https_url(tmp_path: Path, url: str) -> None:
    with pytest.raises(ValueError, match="HTTPS URL"):
        _load_apps(tmp_path, _HTTP.replace("https://mcp.example.org/rpc", url))


def test_apps_rejects_invalid_event_mode_enabled_type_and_auth_environment(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="event_mode"):
        _load_apps(tmp_path, _STDIO.replace("disabled", "vendor_events"))
    with pytest.raises(ValueError, match="布尔值"):
        _load_apps(tmp_path, _STDIO.replace("enabled = true", 'enabled = "true"'))
    with pytest.raises(ValueError, match="环境变量名"):
        _load_apps(tmp_path, _HTTP.replace("MCP_BEARER_TOKEN", "BAD-NAME"))


def test_platforms_parses_exact_mcp_preference(tmp_path: Path) -> None:
    configuration = _load_platforms(
        tmp_path,
        """\
[platform.mcp]
enabled = false
terminal_logs = true
""",
    )

    assert configuration == PlatformsConfig(McpPlatformConfig(enabled=False, terminal_logs=True))


@pytest.mark.parametrize(
    "content",
    (
        "",
        "[other]\nenabled = true\n",
        "[platform.other]\nenabled = true\n",
        "[platform.mcp]\nenabled = true\n",
        "[platform.mcp]\nenabled = true\nterminal_logs = false\nunknown = true\n",
        '[platform.mcp]\nenabled = "true"\nterminal_logs = false\n',
    ),
)
def test_platforms_rejects_unknown_missing_and_non_boolean_fields(tmp_path: Path, content: str) -> None:
    with pytest.raises(ValueError, match=r"字段不匹配|布尔值"):
        _load_platforms(tmp_path, content)
