"""ops 文本显示宽度工具。"""


def display_width(text: str) -> int:
    """计算字符串的终端显示宽度，CJK 字符算 2 宽，其余算 1。"""
    width = 0
    for char in text:
        cjk = "\u4e00" <= char <= "\u9fff" or "\u3000" <= char <= "\u303f" or "\uff00" <= char <= "\uffef"
        width += 2 if cjk else 1
    return width


def pad(text: str, target: int) -> str:
    """将文本右侧填充空格至目标显示宽度。"""
    return text + " " * (target - display_width(text))
