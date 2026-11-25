"""使用 JSON Schema 校验 TOML 数据，统一缺省值和不含字段值的错误定位。"""

from collections.abc import Callable
from copy import deepcopy

from aurora_core.ids import Id
from aurora_core.json_data import encode_json
from jsonschema import Draft202012Validator, FormatChecker, validators
from referencing import Registry

_formats = FormatChecker()
_Validator = validators.extend(
    Draft202012Validator,
    type_checker=Draft202012Validator.TYPE_CHECKER.redefine("integer", lambda checker, value: type(value) is int),
)


@_formats.checks("aurora-id", raises=ValueError)
def _public_id(value: object) -> bool:
    if isinstance(value, str):
        Id(value)
    return True


def _defaults(value: object, schema: dict) -> object:
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for name, field in properties.items():
            if name not in value and isinstance(field, dict) and "default" in field:
                value[name] = deepcopy(field["default"])
        for name, item in value.items():
            field = properties.get(name, schema.get("additionalProperties", {}))
            if isinstance(field, dict):
                value[name] = _defaults(item, field)
    elif isinstance(value, list) and isinstance(schema.get("items"), dict):
        value = [_defaults(item, schema["items"]) for item in value]
    return value


class ConfigSchema:
    """结构约束与可选业务校验；parse 补齐声明中的默认值且不改写输入。

    默认值支持 properties、additionalProperties 和 items 中的字段。
    validate 同样校验默认值，但不转换 ctx/set 的数据；读取方可使用 parse。
    """

    def __init__(self, definition: dict, *, check: Callable[[object], None] | None = None) -> None:
        self._definition = deepcopy(definition)
        Draft202012Validator.check_schema(self._definition)
        self._validator = _Validator(self._definition, format_checker=_formats, registry=Registry())
        self._check = check

    def parse(self, value: object) -> object:
        encode_json(value)
        candidate = _defaults(deepcopy(value), self._definition)
        encode_json(candidate)
        error = next(self._validator.iter_errors(candidate), None)
        if error is not None:
            path = ".".join(map(str, error.absolute_path)) or "<根>"
            raise ValueError(f"配置字段 {path} 不符合 {error.validator} 约束")
        if self._check is not None:
            self._check(deepcopy(candidate))
        return candidate

    def validate(self, value: object) -> None:
        self.parse(value)
