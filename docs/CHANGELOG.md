# 变更记录

## 未发布

- 项目初始化与可选全局链接统一到无第三方依赖的 `scripts/setup.ts`；`aurora setup` 和各平台启动脚本共用该入口，可直接运行 `node scripts/setup.ts` 或 `pnpm run setup`。
- 工程脚本统一使用 `.ts` 扩展名，文档站任务目标统一命名为 `docsite`。
- 安装脚本固定使用 UTF-8；Windows 脚本使用 UTF-8 BOM，并设置控制台、管道及 Python 子进程编码。
- 精简文档站的历史叙述、重复说明和未实现能力描述，修正文档入口与贡献流程；RFC 和工具路径草案移至 `docs/rfc/`。
