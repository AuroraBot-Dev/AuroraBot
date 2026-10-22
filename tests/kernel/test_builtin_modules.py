"""内建自描述模块经微内核装配的结构与接线测试。"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from aurora_bot.agents.config import AgentConfig, AgentsConfig
from aurora_bot.ai.config import EndpointConfig, EndpointsConfig, ProviderConfig, ProvidersConfig
from aurora_bot.artifacts.config import ArtifactsConfig
from aurora_bot.bot.config import BotConfig
from aurora_bot.cadence.config import CadenceConfig, ReactionsConfig
from aurora_bot.contracts.identity import TagsConfig
from aurora_bot.contracts.scope import ScopeCatalog, ScopeDeclaration, ScopeKind
from aurora_bot.engine.config import EngineConfig
from aurora_bot.kernel import BuiltinSource, compose, resolve
from aurora_bot.mcp.config import AppConfig, AppsConfig, PlatformConfig, PlatformsConfig
from aurora_bot.memory.config import MemoryConfig
from aurora_bot.memory_model.config import MemoryModelConfig
from aurora_bot.prompt.config import PromptConfig, PromptsConfig
from aurora_bot.rhythm.config import RhythmConfig
from aurora_bot.runtime.config import RuntimeConfig
from aurora_bot.world.config import StorageConfig, StorageEntry

if TYPE_CHECKING:
    from pathlib import Path


class _Settings:
    def __init__(self, project_root: Path, values: dict[type, object]) -> None:
        self._project_root = project_root
        self._values = values

    @property
    def project_root(self) -> Path:
        return self._project_root

    def resolve[T](self, config_type: type[T]) -> T:
        return cast("T", self._values[config_type])


def _settings(tmp_path: Path) -> _Settings:
    prompts = tmp_path / "config" / "prompts"
    prompts.mkdir(parents=True)
    (prompts / "system.txt").write_text("系统提示", encoding="utf-8")
    (prompts / "chat.txt").write_text("会话提示", encoding="utf-8")
    return _Settings(
        tmp_path,
        {
            ProvidersConfig: ProvidersConfig((ProviderConfig("test:ai/provider/provider", "litellm", "API_KEY"),)),
            EndpointsConfig: EndpointsConfig(
                (EndpointConfig("test:ai/endpoint/chat", "test:ai/provider/provider", "gpt"),)
            ),
            PromptsConfig: PromptsConfig(
                (
                    PromptConfig("aurora:prompt/system/core", "system.txt"),
                    PromptConfig("aurora:prompt/agent/chat", "chat.txt"),
                )
            ),
            AgentsConfig: AgentsConfig(
                (
                    AgentConfig(
                        "aurora:agent/definition/chat",
                        "会话",
                        "aurora:prompt/agent/chat",
                        "test:ai/endpoint/chat",
                        (),
                    ),
                )
            ),
            EngineConfig: EngineConfig(2, 8, 16),
            BotConfig: BotConfig("aurora:bot/default"),
            RuntimeConfig: RuntimeConfig("default", "aurora:agent/definition/chat", "NONE"),
            MemoryConfig: MemoryConfig(60, 10, (), ()),
            MemoryModelConfig: MemoryModelConfig(),
            ArtifactsConfig: ArtifactsConfig(),
            CadenceConfig: CadenceConfig(False, "aurora:agent/definition/chat", 0.25),
            RhythmConfig: RhythmConfig(),
            ReactionsConfig: ReactionsConfig(()),
            AppsConfig: AppsConfig(
                (
                    AppConfig(
                        "org.example.app",
                        False,
                        "stdio",
                        "disabled",
                        5.0,
                        working_dir=".",
                        command=("python",),
                    ),
                )
            ),
            PlatformsConfig: PlatformsConfig((PlatformConfig("aurora:platform/mcp", False),)),
            StorageConfig: StorageConfig((StorageEntry("world", "data"),)),
            TagsConfig: TagsConfig(()),
            ScopeCatalog: ScopeCatalog(
                (
                    ScopeDeclaration("aurora:world/console", ScopeKind.RESOURCE, "终端输入先进入的世界线"),
                    ScopeDeclaration("aurora:run/*", ScopeKind.RUN, "一次运行的因果台账"),
                )
            ),
        },
    )


def test_builtin_modules_form_a_valid_dependency_graph() -> None:
    specs = tuple(BuiltinSource().discover())
    names = {spec.name for spec in specs}

    assert names == {
        "agents",
        "artifacts",
        "ai",
        "bot",
        "cadence",
        "clock",
        "console",
        "engine",
        "instances",
        "mcp",
        "memory",
        "memory_model",
        "operations",
        "prompt",
        "resources",
        "resource_content",
        "scopes",
        "rhythm",
        "runtime",
        "tools",
        "world",
    }
    resolution = resolve(specs)
    assert resolution.construction[-1].name == "runtime"


def test_builtin_modules_assemble_into_one_assembly(tmp_path: Path) -> None:
    assembly = compose(_settings(tmp_path), BuiltinSource().discover())

    capabilities = (
        assembly.get("ai"),
        assembly.get("scopes"),
        assembly.get("artifacts"),
        assembly.get("prompt"),
        assembly.get("agents"),
        assembly.get("tools"),
        assembly.get("world"),
        assembly.get("memory"),
        assembly.get("memory.checkpoints"),
        assembly.get("console"),
        assembly.get("mcp"),
        assembly.get("engine"),
    )

    assert all(capability is not None for capability in capabilities)
    assert len({id(capability) for capability in capabilities}) == len(capabilities)


def test_runtime_can_be_composed_without_the_console_module() -> None:
    specs = tuple(spec for spec in BuiltinSource().discover() if spec.name != "console")
    resolution = resolve(specs)

    assert resolution.construction[-1].name == "runtime"
    assert all(spec.name != "console" for spec in resolution.construction)
