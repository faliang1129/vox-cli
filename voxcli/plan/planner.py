"""规划器 - 使用LLM将复杂任务分解为执行计划"""

import json
import re
import time
import logging
from typing import List, Optional

from ..llm.base import LlmClient, Message
from .task import Task, TaskType
from .execution_plan import ExecutionPlan

logger = logging.getLogger(__name__)

_PLANNING_PROMPT = """你是一个任务规划专家。请将用户的复杂任务分解为一系列可执行的子任务。

可用任务类型：
- FILE_READ: 读取文件内容
- FILE_WRITE: 写入文件内容
- COMMAND: 执行Shell命令
- ANALYSIS: 分析结果并做出决策
- VERIFICATION: 验证结果是否正确

请按以下JSON格式输出执行计划：
{
    "summary": "任务摘要",
    "tasks": [
        {
            "id": "task_1",
            "description": "任务描述",
            "type": "FILE_READ",
            "dependencies": []
        },
        {
            "id": "task_2",
            "description": "任务描述",
            "type": "FILE_WRITE",
            "dependencies": ["task_1"]
        }
    ]
}

规则：
1. 每个任务必须有唯一的id（如 task_1, task_2）
2. dependencies列出依赖的任务id
3. 任务应该按执行顺序排列
4. 任务描述要具体明确
5. 简单任务（如列目录、读取单个文件、执行单条命令）允许只生成1-3个任务；不要为了凑步数引入无关步骤
6. 复杂任务再拆分为5-10个子任务
7. 不要为了"保存中间结果"而额外创建 FILE_WRITE / FILE_READ，除非用户明确要求落盘
8. 如果一个任务一步就能完成，就保持最短计划

只输出JSON，不要有其他内容。"""

_SIMPLE_GOAL_CUES = ["列出", "查看", "读取", "显示", "执行", "运行", "搜索", "当前目录", "文件"]
_MULTI_STEP_CUES = ["然后", "并且", "并", "再", "最后", "同时", "先", "之后", "接着", "以及"]


class Planner:
    def __init__(self, llm_client: LlmClient):
        self._llm = llm_client
        self._plan_id_counter = 0

    def create_plan(self, goal: str) -> ExecutionPlan:
        logger.info("Planning for goal: %s", goal)
        print(f"📋 正在规划任务: {goal}\n")

        if self._is_simple_goal(goal):
            return self._create_minimal_plan(goal)

        messages = [
            Message.system(_PLANNING_PROMPT),
            Message.user(f"请为以下任务制定执行计划：\n{goal}"),
        ]

        renderer = PlanningStreamRenderer()
        response = self._llm.chat(messages, listener=renderer)
        renderer.finish()
        plan_json = response.content or ""

        return self._parse_plan(goal, plan_json)

    def _parse_plan(self, goal: str, plan_json: str) -> ExecutionPlan:
        cleaned = re.sub(r"```(?:json)?\s*", "", plan_json).strip()
        root = json.loads(cleaned)

        summary = root.get("summary", "")
        tasks_node = root.get("tasks", [])

        plan = ExecutionPlan(self._generate_plan_id(), goal)
        plan.summary = summary

        id_mapping = {}
        for i, task_node in enumerate(tasks_node, 1):
            original_id = task_node.get("id", f"task_{i}")
            new_id = f"task_{i}"
            id_mapping[original_id] = new_id
            desc = task_node.get("description", "")
            task_type = self._parse_task_type(task_node.get("type", "ANALYSIS"))
            plan.add_task(Task(new_id, desc, task_type))

        for i, task_node in enumerate(tasks_node, 1):
            new_id = f"task_{i}"
            task = plan.get_task(new_id)
            if task is None:
                continue
            for dep in task_node.get("dependencies", []):
                mapped = id_mapping.get(dep, dep)
                dep_task = plan.get_task(mapped)
                if dep_task is not None:
                    task.add_dependency(mapped)
                    dep_task.add_dependent(task.id)

        if not plan.compute_execution_order():
            raise ValueError("计划中存在循环依赖")

        return plan

    @staticmethod
    def _parse_task_type(type_str: str) -> TaskType:
        mapping = {
            "FILE_READ": TaskType.FILE_READ,
            "FILE_WRITE": TaskType.FILE_WRITE,
            "COMMAND": TaskType.COMMAND,
            "ANALYSIS": TaskType.ANALYSIS,
            "VERIFICATION": TaskType.VERIFICATION,
        }
        return mapping.get(type_str.upper(), TaskType.ANALYSIS)

    def _generate_plan_id(self) -> str:
        self._plan_id_counter += 1
        return f"plan_{int(time.time())}_{self._plan_id_counter}"

    def replan(self, failed_plan: ExecutionPlan, failure_reason: str) -> ExecutionPlan:
        print(f"🔄 重新规划，原因: {failure_reason}\n")
        context_parts = [f"原任务: {failed_plan.goal}", f"失败原因: {failure_reason}",
                         "已完成的任务:"]
        for task in failed_plan.get_all_tasks():
            if task.status.value == "COMPLETED":
                context_parts.append(f"- {task.id}: {task.description}")
        context_parts.append("\n请制定新的执行计划，避开之前的问题。")
        return self.create_plan("\n".join(context_parts))

    @staticmethod
    def _is_simple_goal(goal: str) -> bool:
        if not goal or not goal.strip():
            return False
        normalized = goal.strip()
        if any(cue in normalized for cue in _MULTI_STEP_CUES):
            return False
        if len(normalized) > 30:
            return False
        return any(cue in normalized for cue in _SIMPLE_GOAL_CUES)

    def _create_minimal_plan(self, goal: str) -> ExecutionPlan:
        plan = ExecutionPlan(self._generate_plan_id(), goal)
        plan.summary = f"直接执行简单任务：{goal.strip()}"
        plan.add_task(Task("task_1", goal.strip(), self._infer_simple_task_type(goal)))
        if not plan.compute_execution_order():
            raise ValueError("简单计划不应出现循环依赖")
        return plan

    @staticmethod
    def _infer_simple_task_type(goal: str) -> TaskType:
        normalized = goal.strip()
        if "读取" in normalized or "打开" in normalized or ("查看" in normalized and "文件" in normalized):
            return TaskType.FILE_READ
        if "写入" in normalized or "修改" in normalized or "创建文件" in normalized:
            return TaskType.FILE_WRITE
        if "分析" in normalized or "总结" in normalized or "解释" in normalized:
            return TaskType.ANALYSIS
        if "验证" in normalized or "检查" in normalized:
            return TaskType.VERIFICATION
        return TaskType.COMMAND


class PlanningStreamRenderer:
    """规划流式渲染器 - 实现 StreamListener 协议"""
    def __init__(self):
        self._buffer = ""
        self._started = False

    def on_reasoning_delta(self, delta: str):
        if delta:
            if not self._started:
                print("🧠 规划思考")
                self._started = True
            print(delta, end="", flush=True)
            self._buffer += delta

    def on_content_delta(self, delta: str):
        if delta:
            print(delta, end="", flush=True)
            self._buffer += delta

    def finish(self):
        if self._started:
            print("\n")
