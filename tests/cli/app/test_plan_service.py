"""``AppManager.prepare_install`` / ``plan_install`` 的编排：顺序、清理与 canonical identity。

Git 边界换成 ``FakeCloner``，GitHub 出口是假 transport。全程不发请求、不起子进程、
不需要本机装 git、uv、npm 或 Node。

本文件里最要紧的一类断言是**顺序**：清单准入发生在 clone 之前，所以「没有清单」
的代价是一次 API 调用，而不是一次整库下载。
"""

from __future__ import annotations

import base64
import dataclasses
from typing import TYPE_CHECKING, NamedTuple

import httpx2
import pytest

from aurora_cli.commands.app.github import GitHubSource
from aurora_cli.commands.app.manifest import MANIFEST_NAME
from aurora_cli.commands.app.models import CloneError, GitHubRateLimitError, InstallPlan, ManifestError, PlanError
from aurora_cli.commands.app.service import AppManager
from aurora_cli.commands.app.store import APPS_RELATIVE_PATH, AppStore
from tests.cli.app.clone_support import (
    APP_PATH,
    CONFLICTING_PACKAGE,
    DEFAULT_COMMIT,
    FakeCloner,
    apps_root,
    apps_root_entries,
    project,
    registry_entry,
    repository_payload,
)
from tests.cli.app.install_support import MANIFEST, WEATHER_COMMAND, manifest_text
from tests.cli.app.search_support import FakeTransport

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

_STAGE_MARKER = ".aurora-stage-"
_REQUESTED_NAME = "churk-ben/aurora-qq"
_CANONICAL = "Churk-Ben/Aurora-QQ"
_COMMAND_JSON = '["uv","run","pkg-a"]'


class Setup(NamedTuple):
    """一次编排测试需要的四样东西；``root`` 是 AppStore 眼里的项目根。"""

    manager: AppManager
    root: Path
    cloner: FakeCloner
    http: FakeTransport


def _contents(content: str) -> httpx2.Response:
    """一份 Contents API 的文件响应。"""
    payload = {
        "type": "file",
        "encoding": "base64",
        "content": base64.b64encode(content.encode("utf-8")).decode(),
    }
    return httpx2.Response(200, json=payload)


def _no_manifest() -> httpx2.Response:
    """仓库根目录没有 ``aurora-app.toml`` 时 GitHub 的回答。"""
    return httpx2.Response(404, json={"message": "Not Found"})


def _setup(
    tmp_path: Path,
    *,
    manifest: httpx2.Response | None = None,
    files: Mapping[str, str] | None = None,
    failure: Exception | None = None,
    payload: Mapping[str, object] | None = None,
    apps_toml: str | None = None,
) -> Setup:
    """一个完全离线的 manager。

    ``manifest`` 默认是一份声明了天气 Server 的合规清单；传 ``_no_manifest()``
    就是「仓库里没有这个文件」。克隆内容默认带着同一份清单，因为真实仓库既然声明
    了它，clone 下来的目录里当然有。
    """
    root = project(tmp_path, apps_toml)
    http = FakeTransport(
        httpx2.Response(200, json=dict(payload if payload is not None else repository_payload())),
        _contents(MANIFEST) if manifest is None else manifest,
    )
    cloner = FakeCloner(files if files is not None else {MANIFEST_NAME: MANIFEST}, failure=failure)
    store = AppStore(root)
    return Setup(AppManager(store, GitHubSource(http), cloner=cloner), store.project_root, cloner, http)


def _contents_call(http: FakeTransport) -> dict[str, object]:
    """第 1 次调用是仓库接口，第 2 次是清单接口。"""
    return http.calls[1]


def test_plan_carries_every_field_the_next_stage_needs(tmp_path: Path) -> None:
    setup = _setup(tmp_path)

    plan = setup.manager.plan_install(_REQUESTED_NAME, ref="v1.2.0")

    assert plan.repository == _CANONICAL
    assert plan.ref == "v1.2.0"
    assert plan.commit == DEFAULT_COMMIT
    assert plan.package == "github.churk-ben.aurora-qq"
    assert plan.install_path == APP_PATH
    assert plan.repository_subdir == "."
    assert plan.working_dir == APP_PATH
    assert plan.transport == "stdio"
    assert plan.command == WEATHER_COMMAND
    assert plan.runtime == "python-uv"
    assert plan.evidence == f"{MANIFEST_NAME} [server].command"
    assert plan.enabled is False


