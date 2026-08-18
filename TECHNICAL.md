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

`Tool.execute(call)` 返回 `ToolOutput`。异常被规范化为错误 tool 消息，让模型决定是否恢复。未知或不可见工具同样返回错误
tool 消息。模型边界失败使当前节点失败；child 失败作为 delegate tool 错误恢复 parent。

## 项目组合

`config.example/` 随源码发布，包含 runtime、engine、agents、models、prompts、apps、platforms、extensions、logging、storage
和 profile 配置。用户复制为 `config/` 后生效；`config/` 被 Git 忽略，运行时不会回退读取模板。
每个 TOML 都有同相对路径的 `configuration` 模块；通用合并器按注册顺序产生 `AuroraConfig`，不认识具体文件或字段。
`runtime.tree`、`engine.tree` 和 prompts 目录由当前 AgentTree 组合直接消费，其余配置保持为只读项目事实。

`composition.prompt` 构造 PromptAssembler，`composition.engine` 校验 Tool 并构造 AgentTreeRunner。两者把实例写入类型化组合
上下文，`runtime.py` 从只读 `AuroraAssembly` 取得最终 runner。命令、配置和组件目录都采用“单模块 + 目录入口一条注册记录”
的扩展方式；子进程执行等共享功能位于 `aurora.utils`。

`aurora config list` 列出个人配置中的注册名称与源路径，`aurora config show <name>` 原样显示对应 TOML；两者都不修改文件。

Model 与 Tool 由组合调用者注入。当前仓库故意不提供联网 Provider 或生产进程生命周期，以免 Provider 选择再次侵入核心。

## 验证

测试覆盖：单节点完成、工具往返、未知工具恢复、树形委派、child 独立 model、四角色组装、OpenAI role 映射、非法树与
call id、上下文上界以及配置到 runtime 的完整装配。全部测试使用 fake Model/Tool，离线执行。
