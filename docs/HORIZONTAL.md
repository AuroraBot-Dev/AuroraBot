# AuroraBot 横向体系

> 纵向（分层）由 `tests/foundation/test_dependency_boundaries.py` 强制，已经清晰，本文不重复。
> 本文只管**横向**：名字、集合、因果、扩展——那些穿透所有分层的东西。

---

## 0. 一句话

> **一条 ID 语法覆盖全部可寻址之物；标签把集合命名化；每个物种一张注册表；域是世界的分区键。**

横向体系的全部目的，是让「模型能读到自己的目录」成为可能。硬编码的路由表在 Python 里，
模型永远看不见它；一旦它变成命名空间里的条目和标签，模型就能读、能选、能自己路由。

---

## 1. 四条不变量

| #   | 不变量                                                     | 为什么                                                           |
| --- | ---------------------------------------------------------- | ---------------------------------------------------------------- |
| H1  | 一切可寻址之物只有一个 ID 形式：`<namespace>:<path>`       | 否则每个物种各自发明语法与校验器（现状：8 套）                   |
| H2  | ID 语法统一，**注册表按物种分**                            | 统一的是名字，不是类型。类型留在 value 侧继续抓 bug              |
| H3  | `namespace` 即**所有者**，唯一声明权威                     | 「谁声明了这个名字」必须可回答                                   |
| H4  | 名字与集合在**加载期**解析、校验、冻结；解析不到即启动失败 | 沿用项目既有纪律（缺失依赖、依赖环、同优先级冲突都在启动前失败） |

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

| 概念                                              | 载体              |
| ------------------------------------------------- | ----------------- |
| 所有者                                            | `namespace`       |
| 物种（tool / agent / prompt / platform / 域 / …） | `path` 的第一段   |
| 条目                                              | `path` 的其余部分 |

### 现状 → 目标映射

| 现在                                 | 目标                               | 归属       | 状态      |
| ------------------------------------ | ---------------------------------- | ---------- | --------- |
| `aur.agent.delegate`                 | `aurora:tool/delegate`             | 内置       | ✅ 已落地 |
| `aur.serv.world.read`                | `aurora:tool/world_read`           | 内置       | ✅ 已落地 |
| `aur.builtin.wait`                   | `aurora:tool/wait`                 | 内置       | ✅ 已落地 |
| `aur.mcp.<package>.<raw_name>`       | `<package>:tool/<raw_name 或别名>` | 扩展       | ✅ 已落地 |
| `builtin.root`（agent）              | `aurora:agent/root`                | 内置       | ✅ 已落地 |
| `system.soul`（prompt）              | `aurora:prompt/system/soul`        | 内置       | ✅ 已落地 |
| `builtin.triage`（prompt）           | `aurora:prompt/agent/triage`       | 内置       | ✅ 已落地 |
| `builtin.console`（platform）        | `aurora:platform/console`          | 内置       | ✅ 已落地 |
| `world` / `mcp` / `engine`（module） | 保持原样                           | 内部诊断名 | **不改**  |
| `tools.catalog`（贡献键）            | 保持原样                           | 内部贡献键 | **不改**  |
| `aurora:world/console`               | `aurora:world/console`             | 资源域     | ✅ 已落地 |
| `aurora:world/cadence`               | `aurora:world/cadence`             | 资源域     | ✅ 已落地 |
| `aurora:mcp:<package>`               | `<package>:world`                  | 资源域     | ✅ 已落地 |
| `aurora:tree:<id>`                   | `aurora:run/<id>`                  | **运行域** | ✅ 已落地 |
| `AuroraConfig` 等能力类型            | 保留 Python 类型（value 侧）       | —          | 不需要 ID |

**只改「可被配置或模型寻址」的东西。** module 名与贡献键是内部诊断与接线标识，
既不被配置引用也不被模型看见，改成命名空间化只是噪声——横向体系管的是**可寻址面**，不是所有字符串。

### 换根顺手消掉的一处歧义

`builtin.chat` 在旧方案里**同时是 agent id 和 prompt id**（前者在 `agents.toml`，后者在 `prompts.toml`），
而提示词的「全局 system 片段 vs Agent 局部提示词」只靠 Python 里一个 `_SYSTEM_PREFIX = "system."` 判别。
换根后两者都由 path 段显式表达：

```
aurora:agent/chat                   Agent 原型
aurora:prompt/agent/chat            它的提示词
aurora:prompt/system/soul           全局 system 片段
```

`prompt/<kind>/<name>` 的 kind 段取代了那个隐藏前缀；未知 kind 在读取时直接报错，
而不是悄悄落进 Agent 提示词里。

### 外来名字的接纳规则（第三方 MCP 的接入面）

