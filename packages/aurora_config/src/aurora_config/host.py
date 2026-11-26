"""插件宿主引导声明；CLI 读取器与显式初始化预设共用结构校验。"""

from .schema import ConfigSchema

HOST_SCHEMA = ConfigSchema(
    {
        "type": "object",
        "additionalProperties": False,
        "not": {"required": ["assembly", "assembly_file"]},
        "if": {"required": ["assembly_file"]},
        "then": {"properties": {"plugins": {"maxItems": 0}}},
        "properties": {
            "plugins": {"type": "array", "items": {"type": "string", "pattern": r"\S"}, "default": []},
            "assembly_file": {"type": "string", "minLength": 1},
            "assembly": {"type": "string", "format": "aurora-id"},
        },
    }
)
