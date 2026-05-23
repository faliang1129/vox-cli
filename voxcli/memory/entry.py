"""记忆条目"""

import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class MemoryType(Enum):
    CONVERSATION = "conversation"
    FACT = "fact"
    SUMMARY = "summary"
    TOOL_RESULT = "tool_result"


@dataclass
class MemoryEntry:
    id: str
    content: str
    type: MemoryType
    metadata: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    token_count: int = 0

    def __post_init__(self):
        if self.token_count <= 0 and self.content:
            self.token_count = estimate_tokens(self.content)


def estimate_tokens(text: Optional[str]) -> int:
    if not text:
        return 0
    chinese = sum(1 for c in text if '一' <= c <= '鿿')
    other = len(text) - chinese
    return math.ceil(chinese / 1.5 + other / 4.0)
