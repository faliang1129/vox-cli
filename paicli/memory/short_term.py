"""短期记忆 - 管理当前对话上下文"""

from collections import OrderedDict
from typing import List, Optional

from .base import Memory
from .entry import MemoryEntry
from .tokenizer import matches, tokenize


class ConversationMemory(Memory):
    def __init__(self, max_tokens: int = 32768):
        self._entries: OrderedDict[str, MemoryEntry] = OrderedDict()
        self._max_tokens = max_tokens
        self._current_tokens = 0
        self._compressed_summaries: List[MemoryEntry] = []

    def store(self, entry: MemoryEntry):
        self._entries[entry.id] = entry
        self._current_tokens += entry.token_count
        while self._current_tokens > self._max_tokens and len(self._entries) > 1:
            self._evict_oldest()

    def retrieve(self, id: str) -> Optional[MemoryEntry]:
        return self._entries.get(id)

    def search(self, query: str, limit: int) -> List[MemoryEntry]:
        query_tokens = tokenize(query)
        results = []
        for entry in self._entries.values():
            if matches(entry.content, query_tokens):
                results.append(entry)
                if len(results) >= limit:
                    break
        return results

    def get_all(self) -> List[MemoryEntry]:
        return list(self._entries.values())

    def delete(self, id: str) -> bool:
        entry = self._entries.pop(id, None)
        if entry:
            self._current_tokens -= entry.token_count
            return True
        return False

    def clear(self):
        self._entries.clear()
        self._current_tokens = 0
        self._compressed_summaries.clear()

    def token_count(self) -> int:
        return self._current_tokens

    def size(self) -> int:
        return len(self._entries)

    @property
    def max_tokens(self) -> int:
        return self._max_tokens

    def get_compressed_summaries(self) -> List[MemoryEntry]:
        return list(self._compressed_summaries)

    def inject_summary(self, summary: MemoryEntry):
        self._compressed_summaries.clear()
        self._entries[summary.id] = summary
        self._current_tokens += summary.token_count

    @property
    def usage_ratio(self) -> float:
        return self._current_tokens / self._max_tokens if self._max_tokens > 0 else 0.0

    def status_summary(self) -> str:
        return (f"短期记忆: {self.size()}条 / {self._current_tokens} tokens "
                f"(预算: {self._max_tokens}, 使用率: {self.usage_ratio * 100:.0f}%, "
                f"已压缩: {len(self._compressed_summaries)}条)")

    def _evict_oldest(self):
        if not self._entries:
            return
        _id, entry = self._entries.popitem(last=False)
        self._current_tokens -= entry.token_count
        self._compressed_summaries.append(entry)
