from aurora_bot.contracts.resource import ResourceKey, ResourceRef

RUN_STARTED = "engine.run.started"
RUN_COMPLETED = "engine.run.completed"
RUN_FAILED = "engine.run.failed"
RUN_SCOPE_PATTERN = "aurora:run/*"
RUN_INSTANCE_CONTRACT = ResourceRef(ResourceKey("aurora", "engine", "contract", "instance"), "1")


def run_scope(run_id: str) -> str:
    if not run_id.strip():
        raise ValueError("运行身份不能为空")
    return f"aurora:run/{run_id}"
