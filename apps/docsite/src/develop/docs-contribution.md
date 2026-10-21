---
order: 1
---

# 贡献与修订文档

页面位于 `apps/docsite/src/`，按读者任务组织：

- `start/`：安装、启动与日常配置。
- `develop/`：开发步骤、示例与验证方法。
- `architecture/`：组件职责、运行机制与边界。
- `reference/`：精确协议与查阅资料。

正文以简体中文描述当前用法、能力和限制。修改行为时直接更新对应说明；变更经过和修复记录写入仓库的 `docs/CHANGELOG.md`。只保留帮助读者操作或理解机制的细节，同一内容通过链接引用，避免重复。

标题说明页面主题，`order` 控制侧边栏排序。站内链接使用相对路径；命令示例注明执行目录，并与实际入口一致。

在仓库根目录预览和验证：

```bash
pnpm dev docsite
pnpm build docsite
```

构建检查 Markdown 和站内链接。完整环境说明见[离线文档](../start/offline-docsite)。
