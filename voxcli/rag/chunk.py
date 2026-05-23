"""代码块数据模型"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class CodeChunk:
    id: str
    file_path: str
    content: str
    language: str
    start_line: int
    end_line: int
    chunk_type: str = "code"  # code, comment, import, class, function
    metadata: dict = field(default_factory=dict)
    embedding: Optional[List[float]] = None
