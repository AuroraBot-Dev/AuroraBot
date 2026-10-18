"""从模组贡献构造统一资源目录。"""

from src.contracts.operation import OPERATION_CONTRIBUTIONS
from src.contracts.pkgs.resources import ResourceCatalog as ResourceCatalogPort
from src.contracts.resource import RESOURCE_ALIASES, RESOURCE_CONTRIBUTIONS
from src.kernel import ModuleContext, module
from src.resources.catalog import ResourceCatalog


@module(
    name="resources",
    provides=ResourceCatalogPort,
    consumes=(RESOURCE_CONTRIBUTIONS, RESOURCE_ALIASES, OPERATION_CONTRIBUTIONS),
    declares=(RESOURCE_CONTRIBUTIONS, RESOURCE_ALIASES),
)
def build(context: ModuleContext) -> ResourceCatalogPort:
    """操作定义自动进入发现目录，其余资源由所属模组声明。"""
    operations = context.contributions(OPERATION_CONTRIBUTIONS)
    definitions = (
        *context.contributions(RESOURCE_CONTRIBUTIONS),
        *(operation.definition.resource for operation in operations),
    )
    return ResourceCatalog(definitions, context.contributions(RESOURCE_ALIASES))


MODULE = build
