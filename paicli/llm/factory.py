"""LLM 客户端工厂 - 从环境变量读取模型配置"""

import os
import logging
from typing import Optional

from ..config import pai_config
from .base import LlmClient
from .openai_compatible import OpenAiCompatibleClient
from .ollama_client import OllamaClient

logger = logging.getLogger(__name__)

# 默认模型映射
_DEFAULT_MODELS = {
    "glm": "glm-5.1",
    "deepseek": "deepseek-chat",
    "ollama": "qwen2.5:7b",
}

# base_url 映射
_DEFAULT_URLS = {
    "glm": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
    "deepseek": "https://api.deepseek.com/chat/completions",
    "ollama": "http://localhost:11434",
}

# env key 映射
_ENV_KEYS = {
    "glm": ("GLM_API_KEY", "GLM_MODEL", "GLM_BASE_URL"),
    "deepseek": ("DEEPSEEK_API_KEY", "DEEPSEEK_MODEL", "DEEPSEEK_BASE_URL"),
    "ollama": (None, "OLLAMA_MODEL", "OLLAMA_BASE_URL"),
}


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip() or default


def create(provider: str, model_name: Optional[str] = None) -> Optional[LlmClient]:
    """根据 provider 名称创建 LLM 客户端，所有配置从环境变量读取"""
    provider = provider.lower().strip()
    keys = _ENV_KEYS.get(provider)
    if keys is None:
        logger.warning("Unknown provider: %s", provider)
        return None

    api_key_key, model_key, url_key = keys

    # 模型名：优先参数 > env > 默认值
    model = model_name or _env(model_key) if model_key else ""
    if not model:
        model = _DEFAULT_MODELS.get(provider, "")

    # base_url：优先 env > 默认值
    base_url = _env(url_key) if url_key else ""
    if not base_url:
        base_url = _DEFAULT_URLS.get(provider, "")

    if provider == "ollama":
        return OllamaClient(model=model, base_url=base_url)

    # OpenAI 兼容：需要 api_key
    api_key = _env(api_key_key) if api_key_key else ""
    if not api_key:
        logger.warning("No API key for %s (env: %s)", provider, api_key_key)
        return None

    return OpenAiCompatibleClient(
        api_key=api_key, model=model,
        base_url=base_url, provider_name=provider,
    )


def create_from_config() -> Optional[LlmClient]:
    """依次尝试 default_provider → glm → deepseek → ollama"""
    # 先试默认 provider
    default = pai_config.default_provider_name
    if default:
        client = create(default)
        if client is not None:
            return client

    # 回退遍历
    for provider in ("glm", "deepseek", "ollama"):
        client = create(provider)
        if client is not None:
            return client

    return None