MCP SDK 对 `Tool.name` **不做任何格式约束**（`annotation=str`），所以门只有我们这一道。
这一层必须是**全函数**：

| 情形              | 处理                          | 理由                                                          |
| ----------------- | ----------------------------- | ------------------------------------------------------------- |
| raw name 本身合法 | **原样使用**，零映射          | 模型看到的就是服务器给的名字                                  |
| 否则              | 确定性别名 `<slug>-<8位哈希>` | 只依赖 raw ⇒ 服务器增删工具不会让已有工具 ID 漂移             |
| 首尾带空白 / 空   | **拒绝**，报出是哪个名字      | 这是 Server 的缺陷；静默别名会让两个看似相同的名字变成两个 ID |

迁移前 `_MCP_TOOL_ID` 会拒绝 `tool/read`、`2fa_verify`、`_private` 这类**完全合法**的第三方名字，
而 discovery 失败会升级成 `McpStartupError` —— **一个古怪工具名就能让整个 AuroraBot 起不来**。
这条现在关闭：任何第三方名字都能接入。

### 模式语言跟随 ID 语法（P2-3 已落地）

模式曾经以 `.` 为唯一段分隔符，于是 `org.aurora.qq:tool/*` 匹配不到
`org.aurora.qq:tool/send.message`——path 里的点被当成了层级。

现在 `*` 不跨哪些字符是**按位置**决定的，因为 ID 的层级语法本来就是三段式的：

| 位置                   | 分层字符 | 单星 `*` 不跨 | 例子                                         |
| ---------------------- | -------- | ------------- | -------------------------------------------- |
| 命名空间段（`:` 之前） | `.`      | `.` `:`       | `*:tool/*` 只够到一层命名空间                |
| path 段（`:` 之后）    | `/`      | `/`           | `org.aurora.qq:tool/*` 够得到 `send.message` |
| 无 `:` 的模式          | `.`      | `.`           | `org.aurora.**` 仍是命名空间前缀模式         |

`**` 在任意位置都跨全部层级。第三方 MCP 的业务 scope 是自由文本，
其中的 `:` 落在 path 段，所以 `qq:*` 仍能匹配 `qq:group:123`。

### 修复的缺陷

- `_MCP_TOOL_ID` 在 `src/tools/registry.py` 与 `src/mcp/tool.py` 写了两份 → **一个** `is_tool_id`（落在 contracts）
- `aurora:`（域）与 `aur.`（工具）两套根 → 工具已并入命名空间化语法，域待 P2-2
- 第三方工具名不合规 → 整个进程起不来 → 已接纳，只报真正无身份的名字

---

## 3. 标签集合（tag）

### 语义

标签是**命名的条目集合**，条目可以是 ID、模式，或 `#其它标签`。展开保留书写顺序，
因此「最后匹配者胜」的语义与直接写模式**完全相同**。

```toml
[[tag]]
name = "aurora:tool/qq-send"
values = [
    "org.aurora.qq:tool/qq_send_*message",
    "!org.aurora.qq:tool/qq_send_forward_message",
]

[[tag]]
name = "aurora:tool/qq"
values = ["#aurora:tool/qq-send", "#aurora:tool/qq-read"]   # 标签可嵌套
```

引用处写 `#aurora:tool/qq`。**保留 `!` 取反**——Minecraft 的 tag 没有取反（只有 `required: false`），
而项目两处已有实现都用「顺序 + 取反」，这是更强的语义，要保留。

### 为什么需要它

项目里**已经有两套手写的 tag 系统**，只是不叫这个名字：

| 位置                                     | 现状                                          |
| ---------------------------------------- | --------------------------------------------- |
| `config.example/agents.toml:15-18,41-42` | 内联 glob + `!` 取反，同一个集合写了两遍      |
| `config.example/memory.toml:4-5`         | `scope_include` / `scope_exclude`，同一套语法 |

还有一处**硬编码的前缀切分**：`src/cadence/cadence.py:33` 的 `_MCP_SCOPE_PREFIX = "aurora:mcp:"`
用字符串前缀硬切「业务域」，应改为 tag 引用。

### 加载期纪律

| 情况                             | 行为                                           |
| -------------------------------- | ---------------------------------------------- |
| 引用未声明的标签                 | **报错**（沿用「精确模式未匹配即报错」的纪律） |
| 标签循环引用                     | **报错**                                       |
| 嵌套超过 16 层                   | **报错**                                       |
| 重复声明同名标签                 | **报错**                                       |
| 展开后精确条目匹配不到任何注册项 | 由 `resolve_names` 报错                        |
| 展开后 glob 条目匹配不到         | 只 warn                                        |

---

## 4. 物种与注册表

