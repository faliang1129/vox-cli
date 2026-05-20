"""Agent 循环的退出预算 - token/停滞/硬轮数兜底"""

import os
from enum import Enum
from collections import deque
from typing import List, Optional

from ..llm.base import ToolCall


class ExitReason(Enum):
    WITHIN_BUDGET = "WITHIN_BUDGET"
    TOKEN_BUDGET_EXCEEDED = "TOKEN_BUDGET_EXCEEDED"
    STAGNATION_DETECTED = "STAGNATION_DETECTED"
    HARD_ITERATION_LIMIT = "HARD_ITERATION_LIMIT"


_DEFAULT_TOKEN_BUDGET = 300_000
_DEFAULT_STAGNATION_WINDOW = 3
_DEFAULT_HARD_MAX_ITERATIONS = 50


class AgentBudget:
    def __init__(self, token_budget: int = _DEFAULT_TOKEN_BUDGET,
                 stagnation_window: int = _DEFAULT_STAGNATION_WINDOW,
                 hard_max_iterations: int = _DEFAULT_HARD_MAX_ITERATIONS):
        if token_budget <= 0:
            raise ValueError("token_budget must be positive")
        if stagnation_window < 2:
            raise ValueError("stagnation_window must be >= 2")
        if hard_max_iterations <= 0:
            raise ValueError("hard_max_iterations must be positive")

        self._token_budget = token_budget
        self._stagnation_window = stagnation_window
        self._hard_max_iterations = hard_max_iterations
        self._recent_tool_signatures: deque = deque()
        self._iteration = 0
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._stagnant = False

    @classmethod
    def from_env(cls) -> "AgentBudget":
        return cls(
            _read_int_env("VOX_CODE_REACT_TOKEN_BUDGET", _DEFAULT_TOKEN_BUDGET),
            _read_int_env("VOX_CODE_REACT_STAGNATION_WINDOW", _DEFAULT_STAGNATION_WINDOW),
            _read_int_env("VOX_CODE_REACT_HARD_MAX_ITERATIONS", _DEFAULT_HARD_MAX_ITERATIONS),
        )

    def begin_iteration(self) -> int:
        self._iteration += 1
        return self._iteration

    def record_tokens(self, input_tokens: int, output_tokens: int):
        self._total_input_tokens += max(0, input_tokens)
        self._total_output_tokens += max(0, output_tokens)

    def record_tool_calls(self, tool_calls: Optional[List[ToolCall]]):
        if not tool_calls:
            self._recent_tool_signatures.clear()
            return
        sig = self._signature(tool_calls)
        self._recent_tool_signatures.append(sig)
        while len(self._recent_tool_signatures) > self._stagnation_window:
            self._recent_tool_signatures.popleft()
        if len(self._recent_tool_signatures) == self._stagnation_window:
            first = self._recent_tool_signatures[0]
            self._stagnant = all(s == first for s in self._recent_tool_signatures)

    def check(self) -> ExitReason:
        if self._stagnant:
            return ExitReason.STAGNATION_DETECTED
        if self._total_input_tokens + self._total_output_tokens >= self._token_budget:
            return ExitReason.TOKEN_BUDGET_EXCEEDED
        if self._iteration >= self._hard_max_iterations:
            return ExitReason.HARD_ITERATION_LIMIT
        return ExitReason.WITHIN_BUDGET

    @property
    def iteration(self) -> int:
        return self._iteration

    @property
    def total_input_tokens(self) -> int:
        return self._total_input_tokens

    @property
    def total_output_tokens(self) -> int:
        return self._total_output_tokens

    @property
    def token_budget(self) -> int:
        return self._token_budget

    @property
    def hard_max_iterations(self) -> int:
        return self._hard_max_iterations

    @property
    def stagnation_window(self) -> int:
        return self._stagnation_window

    def describe_exit(self, reason: ExitReason) -> str:
        descriptions = {
            ExitReason.WITHIN_BUDGET: "未触发兜底条件",
            ExitReason.TOKEN_BUDGET_EXCEEDED: (
                f"Token 预算已用尽（{self._total_input_tokens + self._total_output_tokens} / "
                f"{self._token_budget}），任务被强制收尾"
            ),
            ExitReason.STAGNATION_DETECTED: (
                f"检测到连续 {self._stagnation_window} 轮重复的工具调用，疑似死循环，已强制收尾"
            ),
            ExitReason.HARD_ITERATION_LIMIT: (
                f"达到硬轮数上限（{self._hard_max_iterations}），已强制收尾"
            ),
        }
        return descriptions.get(reason, "未知原因")

    @staticmethod
    def _signature(tool_calls: List[ToolCall]) -> str:
        return ";".join(f"{tc.name}|{tc.arguments}" for tc in tool_calls)


def _read_int_env(key: str, default: int) -> int:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return default
    try:
        parsed = int(raw)
        return parsed if parsed > 0 else default
    except ValueError:
        return default
