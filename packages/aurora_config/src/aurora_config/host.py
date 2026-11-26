"""插件宿主引导声明；CLI 读取器与显式初始化预设共用结构校验。"""

from .schema import ConfigSchema

HOST_SCHEMA = ConfigSchema(
    {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "plugins": {"type": "array", "items": {"type": "string", "pattern": r"\S"}, "default": []},
            "assembly": {"type": "string", "format": "aurora-id"},
        },
    }
)
