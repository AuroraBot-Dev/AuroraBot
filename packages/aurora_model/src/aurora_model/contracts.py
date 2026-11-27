"""模型资源与配置的纯数据契约。"""


def profile_schema():
    return {
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
    }


def profiles_schema():
    return {"type": "object", "propertyNames": {"minLength": 1}, "additionalProperties": profile_schema()}


def resource_options():
    return {
        "oneOf": [
            profile_schema(),
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["profile"],
                "properties": {"profile": {"type": "string", "minLength": 1}},
            },
        ]
    }
