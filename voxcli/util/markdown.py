"""终端 Markdown 渲染器 - 将 Markdown 文本流式渲染到终端"""

import re
import sys
from typing import Optional, TextIO

from .ansi import heading, section, subtle, quote_prefix, emphasis, code_label


class TerminalMarkdownRenderer:
    def __init__(self, stream: Optional[TextIO] = None):
        self._stream = stream or sys.stdout
        self._buffer = ""
        self._in_code_block = False
        self._in_blockquote = False
        self._list_level = 0

    def append(self, text: str):
        self._buffer += text
        self._flush()

    def finish(self):
        if self._buffer.strip():
            self._render(self._buffer)
            self._buffer = ""

    def _flush(self):
        while "\n" in self._buffer:
            idx = self._buffer.index("\n")
            line = self._buffer[:idx]
            self._buffer = self._buffer[idx + 1:]
            self._render(line)
        if len(self._buffer) > 200:
            self._render(self._buffer)
            self._buffer = ""

    def _render(self, line: str):
        stripped = line.strip()

        if stripped.startswith("```"):
            self._in_code_block = not self._in_code_block
            if self._in_code_block:
                self._write(code_label(stripped[3:] or "code"))
            return

        if self._in_code_block:
            self._write(f"  {line}")
            return

        if stripped.startswith("> "):
            self._write(quote_prefix(stripped))
            return

        if stripped.startswith("# "):
            self._write(heading(stripped[2:]))
            return

        if stripped.startswith("## "):
            self._write(section(stripped[3:]))
            return

        if stripped.startswith("### "):
            self._write(f"\033[1;36m{stripped[4:]}\033[0m")
            return

        if stripped.startswith("- ") or stripped.startswith("* "):
            self._write(f"  • {stripped[2:]}")
            return

        if re.match(r"^\d+\. ", stripped):
            self._write(f"  {stripped}")
            return

        if stripped.startswith("---") or stripped.startswith("***"):
            self._write(subtle("─" * 40))
            return

        if stripped == "":
            self._write("")
            return

        rendered = self._render_inline(stripped)
        self._write(rendered)

    @staticmethod
    def _render_inline(text: str) -> str:
        text = re.sub(
            r"\[([^\]]+)\]\(([^)]+)\)",
            lambda m: f"{emphasis(m.group(1))} ({subtle(m.group(2))})",
            text,
        )
        text = re.sub(r"`([^`]+)`", lambda m: code_label(m.group(1)), text)
        text = re.sub(r"\*\*([^*]+)\*\*", lambda m: emphasis(m.group(1)), text)
        text = re.sub(r"\*([^*]+)\*", lambda m: f"\033[3m{m.group(1)}\033[0m", text)
        return text

    def _write(self, text: str):
        print(text, file=self._stream)
