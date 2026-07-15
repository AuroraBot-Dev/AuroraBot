# AuroraBot vNext

<p align="center">
  <b>中文</b> | <a href="README.en.md">English</a> | <a href="README.ja.md">日本語</a>
</p>

AuroraBot 正在重建为一个以因果事件为中心的自主智能体框架。当前仓库处于架构冻结后的重建阶段：旧实现保存在 `legacy/`，不再是现行架构或功能的依据。

## 当前基准

`docs/rfc/` 是 vNext 唯一的架构基准。代码、配置样例、贡献说明与对外文档必须遵从已接受的 RFC；发生冲突时，以 RFC 为准。

vNext 的首轮认知闭环为：

```text
平台环境事件（AMP JSON）
  → Kernel 接管、形成 Episode 与周期快照
  → builtin.fast_gate 直接处理或升级 builtin.native_agent
  → 原生模型 Tool Call → effect.requested
  → 平台执行能力
  → effect.succeeded / effect.failed（下一周期）
```

生成文本不是效果。只有平台回写执行结果，因果闭环才完成；没有外界输入时，Kernel scheduler 也会以
受预算和退避约束的 `system.tick` 推进自主认知。

## 目录

```text
config/       TOML 主配置与 profile 覆盖
docs/rfc/     vNext 规范性设计文档
legacy/       冻结的旧代码和旧测试，仅供迁移参考
src/          vNext 实现（从最小闭环重新演化）
tests/        vNext 契约与集成测试
extensions/   推荐的第三方节点、平台适配器和应用扩展位置
```

内核工作区固定为 `data/kernel/{inbox,process,archive}`；运行时数据使用 JSON，结构性配置使用 TOML，密钥来自环境变量。

## RFC 导航

- [RFC 0000：RFC 过程](docs/rfc/0000-rfc-process.md)
- [RFC 0001：架构基准](docs/rfc/0001-architecture.md)
- [RFC 0002：配置基准](docs/rfc/0002-configuration.md)
- [RFC 0003：事件与因果契约](docs/rfc/0003-event-contract.md)
- [RFC 0004：扩展契约](docs/rfc/0004-plugin-contract.md)
- [RFC 0005：模型网关](docs/rfc/0005-model-gateway.md)
- [RFC 0008：首轮认知图、Episode 与主动节律](docs/rfc/0008-first-cognitive-loop.md)
- [RFC 0009：常驻 Bot 循环入口](docs/rfc/0009-bot-loop-entry.md)

## 重建状态

vNext 现在可以直接进入常驻无头 Bot 循环：

```powershell
uv run python bot.py

# 可选：选择 config/profiles 下的覆盖配置
uv run python bot.py --profile prod
```

该入口只启动一个 `AuroraRuntime`，持续推进 scheduler、Kernel、模型 dispatcher 与 Platform 回执，按
`Ctrl+C` 后优雅关闭。开发调试仍可使用以下入口：

```powershell
# 同时启动 serve + console（console 前台，serve 后台自动关闭）
uv run aurora

# 仅启动开发调试 HTTP API（默认 http://127.0.0.1:8765）
uv run aurora serve

# 仅启动分层交互式本地控制台
uv run aurora console
```

`serve`、`console` 和组合入口都会启动主动 scheduler。控制台中输入 `/say 你好` 投递消息，`/cycle`
可强制推进一个调试周期，`/record <record_id>` 查询审计记录。HTTP API 另提供 scheduler/episode
只读状态，具体契约见 RFC 0006 与 RFC 0008。

## 许可证

本项目使用 [Apache License 2.0](LICENSE) 协议。
