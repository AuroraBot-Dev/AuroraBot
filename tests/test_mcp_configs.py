from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from aurora import load_config
from aurora.configs.apps import APPS_CONFIG, AppConfig
from aurora.configs.platforms import PLATFORMS_CONFIG, PlatformConfig
from aurora.configurator import assemble_config
from src.mcp import McpAppSpec, McpEventMode, McpTransport
from src.mcp.module import build_mcp_specs
from src.mcp.runtime import app_owned_scopes
from src.mcp.scopes import owns_scope

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

_EXPECTED_TEMPLATE_APPS = 2
_EXPECTED_TIMEOUT_SECONDS = 30.0
_QQ_PACKAGE = "org.aurora.qq"
_QQ_SCOPES = ("org.aurora.qq:world",)


def _load_apps(tmp_path: Path, content: str) -> tuple[AppConfig, ...]:
    config_directory = tmp_path / "config"
    config_directory.mkdir(exist_ok=True)
    (config_directory / "apps.toml").write_text(content, encoding="utf-8")
    return assemble_config(tmp_path, (APPS_CONFIG,)).get(APPS_CONFIG).apps


def _load_platforms(tmp_path: Path, content: str) -> tuple[PlatformConfig, ...]:
    config_directory = tmp_path / "config"
    config_directory.mkdir(exist_ok=True)
    (config_directory / "platforms.toml").write_text(content, encoding="utf-8")
    return assemble_config(tmp_path, (PLATFORMS_CONFIG,)).get(PLATFORMS_CONFIG).platforms


def test_template_declares_the_domains_each_app_owns(configured_project: Path) -> None:
    apps = load_config(configured_project).get(APPS_CONFIG).apps

    qq = next(app for app in apps if app.package == _QQ_PACKAGE)
    windows = next(app for app in apps if app.package != _QQ_PACKAGE)

    assert qq.scopes == _QQ_SCOPES
    assert windows.scopes == ()


def test_app_scopes_must_stay_inside_the_app_own_namespace(tmp_path: Path) -> None:
    """命名空间即所有权：扩展不能声明别人的域。"""
    foreign = _STDIO.replace('event_mode = "disabled"', f'event_mode = "disabled"\nscopes = ["{_QQ_SCOPES[0]}"]')

    with pytest.raises(ValueError, match="只能声明自己命名空间下的域"):
        _load_apps(tmp_path, foreign)


def test_app_scopes_accept_the_own_domain_and_its_sub_domains(tmp_path: Path) -> None:
    own = _STDIO.replace(
        'event_mode = "disabled"',
        'event_mode = "disabled"\nscopes = ["org.example.clock:world", "org.example.clock:world/room/1"]',
    )

    app = _load_apps(tmp_path, own)[0]

    assert app.scopes == ("org.example.clock:world", "org.example.clock:world/room/1")


def test_app_scopes_reject_duplicates(tmp_path: Path) -> None:
    duplicated = _STDIO.replace(
        'event_mode = "disabled"',
        'event_mode = "disabled"\nscopes = ["org.example.clock:world", "org.example.clock:world"]',
    )

    with pytest.raises(ValueError, match="不得重复"):
        _load_apps(tmp_path, duplicated)


def test_app_scopes_reject_values_outside_the_scope_grammar() -> None:
    """TOML 层会 strip，所以带空白的域只能从 DTO 构造这一侧验证。"""
    with pytest.raises(ValueError, match="MCP scope 非法"):
        AppConfig(
            "org.example.clock",
            False,
            "stdio",
            "disabled",
            30.0,
            working_dir="extensions/clock",
            command=("uv", "run", "clock"),
            scopes=("org.example.clock:world ",),
        )


def test_owning_a_lookalike_package_is_not_owning_this_one() -> None:
    assert owns_scope(_QQ_PACKAGE, "org.aurora.qq:world")
    assert owns_scope(_QQ_PACKAGE, "org.aurora.qq:world/room/7")
    assert not owns_scope(_QQ_PACKAGE, "org.aurora.qq:worldq")
    assert not owns_scope(_QQ_PACKAGE, "org.aurora.qqq:world/room/7")
    assert not owns_scope(_QQ_PACKAGE, "aurora:world/cadence")


def test_app_owned_scopes_fall_back_to_the_package_domain() -> None:
    spec = McpAppSpec(
        _QQ_PACKAGE,
        False,
        McpTransport.STDIO,
        30.0,
        False,
        McpEventMode.DISABLED,
        command=("uv", "run", "aurora-qq-mcp"),
        working_dir=Path("extensions/apps/Aurora-QQ"),
    )

    assert spec.scopes == ()
    assert app_owned_scopes(spec) == _QQ_SCOPES
    assert app_owned_scopes(replace(spec, scopes=("org.aurora.qq:world/room/1",))) == ("org.aurora.qq:world/room/1",)


