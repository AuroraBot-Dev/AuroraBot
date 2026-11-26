"""HTTP/WS 的显式来源、主机与运行期令牌边界。"""

import os
import re
from dataclasses import dataclass, field
from secrets import compare_digest

from yarl import URL


def validate_token(token: str | None) -> None:
    """令牌采用至少 32 位 URL 安全字符，不在错误消息中回显。"""
    if token is not None and (not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", token)):
        raise ValueError("访问令牌须为 32 至 256 位 URL 安全字符")


def token_from_env(name: str | None) -> str | None:
    """只解析调用方显式指定的环境变量，不保存凭证。"""
    if name is None:
        return None
    token = os.environ.get(name)
    if not token:
        raise ValueError("访问令牌环境变量未设置或为空")
    validate_token(token)
    return token


@dataclass(frozen=True)
class AccessPolicy:
    """默认只允许本机非浏览器访问；扩展来源或主机必须配置令牌。"""

    token: str | None = field(default=None, repr=False)
    allowed_origins: tuple[str, ...] = ()
    allowed_hosts: tuple[str, ...] = ("127.0.0.1", "localhost")

    def __post_init__(self) -> None:
        validate_token(self.token)
        if isinstance(self.allowed_origins, str) or isinstance(self.allowed_hosts, str):
            raise TypeError("来源与 Host 白名单须为字符串序列")
        object.__setattr__(self, "allowed_origins", tuple(self.allowed_origins))
        object.__setattr__(self, "allowed_hosts", tuple(self.allowed_hosts))
        for origin in self.allowed_origins:
            if not isinstance(origin, str):
                raise TypeError("浏览器来源须为字符串")
            url = URL(origin)
            if (
                url.scheme not in ("http", "https")
                or not url.host
                or url.user is not None
                or url.password is not None
                or str(url.origin()) != origin
                or "*" in origin
            ):
                raise ValueError("浏览器来源须为完整且规范的 http(s)://主机[:端口]，不含路径或通配符")
        if not self.allowed_hosts:
            raise ValueError("至少开放一个 Host 主机名")
        for host in self.allowed_hosts:
            if not isinstance(host, str) or not re.fullmatch(r"[a-z0-9]+(?:[.-][a-z0-9]+)*", host):
                raise ValueError("Host 白名单须为小写 ASCII 域名或 IPv4 地址，不含端口或通配符")
        if self.token is None and (self.allowed_origins or set(self.allowed_hosts) - {"127.0.0.1", "localhost"}):
            raise ValueError("开放浏览器来源或代理主机必须配置访问令牌")

    def accepts_token(self, value: object) -> bool:
        """使用固定时间比较验证不可信输入。"""
        return (
            self.token is not None and isinstance(value, str) and value.isascii() and compare_digest(value, self.token)
        )
