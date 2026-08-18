# AuroraBot 技术说明

## 核心值对象

`ChatMessage` 支持四个领域 role：

- `system`：稳定身份、世界说明和节点职责；
- `message`：人、环境或 parent 给出的事实；
- `assistant`：模型文本和 Tool calls；
- `tool`：一个 call id 的规范结果或错误。

`AgentNode` 显式保存 `profile_id`、`model`、可见 Tool 名称和追加式 transcript。`AgentTree` 校验唯一 root、父子可达、
无环、节点 id 唯一、Tool call 配对和终态一致性。深度从 parent 链推导。

## PromptAssembler

输入是 `AgentTree + node_id`。组装顺序固定为：

1. 全局 system 片段；
2. 当前 profile prompt；
3. 当前节点原有的 message、assistant、tool transcript。

组装器对文本与 Tool call 参数做显式字符上界检查，不裁剪、不摘要、不访问外部状态。

## Model 与 Tool

`ModelRequest` 明确携带节点 model、四角色消息和本节点可见的 Tool 定义。OpenAI-compatible adapter 只在协议边界把
`message` 映射为 `user`。

节点 model 是 `models.toml` 的端点 id。`LiteLLMModelGateway` 只按该 id 查找固定 provider/model；它不读取 profile，也不
替 Runner 选择模型。`litellm` 与 `openai_compatible` provider 最终都经过 LiteLLM Chat Completions 调用。

`Tool.execute(call)` 返回 `ToolOutput`。异常被规范化为错误 tool 消息，让模型决定是否恢复。未知或不可见工具同样返回错误
tool 消息。模型边界失败使当前节点失败；child 失败作为 delegate tool 错误恢复 parent。

## 项目组合

`config.example/` 随源码发布，包含 runtime、engine、agents、models、prompts、apps、platforms、extensions、logging、storage
和 profile 配置。用户复制为 `config/` 后生效；`config/` 被 Git 忽略，运行时不会回退读取模板。
每个 TOML 都有同相对路径的 `configuration` 模块；通用合并器按注册顺序产生 `AuroraConfig`，不认识具体文件或字段。
`runtime.tree`、`runtime.console`、`engine.tree`、models 和 prompts 目录由当前组合直接消费，其余配置保持为项目事实。

`composition.ai/prompt/console/engine` 分别构造模型网关、PromptAssembler、TerminalConsole 和 AgentTreeRunner。实例写入
类型化组合上下文，`runtime.py` 从只读 `AuroraAssembly` 取得最终组件。命令、配置和组件目录都采用“单模块 + 目录入口一条
注册记录”的扩展方式；下层无项目语义工具位于 `src.utils`，项目命令工具位于 `aurora.utils`。

`aurora config list` 列出个人配置中的注册名称与源路径，`aurora config show <name>` 原样显示对应 TOML；两者都不修改文件。

`aurora start` 首先读取项目根目录的 `.env`，但不覆盖已有进程环境变量，再加载 TOML 并组合运行时。它默认启动本地
Console；普通文本发起新 AgentTree，斜杠文本进入 ops。`/exit`、EOF、SIGINT、SIGTERM 和
`--headless` 使用同一组合与停止路径。调用者也可以显式注入 Model 和 Tool，供嵌入运行与离线测试使用。

## 验证

测试覆盖：单节点完成、工具往返、未知工具恢复、树形委派、child 独立 model、四角色组装、LiteLLM 参数映射、非法树与
call id、Console 普通文本/操作/停止，以及配置到 start 的完整装配。效果测试使用 fake Model/Tool/Caller，离线执行。
