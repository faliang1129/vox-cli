"""代码关系 - 代码块之间的调用/引用关系"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class CodeRelation:
    source_file: str
    target_file: str
    relation_type: str  # import, call, extend, implement, reference
    source_chunk_id: Optional[str] = None
    target_chunk_id: Optional[str] = None
    metadata: dict = field(default_factory=dict)
