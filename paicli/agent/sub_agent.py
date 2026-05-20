"""子代理 - 可配置角色的轻量 Agent"""

import json
import time
import logging
from typing import List, Optional, Dict

from ..llm.base import LlmClient, Message, ToolCall
from ..tool import ToolRegistry, ToolInvocation
from ..util.ansi import heading, section, subtle
from .roles import AgentRole, AgentMessage, AgentMessageType
from .agent_budget import AgentBudget, ExitReason

logger = logging.getLogger(__name__)

_PLANNER_PROMPT = """你是一个任务规划专家。你的职责是分析用户的需求，将其拆解为清晰的执行步骤。

请按以下 JSON 格式输出执行计划：
{
    "summary": "任务摘要",
    "steps": [
        {
            "id": "step_1",
            "description": "步骤描述，要具体明确",
            "type": "FILE_READ | FILE_WRITE | COMMAND | ANALYSIS | VERIFICATION",
            "dependencies": []
        }
    ]
}

规则：
1. 每个步骤必须有唯一的 id（如 step_1, step_2）
2. dependencies 列出依赖的步骤 id
3. 步骤描述要具体，让执行者能直接理解要做什么
4. 简单任务可以只拆成 1-3 步
5. 复杂任务拆成 5-10 步
6. 不要为了凑步数引入无关操作
7. 如果多个步骤可以独立完成，不要给它们添加依赖；保持 dependencies 为空，让编排器能并行分配给多个 Worker。
8. 只有后一步确实需要前一步结果时，才写 dependencies。

只输出 JSON，不要有其他内容。
请用中文回复。"""

_WORKER_PROMPT = """你是一个任务执行专家。你的职责是根据给定的任务步骤，调用工具完成具体操作。

可用工具：
1. read_file - 读取文件内容，参数：{"path": "文件路径"}
2. write_file - 写入文件内容，参数：{"path": "文件路径", "content": "内容"}
3. list_dir - 列出目录内容，参数：{"path": "目录路径"}
4. execute_command - 执行命令，参数：{"command": "命令"}
5. create_project - 创建项目，参数：{"name": "名称", "type": "java|python|node"}
6. search_code - 语义检索代码库，参数：{"query": "自然语言描述", "top_k": 5}
7. web_search - 搜索互联网获取实时信息，参数：{"query": "搜索关键词", "top_k": 5}
8. web_fetch - 抓取已知 URL 并返回正文 Markdown，参数：{"url": "https://...", "max_chars": 8000}

如果任务涉及理解代码库，请优先使用 search_code 工具。
如果任务涉及实时性或互联网信息，先用 web_search 找入口，拿到 URL 后用 web_fetch 取全文。
对于当前项目内的文件，请优先使用 read_file 或 list_dir，不要用 execute_command 扫描 /、~ 或整个文件系统。
execute_command 只适合在当前项目目录执行短时命令。
安全策略硬规则（HITL 之外的兜底，无法绕过）：read_file / write_file / list_dir / create_project 必须在项目根之内；
write_file 单文件 5MB 上限；execute_command 禁止 sudo / rm -rf 全盘 / mkfs / dd of=/dev / fork bomb / curl|sh / find / / chmod 777 / / shutdown。
被策略拒绝的工具调用（"🛡️ 策略拒绝" 开头）不要原样重试，改用项目内相对路径或更安全的命令。
同一轮返回多个工具调用时，系统会并行执行这些工具；如果工具之间有依赖关系，请分多轮调用。
如果是 ANALYSIS 或 VERIFICATION 类型任务，请直接输出分析结果。

请用中文回复。"""

_REVIEWER_PROMPT = """你是一个质量检查专家。你的职责是检查执行结果是否正确、完整和高质量。

检查要点：
1. 任务是否按要求完成
2. 结果是否正确，有无明显错误
3. 是否遗漏了重要步骤或细节
4. 输出格式是否规范

请以 JSON 格式输出检查结果：
{
    "approved": true 或 false,
    "summary": "检查摘要",
    "issues": ["问题1", "问题2"],
    "suggestions": ["建议1", "建议2"]
}

如果 approved 为 true，issues 为空即可。
如果 approved 为 false，请详细说明问题并给出改进建议。
只输出 JSON，不要有其他内容。
请用中文回复。"""


