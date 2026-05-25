import json
import os
import sys
import requests
from dotenv import load_dotenv

# 将项目根目录（AuroraBot）加入到系统路径，解决 'src' 模块找不到的问题
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../..")))

from src.brain.memory import UnifiedMemoryManager


def chat_with_deepseek(prompt_context: str, user_input: str) -> str:
    """直接使用 requests 调用 DeepSeek API，附带三级记忆上下文"""
    load_dotenv()
    api_key = os.getenv("MEM0_LLM_API_KEY")
    base_url = os.getenv("MEM0_LLM_BASE_URL", "https://api.deepseek.com")
    model = os.getenv("MEM0_LLM_MODEL", "deepseek-chat")

    if not api_key:
        return "错误: 未在 .env 中找到 MEM0_LLM_API_KEY，无法调用大模型。"

    url = f"{base_url}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    
    # 构建请求体，系统提示词强调必须基于上下文
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system", 
                "content": "你是一个有记忆的贴心私人助理。请结合下方提供的【三级记忆上下文】来理解用户，并回答用户的最新问题。如果上下文中包含用户的习惯、偏好或历史事件，请尽可能自然地在回答中体现出来，让用户感觉到你‘记得’他们。\n\n" + prompt_context
            },
            {"role": "user", "content": user_input}
        ],
        "max_tokens": 800,
        "temperature": 0.7
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=20)
        response.raise_for_status() 
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"❌ 大模型请求失败: {e}"


def interactive_chat_test() -> None:
    """交互式多轮对话测试"""
    # 1. 初始化统一记忆管理器
    memory_manager = UnifiedMemoryManager()
    user_id = "test_user_001"

    print("=====================================================")
    print("🤖 欢迎进入 AuroraBot 记忆系统交互测试！")
    print("💡 提示：")
    print("  - 你可以告诉我你的名字、爱好、最近做了什么事。")
    print("  - 然后试着在后面的对话中问我相关的细节，测试我是否'记得'。")
    print("  - 系统会在后台自动为你构建 L1(短期)、L2(日志)、L3(语义) 缓存。")
    print("  - 输入 'quit' 或 'exit' 退出测试。")
    print("=====================================================\n")

    while True:
        try:
            # 获取用户输入
            user_msg = input("\n👤 你的输入: ").strip()
            if not user_msg:
                continue
            if user_msg.lower() in ["quit", "exit"]:
                print("👋 退出测试。")
                break

            # --- 第一步：检索记忆上下文 ---
            # 在让大模型思考前，先把所有相关的记忆都捞出来
            print("🔍 正在检索大脑记忆 (L1/L2/L3)...")
            context = memory_manager.retrieve_context(current_query=user_msg, user_id=user_id)
            prompt_text = context.to_prompt_text()
            
            # (可选：你可以把这行取消注释，来观察每次发给大模型的完整提示词长什么样)
            # print(f"\n[Debug] 提取到的上下文: \n{prompt_text}\n")

            # --- 第二步：将上下文和用户输入喂给大模型 ---
            print("🧠 思考中...")
            bot_reply = chat_with_deepseek(prompt_text, user_msg)
            print(f"\n🤖 助手: {bot_reply}")

            # --- 第三步：一键瀑布式写入记忆 ---
            # 交互完成后，将这一轮对话同时写入 L1(工作区), L2(日志文件), L3(交由mem0提炼)
            memory_manager.process_interaction(content=user_msg, role="user", user_id=user_id)
            memory_manager.process_interaction(content=bot_reply, role="assistant", user_id=user_id)

        except KeyboardInterrupt:
            print("\n👋 退出测试。")
            break
        except Exception as e:
            print(f"\n❌ 发生异常: {e}")

def main() -> None:
    # 启动交互式聊天
    interactive_chat_test()

if __name__ == "__main__":
    main()