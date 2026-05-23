"""搜索结果"""

from dataclasses import dataclass


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    position: int
    source: str = ""

    def __post_init__(self):
        self._source = self.source

    @property
    def source(self) -> str:
        return self._source

    @source.setter
    def source(self, value: str):
        self._source = value
