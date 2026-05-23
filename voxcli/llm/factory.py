"""LLM 客户端工厂 - 从环境变量读取模型配置"""

import os
import logging
from typing import Optional

from ..config import ProviderConfig, pai_config
from .base import LlmClient
from .openai_compatible import OpenAiCompatibleClient
from .ollama_client import OllamaClient

logger = logging.getLogger(__name__)

# 默认模型映射
_DEFAULT_MODELS = {
    "glm": "glm-5.1",
    "deepseek": "deepseek-chat",
    "ollama": "qwen2.5:7b",
    "codex": "gpt-5-codex",
    "claude-code": "claude-sonnet-4-20250514",
}

# base_url 映射
_DEFAULT_URLS = {
    "glm": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
    "deepseek": "https://api.deepseek.com/chat/completions",
    "ollama": "http://localhost:11434",
    "codex": "",
    "claude-code": "",
}

# env key 映射
_ENV_KEYS = {
    "glm": ("GLM_API_KEY", "GLM_MODEL", "GLM_BASE_URL"),
    "deepseek": ("DEEPSEEK_API_KEY", "DEEPSEEK_MODEL", "DEEPSEEK_BASE_URL"),
    "ollama": (None, "OLLAMA_MODEL", "OLLAMA_BASE_URL"),
    "codex": (None, None, None),
    "claude-code": (None, None, None),
}


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip() or default


def default_model_for(provider: str) -> str:
    return _DEFAULT_MODELS.get(provider.lower().strip(), "")


def _config_value(provider: str, field: str) -> str:
    provider_config = pai_config.providers.get(provider.lower())
    if provider_config is None:
        return ""
    return provider_config.get(field, "")


def _build_client(provider: str, model: str, base_url: str, api_key: str) -> Optional[LlmClient]:
    if provider == "ollama":
        if not model:
            logger.warning("No model for ollama")
            return None
        return OllamaClient(model=model, base_url=base_url or _DEFAULT_URLS["ollama"])

    if not api_key:
        logger.warning("No API key for %s", provider)
        return None

    if not model:
        logger.warning("No model for %s", provider)
        return None

    return OpenAiCompatibleClient(
        api_key=api_key,
        model=model,
        base_url=base_url,
        provider_name=provider,
    )


def create(provider: str, model_name: Optional[str] = None) -> Optional[LlmClient]:
    """根据 provider 名称创建 LLM 客户端，优先读取环境变量，其次读取全局配置。"""
    provider = provider.lower().strip()
    keys = _ENV_KEYS.get(provider)
    if keys is None:
        logger.warning("Unknown provider: %s", provider)
        return None

    api_key_key, model_key, url_key = keys

    # 模型名：优先参数 > env > 全局配置 > 默认值
    model = model_name or (_env(model_key) if model_key else "")
    if not model:
        model = _config_value(provider, "model")
    if not model:
        model = _DEFAULT_MODELS.get(provider, "")

    # base_url：优先 env > 全局配置 > 默认值
    base_url = _env(url_key) if url_key else ""
    if not base_url:
        base_url = _config_value(provider, "base_url")
    if not base_url:
        base_url = _DEFAULT_URLS.get(provider, "")

    # OpenAI 兼容：需要 api_key
    api_key = _env(api_key_key) if api_key_key else ""
    if not api_key:
        api_key = _config_value(provider, "api_key")

    return _build_client(provider, model, base_url, api_key)


def create_from_provider_config(provider: str, config: ProviderConfig) -> Optional[LlmClient]:
    """根据显式 provider 配置创建客户端，不读取全局配置。"""
    normalized = provider.lower().strip()
    if normalized not in _ENV_KEYS:
        logger.warning("Unknown provider: %s", provider)
        return None
    model = config.model.strip() or default_model_for(normalized)
    base_url = config.base_url.strip() or _DEFAULT_URLS.get(normalized, "")
    api_key = config.api_key.strip()
    return _build_client(normalized, model, base_url, api_key)


def create_from_config() -> Optional[LlmClient]:
    """依次尝试 active preset → default provider → common fallbacks."""
    preset = pai_config.get_model_preset(pai_config.active_model_preset)
    if preset is not None:
        client = create(preset.provider, preset.model)
        if client is not None:
            return client

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
