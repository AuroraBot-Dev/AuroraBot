#L3缓存，mem0层
from typing import List

from src.brain.memory.client import create_memory
from src.utils.log_utils import get_logger

logger = get_logger("SemanticMemory")

class SemanticMemory:
    """L3 缓存：语义记忆 (Knowledge Graph & Facts)。
    
    基于 mem0 实现。
    主要解决：长期事实、用户偏好、通用经验的提炼与向量检索。
    """
    def __init__(self):
        # 延迟初始化 mem0 客户端，避免导入时就进行耗时的初始化和连接操作
        self._client = None

    @property
    def mem0(self):
        if self._client is None:
            self._client = create_memory()
        return self._client

    def extract_and_store(self, text: str, user_id: str) -> None:
        """写策略：智能提炼与向量化 (Write via LLM Extraction)
        
        调用 mem0 的 add 方法。mem0 会在内部调用大模型(DeepSeek)分析这段文本，
        如果包含有价值的长期信息，就会将其转换为向量并存入 ChromaDB。
        """
        try:
            # mem0 的 add 需要传入特定的 message 格式
            messages = [{"role": "user", "content": text}]
            self.mem0.add(messages, user_id=user_id)
            logger.info(f"已尝试从文本中提取语义记忆，User: {user_id}")
        except Exception as e:
            logger.error(f"提取语义记忆失败: {e}")

    def search_facts(self, query: str, user_id: str) -> List[str]:
        """读策略：语义向量检索 (Semantic Search)
        
        根据当前任务或问题，去向量库中寻找最相关的长期记忆事实。
        """
        try:
            # 使用 filters 语法按用户隔离记忆
            hits = self.mem0.search(query, filters={"user_id": user_id})
            
            results = []
            if hits and "results" in hits:
                for hit in hits["results"]:
                    # 这里你可以根据需要加入 score (相似度得分) 的阈值判断
                    # 例如: if hit["score"] > 0.3:
                    results.append(hit["memory"])
                    
            return results
        except Exception as e:
            logger.error(f"搜索语义记忆失败: {e}")
            return []

    