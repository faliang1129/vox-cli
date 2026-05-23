"""记忆查询关键词分词"""

import re
from typing import Set


def tokenize(text: str) -> Set[str]:
    if not text:
        return set()
    text = text.lower()
    # 按非字母数字字符分割
    tokens = set(re.findall(r'[a-zA-Z0-9一-鿿]+', text))
    # 去掉单字词（无意义）
    return {t for t in tokens if len(t) > 1 if not t.isascii() or len(t) > 2}


def matches(content: str, query_tokens: Set[str]) -> bool:
    if not query_tokens:
        return True
    content_lower = content.lower()
    return any(t in content_lower for t in query_tokens)
