"""上下文压缩器"""

import logging
import uuid
from typing import List, Optional

from .entry import MemoryEntry, MemoryType, estimate_tokens
from .short_term import ConversationMemory
from .long_term import LongTermMemory
from ..llm.base import LlmClient, Message

logger = logging.getLogger(__name__)

_MAP_PROMPT = """请将以下对话片段压缩成一段简洁的摘要，保留关键信息：
- 用户的需求和意图
- 已执行的操作和结果
- 做出的决策和结论
- 重要的技术细节

对话片段：
%s

请用中文输出摘要，控制在200字以内。"""

_REDUCE_PROMPT = """请将以下多个摘要合并成一个整体摘要，保留所有关键信息。

各片段摘要：
%s

请用中文输出合并摘要，控制在300字以内。"""

_EXTRACT_FACTS_PROMPT = """请从以下对话中提取"跨会话仍然成立、未来复用仍有价值"的稳定事实，格式为每行一条：
- 用户偏好和习惯
- 项目信息（名称、路径、技术栈）
- 重要决策和约定

只保留用户明确说明、或工具/代码库可验证的信息。
绝对不要提取以下内容：
- 当前这一轮让你执行的临时任务、步骤、todo
- 一次性的文件名、目录名、输出要求
- 模型自己的猜测、纠错、提醒、推断
- "用户想要/需要/让我/请你..." 这类请求句

对话内容：
%s

请每行一条事实，不要多余解释。"""

_EPHEMERAL_PREFIXES = ["用户想", "用户要", "用户需要", "用户请求", "帮我", "让我",
                        "新建", "创建", "删除", "修改", "生成", "补充要求", "当前这一轮", "本次任务"]
_SPECULATION_CUES = ["可能", "应该", "猜测", "推测", "笔误", "提醒"]
_DURABLE_HINTS = ["用户偏好", "用户习惯", "喜欢", "倾向", "项目", "仓库", "路径", "技术栈",
                   "版本", "模型", "接口", "配置", "环境变量", "命令", "约定", "规则", "默认"]


class ContextCompressor:
    def __init__(self, llm_client: LlmClient, retain_recent_rounds: int = 3):
        self._llm = llm_client
        self._retain = retain_recent_rounds

    def set_llm_client(self, llm_client: LlmClient):
        self._llm = llm_client

    def compress(self, memory: ConversationMemory) -> Optional[str]:
        all_entries = memory.get_all()
        if len(all_entries) <= self._retain:
            return None

        split = len(all_entries) - self._retain
        old = list(all_entries[:split])
        recent = list(all_entries[split:])

        chunk_summaries = self._map_phase(old)
        if not chunk_summaries:
            return None

        final_summary = (chunk_summaries[0] if len(chunk_summaries) == 1
                         else self._reduce_phase(chunk_summaries))

        memory.clear()
        summary_entry = MemoryEntry(
            id=f"summary-{uuid.uuid4().hex[:8]}",
            content=f"[历史对话摘要] {final_summary}",
            type=MemoryType.SUMMARY,
        )
        memory.store(summary_entry)
        for entry in recent:
            memory.store(entry)

        return final_summary

    def extract_facts(self, entries: List[MemoryEntry],
                      long_term: LongTermMemory,
                      extra_metadata: Optional[dict] = None) -> List[str]:
        if not entries:
            return []

        conversation = "\n".join(
            f"{self._resolve_source(e)}({e.type.value}): {e.content}"
            for e in entries
        )

        try:
            prompt = _EXTRACT_FACTS_PROMPT % conversation
            resp = self._llm.chat([
                Message.system("你是一个信息提取助手，只输出关键事实，不输出其他内容。"),
                Message.user(prompt),
            ])
            facts_text = resp.content or ""

            facts = []
            seen_facts = set()
            for line in facts_text.split("\n"):
                fact = self._normalize_fact(line)
                if self._is_persistent_fact(fact) and fact not in seen_facts:
                    seen_facts.add(fact)
                    facts.append(fact)
                    metadata = {"source": "fact_extractor"}
                    if extra_metadata:
                        metadata.update(extra_metadata)
                    entry = MemoryEntry(
                        id=f"fact-{uuid.uuid4().hex[:8]}",
                        content=fact,
                        type=MemoryType.FACT,
                        metadata=metadata,
                    )
                    long_term.store(entry)
            return facts
        except Exception as e:
            logger.warning("事实提取失败: %s", e)
            return []

    def _map_phase(self, entries: List[MemoryEntry]) -> List[str]:
        summaries = []
        chunk_size = 5
        for i in range(0, len(entries), chunk_size):
            chunk = entries[i:i + chunk_size]
            chunk_text = "\n".join(
                f"{e.type.value}: {e.content}" for e in chunk
            )
            try:
                prompt = _MAP_PROMPT % chunk_text
                resp = self._llm.chat([
                    Message.system("你是一个对话摘要助手。"),
                    Message.user(prompt),
                ])
                summaries.append(resp.content or "")
            except Exception as e:
                logger.warning("摘要生成失败: %s", e)
                summaries.append(f"[压缩] {chunk_text[:200]}")
        return summaries

    def _reduce_phase(self, summaries: List[str]) -> str:
        joined = "\n\n---\n\n".join(summaries)
        try:
            prompt = _REDUCE_PROMPT % joined
            resp = self._llm.chat([
                Message.system("你是一个摘要合并助手。"),
                Message.user(prompt),
            ])
            return resp.content or "；".join(summaries)
        except Exception as e:
            logger.warning("摘要合并失败: %s", e)
            return "；".join(summaries)

    @staticmethod
    def _resolve_source(entry: MemoryEntry) -> str:
        src = entry.metadata.get("source", "")
        if src:
            return src
        if entry.id.startswith("user-"):
            return "user"
        if entry.id.startswith("assistant-"):
            return "assistant"
        if entry.id.startswith("tool-"):
            return "tool"
        return "unknown"

    @staticmethod
    def _normalize_fact(line: str) -> str:
        fact = (line or "").strip()
        if fact.startswith("- "):
            fact = fact[2:]
        elif fact.startswith("• "):
            fact = fact[2:]
        return fact.strip()

    @staticmethod
    def _is_persistent_fact(fact: str) -> bool:
        if not fact or len(fact) <= 5:
            return False
        normalized = fact.lower()
        for p in _EPHEMERAL_PREFIXES:
            if normalized.startswith(p.lower()):
                return False
        for c in _SPECULATION_CUES:
            if c in normalized:
                return False
        if "：" in fact or ":" in fact:
            return True
        for h in _DURABLE_HINTS:
            if h in normalized:
                return True
        return False