**统一的是 ID 语法，不是注册表。** 每个物种一张注册表，语法一致：

| 物种         | 注册表                                               | 现状               |
| ------------ | ---------------------------------------------------- | ------------------ |
| Tool         | `ToolRegistry`（ID → executor）                      | ✅ 已有            |
| Agent        | `AgentCatalog`（ID → definition）                    | ✅ 已有            |
| Prompt       | `PromptCatalog`（ID → 文本）                         | ✅ 已有            |
| 域           | `ScopeCatalog`（ID → 所有者/种类/语义）              | ✅ **已落地**      |
| Tag          | `TagTable`（ID → 条目集合）                          | ✅ 本轮新增        |
| Platform     | 组合期按 id 决定装配                                 | ⚠️ 隐式            |
| Module       | `ModuleSpec`（含 `owns_scopes` / `observes_scopes`） | ✅ **P3a 已落地**  |
| 贡献键       | `Assembly.contributions(key)`                        | ⚠️ 隐式            |
| 能力（类型） | `Assembly.get(type)`                                 | ✅ 保留在 value 侧 |

---

## 5. 域模型

### 两类域，必须分开

|          | 资源域                                        | 运行域                 |
| -------- | --------------------------------------------- | ---------------------- |
| 例子     | `aurora:world/console`、`org.aurora.qq:world` | `aurora:run/<tree_id>` |
| 生命     | 长期存在，被观察                              | 与一次认知运行同寿     |
| 语义     | **Bot 经历的世界**                            | **引擎的运转台账**     |
| 默认可见 | 是                                            | 否                     |

实测（一次 2 节点、23 模型步的树）：94 条提交里 **约 92 条是引擎台账**，总行数
**92% 是元数据**。混在一起写，等于让 Bot 的「生活记录」被自己的运转日志淹没。

### 域 ≠ tag

> tag = 一个 ID 的集合，**没有时间维度**。
> 域 = 一个按域分区的世界事实流 + **单调序号** + **观察前沿**。

所以：**tag 用来表达「哪些域」，域本身仍是带序号的流。**
`#aurora:world/*` 展开成一组域，每个域各自有独立的序号与前沿。

### 域注册表要存的字段

| 字段          | 用途                                                    |
| ------------- | ------------------------------------------------------- |
| `pattern`     | 精确域、`<前缀>:*` 一族域，或 `*:<path>` 任意命名空间   |
| `owner`       | 由 pattern 的命名空间推出；即声明权威（`*` 不算所有者） |
| `kind`        | `resource` / `run`                                      |
| `description` | **给模型读的一句话**                                    |

命名空间通配是扩展域逼出来的：`<package>:world` 里的 package 在发现之前不可知，
注册表无法逐个列举。所以扩展域写成**两条**声明而不是含糊的 `*:world*`：

```toml
[[scope]]
pattern = "*:world"      # 扩展拥有的世界域本身
kind = "resource"

[[scope]]
pattern = "*:world/*"    # 及其子域，例如 <package>:world/room/1
kind = "resource"
```

具体声明必须排在前——`*:world` 也会匹配 `aurora:world/console`，靠首条命中把它让给内置声明。

### 已经吃上力的地方

| 用途       | 之前                                                                    | 现在                                                                             |
| ---------- | ----------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| 记忆可见性 | 用户得手写 `scope_include = ["**", "!aurora:tree:**"]` 才能挡住引擎台账 | 注册表声明 `kind=run`，默认不进记忆；未声明的域一律保留                          |
| 模型可读   | 域对模型完全不可见                                                      | `aurora:tool/world_scopes` 列出所有者、种类与说明                                |
| 声明封闭性 | 无处校验                                                                | 测试断言**代码产生的每个域都被模板覆盖**（`ScopeCatalog.undeclared(...) == ()`） |

`ScopeCatalog.classify` 对未声明的域返回 `None`（宽松），只有**明确声明为 `run`** 的域才被排除——
缺一条声明不能丢掉真实世界内容。

---

## 6. 扩展的三类声明

一个扩展要能说三句话。两条入口的进度不同：

| 扩展想说             | 组合期（`ModuleSpec`）               | 运行期（`aurora app` / `apps.toml`）  |
| -------------------- | ------------------------------------ | ------------------------------------- |
| 我提供哪些 **Act**   | ✅ `provides` + `TOOL_CONTRIBUTIONS` | ✅ 冻结工具目录                       |
| 我拥有哪些**域**     | ✅ **P3a**：`owns_scopes`            | ✅ **P3b**：`scopes`                  |
| 我需要观察哪些**域** | ✅ **P3a**：`observes_scopes`        | ⚠️ 仅 MCP tool contract，声明权在远端 |

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

