"""Plan-and-Execute Agent - 先规划后执行"""

import json
import time
import logging
from concurrent.futures import ThreadPoolExecutor, Future
from io import StringIO
from typing import List, Optional, Dict, Set, Callable
from enum import Enum

from ..config import VoxCodeConfig
from ..llm.base import LlmClient, Message, ToolCall
from ..memory.manager import MemoryManager
from ..plan import Planner, ExecutionPlan, PlanStatus, Task, TaskStatus, TaskType
from ..tool import ToolRegistry, ToolInvocation
from ..util.ansi import heading, section, subtle
from .agent_budget import AgentBudget

logger = logging.getLogger(__name__)

_MAX_TASK_ITERATIONS = 5

_EXECUTION_PROMPT = """你是一个任务执行专家。请根据当前任务和上下文，选择合适的工具或生成回复。

当前任务类型：%s
任务描述：%s

可用工具：
1. read_file - 读取文件内容，参数：{"path": "文件路径"}
2. write_file - 写入文件内容，参数：{"path": "文件路径", "content": "内容"}
3. list_dir - 列出目录内容，参数：{"path": "目录路径"}
4. execute_command - 执行命令，参数：{"command": "命令"}
5. create_project - 创建项目，参数：{"name": "名称", "type": "java|python|node"}
6. search_code - 语义检索代码库，参数：{"query": "自然语言描述", "top_k": 5}
7. web_search - 搜索互联网获取实时信息，参数：{"query": "搜索关键词", "top_k": 5}
8. web_fetch - 抓取已知 URL 并返回正文 Markdown，参数：{"url": "https://...", "max_chars": 8000}

如果任务涉及理解代码库（如分析代码结构、查找实现位置），请优先使用 search_code 工具。
如果任务需要实时互联网信息（如查询框架最新版本、官方文档），请使用 web_search 找入口，
拿到具体 URL 后用 web_fetch 抓取全文。已经有 URL 时直接 web_fetch，不要再 web_search 一次。
web_fetch 拿到空正文（SPA / 防爬墙）时，明确告知用户这是已知边界，不要反复重试。
对于当前项目内的文件，请优先使用 read_file 或 list_dir，不要用 execute_command 扫描 /、~ 或整个文件系统。
execute_command 只适合在当前项目目录执行短时命令。
安全策略硬规则（HITL 之外的兜底，无法绕过）：read_file / write_file / list_dir / create_project 必须在项目根之内；write_file 单文件 5MB 上限；
execute_command 禁止 sudo / rm -rf 全盘 / mkfs / dd of=/dev / fork bomb / curl|sh / find / / chmod 777 / / shutdown。
被策略拒绝的工具调用（"🛡️ 策略拒绝" 开头）不要原样重试，改用项目内相对路径或更安全的命令。
同一轮返回多个工具调用时，系统会并行执行这些工具；如果工具之间有依赖关系，请分多轮调用。
如果是 ANALYSIS 或 VERIFICATION 类型任务，请直接输出分析结果，不需要调用工具。

请用中文回复。"""


class PlanReviewAction(Enum):
    EXECUTE = "EXECUTE"
    SUPPLEMENT = "SUPPLEMENT"
    CANCEL = "CANCEL"


class PlanReviewDecision:
    def __init__(self, action: PlanReviewAction, feedback: Optional[str] = None):
        self.action = action
        self.feedback = feedback

    @staticmethod
    def execute() -> "PlanReviewDecision":
        return PlanReviewDecision(PlanReviewAction.EXECUTE)

    @staticmethod
    def supplement(feedback: str) -> "PlanReviewDecision":
        return PlanReviewDecision(PlanReviewAction.SUPPLEMENT, feedback)

    @staticmethod
    def cancel() -> "PlanReviewDecision":
        return PlanReviewDecision(PlanReviewAction.CANCEL)


class PlanReviewHandler:
    def review(self, goal: str, plan: ExecutionPlan) -> PlanReviewDecision:
        return PlanReviewDecision.execute()


