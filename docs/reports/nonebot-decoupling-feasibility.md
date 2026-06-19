# AuroraBot 脱离 NoneBot 框架的可行性与合理性研究报告

> 日期：2026-06-19
>
> 结论先行：**建议让 AuroraBot Core 脱离 NoneBot，但不建议立刻让 QQ/OneBot 接入完全脱离 NoneBot。**  
> 正确方向不是“删掉 NoneBot”，而是把 NoneBot 从主框架降级为一个可选边缘连接器：Core 独立运行，Platform 用 MCP/AMP 连接外围 App，NoneBot 只在需要 QQ/OneBot 生态时作为某个 App/Connector 的实现细节存在。

---

## 1. 研究问题

本报告回答三个问题：

1. AuroraBot 是否技术上可以脱离 NoneBot？
2. 脱离是否符合 AuroraBot 当前架构方向？
3. 如果要脱离，合理边界和迁移路径是什么？

本报告中的“脱离 NoneBot”分三种强度：

| 强度 | 含义 | 本报告态度 |
| --- | --- | --- |
| Core 脱离 | `Brain + Platform + MCP runtime` 不依赖 NoneBot 启动、插件、生命周期 | 应该做 |
| 默认运行脱离 | `uv run aurora` 不启动 NoneBot；QQ 作为可选连接器 | 应该做 |
| 所有接入脱离 | QQ/OneBot 也完全不用 NoneBot，自己实现协议端适配 | 暂不建议一次完成 |

---

## 2. 当前 NoneBot 依赖事实

### 2.1 入口依赖

当前 `bot.py` 是 NoneBot 启动入口：

```python
import nonebot
from nonebot.adapters.onebot.v11 import Adapter as ONEBOT_V11

nonebot.init()
driver = nonebot.get_driver()
driver.register_adapter(ONEBOT_V11)
nonebot.load_from_toml("pyproject.toml")

if __name__ == "__main__":
    nonebot.run()
```

这意味着：

- 进程生命周期由 NoneBot driver 托管。
- OneBot V11 adapter 在主进程注册。
- `src/` 通过 `pyproject.toml` 的 `plugin_dirs = ["src"]` 被当成 NoneBot 插件目录加载。

### 2.2 `src/main.py` 生命周期依赖

当前 `src/main.py` 通过 NoneBot driver 钩子启动和停止 AuroraBot runtime：

```python
from nonebot import get_driver

driver = get_driver()

@driver.on_startup
async def startup_agent() -> None:
    _runtime = await start_runtime(app_host)

@driver.on_shutdown
async def shutdown_agent() -> None:
    await shutdown_runtime(_runtime)
```

这里的 NoneBot 只提供两件事：

- `on_startup`
- `on_shutdown`

这两件事可以用普通 `asyncio.run()`、`asyncio.TaskGroup`、signal handler 和自定义 `RuntimeSupervisor` 替代。

### 2.3 `src/__init__.py` 插件加载依赖

当前 `src/__init__.py` 检测到 NoneBot driver 后导入 `src.main`：

```python
try:
    import nonebot

    nonebot.get_driver()
except Exception:
    pass
else:
    from . import main
```

这说明 `src/` 被设计成 NoneBot 插件目录。脱离后应改为普通 Python 包，不再把 `src` 当插件加载入口。

### 2.4 QQ App 依赖

`apps/aurora-app-qq/runtime.py` 是 NoneBot 依赖最重的部分：

- `from nonebot import get_bot, get_bots, on_message`
- `from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageEvent`
- 使用 `on_message(...).handle()` 注册消息监听。
- 使用 `get_bot()` / `get_bots()` 找 OneBot Bot 对象。
- 使用 `bot.send_group_msg()` / `bot.send_private_msg()` 发消息。
- 使用 OneBot V11 `Message` 解析 CQ 码和消息段。

这部分不是简单替换启动钩子就能解决。它承担的是“QQ/OneBot 协议适配器”职责。

### 2.5 热重载依赖

`src/brain/localhost/reloader.py` 里有少量 NoneBot 插件加载器判断：

- 跳过 `src.main`
- 跳过 `src.config`
- 识别 `nonebot.plugin` loader
- 停止进程时注释中提到 NoneBot driver 捕获 SIGINT

