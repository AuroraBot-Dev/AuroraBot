"""localhost 独立运行时调试 API。"""

from typing import Any

from fastapi import FastAPI, HTTPException

from src.contracts.amp import AmpValidationError
from src.contracts.ports import DashboardDebugPort


def create_debug_app(debug: DashboardDebugPort) -> FastAPI:
    """创建只依赖 localhost 调试端口的 FastAPI 应用。"""
    app = FastAPI(title="Aurora localhost", version="1")

    @app.post("/v1/debug/amp", status_code=202)
    async def submit_amp(value: dict[str, Any]) -> dict[str, str]:
        try:
            return {"message_id": await debug.submit_amp(value)}
        except AmpValidationError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/v1/debug/pump")
    async def pump(max_turns: int = 8) -> dict[str, Any]:
        if not 1 <= max_turns <= 100:  # noqa: PLR2004 - 公共调试安全边界
            raise HTTPException(status_code=422, detail="max_turns 必须在 1 到 100 之间")
        return await debug.pump(max_turns)

    @app.get("/v1/debug/status")
    def status() -> dict[str, Any]:
        return debug.status()

    @app.get("/v1/debug/tasks/{task_id}")
    def task(task_id: str) -> dict[str, Any]:
        value = debug.task(task_id)
        if value is None:
            raise HTTPException(status_code=404, detail="Task 未找到")
        return value

    @app.get("/v1/debug/agents/{agent_id}")
    def agent(agent_id: str) -> dict[str, Any]:
        value = debug.agent(agent_id)
        if value is None:
            raise HTTPException(status_code=404, detail="Agent 未找到")
        return value

    @app.get("/v1/debug/brain-context")
    def brain_context() -> dict[str, Any]:
        return debug.brain_context()

    return app
