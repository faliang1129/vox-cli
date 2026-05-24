"""记忆检索器"""

import time
from typing import List

from .entry import MemoryEntry, MemoryType
from .long_term import LongTermMemory
from .short_term import ConversationMemory
from .tokenizer import tokenize


class MemoryRetriever:
    def __init__(self, short_term: ConversationMemory,
                 project_long_term: LongTermMemory,
                 global_long_term: LongTermMemory):
        self._short_term = short_term
        self._project_long_term = project_long_term
        self._global_long_term = global_long_term

    def retrieve(self, query: str, limit: int) -> List[MemoryEntry]:
        scored: list[tuple[MemoryEntry, float, int]] = []
        for entry in self._short_term.get_all():
            score = self._compute_relevance(entry, query)
            if score > 0:
                scored.append((entry, score, 2))
        scored.extend(self._score_long_term(self._project_long_term, query, 2))
        scored.extend(self._score_long_term(self._global_long_term, query, 1))
        scored.sort(key=lambda x: (x[1], x[2]), reverse=True)
        return [e for e, _, _ in scored[:limit]]

    def retrieve_long_term(self, query: str, limit: int) -> List[MemoryEntry]:
        scored = self._score_long_term(self._project_long_term, query, 2)
        scored.extend(self._score_long_term(self._global_long_term, query, 1))
        scored.sort(key=lambda x: (x[1], x[2]), reverse=True)
        return [e for e, _, _ in scored[:limit]]

    def build_context_for_query(self, query: str, max_tokens: int) -> str:
        relevant = self.retrieve_long_term(query, 10)
        if not relevant:
            return ""
        parts = ["## 相关长期记忆\n"]
        used = 0
        for entry in relevant:
            if used + entry.token_count > max_tokens:
                break
            scope = entry.metadata.get("scope", "project")
            parts.append(f"- [{scope}/{entry.type.value}] {entry.content}\n")
            used += entry.token_count
        parts.append("\n")
        return "".join(parts)

    def _score_long_term(self, memory: LongTermMemory,
                         query: str, priority: int) -> list[tuple[MemoryEntry, float, int]]:
        scored: list[tuple[MemoryEntry, float, int]] = []
        for entry in memory.get_all():
            score = self._compute_relevance(entry, query) * 1.2
            if score > 0:
                scored.append((entry, score, priority))
        return scored

    @staticmethod
    def _compute_relevance(entry: MemoryEntry, query: str) -> float:
        content_lower = entry.content.lower()
        query_lower = query.lower()

        if query_lower in content_lower:
            return 1.0

        query_words = tokenize(query_lower)
        if not query_words:
            return 0.0

        matched = sum(1 for w in query_words if w in content_lower)
        if matched == 0:
            return 0.0

        keyword_score = matched / len(query_words)
        age_hours = (time.time() - entry.timestamp) / 3600
        time_decay = max(0.5, 1.0 - age_hours / 24.0)
        return keyword_score * time_decay
