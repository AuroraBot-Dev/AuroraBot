import json
import os
import requests
from pathlib import Path
from typing import List, Dict, Any

from src.brain.memory.base import MemoryItem
from src.config import Config
from src.utils.log_utils import get_logger

logger = get_logger("EpisodicMemory")

class EpisodicMemory:
    """L2 缓存：情景记忆。
    记录按时间线发生的所有事件，相当于一个带有时间戳的 Log 库。
    引入了“滚动压缩”机制防止文件无限膨胀。
    """
    def __init__(self):
        # 复用项目现有的数据目录规范，将情景记忆持久化为 JSON 文件
        self._file_path = Config.MEMORY_DATA_DIR / "episodes.json"
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        # 触发压缩的阈值
        self._COMPRESS_THRESHOLD = 50

    def record_event(self, event_type: str, content: str, user_id: str) -> None:
        """写策略：追加写入 (Append Only)，并在必要时触发压缩。同时防止连续重复写入。"""
        records = self._load()
        
        # --- 简单的防抖去重逻辑 ---
        # 如果最近的一条记录，它的内容和当前准备写入的内容完全一致，并且也是同一个用户发出的，
        # 我们就认为这是一次重复请求（可能是网络重试或测试脚本跑了多次），直接忽略它。
        if records:
            last_record = records[-1]
            if last_record.get("content") == content and last_record.get("user_id") == user_id:
                logger.info(f"拦截到重复的情景记忆写入，已忽略。内容摘要: {content[:10]}...")
                return
        # ------------------------
        
        item = MemoryItem(content=content, metadata={"type": event_type, "user_id": user_id})
        
        records.append({
            "timestamp": item.timestamp,
            "type": event_type,
            "user_id": user_id,
            "content": content
        })
        
        # 模拟 RNN 隐状态更新：如果记录太多，触发折叠压缩
        if len(records) > self._COMPRESS_THRESHOLD:
            records = self._fold_state(records)
            
        self._save(records)

    def _fold_state(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        核心压缩逻辑 (模拟 RNN 的 Hidden State Update)。
        调用 DeepSeek API 将大量流水账压缩成一条 'summary' 类型的浓缩记录。
        """
        to_compress = records[:-10]
        to_keep = records[-10:]
        
        start_time = to_compress[0]['timestamp']
        end_time = to_compress[-1]['timestamp']
        
        # 将历史记录拼接成一段纯文本，准备喂给大模型
        history_text = "\n".join([f"[{r['timestamp']}] {r['type']}: {r['content']}" for r in to_compress])
        
        # --- 调用 DeepSeek API 进行智能提炼 ---
        summary_content = f"【系统摘要】在 {start_time} 到 {end_time} 期间，发生了 {len(to_compress)} 次交互。"
        
        api_key = os.getenv("MEM0_LLM_API_KEY")
        base_url = os.getenv("MEM0_LLM_BASE_URL", "https://api.deepseek.com")
        model = os.getenv("MEM0_LLM_MODEL", "deepseek-chat")
        
        if api_key:
            try:
                url = f"{base_url}/chat/completions"
                headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
                payload = {
                    "model": model,
                    "messages": [
                        {
                            "role": "system", 
                            "content": "你是一个专业的记忆压缩员。请阅读以下系统与用户的历史交互流水账，提炼出一段连贯、精简的背景故事（不超过150字），省略琐碎的客套话，重点保留已经发生的关键事件、任务进展和重要转折。直接输出摘要内容即可。"
                        },
                        {"role": "user", "content": f"请压缩以下历史记录：\n{history_text}"}
                    ],
                    "max_tokens": 300,
                    "temperature": 0.5
                }
                
                response = requests.post(url, headers=headers, json=payload, timeout=20)
                response.raise_for_status()
                
                data = response.json()
                llm_summary = data["choices"][0]["message"]["content"].strip()
                # 将大模型的总结拼接到系统摘要后面
                summary_content = f"【AI提炼的长期背景】{llm_summary}"
                logger.info("已成功使用 DeepSeek 对情景记忆进行折叠压缩。")
                
            except Exception as e:
                logger.error(f"调用 DeepSeek 压缩情景记忆失败，将降级使用基础统计摘要。错误: {e}")
        else:
            logger.warning("未配置 MEM0_LLM_API_KEY，跳过智能压缩，使用基础统计摘要。")
        # -----------------------------------
        
        # 生成一条新的“摘要”记录
        summary_record = {
            "timestamp": end_time, # 用折叠结束的时间作为时间戳
            "type": "summary",
            "user_id": "system",
            "content": summary_content
        }
        
        return [summary_record] + to_keep

    def search_recent_events(self, limit: int = 5, user_id: str = None) -> List[str]:
        """读策略：按时间倒序截取 (Time-based retrieval)
        查询最近发生的事情。如果有 summary 记录，它会自动被包含在内提供长线背景。
        """
        records = self._load()
        # 过滤出当前用户相关的事件，以及系统级别的 summary 摘要
        if user_id:
            records = [r for r in records if r.get("user_id") == user_id or r.get("type") == "summary"]
        
        recent = records[-limit:]
        return [f"[{r['timestamp']}] {r['type']}: {r['content']}" for r in recent]

    def _load(self) -> List[Dict[str, Any]]:
        """辅助方法：从文件加载数据"""
        if not self._file_path.exists():
            return []
        try:
            return json.loads(self._file_path.read_text(encoding="utf-8"))
        except Exception:
            # 如果文件损坏，这里简单处理返回空列表，实际工程中可能需要备份和恢复机制
            return []

    def _save(self, data: List[Dict[str, Any]]) -> None:
        """辅助方法：将数据写回文件"""
        self._file_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")