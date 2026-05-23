"""Presentation layer for user-facing reply rendering."""

from dataclasses import dataclass
from enum import Enum
import logging
import re
from typing import Optional, Union

from ..config import pai_config
from ..llm.base import LlmClient, Message

logger = logging.getLogger(__name__)

PRESENTER_GUARD_PROMPT = """你不是任务执行者，你是结果转述者。

你的任务是：基于“原始回复”进行人格化重述，让它更像桌面宠物 Vox 在向主人汇报。

硬规则：
1. 只能基于提供的原始回复重述，不得新增事实、步骤、结论。
2. 不得伪造任何工具调用、文件读取、联网搜索、代码修改行为。
3. 所有代码块、命令、路径、URL、JSON、错误正文必须原样保留。
4. 可以调整语气、顺序和解释方式，但不能改变技术含义。
5. 如果原始回复已经很短，只做轻度自然化改写。
6. 如果原始回复较长，可以“人格化开场 + 专业正文保留”。
7. 默认只输出给主人看的最终回复，不要解释你如何改写。
"""

_STATS_RE = re.compile(r"(?:\n|\A)📊 Token:.*$", re.S)


class PresentationMode(str, Enum):
    WORK = "work"
    PET = "pet"

    @classmethod
    def normalize(cls, value: Optional[str]) -> "PresentationMode":
        if not value:
            return cls.WORK
        normalized = value.strip().lower()
        return cls.PET if normalized == cls.PET.value else cls.WORK

    @classmethod
    def is_valid(cls, value: Optional[str]) -> bool:
        if not value:
            return False
        return value.strip().lower() in {cls.WORK.value, cls.PET.value}


@dataclass
class PresentationResult:
    raw_response: str
    display_response: str
    used_presenter: bool = False


class ResponsePresenter:
    def __init__(self, llm_client: LlmClient):
        self._llm = llm_client

    def present(self, user_input: str, raw_response: str,
                mode: Union[PresentationMode, str]) -> PresentationResult:
        normalized_mode = PresentationMode.normalize(
            mode.value if isinstance(mode, PresentationMode) else mode
        )
        if not raw_response:
            return PresentationResult(raw_response=raw_response, display_response=raw_response)

        if normalized_mode == PresentationMode.WORK:
            return PresentationResult(raw_response=raw_response, display_response=raw_response)

        stats = _extract_stats(raw_response)
        body = _strip_stats(raw_response)
        source = _extract_presentable_body(body)

        if _looks_strictly_structured(source):
            return PresentationResult(raw_response=raw_response, display_response=raw_response)

        prompt = _build_presenter_input(user_input, source)
        persona_prompt = pai_config.get_active_persona_prompt()

        try:
            response = self._llm.chat([
                Message.system(persona_prompt + "\n\n" + PRESENTER_GUARD_PROMPT),
                Message.user(prompt),
            ])
            display = (response.content or "").strip()
            if not display:
                return PresentationResult(raw_response=raw_response, display_response=raw_response)
            if _contains_code_block(source) and not _preserves_code_block(source, display):
                logger.warning("Presenter output dropped code block, falling back to raw response")
                return PresentationResult(raw_response=raw_response, display_response=raw_response)
            final = display if not stats else f"{display}\n\n{stats}"
            return PresentationResult(
                raw_response=raw_response,
                display_response=final,
                used_presenter=True,
            )
        except Exception as e:
            logger.warning("Presenter LLM failed, falling back to raw response: %s", e)
            return PresentationResult(raw_response=raw_response, display_response=raw_response)


def _build_presenter_input(user_input: str, raw_response: str) -> str:
    return (
        "请将下面的原始回复改写成桌面宠物 Vox 对主人的自然汇报。\n\n"
        f"用户原始输入：\n{user_input}\n\n"
        "要求：\n"
        "- 可爱但克制，别太吵\n"
        "- 优先准确，别改事实\n"
        "- 需要保留所有技术正文中的代码、命令、路径、URL、错误、JSON\n"
        "- 不要输出多余解释\n\n"
        f"原始回复：\n{raw_response}"
    )


def _strip_stats(text: str) -> str:
    return _STATS_RE.sub("", text).strip()


def _extract_stats(text: str) -> str:
    match = _STATS_RE.search(text)
    return match.group(0).strip() if match else ""


def _extract_presentable_body(text: str) -> str:
    marker = "\n\n🤖 回复:\n"
    if marker in text:
        return text.split(marker, 1)[1].strip()
    return text.strip()


def _looks_strictly_structured(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if stripped.startswith("{") and stripped.endswith("}"):
        return True
    if stripped.startswith("[") and stripped.endswith("]"):
        return True
    if stripped.startswith("```json") or stripped.startswith("```yaml"):
        return True
    if '"approved"' in stripped and stripped.count("{") >= 1:
        return True
    if '"steps"' in stripped or '"tasks"' in stripped:
        return True
    return False


def _contains_code_block(text: str) -> bool:
    return "```" in text


def _preserves_code_block(source: str, display: str) -> bool:
    return source.count("```") == display.count("```")
