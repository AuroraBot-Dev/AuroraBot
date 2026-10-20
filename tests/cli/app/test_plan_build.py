"""计划层的纯函数：``--command`` 解析、路径推导、包管理器与远程端点的准入。

这一层不克隆、不读注册表、不发请求，所以本文件也不需要任何替身：输入是字符串与
元组，输出是计划或 PlanError。三条登记路径各自的准入规则都在这里，因为它们都是
「一边解析用户输入、一边组装计划」的纯逻辑，跑到 service 里测反而绕。
"""

from __future__ import annotations

import pytest

from aurora.commands.app.install import (
    PACKAGE_RUNNER_WORKING_DIR,
    check_app_config,
    check_connect_url,
    check_remote_config,
    check_runner_specifier,
    derive_working_dir,
    install_path,
    manifest_candidate,
    parse_command,
    runner_command,
    runner_package,
    runner_plan,
    runtime_of,
    subdir_parts,
    user_candidate,
)
from aurora.commands.app.models import PlanError
from tests.cli.app.clone_support import APPS_DIRECTORY
from tests.cli.app.install_support import ENDPOINT, MANIFEST_EVIDENCE, WEATHER_COMMAND, candidate, manifest_text

_FULL_NAME = "Churk-Ben/Aurora-QQ"
_FINAL_PATH = "extensions/apps/Churk-Ben/Aurora-QQ"


@pytest.mark.parametrize(
    "value",
    [
        "uv run weather-mcp",
        "[]",
        '["uv",123]',
        '{"command": ["uv"]}',
        '[""]',
    ],
)
def test_invalid_commands_are_plan_errors(value: str) -> None:
    """非法输入只有一条出路：PlanError。内部永远是 argv 元组，不 join 回字符串。"""
    with pytest.raises(PlanError):
        parse_command(value)


def test_valid_command_becomes_an_argv_tuple() -> None:
    assert parse_command('["uv","run","weather-mcp"]') == WEATHER_COMMAND


def test_command_keeps_extra_arguments_verbatim() -> None:
    assert parse_command('["uv", "run", "--frozen", "weather-mcp"]') == (
        "uv",
        "run",
        "--frozen",
        "weather-mcp",
    )


def test_user_candidate_shape() -> None:
    """``--command`` 只表示用户接管了「怎么启动」，不表示验证过它是 MCP Server。"""
    user = user_candidate(WEATHER_COMMAND)

    assert user.command == WEATHER_COMMAND
    assert user.evidence == "explicit --command"
    assert user.runtime == "python-uv"
    assert user.repository_subdir == "."


def test_manifest_candidate_shape() -> None:
    """清单声明的入口带出处：仓库作者写了什么，计划里就记什么。"""
    from_manifest = manifest_candidate(WEATHER_COMMAND)

    assert "aurora-app.toml" in from_manifest.evidence
    assert from_manifest.command == WEATHER_COMMAND


def test_the_two_candidates_are_distinguishable() -> None:
    """出处只有一句证据；计划里没有第二个字段再表达一遍「谁说的」。"""
    assert user_candidate(WEATHER_COMMAND).evidence != manifest_candidate(WEATHER_COMMAND).evidence


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        (("uv", "run", "weather-mcp"), "python-uv"),
        (("uvx", "weather-mcp"), "python-uv"),
        (("node", "./dist/index.js"), "node"),
        (("npx", "-y", "demo"), "node"),
        (("/usr/local/bin/node", "./x.js"), "node"),
        (("docker", "run", "demo"), "docker"),
    ],
)
def test_runtime_is_classified_by_executable_name(command: tuple[str, ...], expected: str) -> None:
    assert runtime_of(command) == expected


