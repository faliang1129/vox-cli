"""终端动画效果 - Claude Code 风格的 thinking 动画、打字机效果、工具调用动画"""

import sys
import time
import threading
from typing import Optional, TextIO

from .ansi import dim, subtle, success, is_enabled

# ============================================================
# Thinking 动画
# ============================================================

class ThinkingDots:
    """Claude Code 风格的 thinking 动画 (● ● ●)

    在 LLM 响应等待期间显示脉冲动画，收到首个 delta 后自动停止。
    """

    _FRAMES = ["● ○ ○", "○ ● ○", "○ ○ ●", "○ ● ○"]

    def __init__(self, stream: Optional[TextIO] = None):
        self._stream = stream or sys.stdout
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        if not is_enabled() or not self._stream.isatty():
            self._running = False
            return
        self._running = True
        self._thread = threading.Thread(target=self._animate, daemon=True)
        self._thread.start()

    def _animate(self):
        idx = 0
        while self._running:
            frame = self._FRAMES[idx % len(self._FRAMES)]
            self._stream.write(f"\r{dim(frame)}")
            self._stream.flush()
            time.sleep(0.25)
            idx += 1

    def stop(self):
        if not self._running:
            return
        self._running = False
        if self._thread:
            self._thread.join(0.3)
        self._stream.write("\r\033[K")
        self._stream.flush()


# ============================================================
# 打字机效果 - 流式输出
# ============================================================

class Typewriter:
    """打字机效果 - 流式输出文本。

    模拟 Claude Code 的输出节奏：字符以微节奏流出（非逐字卡顿），
    ANSI 转义序列整体快速写入，仅在可见字符间引入极短间隔。
    非 TTY 环境退化为直接输出。
    """

    def __init__(self, stream: Optional[TextIO] = None, char_delay: float = 0.004):
        self._stream = stream or sys.stdout
        # 仅在 TTY 启用延迟，管道/重定向直接输出
        self._char_delay = char_delay if is_enabled() and self._stream.isatty() else 0.0
        self._in_escape = False

    def write(self, text: str):
        """写出文本，可见字符间插入微延迟，ANSI 序列整体跳过。"""
        if self._char_delay <= 0 or not text:
            self._stream.write(text)
            self._stream.flush()
            return
        buf = []
        for ch in text:
            if ch == "\033":
                self._in_escape = True
                buf.append(ch)
                continue
            if self._in_escape:
                buf.append(ch)
                # ANSI 序列以字母结尾（a-z / A-Z）
                if ch.isalpha():
                    self._in_escape = False
                continue
            buf.append(ch)
            # 累积一段后写出并延迟
            if len(buf) >= 32 or ch == "\n":
                self._stream.write("".join(buf))
                self._stream.flush()
                buf.clear()
            if ch != "\n":
                time.sleep(self._char_delay)
        if buf:
            self._stream.write("".join(buf))
            self._stream.flush()

    def write_fast(self, text: str):
        """快速写出，无需动画（代码块、工具结果等）"""
        self._stream.write(text)
        self._stream.flush()

    def newline(self):
        self._stream.write("\n")
        self._stream.flush()

    def clear_line(self):
        self._stream.write("\r\033[K")
        self._stream.flush()


# ============================================================
# 工具调用动画（流式）
# ============================================================

class ToolCallAnimator:
    """工具调用动画 - 显示工具执行状态

    工具调用使用 ANSI 转义序列实现原地更新：
    1. running() 逐行打印所有工具调用
    2. finish_all() 回退到起始位置，逐行覆写为 ✓ 格式

    示例输出:
       ✓ read_file: /path/to/file
       ✓ execute_command: npm test
    """

    def __init__(self, stream: Optional[TextIO] = None):
        self._stream = stream or sys.stdout
        self._can_animate = is_enabled() and self._stream.isatty()
        self._line_count = 0
        self._entries: list[tuple[str, str]] = []

    def running(self, tool_name: str, detail: str = ""):
        """记录一个正在运行的工具调用（追加一行）"""
        self._entries.append((tool_name, detail))
        msg = f"  > {tool_name}"
        if detail:
            msg += f"  {detail}"
        self._stream.write(f"{subtle(msg)}\n")
        self._stream.flush()
        self._line_count += 1

    def finish_all(self):
        """将所有工具调用标记为已完成（原地更新）"""
        if not self._entries:
            return
        if self._can_animate:
            # 回退到工具调用列表的起始行
            self._stream.write(f"\033[{self._line_count}A")
            self._stream.flush()
            for name, detail in self._entries:
                msg = f"  {name}"
                if detail:
                    msg += f": {detail}"
                self._stream.write(f"{success('  ✓')} {subtle(msg)}\n")
                self._stream.flush()
        else:
            for name, detail in self._entries:
                msg = f"  {name}"
                if detail:
                    msg += f": {detail}"
                self._stream.write(f"{success('  ✓')} {subtle(msg)}\n")
                self._stream.flush()
        self._line_count = 0
        self._entries = []

    def done(self, tool_name: str, detail: str = ""):
        """单工具兼容接口（仍使用 \r，仅用于单个工具场景）"""
        msg = f"  {tool_name}"
        if detail:
            msg += f": {detail}"
        self._stream.write(f"\r{success('  ✓')} {subtle(msg)}\n")
        self._stream.flush()


# ============================================================
# 进度指示器（轻量）
# ============================================================

class ProgressDots:
    """简单的进度点动画 — 用于等待、搜索等短暂操作"""

    def __init__(self, text: str = "", stream: Optional[TextIO] = None):
        self._text = text
        self._stream = stream or sys.stdout
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        if not is_enabled() or not self._stream.isatty():
            self._stream.write(f"{self._text}...\n")
            return
        self._running = True
        self._thread = threading.Thread(target=self._animate, daemon=True)
        self._thread.start()

    def _animate(self):
        idx = 0
        prefix = f"\r{self._text}" if self._text else "\r"
        while self._running:
            dots = "." * ((idx % 3) + 1)
            self._stream.write(f"{prefix}{dots}  ")
            self._stream.flush()
            time.sleep(0.4)
            idx += 1

    def stop(self, final_msg: str = ""):
        self._running = False
        if self._thread:
            self._thread.join(0.3)
        self._stream.write("\r\033[K")
        if final_msg:
            self._stream.write(f"{final_msg}\n")
        self._stream.flush()
