"""``aurora app search`` 的结果呈现测试：表格、JSON 与两者的同源性。

这里只管 stdout 长什么样；命令怎么装配、参数怎么转发、退出码怎么定，归
``test_app_search_cli.py``。全部离线：``_github_source`` 被换成预置 source。

表格解析辅助自带一份、不共享：它是「怎么读表格」的测试知识，跟构造用例的辅助
不是一类东西，混进共享模块会让那模块同时管两件事。
"""

from __future__ import annotations

import json
import unicodedata
from typing import TYPE_CHECKING

from app_search_support import captured, page, repository, stub

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

_HEADERS = ["REPOSITORY", "STARS", "STATUS", "UPDATED", "DESCRIPTION"]
_SEPARATOR_PREFIX = "|="
_FULLWIDTH = frozenset(("F", "W"))
_DESCRIPTION_WIDTH = 50


# --- 表格解析 -----------------------------------------------------------------


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip("|").split("|")]


def _separator_index(output: str) -> int:
    return next(index for index, line in enumerate(output.splitlines()) if line.startswith(_SEPARATOR_PREFIX))


def _header_row(output: str) -> list[str]:
    return _cells(output.splitlines()[_separator_index(output) - 1])


def _data_rows(output: str) -> list[list[str]]:
    lines = output.splitlines()
    return [_cells(line) for line in lines[_separator_index(output) + 1 :] if line.startswith("| ")]


def _cell_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(char) in _FULLWIDTH else 1 for char in text)


def _widths(output: str) -> set[int]:
    """只量框线行 —— 表格下方还有一行普通文本的页脚。"""
    return {_cell_width(line) for line in output.splitlines() if line[:1] in ("+", "|")}


# --- 表格渲染 -----------------------------------------------------------------


def test_the_table_renders_the_search_columns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stub(monkeypatch, page((repository(),)))

    code, output, _ = captured(capsys, tmp_path, "search")

    assert code == 0
    assert _header_row(output) == _HEADERS


def test_the_banner_names_the_topic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stub(monkeypatch, page((repository(),)))

    _, output, _ = captured(capsys, tmp_path, "search")

    assert "topic:aurorabot-app" in output.splitlines()[1]


def test_each_row_projects_one_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stub(monkeypatch, page((repository(), repository(full_name="aurora/clock", stars=3, archived=True))))

    _, output, _ = captured(capsys, tmp_path, "search")

    assert _data_rows(output) == [
        ["Churk-Ben/Aurora-QQ", "12", "active", "2026-09-01", "QQ 通知 App"],
        ["aurora/clock", "3", "archived", "2026-09-01", "QQ 通知 App"],
    ]


def test_a_disabled_repository_is_labelled_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stub(monkeypatch, page((repository(disabled=True),)))

    _, output, _ = captured(capsys, tmp_path, "search")

    assert _data_rows(output)[0][2] == "disabled"


def test_missing_description_and_timestamp_render_as_dashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stub(monkeypatch, page((repository(description=None, updated_at=""),)))

    _, output, _ = captured(capsys, tmp_path, "search")

    assert _data_rows(output)[0][3:] == ["-", "-"]


def test_a_long_description_is_truncated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stub(monkeypatch, page((repository(description="x" * 200),)))

    _, output, _ = captured(capsys, tmp_path, "search")

    description = _data_rows(output)[0][4]
    assert len(description) == _DESCRIPTION_WIDTH
    assert description.endswith("…")


