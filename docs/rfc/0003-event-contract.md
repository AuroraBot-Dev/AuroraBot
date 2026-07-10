# RFC 0003：事件、因果与效果契约

状态：已接受
日期：2026-07-11

## 决策

### AMP 是跨平台事件信封

Platform 与原生 App 以 UTF-8 JSON 交换 AMP 信封。AMP 至少包含稳定的 `header` 与 `payload`：

```json
{
  "header": {
    "protocol": "amp/1.0",
    "method": "aurora/event",
    "message_id": "uuid",
    "timestamp": "2026-07-11T00:00:00+00:00",
    "source": {"app": "platform.example", "instance": "default"}
  },
  "payload": {
    "type": "message.received",
    "session_id": "session-id",
    "summary": "human-readable summary",
    "data": {},
    "expire_at": null
  }
}
```

`header.method` 描述传输或协议动作；`payload.type` 描述领域事实。普通 MCP Server 不需要实现 AMP；Platform 负责归一化。

### Kernel record 与 AMP 分层

AMP 是不可变的跨边界事实。Kernel 接管后创建自己的 `KernelRecord`，记录 `record_id`、AMP `message_id`、因果父级、episode、生产节点、状态、可用周期、轮次/跳数、租约、错误与保留策略。Kernel 不要求外部平台预先理解或填写这些内部字段。

### 事件状态

记录状态至少为 `PENDING`、`PROCESSING`、`ARCHIVED`、`ERROR`。状态迁移必须是可审计且并发安全的；节点不得直接修改 AMP 正文或其他节点拥有的记录。

### 效果

节点产出的 `effect.requested` 必须在 `payload.data` 中包含能力标识、参数和可关联的请求标识。Platform 执行后必须投递一个新的 `effect.succeeded` 或 `effect.failed` AMP；该事件关联原请求，但仍是新的外部事实。

### 周期、循环与去重

- 一个周期只消费开始时已就绪的记录集合；新产物最早下一周期处理。
- 入口以 `header.message_id` 去重；重放不得产生重复效果。
- 每条派生产物必须记录因果父级和 episode。
- 每个循环必须有显式推进条件与上限；超限转为可审计的终止或错误记录。
- 未完成的临时文件不得被接管；写入采用临时文件加原子改名。

## 验收标准

1. Kernel 能校验 AMP、拒绝损坏或不支持版本的信封，并保留错误审计。
2. 任一效果回执能追溯到其请求和最初输入。
3. 同一 AMP 重放不导致二次 Platform 效果执行。
4. 节点在同一周期内不能消费自己刚产生的事件。
