# aurora app

`aurora app` 管理 Bot 的 MCP App：登记 MCP Server，让 `aurora start` 启动本地 Server 或连接远程端点，
并发现它们提供的工具。

登记结果写在个人配置 `config/apps.toml`，运行 `aurora config apps --init` 创建。
`aurora app` 只修改已有配置。

## 三种登记来源

| 来源     | 命令写法                                      | Aurora 做了什么                                                   | 需要什么                                                          |
| -------- | --------------------------------------------- | ----------------------------------------------------------------- | ----------------------------------------------------------------- |
| 源码仓库 | `install owner/repo`                          | clone 仓库到 `extensions/apps/<owner>/<repo>/`，注册启动命令      | 仓库根目录有 `aurora-app.toml`，或用 `--command` 显式给出启动命令 |
| 包管理器 | `install --npx <pkg>` / `install --uvx <pkg>` | 启动包完成 MCP 检查，并登记启动命令；包管理器可能下载到自己的缓存 | 本机装了 npx 或 uvx                                               |
| 远程端点 | `install https://mcp.example.com/rpc`         | 检查端点并在 `apps.toml` 登记地址与认证变量名；不下载 Server 文件 | 端点能完成 MCP 握手并提供 Tool                                    |

三者的共同点：登记前都要通过一次 MCP 握手，确认它连得上、至少能提供一个 Tool。装完的 App
是「已经登记」，不保证 Bot 已能调用 —— 那还取决于当前 Agent 的工具可见配置。

## 命令

### `list`

列出注册表里的每个 App 及其就绪状态。

```text
| PACKAGE ID            | TYPE   | TRANSPORT       | ENABLED | STATE      | PATH                          |
```

- `TYPE` 是 `local`（要在本机起进程）或 `remote`（启动时连过去）。
- `STATE` 为 `ready`（本地目录在）、`missing`（目录不在）、`invalid`（条目或路径不合规）、
  `configured`（远程条目读得通；列表不检查端点是否在线）。
- 有任何一条不是 `ready`/`configured` 时退出码为 1，脚本可以直接据此判断。

### `search [QUERY]`

在 GitHub 上搜索带 `aurorabot-app` topic 的仓库，`QUERY` 追加在 topic 之后用来缩小范围。

```bash
aurora app search                      # 列出所有候选
aurora app search weather              # 只找与 weather 相关的
aurora app search --sort stars --order desc
```

`--page`（默认 1）、`--page-size`（默认 20，最多 100）、`--sort`（stars/forks/updated）、
`--order`（asc/desc，需与 `--sort` 同用）。GitHub 只暴露前 1000 条结果，翻不到更远时请用
关键词缩小范围。

设置 `GITHUB_TOKEN` 可以提高速率上限；`aurora app` 会读项目 `.env`，把它写在里面即可。
搜索不读也不写注册表，没有 `config/apps.toml` 也能用。

### `install SOURCE`

`SOURCE` 决定走哪条路径：GitHub 的 `owner/repo` 或仓库 URL 走源码安装，其他 HTTPS URL 走
远程端点登记，`--npx` / `--uvx` 走包管理器安装。

```bash
# 源码仓库：需要仓库声明了 aurora-app.toml
aurora app install Churk-Ben/Aurora-QQ
aurora app install https://github.com/Churk-Ben/Aurora-QQ --ref v1.2.0

# 仓库没有清单时，自己接管启动命令
aurora app install owner/repo --command '["uv", "run", "my-mcp"]'

# 包管理器：不克隆任何仓库
aurora app install --npx @modelcontextprotocol/server-filesystem \
  --arg /path/to/allowed/dir

# 远程端点：凭据只放变量名，值留在环境里
aurora app install https://mcp.example.com/rpc --auth-env MCP_TOKEN
```

选项：

| 选项                      | 作用                                                               |
| ------------------------- | ------------------------------------------------------------------ |
| `--ref REF`               | 分支或标签，交给 Git 解析；只用于源码安装                          |
| `--package ID`            | 显式指定 package ID，默认由来源推导                                |
| `--command JSON`          | 显式启动命令，JSON 字符串数组；给出后不再要求 `aurora-app.toml`    |
| `--npx` / `--uvx PACKAGE` | 交给对应包管理器运行，两者只能用一个                               |
| `--arg VALUE`             | 传给 Server 的参数，可重复，排在包名之后；只用于 `--npx` / `--uvx` |
| `--auth-env ENV_NAME`     | Bearer token 所在的环境变量名；只用于远程 URL                      |
| `--disabled`              | 登记为禁用（默认启用）                                             |
| `--yes`                   | 跳过最后那次确认，不跳过任何检查                                   |

源码安装的顺序是有意的：准入、package 查重、目标路径冲突、读清单都在 clone 之前完成 ——
这几种情形在下载整库之前就能给出答案。clone、检测、展示、确认与握手完成后，
提交前再核对一次注册表与目标路径。

安装必须完成 MCP 握手并发现至少一个 Tool；失败时不会写入注册表。`list` 的 `ready` 只表示
本地目录仍存在，`configured` 只表示远程配置可解析；它们都不保证 Server 此刻在线。

### `remove PACKAGE`

从注册表移除一个 App。受管目录（`extensions/apps/<owner>/<repo>/`）一并删除：先把目录搬到
回收目录，注册表写成功之后才真删，写失败则搬回来。

```bash
aurora app remove com.example.weather
aurora app remove com.example.weather --force
```

