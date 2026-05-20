"""Ollama 本地模型客户端"""

import json
import logging
from typing import Optional

import httpx

from .base import (
    LlmClient, Message, ChatResponse, ToolCall, ToolDef,
    StreamListener, STREAM_LISTENER_NOOP,
)

logger = logging.getLogger(__name__)


class OllamaClient(LlmClient):
    def __init__(self, model: str, base_url: str = "http://localhost:11434"):
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._http = httpx.Client(timeout=httpx.Timeout(300.0, connect=10.0))

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def provider_name(self) -> str:
        return "ollama"

    def _build_request(self, messages: list[Message],
                       tools: Optional[list[ToolDef]] = None) -> dict:
        body: dict = {
            "model": self._model,
            "stream": True,
            "messages": [],
        }
        for msg in messages:
            m: dict = {"role": msg.role}
            if msg.content is not None:
                m["content"] = msg.content
            if msg.tool_calls:
                m["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in msg.tool_calls
                ]
            if msg.tool_call_id:
                m["tool_call_id"] = msg.tool_call_id
            body["messages"].append(m)
        if tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ]
        return body

    def chat(self, messages: list[Message], tools: Optional[list[ToolDef]] = None,
             listener: StreamListener = STREAM_LISTENER_NOOP) -> ChatResponse:
        body = self._build_request(messages, tools)
        resp = self._http.post(f"{self._base_url}/api/chat", json=body)
        resp.raise_for_status()

        content_parts: list[str] = []
        tool_calls_acc: dict[int, dict] = {}

        for line in resp.iter_lines():
            line = line.strip()
            if not line:
                continue
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError:
                continue

            if chunk.get("done"):
                break

            delta = chunk.get("message", {})
            if delta.get("content"):
                content_parts.append(delta["content"])
                listener.on_content_delta(delta["content"])
            if delta.get("tool_calls"):
                self._merge_ollama_tool_calls(tool_calls_acc, delta["tool_calls"])

        content = "".join(content_parts) or None
        tool_calls = self._build_tool_calls(tool_calls_acc) or None

        return ChatResponse(
            role="assistant",
            content=content,
            tool_calls=tool_calls,
        )

    @staticmethod
    def _merge_ollama_tool_calls(acc: dict[int, dict], tool_calls: list[dict]):
        for tc in tool_calls:
            idx = len(acc)
            if idx not in acc:
                acc[idx] = {"id": f"call_{idx}", "name": "", "arguments": ""}
            fn = tc.get("function", {})
            if fn.get("name"):
                acc[idx]["name"] = fn["name"]
            if fn.get("arguments"):
                acc[idx]["arguments"] = json.dumps(fn["arguments"], ensure_ascii=False)

    @staticmethod
    def _build_tool_calls(acc: dict[int, dict]) -> list[ToolCall]:
        if not acc:
            return []
        result = []
        for idx in sorted(acc.keys()):
            entry = acc[idx]
            if not entry["id"]:
                continue
            result.append(ToolCall(
                id=entry["id"],
                name=entry["name"],
                arguments=entry["arguments"],
            ))
        return result
