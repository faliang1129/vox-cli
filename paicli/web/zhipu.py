"""智谱搜索提供者 - 使用智谱 API 进行搜索"""

import json
import logging
from typing import List, Optional

import httpx

from .result import SearchResult
from .base import SearchProvider

logger = logging.getLogger(__name__)


class ZhipuSearchProvider:
    def __init__(self, api_key: str = "", base_url: str = "https://open.bigmodel.cn/api/paas/v4"):
        self._api_key = api_key
        self._base_url = base_url

    @property
    def name(self) -> str:
        return "zhipu"

    def search(self, query: str, top_k: int = 5) -> List[SearchResult]:
        if not self._api_key:
            return []
        response = httpx.post(
            f"{self._base_url}/tools/web_search",
            headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
            json={"query": query, "top_k": min(top_k, 10)},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        return self._parse_results(data)

    def is_ready(self) -> bool:
        return bool(self._api_key)

    def unavailable_hint(self) -> str:
        return "智谱搜索需要配置 GLM_API_KEY 环境变量"

    @staticmethod
    def _parse_results(data: dict) -> List[SearchResult]:
        results = []
        items = data.get("results", []) or data.get("data", [])
        for i, item in enumerate(items):
            results.append(SearchResult(
                title=item.get("title", ""),
                url=item.get("url", "") or item.get("link", ""),
                snippet=item.get("snippet", "") or item.get("content", ""),
                position=i + 1,
                source="zhipu",
            ))
        return results
