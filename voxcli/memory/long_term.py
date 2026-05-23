"""长期记忆 - 跨对话持久化的关键信息"""

import json
import os
from pathlib import Path
from typing import List, Optional

from .base import Memory
from .entry import MemoryEntry, MemoryType
from .tokenizer import matches, tokenize


_STORAGE_FILE = "long_term_memory.json"


def _storage_dir() -> Path:
    env_dir = os.environ.get("VOX_CODE_MEMORY_DIR", "")
    if env_dir.strip():
        return Path(env_dir.strip())
    return Path.home() / ".vox-code" / "memory"


class LongTermMemory(Memory):
    def __init__(self):
        self._entries: dict[str, MemoryEntry] = {}
        self._token_counter = 0
        self._storage_file = _storage_dir() / _STORAGE_FILE
        self._load_from_disk()

    def store(self, entry: MemoryEntry):
        if any(e.content == entry.content for e in self._entries.values()):
            return
        self._entries[entry.id] = entry
        self._token_counter += entry.token_count
        self._save_to_disk()

    def retrieve(self, id: str) -> Optional[MemoryEntry]:
        return self._entries.get(id)

    def search(self, query: str, limit: int) -> List[MemoryEntry]:
        query_tokens = tokenize(query)
        results = []
        for entry in self._entries.values():
            if matches(entry.content, query_tokens):
                results.append(entry)
            elif any(matches(v, query_tokens) for v in entry.metadata.values()):
                results.append(entry)
            if len(results) >= limit:
                break
        return results

    def get_all(self) -> List[MemoryEntry]:
        return list(self._entries.values())

    def delete(self, id: str) -> bool:
        entry = self._entries.pop(id, None)
        if entry:
            self._token_counter -= entry.token_count
            self._save_to_disk()
            return True
        return False

    def clear(self):
        self._entries.clear()
        self._token_counter = 0
        self._save_to_disk()

    def token_count(self) -> int:
        return self._token_counter

    def size(self) -> int:
        return len(self._entries)

    def get_by_type(self, type_: MemoryType) -> List[MemoryEntry]:
        return [e for e in self._entries.values() if e.type == type_]

    def status_summary(self) -> str:
        type_counts = {}
        for e in self._entries.values():
            type_counts[e.type] = type_counts.get(e.type, 0) + 1
        return (f"长期记忆: {self.size()}条 / {self._token_counter} tokens "
                f"(事实: {type_counts.get(MemoryType.FACT, 0)}, "
                f"摘要: {type_counts.get(MemoryType.SUMMARY, 0)}, "
                f"工具结果: {type_counts.get(MemoryType.TOOL_RESULT, 0)})")

    def _save_to_disk(self):
        try:
            self._storage_file.parent.mkdir(parents=True, exist_ok=True)
            data = [
                {
                    "id": e.id, "content": e.content,
                    "type": e.type.value,
                    "timestamp": e.timestamp,
                    "metadata": e.metadata,
                    "tokenCount": e.token_count,
                }
                for e in self._entries.values()
            ]
            self._storage_file.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as e:
            print(f"⚠️ 长期记忆持久化失败: {e}")

    def _load_from_disk(self):
        if not self._storage_file.exists():
            return
        try:
            data = json.loads(self._storage_file.read_text(encoding="utf-8"))
            for item in data:
                entry = MemoryEntry(
                    id=item["id"],
                    content=item["content"],
                    type=MemoryType(item["type"]),
                    metadata=item.get("metadata", {}),
                    timestamp=item.get("timestamp", 0),
                    token_count=item.get("tokenCount", 0),
                )
                if entry.token_count <= 0:
                    from .entry import estimate_tokens
                    entry.token_count = estimate_tokens(entry.content)
                self._entries[entry.id] = entry
                self._token_counter += entry.token_count
            print(f"📂 加载了 {len(self._entries)} 条长期记忆")
        except Exception as e:
            print(f"⚠️ 加载长期记忆失败: {e}")
