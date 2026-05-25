from __future__ import annotations
import json
from pathlib import Path
from typing import Any

from src.brain.kernel.base import FileDescriptor, FilePattern, FileUpdate, Router
from src.brain.kernel.state_store import kernel_data_dir
from src.utils.log_utils import get_logger

logger = get_logger("FanOutRouter")


class FanOutRouter(Router):
    """多路扇出 Router —— 将输入文件内容复制到 N 个 emit 目录。

    纯机械逻辑，零 LLM 调用。

    监听匹配 watch 模式的文件，将每个文件的内容原样复制到所有
    emit 目录（保留原始文件名）。处理完成后将源文件移至 ``done/``
    子目录，实现「文件写一次永不修改」的生命周期管理。

    典型拓扑用途：作为认知电路的入口，将外部事件扇出到多个
    下游节点的 ``pending/`` 输入目录。

    watch / emit 来自 topology.yaml 的顶层字段覆盖
    （:attr:`_config_watch` / :attr:`_config_emit`），
    不由本构造函数的 ``**config`` 参数提供。
    """

    def __init__(self, node_id: str, **config: Any) -> None:
        super().__init__(node_id)
        # watch/emit 由 build_circuit 在装配时通过 _config_watch / _config_emit
        # 注入，不在此处消费 **config。

    async def execute(self) -> list[FileUpdate]:
        """扫描匹配的源文件，逐文件复制到所有 emit 目录。

        对每个源文件：
        1. 读取 JSON 内容
        2. 为每个 emit 目录构造 ``<emit_dir>/<源文件名>`` 的 FileUpdate
        3. 为 ``inbox/done/<源文件名>`` 构造 FileUpdate（走总线唤醒 Planner）
        4. 删除 inbox/pending/ 中的源文件
        5. 返回所有 FileUpdate 列表
        """
        watch_patterns = self._config_watch or []
        emit_dirs = self._config_emit or []

        if not watch_patterns or not emit_dirs:
            logger.warning("FanOutRouter: watch 或 emit 为空，跳过执行")
            return []

        # ── 收集所有匹配的源文件 ──────────────────────────────────
        all_matched: list[Path] = []
        for pattern in watch_patterns:
            guard_path = kernel_data_dir / pattern
            parent = guard_path.parent
            pattern_name = guard_path.name

            if not parent.exists():
                continue

            matched = sorted(parent.glob(pattern_name))
            all_matched.extend(matched)

        if not all_matched:
            return []

        # ── 解析 emit 目录（相对路径 → Path） ─────────────────────
        emit_dirs_resolved = [Path(d) for d in emit_dirs]

        # ── 扇出：逐文件处理 ──────────────────────────────────────
        updates: list[FileUpdate] = []

        for src_path in all_matched:
            source_filename = src_path.name

            # 1) 读取源文件
            try:
                content = json.loads(src_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning(f"FanOutRouter 读取源文件失败 {src_path}: {exc}")
                continue

            # 2) 复制到每个 emit 目录
            for emit_dir in emit_dirs_resolved:
                target_path = str(emit_dir / source_filename)
                updates.append(
                    FileUpdate(
                        descriptor=FileDescriptor(
                            path=target_path,
                            schema="json",
                        ),
                        content=content,
                    )
                )
                logger.debug(f"FanOutRouter: {source_filename} → {target_path}")

            # 3) 源文件移入 inbox/done/ — 通过 FileUpdate 走总线，唤醒 Planner
            inbox_done_path = f"inbox/done/{source_filename}"
            updates.append(
                FileUpdate(
                    descriptor=FileDescriptor(
                        path=inbox_done_path,
                        schema="json",
                    ),
                    content=content,
                )
            )
            # 删除 inbox/pending/ 中的源文件（内容已转移）
            try:
                src_path.unlink()
            except OSError as exc:
                logger.warning(f"FanOutRouter 删除源文件失败 {src_path}: {exc}")
            logger.debug(f"FanOutRouter: 源文件 {source_filename} → {inbox_done_path}")

        return updates
