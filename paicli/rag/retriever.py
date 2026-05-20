"""代码检索器 - 混合检索（语义 + 关键词）"""

import logging
from dataclasses import dataclass
from typing import List, Optional

from .embedding import EmbeddingClient
from .store import VectorStore, SearchResult
from .chunker import CodeChunker
from .index import CodeIndex

logger = logging.getLogger(__name__)


@dataclass
class IndexStats:
    chunk_count: int
    file_count: int


class CodeRetriever:
    def __init__(self, project_path: str,
                 vector_store: Optional[VectorStore] = None,
                 embedding_client: Optional[EmbeddingClient] = None):
        self._project_path = project_path
        self._store = vector_store or VectorStore()
        self._embedding = embedding_client or EmbeddingClient.from_env()

    def hybrid_search(self, query: str, top_k: int = 5) -> List[SearchResult]:
        query_embedding = self._embedding.embed(query)
        semantic_results = self._store.search_by_embedding(query_embedding, top_k)
        keyword_results = self._store.search_by_keyword(query, top_k)

        seen = set()
        merged = []

        for r in semantic_results + keyword_results:
            if r.chunk.id not in seen:
                seen.add(r.chunk.id)
                merged.append(r)

        merged.sort(key=lambda x: x.score, reverse=True)
        return merged[:top_k]

    def get_stats(self) -> IndexStats:
        return IndexStats(
            chunk_count=self._store.chunk_count,
            file_count=self._store.file_count,
        )

    def close(self):
        self._store.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
