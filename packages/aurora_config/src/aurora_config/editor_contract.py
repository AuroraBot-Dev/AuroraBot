"""配置文件编辑的显式 HTTP 契约，不包含本机绝对路径或凭证。"""


def describe_configuration() -> dict:
    def ref(name):
        return {"$ref": f"#/$defs/{name}"}

    def obj(properties):
        return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}

    text = {"type": "string"}
    identity = {"id": ref("StateId")}
    definitions = {
        "ConfigurationFile": obj({**identity, "state": ref("StateId"), "path": text}),
        "ConfigurationDocument": obj({**identity, "content": text, "revision": text}),
        "ConfigurationListRequest": obj({}),
        "ConfigurationListResponse": obj({"result": {"type": "array", "items": ref("ConfigurationFile")}}),
        "ConfigurationGetRequest": obj(identity),
        "ConfigurationGetResponse": obj({"result": ref("ConfigurationDocument")}),
        "ConfigurationSaveRequest": ref("ConfigurationDocument"),
        "ConfigurationSaveResponse": obj({"result": obj({**identity, "restart_required": {"const": True}})}),
    }
    return {
        "$defs": definitions,
        "http": {
            f"configuration{action}": {
                "method": "POST",
                "path": f"/configuration/{action.lower()}",
                "operation": None,
                "request": ref(f"Configuration{action}Request"),
                "response": ref(f"Configuration{action}Response"),
                "error": ref("ErrorResponse"),
            }
            for action in ("List", "Get", "Save")
        },
    }
