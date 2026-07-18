# RFC 0002：配置基准

状态：已接受
日期：2026-07-11

## 决策

### TOML 为主，JSON 为辅

结构性配置必须使用 TOML；运行时数据、AMP 事件、工作区记录和扩展私有载荷使用 JSON。JSON 不得承担运行图、模型角色、应用启用状态或密钥映射等主配置职责；YAML 不进入运行时配置链。

### 配置文件

```text
config/aurora.toml          全局默认：运行时、SOUL、存储、日志、模型角色
config/apps.toml            内建与外部应用、平台适配器及启用状态
config/nodes.toml           图实例、边和节点参数
config/profiles/<name>.toml 仅覆盖 aurora.toml 的环境差异
```

运行器必须先加载 `aurora.toml`，再加载选定 profile。profile 选择顺序为显式启动参数、`AURORA_PROFILE`、`runtime.profile`、无 profile。表递归合并，标量与数组整体替换；未知键、类型不匹配和无效引用必须在启动前失败。

`apps.toml` 与 `nodes.toml` 是独立领域配置，不被 profile 隐式覆盖。环境差异需要改变应用或节点启用状态时，必须使用显式配置路径或后续 RFC 定义的领域 profile，而不是隐藏环境变量。

### 环境变量与密钥

密钥只来自环境变量。TOML 只能声明其名称，例如 `secret_env = "OPENAI_API_KEY"`；不得保存值。`.env` 仅可作为本地开发时的环境注入辅助，不能定义结构性配置，也不能覆盖任意 TOML 字段。

除 `AURORA_PROFILE` 外，环境变量不得静默覆盖 TOML 配置。任何未来的显式覆盖机制必须声明白名单、类型转换和来源审计。

### SOUL

`SOUL.md` 是版本化的文本配置，其路径由 `aurora.toml` 声明。Kernel 在周期开始时读取固定版本，并将其内容摘要或哈希记录入快照；运行时不得修改 SOUL。

## 验收标准

1. 没有 YAML 读取器参与配置加载。
2. 同一组 TOML 文件和环境变量总能得到相同的已验证配置快照。
3. 配置快照能表明 profile、文件来源和 SOUL 版本。
4. 密钥不会写入 TOML、工作区快照或日志。
