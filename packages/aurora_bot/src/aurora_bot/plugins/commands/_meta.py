"""由 aurora-meta 生成；公共声明的编辑来源为同目录 plugin.meta.toml。"""

from aurora_core.components import Definition, PluginDeclaration
from aurora_core.ids import Id

SUBMIT = Id("org.aurora.bot:commands/run/submit")
ACTIVATE = Id("org.aurora.bot:commands/run/activate")
CANCEL = Id("org.aurora.bot:commands/run/cancel")

commands_plugin = PluginDeclaration(
    name="aurora_bot.commands",
    definitions=(
        Definition(
            SUBMIT,
            "command",
            "aurora_bot.commands",
            register_to=Id("org.aurora.cli:registries/commands"),
            interface=None,
        ),
        Definition(
            ACTIVATE,
            "command",
            "aurora_bot.commands",
            register_to=Id("org.aurora.cli:registries/commands"),
            interface=None,
        ),
        Definition(
            CANCEL,
            "command",
            "aurora_bot.commands",
            register_to=Id("org.aurora.cli:registries/commands"),
            interface=None,
        ),
    ),
    requires=("aurora_bot.runtime",),
    components={},
).bind
