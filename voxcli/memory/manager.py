"""Memory 管理器 - Memory 系统的门面类"""

import uuid
from typing import List, Optional

from ..llm.base import LlmClient
from .entry import MemoryEntry, MemoryType, estimate_tokens
from .short_term import ConversationMemory
from .long_term import LongTermMemory
from .retriever import MemoryRetriever
from .budget import TokenBudget
from .compressor import ContextCompressor


_MAX_TOOL_RESULT_CHARS = 500


class MemoryManager:
    def __init__(self, llm_client: LlmClient,
                 short_term_budget: int = 32768,
                 context_window: int = 200000,
                 long_term: Optional[LongTermMemory] = None):
        self._short_term = ConversationMemory(short_term_budget)
        self._long_term = long_term or LongTermMemory()
        self._compressor = ContextCompressor(llm_client)
        self._retriever = MemoryRetriever(self._short_term, self._long_term)
        self._budget = TokenBudget(context_window)
        self._llm = llm_client

    def set_llm_client(self, llm_client: LlmClient):
        self._llm = llm_client
        self._compressor.set_llm_client(llm_client)

    def add_user_message(self, content: str):
        entry = MemoryEntry(
            id=f"user-{uuid.uuid4().hex[:8]}",
            content=content,
            type=MemoryType.CONVERSATION,
            metadata={"source": "user"},
        )
        self._short_term.store(entry)
        self._compress_if_needed()

    def add_assistant_message(self, content: str):
        entry = MemoryEntry(
            id=f"assistant-{uuid.uuid4().hex[:8]}",
            content=content,
            type=MemoryType.CONVERSATION,
            metadata={"source": "assistant"},
        )
        self._short_term.store(entry)
        self._compress_if_needed()

    def add_tool_result(self, tool_name: str, result: str):
        truncated = result[:_MAX_TOOL_RESULT_CHARS] + "...(已截断)" if len(result) > _MAX_TOOL_RESULT_CHARS else result
        content = f"[{tool_name}] {truncated}"
        entry = MemoryEntry(
            id=f"tool-{uuid.uuid4().hex[:8]}",
            content=content,
            type=MemoryType.TOOL_RESULT,
            metadata={"source": "tool", "toolName": tool_name},
        )
        self._short_term.store(entry)
        self._compress_if_needed()

    def store_fact(self, fact: str):
        entry = MemoryEntry(
            id=f"fact-{uuid.uuid4().hex[:8]}",
            content=fact,
            type=MemoryType.FACT,
            metadata={"source": "fact"},
        )
        self._long_term.store(entry)

    def retrieve_relevant(self, query: str, limit: int) -> List[MemoryEntry]:
        return self._retriever.retrieve(query, limit)

    def build_context_for_query(self, query: str, max_tokens: int) -> str:
        return self._retriever.build_context_for_query(query, max_tokens)

    def record_token_usage(self, input_tokens: int, output_tokens: int):
        self._budget.record_usage(input_tokens, output_tokens)

    def clear_short_term(self):
        self._short_term.clear()

    def clear_long_term(self):
        self._long_term.clear()

    def status_summary(self) -> str:
        return (f"{self._short_term.status_summary()}\n"
                f"{self._long_term.status_summary()}\n"
                f"{self._budget.usage_report}")

    def _compress_if_needed(self):
        if not self._budget.needs_compression(self._short_term):
            return
        print("📦 短期记忆接近预算上限，触发压缩...")
        summary = self._compressor.compress(self._short_term)
        if summary:
            print(f"   压缩完成，摘要: {summary[:100]}...")