def test_plan_never_contains_a_staging_path_or_a_version(tmp_path: Path) -> None:
    """stage 在计划生成完就删，任何写进计划的 stage 路径都是死引用。"""
    setup = _setup(tmp_path)

    plan = setup.manager.plan_install(_REQUESTED_NAME)

    assert not hasattr(plan, "version")
    for field in dataclasses.fields(plan):
        assert _STAGE_MARKER not in str(getattr(plan, field.name))


def test_head_comes_from_the_clone_not_from_the_api(tmp_path: Path) -> None:
    """commit 只写可证明的事实：clone 之后 rev-parse 出来的实际 HEAD。"""
    setup = _setup(tmp_path)

    plan = setup.manager.plan_install(_REQUESTED_NAME)

    assert plan.commit == setup.cloner.commit


def test_the_command_comes_from_the_manifest_the_repository_shipped(tmp_path: Path) -> None:
    """清单写的是什么，计划里就是什么：不推断、不改写、不挑「更像样的」那个。"""
    command = ("node", "./dist/server.js", "--stdio")
    setup = _setup(
        tmp_path,
        manifest=_contents(manifest_text(command)),
        files={MANIFEST_NAME: manifest_text(command)},
    )

    plan = setup.manager.plan_install(_REQUESTED_NAME)

    assert plan.command == command
    assert plan.runtime == "node"


def test_staging_is_cleaned_up_after_success(tmp_path: Path) -> None:
    """这个入口只回答「这个仓库是什么」，stage 里没有任何东西值得留下。"""
    setup = _setup(tmp_path)

    setup.manager.plan_install(_REQUESTED_NAME)

    assert setup.cloner.roots and not setup.cloner.roots[0].exists()
    assert apps_root_entries(setup.root) == []


def test_registry_is_never_written(tmp_path: Path) -> None:
    """这个入口与注册表只有「查重」这一件事，不写。"""
    existing = registry_entry()
    setup = _setup(tmp_path, apps_toml=existing)

    setup.manager.plan_install(_REQUESTED_NAME)

    assert (setup.root / APPS_RELATIVE_PATH).read_text(encoding="utf-8") == existing


def test_a_missing_registry_is_not_required(tmp_path: Path) -> None:
    """``config/apps.toml`` 是 aurora setup 生成的；只生成计划不需要它存在。"""
    setup = _setup(tmp_path)

    assert setup.manager.plan_install(_REQUESTED_NAME).package

    assert not (setup.root / APPS_RELATIVE_PATH).exists()


def test_plan_is_the_shared_value_object(tmp_path: Path) -> None:
    setup = _setup(tmp_path)

    assert isinstance(setup.manager.plan_install(_REQUESTED_NAME), InstallPlan)


def test_ref_is_passed_through_to_the_cloner(tmp_path: Path) -> None:
    """ref 不在这里判断形状，按原样交给 Git（裁决第 1 条）。"""
    setup = _setup(tmp_path)

    setup.manager.plan_install(_REQUESTED_NAME, ref="9f8e7d6")

    assert setup.cloner.calls[0]["ref"] == "9f8e7d6"


def test_the_manifest_is_read_from_the_requested_ref(tmp_path: Path) -> None:
    """从 main 读到清单却去装一个 tag，等于按另一个版本的声明安装。"""
    setup = _setup(tmp_path)

    setup.manager.plan_install(_REQUESTED_NAME, ref="v1.2.0")

    call = _contents_call(setup.http)
    assert str(call["url"]).endswith(f"/contents/{MANIFEST_NAME}")
    assert call["params"] == {"ref": "v1.2.0"}


def test_no_ref_means_the_default_branch(tmp_path: Path) -> None:
    setup = _setup(tmp_path)

    setup.manager.plan_install(_REQUESTED_NAME)

    assert _contents_call(setup.http)["params"] == {}


def test_a_repository_without_a_manifest_is_rejected_without_cloning(tmp_path: Path) -> None:
    """整平台仓库一旦克隆下来，用户已经付了整库下载与检出的成本。"""
    setup = _setup(tmp_path, manifest=_no_manifest())

    with pytest.raises(ManifestError) as error_info:
        setup.manager.plan_install(_REQUESTED_NAME)

    assert MANIFEST_NAME in str(error_info.value)
    assert setup.cloner.calls == []
    assert not apps_root(setup.root).exists(), "拒绝发生在建安装根之前"


def test_a_broken_manifest_is_rejected_without_cloning(tmp_path: Path) -> None:
    """清单存在但读不懂，与没有清单对用户是同一件事：这个仓库没声明怎么启动。"""
    setup = _setup(tmp_path, manifest=_contents('manifest_version = 1\n\n[server]\ncommand = ["uv"\n'))

    with pytest.raises(ManifestError) as error_info:
        setup.manager.plan_install(_REQUESTED_NAME)

    assert "无法解析" in str(error_info.value)
    assert setup.cloner.calls == []


