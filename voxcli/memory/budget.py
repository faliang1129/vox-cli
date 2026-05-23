"""Token 预算管理器"""

from typing import List

from .entry import estimate_tokens
from .short_term import ConversationMemory
from ..llm.base import Message


class TokenBudget:
    def __init__(self, context_window: int = 200000,
                 reserved_for_system: int = 500,
                 reserved_for_tools: int = 800,
                 reserved_for_response: int = 2000):
        self._context_window = context_window
        self._reserved_for_system = reserved_for_system
        self._reserved_for_tools = reserved_for_tools
        self._reserved_for_response = reserved_for_response
        self._total_input = 0
        self._total_output = 0
        self._call_count = 0

    @property
    def available_for_conversation(self) -> int:
        return self._context_window - self._reserved_for_system - self._reserved_for_tools - self._reserved_for_response

    def needs_compression(self, memory: ConversationMemory) -> bool:
        compression_budget = min(memory.max_tokens, self.available_for_conversation)
        return memory.token_count() >= compression_budget * 0.8

    def record_usage(self, input_tokens: int, output_tokens: int):
        self._total_input += input_tokens
        self._total_output += output_tokens
        self._call_count += 1

    @property
    def usage_report(self) -> str:
        avg = self._total_input / self._call_count if self._call_count > 0 else 0
        return (f"Token 统计: 调用 {self._call_count} 次 | "
                f"总输入: {self._total_input} | 总输出: {self._total_output} | "
                f"平均输入: {avg:.0f} | 预算: {self._context_window}")

    @staticmethod
    def estimate_messages_tokens(messages: List[Message]) -> int:
        total = 0
        for msg in messages:
            if msg.content:
                total += estimate_tokens(msg.content)
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    total += estimate_tokens(tc.arguments)
        total += len(messages) * 4
        return total
