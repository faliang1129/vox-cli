"""Memory 管理器 - Memory 系统的门面类"""

from dataclasses import dataclass
from pathlib import Path
import uuid
from typing import List, Optional

from ..config import VoxCodeConfig
from ..llm.base import LlmClient
from .entry import MemoryEntry, MemoryType, estimate_tokens
from .short_term import ConversationMemory
from .long_term import LongTermMemory
from .retriever import MemoryRetriever
from .budget import TokenBudget
from .compressor import ContextCompressor


_MAX_TOOL_RESULT_CHARS = 500


@dataclass(frozen=True)
class SaveResult:
    scope: str
    storage_file: Path
    extracted_count: int
    stored_count: int
    facts: tuple[str, ...]


class MemoryManager:
    def __init__(self, llm_client: LlmClient,
                 short_term_budget: int = 32768,
                 context_window: int = 200000,
                 long_term: Optional[LongTermMemory] = None,
                 project_path: Optional[str] = None,
                 global_config_dir: Optional[str | Path] = None,
                 project_long_term: Optional[LongTermMemory] = None,
                 global_long_term: Optional[LongTermMemory] = None):
        self._short_term = ConversationMemory(short_term_budget)
        self._project_path = self._normalize_project_path(project_path)
        self._project_long_term = project_long_term or long_term or LongTermMemory(
            storage_dir=self._project_memory_dir(self._project_path),
            scope="project",
            default_metadata={"projectPath": self._project_path} if self._project_path else {},
        )
        self._global_long_term = global_long_term or LongTermMemory(
            storage_dir=self._global_memory_dir(global_config_dir),
            scope="global",
        )
        self._compressor = ContextCompressor(llm_client)
        self._retriever = MemoryRetriever(
            self._short_term, self._project_long_term, self._global_long_term
        )
        self._budget = TokenBudget(context_window)
        self._llm = llm_client

    def set_llm_client(self, llm_client: LlmClient):
        self._llm = llm_client
        self._compressor.set_llm_client(llm_client)

    def add_user_message(self, content: str):
        entry = MemoryEntry(
            id=f"user-{uuid.uuid4().hex[:8]}",
            content=content,
            type=MemoryType.CONVERSATION,
            metadata={"source": "user"},
        )
        self._short_term.store(entry)
        self._compress_if_needed()

    def add_assistant_message(self, content: str):
        entry = MemoryEntry(
            id=f"assistant-{uuid.uuid4().hex[:8]}",
            content=content,
            type=MemoryType.CONVERSATION,
            metadata={"source": "assistant"},
        )
        self._short_term.store(entry)
        self._compress_if_needed()

    def add_tool_result(self, tool_name: str, result: str):
        truncated = result[:_MAX_TOOL_RESULT_CHARS] + "...(已截断)" if len(result) > _MAX_TOOL_RESULT_CHARS else result
        content = f"[{tool_name}] {truncated}"
        entry = MemoryEntry(
            id=f"tool-{uuid.uuid4().hex[:8]}",
            content=content,
            type=MemoryType.TOOL_RESULT,
            metadata={"source": "tool", "toolName": tool_name},
        )
        self._short_term.store(entry)
        self._compress_if_needed()

    def store_fact(self, fact: str, scope: str = "project"):
        entry = MemoryEntry(
            id=f"fact-{uuid.uuid4().hex[:8]}",
            content=fact,
            type=MemoryType.FACT,
            metadata={"source": "fact"},
        )
        self._resolve_long_term(scope).store(entry)

    def retrieve_relevant(self, query: str, limit: int) -> List[MemoryEntry]:
        return self._retriever.retrieve(query, limit)

    def build_context_for_query(self, query: str, max_tokens: int) -> str:
        return self._retriever.build_context_for_query(query, max_tokens)

    def save_long_term(self, scope: str = "project") -> SaveResult:
        target = self._resolve_long_term(scope)
        entries = self._short_term.get_all()
        if not entries:
            return SaveResult(target.scope, target.storage_file, 0, 0, ())

        before = target.size()
        facts = self._compressor.extract_facts(
            entries, target, extra_metadata={"savedVia": "manual_save"}
        )
        after = target.size()
        return SaveResult(
            scope=target.scope,
            storage_file=target.storage_file,
            extracted_count=len(facts),
            stored_count=max(after - before, 0),
            facts=tuple(facts),
        )

    def record_token_usage(self, input_tokens: int, output_tokens: int):
        self._budget.record_usage(input_tokens, output_tokens)

    def clear_short_term(self):
        self._short_term.clear()

    def clear_long_term(self):
        self._project_long_term.clear()
        self._global_long_term.clear()

    def status_summary(self) -> str:
        return (f"{self._short_term.status_summary()}\n"
                f"{self._project_long_term.status_summary()}\n"
                f"{self._global_long_term.status_summary()}\n"
                f"{self._budget.usage_report}")

    def _compress_if_needed(self):
        if not self._budget.needs_compression(self._short_term):
            return
        print("📦 短期记忆接近预算上限，触发压缩...")
        summary = self._compressor.compress(self._short_term)
        if summary:
            print(f"   压缩完成，摘要: {summary[:100]}...")

    @staticmethod
    def _normalize_project_path(project_path: Optional[str]) -> str:
        raw = project_path or Path.cwd().as_posix()
        return str(Path(raw).expanduser().resolve())

    @staticmethod
    def _project_memory_dir(project_path: str) -> Path:
        return Path(project_path) / ".vox-code" / "memory"

    @staticmethod
    def _global_memory_dir(global_config_dir: Optional[str | Path]) -> Path:
        base = Path(global_config_dir) if global_config_dir is not None else VoxCodeConfig.config_dir()
        return base / "memory"

    def _resolve_long_term(self, scope: str) -> LongTermMemory:
        normalized = (scope or "project").strip().lower()
        if normalized == "global":
            return self._global_long_term
        return self._project_long_term
