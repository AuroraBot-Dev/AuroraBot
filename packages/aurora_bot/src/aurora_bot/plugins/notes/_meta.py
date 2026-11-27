"""由 aurora-meta 生成；公共声明的编辑来源为同目录 plugin.meta.toml。"""

from aurora_core.components import ComponentDeclaration, Definition, PluginDeclaration
from aurora_core.ids import Id

NOTES = Id("org.aurora.bot:state/notes")
COMPONENT = Id("org.aurora.bot:components/notes")
EXECUTE = Id("org.aurora.bot:components/notes/execute")
WRITE = Id("org.aurora.bot:tools/notes/write")
READ = Id("org.aurora.bot:tools/notes/read")
LIST = Id("org.aurora.bot:tools/notes/list")

notes_plugin = PluginDeclaration(
    name="aurora_bot.notes",
    definitions=(
        Definition(NOTES, "state_key", "aurora_bot.notes", register_to=None, interface=None),
        Definition(COMPONENT, "component", "aurora_bot.notes", register_to=None, interface=None),
        Definition(
            EXECUTE,
            "hook_handler",
            "aurora_bot.notes",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=Id("org.aurora.bot:components/notes"),
        ),
        Definition(
            WRITE, "tool", "aurora_bot.notes", register_to=Id("org.aurora.tools:registries/tools"), interface=None
        ),
        Definition(
            READ, "tool", "aurora_bot.notes", register_to=Id("org.aurora.tools:registries/tools"), interface=None
        ),
        Definition(
            LIST, "tool", "aurora_bot.notes", register_to=Id("org.aurora.tools:registries/tools"), interface=None
        ),
    ),
    requires=("aurora_tools",),
    components={
        "notes": ComponentDeclaration(
            plugs=(),
            slots=(),
            inject=("ctx", "options"),
            states=(),
            resources=("notes",),
            inputs=(),
            options={
                "type": "object",
                "additionalProperties": False,
                "required": ["owner"],
                "properties": {"owner": {"type": "string", "minLength": 1}},
            },
        ),
    },
).bind