class PlanExecuteAgent:
    def __init__(self, llm_client: LlmClient,
                 tool_registry: Optional[ToolRegistry] = None,
                 planner: Optional[Planner] = None,
                 memory_manager: Optional[MemoryManager] = None,
                 review_handler: Optional[PlanReviewHandler] = None):
        self._llm = llm_client
        self._tool_registry = tool_registry or ToolRegistry()
        self._planner = planner or Planner(llm_client)
        self._memory_manager = memory_manager or MemoryManager(
            llm_client,
            project_path=self._tool_registry.project_path,
            global_config_dir=VoxCodeConfig.config_dir(),
        )
        self._review_handler = review_handler or PlanReviewHandler()

    @property
    def memory_manager(self) -> MemoryManager:
        return self._memory_manager

    @property
    def tool_registry(self) -> ToolRegistry:
        return self._tool_registry

    # ---- Public API ----

    def run(self, user_input: str) -> str:
        logger.info("Plan run started: inputLength=%d", len(user_input) if user_input else 0)
        self._memory_manager.add_user_message(user_input)
        stream_state = _StreamState()

        try:
            outcome = self._run_with_plan(user_input, stream_state)
            if outcome.persist and outcome.result:
                self._memory_manager.add_assistant_message("[计划结果] " + outcome.result)
            if stream_state.has_streamed and (not outcome.result):
                return ""
            return outcome.result or ""
        except Exception as e:
            logger.error("Plan run failed", exc_info=True)
            msg = f"❌ 执行失败: {e}"
            self._memory_manager.add_assistant_message(msg)
            return msg

    # ---- Internal ----

    def _run_with_plan(self, goal: str, stream_state: "_StreamState"):
        plan = self._planner.create_plan(goal)
        return self._review_and_execute(plan, stream_state)

    def _review_and_execute(self, plan: ExecutionPlan, stream_state: "_StreamState"):
        while True:
            decision = self._review_handler.review(plan.goal, plan)
            if decision is None or decision.action == PlanReviewAction.EXECUTE:
                return _PlanOutcome.executed(self._execute_plan(plan, stream_state))
            if decision.action == PlanReviewAction.CANCEL:
                return _PlanOutcome.canceled("⏹️ 已取消本次计划执行。")
            feedback = (decision.feedback or "").strip()
            if not feedback:
                return _PlanOutcome.executed(self._execute_plan(plan, stream_state))
            print("📝 已收到补充要求，正在重新规划...\n")
            plan = self._planner.create_plan(f"{plan.goal}\n补充要求：{feedback}")

    def _execute_plan(self, plan: ExecutionPlan, stream_state: "_StreamState") -> str:
        logger.info("Executing plan: goal='%s', taskCount=%d", plan.goal, len(plan.get_all_tasks()))
        print("🚀 开始执行计划...\n")
        plan.mark_started()

        final_result_parts = []
        streamed_outputs: Dict[str, bool] = {}

        while True:
            executable = self._get_executable_in_order(plan)
            if not executable:
                break

            batch_results = self._execute_task_batch(plan, executable, stream_state)
            for br in batch_results:
                task = br.task
                if not br.failed:
                    task.mark_completed(br.result or "")
                    streamed_outputs[task.id] = br.streamed
                    logger.info("Task completed: %s status=%s resultChars=%d",
                                task.id, task.status, len(br.result or ""))
                    if br.streamed or not br.result:
                        print(f"✅ 完成 [{task.id}]\n")
                    else:
                        preview = br.result[:100] if len(br.result) > 100 else br.result
                        print(f"✅ 完成 [{task.id}]: {preview}\n")
                else:
                    err_msg = str(br.error) if br.error else "未知错误"
                    task.mark_failed(err_msg)
                    logger.warning("Task failed: %s error=%s", task.id, err_msg)
                    print(f"❌ 失败 [{task.id}]: {err_msg}\n")
                    if plan.get_progress() < 0.5:
                        print("🔄 尝试重新规划...\n")
                        replanned = self._planner.replan(plan, err_msg)
                        return self._review_and_execute(replanned, stream_state).result or ""
                    final_result_parts.append(f"任务 {task.id} 失败: {err_msg}")

        if not plan.is_all_completed() and not plan.has_failed():
            plan.mark_failed()
            return "⚠️ 计划未能继续推进，存在未满足依赖的任务。"

        summary = "\n".join(final_result_parts) if final_result_parts else \
            self._build_final_result(plan, streamed_outputs)

        if plan.has_failed():
            plan.mark_failed()
            return f"⚠️ 计划部分完成，有任务失败。\n{summary}" if summary else "⚠️ 计划部分完成，有任务失败。"

        plan.mark_completed()
        return f"✅ 计划执行完成！\n{summary}" if summary else "✅ 计划执行完成！"

    def _get_executable_in_order(self, plan: ExecutionPlan) -> List[Task]:
        executable_ids = {t.id for t in plan.get_executable_tasks()}
        return [plan.get_task(tid) for tid in plan.get_execution_order()
                if tid in executable_ids and plan.get_task(tid) is not None]

    def _execute_task_batch(self, plan: ExecutionPlan, tasks: List[Task],
                            stream_state: "_StreamState") -> List["_TaskExecResult"]:
        if len(tasks) == 1:
            task = tasks[0]
            logger.info("Executing single task: %s type=%s", task.id, task.type.value)
            print(f"▶️ 执行任务 [{task.id}]: {task.description}")
            task.mark_started()
            try:
                result = self._execute_single_task(plan.goal, plan, task, stream_state)
                return [_TaskExecResult.success(task, result)]
            except Exception as e:
                return [_TaskExecResult.failure(task, e)]

        ids = ", ".join(t.id for t in tasks)
        logger.info("Executing parallel batch: %s", ids)
        print(f"⚡ 本轮并行执行 {len(tasks)} 个任务: {ids}")

        parallelism = min(len(tasks), 4)
        results: List[Optional[_TaskExecResult]] = [None] * len(tasks)

        with ThreadPoolExecutor(max_workers=parallelism) as executor:
            future_map = {}
            for i, task in enumerate(tasks):
                print(f"▶️ 并行任务 [{task.id}]: {task.description}")
                task.mark_started()
                buf = StringIO()
                future = executor.submit(self._execute_single_task, plan.goal, plan, task, stream_state)
                future_map[future] = i

            for future in future_map:
                idx = future_map[future]
                task = tasks[idx]
                try:
                    result = future.result()
                    results[idx] = _TaskExecResult.success(task, result)
                except Exception as e:
                    results[idx] = _TaskExecResult.failure(task, e)

        return [r for r in results if r is not None]

    def _execute_single_task(self, goal: str, plan: ExecutionPlan, task: Task,
                             stream_state: "_StreamState"):
        prompt = _EXECUTION_PROMPT % (task.type.value, task.description)
        memory_context = self._memory_manager.build_context_for_query(task.description, 300)
        task_input = self._build_task_context(goal, plan, task)
        if memory_context:
            task_input += f"\n\n{memory_context}"

        messages = [
            Message.system(prompt),
            Message.user(task_input),
        ]

        all_results = []
        renderer = _TaskStreamRenderer(task.id, stream_state)
        total_input = 0
        total_output = 0
        start = time.time()

        for iteration in range(_MAX_TASK_ITERATIONS):
            response = self._llm.chat(
                messages,
                self._tool_registry.get_tool_definitions(),
                renderer,
            )
            total_input += response.input_tokens or 0
            total_output += response.output_tokens or 0

            logger.info("Task %s iteration %d: toolCalls=%d, reasoningChars=%d, contentChars=%d",
                        task.id, iteration + 1,
                        len(response.tool_calls) if response.tool_calls else 0,
                        len(response.reasoning_content or ""), len(response.content or ""))

            if not response.has_tool_calls():
                self._memory_manager.record_token_usage(total_input, total_output)
                if response.content:
                    self._memory_manager.add_assistant_message(
                        f"[计划任务 {task.id}] {response.content}")
                renderer.finish()
                stats = subtle(
                    f"📊 Token: {total_input} 输入 / {total_output} 输出 / "
                    f"{total_input + total_output} 合计 | ⏱ {time.time() - start:.1f}s")
                print(stats)
                return _TaskRunResult(response.content or "", renderer.has_streamed_output)

            all_results.append(response.content or "")
            _print_task_tool_calls(task.id, response.tool_calls)
            messages.append(Message.assistant(
                content=response.content or "",
                reasoning_content=response.reasoning_content,
                tool_calls=response.tool_calls,
            ))
            renderer.reset_between_iterations()

            tool_results = self._execute_task_tool_calls(task.id, response.tool_calls)
            for tr in tool_results:
                self._memory_manager.add_tool_result(tr.name, tr.result)
                all_results.append(tr.result)
                messages.append(Message.tool(tr.id, tr.result))

        fallback = "\n".join(r for r in all_results if r).strip()
        if fallback:
            self._memory_manager.add_assistant_message(f"[计划任务 {task.id}] {fallback}")
        renderer.finish()
        stats = subtle(
            f"📊 Token: {total_input} 输入 / {total_output} 输出 / "
            f"{total_input + total_output} 合计 | ⏱ {time.time() - start:.1f}s")
        print(stats)
        return _TaskRunResult(fallback, renderer.has_streamed_output)

    def _execute_task_tool_calls(self, task_id: str, tool_calls: List[dict]) -> List:
        invocations = []
        for tc in tool_calls:
            func = tc.get("function", {})
            invocations.append(ToolInvocation(
                tc.get("id", ""), func.get("name", ""), func.get("arguments", "{}")
            ))
        if len(invocations) > 1:
            logger.info("Task %s executing %d tool calls in parallel", task_id, len(invocations))
        return self._tool_registry.execute_tools(invocations)

    @staticmethod
    def _build_task_context(goal: str, plan: ExecutionPlan, task: Task) -> str:
        parts = [f"总目标：{goal}", f"当前任务：{task.description}"]
        if not task.dependencies:
            parts.append("依赖任务：无")
        else:
            parts.append("依赖任务结果：")
            for dep_id in task.dependencies:
                dep = plan.get_task(dep_id)
                if dep is None:
                    continue
                parts.append(f"- {dep.id} / {dep.description} / 状态={dep.status.value}")
                if dep.result:
                    parts.append(dep.result)
        parts.append("请执行此任务。如果是 ANALYSIS 或 VERIFICATION 类型，请基于以上上下文直接给出结果。")
        return "\n".join(parts)

    @staticmethod
    def _build_final_result(plan: ExecutionPlan, streamed: Dict[str, bool]) -> str:
        leaf_tasks = [t for t in plan.get_all_tasks() if not t.dependents]

        results = []
        for t in leaf_tasks:
            if streamed.get(t.id):
                continue
            if t.result:
                results.append(f"[{t.id}] {t.result}")

        if results:
            return "\n".join(results)

        for t in plan.get_all_tasks():
            if not streamed.get(t.id) and t.result:
                results.append(f"[{t.id}] {t.result}")

        return results[-1] if results else ""


