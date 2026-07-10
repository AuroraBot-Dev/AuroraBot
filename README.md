# AuroraBot vNext

<p align="center">
  <b>中文</b> | <a href="README.en.md">English</a> | <a href="README.ja.md">日本語</a>
</p>

AuroraBot 正在重建为一个以因果事件为中心的自主智能体框架。当前仓库处于架构冻结后的重建阶段：旧实现保存在 `legacy/`，不再是现行架构或功能的依据。

## 当前基准

`docs/rfc/` 是 vNext 唯一的架构基准。代码、配置样例、贡献说明与对外文档必须遵从已接受的 RFC；发生冲突时，以 RFC 为准。

vNext 的最小闭环为：

```text
平台环境事件（AMP JSON）
  → Kernel 接管、形成周期快照并调度图
  → builtin.decide 节点
  → effect.requested
  → 平台执行能力
  → effect.succeeded / effect.failed（下一周期）
```

生成文本不是效果。只有平台回写执行结果，因果闭环才完成。

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

## 重建状态

vNext 尚未提供可运行的 Bot 入口。请勿把当前根目录的旧入口文件或 `legacy/` 中的实现视作 vNext 的启动方式；第一个可运行闭环会在 RFC 0001、0002、0003 的契约测试完成后引入。

## 许可证

本项目使用 [Apache License 2.0](LICENSE) 协议。
