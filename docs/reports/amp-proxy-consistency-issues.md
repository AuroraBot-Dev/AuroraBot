# AMP Envelope 使用不一致 & 代理单例模式不统一

> 记录日期：2026-07-09
>
> 背景：kernel/nodes 层即将彻底重写，以下两个问题是 platform 层和基础设施层各自内部的
> 设计债务，不受 kernel/nodes 重构影响，应独立跟进。

---

## 一、AMP Envelope 使用不一致

### 现状

`src/platform/amp.py` 定义了一套完整的数据类：

| 类 | 职责 |
|----|------|
| `AMPHeader` | 协议版本、方法、消息 ID、时间戳、来源 |
| `AMPPayload` | 事件类型、会话 ID、摘要、结构化数据、过期时间 |
| `AMPEnvelope` | header + payload 的容器 |
| `build_event_envelope()` | Host 侧构建 envelope 的工厂函数 |
| `parse_amp_envelope()` | 从 dict 反序列化 envelope |
| `amp_to_file_event()` | envelope → 可写入文件的 dict |

设计意图很明确：所有进出 Brain 的事件都走 AMP envelope 归一化，Platform 层负责生成，
Brain 层只消费已归一化的 AMP 格式。

### 实际使用情况

| 模块 | 使用方式 | 问题 |
|------|----------|------|
| `nodes/event_bridge.py` | 正确使用 `build_event_envelope` / `parse_amp_envelope` / `amp_to_file_event` | 无 |
| `nodes/routers/message_preprocessor.py` | 手动解析 dict（`_extract_event_data`），自行处理 `header.source`、`payload.data` 等字段，完全绕过 AMP dataclass | AMP 数据类形同虚设，字段路径分散在两处 |
| `nodes/agents/internalizer.py` | 直接操作 `data["envelope"]` / `data["payload"]` dict，自行提取字段 | 同上 |
| `nodes/agents/externalizer.py` | 直接操作 dict，完全不走 AMP | 同上 |

### 问题分析

1. **AMP 数据类被架空**：`build_event_envelope` / `parse_amp_envelope` 只在 `event_bridge.py` 中作为"入口处打包"使用，一旦文件落盘后，后续所有节点（Preprocessor、Internalizer、Externalizer）全部绕过 AMP，直接裸操作 dict。

2. **字段路径分散**：`message_preprocessor._extract_event_data()` 中的字段提取逻辑（`header["source"]["app"]`、`payload["data"]` 等）实际上在重复实现 `parse_amp_envelope` 的功能。如果 AMP 格式演进，需要同时改两处。

3. **类型安全缺失**：直接操作 dict 没有类型检查，字段拼写错误只能在运行时发现。

### 建议

两条路选一：

**方案 A：AMP 全链路贯通**（推荐）
- 所有节点统一使用 `parse_amp_envelope(data)` 将文件内容反序列化为 `AMPEnvelope`
- 字段访问走 `envelope.header.source.app` 而非 `data["header"]["source"]["app"]`
- `build_event_envelope` 统一构建输出

**方案 B：简化 AMP 为纯工具函数**
- 删除 `AMPHeader` / `AMPPayload` / `AMPEnvelope` 数据类
- 保留 `build_event_envelope` 和 `parse_amp_envelope` 但改为直接操作 dict
- 减少抽象层次，降低认知负担

考虑到 kernel/nodes 即将重写，方案 A 更适合作为重写时的约束条件。

---

## 二、代理单例模式不统一

### 现状

项目中两个核心模块使用了相同的"懒加载代理 + 模块单例"模式，但实现不同：

#### `src/memory/__init__.py`

```python
class _MemoryManagerProxy:
    """兼容旧调用方式的懒加载代理。"""
    def __getattr__(self, name: str) -> Any:
        return getattr(get_memory_manager(), name)

memory_manager = _MemoryManagerProxy()
```

#### `src/ai/gateway.py`

```python
class _GatewayProxy:
    """兼容旧调用方式的懒加载代理。"""
    def __getattr__(self, name: str) -> Any:
        return getattr(get_gateway(), name)

gateway = _GatewayProxy()
```

### 差异对比

| 维度 | `_MemoryManagerProxy` | `_GatewayProxy` |
|------|-----------------------|------------------|
| 委托目标 | `get_memory_manager()` | `get_gateway()` |
| `__getattr__` 逻辑 | 完全一致 | 完全一致 |
| 单例管理 | `_memory_manager_singleton` + `get_memory_manager()` | `_singleton` + `get_gateway()` |
| 公开别名 | `memory_manager` | `gateway` |
| 文档 | 有 docstring | 有 docstring |

两者的代理逻辑和单例管理模式**完全相同**，但没有提取公共抽象。

### 问题分析

1. **代码重复**：两个 `__getattr__` 实现一字不差
2. **新增模块成本**：如果后续有第三个需要懒加载单例的模块（如 `SandboxManager`），需要再抄一遍
3. **行为一致性风险**：如果一方修改了 `__getattr__` 的行为（如加缓存、加日志），另一方不会同步

### 建议

提取通用基类：

```python
# src/utils/proxy.py
from __future__ import annotations
from typing import Any

class LazySingletonProxy:
    """懒加载单例代理基类。

    用法::

        _proxy = LazySingletonProxy(get_foo)
        foo = _proxy  # 所有属性访问委托给 get_foo()
    """

    def __init__(self, factory):
        object.__setattr__(self, "_factory", factory)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._factory(), name)
```

然后两个模块改为：

```python
# src/memory/__init__.py
from src.utils.proxy import LazySingletonProxy
memory_manager = LazySingletonProxy(get_memory_manager)

# src/ai/gateway.py
from src.utils.proxy import LazySingletonProxy
gateway = LazySingletonProxy(get_gateway)
```

---

## 影响范围

两个问题都仅限于 `src/platform/amp.py`、`src/nodes/`、`src/memory/__init__.py`、`src/ai/gateway.py`，
不涉及 kernel 核心抽象（base.py / circuit.py / event_bus.py），因此不受 kernel/nodes 重构影响，
可以独立修复。

- **AMP 不一致**：修复时机建议在 kernel/nodes 重写时一并处理，因为重写必然涉及 Internalizer / Externalizer / Preprocessor
- **代理单例**：可以随时修复，风险极低，改动量小
