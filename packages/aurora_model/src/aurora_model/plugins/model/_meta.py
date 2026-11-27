"""由 aurora-meta 生成；公共声明的编辑来源为同目录 plugin.meta.toml。"""

from aurora_core.components import ComponentDeclaration, Definition, PluginDeclaration
from aurora_core.ids import Id

ADAPTERS = Id("org.aurora.model:registries/adapters")
EMBEDDING_CLIENT = Id("org.aurora.model:services/embedding_client")
CHOICE_CLIENT = Id("org.aurora.model:services/choice_client")
CHAT_CLIENT = Id("org.aurora.model:services/chat_client")
CHAT_REQUEST = Id("org.aurora.model:schemas/chat/request")
CHAT_RESPONSE = Id("org.aurora.model:schemas/chat/response")
CHAT_CHUNK = Id("org.aurora.model:schemas/chat/chunk")
CHAT_CAPABILITIES = Id("org.aurora.model:schemas/chat/capabilities")
CHAT_PREPARE = Id("org.aurora.model:handlers/chat/prepare")
CHAT_CLEAN = Id("org.aurora.model:handlers/chat/clean")
CHOICE_PREPARE = Id("org.aurora.model:handlers/choice/prepare")
CHOICE_CLEAN = Id("org.aurora.model:handlers/choice/clean")
EMBEDDING_PREPARE = Id("org.aurora.model:handlers/embedding/prepare")
EMBEDDING_CLEAN = Id("org.aurora.model:handlers/embedding/clean")