不提问，也不需要 `--yes`。`--force` 只跳过「这个目录确实来自它路径所声称的那个仓库」这项
校验（用于 `.git` 已被改动或删除的目录），不放宽任何路径边界。包管理器安装与远程端点的条目
不产生 Aurora 拥有的文件，移除时只解除注册，输出的第二行会说清这一点。

### `enable` / `disable`

```bash
aurora app disable com.example.weather
aurora app enable com.example.weather
```

改的是注册表里的 `enabled`，下次 `aurora start` 生效。

## `aurora-app.toml`

源码型自动安装只认这一份契约：

```toml
manifest_version = 1

[server]
command = ["uv", "run", "weather-mcp"]
```

- 只允许 `manifest_version`、`[server].command` 两个键，多写一个会被拒绝 —— 清单是契约，
  多出来的键多半是作者以为它生效了。
- `command` 是非空的字符串数组，第一项是可执行名；带路径分隔符时必须是仓库内的相对路径。
- 没有 `prepare`、`install` 之类的字段：Aurora 在安装期不执行仓库里的命令，也不替仓库装
  依赖。前置条件由仓库自己在 README 里写清楚。
- 清单缺失或格式不合规时，Aurora 无法确定启动命令；可以用 `--command` 显式指定。
  GitHub API 请求失败会单独报告，不会当成清单缺失。

## 注册表条目

`config/apps.toml` 里每个 App 是一个 `[[app]]` 表：

```toml
[[app]]
package = "org.aurora.qq"
enabled = true
transport = "stdio"
working_dir = "extensions/apps/Aurora-QQ"
command = ["uv", "run", "--frozen", "aurora-qq-mcp"]
env = ["AURORA_QQ_TOKEN", "AURORA_QQ_CONFIG"]
timeout_seconds = 60
event_mode = "world_events"
```

| 字段              | 说明                                                                                                                        |
| ----------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `package`         | 小写点分 ID，Aurora 内部的唯一身份；也是 Bot 看到的工具名前缀                                                               |
| `enabled`         | 是否在 `aurora start` 时启动                                                                                                |
| `transport`       | `stdio`（本地进程）或 `streamable_http`（远程端点）                                                                         |
| `working_dir`     | 仅 stdio：项目内相对目录，不得越出项目根或经过符号链接；`remove` 只把 `extensions/apps/<owner>/<repo>` 这一种形状当受管目录 |
| `command`         | 仅 stdio：启动命令的 argv                                                                                                   |
| `env`             | 仅 stdio：要额外传给 Server 的环境变量**名**，值取自 Aurora 进程的环境；`aurora app` 写出的条目恒为 `[]`                    |
| `url`             | 仅 streamable_http：端点的 HTTPS 地址                                                                                       |
| `auth_env`        | 仅 streamable_http：Bearer token 所在的环境变量名，可选                                                                     |
| `timeout_seconds` | MCP 连接和协议读取的超时时间                                                                                                |
| `event_mode`      | 是否把 Server 上报的事件送进 Bot 的世界线                                                                                   |

两种 transport 的键集是各自封闭的白名单：多写一个键（例如给远程条目加 `working_dir`）会让
`aurora start` 拒绝整个文件。手工编辑时请参照 `src/aurora_cli/configs/apps/apps.toml` 的形状。

注册表的 `auth_env` 只保存变量名，token 值从运行环境读取。URL 不接受用户信息或常见的凭据参数，
例如 `token=`、`key=`；错误摘要会遮蔽已知的敏感变量值。

## 磁盘与写入

- 源码安装的落点是 `extensions/apps/<owner>/<repo>/`，`extensions/` 由 Git 忽略。
- 安装过程中的暂存目录 `.aurora-stage-<hex>`、移除过程中的回收目录 `.aurora-remove-<hex>`
  都在 `extensions/apps/` 下，正常结束时不会留下。失败信息里会给出确切的残留路径。
- `config/apps.toml` 通过同目录临时文件原子替换。一次只运行一个 `aurora app` 写命令；
  多个写命令并行执行时，后提交的修改可能覆盖先提交的修改。

## 退出码

| 码  | 含义                                                                    |
| --- | ----------------------------------------------------------------------- |
| 0   | 成功（`search` 没有结果也是 0）                                         |
| 1   | 一般失败：写盘、网络、git、握手、`list` 里有条目自身不可用              |
| 2   | 配置或输入错误：注册表缺失/无法解析、package 不合规、路径冲突、参数用错 |
| 130 | 被用户取消（对确认回答 n，或 Ctrl-C）                                   |

## 排错

**未找到 `config/apps.toml`** —— 运行 `aurora config apps --init`。

**仓库没有 `aurora-app.toml`** —— 用 `--command` 给出启动命令；如果它其实是个远程服务，改用
`install <URL>` 登记地址。

**握手失败** —— 错误信息里会说清是本地进程还是远程端点、失败在哪个阶段（启动、协议连接、
工具发现、关闭）。本地进程失败时按提示手动在它的工作目录下跑一遍那条命令；远程端点失败时
先用 `curl -i` 确认地址可达，`--auth-env` 声明的变量未设置或已过期都会 401。

**`list` 里 `STATE=missing`** —— 目录被删了（手工清理、换机器、移动过项目）。重新 `install`
一次，或手工修正注册表里那条。

**`STATE=invalid`** —— 条目字段不合规，或 `working_dir` 越出了项目根、经过了符号链接。错误
信息里带着出问题的那个值。