def test_a_manifest_without_a_command_is_rejected_without_cloning(tmp_path: Path) -> None:
    setup = _setup(tmp_path, manifest=_contents("manifest_version = 1\n\n[server]\n"))

    with pytest.raises(ManifestError):
        setup.manager.plan_install(_REQUESTED_NAME)

    assert setup.cloner.calls == []


def test_an_unsupported_manifest_version_is_rejected_without_cloning(tmp_path: Path) -> None:
    setup = _setup(tmp_path, manifest=_contents(manifest_text(version=2)))

    with pytest.raises(ManifestError):
        setup.manager.plan_install(_REQUESTED_NAME)

    assert setup.cloner.calls == []


def test_the_manifest_error_names_the_repository_and_the_ref(tmp_path: Path) -> None:
    setup = _setup(tmp_path, manifest=_no_manifest())

    with pytest.raises(ManifestError) as error_info:
        setup.manager.plan_install(_REQUESTED_NAME, ref="v1.2.0")

    assert f"{_CANONICAL}@v1.2.0" in str(error_info.value)


def test_a_manifest_read_failure_is_not_mistaken_for_a_missing_manifest(tmp_path: Path) -> None:
    """配额耗尽与「仓库里没有这个文件」的修法完全不同，不能都报成后者。"""
    limited = httpx2.Response(403, json={"message": "nope"}, headers={"X-RateLimit-Remaining": "0"})
    setup = _setup(tmp_path, manifest=limited)

    with pytest.raises(GitHubRateLimitError):
        setup.manager.plan_install(_REQUESTED_NAME)

    assert setup.cloner.calls == []


def test_an_explicit_command_skips_the_manifest_entirely(tmp_path: Path) -> None:
    """用户接管了「怎么启动」这个判断，此时再要求清单等于把两种准入叠在一起。"""
    setup = _setup(tmp_path, manifest=_no_manifest())

    plan = setup.manager.plan_install(_REQUESTED_NAME, command=_COMMAND_JSON)

    assert plan.command == ("uv", "run", "pkg-a")
    assert plan.evidence == "explicit --command"
    assert len(setup.http.calls) == 1, "给了 --command 就不该再去读清单"


def test_an_explicit_command_installs_a_repository_that_would_otherwise_be_rejected(tmp_path: Path) -> None:
    setup = _setup(tmp_path, manifest=_no_manifest())

    plan = setup.manager.plan_install(_REQUESTED_NAME, command=_COMMAND_JSON)

    assert plan.install_path == APP_PATH
    assert setup.cloner.calls != []


def test_paths_and_package_come_from_the_api_not_from_the_user_string(tmp_path: Path) -> None:
    """GitHub 对大小写不敏感，canonical 只有 API 返回值这一个来源。"""
    setup = _setup(tmp_path)

    plan = setup.manager.plan_install("CHURK-BEN/AURORA-QQ")

    assert plan.repository == _CANONICAL
    assert plan.install_path == APP_PATH


def test_the_manifest_is_read_from_the_canonical_name(tmp_path: Path) -> None:
    """清单接口用的是 API 返回的全名：用户的写法只用来发起第一次查询。"""
    setup = _setup(tmp_path)

    setup.manager.plan_install("CHURK-BEN/AURORA-QQ")

    assert _CANONICAL in str(_contents_call(setup.http)["url"])


@pytest.mark.parametrize("name", ["weather-mcp", "example/foo/bar", "example/", "../repo"])
def test_malformed_requested_names_never_reach_the_network(tmp_path: Path, name: str) -> None:
    """输入形状不合规时连一次查询都不发：这是自己的参数写错了。"""
    setup = _setup(tmp_path)

    with pytest.raises(PlanError):
        setup.manager.plan_install(name)

    assert setup.http.calls == []
    assert setup.cloner.calls == []


def test_a_malformed_command_is_rejected_before_any_request(tmp_path: Path) -> None:
    """``--command`` 写错了就是写错了，没必要先发一次请求再报。"""
    setup = _setup(tmp_path)

    with pytest.raises(PlanError):
        setup.manager.plan_install(_REQUESTED_NAME, command="uv run weather-mcp")

    assert setup.http.calls == []
    assert setup.cloner.calls == []


