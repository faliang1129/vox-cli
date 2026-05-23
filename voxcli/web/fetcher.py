"""网页抓取器 - 使用 httpx 获取网页内容"""

import logging
from typing import Dict, Optional

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 30
_MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # 5MB


class WebFetcher:
    def __init__(self, timeout: int = _DEFAULT_TIMEOUT):
        self._timeout = timeout

    def fetch(self, url: str) -> Dict[str, str]:
        logger.info("Fetching URL: %s", url)
        response = httpx.get(
            url,
            timeout=self._timeout,
            follow_redirects=True,
            headers={
                "User-Agent": ("Mozilla/5.0 (compatible; VoxCode/1.0; "
                               "+https://github.com/vox-code)"),
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        )
        response.raise_for_status()

        body = response.text
        if len(body) > _MAX_RESPONSE_BYTES:
            body = body[:_MAX_RESPONSE_BYTES]
            logger.warning("Response truncated to %d bytes", _MAX_RESPONSE_BYTES)

        return {
            "url": str(response.url),
            "body": body,
            "content_type": response.headers.get("content-type", ""),
        }
