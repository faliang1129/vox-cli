"""Agent 核心类 - 实现 ReAct 循环"""

from __future__ import annotations

import json
import time
import logging
from typing import List, Optional, Dict

from ..chat import GuiChatSubmission
from ..llm.base import LlmClient, Message, ToolCall
from ..memory.manager import MemoryManager
from ..tool import ToolRegistry, ToolInvocation
from ..util.ansi import heading, section, subtle
from ..util.animation import ThinkingDots, Typewriter, ToolCallAnimator
from .agent_budget import AgentBudget, ExitReason
import sys

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """你是一个智能编程 Agent Vox Code，可以帮助用户完成各种任务。

你可以使用以下工具来完成任务：
1. read_file - 读取文件内容
2. write_file - 写入文件内容
3. list_dir - 列出目录内容
4. execute_command - 执行Shell命令
5. create_project - 创建新项目结构
6. search_code - 语义检索代码库，参数：{"query": "自然语言描述", "top_k": 5}
7. web_search - 搜索互联网获取实时信息（最新版本、官方文档、技术资讯等），参数：{"query": "搜索关键词", "top_k": 5}
8. web_fetch - 抓取已知 URL 并返回正文 Markdown，参数：{"url": "https://...", "max_chars": 8000}

当需要操作文件、执行命令或创建项目时，请使用工具调用。
使用工具后，根据工具返回的结果继续思考下一步行动。
对于当前项目内的文件和代码，请优先使用 read_file、list_dir、search_code。
execute_command 只适合在当前项目目录执行短时命令（如 git status、mvn test），不要用它扫描 /、~ 或整个文件系统。
安全策略硬规则（HITL 之外的兜底，无法绕过，请提前规避）：
- read_file / write_file / list_dir / create_project 的路径必须在项目根之内，绝对路径或 .. 越界会被拒绝
- write_file 单文件 5MB 上限
- execute_command 禁止 sudo、rm -rf 全盘或用户目录、mkfs、dd 写裸设备、fork bomb、curl|sh、find /、chmod 777 /、shutdown
- 若调用被策略拒绝（结果以 "🛡️ 策略拒绝" 开头），不要原样重试，改用项目内相对路径或更安全的方式
同一轮返回多个工具调用时，系统会并行执行这些工具；如果工具之间有依赖关系，请分多轮调用。
如果需要同时检查多个已知且互不依赖的文件或目录（例如同时读取 pom.xml、README.md、ROADMAP.md，
或同时列出 src/main/java、src/test/java、src/main/resources），请在同一轮返回多个 read_file/list_dir 工具调用。

工具选择优先级：
- 代码库相关问题（"这个类是干什么的"、"哪里用了某个功能"）→ search_code，不要走 web_search
- 训练数据已知的稳定知识（语法、稳定 API、基础概念）→ 直接回答，不要联网
- 时效性 / 最新信息 / 不确定的事实 → web_search 找入口，找到 URL 后再 web_fetch 拿全文
- 已经有具体 URL → 直接 web_fetch，不要再 web_search 一次
- web_fetch 拿到空正文（提示 SPA / 防爬墙）→ 这是已知边界，告知用户即可，不要反复重试

如果提供了相关记忆，请参考其中的信息来辅助决策。

请用中文回复用户。"""


