"""显式开放的声明 TOML 编辑入口；不提供任意文件访问或运行期重装配。"""

from aurora_core.ids import Id

from .editor_contract import describe_configuration
from .files import ConfigurationConflict, ConfigurationFiles

CONFIGURATION = Id("org.aurora.config:endpoints/configuration")


class ConfigurationEndpoint:
    def __init__(self) -> None:
        self.http = describe_configuration()["http"]
        self.files: ConfigurationFiles | None = None

    async def handle(self, action: str, data: object) -> tuple[int, dict]:
        fields = {
            "configurationList": set(),
            "configurationGet": {"id"},
            "configurationSave": {"id", "content", "revision"},
        }
        try:
            if action not in fields or not isinstance(data, dict) or set(data) != fields[action]:
                raise ValueError("请求字段无效")
            if any(not isinstance(value, str) for value in data.values()):
                raise ValueError("请求值须为字符串")
            if self.files is None:
                return self._error(503, "unavailable", "配置服务尚未就绪或正在关闭")
            if action == "configurationList":
                return 200, {"result": self.files.list()}
            identity = Id(data["id"])
            if action == "configurationGet":
                return 200, {"result": self.files.get(identity)}
            return 200, {"result": self.files.save(identity, data["content"], data["revision"])}
        except ConfigurationConflict:
            return self._error(409, "configuration_conflict", "配置文件已变化，请重新读取后编辑")
        except KeyError:
            return self._error(404, "not_found", "配置声明不存在")
        except (ValueError, TypeError, UnicodeError):
            return self._error(400, "invalid_configuration", "请求、TOML 结构或配置关联校验失败")
        except OSError:
            return self._error(500, "configuration_io", "配置文件读取或保存失败，请重新读取核对")

    @staticmethod
    def _error(status: int, code: str, message: str) -> tuple[int, dict]:
        return status, {"error": {"code": code, "message": message}}
