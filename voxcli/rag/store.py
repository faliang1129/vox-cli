"""向量存储 - SQLite + 余弦相似度检索"""

import json
import logging
import math
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .chunk import CodeChunk

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    chunk: CodeChunk
    score: float


class VectorStore:
    def __init__(self, db_path: Optional[str] = None):
        if db_path:
            self._db_path = Path(db_path)
        else:
            mem_dir = Path.home() / ".vox-code" / "memory"
            mem_dir.mkdir(parents=True, exist_ok=True)
            self._db_path = mem_dir / "vector_store.db"
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_db()

    def _init_db(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS chunks (
                id TEXT PRIMARY KEY,
                file_path TEXT NOT NULL,
                content TEXT NOT NULL,
                language TEXT NOT NULL,
                start_line INTEGER NOT NULL,
                end_line INTEGER NOT NULL,
                chunk_type TEXT DEFAULT 'code',
                metadata TEXT DEFAULT '{}',
                embedding TEXT,
                indexed_at REAL NOT NULL
            )
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_chunks_file_path ON chunks(file_path)
        """)
        self._conn.commit()

    def store_chunk(self, chunk: CodeChunk):
        self._conn.execute("""
            INSERT OR REPLACE INTO chunks
            (id, file_path, content, language, start_line, end_line,
             chunk_type, metadata, embedding, indexed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            chunk.id, chunk.file_path, chunk.content, chunk.language,
            chunk.start_line, chunk.end_line, chunk.chunk_type,
            json.dumps(chunk.metadata),
            json.dumps(chunk.embedding) if chunk.embedding else None,
            time.time(),
        ))
        self._conn.commit()

    def store_chunks(self, chunks: List[CodeChunk]):
        for chunk in chunks:
            self.store_chunk(chunk)

    def search_by_embedding(self, query_embedding: List[float], top_k: int = 5) -> List[SearchResult]:
        cursor = self._conn.execute(
            "SELECT id, file_path, content, language, start_line, end_line, "
            "chunk_type, metadata, embedding FROM chunks WHERE embedding IS NOT NULL"
        )
        scored: List[Tuple[float, dict]] = []
        for row in cursor:
            try:
                stored_emb = json.loads(row[8])
                score = self._cosine_similarity(query_embedding, stored_emb)
                scored.append((score, {
                    "id": row[0], "file_path": row[1], "content": row[2],
                    "language": row[3], "start_line": row[4], "end_line": row[5],
                    "chunk_type": row[6], "metadata": json.loads(row[7]),
                }))
            except (json.JSONDecodeError, IndexError):
                continue

        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        for score, data in scored[:top_k]:
            chunk = CodeChunk(**data)
            results.append(SearchResult(chunk=chunk, score=score))
        return results

    def search_by_keyword(self, query: str, top_k: int = 5) -> List[SearchResult]:
        terms = query.lower().split()
        cursor = self._conn.execute(
            "SELECT id, file_path, content, language, start_line, end_line, "
            "chunk_type, metadata FROM chunks"
        )
        scored: List[Tuple[float, dict]] = []
        for row in cursor:
            content_lower = (row[2] or "").lower()
            path_lower = (row[1] or "").lower()
            match_count = sum(1 for t in terms if t in content_lower or t in path_lower)
            if match_count > 0:
                score = match_count / len(terms)
                scored.append((score, {
                    "id": row[0], "file_path": row[1], "content": row[2],
                    "language": row[3], "start_line": row[4], "end_line": row[5],
                    "chunk_type": row[6], "metadata": json.loads(row[7]),
                }))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        for score, data in scored[:top_k]:
            chunk = CodeChunk(**data)
            results.append(SearchResult(chunk=chunk, score=score))
        return results

    def remove_file(self, file_path: str):
        self._conn.execute("DELETE FROM chunks WHERE file_path = ?", (file_path,))
        self._conn.commit()

    def clear(self):
        self._conn.execute("DELETE FROM chunks")
        self._conn.commit()

    @property
    def chunk_count(self) -> int:
        cursor = self._conn.execute("SELECT COUNT(*) FROM chunks")
        return cursor.fetchone()[0]

    @property
    def file_count(self) -> int:
        cursor = self._conn.execute("SELECT COUNT(DISTINCT file_path) FROM chunks")
        return cursor.fetchone()[0]

    def close(self):
        self._conn.close()

    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]) -> float:
        if not a or not b:
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)
