"""``aurora app`` 的命令注册、列表渲染与开关行为测试。"""

from __future__ import annotations

import json
import unicodedata
from typing import TYPE_CHECKING

import pytest

from aurora.commander import run
from aurora.commands import DEFAULT_REGISTRY
from aurora.utils.process import EXIT_FAILURE

if TYPE_CHECKING:
    from pathlib import Path

_CONFIG = "config/apps.toml"
# 表头单元格原文；带框渲染后每格由 | 分隔，"PACKAGE ID" 是一个整体。
_HEADERS = ["PACKAGE ID", "ENABLED", "TRANSPORT", "STATE", "PATH"]
# render_table 的表头分隔行形如 |====+====|，在它之前的最后一格是表头。
_SEPARATOR_PREFIX = "|="
_FULLWIDTH = frozenset(("F", "W"))


def _project(tmp_path: Path, content: str) -> Path:
    directory = tmp_path / "config"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "apps.toml").write_text(content, encoding="utf-8")
    return tmp_path


def _stdio(package: str, working_dir: str, *, enabled: bool = False) -> str:
    return (
        f'[[app]]\npackage = "{package}"\nenabled = {str(enabled).lower()}\ntransport = "stdio"\n'
        f'working_dir = "{working_dir}"\ncommand = ["uv", "run", "demo"]\nenv = []\n'
        f'timeout_seconds = 30\nevent_mode = "disabled"\n'
    )


def _cli(root: Path, *arguments: str) -> int:
    return run(["--root", str(root), "app", *arguments], registry=DEFAULT_REGISTRY)


def _cells(line: str) -> list[str]:
    """取出一行网格里的单元格文本。"""
    return [cell.strip() for cell in line.strip("|").split("|")]


def _separator_index(output: str) -> int:
    """``|====|`` 行的下标；它把表头与数据行分开，也排除了上方的 banner。"""
    return next(index for index, line in enumerate(output.splitlines()) if line.startswith(_SEPARATOR_PREFIX))


def _header_row(output: str) -> list[str]:
    return _cells(output.splitlines()[_separator_index(output) - 1])


def _data_rows(output: str) -> list[list[str]]:
    lines = output.splitlines()
    return [_cells(line) for line in lines[_separator_index(output) + 1 :] if line.startswith("| ")]


def _widths(output: str) -> set[int]:
    """逐行计算显示宽度。

    故意不复用 aurora.utils.table 里的实现：框线是否真的等宽必须独立验证，
    否则实现算错时测试会跟着一起错。
    """
    return {_cell_width(line) for line in output.splitlines()}


def _cell_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(char) in _FULLWIDTH else 1 for char in text)