这些属于开发体验和运行时管理细节，不是核心架构依赖。

### 2.6 依赖声明

`pyproject.toml` 当前把 NoneBot 作为主依赖：

```toml
dependencies = [
    "nonebot2[fastapi]>=2.5.0,<3.0.0",
    "nonebot-adapter-onebot>=2.4.6",
    "nonebot-plugin-localstore>=0.7.4",
    ...
]

[tool.nonebot]
plugin_dirs = ["src"]
builtin_plugins = ["echo"]
```

脱离后应把这些移动到可选依赖组，例如：

```toml
[project.optional-dependencies]
nonebot = [
    "nonebot2[fastapi]>=2.5.0,<3.0.0",
    "nonebot-adapter-onebot>=2.4.6",
    "nonebot-plugin-localstore>=0.7.4",
]
```

---

## 3. NoneBot 在 AuroraBot 中实际提供了什么

结合当前代码，NoneBot 实际提供四类能力。

| 能力 | 当前使用位置 | 可替代性 |
| --- | --- | --- |
| 进程入口与生命周期 | `bot.py`, `src/main.py` | 高，可用 `asyncio` 自建 |
| 插件加载 | `pyproject.toml`, `src/__init__.py` | 高，AuroraBot 已有自己的 App/MCP 方向 |
| OneBot/QQ 事件接收 | `aurora-app-qq/runtime.py` | 中，需要保守迁移 |
| OneBot/QQ API 调用 | `aurora-app-qq/runtime.py` | 中，可由 NoneBot connector 或直连 OneBot 实现 |

NoneBot 没有提供 AuroraBot 最核心的东西：

- Brain 认知模型
- MCP Platform
- AMP 事件协议
- 文件驱动认知痕迹
- LLM gateway
- Memory 系统
- App 的目标位置无关模型

因此，NoneBot 是边缘接入框架，不应继续是 AuroraBot 主框架。

---

## 4. 官方 NoneBot 能力边界

NoneBot 官方文档对自身定位很清楚：它是现代、跨平台、可扩展的 Python 聊天机器人框架，特点包括异步优先、插件系统和依赖注入系统。官方还明确 Adapter 是机器人与平台交互的核心桥梁，负责在驱动器和插件之间转换/传递消息；Adapter 主要做两件事：接收事件、调用平台接口。Driver 是运行基石，负责数据收发。

这说明 NoneBot 的优势正好在“聊天机器人接入层”：

- 多平台适配器生态。
- 事件模型。
- Bot 对象和平台 API 调用。
- 插件生命周期。
- 依赖注入。

但 AuroraBot 的目标正在从“聊天机器人框架”转向“持续存在的智能体框架”。在这个目标下，NoneBot 的插件系统和事件响应器模型会逐渐变成外层连接器，而不是主运行时。

官方文档还显示，NoneBot 插件加载有自己的路径和导入规则，插件目录应相对入口文件可导入，并且插件只能加载一次。这与 AuroraBot 正在形成的“主仓库不规定 MCP Server 位置，通过统一协议和外围信息通信”的方向天然不一致。

---

## 5. 合理性分析

### 5.1 为什么 Core 应该脱离

#### 5.1.1 架构语义不匹配

NoneBot 的基本范式是：

```text
平台事件 -> Adapter -> NoneBot Event -> Matcher/Plugin -> 响应
```

AuroraBot 的目标范式是：

```text
任何外部变化 -> AMP Event -> Brain 统一事件认知 -> ActionIntent -> MCP Tool
```

前者是“聊天机器人事件响应器”，后者是“生命体认知循环”。继续把 AuroraBot 主体挂在 NoneBot 插件体系下，会让主框架语义被聊天机器人模型污染。

#### 5.1.2 Platform 已经走向 MCP 位置无关

你前面已经明确了关键点：主仓库不应规定 MCP Server/App 的位置，而应通过统一协议和外围信息通信。

NoneBot 插件系统则天然要求插件模块路径、加载时机、入口文件可导入性。这适合 Bot 插件生态，不适合 AuroraBot 的 MCP App Server 生态。

#### 5.1.3 降低全局状态耦合

NoneBot 使用全局 driver、adapter、bot registry、插件加载器。当前 AuroraBot 已经出现这些耦合：

