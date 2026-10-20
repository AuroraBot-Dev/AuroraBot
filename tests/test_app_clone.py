"""Git 边界：准入、URL 交叉校验、配置隔离、argv、超时与 staging 清理。

全部离线：``FakeProcessRunner`` 返回预置结果；只有 ``CapturedProcessRunner`` 的
用例会真的起子进程，起的也是当前解释器自己，不需要 git、uv、npm 或 Node。
仓库简名和三种 GitHub 地址写法归一到同一身份，禁用与归档保留各自的拒绝原因。
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from aurora.commands.app.clone import (
    GIT_CLONE_TIMEOUT_SECONDS,
    STAGE_PREFIX,
    CapturedProcessRunner,
    GitRepositoryCloner,
    ProcessResult,
    check_clone_url,
    check_commit,
    check_repository_name,
    isolated_git_environment,
    normalize_repository_input,
    staging_directory,
)
from aurora.commands.app.install import check_admission, install_root
from aurora.commands.app.models import CloneError, PlanError
from tests.app_clone_support import DEFAULT_COMMIT, FakeProcessRunner, apps_root_entries, cloning_runner, repository

if TYPE_CHECKING:
    from collections.abc import Mapping


_CLONE_TARGET = ["clone", "--depth", "1"]
_BRANCH_TARGET = ["--branch", "v1.2.0", "--single-branch"]
_BAD_URLS = [
    "http://github.com/example/weather-mcp.git",
    "https://gitlab.com/example/weather-mcp.git",
    "https://user@github.com/example/weather-mcp.git",
    "https://user:pass@github.com/example/weather-mcp.git",
    "https://github.com/example/weather-mcp.git?ref=main",
    "https://github.com/example/weather-mcp.git#fragment",
    "https://github.com:8443/example/weather-mcp.git",
    "https://github.com/evil/other.git",
    "https://github.com/example/weather-mcp/extra.git",
]
_BAD_NAMES = [
    "weather-mcp",
    "example/foo/bar",
    "/example/repo",
    "example/",
    "/",
    "",
    " example/repo",
    "example/repo ",
    "../repo",
]
_REMOTE_URL = "https://github.com/Churk-Ben/Aurora-QQ.git"
_TOKEN = "ghp_SECRETTOKEN123"
_EXIT_UNKNOWN = 3
_EXIT_BAD_REVISION = 128
_REJECTION_REASONS = {"archived": "已归档", "disabled": "已禁用"}
_PROBE_TIMEOUT_SECONDS = 1.0
_RUNNER_TIMEOUT_SECONDS = 30.0
_SLEEP_FOREVER = "import time; time.sleep(30)"


def _environment_of(runner: FakeProcessRunner, index: int = 0) -> Mapping[str, str]:
    return runner.environment(index)


@pytest.mark.parametrize("value", ["example/weather-mcp", "Churk-Ben/Aurora-QQ", "a/b"])
def test_valid_repository_names_are_returned_unchanged(value: str) -> None:
    assert check_repository_name(value) == value


@pytest.mark.parametrize("value", _BAD_NAMES)
def test_invalid_repository_names_are_rejected(value: str) -> None:
    with pytest.raises(CloneError):
        check_repository_name(value)


_ACCEPTED_INPUTS = [
    "example/weather-mcp",
    "example/weather-mcp/",
    "gh repo clone example/weather-mcp",
    "GH REPO CLONE example/weather-mcp",
    "github.com/example/weather-mcp",
    "https://github.com/example/weather-mcp",
    "https://github.com/example/weather-mcp.git",
    "https://github.com/example/weather-mcp.git/",
    "git@github.com:example/weather-mcp",
    "git@github.com:example/weather-mcp.git",
    "ssh://git@github.com/example/weather-mcp.git",
    "  https://github.com/example/weather-mcp  ",
]
_BAD_INPUTS = [
    "https://gitlab.com/example/weather-mcp",
    "https://github.com:8443/example/weather-mcp",
    "https://user@github.com/example/weather-mcp",
    "https://github.com/example/weather-mcp?tab=readme",
    "https://github.com/example/weather-mcp#readme",
    "ssh://root@github.com/example/weather-mcp",
    "git@gitlab.com:example/weather-mcp.git",
    "git://github.com/example/weather-mcp",
    "http://github.com/example/weather-mcp",
]


@pytest.mark.parametrize("value", _ACCEPTED_INPUTS)
def test_every_github_way_of_naming_a_repository_normalises(value: str) -> None:
    assert normalize_repository_input(value) == "example/weather-mcp"


@pytest.mark.parametrize("value", _BAD_INPUTS)
def test_urls_that_are_not_github_are_rejected_with_a_readable_reason(value: str) -> None:
    """看着像 URL 但不是 GitHub 的输入不能落到「仓库全名必须是 owner/repo 两段」上。"""
    with pytest.raises(CloneError) as error_info:
        normalize_repository_input(value)

    message = str(error_info.value)
    assert "owner/repo" in message
    assert "HTTPS" in message


@pytest.mark.parametrize("value", ["not-a-full-name", "a/b/c", "extensions/apps/x", ""])
def test_shapes_that_are_neither_url_nor_gh_form_are_left_alone(value: str) -> None:
    """认不出来就原样交回，由 check_repository_name 报出那句话。"""
    assert normalize_repository_input(value) == value


@pytest.mark.parametrize("clone_url", _BAD_URLS)
def test_clone_url_must_be_this_repository_on_github_over_https(clone_url: str) -> None:
    """只证明「是 github.com 的 URL」不够，必须证明「是这个 Repository 的 URL」。"""
    with pytest.raises(CloneError):
        check_clone_url(clone_url, "example/weather-mcp")


@pytest.mark.parametrize(
    "clone_url",
    ["https://github.com/example/weather-mcp", "https://github.com/example/weather-mcp.git"],
)
def test_clone_url_accepts_the_git_suffix_with_or_without(clone_url: str) -> None:
    assert check_clone_url(clone_url, "example/weather-mcp") == clone_url


@pytest.mark.parametrize("value", [DEFAULT_COMMIT, DEFAULT_COMMIT[:7], DEFAULT_COMMIT.upper()])
def test_valid_commits_are_lowercased(value: str) -> None:
    assert check_commit(f"{value}\n") == value.lower()


@pytest.mark.parametrize("value", ["", "abc123", "z" * 40, "3f2a1c9\nnot-hex"])
def test_invalid_commit_output_is_rejected(value: str) -> None:
    with pytest.raises(CloneError):
        check_commit(value)


def test_admission_returns_canonical_full_name() -> None:
    assert check_admission(repository()) == "Churk-Ben/Aurora-QQ"


@pytest.mark.parametrize("flag", sorted(_REJECTION_REASONS))
def test_admission_rejects_uninstallable_states(flag: str) -> None:
    """archived / disabled 是用户输入的确定性问题，属于 PlanError 而不是发现失败。"""
    uninstallable = repository(archived=True) if flag == "archived" else repository(disabled=True)

    with pytest.raises(PlanError) as failure:
        check_admission(uninstallable)

    assert str(failure.value) == f"仓库 Churk-Ben/Aurora-QQ {_REJECTION_REASONS[flag]}，无法安装"


def test_admission_rejects_clone_url_pointing_elsewhere() -> None:
    with pytest.raises(PlanError) as failure:
        check_admission(repository(clone_url="https://github.com/evil/other.git"))
    assert "不一致" in str(failure.value)


def test_git_environment_isolates_global_and_system_configuration(tmp_path: Path) -> None:
    empty_config = tmp_path / "empty-gitconfig"
    empty_config.write_text("", encoding="utf-8")

    environment = isolated_git_environment({"PATH": "/usr/bin", "GITHUB_TOKEN": _TOKEN}, empty_config)

    assert environment["GIT_CONFIG_GLOBAL"] == str(empty_config)
    assert environment["GIT_CONFIG_NOSYSTEM"] == "1"
    assert environment["PATH"] == "/usr/bin", "基础系统环境必须保留，否则 git 自己都找不到"


def test_git_isolation_uses_a_real_empty_file(tmp_path: Path) -> None:
    """不能用 /dev/null：Windows 上要写 NUL，一个真实的空文件最省事。"""
    runner = cloning_runner()
    with staging_directory(install_root(tmp_path)) as staging:
        GitRepositoryCloner(runner).clone(repository(), staging)
        config = _environment_of(runner)["GIT_CONFIG_GLOBAL"]

        assert Path(config).is_file()
        assert Path(config).stat().st_size == 0


def test_clone_argv_hardens_the_git_boundary(tmp_path: Path) -> None:
    """redirect 与 hooks 两条规则只体现在 argv 上，必须逐项断言。"""
    runner = cloning_runner()
    with staging_directory(install_root(tmp_path)) as staging:
        GitRepositoryCloner(runner).clone(repository(), staging)
        argv = runner.argv()

        assert argv[:2] == ["git", "-c"]
        assert argv[2] == "http.followRedirects=false"
        assert argv[3] == "-c"
        assert argv[4].startswith("core.hooksPath=")
        assert Path(argv[4].removeprefix("core.hooksPath=")).is_dir()
        assert argv[5:8] == _CLONE_TARGET
        assert argv[8:] == ["--", _REMOTE_URL, str(staging.root)]


def test_clone_argv_pins_branch_only_when_ref_is_given(tmp_path: Path) -> None:
    runner = cloning_runner()
    with staging_directory(install_root(tmp_path)) as staging:
        GitRepositoryCloner(runner).clone(repository(), staging, ref="v1.2.0")
        argv = runner.argv()

        assert argv[5:8] == _CLONE_TARGET
        assert argv[8:11] == _BRANCH_TARGET
        assert argv[11:] == ["--", _REMOTE_URL, str(staging.root)]


def test_clone_records_the_head_from_rev_parse(tmp_path: Path) -> None:
    """HEAD 来自 clone 之后实际 checkout 的那一份，不用 GitHub API 的 SHA 代替。"""
    runner = cloning_runner()
    with staging_directory(install_root(tmp_path)) as staging:
        result = GitRepositoryCloner(runner).clone(repository(), staging, ref="v1.2.0")

        assert result.commit == DEFAULT_COMMIT
        assert result.ref == "v1.2.0"
        assert result.path == staging.root
        assert runner.argv(1) == ["git", "-C", str(staging.root), "rev-parse", "HEAD"]


def test_clone_without_ref_reports_the_default_branch(tmp_path: Path) -> None:
    runner = cloning_runner()
    with staging_directory(install_root(tmp_path)) as staging:
        result = GitRepositoryCloner(runner).clone(repository(), staging)

    assert result.ref == "main"


def test_clone_failure_is_a_clone_error_without_environment_details(tmp_path: Path) -> None:
    runner = FakeProcessRunner(ProcessResult(_EXIT_BAD_REVISION, "", "fatal: repository not found"))
    with staging_directory(install_root(tmp_path)) as staging, pytest.raises(CloneError) as failure:
        GitRepositoryCloner(runner).clone(repository(), staging)

    message = str(failure.value)
    assert f"退出码 {_EXIT_BAD_REVISION}" in message
    assert "fatal: repository not found" in message
    for secret in (_TOKEN, "Authorization", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM"):
        assert secret not in message


def test_rev_parse_failure_is_a_clone_error(tmp_path: Path) -> None:
    runner = FakeProcessRunner(ProcessResult(0, "", ""), ProcessResult(_EXIT_BAD_REVISION, "", "fatal: bad revision"))
    with staging_directory(install_root(tmp_path)) as staging, pytest.raises(CloneError) as failure:
        GitRepositoryCloner(runner).clone(repository(), staging)

    assert "无法读取 clone 后的 HEAD" in str(failure.value)


def test_hex_shaped_ref_gets_a_hint_but_is_not_rejected_upfront(tmp_path: Path) -> None:
    """叫 deadbeef 的 branch 完全合法，所以只提示、不预判它的类型。"""
    runner = FakeProcessRunner(ProcessResult(_EXIT_BAD_REVISION, "", "fatal: Remote branch deadbeef not found"))
    with staging_directory(install_root(tmp_path)) as staging, pytest.raises(CloneError) as failure:
        GitRepositoryCloner(runner).clone(repository(), staging, ref="deadbeef")

    assert "--branch" in runner.argv(), "hex 形状的 ref 仍然照常交给 git"
    assert "不支持按 commit 安装" in str(failure.value)


def test_non_hex_ref_failure_has_no_commit_hint(tmp_path: Path) -> None:
    runner = FakeProcessRunner(ProcessResult(_EXIT_BAD_REVISION, "", "fatal: Remote branch nope not found"))
    with staging_directory(install_root(tmp_path)) as staging, pytest.raises(CloneError) as failure:
        GitRepositoryCloner(runner).clone(repository(), staging, ref="nope")

    assert "不支持按 commit 安装" not in str(failure.value)


def test_clone_uses_a_bounded_timeout(tmp_path: Path) -> None:
    """不要无限等待：Git 卡在凭据提示时用户看到的是一个不动的终端。"""
    runner = cloning_runner()
    with staging_directory(install_root(tmp_path)) as staging:
        GitRepositoryCloner(runner).clone(repository(), staging)

    assert runner.calls[0]["timeout"] == GIT_CLONE_TIMEOUT_SECONDS


def test_staging_lives_under_the_apps_root(tmp_path: Path) -> None:
    root = install_root(tmp_path)
    with staging_directory(root) as staging:
        assert staging.root.parent == root
        assert staging.root.name.startswith(STAGE_PREFIX)
        assert staging.root.is_dir()
        assert staging.scratch.is_dir()


def test_staging_is_removed_after_the_block(tmp_path: Path) -> None:
    root = install_root(tmp_path)
    with staging_directory(root) as staging:
        captured = staging.root
        scratch = staging.scratch

    assert not captured.exists()
    assert not scratch.exists()
    assert apps_root_entries(tmp_path) == []


def test_staging_is_removed_when_the_block_raises(tmp_path: Path) -> None:
    """清理做进结构里，任何一条失败路径都不会漏掉。"""
    root = install_root(tmp_path)
    used: list[Path] = []
    with pytest.raises(PlanError), staging_directory(root) as staging:
        used.append(staging.root)
        raise PlanError("计划失败")

    assert used, "staging_directory 没有交出 staging 目录"
    assert not used[0].exists()
    assert apps_root_entries(tmp_path) == []


def test_staging_cleanup_survives_a_read_only_file(tmp_path: Path) -> None:
    """只读文件不该让清理失败。

    Windows 上 git clone 出来的 .git/objects/pack/*.pack 带只读属性，rmtree 遇到它
    会直接 WinError 5 —— 那不是「删不掉」，只是属性问题。少了这一步，失败的
    install 会在 extensions/apps/ 下静默留下一个 .aurora-stage-*。
    """
    root = install_root(tmp_path)
    with staging_directory(root) as staging:
        pack = staging.root / ".git" / "objects" / "pack"
        pack.mkdir(parents=True)
        blob = pack / "pack-abcdef.pack"
        blob.write_bytes(b"x")
        blob.chmod(stat.S_IREAD)

    assert apps_root_entries(tmp_path) == []


def test_install_root_creates_the_apps_directory(tmp_path: Path) -> None:
    root = install_root(tmp_path)

    assert root == tmp_path / "extensions" / "apps"
    assert root.is_dir()


def test_install_root_rejects_a_symlinked_ancestor(tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    try:
        (tmp_path / "extensions").symlink_to(elsewhere, target_is_directory=True)
    except OSError as error:  # pragma: no cover - 平台不具备创建符号链接的权限
        pytest.skip(f"当前环境无法创建符号链接：{error}")

    with pytest.raises(PlanError):
        install_root(tmp_path)


def _run(
    *arguments: str, timeout: float = _RUNNER_TIMEOUT_SECONDS, env: Mapping[str, str] | None = None
) -> ProcessResult:
    return CapturedProcessRunner().run([sys.executable, *arguments], cwd=Path.cwd(), timeout=timeout, env=env)


def test_runner_captures_the_two_streams_separately() -> None:
    """两个流都不写进 Aurora 的 stdout：以后还有 JSON 输出、GUI 与 scripting。"""
    result = _run("-c", "import sys; sys.stdout.write('to-out'); sys.stderr.write('to-err')")

    assert result.returncode == 0
    assert result.stdout == "to-out"
    assert result.stderr == "to-err"


def test_runner_returns_non_zero_exit_codes_instead_of_raising() -> None:
    assert _run("-c", f"raise SystemExit({_EXIT_UNKNOWN})").returncode == _EXIT_UNKNOWN


def test_runner_never_goes_through_a_shell() -> None:
    """shell=False：分号留在同一个 argv 元素里，没有被当成命令分隔符。"""
    result = _run("-c", "import sys; print(sys.argv[1:])", "safe; echo pwned")

    assert result.stdout.strip() == "['safe; echo pwned']"


def test_runner_passes_the_injected_environment() -> None:
    result = _run("-c", "import os; print(os.environ.get('AURORA_PROBE', ''))", env=_probe_environment())

    assert result.stdout.strip() == "probe"


def _probe_environment() -> dict[str, str]:
    return dict(os.environ, AURORA_PROBE="probe")


def test_runner_reports_a_missing_executable() -> None:
    with pytest.raises(CloneError) as failure:
        CapturedProcessRunner().run(["aurora-no-such-executable"], cwd=Path.cwd(), timeout=_PROBE_TIMEOUT_SECONDS)

    assert "未找到命令" in str(failure.value)


def test_runner_turns_a_timeout_into_a_clone_error() -> None:
    with pytest.raises(CloneError) as failure:
        _run("-c", _SLEEP_FOREVER, timeout=_PROBE_TIMEOUT_SECONDS)

    assert f"超过 {_PROBE_TIMEOUT_SECONDS:g} 秒未结束" in str(failure.value)