class Agent:
    def __init__(self, llm_client: LlmClient, tool_registry: Optional[ToolRegistry] = None):
        self._llm = llm_client
        self._tool_registry = tool_registry or ToolRegistry()
        self._conversation_history: List[Message] = [Message.system(_SYSTEM_PROMPT)]
        self._memory_manager = MemoryManager(llm_client)

    def set_llm_client(self, llm_client: LlmClient):
        self._llm = llm_client
        self._memory_manager.set_llm_client(llm_client)

    @property
    def memory_manager(self) -> MemoryManager:
        return self._memory_manager

    @property
    def tool_registry(self) -> ToolRegistry:
        return self._tool_registry

    @property
    def conversation_history(self) -> List[Message]:
        return list(self._conversation_history)

    # ---- Public API ----

    def run(self, user_input: str | GuiChatSubmission) -> str:
        submission = user_input if isinstance(user_input, GuiChatSubmission) else None
        input_text = submission.summary_text if submission is not None else user_input
        logger.info("ReAct run started: inputLength=%d", len(input_text) if input_text else 0)
        self._memory_manager.add_user_message(input_text)

        memory_context = self._memory_manager.build_context_for_query(input_text, 500)
        self._update_system_prompt(memory_context)

        if submission is not None:
            self._conversation_history.append(
                Message.user(submission.text, attachments=submission.attachments)
            )
        else:
            self._conversation_history.append(Message.user(user_input))
        reasoning_transcript: List[str] = []
        thinking_dots = ThinkingDots()
        stream_renderer = _StreamRenderer(stop_thinking=thinking_dots.stop)

        start_nanos = time.time()
        budget = AgentBudget.from_env()

        while True:
            exit_reason = budget.check()
            if exit_reason != ExitReason.WITHIN_BUDGET:
                stats = self._format_token_stats(budget.total_input_tokens,
                                                  budget.total_output_tokens, start_nanos)
                desc = budget.describe_exit(exit_reason)
                logger.warning("ReAct budget exhausted: reason=%s, iteration=%d, tokens=%d/%d",
                               exit_reason, budget.iteration,
                               budget.total_input_tokens + budget.total_output_tokens,
                               budget.token_budget)
                return f"❌ {desc}\n\n{stats}"

            iteration = budget.begin_iteration()
            thinking_dots.start()

            try:
                response = self._llm.chat(
                    self._conversation_history,
                    self._tool_registry.get_tool_definitions(),
                    stream_renderer,
                )
                thinking_dots.stop()

                if response is None:
                    return "❌ LLM 返回空响应，请检查模型接口是否正常"

                budget.record_tokens(response.input_tokens or 0, response.output_tokens or 0)

                if response.has_tool_calls:
                    self._append_reasoning(reasoning_transcript, response.reasoning_content)
                    logger.info("LLM requested %d tool call(s) in iteration %d",
                                len(response.tool_calls), iteration)
                    budget.record_tool_calls(response.tool_calls)

                    tool_anim = ToolCallAnimator()
                    _format_tool_calls_info(response.tool_calls, tool_anim)

                    self._conversation_history.append(Message.assistant(
                        content=response.content or "",
                        reasoning_content=response.reasoning_content,
                        tool_calls=response.tool_calls,
                    ))

                    tool_results = self._execute_tool_calls(response.tool_calls, iteration)
                    for tr in tool_results:
                        self._memory_manager.add_tool_result(tr.name, tr.result)
                        self._conversation_history.append(Message.tool(tr.id, tr.result))

                    # 原地将工具调用标记为 ✓（finish_all 必须在 reset 之前，否则多出的空行会破坏 ANSI 定位）
                    tool_anim.finish_all()

                    stream_renderer.reset_between_iterations()
                    continue

                self._append_reasoning(reasoning_transcript, response.reasoning_content)
                self._conversation_history.append(Message.assistant(
                    content=response.content or "",
                    reasoning_content=response.reasoning_content,
                ))

                self._memory_manager.add_assistant_message(response.content or "")
                self._memory_manager.record_token_usage(
                    budget.total_input_tokens, budget.total_output_tokens)

                logger.info("ReAct finished: inputTokens=%d, outputTokens=%d, reasoningChars=%d, answerChars=%d",
                            budget.total_input_tokens, budget.total_output_tokens,
                            len(response.reasoning_content or ""), len(response.content or ""))

                stats = self._format_token_stats(budget.total_input_tokens,
                                                  budget.total_output_tokens, start_nanos)

                if stream_renderer.has_streamed_output():
                    stream_renderer.finish()
                    print(subtle(stats))
                    return ""

                result = self._format_response("\n".join(reasoning_transcript), response.content or "")
                return result + "\n\n" + subtle(stats)

            except Exception as e:
                thinking_dots.stop()
                logger.error("LLM call failed in ReAct loop", exc_info=True)
                return f"❌ 调用 LLM 失败: {e}"

    def clear_history(self):
        system_msg = self._conversation_history[0]
        self._conversation_history.clear()
        self._conversation_history.append(system_msg)
        self._memory_manager.clear_short_term()

    def clear_attachment_context(self):
        for message in self._conversation_history:
            if message.attachments:
                message.attachments = ()

    def get_context_status(self) -> str:
        system_count = user_count = assistant_count = tool_count = 0
        total_chars = 0
        for msg in self._conversation_history:
            total_chars += len(msg.content or "")
            role_counts = {"system": 0, "user": 0, "assistant": 0, "tool": 0}
            r = msg.role
            if r == "system":
                system_count += 1
            elif r == "user":
                user_count += 1
            elif r == "assistant":
                assistant_count += 1
            elif r == "tool":
                tool_count += 1

        total_messages = len(self._conversation_history)
        rounds = user_count
        return (
            f"对话上下文: {total_messages} 条消息, {rounds} 轮对话, ~{total_chars} 字符\n"
            f"   system: {system_count} / user: {user_count} / assistant: {assistant_count} / tool: {tool_count}\n"
            f"{self._memory_manager.status_summary()}"
        )

    # ---- Internal ----

    def _update_system_prompt(self, memory_context: str):
        if memory_context:
            enriched = _SYSTEM_PROMPT + "\n" + memory_context
            self._conversation_history[0] = Message.system(enriched)
        else:
            self._conversation_history[0] = Message.system(_SYSTEM_PROMPT)

    def _execute_tool_calls(self, tool_calls: List, iteration: int) -> List:
        invocations = []
        for tc in tool_calls:
            if isinstance(tc, ToolCall):
                func_name = tc.name
                func_args = tc.arguments
                tool_id = tc.id
            else:
                func_name = tc.get("function", {}).get("name", "")
                func_args = tc.get("function", {}).get("arguments", "")
                tool_id = tc.get("id", "")
            logger.info("Scheduling tool: %s (iteration=%d)", func_name, iteration)
            invocations.append(ToolInvocation(tool_id, func_name, func_args))

        if len(invocations) > 1:
            logger.info("Executing %d tool calls in parallel (iteration=%d)",
                        len(invocations), iteration)
        return self._tool_registry.execute_tools(invocations)

    @staticmethod
    def _append_reasoning(transcript: List[str], reasoning: Optional[str]):
        if reasoning and reasoning.strip():
            if transcript:
                transcript.append("")
            transcript.append(reasoning.strip())

    @staticmethod
    def _format_response(reasoning: str, answer: str) -> str:
        if not reasoning:
            return answer
        if not answer:
            return f"🧠 思考过程:\n{reasoning}"
        return f"🧠 思考过程:\n{reasoning}\n\n🤖 回复:\n{answer}"

    @staticmethod
    def _format_token_stats(input_tokens: int, output_tokens: int, start: float) -> str:
        elapsed = time.time() - start
        return subtle(
            f"📊 Token: {input_tokens} 输入 / {output_tokens} 输出 / "
            f"{input_tokens + output_tokens} 合计 | ⏱ {elapsed:.1f}s"
        )


