"""MCP Server 发现逻辑。

扫描策略：
- ``apps/`` 目录下的内建 App（有 ``manifest.yaml``），结合 ``apps/config.yml`` 覆盖。
- ``apps/config.yml`` 中配置了完整 ``command`` 的外部 MCP Server（位置无关）。

位置无关的外部 MCP Server 示例::

  apps:
    my-custom-server:
      enabled: true
      package: im.polaris.custom
      name: 自定义服务
      mcp:
        enabled: true
        transport: stdio
        command: ["uv", "run", "--project", "/path/to/server", "python", "-m", "mcp_server"]
        env:
          DATA_DIR: /home/user/data
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from src.platform.mcp_kit.manifest import read_mcp_manifest
from src.platform.mcp_kit.server_spec import MCPServerSpec

# 项目根目录（通过 ``APPS_DIR`` 环境变量或相对于此文件向上查找）
_PROJECT_ROOT: Path | None = None


def _get_project_root() -> Path:
    """获取项目根目录。"""
    global _PROJECT_ROOT  # noqa: PLW0603
    if _PROJECT_ROOT is None:
        env_dir = os.environ.get("APPS_DIR")
        _PROJECT_ROOT = Path(env_dir) if env_dir else Path(__file__).resolve().parent.parent.parent.parent
    return _PROJECT_ROOT


APPS_DIR_NAME = "apps"


def discover_mcp_servers(  # noqa: C901, PLR0912 — 内建扫描 + 外部配置扫描的两个逻辑块
    apps_dir: Path | None = None,
    config_path: Path | None = None,
) -> list[MCPServerSpec]:
    """发现所有可用的 MCP Server 配置（内建 + 外部）。

    内建：扫描 ``apps/*/manifest.yaml``，合并 ``apps/config.yml`` 覆盖。
    外部：从 ``apps/config.yml`` 读取无本地目录、但配置了完整 ``mcp.command`` 的条目。

    Args:
        apps_dir: ``apps/`` 目录路径。默认自动查找。
        config_path: ``apps/config.yml`` 路径。默认自动查找。

    Returns:
        MCPServerSpec 列表。
    """
    root = _get_project_root()
    apps_dir = apps_dir or root / APPS_DIR_NAME
    config_path = config_path or root / APPS_DIR_NAME / "config.yml"

    # 读取全局配置
    config: dict[str, Any] = {}
    if config_path.exists():
        raw_config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if isinstance(raw_config, dict):
            config = raw_config

    apps_config: dict[str, Any] = {}
    if isinstance(config.get("apps"), dict):
        apps_config = dict(config["apps"])

    specs: list[MCPServerSpec] = []

    # ── 1. 扫描内建 apps/ 目录 ──
    if apps_dir.exists():
        for entry in sorted(apps_dir.iterdir()):
            if not entry.is_dir():
                continue
            manifest_file = entry / "manifest.yaml"
            if not manifest_file.exists():
                # 没有 manifest 的目录可能是外部 Server 的本地数据目录，跳过
                continue

            spec = _build_spec(entry, manifest_file, apps_config.get(entry.name, {}))
            if spec is not None:
                specs.append(spec)

    # ── 2. 从 config.yml 发现外部 MCP Server ──
    for key, cfg in apps_config.items():
        # 跳过已经在 apps/ 目录下有对应内建应用的条目
        if apps_dir.exists() and (apps_dir / key).is_dir():
            continue

        mcp_cfg = cfg.get("mcp", {})
        if not isinstance(mcp_cfg, dict):
            continue

        enabled = bool(mcp_cfg.get("enabled", True))
        if not enabled:
            continue

        command = list(mcp_cfg.get("command", []))
        if not command:
            continue  # 没有 command 无法启动

        specs.append(
            MCPServerSpec(
                key=str(cfg.get("package", key)),
                package=str(cfg.get("package", key)),
                name=str(cfg.get("name", key)),
                version=str(cfg.get("version", "0.1.0")),
                directory=Path(),
                transport=str(mcp_cfg.get("transport", "stdio")),
                command=[str(c) for c in command],
                args=[str(a) for a in mcp_cfg.get("args", [])],
                env={str(k): str(v) for k, v in mcp_cfg.get("env", {}).items()},
                enabled=True,
                health_timeout_seconds=float(mcp_cfg.get("health_timeout_seconds", 10.0)),
            )
        )

    return specs


def _build_spec(
    app_dir: Path,
    manifest_path: Path,
    app_cfg: dict[str, Any],
) -> MCPServerSpec | None:
    """从 manifest + 配置构建单个 MCPServerSpec。

    Args:
        app_dir: App 目录。
        manifest_path: manifest.yaml 路径。
        app_cfg: ``apps/config.yml`` 中对应 App 的配置 dict。

    Returns:
        如果 App 启用或可构建则返回 ``MCPServerSpec``，否则返回 ``None``。
    """
    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return None

    package = str(raw.get("package", ""))
    name = str(raw.get("name", app_dir.name))
    version = str(raw.get("version", "0.1.0"))

    # 检查是否启用
    enabled = bool(app_cfg.get("enabled", True))
    if not enabled:
        return None

    # 读取 MCP 扩展配置
    mcp_ext = read_mcp_manifest(manifest_path)

    # 从 config.yml 获取 MCP 覆盖配置
    mcp_cfg: dict[str, Any] = {}
    if isinstance(app_cfg.get("mcp"), dict):
        mcp_cfg = dict(app_cfg["mcp"])

    mcp_enabled = bool(mcp_cfg.get("enabled", mcp_ext is not None and mcp_ext.server_type == "mcp-server"))

    if not mcp_enabled:
        # 不启用 MCP 路径——返回带 legacy 标记的 spec供旧 ApplicationHost 使用
        return MCPServerSpec(
            key=package or app_dir.name,
            package=package or app_dir.name,
            name=name,
            version=version,
            directory=app_dir,
            enabled=False,
            startup=dict(app_cfg.get("startup", {})),
        )

    # 构建启动命令
    command: list[str] = []
    cmd_override = list(mcp_cfg.get("command", []))
    if cmd_override:
        command = [str(c) for c in cmd_override]
    elif mcp_ext and mcp_ext.mcp_command:
        command = [str(c) for c in mcp_ext.mcp_command]

    # 如果没有显式 command，构建默认命令
    if not command and mcp_ext and mcp_ext.mcp_entry:
        entry = mcp_ext.mcp_entry
        if entry.endswith(".py"):
            command = ["uv", "run", "python", str(app_dir / entry)]
        else:
            command = ["uv", "run", "python", "-m", f"{package}.{entry.replace('.py', '')}"]

    return MCPServerSpec(
        key=package or app_dir.name,
        package=package or app_dir.name,
        name=name,
        version=version,
        directory=app_dir,
        transport=str(mcp_cfg.get("transport", "stdio")),
        command=command,
        args=[str(a) for a in mcp_cfg.get("args", [])],
        env={str(k): str(v) for k, v in mcp_cfg.get("env", {}).items()},
        enabled=True,
        startup=dict(app_cfg.get("startup", {})),
        health_timeout_seconds=float(mcp_cfg.get("health_timeout_seconds", 10.0)),
    )
