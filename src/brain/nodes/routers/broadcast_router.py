"""BroadcastRouter —— 一对多扇出路由。

纯机械 Router 节点。watch 一个 glob，将匹配的每个文件复制到 config.targets
中列出的所有 emit 路径。

典型用途：CommandDispatcher 的产出同时触发 Reflector + MoodMonitor。
"""

from __future__ import annotations

import contextlib
import json
from typing import Any

from src.brain.kernel.base import FileDescriptor, FileUpdate, Router
from src.brain.kernel.state_store import kernel_data_dir
from src.utils.log_utils import get_logger

logger = get_logger("BroadcastRouter")


class BroadcastRouter(Router):
    """一对多扇出路由。

    config.targets 格式::

        targets:
          - "pipeline/dispatch_queue/{filename}"
          - "reflection/inbox/{filename}"
          - "history/archive/{filename}"

    每个匹配的文件复制到所有 target 路径。
    """

    _default_guards: list[str] = []  # noqa: RUF012 — topology config 提供
    _default_produces: list[str] = []  # noqa: RUF012

    def __init__(
        self,
        node_id: str,
        host: "object | None" = None,
        *,
        targets: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(node_id, host=host, **kwargs)
        self._targets = targets or []

    async def execute(self) -> list[FileUpdate]:
        if not self._config_watch or not self._targets:
            return []

        updates: list[FileUpdate] = []
        base = kernel_data_dir

        for pattern in self._config_watch:
            for file_path in sorted(base.glob(pattern), key=lambda p: p.name):
                try:
                    data = json.loads(file_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue

                # 移除源文件
                with contextlib.suppress(OSError):
                    file_path.unlink()

                filename = file_path.name
                for target in self._targets:
                    resolved = target.replace("{filename}", filename)
                    update = FileUpdate(
                        descriptor=FileDescriptor(path=resolved, schema="json"),
                        content=data,
                    )
                    updates.append(update)

                logger.debug("扇出: %s → %d targets", filename, len(self._targets))

        return updates