class _StreamState:
    def __init__(self):
        self.has_streamed = False

    def mark(self):
        self.has_streamed = True


class _PlanOutcome:
    def __init__(self, result: Optional[str], persist: bool):
        self.result = result
        self.persist = persist

    @staticmethod
    def executed(result: str) -> "_PlanOutcome":
        return _PlanOutcome(result, True)

    @staticmethod
    def canceled(result: str) -> "_PlanOutcome":
        return _PlanOutcome(result, False)

    @staticmethod
    def failed(result: str) -> "_PlanOutcome":
        return _PlanOutcome(result, True)


class _TaskRunResult:
    def __init__(self, result: str, streamed: bool):
        self.result = result
        self.streamed = streamed

    @staticmethod
    def of(result: str, streamed: bool) -> "_TaskRunResult":
        return _TaskRunResult(result, streamed)


class _TaskExecResult:
    def __init__(self, task: Task, result: Optional[str] = None,
                 streamed: bool = False, error: Optional[Exception] = None):
        self.task = task
        self.result = result
        self.streamed = streamed
        self.error = error

    @property
    def failed(self) -> bool:
        return self.error is not None

    @staticmethod
    def success(task: Task, run_result: _TaskRunResult) -> "_TaskExecResult":
        return _TaskExecResult(task, run_result.result, run_result.streamed, None)

    @staticmethod
    def failure(task: Task, error: Exception) -> "_TaskExecResult":
        return _TaskExecResult(task, None, False, error)


