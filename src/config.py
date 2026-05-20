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
    RUN_MODE: str = os.getenv("RUN_MODE", "prod")
    HEARTBEAT_INTERVAL: float = float(os.getenv("HEARTBEAT_INTERVAL", "1.0"))
    APP_FRAME_INTERVAL: float = float(os.getenv("APP_FRAME_INTERVAL", "1.0"))

    # MAX_ACTIONS_PER_BEAT: int = int(os.getenv("MAX_ACTIONS_PER_BEAT", "50"))
    # SELF_MAINTENANCE_INTERVAL: int = int(os.getenv("SELF_MAINTENANCE_INTERVAL", "12"))
    # QUEUES_RESTORE_ON_START: bool = _get_bool("QUEUES_RESTORE_ON_START", True)
    # SESSION_MAX_TOKENS: int = int(os.getenv("SESSION_MAX_TOKENS", "4000"))

    # 模型配置
    LITELLM_MODEL: str = os.getenv("LITELLM_MODEL", "deepseek/deepseek-v4-flash")
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "sk-xxx")
    AI_CONTEXT_CHAR_LIMIT: int = int(os.getenv("AI_CONTEXT_CHAR_LIMIT", "6000"))

    MEM0_API_KEY: str = os.getenv("MEM0_API_KEY", "m0-xxx")
    MEM0_API_BASE_URL: str = os.getenv("MEM0_API_BASE_URL", "https://api.mem0.ai")

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


Config.ensure_dirs()
