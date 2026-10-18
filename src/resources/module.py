"""从模组贡献构造统一资源目录。"""

from src.contracts.pkgs.resources import RESOURCE_PROVIDERS
from src.contracts.pkgs.resources import ResourceCatalog as ResourceCatalogPort
from src.contracts.resource import RESOURCE_ALIASES, RESOURCE_CONTRIBUTIONS
from src.kernel import ModuleContext, module
from src.resources.catalog import ResourceCatalog


@module(
    name="resources",
    provides=ResourceCatalogPort,
    consumes=(RESOURCE_CONTRIBUTIONS, RESOURCE_ALIASES, RESOURCE_PROVIDERS),
    declares=(RESOURCE_CONTRIBUTIONS, RESOURCE_ALIASES, RESOURCE_PROVIDERS),
)
def build(context: ModuleContext) -> ResourceCatalogPort:
    """先读取模组静态定义，再合并依赖配置或模型状态的资源贡献。"""
    definitions = (
        *context.contributions(RESOURCE_CONTRIBUTIONS),
        *(descriptor for spec in context.modules for descriptor in spec.resources),
    )
    return ResourceCatalog(
        definitions, context.contributions(RESOURCE_ALIASES), context.contributions(RESOURCE_PROVIDERS)
    )


MODULE = build
