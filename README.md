# AuroraBot

<p align="center">
  <b>中文</b> | <a href="README.en.md">English</a> | <a href="README.ja.md">日本語</a>
</p>

AuroraBot 是一个以因果事件、图式认知和主动节律为核心的自主智能体框架。它把环境输入、模型调用、
能力执行和执行回执都保留为可审计记录，使一次认知过程能够异步暂停、可靠恢复并明确终止。

## 认知闭环

```text
外部 AMP 事件 / system.tick
  → Kernel 创建有界 Episode 和只读认知快照
  → builtin.fast_gate 直接处理、调用能力、沉默或升级
  → builtin.native_agent 处理复杂任务与有界工具回路
  → effect.requested
  → Platform 执行能力
  → effect receipt 在下一周期恢复或结束 Episode
```

模型产生的文本不会直接成为外部输出。只有声明过的 Platform 能力可以产生效果；模型调用、工具调用、
回执、预算变化和终止原因均进入同一条因果链。每个外部输入或自主 tick 使用独立 Episode，当前闭环不保存
跨 Episode 对话历史，也不启用长期记忆或沙箱节点。

没有外界输入时，持久化 scheduler 会按预算产生 `system.tick`。连续静默会从 30 秒逐步退避到 30 分钟；
外部输入立即唤醒运行时，交互 Episode 优先于自主 Episode。

## 主要能力

- AMP JSON 事件、Kernel 记录和原子工作区操作
- 有界 Episode、动态 continuation edge、预算与取消策略
- Chat Completions tools 与 Responses agent 双通道模型网关
- 不可变能力目录、JSON Schema 参数校验和 MCP 应用接入
- 单进程 `AuroraRuntime`，统一推进 scheduler、Kernel、模型 dispatcher 和 Platform 回执
- 结构化上下文日志，以及独立于日志的因果审计记录

## 快速开始

需要 Python 3.12 和 [uv](https://docs.astral.sh/uv/)。

```powershell
uv sync --group dev
Copy-Item .env.example .env
# 在 .env 中填写所选 Provider 对应的密钥
uv run python bot.py
```

默认同时启动认知循环和 `http://127.0.0.1:8000` Dashboard 后端。聊天前端保持在独立 AuroraChat 仓库：

```powershell
Set-Location ..\AuroraChat
pnpm install
pnpm run dev
```

浏览器打开 `http://localhost:5173`，注册后即可和普通用户或内建 AuroraBot 联系人聊天。

常用入口：

```powershell
# 仅常驻认知循环，不启动 Dashboard
uv run python bot.py --headless --profile prod

# 同时启动调试 API 与本地控制台
uv run aurora

# 分别启动调试 API 或控制台
uv run aurora serve
uv run aurora console

# 执行项目质量检查
uv run aurora check
```

控制台可用 `/say 你好` 投递消息，使用 `/cycle` 强制推进一个调试周期，并通过 `/record <record_id>`、
`/status` 查看审计和调度状态。

## 目录

```text
config/         TOML 主配置、领域配置与 profile 覆盖
docs/rfc/       规范性架构与公共契约
src/kernel/     事件、工作区、图、周期、因果与 Episode
src/ai/         模型角色、路由、原生 tools/Responses 和用量记录
src/localhost/  本地业务、聊天室、scheduler 与控制台用例
src/dashboard/  Dashboard HTTP/WebSocket 与调试路由适配层
src/platform/   平台生态适配、能力目录与 AMP 归一化
src/apps/       内建原生 AMP-MCP 应用
src/nodes/      内建、自包含的认知节点
src/sandbox/    独立沙箱组件；当前认知图不启用
src/utils/      无上层依赖的通用工具
tests/          契约、集成与回归测试
```

Kernel 工作区固定为 `data/kernel/{inbox,process,archive}`。运行时数据使用 JSON，结构性配置使用 TOML，
密钥只通过环境变量提供。

## 文档

- [RFC 索引](docs/rfc/README.md)
- [RFC 0001：架构基准](docs/rfc/0001-architecture.md)
- [RFC 0008：首轮认知图、Episode 与主动节律](docs/rfc/0008-first-cognitive-loop.md)
- [RFC 0010：Dashboard 聊天适配](docs/rfc/0010-dashboard-chat.md)
- [RFC 0011：当前项目基线](docs/rfc/0011-current-project-baseline.md)
- [贡献指南](docs/CONTRIBUTING.md)
- [日志规范](LOGGING.md)
- [社区行为准则](CODE_OF_CONDUCT.md)

## 许可证

本项目使用 [Apache License 2.0](LICENSE) 协议。
