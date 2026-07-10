"""The single public configuration entry point for AuroraBot vNext.

Structural configuration is loaded exclusively from RFC 0002 TOML files.  The
``Config`` facade retains the small set of path and model aliases needed by
extracted legacy modules, but those modules are not enabled in the vNext
runtime unless a later accepted RFC explicitly integrates them.
"""

from __future__ import annotations

from pathlib import Path

from src.localhost.configuration import AuroraConfig, load_configuration

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_COMPATIBILITY_EMBEDDING_MODEL = "openai/text-embedding-3-small"


def load_config(root: Path | None = None, profile: str | None = None) -> AuroraConfig:
    """Load one validated, immutable vNext configuration snapshot."""
    return load_configuration(root or PROJECT_ROOT, profile)


class Config:
    """Compatibility facade backed by the validated vNext TOML snapshot.

    New code should accept an :class:`AuroraConfig` snapshot explicitly.  This
    class exists for extracted code that previously imported ``src.config``;
    it never reads structural values from environment variables.
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
    LOG_LEVEL: str
    LLM_GATEWAY_FAST_MODEL: str
    LLM_GATEWAY_QUALITY_MODEL: str
    LLM_GATEWAY_MULTIMODAL_MODEL: str
    LLM_GATEWAY_EMBEDDING_MODEL: str
    LLM_GATEWAY_RERANKER_MODEL: str
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
        cls.LOG_LEVEL = snapshot.logging_level
        roles = {
            role: f"{settings.provider}/{settings.model}"
            for role, settings in snapshot.model_definitions.items()
        }
        cls.LLM_GATEWAY_FAST_MODEL = roles.get("fast", "")
        cls.LLM_GATEWAY_QUALITY_MODEL = roles.get("quality", "")
        # RFC 0005 is still a draft, while the extracted gateway requires
        # these two legacy roles merely to initialize.  They remain outside
        # the vNext runtime and must not be treated as declared node access.
        cls.LLM_GATEWAY_MULTIMODAL_MODEL = roles.get("multimodal", cls.LLM_GATEWAY_QUALITY_MODEL)
        cls.LLM_GATEWAY_EMBEDDING_MODEL = roles.get("embedding", _COMPATIBILITY_EMBEDDING_MODEL)
        cls.LLM_GATEWAY_RERANKER_MODEL = roles.get("reranker", "")
        cls.ensure_dirs()
        return snapshot

    @classmethod
    def snapshot(cls) -> AuroraConfig:
        """Return the immutable configuration backing this compatibility view."""
        return cls._snapshot

    @classmethod
    def ensure_dirs(cls) -> None:
        """Create non-Kernel compatibility storage directories when needed."""
        for path in (
            cls.LOG_DIR,
            cls.APP_DATA_DIR,
            cls.SANDBOX_TEMP_DIR,
            cls.SANDBOX_OUTPUT_DIR,
        ):
            path.mkdir(parents=True, exist_ok=True)

Config.reload()
