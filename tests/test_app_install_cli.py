"""``aurora app install <repo>`` 的命令装配、清单准入、计划展示、确认与退出码。

参数解析、``execute`` 的错误通道与渲染都走真实代码；只有两条对外出口（GitHub 与
Git）换成替身，所以这个文件不发请求、不起子进程、不连接 MCP。

``--npx`` / ``--uvx`` 是同一个子命令的另一条路径，它不读清单、不克隆，所以那些
用例在 ``test_app_runner_cli.py``。
"""

from __future__ import annotations

import io
import sys
from typing import TYPE_CHECKING

import pytest
from app_clone_support import CONFLICTING_PACKAGE, apps_root_entries, registry_entry, repository
from app_install_support import DEFAULT_PROTOCOL, WEATHER_COMMAND, FakeMcpClientFactory, stub_cli

from aurora.commander import run
from aurora.commands import DEFAULT_REGISTRY
from aurora.commands.app.models import DiscoveryError, RegistryWriteError
from aurora.commands.app.store import AppStore
from aurora.commands.app.verify import MCPVerifier
from aurora.utils.process import EXIT_CONFIG_ERROR, EXIT_FAILURE, EXIT_INTERRUPTED

if TYPE_CHECKING:
    from pathlib import Path

_EMPTY_REGISTRY = "app = []\n"
_PACKAGE = "github.churk-ben.aurora-qq"
_APP_PATH = "extensions/apps/Churk-Ben/Aurora-QQ"
_CONFIG = "config/apps.toml"
_REQUESTED = "churk-ben/aurora-qq"
_COMMAND_JSON = '["node","./server.js"]'
# 计划里 Install path 一次、注册表条目的 working_dir 一次。
_PLAN_PATH_OCCURRENCES = 2


def _project(tmp_path: Path, apps_toml: str = _EMPTY_REGISTRY) -> Path:
    config = tmp_path / "config"
    config.mkdir(parents=True, exist_ok=True)
    (config / "apps.toml").write_text(apps_toml, encoding="utf-8")
    return tmp_path


def _cli(root: Path, *arguments: str) -> int:
    return run(["--root", str(root), "app", *arguments], registry=DEFAULT_REGISTRY)


def _capture(capsys: pytest.CaptureFixture[str], root: Path, *arguments: str) -> tuple[int, str, str]:
    code = _cli(root, *arguments)
    streams = capsys.readouterr()
    return code, streams.out, streams.err


def _verifier() -> MCPVerifier:
    return MCPVerifier(FakeMcpClientFactory(protocol_version=DEFAULT_PROTOCOL))  # type: ignore[arg-type]


class _Terminal(io.StringIO):
    """一个自称是终端的 stdin，里面放着用户将要敲的那一行。

    用真的 ``input()`` 而不是替掉 ``_confirmed``：提问、认答案、处理 EOF 都是
    被测行为的一部分，把整段换掉只能测到「调用方是否调了它」。
    """

    def isatty(self) -> bool:
        return True


def _pipe(monkeypatch: pytest.MonkeyPatch) -> None:
    """把 stdin 换成非终端：管道与 CI 的默认情形。"""
    monkeypatch.setattr(sys, "stdin", io.StringIO())


def _terminal(monkeypatch: pytest.MonkeyPatch, answer: str = "n") -> None:
    """把 stdin 换成终端，并预置用户敲下的一行（空串就是直接回车）。"""
    monkeypatch.setattr(sys, "stdin", _Terminal(f"{answer}\n"))


def _closed_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    """把 stdin 换成读到 EOF 的终端：用户没回答就断开了。"""
    monkeypatch.setattr(sys, "stdin", _Terminal(""))


def _failing_write(*_args: object, **_kwargs: object) -> None:
    raise RegistryWriteError("无法写入 apps.toml：磁盘满了")


# --- 命令注册 -----------------------------------------------------------------


