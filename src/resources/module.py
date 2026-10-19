"""从模组贡献构造统一资源目录。"""

from src.contracts.operation import OPERATION_CONTRIBUTIONS
from src.contracts.pkgs.resources import RESOURCE_PROVIDERS
from src.contracts.pkgs.resources import ResourceCatalog as ResourceCatalogPort
from src.contracts.resource import RESOURCE_ALIASES, RESOURCE_CONTRIBUTIONS
from src.kernel import ModuleContext, module
from src.resources.catalog import ResourceCatalog
from src.resources.queries import ResourceFindQuery, ResourceInspectQuery


@module(
    name="resources",
    provides=ResourceCatalogPort,
    requires=ResourceCatalogPort,
    contributes=OPERATION_CONTRIBUTIONS,
    resources=(ResourceFindQuery.DEFINITION.resource, ResourceInspectQuery.DEFINITION.resource),
    consumes=(RESOURCE_CONTRIBUTIONS, RESOURCE_ALIASES, RESOURCE_PROVIDERS),
    declares=(RESOURCE_CONTRIBUTIONS, RESOURCE_ALIASES, RESOURCE_PROVIDERS),
)
def build(context: ModuleContext) -> ResourceCatalogPort:
    """先读取模组静态定义，再合并依赖配置或模型状态的资源贡献。"""
    definitions = (
        *context.contributions(RESOURCE_CONTRIBUTIONS),
        *(spec.resource for spec in context.modules),
        *(descriptor for spec in context.modules for descriptor in spec.resources),
    )
    catalog = context.get_optional(ResourceCatalogPort)
    if catalog is None:
        catalog = ResourceCatalog(
            definitions, context.contributions(RESOURCE_ALIASES), context.contributions(RESOURCE_PROVIDERS)
        )
    context.contribute(OPERATION_CONTRIBUTIONS, ResourceFindQuery(catalog))
    context.contribute(OPERATION_CONTRIBUTIONS, ResourceInspectQuery(catalog))
    return catalog


MODULE = build