| 关             | 规则                                                                                                 | 在哪                        |
| -------------- | ---------------------------------------------------------------------------------------------------- | --------------------------- |
| **归属**（H3） | 域必须落在该 App 自己的命名空间下，且前缀按**整段**匹配（`org.aurora.qq` 认领不了 `org.aurora.qqq`） | `AppConfig.__post_init__`   |
| **覆盖**（H4） | 域必须被域注册表覆盖                                                                                 | `build_mcp_specs`（连接前） |

于是「谁拥有这个域」有了唯一答案：`aurora:console` → `console` 模块，`aurora:tree:*` → `engine`，
`aurora:mcp:*` → `mcp`，`aurora:cadence` → `cadence`，`aurora:mcp:org.aurora.qq` → 那个 App。
写错一个域名会在**启动前**失败，不是运行到一半才发现。

声明不是装饰：App 向世界发布事实时，`app_owned_scopes(spec)` 用声明值，未声明才退回
`aurora:mcp:<package>`（`src/mcp/runtime.py`）。所以「我的世界有哪些域」由扩展自己说，
而不是由框架替它猜。

仍然缺的（`aurora/commands/app/verify.py:82`）：

> Aurora 当前只把 MCP 的 Tools 暴露给 Bot：只有 Resources 或 Prompts 的 Server 无法作为工具 App 登记。

**「资源」在 MCP 这条路上已有落脚点**：App 能声明自己的域，也能以 `--events` 作为世界生产者
登记而不必暴露任何 Tool。见 §9 的 P3c。

---

## 7. ReAct 四操作

循环**由域驱动**，四个操作现在各有名字、职责与不变量：

| 操作        | 契约                                    | 域参数                                | 状态            |
| ----------- | --------------------------------------- | ------------------------------------- | --------------- |
| **Observe** | `WorldReader.delta(start, scopes)`      | ✅ 就是域                             | ✅ 已声明（P4） |
| **Recall**  | `MemoryReader.recall(scopes=...)`       | ✅ 就是域                             | ✅ 已声明（P4） |
| **Effect**  | `WorldWriter.append_commit(scopes=...)` | ✅ 就是域                             | ✅ 已声明（P4） |
| **Act**     | `ToolRegistry.execute(call)`            | ⚠️ 靠 `ToolScopes` 携带，地址是工具名 | ✅ 已声明       |

三个结论：

1. 域已经驱动了三阶段——`Observe/Recall/Effect` 的参数本来就是域。
2. **另外三个操作在内核层面一直可替换，缺的从来不是可替换性，而是「谁知道这件事」。**
   内核按 `priority` 裁决同契约的多个 provider（`src/kernel/resolve.py`，
   测试 `tests/kernel/test_kernel.py`），而三个操作都是 `provides=` 的契约类型。
   所以这里做的不是端口化，是**声明 + 校验**（见 §9 的 P4）。
3. 校验只补内核问不了的那件事：**替换之后是否仍是一个完整循环。**

模型可以主动申请一个域：`WorldReadTool.resolve_scopes` 返回 `ToolScopes(observe={scope})`
（`src/tools/builtin/world.py`）。这条是「注意力是一等操作」的种子。

---

## 8. 现状 → 目标：七个待清的点

| #   | 问题                                                                          | 证据                                                                                                                                                                     | 被什么解决                                                                                          |
| --- | ----------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------- |
| 1   | 两套身份机制，字符串侧无唯一权威 → **8 套校验器**                             | `_validate_cross_references`、`_validate_agents`、`resolve_names`、`_reject_unknown`、`require_fields`、`AgentCatalog`、内核 `_validate_names`、`app` 的 24 个 `check_*` | H1+H3                                                                                               |
| 2   | **三套因果表示**：全局 `insertion_sequence`、每域 `sequence`、`based_on` 快照 | `based_on` 实测 **93.2% 重复**，生产代码只读一处                                                                                                                         | 域模型 + P5b                                                                                        |
| 3   | 引擎台账与世界资源同居一条线                                                  | 94 提交里 ~92 条是台账                                                                                                                                                   | ✅ 读侧已分离（P1：记忆按 `kind` 排除运行域）；读代价已按域分区隔离（P5a）；写侧仍共用一条线（P5b） |
| 4   | 两套扩展入口、两个生命周期、无共同语言                                        | `ModuleSpec`（11 个 `module.py`）vs `aurora app`（12 文件 / ~4150 行）                                                                                                   | ✅ 两条入口都能声明「我拥有哪些域」（P3a / P3b）                                                    |
| 5   | 域命名空间混了资源域与运行域                                                  | 无区分标记                                                                                                                                                               | ✅ **P1 已解决**：`kind` 字段 + 注册表                                                              |
| 6   | 正则 / 校验器跨包复制                                                         | `toml.py:91-144` 与 `src/utils/validation.py:13-59` 六函数逐字相同                                                                                                       | H1                                                                                                  |
| 7   | 另外三个操作可替换但**未声明、未校验**                                        | 内核 `priority` 裁决已支持，`WorldReader`/`MemoryReader`/`WorldWriter` 都是 `provides=` 契约                                                                             | §7：声明扩展点 + 语义一致性校验                                                                     |