def _format_tool_calls_info(tool_calls: List, anim: ToolCallAnimator):
    """用 ToolCallAnimator 展示工具调用信息"""
    for tc in tool_calls:
        if isinstance(tc, ToolCall):
            name = tc.name
            args_json = tc.arguments
        else:
            name = tc.get("function", {}).get("name", "")
            args_json = tc.get("function", {}).get("arguments", "{}")
        detail = _extract_key_param(name, args_json)
        anim.running(name, detail)


def _print_tool_calls(tool_calls: List):
    """Legacy: 直接打印工具调用（保持向后兼容）"""
    grouped: Dict[str, list] = {}
    for tc in tool_calls:
        if isinstance(tc, ToolCall):
            name = tc.name
        else:
            name = tc.get("function", {}).get("name", "")
        grouped.setdefault(name, []).append(tc)

    for tool_name, calls in grouped.items():
        print(subtle(f"  {_tool_label(tool_name, len(calls))}"))
        for tc in calls:
            if isinstance(tc, ToolCall):
                args_json = tc.arguments
            else:
                args_json = tc.get("function", {}).get("arguments", "{}")
            detail = _extract_key_param(tool_name, args_json)
            if detail:
                print(subtle(f"    └ {detail}"))


def _tool_label(name: str, count: int) -> str:
    labels = {
        "read_file": f"📖 读取 {count} 个文件",
        "write_file": f"✏️ 写入 {count} 个文件",
        "list_dir": f"📂 列出 {count} 个目录",
        "execute_command": f"⚡ 执行 {count} 条命令",
        "create_project": f"🏗️ 创建 {count} 个项目",
        "search_code": f"🔍 搜索代码 {count} 次",
        "web_search": f"🌐 联网搜索 {count} 次",
        "web_fetch": f"📰 抓取 {count} 个网页",
    }
    return labels.get(name, f"🔧 {name} × {count}")


