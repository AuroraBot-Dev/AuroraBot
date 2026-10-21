---
order: 3
---

# 配置与存储

## 个人配置与模板

`src/aurora_cli/configs/<name>/` 保存同名的 `.py` 解析器和 `.toml` 模板，配套文件放在该项的 `resources/` 中。每项以 `MODULE: CliPlugin` 贡献 `CONFIG_SPEC` 和模板，与外部 CLI 插件共用加载器。`aurora start` 在加载前补齐入选配置中缺失的文件，已有内容不覆盖；加载器本身不回退模板。全部配置形成只读 `AuroraConfig`，运行包只通过 `Settings.resolve` 取得自己的 DTO。

内置配置默认写入个人 `config/`；插件可声明工作目录内的其他相对文件路径。配置名、源配置目标与附属资源的目标冲突在创建文件前失败。配置总览、编辑、初始化与启动均使用声明中的路径。扩展方式见 [CLI 命令与配置插件](../develop/cli-plugins)。

`aurora config` 默认只读；`--init` 补齐缺失文件，`--edit` 或 `--set` 修改个人配置。`.env` 只补充尚不存在的进程环境变量，不改写 TOML，不覆盖调用者的环境。配置与世界记录仅保存密钥变量名，真实值只在 SDK 调用时读取。

## 配置职责

| 文件                                            | 当前用途                                              |
| ----------------------------------------------- | ----------------------------------------------------- |
| `bot.toml`                                      | 长期 Bot 身份                                         |
| `runtime.toml`、`engine.toml`                   | root 原型、节点 ID、日志级别和树深度、节点、步数上限  |
| `agents.toml`、`prompts.toml`、`prompts/`       | 原型、提示词资源和正文                                |
| `providers.toml`、`endpoints.toml`              | 提供方、SDK 路由、实际模型和请求边界                  |
| `tags.toml`                                     | 工具集合标签                                          |
| `cadence.toml`、`reactions.toml`、`rhythm.toml` | 节律入口、即时匹配规则、规则或 GRU 策略               |
| `memory.toml`、`memory_model.toml`              | 经历候选范围、近期窗口、规则或 TGN 排序与投影保存间隔 |
| `scopes.toml`                                   | 领域分类与范围声明                                    |
| `apps.toml`、`platforms.toml`                   | MCP App、传输、启用状态与终端诊断偏好                 |
| `storage.toml`、`artifacts.toml`                | 世界与日志目录、固定内容存储目录                      |

重复定义、未知 root/child/Prompt/model/Tool、无效资源身份和不兼容的配置在效果前失败。失选默认实现的私有配置不应阻止已选替代实现启动。

## 提供方与模型

Agent 显式选择 `namespace:ai/endpoint/path`；端点冻结提供方版本、远端模型名和请求参数。`namespace:ai/provider/path` 是资源身份，`sdk_provider` 是独立的 LiteLLM 协议前缀。例如资源可叫 `lab:ai/provider/accounts/primary`，协议仍为 `deepseek`。

`litellm` adapter 发送 `sdk_provider/model`，配置的 `base_url` 传为 `api_base`。`openai_compatible` 使用 `openai/model`，只接受 `openai` 路由。兼容的简单提供方名称可省略 `sdk_provider`，嵌套路径必须明确声明；协议前缀不能包含路径、冒号或空白。提供方定义与端点版本覆盖实际 SDK 路由，不能从对象显示文本构造模型名。

## 学习模型

安装训练依赖：`uv sync --extra learning`。`rhythm.policy` 选择 `aurora:rhythm/model/rules` 或 `aurora:rhythm/model/gru`，`memory_model.policy` 选择 `aurora:memory/model/rules` 或 `aurora:memory/model/tgn`。

学习模型通过 `weights` 指定文件，或通过 `weights_ref = "资源名@完整SHA256"` 指定已发布版本，二者只能选一项。正式异步启动把路径字节固定为内容资源，再用相同字节构造模型；固定引用不依赖原导出文件仍存在。训练命令发布权重但不自动启用新模型。

节律参数包括检查时间边界和概率阈值；版本或有效参数改变时保留消费位置并清除不兼容隐状态。TGN 的 `checkpoint_seconds` 控制投影保存间隔，规则策略不产生动态图检查点。节点向量是索引状态，不能代替可读取、可修正的记忆内容。

## MCP 与日志

`apps.toml` 定义不可变 App DTO，package 是命名空间。stdio 要求工作目录和命令，HTTPS Streamable HTTP 要求 URL；环境变量按显式白名单传递，远程认证只使用 `auth_env`。事件模式默认禁用，必须明确启用；运行中不热替换冻结目录。具体范围与未知效果语义见 [MCP 适配](./mcp)。

日志级别来自 `runtime.log_level`，日志目录由 `storage.toml` 的 `logs` 项解析。只允许标准级别和项目内路径；日志写入 `aurora.log` 并轮转，不提供远程 handler 或任意格式执行入口。

## 持久数据

`storage.toml` 是具名路径列表，可通过 `%DATA_ROOT%` 引用其他条目。`world` 目录保存 `world.sqlite3`；`src/aurora_bot/world/migration` 维护递增 schema 和完整升级步骤。数据库只归档世界提交及其索引，不保存 Python 协程或整棵运行树对象。

`artifacts.toml` 指定固定内容目录。原始字节的 SHA256 是内容版本，同名的新版本保留旧正文；别名和运行实例不覆盖定义内容。大请求、回执、权重、训练数据及投影以资源引用进入世界。世界数据库与内容目录应一起备份，缺失或损坏的正文不能作为有效历史静默恢复。
