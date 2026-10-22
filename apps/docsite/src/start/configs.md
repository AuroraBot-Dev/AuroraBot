---
order: 3
---

# 配置

AuroraBot 的内置配置位于个人 `config/` 目录，由 CLI 管理并在启动时补齐缺失文件；已有内容不覆盖，个人 `config/` 不进入 Git。CLI 插件的配置自动进入同一配置目录，也可以声明工作目录内的其他相对路径。
配置文件的用途见[配置与存储](../architecture/configs)。

## 查看与编辑

`aurora config` 默认只读：

- `aurora config`：列出可用配置的名称与路径；
- `aurora config --check`：逐个加载并校验全部配置，显示状态（较慢）；
- `aurora config [name] --init`：创建缺失的配置及配套资源，省略名称时补齐全部配置；
- `aurora config <name>`：显示配置文件路径与解析后的值；
- `aurora config <name> --raw`：显示源文件的原始 TOML；
- `aurora config <name> --edit`：用 `$EDITOR`/`$VISUAL` 打开源文件，退出后重新校验；
- `aurora config <name> --set KEY=VALUE`：按 TOML 路径改写源文件（保留注释与格式），可重复，写入后重新校验。

`--set` 的键是文件内的点分路径，例如 `runtime.log_level=DEBUG`、`engine.run.max_model_calls=32`、`endpoint.0.model=...`，
数组元素用下标访问。`--edit`/`--set` 修改配置声明指向的个人文件，不会写回随包分发的模板。使用 `aurora --root <目录> config` 可管理指定工作目录的内置与插件配置。

修改后执行 `aurora config --check` 校验，再重启 Bot 使配置生效。
