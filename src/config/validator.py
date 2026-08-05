"""配置快照的启动前合法性校验。

校验规则独立于 TOML 解析层，接收完全加载的 AuroraConfig 快照，
对所有跨段约束（如路径不重叠、配置一致性）执行最终验证。
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from src.contracts.configuration import ConfigurationError

if TYPE_CHECKING:
    from pathlib import Path

    from src.contracts.configuration import AuroraConfig


class _Msg(StrEnum):
    """本文件内所有用户可见或日志输出的字符串常量。"""

    STORAGE_OVERLAP = "package storage directories must not overlap: {a} and {b}"
    STORAGE_NOT_UNDER_ROOT = "storage directory {dir} must be under data_root {root}"
    DASHBOARD_NOT_LOOPBACK = "dashboard must bind to loopback (127.0.0.1, ::1, or localhost)"
    DASHBOARD_DB_OVERLAP_ENGINE = "dashboard database_path must not overlap engine workspace"
    DASHBOARD_UPLOAD_OVERLAP_ENGINE = "dashboard upload_dir must not overlap engine workspace"
    AGENT_UNKNOWN_MODEL_ROLE = "Agent {agent_id} references unknown model role {model_role}"
    AGENT_UNKNOWN_CHILD = "Agent {agent_id} references unknown child profile {child}"
    AGENT_DELEGATION_DISABLED = "Agent {agent_id} cannot declare child_profiles when can_delegate is False"


LOOPBACK_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "::1", "localhost"})


def validate_config(config: AuroraConfig) -> None:
    """对完全加载的配置快照执行启动前校验，不满足约束时抛出 ConfigurationError。"""
    _validate_storage_paths(config)
    _validate_dashboard_constraints(config)
    _validate_agent_constraints(config)


def _validate_storage_paths(config: AuroraConfig) -> None:
    """校验各包数据目录位于 data_root 之下且互不重叠，仅允许声明过的祖先包含关系。"""
    storage = config.storage
    # 所有包级存储目录必须位于 data_root 之下
    directories: dict[str, Path] = {
        "engine": storage.engine,
        "ai": storage.ai,
        "memory": storage.memory,
        "platform": storage.platform,
        "dashboard": storage.dashboard,
        "mcp": storage.mcp,
        "apps": storage.apps,
    }
    data_root = storage.data_root
    for directory in directories.values():
        if not directory.is_relative_to(data_root):
            raise ConfigurationError(_Msg.STORAGE_NOT_UNDER_ROOT.format(dir=directory, root=data_root))

    # 两两比较，仅允许声明过的祖先包含关系（与 loader 的规则一致）
    paths = list(directories.items())
    for index, (label, directory) in enumerate(paths):
        for other_label, other in paths[index + 1 :]:
            if directory != other and not (directory.is_relative_to(other) or other.is_relative_to(directory)):
                continue
            if label in _STORAGE_CONTAINS[other_label] or other_label in _STORAGE_CONTAINS[label]:
                continue
            raise ConfigurationError(_Msg.STORAGE_OVERLAP.format(a=label, b=other_label))


_STORAGE_CONTAINS: dict[str, frozenset[str]] = {
    "platform": frozenset({"dashboard", "mcp", "apps"}),
    "mcp": frozenset({"apps"}),
    "dashboard": frozenset(),
    "engine": frozenset(),
    "ai": frozenset(),
    "memory": frozenset(),
    "apps": frozenset(),
}


def _validate_dashboard_constraints(config: AuroraConfig) -> None:
    """校验 Dashboard 仅绑定 loopback 且数据目录不与 engine 重叠。"""
    dashboard = config.dashboard
    engine_workspace = config.engine.workspace

    # Dashboard 必须绑定 loopback 地址
    if dashboard.host not in LOOPBACK_HOSTS:
        raise ConfigurationError(_Msg.DASHBOARD_NOT_LOOPBACK)

    # Dashboard 数据目录不得与 engine 工作区重叠
    if dashboard.database_path.is_relative_to(engine_workspace) or engine_workspace.is_relative_to(
        dashboard.database_path
    ):
        raise ConfigurationError(_Msg.DASHBOARD_DB_OVERLAP_ENGINE)
    if dashboard.upload_dir.is_relative_to(engine_workspace) or engine_workspace.is_relative_to(dashboard.upload_dir):
        raise ConfigurationError(_Msg.DASHBOARD_UPLOAD_OVERLAP_ENGINE)


def _validate_agent_constraints(config: AuroraConfig) -> None:
    """校验 Agent profile 引用完整性：模型角色、子档案和委派一致性。"""
    model_roles = config.model_roles
    agent_ids = frozenset(agent.id for agent in config.agents)

    for agent in config.agents:
        # 模型角色必须存在于 models.toml 的 roles 中
        if agent.model_role not in model_roles:
            raise ConfigurationError(
                _Msg.AGENT_UNKNOWN_MODEL_ROLE.format(agent_id=agent.id, model_role=agent.model_role)
            )

        # 子档案引用必须指向已定义的 Agent
        for child in agent.child_profiles:
            if child not in agent_ids:
                raise ConfigurationError(_Msg.AGENT_UNKNOWN_CHILD.format(agent_id=agent.id, child=child))

        # can_delegate 为 False 时不得声明 child_profiles
        if not agent.can_delegate and agent.child_profiles:
            raise ConfigurationError(_Msg.AGENT_DELEGATION_DISABLED.format(agent_id=agent.id))
