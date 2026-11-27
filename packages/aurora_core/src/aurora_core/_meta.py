"""由 aurora-meta 生成；宿主公共声明的来源为 plugin.meta.toml。"""

from aurora_core.components import Definition
from aurora_core.ids import Id

REGISTRY_DIRECTORY = Id("org.aurora.core:registries/registries")
PLUGINS = Id("org.aurora.core:registries/plugins")
OPERATIONS = Id("org.aurora.core:registries/operations")
HOOK_SLOTS = Id("org.aurora.core:registries/hook_slots")
HOOK_HANDLERS = Id("org.aurora.core:registries/hook_handlers")
RESOURCES = Id("org.aurora.core:registries/resources")
SERVICES = Id("org.aurora.core:registries/services")
SCHEMAS = Id("org.aurora.core:registries/schemas")
STATE_KEYS = Id("org.aurora.core:registries/state_keys")
EVENTS = Id("org.aurora.core:registries/events")
CONFIG = Id("org.aurora.core:lifecycle/config")
PREPARE = Id("org.aurora.core:lifecycle/prepare")
START = Id("org.aurora.core:lifecycle/start")
STOP = Id("org.aurora.core:lifecycle/stop")
CLEAN = Id("org.aurora.core:lifecycle/clean")
CTX_GET = Id("org.aurora.core:operations/ctx/get")
CTX_SET = Id("org.aurora.core:operations/ctx/set")
CTX_DELETE = Id("org.aurora.core:operations/ctx/delete")
CTX_LIST = Id("org.aurora.core:operations/ctx/list")
CTX_SUBSCRIBE = Id("org.aurora.core:operations/ctx/subscribe")
CTX_UNSUBSCRIBE = Id("org.aurora.core:operations/ctx/unsubscribe")
CTX_CHANGED = Id("org.aurora.core:events/ctx/changed")

HOST_DEFINITIONS = {
    REGISTRY_DIRECTORY: Definition(REGISTRY_DIRECTORY, "registry", "aurora_core", register_to=None),
    PLUGINS: Definition(PLUGINS, "registry", "aurora_core", register_to=Id("org.aurora.core:registries/registries")),
    OPERATIONS: Definition(
        OPERATIONS, "registry", "aurora_core", register_to=Id("org.aurora.core:registries/registries")
    ),
    HOOK_SLOTS: Definition(
        HOOK_SLOTS, "registry", "aurora_core", register_to=Id("org.aurora.core:registries/registries")
    ),
    HOOK_HANDLERS: Definition(
        HOOK_HANDLERS, "registry", "aurora_core", register_to=Id("org.aurora.core:registries/registries")
    ),
    RESOURCES: Definition(
        RESOURCES, "registry", "aurora_core", register_to=Id("org.aurora.core:registries/registries")
    ),
    SERVICES: Definition(SERVICES, "registry", "aurora_core", register_to=Id("org.aurora.core:registries/registries")),
    SCHEMAS: Definition(SCHEMAS, "registry", "aurora_core", register_to=Id("org.aurora.core:registries/registries")),
    STATE_KEYS: Definition(
        STATE_KEYS, "registry", "aurora_core", register_to=Id("org.aurora.core:registries/registries")
    ),
    EVENTS: Definition(EVENTS, "registry", "aurora_core", register_to=Id("org.aurora.core:registries/registries")),
    CONFIG: Definition(CONFIG, "hook_slot", "aurora_core", register_to=Id("org.aurora.core:registries/hook_slots")),
    PREPARE: Definition(PREPARE, "hook_slot", "aurora_core", register_to=Id("org.aurora.core:registries/hook_slots")),
    START: Definition(START, "hook_slot", "aurora_core", register_to=Id("org.aurora.core:registries/hook_slots")),
    STOP: Definition(STOP, "hook_slot", "aurora_core", register_to=Id("org.aurora.core:registries/hook_slots")),
    CLEAN: Definition(CLEAN, "hook_slot", "aurora_core", register_to=Id("org.aurora.core:registries/hook_slots")),
    CTX_GET: Definition(CTX_GET, "operation", "aurora_core", register_to=Id("org.aurora.core:registries/operations")),
    CTX_SET: Definition(CTX_SET, "operation", "aurora_core", register_to=Id("org.aurora.core:registries/operations")),
    CTX_DELETE: Definition(
        CTX_DELETE, "operation", "aurora_core", register_to=Id("org.aurora.core:registries/operations")
    ),
    CTX_LIST: Definition(CTX_LIST, "operation", "aurora_core", register_to=Id("org.aurora.core:registries/operations")),
    CTX_SUBSCRIBE: Definition(
        CTX_SUBSCRIBE, "operation", "aurora_core", register_to=Id("org.aurora.core:registries/operations")
    ),
    CTX_UNSUBSCRIBE: Definition(
        CTX_UNSUBSCRIBE, "operation", "aurora_core", register_to=Id("org.aurora.core:registries/operations")
    ),
    CTX_CHANGED: Definition(CTX_CHANGED, "event", "aurora_core", register_to=Id("org.aurora.core:registries/events")),
}
