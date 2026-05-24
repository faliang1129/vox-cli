"""Agent 编排器 - Multi-Agent 系统的主控"""

import json
import time
import logging
from concurrent.futures import ThreadPoolExecutor, Future
from enum import Enum
from io import StringIO
from typing import List, Optional, Dict, Set
from dataclasses import dataclass, field

from ..config import VoxCodeConfig
from ..llm.base import LlmClient, Message
from ..memory.manager import MemoryManager
from ..tool import ToolRegistry
from ..util.ansi import heading, section, subtle
from .roles import AgentRole, AgentMessage, AgentMessageType
from .sub_agent import SubAgent

logger = logging.getLogger(__name__)

_MAX_RETRIES_PER_STEP = 2


class StepStatus(Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass
class ExecutionStep:
    id: str
    description: str
    type: str
    dependencies: List[str] = field(default_factory=list)
    result: Optional[str] = None
    status: StepStatus = StepStatus.PENDING

    @staticmethod
    def pending(id: str, description: str, type: str,
                dependencies: List[str]) -> "ExecutionStep":
        return ExecutionStep(id=id, description=description, type=type,
                             dependencies=dependencies)

    def with_result(self, result: str) -> "ExecutionStep":
        return ExecutionStep(self.id, self.description, self.type,
                             self.dependencies, result, StepStatus.COMPLETED)

    def with_failed(self, error: str) -> "ExecutionStep":
        return ExecutionStep(self.id, self.description, self.type,
                             self.dependencies, error, StepStatus.FAILED)

    def started(self) -> "ExecutionStep":
        return ExecutionStep(self.id, self.description, self.type,
                             self.dependencies, self.result, StepStatus.RUNNING)


class AgentOrchestrator:
    def __init__(self, llm_client: LlmClient,
                 tool_registry: Optional[ToolRegistry] = None,
                 memory_manager: Optional[MemoryManager] = None):
        self._llm = llm_client
        self._tool_registry = tool_registry or ToolRegistry()
        self._planner = SubAgent("planner", AgentRole.PLANNER, llm_client, self._tool_registry)
        self._workers = [
            SubAgent("worker-1", AgentRole.WORKER, llm_client, self._tool_registry),
            SubAgent("worker-2", AgentRole.WORKER, llm_client, self._tool_registry),
        ]
        self._reviewer = SubAgent("reviewer", AgentRole.REVIEWER, llm_client, self._tool_registry)
        self._memory_manager = memory_manager or MemoryManager(
            llm_client,
            project_path=self._tool_registry.project_path,
            global_config_dir=VoxCodeConfig.config_dir(),
        )

    @property
    def memory_manager(self) -> MemoryManager:
        return self._memory_manager

    @property
    def tool_registry(self) -> ToolRegistry:
        return self._tool_registry

    # ---- Public API ----

    def run(self, user_input: str) -> str:
        logger.info("Multi-Agent run started: inputLength=%d", len(user_input) if user_input else 0)
        self._memory_manager.add_user_message(user_input)

        # 1. Planning phase
        print(heading("📋 第一阶段：规划"))
        print("🧑‍💼 规划者正在分析任务...\n")

        plan_msg = AgentMessage.task("orchestrator",
                                      f"请为以下任务制定执行计划：\n{user_input}")
        plan_result = self._planner.execute(plan_msg)
        self._planner.clear_history()

        if plan_result.type == AgentMessageType.ERROR:
            return f"❌ 规划阶段失败，规划者 LLM 调用出错：{plan_result.content}"
        if not plan_result.content or not plan_result.content.strip():
            return "❌ 规划失败：规划者未能生成有效计划"

        # 2. Parse plan
        steps = self._parse_plan(plan_result.content)
        if not steps:
            return f"❌ 规划失败：无法解析执行计划\n原始输出:\n{plan_result.content}"

        print(heading("📋 执行计划"))
        print(self._summarize_steps(steps) + "\n")

        # 3. Execution phase
        print(heading("⚡ 第二阶段：执行"))
        retry_count: Dict[str, int] = {}
        single_step_cursor = 0
        batch_index = 0

        while True:
            executable = self._get_executable_steps(steps)
            if not executable:
                break
            batch_index += 1

            if len(executable) == 1:
                step = executable[0]
                worker = self._workers[single_step_cursor % len(self._workers)]
                single_step_cursor += 1
                context = self._build_step_context(steps, step)
                self._run_step(step, steps, retry_count, worker, self._reviewer, context)
                worker.clear_history()
            else:
                print(f"⚡ 批次 #{batch_index}：{len(executable)} 个独立步骤并行执行"
                      f"（最多 {len(self._workers)} 个并发 Worker）\n")
                self._run_batch_parallel(executable, steps, retry_count)

        # 4. Report skipped steps
        for step in steps:
            if step.status == StepStatus.PENDING:
                print(f"⏭️ 步骤 [{step.id}] 因前置步骤失败被跳过: {step.description}")

        # 5. Build result
        final = self._build_final_result(steps)
        self._memory_manager.add_assistant_message(f"[多Agent结果] {final}")
        return final

    # ---- Internal ----

    def _parse_plan(self, plan_json: str) -> List[ExecutionStep]:
        try:
            cleaned = plan_json.replace("```json", "").replace("```", "").strip()
            root = json.loads(cleaned)
            steps_node = root.get("steps") or root.get("tasks")
            if not steps_node or not isinstance(steps_node, list):
                logger.warning("Plan JSON has no 'steps' or 'tasks' array")
                return []

            id_mapping: Dict[str, str] = {}
            steps: List[ExecutionStep] = []

            for i, node in enumerate(steps_node, 1):
                orig = node.get("id", f"step_{i}")
                new_id = f"step_{i}"
                id_mapping[orig] = new_id

            for i, node in enumerate(steps_node, 1):
                new_id = f"step_{i}"
                desc = node.get("description", "")
                type_ = node.get("type", "COMMAND")
                deps = [id_mapping.get(d, d) for d in node.get("dependencies", [])]
                steps.append(ExecutionStep.pending(new_id, desc, type_, deps))

            return steps
        except Exception as e:
            logger.error("Failed to parse plan JSON", exc_info=True)
            return []

    def _get_executable_steps(self, steps: List[ExecutionStep]) -> List[ExecutionStep]:
        status_map = {s.id: s.status for s in steps}
        return [s for s in steps
                if s.status == StepStatus.PENDING
                and all(status_map.get(d) == StepStatus.COMPLETED for d in s.dependencies)]

    def _parse_review_approval(self, review_content: Optional[str]) -> bool:
        if not review_content:
            return False
        try:
            cleaned = review_content.replace("```json", "").replace("```", "").strip()
            root = json.loads(cleaned)
            approved = root.get("approved")
            if approved is None:
                return False
            return bool(approved)
        except json.JSONDecodeError:
            lower = review_content.lower()
            has_negative = any(kw in lower for kw in
                               ["未通过", "不通过", "不合格", "有问题",
                                '"approved": false', '"approved":false'])
            has_positive = any(kw in lower for kw in
                               ["通过", "合格", '"approved": true', '"approved":true'])
            if has_negative:
                return False
            if not has_positive:
                return False
            return True

    def _parse_review_issues(self, review_content: Optional[str]) -> str:
        if not review_content:
            return "审查未通过，请改进执行结果"
        try:
            cleaned = review_content.replace("```json", "").replace("```", "").strip()
            root = json.loads(cleaned)
            issues = root.get("issues", [])
            if issues:
                return "\n".join(f"- {i}" for i in issues)
            suggestions = root.get("suggestions", [])
            if suggestions:
                return "\n".join(f"- {s}" for s in suggestions)
            summary = root.get("summary", "")
            if summary:
                return summary
        except (json.JSONDecodeError, Exception):
            pass
        return "审查未通过，请改进执行结果"

    def _run_step(self, step: ExecutionStep, steps: List[ExecutionStep],
                  retry_count: Dict[str, int], worker: SubAgent,
                  reviewer: SubAgent, context: str):
        print(f"🛠️ {worker.name} 执行步骤 [{step.id}]: {step.description}")

        task_msg = AgentMessage.task("orchestrator", step.description)
        result = worker.execute_with_context(task_msg, context)

        if result.type == AgentMessageType.ERROR:
            self._update_step(steps, step.id, step.with_failed(result.content))
            print(f"❌ 步骤 [{step.id}] 执行失败：{result.content}\n")
            return

        if not result.content or not result.content.strip():
            self._update_step(steps, step.id, step.with_failed("执行结果为空"))
            print(f"❌ 步骤 [{step.id}] 执行失败：结果为空\n")
            return

        print(f"🔍 {reviewer.name} 正在审查步骤 [{step.id}] 的结果...")
        review_result = reviewer.review(step.description, result.content)
        reviewer.clear_history()

        if review_result.type == AgentMessageType.ERROR:
            logger.warning("Reviewer failed for step %s: %s", step.id, review_result.content)
            self._update_step(steps, step.id, step.with_result(result.content))
            return

        approved = self._parse_review_approval(review_result.content)
        accepted = result.content

        if approved:
            self._update_step(steps, step.id, step.with_result(accepted))
            print(f"✅ 步骤 [{step.id}] 审查通过\n")
            return

        retries = retry_count.get(step.id, 0)
        issues = self._parse_review_issues(review_result.content)
        logger.info("Step %s rejected (retry %d/%d): %s", step.id, retries, _MAX_RETRIES_PER_STEP, issues)

        while not approved and retries < _MAX_RETRIES_PER_STEP:
            retries += 1
            retry_count[step.id] = retries
            print(f"⚠️ 步骤 [{step.id}] 审查未通过，正在重新执行...")
            print(f"   反馈: {issues}\n")

            feedback_context = f"{context}\n\n之前的执行结果被审查拒绝，原因：\n{issues}"
            retry_result = worker.execute_with_context(task_msg, feedback_context)

            if retry_result.type == AgentMessageType.ERROR:
                issues = f"重试时 LLM 调用失败：{retry_result.content}"
                approved = False
                continue
            if not retry_result.content or not retry_result.content.strip():
                accepted = "执行结果为空"
                approved = False
                issues = "执行结果为空"
                continue

            accepted = retry_result.content
            retry_review = reviewer.review(step.description, accepted)
            reviewer.clear_history()

            if retry_review.type == AgentMessageType.ERROR:
                approved = True
                issues = ""
                break

            approved = self._parse_review_approval(retry_review.content)
            issues = self._parse_review_issues(retry_review.content)

        self._update_step(steps, step.id, step.with_result(accepted))
        status = "✅" if approved else "⚠️"
        msg = "重试后审查通过" if approved else "超过最大重试次数，保留当前结果"
        print(f"{status} 步骤 [{step.id}] {msg}\n")

    def _run_batch_parallel(self, batch: List[ExecutionStep], steps: List[ExecutionStep],
                            retry_count: Dict[str, int]):
        parallelism = min(len(batch), len(self._workers))
        results: List[Optional[ExecutionStep]] = [None] * len(batch)

        with ThreadPoolExecutor(max_workers=parallelism) as executor:
            future_map: Dict[Future, int] = {}
            for i, step in enumerate(batch):
                future = executor.submit(self._run_step_isolated, step, steps, retry_count)
                future_map[future] = i

            for future in future_map:
                idx = future_map[future]
                try:
                    results[idx] = future.result()
                except Exception as e:
                    step = batch[idx]
                    logger.error("Parallel step %s failed", step.id, exc_info=True)
                    results[idx] = step.with_failed(str(e))

        for i, step in enumerate(batch):
            if results[i] is not None:
                self._update_step(steps, step.id, results[i])

    def _run_step_isolated(self, step: ExecutionStep, steps: List[ExecutionStep],
                           retry_count: Dict[str, int]) -> Optional[ExecutionStep]:
        worker_pool = list(self._workers)
        worker = worker_pool[0]
        local_reviewer = SubAgent(f"reviewer-{step.id}", AgentRole.REVIEWER,
                                   self._llm, self._tool_registry)
        context = self._build_step_context(steps, step)

        buf = StringIO()
        # We use print capture but here we simulate the same flow
        task_msg = AgentMessage.task("orchestrator", step.description)
        result = worker.execute_with_context(task_msg, context)

        if result.type == AgentMessageType.ERROR:
            return step.with_failed(result.content)
        if not result.content or not result.content.strip():
            return step.with_failed("执行结果为空")

        review_result = local_reviewer.review(step.description, result.content)
        approved = self._parse_review_approval(review_result.content)

        if approved:
            return step.with_result(result.content)

        # Retries
        retries = 0
        issues = self._parse_review_issues(review_result.content)
        accepted = result.content

        while not approved and retries < _MAX_RETRIES_PER_STEP:
            retries += 1
            feedback_context = f"{context}\n\n之前的执行结果被审查拒绝，原因：\n{issues}"
            retry_result = worker.execute_with_context(task_msg, feedback_context)
            if retry_result.type == AgentMessageType.ERROR:
                break
            if not retry_result.content or not retry_result.content.strip():
                break
            accepted = retry_result.content
            retry_review = local_reviewer.review(step.description, accepted)
            approved = self._parse_review_approval(retry_review.content)
            issues = self._parse_review_issues(retry_review.content)

        return step.with_result(accepted)

    def _build_step_context(self, steps: List[ExecutionStep], current: ExecutionStep) -> str:
        parts = ["总任务上下文："]
        for step in steps:
            if step.status == StepStatus.COMPLETED and current.id in step.dependencies:
                parts.append(f"已完成的依赖步骤 [{step.id}]: {step.description}")
                if step.result:
                    preview = step.result[:500] if len(step.result) > 500 else step.result
                    parts.append(f"结果：{preview}")
                parts.append("")
        return "\n".join(parts)

    @staticmethod
    def _summarize_steps(steps: List[ExecutionStep]) -> str:
        lines = []
        for s in steps:
            deps = ", ".join(s.dependencies) if s.dependencies else "无"
            icon = "✅" if s.status == StepStatus.COMPLETED else "⏳"
            lines.append(f"  {icon} {s.id} [{s.type}] {s.description} (依赖: {deps})")
        return "\n".join(lines)

    @staticmethod
    def _update_step(steps: List[ExecutionStep], step_id: str, updated: ExecutionStep):
        for i, s in enumerate(steps):
            if s.id == step_id:
                steps[i] = updated
                return

    @staticmethod
    def _build_final_result(steps: List[ExecutionStep]) -> str:
        all_done = all(s.status == StepStatus.COMPLETED for s in steps)
        has_failure = any(s.status == StepStatus.FAILED for s in steps)

        lines = []
        if all_done:
            lines.append("✅ 多 Agent 协作任务完成！")
        elif has_failure:
            lines.append("⚠️ 多 Agent 协作任务未完全完成，存在失败步骤。")
        else:
            lines.append("⚠️ 多 Agent 协作任务部分完成，仍有未执行步骤。")

        lines.append("\n📋 执行总结：")
        for s in steps:
            icon = {"COMPLETED": "✅", "FAILED": "❌", "RUNNING": "▶️", "PENDING": "⏳"}.get(
                s.status.value, "⏳")
            lines.append(f"[{s.id}] {icon} {s.description}")
            if s.result:
                preview = s.result[:120] if len(s.result) > 120 else s.result
                lines.append(f"   结果：{preview}")

        return "\n".join(lines)
