"""OpenAI 兼容 API 客户端（支持 SSE 流式）"""

import base64
import json
import logging
from pathlib import Path
from typing import Optional

import httpx

from ..chat import SUPPORTED_IMAGE_MIME_TYPES
from .base import (
    LlmClient, Message, ChatResponse, ToolCall, ToolDef,
    StreamListener, STREAM_LISTENER_NOOP,
)

logger = logging.getLogger(__name__)


class OpenAiCompatibleClient(LlmClient):
    def __init__(self, api_key: str, model: str, base_url: str, provider_name: str,
                 timeout: float = 300.0):
        self._api_key = api_key
        self._model = model
        self._base_url = base_url
        self._provider_name = provider_name
        self._http = httpx.Client(timeout=httpx.Timeout(timeout, connect=60.0))

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def supports_image_inputs(self) -> bool:
        return True

    def _encode_image_attachment(self, attachment) -> dict:
        file_path = Path(attachment.file_path)
        if attachment.mime_type not in SUPPORTED_IMAGE_MIME_TYPES:
            raise ValueError(
                f"仅支持 png/jpg/jpeg/webp 图片，当前文件不受支持: {attachment.display_name}"
            )
        if not file_path.exists():
            raise FileNotFoundError(f"图片不存在: {file_path}")
        if not file_path.is_file():
            raise ValueError(f"不是有效的图片文件: {file_path}")
        try:
            data = file_path.read_bytes()
        except OSError as exc:
            raise RuntimeError(f"读取图片失败: {attachment.display_name}: {exc}") from exc
        try:
            encoded = base64.b64encode(data).decode("ascii")
        except Exception as exc:
            raise RuntimeError(f"图片编码失败: {attachment.display_name}: {exc}") from exc
        return {
            "type": "image_url",
            "image_url": {
                "url": f"data:{attachment.mime_type};base64,{encoded}",
            },
        }

    def _build_message_content(self, message: Message):
        if not message.attachments:
            return message.content

        blocks: list[dict] = []
        text = message.content or ""
        if text:
            blocks.append({"type": "text", "text": text})
        for attachment in message.attachments:
            blocks.append(self._encode_image_attachment(attachment))
        return blocks

    def _build_request(self, messages: list[Message],
                       tools: Optional[list[ToolDef]] = None) -> dict:
        body = {
            "model": self._model,
            "stream": True,
            "messages": [],
        }
        allow_reasoning_content = self._provider_name not in {"deepseek"}
        for msg in messages:
            m: dict = {"role": msg.role}
            content = self._build_message_content(msg)
            if content is not None:
                m["content"] = content
            if allow_reasoning_content and msg.reasoning_content:
                m["reasoning_content"] = msg.reasoning_content
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
            if msg.role == "assistant" and msg.tool_calls and "content" not in m:
                m["content"] = ""
            if msg.role == "tool" and "content" not in m:
                m["content"] = ""
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

    @staticmethod
    def _merge_tool_calls(acc: dict[int, dict], tool_calls_delta: list[dict]):
        for tc in tool_calls_delta:
            idx = tc.get("index", len(acc))
            if idx not in acc:
                acc[idx] = {"id": "", "name": "", "arguments": ""}
            if tc.get("id"):
                acc[idx]["id"] = tc["id"]
            fn = tc.get("function", {})
            if fn.get("name"):
                acc[idx]["name"] = fn["name"]
            if fn.get("arguments"):
                acc[idx]["arguments"] += fn["arguments"]

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

    def chat(self, messages: list[Message], tools: Optional[list[ToolDef]] = None,
             listener: StreamListener = STREAM_LISTENER_NOOP) -> ChatResponse:
        body = self._build_request(messages, tools)
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }

        def clean(obj):
            if isinstance(obj, str):
                return obj.encode("utf-8", "surrogatepass").decode("utf-8", "ignore")
            elif isinstance(obj, dict):
                return {k: clean(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [clean(i) for i in obj]
            return obj

        body = clean(body)

        json_data = json.dumps(body, ensure_ascii=False).encode("utf-8", "ignore")

        response = self._http.post(
            self._base_url,
            content=json_data,
            headers=headers
        )

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = response.text.strip()
            if detail:
                raise RuntimeError(
                    f"{self._provider_name} 接口报错 {response.status_code}: {detail}"
                ) from exc
            raise

        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls_acc: dict[int, dict] = {}
        input_tokens = output_tokens = 0

        for line in response.iter_lines():
            line = line.strip()
            if not line or not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if not payload or payload == "[DONE]":
                break

            try:
                chunk = json.loads(payload)
            except json.JSONDecodeError:
                continue

            usage = chunk.get("usage")
            if usage:
                input_tokens = usage.get("prompt_tokens", input_tokens)
                output_tokens = usage.get("completion_tokens", output_tokens)

            choices = chunk.get("choices", [])
            if not choices:
                continue
            delta = choices[0].get("delta", {})

            rdelta = delta.get("reasoning_content", "")
            if rdelta:
                reasoning_parts.append(rdelta)
                listener.on_reasoning_delta(rdelta)

            cdelta = delta.get("content", "")
            if cdelta:
                content_parts.append(cdelta)
                listener.on_content_delta(cdelta)

            tool_calls_delta = delta.get("tool_calls")
            if tool_calls_delta:
                self._merge_tool_calls(tool_calls_acc, tool_calls_delta)

        tool_calls = self._build_tool_calls(tool_calls_acc)

        return ChatResponse(
            role="assistant",
            content="".join(content_parts) or None,
            reasoning_content="".join(reasoning_parts) or None,
            tool_calls=tool_calls or None,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