**其中 #2、#3、#5 是同一件事**，并且与 `delta()` 的全表扫描曾经是**同一个改动**：域成为物理分区键后，
全表扫描已经消失（两万条提交：40001 条 SQL / 31.44 秒 → 1 条 SQL / 0.004 秒，见 §10 的 P5a）；
三套因果表示的归一留给 P5b，它不再依赖存储结构，可以单独决定。

---

## 9. 迁移阶段

| 阶段      | 内容                                                                              | 触碰                                                            | 状态          |
| --------- | --------------------------------------------------------------------------------- | --------------------------------------------------------------- | ------------- |
| **P0**    | 身份层（`Identifier`）+ 标签集合 + 把策略搬出代码                                 | `src/contracts/identity.py`、新配置                             | ✅ **已落地** |
| **P1**    | 域注册表 + `kind`（资源 / 运行）+ 给域一句 description                            | `src/contracts/scope.py`、新配置、`WorldScopesTool`、记忆可见性 | ✅ **已落地** |
| **P2-1a** | 工具 ID 换根 + 第三方名字接纳（含修掉「古怪工具名让进程起不来」）                 | `registry` / `mcp.tool` / `config.example` / 测试               | ✅ **已落地** |
| **P2-1b** | agent / prompt / platform ID 换根 + 三物种应用同一套规则                          | `config.example` + 三处 DTO + 测试                              | ✅ **已落地** |
| **P2-2**  | 域换根到命名空间语法（接受一次数据断层）                                          | 四处域命名 + `scopes.toml` + 域模式                             | ✅ **已落地** |
| **P2-3**  | 标签/可见性模式的语言跟随 ID 语法（按位置决定 `*` 的边界）                        | `src/utils/patterns.py` + 两处消费者                            | ✅ **已落地** |
| **P3a**   | 组合期扩展声明拥有的域与观察的域 + 启动前覆盖校验                                 | `ModuleSpec` + `src/runtime/assembly.py` + 4 个产出域的模块     | ✅ **已落地** |
| **P3b**   | 运行期扩展（`aurora app`）声明自己拥有的域 + 归属与覆盖校验                       | `AppConfig` / `apps.toml` / `build_mcp_specs`                   | ✅ **已落地** |
| **P3c**   | 零工具的 Server 也能作为世界生产者登记（准入 = 至少一种贡献）                     | `aurora app` 准入规则 + `--events`                              | ✅ **已落地** |
| **P4**    | 声明四操作为扩展点 + 装配期校验（齐备性、世界单源）                               | `src/contracts/loop.py` + `src/runtime/assembly.py`             | ✅ **已落地** |
| **P5a**   | 域作为物理分区键 + `delta()` 下推；世界线 schema 1 → 2                            | `src/world` + migration                                         | ✅ **已落地** |
| **P5b**   | 因果表示收敛（全局 `insertion_sequence` / 每域 `sequence` / `based_on` 三套归一） | `src/contracts/world.py` + `src/world` + 引擎与工具读侧         | ⬜            |

P2 建议在 P1 之后（域注册表要先有地方挂 owner——现已具备）。
P5a 是唯一需要 schema migration 的阶段：只增加索引、不改动提交数据，因此对既有世界线是就地升级。
P5b 要动 `WorldCommit.based_on` 这类契约字段，属于语义变更，与 P5a 的存储改动没有依赖关系，可以单独决定。

---

## 10. 已落地清单

### P0：身份与集合

| 文件                                                                                      | 内容                                                                                    |
| ----------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| `src/contracts/identity.py`                                                               | `Identifier` / `TagDefinition` / `TagTable` / `TagsConfig` / `is_namespace` / `is_path` |
| `aurora/configs/tags.py` + `config.example/tags.toml`                                     | 标签集合的声明与解析                                                                    |
| `src/agents/module.py`                                                                    | 装配时展开 `#标签` 再 `resolve_names`                                                   |
| `config.example/agents.toml`                                                              | 重复的 glob 收敛为 `#aurora:tool/qq-send` / `#aurora:tool/qq-read`                      |
| `src/cadence/config.py` + `aurora/configs/reactions.py` + `config.example/reactions.toml` | 即时路由策略离开 Python                                                                 |
| `src/cadence/cadence.py`                                                                  | **删除** `DEFAULT_REACTIVE_RULES`（含写死的中文触发词）                                 |

