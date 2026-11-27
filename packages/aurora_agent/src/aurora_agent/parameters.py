"""执行参数的纯数据契约；配置默认值与显式组件参数共用字段定义。"""


def react():
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {"max_iterations": {"type": "integer", "minimum": 1}},
    }


def react_options():
    schema = react()
    for field in schema["properties"].values():
        field.pop("default", None)
    return schema


def model_call():
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {"streaming": {"type": "boolean", "default": True}},
    }


def model_call_options():
    schema = model_call()
    for field in schema["properties"].values():
        field.pop("default", None)
    return schema


def react_defaults():
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {"system_prompt": {"type": "string", "default": ""}},
    }


def react_defaults_options():
    schema = react_defaults()
    for field in schema["properties"].values():
        field.pop("default", None)
    return schema


def input_budget():
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {"max_chars": {"type": "integer", "minimum": 1024, "default": 128000}},
    }


def input_budget_options():
    schema = input_budget()
    for field in schema["properties"].values():
        field.pop("default", None)
    return schema


def compaction():
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "tool_result_chars": {"type": "integer", "minimum": 2048, "maximum": 32000, "default": 6000},
            "summary_chars": {"type": "integer", "minimum": 256, "maximum": 16000, "default": 6000},
            "timeout_seconds": {"type": "number", "exclusiveMinimum": 0, "default": 60.0},
        },
    }


def compaction_options():
    schema = compaction()
    for field in schema["properties"].values():
        field.pop("default", None)
    return schema
