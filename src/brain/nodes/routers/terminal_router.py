from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from src.brain.kernel.base import (
    FileDescriptor,
    FilePattern,
    FileUpdate,
    NodeState,
    Router,
)
from src.config import Config
from src.utils.log_utils import get_logger

logger = get_logger("TerminalRouter")

_DATA_DIR = Config.KERNEL_DATA_DIR


class TerminalRouter(Router):
    """生命周期终止 Router —— 定期扫描 done/ 目录，删除过期文件。

    纯机械逻辑，零 LLM 调用。

    通过自触发 tick 文件实现周期性扫描。每次执行都会扫描所有
    守护模式中匹配 ``/done/`` 目录的文件，将修改时间超过
    ``ttl_sec`` 的文件删除。自触发频率为 TTL 的一半（最低 10 秒），
    避免忙等。

    watch / emit 来自 topology.yaml 的顶层字段覆盖
    （:attr:`_config_watch` / :attr:`_config_emit`），
    默认 watch 包含 ``*/done/*.json`` 和自触发 tick 文件。

    参数在构造时通过 ``**config`` 传入：
    - ``ttl_sec``: 文件存活时间（秒），默认 60
    """

    def __init__(self, node_id: str, **config: Any) -> None:
        super().__init__(node_id)
        self._ttl_sec = float(config.get("ttl_sec", 60))
        self._tick_dir = _DATA_DIR / "terminal"

    @property
    def type(self) -> str:
        return "router"

    @property
    def guards(self) -> list[FilePattern]:
        patterns: list[FilePattern] = []
        if self._config_watch is not None:
            patterns = [FilePattern(p) for p in self._config_watch]
        else:
            patterns = [FilePattern("*/done/*.json")]
        # 始终添加自触发 tick 文件
        if not any(p.match("terminal/tick.json") for p in patterns):
            patterns.append(FilePattern("terminal/tick.json"))
        return patterns

    @property
    def produces(self) -> list[FileDescriptor]:
        if self._config_emit is not None:
            return [FileDescriptor(p) for p in self._config_emit]
        return [FileDescriptor("terminal/tick.json")]

    def on_event(self, event: FileEvent) -> bool:
        """允许自触发 —— terminal tick 驱动周期性清理。"""
        if self.state not in (NodeState.IDLE, NodeState.READY):
            return False
        return any(g.match(event.path) for g in self.guards)

    async def execute(self) -> list[FileUpdate]:
        now = time.time()

        # ── 清理过期文件（始终执行） ──────────────────────────────────
        deleted = self._cleanup_expired(now)

        # ── 自触发 tick（限速以节省资源） ─────────────────────────────
        tick_path = self._tick_dir / "tick.json"
        last_tick: float = 0.0

        if tick_path.exists():
            try:
                data = json.loads(tick_path.read_text(encoding="utf-8"))
                last_tick = float(data.get("timestamp", 0.0))
            except (OSError, json.JSONDecodeError, ValueError):
                pass

        interval = max(10.0, self._ttl_sec / 2)
        if now - last_tick < interval:
            return []

        self._tick_dir.mkdir(parents=True, exist_ok=True)
        tick_data = {
            "tick_id": uuid.uuid4().hex[:12],
            "timestamp": now,
            "ttl_sec": self._ttl_sec,
            "last_cleanup_count": deleted,
        }
        logger.debug(f"TerminalRouter: tick {tick_data['tick_id']}, 清理 {deleted} 个过期文件")

        return [
            FileUpdate(
                descriptor=FileDescriptor(
                    path="terminal/tick.json",
                    schema="json",
                ),
                content=tick_data,
            )
        ]

    def _cleanup_expired(self, now: float) -> int:
        """扫描所有守护的 done/ 模式，删除超时文件。"""
        # 仅处理含 /done/ 的模式
        patterns = self._config_watch or ["*/done/*.json"]
        deleted = 0

        for pattern in patterns:
            # 只处理 done 生命周期目录下的模式
            if "/done/" not in pattern and "done/" not in pattern:
                continue

            guard_path = _DATA_DIR / pattern
            parent = guard_path.parent
            pattern_name = guard_path.name

            if not parent.exists():
                continue

            for file_path in parent.glob(pattern_name):
                if not file_path.is_file():
                    continue

                try:
                    mtime = file_path.stat().st_mtime
                except OSError:
                    continue

                if now - mtime >= self._ttl_sec:
                    try:
                        file_path.unlink()
                        deleted += 1
                        logger.debug(f"TerminalRouter: 删除过期文件 {file_path}")
                    except OSError as exc:
                        logger.warning(
                            f"TerminalRouter 删除文件失败 {file_path}: {exc}"
                        )

        if deleted:
            logger.info(f"TerminalRouter: 清理了 {deleted} 个过期文件")

        return deleted

    def on_complete(self) -> None:
        if self.state != NodeState.ERROR:
            self.state = NodeState.IDLE
