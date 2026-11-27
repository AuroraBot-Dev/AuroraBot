"""由 aurora-meta 生成；公共声明的编辑来源为同目录 plugin.meta.toml。"""

from aurora_core.components import ComponentDeclaration, Definition, PluginDeclaration
from aurora_core.ids import Id

SOURCE_STATUS = Id("org.aurora.world:state/sources")
SOURCES = Id("org.aurora.world:registries/sources")
SOURCES_PREPARE = Id("org.aurora.world:handlers/sources/prepare")
SOURCES_START = Id("org.aurora.world:handlers/sources/start")
SOURCES_STOP = Id("org.aurora.world:handlers/sources/stop")
SOURCES_CLEAN = Id("org.aurora.world:handlers/sources/clean")

sources_plugin = PluginDeclaration(
    name="aurora_world.sources",
    definitions=(
        Definition(SOURCE_STATUS, "state_key", "aurora_world.sources", register_to=None, interface=None),
        Definition(
            SOURCES,
            "registry",
            "aurora_world.sources",
            register_to=Id("org.aurora.core:registries/registries"),
            interface=None,
        ),
        Definition(
            SOURCES_PREPARE,
            "hook_handler",
            "aurora_world.sources",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=None,
        ),
        Definition(
            SOURCES_START,
            "hook_handler",
            "aurora_world.sources",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=None,
        ),
        Definition(
            SOURCES_STOP,
            "hook_handler",
            "aurora_world.sources",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=None,
        ),
        Definition(
            SOURCES_CLEAN,
            "hook_handler",
            "aurora_world.sources",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=None,
        ),
    ),
    requires=("aurora_world.records",),
    components={
        "sources": ComponentDeclaration(
            plugs=(
                SOURCES_PREPARE,
                SOURCES_START,
                SOURCES_STOP,
                SOURCES_CLEAN,
            ),
            slots=(),
            inject=("ctx", "instance_id"),
            states=(),
            resources=("sources",),
            inputs=("records",),
            options=None,
        ),
    },
).bind
