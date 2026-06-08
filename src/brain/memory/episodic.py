import asyncio
import json
from typing import Any

from src.brain.memory.base import MemoryItem
from src.config import Config
from src.utils.log_utils import get_logger

logger = get_logger("EpisodicMemory")


class EpisodicMemory:
    """L2 缓存：情景记忆。
    记录按时间线发生的所有事件，相当于一个带有时间戳的 Log 库。
    引入了“滚动压缩”机制防止文件无限膨胀。
    """

    def __init__(self) -> None:
        # 复用项目现有的数据目录规范，将情景记忆持久化为 JSON 文件
        self._file_path = Config.MEMORY_DATA_DIR / "episodes.json"
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        # 触发压缩的阈值
        self._COMPRESS_THRESHOLD = 50
        logger.debug("L2 缓存已启动")

    def record_event(self, event_type: str, content: str, user_id: str) -> None:
        """写策略：追加写入 (Append Only)，并在必要时触发压缩。同时防止连续重复写入。"""
        records = self._load()

        # --- 简单的防抖去重逻辑 ---
        # 如果最近的一条记录，它的内容和当前准备写入的内容完全一致，并且也是同一个用户发出的，
        # 我们就认为这是一次重复请求（可能是网络重试或测试脚本跑了多次），直接忽略它。
        if records:
            last_record = records[-1]
            if last_record.get("content") == content and last_record.get("user_id") == user_id:
                logger.debug(
                    "拦截到重复的情景记忆写入，已忽略。内容摘要: %s...",
                    content[:10],
                )
                return
        # ------------------------

        item = MemoryItem(content=content, metadata={"type": event_type, "user_id": user_id})

        records.append(
            {
                "timestamp": item.timestamp,
                "type": event_type,
                "user_id": user_id,
                "content": content,
            }
        )

        # 模拟 RNN 隐状态更新：如果记录太多，触发折叠压缩
        if len(records) > self._COMPRESS_THRESHOLD:
            records = self._fold_state(records)
            logger.debug("L2 缓存记忆已折叠")
        self._save(records)

    def _fold_state(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """核心压缩逻辑。

        先用基础统计生成摘要记录保存，再异步通过统一 LLM 网关改进摘要，
        改进完成后回写文件。失败时保留基础摘要，不阻塞调用方。
        """
        to_compress = records[:-10]
        to_keep = records[-10:]

        if not to_compress:
            return records

        start_time = to_compress[0]["timestamp"]
        end_time = to_compress[-1]["timestamp"]

        # 先用基础统计生成摘要，保证同步路径不阻塞
        summary_content = f"【系统摘要】在 {start_time} 到 {end_time} 期间，发生了 {len(to_compress)} 次交互。"

        summary_record = {
            "timestamp": end_time,
            "type": "summary",
            "user_id": "system",
            "content": summary_content,
        }
        compressed = [summary_record, *to_keep]

        # 异步通过统一 LLM 网关改进摘要，完成后回写文件
        self._schedule_fold_refinement(to_compress, start_time, end_time, compressed)

        return compressed

    def _schedule_fold_refinement(
        self,
        to_compress: list[dict[str, Any]],
        start_time: str,
        end_time: str,
        compressed: list[dict[str, Any]],
    ) -> None:
        """异步调用 LLM 改进压缩摘要，完成后回写 episodes.json。"""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return  # 无事件循环（测试/脚本），跳过异步改进

        asyncio.create_task(self._refine_summary_async(to_compress, start_time, end_time, compressed))  # noqa: RUF006

    async def _refine_summary_async(
        self,
        to_compress: list[dict[str, Any]],
        start_time: str,
        end_time: str,
        compressed: list[dict[str, Any]],
    ) -> None:
        from src.brain.ai.gateway import gateway

        history_text = "\n".join(f"[{r['timestamp']}] {r['type']}: {r['content']}" for r in to_compress)

        try:
            gen = gateway.quality.acompletion(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是一个专业的记忆压缩员。请阅读以下系统与用户的历史交互流水账，"
                            "提炼出一段连贯、精简的背景故事（不超过150字），省略琐碎的客套话，"
                            "重点保留已经发生的关键事件、任务进展和重要转折。直接输出摘要内容即可。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"请压缩以下历史记录：\n{history_text}",
                    },
                ],
                max_tokens=300,
                temperature=0.5,
                timeout=Config.LLM_GATE_TIMEOUT,
            )
            await gen
            llm_summary = gen.plain()
            improved = (
                f"【AI提炼的长期背景】{llm_summary.strip()}\n"
                f"【系统摘要】在 {start_time} 到 {end_time} 期间，"
                f"发生了 {len(to_compress)} 次交互。"
            )
            compressed[0]["content"] = improved
            self._save(compressed)
            logger.debug("已通过 LLM 网关改进情景记忆压缩摘要")
        except Exception:
            logger.exception("改进情景记忆压缩摘要失败，保留基础摘要")

    def search_recent_events(self, limit: int = 5, user_id: str | None = None) -> list[str]:
        """读策略：按时间倒序截取 (Time-based retrieval)
        查询最近发生的事情。如果有 summary 记录，它会自动被包含在内提供长线背景。
        """
        records = self._load()
        # 过滤出当前用户相关的事件，以及系统级别的 summary 摘要
        if user_id:
            records = [r for r in records if r.get("user_id") == user_id or r.get("type") == "summary"]

        recent = records[-limit:]
        return [f"[{r['timestamp']}] {r['type']}: {r['content']}" for r in recent]

    def _load(self) -> list[dict[str, Any]]:
        """辅助方法：从文件加载数据"""
        if not self._file_path.exists():
            return []
        try:
            return json.loads(self._file_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            # 如果文件损坏，这里简单处理返回空列表，实际工程中可能需要备份和恢复机制
            return []

    def _save(self, data: list[dict[str, Any]]) -> None:
        """辅助方法：将数据写回文件"""
        self._file_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