_JSON_MAPPER = {}


def _get_role_prompt(role: AgentRole) -> str:
    return {
        AgentRole.PLANNER: _PLANNER_PROMPT,
        AgentRole.WORKER: _WORKER_PROMPT,
        AgentRole.REVIEWER: _REVIEWER_PROMPT,
    }.get(role, _WORKER_PROMPT)


class SubAgent:
    def __init__(self, name: str, role: AgentRole, llm_client: LlmClient, tool_registry: ToolRegistry):
        self._name = name
        self._role = role
        self._llm = llm_client
        self._tool_registry = tool_registry
        self._conversation_history: List[Message] = [Message.system(_get_role_prompt(role))]

    @property
    def name(self) -> str:
        return self._name

    @property
    def role(self) -> AgentRole:
        return self._role

    def execute(self, task: AgentMessage) -> AgentMessage:
        logger.info("[%s] executing task from %s: type=%s", self._name, task.from_agent, task.type.value)
        return self._execute_with_out(task, None)

    def execute_with_context(self, task: AgentMessage, context: Optional[str] = None) -> AgentMessage:
        if context:
            enriched = f"{context}\n\n当前任务：{task.content}"
            enriched_task = AgentMessage(task.from_agent, task.from_role, enriched, task.type)
            return self._execute_with_out(enriched_task, None)
        return self._execute_with_out(task, None)

    def review(self, original_task: str, execution_result: str) -> AgentMessage:
        review_input = f"原始任务：{original_task}\n\n执行结果：\n{execution_result}"
        review_task = AgentMessage.task("orchestrator", review_input)
        return self._execute_with_out(review_task, None)

    def clear_history(self):
        system_msg = self._conversation_history[0]
        self._conversation_history.clear()
        self._conversation_history.append(system_msg)

    # ---- Internal ----

    def _execute_with_out(self, task: AgentMessage, _out=None) -> AgentMessage:
        self._conversation_history.append(Message.user(task.content))
        stream_renderer = _SubAgentStreamRenderer(self._name, self._role)

        start_nanos = time.time()
        budget = AgentBudget.from_env()
        should_use_tools = self._role == AgentRole.WORKER

        while True:
            exit_reason = budget.check()
            if exit_reason != ExitReason.WITHIN_BUDGET:
                stream_renderer.finish()
                stats = self._format_token_stats(budget.total_input_tokens,
                                                  budget.total_output_tokens, start_nanos)
                print(subtle(stats))
                desc = budget.describe_exit(exit_reason)
                logger.warning("[%s] budget exhausted: reason=%s", self._name, exit_reason)
                return AgentMessage.error(self._name, self._role, desc)

            budget.begin_iteration()

            try:
                response = self._llm.chat(
                    self._conversation_history,
                    self._tool_registry.get_tool_definitions() if should_use_tools else None,
                    stream_renderer,
                )
                budget.record_tokens(response.input_tokens or 0, response.output_tokens or 0)

                if response.has_tool_calls():
                    budget.record_tool_calls(response.tool_calls)
                    _print_sub_tool_calls(self._name, response.tool_calls)
                    self._conversation_history.append(Message.assistant(
                        response.reasoning_content, response.content, response.tool_calls
                    ))
                    stream_renderer.reset_between_iterations()
                    tool_results = self._execute_tool_calls(response.tool_calls)
                    for tr in tool_results:
                        self._conversation_history.append(Message.tool(tr.id, tr.result))
                    continue

                self._conversation_history.append(Message.assistant(
                    response.reasoning_content, response.content
                ))
                stream_renderer.finish()
                stats = self._format_token_stats(budget.total_input_tokens,
                                                  budget.total_output_tokens, start_nanos)
                print(subtle(stats))
                return AgentMessage.result(self._name, self._role, response.content or "")

            except Exception as e:
                logger.error("[%s] LLM call failed", self._name, exc_info=True)
                stream_renderer.finish()
                return AgentMessage.error(self._name, self._role, f"LLM 调用失败: {e}")

    def _execute_tool_calls(self, tool_calls: List[dict]) -> List:
        invocations = []
        for tc in tool_calls:
            func = tc.get("function", {})
            invocations.append(ToolInvocation(
                tc.get("id", ""), func.get("name", ""), func.get("arguments", "{}")
            ))
        return self._tool_registry.execute_tools(invocations)

    @staticmethod
    def _format_token_stats(input_tokens: int, output_tokens: int, start: float) -> str:
        elapsed = time.time() - start
        return subtle(
            f"📊 Token: {input_tokens} 输入 / {output_tokens} 输出 / "
            f"{input_tokens + output_tokens} 合计 | ⏱ {elapsed:.1f}s"
        )


