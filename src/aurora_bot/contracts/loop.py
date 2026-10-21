"""ReAct 循环的四个操作：一次认知运行的全部扩展面。

循环的每一步都是这四个操作之一——观察世界（Observe）、回忆过往（Recall）、
把效果写回世界（Effect）、调用工具（Act）。每个操作绑定一个契约端口，
所以内核本来就能替换它们：机制（怎么读、怎么写、怎么路由）在代码里，
策略（该不该做、做哪一步）在模型里。

**替换的是机制的实现，不是循环的形状。** 四个操作缺一个就不是循环，
所以 ``aurora_bot.runtime.assembly`` 在装配后校验它们齐备；而 Observe 与 Effect
必须落在**同一个世界对象**上——Bot 不能经历一个自己写不进去的世界。

这里只声明，不构造也不校验：契约层是叶子，校验需要装配结果。
LOOP_OPERATIONS 按观察、回忆、记录效果、行动的顺序列出操作。
"""

from __future__ import annotations

from dataclasses import dataclass

from aurora_bot.contracts.pkgs.memory import MemoryReader
from aurora_bot.contracts.pkgs.tools import ToolRegistry
from aurora_bot.contracts.pkgs.world import WorldJournal, WorldReader, WorldWriter


@dataclass(frozen=True, slots=True)
class LoopOperation:
    """循环里的一个操作：绑定的契约、负责什么、必须守住什么。"""

    name: str
    capability: type
    responsibility: str
    invariants: tuple[str, ...]


OBSERVE = LoopOperation(
    name="observe",
    capability=WorldReader,
    responsibility="读取世界线已经披露的增量与提交正文",
    invariants=(
        "delta 从给定 frontier 出发，返回的 end 不得后退",
        "只交付索引与正文，不替 Bot 按语义筛选消息",
    ),
)

RECALL = LoopOperation(
    name="recall",
    capability=MemoryReader,
    responsibility="按冻结的获知边界召回相关经历与任务恢复状态，形成显式上下文输入",
    invariants=(
        "只读：不写世界线，也不保存另一套认知运行状态",
        "运行域（kind=run）默认不进入快照",
    ),
)

EFFECT = LoopOperation(
    name="effect",
    capability=WorldWriter,
    responsibility="把效果与环境事件追加进世界线，并分配单调序号",
    invariants=(
        "commit_id 幂等：同一个 id 重复追加不产生第二条事实",
        "域由提交方给出；world 只校验、编号、追加，不产生事件",
    ),
)

ACT = LoopOperation(
    name="act",
    capability=ToolRegistry,
    responsibility="把模型的工具调用路由到注册表里的实现",
    invariants=(
        "只有已注册且对该节点可见的工具可被调用",
        "delegate 是唯一由 engine 解释的内建 Tool，其余都经端口执行",
    ),
)

LOOP_OPERATIONS = (OBSERVE, RECALL, EFFECT, ACT)

WORLD_PORTS = (WorldReader, WorldWriter, WorldJournal)

__all__ = [
    "ACT",
    "EFFECT",
    "LOOP_OPERATIONS",
    "OBSERVE",
    "RECALL",
    "WORLD_PORTS",
    "LoopOperation",
]
