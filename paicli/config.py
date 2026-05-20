"""配置管理"""

import json
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


def _load_dotenv_files():
    """加载 .env 文件（当前目录和家目录）"""
    for env_file in [Path.cwd() / ".env", Path.home() / ".env"]:
        if env_file.exists():
            load_dotenv(env_file, override=False)


_load_dotenv_files()


class ProviderConfig:
    def __init__(self, api_key: str = "", base_url: str = "", model: str = ""):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model

    def to_dict(self) -> dict:
        return {"apiKey": self.api_key, "baseUrl": self.base_url, "model": self.model}

    @classmethod
    def from_dict(cls, data: dict) -> "ProviderConfig":
        return cls(
            api_key=data.get("apiKey", ""),
            base_url=data.get("baseUrl", ""),
            model=data.get("model", ""),
        )

    def get(self, key: str, default: str = "") -> str:
        mapping = {"api_key": self.api_key, "base_url": self.base_url, "model": self.model}
        return mapping.get(key, default)


class VoxCodeConfig:
    CONFIG_DIR = Path.home() / ".vox-code"
    CONFIG_FILE = CONFIG_DIR / "config.json"

    def __init__(self):
        self.default_provider: str = "glm"
        self.providers: dict[str, ProviderConfig] = {}

    # ---- env key mapping ----
    _PROVIDER_ENV_KEYS = {
        "glm": ("GLM_API_KEY", "GLM_MODEL", "GLM_BASE_URL"),
        "deepseek": ("DEEPSEEK_API_KEY", "DEEPSEEK_MODEL", "DEEPSEEK_BASE_URL"),
        "ollama": ("", "OLLAMA_MODEL", "OLLAMA_BASE_URL"),
    }

    def get_api_key(self, provider: str) -> Optional[str]:
        provider = provider.lower()
        pc = self.providers.get(provider)
        if pc and pc.api_key:
            return pc.api_key
        keys = self._PROVIDER_ENV_KEYS.get(provider)
        if keys and keys[0]:
            return self._read_env(keys[0])
        return ""

    def get_model(self, provider: str) -> Optional[str]:
        provider = provider.lower()
        pc = self.providers.get(provider)
        if pc and pc.model:
            return pc.model
        keys = self._PROVIDER_ENV_KEYS.get(provider)
        if keys and keys[1]:
            return self._read_env(keys[1])
        return None

    def get_base_url(self, provider: str) -> Optional[str]:
        provider = provider.lower()
        pc = self.providers.get(provider)
        if pc and pc.base_url:
            return pc.base_url
        keys = self._PROVIDER_ENV_KEYS.get(provider)
        if keys and keys[2]:
            return self._read_env(keys[2])
        return None

    @staticmethod
    def _read_env(key: str) -> Optional[str]:
        val = os.environ.get(key)
        if val and val.strip():
            return val.strip()
        return None

    @classmethod
    def load(cls) -> "VoxCodeConfig":
        if cls.CONFIG_FILE.exists():
            try:
                data = json.loads(cls.CONFIG_FILE.read_text(encoding="utf-8"))
                cfg = cls()
                cfg.default_provider = data.get("defaultProvider", "glm")
                for name, pc_data in data.get("providers", {}).items():
                    cfg.providers[name] = ProviderConfig.from_dict(pc_data)
                return cfg
            except Exception as e:
                print(f"⚠️ 配置文件读取失败: {e}")
        return cls()

    def save(self):
        self.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "defaultProvider": self.default_provider,
            "providers": {k: v.to_dict() for k, v in self.providers.items()},
        }
        self.CONFIG_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def get_provider(self, name: str) -> Optional["ProviderConfig"]:
        """获取 provider 配置，兼容 dict 和 ProviderConfig 两种用法"""
        name = name.lower()
        pc = self.providers.get(name)
        if pc and pc.api_key and pc.model:
            return pc
        # Fall through to env-based config
        keys = self._PROVIDER_ENV_KEYS.get(name)
        if keys is None:
            return None
        api_key = self._read_env(keys[0]) if keys[0] else ""
        model = self._read_env(keys[1]) if keys[1] else None
        base_url = self._read_env(keys[2]) if keys[2] else None
        if model or api_key:
            return ProviderConfig(
                api_key=api_key or "",
                base_url=base_url or "",
                model=model or "",
            )
        return None

    @property
    def default_provider_name(self) -> str:
        env_default = os.environ.get("VOX_CODE_DEFAULT_PROVIDER", "")
        return env_default.strip() or self.default_provider


# 模块级单例
pai_config = VoxCodeConfig.load()
