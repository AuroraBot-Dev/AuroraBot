"""域注册表：所有者、种类、语义，以及它与真实运行时域的一致性。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import cast

import pytest

from aurora_bot.cadence import CADENCE_SCOPE
from aurora_bot.console.events import CONSOLE_SCOPE
from aurora_bot.contracts import ScopeCatalog, ScopeDeclaration, ScopeKind, ToolCall, ToolOutput, ToolStatus
from aurora_bot.contracts.scope import merge_scope_catalog
from aurora_bot.contracts.tree_lifecycle import tree_scope
from aurora_bot.kernel import BuiltinSource, ModuleSpec
from aurora_bot.mcp.scopes import mcp_scope
from aurora_bot.runtime.assembly import declared_scopes, validate_declared_scopes
from aurora_bot.runtime.events import RUNTIME_SCOPE
from aurora_bot.tools import WORLD_SCOPES_TOOL, WorldScopesTool
from aurora_cli.configs import initialize_configs
from aurora_cli.configs.scopes import CONFIG_SPEC as SCOPES_CONFIG
from aurora_cli.configurator import assemble_config

_EXPECTED_OWNED_SCOPES = (
    "*:world",
    "*:world/*",
    "*:world/bot/*",
    "*:world/bot/*/cadence",
    "*:world/bot/*/memory",
    "*:world/bot/*/operations",
    "aurora:run/*",
    "aurora:run/memory-model/*",
    "aurora:world/console",
    "aurora:world/runtime",
)

_TEMPLATE = (
    ScopeDeclaration("aurora:world/console", ScopeKind.RESOURCE, "终端输入先进入的世界线"),
    ScopeDeclaration("aurora:world/cadence", ScopeKind.RESOURCE, "节律决策"),
    ScopeDeclaration("*:world", ScopeKind.RESOURCE, "扩展拥有的世界域"),
    ScopeDeclaration("*:world/*", ScopeKind.RESOURCE, "扩展世界域的子域"),
    ScopeDeclaration("aurora:run/*", ScopeKind.RUN, "一次运行的因果台账"),
)
_TEMPLATE_COUNT = len(_TEMPLATE)
_TEMPLATE_RESOURCE_COUNT = sum(1 for item in _TEMPLATE if item.kind is ScopeKind.RESOURCE)


def _catalog(*declarations: ScopeDeclaration) -> ScopeCatalog:
    return ScopeCatalog(declarations or _TEMPLATE)


def test_owner_is_derived_from_the_pattern_namespace() -> None:
    assert ScopeDeclaration("aurora:world/console", ScopeKind.RESOURCE, "说明").owner == "aurora"
    assert ScopeDeclaration("org.aurora.qq:world", ScopeKind.RESOURCE, "说明").owner == "org.aurora.qq"


def test_declaration_matches_exact_names_and_one_wildcard_family() -> None:
    tree = ScopeDeclaration("aurora:run/*", ScopeKind.RUN, "台账")

    assert tree.matches("aurora:run/abc")
    assert not tree.matches("aurora:run/")
    assert not tree.matches("aurora:run")
    assert not tree.matches("aurora:runs/abc")

    exact = ScopeDeclaration("aurora:world/console", ScopeKind.RESOURCE, "说明")
    assert exact.matches("aurora:world/console")
    assert not exact.matches("aurora:world/console:extra")


def test_middle_wildcards_classify_real_bot_subdomains_without_overmatching() -> None:
    """实际 Bot 身份填入后仍能匹配具体域声明，邻近域不会被误分类。"""
    catalog = _catalog(
        ScopeDeclaration("*:world/bot/*/operations", ScopeKind.RUN, "操作回执台账"),
        ScopeDeclaration("*:world/bot/*/cadence", ScopeKind.RESOURCE, "主体节律"),
        ScopeDeclaration("*:world/*", ScopeKind.RESOURCE, "世界域"),
    )
    assert catalog.classify("aurora:world/bot/default/operations") is ScopeKind.RUN
    assert catalog.classify("home:world/bot/family/alice/operations") is ScopeKind.RUN
    assert catalog.describe("home:world/bot/alice/cadence") == "主体节律"
    assert catalog.classify("home:world/bot/alice/operations-archive") is ScopeKind.RESOURCE
    declaration = catalog.declarations[0]
    assert not declaration.matches("home:world/bot//operations")
    assert not declaration.matches(":world/bot/alice/operations")
    assert not declaration.matches("home:other:world/bot/alice/operations")


def test_scope_wildcards_keep_other_characters_literal() -> None:
    """域路径的方括号不表示字符集合，命名空间不做局部模糊匹配。"""
    declaration = ScopeDeclaration("home:world/[room]/*", ScopeKind.RESOURCE, "明确房间")
    assert declaration.matches("home:world/[room]/lamp")
    assert not declaration.matches("home:world/r/lamp")
    assert not declaration.matches("other:world/[room]/lamp")
    with pytest.raises(ValueError, match="完整名称或"):
        ScopeDeclaration("home*:world", ScopeKind.RESOURCE, "模糊归属")


@pytest.mark.parametrize(
    "declaration",
    [
        ("console", ScopeKind.RESOURCE, "说明"),
        ("aurora:world/console ", ScopeKind.RESOURCE, "说明"),
        ("aurora:world/console", "resource", "说明"),
        ("aurora:world/console", ScopeKind.RESOURCE, "   "),
    ],
)
def test_declaration_rejects_malformed_input(declaration: tuple[str, object, str]) -> None:
    pattern, kind, description = declaration
    with pytest.raises(ValueError):
        ScopeDeclaration(pattern, kind, description)  # type: ignore[arg-type]


def test_catalog_first_matching_declaration_wins() -> None:
    catalog = _catalog(
        ScopeDeclaration("aurora:run/special", ScopeKind.RESOURCE, "特例"),
        ScopeDeclaration("aurora:run/*", ScopeKind.RUN, "台账"),
    )

    assert catalog.classify("aurora:run/special") is ScopeKind.RESOURCE
    assert catalog.classify("aurora:run/other") is ScopeKind.RUN
    assert catalog.describe("aurora:run/special") == "特例"


def test_catalog_reports_undeclared_and_unknown_scopes() -> None:
    catalog = _catalog()

    assert catalog.classify("aurora:nowhere") is None
    assert catalog.describe("aurora:nowhere") is None
    assert catalog.undeclared(("aurora:world/console", "aurora:nowhere", "aurora:other")) == (
        "aurora:nowhere",
        "aurora:other",
    )


def test_catalog_groups_declarations_by_kind_and_owner() -> None:
    catalog = _catalog()

    assert catalog.owners == {"aurora"}
    assert [item.pattern for item in catalog.of_kind(ScopeKind.RUN)] == ["aurora:run/*"]
    assert len(catalog.of_kind(ScopeKind.RESOURCE)) == _TEMPLATE_RESOURCE_COUNT


def test_duplicate_patterns_are_rejected() -> None:
    with pytest.raises(ValueError, match="域模式重复声明"):
        _catalog(
            ScopeDeclaration("aurora:world/console", ScopeKind.RESOURCE, "一"),
            ScopeDeclaration("aurora:world/console", ScopeKind.RUN, "二"),
        )


def test_template_declares_every_scope_the_runtime_produces(tmp_path: Path) -> None:
    """域注册表的意义在于它是封闭且可校验的：代码产生的每个域都必须被声明覆盖。"""
    initialize_configs(tmp_path)
    configured = assemble_config(tmp_path, (SCOPES_CONFIG,)).get(SCOPES_CONFIG)
    catalog = merge_scope_catalog(configured, (scope for spec in BuiltinSource().discover() for scope in spec.scopes))

    produced = (
        CONSOLE_SCOPE,
        RUNTIME_SCOPE,
        CADENCE_SCOPE,
        mcp_scope("org.aurora.qq"),
        tree_scope("6f1c"),
    )

    assert catalog.undeclared(produced) == ()
    assert catalog.classify(CONSOLE_SCOPE) is ScopeKind.RESOURCE
    assert catalog.classify(CADENCE_SCOPE) is ScopeKind.RESOURCE
    assert catalog.classify(mcp_scope("org.aurora.qq")) is ScopeKind.RESOURCE
    assert catalog.classify(tree_scope("6f1c")) is ScopeKind.RUN


def test_template_descriptions_are_model_readable(tmp_path: Path) -> None:
    initialize_configs(tmp_path)
    configured = assemble_config(tmp_path, (SCOPES_CONFIG,)).get(SCOPES_CONFIG)
    catalog = merge_scope_catalog(configured, (scope for spec in BuiltinSource().discover() for scope in spec.scopes))

    assert all(item.description.strip() for item in catalog.declarations)
    assert all(item.owner for item in catalog.declarations)
    assert {item.kind for item in catalog.declarations} == {ScopeKind.RESOURCE, ScopeKind.RUN}


def test_scopes_tool_lists_the_registry_for_the_model() -> None:
    tool = WorldScopesTool(_catalog())

    assert tool.definition.name == WORLD_SCOPES_TOOL
    assert tool.resolve_scopes(ToolCall("c1", WORLD_SCOPES_TOOL)).observe == frozenset()


def test_scopes_tool_returns_owners_kinds_and_descriptions() -> None:
    result = asyncio.run(WorldScopesTool(_catalog()).execute(ToolCall("c1", WORLD_SCOPES_TOOL)))

    assert isinstance(result, ToolOutput)
    payload = json.loads(result.content)
    assert payload["count"] == _TEMPLATE_COUNT
    assert payload["owners"] == ["aurora"]
    assert [item["kind"] for item in payload["scopes"]] == [
        "resource",
        "resource",
        "resource",
        "resource",
        "run",
    ]
    assert all(item["description"] for item in payload["scopes"])


def test_scopes_tool_filters_by_kind_and_rejects_unknown_kinds() -> None:
    tool = WorldScopesTool(_catalog())

    filtered = asyncio.run(tool.execute(ToolCall("c1", WORLD_SCOPES_TOOL, {"kind": "run"})))
    assert isinstance(filtered, ToolOutput)
    assert [item["pattern"] for item in json.loads(filtered.content)["scopes"]] == ["aurora:run/*"]

    rejected = asyncio.run(tool.execute(ToolCall("c2", WORLD_SCOPES_TOOL, {"kind": "vendor"})))
    assert isinstance(rejected, ToolOutput)
    assert rejected.status is ToolStatus.FAILED


class _Settings:
    """只回答域注册表的最小设置端口。"""

    def __init__(self, catalog: ScopeCatalog) -> None:
        self._catalog = catalog

    @property
    def project_root(self) -> Path:
        return Path()

    def resolve[T](self, config_type: type[T]) -> T:
        assert config_type is ScopeCatalog
        return cast("T", self._catalog)


def test_builtin_modules_own_exactly_the_domains_the_registry_declares(tmp_path: Path) -> None:
    """每个产出域的模块都要声明它拥有的域，且这些域必须被注册表覆盖。"""
    initialize_configs(tmp_path)
    configured = assemble_config(tmp_path, (SCOPES_CONFIG,)).get(SCOPES_CONFIG)
    catalog = merge_scope_catalog(configured, (scope for spec in BuiltinSource().discover() for scope in spec.scopes))
    specs = tuple(BuiltinSource().discover())

    owns, observes = declared_scopes(specs)

    assert owns == _EXPECTED_OWNED_SCOPES
    assert observes == ()
    validate_declared_scopes(_Settings(catalog), specs)


def test_module_declaring_an_unregistered_domain_fails_before_startup() -> None:
    spec = ModuleSpec(name="ghost", provides=(object,), owns_scopes=("aurora:ghost",))

    with pytest.raises(ValueError, match="未注册的域：aurora:ghost"):
        validate_declared_scopes(_Settings(_catalog()), (spec,))


def test_module_can_declare_the_domains_it_observes() -> None:
    spec = ModuleSpec(name="watcher", provides=(object,), observes_scopes=("*:world",))

    validate_declared_scopes(_Settings(_catalog()), (spec,))
    assert declared_scopes((spec,)) == ((), ("*:world",))


def test_module_spec_rejects_blank_and_duplicated_domain_declarations() -> None:
    with pytest.raises(ValueError, match="非空且无首尾空白"):
        ModuleSpec(name="blank", provides=(object,), owns_scopes=(" ",))
    with pytest.raises(ValueError, match="重复声明域"):
        ModuleSpec(
            name="twice",
            provides=(object,),
            owns_scopes=("aurora:world/console",),
            observes_scopes=("aurora:world/console",),
        )