### P1：域注册表

| 文件                                                      | 内容                                                                                            |
| --------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| `src/contracts/scope.py`                                  | `ScopeKind` / `ScopeDeclaration` / `ScopeCatalog`（自带最小模式匹配，契约层不依赖 `src.utils`） |
| `aurora/configs/scopes.py` + `config.example/scopes.toml` | 域注册表的声明与解析                                                                            |
| `src/tools/builtin/world.py`                              | `aurora:tool/world_scopes`：把域注册表交给模型读                                                |
| `src/memory/memory.py` + `module.py`                      | `kind=run` 的域默认不进记忆；未声明的域保留                                                     |
| `aurora/contracts/config.py`                              | `text_field` 支持 `transform`（与 `strings_field` 对称，供枚举字段使用）                        |

### P3a：组合期扩展声明域

| 文件                                                    | 内容                                                                                        |
| ------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| `src/kernel/declaration.py`                             | `ModuleSpec` / `@module` 新增 `owns_scopes` / `observes_scopes`（校验非空、去空白、不重复） |
| `src/runtime/assembly.py`                               | `declared_scopes()` 汇总 + `validate_declared_scopes()` 启动前覆盖校验                      |
| `src/engine/scopes.py` / `src/mcp/scopes.py`            | 域模式常量 `SCOPE_PATTERN`，命名只在一处                                                    |
| `console` / `cadence` / `engine` / `mcp` 的 `module.py` | 各自声明它拥有的域                                                                          |

### P3b：运行期扩展声明域

| 文件                     | 内容                                                                                                |
| ------------------------ | --------------------------------------------------------------------------------------------------- |
| `src/mcp/scopes.py`      | `owned_scope_prefix()` / `owns_scope()`：前缀按整段匹配，防 `org.aurora.qq` 误认领 `org.aurora.qqq` |
| `src/mcp/config.py`      | `AppConfig.scopes` + 归属校验（H3，命名空间即所有权）                                               |
| `src/mcp/models.py`      | `McpAppSpec.scopes` 携带声明                                                                        |
| `src/mcp/module.py`      | `build_mcp_specs` 校验注册表覆盖（H4，连接前失败）                                                  |
| `src/mcp/runtime.py`     | `app_owned_scopes()`：发布事实时用声明值，未声明才退回标准域                                        |
| `aurora/configs/apps.py` | `scopes` 加入白名单并保持可选（与 `event_mode` 同级）                                               |

### P2-1a：工具 ID 换根与外来名字接纳

| 文件                        | 内容                                                                      |
| --------------------------- | ------------------------------------------------------------------------- |
| `src/contracts/identity.py` | `alias_path()`：全函数，合法即零映射，否则 `<slug>-<8位哈希>`             |
| `src/tools/registry.py`     | `is_tool_id()` 成为**唯一**工具 ID 校验器（旧的两份 `_MCP_TOOL_ID` 消失） |
| `src/mcp/tool.py`           | `mcp_tool_id()`：package 段我们必须合法，raw_name 段原样接纳或别名        |
| `src/mcp/runtime.py`        | 同一命名空间内两个远端名收敛到同一 ID 时，同时报出两个名字                |

### P2-1b：三个物种换根并应用同一套规则

| 文件                        | 内容                                                                                                             |
| --------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `src/contracts/identity.py` | 物种前缀常量（`TOOL_` / `AGENT_` / `PROMPT_` / `PLATFORM_PATH_PREFIX`）与 `SYSTEM_` / `AGENT_PROMPT_PATH_PREFIX` |
| `src/contracts/agent.py`    | `AgentDefinition` 校验自身 ID、prompt ID、工具与 children 的物种                                                 |
| `src/prompt/models.py`      | `PromptCatalog` 校验 Agent prompt ID                                                                             |
| `src/prompt/module.py`      | 按 ID 的 kind 段切分 system / agent，未知 kind 直接报错（取代 `_SYSTEM_PREFIX`）                                 |
| `src/mcp/config.py`         | `PlatformConfig` 校验平台物种前缀                                                                                |

### P2-2：域换根

