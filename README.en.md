<p align="center">
  <img src="assets/logo.svg" width="120" alt="AuroraBot Logo" />
</p>

<h1 align="center">AuroraBot</h1>

<p align="center">
  <a href="README.md">中文</a> | <b>English</b> | <a href="README.ja.md">日本語</a>
</p>

<p align="center">
  <em>A next-generation intrinsically-driven, autonomous decision-making agent framework built on NoneBot2</em>
</p>

<p align="center">
  Declarative Cognitive Topology · Three-Tier Unified Memory · Unified LLM Gateway
</p>

<p align="center">
  <a href="https://github.com/AuroraBot-Dev/AuroraBot"><img src="https://img.shields.io/badge/GitHub-Repository-black?logo=github" alt="GitHub" /></a>
  <a href="https://www.aurorabot.org/"><img src="https://img.shields.io/badge/Docs-Documentation-blue?logo=vitepress" alt="Docs" /></a>
  <a href="./LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-green" alt="License" /></a>
</p>

---

## What She Is

AuroraBot is a next-generation **intrinsically-driven, autonomous agent framework**. She consists of two runtime layers plus a cognitive engine:

- **Application Layer (Apps)** — Pluggable sensors and actuators. Each App declares its capabilities via `manifest.yaml` and connects to the outside world through a unified `PlatformAPI`
- **Platform Layer (Platform)** — `ApplicationHost` manages App registration, lifecycle, and event queues. `PlatformAPI` provides bidirectional communication to each App
- **Cognitive Engine (Brain / CortexForge)** — A file-driven cognitive operating system kernel, composed of two subsystems:
  - **kernel**: `Node` / `Agent` / `Router` node network + `FileEventBus` event bus + `Circuit` orchestrator
  - **memory**: L1 working memory / L2 episodic memory / L3 semantic memory, accessed through `UnifiedMemoryManager`

> She doesn't "wait for instructions" — she continuously observes, autonomously decides, and proactively acts.

## Architecture Overview

```mermaid
flowchart LR
    subgraph APPS["Application Layer (Apps)"]
        direction TB
        QQ["QQ Adapter"]
        ALARM["Scheduled Reminders"]
        DIARY["Diary"]
    end

    subgraph PLATFORM["Platform Layer (Platform)"]
        direction TB
        HOST["ApplicationHost"]
        API["PlatformAPI"]
        EVENTS["Event Queue"]
        CMDS["Command Registry"]
    end

    subgraph BRAIN["Cognitive Engine (CortexForge)"]
        subgraph KERNEL["kernel Subsystem"]
            direction LR
            CIRCUIT["Circuit Orchestrator"]
            BUS["FileEventBus"]
            NODES["Agent / Router Nodes"]
        end
        subgraph MEMORY["memory Subsystem"]
            direction LR
            L1["L1 Working Memory"]
            L2["L2 Episodic Memory"]
            L3["L3 Semantic Memory"]
        end
        GATEWAY["LLM / Embedding Gateway (litellm)"]
    end

    APPS <-->|"AppEvent / invoke_command"| PLATFORM
    PLATFORM <-->|"Event Bridge"| BRAIN
```

### Highly Decoupled App Plugin System

Each App is an independent sensor and actuator. Connecting QQ, timers, file systems, or even external APIs — it only takes one App. Apps declare commands through `manifest.yaml`, interact with the host via `PlatformAPI`, and are enabled on demand.

### Declarative Cognitive Topology

Cognition doesn't rely on a single "super agent" — instead, multiple `Agent` / `Router` nodes are declaratively configured through `topology.yaml`. Nodes pass state through the `FileEventBus` file event bus, forming a file-driven cognitive pipeline. In the future, cognitive node plugins will be opened for third-party cognitive capability extensions.

### Three-Tier Unified Memory

AuroraBot's memory grows structurally:

| Tier               | Type                | Storage                         | Purpose                       |
| ------------------ | ------------------- | ------------------------------- | ----------------------------- |
| L1 Working Memory  | FIFO in-memory list | Not persisted                   | Current session context       |
| L2 Episodic Memory | JSON file append    | LLM-compressed after 50 entries | Timeline-based archiving      |
| L3 Semantic Memory | ChromaDB vector     | Unlimited                       | Semantic similarity retrieval |

`UnifiedMemoryManager` encapsulates all three tiers behind a unified interface — nodes never need to understand the underlying data flow. Every interaction writes to all three tiers at once, and retrieval merges results across all layers.

