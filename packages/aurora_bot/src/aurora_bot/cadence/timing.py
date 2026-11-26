"""可注入的时间与随机源；随机数仅控制判断间隔。"""

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from time import monotonic, time


@dataclass(frozen=True)
class CadenceTiming:
    now: Callable[[], float] = time
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    uniform: Callable[[float, float], float] = field(default_factory=lambda: random.Random().uniform)
    monotonic: Callable[[], float] = monotonic
