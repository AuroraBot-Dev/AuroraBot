# AuroraBot 设计一致性审查报告

> 历史归档：2026-11-09。保留当时的设计、计划与验收语境，不作为当前功能承诺或操作指南；当前入口见 [文档索引](../../INDEX.md)。

日期：2026-11-03

初次审查基线：提交 `8b46dd2`。同日复核对照该基线、已提交的 `dce7ad4` 及当时工作区代码；保留 F1–F16 编号，以下问题定性和优先级以复核结论为准。复核期间出现了并行进行的 MCP 未提交改动，定向测试只代表执行时的工作区状态，不构成对这些改动的完整验收。

参考材料：

- [设计文档 v0.2.3](aurorabot-design-v0.2.3.md)
- [公共 ID 目录 v0.2.3](aurorabot-id-catalog-v0.2.3.md)
- [里程碑与编码计划](plan.md)
- [MCP 通用接入设计草案](mcp_unified_access_design.md)
- [执行包拆包评估](aurora_agent_extraction_assessment.md)
- 当前 `packages/`、`apps/`、`tests/` 实现

初次审查方式：静态阅读、插件登记导出、定向与全量测试、Python 类型检查、生成契约检查。同日复核采用源码与设计对照、定向回归及最小异常场景复现。两次审查均未修改实现，未调用真实模型或外部平台；历史验证与复核结果在第 5 节分别记录。

## 1. 结论

总体判断：**项目基本贯彻了设计思想，没有发现方向性跑偏。**

- `core` 仍然只是微内核，没有混入 bot、模型、MCP 或业务流程机制。
- `bot → agent → control → core` 的代码依赖方向成立；`agent` 没有反向依赖 `bot`、CLI、API 或 world。
- ID、实例、运行、调用、状态值的分层基本清楚；`ctx` 的深拷贝、整项替换、精确地址、订阅不回放等语义与设计一致。
- 生命周期、最终落盘、可选宿主缺席、按需 schema、接收方判断兼容性等原则都有实际代码和测试支撑。
- 文档对“已交付”和“规划中”的区分总体诚实，计划中明确列出了 B5、B3、cadence、Panel、远程认证等未完成项。

复核结论：**报告包含真实缺陷，也混入了已知限制、未来需求和重构偏好，不能将全部条目按原严重度直接整改。**

1. 已确认世界记录通用写入、配置失败后的编辑入口清理，以及少数异常覆盖问题，应优先修复。
2. TUI 实际消费字段的契约、客户端校验描述和文档依赖表需要对齐。
3. MCP 来源与默认对话上下文的长期保留策略值得设计；环境时间和天气已有上限，完整日志也已声明有限规模边界。
4. 默认装配的恢复辅助可以按实际复用需求提取，但显式激活与 runtime 已有互斥，资源所有权和保留策略仍属于装配职责。
5. 浏览器接入、实例切换和更细的数据权限应随对应需求推进，不作为当前已交付能力的回归。

## 2. 设计原则对照

| 设计原则 | 判断 | 主要依据 |
| --- | --- | --- |
| core 只做通用机制 | 良好 | `core` 仅登记、ctx、事件、连接、调用、生命周期、持久化；无业务导入 |
| bot 装配能力，不另造机制 | 基本成立 | 两条激活入口互斥；恢复辅助有复用空间，清理异常传播需修正 |
| 公开对象统一寻址 | 良好 | 初次审查基线导出的 108 个定义均可在 ID 目录中找到；该数量不包含后续动态登记 |
| 接口按需明确 | 部分 | 核心边界清楚；TUI 复刻 `react_work` 内部字段，未进入生成契约 |
| 连接由提供插槽的一方判断 | 良好 | `HookSlot.accept` 可选，schema 不同但接受时仅告警 |
| 缺少接收方允许未连接 | 良好 | `inspect_admissions` 区分 accepted/unconnected/rejected 并告警 |
| 统一 ctx 访问语义 | 良好 | Python/CLI/TS client 共用既有 ctx 操作 ID；API 无任意 operation 转发 |
| 模型适配透明 | 良好 | 模型报文与 SDK 类型限制在 `aurora_adapter.model`；agent 只消费协议 |
| 共享状态与显式变更 | 良好 | 深拷贝、set 整项替换、失败无部分变更、订阅不回放 |
| 身份与实例分离 | 存在局部限制 | MCP 定义持有宿主绑定，限制同一定义对象的复用；不是进程级全局污染 |
| 按连接与依赖逐步关闭 | 总体良好 | 依赖正序启动、反序关闭；最终 flush 后释放存储；配置失败解绑例外见 F11 |
| 单租户、单后端、多界面 | 良好 | API 只监听回环；TUI 偏好留本地；未引入多租户隔离 |
| 不提供任意远端 operation | 良好 | API 仅注册固定 ctx 动作与显式产品端点；测试覆盖 `/operations/invoke` 不存在 |
| 不热插拔工具集合 | 良好 | MCP 工具目录变化要求重建宿主，未在运行中增删工具 |

