"""网络策略 - SSRF 防护和速率限制"""

import ipaddress
import time
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse


@dataclass
class NetworkPolicy:
    rate_limit_per_minute: int = 10
    allowed_schemes: tuple = ("http", "https")
    block_private_ip: bool = True

    def __init__(self, rate_per_minute: int = 10):
        self.rate_limit_per_minute = rate_per_minute
        self._call_timestamps: list = []

    def check_url(self, url: str) -> Optional[str]:
        if not url:
            return "URL 为空"
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return f"不支持的协议: {parsed.scheme}"
        return self._check_ip(parsed.hostname) if self.block_private_ip else None

    def _check_ip(self, hostname: Optional[str]) -> Optional[str]:
        if not hostname:
            return "无法解析 hostname"
        if hostname in ("localhost", "127.0.0.1", "::1"):
            return f"禁止访问本地地址: {hostname}"
        try:
            addr = ipaddress.ip_address(hostname)
            if addr.is_private or addr.is_loopback or addr.is_link_local:
                return f"禁止访问内网地址: {hostname}"
        except ValueError:
            pass
        return None

    def acquire(self) -> Optional[str]:
        now = time.time()
        window = 60.0
        self._call_timestamps = [t for t in self._call_timestamps if now - t < window]
        if len(self._call_timestamps) >= self.rate_limit_per_minute:
            return f"请求频率超过限制（{self.rate_limit_per_minute}/分钟）"
        self._call_timestamps.append(now)
        return None
