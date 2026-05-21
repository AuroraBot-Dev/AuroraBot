import asyncio

from src.brain.memory.base import MemoryContext, MemoryItem
from src.brain.memory.working import WorkingMemory
from src.brain.memory.episodic import EpisodicMemory
from src.brain.memory.semantic import SemanticMemory
from src.utils.log_utils import get_logger

logger = get_logger("UnifiedMemory")


class UnifiedMemoryManager:
    """统一联合记忆的入口网关 (Facade)
    
    Agent 节点只通过这个 Manager 与记忆系统交互，无需关心底层 L1/L2/L3 的流转细节。
    """
    def __init__(self):
        self.working = WorkingMemory()
        self.episodic = EpisodicMemory()
        self.semantic = SemanticMemory()

    def process_interaction(self, content: str, role: str, user_id: str) -> None:
        """【一键写入】当发生一次交互时，将数据瀑布式地灌入各个记忆层级。
        
        L1/L2 同步写入；L3 语义提炼通过 asyncio Task 异步执行，不阻塞调用方。
        """
        # 1. 放入短时工作记忆 (L1: 内存级，极快)
        self.working.add(content=content, role=role)
        
        # 2. 作为一条完整的日志存入情景记忆 (L2: 文件级，较快)
        self.episodic.record_event(event_type=f"chat_{role}", content=content, user_id=user_id)
        
        # 3. 语义提炼 (L3: LLM级，较慢) — 异步执行，不阻塞
        if role == "user":
            self._schedule_semantic_extract(content, user_id)

    def _schedule_semantic_extract(self, text: str, user_id: str) -> None:
        """将 L3 语义提取调度到后台 asyncio Task，避免阻塞调用方。"""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._extract_async(text, user_id))
        except RuntimeError:
            # 没有运行中的事件循环（测试/脚本环境），同步执行
            try:
                self.semantic.extract_and_store(text=text, user_id=user_id)
            except Exception:
                logger.exception("L3 语义提取同步回退失败")

    async def _extract_async(self, text: str, user_id: str) -> None:
        """异步执行 L3 语义提取，异常不影响调用方。"""
        try:
            self.semantic.extract_and_store(text=text, user_id=user_id)
        except Exception:
            logger.exception("L3 语义提取异步任务失败")

    def retrieve_context(self, current_query: str, user_id: str) -> MemoryContext:
        """【一键读取】根据当前问题，组装出一个包含三级缓存的综合上下文"""
        ctx = MemoryContext()
        
        # L1: 拿到最近的完整对话流
        ctx.working_context = self.working.get_context()
        
        # L2: 拿最近发生的 5 件事作为短期历史背景
        ctx.episodic_events = self.episodic.search_recent_events(limit=5, user_id=user_id)
        
        # L3: 利用用户的当前问题去检索相关的深层事实和偏好
        ctx.semantic_facts = self.semantic.search_facts(query=current_query, user_id=user_id)
        
        return ctx

# 暴露给外部方便导入的公共接口
__all__ = ["UnifiedMemoryManager", "MemoryContext", "MemoryItem"]