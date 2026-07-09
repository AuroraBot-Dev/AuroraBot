"""中央配置管理 —— 从 ``.env`` 加载环境变量并提供统一访问接口。

用法::

    from src.config import Config
    Config.LOG_LEVEL
    Config.ensure_dirs()
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parent.parent

_ENV_FILES = (
    (PROJECT_ROOT / ".env", False),
    (PROJECT_ROOT / ".env.dev", True),
    (PROJECT_ROOT / ".env.prod", False),
)
_DOTENV_MANAGED_SOURCES: dict[str, str] = dict(globals().get("_DOTENV_MANAGED_SOURCES", {}))


def reload_env() -> None:
    """Reload project dotenv files while preserving external environment precedence."""
    parsed_files: dict[str, dict[str, str | None]] = {}
    for path, _override in _ENV_FILES:
        parsed_files[str(path)] = dict(dotenv_values(path)) if path.exists() else {}

    for key, source in list(_DOTENV_MANAGED_SOURCES.items()):
        if key not in parsed_files.get(source, {}):
            os.environ.pop(key, None)
            del _DOTENV_MANAGED_SOURCES[key]

    for path, override in _ENV_FILES:
        source = str(path)
        for key, value in parsed_files[source].items():
            if value is None:
                continue
            if override or key not in os.environ or _DOTENV_MANAGED_SOURCES.get(key) == source:
                os.environ[key] = value
                _DOTENV_MANAGED_SOURCES[key] = source


reload_env()


def _get_bool(name: str, default: bool) -> bool:  # noqa: FBT001
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
    SANDBOX_DIR = DATA_DIR / "sandbox"
    SANDBOX_TEMP_DIR = SANDBOX_DIR / "temp"
    SANDBOX_OUTPUT_DIR = SANDBOX_DIR / "output"

    PROMPTS_DIR = SRC_ROOT / "prompts"
    TOPOLOGY_CONFIG = SRC_ROOT / "nodes" / "topology.yaml"

    # 日志配置
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LLM_GATEWAY_ENABLE_LOGGING_QUERIES: bool = _get_bool("LLM_GATEWAY_ENABLE_LOGGING_QUERIES", False)  # noqa: FBT003
    LLM_GATEWAY_ENABLE_LOGGING_RESPONSES: bool = _get_bool("LLM_GATEWAY_ENABLE_LOGGING_RESPONSES", False)  # noqa: FBT003

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

    # Sandbox 配置
    SANDBOX_EXEC_TIMEOUT: float = float(os.getenv("SANDBOX_EXEC_TIMEOUT", "30"))
    SANDBOX_MAX_MEMORY_MB: int = int(os.getenv("SANDBOX_MAX_MEMORY_MB", "256"))
    SANDBOX_MAX_OUTPUT_SIZE: int = int(os.getenv("SANDBOX_MAX_OUTPUT_SIZE", str(1024 * 1024)))

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
            Config.SANDBOX_DIR,
            Config.SANDBOX_TEMP_DIR,
            Config.SANDBOX_OUTPUT_DIR,
        ):
            path.mkdir(parents=True, exist_ok=True)


Config.ensure_dirs()