def _print_sub_tool_calls(agent_name: str, tool_calls: List[dict]):
    grouped: Dict[str, list] = {}
    for tc in tool_calls:
        name = tc.get("function", {}).get("name", "")
        grouped.setdefault(name, []).append(tc)
    for tool_name, calls in grouped.items():
        label = _sub_tool_label(tool_name, len(calls))
        print(subtle(f"  [{agent_name}] {label}"))
        for tc in calls:
            detail = _extract_sub_key_param(tool_name, tc.get("function", {}).get("arguments", "{}"))
            if detail:
                print(subtle(f"    └ {detail}"))


def _sub_tool_label(name: str, count: int) -> str:
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


def _extract_sub_key_param(tool_name: str, args_json: str) -> str:
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


class _SubAgentStreamRenderer:
    def __init__(self, agent_name: str, role: AgentRole):
        self._agent_name = agent_name
        self._role = role
        self._pending_reasoning = ""
        self._late_reasoning = ""
        self._reasoning_started = False
        self._content_started = False
        self._streamed_output = False

    @property
    def _reasoning_label(self) -> str:
        return {
            AgentRole.PLANNER: "规划思考",
            AgentRole.WORKER: "执行思考",
            AgentRole.REVIEWER: "审查思考",
        }.get(self._role, "思考")

    @property
    def _content_label(self) -> str:
        return {
            AgentRole.PLANNER: "规划结果",
            AgentRole.WORKER: "执行输出",
            AgentRole.REVIEWER: "审查结果",
        }.get(self._role, "输出")

    def __call__(self, delta: str):
        if delta:
            self._on_content(delta)

    def on_reasoning_delta(self, delta: str):
        if not delta:
            return
        if self._content_started:
            self._late_reasoning += delta
            return
        if not self._reasoning_started:
            self._pending_reasoning += delta
            if not self._pending_reasoning.strip():
                return
            print(heading(f"🧠 {self._reasoning_label} [{self._agent_name}]"))
            print(self._pending_reasoning, end="", flush=True)
            self._pending_reasoning = ""
            self._reasoning_started = True
            self._streamed_output = True
        else:
            print(delta, end="", flush=True)

    def on_content_delta(self, delta: str):
        if not delta:
            return
        if not self._content_started:
            if self._pending_reasoning.strip():
                print(heading(f"🧠 {self._reasoning_label} [{self._agent_name}]"))
                print(self._pending_reasoning, end="", flush=True)
                print()
                self._pending_reasoning = ""
                self._reasoning_started = True
            print(section(f"🤖 {self._content_label} [{self._agent_name}]"))
            self._content_started = True
            self._streamed_output = True
        print(delta, end="", flush=True)

    def _on_content(self, delta: str):
        self.on_content_delta(delta)

    def reset_between_iterations(self):
        self._pending_reasoning = ""
        late = self._late_reasoning.strip()
        if late:
            print(f"\n{heading(f'🧠 补充思考 [{self._agent_name}]')}")
            print(late)
            self._late_reasoning = ""
            self._streamed_output = True
        self._reasoning_started = False
        self._content_started = False
        if self._streamed_output:
            print()

    def finish(self):
        late = self._late_reasoning.strip()
        if late:
            print(f"\n{heading(f'🧠 补充思考 [{self._agent_name}]')}")
            print(late)
            self._late_reasoning = ""
            self._streamed_output = True
        if self._streamed_output:
            print("\n")

    def has_streamed_output(self) -> bool:
        return self._streamed_output
