"""MCP 安装检查：连接说明、工具发现、三个阶段、脱敏、建议语，以及「不留痕」。

不启动真实 MCP Server、不连接任何东西：``McpClientFactory`` 换成
``FakeMcpClientFactory``，超时靠一个永不返回的 open 加一个被改小的常量来触发，
所以这个文件不会真的等 60 秒。

源码、包管理器与远程 URL 安装共用协议连接、工具发现和资源关闭三个检查阶段。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from aurora_bot.mcp.models import McpEventMode, McpRemoteTool, McpToolsPage, McpTransport
from aurora_cli.commands.app.install import check_remote_config
from aurora_cli.commands.app.models import ConfigError, PlanError, VerifyError
from aurora_cli.commands.app.service import AppManager
from aurora_cli.commands.app.store import APPS_RELATIVE_PATH, AppStore
from aurora_cli.commands.app.verify import (
    Handshake,
    MCPVerifier,
    endpoint_hints,
    endpoint_target,
    install_hints,
    process_target,
    scrub_secrets,
    verify_environment,
)
from tests.cli.app.clone_support import APP_PATH, FakeCloner, project, repository
from tests.cli.app.install_support import (
    ENDPOINT,
    ENDPOINT_PACKAGE,
    WEATHER_COMMAND,
    WEATHER_PACKAGE,
    FakeMcpClientFactory,
    FakeSource,
    tools_page,
)

if TYPE_CHECKING:
    from pathlib import Path

_TOKEN_NAME = "AURORA_QQ_TOKEN"
_TOKEN_VALUE = "ghp_do_not_leak_me_0123456789"
_STAGED = "/staged/repository"
_EMPTY_REGISTRY = "app = []\n"
_LOCAL_SUBJECT = "本地 MCP Server"
_REMOTE_SUBJECT = "远程 MCP 端点"
_COMMAND_JSON = '["uv","run","weather-mcp"]'
_REQUESTED_NAME = "churk-ben/aurora-qq"


def _working_dir(tmp_path: Path) -> Path:
    return tmp_path.joinpath(*_STAGED.strip("/").split("/"))


def _verifier(factory: FakeMcpClientFactory) -> MCPVerifier:
    return MCPVerifier(factory)  # type: ignore[arg-type]


def _process(tmp_path: Path, *, env_names: tuple[str, ...] = ()) -> Handshake:
    """一份安装期的连接说明：连的是 staging 里那一份。"""
    return process_target(
        WEATHER_PACKAGE,
        WEATHER_COMMAND,
        working_dir=_working_dir(tmp_path),
        hints=install_hints(WEATHER_COMMAND),
        env_names=env_names,
    )


def _remote(*, auth_env: str | None = None) -> Handshake:
    return endpoint_target(ENDPOINT_PACKAGE, ENDPOINT, hints=endpoint_hints(ENDPOINT, auth_env), auth_env=auth_env)


def test_a_process_target_points_at_the_directory_it_was_given(tmp_path: Path) -> None:
    """安装期要连的是 staging 里那一份：正式路径上此刻什么都没有。"""
    working_dir = _working_dir(tmp_path)

    spec = _process(tmp_path).spec

    assert spec.working_dir == working_dir
    assert spec.command == WEATHER_COMMAND
    assert spec.package == WEATHER_PACKAGE
    assert spec.transport is McpTransport.STDIO
    assert spec.event_mode is McpEventMode.DISABLED


def test_a_process_target_enables_terminal_logs(tmp_path: Path) -> None:
    """Server 的 stderr 是失败时最有用的诊断信息，而这是用户显式要的检查。"""
    assert _process(tmp_path).spec.terminal_logs is True


def test_no_target_ever_marks_its_spec_enabled(tmp_path: Path) -> None:
    """检查只连一次，不代表这个 App 该被启用。"""
    assert _process(tmp_path).spec.enabled is False
    assert _remote().spec.enabled is False


def test_a_process_target_is_described_as_a_local_server(tmp_path: Path) -> None:
    assert _process(tmp_path).subject == _LOCAL_SUBJECT


def test_a_process_target_only_hands_over_the_named_variables(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_TOKEN_NAME, _TOKEN_VALUE)

    handshake = _process(tmp_path, env_names=(_TOKEN_NAME,))

    assert handshake.spec.environment[_TOKEN_NAME] == _TOKEN_VALUE


def test_a_process_target_keeps_its_environment_as_the_scrub_list(tmp_path: Path) -> None:
    """脱敏的输入就是这份环境：别的来源不可能出现在这个子进程的异常里。"""
    handshake = _process(tmp_path)

    assert handshake.secrets == handshake.spec.environment


def test_an_endpoint_target_carries_the_url_and_no_token_by_default() -> None:
    handshake = _remote()

    assert handshake.spec.url == ENDPOINT
    assert handshake.spec.auth_token is None
    assert handshake.spec.transport is McpTransport.STREAMABLE_HTTP
    assert handshake.secrets == {}


def test_an_endpoint_target_is_described_as_a_remote_endpoint() -> None:
    assert _remote().subject == _REMOTE_SUBJECT


def test_an_endpoint_target_reads_the_token_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """token 只从环境变量读，不经过任何参数。"""
    monkeypatch.setenv(_TOKEN_NAME, _TOKEN_VALUE)

    handshake = _remote(auth_env=_TOKEN_NAME)

    assert handshake.spec.auth_token == _TOKEN_VALUE
    assert handshake.secrets == {_TOKEN_NAME: _TOKEN_VALUE}


@pytest.mark.parametrize("value", [None, ""])
def test_a_declared_but_unreadable_token_fails_before_connecting(
    monkeypatch: pytest.MonkeyPatch, value: str | None
) -> None:
    """与其发一个必然 401 的请求、把用户引去查网络，不如说清是哪个变量没设置。"""
    monkeypatch.delenv(_TOKEN_NAME, raising=False)
    if value is not None:
        monkeypatch.setenv(_TOKEN_NAME, value)

    with pytest.raises(ConfigError) as error_info:
        _remote(auth_env=_TOKEN_NAME)

    assert _TOKEN_NAME in str(error_info.value)


def test_a_valid_package_label_is_kept_as_it_is() -> None:
    assert _remote().spec.package == ENDPOINT_PACKAGE


def test_install_hints_say_what_to_run_by_hand() -> None:
    hints = "".join(install_hints(WEATHER_COMMAND))

    assert "环境变量" in hints
    assert "uv run weather-mcp" in hints


def test_endpoint_hints_point_at_mcp_and_the_certificate() -> None:
    hints = "".join(endpoint_hints(ENDPOINT, None))

    assert ENDPOINT in hints
    assert "MCP Streamable HTTP" in hints
    assert "curl" in hints


def test_endpoint_hints_name_the_auth_variable_without_its_value() -> None:
    hints = "".join(endpoint_hints(ENDPOINT, _TOKEN_NAME))

    assert _TOKEN_NAME in hints
    assert _TOKEN_VALUE not in hints


def test_endpoint_hints_omit_the_auth_line_when_there_is_no_variable() -> None:
    assert "Bearer" not in "".join(endpoint_hints(ENDPOINT, None))


def test_a_successful_inspection_returns_the_protocol_version(tmp_path: Path) -> None:
    factory = FakeMcpClientFactory(protocol_version="2025-06-18")

    assert _verifier(factory).inspect(_process(tmp_path)).protocol_version == "2025-06-18"


def test_a_successful_inspection_closes_the_connection(tmp_path: Path) -> None:
    factory = FakeMcpClientFactory()

    _verifier(factory).inspect(_process(tmp_path))

    assert factory.ports[0].closed is True


def test_a_successful_inspection_reports_the_discovered_tools(tmp_path: Path) -> None:
    """工具 ID 由 ``aurora_bot.mcp`` 的发现规则生成，CLI 只报告它，不自己拼一个名字。"""
    factory = FakeMcpClientFactory(tools=("read_text_file", "list_allowed_directories"))

    inspection = _verifier(factory).inspect(_process(tmp_path))

    assert inspection.tool_ids == (
        f"{WEATHER_PACKAGE}:tool/definition/read_text_file",
        f"{WEATHER_PACKAGE}:tool/definition/list_allowed_directories",
    )


def test_an_empty_catalog_is_a_result_rather_than_a_failure(tmp_path: Path) -> None:
    """只有 Resources 或只有 Prompts 的合法 Server 也是合法 Server：检查本身不判它不合格。"""
    factory = FakeMcpClientFactory(tools=())

    assert _verifier(factory).inspect(_process(tmp_path)).tools == ()


def test_discovery_follows_every_page(tmp_path: Path) -> None:
    """分页与启动期共用一套规则：cursor 为空才算读完。"""
    factory = FakeMcpClientFactory(pages=(tools_page(("first",), next_cursor="page-2"), tools_page(("second",))))

    inspection = _verifier(factory).inspect(_process(tmp_path))

    assert [tool.raw_name for tool in inspection.tools] == ["first", "second"]
    assert factory.ports[0].cursors == [None, "page-2"]


def test_a_looping_cursor_is_reported_as_a_discovery_failure(tmp_path: Path) -> None:
    factory = FakeMcpClientFactory(
        pages=(tools_page(("first",), next_cursor="same"), tools_page(("second",), next_cursor="same"))
    )

    with pytest.raises(VerifyError) as error_info:
        _verifier(factory).inspect(_process(tmp_path))

    assert "工具发现" in str(error_info.value)
    assert "循环 cursor" in str(error_info.value)


def test_a_duplicate_tool_name_is_reported_as_a_discovery_failure(tmp_path: Path) -> None:
    factory = FakeMcpClientFactory(pages=(tools_page(("same", "same")),))

    with pytest.raises(VerifyError) as error_info:
        _verifier(factory).inspect(_process(tmp_path))

    assert "工具发现" in str(error_info.value)
    assert "重复" in str(error_info.value)


def test_an_invalid_schema_is_reported_as_a_discovery_failure(tmp_path: Path) -> None:
    """``object`` 之外的 schema 不是可注册工具，失败要落在发现阶段。"""
    bad = McpRemoteTool(name="broken", description=None, input_schema={"type": "string"})
    factory = FakeMcpClientFactory(pages=(McpToolsPage(tools=(bad,)),))

    with pytest.raises(VerifyError) as error_info:
        _verifier(factory).inspect(_process(tmp_path))

    assert "工具发现" in str(error_info.value)
    assert "object" in str(error_info.value)


def test_a_discovery_failure_still_closes_the_connection(tmp_path: Path) -> None:
    """发现失败也要收掉这次连接起的进程，不能留给调用方去收。"""
    factory = FakeMcpClientFactory(list_failure=RuntimeError("stream reset"))

    with pytest.raises(VerifyError):
        _verifier(factory).inspect(_process(tmp_path))

    assert factory.ports[0].closed is True


def test_open_failure_names_the_startup_phase(tmp_path: Path) -> None:
    factory = FakeMcpClientFactory(failure=RuntimeError("spawn uv ENOENT"))

    with pytest.raises(VerifyError) as error_info:
        _verifier(factory).inspect(_process(tmp_path))

    message = str(error_info.value)
    assert "启动进程或协议连接" in message
    assert "spawn uv ENOENT" in message, "Server 自己的说法是失败时最有用的东西"


def test_an_sdk_exception_group_shows_the_underlying_error(tmp_path: Path) -> None:
    failure = ExceptionGroup("unhandled errors in a TaskGroup", [ValueError("Unexpected content type: text/html")])
    factory = FakeMcpClientFactory(failure=failure)

    with pytest.raises(VerifyError) as error_info:
        _verifier(factory).inspect(_process(tmp_path))

    assert "Unexpected content type: text/html" in str(error_info.value)
    assert "unhandled errors in a TaskGroup" not in str(error_info.value)


def test_the_error_names_the_subject_and_offers_a_way_forward(tmp_path: Path) -> None:
    factory = FakeMcpClientFactory(failure=RuntimeError("boom"))

    with pytest.raises(VerifyError) as error_info:
        _verifier(factory).inspect(_process(tmp_path))

    message = str(error_info.value)
    assert _LOCAL_SUBJECT in message, "连的是本地进程，别说成别人的服务出了问题"
    assert "可尝试" in message
    assert "环境变量" in message, "多数失败是缺 secret，这条建议必须出现"
    assert "uv run weather-mcp" in message


def test_a_remote_failure_is_described_as_a_remote_endpoint() -> None:
    factory = FakeMcpClientFactory(failure=RuntimeError("boom"))

    with pytest.raises(VerifyError) as error_info:
        _verifier(factory).inspect(_remote())

    message = str(error_info.value)
    assert _REMOTE_SUBJECT in message
    assert _LOCAL_SUBJECT not in message


def test_a_timeout_is_reported_as_a_handshake_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """缩短握手超时，验证错误类型与说明，避免测试等待默认时长。"""
    monkeypatch.setattr("aurora_cli.commands.app.verify.DEFAULT_TIMEOUT_SECONDS", 0.05)
    factory = FakeMcpClientFactory(hang=True)

    with pytest.raises(VerifyError) as error_info:
        _verifier(factory).inspect(_process(tmp_path))

    assert "超过 0.05 秒仍未完成握手" in str(error_info.value)


def test_a_disconnect_right_after_the_handshake_is_reported(tmp_path: Path) -> None:
    factory = FakeMcpClientFactory(connected=False)

    with pytest.raises(VerifyError) as error_info:
        _verifier(factory).inspect(_process(tmp_path))

    assert "随即断开" in str(error_info.value)


def test_a_failing_close_is_reported_as_the_closing_phase(tmp_path: Path) -> None:
    factory = FakeMcpClientFactory(close_failure=RuntimeError("pipe already closed"))

    with pytest.raises(VerifyError) as error_info:
        _verifier(factory).inspect(_process(tmp_path))

    message = str(error_info.value)
    assert "关闭阶段失败" in message
    assert "pipe already closed" in message


def test_a_failing_close_does_not_mask_a_successful_handshake(tmp_path: Path) -> None:
    """关闭失败要报成关闭阶段，不能盖掉握手已经得出的结论。"""
    factory = FakeMcpClientFactory(connected=False, close_failure=RuntimeError("closing"))

    with pytest.raises(VerifyError) as error_info:
        _verifier(factory).inspect(_process(tmp_path))

    assert "随即断开" in str(error_info.value)


def test_verify_environment_leaves_bootstrap_variables_to_sdk() -> None:
    assert verify_environment() == {}


def test_verify_environment_only_adds_the_named_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_TOKEN_NAME, _TOKEN_VALUE)
    monkeypatch.setenv("UNRELATED_SECRET", "x")

    environment = verify_environment([_TOKEN_NAME, "MISSING_NAME"])

    assert environment[_TOKEN_NAME] == _TOKEN_VALUE
    assert "UNRELATED_SECRET" not in environment, "没点名的变量不进子进程环境"
    assert "MISSING_NAME" not in environment, "环境里没有的名字直接跳过，不填空串"


def test_scrub_judges_by_name_not_by_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    """值的形状千变万化，而一个叫 ``*_TOKEN`` 的变量的值没有理由出现在诊断信息里。"""
    monkeypatch.setenv("SystemRoot", r"C:\Windows")
    monkeypatch.setenv("MY_PASSWORD", "hunter2")

    environment = verify_environment(["SystemRoot", "MY_PASSWORD"])

    assert scrub_secrets(r"cwd C:\Windows", environment) == r"cwd C:\Windows"
    assert scrub_secrets("pw=hunter2", environment) == "pw=***"


def test_scrub_ignores_empty_values() -> None:
    """空串会把整段文本插满 ``***``：str.replace("") 不是无操作。"""
    assert scrub_secrets("abc", {"EMPTY_TOKEN": ""}) == "abc"


def test_scrub_leaves_text_alone_when_the_value_is_absent() -> None:
    assert scrub_secrets("启动失败：找不到命令", {_TOKEN_NAME: _TOKEN_VALUE}) == "启动失败：找不到命令"


def test_a_process_failure_never_prints_a_secret(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """stderr 是第三方进程写的，不能假定它干净。"""
    monkeypatch.setenv(_TOKEN_NAME, _TOKEN_VALUE)
    factory = FakeMcpClientFactory(failure=RuntimeError(f"启动失败：token={_TOKEN_VALUE}"))

    with pytest.raises(VerifyError) as error_info:
        _verifier(factory).inspect(_process(tmp_path, env_names=(_TOKEN_NAME,)))

    message = str(error_info.value)
    assert _TOKEN_VALUE not in message
    assert "***" in message


@pytest.mark.parametrize("auth_env", [_TOKEN_NAME, "MCP_KEY"])
@pytest.mark.parametrize("phase", ["connect", "discover", "close"])
def test_a_remote_failure_never_prints_the_bearer_token(
    monkeypatch: pytest.MonkeyPatch, auth_env: str, phase: str
) -> None:
    monkeypatch.setenv(auth_env, _TOKEN_VALUE)
    error = RuntimeError(f"{phase}: Bearer {_TOKEN_VALUE}")
    factory = FakeMcpClientFactory(
        failure=error if phase == "connect" else None,
        list_failure=error if phase == "discover" else None,
        close_failure=error if phase == "close" else None,
    )

    with pytest.raises(VerifyError) as error_info:
        _verifier(factory).inspect(_remote(auth_env=auth_env))

    assert _TOKEN_VALUE not in str(error_info.value)
    assert "***" in str(error_info.value)


def _manager(root: Path, factory: FakeMcpClientFactory) -> AppManager:
    """一个完全离线的 manager：GitHub 与 Git 两条出口都换成替身。"""
    return AppManager(
        AppStore(root),
        FakeSource(repository()),  # type: ignore[arg-type]
        cloner=FakeCloner(),
        verifier=_verifier(factory),
    )


def test_a_failed_verify_takes_no_lock_and_writes_nothing(tmp_path: Path) -> None:
    """verify 在提交之前：失败时没有任何东西需要回滚。"""
    root = project(tmp_path, _EMPTY_REGISTRY)
    manager = _manager(root, FakeMcpClientFactory(failure=RuntimeError("boom")))

    with pytest.raises(VerifyError):
        manager.install(_REQUESTED_NAME, command=_COMMAND_JSON, yes=True)

    assert (root / APPS_RELATIVE_PATH).read_text(encoding="utf-8") == _EMPTY_REGISTRY
    assert not (root / APP_PATH).exists()


def test_a_verify_failure_aborts_after_the_confirmation_was_acted_on(tmp_path: Path) -> None:
    """verify 在确认之后：用户说过要继续，但校验失败就不该继续。"""
    root = project(tmp_path, _EMPTY_REGISTRY)
    manager = _manager(root, FakeMcpClientFactory(failure=RuntimeError("boom")))
    seen: list[str] = []

    def confirm(_plan: object) -> bool:
        seen.append("asked")
        return True

    with pytest.raises(VerifyError):
        manager.install(_REQUESTED_NAME, command=_COMMAND_JSON, confirm=confirm)  # type: ignore[arg-type]

    assert seen == ["asked"]
    assert not (root / APP_PATH).exists()


def test_install_checks_and_enables_by_default(tmp_path: Path) -> None:
    """安装的默认目的就是「下次 aurora start 能用到它」，所以两个默认值都是真。"""
    factory = FakeMcpClientFactory()
    manager = _manager(project(tmp_path, _EMPTY_REGISTRY), factory)

    result = manager.install(_REQUESTED_NAME, command=_COMMAND_JSON, yes=True)

    assert result is not None
    assert result.enabled is True
    assert factory.specs != [], "默认就该连一次并发现工具"
    assert manager.list_apps().apps[0].enabled is True


def test_a_server_without_tools_is_not_installed(tmp_path: Path) -> None:
    """连接成功但没有可注册工具的 Server 不算装好：Aurora 只把 Tools 暴露给 Bot。"""
    root = project(tmp_path, _EMPTY_REGISTRY)
    manager = _manager(root, FakeMcpClientFactory(tools=()))

    with pytest.raises(VerifyError) as error_info:
        manager.install(_REQUESTED_NAME, command=_COMMAND_JSON, yes=True)

    message = str(error_info.value)
    assert "连接成功" in message, "不要把「没有工具」说成连接失败"
    assert "可注册的 Tool" in message
    assert "--events" in message, "拒绝时必须指出另一条登记路径"
    assert (root / APPS_RELATIVE_PATH).read_text(encoding="utf-8") == _EMPTY_REGISTRY
    assert not (root / APP_PATH).exists(), "拒绝时磁盘上不留任何东西"


def test_a_server_without_tools_registers_as_a_world_producer(tmp_path: Path) -> None:
    """零工具 + world_events 是**世界生产者**：它把外部事实推进世界线，不需要暴露 Tool。"""
    root = project(tmp_path, _EMPTY_REGISTRY)
    manager = _manager(root, FakeMcpClientFactory(tools=()))

    result = manager.install(_REQUESTED_NAME, command=_COMMAND_JSON, yes=True, event_mode="world_events")

    assert result is not None
    assert result.tools == ()
    assert result.event_mode == "world_events"
    entry = (root / APPS_RELATIVE_PATH).read_text(encoding="utf-8")
    assert 'event_mode = "world_events"' in entry, "声明必须落进注册表，否则启动时又变回 disabled"


def test_world_producer_flag_is_rejected_by_remote_endpoints(tmp_path: Path) -> None:
    """streamable_http 暂不支持 world_events：静态校验要在连接之前就拒绝。"""
    with pytest.raises(PlanError, match="暂不支持 world_events"):
        check_remote_config("org.example.remote", "https://mcp.example.org/rpc", None, event_mode="world_events")


def test_install_does_not_write_per_app_agent_grants(tmp_path: Path) -> None:
    """App 条目只保存连接信息；没有逐 App 的 Agent 授权字段。"""
    root = project(tmp_path, _EMPTY_REGISTRY)
    manager = _manager(root, FakeMcpClientFactory())

    result = manager.install(_REQUESTED_NAME, command=_COMMAND_JSON, yes=True)

    assert result is not None
    assert "agents = " not in (root / APPS_RELATIVE_PATH).read_text(encoding="utf-8")


def test_a_successful_verify_still_installs(tmp_path: Path) -> None:
    root = project(tmp_path, _EMPTY_REGISTRY)
    manager = _manager(root, FakeMcpClientFactory())

    result = manager.install(_REQUESTED_NAME, command=_COMMAND_JSON, yes=True)

    assert result is not None
    assert [item.package for item in manager.list_apps().apps] == [result.package]
    assert (root / APP_PATH).is_dir()


def test_verify_without_an_explicit_yes_needs_a_confirmation(tmp_path: Path) -> None:
    """verify 是通过 --verify 显式请求的，但它不能顺带把确认也一起跳过。"""
    manager = _manager(project(tmp_path, _EMPTY_REGISTRY), FakeMcpClientFactory())

    with pytest.raises(ConfigError, match="未提供确认动作"):
        manager.install(_REQUESTED_NAME, command=_COMMAND_JSON)


def test_the_verified_spec_points_into_the_staging_directory(tmp_path: Path) -> None:
    """verify 连的是 staging 里那一份，不是正式路径 —— 此刻正式路径上什么都没有。"""
    root = project(tmp_path, _EMPTY_REGISTRY)
    factory = FakeMcpClientFactory()
    manager = _manager(root, factory)

    manager.install(_REQUESTED_NAME, command=_COMMAND_JSON, yes=True)

    working_dir = factory.spec().working_dir
    assert working_dir is not None
    assert working_dir.parent == root / "extensions" / "apps"
    assert working_dir.name.startswith(".aurora-stage-"), "连的必须是 staging 目录"
    assert not working_dir.exists(), "verify 之后 staging 已经被清理"


def test_a_runner_verify_connects_in_the_project_root(tmp_path: Path) -> None:
    """包管理器型安装没有 staging：装完即用，没有第二个地方可连。"""
    factory = FakeMcpClientFactory()
    root = project(tmp_path, _EMPTY_REGISTRY)

    plan = _manager(root, factory).install_runner(executable="npx", specifier="demo", yes=True)

    assert plan is not None
    assert factory.spec().working_dir == root
    assert factory.spec().command == ("npx", "-y", "demo")


def test_connect_always_verifies(tmp_path: Path) -> None:
    """这条路径上握手是准入门槛，不是可选项：没有别的东西能证明它后面真的是 MCP。"""
    root = project(tmp_path, _EMPTY_REGISTRY)

    with pytest.raises(VerifyError):
        _manager(root, FakeMcpClientFactory(failure=RuntimeError("连不上"))).connect(
            ENDPOINT, package=ENDPOINT_PACKAGE, yes=True
        )

    assert (root / APPS_RELATIVE_PATH).read_text(encoding="utf-8") == _EMPTY_REGISTRY
