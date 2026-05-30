from __future__ import annotations

import importlib
import inspect
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from src.config import Config
from src.platform.manifest import Manifest
from src.utils.log_utils import get_logger

logger = get_logger("AppDiscovery")


@dataclass(frozen=True, slots=True)
class DiscoveredApp:
    key: str
    package: str
    name: str
    directory: Path


def apps_root() -> Path:
    return Config.APP_DIR


# 发现结果缓存（避免启动流程中多次扫描重复日志）
_discovery_cache: dict[Path | None, dict[str, DiscoveredApp]] = {}


# 发现所有应用
def discover_apps(root: Path | None = None) -> dict[str, DiscoveredApp]:
    search_root = root or apps_root()

    # 缓存命中 → 静默返回
    cached = _discovery_cache.get(search_root)
    if cached is not None:
        logger.debug("应用发现缓存命中（%d 个应用）", len(cached))
        return cached

    discovered: dict[str, DiscoveredApp] = {}
    if not search_root.exists():
        _discovery_cache[search_root] = discovered
        return discovered
    for child in sorted(search_root.iterdir(), key=lambda item: item.name):
        # 检查是否为目录且不以 __ 开头
        if not child.is_dir() or child.name.startswith("__"):
            continue

        # 跳过dotfile目录
        if child.name.startswith("."):
            continue

        # 检查是否包含 manifest.yaml 和 __init__.py 文件
        manifest_path = child / "manifest.yaml"
        init_path = child / "__init__.py"
        if not manifest_path.exists() or not init_path.exists():
            continue

        # 读取 manifest.yaml 文件
        try:
            manifest = Manifest.load(manifest_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"跳过应用目录 {child.name}, manifest 读取失败: {exc}")
            continue
        if not manifest.package:
            logger.warning(f"跳过应用目录 {child.name}, manifest.package 为空")
            continue
        discovered[child.name] = DiscoveredApp(
            key=child.name,
            package=manifest.package,
            name=manifest.name or child.name,
            directory=child,
        )

    _discovery_cache[search_root] = discovered
    logger.info("在 %s 中发现 %d 个合法应用", search_root, len(discovered))
    return discovered


# 实例化应用
def instantiate_app(app_name: str, startup: dict[str, Any] | None = None) -> Any:
    module = importlib.import_module(f"apps.{app_name}")
    app_class = _resolve_application_class(module)
    kwargs = _filter_startup_kwargs(app_class, startup or {})
    return app_class(**kwargs)


# 获取应用启动参数默认值
def startup_defaults(app_name: str) -> dict[str, Any]:
    try:
        module = importlib.import_module(f"apps.{app_name}")
        app_class = _resolve_application_class(module)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"读取应用 {app_name} 启动参数默认值失败: {exc}")
        return {}
    signature = inspect.signature(app_class)
    defaults: dict[str, Any] = {}
    for parameter in signature.parameters.values():
        if parameter.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue
        if parameter.default is inspect.Signature.empty:
            continue
        defaults[parameter.name] = parameter.default
    return defaults


# ? 所以这个函数到底是干嘛的
def _resolve_application_class(module: ModuleType) -> type[Any]:
    exports = getattr(module, "__all__", [])
    for name in exports:
        candidate = getattr(module, str(name), None)
        if inspect.isclass(candidate):
            return candidate
    for _, candidate in inspect.getmembers(module, inspect.isclass):
        # 检查是否主类是否符合规范
        if _check_application_class_name(module, candidate):
            return candidate

    raise LookupError(f"在模块 {module.__name__} 中未找到 Application 类")


# FIXME 这个并没有什么卵用. 之后有空删了
def _check_application_class_name(module: ModuleType, candidate: type[Any]) -> bool:
    if candidate.__module__.startswith(module.__name__):
        if candidate.__name__.endswith("Application"):
            return True
        logger.error(
            f"应用主类 {candidate.__name__} 命名不规范，应为 {module.__name__}Application 类"
        )
        return False
    logger.error(f"应用主类 {candidate.__name__} 命名不规范，应为 {module.__name__}Application 类")
    return False


# 过滤应用启动参数
def _filter_startup_kwargs(
    app_class: type[Any],
    startup: dict[str, Any],
) -> dict[str, Any]:

    signature = inspect.signature(app_class)
    parameters = signature.parameters
    if any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()):
        return dict(startup)
    allowed = {
        name
        for name, parameter in parameters.items()
        if parameter.kind
        in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        )
    }
    unknown = sorted(set(startup) - allowed)
    if unknown:
        logger.warning(f"应用 {app_class.__name__} 忽略未知启动参数: {', '.join(unknown)}")
    return {key: value for key, value in startup.items() if key in allowed}
