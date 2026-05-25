"""Shared Qt helpers for the desktop pet UI."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QMouseEvent
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QMainWindow, QWidget

from ..macos_window import tune_window_for_desktop_pet


def make_shadow(widget: QWidget, blur: int = 36, y: int = 10, alpha: int = 56):
    shadow = QGraphicsDropShadowEffect(widget)
    shadow.setBlurRadius(blur)
    shadow.setOffset(0, y)
    shadow.setColor(QColor(53, 33, 15, alpha))
    widget.setGraphicsEffect(shadow)


def termi_panel_stylesheet(radius: int = 24) -> str:
    return (
        f"background: rgba(10, 12, 16, 244);"
        f"border: 1px solid rgba(72, 76, 84, 220);"
        f"border-radius: {radius}px;"
    )


class FramelessToolWindow(QMainWindow):
    """Shared drag-to-move, hide-on-close behavior for floating panels."""

    def __init__(self):
        super().__init__()
        self._drag_offset = None
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def showEvent(self, event):
        super().showEvent(event)
        tune_window_for_desktop_pet(self, role="panel")

    def closeEvent(self, event):
        event.ignore()
        self.hide()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = None
            event.accept()
            return
        super().mouseReleaseEvent(event)
