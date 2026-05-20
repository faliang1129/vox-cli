"""命令快速拒绝：在命令执行前的黑名单 fast-fail"""

import re
from typing import Optional

_RULES: list[tuple[str, re.Pattern]] = [
    ("禁止 sudo 提权", re.compile(r"(?i)\bsudo\b")),
    (
        "禁止 rm -rf 删除全盘或用户目录",
        re.compile(
            r"(?i)\brm\s+-[a-z]*r[a-z]*f[a-z]*\s+(/|~|\$home)|"
            r"\brm\s+-[a-z]*f[a-z]*r[a-z]*\s+(/|~|\$home)"
        ),
    ),
    ("禁止 mkfs 格式化磁盘", re.compile(r"(?i)\bmkfs(\.|\b)")),
    ("禁止 dd 写入裸设备", re.compile(r"(?i)\bdd\b[^\n]*\bof=/dev/")),
    ("识别为 fork bomb", re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:")),
    ("禁止 curl / wget 管道直接执行远端脚本", re.compile(r"(?i)\b(curl|wget)\b[^|\n]*\|\s*(sh|bash|zsh|fish|ksh)\b")),
    ("不允许扫描 /、~ 或整个文件系统", re.compile(r"(?i)\bfind\s+(/|~|\$home)")),
    ("禁止 chmod 777 全盘", re.compile(r"(?i)\bchmod\s+-R\s+777\s+(/|~)")),
    ("禁止 shutdown / reboot / halt", re.compile(r"(?i)\b(shutdown|reboot|halt|poweroff)\b")),
]


class CommandGuard:
    @staticmethod
    def check(command: str) -> Optional[str]:
        if not command or not command.strip():
            return None
        normalized = re.sub(r"\s+", " ", command.strip())
        for reason, pattern in _RULES:
            if pattern.search(normalized):
                return reason
        return None
