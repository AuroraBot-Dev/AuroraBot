"""按 bot 实例定位运行管理器；公共操作定义与运行实例分别管理。"""

from aurora_adapter.model import JsonValue
from aurora_agent.runtime import AgentRuntime, RunHandle, Submission
from aurora_core import Id, operation

RUN_CONTROL = Id("org.aurora.bot:services/run_control")
RUN_SUBMIT = Id("org.aurora.bot:operations/run/submit")
RUN_ACTIVATE = Id("org.aurora.bot:operations/run/activate")
RUN_CANCEL = Id("org.aurora.bot:operations/run/cancel")


class RunOperations:
    """每份插件清单持有独立分发表；只保存运行期引用，不进入 ctx 快照。

    instance_id 为 bot 配置中的实例身份，必须显式提供。提交与激活沿用进程内
    Submission/RunHandle 返回值；传输层须显式转换回执，不直接序列化运行句柄。
    """

    def __init__(self) -> None:
        self._runtimes: dict[str, AgentRuntime] = {}

    @property
    def instances(self) -> tuple[str, ...]:
        """当前已绑定的 bot 实例；不创建或启动运行资源。"""
        return tuple(self._runtimes)

    def bind(self, instance_id: str, runtime: AgentRuntime) -> None:
        """由装配在启动时绑定，禁止相同实例身份覆盖既有目标。"""
        if not isinstance(instance_id, str) or not instance_id:
            raise ValueError("bot 实例身份必须为非空字符串")
        if instance_id in self._runtimes:
            raise ValueError(f"bot 运行入口已经绑定：{instance_id}")
        self._runtimes[instance_id] = runtime

    def unbind(self, instance_id: str, runtime: AgentRuntime) -> None:
        """仅解除指定所有者的绑定，清理失败重试不会删除其他实例。"""
        if self._runtimes.get(instance_id) is runtime:
            del self._runtimes[instance_id]

    def _runtime(self, instance_id: str) -> AgentRuntime:
        if not isinstance(instance_id, str) or not instance_id:
            raise ValueError("bot 实例身份必须为非空字符串")
        try:
            return self._runtimes[instance_id]
        except KeyError:
            raise LookupError(f"bot 运行入口未绑定：{instance_id}") from None

    @operation(RUN_SUBMIT)
    def submit(self, payload: JsonValue, *, instance_id: str, sequence: int | None = None) -> Submission:
        """向指定 bot 提交引导，返回接纳序号及可等待的运行句柄。"""
        return self._runtime(instance_id).submit(payload, sequence=sequence)

    @operation(RUN_ACTIVATE)
    def activate(self, *, instance_id: str) -> RunHandle:
        """显式激活指定 bot，已有活动阶段复用其运行句柄。"""
        return self._runtime(instance_id).activate()

    @operation(RUN_CANCEL)
    async def cancel(self, run_id: str, *, instance_id: str) -> bool:
        """按 bot 实例及 run_id 取消并等待清理，未匹配到在途运行时返回 False。"""
        return await self._runtime(instance_id).cancel(run_id)
