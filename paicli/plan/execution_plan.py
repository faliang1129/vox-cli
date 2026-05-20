"""执行计划 - 包含一组有依赖关系的任务"""

import time
from enum import Enum
from typing import List, Optional, Dict, Set
from collections import OrderedDict

from .task import Task, TaskStatus


class PlanStatus(Enum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ExecutionPlan:
    def __init__(self, id: str, goal: str):
        self._id = id
        self._goal = goal
        self._tasks: Dict[str, Task] = OrderedDict()
        self._execution_order: List[str] = []
        self._status = PlanStatus.CREATED
        self._summary: Optional[str] = None
        self._start_time: float = 0.0
        self._end_time: float = 0.0

    @property
    def id(self) -> str:
        return self._id

    @property
    def goal(self) -> str:
        return self._goal

    @property
    def status(self) -> PlanStatus:
        return self._status

    @property
    def summary(self) -> Optional[str]:
        return self._summary

    @summary.setter
    def summary(self, value: str):
        self._summary = value

    @property
    def start_time(self) -> float:
        return self._start_time

    @property
    def end_time(self) -> float:
        return self._end_time

    def add_task(self, task: Task):
        self._tasks[task.id] = task
        for dep_id in task.dependencies:
            dep = self._tasks.get(dep_id)
            if dep is not None:
                dep.add_dependent(task.id)

    def get_task(self, id: str) -> Optional[Task]:
        return self._tasks.get(id)

    def get_all_tasks(self) -> List[Task]:
        return list(self._tasks.values())

    def get_root_tasks(self) -> List[Task]:
        return [t for t in self._tasks.values() if not t.dependencies]

    def get_executable_tasks(self) -> List[Task]:
        return [t for t in self._tasks.values() if t.is_executable(self._tasks)]

    def compute_execution_order(self) -> bool:
        self._execution_order.clear()
        visited: Set[str] = set()
        visiting: Set[str] = set()

        def topo_sort(task: Task) -> bool:
            if task.id in visiting:
                return False
            if task.id in visited:
                return True
            visiting.add(task.id)
            for dep_id in task.dependencies:
                dep = self._tasks.get(dep_id)
                if dep is not None:
                    if not topo_sort(dep):
                        return False
            visiting.remove(task.id)
            visited.add(task.id)
            self._execution_order.append(task.id)
            return True

        for task in self._tasks.values():
            if task.id not in visited:
                if not topo_sort(task):
                    return False
        return True

    def get_execution_order(self) -> List[str]:
        if not self._execution_order:
            self.compute_execution_order()
        return list(self._execution_order)

    def get_progress(self) -> float:
        if not self._tasks:
            return 1.0
        completed = sum(1 for t in self._tasks.values()
                        if t.status == TaskStatus.COMPLETED)
        return completed / len(self._tasks)

    def is_all_completed(self) -> bool:
        return all(t.status == TaskStatus.COMPLETED
                   for t in self._tasks.values())

    def has_failed(self) -> bool:
        return any(t.status == TaskStatus.FAILED
                   for t in self._tasks.values())

    def mark_started(self):
        self._status = PlanStatus.RUNNING
        self._start_time = time.time()

    def mark_completed(self):
        self._status = PlanStatus.COMPLETED
        self._end_time = time.time()

    def mark_failed(self):
        self._status = PlanStatus.FAILED
        self._end_time = time.time()

    def mark_cancelled(self):
        self._status = PlanStatus.CANCELLED
        self._end_time = time.time()

    @property
    def duration(self) -> float:
        if self._start_time == 0:
            return 0.0
        if self._end_time == 0:
            return time.time() - self._start_time
        return self._end_time - self._start_time

    def visualize(self) -> str:
        lines = []
        lines.append("╔══════════════════════════════════════════════════════════╗")
        goal_display = self._goal[:46] + "..." if len(self._goal) > 46 else self._goal
        lines.append(f"║  执行计划: {goal_display:<46}║")
        lines.append("╠══════════════════════════════════════════════════════════╣")

        order = self.get_execution_order()
        for i, task_id in enumerate(order):
            task = self._tasks[task_id]
            icon = self._status_icon(task.status)
            deps = ",".join(task.dependencies) if task.dependencies else "无"
            lines.append(f"║  {i+1}. {icon} {task._id:<20} [{task.type.value:<10}] 依赖: {deps:<15}║")
            desc = task.description[:47] + "..." if len(task.description) > 50 else task.description
            lines.append(f"║     {desc:<53}║")

        lines.append("╚══════════════════════════════════════════════════════════╝")
        lines.append(f"   进度: {self.get_progress()*100:.0f}% | 状态: {self._status.value}")
        return "\n".join(lines)

    def summarize(self) -> str:
        batches = self.get_execution_batches()
        ready = self.get_executable_tasks()
        lines = ["📋 计划摘要",
                 f"   - 目标: {self._compact_goal(48)}",
                 f"   - 任务数: {len(self._tasks)} | 并行批次: {len(batches)} | "
                 f"当前可执行: {len(ready)} | 状态: {self._status.value}"]
        if batches:
            lines.append(f"   - 首批执行: {self._format_task_list(batches[0], 5)}")
            if len(batches) > 1:
                lines.append(f"   - 最终收敛: {self._format_task_list(batches[-1], 5)}")
        return "\n".join(lines)

    def get_execution_batches(self) -> List[List[Task]]:
        if not self._tasks:
            return []
        remaining = OrderedDict(self._tasks)
        completed: Set[str] = set()
        batches = []
        while remaining:
            batch = [t for t in remaining.values()
                     if completed.issuperset(t.dependencies)]
            if not batch:
                break
            batches.append(batch)
            for t in batch:
                remaining.pop(t.id)
                completed.add(t.id)
        return batches

    def _compact_goal(self, max_length: int) -> str:
        goal = self._goal.replace("\r\n", " ").replace("\r", " ").replace("\n", " ").strip()
        import re
        goal = re.sub(r" {2,}", " ", goal)
        if len(goal) <= max_length:
            return goal
        return goal[:max_length - 3] + "..."

    def _format_task_list(self, batch: List[Task], limit: int) -> str:
        if not batch:
            return "无"
        ids = [t.id for t in batch]
        if len(ids) <= limit:
            return ", ".join(ids)
        return ", ".join(ids[:limit]) + f" 等 {len(ids)} 个任务"

    @staticmethod
    def _status_icon(status: TaskStatus) -> str:
        return {
            TaskStatus.PENDING: "⏳",
            TaskStatus.RUNNING: "▶️",
            TaskStatus.COMPLETED: "✅",
            TaskStatus.FAILED: "❌",
            TaskStatus.SKIPPED: "⏭️",
        }.get(status, "⏳")

    def __repr__(self) -> str:
        return f"ExecutionPlan[{self._id}: {self._goal}] ({len(self._tasks)} tasks, {self._status.value})"
