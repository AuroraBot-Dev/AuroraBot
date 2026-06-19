"""MemoryConsolidator —— 节律驱动的记忆整理与流归档。

认知 Agent 节点。由节律事件（rhythm/triggers/*.json）触发，
读取当前自我之流（now.md），通过 LLM 提取新知识，
更新 self/memories/*.md，然后将 now.md 归档到 archive/{date}.md。

这是 Kernel-gamma 的记忆沉淀机制——不是"写入数据库"，而是
"她整理自己的思绪，把体验沉淀为记忆"。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from src.brain.ai.gateway import gateway
from src.brain.kernel.base import Agent, FileUpdate
from src.brain.kernel.state_store import kernel_data_dir, move_to_done
from src.brain.nodes.self_stream import SelfStream
from src.utils.log_utils import get_logger

logger = get_logger("MemoryConsolidator")

_CONSOLIDATOR_SYSTEM = """你是 Aurora（小光）的记忆整理者。你在回顾自己的一天。

你的任务：
1. 阅读今天的全部体验和思考
2. 识别其中出现的**新知识**——关于人的、关于事的、关于自己的
3. 对于每条新知识，判断应该更新到哪个记忆文件（或创建新文件）
4. 以第一人称 Markdown 格式输出更新后的记忆内容

## 记忆文件格式

每个记忆文件以 "# 记忆：{主题}" 开头，内容是第一人称叙事。
- people.md / about_alice.md 等：关于某人的记忆
- facts.md / knowledge.md 等：关于事实的知识
- self.md：关于自己的认知

## 输出格式

对于需要更新的每个记忆文件，输出：

```
---MEMORY:{filename}---
新的完整文件内容（覆盖模式）
---END---
```

如果没有新知识需要沉淀，输出：
```
---NO_NEW_KNOWLEDGE---
```
"""


class MemoryConsolidator(Agent):
    """记忆沉淀节点。

    由 rhythm/triggers/*.json 触发。读取自我之流，提取新知，
    更新 memories/，归档 now.md。
    """

    _default_guards = ["rhythm/triggers/*.json"]  # noqa: RUF012
    _default_produces: list[str] = []  # noqa: RUF012

    def __init__(
        self,
        node_id: str,
        host: "object | None" = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(node_id, host=host, **kwargs)
        self._stream = SelfStream()

    async def execute(self) -> list[FileUpdate]:
        triggers_dir = kernel_data_dir / "rhythm" / "triggers"
        if not triggers_dir.exists():
            return []

        trigger_files = sorted(triggers_dir.glob("*.json"), key=lambda p: p.name)
        if not trigger_files:
            return []

        done_dir = triggers_dir / "done"
        done_dir.mkdir(parents=True, exist_ok=True)

        consolidated = False

        for tf in trigger_files:
            try:
                data = json.loads(tf.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                move_to_done(tf, done_dir)
                continue

            move_to_done(tf, done_dir)

            trigger_name = str(data.get("name", ""))
            logger.info("记忆沉淀触发: %s", trigger_name)

            # 只在 evening / midnight 时做完整整理
            if trigger_name not in ("evening", "midnight"):
                continue

            try:
                await self._consolidate()
                consolidated = True
            except Exception:
                logger.exception("记忆沉淀失败")

            # 每个周期只处理第一个匹配的触发器
            break

        if consolidated:
            date_str = datetime.now().strftime("%Y-%m-%d")  # noqa: DTZ005
            self._stream.archive_today(date_str)
            self._stream.append_experience(f"我整理了今天的记忆。新的体验已经沉淀下来，now.md 已归档到 {date_str}。")

        return []

    _MIN_STREAM_LENGTH = 200

    async def _consolidate(self) -> None:
        today_stream = self._stream.read_full()
        if len(today_stream) < self._MIN_STREAM_LENGTH:
            logger.debug("自我之流过短，跳过记忆沉淀")
            return

        existing_memories: dict[str, str] = {}
        for name in self._stream.list_memories():
            content = self._stream.read_memory(name)
            if content:
                existing_memories[name] = content

        memory_list = "\n".join(f"- {n}" for n in existing_memories) or "(无已有记忆)"
        memory_contents = "\n\n".join(f"## {n}\n{c}" for n, c in existing_memories.items()) or "(无已有记忆)"

        user_message = (
            f"## 今天的体验与思考\n\n{today_stream}\n\n"
            f"## 已有记忆列表\n{memory_list}\n\n"
            f"## 已有记忆内容\n{memory_contents}\n\n"
            f"请从中提取新知识，更新或创建记忆文件。"
        )

        messages = [
            {"role": "system", "content": _CONSOLIDATOR_SYSTEM},
            {"role": "user", "content": user_message},
        ]

        gen = gateway.quality.acompletion(
            messages,
            max_tokens=4096,
            temperature=0.3,
        )
        await gen
        response = (gen.plain() or "").strip()

        if not response or "---NO_NEW_KNOWLEDGE---" in response:
            logger.info("无新知识需要沉淀")
            return

        # 解析 LLM 输出的记忆更新
        self._apply_memory_updates(response)

    def _apply_memory_updates(self, response: str) -> None:
        import re

        pattern = r"---MEMORY:(.+?)---\n(.*?)---END---"
        matches = re.findall(pattern, response, re.DOTALL)

        for raw_name, raw_content in matches:
            name = raw_name.strip()
            content = raw_content.strip()
            if name and content:
                self._stream.write_memory(name, content)
                logger.info("记忆已更新: %s (%d chars)", name, len(content))

        if not matches:
            logger.debug("LLM 输出中未解析到记忆更新块")
