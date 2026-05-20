"""LLM 客户端接口与消息类型"""

from dataclasses import dataclass, field
from typing import Optional, Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str


@dataclass
class ToolDef:
    name: str
    description: str
    parameters: dict


@dataclass
class Message:
    role: str  # system, user, assistant, tool
    content: Optional[str] = None
    reasoning_content: Optional[str] = None
    tool_calls: Optional[list[ToolCall]] = None
    tool_call_id: Optional[str] = None

    @classmethod
    def system(cls, content: str) -> "Message":
        return cls(role="system", content=content)

    @classmethod
    def user(cls, content: str) -> "Message":
        return cls(role="user", content=content)

    @classmethod
    def assistant(cls, content: str = "", reasoning_content: Optional[str] = None,
                  tool_calls: Optional[list[ToolCall]] = None) -> "Message":
        return cls(role="assistant", content=content, reasoning_content=reasoning_content,
                   tool_calls=tool_calls)

    @classmethod
    def tool(cls, tool_call_id: str, content: str) -> "Message":
        return cls(role="tool", content=content, tool_call_id=tool_call_id)


@dataclass
class ChatResponse:
    role: str = "assistant"
    content: Optional[str] = None
    reasoning_content: Optional[str] = None
    tool_calls: Optional[list[ToolCall]] = None
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


class StreamListener(Protocol):
    def on_reasoning_delta(self, delta: str): ...
    def on_content_delta(self, delta: str): ...


class StreamListenerNoOp:
    def on_reasoning_delta(self, delta: str): pass
    def on_content_delta(self, delta: str): pass


STREAM_LISTENER_NOOP = StreamListenerNoOp()


class LlmClient(Protocol):
    def chat(self, messages: list[Message], tools: Optional[list[ToolDef]] = None,
             listener: StreamListener = STREAM_LISTENER_NOOP) -> ChatResponse: ...

    @property
    def model_name(self) -> str: ...

    @property
    def provider_name(self) -> str: ...
