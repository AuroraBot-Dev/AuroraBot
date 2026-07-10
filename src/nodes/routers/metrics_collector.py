"""MetricsCollector — 文件流转统计。

由心跳触发，扫描 kernel_data_dir 下的目录，统计文件数量和最近活动时间。
"""

from __future__ import annotations

import json
import time
from typing import Any

from src.kernel.base import FileDescriptor, FileUpdate, Router
from src.kernel.state_store import kernel_data_dir
from src.utils.log_utils import get_logger

logger = get_logger("Metrics")


class MetricsCollector(Router):
    """文件流转统计器。"""

    _default_guards = ["heartbeat/tick.json"]
    _default_produces = ["metrics/status.json"]

    def __init__(self, node_id: str, **kwargs: Any) -> None:
        super().__init__(node_id, **kwargs)

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
