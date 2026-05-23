"""终端 ANSI 样式辅助 - 支持 Claude Code 风格动画显示"""

import os
import sys


def _color_enabled() -> bool:
    prop = os.environ.get("VOX_CODE_RENDER_COLOR", "")
    if prop:
        return prop.lower() in ("true", "1", "yes")
    if os.environ.get("NO_COLOR"):
        return False
    term = os.environ.get("TERM", "")
    return term.lower() != "dumb" and sys.stdout.isatty()


_ENABLED = _color_enabled()


def _wrap(prefix: str, text: str) -> str:
    if not _ENABLED or not text:
        return text or ""
    return f"{prefix}{text}\033[0m"


def heading(text: str) -> str:
    """亮青色粗体 - 用于主标题"""
    return _wrap("\033[1m\033[36m", text)


def section(text: str) -> str:
    """绿色粗体 - 用于段落标题"""
    return _wrap("\033[1m\033[32m", text)


def subtle(text: str) -> str:
    """灰色细体 - 用于辅助信息"""
    return _wrap("\033[2m\033[90m", text)


def dim(text: str) -> str:
    """暗色细体 - 用于状态指示"""
    return _wrap("\033[2m", text)


def code_label(text: str) -> str:
    """黄色粗体 - 用于代码标签"""
    return _wrap("\033[1m\033[33m", text)


def quote_prefix(text: str) -> str:
    """暗青色 - 用于引用"""
    return _wrap("\033[2m\033[36m", text)


def emphasis(text: str) -> str:
    """白色粗体 - 用于强调"""
    return _wrap("\033[1m", text)


def success(text: str) -> str:
    """绿色 - 用于成功/完成状态"""
    return _wrap("\033[32m", text)


def error(text: str) -> str:
    """红色 - 用于错误状态"""
    return _wrap("\033[31m", text)


def warning(text: str) -> str:
    """黄色 - 用于警告"""
    return _wrap("\033[33m", text)


def info(text: str) -> str:
    """蓝色 - 用于信息"""
    return _wrap("\033[34m", text)


def is_enabled() -> bool:
    return _ENABLED