## 3. 做得好的地方

1. **依赖方向有测试和安装验收兜底。** `control` 只依赖 `core`；`agent` 只依赖 `core`、`control`、`model_adapter`；`bot` 不导入 `aurora_api`/`aurora_cli`；`adapters` 的 MCP 消费者按 extra 隔离。`tests/e2e/test_package_boundaries.py` 还验证了无 bot 环境下的 agent 往返。

2. **ctx 语义落实细致。** `Context` 的 get/set 都做深拷贝，set 整项替换，list 返回已赋值地址并排序，缺失 get 抛 `KeyError`，delete 缺失返回 `False`，同值写入也产生新修订，失败写入无部分变更。订阅只接收后续变化，不补发历史（`packages/aurora_core/src/aurora_core/ctx.py`）。

3. **生命周期与最终落盘顺序正确。** config、prepare、start 按依赖顺序执行；stop、clean 反序执行；`ContextPersistence.close()` 成功 flush 后才解除订阅；启动失败和停止失败都有保留资源、可重试的路径（`packages/aurora_core/src/aurora_core/lifecycle.py`、`persistence.py`）。

4. **执行契约干净。** control 的执行请求只携带 `run_id`、`execution_id`、`parent_execution_id`；业务状态通过 `StateBinding` 读写；ReAct 六阶段、Serial、Branch、While、Parallel 都在 control/agent，core 没有业务流程控制。

5. **公共 ID 与插件发现总体一致。** 初次审查基线导出的 108 个定义全部能在 ID 目录中找到；该导出范围内未发现“代码已登记、文档完全没有”的 ID。插件 `requires` 只校验显式启用的依赖，不隐式加载。

6. **生成契约可重复检查。** `scripts/generate.py` 合并 API、bot、config 的显式描述，生成 TS 类型和绑定；`--check` 本次返回 0，说明生成产物与后端描述一致。

## 4. 发现与复核结论

严重度只用于已确认缺陷；容量限制、规划能力和维护建议单独标明，不据此推导必须重构。下列源码链接指向职责位置，后续代码变化时应重新核对。

### F1. 世界记录通过通用 ctx 白名单开放了写操作

**判断：成立。优先级：高，数据完整性缺陷。**

- 当时的 `scripts/serve_bot.py` 在 --world 模式把 RECORDS、SOURCE_STATUS 放入 --keys（现入口为 [scripts/bot.py](../../../scripts/bot.py)，相关状态已改为只读）；[server.py](../../../packages/aurora_api/src/aurora_api/server.py) 对同一集合开放 get/list/set/delete。
- 世界记录要求通过 WorldRecords 追加、去重和裁剪，结构校验无法保证写入经过该入口。最小复核中，删除 RECORDS 返回 HTTP 200、result=true，记录地址随即消失。
- 当前监听范围是本机回环，不能将此问题扩大为已经存在的远程攻击面。CLIENT_STATUS 只读是同类设计建议，并非该启动脚本已经暴露它的证据。

建议拆分读写键或按动作声明权限，让观察状态只读；服务端拒绝写入，TUI 同步表达可写性，并覆盖 set/delete 拒绝测试。

### F2. TUI 手工解释 react_work，实际消费字段缺少契约

**判断：成立。优先级：中，契约一致性问题。**

[workbench.ts](../../../apps/aurora_tui/src/state/workbench.ts) 硬编码 bot 状态 ID，并解释 model_output、tool_calls、tool_current、tool_results 等布局。这些字段没有进入生成契约，后端变化可能只表现为界面少显示内容。

