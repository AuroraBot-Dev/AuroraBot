"""``aurora app`` 的错误映射、退出码与 package 校验测试。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from aurora.commander import run
from aurora.commands import DEFAULT_REGISTRY
from aurora.commands.app import store as store_module
from aurora.commands.app.models import PackageError, RegistryError, registry_package, validate_package
from aurora.utils.process import EXIT_CONFIG_ERROR, EXIT_FAILURE

if TYPE_CHECKING:
    from pathlib import Path

_CONFIG = "config/apps.toml"

_LEGAL_PACKAGES = [
    "com.example.weather",
    "github.example.weather-mcp",
    "github.foo.app-2fast",
    "org.aurora.clock",
    "a.b",
]

_ILLEGAL_PACKAGES = [
    "",
    "weather",
    "GitHub.foo.app",
    "github.123.app",
    "github..app",
    ".github.app",
    "github.foo.应用",
]


def _project(tmp_path: Path, content: str) -> Path:
    directory = tmp_path / "config"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "apps.toml").write_text(content, encoding="utf-8")
    return tmp_path


def _stdio(package: str, working_dir: str = "extensions/apps/example/weather") -> str:
    return (
        f'[[app]]\npackage = "{package}"\nenabled = false\ntransport = "stdio"\n'
        f'working_dir = "{working_dir}"\ncommand = ["uv", "run", "demo"]\nenv = []\n'
        f'timeout_seconds = 30\nevent_mode = "disabled"\n'
    )


def _cli(root: Path, *arguments: str) -> int:
    return run(["--root", str(root), "app", *arguments], registry=DEFAULT_REGISTRY)


@pytest.mark.parametrize("package", _LEGAL_PACKAGES)
def test_validate_package_accepts_lowercase_dotted_names(package: str) -> None:
    assert validate_package(package) == package


@pytest.mark.parametrize("package", _ILLEGAL_PACKAGES)
def test_validate_package_rejects_other_shapes(package: str) -> None:
    with pytest.raises(PackageError):
        validate_package(package)


def test_registry_package_reports_structure_errors_as_registry_errors() -> None:
    with pytest.raises(RegistryError):
        registry_package(7, "config/apps.toml")
    with pytest.raises(RegistryError):
        registry_package("   ", "config/apps.toml")
    with pytest.raises(RegistryError):
        registry_package("Weather", "config/apps.toml")


@pytest.mark.parametrize(
    "arguments",
    [
        ("list",),
        ("enable", "com.example.weather"),
        ("disable", "com.example.weather"),
    ],
)
def test_missing_registry_is_a_configuration_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], arguments: tuple[str, ...]
) -> None:
    (tmp_path / "config").mkdir()

    assert _cli(tmp_path, *arguments) == EXIT_CONFIG_ERROR

    captured = capsys.readouterr()
    assert "App 配置错误" in captured.err
    assert "未找到 config/apps.toml" in captured.err
    assert captured.out == ""


@pytest.mark.parametrize("arguments", [("list",), ("enable", "com.example.weather")])
def test_broken_toml_is_reported_without_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], arguments: tuple[str, ...]
) -> None:
    root = _project(tmp_path, "[[app]\npackage = ")

    assert _cli(root, *arguments) == EXIT_CONFIG_ERROR

    captured = capsys.readouterr()
    assert "无法解析" in captured.err
    assert "Traceback" not in captured.err


@pytest.mark.parametrize("arguments", [("list",), ("enable", "com.example.weather"), ("disable", "com.example.other")])
def test_illegal_registry_package_fails_the_whole_read(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], arguments: tuple[str, ...]
) -> None:
    root = _project(tmp_path, _stdio("Com.Example.Weather"))

    assert _cli(root, *arguments) == EXIT_CONFIG_ERROR

    assert "App 配置错误" in capsys.readouterr().err


def test_duplicate_package_is_a_configuration_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _project(tmp_path, _stdio("com.example.weather") + "\n" + _stdio("com.example.weather"))

    assert _cli(root, "list") == EXIT_CONFIG_ERROR

    assert "重复" in capsys.readouterr().err


@pytest.mark.parametrize("subcommand", ["enable", "disable"])
def test_unknown_package_is_a_configuration_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], subcommand: str
) -> None:
    root = _project(tmp_path, _stdio("com.example.weather"))

    assert _cli(root, subcommand, "com.example.ghost") == EXIT_CONFIG_ERROR

    assert "不存在 package：com.example.ghost" in capsys.readouterr().err


@pytest.mark.parametrize("subcommand", ["enable", "disable"])
def test_illegal_package_argument_is_a_configuration_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], subcommand: str
) -> None:
    root = _project(tmp_path, _stdio("com.example.weather"))

    assert _cli(root, subcommand, "Com.Example.Weather") == EXIT_CONFIG_ERROR

    captured = capsys.readouterr()
    assert "必须是小写点分包名" in captured.err
    assert (root / _CONFIG).read_text(encoding="utf-8").startswith("[[app]]")


def test_a_failed_write_is_a_general_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path, _stdio("com.example.weather"))

    def fail(source: Path, target: Path) -> None:
        raise OSError("disk on fire")

    monkeypatch.setattr(store_module, "_replace", fail)

    assert _cli(root, "enable", "com.example.weather") == EXIT_FAILURE

    captured = capsys.readouterr()
    assert "App 操作失败" in captured.err
    assert "无法写入 apps.toml" in captured.err
    assert captured.out == ""


def test_duplicate_package_cannot_be_toggled(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """重复条目下无法确定该改哪一条，写操作必须先失败。"""
    root = _project(tmp_path, _stdio("com.example.weather") + "\n" + _stdio("com.example.weather"))

    assert _cli(root, "enable", "com.example.weather") == EXIT_CONFIG_ERROR

    assert "重复" in capsys.readouterr().err


@pytest.mark.parametrize("body", ["app = 1\n", 'app = "weather"\n'])
def test_app_that_is_not_a_table_array_fails_structure_checks(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], body: str
) -> None:
    root = _project(tmp_path, body)

    assert _cli(root, "enable", "com.example.weather") == EXIT_CONFIG_ERROR

    assert "必须是表数组" in capsys.readouterr().err


def test_list_without_a_subcommand_prints_help(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _project(tmp_path, _stdio("com.example.weather"))

    assert _cli(root) == 0

    assert "list" in capsys.readouterr().out
