# AuroraBot 横向体系

> 纵向（分层）由 `tests/test_dependency_boundaries.py` 强制，已经清晰，本文不重复。
> 本文只管**横向**：名字、集合、因果、扩展——那些穿透所有分层的东西。

---

## 0. 一句话

> **一条 ID 语法覆盖全部可寻址之物；标签把集合命名化；每个物种一张注册表；域是世界的分区键。**

横向体系的全部目的，是让「模型能读到自己的目录」成为可能。硬编码的路由表在 Python 里，
模型永远看不见它；一旦它变成命名空间里的条目和标签，模型就能读、能选、能自己路由。

---

## 1. 四条不变量

| # | 不变量 | 为什么 |
|---|---|---|
| H1 | 一切可寻址之物只有一个 ID 形式：`<namespace>:<path>` | 否则每个物种各自发明语法与校验器（现状：8 套） |
| H2 | ID 语法统一，**注册表按物种分** | 统一的是名字，不是类型。类型留在 value 侧继续抓 bug |
| H3 | `namespace` 即**所有者**，唯一声明权威 | 「谁声明了这个名字」必须可回答 |
| H4 | 名字与集合在**加载期**解析、校验、冻结；解析不到即启动失败 | 沿用项目既有纪律（缺失依赖、依赖环、同优先级冲突都在启动前失败） |

**红线（比上面四条更要紧）：**

> **机制确定，策略动态。**
> 策略（该不该回应、唤起谁、看哪个域、下一步做什么）→ 交给模型。
> 机制（注册表怎么查、域序号怎么发、前沿怎么单调推进、提交怎么幂等）→ 永远是代码。
> AGENTS.md 要求「测试必须离线、确定、无网络、无环境变量依赖」；这条线一破，测试体系就守不住。

---

## 2. 命名空间化 ID

### 语法

```
<namespace>:<path>

namespace  [a-z][a-z0-9_-]*(\.[a-z][a-z0-9_-]*)*     所有者标识；内置为 aurora
path       [A-Za-z0-9_][A-Za-z0-9_.-]*(/[A-Za-z0-9_][A-Za-z0-9_.-]*)*
```

`path` 允许大写，因为远端 MCP 的 raw name 是第三方外部事实（`McpToolBinding` 已是那层映射）。
`namespace` 只允许小写，与项目既有的 MCP package 规则完全一致——**扩展 id 现成就是合法 namespace**。

### 物种显式化

内置的 `builtin.` 与 `system.` 是两个**非正式命名空间**。新语法把「所有者」和「物种」分开：

| 概念 | 载体 |
|---|---|
| 所有者 | `namespace` |
| 物种（tool / agent / prompt / platform / 域 / …） | `path` 的第一段 |
| 条目 | `path` 的其余部分 |

### 现状 → 目标映射

| 现状 | 目标 | 归属 |
|---|---|---|
| `aur.agent.delegate` | `aurora:tool/delegate` | 内置 |
| `aur.serv.world.read` | `aurora:tool/world_read` | 内置 |
| `aur.builtin.wait` | `aurora:tool/wait` | 内置 |
| `aur.mcp.org.aurora.qq.qq_send_message` | `org.aurora.qq:tool/qq_send_message` | 扩展 |
| `builtin.root`（agent） | `aurora:agent/root` | 内置 |
| `builtin.chat`（agent） | `aurora:agent/chat` | 内置 |
| `system.soul`（prompt） | `aurora:prompt/soul` | 内置 |
| `system.world`（prompt） | `aurora:prompt/world` | 内置 |
| `builtin.console`（platform） | `aurora:platform/console` | 内置 |
| `world` / `mcp` / `engine`（module） | `aurora:module/world` | 内置 |
| `tools.catalog`（贡献键） | `aurora:contribution/tools_catalog` | 内置 |
| `aurora:console`（域） | `aurora:world/console` | 资源域 |
| `aurora:cadence`（域） | `aurora:world/cadence` | 资源域 |
| `aurora:mcp:<package>`（域） | `<package>:world` | 资源域 |
| `aurora:tree:<id>`（域） | `aurora:run/<id>` | **运行域** |
| `AuroraConfig` 等能力类型 | 保留 Python 类型（value 侧） | 不需要 ID |

### 修复的缺陷

- `_MCP_TOOL_ID` 在 `src/tools/registry.py:15` 与 `src/mcp/tool.py:19` 写了两份 → 一个解析器
- `aurora:`（域）与 `aur.`（工具）两套根 → 一套
- `platform` / `module` / `contribution` 三类完全没有格式校验（只查非空）→ 同一套规则

---

## 3. 标签集合（tag）

