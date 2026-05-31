"""MetricsCollector —— 文件流转统计。

纯机械 Router 节点。由心跳触发，扫描 kernel_data_dir 下的所有
pipeline / inbox / rhythm 目录，统计文件数量和最近活动时间，
产出 ``metrics/status.json`` 供外部监控使用。
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

from src.brain.kernel.base import FileDescriptor, FileUpdate, Router
from src.brain.kernel.state_store import kernel_data_dir
from src.utils.log_utils import get_logger

if TYPE_CHECKING:
    from src.platform.application_host import ApplicationHost

logger = get_logger("Metrics")


class MetricsCollector(Router):
    """文件流转统计器。

    watch ``heartbeat/tick.json``，每次心跳扫描各目录，
    产出 ``metrics/status.json``。
    """

    _default_guards = ["heartbeat/tick.json"]  # noqa: RUF012
    _default_produces = ["metrics/status.json"]  # noqa: RUF012

    def __init__(
        self,
        node_id: str,
        host: "ApplicationHost | None" = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(node_id, host=host, **kwargs)

    async def execute(self) -> list[FileUpdate]:
        base = kernel_data_dir
        now = time.time()

        metrics: dict[str, Any] = {
            "timestamp": now,
            "collected_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
            "directories": {},
        }

        scan_roots = {
            "inbox": base / "inbox" / "pending",
            "pipeline": base / "pipeline",
            "rhythm": base / "rhythm",
            "heartbeat": base / "heartbeat",
            "reflection": base / "reflection",
            "dead_letter": base / "dead_letter",
        }

        for name, scan_dir in scan_roots.items():
            files = 0
            newest_age: float | None = None

            if scan_dir.exists():
                for f in scan_dir.rglob("*.json"):
                    if "done" in f.parts:
                        continue
                    files += 1
                    try:
                        age = now - f.stat().st_mtime
                    except OSError:
                        age = 0
                    if newest_age is None or age < newest_age:
                        newest_age = age

            metrics["directories"][name] = {
                "pending_files": files,
                "newest_age_sec": round(newest_age, 1) if newest_age is not None else None,
            }

        metrics_dir = base / "metrics"
        metrics_dir.mkdir(parents=True, exist_ok=True)
        metrics_path = metrics_dir / "status.json"
        metrics_path.write_text(
            json.dumps(metrics, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        return [
            FileUpdate(
                descriptor=FileDescriptor(path="metrics/status.json", schema="json"),
                content=metrics,
            )
        ]