model_plugin = PluginDeclaration(
    name="aurora_model",
    definitions=(
        Definition(
            ADAPTERS,
            "registry",
            "aurora_model",
            register_to=Id("org.aurora.core:registries/registries"),
            interface=None,
        ),
        Definition(
            EMBEDDING_CLIENT,
            "service",
            "aurora_model",
            register_to=Id("org.aurora.core:registries/services"),
            interface=None,
        ),
        Definition(
            CHOICE_CLIENT,
            "service",
            "aurora_model",
            register_to=Id("org.aurora.core:registries/services"),
            interface=None,
        ),
        Definition(
            CHAT_CLIENT,
            "service",
            "aurora_model",
            register_to=Id("org.aurora.core:registries/services"),
            interface=None,
        ),
        Definition(
            CHAT_REQUEST, "schema", "aurora_model", register_to=Id("org.aurora.core:registries/schemas"), interface=None
        ),
        Definition(
            CHAT_RESPONSE,
            "schema",
            "aurora_model",
            register_to=Id("org.aurora.core:registries/schemas"),
            interface=None,
        ),
        Definition(
            CHAT_CHUNK, "schema", "aurora_model", register_to=Id("org.aurora.core:registries/schemas"), interface=None
        ),
        Definition(
            CHAT_CAPABILITIES,
            "schema",
            "aurora_model",
            register_to=Id("org.aurora.core:registries/schemas"),
            interface=None,
        ),
        Definition(
            CHAT_PREPARE,
            "hook_handler",
            "aurora_model",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=None,
        ),
        Definition(
            CHAT_CLEAN,
            "hook_handler",
            "aurora_model",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=None,
        ),
        Definition(
            CHOICE_PREPARE,
            "hook_handler",
            "aurora_model",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=None,
        ),
        Definition(
            CHOICE_CLEAN,
            "hook_handler",
            "aurora_model",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=None,
        ),
        Definition(
            EMBEDDING_PREPARE,
            "hook_handler",
            "aurora_model",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=None,
        ),
        Definition(
            EMBEDDING_CLEAN,
            "hook_handler",
            "aurora_model",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=None,
        ),
    ),
    requires=(),
    components={
        "chat": ComponentDeclaration(
            plugs=(
                CHAT_PREPARE,
                CHAT_CLEAN,
            ),
            slots=(),
            inject=("ctx", "registry", "resolve_credential", "states", "options"),
            states=(),
            resources=("model",),
            inputs=(),
            optional_inputs=("catalog",),
            optional_states=("profiles",),
            options={
                "oneOf": [
                    {
                        "type": "object",
                        "required": ["adapter", "model"],
                        "additionalProperties": False,
                        "properties": {
                            "adapter": {"type": "string", "format": "aurora-id"},
                            "model": {"type": "string", "pattern": "\\S"},
                            "base_url": {"type": "string", "pattern": "\\S"},
                            "credential": {"type": "string", "pattern": "\\S"},
                            "provider": {"type": "string", "pattern": "\\S"},
                            "thinking": {
                                "type": "object",
                                "required": ["type"],
                                "additionalProperties": False,
                                "properties": {
                                    "type": {"enum": ["enabled", "disabled"]},
                                    "budget_tokens": {"type": "integer", "minimum": 1024},
                                },
                            },
                            "reasoning_effort": {"enum": ["none", "minimal", "low", "medium", "high", "xhigh", "max"]},
                            "capabilities": {
                                "type": "object",
                                "required": ["streaming", "tool_calls"],
                                "additionalProperties": False,
                                "properties": {
                                    "streaming": {"type": "boolean"},
                                    "tool_calls": {"type": "boolean"},
                                    "file_input": {"type": "boolean"},
                                },
                            },
                        },
                    },
                    {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["profile"],
                        "properties": {"profile": {"type": "string", "minLength": 1}},
                    },
                ]
            },
        ),
        "choice": ComponentDeclaration(
            plugs=(
                CHOICE_PREPARE,
                CHOICE_CLEAN,
            ),
            slots=(),
            inject=("ctx", "registry", "resolve_credential", "states", "options"),
            states=(),
            resources=("model",),
            inputs=(),
            optional_inputs=("catalog",),
            optional_states=("profiles",),
            options={
                "oneOf": [
                    {
                        "type": "object",
                        "required": ["adapter", "model"],
                        "additionalProperties": False,
                        "properties": {
                            "adapter": {"type": "string", "format": "aurora-id"},
                            "model": {"type": "string", "pattern": "\\S"},
                            "base_url": {"type": "string", "pattern": "\\S"},
                            "credential": {"type": "string", "pattern": "\\S"},
                            "provider": {"type": "string", "pattern": "\\S"},
                            "thinking": {
                                "type": "object",
                                "required": ["type"],
                                "additionalProperties": False,
                                "properties": {
                                    "type": {"enum": ["enabled", "disabled"]},
                                    "budget_tokens": {"type": "integer", "minimum": 1024},
                                },
                            },
                            "reasoning_effort": {"enum": ["none", "minimal", "low", "medium", "high", "xhigh", "max"]},
                            "capabilities": {
                                "type": "object",
                                "required": ["streaming", "tool_calls"],
                                "additionalProperties": False,
                                "properties": {
                                    "streaming": {"type": "boolean"},
                                    "tool_calls": {"type": "boolean"},
                                    "file_input": {"type": "boolean"},
                                },
                            },
                        },
                    },
                    {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["profile"],
                        "properties": {"profile": {"type": "string", "minLength": 1}},
                    },
                ]
            },
        ),
        "embedding": ComponentDeclaration(
            plugs=(
                EMBEDDING_PREPARE,
                EMBEDDING_CLEAN,
            ),
            slots=(),
            inject=("ctx", "registry", "resolve_credential", "states", "options"),
            states=(),
            resources=("model",),
            inputs=(),
            optional_inputs=("catalog",),
            optional_states=("profiles",),
            options={
                "oneOf": [
                    {
                        "type": "object",
                        "required": ["adapter", "model"],
                        "additionalProperties": False,
                        "properties": {
                            "adapter": {"type": "string", "format": "aurora-id"},
                            "model": {"type": "string", "pattern": "\\S"},
                            "base_url": {"type": "string", "pattern": "\\S"},
                            "credential": {"type": "string", "pattern": "\\S"},
                            "provider": {"type": "string", "pattern": "\\S"},
                            "thinking": {
                                "type": "object",
                                "required": ["type"],
                                "additionalProperties": False,
                                "properties": {
                                    "type": {"enum": ["enabled", "disabled"]},
                                    "budget_tokens": {"type": "integer", "minimum": 1024},
                                },
                            },
                            "reasoning_effort": {"enum": ["none", "minimal", "low", "medium", "high", "xhigh", "max"]},
                            "capabilities": {
                                "type": "object",
                                "required": ["streaming", "tool_calls"],
                                "additionalProperties": False,
                                "properties": {
                                    "streaming": {"type": "boolean"},
                                    "tool_calls": {"type": "boolean"},
                                    "file_input": {"type": "boolean"},
                                },
                            },
                        },
                    },
                    {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["profile"],
                        "properties": {"profile": {"type": "string", "minLength": 1}},
                    },
                ]
            },
        ),
    },
).bind