def test_a_cjk_description_is_truncated_by_display_width(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """按字符数截断会让中文描述占两倍列宽；这里必须按显示宽度算。"""
    stub(monkeypatch, page((repository(description="描" * 200),)))

    _, output, _ = captured(capsys, tmp_path, "search")

    description = _data_rows(output)[0][4]
    assert _cell_width(description) <= _DESCRIPTION_WIDTH
    assert description.endswith("…")


def test_every_frame_line_renders_to_the_same_width(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stub(monkeypatch, page((repository(), repository(full_name="aurora/clock", description="中文描述" * 20))))

    _, output, _ = captured(capsys, tmp_path, "search")

    assert len(_widths(output)) == 1


def test_the_footer_reports_the_range_and_the_total(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stub(monkeypatch, page((repository(), repository(), repository()), page=2, page_size=20, total_count=100))

    _, output, _ = captured(capsys, tmp_path, "search", "--page", "2")

    assert "显示第 21-23 条，共 100 条。" in output


def test_the_footer_warns_when_the_total_exceeds_the_search_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """GitHub 只暴露前 1000 条：用户看不到第 1001 条，得当场告知。"""
    stub(monkeypatch, page((repository(),), total_count=5000))

    _, output, _ = captured(capsys, tmp_path, "search")

    assert "只暴露前 1000 条" in output


def test_an_empty_result_is_not_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stub(monkeypatch, page())

    code, output, error = captured(capsys, tmp_path, "search")

    assert code == 0
    assert "没有找到带 aurorabot-app topic 的仓库" in output
    assert error == ""


# --- JSON 输出 -----------------------------------------------------------------


def test_json_is_the_only_thing_on_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stub(monkeypatch, page((repository(),)))

    code, output, _ = captured(capsys, tmp_path, "search", "--json")

    assert code == 0
    assert json.loads(output) == {
        "total_count": 1,
        "page": 1,
        "page_size": 20,
        "incomplete_results": False,
        "items": [
            {
                "full_name": "Churk-Ben/Aurora-QQ",
                "owner": "Churk-Ben",
                "name": "Aurora-QQ",
                "description": "QQ 通知 App",
                "stars": 12,
                "topics": ["aurorabot-app"],
                "updated_at": "2026-09-01T12:00:00Z",
                "default_branch": "main",
                "html_url": "https://github.com/Churk-Ben/Aurora-QQ",
                "clone_url": "https://github.com/Churk-Ben/Aurora-QQ.git",
                "archived": False,
                "disabled": False,
                "status": "active",
            }
        ],
    }


def test_json_carries_the_pagination_it_was_asked_for(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """分页信息是「这一页」的属性；脚本据此才知道还有没有下一页。"""
    stub(monkeypatch, page((repository(),), page=3, page_size=5, total_count=1500))

    _, output, _ = captured(capsys, tmp_path, "search", "--json")

    payload = json.loads(output)
    assert (payload["page"], payload["page_size"], payload["total_count"]) == (3, 5, 1500)


def test_json_and_table_render_the_same_repositories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    result = page((repository(), repository(full_name="aurora/clock", archived=True)))
    stub(monkeypatch, result)
    _, table_output, _ = captured(capsys, tmp_path, "search")
    stub(monkeypatch, result)
    _, json_output, _ = captured(capsys, tmp_path, "search", "--json")

    items = json.loads(json_output)["items"]

    assert [[item["full_name"], item["status"]] for item in items] == [
        [row[0], row[2]] for row in _data_rows(table_output)
    ]


def test_incomplete_results_warn_on_stderr_in_table_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """结果不完整仍然可用，所以不动退出码，但要说清可能还有仓库。"""
    stub(monkeypatch, page((repository(),), incomplete_results=True))

    code, _, error = captured(capsys, tmp_path, "search")

    assert code == 0
    assert "搜索结果不完整" in error


def test_incomplete_results_are_visible_to_scripts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """stderr 不是给机器的接口：这个信号必须在 JSON 里，否则脚本永远读不到。"""
    stub(monkeypatch, page((repository(),), incomplete_results=True))

    _, output, error = captured(capsys, tmp_path, "search", "--json")

    assert json.loads(output)["incomplete_results"] is True
    assert error == ""


def test_a_complete_result_is_silent_on_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stub(monkeypatch, page((repository(),)))

    _, _, error = captured(capsys, tmp_path, "search")

    assert error == ""
