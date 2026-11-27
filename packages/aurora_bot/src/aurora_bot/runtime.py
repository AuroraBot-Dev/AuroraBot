"""绑定 AgentRuntime 与产品状态，负责恢复标记、运行结束后的保留策略和任务收束。"""

from typing import cast

from aurora_agent.react import AgentBusyError, ReActAgent
from aurora_agent.react_defaults import ReActContext
from aurora_agent.runtime import AgentRuntime
from aurora_control import ExecutionRequest
from aurora_core import plug
from aurora_core.components import ComponentFactory, InstanceExport
from aurora_core.ctx import StateKey
from aurora_core.json_data import encode_json

from .operations import RunOperations
from .plugins.runtime._meta import (
    AGENTS,
    CLEAN,
    MESSAGES,
    PREPARE,
    RUN,
    RUN_ACTIVATE,
    RUN_CANCEL,
    RUN_CONTROL,
    RUN_SUBMIT,
    START,
    STOP,
    WORK,
    runtime_plugin,
)

__all__ = ["AGENTS", "MESSAGES", "RUN", "WORK", "RuntimeOwner", "plugin"]


class RuntimeOwner:
    """持有唯一调度器；借用 agent、运行分发表和显式绑定的产品状态。"""

    def __init__(self, *, ctx, instance_id, states, options):
        self.ctx, self.instance_id, self.states = ctx, instance_id, states
        self.owner = options["owner"]
        self.agent: ReActAgent
        self.operations: RunOperations
        self._accepting = False
        self._executing = False
        self._last_request: ExecutionRequest | None = None
        self.runtime = AgentRuntime(
            get_agent=lambda: self.agent, execute=self._activate, is_executing=lambda: self._executing
        )

    def bind(self, *, agent, operations):
        self.agent, self.operations = agent, operations

    @plug(PREPARE)
    def prepare(self):
        for binding in (self.agent.runtime, self.states["work"]):
            for address in self.ctx.list(key=binding.key):
                if not set(binding.location).issubset(address.location):
                    continue
                value = self.ctx.get(address.key, location=dict(address.location))
                if isinstance(value, dict) and value.get("status") == "running":
                    self.ctx.set(
                        address.key,
                        {**value, "status": "failed", "error": "InterruptedRun"},
                        location=dict(address.location),
                    )

    @plug(START)
    def start(self):
        self.operations.bind(self.owner, self.runtime)
        self.runtime.start()
        self._accepting = True

    def stop_accepting(self):
        self._accepting = False
        self.runtime.stop_accepting()

    async def activate(self, request: ExecutionRequest) -> None:
        """等待一次显式激活，新的引导只写入 inbox；调用方负责结束后的 pending 复查。"""
        if self.runtime.current is not None:
            raise AgentBusyError("运行管理器已接管激活，不能混用调度所有者")
        await self._activate(request)

    async def _activate(self, request: ExecutionRequest) -> None:
        if not self._accepting:
            raise RuntimeError("运行所有者未启动或正在关闭")
        if self._executing:
            raise AgentBusyError("运行所有者正在运行，新引导应写入 inbox")
        self._executing = True
        self._last_request = request
        failure: BaseException | None = None
        try:
            await self.agent.execute(request)
        except BaseException as error:
            failure = error
            raise
        finally:
            try:
                self._compact()
            except BaseException as cleanup_error:
                if failure is not None:
                    raise failure from cleanup_error
                raise
            finally:
                self._executing = False

    def _compact(self) -> None:
        request = self._last_request or ExecutionRequest("maintenance")
        try:
            context = cast(ReActContext, self.states["context"].get(self.ctx, request))
        except KeyError:
            context = {"messages": [], "guidance_sequence": 0, "pending": None}
        keep = set()
        if self._last_request is not None:
            keep.add(self.states["model_output"].address(request))
        else:
            try:
                previous = self.agent.runtime.get(self.ctx, request)
            except KeyError:
                previous = None
            if isinstance(previous, dict) and isinstance(previous.get("run_id"), str):
                keep.add(self.states["model_output"].address(ExecutionRequest(previous["run_id"])))
        if context["pending"] is not None:
            keep.add(self.states["tool_output"].address(ExecutionRequest(context["pending"]["run_id"])))
        for address in self.ctx.list(key=self.states["work"].key):
            if set(self.states["work"].location).issubset(address.location) and address not in keep:
                self.ctx.delete(address.key, location=dict(address.location))
        self.agent.inbox.set(self.ctx, request, self.agent.pending(request))

    @plug(STOP)
    async def stop(self):
        await self.runtime.close()
        if self._executing:
            raise RuntimeError("停止前须通过宿主结束在途激活")
        self._compact()

    @plug(CLEAN)
    def clean(self):
        self.operations.unbind(self.owner, self.runtime)


def validate_json(value):
    encode_json(value)


def plugin():
    operations = RunOperations()
    return runtime_plugin(
        targets={
            **{identity: StateKey(validate_json) for identity in (AGENTS, MESSAGES, RUN, WORK)},
            RUN_CONTROL: operations,
            RUN_SUBMIT: operations.submit,
            RUN_ACTIVATE: operations.activate,
            RUN_CANCEL: operations.cancel,
        },
        components={
            "operations": ComponentFactory(
                lambda registry: registry.get(RUN_CONTROL).target,
                lambda instance: InstanceExport(resources={"operations": instance}),
            ),
            "runtime": ComponentFactory(
                RuntimeOwner,
                lambda instance: InstanceExport(
                    plugs={
                        PREPARE: instance.prepare,
                        START: instance.start,
                        STOP: instance.stop,
                        CLEAN: instance.clean,
                    },
                    resources={"runtime": instance.runtime, "owner": instance},
                    stop_accepting=instance.stop_accepting,
                ),
                plugs=(RuntimeOwner.prepare, RuntimeOwner.start, RuntimeOwner.stop, RuntimeOwner.clean),
                bind=lambda instance, resources: instance.bind(**resources),
            ),
        },
    )
