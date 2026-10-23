"""通用实例管理与调用记录；业务操作和状态投影由模块声明，不假定 Agent 行为。"""

from __future__ import annotations

import inspect
from contextlib import AbstractAsyncContextManager, AsyncExitStack, contextmanager, suppress
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from playground.workspace.records import Archive, Checkpoint, Inspection, InvocationError, ReplayResult

if TYPE_CHECKING:
    from collections.abc import Awaitable, Iterator

    from playground.protocol import Model, Operation
    from playground.workspace.spec import WorkspaceSpec

_RESERVED = {"create", "reset", "export", "replay", "close"}


async def resolve(value: Model | Awaitable[Model]) -> Model:
    return await value if inspect.isawaitable(value) else value


@dataclass(slots=True)
class Instance:
    configuration: Model
    value: Any
    resources: AsyncExitStack
    initial: dict[str, Any]
    checkpoints: list[Checkpoint] = field(default_factory=list)


class Workspace:
    def __init__(self, module: str, specification: WorkspaceSpec) -> None:
        self.module, self.spec = module, specification
        self.operations: dict[str, Operation] = {}
        for operation in (specification.snapshot, *specification.operations):
            if operation.name in self.operations or operation.name in _RESERVED:
                raise ValueError(f"工作台操作名称冲突：{operation.name}")
            if specification.identity in operation.input_type.model_fields:
                raise ValueError("操作参数不能占用工作台身份字段")
            self.operations[operation.name] = operation
        for query in (specification.snapshot, self.operations.get("inspect")):
            if query is not None and (query.record or query.input_type.model_fields):
                raise ValueError("快照和 inspect 必须是无参数、无需记录的查询")
        if specification.identity in specification.configuration.model_fields:
            raise ValueError("配置不能占用工作台身份字段")
        if not module.strip() or not specification.revision.strip() or not specification.default_id.strip():
            raise ValueError("模块名称、版本和默认身份不能为空")
        self._instances: dict[str, Instance] = {}
        self._busy: set[str] = set()
        self.closed = False

    @property
    def active(self) -> bool:
        return bool(self._instances)

    @contextmanager
    def claim(self, instance_id: str) -> Iterator[None]:
        if self.closed or not instance_id.strip():
            raise RuntimeError("工作台已关闭或实例身份为空")
        if instance_id in self._busy:
            raise RuntimeError("同一实例不能并发调用、重置或关闭")
        self._busy.add(instance_id)
        try:
            yield
        finally:
            self._busy.remove(instance_id)

    async def build(self, configuration: Model, instance_id: str) -> tuple[Instance, Model]:
        resources = AsyncExitStack()
        try:
            context = self.spec.open(configuration.model_copy(deep=True), instance_id)
            value = (
                await resources.enter_async_context(context)
                if isinstance(context, AbstractAsyncContextManager)
                else resources.enter_context(context)
            )
            state = await self.query(self.spec.snapshot, value)
            return Instance(configuration.model_copy(deep=True), value, resources, self.spec.project(state)), state
        except BaseException:
            await resources.aclose()
            raise

    async def create(self, configuration: dict[str, Any], instance_id: str = "default") -> Model:
        parsed = self.spec.configuration.model_validate(configuration)
        with self.claim(instance_id):
            if instance_id in self._instances:
                raise ValueError(f"实例已存在：{instance_id}")
            instance, state = await self.build(parsed, instance_id)
            self._instances[instance_id] = instance
            return state

    async def ensure(self, instance_id: str) -> Instance:
        if instance_id not in self._instances and self.spec.implicit:
            await self.create({}, instance_id)
        if instance_id not in self._instances:
            raise ValueError(f"实例不存在，请先 create：{instance_id}")
        return self._instances[instance_id]

    async def query(self, operation: Operation, value: Any) -> Model:
        result = await resolve(operation.handler(value))
        return operation.output_type.model_validate(result)

    async def snapshot(self, instance_id: str = "default") -> Model:
        instance = await self.ensure(instance_id)
        with self.claim(instance_id):
            return await self.query(self.spec.snapshot, instance.value)

    async def call(self, instance_id: str, operation: str, arguments: dict[str, Any] | None = None) -> Model:
        declaration = self.operations[operation]
        parsed = declaration.input_type.model_validate(arguments or {})
        instance = await self.ensure(instance_id)
        with self.claim(instance_id):
            output, error_type = None, None
            try:
                result = await resolve(declaration.handler(instance.value, **parsed.model_dump()))
                result = declaration.output_type.model_validate(result)
                output = self.spec.project(result)
                return result
            except Exception as error:
                error_type = type(error).__name__
                raise InvocationError(f"操作失败：{error_type}；使用 inspect 查看保留的状态。") from error
            except BaseException as error:
                error_type = type(error).__name__
                raise
            finally:
                if declaration.record:
                    state = await self.query(self.spec.snapshot, instance.value)
                    instance.checkpoints.append(
                        Checkpoint(
                            operation=operation,
                            input=parsed.model_dump(mode="json"),
                            output=output,
                            state=self.spec.project(state),
                            error_type=error_type,
                        )
                    )

    async def reset(self, instance_id: str = "default", configuration: dict[str, Any] | None = None) -> Model:
        parsed = self.spec.configuration.model_validate(configuration) if configuration is not None else None
        old = await self.ensure(instance_id)
        parsed = old.configuration if parsed is None else parsed
        with self.claim(instance_id):
            replacement, state = await self.build(parsed, instance_id)
            self._instances[instance_id] = replacement
            # 装配失败保留旧实例；替换成功后，即使旧资源清理失败也不再暴露旧实例。
            await old.resources.aclose()
            return state

    async def inspect(self, instance_id: str = "default") -> Model:
        if "inspect" in self.operations:
            return await self.call(instance_id, "inspect")
        instance = await self.ensure(instance_id)
        state = await self.snapshot(instance_id)
        return Inspection(
            configuration=instance.configuration.model_dump(mode="json"),
            state=self.spec.project(state),
            calls=[
                {"sequence": index, "operation": item.operation, "error_type": item.error_type}
                for index, item in enumerate(instance.checkpoints, 1)
            ],
        )

    async def export(self, instance_id: str = "default") -> Archive:
        inspection = await self.inspect(instance_id)
        instance = await self.ensure(instance_id)
        with self.claim(instance_id):
            return Archive(
                module=self.module,
                revision=self.spec.revision,
                instance_id=instance_id,
                configuration=instance.configuration.model_dump(mode="json"),
                initial=instance.initial,
                checkpoints=instance.checkpoints,
                inspection=self.spec.project(inspection),
            ).model_copy(deep=True)

    async def replay(self, archive: Archive, instance_id: str = "replay") -> ReplayResult:
        if archive.module != self.module or archive.revision != self.spec.revision:
            raise ValueError("记录的模块或版本与当前声明不符")
        if not self.spec.isolated:
            raise ValueError("此装配未声明为隔离环境，禁止自动复现")
        # 在任何装配效果之前验证完整序列；记录中的字段不能提升声明的重放权限。
        self.spec.configuration.model_validate(archive.configuration)
        for checkpoint in archive.checkpoints:
            operation = self.operations.get(checkpoint.operation)
            if operation is None or not operation.record or not operation.replayable:
                raise ValueError(f"操作不允许复现：{checkpoint.operation}")
            operation.input_type.model_validate(checkpoint.input)
        await self.create(archive.configuration, instance_id)
        instance = await self.ensure(instance_id)
        differences = [] if instance.initial == archive.initial else ["initial"]
        for index, checkpoint in enumerate(archive.checkpoints):
            with suppress(InvocationError):
                await self.call(instance_id, checkpoint.operation, checkpoint.input)
            if instance.checkpoints[-1] != checkpoint:
                differences.append(f"checkpoints[{index}]")
        if self.spec.project(await self.inspect(instance_id)) != archive.inspection:
            differences.append("inspection")
        state = await self.snapshot(instance_id)
        return ReplayResult(matched=not differences, differences=differences, state=state.model_dump(mode="json"))

    async def dispose(self, instance_id: str) -> None:
        with self.claim(instance_id):
            instance = self._instances.pop(instance_id)
            await instance.resources.aclose()

    async def close(self) -> None:
        if self._busy:
            raise RuntimeError("仍有执行中的实例，不能关闭工作台")
        self.closed = True
        instances, self._instances = self._instances, {}
        async with AsyncExitStack() as resources:
            for instance in instances.values():
                resources.push_async_callback(instance.resources.aclose)
