"""宿主数据根目录下的显式目录分配。"""

from pathlib import Path

from .ids import validate_namespace


class DataDirectories:
    """命名空间表达数据归属；目录分配不构成同进程访问权限隔离。"""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    @property
    def root(self) -> Path:
        return self._root

    def _checked(self, path: Path) -> Path:
        resolved = path.resolve()
        if not resolved.is_relative_to(self._root) or resolved != path:
            raise ValueError(f"数据路径存在重定向或超出根目录：{path}")
        return resolved

    def _directory(self, path: Path) -> Path:
        self._checked(path)
        path.mkdir(parents=True, exist_ok=True)
        return self._checked(path)

    def namespace(self, namespace: str) -> Path:
        """分配 namespaces/ns-<namespace>，保留点分名称并避开系统保留文件名。"""
        validate_namespace(namespace)
        return self._directory(self._root / "namespaces" / f"ns-{namespace}")

    def context_snapshot(self) -> Path:
        """完整 ctx 快照使用宿主级路径，不从公共状态 ID 推导文件名。"""
        directory = self._directory(self._root / "framework")
        return self._checked(directory / "ctx.json")

    def configuration(self) -> Path:
        """用户维护的 TOML 配置根目录。"""
        return self._directory(self._root / "config")

    def structured_database(self) -> Path:
        """框架键值存储独立于插件自行维护的数据库。"""
        directory = self._directory(self._root / "framework")
        return self._checked(directory / "structured.sqlite3")