@pytest.mark.parametrize(
    "value",
    ["", " ", "-y demo", " demo", "demo ", "a b", "a\\b", "a\x00b", "/etc/passwd", "../demo"],
)
def test_unsafe_specifiers_are_rejected(value: str) -> None:
    """包名会原样进 argv，所以它必须不能是选项、路径或带空白的一段文本。"""
    with pytest.raises(PlanError):
        check_runner_specifier(value, executable="npx")


@pytest.mark.parametrize("value", ["demo", "@scope/demo", "demo@1.2.3", "demo[extra]", "demo==1.0", "a.b"])
def test_a_plain_package_specifier_is_accepted(value: str) -> None:
    """版本范围与 extra 交给包管理器自己判断：Aurora 不该比 npm 更懂 npm 的包名。"""
    assert check_runner_specifier(value, executable="npx") == value


def test_npx_runs_without_a_prompt() -> None:
    """``aurora start`` 是非交互的：缺了 -y 会变成一次静默挂起。"""
    assert runner_command("npx", "demo") == ("npx", "-y", "demo")


def test_uvx_needs_no_extra_arguments() -> None:
    assert runner_command("uvx", "demo") == ("uvx", "demo")


def test_an_unknown_runner_is_rejected() -> None:
    with pytest.raises(PlanError) as error_info:
        runner_command("pnpm", "demo")

    assert "pnpm" in str(error_info.value)


@pytest.mark.parametrize(
    ("specifier", "expected"),
    [
        ("weather-mcp", "npx.app.weather-mcp"),
        ("@scope/weather", "npx.scope.weather"),
        ("Weather.MCP", "npx.app.weather-mcp"),
        ("weather_mcp", "npx.app.weather_mcp"),
        ("2fast", "npx.app.app-2fast"),
        ("@scope/2fast", "npx.scope.app-2fast"),
    ],
)
def test_the_runner_package_is_derived_from_the_package_name(specifier: str, expected: str) -> None:
    """包名决定身份，点视为普通字符，npm scope 划分层级，数字开头的段补字母前缀。"""
    assert runner_package("npx", specifier) == expected


def test_the_runner_root_distinguishes_npx_from_uvx() -> None:
    assert runner_package("uvx", "weather-mcp") == "uvx.app.weather-mcp"


def test_a_runner_plan_runs_in_the_project_root() -> None:
    """不克隆任何东西时，进程的 cwd 与安装根无关。"""
    plan = runner_plan(executable="npx", specifier="demo", package="npx.demo")

    assert plan.working_dir == PACKAGE_RUNNER_WORKING_DIR
    assert plan.command == ("npx", "-y", "demo")
    assert plan.runtime == "node"
    assert plan.enabled is False


def test_a_runner_plan_carries_the_requested_initial_state() -> None:
    assert runner_plan(executable="uvx", specifier="demo", package="uvx.demo", enabled=True).enabled is True


def test_a_plain_https_endpoint_is_accepted() -> None:
    assert check_connect_url(ENDPOINT) == ENDPOINT


def test_a_github_repository_is_not_an_mcp_endpoint() -> None:
    with pytest.raises(PlanError, match="GitHub 仓库地址不是 MCP 端点"):
        check_connect_url("https://github.com/n8n-io/n8n.git")


def test_a_harmless_query_parameter_is_allowed() -> None:
    """只拒绝凭据，不拒绝查询串：``?tenant=`` 这类路由参数与认证无关。"""
    url = f"{ENDPOINT}?tenant=acme"

    assert check_connect_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "http://mcp.example.com/rpc",
        "https://user:pw@mcp.example.com/rpc",
        "https://mcp.example.com/rpc#fragment",
        "mcp.example.com/rpc",
        "/rpc",
        "",
    ],
)
def test_a_url_without_a_clean_https_shape_is_rejected(url: str) -> None:
    with pytest.raises(PlanError) as error_info:
        check_connect_url(url)

    assert "--auth-env" in str(error_info.value)


