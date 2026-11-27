"""由 aurora-meta 生成；公共声明的编辑来源为同目录 plugin.meta.toml。"""

from aurora_core.components import Definition, PluginDeclaration
from aurora_core.ids import Id

CHAT = Id("org.aurora.model:adapters/litellm/chat")
CHOICE = Id("org.aurora.model:adapters/litellm/choice")
EMBEDDING = Id("org.aurora.model:adapters/litellm/embedding")

litellm_plugin = PluginDeclaration(
    name="aurora_model.litellm",
    definitions=(
        Definition(
            CHAT,
            "adapter",
            "aurora_model.litellm",
            register_to=Id("org.aurora.model:registries/adapters"),
            interface=None,
        ),
        Definition(
            CHOICE,
            "adapter",
            "aurora_model.litellm",
            register_to=Id("org.aurora.model:registries/adapters"),
            interface=None,
        ),
        Definition(
            EMBEDDING,
            "adapter",
            "aurora_model.litellm",
            register_to=Id("org.aurora.model:registries/adapters"),
            interface=None,
        ),
    ),
    requires=("aurora_model",),
    components={},
).bind
