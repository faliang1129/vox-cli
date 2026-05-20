"""网页抓取结果"""

from dataclasses import dataclass


@dataclass
class FetchResult:
    url: str
    title: str
    markdown: str
    content_length: int
    truncated: bool

    @staticmethod
    def ok(url: str, title: str, markdown: str,
            content_length: int, truncated: bool) -> "FetchResult":
        return FetchResult(url, title, markdown, content_length, truncated)

    @property
    def body_empty(self) -> bool:
        return not self.markdown.strip()

    @property
    def hint(self) -> str:
        if self.body_empty:
            return "正文为空，可能是 SPA 或防爬墙（已知边界，不重试）"
        return ""
