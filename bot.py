"""AuroraBot NoneBot 启动入口（可选）。

Core 也可以通过 ``python -m src.aurora.main`` 独立启动。
此入口仅用于需要 NoneBot QQ/OneBot 适配器的场景。
"""

import nonebot
from nonebot.adapters.onebot.v11 import Adapter as ONEBOT_V11

nonebot.init()
driver = nonebot.get_driver()
driver.register_adapter(ONEBOT_V11)
nonebot.load_from_toml("pyproject.toml")

if __name__ == "__main__":
    nonebot.run()
