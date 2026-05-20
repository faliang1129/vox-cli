"""终端 ANSI 样式辅助"""

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
    return f"{prefix}{text}[0m"


def heading(text: str) -> str:
    return _wrap("[1m[36m", text)


def section(text: str) -> str:
    return _wrap("[1m[32m", text)


def subtle(text: str) -> str:
    return _wrap("[2m[90m", text)


def code_label(text: str) -> str:
    return _wrap("[1m[33m", text)


def quote_prefix(text: str) -> str:
    return _wrap("[2m[36m", text)


def emphasis(text: str) -> str:
    return _wrap("[1m", text)


def is_enabled() -> bool:
    return _ENABLED