读取业务状态不等于把后端 callable、服务对象或插件执行树复制到前端，因此初稿引用设计第 10.1 节作为违规依据不充分；第 10.3 节关于跨语言公开描述的约定才是主要依据。当前未证明已有字段不匹配，严重度由高降为中。

建议为实际消费的状态 ID、字段及地址约定补公开描述和一致性验证。可以先覆盖现有读取路径，不必先新增 state/ui 或完整投影框架。

### F3. 默认装配的恢复复用与清理异常

**判断：部分成立。清理异常值得优先修复；结构拆分属于后续复用建议。**

- [assembly.py](../../../packages/aurora_bot/src/aurora_bot/assembly.py) 的 _activate 在 finally 中调用 _compact。若清理抛错，原始失败或取消可能被替代，应保留原异常及清理失败信息；没有原始异常时也不能仅记录日志后宣称成功。
- 显式 activate 在 runtime.current 非空时拒绝执行；[runtime.py](../../../packages/aurora_agent/src/aurora_agent/runtime.py) 也会拒绝在显式激活占用期间接管。两个入口不等于两个调度者同时执行，不能直接认定违反单一调度所有者。
- 模型和工具所有权、地址分配、保留策略本来属于装配职责。[拆包评估第 4.3 节](aurora_agent_extraction_assessment.md#43-恢复与清理需要可复用实现) 支持提取中断修正和 pending 保留等小范围辅助，不要求把所有策略迁入 agent。

不将“上帝类”作为独立缺陷，也不预先要求拆出 ModelResources、ToolOwnership、BotRuntimeHost。若收敛激活入口，须处理显式 ExecutionRequest 身份及异常传播差异，不能直接把现有 activate(request) 替换为无参数 runtime.activate() + wait()。

### F4. MCP 来源和默认对话上下文的长期保留策略

**判断：容量风险成立，初稿部分描述不准确。类别：长期运行能力。**

- [WorldRecords](../../../packages/aurora_world/src/aurora_world/records.py) 每次操作复制保留日志；默认完整保存。MCP 来源没有声明 RecordRetention，默认 bot 的 messages 也没有上下文裁剪策略。
- 环境时间默认保留最新 1 条，天气保留一小时内最多 4 条，并可配置。不能泛称所有环境消息都会无限增长。
- [ContextPersistence](../../../packages/aurora_core/src/aurora_core/persistence.py) 等待状态变化后，默认延迟 0.5 秒再 flush；快照只包含 persistent 状态，相同修订不会再次保存。初稿“每 0.5 秒对完整 ctx 做快照并写入”不准确。
- 有限规模限制、默认保留全部及应用决定保留策略已在设计和 WorldRecords docstring 中说明，因此不是未说明的架构偏离。长期增长仍会增加复制、序列化和模型输入成本。

建议按产品需要补 MCP 来源 retention 和对话上下文窗口，保留 system、未完成工具轮次等必要关联；裁剪会影响去重和消费位置，须同时明确缺口处理。先测量成本，不因本条直接进行增量存储重构。

### F5. MCP 定义持有宿主绑定，限制同一定义对象复用

**判断：部分成立。类别：宿主复用边界，初稿影响范围夸大。**

- [world.py](../../../packages/aurora_adapter/src/aurora_adapter/mcp/world.py) 将 ctx/clients 写入 SourceSpec 的工厂 binding，并拒绝第二次绑定；关闭不解除该绑定。同一份定义对象的重新装配确实受限。
- [tools.py](../../../packages/aurora_adapter/src/aurora_adapter/mcp/tools.py) 的工厂持有宿主 MCPTools，定义仍会留在该 registry 中。但工具目录在初次审查基线就已先构建 entries，再调用 register_many 原子登记；“先构建临时目录、全部校验后原子登记”是现有行为。
- [DefinitionRegistry](../../../packages/aurora_core/src/aurora_core/registry.py) 是实例对象，不是进程级单例；插件工厂每次创建新对象。因此同进程使用新 registry 和新插件对象重建宿主，并不必然遇到旧绑定。
- Lifecycle 本身只允许启动一次。若要求失败后复用原 registry 或原插件对象，应先明确该支持范围，不能把重启宿主和复用已经关闭的宿主混为一谈。

后续产品装配如需定义复用，可采用独立实例工厂或显式资源注入，并验证关闭后复用及失败清理。暂不据此新增全局撤销登记机制。并行进行的 MCP 协商改动不包含在本条的完整验收范围内。

### F6. RunGroup 缺少实例身份

**判断：字段缺失属实，初稿所述当前触发场景不成立。类别：实例切换功能的前置约束。**

[workbench.ts](../../../apps/aurora_tui/src/state/workbench.ts) 的 RunGroup 只有 run/session，取消时使用当前 instance。但当前 Workbench 首次选择实例后保留该目标，目标不可用时置为未就绪，不自动切换；[main.ts](../../../apps/aurora_tui/src/main.ts) 在启动时按参数和偏好构造 Workbench，没有运行中切换实例的产品入口。

因此撤回“当前切换实例后可能取消错对象”的中高严重度定性。未来增加切换或跨实例分组时，应保存 session_id/instance_id/run_id，并按分组身份取消、查询和隔离展示。

### F7. “远程 ctx 访问已实现”的文档歧义

**判断：合理。优先级：低，文档措辞。**

设计第 9 节使用“远程 ctx 访问”，当前实现仅绑定回环并限制 Host。远程也可能指跨进程调用，但容易被理解为已经支持跨机器部署；同文档和计划已明确浏览器及远程认证待交付。

建议改为“本机 HTTP/WS ctx 访问已实现，浏览器与跨机器接入仍待补齐”。不因这句话要求立即实现远程监听和认证。

### F8. 浏览器与 Panel 路径尚未打通

**判断：事实成立，属于已知规划能力，不是当前实现回归。**

server.py 拒绝所有带 Origin 的请求，共享客户端也没有完整的认证配置。当前边界就是本机客户端；[计划 D08](plan.md) 明确记录了这一决定及浏览器/远程接入待交付状态。

Panel 接入前应确定来源、认证和同源部署规则，并做真实浏览器验收。同源或代理本身不替代访问控制，但不应把尚未交付的 Panel 当作现有功能缺陷。

### F9. 依赖表与公共 ID 目录漂移

**判断：成立。优先级：中，文档一致性。**

- model_adapter 实际依赖 config；CLI 实际还依赖 config、logging；设计依赖表未完整表达。
- bot 实际也依赖 config、world[config]，初稿漏列这部分文档漂移。
- ID 目录把 org.aurora.bot:registries/agents 列为已实现，但 bot 插件没有登记该注册表。

应按实际 pyproject 和登记结果同步文档，区分规划 ID。独立 harness 不等于不能依赖 config；“更新依赖表后还必须验收无 config 的模型包”没有当前需求依据。模型配置已位于 configuration 模块，把它真正变为可选分发能力是另一项设计决策，不是修正文档的必要步骤。

### F10. CLI 内置配置服务的启用语义

**判断：实现事实成立，初稿认定违反 requires 规则过重。类别：宿主规则说明。**

[commander.py](../../../packages/aurora_cli/src/aurora_cli/commander.py) 把配置插件加入 explicit 清单，[host.py](../../../packages/aurora_cli/src/aurora_cli/host.py) 固定装配配置组件。这是 CLI 宿主选择的内置基础设施，不是 load_plugins 根据 requires 隐式加载依赖；后者仍只校验已启用集合。

用户的 --plugin 不是全部内置能力的唯一来源，文档应明确“CLI 内置基础设施 + 用户选择插件”的范围。可以进一步讨论是否允许退出该默认值，但不据此直接移除配置服务，也不要求当前硬依赖 config 的 CLI 支持无 config 安装。

### F11. 配置失败后编辑入口未关闭

**判断：成立。优先级：中，失败清理缺陷。**

[lifecycle.py](../../../packages/aurora_core/src/aurora_core/lifecycle.py) 只对进入 prepare 的组件调用 stop_accepting，对已进入 config 的组件执行 CLEAN。[ConfigurationService](../../../packages/aurora_config/src/aurora_config/service.py) 只通过 stop_accepting 解绑 endpoint.files，没有 CLEAN handler。

最小复核在配置服务完成后令后续 configure 回调失败：Lifecycle 最终为 stopped，但 endpoint.files 仍非空，直接调用 configurationList 返回 200。后续 CONFIG handler 失败也沿同一收尾路径。

建议为配置组件补幂等 CLEAN 解绑并验证异常路径。现有生命周期已维护 configured/attempted 等集合，无需为本条重新引入整套阶段跟踪。默认 CLI 此时尚未启动 HTTP 服务，不能推导为失败后仍存在对外监听。

### F12. 配置生命周期实例 ID 的重复字面量

**判断：低优先级维护建议，不是实例身份机制缺陷。**

world/configuration、MCPClients 和配置服务使用同一 aurora_config 字符串。提取 config 包内常量可以减少漂移，但配置组件当前并未提供任意改名接口。

生命周期实例 ID 不需要登记为公共定义，也不需要通过 admission。Lifecycle 构造时已经检查缺少依赖并报告组件和缺失名称；初稿“增加启动前依赖校验”重复了现有实现。若需要可配置实例身份，再显式传递；不要把配置组件常量放入 core。

### F13. 观察者失败后 TUI 可能保留旧连接状态

**判断：条件成立。优先级：中，异常可观察性。**

[subscriptions.ts](../../../packages/aurora_client/src/subscriptions.ts) 的 observerFailed 将句柄 status 更新为 failed、结束连接和订阅，但不会再次通知失败的观察者。TUI 只从回调更新 connection，首次 ready 完成后的观察者失败可能留下 connected/ready 的旧显示。

不能表述为“订阅完全没有终态”：句柄 status 已可读，已有测试验证观察者失败只终止自身订阅。风险在于 TUI 没有独立消费终态的路径。

建议由 TUI 捕获自身观察/渲染错误，或提供独立失败通知并覆盖 ready 后失败的场景。单纯延迟 setStatus 仍会调用同一个失败观察者，不能保证修复。

### F14. 客户端手工校验与公开描述不完全一致

**判断：成立。优先级：中低，契约维护。**

[transport.ts](../../../packages/aurora_client/src/transport.ts) 手工校验身份、枚举与 revision；[editor_contract.py](../../../packages/aurora_config/src/aurora_config/editor_contract.py) 对 revision 只描述 string，而客户端要求 64 位十六进制。生成检查只保证产物与描述一致，不覆盖这些手工约束。

建议补齐公开约束并验证两端一致性。是否生成运行时校验器应按维护成本决定，设计没有强制该方案；请求和响应身份一致等语义校验仍需保留，不能认为通用 JSON Schema 能替代全部逻辑。

### F15. 整键开放没有字段或 location 权限

**判断：未来能力建议，尚未证明当前存在敏感数据暴露。**

API 明确以完整状态键作为白名单边界，同一键的全部 location 开放。这是当前本机方案已经接受的限制，不等于没有任何访问边界。

初稿没有给出已开放键实际包含敏感字段的证据，因此不能只凭缺少字段级 ACL 认定设计违规。后续若要开放混合敏感度状态，再按消费者需要拆键、投影或限制 location；界面脱敏不能替代服务端边界。

### F16. 其他工程事项

| 事项 | 复核结论 | 后续处理 |
| --- | --- | --- |
| Node 版本 | 直接 node 为 24.16.0，pnpm exec node 为 26.13.0；package.json 已配置 devEngines.runtime 管理运行时。初稿未区分入口，不能认定项目没有版本管理 | 经 pnpm 管理的 Node 重跑两项 TUI e2e 均通过；可改善直接运行 pytest 时的环境诊断 |
| 生产 assert | 初次基线与复核源码均为 17 处，初稿“约 40 处”不准确；内部不变量断言不天然是缺陷 | 区分外部输入校验与内部不变量，不机械全部替换 |
| README 为空 | 长度为 0，事实成立 | 属于文档完善；修改仍需用户确认 |
| 无 CI | 未发现 .github 工作流，事实成立 | 可按现有验证矩阵补自动检查，不改变功能缺陷定性 |
| Panel/docsite/landing 骨架 | 尚未交付相应应用，设计和计划已说明 | 不作为回归，检查完成不能等同产品交付 |
| 405 等异常非 JSON | 实测已知路由使用错误方法返回 405 text/plain；客户端解析为 ProtocolError，失去结构化 HTTP 错误信息 | 统一错误信封，并保留状态及必要协议头 |
| 空来源 prepare 异常覆盖 | WorldSources.prepare 在循环后 prune 失败时引用未赋值的 binding；以已关闭 ctx 复现 UnboundLocalError，原始异常为 RuntimeError | 修正异常分支；正常空来源准备不会自行失败，不夸大触发频率 |
| WorldRecords 的 owner 权限 | 低层记录接口本就独立公开；WorldSources 工厂只获得绑定 emit，未提供原始 ctx | 没有实际绕过路径前，不把公开 prune 定性为权限漏洞 |

## 5. 验证结果

### 5.1 初次审查记录

以下为初稿记载的历史执行结果，不是同日复核重新执行的全量验收：

```powershell
uv run --locked pytest packages tests/contract -q
# 601 passed

uv run --locked pytest -q
# 789 passed, 2 failed
# 两项失败：tests/e2e/test_tui.py、tests/e2e/test_tui_recovery.py
# 初稿记录原因为直接 Node 24.16 不支持 --experimental-ffi

pnpm test
# 97 passed

pnpm typecheck:python
# 0 errors, 0 warnings

uv run --locked python scripts/generate.py --check
# 返回 0
```

### 5.2 同日复核

```powershell
uv run --locked pytest packages/aurora_core/tests/unit/test_lifecycle.py packages/aurora_config/tests/unit/test_configuration.py packages/aurora_agent/tests/unit/test_agent_runtime.py packages/aurora_world/tests/unit/test_world_sources.py packages/aurora_world/tests/unit/test_world_retention.py packages/aurora_adapter/tests/unit/test_mcp_tools.py packages/aurora_adapter/tests/unit/test_mcp_world.py tests/e2e/test_default_assembly.py -q
# 192 passed；1 条 Pydantic ReadOnly 提示

pnpm exec vitest run packages/aurora_client/src/__tests__/client.test.ts apps/aurora_tui/tests/workbench.test.ts
# 58 passed

pnpm exec node --version
# v26.13.0；直接 node --version 为 v24.16.0

pnpm exec uv run --locked pytest tests/e2e/test_tui.py tests/e2e/test_tui_recovery.py -q
# 2 passed

uv run --locked python scripts/generate.py --check
# 返回 0
```

最小场景复核只使用临时目录、离线对象和本机测试 HTTP 服务：

- F1：通过 WorldRecords 追加记录后，经开放 RECORDS 的 API 删除，返回 200、result=true，剩余记录地址为 0。
- F11：配置服务成功后令后续 configure 回调失败，生命周期 stopped，endpoint.files 仍已绑定，configurationList 返回 200。
- F16：已知 ctx 路由使用错误 HTTP 方法，返回 405 text/plain。
- F16：无来源的 WorldSources 使用已关闭 ctx 执行 prepare，抛 UnboundLocalError，异常上下文为原 RuntimeError。

复核没有重新执行全量检查、wheel 安装验收或真实模型验收。定向测试通过不代表所有报告问题不存在，也不构成对并行 MCP 未提交改动的完整验收。

## 6. 复核后的建议优先级

1. 修复 F1 世界记录写保护、F11 配置失败清理、F3 的清理异常传播，以及 F16 的异常覆盖和 HTTP 错误信封。保持改动范围具体，补对应行为验证。
2. 对齐 F2/F14 的实际消费契约与校验描述，同步 F9 的依赖和 ID 目录；F7/F10/F12 按文档与小范围维护事项处理。
3. 单独设计 MCP 来源 retention 和默认对话上下文窗口，明确去重、未完成工具轮次及消费缺口，再按测量结果评估存储优化。
4. 在产品装配或 harness 出现明确复用需求时处理 F3/F5 的辅助实现和宿主绑定边界，不以本报告为由提前引入框架抽象。
5. F6 随实例切换能力处理，F8 随 Panel/浏览器接入处理，F15 随实际数据暴露需求处理；不把未交付功能作为当前回归。
6. MCP 主线推进以当时最新计划和实现验收为准，不沿用初稿的历史进度判断。CI 与直接运行测试的版本诊断作为工程完善项。

## 7. 范围与附注

- 初稿关于“实际登记 108 个定义”和第 3 节生成检查等结论属于原基线的审查记录，不表示当前所有动态登记项仍为该数量。
- 初稿记录用户已确认 docs/opencode_like_mcp_config.md 中两个 token 为测试用途且已删除；本次复核未重新核验凭证历史，不把该历史记录转化为新增处理任务。
- 本次仅更新本报告及 docs/CHAGELOG.md，不修改实现、README.md、AGENTS.md 或用户配置；保留工作区其他任务的修改。
- 设计规划不等于已实现能力；本报告将已确认缺陷、条件性风险、维护建议与未来能力分开定性。
