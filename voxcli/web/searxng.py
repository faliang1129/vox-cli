"""SearXNG 搜索提供者（自托管）"""

import json
import logging
from typing import List, Optional

import httpx

from .result import SearchResult
from .base import SearchProvider

logger = logging.getLogger(__name__)


class SearxngSearchProvider:
    def __init__(self, base_url: str = "http://localhost:8888"):
        self._base_url = base_url.rstrip("/")

    @property
    def name(self) -> str:
        return "SearXNG"

    def search(self, query: str, top_k: int = 5) -> List[SearchResult]:
        response = httpx.get(
            f"{self._base_url}/search",
            params={"q": query, "format": "json", "language": "zh-CN", "categories": "general"},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        return self._parse_results(data, top_k)

    def is_ready(self) -> bool:
        try:
            httpx.get(f"{self._base_url}/health", timeout=5).raise_for_status()
            return True
        except Exception:
            return False

    def unavailable_hint(self) -> str:
        return f"SearXNG 无法连接（{self._base_url}），请确保服务已启动"

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
