"""Sandbox-local defaults that do not depend on the application configuration layer."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SANDBOX_DIR = PROJECT_ROOT / "data" / "sandbox"
SANDBOX_TEMP_DIR = SANDBOX_DIR / "temp"
SANDBOX_OUTPUT_DIR = SANDBOX_DIR / "output"
SANDBOX_EXEC_TIMEOUT = 30.0
SANDBOX_MAX_OUTPUT_SIZE = 50_000
