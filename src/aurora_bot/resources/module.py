"""从模组贡献构造统一资源目录。"""

from __future__ import annotations

from aurora_bot.contracts.operation import OPERATION_CONTRIBUTIONS
from aurora_bot.contracts.pkgs.resources import RESOURCE_PROVIDERS
from aurora_bot.contracts.pkgs.resources import ResourceCatalog as ResourceCatalogPort
from aurora_bot.contracts.resource import RESOURCE_ALIASES, RESOURCE_CONTRIBUTIONS
from aurora_bot.kernel import ModuleContext, module
from aurora_bot.resources.catalog import ResourceCatalog
from aurora_bot.resources.queries import ResourceFindQuery, ResourceInspectQuery


@module(
    name="resources",
    provides=ResourceCatalogPort,
    requires=ResourceCatalogPort,
    contributes=OPERATION_CONTRIBUTIONS,
    consumes=(RESOURCE_CONTRIBUTIONS, RESOURCE_ALIASES, RESOURCE_PROVIDERS),
    declares=(RESOURCE_CONTRIBUTIONS, RESOURCE_ALIASES, RESOURCE_PROVIDERS),
    resources=(ResourceFindQuery.definition.resource, ResourceInspectQuery.definition.resource),
)
def build(context: ModuleContext) -> ResourceCatalogPort:
    """先读取模组静态定义，再合并依赖配置或模型状态的资源贡献。"""
    catalog = context.get_optional(ResourceCatalogPort)
    if catalog is None:
        definitions = (
            *context.contributions(RESOURCE_CONTRIBUTIONS),
            *(spec.resource for spec in context.modules),
            *(descriptor for spec in context.modules for descriptor in spec.resources),
        )
        catalog = ResourceCatalog(
            definitions, context.contributions(RESOURCE_ALIASES), context.contributions(RESOURCE_PROVIDERS)
        )
    context.contribute(OPERATION_CONTRIBUTIONS, ResourceFindQuery(catalog))
    context.contribute(OPERATION_CONTRIBUTIONS, ResourceInspectQuery(catalog))
    return catalog


MODULE = build
