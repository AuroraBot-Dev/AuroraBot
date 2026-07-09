"""L3 语义记忆 —— 基于 mem0 实现的知识图谱与长期事实存储，通过 ChromaDB 进行向量检索。

用法::

    from src.memory.semantic import SemanticMemory

    sm = SemanticMemory()
    sm.extract_and_store(text="用户喜欢蓝色", user_id="user123")
    facts = sm.search_facts(query="用户喜欢什么颜色", user_id="user123")

作者: `HH <https://github.com/haha-ha-cuo>`_
"""

from typing import Any

from src.ai.providers import missing_credentials_reason
from src.config import Config
from src.memory.client import create_memory
from src.utils.log_utils import get_logger

logger = get_logger("SemanticMemory")


class SemanticMemory:
    """L3 缓存：语义记忆 (Knowledge Graph & Facts)。

    基于 mem0 实现。
    主要解决：长期事实、用户偏好、通用经验的提炼与向量检索。
    """

    def __init__(self) -> None:
        # 延迟初始化 mem0 客户端，避免导入时就进行耗时的初始化和连接操作
        self._client = None
        logger.debug("L3 缓存已启动")

    @property
    def mem0(self) -> Any:
        if self._client is None:
            self._client = create_memory()
        return self._client

    def _missing_credentials_reason(self) -> str | None:
        for model in (
            Config.LLM_GATEWAY_FAST_MODEL,
            Config.LLM_GATEWAY_EMBEDDING_MODEL,
        ):
            reason = missing_credentials_reason(model)
            if reason is not None:
                return reason
        return None

    def extract_and_store(self, text: str, user_id: str) -> bool:
        """写策略：智能提炼与向量化 (Write via LLM Extraction)

        调用 mem0 的 add 方法。mem0 会在内部调用大模型分析这段文本，
        如果包含有价值的长期信息，就会将其转换为向量并存入 ChromaDB。
        """
        if not user_id or not str(user_id).strip():
            logger.warning("提取语义记忆跳过：user_id 为空")
            return False

        missing_reason = self._missing_credentials_reason()
        if missing_reason is not None:
            logger.warning(f"提取语义记忆跳过：{missing_reason}")
            return False

        try:
            messages = [{"role": "user", "content": text}]
            self.mem0.add(messages, user_id=user_id)
            logger.debug("已成功提取语义记忆")
            logger.debug("已尝试从文本中提取语义记忆，User: %s", user_id)
        except Exception:
            logger.exception("提取语义记忆失败")
            return False
        else:
            return True

    def search_facts(self, query: str, user_id: str) -> list[str]:
        """读策略：语义向量检索 (Semantic Search)

        根据当前任务或问题，去向量库中寻找最相关的长期记忆事实。
        """
        if not user_id or not str(user_id).strip():
            logger.warning("搜索语义记忆跳过：user_id 为空")
            return []

        query = (query or "").strip()
        if not query:
            return []

        missing_reason = self._missing_credentials_reason()
        if missing_reason is not None:
            logger.warning(f"搜索语义记忆跳过：{missing_reason}")
            return []

        try:
            hits = self.mem0.search(query, filters={"user_id": user_id})

            results: list[str] = []
            if hits and "results" in hits:
                results.extend(hit["memory"] for hit in hits["results"])
        except Exception:
            logger.exception("搜索语义记忆失败")
            return []
        else:
            return results
