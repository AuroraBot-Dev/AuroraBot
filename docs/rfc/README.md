# AuroraBot RFC

`docs/rfc/0300-unified-architecture-and-contracts.md` 是 AuroraBot 唯一的 RFC 与设计基准。此前分散的 02xx 文件已合并，
历史内容由 Git 保存，不再出现在当前工作树。

## 当前基准

- [0300 AuroraBot 统一架构与公共契约](0300-unified-architecture-and-contracts.md)

## 变更规则

- 影响模块边界、事件、结构配置、扩展协议、模型调用、持久化语义或进程组合的改动，必须先更新 RFC 0300。
- 除非先修改 RFC 0300 的治理规则，不新增并行编号 RFC。
- 已接受 RFC 高于 `ARCHITECTURE.md`、`docs/TECHNICAL.md`、README、配置样例、代码注释和现有实现。
- Python 源码与测试的注释和 docstring 禁止提及具体 RFC 编号或章节；局部说明必须直接描述行为和原因。