| 文件                                               | 内容                                                                     |
| -------------------------------------------------- | ------------------------------------------------------------------------ |
| `src/contracts/identity.py`                        | `world_scope(owner)` / `WORLD_SCOPE_PATTERN` / `WORLD_SUB_SCOPE_PATTERN` |
| `src/contracts/scope.py`                           | `*:<path>` 命名空间通配；尾部通配统一要求至少一段；`owners` 排除 `*`     |
| `src/console/events.py` / `src/cadence/cadence.py` | `aurora:world/console` / `aurora:world/cadence`                          |
| `src/engine/scopes.py`                             | 运行域 `aurora:run/<tree_id>`，与其他物种共用同一套语法                  |
| `src/mcp/scopes.py`                                | `mcp_scope(package)` = `world_scope(package)`；子域用 `/`                |
| `src/cadence/cadence.py`                           | **删除**硬编码的 `_MCP_SCOPE_PREFIX`：改由 `source` 按域命名规则现算     |
| `src/tools/builtin/world.py`                       | 域目录工具的 `owners` 改走 `ScopeCatalog.owners`，通配不算所有者         |

### P3c：零工具的世界生产者

原先的准入是「至少一个 Tool」。这条规则把**贡献**和**工具**当成了同一件事，
于是三类 Server 被挡在门外：只有 Resources 的、只有 Prompts 的，以及最要紧的
——**只推事件、不需要任何可调用工具的外部世界桥**。

现在准入问的是「至少能贡献一种东西」：

| 贡献       | 判据                        | 模型能做什么                      |
| ---------- | --------------------------- | --------------------------------- |
| Act        | 发现到至少一个 Tool         | 调用它                            |
| 世界生产者 | `event_mode = world_events` | 等它的世界事件，然后 `world_read` |

两者都做不到的条目纯粹是死配置——既调不动，也等不到它——仍然拒绝，
但拒绝信息会指出 `--events` 这条路。

`event_mode` 之前是安装期写死的 `DEFAULT_EVENT_MODE`，CLI 无法声明，
所以「世界生产者」这条路**根本走不到**。它现在进了三个计划 DTO，
并经由 `registry_entry`（计划 → 配置的唯一翻译点）落进注册表；
远程端点由 `check_remote_config` 在连接之前就拒绝（`streamable_http` 暂不支持事件）。

`verify.require_tools` 改名 `require_contribution`：名字该说清它在判什么，
而不是暗示 Tool 是唯一贡献。

### P4：四操作显式化

| 文件                      | 内容                                                                                     |
| ------------------------- | ---------------------------------------------------------------------------------------- |
| `src/contracts/loop.py`   | `LoopOperation`（名字 / 契约 / 职责 / 不变量）与 `LOOP_OPERATIONS`、`WORLD_PORTS`        |
| `src/runtime/assembly.py` | `validate_loop_operations`：四操作齐备 + 三个世界端口同源；在 `_create` 里对装配结果执行 |

**校验只补内核问不了的那件事。** 内核已经保证：同契约同优先级冲突会失败、
缺依赖会失败。它保证不了的是「替换之后仍是一个完整循环」：

- 缺任一操作 → 那不是一个循环，启动前失败；
- 三个世界端口由不同对象提供 → Bot 会经历一个自己写不进去的世界。

第二条在今天的实现里**恰好成立**，而且是有意为之：`src/world/module.py` 的 `prepare`
会复用外部预先提供的 `WorldJournal`（测试注入预构世界就走这条路），`build` 再把它
登记到全部三个端口下。所以三个端口本来就是同一个对象，校验只是把这件事固定下来。

**顺带记下一处既存类型缺口**：`src.kernel.Capabilities` 把 `settings` 声明为可写属性，
而 `Assembly` 是 frozen 的，两者在类型上并不相容。校验因此只声明自己需要的窄协议
（`get` / `get_optional`），不去改动内核——那是个独立的、影响面更大的问题。

### P2-3：模式语言跟随 ID 语法

| 文件                    | 内容                                                                                        |
| ----------------------- | ------------------------------------------------------------------------------------------- |
| `src/utils/patterns.py` | 按第一个 `:` 切成命名空间段与 path 段，两段各自决定 `*` / `?` 不跨什么；`**` 任意位置跨全部 |

翻译从「按 `.` 切段」改成「逐字符走、按位置取屏蔽集」，因此不需要知道模式里
哪个点属于命名空间、哪个属于名字——**位置本身就说明了这件事**。

**只改了一处断言的语义**：`tests/foundation/test_utils.py` 里原本写着
`not pattern_matches("aurora:tool/*", "aurora:tool/world_read.deep")`，
把旧接缝钉成了期望行为。它现在断言相反的事实，并另加一条 `/` 仍分层、
`*:tool/*` 只够一层命名空间、`qq:*` 仍匹配 `qq:group:123` 的测试。

### P5a：域分区索引与 `delta()` 下推

