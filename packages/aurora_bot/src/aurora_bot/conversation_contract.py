"""直接交流的显式 JSON 契约；导出不创建资源或加载传输实现。"""

from .attachments import MEDIA_TYPES


def describe_conversation() -> dict:
    def ref(name):
        return {"$ref": f"#/$defs/{name}"}

    def obj(properties):
        return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}

    identity = {"type": "string", "minLength": 1, "maxLength": 256, "pattern": r"\S"}
    scope = {"session_id": identity, "instance_id": identity}
    message = {**scope, "request_id": identity}
    run = {**scope, "run_id": identity}
    receipt = {
        **message,
        "guidance_id": identity,
        "sequence": {"type": "integer", "minimum": 1},
        "run_id": identity,
        "accepted": {"const": True},
    }
    definitions = {
        "ConversationAttachment": obj(
            {
                "name": {"type": "string", "minLength": 1, "maxLength": 256},
                "media_type": {"enum": list(MEDIA_TYPES)},
                "data": {"type": "string", "minLength": 1, "maxLength": 13981016},
            }
        ),
        "ConversationInfoRequest": obj({}),
        "ConversationInfoResponse": obj(
            {"result": obj({"session_id": identity, "instance_ids": {"type": "array", "items": identity}})}
        ),
        "ConversationSubmitRequest": obj({**message, "text": {"type": "string", "maxLength": 65536}}),
        "ConversationSubmitResponse": obj({"result": ref("ConversationReceipt")}),
        "ConversationQueryRequest": obj(message),
        "ConversationQueryResponse": obj(
            {
                "result": obj(
                    {
                        **receipt,
                        "run_status": {"enum": ["pending", "completed", "cancelled", "failed"]},
                        "error": {"anyOf": [{"type": "null"}, {"type": "string"}]},
                    }
                )
            }
        ),
        "ConversationCancelRequest": obj(run),
        "ConversationCancelResponse": obj({"result": obj({**run, "cancelled": {"type": "boolean"}})}),
        "ConversationReceipt": obj(receipt),
    }
    definitions["ConversationSubmitRequest"]["properties"]["files"] = {
        "type": "array",
        "maxItems": 8,
        "items": ref("ConversationAttachment"),
    }
    return {
        "$defs": definitions,
        "http": {
            f"conversation{action}": {
                "method": "POST",
                "path": f"/conversation/{action.lower()}",
                "operation": f"org.aurora.bot:operations/run/{operation}" if operation else None,
                "request": ref(f"Conversation{action}Request"),
                "response": ref(f"Conversation{action}Response"),
                "error": ref("ErrorResponse"),
                **({"max_body_bytes": 15 * 1024 * 1024} if action == "Submit" else {}),
            }
            for action, operation in (("Info", None), ("Submit", "submit"), ("Query", None), ("Cancel", "cancel"))
        },
    }