## MCP Adaptation Container (Planned)

We are designing an **MCP (Model Context Protocol) Adaptation Container** that allows any MCP server to connect to AuroraBot as an App.

This means:

- Any tool conforming to the MCP protocol can become an extension of AuroraBot's capabilities
- MCP tools will be automatically mapped into commands callable by the kernel
- The kernel doesn't need to be aware of MCP protocol details — the adaptation container handles it all

> Let the MCP ecosystem become an extension of your capabilities.

## Quick Navigation

For complete architecture design, usage guides, and development documentation, please **[visit the AuroraBot Documentation 📖](https://www.aurorabot.org/)**:

| Document                                                                                 | Description                                                       |
| ---------------------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| [Overview](https://www.aurorabot.org/start/overview.html)                                | A quick introduction to AuroraBot's vision & architecture         |
| [Getting Started](https://www.aurorabot.org/start/getting-started.html)                  | Run the project from scratch                                      |
| [Configuration](https://www.aurorabot.org/start/configuration.html)                      | Environment variables, platform config, app config & persona docs |
| [System Architecture](https://www.aurorabot.org/architecture/system-overview.html)       | Understand the Apps / Platform / Kernel / Brain layers            |
| [Cognitive Architecture](https://www.aurorabot.org/architecture/brain-architecture.html) | File-driven cognitive pipeline and currently enabled topology     |
| [Node System](https://www.aurorabot.org/architecture/node-system.html)                   | Node / Agent / Router data structures and event bus               |
| [Memory System](https://www.aurorabot.org/architecture/memory-system.html)               | L1 / L2 / L3 three-tier unified memory storage and retrieval      |
| [App Development Guide](https://www.aurorabot.org/develop/app-development.html)          | Develop your own App from structure to lifecycle                  |
| [Brain Node Development](https://www.aurorabot.org/develop/brain-node-development.html)  | Write Agent / Router nodes                                        |
| [AUR CLI](https://www.aurorabot.org/develop/aur-cli.html)                                | Application development toolchain roadmap                         |

## Open Source Acknowledgments

AuroraBot is built upon the shoulders of many outstanding open-source projects:

| Project                                           | Description                         | License                                                                             |
| ------------------------------------------------- | ----------------------------------- | :---------------------------------------------------------------------------------- |
| [NoneBot2](https://github.com/nonebot/nonebot2)   | Cross-platform Python bot framework | [MIT License](https://github.com/nonebot/nonebot2/blob/master/LICENSE)              |
| [LiteLLM](https://github.com/BerriAI/litellm)     | Unified LLM API call layer          | [LICENSE](https://github.com/BerriAI/litellm/blob/litellm_internal_staging/LICENSE) |
| [mem0](https://github.com/mem0ai/mem0)            | Agent memory infrastructure         | [Apache License 2.0](https://github.com/mem0ai/mem0/blob/main/LICENSE)              |
| [ChromaDB](https://github.com/chroma-core/chroma) | Open-source vector database         | [Apache License 2.0](https://github.com/chroma-core/chroma/blob/main/LICENSE)       |
| [OneBot](https://github.com/botuniverse/onebot)   | Unified chatbot interface standard  | [MIT License](https://github.com/botuniverse/onebot/blob/main/LICENSE)              |
| [VitePress](https://github.com/vuejs/vitepress)   | Documentation site generator        | [MIT License](https://github.com/vuejs/vitepress/blob/main/LICENSE)                 |

Special thanks to **[MaiBot](https://github.com/MaiM-with-u/MaiBot)** for providing architectural inspiration and design references.

## License

This project is open-sourced under the [Apache License 2.0](./LICENSE).

---

## Star History

<a href="https://www.star-history.com/?repos=AuroraBot-Dev%2FAuroraBot&type=date&logscale=&legend=bottom-right">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=AuroraBot-Dev/AuroraBot&type=date&theme=dark&logscale&legend=bottom-right" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=AuroraBot-Dev/AuroraBot&type=date&logscale&legend=bottom-right" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=AuroraBot-Dev/AuroraBot&type=date&logscale&legend=bottom-right" />
 </picture>
</a>

---

<p align="center">
  <sub>Built with ❤️ by <a href="https://github.com/JuFireX">JuFireX</a> | <a href="https://github.com/AuroraBot-Dev">AuroraBot-Dev</a></sub>
</p>