- `get_driver()`
- `get_bot()`
- `get_bots()`
- `on_message()`
- `src` 被作为插件目录加载

Core 脱离后，AuroraBot 可以用显式 `RuntimeContext` / `RuntimeSupervisor` 管理生命周期，减少全局单例干扰。

#### 5.1.4 更适合 MCP App 隔离

MCP App 可以是：

- 本地 stdio server
- 远程 Streamable HTTP server
- 独立仓库进程
- 用户本机任意路径

NoneBot 插件体系无法天然表达这种位置无关的外围服务模型。

### 5.2 为什么不应立刻完全摆脱 NoneBot

#### 5.2.1 QQ/OneBot 接入成本真实存在

当前 QQ App 用了 NoneBot 的三类能力：

- 消息监听注册：`on_message`
- OneBot 事件类型：`MessageEvent`, `GroupMessageEvent`, `Message`
- Bot API：`send_group_msg`, `send_private_msg`, `get_msg`, `get_stranger_info`

如果完全删除 NoneBot，需要重建：

- OneBot V11 WebSocket/HTTP 连接管理。
- CQ 码和消息段解析。
- Bot session 管理。
- API request/response 封装。
- 断线重连、鉴权、心跳。
- 测试 fixture。

这些不是 AuroraBot 的核心创新点。现在投入过多，会分散 Brain 与 MCP Platform 重构资源。

#### 5.2.2 NoneBot 生态仍有现实价值

NoneBot 在适配器和协议端生态上成熟。对于 QQ / OneBot 这种外围接入，继续利用成熟生态是合理的。

脱离 Core 不等于抵制 NoneBot。更好的边界是：

```text
AuroraBot Core: 不依赖 NoneBot
QQ Connector: 可以依赖 NoneBot
```

#### 5.2.3 过早直连会制造新平台层

如果现在自己写 OneBot connector，很容易在 `src/platform/` 外又长出一套“半成品机器人框架”。这会和 MCP Platform 重构互相冲突。

---

## 6. 可行性评估

### 6.1 Core 脱离可行性：高

需要替换的内容：

| 当前 NoneBot 依赖 | 替代方案 |
| --- | --- |
| `bot.py` | `aurora_main.py` / `src/aurora/runtime_supervisor.py` |
| `driver.on_startup` | `asyncio.run(main())` 中显式启动 |
| `driver.on_shutdown` | signal handler + `try/finally` |
| `src` 作为 plugin dir | 普通 Python package |
| `nonebot.load_from_toml` | 自有配置加载 |

实现复杂度：低到中。

主要风险：

- 需要整理启动/关闭顺序。
- 测试里依赖 `ApplicationHost` 的部分会与 MCP 重构交织。
- 文档和启动命令需要更新。

### 6.2 QQ 接入脱离可行性：中

有两条路线：

#### 路线 A：NoneBot Connector

把 NoneBot 留在一个独立 App/Connector 中：

```text
aurora-core process
  ↕ MCP / AMP
nonebot-qq-connector process
  ↕ OneBot V11
NapCat / 协议端
```

优点：

- Core 立即脱离 NoneBot。
- QQ 继续复用 NoneBot 生态。
- 连接器可以独立重启。
- 与 MCP 位置无关原则一致。

缺点：

- 需要定义 connector 到 Core 的 AMP notification / MCP tools。
- 初期多一个进程。

这是推荐路线。

#### 路线 B：直连 OneBot Connector

自己实现 OneBot V11 WebSocket/HTTP 客户端或服务端：

```text
aurora-core
  ↕ MCP / AMP
aurora-onebot-connector
  ↕ WebSocket/HTTP
NapCat
```

优点：

- 完全移除 NoneBot。
- 控制力最高。
- 依赖更少。

缺点：

- 需要补齐大量协议边缘细节。
- 容易引入新的维护负担。
- 对当前阶段收益不成比例。

这条路线可作为长期优化，不应作为第一阶段。

### 6.3 完全删除 NoneBot 可行性：中，但时机不成熟

前提条件：

- 所有 App 都 MCP 化。
- QQ connector 已独立为 MCP Server。
- Core 启动入口已独立。
- 测试不再依赖 NoneBot 插件加载。
- 文档不再宣称“基于 NoneBot2”。