def _extract_key_param(tool_name: str, args_json: str) -> str:
    try:
        args = json.loads(args_json)
        key_map = {
            "read_file": "path", "write_file": "path", "list_dir": "path",
            "execute_command": "command", "create_project": "name",
            "search_code": "query", "web_search": "query", "web_fetch": "url",
        }
        key = key_map.get(tool_name)
        if key and key in args:
            value = str(args[key])
            return value if len(value) <= 80 else value[:77] + "..."
        return ""
    except json.JSONDecodeError:
        return args_json[:80] if len(args_json) > 80 else args_json


class _StreamRenderer:
    """流式输出渲染器 + Claude Code 风格动画

    - LLM 思考期间显示 ● ● ● 脉冲动画
    - 首个 delta 到达时立即停止动画（防覆盖），切换为打字机效果
    """
    def __init__(self, stop_thinking=None):
        self._pending_reasoning = ""
        self._late_reasoning = ""
        self._reasoning_heading_printed = False
        self._reasoning_started = False
        self._content_started = False
        self._streamed_output = False
        self._tw = Typewriter()
        self._stop_thinking = stop_thinking
        self._thinking_stopped = False

    def _stop_dots(self):
        """首个 delta 到达时立刻停止 thinking 动画（防 \r 覆盖内容）"""
        if not self._thinking_stopped and self._stop_thinking:
            self._stop_thinking()
            self._thinking_stopped = True

    def _ensure_clean_line(self):
        """清空当前行并将光标移至行首（防线程残留 \r 字符）"""
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()

    def __call__(self, delta: str):
        if delta:
            self._on_content_delta(delta)

    def on_reasoning_delta(self, delta: str):
        if not delta:
            return
        self._stop_dots()
        if self._content_started:
            self._late_reasoning += delta
            return
        if not self._reasoning_started:
            self._pending_reasoning += delta
            if not self._pending_reasoning.strip():
                return
            if "\n" not in self._pending_reasoning and "\r" not in self._pending_reasoning:
                return
            self._ensure_clean_line()
            self._print_reasoning_heading()
            self._tw.write_fast(self._pending_reasoning)
            self._pending_reasoning = ""
            self._reasoning_started = True
            self._streamed_output = True
        else:
            self._tw.write(delta)

    def on_content_delta(self, delta: str):
        if not delta:
            return
        self._stop_dots()
        if not self._content_started:
            if self._reasoning_started:
                self._tw.newline()
            elif self._pending_reasoning.strip():
                self._ensure_clean_line()
                self._print_reasoning_heading()
                self._tw.write_fast(self._pending_reasoning)
                self._tw.newline()
                self._pending_reasoning = ""
                self._reasoning_started = True
            self._ensure_clean_line()
            print(section("🤖 回复"))
            self._content_started = True
            self._streamed_output = True
        self._tw.write(delta)

    def _on_content_delta(self, delta: str):
        self.on_content_delta(delta)

    def reset_between_iterations(self):
        self._thinking_stopped = False
        self._pending_reasoning = ""
        late = self._late_reasoning.strip()
        if late:
            print(f"\n{heading('🧠 补充思考')}")
            self._tw.write_fast(late)
            self._late_reasoning = ""
            self._streamed_output = True
        self._reasoning_started = False
        self._content_started = False
        if self._streamed_output:
            print()

    def finish(self):
        late = self._late_reasoning.strip()
        if late:
            print(f"\n{heading('🧠 补充思考')}")
            self._tw.write_fast(late)
            self._late_reasoning = ""
            self._streamed_output = True
        if self._streamed_output:
            print()

    def has_streamed_output(self) -> bool:
        return self._streamed_output

    def _print_reasoning_heading(self):
        if not self._reasoning_heading_printed:
            print(heading("🧠 思考过程"))
            self._reasoning_heading_printed = True