def test_help_lists_every_subcommand(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        run(["app", "--help"], registry=DEFAULT_REGISTRY)

    assert exit_info.value.code == 0
    usage = " ".join(capsys.readouterr().out.split())
    for subcommand in ("install", "remove", "list"):
        assert subcommand in usage
    assert "probe" not in usage


def test_install_help_lists_its_options(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        run(["app", "install", "--help"], registry=DEFAULT_REGISTRY)

    assert exit_info.value.code == 0
    usage = " ".join(capsys.readouterr().out.split())
    for option in (
        "--ref",
        "--package",
        "--command",
        "--npx",
        "--uvx",
        "--arg",
        "--auth-env",
        "--disabled",
        "--yes",
    ):
        assert option in usage
    assert "--no-check" not in usage


def test_install_without_a_target_says_what_it_wants(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """仓库与包管理器二者必居其一，argparse 表达不了「恰好选一种」。"""
    stub_cli(monkeypatch)

    code, _, err = _capture(capsys, _project(tmp_path), "install")

    assert code == EXIT_CONFIG_ERROR
    assert "--npx" in err and "--uvx" in err


# --- 计划展示 -----------------------------------------------------------------


def test_the_plan_shows_every_fact_before_confirming(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stub_cli(monkeypatch)
    root = _project(tmp_path)

    _, out, _ = _capture(capsys, root, "install", _REQUESTED, "--yes")

    for label in ("Repository:", "Ref:", "Commit:", "Package:", "Runtime:", "Command:", "Command from:"):
        assert label in out
    assert "Verification:  pending" in out, "检查是默认动作，计划里要先说它会发生"
    assert "Install path:" in out
    assert out.count(_APP_PATH) >= _PLAN_PATH_OCCURRENCES, "计划里既要有 Install path，也要有注册表条目的 working_dir"


def test_the_plan_names_the_command_it_will_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stub_cli(monkeypatch)

    _, out, _ = _capture(capsys, _project(tmp_path), "install", _REQUESTED, "--yes")

    assert " ".join(WEATHER_COMMAND) in out


def test_the_plan_says_where_the_command_came_from(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """出处只有两种：仓库自己的声明，或用户显式给的命令。"""
    stub_cli(monkeypatch)

    _, out, _ = _capture(capsys, _project(tmp_path), "install", _REQUESTED, "--yes")

    assert "aurora-app.toml" in out


def test_the_plan_renders_the_exact_registry_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """展示的那段 TOML 就是将要写进文件的那一段，连表头都一样。"""
    stub_cli(monkeypatch)
    root = _project(tmp_path)

    _, out, _ = _capture(capsys, root, "install", _REQUESTED, "--yes")

    assert "[[app]]" in out
    assert f'package = "{_PACKAGE}"' in out
    assert "enabled = true" in out, "默认启用：安装的目的就是下次 aurora start 能用它"
    assert 'transport = "stdio"' in out
    assert "env = []" in out
    assert "agents = " not in out, "没有授权就不写这个键"


def test_the_displayed_entry_is_what_lands_in_the_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """展示与落盘同源：把计划里的每一行拿去注册表里找，必须都找得到。"""
    stub_cli(monkeypatch)
    root = _project(tmp_path)

    _, out, _ = _capture(capsys, root, "install", _REQUESTED, "--yes")

    displayed = [line.strip() for line in out.splitlines() if " = " in line]
    written = (root / _CONFIG).read_text(encoding="utf-8")
    assert displayed, "计划里应该有注册表条目"
    for line in displayed:
        assert line in written, f"计划展示了注册表里没有的 {line!r}"


def test_disabled_shows_enabled_false_in_the_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stub_cli(monkeypatch)

    _, out, _ = _capture(capsys, _project(tmp_path), "install", _REQUESTED, "--disabled", "--yes")

    assert "enabled = false" in out


def test_install_does_not_request_or_write_an_agent_grant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """安装只登记 Server；Agent 的工具可见性由项目级规则决定。"""
    stub_cli(monkeypatch)
    root = _project(tmp_path)

    _, out, _ = _capture(capsys, root, "install", _REQUESTED, "--yes")

    assert "Agents:" not in out
    assert "agents = " not in (root / _CONFIG).read_text(encoding="utf-8")


# --- GitHub 页面上的写法 ---------------------------------------------------------


@pytest.mark.parametrize(
    "argument",
    [
        _REQUESTED,
        f"gh repo clone {_REQUESTED}",
        f"https://github.com/{_REQUESTED}.git",
        f"git@github.com:{_REQUESTED}.git",
        f"ssh://git@github.com/{_REQUESTED}",
    ],
)
def test_anything_pasteable_from_github_installs_the_same_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], argument: str
) -> None:
    """绿色按钮给的三种写法直接粘进来就能装：归一化之后一切照旧。"""
    source, _ = stub_cli(monkeypatch)
    root = _project(tmp_path)

    code, out, _ = _capture(capsys, root, "install", argument, "--yes")

    assert code == 0
    assert f"已安装 {_PACKAGE}。" in out
    assert source.calls == [_REQUESTED], "发出去的必须是归一化后的 owner/repo"


def test_a_remote_url_uses_mcp_connect_without_github_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source, _ = stub_cli(monkeypatch)
    root = _project(tmp_path)

    code, out, _ = _capture(capsys, root, "install", "https://mcp.example.com/rpc", "--yes")

    assert code == 0
    assert "remote.mcp.example.com.rpc" in out
    assert 'url = "https://mcp.example.com/rpc"' in (root / _CONFIG).read_text(encoding="utf-8")
    assert source.calls == [], "远程 MCP 不访问 GitHub"


# --- 清单准入 -----------------------------------------------------------------


def test_a_repository_without_a_manifest_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Aurora 不替仓库猜怎么启动它：没有清单就没有可执行的计划。"""
    stub_cli(monkeypatch, manifest=None)
    root = _project(tmp_path)

    code, out, err = _capture(capsys, root, "install", _REQUESTED, "--yes")

    assert code == EXIT_CONFIG_ERROR
    assert "aurora-app.toml" in err
    assert "Repository:" not in out, "没有计划可展示，就不该先展示一张再拒绝"
    assert not (root / _APP_PATH).exists()
    assert apps_root_entries(root) == []


def test_a_rejected_repository_is_never_cloned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """n8n 那种整平台仓库一旦克隆下来，用户已经付了整库下载的成本。"""
    _, cloner = stub_cli(monkeypatch, manifest=None)

    _capture(capsys, _project(tmp_path), "install", _REQUESTED, "--yes")

    assert cloner.calls == []


def test_the_missing_manifest_message_offers_the_escape_hatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stub_cli(monkeypatch, manifest=None)

    _, _, err = _capture(capsys, _project(tmp_path), "install", _REQUESTED, "--yes")

    assert "--command" in err
    assert "远程 MCP" in err


def test_an_explicit_command_installs_a_repository_without_a_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """用户接管了「怎么启动」的判断，这就是清单规则留的那个出口。"""
    stub_cli(monkeypatch, manifest=None)
    root = _project(tmp_path)

    code, out, _ = _capture(capsys, root, "install", _REQUESTED, "--command", _COMMAND_JSON, "--yes")

    assert code == 0
    assert f"已安装 {_PACKAGE}。" in out
    assert 'command = ["node", "./server.js"]' in (root / _CONFIG).read_text(encoding="utf-8")


def test_a_broken_manifest_is_rejected_like_a_missing_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stub_cli(monkeypatch, manifest="[server\ncommand = ")

    code, _, err = _capture(capsys, _project(tmp_path), "install", _REQUESTED, "--yes")

    assert code == EXIT_CONFIG_ERROR
    assert "aurora-app.toml" in err


# --- 成功之后 -----------------------------------------------------------------


def test_a_successful_install_reports_the_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stub_cli(monkeypatch)
    root = _project(tmp_path)

    code, out, _ = _capture(capsys, root, "install", _REQUESTED, "--yes")

    assert code == 0
    assert f"已安装 {_PACKAGE}。" in out
    assert (root / _APP_PATH).is_dir()


def test_a_disabled_install_tells_the_user_how_to_enable_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stub_cli(monkeypatch)

    _, out, _ = _capture(capsys, _project(tmp_path), "install", _REQUESTED, "--disabled", "--yes")

    assert "该 App 处于禁用状态" in out
    assert f"aurora app enable {_PACKAGE}" in out


def test_an_enabled_install_does_not_mention_disabling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stub_cli(monkeypatch)

    _, out, _ = _capture(capsys, _project(tmp_path), "install", _REQUESTED, "--yes")

    assert "该 App 处于禁用状态" not in out


def test_a_checked_install_reports_the_tools_it_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stub_cli(monkeypatch, verifier=_verifier())

    _, out, _ = _capture(capsys, _project(tmp_path), "install", _REQUESTED, "--yes")

    assert "发现的工具：   1 个" in out
    assert f"aur.mcp.{_PACKAGE}.weather_now" in out
    assert "未经过连接检查" not in out


def test_install_explains_that_bot_visibility_depends_on_project_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """「登记了」与「Bot 看得见」是两件事，输出不能让前者冒充后者。"""
    stub_cli(monkeypatch)

    _, out, _ = _capture(capsys, _project(tmp_path), "install", _REQUESTED, "--yes")

    assert "Bot 能否调用取决于现有 Agent 的工具可见配置" in out
    assert "agents = " not in out


# --- 取消与非交互 ---------------------------------------------------------------


def test_yes_still_prints_the_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """--yes 只跳过提问，不跳过展示：用户必须能看到将要发生什么。"""
    stub_cli(monkeypatch)
    root = _project(tmp_path)
    _pipe(monkeypatch)

    code, out, _ = _capture(capsys, root, "install", _REQUESTED, "--yes")

    assert code == 0
    assert "Repository:" in out


def test_a_refused_confirmation_installs_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stub_cli(monkeypatch)
    root = _project(tmp_path)
    _terminal(monkeypatch, "n")

    code, out, _ = _capture(capsys, root, "install", _REQUESTED)

    assert code == EXIT_INTERRUPTED, "用户主动放弃不是失败，不该按失败计数"
    assert "已取消" in out
    assert not (root / _APP_PATH).exists()
    assert (root / _CONFIG).read_text(encoding="utf-8") == _EMPTY_REGISTRY


def test_a_refused_confirmation_leaves_no_staging_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """清单准入之后 clone 已经发生了，放弃时必须把它撤干净。"""
    stub_cli(monkeypatch)
    root = _project(tmp_path)
    _terminal(monkeypatch, "n")

    _capture(capsys, root, "install", _REQUESTED)

    assert apps_root_entries(root) == []


@pytest.mark.parametrize("answer", ["", "y", "Y", "yes"])
def test_an_affirmative_answer_installs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], answer: str
) -> None:
    """空回车即同意，与提示符里的大写 Y 一致。"""
    stub_cli(monkeypatch)
    root = _project(tmp_path)
    _terminal(monkeypatch, answer)

    code, _, _ = _capture(capsys, root, "install", _REQUESTED)

    assert code == 0
    assert (root / _APP_PATH).is_dir()


@pytest.mark.parametrize("answer", ["n", "N", "no", "等等", "1"])
def test_everything_else_is_a_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], answer: str
) -> None:
    """只有白名单里的答案才算同意：看不懂的回答绝不能变成一次安装。"""
    stub_cli(monkeypatch)
    root = _project(tmp_path)
    _terminal(monkeypatch, answer)

    code, _, _ = _capture(capsys, root, "install", _REQUESTED)

    assert code == EXIT_INTERRUPTED
    assert not (root / _APP_PATH).exists()


def test_a_terminal_that_closes_is_a_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """EOF 意味着没有答案，没有答案不是同意。"""
    stub_cli(monkeypatch)
    root = _project(tmp_path)
    _closed_terminal(monkeypatch)

    code, _, _ = _capture(capsys, root, "install", _REQUESTED)

    assert code == EXIT_INTERRUPTED
    assert not (root / _APP_PATH).exists()


def test_the_plan_is_shown_before_the_question(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stub_cli(monkeypatch)
    root = _project(tmp_path)
    _terminal(monkeypatch, "n")

    _, out, _ = _capture(capsys, root, "install", _REQUESTED)

    assert "Repository:" in out
    assert "Continue? [Y/n] " in out
    assert out.index("Repository:") < out.index("Continue?"), "先给事实，再问要不要继续"


def test_a_non_interactive_stdin_without_yes_is_a_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """不能在管道或 CI 里等一个永远不会来的回车。"""
    stub_cli(monkeypatch)
    root = _project(tmp_path)
    _pipe(monkeypatch)

    code, _, err = _capture(capsys, root, "install", _REQUESTED)

    assert code == EXIT_CONFIG_ERROR
    assert "--yes" in err
    assert not (root / _APP_PATH).exists()


def test_the_plan_is_still_shown_before_the_non_interactive_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stub_cli(monkeypatch)
    root = _project(tmp_path)
    _pipe(monkeypatch)

    _, out, _ = _capture(capsys, root, "install", _REQUESTED)

    assert "Repository:" in out


# --- 失败与退出码 ---------------------------------------------------------------


def test_a_missing_registry_points_at_aurora_setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """注册表是 aurora setup 生成的个人配置，install 不凭空造一个。"""
    stub_cli(monkeypatch)

    code, _, err = _capture(capsys, tmp_path, "install", _REQUESTED, "--yes")

    assert code == EXIT_CONFIG_ERROR
    assert "aurora setup" in err
    assert "App 配置错误" in err
    assert not (tmp_path / "config").exists(), "拒绝时不创建任何东西"


def test_a_missing_registry_is_detected_before_the_clone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """等到提交时才发现，用户就白等了一整次 clone。"""
    _, cloner = stub_cli(monkeypatch)

    _capture(capsys, tmp_path, "install", _REQUESTED, "--yes")

    assert cloner.calls == []


def test_a_duplicate_package_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stub_cli(monkeypatch)
    root = _project(tmp_path, registry_entry(CONFLICTING_PACKAGE, "extensions/apps/x/y"))

    code, _, err = _capture(capsys, root, "install", _REQUESTED, "--package", CONFLICTING_PACKAGE, "--yes")

    assert code == EXIT_CONFIG_ERROR
    assert CONFLICTING_PACKAGE in err


def test_a_disabled_repository_is_a_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stub_cli(monkeypatch, result=repository(disabled=True))

    code, _, err = _capture(capsys, _project(tmp_path), "install", _REQUESTED, "--yes")

    assert code == EXIT_CONFIG_ERROR
    assert "已禁用" in err


def test_an_archived_repository_is_a_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stub_cli(monkeypatch, result=repository(archived=True))

    code, _, err = _capture(capsys, _project(tmp_path), "install", _REQUESTED, "--yes")

    assert code == EXIT_CONFIG_ERROR
    assert "已归档" in err


def test_a_malformed_repository_name_is_rejected_before_any_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source, _ = stub_cli(monkeypatch)

    code, _, err = _capture(capsys, _project(tmp_path), "install", "not-a-full-name", "--yes")

    assert code == EXIT_CONFIG_ERROR
    assert "App 配置错误" in err
    assert source.calls == [], "参数形状的问题不该先发一次请求"


def test_a_github_failure_under_install_keeps_the_discovery_label(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """错误标签跟着异常类型走，不跟着子命令走。"""
    stub_cli(monkeypatch, failure=DiscoveryError("GitHub 请求失败"))

    code, _, err = _capture(capsys, _project(tmp_path), "install", _REQUESTED, "--yes")

    assert code == EXIT_FAILURE
    assert "App 搜索失败" in err


def test_a_registry_write_failure_rolls_the_directory_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stub_cli(monkeypatch)
    root = _project(tmp_path)
    monkeypatch.setattr(AppStore, "add_app", _failing_write)

    code, _, err = _capture(capsys, root, "install", _REQUESTED, "--yes")

    assert code == EXIT_FAILURE
    assert "App 操作失败" in err
    assert not (root / _APP_PATH).exists()
    assert (root / _CONFIG).read_text(encoding="utf-8") == _EMPTY_REGISTRY
