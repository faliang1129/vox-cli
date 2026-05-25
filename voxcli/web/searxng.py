"""SearXNG 搜索提供者（自托管）"""

import logging
from typing import List, Optional
from urllib.parse import urlsplit, urlunsplit

import httpx

from .result import SearchResult
from .base import SearchProvider

logger = logging.getLogger(__name__)


class SearxngSearchProvider:
    def __init__(self, base_url: str = "http://localhost:8888"):
        self._base_url = self._normalize_base_url(base_url)

    @property
    def name(self) -> str:
        return "SearXNG"

    def search(self, query: str, top_k: int = 5) -> List[SearchResult]:
        response = httpx.get(
            self._search_url(),
            params={"q": query, "format": "json", "language": "zh-CN", "categories": "general"},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        return self._parse_results(data, top_k)

    def is_ready(self) -> bool:
        try:
            httpx.get(self._health_url(), timeout=5).raise_for_status()
            return True
        except Exception:
            return False

    def unavailable_hint(self) -> str:
        return f"SearXNG 无法连接（{self._base_url}），请确保服务已启动"

    def _search_url(self) -> str:
        return f"{self._base_url}/search"

    def _health_url(self) -> str:
        return f"{self._base_url}/health"

    @staticmethod
    def _normalize_base_url(base_url: str) -> str:
        raw = (base_url or "").strip().rstrip("/")
        if not raw:
            return "http://localhost:8888"

        parsed = urlsplit(raw)
        path = parsed.path.rstrip("/")
        if path.endswith("/search"):
            path = path[:-len("/search")]
        normalized = urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))
        return normalized.rstrip("/")

    @staticmethod
    def _parse_results(data: dict, top_k: int) -> List[SearchResult]:
        results = []
        items = data.get("results", [])
        for i, item in enumerate(items[:top_k]):
            results.append(SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("content", ""),
                position=i + 1,
                source="searxng",
            ))
        return results
