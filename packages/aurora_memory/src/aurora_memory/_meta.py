"""由 aurora-meta 生成；公共声明的编辑来源为同目录 plugin.meta.toml。"""

from aurora_core.components import ComponentDeclaration, Definition, PluginDeclaration
from aurora_core.ids import Id

CONFIGURATION = Id("org.aurora.memory:configs/default")
CONFIG = Id("org.aurora.memory:state/config")
COMPONENT = Id("org.aurora.memory:components/tool")
STORE = Id("org.aurora.memory:components/store")
PREPARE = Id("org.aurora.memory:handlers/store/prepare")
CLEAN = Id("org.aurora.memory:handlers/store/clean")
EXECUTE = Id("org.aurora.memory:components/tool/execute")
WRITE = Id("org.aurora.memory:tools/write")
SEARCH = Id("org.aurora.memory:tools/search")
READ = Id("org.aurora.memory:tools/read")
DELETE = Id("org.aurora.memory:tools/delete")
REINDEX = Id("org.aurora.memory:tools/reindex")

memory_plugin = PluginDeclaration(
    name="aurora_memory",
    definitions=(
        Definition(
            CONFIGURATION,
            "config",
            "aurora_memory",
            register_to=Id("org.aurora.config:registries/configs"),
            interface=None,
        ),
        Definition(CONFIG, "state_key", "aurora_memory", register_to=None, interface=None),
        Definition(COMPONENT, "component", "aurora_memory", register_to=None, interface=None),
        Definition(STORE, "component", "aurora_memory", register_to=None, interface=None),
        Definition(
            PREPARE,
            "hook_handler",
            "aurora_memory",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=None,
        ),
        Definition(
            CLEAN,
            "hook_handler",
            "aurora_memory",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=None,
        ),
        Definition(
            EXECUTE,
            "hook_handler",
            "aurora_memory",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=COMPONENT,
        ),
        Definition(WRITE, "tool", "aurora_memory", register_to=Id("org.aurora.tools:registries/tools"), interface=None),
        Definition(
            SEARCH, "tool", "aurora_memory", register_to=Id("org.aurora.tools:registries/tools"), interface=None
        ),
        Definition(READ, "tool", "aurora_memory", register_to=Id("org.aurora.tools:registries/tools"), interface=None),
        Definition(
            DELETE, "tool", "aurora_memory", register_to=Id("org.aurora.tools:registries/tools"), interface=None
        ),
        Definition(
            REINDEX, "tool", "aurora_memory", register_to=Id("org.aurora.tools:registries/tools"), interface=None
        ),
    ),
    requires=("aurora_config", "aurora_tools"),
    components={
        "store": ComponentDeclaration(
            plugs=(
                PREPARE,
                CLEAN,
            ),
            slots=(),
            inject=("ctx", "storage", "instance_id", "states", "options"),
            states=("config",),
            resources=("memory",),
            inputs=("embedding",),
            options={
                "type": "object",
                "additionalProperties": False,
                "required": ["owner"],
                "properties": {"owner": {"type": "string", "minLength": 1}},
            },
        ),
        "tool": ComponentDeclaration(
            plugs=(
                PREPARE,
                CLEAN,
                EXECUTE,
            ),
            slots=(),
            inject=("ctx", "storage", "instance_id", "states", "options"),
            states=("config", "input", "output"),
            resources=(),
            inputs=("embedding",),
            options={
                "type": "object",
                "additionalProperties": False,
                "required": ["owner", "action"],
                "properties": {
                    "owner": {"type": "string", "minLength": 1},
                    "action": {"enum": ["write", "search", "read", "delete", "reindex"]},
                },
            },
        ),
    },
).bind
