# 0206：运行时组合与配置快照收敛

状态：已接受
日期：2026-08-07
来源：清理平台生命周期和配置热重载技术债，修复组合级契约失真

## 问题

平台句柄定义在实现包并以 `object`、`Callable[..., Any]` 连接组合根，导致输入 Port、配置对象、一次性启动
效果和长驻后台任务可被静态类型混用。配置侧同时存在 loader、未接入的 validator、Prompt 二次加载和没有消费者
的 reload/subscriber，形成多个事实源；运行时重载只替换注册中心快照，已组合的 Engine、模型网关和平台继续使用旧值。

MCP 还存在三个边界缺口：stdio App 继承整个父进程环境、通知在持久化 Inbox 前无界排队、外部事件重复投递时
没有稳定 AMP 身份。连接失效后若进程继续运行，Engine 中的启动时能力目录也会过期。

## 决定

### 平台生命周期契约

- `PlatformHandle`、`PlatformServer` 和平台组合 Port 只定义在 `src.contracts`；平台实现包不再定义跨层 DTO。
- 平台工厂接收不可变 `AuroraConfig` 和强类型运行时 Port，不得通过 `object`、`getattr` 或 `type: ignore` 猜测依赖。
- `PlatformHandle.background` 表示必须运行到 stop 的后台协程。一次性启动效果必须由该协程继续等待 stop，或在平台
  创建阶段完成；后台协程提前返回等同平台失效。
- cleanup 统一为异步回调。组合根负责给 server、后台任务、Debug 和 Engine loop 提供有界清理，不让已记录的任务
  异常中断其余资源释放。
- Tool binding 目录总是在平台创建后绑定；空元组是合法且完整的目录，不表示“尚未初始化”。

### 单一启动配置快照

- `load_configuration()` 是结构配置的唯一解析与校验入口；删除重复 validator。
- `prompts.toml` 由 config loader 解析为 contracts 中的路径 DTO，并进入 `AuroraConfig.sources`。`src.prompt` 只读取
  已校验路径对应的 Markdown 内容，不再二次解析结构配置。
- 核心配置只支持启动时不可变快照。删除没有原子重组语义的 `/reload`、subscriber 和文件 watcher；配置变更通过
  统一重启生效，不提供“注册中心已更新但消费者未更新”的部分重载。
- Profile 只能是 `config/profiles/` 下的简单名称；数值配置必须是有限值，未知键继续在启动前失败。

### MCP 边界

- stdio App 默认只继承启动所需的非密钥基础环境。额外环境变量必须在 `apps.toml` 以变量名显式声明；配置快照
  只保存名称，运行时按名称读取值。
- MCP 和 Dashboard 推送队列必须有界。MCP 上游使用背压；Dashboard 慢消费者只保留最新事件，持久消息由同步接口
  恢复。
- `aurora/event` 通知按 App、事件类型、会话和规范化事件内容派生稳定 UUID；同一外部事件重放得到同一 AMP ID。
- 任一已建立 MCP 会话意外结束时，平台后台协程向组合根报告失败并触发统一关闭，不允许继续广告过期能力。
- Tool 调用在确认会话不存在且尚未派发时返回 `FAILED`；只有派发边界之后无法确认结果才返回 `UNKNOWN`。

## 结果

组合根和平台之间恢复静态类型保护，空平台与浏览器启动组合具有明确语义；配置只有一个可审计快照，删除无效热
重载代码；MCP App 不再默认获得模型密钥，事件入口和连接失效具有有界、可恢复的行为。