### 语义

标签是**命名的条目集合**，条目可以是 ID、模式，或 `#其它标签`。展开保留书写顺序，
因此「最后匹配者胜」的语义与直接写模式**完全相同**。

```toml
[[tag]]
name = "aurora:tool/qq-send"
values = [
    "aur.mcp.org.aurora.qq.qq_send_*message",
    "!aur.mcp.org.aurora.qq.qq_send_forward_message",
]

[[tag]]
name = "aurora:tool/qq"
values = ["#aurora:tool/qq-send", "#aurora:tool/qq-read"]   # 标签可嵌套
```

引用处写 `#aurora:tool/qq`。**保留 `!` 取反**——Minecraft 的 tag 没有取反（只有 `required: false`），
而项目两处已有实现都用「顺序 + 取反」，这是更强的语义，要保留。

### 为什么需要它

项目里**已经有两套手写的 tag 系统**，只是不叫这个名字：

| 位置 | 现状 |
|---|---|
| `config.example/agents.toml:15-18,41-42` | 内联 glob + `!` 取反，同一个集合写了两遍 |
| `config.example/memory.toml:4-5` | `scope_include` / `scope_exclude`，同一套语法 |

还有一处**硬编码的前缀切分**：`src/cadence/cadence.py:33` 的 `_MCP_SCOPE_PREFIX = "aurora:mcp:"`
用字符串前缀硬切「业务域」，应改为 tag 引用。

### 加载期纪律

| 情况 | 行为 |
|---|---|
| 引用未声明的标签 | **报错**（沿用「精确模式未匹配即报错」的纪律） |
| 标签循环引用 | **报错** |
| 嵌套超过 16 层 | **报错** |
| 重复声明同名标签 | **报错** |
| 展开后精确条目匹配不到任何注册项 | 由 `resolve_names` 报错 |
| 展开后 glob 条目匹配不到 | 只 warn |

---

## 4. 物种与注册表

**统一的是 ID 语法，不是注册表。** 每个物种一张注册表，语法一致：

| 物种 | 注册表 | 现状 |
|---|---|---|
| Tool | `ToolRegistry`（ID → executor） | ✅ 已有 |
| Agent | `AgentCatalog`（ID → definition） | ✅ 已有 |
| Prompt | `PromptCatalog`（ID → 文本） | ✅ 已有 |
| 域 | `ScopeCatalog`（ID → 所有者/种类/语义） | ✅ **已落地** |
| Tag | `TagTable`（ID → 条目集合） | ✅ 本轮新增 |
| Platform | 组合期按 id 决定装配 | ⚠️ 隐式 |
| Module | `ModuleSpec`（含 `owns_scopes` / `observes_scopes`） | ✅ **P3a 已落地** |
| 贡献键 | `Assembly.contributions(key)` | ⚠️ 隐式 |
| 能力（类型） | `Assembly.get(type)` | ✅ 保留在 value 侧 |

---

## 5. 域模型

### 两类域，必须分开

| | 资源域 | 运行域 |
|---|---|---|
| 例子 | `aurora:world/console`、`org.aurora.qq:world` | `aurora:run/<tree_id>` |
| 生命 | 长期存在，被观察 | 与一次认知运行同寿 |
| 语义 | **Bot 经历的世界** | **引擎的运转台账** |
| 默认可见 | 是 | 否 |

实测（一次 2 节点、23 模型步的树）：94 条提交里 **约 92 条是引擎台账**，总行数
**92% 是元数据**。混在一起写，等于让 Bot 的「生活记录」被自己的运转日志淹没。

### 域 ≠ tag

> tag = 一个 ID 的集合，**没有时间维度**。
> 域 = 一个按域分区的世界事实流 + **单调序号** + **观察前沿**。

所以：**tag 用来表达「哪些域」，域本身仍是带序号的流。**
`#aurora:world/extensions` 展开成一组域，每个域各自有独立的序号与前沿。

### 域注册表要存的字段

| 字段 | 用途 |
|---|---|
| `pattern` | 精确域或 `<前缀>:*` 覆盖一族域 |
| `owner` | 由 pattern 的命名空间推出；即声明权威 |
| `kind` | `resource` / `run` |
| `description` | **给模型读的一句话** |

### 已经吃上力的地方

| 用途 | 之前 | 现在 |
|---|---|---|
| 记忆可见性 | 用户得手写 `scope_include = ["**", "!aurora:tree:**"]` 才能挡住引擎台账 | 注册表声明 `kind=run`，默认不进记忆；未声明的域一律保留 |
| 模型可读 | 域对模型完全不可见 | `aur.serv.world.scopes` 列出所有者、种类与说明 |
| 声明封闭性 | 无处校验 | 测试断言**代码产生的每个域都被模板覆盖**（`ScopeCatalog.undeclared(...) == ()`） |

