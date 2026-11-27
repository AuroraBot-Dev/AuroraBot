"""执行参数的纯数据契约；配置默认值与显式组件参数共用字段定义。"""


def executor():
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {"timeout": {"type": "number", "exclusiveMinimum": 0, "default": 30.0}},
    }


def executor_options():
    schema = executor()
    for field in schema["properties"].values():
        field.pop("default", None)
    return schema
