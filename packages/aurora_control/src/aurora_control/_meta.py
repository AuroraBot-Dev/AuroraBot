"""由 aurora-meta 生成；公共声明的编辑来源为同目录 plugin.meta.toml。"""

from aurora_core.components import ComponentDeclaration, Definition, PluginDeclaration
from aurora_core.ids import Id

CONTROL = Id("org.aurora.control:handlers/control")
CONTROL_EXECUTE = Id("org.aurora.control:handlers/control/execute")
CONTROL_CHILDREN = Id("org.aurora.control:handlers/control/children")
SERIAL = Id("org.aurora.control:handlers/control/serial")
SERIAL_EXECUTE = Id("org.aurora.control:handlers/control/serial/execute")
SERIAL_CHILDREN = Id("org.aurora.control:handlers/control/serial/children")
BRANCH = Id("org.aurora.control:handlers/control/branch")
BRANCH_EXECUTE = Id("org.aurora.control:handlers/control/branch/execute")
BRANCH_CHILDREN = Id("org.aurora.control:handlers/control/branch/children")
WHILE = Id("org.aurora.control:handlers/control/while")
WHILE_EXECUTE = Id("org.aurora.control:handlers/control/while/execute")
WHILE_CHILDREN = Id("org.aurora.control:handlers/control/while/children")
PARALLEL = Id("org.aurora.control:handlers/control/parallel")
PARALLEL_EXECUTE = Id("org.aurora.control:handlers/control/parallel/execute")
PARALLEL_CHILDREN = Id("org.aurora.control:handlers/control/parallel/children")
CONTROL_STATE = Id("org.aurora.control:state/control")

control_plugin = PluginDeclaration(
    name="aurora_control",
    definitions=(
        Definition(CONTROL, "component", "aurora_control", register_to=None, interface=None),
        Definition(
            CONTROL_EXECUTE,
            "hook_handler",
            "aurora_control",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=CONTROL,
        ),
        Definition(
            CONTROL_CHILDREN,
            "hook_slot",
            "aurora_control",
            register_to=Id("org.aurora.core:registries/hook_slots"),
            interface=None,
        ),
        Definition(SERIAL, "component", "aurora_control", register_to=None, interface=None),
        Definition(
            SERIAL_EXECUTE,
            "hook_handler",
            "aurora_control",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=SERIAL,
        ),
        Definition(
            SERIAL_CHILDREN,
            "hook_slot",
            "aurora_control",
            register_to=Id("org.aurora.core:registries/hook_slots"),
            interface=None,
        ),
        Definition(BRANCH, "component", "aurora_control", register_to=None, interface=None),
        Definition(
            BRANCH_EXECUTE,
            "hook_handler",
            "aurora_control",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=BRANCH,
        ),
        Definition(
            BRANCH_CHILDREN,
            "hook_slot",
            "aurora_control",
            register_to=Id("org.aurora.core:registries/hook_slots"),
            interface=None,
        ),
        Definition(WHILE, "component", "aurora_control", register_to=None, interface=None),
        Definition(
            WHILE_EXECUTE,
            "hook_handler",
            "aurora_control",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=WHILE,
        ),
        Definition(
            WHILE_CHILDREN,
            "hook_slot",
            "aurora_control",
            register_to=Id("org.aurora.core:registries/hook_slots"),
            interface=None,
        ),
        Definition(PARALLEL, "component", "aurora_control", register_to=None, interface=None),
        Definition(
            PARALLEL_EXECUTE,
            "hook_handler",
            "aurora_control",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=PARALLEL,
        ),
        Definition(
            PARALLEL_CHILDREN,
            "hook_slot",
            "aurora_control",
            register_to=Id("org.aurora.core:registries/hook_slots"),
            interface=None,
        ),
        Definition(
            CONTROL_STATE,
            "state_key",
            "aurora_control",
            register_to=Id("org.aurora.core:registries/state_keys"),
            interface=None,
        ),
    ),
    requires=(),
    components={
        "serial": ComponentDeclaration(
            plugs=(SERIAL_EXECUTE,),
            slots=(SERIAL_CHILDREN,),
            inject=("ctx", "hooks", "instance_id", "states", "options"),
            states=(),
            resources=(),
            inputs=(),
            options=None,
        ),
        "branch": ComponentDeclaration(
            plugs=(BRANCH_EXECUTE,),
            slots=(BRANCH_CHILDREN,),
            inject=("ctx", "hooks", "instance_id", "states", "options"),
            states=(),
            resources=(),
            inputs=("select",),
            options=None,
        ),
        "while": ComponentDeclaration(
            plugs=(WHILE_EXECUTE,),
            slots=(WHILE_CHILDREN,),
            inject=("ctx", "hooks", "instance_id", "states", "options"),
            states=(),
            resources=(),
            inputs=("condition",),
            options={
                "type": "object",
                "properties": {"max_iterations": {"type": "integer", "minimum": 1}},
                "required": ["max_iterations"],
                "additionalProperties": False,
            },
        ),
        "parallel": ComponentDeclaration(
            plugs=(PARALLEL_EXECUTE,),
            slots=(PARALLEL_CHILDREN,),
            inject=("ctx", "hooks", "instance_id", "states", "options"),
            states=(),
            resources=(),
            inputs=(),
            options={
                "type": "object",
                "properties": {"concurrency": {"type": "integer", "minimum": 1}},
                "required": ["concurrency"],
                "additionalProperties": False,
            },
        ),
    },
).bind