def test_staging_is_cleaned_up_when_clone_fails(tmp_path: Path) -> None:
    setup = _setup(tmp_path, failure=CloneError("git clone 失败"))

    with pytest.raises(CloneError):
        setup.manager.plan_install(_REQUESTED_NAME)

    assert apps_root_entries(setup.root) == []


def test_staging_is_cleaned_up_when_the_package_conflicts(tmp_path: Path) -> None:
    setup = _setup(tmp_path, apps_toml=registry_entry("github.churk-ben.aurora-qq"))

    with pytest.raises(PlanError) as error_info:
        setup.manager.plan_install(_REQUESTED_NAME)

    assert "已存在 package" in str(error_info.value)
    assert apps_root_entries(setup.root) == []


def test_final_path_collision_is_a_preflight_before_the_clone(tmp_path: Path) -> None:
    """路径冲突不发请求、不克隆：它只取决于本地已经有什么。"""
    setup = _setup(tmp_path)
    (setup.root / "extensions" / "apps" / "Churk-Ben" / "Aurora-QQ").mkdir(parents=True)

    with pytest.raises(PlanError) as error_info:
        setup.manager.plan_install(_REQUESTED_NAME)

    assert "安装目录已存在" in str(error_info.value)
    assert setup.cloner.calls == []


@pytest.mark.parametrize("flag", ["archived", "disabled"])
def test_uninstallable_repositories_are_rejected_before_cloning(tmp_path: Path, flag: str) -> None:
    payload = repository_payload(archived=True) if flag == "archived" else repository_payload(disabled=True)
    setup = _setup(tmp_path, payload=payload)

    with pytest.raises(PlanError) as error_info:
        setup.manager.plan_install(_REQUESTED_NAME)

    assert "无法安装" in str(error_info.value)
    assert setup.cloner.calls == []
    assert not apps_root(setup.root).exists(), "准入失败发生在 preflight 之前，安装根都不该建"


def test_clone_url_mismatch_is_rejected_before_cloning(tmp_path: Path) -> None:
    setup = _setup(tmp_path, payload=repository_payload(clone_url="https://github.com/evil/other.git"))

    with pytest.raises(PlanError):
        setup.manager.plan_install(_REQUESTED_NAME)

    assert setup.cloner.calls == []


def test_a_disabled_repository_does_not_even_get_its_manifest_read(tmp_path: Path) -> None:
    """准入在最前面：连「它有没有清单」都不必问。"""
    setup = _setup(tmp_path, payload=repository_payload(disabled=True), manifest=_no_manifest())

    with pytest.raises(PlanError) as error_info:
        setup.manager.plan_install(_REQUESTED_NAME)

    assert not isinstance(error_info.value, ManifestError)
    assert len(setup.http.calls) == 1


def test_explicit_package_is_used_instead_of_the_derived_one(tmp_path: Path) -> None:
    setup = _setup(tmp_path)

    plan = setup.manager.plan_install(_REQUESTED_NAME, package="com.example.weather")

    assert plan.package == "com.example.weather"
    assert plan.install_path == APP_PATH, "目录来自 full_name，与 package 无关"


def test_an_explicit_package_conflict_is_detected_before_the_clone(tmp_path: Path) -> None:
    setup = _setup(tmp_path, apps_toml=registry_entry(CONFLICTING_PACKAGE))

    with pytest.raises(PlanError) as error_info:
        setup.manager.plan_install(_REQUESTED_NAME, package=CONFLICTING_PACKAGE)

    assert CONFLICTING_PACKAGE in str(error_info.value)
    assert setup.cloner.calls == [], "查重在 clone 之前，用户不必白等一次下载"


def test_prepare_install_keeps_the_staging_directory_alive(tmp_path: Path) -> None:
    """它与 plan_install 的唯一区别：一个交还计划后清场，一个把 staging 留在手上。"""
    setup = _setup(tmp_path)

    with setup.manager.prepare_install(_REQUESTED_NAME) as prepared:
        assert prepared.staging.root.is_dir()
        assert prepared.staging.root.name.startswith(_STAGE_MARKER)
        assert prepared.staging.root.parent == setup.root / "extensions" / "apps"

    assert not prepared.staging.root.exists()


def test_prepare_install_cleans_up_when_the_body_raises(tmp_path: Path) -> None:
    """放弃路径（用户拒绝、verify 失败）与异常路径都必须清理干净。"""
    setup = _setup(tmp_path)

    with pytest.raises(RuntimeError), setup.manager.prepare_install(_REQUESTED_NAME) as prepared:
        raise RuntimeError("用户放弃了")

    assert not prepared.staging.root.exists()
    assert apps_root_entries(setup.root) == []
