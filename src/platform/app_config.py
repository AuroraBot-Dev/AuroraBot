from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from src.config import Config
from src.platform.app_discovery import (
    DiscoveredApp,
    discover_apps,
    startup_defaults,
)
from src.utils.log_utils import get_logger

logger = get_logger("AppConfig")


def _resolve_config_path() -> Path:
    yml_path = Config.APP_DIR / "config.yml"
    yaml_path = Config.APP_DIR / "config.yaml"
    if yml_path.exists():
        return yml_path
    if yaml_path.exists():
        return yaml_path
    return yml_path


def app_config_path() -> Path:
    return _resolve_config_path()


# 加载应用配置
def load_apps_config(path: Path | None = None) -> dict[str, dict[str, Any]]:
    config_path = path or _resolve_config_path()
    discovered = discover_apps()

    # 当配置文件不存在时, 根据发现的应用生成初始化配置
    if not config_path.exists():
        _write_initial_config(config_path, discovered)
        logger.warning(f"未找到 {config_path}, 已根据扫描结果生成初始化配置")
        return {}

    # 读取配置文件
    try:
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8-sig"))
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"读取 {config_path} 失败: {exc}")
        return {}

    # 解析配置文件
    payload = loaded if isinstance(loaded, dict) else {}
    raw_apps = payload.get("apps", {})
    if not isinstance(raw_apps, dict):
        logger.warning(f"{config_path} 格式错误")
        return {}

    # 归一化配置
    normalized: dict[str, dict[str, Any]] = {}
    for name in sorted(discovered):
        raw = raw_apps.get(name)
        if raw is None:
            logger.warning(f"应用 {name} 未在 {config_path} 中声明, 跳过加载")
            continue
        if not isinstance(raw, dict):
            logger.warning(f"应用 {name} 的配置格式错误, 跳过加载")
            continue
        startup = raw.get("startup", {})
        if not isinstance(startup, dict):
            logger.warning(f"应用 {name} 的 startup 字段格式错误, 已重置为空")
            startup = {}
        normalized[name] = {
            "enabled": bool(raw.get("enabled", False)),
            "startup": {str(key): value for key, value in startup.items()},
        }

    # 忽略未知应用
    for name in sorted(set(raw_apps) - set(discovered)):
        logger.warning(f"{config_path} 中声明了未知应用 {name}, 已忽略")

    logger.info(f"本次启动共加载 {len(normalized)} 个应用配置")
    return normalized


# 获取已启用的应用名称
def enabled_app_names(apps_config: dict[str, dict[str, Any]]) -> list[str]:
    return [
        name for name, spec in apps_config.items() if bool(spec.get("enabled", False))
    ]


# 获取应用启动参数
def app_startup(
    apps_config: dict[str, dict[str, Any]], app_name: str
) -> dict[str, Any]:
    startup = apps_config.get(app_name, {}).get("startup", {})
    return startup if isinstance(startup, dict) else {}


# 构建初始应用配置
def build_initial_apps_config() -> dict[str, Any]:
    return _build_initial_apps_config_from_discovered(discover_apps())


# 写入初始应用配置
def _write_initial_config(
    config_path: Path, discovered: dict[str, DiscoveredApp]
) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        yaml.safe_dump(
            _build_initial_apps_config_from_discovered(discovered),
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _build_initial_apps_config_from_discovered(
    discovered: dict[str, DiscoveredApp],
) -> dict[str, Any]:
    return {
        "apps": {
            name: {
                "enabled": True,
                "startup": startup_defaults(name),
            }
            for name in sorted(discovered)
        }
    }
