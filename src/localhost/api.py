"""RFC 0006 FastAPI adapter for the localhost runtime use case."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, status

from src.kernel.events import AmpValidationError
from src.localhost.runtime import AuroraRuntime


def create_app(
    root: Path,
    profile: str | None = None,
    *,
    runtime: AuroraRuntime | None = None,
    manage_runtime: bool = True,
) -> FastAPI:
    """Create the developer-only HTTP adapter around a configured local runtime."""
    runtime = runtime or AuroraRuntime.create(root, profile)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if not manage_runtime:
            yield
            return
        stop = asyncio.Event()
        scheduler = asyncio.create_task(runtime.run_forever(stop), name="aurora-cognitive-scheduler")
        try:
            yield
        finally:
            stop.set()
            await asyncio.gather(scheduler, return_exceptions=True)
            await runtime.shutdown()

    app = FastAPI(title="AuroraBot local debug API", version="0.4.0", lifespan=lifespan)

    @app.get("/healthz")
    def health() -> dict[str, object]:
        return {"status": "ok", "profile": runtime.configuration.runtime.profile}

    @app.post("/v1/debug/amp", status_code=status.HTTP_202_ACCEPTED)
    async def submit_amp(value: dict[str, Any]) -> dict[str, str]:
        try:
            return {"message_id": await runtime.submit_amp(value)}
        except AmpValidationError as error:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error

    @app.post("/v1/debug/cycles")
    async def run_cycle() -> dict[str, Any]:
        return await runtime.run_cycle()

    @app.get("/v1/debug/records/{record_id}")
    def get_record(record_id: str) -> dict[str, Any]:
        record = runtime.record(record_id)
        if record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="record not found")
        return record

    @app.get("/v1/debug/status")
    def get_status() -> dict[str, Any]:
        return runtime.status()

    @app.get("/v1/debug/episodes/{episode_id}")
    def get_episode(episode_id: str) -> dict[str, Any]:
        episode = runtime.episode(episode_id)
        if episode is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="episode not found")
        return episode

    return app
