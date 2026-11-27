"""ctx 的显式传输绑定与 JSON 信封。"""

from aurora_core._meta import CTX_CHANGED, CTX_DELETE, CTX_GET, CTX_LIST, CTX_SET, CTX_SUBSCRIBE, CTX_UNSUBSCRIBE
from aurora_core.ctx import StateAddress, StateChange

HTTP_ACTIONS = {
    "get": ("/ctx/get", CTX_GET),
    "list": ("/ctx/list", CTX_LIST),
    "set": ("/ctx/set", CTX_SET),
    "delete": ("/ctx/delete", CTX_DELETE),
}
WATCH_PATH = "/ctx/watch"
CHANGED = str(CTX_CHANGED)
SUBSCRIBE = CTX_SUBSCRIBE
UNSUBSCRIBE = CTX_UNSUBSCRIBE


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
