"""搜索提供者接口"""

from typing import List, Protocol

from .result import SearchResult


class SearchProvider(Protocol):
    @property
    def name(self) -> str:
        ...

    def search(self, query: str, top_k: int) -> List[SearchResult]:
        ...

    def is_ready(self) -> bool:
        ...

    def unavailable_hint(self) -> str:
        ...