`ScopeCatalog.classify` 对未声明的域返回 `None`（宽松），只有**明确声明为 `run`** 的域才被排除——
缺一条声明不能丢掉真实世界内容。

---

## 6. 扩展的三类声明

一个扩展要能说三句话。两条入口的进度不同：

| 扩展想说 | 组合期（`ModuleSpec`） | 运行期（`aurora app` / `apps.toml`） |
|---|---|---|
| 我提供哪些 **Act** | ✅ `provides` + `TOOL_CONTRIBUTIONS` | ✅ 冻结工具目录 |
| 我拥有哪些**域** | ✅ **P3a**：`owns_scopes` | ✅ **P3b**：`scopes` |
| 我需要观察哪些**域** | ✅ **P3a**：`observes_scopes` | ⚠️ 仅 MCP tool contract，声明权在远端 |

**两条入口都能说「我拥有哪些域」了，而且都由启动前校验把关。**

组合期（P3a）——模块在 `@module(...)` 声明，项目装配入口校验覆盖：

```python
# src/runtime/assembly.py
def validate_declared_scopes(settings, specs) -> None:
    owns, observes = declared_scopes(specs)
    undeclared = settings.resolve(ScopeCatalog).undeclared((*owns, *observes))
    if undeclared:
        raise ValueError(f"模块声明了未注册的域：{', '.join(undeclared)}")
```

运行期（P3b）——App 在 `apps.toml` 声明，两道关：

```toml
[[app]]
package = "org.aurora.qq"
scopes = ["aurora:mcp:org.aurora.qq"]   # 只能声明自己命名空间下的域
```

| 关 | 规则 | 在哪 |
|---|---|---|
| **归属**（H3） | 域必须落在该 App 自己的命名空间下，且前缀按**整段**匹配（`org.aurora.qq` 认领不了 `org.aurora.qqq`） | `AppConfig.__post_init__` |
| **覆盖**（H4） | 域必须被域注册表覆盖 | `build_mcp_specs`（连接前） |

于是「谁拥有这个域」有了唯一答案：`aurora:console` → `console` 模块，`aurora:tree:*` → `engine`，
`aurora:mcp:*` → `mcp`，`aurora:cadence` → `cadence`，`aurora:mcp:org.aurora.qq` → 那个 App。
写错一个域名会在**启动前**失败，不是运行到一半才发现。

声明不是装饰：App 向世界发布事实时，`app_owned_scopes(spec)` 用声明值，未声明才退回
`aurora:mcp:<package>`（`src/mcp/runtime.py`）。所以「我的世界有哪些域」由扩展自己说，
而不是由框架替它猜。

仍然缺的（`aurora/commands/app/verify.py:82`）：

> Aurora 当前只把 MCP 的 Tools 暴露给 Bot：只有 Resources 或 Prompts 的 Server 无法作为工具 App 登记。

**「资源」在 MCP 这条路上仍无落脚点**：App 现在能*声明*自己的域，但 `aurora app` 的准入
仍要求 Server 至少提供一个 Tool。要让它成为「世界生产者」，还差准入规则那一步。

---

## 7. ReAct 四操作

循环今天**已经由域驱动**，只是没被命名：

| 操作 | 契约 | 域参数 | 扩展状态 |
|---|---|---|---|
| **Observe** | `WorldReader.delta(start, scopes)` | ✅ 就是域 | ⚠️ 内核可替换，未声明、未校验 |
| **Recall** | `MemoryReader.recall(scopes=...)` | ✅ 就是域 | ⚠️ 内核可替换，未声明、未校验 |
| **Effect** | `WorldWriter.append_commit(scopes=...)` | ✅ 就是域 | ⚠️ 内核可替换，未声明、未校验 |
| **Act** | `ToolRegistry.execute(call)` | ⚠️ 靠 `ToolScopes` 携带，地址是工具名 | ✅ **唯一被声明为扩展点的** |

两个结论：

1. 域已经驱动了三阶段——`Observe/Recall/Effect` 的参数本来就是域。
2. **另外三个操作在内核层面已经可替换，但没有任何地方声明这是受支持的扩展点。**
   内核按 `priority` 裁决同契约的多个 provider（`src/kernel/resolve.py:134`，
   有测试 `tests/test_kernel.py:101`），而 `WorldReader` / `MemoryReader` / `WorldWriter`
   都是 `provides=` 的契约类型——所以扩展**技术上今天就能**提供一份自己的实现并胜出。
   缺的不是机制，而是两件事：
   - **声明**：没有任何地方说「这三个是扩展点」；
   - **校验**：替换实现可以违反前沿单调性、序号连续性与提交幂等，而无人阻止。

   所以「用不同网络驱动不同阶段」的缺口是**契约与校验**，不是端口化。

