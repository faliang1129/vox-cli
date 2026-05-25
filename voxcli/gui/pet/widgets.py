"""Core widgets for the desktop pet UI."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPainterPath, QPen, QPixmap, QPolygon
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from ...runtime import SessionController, SessionReply
from ..macos_window import tune_window_for_desktop_pet
from .base import make_shadow
from .data import BUILTIN_PETS, PetPackage, SKIN_PALETTES, SkinPalette


class SpriteSheetRenderer:
    def __init__(self):
        self._cache: dict[str, tuple[QPixmap, int, int, int]] = {}

    def frame(self, package: PetPackage | None, action: int, tick: int) -> QPixmap | None:
        if package is None or not package.has_spritesheet:
            return None
        sprite_path = package.spritesheet_path
        cached = self._cache.get(sprite_path)
        if cached is None:
            pixmap = QPixmap(sprite_path)
            if pixmap.isNull():
                return None
            row_count = 9
            frame_height = pixmap.height() // row_count if row_count else 0
            if frame_height <= 0:
                return None
            frame_width = frame_height
            frame_count = max(1, pixmap.width() // frame_width)
            cached = (pixmap, frame_width, frame_height, frame_count)
            self._cache[sprite_path] = cached

        pixmap, frame_width, frame_height, frame_count = cached
        safe_action = max(0, min(action, 8))
        frame_index = tick % frame_count
        return pixmap.copy(frame_index * frame_width, safe_action * frame_height, frame_width, frame_height)


SPRITE_RENDERER = SpriteSheetRenderer()


class SpeechBubble(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("speechBubble")
        self._skin = "glass"
        make_shadow(self, blur=26, y=10, alpha=44)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        self.badge = QLabel("VOX")
        self.badge.setObjectName("speechBubbleBadge")
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge.setFixedSize(42, 20)
        layout.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignLeft)
        self.label = QLabel("点我打开面板，和 Vox 聊天")
        self.label.setObjectName("speechBubbleText")
        self.label.setWordWrap(True)
        layout.addWidget(self.label)
        self.apply_skin("glass")
        self.hide()

    def show_message(self, text: str):
        import textwrap

        preview = textwrap.shorten(" ".join(text.split()), width=56, placeholder="...")
        self.label.setText(preview or "Vox 在这里。")
        self.adjustSize()
        self.show()

    def apply_skin(self, skin: str):
        self._skin = skin if skin in SKIN_PALETTES else "glass"
        self.setStyleSheet(
            "#speechBubble {"
            "background: qlineargradient(x1:0, y1:0, x2:1, y2:1,"
            "stop:0 rgba(24, 26, 31, 0.98), stop:1 rgba(37, 40, 47, 0.96));"
            "border: 1px solid rgba(86, 90, 98, 0.88);"
            "border-radius: 20px;"
            "}"
            "#speechBubbleBadge {"
            "background: rgba(10, 132, 255, 0.96);"
            "border: 1px solid rgba(104, 177, 255, 0.98);"
            "border-radius: 10px;"
            "color: #ffffff;"
            "font-size: 10px;"
            "font-weight: 800;"
            "letter-spacing: 0.5px;"
            "padding: 0 6px;"
            "}"
            "#speechBubbleText {"
            "background: transparent;"
            "color: #f1f1f1;"
            "font-size: 13px;"
            "font-weight: 600;"
            "line-height: 1.35;"
            "}"
        )


class PillLabel(QLabel):
    def __init__(self, text: str):
        super().__init__(text)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            "QLabel {"
            "padding: 6px 12px;"
            "background: rgba(255, 248, 239, 205);"
            "border: 1px solid rgba(220, 187, 138, 190);"
            "border-radius: 14px;"
            "color: #6b5636;"
            "font-size: 12px;"
            "font-weight: 700;"
            "}"
        )


# ---------------------------------------------------------------------------
# 共享宠物绘制函数（供 PetWidget + PetPreviewWidget 复用）
# ---------------------------------------------------------------------------

def draw_pet_body(painter: QPainter, rect: QRect, package: PetPackage,
                  palette: SkinPalette, status_action: int = 0,
                  thinking: bool = False, blink: bool = False,
                  float_phase: int = 0):
    """在给定的 painter/rect 区域内绘制宠物身体。

    参数与 PetWidget 内部状态对应，由调用方决定传入值。
    """
    lift = 2 if (float_phase % 4) in {1, 2} else 0
    if package.id == "pixel-cat":
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

    sprite = SPRITE_RENDERER.frame(package, status_action, float_phase)
    if sprite is not None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(palette.pet_shadow)
        painter.drawEllipse(QRect(62, 178, 128, 22))
        target = QRect(54, 44 - lift, 144, 144)
        painter.drawPixmap(target, sprite)
        return

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(palette.pet_shadow)
    painter.drawEllipse(QRect(62, 178, 128, 22))
    painter.setBrush(palette.pet_glow)
    painter.drawEllipse(QRect(42, 40 - lift, 170, 128))

    body_rect = QRect(62, 76 - lift, 128, 104)
    face_rect = QRect(50, 36 - lift, 152, 120)
    body_radius = 46
    if package.id == "mochi":
        body_rect = QRect(66, 84 - lift, 120, 92)
        face_rect = QRect(46, 40 - lift, 160, 122)
        body_radius = 52
    elif package.id == "pixel-cat":
        body_rect = QRect(66, 82 - lift, 122, 96)
        face_rect = QRect(54, 42 - lift, 146, 112)
        body_radius = 12

    offset_x = 0
    if status_action == 1:
        offset_x = -4 if float_phase in {0, 2} else 4
    elif status_action == 2:
        offset_x = -2 if float_phase in {0, 1} else 2
    elif status_action == 8:
        lift += 4
    body_rect.translate(offset_x, 0)
    face_rect.translate(offset_x, 0)

    left_ear = QPainterPath()
    left_ear.moveTo(82 + offset_x, 54 - lift)
    left_ear.lineTo(102 + offset_x, 18 - lift)
    left_ear.lineTo(122 + offset_x, 58 - lift)
    left_ear.closeSubpath()

    right_ear = QPainterPath()
    right_ear.moveTo(130 + offset_x, 58 - lift)
    right_ear.lineTo(150 + offset_x, 18 - lift)
    right_ear.lineTo(170 + offset_x, 54 - lift)
    right_ear.closeSubpath()

    base_color = palette.pet_base
    outline_color = palette.pet_outline
    blush_color = palette.pet_blush
    charm_color = palette.pet_charm
    highlight_color = palette.pet_highlight
    inner_ear_color = QColor(255, 226, 213)
    collar_color = QColor(101, 190, 146)
    if thinking:
        collar_color = QColor(255, 193, 94)

    if package.id == "terminal-cat":
        collar_color = QColor(93, 214, 171)
    elif package.id == "pixel-cat":
        base_color = QColor(248, 220, 146)
        outline_color = QColor(110, 72, 24)
        blush_color = QColor(255, 168, 122, 72)
        charm_color = QColor(255, 237, 166)
        highlight_color = QColor(255, 248, 214, 32)
        inner_ear_color = QColor(224, 143, 109)
        collar_color = QColor(255, 133, 61)
    elif package.id == "wizard-claude":
        base_color = QColor(238, 234, 246)
        outline_color = QColor(112, 102, 145)
        blush_color = QColor(203, 185, 246, 64)
        charm_color = QColor(255, 235, 161)
        highlight_color = QColor(255, 255, 255, 74)
        inner_ear_color = QColor(209, 171, 216)
        collar_color = QColor(114, 98, 216)
    elif package.id == "mochi":
        base_color = QColor(253, 250, 244)
        outline_color = QColor(226, 214, 202)
        blush_color = QColor(255, 197, 189, 92)
        charm_color = QColor(247, 214, 154)
        highlight_color = QColor(255, 255, 255, 96)
        inner_ear_color = QColor(244, 204, 197)
        collar_color = QColor(240, 164, 112)

    if status_action == 5:
        collar_color = QColor(217, 88, 72)
    elif status_action == 4:
        collar_color = QColor(255, 187, 66)
    elif status_action == 8:
        collar_color = QColor(255, 215, 84)

    painter.setBrush(base_color)
    painter.setPen(QPen(outline_color, 2))
    painter.drawPath(left_ear)
    painter.drawPath(right_ear)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(inner_ear_color)
    painter.drawPolygon(QPolygon([QPoint(90 + offset_x, 50 - lift), QPoint(103 + offset_x, 27 - lift), QPoint(114 + offset_x, 52 - lift)]))
    painter.drawPolygon(QPolygon([QPoint(138 + offset_x, 52 - lift), QPoint(149 + offset_x, 27 - lift), QPoint(161 + offset_x, 50 - lift)]))

    painter.setBrush(base_color)
    painter.setPen(QPen(outline_color, 2))
    painter.drawRoundedRect(body_rect, body_radius, body_radius)
    painter.drawEllipse(face_rect)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(blush_color)
    painter.drawEllipse(QRect(78 + offset_x, 105 - lift, 22, 12))
    painter.drawEllipse(QRect(152 + offset_x, 105 - lift, 22, 12))

    eye_y = 92 - lift
    if status_action == 6:
        painter.setPen(QPen(palette.pet_eye, 3))
        painter.drawLine(95 + offset_x, eye_y, 108 + offset_x, eye_y)
        painter.drawLine(143 + offset_x, eye_y, 156 + offset_x, eye_y)
        painter.setPen(QPen(palette.pet_mouth, 2))
        painter.drawText(QRect(166 + offset_x, 58 - lift, 30, 20), "Z")
    elif status_action == 5:
        painter.setPen(QPen(palette.pet_eye, 3))
        painter.drawLine(96 + offset_x, eye_y - 3, 108 + offset_x, eye_y + 7)
        painter.drawLine(108 + offset_x, eye_y - 3, 96 + offset_x, eye_y + 7)
        painter.drawLine(142 + offset_x, eye_y - 3, 154 + offset_x, eye_y + 7)
        painter.drawLine(154 + offset_x, eye_y - 3, 142 + offset_x, eye_y + 7)
    elif status_action == 3:
        painter.setPen(QPen(palette.pet_eye, 3))
        painter.drawArc(QRect(95 + offset_x, eye_y - 2, 14, 10), 0, 180 * 16)
        painter.drawArc(QRect(141 + offset_x, eye_y - 2, 14, 10), 0, 180 * 16)
    elif thinking:
        painter.setPen(QPen(palette.pet_eye, 3))
        painter.drawLine(97 + offset_x, eye_y, 109 + offset_x, eye_y + 3)
        painter.drawLine(141 + offset_x, eye_y + 3, 153 + offset_x, eye_y)
    elif blink:
        painter.setPen(QPen(palette.pet_eye, 3))
        painter.drawLine(97 + offset_x, eye_y, 108 + offset_x, eye_y)
        painter.drawLine(141 + offset_x, eye_y, 152 + offset_x, eye_y)
    else:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(palette.pet_eye)
        left_eye = QRect(96 + offset_x, eye_y - 5, 11, 15)
        right_eye = QRect(142 + offset_x, eye_y - 5, 11, 15)
        if status_action == 4:
            left_eye = QRect(95 + offset_x, eye_y - 6, 13, 18)
            right_eye = QRect(141 + offset_x, eye_y - 6, 13, 18)
        painter.drawEllipse(left_eye)
        painter.drawEllipse(right_eye)

    painter.setBrush(palette.pet_nose)
    painter.drawEllipse(QRect(116 + offset_x, 104 - lift, 19, 12))
    painter.setPen(QPen(palette.pet_mouth, 3))
    mouth_rect = QRect(104 + offset_x, 108 - lift, 44, 28)
    mouth_start = 210 * 16
    mouth_span = 120 * 16
    if status_action == 3:
        mouth_rect = QRect(104 + offset_x, 106 - lift, 46, 30)
        mouth_start = 200 * 16
        mouth_span = 140 * 16
    elif status_action == 5:
        mouth_rect = QRect(108 + offset_x, 118 - lift, 36, 18)
        mouth_start = 30 * 16
        mouth_span = 120 * 16
    painter.drawArc(mouth_rect, mouth_start, mouth_span)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(collar_color)
    collar_rect = QRect(92 + offset_x, 134 - lift, 68, 20)
    if package.id == "mochi":
        collar_rect = QRect(96 + offset_x, 132 - lift, 62, 18)
    painter.drawRoundedRect(collar_rect, 10, 10)
    painter.setBrush(charm_color)
    if package.id == "wizard-claude":
        star = QPolygon(
            [
                QPoint(125 + offset_x, 138 - lift),
                QPoint(128 + offset_x, 144 - lift),
                QPoint(135 + offset_x, 145 - lift),
                QPoint(130 + offset_x, 149 - lift),
                QPoint(132 + offset_x, 156 - lift),
                QPoint(125 + offset_x, 152 - lift),
                QPoint(118 + offset_x, 156 - lift),
                QPoint(120 + offset_x, 149 - lift),
                QPoint(115 + offset_x, 145 - lift),
                QPoint(122 + offset_x, 144 - lift),
            ]
        )
        painter.drawPolygon(star)
    else:
        painter.drawEllipse(QRect(121 + offset_x, 138 - lift, 9, 9))

    painter.setBrush(highlight_color)
    painter.drawEllipse(QRect(76 + offset_x, 54 - lift, 18, 12))
    if package.id == "wizard-claude":
        hat = QPainterPath()
        hat.moveTo(118 + offset_x, 12 - lift)
        hat.lineTo(96 + offset_x, 60 - lift)
        hat.lineTo(154 + offset_x, 60 - lift)
        hat.closeSubpath()
        painter.setPen(QPen(QColor(76, 61, 138), 2))
        painter.setBrush(QColor(110, 89, 201))
        painter.drawPath(hat)
        painter.setBrush(QColor(255, 221, 112))
        painter.drawEllipse(QRect(118 + offset_x, 30 - lift, 8, 8))
    elif package.id == "pixel-cat":
        painter.setPen(QPen(QColor(110, 72, 24), 3))
        painter.drawRect(QRect(82 + offset_x, 52 - lift, 12, 10))
        painter.drawRect(QRect(156 + offset_x, 52 - lift, 12, 10))

    if status_action == 4:
        painter.setPen(QPen(QColor(255, 189, 59), 3))
        painter.drawText(QRect(166 + offset_x, 56 - lift, 20, 26), "!")
    elif status_action == 8:
        painter.setPen(QPen(QColor(255, 212, 82), 3))
        painter.drawText(QRect(168 + offset_x, 54 - lift, 24, 24), "*")


# ---------------------------------------------------------------------------
# 宠物预览组件（只读、静态，适合放置在设置窗口）
# ---------------------------------------------------------------------------

class PetPreviewWidget(QWidget):
    """静态宠物预览 — 用于 Pet Manager 等管理界面。

    固定尺寸 120x120，显示宠物的 idle 常态，无动画、无交互。
    """

    def __init__(self, package: PetPackage | None = None, skin: str = "glass"):
        super().__init__()
        self._package = package or BUILTIN_PETS[0]
        self._skin = skin if skin in SKIN_PALETTES else "glass"

    def set_package(self, package: PetPackage):
        self._package = package
        self.update()

    def set_skin(self, skin: str):
        self._skin = skin if skin in SKIN_PALETTES else "glass"
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(self.rect(), Qt.GlobalColor.transparent)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        palette = SKIN_PALETTES[self._skin]
        painter.save()
        # Scale the 252x220 drawing to fit our preview rect
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


# ---------------------------------------------------------------------------
# 宠物卡片组件（用于宠物列表网格）
# ---------------------------------------------------------------------------

class PetCardWidget(QWidget):
    """宠物选择卡片 — 小预览 + 名称。

    Signals:
        clicked(): 卡片被点击
        delete_requested(): 删除按钮被点击（仅 imported pets）
    """

    clicked = Signal()
    delete_requested = Signal()

    def __init__(self, package: PetPackage, skin: str = "glass",
                 selected: bool = False, show_delete: bool = False):
        super().__init__()
        self._package = package
        self._skin = skin
        self._selected = selected
        self._show_delete = show_delete
        self.setFixedSize(100, 120)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    @property
    def package_id(self) -> str:
        return self._package.id

    def set_selected(self, selected: bool):
        self._selected = selected
        self.update()

    def set_skin(self, skin: str):
        self._skin = skin
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        palette = SKIN_PALETTES[self._skin]

        # Background
        border_color = QColor(255, 193, 94) if self._selected else QColor(72, 76, 84, 200)
        painter.setPen(QPen(border_color, 2 if self._selected else 1))
        painter.setBrush(QColor(16, 18, 22, 230))
        painter.drawRoundedRect(QRect(1, 1, self.width() - 2, self.height() - 2), 12, 12)

        # Pet preview (64x64 area)
        painter.save()
        preview_rect = QRect(18, 8, 64, 64)
        scale_x = 64 / 252.0
        scale_y = 64 / 220.0
        scale = min(scale_x, scale_y)
        painter.translate(
            preview_rect.x() + (preview_rect.width() - 252 * scale) / 2,
            preview_rect.y() + (preview_rect.height() - 220 * scale) / 2,
        )
        painter.scale(scale, scale)
        draw_pet_body(painter, QRect(0, 0, 252, 220), self._package, palette,
                      status_action=0, thinking=False, blink=False, float_phase=0)
        painter.restore()

        # Name label
        painter.setPen(QColor(220, 220, 220))
        font = painter.font()
        font.setPixelSize(11)
        font.setBold(True)
        painter.setFont(font)
        name = self._package.display_name
        painter.drawText(QRect(4, 76, self.width() - 8, 20),
                         Qt.AlignmentFlag.AlignCenter, name)

        # Delete button (small X in top-right corner)
        if self._show_delete:
            painter.setPen(QPen(QColor(200, 80, 70), 2))
            painter.drawText(QRect(self.width() - 22, 4, 18, 18),
                             Qt.AlignmentFlag.AlignCenter, "×")


# ---------------------------------------------------------------------------
# 主宠物窗口部件
# ---------------------------------------------------------------------------

class PetWidget(QWidget):
    toggled = Signal()
    request_quit = Signal()
    hover_changed = Signal(bool)
    position_changed = Signal()
    cycle_pet_requested = Signal()
    context_menu_requested = Signal(object)

    def __init__(self, controller: SessionController):
        super().__init__()
        self._controller = controller
        self._package = BUILTIN_PETS[0]
        self._drag_offset: QPoint | None = None
        self._press_global_pos: QPoint | None = None
        self._thinking = False
        self._blink = False
        self._float_phase = 0
        self._status_action = 0
        self._skin = "glass"
        self._bubble_timer = QTimer(self)
        self._bubble_timer.setInterval(9000)
        self._bubble_timer.timeout.connect(self._hide_bubble)

        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.setInterval(30000)
        self._idle_timer.timeout.connect(self._go_sleep)

        self._saved_action = 0

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.NoDropShadowWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(252, 220)

        self.bubble = SpeechBubble()
        self.bubble.setParent(self)
        self.bubble.setGeometry(QRect(14, 4, 212, 92))

        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(450)
        self._anim_timer.timeout.connect(self._tick)
        self._anim_timer.start()

        self._mode_label = QLabel(self._controller.mode.upper(), self)
        self._mode_label.setGeometry(QRect(86, 170, 82, 26))
        self._mode_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._mode_label.hide()
        self.set_skin("glass")
        self._idle_timer.start()

    def showEvent(self, event):
        super().showEvent(event)
        tune_window_for_desktop_pet(self, role="pet")

    def update_session_state(self, reply: SessionReply):
        return

    def set_thinking(self, thinking: bool):
        self._thinking = thinking
        self._status_action = 1 if thinking else 0  # 1=run for spritesheet
        if thinking:
            self._idle_timer.stop()
        else:
            self._idle_timer.start()
        self.update()

    def speak(self, text: str):
        self.bubble.show_message(text)
        self._bubble_timer.start()

    def _hide_bubble(self):
        self.bubble.hide()

    def happy(self):
        self._status_action = 3
        QTimer.singleShot(1000, self._reset_action)
        self.update()

    def _go_sleep(self):
        """Idle timeout → sleeping pose."""
        if self._status_action == 0 and not self._thinking:
            self._status_action = 6
            self.update()

    def _reset_idle_timer(self):
        """Reset idle countdown and wake from sleep."""
        self._idle_timer.stop()
        self._idle_timer.start()
        if self._status_action == 6:
            self._status_action = 0
            self.update()

    def _tick(self):
        self._blink = not self._blink
        self._float_phase += 1
        self.update()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_global_pos = event.globalPosition().toPoint()
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._saved_action = self._status_action
            self._reset_idle_timer()
            event.accept()
            return
        if event.button() == Qt.MouseButton.RightButton:
            self.context_menu_requested.emit(event.globalPosition().toPoint())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            self.position_changed.emit()
            # Show "move" (2) once dragged past threshold
            start = self._press_global_pos
            if start and (event.globalPosition().toPoint() - start).manhattanLength() > 10:
                self._status_action = 2
                self.update()
            self._reset_idle_timer()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            moved = 0
            if self._press_global_pos is not None:
                moved = (event.globalPosition().toPoint() - self._press_global_pos).manhattanLength()
            if self._drag_offset is not None and moved < 10:
                # Click → happy (3) + open chat
                self.happy()
                QTimer.singleShot(60, self.toggled.emit)
            else:
                # Drag ended → restore saved state
                saved = getattr(self, '_saved_action', 0)
                self._status_action = saved if not self._thinking else 1
                self.update()
            self._drag_offset = None
            self._press_global_pos = None
            self._reset_idle_timer()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(self.rect(), Qt.GlobalColor.transparent)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        palette = SKIN_PALETTES[self._skin]
        draw_pet_body(painter, self.rect(), self._package, palette,
                      status_action=self._status_action, thinking=self._thinking,
                      blink=self._blink, float_phase=self._float_phase)

    def enterEvent(self, event):
        self._reset_idle_timer()
        self.hover_changed.emit(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hover_changed.emit(False)
        super().leaveEvent(event)

    def set_skin(self, skin: str):
        self._skin = skin if skin in SKIN_PALETTES else "glass"
        self.bubble.apply_skin(self._skin)
        self.update()

    def set_pet_package(self, package: PetPackage):
        self._package = package
        self.update()

    def celebrate(self):
        self._status_action = 8
        QTimer.singleShot(1400, self._reset_action)
        self.update()

    def alert(self):
        self._status_action = 4
        QTimer.singleShot(1200, self._reset_action)
        self.update()

    def error(self):
        self._status_action = 5
        QTimer.singleShot(1600, self._reset_action)
        self.update()

    def _reset_action(self):
        self._status_action = 1 if self._thinking else 0  # 1=run
        self.update()
