"""搜索提供者工厂 - 根据环境变量创建搜索提供者"""

import os
import logging
from typing import Optional

from ..config import pai_config
from .base import SearchProvider
from .zhipu import ZhipuSearchProvider
from .serpapi import SerpApiSearchProvider
from .searxng import SearxngSearchProvider

logger = logging.getLogger(__name__)

_DEFAULT_SEARCH_PROVIDER = "searxng"
_DEFAULT_SEARXNG_URL = "https://searxng-ygys-production.up.railway.app/search?q=YOUR_QUERY&format=json"


class SearchProviderFactory:
    _instance: Optional[SearchProvider] = None

    @classmethod
    def create(cls) -> SearchProvider:
        if cls._instance is not None:
            return cls._instance

        provider_name = os.environ.get("SEARCH_PROVIDER", _DEFAULT_SEARCH_PROVIDER).lower()
        config = pai_config.get_provider("glm") or pai_config.get_provider("deepseek") or {}

        if provider_name == "zhipu":
            api_key = config.get("api_key", "") if config else ""
            cls._instance = ZhipuSearchProvider(api_key=api_key)
        elif provider_name == "searxng":
            base_url = os.environ.get("SEARXNG_BASE_URL", _DEFAULT_SEARXNG_URL)
            cls._instance = SearxngSearchProvider(base_url=base_url)
        else:
            api_key = os.environ.get("SERPAPI_API_KEY", "")
            cls._instance = SerpApiSearchProvider(api_key=api_key)

        logger.info("Created search provider: %s", cls._instance.name)
        return cls._instance