模型可以主动申请一个域：`WorldReadTool.resolve_scopes` 返回 `ToolScopes(observe={scope})`
（`src/tools/builtin/world.py:71`）。这条是「注意力是一等操作」的种子。

---

## 8. 现状 → 目标：七个待清的点

| # | 问题 | 证据 | 被什么解决 |
|---|---|---|---|
| 1 | 两套身份机制，字符串侧无唯一权威 → **8 套校验器** | `_validate_cross_references`、`_validate_agents`、`resolve_names`、`_reject_unknown`、`require_fields`、`AgentCatalog`、内核 `_validate_names`、`app` 的 24 个 `check_*` | H1+H3 |
| 2 | **三套因果表示**：全局 `insertion_sequence`、每域 `sequence`、`based_on` 快照 | `based_on` 实测 **93.2% 重复**，生产代码只读一处 | 域模型 + 存储重设 |
| 3 | 引擎台账与世界资源同居一条线 | 94 提交里 ~92 条是台账 | ✅ 读侧已分离（P1：记忆按 `kind` 排除运行域）；写侧仍同居一条线（P5） |
| 4 | 两套扩展入口、两个生命周期、无共同语言 | `ModuleSpec`（11 个 `module.py`）vs `aurora app`（12 文件 / ~4150 行） | ✅ 两条入口都能声明「我拥有哪些域」（P3a / P3b） |
| 5 | 域命名空间混了资源域与运行域 | 无区分标记 | ✅ **P1 已解决**：`kind` 字段 + 注册表 |
| 6 | 正则 / 校验器跨包复制 | `_MCP_TOOL_ID` ×2；`toml.py:91-144` 与 `src/utils/validation.py:13-59` 六函数逐字相同 | H1 |
| 7 | 另外三个操作可替换但**未声明、未校验** | 内核 `priority` 裁决已支持，`WorldReader`/`MemoryReader`/`WorldWriter` 都是 `provides=` 契约 | §7：声明扩展点 + 语义一致性校验 |

**其中 #2、#3、#5 是同一件事**，并且与 `delta()` 的全表扫描（实测两万条提交
= 40001 条 SQL / 14.35 秒）是**同一个改动**：域一旦成为物理分区键，三套因果和全表扫描一起消失。

---

## 9. 迁移阶段

| 阶段 | 内容 | 触碰 | 状态 |
|---|---|---|---|
| **P0** | 身份层（`Identifier`）+ 标签集合 + 把策略搬出代码 | `src/contracts/identity.py`、新配置 | ✅ **已落地** |
| **P1** | 域注册表 + `kind`（资源 / 运行）+ 给域一句 description | `src/contracts/scope.py`、新配置、`WorldScopesTool`、记忆可见性 | ✅ **已落地** |
| **P2** | ID 语法切到 `namespace:path`（接受一次数据断层） | 全仓 ID 字面量 + `config.example` + 测试 | ⬜ |
| **P3a** | 组合期扩展声明拥有的域与观察的域 + 启动前覆盖校验 | `ModuleSpec` + `src/runtime/assembly.py` + 4 个产出域的模块 | ✅ **已落地** |
| **P3b** | 运行期扩展（`aurora app`）声明自己拥有的域 + 归属与覆盖校验 | `AppConfig` / `apps.toml` / `build_mcp_specs` | ✅ **已落地** |
| **P3c** | 让只有 Resources 的 Server 也能作为世界生产者登记 | `aurora app` 准入规则 | ⬜ |
| **P4** | 声明四操作为扩展点，并为替换实现加语义一致性校验 | contracts 契约文档 + 内核或模块层校验 | ⬜ |
| **P5** | 域作为物理分区键 + `delta()` 下推 + 因果表示收敛 | `src/world` + migration | ⬜ |

P2 建议在 P1 之后（域注册表要先有地方挂 owner——现已具备）。
P5 是唯一需要 schema migration 的阶段。

---

## 10. 已落地清单

### P0：身份与集合

