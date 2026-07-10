"""RFC 0006 FastAPI adapter for the localhost runtime use case."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, status

from src.kernel.events import AmpValidationError
from src.localhost.runtime import AuroraRuntime


def create_app(root: Path, profile: str | None = None) -> FastAPI:
    """Create the developer-only HTTP adapter around a configured local runtime."""
    runtime = AuroraRuntime.create(root, profile)
    app = FastAPI(title="AuroraBot local debug API", version="0.4.0")

    @app.get("/healthz")
    def health() -> dict[str, object]:
        return {"status": "ok", "profile": runtime.configuration.runtime.profile}

    @app.post("/v1/debug/amp", status_code=status.HTTP_202_ACCEPTED)
    def submit_amp(value: dict[str, Any]) -> dict[str, str]:
        try:
            return {"message_id": runtime.submit_amp(value)}
        except AmpValidationError as error:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error

    @app.post("/v1/debug/cycles")
    def run_cycle() -> dict[str, Any]:
        return runtime.run_cycle()

    @app.get("/v1/debug/records/{record_id}")
    def get_record(record_id: str) -> dict[str, Any]:
        record = runtime.record(record_id)
        if record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="record not found")
        return record

    return app
