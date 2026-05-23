"""Configuration models and persistent state for the desktop pet UI."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import shutil

from PySide6.QtGui import QColor

from ...chat import ChatAttachment
from ...config import GuiModelConfig, pai_config
from ...llm.factory import default_model_for


@dataclass
class ChatMessage:
    role: str
    text: str
    attachments: tuple[ChatAttachment, ...] = field(default_factory=tuple)


class PendingAttachmentStore:
    def __init__(self):
        self._attachments: list[ChatAttachment] = []

    def attachments(self) -> tuple[ChatAttachment, ...]:
        return tuple(self._attachments)

    def clear(self):
        self._attachments.clear()

    def remove(self, attachment_id: str):
        self._attachments = [item for item in self._attachments if item.id != attachment_id]

    def reorder(self, ordered_ids: list[str]):
        lookup = {item.id: item for item in self._attachments}
        reordered = [lookup[item_id] for item_id in ordered_ids if item_id in lookup]
        if len(reordered) == len(self._attachments):
            self._attachments = reordered

    def add_files(self, paths: list[str]) -> list[ChatAttachment]:
        added: list[ChatAttachment] = []
        existing_paths = {item.file_path for item in self._attachments}
        for path in paths:
            attachment = ChatAttachment.from_path(path)
            if attachment.file_path in existing_paths:
                continue
            self._attachments.append(attachment)
            existing_paths.add(attachment.file_path)
            added.append(attachment)
        return added


@dataclass(frozen=True)
class PetPackage:
    id: str
    display_name: str
    description: str
    kind: str
    spritesheet_path: str = ""

    @property
    def has_spritesheet(self) -> bool:
        return self.kind == "sprite" and bool(self.spritesheet_path)


@dataclass(frozen=True)
class SkinPalette:
    id: str
    bubble_bg_start: str
    bubble_bg_end: str
    bubble_border: str
    bubble_text: str
    panel_gradient_start: str
    panel_gradient_mid: str
    panel_gradient_end: str
    panel_border: str
    panel_text: str
    input_bg: str
    input_border: str
    secondary_text: str
    primary_button_start: str
    primary_button_end: str
    primary_button_border: str
    secondary_button_bg: str
    secondary_button_text: str
    close_button_bg: str
    close_button_border: str
    close_button_text: str
    toolbar_bg_start: str
    toolbar_bg_end: str
    toolbar_border: str
    pet_shadow: QColor
    pet_glow: QColor
    pet_base: QColor
    pet_outline: QColor
    pet_blush: QColor
    pet_eye: QColor
    pet_nose: QColor
    pet_mouth: QColor
    pet_charm: QColor
    pet_highlight: QColor
    mode_bg: str
    mode_border: str
    mode_text: str


_RGBA_RE = re.compile(r"rgba?\(([^)]+)\)")


def _parse_qcolor(value: str) -> QColor:
    text = str(value).strip()
    match = _RGBA_RE.fullmatch(text)
    if match:
        parts = [int(float(part.strip())) for part in match.group(1).split(",")]
        if len(parts) == 3:
            return QColor(parts[0], parts[1], parts[2])
        if len(parts) >= 4:
            return QColor(parts[0], parts[1], parts[2], parts[3])
    color = QColor(text)
    return color if color.isValid() else QColor(255, 255, 255)


def _load_skin_palettes() -> dict[str, SkinPalette]:
    palettes: dict[str, SkinPalette] = {}
    for skin in pai_config.skins():
        skin_id = str(skin.get("id", "")).strip()
        if not skin_id:
            continue
        palettes[skin_id] = SkinPalette(
            id=skin_id,
            bubble_bg_start=str(skin.get("bubble_bg_start", "")),
            bubble_bg_end=str(skin.get("bubble_bg_end", "")),
            bubble_border=str(skin.get("bubble_border", "")),
            bubble_text=str(skin.get("bubble_text", "")),
            panel_gradient_start=str(skin.get("panel_gradient_start", "")),
            panel_gradient_mid=str(skin.get("panel_gradient_mid", "")),
            panel_gradient_end=str(skin.get("panel_gradient_end", "")),
            panel_border=str(skin.get("panel_border", "")),
            panel_text=str(skin.get("panel_text", "")),
            input_bg=str(skin.get("input_bg", "")),
            input_border=str(skin.get("input_border", "")),
            secondary_text=str(skin.get("secondary_text", "")),
            primary_button_start=str(skin.get("primary_button_start", "")),
            primary_button_end=str(skin.get("primary_button_end", "")),
            primary_button_border=str(skin.get("primary_button_border", "")),
            secondary_button_bg=str(skin.get("secondary_button_bg", "")),
            secondary_button_text=str(skin.get("secondary_button_text", "")),
            close_button_bg=str(skin.get("close_button_bg", "")),
            close_button_border=str(skin.get("close_button_border", "")),
            close_button_text=str(skin.get("close_button_text", "")),
            toolbar_bg_start=str(skin.get("toolbar_bg_start", "")),
            toolbar_bg_end=str(skin.get("toolbar_bg_end", "")),
            toolbar_border=str(skin.get("toolbar_border", "")),
            pet_shadow=_parse_qcolor(str(skin.get("pet_shadow", "#ffffff"))),
            pet_glow=_parse_qcolor(str(skin.get("pet_glow", "#ffffff"))),
            pet_base=_parse_qcolor(str(skin.get("pet_base", "#ffffff"))),
            pet_outline=_parse_qcolor(str(skin.get("pet_outline", "#ffffff"))),
            pet_blush=_parse_qcolor(str(skin.get("pet_blush", "#ffffff"))),
            pet_eye=_parse_qcolor(str(skin.get("pet_eye", "#000000"))),
            pet_nose=_parse_qcolor(str(skin.get("pet_nose", "#000000"))),
            pet_mouth=_parse_qcolor(str(skin.get("pet_mouth", "#000000"))),
            pet_charm=_parse_qcolor(str(skin.get("pet_charm", "#ffffff"))),
            pet_highlight=_parse_qcolor(str(skin.get("pet_highlight", "#ffffff"))),
            mode_bg=str(skin.get("mode_bg", "")),
            mode_border=str(skin.get("mode_border", "")),
            mode_text=str(skin.get("mode_text", "")),
        )
    return palettes


def _load_builtin_pets() -> list[PetPackage]:
    packages: list[PetPackage] = []
    for pet in pai_config.builtin_pets():
        pet_id = str(pet.get("id", "")).strip()
        if not pet_id:
            continue
        packages.append(
            PetPackage(
                id=pet_id,
                display_name=str(pet.get("displayName", pet_id)).strip() or pet_id,
                description=str(pet.get("description", "")).strip(),
                kind=str(pet.get("kind", "drawn")).strip() or "drawn",
                spritesheet_path=str(pet.get("spritesheetPath", "")).strip(),
            )
        )
    return packages or [
        PetPackage("terminal-cat", "Terminal Cat", "默认吉祥物，小猫常驻终端旁边。", "drawn")
    ]


SKIN_PALETTES = _load_skin_palettes()
BUILTIN_PETS = _load_builtin_pets()
if not SKIN_PALETTES:
    SKIN_PALETTES = {
        "glass": SkinPalette(
            id="glass",
            bubble_bg_start="rgba(255,250,243,245)",
            bubble_bg_end="rgba(248,233,209,235)",
            bubble_border="rgba(211,180,138,205)",
            bubble_text="#4c3825",
            panel_gradient_start="rgba(255,250,243,244)",
            panel_gradient_mid="rgba(250,238,222,236)",
            panel_gradient_end="rgba(238,247,240,228)",
            panel_border="rgba(219,193,160,210)",
            panel_text="#443527",
            input_bg="rgba(255,252,247,224)",
            input_border="rgba(216,199,175,235)",
            secondary_text="rgba(87,72,51,204)",
            primary_button_start="#f0b45b",
            primary_button_end="#df8c42",
            primary_button_border="rgba(197,122,44,242)",
            secondary_button_bg="rgba(255,249,240,209)",
            secondary_button_text="#6a5336",
            close_button_bg="rgba(255,244,238,204)",
            close_button_border="rgba(223,165,145,235)",
            close_button_text="#a04b3b",
            toolbar_bg_start="rgba(255,250,243,240)",
            toolbar_bg_end="rgba(244,232,214,232)",
            toolbar_border="rgba(214,189,156,205)",
            pet_shadow=QColor(66, 53, 40, 34),
            pet_glow=QColor(255, 228, 170, 26),
            pet_base=QColor(251, 247, 241),
            pet_outline=QColor(218, 204, 186),
            pet_blush=QColor(255, 214, 205, 120),
            pet_eye=QColor(61, 64, 72),
            pet_nose=QColor(245, 186, 172),
            pet_mouth=QColor(97, 82, 70),
            pet_charm=QColor(255, 242, 218),
            pet_highlight=QColor(255, 252, 247, 88),
            mode_bg="rgba(255,248,239,210)",
            mode_border="rgba(211,180,138,180)",
            mode_text="#6b5a41",
        )
    }


GUI_MODEL_PROFILES = (
    {
        "id": "codex",
        "label": "OpenAI Compatible",
        "summary": "适合任何 OpenAI 兼容网关，可直接自定义 model。",
    },
)


def gui_model_profile_meta(profile_id: str) -> dict[str, str]:
    normalized = normalize_gui_model_provider(profile_id)
    for profile in GUI_MODEL_PROFILES:
        if profile["id"] == normalized:
            return dict(profile)
    return dict(GUI_MODEL_PROFILES[0])


def gui_model_profile_label(profile_id: str) -> str:
    normalized = normalize_gui_model_provider(profile_id)
    for profile in GUI_MODEL_PROFILES:
        if profile["id"] == normalized:
            return profile["label"]
    return profile_id


def normalize_gui_model_provider(value: str) -> str:
    normalized = value.strip().lower().replace("_", "-")
    aliases = {
        "openai": "codex",
        "openai-compatible": "codex",
        "openai-compatible-api": "codex",
        "claude": "codex",
        "claudecode": "codex",
        "claude-code": "codex",
        "codex": "codex",
    }
    return aliases.get(normalized, "codex")


def load_gui_model_config_from_json(
    text: str,
    current: GuiModelConfig | None = None,
) -> GuiModelConfig:
    fallback = current or GuiModelConfig(enabled=True)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 解析失败: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError("JSON 顶层必须是对象。")

    scoped = payload
    for key in ("guiModel", "modelConfig", "config"):
        nested = scoped.get(key)
        if isinstance(nested, dict):
            scoped = nested
            break

    provider = normalize_gui_model_provider(
        str(
            scoped.get("provider")
            or scoped.get("profile")
            or scoped.get("type")
            or fallback.provider
            or "codex"
        )
    )
    enabled_raw = scoped.get("enabled", True)
    enabled = (
        enabled_raw
        if isinstance(enabled_raw, bool)
        else str(enabled_raw).strip().lower() not in {"0", "false", "no"}
    )
    model = str(scoped.get("model", "")).strip() or fallback.model or default_model_for(provider)
    base_url = normalize_gui_model_base_url(
        str(scoped.get("baseUrl", scoped.get("base_url", fallback.base_url))).strip()
    )
    api_key = str(scoped.get("apiKey", scoped.get("api_key", fallback.api_key))).strip()
    return GuiModelConfig(
        enabled=enabled,
        provider=provider,
        model=model,
        base_url=base_url,
        api_key=api_key,
    )


def normalize_gui_model_base_url(value: str) -> str:
    base_url = value.strip()
    if not base_url:
        return ""
    normalized = base_url.rstrip("/")
    lower = normalized.lower()
    if lower.endswith("/chat/completions") or lower.endswith("/beta/chat/completions"):
        return normalized
    return normalized + "/chat/completions"


def gui_state_root() -> Path:
    override = os.environ.get("VOX_CODE_HOME", "").strip() or os.environ.get("VOX_HOME", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".vox-code"


class GuiStateStore:
    def load_skin(self) -> str:
        skin = str(pai_config.active_skin).strip().lower()
        return skin if skin in SKIN_PALETTES else "glass"

    def save_skin(self, skin: str):
        pai_config.set_active_skin(skin)

    def load_selected_pet(self) -> str:
        return str(pai_config.active_pet).strip() or "terminal-cat"

    def save_selected_pet(self, pet_id: str):
        pai_config.set_active_pet(pet_id)


class PetPackageStore:
    def __init__(self):
        self._root = gui_state_root() / "ImportedPets"

    @property
    def root(self) -> Path:
        self._root.mkdir(parents=True, exist_ok=True)
        return self._root

    def list_imported(self) -> list[PetPackage]:
        packages: list[PetPackage] = []
        for child in sorted(self.root.iterdir()):
            if not child.is_dir():
                continue
            package = self._load_from_dir(child)
            if package is not None:
                packages.append(package)
        return packages

    def import_folder(self, folder: str) -> PetPackage:
        source = Path(folder).expanduser().resolve()
        package = self._load_from_dir(source)
        if package is None:
            raise ValueError("所选文件夹不是有效的宠物包，必须包含 pet.json 和 spritesheet.webp")

        destination = self.root / package.id
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source, destination)
        imported = self._load_from_dir(destination)
        if imported is None:
            raise ValueError("导入后无法读取宠物包")
        return imported

    def _load_from_dir(self, folder: Path) -> PetPackage | None:
        config_path = folder / "pet.json"
        if not config_path.exists():
            return None
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            return None

        spritesheet_name = str(data.get("spritesheetPath", "spritesheet.webp")).strip() or "spritesheet.webp"
        sprite_path = folder / spritesheet_name
        if not sprite_path.exists():
            fallback = folder / "spritesheet.webp"
            if not fallback.exists():
                return None
            sprite_path = fallback

        pet_id = str(data.get("id", folder.name)).strip() or folder.name
        display_name = str(data.get("displayName", pet_id)).strip() or pet_id
        description = str(data.get("description", "")).strip()
        return PetPackage(
            id=pet_id,
            display_name=display_name,
            description=description,
            kind="sprite",
            spritesheet_path=str(sprite_path),
        )