def test_app_declaring_an_unregistered_domain_fails_before_startup(configured_project: Path) -> None:
    """域注册表没有覆盖的 App 域必须在启动前失败。"""
    scopes_toml = configured_project / "config" / "scopes.toml"
    text = scopes_toml.read_text(encoding="utf-8")
    without_extensions = text.replace('pattern = "*:world/*"', 'pattern = "aurora:no-such-world/*"').replace(
        'pattern = "*:world"', 'pattern = "aurora:no-such-world"'
    )
    scopes_toml.write_text(without_extensions, encoding="utf-8")

    with pytest.raises(ValueError, match="MCP App 声明了未注册的域"):
        build_mcp_specs(load_config(configured_project))


def test_template_exports_typed_frozen_mcp_config(configured_project: Path) -> None:
    config = load_config(configured_project)
    app_config = config.get(APPS_CONFIG).apps
    platform_config = config.get(PLATFORMS_CONFIG).platforms

    assert len(app_config) == _EXPECTED_TEMPLATE_APPS
    assert all(isinstance(app, AppConfig) for app in app_config)
    assert all(app.enabled is False for app in app_config)
    assert app_config[0].event_mode == "disabled"
    assert app_config[1].event_mode == "world_events"
    assert app_config[1].env == ("AURORA_QQ_TOKEN", "AURORA_QQ_CONFIG")
    assert [item.id for item in platform_config] == ["aurora:platform/console", "aurora:platform/mcp"]
    assert all(item.enabled for item in platform_config)
    assert all(item.logging == "INFO" for item in platform_config)
    assert next(item for item in platform_config if item.id == "aurora:platform/console").config == {}


def test_template_apps_stay_outside_the_installed_src_tree(configured_project: Path) -> None:
    """MCP 应用是外部进程，发布模板不得把 working_dir 指向随包发布的 ``src/``。"""
    apps = load_config(configured_project).get(APPS_CONFIG).apps

    assert apps
    assert all(app.working_dir is not None and not app.working_dir.startswith("src/") for app in apps)


@pytest.mark.parametrize("event_mode", ("disabled", "world_events", "legacy_aurora_event"))
def test_stdio_accepts_each_event_mode_and_project_relative_directory(tmp_path: Path, event_mode: str) -> None:
    config = _load_apps(tmp_path, _STDIO.replace('event_mode = "disabled"', f'event_mode = "{event_mode}"'))
    app = config[0]

    assert app.package == "org.example.clock"
    assert app.working_dir == "extensions/clock"
    assert app.command == ("uv", "run", "clock")
    assert app.env == ("CLOCK_TOKEN",)
    assert app.timeout_seconds == _EXPECTED_TIMEOUT_SECONDS


def test_streamable_http_uses_https_and_optional_auth_environment(tmp_path: Path) -> None:
    with_auth = _load_apps(tmp_path, _HTTP)[0]
    without_auth = _load_apps(tmp_path, _HTTP.replace('auth_env = "MCP_BEARER_TOKEN"\n', ""))[0]

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
    assert _load_apps(tmp_path, "app = []\n") == ()


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
    app = _load_apps(tmp_path, _STDIO.replace('event_mode = "disabled"\n', ""))[0]

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
    config = _load_platforms(
        tmp_path,
        """\
[[platform]]
id = "aurora:platform/mcp"
enabled = false
logging = "NONE"
""",
    )

    assert config == (PlatformConfig("aurora:platform/mcp", enabled=False, logging="NONE"),)


def test_platforms_accepts_empty_and_duplicate_ids_trusting_project(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    root = tmp_path_factory.mktemp("empty")
    config_directory = root / "config"
    config_directory.mkdir()
    (config_directory / "platforms.toml").write_text("platform = []\n", encoding="utf-8")
    empty = assemble_config(root, (PLATFORMS_CONFIG,)).get(PLATFORMS_CONFIG).platforms
    assert empty == ()

    duplicated_entry = '[[platform]]\nid = "aurora:platform/mcp"\nenabled = true\n'
    (config_directory / "platforms.toml").write_text(duplicated_entry * 2, encoding="utf-8")
    duplicated = assemble_config(root, (PLATFORMS_CONFIG,)).get(PLATFORMS_CONFIG).platforms
    assert [item.id for item in duplicated] == ["aurora:platform/mcp", "aurora:platform/mcp"]


@pytest.mark.parametrize(
    "content",
    (
        "",
        '[[platform]]\nid = "aurora:platform/mcp"\nenabled = "true"\n',
        '[[platform]]\nid = "aurora:platform/ghost"\nenabled = true\n',
        '[[platform]]\nid = "aurora:platform/mcp"\nenabled = true\nlogging = "TRACE"\n',
    ),
)
def test_platforms_rejects_unknown_missing_and_non_boolean_fields(tmp_path: Path, content: str) -> None:
    with pytest.raises(ValueError, match=r"未知平台 id|日志级别|布尔值|表数组"):
        _load_platforms(tmp_path, content)
