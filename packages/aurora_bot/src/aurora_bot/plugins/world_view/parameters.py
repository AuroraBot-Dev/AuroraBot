"""世界视图与归档读取的纯参数契约。"""


def schema():
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "max_chars": {"type": "integer", "minimum": 1024, "maximum": 128000, "default": 12000},
            "archive_max_chars": {"type": "integer", "minimum": 1024, "maximum": 32000, "default": 8000},
            "events": {"type": "boolean", "default": True},
            "environment": {"type": "boolean", "default": True},
            "notes": {"type": "boolean", "default": True},
            "actions": {"type": "boolean", "default": True},
        },
    }


def options():
    value = schema()
    for field in value["properties"].values():
        field.pop("default", None)
    return value
