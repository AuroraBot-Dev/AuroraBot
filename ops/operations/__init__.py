"""内建操作目录；各模块通过装饰器注册资源。"""

from ops.contracts import OperationResult


def require_port[Port](port: Port | None, name: str) -> tuple[Port | None, OperationResult | None]:
    """返回已组合的窄端口，或一个统一的 NOT_AVAILABLE 操作结果。"""
    if port is not None:
        return port, None
    return None, OperationResult.failure("NOT_AVAILABLE", f"{name} 端口尚未装配")