在这些条件满足前，强删 NoneBot 会造成 QQ 接入断裂和测试大面积重写。

---

## 7. 推荐目标架构

### 7.1 进程关系

```text
┌──────────────────────────────────────────────────────┐
│ AuroraBot Core                                       │
│                                                      │
│  RuntimeSupervisor                                   │
│    ├── Brain Runtime                                 │
│    ├── MCP Platform                                  │
│    ├── Local Console                                 │
│    └── Signal / shutdown 管理                         │
│                                                      │
│  不 import nonebot                                    │
└──────────────────────────────────────────────────────┘
          ▲                           ▲
          │ MCP + AMP                 │ MCP + AMP
          ▼                           ▼
┌──────────────────────┐     ┌────────────────────────┐
│ nonebot-qq-connector │     │ weather/diary/clock... │
│                      │     │ MCP App Servers         │
│ - 依赖 NoneBot       │     │ - 不依赖 NoneBot         │
│ - 接 OneBot / NapCat │     │                         │
└──────────────────────┘     └────────────────────────┘
```

### 7.2 模块边界

建议最终形成：

```text
src/
  aurora/
    main.py                  # 独立入口
    supervisor.py            # runtime lifecycle
    signals.py               # SIGINT/SIGTERM
  platform/
    mcp_kit/
  brain/
  connectors/
    nonebot_qq/              # 可选，或移出主仓库
```

更彻底的做法是把 `nonebot_qq` 移出主仓库，作为独立 MCP App：

```text
aurora-app-qq-nonebot/
  pyproject.toml
  mcp_server.py
  nonebot_entry.py
  service.py
```

### 7.3 运行命令

Core：

```powershell
uv run aurora
```

或：

```powershell
uv run python -m src.aurora.main
```

QQ connector：

```powershell
uv run --project aurora-app-qq-nonebot python -m aurora_qq_nonebot
```

主仓库通过 `apps/config.yml` 连接：

```yaml
apps:
  qq:
    enabled: true
    package: im.polaris.qq
    mcp:
      transport: stdio
      command:
        - uv
        - run
        - --project
        - D:/aurora-app-qq-nonebot
        - python
        - -m
        - aurora_qq_nonebot.mcp_server
```

---

## 8. 分阶段迁移方案

### Phase 0：明确边界，不改代码

目标：

- 文档更新：AuroraBot 不再表述为“基于 NoneBot2”，而是“可通过 NoneBot connector 接入 OneBot/QQ”。
- 把 NoneBot 标记为 Connector 依赖，而不是 Core 依赖。

验收：

- README、文档站、架构图都不再把 NoneBot 放在主干。

### Phase 1：新增独立 Core 入口

新增：

```text
src/aurora/main.py
src/aurora/supervisor.py
src/aurora/signals.py
```

职责：

- 加载 Config。
- 启动 Platform MCP runtime。
- 启动 Brain runtime。
- 启动 localhost console。
- 捕获 SIGINT/SIGTERM。
- `try/finally` 中执行 shutdown。

保留：

- `bot.py` 作为旧 NoneBot 入口。
- `src/main.py` 作为兼容入口。

验收：

- 不启动 QQ 的情况下，`uv run python -m src.aurora.main` 可以跑起本地控制台和 Brain。
- `rg "nonebot" src/brain src/platform` 结果显著减少，最好为 0。

### Phase 2：把 NoneBot 入口降级为 Connector

新增：

```text
connectors/nonebot_qq/
```

或先放在：

```text
apps/aurora-app-qq/
```

但文档中明确它是 connector，不是主框架。

目标：

- QQ 接收消息后发送 AMP `message.received`。
- QQ 发送动作暴露为 MCP Tools。
- Core 不通过 `get_bot()` / `on_message()` 访问 QQ。

验收：

- Core 不 import NoneBot。
- QQ connector 可以独立启动/停止。
- 群消息仍进入 Brain 统一事件入口。

### Phase 3：移动依赖到 optional group

修改 `pyproject.toml`：

```toml
dependencies = [
    "litellm>=...",
    "mcp[cli]>=...",
    ...
]

[project.optional-dependencies]
nonebot = [
    "nonebot2[fastapi]>=2.5.0,<3.0.0",
    "nonebot-adapter-onebot>=2.4.6",
    "nonebot-plugin-localstore>=0.7.4",
]
```

