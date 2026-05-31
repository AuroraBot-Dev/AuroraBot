try:
    import nonebot

    nonebot.get_driver()
except Exception:  # noqa: BLE001
    pass
else:
    from . import main  # noqa: F401