class _TaskStreamRenderer:
    def __init__(self, task_id: str, stream_state: _StreamState):
        self._task_id = task_id
        self._stream_state = stream_state
        self._pending = ""
        self._late = ""
        self._reasoning_started = False
        self._content_started = False
        self._has_streamed = False

    @property
    def has_streamed_output(self) -> bool:
        return self._has_streamed

    def __call__(self, delta: str):
        if delta:
            self._on_content(delta)

    def on_reasoning_delta(self, delta: str):
        if not delta:
            return
        if self._content_started:
            self._late += delta
            return
        if not self._reasoning_started:
            self._pending += delta
            if not self._pending.strip():
                return
            print(heading(f"🧠 任务思考 [{self._task_id}]"))
            print(self._pending, end="", flush=True)
            self._pending = ""
            self._reasoning_started = True
            self._has_streamed = True
            self._stream_state.mark()
        else:
            print(delta, end="", flush=True)

    def on_content_delta(self, delta: str):
        if not delta:
            return
        if not self._content_started:
            if self._pending.strip():
                print(heading(f"🧠 任务思考 [{self._task_id}]"))
                print(self._pending, end="", flush=True)
                print()
                self._pending = ""
                self._reasoning_started = True
            print(section(f"🤖 任务输出 [{self._task_id}]"))
            self._content_started = True
            self._has_streamed = True
            self._stream_state.mark()
        print(delta, end="", flush=True)

    def _on_content(self, delta: str):
        self.on_content_delta(delta)

    def reset_between_iterations(self):
        self._pending = ""
        self._flush_late()
        self._reasoning_started = False
        self._content_started = False
        if self._has_streamed:
            print()

    def finish(self):
        if self._has_streamed:
            self._flush_late()
            print("\n")

    def _flush_late(self):
        late = self._late.strip()
        if late:
            print(f"\n{heading(f'🧠 补充思考 [{self._task_id}]')}")
            print(late)
            self._late = ""

    def has_streamed_output(self) -> bool:
        return self._has_streamed


def _print_task_tool_calls(task_id: str, tool_calls: List[dict]):
    for tc in tool_calls:
        name = tc.get("function", {}).get("name", "")
        args = tc.get("function", {}).get("arguments", "{}")
        detail = _extract_task_param(name, args)
        print(subtle(f"  [{task_id}] 🔧 {name}: {detail}"))


def _extract_task_param(tool_name: str, args_json: str) -> str:
    try:
        args = json.loads(args_json)
        key_map = {
            "read_file": "path", "write_file": "path", "list_dir": "path",
            "execute_command": "command", "create_project": "name",
            "search_code": "query", "web_search": "query", "web_fetch": "url",
        }
        key = key_map.get(tool_name)
        if key and key in args:
            val = str(args[key])
            return val if len(val) <= 60 else val[:57] + "..."
        return str(args)[:60]
    except json.JSONDecodeError:
        return args_json[:60]
