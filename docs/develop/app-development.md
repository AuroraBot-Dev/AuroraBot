---
title: App 开发指南
description: 从目录结构到生命周期，系统化说明 AuroraBot 的 App 开发方式。
order: 2
---

# App 开发指南

AuroraBot 把"应用"定义成她用来感知世界、执行动作的器官。一个 App 不负责推理——它只干两件事：把外面发生的事变成事件，把内核决定的动作落成命令。

**挼挼如是说**

> 写 app 之前先记住一句话：你不是在给 AuroraBot 写大脑，你是在给她做手、做眼睛、做耳朵。大脑的事，让 kernel 去操心。

## 开发前先记住三件事

1. App 负责感知与执行，不负责复杂决策
2. App 应暴露原子命令，别把复杂业务流程藏进去
3. App 的私有状态归 App 自己管，内核不会翻你柜子

## 一个标准 App 的目录结构

```text
apps/<your_app>/
  __init__.py
  manifest.yaml
  runtime.py
  README.md
  config.example.json
```

一眼就够——五个文件，没多余的。

## 核心文件说明

### `manifest.yaml` — 你的名片

这是 app 的能力声明书，告诉平台和内核三件事：

- 我是谁
- 我会干什么
- 调我的时候要给我什么、我会回什么

示例：

```yaml
package: im.polaris.example
name: 示例应用
version: 1.0.0
brain_version: ">=5.0.0"
app_desc: >-
  描述这个应用适合在什么场景下被调用。
commands:
  - name: do_something
    description: 执行一个示例动作
    parameters:
      text:
        type: string
        description: 要处理的文本
        required: true
    returns:
      success:
        type: boolean
        description: 是否成功
```

### `runtime.py` — 你的核心实现

这里放 app 的实际运行逻辑。框架会找到你的类，把平台管子接上，然后在 app 的一生里反复调度你。

示例：

```python
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.platform.application_api import PlatformAPI


class ExampleApplication:
    def __init__(self) -> None:
        self._api: PlatformAPI | None = None

    def _bind(self, api: "PlatformAPI") -> None:
        self._api = api

    def manifest_path(self) -> Path:
        return Path(__file__).with_name("manifest.yaml")

    async def on_start(self) -> None:
        pass

    async def on_tick(self) -> None:
        pass

    async def on_stop(self) -> None:
        pass

    def do_something(self, text: str) -> dict:
        return {"success": True}
```

## 平台注入的常用能力

`_bind(self, api)` 之后，你就拿到了一根通往外界的管子：

### `api.emit_event(event)`

把外面发生的变化上报给内核。

```python
api.emit_event(
    AppEvent(
        source=api.package,
        type="message.received",
        session_id="12345",
        summary="收到一条消息",
        payload={"text": "你好"},
    )
)
```

### `api.data_dir`

每个 App 都有自己的一块自留地，适合放：

- 配置文件
- 缓存
- 临时状态
- 运行日志或快照

### `api.log(level, message)`

用平台的统一日志器记运行信息，不用自己搞一套。

### `api.package`

你当初在 `manifest.yaml` 里声明的包名，通过这个就能拿到。

## 生命周期 — App 的一生

App 从出生到退休，大致是这么个过程：

1. 平台发现你、把你 new 出来
2. 塞给你 `_bind(api)` 这根管子
3. 喊 `on_start()` 让你穿衣服起床
4. 循环里不停打 `on_tick()` 的拍子
5. 退场前叫 `on_stop()` 让你收拾东西

### `on_start()` — 起床

适合干的事：

- 读本地配置
- 初始化连接
- 注册回调
- 恢复上次的运行状态

### `on_tick()` — 日常心跳

适合干的事：

- 看时间到了没
- 翻翻自己的队列
- 派发到期任务

别干的事：

- 长时间阻塞——这样会拖死整个 tick 循环
- 重型同步 I/O

### `on_stop()` — 晚安

适合干的事：

- 把内存里的状态存到磁盘
- 关连接
- 清资源

## 开发建议

### 让内核做决策，让 App 做执行

别在 App 里写"看到关键词 A 就自动走流程 B"这种硬编码逻辑。把它抛成事件，让 kernel 来拍板——ta 才是决策者。

### 命令粒度保持原子化

好命令长这样：

- 语义明确——一眼能看出干什么的
- 参数清晰——要什么、给什么，清清楚楚
- 方便组合——一个命令只干一件事，几个串起来能干大事
- 方便测试——输入输出规整，容易写单测

### 优先保证容错

尤其在 `on_tick()`、文件读取、外联这些容易翻车的环节，一定要优先考虑异常处理和降级路径。宁可优雅降级，也不要直接崩溃。

## 推荐的开发流程

1. 先设计 `manifest.yaml` — 这是你的 API
2. 再实现 `runtime.py` — 这是你的肉体
3. 用 `config.example.json` 说明配置格式
4. 补个 `README.md` 说清楚边界
5. 通过 `app.py`（或未来的 `aur`）做独立调试

## 一个简单的自检清单

- 是否声明了清晰的 `package`
- 是否为每个命令写了准确描述
- 是否避免了让 App 自己承担复杂决策
- 是否把私有状态都放在 `api.data_dir`
- 是否处理了配置缺失与文件损坏等异常

## 继续阅读

- 想理解平台如何调度 App：读 [平台运行时](../architecture/platform-runtime.html)
- 想理解命令怎么最终被执行：读 [认知架构](../architecture/brain-architecture.html)
