"""RAG 查询分词器 - 简单中文/英文分词"""

import re
from typing import List


class RagQueryTokenizer:
    @staticmethod
    def tokenize(text: str) -> List[str]:
        text = text.lower().strip()
        if not text:
            return []
        tokens = re.findall(r"[\w]+", text)
        return tokens

    @staticmethod
    def tokenize_chinese(text: str) -> List[str]:
        tokens = RagQueryTokenizer.tokenize(text)
        chars = []
        for token in tokens:
            if re.match(r"^[a-zA-Z0-9_]+$", token):
                chars.append(token)
            else:
                for ch in token:
                    chars.append(ch)
        return chars
