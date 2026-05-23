"""代码分块器 - 将源代码文件分割为可检索的块"""

import ast
import logging
import re
from pathlib import Path
from typing import List, Optional

from .chunk import CodeChunk

logger = logging.getLogger(__name__)

_LINE_CHUNK_SIZE = 50
_LINE_OVERLAP = 10

_LANGUAGE_MAP = {
    ".py": "python", ".java": "java", ".js": "javascript",
    ".ts": "typescript", ".tsx": "typescriptreact", ".jsx": "javascriptreact",
    ".go": "go", ".rs": "rust", ".rb": "ruby", ".php": "php",
    ".c": "c", ".cpp": "cpp", ".h": "c", ".hpp": "cpp",
    ".swift": "swift", ".kt": "kotlin", ".scala": "scala",
    ".md": "markdown", ".json": "json", ".yaml": "yaml", ".yml": "yaml",
    ".xml": "xml", ".toml": "toml", ".sql": "sql", ".sh": "bash",
    ".zsh": "bash", ".bash": "bash", ".txt": "text",
}


class CodeChunker:
    def __init__(self, line_chunk_size: int = _LINE_CHUNK_SIZE,
                 line_overlap: int = _LINE_OVERLAP):
        self._chunk_size = line_chunk_size
        self._overlap = line_overlap

    def chunk_file(self, file_path: str) -> List[CodeChunk]:
        path = Path(file_path)
        if not path.exists():
            return []
        try:
            content = path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning("Failed to read %s: %s", file_path, e)
            return []

        ext = path.suffix.lower()
        language = _LANGUAGE_MAP.get(ext, "text")
        chunks = []

        if language == "python":
            chunks = self._chunk_python(file_path, content)
        elif language == "java":
            chunks = self._chunk_java(file_path, content)

        if not chunks:
            chunks = self._chunk_by_lines(file_path, content, language)

        return chunks

    def _chunk_python(self, file_path: str, content: str) -> List[CodeChunk]:
        chunks = []
        try:
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    start = node.lineno or 1
                    end = node.end_lineno or start
                    lines = content.split("\n")[start - 1:end]
                    chunk_type = "class" if isinstance(node, ast.ClassDef) else "function"
                    chunks.append(CodeChunk(
                        id=f"{file_path}:{start}-{end}",
                        file_path=file_path,
                        content="\n".join(lines),
                        language="python",
                        start_line=start,
                        end_line=end,
                        chunk_type=chunk_type,
                    ))
        except SyntaxError:
            pass
        return chunks

    def _chunk_java(self, file_path: str, content: str) -> List[CodeChunk]:
        chunks = []
        pattern = re.compile(
            r'(?:public|private|protected)\s+(?:static\s+)?(?:class|interface|enum)\s+(\w+)|'
            r'(?:public|private|protected)\s+(?:static\s+)?\w+\s+(\w+)\s*\([^)]*\)\s*(?:throws\s+\w+)?\s*\{'
        )
        lines = content.split("\n")
        for match in pattern.finditer(content):
            start_line = content[:match.start()].count("\n") + 1
            brace_pos = content.find("{", match.end())
            if brace_pos == -1:
                continue
            end_line = self._find_matching_brace(content, brace_pos, lines)
            chunk_type = "class" if match.group(1) else "function"
            chunk_lines = lines[start_line - 1:end_line]
            chunks.append(CodeChunk(
                id=f"{file_path}:{start_line}-{end_line}",
                file_path=file_path,
                content="\n".join(chunk_lines),
                language="java",
                start_line=start_line,
                end_line=end_line,
                chunk_type=chunk_type,
            ))
        return chunks

    def _chunk_by_lines(self, file_path: str, content: str, language: str) -> List[CodeChunk]:
        lines = content.split("\n")
        chunks = []
        for i in range(0, len(lines), self._chunk_size - self._overlap):
            chunk_lines = lines[i:i + self._chunk_size]
            if not chunk_lines:
                break
            start = i + 1
            end = i + len(chunk_lines)
            chunks.append(CodeChunk(
                id=f"{file_path}:{start}-{end}",
                file_path=file_path,
                content="\n".join(chunk_lines),
                language=language,
                start_line=start,
                end_line=end,
                chunk_type="code",
            ))
        return chunks

    @staticmethod
    def _find_matching_brace(content: str, open_pos: int, lines: List[str]) -> int:
        depth = 1
        pos = open_pos + 1
        while pos < len(content) and depth > 0:
            if content[pos] == "{":
                depth += 1
            elif content[pos] == "}":
                depth -= 1
            pos += 1
        return content[:pos].count("\n") + 1