def test_help_lists_the_three_subcommands(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        run(["app", "--help"], registry=DEFAULT_REGISTRY)

    assert exit_info.value.code == 0
    usage = " ".join(capsys.readouterr().out.split())
    for subcommand in ("list", "enable", "disable"):
        assert subcommand in usage


def test_list_renders_one_row_per_registered_app(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _project(
        tmp_path,
        _stdio("com.example.ready", "extensions/apps/example/ready", enabled=True)
        + "\n"
        + _stdio("com.example.missing", "extensions/apps/example/missing")
        + "\n"
        + _stdio("com.example.bad", "../../outside"),
    )
    (root / "extensions" / "apps" / "example" / "ready").mkdir(parents=True)

    assert _cli(root, "list") == EXIT_FAILURE
    output = capsys.readouterr().out

    assert _header_row(output) == _HEADERS
    assert _data_rows(output) == [
        ["com.example.ready", "yes", "stdio", "ready", "extensions/apps/example/ready"],
        ["com.example.missing", "no", "stdio", "missing", "extensions/apps/example/missing"],
        ["com.example.bad", "no", "stdio", "invalid", "../../outside"],
    ]


def test_list_exits_zero_when_everything_is_ready(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _project(
        tmp_path,
        _stdio("com.example.ready", "extensions/apps/example/ready")
        + "\n"
        + '[[app]]\npackage = "com.example.remote"\nenabled = false\ntransport = "streamable_http"\n'
        'url = "https://example.com/mcp"\ntimeout_seconds = 60\n',
    )
    (root / "extensions" / "apps" / "example" / "ready").mkdir(parents=True)

    assert _cli(root, "list") == 0
    assert _data_rows(capsys.readouterr().out)[1][4] == "-"


def test_list_reports_an_empty_registry(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _project(tmp_path, "app = []\n")

    assert _cli(root, "list") == 0
    assert "没有注册任何 App" in capsys.readouterr().out


def test_every_frame_line_renders_to_the_same_width(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """框线的全部意义就是每行等宽；宽度算错会让边框断开。"""
    root = _project(
        tmp_path,
        _stdio("com.example.ready", "extensions/apps/example/ready")
        + "\n"
        + _stdio("com.example.bad", "../../outside"),
    )
    (root / "extensions" / "apps" / "example" / "ready").mkdir(parents=True)

    assert _cli(root, "list") == EXIT_FAILURE
    output = capsys.readouterr().out

    assert len(_widths(output)) == 1
    lines = output.splitlines()
    # 顶部边框、banner、边框、表头、|====| 分隔行，随后才是数据。
    assert lines[0].startswith("+-") and lines[2].startswith("+-")
    assert lines[1].startswith("| ") and _CONFIG in lines[1]
    assert _header_row(output) == _HEADERS
    assert lines[4].startswith(_SEPARATOR_PREFIX)


def test_a_cjk_path_keeps_the_frame_aligned(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """中文路径按两列宽计算；用 len() 会让这一行的框线错位。"""
    root = _project(tmp_path, _stdio("com.example.weather", "extensions/apps/天气"))
    (root / "extensions" / "apps" / "天气").mkdir(parents=True)

    assert _cli(root, "list") == 0
    output = capsys.readouterr().out

    assert len(_widths(output)) == 1
    assert _data_rows(output)[0] == ["com.example.weather", "no", "stdio", "ready", "extensions/apps/天气"]


def test_json_output_is_the_only_thing_on_stdout(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _project(
        tmp_path,
        _stdio("com.example.ready", "extensions/apps/example/ready")
        + "\n"
        + '[[app]]\npackage = "com.example.remote"\nenabled = true\ntransport = "streamable_http"\n'
        'url = "https://example.com/mcp"\ntimeout_seconds = 60\n',
    )
    (root / "extensions" / "apps" / "example" / "ready").mkdir(parents=True)

    assert _cli(root, "list", "--json") == 0

    assert json.loads(capsys.readouterr().out) == [
        {
            "package": "com.example.ready",
            "enabled": False,
            "transport": "stdio",
            "state": "ready",
            "path": "extensions/apps/example/ready",
        },
        {
            "package": "com.example.remote",
            "enabled": True,
            "transport": "streamable_http",
            "state": "ready",
            "path": None,
        },
    ]


def test_json_and_table_render_the_same_facts(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _project(
        tmp_path,
        _stdio("com.example.ready", "extensions/apps/example/ready")
        + "\n"
        + _stdio("com.example.missing", "extensions/apps/example/missing")
        + "\n"
        + _stdio("com.example.bad", "../../outside"),
    )
    (root / "extensions" / "apps" / "example" / "ready").mkdir(parents=True)

    _cli(root, "list")
    table = _data_rows(capsys.readouterr().out)
    _cli(root, "list", "--json")
    payload = json.loads(capsys.readouterr().out)

    assert [[item["package"], item["state"], item["path"] or "-"] for item in payload] == [
        [row[0], row[3], row[4]] for row in table
    ]


def test_enable_flips_only_the_enabled_field(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _project(tmp_path, _stdio("com.example.weather", "extensions/apps/example/weather"))
    before = (root / _CONFIG).read_text(encoding="utf-8")

    assert _cli(root, "enable", "com.example.weather") == 0

    assert "已启用 com.example.weather" in capsys.readouterr().out
    after = (root / _CONFIG).read_text(encoding="utf-8")
    assert after == before.replace("enabled = false", "enabled = true")


def test_disable_flips_only_the_enabled_field(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _project(tmp_path, _stdio("com.example.weather", "extensions/apps/example/weather", enabled=True))

    assert _cli(root, "disable", "com.example.weather") == 0

    assert "已禁用 com.example.weather" in capsys.readouterr().out
    assert "enabled = false" in (root / _CONFIG).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (("enable", "com.example.weather"), "已经是启用状态"),
        (("disable", "com.example.weather"), "已经是禁用状态"),
    ],
)
def test_repeating_a_toggle_reports_without_rewriting(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], arguments: tuple[str, ...], expected: str
) -> None:
    root = _project(tmp_path, _stdio("com.example.weather", "extensions/apps/example/weather"))
    if arguments[0] == "enable":
        _cli(root, "enable", "com.example.weather")
        capsys.readouterr()

    path = root / _CONFIG
    before = path.read_text(encoding="utf-8")

    assert _cli(root, *arguments) == 0

    assert expected in capsys.readouterr().out
    assert path.read_text(encoding="utf-8") == before
