---
order: 3
---

# 配置

AuroraBot 的项目配置位于个人 `config/` 目录，由 `config.example/` 模板复制而来；`config/` 属于个人文件，不进入 Git。
每个 TOML 只由 `aurora/configs` 中同相对路径的模块解析为类型化的只读配置。

## 查看与编辑

`aurora config` 默认只读：

- `aurora config`：列出全部已注册配置的名称与路径（不加载任何配置）；
- `aurora config --check`：逐个加载并校验全部配置，显示状态（较慢）；
- `aurora config <name>`：显示源文件路径与实例化后的类型化值（只加载该配置）；
- `aurora config <name> --raw`：显示源文件的原始 TOML；
- `aurora config <name> --edit`：用 `$EDITOR`/`$VISUAL` 打开源文件，退出后重新校验；
- `aurora config <name> --set KEY=VALUE`：按 TOML 路径改写源文件（保留注释与格式），可重复，写入后重新校验。

`--set` 的键是文件内的点分路径，例如 `runtime.log_level=DEBUG`、`engine.tree.max_depth=8`、`endpoint.0.model=...`，
数组元素用下标访问。只有显式 `--edit`/`--set` 才会写入个人 `config/`，不会回退模板或写回源码。
