"""Background workers for the desktop pet UI."""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from ...chat import GuiChatSubmission
from ...config import GuiModelConfig
from ...llm.base import Message
from ...llm.factory import create_from_provider_config
from ...runtime import SessionController


class SessionWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, controller: SessionController, line: str | GuiChatSubmission):
        super().__init__()
        self._controller = controller
        self._line = line

    def run(self):
        try:
            reply = self._controller.submit(self._line)
            self.completed.emit(reply)
        except Exception as exc:
            self.failed.emit(str(exc))


class ModelConnectionTestWorker(QThread):
    completed = Signal(str)
    failed = Signal(str)

    def __init__(self, config: GuiModelConfig):
        super().__init__()
        self._config = config

    def run(self):
        try:
            missing = self._config.validate()
            if missing:
                raise ValueError(f"缺少字段: {', '.join(missing)}")
            client = create_from_provider_config(
                self._config.provider,
                self._config.provider_config(),
            )
            if client is None:
                raise RuntimeError(f"无法创建 provider={self._config.provider} 的客户端")
            response = client.chat([Message.user("Reply with OK only.")])
            summary = (response.content or "").strip() or "OK"
            self.completed.emit(f"连接成功: {summary[:48]}")
        except Exception as exc:
            self.failed.emit(str(exc))
