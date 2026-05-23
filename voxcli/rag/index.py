"""代码索引器 - 将项目文件索引到向量存储"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Optional, Set

from .chunk import CodeChunk
from .chunker import CodeChunker
from .embedding import EmbeddingClient
from .store import VectorStore

logger = logging.getLogger(__name__)

_IGNORE_DIRS = {
    ".git", ".svn", "__pycache__", "node_modules", ".mvn", ".gradle",
    "target", "build", "dist", ".idea", ".vscode", ".venv", "venv",
    "env", ".egg-info", "site-packages", ".tox", ".nox",
}

_IGNORE_EXTENSIONS = {
    ".pyc", ".pyo", ".so", ".o", ".class", ".jar", ".war", ".zip",
    ".tar", ".gz", ".7z", ".rar", ".exe", ".dll", ".dylib", ".bin",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp",
    ".mp4", ".mp3", ".wav", ".avi", ".mov", ".pdf", ".doc", ".docx",
    ".xls", ".xlsx", ".ppt", ".pptx", ".ttf", ".woff", ".woff2",
    ".DS_Store", ".gitkeep", ".gitignore",
}

_INCLUDE_EXTENSIONS = {
    ".py", ".java", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".rb",
    ".php", ".c", ".cpp", ".h", ".hpp", ".swift", ".kt", ".scala",
    ".md", ".json", ".yaml", ".yml", ".xml", ".toml", ".sql", ".sh",
    ".bash", ".zsh", ".txt", ".cfg", ".conf", ".ini", ".properties",
}


class CodeIndex:
    def __init__(self, project_path: str,
                 vector_store: Optional[VectorStore] = None,
                 chunker: Optional[CodeChunker] = None,
                 embedding_client: Optional[EmbeddingClient] = None):
        self._project_path = Path(project_path)
        self._store = vector_store or VectorStore()
        self._chunker = chunker or CodeChunker()
        self._embedding = embedding_client or EmbeddingClient()

    def index_project(self, max_workers: int = 4) -> int:
        files = self._discover_files()
        if not files:
            logger.info("No indexable files found in %s", self._project_path)
            return 0

        total_chunks = 0
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(self._index_file, f) for f in files]
            for future in futures:
                try:
                    total_chunks += future.result()
                except Exception as e:
                    logger.warning("Indexing file failed: %s", e)

        logger.info("Indexed %d chunks from %d files", total_chunks, len(files))
        return total_chunks

    def _discover_files(self) -> List[Path]:
        files = []
        for ext in _INCLUDE_EXTENSIONS:
            files.extend(self._project_path.rglob(f"*{ext}"))

        return [
            f for f in files
            if f.is_file()
            and not any(part.startswith(".") or part in _IGNORE_DIRS
                        for part in f.relative_to(self._project_path).parts)
            and f.suffix.lower() not in _IGNORE_EXTENSIONS
        ]

    def _index_file(self, file_path: Path) -> int:
        try:
            # Remove stale entries
            self._store.remove_file(str(file_path))
            chunks = self._chunker.chunk_file(str(file_path))
            if not chunks:
                return 0

            for chunk in chunks:
                embedding = self._embedding.embed(chunk.content)
                chunk.embedding = embedding

            self._store.store_chunks(chunks)
            return len(chunks)
        except Exception as e:
            logger.warning("Failed to index %s: %s", file_path, e)
            return 0
