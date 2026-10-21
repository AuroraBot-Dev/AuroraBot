"""在业务资源准备前冻结有效域目录。"""

from __future__ import annotations

from aurora_bot.contracts.scope import ScopeCatalog, merge_scope_catalog
from aurora_bot.kernel import ModuleContext, Phase, PhaseKind, module

_SCOPE_DEFINITIONS = Phase("scope_definitions", 50, PhaseKind.SETUP)


async def prepare(context: ModuleContext) -> None:
    """在文件和连接创建前检查声明并登记只读目录。"""
    if not context.contains(ScopeCatalog):
        context.provide(ScopeCatalog, _create_default(context))


@module(
    name="scopes",
    provides=ScopeCatalog,
    hooks={_SCOPE_DEFINITIONS: prepare},
)
def build(context: ModuleContext) -> ScopeCatalog:
    """同步装配使用同一份合并与校验规则。"""
    catalog = context.get_optional(ScopeCatalog)
    if catalog is None:
        catalog = _create_default(context)
    return catalog


def _create_default(context: ModuleContext) -> ScopeCatalog:
    """合并可用模组的声明，校验所有拥有或观察的域。"""
    catalog = merge_scope_catalog(
        context.settings.resolve(ScopeCatalog),
        (scope for spec in context.modules for scope in spec.scopes),
    )
    patterns = (pattern for spec in context.modules for pattern in (*spec.owned_scopes, *spec.observes_scopes))
    undeclared = catalog.undeclared(patterns)
    if undeclared:
        raise ValueError(f"模块声明了未注册的域：{', '.join(undeclared)}")
    return catalog


MODULE = build
