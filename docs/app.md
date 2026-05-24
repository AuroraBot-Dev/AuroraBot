**应用层现在是什么状态**

- [qq/runtime.py](file:///e:/AuroraBot/apps/qq/runtime.py)
  - 已从旧 `TodoItem`、`session_buffer` 解耦
  - 收到消息时发 `AppEvent(type="message.received")`
  - 保留发送能力和本地事件记录
  - 新增 `enable_listener=False`, 方便独立测试, 不依赖 NoneBot 消息钩子
- [alarm/runtime.py](file:///e:/AuroraBot/apps/alarm/runtime.py)
  - 已从旧 `TodoItem` 解耦
  - 到点时发 `AppEvent(type="alarm_reminder" / "diary_prompt")`
- [diary/runtime.py](file:///e:/AuroraBot/apps/diary/runtime.py)
  - 已从旧语义记忆/快照系统解耦
  - 现在就是纯持久化写入, 并发出 `AppEvent(type="diary.written")`

**独立测试入口**

- 我新增了项目根目录入口: [app.py](file:///e:/AuroraBot/app.py)
- 这个文件就是你要的“应用功能测试入口”
- 它不依赖旧内核
- 可以直接:
- 注册若干应用
- 调用某个应用命令
- 注入一个事件
- 单独跑若干次 `tick`

**怎么用**

- 查看当前注册的应用和命令:

```bash
uv run python .\app.py
```

- 独立调用日记应用命令:

```bash
uv run python .\app.py --apps diary alarm --command im.polaris.diary.write_diary --payload "{date: 2026-05-08, summary: 独立测试}"
```

- 独立向 QQ 应用注入一个事件:

```bash
uv run python .\app.py --apps qq --event-type message.received --event-source im.polaris.qq --session-id 2779675416 --payload "{text: 你好, user_id: '2779675416'}"
```

- 单独跑若干次应用 tick:

```bash
uv run python .\app.py --apps alarm --ticks 3
```

**注意**

- `payload` 现在支持:
- JSON
- 也支持更适合 PowerShell 的 YAML 风格简写, 比如 `{date: 2026-05-08, summary: 独立测试}`
