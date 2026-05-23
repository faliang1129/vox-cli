"""Reusable session controller for CLI and desktop shells."""

from __future__ import annotations

from contextlib import redirect_stdout
from dataclasses import dataclass
from io import StringIO
import os
from typing import Optional

from ..agent import Agent, AgentOrchestrator, PlanExecuteAgent
from ..chat import GuiChatSubmission
from ..cli.parser import CliCommandParser, ParsedCommand
from ..config import pai_config
from ..llm.factory import create, create_from_config
from ..memory.manager import MemoryManager
from ..prompting import PresentationMode, ResponsePresenter
from ..tool import ToolRegistry


@dataclass
class SessionReply:
    text: str
    kind: str = "assistant"
    raw_text: str = ""
    mode: str = "single"
    presentation_mode: str = PresentationMode.WORK.value
    should_quit: bool = False


class SessionController:
    """Stateful facade for chat-style shells."""

    def __init__(
        self,
        llm_client=None,
        tool_registry: Optional[ToolRegistry] = None,
        agent: Optional[Agent] = None,
        plan_agent: Optional[PlanExecuteAgent] = None,
        orchestrator: Optional[AgentOrchestrator] = None,
        presenter: Optional[ResponsePresenter] = None,
        allow_model_switch_commands: bool = True,
    ):
        self._llm = llm_client or create_from_config()
        if self._llm is None:
            raise RuntimeError(
                "无法创建 LLM 客户端。请至少配置一组模型环境变量，例如 "
                "GLM_API_KEY/GLM_MODEL、DEEPSEEK_API_KEY/DEEPSEEK_MODEL、"
                "QWEN_API_KEY/QWEN_MODEL 或 "
                "OLLAMA_MODEL/OLLAMA_BASE_URL。"
            )

        self._tool_registry = tool_registry or ToolRegistry()
        self._shared_memory_manager = MemoryManager(self._llm)
        self._agent = agent or Agent(self._llm, self._tool_registry)
        self._plan_agent = plan_agent or PlanExecuteAgent(
            self._llm, self._tool_registry, None, self._shared_memory_manager, None
        )
        self._orchestrator = orchestrator or AgentOrchestrator(
            self._llm, self._tool_registry, self._shared_memory_manager
        )
        self._presenter = presenter or ResponsePresenter(self._llm)
        self._parser = CliCommandParser()
        self._allow_model_switch_commands = allow_model_switch_commands
        self._mode = "single"
        self._presentation_mode = self._default_presentation_mode().value

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def presentation_mode(self) -> str:
        return self._presentation_mode

    @property
    def provider_name(self) -> str:
        return self._llm.provider_name

    @property
    def model_name(self) -> str:
        return self._llm.model_name

    def set_mode(self, mode: str) -> SessionReply:
        normalized = mode.strip().lower()
        if normalized not in {"single", "plan", "team"}:
            return self._system_reply(f"无效运行模式: {mode}", kind="error")
        self._mode = normalized
        return self._system_reply(f"运行模式已切换为: {self._render_mode_label(normalized)}")

    def cycle_mode(self) -> SessionReply:
        modes = ["single", "plan", "team"]
        idx = modes.index(self._mode) if self._mode in modes else 0
        self._mode = modes[(idx + 1) % len(modes)]
        return self._system_reply(f"运行模式已切换为: {self._render_mode_label(self._mode)}")

    def set_presentation_mode(self, mode: str) -> SessionReply:
        if not PresentationMode.is_valid(mode):
            return self._system_reply("无效展示模式，可选: work, pet", kind="error")
        self._presentation_mode = PresentationMode.normalize(mode).value
        return self._system_reply(f"展示模式已设置为: {self._presentation_mode}")

    def set_llm_client(self, llm_client) -> None:
        self._llm = llm_client
        self._agent.set_llm_client(llm_client)
        if not getattr(llm_client, "supports_image_inputs", False) and hasattr(
            self._agent, "clear_attachment_context"
        ):
            self._agent.clear_attachment_context()
        self._plan_agent._llm = llm_client
        if hasattr(self._plan_agent, "_planner") and self._plan_agent._planner is not None:
            self._plan_agent._planner._llm = llm_client
        self._plan_agent.memory_manager.set_llm_client(llm_client)
        self._orchestrator._llm = llm_client
        if hasattr(self._orchestrator, "_planner") and self._orchestrator._planner is not None:
            self._orchestrator._planner._llm = llm_client
        if hasattr(self._orchestrator, "_reviewer") and self._orchestrator._reviewer is not None:
            self._orchestrator._reviewer._llm = llm_client
        if hasattr(self._orchestrator, "_workers"):
            for worker in self._orchestrator._workers:
                worker._llm = llm_client
        self._orchestrator.memory_manager.set_llm_client(llm_client)
        self._presenter._llm = llm_client

    def reload_default_model(self) -> SessionReply:
        new_client = create_from_config()
        if new_client is None:
            return self._system_reply("切换模型失败: 无法创建当前全局配置的客户端", kind="error")
        self.set_llm_client(new_client)
        return self._system_reply(
            f"已切换到全局模型: {new_client.provider_name} ({new_client.model_name})"
        )

    def set_model(self, provider: str, model_name: Optional[str] = None) -> SessionReply:
        try:
            new_client = create(provider, model_name)
            if new_client is None:
                return self._system_reply(
                    f"切换模型失败: 无法创建 provider={provider} 的客户端",
                    kind="error",
                )
            self.set_llm_client(new_client)
            selected_model = getattr(new_client, "model_name", model_name or "")
            pai_config.persist_model_selection(provider, selected_model)
            return self._system_reply(
                "已切换到模型: " + provider + (f" ({selected_model})" if selected_model else "")
            )
        except Exception as exc:
            return self._system_reply(f"切换模型失败: {exc}", kind="error")

    def set_model_preset(self, preset_id: str) -> SessionReply:
        preset = pai_config.get_model_preset(preset_id)
        if preset is None:
            return self._system_reply(f"未知模型预设: {preset_id}", kind="error")
        return self.set_model(preset.provider, preset.model)

    def submit(self, line: str | GuiChatSubmission) -> SessionReply:
        if isinstance(line, GuiChatSubmission):
            submission = line.normalized()
            if submission.is_empty:
                return self._system_reply("", kind="system")

            stripped = submission.text
            parsed = self._parser.parse(stripped) if stripped else None
            if parsed:
                if submission.has_attachments:
                    return self._system_reply("命令消息暂不支持携带图片，请移除附件后重试。", kind="error")
                return self._handle_command(parsed)

            if submission.has_attachments:
                if self._mode != "single":
                    return self._system_reply("图片附件目前仅支持单聊模式，请先切换回 single。", kind="error")
                if not getattr(self._llm, "supports_image_inputs", False):
                    return self._system_reply(
                        "当前模型不支持图片输入。请切换到支持视觉的 OpenAI Compatible 模型。",
                        kind="error",
                    )
                return self._run_user_request(submission)

            if not stripped:
                return self._system_reply("", kind="system")
            return self._run_user_request(stripped)

        stripped = line.strip()
        if not stripped:
            return self._system_reply("", kind="system")

        parsed = self._parser.parse(stripped)
        if parsed:
            return self._handle_command(parsed)
        return self._run_user_request(stripped)

    def help_text(self) -> str:
        lines = ["可用命令:"]
        for command, desc in sorted(CliCommandParser.COMMANDS.items()):
            lines.append(f"  {command:<10} {desc}")
        lines.append("")
        lines.append("桌宠窗口里也支持直接输入普通问题或任务。")
        return "\n".join(lines)

    def _handle_command(self, parsed: ParsedCommand) -> SessionReply:
        cmd = parsed.command

        if cmd == "/help":
            return self._system_reply(self.help_text())

        if cmd == "/exit":
            return SessionReply(
                text="再见！",
                kind="system",
                mode=self._mode,
                presentation_mode=self._presentation_mode,
                should_quit=True,
            )

        if cmd == "/team":
            return self.cycle_mode()

        if cmd == "/init":
            return self._system_reply(
                "请在终端里运行 vox-code init 来完成首次配置。",
                kind="error",
            )

        if cmd == "/style":
            if not parsed.args:
                return self._system_reply(f"当前展示模式: {self._presentation_mode}")
            return self.set_presentation_mode(parsed.args[0])

        if cmd == "/model":
            if not self._allow_model_switch_commands:
                return self._system_reply(
                    "桌宠 GUI 请在“模型设置”窗口中修改模型。",
                    kind="error",
                )
            if not parsed.args:
                return self._system_reply("用法: /model <preset-id|provider[:model]>", kind="error")
            provider, model_name, preset = pai_config.resolve_model_selection(parsed.args[0])
            if preset is not None:
                return self.set_model_preset(preset.id)
            return self.set_model(provider, model_name)

        if cmd == "/plan":
            return self._system_reply(
                "Plan-and-Execute 模式会先生成计划再执行。"
                f"\n当前运行模式: {self._render_mode_label(self._mode)}"
            )

        if cmd == "/memory":
            return self._system_reply(self._active_memory_manager().status_summary())

        if cmd == "/clear":
            self._agent.clear_history()
            self._shared_memory_manager.clear_short_term()
            return self._system_reply("对话历史已清空")

        if cmd == "/context":
            if self._mode == "single":
                return self._system_reply(self._agent.get_context_status())
            return self._system_reply(
                f"当前运行模式: {self._render_mode_label(self._mode)}\n"
                f"{self._active_memory_manager().status_summary()}"
            )

        if cmd == "/policy":
            return self._system_reply(
                "安全策略\n"
                f"- 项目根目录: {self._tool_registry.project_path}\n"
                "- PathGuard: 限制到项目根目录\n"
                "- CommandGuard: 禁止危险命令\n"
                "- 审计日志: ~/.vox-code/audit/"
            )

        if cmd == "/audit":
            entries = self._tool_registry.audit_log.recent(10)
            if not entries:
                return self._system_reply("暂无审计记录")
            lines = ["最近审计记录:"]
            for entry in entries:
                lines.append(
                    f"- {entry.tool} [{entry.outcome}] "
                    f"{entry.reason or '无原因'}"
                )
            return self._system_reply("\n".join(lines))

        if cmd == "/index":
            try:
                from ..rag.index import CodeIndex

                indexer = CodeIndex(self._tool_registry.project_path)
                count = indexer.index_project()
                return self._system_reply(f"索引完成，共 {count} 个代码块")
            except ImportError:
                return self._system_reply("索引功能不可用（缺少 RAG 模块依赖）", kind="error")
            except Exception as exc:
                return self._system_reply(f"索引失败: {exc}", kind="error")

        if cmd == "/search":
            query = " ".join(parsed.args).strip()
            if not query:
                return self._system_reply("用法: /search <query>", kind="error")
            try:
                return self._system_reply(self._tool_registry._search_code(query, 5))
            except Exception as exc:
                return self._system_reply(f"搜索失败: {exc}", kind="error")

        if cmd == "/save":
            filename = " ".join(parsed.args).strip() or "conversation.md"
            try:
                history = self._agent.conversation_history
                lines = []
                for message in history:
                    parts = [message.content or ""]
                    if message.attachments:
                        parts.extend(
                            f"[image] {attachment.display_name} ({attachment.file_path})"
                            for attachment in message.attachments
                        )
                    lines.append(f"## {message.role.upper()}\n" + "\n".join(part for part in parts if part) + "\n")
                with open(filename, "w", encoding="utf-8") as handle:
                    handle.write("\n".join(lines))
                return self._system_reply(f"对话已保存到: {filename}")
            except Exception as exc:
                return self._system_reply(f"保存失败: {exc}", kind="error")

        if cmd == "/hitl":
            return self._system_reply("桌宠版 MVP 暂未接入 HITL 面板，请继续使用 CLI 处理审批。")

        return self._system_reply(f"未知命令: {cmd}", kind="error")

    def _run_user_request(self, user_input: str | GuiChatSubmission) -> SessionReply:
        executor = self._active_executor()
        stdout_buffer = StringIO()
        source_input = user_input.summary_text if isinstance(user_input, GuiChatSubmission) else user_input
        try:
            with redirect_stdout(stdout_buffer):
                raw_result = executor.run(user_input)
        except Exception as exc:
            return self._system_reply(f"执行失败: {exc}", kind="error")

        captured = stdout_buffer.getvalue().strip()
        source = (raw_result or "").strip() or captured
        if not source:
            source = "任务执行完成，但模型没有返回可显示内容。"

        presented = self._presenter.present(source_input, source, self._presentation_mode)
        return SessionReply(
            text=presented.display_response or source,
            raw_text=source,
            kind="assistant",
            mode=self._mode,
            presentation_mode=self._presentation_mode,
        )

    def _active_executor(self):
        if self._mode == "plan":
            return self._plan_agent
        if self._mode == "team":
            return self._orchestrator
        return self._agent

    def _active_memory_manager(self) -> MemoryManager:
        if self._mode == "single":
            return self._agent.memory_manager
        return self._shared_memory_manager

    def _system_reply(self, text: str, kind: str = "system") -> SessionReply:
        return SessionReply(
            text=text,
            kind=kind,
            raw_text=text,
            mode=self._mode,
            presentation_mode=self._presentation_mode,
        )

    @staticmethod
    def _render_mode_label(mode: str) -> str:
        if mode == "plan":
            return "Plan-and-Execute"
        if mode == "team":
            return "多 Agent 团队"
        return "单 Agent"

    @staticmethod
    def _default_presentation_mode() -> PresentationMode:
        return PresentationMode.normalize(os.environ.get("VOX_CODE_PRESENTATION_MODE", "work"))
