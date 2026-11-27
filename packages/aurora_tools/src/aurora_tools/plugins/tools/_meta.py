"""由 aurora-meta 生成；公共声明的编辑来源为同目录 plugin.meta.toml。"""

from aurora_core.components import ComponentDeclaration, Definition, PluginDeclaration
from aurora_core.ids import Id

TOOLS = Id("org.aurora.tools:registries/tools")
EXECUTOR = Id("org.aurora.tools:components/executor")
EXECUTE = Id("org.aurora.tools:components/executor/execute")
CHILDREN = Id("org.aurora.tools:components/executor/children")
BEFORE_CALL = Id("org.aurora.tools:executor/before_call")
AFTER_CALL = Id("org.aurora.tools:executor/after_call")
CONFIGURE = Id("org.aurora.tools:handlers/executor/configure")
COLLECT = Id("org.aurora.tools:handlers/collection/prepare")
CLEAN = Id("org.aurora.tools:handlers/collection/clean")

tools_plugin = PluginDeclaration(
    name="aurora_tools",
    definitions=(
        Definition(
            TOOLS, "registry", "aurora_tools", register_to=Id("org.aurora.core:registries/registries"), interface=None
        ),
        Definition(EXECUTOR, "component", "aurora_tools", register_to=None, interface=None),
        Definition(
            EXECUTE,
            "hook_handler",
            "aurora_tools",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=Id("org.aurora.tools:components/executor"),
        ),
        Definition(
            CHILDREN,
            "hook_slot",
            "aurora_tools",
            register_to=Id("org.aurora.core:registries/hook_slots"),
            interface=None,
        ),
        Definition(
            BEFORE_CALL,
            "hook_slot",
            "aurora_tools",
            register_to=Id("org.aurora.core:registries/hook_slots"),
            interface=None,
        ),
        Definition(
            AFTER_CALL,
            "hook_slot",
            "aurora_tools",
            register_to=Id("org.aurora.core:registries/hook_slots"),
            interface=None,
        ),
        Definition(
            CONFIGURE,
            "hook_handler",
            "aurora_tools",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=None,
        ),
        Definition(
            COLLECT,
            "hook_handler",
            "aurora_tools",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=None,
        ),
        Definition(
            CLEAN,
            "hook_handler",
            "aurora_tools",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=None,
        ),
    ),
    requires=(),
    components={
        "executor": ComponentDeclaration(
            plugs=(
                EXECUTE,
                CONFIGURE,
            ),
            slots=(
                CHILDREN,
                BEFORE_CALL,
                AFTER_CALL,
            ),
            inject=("ctx", "registry", "hooks", "instance_id", "states", "options"),
            states=("input", "output", "current"),
            resources=("executor",),
            inputs=(),
            optional_inputs=("recorder",),
            optional_states=("config",),
            options={
                "type": "object",
                "additionalProperties": False,
                "properties": {"timeout": {"type": "number", "exclusiveMinimum": 0}},
            },
        ),
        "collection": ComponentDeclaration(
            plugs=(
                COLLECT,
                CLEAN,
            ),
            slots=(),
            inject=("ctx", "registry", "storage", "instance_id", "states", "options", "publish_members"),
            states=("input", "output"),
            resources=("catalog",),
            inputs=(),
            optional_inputs=("catalog",),
            resource_maps=("tools",),
            options={
                "type": "object",
                "additionalProperties": False,
                "required": ["owner", "instance_pattern", "location_field"],
                "properties": {
                    "owner": {"type": "string", "minLength": 1},
                    "instance_pattern": {"type": "string", "minLength": 1},
                    "location_field": {"type": "string", "minLength": 1},
                    "tools": {
                        "type": "array",
                        "default": [],
                        "items": {
                            "type": "object",
                            "required": ["id"],
                            "additionalProperties": False,
                            "properties": {
                                "id": {"type": "string", "format": "aurora-id"},
                                "config": {"type": "object", "default": {}},
                            },
                        },
                    },
                    "include": {"type": "array", "default": [], "items": {"type": "string"}},
                    "exclude": {"type": "array", "default": [], "items": {"type": "string"}},
                },
            },
        ),
    },
).bind
