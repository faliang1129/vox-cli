"""Structured chat submissions shared by the GUI and runtime layers."""

from __future__ import annotations

from dataclasses import dataclass
import mimetypes
from pathlib import Path
import uuid

SUPPORTED_IMAGE_MIME_TYPES = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/webp",
    }
)

_SUFFIX_TO_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


def supported_image_extensions_text() -> str:
    return "png/jpg/jpeg/webp"


def guess_image_mime_type(path: str | Path) -> str:
    file_path = Path(path).expanduser()
    mime_type = _SUFFIX_TO_MIME.get(file_path.suffix.lower())
    if not mime_type:
        guessed, _encoding = mimetypes.guess_type(file_path.name)
        mime_type = guessed or ""
    if mime_type not in SUPPORTED_IMAGE_MIME_TYPES:
        raise ValueError(
            f"仅支持 {supported_image_extensions_text()} 图片，当前文件不受支持: {file_path.name}"
        )
    return mime_type


@dataclass(frozen=True)
class ChatAttachment:
    id: str
    file_path: str
    display_name: str
    mime_type: str

    @classmethod
    def from_path(cls, path: str | Path, attachment_id: str | None = None) -> "ChatAttachment":
        file_path = Path(path).expanduser()
        if not file_path.exists():
            raise FileNotFoundError(f"图片不存在: {file_path}")
        if not file_path.is_file():
            raise ValueError(f"不是有效的图片文件: {file_path}")
        mime_type = guess_image_mime_type(file_path)
        return cls(
            id=attachment_id or uuid.uuid4().hex,
            file_path=str(file_path.resolve()),
            display_name=file_path.name,
            mime_type=mime_type,
        )


@dataclass(frozen=True)
class GuiChatSubmission:
    text: str = ""
    attachments: tuple[ChatAttachment, ...] = ()

    def normalized(self) -> "GuiChatSubmission":
        return GuiChatSubmission(
            text=self.text.strip(),
            attachments=tuple(self.attachments),
        )

    @property
    def has_attachments(self) -> bool:
        return bool(self.attachments)

    @property
    def is_empty(self) -> bool:
        return not self.text.strip() and not self.attachments

    @property
    def summary_text(self) -> str:
        if self.text.strip():
            return self.text.strip()
        if self.attachments:
            return f"[用户发送了 {len(self.attachments)} 张图片]"
        return ""
