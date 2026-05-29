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
    # 路径配置
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

    # 日志配置
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # 核心配置
    RUN_MODE: str = os.getenv("RUN_MODE", "prod")
    HEARTBEAT_INTERVAL: float = float(os.getenv("HEARTBEAT_INTERVAL", "1.0"))
    APP_FRAME_INTERVAL: float = float(os.getenv("APP_FRAME_INTERVAL", "1.0"))
    EVENT_BRIDGE_INTERVAL: float = float(os.getenv("EVENT_BRIDGE_INTERVAL", "1.5"))

    # 模型配置
    LLM_GATEWAY_FAST_MODEL: str = os.getenv(
        "LLM_GATEWAY_FAST_MODEL",
        "openai/gpt-4o-mini",
    )
    LLM_GATEWAY_QUALITY_MODEL: str = os.getenv(
        "LLM_GATEWAY_QUALITY_MODEL",
        "openai/gpt-4o",
    )
    LLM_GATEWAY_MULTIMODAL_MODEL: str = os.getenv(
        "LLM_GATEWAY_MULTIMODAL_MODEL",
        "openai/gpt-4o",
    )
    LLM_GATEWAY_EMBEDDING_MODEL: str = os.getenv(
        "LLM_GATEWAY_EMBEDDING_MODEL",
        "openai/text-embedding-3-small",
    )
    LLM_GATEWAY_RERANKER_MODEL: str = os.getenv(
        "LLM_GATEWAY_RERANKER_MODEL",
        "",
    )

    # 超时配置
    LLM_GATE_TIMEOUT: float = float(os.getenv("LLM_GATE_TIMEOUT", "30"))
    MEMORY_RETRIEVE_TIMEOUT: float = float(os.getenv("MEMORY_RETRIEVE_TIMEOUT", "30"))

    # 记忆配置
    MEMORY_VECTOR_STORE: str = os.getenv("MEMORY_VECTOR_STORE", "chroma")
    MEMORY_COLLECTION_NAME: str = os.getenv("MEMORY_COLLECTION_NAME", "mem_openai")
    MEMORY_MODEL_PROVIDER: str = os.getenv("MEMORY_MODEL_PROVIDER", "litellm")

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
