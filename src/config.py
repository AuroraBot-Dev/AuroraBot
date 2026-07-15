"""The public configuration entry point for AuroraBot.

Structural configuration is loaded exclusively from RFC 0002 TOML files.  The
``Config`` facade exposes a small read-only set of shared paths and model
aliases for independent utility and Provider components.
"""

from __future__ import annotations

from pathlib import Path

from src.localhost.configuration import AuroraConfig, load_configuration

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_EMBEDDING_MODEL = "openai/text-embedding-3-small"


def load_config(root: Path | None = None, profile: str | None = None) -> AuroraConfig:
    """Load one validated, immutable configuration snapshot."""
    return load_configuration(root or PROJECT_ROOT, profile)


class Config:
    """Read-only facade backed by the validated TOML snapshot.

    Domain services should accept an :class:`AuroraConfig` snapshot explicitly.
    This facade never reads structural values from environment variables.
    """

    PROJECT_ROOT: Path
    SRC_ROOT: Path
    LOG_DIR: Path
    DATA_DIR: Path
    APP_DATA_DIR: Path
    KERNEL_DATA_DIR: Path
    SANDBOX_DIR: Path
    SANDBOX_TEMP_DIR: Path
    SANDBOX_OUTPUT_DIR: Path
    SANDBOX_EXEC_TIMEOUT: float
    SANDBOX_MAX_OUTPUT_SIZE: int
    LOG_LEVEL: str
    LLM_GATEWAY_FAST_MODEL: str
    LLM_GATEWAY_QUALITY_MODEL: str
    LLM_GATEWAY_MULTIMODAL_MODEL: str
    LLM_GATEWAY_EMBEDDING_MODEL: str
    LLM_GATEWAY_RERANKER_MODEL: str
    LLM_GATEWAY_ENABLE_LOGGING_QUERIES: bool
    LLM_GATEWAY_ENABLE_LOGGING_RESPONSES: bool
    _snapshot: AuroraConfig

    @classmethod
    def reload(cls, root: Path | None = None, profile: str | None = None) -> AuroraConfig:
        """Refresh the facade from TOML; intended for startup and tests only."""
        snapshot = load_config(root, profile)
        root_path = snapshot.root
        data_dir = root_path / "data"
        cls._snapshot = snapshot
        cls.PROJECT_ROOT = root_path
        cls.SRC_ROOT = root_path / "src"
        cls.LOG_DIR = root_path / "logs"
        cls.DATA_DIR = data_dir
        cls.APP_DATA_DIR = data_dir / "app_data"
        cls.KERNEL_DATA_DIR = snapshot.runtime.workspace
        cls.SANDBOX_DIR = data_dir / "sandbox"
        cls.SANDBOX_TEMP_DIR = cls.SANDBOX_DIR / "temp"
        cls.SANDBOX_OUTPUT_DIR = cls.SANDBOX_DIR / "output"
        cls.SANDBOX_EXEC_TIMEOUT = 30.0
        cls.SANDBOX_MAX_OUTPUT_SIZE = 50_000
        cls.LOG_LEVEL = snapshot.logging_level
        roles = {role: f"{settings.provider}/{settings.model}" for role, settings in snapshot.model_definitions.items()}
        cls.LLM_GATEWAY_FAST_MODEL = roles.get("fast", "")
        cls.LLM_GATEWAY_QUALITY_MODEL = roles.get("quality", "")
        # Shared aliases do not authorize Node access to undeclared roles.
        cls.LLM_GATEWAY_MULTIMODAL_MODEL = roles.get("multimodal", cls.LLM_GATEWAY_QUALITY_MODEL)
        cls.LLM_GATEWAY_EMBEDDING_MODEL = roles.get("embedding", _DEFAULT_EMBEDDING_MODEL)
        cls.LLM_GATEWAY_RERANKER_MODEL = roles.get("reranker", "")
        cls.LLM_GATEWAY_ENABLE_LOGGING_QUERIES = snapshot.model_logging.log_queries
        cls.LLM_GATEWAY_ENABLE_LOGGING_RESPONSES = snapshot.model_logging.log_responses
        cls.ensure_dirs()
        return snapshot

    @classmethod
    def snapshot(cls) -> AuroraConfig:
        """Return the immutable configuration backing this shared view."""
        return cls._snapshot

    @classmethod
    def ensure_dirs(cls) -> None:
        """Create non-Kernel storage directories used by independent components."""
        for path in (
            cls.LOG_DIR,
            cls.APP_DATA_DIR,
            cls.SANDBOX_TEMP_DIR,
            cls.SANDBOX_OUTPUT_DIR,
        ):
            path.mkdir(parents=True, exist_ok=True)


Config.reload()
