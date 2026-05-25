"""Top-level coordinator for the desktop pet UI."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap, QPolygon
from PySide6.QtWidgets import QApplication, QFileDialog, QMenu, QSystemTrayIcon, QWidget

from ...chat import GuiChatSubmission
from ...config import GuiModelConfig, GuiModelConfigStore, pai_config
from ...llm.factory import create_from_config, create_from_provider_config
from ...runtime import SessionController, SessionReply
from ..macos_window import configure_app_for_desktop_pet
from .data import (
    BUILTIN_PETS,
    SKIN_PALETTES,
    ChatMessage,
    GuiStateStore,
    PetPackage,
    PetPackageStore,
    gui_model_profile_label,
)
from .widgets import PetWidget
from .windows import ChatWindow, CommandWindow, FloatingActionBar, GuiModelSettingsWindow, PetManagerWindow, PersonalityWindow, StatusCardWidget
from .workers import SessionWorker


class PetCoordinator(QWidget):
    def __init__(self):
        super().__init__()
        self._gui_model_store = GuiModelConfigStore()
        self._gui_model_config = GuiModelConfig()
        self._gui_model_source = "跟随全局"
        self._gui_model_warning = ""
        self.controller = SessionController(
            llm_client=self._build_initial_gui_llm_client(),
            allow_model_switch_commands=False,
        )
        self._state_store = GuiStateStore()
        self._pet_store = PetPackageStore()
        self._settings_window: GuiModelSettingsWindow | None = None
        self._pet_manager: PetManagerWindow | None = None
        self._personality_window: PersonalityWindow | None = None
        self.current_skin = self._state_store.load_skin()
        self.current_pet_id = self._state_store.load_selected_pet()
        self.current_language = pai_config.active_language
        self._pets: list[PetPackage] = []
        self.worker: SessionWorker | None = None
        self._toolbar_hide_timer = QTimer(self)
        self._toolbar_hide_timer.setSingleShot(True)
        self._toolbar_hide_timer.setInterval(220)
        self._toolbar_hide_timer.timeout.connect(self._hide_toolbar_if_idle)

        self.pet = PetWidget(self.controller)
        self.chat = ChatWindow(self.controller)
        self.commands = CommandWindow()
        self.toolbar = FloatingActionBar()
        self.status_card = StatusCardWidget()
        self._pet_state = "idle"
        self.pet.toggled.connect(self.toggle_chat)
        self.pet.request_quit.connect(QApplication.instance().quit)
        self.pet.hover_changed.connect(self._on_pet_hover_changed)
        self.pet.position_changed.connect(self._sync_toolbar_position)
        self.pet.position_changed.connect(self._sync_status_card_position)
        self.pet.cycle_pet_requested.connect(self._cycle_pet_action)
        self.pet.context_menu_requested.connect(self._show_pet_context_menu)
        self.chat.submitted.connect(self.submit_line)
        self.chat.attachment_error.connect(self._handle_attachment_error)
        self.commands.submitted.connect(self.submit_line)
        self.toolbar.chat_requested.connect(self.toggle_chat)
        self.toolbar.commands_requested.connect(self.toggle_commands)
        self.toolbar.hover_changed.connect(self._on_toolbar_hover_changed)

        self.status_card.set_status(
            mode=self.controller.mode,
            model_provider=self.controller.provider_name,
            model_name=self.controller.model_name,
            state=self._pet_state,
        )
        self._reload_pets()
        self._apply_pet(self.current_pet_id, announce=False)

        self.tray = QSystemTrayIcon(self._build_tray_icon(), self)
        self.tray.setToolTip("Vox Pet")
        self.tray.activated.connect(self._on_tray_activated)
        self._tray_menu = self._build_tray_menu()
        self.tray.setContextMenu(self._tray_menu)
        self.tray.show()

        self._place_windows()
        self._apply_skin(self.current_skin)
        self._apply_language(self.current_language, announce=False)
        self.pet.show()
        self._sync_toolbar_position()
        self.commands.set_quick_commands(pai_config.quick_commands())
        self._sync_reply_state(SessionReply(text="", mode=self.controller.mode, presentation_mode=self.controller.presentation_mode))
        self.pet.speak(self._text("ready_bubble", "主人，我已经准备好了。"))
        QTimer.singleShot(160, self._initial_reveal)

    def toggle_chat(self):
        if self.chat.isVisible():
            self.chat.hide()
            self.toolbar.set_active_panel("")
            return
        self.commands.hide()
        self._position_floating_panel(self.chat, x_shift=120, y_gap=34)
        self.chat.show()
        self.chat.raise_()
        self.chat.focus_input()
        self.toolbar.set_active_panel("chat")
        self._show_toolbar()

    def toggle_commands(self):
        if self.commands.isVisible():
            self.commands.hide()
            self.toolbar.set_active_panel("")
            return
        self.chat.hide()
        self._position_floating_panel(self.commands, x_shift=92, y_gap=34)
        self.commands.show()
        self.commands.raise_()
        self.toolbar.set_active_panel("commands")
        self._show_toolbar()

    def reveal_pet(self, reset_position: bool = False):
        if reset_position:
            self._place_windows()
        self._sync_toolbar_position()
        self._sync_status_card_position()
        self.pet.show()
        self.pet.raise_()
        self.pet.speak(self._text("reveal_bubble", "主人，我在这里。"))

    def submit_line(self, line: str | GuiChatSubmission):
        if self.worker is not None and self.worker.isRunning():
            return
        submission = line if isinstance(line, GuiChatSubmission) else GuiChatSubmission(text=line)
        if not self.chat.isVisible():
            self._position_floating_panel(self.chat, x_shift=120, y_gap=34)
            self.chat.show()
        self.chat.raise_()
        self.chat.focus_input()
        self.toolbar.set_active_panel("chat")
        self.chat.append_message(
            ChatMessage("user", submission.text, attachments=submission.attachments)
        )
        self.chat.set_busy(True)
        self._pet_state = "thinking"
        self.pet.set_thinking(True)
        self._update_status_card(state="thinking")
        self.worker = SessionWorker(self.controller, submission)
        self.worker.completed.connect(self._handle_reply)
        self.worker.failed.connect(self._handle_failure)
        self.worker.start()

    def _handle_reply(self, reply: SessionReply):
        submitted_line = ""
        if self.worker is not None:
            submitted = self.worker._line
            submitted_line = submitted.text.strip() if isinstance(submitted, GuiChatSubmission) else submitted.strip()
        self.chat.set_busy(False)
        self.pet.set_thinking(False)
        self._sync_reply_state(reply)

        role = "error" if reply.kind == "error" else "assistant"
        if submitted_line == "/clear" and reply.kind != "error":
            self.chat.clear_messages()
            self._pet_state = "celebrate"
            self.pet.speak(reply.text)
            self.pet.celebrate()
            self._update_status_card(state="celebrate", bubble_text=reply.text)
            self.worker = None
            return

        if reply.text:
            if role == "assistant":
                self.chat.start_streaming_message(ChatMessage(role, reply.text))
            else:
                self.chat.append_message(ChatMessage(role, reply.text))
            self.pet.speak(reply.text)
            if reply.kind == "assistant":
                self._pet_state = "celebrate"
                self.pet.celebrate()
            elif reply.kind == "error":
                self._pet_state = "error"
                self.pet.error()
            else:
                self._pet_state = "alert"
                self.pet.alert()
            self._update_status_card(state=self._pet_state, bubble_text=reply.text)
            self._show_toolbar()

            # Reset to idle after short delay
            QTimer.singleShot(2000, self._reset_pet_state)
        if reply.should_quit:
            QApplication.instance().quit()
        self.worker = None

    def _reset_pet_state(self):
        self._pet_state = "idle"
        self._update_status_card(state="idle")

    def _handle_failure(self, message: str):
        self.chat.set_busy(False)
        self.pet.set_thinking(False)
        self.chat.append_message(ChatMessage("error", message))
        self._pet_state = "error"
        self._update_status_card(state="error", bubble_text=message)
        self.pet.speak(message)
        self.pet.error()
        QTimer.singleShot(2000, self._reset_pet_state)
        self.worker = None

    def _handle_attachment_error(self, message: str):
        self.chat.append_message(ChatMessage("error", message))
        self._pet_state = "error"
        self._update_status_card(state="error", bubble_text=message)
        self.pet.speak(message)
        self.pet.error()
        QTimer.singleShot(2000, self._reset_pet_state)

    def _apply_controller_reply(self, reply: SessionReply):
        self._sync_reply_state(reply)
        self._refresh_tray_menu()
        self.pet.speak(reply.text)
        self.pet.alert()

    def _sync_reply_state(self, reply: SessionReply):
        self.pet.update_session_state(reply)
        self.chat.sync_state(reply, self.current_skin)
        self.toolbar.sync_state(
            reply.mode,
            reply.presentation_mode,
            self.current_skin,
            self._current_pet().display_name,
        )

    def _on_mode_changed(self, mode: str):
        self._apply_controller_reply(self.controller.set_mode(mode))

    def _on_style_changed(self, style: str):
        self._apply_controller_reply(self.controller.set_presentation_mode(style))

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason):
        if reason in {
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        }:
            self.toggle_chat()

    def _build_tray_menu(self) -> QMenu:
        menu = QMenu()
        show_pet = QAction("显示桌宠", menu)
        show_pet.triggered.connect(self.reveal_pet)
        menu.addAction(show_pet)

        reset_pet = QAction("重置桌宠位置", menu)
        reset_pet.triggered.connect(lambda: self.reveal_pet(reset_position=True))
        menu.addAction(reset_pet)

        show_chat = QAction("打开面板", menu)
        show_chat.triggered.connect(self.toggle_chat)
        menu.addAction(show_chat)

        show_commands = QAction("快捷命令", menu)
        show_commands.triggered.connect(self.toggle_commands)
        menu.addAction(show_commands)

        menu.addSeparator()
        model_source = QAction(f"模型来源: {self._gui_model_source}", menu)
        model_source.setEnabled(False)
        menu.addAction(model_source)

        pet_manager = QAction("宠物管理", menu)
        pet_manager.triggered.connect(self.open_pet_manager)
        menu.addAction(pet_manager)

        model_settings = QAction("模型设置", menu)
        model_settings.triggered.connect(self.open_model_settings)
        menu.addAction(model_settings)

        personality = QAction("性格设置", menu)
        personality.triggered.connect(self.open_personality_settings)
        menu.addAction(personality)

        menu.addSeparator()
        self._populate_configuration_menu(menu)

        menu.addSeparator()
        quit_action = QAction("退出", menu)
        quit_action.triggered.connect(QApplication.instance().quit)
        menu.addAction(quit_action)
        return menu

    def _build_tray_icon(self) -> QIcon:
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(QColor(205, 192, 176), 2))
        painter.setBrush(QColor(248, 244, 236))
        painter.drawEllipse(QRect(10, 14, 44, 38))
        painter.drawPolygon(QPolygon([QPoint(18, 20), QPoint(24, 6), QPoint(31, 22)]))
        painter.drawPolygon(QPolygon([QPoint(33, 22), QPoint(40, 6), QPoint(46, 20)]))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(59, 64, 72))
        painter.drawEllipse(QRect(23, 28, 5, 8))
        painter.drawEllipse(QRect(36, 28, 5, 8))
        painter.setBrush(QColor(239, 164, 145))
        painter.drawEllipse(QRect(29, 34, 6, 4))
        painter.end()
        return QIcon(pixmap)

    def _place_windows(self):
        screen = QApplication.primaryScreen()
        if screen is None:
            self.pet.move(80, 80)
            self.chat.move(140, 120)
            self.commands.move(120, 80)
            self._sync_toolbar_position()
            return
        area = screen.availableGeometry()
        pet_x = max(area.left() + 16, area.right() - self.pet.width() - 24)
        pet_y = max(area.top() + 16, area.bottom() - self.pet.height() - 24)
        self.pet.move(pet_x, pet_y)
        self._position_floating_panel(self.chat, x_shift=120, y_gap=34)
        self._position_floating_panel(self.commands, x_shift=92, y_gap=34)
        self._sync_toolbar_position()

    def _position_floating_panel(self, window: QWidget, x_shift: int, y_gap: int):
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        pet_pos = self.pet.pos()
        x = pet_pos.x() - window.width() + x_shift
        y = pet_pos.y() - window.height() - y_gap
        x = max(area.left() + 24, min(x, area.right() - window.width() - 24))
        y = max(area.top() + 24, min(y, area.bottom() - window.height() - 24))
        window.move(x, y)

    def _sync_toolbar_position(self):
        toolbar_size = self.toolbar.sizeHint()
        pet_pos = self.pet.pos()
        x = pet_pos.x() - max(0, (toolbar_size.width() - self.pet.width()) // 2)
        y = pet_pos.y() - toolbar_size.height() - 12
        self.toolbar.move(x, y)

    def _sync_status_card_position(self):
        card_size = self.status_card.sizeHint()
        toolbar_size = self.toolbar.sizeHint()
        pet_pos = self.pet.pos()
        card_y = pet_pos.y() - card_size.height() - toolbar_size.height() - 18
        card_x = pet_pos.x() - max(0, (card_size.width() - self.pet.width()) // 2)
        screen = QApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            card_x = max(area.left() + 8, min(card_x, area.right() - card_size.width() - 8))
            card_y = max(area.top() + 8, card_y)
        self.status_card.move(card_x, card_y)

    def _show_toolbar(self):
        self._toolbar_hide_timer.stop()
        self._sync_toolbar_position()
        self.toolbar.show()
        self.toolbar.raise_()
        self._sync_status_card_position()
        self.status_card.show()
        self.status_card.raise_()

    def _hide_toolbar_if_idle(self):
        if self.chat.isVisible() or self.commands.isVisible():
            return
        if self.pet.underMouse() or self.toolbar.underMouse() or self.status_card.underMouse():
            return
        self.toolbar.hide()
        self.status_card.hide()

    def _update_status_card(self, state: str = "", bubble_text: str = ""):
        self.status_card.set_status(
            mode=self.controller.mode,
            model_provider=self.controller.provider_name,
            model_name=self.controller.model_name,
            state=state or self._pet_state,
            bubble_text=bubble_text,
        )

    def _on_pet_hover_changed(self, hovering: bool):
        if hovering:
            self._show_toolbar()
            return
        self._toolbar_hide_timer.start()

    def _on_toolbar_hover_changed(self, hovering: bool):
        if hovering:
            self._toolbar_hide_timer.stop()
            return
        self._toolbar_hide_timer.start()

    def _show_pet_context_menu(self, global_pos: QPoint):
        menu = QMenu()
        open_chat = QAction("打开聊天", menu)
        open_chat.triggered.connect(self.toggle_chat)
        menu.addAction(open_chat)

        open_commands = QAction("快捷命令", menu)
        open_commands.triggered.connect(self.toggle_commands)
        menu.addAction(open_commands)

        menu.addSeparator()
        pet_manager = QAction("宠物管理", menu)
        pet_manager.triggered.connect(self.open_pet_manager)
        menu.addAction(pet_manager)

        model_settings = QAction("模型设置", menu)
        model_settings.triggered.connect(self.open_model_settings)
        menu.addAction(model_settings)

        personality = QAction("性格设置", menu)
        personality.triggered.connect(self.open_personality_settings)
        menu.addAction(personality)

        menu.addSeparator()
        pets_menu = menu.addMenu("宠物")
        for package in self._pets:
            action = QAction(package.display_name, pets_menu)
            action.setCheckable(True)
            action.setChecked(package.id == self.current_pet_id)
            action.triggered.connect(lambda _checked=False, value=package.id: self._apply_pet(value))
            pets_menu.addAction(action)

        import_pet = QAction("导入宠物", menu)
        import_pet.triggered.connect(self._import_pet_action)
        menu.addAction(import_pet)

        menu.addSeparator()
        reset_pet = QAction("重置桌宠位置", menu)
        reset_pet.triggered.connect(lambda: self.reveal_pet(reset_position=True))
        menu.addAction(reset_pet)

        hide_pet = QAction("隐藏桌宠", menu)
        hide_pet.triggered.connect(self._hide_pet_action)
        menu.addAction(hide_pet)

        menu.addSeparator()
        quit_action = QAction("退出", menu)
        quit_action.triggered.connect(QApplication.instance().quit)
        menu.addAction(quit_action)
        menu.exec(global_pos)

    def _cycle_mode_action(self):
        self._apply_controller_reply(self.controller.cycle_mode())

    def _toggle_style_action(self):
        next_style = "pet" if self.controller.presentation_mode == "work" else "work"
        self._apply_controller_reply(self.controller.set_presentation_mode(next_style))

    def _hide_pet_action(self):
        self.toolbar.hide()
        self.status_card.hide()
        self.chat.hide()
        self.commands.hide()
        self.toolbar.set_active_panel("")
        self.pet.hide()

    def _initial_reveal(self):
        self.reveal_pet(reset_position=True)

    def _cycle_skin_action(self):
        skins = list(SKIN_PALETTES.keys())
        idx = skins.index(self.current_skin) if self.current_skin in skins else 0
        next_skin = skins[(idx + 1) % len(skins)]
        self._apply_skin(next_skin)
        self.pet.speak(f"换成 {next_skin} 皮肤啦。")
        self.pet.celebrate()

    def _apply_skin(self, skin: str):
        self.current_skin = skin if skin in SKIN_PALETTES else "glass"
        self._state_store.save_skin(self.current_skin)
        self.pet.set_skin(self.current_skin)
        self.chat.apply_skin(self.current_skin)
        self.commands.apply_skin(self.current_skin)
        self.toolbar.apply_skin(self.current_skin)
        self._sync_reply_state(SessionReply(text="", mode=self.controller.mode, presentation_mode=self.controller.presentation_mode))
        self._refresh_tray_menu()

    def _apply_language(self, language_id: str, announce: bool = True):
        language = pai_config.get_language(language_id)
        if language is None:
            return
        self.current_language = str(language.get("id", "zh-CN"))
        pai_config.set_active_language(self.current_language)
        texts = dict(language.get("texts", {}))
        self.chat.set_language(texts)
        self.commands.set_language(texts)
        self.commands.set_quick_commands(pai_config.quick_commands())
        self.chat.set_quick_commands(pai_config.quick_commands())
        self.toolbar.set_language(texts)
        self._refresh_tray_menu()
        if announce:
            label = str(language.get("label", self.current_language))
            message = self._format_text("language_switched", label, f"界面语言已切换为 {label}")
            self.pet.speak(message)
            self.pet.alert()

    def _reload_pets(self):
        ordered: list[PetPackage] = []
        seen: dict[str, int] = {}
        for package in BUILTIN_PETS + self._pet_store.list_imported():
            if package.id in seen:
                ordered[seen[package.id]] = package
                continue
            seen[package.id] = len(ordered)
            ordered.append(package)
        self._pets = ordered or BUILTIN_PETS[:]
        if self._pet_manager is not None and self._pet_manager.isVisible():
            self._pet_manager.load_pets(self._pets, self.current_pet_id, self.current_skin)

    def _current_pet(self) -> PetPackage:
        for package in self._pets:
            if package.id == self.current_pet_id:
                return package
        return self._pets[0]

    def _apply_pet(self, pet_id: str, announce: bool = True):
        selected = next((package for package in self._pets if package.id == pet_id), None) or self._pets[0]
        self.current_pet_id = selected.id
        self._state_store.save_selected_pet(self.current_pet_id)
        self.pet.set_pet_package(selected)
        if hasattr(self, "toolbar"):
            self.toolbar.sync_state(
                self.controller.mode,
                self.controller.presentation_mode,
                self.current_skin,
                selected.display_name,
            )
        if hasattr(self, "tray"):
            self._refresh_tray_menu()
        if self._pet_manager is not None and self._pet_manager.isVisible():
            self._pet_manager.load_pets(self._pets, self.current_pet_id, self.current_skin)
        if announce:
            self.pet.speak(self._format_text("pet_changed", selected.display_name, f"{selected.display_name} 来了。"))
            self.pet.celebrate()

    def _cycle_pet_action(self):
        if not self._pets:
            return
        pet_ids = [package.id for package in self._pets]
        try:
            current_index = pet_ids.index(self.current_pet_id)
        except ValueError:
            current_index = -1
        self._apply_pet(pet_ids[(current_index + 1) % len(pet_ids)])

    def _import_pet_action(self):
        folder = QFileDialog.getExistingDirectory(
            self.chat if self.chat.isVisible() else None,
            "选择 Petdex / Codex 宠物文件夹",
            str(Path.home()),
        )
        if not folder:
            return
        try:
            imported = self._pet_store.import_folder(folder)
        except Exception as exc:
            message = f"导入失败: {exc}"
            self.pet.speak(message)
            self.pet.error()
            return
        self._reload_pets()
        self._apply_pet(imported.id, announce=False)
        self.pet.speak(f"{imported.display_name} 已导入。")
        self.pet.celebrate()

    def _populate_configuration_menu(self, menu: QMenu):
        mode_menu = menu.addMenu("运行模式")
        for mode in ("single", "plan", "team"):
            action = QAction(mode, mode_menu)
            action.setCheckable(True)
            action.setChecked(mode == self.controller.mode)
            action.triggered.connect(lambda _checked=False, value=mode: self._set_mode(value))
            mode_menu.addAction(action)

        style_menu = menu.addMenu("展示模式")
        for style in ("work", "pet"):
            action = QAction(style, style_menu)
            action.setCheckable(True)
            action.setChecked(style == self.controller.presentation_mode)
            action.triggered.connect(lambda _checked=False, value=style: self._set_style(value))
            style_menu.addAction(action)

        persona_menu = menu.addMenu("人格 Prompt")
        for persona in pai_config.personas():
            persona_id = str(persona.get("id", "")).strip()
            label = str(persona.get("label", persona_id)).strip() or persona_id
            action = QAction(label, persona_menu)
            action.setCheckable(True)
            action.setChecked(persona_id == pai_config.active_persona)
            action.triggered.connect(lambda _checked=False, value=persona_id: self._apply_persona(value))
            persona_menu.addAction(action)

        language_menu = menu.addMenu("语言")
        for language in pai_config.languages():
            language_id = str(language.get("id", "")).strip()
            label = str(language.get("label", language_id)).strip() or language_id
            action = QAction(label, language_menu)
            action.setCheckable(True)
            action.setChecked(language_id == self.current_language)
            action.triggered.connect(lambda _checked=False, value=language_id: self._apply_language(value))
            language_menu.addAction(action)

        skin_menu = menu.addMenu("皮肤")
        for skin_id in SKIN_PALETTES:
            action = QAction(skin_id, skin_menu)
            action.setCheckable(True)
            action.setChecked(skin_id == self.current_skin)
            action.triggered.connect(lambda _checked=False, value=skin_id: self._apply_skin_action(value))
            skin_menu.addAction(action)

        pets_menu = menu.addMenu("宠物")
        for package in self._pets:
            action = QAction(package.display_name, pets_menu)
            action.setCheckable(True)
            action.setChecked(package.id == self.current_pet_id)
            action.triggered.connect(lambda _checked=False, value=package.id: self._apply_pet(value))
            pets_menu.addAction(action)

        import_pet = QAction("导入 Petdex 宠物", menu)
        import_pet.triggered.connect(self._import_pet_action)
        menu.addAction(import_pet)

        reset_pet = QAction("重置桌宠位置", menu)
        reset_pet.triggered.connect(lambda: self.reveal_pet(reset_position=True))
        menu.addAction(reset_pet)

        hide_pet = QAction("隐藏桌宠", menu)
        hide_pet.triggered.connect(self._hide_pet_action)
        menu.addAction(hide_pet)

    def _set_mode(self, mode: str):
        self._apply_controller_reply(self.controller.set_mode(mode))
        self._update_status_card()

    def _set_style(self, style: str):
        self._apply_controller_reply(self.controller.set_presentation_mode(style))
        self._update_status_card()

    def _apply_skin_action(self, skin_id: str):
        self._apply_skin(skin_id)
        self.pet.speak(self._format_text("skin_switched", skin_id, f"皮肤已切换为 {skin_id}"))
        self.pet.celebrate()

    def _apply_persona(self, persona_id: str):
        persona = pai_config.get_persona(persona_id)
        if persona is None:
            return
        pai_config.set_active_persona(persona_id)
        self._refresh_tray_menu()
        if self._personality_window is not None and self._personality_window.isVisible():
            self._personality_window.load_personas(
                pai_config.personas(), pai_config.active_persona
            )
        label = str(persona.get("label", persona_id)).strip() or persona_id
        message = self._format_text("persona_switched", label, f"人格已切换为 {label}")
        self.pet.speak(message)
        self.pet.alert()

    def _build_initial_gui_llm_client(self):
        self._gui_model_config = self._load_gui_model_config()
        if self._gui_model_config.enabled:
            try:
                client = self._create_gui_model_client(self._gui_model_config)
                self._gui_model_source = self._format_model_source("独立配置", client.provider_name, client.model_name)
                return client
            except Exception as exc:
                self._gui_model_warning = f"独立 GUI 模型加载失败: {exc}。当前已回退到全局模型。"

        client = create_from_config()
        if client is None:
            raise RuntimeError(
                "无法创建 LLM 客户端。请至少配置一组模型环境变量，例如 "
                "GLM_API_KEY/GLM_MODEL、DEEPSEEK_API_KEY/DEEPSEEK_MODEL、"
                "QWEN_API_KEY/QWEN_MODEL 或 "
                "OLLAMA_MODEL/OLLAMA_BASE_URL。"
            )
        self._gui_model_source = self._format_model_source("跟随全局", client.provider_name, client.model_name)
        return client

    def _load_gui_model_config(self) -> GuiModelConfig:
        try:
            return self._gui_model_store.load()
        except Exception as exc:
            self._gui_model_warning = str(exc)
            return GuiModelConfig()

    def _create_gui_model_client(self, config: GuiModelConfig):
        missing = config.validate()
        if missing:
            raise ValueError(f"缺少字段: {', '.join(missing)}")
        client = create_from_provider_config(config.provider, config.provider_config())
        if client is None:
            raise RuntimeError(f"无法创建 provider={config.provider} 的客户端")
        return client

    def _format_model_source(self, prefix: str, provider: str, model: str) -> str:
        return f"{prefix} ({gui_model_profile_label(provider)} / {model})"

    def _current_global_model_summary(self) -> str:
        global_client = create_from_config()
        if global_client is not None:
            return f"{gui_model_profile_label(global_client.provider_name)} / {global_client.model_name}"
        preset = pai_config.get_model_preset(pai_config.active_model_preset)
        if preset is not None:
            return f"{gui_model_profile_label(preset.provider)} / {preset.model}"
        return "未配置"

    def _seed_gui_model_config(self) -> GuiModelConfig:
        config = self._gui_model_config
        if config.enabled or config.model or config.base_url or config.api_key:
            return config
        return GuiModelConfig(enabled=False, provider="codex", model="", base_url="", api_key="")

    def open_model_settings(self):
        if self._settings_window is None:
            self._settings_window = GuiModelSettingsWindow()
            self._settings_window.save_requested.connect(self._save_gui_model_settings)
        self._settings_window.load_state(
            self._seed_gui_model_config(),
            self._gui_model_source,
            self._current_global_model_summary(),
            self._gui_model_warning,
        )
        self._settings_window.show()
        self._settings_window.raise_()
        self._settings_window.activateWindow()

    def _save_gui_model_settings(self, config: GuiModelConfig):
        if not config.enabled:
            self._follow_global_model(config)
            return
        try:
            new_client = self._create_gui_model_client(config)
            self._gui_model_store.save(config)
            self._gui_model_config = config
            self._gui_model_warning = ""
            self.controller.set_llm_client(new_client)
            self._gui_model_source = self._format_model_source(
                "独立配置",
                new_client.provider_name,
                new_client.model_name,
            )
            self._refresh_tray_menu()
            if self._settings_window is not None:
                self._settings_window.update_runtime_labels(
                    self._gui_model_source,
                    self._current_global_model_summary(),
                    self._gui_model_warning,
                )
                self._settings_window.set_status("独立 GUI 模型已保存并应用。")
            self.pet.speak(
                f"桌宠已切换到独立模型 {gui_model_profile_label(new_client.provider_name)} / {new_client.model_name}。"
            )
            self.pet.celebrate()
            self._update_status_card()
        except Exception as exc:
            if self._settings_window is not None:
                self._settings_window.set_status(f"保存失败: {exc}", error=True)
            self.pet.speak(f"模型配置保存失败: {exc}")
            self.pet.error()

    def open_pet_manager(self):
        if self._pet_manager is None:
            from .windows import PetManagerWindow
            self._pet_manager = PetManagerWindow()
            self._pet_manager.pet_selected.connect(self._apply_pet)
            self._pet_manager.import_requested.connect(self._manager_import_pet)
            self._pet_manager.delete_requested.connect(self._manager_delete_pet)
        self._pet_manager.load_pets(self._pets, self.current_pet_id, self.current_skin)
        self._pet_manager.show()
        self._pet_manager.raise_()
        self._pet_manager.activateWindow()

    def open_personality_settings(self):
        if self._personality_window is None:
            self._personality_window = PersonalityWindow()
        self._personality_window.load_personas(
            pai_config.personas(), pai_config.active_persona
        )
        self._personality_window.show()
        self._personality_window.raise_()
        self._personality_window.activateWindow()

    def _manager_import_pet(self):
        """从 Pet Manager 导入宠物"""
        folder = QFileDialog.getExistingDirectory(
            self._pet_manager if self._pet_manager and self._pet_manager.isVisible() else None,
            "选择宠物文件夹",
            str(Path.home()),
        )
        if not folder:
            return
        try:
            imported = self._pet_store.import_folder(folder)
        except Exception as exc:
            self.pet.speak(f"导入失败: {exc}")
            self.pet.error()
            return
        self._reload_pets()
        self._apply_pet(imported.id, announce=False)
        self.pet.speak(f"{imported.display_name} 已导入。")
        self.pet.celebrate()
        if self._pet_manager is not None:
            self._pet_manager.load_pets(self._pets, self.current_pet_id, self.current_skin)

    def _manager_delete_pet(self, pet_id: str):
        """从 Pet Manager 删除已导入宠物"""
        import shutil
        pet_store = self._pet_store
        target_dir = pet_store.root / pet_id
        if target_dir.exists():
            shutil.rmtree(target_dir)
        self._reload_pets()
        if self.current_pet_id == pet_id:
            self._apply_pet(self._pets[0].id if self._pets else "terminal-cat", announce=False)
        if self._pet_manager is not None:
            self._pet_manager.load_pets(self._pets, self.current_pet_id, self.current_skin)
        self.pet.speak(f"{pet_id} 已删除。")
        self.pet.alert()

    def _follow_global_model(self, config: GuiModelConfig | None = None):
        target_config = config or self._seed_gui_model_config()
        target_config.enabled = False
        reply = self.controller.reload_default_model()
        if reply.kind == "error":
            if self._settings_window is not None:
                self._settings_window.set_status(reply.text, error=True)
            self.pet.speak(reply.text)
            self.pet.error()
            return
        try:
            self._gui_model_store.save(target_config)
            self._gui_model_config = target_config
            self._gui_model_warning = ""
            self._gui_model_source = self._format_model_source(
                "跟随全局",
                self.controller.provider_name,
                self.controller.model_name,
            )
            self._refresh_tray_menu()
            if self._settings_window is not None:
                self._settings_window.update_runtime_labels(
                    self._gui_model_source,
                    self._current_global_model_summary(),
                    self._gui_model_warning,
                )
                self._settings_window.set_status("桌宠已恢复跟随全局模型。")
            self.pet.speak("桌宠已经恢复跟随全局模型。")
            self.pet.alert()
            self._update_status_card()
        except Exception as exc:
            if self._settings_window is not None:
                self._settings_window.set_status(f"保存失败: {exc}", error=True)
            self.pet.speak(f"模型配置保存失败: {exc}")
            self.pet.error()

    def _text(self, key: str, default: str) -> str:
        return pai_config.active_language_text(key, default)

    def _format_text(self, key: str, value: str, default: str) -> str:
        template = self._text(key, default)
        try:
            return template.format(value=value)
        except Exception:
            return default

    def _refresh_tray_menu(self):
        if hasattr(self, "tray"):
            self._tray_menu = self._build_tray_menu()
            self.tray.setContextMenu(self._tray_menu)


def run_pet_app(argv: list[str]) -> int:
    app = QApplication(argv)
    app.setQuitOnLastWindowClosed(False)
    configure_app_for_desktop_pet()
    coordinator = PetCoordinator()
    coordinator.hide()
    return app.exec()
