"""节律和决策行为的纯参数契约。"""


def schema():
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "decision": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "active_seconds": {"type": "number", "minimum": 1, "default": 5.0},
                    "idle_seconds": {"type": "number", "minimum": 1, "default": 180.0},
                    "half_life_seconds": {"type": "number", "minimum": 1, "default": 60.0},
                    "jitter_ratio": {"type": "number", "minimum": 0, "maximum": 0.5, "default": 0.2},
                    "timeout_seconds": {"type": "number", "exclusiveMinimum": 0, "default": 15.0},
                    "max_chars": {"type": "integer", "minimum": 4096, "maximum": 128000, "default": 12000},
                },
            },
        },
    }