@pytest.mark.parametrize(
    "query",
    ["token=abc", "access_token=abc", "api_key=abc", "apikey=abc", "key=abc", "sig=abc", "password=abc"],
)
def test_a_credential_in_the_query_string_is_rejected(query: str) -> None:
    """URL 会进注册表、会被日志和终端回显：token 只能待在环境变量里。"""
    with pytest.raises(PlanError) as error_info:
        check_connect_url(f"{ENDPOINT}?{query}")

    message = str(error_info.value)
    assert query.split("=", maxsplit=1)[0] in message, "要指出是哪个参数"
    assert "--auth-env" in message


def test_a_query_name_that_merely_contains_a_short_word_is_allowed() -> None:
    """``monkey`` 里有 ``key``：短名按等值比较，不做子串匹配，否则误伤一片。"""
    url = f"{ENDPOINT}?monkey=business"

    assert check_connect_url(url) == url


def test_a_remote_config_passes_the_runtime_whitelist() -> None:
    """接入的地址与变量名必须能通过 ``aurora start`` 读注册表时那一套校验。"""
    check_remote_config("com.example.remote", ENDPOINT, "MCP_TOKEN")


def test_a_remote_config_rejects_a_bad_environment_name() -> None:
    with pytest.raises(PlanError) as error_info:
        check_remote_config("com.example.remote", ENDPOINT, "1BAD")

    assert "连接配置不合法" in str(error_info.value)


def test_a_remote_config_rejects_a_non_https_url() -> None:
    with pytest.raises(PlanError):
        check_remote_config("com.example.remote", "http://mcp.example.com/rpc", None)


def test_install_path_is_owner_and_repo_under_the_apps_root() -> None:
    assert install_path(_FULL_NAME) == "/".join((*APPS_DIRECTORY, "Churk-Ben", "Aurora-QQ"))


def test_install_path_does_not_use_the_package_id() -> None:
    """目录来自 full_name，与 package 无关：package 可以显式指定成别的名字。"""
    assert install_path(_FULL_NAME) == _FINAL_PATH


def test_root_subdir_makes_working_dir_equal_the_install_path() -> None:
    assert derive_working_dir(_FINAL_PATH, ".") == _FINAL_PATH


def test_subdir_is_joined_under_the_install_path() -> None:
    assert derive_working_dir(_FINAL_PATH, "apps/weather") == f"{_FINAL_PATH}/apps/weather"


def test_working_dir_and_install_path_stay_separate_concepts() -> None:
    """两者恰好同值的情况很多，撞名不会被发现；字段名先把它们分开。"""
    assert derive_working_dir(_FINAL_PATH, "apps/weather") != _FINAL_PATH


def test_subdir_parts_are_shared_by_the_plan_and_verify() -> None:
    """verify 要在 staging 里拼出同一个子目录，两边各拆一次迟早会拆出两个答案。"""
    assert subdir_parts(".") == ()
    assert subdir_parts("apps/weather") == ("apps", "weather")


def test_a_plan_whose_working_dir_escapes_the_project_is_rejected() -> None:
    with pytest.raises(PlanError) as error_info:
        check_app_config("com.example.weather", "../../outside", WEATHER_COMMAND)

    assert "安装配置不合法" in str(error_info.value)


def test_a_plan_with_an_empty_command_is_rejected() -> None:
    with pytest.raises(PlanError):
        check_app_config("com.example.weather", "extensions/apps/weather", ())


def test_a_plan_with_a_bad_package_id_is_rejected() -> None:
    with pytest.raises(PlanError):
        check_app_config("Not.A.Package", "extensions/apps/weather", WEATHER_COMMAND)


def test_the_candidate_builder_matches_the_manifest_defaults() -> None:
    """``candidate()`` 是别的测试文件造计划时的输入，它得与真实清单解析同形。"""
    assert candidate().command == WEATHER_COMMAND
    assert candidate().evidence == MANIFEST_EVIDENCE
    assert manifest_text().startswith("manifest_version = 1")