| 文件 | 内容 |
|---|---|
| `src/contracts/identity.py` | `Identifier` / `TagDefinition` / `TagTable` / `TagsConfig` / `is_namespace` / `is_path` |
| `aurora/configs/tags.py` + `config.example/tags.toml` | 标签集合的声明与解析 |
| `src/agents/module.py` | 装配时展开 `#标签` 再 `resolve_names` |
| `config.example/agents.toml` | 重复的 glob 收敛为 `#aurora:tool/qq-send` / `#aurora:tool/qq-read` |
| `src/cadence/config.py` + `aurora/configs/reactions.py` + `config.example/reactions.toml` | 即时路由策略离开 Python |
| `src/cadence/cadence.py` | **删除** `DEFAULT_REACTIVE_RULES`（含写死的中文触发词） |

### P1：域注册表

| 文件 | 内容 |
|---|---|
| `src/contracts/scope.py` | `ScopeKind` / `ScopeDeclaration` / `ScopeCatalog`（自带最小模式匹配，契约层不依赖 `src.utils`） |
| `aurora/configs/scopes.py` + `config.example/scopes.toml` | 域注册表的声明与解析 |
| `src/tools/builtin/world.py` | `aur.serv.world.scopes`：把域注册表交给模型读 |
| `src/memory/memory.py` + `module.py` | `kind=run` 的域默认不进记忆；未声明的域保留 |
| `aurora/contracts/config.py` | `text_field` 支持 `transform`（与 `strings_field` 对称，供枚举字段使用） |

### P3a：组合期扩展声明域

| 文件 | 内容 |
|---|---|
| `src/kernel/declaration.py` | `ModuleSpec` / `@module` 新增 `owns_scopes` / `observes_scopes`（校验非空、去空白、不重复） |
| `src/runtime/assembly.py` | `declared_scopes()` 汇总 + `validate_declared_scopes()` 启动前覆盖校验 |
| `src/engine/scopes.py` / `src/mcp/scopes.py` | 域模式常量 `SCOPE_PATTERN`，命名只在一处 |
| `console` / `cadence` / `engine` / `mcp` 的 `module.py` | 各自声明它拥有的域 |

### P3b：运行期扩展声明域

| 文件 | 内容 |
|---|---|
| `src/mcp/scopes.py` | `owned_scope_prefix()` / `owns_scope()`：前缀按整段匹配，防 `org.aurora.qq` 误认领 `org.aurora.qqq` |
| `src/mcp/config.py` | `AppConfig.scopes` + 归属校验（H3，命名空间即所有权） |
| `src/mcp/models.py` | `McpAppSpec.scopes` 携带声明 |
| `src/mcp/module.py` | `build_mcp_specs` 校验注册表覆盖（H4，连接前失败） |
| `src/mcp/runtime.py` | `app_owned_scopes()`：发布事实时用声明值，未声明才退回标准域 |
| `aurora/configs/apps.py` | `scopes` 加入白名单并保持可选（与 `event_mode` 同级） |

### 测试

| 文件 | 覆盖 |
|---|---|
| `tests/test_identity.py` | 22 项：ID 解析、标签展开/嵌套/循环/深度、与内联模式逐字等价、模板往返 |
| `tests/test_scopes.py` | 19 项：声明校验、所有者推导、首条命中、按类分组、**模板覆盖全部运行时域**、工具输出、**内建模块拥有的域恰好等于注册表所声明**、未注册域启动前失败、观察声明与 `ModuleSpec` 校验 |
| `tests/test_reactions_configs.py` | 9 项：模板往返、路由命中、字段缺失与未知字段 |
| `tests/test_mcp_configs.py` | +6 项：模板声明 App 拥有的域、跨命名空间被拒、子域可用、重复被拒、前缀整段匹配、未注册域在连接前失败 |
| `tests/test_memory.py` | +3 项：运行域默认排除、未声明域保留、可显式纳入 |
| `tests/test_builtin_modules.py` | 9 条恒真断言（`isinstance(x, object)`）改为实际校验 |

验证：**1132 passed / 1 skipped**，`ruff` 与 `pyright` 均 0 error，配置 14 个 TOML ↔ 14 个 configs 模块（原 11 个 + `reactions` / `scopes` / `tags`）。

---

## 11. 明确不做

| 不做 | 理由 |
|---|---|
| 引入 `Daemon` / `MessageBus` / `ParallelTask` 类 | AGENTS.md 禁止引入与 AgentTree 平行的运行模型；三者应表达为 **AgentTree 的性质 + 域** |
| **树内**并行 | 会砸掉「确定性单循环」，收益远小于代价。并行只做在树之间 |
| 为「模型驱动」放宽静态检查 | 贵的是「类型做身份」那 23 个样板文件，不是注解；注解是实现层唯一抓 bug 的手段 |
| 先改世界线 schema、再定域的分区语义 | 会改两次；域必须先被确认为物理分区键（P5 与域模型是同一个改动） |
