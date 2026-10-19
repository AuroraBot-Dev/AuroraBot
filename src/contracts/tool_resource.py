"""模型工具定义使用可直接解析的原生资源身份。"""

from src.contracts.resource import ResourceKey


def tool_resource_key(name: str) -> ResourceKey:
    """工具定义与工具标签属于不同类别，不能相互冒充。"""
    try:
        key = ResourceKey.parse(name)
        if key.domain == "tool" and key.kind == "definition":
            return key
    except ValueError as error:
        raise ValueError(f"工具身份必须形如 namespace:tool/definition/path：{name}") from error
    raise ValueError(f"工具身份必须形如 namespace:tool/definition/path：{name}")
