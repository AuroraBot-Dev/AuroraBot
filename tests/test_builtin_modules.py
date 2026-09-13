"""内建自描述模块经微内核装配的结构与接线测试。"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from src.agents.config import AgentConfig, AgentsConfig
from src.ai.config import ProviderConfig, ProvidersConfig
from src.cadence.config import CadenceConfig
from src.contracts import (
    AgentCatalog,
    AgentTreeRunner,
    EndpointConfig,
    EndpointsConfig,
    McpRuntime,
    MemoryReader,
    Model,
    PromptAssembler,
    RuntimeConfig,
    TerminalConsole,
    ToolRegistry,
    WorldJournal,
)
from src.engine.config import EngineConfig
from src.kernel import BuiltinSource, compose, resolve
from src.mcp.config import AppConfig, AppsConfig, PlatformConfig, PlatformsConfig
from src.memory.config import MemoryConfig
from src.prompt.config import PromptConfig, PromptsConfig
from src.world.config import StorageConfig, StorageEntry

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
            ProvidersConfig: ProvidersConfig((ProviderConfig("provider", "litellm", "API_KEY"),)),
            EndpointsConfig: EndpointsConfig((EndpointConfig("chat", "provider", "gpt"),)),
            PromptsConfig: PromptsConfig(
                (PromptConfig("system.core", "system.txt"), PromptConfig("builtin.chat", "chat.txt"))
            ),
            AgentsConfig: AgentsConfig((AgentConfig("builtin.chat", "会话", "builtin.chat", "chat", (), frozenset()),)),
            EngineConfig: EngineConfig(2, 8, 16),
            RuntimeConfig: RuntimeConfig("default", "root", "builtin.chat", "NONE"),
            MemoryConfig: MemoryConfig(60, 10, (), ()),
            CadenceConfig: CadenceConfig(False, "builtin.chat", 5, 3600, 0.25),
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
            PlatformsConfig: PlatformsConfig((PlatformConfig("builtin.mcp", False),)),
            StorageConfig: StorageConfig((StorageEntry("world", "data"),)),
        },
    )


def test_builtin_modules_form_a_valid_dependency_graph() -> None:
    specs = tuple(BuiltinSource().discover())
    names = {spec.name for spec in specs}

    assert names == {
        "agents",
        "ai",
        "cadence",
        "console",
        "engine",
        "mcp",
        "memory",
        "prompt",
        "runtime",
        "tools",
        "world",
    }
    resolution = resolve(specs)
    assert resolution.construction[-1].name == "runtime"


def test_builtin_modules_assemble_into_one_assembly(tmp_path: Path) -> None:
    assembly = compose(_settings(tmp_path), BuiltinSource().discover())

    assert isinstance(assembly.get(Model), object)
    assert isinstance(assembly.get(PromptAssembler), object)
    assert isinstance(assembly.get(AgentCatalog), object)
    assert isinstance(assembly.get(ToolRegistry), object)
    assert isinstance(assembly.get(WorldJournal), object)
    assert isinstance(assembly.get(MemoryReader), object)
    assert isinstance(assembly.get(TerminalConsole), object)
    assert isinstance(assembly.get(McpRuntime), object)
    assert isinstance(assembly.get(AgentTreeRunner), object)
