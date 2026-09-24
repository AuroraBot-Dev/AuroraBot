"""``aurora-app.toml`` 的解析与校验：契约本身长什么样、不合规时说什么。

纯文本进、``Manifest`` 出。本文件不读磁盘、不发请求、不 clone —— 清单从哪里来
由调用方决定，这一层只回答「这份内容能不能当契约用」。
"""

from __future__ import annotations

import pytest
from app_install_support import manifest_text

from aurora.commands.app.manifest import (
    MANIFEST_NAME,
    Manifest,
    check_manifest_command,
    manifest_source,
    missing_manifest,
    parse_manifest,
    unusable_manifest,
)
from aurora.commands.app.models import ManifestError, PlanError

_SOURCE = "example/weather-mcp"
_COMMAND = ("uv", "run", "weather-mcp")


def _parse(content: str, *, source: str = _SOURCE) -> Manifest:
    return parse_manifest(content, source=source)


# --- 合规的清单 ---------------------------------------------------------------


def test_a_minimal_manifest_yields_its_command() -> None:
    manifest = _parse(manifest_text(_COMMAND))

    assert manifest.command == _COMMAND


def test_the_command_keeps_every_argument_verbatim() -> None:
    """清单声明的就是仓库作者要执行的，Aurora 不在这里做任何加工。"""
    command = ("uv", "run", "--frozen", "--extra", "server", "weather-mcp")

    assert _parse(manifest_text(command)).command == command


def test_a_relative_executable_inside_the_repository_is_allowed() -> None:
    """仓库里自带的脚本是合法的入口：``./server`` 按 working_dir 解析。"""
    assert _parse(manifest_text(("./bin/server", "--port", "0"))).command == ("./bin/server", "--port", "0")


# --- 顶层结构 -----------------------------------------------------------------


def test_a_missing_version_is_rejected() -> None:
    with pytest.raises(ManifestError) as error_info:
        _parse('[server]\ncommand = ["uv"]\n')

    assert "manifest_version = 1" in str(error_info.value)


def test_an_unknown_version_is_rejected() -> None:
    """v2 的清单可能声明了 v1 实现不了的字段，装作读懂了比拒绝更危险。"""
    with pytest.raises(ManifestError):
        _parse(manifest_text(_COMMAND, version=2))


def test_a_boolean_is_not_a_version() -> None:
    """``True == 1``：少了显式的 bool 判断，``manifest_version = true`` 会被放行。"""
    with pytest.raises(ManifestError):
        _parse('manifest_version = true\n\n[server]\ncommand = ["uv"]\n')


def test_a_missing_server_table_is_rejected() -> None:
    with pytest.raises(ManifestError) as error_info:
        _parse("manifest_version = 1\n")

    assert "[server]" in str(error_info.value)


def test_an_unknown_top_level_field_is_rejected() -> None:
    """清单是契约：多写一个 Aurora 不认识的键，多半是作者以为它生效了。"""
    with pytest.raises(ManifestError) as error_info:
        _parse(manifest_text(_COMMAND, extra="\n[install]\nprepare = []\n"))

    assert "install" in str(error_info.value)


@pytest.mark.parametrize("field", ["prepare", "install", "dependencies", "runtime"])
def test_an_unknown_server_field_is_rejected(field: str) -> None:
    """``[server]`` 只回答「怎么启动」；前置准备是 Aurora 兑现不了的承诺。"""
    with pytest.raises(ManifestError) as error_info:
        _parse(f'manifest_version = 1\n\n[server]\ncommand = ["uv"]\n{field} = []\n')

    assert field in str(error_info.value)


def test_broken_toml_is_rejected_with_the_parser_message() -> None:
    with pytest.raises(ManifestError) as error_info:
        _parse("[server\ncommand = ")

    assert "无法解析" in str(error_info.value)


def test_a_rejected_manifest_is_a_plan_error() -> None:
    """退出码 2 那一档：重试或换个时间都不会变，是用户输入的问题。"""
    with pytest.raises(PlanError):
        _parse("manifest_version = 1\n")


# --- [server].command ---------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "fragment"),
    [
        ('command = "uv run weather-mcp"', "aurora-app.toml 的 [server].command 必须是字符串数组"),
        ('command = ["uv", 123]', "aurora-app.toml 的 [server].command 必须是字符串数组"),
        # 类型对了但内容为空：错误发生在 argv 校验那一步，那里只有 ``[server].command``
        # 这个位置可指，因为同一段代码也给用户的 --command 报错。
        ("command = []", "[server].command 必须是非空的字符串数组"),
        ('command = { executable = "uv" }', "aurora-app.toml 的 [server].command 必须是字符串数组"),
    ],
)
def test_a_malformed_command_is_rejected(value: str, fragment: str) -> None:
    """报错必须同时说清「哪个仓库」与「哪一处」：清单是用户刚写的那几行，改哪里要指得到。"""
    with pytest.raises(ManifestError) as error_info:
        _parse(f"manifest_version = 1\n\n[server]\n{value}\n")

    message = str(error_info.value)
    assert fragment in message
    assert "example/weather-mcp" in message


def test_a_blank_first_item_is_rejected() -> None:
    with pytest.raises(ManifestError):
        check_manifest_command(("", "run"), source=_SOURCE)


@pytest.mark.parametrize("command", [(" uv", "run"), ("uv", "run "), ("uv", " run")])
def test_surrounding_whitespace_is_not_silently_trimmed(command: tuple[str, ...]) -> None:
    """首尾空白几乎总是笔误；替作者修好它，等于让他永远不知道自己写错了。"""
    with pytest.raises(ManifestError) as error_info:
        check_manifest_command(command, source=_SOURCE)

    assert "首尾空白" in str(error_info.value)


@pytest.mark.parametrize("executable", ["/usr/bin/node", "../node", "./../../node", "../../x"])
def test_an_executable_outside_the_repository_is_rejected(executable: str) -> None:
    """``./...`` 按 working_dir 解析，越出仓库就等于去执行别人的机器上的东西。"""
    with pytest.raises(ManifestError) as error_info:
        check_manifest_command((executable, "./server.js"), source=_SOURCE)

    assert "仓库内" in str(error_info.value)


def test_a_bare_executable_name_is_left_to_path_lookup() -> None:
    """不带路径分隔符的名字由 PATH 解析，这是「调用 uv」而不是「调用某个文件」。"""
    assert check_manifest_command(("uv", "run", "x"), source=_SOURCE) == ("uv", "run", "x")


# --- 出处与两种失败说法 -------------------------------------------------------


def test_manifest_source_names_owner_repo() -> None:
    assert manifest_source(_SOURCE, None) == _SOURCE


def test_manifest_source_includes_the_ref_when_one_was_asked_for() -> None:
    """从 tag 读到的清单不能和从默认分支读到的那一份混为一谈。"""
    assert manifest_source(_SOURCE, "v1.2.0") == f"{_SOURCE}@v1.2.0"


def test_the_missing_manifest_message_offers_both_ways_forward() -> None:
    """没有清单时用户有两个选择：自己给命令，或者转去登记一个已经跑起来的端点。"""
    message = str(missing_manifest(_SOURCE))

    assert MANIFEST_NAME in message
    assert _SOURCE in message
    assert "--command" in message
    assert "远程 MCP" in message


def test_the_unusable_manifest_message_carries_the_detail() -> None:
    message = str(unusable_manifest(_SOURCE, "内容不是 UTF-8 文本"))

    assert "内容不是 UTF-8 文本" in message
    assert MANIFEST_NAME in message
    assert "--command" in message
