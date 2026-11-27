"""由 aurora-meta 生成；公共声明的编辑来源为同目录 plugin.meta.toml。"""

from aurora_core.components import Definition, PluginDeclaration
from aurora_core.ids import Id

ENDPOINTS = Id("org.aurora.api:registries/endpoints")

api_plugin = PluginDeclaration(
    name="aurora_api",
    definitions=(
        Definition(
            ENDPOINTS, "registry", "aurora_api", register_to=Id("org.aurora.core:registries/registries"), interface=None
        ),
    ),
    requires=(),
    components={},
).bind
