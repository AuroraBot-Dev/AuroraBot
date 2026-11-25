"""ctx 的显式传输绑定与 JSON 信封。"""

from aurora_core.ctx import StateAddress, StateChange
from aurora_core.ids import Id

HTTP_ACTIONS = {
    "get": ("/ctx/get", Id("org.aurora.core:operations/ctx/get")),
    "list": ("/ctx/list", Id("org.aurora.core:operations/ctx/list")),
    "set": ("/ctx/set", Id("org.aurora.core:operations/ctx/set")),
    "delete": ("/ctx/delete", Id("org.aurora.core:operations/ctx/delete")),
}
WATCH_PATH = "/ctx/watch"
CHANGED = "org.aurora.core:events/ctx/changed"
SUBSCRIBE = Id("org.aurora.core:operations/ctx/subscribe")
UNSUBSCRIBE = Id("org.aurora.core:operations/ctx/unsubscribe")


def address_data(address: StateAddress) -> dict[str, object]:
    return {"id": str(address.key), "location": dict(address.location)}


def change_data(change: StateChange) -> dict[str, object]:
    return {
        **address_data(change.address),
        "revision": change.revision,
        "action": change.action,
        "value": change.value,
        "previous": change.previous,
        "existed": change.existed,
    }


def error_data(code: str, message: str) -> dict[str, object]:
    return {"error": {"code": code, "message": message}}