| 文件                              | 内容                                                                                                                                                         |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `src/world/models.py`             | `world_commit_scopes` 增加覆盖索引 `world_commit_scope_partition (scope, sequence, commit_id)`；`(scope, sequence)` 自此是域分区键                           |
| `src/world/migration/v1.py`       | 1 → 2：`CREATE INDEX IF NOT EXISTS`，只加索引、不触碰数据                                                                                                    |
| `src/world/migration/__init__.py` | `TARGET_VERSION = 2`，`STEPS[1]` 注册该步                                                                                                                    |
| `src/world/store.py`              | `delta()` 把域过滤与 `insertion_sequence` 排序下推到 SQL；`_has_more()` 只查分区索引；`_load_commits()` 按页批量载入正文（每页固定 2 条语句，取代每行 2 条） |

实测（20000 条提交、20 个域、`page_size=64`）：

| 场景                         | 改前                   | 改后               |
| ---------------------------- | ---------------------- | ------------------ |
| 前沿已在 head（应返回 0 条） | 40001 条语句 / 31.44 s | 1 条语句 / 0.004 s |
| 前沿在深处（返回一页）       | 69634 条语句 / 54.70 s | 4 条语句 / 0.018 s |

查询计划确认三条读路径都走覆盖索引：`delta()` 为 `MULTI-INDEX OR` + `SEARCH ... USING COVERING INDEX world_commit_scope_partition (scope=? AND sequence>?)`，
`_has_more()` 与 `commits(scope, after, limit)` 同源。

正确性用差分验证：把旧算法冻结成独立的 `sqlite3` 参照实现，在 5 种 `page_size`、随机域集合与随机前沿上跑 2000 组用例，`end` / 提交序列 / `has_more` 逐字段相等。

### 测试

| 文件                                   | 覆盖                                                                                                                                                                            |
| -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `tests/foundation/test_identity.py`    | 45 项：ID 解析、`alias_path` 对 15 个真实外来名字的全函数性与稳定性、标签展开/嵌套/循环/深度、与内联模式逐字等价、模板往返                                                      |
| `tests/resources/test_scopes.py`       | 19 项：声明校验、所有者推导、首条命中、按类分组、**模板覆盖全部运行时域**、工具输出、**内建模块拥有的域恰好等于注册表所声明**、未注册域启动前失败、观察声明与 `ModuleSpec` 校验 |
| `tests/cli/configs/test_reactions.py`  | 9 项：模板往返、路由命中、字段缺失与未知字段                                                                                                                                    |
| `tests/cli/configs/test_mcp.py`        | +6 项：模板声明 App 拥有的域、跨命名空间被拒、子域可用、重复被拒、前缀整段匹配、未注册域在连接前失败                                                                            |
| `tests/cli/app/test_verify.py`         | +2 项：零工具 + `world_events` 作为世界生产者登记且声明落进注册表；远程端点拒绝 `--events`                                                                                      |
| `tests/cli/app/test_install_cli.py`    | +2 项：`--events` 的 CLI 通路（零工具也登记）与「不加 `--events` 仍拒绝」                                                                                                       |
| `tests/engine/test_loop.py`            | 6 项：四操作的名字与契约互不相同、职责与不变量非空、三个世界端口同源声明、齐备时通过、缺操作报出名字、两个世界被拒、**内建组合恰好满足全部四条不变量**                          |
| `tests/mcp/test_mcp_tool.py`           | +8 项：`read` / `tool/read` / `2fa_verify` / `_private` / `send.message` / `SendMessage` / `send:message` / 非 ASCII **都能接入**；只拒绝真正无身份的名字                       |
| `tests/memory/test_memory.py`          | +3 项：运行域默认排除、未声明域保留、可显式纳入                                                                                                                                 |
| `tests/kernel/test_builtin_modules.py` | 9 条恒真断言（`isinstance(x, object)`）改为实际校验                                                                                                                             |

验证：**1163 passed / 1 skipped**，`ruff` 与 `pyright` 均 0 error，配置 14 个 TOML ↔ 14 个 configs 模块（原 11 个 + `reactions` / `scopes` / `tags`）。

---

## 11. 明确不做

| 不做                                             | 理由                                                                                  |
| ------------------------------------------------ | ------------------------------------------------------------------------------------- |
| 引入 `Daemon` / `MessageBus` / `ParallelTask` 类 | AGENTS.md 禁止引入与 AgentTree 平行的运行模型；三者应表达为 **AgentTree 的性质 + 域** |
| **树内**并行                                     | 会砸掉「确定性单循环」，收益远小于代价。并行只做在树之间                              |
| 为「模型驱动」放宽静态检查                       | 贵的是「类型做身份」那 23 个样板文件，不是注解；注解是实现层唯一抓 bug 的手段         |
| 先改世界线 schema、再定域的分区语义              | 会改两次；域必须先被确认为物理分区键（P5a 与域模型是同一个改动）                      |
