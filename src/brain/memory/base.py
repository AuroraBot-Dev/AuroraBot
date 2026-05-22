from dataclasses import dataclass, field
from typing import Any, Dict, List

from src.utils.time_utils import now_text


@dataclass(slots=True)
class MemoryItem:
    """记忆的通用原子结构
    
    代表了记忆系统中的一条独立记录，无论是短期对话还是长期的日志。
    """
    content: str
    role: str = "user"  # 常见角色: user, assistant, system, tool
    timestamp: str = field(default_factory=now_text)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MemoryContext:
    """提供给大模型当前回合的完整记忆上下文
    
    统筹 L1(工作), L2(情景), L3(语义) 三层记忆的提取结果。
    """
    working_context: List[MemoryItem] = field(default_factory=list)#L1缓存
    episodic_events: List[str] = field(default_factory=list)#L2缓存
    semantic_facts: List[str] = field(default_factory=list)#L3缓存

    def to_prompt_text(self) -> str:
        """将三级记忆合并成适合作为 LLM 提示词 (Prompt) 的纯文本"""
        prompt_lines = []
        
        # 1. 拼接 L1 工作记忆 (最近的对话)
        if self.working_context:
            prompt_lines.append("【当前上下文】")
            for item in self.working_context:
                prompt_lines.append(f"- {item.role}: {item.content}")
            prompt_lines.append("") # 空行分隔
        
        # 2. 拼接 L2 情景记忆 (最近发生的系统事件/日志)
        if self.episodic_events:
            prompt_lines.append("【相关历史事件】")
            for event in self.episodic_events:
                prompt_lines.append(f"- {event}")
            prompt_lines.append("")
                
        # 3. 拼接 L3 语义记忆 (长期事实、用户偏好)
        if self.semantic_facts:
            prompt_lines.append("【已知事实与偏好】")
            for fact in self.semantic_facts:
                prompt_lines.append(f"- {fact}")
            prompt_lines.append("")
                
        return "\n".join(prompt_lines).strip()