验收：

- `uv sync --group dev` 不默认安装 NoneBot，或至少 Core 测试不需要 NoneBot。
- 需要 QQ 时使用额外安装方式。

### Phase 4：重写热重载和停止逻辑

替换：

- `src.brain.localhost.reloader` 中的 NoneBot 插件 loader 判断。
- `_request_process_exit()` 中对 NoneBot driver 捕获 SIGINT 的注释和假设。

验收：

- standalone runtime 下 reload/stop 行为正常。

### Phase 5：评估是否直连 OneBot

只有在以下条件满足时才考虑：

- NoneBot connector 成为维护负担。
- 需要的 OneBot 功能很小且稳定。
- 有足够测试覆盖 NapCat WebSocket/HTTP。
- 需要降低依赖体积或部署复杂度。

否则继续保留 NoneBot connector。

---

## 9. 风险分析

### 9.1 主要风险

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| QQ 接入断裂 | 高 | 先保留 NoneBot connector，不直删 |
| Core 启停顺序重写出错 | 中 | 新旧入口并行，逐步切默认 |
| 测试重写量大 | 中 | 先让 standalone runtime 有独立测试 |
| 文档和用户认知混乱 | 中 | 明确 NoneBot 是 connector，不是 Core |
| 自写 OneBot 适配器变成新维护坑 | 高 | 推迟直连 OneBot |

### 9.2 不脱离的风险

如果 Core 长期不脱离 NoneBot，会有这些问题：

- AuroraBot 的定位继续被“聊天机器人框架”牵引。
- MCP App 位置无关原则与 NoneBot plugin path 规则冲突。
- 主进程生命周期受 NoneBot driver 限制。
- 非 IM 场景、非 QQ 场景看起来像二等公民。
- Brain 重设计容易被事件响应器范式污染。

---

## 10. 合理性结论

### 10.1 是否可行

可行。

Core 脱离 NoneBot 的改造量不大，因为当前核心依赖集中在入口和生命周期钩子。真正复杂的是 QQ/OneBot 接入，而这部分可以独立为 connector，不必阻塞 Core 脱离。

### 10.2 是否合理

合理，而且与 MCP Platform 重构方向一致。

AuroraBot 的主线正在变成：

```text
Core Runtime + MCP Platform + Brain
```

NoneBot 的主线是：

```text
Driver + Adapter + Plugin + Matcher
```

这两个模型可以合作，但不应重叠。NoneBot 应作为 QQ/OneBot 连接器的内部实现，而不是 AuroraBot 的身份基座。

### 10.3 推荐决策

推荐采用：

```text
Core 立即规划脱离；
QQ/OneBot 暂时保留 NoneBot connector；
长期再评估直连 OneBot。
```

不推荐：

- 现在就删除所有 NoneBot 依赖。
- 在 Core 中继续扩展 NoneBot plugin 模型。
- 为了“纯净”而过早自写 OneBot adapter。

---

## 11. 下一步行动清单

1. 新增 `src/aurora/main.py` 和 `RuntimeSupervisor` 设计文档。
2. 将 `src/main.py` 的 NoneBot startup/shutdown 逻辑抽成可复用函数。
3. 建立 standalone 启动测试：不依赖 NoneBot，只启动 Brain + Platform + localhost。
4. 设计 `aurora-app-qq-nonebot` connector 的 MCP/AMP 接口。
5. 把 `nonebot2` 依赖从主依赖移动到 optional dependency 的方案列入迁移计划。
6. 更新 README 和文档站，把“基于 NoneBot2”改为“可通过 NoneBot connector 接入 QQ/OneBot”。

---

## 12. 参考资料

- NoneBot 概览：<https://nonebot.dev/docs/>
- NoneBot Driver：<https://nonebot.dev/docs/advanced/driver>
- NoneBot Adapter：<https://nonebot.dev/docs/advanced/adapter>
- NoneBot 插件加载：<https://nonebot.dev/docs/tutorial/create-plugin>
- AuroraBot MCP 迁移研究报告：`docs/reports/app-platform-mcp-migration.md`
- AuroraBot 平台层 MCP 重构指南：`docs/reports/platform-native-mcp-refactor-guide.md`

