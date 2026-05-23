"""嵌入客户端 - 使用 Ollama 或 OpenAI 兼容 API 生成文本嵌入"""

import json
import logging
from typing import List, Optional

import httpx

from ..config import pai_config

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "nomic-embed-text"
_DEFAULT_BASE_URL = "http://localhost:11434"


class EmbeddingClient:
    def __init__(self, model: str = _DEFAULT_MODEL, base_url: str = _DEFAULT_BASE_URL,
                 api_key: str = ""):
        self._model = model
        self._base_url = base_url
        self._api_key = api_key

    @classmethod
    def from_env(cls) -> "EmbeddingClient":
        provider = pai_config.get_provider("ollama")
        if provider:
            return cls(
                base_url=provider.get("base_url", _DEFAULT_BASE_URL),
                model=provider.get("model", _DEFAULT_MODEL),
            )
        provider = pai_config.get_provider("glm")
        if provider:
            return cls(
                base_url=provider.get("base_url", "https://open.bigmodel.cn/api/paas/v4"),
                model=provider.get("model", "embedding-2"),
                api_key=provider.get("api_key", ""),
            )
        return cls()

    def embed(self, text: str) -> List[float]:
        if self._base_url.startswith("http://localhost") or "ollama" in self._base_url:
            return self._embed_ollama(text)
        return self._embed_openai(text)

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        return [self.embed(t) for t in texts]

    @property
    def dimension(self) -> int:
        return 768

    def _embed_ollama(self, text: str) -> List[float]:
        response = httpx.post(
            f"{self._base_url}/api/embeddings",
            json={"model": self._model, "prompt": text},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        return data.get("embedding", [])

    def _embed_openai(self, text: str) -> List[float]:
        response = httpx.post(
            f"{self._base_url}/embeddings",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json={"model": self._model, "input": text},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        return data.get("data", [{}])[0].get("embedding", [])
