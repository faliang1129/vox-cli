"""Configuration and user-extensible catalog management."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
from typing import Optional

from dotenv import load_dotenv

from .catalog import DEFAULT_CATALOG, load_catalog_from_file, merge_catalog


def _load_dotenv_files():
    """Load .env files from cwd and home without overriding real env vars."""
    for env_file in [Path.cwd() / ".env", Path.home() / ".env"]:
        if env_file.exists():
            load_dotenv(env_file, override=False)


_load_dotenv_files()


@dataclass
class ProviderConfig:
    api_key: str = ""
    base_url: str = ""
    model: str = ""

    def to_dict(self) -> dict:
        return {"apiKey": self.api_key, "baseUrl": self.base_url, "model": self.model}

    @classmethod
    def from_dict(cls, data: dict) -> "ProviderConfig":
        return cls(
            api_key=str(data.get("apiKey", "")),
            base_url=str(data.get("baseUrl", "")),
            model=str(data.get("model", "")),
        )

    def get(self, key: str, default: str = "") -> str:
        mapping = {"api_key": self.api_key, "base_url": self.base_url, "model": self.model}
        return mapping.get(key, default)


@dataclass
class GuiModelConfig:
    enabled: bool = False
    provider: str = "glm"
    model: str = ""
    base_url: str = ""
    api_key: str = ""

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
            "api_key": self.api_key,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GuiModelConfig":
        return cls(
            enabled=bool(data.get("enabled", False)),
            provider=str(data.get("provider", "glm")).strip().lower() or "glm",
            model=str(data.get("model", "")).strip(),
            base_url=str(data.get("base_url", "")).strip(),
            api_key=str(data.get("api_key", "")).strip(),
        )

    def provider_config(self) -> ProviderConfig:
        return ProviderConfig(
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.model,
        )

    def validate(self) -> list[str]:
        issues: list[str] = []
        if not self.provider:
            issues.append("provider")
        if not self.base_url:
            issues.append("base_url")
        if self.provider != "ollama" and not self.api_key:
            issues.append("api_key")
        return issues


@dataclass(frozen=True)
class ModelPreset:
    id: str
    label: str
    provider: str
    model: str
    description: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "ModelPreset":
        return cls(
            id=str(data.get("id", "")).strip(),
            label=str(data.get("label", "")).strip() or str(data.get("id", "")).strip(),
            provider=str(data.get("provider", "")).strip().lower(),
            model=str(data.get("model", "")).strip(),
            description=str(data.get("description", "")).strip(),
        )


class VoxCodeConfig:
    CONFIG_DIR = Path.home() / ".vox-code"
    CONFIG_FILE = CONFIG_DIR / "config.json"
    CATALOG_FILE = CONFIG_DIR / "catalog.json"
    GUI_MODEL_FILE = CONFIG_DIR / "gui-model.json"

    _PROVIDER_ENV_KEYS = {
        "glm": (("GLM_API_KEY",), ("GLM_MODEL",), ("GLM_BASE_URL",)),
        "deepseek": (("DEEPSEEK_API_KEY",), ("DEEPSEEK_MODEL",), ("DEEPSEEK_BASE_URL",)),
        "qwen": (
            ("QWEN_API_KEY", "DASHSCOPE_API_KEY"),
            ("QWEN_MODEL", "DASHSCOPE_MODEL"),
            ("QWEN_BASE_URL", "DASHSCOPE_BASE_URL"),
        ),
        "ollama": ((), ("OLLAMA_MODEL",), ("OLLAMA_BASE_URL",)),
    }

    def __init__(self):
        self.default_provider: str = "glm"
        self.providers: dict[str, ProviderConfig] = {}
        self.active_model_preset: str = "glm-5.1"
        self.active_persona: str = "vox"
        self.active_language: str = "zh-CN"
        self.active_skin: str = "glass"
        self.active_pet: str = "terminal-cat"
        self.skipped_update_version: str = ""
        self._catalog: dict = merge_catalog(DEFAULT_CATALOG, {})

    @classmethod
    def config_dir(cls) -> Path:
        override = os.environ.get("VOX_CODE_HOME", "").strip() or os.environ.get("VOX_HOME", "").strip()
        if override:
            return Path(override).expanduser()
        return Path.home() / ".vox-code"

    @classmethod
    def config_file(cls) -> Path:
        return cls.config_dir() / "config.json"

    @classmethod
    def catalog_file(cls) -> Path:
        return cls.config_dir() / "catalog.json"

    @classmethod
    def gui_model_file(cls) -> Path:
        return cls.config_dir() / "gui-model.json"

    @staticmethod
    def _read_env(keys: str | tuple[str, ...]) -> Optional[str]:
        if isinstance(keys, str):
            keys = (keys,)
        for key in keys:
            val = os.environ.get(key)
            if val and val.strip():
                return val.strip()
        return None

    def _ensure_catalog_loaded(self):
        self._catalog = merge_catalog(DEFAULT_CATALOG, load_catalog_from_file(self.catalog_file()))

    def save(self):
        config_dir = self.config_dir()
        config_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "defaultProvider": self.default_provider,
            "providers": {k: v.to_dict() for k, v in self.providers.items()},
            "activeModelPreset": self.active_model_preset,
            "activePersona": self.active_persona,
            "activeLanguage": self.active_language,
            "activeSkin": self.active_skin,
            "activePet": self.active_pet,
            "skippedUpdateVersion": self.skipped_update_version,
        }
        self.config_file().write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @classmethod
    def load(cls) -> "VoxCodeConfig":
        cfg = cls()
        config_file = cls.config_file()
        if config_file.exists():
            try:
                data = json.loads(config_file.read_text(encoding="utf-8"))
                cfg.default_provider = str(data.get("defaultProvider", "glm")).strip() or "glm"
                cfg.active_model_preset = str(data.get("activeModelPreset", "glm-5.1")).strip() or "glm-5.1"
                cfg.active_persona = str(data.get("activePersona", "vox")).strip() or "vox"
                cfg.active_language = str(data.get("activeLanguage", "zh-CN")).strip() or "zh-CN"
                cfg.active_skin = str(data.get("activeSkin", "glass")).strip() or "glass"
                cfg.active_pet = str(data.get("activePet", "terminal-cat")).strip() or "terminal-cat"
                cfg.skipped_update_version = str(data.get("skippedUpdateVersion", "")).strip()
                for name, pc_data in data.get("providers", {}).items():
                    cfg.providers[str(name).lower()] = ProviderConfig.from_dict(pc_data)
            except Exception as e:
                print(f"⚠️ 配置文件读取失败: {e}")
        cfg._ensure_catalog_loaded()
        cfg._normalize_active_ids()
        return cfg

    def reload_catalog(self):
        self._ensure_catalog_loaded()
        self._normalize_active_ids()

    def _normalize_active_ids(self):
        if self.get_model_preset(self.active_model_preset) is None:
            presets = self.model_presets()
            if presets:
                self.active_model_preset = presets[0].id
        if self.get_persona(self.active_persona) is None:
            personas = self.personas()
            if personas:
                self.active_persona = personas[0]["id"]
        if self.get_language(self.active_language) is None:
            languages = self.languages()
            if languages:
                self.active_language = languages[0]["id"]
        if self.get_skin(self.active_skin) is None:
            skins = self.skins()
            if skins:
                self.active_skin = skins[0]["id"]
        if self.get_builtin_pet(self.active_pet) is None:
            pets = self.builtin_pets()
            if pets:
                self.active_pet = pets[0]["id"]

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

    def get_provider(self, name: str) -> Optional[ProviderConfig]:
        name = name.lower()
        pc = self.providers.get(name)
        if pc and pc.api_key and pc.model:
            return pc

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

    def catalog(self) -> dict:
        return self._catalog

    def quick_commands(self) -> list[dict]:
        return [dict(item) for item in self._catalog.get("quickCommands", [])]

    def languages(self) -> list[dict]:
        return [dict(item) for item in self._catalog.get("languages", [])]

    def get_language(self, language_id: str) -> Optional[dict]:
        for language in self._catalog.get("languages", []):
            if str(language.get("id", "")).strip() == language_id:
                return dict(language)
        return None

    def active_language_text(self, key: str, default: str = "") -> str:
        language = self.get_language(self.active_language) or {}
        texts = language.get("texts", {})
        return str(texts.get(key, default))

    def skins(self) -> list[dict]:
        return [dict(item) for item in self._catalog.get("skins", [])]

    def get_skin(self, skin_id: str) -> Optional[dict]:
        for skin in self._catalog.get("skins", []):
            if str(skin.get("id", "")).strip() == skin_id:
                return dict(skin)
        return None

    def builtin_pets(self) -> list[dict]:
        return [dict(item) for item in self._catalog.get("pets", [])]

    def get_builtin_pet(self, pet_id: str) -> Optional[dict]:
        for pet in self._catalog.get("pets", []):
            if str(pet.get("id", "")).strip() == pet_id:
                return dict(pet)
        return None

    def personas(self) -> list[dict]:
        return [dict(item) for item in self._catalog.get("personas", [])]

    def get_persona(self, persona_id: str) -> Optional[dict]:
        for persona in self._catalog.get("personas", []):
            if str(persona.get("id", "")).strip() == persona_id:
                return dict(persona)
        return None

    def get_active_persona_prompt(self) -> str:
        persona = self.get_persona(self.active_persona)
        if persona:
            return str(persona.get("prompt", "")).strip()
        fallbacks = self.personas()
        if fallbacks:
            return str(fallbacks[0].get("prompt", "")).strip()
        return ""

    def model_presets(self) -> list[ModelPreset]:
        presets: list[ModelPreset] = []
        for item in self._catalog.get("modelPresets", []):
            preset = ModelPreset.from_dict(item)
            if preset.id and preset.provider:
                presets.append(preset)
        return presets

    def find_model_preset(self, provider: str, model: str) -> Optional[ModelPreset]:
        normalized_provider = provider.strip().lower()
        normalized_model = model.strip()
        for preset in self.model_presets():
            if preset.provider == normalized_provider and preset.model == normalized_model:
                return preset
        return None

    def get_model_preset(self, preset_id: str) -> Optional[ModelPreset]:
        target = preset_id.strip()
        for preset in self.model_presets():
            if preset.id == target:
                return preset
        return None

    def resolve_model_selection(self, value: str) -> tuple[str, Optional[str], Optional[ModelPreset]]:
        target = value.strip()
        preset = self.get_model_preset(target)
        if preset is not None:
            return preset.provider, preset.model, preset

        provider = target
        model_name = None
        if ":" in target:
            provider, model_name = target.split(":", 1)
        return provider.strip().lower(), (model_name or "").strip() or None, None

    def set_active_model_preset(self, preset_id: str):
        self.active_model_preset = preset_id
        self.save()

    def set_provider_config(self, provider: str, config: ProviderConfig):
        self.providers[provider.strip().lower()] = config

    def persist_model_selection(self, provider: str, model: str):
        normalized_provider = provider.strip().lower()
        normalized_model = model.strip()
        if not normalized_provider:
            return

        provider_config = self.providers.get(normalized_provider, ProviderConfig())
        if normalized_model:
            provider_config.model = normalized_model
        self.providers[normalized_provider] = provider_config
        self.default_provider = normalized_provider

        if normalized_model:
            preset = self.find_model_preset(normalized_provider, normalized_model)
            if preset is None:
                preset = self._save_custom_model_preset(normalized_provider, normalized_model)
            self.active_model_preset = preset.id

        self.save()

    def set_active_persona(self, persona_id: str):
        self.active_persona = persona_id
        self.save()

    def set_active_language(self, language_id: str):
        self.active_language = language_id
        self.save()

    def set_active_skin(self, skin_id: str):
        self.active_skin = skin_id
        self.save()

    def set_active_pet(self, pet_id: str):
        self.active_pet = pet_id
        self.save()

    def skip_update_version(self, version: str):
        self.skipped_update_version = version.strip()
        self.save()

    def clear_skipped_update_version(self):
        if not self.skipped_update_version:
            return
        self.skipped_update_version = ""
        self.save()

    def _save_custom_model_preset(self, provider: str, model: str) -> ModelPreset:
        preset = ModelPreset(
            id=f"custom-{provider}-{self._slugify(model)}",
            label=f"{self._provider_label(provider)} {model}",
            provider=provider,
            model=model,
            description="用户自定义模型。",
        )

        override = load_catalog_from_file(self.catalog_file())
        existing_presets = override.get("modelPresets", [])
        if not isinstance(existing_presets, list):
            existing_presets = []

        updated = False
        merged_presets: list[dict] = []
        for item in existing_presets:
            if isinstance(item, dict) and str(item.get("id", "")).strip() == preset.id:
                merged_presets.append(
                    {
                        "id": preset.id,
                        "label": preset.label,
                        "provider": preset.provider,
                        "model": preset.model,
                        "description": preset.description,
                    }
                )
                updated = True
            else:
                merged_presets.append(item)

        if not updated:
            merged_presets.append(
                {
                    "id": preset.id,
                    "label": preset.label,
                    "provider": preset.provider,
                    "model": preset.model,
                    "description": preset.description,
                }
            )

        override["modelPresets"] = merged_presets
        self.catalog_file().parent.mkdir(parents=True, exist_ok=True)
        self.catalog_file().write_text(
            json.dumps(override, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.reload_catalog()
        return preset

    @staticmethod
    def _slugify(value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
        return slug or "model"

    @staticmethod
    def _provider_label(provider: str) -> str:
        return {
            "glm": "GLM",
            "deepseek": "DeepSeek",
            "qwen": "Qwen",
            "ollama": "Ollama",
        }.get(provider, provider.upper())


class GuiModelConfigStore:
    def __init__(self, path: Path | None = None):
        self._path = path or VoxCodeConfig.gui_model_file()

    @property
    def path(self) -> Path:
        return self._path

    def exists(self) -> bool:
        return self.path.exists()

    def load(self) -> GuiModelConfig:
        if not self.path.exists():
            return GuiModelConfig()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError(f"GUI 模型配置读取失败: {exc}") from exc
        return GuiModelConfig.from_dict(data)

    def save(self, config: GuiModelConfig):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(config.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


pai_config = VoxCodeConfig.load()
