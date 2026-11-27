"""由 aurora-meta 生成；公共声明的编辑来源为同目录 plugin.meta.toml。"""

from aurora_core.components import ComponentDeclaration, Definition, PluginDeclaration
from aurora_core.ids import Id

START = Id("org.aurora.memory:handlers/compaction/start")
STOP = Id("org.aurora.memory:handlers/compaction/stop")
CLEAN = Id("org.aurora.memory:handlers/compaction/clean")

compaction_plugin = PluginDeclaration(
    name="aurora_memory.compaction",
    definitions=(
        Definition(
            START,
            "hook_handler",
            "aurora_memory.compaction",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=None,
        ),
        Definition(
            STOP,
            "hook_handler",
            "aurora_memory.compaction",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=None,
        ),
        Definition(
            CLEAN,
            "hook_handler",
            "aurora_memory.compaction",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=None,
        ),
    ),
    requires=("aurora_memory",),
    components={
        "recorder": ComponentDeclaration(
            plugs=(
                START,
                STOP,
                CLEAN,
            ),
            slots=(),
            inject=("options",),
            states=(),
            resources=("recorder",),
            inputs=("memory",),
            options={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "index_timeout_seconds": {"type": "number", "exclusiveMinimum": 0, "default": 15},
                    "retry_seconds": {"type": "number", "exclusiveMinimum": 0, "default": 60},
                },
            },
        ),
    },
).bind
