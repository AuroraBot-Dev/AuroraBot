#L1缓存，内存存储

from typing import List
from src.brain.memory.base import MemoryItem

class WorkingMemory:
    """L1 缓存：工作记忆。
    存储当前对话的最近几轮记录，生命周期短，不持久化（或只做临时文件备份）。
    主要解决：让大模型知道刚才的上下文是什么。
    """
    def __init__(self, max_items: int = 10):
        # max_items 控制上下文窗口大小，防止 Token 爆炸
        self.max_items = max_items
        self._items: List[MemoryItem] = []

    def add(self, content: str, role: str = "user", metadata: dict = None) -> None:
        """写策略：直接追加。
        如果超出容量限制，则挤掉最老的一条记忆（FIFO 队列）。
        """
        item = MemoryItem(content=content, role=role, metadata=metadata or {})
        self._items.append(item)
        if len(self._items) > self.max_items:
            self._items.pop(0)

    def get_context(self) -> List[MemoryItem]:
        """读策略：全量读取。
        因为 L1 容量很小，所以直接把整个队列返回。
        """
        return self._items

    def clear(self) -> None:
        """会话结束、或者切换话题时，可以清空工作记忆"""
        self._items.clear()