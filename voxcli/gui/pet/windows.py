"""
Floating windows used by the desktop pet UI."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...chat import ChatAttachment, GuiChatSubmission
from ...config import GuiModelConfig, pai_config
from ...llm.factory import default_model_for
from ...runtime import SessionController, SessionReply
from .base import FramelessToolWindow, make_shadow, termi_panel_stylesheet
from .data import (
    ChatMessage,
    PendingAttachmentStore,
    PetPackage,
    gui_model_profile_label,
    gui_model_profile_meta,
    load_gui_model_config_from_json,
    normalize_gui_model_base_url,
)
from .widgets import PetCardWidget
from .workers import ModelConnectionTestWorker


class CommandCardButton(QPushButton):
    def __init__(self, title: str, summary: str, command_text: str):
        super().__init__()
        self._title = title
        self._summary = summary
        self.command_text = command_text
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(112)
        self.setFlat(True)
        self.setToolTip(summary or command_text)

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect().adjusted(1, 1, -1, -1)
        if self.isDown():
            bg = QColor(38, 41, 48)
        elif self.underMouse():
            bg = QColor(28, 31, 36)
        else:
            bg = QColor(22, 24, 28)

        painter.setPen(QPen(QColor(58, 62, 70), 1))
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, 16, 16)

        title_rect = rect.adjusted(18, 16, -18, -56)
        summary_rect = rect.adjusted(18, 52, -18, -14)

        title_font = QFont("Menlo")
        if not title_font.exactMatch():
            title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(QColor(236, 236, 236))
        painter.drawText(
            title_rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap),
            self._title,
        )

        summary_font = QFont()
        summary_font.setPointSize(10)
        summary_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(summary_font)
        painter.setPen(QColor(145, 145, 145))
        painter.drawText(
            summary_rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap),
            self._summary,
        )


class FloatingActionBar(QFrame):
    chat_requested = Signal()
    commands_requested = Signal()
    hover_changed = Signal(bool)

    def __init__(self):
        super().__init__()
        self._active_panel = ""
        self._texts = {
            "toolbar_chat": "聊天",
            "toolbar_commands": "命令",
        }
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setObjectName("toolbarPanel")
        make_shadow(self, blur=24, y=6, alpha=54)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        self.commands_button = self._make_button("令", self.commands_requested.emit)
        self.chat_button = self._make_button("聊", self.chat_requested.emit)
        layout.addWidget(self.commands_button)
        layout.addWidget(self.chat_button)

        self.apply_skin("dark")
        self.hide()

    def _make_button(self, text: str, handler):
        button = QPushButton(text)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFixedSize(54, 54)
        button.clicked.connect(handler)
        return button

    def sync_state(self, mode: str, presentation_mode: str, skin: str, pet_name: str):
        return

    def set_active_panel(self, panel: str):
        self._active_panel = panel
        self._refresh_button_styles()

    def set_language(self, texts: dict[str, str]):
        self._texts["toolbar_chat"] = texts.get("toolbar_chat", "聊天")
        self._texts["toolbar_commands"] = texts.get("toolbar_commands", "命令")
        self.chat_button.setToolTip(self._texts["toolbar_chat"])
        self.commands_button.setToolTip(self._texts["toolbar_commands"])

    def _refresh_button_styles(self):
        self.commands_button.setStyleSheet(self._button_stylesheet(self._active_panel == "commands"))
        self.chat_button.setStyleSheet(self._button_stylesheet(self._active_panel == "chat"))

    def _button_stylesheet(self, active: bool) -> str:
        bg = "rgba(63, 67, 74, 235)" if active else "rgba(29, 32, 36, 232)"
        border = "rgba(132, 136, 144, 230)" if active else "rgba(86, 90, 98, 220)"
        return (
            "QPushButton {"
            f"background: {bg};"
            f"border: 1px solid {border};"
            "border-radius: 27px;"
            "color: #f2f2f2;"
            "font-size: 18px;"
            "font-weight: 700;"
            "}"
            "QPushButton:hover { background: rgba(74, 79, 87, 238); }"
        )

    def apply_skin(self, skin: str):
        self.setStyleSheet(f"#toolbarPanel {{{termi_panel_stylesheet(radius=28)}}}")
        self._refresh_button_styles()

    def enterEvent(self, event):
        self.hover_changed.emit(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hover_changed.emit(False)
        super().leaveEvent(event)


class StatusCardWidget(QFrame):
    """Floating status card — mode, model, state dot, optional bubble preview.

    Appears above the toolbar on hover. Managed by PetCoordinator.
    """

    STATE_COLORS = {
        "idle": QColor(140, 140, 145),
        "thinking": QColor(255, 193, 94),
        "working": QColor(10, 132, 255),
        "error": QColor(255, 89, 89),
        "celebrate": QColor(50, 210, 120),
        "alert": QColor(255, 183, 64),
    }

    STATE_LABELS = {
        "idle": "空闲",
        "thinking": "思考中",
        "working": "执行中",
        "error": "出错",
        "celebrate": "完成",
        "alert": "提醒",
    }

    CARD_WIDTH = 260
    ROW1_Y = 10
    ROW1_H = 28
    DIVIDER_Y = 42
    ROW2_Y = 48
    ROW2_H = 26
    PAD_TOP = 8
    PAD_BOTTOM = 10

    def __init__(self):
        super().__init__()
        self._mode = "single"
        self._model_provider = ""
        self._model_name = ""
        self._state = "idle"
        self._bubble_text = ""

        self.setObjectName("statusCard")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        make_shadow(self, blur=24, y=6, alpha=54)
        self.setFixedWidth(self.CARD_WIDTH)
        self.adjustSize()
        self.hide()

    def set_status(
        self,
        mode: str = "",
        model_provider: str = "",
        model_name: str = "",
        state: str = "idle",
        bubble_text: str = "",
    ):
        self._mode = mode or self._mode
        self._model_provider = model_provider or self._model_provider
        self._model_name = model_name or self._model_name
        self._state = state if state in self.STATE_COLORS else "idle"
        self._bubble_text = bubble_text or ""
        self.adjustSize()
        self.update()

    def sizeHint(self):
        h = self.PAD_TOP + self.ROW1_H + self.PAD_BOTTOM
        if self._bubble_text:
            h += self.ROW2_Y - self.ROW1_H + self.ROW2_H
        return QSize(self.CARD_WIDTH, h)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect().adjusted(1, 1, -1, -1)

        # Background
        painter.setPen(QPen(QColor(58, 62, 70), 1))
        painter.setBrush(QColor(16, 18, 22, 238))
        painter.drawRoundedRect(rect, 18, 18)

        dot_color = self.STATE_COLORS.get(self._state, self.STATE_COLORS["idle"])

        # State dot
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(dot_color)
        painter.drawEllipse(QPoint(24, self.ROW1_Y + self.ROW1_H // 2), 5, 5)

        # Mode badge
        mode_font = QFont("Menlo")
        if not mode_font.exactMatch():
            mode_font = QFont()
        mode_font.setPointSize(11)
        mode_font.setBold(True)
        painter.setFont(mode_font)
        painter.setPen(QColor(236, 236, 236))
        mode_rect = QRect(36, self.ROW1_Y, 72, self.ROW1_H)
        painter.drawText(
            mode_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self._mode.upper(),
        )

        # Model name
        model_text = self._model_name or self._model_provider
        if model_text:
            model_font = QFont()
            model_font.setPointSize(10)
            painter.setFont(model_font)
            painter.setPen(QColor(165, 165, 170))
            model_rect = QRect(104, self.ROW1_Y, 90, self.ROW1_H)
            painter.drawText(
                model_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                model_text,
            )

        # State label (right-aligned)
        state_label = self.STATE_LABELS.get(self._state, self._state)
        painter.setPen(dot_color)
        painter.setFont(mode_font)
        state_rect = QRect(rect.right() - 76, self.ROW1_Y, 62, self.ROW1_H)
        painter.drawText(
            state_rect,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            state_label,
        )

        # Bubble text (optional second row)
        if self._bubble_text:
            import textwrap

            preview = textwrap.shorten(
                " ".join(self._bubble_text.split()), width=48, placeholder="..."
            )
            painter.setPen(QPen(QColor(58, 62, 70), 1))
            painter.drawLine(rect.left() + 14, self.DIVIDER_Y, rect.right() - 14, self.DIVIDER_Y)

            bubble_font = QFont()
            bubble_font.setPointSize(10)
            painter.setFont(bubble_font)
            painter.setPen(QColor(185, 185, 190))
            text_rect = QRect(20, self.ROW2_Y, rect.width() - 40, self.ROW2_H)
            painter.drawText(
                text_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap,
                preview,
            )


class CommandWindow(FramelessToolWindow):
    submitted = Signal(str)

    def __init__(self):
        super().__init__()
        self._cards: list[CommandCardButton] = []
        self._language_texts: dict[str, str] = {}
        self.setMinimumSize(QSize(720, 560))
        self.resize(720, 560)

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)

        self.panel = QFrame()
        self.panel.setObjectName("commandPanel")
        make_shadow(self.panel, blur=34, y=10, alpha=78)
        outer.addWidget(self.panel)

        layout = QVBoxLayout(self.panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QHBoxLayout()
        header.setContentsMargins(18, 18, 18, 18)
        header.setSpacing(12)

        self.icon_label = QLabel(">_")
        self.icon_label.setObjectName("commandIcon")
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setFixedSize(34, 28)
        header.addWidget(self.icon_label)

        self.title_label = QLabel("快捷指令")
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        header.addWidget(self.title_label)
        header.addStretch(1)

        self.count_label = QLabel("0")
        self.count_label.setObjectName("commandCount")
        header.addWidget(self.count_label)
        layout.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background: transparent;")
        layout.addWidget(scroll, 1)

        container = QWidget()
        scroll.setWidget(container)
        self.grid = QGridLayout(container)
        self.grid.setContentsMargins(18, 8, 18, 18)
        self.grid.setHorizontalSpacing(14)
        self.grid.setVerticalSpacing(14)

        self.apply_skin("dark")

    def set_quick_commands(self, commands: list[dict]):
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._cards.clear()

        visible = 0
        for command in commands:
            command_text = str(command.get("command", "")).strip()
            if not command_text:
                continue
            title = str(command.get("label", command_text)).strip() or command_text
            summary = str(command.get("description", "")).strip()
            button = CommandCardButton(title, summary, command_text)
            button.clicked.connect(lambda _checked=False, value=command_text: self.submitted.emit(value))
            self.grid.addWidget(button, visible // 2, visible % 2)
            self._cards.append(button)
            visible += 1
        self.count_label.setText(str(visible))

    def set_language(self, texts: dict[str, str]):
        self._language_texts = dict(texts)
        self.title_label.setText(texts.get("quick_commands_title", "快捷指令"))

    def apply_skin(self, skin: str):
        self.setStyleSheet(
            "QMainWindow { background: transparent; }"
            f"#commandPanel {{{termi_panel_stylesheet(radius=26)}}}"
            "#commandIcon {"
            "background: rgba(235, 235, 235, 220);"
            "border-radius: 8px;"
            "color: #111111;"
            "font-size: 14px;"
            "font-weight: 700;"
            "}"
            "#commandCount {"
            "color: rgba(164, 164, 164, 220);"
            "font-size: 14px;"
            "font-weight: 700;"
            "}"
            "QLabel { color: #f1f1f1; }"
            "QScrollArea { background: transparent; }"
        )


def _build_attachment_thumbnail(file_path: str, size: int) -> QPixmap:
    pixmap = QPixmap(file_path)
    if not pixmap.isNull():
        return pixmap.scaled(
            size,
            size,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )

    fallback = QPixmap(size, size)
    fallback.fill(QColor(54, 57, 63))
    painter = QPainter(fallback)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(QColor(219, 222, 228))
    font = QFont()
    font.setPointSize(9)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(fallback.rect(), int(Qt.AlignmentFlag.AlignCenter), "IMG")
    painter.end()
    return fallback


class AttachmentChipWidget(QFrame):
    remove_requested = Signal(str)

    def __init__(self, attachment: ChatAttachment):
        super().__init__()
        self.attachment = attachment
        self.setObjectName("attachmentChip")
        self.setFixedSize(88, 100)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(0)
        top.addStretch(1)
        self.remove_button = QPushButton("x")
        self.remove_button.setObjectName("attachmentRemoveButton")
        self.remove_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remove_button.setFixedSize(18, 18)
        self.remove_button.clicked.connect(lambda: self.remove_requested.emit(self.attachment.id))
        top.addWidget(self.remove_button)
        layout.addLayout(top)

        self.thumbnail = QLabel()
        self.thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail.setFixedSize(72, 52)
        self.thumbnail.setPixmap(_build_attachment_thumbnail(attachment.file_path, 72))
        self.thumbnail.setScaledContents(False)
        self.thumbnail.setToolTip(attachment.file_path)
        layout.addWidget(self.thumbnail, 0, Qt.AlignmentFlag.AlignHCenter)

        self.name_label = QLabel(attachment.display_name)
        self.name_label.setWordWrap(True)
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_label.setToolTip(attachment.file_path)
        self.name_label.setObjectName("attachmentNameLabel")
        layout.addWidget(self.name_label, 1)


class AttachmentListWidget(QListWidget):
    files_dropped = Signal(list)
    order_changed = Signal(list)
    remove_requested = Signal(str)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(False)
        self.setSpacing(8)
        self.setMovement(QListView.Movement.Snap)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFixedHeight(116)

    def add_attachment(self, attachment: ChatAttachment):
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, attachment.id)
        item.setSizeHint(QSize(92, 104))
        self.addItem(item)
        chip = AttachmentChipWidget(attachment)
        chip.remove_requested.connect(self.remove_requested.emit)
        self.setItemWidget(item, chip)

    def attachment_ids(self) -> list[str]:
        return [
            str(self.item(index).data(Qt.ItemDataRole.UserRole))
            for index in range(self.count())
        ]

    def remove_attachment(self, attachment_id: str):
        for index in range(self.count()):
            item = self.item(index)
            if str(item.data(Qt.ItemDataRole.UserRole)) != attachment_id:
                continue
            removed = self.takeItem(index)
            del removed
            return

    def dragEnterEvent(self, event):
        if self._extract_paths(event):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if self._extract_paths(event):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event):
        paths = self._extract_paths(event)
        if paths:
            self.files_dropped.emit(paths)
            event.acceptProposedAction()
            return
        super().dropEvent(event)
        self.order_changed.emit(self.attachment_ids())

    @staticmethod
    def _extract_paths(event) -> list[str]:
        mime_data = event.mimeData()
        if mime_data is None or not mime_data.hasUrls():
            return []
        paths: list[str] = []
        for url in mime_data.urls():
            if url.isLocalFile():
                local_path = url.toLocalFile()
                if local_path:
                    paths.append(local_path)
        return paths


class ChatBubbleWidget(QFrame):
    def __init__(self, message: ChatMessage, streaming: bool = False):
        super().__init__()
        self._role = message.role
        self._streaming = streaming
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(11, 8, 11, 8)
        layout.setSpacing(6)
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.label)

        self.attachments_grid = None
        if message.attachments:
            attachments_widget = QWidget()
            self.attachments_grid = QGridLayout(attachments_widget)
            self.attachments_grid.setContentsMargins(0, 0, 0, 0)
            self.attachments_grid.setHorizontalSpacing(6)
            self.attachments_grid.setVerticalSpacing(6)
            for index, attachment in enumerate(message.attachments):
                preview = QLabel()
                preview.setFixedSize(84, 84)
                preview.setPixmap(_build_attachment_thumbnail(attachment.file_path, 84))
                preview.setScaledContents(False)
                preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
                preview.setStyleSheet(
                    "background: rgba(255, 255, 255, 0.08);"
                    "border: 1px solid rgba(255, 255, 255, 0.18);"
                    "border-radius: 10px;"
                )
                preview.setToolTip(attachment.file_path)
                self.attachments_grid.addWidget(preview, index // 2, index % 2)
            layout.addWidget(attachments_widget)

        self._apply_role_style()
        self.set_text(message.text, streaming=streaming)

    def set_text(self, text: str, streaming: bool = False):
        self._streaming = streaming
        self.label.setText(f"{text}▍" if streaming and text else text)
        self.label.setVisible(bool(text) or streaming)
        self.adjustSize()

    def _apply_role_style(self):
        if self._role == "user":
            bubble_bg = "#0a84ff"
            bubble_border = "#4eabff"
            bubble_text = "#ffffff"
        elif self._role == "error":
            bubble_bg = "rgba(79, 33, 33, 0.94)"
            bubble_border = "rgba(153, 74, 74, 0.92)"
            bubble_text = "#ffe4e4"
        else:
            bubble_bg = "rgba(46, 44, 45, 0.96)"
            bubble_border = "rgba(92, 92, 98, 0.84)"
            bubble_text = "#f2f2f2"

        self.setStyleSheet(
            "QFrame {"
            f"background: {bubble_bg};"
            f"border: 1px solid {bubble_border};"
            "border-radius: 14px;"
            "}"
            "QLabel {"
            f"color: {bubble_text};"
            "font-size: 13px;"
            "font-weight: 500;"
            "background: transparent;"
            "border: none;"
            "}"
        )


class ChatMessageRow(QWidget):
    def __init__(self, message: ChatMessage, streaming: bool = False):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.bubble = ChatBubbleWidget(message, streaming=streaming)
        self.bubble.setMaximumWidth(226)
        if message.role == "user":
            layout.addStretch(1)
            layout.addWidget(self.bubble, 0, Qt.AlignmentFlag.AlignRight)
        else:
            layout.addWidget(self.bubble, 0, Qt.AlignmentFlag.AlignLeft)
            layout.addStretch(1)

    def set_text(self, text: str, streaming: bool = False):
        self.bubble.set_text(text, streaming=streaming)


class ChatWindow(FramelessToolWindow):
    submitted = Signal(object)
    attachment_error = Signal(str)

    def __init__(self, controller: SessionController):
        super().__init__()
        self._controller = controller
        self._busy = False
        self._language_texts: dict[str, str] = {}
        self._messages: list[ChatMessage] = []
        self._attachment_store = PendingAttachmentStore()
        self._streaming_message: ChatMessage | None = None
        self._streaming_row: ChatMessageRow | None = None
        self._streaming_visible_text = ""
        self._streaming_index = 0
        self._compact_size = QSize(296, 74)
        self._expanded_size = QSize(296, 340)
        self._streaming_timer = QTimer(self)
        self._streaming_timer.timeout.connect(self._advance_streaming)
        self.setWindowTitle("Vox Pet")
        self.setAcceptDrops(True)
        self.setMinimumSize(self._compact_size)
        self.resize(self._compact_size)

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)

        panel = QFrame()
        panel.setObjectName("chatPanel")
        make_shadow(panel, blur=34, y=10, alpha=78)
        outer.addWidget(panel)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        self.messages_scroll = QScrollArea()
        self.messages_scroll.setWidgetResizable(True)
        self.messages_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.messages_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.messages_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { background: transparent; width: 8px; margin: 2px 0 2px 0; }"
            "QScrollBar::handle:vertical {"
            "background: rgba(110, 110, 116, 0.42);"
            "border-radius: 4px;"
            "min-height: 24px;"
            "}"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }"
        )

        self.messages_container = QWidget()
        self.messages_container.setStyleSheet("background: transparent;")
        self.messages_layout = QVBoxLayout(self.messages_container)
        self.messages_layout.setContentsMargins(2, 4, 2, 4)
        self.messages_layout.setSpacing(5)
        self.messages_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.messages_scroll.setWidget(self.messages_container)
        self.messages_scroll.setMinimumHeight(180)
        self.messages_scroll.setMaximumHeight(228)
        layout.addWidget(self.messages_scroll, 1)

        self.attachments_list = AttachmentListWidget()
        self.attachments_list.files_dropped.connect(self.add_attachment_files)
        self.attachments_list.order_changed.connect(self._reorder_pending_attachments)
        self.attachments_list.remove_requested.connect(self._remove_pending_attachment)
        self.attachments_list.hide()
        layout.addWidget(self.attachments_list)

        footer = QHBoxLayout()
        footer.setSpacing(6)
        self.attach_button = QPushButton("+")
        self.attach_button.setObjectName("attachButton")
        self.attach_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.attach_button.setFixedSize(40, 40)
        self.attach_button.clicked.connect(self._open_attachment_picker)
        footer.addWidget(self.attach_button)

        self.input = QLineEdit()
        self.input.returnPressed.connect(self._emit_submit)
        self.input.textChanged.connect(self._refresh_send_button_state)
        footer.addWidget(self.input, 1)

        self.send_button = QPushButton("↑")
        self.send_button.setObjectName("sendButton")
        self.send_button.setFixedSize(40, 40)
        self.send_button.clicked.connect(self._emit_submit)
        footer.addWidget(self.send_button)
        layout.addLayout(footer)

        self.apply_skin("dark")
        self.set_language((pai_config.get_language(pai_config.active_language) or {}).get("texts", {}))
        self._update_window_mode()
        self._refresh_send_button_state()

    def append_message(self, message: ChatMessage):
        self._flush_streaming_message()
        self._messages.append(message)
        self._add_message_row(message)

    def start_streaming_message(self, message: ChatMessage):
        self._flush_streaming_message()
        self._streaming_message = message
        self._streaming_row = self._add_message_row(ChatMessage(message.role, ""), streaming=True)
        self._streaming_visible_text = ""
        self._streaming_index = 0
        self._update_window_mode()
        self._scroll_messages_to_bottom()
        self._streaming_timer.start(22)

    def clear_messages(self):
        self._streaming_timer.stop()
        self._streaming_message = None
        self._streaming_row = None
        self._streaming_visible_text = ""
        self._streaming_index = 0
        self._messages.clear()
        while self.messages_layout.count():
            item = self.messages_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._update_window_mode()
        self._refresh_send_button_state()

    def sync_state(self, reply: SessionReply, skin: str):
        return

    def set_busy(self, busy: bool):
        self._busy = busy
        self.input.setEnabled(not busy)
        self.attach_button.setEnabled(not busy)
        self.attachments_list.setEnabled(not busy)
        self.send_button.setEnabled(not busy)
        self._refresh_send_button_state()

    def set_quick_commands(self, commands: list[dict]):
        return

    def _flush_streaming_message(self):
        if self._streaming_message is None:
            return
        self._streaming_timer.stop()
        self._messages.append(
            ChatMessage(
                self._streaming_message.role,
                self._streaming_message.text,
                attachments=self._streaming_message.attachments,
            )
        )
        if self._streaming_row is not None:
            self._streaming_row.set_text(self._streaming_message.text, streaming=False)
        self._streaming_message = None
        self._streaming_row = None
        self._streaming_visible_text = ""
        self._streaming_index = 0
        self._update_window_mode()
        self._refresh_send_button_state()

    def _advance_streaming(self):
        if self._streaming_message is None:
            self._streaming_timer.stop()
            return
        text = self._streaming_message.text
        if self._streaming_index >= len(text):
            self._flush_streaming_message()
            self._scroll_messages_to_bottom()
            return

        self._streaming_index = min(len(text), self._streaming_index + 1)
        self._streaming_visible_text = text[: self._streaming_index]
        if self._streaming_row is not None:
            self._streaming_row.set_text(self._streaming_visible_text, streaming=True)
        self._scroll_messages_to_bottom()

        if self._streaming_visible_text:
            last_char = self._streaming_visible_text[-1]
            if last_char in "，。！？；：,.!?;:\n":
                self._streaming_timer.start(96)
                return
            if last_char == " ":
                self._streaming_timer.start(30)
                return
        self._streaming_timer.start(18)

    def _add_message_row(self, message: ChatMessage, streaming: bool = False) -> ChatMessageRow:
        row = ChatMessageRow(message, streaming=streaming)
        self.messages_layout.addWidget(row)
        self._update_window_mode()
        self._scroll_messages_to_bottom()
        return row

    def _scroll_messages_to_bottom(self):
        scrollbar = self.messages_scroll.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _has_visible_messages(self) -> bool:
        return (
            bool(self._messages)
            or self._streaming_message is not None
            or bool(self._attachment_store.attachments())
        )

    def _update_window_mode(self):
        expanded = self._has_visible_messages()
        self.messages_scroll.setVisible(bool(self._messages) or self._streaming_message is not None)
        self.attachments_list.setVisible(bool(self._attachment_store.attachments()))
        target_size = self._expanded_size if expanded else self._compact_size
        self.setMinimumSize(target_size)
        if expanded:
            self.resize(max(self.width(), target_size.width()), max(self.height(), target_size.height()))
        else:
            self.resize(target_size)

    def _refresh_send_button_state(self):
        has_text = bool(self.input.text().strip())
        has_attachments = bool(self._attachment_store.attachments())
        if self._busy or has_text or has_attachments:
            bg = "rgba(10, 132, 255, 0.96)"
            border = "rgba(104, 177, 255, 0.98)"
            fg = "#ffffff"
        else:
            bg = "rgba(58, 58, 61, 0.98)"
            border = "rgba(96, 96, 102, 0.88)"
            fg = "#d8d8dc"

        self.send_button.setText("…" if self._busy else "↑")
        self.send_button.setStyleSheet(
            "QPushButton {"
            f"background: {bg};"
            f"border: 1px solid {border};"
            "border-radius: 20px;"
            f"color: {fg};"
            "font-size: 20px;"
            "font-weight: 700;"
            "padding: 0;"
            "}"
            "QPushButton:hover { background: rgba(82, 82, 88, 0.98); }"
            "QPushButton:disabled { color: rgba(255, 255, 255, 0.88); }"
        )

    def _emit_submit(self):
        text = self.input.text().strip()
        attachments = self._attachment_store.attachments()
        if not text and not attachments:
            return
        self.input.clear()
        self._clear_pending_attachments()
        self.submitted.emit(GuiChatSubmission(text=text, attachments=attachments))

    def focus_input(self):
        self.input.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    def set_language(self, texts: dict[str, str]):
        self._language_texts = dict(texts)
        self.setWindowTitle(texts.get("app_title", "Vox Pet"))
        self.input.setPlaceholderText(texts.get("chat_placeholder", "说点什么..."))
        self.attach_button.setToolTip(texts.get("upload_image_button", "上传图片"))
        self.send_button.setToolTip(texts.get("send_button", "发送"))
        self.set_busy(self._busy)

    def apply_skin(self, skin: str):
        self.setStyleSheet(
            "QMainWindow { background: transparent; }"
            f"#chatPanel {{{termi_panel_stylesheet(radius=26)}}}"
            "QListWidget {"
            "background: rgba(22, 24, 28, 0.72);"
            "border: 1px solid rgba(58, 62, 70, 0.82);"
            "border-radius: 16px;"
            "padding: 6px;"
            "}"
            "QFrame#attachmentChip {"
            "background: rgba(35, 36, 40, 0.96);"
            "border: 1px solid rgba(86, 90, 98, 0.82);"
            "border-radius: 14px;"
            "}"
            "QLabel#attachmentNameLabel {"
            "color: rgba(236, 236, 240, 0.94);"
            "font-size: 11px;"
            "font-weight: 600;"
            "background: transparent;"
            "border: none;"
            "}"
            "QPushButton#attachmentRemoveButton {"
            "background: rgba(79, 33, 33, 0.92);"
            "border: 1px solid rgba(153, 74, 74, 0.92);"
            "border-radius: 9px;"
            "color: #ffe4e4;"
            "font-size: 11px;"
            "font-weight: 700;"
            "padding: 0;"
            "}"
            "QPushButton#attachmentRemoveButton:hover { background: rgba(110, 39, 39, 0.96); }"
            "QLineEdit {"
            "background: rgba(44, 42, 43, 0.96);"
            "border: 1px solid rgba(96, 96, 102, 0.86);"
            "border-radius: 20px;"
            "padding: 0 14px;"
            "color: #f1f1f1;"
            "font-size: 14px;"
            "font-weight: 600;"
            "min-height: 40px;"
            "}"
            "QLineEdit:disabled { color: rgba(180, 180, 184, 0.85); }"
            "QPushButton#attachButton {"
            "background: rgba(29, 32, 36, 0.96);"
            "border: 1px solid rgba(86, 90, 98, 0.88);"
            "border-radius: 20px;"
            "color: #f1f1f1;"
            "font-size: 20px;"
            "font-weight: 700;"
            "padding: 0;"
            "}"
            "QPushButton#attachButton:hover { background: rgba(74, 79, 87, 0.98); }"
        )
        self._refresh_send_button_state()

    def add_attachment_files(self, paths: list[str]):
        for path in paths:
            try:
                added = self._attachment_store.add_files([path])
            except Exception as exc:
                self.attachment_error.emit(str(exc))
                continue
            for attachment in added:
                self.attachments_list.add_attachment(attachment)
        self._update_window_mode()
        self._refresh_send_button_state()

    def dragEnterEvent(self, event):
        if AttachmentListWidget._extract_paths(event):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if AttachmentListWidget._extract_paths(event):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event):
        paths = AttachmentListWidget._extract_paths(event)
        if paths:
            self.add_attachment_files(paths)
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    def _open_attachment_picker(self):
        selected, _filter = QFileDialog.getOpenFileNames(
            self,
            self._language_texts.get("upload_image_button", "上传图片"),
            "",
            "Images (*.png *.jpg *.jpeg *.webp)",
        )
        if selected:
            self.add_attachment_files(selected)

    def _remove_pending_attachment(self, attachment_id: str):
        self._attachment_store.remove(attachment_id)
        self.attachments_list.remove_attachment(attachment_id)
        self._update_window_mode()
        self._refresh_send_button_state()

    def _reorder_pending_attachments(self, ordered_ids: list[str]):
        self._attachment_store.reorder(ordered_ids)
        self._refresh_send_button_state()

    def _clear_pending_attachments(self):
        self._attachment_store.clear()
        self.attachments_list.clear()
        self._update_window_mode()
        self._refresh_send_button_state()


class GuiModelSettingsWindow(FramelessToolWindow):
    save_requested = Signal(object)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Vox Pet 模型设置")
        self._selected_profile = "codex"
        self._source_mode = "global"
        self._source_buttons: dict[str, QPushButton] = {}
        self._test_worker: ModelConnectionTestWorker | None = None
        self.setMinimumSize(QSize(640, 520))
        self.resize(760, 560)

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)

        self.panel = QFrame()
        self.panel.setObjectName("settingsPanel")
        make_shadow(self.panel, blur=34, y=10, alpha=78)
        outer.addWidget(self.panel)

        layout = QVBoxLayout(self.panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QHBoxLayout()
        header.setContentsMargins(18, 18, 18, 16)
        header.setSpacing(12)

        self.back_button = QPushButton("←")
        self.back_button.setObjectName("settingsBackButton")
        self.back_button.setFixedSize(40, 40)
        self.back_button.clicked.connect(self.hide)
        header.addWidget(self.back_button)

        title_stack = QVBoxLayout()
        title_stack.setContentsMargins(0, 0, 0, 0)
        title_stack.setSpacing(3)
        self.title_label = QLabel("模型设置")
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        title_stack.addWidget(self.title_label)

        self.subtitle_label = QLabel("仅影响桌宠 GUI，会话和 CLI 全局模型保持隔离。")
        self.subtitle_label.setObjectName("settingsSecondary")
        title_stack.addWidget(self.subtitle_label)
        header.addLayout(title_stack, 1)

        self.mode_badge = QLabel("跟随全局")
        self.mode_badge.setObjectName("settingsBadge")
        header.addWidget(self.mode_badge, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { background: transparent; width: 8px; margin: 2px 0 2px 0; }"
            "QScrollBar::handle:vertical {"
            "background: rgba(110, 110, 116, 0.42);"
            "border-radius: 4px;"
            "min-height: 24px;"
            "}"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }"
        )
        layout.addWidget(scroll, 1)

        body_container = QWidget()
        scroll.setWidget(body_container)
        body = QVBoxLayout(body_container)
        body.setContentsMargins(18, 6, 18, 18)
        body.setSpacing(12)

        self.mode_card = QFrame()
        self.mode_card.setObjectName("settingsModeCard")
        mode_layout = QVBoxLayout(self.mode_card)
        mode_layout.setContentsMargins(18, 18, 18, 18)
        mode_layout.setSpacing(10)
        mode_title = QLabel("模型来源")
        mode_title.setObjectName("settingsSection")
        mode_layout.addWidget(mode_title)

        self.source_label = QLabel("")
        self.source_label.setObjectName("settingsSource")
        self.source_label.setWordWrap(True)
        mode_layout.addWidget(self.source_label)

        self.global_label = QLabel("")
        self.global_label.setWordWrap(True)
        self.global_label.setObjectName("settingsSecondary")
        mode_layout.addWidget(self.global_label)

        self.warning_label = QLabel("")
        self.warning_label.setWordWrap(True)
        self.warning_label.hide()
        self.warning_label.setObjectName("settingsWarning")
        mode_layout.addWidget(self.warning_label)

        self.source_mode_widget = QWidget()
        self.source_mode_grid = QGridLayout(self.source_mode_widget)
        self.source_mode_grid.setContentsMargins(0, 0, 0, 0)
        self.source_mode_grid.setHorizontalSpacing(10)
        self.source_mode_grid.setVerticalSpacing(8)
        self.global_source_button = self._make_segment_button("跟随全局", "global", self._select_source_mode)
        self.independent_source_button = self._make_segment_button("独立配置", "independent", self._select_source_mode)
        self._source_buttons["global"] = self.global_source_button
        self._source_buttons["independent"] = self.independent_source_button
        mode_layout.addWidget(self.source_mode_widget)
        body.addWidget(self.mode_card)

        self.online_api_card = QFrame()
        self.online_api_card.setObjectName("settingsApiCard")
        api_card_layout = QVBoxLayout(self.online_api_card)
        api_card_layout.setContentsMargins(18, 18, 18, 18)
        api_card_layout.setSpacing(14)
        api_title = QLabel("API 模型")
        api_title.setObjectName("settingsSection")
        api_card_layout.addWidget(api_title)

        api_intro = QLabel("适合任何 OpenAI 兼容网关。填写 Base URL、API Key；如果网关要求显式 model，也可以直接填写。")
        api_intro.setObjectName("settingsSecondary")
        api_intro.setWordWrap(True)
        api_card_layout.addWidget(api_intro)

        self.profile_hint_label = QLabel("")
        self.profile_hint_label.setWordWrap(True)
        self.profile_hint_label.setObjectName("settingsSecondary")
        api_card_layout.addWidget(self.profile_hint_label)

        self.form_widget = QWidget()
        self.form_layout = QGridLayout(self.form_widget)
        self.form_layout.setContentsMargins(0, 0, 0, 0)
        self.form_layout.setHorizontalSpacing(12)
        self.form_layout.setVerticalSpacing(10)

        self.base_url_label = QLabel("Base URL")
        self.base_url_label.setObjectName("settingsFieldLabel")
        self.base_url_input = QLineEdit()
        self.base_url_input.setPlaceholderText("填写根地址、/v1 或完整 chat/completions 地址")
        self.base_url_input.setClearButtonEnabled(True)

        self.api_key_label = QLabel("API Key")
        self.api_key_label.setObjectName("settingsFieldLabel")
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setPlaceholderText("填写对应平台的 API Key")
        self.api_key_input.setClearButtonEnabled(True)

        self.model_label = QLabel("Model")
        self.model_label.setObjectName("settingsFieldLabel")
        self.model_input = QLineEdit()
        self.model_input.setPlaceholderText("可选，留空则默认使用 gpt-5-codex")
        self.model_input.setClearButtonEnabled(True)
        api_card_layout.addWidget(self.form_widget)

        self.api_hint_label = QLabel("根地址或 /v1 会自动补全为 /chat/completions；请求会带上 model 字段。")
        self.api_hint_label.setWordWrap(True)
        self.api_hint_label.setObjectName("settingsInlineHint")
        api_card_layout.addWidget(self.api_hint_label)

        self.test_button = QPushButton("测试连接")
        self.test_button.setObjectName("secondaryAction")
        self.test_button.clicked.connect(self._start_connection_test)
        api_card_layout.addWidget(self.test_button, 0, Qt.AlignmentFlag.AlignLeft)
        body.addWidget(self.online_api_card)

        self.json_card = QFrame()
        self.json_card.setObjectName("settingsJsonCard")
        json_card_layout = QVBoxLayout(self.json_card)
        json_card_layout.setContentsMargins(18, 18, 18, 18)
        json_card_layout.setSpacing(12)

        self.json_title_label = QLabel("配置 JSON")
        self.json_title_label.setObjectName("settingsSection")
        json_card_layout.addWidget(self.json_title_label)

        self.json_intro_label = QLabel("需要自定义 model 或一次性粘贴配置时，再使用这里。")
        self.json_intro_label.setObjectName("settingsSecondary")
        self.json_intro_label.setWordWrap(True)
        json_card_layout.addWidget(self.json_intro_label)

        self.json_actions_widget = QWidget()
        self.json_actions_grid = QGridLayout(self.json_actions_widget)
        self.json_actions_grid.setContentsMargins(0, 0, 0, 0)
        self.json_actions_grid.setHorizontalSpacing(10)
        self.json_actions_grid.setVerticalSpacing(8)

        self.json_sync_button = QPushButton("同步表单")
        self.json_sync_button.setObjectName("secondaryAction")
        self.json_sync_button.clicked.connect(self._sync_json_editor)

        self.json_apply_button = QPushButton("应用 JSON")
        self.json_apply_button.setObjectName("secondaryAction")
        self.json_apply_button.clicked.connect(self._apply_json_from_editor)
        json_card_layout.addWidget(self.json_actions_widget)

        self.json_editor = QPlainTextEdit()
        self.json_editor.setObjectName("settingsJsonEditor")
        self.json_editor.setMinimumHeight(190)
        self.json_editor.setPlaceholderText(
            '{\n  "baseUrl": "https://...",\n  "apiKey": "sk-...",\n  "model": "gpt-5-codex"\n}'
        )
        json_card_layout.addWidget(self.json_editor)

        self.json_hint_label = QLabel(
            "支持 baseUrl/base_url、apiKey/api_key、model、enabled；旧的 provider/profile/type 写法也兼容。"
        )
        self.json_hint_label.setObjectName("settingsSecondary")
        self.json_hint_label.setWordWrap(True)
        json_card_layout.addWidget(self.json_hint_label)
        body.addWidget(self.json_card)

        hint = QLabel("保存后只影响桌宠 GUI，不会修改 CLI 的 ~/.vox-code/config.json。")
        hint.setWordWrap(True)
        hint.setObjectName("settingsSecondary")
        body.addWidget(hint)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.hide()
        body.addWidget(self.status_label)

        self.footer_actions_widget = QWidget()
        self.footer_actions_grid = QGridLayout(self.footer_actions_widget)
        self.footer_actions_grid.setContentsMargins(0, 0, 0, 0)
        self.footer_actions_grid.setHorizontalSpacing(10)
        self.footer_actions_grid.setVerticalSpacing(8)

        self.save_button = QPushButton("保存并应用")
        self.save_button.setObjectName("primaryAction")
        self.save_button.clicked.connect(self._emit_save_request)

        self.close_button = QPushButton("关闭")
        self.close_button.setObjectName("secondaryAction")
        self.close_button.clicked.connect(self.hide)
        body.addWidget(self.footer_actions_widget)

        self.setStyleSheet(
            "QMainWindow { background: transparent; }"
            f"#settingsPanel {{{termi_panel_stylesheet(radius=26)}}}"
            "#settingsBackButton {"
            "background: rgba(29, 32, 36, 0.96);"
            "border: 1px solid rgba(86, 90, 98, 0.88);"
            "border-radius: 20px;"
            "color: #f1f1f1;"
            "font-size: 18px;"
            "font-weight: 700;"
            "}"
            "#settingsBackButton:hover { background: rgba(74, 79, 87, 0.98); }"
            "#settingsBadge {"
            "padding: 6px 12px;"
            "border-radius: 14px;"
            "background: rgba(29, 32, 36, 0.96);"
            "border: 1px solid rgba(86, 90, 98, 0.88);"
            "color: rgba(214, 214, 214, 0.92);"
            "font-size: 12px;"
            "font-weight: 700;"
            "}"
            "QLabel { color: #f1f1f1; font-size: 14px; }"
            "#settingsSource { color: #f1f1f1; font-size: 14px; font-weight: 700; }"
            "#settingsSecondary { color: rgba(164, 164, 164, 0.95); font-size: 12px; }"
            "#settingsSection { color: #f1f1f1; font-size: 15px; font-weight: 700; }"
            "#settingsFieldLabel { color: rgba(234, 234, 238, 0.96); font-size: 13px; font-weight: 700; }"
            "#settingsModeCard, #settingsApiCard, #settingsJsonCard {"
            "background: rgba(22, 24, 28, 0.96);"
            "border: 1px solid rgba(58, 62, 70, 0.92);"
            "border-radius: 16px;"
            "}"
            "#settingsWarning {"
            "padding: 10px 12px;"
            "border-radius: 12px;"
            "background: rgba(79, 33, 33, 0.42);"
            "border: 1px solid rgba(153, 74, 74, 0.46);"
            "color: #ffe4e4;"
            "font-size: 12px;"
            "font-weight: 600;"
            "}"
            "#settingsInlineHint {"
            "padding: 12px 14px;"
            "border-radius: 14px;"
            "background: rgba(35, 36, 40, 0.96);"
            "border: 1px solid rgba(96, 96, 102, 0.72);"
            "color: rgba(214, 214, 220, 0.92);"
            "font-size: 12px;"
            "font-weight: 600;"
            "}"
            "QLineEdit {"
            "background: rgba(44, 42, 43, 0.96);"
            "border: 1px solid rgba(96, 96, 102, 0.86);"
            "border-radius: 20px;"
            "padding: 0 14px;"
            "color: #f1f1f1;"
            "font-size: 14px;"
            "font-weight: 600;"
            "min-height: 42px;"
            "}"
            "QLineEdit:disabled { color: rgba(150, 150, 150, 0.82); }"
            "QPlainTextEdit#settingsJsonEditor {"
            "background: rgba(44, 42, 43, 0.96);"
            "border: 1px solid rgba(96, 96, 102, 0.86);"
            "border-radius: 16px;"
            "padding: 10px 12px;"
            "color: #f1f1f1;"
            "font-size: 13px;"
            "font-family: Menlo, Monaco, monospace;"
            "}"
            "QPushButton#primaryAction {"
            "background: rgba(10, 132, 255, 0.96);"
            "border: 1px solid rgba(104, 177, 255, 0.98);"
            "border-radius: 18px;"
            "padding: 10px 18px;"
            "color: #ffffff;"
            "font-size: 13px;"
            "font-weight: 700;"
            "min-height: 42px;"
            "}"
            "QPushButton#primaryAction:hover { background: rgba(43, 146, 255, 1); }"
            "QPushButton#secondaryAction {"
            "background: rgba(29, 32, 36, 0.96);"
            "border: 1px solid rgba(86, 90, 98, 0.88);"
            "border-radius: 18px;"
            "padding: 10px 16px;"
            "color: #f1f1f1;"
            "font-size: 13px;"
            "font-weight: 700;"
            "min-height: 42px;"
            "}"
            "QPushButton#secondaryAction:hover { background: rgba(74, 79, 87, 0.98); }"
            "QPushButton:disabled { color: rgba(170, 170, 170, 0.82); }"
        )
        self._select_source_mode("global")
        self._relayout_responsive_sections()
        self.base_url_input.textChanged.connect(lambda _text: self._refresh_json_preview_if_clean())
        self.api_key_input.textChanged.connect(lambda _text: self._refresh_json_preview_if_clean())
        self.model_input.textChanged.connect(lambda _text: self._refresh_json_preview_if_clean())
        self.model_input.textChanged.connect(lambda _text: self._refresh_profile_hint())

    def load_state(
        self,
        config: GuiModelConfig,
        source_text: str,
        global_text: str,
        warning_text: str = "",
    ):
        profile_meta = gui_model_profile_meta(config.provider)
        self.update_runtime_labels(source_text, global_text, warning_text)
        self._select_source_mode("independent" if config.enabled else "global")
        self._selected_profile = profile_meta["id"]
        self.base_url_input.setText(config.base_url)
        self.api_key_input.setText(config.api_key)
        self.model_input.setText(config.model.strip())
        self.clear_status()
        self._refresh_profile_hint()
        self._sync_json_editor()

    def update_runtime_labels(self, source_text: str, global_text: str, warning_text: str = ""):
        self.source_label.setText(f"当前来源: {source_text}")
        self.global_label.setText(f"全局模型: {global_text}")
        if warning_text:
            self.warning_label.setText(warning_text)
            self.warning_label.show()
        else:
            self.warning_label.hide()

    def selected_config(self) -> GuiModelConfig:
        return GuiModelConfig(
            enabled=self._source_mode == "independent",
            provider="codex",
            model=self.model_input.text().strip(),
            base_url=normalize_gui_model_base_url(self.base_url_input.text().strip()),
            api_key=self.api_key_input.text().strip(),
        )

    def set_status(self, message: str, error: bool = False):
        self.status_label.setText(message)
        self.status_label.setStyleSheet(
            "padding: 10px 12px;"
            "border-radius: 12px;"
            f"background: {'rgba(79, 33, 33, 0.42)' if error else 'rgba(33, 63, 49, 0.42)'};"
            f"border: 1px solid {'rgba(153, 74, 74, 0.46)' if error else 'rgba(84, 153, 121, 0.46)'};"
            f"color: {'#ffe4e4' if error else '#dff7e7'};"
            "font-size: 12px;"
            "font-weight: 600;"
        )
        self.status_label.show()

    def clear_status(self):
        self.status_label.clear()
        self.status_label.hide()

    def _emit_save_request(self):
        self.save_requested.emit(self.selected_config())

    def _update_form_enabled_state(self, enabled: bool):
        for widget in (self.base_url_input, self.api_key_input, self.model_input):
            widget.setEnabled(enabled)
        self.test_button.setEnabled(enabled and self._test_worker is None)
        self.json_sync_button.setEnabled(enabled)
        self.json_apply_button.setEnabled(enabled)
        self.json_editor.setEnabled(enabled)
        self.online_api_card.setEnabled(enabled)
        self.json_card.setEnabled(enabled)

    def _select_profile(self, profile_id: str, preserve_override: bool = False):
        meta = gui_model_profile_meta(profile_id)
        self._selected_profile = meta["id"]
        self._refresh_profile_hint()

    def _refresh_profile_hint(self):
        meta = gui_model_profile_meta(self._selected_profile)
        model = self.model_input.text().strip()
        if model:
            self.profile_hint_label.setText(
                f"当前网关类型: {meta['label']}。将使用你填写的 model: `{model}`。"
                " 图片上传仅对支持视觉的 OpenAI 兼容模型生效。"
            )
            return
        self.profile_hint_label.setText(
            f"当前网关类型: {meta['label']}。留空时会默认使用 `{default_model_for(meta['id'])}`。"
            " 图片上传仅对支持视觉的 OpenAI 兼容模型生效。"
        )

    def _select_source_mode(self, mode: str):
        self._source_mode = mode if mode in {"global", "independent"} else "global"
        for current_mode, button in self._source_buttons.items():
            button.setStyleSheet(self._segment_button_stylesheet(current_mode == self._source_mode))
        self._update_form_enabled_state(self._source_mode == "independent")
        self.mode_badge.setText("GUI 独立" if self._source_mode == "independent" else "跟随全局")

    def _start_connection_test(self):
        config = self.selected_config()
        if not config.enabled:
            self.set_status("当前是跟随全局模式，无需测试独立配置。", error=True)
            return
        self.clear_status()
        self.test_button.setText("测试中...")
        self.test_button.setEnabled(False)
        self._test_worker = ModelConnectionTestWorker(config)
        self._test_worker.completed.connect(self._handle_test_success)
        self._test_worker.failed.connect(self._handle_test_failure)
        self._test_worker.finished.connect(self._cleanup_test_worker)
        self._test_worker.start()

    def _handle_test_success(self, message: str):
        self.set_status(message)

    def _handle_test_failure(self, message: str):
        self.set_status(f"连接失败: {message}", error=True)

    def _cleanup_test_worker(self):
        self._test_worker = None
        self.test_button.setText("测试连接")
        self.test_button.setEnabled(self._source_mode == "independent")

    def _sync_json_editor(self):
        config = self.selected_config()
        payload = {
            "baseUrl": config.base_url,
            "apiKey": config.api_key,
            "model": config.model,
            "enabled": config.enabled,
        }
        self.json_editor.setPlainText(json.dumps(payload, ensure_ascii=False, indent=2))

    def _apply_json_from_editor(self):
        try:
            loaded = load_gui_model_config_from_json(self.json_editor.toPlainText(), self.selected_config())
        except Exception as exc:
            self.set_status(f"JSON 配置无效: {exc}", error=True)
            return
        self._select_source_mode("independent" if loaded.enabled else "global")
        self._select_profile(loaded.provider, preserve_override=True)
        self.base_url_input.setText(loaded.base_url)
        self.api_key_input.setText(loaded.api_key)
        self.model_input.setText(loaded.model)
        self._refresh_profile_hint()
        self.set_status("JSON 配置已载入，确认后点击保存并应用。")

    def _refresh_json_preview_if_clean(self):
        if not self.json_editor.toPlainText().strip():
            self._sync_json_editor()

    def _relayout_responsive_sections(self):
        compact = self.width() < 720
        self._rebuild_segment_grid(
            self.source_mode_grid,
            [self.global_source_button, self.independent_source_button],
            compact,
        )
        self._rebuild_form_layout(compact)
        self._rebuild_button_grid(
            self.json_actions_grid,
            [self.json_sync_button, self.json_apply_button],
            compact,
        )
        self._rebuild_button_grid(
            self.footer_actions_grid,
            [self.save_button, self.close_button],
            compact,
            align_end=not compact,
        )

    def _rebuild_segment_grid(self, layout: QGridLayout, buttons: list[QPushButton], compact: bool):
        self._clear_grid_layout(layout)
        if compact:
            for row, button in enumerate(buttons):
                layout.addWidget(button, row, 0)
        else:
            for col, button in enumerate(buttons):
                layout.addWidget(button, 0, col)
            layout.setColumnStretch(len(buttons), 1)

    def _rebuild_form_layout(self, compact: bool):
        self._clear_grid_layout(self.form_layout)
        if compact:
            self.form_layout.addWidget(self.base_url_label, 0, 0)
            self.form_layout.addWidget(self.base_url_input, 1, 0)
            self.form_layout.addWidget(self.api_key_label, 2, 0)
            self.form_layout.addWidget(self.api_key_input, 3, 0)
            self.form_layout.addWidget(self.model_label, 4, 0)
            self.form_layout.addWidget(self.model_input, 5, 0)
            return
        self.form_layout.setColumnMinimumWidth(0, 88)
        self.form_layout.setColumnStretch(1, 1)
        self.form_layout.addWidget(self.base_url_label, 0, 0)
        self.form_layout.addWidget(self.base_url_input, 0, 1)
        self.form_layout.addWidget(self.api_key_label, 1, 0)
        self.form_layout.addWidget(self.api_key_input, 1, 1)
        self.form_layout.addWidget(self.model_label, 2, 0)
        self.form_layout.addWidget(self.model_input, 2, 1)

    def _rebuild_button_grid(
        self,
        layout: QGridLayout,
        buttons: list[QPushButton],
        compact: bool,
        align_end: bool = False,
    ):
        self._clear_grid_layout(layout)
        if compact:
            for row, button in enumerate(buttons):
                layout.addWidget(button, row, 0)
            layout.setColumnStretch(0, 1)
            return
        start_col = 1 if align_end else 0
        if align_end:
            layout.setColumnStretch(0, 1)
        for index, button in enumerate(buttons):
            layout.addWidget(button, 0, start_col + index)

    def _clear_grid_layout(self, layout: QGridLayout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(layout.parentWidget())

    def _make_segment_button(self, text: str, value: str, handler):
        button = QPushButton(text)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setProperty("segmentValue", value)
        button.setMinimumHeight(42)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        button.clicked.connect(lambda _checked=False, current=value: handler(current))
        button.setStyleSheet(self._segment_button_stylesheet(False))
        return button

    def _segment_button_stylesheet(self, active: bool) -> str:
        bg = "rgba(10, 132, 255, 0.96)" if active else "rgba(29, 32, 36, 0.96)"
        border = "rgba(104, 177, 255, 0.98)" if active else "rgba(86, 90, 98, 0.88)"
        fg = "#ffffff" if active else "rgba(236, 236, 236, 0.95)"
        hover_bg = "rgba(43, 146, 255, 1)" if active else "rgba(74, 79, 87, 0.98)"
        return (
            "QPushButton {"
            f"background: {bg};"
            f"border: 1px solid {border};"
            "border-radius: 18px;"
            "padding: 9px 16px;"
            f"color: {fg};"
            "font-size: 13px;"
            "font-weight: 700;"
            "}"
            f"QPushButton:hover {{ background: {hover_bg}; }}"
            "QPushButton:disabled { color: rgba(170, 170, 170, 0.8); }"
        )

    def resizeEvent(self, event):
        self._relayout_responsive_sections()
        super().resizeEvent(event)


# ---------------------------------------------------------------------------
# Pet Manager — 可视化宠物管理窗口
# ---------------------------------------------------------------------------

class PetManagerWindow(FramelessToolWindow):
    """宠物管理界面 — 预览、浏览、切换、导入宠物。

    类似 TermiPet 的宠物选择面板：
    - 左侧大预览区
    - 右侧宠物信息
    - 下方卡片网格
    - 底部导入按钮
    """

    pet_selected = Signal(str)       # pet_id
    import_requested = Signal()
    delete_requested = Signal(str)   # pet_id

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Pet Manager")
        self.setFixedSize(480, 520)
        self._pets: list[PetPackage] = []
        self._current_pet_id = ""
        self._skin = "glass"

        root = QWidget(self)
        root.setObjectName("petManagerRoot")
        root.setStyleSheet(termi_panel_stylesheet(20))
        self.setCentralWidget(root)

        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # -- Title bar --
        title_bar = QWidget()
        title_bar.setFixedHeight(48)
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(20, 0, 12, 0)
        title_label = QLabel("Pet Manager")
        title_label.setStyleSheet("color: #f0f0f0; font-size: 16px; font-weight: 700;")
        title_layout.addWidget(title_label)
        title_layout.addStretch()
        close_btn = QPushButton("×")
        close_btn.setFixedSize(28, 28)
        close_btn.setStyleSheet(
            "QPushButton { background: rgba(200,80,70,0.7); border: none; "
            "border-radius: 14px; color: #fff; font-size: 16px; font-weight: 700; }"
            "QPushButton:hover { background: rgba(200,80,70,1); }"
        )
        close_btn.clicked.connect(self.hide)
        title_layout.addWidget(close_btn)

        layout.addWidget(title_bar)

        # -- Preview area --
        preview_section = QWidget()
        preview_section.setFixedHeight(160)
        preview_layout = QHBoxLayout(preview_section)
        preview_layout.setContentsMargins(24, 12, 24, 12)

        self._preview = _PetManagerPreview(120, 120)
        self._preview.setFixedSize(120, 120)
        make_shadow(self._preview, blur=20, y=4, alpha=40)
        preview_layout.addWidget(self._preview, 0, Qt.AlignmentFlag.AlignCenter)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(6)
        self._name_label = QLabel()
        self._name_label.setStyleSheet("color: #f0f0f0; font-size: 15px; font-weight: 700;")
        self._desc_label = QLabel()
        self._desc_label.setStyleSheet("color: rgba(200,200,200,0.85); font-size: 12px;")
        self._desc_label.setWordWrap(True)
        self._kind_label = QLabel()
        self._kind_label.setStyleSheet("color: rgba(180,180,180,0.7); font-size: 11px;")
        info_layout.addWidget(self._name_label)
        info_layout.addWidget(self._desc_label)
        info_layout.addWidget(self._kind_label)
        info_layout.addStretch()
        preview_layout.addLayout(info_layout)

        layout.addWidget(preview_section)

        # -- Separator --
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: rgba(86,90,98,0.5);")
        layout.addWidget(sep)

        # -- Pet grid --
        grid_label = QLabel("All Pets")
        grid_label.setStyleSheet("color: #ccc; font-size: 13px; font-weight: 600; padding: 8px 24px 0;")
        layout.addWidget(grid_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }"
            "QScrollBar:vertical { width: 4px; }"
            "QScrollBar::handle:vertical { background: rgba(120,120,120,0.4); border-radius: 2px; }"
        )
        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent;")
        self._grid_layout = QGridLayout(scroll_content)
        self._grid_layout.setContentsMargins(20, 8, 20, 8)
        self._grid_layout.setSpacing(8)
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll, 1)

        # -- Bottom bar --
        bottom = QWidget()
        bottom.setFixedHeight(56)
        bottom_layout = QHBoxLayout(bottom)
        bottom_layout.setContentsMargins(20, 8, 20, 8)
        import_btn = QPushButton("  Import Pet  ")
        import_btn.setStyleSheet(
            "QPushButton { background: rgba(10,132,255,0.9); border: none; "
            "border-radius: 16px; padding: 8px 18px; color: #fff; font-size: 13px; font-weight: 600; }"
            "QPushButton:hover { background: rgba(10,132,255,1); }"
        )
        import_btn.clicked.connect(self.import_requested.emit)
        bottom_layout.addWidget(import_btn)
        bottom_layout.addStretch()
        layout.addWidget(bottom)

        self._card_widgets: list[PetCardWidget] = []

    def load_pets(self, pets: list[PetPackage], current_pet_id: str, skin: str):
        """刷新宠物列表和预览。"""
        self._pets = list(pets)
        self._current_pet_id = current_pet_id
        self._skin = skin
        self._rebuild_grid()
        self._update_preview()

    def _rebuild_grid(self):
        # Clear old cards
        for card in self._card_widgets:
            self._grid_layout.removeWidget(card)
            card.deleteLater()
        self._card_widgets.clear()

        cols = 4
        for idx, package in enumerate(self._pets):
            show_delete = package.kind == "sprite"
            card = PetCardWidget(
                package, skin=self._skin,
                selected=(package.id == self._current_pet_id),
                show_delete=show_delete,
            )
            card.clicked.connect(lambda _p=package.id: self._on_card_clicked(_p))
            if show_delete:
                card.delete_requested.connect(lambda _p=package.id: self.delete_requested.emit(_p))
            self._grid_layout.addWidget(card, idx // cols, idx % cols)
            self._card_widgets.append(card)

    def _on_card_clicked(self, pet_id: str):
        if pet_id != self._current_pet_id:
            self.pet_selected.emit(pet_id)

    def _update_preview(self):
        package = next((p for p in self._pets if p.id == self._current_pet_id), None)
        if package is None and self._pets:
            package = self._pets[0]
        if package is not None:
            self._preview.set_package(package)
            self._preview.set_skin(self._skin)
            self._name_label.setText(package.display_name)
            self._desc_label.setText(package.description)
            kind_text = "Drawn" if package.kind == "drawn" else "Sprite"
            self._kind_label.setText(f"Type: {kind_text}")
        # Update card selection states
        for card in self._card_widgets:
            card.set_selected(card.package_id == self._current_pet_id)


class _PetManagerPreview(QWidget):
    """宠物管理器专用预览 — 居中绘制宠物。"""

    def __init__(self, width: int, height: int):
        super().__init__()
        self.setFixedSize(width, height)
        self._package: PetPackage | None = None
        self._skin = "glass"

    def set_package(self, package: PetPackage):
        self._package = package
        self.update()

    def set_skin(self, skin: str):
        self._skin = skin
        self.update()

    def paintEvent(self, _event):
        if self._package is None:
            return
        from PySide6.QtGui import QPainter
        from .widgets import draw_pet_body, SKIN_PALETTES

        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(self.rect(), Qt.GlobalColor.transparent)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        palette = SKIN_PALETTES[self._skin]
        painter.save()
        scale_x = self.width() / 252.0
        scale_y = self.height() / 220.0
        scale = min(scale_x, scale_y)
        painter.translate(
            (self.width() - 252 * scale) / 2,
            (self.height() - 220 * scale) / 2,
        )
        painter.scale(scale, scale)
        draw_pet_body(painter, self.rect(), self._package, palette,
                      status_action=0, thinking=False, blink=False, float_phase=0)
        painter.restore()


class _PersonaCard(QWidget):
    """Selectable persona card — label, description, selection state."""

    clicked = Signal(str)

    def __init__(self, persona_id: str, label: str, description: str,
                 selected: bool = False):
        super().__init__()
        self._id = persona_id
        self._label = label
        self._description = description
        self._selected = selected
        self.setFixedSize(440, 64)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_selected(self, selected: bool):
        self._selected = selected
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._id)
            event.accept()
            return
        super().mousePressEvent(event)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect().adjusted(1, 1, -1, -1)

        if self._selected:
            border = QColor(104, 177, 255)
            bg = QColor(22, 28, 38)
            dot_color = QColor(10, 132, 255)
        else:
            border = QColor(58, 62, 70)
            bg = QColor(16, 18, 22, 238)
            dot_color = QColor(86, 90, 98)

        painter.setPen(QPen(border, 2 if self._selected else 1))
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, 12, 12)

        # Selection dot
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(dot_color)
        painter.drawEllipse(QPoint(22, 32), 5, 5)

        # Label
        label_font = QFont("Menlo")
        if not label_font.exactMatch():
            label_font = QFont()
        label_font.setPointSize(12)
        label_font.setBold(True)
        painter.setFont(label_font)
        painter.setPen(QColor(236, 236, 236))
        painter.drawText(QRect(38, 6, 390, 26),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         self._label)

        # Description
        if self._description:
            desc_font = QFont()
            desc_font.setPointSize(10)
            painter.setFont(desc_font)
            painter.setPen(QColor(165, 165, 170))
            painter.drawText(QRect(38, 30, 390, 26),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             self._description)


class PersonalityWindow(FramelessToolWindow):
    """Personality/persona settings window.

    Lists all personas from catalog as selectable cards,
    with a read-only prompt preview at the bottom.
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Vox Pet 性格设置")
        self.setMinimumSize(QSize(480, 420))
        self.resize(480, 460)
        self._cards: list[_PersonaCard] = []
        self._current_id = ""

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)

        panel = QFrame()
        panel.setObjectName("personalityPanel")
        make_shadow(panel, blur=34, y=10, alpha=78)
        outer.addWidget(panel)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QHBoxLayout()
        header.setContentsMargins(18, 18, 18, 16)
        header.setSpacing(12)

        back_button = QPushButton("←")
        back_button.setObjectName("settingsBackButton")
        back_button.setFixedSize(40, 40)
        back_button.clicked.connect(self.hide)
        header.addWidget(back_button)

        title_label = QLabel("性格设置")
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        title_label.setFont(title_font)
        header.addWidget(title_label)
        header.addStretch(1)

        self.badge = QLabel("")
        self.badge.setObjectName("settingsBadge")
        header.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)

        # Scroll area for persona cards
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { background: transparent; width: 8px; margin: 2px 0 2px 0; }"
            "QScrollBar::handle:vertical {"
            "background: rgba(110, 110, 116, 0.42);"
            "border-radius: 4px;"
            "min-height: 24px;"
            "}"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }"
        )

        scroll_content = QWidget()
        self._scroll_layout = QVBoxLayout(scroll_content)
        self._scroll_layout.setContentsMargins(18, 4, 18, 4)
        self._scroll_layout.setSpacing(8)
        self._scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll, 1)

        # Prompt editor
        preview_card = QFrame()
        preview_card.setObjectName("promptCard")
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(18, 14, 18, 14)
        preview_layout.setSpacing(8)

        prompt_title = QLabel("当前 Prompt")
        prompt_title.setStyleSheet(
            "color: #f1f1f1; font-size: 13px; font-weight: 700; background: transparent;"
        )
        preview_layout.addWidget(prompt_title)

        self._prompt_edit = QPlainTextEdit()
        self._prompt_edit.setObjectName("personalityPromptEditor")
        self._prompt_edit.setMinimumHeight(100)
        self._prompt_edit.setMaximumHeight(160)
        self._prompt_edit.setPlaceholderText("选择一个性格预设，然后可以在这里自定义 Prompt")
        preview_layout.addWidget(self._prompt_edit)

        # Prompt actions
        prompt_actions = QHBoxLayout()
        prompt_actions.setSpacing(8)
        self._save_prompt_btn = QPushButton("保存修改")
        self._save_prompt_btn.setObjectName("secondaryAction")
        self._save_prompt_btn.clicked.connect(self._save_custom_prompt)
        prompt_actions.addWidget(self._save_prompt_btn)

        self._reset_prompt_btn = QPushButton("恢复默认")
        self._reset_prompt_btn.setObjectName("secondaryAction")
        self._reset_prompt_btn.clicked.connect(self._reset_custom_prompt)
        prompt_actions.addWidget(self._reset_prompt_btn)

        self._prompt_status = QLabel("")
        self._prompt_status.setStyleSheet(
            "color: rgba(164, 164, 164, 0.95); font-size: 11px; background: transparent;"
        )
        prompt_actions.addWidget(self._prompt_status, 1)

        preview_layout.addLayout(prompt_actions)

        layout.addWidget(preview_card)

        # Close button
        footer = QHBoxLayout()
        footer.setContentsMargins(18, 10, 18, 18)
        footer.setSpacing(10)
        footer.addStretch(1)
        close_btn = QPushButton("关闭")
        close_btn.setObjectName("secondaryAction")
        close_btn.clicked.connect(self.hide)
        footer.addWidget(close_btn)
        layout.addLayout(footer)

        self.apply_skin("dark")

    def load_personas(self, personas: list[dict], current_id: str):
        """Refresh the persona list and selection."""
        self._current_id = current_id
        self._rebuild_cards(personas)
        self._update_prompt(preview=not bool(self._cards))
        self.badge.setText(
            next((p["label"] for p in personas if p["id"] == current_id), "")
        )

    def _rebuild_cards(self, personas: list[dict]):
        for card in self._cards:
            self._scroll_layout.removeWidget(card)
            card.deleteLater()
        self._cards.clear()

        for persona in personas:
            pid = str(persona.get("id", "")).strip()
            label = str(persona.get("label", pid)).strip() or pid
            description = str(persona.get("description", "")).strip()
            selected = pid == self._current_id
            card = _PersonaCard(pid, label, description, selected=selected)
            if pid != "__placeholder__":
                card.clicked.connect(self._on_card_clicked)
            self._scroll_layout.addWidget(card)
            self._cards.append(card)

    def _on_card_clicked(self, persona_id: str):
        """Switch persona and update UI."""
        pai_config.set_active_persona(persona_id)
        self._current_id = persona_id
        for card in self._cards:
            card.set_selected(card._id == persona_id)
        self._update_prompt()
        persona = pai_config.get_persona(persona_id)
        self.badge.setText(str(persona.get("label", persona_id)) if persona else persona_id)

    def _update_prompt(self, preview: bool = False):
        if preview:
            self._prompt_edit.setPlainText("")
            return
        persona = pai_config.get_persona(self._current_id)
        if persona is None:
            self._prompt_edit.setPlainText("")
            return
        prompt = str(persona.get("prompt", "")).strip()
        self._prompt_edit.setPlainText(prompt)
        self._prompt_status.setText("")

    @staticmethod
    def _catalog_path() -> Path:
        override = (
            __import__("os")
            .environ.get("VOX_CODE_HOME", "")
            .strip()
            or __import__("os").environ.get("VOX_HOME", "").strip()
        )
        if override:
            return Path(override).expanduser() / "catalog.json"
        return Path.home() / ".vox-code" / "catalog.json"

    def _save_custom_prompt(self):
        """Save edited prompt to catalog.json as per-id override."""
        text = self._prompt_edit.toPlainText().strip()
        if not text:
            self._prompt_status.setText("Prompt 不能为空")
            self._prompt_status.setStyleSheet(
                "color: #ffe4e4; font-size: 11px; background: transparent;"
            )
            return

        path = self._catalog_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        # Load existing catalog overrides
        existing: dict = {}
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                existing = {}

        personas_override: list[dict] = existing.get("personas", [])
        found = False
        for p in personas_override:
            if p.get("id") == self._current_id:
                p["prompt"] = text
                found = True
                break
        if not found:
            personas_override.append({"id": self._current_id, "prompt": text})

        existing["personas"] = personas_override
        try:
            path.write_text(
                json.dumps(existing, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            self._prompt_status.setText(f"保存失败: {exc}")
            self._prompt_status.setStyleSheet(
                "color: #ffe4e4; font-size: 11px; background: transparent;"
            )
            return

        # Reload catalog so pai_config picks up the change
        pai_config.reload_catalog()
        self._prompt_status.setText("已保存 ✓")
        self._prompt_status.setStyleSheet(
            "color: #7fdb9a; font-size: 11px; background: transparent;"
        )

    def _reset_custom_prompt(self):
        """Remove per-id override from catalog.json, restore default."""
        path = self._catalog_path()
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                existing = {}

            personas_override = [
                p for p in existing.get("personas", []) if p.get("id") != self._current_id
            ]
            existing["personas"] = personas_override
            try:
                path.write_text(
                    json.dumps(existing, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except OSError:
                pass

        pai_config.reload_catalog()
        self._update_prompt()
        self._prompt_status.setText("已恢复默认 ✓")
        self._prompt_status.setStyleSheet(
            "color: rgba(164, 164, 164, 0.95); font-size: 11px; background: transparent;"
        )

    def apply_skin(self, skin: str):
        self.setStyleSheet(
            "QMainWindow { background: transparent; }"
            "#personalityPanel {"
            "background: rgba(10, 12, 16, 244);"
            "border: 1px solid rgba(72, 76, 84, 220);"
            "border-radius: 26px;"
            "}"
            "#settingsBackButton {"
            "background: rgba(29, 32, 36, 0.96);"
            "border: 1px solid rgba(86, 90, 98, 0.88);"
            "border-radius: 20px;"
            "color: #f1f1f1;"
            "font-size: 18px;"
            "font-weight: 700;"
            "}"
            "#settingsBackButton:hover { background: rgba(74, 79, 87, 0.98); }"
            "#settingsBadge {"
            "padding: 6px 12px;"
            "border-radius: 14px;"
            "background: rgba(29, 32, 36, 0.96);"
            "border: 1px solid rgba(86, 90, 98, 0.88);"
            "color: rgba(214, 214, 214, 0.92);"
            "font-size: 12px;"
            "font-weight: 700;"
            "}"
            "#promptCard {"
            "background: rgba(22, 24, 28, 0.96);"
            "border: 1px solid rgba(58, 62, 70, 0.92);"
            "border-radius: 16px;"
            "margin: 0 18px;"
            "}"
            "QPlainTextEdit#personalityPromptEditor {"
            "background: rgba(44, 42, 43, 0.96);"
            "border: 1px solid rgba(96, 96, 102, 0.86);"
            "border-radius: 12px;"
            "padding: 10px 12px;"
            "color: #d8d8dc;"
            "font-size: 12px;"
            "font-family: Menlo, Monaco, monospace;"
            "}"
            "QLabel { color: #f1f1f1; font-size: 14px; }"
            "QPushButton#secondaryAction {"
            "background: rgba(29, 32, 36, 0.96);"
            "border: 1px solid rgba(86, 90, 98, 0.88);"
            "border-radius: 18px;"
            "padding: 10px 16px;"
            "color: #f1f1f1;"
            "font-size: 13px;"
            "font-weight: 700;"
            "min-height: 42px;"
            "}"
            "QPushButton#secondaryAction:hover { background: rgba(74, 79, 87, 0.98); }"
        )
