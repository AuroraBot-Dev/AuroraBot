"""由 aurora-meta 生成；公共声明的编辑来源为同目录 plugin.meta.toml。"""

from aurora_core.components import ComponentDeclaration, Definition, PluginDeclaration
from aurora_core.ids import Id

RECORDS = Id("org.aurora.world:state/records")
ENVIRONMENT = Id("org.aurora.world:state/environment")
RECORDS_PREPARE = Id("org.aurora.world:handlers/records/prepare")
RECORDS_START = Id("org.aurora.world:handlers/records/start")
RECORDS_STOP = Id("org.aurora.world:handlers/records/stop")
RECORDS_CLEAN = Id("org.aurora.world:handlers/records/clean")

records_plugin = PluginDeclaration(
    name="aurora_world.records",
    definitions=(
        Definition(RECORDS, "state_key", "aurora_world.records", register_to=None, interface=None),
        Definition(ENVIRONMENT, "state_key", "aurora_world.records", register_to=None, interface=None),
        Definition(
            RECORDS_PREPARE,
            "hook_handler",
            "aurora_world.records",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=None,
        ),
        Definition(
            RECORDS_START,
            "hook_handler",
            "aurora_world.records",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=None,
        ),
        Definition(
            RECORDS_STOP,
            "hook_handler",
            "aurora_world.records",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=None,
        ),
        Definition(
            RECORDS_CLEAN,
            "hook_handler",
            "aurora_world.records",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=None,
        ),
    ),
    requires=(),
    components={
        "records": ComponentDeclaration(
            plugs=(
                RECORDS_PREPARE,
                RECORDS_START,
                RECORDS_STOP,
                RECORDS_CLEAN,
            ),
            slots=(),
            inject=("ctx", "storage"),
            states=(),
            resources=("records",),
            inputs=(),
            options=None,
        ),
    },
).bind
