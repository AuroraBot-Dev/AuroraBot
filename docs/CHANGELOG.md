# 变更记录

## 未发布

- 内置命令统一收纳为 `aurora_cli/commands/<name>/` 包，由包入口导出 `MODULE`。
- 内置命令与配置统一导出 CLI 插件声明，与 `extensions/cli/` 和 `aurora_cli_plugin` 安装入口共用发现、依赖及冲突校验；配置查看、编辑、模板初始化和启动使用同一次加载的目录，移除全局命令目录和配置缓存。
- Python 发行包名设为 `aurorabot-ai`，补充项目链接，并同步 CLI 的安装版本查询。
- 配置模板与解析器按配置项收归 `aurora_cli/configs/`，启动时只补齐缺失文件；setup 按项询问是否创建，默认跳过。`.env` 新建默认同意，重置已有文件默认拒绝。
- 初始化脚本统一使用工程任务的 Clack 交互样式，支持方向键选择与 Ctrl+C 取消。
- 项目初始化与可选全局链接统一到无第三方依赖的 `scripts/setup.ts`；`aurora setup` 和各平台启动脚本共用该入口，可直接运行 `node scripts/setup.ts` 或 `pnpm run setup`。
- 工程脚本统一使用 `.ts` 扩展名，文档站任务目标统一命名为 `docsite`。
- 安装脚本固定使用 UTF-8；Windows 脚本使用 UTF-8 BOM，并设置控制台、管道及 Python 子进程编码。
- 精简文档站的历史叙述、重复说明和未实现能力描述，修正文档入口与贡献流程；RFC 和工具路径草案移至 `docs/rfc/`。
