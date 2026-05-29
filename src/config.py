import os
from pathlib import Path
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(PROJECT_ROOT / ".env")
if (PROJECT_ROOT / ".env.dev").exists():
    load_dotenv(PROJECT_ROOT / ".env.dev", override=True)
if (PROJECT_ROOT / ".env.prod").exists():
    load_dotenv(PROJECT_ROOT / ".env.prod", override=False)


def _get_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


class Config:
    # 路径相关配置
    PROJECT_ROOT = PROJECT_ROOT
    SRC_ROOT = PROJECT_ROOT / "src"
    LOG_DIR = PROJECT_ROOT / "logs"
    DATA_DIR = PROJECT_ROOT / "data"
    APP_DIR = PROJECT_ROOT / "apps"

    APP_DATA_DIR = DATA_DIR / "app_data"
    MEMORY_DATA_DIR = DATA_DIR / "memory"
    KERNEL_DATA_DIR = DATA_DIR / "kernel"

    PROMPTS_DIR = SRC_ROOT / "brain" / "prompts"
    TOPOLOGY_CONFIG = SRC_ROOT / "brain" / "nodes" / "topology.yaml"

    # QUEUES_SNAPSHOT_FILE = QUEUES_DATA_DIR / "runtime_queues.json"
    # EPISODIC_MEMORY_FILE = MEMORY_DATA_DIR / "episodes.json"
    # SEMANTIC_MEMORY_FILE = MEMORY_DATA_DIR / "semantic_memory.json"
    # SEMANTIC_SNAPSHOT_FILE = MEMORY_DATA_DIR / "semantic_snapshot.txt"

    # 日志配置
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    # 兼容旧配置 AI_QUERY_DEBUG, 同时提供更明确的 LLM 请求/响应日志开关.
    LLM_LOG_QUERY: bool = _get_bool(
        "LLM_LOG_QUERY",
        _get_bool("AI_QUERY_DEBUG", False),
    )
    LLM_LOG_RESPONSE: bool = _get_bool(
        "LLM_LOG_RESPONSE",
        _get_bool("AI_QUERY_DEBUG", False),
    )
    LLM_LOG_MAX_CHARS: int = int(os.getenv("LLM_LOG_MAX_CHARS", "2000"))

    CAPABILITY_LOG_EXECUTION: bool = _get_bool("CAPABILITY_LOG_EXECUTION", False)

    # 核心配置
    DEVELOPER_QQ: str = os.getenv("DEVELOPER_QQ", "10001")
    RUN_MODE: str = os.getenv("RUN_MODE", "prod")
    HEARTBEAT_INTERVAL: float = float(os.getenv("HEARTBEAT_INTERVAL", "1.0"))
    APP_FRAME_INTERVAL: float = float(os.getenv("APP_FRAME_INTERVAL", "1.0"))
    EVENT_BRIDGE_INTERVAL: float = float(os.getenv("EVENT_BRIDGE_INTERVAL", "1.5"))

    # MAX_ACTIONS_PER_BEAT: int = int(os.getenv("MAX_ACTIONS_PER_BEAT", "50"))
    # SELF_MAINTENANCE_INTERVAL: int = int(os.getenv("SELF_MAINTENANCE_INTERVAL", "12"))
    # QUEUES_RESTORE_ON_START: bool = _get_bool("QUEUES_RESTORE_ON_START", True)
    # SESSION_MAX_TOKENS: int = int(os.getenv("SESSION_MAX_TOKENS", "4000"))

    # 模型配置 (新统一网关)
    LLM_GATEWAY_FAST_MODEL: str = os.getenv(
        "LLM_GATEWAY_FAST_MODEL", "deepseek/deepseek-chat"
    )
    LLM_GATEWAY_QUALITY_MODEL: str = os.getenv(
        "LLM_GATEWAY_QUALITY_MODEL", "deepseek/deepseek-reasoner"
    )
    LLM_GATEWAY_MULTIMODAL_MODEL: str = os.getenv(
        "LLM_GATEWAY_MULTIMODAL_MODEL", "deepseek/deepseek-chat"
    )
    LLM_GATEWAY_EMBEDDING_MODEL: str = os.getenv(
        "LLM_GATEWAY_EMBEDDING_MODEL", "BAAI/bge-m3"
    )
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "sk-xxx")
    AI_CONTEXT_CHAR_LIMIT: int = int(os.getenv("AI_CONTEXT_CHAR_LIMIT", "6000"))
    LLM_TIMEOUT: float = float(os.getenv("LLM_TIMEOUT", "120"))
    LLM_GATE_TIMEOUT: float = float(os.getenv("LLM_GATE_TIMEOUT", "30"))
    MEMORY_RETRIEVE_TIMEOUT: float = float(os.getenv("MEMORY_RETRIEVE_TIMEOUT", "30"))

    # MEM0_API_KEY: str = os.getenv("MEM0_API_KEY", "m0-xxx")
    # MEM0_API_BASE_URL: str = os.getenv("MEM0_API_BASE_URL", "https://api.mem0.ai")

    @staticmethod
    def ensure_dirs() -> None:
        for path in (
            Config.LOG_DIR,
            Config.DATA_DIR,
            Config.APP_DATA_DIR,
            Config.SRC_ROOT,
            Config.PROMPTS_DIR,
            Config.KERNEL_DATA_DIR,
            Config.MEMORY_DATA_DIR,
        ):
            path.mkdir(parents=True, exist_ok=True)

    # 记忆配置
    MEM0_VECTOR_STORE: str = os.getenv("MEM0_VECTOR_STORE", "chroma")
    MEM0_COLLECTION_NAME: str = os.getenv("MEM0_COLLECTION_NAME", "aurora_memory_bgem3")
    MEM0_STORE_PATH: Path = MEMORY_DATA_DIR / "mem0"

    MEM0_EMBEDDER_PROVIDER: str = os.getenv("MEM0_EMBEDDER_PROVIDER", "openai")
    MEM0_EMBEDDER_API_KEY: str = os.getenv("MEM0_EMBEDDER_API_KEY", "")
    MEM0_EMBEDDER_BASE_URL: str = os.getenv(
        "MEM0_EMBEDDER_BASE_URL",
        "https://api.siliconflow.cn/v1",
    )
    MEM0_EMBEDDER_MODEL: str = os.getenv("MEM0_EMBEDDER_MODEL", "BAAI/bge-m3")

    MEM0_LLM_PROVIDER: str = os.getenv("MEM0_LLM_PROVIDER", "openai")
    MEM0_LLM_API_KEY: str = os.getenv("MEM0_LLM_API_KEY", DEEPSEEK_API_KEY)
    MEM0_LLM_BASE_URL: str = os.getenv("MEM0_LLM_BASE_URL", "https://api.deepseek.com")
    MEM0_LLM_MODEL: str = os.getenv("MEM0_LLM_MODEL", "deepseek-chat")


Config.ensure_dirs()
