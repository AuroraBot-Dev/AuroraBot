# RFC 0017：Dashboard 单 Owner 与 Token 鉴权

状态：已接受
日期：2026-07-21

## 背景

RFC 0010 将 Dashboard 定义为支持注册、密码登录和普通用户私聊的本地聊天室，RFC 0015 又将 Dashboard
收紧为固定 `owner.local` audience。多用户账号体系不再符合 Dashboard 作为 Aurora 唯一本地管理面板的定位，
并且让配置 owner、实际登录用户和 Bot ingress 授权可能产生分歧。

Dashboard 需要只有一个非 Bot 用户。该用户同时是配置 owner 与管理账号，不经过注册或密码流程；本机持有的
bootstrap token 是建立 Dashboard 会话的唯一凭据。

## 决策

1. Dashboard 只有一个可登录的非 Bot 用户，由 `dashboard.owner.username` 提供稳定用户名。该用户是 owner 与
   管理员的同一身份，Platform 启动时幂等创建，不提供注册、删除、重命名或新增普通用户接口。
2. Dashboard 首次初始化时在数据库同目录创建 `Token.txt`，写入随机、高熵的 bootstrap token。后续启动必须复用
   该文件，不得自动轮换或把 token 写入日志。
3. `POST /api/auth/login` 只接受 `{"token_login": "..."}`。服务端必须以常量时间比较 bootstrap token；成功后签发
   随机 opaque bearer session token，SQLite 只保存 session token 摘要。密码不得参与 Dashboard 鉴权。
4. bearer session 只对持久化 owner 身份有效。旧数据库中的非 owner 用户和消息可以为迁移与审计保留，但这些用户
   不得登录、出现在联系人列表、建立 WebSocket 或成为新消息接收者。
5. Dashboard 联系人固定为内建 Bot。owner 可以查询与 Bot 的历史、同步消息、上传附件、发送文本或命令；现行
   Bot ingress、reply route、publication、幂等与因果边界保持不变。
6. Dashboard 用户表必须持久化唯一 owner 标记。升级旧数据库时，将配置用户名对应的既有用户绑定为 owner；不存在
   时创建该用户。已绑定 owner 与配置用户名冲突时启动必须确定性失败，不能静默改绑。

## 约束与非目标

- Dashboard 仍固定为本地平台；bootstrap token 文件不是远程密钥分发机制。
- 本 RFC 不定义 token 轮换、恢复、多人协作、角色权限或普通用户私聊。
- `Token.txt`、session token 和摘要不得进入 Kernel、AMP、模型上下文或 INFO 日志。
- Bot 仍是不可登录的系统用户；owner 与 Bot 是 Dashboard 中仅有的活跃身份。

## 验收标准

1. 新工作区启动后自动创建配置 owner、Bot、数据库与 `Token.txt`，重复启动不改变 bootstrap token。
2. 注册路由不存在；错误 token 被拒绝，正确 token 只为配置 owner 签发 opaque bearer session。
3. 旧的非 owner session 无法通过 HTTP 或 WebSocket 鉴权，联系人列表只返回 Bot，新消息不能发给旧普通用户。
4. owner 的 Bot 消息、命令、附件、历史、publication 与重启恢复测试继续通过。
5. 数据库迁移保留既有消息，并对 owner 标记施加唯一约束。

## 与现有契约的关系

- 取代 RFC 0010 关于注册、用户名密码登录、双用户私聊和多用户在线状态的决定与验收标准。
- 细化 RFC 0015 的 Dashboard owner 绑定：owner 不再等待用户注册，而是在 Platform 初始化时由配置幂等创建。
- 保留 RFC 0014 的平台边界、RFC 0015 的固定 endpoint/audience 与 publication 语义，以及现有 session bearer
  摘要持久化要求。
