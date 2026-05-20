"""SerpAPI 搜索提供者"""

import json
import logging
from typing import List, Optional

import httpx

from .result import SearchResult
from .base import SearchProvider

logger = logging.getLogger(__name__)


class SerpApiSearchProvider:
    def __init__(self, api_key: str = ""):
        self._api_key = api_key

    @property
    def name(self) -> str:
        return "SerpAPI"

    def search(self, query: str, top_k: int = 5) -> List[SearchResult]:
        if not self._api_key:
            return []
        response = httpx.get(
            "https://serpapi.com/search",
            params={"q": query, "api_key": self._api_key, "engine": "google", "num": min(top_k, 10)},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        return self._parse_results(data)

    def is_ready(self) -> bool:
        return bool(self._api_key)

    def unavailable_hint(self) -> str:
        return "SerpAPI 搜索需要配置 SERPAPI_API_KEY 环境变量"

    @staticmethod
    def _parse_results(data: dict) -> List[SearchResult]:
        results = []
        organic = data.get("organic_results", [])
        for i, item in enumerate(organic[:10]):
            results.append(SearchResult(
                title=item.get("title", ""),
                url=item.get("link", ""),
                snippet=item.get("snippet", ""),
                position=i + 1,
                source="serpapi",
            ))
        return results
