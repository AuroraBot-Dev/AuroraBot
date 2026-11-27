"""由 aurora-meta 生成；公共声明的编辑来源为同目录 plugin.meta.toml。"""

from aurora_core.components import ComponentDeclaration, Definition, PluginDeclaration
from aurora_core.ids import Id

CONVERSATION = Id("org.aurora.bot:endpoints/conversation")

conversation_plugin = PluginDeclaration(
    name="aurora_bot.conversation",
    definitions=(
        Definition(
            CONVERSATION,
            "endpoint",
            "aurora_bot.conversation",
            register_to=Id("org.aurora.api:registries/endpoints"),
            interface=None,
        ),
    ),
    requires=("aurora_bot.runtime",),
    components={
        "endpoint": ComponentDeclaration(
            plugs=(),
            slots=(),
            inject=("registry",),
            states=(),
            resources=("endpoint",),
            inputs=("operations",),
            options=None,
        ),
    },
).bind
